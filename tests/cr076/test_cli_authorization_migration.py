"""STORY-CR076-S02 compatibility 测试：CLI 授权迁移 exactly-one + equality（AE-07）。

FA8/LCQ-01：同一授权文件经旧直读（deprecated 窗口）与新 envelope 解析
必须产生等价授权对象（MF-BUG-10 terminal 的 equality regression 证据）。
三参恰一；治理 kind 适配（GAP-03）；旧路径 deprecated 标记存在性。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from meta_flow.execution_control.exact_file_transaction import ExactFileAuthorizationV1
from meta_flow.workflow.cr_cli import load_cli_authorization

D64 = "f" * 64
LEGACY_HELP_MARK = "legacy direct-read format is deprecated"


def _exact_file_payload() -> dict:
    # ExactFileAuthorizationV1 七字段闭合集（exact_file_transaction.py:175）
    return {
        "schema_version": 1,
        "kind": "ExactFileAuthorizationV1",
        "authorization_id": "EXACTFILE-CR076-CLI-20260901-V1",
        "operation": "exact-file.replace",
        "plan_digest": D64,
        "target_refs": ["process/changes/CR-076.md"],
        "expires_at": "2026-09-02T00:00:00Z",
    }


def _envelope_document(payload: dict, operation: str) -> dict:
    return {
        "schema_version": 1,
        "kind": "authorization-envelope",
        "authorization_id": f"AUTH-CR076-CLI-{operation}-20260901-V1",
        "operation": operation,
        "target_refs": payload.get("target_refs", ["process/changes/CR-076.md"]),
        "plan_digest": D64,
        "issued_at": "2026-09-01T00:00:00Z",
        "expires_at": "2026-09-02T00:00:00Z",
        "single_use": True,
        "authorization_source": "typed-user-confirmation",
        "payload": payload,
    }


def _legacy_exact_file_loader(path: Path) -> ExactFileAuthorizationV1:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return ExactFileAuthorizationV1.from_mapping(payload)


def _write(tmp_path: Path, name: str, document: dict) -> Path:
    target = tmp_path / name
    target.write_text(json.dumps(document), encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# exactly-one：none / 多选确定性阻断（mutation=0）
# ---------------------------------------------------------------------------


def test_ae_07_none_source_blocked(tmp_path: Path) -> None:
    authorization, error = load_cli_authorization(
        file=None, ref=None, authorization_id=None, legacy_loader=_legacy_exact_file_loader
    )
    assert authorization is None
    assert "exactly one" in error and "none" in error


@pytest.mark.parametrize(
    "kwargs",
    [
        {"file": Path("a.json"), "ref": "process/x.json", "authorization_id": None},
        {"file": None, "ref": "process/x.json", "authorization_id": "AUTH-1"},
        {"file": Path("a.json"), "ref": None, "authorization_id": "AUTH-1"},
    ],
)
def test_ae_07_multi_source_blocked(kwargs: dict) -> None:
    authorization, error = load_cli_authorization(
        legacy_loader=_legacy_exact_file_loader, **kwargs
    )
    assert authorization is None
    assert "exactly one" in error


# ---------------------------------------------------------------------------
# equality：同一授权新旧解析等价（LCQ-01 deprecated 窗口的 terminal 证据）
# ---------------------------------------------------------------------------


def test_ae_07_envelope_equivalent_to_legacy(tmp_path: Path) -> None:
    legacy_file = _write(tmp_path, "legacy.json", _exact_file_payload())
    envelope_file = _write(
        tmp_path, "envelope.json", _envelope_document(_exact_file_payload(), "exact-file-mutation")
    )
    via_legacy, legacy_error = load_cli_authorization(
        file=legacy_file, ref=None, authorization_id=None,
        legacy_loader=_legacy_exact_file_loader, expected_type=ExactFileAuthorizationV1,
    )
    via_envelope, envelope_error = load_cli_authorization(
        file=envelope_file, ref=None, authorization_id=None,
        legacy_loader=_legacy_exact_file_loader, expected_type=ExactFileAuthorizationV1,
    )
    assert legacy_error == "" and envelope_error == ""
    # equality：两条解析路径产生等价授权对象（mutation 判定输入一致）
    assert via_legacy == via_envelope
    assert isinstance(via_envelope, ExactFileAuthorizationV1)


def test_ae_07_ref_and_id_sources(tmp_path: Path) -> None:
    envelope_file = _write(
        tmp_path, "envelope.json", _envelope_document(_exact_file_payload(), "exact-file-mutation")
    )
    document = json.loads(envelope_file.read_text(encoding="utf-8"))
    via_ref, ref_error = load_cli_authorization(
        file=None, ref="process/authorization/CR-076.json", authorization_id=None,
        legacy_loader=_legacy_exact_file_loader,
        resolve_ref=lambda ref: envelope_file,
    )
    via_id, id_error = load_cli_authorization(
        file=None, ref=None, authorization_id=document["authorization_id"],
        legacy_loader=_legacy_exact_file_loader,
        issuance_lookup=lambda authorization_id: (
            document if authorization_id == document["authorization_id"] else None
        ),
    )
    assert ref_error == "" and id_error == ""
    assert via_ref == via_id and isinstance(via_id, ExactFileAuthorizationV1)


# ---------------------------------------------------------------------------
# GAP-03 治理 kind：scope-amendment / cr-termination / work-status-transition
# ---------------------------------------------------------------------------


def test_ae_07_governance_kinds_adapted(tmp_path: Path) -> None:
    from meta_flow.work.scope_amend import ScopeAmendAuthorizationV1, ScopeAmendAuthorizationV2
    from meta_flow.work.status_transition import WorkStatusTransitionAuthorizationV2

    scope_v1 = {
        "schema_version": 1,
        "operation": "work.scope-amend",
        "authorization_id": "SCOPE-CR076-CLI-V1",
        "cr_id": "CR-076",
        "work_id": "CR-076",
        "predecessor_revision_id": "rev-1",
        "successor_revision_id": "rev-2",
        "predecessor_revision_bytes_digest": D64,
        "authorized_leaves": ["process/changes/CR-076.md"],
        "effective_at": "2026-09-01T00:00:00Z",
    }
    envelope_file = _write(
        tmp_path, "scope.json", _envelope_document(scope_v1, "scope-amendment")
    )
    resolved, error = load_cli_authorization(
        file=envelope_file, ref=None, authorization_id=None, legacy_loader=dict
    )
    assert error == ""
    assert isinstance(resolved, ScopeAmendAuthorizationV1)
    # V2 分派：12 字段（V1 + predecessor/replacement objective，两者必须不同）
    scope_v2 = dict(
        scope_v1,
        schema_version=2,
        predecessor_objective="objective-1",
        replacement_objective="objective-2",
    )
    envelope_file = _write(tmp_path, "scope2.json", _envelope_document(scope_v2, "scope-amendment"))
    resolved, error = load_cli_authorization(
        file=envelope_file, ref=None, authorization_id=None, legacy_loader=dict
    )
    assert error == "" and isinstance(resolved, ScopeAmendAuthorizationV2)

    # work-status-transition：完整闭合 payload（8 字段，status_transition.py:143）
    transition_payload = {
        "schema_version": 2,
        "kind": "WorkStatusTransitionAuthorizationV2",
        "authorization_id": "WT-CR076-CLI-V1",
        "work_id": "CR-076",
        "plan_digest": D64,
        "parent_plan_digest": D64,
        "target_refs": ["process/changes/CR-076.md"],
        "expires_at": "2026-09-02T00:00:00Z",
    }
    envelope_file = _write(
        tmp_path, "transition.json",
        _envelope_document(transition_payload, "work-status-transition"),
    )
    resolved, error = load_cli_authorization(
        file=envelope_file, ref=None, authorization_id=None, legacy_loader=dict
    )
    assert error == ""
    assert isinstance(resolved, WorkStatusTransitionAuthorizationV2)


def test_ae_07_kind_mismatch_blocked(tmp_path: Path) -> None:
    envelope_file = _write(
        tmp_path, "envelope.json", _envelope_document(_exact_file_payload(), "exact-file-mutation")
    )
    authorization, error = load_cli_authorization(
        file=envelope_file, ref=None, authorization_id=None,
        legacy_loader=_legacy_exact_file_loader,
        expected_type=dict,  # 故意不匹配：envelope 解出 ExactFile 而命令期待其他类型
    )
    assert authorization is None
    assert "kind mismatch" in error


def test_ae_07_symlink_rejected(tmp_path: Path) -> None:
    envelope_file = _write(
        tmp_path, "envelope.json", _envelope_document(_exact_file_payload(), "exact-file-mutation")
    )
    link = tmp_path / "link.json"
    link.symlink_to(envelope_file)
    authorization, error = load_cli_authorization(
        file=link, ref=None, authorization_id=None, legacy_loader=_legacy_exact_file_loader
    )
    assert authorization is None
    assert "regular file" in error


# ---------------------------------------------------------------------------
# deprecated 标记（LCQ-01：显式窗口标记；CP8 前删除旧路径）
# ---------------------------------------------------------------------------


def test_ae_07_deprecated_help_marked() -> None:
    # 结构检查：三个迁移面 argparse help 均显式标注 deprecated 窗口
    cli_root = Path(__file__).resolve().parents[2] / "meta_flow"
    cr_cli_text = (cli_root / "workflow" / "cr_cli.py").read_text(encoding="utf-8")
    work_cli_text = (cli_root / "work" / "cli.py").read_text(encoding="utf-8")
    assert cr_cli_text.count(LEGACY_HELP_MARK) >= 2  # scope-amend + status/close/terminate
    assert LEGACY_HELP_MARK in work_cli_text  # status-transition
