from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from meta_flow.work.budget import BudgetLimit
from meta_flow.work.model import build_work, load_work, write_work_create_only
from meta_flow.work.risk import RiskFacts, classify_work
from meta_flow.work.scope import WorkScope
from meta_flow.work.usage import (
    UsageEvent,
    UsageLedger,
    append_usage_event,
    build_cost_closure,
    collect_changed_path_inventory,
    load_usage,
    stage_usage,
    summarize_usage,
)
from meta_flow.work.usage_admission import (
    execute_admitted_operation,
    plan_operation_admission,
    plan_usage_admission,
)


def init_work(root: Path, *, budget: BudgetLimit | None = None) -> None:
    request_ref = "works/W-001/REQUEST.md"
    request = root / request_ref
    request.parent.mkdir(parents=True)
    request.write_text("confirmed\n", encoding="utf-8")
    work = build_work(
        work_id="W-001",
        project_id="demo",
        objective="x",
        request_ref=request_ref,
        scope=WorkScope(1, (request_ref,), ("README.md",), ("pytest-docs",)),
        classification=classify_work(
            RiskFacts(change_kind="documentation", touched_path_count=1)
        ),
        release_base_oid="a" * 40,
        process_base_oid="",
    )
    if budget is not None:
        work = replace(work, budget=budget)
    write_work_create_only(root, work)


def append_admitted(root: Path, event: UsageEvent):
    plan = plan_usage_admission(root, "W-001", event)
    return append_usage_event(
        root,
        "W-001",
        event,
        expected_admission_digest=plan.plan_digest,
    )


def test_usage_append_is_idempotent_and_stage_addressable(tmp_path: Path) -> None:
    init_work(tmp_path)
    event = UsageEvent(
        event_id="evt-001",
        stage="requirement",
        reads=0,
        writes=0,
        tokens=1_200,
    )

    first = append_admitted(tmp_path, event)
    second = append_admitted(tmp_path, event)
    ledger = load_usage(tmp_path, load_work(tmp_path, "W-001"))

    assert first.decision == "RECORDED"
    assert first.appended
    assert second.decision == "NO_CHANGE"
    assert not second.appended
    assert len(ledger.events) == 1
    assert stage_usage(ledger)["requirement"]["tokens"] == 1_200


def test_conflicting_duplicate_event_id_is_rejected(tmp_path: Path) -> None:
    init_work(tmp_path)
    append_admitted(
        tmp_path,
        UsageEvent(event_id="evt-001", stage="implementation", tokens=10),
    )

    with pytest.raises(ValueError, match="event_id conflict"):
        append_admitted(
            tmp_path,
            UsageEvent(event_id="evt-001", stage="implementation", tokens=11),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [("reads", 9), ("writes", 9), ("check_groups", 4), ("tokens", 32_001)],
)
def test_over_budget_plan_blocks_before_usage_ledger_mutation(
    tmp_path: Path, field: str, value: int
) -> None:
    init_work(tmp_path)
    kwargs = {"reads": 0, "writes": 0, "check_groups": 0, "tokens": 0}
    kwargs[field] = value

    event = UsageEvent(event_id="evt-over", stage="implementation", **kwargs)
    plan = plan_usage_admission(tmp_path, "W-001", event)

    with pytest.raises(ValueError, match="usage admission blocks append"):
        append_usage_event(
            tmp_path,
            "W-001",
            event,
            expected_admission_digest=plan.plan_digest,
        )

    assert plan.decision in {"PAUSE", "BLOCKED"}
    usage_path = tmp_path / "works" / "W-001" / "USAGE.json"
    assert not usage_path.exists()


def test_exact_budget_limit_is_blocked_before_record(tmp_path: Path) -> None:
    init_work(tmp_path)

    event = UsageEvent(
            event_id="evt-limit",
            stage="verification",
            reads=8,
            writes=8,
            check_groups=3,
            tokens=32_000,
        )
    plan = plan_usage_admission(tmp_path, "W-001", event)

    assert plan.decision == "BLOCKED"
    assert "USAGE_HARD_STOP_100_PERCENT" in plan.reason_codes
    assert not (tmp_path / "works/W-001/USAGE.json").exists()


