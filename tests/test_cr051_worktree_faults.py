from __future__ import annotations

import errno
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from meta_flow.workspace.worktree_capacity import (
    DEFAULT_CAPACITY_FLOOR_BYTES,
    CalibrationEvidence,
    CapacityProbe,
    CheckoutEntry,
    CheckoutSnapshot,
    build_capacity_proof,
    capacity_required_bytes,
    prove_checkout_capacity,
    record_capacity_outcome,
    validate_capacity_proof,
)
from meta_flow.workspace.worktree_journal import (
    JournalError,
    JournalFileOps,
    WorktreeJournal,
)


def _calibration(**overrides: object) -> CalibrationEvidence:
    values: dict[str, object] = {
        "profile_id": "plain-checkout",
        "profile_version": "1",
        "profile_digest": "profile-digest",
        "status": "CALIBRATED",
        "false_safe_count": 0,
        "underestimate_count": 0,
        "calibration_ref": "fixture://capacity/plain-v1",
    }
    values.update(overrides)
    return CalibrationEvidence(**values)


def _snapshot(*, entries: int = 2, **overrides: object) -> CheckoutSnapshot:
    values: dict[str, object] = {
        "profile_id": "plain-checkout",
        "profile_version": "1",
        "profile_digest": "profile-digest",
        "tree_oid": "a" * 40,
        "index_digest": "index-digest",
        "sparse_digest": "sparse-digest",
        "entries": tuple(
            CheckoutEntry(path=f"docs/file-{index}.md", blob_size=8192 * (index + 1))
            for index in range(entries)
        ),
        "current_index_size": 4096,
        "target_index_encoded_size": 8192,
        "block_size": 4096,
        "enumeration_complete": True,
        "transform_safe": True,
        "error_reason": "",
    }
    values.update(overrides)
    return CheckoutSnapshot(**values)


def _probe(
    filesystem_id: str, available: int = 2 * DEFAULT_CAPACITY_FLOOR_BYTES, **overrides: object
) -> CapacityProbe:
    values: dict[str, object] = {
        "filesystem_id": filesystem_id,
        "available_bytes": available,
        "block_size": 4096,
        "error_reason": "",
    }
    values.update(overrides)
    return CapacityProbe(**values)


def _decision(**snapshot_overrides: object):
    return prove_checkout_capacity(
        _snapshot(**snapshot_overrides),
        checkout_fs=_probe("checkout-fs"),
        journal_fs=_probe("journal-fs"),
        calibration=_calibration(),
    )


def _materialize_checkout(tmp_path: Path, snapshot: CheckoutSnapshot) -> int:
    actual = 0
    for entry in snapshot.entries:
        path = tmp_path / entry.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * entry.blob_size)
        stat = path.stat()
        actual += stat.st_blocks * 512
    return actual


def test_cap_01_small_bounded_checkout_is_conservative_and_eligible(tmp_path: Path) -> None:
    snapshot = _snapshot(entries=2)
    decision = _decision(entries=2)
    actual = _materialize_checkout(tmp_path, snapshot)
    calibrated = record_capacity_outcome(
        _calibration(), decision.checkout, actual_write_bytes=actual, enospc=False
    )

    assert decision.decision == "PASS"
    assert decision.checkout.upper_bound_bytes >= actual
    assert decision.checkout.required_bytes == DEFAULT_CAPACITY_FLOOR_BYTES
    assert calibrated.false_safe_count == 0
    assert calibrated.underestimate_count == 0


def test_cap_02_medium_checkout_is_deterministic(tmp_path: Path) -> None:
    snapshot = _snapshot(entries=16)
    first = _decision(entries=16)
    second = _decision(entries=16)
    actual = _materialize_checkout(tmp_path, snapshot)

    assert first == second
    assert first.checkout.upper_bound_bytes >= actual
    assert first.checkout.required_bytes >= first.checkout.upper_bound_bytes


