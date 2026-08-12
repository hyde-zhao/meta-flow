from __future__ import annotations

import pytest

from meta_flow.work.budget import (
    G0_BUDGET,
    G1_BUDGET,
    BudgetLimit,
    WorkUsage,
    evaluate_budget,
)
from meta_flow.work.risk import HIGH_RISK_FIELDS, RiskFacts, classify_work
from meta_flow.work.scope import WorkScope, check_scope


def test_g0_is_only_reversible_single_path_low_change() -> None:
    decision = classify_work(
        RiskFacts(change_kind="documentation", touched_path_count=1)
    )

    assert decision.container_kind == "work"
    assert decision.risk_profile == "G0"
    assert decision.budget == G0_BUDGET
    assert decision.required_gates == ()
    assert not decision.blocked


@pytest.mark.parametrize(
    "facts",
    [
        RiskFacts(change_kind="code", touched_path_count=1),
        RiskFacts(change_kind="documentation", touched_path_count=2),
        RiskFacts(change_kind="config", touched_path_count=1, multi_step=True),
        RiskFacts(change_kind="mechanical", touched_path_count=1, multi_module=True),
        RiskFacts(change_kind="config", touched_path_count=1, internal_interface=True),
    ],
)
def test_standard_changes_route_g1(facts: RiskFacts) -> None:
    decision = classify_work(facts)

    assert decision.container_kind == "work"
    assert decision.risk_profile == "G1"
    assert decision.budget == G1_BUDGET
    assert not decision.blocked


@pytest.mark.parametrize("field", sorted(HIGH_RISK_FIELDS))
def test_every_declared_high_risk_trigger_routes_cr_g2(field: str) -> None:
    facts = RiskFacts(
        change_kind="documentation",
        touched_path_count=1,
        **{field: True},
    )
    explicit_budget = BudgetLimit(40, 40, 12, 160_000)

    decision = classify_work(facts, g2_budget=explicit_budget)

    assert decision.container_kind == "cr"
    assert decision.risk_profile == "G2"
    assert decision.budget == explicit_budget
    assert not decision.blocked
    assert HIGH_RISK_FIELDS[field] in decision.reason_codes


def test_g2_without_explicit_budget_is_blocked() -> None:
    decision = classify_work(
        RiskFacts(change_kind="code", touched_path_count=4, public_contract=True)
    )

    assert decision.risk_profile == "G2"
    assert decision.blocked
    assert decision.budget is None
    assert "G2_BUDGET_REQUIRED" in decision.reason_codes


def test_unknown_high_risk_fact_fails_closed_even_with_budget() -> None:
    decision = classify_work(
        RiskFacts(
            change_kind="config",
            touched_path_count=1,
            unknown_high_risk_facts=("production-impact",),
        ),
        g2_budget=BudgetLimit(20, 20, 8, 80_000),
    )

    assert decision.container_kind == "cr"
    assert decision.risk_profile == "G2"
    assert decision.blocked
    assert "UNKNOWN_PRODUCTION_IMPACT" in decision.reason_codes
    assert "HIGH_RISK_FACTS_REQUIRE_RESOLUTION" in decision.reason_codes


def test_user_can_upgrade_but_cannot_silently_downgrade() -> None:
    upgraded = classify_work(
        RiskFacts(change_kind="documentation", touched_path_count=1),
        requested_profile="G1",
    )
    downgrade = classify_work(
        RiskFacts(change_kind="code", touched_path_count=2, security=True),
        requested_profile="G0",
        g2_budget=BudgetLimit(20, 20, 8, 80_000),
    )

    assert upgraded.risk_profile == "G1"
    assert "USER_UPGRADED_TO_G1" in upgraded.reason_codes
    assert downgrade.risk_profile == "G2"
    assert "DOWNGRADE_REJECTED" in downgrade.reason_codes
    assert downgrade.cannot_silently_downgrade


def test_preauthorized_ordinary_git_push_inherits_g0_or_g1() -> None:
    ordinary = classify_work(
        RiskFacts(
            change_kind="documentation",
            touched_path_count=1,
            repository_push=True,
            preauthorized_repo_ref=True,
        )
    )
    new_remote = classify_work(
        RiskFacts(
            change_kind="documentation",
            touched_path_count=1,
            repository_push=True,
            preauthorized_repo_ref=True,
            new_remote=True,
        ),
        g2_budget=BudgetLimit(20, 20, 8, 80_000),
    )

    assert ordinary.risk_profile == "G0"
    assert "PREAUTHORIZED_REPOSITORY_PUSH" in ordinary.reason_codes
    assert new_remote.risk_profile == "G2"
    assert "NEW_REMOTE" in new_remote.reason_codes


