from __future__ import annotations

from pathlib import Path

import pytest

from meta_flow.work.handoff import WorkHandoff, write_handoff
from meta_flow.work.scope import (
    SystemArtifactKindV1,
    authorize_system_write,
    classify_system_artifact,
)


def test_digest_derived_receipt_is_bounded_without_business_scope() -> None:
    ref = "works/W-001/evidence/validation/targeted-0123456789abcdefabcd.receipt.json"
    decision = classify_system_artifact(
        "W-001", "work.validation-receipt.write", ref
    )

    assert decision.allowed
    assert decision.namespace is not None
    assert decision.namespace.artifact_kind is SystemArtifactKindV1.RECEIPT
    assert authorize_system_write(decision.namespace, ref).allowed


@pytest.mark.parametrize(
    ("operation", "ref", "code"),
    [
        (
            "third-party.writer",
            "works/W-001/evidence/validation/targeted-0123456789abcdefabcd.receipt.json",
            "SYSTEM_WRITER_UNREGISTERED",
        ),
        (
            "work.validation-receipt.write",
            "works/W-002/evidence/validation/targeted-0123456789abcdefabcd.receipt.json",
            "SYSTEM_NAMESPACE_BOUNDARY_VIOLATION",
        ),
        (
            "work.validation-receipt.write",
            "works/W-001/evidence/validation/../secret.json",
            "SYSTEM_REF_UNSAFE",
        ),
        (
            "work.validation-receipt.write",
            "works/W-001/evidence/validation/arbitrary.json",
            "SYSTEM_NAMESPACE_BOUNDARY_VIOLATION",
        ),
    ],
)
def test_unregistered_cross_work_or_unsafe_system_writes_fail_closed(
    operation: str,
    ref: str,
    code: str,
) -> None:
    decision = classify_system_artifact("W-001", operation, ref)
    assert decision.decision == "BLOCKED"
    assert decision.reason_code == code
    assert decision.mutation_count == 0


def test_symlink_target_is_rejected_after_namespace_classification() -> None:
    ref = "works/W-001/HANDOFF.yaml"
    decision = classify_system_artifact("W-001", "work.handoff.write", ref)
    assert decision.namespace is not None

    result = authorize_system_write(
        decision.namespace,
        ref,
        target_is_symlink=True,
    )

    assert result.decision == "BLOCKED"
    assert result.reason_code == "SYSTEM_TARGET_SYMLINK"


def test_native_handoff_writer_uses_its_system_namespace(tmp_path: Path) -> None:
    process = tmp_path / "process"
    handoff = WorkHandoff(
        work_id="W-001",
        project_id="fixture",
        work_status="paused",
        scope_digest="a" * 64,
        release_oid="b" * 40,
        process_oid="c" * 40,
        completed=("preflight",),
        remaining=("resume",),
        blockers=(),
        next_step="恢复前重新核对绑定",
        evidence_refs=("works/W-001/REQUEST.md",),
    )

    target = write_handoff(process, handoff)

    assert target == process / "works/W-001/HANDOFF.yaml"
    assert target.is_file()


def test_native_handoff_writer_rejects_symlink_target(tmp_path: Path) -> None:
    process = tmp_path / "process"
    target = process / "works/W-001/HANDOFF.yaml"
    target.parent.mkdir(parents=True)
    actual = process / "actual.yaml"
    actual.write_text("safe: true\n", encoding="utf-8")
    try:
        target.symlink_to(actual)
    except OSError:
        pytest.skip("当前平台不支持 symlink")
    handoff = WorkHandoff(
        "W-001",
        "fixture",
        "blocked",
        "a" * 64,
        "b" * 40,
        "c" * 40,
        (),
        ("repair",),
        ("blocked",),
        "修复后恢复",
        (),
    )

    with pytest.raises(ValueError, match="SYSTEM_TARGET_SYMLINK"):
        write_handoff(process, handoff)

    assert actual.read_text(encoding="utf-8") == "safe: true\n"
