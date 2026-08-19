"""发布包的 truthful SemVer 分类与一次性 bootstrap 合同。"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from meta_flow.workflow.package_plan import canonical_digest

_VERSION_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

BOOTSTRAP_VERSION = "0.6.1"
BOOTSTRAP_RECOMMENDATION = "next-minor"
BOOTSTRAP_SELECTION_SOURCE = "explicit-user-decision"
BOOTSTRAP_REASON = "single-release-convergence-and-first-semver-gate-cutover"
BOOTSTRAP_ENFORCE_AFTER = "0.6.1"


def _closed(value: object, fields: set[str], *, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(code)
    return value


def _text(
    value: object,
    *,
    code: str,
    pattern: re.Pattern[str] | None = None,
    allow_empty: bool = False,
) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or (not value and not allow_empty)
        or (pattern is not None and not pattern.fullmatch(value))
    ):
        raise ValueError(code)
    return value


def _strings(value: object, *, code: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, str) or not item or item != item.strip() for item in value
    ):
        raise ValueError(code)
    return tuple(sorted(set(value)))


def _next_version(version: str, recommendation: str) -> str:
    match = _VERSION_RE.fullmatch(version)
    if match is None:
        raise ValueError("SEMVER_BASE_VERSION_INVALID")
    major, minor, patch = (int(part) for part in match.groups())
    if recommendation == "next-minor":
        return f"{major}.{minor + 1}.0"
    if recommendation == "next-patch":
        return f"{major}.{minor}.{patch + 1}"
    return ""


@dataclass(frozen=True)
class SemVerDecisionInputV1:
    schema_version: int
    package_id: str
    cr_id: str
    base_version: str
    requested_version: str
    added_public_operations: tuple[str, ...]
    added_public_schemas: tuple[str, ...]
    added_compatible_capabilities: tuple[str, ...]
    bug_fix_ids: tuple[str, ...]
    breaking_evidence: tuple[str, ...]
    unknown_compatibility_evidence: tuple[str, ...]
    source_digest: str
    plan_digest: str
    policy_digest: str
    compatibility_digest: str
    claimed_category: str

    @classmethod
    def from_mapping(cls, value: object) -> SemVerDecisionInputV1:
        fields = {
            "schema_version",
            "package_id",
            "cr_id",
            "base_version",
            "requested_version",
            "added_public_operations",
            "added_public_schemas",
            "added_compatible_capabilities",
            "bug_fix_ids",
            "breaking_evidence",
            "unknown_compatibility_evidence",
            "source_digest",
            "plan_digest",
            "policy_digest",
            "compatibility_digest",
            "claimed_category",
        }
        item = _closed(value, fields, code="SEMVER_INPUT_FIELDS_MISMATCH")
        if item["schema_version"] != 1:
            raise ValueError("SEMVER_INPUT_SCHEMA_INVALID")
        claimed = _text(
            item["claimed_category"], code="SEMVER_CLAIMED_CATEGORY_INVALID", allow_empty=True
        )
        if claimed not in {"", "patch", "minor", "major"}:
            raise ValueError("SEMVER_CLAIMED_CATEGORY_INVALID")
        return cls(
            schema_version=1,
            package_id=_text(item["package_id"], code="SEMVER_PACKAGE_ID_INVALID", pattern=_ID_RE),
            cr_id=_text(item["cr_id"], code="SEMVER_CR_ID_INVALID", pattern=_ID_RE),
            base_version=_text(
                item["base_version"], code="SEMVER_BASE_VERSION_INVALID", pattern=_VERSION_RE
            ),
            requested_version=_text(
                item["requested_version"],
                code="SEMVER_REQUESTED_VERSION_INVALID",
                pattern=_VERSION_RE,
            ),
            added_public_operations=_strings(
                item["added_public_operations"], code="SEMVER_CHANGE_INVENTORY_INVALID"
            ),
            added_public_schemas=_strings(
                item["added_public_schemas"], code="SEMVER_CHANGE_INVENTORY_INVALID"
            ),
            added_compatible_capabilities=_strings(
                item["added_compatible_capabilities"], code="SEMVER_CHANGE_INVENTORY_INVALID"
            ),
            bug_fix_ids=_strings(item["bug_fix_ids"], code="SEMVER_CHANGE_INVENTORY_INVALID"),
            breaking_evidence=_strings(
                item["breaking_evidence"], code="SEMVER_CHANGE_INVENTORY_INVALID"
            ),
            unknown_compatibility_evidence=_strings(
                item["unknown_compatibility_evidence"],
                code="SEMVER_CHANGE_INVENTORY_INVALID",
            ),
            source_digest=_text(
                item["source_digest"], code="SEMVER_BINDING_DIGEST_INVALID", pattern=_DIGEST_RE
            ),
            plan_digest=_text(
                item["plan_digest"], code="SEMVER_BINDING_DIGEST_INVALID", pattern=_DIGEST_RE
            ),
            policy_digest=_text(
                item["policy_digest"], code="SEMVER_BINDING_DIGEST_INVALID", pattern=_DIGEST_RE
            ),
            compatibility_digest=_text(
                item["compatibility_digest"],
                code="SEMVER_BINDING_DIGEST_INVALID",
                pattern=_DIGEST_RE,
            ),
            claimed_category=claimed,
        )

    def classification_payload(self) -> dict[str, Any]:
        """只包含 machine facts；caller claim 永远不参与分类。"""

        return {
            "schema_version": self.schema_version,
            "package_id": self.package_id,
            "cr_id": self.cr_id,
            "base_version": self.base_version,
            "added_public_operations": list(self.added_public_operations),
            "added_public_schemas": list(self.added_public_schemas),
            "added_compatible_capabilities": list(self.added_compatible_capabilities),
            "bug_fix_ids": list(self.bug_fix_ids),
            "breaking_evidence": list(self.breaking_evidence),
            "unknown_compatibility_evidence": list(self.unknown_compatibility_evidence),
            "source_digest": self.source_digest,
            "plan_digest": self.plan_digest,
            "policy_digest": self.policy_digest,
            "compatibility_digest": self.compatibility_digest,
        }

    @property
    def classification_digest(self) -> str:
        return canonical_digest(self.classification_payload())


@dataclass(frozen=True)
class SemVerBootstrapDecisionV1:
    schema_version: int
    bootstrap_version: str
    normal_machine_recommendation: str
    selected_version: str
    selection_source: str
    reason: str
    reusable: bool
    enforce_after: str
    source_digest: str
    classification_digest: str
    policy_digest: str
    plan_digest: str
    decision_digest: str

    @classmethod
    def from_mapping(cls, value: object) -> SemVerBootstrapDecisionV1:
        fields = {
            "schema_version",
            "bootstrap_version",
            "normal_machine_recommendation",
            "selected_version",
            "selection_source",
            "reason",
            "reusable",
            "enforce_after",
            "source_digest",
            "classification_digest",
            "policy_digest",
            "plan_digest",
            "decision_digest",
        }
        item = _closed(value, fields, code="SEMVER_BOOTSTRAP_FIELDS_MISMATCH")
        payload = {key: item[key] for key in fields - {"decision_digest"}}
        if (
            item["schema_version"] != 1
            or item["bootstrap_version"] != BOOTSTRAP_VERSION
            or item["normal_machine_recommendation"] != BOOTSTRAP_RECOMMENDATION
            or item["selected_version"] != BOOTSTRAP_VERSION
            or item["selection_source"] != BOOTSTRAP_SELECTION_SOURCE
            or item["reason"] != BOOTSTRAP_REASON
            or item["reusable"] is not False
            or item["enforce_after"] != BOOTSTRAP_ENFORCE_AFTER
        ):
            raise ValueError("SEMVER_BOOTSTRAP_CONSTANT_MISMATCH")
        for field in (
            "source_digest",
            "classification_digest",
            "policy_digest",
            "plan_digest",
            "decision_digest",
        ):
            _text(item[field], code="SEMVER_BOOTSTRAP_DIGEST_INVALID", pattern=_DIGEST_RE)
        if item["decision_digest"] != canonical_digest(payload):
            raise ValueError("SEMVER_BOOTSTRAP_DECISION_DIGEST_MISMATCH")
        return cls(**item)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "bootstrap_version": self.bootstrap_version,
            "normal_machine_recommendation": self.normal_machine_recommendation,
            "selected_version": self.selected_version,
            "selection_source": self.selection_source,
            "reason": self.reason,
            "reusable": self.reusable,
            "enforce_after": self.enforce_after,
            "source_digest": self.source_digest,
            "classification_digest": self.classification_digest,
            "policy_digest": self.policy_digest,
            "plan_digest": self.plan_digest,
            "decision_digest": self.decision_digest,
        }


def build_cr072_bootstrap(value: SemVerDecisionInputV1) -> SemVerBootstrapDecisionV1:
    """构造 CP2 冻结的一次性 0.6.1 bootstrap；不消费它。"""

    payload: dict[str, Any] = {
        "schema_version": 1,
        "bootstrap_version": BOOTSTRAP_VERSION,
        "normal_machine_recommendation": BOOTSTRAP_RECOMMENDATION,
        "selected_version": BOOTSTRAP_VERSION,
        "selection_source": BOOTSTRAP_SELECTION_SOURCE,
        "reason": BOOTSTRAP_REASON,
        "reusable": False,
        "enforce_after": BOOTSTRAP_ENFORCE_AFTER,
        "source_digest": value.source_digest,
        "classification_digest": value.classification_digest,
        "policy_digest": value.policy_digest,
        "plan_digest": value.plan_digest,
    }
    payload["decision_digest"] = canonical_digest(payload)
    return SemVerBootstrapDecisionV1.from_mapping(payload)


@dataclass(frozen=True)
class SemVerDiagnosticV1:
    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"severity": "BLOCKER", "code": self.code, "message": self.message}


@dataclass(frozen=True)
class SemVerDecisionV1:
    schema_version: int
    package_id: str
    cr_id: str
    base_version: str
    requested_version: str
    normal_machine_recommendation: str
    normal_recommended_version: str
    selected_version: str
    classification_digest: str
    bootstrap_used: bool
    bootstrap_decision_digest: str
    bootstrap_consumption_key: str
    diagnostics: tuple[SemVerDiagnosticV1, ...]
    decision: str
    semantic_digest: str
    mutation_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": "SemVerDecisionV1",
            "package_id": self.package_id,
            "cr_id": self.cr_id,
            "base_version": self.base_version,
            "requested_version": self.requested_version,
            "normal_machine_recommendation": self.normal_machine_recommendation,
            "normal_recommended_version": self.normal_recommended_version,
            "selected_version": self.selected_version,
            "classification_digest": self.classification_digest,
            "bootstrap_used": self.bootstrap_used,
            "bootstrap_decision_digest": self.bootstrap_decision_digest,
            "bootstrap_consumption_key": self.bootstrap_consumption_key,
            "diagnostics": [item.as_dict() for item in self.diagnostics],
            "decision": self.decision,
            "semantic_digest": self.semantic_digest,
            "mutation_count": self.mutation_count,
        }


def decide_semver(
    value: SemVerDecisionInputV1,
    bootstrap: SemVerBootstrapDecisionV1 | None = None,
    *,
    consumed_bootstrap_keys: Sequence[str] = (),
) -> SemVerDecisionV1:
    """先 truthful classify，再验证 bootstrap；breaking 永远不能被例外覆盖。"""

    diagnostics: list[SemVerDiagnosticV1] = []
    if value.breaking_evidence:
        diagnostics.append(
            SemVerDiagnosticV1(
                "BREAKING_CHANGE_DETECTED",
                "breaking compatibility evidence blocks every 0.6.1 bootstrap",
            )
        )
    if value.unknown_compatibility_evidence:
        diagnostics.append(
            SemVerDiagnosticV1(
                "COMPATIBILITY_UNKNOWN",
                "unknown compatibility must be resolved before version selection",
            )
        )
    has_public_addition = bool(
        value.added_public_operations
        or value.added_public_schemas
        or value.added_compatible_capabilities
    )
    recommendation = "next-minor" if has_public_addition else "next-patch"
    normal_version = _next_version(value.base_version, recommendation)
    bootstrap_used = False
    bootstrap_digest = ""
    consumption_key = ""
    selected_version = normal_version

    if not diagnostics and bootstrap is not None:
        bootstrap_digest = bootstrap.decision_digest
        bindings_match = (
            bootstrap.source_digest == value.source_digest
            and bootstrap.classification_digest == value.classification_digest
            and bootstrap.policy_digest == value.policy_digest
            and bootstrap.plan_digest == value.plan_digest
        )
        if bootstrap.bootstrap_version != value.requested_version:
            diagnostics.append(
                SemVerDiagnosticV1(
                    "BOOTSTRAP_VERSION_MISMATCH",
                    "bootstrap version differs from the requested version",
                )
            )
        elif recommendation != BOOTSTRAP_RECOMMENDATION:
            diagnostics.append(
                SemVerDiagnosticV1(
                    "BOOTSTRAP_RECOMMENDATION_MISMATCH",
                    "bootstrap only applies to a truthful next-minor classification",
                )
            )
        elif not bindings_match:
            diagnostics.append(
                SemVerDiagnosticV1(
                    "BOOTSTRAP_BINDING_DIGEST_MISMATCH",
                    "source, classification, policy or Plan digest drifted",
                )
            )
        else:
            consumption_key = canonical_digest(
                {
                    "package_id": value.package_id,
                    "version": bootstrap.selected_version,
                    "decision_digest": bootstrap.decision_digest,
                }
            )
            if consumption_key in set(consumed_bootstrap_keys):
                diagnostics.append(
                    SemVerDiagnosticV1(
                        "BOOTSTRAP_ALREADY_CONSUMED",
                        "the one-shot bootstrap decision is already present in release history",
                    )
                )
            else:
                bootstrap_used = True
                selected_version = bootstrap.selected_version
    elif not diagnostics and value.requested_version != normal_version:
        diagnostics.append(
            SemVerDiagnosticV1(
                "REQUESTED_VERSION_SEMVER_MISMATCH",
                "requested version differs from the truthful machine recommendation",
            )
        )

    if value.claimed_category and (
        value.claimed_category
        != {"next-minor": "minor", "next-patch": "patch"}.get(recommendation)
    ):
        # 该提示不阻断，也不进入 machine classification digest。
        caller_claim_ignored = True
    else:
        caller_claim_ignored = False
    ordered_diagnostics = tuple(sorted(diagnostics, key=lambda item: item.code))
    decision = "BLOCKED" if ordered_diagnostics else "PASS"
    if decision == "BLOCKED":
        selected_version = ""
        bootstrap_used = False
        consumption_key = ""
    semantic_payload = {
        "package_id": value.package_id,
        "cr_id": value.cr_id,
        "base_version": value.base_version,
        "requested_version": value.requested_version,
        "normal_machine_recommendation": recommendation,
        "normal_recommended_version": normal_version,
        "selected_version": selected_version,
        "classification_digest": value.classification_digest,
        "bootstrap_used": bootstrap_used,
        "bootstrap_decision_digest": bootstrap_digest,
        "bootstrap_consumption_key": consumption_key,
        "caller_claim_ignored": caller_claim_ignored,
        "diagnostics": [item.as_dict() for item in ordered_diagnostics],
        "decision": decision,
    }
    return SemVerDecisionV1(
        schema_version=1,
        package_id=value.package_id,
        cr_id=value.cr_id,
        base_version=value.base_version,
        requested_version=value.requested_version,
        normal_machine_recommendation=recommendation,
        normal_recommended_version=normal_version,
        selected_version=selected_version,
        classification_digest=value.classification_digest,
        bootstrap_used=bootstrap_used,
        bootstrap_decision_digest=bootstrap_digest,
        bootstrap_consumption_key=consumption_key,
        diagnostics=ordered_diagnostics,
        decision=decision,
        semantic_digest=canonical_digest(semantic_payload),
    )


__all__ = [
    "BOOTSTRAP_ENFORCE_AFTER",
    "BOOTSTRAP_REASON",
    "BOOTSTRAP_RECOMMENDATION",
    "BOOTSTRAP_SELECTION_SOURCE",
    "BOOTSTRAP_VERSION",
    "SemVerBootstrapDecisionV1",
    "SemVerDecisionInputV1",
    "SemVerDecisionV1",
    "build_cr072_bootstrap",
    "decide_semver",
]
