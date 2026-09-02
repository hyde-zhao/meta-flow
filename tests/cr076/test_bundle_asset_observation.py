"""STORY-CR076-S03 targeted 测试：installation 薄扩展与四资产物理观测
（BIT-10：require_full_oid/require_full_digest、observe_bundle_asset_files、
installation_identity_digest + 既有合同零破坏回归）。

权威 = cr076-bundle-identity-transport TEST-PLAN + LLD v1.2 §4.6/§6。
"""

from __future__ import annotations

import io
import zipfile
from hashlib import sha256

import pytest

from meta_flow.installation.artifact import (
    ARTIFACT_RECEIPT_KIND,
    build_provider_release_asset_set,
    observe_bundle_asset_files,
    validate_provider_artifact_receipt,
)
from meta_flow.installation.canonical import canonical_digest
from meta_flow.installation.identity import require_full_digest, require_full_oid
from meta_flow.installation.manifest import (
    INSTALLATION_IDENTITY_FIELDS,
    MANIFEST_V2_FIELDS,
    installation_identity_digest,
    validate_manifest_v2,
)


def test_bit10_require_full_oid_and_digest() -> None:
    assert require_full_oid("1" * 40) == "1" * 40
    assert require_full_digest("a" * 64, field_name="slot") == "a" * 64
    # 拒绝面：短缩写、大写、非 hex、非 str、超长。
    for bad in ("abc1234", "Z" * 40, "g" * 40, 42, None, "1" * 41):
        with pytest.raises(ValueError, match="40-hex"):
            require_full_oid(bad)
    for bad in ("a" * 63, "A" * 64, "z" * 64, "digest", None, "a" * 65):
        with pytest.raises(ValueError, match="64-hex"):
            require_full_digest(bad, field_name="slot")
    # field_name 进入错误信息（错误指向性）。
    with pytest.raises(ValueError, match="naming.sidecar"):
        require_full_digest("a" * 63, field_name="naming.sidecar")


def _wheel_bytes(version: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "meta_flow-1.2.3.dist-info/METADATA",
            f"Metadata-Version: 2.1\nName: meta-flow\nVersion: {version}\n",
        )
        archive.writestr("meta_flow/__init__.py", "")
    return buffer.getvalue()


def test_bit10_observe_bundle_asset_files(tmp_path) -> None:
    wheel = tmp_path / "meta_flow-1.2.3-py3-none-any.whl"
    sdist = tmp_path / "meta_flow-1.2.3.tar.gz"
    receipt = tmp_path / "ProviderArtifactReceiptV1.json"
    sidecar = tmp_path / "ProviderArtifactReceiptV1.digest-policy.json"
    wheel.write_bytes(_wheel_bytes("1.2.3"))
    sdist.write_bytes(b"sdist-bytes")
    receipt.write_bytes(b"receipt-bytes")
    sidecar.write_bytes(b"sidecar-bytes")
    digests = observe_bundle_asset_files(
        wheel, sdist, receipt, sidecar, expected_semver="1.2.3",
    )
    assert set(digests) == {"wheel", "sdist", "build_receipt", "sidecar"}
    assert digests["wheel"] == sha256(wheel.read_bytes()).hexdigest()
    assert digests["sidecar"] == sha256(b"sidecar-bytes").hexdigest()
    # 版本一致性：wheel METADATA 与 sdist 文件名不符 → 拒绝。
    other_sdist = tmp_path / "meta_flow-1.2.4.tar.gz"
    other_sdist.write_bytes(b"sdist-bytes")
    with pytest.raises(ValueError, match="ASSET-VERSION-MISMATCH"):
        observe_bundle_asset_files(wheel, other_sdist, receipt, sidecar)
    # expected_semver 与 wheel METADATA 不符 → 拒绝。
    with pytest.raises(ValueError, match="ASSET-VERSION-MISMATCH"):
        observe_bundle_asset_files(wheel, sdist, receipt, sidecar, expected_semver="1.2.4")
    # symlink 资产 → ASSET-UNSAFE（fail-closed）。
    linked = tmp_path / "linked-sidecar.json"
    linked.symlink_to(sidecar)
    with pytest.raises(ValueError, match="ASSET-UNSAFE"):
        observe_bundle_asset_files(wheel, sdist, receipt, linked)


def _identity_keyset(payload: dict[str, object]) -> dict[str, object]:
    return {
        **{field: payload["installation"][field] for field in INSTALLATION_IDENTITY_FIELDS},  # type: ignore[index]
        "source_identity": payload["source_identity"],
    }


