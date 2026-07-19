from __future__ import annotations

from pathlib import Path

import pytest

from meta_flow.work.model import build_work, load_work, write_work_create_only
from meta_flow.work.risk import RiskFacts, classify_work
from meta_flow.work.scope import WorkScope
from meta_flow.work.usage import (
    UsageEvent,
    append_usage_event,
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
def test_budget_is_checked_before_usage_mutation(tmp_path: Path, field: str, value: int) -> None:
    init_work(tmp_path)
    kwargs = {"reads": 0, "writes": 0, "check_groups": 0, "tokens": 0}
    kwargs[field] = value

    result = append_usage_event(
        tmp_path,
        "W-001",
        UsageEvent(event_id="evt-over", stage="implementation", **kwargs),
    )

    assert result.decision == "BLOCKED"
    assert not result.appended
    usage_path = tmp_path / "works" / "W-001" / "USAGE.json"
    assert not usage_path.exists()


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

    assert result.decision == "RECORDED"
    assert result.budget.decision == "AT_LIMIT"


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
