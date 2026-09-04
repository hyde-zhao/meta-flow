"""有界 Meta Flow 进化包：建议批准、实现授权和发布授权严格分离。"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from meta_flow.execution_control.contract import ExecutionUnitV1
from meta_flow.execution_control.runtime_context import (
    RequestMaterializationCandidateV1,
    target_preimage_digest,
)
from meta_flow.project.model import is_safe_ref
from meta_flow.project.process_route import require_project_process_route
from meta_flow.project.scale import dump_yaml, load_yaml_object
from meta_flow.retrospective import Retrospective, load_retrospective
from meta_flow.work.budget import BudgetLimit
from meta_flow.work.model import Work, build_work, load_work
from meta_flow.work.risk import ClassificationDecision
from meta_flow.work.scope import WorkScope
from meta_flow.work.store import (
    WorkInitReceipt,
    apply_work_init,
    plan_work_init_from_release_root,
)

EVOLUTION_SCHEMA_VERSION = 1
EVOLUTION_RESULT_SCHEMA_VERSION = 1
EVOLUTION_MAX_BYTES = 64 * 1024
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_OID_RE = re.compile(r"^[0-9a-fA-F]{40}([0-9a-fA-F]{24})?$")


@dataclass(frozen=True)
class AcceptanceCriterion:
    criterion_id: str
    metric: str
    operator: str
    threshold: float
    unit: str
    non_regression: bool = False

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class EvolutionPackage:
    evolution_id: str
    project_id: str
    work_id: str
    source_retro_ref: str
    source_candidate_id: str
    facts_confirmation_ref: str
    recommendation_decision_ref: str
    objective: str
    applicability: str
    independent_evidence_sources: tuple[str, ...]
    baseline_oid: str
    risk_profile: str
    scope: WorkScope
    budget: BudgetLimit
    reproduction_steps: tuple[str, ...]
    acceptance_criteria: tuple[AcceptanceCriterion, ...]
    canary_scope: tuple[str, ...]
    rollback_conditions: tuple[str, ...]
    not_authorized: tuple[str, ...]
    reviewer_ref: str
    expires_at: str
    status: str = "approved_not_started"
    implementation_authorized: bool = False
    publication_authorized: bool = False
    recursive_trigger_allowed: bool = False

    @property
    def ref(self) -> str:
        return f"evolution/{self.evolution_id}.yaml"

    @property
    def digest(self) -> str:
        canonical = json.dumps(self.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return sha256(canonical.encode("utf-8")).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": EVOLUTION_SCHEMA_VERSION,
            "evolution_id": self.evolution_id,
            "project_id": self.project_id,
            "work_id": self.work_id,
            "source_retro_ref": self.source_retro_ref,
            "source_candidate_id": self.source_candidate_id,
            "facts_confirmation_ref": self.facts_confirmation_ref,
            "recommendation_decision_ref": self.recommendation_decision_ref,
            "objective": self.objective,
            "applicability": self.applicability,
            "independent_evidence_sources": list(self.independent_evidence_sources),
            "baseline_oid": self.baseline_oid,
            "risk_profile": self.risk_profile,
            "scope": self.scope.as_dict(),
            "budget": self.budget.as_dict(),
            "reproduction_steps": list(self.reproduction_steps),
            "acceptance_criteria": [item.as_dict() for item in self.acceptance_criteria],
            "canary_scope": list(self.canary_scope),
            "rollback_conditions": list(self.rollback_conditions),
            "not_authorized": list(self.not_authorized),
            "reviewer_ref": self.reviewer_ref,
            "expires_at": self.expires_at,
            "status": self.status,
            "authorization_boundaries": {
                "implementation_authorized": self.implementation_authorized,
                "publication_authorized": self.publication_authorized,
                "recursive_trigger_allowed": self.recursive_trigger_allowed,
            },
        }


@dataclass(frozen=True)
class EvolutionStartPlan:
    package: EvolutionPackage
    work: Work
    observed_baseline_oid: str
    decision: str
    reasons: tuple[str, ...]
    plan_digest: str

    @property
    def blocked(self) -> bool:
        return self.decision == "BLOCKED"


@dataclass(frozen=True)
class RecommendationDecision:
    retro_id: str
    candidate_id: str
    decision: str
    rationale: str
    restart_condition: str
    decision_ref: str
    implementation_authorized: bool = False
    publication_authorized: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "decision_type": "evolution_recommendation",
            **self.__dict__,
        }


@dataclass(frozen=True)
class EvolutionStartAuthorization:
    authorization_id: str
    evolution_id: str
    purpose: str
    plan_digest: str
    baseline_oid: str
    expires_at: str
    single_use: bool = True
    publication_authorized: bool = False


@dataclass(frozen=True)
class EvolutionStartReceipt:
    authorization_id: str
    evolution_id: str
    work_id: str
    decision: str
    work_receipt: WorkInitReceipt
    publication_count: int
    recursive_trigger_count: int


@dataclass(frozen=True)
class CriterionResult:
    criterion_id: str
    observed_value: float
    passed: bool
    evidence_ref: str

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class EvolutionResult:
    evolution_id: str
    work_id: str
    reproduction_passed: bool
    criterion_results: tuple[CriterionResult, ...]
    regression_passed: bool
    recovery_passed: bool
    canary_passed: bool
    independent_review_ref: str
    decision: str
    reason: str
    publication_authorized: bool = False
    recursive_triggered: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": EVOLUTION_RESULT_SCHEMA_VERSION,
            **self.__dict__,
            "criterion_results": [item.as_dict() for item in self.criterion_results],
        }


def _validate_id(value: str, label: str) -> None:
    if not _ID_RE.fullmatch(value):
        raise ValueError(f"{label} is invalid")


def _validate_texts(values: tuple[str, ...], label: str, *, required: bool = False) -> None:
    if required and not values:
        raise ValueError(f"{label} must not be empty")
    if len(values) > 50 or not all(
        isinstance(item, str) and item.strip() and len(item) <= 1_000 and "\x00" not in item
        for item in values
    ):
        raise ValueError(f"{label} must contain at most 50 bounded strings")


def _parse_expiry(value: str) -> datetime:
    try:
        expiry = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("expires_at is invalid") from exc
    if expiry.tzinfo is None:
        raise ValueError("expires_at must contain a timezone")
    return expiry.astimezone(UTC)


def validate_evolution_package(package: EvolutionPackage) -> None:
    for label, value in (
        ("evolution_id", package.evolution_id),
        ("project_id", package.project_id),
        ("work_id", package.work_id),
        ("source_candidate_id", package.source_candidate_id),
    ):
        _validate_id(value, label)
    for label, ref in (
        ("source_retro_ref", package.source_retro_ref),
        ("facts_confirmation_ref", package.facts_confirmation_ref),
        ("recommendation_decision_ref", package.recommendation_decision_ref),
        ("reviewer_ref", package.reviewer_ref),
    ):
        if not is_safe_ref(ref):
            raise ValueError(f"{label} must be a safe process-repo-relative ref")
    if package.facts_confirmation_ref == package.recommendation_decision_ref:
        raise ValueError("facts confirmation and recommendation decision must be separate records")
    if not package.objective.strip() or len(package.objective) > 4_000:
        raise ValueError("evolution objective is invalid")
    if package.applicability not in {"project-local", "meta-flow-common"}:
        raise ValueError("evolution applicability is invalid")
    _validate_texts(package.independent_evidence_sources, "independent_evidence_sources", required=True)
    if package.applicability == "meta-flow-common" and len(set(package.independent_evidence_sources)) < 2:
        raise ValueError("a common evolution requires at least two independent evidence sources")
    if not _OID_RE.fullmatch(package.baseline_oid):
        raise ValueError("baseline_oid must be one exact full OID")
    if package.risk_profile not in {"G0", "G1", "G2"}:
        raise ValueError("evolution risk_profile is invalid")
    standard_budget = {
        "G0": BudgetLimit(8, 8, 3, 32_000),
        "G1": BudgetLimit(20, 24, 8, 96_000),
    }
    if package.risk_profile in standard_budget and package.budget != standard_budget[package.risk_profile]:
        raise ValueError(f"{package.risk_profile} evolution budget must use its fixed standard budget")
    request_ref = f"works/{package.work_id}/REQUEST.md"
    if request_ref not in package.scope.allowed_reads:
        raise ValueError("evolution scope must allow reading its generated REQUEST.md")
    _validate_texts(package.reproduction_steps, "reproduction_steps", required=True)
    criterion_ids: set[str] = set()
    if not package.acceptance_criteria:
        raise ValueError("evolution acceptance_criteria must not be empty")
    for item in package.acceptance_criteria:
        _validate_id(item.criterion_id, "criterion_id")
        if item.criterion_id in criterion_ids:
            raise ValueError("acceptance criterion IDs must be unique")
        criterion_ids.add(item.criterion_id)
        if (
            item.operator not in {">=", "<=", "=="}
            or not item.metric.strip()
            or not item.unit.strip()
            or isinstance(item.threshold, bool)
            or not isinstance(item.threshold, int | float)
            or not math.isfinite(float(item.threshold))
            or not isinstance(item.non_regression, bool)
        ):
            raise ValueError("acceptance criterion metric/operator/unit is invalid")
    _validate_texts(package.canary_scope, "canary_scope", required=True)
    _validate_texts(package.rollback_conditions, "rollback_conditions", required=True)
    required_not_authorized = {
        "commit",
        "push",
        "production_write",
        "recursive_evolution",
        "history_rewrite",
    }
    if not required_not_authorized <= set(package.not_authorized):
        raise ValueError("evolution package is missing required not_authorized boundaries")
    if package.status != "approved_not_started":
        raise ValueError("a newly accepted evolution package must remain approved_not_started")
    if (
        package.implementation_authorized is not False
        or package.publication_authorized is not False
        or package.recursive_trigger_allowed is not False
    ):
        raise ValueError("package approval cannot authorize implementation/publication/recursion")
    if len(package.scope.allowed_reads) > package.budget.reads:
        raise ValueError("evolution allowed_reads exceeds its fixed budget")
    if len(package.scope.allowed_writes) > package.budget.writes:
        raise ValueError("evolution allowed_writes exceeds its fixed budget")
    if len(package.scope.required_checks) > package.budget.check_groups:
        raise ValueError("evolution required_checks exceeds its fixed budget")
    _parse_expiry(package.expires_at)


def build_evolution_package(
    *,
    retro: Retrospective,
    candidate_id: str,
    recommendation_decision: str,
    recommendation_decision_ref: str,
    evolution_id: str,
    work_id: str,
    independent_evidence_sources: tuple[str, ...],
    baseline_oid: str,
    risk_profile: str,
    scope: WorkScope,
    budget: BudgetLimit,
    reproduction_steps: tuple[str, ...],
    acceptance_criteria: tuple[AcceptanceCriterion, ...],
    canary_scope: tuple[str, ...],
    rollback_conditions: tuple[str, ...],
    reviewer_ref: str,
    expires_at: str,
) -> EvolutionPackage:
    if retro.status != "facts_confirmed":
        raise ValueError("retrospective facts must be confirmed before recommendation review")
    if recommendation_decision != "accepted":
        raise ValueError("only an accepted recommendation can create an evolution package")
    matches = [item for item in retro.candidates if item.candidate_id == candidate_id]
    if len(matches) != 1:
        raise ValueError("source improvement candidate is missing or ambiguous")
    candidate = matches[0]
    if candidate.applicability == "evidence-insufficient":
        raise ValueError("an evidence-insufficient candidate cannot be accepted")
    package = EvolutionPackage(
        evolution_id=evolution_id,
        project_id=retro.project_id,
        work_id=work_id,
        source_retro_ref=retro.ref,
        source_candidate_id=candidate_id,
        facts_confirmation_ref=retro.facts_confirmation_ref,
        recommendation_decision_ref=recommendation_decision_ref,
        objective=candidate.objective,
        applicability=candidate.applicability,
        independent_evidence_sources=independent_evidence_sources,
        baseline_oid=baseline_oid,
        risk_profile=risk_profile,
        scope=scope,
        budget=budget,
        reproduction_steps=reproduction_steps,
        acceptance_criteria=acceptance_criteria,
        canary_scope=canary_scope,
        rollback_conditions=rollback_conditions,
        not_authorized=(
            "commit",
            "push",
            "production_write",
            "recursive_evolution",
            "history_rewrite",
        ),
        reviewer_ref=reviewer_ref,
        expires_at=expires_at,
    )
    validate_evolution_package(package)
    return package


def evolution_path(process_root: Path, evolution_id: str) -> Path:
    _validate_id(evolution_id, "evolution_id")
    return process_root.resolve() / "evolution" / f"{evolution_id}.yaml"


def build_recommendation_decision(
    process_root: Path,
    *,
    retro_id: str,
    candidate_id: str,
    decision: str,
    rationale: str,
    decision_ref: str,
    restart_condition: str = "",
) -> RecommendationDecision:
    if decision not in {"accepted", "changed", "deferred", "rejected"}:
        raise ValueError("recommendation decision is invalid")
    if not is_safe_ref(decision_ref):
        raise ValueError("recommendation decision_ref is unsafe")
    retro = load_retrospective(process_root, retro_id)
    if retro.status != "facts_confirmed":
        raise ValueError("retrospective facts must be confirmed before recommendation review")
    if len([item for item in retro.candidates if item.candidate_id == candidate_id]) != 1:
        raise ValueError("recommendation candidate is missing or ambiguous")
    if not rationale.strip() or len(rationale) > 4_000:
        raise ValueError("recommendation rationale is invalid")
    if decision == "deferred" and not restart_condition.strip():
        raise ValueError("deferred recommendation requires a restart condition")
    return RecommendationDecision(
        retro_id=retro_id,
        candidate_id=candidate_id,
        decision=decision,
        rationale=rationale,
        restart_condition=restart_condition,
        decision_ref=decision_ref,
    )


def record_recommendation_decision(
    process_root: Path,
    *,
    retro_id: str,
    candidate_id: str,
    decision: str,
    rationale: str,
    decision_ref: str,
    restart_condition: str = "",
) -> RecommendationDecision:
    result = build_recommendation_decision(
        process_root,
        retro_id=retro_id,
        candidate_id=candidate_id,
        decision=decision,
        rationale=rationale,
        decision_ref=decision_ref,
        restart_condition=restart_condition,
    )
    path = process_root.resolve() / decision_ref
    if path.exists() or path.is_symlink():
        raise FileExistsError("recommendation decision record already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_yaml(result.as_dict()) + "\n", encoding="utf-8")
    return result


def load_recommendation_decision(
    process_root: Path,
    decision_ref: str,
) -> RecommendationDecision:
    if not is_safe_ref(decision_ref):
        raise ValueError("recommendation decision_ref is unsafe")
    payload = load_yaml_object(process_root.resolve() / decision_ref)
    allowed = {
        "schema_version",
        "decision_type",
        "retro_id",
        "candidate_id",
        "decision",
        "rationale",
        "restart_condition",
        "decision_ref",
        "implementation_authorized",
        "publication_authorized",
    }
    if (
        set(payload) != allowed
        or payload.get("schema_version") != 1
        or payload.get("decision_type") != "evolution_recommendation"
        or payload.get("decision_ref") != decision_ref
    ):
        raise ValueError("recommendation decision schema/ref is invalid")
    result = RecommendationDecision(
        retro_id=str(payload.get("retro_id") or ""),
        candidate_id=str(payload.get("candidate_id") or ""),
        decision=str(payload.get("decision") or ""),
        rationale=str(payload.get("rationale") or ""),
        restart_condition=str(payload.get("restart_condition") or ""),
        decision_ref=decision_ref,
        implementation_authorized=payload.get("implementation_authorized"),
        publication_authorized=payload.get("publication_authorized"),
    )
    if result.decision not in {"accepted", "changed", "deferred", "rejected"}:
        raise ValueError("recommendation decision value is invalid")
    if not result.rationale.strip() or len(result.rationale) > 4_000:
        raise ValueError("recommendation rationale is invalid")
    if result.decision == "deferred" and not result.restart_condition.strip():
        raise ValueError("deferred recommendation requires a restart condition")
    if result.implementation_authorized is not False or result.publication_authorized is not False:
        raise ValueError("recommendation decision cannot authorize implementation/publication")
    return result


def validate_evolution_provenance(process_root: Path, package: EvolutionPackage) -> None:
    source_parts = Path(package.source_retro_ref).parts
    if len(source_parts) != 2 or source_parts[0] != "retrospectives" or not source_parts[1].endswith(".yaml"):
        raise ValueError("source_retro_ref must use retrospectives/<retro-id>.yaml")
    retro_id = Path(source_parts[1]).stem
    retro = load_retrospective(process_root, retro_id)
    if (
        retro.ref != package.source_retro_ref
        or retro.project_id != package.project_id
        or retro.status != "facts_confirmed"
        or retro.facts_confirmation_ref != package.facts_confirmation_ref
    ):
        raise ValueError("evolution package retrospective provenance mismatch")
    facts_path = process_root.resolve() / package.facts_confirmation_ref
    if not facts_path.is_file():
        raise ValueError("retrospective facts confirmation evidence is missing")
    facts = load_yaml_object(facts_path)
    facts_fields = {
        "schema_version",
        "decision_type",
        "retro_id",
        "decision",
        "implementation_authorized",
        "publication_authorized",
    }
    if (
        set(facts) != facts_fields
        or facts.get("schema_version") != 1
        or facts.get("decision_type") != "retrospective_facts_confirmation"
        or facts.get("retro_id") != retro.retro_id
        or facts.get("decision") != "confirmed"
        or facts.get("implementation_authorized") is not False
        or facts.get("publication_authorized") is not False
    ):
        raise ValueError("retrospective facts confirmation evidence is invalid")
    candidates = [item for item in retro.candidates if item.candidate_id == package.source_candidate_id]
    if len(candidates) != 1:
        raise ValueError("evolution package candidate provenance mismatch")
    candidate = candidates[0]
    if candidate.objective != package.objective or candidate.applicability != package.applicability:
        raise ValueError("evolution package changed the approved candidate identity")
    decision = load_recommendation_decision(process_root, package.recommendation_decision_ref)
    if (
        decision.retro_id != retro.retro_id
        or decision.candidate_id != package.source_candidate_id
        or decision.decision != "accepted"
    ):
        raise ValueError("evolution package requires one matching accepted recommendation decision")


def write_evolution_package_create_only(process_root: Path, package: EvolutionPackage) -> Path:
    validate_evolution_package(package)
    validate_evolution_provenance(process_root, package)
    path = evolution_path(process_root, package.evolution_id)
    if path.exists() or path.is_symlink():
        raise FileExistsError("evolution package already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_yaml(package.as_dict()) + "\n", encoding="utf-8")
    return path


def evolution_from_payload(payload: dict[str, Any]) -> EvolutionPackage:
    allowed = {
        "schema_version",
        "evolution_id",
        "project_id",
        "work_id",
        "source_retro_ref",
        "source_candidate_id",
        "facts_confirmation_ref",
        "recommendation_decision_ref",
        "objective",
        "applicability",
        "independent_evidence_sources",
        "baseline_oid",
        "risk_profile",
        "scope",
        "budget",
        "reproduction_steps",
        "acceptance_criteria",
        "canary_scope",
        "rollback_conditions",
        "not_authorized",
        "reviewer_ref",
        "expires_at",
        "status",
        "authorization_boundaries",
    }
    if set(payload) != allowed or payload.get("schema_version") != EVOLUTION_SCHEMA_VERSION:
        raise ValueError("evolution package schema contains missing or unknown fields")
    scope_payload = payload.get("scope")
    budget_payload = payload.get("budget")
    criteria_payload = payload.get("acceptance_criteria")
    boundaries = payload.get("authorization_boundaries")
    if not isinstance(scope_payload, dict) or not isinstance(budget_payload, dict):
        raise ValueError("evolution scope/budget must be objects")
    scope_fields = {"version", "allowed_reads", "allowed_writes", "required_checks"}
    budget_fields = {"reads", "writes", "check_groups", "tokens"}
    if set(scope_payload) != scope_fields or set(budget_payload) != budget_fields:
        raise ValueError("evolution scope/budget schema contains missing or unknown fields")
    for scope_field in ("allowed_reads", "allowed_writes", "required_checks"):
        value = scope_payload.get(scope_field)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"evolution scope.{scope_field} must be a list of strings")
    if type(scope_payload.get("version")) is not int:
        raise ValueError("evolution scope.version must be an integer")
    if not all(type(budget_payload.get(field)) is int for field in budget_fields):
        raise ValueError("evolution budget values must be integers")
    if not isinstance(criteria_payload, list) or not all(isinstance(item, dict) for item in criteria_payload):
        raise ValueError("evolution acceptance_criteria must be a list of objects")
    boundary_fields = {
        "implementation_authorized",
        "publication_authorized",
        "recursive_trigger_allowed",
    }
    criterion_fields = {
        "criterion_id",
        "metric",
        "operator",
        "threshold",
        "unit",
        "non_regression",
    }
    if not isinstance(boundaries, dict) or set(boundaries) != boundary_fields:
        raise ValueError("evolution authorization_boundaries schema is invalid")
    if any(set(item) != criterion_fields for item in criteria_payload):
        raise ValueError("evolution acceptance criterion schema contains missing or unknown fields")
    for list_field in (
        "independent_evidence_sources",
        "reproduction_steps",
        "canary_scope",
        "rollback_conditions",
        "not_authorized",
    ):
        value = payload.get(list_field)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"evolution {list_field} must be a list of strings")
    package = EvolutionPackage(
        evolution_id=str(payload.get("evolution_id") or ""),
        project_id=str(payload.get("project_id") or ""),
        work_id=str(payload.get("work_id") or ""),
        source_retro_ref=str(payload.get("source_retro_ref") or ""),
        source_candidate_id=str(payload.get("source_candidate_id") or ""),
        facts_confirmation_ref=str(payload.get("facts_confirmation_ref") or ""),
        recommendation_decision_ref=str(payload.get("recommendation_decision_ref") or ""),
        objective=str(payload.get("objective") or ""),
        applicability=str(payload.get("applicability") or ""),
        independent_evidence_sources=tuple(str(item) for item in payload.get("independent_evidence_sources") or ()),
        baseline_oid=str(payload.get("baseline_oid") or ""),
        risk_profile=str(payload.get("risk_profile") or ""),
        scope=WorkScope(
            version=scope_payload.get("version"),
            allowed_reads=tuple(scope_payload.get("allowed_reads") or ()),
            allowed_writes=tuple(scope_payload.get("allowed_writes") or ()),
            required_checks=tuple(scope_payload.get("required_checks") or ()),
        ),
        budget=BudgetLimit(**budget_payload),
        reproduction_steps=tuple(str(item) for item in payload.get("reproduction_steps") or ()),
        acceptance_criteria=tuple(
            AcceptanceCriterion(
                criterion_id=str(item.get("criterion_id") or ""),
                metric=str(item.get("metric") or ""),
                operator=str(item.get("operator") or ""),
                threshold=float(item.get("threshold")),
                unit=str(item.get("unit") or ""),
                non_regression=item.get("non_regression", False),
            )
            for item in criteria_payload
        ),
        canary_scope=tuple(str(item) for item in payload.get("canary_scope") or ()),
        rollback_conditions=tuple(str(item) for item in payload.get("rollback_conditions") or ()),
        not_authorized=tuple(str(item) for item in payload.get("not_authorized") or ()),
        reviewer_ref=str(payload.get("reviewer_ref") or ""),
        expires_at=str(payload.get("expires_at") or ""),
        status=str(payload.get("status") or ""),
        implementation_authorized=boundaries.get("implementation_authorized"),
        publication_authorized=boundaries.get("publication_authorized"),
        recursive_trigger_allowed=boundaries.get("recursive_trigger_allowed"),
    )
    validate_evolution_package(package)
    return package


def load_evolution_package(process_root: Path, evolution_id: str) -> EvolutionPackage:
    path = evolution_path(process_root, evolution_id)
    if path.stat().st_size > EVOLUTION_MAX_BYTES:
        raise ValueError("evolution package exceeds byte budget")
    return evolution_from_payload(load_yaml_object(path))


def build_evolution_start_plan(
    package: EvolutionPackage,
    *,
    observed_baseline_oid: str,
) -> EvolutionStartPlan:
    validate_evolution_package(package)
    reasons: list[str] = []
    if observed_baseline_oid != package.baseline_oid:
        reasons.append("baseline_oid_mismatch")
    if _parse_expiry(package.expires_at) <= datetime.now(UTC):
        reasons.append("package_expired")
    classification = ClassificationDecision(
        container_kind="cr" if package.risk_profile == "G2" else "work",
        risk_profile=package.risk_profile,
        reason_codes=("APPROVED_EVOLUTION_PACKAGE",),
        budget=package.budget,
        required_gates=("GATE-SCOPE", "GATE-DESIGN") if package.risk_profile == "G2" else (),
        blocked=False,
        # EvolutionPackageV1 的 G2 保持历史完整设计语义。
        risk_profile_schema_version=1,
    )
    work = build_work(
        work_id=package.work_id,
        project_id=package.project_id,
        objective=package.objective,
        request_ref=f"works/{package.work_id}/REQUEST.md",
        scope=package.scope,
        classification=classification,
        release_base_oid=package.baseline_oid,
        process_base_oid="",
        execution_unit=ExecutionUnitV1(
            unit_id=package.work_id,
            root_concept="meta-flow-evolution",
            slice_id=package.evolution_id,
            container_role="primary",
            revision=1,
            supersedes_unit_id="",
            contract_ref=package.ref,
            contract_digest=package.digest,
        ),
    )
    source = {
        "schema_version": 1,
        "package_digest": package.digest,
        "observed_baseline_oid": observed_baseline_oid,
        "work": work.as_dict(),
        "decision": "BLOCKED" if reasons else "READY",
        "reasons": reasons,
    }
    plan_digest = sha256(
        json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return EvolutionStartPlan(
        package=package,
        work=work,
        observed_baseline_oid=observed_baseline_oid,
        decision="BLOCKED" if reasons else "READY",
        reasons=tuple(reasons),
        plan_digest=plan_digest,
    )


def _validate_start_authorization(
    plan: EvolutionStartPlan,
    authorization: EvolutionStartAuthorization,
) -> None:
    _validate_id(authorization.authorization_id, "authorization_id")
    if (
        authorization.single_use is not True
        or authorization.publication_authorized is not False
        or authorization.purpose != "implementation_start"
        or authorization.evolution_id != plan.package.evolution_id
        or authorization.plan_digest != plan.plan_digest
        or authorization.baseline_oid != plan.package.baseline_oid
    ):
        raise ValueError("implementation authorization does not match the evolution start plan")
    if _parse_expiry(authorization.expires_at) <= datetime.now(UTC):
        raise ValueError("implementation authorization is expired")


def _render_evolution_request(package: EvolutionPackage) -> bytes:
    return (
        "# 已批准的 Meta Flow 进化 Work\n\n"
        f"来源进化包：`{package.ref}`\n\n"
        f"目标：{package.objective}\n\n"
        "本次只授权创建正常 Work；不授权 commit、push、production 写入或递归自进化。\n"
    ).encode()


def materialize_evolution_work(
    release_root: Path,
    plan: EvolutionStartPlan,
    authorization: EvolutionStartAuthorization,
) -> EvolutionStartReceipt:
    if plan.blocked:
        raise ValueError("evolution start plan is blocked")
    _validate_start_authorization(plan, authorization)
    route = require_project_process_route(
        release_root.resolve(), project_id=plan.package.project_id
    )
    process_root = route.process_root
    persisted = load_evolution_package(process_root, plan.package.evolution_id)
    if persisted.digest != plan.package.digest:
        raise ValueError("evolution package changed after planning")
    fresh = build_evolution_start_plan(
        persisted,
        observed_baseline_oid=plan.observed_baseline_oid,
    )
    if fresh.plan_digest != plan.plan_digest:
        raise ValueError("evolution start plan is stale")
    _validate_start_authorization(fresh, authorization)
    request_path = process_root / fresh.work.request_ref
    candidate = RequestMaterializationCandidateV1.build(
        request_ref=fresh.work.request_ref,
        content_bytes=_render_evolution_request(persisted),
        source_kind="evolution-package-v1",
        source_ref=persisted.ref,
        source_digest=persisted.digest,
        before_preimage_digest=target_preimage_digest(request_path),
    )
    work_plan = plan_work_init_from_release_root(
        release_root,
        fresh.work,
        request_candidate=candidate,
    )
    if work_plan.execution_context is None:
        raise ValueError("evolution Work execution context is unavailable")
    if work_plan.execution_context.release_oid != persisted.baseline_oid:
        raise ValueError("evolution package baseline differs from canonical release OID")
    _validate_start_authorization(fresh, authorization)
    work_receipt = apply_work_init(work_plan)
    return EvolutionStartReceipt(
        authorization_id=authorization.authorization_id,
        evolution_id=plan.package.evolution_id,
        work_id=plan.work.work_id,
        decision="PASS",
        work_receipt=work_receipt,
        publication_count=0,
        recursive_trigger_count=0,
    )


def evaluate_evolution_result(
    package: EvolutionPackage,
    *,
    reproduction_passed: bool,
    criterion_results: tuple[CriterionResult, ...],
    regression_passed: bool,
    recovery_passed: bool,
    canary_passed: bool,
    independent_review_ref: str = "",
) -> EvolutionResult:
    for label, value in (
        ("reproduction_passed", reproduction_passed),
        ("regression_passed", regression_passed),
        ("recovery_passed", recovery_passed),
        ("canary_passed", canary_passed),
    ):
        if not isinstance(value, bool):
            raise ValueError(f"{label} must be a boolean")
    expected = {item.criterion_id for item in package.acceptance_criteria}
    actual = {item.criterion_id for item in criterion_results}
    if actual != expected or len(actual) != len(criterion_results):
        raise ValueError("criterion results must exactly cover package acceptance criteria")
    criteria_by_id = {item.criterion_id: item for item in package.acceptance_criteria}
    for item in criterion_results:
        if not is_safe_ref(item.evidence_ref):
            raise ValueError("criterion result evidence_ref is unsafe")
        if isinstance(item.observed_value, bool) or not isinstance(
            item.observed_value, int | float
        ) or not math.isfinite(
            float(item.observed_value)
        ):
            raise ValueError("criterion observed_value must be a finite number")
        criterion = criteria_by_id[item.criterion_id]
        observed = float(item.observed_value)
        expected_pass = {
            ">=": observed >= criterion.threshold,
            "<=": observed <= criterion.threshold,
            "==": observed == criterion.threshold,
        }[criterion.operator]
        if not isinstance(item.passed, bool) or item.passed != expected_pass:
            raise ValueError("criterion passed flag does not match its approved operator/threshold")
    if package.risk_profile == "G2" and not is_safe_ref(independent_review_ref):
        raise ValueError("G2 evolution result requires independent review evidence")
    all_passed = (
        reproduction_passed
        and all(item.passed for item in criterion_results)
        and regression_passed
        and recovery_passed
        and canary_passed
    )
    return EvolutionResult(
        evolution_id=package.evolution_id,
        work_id=package.work_id,
        reproduction_passed=reproduction_passed,
        criterion_results=criterion_results,
        regression_passed=regression_passed,
        recovery_passed=recovery_passed,
        canary_passed=canary_passed,
        independent_review_ref=independent_review_ref,
        decision="PROMOTE_CANDIDATE" if all_passed else "STOP_OR_ROLLBACK",
        reason="all approved criteria passed" if all_passed else "one or more reproduction/acceptance/non-regression/canary checks failed",
        publication_authorized=False,
        recursive_triggered=False,
    )


def write_evolution_result_create_only(process_root: Path, result: EvolutionResult) -> Path:
    if result.publication_authorized is not False or result.recursive_triggered is not False:
        raise ValueError("evolution result cannot authorize publication or recursively trigger evolution")
    package = load_evolution_package(process_root, result.evolution_id)
    validate_evolution_provenance(process_root, package)
    work = load_work(process_root, result.work_id)
    unit = work.execution_unit
    if (
        work.work_id != package.work_id
        or work.project_id != package.project_id
        or work.kind not in {"work", "cr"}
        or unit is None
        or unit.unit_id != package.work_id
        or unit.root_concept != "meta-flow-evolution"
        or unit.slice_id != package.evolution_id
        or unit.contract_ref != package.ref
        or unit.contract_digest != package.digest
        or work.status not in {"ready_for_verification", "completed"}
    ):
        raise ValueError("evolution result requires its matching verified normal Work")
    path = process_root.resolve() / "evolution" / f"{result.evolution_id}.result.yaml"
    if path.exists() or path.is_symlink():
        raise FileExistsError("evolution result already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_yaml(result.as_dict()) + "\n", encoding="utf-8")
    return path


def load_confirmed_retrospective_for_evolution(
    process_root: Path,
    retro_id: str,
) -> Retrospective:
    retro = load_retrospective(process_root, retro_id)
    if retro.status != "facts_confirmed":
        raise ValueError("retrospective facts are not confirmed")
    return retro
