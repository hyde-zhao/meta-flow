"""CR lifecycle governance for Meta Flow state v2."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from meta_flow.checks import cr_tracking
from meta_flow.design import feature_registry
from meta_flow.policies import authz, route_plan
from meta_flow.project.process_route import _resolve_runtime_ref
from meta_flow.project.scale import load_yaml_object
from meta_flow.state import current

CR_LEDGER_REL = Path("process/state/CR-LEDGER.ndjson")
CR_INDEX_REL = Path("process/changes/CR-INDEX.json")
CR_SUMMARY_ROOT_REL = Path("process/changes/summaries")
CR_ARCHIVE_ROOT_REL = Path("process/archive")
IMPACT_SURFACE_RULES_REL = Path("process/project/IMPACT-SURFACE-RULES.yaml")
STATE_CURRENT_REL = Path("process/state/STATE.current.json")
CR_ID_RE = re.compile(r"CR-\d+")
FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)
ALLOWED_LIFECYCLE_STATUSES = {
    "candidate",
    "proposed",
    "active",
    "implemented",
    "verified",
    "ready",
    "closed",
    "superseded",
    "cancelled",
    "blocked",
}
FINISHED_STATUSES = {"closed", "superseded", "cancelled"}
CLOSED_GATE_STATUS = "cp8_closed"
ALLOWED_CR_TYPES = {
    "product-scope",
    "architecture",
    "feature",
    "refactor",
    "bugfix",
    "docs",
    "process",
    "runtime",
    "release",
    "experiment",
}
CR_TYPE_ALIASES = {
    "requirement-change": "product-scope",
    "architecture-realignment": "architecture",
    "implementation-gate": "feature",
    "runtime-authorization": "runtime",
    "ledger-maintenance": "process",
    "spike": "experiment",
}
IMPACT_SPLIT_FIELDS = (
    "impact_capability_refs",
    "impact_feature_refs",
    "impact_module_paths",
    "impact_policy_refs",
    "impact_process_refs",
    "impact_runtime_refs",
    "impact_data_refs",
)
OPEN_DEPENDENCY_STATUSES = {"active", "blocked", "proposed"}
GOVERNANCE_BASELINE_MARKERS = (
    "process/policies",
    "process/policy",
    "process/state",
    "process/project",
    "process/roadmap",
    "roadmap",
    "authz",
    "policy",
    "policies",
    "gate_profile",
    "gate_profiles",
    "delivery/rules",
    "agent-skill-contract",
    "directory-contract",
)
CP1_PRODUCT_BASELINE_DOCS = (
    "docs/product/use-cases.md",
    "docs/product/requirements.md",
    "docs/product/scenarios",
    "docs/product/test-matrix",
    "docs/product/story-map",
    "docs/product/mvp-scope",
    "docs/product/release-slices",
    "docs/product/backlog",
)
CP1_FULL_REQUIRED_CHECKS = (
    "use_case_completeness",
    "requirements_traceability",
    "scenario_coverage",
    "story_map_alignment",
    "mvp_scope_alignment",
)
CP1_LIGHTWEIGHT_REQUIRED_CHECKS = (
    "cr_tracking",
    "impact_surface",
    "affected_use_case_refs",
)
ARCHIVE_BACKUP_PATH_MARKERS = (
    "process/archive/",
    "process/backups/",
    "process/backup/",
    "/archive/",
    "/backups/",
    "/backup/",
)
HOUSEKEEPING_CR_MARKERS = (
    "housekeeping",
    "archive",
    "backup",
    "retention",
    "cleanup",
    "clean-up",
    "ledger-compaction",
    "state-slim",
)


@dataclass(frozen=True)
class CRRecord:
    cr_id: str
    cr_type: str
    title: str
    status: str
    readiness: str
    gate_status: str
    gate_profile: str
    full_ref: str
    summary_ref: str
    conflict_keys: list[str]
    impact_surface: list[str]
    impact_capability_refs: list[str]
    impact_feature_refs: list[str]
    impact_module_paths: list[str]
    impact_policy_refs: list[str]
    impact_process_refs: list[str]
    impact_runtime_refs: list[str]
    impact_data_refs: list[str]
    impact_capability_resolution: dict[str, Any]
    authz_policy_refs: list[str]
    risk_refs: list[str]
    goal_ref: str
    goal_statement: str
    user_goal_impact: str
    split_rationale: str
    why_not_merge_with_parent: str
    why_not_story_or_task: str
    approval_focus: str
    decision_burden: str
    approve_effect: str
    reject_effect: str
    not_authorized_by_approve: list[str]
    product_baseline_refresh_required: bool
    required_phase: str
    required_agent: str
    required_gate: str
    block_story_decomposition_until: str
    affected_product_docs: list[str]
    affected_use_cases: list[str]
    routing_design_ref: str
    required_evidence: list[str]
    required_capabilities: list[str]


def now_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class AggregateCompletionProjector:
    """Project one persisted PASS aggregate through CR ledger and current-state writers."""

    def __init__(self, *, project_root: Path, expected_state_updated_at: str) -> None:
        self.project_root = project_root.resolve()
        self.expected_state_updated_at = expected_state_updated_at

    def project_aggregate(self, *, result: Any, receipt: Any) -> dict[str, Any]:
        if not getattr(result, "cr_id", "") or not getattr(receipt, "aggregate_id", ""):
            raise ValueError("aggregate projection receipt identity is missing")
        if getattr(result, "aggregate_id", "") != getattr(receipt, "aggregate_id", ""):
            raise ValueError("aggregate projection result/receipt identity mismatch")
        if (
            str(getattr(result, "overall", "")) != "PASS"
            or getattr(result, "terminal", False) is not True
            or str(getattr(result, "projection_decision", "")) != "ELIGIBLE"
            or getattr(receipt, "readback_valid", False) is not True
            or getattr(receipt, "current_selected", False) is not True
        ):
            raise ValueError("aggregate projection requires persisted/readback current 2/2 PASS")
        cr_id = str(getattr(result, "cr_id", "") or "")
        aggregate_ref = str(getattr(receipt, "aggregate_ref", "") or "")
        writer_receipts: dict[str, Any] = {}
        try:
            state_receipt = current.project_aggregate_completion(
                self.project_root,
                cr_id=cr_id,
                aggregate_id=str(result.aggregate_id),
                aggregate_ref=aggregate_ref,
                payload_digest=str(result.payload_digest),
                expected_updated_at=self.expected_state_updated_at,
            )
        except (OSError, RuntimeError, ValueError) as error:
            return {
                "status": "failed",
                "writer_receipts": writer_receipts,
                "error": f"state_current:{type(error).__name__}:{error}",
            }
        writer_receipts["state_current"] = state_receipt
        existing_event = next(
            (
                event
                for event in load_ledger_events(self.project_root)
                if event.get("event") == "aggregate_projection"
                and event.get("id") == cr_id
                and event.get("aggregate_ref") == aggregate_ref
            ),
            None,
        )
        try:
            if existing_event is None:
                ledger_path = append_ledger_event(
                    self.project_root,
                    {
                        "event": "aggregate_projection",
                        "id": cr_id,
                        "status": "active",
                        "aggregate_id": result.aggregate_id,
                        "aggregate_ref": aggregate_ref,
                        "payload_digest": result.payload_digest,
                        "projection_disposition": state_receipt.get("status"),
                        "projected_at": now_utc(),
                    },
                )
                ledger_receipt = {
                    "status": "projected",
                    "ledger_ref": _rel(self.project_root, ledger_path),
                }
            else:
                ledger_receipt = {
                    "status": "idempotent-existing",
                    "ledger_ref": CR_LEDGER_REL.as_posix(),
                }
        except (OSError, RuntimeError, ValueError) as error:
            return {
                "status": "partial",
                "writer_receipts": writer_receipts,
                "error": f"cr_ledger:{type(error).__name__}:{error}",
            }
        writer_receipts["cr_ledger"] = ledger_receipt
        return {
            "status": "complete",
            "writer_receipts": writer_receipts,
        }


def _strip_scalar(value: Any) -> str:
    raw = str(value).strip()
    if " #" in raw:
        raw = raw.split(" #", 1)[0].rstrip()
    return raw.strip().strip("`").strip('"').strip("'")


def _frontmatter(text: str) -> str:
    match = FRONTMATTER_RE.match(text)
    return match.group(1) if match else ""


def _replace_frontmatter(text: str, frontmatter: str) -> str:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return f"---\n{frontmatter.rstrip()}\n---\n\n{text}"
    return f"---\n{frontmatter.rstrip()}\n---\n" + text[match.end() :]


def parse_frontmatter(text: str) -> dict[str, Any]:
    values: dict[str, Any] = {}
    current_list_key = ""
    for line in _frontmatter(text).splitlines():
        if line.startswith("  - ") and current_list_key:
            values.setdefault(current_list_key, []).append(_strip_scalar(line.strip()[2:]))
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        current_list_key = key
        values[key] = _strip_scalar(value) if value else []
    return values


def _format_frontmatter_value(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def update_frontmatter_fields(path: Path, updates: dict[str, str]) -> bool:
    """Update scalar frontmatter fields, preserving unrelated body content."""

    clean_updates = {key: value for key, value in updates.items() if value != ""}
    if not clean_updates:
        return False
    text = path.read_text(encoding="utf-8")
    frontmatter = _frontmatter(text)
    lines = frontmatter.splitlines()
    seen: set[str] = set()
    next_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if ":" not in stripped or stripped.startswith("#") or line.startswith((" ", "\t")):
            next_lines.append(line)
            continue
        key = stripped.split(":", 1)[0].strip()
        if key in clean_updates:
            indent = line[: len(line) - len(line.lstrip())]
            next_lines.append(f"{indent}{key}: {_format_frontmatter_value(clean_updates[key])}")
            seen.add(key)
        else:
            next_lines.append(line)
    for key, value in clean_updates.items():
        if key not in seen:
            next_lines.append(f"{key}: {_format_frontmatter_value(value)}")
    updated = _replace_frontmatter(text, "\n".join(next_lines))
    if updated == text:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def parse_inline_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_strip_scalar(item) for item in value if _strip_scalar(item)]
    raw = _strip_scalar(value)
    if not raw or raw in {"[]", "{}"}:
        return []
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1].strip()
    return [item.strip().strip('"').strip("'") for item in raw.split(",") if item.strip()]


def parse_bool(value: Any) -> bool:
    raw = _strip_scalar(value).lower()
    return raw in {"true", "yes", "y", "1"}


def normalize_cr_type(value: Any) -> str:
    raw = _strip_scalar(value)
    if not raw:
        return "feature"
    return CR_TYPE_ALIASES.get(raw, raw)


def _rel(project_root: Path, path: Path) -> str:
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return path.as_posix()


def _cr_id_from_path(path: Path) -> str:
    match = CR_ID_RE.search(path.name)
    return match.group(0) if match else ""


def _resolve_capability_refs(
    project_root: Path, refs: list[str], *, mode: str = "audit"
) -> dict[str, Any]:
    return feature_registry.resolve_refs(project_root, refs, kind="capability", mode=mode)


def _normalized_capability_refs(resolution: dict[str, Any]) -> list[str]:
    normalized: list[str] = []
    for result in resolution.get("results", []):
        if (
            isinstance(result, dict)
            and result.get("status") == "resolved"
            and result.get("canonical_id")
        ):
            normalized.append(str(result["canonical_id"]))
    return normalized


def _capability_blockers(resolution: dict[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    mode = str(resolution.get("mode") or "audit")
    for result in resolution.get("results", []):
        if not isinstance(result, dict):
            continue
        status = result.get("status")
        is_blocker = status in {"unresolved", "conflict"} or (
            mode == "enforce" and status == "deprecated"
        )
        if is_blocker:
            blockers.append(
                {
                    "input_ref": result.get("input_ref", ""),
                    "status": status or "",
                    "code": result.get("code", ""),
                    "severity": result.get("severity", ""),
                    "canonical_id": result.get("canonical_id", ""),
                    "deprecated_by": result.get("deprecated_by", ""),
                    "candidates": result.get("candidates", []),
                }
            )
    return blockers


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        unique_values.append(value)
    return unique_values


def _impact_split_payload(record: CRRecord) -> dict[str, list[str]]:
    return {
        "impact_capability_refs": record.impact_capability_refs,
        "impact_feature_refs": record.impact_feature_refs,
        "impact_module_paths": record.impact_module_paths,
        "impact_policy_refs": record.impact_policy_refs,
        "impact_process_refs": record.impact_process_refs,
        "impact_runtime_refs": record.impact_runtime_refs,
        "impact_data_refs": record.impact_data_refs,
    }


def _categorized_legacy_impact(
    impact_surface: list[str], *, project_root: Path | None = None
) -> dict[str, list[str]]:
    derived: dict[str, list[str]] = {field: [] for field in IMPACT_SPLIT_FIELDS}
    for value in impact_surface:
        category = _legacy_impact_category(value, project_root=project_root)
        if category is not None:
            field, normalized = category
            derived[field].append(normalized)
    return {key: _unique(values) for key, values in derived.items()}


def _legacy_impact_category(
    value: str, *, project_root: Path | None = None
) -> tuple[str, str] | None:
    builtin = _builtin_legacy_impact_category(value, include_generic_module=False)
    if builtin is not None:
        return builtin
    if project_root is None:
        return _builtin_legacy_impact_category(value, include_generic_module=True)
    project_rule = _project_legacy_impact_category(project_root, value)
    if project_rule is not None:
        return project_rule
    return _builtin_legacy_impact_category(value, include_generic_module=True)


def _builtin_legacy_impact_category(
    value: str, *, include_generic_module: bool = True
) -> tuple[str, str] | None:
    lowered = value.lower()
    if value.startswith("CAP-") or lowered.startswith("capability:"):
        return "impact_capability_refs", value.split(":", 1)[-1]
    if value.startswith("FEAT-") or lowered.startswith("feature:"):
        return "impact_feature_refs", value.split(":", 1)[-1]
    if value.startswith("NO_") or value.startswith("AUTHZ-") or lowered.startswith("policy:"):
        return "impact_policy_refs", value.split(":", 1)[-1]
    if lowered.startswith("process") or lowered.startswith("workflow:"):
        return "impact_process_refs", value.split(":", 1)[-1]
    if any(marker in lowered for marker in ("runtime", "trading", "live", "publish")):
        return "impact_runtime_refs", value
    if (
        lowered.startswith("data:")
        or lowered.startswith("data/")
        or "/data" in lowered
        or "data_" in lowered
    ):
        return "impact_data_refs", value.split(":", 1)[-1]
    if include_generic_module and ("/" in value or value.endswith(".py")):
        return "impact_module_paths", value
    return None


def _project_legacy_impact_category(project_root: Path, value: str) -> tuple[str, str] | None:
    rules_path = _resolve_runtime_ref(project_root, IMPACT_SURFACE_RULES_REL.as_posix())
    if not rules_path.is_file():
        return None
    data = load_yaml_object(rules_path)
    if data.get("schema_version") != 1:
        raise ValueError(f"{IMPACT_SURFACE_RULES_REL.as_posix()} schema_version must be 1")
    rules = data.get("rules", [])
    if not isinstance(rules, list):
        raise ValueError(f"{IMPACT_SURFACE_RULES_REL.as_posix()} rules must be a list")
    for index, rule in enumerate(rules, start=1):
        field, normalized = _apply_impact_rule(rule, value, index=index)
        if field:
            return field, normalized
    return None


def _apply_impact_rule(rule: Any, value: str, *, index: int) -> tuple[str, str]:
    if not isinstance(rule, dict):
        raise ValueError(f"{IMPACT_SURFACE_RULES_REL.as_posix()} rules[{index}] must be an object")
    target_field = str(rule.get("target_field") or "")
    if target_field not in IMPACT_SPLIT_FIELDS:
        raise ValueError(
            f"{IMPACT_SURFACE_RULES_REL.as_posix()} rules[{index}].target_field is invalid: {target_field}"
        )
    match = str(rule.get("match") or "prefix")
    pattern = str(rule.get("pattern") or "")
    if not pattern:
        raise ValueError(
            f"{IMPACT_SURFACE_RULES_REL.as_posix()} rules[{index}].pattern must be non-empty"
        )
    matched = False
    if match == "prefix":
        matched = value.startswith(pattern)
    elif match == "exact":
        matched = value == pattern
    elif match == "contains":
        matched = pattern in value
    elif match == "suffix":
        matched = value.endswith(pattern)
    elif match == "regex":
        try:
            matched = re.search(pattern, value) is not None
        except re.error as exc:
            raise ValueError(
                f"{IMPACT_SURFACE_RULES_REL.as_posix()} rules[{index}].pattern invalid regex: {exc}"
            ) from exc
    else:
        raise ValueError(
            f"{IMPACT_SURFACE_RULES_REL.as_posix()} rules[{index}].match is invalid: {match}"
        )
    if not matched:
        return "", ""
    normalized = value
    if rule.get("strip_prefix") is True and value.startswith(pattern):
        normalized = value[len(pattern) :]
    if isinstance(rule.get("replacement"), str) and rule.get("replacement"):
        normalized = str(rule["replacement"])
    return target_field, normalized


def _uncategorized_legacy_impact(
    impact_surface: list[str], *, project_root: Path | None = None
) -> list[str]:
    return _unique(
        [
            value
            for value in impact_surface
            if _legacy_impact_category(value, project_root=project_root) is None
        ]
    )


def _impact_followup_candidates(
    cr_id: str, uncategorized_legacy: list[str]
) -> list[dict[str, Any]]:
    if not uncategorized_legacy:
        return []
    return [
        {
            "candidate_id": f"{cr_id}-IMPACT-UNCATEGORIZED",
            "kind": "manual-impact-classification",
            "summary": f"{cr_id}: manually classify uncategorized legacy impact_surface values",
            "input_refs": uncategorized_legacy,
            "recommended_action": "Add explicit impact_* split fields or extend classification rules in a follow-up Story.",
            "write_policy": "candidate-only",
        }
    ]


def _merge_impact_fields(
    base: dict[str, list[str]], extra: dict[str, list[str]]
) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {}
    for field in IMPACT_SPLIT_FIELDS:
        merged[field] = _unique([*base.get(field, []), *extra.get(field, [])])
    return merged


def _effective_impact_fields(
    record: CRRecord, *, project_root: Path | None = None
) -> dict[str, list[str]]:
    return _merge_impact_fields(
        _impact_split_payload(record),
        _categorized_legacy_impact(record.impact_surface, project_root=project_root),
    )


def _extract_section_lines(text: str, heading: str) -> list[str]:
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip() == heading:
            start = index + 1
            break
    if start is None:
        return []
    collected: list[str] = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        stripped = line.strip()
        if stripped:
            collected.append(stripped)
    return collected


def _section_summary(text: str, heading: str, *, max_items: int = 3) -> list[str]:
    values: list[str] = []
    for line in _extract_section_lines(text, heading):
        if line.startswith("|") or line.startswith(">") or line.startswith("["):
            continue
        cleaned = line.lstrip("- ").strip()
        if cleaned:
            values.append(cleaned)
        if len(values) >= max_items:
            break
    return values


def _body_text(text: str) -> str:
    return FRONTMATTER_RE.sub("", text, count=1)


def _record_required_evidence(record: CRRecord, text: str = "") -> list[str]:
    inferred = authz.infer_required_evidence_from_text(
        " ".join(
            [
                record.title,
                record.goal_statement,
                record.user_goal_impact,
                " ".join(record.impact_data_refs),
                " ".join(record.impact_runtime_refs),
                _body_text(text),
            ]
        )
    )
    return _unique([*record.required_evidence, *inferred])


def collect_scope_authz_findings(
    record: CRRecord, *, text: str = ""
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return blocking conflicts and review findings for CR scope/authz consistency."""

    required_evidence = _record_required_evidence(record, text)
    authz_caps = authz.normalize_capability_aliases(
        record.authz_policy_refs + record.not_authorized_by_approve
    )
    required_from_evidence = authz.required_capabilities_for_evidence(required_evidence)
    forbidden = set(authz_caps["forbidden"])
    allowed = set(authz_caps["allowed"])
    required_capabilities = set(record.required_capabilities)
    blockers: list[dict[str, Any]] = []
    needs_review: list[dict[str, Any]] = []

    explicit_overlap = sorted(required_capabilities.intersection(forbidden))
    if explicit_overlap:
        blockers.append(
            {
                "level": "L1",
                "code": "explicit_scope_authz_conflict",
                "required_capabilities": explicit_overlap,
                "authz_policy_refs": record.authz_policy_refs,
                "decision": "BLOCKED",
            }
        )

    direct_evidence_overlap = sorted(set(required_from_evidence["direct"]).intersection(forbidden))
    prerequisite_overlap = sorted(
        set(required_from_evidence["prerequisites"]).intersection(forbidden)
        - set(direct_evidence_overlap)
    )
    if direct_evidence_overlap:
        blockers.append(
            {
                "level": "L2",
                "code": "required_evidence_forbidden_by_authz",
                "required_evidence": required_evidence,
                "required_capabilities": direct_evidence_overlap,
                "authz_policy_refs": record.authz_policy_refs,
                "decision": "BLOCKED",
            }
        )
    if prerequisite_overlap:
        needs_review.append(
            {
                "level": "L2",
                "code": "required_evidence_prerequisite_authz_conflict",
                "required_evidence": required_evidence,
                "required_capabilities": prerequisite_overlap,
                "authz_policy_refs": record.authz_policy_refs,
                "decision": "NEEDS_REVIEW",
            }
        )

    high_risk_evidence = {"real_lake_validation", "historical_backtest", "oos_walkforward"}
    if (
        high_risk_evidence.intersection(required_evidence)
        and "real_lake_read" not in allowed
        and "real_lake_read" not in forbidden
    ):
        needs_review.append(
            {
                "level": "L3",
                "code": "high_risk_validation_authz_boundary_not_explicit",
                "required_evidence": sorted(high_risk_evidence.intersection(required_evidence)),
                "decision": "NEEDS_REVIEW",
            }
        )
    if required_from_evidence["unknown"]:
        needs_review.append(
            {
                "level": "L3",
                "code": "unknown_required_evidence_kind",
                "required_evidence": required_from_evidence["unknown"],
                "decision": "NEEDS_REVIEW",
            }
        )
    return blockers, needs_review


