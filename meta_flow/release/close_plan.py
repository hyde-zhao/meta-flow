"""P6 收口（IF-10..12）：零写 fresh precheck → 受权逐对象可恢复 close → terminal。

P6ClosurePlanV1 只读规划（不落库，apply 前 fresh 重算，授权绑定 plan_digest）；
apply 按 Work→CR 逐对象分步提交（不跨对象原子，HLD-AMENDMENT-A1），partial →
journal append + 整体 BLOCKED；仅 active 归零后生成 P6TerminalResultV1（一次 closure
唯一）；phase transition 不在本模块执行（precheck=not-executed，Host native 域）。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from meta_flow.execution_control.contract import canonical_digest
from meta_flow.ingestion.consumer_acceptance_validator import (
    INSTALLED_ARTIFACT,
    SOURCE_CANDIDATE,
)
from meta_flow.project.model import load_project
from meta_flow.project.process_route import require_process_route, resolve_process_ref
from meta_flow.work.lifecycle_transaction import apply_work_close, plan_work_close
from meta_flow.work.model import load_work
from meta_flow.work.publication_close import plan_cr076_release_close_guard
from meta_flow.workflow.cr_lifecycle import close_cr

P6_CLOSURE_PLAN_KIND = "P6ClosurePlanV1"
P6_TERMINAL_KIND = "P6TerminalResultV1"
P6_CLOSURE_AUTHORIZATION_KIND = "p6-closure-authorization-v1"
CLOSURE_DIR_REF = "process/evidence/CR-076/p6-closure"
TERMINAL_NAME = "P6-TERMINAL-RESULT.yaml"
JOURNAL_NAME = "RECOVERY-JOURNAL.ndjson"

VARIANT_CARDINALITY_VIOLATED = "VARIANT-CARDINALITY-VIOLATED"
VARIANT_ORDER_VIOLATED = "VARIANT-ORDER-VIOLATED"
VARIANT_IDENTITY_DIVERGED = "VARIANT-IDENTITY-DIVERGED"
ATTESTATION_BINDING_MISMATCH = "ATTESTATION-BINDING-MISMATCH"
CLOSURE_TARGET_MISSING = "CLOSURE-TARGET-MISSING"
PLAN_DRIFTED = "PLAN-DRIFTED"
TERMINAL_ALREADY_EXISTS = "TERMINAL-ALREADY-EXISTS"
P6_CLOSURE_BLOCKED = "P6-CLOSURE-BLOCKED"

# 双 result 必须相等的执行身份与来源身份键（artifact 组 + execution 组）
_SHARED_ARTIFACT_KEYS = ("source_release_oid", "source_process_oid")
_SHARED_EXECUTION_KEYS = (
    "consumer_project_uid",
    "quant_lab_release_oid",
    "quant_lab_process_oid",
    "command_identity",
)


class P6ClosureBlocked(Exception):
    """typed reason code 阻断（partial 时 journal 已 append，mutation 不回滚）。"""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class P6ClosurePlanV1:
    """IF-10 输出：零写 fresh precheck 产物（不落库；apply 前重算比对 digest）。"""

    schema_version: int
    kind: str
    plan_id: str
    inputs: Mapping[str, Any]
    precheck: Mapping[str, Any]
    fu_candidates: tuple[Mapping[str, Any], ...]
    dq06_baseline_statement: str
    ready: bool
    blockers: tuple[str, ...]
    plan_digest: str


@dataclass(frozen=True, slots=True)
class P6TerminalResultV1:
    """IF-11 成功输出：一次 closure 唯一（存在即拒绝重复收口）。"""

    schema_version: int
    kind: str
    terminal_id: str
    plan_digest: str
    closed_cr_ids: tuple[str, ...]
    closed_work_ids: tuple[str, ...]
    active_zero_proof: bool
    stale_zero_proof: bool
    surviving_candidates: tuple[Mapping[str, Any], ...]
    dq06_baseline_carried: str
    phase_transition_precheck: str
    completed_at: str
    result_digest: str


@dataclass(frozen=True, slots=True)
class RecoveryInspection:
    """IF-12 输出：journal 只读检视（不自动续跑；续跑=fresh plan 重试）。"""

    journal_ref: str
    entries: tuple[Mapping[str, Any], ...]
    completed_refs: tuple[str, ...]
    remaining_refs: tuple[str, ...]
    last_error: str


@dataclass(frozen=True, slots=True)
class P6ClosureAuthorizationV1:
    """P6 收口授权（绑定 plan_digest；兼作 WorkCloseAuthorizationProtocol 实现）。"""

    schema_version: int
    kind: str
    authorization_id: str
    plan_digest: str
    cr_id: str
    work_ids: tuple[str, ...]
    expires_at: str
    single_use: bool

    def validate_for(self, plan: Any) -> None:
        work_id = getattr(plan, "work_id", None)
        if work_id is not None:  # Work close plan：成员校验（apply_work_close 消费）
            if self.single_use is not True or work_id not in self.work_ids:
                raise ValueError("p6-closure authorization does not cover this work close")
            return
        if (
            self.schema_version != 1
            or self.kind != P6_CLOSURE_AUTHORIZATION_KIND
            or self.single_use is not True
        ):
            raise ValueError("p6-closure authorization kind/version/single_use mismatch")
        if self.plan_digest != plan.plan_digest or self.cr_id != plan.inputs.get("cr_id"):
            raise ValueError("p6-closure authorization does not bind the current plan")
        if tuple(self.work_ids) != tuple(plan.inputs.get("work_ids") or ()):
            raise ValueError("p6-closure authorization work set mismatch")
        expiry = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        if expiry.tzinfo is None or expiry.astimezone(UTC) <= datetime.now(UTC):
            raise ValueError("p6-closure authorization is expired")


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _closure_dir(project_root: Path) -> Path:
    return resolve_process_ref(Path(project_root).resolve(), CLOSURE_DIR_REF)


def _load_archived(project_root: Path, result_ref: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """读归档 replay result（result.json + ingestion-receipt.yaml）。"""
    base = resolve_process_ref(Path(project_root).resolve(), result_ref)
    if not base.is_dir():
        raise P6ClosureBlocked(CLOSURE_TARGET_MISSING, f"archived result missing: {result_ref}")
    payload = json.loads((base / "result.json").read_bytes().decode("utf-8"))
    receipt = yaml.safe_load((base / "ingestion-receipt.yaml").read_bytes().decode("utf-8"))
    return payload, receipt


def _stale_archive_count(project_root: Path) -> int:
    base = require_process_route(Path(project_root).resolve()).process_root / "evidence" / "CR-076" / "consumer-acceptance"
    if not base.is_dir():
        return 0
    return sum(1 for d in base.iterdir() if d.is_dir() and (not (d / "result.json").is_file() or not (d / "ingestion-receipt.yaml").is_file()))


def plan_p6_closure(
    project_root: Path,
    *,
    replay_result_refs: tuple[str, ...],
    attestation_ref: str,
    publication_receipts: tuple[Mapping[str, Any], ...],
    observation_ref: str,
    installation_receipt: Mapping[str, Any],
    fu_candidates: tuple[Mapping[str, Any], ...] = (),
    cr_id: str,
    work_ids: tuple[str, ...],
    dq06_baseline_statement: str = "",
) -> P6ClosurePlanV1:
    """IF-10：零写 fresh precheck；B1+B2 校验清单任一不满足 → blockers（typed）。"""
    root = Path(project_root).resolve()
    blockers: list[str] = []
    archived: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    by_variant: dict[str, tuple[str, dict[str, Any], dict[str, Any]]] = {}
    for ref in replay_result_refs:
        payload, receipt = _load_archived(root, ref)
        archived.append((ref, payload, receipt))
        by_variant.setdefault(str(payload.get("variant") or ""), (ref, payload, receipt))
    b1, b2 = by_variant.get(SOURCE_CANDIDATE), by_variant.get(INSTALLED_ARTIFACT)
    if len(archived) != 2 or len(by_variant) != 2 or b1 is None or b2 is None:
        blockers.append(VARIANT_CARDINALITY_VIOLATED)
    if b1 is not None and b2 is not None:
        if str(b1[2].get("imported_at") or "") > str(b2[2].get("imported_at") or ""):
            blockers.append(VARIANT_ORDER_VIOLATED)
        diverged: list[str] = []
        for section, keys in (("artifact", _SHARED_ARTIFACT_KEYS), ("execution", _SHARED_EXECUTION_KEYS)):
            for key in keys:
                if (b1[1].get(section) or {}).get(key) != (b2[1].get(section) or {}).get(key):
                    diverged.append(f"{section}.{key}")
        if not str((b1[1].get("artifact") or {}).get("source_tree_digest") or ""):
            diverged.append("artifact.source_tree_digest")
        if diverged:
            blockers.append(VARIANT_IDENTITY_DIVERGED)
    guard = plan_cr076_release_close_guard(root, attestation_ref=attestation_ref, publication_receipts=publication_receipts, observation_ref=observation_ref, acceptance_result_ref=f"{(b2 or ('',))[0]}/result.json", installation_receipt=installation_receipt)
    if not guard.ready:
        blockers.append(ATTESTATION_BINDING_MISMATCH)
    process_root = require_process_route(root).process_root
    active_refs = load_project(process_root).active_work_refs
    for work_id in work_ids:
        try:
            load_work(process_root, work_id)
        except Exception:
            blockers.append(CLOSURE_TARGET_MISSING)
            break
    try:
        if not resolve_process_ref(root, f"process/changes/{cr_id}.md").is_file():
            blockers.append(CLOSURE_TARGET_MISSING)
    except Exception:
        blockers.append(CLOSURE_TARGET_MISSING)
    inputs: dict[str, Any] = {
        "b1_result_ref": (b1 or ("", {}, {}))[0],
        "b2_result_ref": (b2 or ("", {}, {}))[0],
        "attestation_ref": attestation_ref,
        "observation_ref": observation_ref,
        "attestation_digest": guard.attestation_digest,
        "publication_receipt_digests": [str(r.get("receipt_digest") or "") for r in publication_receipts],
        "observation_receipt_digest": guard.observation_receipt_digest,
        "guard_digest": canonical_digest({"blockers": list(guard.blockers), "attestation": guard.attestation_digest}),
        "cr_id": cr_id,
        "work_ids": list(work_ids),
    }
    precheck: dict[str, Any] = {
        "active_cr_ids": [cr_id],
        "active_work_ids": [ref for ref in active_refs if ref.replace("works/", "").replace("/WORK.yaml", "") in work_ids],
        "stale_refs_count": _stale_archive_count(root),
        "fresh_at": _now(),
    }
    ordered = tuple(sorted(set(blockers)))
    document = {
        "schema_version": 1,
        "kind": P6_CLOSURE_PLAN_KIND,
        "inputs": inputs,
        "precheck": precheck,
        "fu_candidates": [dict(item) for item in fu_candidates],
        "dq06_baseline_statement": dq06_baseline_statement,
        "blockers": list(ordered),
    }
    # fresh_at 是展示时间戳而非实质输入：不参与 plan_digest（否则跨秒 fresh 重算恒 PLAN_DRIFTED）
    digest_document = dict(document, precheck={k: v for k, v in precheck.items() if k != "fresh_at"})
    plan_digest = canonical_digest(digest_document)
    return P6ClosurePlanV1(1, P6_CLOSURE_PLAN_KIND, f"P6-{plan_digest[:12]}", inputs, precheck, tuple(fu_candidates), dq06_baseline_statement, not ordered, ordered, plan_digest)


def _journal_append(project_root: Path, event: dict[str, Any]) -> Path:
    journal = _closure_dir(project_root) / JOURNAL_NAME
    journal.parent.mkdir(parents=True, exist_ok=True)
    with journal.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n")
    return journal


def apply_p6_closure(
    project_root: Path,
    plan: P6ClosurePlanV1,
    authorization: P6ClosureAuthorizationV1,
    *,
    publication_receipts: tuple[Mapping[str, Any], ...],
    installation_receipt: Mapping[str, Any],
    work_close_inputs: Mapping[str, Mapping[str, Any]],
    cr_close_input: Mapping[str, Any],
) -> P6TerminalResultV1:
    """IF-11：fresh 重验 → guard 重跑 → Work→CR 逐对象 close → 归零后 terminal。

    partial → journal append（completed/remaining）+ P6ClosureBlocked；已 close 对象
    不回滚，fresh plan 重试幂等续跑。native close 参数面由调用方供给（§8 偏离）。
    """
    root = Path(project_root).resolve()
    authorization.validate_for(plan)
    if not plan.ready:
        raise P6ClosureBlocked(P6_CLOSURE_BLOCKED, f"plan blockers: {list(plan.blockers)}")
    declared = plan.inputs
    fresh = plan_p6_closure(
        root,
        replay_result_refs=(str(declared.get("b1_result_ref") or ""), str(declared.get("b2_result_ref") or "")),
        attestation_ref=str(declared.get("attestation_ref") or ""),
        publication_receipts=publication_receipts,
        observation_ref=str(declared.get("observation_ref") or ""),
        installation_receipt=installation_receipt,
        fu_candidates=plan.fu_candidates,
        cr_id=str(declared.get("cr_id") or ""),
        work_ids=tuple(declared.get("work_ids") or ()),
        dq06_baseline_statement=plan.dq06_baseline_statement,
    )
    if fresh.plan_digest != plan.plan_digest:
        raise P6ClosureBlocked(PLAN_DRIFTED, "fresh precheck differs from authorized plan")
    closure_dir = _closure_dir(root)
    terminal_path = closure_dir / TERMINAL_NAME
    if terminal_path.exists() or terminal_path.is_symlink():
        raise P6ClosureBlocked(TERMINAL_ALREADY_EXISTS, "P6 terminal result already exists")
    process_root = require_process_route(root).process_root
    closed_work_ids: list[str] = []
    remaining = [*(plan.inputs.get("work_ids") or []), str(plan.inputs.get("cr_id") or "")]
    try:
        for work_id in declared.get("work_ids") or []:
            close_input = work_close_inputs.get(work_id) or {}
            result_ref = str(close_input.get("result_ref") or "")
            if result_ref and not result_ref.startswith("process/"):  # native 契约 = canonical 逻辑 ref
                result_ref = f"process/{result_ref}"
            work_plan = plan_work_close(process_root, work_id, expected_status=str(close_input.get("expected_status") or "active"), outcome=str(close_input.get("outcome") or "completed"), result_ref=result_ref)
            # native manifest 按 authorization_id 防重放：多 work 收口按 work 派生子授权 ID
            apply_work_close(process_root, work_plan, replace(authorization, authorization_id=f"{authorization.authorization_id}-{work_id}"))
            closed_work_ids.append(work_id)
            remaining.remove(work_id)
        close_cr(root, str(plan.inputs.get("cr_id") or ""), **dict(cr_close_input))
        remaining.remove(str(plan.inputs.get("cr_id") or ""))
    except Exception as exc:
        _journal_append(
            root,
            {
                "event_type": "partial-closure",
                "plan_digest": plan.plan_digest,
                "authorization_id": authorization.authorization_id,
                "completed": closed_work_ids,
                "remaining": remaining,
                "error": f"{type(exc).__name__}: {exc}",
                "at": _now(),
            },
        )
        code = getattr(exc, "code", P6_CLOSURE_BLOCKED)
        raise P6ClosureBlocked(code, f"partial closure: completed={closed_work_ids}") from exc
    active_refs = load_project(process_root).active_work_refs
    work_ids = tuple(plan.inputs.get("work_ids") or ())
    active_zero = not any(
        ref.replace("works/", "").replace("/WORK.yaml", "") in work_ids for ref in active_refs
    )
    completed_at = _now()
    document: dict[str, Any] = {
        "schema_version": 1,
        "kind": P6_TERMINAL_KIND,
        "terminal_id": f"P6T-{plan.plan_digest[:12]}",
        "plan_digest": plan.plan_digest,
        "closed_cr_ids": [str(plan.inputs.get("cr_id") or "")],
        "closed_work_ids": list(closed_work_ids),
        "active_zero_proof": active_zero,
        "stale_zero_proof": int(plan.precheck.get("stale_refs_count") or 0) == 0,
        "surviving_candidates": [dict(item) for item in plan.fu_candidates if str(item.get("revisit_condition") or "") != "resolved"],
        "dq06_baseline_carried": plan.dq06_baseline_statement,
        "phase_transition_precheck": "not-executed",
        "completed_at": completed_at,
    }
    document["result_digest"] = canonical_digest(document)
    terminal = P6TerminalResultV1(**document)  # tuple 注解字段以 list 落盘（yaml 自然形态）
    closure_dir.mkdir(parents=True, exist_ok=True)
    staged = terminal_path.with_name(f".staged-{TERMINAL_NAME}")
    staged.write_bytes(yaml.safe_dump(document, sort_keys=True, allow_unicode=True).encode("utf-8"))
    staged.replace(terminal_path)
    return terminal


def recover_p6_closure(
    project_root: Path,
    *,
    journal_ref: str = f"{CLOSURE_DIR_REF}/{JOURNAL_NAME}",
) -> RecoveryInspection:
    """IF-12：journal 只读检视（不自动续跑；续跑 = fresh plan 幂等重试）。"""
    root = Path(project_root).resolve()
    journal = resolve_process_ref(root, journal_ref)
    entries: list[Mapping[str, Any]] = [json.loads(line) for line in journal.read_bytes().decode("utf-8").splitlines() if line.strip()] if journal.is_file() else []
    completed = [ref for entry in entries for ref in entry.get("completed") or []]
    remaining = [ref for entry in entries for ref in entry.get("remaining") or []]
    return RecoveryInspection(
        journal_ref=journal_ref,
        entries=tuple(entries),
        completed_refs=tuple(dict.fromkeys(completed)),
        remaining_refs=tuple(dict.fromkeys(remaining)),
        last_error=str(entries[-1].get("error") or "") if entries else "",
    )


__all__ = [
    "CLOSURE_DIR_REF",
    "JOURNAL_NAME",
    "P6ClosureAuthorizationV1",
    "P6ClosureBlocked",
    "P6ClosurePlanV1",
    "P6TerminalResultV1",
    "RecoveryInspection",
    "TERMINAL_NAME",
    "apply_p6_closure",
    "plan_p6_closure",
    "recover_p6_closure",
]
