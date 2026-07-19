from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from meta_flow import cli
from meta_flow.project.governance import (
    Phase,
    load_governance_snapshot,
    load_phase,
    write_phase_create_only,
)
from meta_flow.project.model import load_project, replace_project
from meta_flow.project.onboarding import (
    ProjectInitRequest,
    apply_project_init,
    plan_project_init,
)
from meta_flow.project.query import main as project_query_main
from meta_flow.work.cli import (
    classify_main,
    init_main,
    review_plan_main,
    status_main,
    transition_main,
    validation_plan_main,
)
from meta_flow.work.lifecycle import update_work_status
from meta_flow.work.model import build_work, load_work, write_work_create_only
from meta_flow.work.risk import RiskFacts, classify_work
from meta_flow.work.scope import WorkScope
from meta_flow.work.store import apply_work_init, close_work, plan_work_init


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def init_project(root: Path) -> tuple[Path, Path]:
    release = root / "demo"
    release.mkdir()
    git(release, "init", "-b", "main")
    (release / "README.md").write_text("# Demo\n", encoding="utf-8")
    git(release, "add", "README.md")
    git(
        release,
        "-c",
        "user.name=Meta Flow Test",
        "-c",
        "user.email=meta-flow@example.invalid",
        "commit",
        "-m",
        "initial",
    )
    request = ProjectInitRequest(release, "demo", "Demo")
    apply_project_init(plan_project_init(request))
    return release, root / "demo-process"


def make_request(process: Path, work_id: str = "W-001") -> str:
    ref = f"works/{work_id}/REQUEST.md"
    path = process / ref
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# 请求\n\n目标：更新 README。\n\n用户确认：是。\n",
        encoding="utf-8",
    )
    return ref


def make_work(process: Path, work_id: str = "W-001"):
    request_ref = make_request(process, work_id)
    return build_work(
        work_id=work_id,
        project_id="demo",
        objective="更新 README",
        request_ref=request_ref,
        scope=WorkScope(
            version=1,
            allowed_reads=(request_ref, "README.md"),
            allowed_writes=("README.md",),
            required_checks=("pytest-docs",),
        ),
        classification=classify_work(
            RiskFacts(change_kind="documentation", touched_path_count=1)
        ),
        release_base_oid="a" * 40,
        process_base_oid="",
    )


def test_work_init_dry_run_then_apply_indexes_project(tmp_path: Path) -> None:
    _release, process = init_project(tmp_path)
    work = make_work(process)

    plan = plan_work_init(process, work)
    assert not plan.blocked
    assert plan.as_dict()["mutation_count"] == 0
    assert not (process / work.work_ref).exists()

    receipt = apply_work_init(plan)

    assert receipt.decision == "PASS"
    assert receipt.mutation_count == 2
    assert receipt.project_index_updated
    assert load_work(process, "W-001") == work
    assert load_project(process).active_work_refs == ("works/W-001/WORK.yaml",)
    snapshot, findings = load_governance_snapshot(process)
    assert findings == []
    assert snapshot is not None
    assert snapshot.objects_read == 2


def test_work_init_is_idempotent(tmp_path: Path) -> None:
    _release, process = init_project(tmp_path)
    work = make_work(process)
    apply_work_init(plan_work_init(process, work))

    second = plan_work_init(process, work)
    receipt = apply_work_init(second)

    assert {action.action for action in second.actions} == {"noop"}
    assert receipt.mutation_count == 0
    assert not receipt.project_index_updated


def test_work_init_can_repair_matching_unindexed_work_after_partial_state(tmp_path: Path) -> None:
    _release, process = init_project(tmp_path)
    work = make_work(process)
    write_work_create_only(process, work)

    plan = plan_work_init(process, work)
    receipt = apply_work_init(plan)

    assert not plan.blocked
    assert receipt.mutation_count == 1
    assert receipt.project_index_updated
    assert load_project(process).active_work_refs == (work.work_ref,)


def test_request_change_makes_work_plan_stale_before_mutation(tmp_path: Path) -> None:
    _release, process = init_project(tmp_path)
    work = make_work(process)
    plan = plan_work_init(process, work)
    (process / work.request_ref).write_text("changed\n", encoding="utf-8")

    with pytest.raises(ValueError, match="stale"):
        apply_work_init(plan)

    assert not (process / work.work_ref).exists()
    assert load_project(process).active_work_refs == ()


