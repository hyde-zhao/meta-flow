"""工作区初始化、子项目、link/sync 与 doctor 测试。"""

from __future__ import annotations

import json

import pytest
import yaml

from meta_flow.global_store import bootstrap
from meta_flow.install import install_root
from meta_flow.workspace import (
    WorkspaceError,
    detect_role,
    doctor,
    doctor_global,
    workspace_add_project,
    workspace_init,
    workspace_link,
    workspace_status,
    workspace_sync,
    workspace_upgrade,
)


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    home = tmp_path / "global"
    monkeypatch.setenv("META_FLOW_HOME", str(home))
    bootstrap()
    root = tmp_path / "demo"
    root.mkdir()
    install_root(root)
    workspace_init(root, "Demo App")
    return {"home": home, "root": root, "contract": root / "demo-app-contract"}


def test_workspace_layout(ws):
    root = ws["root"]
    contract = ws["contract"]
    assert contract.is_dir()
    assert (contract / "workspace" / "CLAUDE.md").is_file()
    assert (contract / "workspace" / "README.md").is_file()
    assert (contract / "workspace" / "mf.workspace.yaml").is_file()
    assert (contract / "project" / "PROJECT-PLAN.md").is_file()
    assert (contract / "standards" / "CONTEXT.md").is_file()
    assert (contract / "state" / "current.json").is_file()
    assert (contract / ".git").is_dir()
    assert (root / ".meta-flow" / "workspace.yaml").is_file()
    claude = (root / "CLAUDE.md").read_text(encoding="utf-8")
    assert "@demo-app-contract/workspace/CLAUDE.md" in claude
    assert (root / "README.md").is_symlink()
    assert (root / "README.md").resolve() == (contract / "workspace" / "README.md").resolve()


def test_add_project(ws):
    root = ws["root"]
    result = workspace_add_project(root, "frontend", "frontend")
    sub = root / "frontend"
    assert result["delivery"] == "frontend"
    assert (sub / ".claude" / "agents" / "worker.md").is_file()
    assert (sub / "delivery.yaml").is_file()
    settings = json.loads((sub / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert settings["agent"] == "worker"
    assert (sub / ".git").is_dir()

    status = workspace_status(root)
    assert status["subprojects"][0]["id"] == "frontend"
    manifest = (ws["contract"] / "workspace" / "mf.workspace.yaml").read_text(encoding="utf-8")
    assert "frontend" in manifest


def test_add_project_writes_gitignore(ws):
    root = ws["root"]
    assert not (root / ".gitignore").exists()

    workspace_add_project(root, "frontend", "frontend")
    gitignore = root / "frontend" / ".gitignore"
    first = gitignore.read_text(encoding="utf-8")
    for pattern in ("CLAUDE.md", ".claude/", ".meta-flow/"):
        assert pattern in first

    workspace_add_project(root, "frontend", "frontend")
    assert gitignore.read_text(encoding="utf-8") == first

    assert workspace_sync(root, check=True)["ok"]
    assert doctor(root) == []


def test_workspace_link_recreates(ws):
    root = ws["root"]
    (root / "CLAUDE.md").unlink()
    workspace_link(root)
    claude = (root / "CLAUDE.md").read_text(encoding="utf-8")
    assert "@demo-app-contract/workspace/CLAUDE.md" in claude


def test_workspace_sync_check(ws):
    result = workspace_sync(ws["root"], check=True)
    assert result["ok"], result["errors"]


def test_doctor_ok(ws):
    assert doctor(ws["root"]) == []


def test_doctor_missing_worker_agent(ws):
    root = ws["root"]
    workspace_add_project(root, "frontend", "frontend")
    (root / "frontend" / ".claude" / "agents" / "worker.md").unlink()
    errors = doctor(root)
    assert any("worker agent" in error for error in errors)


def test_doctor_global(ws):
    assert doctor_global() == []


def test_detect_role(ws):
    root = ws["root"]
    assert detect_role(root)[0] == "manager"
    assert detect_role(ws["contract"])[0] == "manager"
    workspace_add_project(root, "frontend", "frontend")
    assert detect_role(root / "frontend")[0] == "worker"


def test_workspace_init_explicit_baseline(tmp_path, monkeypatch):
    home = tmp_path / "global"
    monkeypatch.setenv("META_FLOW_HOME", str(home))
    bootstrap()
    root = tmp_path / "legacy"
    root.mkdir()
    install_root(root)

    result = workspace_init(root, "Legacy App", roadmap="R0", phase="P4", version="0.1.1")
    contract = root / "legacy-app-contract"
    assert result["roadmap"] == "R0"
    assert result["phase"] == "P4"
    assert result["version"] == "0.1.1"

    roadmap_data = yaml.safe_load(
        (contract / "roadmap" / "ROADMAP.yaml").read_text(encoding="utf-8")
    )
    item = roadmap_data["roadmaps"][0]
    assert item["id"] == "R0"
    assert item["status"] == "active"
    assert item["version_range"] == "0.x"
    assert item["version_target"] == "0.1.1"
    assert item["title"] == "R0 基线"

    current = json.loads((contract / "state" / "current.json").read_text(encoding="utf-8"))
    assert current["roadmap"] == "R0"
    assert current["phase"] == "P4"
    assert current["version"] == "0.1.1"
    assert current["next_action"]["text"] == "完成 P4 计划与 INIT-CHECKLIST"

    assert (contract / "roadmap" / "R0" / "PLAN.md").is_file()
    assert (contract / "roadmap" / "R0" / "phases" / "P4" / "PLAN.md").is_file()
    assert not (contract / "roadmap" / "R1").exists()
    plan_text = (contract / "project" / "PROJECT-PLAN.md").read_text(encoding="utf-8")
    assert "roadmap: R0" in plan_text
    assert "roadmap: R1" not in plan_text
    assert doctor(root) == []


def test_workspace_init_rejects_invalid_baseline(tmp_path, monkeypatch):
    home = tmp_path / "global"
    monkeypatch.setenv("META_FLOW_HOME", str(home))
    bootstrap()
    root = tmp_path / "legacy"
    root.mkdir()
    install_root(root)

    for kwargs in ({"roadmap": "X1"}, {"phase": "P9"}, {"version": "0.1"}):
        with pytest.raises(WorkspaceError):
            workspace_init(root, "Legacy App", **kwargs)
    assert not (root / "legacy-app-contract").exists()


def test_workspace_upgrade_rebuilds_baseline_state(tmp_path, monkeypatch):
    home = tmp_path / "global"
    monkeypatch.setenv("META_FLOW_HOME", str(home))
    bootstrap()
    root = tmp_path / "legacy"
    root.mkdir()
    install_root(root)
    workspace_init(root, "Legacy App", roadmap="R0", phase="P4", version="0.1.1")
    contract = root / "legacy-app-contract"
    (contract / "state" / "current.json").unlink()

    workspace_upgrade(root)
    current = json.loads((contract / "state" / "current.json").read_text(encoding="utf-8"))
    assert current["roadmap"] == "R0"
    assert current["phase"] == "P1"
    assert current["version"] == "0.1.1"