def test_cap_03_512_mib_boundary_is_inclusive() -> None:
    upper = DEFAULT_CAPACITY_FLOOR_BYTES * 2 // 3

    assert capacity_required_bytes(upper) == DEFAULT_CAPACITY_FLOOR_BYTES


def test_cap_04_above_512_mib_uses_proved_requirement_not_floor() -> None:
    upper = DEFAULT_CAPACITY_FLOOR_BYTES

    assert capacity_required_bytes(upper) == DEFAULT_CAPACITY_FLOOR_BYTES * 3 // 2


def test_cap_05_actual_write_equal_to_upper_bound_keeps_profile_calibrated() -> None:
    decision = _decision(entries=8)

    updated = record_capacity_outcome(
        _calibration(),
        decision.checkout,
        actual_write_bytes=decision.checkout.upper_bound_bytes,
        enospc=False,
    )

    assert updated.status == "CALIBRATED"
    assert updated.false_safe_count == 0
    assert updated.underestimate_count == 0


def test_cap_06_underestimate_revokes_profile() -> None:
    decision = _decision(entries=8)

    updated = record_capacity_outcome(
        _calibration(),
        decision.checkout,
        actual_write_bytes=decision.checkout.upper_bound_bytes + 1,
        enospc=False,
    )

    assert updated.status == "REVOKED"
    assert updated.underestimate_count == 1


def test_cap_07_false_safe_enospc_revokes_profile() -> None:
    decision = _decision(entries=8)

    updated = record_capacity_outcome(
        _calibration(),
        decision.checkout,
        actual_write_bytes=decision.checkout.upper_bound_bytes,
        enospc=True,
    )

    assert updated.status == "REVOKED"
    assert updated.false_safe_count == 1


def test_cap_08_permission_unknown_blocks_before_mutation() -> None:
    decision = prove_checkout_capacity(
        _snapshot(),
        checkout_fs=_probe("checkout-fs", error_reason="EACCES"),
        journal_fs=_probe("journal-fs"),
        calibration=_calibration(),
    )

    assert decision.decision == "BLOCKED"
    assert decision.reason == "capacity_unproven"


def test_cap_09_incomplete_enumeration_never_uses_512_mib_fallback() -> None:
    decision = _decision(enumeration_complete=False, error_reason="tree enumeration timed out")

    assert decision.decision == "BLOCKED"
    assert decision.checkout.bounded_512_eligible is False


def test_cap_10_profile_digest_mismatch_blocks() -> None:
    decision = prove_checkout_capacity(
        _snapshot(profile_digest="new-profile"),
        checkout_fs=_probe("checkout-fs"),
        journal_fs=_probe("journal-fs"),
        calibration=_calibration(),
    )

    assert decision.decision == "BLOCKED"
    assert decision.reason == "capacity_unproven"


def test_cap_11_checkout_and_journal_filesystems_are_independent() -> None:
    decision = prove_checkout_capacity(
        _snapshot(),
        checkout_fs=_probe("checkout-fs"),
        journal_fs=_probe("journal-fs", available=0),
        calibration=_calibration(),
    )

    assert decision.checkout.filesystem_id == "checkout-fs"
    assert decision.journal.filesystem_id == "journal-fs"
    assert decision.checkout.decision == "PASS"
    assert decision.journal.decision == "BLOCKED"
    assert decision.decision == "BLOCKED"


