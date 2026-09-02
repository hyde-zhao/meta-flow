"""STORY-CR076-S04 targeted 测试：InstallationReceiptV1 双 variant 与映射规则
（IL-03/IL-04 + IL-N03）。

权威 = cr076-installation-lifecycle TEST-PLAN + S04 LLD v1.0 §6/§8 +
冻结 schema release-bundle-identity-v1 rev3（InstallationReceiptV1 分支）。
"""

from __future__ import annotations

from copy import deepcopy

import pytest

from meta_flow.installation.contracts import InstallationContractError
from meta_flow.installation.engine import build_installation_receipt, validate_installation_receipt
from meta_flow.release.bundle_identity import canonical_payload_digest

D_A, D_B, D_C = "a" * 64, "b" * 64, "c" * 64
TS = "2026-09-01T10:00:00Z"
TRANSPORT = {"kind": "TransportReceiptV1", "receipt_digest": D_A}
PUBLISHED = {"kind": "PublishedVerifiedReceiptV1", "receipt_digest": D_B}


# ------------------------------------------------------------ IL-03 双 variant


def test_il03_candidate_install_binds_transport_predecessor() -> None:
    receipt = build_installation_receipt(predecessor=TRANSPORT, consumer_project_uid="consumer/alpha", installed_at=TS, outcome="INSTALLED")
    assert receipt["install_variant"] == "candidate-install"
    assert receipt["predecessor_kind"] == "TransportReceiptV1"
    assert receipt["predecessor_digest"] == D_A


def test_il03_published_install_binds_published_predecessor() -> None:
    receipt = build_installation_receipt(predecessor=PUBLISHED, consumer_project_uid="consumer/alpha", installed_at=TS, outcome="ACTIVATED")
    assert receipt["install_variant"] == "published-install"
    assert receipt["predecessor_kind"] == "PublishedVerifiedReceiptV1"


def test_il03_variant_infers_from_predecessor_kind_and_locks() -> None:
    """显式 variant 与前驱 kind 交叉锁定：错绑 raise（schema allOf 机器化）。"""

    with pytest.raises(InstallationContractError, match="VARIANT-PREDECESSOR-MISMATCH"):
        build_installation_receipt(
            predecessor=TRANSPORT, consumer_project_uid="consumer/alpha", installed_at=TS,
            outcome="INSTALLED", install_variant="published-install",
        )
    with pytest.raises(InstallationContractError, match="VARIANT-PREDECESSOR-MISMATCH"):
        build_installation_receipt(
            predecessor=PUBLISHED, consumer_project_uid="consumer/alpha", installed_at=TS,
            outcome="INSTALLED", install_variant="candidate-install",
        )


def test_il03_n03_unknown_predecessor_kind_rejected_without_receipt() -> None:
    with pytest.raises(InstallationContractError, match="VARIANT-PREDECESSOR-MISMATCH"):
        build_installation_receipt(predecessor={"kind": "SomethingElseV1", "receipt_digest": D_A}, consumer_project_uid="c", installed_at=TS, outcome="INSTALLED")


def test_il03_digest_self_consistency() -> None:
    receipt = build_installation_receipt(predecessor=TRANSPORT, consumer_project_uid="consumer/alpha", installed_at=TS, outcome="INSTALLED")
    unsigned = {key: value for key, value in receipt.items() if key != "receipt_digest"}
    assert receipt["receipt_digest"] == canonical_payload_digest(unsigned)


# ------------------------------------------------- IL-04 升级/降级/幂等映射


def test_il04_upgrade_downgrade_are_fresh_receipts_on_new_chain() -> None:
    """升级/降级 = 对新 bundle 前驱的全新 receipt；旧链 receipt 对象不被改写。"""

    v1 = build_installation_receipt(predecessor=TRANSPORT, consumer_project_uid="consumer/alpha", installed_at=TS, outcome="INSTALLED")
    v2_transport = {"kind": "TransportReceiptV1", "receipt_digest": D_C}  # 新 bundle 链前驱
    v2 = build_installation_receipt(predecessor=v2_transport, consumer_project_uid="consumer/alpha", installed_at=TS, outcome="INSTALLED")
    assert v1["receipt_digest"] != v2["receipt_digest"]
    assert v1["predecessor_digest"] == D_A and v2["predecessor_digest"] == D_C


