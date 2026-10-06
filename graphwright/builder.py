"""Build a knowledge graph from a Python source tree with the standard library.

The builder is deliberately conservative: it records an edge only when the
target can be resolved to a known node, so the graph never contains invented
relationships. Unresolved call sites are counted, not guessed.
"""

from __future__ import annotations

import ast
import os

from . import model as M

SKIP_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", ".venv", "venv", "env", "node_modules",
    ".tox", ".nox", ".mypy_cache", ".pytest_cache", ".ruff_cache", "build", "dist",
    ".eggs", "site-packages",
}

_COMPOUND = (ast.If, ast.With, ast.AsyncWith, ast.For, ast.AsyncFor, ast.While, ast.Try)


def iter_python_files(root):
    """Yield every ``.py`` file under *root* in a deterministic order."""
    root = os.path.abspath(root)
    if os.path.isfile(root):
        if root.endswith(".py"):
            yield root
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(filenames):
            if name.endswith(".py"):
                yield os.path.join(dirpath, name)


def module_name(root, path, fallback="__root__"):
    """Derive a dotted module name from a file path relative to *root*.

    A package's top-level ``__init__.py`` maps to the package name itself (the
    *fallback* label) rather than to an empty string.
    """
    root = os.path.abspath(root)
    base = root if os.path.isdir(root) else os.path.dirname(root)
    rel = os.path.relpath(os.path.abspath(path), base).replace(os.sep, "/")
    if rel.endswith(".py"):
        rel = rel[:-3]
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) or fallback


def _first_doc(node):
    """Return the first line of a docstring, trimmed to a safe width."""
    doc = ast.get_docstring(node, clean=True) or ""
    line = doc.strip().splitlines()[0].strip() if doc.strip() else ""
    return line[:140]


def _dotted(node):
    """Return the dotted name of a Name/Attribute chain, else an empty string."""
    parts = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return ""


