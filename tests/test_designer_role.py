"""WP-F1/T035：designer 角色、设计包、责任映射与角色锚点（A1–A4/A7）。"""
from __future__ import annotations

import io
import json

import pytest
import yaml

from meta_flow import guard, roles, state, templates
from meta_flow.cli import main
from meta_flow.global_store import bootstrap
from meta_flow.install import install_designer, install_root
from meta_flow.task import (
    TaskError,
    create_task,
    load_task,
    packet_text,
    prompt_text,
    start_task,
    submit_task,
)
from meta_flow.workspace import (
    detect_role,
    doctor,
    workspace_add_project,
    workspace_init,
)


class FakeTTY(io.StringIO):
    def isatty(self) -> bool:  # noqa: D401 - 测试桩
        return True


def _acceptance():
    return [{"id": "A1", "method": "artifact", "expect": "设计完成"}]


@pytest.fixture()
def env(tmp_path, monkeypatch):
    home = tmp_path / "global"
    monkeypatch.setenv("META_FLOW_HOME", str(home))
    bootstrap()
    root = tmp_path / "demo"
    root.mkdir()
    install_root(root)
    workspace_init(root, "Demo")
    contract = root / "demo-contract"
    sub = root / "frontend"
    workspace_add_project(root, "frontend", "frontend")
    return {"root": root, "contract": contract, "sub": sub}


def _payload(tool, cwd, path, session_id=None):
    payload = {"tool_name": tool, "cwd": str(cwd), "tool_input": {"file_path": str(path)}}
    if session_id:
        payload["session_id"] = session_id
    return payload


def _bash(command, cwd):
    return {"tool_name": "Bash", "cwd": str(cwd), "tool_input": {"command": command}}


def _write_design_files(contract, task_id):
    bundle = contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / f"T{task_id[-3:]}"
    (bundle / "dev-record.md").write_text("# dev\n设计完成\n", encoding="utf-8")
    (bundle / "handoff.md").write_text("# handoff\n完成\n", encoding="utf-8")
    return bundle


def test_role_aliases_and_designer_agent_template():
    assert roles.normalize_role("mgr") == "manager"
    assert roles.normalize_role("dsg") == "designer"
    assert roles.normalize_role("meta-designer") == "designer"
    assert roles.normalize_role("wkr") == "worker"
    assert roles.normalize_role("mnt") == "maintainer"
    assert roles.normalize_role("unknown") is None
    assert "name: designer" in templates.AGENT_DESIGNER
    assert "designer" in templates.DESIGNER_CLAUDE
    assert "不写生产源码" in templates.AGENT_DESIGNER


