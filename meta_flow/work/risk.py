"""Work/CR 与 GovernanceRiskProfile G0/G1/G2/G3 的可解释分类。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from meta_flow.work.budget import G0_BUDGET, G1_BUDGET, BudgetLimit
from meta_flow.work.governance_profile import (
    GOVERNANCE_PROFILE_SCHEMA_VERSION,
    GOVERNANCE_RISK_PROFILES,
    G3SelectionRecordV1,
)

RISK_PROFILES = set(GOVERNANCE_RISK_PROFILES)
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
    requested_lld: bool = False
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
    risk_profile_schema_version: int = 1
    selection_source: str = "system-default"
    selection_record_digest: str = ""
    selection_authorization_digest: str = ""
    selection_source_oid: str = ""
    route_revision: int = 1

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "container_kind": self.container_kind,
            "risk_profile": self.risk_profile,
            "reason_codes": list(self.reason_codes),
            "budget": self.budget.as_dict() if self.budget else None,
            "required_gates": list(self.required_gates),
            "blocked": self.blocked,
            "cannot_silently_downgrade": self.cannot_silently_downgrade,
        }
        if self.risk_profile_schema_version >= 2:
            payload.update(
                {
                    "risk_profile_schema_version": self.risk_profile_schema_version,
                    "selection_source": self.selection_source,
                    "selection_record_digest": self.selection_record_digest,
                    "selection_authorization_digest": self.selection_authorization_digest,
                    "selection_source_oid": self.selection_source_oid,
                    "route_revision": self.route_revision,
                }
            )
        return payload


def _profile_rank(value: str) -> int:
    return {"G0": 0, "G1": 1, "G2": 2, "G3": 3}[value]


def classify_work(
    facts: RiskFacts,
    *,
    requested_cr: bool = False,
    requested_profile: str | None = None,
    g2_budget: BudgetLimit | None = None,
    g3_selection: G3SelectionRecordV1 | Mapping[str, Any] | None = None,
    selection_cr_id: str = "",
    selection_source_oid: str = "",
    selection_route_revision: int = 1,
    selection_authorization_digest: str = "",
    selection_channel: str = "config",
) -> ClassificationDecision:
    if requested_profile is not None and requested_profile not in RISK_PROFILES:
        raise ValueError("requested_profile must be G0, G1, G2, or G3")
    selection = (
        G3SelectionRecordV1.from_mapping(g3_selection)
        if isinstance(g3_selection, Mapping)
        else g3_selection
    )
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

    selection_errors: list[str] = []
    g3_requested = requested_profile == "G3" or facts.requested_lld or selection is not None
    if g3_requested:
        container_kind = "cr"
        if selection is None:
            selection_errors.append("G3_SELECTION_REQUIRED")
        elif not selection_cr_id or not selection_source_oid:
            selection_errors.append("G3_SELECTION_BINDING_CONTEXT_REQUIRED")
        else:
            selection_errors.extend(
                selection.binding_errors(
                    cr_id=selection_cr_id,
                    source_oid=selection_source_oid,
                    route_revision=selection_route_revision,
                    authorization_digest=selection_authorization_digest,
                    selection_channel=selection_channel,
                )
            )

    final_profile = base_profile
    if g3_requested and not selection_errors:
        final_profile = "G3"
        reasons.append("USER_REQUESTED_FULL_LLD_G3")
    elif g3_requested:
        # 无可信选择时保持在高风险默认档并阻断，禁止把不可信 G3 请求当作 G2 PASS。
        final_profile = "G2"
        reasons.extend(selection_errors)
    elif requested_profile is not None and _profile_rank(requested_profile) > _profile_rank(base_profile):
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
        blocked = bool(unknown_reasons) or budget is None or bool(selection_errors)
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
        risk_profile_schema_version=(
            GOVERNANCE_PROFILE_SCHEMA_VERSION if final_profile in {"G2", "G3"} else 1
        ),
        selection_source="user-explicit" if final_profile == "G3" else "system-default",
        selection_record_digest=selection.digest if final_profile == "G3" and selection else "",
        selection_authorization_digest=(
            selection_authorization_digest if final_profile == "G3" else ""
        ),
        selection_source_oid=selection_source_oid if final_profile == "G3" else "",
        route_revision=selection_route_revision,
    )
