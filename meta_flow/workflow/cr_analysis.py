"""CR consistency, conflict, impact, and human-readable analysis."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from meta_flow.policies import route_plan
from meta_flow.project.process_route import _resolve_runtime_ref
from meta_flow.workflow.cr_index import (
    _cr_numeric_sort_key,
    build_index,
    load_index,
    validate_index_payload,
)
from meta_flow.workflow.cr_model import (
    ALLOWED_CR_TYPES,
    ALLOWED_LIFECYCLE_STATUSES,
    CR_ID_RE,
    FINISHED_STATUSES,
    CRRecord,
    now_utc,
    parse_frontmatter,
)
from meta_flow.workflow.cr_projection import (
    STATE_CURRENT_REL,
    load_ledger_events,
    summary_from_cr_file,
)
from meta_flow.workflow.cr_records import (
    CR_SUMMARY_ROOT_REL,
    IMPACT_SPLIT_FIELDS,
    OPEN_DEPENDENCY_STATUSES,
    _capability_blockers,
    _categorized_legacy_impact,
    _effective_impact_fields,
    _impact_followup_candidates,
    _impact_split_payload,
    _normalized_capability_refs,
    _resolve_capability_refs,
    _uncategorized_legacy_impact,
    collect_archive_isolation_findings,
    collect_governance_dependency_findings,
    collect_scope_authz_findings,
    discover_formal_crs,
    record_from_cr_file,
)


def collect_check_errors(project_root: Path) -> list[str]:
    project_root = project_root.resolve()
    errors: list[str] = []
    try:
        events = load_ledger_events(project_root)
    except ValueError as exc:
        return [str(exc)]
    try:
        index = load_index(project_root)
    except ValueError as exc:
        index = {}
        errors.append(str(exc))
    try:
        expected_index = build_index(project_root)
    except ValueError as exc:
        expected_index = {}
        errors.append(str(exc))
    if index:
        errors.extend(validate_index_payload(index))
        if expected_index and index.get("semantic_digest") != expected_index.get(
            "semantic_digest"
        ):
            errors.append("CR-INDEX stale projection differs from formal truth rebuild digest")
    items = {
        item.get("id"): item
        for item in index.get("items", [])
        if isinstance(item, dict)
    }
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
            elif not _resolve_runtime_ref(project_root, str(summary_ref)).is_file():
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
        for finding in collect_archive_isolation_findings(
            record, project_root=project_root
        ):
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
        str(value)
        for value in item.get("impact_capability_normalized") or []
        if str(value)
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
                f"{cr_id} overlaps {other_id}: conflict_keys={sorted(key_overlap)} "
                f"impact_surface={sorted(surface_overlap)}"
            )
    if not target_keys and not target_surface:
        warnings.append(
            f"{cr_id} has no conflict_keys or impact fields; conflict detection is weak"
        )
    return conflicts, warnings


def proposed_conflict_report(
    project_root: Path,
    *,
    cr_id: str,
    conflict_keys: list[str],
    impact_surface: list[str],
    impact_fields: dict[str, list[str]],
    title: str = "",
    scope: str = "",
) -> dict[str, Any]:
    """Preview one transient CR candidate without writing lifecycle artifacts."""

    project_root = project_root.resolve()
    if not CR_ID_RE.fullmatch(cr_id):
        return {
            "decision": "INVALID",
            "code": "CR_CONFLICT_PROPOSED_INPUT_INVALID",
            "cr_id": cr_id,
            "mutation_count": 0,
            "planned_mutation_count": 0,
            "conflicts": [],
            "warnings": [],
        }
    index = load_index(project_root)
    items = [item for item in index.get("items", []) if isinstance(item, dict)]
    if any(str(item.get("id") or "") == cr_id for item in items):
        return {
            "decision": "INVALID",
            "code": "CR_CONFLICT_PROPOSED_ID_EXISTS",
            "cr_id": cr_id,
            "mutation_count": 0,
            "planned_mutation_count": 0,
            "conflicts": [],
            "warnings": [],
        }

    normalized_keys = sorted(
        set(value.strip() for value in conflict_keys if value.strip())
    )
    normalized_surface = sorted(
        set(value.strip() for value in impact_surface if value.strip())
    )
    normalized_fields = {
        field: sorted(
            set(value.strip() for value in impact_fields.get(field, []) if value.strip())
        )
        for field in IMPACT_SPLIT_FIELDS
    }
    if not normalized_keys and not normalized_surface and not any(
        normalized_fields.values()
    ):
        return {
            "decision": "INVALID",
            "code": "CR_CONFLICT_PROPOSED_INPUT_REQUIRED",
            "cr_id": cr_id,
            "mutation_count": 0,
            "planned_mutation_count": 0,
            "conflicts": [],
            "warnings": [],
        }

    capability_resolution = _resolve_capability_refs(
        project_root,
        normalized_fields["impact_capability_refs"],
        mode="audit",
    )
    candidate = {
        "id": cr_id,
        "title": title,
        "scope": scope,
        "status": "proposed",
        "conflict_keys": normalized_keys,
        "impact_surface": normalized_surface,
        **normalized_fields,
        "impact_capability_normalized": _normalized_capability_refs(
            capability_resolution
        ),
    }
    candidate_keys = set(candidate["conflict_keys"])
    candidate_surface = _conflict_surface(candidate)
    conflicts: list[dict[str, Any]] = []
    for item in sorted(
        items, key=lambda value: _cr_numeric_sort_key(str(value.get("id") or ""))
    ):
        if item.get("status") not in OPEN_DEPENDENCY_STATUSES:
            continue
        key_overlap = sorted(
            candidate_keys.intersection(item.get("conflict_keys") or [])
        )
        surface_overlap = sorted(
            candidate_surface.intersection(_conflict_surface(item))
        )
        if key_overlap or surface_overlap:
            conflicts.append(
                {
                    "existing_cr_id": str(item.get("id") or ""),
                    "matched_conflict_keys": key_overlap,
                    "matched_impact_surface": surface_overlap,
                }
            )
    return {
        "decision": "CONFLICT" if conflicts else "NO_CONFLICT",
        "code": "CR_CONFLICT" if conflicts else "CR_CONFLICT_NONE",
        "cr_id": cr_id,
        "mutation_count": 0,
        "planned_mutation_count": 0,
        "candidate": candidate,
        "conflicts": conflicts,
        "warnings": [],
    }


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
                "impact_capability_normalized": _normalized_capability_refs(
                    capability_resolution
                ),
                "blockers": blockers,
                "followup_candidates": _impact_followup_candidates(
                    cr_id, uncategorized_legacy
                ),
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
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _load_summary(project_root: Path, cr_id: str) -> dict[str, Any]:
    path = (
        _resolve_runtime_ref(project_root, CR_SUMMARY_ROOT_REL.as_posix())
        / f"{cr_id}.summary.json"
    )
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
        else [
            str(item)
            for item in summary.get("impact_capability_refs") or []
            if str(item)
        ]
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
            f"| `{item.get('id')}` | {item.get('status')} | {item.get('cr_type')} | "
            f"{contribution} | {item.get('decision_burden') or '-'} | "
            f"{item.get('gate_status') or '-'} |"
        )
    return "\n".join(lines) + "\n"
