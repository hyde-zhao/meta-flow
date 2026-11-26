"""任务卡、评审任务与状态机测试。"""

from __future__ import annotations

import json

import pytest
import yaml

from meta_flow.global_store import bootstrap
from meta_flow.install import install_root
from meta_flow.task import (
    TaskError,
    accept_task,
    create_task,
    list_tasks,
    load_task,
    packet_text,
    prompt_text,
    reject_task,
    rework_task,
    start_task,
    submit_task,
)
from meta_flow.workspace import workspace_init


@pytest.fixture()
def task_env(tmp_path, monkeypatch):
    home = tmp_path / "global"
    monkeypatch.setenv("META_FLOW_HOME", str(home))
    bootstrap()
    root = tmp_path / "demo"
    root.mkdir()
    install_root(root)
    workspace_init(root, "Demo")
    return {"root": root, "contract": root / "demo-contract"}


def _acceptance():
    return [{"id": "A1", "method": "artifact", "expect": "实现完成"}]


def _write_worker_files(contract, task_id):
    bundle = contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / f"T{task_id[-3:]}"
    (bundle / "dev-record.md").write_text("# dev\n实现完成\n", encoding="utf-8")
    (bundle / "handoff.md").write_text("# handoff\n完成\n", encoding="utf-8")
    return bundle


