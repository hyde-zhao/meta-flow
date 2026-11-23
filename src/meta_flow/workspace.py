"""工作区初始化、contract 仓、子项目、链接与校验。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from . import global_store, templates

LOCAL_META = Path(".meta-flow")
INSTALL_REL = LOCAL_META / "install.yaml"
LOCAL_WORKSPACE = LOCAL_META / "workspace.yaml"
WORKSPACE_MANIFEST = "mf.workspace.yaml"
CONTRACT_ROLE = LOCAL_META / "role.yaml"
_IMPROVEMENTS_README = (
    "# MFP 改进包\n\n"
    "存放针对 meta-flow 工具本身的改进包 `MFP-*.yaml`。\n"
    "manager 创建并 `mf improve submit`；worker 在子项目创建本地 MFP，由 manager 导入。\n"
    "规范见 `standards/IMPROVEMENTS.md`。\n"
)
_TEMPLATES_README = "# 项目模板\n\n本目录由 manager 维护，worker 只读。\n"
_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")


class WorkspaceError(Exception):
    """工作区操作失败。"""

    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _dump_yaml(path: Path, data: dict[str, Any]) -> None:
    _write(
        path,
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False),
    )


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise WorkspaceError(f"缺少文件: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise WorkspaceError(f"{path} 不是合法 YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise WorkspaceError(f"{path} 顶层必须是映射")
    return data


def _digest_text(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def _digest_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "project"


def _as_dir(path: Path) -> Path:
    path = path.expanduser()
    return path.parent if path.is_file() else path


def find_workspace_root(start: Path) -> Path | None:
    current = _as_dir(start).resolve()
    for candidate in (current, *current.parents):
        if (candidate / LOCAL_WORKSPACE).is_file():
            return candidate
    return None


def find_contract_root(start: Path) -> Path | None:
    current = _as_dir(start).resolve()
    for candidate in (current, *current.parents):
        role = candidate / CONTRACT_ROLE
        if role.is_file() and (candidate / "workspace").is_dir():
            try:
                data = yaml.safe_load(role.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                data = {}
            if isinstance(data, dict) and data.get("role") == "manager":
                return candidate
    return None


def find_subproject_root(start: Path) -> Path | None:
    current = _as_dir(start).resolve()
    for candidate in (current, *current.parents):
        path = candidate / INSTALL_REL
        if path.is_file():
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                data = {}
            if isinstance(data, dict) and data.get("role") == "worker":
                return candidate
    return None


def detect_role(start: Path) -> tuple[str, Path | None]:
    """根据目录推导角色。"""
    current = _as_dir(start).resolve()
    home = global_store.global_home()
    if current == home or home in current.parents:
        return "maintainer", home
    contract = find_contract_root(current)
    if contract is not None:
        return "manager", contract
    subproject = find_subproject_root(current)
    if subproject is not None:
        return "worker", subproject
    workspace = find_workspace_root(current)
    if workspace is not None:
        return "manager", workspace
    return "unbound", None


def _load_local_workspace(root: Path) -> dict[str, Any]:
    return _load_yaml(root / LOCAL_WORKSPACE)


def _contract_path(root: Path, local: dict[str, Any]) -> Path:
    raw = local.get("contract_dir")
    if not raw:
        raise WorkspaceError("workspace.yaml 缺少 contract_dir")
    path = Path(str(raw)).expanduser()
    return (root / path).resolve() if not path.is_absolute() else path.resolve()


def resolve_contract(project: str | Path) -> Path:
    """从 workspace、contract 或已安装子项目解析 contract 根。"""
    project_path = Path(project).expanduser().resolve()
    local = project_path / LOCAL_WORKSPACE
    if local.is_file():
        return _contract_path(project_path, _load_yaml(local))
    role = project_path / CONTRACT_ROLE
    if role.is_file() and (project_path / "workspace").is_dir():
        return project_path
    install = project_path / INSTALL_REL
    if install.is_file():
        install_data = _load_yaml(install)
        parent = install_data.get("workspace_root")
        if parent:
            parent_path = Path(str(parent)).expanduser().resolve()
            parent_local = parent_path / LOCAL_WORKSPACE
            if parent_local.is_file():
                return _contract_path(parent_path, _load_yaml(parent_local))
    raise WorkspaceError("当前目录不是 workspace、contract 或已安装子项目")


def load_current_state(contract: str | Path) -> dict[str, Any]:
    path = Path(contract) / "state" / "current.json"
    if not path.is_file():
        raise WorkspaceError(f"缺少 state/current.json: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WorkspaceError(f"{path} 不是合法 JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise WorkspaceError(f"{path} 顶层必须是对象")
    return data


def _git_info(path: Path) -> dict[str, Any]:
    if not (path / ".git").exists():
        return {"git": False}
    branch = subprocess.run(
        ["git", "-C", str(path), "branch", "--show-current"],
        capture_output=True,
        text=True,
        check=False,
    )
    commit = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    dirty = subprocess.run(
        ["git", "-C", str(path), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "git": True,
        "branch": branch.stdout.strip() if branch.returncode == 0 else None,
        "commit": commit.stdout.strip() if commit.returncode == 0 else None,
        "dirty": bool(dirty.stdout.strip()) if dirty.returncode == 0 else None,
    }


def _git_init(path: Path) -> None:
    if (path / ".git").exists():
        return
    result = subprocess.run(
        ["git", "init", "-b", "main", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise WorkspaceError(f"git init 失败: {result.stderr.strip()}")


def _git_remote_add(path: Path, remote: str | None) -> None:
    if not remote:
        return
    existing = subprocess.run(
        ["git", "-C", str(path), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        check=False,
    )
    if existing.returncode == 0:
        if existing.stdout.strip() != remote:
            raise WorkspaceError(
                f"{path} 已有 origin={existing.stdout.strip()}；拒绝改为 {remote}"
            )
        return
    result = subprocess.run(
        ["git", "-C", str(path), "remote", "add", "origin", remote],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise WorkspaceError(f"git remote add 失败: {result.stderr.strip()}")


def _copy_global_tree(subdir: str, target: Path, *, force: bool = True) -> None:
    source = global_store.global_home() / "templates" / subdir
    target.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        for item in source.iterdir():
            if item.is_file() and not item.name.endswith(".bak"):
                destination = target / item.name
                if destination.exists() and not force:
                    continue
                shutil.copyfile(item, destination)
        return
    if subdir == "standards":
        for name, content in templates.STANDARDS.items():
            destination = target / name
            if destination.exists() and not force:
                continue
            _write(destination, content)
    elif subdir == "artifacts":
        for name, content in templates.ARTIFACT_TEMPLATES.items():
            destination = target / name
            if destination.exists() and not force:
                continue
            _write(destination, content)


def _managed_import_block(role: str, import_line: str) -> str:
    return (
        f"{templates.MANAGED_BLOCK_START.format(role=role)}\n"
        f"{import_line}\n"
        f"{templates.MANAGED_BLOCK_END.format(role=role)}\n"
    )


def _import_path(relative: str) -> str:
    return "@" + relative.replace(" ", "\\ ")


def _read_or(path: Path, fallback: str) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else fallback


def _write_contract_manifest(contract: Path, data: dict[str, Any]) -> None:
    _dump_yaml(contract / "workspace" / WORKSPACE_MANIFEST, data)


def _write_root_manifest(root: Path, contract: Path, data: dict[str, Any]) -> str:
    canonical = contract / "workspace" / WORKSPACE_MANIFEST
    content = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    header = (
        f"# generated by mf workspace sync from {canonical}\n"
        f"# digest: {_digest_text(content)}\n"
    )
    _write(root / WORKSPACE_MANIFEST, header + content)
    return _digest_text(content)


def _link_readme(root: Path, contract: Path, mode: str) -> tuple[str, str]:
    source = contract / "workspace" / "README.md"
    target = root / "README.md"
    if target.exists() or target.is_symlink():
        target.unlink()
    if mode == "auto":
        mode = "symlink" if os.name != "nt" else "copy"
    if mode == "symlink":
        relative = os.path.relpath(source, root)
        try:
            target.symlink_to(relative)
            return "symlink", relative
        except OSError:
            if mode == "auto":
                mode = "copy"
            else:
                raise WorkspaceError(f"无法创建符号链接: {target}") from None
    content = source.read_text(encoding="utf-8")
    header = f"<!-- generated from {source}; do not edit -->\n"
    _write(target, header + content)
    return "copy", _digest_text(content)


def _refresh_root_links(root: Path, contract: Path, local: dict[str, Any]) -> dict[str, Any]:
    relative = os.path.relpath(contract / "workspace" / "CLAUDE.md", root)
    import_line = _import_path(relative)
    _write(root / "CLAUDE.md", _managed_import_block("manager", import_line))
    readme_mode, readme_ref = _link_readme(
        root, contract, str(local.get("readme_link_mode", "auto"))
    )
    manifest_digest = _write_root_manifest(
        root, contract, _load_yaml(contract / "workspace" / WORKSPACE_MANIFEST)
    )
    return {
        "claude_import": import_line,
        "readme_link_mode": readme_mode,
        "readme_ref": readme_ref,
        "workspace_manifest_digest": manifest_digest,
    }


def workspace_init(
    root: str | Path,
    name: str,
    *,
    contract_dir: str | Path | None = None,
    contract_remote: str | None = None,
    link_mode: str = "auto",
    force: bool = False,
) -> dict[str, Any]:
    """在已安装 manager 的项目根创建 contract 仓与 workspace 元数据。"""
    root = Path(root).expanduser().resolve()
    install_manifest = root / INSTALL_REL
    if not install_manifest.is_file():
        raise WorkspaceError(f"缺少项目安装记录: {install_manifest}；先运行 mf install claude")
    install_data = _load_yaml(install_manifest)
    if install_data.get("role") != "manager":
        raise WorkspaceError("当前项目不是 manager 安装")

    project_id = slugify(name)
    if contract_dir is None:
        contract = root / f"{project_id}-contract"
    else:
        raw = Path(contract_dir).expanduser()
        contract = (root / raw).resolve() if not raw.is_absolute() else raw.resolve()
    if not contract.is_relative_to(root):
        raise WorkspaceError("contract 目录必须在项目根目录下，才能使用 @ 导入")
    if contract.exists():
        raise WorkspaceError(f"contract 目录已存在: {contract}")
    if link_mode not in {"auto", "symlink", "copy"}:
        raise WorkspaceError("link_mode 只能是 auto|symlink|copy")

    global_store.bootstrap()
    for directory in (
        contract / "workspace",
        contract / "project",
        contract / "roadmap" / "phases",
        contract / "requirements" / "changes",
        contract / "architecture" / "drafts",
        contract / "specs",
        contract / "standards",
        contract / "templates",
        contract / "policies",
        contract / "tasks",
        contract / "dev-records",
        contract / "verification",
        contract / "handoffs",
        contract / "reviews",
        contract / "bugs",
        contract / "knowledge",
        contract / "improvements",
        contract / "state",
        contract / "archive",
        contract / LOCAL_META,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    _copy_global_tree("standards", contract / "standards")
    _copy_global_tree("artifacts", contract / "templates")
    _write(
        contract / "templates" / "README.md",
        _TEMPLATES_README,
    )

    _write(contract / "project" / "PROJECT-PLAN.md", templates.PROJECT_PLAN)
    _write(
        contract / "project" / "INIT-CHECKLIST.md",
        templates.ARTIFACT_TEMPLATES["INIT-CHECKLIST.md"],
    )
    _dump_yaml(
        contract / "roadmap" / "ROADMAP.yaml",
        {
            "schema": 1,
            "roadmaps": [
                {
                    "id": "R1",
                    "title": "v1 MVP",
                    "status": "active",
                    "version_range": "1.x",
                    "version_target": "1.0.0",
                    "goal": "完成第一个可交付版本",
                    "entry_criteria": ["需求基线确认"],
                    "exit_criteria": ["P5 发布通过"],
                    "non_goals": ["多交付库并行"],
                }
            ],
        },
    )
    _write(
        contract / "roadmap" / "R1-PLAN.md",
        templates.ARTIFACT_TEMPLATES["ROADMAP-PLAN.md"].replace("R{n}", "R1"),
    )
    _dump_yaml(
        contract / "requirements" / "REQUIREMENTS.yaml",
        {"schema": 1, "requirements": []},
    )
    _write(contract / "requirements" / "INDEX.md", templates.REQUIREMENTS_INDEX)
    _write(contract / "architecture" / "INDEX.md", templates.ARCHITECTURE_INDEX)
    _write(contract / "bugs" / "README.md", templates.BUGS_README)
    _write(contract / "bugs" / "_TEMPLATE.yaml", templates.BUG_TEMPLATE)
    _write(contract / "knowledge" / "KNOWLEDGE.yaml", templates.KNOWLEDGE_YAML)
    _write(contract / "knowledge" / "KNOWLEDGE.md", templates.KNOWLEDGE_MD)
    _write(
        contract / "improvements" / "README.md",
        _IMPROVEMENTS_README,
    )
    _write(contract / "policies" / "CONTEXT-POLICY.yaml", templates.CONTEXT_POLICY)
    _write(contract / "state" / "ledger.ndjson", "")
    _write(contract / "state" / "READ-LOG.ndjson", "")
    _write(contract / "state" / "current.json", _initial_state(project_id))
    _write(contract / "archive" / "README.md", templates.ARCHIVE_README)
    _write(contract / ".gitignore", "state/current.json\n.meta-flow/*.lock\n*.bak\n")
    _write(contract / CONTRACT_ROLE, "role: manager\nworkspace_root: ..\n")
    for relative in (
        "requirements/changes/.gitkeep",
        "architecture/drafts/.gitkeep",
        "specs/.gitkeep",
        "tasks/.gitkeep",
        "dev-records/.gitkeep",
        "verification/.gitkeep",
        "handoffs/.gitkeep",
        "reviews/.gitkeep",
        "archive/.gitkeep",
        "roadmap/phases/.gitkeep",
    ):
        _write(contract / relative, "")

    root_claude = _read_or(root / "CLAUDE.md", templates.MANAGER_CLAUDE)
    root_readme = _read_or(root / "README.md", templates.PROJECT_README)
    _write(contract / "workspace" / "CLAUDE.md", root_claude)
    _write(contract / "workspace" / "README.md", root_readme)

    workspace_data = {
        "schema": 1,
        "project": {
            "name": name,
            "id": project_id,
            "contract_dir": str(contract.relative_to(root)),
            "contract_remote": contract_remote,
            "link_mode": link_mode,
        },
        "subprojects": [],
        "template_version": global_store.load_manifest().get("template_version"),
    }
    _write_contract_manifest(contract, workspace_data)

    local = {
        "schema": 1,
        "project_id": project_id,
        "project_name": name,
        "contract_dir": str(contract.relative_to(root)),
        "contract_remote": contract_remote,
        "readme_link_mode": link_mode,
        "subprojects": [],
        "installed_at": _now(),
    }
    _dump_yaml(root / LOCAL_WORKSPACE, local)
    links = _refresh_root_links(root, contract, local)
    local.update(links)
    _dump_yaml(root / LOCAL_WORKSPACE, local)

    install_data["contract_dir"] = str(contract.relative_to(root))
    install_data["link_mode"] = links["readme_link_mode"]
    install_data["updated_at"] = _now()
    _dump_yaml(install_manifest, install_data)

    _git_init(contract)
    _git_remote_add(contract, contract_remote)
    return {
        "root": str(root),
        "contract_dir": str(contract),
        "project_id": project_id,
        "claude_import": links["claude_import"],
        "readme_link_mode": links["readme_link_mode"],
    }


def _initial_state(project_id: str) -> str:
    return (
        json.dumps(
            {
                "schema": 1,
                "project_id": project_id,
                "roadmap": "R1",
                "phase": "P1",
                "version": "1.0.0-alpha.1",
                "counts": {},
                "active_tasks": [],
                "next_action": {
                    "type": "plan",
                    "text": "完成 P1 计划与 INIT-CHECKLIST",
                },
                "updated_at": _now(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


def workspace_upgrade(root: str | Path, *, force: bool = False) -> dict[str, Any]:
    """把全局 standards/templates 的新增内容同步到 contract 仓。"""
    root = Path(root).expanduser().resolve()
    local = _load_local_workspace(root)
    contract = _contract_path(root, local)
    _copy_global_tree("standards", contract / "standards", force=force)
    _copy_global_tree("artifacts", contract / "templates", force=force)
    improvements = contract / "improvements"
    improvements.mkdir(parents=True, exist_ok=True)
    readme = improvements / "README.md"
    if not readme.exists() or force:
        _write(readme, _IMPROVEMENTS_README)
    templates_readme = contract / "templates" / "README.md"
    if not templates_readme.exists() or force:
        _write(templates_readme, _TEMPLATES_README)
    return {"root": str(root), "contract_dir": str(contract), "force": force}


def workspace_add_project(    root: str | Path,
    name: str,
    path: str | Path,
    *,
    remote: str | None = None,
    delivery: str | None = None,
) -> dict[str, Any]:
    """创建子项目并安装 worker。"""
    root = Path(root).expanduser().resolve()
    local = _load_local_workspace(root)
    contract = _contract_path(root, local)
    project_id = slugify(name)
    sub = (root / Path(path)).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    if not sub.is_relative_to(root) or sub == contract or contract in sub.parents:
        raise WorkspaceError("子项目路径必须在项目根下，且不能是 contract 目录")
    if sub.exists() and any(sub.iterdir()) and not (sub / INSTALL_REL).is_file():
        raise WorkspaceError(f"子项目目录非空且未安装 worker: {sub}")

    from .install import install_worker

    result = install_worker(
        sub,
        delivery or name,
        workspace_root=root,
        contract_dir=contract,
        remote=remote,
    )

    entry = {
        "id": project_id,
        "path": str(sub.relative_to(root)),
        "remote": remote,
        "delivery": delivery or name,
        "agent": "worker",
    }
    subprojects = [item for item in local.get("subprojects", []) if item.get("id") != project_id]
    subprojects.append(entry)
    local["subprojects"] = subprojects
    _dump_yaml(root / LOCAL_WORKSPACE, local)

    workspace_data = _load_yaml(contract / "workspace" / WORKSPACE_MANIFEST)
    workspace_data["subprojects"] = subprojects
    _write_contract_manifest(contract, workspace_data)
    local["workspace_manifest_digest"] = _write_root_manifest(root, contract, workspace_data)
    _dump_yaml(root / LOCAL_WORKSPACE, local)

    return {"subproject": str(sub), "delivery": delivery or name, "install": result}


def workspace_link(root: str | Path) -> dict[str, Any]:
    """重建根目录 CLAUDE.md 导入、README 链接和 workspace 清单。"""
    root = Path(root).expanduser().resolve()
    local = _load_local_workspace(root)
    contract = _contract_path(root, local)
    links = _refresh_root_links(root, contract, local)
    local.update(links)
    local["linked_at"] = _now()
    _dump_yaml(root / LOCAL_WORKSPACE, local)
    return {"root": str(root), **links}


def workspace_sync(
    root: str | Path,
    *,
    check: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """校验/刷新根目录生成文件。"""
    root = Path(root).expanduser().resolve()
    local = _load_local_workspace(root)
    contract = _contract_path(root, local)
    canonical = contract / "workspace" / WORKSPACE_MANIFEST
    errors: list[str] = []

    claude_path = root / "CLAUDE.md"
    if not claude_path.is_file():
        errors.append("缺少根 CLAUDE.md")
    else:
        text = claude_path.read_text(encoding="utf-8")
        expected_import = _import_path(
            os.path.relpath(contract / "workspace" / "CLAUDE.md", root)
        )
        if expected_import not in text:
            errors.append("根 CLAUDE.md 未指向 contract/workspace/CLAUDE.md")
    if not (contract / "workspace" / "CLAUDE.md").is_file():
        errors.append("缺少 contract/workspace/CLAUDE.md")

    readme = root / "README.md"
    if not readme.exists() and not readme.is_symlink():
        errors.append("缺少根 README.md")
    elif readme.is_symlink():
        target = readme.resolve()
        if target != (contract / "workspace" / "README.md").resolve():
            errors.append("根 README 软链指向错误")
    else:
        canonical_readme = (contract / "workspace" / "README.md").read_text(encoding="utf-8")
        current = readme.read_text(encoding="utf-8")
        if current.endswith(canonical_readme):
            pass
        elif check:
            errors.append("根 README 与 contract/workspace/README.md 不一致")
        elif force:
            mode, _ = _link_readme(root, contract, local.get("readme_link_mode", "auto"))
            local["readme_link_mode"] = mode
        else:
            errors.append("根 README 与 canonical 不一致；使用 --force 或 --check")

    root_manifest = root / WORKSPACE_MANIFEST
    content = yaml.safe_dump(
        _load_yaml(canonical), sort_keys=False, allow_unicode=True
    )
    if not root_manifest.is_file():
        errors.append("缺少根 mf.workspace.yaml")
    elif check:
        current = root_manifest.read_text(encoding="utf-8")
        if _digest_text(content) not in current:
            errors.append("根 mf.workspace.yaml 与 canonical 不一致")
    elif force:
        local["workspace_manifest_digest"] = _write_root_manifest(
            root, contract, _load_yaml(canonical)
        )
        _dump_yaml(root / LOCAL_WORKSPACE, local)
    return {"root": str(root), "errors": errors, "ok": not errors}


def workspace_status(root: str | Path) -> dict[str, Any]:
    """返回 contract 与子项目的 git/版本状态。"""
    root = Path(root).expanduser().resolve()
    local = _load_local_workspace(root)
    contract = _contract_path(root, local)
    subprojects = []
    for item in local.get("subprojects", []):
        path = (root / str(item.get("path", ""))).resolve()
        version = None
        delivery_path = path / "delivery.yaml"
        if delivery_path.is_file():
            try:
                delivery = yaml.safe_load(delivery_path.read_text(encoding="utf-8")) or {}
                version = delivery.get("version") if isinstance(delivery, dict) else None
            except yaml.YAMLError:
                version = None
        subprojects.append(
            {
                **item,
                "absolute_path": str(path),
                "version": version,
                **_git_info(path),
            }
        )
    return {
        "root": str(root),
        "project": {
            "id": local.get("project_id"),
            "name": local.get("project_name"),
        },
        "contract": {
            "dir": str(contract),
            "remote": local.get("contract_remote"),
            **_git_info(contract),
        },
        "subprojects": subprojects,
        "claude_import": local.get("claude_import"),
        "readme_link_mode": local.get("readme_link_mode"),
    }


def doctor_global() -> list[str]:
    errors: list[str] = []
    home = global_store.global_home()
    manifest = home / "manifest.yaml"
    if not manifest.is_file():
        errors.append("缺少 ~/.meta-flow/manifest.yaml")
    else:
        try:
            data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            errors.append(f"manifest.yaml 不是合法 YAML: {exc}")
            data = {}
        if not data.get("repo_url"):
            errors.append("全局 manifest 缺少 repo_url")
    for name in ("manager", "maintainer", "worker"):
        if not (home / "agents" / f"{name}.md").is_file():
            errors.append(f"缺少全局 agent: agents/{name}.md")
    standards = home / "templates" / "standards"
    if not standards.is_dir() or len(list(standards.glob("*.md"))) < len(templates.STANDARDS):
        errors.append("全局 standards 模板不完整")
    return errors


def doctor(root: str | Path) -> list[str]:
    """校验项目、workspace、contract 与子项目安装。"""
    root = Path(root).expanduser().resolve()
    errors: list[str] = []
    install_path = root / INSTALL_REL
    if not install_path.is_file():
        return [f"缺少项目安装记录: {install_path}"]
    try:
        install_data = _load_yaml(install_path)
    except WorkspaceError as exc:
        return [str(exc)]
    if install_data.get("role") != "manager":
        errors.append("根目录安装角色不是 manager")
    for name in install_data.get("agents", ["manager"]):
        if not (root / ".claude" / "agents" / f"{name}.md").is_file():
            errors.append(f"缺少根 agent: .claude/agents/{name}.md")
    settings_path = root / ".claude" / "settings.json"
    if not settings_path.is_file():
        errors.append("缺少 .claude/settings.json")
    else:
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"settings.json 不是合法 JSON: {exc}")
            settings = {}
        if isinstance(settings, dict) and settings.get("agent") != "manager":
            errors.append("根 settings.json 的 agent 不是 manager")

    if (root / "contracts").exists():
        errors.append("根目录存在旧版 contracts/；请迁移或删除")
    if (root / "deliveries").exists():
        errors.append("根目录存在旧版 deliveries/；请迁移或删除")

    local_path = root / LOCAL_WORKSPACE
    if not local_path.is_file():
        errors.append("缺少 .meta-flow/workspace.yaml；运行 mf workspace init")
        return errors
    try:
        local = _load_yaml(local_path)
        contract = _contract_path(root, local)
    except WorkspaceError as exc:
        return errors + [str(exc)]

    for relative in (
        "workspace/CLAUDE.md",
        "workspace/README.md",
        "workspace/mf.workspace.yaml",
        "project/PROJECT-PLAN.md",
        "project/INIT-CHECKLIST.md",
        "roadmap/ROADMAP.yaml",
        "requirements/REQUIREMENTS.yaml",
        "standards/CONTEXT.md",
        "templates/README.md",
        "policies/CONTEXT-POLICY.yaml",
        "state/ledger.ndjson",
        "state/READ-LOG.ndjson",
        "archive/README.md",
        "bugs/README.md",
        "knowledge/KNOWLEDGE.yaml",
        "improvements/README.md",
    ):
        if not (contract / relative).is_file():
            errors.append(f"contract 缺少文件: {relative}")
    state_path = contract / "state" / "current.json"
    if not state_path.is_file():
        errors.append("contract 缺少 state/current.json")
    elif state_path.stat().st_size > 8192:
        errors.append(f"contract state/current.json 超过 8KB: {state_path.stat().st_size} bytes")

    claude_path = root / "CLAUDE.md"
    if not claude_path.is_file():
        errors.append("缺少根 CLAUDE.md")
    else:
        text = claude_path.read_text(encoding="utf-8")
        if "@" not in text or "workspace/CLAUDE.md" not in text:
            errors.append("根 CLAUDE.md 不是 @ contract/workspace/CLAUDE.md 导入")
    readme = root / "README.md"
    if not readme.exists() and not readme.is_symlink():
        errors.append("缺少根 README.md")
    elif readme.is_symlink() and readme.resolve() != (contract / "workspace" / "README.md").resolve():
        errors.append("根 README 软链指向错误")
    root_manifest = root / WORKSPACE_MANIFEST
    if not root_manifest.is_file():
        errors.append("缺少根 mf.workspace.yaml")

    for item in local.get("subprojects", []):
        path = (root / str(item.get("path", ""))).resolve()
        if not path.is_relative_to(root) or path == contract or contract in path.parents:
            errors.append(f"子项目路径非法: {item.get('path')}")
            continue
        if not path.is_dir():
            errors.append(f"子项目目录不存在: {item.get('path')}")
            continue
        sub_install = path / INSTALL_REL
        if not sub_install.is_file():
            errors.append(f"子项目缺少安装记录: {path / INSTALL_REL}")
            continue
        try:
            sub_data = _load_yaml(sub_install)
        except WorkspaceError as exc:
            errors.append(str(exc))
            continue
        if sub_data.get("role") != "worker":
            errors.append(f"子项目 {item.get('id')} 安装角色不是 worker")
        if not (path / ".claude" / "agents" / "worker.md").is_file():
            errors.append(f"子项目 {item.get('id')} 缺少 worker agent")
        sub_settings = path / ".claude" / "settings.json"
        if not sub_settings.is_file():
            errors.append(f"子项目 {item.get('id')} 缺少 settings.json")
        else:
            try:
                data = json.loads(sub_settings.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                errors.append(f"子项目 {item.get('id')} settings.json 非法")
                data = {}
            if isinstance(data, dict) and data.get("agent") != "worker":
                errors.append(f"子项目 {item.get('id')} 默认 agent 不是 worker")
        if not (path / "delivery.yaml").is_file():
            errors.append(f"子项目 {item.get('id')} 缺少 delivery.yaml")

    return errors
