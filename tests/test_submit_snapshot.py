"""提交快照排除 gitignored/既有未跟踪文件并可清理构建产物（MFP-0030）。"""

from __future__ import annotations

import json
import subprocess

import pytest

from meta_flow import guard
from meta_flow.global_store import bootstrap
from meta_flow.install import install_root
from meta_flow.task import TaskError, create_task, start_task, submit_task
from meta_flow.workspace import workspace_add_project, workspace_init


def _acceptance():
    return [{"id": "A1", "method": "artifact", "expect": "完成"}]


def _env(tmp_path, monkeypatch):
    home = tmp_path / "global"
    monkeypatch.setenv("META_FLOW_HOME", str(home))
    bootstrap()
    root = tmp_path / "demo"
    root.mkdir()
    install_root(root)
    workspace_init(root, "Demo")
    sub = root / "frontend"
    workspace_add_project(root, "frontend", "frontend")
    subprocess.run(["git", "init", "-b", "main"], cwd=sub, check=True, capture_output=True)
    with (sub / ".gitignore").open("a", encoding="utf-8") as handle:
        handle.write("*.egg-info/\n")
    return root, root / "demo-contract", sub


def _worker_files(contract, task_id):
    tail = task_id.rsplit("-", 1)[-1]
    bundle = contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / tail
    (bundle / "dev-record.md").write_text("# dev\n完成\n", encoding="utf-8")
    (bundle / "handoff.md").write_text("# handoff\n完成\n", encoding="utf-8")


def test_submit_allows_gitignored_build_artifacts(tmp_path, monkeypatch):
    root, contract, sub = _env(tmp_path, monkeypatch)
    create_task(
        root,
        "前端任务",
        risk="low",
        delivery="frontend",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
    )
    # task start 前已存在的未跟踪文件与构建产物
    (sub / "notes.txt").write_text("pre-existing\n", encoding="utf-8")
    egg = sub / "src" / "meta_flow.egg-info"
    egg.mkdir(parents=True)
    (egg / "PKG-INFO").write_text("before\n", encoding="utf-8")
    start_task(sub, "R1-P1-T001")

    # start 后构建产物重新生成（mtime/size 变化）、既有未跟踪文件被修改
    (egg / "PKG-INFO").write_text("rebuilt metadata\n", encoding="utf-8")
    (sub / "notes.txt").write_text("changed\n", encoding="utf-8")
    (sub / "src").mkdir(exist_ok=True)
    (sub / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")

    _worker_files(contract, "R1-P1-T001")
    data = submit_task(sub, "R1-P1-T001")
    assert data["status"] == "submitted"

    bundle = contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / "T001"
    snapshot = json.loads((bundle / "evidence" / "worktree-start.json").read_text(encoding="utf-8"))
    assert not any("egg-info" in path for path in snapshot)
    meta = json.loads(
        (bundle / "evidence" / "worktree-start-meta.json").read_text(encoding="utf-8")
    )
    assert "notes.txt" in meta["untracked"]


def test_legacy_snapshot_ignored_entries_do_not_block(tmp_path, monkeypatch):
    root, contract, sub = _env(tmp_path, monkeypatch)
    create_task(
        root,
        "前端任务",
        risk="low",
        delivery="frontend",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
    )
    start_task(sub, "R1-P1-T001")
    bundle = contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / "T001"
    snapshot_path = bundle / "evidence" / "worktree-start.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    # 旧版本快照会包含安装镜像（gitignored）条目
    snapshot[".claude/agents/worker.md"] = [1, 1]
    snapshot["CLAUDE.md"] = [1, 1]
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    (sub / ".claude" / "agents").mkdir(parents=True, exist_ok=True)
    (sub / ".claude" / "agents" / "worker.md").write_text("changed\n", encoding="utf-8")
    (sub / "CLAUDE.md").write_text("@contract\n", encoding="utf-8")

    _worker_files(contract, "R1-P1-T001")
    assert submit_task(sub, "R1-P1-T001")["status"] == "submitted"


def test_submit_still_rejects_out_of_scope_source(tmp_path, monkeypatch):
    root, contract, sub = _env(tmp_path, monkeypatch)
    create_task(
        root,
        "前端任务",
        risk="low",
        delivery="frontend",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
    )
    start_task(sub, "R1-P1-T001")
    (sub / "outside.txt").write_text("越界\n", encoding="utf-8")
    _worker_files(contract, "R1-P1-T001")
    with pytest.raises(TaskError, match="allowed_paths"):
        submit_task(sub, "R1-P1-T001")


def test_guard_allows_worker_cleaning_build_artifacts(tmp_path, monkeypatch):
    _root, _contract, sub = _env(tmp_path, monkeypatch)
    create_task(
        _root,
        "前端任务",
        risk="low",
        delivery="frontend",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
    )
    start_task(sub, "R1-P1-T001")
    monkeypatch.setenv("MF_ROLE", "worker")

    def bash(command):
        return {"tool_name": "Bash", "cwd": str(sub), "tool_input": {"command": command}}

    assert guard.pretool_decision(bash("rm -rf src/meta_flow.egg-info")) is None
    assert guard.pretool_decision(bash("rm -rf tests/fixtures")) is not None