def _governance_dependency_values(
    record: CRRecord, *, project_root: Path | None = None
) -> list[str]:
    effective = _effective_impact_fields(record, project_root=project_root)
    values: list[str] = []
    values.extend(record.conflict_keys)
    values.extend(record.impact_surface)
    values.extend(record.authz_policy_refs)
    for field in IMPACT_SPLIT_FIELDS:
        values.extend(effective.get(field, []))
    return _unique([str(value) for value in values if str(value)])


def _governance_markers(values: list[str]) -> set[str]:
    markers: set[str] = set()
    for value in values:
        lowered = value.lower()
        for marker in GOVERNANCE_BASELINE_MARKERS:
            if marker in lowered:
                markers.add(marker)
    return markers


def _is_open_governance_baseline_cr(record: CRRecord, *, project_root: Path | None = None) -> bool:
    if record.status not in OPEN_DEPENDENCY_STATUSES or record.cr_type != "process":
        return False
    return bool(
        _governance_markers(_governance_dependency_values(record, project_root=project_root))
    )


def collect_governance_dependency_findings(
    project_root: Path,
    target: CRRecord,
) -> list[dict[str, Any]]:
    """Return warning-only findings for CRs depending on open governance baseline changes."""

    if target.status not in OPEN_DEPENDENCY_STATUSES:
        return []
    target_values = _governance_dependency_values(target, project_root=project_root)
    target_markers = _governance_markers(target_values)
    if not target_markers:
        return []
    findings: list[dict[str, Any]] = []
    for cr_id, path in discover_formal_crs(project_root).items():
        if cr_id == target.cr_id:
            continue
        other = record_from_cr_file(project_root, path)
        if not _is_open_governance_baseline_cr(other, project_root=project_root):
            continue
        other_values = _governance_dependency_values(other, project_root=project_root)
        other_markers = _governance_markers(other_values)
        marker_overlap = sorted(target_markers.intersection(other_markers))
        direct_overlap = sorted(set(target_values).intersection(other_values))
        if marker_overlap or direct_overlap:
            findings.append(
                {
                    "code": "open_governance_dependency_needs_review",
                    "decision": "NEEDS_REVIEW",
                    "blocking": False,
                    "current_cr": target.cr_id,
                    "governance_cr": other.cr_id,
                    "governance_ref": other.full_ref,
                    "marker_overlap": marker_overlap,
                    "direct_overlap": direct_overlap,
                    "reason": "open governance baseline CR may change policy/authz/roadmap/process-state assumptions",
                }
            )
    return findings


