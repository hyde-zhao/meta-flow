from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from meta_flow.checks import cp_result
from meta_flow.policies import failure_routing
from meta_flow.validation import task_runner


def cp_result_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "checkpoint": "CP7",
        "checkpoint_id": "CP7-STORY-CR123-S01",
        "profile": "standard-code",
        "story_id": "STORY-CR123-S01",
        "cr_id": "CR-123",
        "context_ref": "process/context/stories/STORY-CR123-S01.CP7.verify-packet.json",
        "dispatch_refs": ["ADE-0001"],
        "evidence_ref": "process/evidence/STORY-CR123-S01.CP7.index.json",
        "items": [
            {
                "id": "CP7-01",
                "category": "verification",
                "name": "Acceptance criteria covered",
                "status": "PASS",
                "severity": "BLOCKER",
                "evidence_refs": ["process/evidence/STORY-CR123-S01.CP7.index.json#tests"],
                "owner": "meta-qa",
                "route_on_fail": "rework_same_story",
                "waiver_ref": None,
                "notes": "",
            }
        ],
        "blockers": [],
        "waivers": [],
        "decision": "PASS",
        "next_route": "CP8",
    }


def write_result(root: Path, payload: dict[str, object]) -> Path:
    path = root / "process" / "checks" / "CP7-STORY-CR123-S01.result.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


