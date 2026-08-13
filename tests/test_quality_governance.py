from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from meta_flow.checks import quality_governance

REPO_ROOT = Path(__file__).resolve().parents[1]


def copy_policy_templates(root: Path) -> None:
    exit_code = quality_governance.quality_main(["init", "--project-root", str(root)])
    if exit_code != 0:
        raise AssertionError(f"quality init failed with exit code {exit_code}")


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
    def test_g2_readiness_and_same_finding_reqa_are_bounded(self) -> None:
        ready = {
            "cp6_result_ready": True,
            "approved_design_refs_match": True,
            "required_fixtures_ready": True,
            "changed_paths_allowed": True,
            "consumer_authorization_ready": True,
            "usage_allows_mutation": True,
        }
        policy = {
            "risk_profile": "G2",
            "independent_qa": True,
            "same_finding_reqa_max": 2,
        }
        initial = quality_governance.evaluate_quality_route(
            route_policy=policy,
            readiness_facts=ready,
        )
        self.assertEqual("READY_FOR_QA", initial.decision)
        finding = {
            "check_id": "CP7-01",
            "normalized_contract_ref": "ADR-058-05",
            "affected_path_set": ["meta_flow/checks/quality_governance.py"],
            "root_cause_class": "REAL_CONTENT_FAILURE",
            "title": "first title",
        }
        first = quality_governance.evaluate_quality_route(
            route_policy=policy,
            readiness_facts=ready,
            finding=finding,
            same_finding_rounds_completed=0,
        )
        renamed = {**finding, "title": "renamed finding"}
        second = quality_governance.evaluate_quality_route(
            route_policy=policy,
            readiness_facts=ready,
            finding=renamed,
            same_finding_rounds_completed=1,
        )
        third = quality_governance.evaluate_quality_route(
            route_policy=policy,
            readiness_facts=ready,
            finding=renamed,
            same_finding_rounds_completed=2,
        )
        self.assertEqual("REQA_ALLOWED", first.decision)
        self.assertEqual("REQA_ALLOWED", second.decision)
        self.assertEqual(first.finding_fingerprint, second.finding_fingerprint)
        self.assertEqual("NEEDS_DESIGN_CLARIFICATION", third.decision)
        self.assertEqual("require_user_decision", third.next_action)

    def test_g0_g1_only_allow_targeted_revalidation(self) -> None:
        for profile in ("G0", "G1"):
            with self.subTest(profile=profile):
                decision = quality_governance.evaluate_quality_route(
                    route_policy={
                        "risk_profile": profile,
                        "independent_qa": False,
                        "same_finding_reqa_max": 0,
                    },
                    readiness_facts={
                        "affected_required_check_groups": ["work-policy"],
                    },
                )
                self.assertEqual("TARGETED_REVALIDATION", decision.decision)
                self.assertFalse(decision.independent_qa)
                self.assertTrue(decision.targeted_revalidation_only)
                self.assertEqual(0, decision.same_finding_reqa_max)

    def test_quality_policy_conflict_and_partial_mutation_fail_closed(self) -> None:
        conflict = quality_governance.evaluate_quality_route(
            route_policy={
                "risk_profile": "G1",
                "independent_qa": True,
                "same_finding_reqa_max": 2,
            },
            readiness_facts={"affected_required_check_groups": ["x"]},
        )
        self.assertEqual("PROFILE_ROUTE_CONFLICT", conflict.decision)

        blocked = quality_governance.evaluate_quality_route(
            route_policy={
                "risk_profile": "G2",
                "independent_qa": True,
                "same_finding_reqa_max": 2,
            },
            readiness_facts={
                "cp6_result_ready": True,
                "approved_design_refs_match": True,
                "required_fixtures_ready": True,
                "changed_paths_allowed": True,
                "consumer_authorization_ready": True,
                "usage_allows_mutation": True,
                "partial_mutation": True,
            },
        )
        self.assertEqual("NOT_READY_FOR_QA", blocked.decision)
        self.assertIn("PARTIAL_MUTATION", blocked.blockers)

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
            path.write_text(
                text.replace("manual_truth_source: false", "manual_truth_source: true"),
                encoding="utf-8",
            )

            errors, _warnings = quality_governance.validate_quality_model(root)

            self.assertIn(
                "QUALITY-MODEL metric_derivation.manual_truth_source must be false", errors
            )

    def test_eval_matrix_rejects_unknown_quality_dimension(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            copy_policy_templates(root)
            path = root / "process" / "policies" / "EVAL-MATRIX.yaml"
            text = path.read_text(encoding="utf-8")
            path.write_text(
                text.replace("requirements_traceability", "unknown_dimension", 1), encoding="utf-8"
            )

            errors, _warnings = quality_governance.validate_eval_matrix(root)

            self.assertTrue(
                any(
                    "references unknown quality_dimension: unknown_dimension" in error
                    for error in errors
                )
            )

    def test_quality_cli_and_doctor_commands_report_ok(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            copy_policy_templates(root)

            stream = StringIO()
            with redirect_stdout(stream):
                model_code = quality_governance.quality_main(
                    ["model-check", "--project-root", str(root)]
                )
                eval_code = quality_governance.quality_main(
                    ["eval-check", "--project-root", str(root)]
                )
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

    def test_workflow_doctor_routes_non_cp_artifacts_before_cp_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checks = root / "process" / "checks"
            checks.mkdir(parents=True)
            write_cp1_result(root)
            (checks / "C0-CR-061-PROJECTOR-CUTOVER.result.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "kind": "C0ApplyResultV1",
                        "checkpoint": "C0",
                        "cr_id": "CR-061",
                        "decision": "PASS",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (checks / "CR-068-FILE-OWNERSHIP-DAG.result.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "check_id": "CR-068-FILE-OWNERSHIP-DAG",
                        "check_mode": "static-design-delta",
                        "decision": "PASS_WITH_BASELINE_LIMITATION",
                        "nodes": [],
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
            self.assertIn("check_artifact_files: 3", output)
            self.assertIn("cp_result_files: 1", output)
            self.assertIn("- c0_apply_result: 1", output)
            self.assertIn("- check_result: 1", output)
            self.assertNotIn("checkpoint must be CP0..CP8: C0", output)

    def test_workflow_doctor_unknown_artifact_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checks = root / "process" / "checks"
            checks.mkdir(parents=True)
            (checks / "unknown.result.json").write_text(
                json.dumps({"schema_version": 1, "decision": "PASS", "arbitrary": True}) + "\n",
                encoding="utf-8",
            )

            stream = StringIO()
            with redirect_stdout(stream):
                exit_code = quality_governance.run_workflow_doctor(root)

            self.assertEqual(1, exit_code)
            output = stream.getvalue()
            self.assertIn("Workflow Doctor: FAIL", output)
            self.assertIn(
                "process/checks/unknown.result.json: artifact kind cannot be determined",
                output,
            )

    def test_workflow_doctor_inventories_current_head_with_nonstandard_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checks = root / "process" / "checks"
            checks.mkdir(parents=True)
            result = checks / "CP5-CR-123.current.json"
            result.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "checkpoint": "CP5",
                        "cr_id": "CR-123",
                        "decision": "PASS",
                        "items": [
                            {
                                "id": "CP5-01",
                                "name": "current head",
                                "status": "PASS",
                                "severity": "INFO",
                                "evidence_refs": ["process/checks/evidence.json"],
                            }
                        ],
                        "blockers": [],
                        "waivers": [],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            ledger = root / "process" / "state" / "CHECKPOINT-LEDGER.ndjson"
            ledger.parent.mkdir(parents=True)
            ledger.write_text(
                json.dumps(
                    {
                        "event_id": "CP5-CR-123-V1",
                        "event_type": "checkpoint_result",
                        "checkpoint": "CP5",
                        "cr_id": "CR-123",
                        "decision": "PASS",
                        "result_ref": "process/checks/CP5-CR-123.current.json",
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
            self.assertIn("check_artifact_files: 1", output)
            self.assertIn("cp_result_files: 1", output)


if __name__ == "__main__":
    unittest.main()
