"""PROJECT/ROADMAP/Phase/Work/CR formal truth 到运行态的确定性投影。"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from meta_flow.project.model import is_safe_ref
from meta_flow.project.process_route import _resolve_runtime_ref
from meta_flow.project.scale import load_yaml_object
from meta_flow.workflow.cr_model import parse_frontmatter

PROJECT_REF = "process/PROJECT.yaml"
ROADMAP_REF = "process/ROADMAP.yaml"
CR_LEDGER_REF = "process/state/CR-LEDGER.ndjson"
TERMINAL_WORK = frozenset({"completed", "cancelled", "archived"})
TERMINAL_CR = frozenset({"closed", "cancelled", "superseded", "archived"})


# CR-071 S07 deliberately keeps recovery assessment and planning independent
# from the derived-projection writer.  These types do not know a process path
# and consequently cannot write a gate, lifecycle truth, ledger, or projection.
_PREDICATES = (
    "location", "owner", "current_lineage", "integrity", "completeness", "freshness", "validity"
)
_PRESERVED_BLOCKERS = frozenset({"partial", "recovered", "human-pending"})


@dataclass(frozen=True)
class ExpectedEvidenceSchemaV1:
    """Independent, closed evidence requirements for a recovery candidate."""

    identity: Mapping[str, Any]
    selection: Mapping[str, Any]
    integrity: Mapping[str, Any]
    completeness: Mapping[str, Any]
    freshness: Mapping[str, Any]
    validity: Mapping[str, Any]
    producer_contract_digest: str
    schema_digest: str


@dataclass(frozen=True)
class FailureAssessmentV1:
    decision: str
    reason_code: str
    mutation_count: int
    reprojection_count: int
    predicate_results: Mapping[str, bool]
    preserved_blockers: tuple[str, ...]
    source_evidence_digest: str
    expected_schema_digest: str


@dataclass(frozen=True)
class ReprojectionPlanV1:
    decision: str
    mutation_count: int
    assessment_digest: str
    source_evidence_digest: str
    expected_schema_digest: str
    target_projection_ref: str
    target_projection_preimage_digest: str
    target_blocker_id: str
    target_blocker_preimage_digest: str
    release_oid: str
    process_oid: str
    dirty_inventory_digest: str
    scope_authz_plan_digest: str
    native_writer_id: str
    plan_digest: str


@dataclass(frozen=True)
class ProjectionMutationReceiptV1:
    decision: str
    mutation_count: int
    plan_digest: str
    source_evidence_digest: str
    target_blocker_id: str
    reason_code: str = ""


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _blocker_kind(value: Any) -> str:
    return str(value or "unknown").strip().lower().replace("_", "-").replace(" ", "-")


def _digest_fields(value: Mapping[str, Any]) -> str:
    return _canonical_digest(dict(value))


def _receipt(
    decision: str, plan: ReprojectionPlanV1, *, reason_code: str = ""
) -> ProjectionMutationReceiptV1:
    return ProjectionMutationReceiptV1(
        decision=decision,
        mutation_count=1 if decision == "APPLIED" else 0,
        plan_digest=plan.plan_digest,
        source_evidence_digest=plan.source_evidence_digest,
        target_blocker_id=plan.target_blocker_id,
        reason_code=reason_code,
    )


def evaluate_reprojection(
    expected: ExpectedEvidenceSchemaV1 | Mapping[str, Any],
    failure: Mapping[str, Any],
    candidate: Mapping[str, Any],
    blockers: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] = (),
) -> FailureAssessmentV1:
    """Return a positive-sufficient, zero-write recovery assessment.

    The candidate must explicitly report every closed predicate as ``True``.
    Absence, a non-boolean value, unfamiliar blocker, source drift, or a
    non-exact original reason is a deny; no inference is permitted here.
    """

    expected_values = _mapping(expected.__dict__ if isinstance(expected, ExpectedEvidenceSchemaV1) else expected)
    schema_digest = str(expected_values.get("schema_digest") or "")
    source_digest = str(failure.get("source_evidence_digest") or "")
    predicate_values = _mapping(candidate.get("predicate_results"))
    predicates = {name: predicate_values.get(name) is True for name in _PREDICATES}
    preserved = tuple(sorted(
        _blocker_kind(item.get("class") or item.get("status") or item.get("id"))
        for item in blockers
        if isinstance(item, Mapping)
    ))
    reason = ""
    if not schema_digest or expected_values.get("derived_from_failure_projection") is True:
        reason = "EXPECTED_SCHEMA_UNAVAILABLE"
    elif str(failure.get("reason_code") or "") != "missing-evidence":
        reason = "ORIGINAL_REASON_NOT_MISSING_EVIDENCE"
    elif int(failure.get("reprojection_count") or 0) != 0:
        reason = "REPROJECTION_ALREADY_ATTEMPTED"
    elif candidate.get("candidate_count") != 1:
        reason = "AMBIGUOUS_OR_MISSING_CANDIDATE"
    elif candidate.get("source_identity_matches") is not True:
        reason = "SOURCE_IDENTITY_DRIFT"
    elif not all(predicates.values()):
        reason = "VALID_ARTIFACT_BUT_INSUFFICIENT"
    elif any(value in _PRESERVED_BLOCKERS or value not in {"missing-evidence"} for value in preserved):
        reason = "HIGHER_OR_UNKNOWN_BLOCKER_PRESENT"
    decision = "RECOVERABLE" if not reason else "DENY"
    return FailureAssessmentV1(
        decision=decision, reason_code=reason, mutation_count=0,
        reprojection_count=int(failure.get("reprojection_count") or 0),
        predicate_results=predicates, preserved_blockers=preserved,
        source_evidence_digest=source_digest, expected_schema_digest=schema_digest,
    )


def plan_reprojection(
    assessment: FailureAssessmentV1,
    target: Mapping[str, Any],
    authz_scope: Mapping[str, Any],
) -> ReprojectionPlanV1:
    """Build a pure, closed-delta plan.  It never applies a projection."""

    target_values = _mapping(target)
    authz = _mapping(authz_scope)
    values = {
        "assessment_digest": _digest_fields(assessment.__dict__),
        "source_evidence_digest": assessment.source_evidence_digest,
        "expected_schema_digest": assessment.expected_schema_digest,
        "target_projection_ref": str(target_values.get("target_projection_ref") or ""),
        "target_projection_preimage_digest": str(target_values.get("target_projection_preimage_digest") or ""),
        "target_blocker_id": str(target_values.get("target_blocker_id") or ""),
        "target_blocker_preimage_digest": str(target_values.get("target_blocker_preimage_digest") or ""),
        "release_oid": str(authz.get("release_oid") or ""),
        "process_oid": str(authz.get("process_oid") or ""),
        "dirty_inventory_digest": str(authz.get("dirty_inventory_digest") or ""),
        "scope_authz_plan_digest": str(authz.get("scope_authz_plan_digest") or ""),
        "native_writer_id": str(authz.get("native_writer_id") or ""),
    }
    complete = all(values.values())
    decision = "READY" if assessment.decision == "RECOVERABLE" and complete else "DENY"
    plan_digest = _canonical_digest({"decision": decision, **values})
    return ReprojectionPlanV1(decision=decision, mutation_count=0, plan_digest=plan_digest, **values)


def apply_reprojection_plan(
    plan: ReprojectionPlanV1,
    fresh_repository_snapshot: Mapping[str, Any],
    native_writer: Callable[[ReprojectionPlanV1, Mapping[str, Any]], Mapping[str, Any]] | None,
) -> ProjectionMutationReceiptV1:
    """Delegate one guarded apply to the existing native writer, or no-op.

    This boundary compares fresh facts rather than trusting the planning
    context.  It intentionally has no filesystem write primitive: only the
    injected native writer can perform the one allowed projection mutation.
    """

    fresh = _mapping(fresh_repository_snapshot)
    if plan.decision != "READY":
        return _receipt("BLOCKED_REPLAN", plan, reason_code="PLAN_NOT_READY")
    identity = (plan.source_evidence_digest, plan.expected_schema_digest, plan.target_blocker_id)
    if identity in {tuple(item) for item in fresh.get("applied_source_keys", ()) if isinstance(item, (tuple, list))}:
        return _receipt("NO_CHANGE", plan)
    required = {
        "release_oid": plan.release_oid,
        "process_oid": plan.process_oid,
        "dirty_inventory_digest": plan.dirty_inventory_digest,
        "target_projection_preimage_digest": plan.target_projection_preimage_digest,
        "target_blocker_preimage_digest": plan.target_blocker_preimage_digest,
        "scope_authz_plan_digest": plan.scope_authz_plan_digest,
        "native_writer_id": plan.native_writer_id,
        "source_evidence_digest": plan.source_evidence_digest,
    }
    if any(str(fresh.get(key) or "") != value for key, value in required.items()):
        return _receipt("BLOCKED_REPLAN", plan, reason_code="FRESH_FACT_DRIFT")
    blocker_classes = {
        _blocker_kind(item.get("class") or item.get("status"))
        for item in fresh.get("blockers", ())
        if isinstance(item, Mapping)
    }
    if any(item in _PRESERVED_BLOCKERS or item not in {"missing-evidence"} for item in blocker_classes):
        return _receipt("BLOCKED_REPLAN", plan, reason_code="HIGHER_OR_UNKNOWN_BLOCKER_PRESENT")
    if native_writer is None:
        return _receipt("BLOCKED_REPLAN", plan, reason_code="NATIVE_WRITER_UNAVAILABLE")
    result = _mapping(native_writer(plan, fresh))
    if result.get("decision") != "APPLIED" or result.get("mutation_count") != 1:
        return _receipt("BLOCKED_REPLAN", plan, reason_code="NATIVE_WRITER_DENIED")
    return _receipt("APPLIED", plan)


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def _resolve(project_root: Path, logical_ref: str, process_root: Path | None) -> Path:
    if process_root is None:
        return _resolve_runtime_ref(project_root.resolve(), logical_ref)
    if not logical_ref.startswith("process/") or ".." in Path(logical_ref).parts:
        raise ValueError(f"formal truth ref is unsafe: {logical_ref}")
    return process_root.resolve() / logical_ref.removeprefix("process/")


def _load_object(
    project_root: Path,
    logical_ref: str,
    process_root: Path | None,
    object_overrides: Mapping[str, tuple[dict[str, Any], bytes]] | None = None,
) -> dict[str, Any]:
    if object_overrides is not None and logical_ref in object_overrides:
        return dict(object_overrides[logical_ref][0])
    path = _resolve(project_root, logical_ref, process_root)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"formal truth source missing or not regular: {logical_ref}")
    payload = load_yaml_object(path)
    if not isinstance(payload, dict):
        raise ValueError(f"formal truth source must be an object: {logical_ref}")
    return payload


def _source_receipt(
    project_root: Path,
    logical_ref: str,
    process_root: Path | None,
    object_overrides: Mapping[str, tuple[dict[str, Any], bytes]] | None = None,
) -> dict[str, str]:
    if object_overrides is not None and logical_ref in object_overrides:
        return {
            "ref": logical_ref,
            "digest": sha256(object_overrides[logical_ref][1]).hexdigest(),
        }
    path = _resolve(project_root, logical_ref, process_root)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"formal truth source missing or not regular: {logical_ref}")
    return {"ref": logical_ref, "digest": sha256(path.read_bytes()).hexdigest()}


def _active_cr_ids(
    project_root: Path,
    process_root: Path | None,
) -> tuple[list[str], list[dict[str, str]]]:
    path = _resolve(project_root, CR_LEDGER_REF, process_root)
    if path.is_symlink() or not path.is_file():
        return [], [{"ref": CR_LEDGER_REF, "digest": "missing"}]
    latest: dict[str, str] = {}
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"formal CR ledger is invalid at line {line_no}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"formal CR ledger row {line_no} must be an object")
        cr_id = str(row.get("id") or row.get("cr_id") or "")
        status = str(row.get("status") or row.get("lifecycle_status") or "").lower()
        if cr_id:
            latest[cr_id] = status
    sources = [{"ref": CR_LEDGER_REF, "digest": sha256(path.read_bytes()).hexdigest()}]
    changes_root = path.parent.parent / "changes"
    if changes_root.is_symlink() or not changes_root.is_dir():
        raise ValueError("formal CR truth root missing or not a regular directory")
    discovered: set[str] = set()
    for formal_path in sorted(changes_root.glob("CR-*.md")):
        if formal_path.is_symlink() or not formal_path.is_file():
            raise ValueError(f"formal CR truth is not regular: {formal_path.name}")
        fields = parse_frontmatter(formal_path.read_text(encoding="utf-8"))
        if fields.get("kind") != "cr":
            continue
        cr_id = str(fields.get("cr_id") or "")
        formal_ref = "process/changes/" + formal_path.name
        if not cr_id or cr_id in discovered:
            raise ValueError(f"formal CR truth identity missing or duplicate: {formal_ref}")
        discovered.add(cr_id)
        formal_status = str(
            fields.get("lifecycle_status") or fields.get("status") or ""
        ).lower()
        if not formal_status:
            raise ValueError(f"formal CR truth status missing: {formal_ref}")
        latest[cr_id] = formal_status
        sources.append({"ref": formal_ref, "digest": sha256(formal_path.read_bytes()).hexdigest()})
    missing_formal = sorted(set(latest) - discovered)
    if missing_formal:
        raise ValueError(
            "formal CR truth missing for ledger identities: " + ", ".join(missing_formal)
        )
    active = sorted(cr_id for cr_id, status in latest.items() if status not in TERMINAL_CR)
    return active, sources


def build_formal_truth_snapshot(
    project_root: Path,
    *,
    process_root: Path | None = None,
    object_overrides: Mapping[str, tuple[dict[str, Any], bytes]] | None = None,
) -> dict[str, Any]:
    """只沿 PROJECT→ROADMAP→declared Phase/Work 构建有界 formal truth。"""

    root = project_root.resolve()
    project = _load_object(root, PROJECT_REF, process_root, object_overrides)
    roadmap_ref = str(project.get("roadmap_ref") or "")
    if not roadmap_ref or roadmap_ref.startswith("/") or ".." in Path(roadmap_ref).parts:
        raise ValueError("PROJECT roadmap_ref is missing or unsafe")
    roadmap_logical = "process/" + roadmap_ref.removeprefix("process/")
    roadmap = _load_object(root, roadmap_logical, process_root, object_overrides)
    raw_phase_refs = roadmap.get("phase_refs")
    if not isinstance(raw_phase_refs, list) or not raw_phase_refs:
        raise ValueError("ROADMAP phase_refs must be a non-empty list")
    sources = [
        _source_receipt(root, PROJECT_REF, process_root, object_overrides),
        _source_receipt(root, roadmap_logical, process_root, object_overrides),
    ]
    active_phases: list[str] = []
    active_works: list[str] = []
    phase_statuses: dict[str, str] = {}
    seen_work_refs: set[str] = set()

    def include_work(work_ref: object, *, owner: str) -> None:
        if not isinstance(work_ref, str) or not is_safe_ref(
            work_ref,
            prefix="works",
        ):
            raise ValueError(f"{owner} work_ref is unsafe: {work_ref}")
        if work_ref in seen_work_refs:
            return
        seen_work_refs.add(work_ref)
        work_logical = "process/" + work_ref
        work = _load_object(
            root,
            work_logical,
            process_root,
            object_overrides,
        )
        sources.append(
            _source_receipt(
                root,
                work_logical,
                process_root,
                object_overrides,
            )
        )
        if str(work.get("status") or "").lower() not in TERMINAL_WORK:
            active_works.append(str(work.get("work_id") or Path(work_ref).parent.name))

    for raw_ref in raw_phase_refs:
        if not isinstance(raw_ref, str) or not raw_ref.startswith("phases/"):
            raise ValueError("ROADMAP phase_ref must use phases/<id>/PHASE.yaml")
        logical_ref = "process/" + raw_ref
        phase = _load_object(root, logical_ref, process_root, object_overrides)
        sources.append(_source_receipt(root, logical_ref, process_root, object_overrides))
        phase_id = str(phase.get("phase_id") or "")
        status = str(phase.get("status") or "").lower()
        if not phase_id or not status:
            raise ValueError(f"Phase identity/status missing: {logical_ref}")
        phase_statuses[phase_id] = status
        if status == "active":
            active_phases.append(phase_id)
        work_refs = phase.get("work_refs") or []
        if not isinstance(work_refs, list):
            raise ValueError(f"Phase work_refs must be a list: {logical_ref}")
        for work_ref in work_refs:
            include_work(work_ref, owner="Phase")
    project_work_refs = project.get("active_work_refs") or []
    if not isinstance(project_work_refs, list):
        raise ValueError("PROJECT active_work_refs must be a list")
    for work_ref in project_work_refs:
        include_work(work_ref, owner="PROJECT")
    active_crs, cr_sources = _active_cr_ids(root, process_root)
    sources.extend(cr_sources)
    source_digest = _canonical_digest(sources)
    return {
        "schema_version": 1,
        "project_status": str(project.get("status") or "").lower(),
        "roadmap_status": str(roadmap.get("status") or "").lower(),
        "phase_statuses": dict(sorted(phase_statuses.items())),
        "active_phase_ids": sorted(active_phases),
        "active_work_ids": sorted(active_works),
        "active_cr_ids": active_crs,
        "source_refs": [item["ref"] for item in sources],
        "source_digest": source_digest,
    }


def derive_formal_truth_patch(
    state: dict[str, Any],
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    active_phases = list(snapshot["active_phase_ids"])
    active_works = list(snapshot["active_work_ids"])
    active_crs = list(snapshot["active_cr_ids"])
    if len(active_crs) > 1:
        next_action = {
            "type": "resolve_multiple_active_changes",
            "text": "Resolve multiple active formal CRs before continuing.",
            "stop_reason": None,
        }
        active_change = None
    elif active_crs:
        active_change = active_crs[0]
        next_action = {
            "type": "continue_active_change",
            "text": f"Continue active formal change {active_change}.",
            "stop_reason": None,
        }
    elif active_works:
        active_change = None
        next_action = {
            "type": "continue_active_work",
            "text": f"Continue active Work {active_works[0]}.",
            "stop_reason": None,
        }
    elif active_phases:
        active_change = None
        next_action = {
            "type": "continue_active_phase",
            "text": f"Continue active Phase {active_phases[0]} using its declared results.",
            "stop_reason": None,
        }
    else:
        active_change = None
        next_action = {
            "type": "review_project_completion",
            "text": "Review project and roadmap completion state.",
            "stop_reason": None,
        }
    current_phase = active_phases[0] if len(active_phases) == 1 else (
        "multiple-active-phases" if active_phases else "project-completion"
    )
    pending_gate = str(state.get("pending_gate") or "")
    pending_checklist_path = str(state.get("pending_checklist_path") or "")
    if pending_gate and pending_checklist_path:
        next_action = {
            "type": "human_gate",
            "text": f"Review pending human gate {pending_gate}.",
            "stop_reason": "required_human_gate",
        }
    merged_refs = list(
        dict.fromkeys(
            [
                *(ref for ref in state.get("source_refs", []) if isinstance(ref, str)),
                *snapshot["source_refs"],
            ]
        )
    )
    return {
        "current_phase": current_phase,
        "active_change": active_change,
        "blocked": len(active_phases) > 1 or len(active_crs) > 1,
        "next_action": next_action,
        "formal_truth_projection": snapshot,
        "source_refs": merged_refs[:24],
    }


__all__ = ["build_formal_truth_snapshot", "derive_formal_truth_patch"]
