"""BLOCKED 提交不推进独立评审，转 manager 裁决（MFP-0026）。"""

from __future__ import annotations

import json

from meta_flow import state
from meta_flow.cli import main
from meta_flow.global_store import bootstrap
from meta_flow.install import install_root
from meta_flow.task import create_task, load_task, prompt_text, start_task, submit_task
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


def _write_handoff(contract, task_id, text):
    tail = task_id.rsplit("-", 1)[-1]
    bundle = contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / tail
    (bundle / "dev-record.md").write_text("# dev\n阻塞分析\n", encoding="utf-8")
    (bundle / "handoff.md").write_text(text, encoding="utf-8")


def test_blocked_submit_routes_to_manager_and_keeps_review_draft(tmp_path, monkeypatch):
    root, contract, _sub = _env(tmp_path, monkeypatch)
    result = create_task(root, "高风险改动", risk="high", acceptance=_acceptance())
    task_id, review_id = result["task"], result["review_task"]
    start_task(root, task_id)
    _write_handoff(
        contract,
        task_id,
        "# handoff\n\n## 完成摘要\n修复点不在 allowed_paths。\n\n结论: BLOCKED\n",
    )

    data = submit_task(root, task_id)
    assert data["status"] == "blocked"
    assert data["next_owner"] == "manager"
    assert data["lease"] is None
    assert load_task(root, str(review_id))[1]["status"] == "draft"

    prompt = prompt_text(root, task_id)
    assert "responsible_agent: manager" in prompt
    assert "BLOCKED" in prompt and "裁决" in prompt

    hot = state.read_current(contract)
    assert hot["next_action"]["type"] == "blocked_decision"
    assert hot["next_action"]["task"] == task_id

    ledger = (contract / "state" / "ledger.ndjson").read_text(encoding="utf-8")
    events = [json.loads(line) for line in ledger.splitlines() if line.strip()]
    blocked_events = [event for event in events if event.get("event") == "task.blocked"]
    assert blocked_events and blocked_events[-1]["to"] == "blocked"

    # 恢复路径：manager reject 后 worker 重新 start
    from meta_flow.task import reject_task

    rejected = reject_task(root, task_id, "补 allowed_paths 后重做")
    assert rejected["status"] == "rejected"
    started = start_task(root, task_id)
    assert started["status"] == "in_progress"


def test_submit_blocked_flag_and_normal_submit(tmp_path, monkeypatch):
    root, contract, _sub = _env(tmp_path, monkeypatch)
    create_task(root, "普通任务", risk="low", acceptance=_acceptance())
    start_task(root, "R1-P1-T001")
    _write_handoff(contract, "R1-P1-T001", "# handoff\n完成\n")
    data = submit_task(root, "R1-P1-T001", blocked=True)
    assert data["status"] == "blocked"
    assert data["next_owner"] == "manager"

    create_task(root, "正常任务", risk="low", acceptance=_acceptance())
    start_task(root, "R1-P1-T002")
    _write_handoff(contract, "R1-P1-T002", "# handoff\n完成\n")
    normal = submit_task(root, "R1-P1-T002")
    assert normal["status"] == "submitted"
    assert normal["next_owner"] == "manager"


def test_cli_submit_blocked(tmp_path, monkeypatch, capsys):
    root, contract, sub = _env(tmp_path, monkeypatch)
    create_task(
        root, "任务", risk="low", delivery="frontend", acceptance=_acceptance()
    )
    start_task(sub, "R1-P1-T001")
    _write_handoff(contract, "R1-P1-T001", "# handoff\n结论: BLOCKED\n")
    monkeypatch.chdir(sub)
    capsys.readouterr()
    assert (
        main(
            [
                "task",
                "submit",
                "R1-P1-T001",
                "--blocked",
                "--handoff",
                str(contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / "T001" / "handoff.md"),
                "--dev-record",
                str(contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / "T001" / "dev-record.md"),
            ]
        )
        == 0
    )
    assert "blocked" in capsys.readouterr().out
    assert load_task(root, "R1-P1-T001")[1]["status"] == "blocked"
