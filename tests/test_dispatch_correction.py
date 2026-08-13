from __future__ import annotations

import json
from pathlib import Path

from meta_flow.state import event_ledger
from meta_flow.state.dispatch_correction import (
    apply_dispatch_corrections,
    build_dispatch_correction,
    plan_dispatch_corrections,
)


def _source(*, status: str = "interrupted", terminal_result: str = "") -> dict[str, object]:
    payload: dict[str, object] = {
        "event_id": "D-1-INTERRUPTED",
        "event_type": "dispatch",
        "dispatch_id": "D-1",
        "attempt_id": "A-1",
        "story_id": "STORY-1",
        "canonical_role": "meta-qa",
        "checkpoint": "CP7",
        "dispatch_mode": "subagent",
        "tool_name": "spawn_agent",
        "status": status,
        "completed_at": "2026-08-01T00:00:00Z",
    }
    if terminal_result:
        payload["terminal_result"] = terminal_result
    return payload


def _ledger(tmp_path: Path, events: list[dict[str, object]]) -> Path:
    path = tmp_path / "process/state/AGENT-DISPATCH-LEDGER.ndjson"
    path.parent.mkdir(parents=True)
    path.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )
    return path


def test_exact_digest_correction_covers_only_missing_terminal_result(tmp_path: Path) -> None:
    source = _source()
    correction = build_dispatch_correction(
        source,
        terminal_result="INTERRUPTED",
        reason="source status is explicitly interrupted",
        evidence_refs=("process/state/AGENT-DISPATCH-LEDGER.ndjson",),
        created_at="2026-08-02T00:00:00Z",
    )
    ledger = _ledger(tmp_path, [source, correction])

    errors, warnings = event_ledger.validate_event_ledger(ledger, ledger_type="dispatch")

    assert errors == []
    assert any(
        "missing terminal_result is covered by dispatch correction" in item for item in warnings
    )


def test_correction_digest_drift_fails_closed(tmp_path: Path) -> None:
    source = _source()
    correction = build_dispatch_correction(
        source,
        terminal_result="INTERRUPTED",
        reason="source status is explicitly interrupted",
        evidence_refs=("process/state/AGENT-DISPATCH-LEDGER.ndjson",),
        created_at="2026-08-02T00:00:00Z",
    )
    correction["original_event_digest"] = "0" * 64
    ledger = _ledger(tmp_path, [source, correction])

    errors, _warnings = event_ledger.validate_event_ledger(ledger, ledger_type="dispatch")

    assert "dispatch correction original_event_digest mismatch: D-1-INTERRUPTED" in errors
    assert "line 1: terminal typed dispatch attempt requires terminal_result" in errors


def test_duplicate_correction_head_fails_closed(tmp_path: Path) -> None:
    source = _source()
    first = build_dispatch_correction(
        source,
        terminal_result="INTERRUPTED",
        reason="first",
        evidence_refs=("process/state/AGENT-DISPATCH-LEDGER.ndjson",),
        created_at="2026-08-02T00:00:00Z",
    )
    second = {**first, "event_id": str(first["event_id"]) + "-FORK", "reason": "fork"}
    ledger = _ledger(tmp_path, [source, first, second])

    errors, _warnings = event_ledger.validate_event_ledger(ledger, ledger_type="dispatch")

    assert "dispatch correction fork: D-1-INTERRUPTED" in errors


def test_plan_apply_is_preimage_bound_and_idempotent(tmp_path: Path) -> None:
    source = _source()
    ledger = _ledger(tmp_path, [source])
    before = ledger.read_bytes()
    plan = plan_dispatch_corrections(
        tmp_path,
        source_event_ids=("D-1-INTERRUPTED",),
        terminal_result="INTERRUPTED",
        reason="source status is explicitly interrupted",
        evidence_refs=("process/state/AGENT-DISPATCH-LEDGER.ndjson",),
        process_oid="1" * 40,
        created_at="2026-08-02T00:00:00Z",
    )

    assert plan.decision == "READY"
    assert plan.mutation_count == 1
    assert ledger.read_bytes() == before

    receipt = apply_dispatch_corrections(
        tmp_path,
        plan=plan,
        expected_plan_digest=plan.plan_digest,
        current_process_oid=plan.process_oid,
    )

    assert receipt["decision"] == "APPLIED"
    assert receipt["mutation_count"] == 1
    errors, _warnings = event_ledger.validate_event_ledger(ledger, ledger_type="dispatch")
    assert errors == []

    replay = plan_dispatch_corrections(
        tmp_path,
        source_event_ids=("D-1-INTERRUPTED",),
        terminal_result="INTERRUPTED",
        reason="source status is explicitly interrupted",
        evidence_refs=("process/state/AGENT-DISPATCH-LEDGER.ndjson",),
        process_oid="1" * 40,
        created_at="2026-08-02T00:00:00Z",
    )
    assert replay.decision == "NO_CHANGE"