def test_work_plan_blocks_missing_or_out_of_scope_request(tmp_path: Path) -> None:
    _release, process = init_project(tmp_path)
    missing = build_work(
        work_id="W-001",
        project_id="demo",
        objective="x",
        request_ref="works/W-001/REQUEST.md",
        scope=WorkScope(1, ("README.md",), ("README.md",), ()),
        classification=classify_work(
            RiskFacts(change_kind="documentation", touched_path_count=1)
        ),
        release_base_oid="a" * 40,
        process_base_oid="",
    )

    plan = plan_work_init(process, missing)

    assert plan.blocked
    assert {item.code for item in plan.conflicts} >= {"request_missing", "request_out_of_scope"}


def test_scope_declaration_cannot_exceed_profile_budget(tmp_path: Path) -> None:
    _release, process = init_project(tmp_path)
    request_ref = make_request(process)
    reads = (request_ref, *(f"docs/{index}.md" for index in range(8)))
    work = build_work(
        work_id="W-001",
        project_id="demo",
        objective="x",
        request_ref=request_ref,
        scope=WorkScope(1, reads, (), ()),
        classification=classify_work(
            RiskFacts(change_kind="documentation", touched_path_count=1)
        ),
        release_base_oid="a" * 40,
        process_base_oid="",
    )

    plan = plan_work_init(process, work)

    assert plan.blocked
    assert "read_scope_over_budget" in {item.code for item in plan.conflicts}


