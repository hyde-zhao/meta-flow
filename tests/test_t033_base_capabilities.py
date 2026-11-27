"""T033 A1–A3：角色锚定回归、子项目任务绑定/隔离、安全类任务基线。

覆盖本任务新增的缺口修复：
- 子项目 install.yaml 丢失 workspace_root 时按父工作区解析（A1/A2）；
- contract 无法解析时 guard fail-closed（A1/A3）；
- 任务 create 强制/自动绑定 delivery，packet/prompt 显示工作目录与基准（A2）；
- cross_subproject 只读/测试例外、写拒绝（A2）；
- 安全类任务 validate/doctor/start 校验威胁模型与负向矩阵（A3）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from meta_flow import guard
from meta_flow.cli import main
from meta_flow.global_store import bootstrap
from meta_flow.install import install_root, install_worker
from meta_flow.task import (
    TaskError,
    create_task,
    load_task,
    packet_text,
    prompt_text,
    start_task,
    summary_text,
    task_security_errors,
    task_security_warnings,
    validate_task,
)
from meta_flow.workspace import (
    WorkspaceError,
    workspace_add_project,
    workspace_init,
)


def _acceptance():
    return [{"id": "A1", "method": "artifact", "expect": "完成"}]


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
    frontend = root / "frontend"
    backend = root / "backend"
    workspace_add_project(root, "frontend", "frontend")
    workspace_add_project(root, "backend", "backend")
    return {
        "root": root,
        "contract": contract,
        "frontend": frontend,
        "backend": backend,
    }


def _payload(tool, cwd, path=None, command=None):
    data = {"tool_name": tool, "cwd": str(cwd), "tool_input": {}}
    if path is not None:
        data["tool_input"]["file_path"] = str(path)
    if command is not None:
        data["tool_input"]["command"] = command
    return data


def _complete_security():
    return {
        "applies": True,
        "threat_model": {
            "assets": ["contract 真相"],
            "attackers": ["越权 worker"],
            "entry_points": ["mf task start"],
            "trust_boundary": ["guard 静态解析 vs 同用户任意代码"],
            "attacker_capabilities": ["worker shell 任意命令"],
        },
        "uncovered": ["同用户任意代码/OS 隔离不在本任务"],
        "risk_acceptor": "manager",
        "invariants": [
            {"id": "INV-1", "text": "worker 不得跨子项目读写"},
            {"id": "INV-2", "text": "无法判定时 fail-closed 拒绝"},
        ],
        "negative_matrix": [
            {"id": "N1", "category": "命令首词", "command": "echo mf", "expected": "deny"},
            {"id": "N2", "category": "前缀命令", "command": "cd x && mf", "expected": "deny"},
            {"id": "N3", "category": "参数伪装", "command": "x mf context expand", "expected": "deny"},
            {"id": "N4", "category": "操作符/替换", "command": "mf $(x)", "expected": "deny"},
            {"id": "N5", "category": "跨项目", "command": "cat ../backend/src", "expected": "deny"},
            {"id": "N6", "category": "越界", "command": "expand outside", "expected": "deny"},
            {
                "id": "N7",
                "category": "module/subprocess/list",
                "command": "python -m meta_flow.cli",
                "expected": "deny",
            },
            {
                "id": "N8",
                "category": "alias/importlib/getattr/拼接",
                "command": "importlib + getattr + 拼接",
                "expected": "deny",
            },
            {
                "id": "N9",
                "category": "cd/嵌套 shell/env/session_id",
                "command": "cd x && sh -c; env; session_id",
                "expected": "deny",
            },
        ],
        "fail_closed": True,
        "fail_closed_scope": "静态命令解析 + 会话绑定",
    }


# ---------------------------------------------------------------------------
# A1：角色/工作区绑定与 guard fail-closed
# ---------------------------------------------------------------------------


def test_unbound_subproject_install_resolves_contract_and_task_commands(env, monkeypatch):
    root, _contract, frontend = env["root"], env["contract"], env["frontend"]
    # 模拟 1.0.3 重装 worker 时漏传 --workspace-root：install.yaml 绑定为 null，
    # 但子项目仍在已注册工作区内。
    install_worker(frontend, "frontend", force=True)
    manifest = yaml.safe_load(
        (frontend / ".meta-flow" / "install.yaml").read_text(encoding="utf-8")
    )
    assert manifest["workspace_root"] is None

    result = create_task(
        root,
        "绑定回退任务",
        risk="low",
        delivery="frontend",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
    )
    task_id = result["task"]
    assert frontend in Path(str(load_task(root, task_id)[1]["project_dir"])).parents or (
        load_task(root, task_id)[1]["project_dir"] == str(frontend)
    )

    monkeypatch.chdir(frontend)
    assert main(["task", "prompt", task_id, "--project-dir", str(root)]) == 0
    assert main(["task", "show", task_id, "--project-dir", str(root)]) == 0


def test_mismatched_workspace_binding_is_rejected(env, tmp_path):
    frontend = env["frontend"]
    other = tmp_path / "other-workspace"
    other.mkdir()
    install_worker(frontend, "frontend", workspace_root=other, force=True)
    from meta_flow.workspace import resolve_contract

    with pytest.raises(WorkspaceError, match="不一致"):
        resolve_contract(frontend)


def test_guard_fails_closed_when_contract_unresolvable(tmp_path):
    sub = tmp_path / "standalone"
    (sub / ".meta-flow").mkdir(parents=True)
    (sub / "delivery.yaml").write_text("id: standalone\n", encoding="utf-8")
    (sub / ".meta-flow" / "install.yaml").write_text(
        yaml.safe_dump(
            {"schema": 1, "role": "worker", "project_dir": str(sub), "workspace_root": None},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    target = sub / "src" / "x.py"
    target.parent.mkdir()
    target.write_text("x = 1\n", encoding="utf-8")

    decision = guard.pretool_decision(_payload("Write", sub, target))
    assert decision is not None
    assert "fail-closed" in decision["hookSpecificOutput"]["permissionDecisionReason"]

    bash = guard.pretool_decision(_payload("Bash", sub, command="echo hi"))
    assert bash is not None
    assert "fail-closed" in bash["hookSpecificOutput"]["permissionDecisionReason"]

    read = guard.pretool_decision(_payload("Read", sub, target))
    assert read is not None


# ---------------------------------------------------------------------------
# A2：子项目任务绑定与隔离
# ---------------------------------------------------------------------------


def test_task_create_binds_delivery_and_displays_workdir(env, monkeypatch):
    root, contract, frontend = env["root"], env["contract"], env["frontend"]
    monkeypatch.chdir(root)
    with pytest.raises(TaskError, match="未指定 --delivery"):
        create_task(root, "无子项目", risk="low", acceptance=_acceptance())
    with pytest.raises(TaskError, match="未知子项目"):
        create_task(
            root, "未知子项目", risk="low", delivery="ghost", acceptance=_acceptance()
        )

    monkeypatch.chdir(frontend)
    result = create_task(root, "自动绑定", risk="low", acceptance=_acceptance())
    task_id = result["task"]
    _path, task = load_task(root, task_id)
    assert task["delivery"] == "frontend"
    assert task["scope"]["mode"] == "single_subproject"
    assert Path(task["project_dir"]) == frontend
    assert Path(task["allowed_paths_base"]) == frontend

    packet = packet_text(root, task_id)
    assert "- delivery: frontend" in packet
    assert f"- project_dir: {frontend}" in packet
    assert f"- allowed_paths_base: {frontend}" in packet
    prompt = prompt_text(root, task_id)
    assert "project_dir: " + str(frontend) in prompt
    summary = summary_text(task, contract)
    assert "工作目录: " + str(frontend) in summary


def test_cli_task_create_autobinds_from_subproject_cwd(env, monkeypatch):
    root, frontend = env["root"], env["frontend"]
    from meta_flow import roles

    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s-manager")
    roles.write_anchor(
        "manager", start=root, source="session-start", session_id="s-manager"
    )
    monkeypatch.chdir(frontend)
    assert (
        main(
            [
                "task",
                "create",
                "--project-dir",
                str(root),
                "--title",
                "CLI 自动绑定",
                "--risk",
                "low",
                "--acceptance",
                "完成",
            ]
        )
        == 0
    )


def test_worker_guard_blocks_sibling_project_read_write(env, monkeypatch):
    root, frontend, backend = env["root"], env["frontend"], env["backend"]
    monkeypatch.chdir(frontend)
    result = create_task(root, "前端任务", risk="low", acceptance=_acceptance())
    start_task(root, result["task"], owner="worker1")
    backend_file = backend / "src" / "main.py"
    backend_file.parent.mkdir(parents=True, exist_ok=True)
    backend_file.write_text("print('backend')\n", encoding="utf-8")

    read = guard.pretool_decision(_payload("Read", frontend, backend_file))
    assert read is not None
    write = guard.pretool_decision(_payload("Write", frontend, backend_file))
    assert write is not None
    bash_read = guard.pretool_decision(
        _payload("Bash", frontend, command="cat ../backend/src/main.py")
    )
    assert bash_read is not None


def test_cross_subproject_read_allowed_write_denied(env, monkeypatch):
    root, frontend, backend = env["root"], env["frontend"], env["backend"]
    result = create_task(
        root,
        "跨子项目只读验证",
        risk="low",
        delivery="frontend",
        scope_mode="cross_subproject",
        scope_projects=["frontend", "backend"],
        scope_operations=["read", "test"],
        scope_justification="契约联调只读验证",
        actor_role="manager",
        acceptance=_acceptance(),
    )
    start_task(root, result["task"], owner="worker1")
    backend_file = backend / "src" / "api.py"
    backend_file.parent.mkdir(parents=True, exist_ok=True)
    backend_file.write_text("print('api')\n", encoding="utf-8")

    read = guard.pretool_decision(_payload("Read", frontend, backend_file))
    assert read is None  # cross 只读例外
    write = guard.pretool_decision(_payload("Write", frontend, backend_file))
    assert write is not None
    assert "cross_subproject" in write["hookSpecificOutput"]["permissionDecisionReason"]
    bash_write = guard.pretool_decision(
        _payload("Bash", frontend, command="echo x > ../backend/src/api.py")
    )
    assert bash_write is not None


def test_cross_subproject_scope_requires_manager_and_fields(env):
    root = env["root"]
    with pytest.raises(TaskError, match="只能由 manager 创建"):
        create_task(
            root,
            "worker 跨项目",
            risk="low",
            delivery="frontend",
            scope_mode="cross_subproject",
            scope_projects=["frontend", "backend"],
            scope_operations=["read"],
            scope_justification="越权",
            actor_role="worker",
            acceptance=_acceptance(),
        )
    with pytest.raises(TaskError, match="scope.justification"):
        create_task(
            root,
            "缺少理由",
            risk="low",
            delivery="frontend",
            scope_mode="cross_subproject",
            scope_projects=["frontend", "backend"],
            scope_operations=["read"],
            actor_role="manager",
            acceptance=_acceptance(),
        )


# ---------------------------------------------------------------------------
# A3：安全类任务基线
# ---------------------------------------------------------------------------


def test_security_task_complete_fields_pass(env):
    root = env["root"]
    result = create_task(
        root,
        "安全任务",
        risk="low",
        delivery="frontend",
        security=_complete_security(),
        acceptance=_acceptance(),
    )
    task_id = result["task"]
    assert validate_task(root, task_id)["ok"] is True
    assert task_security_errors(load_task(root, task_id)[1]) == []
    assert task_security_warnings(load_task(root, task_id)[1]) == []


def test_security_task_missing_fields_rejected_at_create(env):
    root = env["root"]
    incomplete = _complete_security()
    incomplete["threat_model"].pop("trust_boundary")
    with pytest.raises(TaskError, match="安全类任务缺少必要字段"):
        create_task(
            root,
            "残缺安全任务",
            risk="low",
            delivery="frontend",
            security=incomplete,
            acceptance=_acceptance(),
        )


def test_security_task_validate_and_start_reject_incomplete(tmp_path, monkeypatch):
    home = tmp_path / "global"
    monkeypatch.setenv("META_FLOW_HOME", str(home))
    bootstrap()
    root = tmp_path / "demo"
    root.mkdir()
    install_root(root)
    workspace_init(root, "Demo")
    workspace_add_project(root, "frontend", "frontend")
    result = create_task(
        root,
        "安全任务",
        risk="low",
        delivery="frontend",
        security=_complete_security(),
        acceptance=_acceptance(),
    )
    task_id = result["task"]
    path, data = load_task(root, task_id)
    data["security"].pop("negative_matrix")
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")

    validation = validate_task(root, task_id)
    assert validation["ok"] is False
    assert any("negative_matrix" in item for item in validation["errors"])
    from meta_flow.workspace import doctor

    doctor_errors = doctor(root)
    assert any("negative_matrix" in item for item in doctor_errors)
    with pytest.raises(TaskError, match="拒绝 start"):
        start_task(root, task_id)
    assert main(["task", "validate", task_id, "--project-dir", str(root)]) == 1


def test_security_matrix_coverage_warning_not_error(env):
    root = env["root"]
    security = _complete_security()
    security["negative_matrix"] = [
        {"id": "N1", "category": "跨项目", "command": "cat ../backend", "expected": "deny"}
    ]
    result = create_task(
        root,
        "流程安全任务",
        risk="low",
        delivery="frontend",
        security=security,
        acceptance=_acceptance(),
    )
    task_id = result["task"]
    validation = validate_task(root, task_id)
    assert validation["ok"] is True
    assert any("覆盖不足" in item for item in validation["warnings"])


def test_packet_input_resolves_exact_contract_path(tmp_path, monkeypatch):
    home = tmp_path / "global"
    monkeypatch.setenv("META_FLOW_HOME", str(home))
    bootstrap()
    root = tmp_path / "demo"
    root.mkdir()
    install_root(root)
    workspace_init(root, "Demo")
    workspace_add_project(root, "frontend", "frontend")
    result = create_task(
        root,
        "输入路径解析",
        risk="low",
        delivery="frontend",
        inputs={"standards": ["standards/TASK-CARD.md"]},
        acceptance=_acceptance(),
    )
    packet = packet_text(root, result["task"])
    assert "### standards/TASK-CARD.md (standards/TASK-CARD.md)" in packet
    assert "TASK-CARD — 任务卡规范" in packet
    assert "CHG-0004 评审 NEEDS_REWORK" not in packet


# ---------------------------------------------------------------------------
# A4/A6：文档与模板收口
# ---------------------------------------------------------------------------


def test_agent_templates_require_subproject_and_security():
    from meta_flow import templates

    root = Path(__file__).resolve().parents[1]
    for name, const in (("worker", templates.AGENT_WORKER), ("manager", templates.AGENT_MANAGER)):
        repo = (root / "agents" / f"{name}.md").read_text(encoding="utf-8")
        assert repo.strip() == const.strip()
    worker = (root / "agents" / "worker.md").read_text(encoding="utf-8")
    manager = (root / "agents" / "manager.md").read_text(encoding="utf-8")
    assert "子项目绑定与安全基线" in worker
    assert "负向矩阵" in worker and "威胁模型" in worker
    assert "子项目任务绑定" in manager
    assert "mf task validate" in manager
    assert "project_dir" in manager


def test_user_manual_quickstarts_and_binding_checkpoints():
    root = Path(__file__).resolve().parents[1]
    text = (root / "USER-MANUAL.md").read_text(encoding="utf-8")
    assert "## 快速开始 1：全新项目" in text
    assert "## 快速开始 2：迁移项目" in text
    assert "--delivery backend" in text
    assert "mf task validate" in text
    assert "mf role" in text and "mf doctor" in text
    assert "git status" in text


def test_gitignore_install_mirror_block_checked_by_doctor(env):
    from meta_flow.workspace import doctor

    root, frontend = env["root"], env["frontend"]
    gitignore = frontend / ".gitignore"
    text = gitignore.read_text(encoding="utf-8")
    assert ">>> meta-flow install mirror >>>" in text
    assert doctor(root) == []

    # 移除受控块：doctor 应报告安装镜像未忽略（REQ-0013 AC5）。
    gitignore.write_text(text.replace(">>> meta-flow install mirror >>>", "# removed"), encoding="utf-8")
    errors = doctor(root)
    assert any("安装镜像块" in item for item in errors)

    # 非 git 根不要求 .gitignore（REQ-0013 AC2）。
    assert not (root / ".git").is_dir()
    assert not any(str(root) in item for item in errors if "安装镜像块" in item)


