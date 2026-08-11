"""跨控制面的 outcome family 与显式边界映射。"""

from __future__ import annotations

from collections import Counter
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from meta_flow.project.onboarding_contract import canonical_digest
from meta_flow.project.process_route import _resolve_runtime_ref
from meta_flow.project.scale import load_yaml_object
from meta_flow.semantics.cr_status import (
    NATIVE_GATE_STATUSES,
    NATIVE_LIFECYCLE_STATUSES,
    NATIVE_READINESS_STATUSES,
)

OUTCOME_CANDIDATE_DISPOSITIONS_REL = Path(
    "process/docs/design/OUTCOME-CANDIDATE-DISPOSITIONS.yaml"
)
OUTCOME_CANDIDATE_SOURCE_REL = Path(
    "process/works/P4-D0-CONTROL-PLANE-AUDIT-001/results/"
    "d2-d3-product-scan-run-21.json"
)
OUTCOME_CANDIDATE_KIND = "outcome-family-mix-candidate"
OUTCOME_CANDIDATE_COUNT = 66
OUTCOME_CANDIDATE_SOURCE_DIGEST = (
    "fc62b3bf93ce73ccf5debc74c71a0f64db0d34dd4d37d424ef0bbd4568e17ddc"
)
OUTCOME_DISPOSITION_IDS = frozenset(
    {
        "canonical-owner-consumer",
        "detector-contract-aggregator",
        "intentional-typed-boundary",
        "test-or-fixture",
    }
)
_DISPOSITION_TOP_FIELDS = {
    "schema_version",
    "kind",
    "source",
    "dispositions",
    "candidates",
}
_DISPOSITION_SOURCE_FIELDS = {
    "logical_ref",
    "result_digest",
    "candidate_kind",
    "candidate_count",
}
_DISPOSITION_DEFINITION_FIELDS = {"terminal", "rationale", "enforcement"}
_DISPOSITION_CANDIDATE_FIELDS = {"finding_id", "ref", "disposition_id"}


class OutcomeFamily(StrEnum):
    """不可互换的五个 outcome family。"""

    AUTHORIZATION = "authorization"
    EXECUTION = "execution"
    LIFECYCLE = "lifecycle"
    VERIFICATION = "verification"
    RELEASE = "release"


class VerificationDisposition(StrEnum):
    """verification decision 对状态推进的语义分类。"""

    PASS_LIKE = "pass-like"
    FAILURE = "failure"
    NOT_APPLICABLE = "not-applicable"
    UNKNOWN = "unknown"


AUTHORIZATION_DECISIONS = frozenset(
    {"AUTHORIZED", "AUTHORIZATION_REQUIRED", "AUTHORIZATION_INVALID"}
)
AUTHORITY_APPLY_STATUSES = frozenset(
    {"APPLIED", "RECOVERED", "NO_CHANGE", "BLOCKED", "PARTIAL"}
)
EXECUTION_DECISIONS = frozenset({"PASS", "BLOCKED", "PARTIAL"})
GENERAL_VERIFICATION_DECISIONS = frozenset(
    {"PASS", "FAIL", "BLOCKED", "N/A", "WAIVED"}
)
CP7_VERIFICATION_DECISIONS = GENERAL_VERIFICATION_DECISIONS | frozenset(
    {"PASS_WITH_RISK", "NEEDS_REWORK", "NEEDS_DESIGN_CLARIFICATION"}
)
PASS_LIKE_VERIFICATION_DECISIONS = frozenset(
    {"PASS", "WAIVED", "PASS_WITH_RISK"}
)
FAILURE_VERIFICATION_DECISIONS = frozenset(
    {"FAIL", "BLOCKED", "NEEDS_REWORK", "NEEDS_DESIGN_CLARIFICATION"}
)
NOT_APPLICABLE_VERIFICATION_DECISIONS = frozenset({"N/A"})
RELEASE_DECISIONS = frozenset(
    {"READY", "READY_WITH_RISK", "NOT_READY", "RELEASED", "FAILED"}
)
FAILURE_CLASSES = frozenset(
    {
        "CHECK_HARNESS_ERROR",
        "DETERMINISTIC_SCHEMA_REPAIR",
        "REAL_CONTENT_FAILURE",
        "PARTIAL_MUTATION",
    }
)