def _v2_manifest(**installation_overrides: object) -> dict[str, object]:
    """紧凑合法 v2 构造（只覆盖 identity 关键组相关字段）。"""

    def digest(value: str) -> str:
        return canonical_digest({"value": value})

    installation: dict[str, object] = {
        "installation_id": "install-001",
        "platform": "codex",
        "scope": "project",
        "component_set": ["agents", "skills"],
        "source_version": "0.5.1",
        "source_oid": "a" * 40,
        "target_digest": digest("target"),
        "facts_digest": digest("facts"),
        "ownership_count": 0,
        "operation": "install",
        "decision_ref": "decisions/install-001",
        "status": "complete",
        "transaction_generation": 1,
        "install_digest": digest("install"),
    }
    installation.update(installation_overrides)
    payload: dict[str, object] = {
        "schema_version": 2,
        "manifest_id": "manifests/install-001",
        "source_identity": {
            "source": "meta-flow-delivery",
            "version": "0.5.1",
            "oid": "a" * 40,
            "delivery_tree_digest": "b" * 64,
            "rules_source_digest": "c" * 64,
            "inventory_digest": "d" * 64,
        },
        "target_ref": "targets/project",
        "plan_ref": "plans/install-001",
        "installation": installation,
        "ownership": [],
        "transaction_ref": "transactions/install-001",
        "integrity": {
            "algorithm": "sha256",
            "content_digest": digest("content"),
            "ownership_digest": canonical_digest([]),
            "canonical_version": 1,
        },
        "migration": {
            "from_schema": 2,
            "candidate": False,
            "backup_ref": "journals/install-001/backup",
            "status": "not-needed",
            "source_match": True,
        },
        "state": "complete",
        "manifest_digest": "",
    }
    payload["manifest_digest"] = canonical_digest(
        {key: payload[key] for key in MANIFEST_V2_FIELDS if key != "manifest_digest"}
    )
    return payload


def test_bit10_installation_identity_digest() -> None:
    base = _v2_manifest()
    assert validate_manifest_v2(base) is not None
    identity = installation_identity_digest(base)
    # 关键组就是身份：同输入重建必然同值（S04 验收点口径）。
    assert installation_identity_digest(_v2_manifest()) == identity
    assert identity == canonical_digest(_identity_keyset(base))
    # 非关键组变化（status / facts_digest / integrity）不影响身份。
    for overrides in ({"status": "active"}, {"facts_digest": "e" * 64}):
        assert installation_identity_digest(_v2_manifest(**overrides)) == identity
    # 任一关键组字段变化 → 不同身份。
    for overrides in (
        {"platform": "claude"},
        {"scope": "user"},
        {"component_set": ["rules"]},
        {"source_version": "0.5.2"},
        {"source_oid": "9" * 40},
        {"target_digest": "8" * 64},
        {"installation_id": "install-002"},
    ):
        assert installation_identity_digest(_v2_manifest(**overrides)) != identity, overrides
    # 非法 manifest（自 digest 破坏）→ 先过 validate 再拒。
    broken = _v2_manifest()
    broken["manifest_digest"] = "0" * 64
    with pytest.raises(ValueError):
        installation_identity_digest(broken)


def test_existing_artifact_contract_regression() -> None:
    # 既有四资产清单合同零破坏（S03 只加 observe，不改 build/validate）。
    asset_set = build_provider_release_asset_set("0.6.1")
    assert asset_set.required_count == 4
    assert asset_set.wheel_filename == "meta_flow-0.6.1-py3-none-any.whl"
    # receipt 合同字段面不变（新 helper 未改 _FIELDS）。
    receipt = {
        "schema_version": 1,
        "kind": ARTIFACT_RECEIPT_KIND,
        "distribution_name": "meta-flow",
        "distribution_version": "0.6.1",
        "source_commit": "1" * 40,
        "source_dirty": False,
        "source_tree_digest": "a" * 64,
        "artifact_filename": "meta_flow-0.6.1-py3-none-any.whl",
        "artifact_sha256": "b" * 64,
        "capability_profile_digest": "c" * 64,
        "installed_payload_digest": "d" * 64,
        "release_qualifying": True,
        "receipt_digest": "",
    }
    receipt["receipt_digest"] = canonical_digest(
        {k: v for k, v in receipt.items() if k != "receipt_digest"}
    )
    assert validate_provider_artifact_receipt(receipt) == receipt
