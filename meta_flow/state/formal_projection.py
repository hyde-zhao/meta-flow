"""PROJECT/ROADMAP/Phase/Work/CR formal truth 到运行态的确定性投影。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any

from meta_flow.project.process_route import _resolve_runtime_ref
from meta_flow.project.scale import load_yaml_object
from meta_flow.workflow.cr_model import parse_frontmatter

PROJECT_REF = "process/PROJECT.yaml"
ROADMAP_REF = "process/ROADMAP.yaml"
CR_LEDGER_REF = "process/state/CR-LEDGER.ndjson"
TERMINAL_WORK = frozenset({"completed", "cancelled", "archived"})
TERMINAL_CR = frozenset({"closed", "cancelled", "superseded", "archived"})


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def _resolve(project_root: Path, logical_ref: str, process_root: Path | None) -> Path:
    if process_root is None:
        return _resolve_runtime_ref(project_root.resolve(), logical_ref)
    if not logical_ref.startswith("process/") or ".." in Path(logical_ref).parts:
        raise ValueError(f"formal truth ref is unsafe: {logical_ref}")
    return process_root.resolve() / logical_ref.removeprefix("process/")


def _load_object(
    project_root: Path,
    logical_ref: str,
    process_root: Path | None,
    object_overrides: Mapping[str, tuple[dict[str, Any], bytes]] | None = None,
) -> dict[str, Any]:
    if object_overrides is not None and logical_ref in object_overrides:
        return dict(object_overrides[logical_ref][0])
    path = _resolve(project_root, logical_ref, process_root)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"formal truth source missing or not regular: {logical_ref}")
    payload = load_yaml_object(path)
    if not isinstance(payload, dict):
        raise ValueError(f"formal truth source must be an object: {logical_ref}")
    return payload


def _source_receipt(
    project_root: Path,
    logical_ref: str,
    process_root: Path | None,
    object_overrides: Mapping[str, tuple[dict[str, Any], bytes]] | None = None,
) -> dict[str, str]:
    if object_overrides is not None and logical_ref in object_overrides:
        return {
            "ref": logical_ref,
            "digest": sha256(object_overrides[logical_ref][1]).hexdigest(),
        }
    path = _resolve(project_root, logical_ref, process_root)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"formal truth source missing or not regular: {logical_ref}")
    return {"ref": logical_ref, "digest": sha256(path.read_bytes()).hexdigest()}


def _active_cr_ids(
    project_root: Path,
    process_root: Path | None,
) -> tuple[list[str], list[dict[str, str]]]:
    path = _resolve(project_root, CR_LEDGER_REF, process_root)
    if path.is_symlink() or not path.is_file():
        return [], [{"ref": CR_LEDGER_REF, "digest": "missing"}]
    latest: dict[str, str] = {}
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"formal CR ledger is invalid at line {line_no}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"formal CR ledger row {line_no} must be an object")
        cr_id = str(row.get("id") or row.get("cr_id") or "")
        status = str(row.get("status") or row.get("lifecycle_status") or "").lower()
        if cr_id:
            latest[cr_id] = status
    sources = [{"ref": CR_LEDGER_REF, "digest": sha256(path.read_bytes()).hexdigest()}]
    changes_root = path.parent.parent / "changes"
    if changes_root.is_symlink() or not changes_root.is_dir():
        raise ValueError("formal CR truth root missing or not a regular directory")
    discovered: set[str] = set()
    for formal_path in sorted(changes_root.glob("CR-*.md")):
        if formal_path.is_symlink() or not formal_path.is_file():
            raise ValueError(f"formal CR truth is not regular: {formal_path.name}")
        fields = parse_frontmatter(formal_path.read_text(encoding="utf-8"))
        if fields.get("kind") != "cr":
            continue
        cr_id = str(fields.get("cr_id") or "")
        formal_ref = "process/changes/" + formal_path.name
        if not cr_id or cr_id in discovered:
            raise ValueError(f"formal CR truth identity missing or duplicate: {formal_ref}")
        discovered.add(cr_id)
        formal_status = str(
            fields.get("lifecycle_status") or fields.get("status") or ""
        ).lower()
        if not formal_status:
            raise ValueError(f"formal CR truth status missing: {formal_ref}")
        latest[cr_id] = formal_status
        sources.append({"ref": formal_ref, "digest": sha256(formal_path.read_bytes()).hexdigest()})
    missing_formal = sorted(set(latest) - discovered)
    if missing_formal:
        raise ValueError(
            "formal CR truth missing for ledger identities: " + ", ".join(missing_formal)
        )
    active = sorted(cr_id for cr_id, status in latest.items() if status not in TERMINAL_CR)
    return active, sources


def build_formal_truth_snapshot(
    project_root: Path,
    *,
    process_root: Path | None = None,
    object_overrides: Mapping[str, tuple[dict[str, Any], bytes]] | None = None,
) -> dict[str, Any]:
    """只沿 PROJECT→ROADMAP→declared Phase/Work 构建有界 formal truth。"""

    root = project_root.resolve()
    project = _load_object(root, PROJECT_REF, process_root, object_overrides)
    roadmap_ref = str(project.get("roadmap_ref") or "")
    if not roadmap_ref or roadmap_ref.startswith("/") or ".." in Path(roadmap_ref).parts:
        raise ValueError("PROJECT roadmap_ref is missing or unsafe")
    roadmap_logical = "process/" + roadmap_ref.removeprefix("process/")
    roadmap = _load_object(root, roadmap_logical, process_root, object_overrides)
    raw_phase_refs = roadmap.get("phase_refs")
    if not isinstance(raw_phase_refs, list) or not raw_phase_refs:
        raise ValueError("ROADMAP phase_refs must be a non-empty list")
    sources = [
        _source_receipt(root, PROJECT_REF, process_root, object_overrides),
        _source_receipt(root, roadmap_logical, process_root, object_overrides),
    ]
    active_phases: list[str] = []
    active_works: list[str] = []
    phase_statuses: dict[str, str] = {}
    seen_work_refs: set[str] = set()
    for raw_ref in raw_phase_refs:
        if not isinstance(raw_ref, str) or not raw_ref.startswith("phases/"):
            raise ValueError("ROADMAP phase_ref must use phases/<id>/PHASE.yaml")
        logical_ref = "process/" + raw_ref
        phase = _load_object(root, logical_ref, process_root, object_overrides)
        sources.append(_source_receipt(root, logical_ref, process_root, object_overrides))
        phase_id = str(phase.get("phase_id") or "")
        status = str(phase.get("status") or "").lower()
        if not phase_id or not status:
            raise ValueError(f"Phase identity/status missing: {logical_ref}")
        phase_statuses[phase_id] = status
        if status == "active":
            active_phases.append(phase_id)
        work_refs = phase.get("work_refs") or []
        if not isinstance(work_refs, list):
            raise ValueError(f"Phase work_refs must be a list: {logical_ref}")
        for work_ref in work_refs:
            if not isinstance(work_ref, str) or not work_ref.startswith("works/"):
                raise ValueError(f"Phase work_ref is unsafe: {work_ref}")
            if work_ref in seen_work_refs:
                continue
            seen_work_refs.add(work_ref)
            work_logical = "process/" + work_ref
            work = _load_object(root, work_logical, process_root)
            sources.append(_source_receipt(root, work_logical, process_root))
            if str(work.get("status") or "").lower() not in TERMINAL_WORK:
                active_works.append(str(work.get("work_id") or Path(work_ref).parent.name))
    active_crs, cr_sources = _active_cr_ids(root, process_root)
    sources.extend(cr_sources)
    source_digest = _canonical_digest(sources)
    return {
        "schema_version": 1,
        "project_status": str(project.get("status") or "").lower(),
        "roadmap_status": str(roadmap.get("status") or "").lower(),
        "phase_statuses": dict(sorted(phase_statuses.items())),
        "active_phase_ids": sorted(active_phases),
        "active_work_ids": sorted(active_works),
        "active_cr_ids": active_crs,
        "source_refs": [item["ref"] for item in sources],
        "source_digest": source_digest,
    }


def derive_formal_truth_patch(
    state: dict[str, Any],
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    active_phases = list(snapshot["active_phase_ids"])
    active_works = list(snapshot["active_work_ids"])
    active_crs = list(snapshot["active_cr_ids"])
    if len(active_crs) > 1:
        next_action = {
            "type": "resolve_multiple_active_changes",
            "text": "Resolve multiple active formal CRs before continuing.",
            "stop_reason": None,
        }
        active_change = None
    elif active_crs:
        active_change = active_crs[0]
        next_action = {
            "type": "continue_active_change",
            "text": f"Continue active formal change {active_change}.",
            "stop_reason": None,
        }
    elif active_works:
        active_change = None
        next_action = {
            "type": "continue_active_work",
            "text": f"Continue active Work {active_works[0]}.",
            "stop_reason": None,
        }
    elif active_phases:
        active_change = None
        next_action = {
            "type": "continue_active_phase",
            "text": f"Continue active Phase {active_phases[0]} using its declared results.",
            "stop_reason": None,
        }
    else:
        active_change = None
        next_action = {
            "type": "review_project_completion",
            "text": "Review project and roadmap completion state.",
            "stop_reason": None,
        }
    current_phase = active_phases[0] if len(active_phases) == 1 else (
        "multiple-active-phases" if active_phases else "project-completion"
    )
    merged_refs = list(
        dict.fromkeys(
            [
                *(ref for ref in state.get("source_refs", []) if isinstance(ref, str)),
                *snapshot["source_refs"],
            ]
        )
    )
    return {
        "current_phase": current_phase,
        "active_change": active_change,
        "blocked": len(active_phases) > 1 or len(active_crs) > 1,
        "next_action": next_action,
        "formal_truth_projection": snapshot,
        "source_refs": merged_refs[:24],
    }


__all__ = ["build_formal_truth_snapshot", "derive_formal_truth_patch"]
