"""Work create-only 计划、索引和恢复友好 apply。"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Any

from meta_flow.project.governance import load_phase, replace_phase
from meta_flow.project.model import Project, is_safe_ref, load_project, replace_project
from meta_flow.project.scale import load_yaml_object
from meta_flow.work.model import Work, load_work, work_path, write_work_create_only


@dataclass(frozen=True)
class WorkInitAction:
    action: str
    ref: str
    reason: str


@dataclass(frozen=True)
class WorkInitConflict:
    code: str
    ref: str
    message: str


@dataclass(frozen=True)
class WorkInitPlan:
    process_root: Path
    work: Work
    project: Project | None
    actions: tuple[WorkInitAction, ...]
    conflicts: tuple[WorkInitConflict, ...]
    plan_digest: str

    @property
    def blocked(self) -> bool:
        return bool(self.conflicts)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "decision": "BLOCKED" if self.blocked else "READY",
            "process_root": str(self.process_root),
            "work_id": self.work.work_id,
            "work_ref": self.work.work_ref,
            "risk_profile": self.work.risk_profile,
            "scope_digest": self.work.scope.digest,
            "budget": self.work.budget.as_dict(),
            "actions": [action.__dict__ for action in self.actions],
            "conflicts": [conflict.__dict__ for conflict in self.conflicts],
            "plan_digest": self.plan_digest,
            "mutation_count": 0,
        }


@dataclass(frozen=True)
class WorkInitReceipt:
    decision: str
    work_id: str
    work_ref: str
    plan_digest: str
    mutation_count: int
    project_index_updated: bool
    recovery_route: str

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class WorkInitApplyError(RuntimeError):
    def __init__(self, message: str, receipt: WorkInitReceipt) -> None:
        super().__init__(message)
        self.receipt = receipt


def _same_work(existing: Work, requested: Work) -> bool:
    return existing == requested


def _digest(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def plan_work_init(process_root: Path, work: Work) -> WorkInitPlan:
    root = process_root.resolve()
    actions: list[WorkInitAction] = []
    conflicts: list[WorkInitConflict] = []
    project: Project | None = None
    try:
        project = load_project(root)
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

    request_path = root / work.request_ref
    if not request_path.is_file():
        conflicts.append(WorkInitConflict("request_missing", work.request_ref, "confirmed REQUEST.md is missing"))
    if work.request_ref not in work.scope.allowed_reads:
        conflicts.append(WorkInitConflict("request_out_of_scope", work.request_ref, "request_ref must be an exact allowed_read"))
    if len(work.scope.allowed_reads) > work.budget.reads:
        conflicts.append(WorkInitConflict("read_scope_over_budget", work.work_ref, "allowed_reads count exceeds budget"))
    if len(work.scope.allowed_writes) > work.budget.writes:
        conflicts.append(WorkInitConflict("write_scope_over_budget", work.work_ref, "allowed_writes count exceeds budget"))
    if len(work.scope.required_checks) > work.budget.check_groups:
        conflicts.append(WorkInitConflict("check_scope_over_budget", work.work_ref, "required_checks count exceeds budget"))

    phase = None
    if work.phase_ref:
        try:
            phase = load_phase(root, work.phase_ref)
        except (OSError, ValueError) as exc:
            conflicts.append(WorkInitConflict("phase_invalid", work.phase_ref, str(exc)))
        else:
            if phase.project_id != work.project_id:
                conflicts.append(WorkInitConflict("phase_project_mismatch", work.phase_ref, "Phase belongs to another project"))
            elif work.work_ref in phase.work_refs:
                actions.append(WorkInitAction("noop", work.phase_ref, "Phase already indexes Work"))
            else:
                actions.append(WorkInitAction("update", work.phase_ref, "append Work ref to Phase"))

    path = work_path(root, work.work_id)
    if path.exists() or path.is_symlink():
        try:
            existing = load_work(root, work.work_id)
        except (OSError, ValueError) as exc:
            conflicts.append(WorkInitConflict("work_invalid", work.work_ref, str(exc)))
        else:
            if not _same_work(existing, work):
                conflicts.append(WorkInitConflict("work_conflict", work.work_ref, "existing WORK.yaml differs"))
            else:
                actions.append(WorkInitAction("noop", work.work_ref, "matching WORK.yaml already exists"))
    else:
        actions.append(WorkInitAction("create", work.work_ref, "create Work envelope"))

    if project is not None:
        if work.work_ref in project.active_work_refs:
            if not path.is_file():
                conflicts.append(WorkInitConflict("broken_project_index", work.work_ref, "Project indexes a missing Work"))
            else:
                actions.append(WorkInitAction("noop", "PROJECT.yaml", "Project already indexes Work"))
        else:
            actions.append(WorkInitAction("update", "PROJECT.yaml", "append active Work ref"))

    digest_source = {
        "schema_version": 1,
        "process_root": str(root),
        "project": project.as_dict() if project else None,
        "phase": phase.as_dict() if phase else None,
        "work": work.as_dict(),
        "request_sha256": sha256(request_path.read_bytes()).hexdigest() if request_path.is_file() else "",
        "actions": [action.__dict__ for action in actions],
        "conflicts": [conflict.__dict__ for conflict in conflicts],
    }
    return WorkInitPlan(
        process_root=root,
        work=work,
        project=project,
        actions=tuple(actions),
        conflicts=tuple(conflicts),
        plan_digest=_digest(digest_source),
    )


def apply_work_init(plan: WorkInitPlan) -> WorkInitReceipt:
    if plan.blocked:
        raise ValueError("Work init plan is blocked: " + "; ".join(item.message for item in plan.conflicts))
    fresh = plan_work_init(plan.process_root, plan.work)
    if fresh.plan_digest != plan.plan_digest:
        raise ValueError("Work init plan is stale; rebuild plan before apply")
    mutations = 0
    indexed = False
    try:
        path = work_path(plan.process_root, plan.work.work_id)
        if not path.exists() and not path.is_symlink():
            write_work_create_only(plan.process_root, plan.work)
            mutations += 1
        project = load_project(plan.process_root)
        if plan.work.work_ref not in project.active_work_refs:
            updated = replace(
                project,
                active_work_refs=(*project.active_work_refs, plan.work.work_ref),
            )
            replace_project(
                plan.process_root,
                updated,
                expected_project_id=project.project_id,
            )
            indexed = True
            mutations += 1
        if plan.work.phase_ref:
            phase = load_phase(plan.process_root, plan.work.phase_ref)
            if plan.work.work_ref not in phase.work_refs:
                replace_phase(
                    plan.process_root,
                    replace(phase, work_refs=(*phase.work_refs, plan.work.work_ref)),
                    expected_phase_id=phase.phase_id,
                )
                mutations += 1
        return WorkInitReceipt(
            decision="PASS",
            work_id=plan.work.work_id,
            work_ref=plan.work.work_ref,
            plan_digest=plan.plan_digest,
            mutation_count=mutations,
            project_index_updated=indexed,
            recovery_route="none",
        )
    except Exception as exc:
        receipt = WorkInitReceipt(
            decision="PARTIAL" if mutations else "BLOCKED",
            work_id=plan.work.work_id,
            work_ref=plan.work.work_ref,
            plan_digest=plan.plan_digest,
            mutation_count=mutations,
            project_index_updated=indexed,
            recovery_route="rebuild-plan-and-repair-work-index",
        )
        raise WorkInitApplyError(str(exc), receipt) from exc


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
