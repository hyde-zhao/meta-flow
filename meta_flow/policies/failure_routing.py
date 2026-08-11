"""Failure routing and waiver governance policies."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meta_flow.project.process_route import _resolve_runtime_path, _resolve_runtime_ref
from meta_flow.project.read_contract import ReadContextProtocol
from meta_flow.semantics import outcome

FAILURE_ROUTING_REL = Path("process/policies/FAILURE-ROUTING.json")
WAIVER_POLICY_REL = Path("process/policies/WAIVER-POLICY.json")
FAILURE_ROUTES = {
    "rework_same_story",
    "reopen_cp5_design",
    "require_user_decision",
    "create_followup_candidate",
    "escalate_runtime_high_risk",
    "block_release",
    "waive_with_risk_acceptance",
}
TERMINAL_BLOCKING_DECISIONS = frozenset({"FAIL", "BLOCKED"})
RISK_ACCEPTANCE_DECISIONS = frozenset({"PASS_WITH_RISK", "WAIVED"})
RELEASE_READY_WITH_RISK = "READY_WITH_RISK"
FAILURE_CLASSES = outcome.FAILURE_CLASSES
PROFILE_RECOVERY_MAX = {"G0": 1, "G1": 2, "G2": 2}
NON_RECOVERABLE_FAILURES = {"REAL_CONTENT_FAILURE", "PARTIAL_MUTATION", "UNKNOWN"}
DRIFT_FACTS = ("facts_digest", "scope_digest", "oid_digest", "authz_digest", "profile_digest")
VALIDATION_LAYER_ORDER = ("targeted", "compatibility", "full")


@dataclass(frozen=True)
class FailureClassification:
    failure_class: str
    reason_codes: tuple[str, ...]
    automatic_recovery_candidate: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "failure_class": self.failure_class,
            "reason_codes": list(self.reason_codes),
            "automatic_recovery_candidate": self.automatic_recovery_candidate,
        }


@dataclass(frozen=True)
class RecoveryDecision:
    decision: str
    risk_profile: str
    route_max_auto_recovery_attempts: int
    effective_max_auto_recovery_attempts: int
    attempts_completed: int
    remaining_attempts: int
    next_action: str
    reason_codes: tuple[str, ...]
    targeted_revalidation_only: bool

    @property
    def allowed(self) -> bool:
        return self.decision == "RECOVERY_ALLOWED"

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "risk_profile": self.risk_profile,
            "route_max_auto_recovery_attempts": self.route_max_auto_recovery_attempts,
            "effective_max_auto_recovery_attempts": self.effective_max_auto_recovery_attempts,
            "attempts_completed": self.attempts_completed,
            "remaining_attempts": self.remaining_attempts,
            "next_action": self.next_action,
            "reason_codes": list(self.reason_codes),
            "targeted_revalidation_only": self.targeted_revalidation_only,
        }


@dataclass(frozen=True)
class SliceFailureRoute:
    decision: str
    failure_class: str
    failed_layer: str
    current_slice_id: str
    next_action: str
    invalidated_layers: tuple[str, ...]
    reopened_slices: tuple[str, ...]
    stop_downstream: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.__dict__,
            "invalidated_layers": list(self.invalidated_layers),
            "reopened_slices": list(self.reopened_slices),
        }


def route_slice_failure(
    *,
    failure_class: str,
    failed_layer: str,
    current_slice_id: str,
    fingerprint_invalidated_slices: tuple[str, ...] = (),
) -> SliceFailureRoute:
    """失败只回当前切片；显式 fingerprint closure 才能重开其他切片。"""

    if failure_class not in (*FAILURE_CLASSES, "UNKNOWN"):
        raise ValueError("unsupported failure class")
    if failed_layer not in VALIDATION_LAYER_ORDER:
        raise ValueError("unsupported validation layer")
    if not current_slice_id:
        raise ValueError("current_slice_id is required")
    invalidated = VALIDATION_LAYER_ORDER[VALIDATION_LAYER_ORDER.index(failed_layer) :]
    closure = tuple(dict.fromkeys(fingerprint_invalidated_slices))
    if failure_class == "CHECK_HARNESS_ERROR":
        return SliceFailureRoute(
            "RETRY_LAYER",
            failure_class,
            failed_layer,
            current_slice_id,
            "repair_harness_then_rerun_failed_layer",
            (failed_layer,),
            (),
            True,
        )
    if failure_class == "PARTIAL_MUTATION":
        return SliceFailureRoute(
            "RECOVERY_REQUIRED",
            failure_class,
            failed_layer,
            current_slice_id,
            "inspect_then_explicit_resume_or_rollback",
            invalidated,
            (),
            True,
        )
    if failure_class == "UNKNOWN":
        return SliceFailureRoute(
            "BLOCKED",
            failure_class,
            failed_layer,
            current_slice_id,
            "classify_failure_before_retry",
            invalidated,
            (),
            True,
        )
    reopened = tuple(dict.fromkeys((current_slice_id, *closure)))
    return SliceFailureRoute(
        "REWORK_CURRENT_SLICE",
        failure_class,
        failed_layer,
        current_slice_id,
        (
            "repair_schema_in_current_slice"
            if failure_class == "DETERMINISTIC_SCHEMA_REPAIR"
            else "repair_content_in_current_slice"
        ),
        invalidated,
        reopened,
        True,
    )


def classify_failure(facts: Mapping[str, Any]) -> FailureClassification:
    """把失败事实稳定归入四类；证据不充分时失败关闭为 UNKNOWN。"""

    if facts.get("partial_mutation") or facts.get("mutation_receipts"):
        return FailureClassification(
            "PARTIAL_MUTATION",
            ("PARTIAL_MUTATION_OBSERVED",),
            False,
        )
    if facts.get("real_content_failure") or facts.get("contract_failure") or facts.get("semantic_failure"):
        return FailureClassification(
            "REAL_CONTENT_FAILURE",
            ("CONTENT_OR_CONTRACT_FAILURE",),
            False,
        )
    if (
        facts.get("deterministic_schema_repair")
        and facts.get("repair_path_in_scope")
        and facts.get("before_digest_matches")
    ):
        return FailureClassification(
            "DETERMINISTIC_SCHEMA_REPAIR",
            ("DETERMINISTIC_REPAIR_PROVEN",),
            True,
        )
    if facts.get("check_harness_error") and facts.get("semantic_digest_unchanged"):
        return FailureClassification(
            "CHECK_HARNESS_ERROR",
            ("HARNESS_ERROR_WITH_UNCHANGED_SEMANTICS",),
            True,
        )
    return FailureClassification(
        "UNKNOWN",
        ("FAILURE_CLASSIFICATION_INSUFFICIENT",),
        False,
    )


def _policy_value(route_policy: Mapping[str, Any], key: str, default: Any = None) -> Any:
    recovery = route_policy.get("recovery")
    if isinstance(recovery, Mapping) and key in recovery:
        return recovery[key]
    return route_policy.get(key, default)


def _budget_allows_recovery(
    *,
    risk_profile: str,
    remaining_budget: Mapping[str, int | None],
    recovery_cost: Mapping[str, int],
    pending_required_check_groups: int,
) -> tuple[bool, tuple[str, ...]]:
    reasons: list[str] = []
    for dimension in ("reads", "writes", "tokens"):
        remaining = remaining_budget.get(dimension)
        cost = int(recovery_cost.get(dimension, 0))
        if remaining is None or int(remaining) < cost:
            reasons.append(f"{dimension.upper()}_BUDGET_INSUFFICIENT")
    remaining_checks = remaining_budget.get("check_groups")
    recovery_checks = int(recovery_cost.get("check_groups", 0))
    required_checks = recovery_checks
    if risk_profile == "G0":
        required_checks += pending_required_check_groups
    if remaining_checks is None or int(remaining_checks) < required_checks:
        reasons.append("CHECK_GROUP_BUDGET_INSUFFICIENT")
    return not reasons, tuple(reasons)


def evaluate_recovery(
    *,
    failure_class: str,
    route_policy: Mapping[str, Any],
    attempts_completed: int,
    baseline_facts: Mapping[str, Any],
    current_facts: Mapping[str, Any],
    remaining_budget: Mapping[str, int | None],
    recovery_cost: Mapping[str, int],
    pending_required_check_groups: int = 0,
) -> RecoveryDecision:
    """消费 route policy 计算有效恢复上限，不自行重新判定 Work profile。"""

    if attempts_completed < 0 or pending_required_check_groups < 0:
        raise ValueError("attempt and pending check counts must be non-negative")
    risk_profile = str(_policy_value(route_policy, "risk_profile", "")).upper()
    expected_max = PROFILE_RECOVERY_MAX.get(risk_profile)
    try:
        route_max = int(_policy_value(route_policy, "max_auto_recovery_attempts", -1))
    except (TypeError, ValueError):
        route_max = -1
    reasons: list[str] = []
    effective_max = 0
    next_action = "require_user_decision"

    if expected_max is None or route_max != expected_max:
        reasons.append("PROFILE_ROUTE_CONFLICT")
    elif failure_class not in FAILURE_CLASSES:
        reasons.append("FAILURE_CLASSIFICATION_UNKNOWN")
    elif failure_class in NON_RECOVERABLE_FAILURES:
        reasons.append(f"{failure_class}_AUTOMATIC_RECOVERY_FORBIDDEN")
        next_action = "preserve_partial_and_stop" if failure_class == "PARTIAL_MUTATION" else "rework_content"
    else:
        drifted = [
            key
            for key in DRIFT_FACTS
            if baseline_facts.get(key) != current_facts.get(key)
        ]
        if drifted:
            reasons.extend(f"{key.upper()}_DRIFT" for key in drifted)
            next_action = "replan_or_reclassify"
        else:
            budget_ok, budget_reasons = _budget_allows_recovery(
                risk_profile=risk_profile,
                remaining_budget=remaining_budget,
                recovery_cost=recovery_cost,
                pending_required_check_groups=pending_required_check_groups,
            )
            if not budget_ok:
                reasons.extend(budget_reasons)
                next_action = "stop_budget_blocked"
            else:
                effective_max = route_max
                next_action = "rerun_original_check_group"

    remaining_attempts = max(effective_max - attempts_completed, 0)
    allowed = effective_max > 0 and remaining_attempts > 0
    if not allowed and not reasons and attempts_completed >= effective_max:
        reasons.append("AUTO_RECOVERY_LIMIT_REACHED")
        next_action = "stop_recovery_loop"
    return RecoveryDecision(
        decision="RECOVERY_ALLOWED" if allowed else "RECOVERY_BLOCKED",
        risk_profile=risk_profile,
        route_max_auto_recovery_attempts=route_max,
        effective_max_auto_recovery_attempts=effective_max,
        attempts_completed=attempts_completed,
        remaining_attempts=remaining_attempts,
        next_action=next_action,
        reason_codes=tuple(reasons),
        targeted_revalidation_only=risk_profile in {"G0", "G1"},
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in _as_list(value) if str(item)]


def _normalize_text(value: Any) -> str:
    text = str(value or "").lower()
    return re.sub(r"[^a-z0-9_]+", "_", text)


def failure_routing_path(project_root: Path) -> Path:
    return _resolve_runtime_ref(project_root, FAILURE_ROUTING_REL.as_posix())


def waiver_policy_path(project_root: Path) -> Path:
    return _resolve_runtime_ref(project_root, WAIVER_POLICY_REL.as_posix())


def default_failure_routing_policy() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "routes": {
            "rework_same_story": {
                "description": "实现或验证失败，但 Story 范围仍然成立，回到同一 Story 的 CP6/CP7 返工。",
                "creates": ["rework_packet"],
                "updates": ["STORY-LEDGER"],
                "invalidates": ["current_cp_result", "downstream_verify_packet"],
                "next_allowed_stage": "CP6",
            },
            "reopen_cp5_design": {
                "description": "失败来自 Story 设计证据不足或契约不清，回到 CP5 设计证据。",
                "creates": ["question_ledger_entry", "design_delta_or_lld_update"],
                "updates": ["STORY-LEDGER", "QUESTION-LEDGER"],
                "invalidates": ["CP6_packet", "CP7_packet", "current_cp_result"],
                "next_allowed_stage": "CP5",
            },
            "require_user_decision": {
                "description": "需要用户确认 scope/security/runtime/risk decision 后才能继续。",
                "creates": ["human_decision_item"],
                "updates": ["GATE-LEDGER"],
                "invalidates": ["current_cp_result"],
                "next_allowed_stage": "human_gate",
            },
            "create_followup_candidate": {
                "description": "当前交付可收敛，但剩余问题必须进入 follow-up candidate，不自动创建正式 CR。",
                "creates": ["followup_candidate"],
                "updates": ["CR-LEDGER"],
                "invalidates": [],
                "next_allowed_stage": "CP8",
            },
            "escalate_runtime_high_risk": {
                "description": "触碰 runtime / credential / trading / publish 等边界，强制升级高风险门禁。",
                "creates": ["runtime_authorization_decision_item"],
                "updates": ["GATE-LEDGER", "AUTHZ policy refs"],
                "invalidates": ["current_gate_profile", "current_context_pack"],
                "next_allowed_stage": "CP3",
            },
            "block_release": {
                "description": "发布阻断，不能进入 READY / READY_WITH_RISK。",
                "creates": ["release_blocker"],
                "updates": ["GATE-LEDGER", "CHECKPOINT-LEDGER"],
                "invalidates": ["CP8_release_context"],
                "next_allowed_stage": "blocked",
            },
            "waive_with_risk_acceptance": {
                "description": "可豁免检查项，但必须有 scope / expiry / approval_ref，并强制风险接受状态。",
                "creates": ["waiver_record", "risk_acceptance_item"],
                "updates": ["GATE-LEDGER", "CHECKPOINT-LEDGER"],
                "invalidates": [],
                "next_allowed_stage": "CP8",
            },
        },
        "severity_route_requirements": {
            "BLOCKER": "required",
            "HIGH": "required",
            "MEDIUM": "recommended",
            "LOW": "optional",
            "INFO": "optional",
        },
    }


def default_waiver_policy() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "required_fields": [
            "waiver_id",
            "applies_to",
            "scope",
            "expires_at",
            "approval_ref",
            "forces_release_status",
        ],
        "applies_to_required_fields": ["checkpoint", "check_item_id"],
        "non_waivable": {
            "categories": [
                "unauthorized_runtime_access",
                "credential_secret_exposure",
                "missing_dispatch_evidence",
                "runtime_high_risk_forbidden_path_touched",
                "missing_runtime_high_risk_human_gate",
                "missing_read_expansion_log",
                "missing_evidence",
                "forbidden_path_high_risk",
                "false_capability_claim",
            ],
            "name_patterns": [
                "unauthorized_runtime",
                "credential",
                "secret",
                "missing_dispatch",
                "dispatch_evidence",
                "runtime_high_risk_forbidden",
                "missing_human_gate",
                "missing_read_expansion",
                "read_expansion_refs",
                "evidence_does_not_exist",
                "forbidden_path",
                "runtime_ready_claim",
                "not_authorized",
            ],
        },
        "forces_release_status_values": ["READY_WITH_RISK", "NOT_READY"],
        "ready_with_risk_requires": ["risk_refs", "approval_ref", "scope", "expires_at"],
        "non_waivable_decisions": ["FAIL", "BLOCKED", "NOT_READY"],
    }


def load_failure_routing_policy(
    project_root: Path,
    *,
    read_context: ReadContextProtocol | None = None,
) -> dict[str, Any]:
    path = failure_routing_path(project_root.resolve())
    if read_context is None or not path.is_file():
        data = _read_json(path)
    else:
        payload = read_context.read_json(FAILURE_ROUTING_REL.as_posix())
        data = payload if isinstance(payload, dict) else {}
    return data or default_failure_routing_policy()


def load_waiver_policy(
    project_root: Path,
    *,
    read_context: ReadContextProtocol | None = None,
) -> dict[str, Any]:
    path = waiver_policy_path(project_root.resolve())
    if read_context is None or not path.is_file():
        data = _read_json(path)
    else:
        payload = read_context.read_json(WAIVER_POLICY_REL.as_posix())
        data = payload if isinstance(payload, dict) else {}
    return data or default_waiver_policy()


def write_default_failure_routing_policy(project_root: Path, *, force: bool = False) -> Path:
    path = failure_routing_path(project_root.resolve())
    if path.exists() and not force:
        return path
    _write_json(path, default_failure_routing_policy())
    return path


def write_default_waiver_policy(project_root: Path, *, force: bool = False) -> Path:
    path = waiver_policy_path(project_root.resolve())
    if path.exists() and not force:
        return path
    _write_json(path, default_waiver_policy())
    return path


def validate_failure_routing_policy(
    project_root: Path,
    *,
    read_context: ReadContextProtocol | None = None,
) -> list[str]:
    errors: list[str] = []
    data = load_failure_routing_policy(project_root, read_context=read_context)
    if data.get("schema_version") != 1:
        errors.append("FAILURE-ROUTING schema_version must be 1")
    routes = data.get("routes")
    if not isinstance(routes, dict) or not routes:
        return ["FAILURE-ROUTING routes must be a non-empty object"]
    missing_routes = sorted(FAILURE_ROUTES - set(routes))
    for route in missing_routes:
        errors.append(f"missing required failure route: {route}")
    for route_name, route in routes.items():
        if route_name not in FAILURE_ROUTES:
            errors.append(f"unknown failure route: {route_name}")
        if not isinstance(route, dict):
            errors.append(f"{route_name} must be an object")
            continue
        for field in ("creates", "updates", "invalidates", "next_allowed_stage"):
            if field not in route:
                errors.append(f"{route_name} missing {field}")
        for list_field in ("creates", "updates", "invalidates"):
            if list_field in route and not isinstance(route[list_field], list):
                errors.append(f"{route_name}.{list_field} must be a list")
        if not str(route.get("next_allowed_stage") or ""):
            errors.append(f"{route_name}.next_allowed_stage must be non-empty")
    return errors


def validate_waiver_policy(
    project_root: Path,
    *,
    read_context: ReadContextProtocol | None = None,
) -> list[str]:
    errors: list[str] = []
    data = load_waiver_policy(project_root, read_context=read_context)
    if data.get("schema_version") != 1:
        errors.append("WAIVER-POLICY schema_version must be 1")
    for field in ("required_fields", "applies_to_required_fields", "non_waivable", "forces_release_status_values"):
        if field not in data:
            errors.append(f"WAIVER-POLICY missing {field}")
    required = set(_string_list(data.get("required_fields")))
    for field in ("waiver_id", "applies_to", "scope", "expires_at", "approval_ref", "forces_release_status"):
        if field not in required:
            errors.append(f"WAIVER-POLICY required_fields missing {field}")
    non_waivable = data.get("non_waivable") or {}
    if not isinstance(non_waivable, dict):
        errors.append("WAIVER-POLICY non_waivable must be an object")
    else:
        if not _string_list(non_waivable.get("categories")):
            errors.append("WAIVER-POLICY non_waivable.categories must be non-empty")
        if not _string_list(non_waivable.get("name_patterns")):
            errors.append("WAIVER-POLICY non_waivable.name_patterns must be non-empty")
    return errors


def route_names(
    project_root: Path,
    *,
    read_context: ReadContextProtocol | None = None,
) -> set[str]:
    routes = load_failure_routing_policy(
        project_root,
        read_context=read_context,
    ).get("routes") or {}
    if isinstance(routes, dict) and routes:
        return set(str(route) for route in routes)
    return set(FAILURE_ROUTES)


def validate_failure_routes_for_result(
    project_root: Path,
    result: dict[str, Any],
    *,
    read_context: ReadContextProtocol | None = None,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    policy_errors = validate_failure_routing_policy(
        project_root,
        read_context=read_context,
    )
    if policy_errors:
        errors.extend(f"failure routing policy: {error}" for error in policy_errors)
    routes = route_names(project_root, read_context=read_context)
    requirements = (
        load_failure_routing_policy(
            project_root,
            read_context=read_context,
        ).get("severity_route_requirements")
        or {}
    )
    for index, item in enumerate(_as_list(result.get("items")), 1):
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "")
        severity = str(item.get("severity") or "")
        route = str(item.get("route_on_fail") or "")
        if route and route not in routes:
            errors.append(f"item {index}: route_on_fail must be one of {', '.join(sorted(routes))}: {route}")
        requirement = str(requirements.get(severity) or "")
        if status in {"FAIL", "BLOCKED"} and requirement == "required" and not route:
            errors.append(f"item {index}: {severity} {status} requires route_on_fail")
        elif status in {"FAIL", "BLOCKED"} and requirement == "recommended" and not route:
            warnings.append(f"item {index}: {severity} {status} should include route_on_fail")
    return errors, warnings


def _waiver_records(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for entry in _as_list(result.get("waivers")):
        if isinstance(entry, dict):
            waiver_id = str(entry.get("waiver_id") or entry.get("id") or "")
            if waiver_id:
                records[waiver_id] = entry
    return records


def is_non_waivable_item(
    project_root: Path,
    item: dict[str, Any],
    *,
    read_context: ReadContextProtocol | None = None,
) -> bool:
    policy = load_waiver_policy(project_root, read_context=read_context)
    non_waivable = policy.get("non_waivable") or {}
    categories = {_normalize_text(category) for category in _string_list(non_waivable.get("categories"))}
    patterns = [_normalize_text(pattern) for pattern in _string_list(non_waivable.get("name_patterns"))]
    category = _normalize_text(item.get("category"))
    if category in categories:
        return True
    text = _normalize_text(" ".join(str(item.get(field) or "") for field in ("id", "name", "notes")))
    return any(pattern and pattern in text for pattern in patterns)


def _validate_waiver_record(
    project_root: Path,
    waiver_id: str,
    waiver: dict[str, Any],
    *,
    read_context: ReadContextProtocol | None = None,
) -> list[str]:
    errors: list[str] = []
    policy = load_waiver_policy(project_root, read_context=read_context)
    for field in _string_list(policy.get("required_fields")):
        if not waiver.get(field):
            errors.append(f"waiver {waiver_id}: missing required field: {field}")
    applies_to = waiver.get("applies_to") or {}
    if not isinstance(applies_to, dict):
        errors.append(f"waiver {waiver_id}: applies_to must be an object")
        applies_to = {}
    for field in _string_list(policy.get("applies_to_required_fields")):
        if not applies_to.get(field):
            errors.append(f"waiver {waiver_id}: applies_to missing required field: {field}")
    status = str(waiver.get("forces_release_status") or "")
    allowed_statuses = set(_string_list(policy.get("forces_release_status_values")))
    if status and status not in allowed_statuses:
        errors.append(f"waiver {waiver_id}: invalid forces_release_status: {status}")
    if status == RELEASE_READY_WITH_RISK:
        for field in _string_list(policy.get("ready_with_risk_requires")):
            if not waiver.get(field):
                errors.append(f"waiver {waiver_id}: READY_WITH_RISK requires {field}")
    return errors


def validate_waivers_for_result(
    project_root: Path,
    result: dict[str, Any],
    *,
    read_context: ReadContextProtocol | None = None,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    policy_errors = validate_waiver_policy(
        project_root,
        read_context=read_context,
    )
    if policy_errors:
        errors.extend(f"waiver policy: {error}" for error in policy_errors)
    waivers = _waiver_records(result)
    waiver_ids_used: set[str] = set()
    decision = str(result.get("decision") or "")
    release_decision = str(result.get("release_decision") or "")
    for index, item in enumerate(_as_list(result.get("items")), 1):
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "")
        waiver_ref = str(item.get("waiver_ref") or "")
        if status == "WAIVED":
            if is_non_waivable_item(
                project_root,
                item,
                read_context=read_context,
            ):
                errors.append(f"item {index}: non-waivable check cannot be WAIVED: {item.get('id') or '-'}")
            if not waiver_ref:
                errors.append(f"item {index}: WAIVED requires waiver_ref")
                continue
            waiver_ids_used.add(waiver_ref)
            waiver = waivers.get(waiver_ref)
            if not waiver:
                errors.append(f"item {index}: waiver_ref not found in result.waivers: {waiver_ref}")
                continue
            errors.extend(
                _validate_waiver_record(
                    project_root,
                    waiver_ref,
                    waiver,
                    read_context=read_context,
                )
            )
            forced = str(waiver.get("forces_release_status") or "")
            if forced == RELEASE_READY_WITH_RISK and decision == "PASS" and release_decision != RELEASE_READY_WITH_RISK:
                errors.append(f"item {index}: waiver {waiver_ref} forces READY_WITH_RISK; decision cannot be silent PASS")
        elif waiver_ref:
            warnings.append(f"item {index}: waiver_ref is set but status is not WAIVED")
        if (
            is_non_waivable_item(
                project_root,
                item,
                read_context=read_context,
            )
            and status in {"FAIL", "BLOCKED"}
            and decision in RISK_ACCEPTANCE_DECISIONS
        ):
            errors.append(f"item {index}: non-waivable failure cannot use risk-acceptance decision {decision}")
    for waiver_id, waiver in waivers.items():
        if waiver_id not in waiver_ids_used:
            warnings.append(f"waiver record is not referenced by any WAIVED item: {waiver_id}")
            errors.extend(
                _validate_waiver_record(
                    project_root,
                    waiver_id,
                    waiver,
                    read_context=read_context,
                )
            )
    return errors, warnings


def validate_result_governance(
    project_root: Path,
    result: dict[str, Any],
    *,
    read_context: ReadContextProtocol | None = None,
) -> tuple[list[str], list[str]]:
    route_errors, route_warnings = validate_failure_routes_for_result(
        project_root,
        result,
        read_context=read_context,
    )
    waiver_errors, waiver_warnings = validate_waivers_for_result(
        project_root,
        result,
        read_context=read_context,
    )
    return [*route_errors, *waiver_errors], [*route_warnings, *waiver_warnings]


def _load_result(project_root: Path, path: Path) -> dict[str, Any]:
    result_ref = path.as_posix()
    try:
        resolved = _resolve_runtime_path(project_root, path)
    except ValueError as exc:
        raise SystemExit(f"{result_ref} cannot be resolved: {exc}") from exc
    if not resolved.is_file():
        raise SystemExit(f"{result_ref} is not a readable result file")
    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{result_ref} invalid JSON: {exc}") from exc
    except OSError as exc:
        raise SystemExit(f"{result_ref} cannot be read: {exc.strerror or 'I/O error'}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"{result_ref} must contain a JSON object")
    return data


def _print_failure_help() -> None:
    print(
        "usage: meta-flow failure <policy-check|route-check> [options]\n\n"
        "Commands:\n"
        "  policy-check  Validate FAILURE-ROUTING.json.\n"
        "  route-check   Validate route_on_fail values in a CP result.\n\n"
        "Examples:\n"
        "  meta-flow failure policy-check --project-root . --write-default\n"
        "  meta-flow failure route-check --result process/checks/CP7-STORY.result.json --project-root .\n"
    )


def failure_main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if not args or args[0] in {"-h", "--help"}:
        _print_failure_help()
        return 0
    command = args[0]
    if command == "policy-check":
        parser = argparse.ArgumentParser(prog="meta-flow failure policy-check")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--write-default", action="store_true")
        parsed = parser.parse_args(args[1:])
        if parsed.write_default:
            path = write_default_failure_routing_policy(parsed.project_root)
            print(f"wrote: {path}")
        errors = validate_failure_routing_policy(parsed.project_root)
        print("Failure Routing Policy Check: " + ("FAIL" if errors else "OK"))
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    if command == "route-check":
        parser = argparse.ArgumentParser(prog="meta-flow failure route-check")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--result", dest="result_path", type=Path, required=True)
        parsed = parser.parse_args(args[1:])
        errors, warnings = validate_failure_routes_for_result(
            parsed.project_root,
            _load_result(parsed.project_root, parsed.result_path),
        )
        print("Failure Route Check: " + ("FAIL" if errors else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    raise SystemExit(f"未知 failure 命令: {command}")


def _print_waiver_help() -> None:
    print(
        "usage: meta-flow waiver <policy-check|check> [options]\n\n"
        "Commands:\n"
        "  policy-check  Validate WAIVER-POLICY.json.\n"
        "  check         Validate waiver refs, scope, expiry, approval_ref, and non-waivable checks in a CP result.\n\n"
        "Examples:\n"
        "  meta-flow waiver policy-check --project-root . --write-default\n"
        "  meta-flow waiver check --result process/checks/CP8-DELIVERY.result.json --project-root .\n"
    )


def waiver_main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if not args or args[0] in {"-h", "--help"}:
        _print_waiver_help()
        return 0
    command = args[0]
    if command == "policy-check":
        parser = argparse.ArgumentParser(prog="meta-flow waiver policy-check")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--write-default", action="store_true")
        parsed = parser.parse_args(args[1:])
        if parsed.write_default:
            path = write_default_waiver_policy(parsed.project_root)
            print(f"wrote: {path}")
        errors = validate_waiver_policy(parsed.project_root)
        print("Waiver Policy Check: " + ("FAIL" if errors else "OK"))
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    if command == "check":
        parser = argparse.ArgumentParser(prog="meta-flow waiver check")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--result", dest="result_path", type=Path, required=True)
        parsed = parser.parse_args(args[1:])
        errors, warnings = validate_waivers_for_result(
            parsed.project_root,
            _load_result(parsed.project_root, parsed.result_path),
        )
        print("Waiver Check: " + ("FAIL" if errors else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    raise SystemExit(f"未知 waiver 命令: {command}")


if __name__ == "__main__":
    raise SystemExit(failure_main(sys.argv[1:]))
