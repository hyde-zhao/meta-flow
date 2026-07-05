"""Validate post-approval and automatic-CP workflow transitions."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PASS_LIKE_DECISIONS = {"PASS", "WAIVED", "PASS_WITH_RISK"}
FAILURE_DECISIONS = {"FAIL", "BLOCKED", "NEEDS_REWORK", "NEEDS_DESIGN_CLARIFICATION"}
ALLOWED_STOP_REASONS = {
    "required_human_gate",
    "blocked",
    "needs_rework",
    "needs_design_clarification",
    "authorization_required",
    "workflow_health_threshold",
    "delivered",
    "no_remaining_route",
}
AWAIT_USER_ACTION_TYPES = {"await_user", "human_gate", "required_human_gate"}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _state_path(project_root: Path, explicit: Path | None = None) -> Path:
    if explicit:
        return explicit
    return project_root / "process" / "state" / "STATE.current.json"


def _stage_index(stages: list[dict[str, Any]], checkpoint: str) -> int:
    for index, stage in enumerate(stages):
        if str(stage.get("checkpoint") or "") == checkpoint:
            return index
    return -1


def _next_required_gate(stages: list[dict[str, Any]], checkpoint: str) -> str:
    start = _stage_index(stages, checkpoint)
    if start < 0:
        return ""
    for stage in stages[start + 1 :]:
        if str(stage.get("human_gate") or "none") == "required":
            return str(stage.get("checkpoint") or "")
    return ""


def expected_post_transition(route: dict[str, Any], checkpoint: str) -> dict[str, str]:
    """Return the required stop target after a checkpoint or approved gate."""

    stages = [stage for stage in route.get("stages") or [] if isinstance(stage, dict)]
    expected_gate = _next_required_gate(stages, checkpoint)
    if expected_gate:
        return {"kind": "required_human_gate", "checkpoint": expected_gate}
    if checkpoint == "CP8":
        return {"kind": "delivered", "checkpoint": ""}
    return {"kind": "no_remaining_required_gate", "checkpoint": ""}


def _next_action(state: dict[str, Any]) -> dict[str, Any]:
    value = state.get("next_action") or {}
    if isinstance(value, dict):
        return value
    if value:
        return {"type": "continue", "text": str(value)}
    return {}


def _stop_reason(state: dict[str, Any]) -> str:
    action = _next_action(state)
    reason = str(action.get("stop_reason") or action.get("reason") or "")
    return reason.strip()


def _has_valid_stop_reason(state: dict[str, Any], expected: dict[str, str]) -> bool:
    reason = _stop_reason(state)
    if reason not in ALLOWED_STOP_REASONS:
        return False
    if reason == "required_human_gate":
        return bool(state.get("pending_gate")) and str(state.get("pending_gate")) == expected.get("checkpoint")
    if reason == "delivered":
        return str(state.get("current_phase") or "") == "delivered"
    return True


def _state_matches_expected_stop(state: dict[str, Any], expected: dict[str, str]) -> list[str]:
    errors: list[str] = []
    kind = expected.get("kind") or ""
    expected_gate = expected.get("checkpoint") or ""
    pending_gate = str(state.get("pending_gate") or "")
    action = _next_action(state)
    action_type = str(action.get("type") or "")

    if kind == "required_human_gate":
        if pending_gate == expected_gate:
            if not state.get("pending_checklist_path"):
                errors.append(f"{expected_gate} is pending but pending_checklist_path is missing")
            if action_type and action_type not in AWAIT_USER_ACTION_TYPES:
                errors.append(f"{expected_gate} pending gate should use await_user next_action.type, got {action_type}")
            return errors
        if _has_valid_stop_reason(state, expected):
            return errors
        errors.append(
            f"post-transition must advance to pending_gate={expected_gate} or record a valid stop_reason; "
            f"got pending_gate={pending_gate or '-'} next_action.type={action_type or '-'}"
        )
        return errors

    if kind == "delivered":
        if str(state.get("current_phase") or "") == "delivered" and not state.get("active_change"):
            return errors
        if _has_valid_stop_reason(state, expected):
            return errors
        errors.append("CP8 approval must close the active CR and advance current_phase=delivered, or record a valid stop_reason")
        return errors

    if _has_valid_stop_reason(state, expected):
        return errors
    if action_type in {"await_user", "continue", "wait_user"} and not pending_gate:
        errors.append("route has no remaining required gate; state must continue automatically, deliver, or record a valid stop_reason")
    return errors


def validate_auto_cp_transition(
    *,
    route: dict[str, Any],
    state: dict[str, Any],
    checkpoint: str,
    decision: str,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    stages = [stage for stage in route.get("stages") or [] if isinstance(stage, dict)]
    index = _stage_index(stages, checkpoint)
    if index < 0:
        return [f"{checkpoint} is not present in route_plan.stages"], warnings
    human_gate = str(stages[index].get("human_gate") or "none")
    if decision in FAILURE_DECISIONS:
        if not _has_valid_stop_reason(state, {"kind": "failure", "checkpoint": ""}):
            errors.append(f"{checkpoint} decision={decision} must leave a valid stop_reason")
        return errors, warnings
    if decision not in PASS_LIKE_DECISIONS:
        warnings.append(f"{checkpoint} decision={decision} is not pass-like; transition guard did not enforce auto-advance")
        return errors, warnings
    if human_gate != "none":
        warnings.append(f"{checkpoint} human_gate={human_gate}; use --approved-gate after human approval is recorded")
        return errors, warnings
    expected = expected_post_transition(route, checkpoint)
    errors.extend(_state_matches_expected_stop(state, expected))
    return errors, warnings


def validate_approved_gate_transition(
    *,
    route: dict[str, Any],
    state: dict[str, Any],
    checkpoint: str,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    stages = [stage for stage in route.get("stages") or [] if isinstance(stage, dict)]
    index = _stage_index(stages, checkpoint)
    if index < 0:
        return [f"{checkpoint} is not present in route_plan.stages"], warnings
    human_gate = str(stages[index].get("human_gate") or "none")
    if human_gate != "required":
        warnings.append(f"{checkpoint} human_gate={human_gate}; approved-gate transition is normally checked for required gates")
    pending_gate = str(state.get("pending_gate") or "")
    if pending_gate == checkpoint:
        errors.append(f"{checkpoint} approval was recorded but STATE.current.json still waits on the same pending_gate")
        return errors, warnings
    expected = expected_post_transition(route, checkpoint)
    errors.extend(_state_matches_expected_stop(state, expected))
    return errors, warnings


def validate_transition(
    *,
    route_plan_path: Path,
    state_path: Path,
    result_path: Path | None = None,
    checkpoint: str = "",
    decision: str = "",
    approved_gate: str = "",
) -> tuple[list[str], list[str]]:
    route = _read_json(route_plan_path)
    state = _read_json(state_path)
    if approved_gate:
        return validate_approved_gate_transition(route=route, state=state, checkpoint=approved_gate)
    if result_path:
        result = _read_json(result_path)
        checkpoint = str(result.get("checkpoint") or result.get("checkpoint_id") or checkpoint)
        decision = str(result.get("decision") or decision)
    if not checkpoint or not decision:
        return ["provide --result or both --checkpoint and --decision"], []
    return validate_auto_cp_transition(route=route, state=state, checkpoint=checkpoint, decision=decision)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="meta-flow check state-transition",
        description="Validate that approve/auto-CP transitions run until the next required gate, delivery, or an explicit stop_reason.",
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--route-plan", type=Path, required=True)
    parser.add_argument("--state", type=Path, default=None)
    parser.add_argument("--result", type=Path, default=None, help="CP result JSON for automatic CP PASS/WAIVED transitions")
    parser.add_argument("--checkpoint", default="", help="Checkpoint id when --result is not supplied")
    parser.add_argument("--decision", default="", help="Decision when --result is not supplied")
    parser.add_argument("--approved-gate", default="", help="Required human gate that was just approved, for example CP3")
    parsed = parser.parse_args(argv)

    project_root = parsed.project_root.resolve()
    state_path = _state_path(project_root, parsed.state)
    try:
        errors, warnings = validate_transition(
            route_plan_path=parsed.route_plan,
            state_path=state_path,
            result_path=parsed.result,
            checkpoint=parsed.checkpoint,
            decision=parsed.decision,
            approved_gate=parsed.approved_gate,
        )
    except ValueError as exc:
        errors, warnings = [str(exc)], []
    print("State Transition Check: " + ("FAIL" if errors else "OK"))
    for warning in warnings:
        print(f"- WARN: {warning}")
    for error in errors:
        print(f"- ERROR: {error}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
