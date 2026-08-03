from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from meta_flow.design import module_boundaries


def _write_python(root: Path, module: str, source: str) -> None:
    path = root / (module.replace(".", "/") + ".py")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


class ModuleBoundarySccTests(unittest.TestCase):
    def test_cli_and_facade_have_exact_downward_edges_without_back_imports(
        self,
    ) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        facade = "meta_flow.workflow.cr_lifecycle"
        cli = "meta_flow.workflow.cr_cli"
        analysis = "meta_flow.workflow.cr_analysis"
        index = "meta_flow.workflow.cr_index"
        model = "meta_flow.workflow.cr_model"
        projection = "meta_flow.workflow.cr_projection"
        records = "meta_flow.workflow.cr_records"
        status_sync = "meta_flow.workflow.cr_status_sync"
        transaction = "meta_flow.workflow.cr_status_transaction"
        termination = "meta_flow.workflow.cr_termination"
        leaves = {
            analysis,
            index,
            model,
            projection,
            records,
            status_sync,
            transaction,
            termination,
        }
        leaf_edges = {
            (analysis, index),
            (analysis, model),
            (analysis, projection),
            (analysis, records),
            (cli, analysis),
            (cli, index),
            (cli, model),
            (cli, projection),
            (cli, records),
            (cli, status_sync),
            (cli, transaction),
            (cli, termination),
            (index, model),
            (index, projection),
            (index, records),
            (projection, model),
            (projection, records),
            (records, model),
            (status_sync, index),
            (status_sync, model),
            (status_sync, projection),
            (status_sync, records),
            (status_sync, transaction),
            (termination, index),
            (termination, model),
            (termination, projection),
            (termination, records),
            (transaction, model),
            (transaction, projection),
            (transaction, records),
        }

        cli_report = module_boundaries.check_import_graph(
            repo_root,
            targets={cli},
            touched=leaves,
            allowed_edges=leaf_edges,
        )
        self.assertEqual(sorted({cli, *leaves}), cli_report["closure"])
        self.assertEqual(sorted(leaf_edges), cli_report["edges"])
        self.assertEqual([], cli_report["undeclared_edges"])
        self.assertEqual([], cli_report["self_loops"])
        self.assertEqual([], cli_report["known_scc_drift"])
        self.assertEqual([], cli_report["findings"])

        facade_edges = leaf_edges | {(facade, cli)} | {
            (facade, leaf) for leaf in leaves
        }
        facade_report = module_boundaries.check_import_graph(
            repo_root,
            targets={facade},
            touched={cli, *leaves},
            allowed_edges=facade_edges,
        )
        self.assertEqual(
            sorted({facade, cli, *leaves}),
            facade_report["closure"],
        )
        self.assertEqual(sorted(facade_edges), facade_report["edges"])
        self.assertEqual([], facade_report["undeclared_edges"])
        self.assertEqual([], facade_report["self_loops"])
        self.assertEqual([], facade_report["known_scc_drift"])
        self.assertEqual([], facade_report["findings"])

        for module, expected in ((cli, leaves), (facade, {cli, *leaves})):
            with self.subTest(module=module):
                source = repo_root / (module.replace(".", "/") + ".py")
                tree = ast.parse(source.read_text(encoding="utf-8"))
                direct_modules = {
                    node.module
                    for node in tree.body
                    if isinstance(node, ast.ImportFrom) and node.module
                }
                self.assertEqual(
                    expected,
                    {
                        imported
                        for imported in direct_modules
                        if imported.startswith("meta_flow.workflow.cr_")
                    },
                )

    def test_analysis_has_exact_downward_edges_and_no_horizontal_dependencies(
        self,
    ) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        analysis = "meta_flow.workflow.cr_analysis"
        index = "meta_flow.workflow.cr_index"
        projection = "meta_flow.workflow.cr_projection"
        records = "meta_flow.workflow.cr_records"
        model = "meta_flow.workflow.cr_model"
        allowed_edges = {
            (analysis, index),
            (analysis, model),
            (analysis, projection),
            (analysis, records),
            (index, model),
            (index, projection),
            (index, records),
            (projection, model),
            (projection, records),
            (records, model),
        }

        report = module_boundaries.check_import_graph(
            repo_root,
            targets={analysis},
            touched={index, projection, records, model},
            allowed_edges=allowed_edges,
        )

        self.assertEqual(
            sorted({analysis, index, projection, records, model}),
            report["closure"],
        )
        self.assertEqual(sorted(allowed_edges), report["edges"])
        self.assertEqual([], report["undeclared_edges"])
        self.assertEqual([], report["self_loops"])
        self.assertEqual([], report["known_scc_drift"])
        self.assertEqual([], report["findings"])

        source = repo_root / "meta_flow" / "workflow" / "cr_analysis.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        direct_modules = {
            node.module
            for node in tree.body
            if isinstance(node, ast.ImportFrom) and node.module
        }
        self.assertEqual(
            {index, projection, records, model},
            {
                module
                for module in direct_modules
                if module.startswith("meta_flow.workflow.cr_")
            },
        )
        self.assertTrue(
            {
                "meta_flow.workflow.cr_status_sync",
                "meta_flow.workflow.cr_status_transaction",
                "meta_flow.workflow.cr_termination",
                "meta_flow.workflow.cr_lifecycle",
                "meta_flow.workflow.cr_cli",
            }.isdisjoint(direct_modules)
        )

    def test_termination_has_exact_downward_edges_and_no_horizontal_dependencies(
        self,
    ) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        termination = "meta_flow.workflow.cr_termination"
        index = "meta_flow.workflow.cr_index"
        projection = "meta_flow.workflow.cr_projection"
        records = "meta_flow.workflow.cr_records"
        model = "meta_flow.workflow.cr_model"
        allowed_edges = {
            (index, model),
            (index, projection),
            (index, records),
            (projection, model),
            (projection, records),
            (records, model),
            (termination, index),
            (termination, model),
            (termination, projection),
            (termination, records),
        }

        report = module_boundaries.check_import_graph(
            repo_root,
            targets={termination},
            touched={index, projection, records, model},
            allowed_edges=allowed_edges,
        )

        self.assertEqual(
            sorted({termination, index, projection, records, model}),
            report["closure"],
        )
        self.assertEqual(sorted(allowed_edges), report["edges"])
        self.assertEqual([], report["undeclared_edges"])
        self.assertEqual([], report["self_loops"])
        self.assertEqual([], report["known_scc_drift"])
        self.assertEqual([], report["findings"])

        source = repo_root / "meta_flow" / "workflow" / "cr_termination.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        direct_modules = {
            node.module
            for node in tree.body
            if isinstance(node, ast.ImportFrom) and node.module
        }
        self.assertEqual(
            {index, projection, records, model},
            {
                module
                for module in direct_modules
                if module.startswith("meta_flow.workflow.cr_")
            },
        )
        self.assertTrue(
            {
                "meta_flow.workflow.cr_status_sync",
                "meta_flow.workflow.cr_status_transaction",
                "meta_flow.workflow.cr_lifecycle",
                "meta_flow.workflow.cr_cli",
            }.isdisjoint(direct_modules)
        )

    def test_projection_has_exact_downward_edge_to_records(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        projection = "meta_flow.workflow.cr_projection"
        records = "meta_flow.workflow.cr_records"
        known_workspace_scc = frozenset(
            {
                "meta_flow.workspace.git_sync",
                "meta_flow.workspace.legacy_route_adapter",
                "meta_flow.workspace.routing",
            }
        )

        report = module_boundaries.check_import_graph(
            repo_root,
            targets={projection},
            touched={records},
            allowed_edges={(projection, records)},
            known_sccs={
                known_workspace_scc: frozenset(
                    {
                        (
                            "meta_flow.workspace.git_sync",
                            "meta_flow.workspace.legacy_route_adapter",
                        ),
                        (
                            "meta_flow.workspace.git_sync",
                            "meta_flow.workspace.routing",
                        ),
                        (
                            "meta_flow.workspace.legacy_route_adapter",
                            "meta_flow.workspace.git_sync",
                        ),
                        (
                            "meta_flow.workspace.routing",
                            "meta_flow.workspace.legacy_route_adapter",
                        ),
                    }
                )
            },
        )

        self.assertEqual([projection, records], report["closure"])
        self.assertEqual([(projection, records)], report["edges"])
        self.assertNotIn((records, projection), report["edges"])
        self.assertEqual([], report["undeclared_edges"])
        self.assertEqual([sorted(known_workspace_scc)], report["sccs"])
        self.assertEqual([], report["self_loops"])
        self.assertEqual([], report["known_scc_drift"])
        self.assertEqual([], report["findings"])

    def test_status_transaction_has_exact_negative_edge_to_index_owner(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        transaction = "meta_flow.workflow.cr_status_transaction"
        index_owner = "meta_flow.workflow.cr_index"

        report = module_boundaries.check_import_graph(
            repo_root,
            targets={transaction},
            touched={index_owner},
            allowed_edges=set(),
        )

        self.assertEqual([index_owner, transaction], report["closure"])
        self.assertEqual([], report["edges"])
        self.assertEqual([], report["undeclared_edges"])
        self.assertEqual([], report["findings"])

    def test_ast_graph_checks_declared_edges_cycles_and_known_scc_freeze(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_python(root, "app.a", "from app.b import value\n")
            _write_python(root, "app.b", "import app.c\n")
            _write_python(root, "app.c", "import app.a\n")
            _write_python(root, "workspace.git_sync", "import workspace.routing\n")
            _write_python(root, "workspace.legacy_route_adapter", "import workspace.git_sync\n")
            _write_python(root, "workspace.routing", "import workspace.legacy_route_adapter\n")

            known = frozenset(
                {"workspace.git_sync", "workspace.legacy_route_adapter", "workspace.routing"}
            )
            report = module_boundaries.check_import_graph(
                root,
                targets={"app.a"},
                touched={"app.a", "app.b", "app.c"},
                allowed_edges={
                    ("app.a", "app.b"),
                    ("app.b", "app.c"),
                    ("app.c", "app.a"),
                },
                known_sccs={
                    known: frozenset(
                        {
                            ("workspace.git_sync", "workspace.routing"),
                            ("workspace.legacy_route_adapter", "workspace.git_sync"),
                            ("workspace.routing", "workspace.legacy_route_adapter"),
                        }
                    )
                },
            )

            self.assertEqual([], report["undeclared_edges"])
            self.assertEqual([], report["known_scc_drift"])
            self.assertIn("SCC(size>1): app.a,app.b,app.c", report["findings"])
            self.assertNotIn(
                "SCC(size>1): workspace.git_sync,workspace.legacy_route_adapter,workspace.routing",
                report["findings"],
            )

    def test_graph_rejects_undeclared_edge_self_loop_and_known_scc_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_python(root, "app.a", "import app.b\n")
            _write_python(root, "app.b", "import app.b\n")
            _write_python(root, "workspace.git_sync", "import workspace.routing\n")
            _write_python(root, "workspace.legacy_route_adapter", "import workspace.git_sync\n")
            _write_python(root, "workspace.routing", "import workspace.git_sync\n")

            report = module_boundaries.check_import_graph(
                root,
                targets={"app.a"},
                touched={"app.a", "app.b"},
                allowed_edges=set(),
                known_sccs={
                    frozenset(
                        {"workspace.git_sync", "workspace.legacy_route_adapter", "workspace.routing"}
                    ): frozenset()
                },
            )

            self.assertEqual(["app.a", "app.b"], report["closure"])
            self.assertIn(("app.a", "app.b"), report["undeclared_edges"])
            self.assertEqual(["app.b"], report["self_loops"])
            self.assertEqual(
                [
                    "known SCC membership/edge drift: "
                    "workspace.git_sync,workspace.legacy_route_adapter,workspace.routing"
                ],
                report["known_scc_drift"],
            )
            self.assertFalse(any(finding.startswith("SCC(size>1): workspace") for finding in report["findings"]))

    def test_graph_ignores_function_imports_and_scope_external_edges(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_python(root, "app.a", "import app.c\n\ndef late():\n    import app.b\n")
            _write_python(root, "app.b", "def late():\n    import app.a\n")
            _write_python(root, "app.c", "def late():\n    import app.a\n")

            report = module_boundaries.check_import_graph(
                root,
                targets={"app.a"},
                touched={"app.a"},
                allowed_edges=set(),
            )

            self.assertEqual(["app.a"], report["closure"])
            self.assertEqual([], report["edges"])
            self.assertEqual([], report["undeclared_edges"])
            self.assertEqual([], report["sccs"])
            self.assertEqual([], report["findings"])

    def test_i3_future_owner_leaves_do_not_import_the_facade_and_support_is_inert(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        support = repo_root / "tests" / "cr_lifecycle_test_support.py"
        support_tree = ast.parse(support.read_text(encoding="utf-8"))
        support_members = {
            node.name
            for node in support_tree.body
            if isinstance(node, (ast.FunctionDef, ast.ClassDef))
        }
        self.assertEqual(
            {
                "LifecycleFixtureCollaborators",
                "normalize_compatibility_snapshot",
                "init_binding_project",
                "write_cr",
                "write_termination_fixture",
            },
            support_members,
        )
        self.assertFalse(
            any(
                isinstance(node, (ast.FunctionDef, ast.ClassDef))
                and node.name.startswith("test_")
                for node in ast.walk(support_tree)
            )
        )
        self.assertFalse(any(isinstance(node, ast.Assert) for node in ast.walk(support_tree)))
        self.assertFalse(
            any(
                (
                    isinstance(node, ast.ImportFrom)
                    and (node.module or "").startswith("meta_flow")
                )
                or (
                    isinstance(node, ast.Import)
                    and any(alias.name.startswith("meta_flow") for alias in node.names)
                )
                for node in ast.walk(support_tree)
            )
        )
        imported_roots = {
            (node.module or "").split(".")[0]
            for node in ast.walk(support_tree)
            if isinstance(node, ast.ImportFrom)
        }
        imported_roots |= {
            alias.name.split(".")[0]
            for node in ast.walk(support_tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        self.assertTrue(imported_roots.isdisjoint({"pytest", "unittest"}))

        for name in ("test_cr_status_sync.py", "test_cr_status_transaction.py"):
            with self.subTest(owner_test=name):
                tree = ast.parse(
                    (repo_root / "tests" / name).read_text(encoding="utf-8")
                )
                imports_facade_test_or_production = any(
                    (
                        isinstance(node, ast.ImportFrom)
                        and (node.module or "")
                        in {"test_cr_lifecycle", "meta_flow.workflow.cr_lifecycle"}
                    )
                    or (
                        isinstance(node, ast.Import)
                        and any(
                            alias.name
                            in {"test_cr_lifecycle", "meta_flow.workflow.cr_lifecycle"}
                            for alias in node.names
                        )
                    )
                    for node in ast.walk(tree)
                )
                self.assertFalse(imports_facade_test_or_production)

        owner_modules = [
            path
            for path in (repo_root / "meta_flow" / "workflow").glob("cr_*.py")
            if path.name != "cr_lifecycle.py"
        ]
        for path in owner_modules:
            with self.subTest(owner=path.name):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                imports_facade = any(
                    (
                        isinstance(node, ast.ImportFrom)
                        and node.module == "meta_flow.workflow.cr_lifecycle"
                    )
                    or (
                        isinstance(node, ast.Import)
                        and any(alias.name == "meta_flow.workflow.cr_lifecycle" for alias in node.names)
                    )
                    for node in ast.walk(tree)
                )
                self.assertFalse(imports_facade)


if __name__ == "__main__":
    unittest.main()
