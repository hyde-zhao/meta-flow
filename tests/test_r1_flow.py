"""R1 流程重构工具（T006）回归：上下文/guard/归档/maintainer/任务/版本/文档/证据。"""

from __future__ import annotations

import pytest
import yaml

from meta_flow import bug as bug_mod
from meta_flow import context, docmodel, guard, roadmap, roles, task, verify
from meta_flow.install import install_root
from meta_flow.workspace import workspace_add_project, workspace_init


@pytest.fixture()
def r1_env(tmp_path, monkeypatch):
    home = tmp_path / "global"
    monkeypatch.setenv("META_FLOW_HOME", str(home))
    from meta_flow.global_store import bootstrap

    bootstrap()
    root = tmp_path / "demo"
    root.mkdir()
    install_root(root)
    workspace_init(root, "Demo")
    workspace_add_project(root, "frontend", "frontend")
    monkeypatch.setenv("MF_ROLE", "worker")
    return {
        "root": root,
        "contract": root / "demo-contract",
        "frontend": root / "frontend",
    }


def _acceptance():
    return [{"id": "A1", "method": "artifact", "expect": "完成"}]


def _bundle(contract, task_id):
    return contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / f"T{task_id[-3:]}"


def _write_worker_files(contract, task_id, extra=""):
    bundle = _bundle(contract, task_id)
    (bundle / "dev-record.md").write_text("# dev\n实现完成\n" + extra, encoding="utf-8")
    (bundle / "handoff.md").write_text("# handoff\n完成\n" + extra, encoding="utf-8")
    return bundle