def classify_cp1_review_profile(record: CRRecord) -> dict[str, Any]:
    """Classify how much CP1 use-case completeness review the CR needs."""

    product_doc_values = [value.lower() for value in record.affected_product_docs]
    impact_values = [
        value.lower()
        for value in record.impact_surface + record.impact_process_refs + record.impact_module_paths
    ]
    product_baseline_touched = record.product_baseline_refresh_required or any(
        any(marker in value for marker in CP1_PRODUCT_BASELINE_DOCS)
        for value in [*product_doc_values, *impact_values]
    )
    if product_baseline_touched:
        return {
            "profile": "full",
            "decision": "FULL_CP1_REQUIRED",
            "required_checks": list(CP1_FULL_REQUIRED_CHECKS),
            "reason": "product baseline docs or product_baseline_refresh_required indicate use-case completeness must be rechecked",
        }
    if record.affected_use_cases:
        return {
            "profile": "lightweight_existing_use_case_extension",
            "decision": "LIGHTWEIGHT_CP1",
            "required_checks": list(CP1_LIGHTWEIGHT_REQUIRED_CHECKS),
            "affected_use_cases": record.affected_use_cases,
            "reason": "CR extends existing use-case refs without refreshing the product baseline",
        }
    if record.cr_type in {"process", "refactor", "bugfix", "docs", "runtime", "release"}:
        return {
            "profile": "not_applicable",
            "decision": "CP1_NOT_REQUIRED",
            "required_checks": ["cr_tracking", "impact_surface"],
            "reason": "CR type does not change user scenarios or product baseline by default",
        }
    return {
        "profile": "standard",
        "decision": "STANDARD_CP1_REVIEW",
        "required_checks": list(CP1_FULL_REQUIRED_CHECKS),
        "reason": "CR may affect product behavior but does not provide enough evidence for lightweight CP1",
    }


def _archive_backup_refs(record: CRRecord, *, project_root: Path | None = None) -> list[str]:
    effective = _effective_impact_fields(record, project_root=project_root)
    values: list[str] = []
    values.extend(record.impact_surface)
    for field in (
        "impact_module_paths",
        "impact_process_refs",
        "impact_data_refs",
    ):
        values.extend(effective.get(field, []))
    refs: list[str] = []
    for value in values:
        normalized = str(value).strip().replace("\\", "/")
        lowered = normalized.lower()
        if any(marker in lowered for marker in ARCHIVE_BACKUP_PATH_MARKERS):
            refs.append(normalized)
    return _unique(refs)


def _is_housekeeping_cr(record: CRRecord) -> bool:
    values = [record.title, record.cr_type, *record.conflict_keys, *record.impact_surface]
    lowered = " ".join(str(value).lower() for value in values if str(value))
    return record.cr_type == "process" and any(
        marker in lowered for marker in HOUSEKEEPING_CR_MARKERS
    )