def test_cap_12_capacity_proof_is_attempt_bound_and_expires() -> None:
    created_at = datetime(2026, 7, 19, 9, 0, tzinfo=UTC)
    calibration = _calibration()
    proof = build_capacity_proof(
        _decision(),
        calibration,
        project_id="meta-flow",
        repository_id="artifact-fixture",
        operation_id="op-1",
        attempt_id="attempt-1",
        before_observation_digest="before-digest",
        target_ref="refs/heads/projects/meta-flow/cr/cr-051-proof",
        target_oid="b" * 40,
        created_at=created_at,
        ttl=timedelta(minutes=5),
    )

    assert validate_capacity_proof(
        proof,
        calibration,
        project_id="meta-flow",
        repository_id="artifact-fixture",
        operation_id="op-1",
        attempt_id="attempt-1",
        before_observation_digest="before-digest",
        target_ref="refs/heads/projects/meta-flow/cr/cr-051-proof",
        target_oid="b" * 40,
        now=created_at,
    ) == (True, "capacity_proved")
    assert validate_capacity_proof(
        proof,
        calibration,
        project_id="meta-flow",
        repository_id="artifact-fixture",
        operation_id="op-1",
        attempt_id="attempt-2",
        before_observation_digest="before-digest",
        target_ref="refs/heads/projects/meta-flow/cr/cr-051-proof",
        target_oid="b" * 40,
        now=created_at,
    ) == (False, "capacity_proof_binding_mismatch")
    assert validate_capacity_proof(
        proof,
        calibration,
        project_id="meta-flow",
        repository_id="artifact-fixture",
        operation_id="op-1",
        attempt_id="attempt-1",
        before_observation_digest="before-digest",
        target_ref="refs/heads/projects/meta-flow/cr/cr-051-proof",
        target_oid="b" * 40,
        now=created_at + timedelta(minutes=6),
    ) == (False, "capacity_proof_expired")


def test_cap_13_revoked_calibration_invalidates_existing_proof() -> None:
    created_at = datetime(2026, 7, 19, 9, 0, tzinfo=UTC)
    calibration = _calibration()
    proof = build_capacity_proof(
        _decision(),
        calibration,
        project_id="meta-flow",
        repository_id="artifact-fixture",
        operation_id="op-1",
        attempt_id="attempt-1",
        before_observation_digest="before-digest",
        target_ref="refs/heads/projects/meta-flow/cr/cr-051-proof",
        target_oid="b" * 40,
        created_at=created_at,
    )
    revoked = replace(calibration, status="REVOKED", underestimate_count=1)

    ok, reason = validate_capacity_proof(
        proof,
        revoked,
        project_id="meta-flow",
        repository_id="artifact-fixture",
        operation_id="op-1",
        attempt_id="attempt-1",
        before_observation_digest="before-digest",
        target_ref="refs/heads/projects/meta-flow/cr/cr-051-proof",
        target_oid="b" * 40,
        now=created_at,
    )

    assert ok is False
    assert reason == "calibration_revoked_or_mismatch"


class FaultOps(JournalFileOps):
    def __init__(self, fault: str | None = None) -> None:
        self.fault = fault
        self.checkpoints: list[str] = []

    def checkpoint(self, name: str) -> None:
        self.checkpoints.append(name)
        if name != self.fault:
            return
        if name == "temp_write_enospc":
            raise OSError(errno.ENOSPC, "fixture ENOSPC")
        if name == "temp_open_eacces":
            raise OSError(errno.EACCES, "fixture EACCES")
        if name == "replace_cross_device":
            raise OSError(errno.EXDEV, "fixture EXDEV")
        raise OSError(errno.EIO, f"fixture fault at {name}")


def _journal(tmp_path: Path, *, fault: str | None = None) -> tuple[WorktreeJournal, FaultOps]:
    target = tmp_path / "projects" / "meta-flow"
    target.mkdir(parents=True)
    ops = FaultOps(fault)
    journal = WorktreeJournal(
        store_root=tmp_path / "state" / "meta-flow",
        target_path=target,
        project_id="meta-flow",
        repository_id="artifact-fixture",
        file_ops=ops,
    )
    return journal, ops