def test_il04_idempotent_rebuild_yields_identical_receipt() -> None:
    """幂等重装：同前驱同参数重建 → 同 receipt digest（确定性）。"""

    first = build_installation_receipt(predecessor=TRANSPORT, consumer_project_uid="consumer/alpha", installed_at=TS, outcome="ACTIVATED")
    second = build_installation_receipt(predecessor=TRANSPORT, consumer_project_uid="consumer/alpha", installed_at=TS, outcome="ACTIVATED")
    assert first == second


def test_il04_upgraded_downgraded_have_no_enum_and_direction_stays_local() -> None:
    """schema 冻结：UPGRADED/DOWNGRADED 不入 outcome 枚举；方向只记 journal。"""

    receipt = build_installation_receipt(predecessor=TRANSPORT, consumer_project_uid="consumer/alpha", installed_at=TS, outcome="INSTALLED")
    assert "UPGRADED" not in receipt  # 无字段承载方向 → 方向性只在 journal 本地
    assert set(receipt) == {
        "schema_version", "kind", "receipt_digest", "predecessor_digest", "predecessor_kind",
        "install_variant", "consumer_project_uid", "installed_at", "outcome", "reason_codes",
    }


# ------------------------------------------------ validate 负向矩阵（schema）


def test_validate_rejects_unknown_and_missing_fields() -> None:
    good = build_installation_receipt(predecessor=TRANSPORT, consumer_project_uid="c", installed_at=TS, outcome="INSTALLED")
    extra = dict(good)
    extra["upgrade_direction"] = "up"
    with pytest.raises(InstallationContractError, match="INSTALL-RECEIPT-INVALID"):
        validate_installation_receipt(extra)
    missing = dict(good)
    missing.pop("installed_at")
    with pytest.raises(InstallationContractError, match="INSTALL-RECEIPT-INVALID"):
        validate_installation_receipt(missing)


@pytest.mark.parametrize(
    "patch",
    [
        {"schema_version": 2},
        {"kind": "InstallationReceiptV2"},
        {"outcome": "UPGRADED"},
        {"install_variant": "staging-install"},
        {"predecessor_kind": "PublishedVerifiedReceiptV1"},  # 与 variant 失配
        {"consumer_project_uid": "has space"},
        {"installed_at": "2026-09-01 10:00:00"},
        {"reason_codes": ["ACTIVATED", ""]},
    ],
)
def test_validate_rejects_enum_and_pattern_violations(patch: dict) -> None:
    good = build_installation_receipt(predecessor=TRANSPORT, consumer_project_uid="c", installed_at=TS, outcome="INSTALLED")
    bad = dict(good)
    bad.update(patch)
    bad["receipt_digest"] = canonical_payload_digest({k: v for k, v in bad.items() if k != "receipt_digest"})
    with pytest.raises(InstallationContractError):
        validate_installation_receipt(bad)


def test_validate_reason_codes_linked_to_failed_outcome_only() -> None:
    good = build_installation_receipt(predecessor=TRANSPORT, consumer_project_uid="c", installed_at=TS, outcome="INSTALLED")
    with_codes = dict(good)
    with_codes["reason_codes"] = ["SOME-REASON"]
    with pytest.raises(InstallationContractError, match="INSTALL-RECEIPT-INVALID"):
        validate_installation_receipt(with_codes)
    failed = build_installation_receipt(
        predecessor=TRANSPORT, consumer_project_uid="c", installed_at=TS,
        outcome="FAILED", reason_codes=("OWNERSHIP-ACTIVATION-CONFLICT",),
    )
    empty = dict(failed)
    empty["reason_codes"] = []
    empty["receipt_digest"] = canonical_payload_digest({k: v for k, v in empty.items() if k != "receipt_digest"})
    with pytest.raises(InstallationContractError):
        validate_installation_receipt(empty)


def test_validate_detects_digest_tampering() -> None:
    good = build_installation_receipt(predecessor=TRANSPORT, consumer_project_uid="c", installed_at=TS, outcome="INSTALLED")
    tampered = deepcopy(good)
    tampered["consumer_project_uid"] = "consumer/other"
    with pytest.raises(InstallationContractError, match="receipt_digest"):
        validate_installation_receipt(tampered)


def test_validate_normalizes_and_sorts_reason_codes() -> None:
    receipt = build_installation_receipt(
        predecessor=TRANSPORT, consumer_project_uid="c", installed_at=TS,
        outcome="FAILED", reason_codes=("B-CODE", "A-CODE"),
    )
    assert receipt["reason_codes"] == ["A-CODE", "B-CODE"]