class FailureRoutingWaiverTests(unittest.TestCase):
    def test_failure_classifier_covers_all_four_classes_and_unknown(self) -> None:
        fixtures = [
            (
                {"check_harness_error": True, "semantic_digest_unchanged": True},
                "CHECK_HARNESS_ERROR",
                True,
            ),
            (
                {
                    "deterministic_schema_repair": True,
                    "repair_path_in_scope": True,
                    "before_digest_matches": True,
                },
                "DETERMINISTIC_SCHEMA_REPAIR",
                True,
            ),
            ({"real_content_failure": True}, "REAL_CONTENT_FAILURE", False),
            ({"partial_mutation": True}, "PARTIAL_MUTATION", False),
            ({}, "UNKNOWN", False),
        ]
        for facts, expected, recoverable in fixtures:
            with self.subTest(expected=expected):
                result = failure_routing.classify_failure(facts)
                self.assertEqual(expected, result.failure_class)
                self.assertEqual(recoverable, result.automatic_recovery_candidate)

    def test_recovery_profile_limits_and_task_receipt(self) -> None:
        stable = {
            "facts_digest": "facts",
            "scope_digest": "scope",
            "oid_digest": "oids",
            "authz_digest": "authz",
            "profile_digest": "profile",
        }
        for profile, maximum in (("G0", 1), ("G1", 2), ("G2", 2)):
            with self.subTest(profile=profile):
                decision = failure_routing.evaluate_recovery(
                    failure_class="CHECK_HARNESS_ERROR",
                    route_policy={
                        "risk_profile": profile,
                        "max_auto_recovery_attempts": maximum,
                    },
                    attempts_completed=0,
                    baseline_facts=stable,
                    current_facts=stable,
                    remaining_budget={
                        "reads": 10,
                        "writes": 10,
                        "check_groups": 10,
                        "tokens": 10_000,
                    },
                    recovery_cost={
                        "reads": 1,
                        "writes": 0,
                        "check_groups": 1,
                        "tokens": 100,
                    },
                    pending_required_check_groups=2,
                )
                self.assertTrue(decision.allowed)
                self.assertEqual(maximum, decision.effective_max_auto_recovery_attempts)
                plan = task_runner.build_recovery_attempt_plan(
                    work_id="WORK-1",
                    check_id="check-1",
                    failure_class="CHECK_HARNESS_ERROR",
                    input_digest="input",
                    scope_digest="scope",
                    work_profile_digest="profile",
                    recovery_decision=decision.as_dict(),
                )
                receipt = task_runner.build_recovery_receipt(
                    plan,
                    result="PASS",
                    evidence_refs=["process/evidence/check-1.json"],
                    output_digest="output",
                )
                self.assertEqual(1, receipt["attempt_number"])
                self.assertEqual("rerun_original_check_group", receipt["action"])

    def test_g0_budget_formula_and_drift_force_effective_zero(self) -> None:
        stable = {
            "facts_digest": "facts",
            "scope_digest": "scope",
            "oid_digest": "oids",
            "authz_digest": "authz",
            "profile_digest": "profile",
        }
        blocked = failure_routing.evaluate_recovery(
            failure_class="DETERMINISTIC_SCHEMA_REPAIR",
            route_policy={"risk_profile": "G0", "max_auto_recovery_attempts": 1},
            attempts_completed=0,
            baseline_facts=stable,
            current_facts=stable,
            remaining_budget={
                "reads": 2,
                "writes": 1,
                "check_groups": 2,
                "tokens": 500,
            },
            recovery_cost={
                "reads": 1,
                "writes": 1,
                "check_groups": 1,
                "tokens": 100,
            },
            pending_required_check_groups=2,
        )
        self.assertFalse(blocked.allowed)
        self.assertEqual(0, blocked.effective_max_auto_recovery_attempts)
        self.assertIn("CHECK_GROUP_BUDGET_INSUFFICIENT", blocked.reason_codes)

        drifted = {**stable, "oid_digest": "changed"}
        drift = failure_routing.evaluate_recovery(
            failure_class="CHECK_HARNESS_ERROR",
            route_policy={"risk_profile": "G2", "max_auto_recovery_attempts": 2},
            attempts_completed=0,
            baseline_facts=stable,
            current_facts=drifted,
            remaining_budget={
                "reads": 100,
                "writes": 100,
                "check_groups": 100,
                "tokens": 100_000,
            },
            recovery_cost={},
        )
        self.assertFalse(drift.allowed)
        self.assertEqual(0, drift.effective_max_auto_recovery_attempts)
        self.assertIn("OID_DIGEST_DRIFT", drift.reason_codes)

    def test_content_and_partial_failures_never_auto_recover(self) -> None:
        stable = {key: "same" for key in failure_routing.DRIFT_FACTS}
        for failure_class in ("REAL_CONTENT_FAILURE", "PARTIAL_MUTATION"):
            with self.subTest(failure_class=failure_class):
                decision = failure_routing.evaluate_recovery(
                    failure_class=failure_class,
                    route_policy={
                        "risk_profile": "G2",
                        "max_auto_recovery_attempts": 2,
                    },
                    attempts_completed=0,
                    baseline_facts=stable,
                    current_facts=stable,
                    remaining_budget={
                        "reads": 100,
                        "writes": 100,
                        "check_groups": 100,
                        "tokens": 100_000,
                    },
                    recovery_cost={},
                )
                self.assertFalse(decision.allowed)
                self.assertEqual(0, decision.effective_max_auto_recovery_attempts)

    def test_policy_check_writes_and_validates_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            stream = StringIO()
            with redirect_stdout(stream):
                failure_code = failure_routing.failure_main(["policy-check", "--write-default", "--project-root", str(root)])
            with redirect_stdout(stream):
                waiver_code = failure_routing.waiver_main(["policy-check", "--write-default", "--project-root", str(root)])

            self.assertEqual(0, failure_code)
            self.assertEqual(0, waiver_code)
            self.assertTrue((root / "process" / "policies" / "FAILURE-ROUTING.json").is_file())
            self.assertTrue((root / "process" / "policies" / "WAIVER-POLICY.json").is_file())
            self.assertIn("Failure Routing Policy Check: OK", stream.getvalue())
            self.assertIn("Waiver Policy Check: OK", stream.getvalue())

    def test_blocker_failure_requires_route_on_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = cp_result_payload()
            payload["decision"] = "FAIL"
            payload["items"][0]["status"] = "FAIL"  # type: ignore[index]
            payload["items"][0]["route_on_fail"] = ""  # type: ignore[index]

            errors, _warnings = failure_routing.validate_failure_routes_for_result(root, payload)

            self.assertIn("item 1: BLOCKER FAIL requires route_on_fail", errors)

    def test_unknown_route_on_fail_is_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = cp_result_payload()
            payload["decision"] = "FAIL"
            payload["items"][0]["status"] = "FAIL"  # type: ignore[index]
            payload["items"][0]["route_on_fail"] = "NEEDS_REWORK"  # type: ignore[index]

            errors, _warnings = failure_routing.validate_failure_routes_for_result(root, payload)

            self.assertTrue(any("route_on_fail must be one of" in error for error in errors))

    def test_waived_item_requires_full_waiver_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = cp_result_payload()
            payload["decision"] = "WAIVED"
            payload["items"][0]["status"] = "WAIVED"  # type: ignore[index]
            payload["items"][0]["waiver_ref"] = "WV-001"  # type: ignore[index]
            payload["items"][0]["route_on_fail"] = "waive_with_risk_acceptance"  # type: ignore[index]
            payload["waivers"] = [{"waiver_id": "WV-001", "scope": "fixture gap only"}]

            errors, _warnings = failure_routing.validate_waivers_for_result(root, payload)

            self.assertIn("waiver WV-001: missing required field: applies_to", errors)
            self.assertIn("waiver WV-001: missing required field: expires_at", errors)
            self.assertIn("waiver WV-001: missing required field: approval_ref", errors)
            self.assertIn("waiver WV-001: missing required field: forces_release_status", errors)

    def test_non_waivable_item_cannot_be_waived(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = cp_result_payload()
            payload["decision"] = "WAIVED"
            payload["items"][0].update(  # type: ignore[index]
                {
                    "id": "CP7-DISPATCH",
                    "category": "missing_dispatch_evidence",
                    "name": "Missing dispatch evidence",
                    "status": "WAIVED",
                    "waiver_ref": "WV-001",
                    "route_on_fail": "waive_with_risk_acceptance",
                }
            )
            payload["waivers"] = [
                {
                    "waiver_id": "WV-001",
                    "applies_to": {"checkpoint": "CP7", "check_item_id": "CP7-DISPATCH"},
                    "scope": "not allowed",
                    "expires_at": "2026-07-01T00:00:00+08:00",
                    "approval_ref": "process/checkpoints/CP8.decision.json#DQ-001",
                    "forces_release_status": "READY_WITH_RISK",
                    "risk_refs": ["RISK-DISPATCH-MISSING"],
                }
            ]

            errors, _warnings = failure_routing.validate_waivers_for_result(root, payload)

            self.assertIn("item 1: non-waivable check cannot be WAIVED: CP7-DISPATCH", errors)

    def test_ready_with_risk_waiver_cannot_silent_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = cp_result_payload()
            payload["decision"] = "PASS"
            payload["items"][0].update(  # type: ignore[index]
                {
                    "status": "WAIVED",
                    "severity": "LOW",
                    "waiver_ref": "WV-001",
                    "route_on_fail": "waive_with_risk_acceptance",
                }
            )
            payload["waivers"] = [
                {
                    "waiver_id": "WV-001",
                    "applies_to": {"checkpoint": "CP7", "check_item_id": "CP7-01"},
                    "scope": "fixture-only coverage gap accepted for this CR",
                    "expires_at": "2026-07-01T00:00:00+08:00",
                    "approval_ref": "process/checkpoints/CP8.decision.json#DQ-004",
                    "forces_release_status": "READY_WITH_RISK",
                    "risk_refs": ["RISK-FIXTURE-COVERAGE-GAP"],
                }
            ]

            errors, _warnings = failure_routing.validate_waivers_for_result(root, payload)

            self.assertIn("item 1: waiver WV-001 forces READY_WITH_RISK; decision cannot be silent PASS", errors)

    def test_cp_result_check_includes_failure_and_waiver_governance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = cp_result_payload()
            payload["decision"] = "FAIL"
            payload["items"][0]["status"] = "FAIL"  # type: ignore[index]
            payload["items"][0]["route_on_fail"] = ""  # type: ignore[index]
            result = write_result(root, payload)

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root)

            self.assertIn("item 1: BLOCKER FAIL requires route_on_fail", errors)

    def test_cli_route_and_waiver_checks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = write_result(root, cp_result_payload())

            route_stream = StringIO()
            with redirect_stdout(route_stream):
                route_code = failure_routing.failure_main(["route-check", "--result", str(result), "--project-root", str(root)])
            waiver_stream = StringIO()
            with redirect_stdout(waiver_stream):
                waiver_code = failure_routing.waiver_main(["check", "--result", str(result), "--project-root", str(root)])

            self.assertEqual(0, route_code)
            self.assertEqual(0, waiver_code)
            self.assertIn("Failure Route Check: OK", route_stream.getvalue())
            self.assertIn("Waiver Check: OK", waiver_stream.getvalue())


if __name__ == "__main__":
    unittest.main()
