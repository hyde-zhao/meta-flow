"""CR-076 S03：发布资产发现、naming 规范化、三端 preimage 与恢复判定。

权威 = STORY-CR076-S03-bundle-identity-transport-LLD（v1.2）§3/§6/§7。
naming/发现区：歧义/重复/缺失/symlink 全部 fail-closed；digest 观测为
物理域 sha256（sidecar 预像域只在 verify 复算，禁与物理域直比）。
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any

from delivery.scripts.digest_policy import sidecar_path_for_receipt
from meta_flow.installation.identity import require_full_digest
from meta_flow.release.bundle_identity import (
    ASSET_FIELDS,
    NAMING_FIELDS,
    append_lineage_entry,
    canonical_payload_digest,
    mark_superseded,
    require_name_token,
    validate_lineage_index,
    validate_transport_receipt,
)

BUILD_RECEIPT_FILENAME = "ProviderArtifactReceiptV1.json"


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_directory(directory: Path) -> Path:
    resolved = Path(os.path.abspath(Path(directory).expanduser()))
    if resolved.is_symlink() or not resolved.is_dir():
        raise ValueError(f"ASSET-UNSAFE: release directory must be one real directory: {directory}")
    return resolved


# --- naming/发现区 -----------------------------------------------------------


def normalize_naming(*, project_name: str, wheel_filename: str) -> dict[str, str]:
    """从观测 wheel 文件名规范化 naming 三元组（wheel_tag 为观测值，O-S03-03）。

    ``normalized_prefix`` = PEP 503 归一 distribution 名 + 版本（wheel/sdist
    文件名公共前缀）；wheel 文件名的 distribution 段必须与归一项目名一致。
    """

    if not isinstance(project_name, str) or not project_name.strip():
        raise ValueError("ASSET-UNSAFE: project_name must be a non-empty string")
    normalized_name = re.sub(r"[-_.]+", "_", project_name.strip()).lower()
    if not normalized_name or not re.fullmatch(r"[a-z0-9_]+", normalized_name):
        raise ValueError(f"ASSET-UNSAFE: project_name cannot be normalized: {project_name!r}")
    stem = Path(wheel_filename).name.removesuffix(".whl")
    segments = stem.split("-")
    if len(segments) < 5:
        raise ValueError(f"ASSET-UNSAFE: wheel filename must be <prefix>-<py>-<abi>-<plat>.whl: {wheel_filename!r}")
    wheel_tag = "-".join(segments[-3:])
    prefix = "-".join(segments[:-3])
    if not prefix.startswith(f"{normalized_name}-"):
        raise ValueError(
            f"ASSET-UNSAFE: wheel distribution segment {prefix!r} does not match project {normalized_name!r}"
        )
    return {
        "project_name": require_name_token(project_name.strip(), field="naming.project_name"),
        "wheel_tag": require_name_token(wheel_tag, field="naming.wheel_tag"),
        "normalized_prefix": require_name_token(prefix, field="naming.normalized_prefix"),
    }


def _require_naming(naming: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(naming, Mapping) or set(naming) != set(NAMING_FIELDS):
        raise ValueError(f"ASSET-UNSAFE: naming must contain exactly {list(NAMING_FIELDS)}")
    return {
        field: require_name_token(naming[field], field=f"naming.{field}")
        for field in NAMING_FIELDS
    }


def _require_regular_file(path: Path, *, slot: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"ASSET-UNSAFE: {slot} candidate must be one regular file (no symlink): {path.name}")
    return path


def _pick_slot(
    directory: Path,
    *,
    slot: str,
    pattern: str,
) -> Path:
    candidates = sorted(directory.glob(pattern))
    if not candidates:
        raise ValueError(f"ASSET-MISSING: no {slot} candidate matching {pattern!r} in {directory.name}")
    if len(candidates) == 1:
        return _require_regular_file(candidates[0], slot=slot)
    digests = {_file_sha256(_require_regular_file(item, slot=slot)) for item in candidates}
    if len(digests) == 1:
        raise ValueError(f"ASSET-DUPLICATE: {slot} has {len(candidates)} identical-byte candidates: {[p.name for p in candidates]}")
    raise ValueError(f"ASSET-AMBIGUOUS: {slot} has {len(candidates)} differing candidates: {[p.name for p in candidates]}")


def discover_release_assets(directory: Path, naming: Mapping[str, Any]) -> dict[str, Path]:
    """在资产目录中发现恰好四资产；歧义/重复/缺失/symlink fail-closed。"""

    resolved = _require_directory(directory)
    normalized = _require_naming(naming)
    prefix = normalized["normalized_prefix"]
    sidecar_name = sidecar_path_for_receipt(Path(BUILD_RECEIPT_FILENAME)).name
    # 发现 pattern 按公共前缀模糊匹配：wheel 覆盖任意 tag、sdist 覆盖压缩格式后缀；
    # 命中多于一个候选即歧义/重复（tag 本身是 naming 观测值，不参与发现过滤）。
    slots = {
        "wheel": f"{prefix}-*.whl",
        "sdist": f"{prefix}*.tar.gz",
        "build_receipt": BUILD_RECEIPT_FILENAME,
        "sidecar": sidecar_name,
    }
    return {
        slot: _pick_slot(resolved, slot=slot, pattern=pattern)
        for slot, pattern in slots.items()
    }


def observe_asset_digests(directory: Path, naming: Mapping[str, Any]) -> dict[str, str]:
    """发现四资产并计算物理域 sha256（含 sidecar 物理 bytes，流式单遍）。"""

    found = discover_release_assets(directory, naming)
    return {slot: _file_sha256(path) for slot, path in found.items()}


# --- preimage/恢复区（前置=S02 transport_authorization_contract_ready） -----


def _require_physical_digests(values: object, *, field: str) -> dict[str, str]:
    if not isinstance(values, Mapping) or set(values) != set(ASSET_FIELDS):
        raise ValueError(f"MANIFEST-FIELD-INVALID: {field} must contain exactly {list(ASSET_FIELDS)}")
    normalized = {}
    for name in ASSET_FIELDS:
        normalized[name] = require_full_digest(values[name], field_name=f"{field}.{name}")
    return normalized


def verify_three_way_preimage(
    *,
    exported: Mapping[str, str],
    carrier: Mapping[str, str],
    landed: Mapping[str, str],
    receipt: Mapping[str, Any],
) -> tuple[str, ...]:
    """三端物理域相等：出口==载体==落盘==receipt.transported_assets（DQ-07）。

    比对全部是物理 sha256 域值；与 manifest.assets.sidecar（预像域）无关，
    两域禁直接相等比较。
    """

    asserted = validate_transport_receipt(receipt)["transported_assets"]
    conflicts: list[str] = []
    for source, values in (("exported", exported), ("carrier", carrier), ("landed", landed)):
        normalized = _require_physical_digests(values, field=source)
        for name in ASSET_FIELDS:
            if normalized[name] != asserted[name]:
                conflicts.append(f"TRANSPORT-BYTES-MISMATCH:{source}:{name}")
    return tuple(sorted(conflicts))


def scan_transport_materialization(
    landing_directory: Path,
    *,
    expected_digests: Mapping[str, str],
    expected_filenames: Mapping[str, str],
) -> dict[str, Any]:
    """只读扫描落盘现场：缺失清单 + 每槽 observed 物理 digest。

    目录缺失 → 全槽 missing（可幂等续传）；symlink/非常规 → 该槽 unsafe
    （fail-closed，阻断自动恢复）；``mismatched`` = 已落盘但 digest 与期望
    不等（半写/损坏）。无 mutation。
    """

    expected = _require_physical_digests(expected_digests, field="expected_digests")
    if not isinstance(expected_filenames, Mapping) or set(expected_filenames) != set(ASSET_FIELDS):
        raise ValueError(f"MANIFEST-FIELD-INVALID: expected_filenames must cover {list(ASSET_FIELDS)}")
    resolved = Path(os.path.abspath(Path(landing_directory).expanduser()))
    observed: dict[str, str] = {}
    missing: list[str] = []
    unsafe: list[str] = []
    if not resolved.exists():
        return {
            "kind": "TransportMaterializationScanV1",
            "missing": tuple(ASSET_FIELDS),
            "unsafe": (),
            "observed": {},
            "mismatched": (),
            "expected": expected,
        }
    if resolved.is_symlink() or not resolved.is_dir():
        raise ValueError(f"ASSET-UNSAFE: landing directory must be one real directory: {landing_directory}")
    for slot in ASSET_FIELDS:
        path = resolved / str(expected_filenames[slot])
        if path.is_symlink():
            unsafe.append(slot)
            continue
        if not path.is_file():
            missing.append(slot)
            continue
        observed[slot] = _file_sha256(path)
    return {
        "kind": "TransportMaterializationScanV1",
        "missing": tuple(missing),
        "unsafe": tuple(unsafe),
        "observed": observed,
        "mismatched": tuple(sorted(slot for slot in observed if observed[slot] != expected[slot])),
        "expected": expected,
    }


def resume_or_conflict(scan: Mapping[str, Any]) -> dict[str, Any]:
    """R6 恢复判定：digest 相等幂等续传；不等 TRANSPORT-BYTES-CONFLICT。"""

    if not isinstance(scan, Mapping) or scan.get("kind") != "TransportMaterializationScanV1":
        raise ValueError("MANIFEST-FIELD-INVALID: scan must be a TransportMaterializationScanV1 result")
    payload: dict[str, Any] = {
        "kind": "TransportResumeDecisionV1",
        "mutation_count": 0,
        "missing": tuple(scan.get("missing", ())),
        "mismatched": tuple(scan.get("mismatched", ())),
    }
    if scan.get("unsafe"):
        payload.update({"decision": "BLOCKED", "blocker_code": "ASSET-UNSAFE", "unsafe": tuple(scan["unsafe"])})
        return payload
    if scan.get("mismatched"):
        payload.update({
            "decision": "CONFLICT",
            "blocker_code": "TRANSPORT-BYTES-CONFLICT",
            "retry_contract": "new-authorization-new-attempt",
        })
        return payload
    if scan.get("missing"):
        payload.update({"decision": "RESUME", "blocker_code": None})
        return payload
    payload.update({"decision": "IDEMPOTENT-COMPLETE", "blocker_code": None})
    return payload


def _lineage_preimage(index: Mapping[str, Any]) -> str:
    """lineage index 内容 preimage（O-S03-02 漂移复核基准）。

    排除 ``updated_at``：该键是 installation canonical 合同的动态禁键，且属
    投影时间戳——entries/index_id/bundle_digest 已完整承载内容身份。
    """

    base = validate_lineage_index(index)
    return canonical_payload_digest(
        {
            "bundle_digest": base["bundle_digest"],
            "entries": base["entries"],
            "index_id": base["index_id"],
        }
    )


def plan_full_supersede(
    index: Mapping[str, Any],
    *,
    successor_attempt_id: str,
    planned_at: str,
) -> dict[str, Any]:
    """冻结现存 STALE 清单进 plan 对象（O-S03-02 全量口径，mutation=0）。

    STALE 判定：transport 类 entry 且未被 supersede。实测清单为空 →
    ``decision=NA``（CP5 V4：为空则 N/A）。plan 携带 index preimage digest，
    apply 时复核防冻结后漂移。
    """

    base = validate_lineage_index(index)
    require_name_token(successor_attempt_id, field="successor_attempt_id")
    stale = tuple(
        entry["entry_digest"]
        for entry in base["entries"]
        if entry["entry_kind"] == "transport" and entry.get("superseded_by") is None
    )
    return {
        "kind": "FullSupersedePlanV1",
        "decision": "PLANNED" if stale else "NA",
        "bundle_digest": base["bundle_digest"],
        "successor_attempt_id": successor_attempt_id,
        "stale_entry_digests": stale,
        "preimage_index_digest": _lineage_preimage(base),
        "planned_at": planned_at,
        "mutation_count": 0,
    }


def apply_full_supersede(
    index: Mapping[str, Any],
    *,
    plan: Mapping[str, Any],
    successor_receipt: Mapping[str, Any],
    recorded_at: str,
) -> dict[str, Any]:
    """追加新 materialization receipt 并对冻结清单全集 mark_superseded。

    仅追加 index、不改任何旧 receipt bytes（append-only）；plan 冻结后
    index 漂移即拒绝（SUPERSEDE-PLAN-STALE）。
    """

    base = validate_lineage_index(index)
    if not isinstance(plan, Mapping) or plan.get("kind") != "FullSupersedePlanV1":
        raise ValueError("MANIFEST-FIELD-INVALID: plan must be a FullSupersedePlanV1 result")
    receipt = validate_transport_receipt(successor_receipt)
    if _lineage_preimage(base) != plan["preimage_index_digest"]:
        raise ValueError("SUPERSEDE-PLAN-STALE: lineage index drifted after plan freeze")
    if receipt.get("attempt_id") != plan["successor_attempt_id"]:
        raise ValueError("SUPERSEDE-PLAN-STALE: successor receipt attempt does not match the frozen plan")
    updated = append_lineage_entry(
        base,
        entry_kind="transport",
        entry_digest=receipt["receipt_digest"],
        recorded_at=recorded_at,
    )
    superseded: list[str] = []
    for entry_digest in plan["stale_entry_digests"]:
        updated = mark_superseded(
            updated,
            entry_digest=entry_digest,
            superseded_by=receipt["receipt_digest"],
        )
        superseded.append(entry_digest)
    return {
        "kind": "FullSupersedeResultV1",
        "index": updated,
        "appended_entry_digest": receipt["receipt_digest"],
        "superseded_entry_digests": tuple(superseded),
        "superseded_by": receipt["receipt_digest"],
        "mutation_count": 1 + len(superseded),
    }