class Builder:
    """Turn a directory of Python files into a :class:`graphwright.model.Graph`."""

    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.base = self.root if os.path.isdir(self.root) else os.path.dirname(self.root)
        label = os.path.basename(self.root.rstrip(os.sep)) or self.root
        self.graph = M.Graph(root=label)
        self.trees = {}
        self.relpath = {}
        self.scope_names = {}
        self.imports = {}

    # -- orchestration ----------------------------------------------------
    def build(self):
        for path in iter_python_files(self.root):
            qname = module_name(self.root, path, self.graph.root)
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as handle:
                    tree = ast.parse(handle.read(), filename=path)
            except (OSError, SyntaxError) as exc:
                rel = os.path.relpath(path, self.base).replace(os.sep, "/")
                self.graph.warnings.append("%s: %s" % (rel, exc.__class__.__name__))
                continue
            rel = os.path.relpath(path, self.base).replace(os.sep, "/")
            self.trees[qname] = tree
            self.relpath[qname] = rel
            self.graph.add_node(M.Node(qname, M.MODULE, file=rel, line=1,
                                       name=qname.rpartition(".")[2], doc=_first_doc(tree)))
        if not self.trees:
            self.graph.warnings.append("no Python files found under %s" % self.root)
            return self.graph.finalize()
        for qname in sorted(self.trees):
            self._collect(qname, self.trees[qname])
        for qname in sorted(self.trees):
            self._relations(qname, self.trees[qname])
        return self.graph.finalize()

    # -- pass 1: definitions ---------------------------------------------
    def _collect(self, module_qname, tree):
        self.scope_names.setdefault(module_qname, {})
        self._walk_body(tree.body, module_qname, module_qname)

    def _walk_body(self, body, scope, module_qname):
        for node in body:
            if isinstance(node, ast.ClassDef):
                qname = self._add_def(scope, M.CLASS, node, module_qname)
                self._walk_body(node.body, qname, module_qname)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qname = self._add_def(scope, M.FUNCTION, node, module_qname)
                self._walk_body(node.body, qname, module_qname)
            elif isinstance(node, _COMPOUND):
                for sub in self._sub_bodies(node):
                    self._walk_body(sub, scope, module_qname)

    def _add_def(self, scope, kind, node, module_qname):
        qname = "%s.%s" % (scope, node.name)
        rel = self.relpath[module_qname]
        self.graph.add_node(M.Node(qname, kind, file=rel, line=node.lineno,
                                   name=node.name, doc=_first_doc(node)))
        self.scope_names.setdefault(scope, {})[node.name] = qname
        self.graph.add_edge(scope, qname, M.DEFINES, "defined at %s:%d" % (rel, node.lineno))
        return qname

    # -- pass 2: relationships -------------------------------------------
    def _relations(self, module_qname, tree):
        aliases = self._imports(module_qname, tree)
        self._scope_relations(module_qname, tree.body, module_qname, aliases)

    def _scope_relations(self, module_qname, body, scope, aliases):
        for node in body:
            if isinstance(node, ast.ClassDef):
                qname = "%s.%s" % (scope, node.name)
                self._inherits(module_qname, aliases, node, qname)
                headers = list(node.decorator_list) + list(node.bases) + [k.value for k in node.keywords]
                for header in headers:
                    self._scan_calls(module_qname, header, qname, aliases)
                self._scope_relations(module_qname, node.body, qname, aliases)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qname = "%s.%s" % (scope, node.name)
                defaults = list(node.args.defaults) + [d for d in node.args.kw_defaults if d is not None]
                for header in list(node.decorator_list) + defaults:
                    self._scan_calls(module_qname, header, qname, aliases)
                self._scope_relations(module_qname, node.body, qname, aliases)
            elif isinstance(node, _COMPOUND):
                for head in self._compound_heads(node):
                    self._scan_calls(module_qname, head, scope, aliases)
                for sub in self._sub_bodies(node):
                    self._scope_relations(module_qname, sub, scope, aliases)
            else:
                self._scan_calls(module_qname, node, scope, aliases)

    @staticmethod
    def _sub_bodies(node):
        bodies = []
        if isinstance(node, ast.If):
            bodies = [node.body, node.orelse]
        elif isinstance(node, (ast.With, ast.AsyncWith, ast.For, ast.AsyncFor, ast.While)):
            bodies = [node.body, getattr(node, "orelse", [])]
        elif isinstance(node, ast.Try):
            bodies = [node.body, node.orelse, node.finalbody]
            bodies.extend(handler.body for handler in node.handlers)
        return [b for b in bodies if b]

    @staticmethod
    def _compound_heads(node):
        if isinstance(node, (ast.If, ast.While)):
            return [node.test]
        if isinstance(node, (ast.With, ast.AsyncWith)):
            return [item.context_expr for item in node.items]
        if isinstance(node, (ast.For, ast.AsyncFor)):
            return [node.iter]
        return []

    def _scan_calls(self, module_qname, node, scope, aliases):
        rel = self.relpath.get(module_qname, "")
        for call in self._iter_calls(node):
            target = self._resolve_call(module_qname, scope, call.func, aliases)
            if target is None:
                self.graph.unresolved += 1
                continue
            self.graph.add_edge(scope, target, M.CALLS,
                                "called at %s:%d" % (rel, getattr(call, "lineno", 0)))

    def _iter_calls(self, node, _top=True):
        """Yield Call nodes, never descending into a nested function or class."""
        if isinstance(node, ast.Call):
            yield node
        if not _top and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            return
        for child in ast.iter_child_nodes(node):
            for call in self._iter_calls(child, _top=False):
                yield call

    # -- imports ----------------------------------------------------------
    def _imports(self, module_qname, tree):
        aliases = {}
        rel = self.relpath.get(module_qname, "")
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    aliases[alias.asname or alias.name.split(".")[0]] = alias.name
                    self._import_edge(module_qname, alias.name, rel, node.lineno)
            elif isinstance(node, ast.ImportFrom):
                base = self._relative_base(module_qname, node.level, node.module)
                module_target = "%s.%s" % (base, node.module) if (base and node.module) else (base or node.module or "")
                if module_target:
                    self._import_edge(module_qname, module_target, rel, node.lineno)
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    local = alias.asname or alias.name
                    full = "%s.%s" % (module_target, alias.name) if module_target else alias.name
                    if full in self.graph.nodes:
                        aliases[local] = full
                    elif module_target in self.graph.nodes:
                        aliases[local] = module_target
                    else:
                        aliases[local] = full
        self.imports[module_qname] = aliases
        return aliases

    @staticmethod
    def _relative_base(module_qname, level, module):
        if not level:
            return module or ""
        parts = module_qname.split(".")
        keep = max(0, len(parts) - level)
        return ".".join(parts[:keep])

    def _import_edge(self, src, target, rel, line):
        if not target:
            return
        if target in self.graph.nodes:
            dst = target
        else:
            dst = "ext:" + target
            self.graph.add_node(M.Node(dst, M.EXTERNAL, doc="external module"))
        if self.graph.nodes[dst].kind in (M.MODULE, M.EXTERNAL):
            self.graph.add_edge(src, dst, M.IMPORTS, "imported at %s:%d" % (rel, line))

    # -- inheritance ------------------------------------------------------
    def _inherits(self, module_qname, aliases, node, class_qname):
        rel = self.relpath[module_qname]
        for base in node.bases:
            name = _dotted(base)
            if not name:
                continue
            reason = "%s inherits %s at %s:%d" % (node.name, name, rel, getattr(base, "lineno", node.lineno))
            target = self._resolve_name(module_qname, class_qname, name, aliases)
            if target and self.graph.nodes[target].kind in (M.CLASS, M.EXTERNAL):
                self.graph.add_edge(class_qname, target, M.INHERITS, reason)
            elif "." not in name:
                dst = "ext:" + name
                self.graph.add_node(M.Node(dst, M.EXTERNAL, doc="external base class"))
                self.graph.add_edge(class_qname, dst, M.INHERITS, reason)

    # -- name resolution --------------------------------------------------
    def _resolve_call(self, module_qname, scope, func, aliases):
        name = _dotted(func)
        if not name:
            return None
        if name in self.graph.nodes:
            return name
        first = name.split(".")[0]
        if first in ("self", "cls"):
            owner = self._enclosing_class(scope)
            parts = name.split(".")
            if owner and len(parts) == 2:
                candidate = "%s.%s" % (owner, parts[1])
                if candidate in self.graph.nodes:
                    return candidate
            return None
        return self._resolve_name(module_qname, scope, name, aliases)

    def _resolve_name(self, module_qname, scope, name, aliases):
        if name in self.graph.nodes:
            return name
        for level in self._scope_chain(scope):
            table = self.scope_names.get(level, {})
            if name in table:
                return table[name]
        first = name.split(".")[0]
        if "." in name and first in aliases:
            candidate = aliases[first] + name[len(first):]
            if candidate in self.graph.nodes:
                return candidate
        if first in aliases and aliases[first] in self.graph.nodes:
            return aliases[first]
        matches = [nid for nid in self.graph.nodes if nid.endswith("." + name)]
        if len(matches) == 1:
            return matches[0]
        return None

    def _scope_chain(self, scope):
        parts = scope.split(".")
        return [".".join(parts[:i]) for i in range(len(parts), 0, -1)]

    def _enclosing_class(self, scope):
        for level in self._scope_chain(scope):
            node = self.graph.nodes.get(level)
            if node is not None and node.kind == M.CLASS:
                return level
        return None
