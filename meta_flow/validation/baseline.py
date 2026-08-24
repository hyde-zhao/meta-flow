"""Phase green baseline lifecycle（STORY-CR075-S06，MF-GAP-04）。

`meta-flow phase-baseline plan|apply|check|invalidate|inspect`：
- baseline 绑定 phase_id + fingerprint 集（source/command/environment/
  provider/manifest，与 S04 共享归属算法）
- apply 走 exact-file typed transaction（target namespace=system，P0 成果）
- baseline bytes append-only（修订 version+1，永不改写历史）
- full 失败与 baseline 对比输出五类归属（既存漂移/环境漂移/provider
  漂移/新回归/不可归属）
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meta_flow.execution_control.contract import canonical_digest
from meta_flow.execution_control.exact_file_transaction import (
    ExactFileAuthorizationV1,
    ExactFileTargetV1,
    apply_exact_file_plan,
    build_exact_file_plan,
)

SCHEMA_VERSION = 1
BASELINE_FILENAME = "BASELINE.json"

_EXISTING_DRIFT_CODES = {
    "SOURCE_FINGERPRINT_DRIFT",
    "PROFILE_DRIFT",
    "SOURCE_MANIFEST_DRIFT",
}
_ENVIRONMENT_DRIFT_CODES = {"ENVIRONMENT_DRIFT"}
_PROVIDER_DRIFT_CODES = {"PROVIDER_IDENTITY_DRIFT"}


@dataclass(frozen=True)
class PhaseGreenBaselineV1:
    """Phase 绿基线（evidence 性质；修订 append version+1）。"""

    schema_version: int
    phase_id: str
    version: int
    scope_digest: str
    fingerprint: dict[str, str]
    entries: tuple[dict[str, str], ...]
    created_at: str = ""
    invalidated_at: str = ""
    invalidation_reasons: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": "PhaseGreenBaselineV1",
            "phase_id": self.phase_id,
            "version": self.version,
            "scope_digest": self.scope_digest,
            "fingerprint": dict(sorted(self.fingerprint.items())),
            "entries": [dict(entry) for entry in self.entries],
            "created_at": self.created_at,
            "invalidated_at": self.invalidated_at,
            "invalidation_reasons": list(self.invalidation_reasons),
        }


def baseline_ref(phase_ref: str) -> str:
    parts = phase_ref.strip("/").split("/")
    return "/".join([*parts[:-1], BASELINE_FILENAME]) if parts[-1].endswith(".yaml") else "/".join(
        [*parts, BASELINE_FILENAME]
    )


def load_baseline(process_root: Path, phase_ref: str) -> dict[str, Any] | None:
    path = process_root / baseline_ref(phase_ref)
    if not path.is_file() or path.is_symlink():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def plan_baseline(
    process_root: Path,
    *,
    phase_ref: str,
    entries: list[dict[str, str]],
    fingerprint: dict[str, str],
) -> dict[str, Any]:
    """零写收集当前绿集并产出冻结计划。"""

    if not phase_ref.strip("/"):
        return _blocked("PHASE_REF_INVALID")
    normalized = tuple(
        {"check_id": str(item.get("check_id") or ""), "result_digest": str(item.get("result_digest") or "")}
        for item in sorted(entries, key=lambda item: str(item.get("check_id") or ""))
        if str(item.get("check_id") or "")
    )
    if not normalized:
        return _blocked("BASELINE_ENTRIES_EMPTY")
    # 路径安全：phase_ref 拒绝绝对路径/越界段/symlink 占用。
    candidate = Path(phase_ref)
    if candidate.is_absolute() or any(
        part in {"", ".", ".."} for part in candidate.parts
    ):
        return _blocked("PHASE_REF_UNSAFE")
    phase_path = process_root / phase_ref
    if phase_path.is_symlink() or not phase_path.is_file():
        return _blocked("PHASE_FILE_MISSING")
    scope_digest = canonical_digest(
        {"phase_ref": phase_ref, "entries": [dict(entry) for entry in normalized]}
    )
    existing = load_baseline(process_root, phase_ref)
    # 5e 整改：valid baseline 不可原位覆盖；只有已失效基线才允许 rebaseline
    # （version+1）。历史保留模型：单一 BASELINE.json 承载当前代，失效代以
    # version 单调递增 + invalidated_at/reasons append 记录，不可回退重写。
    if existing and not existing.get("invalidated_at"):
        return _blocked("BASELINE_ALREADY_ACTIVE")
    next_version = (int(existing.get("version") or 0) + 1) if existing else 1
    payload = PhaseGreenBaselineV1(
        SCHEMA_VERSION,
        phase_ref,
        next_version,
        scope_digest,
        dict(sorted(fingerprint.items())),
        normalized,
    ).as_dict()
    after_bytes = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    ref = baseline_ref(phase_ref)
    before = (process_root / ref).read_bytes() if (process_root / ref).is_file() else b""
    import hashlib

    target = ExactFileTargetV1(
        ref,
        bool(before),
        hashlib.sha256(before).hexdigest(),
        after_bytes,
        hashlib.sha256(after_bytes).hexdigest(),
        namespace="system",
    )
    exact_plan = build_exact_file_plan(
        "phase-baseline.apply",
        (target,),
        semantic_binding_digest=canonical_digest(
            {"phase_ref": phase_ref, "scope_digest": scope_digest}
        ),
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "PhaseBaselinePlanV1",
        "decision": "READY",
        "phase_ref": phase_ref,
        "baseline_ref": ref,
        "scope_digest": scope_digest,
        "entries": [dict(entry) for entry in normalized],
        "exact_plan": exact_plan.as_dict(),
        "exact_plan_digest": exact_plan.plan_digest,
        "mutation_count": 0,
    }


def apply_baseline(
    process_root: Path,
    *,
    plan_payload: dict[str, Any],
    authorization: ExactFileAuthorizationV1,
) -> dict[str, Any]:
    """typed apply：exact-file 事务（system namespace target）。"""

    exact_payload = dict(plan_payload.get("exact_plan") or {})
    targets = []
    import base64

    for item in exact_payload.get("targets", []):
        targets.append(
            ExactFileTargetV1(
                str(item["ref"]),
                bool(item["before_exists"]),
                str(item["before_digest"]),
                base64.b64decode(str(item["after_bytes_b64"]), validate=True),
                str(item["after_digest"]),
                namespace=str(item.get("namespace") or "system"),
            )
        )
    exact_plan = build_exact_file_plan(
        "phase-baseline.apply",
        tuple(targets),
        semantic_binding_digest=str(exact_payload.get("semantic_binding_digest") or ""),
    )
    if exact_plan.plan_digest != plan_payload.get("exact_plan_digest"):
        return _blocked("PLAN_DIGEST_MISMATCH")
    authorization.validate_for(exact_plan)
    return apply_exact_file_plan(process_root, exact_plan, authorization)


def check_baseline(
    process_root: Path,
    *,
    phase_ref: str,
    current_fingerprint: dict[str, str],
    failing_checks: list[str],
) -> dict[str, Any]:
    """现集 vs baseline：diff + 五类归属（与 S04 共享算法）。"""

    baseline = load_baseline(process_root, phase_ref)
    if baseline is None:
        return _blocked("BASELINE_MISSING")
    if baseline.get("invalidated_at"):
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "PhaseBaselineCheckV1",
            "decision": "NEEDS_REVIEW",
            "reason_codes": ["BASELINE_INVALIDATED"],
            "invalidation_reasons": list(baseline.get("invalidation_reasons") or []),
            "mutation_count": 0,
        }
    reasons: list[str] = []
    stored = dict(baseline.get("fingerprint") or {})
    comparisons = (
        ("SOURCE_FINGERPRINT_DRIFT", "source_fingerprint"),
        ("COMMAND_IDENTITY_DRIFT", "command_identity"),
        ("ENVIRONMENT_DRIFT", "environment"),
        ("PROVIDER_IDENTITY_DRIFT", "provider_identity_digest"),
        ("SOURCE_MANIFEST_DRIFT", "source_manifest_digest"),
        ("PROFILE_DRIFT", "profile_digest"),
    )
    for code, key in comparisons:
        if key in current_fingerprint and str(current_fingerprint[key]) != str(
            stored.get(key, current_fingerprint[key])
        ):
            reasons.append(code)
    reason_set = set(reasons)
    green = {str(entry.get("check_id") or "") for entry in baseline.get("entries") or []}
    failing = {str(item) for item in failing_checks if str(item)}
    regression = sorted(failing & green)
    # 5c 整改：归属矩阵--
    #   baseline 外失败 -> NEW_REGRESSION；
    #   绿转失败 + 源/manifest/profile 漂移 -> EXISTING_SOURCE_DRIFT；
    #   绿转失败 + 仅环境漂移 -> ENVIRONMENT_DRIFT；
    #   绿转失败 + provider 漂移（无源/环境漂移）-> PROVIDER_DRIFT；
    #   绿转失败且无任何 fingerprint 漂移可解释 -> UNATTRIBUTABLE。
    attribution: dict[str, list[str]] = {"NEW_REGRESSION": sorted(failing - green)}
    if regression:
        if reason_set & _EXISTING_DRIFT_CODES:
            attribution["EXISTING_SOURCE_DRIFT"] = regression
        elif reason_set & _ENVIRONMENT_DRIFT_CODES:
            attribution["ENVIRONMENT_DRIFT"] = regression
        elif reason_set & _PROVIDER_DRIFT_CODES:
            attribution["PROVIDER_DRIFT"] = regression
        else:
            attribution["UNATTRIBUTABLE"] = regression
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "PhaseBaselineCheckV1",
        # 5d 整改：存在 failing 不得无条件 PASS。
        "decision": "FAILINGS_PRESENT" if failing else "PASS",
        "phase_ref": phase_ref,
        "baseline_version": int(baseline.get("version") or 0),
        "drift_reason_codes": sorted(reason_set),
        "failing_count": len(failing),
        "attribution": {key: value for key, value in attribution.items() if value},
        "mutation_count": 0,
    }


def plan_invalidation(
    process_root: Path,
    *,
    phase_ref: str,
    reasons: list[str],
    at: str,
) -> dict[str, Any]:
    """5a 整改：失效走 typed plan（零写；apply 需 exact-file authorization）。"""

    baseline = load_baseline(process_root, phase_ref)
    if baseline is None:
        return _blocked("BASELINE_MISSING")
    if baseline.get("invalidated_at"):
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "PhaseBaselineInvalidationPlanV1",
            "decision": "NO_CHANGE",
            "idempotent": True,
            "version": int(baseline.get("version") or 0),
            "mutation_count": 0,
        }
    payload = dict(baseline)
    payload["version"] = int(baseline.get("version") or 0) + 1
    payload["invalidated_at"] = at
    payload["invalidation_reasons"] = sorted(set(str(item) for item in reasons))
    ref = baseline_ref(phase_ref)
    import hashlib

    before = (process_root / ref).read_bytes()
    after_bytes = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    target = ExactFileTargetV1(
        ref,
        True,
        hashlib.sha256(before).hexdigest(),
        after_bytes,
        hashlib.sha256(after_bytes).hexdigest(),
        namespace="system",
    )
    exact_plan = build_exact_file_plan(
        "phase-baseline.invalidate",
        (target,),
        semantic_binding_digest=canonical_digest(
            {"phase_ref": phase_ref, "invalidated_at": at, "reasons": sorted(set(reasons))}
        ),
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "PhaseBaselineInvalidationPlanV1",
        "decision": "READY",
        "phase_ref": phase_ref,
        "baseline_ref": ref,
        "next_version": payload["version"],
        "invalidation_reasons": sorted(set(str(item) for item in reasons)),
        "exact_plan": exact_plan.as_dict(),
        "exact_plan_digest": exact_plan.plan_digest,
        "mutation_count": 0,
    }


def apply_invalidation(
    process_root: Path,
    *,
    plan_payload: dict[str, Any],
    authorization: ExactFileAuthorizationV1,
) -> dict[str, Any]:
    """typed apply：与 baseline apply 同一 exact-file 事务内核（可恢复）。"""

    import base64

    exact_payload = dict(plan_payload.get("exact_plan") or {})
    targets = []
    for item in exact_payload.get("targets", []):
        targets.append(
            ExactFileTargetV1(
                str(item["ref"]),
                bool(item["before_exists"]),
                str(item["before_digest"]),
                base64.b64decode(str(item["after_bytes_b64"]), validate=True),
                str(item["after_digest"]),
                namespace=str(item.get("namespace") or "system"),
            )
        )
    exact_plan = build_exact_file_plan(
        "phase-baseline.invalidate",
        tuple(targets),
        semantic_binding_digest=str(exact_payload.get("semantic_binding_digest") or ""),
    )
    if exact_plan.plan_digest != plan_payload.get("exact_plan_digest"):
        return _blocked("PLAN_DIGEST_MISMATCH")
    authorization.validate_for(exact_plan)
    return apply_exact_file_plan(process_root, exact_plan, authorization)


def inspect_baseline(process_root: Path, *, phase_ref: str) -> dict[str, Any]:
    """审计视图（零 mutation）。"""

    baseline = load_baseline(process_root, phase_ref)
    if baseline is None:
        return _blocked("BASELINE_MISSING")
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "PhaseBaselineInspectV1",
        "decision": "PASS",
        "baseline": baseline,
        "mutation_count": 0,
    }


def _blocked(reason: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "decision": "BLOCKED",
        "reason_codes": [reason],
        "mutation_count": 0,
    }


def baseline_main(argv: list[str] | None = None) -> int:
    """CLI：``meta-flow phase-baseline plan|apply|check|invalidate|inspect``。"""

    parser = argparse.ArgumentParser(prog="meta-flow phase-baseline")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("command", choices=("plan", "apply", "check", "invalidate", "inspect"))
    parser.add_argument("--phase-ref", required=True)
    parser.add_argument("--entries", type=Path, default=None)
    parser.add_argument("--fingerprint", type=Path, default=None)
    parser.add_argument("--current-fingerprint", type=Path, default=None)
    parser.add_argument("--failing-checks", type=Path, default=None)
    parser.add_argument("--reasons", default="")
    parser.add_argument("--at", default="")
    parser.add_argument("--plan", type=Path, default=None)
    parser.add_argument("--authorization", type=Path, default=None)
    parsed = parser.parse_args(argv or [])
    from meta_flow.project.process_route import require_process_route

    try:
        process_root = require_process_route(parsed.project_root.resolve()).process_root
    except Exception as exc:
        print(
            json.dumps(
                {"decision": "BLOCKED", "reason_codes": ["PROCESS_ROUTE_UNHEALTHY"],
                 "detail": f"{type(exc).__name__}: {exc}", "mutation_count": 0}
            )
        )
        return 2

    def _load_json(path: Path | None) -> dict[str, Any]:
        if path is None:
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    try:
        if parsed.command == "plan":
            payload = plan_baseline(
                process_root,
                phase_ref=parsed.phase_ref,
                entries=list(_load_json(parsed.entries).get("entries", [])),
                fingerprint=dict(_load_json(parsed.fingerprint)),
            )
        elif parsed.command == "apply":
            from meta_flow.execution_control.exact_file_transaction import (
                ExactFileAuthorizationV1 as _Auth,
            )

            plan_payload = _load_json(parsed.plan)
            authorization = _Auth.from_mapping(_load_json(parsed.authorization))
            payload = apply_baseline(
                process_root, plan_payload=plan_payload, authorization=authorization
            )
        elif parsed.command == "check":
            payload = check_baseline(
                process_root,
                phase_ref=parsed.phase_ref,
                current_fingerprint=dict(_load_json(parsed.current_fingerprint)),
                failing_checks=list(_load_json(parsed.failing_checks).get("failing", [])),
            )
        elif parsed.command == "invalidate":
            if parsed.plan is not None and parsed.authorization is not None:
                plan_payload = _load_json(parsed.plan)
                authorization = ExactFileAuthorizationV1.from_mapping(
                    _load_json(parsed.authorization)
                )
                payload = apply_invalidation(
                    process_root, plan_payload=plan_payload, authorization=authorization
                )
            elif parsed.plan is None and parsed.authorization is None:
                # 零写 plan 阶段：产出 typed 失效计划（apply 需重新带 --plan/--authorization）。
                payload = plan_invalidation(
                    process_root,
                    phase_ref=parsed.phase_ref,
                    reasons=[item for item in parsed.reasons.split(",") if item],
                    at=parsed.at,
                )
            else:
                payload = _blocked("INVALIDATION_REQUIRES_PLAN_AND_AUTHORIZATION")
        else:
            payload = inspect_baseline(process_root, phase_ref=parsed.phase_ref)
    except (ValueError, KeyError, OSError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {"decision": "BLOCKED", "detail": f"{type(exc).__name__}: {exc}", "mutation_count": 0}
            )
        )
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    decision = str(payload.get("decision") or "")
    return 0 if decision in {"PASS", "READY", "NO_CHANGE"} else 2
