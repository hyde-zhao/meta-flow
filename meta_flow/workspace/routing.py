"""Process workspace routing and health checks."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


ROUTE_METADATA_NAME = ".meta-flow-process.yaml"
PROCESS_SCAFFOLD_DIRS = ("checks", "checkpoints", "context", "changes")
BLOCKING_STATUSES = {
    "missing",
    "broken_link",
    "state_missing",
    "project_mismatch",
    "route_mismatch",
    "permission_denied",
}


@dataclass(frozen=True)
class ProcessRouteHealth:
    status: str
    project_root: Path
    link_path: Path
    state_path: Path
    routing_mode: str
    expected_project_name: str
    actual_target: Path | None = None
    metadata_path: Path | None = None
    artifact_root: Path | None = None
    project_process_root: Path | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    artifact_git_dirty: str = "unknown"

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    @property
    def blocking(self) -> bool:
        return self.status in BLOCKING_STATUSES

    def format_lines(self) -> list[str]:
        lines = [
            f"process_link_health: {self.status}",
            f"- project_root: {self.project_root}",
            f"- link_path: {self.link_path}",
            f"- routing_mode: {self.routing_mode}",
            f"- expected_project_name: {self.expected_project_name}",
        ]
        if self.actual_target is not None:
            lines.append(f"- actual_target: {self.actual_target}")
        if self.artifact_root is not None:
            lines.append(f"- artifact_root: {self.artifact_root}")
        if self.project_process_root is not None:
            lines.append(f"- project_process_root: {self.project_process_root}")
        if self.metadata_path is not None:
            lines.append(f"- metadata_path: {self.metadata_path}")
        lines.append(f"- state_path: {self.state_path}")
        lines.append(f"- artifact_git_dirty: {self.artifact_git_dirty}")
        lines.extend(f"- WARN: {warning}" for warning in self.warnings)
        lines.extend(f"- ERROR: {error}" for error in self.errors)
        return lines


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---", 4)
    if end == -1:
        return text
    return text[4:end]


def _scalar_value(frontmatter: str, key: str, *, section: str | None = None) -> str:
    in_section = section is None
    section_indent = ""
    for line in frontmatter.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if section is not None:
            if not line.startswith((" ", "\t")) and stripped == f"{section}:":
                in_section = True
                section_indent = line[: len(line) - len(line.lstrip())]
                continue
            if in_section and not line.startswith(f"{section_indent}  "):
                in_section = False
        if not in_section:
            continue
        candidate = stripped if section is not None else line
        if not candidate.startswith(f"{key}:"):
            continue
        raw = candidate.split(":", 1)[1].strip()
        return raw.strip('"').strip("'")
    return ""


def _read_key_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in _read_text(path).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _resolve_link_target(link_path: Path) -> Path | None:
    if not link_path.is_symlink():
        return None
    raw = os.readlink(link_path)
    target = Path(raw)
    if not target.is_absolute():
        target = link_path.parent / target
    return target.resolve(strict=False)


def _find_git_root(path: Path) -> Path | None:
    current = path.resolve(strict=False)
    for candidate in (current, *current.parents):
        git_dir = candidate / ".git"
        if git_dir.exists():
            return candidate
    return None


def _git_dirty_state(path: Path | None) -> str:
    if path is None:
        return "unknown"
    git_root = _find_git_root(path)
    if git_root is None:
        return "not-a-git-repo"
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=git_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError:
        return "git-unavailable"
    if result.returncode != 0:
        return "git-error"
    return "dirty" if result.stdout.strip() else "clean"


def _parse_state_summary(state_path: Path) -> tuple[str, dict[str, str]]:
    if not state_path.is_file():
        return "", {}
    try:
        frontmatter = _frontmatter(_read_text(state_path))
    except OSError:
        return "", {}
    project_id = _scalar_value(frontmatter, "project_id")
    artifact_routing = {
        "routing_mode": _scalar_value(frontmatter, "routing_mode", section="artifact_routing"),
        "artifact_root": _scalar_value(frontmatter, "artifact_root", section="artifact_routing"),
        "project_process_root": _scalar_value(frontmatter, "project_process_root", section="artifact_routing"),
        "link_path": _scalar_value(frontmatter, "link_path", section="artifact_routing"),
        "project_name": _scalar_value(frontmatter, "project_name", section="artifact_routing"),
    }
    return project_id, {key: value for key, value in artifact_routing.items() if value}


def check_process_route(project_root: Path) -> ProcessRouteHealth:
    project_root = project_root.resolve()
    link_path = project_root / "process"
    state_path = link_path / "STATE.md"
    project_id, state_routing = _parse_state_summary(state_path)
    expected_project_name = state_routing.get("project_name") or project_id or project_root.name
    routing_mode = state_routing.get("routing_mode", "")

    errors: list[str] = []
    warnings: list[str] = []
    actual_target: Path | None = None
    metadata_path: Path | None = None
    metadata: dict[str, str] = {}

    if link_path.is_symlink():
        actual_target = _resolve_link_target(link_path)
        routing_mode = routing_mode or "symlink"
        if actual_target is None or not actual_target.exists():
            errors.append("process symlink target does not exist")
            return ProcessRouteHealth(
                status="broken_link",
                project_root=project_root,
                link_path=link_path,
                state_path=state_path,
                routing_mode=routing_mode,
                expected_project_name=expected_project_name,
                actual_target=actual_target,
                errors=errors,
                warnings=warnings,
            )
        metadata_path = actual_target / ROUTE_METADATA_NAME
        metadata = _read_key_values(metadata_path)
        if not project_id and not state_routing.get("project_name") and metadata.get("project_name"):
            expected_project_name = metadata["project_name"]
    elif link_path.exists():
        routing_mode = routing_mode or "local-directory"
        metadata_path = link_path / ROUTE_METADATA_NAME
        metadata = _read_key_values(metadata_path)
        if not project_id and not state_routing.get("project_name") and metadata.get("project_name"):
            expected_project_name = metadata["project_name"]
        if routing_mode == "symlink":
            errors.append("STATE artifact_routing.routing_mode=symlink but process is not a symlink")
    else:
        routing_mode = routing_mode or "missing"
        errors.append("process path is missing")
        return ProcessRouteHealth(
            status="missing",
            project_root=project_root,
            link_path=link_path,
            state_path=state_path,
            routing_mode=routing_mode,
            expected_project_name=expected_project_name,
            errors=errors,
            warnings=warnings,
        )

    if not state_path.is_file():
        errors.append("process/STATE.md is missing")
        status = "state_missing"
    else:
        status = "ok"

    metadata_project = metadata.get("project_name")
    if metadata_project and metadata_project != expected_project_name:
        errors.append(
            f"route metadata project_name={metadata_project} does not match expected {expected_project_name}"
        )
        status = "project_mismatch"

    state_project_name = state_routing.get("project_name")
    if state_project_name and state_project_name != expected_project_name:
        errors.append(
            f"STATE artifact_routing.project_name={state_project_name} does not match expected {expected_project_name}"
        )
        status = "project_mismatch"

    state_process_root = state_routing.get("project_process_root")
    if actual_target is not None and state_process_root:
        expected_target = Path(state_process_root).expanduser().resolve(strict=False)
        if expected_target != actual_target:
            errors.append(
                f"STATE artifact_routing.project_process_root={expected_target} does not match symlink target={actual_target}"
            )
            status = "route_mismatch"

    artifact_root = None
    if state_routing.get("artifact_root"):
        artifact_root = Path(state_routing["artifact_root"]).expanduser().resolve(strict=False)
    elif metadata.get("artifact_root"):
        artifact_root = Path(metadata["artifact_root"]).expanduser().resolve(strict=False)

    project_process_root = actual_target or link_path
    if routing_mode == "local-directory":
        warnings.append("process is a local directory; this is legacy-compatible until artifact migration")

    if errors and status == "ok":
        status = "route_mismatch"

    return ProcessRouteHealth(
        status=status,
        project_root=project_root,
        link_path=link_path,
        state_path=state_path,
        routing_mode=routing_mode,
        expected_project_name=expected_project_name,
        actual_target=actual_target,
        metadata_path=metadata_path,
        artifact_root=artifact_root,
        project_process_root=project_process_root,
        errors=errors,
        warnings=warnings,
        artifact_git_dirty=_git_dirty_state(project_process_root),
    )


def require_process_health(project_root: Path) -> ProcessRouteHealth:
    health = check_process_route(project_root)
    if health.blocking:
        lines = [
            "Process route health check failed; workflow is blocked until the process route is restored.",
            *health.format_lines(),
            "",
            "Provide a valid artifact root and relink the workspace, for example:",
            "  meta-flow workspace link --artifact-root /path/to/meta-flow-artifacts --project-name <project-name>",
            "",
            "Do not recreate process/STATE.md unless you explicitly intend to initialize a new workflow state.",
        ]
        raise SystemExit("\n".join(lines))
    return health


def write_route_metadata(
    *,
    project_root: Path,
    artifact_root: Path,
    project_name: str,
    process_root: Path,
    link_path: Path,
) -> Path:
    metadata_path = process_root / ROUTE_METADATA_NAME
    created_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    text = (
        f'project_name: "{project_name}"\n'
        f'project_root: "{project_root.resolve()}"\n'
        f'artifact_root: "{artifact_root.resolve()}"\n'
        f'process_root: "{process_root.resolve()}"\n'
        f'link_path: "{link_path}"\n'
        'routing_mode: "symlink"\n'
        f'created_at: "{created_at}"\n'
    )
    metadata_path.write_text(text, encoding="utf-8")
    return metadata_path


def link_process_workspace(project_root: Path, artifact_root: Path, project_name: str) -> ProcessRouteHealth:
    project_root = project_root.resolve()
    artifact_root = artifact_root.expanduser().resolve(strict=False)
    process_root = artifact_root / "process" / project_name
    link_path = project_root / "process"
    process_root.mkdir(parents=True, exist_ok=True)
    for dirname in PROCESS_SCAFFOLD_DIRS:
        (process_root / dirname).mkdir(parents=True, exist_ok=True)

    if link_path.exists() or link_path.is_symlink():
        if not link_path.is_symlink():
            raise SystemExit(
                f"Cannot create process symlink because {link_path} already exists as a regular path. "
                "Migrate or move it first."
            )
        current_target = _resolve_link_target(link_path)
        if current_target != process_root.resolve(strict=False):
            raise SystemExit(
                f"Cannot relink existing process symlink automatically.\n"
                f"Current target: {current_target}\n"
                f"Requested target: {process_root.resolve(strict=False)}"
            )
    else:
        link_path.symlink_to(process_root, target_is_directory=True)

    write_route_metadata(
        project_root=project_root,
        artifact_root=artifact_root,
        project_name=project_name,
        process_root=process_root,
        link_path=link_path,
    )
    return check_process_route(project_root)
