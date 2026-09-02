"""STORY-CR076-S03 targeted 测试：transport receipt、三端相等与重试合同
（BIT-05/06 + BIT-N03/N07）。

权威 = cr076-bundle-identity-transport TEST-PLAN + LLD v1.2 §6/§7/ADR-07。
"""

from __future__ import annotations

from copy import deepcopy

import pytest

from meta_flow.release.asset_discovery import verify_three_way_preimage
from meta_flow.release.bundle_identity import (
    ZERO_DIGEST_PLACEHOLDER,
    build_base_bundle_manifest,
    build_transport_receipt,
    derive_sidecar_preimage,
    validate_transport_receipt,
    verify_predecessor_chain,
)

_OK = "a" * 64
_OID1, _OID2 = "1" * 40, "2" * 40
_TS1, _TS2 = "2026-09-01T08:00:00Z", "2026-09-01T09:30:00Z"
_AUTH1, _AUTH2 = "sha256:" + "b" * 64, "sha256:" + "c" * 64
_NAMING = {"project_name": "meta-flow", "wheel_tag": "py3-none-any", "normalized_prefix": "meta_flow-1.2.3"}
_ASSETS = {"wheel": _OK, "sdist": "b" * 64, "build_receipt": "c" * 64, "sidecar": "d" * 64}


def _manifest() -> dict[str, object]:
    skeleton = {
        "schema_version": 1,
        "kind": "ImmutableBaseBundleManifestV1",
        "bundle_id": ZERO_DIGEST_PLACEHOLDER,
        "bundle_digest": ZERO_DIGEST_PLACEHOLDER,
        "semver": "1.2.3",
        "source": {"release_oid": _OID1, "process_oid": _OID2, "frozen_at": _TS1},
        "assets": {"wheel": _OK, "sdist": "b" * 64, "build_receipt": "c" * 64, "sidecar": ZERO_DIGEST_PLACEHOLDER},
        "naming": _NAMING,
        "built_at": _TS1,
        "build_authorization_digest": _AUTH1,
    }
    assets = dict(_ASSETS, sidecar=derive_sidecar_preimage(skeleton))
    return build_base_bundle_manifest(
        release_oid=_OID1,
        process_oid=_OID2,
        frozen_at=_TS1,
        semver="1.2.3",
        asset_digests=assets,
        naming=_NAMING,
        built_at=_TS1,
        build_authorization_digest=_AUTH1,
    )


def test_bit05_three_way_equal_and_outcomes() -> None:
    m = _manifest()
    for outcome, codes in (
        ("DELIVERED", ()),
        ("PARTIAL", ("CARRIER-PARTIAL",)),
        ("FAILED", ("CONSUMER-REJECTED", "BYTES-DAMAGED")),
    ):
        receipt = build_transport_receipt(
            predecessor=m,
            attempt_id=f"attempt-{outcome}",
            transported_assets=_ASSETS,
            transported_at=_TS1,
            transport_authorization_digest=_AUTH1,
            outcome=outcome,
            reason_codes=codes,
        )
        assert receipt["outcome"] == outcome
        assert receipt["reason_codes"] == sorted(codes)
        # 三端物理域相等（出口==载体==落盘==receipt 断言，DQ-07）。
        assert verify_three_way_preimage(
            exported=_ASSETS, carrier=_ASSETS, landed=_ASSETS, receipt=receipt
        ) == ()
        assert verify_predecessor_chain([m, receipt]) == ()


def test_bit05_reason_codes_rules() -> None:
    m = _manifest()

    def build(outcome: str, codes: object) -> None:
        build_transport_receipt(
            predecessor=m,
            attempt_id="attempt-x",
            transported_assets=_ASSETS,
            transported_at=_TS1,
            transport_authorization_digest=_AUTH1,
            outcome=outcome,
            reason_codes=codes,  # type: ignore[arg-type]
        )

    # PARTIAL/FAILED 必附非空 reason_codes；DELIVERED 禁 reason_codes。
    with pytest.raises(ValueError, match="RECEIPT-REASON-CODES-REQUIRED"):
        build("PARTIAL", ())
    with pytest.raises(ValueError, match="RECEIPT-REASON-CODES-REQUIRED"):
        build("FAILED", None)
    with pytest.raises(ValueError, match="RECEIPT-REASON-CODES-REQUIRED"):
        build("DELIVERED", ("ANY-CODE",))
    # 格式：free-text 拒绝；超 16 项拒绝；重复去重排序。
    with pytest.raises(ValueError, match="RECEIPT-REASON-CODES-REQUIRED"):
        build("PARTIAL", ("free text",))
    with pytest.raises(ValueError, match="RECEIPT-REASON-CODES-REQUIRED"):
        build("PARTIAL", tuple(f"CODE-{i:02d}" for i in range(17)))
    deduped = build_transport_receipt(
        predecessor=m, attempt_id="attempt-d",
        transported_assets=_ASSETS, transported_at=_TS1,
        transport_authorization_digest=_AUTH1, outcome="PARTIAL",
        reason_codes=["B-CODE", "A-CODE", "A-CODE"],
    )
    assert deduped["reason_codes"] == ["A-CODE", "B-CODE"]


