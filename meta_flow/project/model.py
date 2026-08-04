"""Meta Flow vNext 的轻量项目真相模型。"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meta_flow.project.read_contract import ReadContextProtocol
from meta_flow.project.scale import dump_yaml, load_yaml_object

PROJECT_FILE = Path("PROJECT.yaml")
PROJECT_SCHEMA_VERSION = 1
PROJECT_MAX_BYTES = 8 * 1024
PROJECT_STATUSES = {"planned", "active", "paused", "completed", "archived"}
PROJECT_ALLOWED_KEYS = {
    "schema_version",
    "project_id",
    "name",
    "objective",
    "status",
    "roadmap_ref",
    "active_phase_ref",
    "active_work_refs",
    "updated_at",
}
PROJECT_REQUIRED_KEYS = {"schema_version", "project_id", "name", "status"}
PROJECT_FORBIDDEN_KEY_PARTS = (
    "credential",
    "secret",
    "token",
    "cookie",
    "private_key",
    "private-key",
    "transcript",
)
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


@dataclass(frozen=True)
class ProjectFinding:
    severity: str
    code: str
    message: str
    key: str | None = None


@dataclass(frozen=True)
class Project:
    schema_version: int
    project_id: str
    name: str
    status: str
    objective: str = ""
    roadmap_ref: str = ""
    active_phase_ref: str = ""
    active_work_refs: tuple[str, ...] = ()
    updated_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "name": self.name,
            "status": self.status,
        }
        if self.objective:
            payload["objective"] = self.objective
        if self.roadmap_ref:
            payload["roadmap_ref"] = self.roadmap_ref
        if self.active_phase_ref:
            payload["active_phase_ref"] = self.active_phase_ref
        if self.active_work_refs:
            payload["active_work_refs"] = list(self.active_work_refs)
        if self.updated_at:
            payload["updated_at"] = self.updated_at
        return payload


def build_minimal_project(*, project_id: str, name: str) -> Project:
    """构造无 Roadmap/Phase 的最小 Project。"""

    return Project(
        schema_version=PROJECT_SCHEMA_VERSION,
        project_id=project_id,
        name=name,
        status="active",
    )


def _finding(
    findings: list[ProjectFinding],
    code: str,
    message: str,
    *,
    key: str | None = None,
) -> None:
    findings.append(ProjectFinding("ERROR", code, message, key))


def is_safe_ref(value: str, *, prefix: str | None = None) -> bool:
    path = Path(value)
    if not value or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return False
    if prefix is not None and path.parts[0] != prefix:
        return False
    return True


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            lowered = str(key).lower()
            if any(part in lowered for part in PROJECT_FORBIDDEN_KEY_PARTS):
                return True
            if _contains_forbidden_key(nested):
                return True
    elif isinstance(value, list | tuple):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def validate_project_payload(
    payload: Mapping[str, Any],
    *,
    byte_size: int | None = None,
) -> list[ProjectFinding]:
    findings: list[ProjectFinding] = []
    if byte_size is not None and byte_size > PROJECT_MAX_BYTES:
        _finding(
            findings,
            "project_over_budget",
            f"PROJECT.yaml exceeds {PROJECT_MAX_BYTES} bytes: {byte_size}",
        )
    unknown = sorted(set(payload) - PROJECT_ALLOWED_KEYS)
    for key in unknown:
        _finding(findings, "unknown_key", f"PROJECT.yaml contains unknown field: {key}", key=key)
    for key in sorted(PROJECT_REQUIRED_KEYS - set(payload)):
        _finding(
            findings, "missing_required", f"PROJECT.yaml missing required field: {key}", key=key
        )
    if _contains_forbidden_key(payload):
        _finding(
            findings, "forbidden_key", "PROJECT.yaml contains credential/transcript-like field"
        )

    if payload.get("schema_version") != PROJECT_SCHEMA_VERSION:
        _finding(
            findings,
            "schema_version",
            f"PROJECT.yaml schema_version must be {PROJECT_SCHEMA_VERSION}",
            key="schema_version",
        )
    project_id = payload.get("project_id")
    if not isinstance(project_id, str) or not _ID_RE.fullmatch(project_id):
        _finding(
            findings, "project_id", "project_id must be 1-64 safe ID characters", key="project_id"
        )
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        _finding(findings, "name", "name must be a non-empty string", key="name")
    status = payload.get("status")
    if status not in PROJECT_STATUSES:
        _finding(
            findings,
            "status",
            "status must be one of: " + ", ".join(sorted(PROJECT_STATUSES)),
            key="status",
        )
    for key in ("objective", "updated_at"):
        value = payload.get(key, "")
        if value not in (None, "") and not isinstance(value, str):
            _finding(findings, "field_type", f"{key} must be a string", key=key)

    roadmap_ref = payload.get("roadmap_ref", "")
    if roadmap_ref not in (None, ""):
        if not isinstance(roadmap_ref, str) or not is_safe_ref(roadmap_ref):
            _finding(
                findings,
                "ref_path",
                "roadmap_ref must be a safe process-repo-relative path",
                key="roadmap_ref",
            )
    phase_ref = payload.get("active_phase_ref", "")
    if phase_ref not in (None, ""):
        if not isinstance(phase_ref, str) or not is_safe_ref(phase_ref, prefix="phases"):
            _finding(
                findings,
                "ref_path",
                "active_phase_ref must be under phases/",
                key="active_phase_ref",
            )
    work_refs = payload.get("active_work_refs", [])
    if work_refs in (None, ""):
        work_refs = []
    if not isinstance(work_refs, list) or not all(
        isinstance(item, str) and is_safe_ref(item, prefix="works") for item in work_refs
    ):
        _finding(
            findings,
            "ref_path",
            "active_work_refs must be safe paths under works/",
            key="active_work_refs",
        )
    elif len(work_refs) != len(set(work_refs)):
        _finding(
            findings,
            "duplicate_ref",
            "active_work_refs must not contain duplicates",
            key="active_work_refs",
        )
    return findings


def project_from_payload(payload: Mapping[str, Any]) -> Project:
    findings = validate_project_payload(payload)
    if findings:
        raise ValueError("; ".join(finding.message for finding in findings))
    return Project(
        schema_version=int(payload["schema_version"]),
        project_id=str(payload["project_id"]),
        name=str(payload["name"]),
        status=str(payload["status"]),
        objective=str(payload.get("objective") or ""),
        roadmap_ref=str(payload.get("roadmap_ref") or ""),
        active_phase_ref=str(payload.get("active_phase_ref") or ""),
        active_work_refs=tuple(str(item) for item in payload.get("active_work_refs") or ()),
        updated_at=str(payload.get("updated_at") or ""),
    )


def load_project(
    process_root: Path,
    *,
    read_context: ReadContextProtocol | None = None,
) -> Project:
    path = process_root.resolve() / PROJECT_FILE
    if read_context is None:
        payload = load_yaml_object(path)
        byte_size = path.stat().st_size
    else:
        payload = read_context.read_yaml_object(
            PROJECT_FILE.as_posix(),
            loader=load_yaml_object,
        )
        byte_size = read_context.byte_size(PROJECT_FILE.as_posix())
    findings = validate_project_payload(payload, byte_size=byte_size)
    if findings:
        raise ValueError("; ".join(finding.message for finding in findings))
    return project_from_payload(payload)


def write_project_create_only(process_root: Path, project: Project) -> Path:
    path = process_root.resolve() / PROJECT_FILE
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"PROJECT.yaml already exists: {path}")
    findings = validate_project_payload(project.as_dict())
    if findings:
        raise ValueError("; ".join(finding.message for finding in findings))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(dump_yaml(project.as_dict()) + "\n")
    return path


def replace_project(
    process_root: Path,
    project: Project,
    *,
    expected_project_id: str,
) -> Project:
    current = load_project(process_root)
    if current.project_id != expected_project_id or project.project_id != expected_project_id:
        raise ValueError("PROJECT.yaml project_id changed")
    findings = validate_project_payload(project.as_dict())
    if findings:
        raise ValueError("; ".join(finding.message for finding in findings))
    path = process_root.resolve() / PROJECT_FILE
    temporary = path.with_name(f".{path.name}.tmp")
    if temporary.exists() or temporary.is_symlink():
        raise FileExistsError(f"temporary project path already exists: {temporary}")
    try:
        temporary.write_text(dump_yaml(project.as_dict()) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()
    return load_project(process_root)
