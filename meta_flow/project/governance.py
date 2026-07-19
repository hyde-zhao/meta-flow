"""弹性 Project -> [Roadmap] -> [Phase] -> Work 治理对象。"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meta_flow.project.model import Project, is_safe_ref, load_project
from meta_flow.project.scale import dump_yaml, load_yaml_object
from meta_flow.work.model import load_work

ROADMAP_FILE = Path("ROADMAP.yaml")
ROADMAP_SCHEMA_VERSION = 1
PHASE_SCHEMA_VERSION = 1
GOVERNANCE_MAX_BYTES = 12 * 1024
ROADMAP_STATUSES = {"planned", "active", "paused", "completed", "archived"}
PHASE_STATUSES = {"planned", "active", "paused", "blocked", "completed", "cancelled", "archived"}
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


@dataclass(frozen=True)
class GovernanceFinding:
    severity: str
    code: str
    message: str
    ref: str = ""


@dataclass(frozen=True)
class Roadmap:
    schema_version: int
    project_id: str
    outcome: str
    status: str
    phase_refs: tuple[str, ...] = ()
    updated_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "outcome": self.outcome,
            "status": self.status,
            "phase_refs": list(self.phase_refs),
        }
        if self.updated_at:
            payload["updated_at"] = self.updated_at
        return payload


@dataclass(frozen=True)
class Phase:
    schema_version: int
    project_id: str
    phase_id: str
    objective: str
    status: str
    work_refs: tuple[str, ...] = ()
    result_refs: tuple[str, ...] = ()
    updated_at: str = ""

    @property
    def phase_ref(self) -> str:
        return f"phases/{self.phase_id}/PHASE.yaml"

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "phase_id": self.phase_id,
            "objective": self.objective,
            "status": self.status,
            "work_refs": list(self.work_refs),
            "result_refs": list(self.result_refs),
        }
        if self.updated_at:
            payload["updated_at"] = self.updated_at
        return payload


@dataclass(frozen=True)
class GovernanceSnapshot:
    project: Project
    roadmap: Roadmap | None
    active_phase: Phase | None
    active_works: tuple[Any, ...]
    objects_read: int


def _finding(findings: list[GovernanceFinding], code: str, message: str, ref: str = "") -> None:
    findings.append(GovernanceFinding("ERROR", code, message, ref))


def _valid_project_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_ID_RE.fullmatch(value))


def _string_refs(value: Any, *, prefix: str) -> tuple[tuple[str, ...], str]:
    if not isinstance(value, list):
        return (), "must be a list"
    if not all(isinstance(item, str) and is_safe_ref(item, prefix=prefix) for item in value):
        return (), f"must contain safe refs under {prefix}/"
    if len(value) != len(set(value)):
        return (), "must not contain duplicate refs"
    return tuple(value), ""


def validate_roadmap_payload(
    payload: Mapping[str, Any],
    *,
    byte_size: int | None = None,
) -> list[GovernanceFinding]:
    findings: list[GovernanceFinding] = []
    allowed = {"schema_version", "project_id", "outcome", "status", "phase_refs", "updated_at"}
    required = {"schema_version", "project_id", "outcome", "status", "phase_refs"}
    if byte_size is not None and byte_size > GOVERNANCE_MAX_BYTES:
        _finding(findings, "roadmap_over_budget", f"ROADMAP.yaml exceeds {GOVERNANCE_MAX_BYTES} bytes")
    for key in sorted(set(payload) - allowed):
        _finding(findings, "unknown_key", f"ROADMAP.yaml contains unknown field: {key}")
    for key in sorted(required - set(payload)):
        _finding(findings, "missing_required", f"ROADMAP.yaml missing required field: {key}")
    if payload.get("schema_version") != ROADMAP_SCHEMA_VERSION:
        _finding(findings, "schema_version", f"ROADMAP schema_version must be {ROADMAP_SCHEMA_VERSION}")
    if not _valid_project_id(payload.get("project_id")):
        _finding(findings, "project_id", "ROADMAP project_id is invalid")
    if not isinstance(payload.get("outcome"), str) or not str(payload.get("outcome") or "").strip():
        _finding(findings, "outcome", "ROADMAP outcome must be non-empty")
    if payload.get("status") not in ROADMAP_STATUSES:
        _finding(findings, "status", "ROADMAP status is invalid")
    _refs, error = _string_refs(payload.get("phase_refs"), prefix="phases")
    if error:
        _finding(findings, "phase_refs", f"phase_refs {error}")
    return findings


def roadmap_from_payload(payload: Mapping[str, Any]) -> Roadmap:
    findings = validate_roadmap_payload(payload)
    if findings:
        raise ValueError("; ".join(item.message for item in findings))
    return Roadmap(
        schema_version=int(payload["schema_version"]),
        project_id=str(payload["project_id"]),
        outcome=str(payload["outcome"]),
        status=str(payload["status"]),
        phase_refs=tuple(str(item) for item in payload["phase_refs"]),
        updated_at=str(payload.get("updated_at") or ""),
    )


def validate_phase_payload(
    payload: Mapping[str, Any],
    *,
    byte_size: int | None = None,
) -> list[GovernanceFinding]:
    findings: list[GovernanceFinding] = []
    allowed = {
        "schema_version",
        "project_id",
        "phase_id",
        "objective",
        "status",
        "work_refs",
        "result_refs",
        "updated_at",
    }
    required = allowed - {"updated_at"}
    if byte_size is not None and byte_size > GOVERNANCE_MAX_BYTES:
        _finding(findings, "phase_over_budget", f"PHASE.yaml exceeds {GOVERNANCE_MAX_BYTES} bytes")
    for key in sorted(set(payload) - allowed):
        _finding(findings, "unknown_key", f"PHASE.yaml contains unknown field: {key}")
    for key in sorted(required - set(payload)):
        _finding(findings, "missing_required", f"PHASE.yaml missing required field: {key}")
    if payload.get("schema_version") != PHASE_SCHEMA_VERSION:
        _finding(findings, "schema_version", f"PHASE schema_version must be {PHASE_SCHEMA_VERSION}")
    if not _valid_project_id(payload.get("project_id")):
        _finding(findings, "project_id", "PHASE project_id is invalid")
    if not _valid_project_id(payload.get("phase_id")):
        _finding(findings, "phase_id", "phase_id is invalid")
    if not isinstance(payload.get("objective"), str) or not str(payload.get("objective") or "").strip():
        _finding(findings, "objective", "PHASE objective must be non-empty")
    if payload.get("status") not in PHASE_STATUSES:
        _finding(findings, "status", "PHASE status is invalid")
    _work_refs, work_error = _string_refs(payload.get("work_refs"), prefix="works")
    if work_error:
        _finding(findings, "work_refs", f"work_refs {work_error}")
    result_refs = payload.get("result_refs")
    if not isinstance(result_refs, list) or not all(
        isinstance(item, str) and is_safe_ref(item) for item in result_refs
    ):
        _finding(findings, "result_refs", "result_refs must contain safe process-repo-relative refs")
    elif len(result_refs) != len(set(result_refs)):
        _finding(findings, "result_refs", "result_refs must not contain duplicate refs")
    return findings


def phase_from_payload(payload: Mapping[str, Any]) -> Phase:
    findings = validate_phase_payload(payload)
    if findings:
        raise ValueError("; ".join(item.message for item in findings))
    return Phase(
        schema_version=int(payload["schema_version"]),
        project_id=str(payload["project_id"]),
        phase_id=str(payload["phase_id"]),
        objective=str(payload["objective"]),
        status=str(payload["status"]),
        work_refs=tuple(str(item) for item in payload["work_refs"]),
        result_refs=tuple(str(item) for item in payload["result_refs"]),
        updated_at=str(payload.get("updated_at") or ""),
    )


def load_roadmap(process_root: Path, ref: str = ROADMAP_FILE.as_posix()) -> Roadmap:
    if not is_safe_ref(ref):
        raise ValueError("roadmap ref is unsafe")
    path = process_root.resolve() / ref
    payload = load_yaml_object(path)
    findings = validate_roadmap_payload(payload, byte_size=path.stat().st_size)
    if findings:
        raise ValueError("; ".join(item.message for item in findings))
    return roadmap_from_payload(payload)


def load_phase(process_root: Path, ref: str) -> Phase:
    if not is_safe_ref(ref, prefix="phases"):
        raise ValueError("phase ref must be under phases/")
    path = process_root.resolve() / ref
    payload = load_yaml_object(path)
    findings = validate_phase_payload(payload, byte_size=path.stat().st_size)
    if findings:
        raise ValueError("; ".join(item.message for item in findings))
    phase = phase_from_payload(payload)
    if phase.phase_ref != ref:
        raise ValueError(f"phase ref does not match phase_id: {ref} != {phase.phase_ref}")
    return phase


def _write_create_only(path: Path, payload: dict[str, Any]) -> Path:
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"governance object already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(dump_yaml(payload) + "\n")
    return path


def write_roadmap_create_only(process_root: Path, roadmap: Roadmap) -> Path:
    findings = validate_roadmap_payload(roadmap.as_dict())
    if findings:
        raise ValueError("; ".join(item.message for item in findings))
    return _write_create_only(process_root.resolve() / ROADMAP_FILE, roadmap.as_dict())


def write_phase_create_only(process_root: Path, phase: Phase) -> Path:
    findings = validate_phase_payload(phase.as_dict())
    if findings:
        raise ValueError("; ".join(item.message for item in findings))
    return _write_create_only(process_root.resolve() / phase.phase_ref, phase.as_dict())


def replace_phase(
    process_root: Path,
    phase: Phase,
    *,
    expected_phase_id: str,
) -> Path:
    if phase.phase_id != expected_phase_id:
        raise ValueError("phase_id changed during phase replacement")
    findings = validate_phase_payload(phase.as_dict())
    if findings:
        raise ValueError("; ".join(item.message for item in findings))
    path = process_root.resolve() / phase.phase_ref
    current = load_phase(process_root, phase.phase_ref)
    if current.phase_id != expected_phase_id or current.project_id != phase.project_id:
        raise ValueError("Phase identity changed before replacement")
    temporary = path.with_name(f".{path.name}.tmp")
    if temporary.exists() or temporary.is_symlink():
        raise FileExistsError(f"temporary Phase path already exists: {temporary}")
    try:
        temporary.write_text(dump_yaml(phase.as_dict()) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()
    return path


def load_governance_snapshot(process_root: Path) -> tuple[GovernanceSnapshot | None, list[GovernanceFinding]]:
    root = process_root.resolve()
    findings: list[GovernanceFinding] = []
    objects_read = 0
    try:
        project = load_project(root)
        objects_read += 1
    except (OSError, ValueError) as exc:
        _finding(findings, "project_invalid", str(exc), "PROJECT.yaml")
        return None, findings

    roadmap: Roadmap | None = None
    if project.roadmap_ref:
        try:
            roadmap = load_roadmap(root, project.roadmap_ref)
            objects_read += 1
        except (OSError, ValueError) as exc:
            _finding(findings, "roadmap_invalid", str(exc), project.roadmap_ref)
        else:
            if roadmap.project_id != project.project_id:
                _finding(findings, "project_id_mismatch", "Roadmap project_id differs from Project", project.roadmap_ref)

    active_phase: Phase | None = None
    if project.active_phase_ref:
        try:
            active_phase = load_phase(root, project.active_phase_ref)
            objects_read += 1
        except (OSError, ValueError) as exc:
            _finding(findings, "phase_invalid", str(exc), project.active_phase_ref)
        else:
            if active_phase.project_id != project.project_id:
                _finding(findings, "project_id_mismatch", "Phase project_id differs from Project", project.active_phase_ref)
            if roadmap is not None and project.active_phase_ref not in roadmap.phase_refs:
                _finding(findings, "orphan_phase", "active Phase is not referenced by Roadmap", project.active_phase_ref)

    works: list[Any] = []
    phase_work_refs = set(active_phase.work_refs if active_phase else ())
    for ref in project.active_work_refs:
        parts = Path(ref).parts
        if len(parts) != 3 or parts[0] != "works" or parts[2] != "WORK.yaml":
            _finding(findings, "work_ref", "active Work ref must be works/<id>/WORK.yaml", ref)
            continue
        try:
            work = load_work(root, parts[1])
            objects_read += 1
        except (OSError, ValueError) as exc:
            _finding(findings, "work_invalid", str(exc), ref)
            continue
        works.append(work)
        if work.project_id != project.project_id:
            _finding(findings, "project_id_mismatch", "Work project_id differs from Project", ref)
        if work.phase_ref:
            if active_phase is None or work.phase_ref != active_phase.phase_ref:
                _finding(findings, "work_parent", "Work phase_ref does not match active Phase", ref)
            if ref not in phase_work_refs:
                _finding(findings, "work_parent", "Phase does not reference its Work", ref)
        elif active_phase is not None and ref in phase_work_refs:
            _finding(findings, "work_parent", "direct Project Work must not appear in Phase work_refs", ref)
    if findings:
        return None, findings
    return (
        GovernanceSnapshot(
            project=project,
            roadmap=roadmap,
            active_phase=active_phase,
            active_works=tuple(works),
            objects_read=objects_read,
        ),
        findings,
    )
