"""WP-F2F3 / REQ-0019/0020：工作包、设计包、技能与文档模型（T038 A2/A3）。"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

from meta_flow import design, docmodel, req, skills, templates, work
from meta_flow.cli import main
from meta_flow.global_store import bootstrap
from meta_flow.install import install_designer, install_root, install_worker
from meta_flow.workspace import workspace_add_project, workspace_init


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


def _ledger(contract):
    return [
        json.loads(line)
        for line in (contract / "state" / "ledger.ndjson").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _create_wp(root):
    return work.create_work_package(
        root,
        "frontend",
        requirements=["REQ-0001"],
        specs=["SPEC-001"],
        allowed_paths=["src/**", "tests/**"],
        acceptance=[{"id": "A1", "method": "artifact", "expect": "完成"}],
    )


def test_work_package_lifecycle_and_ledger(tmp_path, monkeypatch):
    root, contract, _sub = _env(tmp_path, monkeypatch)
    wp = _create_wp(root)
    assert wp["id"] == "R1-P3-WP-frontend-01"
    assert wp["status"] == "planned"
    assert wp["verification"]["final"] == "subproject-worker"
    assert wp["verification"]["acceptance"] == "manager"
    path = contract / "roadmap" / "R1" / "phases" / "P3" / "work-packages" / wp["id"] / "WORK-PACKAGE.yaml"
    assert path.is_file()

    task = work.add_task(
        root,
        wp["id"],
        task_type="implement",
        goal="实现登录",
        acceptance=[{"id": "A1", "method": "artifact", "expect": "完成"}],
    )
    assert task["id"] == "T1" and task["verification"] == "none"

    work.start_work_package(root, wp["id"], actor_role="manager")
    decision = work.request_decision(
        root,
        wp["id"],
        problem="接口 A/B",
        impact="M4/M6",
        options=[{"id": "A", "pros": "简单", "cons": "扩展弱"}],
        recommendation="A",
        level="D1",
        owner="user",
        actor_role="manager",
    )
    assert decision["type"] == "decision"
    assert work.find_work_package(root, wp["id"])[1]["status"] == "waiting_decision"

    work.record_decision(
        root,
        wp["id"],
        decision["id"],
        decision="A",
        decided_by="alice",
        actor_role="manager",
        confirmed_by="alice",
        note="用户确认 A",
    )
    assert work.find_work_package(root, wp["id"])[1]["status"] == "in_progress"

    work.start_verification(root, wp["id"], actor_role="manager")
    done = work.record_verification(
        root, wp["id"], result="PASS", evidence=["evidence/l1.txt"], actor_role="manager"
    )
    assert done["status"] == "done"
    accepted = work.accept_work_package(root, wp["id"], verdict="PASS", note="通过")
    assert accepted["status"] == "accepted"

    events = {event.get("event") for event in _ledger(contract)}
    assert {
        "work_package.created",
        "work_package.task_added",
        "work_package.decision_requested",
        "work_package.decision_recorded",
        "work_package.started",
        "work_package.verification_started",
        "work_package.verified",
        "work_package.accepted",
    } <= events


def test_work_package_validation_and_permissions(tmp_path, monkeypatch):
    root, _contract, _sub = _env(tmp_path, monkeypatch)
    with pytest.raises(work.WorkError) as exc:
        work.create_work_package(root, "frontend", requirements=["REQ-0001"])
    assert "allowed_paths" in str(exc.value)

    with pytest.raises(work.WorkError) as exc:
        work.create_work_package(
            root,
            "frontend",
            requirements=["REQ-0001"],
            allowed_paths=["src/**"],
            actor_role="worker",
        )
    assert exc.value.code == 3

    wp = _create_wp(root)
    with pytest.raises(work.WorkError):
        work.add_task(root, wp["id"], task_type="implement", goal="缺验收")


def test_work_package_creates_no_review_tasks(tmp_path, monkeypatch):
    """CHG-0005：工作包任务不按任务机械生成 review 任务。"""
    root, contract, _sub = _env(tmp_path, monkeypatch)
    wp = _create_wp(root)
    work.add_task(
        root,
        wp["id"],
        task_type="implement",
        goal="实现",
        acceptance=[{"id": "A1", "method": "artifact", "expect": "完成"}],
    )
    reviews = list((contract / "roadmap").glob("*/phases/*/tasks/T*/TASK.yaml"))
    assert reviews == []
    assert work.list_work_packages(root)[0]["id"] == wp["id"]


def test_work_package_cli(tmp_path, monkeypatch, capsys):
    root, contract, _sub = _env(tmp_path, monkeypatch)
    capsys.readouterr()
    assert (
        main(
            [
                "work",
                "create",
                "--project-dir",
                str(root),
                "--subproject",
                "frontend",
                "--requirement",
                "REQ-0001",
                "--allowed-path",
                "src/**",
                "--acceptance",
                "完成",
            ]
        )
        == 0
    )
    wp_id = "R1-P3-WP-frontend-01"
    assert wp_id in capsys.readouterr().out
    assert (
        main(
            [
                "work",
                "task",
                wp_id,
                "--project-dir",
                str(root),
                "--type",
                "implement",
                "--goal",
                "实现",
                "--acceptance",
                "完成",
            ]
        )
        == 0
    )
    assert main(["work", "start", wp_id, "--project-dir", str(root)]) == 0
    assert (
        main(
            ["work", "verify", wp_id, "--project-dir", str(root), "--result", "PASS"]
        )
        == 0
    )
    assert main(["work", "accept", wp_id, "--project-dir", str(root), "--verdict", "PASS"]) == 0
    assert work.find_work_package(root, wp_id)[1]["status"] == "accepted"


def test_design_package_create_and_accept(tmp_path, monkeypatch):
    root, contract, _sub = _env(tmp_path, monkeypatch)
    install_designer(contract, workspace_root=root)
    dp = design.create_design(
        root,
        "登录设计",
        requirements=["REQ-0001"],
        specs=["SPEC-001"],
        subprojects=["frontend"],
        scope="登录闭环",
        actor_role="designer",
    )
    assert dp["id"] == "DP-R1-01"
    path = contract / "roadmap" / "R1" / "phases" / "P2" / "design" / "DP-R1-01.md"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "REQ-0001" in text and "SPEC-001" in text

    with pytest.raises(design.DesignError):
        design.create_design(contract, "越权设计", actor_role="worker")

    accepted = design.accept_design(
        root, dp["id"], verdict="PASS", note="设计通过", actor_role="manager"
    )
    assert accepted["status"] == "accepted"
    with pytest.raises(design.DesignError):
        design.accept_design(contract, dp["id"], verdict="PASS", actor_role="designer")


def test_skill_discovery_and_validation(tmp_path, monkeypatch, capsys):
    root, contract, _sub = _env(tmp_path, monkeypatch)
    skill_dir = root / "templates" / "skills"
    skill_dir.mkdir(parents=True)
    (skill_dir / "sample.md").write_text(
        "---\n"
        "name: sample\n"
        "roles: [manager]\n"
        "trigger: 示例\n"
        "inputs: [x]\n"
        "outputs: [y]\n"
        "read: [requirements/]\n"
        "write: [requirements/]\n"
        "---\n"
        "## 步骤\n1. x\n## 门禁\n- y\n## 失败/升级\n- BLOCKED\n"
        "## 证据\n- ledger\n## 反模式\n- 无\n",
        encoding="utf-8",
    )
    items = skills.discover_skills(root)
    assert [item["name"] for item in items] == ["sample"]
    assert skills.validate_skills(root)[0]["errors"] == []

    capsys.readouterr()
    assert main(["skill", "list", "--project-dir", str(root), "--json"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed[0]["name"] == "sample"
    assert main(["skill", "validate", "--project-dir", str(root)]) == 0

    # 结构缺失 → 校验失败
    (skill_dir / "bad.md").write_text("---\nname: bad\n---\n# bad\n", encoding="utf-8")
    assert main(["skill", "validate", "--project-dir", str(root)]) == 1


def test_shipped_skills_and_prompts_are_layered():
    repo = Path(__file__).resolve().parents[1]
    shipped = sorted((repo / "templates" / "skills").glob("*.md"))
    assert len(shipped) >= 8
    names = {
        path.stem for path in shipped if not path.name.upper().startswith("INDEX")
    }
    for path in shipped:
        if path.name.upper().startswith("INDEX"):
            continue
        errors = skills.validate_skill(path)
        assert errors == [], f"{path.name}: {errors}"
    texts = [
        (repo / "agents" / f"{name}.md").read_text(encoding="utf-8")
        for name in ("manager", "worker", "designer", "maintainer")
    ]
    texts.extend(
        [
            templates.AGENT_MANAGER,
            templates.AGENT_WORKER,
            templates.AGENT_DESIGNER,
            templates.AGENT_MAINTAINER,
        ]
    )
    for text in texts:
        assert "活动索引" in text and "mf skill" in text
        refs = set(re.findall(r"skill:([a-z0-9-]+)", text))
        assert refs, "提示词缺少 skill: 引用"
        missing = refs - names
        assert not missing, f"提示词引用了未交付技能: {sorted(missing)}"


def test_docs_model_check_and_p2_spec_trace(tmp_path, monkeypatch, capsys):
    root, contract, _sub = _env(tmp_path, monkeypatch)
    item = req.add_requirement(root, "登录", acceptance=["成功"])
    p2 = contract / "roadmap" / "R1" / "phases" / "P2" / "specs"
    p2.mkdir(parents=True)
    (p2 / "SPEC-900.md").write_text(f"# SPEC-900\n关联 {item['id']}\n", encoding="utf-8")

    trace = req.trace_requirement(contract, item["id"])
    assert "roadmap/R1/phases/P2/specs/SPEC-900.md" in trace["specs"]

    assert main(["docs", "check", "--project-dir", str(root)]) == 0

    (contract / "architecture").mkdir(exist_ok=True)
    (contract / "architecture" / "SPEC-BAD.md").write_text("# bad\n", encoding="utf-8")
    issues = docmodel.check(contract)
    assert any("SPEC 不应位于继承文档目录" in issue for issue in issues)
    capsys.readouterr()
    assert main(["docs", "check", "--project-dir", str(root), "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False


# ---------------------------------------------------------------- R3/R4/R7 返工


def test_r3_decision_permissions_and_required_fields(tmp_path, monkeypatch):
    root, contract, _sub = _env(tmp_path, monkeypatch)
    wp = _create_wp(root)

    with pytest.raises(work.WorkError):
        work.request_decision(
            root,
            wp["id"],
            problem="",
            impact="i",
            options=[{"id": "A"}],
            recommendation="A",
            level="D2",
            owner="manager",
        )
    with pytest.raises(work.WorkError):
        work.request_decision(
            root,
            wp["id"],
            problem="p",
            impact="i",
            options=[],
            recommendation="A",
            level="D2",
            owner="manager",
        )
    with pytest.raises(work.WorkError):
        work.request_decision(
            root,
            wp["id"],
            problem="p",
            impact="i",
            options=[{"id": "A"}],
            recommendation="A",
            level="D1",
            owner="manager",
        )

    task = work.request_decision(
        root,
        wp["id"],
        problem="接口 A/B",
        impact="M4/M6",
        options=[{"id": "A"}, {"id": "B"}],
        recommendation="A",
        level="D1",
        owner="user",
        actor_role="manager",
    )
    with pytest.raises(work.WorkError) as exc:
        work.record_decision(
            root,
            wp["id"],
            task["id"],
            decision="A",
            decided_by="worker",
            actor_role="worker",
            actor_delivery="frontend",
        )
    assert exc.value.code == 3
    with pytest.raises(work.WorkError):
        work.record_decision(
            root, wp["id"], task["id"], decision="A", decided_by="manager", actor_role="manager"
        )
    with pytest.raises(work.WorkError):
        work.record_decision(
            root,
            wp["id"],
            task["id"],
            decision="A",
            decided_by="manager",
            actor_role="manager",
            confirmed_by="manager",
            note="冒充用户",
        )
    data = work.record_decision(
        root,
        wp["id"],
        task["id"],
        decision="A",
        decided_by="alice",
        actor_role="manager",
        confirmed_by="alice",
        note="用户确认 A",
    )
    block = data["tasks"][-1]["decision"]
    assert block["confirmed_by"] == "alice"
    assert block["decision"] == "A"
    assert any(
        event.get("event") == "work_package.decision_recorded"
        and event.get("level") == "D1"
        for event in _ledger(contract)
    )

    wp2 = work.create_work_package(
        root, "frontend", requirements=["REQ-0001"], allowed_paths=["src/**"]
    )
    task2 = work.request_decision(
        root,
        wp2["id"],
        problem="技术选型",
        impact="模块",
        options=[{"id": "X"}, {"id": "Y"}],
        recommendation="X",
        level="D2",
        owner="manager",
        actor_role="manager",
    )
    with pytest.raises(work.WorkError) as exc:
        work.record_decision(
            root,
            wp2["id"],
            task2["id"],
            decision="X",
            decided_by="worker",
            actor_role="worker",
            actor_delivery="frontend",
        )
    assert exc.value.code == 3
    ok = work.record_decision(
        root, wp2["id"], task2["id"], decision="X", decided_by="manager", actor_role="manager"
    )
    assert ok["tasks"][-1]["decision"]["decision"] == "X"


def test_r4_worker_work_and_design_isolation(tmp_path, monkeypatch, capsys):
    root, contract, sub = _env(tmp_path, monkeypatch)
    front = work.create_work_package(
        root, "frontend", requirements=["REQ-0001"], allowed_paths=["src/**"]
    )
    back = work.create_work_package(
        root, "backend", requirements=["REQ-0001"], allowed_paths=["src/**"]
    )
    r2_wp = {
        "id": "R2-P3-WP-frontend-01",
        "roadmap": "R2",
        "phase": "P3",
        "subproject": "frontend",
        "status": "planned",
        "scope": {"requirements": ["REQ-0001"], "mfps": [], "specs": []},
        "context": {"allowed_paths": ["src/**"], "budget": {"files": 1, "bytes": 1}},
        "tasks": [],
    }
    r2_path = (
        contract
        / "roadmap"
        / "R2"
        / "phases"
        / "P3"
        / "work-packages"
        / "R2-P3-WP-frontend-01"
        / "WORK-PACKAGE.yaml"
    )
    r2_path.parent.mkdir(parents=True)
    r2_path.write_text(yaml.safe_dump(r2_wp, sort_keys=False), encoding="utf-8")

    work.add_task(
        root,
        front["id"],
        task_type="implement",
        goal="实现",
        acceptance=[{"id": "A1", "method": "artifact", "expect": "完成"}],
    )

    capsys.readouterr()
    assert main(["work", "list", "--project-dir", str(sub), "--json"]) == 0
    ids = {item["id"] for item in json.loads(capsys.readouterr().out)}
    assert ids == {front["id"]}
    assert main(["work", "show", back["id"], "--project-dir", str(sub), "--json"]) == 3
    assert (
        main(
            ["work", "show", "R2-P3-WP-frontend-01", "--project-dir", str(sub), "--json"]
        )
        == 3
    )
    assert (
        main(
            [
                "work",
                "task",
                back["id"],
                "--project-dir",
                str(sub),
                "--type",
                "implement",
                "--goal",
                "越权",
                "--acceptance",
                "x",
            ]
        )
        == 3
    )
    assert main(["work", "start", back["id"], "--project-dir", str(sub)]) == 3
    assert (
        main(
            ["work", "verify", back["id"], "--project-dir", str(sub), "--result", "PASS"]
        )
        == 3
    )
    assert main(["work", "start", front["id"], "--project-dir", str(sub)]) == 0

    dp = design.create_design(
        root,
        "后端设计",
        requirements=["REQ-0001"],
        specs=["SPEC-001"],
        subprojects=["backend"],
        actor_role="designer",
    )
    capsys.readouterr()
    assert main(["design", "list", "--project-dir", str(sub), "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []
    assert main(["design", "show", dp["id"], "--project-dir", str(sub), "--json"]) == 3


def test_r7_work_package_requires_accepted_design_package(tmp_path, monkeypatch):
    root, _contract, _sub = _env(tmp_path, monkeypatch)
    with pytest.raises(work.WorkError):
        work.create_work_package(
            root,
            "frontend",
            requirements=["REQ-0001"],
            allowed_paths=["src/**"],
            design_package="DP-R1-99",
        )
    dp = design.create_design(
        root,
        "登录设计",
        requirements=["REQ-0001"],
        specs=["SPEC-001"],
        subprojects=["frontend"],
        actor_role="designer",
    )
    with pytest.raises(work.WorkError):
        work.create_work_package(
            root,
            "frontend",
            requirements=["REQ-0001"],
            allowed_paths=["src/**"],
            design_package=dp["id"],
        )
    design.accept_design(root, dp["id"], verdict="PASS", actor_role="manager")
    wp = work.create_work_package(
        root,
        "frontend",
        requirements=["REQ-0001"],
        allowed_paths=["src/**"],
        design_package=dp["id"],
    )
    assert wp["design_package"] == dp["id"]
