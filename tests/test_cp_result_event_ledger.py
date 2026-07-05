from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from meta_flow.checks import cp_result
from meta_flow.state import current
from meta_flow.state import event_ledger


def write_minimal_state(root: Path) -> None:
    state = current.default_current_state(root)
    state["project_id"] = "fixture-project"
    current.write_current_state(root, state)


def cp6_result_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "checkpoint": "CP6",
        "checkpoint_id": "CP6-STORY-CR123-S01",
        "profile": "standard-code",
        "story_id": "STORY-CR123-S01",
        "cr_id": "CR-123",
        "context_ref": "process/context/stories/STORY-CR123-S01.CP6.work-packet.json",
        "dispatch_refs": ["ADE-0001"],
        "evidence_ref": "process/evidence/STORY-CR123-S01.CP6.index.json",
        "items": [
            {
                "id": "CP6-01",
                "category": "implementation",
                "name": "Implementation matches Story Context Contract",
                "status": "PASS",
                "severity": "BLOCKER",
                "evidence_refs": ["process/evidence/STORY-CR123-S01.CP6.index.json#changed_files"],
                "owner": "meta-dev",
                "route_on_fail": "rework_same_story",
                "waiver_ref": None,
                "notes": "",
            }
        ],
        "blockers": [],
        "waivers": [],
        "decision": "PASS",
        "next_route": "CP7",
        "checked_at": "2026-06-21T00:00:00+00:00",
    }


