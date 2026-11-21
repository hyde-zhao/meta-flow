"""CLI 冒烟测试。"""

from __future__ import annotations

import json

from meta_flow.cli import main


def test_cli_init_doctor_role_status(tmp_path, capsys):
    target = tmp_path / "ws"
    assert (
        main(
            [
                "init",
                "--path",
                str(target),
                "--name",
                "demo",
                "--delivery",
                "app",
                "--no-git",
            ]
        )
        == 0
    )
    assert main(["doctor", "--path", str(target)]) == 0
    assert main(["role", "--path", str(target / "contracts")]) == 0

    capsys.readouterr()  # 清空前面命令的输出
    assert main(["status", "--path", str(target), "--json"]) == 0
    output = capsys.readouterr().out
    data = json.loads(output)
    assert data["project"]["name"] == "demo"
    assert data["role"] == "maintainer"


def test_cli_role_unbound(tmp_path):
    assert main(["role", "--path", str(tmp_path / "empty")]) == 2


def test_cli_doctor_reports_failure(tmp_path):
    target = tmp_path / "ws"
    assert main(["init", "--path", str(target), "--name", "demo", "--no-git"]) == 0
    assert main(["doctor", "--path", str(target)]) == 0

    (target / "deliveries" / "app" / "USER-MANUAL.md").unlink()
    assert main(["doctor", "--path", str(target)]) == 1
