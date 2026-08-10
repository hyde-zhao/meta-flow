from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from meta_flow import cli
from meta_flow.execution_control.admission import (
    acquire_admission_lock,
    release_admission_lock,
)
from meta_flow.execution_control.contract import ExecutionUnitV1
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
from meta_flow.project.onboarding_contract import (
    AUTHORIZATION_KIND,
    AUTHORIZATION_SOURCE,
    OnboardingAuthorization,
)
from meta_flow.project.query import main as project_query_main
from meta_flow.work.budget import BudgetLimit
from meta_flow.work.cli import (
    classify_main,
    init_main,
    review_plan_main,
    status_main,
    transition_main,
    usage_add_main,
    validation_plan_main,
)
from meta_flow.work.io_metrics import IOMetrics
from meta_flow.work.lifecycle import update_work_status
from meta_flow.work.model import build_work, load_work, write_work_create_only
from meta_flow.work.read_context import OperationReadContext
from meta_flow.work.risk import RiskFacts, classify_work
from meta_flow.work.route_profile import RouteProfile
from meta_flow.work.scope import WorkScope
from meta_flow.work.store import (
    WorkInitApplyError,
    apply_work_init,
    close_work,
    plan_work_init,
    plan_work_init_from_release_root,
)


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
    plan = plan_project_init(request)
    payload = plan.as_dict()
    apply_project_init(
        plan,
        OnboardingAuthorization(
            1,
            "work-store-fixture",
            AUTHORIZATION_SOURCE,
            AUTHORIZATION_KIND,
            payload["operation"],
            payload["decision_ref"],
            payload["project_id"],
            payload["plan_digest"],
            payload["base_oids"],
            "2099-01-01T00:00:00+00:00",
        ),
    )
    process = root / "demo-process"
    git(process, "add", ".")
    git(
        process,
        "-c",
        "user.name=Meta Flow Test",
        "-c",
        "user.email=meta-flow@example.invalid",
        "commit",
        "-m",
        "initial process",
    )
    return release, process


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


def typed_work(work):
    return replace(
        work,
        execution_unit=ExecutionUnitV1(
            unit_id=work.work_id,
            root_concept="work-init",
            slice_id=work.work_id,
            container_role="primary",
            revision=1,
            supersedes_unit_id="",
            contract_ref=work.request_ref,
            contract_digest="c" * 64,
        ),
    )


def snapshot_domain_files(process: Path) -> dict[str, bytes]:
    return {
        path.relative_to(process).as_posix(): path.read_bytes()
        for path in sorted(process.rglob("*"))
        if path.is_file() and ".git" not in path.parts
    }


@pytest.mark.parametrize(
    ("target_state", "typed", "context_kind", "expected", "blocked"),
    (
        ("missing", False, "canonical", "BLOCKED_NEW_OBJECT_REQUIRES_EXECUTION_UNIT", True),
        ("missing", False, "legacy", "BLOCKED_NEW_OBJECT_REQUIRES_EXECUTION_UNIT", True),
        ("missing", True, "canonical", "ADMISSION_REQUIRED", False),
        ("missing", True, "legacy", "BLOCKED_EXECUTION_CONTEXT_REQUIRED", True),
        ("current", False, "canonical", "NOOP_GRANDFATHERED_READ_ONLY", False),
        ("current", False, "legacy", "NOOP_GRANDFATHERED_READ_ONLY", False),
        ("repair", False, "canonical", "BLOCKED_LEGACY_HISTORY_WRITE_FORBIDDEN", True),
        ("repair", False, "legacy", "BLOCKED_LEGACY_HISTORY_WRITE_FORBIDDEN", True),
        ("current", True, "canonical", "NOOP_TYPED_CURRENT", False),
        ("current", True, "legacy", "NOOP_TYPED_EXISTING_READ_ONLY", False),
        ("repair", True, "canonical", "TYPED_REPAIR_AFTER_ADMISSION", False),
        ("repair", True, "legacy", "BLOCKED_EXECUTION_CONTEXT_REQUIRED", True),
    ),
)
def test_work_init_revision7_closed_compatibility_matrix_is_zero_write(
    tmp_path: Path,
    target_state: str,
    typed: bool,
    context_kind: str,
    expected: str,
    blocked: bool,
) -> None:
    release, process = init_project(tmp_path)
    work = make_work(process)
    if typed:
        work = typed_work(work)
    if target_state in {"current", "repair"}:
        write_work_create_only(process, work)
    if target_state == "current":
        project = load_project(process)
        replace_project(
            process,
            replace(project, active_work_refs=(work.work_ref,)),
            expected_project_id=project.project_id,
        )

    before = snapshot_domain_files(process)
    plan = (
        plan_work_init_from_release_root(release, work)
        if context_kind == "canonical"
        else plan_work_init(process, work)
    )
    after = snapshot_domain_files(process)

    assert plan.compatibility_decision == expected
    assert plan.blocked is blocked
    assert before == after
    payload = plan.as_dict()
    assert payload["domain_mutation_count"] == 0
    assert payload["coordination_mutation_count"] == 0
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    assert str(release) not in rendered
    assert str(process) not in rendered


