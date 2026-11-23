"""门禁、角色、路径与审计边界的负向测试。"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from meta_flow import context, roadmap, state, verify
from meta_flow.cli import main
from meta_flow.global_store import bootstrap
from meta_flow.install import install_root
from meta_flow.task import (
    TaskError,
    accept_task,
    create_task,
    load_task,
    start_task,
    submit_task,
)
from meta_flow.workspace import workspace_add_project, workspace_init


@pytest.fixture()
def env(tmp_path, monkeypatch):
    home = tmp_path / "global"
    monkeypatch.setenv("META_FLOW_HOME", str(home))
    bootstrap()
    root = tmp_path / "demo"
    root.mkdir()
    install_root(root)
    workspace_init(root, "Demo")
    return root, root / "demo-contract"


def _acceptance():
    return [{"id": "A1", "method": "artifact", "expect": "完成"}]


def _write_task_files(contract, task_id, review_text: str | None = None):
    bundle = contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / f"T{task_id[-3:]}"
    (bundle / "dev-record.md").write_text("# dev\n实现完成\n", encoding="utf-8")
    (bundle / "handoff.md").write_text("# handoff\n完成\n", encoding="utf-8")
    if review_text is not None:
        (bundle / "review.md").write_text(review_text, encoding="utf-8")
        (bundle / "review-handoff.md").write_text(review_text, encoding="utf-8")


def _set_state(contract, *, phase="P5", phase_status="exited", gate=True):
    current = state.read_current(contract)
    current.update({"phase": phase, "phase_status": phase_status})
    if gate:
        current["last_phase_gate"] = {
            "roadmap": current.get("roadmap", "R1"),
            "phase": phase,
            "next_phase": None,
            "approved_by": "user",
            "at": "2026-01-01T00:00:00+00:00",
        }
    else:
        current.pop("last_phase_gate", None)
    state.write_current(contract, current)


def test_phase_cannot_skip_exit_or_gate(env):
    root, contract = env
    with pytest.raises(roadmap.RoadmapError):
        roadmap.phase_enter(root, "P2")

    roadmap.phase_exit(root, approved_by="user", force=True)
    assert state.read_current(contract)["phase_status"] == "exited"
    roadmap.phase_enter(root, "P2")
    with pytest.raises(roadmap.RoadmapError):
        roadmap.phase_enter(root, "P3")
    with pytest.raises(roadmap.RoadmapError):
        roadmap.phase_exit(root, force=True)  # force 不能绕过用户门禁

    roadmap.phase_exit(root, approved_by="user", force=True)
    roadmap.phase_enter(root, "P3")
    with pytest.raises(roadmap.RoadmapError):
        roadmap.phase_enter(root, "P5")


def test_release_and_close_require_p5_gate(env):
    root, _ = env
    _set_state(root / "demo-contract", phase="P5", phase_status="active", gate=False)
    with pytest.raises(verify.VerifyError):
        verify.release_freeze(root, force=True)
    with pytest.raises(roadmap.RoadmapError):
        roadmap.close(root, "R1", force=True)

    _set_state(root / "demo-contract", phase="P5", phase_status="exited", gate=True)
    with pytest.raises(verify.VerifyError):
        verify.release_freeze(root, version="2.0.0")  # 版本 MAJOR 不一致


def test_high_risk_cannot_downgrade_review(env):
    root, _ = env
    with pytest.raises(TaskError):
        create_task(root, "高风险", risk="high", review_mode="manager", acceptance=_acceptance())
    with pytest.raises(TaskError):
        create_task(root, "高风险", risk="high", with_review=False, acceptance=_acceptance())


def test_critical_requires_user_acceptance_and_review_verdict(env):
    root, contract = env
    result = create_task(root, "关键改动", risk="critical", acceptance=_acceptance())
    task_id, review_id = result["task"], result["review_task"]
    assert review_id is not None

    start_task(root, task_id)
    _write_task_files(contract, task_id)
    submit_task(root, task_id)

    start_task(root, review_id)
    _write_task_files(contract, review_id, "# review\nverdict: PASS\n")
    submit_task(root, review_id)
    with pytest.raises(TaskError):
        accept_task(root, review_id, verdict="NEEDS_REWORK")

    accept_task(root, review_id, verdict="PASS")
    with pytest.raises(TaskError):
        accept_task(root, task_id, verdict="PASS")
    accepted = accept_task(root, task_id, verdict="PASS", user_approved_by="product-owner")
    assert accepted["status"] == "accepted"
    assert accepted["user_approved_by"] == "product-owner"


def test_allowed_paths_are_enforced(env):
    root, contract = env
    sub = root / "frontend"
    workspace_add_project(root, "frontend", "frontend")
    subprocess.run(["git", "init"], cwd=sub, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=sub, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-m", "init"],
        cwd=sub,
        check=True,
        capture_output=True,
    )
    create_task(
        root,
        "前端任务",
        risk="low",
        delivery="frontend",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
    )
    start_task(sub, "R1-P1-T001")
    _write_task_files(contract, "R1-P1-T001")
    (sub / "outside.txt").write_text("越界\n", encoding="utf-8")
    with pytest.raises(TaskError, match="allowed_paths"):
        submit_task(sub, "R1-P1-T001")

    (sub / "outside.txt").unlink()
    (sub / "src").mkdir(exist_ok=True)
    (sub / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
    submitted = submit_task(sub, "R1-P1-T001")
    assert submitted["status"] == "submitted"


def test_allowed_paths_without_git_snapshot(env):
    root, contract = env
    sub = root / "backend"
    workspace_add_project(root, "backend", "backend")
    (sub / ".git").rename(sub / ".git.disabled")
    shutil.rmtree(sub / ".git.disabled")
    create_task(
        root,
        "后端任务",
        risk="low",
        delivery="backend",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
    )
    start_task(sub, "R1-P1-T001")
    _write_task_files(contract, "R1-P1-T001")
    (sub / "outside.txt").write_text("越界\n", encoding="utf-8")
    with pytest.raises(TaskError, match="allowed_paths"):
        submit_task(sub, "R1-P1-T001")
    (sub / "outside.txt").unlink()
    (sub / "src").mkdir(exist_ok=True)
    (sub / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
    assert submit_task(sub, "R1-P1-T001")["status"] == "submitted"


def test_start_rejects_unmet_dependency_and_wave_conflict(env):
    root, _ = env
    create_task(
        root,
        "基础",
        risk="low",
        acceptance=_acceptance(),
        wave="W1",
        allowed_paths=["src/**"],
    )
    create_task(
        root,
        "并行",
        risk="low",
        acceptance=_acceptance(),
        wave="W1",
        allowed_paths=["src/**"],
    )
    create_task(
        root,
        "后续",
        risk="low",
        acceptance=_acceptance(),
        wave="W2",
        allowed_paths=["tests/**"],
        depends_on=["R1-P1-T001"],
    )
    with pytest.raises(TaskError, match="尚未 accepted"):
        start_task(root, "R1-P1-T003")
    start_task(root, "R1-P1-T001")
    with pytest.raises(TaskError, match="写路径冲突"):
        start_task(root, "R1-P1-T002")


def test_role_guard_blocks_cross_role_commands(env, monkeypatch):
    root, _ = env
    workspace_add_project(root, "frontend", "frontend")
    create_task(
        root,
        "前端任务",
        risk="low",
        delivery="frontend",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
    )

    monkeypatch.chdir(root)
    assert main(["task", "start", "R1-P1-T001"]) == 3

    monkeypatch.chdir(root / "frontend")
    assert main(["req", "add", "--title", "越权", "--acceptance", "x"]) == 3
    assert main(["task", "accept", "R1-P1-T001"]) == 3
    assert main(["task", "start", "R1-P1-T001"]) == 0


def test_state_rebuilds_from_roadmap_and_tasks(env):
    root, contract = env
    create_task(root, "任务", risk="low", acceptance=_acceptance())
    state_path = contract / "state" / "current.json"
    state_path.unlink()
    current = state.read_current(contract)
    assert current["roadmap"] == "R1"
    assert current["phase"] == "P1"

    state_path.write_text("{broken", encoding="utf-8")
    current = state.read_current(contract)
    assert current["roadmap"] == "R1"


def test_worker_cannot_read_archive(env):
    root, contract = env
    _set_state(contract)
    (contract / "archive" / "R1").mkdir(parents=True, exist_ok=True)
    (contract / "archive" / "R1" / "INDEX.md").write_text("# old\n", encoding="utf-8")
    with pytest.raises(context.ContextError):
        context.expand(root, "archive/R1/INDEX.md", reason="human_audit", actor="worker")
    with pytest.raises(context.ContextError):
        context.archive_show(root, "R1", reason="human_audit", actor="worker")
    result = context.archive_show(root, "R1", reason="human_audit", actor="manager")
    assert result["bytes"] > 0


def test_packet_digest_and_ledger_actor(env, monkeypatch):
    root, contract = env
    monkeypatch.setenv("MF_ROLE", "manager")
    monkeypatch.setenv("MF_ACTOR", "alice")
    create_task(root, "任务", risk="low", acceptance=_acceptance())
    task = load_task(root, "R1-P1-T001")[1]
    from meta_flow.task import packet_text

    text = packet_text(root, "R1-P1-T001")
    assert "## Read policy" in text
    assert "packet_digest:" in text
    assert (contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / "T001" / "packet.sha256").is_file()
    events = [
        json.loads(line)
        for line in (contract / "state" / "ledger.ndjson").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert events[-1]["actor"] == "alice"
    assert events[-1]["role"] == "manager"
    assert task["status"] == "ready"


def test_verify_pass_does_not_close_bug(env):
    root, _ = env
    from meta_flow import bug

    bug_item = bug.add_bug(root, "问题", severity="major")
    verify.record_verification(
        root,
        layer="implementation",
        scope="检查",
        result="PASS",
        bugs=[bug_item["id"]],
    )
    assert bug.show_bug(root, bug_item["id"])["status"] == "verifying"
    closed = bug.close_bug(root, bug_item["id"], verification="manager 确认")
    assert closed["status"] == "closed"
