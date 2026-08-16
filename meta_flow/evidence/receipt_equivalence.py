"""Fail-closed receipt-reuse facts and the planner-facing evidence adapter."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .semantic_identity import (
    APPROVED_CANONICALIZER_SET_DIGEST,
    APPROVED_TABLE_DIGEST,
    DimensionClassificationV1,
    SemanticIdentityV1,
    is_sha256,
)


class ReceiptReuseStatusV1(StrEnum):
    REUSE_ELIGIBLE = "REUSE_ELIGIBLE"
    DENY_NON_EQUIVALENT = "DENY_NON_EQUIVALENT"
    DENY_UNKNOWN = "DENY_UNKNOWN"
    DENY_INSUFFICIENT_EVIDENCE = "DENY_INSUFFICIENT_EVIDENCE"
    DENY_STALE_CLASSIFIER = "DENY_STALE_CLASSIFIER"


class PlannerReuseReasonV1(StrEnum):
    ELIGIBLE_FOR_KERNEL = "ELIGIBLE_FOR_KERNEL"
    RECEIPT_FACT_DENIED = "RECEIPT_FACT_DENIED"
    PLANNER_RECEIPT_DIGEST_MISMATCH = "PLANNER_RECEIPT_DIGEST_MISMATCH"
    AUTHORITY_GRAPH_UNBOUND = "AUTHORITY_GRAPH_UNBOUND"


@dataclass(frozen=True)
class ReceiptReuseFactV1:
    status: ReceiptReuseStatusV1
    classifications: tuple[DimensionClassificationV1, ...]
    evidence_integrity: bool
    stale: bool
    authority: str = "S02-validation-kernel"

    @property
    def eligible(self) -> bool:
        return self.status is ReceiptReuseStatusV1.REUSE_ELIGIBLE


@dataclass(frozen=True)
class PlannerReuseEvidenceV1:
    fact: ReceiptReuseFactV1
    eligible_for_kernel: bool
    reason_code: PlannerReuseReasonV1
    planner_receipt_digest: str
    authority_graph_digest: str


def classify_dimension(left: object, right: object) -> DimensionClassificationV1:
    """Compare canonical dimensions; missing and unknown values never match."""

    if not hasattr(left, "classification") or not hasattr(right, "classification"):
        return DimensionClassificationV1.UNKNOWN
    if (
        left.classification is DimensionClassificationV1.UNKNOWN
        or right.classification is DimensionClassificationV1.UNKNOWN
    ):
        return DimensionClassificationV1.UNKNOWN
    if not left.digest or not right.digest:
        return DimensionClassificationV1.UNKNOWN
    if left.dimension != right.dimension:
        return DimensionClassificationV1.UNKNOWN
    return (
        DimensionClassificationV1.EQUIVALENT
        if left.digest == right.digest
        else DimensionClassificationV1.NON_EQUIVALENT
    )


def assess_receipt_reuse(
    *,
    receipt: SemanticIdentityV1,
    current: SemanticIdentityV1,
    basis_comparable: bool = True,
) -> ReceiptReuseFactV1:
    """Produce a fact; evidence integrity is computed, never caller-asserted."""

    classifications = tuple(
        classify_dimension(left, right)
        for left, right in zip(receipt.dimensions, current.dimensions, strict=False)
    )
    stale = (
        receipt.table_ref != current.table_ref
        or receipt.table_digest != APPROVED_TABLE_DIGEST
        or current.table_digest != APPROVED_TABLE_DIGEST
        or receipt.canonicalizer_set_digest != APPROVED_CANONICALIZER_SET_DIGEST
        or current.canonicalizer_set_digest != APPROVED_CANONICALIZER_SET_DIGEST
        or receipt.decision_graph_digest != current.decision_graph_digest
        or not basis_comparable
    )
    evidence_integrity = (
        is_sha256(receipt.receipt_evidence_digest)
        and receipt.receipt_evidence_digest == current.receipt_evidence_digest
    )
    if stale:
        return ReceiptReuseFactV1(
            ReceiptReuseStatusV1.DENY_STALE_CLASSIFIER,
            classifications,
            evidence_integrity,
            True,
        )
    if len(classifications) != 7 or any(
        item is DimensionClassificationV1.UNKNOWN for item in classifications
    ):
        return ReceiptReuseFactV1(
            ReceiptReuseStatusV1.DENY_UNKNOWN,
            classifications,
            evidence_integrity,
            False,
        )
    if any(item is DimensionClassificationV1.NON_EQUIVALENT for item in classifications):
        return ReceiptReuseFactV1(
            ReceiptReuseStatusV1.DENY_NON_EQUIVALENT,
            classifications,
            evidence_integrity,
            False,
        )
    if not evidence_integrity:
        return ReceiptReuseFactV1(
            ReceiptReuseStatusV1.DENY_INSUFFICIENT_EVIDENCE,
            classifications,
            False,
            False,
        )
    return ReceiptReuseFactV1(
        ReceiptReuseStatusV1.REUSE_ELIGIBLE,
        classifications,
        True,
        False,
    )


def build_planner_reuse_evidence(
    *,
    receipt: SemanticIdentityV1,
    current: SemanticIdentityV1,
    planner_receipt_digest: str,
    basis_comparable: bool,
    authority_graph_digest: str,
    authority_decision: str,
    authority_path_count: int,
    duplicate_rule_owner_count: int,
    dependency_rule_owner: str,
) -> PlannerReuseEvidenceV1:
    """Bind the reuse fact to a real planner receipt and S02 authority graph."""

    fact = assess_receipt_reuse(
        receipt=receipt,
        current=current,
        basis_comparable=basis_comparable,
    )
    planner_bound = (
        is_sha256(planner_receipt_digest)
        and planner_receipt_digest == receipt.receipt_evidence_digest
        and planner_receipt_digest == current.receipt_evidence_digest
    )
    authority_bound = (
        is_sha256(authority_graph_digest)
        and authority_graph_digest == receipt.decision_graph_digest
        and authority_graph_digest == current.decision_graph_digest
        and authority_decision == "PASS"
        and type(authority_path_count) is int
        and authority_path_count == 1
        and type(duplicate_rule_owner_count) is int
        and duplicate_rule_owner_count == 0
        and dependency_rule_owner == "validation_kernel"
    )
    if not fact.eligible:
        reason = PlannerReuseReasonV1.RECEIPT_FACT_DENIED
    elif not planner_bound:
        reason = PlannerReuseReasonV1.PLANNER_RECEIPT_DIGEST_MISMATCH
    elif not authority_bound:
        reason = PlannerReuseReasonV1.AUTHORITY_GRAPH_UNBOUND
    else:
        reason = PlannerReuseReasonV1.ELIGIBLE_FOR_KERNEL
    return PlannerReuseEvidenceV1(
        fact,
        reason is PlannerReuseReasonV1.ELIGIBLE_FOR_KERNEL,
        reason,
        planner_receipt_digest,
        authority_graph_digest,
    )


def invalidate_receipts(
    *,
    receipt: SemanticIdentityV1,
    table_digest: str,
    canonicalizer_set_digest: str,
    decision_graph_digest: str,
) -> bool:
    """Return whether approved classifier/authority bindings are stale."""

    return (
        receipt.table_digest,
        receipt.canonicalizer_set_digest,
        receipt.decision_graph_digest,
    ) != (table_digest, canonicalizer_set_digest, decision_graph_digest)
