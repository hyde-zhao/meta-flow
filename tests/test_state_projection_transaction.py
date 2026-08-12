from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from meta_flow.state import projection_transaction


def _targets(prefix: str) -> dict[str, bytes]:
    return {
        "process/state/STATE.current.json": json.dumps({"state": prefix}).encode(),
        "process/STATE.md": f"state={prefix}\n".encode(),
        "process/current/CURRENT.json": json.dumps({"current": prefix}).encode(),
    }


def test_state_projection_transaction_commits_exact_file_set(tmp_path: Path) -> None:
    result = projection_transaction.apply_state_projection_transaction(tmp_path, _targets("after"))

    assert result["decision"] == "PASS"
    assert result["mutation_count"] == 3
    assert (
        projection_transaction.inspect_state_projection_transaction(tmp_path)["decision"] == "PASS"
    )
    assert (tmp_path / "process/STATE.md").read_text(encoding="utf-8") == "state=after\n"


def test_hard_interrupt_is_detected_and_recoverable(tmp_path: Path) -> None:
    projection_transaction.apply_state_projection_transaction(tmp_path, _targets("before"))
    real_replace = projection_transaction._replace_bytes
    domain_writes = 0

    def interrupt_after_first(path: Path, value: bytes) -> None:
        nonlocal domain_writes
        if "process" in path.parts and ".meta-flow-runtime" not in path.parts:
            domain_writes += 1
            real_replace(path, value)
            if domain_writes == 1:
                raise KeyboardInterrupt("fixture hard interrupt")
            return
        real_replace(path, value)

    with patch.object(projection_transaction, "_replace_bytes", side_effect=interrupt_after_first):
        with pytest.raises(KeyboardInterrupt):
            projection_transaction.apply_state_projection_transaction(tmp_path, _targets("after"))

    inspection = projection_transaction.inspect_state_projection_transaction(tmp_path)
    assert inspection["decision"] == "BLOCKED"
    assert inspection["state"] == "APPLYING"
    manifest = json.loads(
        (tmp_path / projection_transaction.MANIFEST_REL).read_text(encoding="utf-8")
    )
    stale_lock = tmp_path / projection_transaction.LOCK_REL
    stale_lock.write_text(manifest["transaction_id"] + "\n", encoding="utf-8")

    recovered = projection_transaction.recover_state_projection_transaction(tmp_path)

    assert recovered["decision"] == "RECOVERED"
    assert recovered["lock_recovered"] is True
    assert not stale_lock.exists()
    assert (
        projection_transaction.inspect_state_projection_transaction(tmp_path)["decision"] == "PASS"
    )
    assert json.loads(
        (tmp_path / "process/state/STATE.current.json").read_text(encoding="utf-8")
    ) == {"state": "before"}


def test_poisoned_manifest_target_is_blocked_before_recovery_write(tmp_path: Path) -> None:
    projection_transaction.apply_state_projection_transaction(tmp_path, _targets("before"))
    manifest_path = tmp_path / projection_transaction.MANIFEST_REL
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["state"] = "APPLYING"
    manifest["targets"][0]["ref"] = "../../outside.txt"
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    inspection = projection_transaction.inspect_state_projection_transaction(tmp_path)

    assert inspection["decision"] == "BLOCKED"
    with pytest.raises(ValueError, match="not allowed"):
        projection_transaction.recover_state_projection_transaction(tmp_path)


def test_atomic_writer_rejects_symlinked_parent_before_mutation(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="directory path is unsafe"):
        projection_transaction._replace_bytes(linked_parent / "target.json", b"blocked")

    assert list(outside.iterdir()) == []


def test_writer_lock_identity_drift_is_not_silently_deleted(tmp_path: Path) -> None:
    real_replace = projection_transaction._replace_bytes
    drifted = False

    def replace_then_drift_lock(path: Path, value: bytes) -> None:
        nonlocal drifted
        real_replace(path, value)
        if not drifted and "process" in path.parts and ".meta-flow-runtime" not in path.parts:
            drifted = True
            lock_path = tmp_path / projection_transaction.LOCK_REL
            lock_path.write_text("foreign-owner\n", encoding="utf-8")

    with patch.object(
        projection_transaction,
        "_replace_bytes",
        side_effect=replace_then_drift_lock,
    ):
        with pytest.raises(ValueError, match="lock identity drifted"):
            projection_transaction.apply_state_projection_transaction(
                tmp_path,
                _targets("after"),
            )

    lock_path = tmp_path / projection_transaction.LOCK_REL
    assert lock_path.read_text(encoding="utf-8") == "foreign-owner\n"


def test_recovery_does_not_steal_live_state_writer_lock(tmp_path: Path) -> None:
    projection_transaction.apply_state_projection_transaction(tmp_path, _targets("before"))
    manifest_path = tmp_path / projection_transaction.MANIFEST_REL
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["state"] = "APPLYING"
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    lock_path = tmp_path / projection_transaction.LOCK_REL
    handle = projection_transaction.acquire_transaction_lock(
        lock_path,
        manifest["transaction_id"],
    )

    try:
        with pytest.raises(ValueError, match="active writer"):
            projection_transaction.recover_state_projection_transaction(tmp_path)
        assert lock_path.exists()
    finally:
        projection_transaction.release_transaction_lock(handle)


def test_recovery_claims_orphan_lock_created_before_manifest(tmp_path: Path) -> None:
    lock_path = projection_transaction.state_projection_lock_path(tmp_path)
    handle = projection_transaction.acquire_transaction_lock(lock_path, "a" * 32)
    # 模拟进程在 PREPARED manifest 写入前退出：OS 释放 advisory lock，锁文件仍在。
    handle.stream.close()

    assert (
        projection_transaction.inspect_state_projection_transaction(tmp_path)["decision"]
        == "BLOCKED"
    )
    recovered = projection_transaction.recover_state_projection_transaction(tmp_path)

    assert recovered["decision"] == "NO_CHANGE"
    assert recovered["lock_recovered"] is True
    assert not lock_path.exists()
