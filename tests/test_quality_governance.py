from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from meta_flow.checks import quality_governance


REPO_ROOT = Path(__file__).resolve().parents[1]


def copy_policy_templates(root: Path) -> None:
    target = root / "process" / "policies"
    target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REPO_ROOT / "process" / "policies" / "QUALITY-MODEL.yaml", target / "QUALITY-MODEL.yaml")
    shutil.copyfile(REPO_ROOT / "process" / "policies" / "EVAL-MATRIX.yaml", target / "EVAL-MATRIX.yaml")


def write_cp1_result(root: Path) -> Path:
    path = root / "process" / "checks" / "CP1-MF018.result.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "checkpoint": "CP1",
                "checkpoint_id": "CP1-MF018",
                "profile": "standard-code",
                "cr_id": "MF-018",
                "context_ref": "process/context/MF-018.KICKOFF.context.json",
                "items": [
                    {
                        "id": "CP1-01",
                        "category": "quality",
                        "name": "Kickoff context exists",
                        "status": "PASS",
                        "severity": "INFO",
                        "evidence_refs": ["process/context/MF-018.KICKOFF.context.json"],
                        "owner": "host-orchestrator",
                        "route_on_fail": "",
                        "waiver_ref": None,
                        "notes": "",
                    }
                ],
                "blockers": [],
                "waivers": [],
                "decision": "PASS",
                "next_route": "CP2",
                "checked_at": "2026-06-21T00:00:00+00:00",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


class QualityGovernanceTests(unittest.TestCase):
    def test_quality_init_writes_default_policies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            stream = StringIO()
            with redirect_stdout(stream):
                exit_code = quality_governance.quality_main(["init", "--project-root", str(root)])

            self.assertEqual(0, exit_code)
            self.assertTrue((root / "process" / "policies" / "QUALITY-MODEL.yaml").is_file())
            self.assertTrue((root / "process" / "policies" / "EVAL-MATRIX.yaml").is_file())
            self.assertIn("QUALITY-MODEL.yaml", stream.getvalue())
            self.assertEqual(([], []), quality_governance.validate_quality_model(root))
            self.assertEqual(([], []), quality_governance.validate_eval_matrix(root))

    def test_policy_templates_pass_model_and_eval_checks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            copy_policy_templates(root)

            model_errors, model_warnings = quality_governance.validate_quality_model(root)
            eval_errors, eval_warnings = quality_governance.validate_eval_matrix(root)

            self.assertEqual([], model_errors)
            self.assertEqual([], model_warnings)
            self.assertEqual([], eval_errors)
            self.assertEqual([], eval_warnings)

    def test_quality_model_rejects_manual_metrics_truth_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            copy_policy_templates(root)
            path = root / "process" / "policies" / "QUALITY-MODEL.yaml"
            text = path.read_text(encoding="utf-8")
            path.write_text(text.replace("manual_truth_source: false", "manual_truth_source: true"), encoding="utf-8")

            errors, _warnings = quality_governance.validate_quality_model(root)

            self.assertIn("QUALITY-MODEL metric_derivation.manual_truth_source must be false", errors)

    def test_eval_matrix_rejects_unknown_quality_dimension(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            copy_policy_templates(root)
            path = root / "process" / "policies" / "EVAL-MATRIX.yaml"
            text = path.read_text(encoding="utf-8")
            path.write_text(text.replace("requirements_traceability", "unknown_dimension", 1), encoding="utf-8")

            errors, _warnings = quality_governance.validate_eval_matrix(root)

            self.assertTrue(any("references unknown quality_dimension: unknown_dimension" in error for error in errors))

    def test_quality_cli_and_doctor_commands_report_ok(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            copy_policy_templates(root)

            stream = StringIO()
            with redirect_stdout(stream):
                model_code = quality_governance.quality_main(["model-check", "--project-root", str(root)])
                eval_code = quality_governance.quality_main(["eval-check", "--project-root", str(root)])
                doctor_code = quality_governance.run_quality_doctor(root)

            self.assertEqual(0, model_code)
            self.assertEqual(0, eval_code)
            self.assertEqual(0, doctor_code)
            output = stream.getvalue()
            self.assertIn("Quality Model Check: OK", output)
            self.assertIn("Eval Matrix Check: OK", output)
            self.assertIn("Quality Doctor: OK", output)
            self.assertIn("manual_metrics_truth_source: none", output)

    def test_workflow_doctor_derives_metrics_from_results_and_ledgers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_cp1_result(root)
            ledger = root / "process" / "state" / "RUN-LEDGER.ndjson"
            ledger.parent.mkdir(parents=True, exist_ok=True)
            ledger.write_text(
                json.dumps(
                    {
                        "event_id": "RUN-0001",
                        "event_type": "run",
                        "command": "meta-flow quality model-check",
                        "result": "PASS",
                        "timestamp": "2026-06-21T00:00:00+00:00",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            stream = StringIO()
            with redirect_stdout(stream):
                exit_code = quality_governance.run_workflow_doctor(root)

            self.assertEqual(0, exit_code)
            output = stream.getvalue()
            self.assertIn("Workflow Doctor: OK", output)
            self.assertIn("metrics_mode: derived-only", output)
            self.assertIn("cp_result_files: 1", output)
            self.assertIn("- PASS: 1", output)
            self.assertIn("- run: 1", output)
            self.assertIn("manual_metrics_truth_source: none", output)


if __name__ == "__main__":
    unittest.main()
