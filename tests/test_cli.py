"""CLI 冒烟测试。"""

from __future__ import annotations

import json
import subprocess

import pytest
import yaml

from meta_flow import state
from meta_flow.cli import main
from meta_flow.install import install_root
from meta_flow.task import (
    create_task,
    load_task,
    reject_task,
    rework_task,
    start_task,
    submit_task,
)
from meta_flow.workspace import workspace_add_project, workspace_init


def _prepare(tmp_path, monkeypatch):
    home = tmp_path / "global"
    monkeypatch.setenv("META_FLOW_HOME", str(home))
    project = tmp_path / "project"
    project.mkdir()
    return home, project


def test_cli_bootstrap_install_workspace(tmp_path, monkeypatch, capsys):
    _, project = _prepare(tmp_path, monkeypatch)
    assert main(["bootstrap"]) == 0
    assert main(["install", "claude", "--project-dir", str(project), "--init-contract"]) == 0
    assert (project / "project-contract").is_dir()
    assert (
        main(
            [
                "workspace",
                "add-project",
                "--project-dir",
                str(project),
                "--name",
                "frontend",
                "--path",
                "frontend",
            ]
        )
        == 0
    )
    assert main(["doctor", "--path", str(project)]) == 0

    capsys.readouterr()
    assert main(["workspace", "status", "--project-dir", str(project), "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["project"]["id"] == "project"
    assert status["subprojects"][0]["id"] == "frontend"

    assert main(["role", "--path", str(project)]) == 0
    assert main(["role", "--path", str(project / "frontend")]) == 0


def test_cli_improve_smoke(tmp_path, monkeypatch, capsys):
    _, project = _prepare(tmp_path, monkeypatch)
    assert main(["bootstrap"]) == 0
    assert main(["install", "claude", "--project-dir", str(project), "--init-contract"]) == 0
    assert main(["improve", "new", "--project-dir", str(project), "--title", "Add X"]) == 0

    capsys.readouterr()
    assert main(["improve", "list", "--project-dir", str(project), "--json"]) == 0
    items = json.loads(capsys.readouterr().out)
    assert items[0]["id"] == "MFP-0001"

    assert main(["improve", "validate", "--project-dir", str(project), "MFP-0001"]) == 1


def test_cli_task_smoke(tmp_path, monkeypatch, capsys):
    _, project = _prepare(tmp_path, monkeypatch)
    assert main(["bootstrap"]) == 0
    assert main(["install", "claude", "--project-dir", str(project), "--init-contract"]) == 0
    assert (
        main(
            [
                "task",
                "create",
                "--project-dir",
                str(project),
                "--title",
                "文档修正",
                "--risk",
                "low",
                "--acceptance",
                "文档更新完成",
            ]
        )
        == 0
    )

    capsys.readouterr()
    assert main(["task", "list", "--project-dir", str(project), "--json"]) == 0
    items = json.loads(capsys.readouterr().out)
    assert items[0]["id"] == "R1-P1-T001"

    assert main(["task", "show", "--project-dir", str(project), "R1-P1-T001", "--packet"]) == 0
    assert "TASK PACKET" in capsys.readouterr().out
    assert main(["task", "prompt", "--project-dir", str(project), "R1-P1-T001"]) == 0
    assert "responsible_agent: worker" in capsys.readouterr().out


def test_cli_planning_quality_smoke(tmp_path, monkeypatch, capsys):
    _, project = _prepare(tmp_path, monkeypatch)
    assert main(["bootstrap"]) == 0
    assert main(["install", "claude", "--project-dir", str(project), "--init-contract"]) == 0
    root = str(project)
    assert (
        main(
            [
                "req",
                "add",
                "--project-dir",
                root,
                "--title",
                "登录",
                "--acceptance",
                "成功登录",
            ]
        )
        == 0
    )
    assert main(["req", "trace", "--project-dir", root, "REQ-0001"]) == 0
    capsys.readouterr()
    assert main(["roadmap", "show", "--project-dir", root, "--json"]) == 0
    roadmap_data = json.loads(capsys.readouterr().out)
    assert roadmap_data["current"]["roadmap"] == "R1"

    assert (
        main(
            [
                "task",
                "create",
                "--project-dir",
                root,
                "--title",
                "实现登录",
                "--risk",
                "low",
                "--acceptance",
                "完成",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main(["task", "plan", "--project-dir", root, "--json"]) == 0
    plan_data = json.loads(capsys.readouterr().out)
    assert plan_data["ready"][0]["id"] == "R1-P1-T001"
    assert main(["task", "graph", "--project-dir", root, "--json"]) == 0
    capsys.readouterr()

    assert main(["knowledge", "add", "--project-dir", root, "--kind", "term", "--text", "契约库"]) == 0
    capsys.readouterr()
    assert main(["knowledge", "list", "--project-dir", root, "--json"]) == 0
    items = json.loads(capsys.readouterr().out)
    assert items[0]["id"] == "TERM-001"

    assert (
        main(
            [
                "verify",
                "record",
                "--project-dir",
                root,
                "--layer",
                "implementation",
                "--scope",
                "登录",
                "--result",
                "PASS",
                "--requirement",
                "REQ-0001",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main(["verify", "list", "--project-dir", root, "--json"]) == 0
    records = json.loads(capsys.readouterr().out)
    assert records[0]["id"] == "VR-0001"

    assert main(["bug", "add", "--project-dir", root, "--title", "登录报错", "--severity", "major"]) == 0
    capsys.readouterr()
    assert main(["bug", "list", "--project-dir", root, "--json"]) == 0
    bugs = json.loads(capsys.readouterr().out)
    assert bugs[0]["id"] == "BUG-0001"

    assert main(["archive", "list", "--project-dir", root, "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []
    assert main(["log", "--project-dir", root, "--limit", "5", "--json"]) == 0
    logs = json.loads(capsys.readouterr().out)
    assert logs
    assert main(["doctor", "--path", root]) == 0


def test_cli_req_list_scopes_current_roadmap(tmp_path, monkeypatch, capsys):
    _, project = _prepare(tmp_path, monkeypatch)
    assert main(["bootstrap"]) == 0
    assert main(["install", "claude", "--project-dir", str(project), "--init-contract"]) == 0
    root = str(project)
    assert main(["req", "add", "--project-dir", root, "--title", "当前", "--acceptance", "ok"]) == 0
    assert (
        main(
            [
                "req",
                "add",
                "--project-dir",
                root,
                "--title",
                "下一版",
                "--roadmap",
                "R2",
                "--acceptance",
                "ok",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main(["req", "list", "--project-dir", root, "--json"]) == 0
    current = json.loads(capsys.readouterr().out)
    assert [item["id"] for item in current] == ["REQ-0001"]
    assert main(["req", "list", "--project-dir", root, "--all", "--json"]) == 0
    all_items = json.loads(capsys.readouterr().out)
    assert [item["id"] for item in all_items] == ["REQ-0001", "REQ-0002"]


def test_cli_install_status_uninstall(tmp_path, monkeypatch, capsys):
    _, project = _prepare(tmp_path, monkeypatch)
    assert main(["install", "claude", "--project-dir", str(project)]) == 0

    capsys.readouterr()
    assert main(["status", "--path", str(project), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["role"] == "manager"

    assert main(["uninstall", "claude", "--project-dir", str(project)]) == 0
    assert not (project / ".claude" / "agents" / "manager.md").exists()
    assert not (project / ".meta-flow" / "install.yaml").exists()


def test_cli_doctor_global(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    assert main(["bootstrap"]) == 0
    assert main(["doctor", "--global"]) == 0


def test_cli_role_unbound(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    assert main(["role", "--path", str(tmp_path / "empty")]) == 2


@pytest.mark.parametrize("agent", ["manager", "maintainer"])
def test_cli_workspace_init_bootstrap_without_mf_role(
    tmp_path, monkeypatch, capsys, agent
):
    _, project = _prepare(tmp_path, monkeypatch)
    assert main(["bootstrap"]) == 0
    install_root(project, agent=agent)
    # 首次初始化时没有 workspace.yaml，且不依赖手工 MF_ROLE
    monkeypatch.delenv("MF_ROLE", raising=False)
    monkeypatch.chdir(project)
    capsys.readouterr()
    assert (
        main(
            [
                "workspace",
                "init",
                "--project-dir",
                ".",
                "--name",
                "Bootstrap App",
                "--roadmap",
                "R0",
                "--phase",
                "P4",
                "--version",
                "0.1.1",
            ]
        )
        == 0
    )
    contract = project / "bootstrap-app-contract"
    current = json.loads((contract / "state" / "current.json").read_text(encoding="utf-8"))
    assert (current["roadmap"], current["phase"], current["version"]) == ("R0", "P4", "0.1.1")
    assert main(["doctor", "--path", str(project)]) == 0

    capsys.readouterr()
    assert main(["status", "--path", str(project), "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["project"]["id"] == "bootstrap-app"
    assert status["contract"]["dir"] == str(contract)


def test_cli_explicit_role_overrides_directory_for_workspace(tmp_path, monkeypatch, capsys):
    _, project = _prepare(tmp_path, monkeypatch)
    assert main(["bootstrap"]) == 0
    install_root(project)
    workspace_init(project, "Demo App")
    monkeypatch.chdir(project)
    monkeypatch.delenv("MF_ROLE", raising=False)
    capsys.readouterr()
    assert main(["workspace", "status", "--project-dir", ".", "--json"]) == 0

    # 显式 MF_ROLE 优先于目录推导：maintainer 不能借 workspace 根执行 workspace 命令
    monkeypatch.setenv("MF_ROLE", "maintainer")
    assert main(["workspace", "status", "--project-dir", ".", "--json"]) == 3


def _acceptance():
    return [{"id": "A1", "method": "artifact", "expect": "完成"}]


def test_cli_worker_task_scope_requires_project_dir(tmp_path, monkeypatch, capsys):
    _, project = _prepare(tmp_path, monkeypatch)
    assert main(["bootstrap"]) == 0
    install_root(project)
    workspace_init(project, "Demo")
    workspace_add_project(project, "alpha", "alpha")
    workspace_add_project(project, "beta", "beta")
    create_task(
        project, "alpha 任务", risk="low", delivery="alpha", acceptance=_acceptance()
    )
    create_task(
        project, "beta 任务", risk="low", delivery="beta", acceptance=_acceptance()
    )

    monkeypatch.chdir(project)
    monkeypatch.setenv("MF_ROLE", "worker")
    # 无交付根绑定且未提供 --project-dir：rc=3（MFP-0012 E1）
    assert main(["task", "list", "--json"]) == 3
    assert main(["task", "show", "R1-P1-T001", "--packet"]) == 3

    # 显式 --project-dir 绑定 alpha：只看到/操作 alpha 的任务（E2）
    capsys.readouterr()
    assert main(["task", "list", "--project-dir", "alpha", "--json"]) == 0
    items = json.loads(capsys.readouterr().out)
    assert [item["id"] for item in items] == ["R1-P1-T001"]
    assert main(["task", "show", "--project-dir", "alpha", "R1-P1-T001"]) == 0
    assert main(["task", "show", "--project-dir", "alpha", "R1-P1-T002"]) == 3


def test_cli_status_reports_context_boundary(tmp_path, monkeypatch, capsys):
    _, project = _prepare(tmp_path, monkeypatch)
    assert main(["bootstrap"]) == 0
    install_root(project)
    workspace_init(project, "Demo")
    capsys.readouterr()
    assert main(["status", "--path", str(project)]) == 0
    out = capsys.readouterr().out
    assert "上下文: manager 预算 12 文件/131072B" in out
    assert "可读区:" in out
    assert "评审门:" in out
    assert "contract/tasks" not in out


def test_cli_workspace_attach_smoke(tmp_path, monkeypatch, capsys):
    _, project = _prepare(tmp_path, monkeypatch)
    assert main(["bootstrap"]) == 0
    install_root(project)
    workspace_init(project, "Demo", roadmap="R0", phase="P4", version="1.0.0")
    (project / ".meta-flow" / "workspace.yaml").unlink()
    (project / "mf.workspace.yaml").unlink()

    capsys.readouterr()
    assert (
        main(
            [
                "workspace",
                "attach",
                "--project-dir",
                str(project),
                "--name",
                "Demo",
                "--contract-dir",
                "demo-contract",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "已接入契约库" in out
    assert "R0/P4 @ 1.0.0" in out
    assert main(["doctor", "--path", str(project)]) == 0


def test_cli_worker_context_show_expand_scoped(tmp_path, monkeypatch, capsys):
    _, project = _prepare(tmp_path, monkeypatch)
    assert main(["bootstrap"]) == 0
    install_root(project)
    workspace_init(project, "Demo")
    workspace_add_project(project, "alpha", "alpha")
    create_task(
        project,
        "alpha 任务",
        risk="low",
        delivery="alpha",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
    )
    start_task(project / "alpha", "R1-P1-T001")
    contract = project / "demo-contract"
    bundle = contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / "T001"
    (bundle / "evidence").mkdir(parents=True, exist_ok=True)
    large = bundle / "evidence" / "large.log"
    large.write_text("x" * (70 * 1024), encoding="utf-8")

    monkeypatch.chdir(project / "alpha")
    monkeypatch.setenv("MF_ROLE", "worker")
    capsys.readouterr()
    assert main(["context", "show"]) == 0
    assert "任务 bundle 文件" in capsys.readouterr().out
    assert (
        main(["context", "expand", str(large), "--reason", "packet_missing"]) == 0
    )
    assert "x" * 100 in capsys.readouterr().out

    # deny 区不放宽
    assert (
        main(
            ["context", "expand", "requirements/INDEX.md", "--reason", "packet_missing"]
        )
        != 0
    )


def test_cli_task_rework_and_manager_audit(tmp_path, monkeypatch, capsys):
    _, project = _prepare(tmp_path, monkeypatch)
    assert main(["bootstrap"]) == 0
    install_root(project)
    workspace_init(project, "Demo")
    workspace_add_project(project, "alpha", "alpha")
    result = create_task(
        project,
        "alpha 返工",
        risk="medium",
        delivery="alpha",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
    )
    task_id, review_id = result["task"], result["review_task"]
    contract = project / "demo-contract"
    start_task(project, task_id)
    bundle = contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / "T001"
    (bundle / "dev-record.md").write_text("# dev\n完成\n", encoding="utf-8")
    (bundle / "handoff.md").write_text("# handoff\n完成\n", encoding="utf-8")
    submit_task(project, task_id)
    start_task(project, review_id)
    review_bundle = contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / "T002"
    (review_bundle / "review.md").write_text(
        "# review\nverdict: NEEDS_REWORK\n", encoding="utf-8"
    )
    (review_bundle / "review-handoff.md").write_text(
        "\n".join(
            [
                "# review handoff",
                "> verdict: NEEDS_REWORK",
                "> rework_scope: in-scope",
                "> rework_requires: none",
                "> rework_summary: {reason: 验收未满足, risk: 返工风险, "
                "impact: 交付不达标, expectation: 整改后达标}",
                "",
                "## 必须整改项",
                "",
                "| ID | 文件/行 | 要求 | 验收方法 |",
                "|---|---|---|---|",
                "| R1 | src/app.py:1 | 整改 | pytest |",
                "",
            ]
        ),
        encoding="utf-8",
    )
    submit_task(project, review_id)

    monkeypatch.chdir(project)
    monkeypatch.setenv("MF_ROLE", "manager")
    capsys.readouterr()
    assert main(["task", "accept", review_id, "--verdict", "NEEDS_REWORK"]) == 0
    out = capsys.readouterr().out
    assert "自动回流" in out
    assert f"mf task rework {task_id}" in out

    # rework 只允许 worker；manager 不得开始
    assert main(["task", "rework", task_id]) == 3

    monkeypatch.setenv("MF_ROLE", "worker")
    capsys.readouterr()
    assert main(["task", "rework", task_id, "--project-dir", "alpha"]) == 0
    out = capsys.readouterr().out
    assert "in_progress" in out
    assert "ledger task.rework 已记录" in out
    _, task = load_task(project, task_id)
    assert task["status"] == "in_progress"
    assert task["rework"]["review_task"] == review_id
    assert task["rework"]["lease"] == task["lease"]["expires_at"]


def test_cli_task_accept_while_rework_in_progress(tmp_path, monkeypatch, capsys):
    _, project = _prepare(tmp_path, monkeypatch)
    assert main(["bootstrap"]) == 0
    install_root(project)
    workspace_init(project, "Demo")
    workspace_add_project(project, "alpha", "alpha")
    result = create_task(
        project,
        "alpha 先返工后接受",
        risk="medium",
        delivery="alpha",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
    )
    task_id, review_id = result["task"], result["review_task"]
    contract = project / "demo-contract"
    start_task(project, task_id)
    bundle = contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / "T001"
    (bundle / "dev-record.md").write_text("# dev\n完成\n", encoding="utf-8")
    (bundle / "handoff.md").write_text("# handoff\n完成\n", encoding="utf-8")
    submit_task(project, task_id)
    start_task(project, review_id)
    review_bundle = contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / "T002"
    (review_bundle / "review.md").write_text(
        "# review\nverdict: NEEDS_REWORK\n", encoding="utf-8"
    )
    (review_bundle / "review-handoff.md").write_text(
        "\n".join(
            [
                "# review handoff",
                "> verdict: NEEDS_REWORK",
                "> rework_scope: in-scope",
                "> rework_requires: none",
                "> rework_summary: {reason: 验收未满足, risk: 返工风险, "
                "impact: 交付不达标, expectation: 整改后达标}",
                "",
                "## 必须整改项",
                "",
                "| ID | 文件/行 | 要求 | 验收方法 |",
                "|---|---|---|---|",
                "| R1 | src/app.py:1 | 整改 | pytest |",
                "",
            ]
        ),
        encoding="utf-8",
    )
    submit_task(project, review_id)
    reject_task(project, task_id, "manager 先退回返工")
    rework_task(project, task_id)

    monkeypatch.chdir(project)
    monkeypatch.setenv("MF_ROLE", "manager")
    capsys.readouterr()
    assert main(["task", "accept", review_id, "--verdict", "NEEDS_REWORK"]) == 0
    out = capsys.readouterr().out
    assert "已在返工中" in out
    assert "未自动回流" not in out
    _, task = load_task(project, task_id)
    assert task["status"] == "in_progress"
    assert task["next_owner"] == "worker"
    assert task["lease"] is not None


def test_cli_task_start_recovers_legacy_stale_rework(tmp_path, monkeypatch, capsys):
    _, project = _prepare(tmp_path, monkeypatch)
    assert main(["bootstrap"]) == 0
    install_root(project)
    workspace_init(project, "Demo")
    workspace_add_project(project, "alpha", "alpha")
    result = create_task(
        project,
        "alpha 旧卡",
        risk="medium",
        delivery="alpha",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
    )
    task_id = result["task"]
    contract = project / "demo-contract"
    start_task(project, task_id)
    bundle = contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / "T001"
    (bundle / "dev-record.md").write_text("# dev\n完成\n", encoding="utf-8")
    (bundle / "handoff.md").write_text("# handoff\n完成\n", encoding="utf-8")
    submit_task(project, task_id)

    task_yaml = bundle / "TASK.yaml"
    task_data = yaml.safe_load(task_yaml.read_text(encoding="utf-8"))
    task_data.update(
        {
            "status": "rejected",
            "review_verdict": "NEEDS_REWORK",
            "lease": None,
        }
    )
    task_yaml.write_text(
        yaml.safe_dump(task_data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )

    monkeypatch.chdir(project)
    monkeypatch.setenv("MF_ROLE", "worker")
    capsys.readouterr()
    assert main(["task", "start", task_id, "--project-dir", "alpha"]) == 0
    out = capsys.readouterr().out
    assert "in_progress" in out
    _, task = load_task(project, task_id)
    assert task["status"] == "in_progress"
    assert task["review_verdict"] is None


def test_cli_bootstrap_force_upgrade_force_preserve_contract(tmp_path, monkeypatch):
    """BUG-0015 CLI 端到端：bootstrap --force 与 upgrade --force 不覆盖 contract。"""
    home, project = _prepare(tmp_path, monkeypatch)
    assert main(["bootstrap"]) == 0
    assert (
        main(["install", "claude", "--project-dir", str(project), "--init-contract"])
        == 0
    )
    contract = project / "project-contract"
    custom_standard = "# 项目自定义标准\n\n保持不动。\n"
    custom_policy = "# 项目自定义策略\nschema: 1\ntiers:\n  hot:\n    - state/current.json\n"
    custom_improvements = "# 项目自定义改进包说明\n"
    (contract / "standards" / "CONTEXT.md").write_text(custom_standard, encoding="utf-8")
    (contract / "policies" / "CONTEXT-POLICY.yaml").write_text(custom_policy, encoding="utf-8")
    (contract / "improvements" / "README.md").write_text(custom_improvements, encoding="utf-8")
    phase_plan = contract / "roadmap" / "R1" / "phases" / "P1" / "PLAN.md"

    # 先做一次常规升级稳定 contract 状态，再提交基线，便于校验后无意外改动
    assert main(["upgrade", "--project-dir", str(project)]) == 0
    subprocess.run(["git", "-C", str(contract), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(contract),
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "baseline",
        ],
        check=True,
        capture_output=True,
    )

    # bootstrap --force 只刷新全局模板库，不触碰 contract
    assert main(["bootstrap", "--force"]) == 0
    assert (contract / "standards" / "CONTEXT.md").read_text(encoding="utf-8") == custom_standard
    assert (contract / "policies" / "CONTEXT-POLICY.yaml").read_text(encoding="utf-8") == custom_policy
    assert (contract / "improvements" / "README.md").read_text(encoding="utf-8") == custom_improvements

    # 模拟全局安装镜像模板更新后执行 upgrade --force
    global_agent = home / "templates" / "agents" / "manager.md"
    global_agent.parent.mkdir(parents=True, exist_ok=True)
    global_agent.write_text("# 全局 agent 模板更新\n", encoding="utf-8")
    mirror = project / ".claude" / "agents" / "manager.md"
    old_mirror = mirror.read_text(encoding="utf-8")

    assert main(["upgrade", "--project-dir", str(project), "--force"]) == 0

    # contract 自定义内容保持不变，git status 无非预期改动
    assert (contract / "standards" / "CONTEXT.md").read_text(encoding="utf-8") == custom_standard
    assert (contract / "policies" / "CONTEXT-POLICY.yaml").read_text(encoding="utf-8") == custom_policy
    assert (contract / "improvements" / "README.md").read_text(encoding="utf-8") == custom_improvements
    assert phase_plan.is_file()
    status = subprocess.run(
        ["git", "-C", str(contract), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert status == ""

    # 安装镜像仍然更新并保留备份
    assert mirror.read_text(encoding="utf-8") == "# 全局 agent 模板更新\n"
    assert mirror.with_suffix(mirror.suffix + ".bak").read_text(encoding="utf-8") == old_mirror


def test_cli_local_mfp_channel_and_guard_log_query(tmp_path, monkeypatch, capsys):
    _, project = _prepare(tmp_path, monkeypatch)
    assert main(["bootstrap"]) == 0
    install_root(project)
    workspace_init(project, "Demo")
    workspace_add_project(project, "alpha", "alpha")

    monkeypatch.chdir(project / "alpha")
    monkeypatch.setenv("MF_ROLE", "worker")
    capsys.readouterr()
    assert main(["improve", "new", "--local", "--title", "本地改进"]) == 0
    mfp = project / "alpha" / ".meta-flow" / "improvements" / "MFP-0001.yaml"
    assert mfp.is_file()
    log = project / "demo-contract" / "state" / "READ-LOG.ndjson"
    assert "mf improve new --local" in log.read_text(encoding="utf-8")

    # manager 可查询 guard 审计（tool/decision/task）
    monkeypatch.chdir(project)
    monkeypatch.setenv("MF_ROLE", "manager")
    capsys.readouterr()
    assert main(["context", "log", "--project-dir", str(project), "--json"]) == 0
    records = json.loads(capsys.readouterr().out)
    assert any(item.get("tool") == "mf improve new --local" for item in records)


def test_cli_task_review_rework_prompt_and_state(tmp_path, monkeypatch, capsys):
    """T019 关键链路：review prompt 下一环节、NEEDS_REWORK 自动回流与 rework state。"""
    _, project = _prepare(tmp_path, monkeypatch)
    assert main(["bootstrap"]) == 0
    install_root(project)
    workspace_init(project, "Demo")
    workspace_add_project(project, "alpha", "alpha")
    result = create_task(
        project,
        "alpha 任务",
        risk="medium",
        delivery="alpha",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
    )
    task_id, review_id = result["task"], result["review_task"]
    contract = project / "demo-contract"
    start_task(project, task_id)
    bundle = contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / "T001"
    (bundle / "dev-record.md").write_text("# dev\n完成\n", encoding="utf-8")
    (bundle / "handoff.md").write_text("# handoff\n完成\n", encoding="utf-8")
    submit_task(project, task_id)
    start_task(project, review_id)

    # review in_progress：prompt 明确 reviewer 职责与 rework_scope 声明
    capsys.readouterr()
    assert main(["task", "prompt", "--project-dir", str(project), review_id]) == 0
    out = capsys.readouterr().out
    assert "kind: review" in out
    assert "status: in_progress" in out
    assert "responsible_agent: worker" in out
    assert "review-handoff.md" in out
    assert "rework_scope: in-scope|out-of-scope|disputed" in out

    # review 在评审中：实现任务的 prompt 指向关联 review 任务（下一环节明确）
    capsys.readouterr()
    assert main(["task", "prompt", "--project-dir", str(project), task_id]) == 0
    out = capsys.readouterr().out
    assert f"review_task: {review_id}" in out
    assert "kind: review" in out

    review_bundle = contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / "T002"
    (review_bundle / "review.md").write_text(
        "# review\nverdict: NEEDS_REWORK\n", encoding="utf-8"
    )
    (review_bundle / "review-handoff.md").write_text(
        "\n".join(
            [
                "# review handoff",
                "> verdict: NEEDS_REWORK",
                "> rework_scope: in-scope",
                "> rework_requires: none",
                "> rework_summary: {reason: 验收未满足, risk: 返工风险, "
                "impact: 交付不达标, expectation: 整改后达标}",
                "",
                "## 必须整改项",
                "",
                "| ID | 文件/行 | 要求 | 验收方法 |",
                "|---|---|---|---|",
                "| R1 | src/app.py:1 | 整改 | pytest |",
                "",
            ]
        ),
        encoding="utf-8",
    )
    submit_task(project, review_id)

    # review submitted：prompt 指向 manager 验收，不留在空泛“等待处理”
    capsys.readouterr()
    assert main(["task", "prompt", "--project-dir", str(project), review_id]) == 0
    out = capsys.readouterr().out
    assert "responsible_agent: manager" in out
    assert "status: submitted" in out
    assert f"mf task accept {review_id}" in out

    # 评审已提交后：NEEDS_REWORK 在 submit 时自动回流，实现任务 prompt 直接指向返工
    capsys.readouterr()
    assert main(["task", "prompt", "--project-dir", str(project), task_id]) == 0
    out = capsys.readouterr().out
    assert "status: rework" in out
    assert "next_owner: worker" in out
    assert f"mf task rework {task_id}" in out

    monkeypatch.setenv("MF_ROLE", "manager")
    capsys.readouterr()
    assert (
        main(
            [
                "task",
                "accept",
                "--project-dir",
                str(project),
                review_id,
                "--verdict",
                "NEEDS_REWORK",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "已自动回流" in out
    assert f"mf task rework {task_id}" in out

    # 重开后的 task prompt：next_owner=worker，明确只能用 mf task rework 开始
    capsys.readouterr()
    assert main(["task", "prompt", "--project-dir", str(project), task_id]) == 0
    out = capsys.readouterr().out
    assert "status: rework" in out
    assert "next_owner: worker" in out
    assert f"mf task rework {task_id}" in out
    assert "task.rework" in out

    _, task = load_task(project, task_id)
    assert task["status"] == "rework"
    assert task["next_owner"] == "worker"
    assert task["lease"] is None
    assert task["rework"]["review_task"] == review_id
    assert "lease" in task["rework"]

    # worker 通过 mf task rework 开始后进入 in_progress
    monkeypatch.setenv("MF_ROLE", "worker")
    capsys.readouterr()
    assert main(["task", "rework", task_id, "--project-dir", str(project / "alpha")]) == 0
    out = capsys.readouterr().out
    assert "in_progress" in out
    assert "ledger task.rework 已记录" in out
    _, task = load_task(project, task_id)
    assert task["status"] == "in_progress"
    assert task["lease"] is not None
    assert task["rework"]["lease"] == task["lease"]["expires_at"]


def test_cli_release_freeze_stage_policy(tmp_path, monkeypatch, capsys):
    """A2 CLI 证据：P1 禁止冻结；P4 active 修复可冻结（BUG-0016）。"""
    _, project = _prepare(tmp_path, monkeypatch)
    assert main(["bootstrap"]) == 0
    assert (
        main(["install", "claude", "--project-dir", str(project), "--init-contract"])
        == 0
    )
    contract = project / "project-contract"

    # P1 active：拒绝并提示阶段门；--force 也不能绕过
    capsys.readouterr()
    assert (
        main(
            [
                "release",
                "freeze",
                "--project-dir",
                str(project),
                "--version",
                "1.0.0",
                "--force",
                "--reason",
                "尝试绕过",
                "--approved-by",
                "user",
            ]
        )
        == 1
    )
    err = capsys.readouterr().err
    assert "P1" in err
    assert "不允许冻结发布" in err

    # P4 active：修复/补丁随时可冻结
    current = state.read_current(contract)
    current.update({"phase": "P4", "phase_status": "active"})
    state.write_current(contract, current)
    capsys.readouterr()
    assert (
        main(
            [
                "release",
                "freeze",
                "--project-dir",
                str(project),
                "--version",
                "1.0.1",
                "--note",
                "P4 patch",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "已冻结: 1.0.1" in out
    assert "阶段: P4/active" in out
    assert (contract / "release" / "RELEASE-1.0.1.yaml").is_file()


def test_cli_version_flag_matches_source_constant(capsys):
    """MFP-0028：mf --version 输出来自源码版本常量，不得停留旧版本。"""
    import meta_flow

    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"mf {meta_flow.__version__}"


def test_cli_release_check_detects_drift(tmp_path, monkeypatch, capsys):
    """A2 CLI 证据：release check 一致时 0，源码版本漂移时非零并指出字段。"""
    _, project = _prepare(tmp_path, monkeypatch)
    assert main(["bootstrap"]) == 0
    assert main(["install", "claude", "--project-dir", str(project), "--init-contract"]) == 0
    contract = project / "project-contract"
    current = state.read_current(contract)
    current.update({"phase": "P4", "phase_status": "active"})
    state.write_current(contract, current)

    delivery = tmp_path / "delivery"
    (delivery / "src" / "meta_flow").mkdir(parents=True)
    source = delivery / "src" / "meta_flow" / "__init__.py"
    source.write_text('__version__ = "1.0.1"\n', encoding="utf-8")
    (delivery / "pyproject.toml").write_text(
        '[project]\nname = "meta-flow"\nversion = "1.0.1"\n', encoding="utf-8"
    )
    (delivery / "delivery.yaml").write_text("id: meta-flow\nversion: '1.0.1'\n", encoding="utf-8")
    (delivery / "RELEASE-NOTES.md").write_text(
        "# 发布说明\n\n## 1.0.1（测试）\n", encoding="utf-8"
    )

    capsys.readouterr()
    assert (
        main(
            [
                "release",
                "freeze",
                "--project-dir",
                str(project),
                "--version",
                "1.0.1",
                "--source-dir",
                str(delivery),
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        main(
            [
                "release",
                "check",
                "--project-dir",
                str(project),
                "--version",
                "1.0.1",
                "--source-dir",
                str(delivery),
                "--json",
            ]
        )
        == 0
    )
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True, data["errors"]

    # MFP-0028 复发场景：源码版本常量仍是 0.1.1
    source.write_text('__version__ = "0.1.1"\n', encoding="utf-8")
    capsys.readouterr()
    assert (
        main(
            [
                "release",
                "check",
                "--project-dir",
                str(project),
                "--version",
                "1.0.1",
                "--source-dir",
                str(delivery),
            ]
        )
        == 1
    )
    err = capsys.readouterr().err
    assert "source_version" in err
