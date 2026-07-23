"""Validate post-approval and automatic-CP workflow transitions."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from meta_flow.project.process_route import _resolve_runtime_ref

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
FAILURE_STOP_REASONS = {
    "FAIL": {"blocked"},
    "BLOCKED": {"blocked", "authorization_required", "workflow_health_threshold"},
    "NEEDS_REWORK": {"needs_rework"},
    "NEEDS_DESIGN_CLARIFICATION": {"needs_design_clarification"},
}
PASS_COMPATIBLE_INTERRUPT_REASONS = {"authorization_required", "workflow_health_threshold"}
STALE_FAILURE_STOP_REASONS = {"blocked", "needs_rework", "needs_design_clarification"}


@dataclass(frozen=True)
class ChronologyNode:
    """A typed, timezone-aware timestamp from canonical workflow evidence."""

    kind: str
    occurred_at: str | datetime | None
    source_ref: str


@dataclass(frozen=True)
class ChronologyFinding:
    """Stable, machine-consumable chronology validation output."""

    code: str
    object_ref: str
    field: str
    message: str
    source_refs: tuple[str, ...] = ()


CHRONOLOGY_KINDS = {
    "producer-complete",
    "checkpoint-created",
    "gate-opened",
    "conditional-received",
    "conditions-satisfied",
    "reviewed",
    "approved",
    "downstream-dispatch",
}
PRECEDENCE_EDGES = (
    ("producer-complete", "checkpoint-created"),
    ("checkpoint-created", "gate-opened"),
    ("gate-opened", "reviewed"),
    # Review is optional for compatibility, but a final approval must still
    # occur after the gate was formally opened when no review node is present.
    ("gate-opened", "approved"),
    ("reviewed", "approved"),
    ("approved", "downstream-dispatch"),
    ("conditional-received", "conditions-satisfied"),
    ("conditions-satisfied", "approved"),
)


def _parse_chronology_time(value: str | datetime | None) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        token = value.strip()
        if token.endswith("Z"):
            token = f"{token[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(token)
        except ValueError:
            return None
    else:
        return None
    return parsed if parsed.tzinfo is not None else None


def _chronology_finding(
    code: str,
    node: ChronologyNode,
    field: str,
    message: str,
    *refs: str,
) -> ChronologyFinding:
    return ChronologyFinding(
        code=code,
        object_ref=node.source_ref,
        field=field,
        message=message,
        source_refs=tuple(ref for ref in refs if ref),
    )


def validate_chronology(nodes: list[ChronologyNode]) -> list[ChronologyFinding]:
    """Validate the partial order of one canonical workflow attempt.

    Optional nodes are not fabricated.  Multiple nodes of the same kind are
    accepted only when they agree; a conflicting duplicate is surfaced as a
    deterministic temporal finding instead of being silently selected.
    """

    findings: list[ChronologyFinding] = []
    indexed: dict[str, tuple[ChronologyNode, datetime]] = {}
    conditional_present = False
    for node in nodes:
        if node.kind not in CHRONOLOGY_KINDS:
            findings.append(_chronology_finding("UNKNOWN_CHRONOLOGY_KIND", node, "kind", "unknown chronology kind"))
            continue
        if not node.source_ref.strip():
            findings.append(
                _chronology_finding(
                    "INVALID_SOURCE_REF",
                    node,
                    "source_ref",
                    "chronology nodes require a non-empty canonical source_ref",
                )
            )
            continue
        if node.kind == "conditional-received":
            conditional_present = True
        parsed = _parse_chronology_time(node.occurred_at)
        if parsed is None:
            findings.append(
                _chronology_finding(
                    "UNPARSEABLE_TIMESTAMP",
                    node,
                    "occurred_at",
                    "chronology timestamps must be RFC3339 values with an explicit timezone",
                )
            )
            continue
        existing = indexed.get(node.kind)
        if existing is not None and existing[1] != parsed:
            findings.append(
                _chronology_finding(
                    "TEMPORAL_ORDER_VIOLATION",
                    node,
                    "occurred_at",
                    f"conflicting duplicate timestamp for {node.kind}",
                    existing[0].source_ref,
                )
            )
            continue
        indexed[node.kind] = (node, parsed)

    for earlier_kind, later_kind in PRECEDENCE_EDGES:
        earlier = indexed.get(earlier_kind)
        later = indexed.get(later_kind)
        if earlier is None or later is None:
            continue
        if earlier[1] > later[1]:
            findings.append(
                _chronology_finding(
                    "TEMPORAL_ORDER_VIOLATION",
                    later[0],
                    "occurred_at",
                    f"{earlier_kind} must not occur after {later_kind}",
                    earlier[0].source_ref,
                )
            )

    approved = indexed.get("approved")
    gate_opened = indexed.get("gate-opened")
    if approved is not None and gate_opened is None:
        findings.append(
            _chronology_finding(
                "APPROVAL_BEFORE_GATE",
                approved[0],
                "occurred_at",
                "final approval requires a prior gate-opened event",
            )
        )
    if conditional_present and approved is not None and "conditions-satisfied" not in indexed:
        findings.append(
            _chronology_finding(
                "CONDITIONS_UNSATISFIED",
                approved[0],
                "occurred_at",
                "conditional approval requires a conditions-satisfied event before final approval",
            )
        )
    return sorted(findings, key=lambda item: (item.code, item.object_ref, item.field, item.message))


def derive_gate_decision(events: list[ChronologyNode]) -> tuple[str, list[ChronologyFinding]]:
    """Return the gate state without promoting a conditional instruction to approval."""

    findings = validate_chronology(events)
    kinds = {event.kind for event in events}
    if findings:
        return "pending", findings
    if "approved" in kinds:
        return "approved", findings
    if "conditions-satisfied" in kinds:
        return "conditions-satisfied", findings
    if "conditional-received" in kinds:
        return "conditional", findings
    return "pending", findings


def validate_phase_gate_state(state: dict[str, Any], gate_events: list[ChronologyNode]) -> list[ChronologyFinding]:
    """Keep phase work in progress separate from an opened human gate."""

    findings: list[ChronologyFinding] = []
    decision, chronology_findings = derive_gate_decision(gate_events)
    findings.extend(chronology_findings)
    pending_gate = str(state.get("pending_gate") or "")
    kinds = {event.kind for event in gate_events}
    approved_nodes = [event for event in gate_events if event.kind == "approved"]
    reference = approved_nodes[0] if approved_nodes else ChronologyNode("gate-opened", None, "STATE.current.json")

    if "gate-opened" not in kinds and {"reviewed", "approved"} & kinds:
        observed = next(event for event in gate_events if event.kind in {"reviewed", "approved"})
        findings.append(
            _chronology_finding(
                "PHASE_GATE_CONFLATION",
                observed,
                "kind",
                "formal review or approval cannot be recorded while gate-open is false",
            )
        )

    if decision in {"conditional", "conditions-satisfied"} and not pending_gate:
        findings.append(
            _chronology_finding(
                "PHASE_GATE_CONFLATION",
                reference,
                "pending_gate",
                "an unresolved conditional gate must remain represented by pending_gate",
            )
        )
    if decision == "approved":
        has_downstream_dispatch = "downstream-dispatch" in kinds
        if pending_gate:
            findings.append(
                _chronology_finding(
                    "PHASE_GATE_CONFLATION",
                    reference,
                    "pending_gate",
                    "a final approved gate cannot remain pending",
                )
            )
        elif not has_downstream_dispatch:
            findings.append(
                _chronology_finding(
                    "PHASE_GATE_CONFLATION",
                    reference,
                    "pending_gate",
                    "an approved gate without pending_gate requires a downstream transition record",
                )
            )
    return sorted(findings, key=lambda item: (item.code, item.object_ref, item.field, item.message))


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
    return _resolve_runtime_ref(project_root, "process/state/STATE.current.json")


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


def _has_automatic_stage_before_gate(stages: list[dict[str, Any]], checkpoint: str, gate: str) -> bool:
    """Return whether a route has real automatic work before its next human gate."""

    start = _stage_index(stages, checkpoint)
    end = _stage_index(stages, gate)
    if start < 0 or end <= start:
        return False
    return any(str(stage.get("human_gate") or "none") == "none" for stage in stages[start + 1 : end])


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


def _is_true_delivered_terminal(state: dict[str, Any]) -> bool:
    return (
        str(state.get("current_phase") or "") == "delivered"
        and not state.get("active_change")
        and not state.get("pending_gate")
        and _stop_reason(state) == "delivered"
    )


def _decision_compatible_stop_reasons(decision: str, expected: dict[str, str]) -> set[str]:
    if decision in FAILURE_STOP_REASONS:
        return set(FAILURE_STOP_REASONS[decision])
    if decision in PASS_LIKE_DECISIONS:
        reasons = set(PASS_COMPATIBLE_INTERRUPT_REASONS)
        expected_kind = expected.get("kind") or ""
        if expected_kind == "required_human_gate":
            reasons.add("required_human_gate")
        elif expected_kind == "delivered":
            reasons.add("delivered")
        elif expected_kind == "no_remaining_required_gate":
            reasons.add("no_remaining_route")
        return reasons
    return set(ALLOWED_STOP_REASONS)


def _has_valid_stop_reason(state: dict[str, Any], expected: dict[str, str], *, decision: str = "") -> bool:
    reason = _stop_reason(state)
    if reason not in _decision_compatible_stop_reasons(decision, expected):
        return False
    if reason == "required_human_gate":
        return bool(state.get("pending_gate")) and str(state.get("pending_gate")) == expected.get("checkpoint")
    if reason == "delivered":
        return str(state.get("current_phase") or "") == "delivered"
    return True


def _state_matches_expected_stop(state: dict[str, Any], expected: dict[str, str], *, decision: str = "") -> list[str]:
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
        if _has_valid_stop_reason(state, expected, decision=decision):
            return errors
        errors.append(
            f"post-transition must advance to pending_gate={expected_gate} or record a valid stop_reason; "
            f"got pending_gate={pending_gate or '-'} next_action.type={action_type or '-'}"
        )
        return errors

    if kind == "delivered":
        if _is_true_delivered_terminal(state):
            return errors
        if not pending_gate and _stop_reason(state) in PASS_COMPATIBLE_INTERRUPT_REASONS:
            return errors
        errors.append(
            "CP8 approval must reach a true delivered terminal state with no active_change/pending_gate "
            "and stop_reason=delivered, or record authorization_required/workflow_health_threshold"
        )
        return errors

    if _has_valid_stop_reason(state, expected, decision=decision):
        return errors
    if action_type in {"await_user", "continue", "wait_user"} and not pending_gate:
        errors.append("route has no remaining required gate; state must continue automatically, deliver, or record a valid stop_reason")
    return errors


def _is_automatic_phase_in_progress(
    *,
    route: dict[str, Any],
    state: dict[str, Any],
    checkpoint: str,
    expected: dict[str, str],
) -> bool:
    """Accept actual automatic work instead of forcing a future gate into STATE.

    A gate approval may legitimately be followed by CP6/CP7 work.  The state
    is not allowed to claim the later gate before its checklist exists, but it
    also must not fail merely because the automatic work has not finished.
    """

    if expected.get("kind") != "required_human_gate" or checkpoint not in {"CP5", "CP6", "CP7"}:
        return False
    stages = [stage for stage in route.get("stages") or [] if isinstance(stage, dict)]
    if checkpoint != "CP7" and not _has_automatic_stage_before_gate(stages, checkpoint, expected.get("checkpoint") or ""):
        return False
    if state.get("pending_gate") or str(state.get("current_phase") or "") != "story-execution":
        return False
    if checkpoint == "CP7" and not state.get("active_story"):
        # CP7 is rolling.  The final Story must clear active_story and open
        # CP8; an earlier Story may advance the dependency graph instead.
        return False
    action_type = str(_next_action(state).get("type") or "")
    if action_type in AWAIT_USER_ACTION_TYPES or action_type in {"blocked", "done"}:
        return False
    return bool(state.get("active_change")) and bool(str(state.get("current_phase") or "").strip())


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
        expected_failure = {"kind": "failure", "checkpoint": ""}
        if not _has_valid_stop_reason(state, expected_failure, decision=decision):
            errors.append(
                f"{checkpoint} decision={decision} must leave matching "
                "stop_reason in {"
                + ", ".join(sorted(FAILURE_STOP_REASONS[decision]))
                + "}"
            )
        return errors, warnings
    if decision not in PASS_LIKE_DECISIONS:
        warnings.append(f"{checkpoint} decision={decision} is not pass-like; transition guard did not enforce auto-advance")
        return errors, warnings
    if human_gate != "none":
        warnings.append(f"{checkpoint} human_gate={human_gate}; use --approved-gate after human approval is recorded")
        return errors, warnings
    if _is_true_delivered_terminal(state):
        return errors, warnings
    expected = expected_post_transition(route, checkpoint)
    stale_failure_reason = _stop_reason(state)
    if stale_failure_reason in STALE_FAILURE_STOP_REASONS:
        errors.append(
            f"{checkpoint} decision={decision} cannot retain failure stop_reason={stale_failure_reason}"
        )
    if not _is_automatic_phase_in_progress(route=route, state=state, checkpoint=checkpoint, expected=expected):
        errors.extend(_state_matches_expected_stop(state, expected, decision=decision))
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
    if not _is_automatic_phase_in_progress(route=route, state=state, checkpoint=checkpoint, expected=expected):
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
    parser.add_argument("--route-plan", type=Path, default=None)
    parser.add_argument("--state", type=Path, default=None)
    parser.add_argument("--result", type=Path, default=None, help="CP result JSON for automatic CP PASS/WAIVED transitions")
    parser.add_argument("--checkpoint", default="", help="Checkpoint id when --result is not supplied")
    parser.add_argument("--decision", default="", help="Decision when --result is not supplied")
    parser.add_argument("--approved-gate", default="", help="Required human gate that was just approved, for example CP3")
    parser.add_argument(
        "--chronology-events",
        type=Path,
        default=None,
        help="JSON object containing events[] and optional state for chronology-only validation",
    )
    parser.add_argument("--output", choices=("text", "json"), default="text")
    parsed = parser.parse_args(argv)

    project_root = parsed.project_root.resolve()
    if parsed.chronology_events:
        try:
            payload = _read_json(parsed.chronology_events)
            raw_events = payload.get("events")
            if not isinstance(raw_events, list):
                raise ValueError("chronology events payload requires events[]")
            nodes = [
                ChronologyNode(
                    kind=str(item.get("kind") or ""),
                    occurred_at=item.get("occurred_at"),
                    source_ref=str(item.get("source_ref") or ""),
                )
                for item in raw_events
                if isinstance(item, dict)
            ]
            if len(nodes) != len(raw_events):
                raise ValueError("chronology events[] entries must be JSON objects")
            findings = validate_phase_gate_state(payload.get("state") or {}, nodes)
            decision, _ = derive_gate_decision(nodes)
            errors = [finding.message for finding in findings]
            warnings: list[str] = []
        except ValueError as exc:
            findings = []
            decision = "pending"
            errors, warnings = [str(exc)], []
        if parsed.output == "json":
            print(
                json.dumps(
                    {
                        "decision": decision,
                        "findings": [asdict(finding) for finding in findings],
                        "status": "FAIL" if errors else "OK",
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        else:
            print("State Transition Check: " + ("FAIL" if errors else "OK"))
            print(f"- gate_decision: {decision}")
            for finding in findings:
                print(f"- ERROR: {finding.code} {finding.object_ref}.{finding.field}: {finding.message}")
            for error in errors if not findings else []:
                print(f"- ERROR: {error}")
        return 1 if errors else 0

    if parsed.route_plan is None:
        parser.error("--route-plan is required unless --chronology-events is supplied")
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
    except FileNotFoundError as exc:
        # STATE.current.json 是派生投影；CP5 批准后的 CP6 工作可在其尚未
        # 建立时继续，不能为了通过检查而创建该状态文件。
        missing_path = Path(exc.filename).resolve() if exc.filename else None
        if (
            parsed.approved_gate == "CP5"
            and state_path.name == "STATE.current.json"
            and missing_path == state_path.resolve()
        ):
            errors, warnings = [], [f"state projection absent: {exc.filename}; CP5 transition accepted without mutation"]
        else:
            errors, warnings = [str(exc)], []
    except ValueError as exc:
        errors, warnings = [str(exc)], []
    if parsed.output == "json":
        print(json.dumps({"errors": errors, "status": "FAIL" if errors else "OK", "warnings": warnings}, ensure_ascii=False, sort_keys=True))
    else:
        print("State Transition Check: " + ("FAIL" if errors else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