def test_unavailable_usage_blocks_before_record(tmp_path: Path) -> None:
    init_work(tmp_path)

    event = UsageEvent(
            event_id="evt-unavailable",
            stage="implementation",
            reads=1,
            tokens=None,
            token_measurement_status="unavailable",
            unavailable_reason="platform did not report usage",
        )
    plan = plan_usage_admission(tmp_path, "W-001", event)

    assert plan.decision == "BLOCKED"
    assert plan.measurement_basis == "unavailable"
    assert "USAGE_TELEMETRY_UNAVAILABLE" in plan.reason_codes
    assert not (tmp_path / "works/W-001/USAGE.json").exists()


def test_measured_and_proxy_usage_remains_explicitly_proxy(tmp_path: Path) -> None:
    init_work(tmp_path)
    append_admitted(
        tmp_path,
        UsageEvent(event_id="evt-measured", stage="requirement", tokens=100),
    )
    append_admitted(
        tmp_path,
        UsageEvent(
            event_id="evt-proxy",
            stage="implementation",
            tokens=200,
            token_measurement_status="proxy",
            proxy_method="context-bytes-plus-output",
        ),
    )

    usage = summarize_usage(load_usage(tmp_path, load_work(tmp_path, "W-001")))

    assert usage.tokens == 300
    assert usage.token_measurement_status == "proxy"
    assert usage.proxy_method == "context-bytes-plus-output"


def test_invalid_proxy_and_unavailable_events_are_rejected() -> None:
    with pytest.raises(ValueError, match="proxy_method"):
        UsageEvent(
            event_id="evt-proxy",
            stage="implementation",
            tokens=1,
            token_measurement_status="proxy",
        )
    with pytest.raises(ValueError, match="tokens=None"):
        UsageEvent(
            event_id="evt-unavailable",
            stage="implementation",
            tokens=0,
            token_measurement_status="unavailable",
            unavailable_reason="missing",
        )


@pytest.mark.parametrize(
    ("reads", "decision", "reason"),
    [
        (23, "READY", ""),
        (24, "REVIEW", "USAGE_REVIEW_60_PERCENT"),
        (32, "PAUSE", "USAGE_RESERVE_BELOW_20_PERCENT"),
        (40, "BLOCKED", "USAGE_HARD_STOP_100_PERCENT"),
    ],
)
def test_online_stage_admission_freezes_60_80_100_thresholds(
    tmp_path: Path,
    reads: int,
    decision: str,
    reason: str,
) -> None:
    init_work(
        tmp_path,
        budget=BudgetLimit(reads=100, writes=100, check_groups=100, tokens=100_000),
    )

    plan = plan_usage_admission(
        tmp_path,
        "W-001",
        UsageEvent(
            event_id=f"evt-threshold-{reads}",
            stage="implementation",
            reads=reads,
        ),
    )

    assert plan.decision == decision
    assert plan.stage_utilization["reads"] == (reads * 100 + 39) // 40
    if reason:
        assert reason in plan.reason_codes


def test_admitted_operation_reserves_usage_before_executor_runs(tmp_path: Path) -> None:
    init_work(
        tmp_path,
        budget=BudgetLimit(reads=100, writes=100, check_groups=100, tokens=100_000),
    )
    event = UsageEvent(
        event_id="op-read-request",
        stage="requirements",
        reads=1,
        tokens=10,
    )
    permit = plan_operation_admission(
        tmp_path,
        "W-001",
        event,
        operation="read",
        requested_targets=("works/W-001/REQUEST.md",),
    )

    def executor() -> str:
        ledger = load_usage(tmp_path, load_work(tmp_path, "W-001"))
        assert [item.event_id for item in ledger.events] == [event.event_id]
        return "executed"

    receipt, result = execute_admitted_operation(tmp_path, permit, event, executor)

    assert permit.allowed
    assert receipt.decision == "PASS"
    assert receipt.usage_reserved is True
    assert result == "executed"


