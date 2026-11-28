"""安装、更新、卸载测试。"""

from __future__ import annotations

import json
import subprocess

import pytest
import yaml

from meta_flow.global_store import bootstrap
from meta_flow.install import (
    GITIGNORE_BLOCK_START,
    InstallError,
    install_root,
    install_worker,
    uninstall_claude,
    upgrade_project,
)


def _git_init(path):
    subprocess.run(
        ["git", "init", "-b", "main", str(path)],
        check=True,
        capture_output=True,
        text=True,
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
    assert (home / "agents" / "reviewer.md").is_file()
    assert (home / "templates" / "standards" / "CONTEXT.md").is_file()
    manifest = yaml.safe_load((home / "manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["repo_url"]
    assert manifest["template_version"]


def test_install_manager(mf_env):
    project = mf_env["project"]
    result = install_root(project)
    assert result["agents"] == ["manager", "reviewer"]
    assert (project / ".claude" / "agents" / "manager.md").is_file()
    assert (project / ".claude" / "agents" / "reviewer.md").is_file()
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
    assert result["agents"] == ["manager", "maintainer", "reviewer"]
    assert (project / ".claude" / "agents" / "manager.md").is_file()
    assert (project / ".claude" / "agents" / "maintainer.md").is_file()
    assert (project / ".claude" / "agents" / "reviewer.md").is_file()


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
    assert (sub / ".claude" / "agents" / "reviewer.md").is_file()
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


def test_install_manager_writes_gitignore_for_git_repo(mf_env):
    project = mf_env["project"]
    _git_init(project)

    result = install_root(project)

    text = (project / ".gitignore").read_text(encoding="utf-8")
    for pattern in ("CLAUDE.md", ".claude/", ".meta-flow/", "__pycache__/", "*.py[cod]"):
        assert pattern in text
    assert text.count(GITIGNORE_BLOCK_START) == 1
    assert result["gitignore"]["updated"] is True

    status = subprocess.run(
        ["git", "-C", str(project), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    for mirror in ("CLAUDE.md", ".claude/", ".meta-flow/"):
        assert mirror not in status
    assert "README.md" in status


def test_install_manager_skips_gitignore_without_git(mf_env):
    project = mf_env["project"]

    result = install_root(project)

    assert not (project / ".gitignore").exists()
    assert result["gitignore"]["skipped"] == "not-a-git-repo"


def test_install_manager_preserves_existing_gitignore_and_is_idempotent(mf_env):
    project = mf_env["project"]
    _git_init(project)
    gitignore = project / ".gitignore"
    gitignore.write_text("node_modules/\n", encoding="utf-8")

    install_root(project)
    first = gitignore.read_text(encoding="utf-8")
    assert first.startswith("node_modules/\n")
    assert GITIGNORE_BLOCK_START in first

    install_root(project)
    assert gitignore.read_text(encoding="utf-8") == first


def test_uninstall_keeps_custom_gitignore_rules(mf_env):
    project = mf_env["project"]
    _git_init(project)
    gitignore = project / ".gitignore"
    gitignore.write_text("node_modules/\n", encoding="utf-8")
    install_root(project)

    result = uninstall_claude(project)

    assert gitignore.read_text(encoding="utf-8") == "node_modules/\n"
    assert result["gitignore"]["removed"] is True


def test_uninstall_removes_install_created_gitignore(mf_env):
    project = mf_env["project"]
    _git_init(project)
    install_root(project)
    assert (project / ".gitignore").is_file()

    uninstall_claude(project)

    assert not (project / ".gitignore").exists()


def test_install_worker_writes_gitignore(mf_env):
    project = mf_env["project"]
    sub = project / "frontend"

    result = install_worker(sub, "frontend", workspace_root=project)

    text = (sub / ".gitignore").read_text(encoding="utf-8")
    assert "CLAUDE.md" in text
    assert ".meta-flow/" in text
    assert result["gitignore"]["updated"] is True

    install_worker(sub, "frontend", workspace_root=project)
    assert (sub / ".gitignore").read_text(encoding="utf-8") == text


def test_dev_status_missing_or_invalid_source_is_explicit(mf_env):
    from meta_flow.global_store import GlobalStoreError, dev_status

    with pytest.raises(GlobalStoreError, match="源码目录不存在"):
        dev_status()
    source = mf_env["home"] / "source"
    source.mkdir(parents=True)
    with pytest.raises(GlobalStoreError, match="不是 git 仓库"):
        dev_status()
    (source / ".git").mkdir()
    data = dev_status()
    assert data["source_exists"] is True

    with pytest.raises(GlobalStoreError, match="--source"):
        dev_status(source=mf_env["tmp"] / "missing-source")


def test_install_worker_delivery_uses_contract_baseline(mf_env):
    from meta_flow.workspace import workspace_init

    project = mf_env["project"]
    install_root(project)
    workspace_init(project, "Legacy", roadmap="R0", phase="P4", version="1.0.0")
    contract = project / "legacy-contract"
    sub = project / "frontend"
    result = install_worker(
        sub, "frontend", workspace_root=project, contract_dir=contract
    )
    assert result["delivery"] == "frontend"
    delivery = yaml.safe_load((sub / "delivery.yaml").read_text(encoding="utf-8"))
    assert delivery["roadmap"] == "R0"
    assert delivery["version"] == "1.0.0"


def test_agent_templates_use_existing_doctor_flags():
    from meta_flow import templates

    for text in (templates.AGENT_MAINTAINER, templates.MAINTAINER_CLAUDE):
        assert "mf doctor --project" not in text
        assert "mf doctor --path" in text


def _git_commit_all(path):
    subprocess.run(
        ["git", "-C", str(path), "add", "-A"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(path),
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "baseline",
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def _git_status(path):
    return subprocess.run(
        ["git", "-C", str(path), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def test_upgrade_force_preserves_contract_and_refreshes_mirror(mf_env):
    """BUG-0015：upgrade --force 只更新安装镜像，不覆盖 contract 自定义内容。"""
    from meta_flow.workspace import workspace_init

    home = mf_env["home"]
    project = mf_env["project"]
    install_root(project)
    workspace_init(project, "Demo")
    contract = project / "demo-contract"

    custom_standard = "# 项目自定义标准\n\n不要覆盖。\n"
    custom_policy = "# 项目自定义策略\nschema: 1\ntiers:\n  hot:\n    - state/current.json\n"
    custom_improvements = "# 项目自定义改进包说明\n"
    custom_phase_plan = "# R1-P2 项目自定义阶段计划\n"
    (contract / "standards" / "CONTEXT.md").write_text(custom_standard, encoding="utf-8")
    (contract / "policies" / "CONTEXT-POLICY.yaml").write_text(custom_policy, encoding="utf-8")
    (contract / "improvements" / "README.md").write_text(custom_improvements, encoding="utf-8")
    custom_plan_path = contract / "roadmap" / "R1" / "phases" / "P2" / "PLAN.md"
    custom_plan_path.write_text(custom_phase_plan, encoding="utf-8")

    # 基线：先完成一次常规同步，再提交 contract，便于校验升级后无意外改动
    upgrade_project(project)
    _git_commit_all(contract)

    # 模拟全局模板更新（bootstrap --force 的等价效果）
    global_agent = home / "templates" / "agents" / "manager.md"
    global_agent.parent.mkdir(parents=True, exist_ok=True)
    global_agent.write_text("# 全局 agent 模板更新\n", encoding="utf-8")
    mirror = project / ".claude" / "agents" / "manager.md"
    old_mirror = mirror.read_text(encoding="utf-8")

    result = upgrade_project(project, force=True)

    # contract 自定义内容保持不变，且 git status 无非预期改动
    assert (contract / "standards" / "CONTEXT.md").read_text(encoding="utf-8") == custom_standard
    assert (contract / "policies" / "CONTEXT-POLICY.yaml").read_text(encoding="utf-8") == custom_policy
    assert (contract / "improvements" / "README.md").read_text(encoding="utf-8") == custom_improvements
    assert custom_plan_path.read_text(encoding="utf-8") == custom_phase_plan
    assert _git_status(contract) == ""

    # 安装镜像仍然更新，并保留旧文件备份
    assert mirror.read_text(encoding="utf-8") == "# 全局 agent 模板更新\n"
    backup = mirror.with_suffix(mirror.suffix + ".bak")
    assert backup.read_text(encoding="utf-8") == old_mirror

    # 升级结果显式声明 contract 同步未使用 force
    assert result["contract"] is not None
    assert result["contract"]["force"] is False


def test_upgrade_backfills_missing_contract_files_without_overwrite(mf_env):
    """upgrade 同步只补缺失骨架文件，不覆盖已有自定义内容（BUG-0015）。"""
    from meta_flow import templates
    from meta_flow.workspace import workspace_init

    project = mf_env["project"]
    install_root(project)
    workspace_init(project, "Demo")
    contract = project / "demo-contract"
    custom = "# 保留我\n"
    (contract / "standards" / "CONTEXT.md").write_text(custom, encoding="utf-8")
    (contract / "standards" / "VERSION.md").unlink()
    (contract / "roadmap" / "R1" / "phases" / "P3" / "PLAN.md").unlink()
    (contract / "improvements" / "README.md").unlink()

    result = upgrade_project(project, force=True)

    assert (contract / "standards" / "VERSION.md").read_text(
        encoding="utf-8"
    ) == templates.STANDARDS["VERSION.md"]
    assert (contract / "roadmap" / "R1" / "phases" / "P3" / "PLAN.md").is_file()
    assert (contract / "improvements" / "README.md").is_file()
    assert (contract / "standards" / "CONTEXT.md").read_text(encoding="utf-8") == custom
    assert result["contract"]["force"] is False
