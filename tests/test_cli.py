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
