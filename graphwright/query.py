"""Query helpers that operate on a built graph.

Every helper works on node identifiers (the dotted qualified names produced by
the builder). Names supplied by the user are resolved with :func:`find_nodes`.
"""

from __future__ import annotations

from collections import Counter, deque

from . import model as M


def find_nodes(graph, name):
    """Resolve a user supplied name to a sorted list of node identifiers."""
    if name in graph.nodes:
        return [name]
    return sorted(nid for nid in graph.nodes if nid.endswith("." + name))


def require_one(graph, name):
    """Resolve *name* to exactly one node identifier, or raise ``LookupError``."""
    matches = find_nodes(graph, name)
    if not matches:
        raise LookupError("no node matches %r" % name)
    if len(matches) > 1:
        raise LookupError("ambiguous name %r matches %d nodes: %s"
                          % (name, len(matches), ", ".join(matches[:8])))
    return matches[0]


def callers(graph, name):
    """Return call edges whose target is *name*."""
    node_id = require_one(graph, name)
    return [e for e in graph.edges if e.kind == M.CALLS and e.dst == node_id]


def callees(graph, name):
    """Return call edges whose source is *name*."""
    node_id = require_one(graph, name)
    return [e for e in graph.edges if e.kind == M.CALLS and e.src == node_id]


def adjacency(graph, kinds=None):
    """Build an undirected adjacency map, optionally filtered by edge kind."""
    index = {}
    for edge in graph.edges:
        if kinds and edge.kind not in kinds:
            continue
        index.setdefault(edge.src, set()).add(edge.dst)
        index.setdefault(edge.dst, set()).add(edge.src)
    return index


def neighbors(graph, name, depth=1, kinds=None):
    """Breadth-first neighbours of *name* up to *depth* hops."""
    node_id = require_one(graph, name)
    index = adjacency(graph, kinds)
    seen = {node_id: 0}
    order = []
    queue = deque([(node_id, 0)])
    while queue:
        current, distance = queue.popleft()
        if distance >= depth:
            continue
        for other in sorted(index.get(current, ())):
            if other not in seen:
                seen[other] = distance + 1
                order.append(other)
                queue.append((other, distance + 1))
    return [(other, seen[other]) for other in order]


def shortest_path(graph, source, target):
    """Return the undirected edge path between two symbols, or an empty list."""
    src = require_one(graph, source)
    dst = require_one(graph, target)
    if src == dst:
        return []
    index = {}
    for edge in graph.edges:
        index.setdefault(edge.src, []).append((edge, edge.dst))
        index.setdefault(edge.dst, []).append((edge, edge.src))
    previous = {src: None}
    queue = deque([src])
    while queue:
        current = queue.popleft()
        if current == dst:
            break
        for edge, other in sorted(index.get(current, ()), key=lambda pair: pair[1]):
            if other not in previous:
                previous[other] = (current, edge)
                queue.append(other)
    if dst not in previous:
        return []
    chain = []
    cursor = dst
    while previous[cursor] is not None:
        parent, edge = previous[cursor]
        chain.append(edge)
        cursor = parent
    chain.reverse()
    return chain


def summary(graph):
    """Return aggregate statistics about the graph."""
    node_kinds = Counter(node.kind for node in graph.nodes.values())
    edge_kinds = Counter(edge.kind for edge in graph.edges)
    degree = Counter()
    for edge in graph.edges:
        degree[edge.src] += 1
        degree[edge.dst] += 1
    top = sorted(degree.items(), key=lambda pair: (-pair[1], pair[0]))[:10]
    return {
        "root": graph.root,
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
        "node_kinds": dict(sorted(node_kinds.items())),
        "edge_kinds": dict(sorted(edge_kinds.items())),
        "unresolved_calls": graph.unresolved,
        "warnings": list(graph.warnings),
        "top_nodes": top,
        "fingerprint": graph.fingerprint(),
    }