def write_cp6_result(root: Path, payload: dict[str, object] | None = None) -> Path:
    path = root / "process" / "checks" / "CP6-STORY-CR123-S01.result.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload or cp6_result_payload(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def write_cp8_result(root: Path, payload: dict[str, object] | None = None) -> Path:
    path = root / "process" / "checks" / "CP8-CR123.result.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    base = cp6_result_payload()
    base.update(
        {
            "checkpoint": "CP8",
            "checkpoint_id": "CP8-CR123",
            "story_id": "",
            "context_ref": "process/context/CP8-CR123.context.json",
            "dispatch_refs": [],
            "evidence_ref": "process/evidence/CR123.CP8.index.json",
            "release_decision": "READY",
            "next_route": "delivered",
        }
    )
    base.update(payload or {})
    path.write_text(json.dumps(base, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


class CPResultEventLedgerTests(unittest.TestCase):
    def test_cp_result_check_passes_for_valid_cp6_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = write_cp6_result(root)

            stream = StringIO()
            with redirect_stdout(stream):
                exit_code = cp_result.main(["result-check", "--result", str(result), "--project-root", str(root)])

            self.assertEqual(0, exit_code)
            self.assertIn("CP Result Check: OK", stream.getvalue())

    def test_cp_result_check_silent_mode_prints_single_pass_line(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = write_cp6_result(root)

            stream = StringIO()
            with redirect_stdout(stream):
                exit_code = cp_result.main(
                    ["result-check", "--result", str(result), "--project-root", str(root), "--mode", "silent"]
                )

            self.assertEqual(0, exit_code)
            self.assertEqual("PASS", stream.getvalue().strip())

    def test_cp_result_rejects_pass_with_blocking_item(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = cp6_result_payload()
            payload["items"] = [
                {
                    "id": "CP6-01",
                    "category": "implementation",
                    "name": "Forbidden paths not touched",
                    "status": "FAIL",
                    "severity": "BLOCKER",
                    "evidence_refs": [],
                    "owner": "meta-dev",
                    "route_on_fail": "rework_same_story",
                    "waiver_ref": None,
                    "notes": "",
                }
            ]
            result = write_cp6_result(root, payload)

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root)

            self.assertIn("decision cannot be PASS/PASS_WITH_RISK when blocking items exist", errors)

    def test_cp7_result_allows_needs_rework(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = cp6_result_payload()
            payload["checkpoint"] = "CP7"
            payload["checkpoint_id"] = "CP7-STORY-CR123-S01"
            payload["decision"] = "NEEDS_REWORK"
            payload["next_route"] = "NEEDS_REWORK"
            result = write_cp6_result(root, payload)

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root)

            self.assertEqual([], errors)

    def test_na_cp6_result_does_not_require_story_dispatch_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = cp6_result_payload()
            payload.update(
                {
                    "checkpoint": "CP6",
                    "checkpoint_id": "CP6-CR123",
                    "decision": "N/A",
                    "story_id": "",
                    "context_ref": "",
                    "dispatch_refs": [],
                    "evidence_ref": "",
                    "not_applicable_reason": "route_plan marks CP6 N/A because this CR has no new implementation",
                    "items": [
                        {
                            "id": "CP6-NA",
                            "category": "route_plan",
                            "name": "CP6 applicability",
                            "status": "N/A",
                            "severity": "INFO",
                            "evidence_refs": [],
                            "owner": "host-orchestrator",
                            "route_on_fail": "",
                            "waiver_ref": None,
                            "notes": "No implementation stage applies.",
                        }
                    ],
                    "next_route": "CP8",
                }
            )
            result = write_cp6_result(root, payload)

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root)

            self.assertEqual([], errors)

    def test_na_cp_result_requires_applicability_reason_or_route_ref(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = cp6_result_payload()
            payload.update({"checkpoint": "CP3", "checkpoint_id": "CP3-CR123", "decision": "N/A"})
            result = write_cp6_result(root, payload)

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root)

            self.assertIn(
                "decision=N/A requires not_applicable_reason, route_plan_ref, or checkpoint_applicability",
                errors,
            )

    def test_waived_cp_result_requires_waiver_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = cp6_result_payload()
            payload.update({"decision": "WAIVED", "waivers": []})
            result = write_cp6_result(root, payload)

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root)

            self.assertIn("decision=WAIVED requires waivers", errors)

    def test_cp2_commitments_required_evidence_schema_is_validated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = cp6_result_payload()
            payload["checkpoint"] = "CP2"
            payload["checkpoint_id"] = "CP2-CR123"
            payload["story_id"] = ""
            payload["context_ref"] = "process/context/CP2-CR123.context.json"
            payload["evidence_ref"] = ""
            payload["dispatch_refs"] = []
            payload["commitments"] = {
                "required_evidence": [
                    {
                        "id": "REQ-EVID-REAL-LAKE",
                        "kind": "real_lake_validation",
                        "required_stage": "CP7",
                        "minimum_evidence": {"run_refs_min": 2},
                    }
                ]
            }
            result = write_cp6_result(root, payload)

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root)

            self.assertEqual([], errors)

    def test_cp7_missing_required_evidence_blocks_pass_with_risk(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = cp6_result_payload()
            payload["checkpoint"] = "CP7"
            payload["checkpoint_id"] = "CP7-STORY-CR123-S01"
            payload["decision"] = "PASS_WITH_RISK"
            payload["promise_evidence_alignment"] = [
                {
                    "promise_ref": "REQ-EVID-REAL-LAKE",
                    "evidence_status": "MISSING_REQUIRED_EVIDENCE",
                    "result": "BLOCKED",
                    "evidence_refs": [],
                }
            ]
            result = write_cp6_result(root, payload)

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root)

            self.assertIn("CP7 decision must be BLOCKED when required evidence is missing", errors)

    def test_cp7_executed_negative_result_can_pass_with_risk_when_evidenced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = cp6_result_payload()
            payload["checkpoint"] = "CP7"
            payload["checkpoint_id"] = "CP7-STORY-CR123-S01"
            payload["decision"] = "PASS_WITH_RISK"
            payload["promise_evidence_alignment"] = [
                {
                    "promise_ref": "REQ-EVID-ADMISSION",
                    "evidence_status": "EXECUTED_NEGATIVE_RESULT",
                    "result": "PASS_WITH_RISK",
                    "evidence_refs": ["process/evidence/real-lake-validation.json#admission"],
                }
            ]
            result = write_cp6_result(root, payload)

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root)

            self.assertEqual([], errors)

    def test_cp8_fact_diff_rejects_pass_when_required_evidence_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = write_cp8_result(
                root,
                {
                    "decision": "PASS",
                    "release_decision": "READY",
                    "fact_diff": [
                        {
                            "promise_ref": "REQ-EVID-REAL-LAKE",
                            "promise": "Real lake validation must execute",
                            "status": "MISSING_REQUIRED_EVIDENCE",
                            "decision_impact": "NOT_READY",
                            "evidence_refs": [],
                            "risk_ref": "R-REAL-LAKE-MISSING",
                        }
                    ],
                },
            )

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root)

            self.assertIn("CP8 decision cannot be PASS/WAIVED when fact_diff has missing required evidence", errors)
            self.assertIn("CP8 release_decision must be NOT_READY when fact_diff has missing required evidence", errors)

    def test_cp8_fact_diff_allows_ready_with_risk_for_executed_negative_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = write_cp8_result(
                root,
                {
                    "decision": "PASS",
                    "release_decision": "READY_WITH_RISK",
                    "fact_diff": [
                        {
                            "promise_ref": "REQ-EVID-ADMISSION",
                            "promise": "Admission package exists",
                            "status": "EXECUTED_NEGATIVE_RESULT",
                            "decision_impact": "READY_WITH_RISK",
                            "evidence_refs": ["process/evidence/CR123.CP7.index.json#admission"],
                            "risk_ref": "R-ADMISSION-BLOCKED",
                        }
                    ],
                },
            )

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root)

            self.assertEqual([], errors)

    def test_cp8_fact_diff_rejects_ready_for_deferred_follow_up(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = write_cp8_result(
                root,
                {
                    "decision": "PASS",
                    "release_decision": "READY",
                    "fact_diff": [
                        {
                            "promise_ref": "REQ-FOLLOW-UP-001",
                            "promise": "Non-blocking follow-up must be tracked before closeout",
                            "status": "DEFERRED_FOLLOW_UP",
                            "decision_impact": "READY_WITH_RISK",
                            "evidence_refs": ["process/changes/CR123-FOLLOW-UP-TRACKING.md#FU-001"],
                            "risk_ref": "R-FOLLOW-UP-DEFERRED",
                        }
                    ],
                },
            )

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root)

            self.assertIn("CP8 release_decision cannot be READY when fact_diff has risk or not-ready impacts", errors)

    def test_checker_provenance_requires_review_ref_when_fallback_used(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = cp6_result_payload()
            payload["checker_provenance"] = {
                "checker_name": "meta-flow cp result-check",
                "checker_version": "1.0.0",
                "invocation": "meta-flow cp result-check --result process/checks/CP6.result.json",
                "generated_by": "tool",
                "fallback_used": True,
                "fallback_reason": "checker unavailable in current checkout",
            }
            result = write_cp6_result(root, payload)

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root)

            self.assertIn("checker_provenance fallback_used=true requires fallback_review_ref", errors)

    def test_checker_provenance_is_rendered_and_added_to_checkpoint_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = cp6_result_payload()
            payload["checker_provenance"] = {
                "checker_name": "meta-flow cp result-check",
                "checker_commit": "abc1234",
                "invocation": "meta-flow cp result-check --result process/checks/CP6.result.json",
                "generated_by": "tool",
                "fallback_used": False,
            }
            result = write_cp6_result(root, payload)

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root)
            summary = cp_result.render_summary(cp_result.load_cp_result(result))
            event = cp_result.build_checkpoint_event(root, result)

            self.assertEqual([], errors)
            self.assertIn("## Checker Provenance", summary)
            self.assertEqual("meta-flow cp result-check", event["checker_provenance"]["checker_name"])

    def test_render_summary_includes_cp8_release_decision_and_fact_diff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = write_cp8_result(
                root,
                {
                    "decision": "PASS",
                    "release_decision": "READY_WITH_RISK",
                    "fact_diff": [
                        {
                            "promise_ref": "REQ-EVID-ADMISSION",
                            "promise": "Admission package exists",
                            "status": "EXECUTED_NEGATIVE_RESULT",
                            "decision_impact": "READY_WITH_RISK",
                            "evidence_refs": ["process/evidence/CR123.CP7.index.json#admission"],
                            "risk_ref": "R-ADMISSION-BLOCKED",
                        }
                    ],
                },
            )

            summary = cp_result.render_summary(cp_result.load_cp_result(result))

            self.assertIn("Release Decision: READY_WITH_RISK", summary)
            self.assertIn("## Fact Diff", summary)
            self.assertIn("REQ-EVID-ADMISSION", summary)
            self.assertIn("EXECUTED_NEGATIVE_RESULT", summary)

    def test_result_check_consistency_rejects_stale_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = write_cp6_result(root)
            result.with_suffix(".summary.md").write_text("# CP6 Summary\n\nDecision: FAIL\nCR: CR-123\n", encoding="utf-8")

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root, check_consistency=True)

            self.assertTrue(any("summary decision does not match result JSON" in error for error in errors))

    def test_render_summary_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = write_cp6_result(root)

            output = cp_result.render_summary_file(result)

            self.assertTrue(output.is_file())
            self.assertIn("Decision: PASS", output.read_text(encoding="utf-8"))

    def test_checkpoint_ledger_append_and_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            result = write_cp6_result(root)
            cp_result.render_summary_file(result)

            ledger = cp_result.append_checkpoint_ledger(root, result_path=result)
            errors, warnings = event_ledger.validate_event_ledger(ledger, ledger_type="checkpoint")

            self.assertTrue(ledger.is_file())
            self.assertEqual([], errors)
            self.assertEqual([], warnings)

    def test_cp_result_consistency_rejects_missing_dispatch_ref(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = write_cp6_result(root)

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root, check_consistency=True)

            self.assertIn("dispatch_refs require AGENT-DISPATCH-LEDGER entries: ADE-0001", errors)

    def test_cp_result_consistency_runs_state_transition_when_route_plan_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = current.default_current_state(root)
            state["project_id"] = "fixture-project"
            state["active_change"] = "CR-123"
            state["current_phase"] = "story-planning"
            state["next_action"] = {"type": "continue", "text": "manual continue to CP5"}
            current.write_current_state(root, state)
            route_path = root / "process" / "checks" / "CP0-CR123.route-plan.json"
            route_path.parent.mkdir(parents=True, exist_ok=True)
            route_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "decision": "PASS",
                        "stages": [
                            {"checkpoint": "CP3", "mode": "standard", "human_gate": "required"},
                            {"checkpoint": "CP4", "mode": "standard", "human_gate": "none"},
                            {"checkpoint": "CP5", "mode": "standard", "human_gate": "required"},
                        ],
                        "checkpoint_applicability": {},
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            payload = cp6_result_payload()
            payload.update(
                {
                    "checkpoint": "CP4",
                    "checkpoint_id": "CP4-CR123",
                    "story_id": "",
                    "context_ref": "process/context/CP4.context.json",
                    "dispatch_refs": [],
                    "evidence_ref": "",
                    "route_plan_ref": "process/checks/CP0-CR123.route-plan.json",
                }
            )
            result = write_cp6_result(root, payload)

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root, check_consistency=True)

            self.assertTrue(any("pending_gate=CP5" in error for error in errors))

    def test_cp_result_consistency_accepts_dispatch_ref_in_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = write_cp6_result(root)
            event = event_ledger.build_inline_fallback_event(
                dispatch_id="ADE-0001",
                canonical_role="meta-dev",
                fallback_reason="fixture inline implementation",
                approved_by="test",
                cr_id="CR-123",
                checkpoint="CP6",
                result_ref="process/checks/CP6-STORY-CR123-S01.result.json",
                created_at="2026-07-05T00:00:00+00:00",
            )
            event_ledger.append_dispatch_event(root, event)

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root, check_consistency=True)

            self.assertNotIn("dispatch_refs require AGENT-DISPATCH-LEDGER entries: ADE-0001", errors)
            self.assertFalse(any("dispatch_refs missing" in error for error in errors))

    def test_event_ledger_check_silent_mode_prints_single_pass_line(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            result = write_cp6_result(root)
            cp_result.render_summary_file(result)
            ledger = cp_result.append_checkpoint_ledger(root, result_path=result)

            stream = StringIO()
            with redirect_stdout(stream):
                exit_code = event_ledger.main(["check", "--ledger", str(ledger), "--type", "checkpoint", "--mode", "silent"])

            self.assertEqual(0, exit_code)
            self.assertEqual("PASS", stream.getvalue().strip())

    def test_applicability_aggregate_build_and_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            route_plan = root / "process" / "checks" / "CP0-CR156.route-plan.json"
            aggregate = root / "process" / "checks" / "CP8-CR156.applicability.json"
            route_plan.parent.mkdir(parents=True, exist_ok=True)
            route_plan.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "decision": "PASS",
                        "stages": [{"checkpoint": "CP0", "mode": "standard", "human_gate": "none"}],
                        "checkpoint_applicability": {
                            "CP0": {"applies": True, "mode": "standard", "human_gate": "none"},
                            "CP3": {"applies": False, "decision": "N/A", "reason": "uses existing evidence only"},
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            output = cp_result.write_applicability_aggregate(root, route_plan, aggregate, cr_id="CR-156")
            errors, warnings = cp_result.validate_applicability_aggregate(root, output)

            self.assertTrue(output.is_file())
            self.assertEqual([], errors)
            self.assertEqual([], warnings)

    def test_applicability_aggregate_rejects_stale_route_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            route_plan = root / "process" / "checks" / "CP0-CR156.route-plan.json"
            aggregate = root / "process" / "checks" / "CP8-CR156.applicability.json"
            route_plan.parent.mkdir(parents=True, exist_ok=True)
            route_plan.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "decision": "PASS",
                        "stages": [],
                        "checkpoint_applicability": {
                            "CP3": {"applies": False, "decision": "N/A", "reason": "uses existing evidence only"},
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            cp_result.write_applicability_aggregate(root, route_plan, aggregate, cr_id="CR-156")
            payload = json.loads(aggregate.read_text(encoding="utf-8"))
            payload["checkpoint_applicability"]["CP3"]["decision"] = "WAIVED"
            aggregate.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            errors, _warnings = cp_result.validate_applicability_aggregate(root, aggregate)

            self.assertIn("checkpoint_applicability does not match source route plan", errors)

    def test_dispatch_not_required_event_uses_structured_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "process" / "state" / "AGENT-DISPATCH-LEDGER.ndjson"
            event = event_ledger.build_dispatch_not_required_event(
                dispatch_id="ADE-NA-001",
                canonical_role="meta-dev",
                reason="route_plan marks CP6 N/A",
                created_at="2026-07-05T00:00:00+00:00",
            )
            event_ledger.append_dispatch_event(root, event, ledger=ledger)

            errors, warnings = event_ledger.validate_event_ledger(ledger, ledger_type="dispatch")

            self.assertEqual([], errors)
            self.assertEqual([], warnings)

    def test_inline_fallback_dispatch_event_requires_approval_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "process" / "state" / "AGENT-DISPATCH-LEDGER.ndjson"
            ledger.parent.mkdir(parents=True, exist_ok=True)
            ledger.write_text(
                json.dumps(
                    {
                        "dispatch_id": "ADE-INLINE-001",
                        "event_type": "inline_fallback",
                        "canonical_role": "meta-dev",
                        "dispatch_mode": "inline-fallback",
                        "fallback_reason": "current platform has no subagent dispatch tool",
                        "status": "completed",
                        "created_at": "2026-07-05T00:00:00+00:00",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            errors, _warnings = event_ledger.validate_event_ledger(ledger, ledger_type="dispatch")

            self.assertIn("line 1: missing required field: approved_by", errors)

    def test_event_ledger_check_rejects_missing_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "process" / "state" / "CHECKPOINT-LEDGER.ndjson"
            ledger.parent.mkdir(parents=True, exist_ok=True)
            ledger.write_text(json.dumps({"event_id": "E-1", "event_type": "checkpoint_result"}) + "\n", encoding="utf-8")

            errors, _warnings = event_ledger.validate_event_ledger(ledger, ledger_type="checkpoint")

            self.assertIn("line 1: missing required field: checkpoint", errors)
            self.assertIn("line 1: missing required field: decision", errors)
            self.assertIn("line 1: missing required field: result_ref", errors)

    def test_event_cli_append_and_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "process" / "state" / "HANDOFF-LEDGER.ndjson"
            event_file = root / "event.json"
            event_file.write_text(
                json.dumps(
                    {
                        "event_id": "HE-0001",
                        "event_type": "handoff",
                        "stage": "CP6",
                        "from_role": "host-orchestrator",
                        "to_role": "meta-dev",
                        "context_ref": "process/context/stories/STORY.CP6.work-packet.json",
                        "status": "created",
                        "created_at": "2026-06-21T00:00:00+00:00",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            self.assertEqual(0, event_ledger.main(["append", "--ledger", str(ledger), "--event-file", str(event_file)]))
            self.assertEqual(0, event_ledger.main(["check", "--ledger", str(ledger), "--type", "handoff"]))
            stream = StringIO()
            with redirect_stdout(stream):
                exit_code = event_ledger.main(["list", "--ledger", str(ledger)])

            self.assertEqual(0, exit_code)
            self.assertIn("HE-0001\thandoff\tcreated", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
