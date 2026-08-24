"""按 G0/G1/G2 生成足够而不过量的评审与验证计划。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from meta_flow.execution_control.migration import current_execution_control_policy
from meta_flow.work.model import ValidationReuseDecisionV2, Work
from meta_flow.work.validation_fingerprint import VALIDATION_LAYERS
from meta_flow.work.validation_planner import ValidationExecutionPlan


@dataclass(frozen=True)
class ReviewPlan:
    risk_profile: str
    review_mode: str
    max_independent_reviews: int
    required_evidence: tuple[str, ...]
    decision: str
    missing_evidence: tuple[str, ...]
    route_mode: str
    dispatch_mode: str
    stages: tuple[str, ...]
    execution_control_mode: str = "enforce-new"
    provider_receipt_status: str = "MISSING"
    provider_readiness: str = "UNAVAILABLE_PENDING_CP7_CP8"
    invalidated_layers: tuple[str, ...] = ("provider-qualified-readiness",)


@dataclass(frozen=True)
class ValidationPlan:
    risk_profile: str
    check_ids: tuple[str, ...]
    risk_mapping: dict[str, str]
    max_check_groups: int
    independent_qa_required: bool
    validation_scope_required: bool
    decision: str
    errors: tuple[str, ...]
    route_mode: str
    dispatch_mode: str
    stages: tuple[str, ...]
    layer_decisions: dict[str, str]
    next_layer: str
    execution_control_mode: str = "enforce-new"
    provider_receipt_status: str = "MISSING"
    provider_readiness: str = "UNAVAILABLE_PENDING_CP7_CP8"
    invalidated_layers: tuple[str, ...] = ("provider-qualified-readiness",)

    @property
    def full_regression_allowed(self) -> bool:
        """MF-BUG-07：旧名读兼容（一个版本周期后删除）。"""

        import warnings

        warnings.warn(
            "full_regression_allowed is deprecated; use validation_scope_required",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.validation_scope_required

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.__dict__,
            # 双名并存一个版本周期：旧消费方继续可读。
            "full_regression_allowed": self.validation_scope_required,
            "check_ids": list(self.check_ids),
            "risk_mapping": self.risk_mapping.copy(),
            "errors": list(self.errors),
            "stages": list(self.stages),
            "layer_decisions": self.layer_decisions.copy(),
            "invalidated_layers": list(self.invalidated_layers),
        }


def render_validation_provider_decision(
    decision: ValidationReuseDecisionV2,
) -> dict[str, object]:
    """只呈现 provider 的 typed decision，不在 assurance 复制复用规则。"""

    return {
        "decision": decision.decision,
        "reason_codes": list(decision.reason_codes),
        "provider_identity_digest": decision.provider_identity_digest,
    }


def _with_execution_control_assurance(plan: ReviewPlan | ValidationPlan):
    policy = current_execution_control_policy()
    return replace(
        plan,
        execution_control_mode=policy.effective_writer_mode,
        provider_receipt_status=policy.candidate_receipt_status,
        provider_readiness="UNAVAILABLE_PENDING_CP7_CP8",
        invalidated_layers=("provider-qualified-readiness",),
    )


def build_review_plan(
    work: Work,
    *,
    evidence_refs: Mapping[str, str] | None = None,
) -> ReviewPlan:
    evidence = dict(evidence_refs or {})
    profile = work.route_profile
    stages = (
        tuple(f"CP{index}" for index in range(9))
        if profile.legacy_cp_compatibility
        else ("clarification", "design", "implementation", "verification")
    )
    if work.risk_profile == "G0":
        return _with_execution_control_assurance(ReviewPlan(
            "G0",
            "self-check",
            0,
            (),
            "READY",
            (),
            profile.mode,
            profile.dispatch_mode,
            stages,
        ))
    if work.risk_profile == "G1":
        return _with_execution_control_assurance(ReviewPlan(
            "G1",
            "work-scoped-lightweight",
            1,
            (),
            "READY",
            (),
            profile.mode,
            profile.dispatch_mode,
            stages,
        ))
    required = ("hld_ref", "adr_ref", "human_design_gate_ref", "independent_reviewer_ref")
    missing = tuple(key for key in required if not evidence.get(key))
    return _with_execution_control_assurance(ReviewPlan(
        "G2",
        "full-architecture-and-independent-review",
        1,
        required,
        "BLOCKED" if missing else "READY",
        missing,
        profile.mode,
        profile.dispatch_mode,
        stages,
    ))


def build_validation_plan(
    work: Work,
    *,
    check_risk_mapping: Mapping[str, str],
    independent_qa_ref: str = "",
    execution_plan: ValidationExecutionPlan | None = None,
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
    if execution_plan is not None and execution_plan.decision == "BLOCKED":
        errors.extend(execution_plan.errors)
    layer_decisions = (
        {step.layer: step.action for step in execution_plan.steps}
        if execution_plan is not None
        else {layer: "PLANNED" for layer in VALIDATION_LAYERS}
    )
    return _with_execution_control_assurance(ValidationPlan(
        risk_profile=work.risk_profile,
        check_ids=declared,
        risk_mapping=mapping,
        max_check_groups=work.budget.check_groups,
        independent_qa_required=independent,
        validation_scope_required=work.risk_profile == "G2",
        decision="BLOCKED" if errors else "READY",
        errors=tuple(errors),
        route_mode=work.route_profile.mode,
        dispatch_mode=work.route_profile.dispatch_mode,
        stages=(
            tuple(f"CP{index}" for index in range(9))
            if work.route_profile.legacy_cp_compatibility
            else ("clarification", "design", "implementation", "verification")
        ),
        layer_decisions=layer_decisions,
        next_layer=execution_plan.next_layer if execution_plan is not None else "targeted",
    ))
