"""全局模板库与 meta-flow 源码维护。"""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from . import __version__, templates

DEFAULT_REPO_URL = "git@github.com:hyde-zhao/meta-flow.git"
TEMPLATE_VERSION = "2026-11-23"


class GlobalStoreError(Exception):
    """全局模板库或源码操作失败。"""

    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


def global_home() -> Path:
    """返回全局模板库目录；测试可用 META_FLOW_HOME 覆盖。"""
    raw = os.environ.get("META_FLOW_HOME")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / ".meta-flow").resolve()


def manifest_path() -> Path:
    return global_home() / "manifest.yaml"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _write_if_changed(path: Path, content: str, force: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        current = path.read_text(encoding="utf-8")
        if current == content:
            return
        if not force:
            return
        path.with_suffix(path.suffix + ".bak").write_text(current, encoding="utf-8")
    path.write_text(content, encoding="utf-8")


def _dump_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def load_manifest() -> dict[str, Any]:
    path = manifest_path()
    if not path.is_file():
        raise GlobalStoreError("未找到 ~/.meta-flow/manifest.yaml；先运行 mf bootstrap")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise GlobalStoreError(f"{path} 不是合法 YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise GlobalStoreError(f"{path} 顶层必须是映射")
    return data


def bootstrap(repo_url: str | None = None, force: bool = False) -> Path:
    """创建或刷新 ~/.meta-flow 全局模板库。"""
    home = global_home()
    (home / "agents").mkdir(parents=True, exist_ok=True)
    (home / "templates" / "standards").mkdir(parents=True, exist_ok=True)
    (home / "templates" / "artifacts").mkdir(parents=True, exist_ok=True)
    (home / "schemas").mkdir(parents=True, exist_ok=True)

    (home / "VERSION").write_text(__version__ + "\n", encoding="utf-8")

    for name, content in {
        "manager": templates.AGENT_MANAGER,
        "maintainer": templates.AGENT_MAINTAINER,
        "worker": templates.AGENT_WORKER,
    }.items():
        _write_if_changed(home / "agents" / f"{name}.md", content, force)

    for name, content in templates.STANDARDS.items():
        _write_if_changed(home / "templates" / "standards" / name, content, force)

    for name, content in templates.ARTIFACT_TEMPLATES.items():
        _write_if_changed(home / "templates" / "artifacts" / name, content, force)

    for name, content in {
        "CLAUDE.manager.md": templates.MANAGER_CLAUDE,
        "CLAUDE.maintainer.md": templates.MAINTAINER_CLAUDE,
        "CLAUDE.worker.md": templates.WORKER_CLAUDE,
        "README.project.md": templates.PROJECT_README,
        "workspace/CLAUDE.md": templates.MANAGER_CLAUDE,
        "workspace/README.md": templates.PROJECT_README,
    }.items():
        _write_if_changed(home / "templates" / name, content, force)

    old: dict[str, Any] = {}
    if manifest_path().is_file():
        try:
            loaded = yaml.safe_load(manifest_path().read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                old = loaded
        except yaml.YAMLError:
            old = {}

    _dump_yaml(
        manifest_path(),
        {
            "schema": 1,
            "tool_version": __version__,
            "template_version": TEMPLATE_VERSION,
            "repo_url": repo_url or old.get("repo_url") or DEFAULT_REPO_URL,
            "source_dir": old.get("source_dir") or str(home / "source"),
            "installed_at": old.get("installed_at") or _now(),
            "updated_at": _now(),
            "agents": ["manager", "maintainer", "worker"],
        },
    )
    return home


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GlobalStoreError(f"未找到命令: {args[0]}") from exc


def _source_dir(value: str | Path | None) -> Path:
    if value is not None:
        return Path(value).expanduser().resolve()
    return Path(load_manifest().get("source_dir", global_home() / "source")).expanduser()


def dev_clone(dest: str | Path | None = None, repo: str | None = None) -> Path:
    """克隆 meta-flow 源码到全局源码目录。"""
    manifest = load_manifest()
    source = _source_dir(dest)
    url = repo or manifest.get("repo_url", DEFAULT_REPO_URL)
    if source.exists() and any(source.iterdir()):
        raise GlobalStoreError(f"源码目录非空，拒绝覆盖: {source}")
    source.parent.mkdir(parents=True, exist_ok=True)
    result = _run(["git", "clone", str(url), str(source)])
    if result.returncode != 0:
        raise GlobalStoreError(f"git clone 失败: {result.stderr.strip()}")
    return source


def dev_update(source: str | Path | None = None) -> Path:
    """拉取 meta-flow 源码更新；工作区必须干净。"""
    path = _source_dir(source)
    if not (path / ".git").exists():
        raise GlobalStoreError(f"不是 git 仓库: {path}")
    dirty = _run(["git", "-C", str(path), "status", "--porcelain"])
    if dirty.returncode != 0:
        raise GlobalStoreError(f"git status 失败: {dirty.stderr.strip()}")
    if dirty.stdout.strip():
        raise GlobalStoreError("源码工作区不干净；先提交或暂存再更新")
    result = _run(["git", "-C", str(path), "pull", "--ff-only"])
    if result.returncode != 0:
        raise GlobalStoreError(f"git pull 失败: {result.stderr.strip()}")
    return path


def dev_install(source: str | Path | None = None, yes: bool = False) -> Path:
    """从本地源码安装/更新全局 mf 工具。"""
    if not yes:
        raise GlobalStoreError("该操作会更新全局 mf 工具；请加 --yes 确认")
    path = _source_dir(source)
    if not (path / "pyproject.toml").is_file():
        raise GlobalStoreError(f"源码目录缺少 pyproject.toml: {path}")
    result = _run(["uv", "tool", "install", "--force", str(path)])
    if result.returncode != 0:
        raise GlobalStoreError(f"uv tool install 失败: {result.stderr.strip()}")
    return path


def dev_status(source: str | Path | None = None) -> dict[str, Any]:
    """返回源码、全局工具与仓库信息。"""
    manifest = load_manifest()
    path = _source_dir(source)
    status: dict[str, Any] = {
        "repo_url": manifest.get("repo_url"),
        "source_dir": str(path),
        "tool_version": manifest.get("tool_version"),
        "template_version": manifest.get("template_version"),
        "source_exists": path.exists(),
    }
    if path.exists() and (path / ".git").exists():
        branch = _run(["git", "-C", str(path), "branch", "--show-current"])
        commit = _run(["git", "-C", str(path), "rev-parse", "--short", "HEAD"])
        dirty = _run(["git", "-C", str(path), "status", "--porcelain"])
        status.update(
            {
                "branch": branch.stdout.strip() if branch.returncode == 0 else None,
                "commit": commit.stdout.strip() if commit.returncode == 0 else None,
                "dirty": bool(dirty.stdout.strip()) if dirty.returncode == 0 else None,
            }
        )
    return status


def copy_global_asset(relative: str) -> str:
    """读取全局模板库中的文本资产。"""
    path = global_home() / relative
    if not path.is_file():
        raise GlobalStoreError(f"缺少全局资产: {path}")
    return path.read_text(encoding="utf-8")


def reset_for_tests(path: Path) -> None:
    """测试辅助：删除指定全局目录。"""
    if path.exists():
        shutil.rmtree(path)
