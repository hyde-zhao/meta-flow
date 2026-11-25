"""任务卡、评审任务与状态机测试。"""

from __future__ import annotations

import json

import pytest

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