def collect_archive_isolation_findings(
    record: CRRecord,
    *,
    project_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Return warning-only findings for archive/backups paths mixed into business CR scope."""

    if record.status not in OPEN_DEPENDENCY_STATUSES:
        return []
    archive_refs = _archive_backup_refs(record, project_root=project_root)
    if not archive_refs or _is_housekeeping_cr(record):
        return []
    return [
        {
            "code": "archive_backup_scope_needs_isolation",
            "decision": "NEEDS_REVIEW",
            "blocking": False,
            "current_cr": record.cr_id,
            "archive_refs": archive_refs,
            "reason": "archive/backups paths should be isolated in housekeeping CRs or explicitly justified",
        }
    ]


def _first_section_summary(text: str, heading: str) -> str:
    values = _section_summary(text, heading, max_items=1)
    return values[0] if values else ""


def discover_formal_crs(project_root: Path) -> dict[str, Path]:
    root = _resolve_runtime_ref(project_root, "process/changes")
    if not root.is_dir():
        return {}
    crs: dict[str, Path] = {}
    for path in sorted(root.glob("CR-*.md")):
        if "FOLLOW-UP" in path.name:
            continue
        cr_id = _cr_id_from_path(path)
        if cr_id:
            crs[cr_id] = path
    return crs


def record_from_cr_file(project_root: Path, path: Path) -> CRRecord:
    text = path.read_text(encoding="utf-8")
    fields = parse_frontmatter(text)
    cr_id = fields.get("cr_id") or _cr_id_from_path(path)
    if not cr_id:
        raise ValueError(f"无法从 CR 文件识别 cr_id: {path}")
    status = fields.get("lifecycle_status") or fields.get("status") or "active"
    if status == "open":
        status = "active"
    summary_ref = (CR_SUMMARY_ROOT_REL / f"{cr_id}.summary.json").as_posix()
    impact_capability_refs = parse_inline_list(fields.get("impact_capability_refs", ""))
    capability_resolution = _resolve_capability_refs(
        project_root, impact_capability_refs, mode="audit"
    )
    return CRRecord(
        cr_id=cr_id,
        cr_type=normalize_cr_type(fields.get("cr_type") or fields.get("cr_kind") or "feature"),
        title=fields.get("title") or path.stem,
        status=status,
        readiness=fields.get("readiness_status") or "not_ready",
        gate_status=fields.get("gate_status") or "not_started",
        gate_profile=fields.get("gate_profile") or "",
        full_ref=_rel(project_root, path),
        summary_ref=summary_ref,
        conflict_keys=parse_inline_list(fields.get("conflict_keys", "")),
        impact_surface=parse_inline_list(fields.get("impact_surface", "")),
        impact_capability_refs=impact_capability_refs,
        impact_feature_refs=parse_inline_list(fields.get("impact_feature_refs", "")),
        impact_module_paths=parse_inline_list(fields.get("impact_module_paths", "")),
        impact_policy_refs=parse_inline_list(fields.get("impact_policy_refs", "")),
        impact_process_refs=parse_inline_list(fields.get("impact_process_refs", "")),
        impact_runtime_refs=parse_inline_list(fields.get("impact_runtime_refs", "")),
        impact_data_refs=parse_inline_list(fields.get("impact_data_refs", "")),
        impact_capability_resolution=capability_resolution,
        authz_policy_refs=parse_inline_list(fields.get("authz_policy_refs", "")),
        risk_refs=parse_inline_list(fields.get("risk_refs", "")),
        goal_ref=fields.get("goal_ref", ""),
        goal_statement=fields.get("goal_statement", ""),
        user_goal_impact=fields.get("user_goal_impact", ""),
        split_rationale=fields.get("split_rationale", ""),
        why_not_merge_with_parent=fields.get("why_not_merge_with_parent", ""),
        why_not_story_or_task=fields.get("why_not_story_or_task", ""),
        approval_focus=fields.get("approval_focus", ""),
        decision_burden=fields.get("decision_burden", ""),
        approve_effect=fields.get("approve_effect", ""),
        reject_effect=fields.get("reject_effect", ""),
        not_authorized_by_approve=parse_inline_list(fields.get("not_authorized_by_approve", "")),
        product_baseline_refresh_required=parse_bool(
            fields.get("product_baseline_refresh_required", "")
        ),
        required_phase=fields.get("required_phase", ""),
        required_agent=fields.get("required_agent", ""),
        required_gate=fields.get("required_gate", ""),
        block_story_decomposition_until=fields.get("block_story_decomposition_until", ""),
        affected_product_docs=parse_inline_list(fields.get("affected_product_docs", "")),
        affected_use_cases=parse_inline_list(fields.get("affected_use_cases", "")),
        routing_design_ref=fields.get("routing_design_ref", ""),
        required_evidence=parse_inline_list(fields.get("required_evidence", "")),
        required_capabilities=parse_inline_list(fields.get("required_capabilities", "")),
    )


def summary_from_cr_file(
    project_root: Path, path: Path, *, readiness: str | None = None
) -> dict[str, Any]:
    record = record_from_cr_file(project_root, path)
    text = path.read_text(encoding="utf-8")
    summary = {
        "id": record.cr_id,
        "cr_type": record.cr_type,
        "title": record.title,
        "status": record.status,
        "readiness": readiness or record.readiness,
        "gate_status": record.gate_status,
        "gate_profile": record.gate_profile,
        "decision": "pending",
        "scope_summary": _section_summary(text, "## 变更描述") or [record.title],
        "impact_surface": record.impact_surface,
        **_impact_split_payload(record),
        "impact_capability_resolution": record.impact_capability_resolution,
        "impact_capability_normalized": _normalized_capability_refs(
            record.impact_capability_resolution
        ),
        "conflict_keys": record.conflict_keys,
        "remaining_risks": record.risk_refs,
        "followup_candidates": [],
        "authz_policy_refs": record.authz_policy_refs,
        "goal_ref": record.goal_ref,
        "goal_statement": record.goal_statement or _first_section_summary(text, "## 目标影响摘要"),
        "user_goal_impact": record.user_goal_impact,
        "split_rationale": record.split_rationale or _first_section_summary(text, "## 拆分理由"),
        "why_not_merge_with_parent": record.why_not_merge_with_parent,
        "why_not_story_or_task": record.why_not_story_or_task,
        "approval_focus": record.approval_focus,
        "decision_burden": record.decision_burden,
        "approve_effect": record.approve_effect or _first_section_summary(text, "## approve 后果"),
        "reject_effect": record.reject_effect,
        "not_authorized_by_approve": record.not_authorized_by_approve
        or _section_summary(text, "## 不授权范围"),
        "product_baseline_refresh_required": record.product_baseline_refresh_required,
        "required_phase": record.required_phase,
        "required_agent": record.required_agent,
        "required_gate": record.required_gate,
        "block_story_decomposition_until": record.block_story_decomposition_until,
        "affected_product_docs": record.affected_product_docs,
        "affected_use_cases": record.affected_use_cases,
        "routing_design_ref": record.routing_design_ref,
        "required_evidence": _record_required_evidence(record, text),
        "required_capabilities": record.required_capabilities,
        "full_ref": record.full_ref,
        "evidence_index_ref": (
            CR_ARCHIVE_ROOT_REL / record.cr_id / "evidence-index.json"
        ).as_posix(),
        "updated_at": now_utc(),
    }
    blockers, needs_review = collect_scope_authz_findings(record, text=text)
    summary["scope_authz_consistency"] = {
        "decision": "BLOCKED" if blockers else "NEEDS_REVIEW" if needs_review else "PASS",
        "blockers": blockers,
        "needs_review": needs_review,
    }
    governance_findings = collect_governance_dependency_findings(project_root, record)
    summary["governance_dependency_review"] = {
        "decision": "NEEDS_REVIEW" if governance_findings else "PASS",
        "findings": governance_findings,
    }
    archive_findings = collect_archive_isolation_findings(record, project_root=project_root)
    summary["cp1_review_profile"] = classify_cp1_review_profile(record)
    summary["archive_isolation_review"] = {
        "decision": "NEEDS_REVIEW" if archive_findings else "PASS",
        "findings": archive_findings,
    }
    return summary


def write_summary(project_root: Path, cr_id: str, summary: dict[str, Any]) -> Path:
    path = _resolve_runtime_ref(project_root, CR_SUMMARY_ROOT_REL.as_posix()) / f"{cr_id}.summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    # CR summaries are hot/warm routing objects with a 4 KiB budget.  Compact
    # JSON preserves the schema while avoiding formatting-only budget drift.
    path.write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return path


def write_evidence_index(project_root: Path, cr_id: str, summary: dict[str, Any]) -> Path:
    path = _resolve_runtime_ref(project_root, CR_ARCHIVE_ROOT_REL.as_posix()) / cr_id / "evidence-index.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "cr_id": cr_id,
        "summary_ref": (CR_SUMMARY_ROOT_REL / f"{cr_id}.summary.json").as_posix(),
        "full_ref": summary.get("full_ref"),
        "evidence_refs": [],
        "created_at": now_utc(),
    }
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def append_ledger_event(project_root: Path, event: dict[str, Any]) -> Path:
    path = _resolve_runtime_ref(project_root, CR_LEDGER_REL.as_posix())
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def load_ledger_events(project_root: Path) -> list[dict[str, Any]]:
    path = _resolve_runtime_ref(project_root, CR_LEDGER_REL.as_posix())
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no} invalid JSON: {exc}") from exc
    return events


def build_index(project_root: Path) -> dict[str, Any]:
    project_root = project_root.resolve()
    items: list[dict[str, Any]] = []
    formal_ids = set(discover_formal_crs(project_root))
    for cr_id, path in discover_formal_crs(project_root).items():
        record = record_from_cr_file(project_root, path)
        summary_path = project_root / record.summary_ref
        items.append(
            {
                "id": cr_id,
                "cr_type": record.cr_type,
                "title": record.title,
                "status": record.status,
                "lifecycle_status": record.status,
                "readiness": record.readiness,
                "readiness_status": record.readiness,
                "gate_status": record.gate_status,
                "gate_profile": record.gate_profile,
                "full_ref": record.full_ref,
                "formal_cr_path": record.full_ref,
                "summary_ref": record.summary_ref if summary_path.is_file() else "",
                "goal_ref": record.goal_ref,
                "goal_statement": record.goal_statement,
                "approval_focus": record.approval_focus,
                "decision_burden": record.decision_burden,
                "conflict_keys": record.conflict_keys,
                "impact_surface": record.impact_surface,
                **_impact_split_payload(record),
                "impact_capability_resolution": record.impact_capability_resolution,
                "impact_capability_normalized": _normalized_capability_refs(
                    record.impact_capability_resolution
                ),
                "authz_policy_refs": record.authz_policy_refs,
                "risk_refs": record.risk_refs,
                "product_baseline_refresh_required": record.product_baseline_refresh_required,
                "required_phase": record.required_phase,
                "required_agent": record.required_agent,
                "required_gate": record.required_gate,
                "block_story_decomposition_until": record.block_story_decomposition_until,
                "affected_product_docs": record.affected_product_docs,
                "affected_use_cases": record.affected_use_cases,
                "routing_design_ref": record.routing_design_ref,
                "required_evidence": _record_required_evidence(
                    record, path.read_text(encoding="utf-8")
                ),
                "required_capabilities": record.required_capabilities,
            }
        )

    # Candidate rows may intentionally precede a formal CR file.  Rebuilding the
    # canonical JSON index must not silently discard those follow-up decisions.
    # Only non-formal candidate rows are preserved; every formal CR is always
    # regenerated from its source-owned Markdown record above.
    existing_path = _resolve_runtime_ref(project_root, CR_INDEX_REL.as_posix())
    if existing_path.is_file():
        try:
            existing_index = json.loads(existing_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{existing_path} invalid JSON: {exc}") from exc
        for existing in existing_index.get("items", []):
            if not isinstance(existing, dict):
                continue
            item_id = str(existing.get("id", ""))
            lifecycle = str(existing.get("lifecycle_status") or existing.get("status") or "")
            formal_ref = str(existing.get("formal_cr_path") or existing.get("full_ref") or "")
            if item_id in formal_ids or lifecycle != "candidate" or formal_ref:
                continue
            items.append(existing)
    return {
        "schema_version": 1,
        "generated_at": now_utc(),
        "items": sorted(items, key=lambda item: item["id"]),
    }


def write_index(project_root: Path) -> Path:
    project_root = project_root.resolve()
    path = _resolve_runtime_ref(project_root, CR_INDEX_REL.as_posix())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(build_index(project_root), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def load_index(project_root: Path) -> dict[str, Any]:
    path = _resolve_runtime_ref(project_root, CR_INDEX_REL.as_posix())
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} invalid JSON: {exc}") from exc


def _write_bootstrap_cr_file(
    project_root: Path,
    *,
    cr_id: str,
    title: str,
    scope: str,
    gate_status: str,
    readiness: str,
) -> Path:
    if not re.fullmatch(r"CR-\d{3,}", cr_id):
        raise ValueError("bootstrap CR id must use CR-xxx naming, for example CR-001")
    path = _resolve_runtime_ref(project_root, f"process/changes/{cr_id}.md")
    if path.exists():
        raise FileExistsError(f"CR already exists: {path}")
    created_at = now_utc()
    text = f"""---
cr_id: "{cr_id}"
cr_type: "process"
title: "{title}"
lifecycle_status: "active"
readiness_status: "{readiness}"
gate_status: "{gate_status}"
gate_profile: "standard"
conflict_keys: ["bootstrap", "adoption-readiness"]
impact_surface: ["process", "workspace", "state", "context", "human-gate"]
authz_policy_refs: ["NO_CREDENTIAL_READ", "NO_RUNTIME", "NO_PRODUCTION_WRITE", "NO_TRADING"]
risk_refs: []
created_at: "{created_at}"
created_by: "meta-flow cr bootstrap"
---

# {cr_id} {title}

## 变更描述

{scope}

## 不授权范围

- credentials / secret / account read
- runtime / SaaS / production write
- trading / live / publish
- CR-033 runtime trace follow-up activation

## 启动约束

- Formal CR IDs must use `CR-xxx`; `MF-xxx` is historical alias only.
- Business remediation starts only after CP0/context/human gate readiness is reviewed.
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _update_current_active_change(project_root: Path, cr_id: str, context_ref: str) -> None:
    current.update_current_state(
        project_root,
        {
            "active_change": cr_id,
            "active_context_ref": context_ref,
            "current_phase": "init",
            "next_action": {
                "type": "cp0_ready",
                "text": f"Review CP0 bootstrap readiness for {cr_id}, then launch the first human gate.",
            },
            "updated_at": now_utc(),
        },
        actor="meta_flow.workflow.cr_lifecycle",
        reason="bootstrap active change",
    )


def _write_cp0_result(project_root: Path, cr_id: str, context_ref: str) -> Path:
    result_path = _resolve_runtime_ref(
        project_root, f"process/checks/CP0-{cr_id}-BOOTSTRAP.result.json"
    )
    result = {
        "schema_version": 1,
        "checkpoint": "CP0",
        "cr_id": cr_id,
        "decision": "PASS",
        "context_ref": context_ref,
        "evidence_ref": "",
        "dispatch_refs": [],
        "items": [
            {
                "id": "CP0-BS-01",
                "name": "workspace/state/bootstrap artifacts exist",
                "status": "PASS",
                "severity": "INFO",
                "evidence_refs": [
                    "process/state/STATE.current.json",
                    "process/changes/CR-INDEX.json",
                    context_ref,
                ],
            },
            {
                "id": "CP0-BS-02",
                "name": "runtime and credential actions are not authorized",
                "status": "PASS",
                "severity": "INFO",
                "evidence_refs": [(CR_SUMMARY_ROOT_REL / f"{cr_id}.summary.json").as_posix()],
            },
        ],
        "blockers": [],
        "waivers": [],
        "next_route": "human_gate",
        "checked_at": now_utc(),
    }
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result_path


def bootstrap_cr(
    project_root: Path,
    *,
    cr_id: str,
    title: str,
    scope: str,
    gate_status: str = "cp2_pending",
    readiness: str = "READY",
) -> dict[str, Path]:
    project_root = project_root.resolve()
    from meta_flow.context_pack import builder
    from meta_flow.policies import failure_routing

    failure_routing.write_default_failure_routing_policy(project_root)
    failure_routing.write_default_waiver_policy(project_root)
    cr_path = _write_bootstrap_cr_file(
        project_root,
        cr_id=cr_id,
        title=title,
        scope=scope,
        gate_status=gate_status,
        readiness=readiness,
    )
    summary = summary_from_cr_file(project_root, cr_path)
    summary_path = write_summary(project_root, cr_id, summary)
    evidence_path = write_evidence_index(project_root, cr_id, summary)
    index_path = write_index(project_root)
    context, context_path = builder.build_context_pack(
        project_root,
        stage="CP0",
        profile="adoption-bootstrap",
        cr_id=cr_id,
    )
    context_ref = _rel(project_root, context_path)
    _update_current_active_change(project_root, cr_id, context_ref)
    try:
        current.render_state_file(project_root, force=False)
    except FileExistsError:
        pass
    cp0_result_path = _write_cp0_result(project_root, cr_id, context_ref)
    cp0_summary_path = cp0_result_path.with_suffix(".summary.md")
    from meta_flow.checks import cp_result

    cp0_summary_path.write_text(
        cp_result.render_summary(json.loads(cp0_result_path.read_text(encoding="utf-8"))),
        encoding="utf-8",
    )
    ledger_path = append_ledger_event(
        project_root,
        {
            "event": "active",
            "id": cr_id,
            "cr_type": summary.get("cr_type"),
            "status": "active",
            "readiness": summary.get("readiness"),
            "summary_ref": _rel(project_root, summary_path),
            "full_ref": summary.get("full_ref"),
            "evidence_index_ref": _rel(project_root, evidence_path),
            "context_ref": context_ref,
            "cp0_result_ref": _rel(project_root, cp0_result_path),
            "created_at": now_utc(),
        },
    )
    return {
        "cr": cr_path,
        "summary": summary_path,
        "evidence_index": evidence_path,
        "index": index_path,
        "context": context_path,
        "cp0_result": cp0_result_path,
        "cp0_summary": cp0_summary_path,
        "ledger": ledger_path,
    }


def close_cr(project_root: Path, cr_id: str, *, readiness: str) -> dict[str, Path]:
    project_root = project_root.resolve()
    crs = discover_formal_crs(project_root)
    if cr_id not in crs:
        raise FileNotFoundError(f"未找到正式 CR: {cr_id}")
    cr_path = crs[cr_id]
    update_frontmatter_fields(
        cr_path,
        {
            "lifecycle_status": "closed",
            "readiness_status": readiness,
            "gate_status": CLOSED_GATE_STATUS,
        },
    )
    summary = summary_from_cr_file(project_root, cr_path, readiness=readiness)
    summary["status"] = "closed"
    summary["gate_status"] = CLOSED_GATE_STATUS
    summary_path = write_summary(project_root, cr_id, summary)
    evidence_path = write_evidence_index(project_root, cr_id, summary)
    index_path = write_index(project_root)
    ledger_path = append_ledger_event(
        project_root,
        {
            "event": "closed",
            "id": cr_id,
            "cr_type": summary.get("cr_type"),
            "status": "closed",
            "readiness": readiness,
            "gate_status": CLOSED_GATE_STATUS,
            "summary_ref": _rel(project_root, summary_path),
            "full_ref": summary.get("full_ref"),
            "evidence_index_ref": _rel(project_root, evidence_path),
            "risk_refs": summary.get("remaining_risks", []),
            "authz_policy_refs": summary.get("authz_policy_refs", []),
            "closed_at": now_utc(),
        },
    )
    return {
        "summary": summary_path,
        "evidence_index": evidence_path,
        "index": index_path,
        "ledger": ledger_path,
    }


def sync_cr_status(
    project_root: Path,
    cr_id: str,
    *,
    status: str = "",
    readiness: str = "",
    gate_status: str = "",
) -> dict[str, Path]:
    project_root = project_root.resolve()
    crs = discover_formal_crs(project_root)
    if cr_id not in crs:
        raise FileNotFoundError(f"未找到正式 CR: {cr_id}")
    if status == "closed":
        if gate_status and gate_status != CLOSED_GATE_STATUS:
            raise ValueError(f"status=closed requires gate_status={CLOSED_GATE_STATUS}")
        gate_status = CLOSED_GATE_STATUS
    elif gate_status and gate_status not in cr_tracking.ALLOWED_GATE_STATUSES:
        raise ValueError(f"invalid gate_status: {gate_status}")
    cr_path = crs[cr_id]
    frontmatter_updates: dict[str, str] = {}
    if status:
        frontmatter_updates["lifecycle_status"] = status
        existing = parse_frontmatter(cr_path.read_text(encoding="utf-8"))
        if "status" in existing:
            frontmatter_updates["status"] = status
    if readiness:
        frontmatter_updates["readiness_status"] = readiness
    if gate_status:
        frontmatter_updates["gate_status"] = gate_status
    frontmatter_changed = update_frontmatter_fields(cr_path, frontmatter_updates)

    summary = summary_from_cr_file(project_root, cr_path, readiness=readiness or None)
    if status:
        summary["status"] = status
    if gate_status:
        summary["gate_status"] = gate_status
    summary_path = write_summary(project_root, cr_id, summary)
    evidence_path = write_evidence_index(project_root, cr_id, summary)
    index_path = write_index(project_root)
    state_path = _resolve_runtime_ref(project_root, STATE_CURRENT_REL.as_posix())
    if state_path.is_file():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        patch: dict[str, Any] = {"updated_at": now_utc()}
        if status in FINISHED_STATUSES and state.get("active_change") == cr_id:
            patch.update(
                {
                    "active_change": None,
                    "active_context_ref": None,
                    "current_phase": "delivered"
                    if status == "closed"
                    else str(state.get("current_phase") or "delivered"),
                    "pending_gate": None,
                    "pending_checklist_path": None,
                    "next_action": {
                        "type": "done",
                        "text": f"{cr_id} status synced as {status}; choose next CR.",
                        "stop_reason": "delivered" if status == "closed" else "no_remaining_route",
                    },
                }
            )
        elif status in {"active", "proposed", "blocked"} and not state.get("active_change"):
            patch.update(
                {
                    "active_change": cr_id,
                    "next_action": {
                        "type": "status_synced",
                        "text": f"{cr_id} status synced as {status}; continue from route plan.",
                    },
                }
            )
        if len(patch) > 1:
            current.update_current_state(
                project_root,
                patch,
                actor="meta_flow.workflow.cr_lifecycle",
                reason=f"status-sync {cr_id}",
            )
    ledger_path = append_ledger_event(
        project_root,
        {
            "event": "status_sync",
            "id": cr_id,
            "cr_type": summary.get("cr_type"),
            "status": summary.get("status"),
            "readiness": summary.get("readiness"),
            "gate_status": summary.get("gate_status"),
            "summary_ref": _rel(project_root, summary_path),
            "full_ref": summary.get("full_ref"),
            "evidence_index_ref": _rel(project_root, evidence_path),
            "frontmatter_changed": frontmatter_changed,
            "synced_at": now_utc(),
        },
    )
    return {
        "cr": cr_path,
        "summary": summary_path,
        "evidence_index": evidence_path,
        "index": index_path,
        "ledger": ledger_path,
    }


def collect_check_errors(project_root: Path) -> list[str]:
    project_root = project_root.resolve()
    errors: list[str] = []
    try:
        events = load_ledger_events(project_root)
    except ValueError as exc:
        return [str(exc)]
    index = load_index(project_root)
    items = {item.get("id"): item for item in index.get("items", []) if isinstance(item, dict)}
    current_path = _resolve_runtime_ref(project_root, STATE_CURRENT_REL.as_posix())
    current_state: dict[str, Any] = {}
    if current_path.is_file():
        try:
            current_state = json.loads(current_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{current_path} invalid JSON: {exc}")
    for event in events:
        cr_id = event.get("id")
        status = event.get("status")
        cr_type = event.get("cr_type")
        if status and status not in ALLOWED_LIFECYCLE_STATUSES:
            errors.append(f"CR ledger event {cr_id}: invalid status {status}")
        if cr_type and cr_type not in ALLOWED_CR_TYPES:
            errors.append(f"CR ledger event {cr_id}: invalid cr_type {cr_type}")
        summary_ref = event.get("summary_ref")
        if status == "closed":
            if not summary_ref:
                errors.append(f"closed CR {cr_id} missing summary_ref")
            elif not (project_root / summary_ref).is_file():
                errors.append(f"closed CR {cr_id} summary_ref missing on disk: {summary_ref}")
            if current_state.get("active_change") == cr_id:
                errors.append(f"STATE.current.json active_change points to closed CR: {cr_id}")
        if cr_id and cr_id in items:
            index_status = items[cr_id].get("status")
            if status == "closed" and index_status not in {
                "closed",
                "active",
                "implemented",
                "verified",
                "ready",
            }:
                errors.append(f"CR index status for {cr_id} is inconsistent: {index_status}")
    for item_id, item in items.items():
        status = item.get("status")
        if status in FINISHED_STATUSES and not item.get("summary_ref"):
            errors.append(f"CR index finished item {item_id} missing summary_ref")
        if status and status not in ALLOWED_LIFECYCLE_STATUSES:
            errors.append(f"CR index item {item_id}: invalid status {status}")
        cr_type = item.get("cr_type")
        if cr_type and cr_type not in ALLOWED_CR_TYPES:
            errors.append(f"CR index item {item_id}: invalid cr_type {cr_type}")
    for cr_id, path in discover_formal_crs(project_root).items():
        text = path.read_text(encoding="utf-8")
        frontmatter_fields = parse_frontmatter(text)
        record = record_from_cr_file(project_root, path)
        has_route_contract = bool(frontmatter_fields.get("route_plan_ref")) or any(
            str(key).startswith("cr_trait_") for key in frontmatter_fields
        )
        if record.status not in FINISHED_STATUSES and has_route_contract:
            route_errors, _route_warnings = route_plan.validate_route_plan_for_cr(
                project_root, path
            )
            errors.extend(route_errors)
        blockers, _needs_review = collect_scope_authz_findings(record, text=text)
        for blocker in blockers:
            capabilities = ", ".join(blocker.get("required_capabilities") or [])
            evidence = ", ".join(blocker.get("required_evidence") or [])
            suffix = f" evidence={evidence}" if evidence else ""
            errors.append(
                f"{cr_id} scope/authz {blocker.get('level')} {blocker.get('code')}: "
                f"required_capabilities={capabilities}{suffix}"
            )
    return errors


def collect_check_warnings(project_root: Path) -> list[str]:
    project_root = project_root.resolve()
    warnings: list[str] = []
    for cr_id, path in discover_formal_crs(project_root).items():
        frontmatter_fields = parse_frontmatter(path.read_text(encoding="utf-8"))
        record = record_from_cr_file(project_root, path)
        has_route_contract = bool(frontmatter_fields.get("route_plan_ref")) or any(
            str(key).startswith("cr_trait_") for key in frontmatter_fields
        )
        if record.status not in FINISHED_STATUSES and has_route_contract:
            _route_errors, route_warnings = route_plan.validate_route_plan_for_cr(
                project_root, path
            )
            warnings.extend(route_warnings)
        for finding in collect_governance_dependency_findings(project_root, record):
            markers = ", ".join(finding.get("marker_overlap") or [])
            direct = ", ".join(finding.get("direct_overlap") or [])
            overlap = markers or direct or "-"
            warnings.append(
                f"{cr_id} governance dependency {finding.get('code')}: "
                f"governance_cr={finding.get('governance_cr')} overlap={overlap} "
                f"decision={finding.get('decision')}"
            )
        for finding in collect_archive_isolation_findings(record, project_root=project_root):
            refs = ", ".join(finding.get("archive_refs") or [])
            warnings.append(
                f"{cr_id} archive isolation {finding.get('code')}: "
                f"archive_refs={refs or '-'} decision={finding.get('decision')}"
            )
    return warnings


def _conflict_surface(item: dict[str, Any]) -> set[str]:
    values: list[str] = []
    values.extend(str(value) for value in item.get("impact_surface") or [] if str(value))
    for field in IMPACT_SPLIT_FIELDS:
        values.extend(str(value) for value in item.get(field) or [] if str(value))
    values.extend(
        str(value) for value in item.get("impact_capability_normalized") or [] if str(value)
    )
    return set(values)


def conflict_report(project_root: Path, cr_id: str) -> tuple[list[str], list[str]]:
    project_root = project_root.resolve()
    index = load_index(project_root)
    items = [item for item in index.get("items", []) if isinstance(item, dict)]
    target = next((item for item in items if item.get("id") == cr_id), None)
    if not target:
        raise FileNotFoundError(f"CR index 中未找到 {cr_id}；请先运行 meta-flow cr index")
    target_keys = set(target.get("conflict_keys") or [])
    target_surface = _conflict_surface(target)
    conflicts: list[str] = []
    warnings: list[str] = []
    for item in items:
        other_id = item.get("id")
        if other_id == cr_id:
            continue
        if item.get("status") not in {"active", "blocked", "proposed"}:
            continue
        key_overlap = target_keys.intersection(item.get("conflict_keys") or [])
        surface_overlap = target_surface.intersection(_conflict_surface(item))
        if key_overlap or surface_overlap:
            conflicts.append(
                f"{cr_id} overlaps {other_id}: conflict_keys={sorted(key_overlap)} impact_surface={sorted(surface_overlap)}"
            )
    if not target_keys and not target_surface:
        warnings.append(
            f"{cr_id} has no conflict_keys or impact fields; conflict detection is weak"
        )
    return conflicts, warnings


def build_impact_report(project_root: Path, *, mode: str = "enforce") -> dict[str, Any]:
    project_root = project_root.resolve()
    if mode not in {"audit", "enforce"}:
        raise ValueError("mode must be audit or enforce")
    items: list[dict[str, Any]] = []
    blocker_count = 0
    uncategorized_cr_count = 0
    uncategorized_legacy_count = 0
    for cr_id, path in discover_formal_crs(project_root).items():
        record = record_from_cr_file(project_root, path)
        explicit = _impact_split_payload(record)
        derived_from_legacy = _categorized_legacy_impact(
            record.impact_surface, project_root=project_root
        )
        uncategorized_legacy = _uncategorized_legacy_impact(
            record.impact_surface, project_root=project_root
        )
        if uncategorized_legacy:
            uncategorized_cr_count += 1
            uncategorized_legacy_count += len(uncategorized_legacy)
        effective = _effective_impact_fields(record, project_root=project_root)
        capability_resolution = _resolve_capability_refs(
            project_root,
            effective["impact_capability_refs"],
            mode=mode,
        )
        blockers = _capability_blockers(capability_resolution)
        blocker_count += len(blockers)
        items.append(
            {
                "id": cr_id,
                "title": record.title,
                "status": record.status,
                "full_ref": record.full_ref,
                "old_impact_surface": record.impact_surface,
                "explicit_split_fields": explicit,
                "derived_from_legacy": derived_from_legacy,
                "uncategorized_legacy": uncategorized_legacy,
                "effective_split_fields": effective,
                "impact_capability_resolution": capability_resolution,
                "impact_capability_normalized": _normalized_capability_refs(capability_resolution),
                "blockers": blockers,
                "followup_candidates": _impact_followup_candidates(cr_id, uncategorized_legacy),
            }
        )
    return {
        "schema_version": 1,
        "kind": "cr-impact-surface-migration-report",
        "generated_at": now_utc(),
        "mode": mode,
        "write_policy": "side-effect-free",
        "canonical_registry_written": False,
        "summary": {
            "cr_count": len(items),
            "blocker_count": blocker_count,
            "uncategorized_cr_count": uncategorized_cr_count,
            "uncategorized_legacy_count": uncategorized_legacy_count,
        },
        "items": sorted(items, key=lambda item: item["id"]),
    }


def write_impact_report(path: Path, report: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def _load_summary(project_root: Path, cr_id: str) -> dict[str, Any]:
    path = _resolve_runtime_ref(project_root, CR_SUMMARY_ROOT_REL.as_posix()) / f"{cr_id}.summary.json"
    if not path.is_file():
        crs = discover_formal_crs(project_root)
        if cr_id not in crs:
            raise FileNotFoundError(f"未找到正式 CR: {cr_id}")
        return summary_from_cr_file(project_root, crs[cr_id])
    return json.loads(path.read_text(encoding="utf-8"))


def render_cr_brief(project_root: Path, cr_id: str, *, mode: str = "audit") -> str:
    if mode not in {"audit", "enforce"}:
        raise ValueError("mode must be audit or enforce")
    root = project_root.resolve()
    summary = _load_summary(root, cr_id)
    record: CRRecord | None = None
    crs = discover_formal_crs(root)
    if cr_id in crs:
        record = record_from_cr_file(root, crs[cr_id])
    capability_refs = (
        _effective_impact_fields(record, project_root=root)["impact_capability_refs"]
        if record is not None
        else [str(item) for item in summary.get("impact_capability_refs") or [] if str(item)]
    )
    capability_resolution = _resolve_capability_refs(root, capability_refs, mode=mode)
    capability_normalized = _normalized_capability_refs(capability_resolution)
    lines = [
        f"# {summary.get('id')} {summary.get('title')}",
        "",
        "| 字段 | 内容 |",
        "|---|---|",
        f"| 目标 | {summary.get('goal_statement') or summary.get('scope_summary', [''])[0]} |",
        f"| 目标引用 | {summary.get('goal_ref') or '-'} |",
        f"| 用户目标影响 | {summary.get('user_goal_impact') or '-'} |",
        f"| CR 类型 / 状态 | {summary.get('cr_type')} / {summary.get('status')} |",
        f"| gate / readiness | {summary.get('gate_status') or '-'} / {summary.get('readiness') or '-'} |",
        f"| 审批重点 | {summary.get('approval_focus') or '-'} |",
        f"| 决策负担 | {summary.get('decision_burden') or '-'} |",
        f"| 拆分理由 | {summary.get('split_rationale') or '-'} |",
        f"| approve 后果 | {summary.get('approve_effect') or '-'} |",
        f"| reject 后果 | {summary.get('reject_effect') or '-'} |",
        f"| 完整 CR | `{summary.get('full_ref')}` |",
    ]
    not_authorized = summary.get("not_authorized_by_approve") or []
    if not_authorized:
        lines.extend(["", "## approve 不授权", ""])
        lines.extend(f"- {item}" for item in not_authorized)
    if summary.get("impact_surface"):
        lines.extend(["", "## 影响面", ""])
        lines.extend(f"- {item}" for item in summary.get("impact_surface", []))
    uncategorized_legacy = (
        _uncategorized_legacy_impact(record.impact_surface, project_root=root)
        if record is not None
        else _uncategorized_legacy_impact(
            [str(item) for item in summary.get("impact_surface") or [] if str(item)],
            project_root=root,
        )
    )
    split_lines: list[str] = []
    split_labels = {
        "impact_capability_refs": "capability",
        "impact_feature_refs": "feature",
        "impact_module_paths": "module",
        "impact_policy_refs": "policy",
        "impact_process_refs": "process",
        "impact_runtime_refs": "runtime",
        "impact_data_refs": "data",
    }
    for field, label in split_labels.items():
        for value in summary.get(field) or []:
            split_lines.append(f"- {label}: {value}")
    for value in capability_normalized:
        split_lines.append(f"- capability.normalized: {value}")
    if capability_refs:
        split_lines.append(f"- capability.resolution_mode: {mode}")
    if split_lines:
        lines.extend(["", "## 结构化影响面", ""])
        lines.extend(split_lines)
    if uncategorized_legacy:
        lines.extend(["", "## 未分类 legacy impact_surface", ""])
        lines.extend(f"- {item}" for item in uncategorized_legacy)
        for candidate in _impact_followup_candidates(
            str(summary.get("id") or cr_id), uncategorized_legacy
        ):
            lines.append(f"- follow-up candidate: {candidate['candidate_id']}")
    capability_blockers = _capability_blockers(capability_resolution)
    if capability_blockers:
        lines.extend(["", "## capability ref blockers", ""])
        lines.extend(
            f"- {item['input_ref']}: {item['status']} {item['code']}"
            for item in capability_blockers
        )
    return "\n".join(lines) + "\n"


def render_goal_brief(project_root: Path, goal_ref: str) -> str:
    index = load_index(project_root.resolve())
    items = [
        item
        for item in index.get("items", [])
        if isinstance(item, dict) and item.get("goal_ref") == goal_ref
    ]
    if not items:
        raise FileNotFoundError(
            f"CR-INDEX.json 中未找到 goal_ref={goal_ref!r} 的 CR；请先运行 meta-flow cr index"
        )
    lines = [
        f"# Goal Brief: {goal_ref}",
        "",
        "| CR | 状态 | 类型 | 目标贡献 | 决策负担 | gate |",
        "|---|---|---|---|---|---|",
    ]
    for item in items:
        summary: dict[str, Any]
        try:
            summary = _load_summary(project_root, str(item["id"]))
        except (FileNotFoundError, json.JSONDecodeError):
            summary = item
        contribution = (
            summary.get("user_goal_impact")
            or summary.get("goal_statement")
            or item.get("title")
            or "-"
        )
        lines.append(
            f"| `{item.get('id')}` | {item.get('status')} | {item.get('cr_type')} | {contribution} | "
            f"{item.get('decision_burden') or '-'} | {item.get('gate_status') or '-'} |"
        )
    return "\n".join(lines) + "\n"


def aggregate_main(argv: list[str] | None = None) -> int:
    """Run the explicit CR-051 aggregate evidence gate without implicit lifecycle actions."""
    from meta_flow.workflow.artifact_aggregate import (
        AggregateRequest,
        FileAggregateStore,
        PersistDisposition,
        ProjectFileLegResultReader,
        ProjectionStatus,
        coordinate_aggregate,
    )

    parser = argparse.ArgumentParser(
        prog="meta-flow cr aggregate",
        description=(
            "Validate explicit source/artifact published handles, compute the aggregate, and "
            "optionally persist or project a 2/2 PASS through controlled writers."
        ),
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--id", dest="cr_id", required=True)
    parser.add_argument("--project-id", default="")
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--attempt", type=int, required=True)
    parser.add_argument("--source-handle", type=Path, required=True)
    parser.add_argument("--artifact-handle", type=Path, required=True)
    parser.add_argument("--source-mode", choices=("source-default",), default="source-default")
    parser.add_argument(
        "--artifact-mode",
        choices=("shared-artifact-project-first",),
        default="shared-artifact-project-first",
    )
    parser.add_argument("--policy-version", default="aggregate-v1")
    parser.add_argument("--expected-current-ref", default=None)
    parser.add_argument("--store-root", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--project-completion", action="store_true")
    parser.add_argument("--expected-state-updated-at", default="")
    parsed = parser.parse_args(list(argv or []))
    if not CR_ID_RE.fullmatch(parsed.cr_id):
        parser.error("--id must use CR-xxx naming")
    if parsed.project_completion and parsed.dry_run:
        parser.error("--project-completion cannot be combined with --dry-run")
    if parsed.project_completion and not parsed.expected_state_updated_at:
        parser.error("--expected-state-updated-at is required with --project-completion")

    project_root = parsed.project_root.resolve()
    handles: list[dict[str, Any]] = []
    for label, path in (
        ("source", parsed.source_handle),
        ("artifact", parsed.artifact_handle),
    ):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            parser.error(f"unable to read {label} handle: {exc}")
        if not isinstance(payload, dict):
            parser.error(f"{label} handle must be a JSON object")
        handles.append(payload)

    request = AggregateRequest(
        operation_id=parsed.operation_id,
        logical_attempt=parsed.attempt,
        cr_id=parsed.cr_id,
        project_id=parsed.project_id or project_root.name,
        required_legs=("source", "artifact"),
        expected_modes=(
            ("source", parsed.source_mode),
            ("artifact", parsed.artifact_mode),
        ),
        policy_version=parsed.policy_version,
    )
    reader = ProjectFileLegResultReader(project_root)
    store_root = parsed.store_root
    if store_root is not None and not store_root.is_absolute():
        store_root = project_root / store_root
    store = (
        None
        if parsed.dry_run
        else FileAggregateStore(project_root=project_root, store_root=store_root)
    )
    projector = (
        AggregateCompletionProjector(
            project_root=project_root,
            expected_state_updated_at=parsed.expected_state_updated_at,
        )
        if parsed.project_completion
        else None
    )
    command = coordinate_aggregate(
        request,
        handles,
        reader=reader,
        store=store,
        projector=projector,
        expected_current_ref=parsed.expected_current_ref,
        dry_run=parsed.dry_run,
        project=parsed.project_completion,
    )
    print(json.dumps(command.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    if command.validation_errors:
        return 2
    if command.write_receipt is not None and command.write_receipt.disposition in {
        PersistDisposition.CONFLICT,
        PersistDisposition.FAILED,
    }:
        return 3
    if command.projection_receipt is not None and command.projection_receipt.status in {
        ProjectionStatus.PARTIAL,
        ProjectionStatus.FAILED,
    }:
        return 4
    return 0


def _print_cr_help() -> None:
    print(
        "usage: meta-flow cr <command> [options]\n\n"
        "Commands:\n"
        "  bootstrap  Create an active bootstrap CR plus summary, index, ledger, CP0 result, and context.\n"
        "  index      Rebuild process/changes/CR-INDEX.json from formal CR files.\n"
        "  summary    Generate process/changes/summaries/<CR>.summary.json.\n"
        "  brief      Print a goal-oriented CR brief from summary/frontmatter.\n"
        "  goal-brief Print all CRs attached to one goal_ref.\n"
        "  impact-report Print a side-effect-free impact surface migration report as JSON.\n"
        "  status-sync Sync one CR frontmatter, summary, CR-INDEX, ledger, and active STATE pointer.\n"
        "  aggregate  Validate explicit published leg handles and persist/project a guarded aggregate.\n"
        "  branch-open Open paired project/artifact CR branches from fresh remote defaults.\n"
        "  branch-publish Publish existing committed CR refs; never stage or commit.\n"
        "  branch-merge Explicitly fast-forward paired remote defaults from published tips.\n"
        "  branch-finish Re-prove merge facts, retain recovery refs, then clean CR branches.\n"
        "  close      Close a CR logically: summary + evidence index + ledger event.\n"
        "  check      Validate CR ledger, index, summaries, and active state refs.\n"
        "  conflicts  Compare active/proposed/blocked CR conflict keys from CR-INDEX.json.\n\n"
        "Examples:\n"
        '  meta-flow cr bootstrap --id CR-001 --title "target adoption bootstrap" --scope "Initialize Meta Flow adoption readiness." --project-root .\n'
        "  meta-flow cr index --project-root .\n"
        "  meta-flow cr summary --id CR-101 --project-root .\n"
        "  meta-flow cr brief --id CR-101 --project-root .\n"
        "  meta-flow cr brief --id CR-101 --mode enforce --project-root .\n"
        "  meta-flow cr goal-brief --goal-ref GOAL-001 --project-root .\n"
        "  meta-flow cr impact-report --project-root .\n"
        "  meta-flow cr status-sync --id CR-101 --status closed --readiness READY_WITH_RISK --gate-status cp8_closed --project-root .\n"
        "  meta-flow cr aggregate --id CR-051 --operation-id operation-001 --attempt 1 --source-handle source.json --artifact-handle artifact.json --dry-run --project-root .\n"
        "  meta-flow cr branch-open --id CR-101 --slug safe-change --dry-run --project-root .\n"
        "  meta-flow cr branch-publish --id CR-101 --branch cr/cr-101-safe-change --dry-run --project-root .\n"
        "  meta-flow cr branch-merge --id CR-101 --branch cr/cr-101-safe-change --publish-result publish.json --dry-run --project-root .\n"
        "  meta-flow cr branch-finish --id CR-101 --branch cr/cr-101-safe-change --merge-result merge.json --dry-run --project-root .\n"
        "  meta-flow cr close --id CR-101 --readiness READY_WITH_RISK --project-root .\n"
        "  meta-flow cr conflicts --id CR-102 --project-root .\n"
    )


def main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if not args or args[0] in {"-h", "--help"}:
        _print_cr_help()
        return 0
    command = args[0]
    if command == "aggregate":
        return aggregate_main(args[1:])
    if command in {"branch-open", "branch-publish", "branch-merge", "branch-finish"}:
        from meta_flow.workflow.git_branch_lifecycle import branch_main

        return branch_main(command, args[1:])
    parser = argparse.ArgumentParser(prog=f"meta-flow cr {command}")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--id", dest="cr_id", default="")
    parser.add_argument("--title", default="Meta Flow adoption bootstrap")
    parser.add_argument(
        "--scope", default="Bootstrap Meta Flow adoption readiness for this target project."
    )
    parser.add_argument(
        "--gate-status",
        default="cp2_pending",
        help="Gate status; status-sync --status closed uses and requires cp8_closed.",
    )
    parser.add_argument("--readiness", default="READY")
    parser.add_argument("--status", default="")
    parser.add_argument("--goal-ref", default="")
    parser.add_argument("--mode", choices=["audit", "enforce"], default=None)
    parser.add_argument("--output", type=Path, default=None)
    parsed = parser.parse_args(args[1:])
    project_root = parsed.project_root.resolve()

    if command == "bootstrap":
        if not parsed.cr_id:
            raise SystemExit("--id is required and must use CR-xxx naming")
        paths = bootstrap_cr(
            project_root,
            cr_id=parsed.cr_id,
            title=parsed.title,
            scope=parsed.scope,
            gate_status=parsed.gate_status,
            readiness=parsed.readiness,
        )
        for key, path in paths.items():
            print(f"{key}: {path}")
        return 0
    if command == "index":
        path = write_index(project_root)
        print(f"wrote: {path}")
        return 0
    if command == "summary":
        if not parsed.cr_id:
            raise SystemExit("--id is required")
        crs = discover_formal_crs(project_root)
        if parsed.cr_id not in crs:
            raise SystemExit(f"未找到正式 CR: {parsed.cr_id}")
        summary = summary_from_cr_file(project_root, crs[parsed.cr_id])
        path = write_summary(project_root, parsed.cr_id, summary)
        print(f"wrote: {path}")
        return 0
    if command == "brief":
        if not parsed.cr_id:
            raise SystemExit("--id is required")
        print(render_cr_brief(project_root, parsed.cr_id, mode=parsed.mode or "audit"), end="")
        return 0
    if command == "goal-brief":
        if not parsed.goal_ref:
            raise SystemExit("--goal-ref is required")
        print(render_goal_brief(project_root, parsed.goal_ref), end="")
        return 0
    if command == "impact-report":
        report = build_impact_report(project_root, mode=parsed.mode or "enforce")
        rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if parsed.output:
            path = write_impact_report(parsed.output, report)
            print(f"wrote: {path}")
        else:
            print(rendered, end="")
        return 0
    if command == "close":
        if not parsed.cr_id:
            raise SystemExit("--id is required")
        paths = close_cr(project_root, parsed.cr_id, readiness=parsed.readiness)
        for key, path in paths.items():
            print(f"{key}: {path}")
        return 0
    if command == "status-sync":
        if not parsed.cr_id:
            raise SystemExit("--id is required")
        paths = sync_cr_status(
            project_root,
            parsed.cr_id,
            status=parsed.status,
            readiness=parsed.readiness if "--readiness" in args else "",
            gate_status=parsed.gate_status if "--gate-status" in args else "",
        )
        for key, path in paths.items():
            print(f"{key}: {path}")
        return 0
    if command == "check":
        errors = collect_check_errors(project_root)
        warnings = collect_check_warnings(project_root)
        print("CR Lifecycle Check: " + ("FAIL" if errors else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    if command == "conflicts":
        if not parsed.cr_id:
            raise SystemExit("--id is required")
        conflicts, warnings = conflict_report(project_root, parsed.cr_id)
        print("CR Conflicts: " + ("FAIL" if conflicts else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for conflict in conflicts:
            print(f"- CONFLICT: {conflict}")
        return 1 if conflicts else 0
    raise SystemExit(
        f"未知 cr 命令: {command}. 目前支持: bootstrap, index, summary, brief, goal-brief, impact-report, "
        "status-sync, aggregate, branch-open, branch-publish, branch-merge, branch-finish, close, check, conflicts"
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