def _write_review_files(contract, review_id, verdict):
    bundle = _bundle(contract, review_id)
    (bundle / "review.md").write_text(f"# review\nverdict: {verdict}\n", encoding="utf-8")
    lines = [f"# review handoff\n> verdict: {verdict}"]
    if verdict == "NEEDS_REWORK":
        lines.extend(
            [
                "> rework_scope: in-scope",
                "> rework_summary:",
                ">   reason: 整改项未满足验收",
                ">   risk: 不整改无法验收",
                ">   impact: 交付不达标",
                ">   expectation: 整改后可复审",
                "",
                "## 必须整改项",
                "",
                "| ID | 文件/行 | 要求 | 验收方法 |",
                "|---|---|---|---|",
                "| R1 | src/app.py:1 | 整改 | pytest |",
            ]
        )
    (bundle / "review-handoff.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return bundle


def _create_implement(env, *, risk="medium", review_mode="independent", title="实现"):
    root = env["root"]
    result = task.create_task(
        root,
        title,
        delivery="frontend",
        risk=risk,
        review_mode=review_mode,
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
        estimate={"vu": 2, "effort_hours": 3, "confidence": "medium"},
        verify="pytest tests/test_demo.py::test_ok",
        slice="S1",
    )
    return result


# ---------------------------------------------------------------- C5 expand


def test_segmented_expand_and_read_log(r1_env):
    root, frontend = r1_env["root"], r1_env["frontend"]
    result = task.create_task(
        root,
        "分段读取",
        delivery="frontend",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
    )
    task.start_task(root, result["task"])
    (frontend / "src").mkdir(parents=True, exist_ok=True)
    (frontend / "src" / "big.py").write_text("é" * 120, encoding="utf-8")

    data = context.expand(
        frontend, "src/big.py", reason="packet_missing", actor="worker", start=0, end=40
    )
    assert data["segmented"] is True
    assert data["start"] == 0 and data["end"] == 40
    assert data["text"]

    with pytest.raises(context.ContextError):
        context.expand(
            frontend, "src/big.py", reason="packet_missing", actor="worker", end=10_000
        )
    with pytest.raises(context.ContextError):
        context.expand(
            frontend,
            "src/big.py",
            reason="packet_missing",
            actor="worker",
            start=10,
            end=5,
        )
    with pytest.raises(context.ContextError):
        context.expand(
            frontend,
            "src/big.py",
            reason="packet_missing",
            actor="worker",
            start=0,
            end=100,
            max_bytes=10,
        )
    # UTF-8 边界：把 2 字节字符截成 1 字节时自动回退到合法边界
    boundary = context.expand(
        frontend, "src/big.py", reason="packet_missing", actor="worker", start=0, end=1
    )
    assert boundary["text"] == ""
    log = context.read_log(root)
    assert any(
        item.get("event") == "context.expand" and item.get("segmented") for item in log
    )


def test_guard_redirect_and_readonly_commands():
    assert not guard._has_redirect_write("cat src/a.py 2>&1")
    assert not guard._has_redirect_write("grep x src/a.py 2>/dev/null")
    assert guard._has_redirect_write("echo hi > out.txt")
    assert guard._readonly_mf_command(
        "mf context expand src/a.py --reason packet_missing --start 0 --end 10"
    )
    assert guard._readonly_mf_command(
        "mf archive show R0 --reason human_audit --grant ARC-1"
    )
    assert not guard._readonly_mf_command("echo mf context expand src/a.py")
    assert not guard._readonly_mf_command("cd x && mf archive show R0")
    assert not guard._readonly_mf_command("mf archive show R0 > out.txt")


# ---------------------------------------------------------------- C5.2 maintainer


def test_maintainer_root_and_external_gate(r1_env, monkeypatch):
    root, contract = r1_env["root"], r1_env["contract"]
    requirement = contract / "requirements" / "INDEX.md"
    requirement.parent.mkdir(parents=True, exist_ok=True)
    requirement.write_text("# REQ\n", encoding="utf-8")
    monkeypatch.setenv("MF_ROLE", "maintainer")
    # root：读写 contract/交付/archive 均放行（非阻断审计）
    assert guard.pretool_decision(_payload("Read", root, requirement)) is None
    assert guard.pretool_decision(_payload("Write", root, requirement)) is None
    # 外部动作默认拒绝，需用户 TTY 授权
    push = guard.pretool_decision(_payload("Bash", root, command="git push origin main"))
    assert push is not None
    assert "外部动作" in push["hookSpecificOutput"]["permissionDecisionReason"]
    entry = roles.authorize_external("git push", "发布前推送", cwd=root, tty=True)
    assert entry["approved_by"] == "user"
    assert guard.pretool_decision(_payload("Bash", root, command="git push origin main")) is None
    # 授权文件不得由工具层伪造写入
    forged = guard.pretool_decision(
        _payload(
            "Write", root, path=root / ".meta-flow" / "external-authorizations.yaml"
        )
    )
    assert forged is not None
    # 非 TTY 不能授权
    with pytest.raises(roles.RoleError):
        roles.authorize_external("network", "x", cwd=root, tty=False)


def test_worker_role_not_polluted_by_maintainer(r1_env, monkeypatch):
    root, contract = r1_env["root"], r1_env["contract"]
    requirement = contract / "requirements" / "INDEX.md"
    requirement.parent.mkdir(parents=True, exist_ok=True)
    requirement.write_text("# REQ\n", encoding="utf-8")
    monkeypatch.setenv("MF_ROLE", "worker")
    payload = _payload("Read", root, requirement)
    payload["session_id"] = "s1"
    assert guard.pretool_decision(payload) is not None
    monkeypatch.setenv("MF_ROLE", "maintainer")
    payload2 = _payload("Read", root, requirement)
    payload2["session_id"] = "s1"
    assert guard.pretool_decision(payload2) is None


def _payload(tool, cwd, path=None, command=None):
    data = {"tool_name": tool, "cwd": str(cwd), "tool_input": {}}
    if path is not None:
        data["tool_input"]["file_path"] = str(path)
    if command is not None:
        data["tool_input"]["command"] = command
    return data


# ---------------------------------------------------------------- C5.1 archive


def _setup_archive(contract):
    base = contract / "archive" / "R0"
    (base / "phases" / "P4" / "tasks" / "T048").mkdir(parents=True)
    (base / "INDEX.md").write_text("# archive R0\n", encoding="utf-8")
    (base / "phases" / "P4" / "tasks" / "T048" / "review.md").write_text(
        "# review\n", encoding="utf-8"
    )
    (base / "CLOSE.md").write_text("# close\n", encoding="utf-8")


def test_archive_grant_lifecycle(r1_env):
    root, contract = r1_env["root"], r1_env["contract"]
    _setup_archive(contract)
    with pytest.raises(context.ContextError):
        context.archive_show(root, "R0", reason="human_audit", actor="manager")
    with pytest.raises(context.ContextError):
        context.expand(root, "archive/R0/INDEX.md", reason="human_audit", actor="manager")
    with pytest.raises(context.ContextError):
        context.authorize_archive(
            root,
            role="manager",
            roadmap="R0",
            scope=["**"],
            purpose="human_audit",
            tty=False,
        )
    with pytest.raises(context.ContextError):
        context.authorize_archive(
            root,
            role="worker",
            roadmap="R0",
            scope=["**"],
            purpose="human_audit",
            tty=True,
        )
    grant = context.authorize_archive(
        root,
        role="manager",
        roadmap="R0",
        scope=["phases/P4/tasks/T048/**", "INDEX.md"],
        purpose="human_audit",
        tty=True,
        one_shot=False,
        max_bytes=10000,
        max_files=10,
    )
    shown = context.archive_show(
        root, "R0", reason="human_audit", actor="manager", grant_id=grant["grant_id"]
    )
    assert set(shown["files"]) == {"phases/P4/tasks/T048/review.md"}
    with pytest.raises(context.ContextError):
        context.archive_show(
            root,
            "R0",
            reason="human_audit",
            actor="manager",
            grant_id=grant["grant_id"],
            path="CLOSE.md",
        )
    # 其他角色不能复用 manager grant
    with pytest.raises(context.ContextError):
        context.archive_show(
            root, "R0", reason="human_audit", actor="designer", grant_id=grant["grant_id"]
        )
    exported = context.archive_export(
        root,
        grant_id=grant["grant_id"],
        to="roadmap/R1/inputs/archive-r0",
        actor="manager",
    )
    assert exported["digest"].startswith("sha256:")
    manifest = yaml.safe_load(
        (contract / "roadmap" / "R1" / "inputs" / "archive-r0" / "SOURCES.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert all(item["reference_only"] for item in manifest["files"])
    with pytest.raises(context.ContextError):
        context.archive_export(
            root, grant_id=grant["grant_id"], to="roadmap/R1/not-inputs", actor="manager"
        )
    # maintainer root 免 grant
    data = context.archive_show(
        root, "R0", reason="human_audit", actor="maintainer"
    )
    assert data["bytes"] > 0
    expanded = context.expand(
        root, "archive/R0/INDEX.md", reason="human_audit", actor="maintainer"
    )
    assert "archive R0" in expanded["text"]
    context.revoke_archive(root, grant["grant_id"], tty=True)
    with pytest.raises(context.ContextError):
        context.archive_show(
            root, "R0", reason="human_audit", actor="manager", grant_id=grant["grant_id"]
        )


def test_archive_grant_one_shot_and_limits(r1_env):
    root, contract = r1_env["root"], r1_env["contract"]
    _setup_archive(contract)
    grant = context.authorize_archive(
        root,
        role="manager",
        roadmap="R0",
        scope=["INDEX.md"],
        purpose="human_audit",
        tty=True,
        one_shot=True,
    )
    context.archive_show(
        root, "R0", reason="human_audit", actor="manager", grant_id=grant["grant_id"]
    )
    with pytest.raises(context.ContextError):
        context.archive_show(
            root, "R0", reason="human_audit", actor="manager", grant_id=grant["grant_id"]
        )
    small = context.authorize_archive(
        root,
        role="manager",
        roadmap="R0",
        scope=["phases/P4/tasks/T048/**"],
        purpose="human_audit",
        tty=True,
        max_bytes=1,
    )
    with pytest.raises(context.ContextError):
        context.archive_show(
            root,
            "R0",
            reason="human_audit",
            actor="manager",
            grant_id=small["grant_id"],
        )


# ---------------------------------------------------------------- C3/C3.2/C3.1


def test_review_role_derivation_design_manager(r1_env, monkeypatch):
    root = r1_env["root"]
    monkeypatch.setenv("MF_ROLE", "designer")
    result = task.create_task(
        root,
        "设计任务",
        kind="design",
        risk="low",
        review_mode="independent",
        allowed_paths=["architecture/**"],
        acceptance=_acceptance(),
    )
    review_id = result["review_task"]
    _, review = task.load_task(root, review_id)
    assert review["owner_role"] == "manager"
    assert review["executor_role"] == "manager"
    task.start_task(root, result["task"])
    _write_worker_files(r1_env["contract"], result["task"])
    task.submit_task(root, result["task"])

    monkeypatch.setenv("MF_ROLE", "worker")
    with pytest.raises(task.TaskError):
        task.start_task(root, review_id, owner="reviewer-w")
    monkeypatch.setenv("MF_ROLE", "manager")
    started = task.start_task(root, review_id)
    assert started["review"]["independence"]["reviewer_role"] == "manager"


def test_implementation_review_independence_same_owner_and_session(r1_env):
    root = r1_env["root"]
    result = _create_implement(r1_env, title="独立评审")
    task.start_task(root, result["task"], owner="worker-a")
    _write_worker_files(r1_env["contract"], result["task"])
    task.submit_task(root, result["task"], owner="worker-a")
    with pytest.raises(task.TaskError):
        task.start_task(root, result["review_task"], owner="worker-a")
    started = task.start_task(root, result["review_task"], owner="worker-b")
    assert started["review"]["independence"]["owner"] == "worker-b"


def test_implementation_review_same_session_denied(r1_env, monkeypatch):
    root = r1_env["root"]
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "session-1")
    result = _create_implement(r1_env, title="同会话")
    task.start_task(root, result["task"], owner="worker-a")
    _write_worker_files(r1_env["contract"], result["task"])
    task.submit_task(root, result["task"], owner="worker-a")
    with pytest.raises(task.TaskError):
        task.start_task(root, result["review_task"], owner="worker-b")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "session-2")
    task.start_task(root, result["review_task"], owner="worker-b")


def test_rework_third_round_escalates(r1_env):
    root, contract = r1_env["root"], r1_env["contract"]
    result = _create_implement(r1_env, title="三次返工")
    task_id, review_id = result["task"], result["review_task"]
    task.start_task(root, task_id, owner="worker-a")
    _write_worker_files(contract, task_id)
    task.submit_task(root, task_id, owner="worker-a")
    for round_no in (1, 2, 3):
        task.start_task(root, review_id)
        _write_review_files(contract, review_id, "NEEDS_REWORK")
        task.submit_task(root, review_id)
        _, target = task.load_task(root, task_id)
        assert target["rework_count"] == round_no
        if round_no < 3:
            assert target["status"] == "rework"
            task.rework_task(root, task_id, owner="worker-a")
            _write_worker_files(contract, task_id)
            task.submit_task(root, task_id, owner="worker-a")
        else:
            assert target["status"] == "blocked"
            assert target["next_owner"] == "manager"
            assert target["rework"]["escalated"] is True
    accepted = task.accept_task(root, review_id, verdict="NEEDS_REWORK")
    _, target = task.load_task(root, task_id)
    assert target["status"] == "blocked"
    assert target["rework_count"] == 3
    assert accepted["rework_decision"]["already_escalated"] is True
    ledger = (contract / "state" / "ledger.ndjson").read_text(encoding="utf-8")
    assert '"review.rework.escalate"' in ledger


def test_task_withdraw_and_processed_deny(r1_env):
    root, contract = r1_env["root"], r1_env["contract"]
    result = _create_implement(r1_env, title="撤回")
    task_id, review_id = result["task"], result["review_task"]
    task.start_task(root, task_id, owner="worker-a")
    _write_worker_files(contract, task_id)
    task.submit_task(root, task_id, owner="worker-a")
    data = task.withdraw_task(root, task_id, reason="补充证据", owner="worker-a")
    assert data["status"] == "in_progress"
    assert data["withdraw_count"] == 1
    _, review = task.load_task(root, review_id)
    assert review["status"] == "cancelled"
    # 补充后重新提交，review 恢复 ready
    _write_worker_files(contract, task_id)
    task.submit_task(root, task_id, owner="worker-a")
    _, review = task.load_task(root, review_id)
    assert review["status"] == "ready"
    # 评审已开始后不得 withdraw
    task.start_task(root, review_id)
    with pytest.raises(task.TaskError):
        task.withdraw_task(root, task_id, reason="再补充", owner="worker-a")
    ledger = (contract / "state" / "ledger.ndjson").read_text(encoding="utf-8")
    assert '"task.withdraw"' in ledger and '"review.cancelled"' in ledger


def test_review_dispatch_and_fallback(r1_env):
    root, contract = r1_env["root"], r1_env["contract"]
    result = _create_implement(r1_env, title="派发")
    task_id, review_id = result["task"], result["review_task"]
    task.start_task(root, task_id, owner="worker-a")
    _write_worker_files(contract, task_id)
    task.submit_task(root, task_id, owner="worker-a")
    dispatched = task.dispatch_review(
        root, review_id, owner="reviewer-x", session_id="preview-session"
    )
    assert dispatched["dispatch"]["spawn_state"] == "spawn-requested"
    fallback = task.dispatch_review(
        root, review_id, host="manual", fallback=True, reason="宿主不可用"
    )
    assert fallback["dispatch"]["spawn_state"] == "fallback-manual"
    ledger = (contract / "state" / "ledger.ndjson").read_text(encoding="utf-8")
    assert '"review.spawn"' in ledger and '"orchestration.fallback"' in ledger


def test_submit_blocked_requires_research_after_three_attempts(r1_env):
    root, contract = r1_env["root"], r1_env["contract"]
    result = _create_implement(r1_env, title="研究升级", review_mode="manager")
    task_id = result["task"]
    _, data = task.load_task(root, task_id)
    data["attempt_count"] = 3
    data["attempts"] = [
        {"try": 1, "result": "failed"},
        {"try": 2, "result": "failed"},
        {"try": 3, "result": "failed"},
    ]
    path = contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / f"T{task_id[-3:]}" / "TASK.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    task.start_task(root, task_id, owner="worker-a")
    _write_worker_files(contract, task_id)
    with pytest.raises(task.TaskError):
        task.submit_task(root, task_id, owner="worker-a", blocked=True)
    _write_worker_files(
        contract,
        task_id,
        extra="\n官方文档 RFC 结论\nGitHub issues 讨论\n知名论坛/社区结论\n",
    )
    data = task.submit_task(root, task_id, owner="worker-a", blocked=True)
    assert data["status"] == "blocked"


# ---------------------------------------------------------------- C1.1/C2 version


def test_roadmap_sizing_classify_and_phase_profile(r1_env):
    root, contract = r1_env["root"], r1_env["contract"]
    _create_implement(r1_env, title="VU 任务")
    sizing = roadmap.sizing(root, "R1")
    assert sizing["estimate"]["vu_count"] >= 1
    assert sizing["suggestion"] in {"small", "large", "split"}
    with pytest.raises(roadmap.RoadmapError):
        roadmap.classify(
            root, "R1", flow="program", decided_by="manager", reason="x", tty=True
        )
    with pytest.raises(roadmap.RoadmapError):
        roadmap.classify(
            root, "R1", flow="program", decided_by="user", reason="x", tty=False
        )
    data = roadmap.classify(
        root,
        "R1",
        flow="program",
        decided_by="user",
        reason="R1 program profile",
        tty=True,
    )
    assert data["phase_plan"]["P2"]["mode"] == "merged_into"
    version = yaml.safe_load(
        (contract / "roadmap" / "R1" / "VERSION.yaml").read_text(encoding="utf-8")
    )
    assert version["flow_profile"] == "program"
    view = roadmap.phase_view(root)
    phases = {item["phase"]: item for item in view["phases"]}
    assert phases["P2"]["mode"] == "merged_into"
    assert phases["P1"]["required"] is True
    with pytest.raises(roadmap.RoadmapError):
        roadmap.phase_enter(root, "P2")


def test_task_estimate_verify_validation(r1_env):
    root = r1_env["root"]
    result = _create_implement(r1_env, title="字段校验")
    checked = task.validate_task(root, result["task"])
    assert not any("estimate" in warning for warning in checked["warnings"])
    assert not any("verify" in warning for warning in checked["warnings"])
    with pytest.raises(task.TaskError):
        task.create_task(
            root,
            "坏估计",
            delivery="frontend",
            allowed_paths=["src/**"],
            acceptance=_acceptance(),
            estimate={"vu": 0, "effort_hours": 1},
        )


def test_cli_r1_smoke(r1_env, monkeypatch):
    from meta_flow.cli import main

    monkeypatch.setenv("MF_ROLE", "manager")
    root = str(r1_env["root"])
    assert main(["phase", "show", "--project-dir", root, "--json"]) == 0
    assert main(["roadmap", "sizing", "R1", "--project-dir", root, "--json"]) == 0
    assert main(["archive", "list", "--project-dir", root, "--json"]) == 0
    assert main(["verify", "index", "--project-dir", root, "--json"]) == 0


# ---------------------------------------------------------------- C5.3 BUG


def test_bug_packet_minimal_context(r1_env):
    root = r1_env["root"]
    item = bug_mod.add_bug(
        root,
        "缺陷",
        severity="major",
        flow="verification",
        subproject="frontend",
        steps="1. 复现步骤",
        expected="ok",
        actual="bad",
        environment="linux/python3.12",
    )
    packet = bug_mod.bug_packet(root, item["id"])
    assert packet["flow"] == "verification"
    assert packet["reproduction"] == "1. 复现步骤"
    assert packet["expected"] == "ok" and packet["actual"] == "bad"
    assert packet["related"]["requirements"] == []
    assert packet["fix_scope"]["allowed_paths"] == []


# ---------------------------------------------------------------- 返工 T6-M1..M5


def test_external_action_bypass_forms_denied(r1_env, monkeypatch):
    root = r1_env["root"]
    monkeypatch.setenv("MF_ROLE", "maintainer")
    forms = {
        "git -C . push": "git push",
        "git -c k=v push": "git push",
        "git -C . tag": "git tag",
        "bash -c git push": "git push",
        "sh -c 'git merge main'": "git merge",
        "python -m pip install x": "install",
        "python3 -m pip download x": "install",
        "uvx ruff check": "install",
        "pipx install ruff": "install",
        "nc host 80": "network",
        "telnet host 23": "network",
    }
    for command, action in forms.items():
        assert guard._external_action(command) == action, command
        decision = guard.pretool_decision(_payload("Bash", root, command=command))
        assert decision is not None, command
    # 授权后放行（动作级匹配）
    roles.authorize_external("git push", "推送", cwd=root, tty=True)
    assert guard.pretool_decision(
        _payload("Bash", root, command="git -C . push")
    ) is None
    roles.authorize_external("install", "安装", cwd=root, tty=True)
    assert guard.pretool_decision(
        _payload("Bash", root, command="python -m pip install x")
    ) is None
    roles.authorize_external("network", "网络", cwd=root, tty=True)
    assert guard.pretool_decision(_payload("Bash", root, command="nc host 80")) is None
    # 未授权动作仍拒绝
    assert guard.pretool_decision(
        _payload("Bash", root, command="git clone https://example.com/x.git")
    ) is not None


def test_doctor_process_forward_refs_and_draft_review(r1_env):
    contract = r1_env["contract"]
    result = _create_implement(r1_env, title="过程检查")
    task_id, review_id = result["task"], result["review_task"]
    # forward review / draft review 属正常前置状态，不应误报
    issues = docmodel.process_check(contract)
    assert not any("孤儿引用" in issue for issue in issues)
    assert not any("评审已开始" in issue for issue in issues)
    # submitted review 无 rounds（旧工具）不应误报
    task.start_task(r1_env["root"], task_id, owner="worker-a")
    _write_worker_files(contract, task_id)
    task.submit_task(r1_env["root"], task_id, owner="worker-a")
    task.start_task(r1_env["root"], review_id)
    _write_review_files(contract, review_id, "PASS")
    task.submit_task(r1_env["root"], review_id)
    _, review = task.load_task(r1_env["root"], review_id)
    review.pop("rounds", None)
    review.pop("round", None)
    review["status"] = "submitted"
    path = (
        contract
        / "roadmap"
        / "R1"
        / "phases"
        / "P1"
        / "tasks"
        / f"T{review_id[-3:]}"
        / "TASK.yaml"
    )
    path.write_text(yaml.safe_dump(review, sort_keys=False, allow_unicode=True), encoding="utf-8")
    issues = docmodel.process_check(contract)
    assert not any("rounds" in issue for issue in issues)


def _security_without_marker():
    return {
        "applies": True,
        "threat_model": {
            "assets": ["contract"],
            "attackers": ["worker"],
            "entry_points": ["mf"],
            "trust_boundary": ["guard"],
            "attacker_capabilities": ["shell"],
        },
        "uncovered": ["同用户任意代码"],
        "risk_acceptor": "manager",
        "invariants": [{"id": "INV-1", "text": "不得跨项目读写"}],
        "negative_matrix": [
            {
                "id": "N1",
                "category": "命令首词",
                "command": "echo mf",
                "expected": "deny",
                "evidence": "pytest",
            }
        ],
        "evidence": ["pytest tests/test_r1_flow.py"],
        "fail_closed": True,
        "fail_closed_scope": "静态解析范围",
    }


def test_security_v2_active_missing_marker_fails(r1_env):
    root = r1_env["root"]
    errors = task.task_security_errors(
        {"kind": "implement", "security": _security_without_marker()}
    )
    assert any("安全卡 v2 未完成" in error for error in errors)
    with pytest.raises(task.TaskError):
        task.create_task(
            root,
            "缺 v2 标记",
            delivery="frontend",
            allowed_paths=["src/**"],
            acceptance=_acceptance(),
            security=_security_without_marker(),
        )
    ok = task.task_security_errors(
        {
            "kind": "implement",
            "security": {**_security_without_marker(), "schema": 2, "compat": "v2"},
        }
    )
    assert ok == []


def test_one_shot_grant_export_consumed(r1_env):
    root, contract = r1_env["root"], r1_env["contract"]
    _setup_archive(contract)
    grant = context.authorize_archive(
        root,
        role="manager",
        roadmap="R0",
        scope=["INDEX.md"],
        purpose="human_audit",
        tty=True,
        one_shot=True,
    )
    context.archive_export(
        root,
        grant_id=grant["grant_id"],
        to="roadmap/R1/inputs/one-shot",
        actor="manager",
    )
    with pytest.raises(context.ContextError):
        context.archive_export(
            root,
            grant_id=grant["grant_id"],
            to="roadmap/R1/inputs/one-shot-2",
            actor="manager",
        )
    with pytest.raises(context.ContextError):
        context.archive_show(
            root, "R0", reason="human_audit", actor="manager", grant_id=grant["grant_id"]
        )


def test_maintainer_export_without_grant(r1_env):
    root, contract = r1_env["root"], r1_env["contract"]
    _setup_archive(contract)
    data = context.archive_export(
        root,
        roadmap="R0",
        to="roadmap/R1/inputs/maintainer-export",
        actor="maintainer",
    )
    assert data["grant_id"] is None
    manifest = yaml.safe_load(
        (
            contract
            / "roadmap"
            / "R1"
            / "inputs"
            / "maintainer-export"
            / "SOURCES.yaml"
        ).read_text(encoding="utf-8")
    )
    assert manifest["grant_id"] is None


def test_review_verdict_schema_installed(r1_env, monkeypatch):
    import os
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    assert (repo / "templates" / "schemas" / "review-verdict.json").is_file()
    home = Path(os.environ["META_FLOW_HOME"])
    assert (home / "schemas" / "review-verdict.json").is_file()
    result = _create_implement(r1_env, title="派发 schema")
    root = r1_env["root"]
    task.start_task(root, result["task"], owner="worker-a")
    _write_worker_files(r1_env["contract"], result["task"])
    task.submit_task(root, result["task"], owner="worker-a")
    dispatched = task.dispatch_review(
        root, result["review_task"], owner="reviewer-x", session_id="schema-session"
    )
    assert dispatched["dispatch"]["verdict_schema"].endswith(
        "schemas/review-verdict.json"
    )


def test_docmodel_docs_and_process_checks(r1_env):
    contract = r1_env["contract"]
    (contract / "roadmap" / "R1" / "phases" / "P2" / "specs").mkdir(
        parents=True, exist_ok=True
    )
    spec = contract / "roadmap" / "R1" / "phases" / "P2" / "specs" / "SPEC-R1-DEMO.md"
    spec.write_text("# SPEC demo\n", encoding="utf-8")
    issues = docmodel.docs_check(contract)
    assert any("front matter" in issue for issue in issues)
    spec.write_text(
        "---\nid: SPEC-R1-DEMO\ntype: spec\nstatus: draft\nowner: designer\n"
        "roadmap: R1\nphase: P2\nupdated_at: 2026-11-28\nrefs: []\n---\n\n# SPEC demo\n",
        encoding="utf-8",
    )
    issues = docmodel.docs_check(contract)
    assert not any("SPEC-R1-DEMO" in issue and "front matter" in issue for issue in issues)
    # 入口行数
    (contract / "CLAUDE.md").write_text("\n".join(["# x"] * 101), encoding="utf-8")
    assert any("超过 100 行" in issue for issue in docmodel.docs_check(contract))

    result = _create_implement(r1_env, title="过程记录")
    bundle = _bundle(contract, result["task"])
    (bundle / "handoff.md").write_text(
        "\n".join(["# handoff"] * 70), encoding="utf-8"
    )
    process_issues = docmodel.process_check(contract)
    assert any("handoff.md 超过篇幅预算" in issue for issue in process_issues)


def test_verify_evidence_index_and_reuse(r1_env):
    root = r1_env["root"]
    first = verify.record_verification(
        root,
        layer="implementation",
        scope="切片",
        result="PASS",
        command="pytest tests/test_demo.py::test_ok",
        result_digest="sha256:abc",
    )
    assert first["items"][0]["result_digest"] == "sha256:abc"
    without_digest = verify.record_verification(
        root, layer="implementation", scope="无 digest", result="PASS"
    )
    index = verify.evidence_index(root)
    assert index["summary"]["total"] == 2
    assert any(without_digest["id"] in issue for issue in index["evidence_debt"])
    reused = verify.record_verification(
        root,
        layer="implementation",
        scope="复用",
        result="PASS",
        command="pytest tests/test_demo.py::test_ok",
        reuse_of=first["id"],
    )
    assert reused["reuse_of"] == first["id"]
    with pytest.raises(verify.VerifyError):
        verify.record_verification(
            root,
            layer="implementation",
            scope="漂移",
            result="PASS",
            command="pytest tests/test_other.py",
            reuse_of=first["id"],
        )
    with pytest.raises(verify.VerifyError):
        verify.record_verification(
            root, layer="implementation", scope="失败无证据", result="BLOCKED"
        )
