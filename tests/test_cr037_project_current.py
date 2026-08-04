from __future__ import annotations

import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from meta_flow import cli
from meta_flow.project import scaffold
from meta_flow.project import state as project_state
from meta_flow.state import current
from meta_flow.work.io_metrics import IOMetrics
from meta_flow.work.read_context import OperationReadContext
from meta_flow.workspace import routing


def write_current_state(root: Path, *, project_id: str = "demo-project") -> None:
    payload = current.default_current_state(root, project_id=project_id)
    current.write_current_state(root, payload)


def write_project_current(root: Path, payload: dict) -> Path:
    path = root / project_state.PROJECT_CURRENT_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


class ProjectCurrentTests(unittest.TestCase):
    def test_state_and_health_loaders_reuse_one_operation_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_current_state(root)
            health_path = root / current.WORKFLOW_HEALTH_REL
            health_path.write_text(
                json.dumps({"schema_version": 1, "phase_counters": {}}),
                encoding="utf-8",
            )
            metrics = IOMetrics("current-loaders", enabled=True)
            context = OperationReadContext(
                root / "process",
                operation_id="current-loaders",
                operation_kind="check",
                allowed_reads=(
                    current.STATE_CURRENT_REL.as_posix(),
                    current.WORKFLOW_HEALTH_REL.as_posix(),
                ),
                metrics=metrics,
            )

            self.assertEqual(
                current.load_current_state(root, read_context=context),
                current.load_current_state(root, read_context=context),
            )
            self.assertEqual(
                current.load_workflow_health(root, read_context=context),
                current.load_workflow_health(root, read_context=context),
            )

            totals = metrics.summary()["totals"]
            self.assertEqual(2, totals["physical_reads"])
            self.assertGreaterEqual(totals["cache_hits"], 2)

    def test_current_and_health_skip_timestamp_only_rewrites(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_current_state(root)
            current_path = current.refresh_current_entry(root)
            state_ref = root / "process/current/state.ref"
            os.utime(current_path, (1, 1))
            os.utime(state_ref, (1, 1))

            current.refresh_current_entry(root)

            self.assertEqual(1_000_000_000, current_path.stat().st_mtime_ns)
            self.assertEqual(1_000_000_000, state_ref.stat().st_mtime_ns)

            current.update_workflow_health(
                root,
                phase="routine",
                increments={"phase_round_count": 1},
            )
            health_path = root / current.WORKFLOW_HEALTH_REL
            state_path = root / current.STATE_CURRENT_REL
            health_before = health_path.read_bytes()
            state_before = state_path.read_bytes()

            current.update_workflow_health(
                root,
                phase="routine",
                increments={"phase_round_count": 0},
            )

            self.assertEqual(health_before, health_path.read_bytes())
            self.assertEqual(state_before, state_path.read_bytes())

    def test_workspace_scaffold_dirs_include_project(self) -> None:
        self.assertIn("project", routing.PROCESS_SCAFFOLD_DIRS)

    def test_minimal_project_current_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "process" / "docs").mkdir(parents=True)
            (root / "process" / "docs" / "design.md").write_text("# design\n", encoding="utf-8")
            write_project_current(
                root,
                {
                    "schema_version": 1,
                    "project_id": "demo-project",
                    "project_name": "demo-project",
                    "updated_at": "2026-07-03T00:00:00+00:00",
                    "active_governance_refs": [],
                    "source_refs": [{"kind": "design", "path": "process/docs/design.md"}],
                },
            )

            errors, warnings = project_state.validate_project_current(root)

            self.assertEqual([], errors)
            self.assertEqual([], warnings)

    def test_unknown_forbidden_and_over_budget_fields_fail(self) -> None:
        cases = [
            ("unknown", {"surprise": "field"}, "unknown field"),
            ("forbidden", {"history": []}, "must not store history"),
            (
                "secret",
                {
                    "source_refs": [
                        {"kind": "x", "path": "process/x.md", "secret_token": "redacted"}
                    ]
                },
                "credential-like",
            ),
            (
                "over_budget",
                {"active_governance_refs": ["process/" + ("x" * 17000)]},
                "exceeds budget",
            ),
        ]
        for _name, extra, expected in cases:
            with self.subTest(_name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                payload = {
                    "schema_version": 1,
                    "project_id": "demo-project",
                    "project_name": "demo-project",
                    "updated_at": "2026-07-03T00:00:00+00:00",
                    "active_governance_refs": [],
                    "source_refs": [],
                }
                payload.update(extra)
                write_project_current(root, payload)

                errors, _warnings = project_state.validate_project_current(root)

                self.assertTrue(errors)
                self.assertIn(expected, "\n".join(errors))

    def test_absolute_parent_escape_and_quant_lab_refs_fail(self) -> None:
        refs = ["/tmp/project.json", "../outside.json", "process/quant-lab/PROJECT.current.json"]
        for ref in refs:
            with self.subTest(ref=ref), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                write_project_current(
                    root,
                    {
                        "schema_version": 1,
                        "project_id": "demo-project",
                        "project_name": "demo-project",
                        "updated_at": "2026-07-03T00:00:00+00:00",
                        "scale_ref": ref,
                    },
                )

                errors, _warnings = project_state.validate_project_current(root)

                self.assertTrue(errors)
                self.assertIn("project-relative path", "\n".join(errors))

    def test_broken_project_current_ref_fails_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_project_current(
                root,
                {
                    "schema_version": 1,
                    "project_id": "demo-project",
                    "project_name": "demo-project",
                    "updated_at": "2026-07-03T00:00:00+00:00",
                    "source_refs": [{"kind": "design", "path": "process/docs/missing.md"}],
                },
            )

            errors, _warnings = project_state.validate_project_current(root)
            shape_only_errors, _shape_warnings = project_state.validate_project_current(
                root, require_ref_targets=False
            )

            self.assertIn("points to missing file", "\n".join(errors))
            self.assertEqual([], shape_only_errors)

    def test_dry_run_scaffold_does_not_write_files_or_current_ref(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_current_state(root)

            plan = scaffold.build_project_scaffold_plan(root)

            self.assertFalse((root / "process" / "project").exists())
            self.assertFalse((root / project_state.PROJECT_CURRENT_REL).exists())
            self.assertNotIn("project_state_ref", current.load_current_state(root))
            self.assertEqual(["create", "create"], [action.action for action in plan.actions])

    def test_apply_scaffold_creates_project_current_and_updates_current_ref(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_current_state(root, project_id="demo-project")

            plan = scaffold.build_project_scaffold_plan(root)
            result = scaffold.apply_project_scaffold(plan)

            self.assertEqual(["process/project/PROJECT.current.json"], result["created"])
            self.assertEqual(
                "process/project/PROJECT.current.json", result["updated_state_project_ref"]
            )
            project_payload = project_state.load_project_current(root)
            self.assertEqual("demo-project", project_payload["project_id"])
            state_payload = current.load_current_state(root)
            self.assertEqual(
                "process/project/PROJECT.current.json", state_payload["project_state_ref"]
            )
            self.assertNotIn("project_name", state_payload)
            self.assertNotIn("roadmap_ref", state_payload)
            errors, _warnings = project_state.validate_project_current(root)
            self.assertEqual([], errors)

    def test_apply_scaffold_is_noop_for_existing_valid_project_current(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_current_state(root, project_id="demo-project")
            plan = scaffold.build_project_scaffold_plan(root)
            scaffold.apply_project_scaffold(plan)
            before = (root / project_state.PROJECT_CURRENT_REL).read_text(encoding="utf-8")

            second_plan = scaffold.build_project_scaffold_plan(root)
            second_result = scaffold.apply_project_scaffold(second_plan)

            self.assertEqual([], second_result["created"])
            self.assertEqual(
                before, (root / project_state.PROJECT_CURRENT_REL).read_text(encoding="utf-8")
            )
            self.assertIn("noop", [action.action for action in second_plan.actions])

    def test_apply_scaffold_conflict_does_not_overwrite_or_write_current_ref(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_current_state(root, project_id="demo-project")
            conflict_path = root / project_state.PROJECT_CURRENT_REL
            conflict_path.parent.mkdir(parents=True, exist_ok=True)
            conflict_path.write_text('{"not": "valid"}\n', encoding="utf-8")
            before = conflict_path.read_text(encoding="utf-8")

            plan = scaffold.build_project_scaffold_plan(root)
            with self.assertRaises(FileExistsError):
                scaffold.apply_project_scaffold(plan)

            self.assertEqual(before, conflict_path.read_text(encoding="utf-8"))
            self.assertNotIn("project_state_ref", current.load_current_state(root))

    def test_current_state_rejects_embedded_project_fields_and_invalid_project_ref(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_current_state(root, project_id="demo-project")

            with self.assertRaises(current.StateValidationError) as embedded:
                current.update_current_state(root, {"roadmap_ref": "process/project/ROADMAP.yaml"})
            with self.assertRaises(current.StateValidationError) as invalid_ref:
                current.update_current_state(root, {"project_state_ref": "../PROJECT.current.json"})

            self.assertIn("unknown_patch_key", str(embedded.exception))
            self.assertIn("ref_path", str(invalid_ref.exception))

    def test_current_state_check_fails_on_broken_project_state_ref(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_current_state(root, project_id="demo-project")
            current.update_current_state(
                root, {"project_state_ref": "process/project/PROJECT.current.json"}
            )

            output = StringIO()
            with redirect_stdout(output):
                exit_code = current.main(
                    ["check", "--project-root", str(root), "--mode", "enforce"]
                )

            self.assertEqual(1, exit_code)
            self.assertIn("project_state_ref points to missing file", output.getvalue())

    def test_project_cli_scaffold_and_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_current_state(root, project_id="demo-project")

            dry_run = StringIO()
            with redirect_stdout(dry_run):
                dry_code = scaffold.main(["--project-root", str(root)])
            self.assertEqual(0, dry_code)
            self.assertFalse((root / project_state.PROJECT_CURRENT_REL).exists())

            apply_output = StringIO()
            with redirect_stdout(apply_output):
                apply_code = scaffold.main(["--project-root", str(root), "--apply"])
            check_output = StringIO()
            with redirect_stdout(check_output):
                with self.assertRaises(SystemExit) as raised:
                    cli._run_project(["check", "--project-root", str(root)])

            self.assertEqual(0, apply_code)
            self.assertEqual(0, raised.exception.code)
            self.assertIn("Project Current Check: OK", check_output.getvalue())


if __name__ == "__main__":
    unittest.main()
