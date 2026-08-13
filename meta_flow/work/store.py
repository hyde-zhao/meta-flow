"""Work create-only 计划、索引和恢复友好 apply。"""

from __future__ import annotations

import json
import secrets
import subprocess
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Any

from meta_flow.execution_control.admission import (
    acquire_admission_lock,
    plan_admission,
    release_admission_lock,
    validate_admission_preimage,
)
from meta_flow.execution_control.contract import (
    AdmissionPlanV1,
    canonical_digest,
)
from meta_flow.execution_control.migration import current_execution_control_policy
from meta_flow.execution_control.runtime_context import (
    ExecutionControlContextV1,
    RequestMaterializationCandidateV1,
    build_execution_control_context,
    target_preimage_digest,
)
from meta_flow.project.governance import load_phase
from meta_flow.project.model import Project, load_project
from meta_flow.project.read_contract import ReadContextProtocol
from meta_flow.project.scale import dump_yaml, load_yaml_object
from meta_flow.work.model import Work, load_work, work_path
from meta_flow.work.read_context import OperationReadContext
from meta_flow.work.route_profile import RouteDecision, evaluate_route_profile
from meta_flow.work.scope import check_scope


@dataclass(frozen=True)
class WorkInitAction:
    action: str
    ref: str
    reason: str
    before_digest: str = ""


@dataclass(frozen=True)
class WorkInitConflict:
    code: str
    ref: str
    message: str


@dataclass(frozen=True)
class WorkInitPlan:
    process_root: Path | None
    release_root: Path | None
    work: Work
    project: Project | None
    actions: tuple[WorkInitAction, ...]
    conflicts: tuple[WorkInitConflict, ...]
    route_decision: RouteDecision
    human_design_gate_ref: str
    compatibility_decision: str
    execution_context: ExecutionControlContextV1 | None
    admission_plan: AdmissionPlanV1 | None
    request_candidate: RequestMaterializationCandidateV1 | None
    target_preimages: tuple[tuple[str, str], ...]
    plan_digest: str
    lineage_preflight: tuple[tuple[str, str, str, str], ...] = ()

    @property
    def blocked(self) -> bool:
        return bool(self.conflicts)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "decision": "BLOCKED" if self.blocked else "READY",
            "compatibility_decision": self.compatibility_decision,
            "work_id": self.work.work_id,
            "work_ref": self.work.work_ref,
            "risk_profile": self.work.risk_profile,
            "scope_digest": self.work.scope.digest,
            "budget": self.work.budget.as_dict(),
            "route": self.route_decision.as_dict(),
            "human_design_gate_ref": self.human_design_gate_ref,
            "actions": [action.__dict__ for action in self.actions],
            "conflicts": [conflict.__dict__ for conflict in self.conflicts],
            "target_preimages": dict(self.target_preimages),
            "lineage_preflight": [
                {
                    "ref": ref,
                    "anchor_close_authorization_id": anchor,
                    "predecessor_successor_id": predecessor,
                    "before_digest": before_digest,
                }
                for ref, anchor, predecessor, before_digest in self.lineage_preflight
            ],
            "context_digest": (
                self.execution_context.context_digest
                if self.execution_context is not None
                else ""
            ),
            "provider_receipt_status": (
                self.execution_context.provider_receipt_status
                if self.execution_context is not None
                else ""
            ),
            "admission": (
                self.admission_plan.as_dict()
                if self.admission_plan is not None
                else None
            ),
            "request_candidate_digest": (
                self.request_candidate.candidate_digest
                if self.request_candidate is not None
                else ""
            ),
            "plan_digest": self.plan_digest,
            "domain_mutation_count": 0,
            "coordination_mutation_count": 0,
            "mutation_count": 0,
        }


@dataclass(frozen=True)
class WorkInitReceipt:
    decision: str
    work_id: str
    work_ref: str
    plan_digest: str
    mutation_count: int
    domain_mutation_count: int
    coordination_mutation_count: int
    durable_refs: tuple[str, ...]
    durable_lock_count: int
    project_index_updated: bool
    context_digest: str
    provider_receipt_status: str
    reason_codes: tuple[str, ...]
    recovery_route: str
    transaction_id: str = ""
    transaction_state: str = ""
    recovery_required: bool = False
    shared_projection_successor_id: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "work_id": self.work_id,
            "work_ref": self.work_ref,
            "plan_digest": self.plan_digest,
            "mutation_count": self.mutation_count,
            "domain_mutation_count": self.domain_mutation_count,
            "coordination_mutation_count": self.coordination_mutation_count,
            "durable_refs": list(self.durable_refs),
            "durable_lock_count": self.durable_lock_count,
            "project_index_updated": self.project_index_updated,
            "context_digest": self.context_digest,
            "provider_receipt_status": self.provider_receipt_status,
            "reason_codes": list(self.reason_codes),
            "recovery_route": self.recovery_route,
            "transaction_id": self.transaction_id,
            "transaction_state": self.transaction_state,
            "recovery_required": self.recovery_required,
            "shared_projection_successor_id": self.shared_projection_successor_id,
        }


class WorkInitApplyError(RuntimeError):
    def __init__(self, message: str, receipt: WorkInitReceipt) -> None:
        super().__init__(message)
        self.receipt = receipt


def _same_work(existing: Work, requested: Work) -> bool:
    return existing == requested


