"""PROJECT → ROADMAP → declared Phase 的长期治理投影检查。"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from meta_flow.project.model import Project, is_safe_ref, load_project
from meta_flow.project.scale import load_yaml_object

GOVERNANCE_PROJECTION_REL = Path("governance/GOVERNANCE-BASELINE.json")
GOVERNANCE_PROJECTION_KIND = "GovernanceBaselineProjectionV1"
GOVERNANCE_PROJECTION_SCHEMA_VERSION = 1
PHASE_STATUSES = frozenset({"planned", "active", "blocked", "completed", "archived"})
RUNTIME_IDENTITY_ROLES = ("release_head", "process_head")
_OID_RE = re.compile(r"^[0-9a-f]{40}$")


def _logical(ref: str) -> str:
    return f"process/{ref}"


def _safe_file(process_root: Path, ref: str, *, subject: str) -> Path:
    if not is_safe_ref(ref):
        raise ValueError(f"{subject} is not a safe process-relative ref: {ref}")
    path = process_root / ref
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{subject} does not resolve to a regular file: {_logical(ref)}")
    return path


def _string_list(value: Any, *, subject: str) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise ValueError(f"{subject} must be a list of non-empty strings")
    if len(value) != len(set(value)):
        raise ValueError(f"{subject} must not contain duplicate refs")
    return list(value)


def build_governance_truth(process_root: Path) -> dict[str, Any]:
    """Build the six-object long-term declaration closure without sibling discovery."""

    root = process_root.resolve()
    project: Project = load_project(root)
    if not project.roadmap_ref:
        raise ValueError("PROJECT.yaml does not declare roadmap_ref")
    roadmap_path = _safe_file(root, project.roadmap_ref, subject="PROJECT.roadmap_ref")
    roadmap = load_yaml_object(roadmap_path)
    if roadmap.get("schema_version") != 1:
        raise ValueError("ROADMAP.yaml schema_version must be 1")
    if roadmap.get("project_id") != project.project_id:
        raise ValueError("ROADMAP.yaml project_id differs from PROJECT.yaml")
    if roadmap.get("status") not in {"planned", "active", "blocked", "completed"}:
        raise ValueError("ROADMAP.yaml status is invalid")
    phase_refs = _string_list(roadmap.get("phase_refs"), subject="ROADMAP.phase_refs")
    phase_statuses: dict[str, str] = {}
    active_phase_refs: list[str] = []
    phase_ids: set[str] = set()
    active_result_refs: list[str] = []

    for phase_ref in phase_refs:
        phase_path = _safe_file(root, phase_ref, subject="ROADMAP.phase_refs[]")
        phase = load_yaml_object(phase_path)
        if phase.get("schema_version") != 1:
            raise ValueError(f"{_logical(phase_ref)} schema_version must be 1")
        if phase.get("project_id") != project.project_id:
            raise ValueError(f"{_logical(phase_ref)} project_id differs from PROJECT.yaml")
        phase_id = phase.get("phase_id")
        if not isinstance(phase_id, str) or not phase_id:
            raise ValueError(f"{_logical(phase_ref)} phase_id must be non-empty")
        if phase_id in phase_ids:
            raise ValueError(f"duplicate declared phase_id: {phase_id}")
        phase_ids.add(phase_id)
        status = phase.get("status")
        if status not in PHASE_STATUSES:
            raise ValueError(f"{_logical(phase_ref)} status is invalid: {status}")
        logical_phase_ref = _logical(phase_ref)
        phase_statuses[logical_phase_ref] = str(status)
        result_refs = _string_list(
            phase.get("result_refs", []), subject=f"{logical_phase_ref}.result_refs"
        )
        for result_ref in result_refs:
            _safe_file(root, result_ref, subject=f"{logical_phase_ref}.result_refs[]")
        if status == "active":
            active_phase_refs.append(logical_phase_ref)
            active_result_refs.extend(_logical(ref) for ref in result_refs)

    if project.status == "active" and len(active_phase_refs) != 1:
        raise ValueError(
            "an active PROJECT must have exactly one active declared Phase: "
            f"found {len(active_phase_refs)}"
        )
    projection_ref = _logical(GOVERNANCE_PROJECTION_REL.as_posix())
    if active_phase_refs and projection_ref not in active_result_refs:
        raise ValueError(
            "the active Phase must declare the governance projection result_ref: "
            f"{projection_ref}"
        )
    return {
        "project_ref": "process/PROJECT.yaml",
        "roadmap_ref": _logical(project.roadmap_ref),
        "phase_refs": [_logical(ref) for ref in phase_refs],
        "phase_statuses": phase_statuses,
        "active_phase_refs": active_phase_refs,
        "active_result_refs": active_result_refs,
    }


def _semantic_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": payload.get("schema_version"),
        "kind": payload.get("kind"),
        "project_ref": payload.get("project_ref"),
        "roadmap_ref": payload.get("roadmap_ref"),
        "phase_refs": payload.get("phase_refs"),
        "phase_statuses": payload.get("phase_statuses"),
        "active_phase_refs": payload.get("active_phase_refs"),
        "active_result_refs": payload.get("active_result_refs"),
        "immutable_commit_roles": payload.get("immutable_commit_roles"),
        "runtime_identity_roles": payload.get("runtime_identity_roles"),
    }


def semantic_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        _semantic_payload(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def _head_oid(root: Path, *, repository: str, errors: list[str]) -> str:
    result = _git(root, "rev-parse", "--verify", "HEAD")
    oid = result.stdout.strip().lower()
    if result.returncode != 0 or not _OID_RE.fullmatch(oid):
        errors.append(f"{repository} repository HEAD is unavailable")
        return ""
    return oid


def validate_governance_projection(
    release_root: Path,
    process_root: Path,
) -> dict[str, Any]:
    """Validate declared truth, immutable commit roles, and runtime Git identities."""

    release = release_root.resolve()
    process = process_root.resolve()
    errors: list[str] = []
    try:
        truth = build_governance_truth(process)
    except (OSError, ValueError) as exc:
        return {
            "schema_version": 1,
            "kind": "GovernanceProjectionCheckV1",
            "decision": "BLOCKED",
            "errors": [str(exc)],
            "runtime_identity": {},
        }

    path = process / GOVERNANCE_PROJECTION_REL
    if path.is_symlink() or not path.is_file():
        errors.append(
            "governance projection is missing or not a regular file: "
            f"{_logical(GOVERNANCE_PROJECTION_REL.as_posix())}"
        )
        payload: dict[str, Any] = {}
    else:
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"governance projection is invalid JSON: {exc}")
            payload = {}
        else:
            if not isinstance(loaded, dict):
                errors.append("governance projection must be a JSON object")
                payload = {}
            else:
                payload = loaded

    allowed_keys = {
        "schema_version",
        "kind",
        "project_ref",
        "roadmap_ref",
        "phase_refs",
        "phase_statuses",
        "active_phase_refs",
        "active_result_refs",
        "immutable_commit_roles",
        "runtime_identity_roles",
        "semantic_digest",
    }
    if payload:
        unknown = sorted(set(payload) - allowed_keys)
        if unknown:
            errors.append(f"governance projection has unknown fields: {', '.join(unknown)}")
        if payload.get("schema_version") != GOVERNANCE_PROJECTION_SCHEMA_VERSION:
            errors.append("governance projection schema_version must be 1")
        if payload.get("kind") != GOVERNANCE_PROJECTION_KIND:
            errors.append(f"governance projection kind must be {GOVERNANCE_PROJECTION_KIND}")
        for key, expected in truth.items():
            if payload.get(key) != expected:
                errors.append(f"governance projection {key} differs from declared truth")
        if payload.get("runtime_identity_roles") != list(RUNTIME_IDENTITY_ROLES):
            errors.append(
                "runtime_identity_roles must be [release_head, process_head] without persisted OIDs"
            )
        if payload.get("semantic_digest") != semantic_digest(payload):
            errors.append("governance projection semantic_digest mismatch")

    release_head = _head_oid(release, repository="release", errors=errors)
    process_head = _head_oid(process, repository="process", errors=errors)
    roles = payload.get("immutable_commit_roles", []) if payload else []
    if not isinstance(roles, list):
        errors.append("immutable_commit_roles must be a list")
        roles = []
    seen_roles: set[str] = set()
    for index, item in enumerate(roles):
        if not isinstance(item, dict) or set(item) != {"role", "repository", "oid"}:
            errors.append(f"immutable_commit_roles[{index}] must use exact role/repository/oid shape")
            continue
        role = item.get("role")
        repository = item.get("repository")
        oid = item.get("oid")
        if not isinstance(role, str) or not role or role in seen_roles:
            errors.append(f"immutable_commit_roles[{index}].role is empty or duplicate")
            continue
        seen_roles.add(role)
        if repository not in {"release", "process"}:
            errors.append(f"immutable_commit_roles[{index}].repository is invalid")
            continue
        if not isinstance(oid, str) or not _OID_RE.fullmatch(oid):
            errors.append(f"immutable_commit_roles[{index}].oid must be lowercase 40-hex")
            continue
        repository_root = release if repository == "release" else process
        head_oid = release_head if repository == "release" else process_head
        if not head_oid:
            continue
        exists = _git(repository_root, "cat-file", "-e", f"{oid}^{{commit}}")
        if exists.returncode != 0:
            errors.append(f"immutable commit role {role} does not exist in {repository}")
            continue
        ancestor = _git(repository_root, "merge-base", "--is-ancestor", oid, head_oid)
        if ancestor.returncode != 0:
            errors.append(f"immutable commit role {role} is not an ancestor of {repository} HEAD")

    return {
        "schema_version": 1,
        "kind": "GovernanceProjectionCheckV1",
        "decision": "PASS" if not errors else "BLOCKED",
        "errors": errors,
        "runtime_identity": {
            "release_head": release_head,
            "process_head": process_head,
        },
        "declared_truth": truth,
    }


__all__ = [
    "GOVERNANCE_PROJECTION_KIND",
    "GOVERNANCE_PROJECTION_REL",
    "RUNTIME_IDENTITY_ROLES",
    "build_governance_truth",
    "semantic_digest",
    "validate_governance_projection",
]
