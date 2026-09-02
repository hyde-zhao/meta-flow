"""STORY-CR076-S03 targeted 测试：lineage 索引、全量 supersede 与恢复判定
（BIT-07/09 + BIT-N05/N08 落盘侧）。

权威 = cr076-bundle-identity-transport TEST-PLAN + LLD v1.2 §6/§7.4/§12 O-S03-02。
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256

import pytest

from meta_flow.release.asset_discovery import (
    apply_full_supersede,
    plan_full_supersede,
    resume_or_conflict,
    scan_transport_materialization,
)
from meta_flow.release.bundle_identity import (
    ZERO_DIGEST_PLACEHOLDER,
    append_lineage_entry,
    build_base_bundle_manifest,
    build_lineage_index,
    build_transport_receipt,
    derive_sidecar_preimage,
    mark_superseded,
)

_OID1, _OID2 = "1" * 40, "2" * 40
_TS1, _TS2 = "2026-09-01T08:00:00Z", "2026-09-01T09:30:00Z"
_AUTH1, _AUTH2 = "sha256:" + "b" * 64, "sha256:" + "c" * 64
_NAMING = {"project_name": "meta-flow", "wheel_tag": "py3-none-any", "normalized_prefix": "meta_flow-1.2.3"}
_ASSETS = {"wheel": "a" * 64, "sdist": "b" * 64, "build_receipt": "c" * 64, "sidecar": "d" * 64}
_FILES = {
    "wheel": "meta_flow-1.2.3-py3-none-any.whl",
    "sdist": "meta_flow-1.2.3.tar.gz",
    "build_receipt": "ProviderArtifactReceiptV1.json",
    "sidecar": "ProviderArtifactReceiptV1.digest-policy.json",
}


def _manifest() -> dict[str, object]:
    skeleton = {
        "schema_version": 1,
        "kind": "ImmutableBaseBundleManifestV1",
        "bundle_id": ZERO_DIGEST_PLACEHOLDER,
        "bundle_digest": ZERO_DIGEST_PLACEHOLDER,
        "semver": "1.2.3",
        "source": {"release_oid": _OID1, "process_oid": _OID2, "frozen_at": _TS1},
        "assets": dict(_ASSETS, sidecar=ZERO_DIGEST_PLACEHOLDER),
        "naming": _NAMING,
        "built_at": _TS1,
        "build_authorization_digest": _AUTH1,
    }
    return build_base_bundle_manifest(
        release_oid=_OID1, process_oid=_OID2, frozen_at=_TS1, semver="1.2.3",
        asset_digests=dict(_ASSETS, sidecar=derive_sidecar_preimage(skeleton)),
        naming=_NAMING, built_at=_TS1, build_authorization_digest=_AUTH1,
    )


def _receipt(manifest: dict[str, object], *, attempt_id: str, outcome: str = "DELIVERED") -> dict[str, object]:
    return build_transport_receipt(
        predecessor=manifest, attempt_id=attempt_id,
        transported_assets=_ASSETS, transported_at=_TS1,
        transport_authorization_digest=_AUTH1, outcome=outcome,
        reason_codes=() if outcome == "DELIVERED" else ("CARRIER-PARTIAL",),
        predecessor_attempt=None if attempt_id == "attempt-1" else "attempt-1",
    )


def _index_with_receipts() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    m = _manifest()
    r1 = _receipt(m, attempt_id="attempt-1")
    index = build_lineage_index(index_id="idx-1", bundle_digest=m["bundle_digest"], recorded_at=_TS1)
    index = append_lineage_entry(index, entry_kind="transport", entry_digest=r1["receipt_digest"], recorded_at=_TS1)
    return index, m, r1


def test_bit09_append_never_touches_existing_entries() -> None:
    index, m, r1 = _index_with_receipts()
    frozen = deepcopy(index)
    r2 = _receipt(m, attempt_id="attempt-2")
    grown = append_lineage_entry(
        index, entry_kind="transport", entry_digest=r2["receipt_digest"], recorded_at=_TS2,
    )
    # 不可变：原 index 不变；既有 entry bytes（含 digest）逐字节不变。
    assert index == frozen
    assert grown["entries"][: len(index["entries"])] == index["entries"]
    assert len(grown["entries"]) == 3
    # mark_superseded 同样不可变 + 标记语义（FU-CR075-002）。
    marked = mark_superseded(grown, entry_digest=r1["receipt_digest"], superseded_by=r2["receipt_digest"])
    assert grown["entries"][1]["superseded_by"] is None
    assert marked["entries"][1]["superseded_by"] == r2["receipt_digest"]
    # 重复 supersede 拒绝；未知 digest 拒绝。
    with pytest.raises(ValueError, match="ENTRY-ALREADY-SUPERSEDED"):
        mark_superseded(marked, entry_digest=r1["receipt_digest"], superseded_by="e" * 64)
    with pytest.raises(ValueError, match="LINEAGE-ENTRY-MISSING"):
        mark_superseded(grown, entry_digest="9" * 64, superseded_by="e" * 64)


def test_bit09_full_supersede_plan_apply() -> None:
    index, m, r1 = _index_with_receipts()
    plan = plan_full_supersede(index, successor_attempt_id="attempt-2", planned_at=_TS2)
    assert plan["decision"] == "PLANNED"
    assert plan["mutation_count"] == 0
    # O-S03-02 全量口径：manifest 首条 + 未 supersede 的 transport entry 全进冻结清单。
    assert set(plan["stale_entry_digests"]) == {m["bundle_digest"], r1["receipt_digest"]}
    r2 = _receipt(m, attempt_id="attempt-2")
    result = apply_full_supersede(index, plan=plan, successor_receipt=r2, recorded_at=_TS2)
    assert result["mutation_count"] == 3
    appended = result["index"]["entries"][-1]
    assert appended["entry_digest"] == r2["receipt_digest"] and appended["superseded_by"] is None
    # 冻结清单全集被 successor 标记；successor 自身不被标记。
    assert all(
        entry["superseded_by"] == r2["receipt_digest"] for entry in result["index"]["entries"][:-1]
    )
    # 旧 receipt bytes 不变（append-only：只动 index）。
    assert r1 == _receipt(m, attempt_id="attempt-1")


def test_bit09_supersede_plan_stale_and_na() -> None:
    index, m, _ = _index_with_receipts()
    plan = plan_full_supersede(index, successor_attempt_id="attempt-2", planned_at=_TS2)
    # plan 冻结后 index 漂移 → SUPERSEDE-PLAN-STALE。
    drifted = append_lineage_entry(index, entry_kind="acceptance", entry_digest="7" * 64, recorded_at=_TS2)
    r2 = _receipt(m, attempt_id="attempt-2")
    with pytest.raises(ValueError, match="SUPERSEDE-PLAN-STALE"):
        apply_full_supersede(drifted, plan=plan, successor_receipt=r2, recorded_at=_TS2)
    # successor attempt 与 plan 不符 → 拒绝。
    r3 = _receipt(m, attempt_id="attempt-3")
    with pytest.raises(ValueError, match="SUPERSEDE-PLAN-STALE"):
        apply_full_supersede(index, plan=plan, successor_receipt=r3, recorded_at=_TS2)
    # 实测清单为空（现存 STALE=0）→ N/A（CP5 V4）。
    marked = mark_superseded(index, entry_digest=m["bundle_digest"], superseded_by="e" * 64)
    marked = mark_superseded(marked, entry_digest=marked["entries"][1]["entry_digest"], superseded_by="e" * 64)
    na_plan = plan_full_supersede(marked, successor_attempt_id="attempt-9", planned_at=_TS2)
    assert na_plan["decision"] == "NA" and na_plan["stale_entry_digests"] == ()


def _observed_digests() -> dict[str, str]:
    """按落盘写入内容（slot 名 bytes）观测的期望 digest 组。"""

    return {slot: sha256(slot.encode()).hexdigest() for slot in _ASSETS}


def test_bit07_scan_and_resume_decisions(tmp_path) -> None:
    # 目录缺失 → 全槽 missing → RESUME（幂等续传，无 mutation）。
    absent = scan_transport_materialization(
        tmp_path / "landing", expected_digests=_ASSETS, expected_filenames=_FILES,
    )
    assert absent["missing"] == tuple(_ASSETS)
    decision = resume_or_conflict(absent)
    assert decision["decision"] == "RESUME" and decision["mutation_count"] == 0
    # 全部落盘且 digest 相等 → IDEMPOTENT-COMPLETE。
    landing = tmp_path / "landing"
    landing.mkdir()
    for slot, name in _FILES.items():
        (landing / name).write_bytes(slot.encode())
    complete = scan_transport_materialization(
        landing, expected_digests=_observed_digests(), expected_filenames=_FILES,
    )
    assert complete["missing"] == () and complete["mismatched"] == ()
    assert resume_or_conflict(complete)["decision"] == "IDEMPOTENT-COMPLETE"
    # 部分缺失 → RESUME + 缺失清单。
    (landing / _FILES["wheel"]).unlink()
    partial = scan_transport_materialization(
        landing, expected_digests=_observed_digests(), expected_filenames=_FILES,
    )
    resumed = resume_or_conflict(partial)
    assert resumed["decision"] == "RESUME" and resumed["missing"] == ("wheel",)


def test_n05_half_written_bytes_conflict(tmp_path) -> None:
    landing = tmp_path / "landing"
    landing.mkdir()
    for slot, name in _FILES.items():
        (landing / name).write_bytes(slot.encode())
    # 残留半写：sdist bytes 损坏 → 仅 sdist 与期望不等（其余槽期望=观测值）。
    (landing / _FILES["sdist"]).write_bytes(b"corrupted-half-write")
    scan = scan_transport_materialization(
        landing, expected_digests={**_observed_digests(), "sdist": _ASSETS["sdist"]},
        expected_filenames=_FILES,
    )
    assert scan["mismatched"] == ("sdist",)
    decision = resume_or_conflict(scan)
    assert decision["decision"] == "CONFLICT"
    assert decision["blocker_code"] == "TRANSPORT-BYTES-CONFLICT"
    assert decision["retry_contract"] == "new-authorization-new-attempt"
    assert decision["mutation_count"] == 0


def test_n08_symlink_slot_is_unsafe(tmp_path) -> None:
    landing = tmp_path / "landing"
    landing.mkdir()
    real = tmp_path / "outside.bin"
    real.write_bytes(b"wheel-bytes")
    for slot, name in _FILES.items():
        (landing / name).write_bytes(slot.encode())
    (landing / _FILES["wheel"]).unlink()
    (landing / _FILES["wheel"]).symlink_to(real)
    scan = scan_transport_materialization(
        landing,
        expected_digests={**_ASSETS, "wheel": sha256(b"wheel-bytes").hexdigest()},
        expected_filenames=_FILES,
    )
    assert "wheel" in scan["unsafe"]
    decision = resume_or_conflict(scan)
    assert decision["decision"] == "BLOCKED" and decision["blocker_code"] == "ASSET-UNSAFE"


def test_lineage_index_bounds() -> None:
    m = _manifest()
    index = build_lineage_index(index_id="idx-1", bundle_digest=m["bundle_digest"], recorded_at=_TS1)
    # 上限 256：追加到边界后拒绝。
    for position in range(255):
        index = append_lineage_entry(
            index, entry_kind="installation", entry_digest=f"{position:064x}", recorded_at=_TS1,
        )
    assert len(index["entries"]) == 256
    with pytest.raises(ValueError, match="LINEAGE-INDEX-FULL"):
        append_lineage_entry(index, entry_kind="installation", entry_digest="f" * 64, recorded_at=_TS1)
    # 非法 entry_kind 拒绝。
    with pytest.raises(ValueError, match="MANIFEST-FIELD-INVALID"):
        append_lineage_entry(index, entry_kind="unknown-kind", entry_digest="f" * 64, recorded_at=_TS1)
