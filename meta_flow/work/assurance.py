"""按 G0/G1/G2 生成足够而不过量的评审与验证计划。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from meta_flow.work.model import Work


@dataclass(frozen=True)
class ReviewPlan:
    risk_profile: str
    review_mode: str
    max_independent_reviews: int
    required_evidence: tuple[str, ...]
    decision: str
    missing_evidence: tuple[str, ...]


@dataclass(frozen=True)
class ValidationPlan:
    risk_profile: str
    check_ids: tuple[str, ...]
    risk_mapping: dict[str, str]
    max_check_groups: int
    independent_qa_required: bool
    full_regression_allowed: bool
    decision: str
    errors: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.__dict__,
            "check_ids": list(self.check_ids),
            "risk_mapping": self.risk_mapping.copy(),
            "errors": list(self.errors),
        }


def build_review_plan(
    work: Work,
    *,
    evidence_refs: Mapping[str, str] | None = None,
) -> ReviewPlan:
    evidence = dict(evidence_refs or {})
    if work.risk_profile == "G0":
        return ReviewPlan("G0", "self-check", 0, (), "READY", ())
    if work.risk_profile == "G1":
        return ReviewPlan("G1", "work-scoped-lightweight", 1, (), "READY", ())
    required = ("hld_ref", "adr_ref", "human_design_gate_ref", "independent_reviewer_ref")
    missing = tuple(key for key in required if not evidence.get(key))
    return ReviewPlan(
        "G2",
        "full-architecture-and-independent-review",
        1,
        required,
        "BLOCKED" if missing else "READY",
        missing,
    )


def build_validation_plan(
    work: Work,
    *,
    check_risk_mapping: Mapping[str, str],
    independent_qa_ref: str = "",
) -> ValidationPlan:
    errors: list[str] = []
    mapping = dict(check_risk_mapping)
    declared = work.scope.required_checks
    if set(mapping) != set(declared):
        errors.append("check_risk_mapping must exactly cover required_checks")
    for check_id, risk in mapping.items():
        if not isinstance(risk, str) or not risk.strip():
            errors.append(f"check {check_id} has no concrete risk/acceptance mapping")
    if len(declared) > work.budget.check_groups:
        errors.append("declared checks exceed Work check-group budget")
    if work.risk_profile in {"G0", "G1"} and any(
        marker in check_id.lower() for check_id in declared for marker in ("full-all", "global-all")
    ):
        errors.append("G0/G1 cannot request an unrelated global full check")
    independent = work.risk_profile == "G2"
    if independent and not independent_qa_ref:
        errors.append("G2 requires independent QA evidence")
    return ValidationPlan(
        risk_profile=work.risk_profile,
        check_ids=declared,
        risk_mapping=mapping,
        max_check_groups=work.budget.check_groups,
        independent_qa_required=independent,
        full_regression_allowed=work.risk_profile == "G2",
        decision="BLOCKED" if errors else "READY",
        errors=tuple(errors),
    )
