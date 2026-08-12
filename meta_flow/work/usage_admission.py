"""R11 在线用量准入：60/80/100 阈值、stage budget 与 telemetry 语义。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from math import ceil, floor
from pathlib import Path
from typing import Any

from meta_flow.execution_control.contract import canonical_digest
from meta_flow.work.budget import BudgetLimit, WorkUsage
from meta_flow.work.model import load_work
from meta_flow.work.scope import check_scope

STAGE_SHARES = {
    "requirements": 0.20,
    "design": 0.20,
    "implementation": 0.40,
    "verification": 0.20,
}
STAGE_ALIASES = {
    "requirement": "requirements",
    "requirement-confirmation": "requirements",
    "requirements-confirmation": "requirements",
    "solution-design": "design",
    "validation": "verification",
    "verify": "verification",
}
GOVERNANCE_LIMITS = {
    "human_interactions": 3,
    "design_revisions": 2,
    "qa_attempts": 2,
    "final_full_suites": 1,
}
SCOPED_OPERATION_DIMENSIONS = {
    "read": "reads",
    "write": "writes",
    "check": "check_groups",
}
GOVERNANCE_OPERATION_DIMENSIONS = {
    "human-interaction": "human_interactions",
    "design-revision": "design_revisions",
    "qa-attempt": "qa_attempts",
    "final-full-suite": "final_full_suites",
}
SYSTEM_OPERATION_KINDS = {"usage-record"}


def normalize_stage(value: str) -> str:
    normalized = value.strip().lower()
    return STAGE_ALIASES.get(normalized, normalized)


def _stage_limit(limit: BudgetLimit, stage: str) -> BudgetLimit:
    share = STAGE_SHARES[stage]

    def portion(value: int) -> int:
        return max(1, floor(value * share)) if value else 0

    return BudgetLimit(
        reads=portion(limit.reads),
        writes=portion(limit.writes),
        check_groups=portion(limit.check_groups),
        tokens=portion(limit.tokens),
    )


def _add(current: WorkUsage, delta: WorkUsage) -> WorkUsage:
    if "unavailable" in {
        current.token_measurement_status,
        delta.token_measurement_status,
    }:
        return WorkUsage(
            reads=current.reads + delta.reads,
            writes=current.writes + delta.writes,
            check_groups=current.check_groups + delta.check_groups,
            tokens=None,
            token_measurement_status="unavailable",
            unavailable_reason=current.unavailable_reason or delta.unavailable_reason,
        )
    status = (
        "proxy"
        if "proxy"
        in {current.token_measurement_status, delta.token_measurement_status}
        else "measured"
    )
    methods = [item for item in (current.proxy_method, delta.proxy_method) if item]
    return WorkUsage(
        reads=current.reads + delta.reads,
        writes=current.writes + delta.writes,
        check_groups=current.check_groups + delta.check_groups,
        tokens=int(current.tokens or 0) + int(delta.tokens or 0),
        token_measurement_status=status,
        proxy_method=" + ".join(dict.fromkeys(methods)) if status == "proxy" else "",
    )


def _utilization(limit: BudgetLimit, usage: WorkUsage) -> dict[str, int | None]:
    if usage.token_measurement_status == "unavailable":
        token_value: int | None = None
    else:
        token_value = int(usage.tokens or 0)
    actual: dict[str, int | None] = {
        "reads": usage.reads,
        "writes": usage.writes,
        "check_groups": usage.check_groups,
        "tokens": token_value,
    }
    maximum = limit.as_dict()
    result: dict[str, int | None] = {}
    for key, value in actual.items():
        if value is None:
            result[key] = None
        elif maximum[key] == 0:
            result[key] = 0 if value == 0 else 100
        else:
            result[key] = ceil(value * 100 / maximum[key])
    return result


def _usage_values(usage: WorkUsage) -> dict[str, int | None]:
    return {
        "reads": usage.reads,
        "writes": usage.writes,
        "check_groups": usage.check_groups,
        "tokens": (
            None
            if usage.token_measurement_status == "unavailable"
            else int(usage.tokens or 0)
        ),
    }


def _exceeded_dimensions(
    limit: BudgetLimit,
    usage: WorkUsage,
) -> tuple[str, ...]:
    maximum = limit.as_dict()
    return tuple(
        key
        for key, value in _usage_values(usage).items()
        if value is not None and value > maximum[key]
    )


def _at_limit_dimensions(
    limit: BudgetLimit,
    usage: WorkUsage,
) -> tuple[str, ...]:
    maximum = limit.as_dict()
    return tuple(
        key
        for key, value in _usage_values(usage).items()
        if value is not None and maximum[key] > 0 and value == maximum[key]
    )


@dataclass(frozen=True, slots=True)
class UsageAdmissionPlanV1:
    decision: str
    post_action: str
    work_id: str
    event_id: str
    stage: str
    measurement_basis: str
    total_budget: dict[str, int]
    stage_budget: dict[str, int]
    projected_total: dict[str, Any]
    projected_stage: dict[str, Any]
    total_utilization: dict[str, int | None]
    stage_utilization: dict[str, int | None]
    governance_usage: dict[str, dict[str, int]]
    reason_codes: tuple[str, ...]
    ledger_digest: str
    event_digest: str
    plan_digest: str

    @property
    def allowed(self) -> bool:
        return self.decision in {"READY", "REVIEW"}

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "UsageAdmissionPlanV1",
            "decision": self.decision,
            "post_action": self.post_action,
            "work_id": self.work_id,
            "event_id": self.event_id,
            "stage": self.stage,
            "measurement_basis": self.measurement_basis,
            "total_budget": self.total_budget,
            "stage_budget": self.stage_budget,
            "projected_total": self.projected_total,
            "projected_stage": self.projected_stage,
            "thresholds": {
                "review_percent": 60,
                "pause_percent": 80,
                "hard_stop_percent": 100,
                "hard_stop_comparison": "projected_usage > allowed_usage",
            },
            "total_utilization": self.total_utilization,
            "stage_utilization": self.stage_utilization,
            "governance_usage": self.governance_usage,
            "reason_codes": list(self.reason_codes),
            "ledger_digest": self.ledger_digest,
            "event_digest": self.event_digest,
            "plan_digest": self.plan_digest,
            "mutation_count": 0,
        }


def plan_usage_admission(
    process_root: Path,
    work_id: str,
    event: Any,
) -> UsageAdmissionPlanV1:
    """对下一条 exact usage event 做零写、可绑定的前置判定。"""

    from meta_flow.work.usage import load_usage, summarize_usage

    work = load_work(process_root, work_id)
    ledger = load_usage(process_root, work)
    stage = normalize_stage(str(event.stage))
    reasons: list[str] = []
    if stage not in STAGE_SHARES:
        reasons.append("USAGE_STAGE_NOT_BUDGETED")
        stage_current = WorkUsage()
        stage_limit = work.budget
    else:
        stage_limit = _stage_limit(work.budget, stage)
        stage_current = WorkUsage()
        for existing in ledger.events:
            if normalize_stage(existing.stage) == stage:
                stage_current = _add(stage_current, existing.as_usage())
    recorded_event = next(
        (item for item in ledger.events if item.event_id == event.event_id),
        None,
    )
    if recorded_event is not None and recorded_event != event:
        raise ValueError(f"usage event_id conflict: {event.event_id}")
    event_delta = WorkUsage() if recorded_event is not None else event.as_usage()
    projected_total = _add(summarize_usage(ledger), event_delta)
    projected_stage = _add(stage_current, event_delta)
    governance_totals = {
        field: sum(int(getattr(existing, field)) for existing in ledger.events)
        + (0 if recorded_event is not None else int(getattr(event, field)))
        for field in GOVERNANCE_LIMITS
    }
    governance_usage = {
        field: {
            "projected": governance_totals[field],
            "limit": limit,
            "remaining": limit - governance_totals[field],
        }
        for field, limit in GOVERNANCE_LIMITS.items()
    }
    total_utilization = _utilization(work.budget, projected_total)
    stage_utilization = _utilization(stage_limit, projected_stage)
    values = [
        value
        for value in (*total_utilization.values(), *stage_utilization.values())
        if value is not None
    ]
    maximum = max(values, default=0)
    exceeded_total = _exceeded_dimensions(work.budget, projected_total)
    exceeded_stage = _exceeded_dimensions(stage_limit, projected_stage)
    at_total_limit = _at_limit_dimensions(work.budget, projected_total)
    at_stage_limit = _at_limit_dimensions(stage_limit, projected_stage)
    exceeded_governance = [
        field
        for field, limit in GOVERNANCE_LIMITS.items()
        if governance_totals[field] > limit
    ]
    if exceeded_governance:
        decision = "BLOCKED"
        post_action = "BLOCK_EXECUTION"
        reasons.extend(
            f"USAGE_GOVERNANCE_LIMIT_EXCEEDED:{field}"
            for field in exceeded_governance
        )
    elif projected_total.token_measurement_status == "unavailable":
        decision = "BLOCKED"
        post_action = "BLOCK_EXECUTION"
        reasons.append("USAGE_TELEMETRY_UNAVAILABLE")
    elif reasons:
        decision = "BLOCKED"
        post_action = "BLOCK_EXECUTION"
    elif exceeded_total or exceeded_stage:
        decision = "BLOCKED"
        post_action = "BLOCK_EXECUTION"
        reasons.append("USAGE_HARD_STOP_100_PERCENT")
        reasons.extend(
            f"USAGE_TOTAL_LIMIT_EXCEEDED:{field}" for field in exceeded_total
        )
        reasons.extend(
            f"USAGE_STAGE_LIMIT_EXCEEDED:{field}" for field in exceeded_stage
        )
    elif at_total_limit or at_stage_limit:
        decision = "REVIEW"
        post_action = "PAUSE_AFTER_EXECUTION"
        reasons.append("USAGE_LIMIT_REACHED_100_PERCENT")
    elif maximum >= 80:
        decision = "REVIEW"
        post_action = "PAUSE_AFTER_EXECUTION"
        reasons.append("USAGE_RESERVE_BELOW_20_PERCENT")
    elif maximum >= 60:
        decision = "REVIEW"
        post_action = "REVIEW_AFTER_EXECUTION"
        reasons.append("USAGE_REVIEW_60_PERCENT")
    else:
        decision = "READY"
        post_action = "CONTINUE"
    ledger_digest = canonical_digest(ledger.as_dict())
    event_digest = canonical_digest(event.as_dict())
    digest_input = {
        "schema_version": 1,
        "work_id": work_id,
        "event_id": event.event_id,
        "stage": stage,
        "measurement_basis": projected_total.token_measurement_status,
        "total_budget": work.budget.as_dict(),
        "stage_budget": stage_limit.as_dict(),
        "projected_total": projected_total.as_dict(),
        "projected_stage": projected_stage.as_dict(),
        "total_utilization": total_utilization,
        "stage_utilization": stage_utilization,
        "governance_usage": governance_usage,
        "reason_codes": sorted(set(reasons)),
        "decision": decision,
        "post_action": post_action,
        "ledger_digest": ledger_digest,
        "event_digest": event_digest,
    }
    return UsageAdmissionPlanV1(
        decision=decision,
        post_action=post_action,
        work_id=work_id,
        event_id=event.event_id,
        stage=stage,
        measurement_basis=projected_total.token_measurement_status,
        total_budget=work.budget.as_dict(),
        stage_budget=stage_limit.as_dict(),
        projected_total=projected_total.as_dict(),
        projected_stage=projected_stage.as_dict(),
        total_utilization=total_utilization,
        stage_utilization=stage_utilization,
        governance_usage=governance_usage,
        reason_codes=tuple(sorted(set(reasons))),
        ledger_digest=ledger_digest,
        event_digest=event_digest,
        plan_digest=canonical_digest(digest_input),
    )


@dataclass(frozen=True, slots=True)
class OperationAdmissionPermitV1:
    decision: str
    post_action: str
    work_id: str
    event_id: str
    operation: str
    requested_targets: tuple[str, ...]
    scope_digest: str
    usage_plan_digest: str
    blockers: tuple[str, ...]
    permit_digest: str

    @property
    def allowed(self) -> bool:
        return self.decision in {"READY", "REVIEW"} and not self.blockers

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "OperationAdmissionPermitV1",
            "decision": self.decision,
            "post_action": self.post_action,
            "work_id": self.work_id,
            "event_id": self.event_id,
            "operation": self.operation,
            "requested_targets": list(self.requested_targets),
            "scope_digest": self.scope_digest,
            "usage_plan_digest": self.usage_plan_digest,
            "blockers": list(self.blockers),
            "permit_digest": self.permit_digest,
            "mutation_count": 0,
        }


@dataclass(frozen=True, slots=True)
class OperationExecutionReceiptV1:
    decision: str
    post_action: str
    work_id: str
    event_id: str
    operation: str
    permit_digest: str
    usage_reserved: bool
    reservation: Any = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "OperationExecutionReceiptV1",
            "decision": self.decision,
            "post_action": self.post_action,
            "work_id": self.work_id,
            "event_id": self.event_id,
            "operation": self.operation,
            "permit_digest": self.permit_digest,
            "usage_reserved": self.usage_reserved,
        }


def _positive_event_dimension(event: Any, field: str) -> int:
    value = getattr(event, field, None)
    return value if type(value) is int and value > 0 else 0


def plan_operation_admission(
    process_root: Path,
    work_id: str,
    event: Any,
    *,
    operation: str,
    requested_targets: tuple[str, ...] = (),
) -> OperationAdmissionPermitV1:
    """把 deny-default scope 与预算合成一次 exact operation permit。"""

    work = load_work(process_root, work_id)
    usage_plan = plan_usage_admission(process_root, work_id, event)
    targets = tuple(dict.fromkeys(str(target) for target in requested_targets))
    blockers: list[str] = []
    dimension = SCOPED_OPERATION_DIMENSIONS.get(operation)
    governance_dimension = GOVERNANCE_OPERATION_DIMENSIONS.get(operation)
    system_operation = operation in SYSTEM_OPERATION_KINDS
    if dimension is None and governance_dimension is None and not system_operation:
        blockers.append("OPERATION_KIND_UNSUPPORTED")
    if system_operation:
        if targets:
            blockers.append("SYSTEM_OPERATION_TARGETS_FORBIDDEN")
    elif dimension is not None:
        if not targets:
            blockers.append("OPERATION_TARGET_REQUIRED")
        if _positive_event_dimension(event, dimension) < len(targets):
            blockers.append("OPERATION_USAGE_DELTA_TOO_SMALL")
        for target in targets:
            try:
                scope = check_scope(work.scope, operation, target)
            except ValueError:
                blockers.append(f"OPERATION_TARGET_INVALID:{target}")
                continue
            if not scope.allowed:
                blockers.append(f"OPERATION_SCOPE_DENIED:{operation}:{target}")
    else:
        if targets:
            blockers.append("GOVERNANCE_OPERATION_TARGETS_FORBIDDEN")
        if governance_dimension and _positive_event_dimension(event, governance_dimension) != 1:
            blockers.append("GOVERNANCE_OPERATION_DELTA_MUST_BE_ONE")
    decision = "BLOCKED" if blockers else usage_plan.decision
    post_action = "BLOCK_EXECUTION" if blockers else usage_plan.post_action
    source = {
        "schema_version": 1,
        "work_id": work_id,
        "event_id": event.event_id,
        "operation": operation,
        "requested_targets": list(targets),
        "scope_digest": work.scope.digest,
        "usage_plan_digest": usage_plan.plan_digest,
        "decision": decision,
        "post_action": post_action,
        "blockers": sorted(set(blockers)),
    }
    return OperationAdmissionPermitV1(
        decision=decision,
        post_action=post_action,
        work_id=work_id,
        event_id=event.event_id,
        operation=operation,
        requested_targets=targets,
        scope_digest=work.scope.digest,
        usage_plan_digest=usage_plan.plan_digest,
        blockers=tuple(sorted(set(blockers))),
        permit_digest=canonical_digest(source),
    )


def execute_admitted_operation(
    process_root: Path,
    permit: OperationAdmissionPermitV1,
    event: Any,
    executor: Callable[[], Any],
) -> tuple[OperationExecutionReceiptV1, Any]:
    """先预占 exact usage，再调用受控执行器；拒绝或漂移时调用数为 0。"""

    fresh = plan_operation_admission(
        process_root,
        permit.work_id,
        event,
        operation=permit.operation,
        requested_targets=permit.requested_targets,
    )
    if fresh.permit_digest != permit.permit_digest:
        raise ValueError("operation admission permit drifted before execution")
    if not fresh.allowed:
        raise ValueError(
            "operation admission blocks execution: "
            f"{fresh.decision}:{','.join(fresh.blockers)}"
        )
    from meta_flow.work.usage import append_usage_event

    reservation = append_usage_event(
        process_root,
        permit.work_id,
        event,
        expected_admission_digest=permit.usage_plan_digest,
    )
    if not reservation.appended:
        return (
            OperationExecutionReceiptV1(
                decision="NO_CHANGE",
                post_action=fresh.post_action,
                work_id=permit.work_id,
                event_id=permit.event_id,
                operation=permit.operation,
                permit_digest=permit.permit_digest,
                usage_reserved=False,
                reservation=reservation,
            ),
            None,
        )
    result = executor()
    return (
        OperationExecutionReceiptV1(
            decision="PASS",
            post_action=fresh.post_action,
            work_id=permit.work_id,
            event_id=permit.event_id,
            operation=permit.operation,
            permit_digest=permit.permit_digest,
            usage_reserved=True,
            reservation=reservation,
        ),
        result,
    )


__all__ = [
    "GOVERNANCE_LIMITS",
    "OperationAdmissionPermitV1",
    "OperationExecutionReceiptV1",
    "SYSTEM_OPERATION_KINDS",
    "STAGE_SHARES",
    "UsageAdmissionPlanV1",
    "execute_admitted_operation",
    "normalize_stage",
    "plan_operation_admission",
    "plan_usage_admission",
]
