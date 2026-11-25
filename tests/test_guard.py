"""PreToolUse 守卫与热/冷区读取测试。"""

from __future__ import annotations

import json

import pytest

from meta_flow import context, guard, knowledge, state
from meta_flow.global_store import bootstrap
from meta_flow.install import install_root, uninstall_claude
from meta_flow.task import create_task, start_task
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
    sub = root / "frontend"
    workspace_add_project(root, "frontend", "frontend")
    return root, root / "demo-contract", sub


def _acceptance():
    return [{"id": "A1", "method": "artifact", "expect": "完成"}]


def _task_bundle(contract, task_id):
    return contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / f"T{task_id[-3:]}"


def _payload(tool, cwd, path):
    return {"tool_name": tool, "cwd": str(cwd), "tool_input": {"file_path": str(path)}}


def test_hook_installed_and_removed(env):
    root, contract, _ = env
    settings = json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8"))
    entries = settings["hooks"]["PreToolUse"]
    assert any(
        item.get("command") == guard.HOOK_COMMAND
        for entry in entries
        for item in entry.get("hooks") or []
    )
    uninstall_claude(root)
    settings_path = root / ".claude" / "settings.json"
    if settings_path.is_file():
        restored = json.loads(settings_path.read_text(encoding="utf-8"))
        assert "hooks" not in restored


def test_manager_upgrades_worker_hook(env, monkeypatch):
    from meta_flow.cli import main

    root, _, sub = env
    monkeypatch.chdir(root)
    assert main(["upgrade", "--project-dir", str(sub)]) == 0
    settings = json.loads((sub / ".claude" / "settings.json").read_text(encoding="utf-8"))
    commands = [
        item.get("command")
        for entry in settings["hooks"]["PreToolUse"]
        for item in entry.get("hooks") or []
    ]
    assert guard.HOOK_COMMAND in commands


def test_guard_manager_archive_and_delivery_source(env):
    root, contract, sub = env
    archive_file = contract / "archive" / "R1" / "INDEX.md"
    archive_file.parent.mkdir(parents=True, exist_ok=True)
    archive_file.write_text("# archive\n", encoding="utf-8")
    decision = guard.pretool_decision(_payload("Read", root, archive_file))
    assert decision and decision["hookSpecificOutput"]["permissionDecision"] == "deny"

    assert guard.pretool_decision(_payload("Read", root, contract / "requirements" / "INDEX.md")) is None
    source = sub / "src" / "main.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("print('ok')\n", encoding="utf-8")
    decision = guard.pretool_decision(_payload("Read", root, source))
    assert decision and "交付库源码" in decision["hookSpecificOutput"]["permissionDecisionReason"]


def test_guard_mf_role_overrides_directory_role(env, monkeypatch):
    root, contract, _ = env
    requirement = contract / "requirements" / "INDEX.md"
    # 目录推导为 manager：可读需求
    assert guard.pretool_decision(_payload("Read", root, requirement)) is None

    # 显式 MF_ROLE=maintainer 优先：maintainer 不读项目契约内容
    monkeypatch.setenv("MF_ROLE", "maintainer")
    decision = guard.pretool_decision(_payload("Read", root, requirement))
    assert decision is not None
    assert "maintainer" in decision["hookSpecificOutput"]["permissionDecisionReason"]


def test_guard_worker_scope(env):
    root, contract, sub = env
    create_task(
        root,
        "前端任务",
        risk="low",
        delivery="frontend",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
    )
    create_task(
        root,
        "其他任务",
        risk="low",
        delivery="frontend",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
    )
    start_task(sub, "R1-P1-T001")
    own = _task_bundle(contract, "R1-P1-T001") / "dev-record.md"
    own.write_text("# dev\n", encoding="utf-8")
    other = _task_bundle(contract, "R1-P1-T002") / "dev-record.md"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text("# other\n", encoding="utf-8")

    assert guard.pretool_decision(_payload("Read", sub, own)) is None
    decision = guard.pretool_decision(_payload("Read", sub, other))
    assert decision and "bundle" in decision["hookSpecificOutput"]["permissionDecisionReason"]

    assert guard.pretool_decision(_payload("Write", sub, own)) is None
    decision = guard.pretool_decision(_payload("Read", sub, contract / "requirements" / "INDEX.md"))
    assert decision is not None

    assert guard.pretool_decision(_payload("Write", sub, sub / "src" / "main.py")) is None
    decision = guard.pretool_decision(_payload("Write", sub, sub / "outside.txt"))
    assert decision and "allowed_paths" in decision["hookSpecificOutput"]["permissionDecisionReason"]


def test_hot_context_budget_and_previous_handoff(env):
    root, contract, _ = env
    data = context.hot_files(root)
    assert data["total_bytes"] >= 0
    assert data["budget"]["bytes"] > 0
    assert data["within_budget"] is True

    big = contract / "requirements" / "BIG.md"
    big.write_text("x" * (140 * 1024), encoding="utf-8")
    with pytest.raises(context.ContextError, match="读预算"):
        context.expand(root, "requirements/BIG.md", reason="human_audit", actor="manager")


def test_knowledge_hot_and_lessons_split(env):
    root, contract, _ = env
    knowledge.add_knowledge(root, "term", "契约库=共享真相")
    knowledge.add_knowledge(root, "lesson", "旧经验不应进入热区")
    hot = (contract / "knowledge" / "KNOWLEDGE.md").read_text(encoding="utf-8")
    lessons = (contract / "knowledge" / "LESSONS.md").read_text(encoding="utf-8")
    assert "契约库" in hot
    assert "旧经验" not in hot
    assert "旧经验" in lessons


def test_state_truncation_is_audited(env):
    _, contract, _ = env
    data = state.read_current(contract)
    data["active_tasks"] = [f"R1-P1-T{index:03d}" for index in range(200)]
    data["active_leases"] = [{"task": item} for item in data["active_tasks"]]
    written = state.write_current(contract, data)
    assert written.get("truncated") is True
    ledger = (contract / "state" / "ledger.ndjson").read_text(encoding="utf-8")
    assert "state.truncate" in ledger
    assert (contract / "state" / "current.json").stat().st_size <= state.MAX_STATE_BYTES


def test_tail_lines_reads_last_records(env):
    _, contract, _ = env
    path = contract / "state" / "ledger.ndjson"
    path.write_text(
        "\n".join(json.dumps({"n": index}) for index in range(1000)) + "\n",
        encoding="utf-8",
    )
    lines = state.tail_lines(path, 5)
    assert len(lines) == 5
    assert json.loads(lines[-1])["n"] == 999
