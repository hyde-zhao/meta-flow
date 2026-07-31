from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from meta_flow.installation.authorization import (
    AUTHORIZATION_FIELDS,
    AUTHORIZATION_SOURCE,
    AuthorizationClaims,
    AuthorizationError,
    authorization_binding,
)
from meta_flow.installation.canonical import build_plan
from meta_flow.installation.contracts import InstallationContractError
from meta_flow.installation.engine import ExecutionOutcome, dispatch_authorized
from meta_flow.installation.planner import CHECKPOINT_SCALARS, CHECKPOINTS, compare_checkpoints


def _source_identity() -> dict[str, str]:
    return {
        "source": "meta-flow-delivery",
        "version": "0.4.0",
        "oid": "a" * 40,
        "delivery_tree_digest": "b" * 64,
        "rules_source_digest": "c" * 64,
        "inventory_digest": "d" * 64,
    }


def _unsigned_action(
    *,
    action_id: str,
    action_kind: str,
    component: str,
    ownership_kind: str,
    source_ref: str | None,
    target_ref: str,
    ordinal: int,
) -> dict[str, object]:
    return {
        "action_id": action_id,
        "action_kind": action_kind,
        "component": component,
        "ownership_kind": ownership_kind,
        "source_ref": source_ref,
        "target_ref": target_ref,
        "before_state": {"exists": False, "digest": None},
        "desired_state": {"exists": True, "digest": "f" * 64},
        "preconditions": [],
        "rollback_action": None,
        "ordinal": ordinal,
    }


def _plan() -> dict[str, object]:
    return build_plan(
        operation="assets.install",
        decision_ref="decisions/GOV-006-S04.json",
        request_intent="安装已审核组件",
        component="agents",
        scope="project",
        platform="codex",
        source_identity=_source_identity(),
        target_identity={"project_id": "demo", "target_digest": "e" * 64},
        base_facts={"risk": "architecture-major", "target_complete": True},
        actions=[
            _unsigned_action(
                action_id="A-001",
                action_kind="write_exact_file",
                component="agents",
                ownership_kind="exact_file",
                source_ref="delivery/agents/example.md",
                target_ref=".codex/agents/example.toml",
                ordinal=1,
            ),
            _unsigned_action(
                action_id="A-002",
                action_kind="write_manifest",
                component="manifest",
                ownership_kind="manifest",
                source_ref=None,
                target_ref=".meta-flow/INSTALL-MANIFEST.yaml",
                ordinal=2,
            ),
        ],
        rollback_plan={"strategy": "replan-required", "transaction_ref": "transactions/GOV-006-S04.json"},
    )


def _authorization(plan: dict[str, object], **updates: object) -> dict[str, object]:
    binding = authorization_binding(plan)
    values: dict[str, object] = {
        "schema_version": 1,
        "authorization_id": "auth-s04-001",
        "authorization_source": AUTHORIZATION_SOURCE,
        "authorization_kind": "installation-mutation",
        **binding,
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        "single_use": True,
    }
    values.update(updates)
    return {field: values[field] for field in AUTHORIZATION_FIELDS}


def _facts() -> dict[str, dict[str, str]]:
    return {
        checkpoint: {scalar: f"{checkpoint}-{scalar}" for scalar in CHECKPOINT_SCALARS}
        for checkpoint in CHECKPOINTS
    }


def test_authorization_schema_and_checkpoint_vector_are_exact() -> None:
    plan = _plan()
    authorization = _authorization(plan)
    facts = _facts()

    assert tuple(authorization) == AUTHORIZATION_FIELDS
    assert len(authorization) == 12
    comparisons = compare_checkpoints(facts, facts)
    assert len(comparisons) == 24
    assert all(comparison.matched for comparison in comparisons)


