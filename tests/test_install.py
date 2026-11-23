"""安装、更新、卸载测试。"""

from __future__ import annotations

import json

import pytest
import yaml

from meta_flow.global_store import bootstrap
from meta_flow.install import (
    InstallError,
    install_root,
    install_worker,
    uninstall_claude,
)


@pytest.fixture()
def mf_env(tmp_path, monkeypatch):
    home = tmp_path / "global"
    monkeypatch.setenv("META_FLOW_HOME", str(home))
    bootstrap()
    project = tmp_path / "project"
    project.mkdir()
    return {"home": home, "project": project, "tmp": tmp_path}


def test_bootstrap_creates_store(mf_env):
    home = mf_env["home"]
    assert (home / "manifest.yaml").is_file()
    assert (home / "agents" / "manager.md").is_file()
    assert (home / "agents" / "maintainer.md").is_file()
    assert (home / "agents" / "worker.md").is_file()
    assert (home / "templates" / "standards" / "CONTEXT.md").is_file()
    manifest = yaml.safe_load((home / "manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["repo_url"]
    assert manifest["template_version"]


def test_install_manager(mf_env):
    project = mf_env["project"]
    result = install_root(project)
    assert result["agents"] == ["manager"]
    assert (project / ".claude" / "agents" / "manager.md").is_file()
    assert (project / "CLAUDE.md").is_file()
    assert "meta-flow:manager:start" in (project / "CLAUDE.md").read_text(encoding="utf-8")
    settings = json.loads((project / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert settings["agent"] == "manager"
    assert (project / ".meta-flow" / "install.yaml").is_file()
    assert not (project / "contracts").exists()
    assert not (project / "deliveries").exists()


def test_install_maintainer_includes_manager(mf_env):
    project = mf_env["project"]
    result = install_root(project, agent="maintainer")
    assert result["agents"] == ["manager", "maintainer"]
    assert (project / ".claude" / "agents" / "manager.md").is_file()
    assert (project / ".claude" / "agents" / "maintainer.md").is_file()


def test_install_refuses_existing_agent(mf_env):
    project = mf_env["project"]
    path = project / ".claude" / "agents" / "manager.md"
    path.parent.mkdir(parents=True)
    path.write_text("custom", encoding="utf-8")
    with pytest.raises(InstallError):
        install_root(project)


def test_install_worker(mf_env):
    project = mf_env["project"]
    sub = project / "frontend"
    result = install_worker(sub, "frontend", workspace_root=project)
    assert result["delivery"] == "frontend"
    assert (sub / ".claude" / "agents" / "worker.md").is_file()
    assert (sub / "delivery.yaml").is_file()
    assert (sub / "CLAUDE.md").is_file()
    settings = json.loads((sub / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert settings["agent"] == "worker"
    assert (sub / ".git").is_dir()


def test_uninstall_restores_settings(mf_env):
    project = mf_env["project"]
    settings_path = project / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(
        json.dumps({"agent": "other", "theme": "dark"}),
        encoding="utf-8",
    )
    install_root(project, force=True)
    assert json.loads(settings_path.read_text(encoding="utf-8"))["agent"] == "manager"

    result = uninstall_claude(project)
    restored = json.loads(settings_path.read_text(encoding="utf-8"))
    assert restored == {"agent": "other", "theme": "dark"}
    assert not (project / ".claude" / "agents" / "manager.md").exists()
    assert not (project / ".meta-flow" / "install.yaml").exists()
    assert result["removed"]