def test_work_init_dry_run_then_apply_indexes_project(tmp_path: Path) -> None:
    release, process = init_project(tmp_path)
    work = typed_work(make_work(process))

    plan = plan_work_init_from_release_root(release, work)
    assert not plan.blocked
    assert plan.as_dict()["mutation_count"] == 0
    assert not (process / work.work_ref).exists()

    receipt = apply_work_init(plan)

    assert receipt.decision == "PASS"
    assert receipt.domain_mutation_count == 2
    assert receipt.coordination_mutation_count == 2
    assert receipt.mutation_count == 4
    assert receipt.project_index_updated
    assert load_work(process, "W-001") == work
    assert load_project(process).active_work_refs == ("works/W-001/WORK.yaml",)
    snapshot, findings = load_governance_snapshot(process)
    assert findings == []
    assert snapshot is not None
    assert snapshot.objects_read == 2


def test_work_init_plan_reuses_project_and_request_in_one_snapshot(
    tmp_path: Path,
) -> None:
    _release, process = init_project(tmp_path)
    work = make_work(process)
    write_work_create_only(process, work)
    project = load_project(process)
    replace_project(
        process,
        replace(project, active_work_refs=(work.work_ref,)),
        expected_project_id=project.project_id,
    )
    metrics = IOMetrics("work-init-plan", enabled=True)
    context = OperationReadContext(
        process,
        operation_id="work-init-plan",
        operation_kind="plan",
        allowed_reads=("PROJECT.yaml", work.request_ref, work.work_ref),
        metrics=metrics,
    )

    first = plan_work_init(process, work, read_context=context)
    second = plan_work_init(process, work, read_context=context)

    assert first.plan_digest == second.plan_digest
    totals = metrics.summary()["totals"]
    assert totals["physical_reads"] == 2
    assert totals["cache_hits"] == 2


def test_work_init_is_idempotent(tmp_path: Path) -> None:
    release, process = init_project(tmp_path)
    work = typed_work(make_work(process))
    apply_work_init(plan_work_init_from_release_root(release, work))

    second = plan_work_init_from_release_root(release, work)
    receipt = apply_work_init(second)

    assert {action.action for action in second.actions} == {"noop"}
    assert receipt.mutation_count == 0
    assert not receipt.project_index_updated


def test_work_init_can_repair_matching_unindexed_work_after_partial_state(tmp_path: Path) -> None:
    release, process = init_project(tmp_path)
    work = typed_work(make_work(process))
    write_work_create_only(process, work)

    plan = plan_work_init_from_release_root(release, work)
    receipt = apply_work_init(plan)

    assert not plan.blocked
    assert receipt.domain_mutation_count == 1
    assert receipt.coordination_mutation_count == 2
    assert receipt.project_index_updated
    assert load_project(process).active_work_refs == (work.work_ref,)


def test_request_change_makes_work_plan_stale_before_mutation(tmp_path: Path) -> None:
    release, process = init_project(tmp_path)
    work = typed_work(make_work(process))
    plan = plan_work_init_from_release_root(release, work)
    (process / work.request_ref).write_text("changed\n", encoding="utf-8")

    with pytest.raises(WorkInitApplyError) as raised:
        apply_work_init(plan)

    assert raised.value.receipt.decision == "BLOCKED"
    assert raised.value.receipt.domain_mutation_count == 0
    assert raised.value.receipt.coordination_mutation_count == 2
    assert not (process / work.work_ref).exists()
    assert load_project(process).active_work_refs == ()


