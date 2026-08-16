from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from meta_flow.state import event_ledger
from meta_flow.state.dispatch_correction import (
    CORRECTION_TRANSACTION_LEDGER_REF,
    CorrectionSnapshotV1,
    CorrectionTransactionSnapshotV1,
    apply_correction_transaction,
    apply_dispatch_corrections,
    apply_typed_corrections,
    build_dispatch_correction,
    plan_correction_transaction,
    plan_dispatch_corrections,
    plan_typed_corrections,
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


class _AtomicFixture:
    _STAGES = ("serialize", "resolve-completion", "verify-preimage", "append", "build-index", "cutover", "publish-report")

    def __init__(self, *, fail_stage: str = "") -> None:
        self.fail_stage = fail_stage
        self.events: tuple[object, ...] = ()
        self.authority: dict[str, object] = {"head": "old"}

    def commit(self, events: tuple[object, ...], authority: dict[str, object]) -> None:
        for stage in self._STAGES:
            if self.fail_stage == stage:
                raise RuntimeError(f"fault injected at {stage}")
        self.events = events
        self.authority = authority


def _typed_snapshot() -> CorrectionSnapshotV1:
    return CorrectionSnapshotV1(
        release_oid="a" * 40,
        process_oid="b" * 40,
        source_preimages=(("process/state/GATE-LEDGER.ndjson", "c" * 64),),
        authority_preimage="d" * 64,
    )


def _candidate() -> dict[str, object]:
    return {"event_id": "CANDIDATE-001", "event_type": "compensates", "value": "fixture"}


def test_typed_planner_requires_independent_authorization_and_writes_nothing() -> None:
    plan = plan_typed_corrections(_typed_snapshot(), completion_digest="e" * 64, candidate_events=(_candidate(),), lineage_digest="1" * 64, head_set_digest="2" * 64)
    assert plan.decision == "BLOCKED"
    assert plan.mutation_count == 0
    assert plan.authorization_ref == ""
    assert "TYPED_AUTHORIZATION_REQUIRED" in plan.blockers
    duplicate_ids = plan_typed_corrections(
        _typed_snapshot(),
        completion_digest="e" * 64,
        authorization_ref="process/authorizations/CR-071-S00.json",
        candidate_events=(_candidate(), {**_candidate(), "value": "different"}),
        lineage_digest="1" * 64,
        head_set_digest="2" * 64,
    )
    assert "DUPLICATE_CANDIDATE_EVENT" in duplicate_ids.blockers


def test_typed_apply_is_fresh_guarded_atomic_and_fixture_replay_safe() -> None:
    snapshot = _typed_snapshot()
    plan = plan_typed_corrections(
        snapshot,
        completion_digest="e" * 64,
        authorization_ref="process/authorizations/CR-071-S00.json",
        candidate_events=(_candidate(),),
        previous_head_digests=(("SOURCE-001", "3" * 64),),
        lineage_digest="1" * 64,
        head_set_digest="2" * 64,
    )
    adapter = _AtomicFixture()
    drift = apply_typed_corrections(
        plan,
        fresh_snapshot=CorrectionSnapshotV1(**{**snapshot.__dict__, "process_oid": "f" * 40}),
        adapter=adapter,
        events=(_candidate(),),
        authority={"head": "new"},
        lineage_digest="1" * 64,
        head_set_digest="2" * 64,
    )
    assert drift["decision"] == "BLOCKED"
    assert adapter.authority == {"head": "old"}
    for stage in _AtomicFixture._STAGES:
        failed_adapter = _AtomicFixture(fail_stage=stage)
        failed = apply_typed_corrections(plan, fresh_snapshot=snapshot, adapter=failed_adapter, events=(_candidate(),), authority={"head": "new"}, lineage_digest="1" * 64, head_set_digest="2" * 64)
        assert failed == {"decision": "BLOCKED", "blockers": ["ATOMIC_CUTOVER_FAILED"], "mutation_count": 0}
        assert failed_adapter.events == ()
        assert failed_adapter.authority == {"head": "old"}
    drifted_candidate = {**_candidate(), "value": "drift"}
    candidate_drift = apply_typed_corrections(plan, fresh_snapshot=snapshot, adapter=adapter, events=(drifted_candidate,), authority={"head": "new"}, lineage_digest="1" * 64, head_set_digest="2" * 64)
    assert candidate_drift == {"decision": "BLOCKED", "blockers": ["CANDIDATE_EVENT_DRIFT"], "mutation_count": 0}
    receipt = apply_typed_corrections(plan, fresh_snapshot=snapshot, adapter=adapter, events=(_candidate(),), authority={"head": "new"}, lineage_digest="1" * 64, head_set_digest="2" * 64)
    assert receipt == {"decision": "APPLIED", "atomic": True, "lineage_digest": "1" * 64, "head_set_digest": "2" * 64, "plan_digest": plan.plan_digest, "completion_digest": plan.completion_digest, "candidate_event_digests": list(plan.candidate_event_digests), "accepted_event_digest_set": plan.accepted_event_digest_set, "previous_head_digests": list(plan.previous_head_digests), "mutation_count": 0}


def _transaction_baseline() -> tuple[dict[str, object], ...]:
    return (
        {
            "finding_id": "CR071-LEDGER-RAW-001",
            "source_ledger_ref": "process/state/GATE-LEDGER.ndjson",
            "source_line": 175,
            "source_event_id": "GATE-CR071-CP2-CHANGES-REQUESTED-20260815-V1",
            "original_bytes_digest": "2460f014e141e1ce74c60ca691f3c32b640c57cc48408f6bcbabd65d161d3744",
            "allowed_correction_fields": ("gate",),
        },
        {
            "finding_id": "CR071-LEDGER-RAW-002",
            "source_ledger_ref": "process/state/AGENT-DISPATCH-LEDGER.ndjson",
            "source_line": 539,
            "source_event_id": "DISPATCH-CR071-CP2-META-PM-REV2-RESUMED-20260815-V1",
            "original_bytes_digest": "f481829d6580c11749796aea07177a987c074e25fd8c5fa7df8814ab41b2bf41",
            "allowed_correction_fields": ("dispatch_id", "canonical_role"),
        },
        {
            "finding_id": "CR071-LEDGER-RAW-003",
            "source_ledger_ref": "process/state/AGENT-DISPATCH-LEDGER.ndjson",
            "source_line": 540,
            "source_event_id": "DISPATCH-CR071-CP2-META-PM-REV2-COMPLETED-20260815-V1",
            "original_bytes_digest": "3492d2e3d57399fd12a03ed56696d890aad507e4755a0b99ca01ef7c3832e509",
            "allowed_correction_fields": ("dispatch_id", "canonical_role"),
        },
    )


_TRANSACTION_SOURCE_PREIMAGES = (
    ("process/state/AGENT-DISPATCH-LEDGER.ndjson", "7" * 64),
    ("process/state/GATE-LEDGER.ndjson", "6" * 64),
)
_TRANSACTION_COMPLETION = (
    ("STORY-CR071-S00", "process/evidence/STORY-CR071-S00.CP6.index.json", "8" * 64),
    ("STORY-CR071-S08", "process/evidence/STORY-CR071-S08.CP6.index.json", "9" * 64),
)
_TRANSACTION_AUTH_REF = "process/authorizations/CR071-S00-ATOMIC-CORRECTION.json"
_TRANSACTION_AUTH_DIGEST = "a" * 64


def _transaction_events() -> tuple[dict[str, object], ...]:
    target_by_ref = dict(_TRANSACTION_SOURCE_PREIMAGES)
    events: list[dict[str, object]] = []
    for index, source in enumerate(_transaction_baseline(), start=1):
        logical_ref = str(source["source_ledger_ref"])
        events.append(
            {
                "schema_version": 1,
                "event_id": f"CORRECTION-CR071-{index:03d}",
                "event_type": "compensates",
                "source_ledger_ref": logical_ref,
                "source_line": source["source_line"],
                "source_event_id": source["source_event_id"],
                "original_bytes_digest": source["original_bytes_digest"],
                "preimage_release_oid": "b" * 40,
                "preimage_process_oid": "c" * 40,
                "target_preimage_digest": target_by_ref[logical_ref],
                "correction_fields": event_ledger.canonical_correction_fields(
                    str(source["finding_id"])
                ),
                "authoritative_evidence_refs": (
                    "process/checks/CP5-CR071-S08-ATOMIC-CORRECTION-REPAIR-FORMAL.result.json",
                ),
                "authoritative_evidence_digests": ("d" * 64,),
                "remediation_story_ref": "process/stories/CR-071/STORY-CR071-S00-ledger-remediation-lineage.md",
                "implementation_completion_evidence_ref": "process/evidence/STORY-CR071-S00.CP6.index.json",
                "implementation_completion_evidence_digest": "8" * 64,
                "previous_effective_event_id": "",
                "previous_effective_event_digest": "",
                "typed_authorization_ref": _TRANSACTION_AUTH_REF,
                "created_by": "native-correction-transaction-writer",
                "created_at": "2026-08-16T10:00:00Z",
            }
        )
    return tuple(events)


def _transaction_snapshot(ledger_bytes: bytes = b"") -> CorrectionTransactionSnapshotV1:
    return CorrectionTransactionSnapshotV1(
        release_oid="b" * 40,
        process_oid="c" * 40,
        release_dirty_inventory_digest="d" * 64,
        process_dirty_inventory_digest="e" * 64,
        source_preimages=_TRANSACTION_SOURCE_PREIMAGES,
        transaction_ledger_preimage=sha256(ledger_bytes).hexdigest(),
    )


def _transaction_plan():
    return plan_correction_transaction(
        _transaction_snapshot(),
        baseline=_transaction_baseline(),
        candidate_events=_transaction_events(),
        completion_evidence=_TRANSACTION_COMPLETION,
        authorization_ref=_TRANSACTION_AUTH_REF,
        authorization_digest=_TRANSACTION_AUTH_DIGEST,
        created_by="native-correction-transaction-writer",
        created_at="2026-08-16T10:00:00Z",
    )


def _completion_digests() -> dict[str, str]:
    return {ref: digest for _story, ref, digest in _TRANSACTION_COMPLETION}


def _authorization_digests() -> dict[str, str]:
    return {_TRANSACTION_AUTH_REF: _TRANSACTION_AUTH_DIGEST}


def test_correction_transaction_plan_scan_and_canonical_values_are_closed() -> None:
    plan = _transaction_plan()
    assert plan.decision == "READY"
    assert plan.record is not None
    assert plan.mutation_count == 0
    validation = event_ledger.validate_correction_transaction(
        plan.record,
        _transaction_baseline(),
        _completion_digests(),
        _authorization_digests(),
    )
    assert validation.decision == "PASS"
    payload = event_ledger.canonical_correction_transaction_line(plan.record)
    scan = event_ledger.scan_correction_transactions(
        payload,
        _transaction_baseline(),
        _completion_digests(),
        _authorization_digests(),
    )
    assert scan.decision == "PASS"
    assert scan.record_count == 1
    assert scan.authority is not None
    assert scan.authority.transaction_record_digest == plan.record_digest

    drifted = json.loads(payload)
    drifted["corrections"][0]["correction_fields"]["gate"] = "WRONG"
    assert event_ledger.validate_correction_transaction(
        drifted,
        _transaction_baseline(),
        _completion_digests(),
        _authorization_digests(),
    ).code == "CORRECTION_VALUE_MISMATCH"
    assert event_ledger.scan_correction_transactions(
        payload[:-1],
        _transaction_baseline(),
        _completion_digests(),
        _authorization_digests(),
    ).errors == ("MALFORMED_TRANSACTION_TAIL",)
    legacy = b'{"schema_version":1}\n'
    assert event_ledger.scan_correction_transactions(
        legacy,
        _transaction_baseline(),
        _completion_digests(),
        _authorization_digests(),
    ).errors == ("SCHEMA_MIGRATION_REQUIRED",)


def test_correction_transaction_atomic_apply_replay_and_real_target_guard(
    tmp_path: Path,
) -> None:
    plan = _transaction_plan()
    state_dir = tmp_path / "process/state"
    ledger = state_dir / "CORRECTION-TRANSACTION-LEDGER.ndjson"
    lock = tmp_path / ".meta-flow-runtime/correction-transaction.lock"
    receipt = apply_correction_transaction(
        plan,
        transaction_ledger=ledger,
        lock_path=lock,
        allowed_state_dir=state_dir,
        target_logical_ref=CORRECTION_TRANSACTION_LEDGER_REF,
        fresh_snapshot=_transaction_snapshot,
        baseline=_transaction_baseline(),
        completion_evidence_digests=_completion_digests(),
        authorization_evidence_digests=_authorization_digests(),
    )
    assert receipt["decision"] == "APPLIED"
    assert receipt["mutation_count"] == 1
    assert not lock.exists()
    committed = ledger.read_bytes()
    assert event_ledger.scan_correction_transactions(
        committed,
        _transaction_baseline(),
        _completion_digests(),
        _authorization_digests(),
    ).authority is not None

    replay = apply_correction_transaction(
        plan,
        transaction_ledger=ledger,
        lock_path=lock,
        allowed_state_dir=state_dir,
        target_logical_ref=CORRECTION_TRANSACTION_LEDGER_REF,
        fresh_snapshot=lambda: _transaction_snapshot(committed),
        baseline=_transaction_baseline(),
        completion_evidence_digests=_completion_digests(),
        authorization_evidence_digests=_authorization_digests(),
    )
    assert replay["decision"] == "NO_CHANGE"
    assert replay["mutation_count"] == 0
    assert ledger.read_bytes() == committed

    raw_target = state_dir / "GATE-LEDGER.ndjson"
    denied = apply_correction_transaction(
        plan,
        transaction_ledger=raw_target,
        lock_path=lock,
        allowed_state_dir=state_dir,
        target_logical_ref=CORRECTION_TRANSACTION_LEDGER_REF,
        fresh_snapshot=_transaction_snapshot,
        baseline=_transaction_baseline(),
        completion_evidence_digests=_completion_digests(),
        authorization_evidence_digests=_authorization_digests(),
    )
    assert denied["blockers"] == ["TRANSACTION_TARGET_NOT_ALLOWED"]
    assert denied["mutation_count"] == 0
    assert not raw_target.exists()


def test_correction_transaction_fault_matrix_preserves_old_or_valid_new_bytes(
    tmp_path: Path,
) -> None:
    prewrite = {
        "before_lock",
        "after_lock",
        "after_fresh_recapture",
        "before_atomic_replace",
    }
    for stage in (*sorted(prewrite), "after_atomic_replace", "after_reread"):
        case_root = tmp_path / stage
        state_dir = case_root / "process/state"
        ledger = state_dir / "CORRECTION-TRANSACTION-LEDGER.ndjson"
        lock = case_root / ".meta-flow-runtime/correction-transaction.lock"

        def inject(current: str, *, expected: str = stage) -> None:
            if current == expected:
                raise RuntimeError(f"fault at {current}")

        receipt = apply_correction_transaction(
            _transaction_plan(),
            transaction_ledger=ledger,
            lock_path=lock,
            allowed_state_dir=state_dir,
            target_logical_ref=CORRECTION_TRANSACTION_LEDGER_REF,
            fresh_snapshot=_transaction_snapshot,
            baseline=_transaction_baseline(),
            completion_evidence_digests=_completion_digests(),
            authorization_evidence_digests=_authorization_digests(),
            fault_injector=inject,
        )
        assert not lock.exists()
        if stage in prewrite:
            assert receipt["decision"] == "BLOCKED"
            assert receipt["mutation_count"] == 0
            assert not ledger.exists()
        else:
            assert receipt["decision"] == "BLOCKED_RECOVERY_REQUIRED"
            assert receipt["mutation_count"] == 1
            scan = event_ledger.scan_correction_transactions(
                ledger.read_bytes(),
                _transaction_baseline(),
                _completion_digests(),
                _authorization_digests(),
            )
            assert scan.decision == "PASS"
            assert scan.authority is not None


def test_correction_transaction_competing_fresh_snapshot_blocks_without_write(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "process/state"
    ledger = state_dir / "CORRECTION-TRANSACTION-LEDGER.ndjson"
    lock = tmp_path / ".meta-flow-runtime/correction-transaction.lock"
    drifted = CorrectionTransactionSnapshotV1(
        **{
            **_transaction_snapshot().__dict__,
            "process_oid": "f" * 40,
        }
    )
    receipt = apply_correction_transaction(
        _transaction_plan(),
        transaction_ledger=ledger,
        lock_path=lock,
        allowed_state_dir=state_dir,
        target_logical_ref=CORRECTION_TRANSACTION_LEDGER_REF,
        fresh_snapshot=lambda: drifted,
        baseline=_transaction_baseline(),
        completion_evidence_digests=_completion_digests(),
        authorization_evidence_digests=_authorization_digests(),
    )
    assert receipt["blockers"] == ["FRESH_FACT_DRIFT"]
    assert receipt["mutation_count"] == 0
    assert not ledger.exists()
