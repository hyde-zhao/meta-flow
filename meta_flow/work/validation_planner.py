"""targeted → compatibility → full 的确定性验证与复用计划。"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from meta_flow.evidence.receipt_equivalence import PlannerReuseEvidenceV1
from meta_flow.work.validation_fingerprint import VALIDATION_LAYERS
from meta_flow.work.validation_kernel import DecisionStatus, NormalizedDecisionGraphV1
from meta_flow.work.validation_receipt import ValidationReceipt

_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ValidationStep:
    layer: str
    action: str
    reason: str
    receipt_digest: str = ""

    def as_dict(self) -> dict[str, str]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class ValidationExecutionPlan:
    decision: str
    steps: tuple[ValidationStep, ...]
    next_layer: str
    full_execution_count: int
    errors: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "steps": [step.as_dict() for step in self.steps],
            "next_layer": self.next_layer,
            "full_execution_count": self.full_execution_count,
            "errors": list(self.errors),
        }


def build_validation_execution_plan(
    *,
    fingerprints: Mapping[str, str],
    command_identities: Mapping[str, str],
    receipts: tuple[ValidationReceipt, ...] = (),
    layers: tuple[str, ...] = VALIDATION_LAYERS,
    reuse_evidence: Mapping[str, PlannerReuseEvidenceV1] | None = None,
    authority_graph: NormalizedDecisionGraphV1 | None = None,
) -> ValidationExecutionPlan:
    if not layers or any(layer not in VALIDATION_LAYERS for layer in layers):
        raise ValueError("validation layers must be a non-empty supported subset")
    expected_order = tuple(layer for layer in VALIDATION_LAYERS if layer in layers)
    if layers != expected_order:
        raise ValueError("validation layers must preserve targeted/compatibility/full order")
    if set(fingerprints) != set(layers) or set(command_identities) != set(layers):
        raise ValueError("fingerprints and command identities must exactly cover validation layers")
    for value in (*fingerprints.values(), *command_identities.values()):
        if not _HEX_RE.fullmatch(value):
            raise ValueError("validation fingerprints and command identities must be sha256 digests")

    evidence_by_receipt = dict(reuse_evidence or {})
    if any(
        not _HEX_RE.fullmatch(key)
        or not isinstance(value, PlannerReuseEvidenceV1)
        for key, value in evidence_by_receipt.items()
    ):
        raise ValueError("reuse evidence must be keyed by receipt SHA-256")

    steps: list[ValidationStep] = []
    errors: list[str] = []
    next_layer = ""
    execution_scheduled = False
    for layer in layers:
        if execution_scheduled:
            steps.append(ValidationStep(layer, "NOT_STARTED", "prior layer must pass first"))
            continue
        exact = [
            receipt
            for receipt in receipts
            if receipt.layer == layer
            and receipt.fingerprint_digest == fingerprints[layer]
            and receipt.command_identity == command_identities[layer]
        ]
        passes = [receipt for receipt in exact if receipt.decision == "PASS"]
        if len(passes) > 1:
            errors.append(f"{layer} has duplicate exact PASS receipts")
            steps.append(ValidationStep(layer, "BLOCKED", "duplicate exact PASS receipts"))
            execution_scheduled = True
            continue
        if passes:
            receipt = passes[0]
            evidence = evidence_by_receipt.get(receipt.receipt_digest)
            if _reuse_authorized(receipt, evidence, authority_graph):
                steps.append(
                    ValidationStep(
                        layer,
                        "REUSED_UNCHANGED",
                        "exact PASS plus semantic evidence and sole-authority graph match",
                        receipt.receipt_digest,
                    )
                )
                continue
            steps.append(
                ValidationStep(
                    layer,
                    "RUN",
                    "exact PASS lacks current semantic evidence or sole-authority graph binding",
                )
            )
            next_layer = layer
            execution_scheduled = True
            continue
        reason = "matching prior FAIL is never reusable" if exact else "no exact PASS receipt"
        steps.append(ValidationStep(layer, "RUN", reason))
        next_layer = layer
        execution_scheduled = True

    if errors:
        decision = "BLOCKED"
    elif next_layer:
        decision = "READY_TO_RUN"
    else:
        decision = "REUSED_ALL"
    return ValidationExecutionPlan(
        decision,
        tuple(steps),
        next_layer,
        1 if next_layer == "full" else 0,
        tuple(errors),
    )


def _reuse_authorized(
    receipt: ValidationReceipt,
    evidence: PlannerReuseEvidenceV1 | None,
    graph: NormalizedDecisionGraphV1 | None,
) -> bool:
    return bool(
        evidence is not None
        and evidence.eligible_for_kernel
        and evidence.planner_receipt_digest == receipt.receipt_digest
        and graph is not None
        and graph.decision is DecisionStatus.PASS
        and graph.authoritative_decision_path_count == 1
        and graph.duplicate_rule_owner_count == 0
        and evidence.authority_graph_digest == graph.graph_digest
    )
