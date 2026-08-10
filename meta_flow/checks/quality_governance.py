"""Lightweight quality, eval, and workflow metrics governance checks."""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meta_flow.checks import cp_result
from meta_flow.checks.correction import validate_correction_event
from meta_flow.context_pack import read_expansion
from meta_flow.evals.runner import parse_yaml_subset
from meta_flow.project.process_route import (
    _resolve_injected_process_ref,
    _resolve_runtime_ref,
    format_runtime_ref,
)
from meta_flow.state import event_ledger

QUALITY_MODEL_REL = Path("process/policies/QUALITY-MODEL.yaml")
EVAL_MATRIX_REL = Path("process/policies/EVAL-MATRIX.yaml")
READ_EXPANSION_REL = Path("process/state/READ-EXPANSION-LEDGER.ndjson")
READ_EXPANSION_CORRECTION_REL = Path("process/corrections/CR047-LEGACY-READ-EXPANSION.ndjson")
ALLOWED_GATES = {f"CP{index}" for index in range(9)}
ALLOWED_BLOCKING_POLICIES = {"always", "on-release", "advisory"}
DERIVED_SOURCE_NEEDLES = (
    "process/checks/*.result.json",
    "process/state/*-LEDGER.ndjson",
    "process/state/READ-EXPANSION-LEDGER.ndjson",
)
FORBIDDEN_MANUAL_SOURCE_NEEDLES = (
    "WORKFLOW-METRICS",
    "manual metrics",
    "manual_metrics",
    "dashboard",
    "agent performance ranking",
    "portfolio reporting",
)
LEDGER_TYPES = ("checkpoint", "handoff", "dispatch", "run", "gate")
QA_READINESS_FACTS = (
    "cp6_result_ready",
    "approved_design_refs_match",
    "required_fixtures_ready",
    "changed_paths_allowed",
    "consumer_authorization_ready",
    "usage_allows_mutation",
)


@dataclass(frozen=True)
class QualityRouteDecision:
    decision: str
    independent_qa: bool
    targeted_revalidation_only: bool
    same_finding_reqa_max: int
    finding_round: int
    finding_fingerprint: str
    next_action: str
    blockers: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "independent_qa": self.independent_qa,
            "targeted_revalidation_only": self.targeted_revalidation_only,
            "same_finding_reqa_max": self.same_finding_reqa_max,
            "finding_round": self.finding_round,
            "finding_fingerprint": self.finding_fingerprint,
            "next_action": self.next_action,
            "blockers": list(self.blockers),
        }


