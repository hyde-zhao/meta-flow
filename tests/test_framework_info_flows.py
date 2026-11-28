"""WP-F2F3 / REQ-0018：REQ/MFP/BUG 信息流闭环与负向矩阵（T038 A1）。

覆盖任务卡 negative_matrix：
- N1 用户确认：external BUG 缺 --confirmed-by / 角色冒充确认人 → deny
- N2 自验自关：verification BUG 修复者本人 verify/close → deny
- N3 MFP 越权：生产项目角色归档/同步 → deny
- N4 跨项目：worker 读写兄弟子项目 → deny（guard）
- N5 状态篡改：直接改 state → deny；绕过 CLI 的 closed 缺确认 → 审计
- N6 版本隔离：worker 读其他 R 流程文件 → deny
"""

from __future__ import annotations

import json

import pytest
import yaml

from meta_flow import bug, context, guard, improve, req
from meta_flow.cli import main
from meta_flow.global_store import bootstrap
from meta_flow.install import install_root, install_worker
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
    install_worker(sub, "frontend", workspace_root=root)
    return root, root / "demo-contract", sub


def _fill_mfp(path, **overrides):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data.update(
        {
            "problem": "工具缺口",
            "context": {
                "scenario": "worker 需要 X",
                "reproduction": ["运行 mf X"],
                "expected": "正常",
                "actual": "失败",
                "evidence": [{"path": "logs/x.log", "note": "输出"}],
                "affected": ["cli"],
            },
            "acceptance": [{"id": "A1", "method": "automated", "expect": "exit_code=0"}],
            "testing_plan": "uv run pytest",
            "privacy": {"sanitized": True, "removed": []},
        }
    )
    data.update(overrides)
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return data


