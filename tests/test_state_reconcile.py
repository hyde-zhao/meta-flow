"""任务/状态一致性对账与重建（MFP-0018）。"""

from __future__ import annotations

import json

import yaml

from meta_flow import state
from meta_flow.cli import main
from meta_flow.global_store import bootstrap
from meta_flow.install import install_root
from meta_flow.task import accept_task, create_task, start_task, submit_task
from meta_flow.workspace import doctor, workspace_init


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
    return root, root / "demo-contract"


def _task_path(contract, task_id):
    tail = task_id.rsplit("-", 1)[-1]
    return contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / tail / "TASK.yaml"


def _accept_low_task(root, contract, task_id):
    start_task(root, task_id)
    bundle = _task_path(contract, task_id).parent
    (bundle / "dev-record.md").write_text("# dev\n完成\n", encoding="utf-8")
    (bundle / "handoff.md").write_text("# handoff\n完成\n", encoding="utf-8")
    submit_task(root, task_id)
    accept_task(root, task_id, verdict="PASS")


def test_reconcile_detects_stale_ready_and_rebuild_is_idempotent(tmp_path, monkeypatch):
    root, contract = _env(tmp_path, monkeypatch)
    create_task(root, "低风险任务", risk="low", acceptance=_acceptance())
    _accept_low_task(root, contract, "R1-P1-T001")

    current = state.read_current(contract)
    current.setdefault("ready_tasks", []).append("R1-P1-T001")
    state.write_current(contract, current)

    issues = state.reconcile(contract)
    assert any("ready_tasks" in issue and "R1-P1-T001" in issue for issue in issues)
    errors = doctor(root)
    assert any("状态对账" in error for error in errors)

    rebuilt = state.rebuild(contract)
    assert rebuilt["counts"] == {"accepted": 1}
    assert "R1-P1-T001" not in (rebuilt.get("ready_tasks") or [])
    assert state.reconcile(contract) == []

    again = state.rebuild(contract)
    assert again["counts"] == rebuilt["counts"]
    assert state.reconcile(contract) == []
    ledger = (contract / "state" / "ledger.ndjson").read_text(encoding="utf-8")
    assert ledger.count("state.rebuild") == 2
    events = [json.loads(line) for line in ledger.splitlines() if line.strip()]
    assert any(event.get("event") == "state.rebuild" for event in events)


def test_rebuild_keeps_active_task_and_lease(tmp_path, monkeypatch):
    root, contract = _env(tmp_path, monkeypatch)
    create_task(root, "任务 A", risk="low", acceptance=_acceptance())
    create_task(root, "任务 B", risk="low", acceptance=_acceptance())
    start_task(root, "R1-P1-T001")
    start_task(root, "R1-P1-T002")

    rebuilt = state.rebuild(contract)
    assert "R1-P1-T001" in rebuilt["active_tasks"]
    assert "R1-P1-T002" in rebuilt["active_tasks"]
    leases = {lease["task"] for lease in rebuilt["active_leases"]}
    assert {"R1-P1-T001", "R1-P1-T002"} <= leases
    task = yaml.safe_load(_task_path(contract, "R1-P1-T001").read_text(encoding="utf-8"))
    assert task["status"] == "in_progress"
    assert task["lease"]["expires_at"]
    assert state.reconcile(contract) == []


def test_submitted_task_awaiting_review_is_consistent(tmp_path, monkeypatch):
    root, contract = _env(tmp_path, monkeypatch)
    result = create_task(root, "高风险任务", risk="high", acceptance=_acceptance())
    task_id = result["task"]
    start_task(root, task_id)
    bundle = _task_path(contract, task_id).parent
    (bundle / "dev-record.md").write_text("# dev\n完成\n", encoding="utf-8")
    (bundle / "handoff.md").write_text("# handoff\n完成\n", encoding="utf-8")
    submit_task(root, task_id)
    assert state.reconcile(contract) == []


def test_reconcile_detects_manual_task_card_edit(tmp_path, monkeypatch):
    root, contract = _env(tmp_path, monkeypatch)
    create_task(root, "任务", risk="low", acceptance=_acceptance())
    path = _task_path(contract, "R1-P1-T001")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["status"] = "accepted"
    data["next_owner"] = "manager"
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")

    issues = state.reconcile(contract)
    assert any("counts" in issue for issue in issues)
    assert any("ledger" in issue or "source_digest" in issue for issue in issues)
    errors = doctor(root)
    assert any("状态对账" in error for error in errors)

    state.rebuild(contract)
    assert state.reconcile(contract) == []


def test_state_cli_show_and_rebuild(tmp_path, monkeypatch, capsys):
    root, contract = _env(tmp_path, monkeypatch)
    create_task(root, "任务", risk="low", acceptance=_acceptance())
    current = state.read_current(contract)
    current["ready_tasks"] = ["R1-P1-T999"]
    state.write_current(contract, current)

    capsys.readouterr()
    assert main(["state", "show", "--project-dir", str(root)]) == 1
    out = capsys.readouterr().out
    assert "状态对账: FAIL" in out and "R1-P1-T999" in out

    assert main(["state", "rebuild", "--project-dir", str(root)]) == 0
    out = capsys.readouterr().out
    assert "state 已重建" in out and "状态对账: OK" in out
    assert main(["state", "show", "--project-dir", str(root)]) == 0
    assert "状态对账: OK" in capsys.readouterr().out
