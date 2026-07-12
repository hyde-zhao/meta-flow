from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from meta_flow.checks import state_transition


def write_route_plan(root: Path) -> Path:
    path = root / "process" / "checks" / "CP0-CR158.route-plan.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "decision": "PASS",
        "stages": [
            {"checkpoint": "CP0", "mode": "standard", "human_gate": "none"},
            {"checkpoint": "CP2", "mode": "standard", "human_gate": "required"},
            {"checkpoint": "CP3", "mode": "standard", "human_gate": "required"},
            {"checkpoint": "CP4", "mode": "standard", "human_gate": "none"},
            {"checkpoint": "CP5", "mode": "standard", "human_gate": "required"},
            {"checkpoint": "CP6", "mode": "standard", "human_gate": "none"},
            {"checkpoint": "CP7", "mode": "standard", "human_gate": "none"},
            {"checkpoint": "CP8", "mode": "standard", "human_gate": "required"},
        ],
        "checkpoint_applicability": {},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_state(root: Path, payload: dict) -> Path:
    path = root / "process" / "state" / "STATE.current.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "schema_version": 2,
        "project_id": "demo",
        "workflow_mode": "standard",
        "current_phase": "story-planning",
        "blocked": False,
        "active_change": "CR-158",
        "pending_gate": None,
        "next_action": {"type": "continue", "text": "continue current phase"},
        "routing_ref": "process/.meta-flow-process.yaml",
        "updated_at": "2026-07-05T00:00:00+00:00",
    }
    state.update(payload)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