@pytest.mark.parametrize("checkpoint", CHECKPOINTS)
@pytest.mark.parametrize("scalar", CHECKPOINT_SCALARS)
def test_each_scalar_drift_blocks_executor(checkpoint: str, scalar: str) -> None:
    plan = _plan()
    expected = _facts()
    observed = _facts()
    observed[checkpoint][scalar] = "drift"
    calls = 0

    def executor(_context: object) -> ExecutionOutcome:
        nonlocal calls
        calls += 1
        return ExecutionOutcome(mutation_count=1, value="unexpected")

    if checkpoint in {"C1", "C2"}:
        with pytest.raises(InstallationContractError):
            dispatch_authorized(
                plan=plan,
                authorization=_authorization(plan),
                expected_checkpoints=expected,
                observed_checkpoints=observed,
                claims=AuthorizationClaims(),
                executor=executor,
            )
    elif checkpoint == "C3":
        receipt = dispatch_authorized(
            plan=plan,
            authorization=_authorization(plan),
            expected_checkpoints=expected,
            observed_checkpoints=observed,
            claims=AuthorizationClaims(),
            executor=executor,
        )
        assert receipt.terminal == "consumed_no_mutation"
        assert receipt.mutation_count == 0
    else:
        receipt = dispatch_authorized(
            plan=plan,
            authorization=_authorization(plan),
            expected_checkpoints=expected,
            observed_checkpoints=observed,
            claims=AuthorizationClaims(),
            executor=executor,
        )
        assert receipt.terminal == "rollback_pending"
    assert calls == 0 if checkpoint != "C4" else 1


def test_two_concurrent_claimants_have_exactly_one_success_and_replay_is_rejected() -> None:
    plan = _plan()
    authorization = _authorization(plan)
    claims = AuthorizationClaims()

    def claim() -> bool:
        try:
            claims.claim_once(authorization, plan=plan)
        except AuthorizationError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: claim(), range(2)))

    assert results.count(True) == 1
    assert results.count(False) == 1
    with pytest.raises(AuthorizationError, match="already consumed"):
        claims.claim_once(authorization, plan=plan)


def test_checkpoint_observer_refreshes_each_execution_boundary() -> None:
    plan = _plan()
    expected = _facts()
    observed = _facts()
    observation_count = 0

    def observer() -> dict[str, dict[str, str]]:
        nonlocal observation_count
        observation_count += 1
        return observed

    receipt = dispatch_authorized(
        plan=plan,
        authorization=_authorization(plan),
        expected_checkpoints=expected,
        observed_checkpoints=observer,
        claims=AuthorizationClaims(),
        executor=lambda _context: ExecutionOutcome(mutation_count=1, value="applied"),
    )

    assert receipt.terminal == "applied"
    assert receipt.mutation_count == 1
    assert observation_count == 3


def test_executor_reports_exact_mutation_count_instead_of_engine_guessing() -> None:
    plan = _plan()

    receipt = dispatch_authorized(
        plan=plan,
        authorization=_authorization(plan),
        expected_checkpoints=_facts(),
        observed_checkpoints=_facts(),
        claims=AuthorizationClaims(),
        executor=lambda _context: ExecutionOutcome(mutation_count=7, value={"actions": 7}),
    )

    assert receipt.terminal == "applied"
    assert receipt.mutation_count == 7
    assert receipt.outcome == {"actions": 7}


@pytest.mark.parametrize("field", ["source_digest", "target_digest"])
def test_source_or_target_binding_drift_fails_closed(field: str) -> None:
    plan = _plan()
    authorization = _authorization(plan, **{field: "0" * 64})
    calls = 0

    def executor(_context: object) -> None:
        nonlocal calls
        calls += 1

    with pytest.raises(AuthorizationError):
        dispatch_authorized(
            plan=plan,
            authorization=authorization,
            expected_checkpoints=_facts(),
            observed_checkpoints=_facts(),
            claims=AuthorizationClaims(),
            executor=executor,
        )
    assert calls == 0


def test_claim_then_pre_mutation_failure_emits_terminal_receipt_and_never_retries() -> None:
    plan = _plan()
    expected = _facts()
    observed = _facts()
    observed["C3"]["facts_digest"] = "drift"
    journal_events: list[tuple[str, str, dict[str, object]]] = []

    def journal(context: object, state: str, payload: dict[str, object]) -> None:
        journal_events.append((context.authorization_id, state, payload))  # type: ignore[union-attr]

    receipt = dispatch_authorized(
        plan=plan,
        authorization=_authorization(plan),
        expected_checkpoints=expected,
        observed_checkpoints=observed,
        claims=AuthorizationClaims(),
        executor=lambda _context: pytest.fail("executor must not be called"),
        journal=journal,
    )

    assert receipt.terminal == "consumed_no_mutation"
    assert receipt.mutation_count == 0
    assert receipt.retry_count == 0
    assert journal_events[-1][2]["terminal"] == "consumed_no_mutation"
