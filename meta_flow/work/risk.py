"""Work/CR 与 G0/G1/G2 的结构化、可解释分类。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from meta_flow.work.budget import G0_BUDGET, G1_BUDGET, BudgetLimit

RISK_PROFILES = {"G0", "G1", "G2"}
LOW_CHANGE_KINDS = {"documentation", "config", "mechanical"}
HIGH_RISK_FIELDS = {
    "public_contract": "PUBLIC_CONTRACT",
    "architecture_boundary": "ARCHITECTURE_BOUNDARY",
    "security": "SECURITY",
    "permissions": "PERMISSIONS",
    "irreversible_migration": "IRREVERSIBLE_MIGRATION",
    "production_write": "PRODUCTION_WRITE",
    "formal_release": "FORMAL_RELEASE",
    "strong_audit": "STRONG_AUDIT",
    "risk_acceptance": "RISK_ACCEPTANCE",
    "cross_phase_restructure": "CROSS_PHASE_RESTRUCTURE",
    "new_remote": "NEW_REMOTE",
    "protected_ref": "PROTECTED_REF",
    "tag": "TAG",
    "external_publication": "EXTERNAL_PUBLICATION",
}


@dataclass(frozen=True)
class RiskFacts:
    change_kind: str
    touched_path_count: int
    reversible: bool = True
    multi_module: bool = False
    internal_interface: bool = False
    multi_step: bool = False
    repository_push: bool = False
    preauthorized_repo_ref: bool = False
    public_contract: bool = False
    architecture_boundary: bool = False
    security: bool = False
    permissions: bool = False
    irreversible_migration: bool = False
    production_write: bool = False
    formal_release: bool = False
    strong_audit: bool = False
    risk_acceptance: bool = False
    cross_phase_restructure: bool = False
    new_remote: bool = False
    protected_ref: bool = False
    tag: bool = False
    external_publication: bool = False
    unknown_high_risk_facts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.change_kind:
            raise ValueError("change_kind is required")
        if self.touched_path_count < 0:
            raise ValueError("touched_path_count must be non-negative")
        if len(set(self.unknown_high_risk_facts)) != len(self.unknown_high_risk_facts):
            raise ValueError("unknown_high_risk_facts contains duplicates")


@dataclass(frozen=True)
class ClassificationDecision:
    container_kind: str
    risk_profile: str
    reason_codes: tuple[str, ...]
    budget: BudgetLimit | None
    required_gates: tuple[str, ...]
    blocked: bool
    cannot_silently_downgrade: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "container_kind": self.container_kind,
            "risk_profile": self.risk_profile,
            "reason_codes": list(self.reason_codes),
            "budget": self.budget.as_dict() if self.budget else None,
            "required_gates": list(self.required_gates),
            "blocked": self.blocked,
            "cannot_silently_downgrade": self.cannot_silently_downgrade,
        }


def _profile_rank(value: str) -> int:
    return {"G0": 0, "G1": 1, "G2": 2}[value]


def classify_work(
    facts: RiskFacts,
    *,
    requested_cr: bool = False,
    requested_profile: str | None = None,
    g2_budget: BudgetLimit | None = None,
) -> ClassificationDecision:
    if requested_profile is not None and requested_profile not in RISK_PROFILES:
        raise ValueError("requested_profile must be G0, G1, or G2")
    high_reasons = [
        code
        for field, code in HIGH_RISK_FIELDS.items()
        if bool(getattr(facts, field))
    ]
    unknown_reasons = [f"UNKNOWN_{item.upper().replace('-', '_')}" for item in facts.unknown_high_risk_facts]
    if requested_cr:
        high_reasons.append("USER_REQUESTED_CR")

    if high_reasons or unknown_reasons:
        base_profile = "G2"
        container_kind = "cr"
        reasons = [*high_reasons, *unknown_reasons]
    elif (
        facts.change_kind in LOW_CHANGE_KINDS
        and facts.touched_path_count <= 1
        and facts.reversible
        and not facts.multi_module
        and not facts.internal_interface
        and not facts.multi_step
    ):
        base_profile = "G0"
        container_kind = "work"
        reasons = ["REVERSIBLE_LOCAL_CHANGE"]
    else:
        base_profile = "G1"
        container_kind = "work"
        reasons = ["STANDARD_MULTI_FILE_OR_MULTI_STEP_CHANGE"]
        if not facts.reversible:
            reasons.append("NON_REVERSIBLE_LOCAL_CHANGE")
        if facts.multi_module:
            reasons.append("MULTI_MODULE")
        if facts.internal_interface:
            reasons.append("INTERNAL_INTERFACE")
        if facts.multi_step:
            reasons.append("MULTI_STEP")

    if facts.repository_push:
        if facts.preauthorized_repo_ref and base_profile != "G2":
            reasons.append("PREAUTHORIZED_REPOSITORY_PUSH")
        elif not facts.preauthorized_repo_ref:
            base_profile = "G2"
            container_kind = "cr"
            reasons.append("UNAUTHORIZED_REPOSITORY_PUSH_TARGET")

    final_profile = base_profile
    if requested_profile is not None and _profile_rank(requested_profile) > _profile_rank(base_profile):
        final_profile = requested_profile
        reasons.append(f"USER_UPGRADED_TO_{requested_profile}")
    elif requested_profile is not None and _profile_rank(requested_profile) < _profile_rank(base_profile):
        reasons.append("DOWNGRADE_REJECTED")

    if final_profile == "G0":
        budget = G0_BUDGET
        gates: tuple[str, ...] = ()
        blocked = False
    elif final_profile == "G1":
        budget = G1_BUDGET
        gates = ()
        blocked = False
    else:
        budget = g2_budget
        gates = ("GATE-SCOPE", "GATE-DESIGN")
        blocked = bool(unknown_reasons) or budget is None
        if unknown_reasons:
            reasons.append("HIGH_RISK_FACTS_REQUIRE_RESOLUTION")
        if budget is None:
            reasons.append("G2_BUDGET_REQUIRED")

    return ClassificationDecision(
        container_kind=container_kind,
        risk_profile=final_profile,
        reason_codes=tuple(dict.fromkeys(reasons)),
        budget=budget,
        required_gates=gates,
        blocked=blocked,
    )
