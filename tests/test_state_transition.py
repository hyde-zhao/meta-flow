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


if __name__ == "__main__":
    unittest.main()
