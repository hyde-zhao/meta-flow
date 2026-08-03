"""已退役 C0 V2 的零副作用兼容层。

本模块保留历史 Python / CLI importer 需要的类型与函数名，但 C0 V2 不再拥有
任何计划、授权、事务、锁、receipt 或 Projection Kernel 写入能力。所有入口均
返回可稳定重放的 ``BLOCKED/C0_V2_RETIRED`` 载荷。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meta_flow.project.onboarding_contract import canonical_digest

C0_CUTOVER_OPERATION = "route.c0-cutover-apply"
C0_AUTHORIZATION_SOURCE = "retired-compatibility"
C0_AUTHORIZATION_KIND = "c0-cutover-v2-retired"
C0_WRITE_OWNER = ""
C0_PLAN_KIND = "C0CutoverPlanV2"
C0_RESULT_KIND = "C0CutoverReceiptV2"
C0_TARGET_COUNT = 0
RETIRED_REASON = "C0_V2_RETIRED"
# 保留审计 registry 分类；retired stub 从不解析或读取该逻辑引用。
RETIRED_GATE_LEDGER_REF = "process/state/GATE-LEDGER.ndjson"


@dataclass(frozen=True)
class C0CutoverTargetV2:
    """保留导入兼容性；退役计划永远不产生 target。"""

    order: int = 0
    logical_ref: str = ""
    path: Path | None = None
    before: str | None = None
    after: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"order": self.order, "logical_ref": self.logical_ref}


@dataclass(frozen=True)
class C0CutoverPlanV2:
    """历史 plan shape 的 fail-closed 表示；不会读取任何输入路径。"""

    cr_id: str = ""
    work_id: str = ""
    decision: str = "BLOCKED"
    blockers: tuple[str, ...] = (RETIRED_REASON,)
    retired_diagnostic_ref: str = RETIRED_GATE_LEDGER_REF

    @property
    def targets(self) -> tuple[C0CutoverTargetV2, ...]:
        return ()

    @property
    def mutation_allowlist(self) -> tuple[str, ...]:
        return ()

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": 2,
            "kind": C0_PLAN_KIND,
            "operation": "route.c0-cutover-plan",
            "decision": "BLOCKED",
            "dry_run": True,
            "actual_mutation_count": 0,
            "planned_mutation_count": 0,
            "cr_id": self.cr_id,
            "work_id": self.work_id,
            "targets": [],
            "mutation_allowlist": [],
            "rollback_order": [],
            "blockers": [RETIRED_REASON],
        }
        payload["plan_digest"] = canonical_digest(payload)
        return payload


@dataclass(frozen=True)
class C0CutoverAuthorizationV2:
    """仅接受历史授权对象的语法，不授予任何 mutation 权限。"""

    payload: Mapping[str, Any]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> C0CutoverAuthorizationV2:
        if not isinstance(payload, Mapping):
            raise ValueError("C0 V2 authorization must be an object")
        return cls(dict(payload))


@dataclass(frozen=True)
class C0CutoverReceiptV2:
    """历史 apply 输出的零写入 blocked receipt。"""

    plan_digest: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "kind": C0_RESULT_KIND,
            "status": "BLOCKED",
            "decision": "BLOCKED",
            "reason": RETIRED_REASON,
            "plan_digest": self.plan_digest,
            "mutation_count": 0,
            "path_refs": [],
            "receipt_ref": "",
            "recovery_refs": [],
        }


def build_c0_cutover_plan(
    *,
    project_root: Path,
    work_id: str,
    semantic_plan: Any = None,
    cr_id: str = "",
    diagnostic_ref: str = RETIRED_GATE_LEDGER_REF,
) -> C0CutoverPlanV2:
    """返回 retired plan；参数只为历史调用方保留且绝不解引用。"""

    del project_root, semantic_plan
    return C0CutoverPlanV2(
        cr_id=cr_id, work_id=work_id, retired_diagnostic_ref=diagnostic_ref
    )


def validate_c0_cutover_authorization(
    plan: C0CutoverPlanV2,
    authorization: C0CutoverAuthorizationV2 | None,
) -> None:
    """保留调用点；退役状态下不验证也不声明授权。"""

    del plan, authorization


def apply_c0_cutover(
    *,
    project_root: Path,
    work_id: str,
    expected_plan_digest: str = "",
    authorization: C0CutoverAuthorizationV2 | None = None,
    semantic_plan_factory: Any = None,
    **_ignored: Any,
) -> dict[str, Any]:
    """返回 zero-write blocked receipt；不会读取 root 或调用 factory。"""

    del project_root, work_id, authorization, semantic_plan_factory
    return C0CutoverReceiptV2(plan_digest=expected_plan_digest).as_dict()
