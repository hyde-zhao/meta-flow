"""工作区初始化、子项目、link/sync 与 doctor 测试。"""

from __future__ import annotations

import json

import pytest

from meta_flow.global_store import bootstrap
from meta_flow.install import install_root
from meta_flow.workspace import (
    detect_role,
    doctor,
    doctor_global,
    workspace_add_project,
    workspace_init,
    workspace_link,
    workspace_status,
    workspace_sync,
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
