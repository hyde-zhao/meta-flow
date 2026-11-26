"""CLI 冒烟测试。"""

from __future__ import annotations

import json

import pytest
import yaml

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
    assert "自动重开" in out
    assert f"mf task rework {task_id}" in out

    # rework 只允许 worker；manager 不得开始
    assert main(["task", "rework", task_id]) == 3

    monkeypatch.setenv("MF_ROLE", "worker")
    capsys.readouterr()
    assert main(["task", "rework", task_id, "--project-dir", "alpha"]) == 0
    out = capsys.readouterr().out
    assert "in_progress" in out
    assert "manager 审计通知" in out
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
    assert "未自动重开" not in out
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
