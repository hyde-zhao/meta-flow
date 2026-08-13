from __future__ import annotations

import json
from pathlib import Path

from meta_flow.checks import cp_result
from meta_flow.state.checkpoint_successor import (
    apply_checkpoint_successor,
    inspect_checkpoint_successor,
    plan_checkpoint_successor,
    recover_checkpoint_successor,
)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _legacy_result() -> dict[str, object]:
    return {
        "schema_version": 1,
        "checkpoint": "CP5",
        "cr_id": "CR-123",
        "decision": "PASS",
        "checks": [
            {
                "id": "CP5-01",
                "name": "design evidence",
                "status": "PASS",
                "summary": "verified",
            }
        ],
        "blockers": [],
        "waivers": [],
    }


def _prepare(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path
    source = root / "process" / "checks" / "CP5-CR-123-legacy.result.json"
    ledger = root / "process" / "state" / "CHECKPOINT-LEDGER.ndjson"
    target = root / "process" / "checks" / "CP5-CR-123-successor.result.json"
    _write_json(source, _legacy_result())
    ledger.parent.mkdir(parents=True)
    ledger.write_text(
        json.dumps(
            {
                "event_id": "CP5-CR-123-LEGACY",
                "event_type": "checkpoint_result",
                "checkpoint": "CP5",
                "cr_id": "CR-123",
                "decision": "PASS",
                "result_ref": "process/checks/CP5-CR-123-legacy.result.json",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return root, source, target


def test_plan_is_zero_write_and_builds_canonical_successor(tmp_path: Path) -> None:
    root, source, target = _prepare(tmp_path)
    source_before = source.read_bytes()
    ledger_before = (root / "process/state/CHECKPOINT-LEDGER.ndjson").read_bytes()

    plan = plan_checkpoint_successor(
        root,
        source_ref="process/checks/CP5-CR-123-legacy.result.json",
        target_ref="process/checks/CP5-CR-123-successor.result.json",
        evidence_refs=("process/checks/evidence.json",),
        reason="migrate current legacy checkpoint result",
        process_oid="1" * 40,
    )

    assert plan.decision == "READY"
    assert plan.mutation_count == 2
    assert source.read_bytes() == source_before
    assert not target.exists()
    assert (root / "process/state/CHECKPOINT-LEDGER.ndjson").read_bytes() == ledger_before
    assert plan.successor["artifact_kind"] == "checkpoint_result"
    assert plan.successor["supersedes_ref"] == "process/checks/CP5-CR-123-legacy.result.json"
    assert plan.event["supersedes_event_id"] == "CP5-CR-123-LEGACY"
    assert plan.successor["items"][0]["status"] == "PASS"


def test_apply_writes_result_and_ledger_as_one_preimage_checked_operation(
    tmp_path: Path,
) -> None:
    root, source, target = _prepare(tmp_path)
    source_before = source.read_bytes()
    plan = plan_checkpoint_successor(
        root,
        source_ref="process/checks/CP5-CR-123-legacy.result.json",
        target_ref="process/checks/CP5-CR-123-successor.result.json",
        evidence_refs=("process/checks/evidence.json",),
        reason="migrate current legacy checkpoint result",
        process_oid="2" * 40,
    )

    receipt = apply_checkpoint_successor(
        root,
        plan=plan,
        expected_plan_digest=plan.plan_digest,
        current_process_oid=plan.process_oid,
    )

    assert receipt["decision"] == "APPLIED"
    assert receipt["mutation_count"] == 2
    assert source.read_bytes() == source_before
    errors, _warnings = cp_result.validate_cp_result(target, project_root=root)
    assert errors == []
    ledger = (root / "process/state/CHECKPOINT-LEDGER.ndjson").read_text(encoding="utf-8")
    assert plan.event["event_id"] in ledger

    replay = plan_checkpoint_successor(
        root,
        source_ref="process/checks/CP5-CR-123-legacy.result.json",
        target_ref="process/checks/CP5-CR-123-successor.result.json",
        evidence_refs=("process/checks/evidence.json",),
        reason="migrate current legacy checkpoint result",
        process_oid="2" * 40,
    )
    assert replay.decision == "NO_CHANGE"
    assert replay.blockers == ()
    assert replay.mutation_count == 0


def test_apply_rejects_source_or_ledger_drift_without_mutation(tmp_path: Path) -> None:
    root, _source, target = _prepare(tmp_path)
    plan = plan_checkpoint_successor(
        root,
        source_ref="process/checks/CP5-CR-123-legacy.result.json",
        target_ref="process/checks/CP5-CR-123-successor.result.json",
        evidence_refs=("process/checks/evidence.json",),
        reason="migrate current legacy checkpoint result",
        process_oid="3" * 40,
    )
    ledger = root / "process/state/CHECKPOINT-LEDGER.ndjson"
    ledger.write_text(ledger.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")

    receipt = apply_checkpoint_successor(
        root,
        plan=plan,
        expected_plan_digest=plan.plan_digest,
        current_process_oid=plan.process_oid,
    )

    assert receipt["decision"] == "BLOCKED"
    assert receipt["blockers"] == ["SOURCE_OR_LEDGER_PREIMAGE_DRIFT"]
    assert not target.exists()


def test_incomplete_transaction_is_inspectable_and_recoverable(tmp_path: Path) -> None:
    root, _source, target = _prepare(tmp_path)
    ledger = root / "process/state/CHECKPOINT-LEDGER.ndjson"
    ledger_before = ledger.read_bytes()
    target.write_text("partial\n", encoding="utf-8")
    manifest = root / ".meta-flow-runtime/checkpoint-successor/transaction.json"
    manifest.parent.mkdir(parents=True)
    import base64

    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "CheckpointSuccessorTransactionV1",
                "state": "PARTIAL",
                "plan_digest": "a" * 64,
                "target_ref": "process/checks/CP5-CR-123-successor.result.json",
                "ledger_ref": "process/state/CHECKPOINT-LEDGER.ndjson",
                "target_before": None,
                "ledger_before": base64.b64encode(ledger_before).decode("ascii"),
                "target_after_digest": "b" * 64,
                "ledger_after_digest": "c" * 64,
                "attempted_refs": ["process/checks/CP5-CR-123-successor.result.json"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert inspect_checkpoint_successor(root)["decision"] == "BLOCKED"
    receipt = recover_checkpoint_successor(root)

    assert receipt["decision"] == "RECOVERED"
    assert not target.exists()
    assert ledger.read_bytes() == ledger_before
    assert inspect_checkpoint_successor(root)["decision"] == "PASS"
