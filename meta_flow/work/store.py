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
from meta_flow.project.governance import load_phase, replace_phase
from meta_flow.project.model import Project, is_safe_ref, load_project, replace_project
from meta_flow.project.read_contract import ReadContextProtocol
from meta_flow.project.scale import load_yaml_object
from meta_flow.work.model import Work, load_work, work_path, write_work_create_only
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
            else "none"
        ),
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


def _write_request_candidate(
    process_root: Path,
    candidate: RequestMaterializationCandidateV1,
) -> None:
    path = process_root / candidate.request_ref
    if path.exists() or path.is_symlink():
        raise FileExistsError("REQUEST target already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(candidate.content_bytes)


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

        action_by_ref = {action.ref: action for action in plan.actions}
        request_action = action_by_ref.get(plan.work.request_ref)
        if request_action is not None and request_action.action == "create":
            if plan.request_candidate is None:
                raise ValueError("REQUEST create action lacks a bound candidate")
            _write_request_candidate(plan.process_root, plan.request_candidate)
        work_action = action_by_ref.get(plan.work.work_ref)
        if work_action is not None and work_action.action == "create":
            write_work_create_only(plan.process_root, plan.work)
        project_action = action_by_ref.get("PROJECT.yaml")
        if project_action is not None and project_action.action == "update":
            project = load_project(plan.process_root)
            replace_project(
                plan.process_root,
                replace(
                    project,
                    active_work_refs=(*project.active_work_refs, plan.work.work_ref),
                ),
                expected_project_id=project.project_id,
            )
            project_index_updated = True
        if plan.work.phase_ref:
            phase_action = action_by_ref.get(plan.work.phase_ref)
            if phase_action is not None and phase_action.action == "update":
                phase = load_phase(plan.process_root, plan.work.phase_ref)
                replace_phase(
                    plan.process_root,
                    replace(phase, work_refs=(*phase.work_refs, plan.work.work_ref)),
                    expected_phase_id=phase.phase_id,
                )
    except Exception as exc:
        failure = exc
        if not failure_codes:
            failure_codes = ("WORK_INIT_DOMAIN_WRITE_FAILED",)

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
        )
        raise WorkInitApplyError("Work init admission lock cleanup failed", receipt)
    if failure is not None:
        decision = "PARTIAL_MUTATION" if domain_refs else "BLOCKED"
        receipt = _make_work_init_receipt(
            plan,
            decision=decision,
            domain_refs=domain_refs,
            coordination_mutation_count=coordination_mutations,
            durable_lock_count=0,
            project_index_updated=project_index_updated,
            reason_codes=failure_codes,
        )
        raise WorkInitApplyError(str(failure), receipt) from failure
    return _make_work_init_receipt(
        plan,
        decision="PASS",
        domain_refs=domain_refs,
        coordination_mutation_count=coordination_mutations,
        durable_lock_count=0,
        project_index_updated=project_index_updated,
    )


def close_work(
    process_root: Path,
    work_id: str,
    *,
    expected_status: str,
    outcome: str,
    result_ref: str = "",
) -> Work:
    if outcome not in {"completed", "cancelled"}:
        raise ValueError("outcome must be completed or cancelled")
    if outcome == "completed":
        if not result_ref or not is_safe_ref(result_ref):
            raise ValueError("completed Work requires result_ref")
        result_path = process_root.resolve() / result_ref
        if not result_path.is_file():
            raise ValueError(f"Work result is missing: {result_ref}")
        result_payload = load_yaml_object(result_path)
        if (
            set(result_payload) != {"schema_version", "work_id", "decision"}
            or result_payload.get("schema_version") != 1
            or result_payload.get("work_id") != work_id
            or result_payload.get("decision") != "PASS"
        ):
            raise ValueError("completed Work requires one exact matching PASS result")
    from meta_flow.work.lifecycle import update_work_status

    current = load_work(process_root, work_id)
    if current.status == outcome and (outcome == "cancelled" or current.result_ref == result_ref):
        closed = current
    else:
        closed = update_work_status(
            process_root,
            work_id,
            expected_status=expected_status,
            new_status=outcome,
            result_ref=result_ref,
        )
    project = load_project(process_root)
    if closed.work_ref in project.active_work_refs:
        updated = replace(
            project,
            active_work_refs=tuple(
                ref for ref in project.active_work_refs if ref != closed.work_ref
            ),
        )
        replace_project(
            process_root,
            updated,
            expected_project_id=project.project_id,
        )
    if closed.phase_ref:
        phase = load_phase(process_root, closed.phase_ref)
        phase_work_refs = tuple(ref for ref in phase.work_refs if ref != closed.work_ref)
        phase_result_refs = phase.result_refs
        if result_ref and result_ref not in phase_result_refs:
            phase_result_refs = (*phase_result_refs, result_ref)
        if phase_work_refs != phase.work_refs or phase_result_refs != phase.result_refs:
            replace_phase(
                process_root,
                replace(
                    phase,
                    work_refs=phase_work_refs,
                    result_refs=phase_result_refs,
                ),
                expected_phase_id=phase.phase_id,
            )
    return load_work(process_root, work_id)
