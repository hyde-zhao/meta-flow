"""review 任务读取 review_scope 大文件与只读 expand（MFP-0027）。"""

from __future__ import annotations

import pytest

from meta_flow import context, guard
from meta_flow.global_store import bootstrap
from meta_flow.install import install_root
from meta_flow.task import create_task, start_task, submit_task
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


def _payload(tool, cwd, path):
    return {"tool_name": tool, "cwd": str(cwd), "tool_input": {"file_path": str(path)}}


def _bash(command, cwd):
    return {"tool_name": "Bash", "cwd": str(cwd), "tool_input": {"command": command}}


def _review_env(tmp_path, monkeypatch):
    root, contract, sub = _env(tmp_path, monkeypatch)
    result = create_task(
        root,
        "高风险改动",
        risk="high",
        delivery="frontend",
        review_scope=["src/**"],
        acceptance=_acceptance(),
    )
    task_id, review_id = result["task"], result["review_task"]
    start_task(sub, task_id)
    bundle = contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / ("T" + task_id[-3:])
    (bundle / "dev-record.md").write_text("# dev\n完成\n", encoding="utf-8")
    (bundle / "handoff.md").write_text("# handoff\n完成\n", encoding="utf-8")
    submit_task(sub, task_id)
    start_task(sub, review_id)
    (sub / "src").mkdir(parents=True, exist_ok=True)
    big = sub / "src" / "big.py"
    big.write_text("x" * (70 * 1024), encoding="utf-8")
    outside = sub / "docs" / "big.md"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text("x" * (70 * 1024), encoding="utf-8")
    monkeypatch.setenv("MF_ROLE", "worker")
    return root, contract, sub, big, outside, review_id


def test_review_read_budget_exempts_review_scope(tmp_path, monkeypatch):
    _root, _contract, sub, big, outside, _review = _review_env(tmp_path, monkeypatch)
    assert guard.pretool_decision(_payload("Read", sub, big)) is None
    decision = guard.pretool_decision(_payload("Read", sub, outside))
    assert decision is not None
    assert "读预算" in decision["hookSpecificOutput"]["permissionDecisionReason"]

    assert guard.pretool_decision(_bash(f"cat {big}", sub)) is None
    decision = guard.pretool_decision(_bash(f"cat {outside}", sub))
    assert decision is not None


def test_review_expand_review_scope_and_audit(tmp_path, monkeypatch):
    _root, contract, sub, big, outside, _review = _review_env(tmp_path, monkeypatch)
    expanded = context.expand(sub, str(big), reason="packet_missing", actor="worker")
    assert expanded["bytes"] == 70 * 1024
    with pytest.raises(context.ContextError, match="allowed_paths"):
        context.expand(sub, str(outside), reason="packet_missing", actor="worker")
    log = (contract / "state" / "READ-LOG.ndjson").read_text(encoding="utf-8")
    assert "context.expand" in log


def test_review_scope_negative_still_denied_for_other_files(tmp_path, monkeypatch):
    _root, contract, sub, _big, _outside, _review = _review_env(tmp_path, monkeypatch)
    other_task = contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / "T999" / "dev-record.md"
    other_task.parent.mkdir(parents=True, exist_ok=True)
    other_task.write_text("# other\n", encoding="utf-8")
    decision = guard.pretool_decision(_payload("Read", sub, other_task))
    assert decision is not None
