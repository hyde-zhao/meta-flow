"""ValidationPolicyV2 的唯一语义 owner；纯函数、无 I/O、无持久写。"""

from __future__ import annotations

from dataclasses import dataclass

from meta_flow.validation.receipt_identity import ReceiptIdentityV2

_LAYERS = ("targeted", "compatibility", "full")


@dataclass(frozen=True)
class ValidationLayerGraphV1:
    edges: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if tuple(sorted(set(self.edges))) != self.edges or any(
            source not in _LAYERS or target not in _LAYERS or source == target
            for source, target in self.edges
        ):
            raise ValueError("VALIDATION_LAYER_GRAPH_INVALID")
        for layer in _LAYERS:
            if layer in self.downstream(layer):
                raise ValueError("VALIDATION_LAYER_GRAPH_CYCLE")

    def downstream(self, layer: str) -> tuple[str, ...]:
        if layer not in _LAYERS:
            raise ValueError("VALIDATION_LAYER_UNKNOWN")
        reached: set[str] = set()
        frontier = [layer]
        while frontier:
            current = frontier.pop()
            for source, target in self.edges:
                if source == current and target not in reached:
                    reached.add(target)
                    frontier.append(target)
        return tuple(value for value in _LAYERS if value in reached)


@dataclass(frozen=True)
class ValidationPolicyRequestV2:
    current_identity: ReceiptIdentityV2
    candidate_receipt: ReceiptIdentityV2 | None
    layer_graph: ValidationLayerGraphV1
    full_layer_default_for_profile: bool
    planner_action: str

    def __post_init__(self) -> None:
        if (
            type(self.full_layer_default_for_profile) is not bool
            or self.planner_action not in {"REUSE", "RUN", "BLOCKED"}
        ):
            raise ValueError("VALIDATION_POLICY_REQUEST_INVALID")


@dataclass(frozen=True)
class ValidationPolicyDecisionV2:
    action: str
    affected_layers: tuple[str, ...]
    reason_codes: tuple[str, ...]
    current_identity_digest: str
    candidate_identity_digest: str
    machine_notes: tuple[str, ...]
    mutation_count: int = 0

    def __post_init__(self) -> None:
        if (
            self.action not in {"REUSE", "RUN", "BLOCKED"}
            or tuple(layer for layer in _LAYERS if layer in self.affected_layers)
            != self.affected_layers
            or tuple(sorted(set(self.reason_codes))) != self.reason_codes
            or tuple(sorted(set(self.machine_notes))) != self.machine_notes
        ):
            raise ValueError("VALIDATION_POLICY_DECISION_INVALID")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 2,
            "kind": "ValidationPolicyDecisionV2",
            "action": self.action,
            "affected_layers": list(self.affected_layers),
            "reason_codes": list(self.reason_codes),
            "current_identity_digest": self.current_identity_digest,
            "candidate_identity_digest": self.candidate_identity_digest,
            "machine_notes": list(self.machine_notes),
            "mutation_count": self.mutation_count,
        }


def _identity_drift_reasons(
    current: ReceiptIdentityV2, candidate: ReceiptIdentityV2
) -> tuple[str, ...]:
    reasons: list[str] = []
    if candidate.outcome != "PASS":
        reasons.append("RECEIPT_OUTCOME_NOT_PASS")
    if candidate.partial_mutation:
        reasons.append("PARTIAL_MUTATION")
    if candidate.source_fingerprint_digest != current.source_fingerprint_digest:
        reasons.append("SOURCE_FINGERPRINT_DRIFT")
    if candidate.profile_digest != current.profile_digest:
        reasons.append("PROFILE_DRIFT")
    if candidate.command_identity != current.command_identity:
        reasons.append("COMMAND_IDENTITY_DRIFT")
    if candidate.environment != current.environment:
        reasons.append("ENVIRONMENT_DRIFT")
    if candidate.source_manifest.digest != current.source_manifest.digest:
        reasons.append("SOURCE_MANIFEST_DRIFT")
    if candidate.provider_identity_digest != current.provider_identity_digest:
        reasons.append("PROVIDER_IDENTITY_DRIFT")
    return tuple(sorted(set(reasons)))


