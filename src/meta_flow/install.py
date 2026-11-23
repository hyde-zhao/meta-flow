"""项目级安装、更新与卸载。"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from . import __version__, global_store, templates

INSTALL_SCHEMA = 1
INSTALL_REL = Path(".meta-flow/install.yaml")
SETTINGS_REL = Path(".claude/settings.json")
CLAUDE_REL = Path("CLAUDE.md")
README_REL = Path("README.md")


class InstallError(Exception):
    """安装或卸载失败。"""

    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _digest_text(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def _digest_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _managed_block(role: str, body: str) -> str:
    start = templates.MANAGED_BLOCK_START.format(role=role)
    end = templates.MANAGED_BLOCK_END.format(role=role)
    return f"{start}\n{body.rstrip()}\n{end}\n"


def _replace_managed_block(text: str, role: str, body: str) -> str:
    start = templates.MANAGED_BLOCK_START.format(role=role)
    end = templates.MANAGED_BLOCK_END.format(role=role)
    block = _managed_block(role, body)
    if start in text and end in text:
        before, rest = text.split(start, 1)
        _, after = rest.split(end, 1)
        return before + block + after.lstrip("\n")
    return block + ("\n" + text if text.strip() else "")


def _remove_managed_block(text: str, role: str) -> str:
    start = templates.MANAGED_BLOCK_START.format(role=role)
    end = templates.MANAGED_BLOCK_END.format(role=role)
    if start not in text or end not in text:
        return text
    before, rest = text.split(start, 1)
    _, after = rest.split(end, 1)
    return (before.rstrip() + "\n" + after.lstrip("\n")).strip() + "\n"


def _global_template(name: str, fallback: str) -> str:
    try:
        return global_store.copy_global_asset(f"templates/{name}")
    except global_store.GlobalStoreError:
        return fallback


def _install_file(project: Path, relative: Path, content: str, force: bool) -> dict[str, Any]:
    target = project / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        current = target.read_text(encoding="utf-8")
        if current == content:
            return {"path": str(relative), "digest": _digest_text(current)}
        if not force:
            raise InstallError(f"{target} 已存在且内容不同；使用 --force 覆盖")
        (target.with_suffix(target.suffix + ".bak")).write_text(current, encoding="utf-8")
    target.write_text(content, encoding="utf-8")
    return {"path": str(relative), "digest": _digest_text(content)}


def _merge_settings(
    project: Path,
    agent: str,
    force: bool,
) -> tuple[dict[str, Any], str | None, bool]:
    path = project / SETTINGS_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        path.write_text(json.dumps({"agent": agent}, ensure_ascii=False, indent=2) + "\n")
        return (
            {"path": str(SETTINGS_REL), "agent": agent, "agent_before": None, "created": True},
            None,
            True,
        )

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InstallError(f"{path} 不是合法 JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise InstallError(f"{path} 顶层必须是 JSON 对象")

    before = data.get("agent")
    if before is not None and before != agent and not force:
        raise InstallError(
            f"{path} 已设置 agent={before!r}；使用 --force 覆盖为 {agent!r}"
        )
    data["agent"] = agent
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return (
        {"path": str(SETTINGS_REL), "agent": agent, "agent_before": before, "created": False},
        before,
        False,
    )


def _restore_settings(project: Path, info: dict[str, Any]) -> None:
    path = project / SETTINGS_REL
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    if not isinstance(data, dict):
        return
    if data.get("agent") != info.get("agent"):
        return
    before = info.get("agent_before")
    if before is None:
        data.pop("agent", None)
    else:
        data["agent"] = before
    if info.get("created") and not data:
        path.unlink()
        return
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _write_manifest(project: Path, data: dict[str, Any]) -> Path:
    path = project / INSTALL_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = _now()
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return path


def load_install_manifest(project: Path) -> dict[str, Any]:
    path = project / INSTALL_REL
    if not path.is_file():
        raise InstallError(f"缺少安装记录: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise InstallError(f"{path} 不是合法 YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise InstallError(f"{path} 顶层必须是映射")
    return data


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
        raise InstallError(f"git init 失败: {result.stderr.strip()}")


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
            raise InstallError(
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
        raise InstallError(f"git remote add 失败: {result.stderr.strip()}")


def install_root(
    project_dir: str | Path,
    *,
    agent: str = "manager",
    init_contract: bool = False,
    link_mode: str = "auto",
    force: bool = False,
) -> dict[str, Any]:
    """在项目根目录安装 manager（可选 maintainer）。"""
    project = Path(project_dir).expanduser().resolve()
    project.mkdir(parents=True, exist_ok=True)
    global_store.bootstrap()

    if agent not in {"manager", "maintainer"}:
        raise InstallError("根目录只支持 --agent manager 或 --agent maintainer")
    agents = ["manager", "maintainer"] if agent == "maintainer" else ["manager"]

    files: list[dict[str, Any]] = []
    for name in agents:
        content = _global_template(f"agents/{name}.md", getattr(templates, f"AGENT_{name.upper()}"))
        files.append(_install_file(project, Path(".claude/agents") / f"{name}.md", content, force))

    manager_body = _global_template("CLAUDE.manager.md", templates.MANAGER_CLAUDE)
    claude_path = project / CLAUDE_REL
    existed = claude_path.exists()
    current = claude_path.read_text(encoding="utf-8") if existed else ""
    claude_path.write_text(
        _replace_managed_block(current, "manager", manager_body),
        encoding="utf-8",
    )
    files.append({"path": str(CLAUDE_REL), "digest": _digest_file(claude_path)})

    readme_path = project / README_REL
    readme_created = False
    if not readme_path.exists():
        readme_path.write_text(
            _global_template("README.project.md", templates.PROJECT_README).replace(
                "<项目名>", project.name
            ),
            encoding="utf-8",
        )
        readme_created = True

    settings_info, _, _ = _merge_settings(project, agents[0], force)

    manifest = {
        "schema": INSTALL_SCHEMA,
        "role": "manager",
        "project_dir": str(project),
        "workspace_root": str(project),
        "contract_dir": None,
        "agents": agents,
        "tool_version": __version__,
        "template_version": global_store.load_manifest().get("template_version"),
        "installed_at": _now(),
        "files": files,
        "claude": {"path": str(CLAUDE_REL), "managed_role": "manager"},
        "settings": settings_info,
        "readme": {"path": str(README_REL), "created": readme_created},
    }
    _write_manifest(project, manifest)

    result: dict[str, Any] = {
        "project_dir": str(project),
        "agents": agents,
        "install_manifest": str(project / INSTALL_REL),
        "contract": None,
    }
    if init_contract:
        from .workspace import workspace_init

        result["contract"] = workspace_init(
            project,
            project.name,
            link_mode=link_mode,
            force=force,
        )
    return result


def install_worker(
    project_dir: str | Path,
    delivery: str,
    *,
    workspace_root: str | Path | None = None,
    contract_dir: str | Path | None = None,
    remote: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """在子项目安装 worker，并写入 delivery 骨架。"""
    project = Path(project_dir).expanduser().resolve()
    project.mkdir(parents=True, exist_ok=True)
    global_store.bootstrap()

    existing = project / INSTALL_REL
    if existing.is_file():
        old = load_install_manifest(project)
        if old.get("role") != "worker":
            raise InstallError(f"{project} 已安装为 {old.get('role')}，不能覆盖为 worker")

    files: list[dict[str, Any]] = []
    content = _global_template("agents/worker.md", templates.AGENT_WORKER)
    files.append(_install_file(project, Path(".claude/agents/worker.md"), content, force))

    worker_body = _global_template("CLAUDE.worker.md", templates.WORKER_CLAUDE)
    claude_path = project / CLAUDE_REL
    current = claude_path.read_text(encoding="utf-8") if claude_path.exists() else ""
    claude_path.write_text(
        _replace_managed_block(current, "worker", worker_body),
        encoding="utf-8",
    )
    files.append({"path": str(CLAUDE_REL), "digest": _digest_file(claude_path)})

    readme_path = project / README_REL
    readme_created = False
    if not readme_path.exists():
        readme_path.write_text(f"# {project.name}\n\nMeta Flow worker 子项目。\n", encoding="utf-8")
        readme_created = True

    settings_info, _, _ = _merge_settings(project, "worker", force)

    if not (project / "delivery.yaml").exists():
        (project / "delivery.yaml").write_text(
            yaml.safe_dump(
                {
                    "id": delivery,
                    "version": "1.0.0",
                    "roadmap": "R1",
                    "responsibility": f"{delivery} 交付",
                    "contracts": [],
                    "artifacts": [],
                    "docs": {
                        "release_notes": "RELEASE-NOTES.md",
                        "user_manual": "USER-MANUAL.md",
                    },
                    "repo": remote or ".",
                },
                sort_keys=False,
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
    for name, content in {
        "RELEASE-NOTES.md": templates.RELEASE_NOTES,
        "USER-MANUAL.md": templates.USER_MANUAL,
    }.items():
        path = project / name
        if not path.exists():
            path.write_text(content, encoding="utf-8")
    for directory in (
        "src",
        "tests",
        "release",
        ".meta-flow/dev-records",
        ".meta-flow/handoffs",
        ".meta-flow/improvements",
    ):
        (project / directory).mkdir(parents=True, exist_ok=True)

    manifest = {
        "schema": INSTALL_SCHEMA,
        "role": "worker",
        "project_dir": str(project),
        "workspace_root": str(Path(workspace_root).expanduser().resolve())
        if workspace_root
        else None,
        "contract_dir": str(Path(contract_dir).expanduser().resolve())
        if contract_dir
        else None,
        "delivery": delivery,
        "remote": remote,
        "agents": ["worker"],
        "tool_version": __version__,
        "template_version": global_store.load_manifest().get("template_version"),
        "installed_at": _now(),
        "files": files,
        "claude": {"path": str(CLAUDE_REL), "managed_role": "worker"},
        "settings": settings_info,
        "readme": {"path": str(README_REL), "created": readme_created},
    }
    _write_manifest(project, manifest)

    _git_init(project)
    _git_remote_add(project, remote)

    return {
        "project_dir": str(project),
        "delivery": delivery,
        "install_manifest": str(project / INSTALL_REL),
    }


def uninstall_claude(
    project_dir: str | Path,
    *,
    force: bool = False,
    purge: bool = False,
) -> dict[str, Any]:
    """按 .meta-flow/install.yaml 卸载项目或子项目安装。"""
    project = Path(project_dir).expanduser().resolve()
    manifest = load_install_manifest(project)
    removed: list[str] = []
    skipped: list[str] = []

    for item in manifest.get("files", []):
        relative = Path(str(item.get("path", "")))
        if not relative:
            continue
        if relative == CLAUDE_REL:
            continue
        path = project / relative
        if not path.exists():
            continue
        if not path.is_file():
            continue
        if force or _digest_file(path) == item.get("digest"):
            path.unlink()
            removed.append(str(relative))
        else:
            skipped.append(str(relative))

    role = manifest.get("claude", {}).get("managed_role")
    claude_path = project / CLAUDE_REL
    if role and claude_path.is_file():
        text = claude_path.read_text(encoding="utf-8")
        new_text = _remove_managed_block(text, role)
        if new_text.strip():
            claude_path.write_text(new_text, encoding="utf-8")
        else:
            claude_path.unlink()
            removed.append(str(CLAUDE_REL))

    _restore_settings(project, manifest.get("settings", {}))

    readme = manifest.get("readme", {})
    if readme.get("created"):
        readme_path = project / README_REL
        if readme_path.is_file():
            readme_path.unlink()
            removed.append(str(README_REL))

    install_path = project / INSTALL_REL
    if install_path.is_file():
        install_path.unlink()
        removed.append(str(INSTALL_REL))
    if purge:
        for relative in (".meta-flow/workspace.yaml", "mf.workspace.yaml"):
            path = project / relative
            if path.is_file() or path.is_symlink():
                path.unlink()
                removed.append(relative)
    meta_dir = project / ".meta-flow"
    if meta_dir.is_dir() and not any(meta_dir.iterdir()):
        meta_dir.rmdir()

    return {"project_dir": str(project), "removed": removed, "skipped": skipped}


def upgrade_project(project_dir: str | Path, *, force: bool = False) -> dict[str, Any]:
    """按当前全局模板更新项目安装文件。"""
    project = Path(project_dir).expanduser().resolve()
    manifest = load_install_manifest(project)
    global_store.bootstrap()
    role = manifest.get("role", "manager")
    agents = manifest.get("agents", ["manager"] if role == "manager" else ["worker"])

    updated: list[str] = []
    for name in agents:
        content = _global_template(
            f"agents/{name}.md",
            getattr(templates, f"AGENT_{name.upper()}"),
        )
        info = _install_file(project, Path(".claude/agents") / f"{name}.md", content, force)
        updated.append(info["path"])

    if role == "manager":
        contract_dir = manifest.get("contract_dir")
        if contract_dir:
            body = "@" + str(contract_dir).replace(" ", "\\ ") + "/workspace/CLAUDE.md"
        else:
            body = _global_template("CLAUDE.manager.md", templates.MANAGER_CLAUDE)
    else:
        body = _global_template("CLAUDE.worker.md", templates.WORKER_CLAUDE)
    claude_path = project / CLAUDE_REL
    current = claude_path.read_text(encoding="utf-8") if claude_path.exists() else ""
    claude_path.write_text(_replace_managed_block(current, role, body), encoding="utf-8")

    if role == "manager" and (project / ".meta-flow" / "workspace.yaml").is_file():
        from .workspace import workspace_upgrade

        workspace_upgrade(project, force=force)

    manifest["tool_version"] = __version__
    manifest["template_version"] = global_store.load_manifest().get("template_version")
    manifest["updated_at"] = _now()
    for item in manifest.get("files", []):
        path = project / str(item.get("path", ""))
        if path.is_file():
            item["digest"] = _digest_file(path)
    _write_manifest(project, manifest)
    return {"project_dir": str(project), "updated": updated, "role": role}