AUTHORITY_APPLY_STATUS_TO_EXECUTION_DECISION = MappingProxyType(
    {
        "APPLIED": "PASS",
        "RECOVERED": "PASS",
        "NO_CHANGE": "PASS",
        "BLOCKED": "BLOCKED",
        "PARTIAL": "PARTIAL",
    }
)
FAILURE_DECISION_TO_STOP_REASONS = MappingProxyType(
    {
        "FAIL": frozenset({"blocked"}),
        "BLOCKED": frozenset(
            {"blocked", "authorization_required", "workflow_health_threshold"}
        ),
        "NEEDS_REWORK": frozenset({"needs_rework"}),
        "NEEDS_DESIGN_CLARIFICATION": frozenset(
            {"needs_design_clarification"}
        ),
    }
)
PASS_COMPATIBLE_INTERRUPT_REASONS = frozenset(
    {"authorization_required", "workflow_health_threshold"}
)
STALE_FAILURE_STOP_REASONS = frozenset(
    {"blocked", "needs_rework", "needs_design_clarification"}
)
ALL_TRANSITION_STOP_REASONS = frozenset(
    {
        "required_human_gate",
        "blocked",
        "needs_rework",
        "needs_design_clarification",
        "authorization_required",
        "workflow_health_threshold",
        "delivered",
        "no_remaining_route",
    }
)


def authority_apply_decision(status: object) -> str:
    """把 authority apply status 显式映射到 execution decision。"""

    if not isinstance(status, str):
        raise ValueError("unknown authority issue status")
    try:
        return AUTHORITY_APPLY_STATUS_TO_EXECUTION_DECISION[status]
    except KeyError as exc:
        raise ValueError("unknown authority issue status") from exc


def classify_verification_decision(value: object) -> VerificationDisposition:
    """分类 verification decision；同名的 execution decision 不隐式进入。"""

    if not isinstance(value, str):
        return VerificationDisposition.UNKNOWN
    if value in PASS_LIKE_VERIFICATION_DECISIONS:
        return VerificationDisposition.PASS_LIKE
    if value in FAILURE_VERIFICATION_DECISIONS:
        return VerificationDisposition.FAILURE
    if value in NOT_APPLICABLE_VERIFICATION_DECISIONS:
        return VerificationDisposition.NOT_APPLICABLE
    return VerificationDisposition.UNKNOWN


def transition_stop_reasons(decision: str, expected_kind: str) -> frozenset[str]:
    """返回 verification decision 可合法投影的 execution stop reasons。"""

    disposition = classify_verification_decision(decision)
    if disposition is VerificationDisposition.FAILURE:
        return FAILURE_DECISION_TO_STOP_REASONS[decision]
    if disposition is VerificationDisposition.NOT_APPLICABLE:
        return ALL_TRANSITION_STOP_REASONS
    if disposition is not VerificationDisposition.PASS_LIKE:
        return frozenset()
    reasons = set(PASS_COMPATIBLE_INTERRUPT_REASONS)
    route_reason = {
        "required_human_gate": "required_human_gate",
        "delivered": "delivered",
        "no_remaining_required_gate": "no_remaining_route",
    }.get(expected_kind)
    if route_reason:
        reasons.add(route_reason)
    return frozenset(reasons)