def _profile_notes(request: ValidationPolicyRequestV2) -> tuple[str, ...]:
    notes = [
        "FULL_LAYER_DEFAULT_FOR_PROFILE:"
        + ("true" if request.full_layer_default_for_profile else "false"),
        f"PLANNER_ACTION:{request.planner_action}",
    ]
    if not request.full_layer_default_for_profile and request.planner_action == "RUN":
        notes.append("PROFILE_DEFAULT_IS_NOT_PERMISSION")
    return tuple(sorted(notes))


def evaluate_validation_policy_v2(
    request: ValidationPolicyRequestV2,
) -> ValidationPolicyDecisionV2:
    current = request.current_identity
    candidate = request.candidate_receipt
    notes = _profile_notes(request)
    if candidate is None:
        affected = (current.layer, *request.layer_graph.downstream(current.layer))
        return ValidationPolicyDecisionV2(
            "RUN",
            tuple(layer for layer in _LAYERS if layer in affected),
            ("V2_RECEIPT_IDENTITY_MISSING",),
            current.digest,
            "",
            notes,
        )
    if candidate.layer != current.layer:
        return ValidationPolicyDecisionV2(
            "BLOCKED",
            (current.layer,),
            ("RECEIPT_LAYER_MISMATCH",),
            current.digest,
            candidate.digest,
            notes,
        )
    reasons = _identity_drift_reasons(current, candidate)
    if not reasons:
        return ValidationPolicyDecisionV2(
            "REUSE",
            (),
            (),
            current.digest,
            candidate.digest,
            notes,
        )
    affected = (current.layer, *request.layer_graph.downstream(current.layer))
    return ValidationPolicyDecisionV2(
        "RUN",
        tuple(layer for layer in _LAYERS if layer in affected),
        reasons,
        current.digest,
        candidate.digest,
        notes,
    )


def evaluate_validation_reuse_request_v2(request: object) -> tuple[str, tuple[str, ...]]:
    """消费 S02 typed request；与完整 identity policy 共用同一组 drift code。"""

    reasons: list[str] = []
    if getattr(request, "receipt_decision", "") != "PASS":
        reasons.append("RECEIPT_OUTCOME_NOT_PASS")
    if bool(getattr(request, "partial_mutation", False)):
        reasons.append("PARTIAL_MUTATION")
    comparisons = (
        (
            "SOURCE_FINGERPRINT_DRIFT",
            "receipt_fingerprint_digest",
            "current_fingerprint_digest",
        ),
        ("PROFILE_DRIFT", "receipt_profile_digest", "current_profile_digest"),
        (
            "COMMAND_IDENTITY_DRIFT",
            "receipt_command_identity",
            "current_command_identity",
        ),
        ("ENVIRONMENT_DRIFT", "receipt_environment", "current_environment"),
        (
            "SOURCE_MANIFEST_DRIFT",
            "receipt_source_manifest_digest",
            "current_source_manifest_digest",
        ),
        (
            "PROVIDER_IDENTITY_DRIFT",
            "receipt_provider_identity_digest",
            "current_provider_identity_digest",
        ),
    )
    for code, receipt_field, current_field in comparisons:
        if getattr(request, receipt_field, None) != getattr(request, current_field, None):
            reasons.append(code)
    canonical = tuple(sorted(set(reasons)))
    return ("REUSE" if not canonical else "RUN"), canonical


class ValidationPolicyV2Provider:
    """S02 `ValidationPolicyProvider` 的 concrete implementation。"""

    def evaluate_reuse(self, request: object) -> object:
        from meta_flow.work.model import ValidationReuseDecisionV2

        action, reasons = evaluate_validation_reuse_request_v2(request)
        return ValidationReuseDecisionV2(
            action,
            reasons,
            str(getattr(request, "current_provider_identity_digest", "")),
        )
