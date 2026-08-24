"""ValidationPolicyV2 公共 CLI（STORY-CR075-S04，MF-BUG-05）。

`meta-flow validation-plan --work-id <id>`：消费 works/<id>/validation-receipts
的 receipt 集，按六维 fingerprint（source/profile/command/environment/
manifest/provider identity）逐 receipt 输出 ``REUSE|RUN`` 与五类归属
（新回归/既存漂移/环境漂移/provider 漂移/不可归属）。

V1 receipt 缺安全字段 → ``RUN``（不伪造 REUSE）。与 checker/doctor 同一
判定源：``validation.policy_v2.evaluate_validation_reuse_request_v2``。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from meta_flow.validation.policy_v2 import evaluate_validation_reuse_request_v2

SCHEMA_VERSION = 2

# 公共 operation owner declaration（S06 整改：mutation 命令须有声明与契约）。
PUBLIC_OPERATION_DECLARATIONS = (
    ("phase-baseline.apply", ("meta-flow", "phase-baseline", "apply")),
    ("phase-baseline.invalidate", ("meta-flow", "phase-baseline", "invalidate")),
)

_EXISTING_DRIFT_CODES = {
    "SOURCE_FINGERPRINT_DRIFT",
    "PROFILE_DRIFT",
    "SOURCE_MANIFEST_DRIFT",
}
_ENVIRONMENT_DRIFT_CODES = {"ENVIRONMENT_DRIFT"}
_PROVIDER_DRIFT_CODES = {"PROVIDER_IDENTITY_DRIFT"}
_V1_MISSING_CODE = "V1_RECEIPT_MISSING_SECURE_FIELD"
_SECURE_FIELDS = (
    "fingerprint_digest",
    "profile_digest",
    "command_identity",
    "environment",
    "source_manifest_digest",
    "provider_identity_digest",
)


def _classify(action: str, reasons: tuple[str, ...], *, has_receipt: bool) -> str:
    if not has_receipt:
        return "NEW_REGRESSION"
    if action == "REUSE":
        return "REUSABLE"
    if "RECEIPT_INVALIDATED_BY_SCOPE_VERSION" in reasons:
        return "INVALIDATED_BY_SCOPE_VERSION"
    if _V1_MISSING_CODE in reasons:
        return "UNATTRIBUTABLE"
    reason_set = set(reasons)
    if reason_set & _PROVIDER_DRIFT_CODES:
        return "PROVIDER_DRIFT"
    if reason_set & _ENVIRONMENT_DRIFT_CODES:
        return "ENVIRONMENT_DRIFT"
    if reason_set & _EXISTING_DRIFT_CODES:
        return "EXISTING_SOURCE_DRIFT"
    return "UNATTRIBUTABLE"


def build_reuse_plan(
    process_root: Path,
    *,
    work_id: str,
    current: dict[str, str],
    declared_checks: list[str] | None = None,
) -> dict[str, Any]:
    """零写构建 ValidationReusePlanV2；五类归属聚合。"""

    receipts_root = process_root / "works" / work_id / "validation-receipts"
    receipts: list[dict[str, Any]] = []
    receipt_names: set[str] = set()
    if receipts_root.is_dir():
        receipt_names = {path.stem for path in receipts_root.glob("*.json")}
    if receipts_root.is_dir():
        for path in sorted(receipts_root.glob("*.json")):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                receipts.append(
                    {
                        "receipt_ref": f"works/{work_id}/validation-receipts/{path.name}",
                        "action": "RUN",
                        "reason_codes": ["RECEIPT_UNREADABLE"],
                        "attribution": "UNATTRIBUTABLE",
                    }
                )
                continue
            missing = [
                field
                for field in _SECURE_FIELDS
                if not str(payload.get(field) or "").strip()
            ]
            # S02+S04 联合回修：scope amendment 已失效的 receipt 强制 RUN，
            # 不得 REUSE（invalidated_by_scope_version / invalidation_reason）。
            invalidated_by = payload.get("invalidated_by_scope_version")
            invalidation_reason = str(payload.get("invalidation_reason") or "")
            request = SimpleNamespace(
                receipt_decision=str(payload.get("decision") or ""),
                partial_mutation=bool(payload.get("partial_mutation")),
                receipt_fingerprint_digest=str(payload.get("fingerprint_digest") or ""),
                current_fingerprint_digest=current.get("source_fingerprint", ""),
                receipt_profile_digest=str(payload.get("profile_digest") or ""),
                current_profile_digest=current.get("profile_digest", ""),
                receipt_command_identity=str(payload.get("command_identity") or ""),
                current_command_identity=current.get("command_identity", ""),
                receipt_environment=str(payload.get("environment") or ""),
                current_environment=current.get("environment", ""),
                receipt_source_manifest_digest=str(payload.get("source_manifest_digest") or ""),
                current_source_manifest_digest=current.get("source_manifest_digest", ""),
                receipt_provider_identity_digest=str(
                    payload.get("provider_identity_digest") or ""
                ),
                current_provider_identity_digest=current.get("provider_identity_digest", ""),
            )
            action, reasons = evaluate_validation_reuse_request_v2(request)
            reason_list = list(reasons)
            if invalidated_by is not None or invalidation_reason:
                action = "RUN"
                reason_list = sorted(
                    {
                        *reason_list,
                        "RECEIPT_INVALIDATED_BY_SCOPE_VERSION",
                    }
                )
            if missing:
                # V1 receipt 缺安全字段：强制 RUN，不伪造 REUSE。
                action = "RUN"
                reason_list = sorted({*reason_list, _V1_MISSING_CODE})
            receipts.append(
                {
                    "receipt_ref": f"works/{work_id}/validation-receipts/{path.name}",
                    "action": action,
                    "reason_codes": reason_list,
                    "attribution": _classify(action, tuple(reason_list), has_receipt=True),
                }
            )
    # declared checks 无对应 receipt：新回归（需要跑）。
    for check in sorted(set(declared_checks or [])):
        if check not in receipt_names:
            receipts.append(
                {
                    "receipt_ref": "",
                    "check_id": check,
                    "action": "RUN",
                    "reason_codes": ["NO_PASS_RECEIPT"],
                    "attribution": "NEW_REGRESSION",
                }
            )
    summary: dict[str, int] = {}
    for item in receipts:
        summary[item["attribution"]] = summary.get(item["attribution"], 0) + 1
    run_count = sum(1 for item in receipts if item["action"] == "RUN")
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "ValidationReusePlanV2",
        "work_id": work_id,
        "decision": "RUN_REQUIRED" if run_count else "PASS",
        "run_count": run_count,
        "receipts": receipts,
        "summary": dict(sorted(summary.items())),
        "mutation_count": 0,
    }


def validation_plan_main(argv: list[str] | None = None) -> int:
    """CLI：``meta-flow validation-plan``（exit 0=PASS）。"""

    parser = argparse.ArgumentParser(prog="meta-flow validation-plan")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--work-id", required=True)
    parser.add_argument("--changed-paths", type=Path, default=None)
    parser.add_argument("--source-fingerprint", default="")
    parser.add_argument("--profile-digest", default="")
    parser.add_argument("--command-identity", default="")
    parser.add_argument("--environment", default="")
    parser.add_argument("--source-manifest-digest", default="")
    parser.add_argument("--provider-identity-digest", default="")
    parser.add_argument("--format", choices=("json",), default="json")
    parsed = parser.parse_args(argv or [])
    declared: list[str] | None = None
    if parsed.changed_paths is not None:
        if not parsed.changed_paths.is_file():
            print(
                json.dumps(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "decision": "BLOCKED",
                        "reason_codes": ["CHANGED_PATHS_FILE_MISSING"],
                        "mutation_count": 0,
                    }
                )
            )
            return 2
        declared = [
            line.strip()
            for line in parsed.changed_paths.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    from meta_flow.project.process_route import require_process_route

    try:
        process_root = require_process_route(parsed.project_root.resolve()).process_root
    except Exception as exc:
        print(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "decision": "BLOCKED",
                    "reason_codes": ["PROCESS_ROUTE_UNHEALTHY"],
                    "detail": f"{type(exc).__name__}: {exc}",
                    "mutation_count": 0,
                }
            )
        )
        return 2
    payload = build_reuse_plan(
        process_root,
        work_id=parsed.work_id,
        current={
            "source_fingerprint": parsed.source_fingerprint,
            "profile_digest": parsed.profile_digest,
            "command_identity": parsed.command_identity,
            "environment": parsed.environment,
            "source_manifest_digest": parsed.source_manifest_digest,
            "provider_identity_digest": parsed.provider_identity_digest,
        },
        declared_checks=declared,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload.get("decision") == "PASS" else 2