def test_work_classify_cli_reports_explainable_decision(capsys: pytest.CaptureFixture[str]) -> None:
    code = classify_main(
        [
            "--change-kind",
            "documentation",
            "--touched-path-count",
            "1",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["container_kind"] == "work"
    assert payload["risk_profile"] == "G0"
    assert payload["budget"] == {
        "reads": 8,
        "writes": 8,
        "check_groups": 3,
        "tokens": 32_000,
    }
    assert payload["cannot_silently_downgrade"] is True


def test_work_cli_end_to_end_and_top_level_dispatch(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    release, process = init_project(tmp_path)
    request_ref = make_request(process)
    common = [
        "--project-root",
        str(release),
        "--work-id",
        "W-001",
        "--objective",
        "更新 README",
        "--request-ref",
        request_ref,
        "--allowed-read",
        request_ref,
        "--allowed-read",
        "README.md",
        "--allowed-write",
        "README.md",
        "--required-check",
        "pytest-docs",
        "--change-kind",
        "documentation",
        "--touched-path-count",
        "1",
    ]

    dry_code = init_main(common)
    dry_payload = json.loads(capsys.readouterr().out)
    assert dry_code == 0
    assert dry_payload["decision"] == "READY"
    assert dry_payload["mutation_count"] == 0

    apply_code = init_main([*common, "--apply"])
    apply_payload = json.loads(capsys.readouterr().out)
    assert apply_code == 0
    assert apply_payload["receipt"]["decision"] == "PASS"

    status_code = status_main(
        ["--project-root", str(release), "--work-id", "W-001"]
    )
    status_payload = json.loads(capsys.readouterr().out)
    assert status_code == 0
    assert status_payload["default_objects_read"] == 1
    assert status_payload["work"]["work_id"] == "W-001"

    with pytest.raises(SystemExit) as raised:
        cli._run_work(["status", "--project-root", str(release), "--work-id", "W-001"])
    dispatched = json.loads(capsys.readouterr().out)
    assert raised.value.code == 0
    assert dispatched["work"]["risk_profile"] == "G0"


def test_work_start_pause_resume_and_close_minimally_updates_project(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release, process = init_project(tmp_path)
    work = make_work(process)
    apply_work_init(plan_work_init(process, work))

    assert transition_main(
        "start", ["--project-root", str(release), "--work-id", "W-001"]
    ) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "active"
    assert transition_main(
        "pause", ["--project-root", str(release), "--work-id", "W-001"]
    ) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "paused"
    assert (process / "works" / "W-001" / "HANDOFF.yaml").is_file()
    assert transition_main(
        "resume", ["--project-root", str(release), "--work-id", "W-001"]
    ) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "active"

    result_ref = "works/W-001/RESULT.json"
    (process / result_ref).write_text(
        json.dumps({"schema_version": 1, "work_id": "W-001", "decision": "PASS"}) + "\n",
        encoding="utf-8",
    )
    assert transition_main(
        "close",
        [
            "--project-root",
            str(release),
            "--work-id",
            "W-001",
            "--result-ref",
            result_ref,
        ],
    ) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "completed"
    assert load_work(process, "W-001").result_ref == result_ref
    assert load_project(process).active_work_refs == ()


def test_phase_work_index_is_added_on_init_and_projected_on_close(tmp_path: Path) -> None:
    _release, process = init_project(tmp_path)
    phase = Phase(1, "demo", "PH-001", "完成首个阶段", "active")
    write_phase_create_only(process, phase)
    project = load_project(process)
    replace_project(
        process,
        replace(project, active_phase_ref=phase.phase_ref),
        expected_project_id=project.project_id,
    )
    work = replace(make_work(process), phase_ref=phase.phase_ref)

    receipt = apply_work_init(plan_work_init(process, work))

    assert receipt.mutation_count == 3
    assert load_phase(process, phase.phase_ref).work_refs == (work.work_ref,)
    update_work_status(
        process,
        work.work_id,
        expected_status="planned",
        new_status="active",
    )
    result_ref = "works/W-001/RESULT.json"
    (process / result_ref).write_text(
        json.dumps({"schema_version": 1, "work_id": "W-001", "decision": "PASS"}) + "\n",
        encoding="utf-8",
    )
    # 模拟 Work 真相已落盘、Project/Phase 投影尚未更新的中断现场。
    update_work_status(
        process,
        work.work_id,
        expected_status="active",
        new_status="completed",
        result_ref=result_ref,
    )
    assert load_project(process).active_work_refs == (work.work_ref,)
    assert load_phase(process, phase.phase_ref).work_refs == (work.work_ref,)
    close_work(
        process,
        work.work_id,
        expected_status="active",
        outcome="completed",
        result_ref=result_ref,
    )

    projected = load_phase(process, phase.phase_ref)
    assert projected.work_refs == ()
    assert projected.result_refs == (result_ref,)
    assert load_project(process).active_work_refs == ()


def test_resume_blocks_after_release_oid_drift(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release, process = init_project(tmp_path)
    work = make_work(process)
    apply_work_init(plan_work_init(process, work))
    transition_main("start", ["--project-root", str(release), "--work-id", "W-001"])
    capsys.readouterr()
    transition_main("pause", ["--project-root", str(release), "--work-id", "W-001"])
    capsys.readouterr()
    (release / "drift.txt").write_text("drift\n", encoding="utf-8")
    git(release, "add", "drift.txt")
    git(
        release,
        "-c",
        "user.name=Meta Flow Test",
        "-c",
        "user.email=meta-flow@example.invalid",
        "commit",
        "-m",
        "drift",
    )

    code = transition_main(
        "resume", ["--project-root", str(release), "--work-id", "W-001"]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert "release_oid_mismatch" in payload["error"]
    assert load_work(process, "W-001").status == "paused"


def test_review_and_validation_cli_are_work_scoped(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release, process = init_project(tmp_path)
    apply_work_init(plan_work_init(process, make_work(process)))

    assert review_plan_main(
        ["--project-root", str(release), "--work-id", "W-001"]
    ) == 0
    review = json.loads(capsys.readouterr().out)
    assert review["review_mode"] == "self-check"
    assert review["max_independent_reviews"] == 0

    assert validation_plan_main(
        [
            "--project-root",
            str(release),
            "--work-id",
            "W-001",
            "--check-risk",
            "pytest-docs=覆盖文档行为",
        ]
    ) == 0
    validation = json.loads(capsys.readouterr().out)
    assert validation["decision"] == "READY"
    assert validation["check_ids"] == ["pytest-docs"]

    assert project_query_main(["--project-root", str(release)]) == 0
    query = json.loads(capsys.readouterr().out)
    assert query["objects_read"] == 2
    assert query["work"]["work_id"] == "W-001"


def test_close_fails_without_result_and_keeps_work_active(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release, process = init_project(tmp_path)
    work = make_work(process)
    apply_work_init(plan_work_init(process, work))
    transition_main("start", ["--project-root", str(release), "--work-id", "W-001"])
    capsys.readouterr()

    code = transition_main(
        "close", ["--project-root", str(release), "--work-id", "W-001"]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert payload["decision"] == "BLOCKED"
    assert load_work(process, "W-001").status == "active"
    assert load_project(process).active_work_refs == ("works/W-001/WORK.yaml",)
