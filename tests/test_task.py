"""任务卡、评审任务与状态机测试。"""

from __future__ import annotations

import pytest

from meta_flow.global_store import bootstrap
from meta_flow.install import install_root
from meta_flow.task import (
    TaskError,
    accept_task,
    create_task,
    list_tasks,
    load_task,
    packet_text,
    prompt_text,
    reject_task,
    start_task,
    submit_task,
)
from meta_flow.workspace import workspace_init


@pytest.fixture()
def task_env(tmp_path, monkeypatch):
    home = tmp_path / "global"
    monkeypatch.setenv("META_FLOW_HOME", str(home))
    bootstrap()
    root = tmp_path / "demo"
    root.mkdir()
    install_root(root)
    workspace_init(root, "Demo")
    return {"root": root, "contract": root / "demo-contract"}


def _acceptance():
    return [{"id": "A1", "method": "artifact", "expect": "实现完成"}]


def _write_worker_files(contract, task_id):
    bundle = contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / f"T{task_id[-3:]}"
    (bundle / "dev-record.md").write_text("# dev\n实现完成\n", encoding="utf-8")
    (bundle / "handoff.md").write_text("# handoff\n完成\n", encoding="utf-8")
    return bundle


def test_create_low_task(task_env):
    root = task_env["root"]
    result = create_task(root, "文档修正", risk="low", acceptance=_acceptance())
    assert result["task"] == "R1-P1-T001"
    assert result["review_task"] is None
    _, task = load_task(root, "R1-P1-T001")
    assert task["status"] == "ready"
    assert task["next_owner"] == "worker"
    assert task["review"]["mode"] == "manager"
    assert "responsible_agent: worker" in prompt_text(root, "R1-P1-T001")


def test_create_high_task_auto_review(task_env):
    root = task_env["root"]
    result = create_task(root, "安装器改动", risk="high", acceptance=_acceptance())
    assert result["task"] == "R1-P1-T001"
    assert result["review_task"] == "R1-P1-T002"
    _, task = load_task(root, "R1-P1-T001")
    _, review = load_task(root, "R1-P1-T002")
    assert task["reviewed_by_task"] == "R1-P1-T002"
    assert review["kind"] == "review"
    assert review["reviews"] == "R1-P1-T001"
    assert review["status"] == "draft"


def test_low_risk_flow(task_env):
    root = task_env["root"]
    contract = task_env["contract"]
    create_task(root, "文档修正", risk="low", acceptance=_acceptance())
    start_task(root, "R1-P1-T001")
    _write_worker_files(contract, "R1-P1-T001")
    data = submit_task(root, "R1-P1-T001")
    assert data["status"] == "submitted"
    assert data["next_owner"] == "manager"
    assert "responsible_agent: manager" in prompt_text(root, "R1-P1-T001")
    accepted = accept_task(root, "R1-P1-T001", verdict="PASS")
    assert accepted["status"] == "accepted"


def test_high_risk_review_flow(task_env):
    root = task_env["root"]
    contract = task_env["contract"]
    result = create_task(root, "安装器改动", risk="high", acceptance=_acceptance())
    task_id = result["task"]
    review_id = result["review_task"]

    start_task(root, task_id)
    _write_worker_files(contract, task_id)
    task = submit_task(root, task_id)
    assert task["next_owner"] == "worker"
    _, review = load_task(root, review_id)
    assert review["status"] == "ready"
    prompt = prompt_text(root, task_id)
    assert f"review_task: {review_id}" in prompt
    assert "--review-packet" in prompt

    with pytest.raises(TaskError):
        accept_task(root, task_id, verdict="PASS")

    start_task(root, review_id)
    bundle = contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / f"T{review_id[-3:]}"
    (bundle / "handoff.md").write_text("# review handoff\n通过\n", encoding="utf-8")
    (bundle / "review.md").write_text("# review\nPASS\n", encoding="utf-8")
    (bundle / "review-handoff.md").write_text(
        "# review handoff\nverdict: PASS\n", encoding="utf-8"
    )
    submit_task(root, review_id)
    accept_task(root, review_id, verdict="PASS")

    accepted = accept_task(root, task_id, verdict="PASS")
    assert accepted["status"] == "accepted"


def test_reject_resets_review(task_env):
    root = task_env["root"]
    contract = task_env["contract"]
    result = create_task(root, "安装器改动", risk="high", acceptance=_acceptance())
    task_id = result["task"]
    review_id = result["review_task"]
    start_task(root, task_id)
    _write_worker_files(contract, task_id)
    submit_task(root, task_id)
    rejected = reject_task(root, task_id, "验收不通过")
    assert rejected["status"] == "rejected"
    assert rejected["next_owner"] == "worker"
    _, review = load_task(root, review_id)
    assert review["status"] == "ready"
    assert review["review_verdict"] is None


def test_packet_and_list(task_env):
    root = task_env["root"]
    create_task(root, "文档修正", risk="low", acceptance=_acceptance())
    text = packet_text(root, "R1-P1-T001")
    assert "TASK PACKET R1-P1-T001" in text
    review_text = packet_text(root, "R1-P1-T001", review=True)
    assert "REVIEW PACKET" in review_text
    items = list_tasks(root)
    assert items[0]["id"] == "R1-P1-T001"
