"""规划、质量与控制闭环测试。"""

from __future__ import annotations

import json

import pytest
import yaml

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
    reject_task,
    release_task,
    rework_task,
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


def _write_review(contract, review_id, verdict, scope, requires):
    bundle = contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / f"T{review_id[-3:]}"
    (bundle / "review.md").write_text(f"# review\nverdict: {verdict}\n", encoding="utf-8")
    (bundle / "review-handoff.md").write_text(
        "\n".join(
            [
                "# review handoff",
                f"> verdict: {verdict}",
                f"> rework_scope: {scope}",
                f"> rework_requires: {requires}",
                "> rework_summary: {reason: 验收未满足, risk: 返工风险, "
                "impact: 交付不达标, expectation: 整改后达标}",
                "",
                "## 必须整改项",
                "",
                "| ID | 文件/行 | 要求 | 验收方法 |",
                "|---|---|---|---|",
                "| R1 | src/a.py:1 | 整改 | pytest |",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _move_to_p5(contract):
    """把状态推到 P5 已退出，覆盖 roadmap.close 门。

    新阶段策略下 P4/P5 的修复/补丁也可冻结（矩阵见 test_release.py），
    这里保留 P5 退出路径用于 close 联调。
    """
    current = state.read_current(contract)
    current.update(
        {
            "phase": "P5",
            "phase_status": "exited",
            "last_phase_gate": {
                "roadmap": current.get("roadmap", "R1"),
                "phase": "P5",
                "next_phase": None,
                "approved_by": "user",
                "note": "test gate",
                "at": "2026-01-01T00:00:00+00:00",
            },
        }
    )
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

    with pytest.raises(roadmap.RoadmapError):
        roadmap.phase_enter(root, "P2")

    first = roadmap.phase_exit(root, approved_by="user", force=True)
    assert first["phase"] == "P1"
    assert state.read_current(contract)["phase_status"] == "exited"
    entered = roadmap.phase_enter(root, "P2")
    assert entered["phase"] == "P2"
    assert state.read_current(contract)["phase"] == "P2"
    report = roadmap.phase_review(root)
    assert (contract / "roadmap" / "R1" / "phases" / "P2" / "REPORT.md").is_file()
    assert "阶段报告" in report["text"]

    with pytest.raises(roadmap.RoadmapError):
        roadmap.phase_exit(root)

    exited = roadmap.phase_exit(root, approved_by="user", force=True)
    assert exited["phase"] == "P2"
    assert exited["next"] == "P3"
    assert (contract / "roadmap" / "R1" / "phases" / "P2" / "HANDOFF-TO-P3.md").is_file()

    roadmap.phase_enter(root, "P3")
    roadmap.phase_exit(root)
    roadmap.phase_enter(root, "P4")
    roadmap.phase_exit(root, approved_by="user", force=True)
    roadmap.phase_enter(root, "P5")
    roadmap.phase_exit(root, approved_by="user")
    assert state.read_current(contract)["phase_status"] == "exited"

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
    assert manifest["stage"] == {"phase": "P5", "phase_status": "exited"}
    assert (contract / "release" / "RELEASE-1.0.0.yaml").is_file()

    closed = roadmap.close(root, "R1")
    assert closed["closed"] is True
    assert (contract / "archive" / "R1" / "CLOSE.md").is_file()
    assert (contract / "archive" / "R1" / "verification" / "VR-0001.yaml").is_file()
    assert (contract / "archive" / "R1" / "bugs" / "BUG-0001.yaml").is_file()
    assert (contract / "archive" / "R1" / "release" / "RELEASE-1.0.0.yaml").is_file()
    assert verify.show_release(root)["roadmap"] == "R1"
    from meta_flow.workspace import doctor

    assert doctor(root) == []


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


def test_rework_state_next_owner_and_execute(project_env):
    root, contract = project_env
    result = create_task(
        root, "返工状态", risk="medium", allowed_paths=["src/**"], acceptance=_acceptance()
    )
    task_id, review_id = result["task"], result["review_task"]
    start_task(root, task_id)
    bundle = contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / "T001"
    (bundle / "dev-record.md").write_text("# dev\n完成\n", encoding="utf-8")
    (bundle / "handoff.md").write_text("# handoff\n完成\n", encoding="utf-8")
    submit_task(root, task_id)
    start_task(root, review_id)
    _write_review(contract, review_id, "NEEDS_REWORK", "in-scope", "none")
    submit_task(root, review_id)

    accepted = accept_task(root, review_id, verdict="NEEDS_REWORK")
    assert accepted["rework_decision"]["auto"] is True
    current = state.refresh_current(contract)
    assert task_id in current["rework_tasks"]
    assert current["next_action"]["type"] == "execute_rework"
    assert current["next_action"]["task"] == task_id
    assert "mf task rework" in current["next_action"]["text"]
    assert next_tasks(root)[0]["id"] == task_id

    rework_task(root, task_id)
    current = state.refresh_current(contract)
    assert current["next_action"]["type"] == "follow_up_task"
    assert current["next_action"]["task"] == task_id


def test_rework_decision_state_requires_manager(project_env):
    root, contract = project_env
    result = create_task(
        root, "范围外返工", risk="high", allowed_paths=["src/**"], acceptance=_acceptance()
    )
    task_id, review_id = result["task"], result["review_task"]
    start_task(root, task_id)
    bundle = contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / "T001"
    (bundle / "dev-record.md").write_text("# dev\n完成\n", encoding="utf-8")
    (bundle / "handoff.md").write_text("# handoff\n完成\n", encoding="utf-8")
    submit_task(root, task_id)
    start_task(root, review_id)
    _write_review(contract, review_id, "NEEDS_REWORK", "out-of-scope", "none")
    submit_task(root, review_id)

    accepted = accept_task(root, review_id, verdict="NEEDS_REWORK")
    assert accepted["rework_decision"]["auto"] is False
    current = state.refresh_current(contract)
    assert current["next_action"]["type"] == "rework_decision"
    assert current["next_action"]["task"] == task_id
    assert current["next_action"]["review_task"] == review_id


def test_rework_resubmit_state_resets_review_stage(project_env):
    root, contract = project_env
    result = create_task(
        root, "复审状态", risk="medium", allowed_paths=["src/**"], acceptance=_acceptance()
    )
    task_id, review_id = result["task"], result["review_task"]
    start_task(root, task_id)
    bundle = contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / "T001"
    (bundle / "dev-record.md").write_text("# dev\n完成\n", encoding="utf-8")
    (bundle / "handoff.md").write_text("# handoff\n完成\n", encoding="utf-8")
    submit_task(root, task_id)
    start_task(root, review_id)
    _write_review(contract, review_id, "NEEDS_REWORK", "in-scope", "none")
    submit_task(root, review_id)
    accept_task(root, review_id, verdict="NEEDS_REWORK")

    rework_task(root, task_id)
    (bundle / "dev-record.md").write_text("# dev\n返工完成\n", encoding="utf-8")
    (bundle / "handoff.md").write_text("# handoff\n返工完成\n", encoding="utf-8")
    submit_task(root, task_id)

    current = state.refresh_current(contract)
    assert current["next_action"]["type"] == "review"
    assert current["next_action"]["task"] == review_id
    detail = next(item for item in current["submitted_details"] if item["id"] == task_id)
    assert detail["review_status"] == "ready"
    assert detail["review_verdict"] is None
    assert task_id not in current["rework_tasks"]


def test_state_rework_flags_follow_review_current_state(project_env):
    root, contract = project_env
    result = create_task(
        root, "R3 状态", risk="medium", allowed_paths=["src/**"], acceptance=_acceptance()
    )
    task_id, review_id = result["task"], result["review_task"]
    start_task(root, task_id)
    bundle = contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / "T001"
    (bundle / "dev-record.md").write_text("# dev\n完成\n", encoding="utf-8")
    (bundle / "handoff.md").write_text("# handoff\n完成\n", encoding="utf-8")
    submit_task(root, task_id)
    start_task(root, review_id)
    _write_review(contract, review_id, "NEEDS_REWORK", "in-scope", "none")
    submit_task(root, review_id)

    # review submitted NEEDS_REWORK + manager 先 reject：可返工任务应被识别
    reject_task(root, task_id, "manager 先退回")
    current = state.refresh_current(contract)
    assert task_id in current["rework_tasks"]
    assert current["next_action"]["type"] == "execute_rework"
    assert current["next_action"]["task"] == task_id

    # review 被重置 ready 后旧 verdict 失效：state 指向 start 恢复而非 execute_rework
    review_yaml = (
        contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / f"T{review_id[-3:]}"
        / "TASK.yaml"
    )
    review_data = yaml.safe_load(review_yaml.read_text(encoding="utf-8"))
    review_data["status"] = "ready"
    review_data["review_verdict"] = None
    review_yaml.write_text(
        yaml.safe_dump(review_data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    current = state.refresh_current(contract)
    assert task_id not in current["rework_tasks"]
    assert task_id in current["stale_rework_tasks"]
    assert current["next_action"]["type"] == "recover_rework"
    assert current["next_action"]["task"] == task_id
    assert "mf task start" in current["next_action"]["text"]


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


def test_release_freeze_uses_declared_version_mapping(tmp_path, monkeypatch):
    home = tmp_path / "global"
    monkeypatch.setenv("META_FLOW_HOME", str(home))
    bootstrap()
    root = tmp_path / "legacy"
    root.mkdir()
    install_root(root)
    workspace_init(root, "Legacy", roadmap="R0", phase="P5", version="1.0.0")
    contract = root / "legacy-contract"
    _move_to_p5(contract)

    result = verify.release_freeze(root)
    assert result["version"] == "1.0.0"
    manifest = yaml.safe_load(
        (contract / "release" / "RELEASE-1.0.0.yaml").read_text(encoding="utf-8")
    )
    assert "override" not in manifest
    assert manifest["stage"] == {"phase": "P5", "phase_status": "exited"}

    with pytest.raises(verify.VerifyError, match="MAJOR"):
        verify.release_freeze(root, version="2.0.0")
    with pytest.raises(verify.VerifyError, match="--reason"):
        verify.release_freeze(root, version="2.0.0", force=True)

    forced = verify.release_freeze(
        root,
        version="2.0.0",
        force=True,
        reason="用户批准的例外",
        approved_by="product-owner",
    )
    assert forced["version"] == "2.0.0"
    manifest = yaml.safe_load(
        (contract / "release" / "RELEASE-2.0.0.yaml").read_text(encoding="utf-8")
    )
    assert manifest["override"]["reason"] == "用户批准的例外"
    assert manifest["override"]["approved_by"] == "product-owner"
    assert manifest["override"]["version"] == "2.0.0"


def test_req_trace_excludes_archive_dedupes_and_filters_specs(project_env):
    root, contract = project_env
    req.add_requirement(root, "登录", priority="must", acceptance=["成功登录"], roadmap="R1")
    create_task(
        root,
        "实现登录",
        risk="low",
        acceptance=_acceptance(),
        inputs={"requirements": ["REQ-0001"]},
    )

    archive_task = contract / "archive" / "R0" / "phases" / "P4" / "tasks" / "T001"
    archive_task.mkdir(parents=True)
    (archive_task / "TASK.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "R0-P4-T001",
                "status": "accepted",
                "inputs": {"requirements": ["REQ-0001"]},
                "risk": {"level": "low"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (contract / "specs" / "INDEX.md").write_text("REQ-0001 索引\n", encoding="utf-8")
    (contract / "specs" / "SPEC-001.md").write_text("REQ-0001 规格\n", encoding="utf-8")
    bugs_dir = contract / "bugs"
    (bugs_dir / "BUG-0001.yaml").write_text(
        yaml.safe_dump(
            {"id": "BUG-0001", "status": "open", "severity": "major", "related_reqs": ["REQ-0001"]},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    archive_bugs = contract / "archive" / "R0" / "bugs"
    archive_bugs.mkdir(parents=True)
    (archive_bugs / "BUG-0001.yaml").write_text(
        yaml.safe_dump(
            {"id": "BUG-0001", "status": "closed", "severity": "major", "related_reqs": ["REQ-0001"]},
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    traced = req.trace(root, roadmap="R1")["REQ-0001"]
    assert [item["id"] for item in traced["tasks"]] == ["R1-P1-T001"]
    assert traced["specs"] == ["specs/SPEC-001.md"]
    assert [item["id"] for item in traced["bugs"]] == ["BUG-0001"]

    all_traced = req.trace(root, roadmap="R1", include_archive=True)["REQ-0001"]
    assert {item["id"] for item in all_traced["tasks"]} == {"R1-P1-T001", "R0-P4-T001"}
    assert [item["id"] for item in all_traced["bugs"]] == ["BUG-0001"]
