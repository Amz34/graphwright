"""Command line interface for Graphwright."""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import query, render
from . import model as M
from .builder import Builder

_FORMATS = ("json", "dot", "markdown", "csv")


def load_graph(args):
    """Build a graph from a path, or load a previously exported one."""
    if getattr(args, "graph", None):
        with open(args.graph, "r", encoding="utf-8") as handle:
            return M.Graph.from_dict(json.load(handle))
    path = getattr(args, "path", None) or "."
    if not os.path.exists(path):
        raise SystemExit("error: path does not exist: %s" % path)
    return Builder(path).build()


def render_as(graph, fmt):
    if fmt == "json":
        return render.to_json(graph)
    if fmt == "dot":
        return render.to_dot(graph)
    if fmt == "markdown":
        return render.to_markdown(graph)
    if fmt == "csv":
        return render.to_csv(graph)
    raise SystemExit("error: unknown format: %s" % fmt)


def _cmd_build(args, graph):
    text = render_as(graph, args.format)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(text)
        print("wrote %s | %d nodes, %d edges | fingerprint %s"
              % (args.output, len(graph.nodes), len(graph.edges), graph.fingerprint()))
    else:
        sys.stdout.write(text)
    return 0


def _cmd_show(args, graph):
    data = query.summary(graph)
    if args.json:
        print(json.dumps(data, indent=2))
        return 0
    print("root:        %s" % data["root"])
    print("nodes:       %d %s" % (data["nodes"], data["node_kinds"]))
    print("edges:       %d %s" % (data["edges"], data["edge_kinds"]))
    print("unresolved:  %d call site(s)" % data["unresolved_calls"])
    print("fingerprint: %s" % data["fingerprint"])
    if data["top_nodes"]:
        print("most connected:")
        for node_id, degree in data["top_nodes"]:
            print("  %3d  %s" % (degree, node_id))
    for warning in data["warnings"]:
        print("warning:     %s" % warning)
    return 0


def _cmd_definition(args, graph):
    matches = query.find_nodes(graph, args.name)
    if not matches:
        print("no node matches %r" % args.name, file=sys.stderr)
        return 2
    for node_id in matches:
        node = graph.nodes[node_id]
        print("%s  [%s]" % (node.id, node.kind))
        if node.file:
            print("  location: %s:%d" % (node.file, node.line))
        else:
            print("  location: external symbol")
        if node.doc:
            print("  doc:      %s" % node.doc)
        inbound = [e for e in graph.in_edges(node_id) if e.kind == M.DEFINES]
        for edge in inbound:
            print("  defined by: %s (%s)" % (edge.src, edge.reason))
    return 0


def _cmd_callers(args, graph):
    try:
        node_id = query.require_one(graph, args.name)
    except LookupError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    edges = query.callers(graph, node_id)
    print("%s is called at %d site(s):" % (node_id, len(edges)))
    for edge in edges:
        print("  %-42s  %s" % (edge.src, edge.reason))
    return 0


def _cmd_callees(args, graph):
    try:
        node_id = query.require_one(graph, args.name)
    except LookupError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    edges = query.callees(graph, node_id)
    print("%s calls %d target(s):" % (node_id, len(edges)))
    for edge in edges:
        print("  %-42s  %s" % (edge.dst, edge.reason))
    return 0


def _cmd_neighbors(args, graph):
    try:
        node_id = query.require_one(graph, args.name)
    except LookupError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    kinds = set(args.kinds.split(",")) if args.kinds else None
    result = query.neighbors(graph, node_id, depth=args.depth, kinds=kinds)
    print("neighbours of %s (depth %d): %d" % (node_id, args.depth, len(result)))
    for other, distance in result:
        print("  d%d  %-46s [%s]" % (distance, other, graph.nodes[other].kind))
    return 0


def _cmd_path(args, graph):
    try:
        chain = query.shortest_path(graph, args.source, args.target)
    except LookupError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if not chain:
        print("no path between %s and %s" % (args.source, args.target))
        return 1
    print("path: %s -> %s (%d hop(s))" % (chain[0].src, chain[-1].dst, len(chain)))
    for edge in chain:
        print("  %s --%s--> %s  (%s)" % (edge.src, edge.kind, edge.dst, edge.reason))
    return 0


def _add_source(parser):
    parser.add_argument("path", nargs="?", default=".", help="directory or file to analyse (default: .)")
    parser.add_argument("--graph", help="load a previously exported JSON graph instead of scanning a path")


def _add_query_source(parser):
    parser.add_argument("--graph", help="load a previously exported JSON graph instead of scanning a path")
    parser.add_argument("--path", default=None, help="directory or file to analyse (default: .)")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="graphwright",
        description="Build and query an explained knowledge graph of a Python codebase.",
    )
    parser.add_argument("--version", action="version", version="graphwright 0.1.0")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="scan a path and export the graph")
    _add_source(build)
    build.add_argument("-o", "--output", help="write the export to this file instead of stdout")
    build.add_argument("-f", "--format", choices=_FORMATS, default="json", help="export format")
    build.set_defaults(func=_cmd_build)

    show = sub.add_parser("show", help="print a summary of the graph")
    _add_query_source(show)
    show.add_argument("--json", action="store_true", help="print the summary as JSON")
    show.set_defaults(func=_cmd_show)

    definition = sub.add_parser("definition", aliases=["def"], help="show where a symbol is defined")
    definition.add_argument("name")
    _add_query_source(definition)
    definition.set_defaults(func=_cmd_definition)

    callers = sub.add_parser("callers", help="list call sites that target a symbol")
    callers.add_argument("name")
    _add_query_source(callers)
    callers.set_defaults(func=_cmd_callers)

    callees = sub.add_parser("callees", help="list symbols called by a symbol")
    callees.add_argument("name")
    _add_query_source(callees)
    callees.set_defaults(func=_cmd_callees)

    neighbours = sub.add_parser("neighbors", help="list neighbours within a number of hops")
    neighbours.add_argument("name")
    neighbours.add_argument("--depth", type=int, default=1, help="maximum hop distance (default: 1)")
    neighbours.add_argument("--kinds", help="comma-separated edge kinds to follow")
    _add_query_source(neighbours)
    neighbours.set_defaults(func=_cmd_neighbors)

    path = sub.add_parser("path", help="find the shortest relationship path between two symbols")
    path.add_argument("source")
    path.add_argument("target")
    _add_query_source(path)
    path.set_defaults(func=_cmd_path)

    export = sub.add_parser("export", help="export the graph in a chosen format")
    _add_query_source(export)
    export.add_argument("-o", "--output", help="write the export to this file instead of stdout")
    export.add_argument("-f", "--format", choices=_FORMATS, default="dot", help="export format")
    export.set_defaults(func=_cmd_build)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    graph = load_graph(args)
    return args.func(args, graph)


if __name__ == "__main__":
    raise SystemExit(main())
