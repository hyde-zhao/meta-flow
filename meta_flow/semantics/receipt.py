"""semantic contract digest 的 compiler 与 validator owner。"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meta_flow.project.onboarding_contract import canonical_digest
from meta_flow.semantics import outcome, ownership, preregistration

SEMANTIC_CONTRACT_SCHEMA_VERSION = 1
SEMANTIC_CONTRACT_KIND = "SemanticContractV1"
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
RECEIPT_BINDING_CONTRACT = {
    "schema": "FrozenCp6EvidenceV2",
    "schema_version": 2,
    "contract_digest_field": "contract_digest",
    "compiler": "current-source-r5-r6-r7",
    "validator": "recompute-current-source-before-ready",
    "v1_compatibility": "read-only-without-contract-bound-claim",
}


class SemanticContractError(ValueError):
    """当前 semantic contract 无法可信编译。"""


@dataclass(frozen=True)
class SemanticContractV1:
    """R5/R6/R7 语义的可摘要闭集快照。"""

    ownership: dict[str, Any]
    preregistration: dict[str, Any]
    outcome: dict[str, Any]
    receipt_binding: dict[str, Any]
    schema_version: int = SEMANTIC_CONTRACT_SCHEMA_VERSION
    kind: str = SEMANTIC_CONTRACT_KIND

    def __post_init__(self) -> None:
        if self.schema_version != SEMANTIC_CONTRACT_SCHEMA_VERSION:
            raise SemanticContractError("unknown semantic contract schema_version")
        if self.kind != SEMANTIC_CONTRACT_KIND:
            raise SemanticContractError("semantic contract kind mismatch")
        if set(self.ownership) != {
            "source_fingerprint",
            "concept_coverage",
            "consumer_coverage",
            "detector_profile_id",
        }:
            raise SemanticContractError("semantic ownership contract fields mismatch")
        source_fingerprint = self.ownership.get("source_fingerprint")
        if not isinstance(source_fingerprint, str) or not _DIGEST_RE.fullmatch(
            source_fingerprint
        ):
            raise SemanticContractError("semantic ownership source fingerprint invalid")
        for key in ("concept_coverage", "consumer_coverage"):
            coverage = self.ownership.get(key)
            if not isinstance(coverage, Mapping) or coverage.get("percent") != 100.0:
                raise SemanticContractError(f"semantic {key} must be 100%")
        if set(self.ownership["concept_coverage"]) != {
            "discovered",
            "owned",
            "percent",
        }:
            raise SemanticContractError("semantic concept coverage fields mismatch")
        if set(self.ownership["consumer_coverage"]) != {
            "discovered",
            "mapped",
            "percent",
        }:
            raise SemanticContractError("semantic consumer coverage fields mismatch")
        if not isinstance(self.ownership.get("detector_profile_id"), str) or not self.ownership[
            "detector_profile_id"
        ]:
            raise SemanticContractError("semantic detector profile is required")
        if self.preregistration.get("kind") != "PreregistrationSemanticsContractV1":
            raise SemanticContractError("preregistration semantic contract kind mismatch")
        if set(self.preregistration) != set(
            preregistration.semantic_contract_payload()
        ):
            raise SemanticContractError("preregistration semantic contract fields mismatch")
        if self.outcome.get("kind") != "OutcomeBoundaryContractV1":
            raise SemanticContractError("outcome semantic contract kind mismatch")
        if set(self.outcome) != set(outcome.semantic_contract_payload()):
            raise SemanticContractError("outcome semantic contract fields mismatch")
        if set(self.receipt_binding) != set(RECEIPT_BINDING_CONTRACT):
            raise SemanticContractError("semantic receipt binding fields mismatch")
        if self.receipt_binding.get("schema_version") != 2 or any(
            not isinstance(self.receipt_binding.get(field), str)
            or not self.receipt_binding[field]
            for field in set(RECEIPT_BINDING_CONTRACT) - {"schema_version"}
        ):
            raise SemanticContractError("semantic receipt binding values invalid")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "ownership": dict(self.ownership),
            "preregistration": dict(self.preregistration),
            "outcome": dict(self.outcome),
            "receipt_binding": dict(self.receipt_binding),
        }

    @property
    def contract_digest(self) -> str:
        return canonical_digest(self.as_dict())


def compile_contract_from_components(
    *,
    ownership_contract: Mapping[str, Any],
    preregistration_contract: Mapping[str, Any],
    outcome_contract: Mapping[str, Any],
    receipt_binding_contract: Mapping[str, Any] = RECEIPT_BINDING_CONTRACT,
) -> SemanticContractV1:
    """从已观察的三个 canonical component 构造稳定合同。"""

    return SemanticContractV1(
        ownership=dict(ownership_contract),
        preregistration=dict(preregistration_contract),
        outcome=dict(outcome_contract),
        receipt_binding=dict(receipt_binding_contract),
    )


def compile_semantic_contract(project_root: Path) -> SemanticContractV1:
    """从当前 release/process source 重新编译，不接受 caller digest。"""

    root = project_root.resolve()
    report = ownership.validate_ownership(root)
    if report.get("decision") != "PASS":
        errors = report.get("errors") or []
        raise SemanticContractError(
            "governance ownership is not current: " + "; ".join(str(item) for item in errors)
        )
    concept_coverage = report.get("concept_coverage")
    consumer_coverage = report.get("consumer_coverage")
    detector = report.get("detector")
    if not all(isinstance(item, Mapping) for item in (concept_coverage, consumer_coverage, detector)):
        raise SemanticContractError("governance ownership report shape invalid")
    return compile_contract_from_components(
        ownership_contract={
            "source_fingerprint": report.get("source_fingerprint"),
            "concept_coverage": {
                "discovered": concept_coverage.get("discovered"),
                "owned": concept_coverage.get("owned"),
                "percent": concept_coverage.get("percent"),
            },
            "consumer_coverage": {
                "discovered": consumer_coverage.get("discovered"),
                "mapped": consumer_coverage.get("mapped"),
                "percent": consumer_coverage.get("percent"),
            },
            "detector_profile_id": detector.get("profile_id"),
        },
        preregistration_contract=preregistration.semantic_contract_payload(),
        outcome_contract=outcome.semantic_contract_payload(),
    )


def validate_semantic_contract_digest(
    project_root: Path,
    expected_contract_digest: str,
) -> dict[str, Any]:
    """validator 端重算 current digest 并返回稳定失效结论。"""

    if not isinstance(expected_contract_digest, str) or not _DIGEST_RE.fullmatch(
        expected_contract_digest
    ):
        return {
            "decision": "BLOCKED",
            "reason_codes": ["SEMANTIC_CONTRACT_DIGEST_INVALID"],
            "current_contract_digest": "",
        }
    try:
        current = compile_semantic_contract(project_root)
    except (OSError, ValueError) as exc:
        return {
            "decision": "BLOCKED",
            "reason_codes": ["SEMANTIC_CONTRACT_RECOMPUTE_FAILED"],
            "detail": str(exc),
            "current_contract_digest": "",
        }
    current_digest = current.contract_digest
    if current_digest != expected_contract_digest:
        return {
            "decision": "revalidation-required",
            "reason_codes": ["SEMANTIC_CONTRACT_DIGEST_CHANGED"],
            "current_contract_digest": current_digest,
        }
    return {
        "decision": "READY",
        "reason_codes": ["SEMANTIC_CONTRACT_DIGEST_RECONFIRMED"],
        "current_contract_digest": current_digest,
    }


__all__ = [
    "SEMANTIC_CONTRACT_KIND",
    "SEMANTIC_CONTRACT_SCHEMA_VERSION",
    "RECEIPT_BINDING_CONTRACT",
    "SemanticContractError",
    "SemanticContractV1",
    "compile_contract_from_components",
    "compile_semantic_contract",
    "validate_semantic_contract_digest",
]