def _ledger(contract):
    return [
        json.loads(line)
        for line in (contract / "state" / "ledger.ndjson").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# ---------------------------------------------------------------- REQ triage


def test_req_triage_states_and_ledger(tmp_path, monkeypatch):
    root, contract, _sub = _env(tmp_path, monkeypatch)
    item = req.add_requirement(root, "登录", acceptance=["成功"])
    assert item["status"] == "proposed"

    accepted = req.triage_requirement(root, item["id"], decision="accepted", next_step="design")
    assert accepted["status"] == "accepted"
    assert accepted["assessment"]["next_step"] == "design"
    assert any(
        event.get("event") == "req.triaged" and event.get("decision") == "accepted"
        for event in _ledger(contract)
    )

    with pytest.raises(req.ReqError):
        req.triage_requirement(root, item["id"], decision="accepted")
    with pytest.raises(req.ReqError):
        req.triage_requirement(root, item["id"], decision="rejected", reason="")


# ---------------------------------------------------------------- MFP 信息流


def test_mfp_local_id_archive_index_sync(tmp_path, monkeypatch):
    root, contract, sub = _env(tmp_path, monkeypatch)
    local = improve.new_improvement(sub, "worker 工具缺口", local=True)
    assert local.stem == "MFP-demo-0001"
    _fill_mfp(local)
    improve.submit_improvement(sub, "MFP-demo-0001")

    source = tmp_path / "source"
    source.mkdir()
    (source / "pyproject.toml").write_text("[project]\nname='meta-flow'\n", encoding="utf-8")
    improve.archive_improvement("demo/MFP-demo-0001", source=source)
    assert (source / "improvements" / "archive" / "MFP-demo-0001.yaml").is_file()
    index_path = source / "improvements" / "archive" / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert index["mfps"][0]["id"] == "MFP-demo-0001"
    assert index["mfps"][0]["status"] == "archived"

    state = improve.sync_improvements(root, from_path=index_path)
    assert state["mfps"]["MFP-demo-0001"]["status"] == "archived"
    state_path = root / ".meta-flow" / "improvements" / "state.json"
    assert state_path.is_file()
    assert any(event.get("event") == "mfp.synced" for event in _ledger(contract))


def test_mfp_archive_sync_denied_for_non_maintainer(tmp_path, monkeypatch):
    root, _contract, sub = _env(tmp_path, monkeypatch)
    local = improve.new_improvement(sub, "工具缺口", local=True)
    _fill_mfp(local)
    improve.submit_improvement(sub, "MFP-demo-0001")
    source = tmp_path / "source"
    source.mkdir()
    (source / "pyproject.toml").write_text("[project]\nname='meta-flow'\n", encoding="utf-8")

    for role in ("manager", "designer", "worker"):
        with pytest.raises(improve.ImproveError) as exc:
            improve.archive_improvement("demo/MFP-demo-0001", source=source, actor_role=role)
        assert exc.value.code == 3
    for role in ("manager", "worker", "designer"):
        with pytest.raises(improve.ImproveError) as exc:
            improve.sync_improvements(root, from_path=tmp_path / "missing.json", actor_role=role)
        assert exc.value.code == 3

    # CLI：manager 执行 improve sync 被角色门拒绝
    assert main(
        ["improve", "sync", "--project-dir", str(root), "--source", str(source)]
    ) == 3


# ---------------------------------------------------------------- BUG external


def test_external_bug_requires_user_confirmation(tmp_path, monkeypatch, capsys):
    root, _contract, _sub = _env(tmp_path, monkeypatch)
    item = bug.add_bug(root, "试运行缺陷", severity="major")
    bug.update_bug(root, item["id"], status="fixed", fix_owner="worker-a")
    verified = bug.verify_bug(root, item["id"], by="verifier-a")
    assert verified["status"] == "pending_user_close"

    with pytest.raises(bug.BugError):
        bug.close_bug(root, item["id"], verification="通过")
    with pytest.raises(bug.BugError):
        bug.close_bug(root, item["id"], verification="通过", confirmed_by="manager", note="ok")
    with pytest.raises(bug.BugError):
        bug.close_bug(root, item["id"], verification="通过", confirmed_by="alice")

    closed = bug.close_bug(
        root, item["id"], verification="通过", confirmed_by="alice", note="用户确认关闭"
    )
    assert closed["status"] == "closed"
    assert closed["closure_type"] == "manager_user"
    assert closed["confirmation"]["confirmed_by"] == "alice"

    # CLI 负例：缺 --confirmed-by 拒绝（退出码 3）
    item2 = bug.add_bug(root, "第二个试运行缺陷")
    bug.update_bug(root, item2["id"], status="fixed")
    bug.verify_bug(root, item2["id"], by="verifier-a")
    capsys.readouterr()
    assert (
        main(
            [
                "bug",
                "close",
                item2["id"],
                "--project-dir",
                str(root),
                "--verification",
                "通过",
            ]
        )
        == 3
    )
    err = capsys.readouterr().err
    assert "--confirmed-by" in err or "确认人" in err


# ---------------------------------------------------------------- BUG verification


def test_verification_bug_viewer_close_and_self_close_denied(tmp_path, monkeypatch):
    root, contract, _sub = _env(tmp_path, monkeypatch)
    item = bug.add_bug(
        root,
        "内部缺陷",
        flow="verification",
        subproject="frontend",
        found_by="worker-a",
    )
    assert item["flow"] == "verification" and item["scope"] == "same_subproject"
    bug.update_bug(root, item["id"], status="fixed", fix_owner="worker-a")

    with pytest.raises(bug.BugError):
        bug.verify_bug(root, item["id"], by="worker-a")
    verified = bug.verify_bug(root, item["id"], by="worker-b")
    assert verified["status"] == "verified"

    with pytest.raises(bug.BugError):
        bug.close_bug(root, item["id"], verification="复验通过", by="worker-a")
    closed = bug.close_bug(root, item["id"], verification="复验通过", by="worker-b")
    assert closed["status"] == "closed"
    assert closed["closure_type"] == "viewer"
    assert closed["verified_by"] == "worker-b"

    events = [event for event in _ledger(contract) if event.get("event") == "bug.closed"]
    assert events and events[-1]["closure_type"] == "viewer"


def test_verification_bug_requires_same_subproject_and_escalates(tmp_path, monkeypatch):
    root, _contract, _sub = _env(tmp_path, monkeypatch)
    with pytest.raises(bug.BugError):
        bug.add_bug(root, "缺子项目", flow="verification")
    with pytest.raises(bug.BugError):
        bug.add_bug(
            root, "跨项目伪装", flow="verification", subproject="frontend", scope="cross_subproject"
        )

    item = bug.add_bug(root, "接口级缺陷", flow="verification", subproject="frontend")
    escalated = bug.escalate_bug(root, item["id"], reason="跨子项目接口")
    assert escalated["flow"] == "external"
    assert escalated["scope"] == "cross_subproject"
    assert escalated["status"] == "triaged"
    assert escalated["escalated_from"] == "verification"


def test_closed_bug_hidden_and_authorized_query_writes_read_log(
    tmp_path, monkeypatch, capsys
):
    root, contract, _sub = _env(tmp_path, monkeypatch)
    item = bug.add_bug(root, "历史缺陷")
    bug.update_bug(root, item["id"], status="fixed")
    bug.verify_bug(root, item["id"], by="verifier")
    bug.close_bug(
        root,
        item["id"],
        verification="兼容关闭",
        confirmed_by="alice",
        note="用户确认",
    )

    assert bug.list_bugs(root, active_only=True) == []
    assert [entry["id"] for entry in bug.list_bugs(root)] == [item["id"]]

    # 默认（未授权）closed 不显示
    capsys.readouterr()
    assert main(["bug", "list", "--project-dir", str(root), "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []

    # 未授权查询 closed 拒绝（缺 authorized-by）
    assert (
        main(
            [
                "bug",
                "list",
                "--project-dir",
                str(root),
                "--include-closed",
                "--reason",
                "审计",
                "--json",
            ]
        )
        == 3
    )

    # 用户授权 + reason：显示 closed，并写 READ-LOG
    capsys.readouterr()
    assert (
        main(
            [
                "bug",
                "list",
                "--project-dir",
                str(root),
                "--include-closed",
                "--authorized-by",
                "alice",
                "--reason",
                "历史审计",
                "--json",
            ]
        )
        == 0
    )
    items = json.loads(capsys.readouterr().out)
    assert [entry["id"] for entry in items] == [item["id"]]
    records = [
        json.loads(line)
        for line in (contract / "state" / "READ-LOG.ndjson").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(
        record.get("event") == "bug.list.closed" and record.get("authorized_by") == "alice"
        for record in records
    )


# ---------------------------------------------------------------- N5/N6/guard


def test_direct_state_write_denied_and_audit_detects_bypass(tmp_path, monkeypatch):
    root, contract, sub = _env(tmp_path, monkeypatch)
    decision = guard.pretool_decision(
        {
            "tool_name": "Write",
            "cwd": str(root),
            "tool_input": {"file_path": str(contract / "state" / "current.json")},
        }
    )
    assert decision is not None
    assert decision["hookSpecificOutput"]["permissionDecision"] == "deny"

    # 绕过 CLI 直接改 closed（模拟篡改）→ 审计发现缺少用户确认
    item = bug.add_bug(root, "篡改缺陷")
    path = contract / "bugs" / f"{item['id']}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["status"] = "closed"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    issues = bug.audit_bugs(contract)
    assert any("缺少用户确认记录" in issue for issue in issues)


def test_version_isolation_worker_reads_only_current_roadmap(tmp_path, monkeypatch):
    root, contract, sub = _env(tmp_path, monkeypatch)
    create_task(
        root, "当前任务", risk="low", delivery="frontend", acceptance=_acceptance()
    )
    start_task(sub, "R1-P1-T001")

    # 构造旧/其他 R 的 in_progress 任务（R2）
    create_task(
        root, "其他版本任务", risk="low", delivery="frontend", acceptance=_acceptance()
    )
    src = contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / "T002"
    dst = contract / "roadmap" / "R2" / "phases" / "P1" / "tasks" / "T002"
    dst.parent.mkdir(parents=True)
    data = yaml.safe_load((src / "TASK.yaml").read_text(encoding="utf-8"))
    data["roadmap"] = "R2"
    data["id"] = "R2-P1-T002"
    data["status"] = "in_progress"
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "TASK.yaml").write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    (src / "TASK.yaml").unlink()

    with pytest.raises(context.ContextError):
        context.expand(
            sub,
            "roadmap/R2/phases/P1/tasks/T002/TASK.yaml",
            reason="packet_missing",
            actor="worker",
        )

    decision = guard.pretool_decision(
        {
            "tool_name": "Read",
            "cwd": str(sub),
            "tool_input": {"file_path": str(dst / "TASK.yaml")},
        }
    )
    assert decision is not None
    assert decision["hookSpecificOutput"]["permissionDecision"] == "deny"

    # CLI：worker 查看其他 R 任务被拒绝（版本隔离）
    assert main(["task", "show", "R2-P1-T002", "--project-dir", str(sub), "--json"]) == 3


def test_cross_project_guard_denies_sibling(tmp_path, monkeypatch):
    root, _contract, sub = _env(tmp_path, monkeypatch)
    sibling = root / "backend"
    workspace_add_project(root, "backend", "backend")
    install_worker(sibling, "backend", workspace_root=root)
    create_task(
        root, "当前任务", risk="low", delivery="frontend", acceptance=_acceptance()
    )
    start_task(sub, "R1-P1-T001")

    for tool, payload in (
        ("Read", {"file_path": str(sibling / "app.py")}),
        ("Write", {"file_path": str(sibling / "app.py"), "content": "x"}),
    ):
        decision = guard.pretool_decision(
            {"tool_name": tool, "cwd": str(sub), "tool_input": payload}
        )
        assert decision is not None, tool
        assert decision["hookSpecificOutput"]["permissionDecision"] == "deny", tool


# ---------------------------------------------------------------- R1-R10 返工


def test_r1_external_fixed_cannot_close_even_with_confirmation(tmp_path, monkeypatch):
    root, _contract, _sub = _env(tmp_path, monkeypatch)
    item = bug.add_bug(root, "试运行缺陷")
    bug.update_bug(root, item["id"], status="fixed")
    with pytest.raises(bug.BugError):
        bug.close_bug(
            root,
            item["id"],
            verification="通过",
            confirmed_by="alice",
            note="用户确认",
        )
    bug.verify_bug(root, item["id"], by="verifier")
    closed = bug.close_bug(
        root, item["id"], verification="通过", confirmed_by="alice", note="用户确认"
    )
    assert closed["status"] == "closed"


def test_r1_audit_rejects_new_schema_legacy_close(tmp_path, monkeypatch):
    root, contract, _sub = _env(tmp_path, monkeypatch)
    item = bug.add_bug(root, "篡改缺陷")
    path = contract / "bugs" / f"{item['id']}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["status"] = "closed"
    data["legacy_close"] = True
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    issues = bug.audit_bugs(contract)
    assert any("不得走 legacy 兼容路径" in issue for issue in issues)


def test_r2_verification_requires_fix_owner_and_session_binding(tmp_path, monkeypatch):
    root, _contract, _sub = _env(tmp_path, monkeypatch)
    item = bug.add_bug(root, "内部缺陷", flow="verification", subproject="frontend")
    bug.update_bug(root, item["id"], status="fixed")  # 无 fix_owner
    with pytest.raises(bug.BugError):
        bug.verify_bug(root, item["id"], by="worker-b")
    with pytest.raises(bug.BugError):
        bug.close_bug(root, item["id"], verification="x", by="worker-b")

    bug.update_bug(
        root, item["id"], status="fixed", fix_owner="worker-a", fix_session="sess-1"
    )
    with pytest.raises(bug.BugError):
        bug.verify_bug(root, item["id"], by="worker-b", viewer_session="sess-1")
    verified = bug.verify_bug(
        root, item["id"], by="worker-b", viewer_session="sess-2"
    )
    assert verified["status"] == "verified"
    with pytest.raises(bug.BugError):
        bug.close_bug(
            root, item["id"], verification="x", by="worker-b", viewer_session="sess-1"
        )
    closed = bug.close_bug(
        root, item["id"], verification="x", by="worker-b", viewer_session="sess-2"
    )
    assert closed["closure_type"] == "viewer"


def test_r2_cross_subproject_verify_close_denied(tmp_path, monkeypatch):
    root, _contract, _sub = _env(tmp_path, monkeypatch)
    item = bug.add_bug(root, "兄弟缺陷", flow="verification", subproject="backend")
    bug.update_bug(root, item["id"], status="fixed", fix_owner="backend-a")
    with pytest.raises(bug.BugError):
        bug.verify_bug(root, item["id"], by="frontend-b", subproject="frontend")
    with pytest.raises(bug.BugError):
        bug.close_bug(
            root, item["id"], verification="x", by="frontend-b", subproject="frontend"
        )


def test_r2_cli_same_session_cannot_self_verify(tmp_path, monkeypatch):
    root, _contract, sub = _env(tmp_path, monkeypatch)
    item = bug.add_bug(root, "内部缺陷", flow="verification", subproject="frontend")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-1")
    assert (
        main(
            [
                "bug",
                "fix",
                item["id"],
                "--project-dir",
                str(sub),
                "--by",
                "alice",
                "--fixed",
            ]
        )
        == 0
    )
    assert (
        main(
            ["bug", "verify", item["id"], "--project-dir", str(sub), "--by", "bob"]
        )
        == 3
    )
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-2")
    assert (
        main(
            ["bug", "verify", item["id"], "--project-dir", str(sub), "--by", "bob"]
        )
        == 0
    )


def test_r5_worker_closed_visibility_and_authorized_query(tmp_path, monkeypatch, capsys):
    root, contract, sub = _env(tmp_path, monkeypatch)
    # external：用户确认关闭
    external = bug.add_bug(root, "外部缺陷", delivery="frontend")
    bug.update_bug(root, external["id"], status="fixed")
    bug.verify_bug(root, external["id"], by="verifier")
    bug.close_bug(
        root, external["id"], verification="ok", confirmed_by="alice", note="确认"
    )
    # verification：同子项目 viewer 关闭
    peer = bug.add_bug(root, "内部缺陷", flow="verification", subproject="frontend")
    bug.update_bug(root, peer["id"], status="fixed", fix_owner="worker-a")
    bug.verify_bug(root, peer["id"], by="worker-b")
    bug.close_bug(root, peer["id"], verification="ok", by="worker-b")
    # 兄弟子项目 verification：不可见
    other = bug.add_bug(root, "兄弟缺陷", flow="verification", subproject="backend")
    bug.update_bug(root, other["id"], status="fixed", fix_owner="backend-a")
    bug.verify_bug(root, other["id"], by="backend-b")
    bug.close_bug(root, other["id"], verification="ok", by="backend-b")

    capsys.readouterr()
    assert main(["bug", "list", "--project-dir", str(sub), "--json"]) == 0
    default_ids = {item["id"] for item in json.loads(capsys.readouterr().out)}
    assert peer["id"] in default_ids
    assert external["id"] not in default_ids
    assert other["id"] not in default_ids

    # worker 授权查询 closed 缺授权 → 拒绝
    capsys.readouterr()
    assert (
        main(
            [
                "bug",
                "list",
                "--project-dir",
                str(sub),
                "--include-closed",
                "--reason",
                "审计",
                "--json",
            ]
        )
        == 3
    )

    # worker 授权查询 closed external → 放行 + READ-LOG
    assert (
        main(
            [
                "bug",
                "list",
                "--project-dir",
                str(sub),
                "--include-closed",
                "--authorized-by",
                "alice",
                "--reason",
                "历史审计",
                "--json",
            ]
        )
        == 0
    )
    authorized_ids = {item["id"] for item in json.loads(capsys.readouterr().out)}
    assert external["id"] in authorized_ids
    records = [
        json.loads(line)
        for line in (contract / "state" / "READ-LOG.ndjson").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(
        record.get("event") == "bug.list.closed"
        and record.get("authorized_by") == "alice"
        and record.get("actor") == "worker"
        for record in records
    )

    # closed verification 同子项目可 show；closed external / 兄弟子项目拒绝
    assert main(["bug", "show", peer["id"], "--project-dir", str(sub), "--json"]) == 0
    capsys.readouterr()
    assert main(["bug", "show", external["id"], "--project-dir", str(sub), "--json"]) == 3
    capsys.readouterr()
    assert main(["bug", "show", other["id"], "--project-dir", str(sub), "--json"]) == 3


def test_r10_worker_cannot_register_sibling_subproject_bug(tmp_path, monkeypatch):
    root, _contract, sub = _env(tmp_path, monkeypatch)
    assert (
        main(
            [
                "bug",
                "add",
                "--project-dir",
                str(sub),
                "--flow",
                "verification",
                "--subproject",
                "backend",
                "--title",
                "越权登记",
            ]
        )
        == 3
    )
    # 本子项目正例
    assert (
        main(
            [
                "bug",
                "add",
                "--project-dir",
                str(sub),
                "--flow",
                "verification",
                "--subproject",
                "frontend",
                "--title",
                "本子项目缺陷",
            ]
        )
        == 0
    )


def test_r8_mfp_id_and_ref_path_traversal_denied(tmp_path, monkeypatch):
    root, _contract, sub = _env(tmp_path, monkeypatch)
    local = improve.new_improvement(sub, "工具缺口", local=True)
    _fill_mfp(local)
    improve.submit_improvement(sub, local.stem)
    source = tmp_path / "source"
    source.mkdir()
    (source / "pyproject.toml").write_text("[project]\nname='meta-flow'\n", encoding="utf-8")
    inbox = improve.inbox_dir("demo") / f"{local.stem}.yaml"
    data = yaml.safe_load(inbox.read_text(encoding="utf-8"))
    data["id"] = "../../../evil"
    inbox.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    with pytest.raises(improve.ImproveError):
        improve.archive_improvement(f"demo/{local.stem}", source=source)
    assert not (source.parent / "evil.yaml").exists()
    with pytest.raises(improve.ImproveError):
        improve.archive_improvement("../x", source=source)
    with pytest.raises(improve.ImproveError):
        improve.find_improvement(root, "../../etc")


def test_r9_mfp_triage_requires_next_step(tmp_path, monkeypatch):
    root, contract, _sub = _env(tmp_path, monkeypatch)
    path = improve.new_improvement(root, "工具改进")
    _fill_mfp(path)
    with pytest.raises(improve.ImproveError):
        improve.triage_improvement(root, path.stem, decision="accepted")
    with pytest.raises(improve.ImproveError):
        improve.triage_improvement(root, path.stem, decision="rejected")
    data = improve.triage_improvement(
        root, path.stem, decision="accepted", next_step="design"
    )
    assert data["status"] == "accepted"
    assert data["triage"]["next_step"] == "design"
    assert any(event.get("event") == "mfp.triaged" for event in _ledger(contract))
