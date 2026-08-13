from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from meta_flow.project.onboarding_contract import canonical_digest
from meta_flow.state import event_ledger
from meta_flow.state.dispatch_closure import (
    apply_dispatch_closures,
    build_dispatch_closure,
    plan_dispatch_closures,
)
from meta_flow.workflow.terminal_lineage import (
    discover_terminal_lineage,
    load_terminal_lineage_dispositions,
    project_terminal_lineage,
)


def _source() -> dict[str, object]:
    return {
        "event_id": "D-1-RUNNING",
        "event_type": "dispatch",
        "dispatch_id": "D-1",
        "attempt_id": "ATTEMPT-1",
        "story_id": "STORY-1",
        "canonical_role": "meta-dev",
        "checkpoint": "CP6",
        "dispatch_mode": "subagent",
        "tool_name": "spawn_agent",
        "dispatch_trigger": "implementation",
        "agent_id": "/root/worker",
        "spawned_at": "2026-08-01T00:00:00Z",
        "status": "running",
    }


def _fixture(tmp_path: Path) -> tuple[Path, dict[str, object], dict[str, object]]:
    process_root = tmp_path / "process"
    ledger = process_root / "state/AGENT-DISPATCH-LEDGER.ndjson"
    ledger.parent.mkdir(parents=True)
    source = _source()
    ledger.write_text(json.dumps(source, sort_keys=True) + "\n", encoding="utf-8")
    evidence = process_root / "changes/summaries/CR-1.summary.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text('{"decision":"PASS"}\n', encoding="utf-8")
    evidence_ref = "process/changes/summaries/CR-1.summary.json"
    disposition: dict[str, object] = {
        "key": "dispatch:D-1",
        "source_digest": canonical_digest(source),
        "terminal_status": "superseded",
        "reason": "historical running attempt is superseded by closed lineage",
        "evidence_refs": [evidence_ref],
        "evidence_digests": {evidence_ref: sha256(evidence.read_bytes()).hexdigest()},
    }
    policy = process_root / "policies/TERMINAL-LINEAGE-DISPOSITIONS.json"
    policy.parent.mkdir(parents=True)
    policy.write_text(
        json.dumps(
            {"schema_version": 1, "dispositions": [disposition]},
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return ledger, source, disposition


def test_plan_apply_closes_exact_nonterminal_attempt_without_rewriting_source(
    tmp_path: Path,
) -> None:
    ledger, source, _disposition = _fixture(tmp_path)
    source_bytes = ledger.read_bytes()
    plan = plan_dispatch_closures(
        tmp_path,
        dispatch_ids=("D-1",),
        process_oid="1" * 40,
        created_at="2026-08-02T00:00:00Z",
    )

    assert plan.decision == "READY"
    assert plan.mutation_count == 1
    assert ledger.read_bytes() == source_bytes

    receipt = apply_dispatch_closures(
        tmp_path,
        plan=plan,
        expected_plan_digest=plan.plan_digest,
        current_process_oid=plan.process_oid,
    )

    assert receipt["decision"] == "APPLIED"
    assert receipt["mutation_count"] == 1
    assert ledger.read_bytes().startswith(source_bytes)
    events, load_errors = event_ledger.load_events(ledger)
    assert load_errors == []
    assert events[0] == {**source, "_line_no": 1}
    assert events[1]["event_type"] == "dispatch_attempt_closure"
    assert events[1]["terminal_result"] == "SUPERSEDED"
    errors, _warnings = event_ledger.validate_event_ledger(ledger, ledger_type="dispatch")
    assert errors == []

    replay = plan_dispatch_closures(
        tmp_path,
        dispatch_ids=("D-1",),
        process_oid="1" * 40,
        created_at="2026-08-02T00:00:00Z",
    )
    assert replay.decision == "NO_CHANGE"


def test_closure_requires_exact_disposition_and_evidence_digest(tmp_path: Path) -> None:
    _ledger, _source_event, _disposition = _fixture(tmp_path)
    evidence = tmp_path / "process/changes/summaries/CR-1.summary.json"
    evidence.write_text('{"decision":"DRIFT"}\n', encoding="utf-8")

    plan = plan_dispatch_closures(
        tmp_path,
        dispatch_ids=("D-1",),
        process_oid="1" * 40,
        created_at="2026-08-02T00:00:00Z",
    )

    assert plan.decision == "BLOCKED"
    assert any("evidence drift" in item for item in plan.blockers)
    assert plan.mutation_count == 0


def test_closure_apply_rejects_ledger_preimage_drift(tmp_path: Path) -> None:
    ledger, _source_event, _disposition = _fixture(tmp_path)
    plan = plan_dispatch_closures(
        tmp_path,
        dispatch_ids=("D-1",),
        process_oid="1" * 40,
        created_at="2026-08-02T00:00:00Z",
    )
    ledger.write_text(ledger.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    receipt = apply_dispatch_closures(
        tmp_path,
        plan=plan,
        expected_plan_digest=plan.plan_digest,
        current_process_oid=plan.process_oid,
    )

    assert receipt == {
        "decision": "BLOCKED",
        "blockers": ["LEDGER_PREIMAGE_DRIFT"],
        "mutation_count": 0,
    }


def test_terminal_lineage_accepts_native_successor_of_disposed_source(tmp_path: Path) -> None:
    ledger, source, disposition = _fixture(tmp_path)
    closure = build_dispatch_closure(
        source,
        disposition=disposition,
        created_at="2026-08-02T00:00:00Z",
    )
    ledger.write_text(
        ledger.read_text(encoding="utf-8") + json.dumps(closure, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    records, _discovery_errors = discover_terminal_lineage(tmp_path / "process")
    dispatch_records = [record for record in records if record.kind == "dispatch"]
    dispositions, disposition_errors = load_terminal_lineage_dispositions(tmp_path / "process")

    report = project_terminal_lineage(dispatch_records, dispositions=dispositions)

    assert disposition_errors == []
    assert report["decision"] == "PASS"
    assert report["findings"] == []
    assert report["current"][0]["event_id"] == closure["event_id"]
    assert report["current"][0]["disposition_applied"] is True


def test_dispatch_correction_is_not_a_new_terminal_lineage_generation(
    tmp_path: Path,
) -> None:
    ledger, source, _disposition = _fixture(tmp_path)
    terminal = {**source, "status": "interrupted", "terminal_result": "INTERRUPTED"}
    correction = {
        "event_id": "DISPATCH-CORRECTION-X",
        "event_type": "dispatch_correction",
        "dispatch_id": "D-1",
        "attempt_id": "ATTEMPT-1",
        "status": "",
    }
    ledger.write_text(
        json.dumps(terminal, sort_keys=True) + "\n" + json.dumps(correction, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    records, _errors = discover_terminal_lineage(tmp_path / "process")
    dispatch_records = [record for record in records if record.kind == "dispatch"]

    assert len(dispatch_records) == 1
    assert dispatch_records[0].event_id == "D-1-RUNNING"
    assert dispatch_records[0].terminal is True
