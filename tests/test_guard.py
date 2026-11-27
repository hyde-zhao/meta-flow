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
    # BUG-0014/R7：hook matcher 覆盖 Bash
    assert any(
        item.get("command") == guard.HOOK_COMMAND and "Bash" in str(entry.get("matcher"))
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
    # 140KB 超过热区预算，但 expand --reason 可用于受控补读并写 READ-LOG
    expanded = context.expand(root, "requirements/BIG.md", reason="human_audit", actor="manager")
    assert expanded["bytes"] == 140 * 1024
    assert "context.expand" in (contract / "state" / "READ-LOG.ndjson").read_text(encoding="utf-8")

    huge = contract / "requirements" / "HUGE.md"
    huge.write_text("x" * (300 * 1024), encoding="utf-8")
    with pytest.raises(context.ContextError, match="expand 上限"):
        context.expand(root, "requirements/HUGE.md", reason="human_audit", actor="manager")


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


def test_guard_worker_without_delivery_root_requires_binding(env, monkeypatch):
    root, contract, sub = env
    create_task(
        root,
        "前端任务",
        risk="low",
        delivery="frontend",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
    )
    start_task(sub, "R1-P1-T001")
    bundle = _task_bundle(contract, "R1-P1-T001") / "dev-record.md"
    bundle.write_text("# dev\n", encoding="utf-8")
    source = sub / "src" / "main.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("print('ok')\n", encoding="utf-8")

    monkeypatch.setenv("MF_ROLE", "worker")
    # cwd 为 workspace 根：无交付根绑定，拒绝任务包读取
    decision = guard.pretool_decision(_payload("Read", root, bundle))
    assert decision is not None
    reason = decision["hookSpecificOutput"]["permissionDecisionReason"]
    assert "交付根绑定" in reason or "--project-dir" in reason

    # guard 不按目标路径猜测交付库：交付库文件同样要求从交付库运行
    decision = guard.pretool_decision(_payload("Read", root, source))
    assert decision is not None
    assert "交付根绑定" in decision["hookSpecificOutput"]["permissionDecisionReason"]

    # 从交付库目录运行时正常放行
    monkeypatch.chdir(sub)
    assert guard.pretool_decision(_payload("Read", sub, source)) is None


def test_worker_context_expand_scoped(env):
    root, contract, sub = env
    create_task(
        root,
        "前端任务",
        risk="low",
        delivery="frontend",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
    )
    start_task(sub, "R1-P1-T001")
    bundle = _task_bundle(contract, "R1-P1-T001")
    (bundle / "evidence").mkdir(parents=True, exist_ok=True)
    large = bundle / "evidence" / "large.log"
    large.write_text("x" * (70 * 1024), encoding="utf-8")
    expanded = context.expand(
        sub, str(large), reason="packet_missing", actor="worker"
    )
    assert expanded["bytes"] == 70 * 1024

    (sub / "src").mkdir(parents=True, exist_ok=True)
    source = sub / "src" / "big.py"
    source.write_text("x" * (70 * 1024), encoding="utf-8")
    expanded = context.expand(sub, "src/big.py", reason="packet_missing", actor="worker")
    assert expanded["bytes"] == 70 * 1024

    with pytest.raises(context.ContextError, match="任务 bundle"):
        context.expand(sub, "requirements/INDEX.md", reason="packet_missing", actor="worker")
    (sub / "docs").mkdir(parents=True, exist_ok=True)
    (sub / "docs" / "other.md").write_text("x\n", encoding="utf-8")
    with pytest.raises(context.ContextError, match="allowed_paths"):
        context.expand(sub, "docs/other.md", reason="packet_missing", actor="worker")
    log = (contract / "state" / "READ-LOG.ndjson").read_text(encoding="utf-8")
    assert "context.expand" in log


def test_guard_review_task_reads_target_bundle_only(env, monkeypatch):
    root, contract, sub = env
    result = create_task(
        root, "安装器改动", risk="high", delivery="frontend", acceptance=_acceptance()
    )
    task_id, review_id = result["task"], result["review_task"]
    from meta_flow.task import submit_task

    start_task(sub, task_id)
    target_bundle = _task_bundle(contract, task_id)
    (target_bundle / "dev-record.md").write_text("# dev\n实现完成\n", encoding="utf-8")
    (target_bundle / "handoff.md").write_text("# handoff\n完成\n", encoding="utf-8")
    submit_task(sub, task_id)
    start_task(sub, review_id)

    target = _task_bundle(contract, task_id) / "dev-record.md"
    own = _task_bundle(contract, review_id) / "review.md"
    own.write_text("# review\nverdict: PASS\n", encoding="utf-8")
    third = contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / "T999" / "dev-record.md"
    third.parent.mkdir(parents=True, exist_ok=True)
    third.write_text("# third\n", encoding="utf-8")

    monkeypatch.setenv("MF_ROLE", "worker")
    assert guard.pretool_decision(_payload("Read", sub, target)) is None
    assert guard.pretool_decision(_payload("Read", sub, own)) is None
    decision = guard.pretool_decision(_payload("Read", sub, third))
    assert decision is not None


def test_guard_bash_path_policy_and_audit(env, monkeypatch):
    root, contract, sub = env
    create_task(
        root,
        "前端任务",
        risk="low",
        delivery="frontend",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
    )
    start_task(sub, "R1-P1-T001")
    own = _task_bundle(contract, "R1-P1-T001") / "dev-record.md"
    own.write_text("# dev\n", encoding="utf-8")
    source = sub / "src" / "main.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("print('ok')\n", encoding="utf-8")
    big = sub / "src" / "big.py"
    big.write_text("x" * (70 * 1024), encoding="utf-8")
    other = contract / "requirements" / "INDEX.md"
    other.write_text("# index\n", encoding="utf-8")

    def bash(command, cwd=sub):
        return {
            "tool_name": "Bash",
            "cwd": str(cwd),
            "tool_input": {"command": command},
        }

    monkeypatch.setenv("MF_ROLE", "worker")
    # 自身 bundle 可读；契约基线/读预算/写越界拒绝
    assert guard.pretool_decision(bash(f"cat {own}")) is None
    decision = guard.pretool_decision(bash(f"cat {other}"))
    assert decision is not None
    assert "Bash" in decision["hookSpecificOutput"]["permissionDecisionReason"]
    decision = guard.pretool_decision(bash(f"cat {big}"))
    assert decision is not None
    assert "context expand" in decision["hookSpecificOutput"]["permissionDecisionReason"]
    decision = guard.pretool_decision(bash(f"echo x > {sub / 'outside.txt'}"))
    assert decision is not None
    assert "allowed_paths" in decision["hookSpecificOutput"]["permissionDecisionReason"]
    assert guard.pretool_decision(bash(f"cat {source}")) is None

    # 无交付根绑定：workspace 根执行 shell 读契约被拒绝
    decision = guard.pretool_decision(bash(f"cat {other}", cwd=root))
    assert decision is not None
    log = (contract / "state" / "READ-LOG.ndjson").read_text(encoding="utf-8")
    assert '"event": "guard"' in log
    assert '"tool": "Bash"' in log
    assert '"decision": "deny"' in log
    assert '"task": "R1-P1-T001"' in log


def _bash_payload(command, cwd):
    return {"tool_name": "Bash", "cwd": str(cwd), "tool_input": {"command": command}}


def test_guard_bash_expands_variables_and_nested_shell(env, monkeypatch):
    root, contract, sub = env
    create_task(
        root,
        "前端任务",
        risk="low",
        delivery="frontend",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
    )
    start_task(sub, "R1-P1-T001")
    own = _task_bundle(contract, "R1-P1-T001") / "dev-record.md"
    own.write_text("# dev\n", encoding="utf-8")
    (contract / "requirements" / "INDEX.md").write_text("# index\n", encoding="utf-8")

    monkeypatch.setenv("MF_ROLE", "worker")
    monkeypatch.setenv("HOME", str(root))
    for command in (
        'cat "$HOME/demo-contract/requirements/INDEX.md"',
        "cd $HOME/demo-contract && cat requirements/INDEX.md",
        "sh -c 'cat $HOME/demo-contract/requirements/INDEX.md'",
        'bash -c "cat $HOME/demo-contract/requirements/INDEX.md"',
        "cat $UNKNOWN_VAR/demo-contract/requirements/INDEX.md",
    ):
        decision = guard.pretool_decision(_bash_payload(command, sub))
        assert decision is not None, command
        assert "Meta Flow 边界" in decision["hookSpecificOutput"]["permissionDecisionReason"]

    own_by_var = (
        'cat "$HOME/demo-contract/roadmap/R1/phases/P1/tasks/T001/dev-record.md"'
    )
    assert guard.pretool_decision(_bash_payload(own_by_var, sub)) is None
    nested_own = (
        "sh -c 'cat $HOME/demo-contract/roadmap/R1/phases/P1/tasks/T001/dev-record.md'"
    )
    assert guard.pretool_decision(_bash_payload(nested_own, sub)) is None

    log_lines = (contract / "state" / "READ-LOG.ndjson").read_text(encoding="utf-8").splitlines()
    deny_records = [json.loads(line) for line in log_lines if '"decision": "deny"' in line]
    assert any("$HOME" in record.get("command", "") for record in deny_records)
    assert any(
        "demo-contract/requirements" in " ".join(record.get("parsed_paths") or [])
        for record in deny_records
    )


def test_guard_deny_includes_task_lease_allowed_and_protocol(env, monkeypatch):
    from meta_flow.task import reject_task, submit_task

    root, contract, sub = env
    create_task(
        root,
        "前端任务",
        risk="low",
        delivery="frontend",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
    )
    start_task(sub, "R1-P1-T001")
    monkeypatch.setenv("MF_ROLE", "worker")
    decision = guard.pretool_decision(
        _payload("Write", sub, sub / "outside.txt")
    )
    reason = decision["hookSpecificOutput"]["permissionDecisionReason"]
    assert "role=worker" in reason
    assert "task=R1-P1-T001" in reason
    assert "lease=" in reason
    assert "allowed=src/**" in reason
    assert "mf task rework" in reason
    assert "不阻塞返工" in reason

    bundle = _task_bundle(contract, "R1-P1-T001")
    (bundle / "dev-record.md").write_text("# dev\n完成\n", encoding="utf-8")
    (bundle / "handoff.md").write_text("# handoff\n完成\n", encoding="utf-8")
    submit_task(sub, "R1-P1-T001")
    decision = guard.pretool_decision(
        _payload("Write", sub, sub / "outside.txt")
    )
    reason = decision["hookSpecificOutput"]["permissionDecisionReason"]
    assert "task=无" in reason
    assert "mf task rework" in reason
    assert "不阻塞返工" in reason

    reject_task(root, "R1-P1-T001", "补证据")
    from meta_flow.task import prompt_text

    prompt = prompt_text(sub, "R1-P1-T001")
    assert "mf task start R1-P1-T001" in prompt


def test_worker_can_write_local_mfp_after_submit(env, monkeypatch):
    from meta_flow.task import submit_task

    root, contract, sub = env
    create_task(
        root,
        "前端任务",
        risk="low",
        delivery="frontend",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
    )
    start_task(sub, "R1-P1-T001")
    bundle = _task_bundle(contract, "R1-P1-T001")
    (bundle / "dev-record.md").write_text("# dev\n完成\n", encoding="utf-8")
    (bundle / "handoff.md").write_text("# handoff\n完成\n", encoding="utf-8")
    submit_task(sub, "R1-P1-T001")

    improvements = sub / ".meta-flow" / "improvements"
    improvements.mkdir(parents=True, exist_ok=True)
    mfp = improvements / "MFP-0002.yaml"
    monkeypatch.setenv("MF_ROLE", "worker")
    assert guard.pretool_decision(_payload("Write", sub, mfp)) is None
    assert (
        guard.pretool_decision(_payload("Write", sub, improvements / "notes.txt"))
        is not None
    )
    assert (
        guard.pretool_decision(
            _payload("Write", sub, sub / ".meta-flow" / "other" / "MFP-0001.yaml")
        )
        is not None
    )
    log = (contract / "state" / "READ-LOG.ndjson").read_text(encoding="utf-8")
    assert '"tool": "Write"' in log
    assert "MFP-0002.yaml" in log
    assert '"decision": "allow"' in log


def test_guard_audit_records_fields_and_redacts_secrets(env, monkeypatch):
    root, contract, sub = env
    create_task(
        root,
        "前端任务",
        risk="low",
        delivery="frontend",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
    )
    start_task(sub, "R1-P1-T001")
    own = _task_bundle(contract, "R1-P1-T001") / "dev-record.md"
    own.write_text("# dev\n", encoding="utf-8")
    other = contract / "requirements" / "INDEX.md"
    other.write_text("# index\n", encoding="utf-8")
    monkeypatch.setenv("MF_ROLE", "worker")

    assert guard.pretool_decision(_payload("Read", sub, own)) is None
    assert guard.pretool_decision(_payload("Read", sub, other)) is not None
    secret_command = f"cat {other} --password supersecret-value"
    assert guard.pretool_decision(_bash_payload(secret_command, sub)) is not None

    log_path = contract / "state" / "READ-LOG.ndjson"
    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    guard_records = [record for record in records if record.get("event") == "guard"]
    assert any(record.get("decision") == "allow" for record in guard_records)
    deny = next(record for record in guard_records if record.get("decision") == "deny")
    for field in ("role", "task", "path", "reason", "tool"):
        assert field in deny
    assert deny["tool"] in {"Read", "Bash"}
    assert "supersecret-value" not in log_path.read_text(encoding="utf-8")
    assert "***" in log_path.read_text(encoding="utf-8")


def test_guard_bundle_match_uses_full_task_id(env, monkeypatch):
    root, contract, sub = env
    create_task(
        root,
        "前端任务",
        risk="low",
        delivery="frontend",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
    )
    start_task(sub, "R1-P1-T001")
    own = _task_bundle(contract, "R1-P1-T001") / "dev-record.md"
    own.write_text("# dev\n", encoding="utf-8")
    fake = contract / "roadmap" / "R0" / "phases" / "P4" / "tasks" / "T001" / "dev-record.md"
    fake.parent.mkdir(parents=True)
    fake.write_text("# fake\n", encoding="utf-8")

    monkeypatch.setenv("MF_ROLE", "worker")
    assert guard.pretool_decision(_payload("Read", sub, own)) is None
    decision = guard.pretool_decision(_payload("Read", sub, fake))
    assert decision is not None
    assert "bundle" in decision["hookSpecificOutput"]["permissionDecisionReason"]


def test_bash_write_heuristic_ignores_fd_dup_but_keeps_redirects():
    assert guard._bash_write_heuristic("wc -l src/main.py 2>&1") is False
    assert guard._bash_write_heuristic("command >&2") is False
    assert guard._bash_write_heuristic("echo x > out.txt") is True
    assert guard._bash_write_heuristic("echo x 2> err.txt") is True
    assert guard._bash_write_heuristic("echo x >> out.txt") is True


def test_guard_bash_blocks_eval_source_and_process_substitution(env, monkeypatch):
    root, contract, sub = env
    create_task(
        root,
        "前端任务",
        risk="low",
        delivery="frontend",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
    )
    start_task(sub, "R1-P1-T001")
    own = _task_bundle(contract, "R1-P1-T001") / "dev-record.md"
    own.write_text("# dev\n", encoding="utf-8")
    (contract / "requirements" / "INDEX.md").write_text("# index\n", encoding="utf-8")

    monkeypatch.setenv("MF_ROLE", "worker")
    monkeypatch.setenv("HOME", str(root))
    denied = [
        'eval "cat \\$HOME/demo-contract/requirements/INDEX.md"',
        'source <(echo "cat \\$HOME/demo-contract/requirements/INDEX.md")',
        '. <(echo "cat \\$HOME/demo-contract/requirements/INDEX.md")',
        "cat \\$HOME/demo-contract/requirements/INDEX.md",
        "env HOME=" + str(root) + " sh -c 'cat $HOME/demo-contract/requirements/INDEX.md'",
        f"echo {contract / 'requirements' / 'INDEX.md'} | xargs cat",
    ]
    for command in denied:
        decision = guard.pretool_decision(_bash_payload(command, sub))
        assert decision is not None, command

    allowed = [
        'eval "cat \\$HOME/demo-contract/roadmap/R1/phases/P1/tasks/T001/dev-record.md"',
        "cat $HOME/demo-contract/roadmap/R1/phases/P1/tasks/T001/dev-record.md",
        "bash -c 'cat $HOME/demo-contract/roadmap/R1/phases/P1/tasks/T001/dev-record.md'",
    ]
    for command in allowed:
        assert guard.pretool_decision(_bash_payload(command, sub)) is None, command

    log_path = contract / "state" / "READ-LOG.ndjson"
    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    guard_records = [record for record in records if record.get("event") == "guard"]
    assert any(
        record.get("tool") == "Bash"
        and record.get("decision") == "deny"
        and record.get("unsafe") is True
        for record in guard_records
    )
    assert any(
        "$HOME" in record.get("command", "") and record.get("parsed_paths")
        for record in guard_records
    )
