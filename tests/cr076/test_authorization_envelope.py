"""STORY-CR076-S02 Feature A targeted 测试：authorization envelope（T1 起增量）。

T1 覆盖：AE-01（闭合）、AE-02（exactly-one 三源等价）、AE-N01..N04
（负向矩阵；N03 的 operation 未注册分支待 T2 registry 落位后补测）。
权威 = cr076-authorization-envelope TEST-PLAN v1.2。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from meta_flow.execution_control.authorization import (
    BLOCKING_CODES,
    ENVELOPE_EXPIRED,
    ENVELOPE_KIND_UNKNOWN,
    ENVELOPE_SCHEMA_INVALID,
    ENVELOPE_SOURCE_NOT_EXACTLY_ONE,
    OPERATION_NOT_REGISTERED,
    AuthorizationBlockedError,
    AuthorizationResolver,
    ensure_not_expired,
    parse_authorization_envelope,
    parse_operation_payload,
    registered_operation_kinds,
)


def _valid_envelope_document() -> dict:
    """合法 envelope（payload 透传任意 versioned operation payload）。"""
    return {
        "schema_version": 1,
        "kind": "authorization-envelope",
        "authorization_id": "AUTH-CR076-TEST-20260901-V1",
        "operation": "exact-file-mutation",
        "target_refs": ["process/changes/CR-076.md"],
        "plan_digest": "0f851dd9b93b765f0000000000000000deadbeef",
        "issued_at": "2026-09-01T00:00:00Z",
        "expires_at": "2099-01-01T00:00:00Z",
        "single_use": True,
        "authorization_source": "typed-user-confirmation",
        "payload": {"schema_version": 1, "kind": "ExactFileAuthorizationV1"},
    }


def _blocked(excinfo: pytest.ExceptionInfo[AuthorizationBlockedError]) -> None:
    """阻断形态断言：code 属冻结枚举、findings typed、mutation=0。"""
    error = excinfo.value
    assert error.code in BLOCKING_CODES
    assert error.findings == [
        {"code": error.code, "severity": "ERROR", "mutation": 0, "detail": error.detail}
    ]


# ---------------------------------------------------------------------------
# AE-01：envelope 闭合校验
# ---------------------------------------------------------------------------


def test_ae_01_valid_envelope_parses_and_roundtrips() -> None:
    document = _valid_envelope_document()
    envelope = parse_authorization_envelope(document)
    assert envelope.authorization_id == document["authorization_id"]
    assert envelope.operation == "exact-file-mutation"
    assert envelope.target_refs == ("process/changes/CR-076.md",)
    assert envelope.single_use is True
    # payload 原样透传（versioned operation payload 零改动）
    assert dict(envelope.payload) == document["payload"]
    assert envelope.as_dict() == document


def test_ae_01_extra_field_rejected() -> None:
    document = _valid_envelope_document()
    document["unexpected_field"] = "x"
    with pytest.raises(AuthorizationBlockedError) as excinfo:
        parse_authorization_envelope(document)
    assert excinfo.value.code == ENVELOPE_SCHEMA_INVALID
    _blocked(excinfo)


@pytest.mark.parametrize(
    "missing_field",
    [
        "schema_version",
        "kind",
        "authorization_id",
        "operation",
        "target_refs",
        "plan_digest",
        "issued_at",
        "expires_at",
        "single_use",
        "authorization_source",
        "payload",
    ],
)
def test_ae_01_missing_field_rejected(missing_field: str) -> None:
    document = _valid_envelope_document()
    del document[missing_field]
    with pytest.raises(AuthorizationBlockedError) as excinfo:
        parse_authorization_envelope(document)
    assert excinfo.value.code == ENVELOPE_SCHEMA_INVALID


def test_ae_01_single_use_false_rejected() -> None:
    document = _valid_envelope_document()
    document["single_use"] = False
    with pytest.raises(AuthorizationBlockedError) as excinfo:
        parse_authorization_envelope(document)
    assert excinfo.value.code == ENVELOPE_SCHEMA_INVALID
    _blocked(excinfo)


def test_ae_01_source_const_enforced() -> None:
    document = _valid_envelope_document()
    document["authorization_source"] = "ambient-approval"
    with pytest.raises(AuthorizationBlockedError) as excinfo:
        parse_authorization_envelope(document)
    assert excinfo.value.code == ENVELOPE_SCHEMA_INVALID


def test_ae_01_bad_timestamp_rejected() -> None:
    document = _valid_envelope_document()
    document["expires_at"] = "not-a-timestamp"
    with pytest.raises(AuthorizationBlockedError) as excinfo:
        parse_authorization_envelope(document)
    assert excinfo.value.code == ENVELOPE_SCHEMA_INVALID


# ---------------------------------------------------------------------------
# AE-02：exactly-one 三源等价
# ---------------------------------------------------------------------------


def test_ae_02_three_sources_equivalent(tmp_path: Path) -> None:
    document = _valid_envelope_document()
    source = tmp_path / "authorization.json"
    source.write_text(json.dumps(document), encoding="utf-8")
    resolver = AuthorizationResolver(
        ref_resolver=lambda ref: source,
        issuance_lookup=lambda authorization_id: (
            document if authorization_id == document["authorization_id"] else None
        ),
    )
    via_file = resolver.resolve(file=source)
    via_ref = resolver.resolve(ref="process/authorization/CR-076.json")
    via_id = resolver.resolve(authorization_id=document["authorization_id"])
    assert via_file == via_ref == via_id


def test_ae_02_none_source_blocked() -> None:
    resolver = AuthorizationResolver()
    with pytest.raises(AuthorizationBlockedError) as excinfo:
        resolver.resolve()
    assert excinfo.value.code == ENVELOPE_SOURCE_NOT_EXACTLY_ONE
    _blocked(excinfo)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"file": "a.json", "ref": "process/x.json"},
        {"ref": "process/x.json", "authorization_id": "AUTH-1"},
        {"file": "a.json", "authorization_id": "AUTH-1"},
        {"file": "a.json", "ref": "process/x.json", "authorization_id": "AUTH-1"},
    ],
)
def test_ae_n01_multi_source_blocked(kwargs: dict) -> None:
    resolver = AuthorizationResolver(
        ref_resolver=lambda ref: Path("unused"),
        issuance_lookup=lambda authorization_id: {},
    )
    with pytest.raises(AuthorizationBlockedError) as excinfo:
        resolver.resolve(**kwargs)
    assert excinfo.value.code == ENVELOPE_SOURCE_NOT_EXACTLY_ONE
    _blocked(excinfo)


def test_ae_02_file_source_unreadable_blocked(tmp_path: Path) -> None:
    resolver = AuthorizationResolver()
    with pytest.raises(AuthorizationBlockedError) as excinfo:
        resolver.resolve(file=tmp_path / "missing.json")
    assert excinfo.value.code == ENVELOPE_SCHEMA_INVALID
    _blocked(excinfo)


# ---------------------------------------------------------------------------
# AE-N03（kind 分支）/ AE-N04（有效期）
# ---------------------------------------------------------------------------


def test_ae_n03_kind_unknown_blocked() -> None:
    # 旧授权文件直喂（无 envelope 层）→ KIND_UNKNOWN 而非 schema 错误
    document = _valid_envelope_document()
    document["kind"] = "ExactFileAuthorizationV1"
    with pytest.raises(AuthorizationBlockedError) as excinfo:
        parse_authorization_envelope(document)
    assert excinfo.value.code == ENVELOPE_KIND_UNKNOWN
    _blocked(excinfo)


def test_ae_n04_expired_envelope_not_consumed() -> None:
    document = _valid_envelope_document()
    document["expires_at"] = "2026-08-31T00:00:00Z"
    envelope = parse_authorization_envelope(document)
    with pytest.raises(AuthorizationBlockedError) as excinfo:
        ensure_not_expired(envelope, now=parse_iso("2026-09-01T00:00:00Z"))
    assert excinfo.value.code == ENVELOPE_EXPIRED
    _blocked(excinfo)


def parse_iso(value: str):
    from datetime import datetime

    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# AE-03 / AE-N03（operation 分支）：registry 分派与既有授权适配（T2）
# ---------------------------------------------------------------------------


def _exact_file_payload() -> dict:
    # ExactFileAuthorizationV1 七字段闭合集（exact_file_transaction.py:194）
    return {
        "schema_version": 1,
        "kind": "ExactFileAuthorizationV1",
        "authorization_id": "EXACTFILE-CR076-TEST-20260901-V1",
        "operation": "exact-file.replace",
        "plan_digest": "a" * 64,
        "target_refs": ["process/changes/CR-076.md"],
        "expires_at": "2099-01-01T00:00:00Z",
    }


def test_ae_03_exact_file_payload_adapts_unchanged() -> None:
    from meta_flow.execution_control.exact_file_transaction import (
        ExactFileAuthorizationV1,
    )

    envelope = parse_authorization_envelope(
        {**_valid_envelope_document(), "payload": _exact_file_payload()}
    )
    resolved = parse_operation_payload(envelope)
    assert isinstance(resolved, ExactFileAuthorizationV1)
    assert resolved.authorization_id == _exact_file_payload()["authorization_id"]


def test_ae_03_registry_contains_builtin_kinds() -> None:
    # T2 内建四项；publication/transport/observation 三项由 T4 注册
    assert set(registered_operation_kinds()) >= {
        "exact-file-mutation",
        "status-sync",
        "release-transition",
        "work-publication-close",
    }


def test_ae_n03_operation_not_registered_blocked() -> None:
    envelope = parse_authorization_envelope(
        {**_valid_envelope_document(), "operation": "not-a-registered-operation"}
    )
    with pytest.raises(AuthorizationBlockedError) as excinfo:
        parse_operation_payload(envelope)
    assert excinfo.value.code == OPERATION_NOT_REGISTERED
    _blocked(excinfo)


def test_ae_n03_legacy_payload_schema_violation_wrapped() -> None:
    # 既有授权 ValueError → ENVELOPE_SCHEMA_INVALID（适配器不重定义字段集）
    bad = _exact_file_payload()
    bad["unexpected"] = "field"
    envelope = parse_authorization_envelope(
        {**_valid_envelope_document(), "payload": bad}
    )
    with pytest.raises(AuthorizationBlockedError) as excinfo:
        parse_operation_payload(envelope)
    assert excinfo.value.code == ENVELOPE_SCHEMA_INVALID
    _blocked(excinfo)


# ---------------------------------------------------------------------------
# AE-04/05 + AE-N05/N08/N09：双账本 attempt 状态机（T3）
# ---------------------------------------------------------------------------

from meta_flow.execution_control.authorization import (  # noqa: E402
    ATTEMPT_STARTED,
    ATTEMPT_TERMINAL_STATES,
    ENVELOPE_ALREADY_CONSUMED,
    OID_DRIFT_DETECTED,
    PREDECESSOR_DIGEST_MISMATCH,
    PREDECESSOR_RECEIPT_MISSING,
    TARGET_NAMESPACE_MISMATCH,
    TOCTOU_PREIMAGE_DRIFT,
    AuthorizationLedger,
    authorization_digest,
    validate_envelope_context,
)

_PREIMAGES = {"process/changes/CR-076.md": "b" * 64}


def _consumable_envelope(payload: dict | None = None) -> object:
    document = _valid_envelope_document()
    if payload is not None:
        document["payload"] = payload
    return parse_authorization_envelope(document)


def test_ae_05_ledger_lifecycle_started_then_terminal(tmp_path: Path) -> None:
    # AE-05：register_issuance → consume 登记先于副作用（STARTED）→ terminal receipt
    ledger = AuthorizationLedger(root=tmp_path)
    envelope = _consumable_envelope()
    digest = ledger.register_issuance(envelope)
    assert digest == authorization_digest(envelope)
    assert ledger.lookup_issuance_document(envelope.authorization_id) == envelope.as_dict()

    started = ledger.consume(
        envelope, attempt_id="ATT-1", preimage_digests=_PREIMAGES
    )
    assert started["attempt_state"] == ATTEMPT_STARTED
    assert started["preimage_digests"] == _PREIMAGES
    # issuance 只记签发；consumption 首行即 STARTED（登记先于副作用）
    assert ledger.attempts(digest) == [started]

    terminal = ledger.complete_attempt("ATT-1", "SUCCEEDED")
    assert terminal["attempt_state"] == "SUCCEEDED"
    rows = ledger.attempts(digest)
    assert [r["attempt_state"] for r in rows] == ["STARTED", "SUCCEEDED"]
    # append-only：terminal 行不改写 STARTED 行
    assert ledger.attempt_by_id("ATT-1")["attempt_state"] == "SUCCEEDED"


def test_ae_04_predecessor_receipt_chain(tmp_path: Path) -> None:
    # AE-04：predecessor_attempt + predecessor_digest 通过才可消费（链式授权）
    ledger = AuthorizationLedger(root=tmp_path)
    first = _consumable_envelope()
    ledger.consume(first, attempt_id="ATT-1", preimage_digests=_PREIMAGES)
    ledger.complete_attempt("ATT-1", "SUCCEEDED")

    successor_payload = {
        "schema_version": 1,
        "kind": "StatusSyncAuthorization",
        "predecessor_attempt": "ATT-1",
        "predecessor_digest": authorization_digest(first),
    }
    second_doc = _valid_envelope_document()
    second_doc["authorization_id"] = "AUTH-CR076-TEST-20260901-V2"
    second_doc["payload"] = successor_payload
    second = parse_authorization_envelope(second_doc)
    started = ledger.consume(second, attempt_id="ATT-2", preimage_digests=_PREIMAGES)
    assert started["attempt_state"] == ATTEMPT_STARTED


def test_ae_n08_predecessor_missing_and_digest_mismatch(tmp_path: Path) -> None:
    ledger = AuthorizationLedger(root=tmp_path)
    # 缺失：前驱 attempt 不在账本
    orphan = _consumable_envelope(
        {"schema_version": 1, "predecessor_attempt": "NO-SUCH-ATT"}
    )
    with pytest.raises(AuthorizationBlockedError) as excinfo:
        ledger.consume(orphan, attempt_id="ATT-X", preimage_digests=_PREIMAGES)
    assert excinfo.value.code == PREDECESSOR_RECEIPT_MISSING
    _blocked(excinfo)
    assert ledger.consumption_path.exists() is False  # mutation=0

    # 不匹配：前驱存在但 digest 与声明不符
    real = _consumable_envelope()
    ledger.consume(real, attempt_id="ATT-1", preimage_digests=_PREIMAGES)
    mismatch = _consumable_envelope(
        {
            "schema_version": 1,
            "predecessor_attempt": "ATT-1",
            "predecessor_digest": "0" * 64,
        }
    )
    with pytest.raises(AuthorizationBlockedError) as excinfo:
        ledger.consume(mismatch, attempt_id="ATT-Y", preimage_digests=_PREIMAGES)
    assert excinfo.value.code == PREDECESSOR_DIGEST_MISMATCH
    _blocked(excinfo)


def test_ae_n05_reuse_blocked_mutation_zero(tmp_path: Path) -> None:
    # AE-N05：同 envelope 二次消费阻断，且不追加任何行
    ledger = AuthorizationLedger(root=tmp_path)
    envelope = _consumable_envelope()
    ledger.consume(envelope, attempt_id="ATT-1", preimage_digests=_PREIMAGES)
    before = ledger._rows(ledger.consumption_path)
    with pytest.raises(AuthorizationBlockedError) as excinfo:
        ledger.consume(envelope, attempt_id="ATT-2", preimage_digests=_PREIMAGES)
    assert excinfo.value.code == ENVELOPE_ALREADY_CONSUMED
    _blocked(excinfo)
    assert ledger._rows(ledger.consumption_path) == before


def test_ae_n09_toctou_preimage_drift(tmp_path: Path) -> None:
    # AE-N09：plan 期与 consume 期 preimage 摘要不一致 → 阻断且零行
    ledger = AuthorizationLedger(root=tmp_path)
    envelope = _consumable_envelope()
    with pytest.raises(AuthorizationBlockedError) as excinfo:
        ledger.consume(
            envelope,
            attempt_id="ATT-1",
            preimage_digests={"process/changes/CR-076.md": "c" * 64},
            expected_preimage_digests=_PREIMAGES,
        )
    assert excinfo.value.code == TOCTOU_PREIMAGE_DRIFT
    _blocked(excinfo)
    assert ledger.consumption_path.exists() is False
    # 阻断未消费：同授权可重试（TOCTOU 阻断不是消费）
    ledger.consume(envelope, attempt_id="ATT-1", preimage_digests=_PREIMAGES)


def test_ae_n09_expired_at_consume_not_consumed(tmp_path: Path) -> None:
    # 过期在 consume 时重验（ensure_not_expired 内嵌）：阻断且零行
    document = _valid_envelope_document()
    document["expires_at"] = "2026-08-31T00:00:00Z"
    envelope = parse_authorization_envelope(document)
    ledger = AuthorizationLedger(root=tmp_path)
    with pytest.raises(AuthorizationBlockedError) as excinfo:
        ledger.consume(
            envelope,
            attempt_id="ATT-1",
            preimage_digests=_PREIMAGES,
            now=parse_iso("2026-09-01T00:00:00Z"),
        )
    assert excinfo.value.code == ENVELOPE_EXPIRED
    assert ledger.consumption_path.exists() is False


# ---------------------------------------------------------------------------
# AE-N06/N07：namespace 与双仓 OID 有效性检查
# ---------------------------------------------------------------------------


def test_ae_n06_target_namespace_mismatch() -> None:
    envelope = _consumable_envelope()
    with pytest.raises(AuthorizationBlockedError) as excinfo:
        validate_envelope_context(
            envelope, allowed_target_refs=("process/changes/CR-075.md",)
        )
    assert excinfo.value.code == TARGET_NAMESPACE_MISMATCH
    _blocked(excinfo)
    # 命中 namespace 时不阻断
    validate_envelope_context(
        envelope, allowed_target_refs=("process/changes/CR-076.md",)
    )


def test_ae_n07_oid_drift_detected() -> None:
    envelope = _consumable_envelope(
        {"schema_version": 1, "expected_release_oid": "oid-release-a"}
    )
    with pytest.raises(AuthorizationBlockedError) as excinfo:
        validate_envelope_context(envelope, current_release_oid="oid-release-b")
    assert excinfo.value.code == OID_DRIFT_DETECTED
    _blocked(excinfo)
    validate_envelope_context(envelope, current_release_oid="oid-release-a")


# ---------------------------------------------------------------------------
# AE-FI1..04：崩溃断点与 terminal 语义（ADR-076-07）
# ---------------------------------------------------------------------------


def test_ae_fi1_started_without_terminal_counts_consumed(tmp_path: Path) -> None:
    # FI1：consume 后、副作用完成前崩溃（STARTED 无 terminal）→ 视为已消费
    ledger = AuthorizationLedger(root=tmp_path)
    envelope = _consumable_envelope()
    ledger.consume(envelope, attempt_id="ATT-1", preimage_digests=_PREIMAGES)
    with pytest.raises(AuthorizationBlockedError) as excinfo:
        ledger.consume(envelope, attempt_id="ATT-2", preimage_digests=_PREIMAGES)
    assert excinfo.value.code == ENVELOPE_ALREADY_CONSUMED
    _blocked(excinfo)


def test_ae_fi2_terminal_after_crash_before_receipt(tmp_path: Path) -> None:
    # FI2：副作用完成、terminal 行缺失（崩溃）→ 允许从 STARTED 补记 terminal
    ledger = AuthorizationLedger(root=tmp_path)
    envelope = _consumable_envelope()
    ledger.consume(envelope, attempt_id="ATT-1", preimage_digests=_PREIMAGES)
    ledger.complete_attempt("ATT-1", "PARTIAL")  # 补记允许（含 PARTIAL/FAILED）
    assert ledger.attempt_by_id("ATT-1")["attempt_state"] == "PARTIAL"


def test_ae_fi3_terminal_append_is_final(tmp_path: Path) -> None:
    # FI3：terminal 已存在 → 编程错误（ValueError），不静默改写历史行
    ledger = AuthorizationLedger(root=tmp_path)
    envelope = _consumable_envelope()
    ledger.consume(envelope, attempt_id="ATT-1", preimage_digests=_PREIMAGES)
    ledger.complete_attempt("ATT-1", "SUCCEEDED")
    with pytest.raises(ValueError, match="already terminal"):
        ledger.complete_attempt("ATT-1", "FAILED")
    assert ledger.attempt_by_id("ATT-1")["attempt_state"] == "SUCCEEDED"


def test_ae_fi4_invalid_outcome_and_unknown_attempt(tmp_path: Path) -> None:
    # FI4：非法 outcome / 未知 attempt → ValueError（非授权阻断）
    ledger = AuthorizationLedger(root=tmp_path)
    with pytest.raises(ValueError, match="attempt not found in ledger"):
        ledger.complete_attempt("NO-ATT", "SUCCEEDED")
    envelope = _consumable_envelope()
    ledger.consume(envelope, attempt_id="ATT-1", preimage_digests=_PREIMAGES)
    with pytest.raises(ValueError, match="outcome must be one of"):
        ledger.complete_attempt("ATT-1", "RETRYING")
    assert ATTEMPT_TERMINAL_STATES == ("SUCCEEDED", "PARTIAL", "FAILED")