def test_bit06_retry_is_new_attempt_new_authorization() -> None:
    m = _manifest()
    # 第一次 attempt PARTIAL（真实传输有副作用即消费授权，ADR-07）。
    r1 = build_transport_receipt(
        predecessor=m, attempt_id="attempt-1",
        transported_assets=_ASSETS, transported_at=_TS1,
        transport_authorization_digest=_AUTH1, outcome="PARTIAL",
        reason_codes=["CARRIER-PARTIAL"],
    )
    r1_frozen = deepcopy(r1)
    # 重试 = 新授权 + 新 attempt + 新 receipt；predecessor_attempt 链接失败 attempt。
    r2 = build_transport_receipt(
        predecessor=m, attempt_id="attempt-2",
        transported_assets=_ASSETS, transported_at=_TS2,
        transport_authorization_digest=_AUTH2, outcome="DELIVERED",
        predecessor_attempt="attempt-1",
    )
    assert r2["predecessor_attempt"] == "attempt-1"
    assert r2["transport_authorization_digest"] == _AUTH2 != r1["transport_authorization_digest"]
    assert r2["receipt_digest"] != r1["receipt_digest"]
    # 旧 receipt 不删除、不修改（append-only 语义：bytes 级不变）。
    assert r1 == r1_frozen
    assert validate_transport_receipt(r1) == r1_frozen
    # 两 receipt 的对象链前驱都是基座 manifest。
    assert verify_predecessor_chain([m, r1]) == ()
    assert verify_predecessor_chain([m, r2]) == ()


def test_n03_consumer_bytes_flipped() -> None:
    m = _manifest()
    receipt = build_transport_receipt(
        predecessor=m, attempt_id="attempt-1",
        transported_assets=_ASSETS, transported_at=_TS1,
        transport_authorization_digest=_AUTH1, outcome="FAILED",
        reason_codes=["TRANSPORT-BYTES-CONFLICT"],
    )
    # consumer 落盘 wheel bytes 翻转 1 字节 → 物理域 digest 变。
    landed = dict(_ASSETS, wheel="e" * 64)
    conflicts = verify_three_way_preimage(
        exported=_ASSETS, carrier=_ASSETS, landed=landed, receipt=receipt
    )
    assert conflicts == ("TRANSPORT-BYTES-MISMATCH:landed:wheel",)
    # 出口端 / 载体端任一失配同样按 source 定位。
    assert verify_three_way_preimage(
        exported=dict(_ASSETS, sdist="f" * 64), carrier=_ASSETS, landed=_ASSETS, receipt=receipt
    ) == ("TRANSPORT-BYTES-MISMATCH:exported:sdist",)
    assert verify_three_way_preimage(
        exported=_ASSETS, carrier=dict(_ASSETS, build_receipt="7" * 64), landed=_ASSETS, receipt=receipt
    ) == ("TRANSPORT-BYTES-MISMATCH:carrier:build_receipt",)
    # 三端存在不等 → 不得签 DELIVERED（失败路径 receipt 保持 FAILED + codes）。


def test_n07_missing_fields_rejected() -> None:
    m = _manifest()
    receipt = build_transport_receipt(
        predecessor=m, attempt_id="attempt-1",
        transported_assets=_ASSETS, transported_at=_TS1,
        transport_authorization_digest=_AUTH1, outcome="DELIVERED",
    )
    # 缺 attempt_id → schema 分支校验拒绝（非裸 KeyError）。
    missing_attempt = {k: v for k, v in receipt.items() if k != "attempt_id"}
    with pytest.raises(ValueError, match="MANIFEST-FIELD-INVALID"):
        validate_transport_receipt(missing_attempt)
    # 缺 schema_version / kind / 任意必填键同样拒绝。
    for key in ("schema_version", "kind", "receipt_digest", "outcome", "transported_assets"):
        stripped = {k: v for k, v in receipt.items() if k != key}
        with pytest.raises(ValueError, match="MANIFEST-FIELD-INVALID"):
            validate_transport_receipt(stripped)
    # 额外字段拒绝；自 digest 失配拒绝；非法 outcome 拒绝。
    extra = dict(receipt, extra=1)
    with pytest.raises(ValueError, match="unexpected fields"):
        validate_transport_receipt(extra)
    tampered = dict(receipt)
    tampered["transported_at"] = _TS2
    with pytest.raises(ValueError, match="receipt_digest does not match"):
        validate_transport_receipt(tampered)
    with pytest.raises(ValueError, match="MANIFEST-FIELD-INVALID"):
        build_transport_receipt(
            predecessor=m, attempt_id="attempt-bad",
            transported_assets=_ASSETS, transported_at=_TS1,
            transport_authorization_digest=_AUTH1, outcome="LOST",
        )
