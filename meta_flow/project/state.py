"""Refs-only PROJECT.current.json validation."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meta_flow.checks.token_budget import format_bytes
from meta_flow.project import roadmap as project_roadmap
from meta_flow.project import scale as project_scale

PROJECT_CURRENT_REL = Path("process/project/PROJECT.current.json")
PROJECT_CURRENT_SCHEMA_VERSION = 1
PROJECT_CURRENT_MAX_BYTES = 16 * 1024
PROJECT_CURRENT_ALLOWED_KEYS = {
    "schema_version",
    "project_id",
    "project_name",
    "project_uid",
    "scale_ref",
    "roadmap_ref",
    "milestones_ref",
    "active_governance_refs",
    "source_refs",
    "updated_at",
}
PROJECT_CURRENT_REQUIRED_KEYS = {
    "schema_version",
    "project_id",
    "project_name",
    "updated_at",
}
PROJECT_CURRENT_REF_KEYS = {
    "scale_ref",
    "roadmap_ref",
    "milestones_ref",
}
PROJECT_CURRENT_FORBIDDEN_KEY_PARTS = (
    "credential",
    "secret",
    "token",
    "cookie",
    "private_key",
    "private-key",
)
PROJECT_CURRENT_FORBIDDEN_KEYS = {
    "history",
    "ledger",
    "transcript",
    "full_hld",
    "full_roadmap",
    "credentials",
    "secret",
    "token",
    "private_key",
    "private-key",
}


@dataclass(frozen=True)
class ProjectCurrentFinding:
    severity: str
    code: str
    message: str
    key: str | None = None

    def as_cli_line(self) -> str:
        return self.message


@dataclass(frozen=True)
class ProjectSnapshot:
    current: dict[str, Any]
    scale: project_scale.ProjectScale
    roadmap: project_roadmap.Roadmap
    milestones: project_roadmap.Milestones


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _finding(
    findings: list[ProjectCurrentFinding],
    severity: str,
    code: str,
    message: str,
    *,
    key: str | None = None,
) -> None:
    findings.append(ProjectCurrentFinding(severity=severity, code=code, message=message, key=key))


def _json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8"))


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key).lower()
            if key_text in PROJECT_CURRENT_FORBIDDEN_KEYS:
                return True
            if any(part in key_text for part in PROJECT_CURRENT_FORBIDDEN_KEY_PARTS):
                return True
            if _contains_forbidden_key(nested):
                return True
    if isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def is_relative_project_ref(value: str) -> bool:
    path = Path(value)
    if not value or path.is_absolute():
        return False
    if ".." in path.parts:
        return False
    if value.startswith("process/quant-lab/") or value == "process/quant-lab":
        return False
    return True


def validate_project_ref(
    value: Any,
    *,
    key: str,
    findings: list[ProjectCurrentFinding],
    must_exist: bool,
    project_root: Path | None,
) -> None:
    if value in (None, ""):
        return
    if not isinstance(value, str):
        _finding(findings, "ERROR", "ref_type", f"{key} must be a relative path string", key=key)
        return
    if not is_relative_project_ref(value):
        _finding(findings, "ERROR", "ref_path", f"{key} must be a project-relative path and must not escape project root", key=key)
        return
    if must_exist and project_root is not None:
        from meta_flow.project.process_route import _resolve_runtime_path

        try:
            target_exists = _resolve_runtime_path(project_root, value).is_file()
        except OSError:
            target_exists = False
        if not target_exists:
            _finding(findings, "ERROR", "ref_broken", f"{key} points to missing file: {value}", key=key)


def validate_project_current_payload(
    payload: dict[str, Any],
    *,
    byte_size: int | None = None,
    project_root: Path | None = None,
    require_ref_targets: bool = False,
) -> list[ProjectCurrentFinding]:
    findings: list[ProjectCurrentFinding] = []
    actual_size = byte_size if byte_size is not None else _json_size(payload)
    if actual_size > PROJECT_CURRENT_MAX_BYTES:
        _finding(
            findings,
            "ERROR",
            "E_PROJECT_STATE_OVER_BUDGET",
            f"PROJECT.current.json exceeds budget: {format_bytes(actual_size)} > {format_bytes(PROJECT_CURRENT_MAX_BYTES)}",
        )
    if payload.get("schema_version") != PROJECT_CURRENT_SCHEMA_VERSION:
        _finding(
            findings,
            "ERROR",
            "schema_version",
            f"schema_version must be {PROJECT_CURRENT_SCHEMA_VERSION}",
            key="schema_version",
        )
    for key in sorted(PROJECT_CURRENT_REQUIRED_KEYS):
        if key not in payload:
            _finding(findings, "ERROR", "missing_required", f"missing required field: {key}", key=key)
    for key in sorted(set(payload) - PROJECT_CURRENT_ALLOWED_KEYS):
        _finding(findings, "ERROR", "unknown_key", f"PROJECT.current.json contains unknown field: {key}", key=key)
    if _contains_forbidden_key(payload):
        _finding(
            findings,
            "ERROR",
            "forbidden_key",
            "PROJECT.current.json must not store history/ledger/transcript/full-doc/credential-like fields",
        )
    for key in ("project_id", "project_name", "project_uid", "updated_at"):
        if key in payload and payload[key] not in (None, "") and not isinstance(payload[key], str):
            _finding(findings, "ERROR", "field_type", f"{key} must be a string", key=key)
    for key in PROJECT_CURRENT_REF_KEYS:
        validate_project_ref(
            payload.get(key),
            key=key,
            findings=findings,
            must_exist=require_ref_targets,
            project_root=project_root,
        )

    active_refs = payload.get("active_governance_refs", [])
    if active_refs in (None, ""):
        active_refs = []
    if not isinstance(active_refs, list) or not all(isinstance(item, str) for item in active_refs):
        _finding(findings, "ERROR", "field_type", "active_governance_refs must be a list of strings", key="active_governance_refs")
    elif len(active_refs) > 20:
        _finding(findings, "ERROR", "field_budget", "active_governance_refs exceeds item budget: 20", key="active_governance_refs")
    else:
        for index, ref in enumerate(active_refs):
            validate_project_ref(
                ref,
                key=f"active_governance_refs[{index}]",
                findings=findings,
                must_exist=require_ref_targets,
                project_root=project_root,
            )

    source_refs = payload.get("source_refs", [])
    if source_refs in (None, ""):
        source_refs = []
    if not isinstance(source_refs, list):
        _finding(findings, "ERROR", "field_type", "source_refs must be a list", key="source_refs")
    elif len(source_refs) > 20:
        _finding(findings, "ERROR", "field_budget", "source_refs exceeds item budget: 20", key="source_refs")
    else:
        for index, item in enumerate(source_refs):
            if not isinstance(item, dict):
                _finding(findings, "ERROR", "field_type", f"source_refs[{index}] must be an object", key="source_refs")
                continue
            if set(item) - {"kind", "path"}:
                _finding(findings, "ERROR", "unknown_key", f"source_refs[{index}] contains unknown fields", key="source_refs")
            if not isinstance(item.get("kind"), str) or not item.get("kind"):
                _finding(findings, "ERROR", "field_type", f"source_refs[{index}].kind must be a non-empty string", key="source_refs")
            validate_project_ref(
                item.get("path"),
                key=f"source_refs[{index}].path",
                findings=findings,
                must_exist=require_ref_targets,
                project_root=project_root,
            )
    return findings


def project_current_path(project_root: Path) -> Path:
    from meta_flow.project.process_route import _resolve_runtime_ref

    return _resolve_runtime_ref(project_root, PROJECT_CURRENT_REL.as_posix())


def load_project_current(project_root: Path) -> dict[str, Any]:
    return _read_json(project_current_path(project_root))


def validate_project_current(
    project_root: Path,
    *,
    require_ref_targets: bool = True,
) -> tuple[list[str], list[str]]:
    root = project_root.resolve()
    path = project_current_path(root)
    if not path.is_file():
        return [f"PROJECT.current.json missing: {path}"], []
    try:
        payload = _read_json(path)
    except ValueError as exc:
        return [str(exc)], []
    findings = validate_project_current_payload(
        payload,
        byte_size=path.stat().st_size,
        project_root=root,
        require_ref_targets=require_ref_targets,
    )
    errors = [finding.as_cli_line() for finding in findings if finding.severity == "ERROR"]
    warnings = [finding.as_cli_line() for finding in findings if finding.severity == "WARN"]
    return errors, warnings


def _ref_value(payload: dict[str, Any], key: str, default: Path) -> str | Path:
    value = payload.get(key)
    if value in (None, ""):
        return default
    return str(value)


def _project_id_mismatch_finding(object_name: str, current_project_id: Any, object_project_id: str) -> project_scale.ProjectFinding | None:
    if not isinstance(current_project_id, str) or not current_project_id:
        return None
    if current_project_id != object_project_id:
        return project_scale.ProjectFinding(
            "ERROR",
            "project_id_mismatch",
            f"{object_name} project_id does not match PROJECT.current.json: {object_project_id} != {current_project_id}",
            key="project_id",
        )
    return None


def load_project_snapshot(project_root: Path) -> tuple[ProjectSnapshot | None, list[project_scale.ProjectFinding]]:
    root = project_root.resolve()
    current_path = project_current_path(root)
    if not current_path.is_file():
        return None, [project_scale.ProjectFinding("ERROR", "E_PROJECT_CURRENT_MISSING", f"PROJECT.current.json missing: {current_path}")]
    try:
        current_payload = _read_json(current_path)
    except ValueError as exc:
        return None, [project_scale.ProjectFinding("ERROR", "E_PROJECT_CURRENT_INVALID", str(exc))]

    current_findings = validate_project_current_payload(
        current_payload,
        byte_size=current_path.stat().st_size,
        project_root=root,
        require_ref_targets=True,
    )
    findings = [
        project_scale.ProjectFinding(finding.severity, finding.code, finding.message, finding.key)
        for finding in current_findings
    ]
    if any(finding.severity == "ERROR" for finding in findings):
        return None, findings

    if not any(current_payload.get(key) for key in PROJECT_CURRENT_REF_KEYS):
        return None, findings

    scale_snapshot, scale_findings = project_scale.validate_project_scale(
        root,
        _ref_value(current_payload, "scale_ref", project_scale.PROJECT_SCALE_REL),
    )
    roadmap_snapshot, roadmap_findings = project_roadmap.validate_roadmap(
        root,
        _ref_value(current_payload, "roadmap_ref", project_roadmap.ROADMAP_REL),
    )
    milestones_snapshot, milestone_findings = project_roadmap.validate_milestones(
        root,
        _ref_value(current_payload, "milestones_ref", project_roadmap.MILESTONES_REL),
    )
    findings.extend(scale_findings)
    findings.extend(roadmap_findings)
    findings.extend(milestone_findings)

    current_project_id = current_payload.get("project_id")
    if scale_snapshot is not None:
        mismatch = _project_id_mismatch_finding("PROJECT-SCALE.yaml", current_project_id, scale_snapshot.project_id)
        if mismatch is not None:
            findings.append(mismatch)
    if roadmap_snapshot is not None:
        mismatch = _project_id_mismatch_finding("ROADMAP.yaml", current_project_id, roadmap_snapshot.project_id)
        if mismatch is not None:
            findings.append(mismatch)
    if milestones_snapshot is not None:
        mismatch = _project_id_mismatch_finding("MILESTONES.yaml", current_project_id, milestones_snapshot.project_id)
        if mismatch is not None:
            findings.append(mismatch)

    findings.extend(project_roadmap.validate_roadmap_milestone_refs(roadmap_snapshot, milestones_snapshot))
    if any(finding.severity == "ERROR" for finding in findings):
        return None, findings
    if scale_snapshot is None or roadmap_snapshot is None or milestones_snapshot is None:
        return None, findings
    return (
        ProjectSnapshot(
            current=current_payload,
            scale=scale_snapshot,
            roadmap=roadmap_snapshot,
            milestones=milestones_snapshot,
        ),
        findings,
    )


def validate_project_objects(project_root: Path) -> tuple[list[str], list[str]]:
    _snapshot, findings = load_project_snapshot(project_root)
    errors = [finding.as_cli_line() for finding in findings if finding.severity == "ERROR"]
    warnings = [finding.as_cli_line() for finding in findings if finding.severity == "WARN"]
    return errors, warnings


def _print_project_check(errors: list[str], warnings: list[str]) -> None:
    print("Project Check: " + ("FAIL" if errors else "OK"))
    print("Project Current Check: " + ("FAIL" if errors else "OK"))
    for warning in warnings:
        print(f"- WARN: {warning}")
    for error in errors:
        print(f"- ERROR: {error}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow project check")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--allow-missing-ref-targets",
        action="store_true",
        help="Validate ref shape only; default check also reports broken reference targets.",
    )
    parsed = parser.parse_args(argv or [])
    if parsed.allow_missing_ref_targets:
        errors, warnings = validate_project_current(
            parsed.project_root,
            require_ref_targets=False,
        )
    else:
        errors, warnings = validate_project_objects(parsed.project_root)
    _print_project_check(errors, warnings)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
