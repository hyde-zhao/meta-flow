"""只读 Work preflight adapter；所有路径都在 mutation 前完成模拟。"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from meta_flow.work.validation_kernel import (
    AdmissionDecisionV2,
    AdmissionValidatorV2,
    NormalizedDecisionGraphV1,
    ValidationDecisionV1,
    build_admission_decision_v2,
    capture_validation_snapshot,
    decision_from_graph,
    evaluate_work,
)


class LifecyclePathV1(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    NO_OP = "no_op"


class ScopeAccessV1(StrEnum):
    READ = "read"
    WRITE = "write"


class DemandOwnerClassV1(StrEnum):
    BUSINESS = "business"
    SYSTEM = "system"


_WORK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_SECRET_MARKERS = ("password=", "passwd=", "secret=", "token=", "api_key=")
_SYSTEM_KINDS = (
    "blocker",
    "failure-evidence",
    "handoff",
    "project-projection",
    "transaction",
    "usage",
    "validation-receipt",
    "work-envelope",
)


def _safe_logical_ref(value: object) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError("PREFLIGHT_REF_UNSAFE")
    lowered = value.lower()
    if (
        value.startswith("/")
        or "\\" in value
        or "://" in value
        or "@" in value
        or any(marker in lowered for marker in _SECRET_MARKERS)
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise ValueError("PREFLIGHT_REF_UNSAFE")
    return value


def _canonical_refs(values: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(values, (tuple, list)):
        raise ValueError(f"{field} must be a list or tuple")
    refs = tuple(_safe_logical_ref(value) for value in values)
    if tuple(sorted(set(refs))) != refs:
        raise ValueError(f"{field} must be sorted and unique")
    return refs


@dataclass(frozen=True)
class ScopeDemandV1:
    logical_ref: str
    access: ScopeAccessV1
    owner_class: DemandOwnerClassV1
    reason: str
    object_kind: str

    def __post_init__(self) -> None:
        _safe_logical_ref(self.logical_ref)
        if not self.reason or not self.object_kind:
            raise ValueError("scope demand reason and object_kind are required")

    def as_digest_input(self) -> dict[str, str]:
        return {
            "logical_ref": self.logical_ref,
            "access": self.access.value,
            "owner_class": self.owner_class.value,
            "reason": self.reason,
            "object_kind": self.object_kind,
        }


@dataclass(frozen=True)
class LifecycleSimulationV1:
    path: LifecyclePathV1
    demands: tuple[ScopeDemandV1, ...]
    terminal_disposition: str
    conflicts: tuple[str, ...] = ()

    @property
    def business_scope_demands(self) -> tuple[ScopeDemandV1, ...]:
        return tuple(d for d in self.demands if d.owner_class is DemandOwnerClassV1.BUSINESS)

    @property
    def system_owned_demands(self) -> tuple[ScopeDemandV1, ...]:
        return tuple(d for d in self.demands if d.owner_class is DemandOwnerClassV1.SYSTEM)

    def as_digest_input(self) -> dict[str, object]:
        return {
            "path": self.path.value,
            "terminal_disposition": self.terminal_disposition,
            "demands": [d.as_digest_input() for d in self.demands],
            "conflicts": list(self.conflicts),
        }


@dataclass(frozen=True)
class WorkLifecycleCandidateV1:
    work_id: str
    business_reads: tuple[str, ...] = ()
    business_writes: tuple[str, ...] = ()
    candidate_digest: str = ""
    existing_digest: str = ""

    def __post_init__(self) -> None:
        if not _WORK_ID_RE.fullmatch(self.work_id):
            raise ValueError("PREFLIGHT_WORK_ID_INVALID")
        _canonical_refs(self.business_reads, field="business_reads")
        _canonical_refs(self.business_writes, field="business_writes")
        for value in (self.candidate_digest, self.existing_digest):
            if value and not _DIGEST_RE.fullmatch(value):
                raise ValueError("PREFLIGHT_DIGEST_INVALID")


@dataclass(frozen=True)
class WorkLifecycleContextV1:
    granted_business_reads: tuple[str, ...] = ()
    granted_business_writes: tuple[str, ...] = ()
    supported_system_kinds: tuple[str, ...] = _SYSTEM_KINDS

    def __post_init__(self) -> None:
        _canonical_refs(self.granted_business_reads, field="granted_business_reads")
        _canonical_refs(self.granted_business_writes, field="granted_business_writes")
        if tuple(sorted(set(self.supported_system_kinds))) != self.supported_system_kinds:
            raise ValueError("supported_system_kinds must be sorted and unique")
        if any(kind not in _SYSTEM_KINDS for kind in self.supported_system_kinds):
            raise ValueError("PREFLIGHT_SYSTEM_KIND_UNKNOWN")


@dataclass(frozen=True)
class PreflightReportV2:
    decision: AdmissionDecisionV2
    simulations: tuple[LifecycleSimulationV1, ...]
    mutation_count: int = 0


@dataclass(frozen=True)
class PreflightReportV1:
    decision: ValidationDecisionV1
    graph: NormalizedDecisionGraphV1
    mutation_count: int = 0


def run_preflight(context: dict[str, object]) -> PreflightReportV1:
    snapshot = capture_validation_snapshot("init-preflight", context)
    graph = evaluate_work(snapshot)
    return PreflightReportV1(decision_from_graph(graph), graph, mutation_count=0)


def render_preflight(report: PreflightReportV1) -> dict[str, object]:
    return {"decision": report.decision.decision.value, "graph_digest": report.graph.graph_digest, "mutation_count": 0, "codes": [item.code for item in report.graph.items]}


def _coerce_candidate(candidate: WorkLifecycleCandidateV1 | Mapping[str, object]) -> WorkLifecycleCandidateV1:
    if isinstance(candidate, WorkLifecycleCandidateV1):
        return candidate
    allowed = {"work_id", "business_reads", "business_writes", "candidate_digest", "existing_digest"}
    if set(candidate) - allowed or "work_id" not in candidate:
        raise ValueError("PREFLIGHT_CANDIDATE_FIELDS_INVALID")
    return WorkLifecycleCandidateV1(
        work_id=str(candidate["work_id"]),
        business_reads=_canonical_refs(candidate.get("business_reads", ()), field="business_reads"),
        business_writes=_canonical_refs(candidate.get("business_writes", ()), field="business_writes"),
        candidate_digest=str(candidate.get("candidate_digest") or ""),
        existing_digest=str(candidate.get("existing_digest") or ""),
    )


def _coerce_context(context: WorkLifecycleContextV1 | Mapping[str, object]) -> WorkLifecycleContextV1:
    if isinstance(context, WorkLifecycleContextV1):
        return context
    allowed = {"granted_business_reads", "granted_business_writes", "supported_system_kinds"}
    if set(context) - allowed:
        raise ValueError("PREFLIGHT_CONTEXT_FIELDS_INVALID")
    return WorkLifecycleContextV1(
        granted_business_reads=_canonical_refs(
            context.get("granted_business_reads", ()), field="granted_business_reads"
        ),
        granted_business_writes=_canonical_refs(
            context.get("granted_business_writes", ()), field="granted_business_writes"
        ),
        supported_system_kinds=tuple(context.get("supported_system_kinds", _SYSTEM_KINDS)),
    )


def _demand(
    logical_ref: str,
    access: ScopeAccessV1,
    owner_class: DemandOwnerClassV1,
    reason: str,
    object_kind: str,
) -> ScopeDemandV1:
    return ScopeDemandV1(logical_ref, access, owner_class, reason, object_kind)


def _system_demands(work_id: str, path: LifecyclePathV1) -> tuple[ScopeDemandV1, ...]:
    root = f"process/works/{work_id}"
    common_reads = (
        _demand(f"{root}/WORK.yaml", ScopeAccessV1.READ, DemandOwnerClassV1.SYSTEM, "work_preimage", "work-envelope"),
        _demand("process/PROJECT.yaml", ScopeAccessV1.READ, DemandOwnerClassV1.SYSTEM, "project_preimage", "project-projection"),
    )
    if path is LifecyclePathV1.NO_OP:
        return common_reads
    common_writes = (
        _demand(f"{root}/WORK.yaml", ScopeAccessV1.WRITE, DemandOwnerClassV1.SYSTEM, "materialize_work", "work-envelope"),
        _demand("process/PROJECT.yaml", ScopeAccessV1.WRITE, DemandOwnerClassV1.SYSTEM, "project_work_projection", "project-projection"),
        _demand(
            f"process/.meta-flow-runtime/work-init/transactions/{work_id}/manifest.json",
            ScopeAccessV1.WRITE,
            DemandOwnerClassV1.SYSTEM,
            "transaction_manifest",
            "transaction",
        ),
    )
    if path is LifecyclePathV1.SUCCESS:
        return common_reads + common_writes + (
            _demand(f"{root}/USAGE.json", ScopeAccessV1.WRITE, DemandOwnerClassV1.SYSTEM, "usage_baseline", "usage"),
            _demand(f"{root}/evidence/validation/preflight.receipt.json", ScopeAccessV1.WRITE, DemandOwnerClassV1.SYSTEM, "preflight_receipt", "validation-receipt"),
        )
    return common_reads + common_writes + (
        _demand(f"{root}/FAILURE-EVIDENCE.json", ScopeAccessV1.WRITE, DemandOwnerClassV1.SYSTEM, "failure_observation", "failure-evidence"),
        _demand(f"{root}/BLOCKER.json", ScopeAccessV1.WRITE, DemandOwnerClassV1.SYSTEM, "blocked_projection", "blocker"),
        _demand(f"{root}/HANDOFF.yaml", ScopeAccessV1.WRITE, DemandOwnerClassV1.SYSTEM, "recovery_handoff", "handoff"),
    )


def simulate_work_lifecycle(
    candidate: WorkLifecycleCandidateV1 | Mapping[str, object],
    context: WorkLifecycleContextV1 | Mapping[str, object],
) -> tuple[LifecycleSimulationV1, ...]:
    """纯模型模拟 success/failure/no-op；不读取或写入 filesystem。"""

    normalized_candidate = _coerce_candidate(candidate)
    normalized_context = _coerce_context(context)
    no_change = bool(
        normalized_candidate.candidate_digest
        and normalized_candidate.candidate_digest == normalized_candidate.existing_digest
    )
    simulations: list[LifecycleSimulationV1] = []
    for path in LifecyclePathV1:
        business_demands = tuple(
            _demand(ref, ScopeAccessV1.READ, DemandOwnerClassV1.BUSINESS, "candidate_business_read", "business-ref")
            for ref in normalized_candidate.business_reads
        )
        if path is LifecyclePathV1.SUCCESS and not no_change:
            business_demands += tuple(
                _demand(ref, ScopeAccessV1.WRITE, DemandOwnerClassV1.BUSINESS, "candidate_business_write", "business-ref")
                for ref in normalized_candidate.business_writes
            )
        system_demands = _system_demands(normalized_candidate.work_id, path)
        conflicts: list[str] = []
        missing_reads = sorted(
            set(normalized_candidate.business_reads) - set(normalized_context.granted_business_reads)
        )
        missing_writes = sorted(
            set(normalized_candidate.business_writes) - set(normalized_context.granted_business_writes)
        ) if path is LifecyclePathV1.SUCCESS and not no_change else []
        conflicts.extend(f"BUSINESS_READ_SCOPE_MISSING:{ref}" for ref in missing_reads)
        conflicts.extend(f"BUSINESS_WRITE_SCOPE_MISSING:{ref}" for ref in missing_writes)
        missing_kinds = sorted(
            {d.object_kind for d in system_demands}
            - set(normalized_context.supported_system_kinds)
        )
        conflicts.extend(f"SYSTEM_DEMAND_UNAVAILABLE:{kind}" for kind in missing_kinds)
        terminal = (
            "NO_CHANGE"
            if path is LifecyclePathV1.NO_OP and no_change
            else "NOT_APPLICABLE"
            if no_change
            else "READY"
            if path is LifecyclePathV1.SUCCESS
            else "RECOVERABLE_BLOCK"
            if path is LifecyclePathV1.FAILURE
            else "NOT_APPLICABLE"
        )
        simulations.append(
            LifecycleSimulationV1(
                path=path,
                demands=tuple(
                    sorted(
                        business_demands + system_demands,
                        key=lambda demand: (
                            demand.owner_class.value,
                            demand.logical_ref,
                            demand.access.value,
                            demand.object_kind,
                        ),
                    )
                ),
                terminal_disposition=terminal,
                conflicts=tuple(sorted(set(conflicts))),
            )
        )
    return tuple(sorted(simulations, key=lambda simulation: simulation.path.value))


def run_lifecycle_preflight(
    candidate: WorkLifecycleCandidateV1 | Mapping[str, object],
    context: WorkLifecycleContextV1 | Mapping[str, object],
    validators: Iterable[tuple[str, AdmissionValidatorV2]] = (),
) -> PreflightReportV2:
    simulations = simulate_work_lifecycle(candidate, context)
    decision = build_admission_decision_v2(simulations, validators)
    return PreflightReportV2(decision=decision, simulations=simulations, mutation_count=0)


def render_preflight_result(report: PreflightReportV2) -> dict[str, object]:
    """渲染稳定公共 JSON；只包含 logical ref 与 bounded diagnostics。"""

    return {
        "schema_version": 2,
        "kind": "AdmissionDecisionV2",
        "decision": report.decision.decision.value,
        "graph_digest": report.decision.graph_digest,
        "lifecycle_digest": report.decision.lifecycle_digest,
        "authoritative_decision_path_count": report.decision.authoritative_decision_path_count,
        "duplicate_rule_owner_count": report.decision.duplicate_rule_owner_count,
        "mutation_count": 0,
        "items": [
            {
                "owner": item.owner,
                "code": item.code,
                "decision": item.decision.value,
                "detail": item.detail,
            }
            for item in report.decision.items
        ],
        "simulations": [
            {
                "path": simulation.path.value,
                "terminal_disposition": simulation.terminal_disposition,
                "business_scope_demands": [
                    demand.as_digest_input() for demand in simulation.business_scope_demands
                ],
                "system_owned_demands": [
                    demand.as_digest_input() for demand in simulation.system_owned_demands
                ],
                "conflicts": list(simulation.conflicts),
            }
            for simulation in report.simulations
        ],
    }