def finding_fingerprint(finding: Mapping[str, Any]) -> str:
    payload = {
        "check_id": str(finding.get("check_id") or ""),
        "normalized_contract_ref": str(
            finding.get("normalized_contract_ref") or ""
        ),
        "affected_path_set": sorted(
            str(item) for item in finding.get("affected_path_set") or []
        ),
        "root_cause_class": str(finding.get("root_cause_class") or ""),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def evaluate_quality_route(
    *,
    route_policy: Mapping[str, Any],
    readiness_facts: Mapping[str, Any],
    finding: Mapping[str, Any] | None = None,
    same_finding_rounds_completed: int = 0,
) -> QualityRouteDecision:
    """按 route policy 判定 G2 independent QA 或 G0/G1 定向复验。"""

    if same_finding_rounds_completed < 0:
        raise ValueError("same finding rounds must be non-negative")
    quality = route_policy.get("quality")
    policy = quality if isinstance(quality, Mapping) else route_policy
    risk_profile = str(policy.get("risk_profile") or "").upper()
    independent_qa = bool(policy.get("independent_qa"))
    try:
        reqa_max = int(policy.get("same_finding_reqa_max", -1))
    except (TypeError, ValueError):
        reqa_max = -1
    expected = {
        "G0": (False, 0),
        "G1": (False, 0),
        "G2": (True, 2),
    }.get(risk_profile)
    fingerprint = finding_fingerprint(finding or {}) if finding else ""
    if expected is None or (independent_qa, reqa_max) != expected:
        return QualityRouteDecision(
            "PROFILE_ROUTE_CONFLICT",
            False,
            False,
            0,
            same_finding_rounds_completed,
            fingerprint,
            "reclassify_and_rebuild_route",
            ("PROFILE_ROUTE_CONFLICT",),
        )
    if risk_profile in {"G0", "G1"}:
        if readiness_facts.get("g2_reason_present") or readiness_facts.get(
            "independent_risk_acceptance_required"
        ):
            return QualityRouteDecision(
                "RECLASSIFICATION_REQUIRED_G2",
                False,
                True,
                0,
                0,
                fingerprint,
                "reclassify_and_rebuild_route",
                ("G2_REASON_OR_RISK_ACCEPTANCE_REQUIRED",),
            )
        affected = readiness_facts.get("affected_required_check_groups") or []
        return QualityRouteDecision(
            "TARGETED_REVALIDATION",
            False,
            True,
            0,
            0,
            fingerprint,
            "rerun_affected_required_check_groups",
            () if affected else ("NO_AFFECTED_REQUIRED_CHECK_GROUPS",),
        )

    blockers = [
        fact.upper()
        for fact in QA_READINESS_FACTS
        if not readiness_facts.get(fact)
    ]
    for fact in (
        "partial_mutation",
        "blocking_design_item",
        "telemetry_budget_block",
        "route_stop_reason",
    ):
        if readiness_facts.get(fact):
            blockers.append(fact.upper())
    if blockers:
        return QualityRouteDecision(
            "NOT_READY_FOR_QA",
            True,
            False,
            reqa_max,
            same_finding_rounds_completed,
            fingerprint,
            "return_to_implementation_readiness",
            tuple(blockers),
        )
    if finding and same_finding_rounds_completed >= reqa_max:
        return QualityRouteDecision(
            "NEEDS_DESIGN_CLARIFICATION",
            True,
            False,
            reqa_max,
            same_finding_rounds_completed + 1,
            fingerprint,
            "require_user_decision",
            ("SAME_FINDING_REQA_LIMIT_REACHED",),
        )
    if finding:
        return QualityRouteDecision(
            "REQA_ALLOWED",
            True,
            False,
            reqa_max,
            same_finding_rounds_completed + 1,
            fingerprint,
            "rework_then_independent_reqa",
            (),
        )
    return QualityRouteDecision(
        "READY_FOR_QA",
        True,
        False,
        reqa_max,
        0,
        "",
        "dispatch_independent_qa",
        (),
    )


QUALITY_MODEL_TEMPLATE = """schema_version: 1
model_id: meta-flow-lightweight-quality-v1
title: Lightweight Quality Model
source_policy: derived-only
metric_derivation:
  mode: derived
  manual_truth_source: false
  allowed_sources:
    - process/checks/*.result.json
    - process/state/*-LEDGER.ndjson
    - process/state/READ-EXPANSION-LEDGER.ndjson
dimensions:
  - id: requirements_traceability
    owner: meta-pm
    gates: [CP2, CP5, CP7]
    required_evidence: [requirements_ref, scenarios_ref, story_refs, test_matrix_ref]
    derived_metrics: [cp_decision_distribution, cp_item_status_distribution]
  - id: architecture_contract
    owner: meta-se
    gates: [CP3, CP5, CP7]
    required_evidence: [hld_ref, adr_ref, feature_design_refs, design_delta_refs]
    derived_metrics: [cp_blockers, design_clarification_count]
  - id: implementation_evidence
    owner: meta-dev
    gates: [CP6, CP7]
    required_evidence: [story_return_ref, evidence_index_ref, verification_commands]
    derived_metrics: [story_return_count, run_ledger_event_count, cp_item_status_distribution]
  - id: verification_readiness
    owner: meta-qa
    gates: [CP7, CP8]
    required_evidence: [verification_report_ref, test_report_ref, review_ref]
    derived_metrics: [cp7_decision_distribution, waiver_count, blocker_count]
  - id: context_budget_governance
    owner: host-orchestrator
    gates: [CP2, CP3, CP5, CP6, CP7, CP8]
    required_evidence: [context_ref, read_expansion_refs, ledger_refs]
    derived_metrics: [read_expansion_event_count, estimated_extra_tokens, ledger_event_count]
"""


EVAL_MATRIX_TEMPLATE = """schema_version: 1
matrix_id: meta-flow-lightweight-eval-matrix-v1
quality_model_ref: process/policies/QUALITY-MODEL.yaml
cases:
  - id: eval-requirements-traceability
    quality_dimension: requirements_traceability
    eval_ref: meta-flow quality model-check
    blocking_policy: on-release
    applies_to: [CP2, CP5, CP7]
    evidence_refs: [process/checks/*.result.json, docs/product/TEST-MATRIX.md]
  - id: eval-architecture-contract
    quality_dimension: architecture_contract
    eval_ref: meta-flow quality eval-check
    blocking_policy: on-release
    applies_to: [CP3, CP5, CP7]
    evidence_refs: [docs/design/HLD.md, docs/design/ARCHITECTURE-DECISION.md, process/design-deltas/*.delta.json]
  - id: eval-implementation-evidence
    quality_dimension: implementation_evidence
    eval_ref: meta-flow story evidence-check
    blocking_policy: always
    applies_to: [CP6, CP7]
    evidence_refs: [process/returns/*.return.json, process/evidence/*.index.json, process/state/RUN-LEDGER.ndjson]
  - id: eval-verification-readiness
    quality_dimension: verification_readiness
    eval_ref: meta-flow cp result-check
    blocking_policy: always
    applies_to: [CP7, CP8]
    evidence_refs: [process/checks/*.result.json, docs/quality/TEST-REPORT.md, docs/quality/REVIEW.md]
  - id: eval-context-budget-governance
    quality_dimension: context_budget_governance
    eval_ref: meta-flow doctor workflow
    blocking_policy: advisory
    applies_to: [CP2, CP3, CP5, CP6, CP7, CP8]
    evidence_refs: [process/context/*.context.json, process/state/READ-EXPANSION-LEDGER.ndjson, process/state/*-LEDGER.ndjson]
"""


def _read_policy(path: Path) -> tuple[dict[str, Any], list[str]]:
    if not path.is_file():
        return {}, [f"policy missing: {path}"]
    text = path.read_text(encoding="utf-8")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = parse_yaml_subset(text)
    if not isinstance(parsed, dict) or not parsed:
        return {}, [f"policy is empty or unsupported YAML: {path}"]
    return parsed, []


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return [str(value)] if str(value) else []


def _as_dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _contains_forbidden_source(value: Any) -> bool:
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    lowered = text.lower()
    return any(needle.lower() in lowered for needle in FORBIDDEN_MANUAL_SOURCE_NEEDLES)


def quality_model_path(
    project_root: Path, *, process_root: Path | None = None
) -> Path:
    if process_root is not None:
        return _resolve_injected_process_ref(process_root, QUALITY_MODEL_REL.as_posix())
    return _resolve_runtime_ref(project_root, QUALITY_MODEL_REL.as_posix())


def eval_matrix_path(
    project_root: Path, *, process_root: Path | None = None
) -> Path:
    if process_root is not None:
        return _resolve_injected_process_ref(process_root, EVAL_MATRIX_REL.as_posix())
    return _resolve_runtime_ref(project_root, EVAL_MATRIX_REL.as_posix())


def write_default_quality_policies(project_root: Path, *, force: bool = False) -> list[Path]:
    root = project_root.resolve()
    outputs = [
        (quality_model_path(root), QUALITY_MODEL_TEMPLATE),
        (eval_matrix_path(root), EVAL_MATRIX_TEMPLATE),
    ]
    written: list[Path] = []
    for path, text in outputs:
        if path.exists() and not force:
            written.append(path)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written


def load_quality_model(
    project_root: Path, *, process_root: Path | None = None
) -> dict[str, Any]:
    data, _errors = _read_policy(
        quality_model_path(project_root, process_root=process_root)
    )
    return data


def load_eval_matrix(
    project_root: Path, *, process_root: Path | None = None
) -> dict[str, Any]:
    data, _errors = _read_policy(
        eval_matrix_path(project_root, process_root=process_root)
    )
    return data


def validate_quality_model(
    project_root: Path, *, process_root: Path | None = None
) -> tuple[list[str], list[str]]:
    path = quality_model_path(project_root, process_root=process_root)
    data, read_errors = _read_policy(path)
    if read_errors:
        return read_errors, []
    errors: list[str] = []
    warnings: list[str] = []

    if data.get("schema_version") != 1:
        errors.append("QUALITY-MODEL schema_version must be 1")
    if not data.get("model_id"):
        errors.append("QUALITY-MODEL model_id is required")
    if data.get("source_policy") != "derived-only":
        errors.append("QUALITY-MODEL source_policy must be derived-only")

    metric_derivation = data.get("metric_derivation")
    if not isinstance(metric_derivation, dict):
        errors.append("QUALITY-MODEL metric_derivation must be an object")
        metric_derivation = {}
    if metric_derivation.get("mode") != "derived":
        errors.append("QUALITY-MODEL metric_derivation.mode must be derived")
    if metric_derivation.get("manual_truth_source") is not False:
        errors.append("QUALITY-MODEL metric_derivation.manual_truth_source must be false")
    allowed_sources = _as_list(metric_derivation.get("allowed_sources"))
    if not allowed_sources:
        errors.append("QUALITY-MODEL metric_derivation.allowed_sources must be non-empty")
    for required in DERIVED_SOURCE_NEEDLES:
        if required not in allowed_sources:
            errors.append(f"QUALITY-MODEL allowed_sources missing derived source: {required}")
    if _contains_forbidden_source(metric_derivation):
        errors.append("QUALITY-MODEL must not define dashboard, ranking, portfolio, or manual metrics truth sources")

    dimensions = _as_dict_list(data.get("dimensions"))
    if not dimensions:
        errors.append("QUALITY-MODEL dimensions must be a non-empty list")
    seen_dimensions: set[str] = set()
    for index, dimension in enumerate(dimensions, 1):
        dimension_id = str(dimension.get("id") or "")
        if not dimension_id:
            errors.append(f"QUALITY-MODEL dimension {index} missing id")
        elif dimension_id in seen_dimensions:
            errors.append(f"QUALITY-MODEL duplicate dimension id: {dimension_id}")
        seen_dimensions.add(dimension_id)
        if not dimension.get("owner"):
            errors.append(f"QUALITY-MODEL dimension {dimension_id or index} missing owner")
        gates = _as_list(dimension.get("gates"))
        if not gates:
            errors.append(f"QUALITY-MODEL dimension {dimension_id or index} missing gates")
        for gate in gates:
            if gate not in ALLOWED_GATES:
                errors.append(f"QUALITY-MODEL dimension {dimension_id or index} has invalid gate: {gate}")
        if not _as_list(dimension.get("required_evidence")):
            errors.append(f"QUALITY-MODEL dimension {dimension_id or index} missing required_evidence")
        if not _as_list(dimension.get("derived_metrics")):
            warnings.append(f"QUALITY-MODEL dimension {dimension_id or index} has no derived_metrics")
    return errors, warnings


def validate_eval_matrix(
    project_root: Path, *, process_root: Path | None = None
) -> tuple[list[str], list[str]]:
    path = eval_matrix_path(project_root, process_root=process_root)
    data, read_errors = _read_policy(path)
    if read_errors:
        return read_errors, []
    errors: list[str] = []
    warnings: list[str] = []

    if data.get("schema_version") != 1:
        errors.append("EVAL-MATRIX schema_version must be 1")
    if not data.get("matrix_id"):
        errors.append("EVAL-MATRIX matrix_id is required")
    if data.get("quality_model_ref") != QUALITY_MODEL_REL.as_posix():
        errors.append(f"EVAL-MATRIX quality_model_ref must be {QUALITY_MODEL_REL.as_posix()}")
    if _contains_forbidden_source(data):
        errors.append("EVAL-MATRIX must not define dashboard, ranking, portfolio, or manual metrics truth sources")

    model = load_quality_model(project_root, process_root=process_root)
    model_dimension_ids = {str(item.get("id")) for item in _as_dict_list(model.get("dimensions")) if item.get("id")}
    if not model_dimension_ids:
        warnings.append("EVAL-MATRIX could not load quality model dimensions for cross-check")

    cases = _as_dict_list(data.get("cases"))
    if not cases:
        errors.append("EVAL-MATRIX cases must be a non-empty list")
    seen_cases: set[str] = set()
    for index, case in enumerate(cases, 1):
        case_id = str(case.get("id") or "")
        dimension = str(case.get("quality_dimension") or "")
        if not case_id:
            errors.append(f"EVAL-MATRIX case {index} missing id")
        elif case_id in seen_cases:
            errors.append(f"EVAL-MATRIX duplicate case id: {case_id}")
        seen_cases.add(case_id)
        if not dimension:
            errors.append(f"EVAL-MATRIX case {case_id or index} missing quality_dimension")
        elif model_dimension_ids and dimension not in model_dimension_ids:
            errors.append(f"EVAL-MATRIX case {case_id or index} references unknown quality_dimension: {dimension}")
        if not case.get("eval_ref"):
            errors.append(f"EVAL-MATRIX case {case_id or index} missing eval_ref")
        blocking_policy = str(case.get("blocking_policy") or "")
        if blocking_policy not in ALLOWED_BLOCKING_POLICIES:
            errors.append(f"EVAL-MATRIX case {case_id or index} invalid blocking_policy: {blocking_policy or '-'}")
        if not _as_list(case.get("evidence_refs")):
            errors.append(f"EVAL-MATRIX case {case_id or index} missing evidence_refs")
    return errors, warnings


def _print_check_result(label: str, errors: list[str], warnings: list[str]) -> int:
    print(f"{label}: " + ("FAIL" if errors else "OK"))
    for warning in warnings:
        print(f"- WARN: {warning}")
    for error in errors:
        print(f"- ERROR: {error}")
    return 1 if errors else 0


def run_quality_doctor(project_root: Path) -> int:
    root = project_root.resolve()
    model_errors, model_warnings = validate_quality_model(root)
    eval_errors, eval_warnings = validate_eval_matrix(root)
    model = load_quality_model(root)
    matrix = load_eval_matrix(root)
    dimensions = _as_dict_list(model.get("dimensions"))
    cases = _as_dict_list(matrix.get("cases"))

    print("Quality Doctor: " + ("FAIL" if model_errors or eval_errors else "OK"))
    print(f"project_root: {root}")
    print(f"quality_model: {QUALITY_MODEL_REL.as_posix()}")
    print(f"quality_dimensions: {len(dimensions)}")
    print(f"eval_matrix: {EVAL_MATRIX_REL.as_posix()}")
    print(f"eval_cases: {len(cases)}")
    print("manual_metrics_truth_source: none")
    for warning in [*model_warnings, *eval_warnings]:
        print(f"- WARN: {warning}")
    for error in [*model_errors, *eval_errors]:
        print(f"- ERROR: {error}")
    return 1 if model_errors or eval_errors else 0


def _load_read_expansion_corrections(root: Path) -> tuple[dict[str, str], list[str]]:
    path = _resolve_runtime_ref(root, READ_EXPANSION_CORRECTION_REL.as_posix())
    if not path.is_file():
        return {}, []
    targets: dict[str, str] = {}
    errors: list[str] = []
    chain: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{READ_EXPANSION_CORRECTION_REL.as_posix()}:{line_no}: invalid JSON: {exc}")
            continue
        findings = validate_correction_event(event, chain=chain)
        if findings:
            errors.extend(
                f"{READ_EXPANSION_CORRECTION_REL.as_posix()}:{line_no}: {finding}" for finding in findings
            )
            continue
        target = event.get("target_ref") or {}
        if target.get("namespace") != "cp-result":
            errors.append(
                f"{READ_EXPANSION_CORRECTION_REL.as_posix()}:{line_no}: target namespace must be cp-result"
            )
            continue
        target_id = str(target.get("id") or "")
        targets[target_id] = str(event.get("event_id") or "")
        chain.append(event)
    return targets, errors


def _load_cp_results(root: Path) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []
    corrected_targets, correction_errors = _load_read_expansion_corrections(root)
    errors.extend(correction_errors)
    checks_root = _resolve_runtime_ref(root, "process/checks")
    for result_path in sorted(checks_root.glob("*.result.json")):
        result_errors, result_warnings = cp_result.validate_cp_result(result_path, project_root=root)
        rel_path = format_runtime_ref(root, result_path)
        correction_id = corrected_targets.get(rel_path)
        if correction_id:
            warnings.extend(
                f"{rel_path}: legacy/unavailable read-expansion provenance retained by append-only correction "
                f"{correction_id}; original finding remains non-PASS: {error}"
                for error in result_errors
            )
        else:
            errors.extend(f"{rel_path}: {error}" for error in result_errors)
        warnings.extend(
            f"{format_runtime_ref(root, result_path)}: {warning}"
            for warning in result_warnings
        )
        try:
            results.append(cp_result.load_cp_result(result_path))
        except ValueError as exc:
            errors.append(str(exc))
    return results, errors, warnings


def _load_ledger_counts(root: Path) -> tuple[dict[str, int], list[str], list[str]]:
    counts: dict[str, int] = {}
    errors: list[str] = []
    warnings: list[str] = []
    for ledger_type in LEDGER_TYPES:
        ledger = event_ledger.ledger_path(root, ledger_type)
        events, ledger_errors = event_ledger.load_events(ledger)
        if ledger_errors and not ledger.is_file():
            warnings.extend(f"{ledger_type}: {error}" for error in ledger_errors)
            counts[ledger_type] = 0
            continue
        errors.extend(f"{ledger_type}: {error}" for error in ledger_errors)
        validate_errors, validate_warnings = event_ledger.validate_event_ledger(ledger, ledger_type=ledger_type)
        errors.extend(f"{ledger_type}: {error}" for error in validate_errors)
        warnings.extend(f"{ledger_type}: {warning}" for warning in validate_warnings)
        counts[ledger_type] = len(events)
    return counts, errors, warnings


def run_workflow_doctor(project_root: Path) -> int:
    root = project_root.resolve()
    cp_results, cp_errors, cp_warnings = _load_cp_results(root)
    ledger_counts, ledger_errors, ledger_warnings = _load_ledger_counts(root)
    read_ledger = _resolve_runtime_ref(root, READ_EXPANSION_REL.as_posix())
    read_summary = read_expansion.summarize_events(root, ledger=read_ledger)
    read_errors, read_warnings = read_expansion.validate_ledger(root, ledger=read_ledger)
    if read_errors and not read_ledger.is_file():
        read_warnings.extend(read_errors)
        read_errors = []

    decisions = collections.Counter(str(result.get("decision") or "-") for result in cp_results)
    checkpoints = collections.Counter(str(result.get("checkpoint") or result.get("checkpoint_id") or "-") for result in cp_results)
    blockers = sum(len(_as_list(result.get("blockers"))) for result in cp_results)
    item_statuses: collections.Counter[str] = collections.Counter()
    for result in cp_results:
        for item in result.get("items") or []:
            if isinstance(item, dict):
                item_statuses[str(item.get("status") or "-")] += 1

    errors = [*cp_errors, *ledger_errors, *read_errors]
    warnings = [*cp_warnings, *ledger_warnings, *read_warnings]
    print("Workflow Doctor: " + ("FAIL" if errors else "OK"))
    print(f"project_root: {root}")
    print("metrics_mode: derived-only")
    print("manual_metrics_truth_source: none")
    print(f"cp_result_files: {len(cp_results)}")
    print("cp_decisions:")
    for decision, count in sorted(decisions.items()):
        print(f"- {decision}: {count}")
    if not decisions:
        print("- none")
    print("cp_checkpoints:")
    for checkpoint, count in sorted(checkpoints.items()):
        print(f"- {checkpoint}: {count}")
    if not checkpoints:
        print("- none")
    print("cp_item_statuses:")
    for status, count in sorted(item_statuses.items()):
        print(f"- {status}: {count}")
    if not item_statuses:
        print("- none")
    print(f"cp_blockers: {blockers}")
    print("ledger_events:")
    for ledger_type in LEDGER_TYPES:
        print(f"- {ledger_type}: {ledger_counts.get(ledger_type, 0)}")
    print(f"read_expansion_events: {read_summary['event_count']}")
    print(f"estimated_extra_tokens: {read_summary['estimated_extra_tokens']}")
    print("derived_sources:")
    for source in DERIVED_SOURCE_NEEDLES:
        print(f"- {source}")
    for warning in warnings:
        print(f"- WARN: {warning}")
    for error in errors:
        print(f"- ERROR: {error}")
    return 1 if errors else 0


def _print_quality_help() -> None:
    print(
        "usage: meta-flow quality <init|model-check|eval-check> [options]\n\n"
        "Commands:\n"
        "  init         Write default quality governance policies under process/policies.\n"
        "  model-check  Validate process/policies/QUALITY-MODEL.yaml.\n"
        "  eval-check   Validate process/policies/EVAL-MATRIX.yaml against the quality model.\n\n"
        "Examples:\n"
        "  meta-flow quality init --project-root .\n"
        "  meta-flow quality model-check --project-root .\n"
        "  meta-flow quality eval-check --project-root .\n"
    )


def quality_main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if not args or args[0] in {"-h", "--help"}:
        _print_quality_help()
        return 0
    command = args[0]
    parser = argparse.ArgumentParser(prog=f"meta-flow quality {command}")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--force", action="store_true")
    parsed = parser.parse_args(args[1:])
    root = parsed.project_root.resolve()
    if command == "init":
        paths = write_default_quality_policies(root, force=parsed.force)
        for path in paths:
            print(f"wrote: {path}")
        return 0
    if command == "model-check":
        errors, warnings = validate_quality_model(root)
        return _print_check_result("Quality Model Check", errors, warnings)
    if command == "eval-check":
        errors, warnings = validate_eval_matrix(root)
        return _print_check_result("Eval Matrix Check", errors, warnings)
    raise SystemExit(f"未知 quality 命令: {command}. 目前支持: init, model-check, eval-check")


if __name__ == "__main__":
    raise SystemExit(quality_main(sys.argv[1:]))
