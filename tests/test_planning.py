"""规划、质量与控制闭环测试。"""

from __future__ import annotations

import json

import pytest

from meta_flow import bug, context, knowledge, req, roadmap, state, verify
from meta_flow.global_store import bootstrap
from meta_flow.install import install_root
from meta_flow.task import (
    TaskError,
    accept_task,
    create_task,
    graph,
    next_tasks,
    plan_tasks,
    release_task,
    start_task,
    submit_task,
)
from meta_flow.workspace import workspace_init


@pytest.fixture()
def project_env(tmp_path, monkeypatch):
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


def _move_to_p5(contract):
    current = state.read_current(contract)
    current.update({"phase": "P5", "phase_status": "active"})
    state.write_current(contract, current)


def test_requirement_lifecycle_and_trace(project_env):
    root, contract = project_env
    item = req.add_requirement(
        root,
        "用户登录",
        priority="must",
        acceptance=["成功登录"],
        roadmap="R1",
    )
    assert item["id"] == "REQ-0001"
    assert (contract / "requirements" / "REQ-0001.md").is_file()

    req.update_requirement(root, "REQ-0001", status="accepted")
    items = req.list_requirements(root, status="accepted")
    assert items[0]["id"] == "REQ-0001"

    create_task(
        root,
        "实现登录",
        risk="low",
        acceptance=_acceptance(),
        inputs={"requirements": ["REQ-0001"]},
    )
    traced = req.trace(root, "REQ-0001")
    assert traced["REQ-0001"]["tasks"][0]["id"] == "R1-P1-T001"
    req.trace(root)
    assert (contract / "requirements" / "TRACE.md").is_file()
    assert req.validate_all(root) == []

    with pytest.raises(req.ReqError):
        req.add_requirement(root, "无验收", acceptance=[])


def test_roadmap_phase_close_and_archive(project_env):
    root, contract = project_env
    planned = roadmap.plan(
        root,
        "R2",
        title="v2",
        version_target="2.0.0",
        goal="第二版",
    )
    assert planned["created"] is True
    assert (contract / "roadmap" / "R2" / "PLAN.md").is_file()

    entered = roadmap.phase_enter(root, "P2")
    assert entered["phase"] == "P2"
    assert state.read_current(contract)["phase"] == "P2"
    report = roadmap.phase_review(root)
    assert (contract / "roadmap" / "R1" / "phases" / "P2" / "REPORT.md").is_file()
    assert "阶段报告" in report["text"]

    with pytest.raises(roadmap.RoadmapError):
        roadmap.phase_exit(root)

    exited = roadmap.phase_exit(root, approved_by="user")
    assert exited["phase"] == "P2"
    assert exited["next"] == "P3"
    assert (contract / "roadmap" / "R1" / "phases" / "P2" / "HANDOFF-TO-P3.md").is_file()

    closed = roadmap.close(root, "R1", force=True)
    assert closed["next"] == "R2"
    assert (contract / "archive" / "R1" / "CLOSE.md").is_file()
    assert (contract / "archive" / "R1" / "LESSONS-R1.md").is_file()
    assert state.read_current(contract)["roadmap"] == "R2"

    archives = context.archive_list(root)
    assert archives[0]["roadmap"] == "R1"
    shown = context.archive_show(root, "R1", reason="human_audit")
    assert shown["index"]
    log = context.read_log(root)
    assert any(item.get("event") == "archive.show" for item in log)


def test_bug_lifecycle(project_env):
    root, contract = project_env
    item = bug.add_bug(
        root,
        "登录报错",
        severity="critical",
        task="R1-P1-T001",
        related_reqs=["REQ-0001"],
    )
    assert item["id"] == "BUG-0001"
    assert item["status"] == "open"
    assert bug.open_blockers(root)[0]["id"] == "BUG-0001"

    with pytest.raises(bug.BugError):
        bug.close_bug(root, "BUG-0001", verification="未修复")

    bug.update_bug(root, "BUG-0001", status="fixed", fix_task="R1-P1-T001")
    closed = bug.close_bug(root, "BUG-0001", verification="回归通过")
    assert closed["status"] == "closed"
    assert bug.open_blockers(root) == []