class StateTransitionTests(unittest.TestCase):
    def test_chronology_accepts_complete_timezone_aware_order(self) -> None:
        nodes = [
            state_transition.ChronologyNode("producer-complete", "2026-07-12T00:00:00Z", "producer"),
            state_transition.ChronologyNode("checkpoint-created", "2026-07-12T00:01:00Z", "checkpoint"),
            state_transition.ChronologyNode("gate-opened", "2026-07-12T00:02:00Z", "gate"),
            state_transition.ChronologyNode("reviewed", "2026-07-12T00:03:00Z", "review"),
            state_transition.ChronologyNode("approved", "2026-07-12T00:04:00Z", "approval"),
            state_transition.ChronologyNode("downstream-dispatch", "2026-07-12T00:05:00Z", "dispatch"),
        ]
        self.assertEqual([], state_transition.validate_chronology(nodes))

    def test_chronology_rejects_each_core_order_violation(self) -> None:
        nodes = [
            state_transition.ChronologyNode("producer-complete", "2026-07-12T00:02:00Z", "producer"),
            state_transition.ChronologyNode("checkpoint-created", "2026-07-12T00:01:00Z", "checkpoint"),
        ]
        findings = state_transition.validate_chronology(nodes)
        self.assertEqual(["TEMPORAL_ORDER_VIOLATION"], [finding.code for finding in findings])

    def test_conditional_approval_requires_conditions_satisfied(self) -> None:
        nodes = [
            state_transition.ChronologyNode("gate-opened", "2026-07-12T00:00:00Z", "gate"),
            state_transition.ChronologyNode("conditional-received", "2026-07-12T00:01:00Z", "conditional"),
            state_transition.ChronologyNode("approved", "2026-07-12T00:02:00Z", "approval"),
        ]
        decision, findings = state_transition.derive_gate_decision(nodes)
        self.assertEqual("pending", decision)
        self.assertIn("CONDITIONS_UNSATISFIED", [finding.code for finding in findings])

    def test_conditional_approval_with_conditions_and_dispatch_is_approved(self) -> None:
        nodes = [
            state_transition.ChronologyNode("gate-opened", "2026-07-12T00:00:00Z", "gate"),
            state_transition.ChronologyNode("conditional-received", "2026-07-12T00:01:00Z", "conditional"),
            state_transition.ChronologyNode("conditions-satisfied", "2026-07-12T00:02:00Z", "conditions"),
            state_transition.ChronologyNode("approved", "2026-07-12T00:03:00Z", "approval"),
            state_transition.ChronologyNode("downstream-dispatch", "2026-07-12T00:04:00Z", "dispatch"),
        ]
        decision, findings = state_transition.derive_gate_decision(nodes)
        self.assertEqual("approved", decision)
        self.assertEqual([], findings)
        self.assertEqual([], state_transition.validate_phase_gate_state({"pending_gate": None}, nodes))

    def test_phase_work_without_gate_is_not_a_future_gate_fact(self) -> None:
        findings = state_transition.validate_phase_gate_state(
            {"current_phase": "solution-design", "pending_gate": None},
            [],
        )
        self.assertEqual([], findings)

    def test_review_without_opened_gate_is_rejected(self) -> None:
        findings = state_transition.validate_phase_gate_state(
            {"current_phase": "story-execution", "pending_gate": None},
            [state_transition.ChronologyNode("reviewed", "2026-07-12T00:00:00Z", "review")],
        )
        self.assertIn("PHASE_GATE_CONFLATION", [finding.code for finding in findings])

    def test_approved_gate_without_downstream_transition_is_rejected(self) -> None:
        findings = state_transition.validate_phase_gate_state(
            {"current_phase": "story-execution", "pending_gate": None},
            [
                state_transition.ChronologyNode("gate-opened", "2026-07-12T00:00:00Z", "gate"),
                state_transition.ChronologyNode("reviewed", "2026-07-12T00:01:00Z", "review"),
                state_transition.ChronologyNode("approved", "2026-07-12T00:02:00Z", "approval"),
            ],
        )
        self.assertIn("PHASE_GATE_CONFLATION", [finding.code for finding in findings])

    def test_timezone_is_required_for_chronology(self) -> None:
        findings = state_transition.validate_chronology(
            [state_transition.ChronologyNode("gate-opened", "2026-07-12T00:00:00", "gate")]
        )
        self.assertEqual(["UNPARSEABLE_TIMESTAMP"], [finding.code for finding in findings])
    def test_cp4_pass_requires_auto_advance_to_cp5_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            route = write_route_plan(root)
            state = write_state(root, {"next_action": {"type": "continue", "text": "等待用户继续推进 CP5"}})

            errors, warnings = state_transition.validate_transition(
                route_plan_path=route,
                state_path=state,
                checkpoint="CP4",
                decision="PASS",
            )

            self.assertEqual([], warnings)
            self.assertTrue(any("pending_gate=CP5" in error for error in errors))

    def test_cp4_pass_accepts_state_stopped_at_cp5_required_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            route = write_route_plan(root)
            state = write_state(
                root,
                {
                    "pending_gate": "CP5",
                    "pending_checklist_path": "process/checkpoints/CP5-ALL-STORIES-LLD-BATCH.md",
                    "next_action": {"type": "await_user", "text": "review CP5"},
                },
            )

            errors, warnings = state_transition.validate_transition(
                route_plan_path=route,
                state_path=state,
                checkpoint="CP4",
                decision="PASS",
            )

            self.assertEqual([], errors)
            self.assertEqual([], warnings)

    def test_approved_cp3_requires_post_approval_transition_to_cp5(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            route = write_route_plan(root)
            state = write_state(root, {"next_action": {"type": "continue", "text": "approval writeback complete"}})

            errors, _warnings = state_transition.validate_transition(
                route_plan_path=route,
                state_path=state,
                approved_gate="CP3",
            )

            self.assertTrue(any("pending_gate=CP5" in error for error in errors))

    def test_approved_cp5_accepts_auto_advance_to_cp8_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            route = write_route_plan(root)
            state = write_state(
                root,
                {
                    "current_phase": "documentation",
                    "pending_gate": "CP8",
                    "pending_checklist_path": "process/checkpoints/CP8-DELIVERY-READINESS.md",
                    "next_action": {"type": "await_user", "text": "review CP8"},
                },
            )

            errors, warnings = state_transition.validate_transition(
                route_plan_path=route,
                state_path=state,
                approved_gate="CP5",
            )

            self.assertEqual([], errors)
            self.assertEqual([], warnings)

    def test_approved_cp5_accepts_story_execution_before_cp8_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            route = write_route_plan(root)
            state = write_state(
                root,
                {
                    "current_phase": "story-execution",
                    "active_change": "CR-158",
                    "pending_gate": None,
                    "next_action": {"type": "inline_implementation", "text": "implement CP6 work"},
                },
            )

            errors, warnings = state_transition.validate_transition(
                route_plan_path=route,
                state_path=state,
                approved_gate="CP5",
            )

            self.assertEqual([], errors)
            self.assertEqual([], warnings)

    def test_approved_cp8_accepts_true_delivered_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            route = write_route_plan(root)
            state = write_state(
                root,
                {
                    "current_phase": "delivered",
                    "active_change": None,
                    "pending_gate": None,
                    "next_action": {"type": "done", "text": "workflow delivered", "stop_reason": "delivered"},
                },
            )

            errors, warnings = state_transition.validate_transition(
                route_plan_path=route,
                state_path=state,
                approved_gate="CP8",
            )

            self.assertEqual([], errors)
            self.assertEqual([], warnings)

    def test_approved_cp8_rejects_incomplete_or_false_delivered_state(self) -> None:
        invalid_states = (
            {
                "current_phase": "delivered",
                "active_change": None,
                "pending_gate": None,
                "next_action": {"type": "done", "stop_reason": "no_remaining_route"},
            },
            {
                "current_phase": "delivered",
                "active_change": None,
                "pending_gate": "CP7",
                "next_action": {"type": "done", "stop_reason": "delivered"},
            },
            {
                "current_phase": "delivered",
                "active_change": "CR-158",
                "pending_gate": None,
                "next_action": {"type": "done", "stop_reason": "delivered"},
            },
            {
                "current_phase": "documentation",
                "active_change": None,
                "pending_gate": None,
                "next_action": {"type": "done", "stop_reason": "delivered"},
            },
        )
        for state_patch in invalid_states:
            with self.subTest(state_patch=state_patch), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                route = write_route_plan(root)
                state = write_state(root, state_patch)

                errors, _warnings = state_transition.validate_transition(
                    route_plan_path=route,
                    state_path=state,
                    approved_gate="CP8",
                )

                self.assertTrue(any("true delivered terminal state" in error for error in errors))

    def test_approved_cp8_accepts_legitimate_interrupt_without_pending_gate(self) -> None:
        for stop_reason in ("authorization_required", "workflow_health_threshold"):
            with self.subTest(stop_reason=stop_reason), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                route = write_route_plan(root)
                state = write_state(
                    root,
                    {
                        "current_phase": "documentation",
                        "active_change": "CR-158",
                        "pending_gate": None,
                        "next_action": {"type": "blocked", "text": "legitimate interruption", "stop_reason": stop_reason},
                    },
                )

                errors, warnings = state_transition.validate_transition(
                    route_plan_path=route,
                    state_path=state,
                    approved_gate="CP8",
                )

                self.assertEqual([], errors)
                self.assertEqual([], warnings)

    def test_explicit_stop_reason_allows_blocked_transition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            route = write_route_plan(root)
            state = write_state(
                root,
                {
                    "next_action": {
                        "type": "blocked",
                        "text": "authorization required before continuing",
                        "stop_reason": "authorization_required",
                    }
                },
            )

            errors, _warnings = state_transition.validate_transition(
                route_plan_path=route,
                state_path=state,
                approved_gate="CP3",
            )

            self.assertEqual([], errors)

    def test_cp7_pass_like_decisions_reject_stale_failure_stop_reasons(self) -> None:
        for decision in ("PASS", "PASS_WITH_RISK"):
            for stop_reason in ("needs_rework", "needs_design_clarification", "blocked"):
                with self.subTest(decision=decision, stop_reason=stop_reason), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    route = write_route_plan(root)
                    state = write_state(
                        root,
                        {
                            "next_action": {
                                "type": "blocked",
                                "text": "stale failure state",
                                "stop_reason": stop_reason,
                            }
                        },
                    )

                    errors, _warnings = state_transition.validate_transition(
                        route_plan_path=route,
                        state_path=state,
                        checkpoint="CP7",
                        decision=decision,
                    )

                    self.assertTrue(any("cannot retain failure stop_reason" in error for error in errors))
                    self.assertTrue(any("pending_gate=CP8" in error for error in errors))

    def test_cp7_pass_like_decisions_accept_pending_cp8(self) -> None:
        for decision in ("PASS", "PASS_WITH_RISK"):
            with self.subTest(decision=decision), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                route = write_route_plan(root)
                state = write_state(
                    root,
                    {
                        "current_phase": "documentation",
                        "pending_gate": "CP8",
                        "pending_checklist_path": "process/checkpoints/CP8-DELIVERY-READINESS.md",
                        "next_action": {"type": "await_user", "text": "review CP8"},
                    },
                )

                errors, warnings = state_transition.validate_transition(
                    route_plan_path=route,
                    state_path=state,
                    checkpoint="CP7",
                    decision=decision,
                )

                self.assertEqual([], errors)
                self.assertEqual([], warnings)

    def test_cp7_pass_like_decision_accepts_next_story_before_final_cp8(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            route = write_route_plan(root)
            state = write_state(
                root,
                {
                    "current_phase": "story-execution",
                    "active_change": "CR-158",
                    "active_story": "STORY-NEXT",
                    "pending_gate": None,
                    "next_action": {"type": "inline_implementation", "text": "advance dependency graph"},
                },
            )

            errors, warnings = state_transition.validate_transition(
                route_plan_path=route,
                state_path=state,
                checkpoint="CP7",
                decision="PASS_WITH_RISK",
            )

            self.assertEqual([], errors)
            self.assertEqual([], warnings)

    def test_cp7_pass_accepts_decision_compatible_interrupts(self) -> None:
        for stop_reason in ("authorization_required", "workflow_health_threshold"):
            with self.subTest(stop_reason=stop_reason), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                route = write_route_plan(root)
                state = write_state(
                    root,
                    {
                        "next_action": {
                            "type": "blocked",
                            "text": "legitimate workflow interruption",
                            "stop_reason": stop_reason,
                        }
                    },
                )

                errors, _warnings = state_transition.validate_transition(
                    route_plan_path=route,
                    state_path=state,
                    checkpoint="CP7",
                    decision="PASS",
                )

                self.assertEqual([], errors)

    def test_historical_pass_like_result_accepts_true_delivered_terminal_replay(self) -> None:
        for checkpoint in ("CP4", "CP7"):
            for decision in ("PASS", "PASS_WITH_RISK"):
                with self.subTest(checkpoint=checkpoint, decision=decision), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    route = write_route_plan(root)
                    state = write_state(
                        root,
                        {
                            "current_phase": "delivered",
                            "active_change": None,
                            "pending_gate": None,
                            "next_action": {"type": "done", "text": "workflow delivered", "stop_reason": "delivered"},
                        },
                    )

                    errors, warnings = state_transition.validate_transition(
                        route_plan_path=route,
                        state_path=state,
                        checkpoint=checkpoint,
                        decision=decision,
                    )

                    self.assertEqual([], errors)
                    self.assertEqual([], warnings)

    def test_pass_like_terminal_replay_requires_complete_delivered_state(self) -> None:
        invalid_states = (
            {"current_phase": "delivered", "active_change": "CR-158", "next_action": {"stop_reason": "delivered"}},
            {"current_phase": "delivered", "active_change": None, "pending_gate": "CP8", "next_action": {"stop_reason": "delivered"}},
            {"current_phase": "delivered", "active_change": None, "next_action": {"stop_reason": "no_remaining_route"}},
            {"current_phase": "documentation", "active_change": None, "next_action": {"stop_reason": "delivered"}},
        )
        for state_patch in invalid_states:
            with self.subTest(state_patch=state_patch), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                route = write_route_plan(root)
                state = write_state(root, state_patch)

                errors, _warnings = state_transition.validate_transition(
                    route_plan_path=route,
                    state_path=state,
                    checkpoint="CP7",
                    decision="PASS",
                )

                self.assertTrue(errors)

    def test_failure_result_replay_rejects_delivered_stop_reason(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            route = write_route_plan(root)
            state = write_state(
                root,
                {
                    "current_phase": "delivered",
                    "active_change": None,
                    "pending_gate": None,
                    "next_action": {"type": "done", "text": "workflow delivered", "stop_reason": "delivered"},
                },
            )

            errors, _warnings = state_transition.validate_transition(
                route_plan_path=route,
                state_path=state,
                checkpoint="CP7",
                decision="NEEDS_REWORK",
            )

            self.assertTrue(any("stop_reason in {needs_rework}" in error for error in errors))

    def test_failure_decisions_accept_decision_compatible_stop_reasons(self) -> None:
        cases = (
            ("FAIL", "blocked"),
            ("BLOCKED", "blocked"),
            ("BLOCKED", "authorization_required"),
            ("BLOCKED", "workflow_health_threshold"),
            ("NEEDS_REWORK", "needs_rework"),
            ("NEEDS_DESIGN_CLARIFICATION", "needs_design_clarification"),
        )
        for decision, stop_reason in cases:
            with self.subTest(decision=decision), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                route = write_route_plan(root)
                state = write_state(
                    root,
                    {"next_action": {"type": "blocked", "text": "failure", "stop_reason": stop_reason}},
                )

                errors, _warnings = state_transition.validate_transition(
                    route_plan_path=route,
                    state_path=state,
                    checkpoint="CP7",
                    decision=decision,
                )

                self.assertEqual([], errors)

    def test_failure_decisions_reject_incompatible_stop_reasons(self) -> None:
        cases = (
            ("FAIL", "authorization_required"),
            ("FAIL", "workflow_health_threshold"),
            ("BLOCKED", "needs_rework"),
            ("BLOCKED", "needs_design_clarification"),
            ("NEEDS_REWORK", "blocked"),
            ("NEEDS_REWORK", "authorization_required"),
            ("NEEDS_REWORK", "workflow_health_threshold"),
            ("NEEDS_REWORK", "needs_design_clarification"),
            ("NEEDS_DESIGN_CLARIFICATION", "blocked"),
            ("NEEDS_DESIGN_CLARIFICATION", "authorization_required"),
            ("NEEDS_DESIGN_CLARIFICATION", "workflow_health_threshold"),
            ("NEEDS_DESIGN_CLARIFICATION", "needs_rework"),
        )
        for decision, stop_reason in cases:
            with self.subTest(decision=decision, stop_reason=stop_reason), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                route = write_route_plan(root)
                state = write_state(
                    root,
                    {"next_action": {"type": "blocked", "text": "wrong failure", "stop_reason": stop_reason}},
                )

                errors, _warnings = state_transition.validate_transition(
                    route_plan_path=route,
                    state_path=state,
                    checkpoint="CP7",
                    decision=decision,
                )

                self.assertTrue(any("must leave matching stop_reason" in error for error in errors))

    def test_cli_reports_state_transition_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            route = write_route_plan(root)
            write_state(root, {"next_action": {"type": "continue", "text": "manual continue requested"}})
            output = StringIO()

            with redirect_stdout(output):
                exit_code = state_transition.main(
                    [
                        "--project-root",
                        str(root),
                        "--route-plan",
                        str(route),
                        "--checkpoint",
                        "CP4",
                        "--decision",
                        "PASS",
                    ]
                )

            self.assertEqual(1, exit_code)
            self.assertIn("State Transition Check: FAIL", output.getvalue())
            self.assertIn("pending_gate=CP5", output.getvalue())

    def test_cli_reports_chronology_findings_as_stable_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload_path = root / "chronology.json"
            payload_path.write_text(
                json.dumps(
                    {
                        "events": [
                            {"kind": "gate-opened", "occurred_at": "2026-07-12T00:01:00Z", "source_ref": "gate"},
                            {"kind": "approved", "occurred_at": "2026-07-12T00:00:00Z", "source_ref": "approval"},
                        ],
                        "state": {"pending_gate": None},
                    }
                ),
                encoding="utf-8",
            )
            output = StringIO()

            with redirect_stdout(output):
                exit_code = state_transition.main(
                    ["--chronology-events", str(payload_path), "--output", "json"]
                )

            result = json.loads(output.getvalue())
            self.assertEqual(1, exit_code)
            self.assertEqual("FAIL", result["status"])
            self.assertEqual("pending", result["decision"])
            self.assertEqual("TEMPORAL_ORDER_VIOLATION", result["findings"][0]["code"])


if __name__ == "__main__":
    unittest.main()
