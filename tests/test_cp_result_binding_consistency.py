from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from meta_flow.checks import cp_result


def _init_sibling_binding(root: Path) -> tuple[Path, Path]:
    release = root / "meta-flow"
    process = root / "meta-flow-process"
    for repository in (release, process):
        repository.mkdir()
        subprocess.run(
            ["git", "init", "-b", "main"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        )
    binding = release / ".meta-flow" / "workspace.yaml"
    binding.parent.mkdir()
    binding.write_text(
        "schema_version: 1\n"
        "layout_version: independent-process-repo-v1\n"
        "workflow_model: vnext\n"
        "project_id: fixture-project\n"
        "repo_role: release\n"
        "route_mode: sibling-binding\n"
        "process_repo:\n"
        "  anchor: workspace_parent\n"
        "  relative_path: meta-flow-process\n",
        encoding="utf-8",
    )
    (process / ".meta-flow-process.yaml").write_text(
        "schema_version: 1\n"
        "layout_version: independent-process-repo-v1\n"
        "workflow_model: vnext\n"
        "project_id: fixture-project\n"
        "repo_role: process\n"
        "route_mode: sibling-binding\n"
        "release_repo:\n"
        "  anchor: workspace_parent\n"
        "  relative_path: meta-flow\n",
        encoding="utf-8",
    )
    (process / "PROJECT.yaml").write_text(
        "schema_version: 1\nproject_id: fixture-project\nname: Fixture Project\nstatus: active\n",
        encoding="utf-8",
    )
    return release, process


def _write_cp4_result(process: Path, *, summary_decision: str | None = None) -> Path:
    result = process / "checks" / "CP4-CR064.result.json"
    result.parent.mkdir(parents=True, exist_ok=True)
    result.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "checkpoint": "CP4",
                "checkpoint_id": "CP4-CR064",
                "cr_id": "CR-064",
                "items": [
                    {
                        "id": "CP4-01",
                        "name": "fixture",
                        "status": "PASS",
                        "severity": "INFO",
                        "evidence_refs": [],
                    }
                ],
                "blockers": [],
                "waivers": [],
                "decision": "PASS",
                "next_route": "CP5",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (process / "checks" / "CP0-CR-064.route-plan.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "decision": "PASS",
                "stages": [],
                "checkpoint_applicability": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    if summary_decision is not None:
        result.with_suffix(".summary.md").write_text(
            f"# CP4 Summary\n\nDecision: {summary_decision}\nCR: CR-064\n",
            encoding="utf-8",
        )
    return result


class CPResultBindingConsistencyTests(unittest.TestCase):
    def test_sibling_process_route_plan_returns_semantic_verdicts_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process = _init_sibling_binding(Path(directory))
            _write_cp4_result(process)

            passed_output = StringIO()
            with redirect_stdout(passed_output):
                passed = cp_result.main(
                    [
                        "result-check",
                        "--result",
                        "process/checks/CP4-CR064.result.json",
                        "--project-root",
                        str(release),
                        "--check-consistency",
                    ]
                )

            self.assertEqual(0, passed)
            self.assertIn("CP Result Check: OK", passed_output.getvalue())

            _write_cp4_result(process, summary_decision="FAIL")
            failed_output = StringIO()
            with redirect_stdout(failed_output):
                failed = cp_result.main(
                    [
                        "result-check",
                        "--result",
                        "process/checks/CP4-CR064.result.json",
                        "--project-root",
                        str(release),
                        "--check-consistency",
                    ]
                )

            self.assertEqual(1, failed)
            self.assertIn("CP Result Check: FAIL", failed_output.getvalue())
            self.assertIn("summary decision does not match", failed_output.getvalue())
            self.assertNotIn("Traceback", failed_output.getvalue())


if __name__ == "__main__":
    unittest.main()
