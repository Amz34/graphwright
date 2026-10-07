# Graphwright

![Graphwright — an explained knowledge graph of a Python codebase](assets/graphwright-overview.jpg)

**Turn a Python codebase into an explained, queryable knowledge graph — using nothing but the Python standard library.**

[![CI](https://github.com/Amz34/graphwright/actions/workflows/ci.yml/badge.svg)](https://github.com/Amz34/graphwright/actions/workflows/ci.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## Why

Reading an unfamiliar codebase means asking the same questions over and over:

- Where is this symbol defined, and who calls it?
- What does this function actually depend on?
- Which modules does this package import, and how are these two symbols related?

Grep answers none of them reliably, and a full IDE index is heavyweight and locked to one editor.
Graphwright answers them from a small, portable graph that you can build in one command, inspect as
plain text, and query from the command line or from your own Python code.

Everything is derived by parsing source with the standard library `ast` module. There is no
database, no server, no third-party dependency, and nothing to install beyond Python itself.

## Quickstart

```bash
git clone https://github.com/Amz34/graphwright
cd graphwright

# 1. Build a summary of any Python project
python3 -m graphwright show --path /path/to/some/project

# 2. Export the graph as JSON
python3 -m graphwright build /path/to/some/project -o graph.json

# 3. Ask questions about it
python3 -m graphwright definition Engine.run --graph graph.json
python3 -m graphwright callers util.helper          --graph graph.json
python3 -m graphwright path build_engine Base.greet --graph graph.json
```

Install it as a command instead:

```bash
pip install .
graphwright show --path .
```

## Command reference

| Command | Purpose |
|---|---|
| `build PATH [-o FILE] [-f FORMAT]` | Scan a directory or file and export the graph (`json`, `dot`, `markdown`, `csv`). |
| `show [--json]` | Print a summary: counts by kind, unresolved call sites, most connected nodes, warnings. |
| `definition NAME` | Show the kind, source location and docstring of a symbol, plus the node that defines it. |
| `callers NAME` | List every call site whose target resolves to `NAME`. |
| `callees NAME` | List every symbol `NAME` calls. |
| `neighbors NAME [--depth N] [--kinds a,b]` | Breadth-first neighbourhood around a symbol, optionally restricted to edge kinds. |
| `path SOURCE TARGET` | Shortest relationship path between two symbols, hop by hop. |
| `export [-f FORMAT] [-o FILE]` | Export in any supported format; defaults to Graphviz `dot`. |

Every query command accepts either `--path DIR` (scan a tree) or `--graph FILE` (reuse an export),
so a graph can be built once in CI and queried many times afterwards. Symbols may be given as a
full identifier (`core.Engine.run`) or as a unique suffix (`Engine.run`, `run`).

Example:

```
$ python3 -m graphwright show --path tests/fixtures/sample
root:        sample
nodes:       12 {'module': 3, 'class': 2, 'function': 6, 'external': 1}
edges:       14 {'defines': 9, 'calls': 3, 'imports': 2, 'inherits': 1}
unresolved:  1 call site(s)
fingerprint: 5f2c...
```

## What ends up in the graph

**Nodes** — one per module, class, function or method, plus a node for every external module that is
imported but not present in the scanned tree (`ext:os`). Each node records its kind, file, line and
docstring.

**Edges** — four kinds, each carrying a human-readable reason:

| Edge | Meaning | Example reason |
|---|---|---|
| `defines` | A module or class declares a symbol. | `defined at core.py:6` |
| `calls` | A function calls a resolvable target. | `called at core.py:11` |
| `imports` | A module imports another module. | `imported at util.py:3` |
| `inherits` | A class subclasses a known base class. | `Engine inherits Base at core.py:6` |

## How it works

1. **Collect** every `.py` file under the target, skipping virtual environments, caches and vendor
   directories.
2. **Parse** each file with `ast` and assign qualified names (`module.Class.method`).
3. **Walk** each scope: declarations become `defines` edges, `import` statements register aliases,
   class bases become `inherits` edges, and call expressions become `calls` edges.
4. **Resolve conservatively** — a call is emitted as an edge only when it provably maps to a node we
   already know: an imported name, a module-qualified name, `self.method` inside a class, or a class
   instantiated in the same module. Anything else is counted as unresolved rather than guessed.
5. **Canonicalise** — duplicate edges are merged with their reasons combined, and the edge list is
   sorted, so two runs over identical sources produce byte-identical output.

Every edge answers "why does this edge exist?" with a file and a line number, which is what makes
the graph reviewable instead of merely suggestive.

## Guarantees and design choices

- **Deterministic.** Output is a pure function of the source tree; `fingerprint()` is a SHA-256 over
  the canonical graph, suitable for change detection in CI.
- **Conservative by default.** Precision is preferred over recall: an unresolved call site is
  reported, never invented. The `unresolved` counter tells you how much was left on the table.
- **Fault tolerant.** A file that fails to parse is skipped with a warning; the rest of the tree is
  still analysed.
- **Zero dependencies.** Standard library only, Python 3.9 and newer.

## Limitations

- Static analysis over the syntax tree: dynamic calls (`getattr`, decorators that wrap, string-based
  dispatch) and re-exports are not followed.
- A call on a local variable whose type is not obvious from the same module is left unresolved
  rather than guessed; so is `from x import *`.
- Conditional imports and platform-specific branches are recorded as written, not evaluated.
- Lambdas are used as call arguments; calls made *inside* a lambda body are not traversed.
- The graph models Python only.

## Development

```bash
make test     # run the unittest suite
make check    # byte-compile every source file
make demo     # build and summarise the bundled fixture package
```

The test suite covers the builder, the query helpers, the exporters and the command line interface
end to end, and runs on Python 3.11 and 3.12 in CI.

## License

MIT — see [LICENSE](LICENSE).

---

Part of [my always-on agent stack](https://github.com/Amz34) · [Awesome Agent Infrastructure](https://github.com/Amz34/awesome-agent-infrastructure) (135 live-checked building blocks).
