"""Unit tests for Graphwright.

The suite is standard library only (``unittest``) and needs no third-party
packages. It exercises the builder, the query helpers, the exporters and the
command line interface end to end.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "sample"

sys.path.insert(0, str(ROOT))

from graphwright import model as M  # noqa: E402
from graphwright import query, render  # noqa: E402
from graphwright.builder import Builder, iter_python_files, module_name  # noqa: E402


def build_fixture():
    return Builder(str(FIXTURE)).build()


class BuilderTests(unittest.TestCase):
    def setUp(self):
        self.graph = build_fixture()

    def test_expected_nodes_are_discovered(self):
        for node_id, kind in [
            ("core", M.MODULE),
            ("core.Engine", M.CLASS),
            ("core.Engine.run", M.FUNCTION),
            ("core.build_engine", M.FUNCTION),
            ("util.Base", M.CLASS),
            ("util.Base.greet", M.FUNCTION),
            ("util.helper", M.FUNCTION),
        ]:
            self.assertIn(node_id, self.graph.nodes)
            self.assertEqual(self.graph.nodes[node_id].kind, kind)

    def test_package_init_maps_to_package_name(self):
        self.assertIn("sample", self.graph.nodes)
        self.assertNotIn("__root__", self.graph.nodes)

    def test_no_unexpected_nodes(self):
        self.assertEqual(len(self.graph.nodes), 12)

    def test_defines_edges(self):
        pairs = {(e.src, e.dst) for e in self.graph.edges if e.kind == M.DEFINES}
        self.assertIn(("core", "core.Engine"), pairs)
        self.assertIn(("core.Engine", "core.Engine.run"), pairs)
        self.assertIn(("util.Base", "util.Base.greet"), pairs)

    def test_self_call_resolves_to_enclosing_class(self):
        calls = {(e.dst) for e in self.graph.edges
                 if e.kind == M.CALLS and e.src == "core.Engine.run"}
        self.assertEqual(calls, {"core.Engine.step", "util.helper"})

    def test_imported_name_call_resolves(self):
        edges = [e for e in self.graph.edges
                 if e.kind == M.CALLS and e.src == "core.Engine.run" and e.dst == "util.helper"]
        self.assertEqual(len(edges), 1)
        self.assertIn("core.py:11", edges[0].reason)

    def test_inheritance_edge(self):
        edges = [e for e in self.graph.edges if e.kind == M.INHERITS]
        self.assertEqual(len(edges), 1)
        self.assertEqual((edges[0].src, edges[0].dst), ("core.Engine", "util.Base"))

    def test_import_edges_include_external(self):
        edges = [e for e in self.graph.edges if e.kind == M.IMPORTS]
        self.assertIn(("core", "util"), [(e.src, e.dst) for e in edges])
        self.assertIn(("util", "ext:os"), [(e.src, e.dst) for e in edges])
        self.assertEqual(self.graph.nodes["ext:os"].kind, M.EXTERNAL)

    def test_local_instance_call_is_not_guessed(self):
        # ``engine.run(3)`` cannot be resolved statically: it must be counted,
        # not invented as an edge.
        self.assertEqual(self.graph.unresolved, 1)
        self.assertFalse([e for e in self.graph.edges
                          if e.kind == M.CALLS and e.src == "core.build_engine"
                          and e.dst == "core.Engine.run"])

    def test_edges_are_unique_and_sorted(self):
        keys = [(e.kind, e.src, e.dst) for e in self.graph.edges]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(keys, sorted(keys))

    def test_fingerprint_is_deterministic(self):
        first = build_fixture()
        second = build_fixture()
        self.assertEqual(first.fingerprint(), second.fingerprint())

    def test_fingerprint_changes_with_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mod.py"
            path.write_text("def a():\n    return 1\n", encoding="utf-8")
            before = Builder(tmp).build().fingerprint()
            path.write_text("def a():\n    return 1\n\n\ndef b():\n    return 2\n", encoding="utf-8")
            after = Builder(tmp).build().fingerprint()
        self.assertNotEqual(before, after)

    def test_single_file_target(self):
        graph = Builder(str(FIXTURE / "util.py")).build()
        self.assertIn("util", graph.nodes)
        self.assertIn("util.helper", graph.nodes)

    def test_syntax_error_is_a_warning_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "broken.py").write_text("def (:\n", encoding="utf-8")
            Path(tmp, "good.py").write_text("def ok():\n    return 1\n", encoding="utf-8")
            graph = Builder(tmp).build()
        self.assertIn("good", graph.nodes)
        self.assertTrue(any("broken.py" in w for w in graph.warnings))

    def test_empty_directory_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            graph = Builder(tmp).build()
        self.assertEqual(graph.nodes, {})
        self.assertTrue(any("no Python files" in w for w in graph.warnings))

    def test_iter_python_files_skips_vendor_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "keep.py").write_text("", encoding="utf-8")
            for skipped in ("__pycache__", ".git", "node_modules"):
                Path(tmp, skipped).mkdir()
                Path(tmp, skipped, "x.py").write_text("", encoding="utf-8")
            found = sorted(os.path.basename(p) for p in iter_python_files(tmp))
        self.assertEqual(found, ["keep.py"])

    def test_module_name_helper(self):
        self.assertEqual(module_name(str(FIXTURE), str(FIXTURE / "core.py")), "core")
        self.assertEqual(module_name(str(FIXTURE), str(FIXTURE / "__init__.py"), "sample"), "sample")


class ModelTests(unittest.TestCase):
    def test_finalize_collapses_duplicate_edges(self):
        graph = M.Graph(root="x")
        graph.add_edge("a", "b", M.CALLS, "first")
        graph.add_edge("a", "b", M.CALLS, "second")
        graph.add_edge("a", "b", M.CALLS, "second")
        graph.finalize()
        self.assertEqual(len(graph.edges), 1)
        self.assertEqual(graph.edges[0].reason, "first; second")

    def test_finalize_reason_overflow_is_marked(self):
        graph = M.Graph(root="x")
        for reason in ("r1", "r2", "r3", "r4"):
            graph.add_edge("a", "b", M.CALLS, reason)
        graph.finalize()
        self.assertIn("(+2 more)", graph.edges[0].reason)

    def test_roundtrip_preserves_state(self):
        original = build_fixture()
        restored = M.Graph.from_dict(json.loads(render.to_json(original)))
        self.assertEqual(restored.fingerprint(), original.fingerprint())
        self.assertEqual(restored.unresolved, original.unresolved)


class QueryTests(unittest.TestCase):
    def setUp(self):
        self.graph = build_fixture()

    def test_find_nodes_exact_and_suffix(self):
        self.assertEqual(query.find_nodes(self.graph, "core.Engine"), ["core.Engine"])
        self.assertEqual(query.find_nodes(self.graph, "helper"), ["util.helper"])
        self.assertEqual(query.find_nodes(self.graph, "run"), ["core.Engine.run"])

    def test_find_nodes_no_match(self):
        self.assertEqual(query.find_nodes(self.graph, "does_not_exist"), [])

    def test_require_one_raises_on_missing_and_ambiguous(self):
        with self.assertRaises(LookupError):
            query.require_one(self.graph, "nope")
        graph = M.Graph(root="x")
        graph.add_node(M.Node("alpha.run", M.FUNCTION))
        graph.add_node(M.Node("beta.run", M.FUNCTION))
        with self.assertRaises(LookupError):
            query.require_one(graph, "run")  # two nodes share the suffix

    def test_callers_and_callees(self):
        self.assertEqual([e.src for e in query.callers(self.graph, "step")], ["core.Engine.run"])
        self.assertEqual([e.dst for e in query.callees(self.graph, "Engine.run")],
                         ["core.Engine.step", "util.helper"])

    def test_neighbors_depth(self):
        depth_one = dict(query.neighbors(self.graph, "util.helper", depth=1))
        self.assertEqual(depth_one, {"core.Engine.run": 1, "util": 1})
        depth_two = dict(query.neighbors(self.graph, "util.helper", depth=2))
        self.assertEqual(depth_two["core.Engine"], 2)

    def test_neighbors_kind_filter(self):
        only_imports = dict(query.neighbors(self.graph, "util", depth=2, kinds={M.IMPORTS}))
        self.assertEqual(only_imports, {"core": 1, "ext:os": 1})

    def test_shortest_path(self):
        chain = query.shortest_path(self.graph, "build_engine", "Base.greet")
        self.assertEqual([e.kind for e in chain], [M.CALLS, M.INHERITS, M.DEFINES])
        self.assertEqual(chain[0].src, "core.build_engine")
        self.assertEqual(chain[-1].dst, "util.Base.greet")

    def test_shortest_path_same_node_is_empty(self):
        self.assertEqual(query.shortest_path(self.graph, "util", "util"), [])

    def test_shortest_path_unknown_node(self):
        with self.assertRaises(LookupError):
            query.shortest_path(self.graph, "util", "nope")

    def test_summary_shape(self):
        data = query.summary(self.graph)
        self.assertEqual(data["nodes"], 12)
        self.assertEqual(data["edges"], 14)
        self.assertEqual(data["unresolved_calls"], 1)
        self.assertEqual(data["node_kinds"]["module"], 3)
        self.assertEqual(len(data["fingerprint"]), 64)


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.graph = build_fixture()

    def test_json_is_valid_and_complete(self):
        data = json.loads(render.to_json(self.graph))
        self.assertEqual(data["node_count"], len(data["nodes"]))
        self.assertEqual(data["edge_count"], len(data["edges"]))
        self.assertEqual(data["unresolved_calls"], 1)

    def test_dot_lists_every_node_and_edge(self):
        dot = render.to_dot(self.graph)
        self.assertTrue(dot.startswith("digraph graphwright {"))
        self.assertTrue(dot.rstrip().endswith("}"))
        for node_id in self.graph.nodes:
            self.assertIn('"%s"' % node_id, dot)
        self.assertEqual(dot.count(" -> "), len(self.graph.edges))

    def test_markdown_tables(self):
        markdown = render.to_markdown(self.graph)
        self.assertIn("# Code knowledge graph: sample", markdown)
        self.assertIn("| Kind | Symbol | Location | Documentation |", markdown)
        # every node row carries one back-ticked cell, every edge row two
        self.assertEqual(markdown.count("| `"),
                         len(self.graph.nodes) + 2 * len(self.graph.edges))

    def test_csv_rows(self):
        rows = render.to_csv(self.graph).strip().splitlines()
        self.assertEqual(rows[0], "kind,source,target,reason")
        self.assertEqual(len(rows), len(self.graph.edges) + 1)

    def test_fingerprint_is_stable_across_renders(self):
        self.assertEqual(render.to_json(self.graph), render.to_json(build_fixture()))


class CliTests(unittest.TestCase):
    def run_cli(self, *args, **kwargs):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        return subprocess.run(
            [sys.executable, "-m", "graphwright", *args],
            cwd=str(ROOT), env=env, capture_output=True, text=True, **kwargs,
        )

    def test_version(self):
        result = self.run_cli("--version")
        self.assertEqual(result.returncode, 0)
        self.assertIn("graphwright 0.1.0", result.stdout)

    def test_help_lists_all_commands(self):
        result = self.run_cli("--help")
        self.assertEqual(result.returncode, 0)
        for command in ("build", "show", "definition", "callers", "callees",
                        "neighbors", "path", "export"):
            self.assertIn(command, result.stdout)

    def test_build_writes_export_and_reports_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "graph.json"
            result = self.run_cli("build", str(FIXTURE), "-o", str(out))
            self.assertEqual(result.returncode, 0)
            self.assertIn("12 nodes, 14 edges", result.stdout)
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(data["node_count"], 12)

    def test_build_to_stdout(self):
        result = self.run_cli("build", str(FIXTURE))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["edge_count"], 14)

    def test_build_markdown_format(self):
        result = self.run_cli("build", str(FIXTURE), "-f", "markdown")
        self.assertEqual(result.returncode, 0)
        self.assertTrue(result.stdout.startswith("# Code knowledge graph"))

    def test_query_commands_with_path(self):
        for args in (
            ("definition", "Engine.run"),
            ("callers", "step"),
            ("callees", "Engine.run"),
            ("neighbors", "util.helper", "--depth", "2"),
            ("path", "build_engine", "Base.greet"),
        ):
            result = self.run_cli(*args, "--path", str(FIXTURE))
            self.assertEqual(result.returncode, 0, msg="%s -> %s" % (args, result.stderr))

    def test_definition_reports_location_and_doc(self):
        result = self.run_cli("definition", "Engine.run", "--path", str(FIXTURE))
        self.assertIn("core.Engine.run  [function]", result.stdout)
        self.assertIn("core.py:9", result.stdout)
        self.assertIn("Run the engine over a value.", result.stdout)

    def test_unknown_symbol_exits_2(self):
        result = self.run_cli("callers", "does_not_exist", "--path", str(FIXTURE))
        self.assertEqual(result.returncode, 2)
        self.assertIn("no node matches", result.stderr)

    def test_missing_path_exits_with_error(self):
        result = self.run_cli("show", "--path", "/no/such/directory/anywhere")
        self.assertNotEqual(result.returncode, 0)

    def test_show_json(self):
        result = self.run_cli("show", "--path", str(FIXTURE), "--json")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["nodes"], 12)

    def test_show_text(self):
        result = self.run_cli("show", "--path", str(FIXTURE))
        self.assertIn("root:        sample", result.stdout)
        self.assertIn("most connected:", result.stdout)

    def test_export_csv_default_format(self):
        result = self.run_cli("export", "--path", str(FIXTURE))
        self.assertEqual(result.returncode, 0)
        self.assertTrue(result.stdout.startswith("digraph"))

    def test_graph_file_roundtrip_between_invocations(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "graph.json"
            self.run_cli("build", str(FIXTURE), "-o", str(out))
            result = self.run_cli("callees", "Engine.run", "--graph", str(out))
        self.assertEqual(result.returncode, 0)
        self.assertIn("util.helper", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
