"""CR lifecycle record, governance, and discovery primitives."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from meta_flow.design import feature_registry
from meta_flow.policies import authz
from meta_flow.project.process_route import _resolve_runtime_ref, format_runtime_ref
from meta_flow.project.scale import load_yaml_object
from meta_flow.workflow.cr_model import (
    CR_ID_RE,
    FRONTMATTER_RE,
    CRRecord,
    normalize_cr_type,
    parse_bool,
    parse_frontmatter,
    parse_inline_list,
    render_frontmatter_fields,
)
from meta_flow.workspace.git_sync import run_git

LEGACY_SOURCE_REL = Path("process/legacy/LEGACY-SOURCE.yaml")

CR_SUMMARY_ROOT_REL = Path("process/changes/summaries")

IMPACT_SURFACE_RULES_REL = Path("process/project/IMPACT-SURFACE-RULES.yaml")

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

def update_frontmatter_fields(path: Path, updates: dict[str, str]) -> bool:
    """Update scalar frontmatter fields, preserving unrelated body content."""

    text = path.read_text(encoding="utf-8")
    updated = render_frontmatter_fields(text, updates)
    if updated == text:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def _rel(project_root: Path, path: Path) -> str:
    """保留 records facade owner；格式语义由 canonical route service 提供。"""

    return format_runtime_ref(project_root, path)


def _process_root(project_root: Path) -> Path:
    """Resolve the process root for binding projects and legacy test fixtures."""

    return _resolve_runtime_ref(project_root.resolve(), "process/PROJECT.yaml").parent.resolve(
        strict=False
    )


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

def discover_formal_crs(
    project_root: Path,
    *,
    _resolve_runtime_ref_fn: Any | None = None,
    _rel_fn: Any | None = None,
    excluded_legacy_paths: frozenset[Path] | None = None,
) -> dict[str, Path]:
    resolve_runtime_ref = (
        _resolve_runtime_ref if _resolve_runtime_ref_fn is None else _resolve_runtime_ref_fn
    )
    rel = _rel if _rel_fn is None else _rel_fn
    root = resolve_runtime_ref(project_root, "process/changes")
    if not root.is_dir():
        return {}
    excluded_legacy_paths = excluded_legacy_paths or frozenset()
    crs: dict[str, Path] = {}
    for path in sorted(root.glob("CR-*.md")):
        if "FOLLOW-UP" in path.name:
            continue
        if path.resolve() in excluded_legacy_paths:
            continue
        cr_id = _cr_id_from_path(path)
        if cr_id:
            if cr_id in crs:
                raise ValueError(
                    f"duplicate formal CR id {cr_id}: {rel(project_root, crs[cr_id])}, {rel(project_root, path)}"
                )
            crs[cr_id] = path
    return crs

def record_from_cr_file(
    project_root: Path,
    path: Path,
    *,
    _rel_fn: Any | None = None,
    read_context: Any | None = None,
    text: str | None = None,
) -> CRRecord:
    rel = _rel if _rel_fn is None else _rel_fn
    if text is None:
        text = (
            path.read_text(encoding="utf-8")
            if read_context is None
            else read_context.read_text(rel(project_root, path))
        )
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
        full_ref=rel(project_root, path),
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

def _git_fact(root: Path, *args: str) -> str:
    result = run_git(list(args), cwd=root)
    return result.stdout.strip() if result.ok else ""

def _load_json_object(path: Path, *, subject: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{subject} is not readable JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{subject} must be one JSON object")
    return payload