def _write_review_files(
    contract,
    review_id,
    verdict,
    *,
    scope=None,
    requires=None,
    items=("R1",),
):
    bundle = contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / f"T{review_id[-3:]}"
    (bundle / "review.md").write_text(f"# review\nverdict: {verdict}\n", encoding="utf-8")
    lines = [f"# review handoff\n> verdict: {verdict}"]
    if scope is not None:
        lines.append(f"> rework_scope: {scope}")
    if requires is not None:
        lines.append(f"> rework_requires: {requires}")
    lines.extend(
        [
            "",
            "## 必须整改项",
            "",
            "| ID | 文件/行 | 要求 | 验收方法 |",
            "|---|---|---|---|",
        ]
    )
    for item in items:
        lines.append(f"| {item} | src/app.py:1 | 整改 | pytest |")
    (bundle / "review-handoff.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return bundle


def test_create_low_task(task_env):
    root = task_env["root"]
    result = create_task(root, "文档修正", risk="low", acceptance=_acceptance())
    assert result["task"] == "R1-P1-T001"
    assert result["review_task"] is None
    _, task = load_task(root, "R1-P1-T001")
    assert task["status"] == "ready"
    assert task["next_owner"] == "worker"
    assert task["review"]["mode"] == "manager"
    assert "responsible_agent: worker" in prompt_text(root, "R1-P1-T001")


def test_create_high_task_auto_review(task_env):
    root = task_env["root"]
    result = create_task(root, "安装器改动", risk="high", acceptance=_acceptance())
    assert result["task"] == "R1-P1-T001"
    assert result["review_task"] == "R1-P1-T002"
    _, task = load_task(root, "R1-P1-T001")
    _, review = load_task(root, "R1-P1-T002")
    assert task["reviewed_by_task"] == "R1-P1-T002"
    assert review["kind"] == "review"
    assert review["reviews"] == "R1-P1-T001"
    assert review["status"] == "draft"


def test_low_risk_flow(task_env):
    root = task_env["root"]
    contract = task_env["contract"]
    create_task(root, "文档修正", risk="low", acceptance=_acceptance())
    start_task(root, "R1-P1-T001")
    _write_worker_files(contract, "R1-P1-T001")
    data = submit_task(root, "R1-P1-T001")
    assert data["status"] == "submitted"
    assert data["next_owner"] == "manager"
    assert "responsible_agent: manager" in prompt_text(root, "R1-P1-T001")
    accepted = accept_task(root, "R1-P1-T001", verdict="PASS")
    assert accepted["status"] == "accepted"


def test_high_risk_review_flow(task_env):
    root = task_env["root"]
    contract = task_env["contract"]
    result = create_task(root, "安装器改动", risk="high", acceptance=_acceptance())
    task_id = result["task"]
    review_id = result["review_task"]

    start_task(root, task_id)
    _write_worker_files(contract, task_id)
    task = submit_task(root, task_id)
    assert task["next_owner"] == "worker"
    _, review = load_task(root, review_id)
    assert review["status"] == "ready"
    prompt = prompt_text(root, task_id)
    assert f"review_task: {review_id}" in prompt
    assert "--review-packet" in prompt

    with pytest.raises(TaskError):
        accept_task(root, task_id, verdict="PASS")

    start_task(root, review_id)
    bundle = contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / f"T{review_id[-3:]}"
    (bundle / "handoff.md").write_text("# review handoff\n通过\n", encoding="utf-8")
    (bundle / "review.md").write_text("# review\nPASS\n", encoding="utf-8")
    (bundle / "review-handoff.md").write_text(
        "# review handoff\nverdict: PASS\n", encoding="utf-8"
    )
    submit_task(root, review_id)
    accept_task(root, review_id, verdict="PASS")

    accepted = accept_task(root, task_id, verdict="PASS")
    assert accepted["status"] == "accepted"


def test_reject_resets_review(task_env):
    root = task_env["root"]
    contract = task_env["contract"]
    result = create_task(root, "安装器改动", risk="high", acceptance=_acceptance())
    task_id = result["task"]
    review_id = result["review_task"]
    start_task(root, task_id)
    _write_worker_files(contract, task_id)
    submit_task(root, task_id)
    rejected = reject_task(root, task_id, "验收不通过")
    assert rejected["status"] == "rejected"
    assert rejected["next_owner"] == "worker"
    _, review = load_task(root, review_id)
    assert review["status"] == "ready"
    assert review["review_verdict"] is None


def test_needs_rework_in_scope_auto_reopens_and_rework_starts(task_env):
    from meta_flow import state

    root = task_env["root"]
    contract = task_env["contract"]
    result = create_task(
        root,
        "中风险返工",
        risk="medium",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
    )
    task_id, review_id = result["task"], result["review_task"]
    start_task(root, task_id)
    _write_worker_files(contract, task_id)
    submit_task(root, task_id)

    start_task(root, review_id)
    _write_review_files(
        contract,
        review_id,
        "NEEDS_REWORK",
        scope="in-scope",
        requires="none",
        items=("R1", "R2"),
    )
    submit_task(root, review_id)
    accepted = accept_task(root, review_id, verdict="NEEDS_REWORK")
    assert accepted["review_verdict"] == "NEEDS_REWORK"
    decision = accepted["rework_decision"]
    assert decision["auto"] is True

    _, task = load_task(root, task_id)
    assert task["status"] == "rework"
    assert task["next_owner"] == "worker"
    rework = task["rework"]
    assert rework["review_task"] == review_id
    assert rework["items"] == ["R1", "R2"]
    assert rework["allowed_paths"] == ["src/**"]
    assert rework["decision"] == "auto"
    assert rework["notify"] == ["manager"]

    summary = state.task_summary(contract)
    assert summary["rework_tasks"] == [task_id]
    current = state.refresh_current(contract)
    assert current["next_action"]["type"] == "execute_rework"
    assert current["next_action"]["task"] == task_id

    prompt = prompt_text(root, task_id)
    assert "responsible_agent: worker" in prompt
    assert f"mf task rework {task_id}" in prompt
    with pytest.raises(TaskError, match="mf task rework"):
        start_task(root, task_id)

    started = rework_task(root, task_id)
    assert started["status"] == "in_progress"
    assert started["next_owner"] == "worker"
    assert started["lease"]["owner"] == "worker"
    assert started["rework"]["review_task"] == review_id
    assert started["rework"]["items"] == ["R1", "R2"]
    assert started["rework"]["allowed_paths"] == ["src/**"]
    assert started["rework"]["lease"] == started["lease"]["expires_at"]

    events = [
        json.loads(line)
        for line in (contract / "state" / "ledger.ndjson")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert any(
        event.get("event") == "task.rework.open"
        and event.get("task") == task_id
        and event.get("review_task") == review_id
        and event.get("decision") == "auto"
        and event.get("notify") == ["manager"]
        for event in events
    )
    assert any(
        event.get("event") == "task.rework"
        and event.get("task") == task_id
        and event.get("review_task") == review_id
        and event.get("lease")
        and event.get("notify") == ["manager"]
        for event in events
    )


def test_needs_rework_high_risk_keeps_manager_decision(task_env):
    root = task_env["root"]
    contract = task_env["contract"]
    result = create_task(
        root,
        "高风险返工",
        risk="high",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
    )
    task_id, review_id = result["task"], result["review_task"]
    start_task(root, task_id)
    _write_worker_files(contract, task_id)
    submit_task(root, task_id)
    start_task(root, review_id)
    _write_review_files(contract, review_id, "NEEDS_REWORK", scope="in-scope", requires="none")
    submit_task(root, review_id)

    accepted = accept_task(root, review_id, verdict="NEEDS_REWORK")
    decision = accepted["rework_decision"]
    assert decision["auto"] is False
    assert "高风险" in (decision["reason"] or "")

    _, task = load_task(root, task_id)
    assert task["status"] == "submitted"
    assert task["next_owner"] == "manager"
    assert task["rework"]["decision"] == "manager"
    assert task["rework"]["auto"] is False
    assert "responsible_agent: manager" in prompt_text(root, task_id)
    assert "裁决" in prompt_text(root, task_id)
    with pytest.raises(TaskError, match="submitted"):
        rework_task(root, task_id)


def test_needs_rework_out_of_scope_blocked_until_manager_rejects(task_env):
    root = task_env["root"]
    contract = task_env["contract"]
    result = create_task(
        root,
        "范围外返工",
        risk="medium",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
    )
    task_id, review_id = result["task"], result["review_task"]
    start_task(root, task_id)
    _write_worker_files(contract, task_id)
    submit_task(root, task_id)
    start_task(root, review_id)
    _write_review_files(
        contract, review_id, "NEEDS_REWORK", scope="out-of-scope", requires="chg"
    )
    submit_task(root, review_id)

    accepted = accept_task(root, review_id, verdict="NEEDS_REWORK")
    assert accepted["rework_decision"]["auto"] is False
    assert "CHG" in (accepted["rework_decision"]["reason"] or "")
    with pytest.raises(TaskError, match="submitted"):
        rework_task(root, task_id)

    rejected = reject_task(root, task_id, "确认整改项后返工")
    assert rejected["status"] == "rejected"
    assert rejected["next_owner"] == "worker"
    assert rejected["rework"]["decision"] == "manager"
    _, review = load_task(root, review_id)
    assert review["status"] == "accepted"
    assert review["review_verdict"] == "NEEDS_REWORK"

    prompt = prompt_text(root, task_id)
    assert "responsible_agent: worker" in prompt
    assert f"mf task rework {task_id}" in prompt
    started = rework_task(root, task_id)
    assert started["status"] == "in_progress"
    assert started["rework"]["decision"] == "manager"


@pytest.mark.parametrize(
    ("scope", "requires"),
    [("disputed", "none"), ("in-scope", "acceptance"), ("in-scope", "bug,mfp")],
)
def test_needs_rework_scope_or_new_requirements_blocks_auto(task_env, scope, requires):
    root = task_env["root"]
    contract = task_env["contract"]
    result = create_task(
        root,
        "范围门",
        risk="medium",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
    )
    task_id, review_id = result["task"], result["review_task"]
    start_task(root, task_id)
    _write_worker_files(contract, task_id)
    submit_task(root, task_id)
    start_task(root, review_id)
    _write_review_files(contract, review_id, "NEEDS_REWORK", scope=scope, requires=requires)
    submit_task(root, review_id)

    accepted = accept_task(root, review_id, verdict="NEEDS_REWORK")
    assert accepted["rework_decision"]["auto"] is False
    _, task = load_task(root, task_id)
    assert task["status"] == "submitted"
    assert task["next_owner"] == "manager"
    assert task["rework"]["decision"] == "manager"


def test_needs_rework_missing_scope_declaration_requires_manager(task_env):
    root = task_env["root"]
    contract = task_env["contract"]
    result = create_task(
        root,
        "缺范围声明",
        risk="medium",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
    )
    task_id, review_id = result["task"], result["review_task"]
    start_task(root, task_id)
    _write_worker_files(contract, task_id)
    submit_task(root, task_id)
    start_task(root, review_id)
    _write_review_files(contract, review_id, "NEEDS_REWORK")
    submit_task(root, review_id)

    accepted = accept_task(root, review_id, verdict="NEEDS_REWORK")
    assert accepted["rework_decision"]["auto"] is False
    assert "rework_requires" in (accepted["rework_decision"]["reason"] or "")
    _, task = load_task(root, task_id)
    assert task["status"] == "submitted"
    assert task["next_owner"] == "manager"


def test_rework_command_requires_needs_rework_verdict(task_env):
    root = task_env["root"]
    contract = task_env["contract"]
    create_task(root, "普通返工", risk="low", acceptance=_acceptance())
    start_task(root, "R1-P1-T001")
    _write_worker_files(contract, "R1-P1-T001")
    submit_task(root, "R1-P1-T001")
    reject_task(root, "R1-P1-T001", "普通验收不通过")

    with pytest.raises(TaskError, match="NEEDS_REWORK|review 任务"):
        rework_task(root, "R1-P1-T001")
    # 旧路径兼容：无 review NEEDS_REWORK 的 rejected 任务仍用 mf task start
    started = start_task(root, "R1-P1-T001")
    assert started["status"] == "in_progress"

    create_task(root, "提交中任务", risk="low", acceptance=_acceptance())
    start_task(root, "R1-P1-T002")
    _write_worker_files(contract, "R1-P1-T002")
    submit_task(root, "R1-P1-T002")
    with pytest.raises(TaskError, match="submitted"):
        rework_task(root, "R1-P1-T002")


def test_rework_resubmit_clears_stale_verdict_and_second_review_passes(task_env):
    from meta_flow import state

    root = task_env["root"]
    contract = task_env["contract"]
    result = create_task(
        root,
        "二次复审",
        risk="medium",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
    )
    task_id, review_id = result["task"], result["review_task"]
    start_task(root, task_id)
    _write_worker_files(contract, task_id)
    submit_task(root, task_id)
    start_task(root, review_id)
    _write_review_files(contract, review_id, "NEEDS_REWORK", scope="in-scope", requires="none")
    submit_task(root, review_id)
    accept_task(root, review_id, verdict="NEEDS_REWORK")

    rework_task(root, task_id)
    _write_worker_files(contract, task_id)
    submit_task(root, task_id)

    _, review = load_task(root, review_id)
    assert review["status"] == "ready"
    assert review["review_verdict"] is None
    _, task = load_task(root, task_id)
    assert task["status"] == "submitted"
    assert task["review_verdict"] is None

    start_task(root, review_id)
    _write_review_files(contract, review_id, "PASS")
    submit_task(root, review_id)

    # 即使 review 卡片被旧值污染，prompt/state 也必须以最新 handoff 为准
    review_yaml = (
        contract
        / "roadmap" / "R1" / "phases" / "P1" / "tasks" / f"T{review_id[-3:]}"
        / "TASK.yaml"
    )
    review_data = yaml.safe_load(review_yaml.read_text(encoding="utf-8"))
    review_data["review_verdict"] = "NEEDS_REWORK"
    review_yaml.write_text(
        yaml.safe_dump(review_data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    current = state.refresh_current(contract)
    detail = next(item for item in current["submitted_details"] if item["id"] == task_id)
    assert detail["review_status"] == "submitted"
    assert detail["review_verdict"] == "PASS"
    prompt = prompt_text(root, review_id)
    assert "不会自动重开" not in prompt

    accept_task(root, review_id, verdict="PASS")
    _, task = load_task(root, task_id)
    assert task["review_verdict"] == "PASS"
    accepted = accept_task(root, task_id, verdict="PASS")
    assert accepted["status"] == "accepted"


def test_rework_resubmit_then_manager_reject_does_not_deadlock(task_env):
    root = task_env["root"]
    contract = task_env["contract"]
    result = create_task(
        root,
        "复审前退回",
        risk="medium",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
    )
    task_id, review_id = result["task"], result["review_task"]
    start_task(root, task_id)
    _write_worker_files(contract, task_id)
    submit_task(root, task_id)
    start_task(root, review_id)
    _write_review_files(contract, review_id, "NEEDS_REWORK", scope="in-scope", requires="none")
    submit_task(root, review_id)
    accept_task(root, review_id, verdict="NEEDS_REWORK")
    rework_task(root, task_id)
    _write_worker_files(contract, task_id)
    submit_task(root, task_id)

    rejected = reject_task(root, task_id, "复审前调整范围")
    assert rejected["status"] == "rejected"
    assert rejected["review_verdict"] is None
    _, review = load_task(root, review_id)
    assert review["status"] == "ready"
    assert review["review_verdict"] is None

    prompt = prompt_text(root, task_id)
    assert "mf task start" in prompt
    assert "mf task rework" not in prompt
    started = start_task(root, task_id)
    assert started["status"] == "in_progress"


def test_rework_accepts_submitted_review_needs_rework(task_env):
    root = task_env["root"]
    contract = task_env["contract"]
    result = create_task(
        root,
        "提交中评审返工",
        risk="medium",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
    )
    task_id, review_id = result["task"], result["review_task"]
    start_task(root, task_id)
    _write_worker_files(contract, task_id)
    submit_task(root, task_id)
    start_task(root, review_id)
    _write_review_files(contract, review_id, "NEEDS_REWORK", scope="in-scope", requires="none")
    submit_task(root, review_id)

    rejected = reject_task(root, task_id, "manager 先退回返工")
    assert rejected["status"] == "rejected"
    assert rejected["rework"]["review_status"] == "submitted"
    _, review = load_task(root, review_id)
    assert review["status"] == "submitted"
    assert review["review_verdict"] is None

    from meta_flow import state

    current = state.refresh_current(contract)
    assert task_id in current["rework_tasks"]
    assert current["next_action"]["type"] == "execute_rework"

    started = rework_task(root, task_id)
    assert started["status"] == "in_progress"
    assert started["rework"]["review_status"] == "submitted"


def test_accept_review_while_rework_in_progress_preserves_lease_and_metadata(task_env):
    root = task_env["root"]
    contract = task_env["contract"]
    result = create_task(
        root,
        "先返工后接受",
        risk="medium",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
    )
    task_id, review_id = result["task"], result["review_task"]
    start_task(root, task_id)
    _write_worker_files(contract, task_id)
    submit_task(root, task_id)
    start_task(root, review_id)
    _write_review_files(contract, review_id, "NEEDS_REWORK", scope="in-scope", requires="none")
    submit_task(root, review_id)
    reject_task(root, task_id, "manager 先退回返工")
    rework_task(root, task_id)

    _, before = load_task(root, task_id)
    lease_before = dict(before["lease"])
    started_at_before = before["started_at"]
    rework_before = dict(before["rework"])
    accepted = accept_task(root, review_id, verdict="NEEDS_REWORK")
    decision = accepted["rework_decision"]
    assert decision["already_in_progress"] is True
    assert decision["lease_valid"] is True

    _, after = load_task(root, task_id)
    assert after["status"] == "in_progress"
    assert after["next_owner"] == "worker"
    assert after["lease"] == lease_before
    assert after["started_at"] == started_at_before
    assert after["rework"]["items"] == rework_before["items"]
    assert after["rework"]["allowed_paths"] == rework_before["allowed_paths"]
    assert after["rework"]["lease"] == rework_before["lease"]
    assert after["rework"]["started_at"] == rework_before["started_at"]
    assert after["rework"]["decision"] == rework_before["decision"]
    assert after["rework"]["review_status"] == "accepted"

    events = [
        json.loads(line)
        for line in (contract / "state" / "ledger.ndjson")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert not any(
        event.get("event") == "task.rework.decision_required"
        and event.get("task") == task_id
        for event in events
    )
    confirm = [
        event
        for event in events
        if event.get("event") == "task.rework.confirm"
        and event.get("task") == task_id
    ]
    assert confirm
    assert confirm[-1]["lease"] == lease_before["expires_at"]
    assert confirm[-1]["next_owner"] == "worker"

    _write_worker_files(contract, task_id)
    submitted = submit_task(root, task_id)
    assert submitted["status"] == "submitted"


def test_legacy_rejected_stale_verdict_recovers_with_start(task_env):
    root = task_env["root"]
    contract = task_env["contract"]
    result = create_task(
        root,
        "旧卡恢复",
        risk="medium",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
    )
    task_id, review_id = result["task"], result["review_task"]
    start_task(root, task_id)
    _write_worker_files(contract, task_id)
    submit_task(root, task_id)

    task_yaml = (
        contract
        / "roadmap" / "R1" / "phases" / "P1" / "tasks" / f"T{task_id[-3:]}"
        / "TASK.yaml"
    )
    task_data = yaml.safe_load(task_yaml.read_text(encoding="utf-8"))
    task_data.update(
        {
            "status": "rejected",
            "review_verdict": "NEEDS_REWORK",
            "lease": None,
            "rework": {
                "review_task": review_id,
                "review_verdict": "NEEDS_REWORK",
                "decision": "manager",
                "auto": False,
                "items": ["R1"],
                "allowed_paths": ["src/**"],
            },
        }
    )
    task_yaml.write_text(
        yaml.safe_dump(task_data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    review_yaml = (
        contract
        / "roadmap" / "R1" / "phases" / "P1" / "tasks" / f"T{review_id[-3:]}"
        / "TASK.yaml"
    )
    review_data = yaml.safe_load(review_yaml.read_text(encoding="utf-8"))
    review_data["status"] = "ready"
    review_data["review_verdict"] = None
    review_yaml.write_text(
        yaml.safe_dump(review_data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    with pytest.raises(TaskError, match="mf task start"):
        rework_task(root, task_id)
    from meta_flow import state

    current = state.refresh_current(contract)
    assert task_id not in current["rework_tasks"]
    assert task_id in current["stale_rework_tasks"]
    assert current["next_action"]["type"] == "recover_rework"
    assert "mf task start" in current["next_action"]["text"]
    started = start_task(root, task_id)
    assert started["status"] == "in_progress"
    _, task = load_task(root, task_id)
    assert task["review_verdict"] is None
    assert task["rework"]["stale"] is True
    events = [
        json.loads(line)
        for line in (contract / "state" / "ledger.ndjson")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert any(
        event.get("event") == "task.rework.stale" and event.get("task") == task_id
        for event in events
    )


def test_packet_and_list(task_env):
    root = task_env["root"]
    create_task(root, "文档修正", risk="low", acceptance=_acceptance())
    text = packet_text(root, "R1-P1-T001")
    assert "TASK PACKET R1-P1-T001" in text
    items = list_tasks(root)
    assert items[0]["id"] == "R1-P1-T001"


def test_submit_ignores_tool_caches_and_local_mfp(task_env):
    root = task_env["root"]
    contract = task_env["contract"]
    cache = root / ".pytest_cache" / "v" / "cache"
    cache.mkdir(parents=True)
    (cache / "nodeids").write_text("[]", encoding="utf-8")

    create_task(root, "文档修正", risk="low", acceptance=_acceptance())
    start_task(root, "R1-P1-T001")

    (cache / "nodeids").write_text('["changed"]', encoding="utf-8")
    (cache / "lastfailed").write_text("{}", encoding="utf-8")
    ruff_cache = root / ".ruff_cache" / "0.17.6"
    ruff_cache.mkdir(parents=True)
    (ruff_cache / "cache").write_text("x", encoding="utf-8")
    improvements = root / ".meta-flow" / "improvements"
    improvements.mkdir(parents=True)
    (improvements / "MFP-0001.yaml").write_text("id: MFP-0001\n", encoding="utf-8")

    _write_worker_files(contract, "R1-P1-T001")
    data = submit_task(root, "R1-P1-T001")
    assert data["status"] == "submitted"


def test_submit_ignores_legacy_snapshot_cache_entries(task_env):
    root = task_env["root"]
    contract = task_env["contract"]
    create_task(root, "文档修正", risk="low", acceptance=_acceptance())
    start_task(root, "R1-P1-T001")

    bundle = contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / "T001"
    snapshot = bundle / "evidence" / "worktree-start.json"
    data = json.loads(snapshot.read_text(encoding="utf-8"))
    data[".pytest_cache/v/cache/legacy"] = [1, 1]
    data[".ruff_cache/0.17.6/legacy"] = [1, 1]
    snapshot.write_text(json.dumps(data), encoding="utf-8")
    (root / ".pytest_cache" / "v" / "cache").mkdir(parents=True)
    (root / ".pytest_cache" / "v" / "cache" / "legacy").write_text("changed", encoding="utf-8")
    (root / ".ruff_cache" / "0.17.6").mkdir(parents=True)
    (root / ".ruff_cache" / "0.17.6" / "legacy").write_text("changed", encoding="utf-8")

    _write_worker_files(contract, "R1-P1-T001")
    data = submit_task(root, "R1-P1-T001")
    assert data["status"] == "submitted"


def test_parallel_tasks_submit_without_cross_contamination(task_env):
    root = task_env["root"]
    contract = task_env["contract"]
    create_task(
        root, "源码任务", risk="low", allowed_paths=["src/**"], acceptance=_acceptance()
    )
    create_task(
        root, "文档任务", risk="low", allowed_paths=["docs/**"], acceptance=_acceptance()
    )
    start_task(root, "R1-P1-T001")
    start_task(root, "R1-P1-T002")

    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("print('a')\n", encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "guide.md").write_text("# guide\n", encoding="utf-8")

    _write_worker_files(contract, "R1-P1-T001")
    first = submit_task(root, "R1-P1-T001")
    assert first["status"] == "submitted"
    ownership = json.loads(
        (
            contract
            / "roadmap" / "R1" / "phases" / "P1" / "tasks" / "T001"
            / "evidence" / "ownership.json"
        ).read_text(encoding="utf-8")
    )
    assert ownership["isolated_from"] == {"docs/guide.md": "R1-P1-T002"}

    _write_worker_files(contract, "R1-P1-T002")
    second = submit_task(root, "R1-P1-T002")
    assert second["status"] == "submitted"
    ownership = json.loads(
        (
            contract
            / "roadmap" / "R1" / "phases" / "P1" / "tasks" / "T002"
            / "evidence" / "ownership.json"
        ).read_text(encoding="utf-8")
    )
    assert ownership["isolated_from"] == {"src/main.py": "R1-P1-T001"}


def test_single_task_out_of_bounds_still_rejected(task_env):
    root = task_env["root"]
    contract = task_env["contract"]
    create_task(
        root, "源码任务", risk="low", allowed_paths=["src/**"], acceptance=_acceptance()
    )
    start_task(root, "R1-P1-T001")
    (root / "outside.txt").write_text("越界\n", encoding="utf-8")
    _write_worker_files(contract, "R1-P1-T001")
    with pytest.raises(TaskError, match="allowed_paths"):
        submit_task(root, "R1-P1-T001")


def test_packet_process_paths_budget_and_entry_index(task_env):
    root = task_env["root"]
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
    create_task(
        root,
        "大任务",
        risk="low",
        effort="XL",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
    )
    text = packet_text(root, "R1-P1-T001")
    assert "## Process paths (explicit)" in text
    assert "handoff:" in text and "dev-record:" in text and "evidence:" in text
    assert "与 allowed_paths/forbidden 独立" in text
    assert "budget: files=60" in text
    assert "## Code entry index" in text
    assert "src/main.py" in text
    assert "mf context expand" in text
    assert "review_gate" in text


def test_packet_knowledge_does_not_match_foreign_same_name_task(task_env):
    import yaml

    from meta_flow import knowledge

    root = task_env["root"]
    contract = task_env["contract"]
    knowledge.add_knowledge(root, "term", "契约库=共享真相")
    knowledge.add_knowledge(
        root,
        "convention",
        "ptm-team 负责 ptm-tde；本 contract 只记录验证任务 T001",
    )
    knowledge.add_knowledge(
        root, "convention", "R1-P1-T001 必须走任务包和独立评审"
    )
    # 模拟从其他项目复制、未带 project 字段的历史知识
    knowledge_path = contract / "knowledge" / "KNOWLEDGE.yaml"
    data = yaml.safe_load(knowledge_path.read_text(encoding="utf-8"))
    for item in data["conventions"]:
        if "ptm-team" in str(item.get("text")):
            item.pop("project", None)
    knowledge_path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    create_task(
        root, "任务包验证", risk="low", delivery="demo", acceptance=_acceptance()
    )
    text = packet_text(root, "R1-P1-T001")
    assert "契约库=共享真相" in text
    assert "ptm-team 负责" not in text
    assert "R1-P1-T001 必须走任务包" in text


def test_submit_reads_local_dev_record_and_handoff_fallback(task_env):
    root = task_env["root"]
    create_task(root, "本地记录", risk="low", acceptance=_acceptance())
    start_task(root, "R1-P1-T001")
    (root / ".meta-flow" / "dev-records").mkdir(parents=True)
    (root / ".meta-flow" / "handoffs").mkdir(parents=True)
    (root / ".meta-flow" / "dev-records" / "R1-P1-T001.md").write_text(
        "# dev\n实现完成\n", encoding="utf-8"
    )
    (root / ".meta-flow" / "handoffs" / "R1-P1-T001.md").write_text(
        "# handoff\n完成\n", encoding="utf-8"
    )
    data = submit_task(root, "R1-P1-T001")
    assert data["status"] == "submitted"


def test_next_action_prioritizes_inflight_and_review_gate(task_env):
    from meta_flow import state

    root = task_env["root"]
    contract = task_env["contract"]
    result = create_task(root, "安装器改动", risk="high", acceptance=_acceptance())
    task_id, review_id = result["task"], result["review_task"]

    start_task(root, task_id)
    current = state.refresh_current(contract)
    assert current["next_action"]["type"] == "follow_up_task"
    assert current["next_action"]["task"] == task_id

    _write_worker_files(contract, task_id)
    submit_task(root, task_id)
    current = state.refresh_current(contract)
    assert current["next_action"]["type"] == "review"
    assert current["next_action"]["task"] == review_id

    review_prompt = prompt_text(root, review_id)
    assert "PASS_WITH_RISK" in review_prompt
    assert "不得是实现者" in review_prompt


def test_allowed_path_dotfile_matches(task_env):
    root = task_env["root"]
    contract = task_env["contract"]
    create_task(
        root,
        "忽略规则",
        risk="low",
        allowed_paths=[".gitignore"],
        acceptance=_acceptance(),
    )
    start_task(root, "R1-P1-T001")
    (root / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    _write_worker_files(contract, "R1-P1-T001")
    data = submit_task(root, "R1-P1-T001")
    assert data["status"] == "submitted"


def test_review_packet_embeds_reviewed_evidence(task_env):
    import subprocess

    root = task_env["root"]
    contract = task_env["contract"]
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    result = create_task(
        root,
        "安装器改动",
        risk="high",
        allowed_paths=["src/**"],
        acceptance=_acceptance(),
    )
    task_id, review_id = result["task"], result["review_task"]
    start_task(root, task_id)
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("print('x')\n", encoding="utf-8")
    _write_worker_files(contract, task_id)
    submit_task(root, task_id)
    start_task(root, review_id)

    text = packet_text(root, review_id, review=True)
    assert "REVIEW PACKET" in text
    assert "实现完成" in text
    assert "# handoff" in text
    assert "diff --git" in text
    assert "src/app.py" in text
    assert "(missing)" not in text

    target_bundle = (
        contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / f"T{task_id[-3:]}"
    )
    (target_bundle / "evidence" / "diff.patch").unlink()
    with pytest.raises(TaskError, match="diff"):
        packet_text(root, review_id, review=True)


def test_diff_includes_untracked_owned_files(task_env):
    import subprocess

    root = task_env["root"]
    contract = task_env["contract"]
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    create_task(
        root, "新增文件", risk="low", allowed_paths=["src/**"], acceptance=_acceptance()
    )
    start_task(root, "R1-P1-T001")
    (root / "src").mkdir()
    (root / "src" / "new.py").write_text("print('new')\n", encoding="utf-8")
    _write_worker_files(contract, "R1-P1-T001")
    submit_task(root, "R1-P1-T001")
    bundle = contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / "T001"
    diff = (bundle / "evidence" / "diff.patch").read_text(encoding="utf-8")
    assert "src/new.py" in diff
    assert "new file mode" in diff or "--- /dev/null" in diff


def test_inactive_task_changes_rejected(task_env):
    root = task_env["root"]
    contract = task_env["contract"]
    create_task(
        root, "源码任务", risk="low", allowed_paths=["src/**"], acceptance=_acceptance()
    )
    start_task(root, "R1-P1-T001")
    (root / "src").mkdir()
    (root / "src" / "a.py").write_text("print('a')\n", encoding="utf-8")
    _write_worker_files(contract, "R1-P1-T001")
    submit_task(root, "R1-P1-T001")

    create_task(
        root, "文档任务", risk="low", allowed_paths=["docs/**"], acceptance=_acceptance()
    )
    start_task(root, "R1-P1-T002")
    # 非本任务、非活动（A 已提交且不与 B 重叠）的改动必须拒绝
    (root / "src" / "other.py").write_text("print('other')\n", encoding="utf-8")
    _write_worker_files(contract, "R1-P1-T002")
    with pytest.raises(TaskError, match="src/other.py"):
        submit_task(root, "R1-P1-T002")


def test_review_submit_requires_only_review_files(task_env):
    root = task_env["root"]
    contract = task_env["contract"]
    result = create_task(root, "安装器改动", risk="high", acceptance=_acceptance())
    task_id, review_id = result["task"], result["review_task"]
    start_task(root, task_id)
    _write_worker_files(contract, task_id)
    submit_task(root, task_id)

    start_task(root, review_id)
    bundle = (
        contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / f"T{review_id[-3:]}"
    )
    (bundle / "review.md").write_text("# review\nverdict: PASS\n", encoding="utf-8")
    (bundle / "review-handoff.md").write_text(
        "# review handoff\nverdict: PASS\n", encoding="utf-8"
    )
    data = submit_task(root, review_id)
    assert data["status"] == "submitted"
    assert not (bundle / "handoff.md").exists()


def test_implement_submit_still_requires_handoff(task_env):
    root = task_env["root"]
    contract = task_env["contract"]
    create_task(root, "文档任务", risk="low", acceptance=_acceptance())
    start_task(root, "R1-P1-T001")
    bundle = contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / "T001"
    (bundle / "dev-record.md").write_text("# dev\n完成\n", encoding="utf-8")
    with pytest.raises(TaskError, match="交接"):
        submit_task(root, "R1-P1-T001")


def test_rework_diff_keeps_original_task_changes(task_env):
    import subprocess

    root = task_env["root"]
    contract = task_env["contract"]
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    create_task(
        root, "返工证据", risk="low", allowed_paths=["src/**"], acceptance=_acceptance()
    )
    start_task(root, "R1-P1-T001")
    (root / "src").mkdir()
    (root / "src" / "first.py").write_text("print('first')\n", encoding="utf-8")
    _write_worker_files(contract, "R1-P1-T001")
    submit_task(root, "R1-P1-T001")

    reject_task(root, "R1-P1-T001", "证据需补")
    # 返工 start 会重置快照；证据 diff 仍必须覆盖返工前的 first.py
    start_task(root, "R1-P1-T001")
    (root / "src" / "second.py").write_text("print('second')\n", encoding="utf-8")
    _write_worker_files(contract, "R1-P1-T001")
    submit_task(root, "R1-P1-T001")

    bundle = contract / "roadmap" / "R1" / "phases" / "P1" / "tasks" / "T001"
    diff = (bundle / "evidence" / "diff.patch").read_text(encoding="utf-8")
    assert "src/first.py" in diff
    assert "src/second.py" in diff