def test_work_init_lock_contention_blocks_without_domain_mutation(tmp_path: Path) -> None:
    release, process = init_project(tmp_path)
    work = typed_work(make_work(process))
    plan = plan_work_init_from_release_root(release, work)
    assert plan.admission_plan is not None
    git_common = process / git(process, "rev-parse", "--git-common-dir")
    held = acquire_admission_lock(
        git_common,
        plan.admission_plan,
        owner_token="independent-holder",
        owner_process_identity="test-holder",
    )
    assert held.decision == "PASS" and held.handle is not None
    try:
        with pytest.raises(WorkInitApplyError) as raised:
            apply_work_init(plan)
        receipt = raised.value.receipt
        assert receipt.decision == "BLOCKED"
        assert receipt.domain_mutation_count == 0
        assert receipt.coordination_mutation_count == 0
        assert receipt.durable_lock_count == 1
        assert not (process / work.work_ref).exists()
    finally:
        assert release_admission_lock(git_common, held.handle).decision == "PASS"


def test_work_init_reports_exact_partial_after_first_domain_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    release, process = init_project(tmp_path)
    work = typed_work(make_work(process))
    plan = plan_work_init_from_release_root(release, work)

    def fail_project(*_args, **_kwargs):
        raise OSError("injected project writer failure")

    monkeypatch.setattr("meta_flow.work.store.replace_project", fail_project)
    with pytest.raises(WorkInitApplyError) as raised:
        apply_work_init(plan)

    receipt = raised.value.receipt
    assert receipt.decision == "PARTIAL_MUTATION"
    assert receipt.domain_mutation_count == 1
    assert receipt.coordination_mutation_count == 2
    assert receipt.durable_refs == (work.work_ref,)
    assert receipt.recovery_route == "stop-and-inspect-partial-mutation"
    assert (process / work.work_ref).is_file()
    assert load_project(process).active_work_refs == ()


def test_work_plan_blocks_missing_or_out_of_scope_request(tmp_path: Path) -> None:
    release, process = init_project(tmp_path)
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

    plan = plan_work_init_from_release_root(release, typed_work(missing))

    assert plan.blocked
    assert {item.code for item in plan.conflicts} >= {"request_missing", "request_out_of_scope"}


def test_scope_declaration_cannot_exceed_profile_budget(tmp_path: Path) -> None:
    release, process = init_project(tmp_path)
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

    plan = plan_work_init_from_release_root(release, typed_work(work))

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
        "--execution-unit-id",
        "W-001",
        "--execution-root-concept",
        "work-init",
        "--execution-slice-id",
        "W-001",
        "--execution-container-role",
        "primary",
        "--execution-revision",
        "1",
        "--execution-contract-ref",
        request_ref,
        "--execution-contract-digest",
        "c" * 64,
    ]

    dry_code = init_main(common)
    dry_payload = json.loads(capsys.readouterr().out)
    assert dry_code == 0
    assert dry_payload["decision"] == "READY"
    assert dry_payload["mutation_count"] == 0
    assert dry_payload["route"] == {
        "decision": "READY",
        "mode": "routine-four-stage",
        "dispatch_mode": "direct",
        "stages": ["clarification", "design", "implementation", "verification"],
        "functional_agent_dispatches": 0,
        "legacy_cp_artifacts_allowed": False,
        "errors": [],
    }

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
    assert dispatched["work"]["route_profile"]["dispatch_mode"] == "direct"