def test_usage_record_production_operation_is_single_use(tmp_path: Path) -> None:
    init_work(
        tmp_path,
        budget=BudgetLimit(reads=100, writes=100, check_groups=100, tokens=100_000),
    )
    event = UsageEvent(
        event_id="usage-record-once",
        stage="implementation",
        writes=1,
        tokens=10,
    )
    permit = plan_operation_admission(
        tmp_path,
        "W-001",
        event,
        operation="usage-record",
    )
    calls = 0

    def executor() -> str:
        nonlocal calls
        calls += 1
        return "first"

    first, first_result = execute_admitted_operation(tmp_path, permit, event, executor)
    duplicate = plan_operation_admission(
        tmp_path,
        "W-001",
        event,
        operation="usage-record",
    )
    second, second_result = execute_admitted_operation(
        tmp_path,
        duplicate,
        event,
        executor,
    )

    assert first.decision == "PASS"
    assert first_result == "first"
    assert second.decision == "NO_CHANGE"
    assert second_result is None
    assert calls == 1


def test_blocked_or_stale_operation_permit_never_calls_executor(tmp_path: Path) -> None:
    init_work(
        tmp_path,
        budget=BudgetLimit(reads=100, writes=100, check_groups=100, tokens=100_000),
    )
    calls = 0

    def executor() -> None:
        nonlocal calls
        calls += 1

    denied_event = UsageEvent(
        event_id="op-denied-write",
        stage="implementation",
        writes=1,
        tokens=10,
    )
    denied = plan_operation_admission(
        tmp_path,
        "W-001",
        denied_event,
        operation="write",
        requested_targets=("outside.txt",),
    )
    with pytest.raises(ValueError, match="blocks execution"):
        execute_admitted_operation(tmp_path, denied, denied_event, executor)
    assert calls == 0
    assert not (tmp_path / "works/W-001/USAGE.json").exists()

    allowed_event = UsageEvent(
        event_id="op-stale-read",
        stage="requirements",
        reads=1,
        tokens=10,
    )
    stale = plan_operation_admission(
        tmp_path,
        "W-001",
        allowed_event,
        operation="read",
        requested_targets=("works/W-001/REQUEST.md",),
    )
    append_admitted(
        tmp_path,
        UsageEvent(event_id="concurrent-usage", stage="requirements", tokens=1),
    )
    with pytest.raises(ValueError, match="permit drifted"):
        execute_admitted_operation(tmp_path, stale, allowed_event, executor)
    assert calls == 0


def test_governance_limits_are_admitted_before_real_operation(tmp_path: Path) -> None:
    init_work(tmp_path)
    first = UsageEvent(
        event_id="final-full-1",
        stage="verification",
        tokens=1,
        final_full_suites=1,
    )
    first_permit = plan_operation_admission(
        tmp_path,
        "W-001",
        first,
        operation="final-full-suite",
    )
    execute_admitted_operation(tmp_path, first_permit, first, lambda: "full-1")

    calls = 0

    def forbidden_second_full() -> None:
        nonlocal calls
        calls += 1

    second = UsageEvent(
        event_id="final-full-2",
        stage="verification",
        tokens=1,
        final_full_suites=1,
    )
    second_permit = plan_operation_admission(
        tmp_path,
        "W-001",
        second,
        operation="final-full-suite",
    )
    with pytest.raises(ValueError, match="blocks execution"):
        execute_admitted_operation(
            tmp_path,
            second_permit,
            second,
            forbidden_second_full,
        )

    assert second_permit.decision == "BLOCKED"
    assert (
        "USAGE_GOVERNANCE_LIMIT_EXCEEDED:final_full_suites"
        in plan_usage_admission(tmp_path, "W-001", second).reason_codes
    )
    assert calls == 0


def test_usage_single_writer_lock_blocks_concurrent_reservation(tmp_path: Path) -> None:
    init_work(tmp_path)
    event = UsageEvent(event_id="locked-event", stage="implementation", tokens=1)
    plan = plan_usage_admission(tmp_path, "W-001", event)
    lock = tmp_path / "works/W-001/.USAGE.json.writer.lock"
    lock.write_text("other-event\n", encoding="utf-8")

    with pytest.raises(ValueError, match="already held"):
        append_usage_event(
            tmp_path,
            "W-001",
            event,
            expected_admission_digest=plan.plan_digest,
        )

    assert lock.read_text(encoding="utf-8") == "other-event\n"
    assert not (tmp_path / "works/W-001/USAGE.json").exists()


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