def test_designer_install_and_doctor(env):
    root, contract = env["root"], env["contract"]
    result = install_designer(contract, workspace_root=root)
    assert result["agents"] == ["designer"]
    assert (contract / ".claude" / "agents" / "designer.md").is_file()
    assert (contract / "CLAUDE.md").is_file()
    assert "meta-flow:designer:start" in (contract / "CLAUDE.md").read_text(encoding="utf-8")
    settings = json.loads(
        (contract / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    assert settings["agent"] == "designer"
    commands = [
        item.get("command")
        for entry in settings["hooks"]["PreToolUse"]
        for item in entry.get("hooks") or []
    ]
    assert guard.HOOK_COMMAND in commands
    session_commands = [
        item.get("command")
        for entry in settings["hooks"]["SessionStart"]
        for item in entry.get("hooks") or []
    ]
    assert "mf hook session-start" in session_commands
    manifest = yaml.safe_load(
        (contract / ".meta-flow" / "install.yaml").read_text(encoding="utf-8")
    )
    assert manifest["role"] == "designer"
    assert detect_role(contract)[0] == "designer"
    assert doctor(root) == []


def test_design_package_template_single_source(env):
    contract = env["contract"]
    template = templates.ARTIFACT_TEMPLATES["DESIGN-PACKAGE.md"]
    assert (contract / "templates" / "DESIGN-PACKAGE.md").read_text(
        encoding="utf-8"
    ) == template
    repo = __import__("pathlib").Path(__file__).resolve().parents[1]
    delivery_template = repo / "templates" / "DESIGN-PACKAGE.md"
    assert delivery_template.is_file()
    assert delivery_template.read_text(encoding="utf-8") == template
    for field in (
        "信息流",
        "子项目/职责/交互/接口",
        "模块/功能/接口",
        "映射表（REQ/MFP → SPEC → 子项目/模块）",
        "跨子项目验证计划",
        "预研计划",
        "设计验收（manager）",
    ):
        assert field in template


def test_design_task_defaults_owner_designer_and_prompt_packet(env):
    root, contract = env["root"], env["contract"]
    result = create_task(
        root,
        "设计包 DP",
        kind="design",
        risk="low",
        allowed_paths=["architecture/**", "specs/**"],
        acceptance=_acceptance(),
    )
    task_id = result["task"]
    _, task = load_task(root, task_id)
    assert task["owner_role"] == "designer"
    assert task["executor_role"] == "designer"
    assert task["next_owner"] == "designer"
    prompt = prompt_text(root, task_id)
    assert "responsible_agent: designer" in prompt
    assert "owner_role: designer" in prompt
    assert "executor_role: designer" in prompt
    packet = packet_text(root, task_id)
    assert "- owner_role: designer" in packet
    assert "- executor_role: designer" in packet
    assert "- delivery: -" in packet
    assert state.reconcile(contract) == []


def test_design_task_non_designer_owner_requires_manager_confirmation(env):
    root, contract = env["root"], env["contract"]
    with pytest.raises(TaskError, match="owner-confirmed-by"):
        create_task(
            root,
            "manager 主责设计",
            kind="design",
            risk="low",
            owner_role="manager",
            acceptance=_acceptance(),
        )
    result = create_task(
        root,
        "manager 主责设计（已确认）",
        kind="design",
        risk="low",
        owner_role="manager",
        owner_confirmed_by="manager:user-2026-11-27",
        acceptance=_acceptance(),
    )
    _, task = load_task(root, result["task"])
    assert task["owner_role"] == "manager"
    assert task["owner_confirmation"]["confirmed_by"] == "manager:user-2026-11-27"
    ledger = (contract / "state" / "ledger.ndjson").read_text(encoding="utf-8")
    assert "task.owner.confirm" in ledger


def test_design_task_actor_rules(env, monkeypatch):
    root, contract = env["root"], env["contract"]
    result = create_task(
        root,
        "设计任务",
        kind="design",
        risk="low",
        allowed_paths=["architecture/**"],
        acceptance=_acceptance(),
    )
    task_id = result["task"]
    # worker（默认）不得冒充 designer
    with pytest.raises(TaskError, match="不得冒充 designer"):
        start_task(root, task_id)
    monkeypatch.setenv("MF_ROLE", "designer")
    started = start_task(root, task_id)
    assert started["status"] == "in_progress"
    assert started["next_owner"] == "designer"
    _write_design_files(contract, task_id)
    submitted = submit_task(root, task_id)
    assert submitted["status"] == "submitted"
    assert submitted["next_owner"] == "manager"

    # designer 不得执行 implement 任务
    impl = create_task(
        root,
        "实现任务",
        risk="low",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
    )
    with pytest.raises(TaskError, match="designer 只能执行 design"):
        start_task(root, impl["task"])


def test_designer_guard_workspace_permissions(env, monkeypatch):
    root, contract, sub = env["root"], env["contract"], env["sub"]
    install_designer(contract, workspace_root=root)
    monkeypatch.setenv("MF_ROLE", "designer")
    (contract / "architecture").mkdir(parents=True, exist_ok=True)
    (sub / "src").mkdir(parents=True, exist_ok=True)
    (sub / "src" / "main.py").write_text("print('x')\n", encoding="utf-8")

    # contract 设计区写放行
    for relative in (
        "architecture/ARCHITECTURE.md",
        "specs/SPEC-FRAMEWORK.md",
        "roadmap/R1/phases/P2/design/DP-001.md",
        "templates/DESIGN-PACKAGE.md",
    ):
        assert guard.pretool_decision(_payload("Write", contract, contract / relative)) is None
    # 需求/发布/归档/子项目源码写拒绝
    for path in (
        contract / "requirements" / "REQ-0001.md",
        contract / "release" / "RELEASE.md",
        contract / "archive" / "R1" / "INDEX.md",
        sub / "src" / "main.py",
        root / "README.md",
    ):
        decision = guard.pretool_decision(_payload("Write", contract, path))
        assert decision is not None, path
        assert (
            "mf role --as" in decision["hookSpecificOutput"]["permissionDecisionReason"]
        ), path
    # 子项目源码只读
    assert guard.pretool_decision(_payload("Read", contract, sub / "src" / "main.py")) is None
    # Bash 同样：设计区写放行、子项目写拒绝
    assert (
        guard.pretool_decision(
            _bash(f"echo x > {contract / 'architecture' / 'NEW.md'}", contract)
        )
        is None
    )
    decision = guard.pretool_decision(_bash(f"echo x > {sub / 'src' / 'main.py'}", contract))
    assert decision is not None
    # worker 不能写会话锚点伪造角色
    monkeypatch.setenv("MF_ROLE", "worker")
    decision = guard.pretool_decision(
        _payload("Write", sub, sub / ".meta-flow" / "session-role.yaml")
    )
    assert decision is not None
    # 任何角色都不能通过工具直接写锚点/手动执行 SessionStart hook
    assert (
        guard.pretool_decision(
            _payload("Write", contract, contract / ".meta-flow" / "session-role.yaml")
        )
        is not None
    )
    assert guard.pretool_decision(_bash("mf hook session-start", contract)) is not None
    log = (contract / "state" / "READ-LOG.ndjson").read_text(encoding="utf-8")
    assert '"decision": "deny"' in log
    assert '"role": "designer"' in log


def test_role_anchor_session_start_multi_session_and_clear(env):
    root, contract, sub = env["root"], env["contract"], env["sub"]
    (contract / "requirements" / "INDEX.md").write_text("# index\n", encoding="utf-8")

    worker_anchor = roles.session_start(
        sub, source="startup", session_id="s-worker"
    )
    assert worker_anchor["role"] == "worker"
    # N4：worker 会话在 workspace 根读 contract 仍拒绝（按会话锚点）
    decision = guard.pretool_decision(
        _payload(
            "Read", root, contract / "requirements" / "INDEX.md", session_id="s-worker"
        )
    )
    assert decision is not None

    manager_anchor = roles.session_start(
        root, source="startup", session_id="s-manager"
    )
    assert manager_anchor["role"] == "manager"
    # M2：manager 会话的 SessionStart 不得覆盖 worker 会话
    decision = guard.pretool_decision(
        _payload(
            "Read", sub, contract / "requirements" / "INDEX.md", session_id="s-worker"
        )
    )
    assert decision is not None
    # N3：manager 会话在子项目 cwd 读 contract 允许（按会话锚点）
    assert (
        guard.pretool_decision(
            _payload(
                "Read",
                sub,
                contract / "requirements" / "INDEX.md",
                session_id="s-manager",
            )
        )
        is None
    )
    # 无 session_id：不回退共享会话锚点，按目录推导（worker）拒绝
    assert guard.pretool_decision(
        _payload("Read", sub, contract / "requirements" / "INDEX.md")
    ) is not None

    # /clear 只重写本会话锚点
    cleared = roles.session_start(sub, source="clear", session_id="s-worker")
    assert cleared["role"] == "worker"
    decision = guard.pretool_decision(
        _payload(
            "Read", root, contract / "requirements" / "INDEX.md", session_id="s-worker"
        )
    )
    assert decision is not None
    info = roles.describe(sub)
    assert info["source"] == "directory"
    assert info["effective"] == "worker"


def test_role_switch_requires_tty_and_writes_ledger(env, monkeypatch):
    _root, contract, sub = env["root"], env["contract"], env["sub"]
    monkeypatch.chdir(sub)
    with pytest.raises(roles.RoleError, match="非 TTY"):
        roles.switch_role("manager", "测试", cwd=sub)
    # CLI 非 TTY：rc=3
    assert main(["role", "--as", "designer", "--reason", "测试"]) == 3
    # 用户终端（模拟 TTY）：写锚点 + ledger
    out = FakeTTY()
    data = roles.switch_role(
        "mgr", "用户终端切换", cwd=sub, stream=FakeTTY(), out=out
    )
    assert data["role"] == "manager"
    anchor = roles.read_anchor(sub)
    assert anchor["role"] == "manager"
    assert anchor["source"] == "user-tty"
    ledger_lines = [
        json.loads(line)
        for line in (contract / "state" / "ledger.ndjson")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert any(
        event.get("event") == "role.switch" and event.get("to") == "manager"
        for event in ledger_lines
    )


def test_worker_env_designer_cannot_escalate(env, monkeypatch):
    _root, contract, sub = env["root"], env["contract"], env["sub"]
    (contract / "requirements" / "INDEX.md").write_text("# index\n", encoding="utf-8")
    monkeypatch.setenv("MF_ROLE", "designer")
    # 无锚点/目录 designer：env 不能提权，仍按 worker 拒绝 contract 读取
    decision = guard.pretool_decision(
        _payload("Read", sub, contract / "requirements" / "INDEX.md")
    )
    assert decision is not None
    assert "bundle" in decision["hookSpecificOutput"]["permissionDecisionReason"]


def test_manager_cannot_delegate_design_to_worker(env):
    root = env["root"]
    # 未确认的 manager 主责 design 被拒绝（N6 委托绕过）
    with pytest.raises(TaskError, match="owner-confirmed-by"):
        create_task(
            root,
            "manager 代做设计",
            kind="design",
            risk="low",
            owner_role="manager",
            executor_role="worker",
            acceptance=_acceptance(),
        )


def test_session_start_hook_cli_writes_anchor(env, monkeypatch):
    _root, sub = env["root"], env["sub"]
    payload = {
        "cwd": str(sub),
        "source": "startup",
        "session_id": "s-hook",
        "hook_event_name": "SessionStart",
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    assert main(["hook", "session-start"]) == 0
    anchor = roles.read_anchor(sub, "s-hook")
    assert anchor is not None
    assert anchor["role"] == "worker"
    assert str(anchor["root"]) == str(sub.resolve())
    # 无 session_id 时不写共享锚点（fail-closed）
    monkeypatch.setattr(
        "sys.stdin", io.StringIO(json.dumps({"cwd": str(sub), "source": "clear"}))
    )
    assert main(["hook", "session-start"]) == 0
    assert roles.read_anchor(sub, "unknown-session") is None


def test_m1_nested_session_hook_and_anchor_api_denied(env, monkeypatch):
    _root, contract, sub = env["root"], env["contract"], env["sub"]
    monkeypatch.setenv("MF_ROLE", "worker")
    commands = [
        "mf hook session-start",
        f"cd {contract} && mf hook session-start",
        f"sh -c 'cd {contract} && mf hook session-start'",
        f'bash -c "cd {contract} && mf hook session-start"',
        f"python3 -c \"from meta_flow.roles import session_start; session_start(r'{contract}')\"",
        f"python3 -c \"from meta_flow.roles import write_anchor; write_anchor('designer', start=r'{contract}', source='session-start', session_id='x')\"",
        f"python3 -c \"from meta_flow import roles as r; r.write_anchor('designer', start=r'{contract}', source='user-tty')\"",
        "python3 -c \"import importlib; importlib.import_module('meta_flow.roles').session_start('.')\"",
        f"python3 -c \"from meta_flow.roles import write_anchor as w; w('designer', start=r'{contract}', source='user-tty')\"",
        "python3 -c \"import meta_flow; getattr(meta_flow, 'roles').write_anchor('designer', start='.', source='user-tty')\"",
        "python3 -c \"import meta_flow; r=getattr(meta_flow,'roles'); getattr(r,'write_'+'anchor')('designer', start='.', source='user-tty')\"",
        "python3 -c \"import meta_flow; getattr(meta_flow,'roles').session_start('.')\"",
    ]
    for command in commands:
        decision = guard.pretool_decision(_bash(command, sub))
        assert decision is not None, command
    # 未被写入任何有效锚点
    assert roles.read_anchor(sub, "s-real") is None


def test_m1b_anchor_write_requires_session_binding(env):
    _root, contract, sub = env["root"], env["contract"], env["sub"]
    # 无 session_id：拒绝写锚点（fail-closed）
    assert roles.session_start(contract) is None
    assert roles.read_anchor(contract, "s-real") is None
    # 伪造其它 session 的锚点不影响当前会话
    fake = roles.session_start(contract, session_id="s-fake")
    assert fake is not None
    assert roles.read_anchor(contract, "s-fake")["role"] == "manager"
    assert guard._resolve_role(sub, "s-real") == ("worker", sub)
    assert guard.pretool_decision(
        _payload("Read", sub, contract / "requirements" / "INDEX.md", session_id="s-real")
    ) is not None


def test_user_tty_switch_overrides_until_next_session_start(env):
    _root, contract, sub = env["root"], env["contract"], env["sub"]
    (contract / "requirements" / "INDEX.md").write_text("# index\n", encoding="utf-8")
    roles.switch_role(
        "manager", "用户终端切换", cwd=sub, stream=FakeTTY(), out=FakeTTY()
    )
    # 任意会话（含无 sid）先认用户显式切换
    assert roles.read_anchor(sub, "s-other")["role"] == "manager"
    assert roles.read_anchor(sub)["role"] == "manager"
    # 本会话下一次 SessionStart 覆盖用户切换
    roles.session_start(sub, session_id="s-other")
    assert roles.read_anchor(sub, "s-other")["role"] == "worker"
    assert roles.read_anchor(sub, "s-new")["role"] == "manager"
    assert guard.pretool_decision(
        _payload(
            "Read", sub, contract / "requirements" / "INDEX.md", session_id="s-other"
        )
    ) is not None


def test_r1_user_tty_anchor_requires_tty(env):
    _root, _contract, sub = env["root"], env["contract"], env["sub"]
    with pytest.raises(roles.RoleError, match="非 TTY"):
        roles.write_anchor("manager", start=sub, source="user-tty")
    # 未写入任何 user-tty 锚点
    assert roles.read_anchor(sub) is None
    assert roles.read_anchor(sub, "s-any") is None
    # FakeTTY 的 switch_role 仍可写（用户终端路径）
    roles.switch_role(
        "manager", "用户终端切换", cwd=sub, stream=FakeTTY(), out=FakeTTY()
    )
    assert roles.read_anchor(sub)["role"] == "manager"

    # 其他会话/无 sid 只受人工 user-tty 影响；AI 不能直接写
    with pytest.raises(roles.RoleError, match="非 TTY"):
        roles.write_anchor("designer", start=sub, source="user-tty")


@pytest.mark.xfail(
    strict=False,
    reason="R2 范围外（CHG/BUG 待 manager）：真实 session_id 直接 API 调用属威胁模型边界",
)
def test_r2_real_session_id_direct_api_should_not_escalate(env, monkeypatch):
    _root, contract, _sub = env["root"], env["contract"], env["sub"]
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s-real")
    roles.session_start(contract, session_id="s-real")
    # 负向期望：真实 sid 直接 API 不应写入有效锚点（当前仍可，R2 范围外）
    assert roles.read_anchor(contract, "s-real") is None


def test_r4_module_and_list_session_hook_denied(env, monkeypatch):
    _root, _contract, sub = env["root"], env["contract"], env["sub"]
    monkeypatch.setenv("MF_ROLE", "worker")
    commands = [
        "python -m meta_flow.cli hook session-start",
        "sh -c 'python -m meta_flow.cli hook session-start'",
        "bash -c 'python -m meta_flow.cli hook session-start'",
        "python -c \"import subprocess; subprocess.run(['mf','hook','session-start'])\"",
        "python -c \"import subprocess; subprocess.run(['meta_flow.cli','hook','session-start'])\"",
        "python -c \"from meta_flow.cli import main; main(['hook','session-start'])\"",
        "python -c \"import subprocess; subprocess.run(['mf','hook','session'+'-start'])\"",
    ]
    for command in commands:
        decision = guard.pretool_decision(_bash(command, sub))
        assert decision is not None, command
    # 纯只读检索不误伤
    assert (
        guard.pretool_decision(_bash('grep "hook session-start" README.md', sub))
        is None
    )
    # 未写入有效锚点
    assert roles.read_anchor(sub, "s-real") is None


def test_r5_split_anchor_function_name_denied(env, monkeypatch):
    _root, _contract, sub = env["root"], env["contract"], env["sub"]
    monkeypatch.setenv("MF_ROLE", "worker")
    commands = [
        "python3 -c \"from meta_flow import roles as r; getattr(r,'session_'+'start')('.')\"",
        "python3 -c \"from meta_flow import roles as r; getattr(r,'switch'+'_role')('manager','x')\"",
        "python3 -c \"import importlib; m=importlib.import_module('meta_flow.roles'); getattr(m,'write_'+'anchor')('designer', start='.', source='user-tty')\"",
        "python3 -c \"from meta_flow import roles as r; getattr(r, 'sess'+'ion'+'start')('.')\"",
    ]
    for command in commands:
        decision = guard.pretool_decision(_bash(command, sub))
        assert decision is not None, command
    assert roles.read_anchor(sub, "s-real") is None


def test_cli_design_task_role_flow(env, monkeypatch, capsys):
    root, contract, _sub = env["root"], env["contract"], env["sub"]
    install_designer(contract, workspace_root=root)
    monkeypatch.chdir(root)
    capsys.readouterr()
    assert (
        main(
            [
                "task",
                "create",
                "--kind",
                "design",
                "--title",
                "CLI 设计任务",
                "--risk",
                "low",
                "--allowed-path",
                "architecture/**",
                "--acceptance",
                "设计完成",
            ]
        )
        == 0
    )
    _, task = load_task(contract, "R1-P1-T001")
    assert task["owner_role"] == "designer"
    # manager 不得 start（_enforce_role）
    assert main(["task", "start", "R1-P1-T001"]) == 3
    # designer（contract 目录）可以 start/submit
    monkeypatch.chdir(contract)
    capsys.readouterr()
    assert main(["task", "start", "R1-P1-T001"]) == 0
    _write_design_files(contract, "R1-P1-T001")
    assert main(["task", "submit", "R1-P1-T001"]) == 0
    _, submitted = load_task(contract, "R1-P1-T001")
    assert submitted["status"] == "submitted"
    assert submitted["next_owner"] == "manager"
    # manager 验收设计
    monkeypatch.chdir(root)
    assert main(["task", "accept", "R1-P1-T001", "--verdict", "PASS"]) == 0
    _, accepted = load_task(contract, "R1-P1-T001")
    assert accepted["status"] == "accepted"


def test_role_json_with_anchor_is_serializable(env, monkeypatch, capsys):
    """A4：存在会话锚点时 mf role --json 不得因 Path 崩溃。"""
    root = env["root"]
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-json-a4")
    roles.write_anchor(
        "maintainer",
        start=root,
        source="session-start",
        session_id="sid-json-a4",
        cwd=root,
        root=root,
    )
    capsys.readouterr()
    assert main(["role", "--path", str(root), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["role"] == "maintainer"
    assert data["source"] == "anchor"
    assert data["session_id"] == "sid-json-a4"
    assert isinstance(data["anchor"]["root"], str)
    assert isinstance(data["anchor"]["session_id"], str)

    # 无锚点（无会话标识、无 user-tty）时同样可序列化
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    capsys.readouterr()
    assert main(["role", "--path", str(root), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["anchor"] is None
    assert data["role"] == "manager"


def test_role_reset_removes_all_anchor_kinds_and_audits(env, monkeypatch):
    """MFP-0039：reset 只清理 user-tty/会话/遗留锚点，不写新锚点。"""
    root = env["root"]
    sub = env["sub"]
    contract = env["contract"]
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s-reset")
    roles.write_anchor(
        "worker",
        start=sub,
        source="session-start",
        cwd=sub,
        session_id="s-reset",
        root=sub,
    )
    roles.write_anchor(
        "maintainer",
        start=root,
        source="user-tty",
        cwd=root,
        root=root,
        stream=FakeTTY(),
        out=FakeTTY(),
    )
    legacy = root / ".meta-flow" / "session-role.yaml"
    legacy.write_text("role: manager\nroot: " + str(root) + "\n", encoding="utf-8")
    assert roles.read_anchor(root, "s-reset") is not None

    result = roles.reset_anchor(root, session_id="s-reset")
    assert len(result["removed"]) == 3
    assert roles.read_anchor(root, "s-reset") is None
    assert not legacy.exists()
    assert not (root / ".meta-flow" / "session-roles" / "user-tty.yaml").exists()
    events = [
        json.loads(line)
        for line in (contract / "state" / "ledger.ndjson")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert any(
        event.get("event") == "role.reset" and event.get("removed")
        for event in events
    )


def test_role_reset_cli_requires_maintainer(env, monkeypatch, capsys):
    """MFP-0039/REQ-0023：worker 不能 reset；maintainer 可清理。"""
    root = env["root"]
    monkeypatch.setenv("MF_ROLE", "worker")
    capsys.readouterr()
    assert main(["role", "--path", str(root), "--reset"]) == 3

    anchor = root / ".meta-flow" / "session-roles" / "user-tty.yaml"
    anchor.parent.mkdir(parents=True, exist_ok=True)
    anchor.write_text("role: manager\nroot: " + str(root) + "\n", encoding="utf-8")
    monkeypatch.setenv("MF_ROLE", "maintainer")
    capsys.readouterr()
    assert main(["role", "--path", str(root), "--reset"]) == 0
    assert not anchor.exists()


@pytest.mark.parametrize(
    "command",
    [
        'git commit -m "fix(anchor): note uv run meta_flow"',
        'git commit -m "docs: mf hook session-start anchor"',
        "uv run python -m meta_flow.cli status",
        'grep "mf hook session-start" README.md',
    ],
)
def test_maintenance_commands_not_blocked_by_anchor_heuristics(
    env, monkeypatch, command
):
    """MFP-0039/REQ-0023：提交消息/uv/只读 grep 不误拦。"""
    monkeypatch.setenv("MF_ROLE", "worker")
    assert guard.pretool_decision(_bash(command, env["sub"])) is None


def test_real_anchor_and_hook_calls_still_denied(env, monkeypatch):
    """MFP-0039：误伤修复后真实入口仍 fail-closed。"""
    monkeypatch.setenv("MF_ROLE", "worker")
    commands = [
        "mf hook session-start",
        "git commit -m ok && mf hook session-start",
        "python -c \"from meta_flow.roles import write_anchor; "
        "write_anchor('worker', start='.', source='session-start', session_id='x')\"",
    ]
    for command in commands:
        assert guard.pretool_decision(_bash(command, env["sub"])) is not None


def test_worker_manager_cannot_write_anchor_file(env, monkeypatch):
    """MFP-0039：worker/manager 不得通过工具层创建/改写锚点。"""
    root = env["root"]
    anchor = root / ".meta-flow" / "session-roles" / "user-tty.yaml"
    for role in ("worker", "manager"):
        monkeypatch.setenv("MF_ROLE", role)
        decision = guard.pretool_decision(_payload("Write", env["sub"], anchor))
        assert decision is not None


@pytest.mark.parametrize(
    ("category", "command"),
    [
        ("mf-cli", "mf hook session-start"),
        ("sh-c", "sh -c 'mf hook session-start'"),
        ("module", "python -m meta_flow.cli hook session-start"),
        (
            "subprocess-list",
            "python -c \"import subprocess; "
            "subprocess.run(['mf','hook','session-start'])\"",
        ),
        (
            "alias-split",
            "python -c \"from meta_flow import roles as r; "
            "getattr(r,'write_'+'anchor')('x')\"",
        ),
        ("cd-chain", "cd . && mf hook session-start"),
        (
            "env-session",
            "python -c \"from meta_flow.roles import write_anchor; "
            "write_anchor('worker', start='.', source='session-start', "
            "session_id='x')\"",
        ),
    ],
)
def test_a3_negative_matrix_entries_denied(env, monkeypatch, category, command):
    """MFP-0041 A3：入口×变形×shell×环境矩阵中的真实入口均拒绝。"""
    monkeypatch.setenv("MF_ROLE", "worker")
    assert guard.pretool_decision(_bash(command, env["sub"])) is not None, category
