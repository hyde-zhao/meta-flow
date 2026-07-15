"""ROADMAP.yaml and MILESTONES.yaml validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meta_flow.project.scale import ProjectFinding, add_finding, load_yaml_object

ROADMAP_REL = Path("process/project/ROADMAP.yaml")
MILESTONES_REL = Path("process/project/MILESTONES.yaml")
ROADMAP_SCHEMA_VERSION = 1
MILESTONES_SCHEMA_VERSION = 1
ROADMAP_STATUSES = {"planned", "active", "blocked", "done", "deferred"}
MILESTONE_STATUSES = {"planned", "active", "blocked", "done", "deferred"}


@dataclass(frozen=True)
class RoadmapItem:
    id: str
    title: str
    status: str
    milestone_refs: tuple[str, ...]
    source_refs: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class Roadmap:
    roadmap_id: str
    project_id: str
    horizon: str
    items: tuple[RoadmapItem, ...]
    source_refs: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class Milestone:
    milestone_id: str
    title: str
    status: str
    target_window: str
    roadmap_item_refs: tuple[str, ...]
    source_refs: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class Milestones:
    project_id: str
    milestones: tuple[Milestone, ...]
    source_refs: tuple[dict[str, Any], ...]


def _as_object_list(value: Any, *, key: str, findings: list[ProjectFinding]) -> list[dict[str, Any]]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        add_finding(findings, "ERROR", "field_type", f"{key} must be a list", key=key)
        return []
    objects: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            add_finding(findings, "ERROR", "field_type", f"{key}[{index}] must be an object", key=key)
            continue
        objects.append(item)
    return objects


def _string_list(value: Any, *, key: str, findings: list[ProjectFinding]) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        add_finding(findings, "ERROR", "field_type", f"{key} must be a list of non-empty strings", key=key)
        return ()
    return tuple(value)


def _source_refs(value: Any, *, key: str, findings: list[ProjectFinding]) -> tuple[dict[str, Any], ...]:
    objects = _as_object_list(value, key=key, findings=findings)
    for index, item in enumerate(objects):
        if not isinstance(item.get("kind"), str) or not item.get("kind"):
            add_finding(findings, "ERROR", "field_type", f"{key}[{index}].kind must be a non-empty string", key=key)
        if not isinstance(item.get("path"), str) or not item.get("path"):
            add_finding(findings, "ERROR", "field_type", f"{key}[{index}].path must be a non-empty string", key=key)
    return tuple(objects)


def validate_roadmap_payload(payload: dict[str, Any]) -> tuple[Roadmap | None, list[ProjectFinding]]:
    findings: list[ProjectFinding] = []
    if payload.get("schema_version") != ROADMAP_SCHEMA_VERSION:
        add_finding(findings, "ERROR", "schema_version", f"ROADMAP.yaml schema_version must be {ROADMAP_SCHEMA_VERSION}", key="schema_version")
    roadmap_id = payload.get("roadmap_id")
    project_id = payload.get("project_id")
    horizon = payload.get("horizon")
    if not isinstance(roadmap_id, str) or not roadmap_id:
        add_finding(findings, "ERROR", "missing_required", "ROADMAP.yaml roadmap_id must be a non-empty string", key="roadmap_id")
    if not isinstance(project_id, str) or not project_id:
        add_finding(findings, "ERROR", "missing_required", "ROADMAP.yaml project_id must be a non-empty string", key="project_id")
    if not isinstance(horizon, str) or not horizon:
        add_finding(findings, "ERROR", "missing_required", "ROADMAP.yaml horizon must be a non-empty string", key="horizon")

    seen: set[str] = set()
    items: list[RoadmapItem] = []
    for index, item in enumerate(_as_object_list(payload.get("items", []), key="items", findings=findings)):
        item_id = item.get("id")
        title = item.get("title")
        status = item.get("status")
        key_prefix = f"items[{index}]"
        if not isinstance(item_id, str) or not item_id:
            add_finding(findings, "ERROR", "missing_required", f"{key_prefix}.id must be a non-empty string", key=f"{key_prefix}.id")
            item_id = ""
        elif item_id in seen:
            add_finding(findings, "ERROR", "duplicate_id", f"duplicate roadmap item id: {item_id}", key=f"{key_prefix}.id")
        seen.add(item_id)
        if not isinstance(title, str) or not title:
            add_finding(findings, "ERROR", "missing_required", f"{key_prefix}.title must be a non-empty string", key=f"{key_prefix}.title")
            title = ""
        if status not in ROADMAP_STATUSES:
            add_finding(findings, "ERROR", "status_enum", f"{key_prefix}.status must be one of: active, blocked, deferred, done, planned", key=f"{key_prefix}.status")
            status = ""
        items.append(
            RoadmapItem(
                id=str(item_id),
                title=str(title),
                status=str(status),
                milestone_refs=_string_list(item.get("milestone_refs", []), key=f"{key_prefix}.milestone_refs", findings=findings),
                source_refs=_source_refs(item.get("source_refs", []), key=f"{key_prefix}.source_refs", findings=findings),
            )
        )
    source_refs = _source_refs(payload.get("source_refs", []), key="source_refs", findings=findings)
    if any(finding.severity == "ERROR" for finding in findings):
        return None, findings
    return Roadmap(roadmap_id=str(roadmap_id), project_id=str(project_id), horizon=str(horizon), items=tuple(items), source_refs=source_refs), findings


def validate_milestones_payload(payload: dict[str, Any]) -> tuple[Milestones | None, list[ProjectFinding]]:
    findings: list[ProjectFinding] = []
    if payload.get("schema_version") != MILESTONES_SCHEMA_VERSION:
        add_finding(findings, "ERROR", "schema_version", f"MILESTONES.yaml schema_version must be {MILESTONES_SCHEMA_VERSION}", key="schema_version")
    project_id = payload.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        add_finding(findings, "ERROR", "missing_required", "MILESTONES.yaml project_id must be a non-empty string", key="project_id")
    seen: set[str] = set()
    milestones: list[Milestone] = []
    for index, item in enumerate(_as_object_list(payload.get("milestones", []), key="milestones", findings=findings)):
        milestone_id = item.get("milestone_id")
        title = item.get("title")
        status = item.get("status")
        target_window = item.get("target_window", "")
        key_prefix = f"milestones[{index}]"
        if not isinstance(milestone_id, str) or not milestone_id:
            add_finding(findings, "ERROR", "missing_required", f"{key_prefix}.milestone_id must be a non-empty string", key=f"{key_prefix}.milestone_id")
            milestone_id = ""
        elif milestone_id in seen:
            add_finding(findings, "ERROR", "duplicate_id", f"duplicate milestone id: {milestone_id}", key=f"{key_prefix}.milestone_id")
        seen.add(milestone_id)
        if not isinstance(title, str) or not title:
            add_finding(findings, "ERROR", "missing_required", f"{key_prefix}.title must be a non-empty string", key=f"{key_prefix}.title")
            title = ""
        if status not in MILESTONE_STATUSES:
            add_finding(findings, "ERROR", "status_enum", f"{key_prefix}.status must be one of: active, blocked, deferred, done, planned", key=f"{key_prefix}.status")
            status = ""
        if target_window not in (None, "") and not isinstance(target_window, str):
            add_finding(findings, "ERROR", "field_type", f"{key_prefix}.target_window must be a string", key=f"{key_prefix}.target_window")
            target_window = ""
        milestones.append(
            Milestone(
                milestone_id=str(milestone_id),
                title=str(title),
                status=str(status),
                target_window=str(target_window or ""),
                roadmap_item_refs=_string_list(item.get("roadmap_item_refs", []), key=f"{key_prefix}.roadmap_item_refs", findings=findings),
                source_refs=_source_refs(item.get("source_refs", []), key=f"{key_prefix}.source_refs", findings=findings),
            )
        )
    source_refs = _source_refs(payload.get("source_refs", []), key="source_refs", findings=findings)
    if any(finding.severity == "ERROR" for finding in findings):
        return None, findings
    return Milestones(project_id=str(project_id), milestones=tuple(milestones), source_refs=source_refs), findings


def validate_roadmap(project_root: Path, ref: str | Path = ROADMAP_REL) -> tuple[Roadmap | None, list[ProjectFinding]]:
    path = project_root.resolve() / ref
    if not path.is_file():
        return None, [ProjectFinding("ERROR", "E_ROADMAP_MISSING", f"ROADMAP.yaml missing: {path}")]
    try:
        payload = load_yaml_object(path)
    except (OSError, ValueError) as exc:
        return None, [ProjectFinding("ERROR", "E_ROADMAP_INVALID", str(exc))]
    return validate_roadmap_payload(payload)


def validate_milestones(project_root: Path, ref: str | Path = MILESTONES_REL) -> tuple[Milestones | None, list[ProjectFinding]]:
    path = project_root.resolve() / ref
    if not path.is_file():
        return None, [ProjectFinding("ERROR", "E_MILESTONES_MISSING", f"MILESTONES.yaml missing: {path}")]
    try:
        payload = load_yaml_object(path)
    except (OSError, ValueError) as exc:
        return None, [ProjectFinding("ERROR", "E_MILESTONES_INVALID", str(exc))]
    return validate_milestones_payload(payload)


def validate_roadmap_milestone_refs(roadmap: Roadmap | None, milestones: Milestones | None) -> list[ProjectFinding]:
    findings: list[ProjectFinding] = []
    if roadmap is None or milestones is None:
        return findings
    roadmap_ids = {item.id for item in roadmap.items}
    milestone_ids = {item.milestone_id for item in milestones.milestones}
    milestone_to_roadmap = {item.milestone_id: set(item.roadmap_item_refs) for item in milestones.milestones}
    roadmap_to_milestone = {item.id: set(item.milestone_refs) for item in roadmap.items}

    for item in roadmap.items:
        for milestone_ref in item.milestone_refs:
            if milestone_ref not in milestone_ids:
                add_finding(findings, "ERROR", "broken_ref", f"roadmap item {item.id} references missing milestone: {milestone_ref}", key=f"items.{item.id}.milestone_refs")
            elif item.id not in milestone_to_roadmap.get(milestone_ref, set()):
                add_finding(findings, "ERROR", "cross_ref_mismatch", f"roadmap item {item.id} references milestone {milestone_ref}, but milestone does not reference the roadmap item", key=f"items.{item.id}.milestone_refs")

    for milestone in milestones.milestones:
        for roadmap_ref in milestone.roadmap_item_refs:
            if roadmap_ref not in roadmap_ids:
                add_finding(findings, "ERROR", "broken_ref", f"milestone {milestone.milestone_id} references missing roadmap item: {roadmap_ref}", key=f"milestones.{milestone.milestone_id}.roadmap_item_refs")
            elif milestone.milestone_id not in roadmap_to_milestone.get(roadmap_ref, set()):
                add_finding(findings, "ERROR", "cross_ref_mismatch", f"milestone {milestone.milestone_id} references roadmap item {roadmap_ref}, but roadmap item does not reference the milestone", key=f"milestones.{milestone.milestone_id}.roadmap_item_refs")
    return findings