def validate_candidate_dispositions(project_root: Path) -> dict[str, Any]:
    """逐项复算 D7 的 66 个 mixed-outcome candidate 处置闭集。"""

    root = project_root.resolve()
    errors: list[str] = []
    try:
        disposition_path = _resolve_runtime_ref(
            root, OUTCOME_CANDIDATE_DISPOSITIONS_REL.as_posix()
        )
        source_path = _resolve_runtime_ref(root, OUTCOME_CANDIDATE_SOURCE_REL.as_posix())
    except (OSError, ValueError) as exc:
        return {
            "decision": "BLOCKED",
            "candidate_count": 0,
            "disposed_count": 0,
            "disposition_counts": {},
            "source_result_digest": "",
            "disposition_digest": "",
            "errors": [str(exc)],
        }

    for ref, path in (
        (OUTCOME_CANDIDATE_DISPOSITIONS_REL.as_posix(), disposition_path),
        (OUTCOME_CANDIDATE_SOURCE_REL.as_posix(), source_path),
    ):
        if path.is_symlink() or not path.is_file():
            errors.append(f"outcome disposition source must be a regular file: {ref}")

    payload: dict[str, Any] = {}
    source_payload: dict[str, Any] = {}
    if not errors:
        try:
            payload = load_yaml_object(disposition_path)
            source_payload = load_yaml_object(source_path)
        except (OSError, ValueError) as exc:
            errors.append(f"outcome disposition source is invalid: {exc}")

    if set(payload) != _DISPOSITION_TOP_FIELDS:
        errors.append("outcome disposition top-level fields mismatch")
    if payload.get("schema_version") != 1:
        errors.append("outcome disposition schema_version must be 1")
    if payload.get("kind") != "OutcomeCandidateDispositionSetV1":
        errors.append("outcome disposition kind mismatch")

    source = payload.get("source")
    if not isinstance(source, dict) or set(source) != _DISPOSITION_SOURCE_FIELDS:
        errors.append("outcome disposition source fields mismatch")
        source = {}
    expected_source = {
        "logical_ref": OUTCOME_CANDIDATE_SOURCE_REL.as_posix(),
        "result_digest": OUTCOME_CANDIDATE_SOURCE_DIGEST,
        "candidate_kind": OUTCOME_CANDIDATE_KIND,
        "candidate_count": OUTCOME_CANDIDATE_COUNT,
    }
    if source != expected_source:
        errors.append("outcome disposition source identity mismatch")
    if source_payload.get("result_digest") != OUTCOME_CANDIDATE_SOURCE_DIGEST:
        errors.append("D7 outcome candidate source result_digest mismatch")

    source_findings = source_payload.get("findings")
    if not isinstance(source_findings, list):
        errors.append("D7 outcome candidate source findings must be a list")
        source_findings = []
    candidates_from_source: dict[str, str] = {}
    for finding in source_findings:
        if not isinstance(finding, dict) or finding.get("kind") != OUTCOME_CANDIDATE_KIND:
            continue
        finding_id = finding.get("finding_id")
        ref = finding.get("ref")
        if not isinstance(finding_id, str) or not isinstance(ref, str):
            errors.append("D7 outcome candidate identity must be strings")
            continue
        if finding_id in candidates_from_source:
            errors.append(f"duplicate D7 outcome candidate: {finding_id}")
        candidates_from_source[finding_id] = ref
    if len(candidates_from_source) != OUTCOME_CANDIDATE_COUNT:
        errors.append(
            "D7 outcome candidate count mismatch: "
            f"{len(candidates_from_source)} != {OUTCOME_CANDIDATE_COUNT}"
        )

    definitions = payload.get("dispositions")
    if not isinstance(definitions, dict) or set(definitions) != OUTCOME_DISPOSITION_IDS:
        errors.append("outcome disposition definitions must equal the closed ID set")
        definitions = {}
    for disposition_id, definition in definitions.items():
        if not isinstance(definition, dict) or set(definition) != _DISPOSITION_DEFINITION_FIELDS:
            errors.append(f"outcome disposition definition fields mismatch: {disposition_id}")
            continue
        if definition.get("terminal") is not True:
            errors.append(f"outcome disposition must be terminal: {disposition_id}")
        for field in ("rationale", "enforcement"):
            if not isinstance(definition.get(field), str) or not definition[field]:
                errors.append(
                    f"outcome disposition {field} must be non-empty: {disposition_id}"
                )

    raw_candidates = payload.get("candidates")
    if not isinstance(raw_candidates, list):
        errors.append("outcome disposition candidates must be a list")
        raw_candidates = []
    disposed: dict[str, tuple[str, str]] = {}
    disposition_counts: Counter[str] = Counter()
    for index, candidate in enumerate(raw_candidates, start=1):
        if not isinstance(candidate, dict) or set(candidate) != _DISPOSITION_CANDIDATE_FIELDS:
            errors.append(f"outcome disposition candidate fields mismatch: {index}")
            continue
        finding_id = candidate.get("finding_id")
        ref = candidate.get("ref")
        disposition_id = candidate.get("disposition_id")
        if not all(isinstance(item, str) and item for item in (finding_id, ref, disposition_id)):
            errors.append(f"outcome disposition candidate values must be strings: {index}")
            continue
        if finding_id in disposed:
            errors.append(f"duplicate outcome disposition candidate: {finding_id}")
        disposed[finding_id] = (ref, disposition_id)
        disposition_counts[disposition_id] += 1
        if disposition_id not in OUTCOME_DISPOSITION_IDS:
            errors.append(f"unknown outcome disposition ID: {disposition_id}")

    source_ids = set(candidates_from_source)
    disposed_ids = set(disposed)
    missing = sorted(source_ids - disposed_ids)
    unknown = sorted(disposed_ids - source_ids)
    if missing:
        errors.append(f"outcome candidates missing disposition: {missing}")
    if unknown:
        errors.append(f"unknown outcome disposition candidates: {unknown}")
    for finding_id in sorted(source_ids & disposed_ids):
        if disposed[finding_id][0] != candidates_from_source[finding_id]:
            errors.append(f"outcome candidate ref mismatch: {finding_id}")
    if len(raw_candidates) != OUTCOME_CANDIDATE_COUNT:
        errors.append(
            "outcome disposed candidate count mismatch: "
            f"{len(raw_candidates)} != {OUTCOME_CANDIDATE_COUNT}"
        )

    return {
        "decision": "PASS" if not errors else "BLOCKED",
        "candidate_count": len(candidates_from_source),
        "disposed_count": len(disposed_ids & source_ids),
        "disposition_counts": dict(sorted(disposition_counts.items())),
        "source_result_digest": str(source_payload.get("result_digest") or ""),
        "disposition_digest": canonical_digest(payload) if payload else "",
        "errors": errors,
    }


