"""Core data model for the Graphwright knowledge graph.

The model is intentionally small and dependency-free. A graph is a mapping of
unique identifiers to :class:`Node` objects plus a list of :class:`Edge`
objects. Every edge carries a human-readable ``reason`` so the graph is
explainable rather than opaque.
"""

from __future__ import annotations

import hashlib
import json

MODULE = "module"
CLASS = "class"
FUNCTION = "function"
EXTERNAL = "external"

DEFINES = "defines"
IMPORTS = "imports"
INHERITS = "inherits"
CALLS = "calls"

NODE_KINDS = (MODULE, CLASS, FUNCTION, EXTERNAL)
EDGE_KINDS = (DEFINES, IMPORTS, INHERITS, CALLS)

_MAX_REASONS = 2


class Node:
    """A single named symbol in the graph."""

    __slots__ = ("id", "kind", "file", "line", "name", "doc")

    def __init__(self, id, kind, file="", line=0, name="", doc=""):
        self.id = id
        self.kind = kind
        self.file = file
        self.line = int(line or 0)
        self.name = name or id.rpartition(".")[2]
        self.doc = doc or ""

    def to_dict(self):
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "file": self.file,
            "line": self.line,
            "doc": self.doc,
        }

    def __repr__(self):
        return "Node(%r, %r)" % (self.id, self.kind)


class Edge:
    """A directed, explained relationship between two nodes."""

    __slots__ = ("src", "dst", "kind", "reason")

    def __init__(self, src, dst, kind, reason=""):
        self.src = src
        self.dst = dst
        self.kind = kind
        self.reason = reason or ""

    def to_dict(self):
        return {"source": self.src, "target": self.dst, "kind": self.kind, "reason": self.reason}

    def __repr__(self):
        return "Edge(%r -%s-> %r)" % (self.src, self.kind, self.dst)


class Graph:
    """A code knowledge graph: nodes plus explained edges."""

    def __init__(self, root=""):
        self.root = root
        self.nodes = {}
        self.edges = []
        self.warnings = []
        self.unresolved = 0

    # -- construction -----------------------------------------------------
    def add_node(self, node):
        if node.id not in self.nodes:
            self.nodes[node.id] = node
        return self.nodes[node.id]

    def add_edge(self, src, dst, kind, reason=""):
        self.edges.append(Edge(src, dst, kind, reason))

    def finalize(self):
        """Collapse duplicate edges and order nodes and edges deterministically."""
        grouped = {}
        for edge in self.edges:
            grouped.setdefault((edge.kind, edge.src, edge.dst), set()).add(edge.reason)
        merged = []
        for (kind, src, dst), reasons in grouped.items():
            ordered = sorted(r for r in reasons if r)
            if not ordered:
                text = ""
            elif len(ordered) <= _MAX_REASONS:
                text = "; ".join(ordered)
            else:
                extra = len(ordered) - _MAX_REASONS
                text = "; ".join(ordered[:_MAX_REASONS]) + "; (+%d more)" % extra
            merged.append(Edge(src, dst, kind, text))
        merged.sort(key=lambda e: (e.kind, e.src, e.dst, e.reason))
        self.edges = merged
        self.nodes = {nid: self.nodes[nid] for nid in sorted(self.nodes)}
        return self

    # -- serialisation ----------------------------------------------------
    def to_dict(self):
        return {
            "root": self.root,
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
            "unresolved_calls": self.unresolved,
            "warnings": sorted(self.warnings),
            "nodes": [self.nodes[nid].to_dict() for nid in sorted(self.nodes)],
            "edges": [edge.to_dict() for edge in self.edges],
        }

    def fingerprint(self):
        blob = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()

    @classmethod
    def from_dict(cls, data):
        graph = cls(root=data.get("root", ""))
        for item in data.get("nodes", []):
            graph.add_node(Node(item["id"], item["kind"], item.get("file", ""), item.get("line", 0),
                                item.get("name", ""), item.get("doc", "")))
        for item in data.get("edges", []):
            graph.add_edge(item["source"], item["target"], item["kind"], item.get("reason", ""))
        graph.warnings = list(data.get("warnings", []))
        graph.unresolved = int(data.get("unresolved_calls", 0))
        return graph

    # -- lookups ----------------------------------------------------------
    def out_edges(self, node_id, kinds=None):
        return [e for e in self.edges if e.src == node_id and (not kinds or e.kind in kinds)]

    def in_edges(self, node_id, kinds=None):
        return [e for e in self.edges if e.dst == node_id and (not kinds or e.kind in kinds)]
