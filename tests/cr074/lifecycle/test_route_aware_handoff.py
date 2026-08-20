from __future__ import annotations

import inspect
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from test_work_lifecycle_transaction import (
    _enable_state_projection,
    _governance_fixture,
    make_work,
)

from meta_flow.work.budget import BudgetLimit
from meta_flow.work.handoff import (
    HandoffPolicyDecisionV1,
    WorkHandoff,
    decide_handoff_policy,
)
from meta_flow.work.model import build_work, load_work
from meta_flow.work.risk import RiskFacts, classify_work
from meta_flow.work.route_profile import RouteProfile
from meta_flow.work.scope import WorkScope
from meta_flow.work.status_transition import (
    WorkStatusTransitionAuthorizationV2,
    apply_work_status_transition,
    inspect_work_status_transitions,
    plan_work_status_transition,
    recover_work_status_transition,
)
from meta_flow.work.store import apply_work_init, plan_work_init_from_release_root
from meta_flow.work.transaction_child import handoff_for_parent, recover_handoff


def _work(
    risk_profile: str,
    *,
    route_profile: RouteProfile | None = None,
):
    facts = RiskFacts(
        change_kind="documentation" if risk_profile == "G0" else "code",
        touched_path_count=1 if risk_profile == "G0" else 2,
        public_contract=risk_profile == "G2",
    )
    classification = classify_work(
        facts,
        g2_budget=(BudgetLimit(30, 30, 12, 160_000) if risk_profile == "G2" else None),
    )
    assert classification.risk_profile == risk_profile
    return build_work(
        work_id=f"W-{risk_profile}",
        project_id="meta-flow",
        objective="验证 route-aware handoff policy",
        request_ref=f"works/W-{risk_profile}/REQUEST.md",
        scope=WorkScope(1, (), (), ()),
        classification=classification,
        release_base_oid="a" * 40,
        process_base_oid="b" * 40,
        route_profile=route_profile or RouteProfile(),
    )


@pytest.mark.parametrize("risk_profile", ("G0", "G1"))
@pytest.mark.parametrize("transition", ("paused", "blocked"))
def test_routine_direct_g0_g1_handoff_is_not_required(
    risk_profile: str,
    transition: str,
) -> None:
    result = decide_handoff_policy(_work(risk_profile), transition)

    assert result.decision == "NOT_REQUIRED"
    assert result.required is False
    assert result.reason_codes == ("ROUTINE_DIRECT_G0_G1_HANDOFF_NOT_REQUIRED",)


@pytest.mark.parametrize("transition", ("paused", "blocked"))
def test_g2_functional_agent_handoff_is_required(transition: str) -> None:
    work = _work(
        "G2",
        route_profile=RouteProfile(dispatch_mode="functional-agent"),
    )

    result = decide_handoff_policy(work, transition)

    assert result.decision == "REQUIRED"
    assert result.required is True
    assert result.reason_codes == ("G2_FUNCTIONAL_AGENT_HANDOFF_REQUIRED",)


@pytest.mark.parametrize("transition", ("paused", "blocked"))
def test_g2_legacy_compatibility_handoff_is_required(transition: str) -> None:
    work = _work(
        "G2",
        route_profile=RouteProfile(
            mode="legacy-cp0-cp8",
            legacy_cp_compatibility=True,
        ),
    )

    result = decide_handoff_policy(work, transition)

    assert result.decision == "REQUIRED"
    assert result.required is True
    assert result.reason_codes == ("G2_LEGACY_CP_HANDOFF_REQUIRED",)


def test_g2_routine_direct_handoff_is_not_required() -> None:
    result = decide_handoff_policy(_work("G2"), "paused")

    assert result.decision == "NOT_REQUIRED"
    assert result.required is False
    assert result.reason_codes == ("ROUTINE_DIRECT_HANDOFF_NOT_REQUIRED",)


@pytest.mark.parametrize(
    "route_profile",
    (
        RouteProfile(dispatch_mode="functional-agent"),
        RouteProfile(mode="legacy-cp0-cp8", legacy_cp_compatibility=True),
    ),
)
def test_active_transition_never_requires_handoff(route_profile: RouteProfile) -> None:
    result = decide_handoff_policy(
        _work("G2", route_profile=route_profile),
        "active",
    )

    assert result.decision == "NOT_REQUIRED"
    assert result.required is False
    assert result.reason_codes == ("ACTIVE_TRANSITION_HANDOFF_NOT_REQUIRED",)


def test_policy_contract_is_closed_and_has_no_boolean_override() -> None:
    result = decide_handoff_policy(_work("G1"), "paused")

    assert isinstance(result, HandoffPolicyDecisionV1)
    assert tuple(inspect.signature(decide_handoff_policy).parameters) == ("work", "transition")
    assert result.as_dict() == {
        "schema_version": 1,
        "kind": "HandoffPolicyDecisionV1",
        "work_id": "W-G1",
        "transition": "paused",
        "required": False,
        "decision": "NOT_REQUIRED",
        "reason_codes": ["ROUTINE_DIRECT_G0_G1_HANDOFF_NOT_REQUIRED"],
    }