def semantic_contract_payload() -> dict[str, Any]:
    """供 checker/receipt 编译器消费的稳定、可序列化合同。"""

    return {
        "schema_version": 1,
        "kind": "OutcomeBoundaryContractV1",
        "families": {
            OutcomeFamily.AUTHORIZATION.value: {
                "decisions": sorted(AUTHORIZATION_DECISIONS),
            },
            OutcomeFamily.EXECUTION.value: {
                "authority_apply_statuses": sorted(AUTHORITY_APPLY_STATUSES),
                "decisions": sorted(EXECUTION_DECISIONS),
                "stop_reasons": sorted(ALL_TRANSITION_STOP_REASONS),
            },
            OutcomeFamily.LIFECYCLE.value: {
                "lifecycle_statuses": sorted(NATIVE_LIFECYCLE_STATUSES),
                "readiness_statuses": sorted(NATIVE_READINESS_STATUSES),
                "gate_statuses": sorted(NATIVE_GATE_STATUSES),
            },
            OutcomeFamily.VERIFICATION.value: {
                "general_decisions": sorted(GENERAL_VERIFICATION_DECISIONS),
                "cp7_decisions": sorted(CP7_VERIFICATION_DECISIONS),
                "pass_like_decisions": sorted(PASS_LIKE_VERIFICATION_DECISIONS),
                "failure_decisions": sorted(FAILURE_VERIFICATION_DECISIONS),
                "not_applicable_decisions": sorted(
                    NOT_APPLICABLE_VERIFICATION_DECISIONS
                ),
            },
            OutcomeFamily.RELEASE.value: {
                "decisions": sorted(RELEASE_DECISIONS),
            },
        },
        "mappings": {
            "authority_apply_status_to_execution_decision": {
                key: value
                for key, value in sorted(
                    AUTHORITY_APPLY_STATUS_TO_EXECUTION_DECISION.items()
                )
            },
            "verification_failure_decision_to_execution_stop_reasons": {
                key: sorted(value)
                for key, value in sorted(
                    FAILURE_DECISION_TO_STOP_REASONS.items()
                )
            },
        },
        "orthogonal_failure_classes": sorted(FAILURE_CLASSES),
        "candidate_disposition_contract": {
            "logical_ref": OUTCOME_CANDIDATE_DISPOSITIONS_REL.as_posix(),
            "source_ref": OUTCOME_CANDIDATE_SOURCE_REL.as_posix(),
            "source_result_digest": OUTCOME_CANDIDATE_SOURCE_DIGEST,
            "required_candidate_count": OUTCOME_CANDIDATE_COUNT,
            "terminal_disposition_ids": sorted(OUTCOME_DISPOSITION_IDS),
        },
        "constraints": [
            "same literal in different families is not type equivalence",
            "unknown outcome literal fails closed",
            "CHECK_HARNESS_ERROR is not a verification decision",
        ],
    }


__all__ = [
    "ALL_TRANSITION_STOP_REASONS",
    "AUTHORITY_APPLY_STATUSES",
    "AUTHORITY_APPLY_STATUS_TO_EXECUTION_DECISION",
    "AUTHORIZATION_DECISIONS",
    "CP7_VERIFICATION_DECISIONS",
    "EXECUTION_DECISIONS",
    "FAILURE_CLASSES",
    "FAILURE_DECISION_TO_STOP_REASONS",
    "FAILURE_VERIFICATION_DECISIONS",
    "GENERAL_VERIFICATION_DECISIONS",
    "NOT_APPLICABLE_VERIFICATION_DECISIONS",
    "OUTCOME_CANDIDATE_COUNT",
    "OUTCOME_CANDIDATE_DISPOSITIONS_REL",
    "OUTCOME_CANDIDATE_SOURCE_DIGEST",
    "OUTCOME_CANDIDATE_SOURCE_REL",
    "OUTCOME_DISPOSITION_IDS",
    "OutcomeFamily",
    "PASS_COMPATIBLE_INTERRUPT_REASONS",
    "PASS_LIKE_VERIFICATION_DECISIONS",
    "RELEASE_DECISIONS",
    "STALE_FAILURE_STOP_REASONS",
    "VerificationDisposition",
    "authority_apply_decision",
    "classify_verification_decision",
    "semantic_contract_payload",
    "transition_stop_reasons",
    "validate_candidate_dispositions",
]
