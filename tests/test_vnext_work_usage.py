from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

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


def init_work(root: Path) -> None:
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
    write_work_create_only(root, work)


def test_usage_append_is_idempotent_and_stage_addressable(tmp_path: Path) -> None:
    init_work(tmp_path)
    event = UsageEvent(
        event_id="evt-001",
        stage="requirement",
        reads=2,
        writes=1,
        tokens=1_200,
    )

    first = append_usage_event(tmp_path, "W-001", event)
    second = append_usage_event(tmp_path, "W-001", event)
    ledger = load_usage(tmp_path, load_work(tmp_path, "W-001"))

    assert first.decision == "RECORDED"
    assert first.appended
    assert second.decision == "NO_CHANGE"
    assert not second.appended
    assert len(ledger.events) == 1
    assert stage_usage(ledger)["requirement"]["tokens"] == 1_200


def test_conflicting_duplicate_event_id_is_rejected(tmp_path: Path) -> None:
    init_work(tmp_path)
    append_usage_event(
        tmp_path,
        "W-001",
        UsageEvent(event_id="evt-001", stage="implementation", tokens=10),
    )

    with pytest.raises(ValueError, match="event_id conflict"):
        append_usage_event(
            tmp_path,
            "W-001",
            UsageEvent(event_id="evt-001", stage="implementation", tokens=11),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [("reads", 9), ("writes", 9), ("check_groups", 4), ("tokens", 32_001)],
)
def test_over_budget_fact_is_recorded_and_blocks_followup_mutation(
    tmp_path: Path, field: str, value: int
) -> None:
    init_work(tmp_path)
    kwargs = {"reads": 0, "writes": 0, "check_groups": 0, "tokens": 0}
    kwargs[field] = value

    result = append_usage_event(
        tmp_path,
        "W-001",
        UsageEvent(event_id="evt-over", stage="implementation", **kwargs),
    )

    assert result.decision == "RECORDED_AND_BLOCKED"
    assert result.appended
    usage_path = tmp_path / "works" / "W-001" / "USAGE.json"
    assert usage_path.exists()
    ledger = load_usage(tmp_path, load_work(tmp_path, "W-001"))
    assert ledger.events[0].event_id == "evt-over"
    assert result.budget.decision == "EXCEEDED"


def test_exact_budget_limit_is_recorded(tmp_path: Path) -> None:
    init_work(tmp_path)

    result = append_usage_event(
        tmp_path,
        "W-001",
        UsageEvent(
            event_id="evt-limit",
            stage="verification",
            reads=8,
            writes=8,
            check_groups=3,
            tokens=32_000,
        ),
    )

    assert result.decision == "RECORDED_AND_BLOCKED"
    assert result.budget.decision == "EXCEEDED"


def test_unavailable_usage_is_recorded_but_blocks_further_execution(tmp_path: Path) -> None:
    init_work(tmp_path)

    result = append_usage_event(
        tmp_path,
        "W-001",
        UsageEvent(
            event_id="evt-unavailable",
            stage="implementation",
            reads=1,
            tokens=None,
            token_measurement_status="unavailable",
            unavailable_reason="platform did not report usage",
        ),
    )

    assert result.decision == "RECORDED_AND_BLOCKED"
    assert result.appended
    assert result.budget.decision == "TELEMETRY_UNAVAILABLE"


def test_measured_and_proxy_usage_remains_explicitly_proxy(tmp_path: Path) -> None:
    init_work(tmp_path)
    append_usage_event(
        tmp_path,
        "W-001",
        UsageEvent(event_id="evt-measured", stage="requirement", tokens=100),
    )
    append_usage_event(
        tmp_path,
        "W-001",
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