@pytest.mark.parametrize(
    ("case_id", "fault", "expected_code"),
    [
        ("DUR-01", "temp_write_enospc", "journal_enospc"),
        ("DUR-02", "temp_open_eacces", "journal_eacces"),
        ("DUR-03", "file_fsync", "journal_fsync_failed"),
        ("DUR-04", "replace", "journal_replace_failed"),
        ("DUR-05", "dir_fsync", "journal_dir_fsync_failed"),
        ("DUR-06", "readback", "journal_readback_failed"),
    ],
)
def test_dur_01_to_06_faults_never_return_a_durable_intent(
    tmp_path: Path, case_id: str, fault: str, expected_code: str
) -> None:
    journal, _ = _journal(tmp_path, fault=fault)
    git_mutations: list[str] = []

    with pytest.raises(JournalError) as error:
        journal.persist_intent(
            "op-1", "attempt-1", {"target_ref": "refs/heads/projects/meta-flow/integration"}
        )

    assert error.value.code == expected_code, case_id
    assert git_mutations == []


def test_dur_07_torn_record_is_rejected(tmp_path: Path) -> None:
    journal, _ = _journal(tmp_path)
    intent = journal.persist_intent("op-1", "attempt-1", {"target_oid": "a" * 40})
    intent.intent_record.path.write_text('{"torn":', encoding="utf-8")

    scan = journal.scan_attempt("op-1", "attempt-1")

    assert scan.decision == "BLOCKED"
    assert scan.reason == "journal_chain_invalid"


@pytest.mark.parametrize("fault", ["temp_write", "file_flush", "after_file_fsync"])
def test_dur_08_kill_before_replace_leaves_no_consumable_intent(tmp_path: Path, fault: str) -> None:
    journal, _ = _journal(tmp_path, fault=fault)

    with pytest.raises(JournalError):
        journal.persist_intent("op-1", "attempt-1", {"target_oid": "a" * 40})

    assert journal.scan_attempt("op-1", "attempt-1").durable_intent is None


def test_dur_09_kill_after_replace_before_dir_fsync_has_no_valid_seal(tmp_path: Path) -> None:
    journal, _ = _journal(tmp_path, fault="dir_fsync")

    with pytest.raises(JournalError):
        journal.persist_intent("op-1", "attempt-1", {"target_oid": "a" * 40})

    scan = journal.scan_attempt("op-1", "attempt-1")
    assert scan.decision == "BLOCKED"
    assert scan.durable_intent is None


def test_dur_10_sealed_intent_is_readback_verified_before_git(tmp_path: Path) -> None:
    journal, ops = _journal(tmp_path)
    git_mutations: list[str] = []

    intent = journal.persist_intent("op-1", "attempt-1", {"target_oid": "a" * 40})

    assert intent.sealed is True
    assert intent.intent_record.record_digest == intent.seal_record.payload["sealed_record_digest"]
    assert ops.checkpoints.index("dir_fsync") < ops.checkpoints.index("readback")
    assert git_mutations == []


def test_dur_11_observation_required_phase_is_durable_and_scannable(tmp_path: Path) -> None:
    journal, _ = _journal(tmp_path)
    intent = journal.persist_intent("op-1", "attempt-1", {"target_oid": "a" * 40})

    record = journal.persist_phase(
        "op-1",
        "attempt-1",
        "OBSERVATION_REQUIRED",
        {"intent_seal_digest": intent.seal_record.record_digest},
    )
    scan = journal.scan_attempt("op-1", "attempt-1")

    assert record.phase == "OBSERVATION_REQUIRED"
    assert scan.decision == "PASS"


def test_dur_12_cross_device_replace_is_blocked_without_copy_fallback(tmp_path: Path) -> None:
    journal, ops = _journal(tmp_path, fault="replace_cross_device")

    with pytest.raises(JournalError) as error:
        journal.persist_intent("op-1", "attempt-1", {"target_oid": "a" * 40})

    assert error.value.code == "cross_device_store"
    assert "copy" not in ops.checkpoints


