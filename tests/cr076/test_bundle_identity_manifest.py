"""STORY-CR076-S03 targeted 测试：不可变基座 manifest 构建与双域 digest
（BIT-01/02/08 + BIT-N02/N04/N06）。

权威 = cr076-bundle-identity-transport TEST-PLAN + LLD v1.2 §5/§6/§7。
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256

import pytest

from meta_flow.installation.identity import require_full_oid
from meta_flow.release.bundle_identity import (
    ZERO_DIGEST_PLACEHOLDER,
    build_base_bundle_manifest,
    build_sidecar_envelope,
    build_transport_receipt,
    canonical_bytes,
    derive_sidecar_preimage,
    materialize_sidecar_envelope,
    require_object_kind,
    sidecar_preimage_digest,
    slotted_zero_digest,
    validate_base_bundle_manifest,
    verify_predecessor_chain,
)

_OK = "a" * 64
_OID1, _OID2 = "1" * 40, "2" * 40
_TS1, _TS2 = "2026-09-01T08:00:00Z", "2026-09-01T09:30:00Z"
_AUTH1, _AUTH2 = "sha256:" + "b" * 64, "sha256:" + "c" * 64
_NAMING = {"project_name": "meta-flow", "wheel_tag": "py3-none-any", "normalized_prefix": "meta_flow-1.2.3"}


def _asset_digests(
    *,
    semver: str = "1.2.3",
    release_oid: str = _OID1,
    naming: dict[str, str] | None = None,
    **overrides: str,
) -> dict[str, str]:
    """由 draft 骨架推导零槽预像后组装四槽（与 build 内部推导同口径）。"""

    skeleton = {
        "schema_version": 1,
        "kind": "ImmutableBaseBundleManifestV1",
        "bundle_id": ZERO_DIGEST_PLACEHOLDER,
        "bundle_digest": ZERO_DIGEST_PLACEHOLDER,
        "semver": semver,
        "source": {"release_oid": release_oid, "process_oid": _OID2, "frozen_at": _TS1},
        "assets": {"wheel": _OK, "sdist": _OK, "build_receipt": _OK, "sidecar": ZERO_DIGEST_PLACEHOLDER},
        "naming": naming if naming is not None else _NAMING,
        "built_at": _TS1,
        "build_authorization_digest": _AUTH1,
    }
    preimage = derive_sidecar_preimage(skeleton)
    assets = {"wheel": _OK, "sdist": _OK, "build_receipt": _OK, "sidecar": preimage}
    assets.update(overrides)
    return assets


def _manifest(**overrides: object) -> dict[str, object]:
    params: dict[str, object] = {
        "release_oid": _OID1,
        "process_oid": _OID2,
        "frozen_at": _TS1,
        "semver": "1.2.3",
        "asset_digests": None,
        "naming": _NAMING,
        "built_at": _TS1,
        "build_authorization_digest": _AUTH1,
    }
    params.update(overrides)
    if params["asset_digests"] is None:
        # 预像推导必须与最终 draft 同 semver/release_oid/naming（长度敏感）。
        params["asset_digests"] = _asset_digests(
            semver=str(params["semver"]),
            release_oid=str(params["release_oid"]),
            naming=params["naming"],  # type: ignore[arg-type]
        )
    return build_base_bundle_manifest(**params)


def _receipt(manifest: dict[str, object], *, attempt_id: str = "attempt-1") -> dict[str, object]:
    return build_transport_receipt(
        predecessor=manifest,
        attempt_id=attempt_id,
        transported_assets=deepcopy(manifest["assets"]),  # type: ignore[arg-type]
        transported_at=_TS1,
        transport_authorization_digest=_AUTH1,
        outcome="DELIVERED",
    )


def test_bit01_bundle_id_composition_and_stability() -> None:
    m1, m2 = _manifest(), _manifest()
    assert m1["bundle_id"] == m2["bundle_id"], "同输入重建必须同 id"
    # built_at / 授权 digest 不入 id，但入 bundle_digest。
    m3 = _manifest(built_at=_TS2, build_authorization_digest=_AUTH2)
    assert m3["bundle_id"] == m1["bundle_id"]
    assert m3["bundle_digest"] != m1["bundle_digest"]
    # 资产全集与 naming 均入 id：任一变化即不同 bundle。
    for overrides in (
        {"asset_digests": _asset_digests(wheel="e" * 64)},
        {"naming": {**_NAMING, "wheel_tag": "py3-none-many"}},
        {"semver": "1.2.4"},
        {"release_oid": "3" * 40},
    ):
        assert _manifest(**overrides)["bundle_id"] != m1["bundle_id"], overrides


def test_bit01_duplicate_registration_blocked() -> None:
    m = _manifest()
    with pytest.raises(ValueError, match="BUNDLE-ALREADY-REGISTERED"):
        _manifest(registered_index=[m])
    # registered_index 内对象 kind 不符即先拒绝（不是合法注册表）。
    with pytest.raises(ValueError, match="OBJECT-KIND-MISMATCH"):
        _manifest(registered_index=[{"kind": "TransportReceiptV1"}])


def test_bit02_dual_domain_digests() -> None:
    m = _manifest()
    envelope = materialize_sidecar_envelope(m)
    # 信封 = 8 字节大端长度头 + 4096 定长槽位（LCQ-S03-01 冻结）。
    assert len(envelope) == 4104
    assert int.from_bytes(envelope[:8], "big") == len(canonical_bytes(m))
    # 预像域：槽位置 b"\x00"*4096 后整体 sha256，只绑定 header（结构）。
    assert m["assets"]["sidecar"] == sidecar_preimage_digest(envelope)
    physical = sha256(envelope).hexdigest()
    # 物理域 sha256 != 预像域值：两域值不同、各司其职。
    assert m["assets"]["sidecar"] != physical
    # bundle_digest = 自身槽位替换 "0"*64 后的 canonical digest。
    assert m["bundle_digest"] == slotted_zero_digest(m, "bundle_digest", ZERO_DIGEST_PLACEHOLDER)
    # 预像域对槽位内容不敏感：改槽位 bytes 后预像不变（结构绑定语义）。
    tampered = bytearray(envelope)
    tampered[100] ^= 0xFF
    assert sidecar_preimage_digest(bytes(tampered)) == m["assets"]["sidecar"]


def test_bit02_envelope_rejects_oversized_manifest() -> None:
    with pytest.raises(ValueError, match="SIDECAR-ENVELOPE-INVALID"):
        build_sidecar_envelope(b"x" * 4097)
    with pytest.raises(ValueError, match="SIDECAR-ENVELOPE-INVALID"):
        sidecar_preimage_digest(b"\x00" * 10)


def test_n02_physical_sha_in_preimage_slot_blocked() -> None:
    physical = sha256(materialize_sidecar_envelope(_manifest())).hexdigest()
    with pytest.raises(ValueError, match="SIDECAR-PREIMAGE-MISMATCH"):
        _manifest(asset_digests=_asset_digests(sidecar=physical))


def test_bit08_exact_predecessor_chain() -> None:
    m, r = _manifest(), None  # type: ignore[assignment]
    r = _receipt(m)
    assert verify_predecessor_chain([m, r]) == ()
    # 倒序 / receipt 相邻 receipt：对象链前驱只能是基座 manifest。
    assert verify_predecessor_chain([r, m])
    assert verify_predecessor_chain([m, r, _receipt(m, attempt_id="attempt-2")])
    # digest 指向断裂：篡改前驱 bundle_digest 后 receipt 指向失配。
    broken = deepcopy(m)
    broken["bundle_digest"] = "9" * 64
    conflicts = verify_predecessor_chain([broken, r])
    assert any("PREDECESSOR-DIGEST-MISMATCH" in c for c in conflicts)
    # 空序列通过（S03/S04/S05 共用约定）。
    assert verify_predecessor_chain([]) == ()


def test_n06_short_or_nonhex_oid_rejected_two_layers() -> None:
    # helper 层（identity 薄扩展，BIT-10）：短缩写 / 非 40 hex / 大写 / 非 str。
    with pytest.raises(ValueError, match="40-hex"):
        require_full_oid("abc1234")
    with pytest.raises(ValueError, match="40-hex"):
        require_full_oid("Z" * 40)
    with pytest.raises(ValueError, match="40-hex"):
        require_full_oid(40)
    # build 层：source OID 短缩写拒绝。
    with pytest.raises(ValueError):
        _manifest(release_oid="abc1234")
    # validate 层（schema 分支复用同一 helper）：直接破坏 manifest.source.release_oid。
    broken = deepcopy(_manifest())
    broken["source"]["release_oid"] = "1" * 39  # type: ignore[index]
    with pytest.raises(ValueError, match="40-hex"):
        validate_base_bundle_manifest(broken)


def test_manifest_digest_and_field_tamper_rejected() -> None:
    m = _manifest()
    # 自 digest 复核：改任一字段后 digest 失配。
    for path in ("bundle_id", "built_at"):
        broken = deepcopy(m)
        broken[path] = "0" * 64 if path == "bundle_id" else _TS2  # type: ignore[assignment]
        with pytest.raises(ValueError, match="bundle_digest does not match"):
            validate_base_bundle_manifest(broken)
    # 未知字段 / 非法 kind / 非法 semver。
    extra = deepcopy(m)
    extra["extra"] = 1
    with pytest.raises(ValueError, match="MANIFEST-FIELD-INVALID"):
        validate_base_bundle_manifest(extra)
    wrong_kind = deepcopy(m)
    wrong_kind["kind"] = "TransportReceiptV1"
    with pytest.raises(ValueError, match="MANIFEST-FIELD-INVALID"):
        validate_base_bundle_manifest(wrong_kind)
    with pytest.raises(ValueError, match="MANIFEST-FIELD-INVALID"):
        _manifest(semver="1.2")
    # require_object_kind：kind 门（前驱链断裂信号）。
    assert require_object_kind(m, "ImmutableBaseBundleManifestV1") == "ImmutableBaseBundleManifestV1"
