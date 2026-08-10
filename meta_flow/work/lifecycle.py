"""Work 状态转移与 expected-status 原子更新。"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from meta_flow.execution_control.admission import acquire_admission_lock, release_admission_lock
from meta_flow.execution_control.contract import canonical_digest
from meta_flow.execution_control.failure import (
    FailureAttemptV1,
    FailureObservationApplyResultV1,
    FindingObservationPlanV1,
    blocked_observation_plan,
    coordination_plan_for_observation,
    load_frozen_failure_contract,
    load_frozen_failure_evidence,
    plan_finding_observation,
)
from meta_flow.project.process_route import _resolve_runtime_path, _resolve_runtime_ref
from meta_flow.project.scale import dump_yaml
from meta_flow.state.event_ledger import (
    append_execution_control_event,
    execution_control_ledger_preimage,
    load_events,
    project_execution_control_ledger,
)
from meta_flow.work.model import Work, load_work, with_status, work_path

ALLOWED_TRANSITIONS = {
    "planned": {"active", "cancelled"},
    "active": {"paused", "blocked", "ready_for_review", "ready_for_verification", "completed", "cancelled"},
    "paused": {"active", "blocked", "cancelled"},
    "blocked": {"active", "cancelled"},
    "ready_for_review": {"active", "ready_for_verification", "cancelled"},
    "ready_for_verification": {"active", "completed", "cancelled"},
    "completed": {"archived"},
    "cancelled": {"archived"},
    "archived": set(),
}


def transition_work(work: Work, new_status: str, *, result_ref: str = "") -> Work:
    allowed = ALLOWED_TRANSITIONS.get(work.status, set())
    if new_status not in allowed:
        raise ValueError(f"invalid Work transition: {work.status} -> {new_status}")
    if new_status == "completed" and not (result_ref or work.result_ref):
        raise ValueError("completed Work requires result_ref")
    return with_status(work, new_status, result_ref=result_ref)


def update_work_status(
    process_root: Path,
    work_id: str,
    *,
    expected_status: str,
    new_status: str,
    result_ref: str = "",
) -> Work:
    current = load_work(process_root, work_id)
    if current.status != expected_status:
        raise ValueError(
            f"Work status changed: expected {expected_status}, current {current.status}"
        )
    updated = transition_work(current, new_status, result_ref=result_ref)
    path = work_path(process_root, work_id)
    temporary = path.with_name(f".{path.name}.tmp")
    if temporary.exists() or temporary.is_symlink():
        raise FileExistsError(f"temporary Work path already exists: {temporary}")
    try:
        temporary.write_text(dump_yaml(updated.as_dict()) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()
    return load_work(process_root, work_id)


def _execution_control_ledger_path(project_root: Path) -> Path:
    return _resolve_runtime_ref(
        project_root.resolve(), "process/state/EXECUTION-CONTROL-LEDGER.ndjson"
    )


def _bound_process_root(project_root: Path) -> Path:
    return _resolve_runtime_ref(
        project_root.resolve(), "process/.meta-flow-process.yaml"
    ).parent


def plan_execution_failure(
    project_root: Path,
    *,
    work_id: str,
    evidence_ref: str,
    facts: Mapping[str, Any],
    failed_layer: str,
    attempt: FailureAttemptV1,
) -> FindingObservationPlanV1:
    """公共 plan 只接受 evidence ref；identity 与 occurrence 均在内部派生。"""

    preimage_digest = hashlib.sha256(b"").hexdigest()
    try:
        ledger = _execution_control_ledger_path(project_root)
        preimage_digest = execution_control_ledger_preimage(ledger)
        process_root = _bound_process_root(project_root)
        work = load_work(process_root, work_id)
        if work.execution_unit is None:
            return blocked_observation_plan(
                "EXECUTION_UNIT_REQUIRED",
                evidence_ref=evidence_ref,
                expected_ledger_preimage_digest=preimage_digest,
            )
        contract_path = _resolve_runtime_path(
            project_root.resolve(), work.execution_unit.contract_ref
        )
        contract, contract_raw_digest = load_frozen_failure_contract(contract_path)
        if contract_raw_digest != work.execution_unit.contract_digest:
            return blocked_observation_plan(
                "EXECUTION_CONTRACT_DIGEST_MISMATCH",
                evidence_ref=evidence_ref,
                expected_ledger_preimage_digest=preimage_digest,
            )
        evidence_path = _resolve_runtime_path(project_root.resolve(), evidence_ref)
        evidence = load_frozen_failure_evidence(evidence_path)
        if evidence.target_scope_digest != work.scope.digest:
            return blocked_observation_plan(
                "FROZEN_TARGET_SCOPE_DIGEST_MISMATCH",
                evidence_ref=evidence_ref,
                expected_ledger_preimage_digest=preimage_digest,
            )
        if ledger.is_file():
            events, errors = load_events(ledger)
            if errors:
                return blocked_observation_plan(
                    "EXECUTION_CONTROL_LEDGER_INVALID",
                    evidence_ref=evidence_ref,
                    expected_ledger_preimage_digest=preimage_digest,
                )
        else:
            events = []
        return plan_finding_observation(
            work.execution_unit,
            contract,
            evidence,
            evidence_ref=evidence_ref,
            facts=facts,
            failed_layer=failed_layer,
            attempt=attempt,
            ledger_projection=project_execution_control_ledger(tuple(events)),
            ledger_preimage_digest=preimage_digest,
        )
    except (FileNotFoundError, OSError, TypeError, ValueError):
        return blocked_observation_plan(
            "FROZEN_FAILURE_EVIDENCE_OR_ROUTE_INVALID",
            evidence_ref=evidence_ref,
            expected_ledger_preimage_digest=preimage_digest,
        )


def _apply_result_after_release(
    *,
    planned: FindingObservationPlanV1,
    operation_decision: str,
    operation_conflicts: tuple[str, ...],
    occurrence: int,
    domain_mutation_count: int,
    idempotent: bool,
    acquire_coordination_count: int,
    release_result: Any,
) -> FailureObservationApplyResultV1:
    conflicts = tuple(sorted({*operation_conflicts, *release_result.conflicts}))
    coordination = acquire_coordination_count + release_result.coordination_mutation_count
    if operation_decision == "PARTIAL_MUTATION" or release_result.partial:
        decision = "PARTIAL_MUTATION"
    elif operation_decision != "PASS" or release_result.decision != "PASS":
        decision = "BLOCKED"
    else:
        decision = "PASS"
    return FailureObservationApplyResultV1(
        decision=decision,
        conflicts=conflicts,
        route=planned.route,
        occurrence=occurrence,
        domain_mutation_count=domain_mutation_count,
        coordination_mutation_count=coordination,
        durable_lock_count=release_result.durable_lock_count,
        idempotent=idempotent,
    )


def apply_execution_failure(
    project_root: Path,
    process_git_common_dir: Path,
    planned: FindingObservationPlanV1,
    *,
    work_id: str,
    evidence_ref: str,
    facts: Mapping[str, Any],
    failed_layer: str,
    attempt: FailureAttemptV1,
    owner_token: str,
    owner_process_identity: str,
) -> FailureObservationApplyResultV1:
    """持 S2 project lock 重建 fresh plan 后 append；不创建 successor Work。"""

    if planned.blocked or planned.route is None:
        return FailureObservationApplyResultV1(
            "BLOCKED", planned.conflicts, planned.route, 0, 0, 0, 0, False
        )
    lock_plan = coordination_plan_for_observation(planned)
    acquired = acquire_admission_lock(
        process_git_common_dir,
        lock_plan,
        owner_token=owner_token,
        owner_process_identity=owner_process_identity,
    )
    if acquired.decision != "PASS" or acquired.handle is None:
        return FailureObservationApplyResultV1(
            acquired.decision,
            acquired.conflicts,
            planned.route,
            0,
            0,
            acquired.coordination_mutation_count,
            acquired.durable_lock_count,
            False,
        )
    fresh = plan_execution_failure(
        project_root,
        work_id=work_id,
        evidence_ref=evidence_ref,
        facts=facts,
        failed_layer=failed_layer,
        attempt=attempt,
    )
    if fresh.blocked or canonical_digest(fresh) != canonical_digest(planned):
        released = release_admission_lock(process_git_common_dir, acquired.handle)
        return _apply_result_after_release(
            planned=planned,
            operation_decision="BLOCKED",
            operation_conflicts=("EXECUTION_CONTROL_FRESH_PLAN_DRIFT",),
            occurrence=0,
            domain_mutation_count=0,
            idempotent=False,
            acquire_coordination_count=acquired.coordination_mutation_count,
            release_result=released,
        )
    if not fresh.append_required:
        released = release_admission_lock(process_git_common_dir, acquired.handle)
        return _apply_result_after_release(
            planned=planned,
            operation_decision="PASS",
            operation_conflicts=(),
            occurrence=fresh.route.occurrence if fresh.route is not None else 0,
            domain_mutation_count=0,
            idempotent=True,
            acquire_coordination_count=acquired.coordination_mutation_count,
            release_result=released,
        )
    if fresh.event is None:
        released = release_admission_lock(process_git_common_dir, acquired.handle)
        return _apply_result_after_release(
            planned=planned,
            operation_decision="BLOCKED",
            operation_conflicts=("EXECUTION_CONTROL_EVENT_MISSING",),
            occurrence=0,
            domain_mutation_count=0,
            idempotent=False,
            acquire_coordination_count=acquired.coordination_mutation_count,
            release_result=released,
        )
    appended = append_execution_control_event(
        _execution_control_ledger_path(project_root),
        fresh.event,
        expected_preimage_digest=fresh.expected_ledger_preimage_digest,
    )
    released = release_admission_lock(process_git_common_dir, acquired.handle)
    return _apply_result_after_release(
        planned=planned,
        operation_decision=appended.decision,
        operation_conflicts=appended.conflicts,
        occurrence=appended.occurrence,
        domain_mutation_count=appended.domain_mutation_count,
        idempotent=appended.idempotent,
        acquire_coordination_count=acquired.coordination_mutation_count,
        release_result=released,
    )