def _digest(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def _plan_digest_source(
    *,
    work: Work,
    project: Project | None,
    phase: object | None,
    route_decision: RouteDecision,
    human_design_gate_ref: str,
    compatibility_decision: str,
    actions: list[WorkInitAction],
    conflicts: list[WorkInitConflict],
    target_preimages: tuple[tuple[str, str], ...],
    process_root_identity: str,
    context_digest: str,
    admission_plan: AdmissionPlanV1 | None,
    request_candidate: RequestMaterializationCandidateV1 | None,
    lineage_preflight: tuple[tuple[str, str, str, str], ...] = (),
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "process_root_identity": process_root_identity,
        "project": project.as_dict() if project is not None else None,
        "phase": phase.as_dict() if phase is not None else None,
        "work": work.as_dict(),
        "route": route_decision.as_dict(),
        "human_design_gate_ref": human_design_gate_ref,
        "compatibility_decision": compatibility_decision,
        "actions": [action.__dict__ for action in actions],
        "conflicts": [conflict.__dict__ for conflict in conflicts],
        "target_preimages": dict(target_preimages),
        "context_digest": context_digest,
        "admission": admission_plan.as_dict() if admission_plan is not None else None,
        "request_candidate_digest": (
            request_candidate.candidate_digest if request_candidate is not None else ""
        ),
        "lineage_preflight": [list(item) for item in lineage_preflight],
    }


def _route_conflicts(
    work: Work,
    *,
    human_design_gate_ref: str,
) -> tuple[RouteDecision, list[WorkInitConflict]]:
    route_decision = evaluate_route_profile(
        work.route_profile,
        risk_profile=work.risk_profile,
        work_kind=work.kind,
        human_design_gate_ref=human_design_gate_ref,
    )
    return route_decision, [
        WorkInitConflict("route_profile_blocked", work.work_ref, error)
        for error in route_decision.errors
    ]


def plan_work_init(
    process_root: Path,
    work: Work,
    *,
    human_design_gate_ref: str = "",
    read_context: ReadContextProtocol | None = None,
) -> WorkInitPlan:
    """Legacy process-root facade：只允许 exact-existing 的零写读取。

    本入口故意不能构造可交给 writer 的新建或修复计划。所有 create/repair
    consumer 必须迁移到 :func:`plan_work_init_from_release_root`。
    """

    root = process_root.resolve()
    owned_context = read_context is None
    allowed_reads = ["PROJECT.yaml", work.work_ref]
    if work.phase_ref:
        allowed_reads.append(work.phase_ref)
    if work.route_profile.legacy_cp_compatibility and human_design_gate_ref:
        allowed_reads.append(human_design_gate_ref)
    context = read_context or OperationReadContext(
        root,
        operation_id=f"work.init.plan:{work.work_id}",
        operation_kind="plan",
        allowed_reads=tuple(dict.fromkeys(allowed_reads)),
        max_objects=max(5, len(allowed_reads)),
        scope_digest=work.scope.digest,
    )
    context.assert_operation("plan")
    actions: list[WorkInitAction] = []
    route_decision, conflicts = _route_conflicts(
        work, human_design_gate_ref=human_design_gate_ref
    )
    if work.route_profile.legacy_cp_compatibility and not route_decision.errors:
        gate_path = root / human_design_gate_ref
        if not gate_path.is_file():
            conflicts.append(
                WorkInitConflict(
                    "human_design_gate_missing",
                    human_design_gate_ref,
                    "legacy CP human design gate evidence is missing",
                )
            )
        if not check_scope(work.scope, "read", human_design_gate_ref).allowed:
            conflicts.append(
                WorkInitConflict(
                    "human_design_gate_out_of_scope",
                    human_design_gate_ref,
                    "legacy CP human design gate must be declared in Work reads",
                )
            )
    project: Project | None = None
    try:
        project = load_project(root, read_context=context)
    except (OSError, ValueError) as exc:
        conflicts.append(WorkInitConflict("project_invalid", "PROJECT.yaml", str(exc)))
    else:
        if project.project_id != work.project_id:
            conflicts.append(
                WorkInitConflict(
                    "project_id_mismatch",
                    "PROJECT.yaml",
                    f"Work project_id={work.project_id} differs from Project={project.project_id}",
                )
            )

    phase = None
    if work.phase_ref:
        try:
            phase = load_phase(root, work.phase_ref, read_context=context)
        except (OSError, ValueError) as exc:
            conflicts.append(WorkInitConflict("phase_invalid", work.phase_ref, str(exc)))
        else:
            if phase.project_id != work.project_id:
                conflicts.append(WorkInitConflict("phase_project_mismatch", work.phase_ref, "Phase belongs to another project"))
            elif work.work_ref in phase.work_refs:
                actions.append(
                    WorkInitAction(
                        "noop",
                        work.phase_ref,
                        "Phase already indexes Work",
                        target_preimage_digest(root / work.phase_ref),
                    )
                )

    path = work_path(root, work.work_id)
    existing_matches = False
    if path.exists() or path.is_symlink():
        try:
            existing = load_work(root, work.work_id, read_context=context)
        except (OSError, ValueError) as exc:
            conflicts.append(WorkInitConflict("work_invalid", work.work_ref, str(exc)))
        else:
            if not _same_work(existing, work):
                conflicts.append(
                    WorkInitConflict(
                        "BLOCKED_EXECUTION_CONTEXT_REQUIRED"
                        if work.execution_unit is not None
                        else "BLOCKED_LEGACY_HISTORY_WRITE_FORBIDDEN",
                        work.work_ref,
                        "legacy facade cannot repair or replace WORK.yaml",
                    )
                )
            else:
                existing_matches = True
                actions.append(
                    WorkInitAction(
                        "noop",
                        work.work_ref,
                        "matching WORK.yaml already exists",
                        target_preimage_digest(path),
                    )
                )
    else:
        conflicts.append(
            WorkInitConflict(
                "BLOCKED_EXECUTION_CONTEXT_REQUIRED"
                if work.execution_unit is not None
                else "BLOCKED_NEW_OBJECT_REQUIRES_EXECUTION_UNIT",
                work.work_ref,
                "legacy process-root facade cannot create a Work",
            )
        )

    repair_required = False
    if project is not None:
        if work.work_ref in project.active_work_refs:
            if not path.is_file():
                conflicts.append(WorkInitConflict("broken_project_index", work.work_ref, "Project indexes a missing Work"))
            else:
                actions.append(
                    WorkInitAction(
                        "noop",
                        "PROJECT.yaml",
                        "Project already indexes Work",
                        target_preimage_digest(root / "PROJECT.yaml"),
                    )
                )
        else:
            repair_required = existing_matches
    if work.phase_ref and phase is not None and work.work_ref not in phase.work_refs:
        repair_required = existing_matches
    if repair_required:
        conflicts.append(
            WorkInitConflict(
                "BLOCKED_EXECUTION_CONTEXT_REQUIRED"
                if work.execution_unit is not None
                else "BLOCKED_LEGACY_HISTORY_WRITE_FORBIDDEN",
                work.work_ref,
                "legacy process-root facade cannot repair Project or Phase indexes",
            )
        )

    if existing_matches and not repair_required and not conflicts:
        compatibility_decision = (
            "NOOP_TYPED_EXISTING_READ_ONLY"
            if work.execution_unit is not None
            else "NOOP_GRANDFATHERED_READ_ONLY"
        )
    else:
        compatibility_decision = (
            conflicts[-1].code if conflicts else "BLOCKED_EXECUTION_CONTEXT_REQUIRED"
        )
    target_preimages = tuple(
        sorted(
            {
                "PROJECT.yaml": target_preimage_digest(root / "PROJECT.yaml"),
                work.work_ref: target_preimage_digest(path),
                **(
                    {work.phase_ref: target_preimage_digest(root / work.phase_ref)}
                    if work.phase_ref
                    else {}
                ),
            }.items()
        )
    )
    digest_source = _plan_digest_source(
        work=work,
        project=project,
        phase=phase,
        route_decision=route_decision,
        human_design_gate_ref=human_design_gate_ref,
        compatibility_decision=compatibility_decision,
        actions=actions,
        conflicts=conflicts,
        target_preimages=target_preimages,
        process_root_identity=_digest({"canonical_root": str(root)}),
        context_digest="",
        admission_plan=None,
        request_candidate=None,
    )
    plan = WorkInitPlan(
        process_root=root,
        release_root=None,
        work=work,
        project=project,
        actions=tuple(actions),
        conflicts=tuple(conflicts),
        route_decision=route_decision,
        human_design_gate_ref=human_design_gate_ref,
        compatibility_decision=compatibility_decision,
        execution_context=None,
        admission_plan=None,
        request_candidate=None,
        target_preimages=target_preimages,
        plan_digest=_digest(digest_source),
    )
    if owned_context:
        context.close()
    return plan


def _evolution_package_digest(source_path: Path) -> str:
    """复用 evolution canonical parser；local import 避免模块初始化环。"""

    from meta_flow.evolution import evolution_from_payload

    return evolution_from_payload(load_yaml_object(source_path)).digest


def _plan_work_init_from_release_root(
    release_root: Path,
    work: Work,
    *,
    request_candidate: RequestMaterializationCandidateV1 | None = None,
    human_design_gate_ref: str = "",
    operation: str,
) -> WorkInitPlan:
    """Canonical 零写 planner；target authority 只能来自 release-root route。"""

    root = release_root.resolve()
    route_decision, conflicts = _route_conflicts(
        work, human_design_gate_ref=human_design_gate_ref
    )
    try:
        execution_context = build_execution_control_context(root, work, operation=operation)
    except (OSError, ValueError) as exc:
        conflicts.append(
            WorkInitConflict("EXECUTION_CONTEXT_UNAVAILABLE", work.work_ref, str(exc))
        )
        digest_source = _plan_digest_source(
            work=work,
            project=None,
            phase=None,
            route_decision=route_decision,
            human_design_gate_ref=human_design_gate_ref,
            compatibility_decision="BLOCKED_EXECUTION_CONTEXT_REQUIRED",
            actions=[],
            conflicts=conflicts,
            target_preimages=(),
            process_root_identity="",
            context_digest="",
            admission_plan=None,
            request_candidate=request_candidate,
        )
        return WorkInitPlan(
            None,
            root,
            work,
            None,
            (),
            tuple(conflicts),
            route_decision,
            human_design_gate_ref,
            "BLOCKED_EXECUTION_CONTEXT_REQUIRED",
            None,
            None,
            request_candidate,
            (),
            _digest(digest_source),
        )

    process_root = execution_context.process_root
    actions: list[WorkInitAction] = []
    project: Project | None = None
    phase = None
    try:
        project = load_project(process_root)
    except (OSError, ValueError) as exc:
        conflicts.append(WorkInitConflict("project_invalid", "PROJECT.yaml", str(exc)))
    else:
        if project.project_id != work.project_id:
            conflicts.append(
                WorkInitConflict(
                    "project_id_mismatch",
                    "PROJECT.yaml",
                    "Work and Project identities differ",
                )
            )
        if canonical_digest(project.active_work_refs) != execution_context.project_active_owner_digest:
            conflicts.append(
                WorkInitConflict(
                    "ADMISSION_PREIMAGE_DRIFT",
                    "PROJECT.yaml",
                    "Project active owner changed while building the plan",
                )
            )

    if work.route_profile.legacy_cp_compatibility and not route_decision.errors:
        gate_path = process_root / human_design_gate_ref
        if not gate_path.is_file():
            conflicts.append(
                WorkInitConflict(
                    "human_design_gate_missing",
                    human_design_gate_ref,
                    "legacy CP human design gate evidence is missing",
                )
            )
        if not check_scope(work.scope, "read", human_design_gate_ref).allowed:
            conflicts.append(
                WorkInitConflict(
                    "human_design_gate_out_of_scope",
                    human_design_gate_ref,
                    "legacy CP human design gate must be declared in Work reads",
                )
            )

    if len(work.scope.allowed_reads) > work.budget.reads:
        conflicts.append(
            WorkInitConflict(
                "read_scope_over_budget",
                work.work_ref,
                "allowed_reads count exceeds budget",
            )
        )
    if len(work.scope.allowed_writes) > work.budget.writes:
        conflicts.append(
            WorkInitConflict(
                "write_scope_over_budget",
                work.work_ref,
                "allowed_writes count exceeds budget",
            )
        )
    if len(work.scope.required_checks) > work.budget.check_groups:
        conflicts.append(
            WorkInitConflict(
                "check_scope_over_budget",
                work.work_ref,
                "required_checks count exceeds budget",
            )
        )

    request_path = process_root / work.request_ref
    request_before = target_preimage_digest(request_path)
    if request_candidate is None:
        if not request_path.is_file():
            conflicts.append(
                WorkInitConflict(
                    "request_missing",
                    work.request_ref,
                    "confirmed REQUEST.md is missing",
                )
            )
        if work.request_ref not in work.scope.allowed_reads:
            conflicts.append(
                WorkInitConflict(
                    "request_out_of_scope",
                    work.request_ref,
                    "request_ref must be an exact allowed_read",
                )
            )
        else:
            actions.append(
                WorkInitAction("noop", work.request_ref, "REQUEST already exists", request_before)
            )
    else:
        if request_candidate.request_ref != work.request_ref:
            conflicts.append(
                WorkInitConflict(
                    "request_candidate_ref_mismatch",
                    work.request_ref,
                    "request candidate must target Work.request_ref",
                )
            )
        if request_candidate.before_preimage_digest != request_before:
            conflicts.append(
                WorkInitConflict(
                    "request_candidate_preimage_drift",
                    work.request_ref,
                    "request candidate target preimage differs",
                )
            )
        if request_path.exists() or request_path.is_symlink():
            conflicts.append(
                WorkInitConflict(
                    "request_candidate_target_exists",
                    work.request_ref,
                    "request candidate is create-only",
                )
            )
        source_path = process_root / request_candidate.source_ref
        try:
            source_bytes = source_path.read_bytes()
        except OSError:
            conflicts.append(
                WorkInitConflict(
                    "request_candidate_source_missing",
                    request_candidate.source_ref,
                    "request candidate source is unavailable",
                )
            )
        else:
            try:
                source_digest = (
                    _evolution_package_digest(source_path)
                    if request_candidate.source_kind == "evolution-package-v1"
                    else sha256(source_bytes).hexdigest()
                )
            except (OSError, ValueError):
                conflicts.append(
                    WorkInitConflict(
                        "request_candidate_source_drift",
                        request_candidate.source_ref,
                        "request candidate source is malformed",
                    )
                )
            else:
                if source_digest != request_candidate.source_digest:
                    conflicts.append(
                        WorkInitConflict(
                            "request_candidate_source_drift",
                            request_candidate.source_ref,
                            "request candidate source digest differs",
                        )
                    )
        actions.append(
            WorkInitAction("create", work.request_ref, "materialize bound REQUEST", request_before)
        )

    if work.phase_ref:
        try:
            phase = load_phase(process_root, work.phase_ref)
        except (OSError, ValueError) as exc:
            conflicts.append(WorkInitConflict("phase_invalid", work.phase_ref, str(exc)))
        else:
            if phase.project_id != work.project_id:
                conflicts.append(
                    WorkInitConflict(
                        "phase_project_mismatch",
                        work.phase_ref,
                        "Phase belongs to another project",
                    )
                )

    governance_path = process_root / "governance/GOVERNANCE-BASELINE.json"
    if governance_path.exists() or governance_path.is_symlink():
        try:
            from meta_flow.project.governance_projection import (
                validate_governance_projection,
            )

            governance = validate_governance_projection(root, process_root)
            if governance["decision"] != "PASS":
                raise ValueError("; ".join(governance.get("errors", [])))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            conflicts.append(
                WorkInitConflict(
                    "WORK_INIT_GOVERNANCE_PREFLIGHT_BLOCKED",
                    "governance/GOVERNANCE-BASELINE.json",
                    f"governance projection must be current: {exc}",
                )
            )

    path = work_path(process_root, work.work_id)
    existing_matches = False
    if path.exists() or path.is_symlink():
        try:
            existing = load_work(process_root, work.work_id)
        except (OSError, ValueError) as exc:
            conflicts.append(WorkInitConflict("work_invalid", work.work_ref, str(exc)))
        else:
            if not _same_work(existing, work):
                conflicts.append(
                    WorkInitConflict("work_conflict", work.work_ref, "existing WORK.yaml differs")
                )
            else:
                existing_matches = True
                actions.append(
                    WorkInitAction("noop", work.work_ref, "matching WORK.yaml already exists", target_preimage_digest(path))
                )
    else:
        actions.append(
            WorkInitAction("create", work.work_ref, "create Work envelope", target_preimage_digest(path))
        )

    repair_required = False
    if project is not None:
        if work.work_ref in project.active_work_refs:
            actions.append(
                WorkInitAction("noop", "PROJECT.yaml", "Project already indexes Work", target_preimage_digest(process_root / "PROJECT.yaml"))
            )
        else:
            repair_required = existing_matches
            actions.append(
                WorkInitAction("update", "PROJECT.yaml", "append active Work ref", target_preimage_digest(process_root / "PROJECT.yaml"))
            )
    if work.phase_ref and phase is not None:
        if work.work_ref in phase.work_refs:
            actions.append(
                WorkInitAction("noop", work.phase_ref, "Phase already indexes Work", target_preimage_digest(process_root / work.phase_ref))
            )
        else:
            repair_required = existing_matches
            actions.append(
                WorkInitAction("update", work.phase_ref, "append Work ref to Phase", target_preimage_digest(process_root / work.phase_ref))
            )

    if work.execution_unit is None:
        if not existing_matches:
            compatibility_decision = "BLOCKED_NEW_OBJECT_REQUIRES_EXECUTION_UNIT"
            conflicts.append(
                WorkInitConflict(
                    compatibility_decision,
                    work.work_ref,
                    "new Work requires ExecutionUnitV1",
                )
            )
        elif repair_required:
            compatibility_decision = "BLOCKED_LEGACY_HISTORY_WRITE_FORBIDDEN"
            conflicts.append(
                WorkInitConflict(
                    compatibility_decision,
                    work.work_ref,
                    "untyped history cannot be repaired",
                )
            )
        else:
            compatibility_decision = "NOOP_GRANDFATHERED_READ_ONLY"
        admission_plan = None
    elif existing_matches and not repair_required:
        compatibility_decision = "NOOP_TYPED_CURRENT"
        admission_plan = None
    else:
        if execution_context.decision == "BLOCKED":
            for reason in execution_context.reason_codes:
                conflicts.append(WorkInitConflict(reason, work.work_ref, reason))
            admission_plan = None
        else:
            policy = current_execution_control_policy()
            admission_plan = plan_admission(
                work.execution_unit,
                execution_context.inventory.units,
                policy.budget,
                execution_context.admission_facts(),
            )
            if admission_plan.blocked:
                for reason in admission_plan.conflicts:
                    conflicts.append(WorkInitConflict(reason, work.work_ref, reason))
        compatibility_decision = (
            "TYPED_REPAIR_AFTER_ADMISSION" if repair_required else "ADMISSION_REQUIRED"
        )

    target_preimages = tuple(
        sorted(
            {
                work.request_ref: request_before,
                **(
                    {
                        str(Path(work.request_ref).parent): target_preimage_digest(
                            process_root / Path(work.request_ref).parent
                        )
                    }
                    if request_candidate is not None
                    else {}
                ),
                work.work_ref: target_preimage_digest(path),
                "PROJECT.yaml": target_preimage_digest(process_root / "PROJECT.yaml"),
                **(
                    {work.phase_ref: target_preimage_digest(process_root / work.phase_ref)}
                    if work.phase_ref
                    else {}
                ),
            }.items()
        )
    )
    lineage_preflight: tuple[tuple[str, str, str, str], ...] = ()
    successor_refs = tuple(
        action.ref
        for action in actions
        if action.action == "update"
        and (
            action.ref == "PROJECT.yaml"
            or Path(action.ref).name == "PHASE.yaml"
        )
    )
    if successor_refs and not conflicts:
        try:
            from meta_flow.work.lifecycle_transaction import (
                plan_shared_projection_successor_preflight,
            )

            successor_before = {
                ref: sha256((process_root / ref).read_bytes()).hexdigest()
                for ref in successor_refs
            }
            lineage_preflight = plan_shared_projection_successor_preflight(
                process_root,
                operation="work.init",
                writer_id=work.work_id,
                before_digests=successor_before,
                allowed_refs=successor_refs,
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            conflicts.append(
                WorkInitConflict(
                    "WORK_INIT_LINEAGE_PREFLIGHT_BLOCKED",
                    ",".join(successor_refs),
                    str(exc),
                )
            )
    digest_source = _plan_digest_source(
        work=work,
        project=project,
        phase=phase,
        route_decision=route_decision,
        human_design_gate_ref=human_design_gate_ref,
        compatibility_decision=compatibility_decision,
        actions=actions,
        conflicts=conflicts,
        target_preimages=target_preimages,
        process_root_identity=execution_context.process_root_identity,
        context_digest=execution_context.context_digest,
        admission_plan=admission_plan,
        request_candidate=request_candidate,
        lineage_preflight=lineage_preflight,
    )
    return WorkInitPlan(
        process_root=process_root,
        release_root=root,
        work=work,
        project=project,
        actions=tuple(actions),
        conflicts=tuple(conflicts),
        route_decision=route_decision,
        human_design_gate_ref=human_design_gate_ref,
        compatibility_decision=compatibility_decision,
        execution_context=execution_context,
        admission_plan=admission_plan,
        request_candidate=request_candidate,
        target_preimages=target_preimages,
        plan_digest=_digest(digest_source),
        lineage_preflight=lineage_preflight,
    )


def plan_work_init_from_release_root(
    release_root: Path,
    work: Work,
    *,
    request_candidate: RequestMaterializationCandidateV1 | None = None,
    human_design_gate_ref: str = "",
) -> WorkInitPlan:
    """公开 canonical planner；调用方不能选择 apply context。"""

    return _plan_work_init_from_release_root(
        release_root,
        work,
        request_candidate=request_candidate,
        human_design_gate_ref=human_design_gate_ref,
        operation="plan",
    )


def _process_git_common_dir(process_root: Path) -> Path:
    completed = subprocess.run(
        ["git", "-C", str(process_root), "rev-parse", "--git-common-dir"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        raise ValueError("process Git common directory is unavailable")
    candidate = Path(completed.stdout.strip())
    if not candidate.is_absolute():
        candidate = process_root / candidate
    return candidate.resolve(strict=False)


def _context_authority_digest(context: ExecutionControlContextV1) -> str:
    return canonical_digest(
        {
            "project_id": context.project_id,
            "release_root_identity": context.release_root_identity,
            "process_root_identity": context.process_root_identity,
            "route_digest": context.route_digest,
            "admission_facts": context.admission_facts().as_dict(),
            "provider_receipt_status": context.provider_receipt_status,
            "provider_receipt_digest": context.provider_receipt_digest,
            "policy_digest": context.policy_digest,
        }
    )


def _current_domain_preimages(plan: WorkInitPlan) -> tuple[tuple[str, str], ...]:
    if plan.process_root is None:
        return ()
    root = plan.process_root
    return tuple((ref, target_preimage_digest(root / ref)) for ref, _ in plan.target_preimages)


def _domain_refs_changed(
    plan: WorkInitPlan,
    baseline: tuple[tuple[str, str], ...],
) -> tuple[str, ...]:
    if plan.process_root is None:
        return ()
    root = plan.process_root
    changed = [
        ref
        for ref, before in baseline
        if target_preimage_digest(root / ref) != before
    ]
    return tuple(sorted(changed))


def _make_work_init_receipt(
    plan: WorkInitPlan,
    *,
    decision: str,
    domain_refs: tuple[str, ...] = (),
    coordination_mutation_count: int = 0,
    durable_lock_count: int = 0,
    project_index_updated: bool = False,
    reason_codes: tuple[str, ...] = (),
    transaction_id: str = "",
    transaction_state: str = "",
    recovery_required: bool = False,
    shared_projection_successor_id: str = "",
) -> WorkInitReceipt:
    context = plan.execution_context
    return WorkInitReceipt(
        decision=decision,
        work_id=plan.work.work_id,
        work_ref=plan.work.work_ref,
        plan_digest=plan.plan_digest,
        mutation_count=len(domain_refs) + coordination_mutation_count,
        domain_mutation_count=len(domain_refs),
        coordination_mutation_count=coordination_mutation_count,
        durable_refs=domain_refs,
        durable_lock_count=durable_lock_count,
        project_index_updated=project_index_updated,
        context_digest=context.context_digest if context is not None else "",
        provider_receipt_status=(
            context.provider_receipt_status if context is not None else ""
        ),
        reason_codes=tuple(sorted(set(reason_codes))),
        recovery_route=(
            "stop-and-inspect-partial-mutation"
            if decision == "PARTIAL_MUTATION"
            else "stop-and-replan"
            if decision == "RECOVERED"
            else "none"
        ),
        transaction_id=transaction_id,
        transaction_state=transaction_state,
        recovery_required=recovery_required,
        shared_projection_successor_id=shared_projection_successor_id,
    )


def _raise_apply_error(
    message: str,
    plan: WorkInitPlan,
    *,
    decision: str,
    coordination_mutation_count: int,
    durable_lock_count: int,
    reason_codes: tuple[str, ...],
    domain_baseline: tuple[tuple[str, str], ...],
    project_index_updated: bool = False,
) -> None:
    domain_refs = _domain_refs_changed(plan, domain_baseline)
    receipt = _make_work_init_receipt(
        plan,
        decision=decision,
        domain_refs=domain_refs,
        coordination_mutation_count=coordination_mutation_count,
        durable_lock_count=durable_lock_count,
        project_index_updated=project_index_updated,
        reason_codes=reason_codes,
    )
    raise WorkInitApplyError(message, receipt)


def _render_yaml_bytes(payload: dict[str, Any]) -> bytes:
    return (dump_yaml(payload) + "\n").encode("utf-8")


def _work_init_transaction_targets(
    plan: WorkInitPlan,
) -> tuple[Any, ...]:
    """基于 fresh plan 构造完整 post-image；此函数只读，不落盘。"""

    if plan.process_root is None or plan.release_root is None:
        raise ValueError("Work init transaction requires canonical roots")
    from meta_flow.work.init_transaction import build_transaction_target
    from meta_flow.work.lifecycle_transaction import build_state_projection_candidates

    root = plan.process_root
    action_by_ref = {action.ref: action for action in plan.actions}
    candidates: list[tuple[str, bytes | None]] = []
    overrides: dict[str, tuple[dict[str, Any], bytes]] = {}

    request_action = action_by_ref.get(plan.work.request_ref)
    if request_action is not None and request_action.action == "create":
        if plan.request_candidate is None:
            raise ValueError("REQUEST create action lacks a bound candidate")
        candidates.append((plan.work.request_ref, plan.request_candidate.content_bytes))

    work_bytes = _render_yaml_bytes(plan.work.as_dict())
    work_action = action_by_ref.get(plan.work.work_ref)
    if work_action is not None and work_action.action == "create":
        candidates.append((plan.work.work_ref, work_bytes))
    overrides["process/" + plan.work.work_ref] = (plan.work.as_dict(), work_bytes)

    if plan.project is None:
        raise ValueError("Work init transaction lacks Project")
    project = plan.project
    project_action = action_by_ref.get("PROJECT.yaml")
    if project_action is not None and project_action.action == "update":
        project = replace(
            project,
            active_work_refs=(*project.active_work_refs, plan.work.work_ref),
        )
        project_bytes = _render_yaml_bytes(project.as_dict())
        candidates.append(("PROJECT.yaml", project_bytes))
        overrides["process/PROJECT.yaml"] = (project.as_dict(), project_bytes)

    if plan.work.phase_ref:
        phase = load_phase(root, plan.work.phase_ref)
        phase_action = action_by_ref.get(plan.work.phase_ref)
        if phase_action is not None and phase_action.action == "update":
            phase = replace(
                phase,
                work_refs=(*phase.work_refs, plan.work.work_ref),
            )
            phase_bytes = _render_yaml_bytes(phase.as_dict())
            candidates.append((plan.work.phase_ref, phase_bytes))
            overrides["process/" + plan.work.phase_ref] = (
                phase.as_dict(),
                phase_bytes,
            )

    # 先证明 State post-image 可构造，但由 State 自身事务 owner 落盘；否则会
    # 绕过其 terminal-generation lineage。Work-init 外层 manifest 负责在后续
    # 失败时回滚领域目标，再调用同一 State owner 收敛回旧 formal truth。
    build_state_projection_candidates(root, object_overrides=overrides)

    targets_list: list[Any] = []
    for ref, after_bytes in candidates:
        path = root / ref
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError(f"Work init transaction target is not regular: {ref}")
        before_bytes = path.read_bytes() if path.is_file() else None
        if before_bytes != after_bytes:
            targets_list.append(
                build_transaction_target(root, ref=ref, after_bytes=after_bytes)
            )
    targets = tuple(targets_list)
    if not targets:
        raise ValueError("mutating Work init produced no transaction targets")
    if len(targets) > 7:
        raise ValueError("Work init transaction target budget exceeded")
    return targets


def _validate_work_init_postimage(plan: WorkInitPlan) -> None:
    """证明成功返回前 State/CURRENT、governance 与共享 lineage 已收敛。"""

    if plan.process_root is None or plan.release_root is None:
        raise ValueError("Work init postimage validation requires canonical roots")
    from meta_flow.project.governance_projection import validate_governance_projection
    from meta_flow.state import current as state_current
    from meta_flow.state.formal_projection import (
        build_formal_truth_snapshot,
        derive_formal_truth_patch,
    )
    from meta_flow.work.lifecycle_transaction import (
        assert_work_close_shared_projection_lineage,
    )

    root = plan.process_root
    assert_work_close_shared_projection_lineage(root)
    state_path = root / "state/STATE.current.json"
    if state_path.is_file() and not state_path.is_symlink():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        snapshot = build_formal_truth_snapshot(
            plan.release_root,
            process_root=root,
        )
        patch = derive_formal_truth_patch(state, snapshot)
        if state.get("formal_truth_projection") != snapshot or any(
            state.get(field) != patch[field]
            for field in ("current_phase", "active_change", "blocked", "next_action")
        ):
            raise ValueError("Work init State formal truth postimage is stale")
        current_findings = state_current.validate_current_projection(plan.release_root)
        if current_findings:
            raise ValueError(
                "Work init CURRENT postimage is stale: "
                + "; ".join(item.message for item in current_findings)
            )
    governance_path = root / "governance/GOVERNANCE-BASELINE.json"
    if governance_path.exists() or governance_path.is_symlink():
        governance = validate_governance_projection(plan.release_root, root)
        if governance["decision"] != "PASS":
            raise ValueError(
                "Work init governance projection postimage is stale: "
                + "; ".join(governance.get("errors", []))
            )


def apply_work_init(plan: WorkInitPlan) -> WorkInitReceipt:
    """只消费 canonical plan；在 project lock 内 fresh replan/CAS 后写入。"""

    if plan.blocked:
        raise ValueError(
            "Work init plan is blocked: "
            + "; ".join(item.message for item in plan.conflicts)
        )
    mutating = any(action.action != "noop" for action in plan.actions)
    if plan.release_root is None:
        if mutating:
            raise ValueError("legacy Work init plan cannot invoke a writer")
        fresh_legacy = plan_work_init(
            plan.process_root,
            plan.work,
            human_design_gate_ref=plan.human_design_gate_ref,
        )
        if fresh_legacy.plan_digest != plan.plan_digest or fresh_legacy.blocked:
            raise ValueError("Work init plan is stale; rebuild plan before apply")
        return _make_work_init_receipt(plan, decision="PASS")
    if plan.process_root is None or plan.execution_context is None:
        raise ValueError("canonical Work init plan lacks execution context")
    from meta_flow.work.init_transaction import (
        apply_work_init_transaction_targets,
        begin_work_init_transaction,
        commit_work_init_transaction,
        rollback_work_init_transaction,
    )
    from meta_flow.work.lifecycle_transaction import (
        acquire_shared_projection_writer_lock,
        assert_work_close_shared_projection_lineage,
        discard_shared_projection_successor,
        record_work_init_shared_projection_successor,
        refresh_state_projection_if_initialized,
        release_shared_projection_writer_lock,
    )

    assert_work_close_shared_projection_lineage(plan.process_root)
    domain_baseline = _current_domain_preimages(plan)
    if not mutating:
        fresh_noop = _plan_work_init_from_release_root(
            plan.release_root,
            plan.work,
            request_candidate=plan.request_candidate,
            human_design_gate_ref=plan.human_design_gate_ref,
            operation="apply",
        )
        if (
            fresh_noop.blocked
            or fresh_noop.compatibility_decision != plan.compatibility_decision
            or fresh_noop.target_preimages != plan.target_preimages
            or fresh_noop.execution_context is None
            or _context_authority_digest(fresh_noop.execution_context)
            != _context_authority_digest(plan.execution_context)
        ):
            raise ValueError("Work init plan is stale; rebuild plan before apply")
        return _make_work_init_receipt(plan, decision="PASS")

    if plan.admission_plan is None or plan.work.execution_unit is None:
        raise ValueError("mutating Work init requires one canonical admission plan")
    process_git_common_dir = _process_git_common_dir(plan.process_root)
    owner_token = secrets.token_hex(32)
    lock = acquire_admission_lock(
        process_git_common_dir,
        plan.admission_plan,
        owner_token=owner_token,
        owner_process_identity=(
            f"meta-flow-work-store:{plan.execution_context.process_root_identity}"
        ),
    )
    if lock.decision != "PASS" or lock.handle is None:
        _raise_apply_error(
            "Work init admission lock acquisition failed",
            plan,
            decision=(
                "PARTIAL_MUTATION"
                if lock.decision == "PARTIAL_MUTATION"
                else "BLOCKED"
            ),
            coordination_mutation_count=lock.coordination_mutation_count,
            durable_lock_count=lock.durable_lock_count,
            reason_codes=lock.conflicts,
            domain_baseline=domain_baseline,
        )

    coordination_mutations = lock.coordination_mutation_count
    project_index_updated = False
    failure: Exception | None = None
    failure_codes: tuple[str, ...] = ()
    shared_writer_lock = None
    shared_writer_id = f"work-init-{plan.work.work_id}-{secrets.token_hex(8)}"
    transaction_id = ""
    transaction_state = ""
    successor_id = ""
    state_refreshed = False
    try:
        fresh = _plan_work_init_from_release_root(
            plan.release_root,
            plan.work,
            request_candidate=plan.request_candidate,
            human_design_gate_ref=plan.human_design_gate_ref,
            operation="apply",
        )
        if (
            fresh.blocked
            or fresh.admission_plan is None
            or fresh.execution_context is None
            or fresh.compatibility_decision != plan.compatibility_decision
            or fresh.target_preimages != plan.target_preimages
            or fresh.lineage_preflight != plan.lineage_preflight
            or _context_authority_digest(fresh.execution_context)
            != _context_authority_digest(plan.execution_context)
        ):
            failure_codes = ("ADMISSION_PREIMAGE_DRIFT",)
            raise ValueError("Work init plan drifted inside the project lock")
        reservation = validate_admission_preimage(
            plan.admission_plan,
            lock.handle,
            process_git_common_dir,
            plan.work.execution_unit,
            fresh.execution_context.inventory.units,
            current_execution_control_policy().budget,
            fresh.execution_context.admission_facts(),
        )
        if reservation.decision != "READY":
            failure_codes = reservation.conflicts
            raise ValueError("Work init admission preimage drifted")

        shared_writer_lock = acquire_shared_projection_writer_lock(
            plan.process_root,
            shared_writer_id,
        )
        assert_work_close_shared_projection_lineage(plan.process_root)
        if _current_domain_preimages(plan) != domain_baseline:
            failure_codes = ("ADMISSION_PREIMAGE_DRIFT",)
            raise ValueError("Work init target preimage drifted before shared writer lock")
        targets = _work_init_transaction_targets(fresh)
        successor_before = {
            target.ref: target.before_digest
            for target in targets
            if target.ref == "PROJECT.yaml"
            or Path(target.ref).name == "PHASE.yaml"
        }
        transaction_id = begin_work_init_transaction(
            plan.process_root,
            operation="work.init",
            work_id=plan.work.work_id,
            plan_digest=plan.plan_digest,
            release_oid=fresh.execution_context.release_oid,
            process_oid=fresh.execution_context.process_oid,
            targets=targets,
        )
        transaction_state = "PREPARED"
        coordination_mutations += 1
        apply_work_init_transaction_targets(
            plan.process_root,
            transaction_id,
        )
        transaction_state = "APPLYING"
        successor_id = record_work_init_shared_projection_successor(
            plan.process_root,
            work_id=plan.work.work_id,
            before_digests=successor_before,
            expected_preflight=plan.lineage_preflight,
        )
        if successor_id:
            coordination_mutations += 1
        refreshed_refs = refresh_state_projection_if_initialized(plan.process_root)
        coordination_mutations += len(refreshed_refs)
        state_refreshed = bool(refreshed_refs)
        _validate_work_init_postimage(fresh)
        commit_work_init_transaction(
            plan.process_root,
            transaction_id,
            successor_id=successor_id,
        )
        transaction_state = "COMMITTED"
        project_index_updated = any(
            action.ref == "PROJECT.yaml" and action.action == "update"
            for action in plan.actions
        )
    except Exception as exc:
        failure = exc
        if not failure_codes:
            failure_codes = ("WORK_INIT_DOMAIN_WRITE_FAILED",)
        if successor_id:
            try:
                if discard_shared_projection_successor(
                    plan.process_root,
                    successor_id=successor_id,
                    operation="work.init",
                    writer_id=plan.work.work_id,
                ):
                    coordination_mutations += 1
                successor_id = ""
            except Exception:
                failure_codes = tuple(
                    sorted(
                        {
                            *failure_codes,
                            "WORK_INIT_SUCCESSOR_RECOVERY_FAILED",
                        }
                    )
                )
        if transaction_id and transaction_state != "COMMITTED":
            try:
                recovery = rollback_work_init_transaction(
                    plan.process_root,
                    transaction_id,
                    failure=str(exc),
                )
                transaction_state = recovery.decision
            except Exception:
                recovery = None
                transaction_state = "PARTIAL"
            if recovery is None or recovery.recovery_required:
                failure_codes = tuple(
                    sorted(
                        {
                            *failure_codes,
                            "WORK_INIT_TRANSACTION_RECOVERY_FAILED",
                        }
                    )
                )
        if state_refreshed and transaction_state == "RECOVERED":
            try:
                coordination_mutations += len(
                    refresh_state_projection_if_initialized(plan.process_root)
                )
                state_refreshed = False
            except Exception:
                failure_codes = tuple(
                    sorted(
                        {
                            *failure_codes,
                            "WORK_INIT_STATE_RECOVERY_FAILED",
                            "WORK_INIT_TRANSACTION_RECOVERY_FAILED",
                        }
                    )
                )

    if shared_writer_lock is not None:
        try:
            release_shared_projection_writer_lock(
                shared_writer_lock,
                shared_writer_id,
            )
        except Exception as exc:
            if failure is None:
                failure = exc
            failure_codes = tuple(
                sorted({*failure_codes, "SHARED_PROJECTION_LOCK_CLEANUP_FAILED"})
            )

    released = release_admission_lock(
        process_git_common_dir,
        lock.handle,
    )
    coordination_mutations += released.coordination_mutation_count
    domain_refs = _domain_refs_changed(plan, domain_baseline)
    if released.decision != "PASS":
        failure_codes = tuple(
            sorted({*failure_codes, *released.conflicts, "ADMISSION_LOCK_CLEANUP_FAILED"})
        )
        receipt = _make_work_init_receipt(
            plan,
            decision="PARTIAL_MUTATION",
            domain_refs=domain_refs,
            coordination_mutation_count=coordination_mutations,
            durable_lock_count=released.durable_lock_count,
            project_index_updated=project_index_updated,
            reason_codes=failure_codes,
            transaction_id=transaction_id,
            transaction_state=transaction_state,
            recovery_required=True,
            shared_projection_successor_id=successor_id,
        )
        raise WorkInitApplyError("Work init admission lock cleanup failed", receipt)
    if failure is not None:
        recovery_failed = "WORK_INIT_TRANSACTION_RECOVERY_FAILED" in failure_codes
        decision = (
            "PARTIAL_MUTATION"
            if domain_refs or recovery_failed or transaction_state == "COMMITTED"
            else "RECOVERED"
            if transaction_id
            else "BLOCKED"
        )
        receipt = _make_work_init_receipt(
            plan,
            decision=decision,
            domain_refs=domain_refs,
            coordination_mutation_count=coordination_mutations,
            durable_lock_count=0,
            project_index_updated=project_index_updated,
            reason_codes=failure_codes,
            transaction_id=transaction_id,
            transaction_state=transaction_state,
            recovery_required=decision == "PARTIAL_MUTATION",
            shared_projection_successor_id=successor_id,
        )
        raise WorkInitApplyError(str(failure), receipt) from failure
    return _make_work_init_receipt(
        plan,
        decision="PASS",
        domain_refs=domain_refs,
        coordination_mutation_count=coordination_mutations,
        durable_lock_count=0,
        project_index_updated=project_index_updated,
        transaction_id=transaction_id,
        transaction_state=transaction_state,
        shared_projection_successor_id=successor_id,
    )


@dataclass(frozen=True, slots=True)
class LegacyWorkInitRecoveryPlanV1:
    decision: str
    release_root: Path
    process_root: Path
    work_id: str
    release_oid: str
    process_oid: str
    targets: tuple[Any, ...]
    lineage_preflight: tuple[tuple[str, str, str, str], ...]
    blockers: tuple[str, ...]
    plan_digest: str

    @property
    def ready(self) -> bool:
        return self.decision == "READY" and not self.blockers

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "LegacyWorkInitRecoveryPlanV1",
            "operation": "work.init.recover-legacy-partial",
            "decision": self.decision,
            "work_id": self.work_id,
            "release_oid": self.release_oid,
            "process_oid": self.process_oid,
            "targets": [target.as_plan_dict() for target in self.targets],
            "lineage_preflight": [
                {
                    "ref": ref,
                    "anchor_close_authorization_id": anchor,
                    "predecessor_successor_id": predecessor,
                    "before_digest": before_digest,
                }
                for ref, anchor, predecessor, before_digest in self.lineage_preflight
            ],
            "blockers": list(self.blockers),
            "plan_digest": self.plan_digest,
            "mutation_count": 0,
            "recovery_disposition": "exact-rollback",
            "next_action": (
                "apply this plan, stop, then rebuild Work-init plan"
                if self.ready
                else "resolve blockers without editing consumer truth by hand"
            ),
        }


def recover_partial_work_init_transaction(
    release_root: Path,
    *,
    transaction_id: str,
    expected_plan_digest: str,
) -> dict[str, Any]:
    """恢复新协议留下的 PARTIAL/APPLYING manifest，并重新收敛 State。"""

    from meta_flow.project.process_route import require_process_route
    from meta_flow.work.init_transaction import (
        inspect_work_init_transactions,
        recover_work_init_transaction,
    )
    from meta_flow.work.lifecycle_transaction import (
        acquire_shared_projection_writer_lock,
        assert_work_close_shared_projection_lineage,
        discard_shared_projection_successor,
        refresh_state_projection_if_initialized,
        release_shared_projection_writer_lock,
        shared_projection_successor_for_writer,
    )

    release = release_root.resolve()
    process = require_process_route(release).process_root.resolve()
    release_oid = _repository_head_oid(release)
    process_oid = _repository_head_oid(process)
    writer_id = f"work-init-transaction-recover-{transaction_id[-32:]}"
    shared_lock = acquire_shared_projection_writer_lock(process, writer_id)
    try:
        inspection = inspect_work_init_transactions(process)
        matches = [
            item
            for item in inspection["transactions"]
            if item["transaction_id"] == transaction_id
        ]
        if len(matches) != 1:
            raise ValueError("Work-init transaction identity is unavailable")
        transaction = matches[0]
        if transaction["plan_digest"] != expected_plan_digest:
            raise ValueError("Work-init transaction plan digest differs")
        work_id = str(transaction["work_id"])
        successor_id = shared_projection_successor_for_writer(
            process,
            operation="work.init",
            writer_id=work_id,
        )
        if successor_id:
            discard_shared_projection_successor(
                process,
                successor_id=successor_id,
                operation="work.init",
                writer_id=work_id,
            )
        receipt = recover_work_init_transaction(
            process,
            transaction_id,
            expected_plan_digest=expected_plan_digest,
            release_oid=release_oid,
            process_oid=process_oid,
        )
        if receipt.decision != "RECOVERED":
            return receipt.as_dict()
        refreshed_refs = refresh_state_projection_if_initialized(process)
        assert_work_close_shared_projection_lineage(process)
        return {
            **receipt.as_dict(),
            "decision": "RECOVERED",
            "state_refreshed_refs": list(refreshed_refs),
            "next_action": "stop and rebuild the Work-init plan",
        }
    finally:
        release_shared_projection_writer_lock(shared_lock, writer_id)


def _repository_head_oid(root: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    oid = completed.stdout.strip() if completed.returncode == 0 else ""
    if len(oid) != 40 or any(character not in "0123456789abcdef" for character in oid):
        raise ValueError("repository HEAD OID is unavailable")
    return oid


def plan_legacy_partial_work_init_recovery(
    release_root: Path,
    work_id: str,
) -> LegacyWorkInitRecoveryPlanV1:
    """识别 0.4.1 无 manifest 的 Work-init 部分写入并规划 exact rollback。"""

    from meta_flow.project.governance_projection import validate_governance_projection
    from meta_flow.project.process_route import require_process_route
    from meta_flow.state import current as state_current
    from meta_flow.state.formal_projection import (
        build_formal_truth_snapshot,
        derive_formal_truth_patch,
    )
    from meta_flow.work.init_transaction import (
        build_transaction_target,
        inspect_work_init_transactions,
    )
    from meta_flow.work.lifecycle_transaction import (
        plan_shared_projection_successor_preflight,
    )

    release = release_root.resolve()
    blockers: list[str] = []
    targets: tuple[Any, ...] = ()
    lineage_preflight: tuple[tuple[str, str, str, str], ...] = ()
    try:
        route = require_process_route(release)
        process = route.process_root.resolve()
        release_oid = _repository_head_oid(release)
        process_oid = _repository_head_oid(process)
    except (OSError, ValueError) as exc:
        process = Path()
        release_oid = ""
        process_oid = ""
        blockers.append(str(exc))
    if not blockers:
        try:
            inspection = inspect_work_init_transactions(process, work_id=work_id)
            if inspection["transactions"]:
                raise ValueError(
                    "Work already has a native Work-init transaction; recover that transaction"
                )
            work = load_work(process, work_id)
            if work.status != "planned" or work.execution_unit is None:
                raise ValueError(
                    "legacy partial recovery requires one planned typed Work"
                )
            if not work.phase_ref:
                raise ValueError("legacy partial recovery requires one declared Phase")
            project = load_project(process)
            phase = load_phase(process, work.phase_ref)
            if project.active_work_refs.count(work.work_ref) != 1:
                raise ValueError(
                    "Project must contain the partial Work ref exactly once"
                )
            if phase.work_refs.count(work.work_ref) != 1:
                raise ValueError(
                    "Phase must contain the partial Work ref exactly once"
                )
            previous_project = replace(
                project,
                active_work_refs=tuple(
                    ref for ref in project.active_work_refs if ref != work.work_ref
                ),
            )
            previous_phase = replace(
                phase,
                work_refs=tuple(ref for ref in phase.work_refs if ref != work.work_ref),
            )
            project_bytes = _render_yaml_bytes(previous_project.as_dict())
            phase_bytes = _render_yaml_bytes(previous_phase.as_dict())
            previous_digests = {
                "PROJECT.yaml": sha256(project_bytes).hexdigest(),
                work.phase_ref: sha256(phase_bytes).hexdigest(),
            }
            lineage_preflight = plan_shared_projection_successor_preflight(
                process,
                operation="work.init",
                writer_id=work.work_id,
                before_digests=previous_digests,
                allowed_refs=("PROJECT.yaml", work.phase_ref),
            )
            state_path = process / "state/STATE.current.json"
            if state_path.is_file() and not state_path.is_symlink():
                state = json.loads(state_path.read_text(encoding="utf-8"))
                overrides = {
                    "process/PROJECT.yaml": (
                        previous_project.as_dict(),
                        project_bytes,
                    ),
                    "process/" + work.phase_ref: (
                        previous_phase.as_dict(),
                        phase_bytes,
                    ),
                }
                snapshot = build_formal_truth_snapshot(
                    release,
                    process_root=process,
                    object_overrides=overrides,
                )
                patch = derive_formal_truth_patch(state, snapshot)
                if state.get("formal_truth_projection") != snapshot or any(
                    state.get(field) != patch[field]
                    for field in (
                        "current_phase",
                        "active_change",
                        "blocked",
                        "next_action",
                    )
                ):
                    raise ValueError(
                        "State is not the exact pre-Work-init formal truth generation"
                    )
                current_findings = state_current.validate_current_projection(release)
                if current_findings:
                    raise ValueError(
                        "CURRENT is not bound to the retained State generation: "
                        + "; ".join(item.message for item in current_findings)
                    )
            governance_path = process / "governance/GOVERNANCE-BASELINE.json"
            if governance_path.exists() or governance_path.is_symlink():
                governance = validate_governance_projection(release, process)
                if governance["decision"] != "PASS":
                    raise ValueError(
                        "governance projection is not current: "
                        + "; ".join(governance.get("errors", []))
                    )
            targets = (
                build_transaction_target(
                    process,
                    ref=work.work_ref,
                    after_bytes=None,
                ),
                build_transaction_target(
                    process,
                    ref="PROJECT.yaml",
                    after_bytes=project_bytes,
                ),
                build_transaction_target(
                    process,
                    ref=work.phase_ref,
                    after_bytes=phase_bytes,
                ),
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            blockers.append(str(exc))
    fields = {
        "schema_version": 1,
        "operation": "work.init.recover-legacy-partial",
        "work_id": work_id,
        "release_oid": release_oid,
        "process_oid": process_oid,
        "targets": [target.as_plan_dict() for target in targets],
        "lineage_preflight": [list(item) for item in lineage_preflight],
        "blockers": blockers,
    }
    return LegacyWorkInitRecoveryPlanV1(
        decision="BLOCKED" if blockers else "READY",
        release_root=release,
        process_root=process,
        work_id=work_id,
        release_oid=release_oid,
        process_oid=process_oid,
        targets=targets,
        lineage_preflight=lineage_preflight,
        blockers=tuple(blockers),
        plan_digest=_digest(fields),
    )


def apply_legacy_partial_work_init_recovery(
    plan: LegacyWorkInitRecoveryPlanV1,
    *,
    expected_plan_digest: str,
) -> dict[str, Any]:
    """应用 exact rollback；成功后返回 RECOVERED，并强制调用方停止重规划。"""

    from meta_flow.project.governance_projection import validate_governance_projection
    from meta_flow.state import current as state_current
    from meta_flow.work.init_transaction import (
        apply_work_init_transaction_targets,
        begin_work_init_transaction,
        commit_work_init_transaction,
        rollback_work_init_transaction,
    )
    from meta_flow.work.lifecycle_transaction import (
        acquire_shared_projection_writer_lock,
        assert_work_close_shared_projection_lineage,
        release_shared_projection_writer_lock,
    )

    if not plan.ready:
        raise ValueError("blocked legacy Work-init recovery plan cannot apply")
    if expected_plan_digest != plan.plan_digest:
        raise ValueError("legacy Work-init recovery plan digest differs")
    fresh = plan_legacy_partial_work_init_recovery(
        plan.release_root,
        plan.work_id,
    )
    if fresh.as_dict() != plan.as_dict():
        raise ValueError("legacy Work-init recovery plan drifted before lock")
    writer_id = f"work-init-recover-{plan.work_id}"
    shared_lock = acquire_shared_projection_writer_lock(plan.process_root, writer_id)
    transaction_id = ""
    try:
        locked = plan_legacy_partial_work_init_recovery(
            plan.release_root,
            plan.work_id,
        )
        if locked.as_dict() != plan.as_dict():
            raise ValueError("legacy Work-init recovery plan drifted inside lock")
        transaction_id = begin_work_init_transaction(
            plan.process_root,
            operation="work.init.recover-legacy-partial",
            work_id=plan.work_id,
            plan_digest=plan.plan_digest,
            release_oid=plan.release_oid,
            process_oid=plan.process_oid,
            targets=plan.targets,
        )
        apply_work_init_transaction_targets(plan.process_root, transaction_id)
        assert_work_close_shared_projection_lineage(plan.process_root)
        state_errors, _state_warnings = state_current.check_current_state(
            plan.release_root,
            mode="enforce",
        )
        if state_errors:
            raise ValueError(
                "State is not current after legacy Work-init recovery: "
                + "; ".join(state_errors)
            )
        governance_path = (
            plan.process_root / "governance/GOVERNANCE-BASELINE.json"
        )
        if governance_path.exists() or governance_path.is_symlink():
            governance = validate_governance_projection(
                plan.release_root,
                plan.process_root,
            )
            if governance["decision"] != "PASS":
                raise ValueError(
                    "governance projection is stale after recovery: "
                    + "; ".join(governance.get("errors", []))
                )
        commit_work_init_transaction(
            plan.process_root,
            transaction_id,
            successor_id="",
        )
        return {
            "schema_version": 1,
            "kind": "LegacyWorkInitRecoveryReceiptV1",
            "operation": "work.init.recover-legacy-partial",
            "decision": "RECOVERED",
            "work_id": plan.work_id,
            "plan_digest": plan.plan_digest,
            "transaction_id": transaction_id,
            "transaction_state": "COMMITTED",
            "mutation_count": len(plan.targets),
            "mutated_refs": [target.ref for target in plan.targets],
            "recovery_required": False,
            "next_action": "stop and rebuild the Work-init plan",
        }
    except Exception as exc:
        if transaction_id:
            rollback = rollback_work_init_transaction(
                plan.process_root,
                transaction_id,
                failure=str(exc),
            )
            if rollback.recovery_required:
                raise ValueError(
                    "legacy Work-init recovery failed and requires transaction recovery"
                ) from exc
        raise
    finally:
        release_shared_projection_writer_lock(shared_lock, writer_id)


def close_work(
    process_root: Path,
    work_id: str,
    *,
    expected_status: str,
    outcome: str,
    result_ref: str = "",
    authorization: object | None = None,
) -> Work:
    """兼容 facade；所有写入必须携带绑定当前 plan 的 typed authorization。"""

    from meta_flow.work.lifecycle_transaction import (
        WorkCloseAuthorizationV1,
        apply_work_close,
        plan_work_close,
    )

    if not isinstance(authorization, WorkCloseAuthorizationV1):
        raise ValueError("Work close requires WorkCloseAuthorizationV1")
    plan = plan_work_close(
        process_root,
        work_id,
        expected_status=expected_status,
        outcome=outcome,
        result_ref=result_ref,
    )
    receipt = apply_work_close(process_root, plan, authorization)
    if receipt.decision != "PASS":
        raise ValueError(
            "Work close transaction did not commit: "
            f"{receipt.decision}:{','.join(receipt.reason_codes)}"
        )
    return load_work(process_root, work_id)
