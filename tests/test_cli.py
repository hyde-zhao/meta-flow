"""CLI 冒烟测试。"""

from __future__ import annotations

import json

from meta_flow.cli import main


def _prepare(tmp_path, monkeypatch):
    home = tmp_path / "global"
    monkeypatch.setenv("META_FLOW_HOME", str(home))
    project = tmp_path / "project"
    project.mkdir()
    return home, project


def test_cli_bootstrap_install_workspace(tmp_path, monkeypatch, capsys):
    _, project = _prepare(tmp_path, monkeypatch)
    assert main(["bootstrap"]) == 0
    assert main(["install", "claude", "--project-dir", str(project), "--init-contract"]) == 0
    assert (project / "project-contract").is_dir()
    assert (
        main(
            [
                "workspace",
                "add-project",
                "--project-dir",
                str(project),
                "--name",
                "frontend",
                "--path",
                "frontend",
            ]
        )
        == 0
    )
    assert main(["doctor", "--path", str(project)]) == 0

    capsys.readouterr()
    assert main(["workspace", "status", "--project-dir", str(project), "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["project"]["id"] == "project"
    assert status["subprojects"][0]["id"] == "frontend"

    assert main(["role", "--path", str(project)]) == 0
    assert main(["role", "--path", str(project / "frontend")]) == 0


def test_cli_improve_smoke(tmp_path, monkeypatch, capsys):
    _, project = _prepare(tmp_path, monkeypatch)
    assert main(["bootstrap"]) == 0
    assert main(["install", "claude", "--project-dir", str(project), "--init-contract"]) == 0
    assert main(["improve", "new", "--project-dir", str(project), "--title", "Add X"]) == 0

    capsys.readouterr()
    assert main(["improve", "list", "--project-dir", str(project), "--json"]) == 0
    items = json.loads(capsys.readouterr().out)
    assert items[0]["id"] == "MFP-0001"

    assert main(["improve", "validate", "--project-dir", str(project), "MFP-0001"]) == 1


def test_cli_task_smoke(tmp_path, monkeypatch, capsys):
    _, project = _prepare(tmp_path, monkeypatch)
    assert main(["bootstrap"]) == 0
    assert main(["install", "claude", "--project-dir", str(project), "--init-contract"]) == 0
    assert (
        main(
            [
                "task",
                "create",
                "--project-dir",
                str(project),
                "--title",
                "文档修正",
                "--risk",
                "low",
                "--acceptance",
                "文档更新完成",
            ]
        )
        == 0
    )

    capsys.readouterr()
    assert main(["task", "list", "--project-dir", str(project), "--json"]) == 0
    items = json.loads(capsys.readouterr().out)
    assert items[0]["id"] == "R1-P1-T001"

    assert main(["task", "show", "--project-dir", str(project), "R1-P1-T001", "--packet"]) == 0
    assert "TASK PACKET" in capsys.readouterr().out
    assert main(["task", "prompt", "--project-dir", str(project), "R1-P1-T001"]) == 0
    assert "responsible_agent: worker" in capsys.readouterr().out


def test_cli_planning_quality_smoke(tmp_path, monkeypatch, capsys):
    _, project = _prepare(tmp_path, monkeypatch)
    assert main(["bootstrap"]) == 0
    assert main(["install", "claude", "--project-dir", str(project), "--init-contract"]) == 0
    root = str(project)
    assert (
        main(
            [
                "req",
                "add",
                "--project-dir",
                root,
                "--title",
                "登录",
                "--acceptance",
                "成功登录",
            ]
        )
        == 0
    )
    assert main(["req", "trace", "--project-dir", root, "REQ-0001"]) == 0
    capsys.readouterr()
    assert main(["roadmap", "show", "--project-dir", root, "--json"]) == 0
    roadmap_data = json.loads(capsys.readouterr().out)
    assert roadmap_data["current"]["roadmap"] == "R1"

    assert (
        main(
            [
                "task",
                "create",
                "--project-dir",
                root,
                "--title",
                "实现登录",
                "--risk",
                "low",
                "--acceptance",
                "完成",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main(["task", "plan", "--project-dir", root, "--json"]) == 0
    plan_data = json.loads(capsys.readouterr().out)
    assert plan_data["ready"][0]["id"] == "R1-P1-T001"
    assert main(["task", "graph", "--project-dir", root, "--json"]) == 0
    capsys.readouterr()

    assert main(["knowledge", "add", "--project-dir", root, "--kind", "term", "--text", "契约库"]) == 0
    capsys.readouterr()
    assert main(["knowledge", "list", "--project-dir", root, "--json"]) == 0
    items = json.loads(capsys.readouterr().out)
    assert items[0]["id"] == "TERM-001"

    assert (
        main(
            [
                "verify",
                "record",
                "--project-dir",
                root,
                "--layer",
                "implementation",
                "--scope",
                "登录",
                "--result",
                "PASS",
                "--requirement",
                "REQ-0001",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main(["verify", "list", "--project-dir", root, "--json"]) == 0
    records = json.loads(capsys.readouterr().out)
    assert records[0]["id"] == "VR-0001"

    assert main(["bug", "add", "--project-dir", root, "--title", "登录报错", "--severity", "major"]) == 0
    capsys.readouterr()
    assert main(["bug", "list", "--project-dir", root, "--json"]) == 0
    bugs = json.loads(capsys.readouterr().out)
    assert bugs[0]["id"] == "BUG-0001"

    assert main(["archive", "list", "--project-dir", root, "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []
    assert main(["log", "--project-dir", root, "--limit", "5", "--json"]) == 0
    logs = json.loads(capsys.readouterr().out)
    assert logs
    assert main(["doctor", "--path", root]) == 0


def test_cli_req_list_scopes_current_roadmap(tmp_path, monkeypatch, capsys):
    _, project = _prepare(tmp_path, monkeypatch)
    assert main(["bootstrap"]) == 0
    assert main(["install", "claude", "--project-dir", str(project), "--init-contract"]) == 0
    root = str(project)
    assert main(["req", "add", "--project-dir", root, "--title", "当前", "--acceptance", "ok"]) == 0
    assert (
        main(
            [
                "req",
                "add",
                "--project-dir",
                root,
                "--title",
                "下一版",
                "--roadmap",
                "R2",
                "--acceptance",
                "ok",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main(["req", "list", "--project-dir", root, "--json"]) == 0
    current = json.loads(capsys.readouterr().out)
    assert [item["id"] for item in current] == ["REQ-0001"]
    assert main(["req", "list", "--project-dir", root, "--all", "--json"]) == 0
    all_items = json.loads(capsys.readouterr().out)
    assert [item["id"] for item in all_items] == ["REQ-0001", "REQ-0002"]


def test_cli_install_status_uninstall(tmp_path, monkeypatch, capsys):
    _, project = _prepare(tmp_path, monkeypatch)
    assert main(["install", "claude", "--project-dir", str(project)]) == 0

    capsys.readouterr()
    assert main(["status", "--path", str(project), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["role"] == "manager"

    assert main(["uninstall", "claude", "--project-dir", str(project)]) == 0
    assert not (project / ".claude" / "agents" / "manager.md").exists()
    assert not (project / ".meta-flow" / "install.yaml").exists()


def test_cli_doctor_global(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    assert main(["bootstrap"]) == 0
    assert main(["doctor", "--global"]) == 0


def test_cli_role_unbound(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    assert main(["role", "--path", str(tmp_path / "empty")]) == 2
