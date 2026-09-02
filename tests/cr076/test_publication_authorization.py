"""STORY-CR076-S02 Feature A targeted 测试：publication/observation payload 与 producer。

覆盖 TEST-PLAN v1.2：AE-06（publication payload 闭合）、AE-N10（digest 口径）、
AE-08（producer 两 builder + 崩溃补记幂等）、AE-09（observation 合同/实测解析
闭合）、AE-N11..N18（观测失败矩阵）。权威 = Feature DESIGN v1.2 数据模型节。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from meta_flow.release.publication_authorization import (
    BLOCKED,
    NOT_VERIFIED,
    PUBLICATION_RECEIPTS_REF,
    PUBLISHED_VERIFIED_RECEIPTS_REF,
    VERIFIED,
    ObservationAuthorizationV1,
    PublicationMutationAuthorizationV1,
    PublishedVerifiedReceiptV1,
    RemoteObservationResultV1,
    TransportMutationAuthorizationV1,
    build_publication_receipt,
    build_published_verified_receipt,
)

D64 = "d" * 64
E64 = "e" * 64
SHA1_40 = "a" * 40


def _publication_payload(**overrides: object) -> dict:
    payload = {
        "schema_version": 1,
        "kind": "publication-mutation-authorization",
        "target_kind": "registry-upload",
        "target_identity": "pypi/meta-flow",
        "remote_namespace": "meta-flow",
        "remote_name": "meta-flow",
        "remote_version": "6.0.0",
        "consumer_accepted_digest": D64,
    }
    payload.update(overrides)
    return {k: v for k, v in payload.items() if v is not None}


# ---------------------------------------------------------------------------
# AE-06 / AE-N10：PublicationMutationAuthorizationV1 闭合与 digest 口径
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("target_kind", ["git-tag", "github-release", "registry-upload", "asset-upload"])
def test_ae_06_all_target_kinds_parse(target_kind: str) -> None:
    resolved = PublicationMutationAuthorizationV1.from_mapping(
        _publication_payload(target_kind=target_kind)
    )
    assert resolved.target_kind == target_kind
    assert resolved.consumer_accepted_digest == D64


def test_ae_06_predecessor_attempt_links() -> None:
    resolved = PublicationMutationAuthorizationV1.from_mapping(
        _publication_payload(predecessor_attempt="PUB-1")
    )
    assert resolved.predecessor_attempt == "PUB-1"
    # 可空：缺省 = None
    assert (
        PublicationMutationAuthorizationV1.from_mapping(_publication_payload()).predecessor_attempt
        is None
    )


def test_ae_n10_bad_target_kind_and_short_digest_rejected() -> None:
    with pytest.raises(ValueError, match="target_kind"):
        PublicationMutationAuthorizationV1.from_mapping(
            _publication_payload(target_kind="ftp-upload")
        )
    # 非 git-tag 口径：40 hex 拒绝（64 hex 权威，40 仅 Git SHA-1 OID）
    with pytest.raises(ValueError, match="consumer_accepted_digest"):
        PublicationMutationAuthorizationV1.from_mapping(
            _publication_payload(consumer_accepted_digest=SHA1_40)
        )
    with pytest.raises(ValueError, match="consumer_accepted_digest"):
        PublicationMutationAuthorizationV1.from_mapping(
            _publication_payload(consumer_accepted_digest="short")
        )


def test_ae_06_git_tag_accepts_sha1_oid() -> None:
    resolved = PublicationMutationAuthorizationV1.from_mapping(
        _publication_payload(target_kind="git-tag", consumer_accepted_digest=SHA1_40)
    )
    assert resolved.consumer_accepted_digest == SHA1_40


@pytest.mark.parametrize(
    "mutation",
    [
        {"unexpected": "field"},
        {"target_identity": None},
        {"remote_namespace": None},
        {"remote_name": None},
        {"remote_version": None},
        {"schema_version": 2},
        {"kind": "publication-mutation"},
    ],
)
def test_ae_06_closed_field_set(mutation: dict) -> None:
    with pytest.raises(ValueError):
        PublicationMutationAuthorizationV1.from_mapping(_publication_payload(**mutation))


def test_ae_06_transport_payload_closed() -> None:
    resolved = TransportMutationAuthorizationV1.from_mapping(
        {
            "schema_version": 1,
            "kind": "transport-mutation",
            "target_refs": ["process/release/bundle.json"],
            "preimage_digests": {"process/release/bundle.json": D64},
        }
    )
    assert resolved.target_refs == ("process/release/bundle.json",)
    assert resolved.preimage_digests == {"process/release/bundle.json": D64}
    with pytest.raises(ValueError, match="unexpected"):
        TransportMutationAuthorizationV1.from_mapping(
            {
                "schema_version": 1,
                "kind": "transport-mutation",
                "target_refs": ["a"],
                "preimage_digests": {"a": D64},
                "extra": 1,
            }
        )
    with pytest.raises(ValueError, match="preimage_digests"):
        TransportMutationAuthorizationV1.from_mapping(
            {"schema_version": 1, "kind": "transport-mutation", "target_refs": ["a"], "preimage_digests": {}}
        )


# ---------------------------------------------------------------------------
# AE-09：ObservationAuthorizationV1 / RemoteObservationResultV1 解析闭合
# ---------------------------------------------------------------------------


def _observation_auth_doc(**overrides: object) -> dict:
    document = {
        "schema_version": 1,
        "kind": "observation-verification",
        "target_set": ["target-alpha"],
        "publication_receipt_digest_set": [D64],
        "expected_accepted_digest_set": {"target-alpha": [D64]},
        "freshness_seconds": 3600,
        "principal_uid": "principal-1",
        "device_uid": "device-1",
        "project_uid": "project-1",
        "not_before": "2026-09-01T00:00:00Z",
        "not_after": "2026-09-02T00:00:00Z",
        "single_use": True,
    }
    document.update(overrides)
    return {k: v for k, v in document.items() if v is not None}


def _observation_result_doc(**overrides: object) -> dict:
    document = {
        "observed_digest_sets": {"target-alpha": [D64]},
        "observed_at": "2026-09-01T06:00:00Z",
        "command_identity": "observe://registry/read-only",
        "attempt_id": "OBS-1",
    }
    document.update(overrides)
    return {k: v for k, v in document.items() if v is not None}


def test_ae_09_observation_authorization_parses() -> None:
    resolved = ObservationAuthorizationV1.from_mapping(_observation_auth_doc())
    assert resolved.target_set == ("target-alpha",)
    assert resolved.expected_accepted_digest_set == {"target-alpha": (D64,)}
    assert resolved.freshness_seconds == 3600
    assert resolved.single_use is True


@pytest.mark.parametrize(
    "mutation",
    [
        {"single_use": False},
        {"freshness_seconds": 0},
        {"freshness_seconds": "3600"},
        {"expected_accepted_digest_set": {"target-other": [D64]}},
        {"not_after": "2026-08-31T00:00:00Z"},  # 早于 not_before
        {"not_before": "not-a-timestamp"},
        {"principal_uid": None},
        {"unexpected": "field"},
        {"target_set": []},
    ],
)
def test_ae_09_observation_authorization_closed(mutation: dict) -> None:
    with pytest.raises(ValueError):
        ObservationAuthorizationV1.from_mapping(_observation_auth_doc(**mutation))


def test_ae_09_remote_observation_result_parses() -> None:
    resolved = RemoteObservationResultV1.from_mapping(_observation_result_doc())
    assert resolved.observed_digest_sets == {"target-alpha": (D64,)}
    assert resolved.attempt_id == "OBS-1"
    with pytest.raises(ValueError, match="unexpected"):
        RemoteObservationResultV1.from_mapping(_observation_result_doc(tampered=1))
    with pytest.raises(ValueError, match="observed_at"):
        RemoteObservationResultV1.from_mapping(_observation_result_doc(observed_at="nope"))


# ---------------------------------------------------------------------------
# AE-08：producer 两 builder（成功路径 + 崩溃补记幂等）
# ---------------------------------------------------------------------------


def _now(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


@pytest.fixture
def chain(tmp_path: Path) -> dict:
    """happy-path 三件套：一条 SUCCEEDED publication receipt + 匹配的观测合同/实测。"""
    receipts_path = tmp_path / "publication-receipts.ndjson"
    receipt, ref = build_publication_receipt(
        receipts_path=receipts_path, attempt_id="PUB-1", target_kind="registry-upload",
        target_identity="target-alpha", outcome="SUCCEEDED", digests=[D64],
        now=_now("2026-09-01T05:00:00Z"),
    )
    return {
        "receipts_path": receipts_path,
        "receipt": receipt,
        "ref": ref,
        "auth": ObservationAuthorizationV1.from_mapping(
            _observation_auth_doc(publication_receipt_digest_set=[receipt.receipt_digest])
        ),
        "result": RemoteObservationResultV1.from_mapping(_observation_result_doc()),
    }


def test_ae_08_publication_receipt_appends_with_ref(chain: dict) -> None:
    receipt, ref = chain["receipt"], chain["ref"]
    assert ref == PUBLICATION_RECEIPTS_REF
    assert len(receipt.receipt_digest) == 64
    assert receipt.outcome == "SUCCEEDED"
    rows = [json.loads(line) for line in chain["receipts_path"].read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1 and rows[0]["attempt_id"] == "PUB-1"


def test_ae_08_receipt_retry_after_crash_is_idempotent(chain: dict) -> None:
    # 副作用后崩溃、receipt 未落盘 → 重调补记：内容一致返回既有行不重复 append
    again, ref = build_publication_receipt(
        receipts_path=chain["receipts_path"], attempt_id="PUB-1", target_kind="registry-upload",
        target_identity="target-alpha", outcome="SUCCEEDED", digests=[D64],
        now=_now("2026-09-01T05:30:00Z"),
    )
    assert again.receipt_digest == chain["receipt"].receipt_digest
    assert ref == PUBLICATION_RECEIPTS_REF
    lines = chain["receipts_path"].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1  # 未新增行


def test_ae_08_conflicting_receipt_for_same_attempt_rejected(chain: dict) -> None:
    with pytest.raises(ValueError, match="already exists"):
        build_publication_receipt(
            receipts_path=chain["receipts_path"], attempt_id="PUB-1", target_kind="registry-upload",
            target_identity="target-alpha", outcome="FAILED", digests=[D64],
        )


def test_ae_08_partial_outcome_receipt_allowed(tmp_path: Path) -> None:
    receipts_path = tmp_path / "publication-receipts.ndjson"
    receipt, _ = build_publication_receipt(
        receipts_path=receipts_path, attempt_id="PUB-P", target_kind="asset-upload",
        target_identity="target-beta", outcome="PARTIAL", digests=[E64],
    )
    assert receipt.outcome == "PARTIAL"
    with pytest.raises(ValueError, match="outcome"):
        build_publication_receipt(
            receipts_path=receipts_path, attempt_id="PUB-X", target_kind="asset-upload",
            target_identity="target-beta", outcome="RETRYING", digests=[E64],
        )


def test_ae_08_verified_happy_path(chain: dict, tmp_path: Path) -> None:
    verified_path = tmp_path / "published-verified-receipts.ndjson"
    receipt, ref = build_published_verified_receipt(
        receipts_path=verified_path, authorization=chain["auth"],
        publication_receipts=[chain["receipt"].as_dict()],
        observation_result=chain["result"], authorization_attempt_id="OBS-1",
        now=_now("2026-09-01T06:30:00Z"),
    )
    assert isinstance(receipt, PublishedVerifiedReceiptV1)
    assert receipt.verification == VERIFIED
    assert receipt.mismatched_targets == ()
    assert receipt.observation_attempt_id == "OBS-1"
    assert ref == PUBLISHED_VERIFIED_RECEIPTS_REF
    rows = [json.loads(line) for line in verified_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1 and rows[0]["verification"] == VERIFIED


# ---------------------------------------------------------------------------
# AE-N11..N18：观测失败矩阵（任何违规不得构造 VERIFIED）
# ---------------------------------------------------------------------------


def _build_verified(chain: dict, tmp_path: Path, **overrides: object):
    kwargs = {
        "receipts_path": tmp_path / "published-verified-receipts.ndjson",
        "authorization": chain["auth"],
        "publication_receipts": [chain["receipt"].as_dict()],
        "observation_result": chain["result"],
        "authorization_attempt_id": "OBS-1",
        "now": _now("2026-09-01T06:30:00Z"),
    }
    kwargs.update(overrides)
    return build_published_verified_receipt(**kwargs)


def test_ae_n11_publication_receipt_digest_set_mismatch(chain: dict, tmp_path: Path) -> None:
    # 前驱错误：授权声明的 digest-set 与实际 receipts 不匹配
    wrong = ObservationAuthorizationV1.from_mapping(
        _observation_auth_doc(publication_receipt_digest_set=[E64])
    )
    receipt, _ = _build_verified(chain, tmp_path, authorization=wrong)
    assert receipt.verification == BLOCKED
    assert receipt.reasons and "does not match" in receipt.reasons[0]


def test_ae_n12_observed_digest_set_mismatch_not_verified(chain: dict, tmp_path: Path) -> None:
    for mutated in (
        {"target-alpha": [E64]},        # 错 digest
        {"target-alpha": [D64, E64]},   # 多
        {"target-alpha": []},           # 少
        {"target-alpha": [D64, D64]},   # 重复
    ):
        result = RemoteObservationResultV1.from_mapping(
            _observation_result_doc(observed_digest_sets=mutated)
        ) if mutated["target-alpha"] else None
        if result is None:
            continue  # 空列表在解析层已拒绝（闭合校验），不进入 builder
        receipt, _ = _build_verified(chain, tmp_path, observation_result=result)
        assert receipt.verification == NOT_VERIFIED, mutated
        assert receipt.mismatched_targets == ("target-alpha",)
        assert receipt.verification != VERIFIED


def test_ae_n13_freshness_window_exceeded(chain: dict, tmp_path: Path) -> None:
    receipt, _ = _build_verified(chain, tmp_path, now=_now("2026-09-01T08:00:00Z"))
    assert receipt.verification == NOT_VERIFIED
    assert "freshness" in receipt.reasons[0]


def test_ae_n14_mismatch_never_verified(chain: dict, tmp_path: Path) -> None:
    result = RemoteObservationResultV1.from_mapping(
        _observation_result_doc(observed_digest_sets={"target-alpha": [E64]})
    )
    receipt, _ = _build_verified(chain, tmp_path, observation_result=result)
    assert receipt.verification is not VERIFIED and receipt.verification == NOT_VERIFIED


def test_ae_n15_observed_missing_target_blocked(chain: dict, tmp_path: Path) -> None:
    result = RemoteObservationResultV1.from_mapping(
        _observation_result_doc(observed_digest_sets={"target-other": [D64]})
    )
    receipt, _ = _build_verified(chain, tmp_path, observation_result=result)
    assert receipt.verification == BLOCKED
    assert "missing target" in receipt.reasons[0]


def test_ae_n16_tampered_result_attempt_blocked(chain: dict, tmp_path: Path) -> None:
    # result 被篡改：attempt 字段与真实观测产出不符 → 三方不一致路径阻断
    tampered = RemoteObservationResultV1.from_mapping(
        _observation_result_doc(attempt_id="OBS-EVIL")
    )
    receipt, _ = _build_verified(chain, tmp_path, observation_result=tampered)
    assert receipt.verification == BLOCKED
    assert "not bound" in receipt.reasons[0]


def test_ae_n17_no_observation_result_blocked(chain: dict, tmp_path: Path) -> None:
    receipt, _ = _build_verified(chain, tmp_path, observation_result=None)
    assert receipt.verification == BLOCKED
    assert "no observation result" in receipt.reasons[0]


def test_ae_n18_attempt_three_way_mismatch_blocked(chain: dict, tmp_path: Path) -> None:
    # 授权消费 attempt 与 result.attempt_id 不一致（三方校验失败）
    receipt, _ = _build_verified(chain, tmp_path, authorization_attempt_id="OBS-OTHER")
    assert receipt.verification == BLOCKED
    assert "not bound" in receipt.reasons[0]


def test_ae_n18_unbound_attempt_defaults_to_blocked(chain: dict, tmp_path: Path) -> None:
    # authorization_attempt_id 缺省（None）＝无法证明三方一致 → 安全默认阻断
    receipt, _ = _build_verified(chain, tmp_path, authorization_attempt_id=None)
    assert receipt.verification == BLOCKED


def test_ae_n15_receipts_not_covering_target_set_blocked(chain: dict, tmp_path: Path) -> None:
    # receipts 与 target_set 不一致（target 错位）→ BLOCKED
    receipt, _ = _build_verified(
        chain, tmp_path, publication_receipts=[{**chain["receipt"].as_dict(), "target_identity": "target-other"}]
    )
    assert receipt.verification == BLOCKED
