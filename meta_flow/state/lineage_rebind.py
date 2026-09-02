"""CR-076 S02 FB3：StateProjectionLineageRebindV1（R-01..R-08 单一 owner）。

MF-BUG-19 恢复通道：对 COMMITTED 且 findings 仅含 LINEAGE_UNBOUND 的投影
manifest 做一次性 lineage 重锚。非状态 setter（R-04）：唯一写入对象是 successor
manifest，投影 bytes 逐字节不变；不裁决 DQ-09（R-08）。plan/execute 两入口
不可合并（R-07）；执行需独立 single-use 授权（R-05）。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path
from typing import Any

REBIND_KIND = "state-projection-lineage-rebind"
AUTHORIZATION_PAYLOAD_KIND = "StateProjectionLineageRebindAuthorizationV1"
LINEAGE_UNBOUND_PREFIX = "STATE_PROJECTION_LINEAGE_UNBOUND:"
_AUTHORIZATION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _parse_ts(value: str, field_name: str) -> datetime:
    if not isinstance(value, str) or not _TS_RE.match(value):
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp with timezone")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass(frozen=True, slots=True)
class StateProjectionLineageRebindAuthorizationV1:
    """R-05 single-use 独立授权（闭合字段集）。"""

    schema_version: int
    kind: str
    authorization_id: str
    plan_digest: str
    target_manifest_digest: str
    transaction_id: str
    not_before: str
    not_after: str
    single_use: bool

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> StateProjectionLineageRebindAuthorizationV1:
        expected = {f.name for f in fields(cls)}
        if set(payload) != expected:
            raise ValueError("lineage rebind authorization fields mismatch")
        if payload["schema_version"] != 1 or payload["kind"] != AUTHORIZATION_PAYLOAD_KIND:
            raise ValueError("lineage rebind authorization kind mismatch")
        if payload["single_use"] is not True:
            raise ValueError("lineage rebind authorization must be single-use")
        if not _AUTHORIZATION_ID_RE.match(str(payload["authorization_id"])):
            raise ValueError("lineage rebind authorization id is invalid")
        for name in ("plan_digest", "target_manifest_digest"):
            if not _DIGEST_RE.match(str(payload[name])):
                raise ValueError(f"lineage rebind authorization {name} is invalid")
        if not str(payload["transaction_id"]).strip():
            raise ValueError("lineage rebind authorization transaction_id is required")
        _parse_ts(payload["not_before"], "not_before")
        _parse_ts(payload["not_after"], "not_after")
        return cls(**dict(payload))

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class LineageRebindPlanV1:
    """R-02/R-03 零写计划：五类 digest + writer receipt 绑定。"""

    decision: str  # READY | BLOCKED
    reason: str
    transaction_id: str
    manifest_digest: str
    projection_digests: tuple[tuple[str, str], ...]
    writer_receipt_ref: str
    findings: tuple[str, ...]
    plan_digest: str

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["projection_digests"] = [list(pair) for pair in self.projection_digests]
        return payload


def _blocked(reason: str, *, findings: tuple[str, ...] = ()) -> LineageRebindPlanV1:
    return LineageRebindPlanV1(
        "BLOCKED", reason, "", "", (), "", findings,
        _canonical_digest({"decision": "BLOCKED", "reason": reason}),
    )


def plan_lineage_rebind(
    project_root: Path,
    *,
    writer_receipt_ref: str,
) -> LineageRebindPlanV1:
    """R-01..R-03：生成零写 rebind 计划（不消费授权、不写任何文件）。"""
    from meta_flow.state.projection_transaction import (
        inspect_state_projection_transaction,
        load_committed_projection_snapshot,
    )

    if not isinstance(writer_receipt_ref, str) or not writer_receipt_ref.strip():
        return _blocked("writer_receipt_ref is required (R-03)")
    try:
        snapshot = load_committed_projection_snapshot(project_root)
    except (OSError, ValueError) as exc:
        return _blocked(f"projection manifest not terminal-loadable: {exc}")
    manifest = snapshot["manifest"]
    if manifest.get("lineage_rebind"):
        return _blocked("manifest already carries a lineage rebind successor")
    inspection = inspect_state_projection_transaction(project_root)
    findings = tuple(str(item) for item in inspection.get("findings", []))
    # R-01：仅接受 LINEAGE_UNBOUND-only；共现 DRIFT/其他 finding → 拒绝。
    unbound = tuple(f for f in findings if f.startswith(LINEAGE_UNBOUND_PREFIX))
    if not unbound:
        return _blocked("no LINEAGE_UNBOUND finding to rebind (nothing to do)")
    if len(unbound) != len(findings):
        message = ("findings co-exist with non-LINEAGE_UNBOUND entries (R-01); "
                   "route TERMINAL_GENERATION_DRIFT to the correction channel")
        return _blocked(message, findings=findings)
    manifest_digest = hashlib.sha256(
        (project_root.resolve() / _manifest_rel()).read_bytes()
    ).hexdigest()
    projection_digests = tuple(
        (ref, str(snapshot["current_by_ref"][ref]))
        for ref in sorted(snapshot["current_by_ref"])
    )
    transaction_id = str(manifest.get("transaction_id") or "")
    plan_digest = _canonical_digest({
        "manifest_digest": manifest_digest,
        "transaction_id": transaction_id,
        "projection_digests": [list(pair) for pair in projection_digests],
        "writer_receipt_ref": writer_receipt_ref,
        "findings": list(findings),
    })
    return LineageRebindPlanV1(
        "READY",
        "LINEAGE_UNBOUND-only manifest ready for one-shot rebind",
        transaction_id,
        manifest_digest,
        projection_digests,
        writer_receipt_ref,
        findings,
        plan_digest,
    )


def _manifest_rel() -> Path:
    from meta_flow.state.projection_transaction import MANIFEST_REL

    return MANIFEST_REL


def execute_lineage_rebind(
    project_root: Path,
    plan: LineageRebindPlanV1,
    authorization: StateProjectionLineageRebindAuthorizationV1,
    *,
    now: str = "",
) -> dict[str, Any]:
    """R-05..R-08：一次性 successor 写入（独立授权；本模块不发起真实执行）。"""
    from meta_flow.state.projection_transaction import load_committed_projection_snapshot

    if plan.decision != "READY":
        return {"status": "BLOCKED", "reason": plan.reason, "mutation_count": 0}
    effective_now = now or datetime.now().astimezone().replace(microsecond=0).isoformat()
    try:
        if (
            (authorization.plan_digest, authorization.target_manifest_digest, authorization.transaction_id)
            != (plan.plan_digest, plan.manifest_digest, plan.transaction_id)
        ):
            raise ValueError("authorization bindings do not match the rebind plan")
        if not (
            _parse_ts(authorization.not_before, "not_before")
            <= _parse_ts(effective_now, "now")
            <= _parse_ts(authorization.not_after, "not_after")
        ):
            raise ValueError("lineage rebind authorization is not within its validity window")
    except ValueError as exc:
        return {"status": "BLOCKED", "reason": str(exc), "mutation_count": 0}
    # R-05 TOCTOU：执行前重验 R-02 全部 digest。
    try:
        snapshot = load_committed_projection_snapshot(project_root)
    except (OSError, ValueError) as exc:
        return {"status": "BLOCKED", "mutation_count": 0, "reason": f"TOCTOU reload failed: {exc}"}
    manifest_path = project_root.resolve() / _manifest_rel()
    if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != plan.manifest_digest:
        return {"status": "BLOCKED", "mutation_count": 0,
                "reason": "TOCTOU: projection manifest drifted (R-05); authorization not consumed"}
    drifted = [
        ref for ref, digest in plan.projection_digests
        if str(snapshot["current_by_ref"].get(ref)) != digest
    ]
    if drifted:
        return {"status": "BLOCKED", "mutation_count": 0,
                "reason": "TOCTOU: projection file digests drifted (R-05): " + ", ".join(drifted)}
    # R-06：successor manifest 一次原子写入；旧 manifest digest 保留可追溯。
    successor = dict(snapshot["manifest"])
    lineage = {
        ref: dict(entry) for ref, entry in dict(successor.get("lineage") or {}).items()
    }
    for ref, head in sorted(dict(snapshot["close_heads"]).items()):
        scoped_ref = f"process/{ref}"
        lineage[scoped_ref] = {
            "anchor_close_authorization_id": str(head["authorization_id"]),
            "anchor_close_digest": str(head["after_digest"]),
            "current_digest": str(snapshot["current_by_ref"][scoped_ref]),
        }
    successor["lineage"] = lineage
    # R-04：投影文件 bytes 不变；R-08：不裁决 DQ-09。
    rebind_record = {
        "kind": REBIND_KIND,
        "authorization_id": authorization.authorization_id,
        "supersedes_manifest_digest": plan.manifest_digest,
        "writer_receipt_ref": plan.writer_receipt_ref,
        "executed_at": effective_now,
        "projection_files_mutated": 0,
        "dq09_ruling": "not_adjudicated",
    }
    successor["lineage_rebind"] = rebind_record
    successor["updated_at"] = effective_now
    payload = json.dumps(successor, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary = manifest_path.with_name(manifest_path.name + ".rebind-tmp")
    try:
        temporary.write_text(payload, encoding="utf-8")
        if temporary.read_bytes() != payload.encode("utf-8"):
            raise RuntimeError("successor manifest write verification failed")
        os.replace(temporary, manifest_path)  # 原子 rename；失败时旧 manifest 完整
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        return {"status": "BLOCKED", "mutation_count": 0,
                "reason": f"successor manifest write failed (R-06, no half state): {exc}"}
    return {
        "status": "PASS",
        "transaction_id": plan.transaction_id,
        "mutation_count": 1,  # 唯一 mutation = successor manifest 文件
        **rebind_record,
    }