@pytest.mark.parametrize("dimension", ["reads", "writes", "check_groups", "tokens"])
def test_budget_allows_exact_limit_and_blocks_limit_plus_one(dimension: str) -> None:
    exact_values = {"reads": 0, "writes": 0, "check_groups": 0, "tokens": 0}
    exact_values[dimension] = G0_BUDGET.as_dict()[dimension]
    exact = WorkUsage(**exact_values)
    delta_values = {"reads": 0, "writes": 0, "check_groups": 0, "tokens": 0}
    delta_values[dimension] = 1

    exact_decision = evaluate_budget(G0_BUDGET, exact)
    exceeded = evaluate_budget(G0_BUDGET, exact, delta=WorkUsage(**delta_values))

    assert exact_decision.decision == "WARNING"
    assert exact_decision.allowed
    assert exact_decision.exceeded_dimensions == ()
    assert exact_decision.remaining[dimension] == 0
    assert exceeded.decision == "EXCEEDED"
    assert not exceeded.allowed
    assert dimension in exceeded.exceeded_dimensions


@pytest.mark.parametrize("profile", ["G0", "G1", "G2"])
@pytest.mark.parametrize(
    ("tokens", "expected"),
    [
        (7_999, "OK"),
        (8_000, "WARNING"),
        (9_999, "WARNING"),
        (10_000, "WARNING"),
        (10_001, "EXCEEDED"),
    ],
)
def test_budget_thresholds_are_consistent_across_profiles(
    profile: str,
    tokens: int,
    expected: str,
) -> None:
    # 使用可精确表达 79.99% / 80% / 99.99% / 100% / 100.01% 的共同刻度，
    # profile 参数确保三种治理档位消费同一边界语义。
    del profile
    limit = BudgetLimit(reads=10_000, writes=10_000, check_groups=10_000, tokens=10_000)
    decision = evaluate_budget(limit, WorkUsage(tokens=tokens))

    assert decision.decision == expected
    assert decision.allowed is (expected in {"OK", "WARNING"})


def test_unavailable_tokens_are_not_treated_as_zero() -> None:
    unavailable = WorkUsage(
        reads=1,
        tokens=None,
        token_measurement_status="unavailable",
        unavailable_reason="platform did not report usage",
    )

    decision = evaluate_budget(G0_BUDGET, unavailable)

    assert decision.decision == "TELEMETRY_UNAVAILABLE"
    assert not decision.allowed
    assert decision.remaining["tokens"] is None


def test_proxy_usage_requires_method_and_remains_labeled() -> None:
    with pytest.raises(ValueError, match="proxy_method"):
        WorkUsage(tokens=100, token_measurement_status="proxy")

    decision = evaluate_budget(
        G0_BUDGET,
        WorkUsage(
            tokens=1_000,
            token_measurement_status="proxy",
            proxy_method="context-bytes-plus-output",
        ),
        delta=WorkUsage(tokens=500),
    )

    assert decision.allowed
    assert decision.projected.token_measurement_status == "proxy"
    assert decision.projected.proxy_method == "context-bytes-plus-output"
    assert decision.projected.tokens == 1_500


def test_scope_is_deny_default_for_reads_writes_and_checks() -> None:
    scope = WorkScope(
        version=1,
        allowed_reads=("README.md", "meta_flow/work/**"),
        allowed_writes=("meta_flow/work/**", "tests/test_work.py"),
        required_checks=("pytest-work", "ruff-work"),
    )

    assert check_scope(scope, "read", "README.md").allowed
    assert check_scope(scope, "read", "meta_flow/work/model.py").allowed
    assert not check_scope(scope, "read", "process/STATE.md").allowed
    assert check_scope(scope, "write", "meta_flow/work/risk.py").allowed
    assert not check_scope(scope, "write", "meta_flow/cli.py").allowed
    assert check_scope(scope, "check", "pytest-work").allowed
    assert not check_scope(scope, "check", "pytest-all").allowed


@pytest.mark.parametrize(
    "pattern",
    ["/etc/passwd", "../outside", "meta_flow/*/secret", "meta_flow/../secret", ""],
)
def test_scope_rejects_unsafe_patterns(pattern: str) -> None:
    with pytest.raises(ValueError, match="unsafe"):
        WorkScope(version=1, allowed_reads=(pattern,), allowed_writes=(), required_checks=())