def test_dur_13_sequence_gap_or_previous_digest_mismatch_is_rejected(tmp_path: Path) -> None:
    journal, _ = _journal(tmp_path)
    journal.persist_intent("op-1", "attempt-1", {"target_oid": "a" * 40})
    records = sorted(journal.attempt_path("op-1", "attempt-1").glob("*.json"))
    payload = json.loads(records[-1].read_text(encoding="utf-8"))
    payload["previous_record_digest"] = "0" * 64
    records[-1].write_text(json.dumps(payload), encoding="utf-8")

    scan = journal.scan_attempt("op-1", "attempt-1")

    assert scan.decision == "BLOCKED"
    assert scan.reason == "journal_chain_invalid"


def test_dur_14_repeated_resume_scan_is_idempotent(tmp_path: Path) -> None:
    journal, _ = _journal(tmp_path)
    journal.persist_intent("op-1", "attempt-1", {"target_oid": "a" * 40})

    scans = [journal.scan_attempt("op-1", "attempt-1") for _ in range(10)]

    assert all(scan == scans[0] for scan in scans)
    assert scans[0].decision == "PASS"
    assert [record.sequence for record in scans[0].records] == [1, 2]


def test_tc_aw_014_project_lock_is_non_blocking_and_project_scoped(tmp_path: Path) -> None:
    first, _ = _journal(tmp_path)
    second = WorktreeJournal(
        store_root=first.store_root,
        target_path=first.target_path,
        project_id="meta-flow",
        repository_id="artifact-fixture",
    )

    with first.project_lock():
        with pytest.raises(JournalError) as error:
            with second.project_lock():
                pass

    assert error.value.code == "lock_unavailable"


def test_dur_15_owner_marker_rejects_cross_project_reuse(tmp_path: Path) -> None:
    first, _ = _journal(tmp_path)
    first.persist_intent("op-1", "attempt-1", {"target_oid": "a" * 40})
    second = WorktreeJournal(
        store_root=first.store_root,
        target_path=first.target_path,
        project_id="other-project",
        repository_id="artifact-fixture",
    )

    scan = second.scan_attempt("op-1", "attempt-1")

    assert scan.decision == "BLOCKED"
    assert scan.reason == "journal_owner_mismatch"
    with pytest.raises(JournalError) as error:
        with second.project_lock():
            pass
    assert error.value.code == "journal_owner_mismatch"


def test_dur_16_calibration_and_revocation_are_persisted(tmp_path: Path) -> None:
    journal, _ = _journal(tmp_path)
    calibrated = _calibration()

    path = journal.save_calibration(calibrated)
    assert path.is_file()
    assert journal.load_calibration(calibrated.profile_digest) == calibrated

    revoked = replace(calibrated, status="REVOKED", false_safe_count=1)
    journal.save_calibration(revoked)
    assert journal.load_calibration(calibrated.profile_digest) == revoked


def test_dur_17_record_identity_tampering_is_rejected_even_with_recomputed_digest(
    tmp_path: Path,
) -> None:
    journal, _ = _journal(tmp_path)
    journal.persist_intent("op-1", "attempt-1", {"target_oid": "a" * 40})
    first = sorted(journal.attempt_path("op-1", "attempt-1").glob("*.json"))[0]
    document = json.loads(first.read_text(encoding="utf-8"))
    document["project_id"] = "other-project"
    unsigned = {key: value for key, value in document.items() if key != "record_digest"}
    document["record_digest"] = hashlib.sha256(
        json.dumps(
            unsigned,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    first.write_text(
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )

    scan = journal.scan_attempt("op-1", "attempt-1")

    assert scan.decision == "BLOCKED"
    assert scan.reason == "journal_chain_invalid"


def test_dur_18_invalid_phase_transition_is_rejected_before_write(tmp_path: Path) -> None:
    journal, _ = _journal(tmp_path)
    journal.persist_intent("op-1", "attempt-1", {"target_oid": "a" * 40})

    with pytest.raises(JournalError) as error:
        journal.persist_phase("op-1", "attempt-1", "FINAL_OBSERVATION", {})

    assert error.value.code == "journal_phase_invalid"
    assert [record.phase for record in journal.scan_attempt("op-1", "attempt-1").records] == [
        "INTENT",
        "INTENT_SEAL",
    ]