@pytest.mark.parametrize(
    "transition",
    (
        "ready_for_review",
        "ready_for_verification",
        "completed",
        "cancelled",
        "archived",
    ),
)
def test_legal_non_handoff_transition_is_not_required(transition: str) -> None:
    result = decide_handoff_policy(
        _work(
            "G2",
            route_profile=RouteProfile(dispatch_mode="functional-agent"),
        ),
        transition,
    )

    assert result.decision == "NOT_REQUIRED"
    assert result.required is False
    assert result.reason_codes == ("LIFECYCLE_TRANSITION_HANDOFF_NOT_REQUIRED",)


def test_policy_rejects_unknown_transition() -> None:
    with pytest.raises(ValueError, match="HANDOFF_POLICY_TRANSITION_INVALID"):
        decide_handoff_policy(_work("G1"), "unknown")


def _authorization(plan, suffix: str) -> WorkStatusTransitionAuthorizationV2:
    return WorkStatusTransitionAuthorizationV2(
        authorization_id=f"cr074-handoff-{suffix}-{plan.plan_digest[:12]}",
        work_id=plan.parent_plan.work_id,
        plan_digest=plan.plan_digest,
        parent_plan_digest=plan.parent_plan.plan_digest,
        target_refs=plan.target_refs,
        expires_at=(datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
    )


def _g2_fixture(tmp_path: Path):
    release, process, phase = _governance_fixture(tmp_path)
    _enable_state_projection(release, process)
    work = make_work(process, "W-G2", phase.phase_ref)
    classification = classify_work(
        RiskFacts(change_kind="code", touched_path_count=2, public_contract=True),
        g2_budget=BudgetLimit(30, 30, 12, 160_000),
    )
    work = replace(
        work,
        kind=classification.container_kind,
        risk_profile=classification.risk_profile,
        risk_reason_codes=classification.reason_codes,
        required_gates=classification.required_gates,
        budget=classification.budget,
        route_profile=RouteProfile(dispatch_mode="functional-agent"),
    )
    apply_work_init(plan_work_init_from_release_root(release, work))
    start = plan_work_status_transition(
        process,
        work.work_id,
        expected_status="planned",
        new_status="active",
    )
    assert (
        apply_work_status_transition(process, start, _authorization(start, "start")).decision
        == "PASS"
    )
    active = load_work(process, work.work_id)
    handoff = WorkHandoff(
        work_id=active.work_id,
        project_id=active.project_id,
        work_status="paused",
        scope_digest=active.scope.digest,
        release_oid="",
        process_oid="",
        completed=("active slice captured",),
        remaining=("resume current slice",),
        blockers=(),
        next_step="resume after owner review",
        evidence_refs=(),
    )
    return release, process, active, handoff


def test_g2_required_handoff_is_parent_bound_and_committed_parent_forbids_rollback(
    tmp_path: Path,
) -> None:
    _release, process, active, handoff = _g2_fixture(tmp_path)
    missing = plan_work_status_transition(
        process,
        active.work_id,
        expected_status="active",
        new_status="paused",
    )
    assert not missing.ready
    assert missing.handoff_plan.blockers == ("HANDOFF_REQUIRED_BY_ROUTE_POLICY",)

    plan = plan_work_status_transition(
        process,
        active.work_id,
        expected_status="active",
        new_status="paused",
        handoff=handoff,
    )
    authorization = _authorization(plan, "pause")
    assert plan.ready
    assert plan.handoff_plan.target_refs == (f"works/{active.work_id}/HANDOFF.yaml",)

    receipt = apply_work_status_transition(process, plan, authorization)

    assert receipt.decision == "PASS"
    assert receipt.handoff_decision == "PASS"
    assert plan.handoff_plan.target_ref in receipt.actual_mutation_refs
    assert inspect_work_status_transitions(process)["decision"] == "PASS"
    child = handoff_for_parent(
        process,
        authorization_id=authorization.authorization_id,
        parent_plan_digest=plan.parent_plan.plan_digest,
    )
    assert child is not None
    with pytest.raises(ValueError, match="committed parent"):
        recover_handoff(process, str(child["transaction_id"]))


def test_g2_handoff_hard_interrupt_is_inspectable_and_parent_first_recoverable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _release, process, active, handoff = _g2_fixture(tmp_path)
    plan = plan_work_status_transition(
        process,
        active.work_id,
        expected_status="active",
        new_status="paused",
        handoff=handoff,
    )
    authorization = _authorization(plan, "interrupt")
    lifecycle = __import__("meta_flow.work.lifecycle_transaction", fromlist=["_write_json_atomic"])
    original = lifecycle._write_json_atomic

    def interrupt_after_handoff_commit(path: Path, payload) -> None:
        original(path, payload)
        if (
            path.parent.name == "work-handoff"
            and payload.get("kind") == "HandoffTransitionTransactionV1"
            and payload.get("state") == "COMMITTED"
        ):
            raise KeyboardInterrupt

    monkeypatch.setattr(lifecycle, "_write_json_atomic", interrupt_after_handoff_commit)
    with pytest.raises(KeyboardInterrupt):
        apply_work_status_transition(process, plan, authorization)
    assert inspect_work_status_transitions(process)["decision"] == "BLOCKED"

    monkeypatch.setattr(lifecycle, "_write_json_atomic", original)
    recovered = recover_work_status_transition(process, authorization.authorization_id)

    assert recovered.decision == "RECOVERED"
    assert recovered.handoff_decision == "RECOVERED"
    assert inspect_work_status_transitions(process)["decision"] == "PASS"
    assert not (process / plan.handoff_plan.target_ref).exists()