def test_knowledge_render_and_packet(project_env):
    root, contract = project_env
    term = knowledge.add_knowledge(root, "term", "契约库=项目公共规范", context="初始化")
    lesson = knowledge.add_knowledge(root, "lesson", "先写验收再实现")
    assert term["id"] == "TERM-001"
    assert lesson["id"] == "LESSON-001"
    assert "契约库" in (contract / "knowledge" / "KNOWLEDGE.md").read_text(encoding="utf-8")
    lines = knowledge.packet_lines(contract)
    assert any("TERM-001" in line for line in lines)

    create_task(root, "实现登录", risk="low", acceptance=_acceptance())
    from meta_flow.task import packet_text

    packet = packet_text(root, "R1-P1-T001")
    assert "Project knowledge" in packet
    assert "TERM-001" in packet


def test_verify_and_release_freeze(project_env):
    root, contract = project_env
    _move_to_p5(contract)
    req.add_requirement(root, "登录", acceptance=["成功登录"])
    req.update_requirement(root, "REQ-0001", status="verified")
    bug.add_bug(root, "小问题", severity="minor")

    with pytest.raises(verify.VerifyError):
        verify.record_verification(
            root,
            layer="implementation",
            scope="登录",
            result="FAIL",
        )

    item = verify.record_verification(
        root,
        layer="implementation",
        scope="登录",
        result="PASS",
        requirement_refs=["REQ-0001"],
    )
    assert item["id"] == "VR-0001"
    assert item["roadmap"] == "R1"

    with pytest.raises(verify.VerifyError):
        verify.release_freeze(root, version="2.0.0")

    result = verify.release_freeze(root)
    assert result["version"] == "1.0.0"
    assert result["published"] is False
    manifest = verify.show_release(root)
    assert manifest["status"] == "frozen"
    assert manifest["published"] is False
    assert (contract / "release" / "RELEASE-1.0.0.yaml").is_file()

    closed = roadmap.close(root, "R1")
    assert closed["closed"] is True
    assert (contract / "archive" / "R1" / "CLOSE.md").is_file()
    assert (contract / "archive" / "R1" / "verification" / "VR-0001.yaml").is_file()
    assert (contract / "archive" / "R1" / "bugs" / "BUG-0001.yaml").is_file()


def test_task_orchestration_and_leases(project_env):
    root, _ = project_env
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
        "后续",
        risk="low",
        acceptance=_acceptance(),
        wave="W2",
        depends_on=["R1-P1-T001"],
        allowed_paths=["src/**"],
    )
    data = plan_tasks(root)
    assert [item["id"] for item in data["ready"]] == ["R1-P1-T001"]
    assert data["blocked"][0]["id"] == "R1-P1-T002"
    assert next_tasks(root)[0]["id"] == "R1-P1-T001"
    assert len(graph(root)["edges"]) == 1

    start_task(root, "R1-P1-T001")
    with pytest.raises(TaskError):
        start_task(root, "R1-P1-T001")
    with pytest.raises(TaskError):
        release_task(root, "R1-P1-T001")
    released = release_task(root, "R1-P1-T001", force=True)
    assert released["status"] == "ready"

    start_task(root, "R1-P1-T001")
    contract = project_env[1]
    bundle = contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / "T001"
    (bundle / "dev-record.md").write_text("# dev\n", encoding="utf-8")
    (bundle / "handoff.md").write_text("# handoff\n", encoding="utf-8")
    submit_task(root, "R1-P1-T001")
    accept_task(root, "R1-P1-T001")
    assert next_tasks(root)[0]["id"] == "R1-P1-T002"


def test_context_expand_requires_reason(project_env):
    root, contract = project_env
    with pytest.raises(context.ContextError):
        context.expand(root, "requirements/REQ-0001.md", reason="because")
    with pytest.raises(context.ContextError):
        context.expand(root, "../outside.txt", reason="human_audit")
    result = context.expand(root, "roadmap/ROADMAP.yaml", reason="human_audit")
    assert "roadmaps" in result["text"]
    log = context.read_log(root)
    assert log[0]["event"] == "context.expand"
    assert log[0]["reason"] == "human_audit"
    assert json.loads(json.dumps(log[0]))["allowed"] is True