def test_g0_functional_agent_override_blocks_before_root_resolution(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = init_main(
        [
            "--project-root",
            str(tmp_path / "missing-release"),
            "--work-id",
            "W-001",
            "--objective",
            "不应调度",
            "--request-ref",
            "works/W-001/REQUEST.md",
            "--change-kind",
            "documentation",
            "--touched-path-count",
            "1",
            "--dispatch-mode",
            "functional-agent",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert payload["decision"] == "BLOCKED"
    assert "explicit G2 upgrade" in payload["error"]
    assert not (tmp_path / "missing-release").exists()


def test_legacy_cp_route_requires_g2_formal_cr_gate_evidence_and_scope(tmp_path: Path) -> None:
    release, process = init_project(tmp_path)
    request_ref = make_request(process)
    gate_ref = "gates/G2-DESIGN.md"
    classification = classify_work(
        RiskFacts(change_kind="code", touched_path_count=4, public_contract=True),
        requested_cr=True,
        g2_budget=BudgetLimit(30, 30, 12, 160_000),
    )
    work = build_work(
        work_id="W-001",
        project_id="demo",
        objective="显式 legacy 兼容",
        request_ref=request_ref,
        scope=WorkScope(1, (request_ref, gate_ref), (), ("full",)),
        classification=classification,
        release_base_oid="a" * 40,
        process_base_oid="",
        route_profile=RouteProfile(
            mode="legacy-cp0-cp8",
            legacy_cp_compatibility=True,
        ),
    )
    work = typed_work(work)

    missing_ref = plan_work_init_from_release_root(release, work)
    missing_file = plan_work_init_from_release_root(
        release, work, human_design_gate_ref=gate_ref
    )
    gate_path = process / gate_ref
    gate_path.parent.mkdir(parents=True)
    gate_path.write_text("approved: true\n", encoding="utf-8")
    ready = plan_work_init_from_release_root(
        release, work, human_design_gate_ref=gate_ref
    )

    assert "route_profile_blocked" in {item.code for item in missing_ref.conflicts}
    assert "human_design_gate_missing" in {item.code for item in missing_file.conflicts}
    assert not ready.blocked
    assert ready.route_decision.stages == tuple(f"CP{index}" for index in range(9))


def test_usage_add_cli_records_over_limit_fact_then_blocks_mutation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release, process = init_project(tmp_path)
    work = typed_work(make_work(process))
    apply_work_init(plan_work_init_from_release_root(release, work))

    exit_code = usage_add_main(
        [
            "--project-root",
            str(release),
            "--work-id",
            "W-001",
            "--event-id",
            "usage-over-limit",
            "--stage",
            "implementation",
            "--reads",
            "9",
            "--tokens",
            "100",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["decision"] == "RECORDED_AND_BLOCKED"
    assert payload["appended"] is True
    assert payload["budget_decision"] == "EXCEEDED"
    ledger = json.loads(
        (process / "works" / "W-001" / "USAGE.json").read_text(encoding="utf-8")
    )
    assert ledger["events"][0]["event_id"] == "usage-over-limit"
    assert sum(event["reads"] for event in ledger["events"]) == 9


def test_work_start_pause_resume_and_close_minimally_updates_project(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release, process = init_project(tmp_path)
    work = typed_work(make_work(process))
    apply_work_init(plan_work_init_from_release_root(release, work))

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
    release, process = init_project(tmp_path)
    phase = Phase(1, "demo", "PH-001", "完成首个阶段", "active")
    write_phase_create_only(process, phase)
    project = load_project(process)
    replace_project(
        process,
        replace(project, active_phase_ref=phase.phase_ref),
        expected_project_id=project.project_id,
    )
    work = typed_work(replace(make_work(process), phase_ref=phase.phase_ref))

    receipt = apply_work_init(plan_work_init_from_release_root(release, work))

    assert receipt.domain_mutation_count == 3
    assert receipt.coordination_mutation_count == 2
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
    work = typed_work(make_work(process))
    apply_work_init(plan_work_init_from_release_root(release, work))
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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "meta_flow.execution_control.migration._receipt_path",
        lambda: tmp_path / "missing-provider-receipt.json",
    )
    release, process = init_project(tmp_path)
    work = typed_work(make_work(process))
    apply_work_init(plan_work_init_from_release_root(release, work))

    assert review_plan_main(
        ["--project-root", str(release), "--work-id", "W-001"]
    ) == 0
    review = json.loads(capsys.readouterr().out)
    assert review["review_mode"] == "self-check"
    assert review["max_independent_reviews"] == 0
    assert review["execution_control_mode"] == "enforce-new"
    assert review["provider_receipt_status"] == "MISSING"
    assert review["provider_readiness"] == "UNAVAILABLE_PENDING_CP7_CP8"

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
    assert validation["execution_control_mode"] == "enforce-new"
    assert validation["provider_readiness"] == "UNAVAILABLE_PENDING_CP7_CP8"

    assert project_query_main(["--project-root", str(release)]) == 0
    query = json.loads(capsys.readouterr().out)
    assert query["objects_read"] == 2
    assert query["work"]["work_id"] == "W-001"


def test_close_fails_without_result_and_keeps_work_active(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release, process = init_project(tmp_path)
    work = typed_work(make_work(process))
    apply_work_init(plan_work_init_from_release_root(release, work))
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
