"""packet 本地副本写入与 must_read 契约基线只读通道（MFP-0025）。"""

from __future__ import annotations

import pytest

from meta_flow import context, guard, req
from meta_flow.global_store import bootstrap
from meta_flow.install import install_root
from meta_flow.task import create_task, start_task
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
    return root, root / "demo-contract", sub


def _write_source(path, text="# source\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _payload(tool, cwd, path):
    return {"tool_name": tool, "cwd": str(cwd), "tool_input": {"file_path": str(path)}}


def test_worker_can_write_current_task_local_copies(tmp_path, monkeypatch):
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

    for relative in (
        ".meta-flow/handoffs/R1-P1-T001.md",
        ".meta-flow/dev-records/R1-P1-T001.md",
    ):
        assert guard.pretool_decision(_payload("Write", sub, sub / relative)) is None
    # 其他任务/其他 .meta-flow 文件仍拒绝
    assert guard.pretool_decision(
        _payload("Write", sub, sub / ".meta-flow/handoffs/R1-P1-T999.md")
    ) is not None
    assert guard.pretool_decision(
        _payload("Write", sub, sub / ".meta-flow/session-role.json")
    ) is not None


def test_expand_must_read_contract_baseline_only(tmp_path, monkeypatch):
    root, contract, sub = _env(tmp_path, monkeypatch)
    req.add_requirement(root, "登录", acceptance=["成功"])
    _write_source(contract / "improvements" / "MFP-0001.yaml", "id: MFP-0001\n")
    create_task(
        root,
        "前端任务",
        risk="low",
        delivery="frontend",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
        inputs={
            "requirements": ["REQ-0001"],
            "improvements": ["MFP-0001"],
            "standards": ["VERSION"],
        },
    )
    start_task(sub, "R1-P1-T001")

    for path in (
        "requirements/REQ-0001.md",
        "improvements/MFP-0001.yaml",
        "standards/VERSION.md",
    ):
        expanded = context.expand(sub, path, reason="packet_missing", actor="worker")
        assert expanded["bytes"] > 0
    log = (contract / "state" / "READ-LOG.ndjson").read_text(encoding="utf-8")
    assert log.count("context.expand") >= 3

    with pytest.raises(context.ContextError, match="must_read|契约基线"):
        context.expand(sub, "requirements/INDEX.md", reason="packet_missing", actor="worker")
    with pytest.raises(context.ContextError):
        context.expand(sub, "roadmap/ROADMAP.yaml", reason="packet_missing", actor="worker")


def test_readonly_expand_requires_first_executable_token(tmp_path, monkeypatch):
    """R1：只读 expand 豁免必须从首个可执行 token 起，前置命令不放宽。"""
    root, contract, sub = _env(tmp_path, monkeypatch)
    req.add_requirement(root, "登录", acceptance=["成功"])
    _write_source(contract / "improvements" / "MFP-0001.yaml", "id: MFP-0001\n")
    create_task(
        root,
        "前端任务",
        risk="low",
        delivery="frontend",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
        inputs={"requirements": ["REQ-0001"], "improvements": ["MFP-0001"]},
    )
    start_task(sub, "R1-P1-T001")
    monkeypatch.setenv("MF_ROLE", "worker")

    # 正例：首个可执行 token 是 mf / 带受控前缀或绝对路径
    assert guard._readonly_expand(
        "mf context expand improvements/MFP-0001.yaml --reason packet_missing"
    )
    assert guard._readonly_expand("/usr/local/bin/mf context expand x --reason packet_missing")
    assert guard._readonly_expand("env mf context expand x --reason packet_missing")

    # 负例：前置命令/链式/写命令后附加 expand 均不豁免
    assert not guard._readonly_expand(
        "git reset --hard src/meta_flow/task.py mf context expand"
    )
    assert not guard._readonly_expand(
        f"cat {contract / 'requirements' / 'INDEX.md'} mf context expand"
    )
    assert not guard._readonly_expand(
        f"git checkout -- {contract / 'requirements' / 'REQ-0001.md'} mf context expand"
    )
    assert not guard._readonly_expand(
        "mf context expand improvements/MFP-0001.yaml --reason packet_missing && rm -rf src"
    )

    def bash(command):
        return {"tool_name": "Bash", "cwd": str(sub), "tool_input": {"command": command}}

    # 前置 cat/git checkout 不得因附带 expand 而跳过契约读取检查
    assert (
        guard.pretool_decision(
            bash(f"cat {contract / 'requirements' / 'INDEX.md'} mf context expand")
        )
        is not None
    )
    assert (
        guard.pretool_decision(
            bash(
                f"git checkout -- {contract / 'requirements' / 'REQ-0001.md'} "
                "mf context expand"
            )
        )
        is not None
    )
    # 正常 must_read expand 仍放行，并写 READ-LOG
    assert (
        guard.pretool_decision(
            bash("mf context expand improvements/MFP-0001.yaml --reason packet_missing")
        )
        is None
    )
    context.expand(sub, "improvements/MFP-0001.yaml", reason="packet_missing", actor="worker")
    log = (contract / "state" / "READ-LOG.ndjson").read_text(encoding="utf-8")
    assert "context.expand" in log


def test_guard_treats_mf_context_expand_as_readonly(tmp_path, monkeypatch):
    root, contract, sub = _env(tmp_path, monkeypatch)
    req.add_requirement(root, "登录", acceptance=["成功"])
    _write_source(contract / "improvements" / "MFP-0001.yaml", "id: MFP-0001\n")
    create_task(
        root,
        "前端任务",
        risk="low",
        delivery="frontend",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
        inputs={"requirements": ["REQ-0001"], "improvements": ["MFP-0001"]},
    )
    start_task(sub, "R1-P1-T001")
    monkeypatch.setenv("MF_ROLE", "worker")

    def bash(command, cwd=sub):
        return {"tool_name": "Bash", "cwd": str(cwd), "tool_input": {"command": command}}

    assert (
        guard.pretool_decision(
            bash("mf context expand improvements/MFP-0001.yaml --reason packet_missing")
        )
        is None
    )
    assert (
        guard.pretool_decision(
            bash(
                f"mf context expand {contract / 'requirements' / 'REQ-0001.md'} "
                "--reason packet_missing"
            )
        )
        is None
    )
    # 链式写命令不享受只读豁免
    assert (
        guard.pretool_decision(
            bash(
                f"mf context expand improvements/MFP-0001.yaml --reason packet_missing "
                f"&& rm -rf {sub / 'src'}"
            )
        )
        is not None
    )
