from __future__ import annotations

from hashlib import sha256

import pytest
from test_semantic_identity import _value

from meta_flow.evidence.receipt_equivalence import (
    PlannerReuseReasonV1,
    ReceiptReuseStatusV1,
    assess_receipt_reuse,
    build_planner_reuse_evidence,
    invalidate_receipts,
)
from meta_flow.evidence.semantic_identity import (
    APPROVED_CANONICALIZER_SET_DIGEST,
    APPROVED_DIMENSIONS,
    APPROVED_TABLE_DIGEST,
    build_semantic_identity,
    load_embedded_concrete_equivalence_table,
)


def _digest(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def _identity(
    *,
    values: dict[str, dict[str, object]] | None = None,
    evidence: str | None = None,
    graph: str | None = None,
    oid: str = "audit",
):
    return build_semantic_identity(
        table=load_embedded_concrete_equivalence_table(),
        values=values
        or {dimension: _value(dimension) for dimension in APPROVED_DIMENSIONS},
        receipt_evidence_digest=evidence or _digest("evidence"),
        decision_graph_digest=graph or _digest("graph"),
        oid=oid,
    )


def test_seven_of_seven_with_exact_evidence_digest_is_only_eligible_fact() -> None:
    fact = assess_receipt_reuse(receipt=_identity(oid="old"), current=_identity(oid="new"))
    assert fact.status is ReceiptReuseStatusV1.REUSE_ELIGIBLE
    assert fact.authority == "S02-validation-kernel"
    assert len(fact.classifications) == 7


def test_evidence_digest_mismatch_denies_reuse() -> None:
    fact = assess_receipt_reuse(
        receipt=_identity(evidence=_digest("receipt")),
        current=_identity(evidence=_digest("current")),
    )
    assert fact.status is ReceiptReuseStatusV1.DENY_INSUFFICIENT_EVIDENCE


@pytest.mark.parametrize("dimension", APPROVED_DIMENSIONS)
def test_each_directed_semantic_drift_denies_reuse(dimension: str) -> None:
    values = {item: _value(item) for item in APPROVED_DIMENSIONS}
    values[dimension] = _value(dimension, "changed")
    assert (
        assess_receipt_reuse(receipt=_identity(), current=_identity(values=values)).status
        is ReceiptReuseStatusV1.DENY_NON_EQUIVALENT
    )


@pytest.mark.parametrize("dimension", APPROVED_DIMENSIONS)
def test_each_directed_unknown_denies_reuse(dimension: str) -> None:
    values = {item: _value(item) for item in APPROVED_DIMENSIONS}
    values[dimension] = {"ambiguous": True}
    assert (
        assess_receipt_reuse(receipt=_identity(), current=_identity(values=values)).status
        is ReceiptReuseStatusV1.DENY_UNKNOWN
    )


def test_planner_adapter_binds_real_receipt_and_sole_authority_graph() -> None:
    evidence = _digest("planner-receipt")
    graph = _digest("authoritative-graph")
    result = build_planner_reuse_evidence(
        receipt=_identity(evidence=evidence, graph=graph),
        current=_identity(evidence=evidence, graph=graph),
        planner_receipt_digest=evidence,
        basis_comparable=True,
        authority_graph_digest=graph,
        authority_decision="PASS",
        authority_path_count=1,
        duplicate_rule_owner_count=0,
        dependency_rule_owner="validation_kernel",
    )
    assert result.eligible_for_kernel
    assert result.reason_code is PlannerReuseReasonV1.ELIGIBLE_FOR_KERNEL


@pytest.mark.parametrize(
    ("override", "reason"),
    (
        ({"planner_receipt_digest": _digest("wrong")}, PlannerReuseReasonV1.PLANNER_RECEIPT_DIGEST_MISMATCH),
        ({"authority_graph_digest": _digest("wrong")}, PlannerReuseReasonV1.AUTHORITY_GRAPH_UNBOUND),
        ({"authority_decision": "BLOCKED"}, PlannerReuseReasonV1.AUTHORITY_GRAPH_UNBOUND),
        ({"authority_path_count": 2}, PlannerReuseReasonV1.AUTHORITY_GRAPH_UNBOUND),
        ({"duplicate_rule_owner_count": 1}, PlannerReuseReasonV1.AUTHORITY_GRAPH_UNBOUND),
        ({"dependency_rule_owner": "fake-consumer"}, PlannerReuseReasonV1.AUTHORITY_GRAPH_UNBOUND),
    ),
)
def test_planner_adapter_denies_unbound_receipt_or_authority(
    override: dict[str, object], reason: PlannerReuseReasonV1
) -> None:
    evidence = _digest("planner-receipt")
    graph = _digest("authoritative-graph")
    arguments: dict[str, object] = {
        "receipt": _identity(evidence=evidence, graph=graph),
        "current": _identity(evidence=evidence, graph=graph),
        "planner_receipt_digest": evidence,
        "basis_comparable": True,
        "authority_graph_digest": graph,
        "authority_decision": "PASS",
        "authority_path_count": 1,
        "duplicate_rule_owner_count": 0,
        "dependency_rule_owner": "validation_kernel",
    }
    arguments.update(override)
    result = build_planner_reuse_evidence(**arguments)
    assert not result.eligible_for_kernel
    assert result.reason_code is reason


def test_invalidation_ignores_oid_but_not_approved_bindings() -> None:
    receipt = _identity(oid="same")
    assert not invalidate_receipts(
        receipt=receipt,
        table_digest=APPROVED_TABLE_DIGEST,
        canonicalizer_set_digest=APPROVED_CANONICALIZER_SET_DIGEST,
        decision_graph_digest=_digest("graph"),
    )
    assert invalidate_receipts(
        receipt=receipt,
        table_digest=APPROVED_TABLE_DIGEST,
        canonicalizer_set_digest=_digest("stale"),
        decision_graph_digest=_digest("graph"),
    )