def test_changed_path_inventory_separates_collapsed_ui_and_leaf_paths(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init", "-b", "main")
    for index in range(8):
        (tmp_path / f"tracked-{index}.txt").write_text("before\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(
        tmp_path,
        "-c",
        "user.name=Meta Flow Test",
        "-c",
        "user.email=meta-flow@example.invalid",
        "commit",
        "-m",
        "initial",
    )
    for index in range(8):
        (tmp_path / f"tracked-{index}.txt").write_text("after\n", encoding="utf-8")
    untracked: list[str] = []
    for index in range(23):
        directory = tmp_path / f"new-{index:02d}"
        directory.mkdir()
        names = ["one.txt", "two.txt"] if index < 8 else ["one.txt"]
        for name in names:
            path = directory / name
            path.write_text("new\n", encoding="utf-8")
            untracked.append(path.relative_to(tmp_path).as_posix())
    allowed = {
        *(f"tracked-{index}.txt" for index in range(8)),
        *untracked,
    }

    inventory = collect_changed_path_inventory(
        tmp_path,
        allowed_leaf_paths=allowed,
    )

    assert inventory.collapsed_status_entry_count == 31
    assert len(inventory.changed_leaf_paths) == 39
    assert len(inventory.tracked_modified_leaf_paths) == 8
    assert len(inventory.untracked_leaf_paths) == 31
    assert len(inventory.staged_leaf_paths) == 0
    assert len(inventory.unknown_leaf_paths) == 0
    payload = inventory.as_dict()
    assert payload["collapsed_status_entries_ui_only"] is True
    assert payload["machine_decision_path_field"] == "changed_leaf_paths"


def test_cost_closure_enforces_limits_and_preserves_cr057_baseline_limitation(
    tmp_path: Path,
) -> None:
    ledger = UsageLedger(
        work_id="GOV-004-FU-001",
        events=(
            UsageEvent(
                event_id="init",
                stage="init",
                tokens=100_000,
                token_measurement_status="proxy",
                proxy_method="context-estimate",
            ),
            UsageEvent(
                event_id="implementation",
                stage="implementation",
                tokens=200_000,
                token_measurement_status="proxy",
                proxy_method="context-estimate",
            ),
        ),
    )
    inventory = collect_changed_path_inventory(
        tmp_path,
        allowed_leaf_paths=(),
    ) if (tmp_path / ".git").exists() else None
    if inventory is None:
        _git(tmp_path, "init", "-b", "main")
        inventory = collect_changed_path_inventory(
            tmp_path,
            allowed_leaf_paths=(),
        )
    gate_events = [
        {
            "event_id": "cp3",
            "event_type": "human_gate_approval",
            "decision": "approve",
            "interaction_id": "merged-design",
        },
        {
            "event_id": "cp5",
            "event_type": "human_gate_approval",
            "decision": "approve",
            "interaction_id": "merged-design",
        },
        {
            "event_id": "scope",
            "event_type": "human_gate_approval",
            "decision": "approve",
        },
        {
            "event_id": "launch",
            "event_type": "human_gate_launched",
        },
    ]

    closure = build_cost_closure(
        ledger=ledger,
        required_stages=["init", "implementation"],
        gate_events=gate_events,
        changed_path_inventory=inventory,
    )

    assert closure["decision"] == "PASS_WITH_BASELINE_LIMITATION"
    assert closure["human_interactions"]["deduplicated_user_decisions"] == 2
    assert closure["human_interactions"]["reduction_ratio"] >= 0.8235
    assert closure["baseline"]["token_actual"] is None
    assert closure["baseline"]["token_actual_status"] == "unavailable"
    assert closure["baseline"]["authorized_proxy_ceiling"] == 1_752_000
    assert (
        closure["baseline"]["actual_to_actual_token_reduction_claim"]
        == "not_available"
    )
