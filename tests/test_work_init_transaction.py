from __future__ import annotations

from pathlib import Path

import pytest

from meta_flow.work.init_transaction import (
    apply_work_init_transaction_targets,
    begin_work_init_transaction,
    build_transaction_target,
    inspect_work_init_transactions,
    recover_work_init_transaction,
)


def test_applying_work_init_transaction_has_exact_native_recovery(
    tmp_path: Path,
) -> None:
    process = tmp_path / "process"
    process.mkdir()
    target_path = process / "PROJECT.yaml"
    before = b"before\n"
    after = b"after\n"
    target_path.write_bytes(before)
    plan_digest = "a" * 64
    release_oid = "b" * 40
    process_oid = "c" * 40
    transaction_id = begin_work_init_transaction(
        process,
        operation="work.init",
        work_id="W-001",
        plan_digest=plan_digest,
        release_oid=release_oid,
        process_oid=process_oid,
        targets=(
            build_transaction_target(
                process,
                ref="PROJECT.yaml",
                after_bytes=after,
            ),
        ),
    )
    apply_work_init_transaction_targets(process, transaction_id)

    inspection = inspect_work_init_transactions(process, work_id="W-001")
    assert inspection["decision"] == "BLOCKED"
    assert inspection["transactions"][0]["state"] == "APPLYING"
    assert target_path.read_bytes() == after

    receipt = recover_work_init_transaction(
        process,
        transaction_id,
        expected_plan_digest=plan_digest,
        release_oid=release_oid,
        process_oid=process_oid,
    )

    assert receipt.decision == "RECOVERED"
    assert target_path.read_bytes() == before
    assert inspect_work_init_transactions(process)["decision"] == "PASS"


def test_work_init_transaction_recovery_rejects_stale_identity(
    tmp_path: Path,
) -> None:
    process = tmp_path / "process"
    process.mkdir()
    (process / "PROJECT.yaml").write_bytes(b"before\n")
    transaction_id = begin_work_init_transaction(
        process,
        operation="work.init",
        work_id="W-001",
        plan_digest="a" * 64,
        release_oid="b" * 40,
        process_oid="c" * 40,
        targets=(
            build_transaction_target(
                process,
                ref="PROJECT.yaml",
                after_bytes=b"after\n",
            ),
        ),
    )

    with pytest.raises(ValueError, match="identity drifted"):
        recover_work_init_transaction(
            process,
            transaction_id,
            expected_plan_digest="d" * 64,
            release_oid="b" * 40,
            process_oid="c" * 40,
        )

    assert (process / "PROJECT.yaml").read_bytes() == b"before\n"


def test_work_init_recovery_removes_exact_created_empty_directories(
    tmp_path: Path,
) -> None:
    process = tmp_path / "process"
    process.mkdir()
    transaction_id = begin_work_init_transaction(
        process,
        operation="work.init",
        work_id="W-NEW",
        plan_digest="a" * 64,
        release_oid="b" * 40,
        process_oid="c" * 40,
        targets=(
            build_transaction_target(
                process,
                ref="works/W-NEW/WORK.yaml",
                after_bytes=b"kind: work\n",
            ),
        ),
    )
    apply_work_init_transaction_targets(process, transaction_id)

    inspection = inspect_work_init_transactions(process, work_id="W-NEW")
    assert inspection["transactions"][0]["created_directory_refs"] == [
        "works",
        "works/W-NEW",
    ]

    receipt = recover_work_init_transaction(
        process,
        transaction_id,
        expected_plan_digest="a" * 64,
        release_oid="b" * 40,
        process_oid="c" * 40,
    )

    assert receipt.decision == "RECOVERED"
    assert not (process / "works/W-NEW").exists()
    assert not (process / "works").exists()


def test_work_init_recovery_preserves_unrelated_content_and_stays_partial(
    tmp_path: Path,
) -> None:
    process = tmp_path / "process"
    process.mkdir()
    transaction_id = begin_work_init_transaction(
        process,
        operation="work.init",
        work_id="W-NEW",
        plan_digest="a" * 64,
        release_oid="b" * 40,
        process_oid="c" * 40,
        targets=(
            build_transaction_target(
                process,
                ref="works/W-NEW/WORK.yaml",
                after_bytes=b"kind: work\n",
            ),
        ),
    )
    apply_work_init_transaction_targets(process, transaction_id)
    unrelated = process / "works/W-NEW/user-owned.txt"
    unrelated.write_text("保留\n", encoding="utf-8")

    receipt = recover_work_init_transaction(
        process,
        transaction_id,
        expected_plan_digest="a" * 64,
        release_oid="b" * 40,
        process_oid="c" * 40,
    )

    assert receipt.decision == "PARTIAL"
    assert receipt.recovery_required
    assert unrelated.read_text(encoding="utf-8") == "保留\n"
    assert not (process / "works/W-NEW/WORK.yaml").exists()
