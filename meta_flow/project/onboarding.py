"""独立过程仓项目初始化、路由与健康检查。"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from meta_flow.project.model import (
    PROJECT_FILE,
    Project,
    build_minimal_project,
    load_project,
    write_project_create_only,
)
from meta_flow.project.scale import dump_yaml, load_yaml_object
from meta_flow.workspace.git_sync import run_git

LAYOUT_VERSION = "independent-process-repo-v1"
WORKSPACE_BINDING_REL = Path(".meta-flow/workspace.yaml")
PROCESS_METADATA_REL = Path(".meta-flow-process.yaml")
PROCESS_LINK_REL = Path("process")
PROCESS_LINK_MODE_NONE = "none"
PROCESS_LINK_MODE_RELATIVE_SYMLINK = "relative-symlink"
ROUTE_MODE_SIBLING_BINDING = "sibling-binding"
ROUTE_MODE_RELATIVE_SYMLINK = "relative-symlink"
_PROCESS_LINK_MODES = {
    PROCESS_LINK_MODE_NONE,
    PROCESS_LINK_MODE_RELATIVE_SYMLINK,
}
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


@dataclass(frozen=True)
class ProjectInitRequest:
    project_root: Path
    project_id: str
    project_name: str
    process_repo_root: Path | None = None
    process_link_mode: str = PROCESS_LINK_MODE_NONE


@dataclass(frozen=True)
class RepositoryObservation:
    root: Path
    exists: bool
    is_git_repo: bool
    git_common_dir: Path | None = None
    branch: str = ""
    head_oid: str = ""
    dirty: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "exists": self.exists,
            "is_git_repo": self.is_git_repo,
            "git_common_dir": str(self.git_common_dir) if self.git_common_dir else "",
            "branch": self.branch,
            "head_oid": self.head_oid,
            "dirty": self.dirty,
        }


@dataclass(frozen=True)
class InitAction:
    action: str
    path: str
    reason: str


@dataclass(frozen=True)
class InitConflict:
    code: str
    path: str
    message: str


@dataclass(frozen=True)
class ProjectInitPlan:
    request: ProjectInitRequest
    project_root: Path
    process_repo_root: Path
    release_repo: RepositoryObservation
    process_repo: RepositoryObservation
    project: Project
    binding_payload: dict[str, Any]
    process_metadata_payload: dict[str, Any]
    actions: tuple[InitAction, ...]
    conflicts: tuple[InitConflict, ...]
    plan_digest: str

    @property
    def blocked(self) -> bool:
        return bool(self.conflicts)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "decision": "BLOCKED" if self.blocked else "READY",
            "project_id": self.request.project_id,
            "project_name": self.request.project_name,
            "project_root": str(self.project_root),
            "process_repo_root": str(self.process_repo_root),
            "process_link_mode": self.request.process_link_mode,
            "release_repo": self.release_repo.as_dict(),
            "process_repo": self.process_repo.as_dict(),
            "actions": [action.__dict__ for action in self.actions],
            "conflicts": [conflict.__dict__ for conflict in self.conflicts],
            "plan_digest": self.plan_digest,
            "mutation_count": 0,
        }


@dataclass(frozen=True)
class ProjectInitReceipt:
    plan_digest: str
    decision: str
    created_paths: tuple[str, ...]
    release_oid_before: str
    process_oid_after: str
    mutation_count: int
    recovery_route: str
    health_status: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "plan_digest": self.plan_digest,
            "decision": self.decision,
            "created_paths": list(self.created_paths),
            "release_oid_before": self.release_oid_before,
            "process_oid_after": self.process_oid_after,
            "mutation_count": self.mutation_count,
            "recovery_route": self.recovery_route,
            "health_status": self.health_status,
        }


@dataclass(frozen=True)
class IndependentProcessHealth:
    status: str
    project_id: str
    project_root: Path
    process_repo_root: Path | None
    route_mode: str
    link_text: str
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors and self.status == "healthy"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "layout_version": LAYOUT_VERSION,
            "status": self.status,
            "ok": self.ok,
            "project_id": self.project_id,
            "project_root": str(self.project_root),
            "process_repo_root": str(self.process_repo_root) if self.process_repo_root else "",
            "route_mode": self.route_mode,
            "link_text": self.link_text,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


class ProjectInitApplyError(RuntimeError):
    def __init__(self, message: str, receipt: ProjectInitReceipt) -> None:
        super().__init__(message)
        self.receipt = receipt


def _git_value(root: Path, args: list[str]) -> str:
    result = run_git(args, cwd=root)
    return result.stdout.strip() if result.ok else ""


def _observe_repo(root: Path) -> RepositoryObservation:
    resolved = root.resolve()
    if not resolved.exists() or not resolved.is_dir():
        return RepositoryObservation(root=resolved, exists=False, is_git_repo=False)
    top = _git_value(resolved, ["rev-parse", "--show-toplevel"])
    if not top or Path(top).resolve() != resolved:
        return RepositoryObservation(root=resolved, exists=True, is_git_repo=False)
    common_text = _git_value(resolved, ["rev-parse", "--git-common-dir"])
    common_dir = Path(common_text)
    if not common_dir.is_absolute():
        common_dir = resolved / common_dir
    status = run_git(["status", "--short"], cwd=resolved)
    return RepositoryObservation(
        root=resolved,
        exists=True,
        is_git_repo=True,
        git_common_dir=common_dir.resolve(),
        branch=_git_value(resolved, ["branch", "--show-current"]),
        head_oid=_git_value(resolved, ["rev-parse", "--verify", "HEAD"]),
        dirty=not status.ok or bool(status.stdout.strip()),
    )


def _default_process_root(project_root: Path, project_id: str) -> Path:
    return project_root.parent / f"{project_id}-process"


def _relative_single_component(path: Path, parent: Path) -> str:
    resolved = path.resolve()
    resolved_parent = parent.resolve()
    if resolved.parent != resolved_parent or resolved.name in {"", ".", ".."}:
        raise ValueError("process repo must be one sibling directory under workspace parent")
    return resolved.name


def _route_mode_for_link_mode(process_link_mode: str) -> str:
    if process_link_mode == PROCESS_LINK_MODE_NONE:
        return ROUTE_MODE_SIBLING_BINDING
    if process_link_mode == PROCESS_LINK_MODE_RELATIVE_SYMLINK:
        return ROUTE_MODE_RELATIVE_SYMLINK
    raise ValueError("process_link_mode must be none or relative-symlink")


def _binding_payload(
    project_id: str,
    process_repo_name: str,
    process_link_mode: str,
) -> dict[str, Any]:
    route_mode = _route_mode_for_link_mode(process_link_mode)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "layout_version": LAYOUT_VERSION,
        "workflow_model": "vnext",
        "project_id": project_id,
        "repo_role": "release",
        "route_mode": route_mode,
        "process_repo": {
            "anchor": "workspace_parent",
            "relative_path": process_repo_name,
        },
    }
    if process_link_mode == PROCESS_LINK_MODE_RELATIVE_SYMLINK:
        payload["process_link"] = PROCESS_LINK_REL.as_posix()
    return payload


def _process_metadata_payload(
    project_id: str,
    release_repo_name: str,
    route_mode: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "layout_version": LAYOUT_VERSION,
        "workflow_model": "vnext",
        "project_id": project_id,
        "repo_role": "process",
        "route_mode": route_mode,
        "release_repo": {
            "anchor": "workspace_parent",
            "relative_path": release_repo_name,
        },
    }


def _same_payload(path: Path, expected: dict[str, Any]) -> bool:
    if not path.is_file():
        return False
    try:
        return load_yaml_object(path) == expected
    except (OSError, ValueError):
        return False


def _is_empty_directory(path: Path) -> bool:
    try:
        return path.is_dir() and next(path.iterdir(), None) is None
    except OSError:
        return False


def _link_target(link_path: Path) -> tuple[str, Path | None]:
    if not link_path.is_symlink():
        return "", None
    text = os.readlink(link_path)
    target = Path(text)
    if target.is_absolute():
        return text, target.resolve()
    return text, (link_path.parent / target).resolve()


def _gitignore_has_process_entry(path: Path) -> bool:
    if not path.is_file():
        return False
    entries = {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    return bool(entries & {"process", "process/", "/process", "/process/"})


def _digest_payload(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def plan_project_init(request: ProjectInitRequest) -> ProjectInitPlan:
    project_root = request.project_root.resolve()
    process_root = (
        request.process_repo_root.resolve()
        if request.process_repo_root is not None
        else _default_process_root(project_root, request.project_id).resolve()
    )
    actions: list[InitAction] = []
    conflicts: list[InitConflict] = []

    if request.process_link_mode not in _PROCESS_LINK_MODES:
        conflicts.append(
            InitConflict(
                "invalid_process_link_mode",
                "process_link_mode",
                "process_link_mode must be none or relative-symlink",
            )
        )
    if not _SAFE_ID_RE.fullmatch(request.project_id):
        conflicts.append(InitConflict("invalid_project_id", "project_id", "project_id must use 1-64 safe ID characters"))
    if not request.project_name.strip():
        conflicts.append(InitConflict("invalid_project_name", "project_name", "project_name must not be empty"))
    if project_root == process_root:
        conflicts.append(InitConflict("same_repo", str(process_root), "release and process repo roots must differ"))
    try:
        process_repo_name = _relative_single_component(process_root, project_root.parent)
    except ValueError as exc:
        process_repo_name = process_root.name
        conflicts.append(InitConflict("not_sibling", str(process_root), str(exc)))

    release_repo = _observe_repo(project_root)
    process_repo = _observe_repo(process_root)
    if not release_repo.exists:
        if not project_root.parent.is_dir():
            conflicts.append(
                InitConflict(
                    "workspace_parent_missing",
                    str(project_root.parent),
                    "workspace parent must already exist",
                )
            )
        else:
            actions.append(InitAction("create", str(project_root), "create release repo directory"))
            actions.append(InitAction("git-init", str(project_root), "initialize release Git repo on main"))
    elif not release_repo.is_git_repo:
        if _is_empty_directory(project_root):
            actions.append(InitAction("git-init", str(project_root), "initialize empty release Git repo on main"))
        else:
            conflicts.append(
                InitConflict(
                    "release_not_git_root",
                    str(project_root),
                    "non-empty project root must already be the release Git repository root",
                )
            )

    if process_root.exists() and not process_root.is_dir():
        conflicts.append(InitConflict("process_not_directory", str(process_root), "process repo path exists and is not a directory"))
    elif not process_root.exists():
        actions.append(InitAction("create", str(process_root), "create independent process repo directory"))
        actions.append(InitAction("git-init", str(process_root), "initialize independent process Git repo on main"))
    elif not process_repo.is_git_repo:
        if _is_empty_directory(process_root):
            actions.append(InitAction("git-init", str(process_root), "initialize empty independent process Git repo on main"))
        else:
            conflicts.append(InitConflict("process_not_git", str(process_root), "non-empty process path is not a Git repository"))
    elif process_repo.git_common_dir == release_repo.git_common_dir:
        conflicts.append(InitConflict("shared_git_control", str(process_root), "release and process repo share Git common dir"))
    elif process_repo.branch and process_repo.branch != "main":
        conflicts.append(InitConflict("process_branch_conflict", str(process_root), "existing process repo must be on main"))

    project = build_minimal_project(project_id=request.project_id, name=request.project_name)
    project_path = process_root / PROJECT_FILE
    if project_path.exists() or project_path.is_symlink():
        try:
            existing = load_project(process_root)
        except (OSError, ValueError) as exc:
            conflicts.append(InitConflict("project_invalid", str(project_path), str(exc)))
        else:
            if existing.project_id != project.project_id or existing.name != project.name:
                conflicts.append(InitConflict("project_identity_conflict", str(project_path), "existing PROJECT.yaml identity differs from request"))
            else:
                actions.append(InitAction("noop", str(project_path), "matching project identity already exists; preserve evolved governance fields"))
    else:
        actions.append(InitAction("create", str(project_path), "write minimal PROJECT.yaml"))

    try:
        route_mode = _route_mode_for_link_mode(request.process_link_mode)
    except ValueError:
        route_mode = ROUTE_MODE_SIBLING_BINDING
    binding = (
        _binding_payload(request.project_id, process_repo_name, request.process_link_mode)
        if request.process_link_mode in _PROCESS_LINK_MODES
        else {}
    )
    binding_path = project_root / WORKSPACE_BINDING_REL
    if binding_path.exists() or binding_path.is_symlink():
        if _same_payload(binding_path, binding):
            actions.append(InitAction("noop", str(binding_path), "matching workspace binding already exists"))
        else:
            conflicts.append(InitConflict("binding_conflict", str(binding_path), "existing workspace binding differs"))
    else:
        actions.append(InitAction("create", str(binding_path), "write portable release-repo binding"))

    metadata = _process_metadata_payload(request.project_id, project_root.name, route_mode)
    metadata_path = process_root / PROCESS_METADATA_REL
    if metadata_path.exists() or metadata_path.is_symlink():
        if _same_payload(metadata_path, metadata):
            actions.append(InitAction("noop", str(metadata_path), "matching process metadata already exists"))
        else:
            conflicts.append(InitConflict("metadata_conflict", str(metadata_path), "existing process metadata differs"))
    else:
        actions.append(InitAction("create", str(metadata_path), "write portable process-repo metadata"))

    link_path = project_root / PROCESS_LINK_REL
    link_text, actual_target = _link_target(link_path)
    if request.process_link_mode == PROCESS_LINK_MODE_RELATIVE_SYMLINK:
        gitignore_path = project_root / ".gitignore"
        if _gitignore_has_process_entry(gitignore_path):
            actions.append(InitAction("noop", str(gitignore_path), "process link is already ignored"))
        elif gitignore_path.exists() and gitignore_path.is_file():
            actions.append(InitAction("append", str(gitignore_path), "ignore local process link"))
        elif gitignore_path.exists() or gitignore_path.is_symlink():
            conflicts.append(InitConflict("gitignore_conflict", str(gitignore_path), ".gitignore is not a regular file"))
        else:
            actions.append(InitAction("create", str(gitignore_path), "create ignore rule for local process link"))

        if link_path.is_symlink():
            if Path(link_text).is_absolute():
                conflicts.append(InitConflict("absolute_process_link", str(link_path), "process link must be relative"))
            elif actual_target != process_root:
                conflicts.append(InitConflict("process_link_conflict", str(link_path), "process link targets a different repository"))
            else:
                actions.append(InitAction("noop", str(link_path), "matching relative process link already exists"))
        elif link_path.exists():
            conflicts.append(InitConflict("process_path_conflict", str(link_path), "process path exists and is not a symlink"))
        else:
            actions.append(InitAction("create-link", str(link_path), "create local relative link to process repo"))
    elif link_path.exists() or link_path.is_symlink():
        conflicts.append(
            InitConflict(
                "unexpected_process_entry",
                str(link_path),
                "binding-only mode requires the release process entry to be absent",
            )
        )

    digest_source = {
        "schema_version": 1,
        "project_id": request.project_id,
        "project_name": request.project_name,
        "project_root": str(project_root),
        "process_repo_root": str(process_root),
        "process_link_mode": request.process_link_mode,
        "release_head_oid": release_repo.head_oid,
        "process_head_oid": process_repo.head_oid,
        "actions": [action.__dict__ for action in actions],
        "conflicts": [conflict.__dict__ for conflict in conflicts],
        "binding": binding,
        "process_metadata": metadata,
        "project": project.as_dict(),
    }
    return ProjectInitPlan(
        request=request,
        project_root=project_root,
        process_repo_root=process_root,
        release_repo=release_repo,
        process_repo=process_repo,
        project=project,
        binding_payload=binding,
        process_metadata_payload=metadata,
        actions=tuple(actions),
        conflicts=tuple(conflicts),
        plan_digest=_digest_payload(digest_source),
    )


def _write_yaml_create_only(path: Path, payload: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"path already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(dump_yaml(payload) + "\n")


def _append_process_ignore(path: Path) -> None:
    original = path.read_text(encoding="utf-8")
    separator = "" if not original or original.endswith("\n") else "\n"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(f"{separator}/process\n")


def apply_project_init(plan: ProjectInitPlan) -> ProjectInitReceipt:
    if plan.blocked:
        raise ValueError("project init plan is blocked: " + "; ".join(item.message for item in plan.conflicts))
    fresh = plan_project_init(plan.request)
    if fresh.plan_digest != plan.plan_digest:
        raise ValueError("project init plan is stale; rebuild dry-run plan before apply")

    created: list[str] = []
    mutations = 0
    try:
        if not plan.project_root.exists():
            plan.project_root.mkdir(parents=False)
            created.append(str(plan.project_root))
            mutations += 1
        if not _observe_repo(plan.project_root).is_git_repo:
            result = run_git(["init", "-b", "main"], cwd=plan.project_root)
            if not result.ok:
                raise RuntimeError(result.stderr.strip() or "release git init failed")
            created.append(str(plan.project_root / ".git"))
            mutations += 1
        if not plan.process_repo_root.exists():
            plan.process_repo_root.mkdir(parents=False)
            created.append(str(plan.process_repo_root))
            mutations += 1
        if not _observe_repo(plan.process_repo_root).is_git_repo:
            result = run_git(["init", "-b", "main"], cwd=plan.process_repo_root)
            if not result.ok:
                raise RuntimeError(result.stderr.strip() or "git init failed")
            created.append(str(plan.process_repo_root / ".git"))
            mutations += 1

        project_path = plan.process_repo_root / PROJECT_FILE
        if not project_path.exists() and not project_path.is_symlink():
            write_project_create_only(plan.process_repo_root, plan.project)
            created.append(str(project_path))
            mutations += 1
        metadata_path = plan.process_repo_root / PROCESS_METADATA_REL
        if not metadata_path.exists() and not metadata_path.is_symlink():
            _write_yaml_create_only(metadata_path, plan.process_metadata_payload)
            created.append(str(metadata_path))
            mutations += 1
        binding_path = plan.project_root / WORKSPACE_BINDING_REL
        if not binding_path.exists() and not binding_path.is_symlink():
            _write_yaml_create_only(binding_path, plan.binding_payload)
            created.append(str(binding_path))
            mutations += 1

        if plan.request.process_link_mode == PROCESS_LINK_MODE_RELATIVE_SYMLINK:
            gitignore_path = plan.project_root / ".gitignore"
            if not _gitignore_has_process_entry(gitignore_path):
                if gitignore_path.exists():
                    _append_process_ignore(gitignore_path)
                else:
                    gitignore_path.write_text("/process\n", encoding="utf-8")
                    created.append(str(gitignore_path))
                mutations += 1

            link_path = plan.project_root / PROCESS_LINK_REL
            if not link_path.is_symlink():
                link_text = os.path.relpath(plan.process_repo_root, start=plan.project_root)
                temporary = plan.project_root / f".process.meta-flow-init-{plan.plan_digest[:12]}"
                if temporary.exists() or temporary.is_symlink():
                    raise FileExistsError(f"temporary link path already exists: {temporary}")
                temporary.symlink_to(link_text, target_is_directory=True)
                os.replace(temporary, link_path)
                created.append(str(link_path))
                mutations += 1

        health = check_independent_process_route(plan.project_root)
        if not health.ok:
            raise RuntimeError("post-apply health failed: " + "; ".join(health.errors))
        process_after = _observe_repo(plan.process_repo_root)
        return ProjectInitReceipt(
            plan_digest=plan.plan_digest,
            decision="PASS",
            created_paths=tuple(created),
            release_oid_before=plan.release_repo.head_oid,
            process_oid_after=process_after.head_oid,
            mutation_count=mutations,
            recovery_route="none",
            health_status=health.status,
        )
    except Exception as exc:
        process_after = _observe_repo(plan.process_repo_root)
        receipt = ProjectInitReceipt(
            plan_digest=plan.plan_digest,
            decision="PARTIAL" if mutations else "BLOCKED",
            created_paths=tuple(created),
            release_oid_before=plan.release_repo.head_oid,
            process_oid_after=process_after.head_oid,
            mutation_count=mutations,
            recovery_route="inspect-created-paths-and-rerun-plan",
            health_status="apply_failed",
        )
        raise ProjectInitApplyError(str(exc), receipt) from exc


def _safe_sibling_from_binding(project_root: Path, binding: dict[str, Any]) -> Path:
    repo = binding.get("process_repo")
    if not isinstance(repo, dict) or repo.get("anchor") != "workspace_parent":
        raise ValueError("process_repo.anchor must be workspace_parent")
    relative = repo.get("relative_path")
    if not isinstance(relative, str) or not _SAFE_ID_RE.fullmatch(relative):
        raise ValueError("process_repo.relative_path must be one safe sibling name")
    workspace_parent = project_root.parent.resolve()
    resolved = (workspace_parent / relative).resolve()
    if resolved.parent != workspace_parent:
        raise ValueError("process_repo.relative_path must resolve to one sibling under workspace parent")
    return resolved


def resolve_process_repo_root(
    project_root: Path,
    binding: dict[str, Any] | None = None,
) -> Path:
    """从发布仓 binding 解析唯一过程仓根；不做 sibling discovery。"""

    root = project_root.resolve()
    payload = binding
    if payload is None:
        binding_path = root / WORKSPACE_BINDING_REL
        if not binding_path.is_file():
            raise ValueError(
                "vNext project is not initialized: .meta-flow/workspace.yaml is missing; "
                "run meta-flow project init and review the dry-run before --apply"
            )
        payload = load_yaml_object(binding_path)
    if payload.get("schema_version") != 1:
        raise ValueError("workspace binding schema_version must be 1")
    if payload.get("layout_version") != LAYOUT_VERSION:
        raise ValueError(
            "workspace binding is not a supported vNext layout; expected "
            "independent-process-repo-v1. New workspaces must use project init; "
            "legacy shared-subdirectory sources require a compatible snapshot-only migration flow"
        )
    if payload.get("repo_role") != "release" or payload.get("workflow_model") != "vnext":
        raise ValueError("workspace binding role/model mismatch")
    project_id = payload.get("project_id")
    if not isinstance(project_id, str) or not _SAFE_ID_RE.fullmatch(project_id):
        raise ValueError("workspace binding project_id is invalid")
    route_mode = payload.get("route_mode")
    if route_mode not in {ROUTE_MODE_SIBLING_BINDING, ROUTE_MODE_RELATIVE_SYMLINK}:
        raise ValueError("workspace binding route_mode must be sibling-binding or relative-symlink")
    if route_mode == ROUTE_MODE_SIBLING_BINDING and "process_link" in payload:
        raise ValueError("sibling-binding workspace binding must not declare process_link")
    if route_mode == ROUTE_MODE_RELATIVE_SYMLINK and payload.get("process_link") != PROCESS_LINK_REL.as_posix():
        raise ValueError("relative-symlink workspace binding process_link must be process")
    return _safe_sibling_from_binding(root, payload)


def check_independent_process_route(project_root: Path) -> IndependentProcessHealth:
    root = project_root.resolve()
    errors: list[str] = []
    warnings: list[str] = []
    project_id = ""
    route_mode = ""
    expected_process: Path | None = None
    binding_path = root / WORKSPACE_BINDING_REL
    if not binding_path.is_file():
        return IndependentProcessHealth(
            status="not_initialized",
            project_id="",
            project_root=root,
            process_repo_root=None,
            route_mode="",
            link_text="",
            errors=(
                "vNext project is not initialized: .meta-flow/workspace.yaml is missing; "
                "run meta-flow project init and review the dry-run before --apply",
            ),
        )
    try:
        binding = load_yaml_object(binding_path)
    except (OSError, ValueError) as exc:
        return IndependentProcessHealth(
            status="binding_invalid",
            project_id="",
            project_root=root,
            process_repo_root=None,
            route_mode="",
            link_text="",
            errors=(str(exc),),
        )
    project_id = str(binding.get("project_id") or "")
    route_mode = str(binding.get("route_mode") or "")
    try:
        expected_process = resolve_process_repo_root(root, binding)
    except (OSError, ValueError) as exc:
        errors.append(str(exc))

    link_path = root / PROCESS_LINK_REL
    link_text, actual_process = _link_target(link_path)
    if route_mode == ROUTE_MODE_SIBLING_BINDING:
        if link_path.exists() or link_path.is_symlink():
            errors.append("binding-only route requires the release process entry to be absent")
    elif route_mode == ROUTE_MODE_RELATIVE_SYMLINK:
        if not link_path.is_symlink():
            errors.append("process entry is missing or is not a symlink")
        elif Path(link_text).is_absolute():
            errors.append("process symlink must be relative")
        elif expected_process is not None and actual_process != expected_process:
            errors.append("process symlink target does not match workspace binding")

    process_root = expected_process
    if process_root is not None:
        release_repo = _observe_repo(root)
        process_repo = _observe_repo(process_root)
        if not release_repo.is_git_repo:
            errors.append("release root is not an independent Git repository root")
        if not process_repo.is_git_repo:
            errors.append("process root is not an independent Git repository root")
        elif release_repo.git_common_dir == process_repo.git_common_dir:
            errors.append("release and process repositories share Git common dir")
        metadata_path = process_root / PROCESS_METADATA_REL
        try:
            metadata = load_yaml_object(metadata_path)
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
        else:
            if metadata.get("schema_version") != 1 or metadata.get("layout_version") != LAYOUT_VERSION:
                errors.append("process metadata schema/layout mismatch")
            if metadata.get("repo_role") != "process" or metadata.get("workflow_model") != "vnext":
                errors.append("process metadata role/model mismatch")
            if metadata.get("project_id") != project_id:
                errors.append("process metadata project_id mismatch")
            if metadata.get("route_mode") != route_mode:
                errors.append("release/process binding route_mode mismatch")
            release = metadata.get("release_repo")
            if (
                not isinstance(release, dict)
                or release.get("anchor") != "workspace_parent"
                or not isinstance(release.get("relative_path"), str)
                or not _SAFE_ID_RE.fullmatch(release["relative_path"])
                or release.get("relative_path") != root.name
                or (process_root.parent / release.get("relative_path", "")).resolve() != root
            ):
                errors.append("process metadata release_repo route mismatch")
        project_path = process_root / PROJECT_FILE
        if not project_path.is_file():
            errors.append(
                "process repository is not initialized: PROJECT.yaml is missing; "
                "run meta-flow project init --apply"
            )
        else:
            try:
                project = load_project(process_root)
            except (OSError, ValueError) as exc:
                errors.append(str(exc))
            else:
                if project.project_id != project_id:
                    errors.append("PROJECT.yaml project_id mismatch")
    if route_mode == ROUTE_MODE_RELATIVE_SYMLINK and not _gitignore_has_process_entry(root / ".gitignore"):
        warnings.append("release repo does not ignore local process symlink")
    return IndependentProcessHealth(
        status="healthy" if not errors else "route_conflict",
        project_id=project_id,
        project_root=root,
        process_repo_root=process_root,
        route_mode=route_mode,
        link_text=link_text,
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


def init_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow project init")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--project-name", default=None)
    parser.add_argument("--process-repo-root", type=Path, default=None)
    parser.add_argument(
        "--process-link-mode",
        choices=sorted(_PROCESS_LINK_MODES),
        default=PROCESS_LINK_MODE_NONE,
        help="none uses portable binding only; relative-symlink enables legacy Agent/Skill path compatibility",
    )
    parser.add_argument("--apply", action="store_true")
    parsed = parser.parse_args(argv or [])
    request = ProjectInitRequest(
        project_root=parsed.project_root,
        project_id=parsed.project_id,
        project_name=parsed.project_name or parsed.project_id,
        process_repo_root=parsed.process_repo_root,
        process_link_mode=parsed.process_link_mode,
    )
    plan = plan_project_init(request)
    if not parsed.apply:
        print(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        return 1 if plan.blocked else 0
    try:
        receipt = apply_project_init(plan)
    except (ValueError, ProjectInitApplyError) as exc:
        output: dict[str, Any] = {"plan": plan.as_dict(), "error": str(exc)}
        if isinstance(exc, ProjectInitApplyError):
            output["receipt"] = exc.receipt.as_dict()
        print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
        return 1
    print(json.dumps({"plan": plan.as_dict(), "receipt": receipt.as_dict()}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def status_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow project status")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parsed = parser.parse_args(argv or [])
    health = check_independent_process_route(parsed.project_root)
    payload = health.as_dict()
    if health.ok and health.process_repo_root is not None:
        try:
            project = load_project(health.process_repo_root)
        except (OSError, ValueError) as exc:
            payload["ok"] = False
            payload["status"] = "project_invalid"
            payload["errors"] = [*payload["errors"], str(exc)]
        else:
            payload["project"] = project.as_dict()
            payload["default_governance_objects_read"] = 1
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(init_main(sys.argv[1:]))
