"""Exporters that turn a graph into JSON, Graphviz DOT, Markdown or CSV."""

from __future__ import annotations

import csv
import io
import json

from . import model as M

_KIND_STYLE = {
    M.MODULE: ("box", "#dbeafe"),
    M.CLASS: ("ellipse", "#fde68a"),
    M.FUNCTION: ("box", "#dcfce7"),
    M.EXTERNAL: ("box", "#f3f4f6"),
}


def _escape(text):
    return str(text).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def to_json(graph, indent=2):
    """Serialise the whole graph as pretty JSON."""
    return json.dumps(graph.to_dict(), indent=indent, ensure_ascii=False, sort_keys=False) + "\n"


def to_dot(graph):
    """Render the graph as Graphviz DOT."""
    lines = ["digraph graphwright {", '  rankdir="LR";', '  node [fontname="Helvetica"];']
    for node_id in sorted(graph.nodes):
        node = graph.nodes[node_id]
        shape, colour = _KIND_STYLE.get(node.kind, ("box", "#ffffff"))
        style = "dashed" if node.kind == M.EXTERNAL else "solid"
        lines.append('  "%s" [label="%s", shape=%s, style=%s, fillcolor="%s", fontsize=10];'
                     % (_escape(node_id), _escape(node.name), shape, style, colour))
    for edge in graph.edges:
        lines.append('  "%s" -> "%s" [label="%s", fontsize=8];'
                     % (_escape(edge.src), _escape(edge.dst), _escape(edge.kind)))
    lines.append("}")
    return "\n".join(lines) + "\n"


def to_csv(graph):
    """Render the edge list as CSV (one row per relationship)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["kind", "source", "target", "reason"])
    for edge in graph.edges:
        writer.writerow([edge.kind, edge.src, edge.dst, edge.reason])
    return buffer.getvalue()


def to_markdown(graph):
    """Render a human-readable Markdown report of the graph."""
    out = ["# Code knowledge graph: %s" % (graph.root or "(root)"), ""]
    out.append("%d nodes, %d edges, %d unresolved call site(s)." % (len(graph.nodes), len(graph.edges), graph.unresolved))
    out.append("")
    out.append("## Nodes")
    out.append("")
    out.append("| Kind | Symbol | Location | Documentation |")
    out.append("|---|---|---|---|")
    for node_id in sorted(graph.nodes):
        node = graph.nodes[node_id]
        location = "%s:%d" % (node.file, node.line) if node.file else "-"
        out.append("| %s | `%s` | %s | %s |" % (node.kind, node.id, location, node.doc or "-"))
    out.append("")
    out.append("## Relationships")
    out.append("")
    out.append("| Kind | Source | Target | Reason |")
    out.append("|---|---|---|---|")
    for edge in graph.edges:
        out.append("| %s | `%s` | `%s` | %s |" % (edge.kind, edge.src, edge.dst, edge.reason or "-"))
    out.append("")
    if graph.warnings:
        out.append("## Warnings")
        out.append("")
        for warning in sorted(graph.warnings):
            out.append("- %s" % warning)
        out.append("")
    return "\n".join(out)
