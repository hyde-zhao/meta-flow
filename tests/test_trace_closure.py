"""需求/规格追踪闭环、孤儿检查与任务卡最小字段（MFP-0020）。"""

from __future__ import annotations

import json

import yaml

from meta_flow import bug, req, verify
from meta_flow.cli import main
from meta_flow.global_store import bootstrap
from meta_flow.install import install_root
from meta_flow.task import (
    accept_task,
    create_task,
    load_task,
    start_task,
    submit_task,
    summary_text,
)
from meta_flow.workspace import workspace_init


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
    return root, root / "demo-contract"


def _bundle(contract, task_id):
    tail = task_id.rsplit("-", 1)[-1]
    return contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / tail


def _finish_task(root, contract, task_id, *, kind_text=None):
    start_task(root, task_id)
    bundle = _bundle(contract, task_id)
    (bundle / "evidence").mkdir(parents=True, exist_ok=True)
    (bundle / "evidence" / "l1.txt").write_text("L1 PASS\n", encoding="utf-8")
    if kind_text:
        (bundle / "dev-record.md").write_text(kind_text, encoding="utf-8")
        (bundle / "handoff.md").write_text(kind_text, encoding="utf-8")
    else:
        (bundle / "dev-record.md").write_text("# dev\n完成\n", encoding="utf-8")
        (bundle / "handoff.md").write_text("# handoff\n完成\n", encoding="utf-8")
    submit_task(root, task_id)
    accept_task(root, task_id, verdict="PASS")


def test_trace_closure_and_orphan_check(tmp_path, monkeypatch):
    root, contract = _env(tmp_path, monkeypatch)
    item = req.add_requirement(root, "登录", acceptance=["成功登录"])
    req.update_requirement(root, item["id"], status="in_roadmap")

    issues = req.orphans(contract)
    assert any("REQ-0001 无 SPEC" in issue for issue in issues)
    assert any("REQ-0001 无 TASK" in issue for issue in issues)

    specs = contract / "specs"
    specs.mkdir(parents=True, exist_ok=True)
    (specs / "SPEC-001.md").write_text("# SPEC-001\n关联 REQ-0001\n", encoding="utf-8")
    create_task(
        root,
        "实现登录",
        risk="low",
        acceptance=_acceptance(),
        inputs={"requirements": ["REQ-0001"], "specs": ["SPEC-001"]},
    )
    _finish_task(root, contract, "R1-P1-T001")

    issues = req.orphans(contract)
    assert not any("无 SPEC" in issue for issue in issues)
    assert not any("无 TASK" in issue for issue in issues)
    assert not any("无证据" in issue for issue in issues)

    req.update_requirement(root, "REQ-0001", status="verified")
    issues = req.orphans(contract)
    assert any("REQ-0001 状态 verified 但无 VR" in issue for issue in issues)
    verify.record_verification(
        root,
        layer="requirement",
        scope="登录",
        result="PASS",
        requirement_refs=["REQ-0001"],
    )
    assert req.orphans(contract) == []

    entry = req.trace_requirement(contract, "REQ-0001")
    for key in ("specs", "tasks", "evidence", "verification", "bugs", "improvements", "releases"):
        assert key in entry
    assert entry["evidence"]


def test_accepted_fix_task_with_open_bug_is_orphan(tmp_path, monkeypatch):
    root, contract = _env(tmp_path, monkeypatch)
    req.add_requirement(root, "修复崩溃", acceptance=["不崩溃"])
    bug_item = bug.add_bug(root, "崩溃", severity="major", related_reqs=["REQ-0001"])
    create_task(
        root,
        "修复崩溃",
        kind="fix",
        risk="low",
        fixes=[bug_item["id"]],
        acceptance=_acceptance(),
        inputs={"requirements": ["REQ-0001"]},
    )
    root_task = load_task(root, "R1-P1-T001")[1]
    root_task["fixes"] = [bug_item["id"]]
    path = _bundle(contract, "R1-P1-T001") / "TASK.yaml"
    path.write_text(yaml.safe_dump(root_task, sort_keys=False, allow_unicode=True), encoding="utf-8")

    _finish_task(
        root,
        contract,
        "R1-P1-T001",
        kind_text="# dev\n## 根因\nx\n## 修复\ny\n## 回归\nz\n",
    )
    assert bug.show_bug(root, bug_item["id"])["status"] == "fixed"
    issues = req.orphans(contract)
    assert any("已 accepted 但 BUG BUG-0001 未关闭" in issue for issue in issues)

    bug.verify_bug(root, bug_item["id"], by="verifier")
    bug.close_bug(
        root,
        bug_item["id"],
        verification="回归通过",
        confirmed_by="alice",
        note="用户确认关闭",
    )
    assert not any("BUG-0001 未关闭" in issue for issue in req.orphans(contract))


def test_task_minimal_fields_and_human_summary(tmp_path, monkeypatch):
    root, _ = _env(tmp_path, monkeypatch)
    create_task(
        root,
        "登录接口",
        risk="low",
        acceptance=_acceptance(),
        module="auth",
        spec_ids=["SPEC-001"],
        evidence=["evidence/l1.txt"],
    )
    data = load_task(root, "R1-P1-T001")[1]
    assert data["module"] == "auth"
    assert data["spec_ids"] == ["SPEC-001"]
    assert data["evidence"] == ["evidence/l1.txt"]
    text = summary_text(data)
    assert "auth" in text and "SPEC-001" in text and "R1-P1-T001" in text


def test_cli_active_defaults_and_trace_check(tmp_path, monkeypatch, capsys):
    root, contract = _env(tmp_path, monkeypatch)
    req.add_requirement(root, "登录", acceptance=["成功"])
    req.update_requirement(root, "REQ-0001", status="in_roadmap")
    create_task(root, "已完成", risk="low", acceptance=_acceptance())
    create_task(root, "进行中", risk="low", acceptance=_acceptance())
    _finish_task(root, contract, "R1-P1-T001")

    capsys.readouterr()
    assert main(["task", "list", "--project-dir", str(root), "--json"]) == 0
    items = json.loads(capsys.readouterr().out)
    assert [item["id"] for item in items] == ["R1-P1-T002"]
    assert main(["task", "list", "--project-dir", str(root), "--all", "--json"]) == 0
    items = json.loads(capsys.readouterr().out)
    assert {item["id"] for item in items} == {"R1-P1-T001", "R1-P1-T002"}

    assert main(["req", "trace", "--project-dir", str(root), "--check"]) == 1
    out = capsys.readouterr().out
    assert "孤儿/未闭环检查: FAIL" in out
    assert "REQ-0001 无 SPEC" in out

    bug_item = bug.add_bug(root, "报错", severity="minor")
    bug.update_bug(root, bug_item["id"], status="fixed")
    bug.verify_bug(root, bug_item["id"], by="verifier")
    bug.close_bug(
        root,
        bug_item["id"],
        verification="已修复",
        confirmed_by="alice",
        note="用户确认",
    )
    capsys.readouterr()
    assert main(["bug", "list", "--project-dir", str(root), "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []
    assert main(["bug", "list", "--project-dir", str(root), "--history", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["id"] == "BUG-0001"
