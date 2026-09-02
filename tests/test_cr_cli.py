from __future__ import annotations

import ast
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from meta_flow.policies import public_operations
from meta_flow.workflow import cr_cli, git_branch_lifecycle


class CRCliContractTests(unittest.TestCase):
    def _dependencies(self, root: Path) -> dict[str, object]:
        plan = SimpleNamespace(
            decision="READY",
            as_dict=lambda: {
                "decision": "READY",
                "mutation_count": 0,
                "planned_mutation_count": 1,
            },
        )
        cr_path = root / "process" / "changes" / "CR-101.md"
        return {
            "AggregateCompletionProjector": Mock,
            "apply_bootstrap_cr": Mock(return_value={"decision": "PASS", "paths": {}}),
            "apply_cr_termination": Mock(return_value={"status": "PASS"}),
            "apply_status_sync": Mock(return_value={"status": "PASS"}),
            "build_impact_report": Mock(return_value={"summary": {}}),
            "close_cr": Mock(return_value={"cr": cr_path}),
            "collect_check_errors": Mock(return_value=[]),
            "collect_check_warnings": Mock(return_value=[]),
            "conflict_report": Mock(return_value=([], [])),
            "discover_formal_crs": Mock(return_value={"CR-101": cr_path}),
            "inspect_bootstrap_transactions": Mock(
                return_value={"decision": "PASS", "transactions": []}
            ),
            "inspect_status_sync_transactions": Mock(
                return_value={"decision": "PASS", "transaction_count": 0}
            ),
            "load_status_sync_authorization": Mock(return_value=object()),
            "load_termination_authorization": Mock(return_value=object()),
            "plan_cr_termination": Mock(return_value=plan),
            "plan_bootstrap_cr": Mock(return_value=plan),
            "plan_index": Mock(
                return_value={
                    "decision": "READY",
                    "mutation_count": 0,
                    "planned_mutation_count": 1,
                    "expected": {},
                }
            ),
            "plan_status_sync": Mock(return_value=plan),
            "proposed_conflict_report": Mock(
                return_value={
                    "decision": "NO_CONFLICT",
                    "mutation_count": 0,
                    "planned_mutation_count": 0,
                    "conflicts": [],
                    "warnings": [],
                }
            ),
            "recover_status_sync_transaction": Mock(
                return_value={"status": "RECOVERED", "mutation_count": 0}
            ),
            "recover_bootstrap_transaction": Mock(
                return_value={"decision": "RECOVERED", "mutation_count": 0}
            ),
            "rel": Mock(return_value="process/changes/CR-INDEX.json"),
            "render_cr_brief": Mock(return_value="# CR-101\n"),
            "render_goal_brief": Mock(return_value="# GOAL-001\n"),
            "summary_from_cr_file": Mock(return_value={"id": "CR-101"}),
            "sync_cr_status": Mock(return_value={"cr": cr_path}),
            "write_impact_report": Mock(return_value=root / "impact.json"),
            "write_index": Mock(return_value=root / "process" / "changes" / "CR-INDEX.json"),
            "write_summary": Mock(return_value=root / "summary.json"),
        }

    def test_exact_inventory_dependencies_and_function_span_limits(self) -> None:
        path = Path(cr_cli.__file__)
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        expected = {
            "aggregate_main",
            "_print_cr_help",
            "_build_cr_command_parser",
            "_dispatch_cr_projection_command",
            "_dispatch_cr_close_or_termination_command",
            "_dispatch_cr_status_sync_command",
            "_dispatch_cr_status_sync_recovery_command",
            "_dispatch_cr_diagnostic_command",
            "main",
            "render_scope_amend_plan",
            "render_scope_amend_apply",
            "scope_amend_main",
            "_load_scope_amend_receipts",
            "_register_governance_payloads",  # CR-076 S02 GAP-03 治理 kind 注册
            "load_cli_authorization",  # CR-076 S02 FA8 exactly-one 共享 helper
        }
        functions = {
            node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
        }
        self.assertEqual(expected, set(functions))
        self.assertFalse(any(isinstance(node, ast.ClassDef) for node in tree.body))
        for name, node in functions.items():
            with self.subTest(name=name):
                lines = source.splitlines()[node.lineno - 1 : node.end_lineno]
                logical = sum(
                    bool(line.strip()) and not line.lstrip().startswith("#")
                    for line in lines
                )
                self.assertLessEqual(node.end_lineno - node.lineno + 1, 140)
                self.assertLessEqual(logical, 125)
        main_node = functions["main"]
        main_lines = source.splitlines()[main_node.lineno - 1 : main_node.end_lineno]
        self.assertLessEqual(main_node.end_lineno - main_node.lineno + 1, 80)
        self.assertLessEqual(
            sum(bool(line.strip()) for line in main_lines),
            70,
        )
        direct_modules = {
            node.module
            for node in tree.body
            if isinstance(node, ast.ImportFrom) and node.module
        }
        self.assertNotIn("meta_flow.workflow.cr_lifecycle", direct_modules)
        self.assertEqual(
            {
                "meta_flow.workflow.cr_analysis",
                "meta_flow.workflow.cr_index",
                "meta_flow.workflow.cr_model",
                "meta_flow.workflow.cr_projection",
                "meta_flow.workflow.cr_records",
                "meta_flow.workflow.cr_status_sync",
                "meta_flow.workflow.cr_status_transaction",
                "meta_flow.workflow.cr_termination",
            },
            {
                module
                for module in direct_modules
                if module.startswith("meta_flow.workflow.cr_")
            },
        )

    def test_21_commands_dispatch_with_compatible_exit_classes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transaction_id = "a" * 32
            cases = {
                "bootstrap": ["--id", "CR-101"],
                "index": [],
                "summary": ["--id", "CR-101"],
                "brief": ["--id", "CR-101"],
                "goal-brief": ["--goal-ref", "GOAL-001"],
                "impact-report": [],
                "terminate": ["--id", "CR-101"],
                "status-sync": ["--id", "CR-101"],
                "status-sync-inspect": [],
                "status-sync-resume": ["--transaction-id", transaction_id],
                "status-sync-rollback": ["--transaction-id", transaction_id],
                "status-sync-abandon": ["--transaction-id", transaction_id],
                "close": ["--id", "CR-101"],
                "check": [],
                "conflicts": ["--id", "CR-101"],
            }
            observed: set[str] = set()
            for command, command_args in cases.items():
                with self.subTest(command=command):
                    dependencies = self._dependencies(root)
                    output = StringIO()
                    with redirect_stdout(output):
                        code = cr_cli.main(
                            [
                                command,
                                *command_args,
                                "--project-root",
                                str(root),
                            ],
                            dispatch_dependencies=dependencies,
                        )
                    self.assertEqual(0, code, output.getvalue())
                    observed.add(command)

            with patch.object(cr_cli, "aggregate_main", return_value=0) as aggregate:
                self.assertEqual(
                    0,
                    cr_cli.main(
                        ["aggregate"],
                        dispatch_dependencies=self._dependencies(root),
                    ),
                )
                aggregate.assert_called_once()
            observed.add("aggregate")

            with patch.object(public_operations, "main", return_value=0) as operations:
                self.assertEqual(
                    0,
                    cr_cli.main(
                        ["public-operations-check"],
                        dispatch_dependencies=self._dependencies(root),
                    ),
                )
                operations.assert_called_once_with([])
            observed.add("public-operations-check")

            with patch.object(git_branch_lifecycle, "branch_main", return_value=0) as branch:
                for command in (
                    "branch-open",
                    "branch-publish",
                    "branch-merge",
                    "branch-finish",
                ):
                    with self.subTest(command=command):
                        self.assertEqual(
                            0,
                            cr_cli.main(
                                [command],
                                dispatch_dependencies=self._dependencies(root),
                            ),
                        )
                        observed.add(command)
                self.assertEqual(4, branch.call_count)

            self.assertEqual(
                {
                    "aggregate",
                    "bootstrap",
                    "branch-finish",
                    "branch-merge",
                    "branch-open",
                    "branch-publish",
                    "brief",
                    "check",
                    "close",
                    "conflicts",
                    "goal-brief",
                    "impact-report",
                    "index",
                    "public-operations-check",
                    "status-sync",
                    "status-sync-abandon",
                    "status-sync-inspect",
                    "status-sync-resume",
                    "status-sync-rollback",
                    "summary",
                    "terminate",
                },
                observed,
            )

    def test_bootstrap_forwards_explicit_rebuild_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dependencies = self._dependencies(root)

            with redirect_stdout(StringIO()):
                self.assertEqual(
                    0,
                    cr_cli.main(
                        [
                            "bootstrap",
                            "--id",
                            "CR-101",
                            "--rebuild",
                            "--project-root",
                            str(root),
                        ],
                        dispatch_dependencies=dependencies,
                    ),
                )

            dependencies["plan_bootstrap_cr"].assert_called_once_with(
                root.resolve(),
                cr_id="CR-101",
                title="Meta Flow adoption bootstrap",
                scope="Bootstrap Meta Flow adoption readiness for this target project.",
                gate_status="not_started",
                readiness="not_ready",
                rebuild_corrupt=True,
                effective_at="",
            )

    def test_help_unknown_and_invalid_paths_keep_exit_mapping(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(0, cr_cli.main(["--help"]))
        help_text = output.getvalue()
        for command in (
            "bootstrap",
            "index",
            "summary",
            "brief",
            "goal-brief",
            "impact-report",
            "terminate",
            "status-sync",
            "status-sync-inspect",
            "status-sync-resume",
            "status-sync-rollback",
            "status-sync-abandon",
            "aggregate",
            "branch-open",
            "branch-publish",
            "branch-merge",
            "branch-finish",
            "close",
            "check",
            "public-operations-check",
            "conflicts",
        ):
            with self.subTest(command=command):
                self.assertIn(command, help_text)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dependencies = self._dependencies(root)
            dependencies["collect_check_errors"] = Mock(return_value=["broken"])
            with redirect_stdout(StringIO()):
                self.assertEqual(
                    1,
                    cr_cli.main(
                        ["check", "--project-root", str(root)],
                        dispatch_dependencies=dependencies,
                    ),
                )
                self.assertEqual(
                    2,
                    cr_cli.main(
                        [
                            "conflicts",
                            "--id",
                            "CR-999",
                            "--proposed",
                            "--output",
                            str(root / "forbidden.json"),
                            "--project-root",
                            str(root),
                        ],
                        dispatch_dependencies=self._dependencies(root),
                    ),
                )
            with self.assertRaises(SystemExit):
                cr_cli.main(
                    ["unknown", "--project-root", str(root)],
                    dispatch_dependencies=self._dependencies(root),
                )


if __name__ == "__main__":
    unittest.main()
