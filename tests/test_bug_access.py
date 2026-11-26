"""worker 读取任务关联 BUG（MFP-0024）。"""

from __future__ import annotations

import json

from meta_flow import bug
from meta_flow.cli import main
from meta_flow.global_store import bootstrap
from meta_flow.install import install_root
from meta_flow.task import create_task, packet_text, start_task
from meta_flow.workspace import workspace_add_project, workspace_init


def _acceptance():
    return [{"id": "A1", "method": "artifact", "expect": "完成"}]


def _env(tmp_path, monkeypatch):
    home = tmp_path / "global"
    monkeypatch.setenv("META_FLOW_HOME", str(home))
    bootstrap()
    root = tmp_path / "demo"
    root.mkdir()
    install_root(root)
    workspace_init(root, "Demo")
    sub = root / "frontend"
    workspace_add_project(root, "frontend", "frontend")
    return root, root / "demo-contract", sub


def test_packet_embeds_linked_bug_summary(tmp_path, monkeypatch):
    root, _contract, _sub = _env(tmp_path, monkeypatch)
    linked = bug.add_bug(root, "启动崩溃", severity="major", expected="正常启动", actual="崩溃")
    create_task(
        root,
        "修复启动崩溃",
        kind="fix",
        risk="low",
        delivery="frontend",
        fixes=[linked["id"]],
        acceptance=_acceptance(),
    )
    text = packet_text(root, "R1-P1-T001")
    assert "## Linked BUGs" in text
    assert linked["id"] in text and "启动崩溃" in text
    assert "expected" in text and "正常启动" in text


def test_worker_bug_show_only_task_linked_and_audited(tmp_path, monkeypatch, capsys):
    root, contract, sub = _env(tmp_path, monkeypatch)
    linked = bug.add_bug(root, "关联缺陷", severity="major")
    other = bug.add_bug(root, "无关缺陷", severity="minor")
    create_task(
        root,
        "修复关联缺陷",
        kind="fix",
        risk="low",
        delivery="frontend",
        fixes=[linked["id"]],
        acceptance=_acceptance(),
    )
    start_task(sub, "R1-P1-T001")
    monkeypatch.chdir(sub)

    capsys.readouterr()
    assert main(["bug", "show", linked["id"]]) == 0
    out = capsys.readouterr().out
    assert linked["id"] in out

    assert main(["bug", "show", other["id"]]) == 3
    assert "活动任务" in capsys.readouterr().err

    log = (contract / "state" / "READ-LOG.ndjson").read_text(encoding="utf-8")
    records = [json.loads(line) for line in log.splitlines() if line.strip()]
    assert any(
        record.get("event") == "bug.show" and record.get("decision") == "allow"
        for record in records
    )


def test_manager_bug_show_unaffected(tmp_path, monkeypatch, capsys):
    root, _contract, _sub = _env(tmp_path, monkeypatch)
    item = bug.add_bug(root, "任意缺陷", severity="minor")
    monkeypatch.chdir(root)
    capsys.readouterr()
    assert main(["bug", "show", item["id"]]) == 0
    assert item["id"] in capsys.readouterr().out
