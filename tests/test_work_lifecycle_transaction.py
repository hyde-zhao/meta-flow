from __future__ import annotations

import base64
import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from meta_flow.execution_control.contract import ExecutionUnitV1
from meta_flow.project.governance import (
    Phase,
    Roadmap,
    load_phase,
    replace_phase,
    write_phase_create_only,
    write_roadmap_create_only,
)
from meta_flow.project.governance_projection import (
    GOVERNANCE_PROJECTION_REL,
    ImmutableCommitRole,
    build_governance_projection,
    semantic_digest,
    validate_governance_projection,
)
from meta_flow.project.model import load_project, replace_project
from meta_flow.project.onboarding import (
    ProjectInitRequest,
    apply_project_init,
    plan_project_init,
)
from meta_flow.project.onboarding_contract import (
    AUTHORIZATION_KIND as PROJECT_AUTHORIZATION_KIND,
)
from meta_flow.project.onboarding_contract import (
    AUTHORIZATION_SOURCE,
    OnboardingAuthorization,
)
from meta_flow.state import current as state_current
from meta_flow.state.projection_transaction import (
    acquire_transaction_lock,
    release_transaction_lock,
    state_projection_lock_path,
)
from meta_flow.work.cli import init_inspect_main, init_recover_main
from meta_flow.work.lifecycle import update_work_status
from meta_flow.work.lifecycle_transaction import (
    AUTHORIZATION_KIND,
    WorkCloseAuthorizationV1,
    acquire_shared_projection_writer_lock,
    apply_work_close,
    inspect_work_close_transactions,
    plan_work_close,
    recover_work_close_transaction,
    release_shared_projection_writer_lock,
)
from meta_flow.work.model import build_work, load_work, write_work_create_only
from meta_flow.work.risk import RiskFacts, classify_work
from meta_flow.work.scope import WorkScope
from meta_flow.work.store import (
    WorkInitApplyError,
    apply_work_init,
    plan_legacy_partial_work_init_recovery,
    plan_work_init_from_release_root,
)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def init_project(root: Path) -> tuple[Path, Path]:
    release = root / "demo"
    release.mkdir()
    _git(release, "init", "-b", "main")
    (release / "README.md").write_text("# Demo\n", encoding="utf-8")
    _git(release, "add", "README.md")
    _git(
        release,
        "-c",
        "user.name=Meta Flow Test",
        "-c",
        "user.email=meta-flow@example.invalid",
        "commit",
        "-m",
        "initial",
    )
    plan = plan_project_init(ProjectInitRequest(release, "demo", "Demo"))
    payload = plan.as_dict()
    apply_project_init(
        plan,
        OnboardingAuthorization(
            1,
            "work-close-fixture",
            AUTHORIZATION_SOURCE,
            PROJECT_AUTHORIZATION_KIND,
            payload["operation"],
            payload["decision_ref"],
            payload["project_id"],
            payload["plan_digest"],
            payload["base_oids"],
            "2099-01-01T00:00:00+00:00",
        ),
    )
    process = root / "demo-process"
    _git(process, "add", ".")
    _git(
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


def make_work(process: Path, work_id: str = "W-001", phase_ref: str = ""):
    request_ref = f"works/{work_id}/REQUEST.md"
    request_path = process / request_ref
    request_path.parent.mkdir(parents=True)
    request_path.write_text("# 请求\n\n用户确认：是。\n", encoding="utf-8")
    work = build_work(
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
        classification=classify_work(RiskFacts(change_kind="documentation", touched_path_count=1)),
        release_base_oid="a" * 40,
        process_base_oid="",
        phase_ref=phase_ref,
    )
    return replace(
        work,
        execution_unit=ExecutionUnitV1(
            unit_id=work.work_id,
            root_concept="work-close",
            slice_id=work.work_id,
            container_role="primary",
            revision=1,
            supersedes_unit_id="",
            contract_ref=request_ref,
            contract_digest="c" * 64,
        ),
    )


def _authorization(plan, authorization_id: str) -> WorkCloseAuthorizationV1:
    return WorkCloseAuthorizationV1(
        1,
        AUTHORIZATION_KIND,
        authorization_id,
        plan.work_id,
        plan.plan_digest,
        tuple(target.ref for target in plan.targets),
        "2099-01-01T00:00:00+00:00",
    )


def _active_fixture(tmp_path: Path) -> tuple[Path, Path, str]:
    release, process = init_project(tmp_path)
    work = make_work(process)
    apply_work_init(plan_work_init_from_release_root(release, work))
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
    return release, process, result_ref


def _governance_fixture(tmp_path: Path) -> tuple[Path, Path, Phase]:
    release, process = init_project(tmp_path)
    phase = Phase(
        1,
        "demo",
        "P1",
        "验证 Work close generation 与治理投影一致性",
        "active",
        result_refs=(GOVERNANCE_PROJECTION_REL.as_posix(),),
    )
    write_phase_create_only(process, phase)
    write_roadmap_create_only(
        process,
        Roadmap(1, "demo", "完成通用事务验证", "active", (phase.phase_ref,)),
    )
    project = load_project(process)
    replace_project(
        process,
        replace(
            project,
            roadmap_ref="ROADMAP.yaml",
            active_phase_ref=phase.phase_ref,
        ),
        expected_project_id=project.project_id,
    )
    roles = (
        ImmutableCommitRole("release_input", "release", _git(release, "rev-parse", "HEAD")),
        ImmutableCommitRole("process_input", "process", _git(process, "rev-parse", "HEAD")),
    )
    projection = build_governance_projection(process, roles)
    projection_path = process / GOVERNANCE_PROJECTION_REL
    projection_path.parent.mkdir(parents=True, exist_ok=True)
    projection_path.write_text(
        json.dumps(projection, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return release, process, phase


def _enable_state_projection(release: Path, process: Path) -> dict[str, bytes]:
    (process / "changes").mkdir(exist_ok=True)
    state_current.init_current_state(release, project_id="demo")
    state_current.render_state_file(release, force=True)
    state_current.refresh_current_entry(release)
    state_current.refresh_formal_truth_projection(release)
    return {
        path.relative_to(process).as_posix(): path.read_bytes()
        for path in (process / "state").glob("*-LEDGER.ndjson")
    }


def _close_phase_work(
    release: Path,
    process: Path,
    phase: Phase,
    work_id: str,
):
    work = make_work(process, work_id, phase.phase_ref)
    apply_work_init(plan_work_init_from_release_root(release, work))
    update_work_status(process, work_id, expected_status="planned", new_status="active")
    result_ref = f"works/{work_id}/RESULT.json"
    (process / result_ref).write_text(
        json.dumps({"schema_version": 1, "work_id": work_id, "decision": "PASS"}) + "\n",
        encoding="utf-8",
    )
    plan = plan_work_close(
        process,
        work_id,
        expected_status="active",
        outcome="completed",
        result_ref=result_ref,
    )
    receipt = apply_work_close(
        process,
        plan,
        _authorization(plan, f"close-{work_id.lower()}"),
    )
    return plan, receipt


def _prepare_phase_work(
    release: Path,
    process: Path,
    phase: Phase,
    work_id: str,
) -> str:
    work = make_work(process, work_id, phase.phase_ref)
    apply_work_init(plan_work_init_from_release_root(release, work))
    update_work_status(process, work_id, expected_status="planned", new_status="active")
    result_ref = f"works/{work_id}/RESULT.json"
    (process / result_ref).write_text(
        json.dumps({"schema_version": 1, "work_id": work_id, "decision": "PASS"}) + "\n",
        encoding="utf-8",
    )
    return result_ref


def _close_prepared_phase_work(
    process: Path,
    work_id: str,
    result_ref: str,
):
    plan = plan_work_close(
        process,
        work_id,
        expected_status="active",
        outcome="completed",
        result_ref=result_ref,
    )
    receipt = apply_work_close(
        process,
        plan,
        _authorization(plan, f"close-{work_id.lower()}"),
    )
    return plan, receipt


def _close_cancelled_phase_work(
    release: Path,
    process: Path,
    phase: Phase,
    work_id: str,
) -> None:
    work = make_work(process, work_id, phase.phase_ref)
    apply_work_init(plan_work_init_from_release_root(release, work))
    update_work_status(process, work_id, expected_status="planned", new_status="active")
    plan = plan_work_close(
        process,
        work_id,
        expected_status="active",
        outcome="cancelled",
    )
    receipt = apply_work_close(
        process,
        plan,
        _authorization(plan, f"close-{work_id.lower()}"),
    )
    assert receipt.decision == "PASS"


def _convert_two_closes_to_duplicate_legacy_generation(process: Path) -> None:
    transaction_root = process / ".meta-flow-runtime/work-close/transactions"
    manifests = []
    for path in sorted(transaction_root.glob("close-w-*/manifest.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload.pop("lineage", None)
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        manifests.append(payload)
    assert len(manifests) == 2
    for ref in ("PROJECT.yaml", "phases/P1/PHASE.yaml"):
        digests = {
            next(target for target in item["targets"] if target["ref"] == ref)[
                "after_digest"
            ]
            for item in manifests
        }
        assert len(digests) == 1
    successor_root = process / ".meta-flow-runtime/work-close/successors"
    if successor_root.is_dir():
        for path in successor_root.glob("*.json"):
            path.unlink()


def test_plan_is_zero_write_and_binds_every_projection_target(tmp_path: Path) -> None:
    _release, process, result_ref = _active_fixture(tmp_path)
    before = {
        path.relative_to(process).as_posix(): path.read_bytes()
        for path in process.rglob("*")
        if path.is_file() and ".git" not in path.parts
    }

    plan = plan_work_close(
        process,
        "W-001",
        expected_status="active",
        outcome="completed",
        result_ref=result_ref,
    )

    after = {
        path.relative_to(process).as_posix(): path.read_bytes()
        for path in process.rglob("*")
        if path.is_file() and ".git" not in path.parts
    }
    assert plan.ready
    assert [target.ref for target in plan.targets] == [
        "works/W-001/WORK.yaml",
        "PROJECT.yaml",
    ]
    assert before == after


def test_apply_commits_work_and_project_under_one_consumed_authorization(
    tmp_path: Path,
) -> None:
    _release, process, result_ref = _active_fixture(tmp_path)
    plan = plan_work_close(
        process,
        "W-001",
        expected_status="active",
        outcome="completed",
        result_ref=result_ref,
    )

    receipt = apply_work_close(process, plan, _authorization(plan, "close-success"))

    assert receipt.decision == "PASS"
    assert receipt.applied_refs == ("works/W-001/WORK.yaml", "PROJECT.yaml")
    assert load_work(process, "W-001").status == "completed"
    assert load_project(process).active_work_refs == ()
    assert inspect_work_close_transactions(process)["decision"] == "PASS"


def test_direct_project_work_close_atomically_refreshes_initialized_state(
    tmp_path: Path,
) -> None:
    release, process, _phase = _governance_fixture(tmp_path)
    work = make_work(process)
    apply_work_init(plan_work_init_from_release_root(release, work))
    update_work_status(
        process,
        work.work_id,
        expected_status="planned",
        new_status="active",
    )
    result_ref = "works/W-001/RESULT.json"
    (process / result_ref).write_text(
        json.dumps({"schema_version": 1, "work_id": "W-001", "decision": "PASS"})
        + "\n",
        encoding="utf-8",
    )
    _enable_state_projection(release, process)
    state_before = state_current.load_current_state(release)["formal_truth_projection"]

    plan = plan_work_close(
        process,
        "W-001",
        expected_status="active",
        outcome="completed",
        result_ref=result_ref,
    )

    assert plan.ready, plan.blockers
    assert [target.ref for target in plan.targets] == [
        "works/W-001/WORK.yaml",
        "PROJECT.yaml",
        "state/STATE.current.json",
        "STATE.md",
    ]
    receipt = apply_work_close(
        process,
        plan,
        _authorization(plan, "close-direct-with-state"),
    )

    assert receipt.decision == "PASS"
    assert receipt.mutation_count == 4
    state_after = state_current.load_current_state(release)["formal_truth_projection"]
    assert state_after["active_work_ids"] == []
    assert state_after["source_digest"] != state_before["source_digest"]
    errors, _warnings = state_current.check_current_state(release, mode="enforce")
    assert errors == []
    retry = plan_work_close(
        process,
        "W-001",
        expected_status="active",
        outcome="completed",
        result_ref=result_ref,
    )
    assert retry.ready
    assert retry.targets == ()


def test_stale_or_retargeted_authorization_blocks_before_writer(tmp_path: Path) -> None:
    _release, process, result_ref = _active_fixture(tmp_path)
    plan = plan_work_close(
        process,
        "W-001",
        expected_status="active",
        outcome="completed",
        result_ref=result_ref,
    )
    invalid = WorkCloseAuthorizationV1(
        1,
        AUTHORIZATION_KIND,
        "close-retargeted",
        plan.work_id,
        plan.plan_digest,
        ("PROJECT.yaml",),
        "2099-01-01T00:00:00+00:00",
    )
    work_before = (process / "works/W-001/WORK.yaml").read_bytes()

    try:
        apply_work_close(process, plan, invalid)
    except ValueError as exc:
        assert "target_refs mismatch" in str(exc)
    else:
        raise AssertionError("retargeted authorization was accepted")

    assert (process / "works/W-001/WORK.yaml").read_bytes() == work_before
    assert not (process / ".meta-flow-runtime/work-close/writer.lock").exists()
    assert not (
        process
        / ".meta-flow-runtime/work-close/transactions/close-retargeted/manifest.json"
    ).exists()


def test_second_target_failure_rolls_back_first_target(tmp_path: Path) -> None:
    _release, process, result_ref = _active_fixture(tmp_path)
    plan = plan_work_close(
        process,
        "W-001",
        expected_status="active",
        outcome="completed",
        result_ref=result_ref,
    )
    work_before = (process / "works/W-001/WORK.yaml").read_bytes()
    project_before = (process / "PROJECT.yaml").read_bytes()
    from meta_flow.work import lifecycle_transaction

    real_replace = lifecycle_transaction._replace_bytes
    calls = 0

    def fail_second(path: Path, content: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected second target failure")
        real_replace(path, content)

    with patch.object(lifecycle_transaction, "_replace_bytes", side_effect=fail_second):
        receipt = apply_work_close(
            process,
            plan,
            _authorization(plan, "close-recovered"),
        )

    assert receipt.decision == "RECOVERED"
    assert receipt.recovery_required is False
    assert (process / "works/W-001/WORK.yaml").read_bytes() == work_before
    assert (process / "PROJECT.yaml").read_bytes() == project_before
    assert inspect_work_close_transactions(process)["decision"] == "PASS"


def test_replace_before_accounting_failure_never_reports_false_recovery(
    tmp_path: Path,
) -> None:
    _release, process, result_ref = _active_fixture(tmp_path)
    plan = plan_work_close(
        process,
        "W-001",
        expected_status="active",
        outcome="completed",
        result_ref=result_ref,
    )
    work_before = (process / "works/W-001/WORK.yaml").read_bytes()
    project_before = (process / "PROJECT.yaml").read_bytes()
    from meta_flow.work import lifecycle_transaction

    real_replace = lifecycle_transaction._replace_bytes
    calls = 0

    def fail_after_first_replace(path: Path, content: bytes) -> None:
        nonlocal calls
        calls += 1
        real_replace(path, content)
        if calls == 1:
            raise OSError("injected failure after target replace before applied accounting")

    with patch.object(
        lifecycle_transaction,
        "_replace_bytes",
        side_effect=fail_after_first_replace,
    ):
        receipt = apply_work_close(
            process,
            plan,
            _authorization(plan, "close-after-replace-recovered"),
        )

    assert receipt.decision == "RECOVERED"
    assert (process / "works/W-001/WORK.yaml").read_bytes() == work_before
    assert (process / "PROJECT.yaml").read_bytes() == project_before
    assert inspect_work_close_transactions(process)["decision"] == "PASS"


def test_hard_interrupt_after_replace_is_recovered_from_durable_attempt(
    tmp_path: Path,
) -> None:
    _release, process, result_ref = _active_fixture(tmp_path)
    plan = plan_work_close(
        process,
        "W-001",
        expected_status="active",
        outcome="completed",
        result_ref=result_ref,
    )
    work_before = (process / "works/W-001/WORK.yaml").read_bytes()
    project_before = (process / "PROJECT.yaml").read_bytes()
    authorization_id = "close-hard-interrupt"
    from meta_flow.work import lifecycle_transaction

    real_replace = lifecycle_transaction._replace_bytes
    calls = 0

    def interrupt_after_first_replace(path: Path, content: bytes) -> None:
        nonlocal calls
        calls += 1
        real_replace(path, content)
        if calls == 1:
            raise KeyboardInterrupt("simulated process interruption")

    with patch.object(
        lifecycle_transaction,
        "_replace_bytes",
        side_effect=interrupt_after_first_replace,
    ):
        with pytest.raises(KeyboardInterrupt, match="process interruption"):
            apply_work_close(
                process,
                plan,
                _authorization(plan, authorization_id),
            )

    assert (process / "works/W-001/WORK.yaml").read_bytes() != work_before
    assert inspect_work_close_transactions(process)["decision"] == "BLOCKED"

    recovered = recover_work_close_transaction(process, authorization_id)

    assert recovered.decision == "RECOVERED"
    assert (process / "works/W-001/WORK.yaml").read_bytes() == work_before
    assert (process / "PROJECT.yaml").read_bytes() == project_before
    assert inspect_work_close_transactions(process)["decision"] == "PASS"


def test_partial_transaction_is_blocked_and_can_retry_recovery(tmp_path: Path) -> None:
    _release, process, result_ref = _active_fixture(tmp_path)
    plan = plan_work_close(
        process,
        "W-001",
        expected_status="active",
        outcome="completed",
        result_ref=result_ref,
    )
    authorization_id = "close-partial-retry"
    receipt = apply_work_close(
        process,
        plan,
        _authorization(plan, authorization_id),
    )
    assert receipt.decision == "PASS"
    manifest_path = (
        process / ".meta-flow-runtime/work-close/transactions" / authorization_id / "manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["state"] = "PARTIAL"
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    assert inspect_work_close_transactions(process)["decision"] == "BLOCKED"
    recovered = recover_work_close_transaction(process, authorization_id)

    assert recovered.decision == "RECOVERED"
    assert inspect_work_close_transactions(process)["decision"] == "PASS"


def test_recovery_rejects_manifest_target_outside_fixed_projector(
    tmp_path: Path,
) -> None:
    _release, process, result_ref = _active_fixture(tmp_path)
    plan = plan_work_close(
        process,
        "W-001",
        expected_status="active",
        outcome="completed",
        result_ref=result_ref,
    )
    authorization_id = "close-poisoned"
    receipt = apply_work_close(
        process,
        plan,
        _authorization(plan, authorization_id),
    )
    assert receipt.decision == "PASS"
    manifest_path = (
        process / ".meta-flow-runtime/work-close/transactions" / authorization_id / "manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["targets"][0]["ref"] = "../../outside.txt"
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("protected\n", encoding="utf-8")

    try:
        recover_work_close_transaction(process, authorization_id)
    except ValueError as exc:
        assert "outside fixed projector" in str(exc)
    else:
        raise AssertionError("poisoned recovery target was accepted")

    assert outside.read_text(encoding="utf-8") == "protected\n"
    assert inspect_work_close_transactions(process)["decision"] == "BLOCKED"


def test_close_atomically_refreshes_governance_baseline(tmp_path: Path) -> None:
    release, process, phase = _governance_fixture(tmp_path)

    plan, receipt = _close_phase_work(release, process, phase, "W-001")

    assert plan.ready, plan.blockers
    assert [target.ref for target in plan.targets] == [
        "works/W-001/WORK.yaml",
        "PROJECT.yaml",
        phase.phase_ref,
        GOVERNANCE_PROJECTION_REL.as_posix(),
    ]
    assert receipt.decision == "PASS"
    assert validate_governance_projection(release, process)["decision"] == "PASS"
    assert inspect_work_close_transactions(process)["decision"] == "PASS"


def test_close_atomically_converges_existing_state_current_and_human_summary(
    tmp_path: Path,
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    work = make_work(process, "W-001", phase.phase_ref)
    apply_work_init(plan_work_init_from_release_root(release, work))
    update_work_status(process, "W-001", expected_status="planned", new_status="active")
    unrelated_ledgers = _enable_state_projection(release, process)
    result_ref = "works/W-001/RESULT.json"
    (process / result_ref).write_text(
        json.dumps({"schema_version": 1, "work_id": "W-001", "decision": "PASS"}) + "\n",
        encoding="utf-8",
    )
    current_before = (process / "current/CURRENT.json").read_bytes()

    plan, receipt = _close_prepared_phase_work(process, "W-001", result_ref)

    assert receipt.decision == "PASS"
    assert [target.ref for target in plan.targets] == [
        "works/W-001/WORK.yaml",
        "PROJECT.yaml",
        phase.phase_ref,
        GOVERNANCE_PROJECTION_REL.as_posix(),
        "state/STATE.current.json",
        "STATE.md",
    ]
    errors, warnings = state_current.check_current_state(release, mode="enforce")
    assert errors == []
    assert warnings == []
    assert state_current.validate_current_projection(release) == []
    assert (process / "current/CURRENT.json").read_bytes() == current_before
    state = state_current.load_current_state(release)
    assert state["formal_truth_projection"]["active_work_ids"] == []
    assert state["next_action"]["type"] == "continue_active_phase"
    assert {
        path.relative_to(process).as_posix(): path.read_bytes()
        for path in (process / "state").glob("*-LEDGER.ndjson")
    } == unrelated_ledgers
    assert validate_governance_projection(release, process)["decision"] == "PASS"
    assert inspect_work_close_transactions(process)["decision"] == "PASS"


def test_later_native_state_transaction_supersedes_work_close_state_generation(
    tmp_path: Path,
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    result_ref = _prepare_phase_work(release, process, phase, "W-001")
    _enable_state_projection(release, process)
    _close_prepared_phase_work(process, "W-001", result_ref)

    state_current.update_current_state(
        release,
        {
            "active_story": "STORY-DOGFOOD-NEXT",
            "updated_at": "2026-08-12T00:00:00+00:00",
        },
        actor="test.native.state.successor",
        reason="验证 State writer 合法接管 Work close generation",
        mode="enforce",
        render=True,
    )

    assert inspect_work_close_transactions(process)["decision"] == "PASS"
    errors, warnings = state_current.check_current_state(release, mode="enforce")
    assert errors == []
    assert warnings == []


def test_external_state_drift_is_not_mistaken_for_native_state_successor(
    tmp_path: Path,
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    result_ref = _prepare_phase_work(release, process, phase, "W-001")
    _enable_state_projection(release, process)
    _close_prepared_phase_work(process, "W-001", result_ref)
    state_path = process / "state/STATE.current.json"
    state_path.write_bytes(state_path.read_bytes() + b"\n")

    report = inspect_work_close_transactions(process)

    assert report["decision"] == "BLOCKED"
    assert any("state/STATE.current.json" in error for error in report["errors"])


def test_close_blocks_when_existing_state_projection_target_set_is_incomplete(
    tmp_path: Path,
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    result_ref = _prepare_phase_work(release, process, phase, "W-001")
    _enable_state_projection(release, process)
    (process / "current/CURRENT.json").unlink()

    plan = plan_work_close(
        process,
        "W-001",
        expected_status="active",
        outcome="completed",
        result_ref=result_ref,
    )

    assert plan.decision == "BLOCKED"
    assert "State projection target set is incomplete" in "; ".join(plan.blockers)
    assert load_work(process, "W-001").status == "active"


def test_sequential_work_closes_supersede_historical_shared_generations(
    tmp_path: Path,
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    _close_phase_work(release, process, phase, "W-001")
    first_manifest_path = (
        process / ".meta-flow-runtime/work-close/transactions/close-w-001/manifest.json"
    )
    first_manifest = json.loads(first_manifest_path.read_text(encoding="utf-8"))
    first_phase_target = next(
        target for target in first_manifest["targets"] if target["ref"] == phase.phase_ref
    )

    _close_phase_work(release, process, phase, "W-002")

    assert (
        first_phase_target["after_digest"]
        != hashlib.sha256((process / phase.phase_ref).read_bytes()).hexdigest()
    )
    report = inspect_work_close_transactions(process)
    assert report["decision"] == "PASS", report["errors"]
    assert report["unresolved_count"] == 0
    assert validate_governance_projection(release, process)["decision"] == "PASS"


def test_work_init_is_an_authorized_successor_between_sequential_closes(
    tmp_path: Path,
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    _close_phase_work(release, process, phase, "W-001")

    result_ref = _prepare_phase_work(release, process, phase, "W-002")

    assert inspect_work_close_transactions(process)["decision"] == "PASS"
    _close_prepared_phase_work(process, "W-002", result_ref)
    assert inspect_work_close_transactions(process)["decision"] == "PASS"
    assert validate_governance_projection(release, process)["decision"] == "PASS"


def test_state_refresh_after_work_init_is_an_authorized_successor_for_next_close(
    tmp_path: Path,
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    _enable_state_projection(release, process)
    first_result = _prepare_phase_work(release, process, phase, "W-001")
    state_current.refresh_formal_truth_projection(release)
    _close_prepared_phase_work(process, "W-001", first_result)

    second_result = _prepare_phase_work(release, process, phase, "W-002")
    state_current.refresh_formal_truth_projection(release)

    assert inspect_work_close_transactions(process)["decision"] == "PASS"
    plan = plan_work_close(
        process,
        "W-002",
        expected_status="active",
        outcome="completed",
        result_ref=second_result,
    )
    assert plan.ready, plan.blockers
    receipt = apply_work_close(
        process,
        plan,
        _authorization(plan, "close-w-002"),
    )
    assert receipt.decision == "PASS"
    assert inspect_work_close_transactions(process)["decision"] == "PASS"
    assert validate_governance_projection(release, process)["decision"] == "PASS"


def test_forged_state_successor_lineage_cannot_authorize_next_close(
    tmp_path: Path,
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    _enable_state_projection(release, process)
    first_result = _prepare_phase_work(release, process, phase, "W-001")
    state_current.refresh_formal_truth_projection(release)
    _close_prepared_phase_work(process, "W-001", first_result)
    second_result = _prepare_phase_work(release, process, phase, "W-002")
    state_current.refresh_formal_truth_projection(release)
    manifest_path = (
        release / ".meta-flow-runtime/state-projection/transaction.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["lineage"]["process/state/STATE.current.json"][
        "anchor_close_authorization_id"
    ] = "forged-close"
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    plan = plan_work_close(
        process,
        "W-002",
        expected_status="active",
        outcome="completed",
        result_ref=second_result,
    )

    assert plan.decision == "BLOCKED"
    assert "state/STATE.current.json" in "; ".join(plan.blockers)
    assert load_work(process, "W-002").status == "active"


def test_legacy_state_manifest_is_migrated_to_explicit_close_lineage(
    tmp_path: Path,
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    _enable_state_projection(release, process)
    first_result = _prepare_phase_work(release, process, phase, "W-001")
    state_current.refresh_formal_truth_projection(release)
    _close_prepared_phase_work(process, "W-001", first_result)
    second_result = _prepare_phase_work(release, process, phase, "W-002")
    state_current.refresh_formal_truth_projection(release)
    manifest_path = (
        release / ".meta-flow-runtime/state-projection/transaction.json"
    )
    legacy_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    legacy_manifest.pop("lineage")
    manifest_path.write_text(json.dumps(legacy_manifest) + "\n", encoding="utf-8")

    assert inspect_work_close_transactions(process)["decision"] == "PASS"
    state_current.update_current_state(
        release,
        {
            "active_story": "STORY-LEGACY-LINEAGE-MIGRATION",
            "updated_at": "2026-08-12T00:00:00+00:00",
        },
        actor="test.legacy.state.lineage",
        reason="将旧 State manifest 迁移到显式 Work-close lineage",
        mode="enforce",
        render=True,
    )
    migrated = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert migrated["lineage"]

    plan = plan_work_close(
        process,
        "W-002",
        expected_status="active",
        outcome="completed",
        result_ref=second_result,
    )
    assert plan.ready, plan.blockers


def test_work_init_blocks_when_latest_close_generation_was_externally_modified(
    tmp_path: Path,
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    _close_phase_work(release, process, phase, "W-001")
    phase_path = process / phase.phase_ref
    phase_path.write_bytes(phase_path.read_bytes() + b"# external drift\n")

    work = make_work(process, "W-002", phase.phase_ref)
    plan = plan_work_init_from_release_root(release, work)

    assert plan.blocked
    assert "WORK_INIT_LINEAGE_PREFLIGHT_BLOCKED" in {
        conflict.code for conflict in plan.conflicts
    }
    with pytest.raises(ValueError, match="preimage drift"):
        apply_work_init(plan)
    assert not (process / work.work_ref).exists()


def test_duplicate_legacy_generation_is_one_auditable_equivalence_tail(
    tmp_path: Path,
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    _close_cancelled_phase_work(release, process, phase, "W-001")
    _close_cancelled_phase_work(release, process, phase, "W-002")
    _convert_two_closes_to_duplicate_legacy_generation(process)

    assert inspect_work_close_transactions(process)["decision"] == "PASS"
    work = make_work(process, "W-003", phase.phase_ref)
    plan = plan_work_init_from_release_root(release, work)

    assert not plan.blocked
    anchors = {item[0]: item[1] for item in plan.lineage_preflight}
    assert anchors == {
        "PROJECT.yaml": "close-w-002",
        phase.phase_ref: "close-w-002",
    }
    receipt = apply_work_init(plan)

    assert receipt.decision == "PASS"
    assert receipt.shared_projection_successor_id.startswith("work-init-")
    assert inspect_work_close_transactions(process)["decision"] == "PASS"


def test_legacy_partial_work_init_recovery_restores_exact_preimage(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    _close_cancelled_phase_work(release, process, phase, "W-001")
    _close_cancelled_phase_work(release, process, phase, "W-002")
    _convert_two_closes_to_duplicate_legacy_generation(process)
    _enable_state_projection(release, process)
    retained_state = {
        ref: (process / ref).read_bytes()
        for ref in (
            "state/STATE.current.json",
            "STATE.md",
            "current/CURRENT.json",
        )
    }
    work = make_work(process, "W-003", phase.phase_ref)
    write_work_create_only(process, work)
    project = load_project(process)
    replace_project(
        process,
        replace(project, active_work_refs=(*project.active_work_refs, work.work_ref)),
        expected_project_id=project.project_id,
    )
    current_phase = load_phase(process, phase.phase_ref)
    replace_phase(
        process,
        replace(current_phase, work_refs=(*current_phase.work_refs, work.work_ref)),
        expected_phase_id=current_phase.phase_id,
    )
    partial_bytes = {
        ref: (process / ref).read_bytes()
        for ref in (work.work_ref, "PROJECT.yaml", phase.phase_ref)
    }

    plan = plan_legacy_partial_work_init_recovery(release, work.work_id)
    assert plan.ready
    assert [target.ref for target in plan.targets] == [
        work.work_ref,
        "PROJECT.yaml",
        phase.phase_ref,
    ]
    assert all((process / ref).read_bytes() == value for ref, value in partial_bytes.items())

    assert (
        init_inspect_main(
            ["--project-root", str(release), "--work-id", work.work_id]
        )
        == 0
    )
    inspection = json.loads(capsys.readouterr().out)
    assert inspection["decision"] == "RECOVERY_REQUIRED"
    assert inspection["legacy_recovery_plan"]["plan_digest"] == plan.plan_digest

    assert (
        init_recover_main(
            [
                "--project-root",
                str(release),
                "--work-id",
                work.work_id,
                "--plan-digest",
                plan.plan_digest,
                "--apply",
            ]
        )
        == 0
    )
    receipt = json.loads(capsys.readouterr().out)

    assert receipt["decision"] == "RECOVERED"
    assert not (process / work.work_ref).exists()
    assert work.work_ref not in load_project(process).active_work_refs
    assert work.work_ref not in load_phase(process, phase.phase_ref).work_refs
    assert all((process / ref).read_bytes() == value for ref, value in retained_state.items())
    assert inspect_work_close_transactions(process)["decision"] == "PASS"
    errors, _warnings = state_current.check_current_state(release, mode="enforce")
    assert errors == []


def test_work_init_blocks_before_domain_write_when_lineage_writer_lock_is_held(
    tmp_path: Path,
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    _close_phase_work(release, process, phase, "W-001")
    work = make_work(process, "W-002", phase.phase_ref)
    plan = plan_work_init_from_release_root(release, work)
    writer_id = "concurrent-work-close"
    lock = acquire_shared_projection_writer_lock(process, writer_id)
    try:
        with pytest.raises(WorkInitApplyError, match="writer lock is already held") as caught:
            apply_work_init(plan)
    finally:
        release_shared_projection_writer_lock(lock, writer_id)

    assert caught.value.receipt.decision == "BLOCKED"
    assert caught.value.receipt.domain_mutation_count == 0
    assert not (process / work.work_ref).exists()


def test_work_init_and_status_transition_keep_initialized_state_current(
    tmp_path: Path,
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    _enable_state_projection(release, process)
    work = make_work(process, "W-001", phase.phase_ref)

    apply_work_init(plan_work_init_from_release_root(release, work))

    errors, warnings = state_current.check_current_state(release, mode="enforce")
    assert errors == []
    assert warnings == []
    assert state_current.load_current_state(release)["formal_truth_projection"][
        "active_work_ids"
    ] == ["W-001"]

    update_work_status(
        process,
        "W-001",
        expected_status="planned",
        new_status="active",
    )

    errors, warnings = state_current.check_current_state(release, mode="enforce")
    assert errors == []
    assert warnings == []
    assert state_current.validate_current_projection(release) == []
    assert inspect_work_close_transactions(process)["decision"] == "PASS"


def test_work_init_governance_postimage_failure_rolls_back_domain_and_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    _enable_state_projection(release, process)
    work = make_work(process, "W-001", phase.phase_ref)
    plan = plan_work_init_from_release_root(release, work)
    refs = (
        "PROJECT.yaml",
        phase.phase_ref,
        "governance/GOVERNANCE-BASELINE.json",
        "state/STATE.current.json",
        "STATE.md",
        "current/CURRENT.json",
    )
    before = {ref: (process / ref).read_bytes() for ref in refs}

    governance_checks = 0

    def fail_after_locked_preflight(*_args, **_kwargs):
        nonlocal governance_checks
        governance_checks += 1
        if governance_checks == 1:
            return {"decision": "PASS", "errors": []}
        return {
            "decision": "BLOCKED",
            "errors": ["injected stale governance projection"],
        }

    monkeypatch.setattr(
        "meta_flow.project.governance_projection.validate_governance_projection",
        fail_after_locked_preflight,
    )
    with pytest.raises(WorkInitApplyError) as raised:
        apply_work_init(plan)

    receipt = raised.value.receipt
    assert receipt.decision == "RECOVERED"
    assert receipt.transaction_state == "RECOVERED"
    assert receipt.domain_mutation_count == 0
    assert not receipt.recovery_required
    assert not (process / work.work_ref).exists()
    exact_refs = refs[:3]
    assert {ref: (process / ref).read_bytes() for ref in exact_refs} == {
        ref: before[ref] for ref in exact_refs
    }
    assert inspect_work_close_transactions(process)["decision"] == "PASS"
    errors, warnings = state_current.check_current_state(release, mode="enforce")
    assert errors == []
    assert warnings == []
    assert state_current.validate_current_projection(release) == []
    assert state_current.load_current_state(release)["formal_truth_projection"][
        "active_work_ids"
    ] == []


def test_work_init_successor_failure_rolls_back_domain_and_state_exactly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    _close_cancelled_phase_work(release, process, phase, "W-000")
    _enable_state_projection(release, process)
    work = make_work(process, "W-001", phase.phase_ref)
    plan = plan_work_init_from_release_root(release, work)
    refs = (
        "PROJECT.yaml",
        phase.phase_ref,
        "state/STATE.current.json",
        "STATE.md",
        "current/CURRENT.json",
    )
    before = {ref: (process / ref).read_bytes() for ref in refs}

    def fail_successor(*_args, **_kwargs) -> str:
        raise OSError("injected successor writer failure")

    monkeypatch.setattr(
        "meta_flow.work.lifecycle_transaction.record_work_init_shared_projection_successor",
        fail_successor,
    )
    with pytest.raises(WorkInitApplyError) as raised:
        apply_work_init(plan)

    receipt = raised.value.receipt
    assert receipt.decision == "RECOVERED"
    assert receipt.transaction_state == "RECOVERED"
    assert receipt.domain_mutation_count == 0
    assert not receipt.recovery_required
    assert not (process / work.work_ref).exists()
    assert {ref: (process / ref).read_bytes() for ref in refs} == before
    assert inspect_work_close_transactions(process)["decision"] == "PASS"
    errors, warnings = state_current.check_current_state(release, mode="enforce")
    assert errors == []
    assert warnings == []
    from meta_flow.work.lifecycle_transaction import (
        acquire_shared_projection_writer_lock,
        release_shared_projection_writer_lock,
    )

    lock = acquire_shared_projection_writer_lock(process, "post-recovery-probe")
    release_shared_projection_writer_lock(lock, "post-recovery-probe")


def test_work_status_rolls_back_when_state_projection_refresh_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    _enable_state_projection(release, process)
    work = make_work(process, "W-001", phase.phase_ref)
    apply_work_init(plan_work_init_from_release_root(release, work))
    work_path = process / work.work_ref
    before = work_path.read_bytes()

    def fail_refresh(_process_root: Path) -> tuple[str, ...]:
        raise OSError("injected State projection refresh failure")

    monkeypatch.setattr(
        "meta_flow.work.lifecycle_transaction.refresh_state_projection_if_initialized",
        fail_refresh,
    )
    with pytest.raises(OSError, match="injected State projection refresh failure"):
        update_work_status(
            process,
            "W-001",
            expected_status="planned",
            new_status="active",
        )

    assert work_path.read_bytes() == before
    assert load_work(process, "W-001").status == "planned"
    errors, warnings = state_current.check_current_state(release, mode="enforce")
    assert errors == []
    assert warnings == []


def test_completed_work_archive_is_an_authorized_close_successor(
    tmp_path: Path,
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    _close_phase_work(release, process, phase, "W-001")

    update_work_status(
        process,
        "W-001",
        expected_status="completed",
        new_status="archived",
    )

    assert load_work(process, "W-001").status == "archived"
    assert inspect_work_close_transactions(process)["decision"] == "PASS"


def test_work_close_blocks_before_domain_write_when_state_writer_lock_is_held(
    tmp_path: Path,
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    result_ref = _prepare_phase_work(release, process, phase, "W-001")
    _enable_state_projection(release, process)
    plan = plan_work_close(
        process,
        "W-001",
        expected_status="active",
        outcome="completed",
        result_ref=result_ref,
    )
    before = {target.ref: (process / target.ref).read_bytes() for target in plan.targets}
    state_lock = acquire_transaction_lock(
        state_projection_lock_path(release),
        "a" * 32,
    )
    try:
        with pytest.raises(ValueError, match="state projection writer lock"):
            apply_work_close(
                process,
                plan,
                _authorization(plan, "close-state-lock-held"),
            )
    finally:
        release_transaction_lock(state_lock)

    assert {ref: (process / ref).read_bytes() for ref in before} == before
    assert not (
        process
        / ".meta-flow-runtime/work-close/transactions/close-state-lock-held/manifest.json"
    ).exists()


def test_three_sequential_work_closes_form_one_lineage_chain(tmp_path: Path) -> None:
    release, process, phase = _governance_fixture(tmp_path)

    for work_id in ("W-000", "W-001", "W-002"):
        _close_phase_work(release, process, phase, work_id)

    manifests = [
        json.loads(
            (
                process
                / ".meta-flow-runtime/work-close/transactions"
                / f"close-{work_id.lower()}"
                / "manifest.json"
            ).read_text(encoding="utf-8")
        )
        for work_id in ("W-000", "W-001", "W-002")
    ]
    for ref in (
        "PROJECT.yaml",
        phase.phase_ref,
        GOVERNANCE_PROJECTION_REL.as_posix(),
    ):
        assert manifests[0]["lineage"].get(ref) is None
        assert manifests[1]["lineage"][ref] == "close-w-000"
        assert manifests[2]["lineage"][ref] == "close-w-001"

    report = inspect_work_close_transactions(process)
    assert report["decision"] == "PASS", report["errors"]
    assert report["unresolved_count"] == 0
    assert validate_governance_projection(release, process)["decision"] == "PASS"


def test_interleaved_work_close_order_remains_one_legal_lineage(
    tmp_path: Path,
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    result_refs = {
        work_id: _prepare_phase_work(release, process, phase, work_id)
        for work_id in ("W-000", "W-001", "W-002")
    }

    for work_id in ("W-001", "W-000", "W-002"):
        _plan, receipt = _close_prepared_phase_work(
            process,
            work_id,
            result_refs[work_id],
        )
        assert receipt.decision == "PASS"
        assert inspect_work_close_transactions(process)["decision"] == "PASS"
        assert validate_governance_projection(release, process)["decision"] == "PASS"

    assert load_project(process).active_work_refs == ()
    assert load_work(process, "W-000").status == "completed"
    assert load_work(process, "W-001").status == "completed"
    assert load_work(process, "W-002").status == "completed"


def test_broken_lineage_predecessor_is_blocked_even_when_head_bytes_match(
    tmp_path: Path,
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    _close_phase_work(release, process, phase, "W-001")
    _close_phase_work(release, process, phase, "W-002")
    manifest_path = (
        process / ".meta-flow-runtime/work-close/transactions/close-w-002/manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["lineage"][phase.phase_ref] = "missing-predecessor"
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    report = inspect_work_close_transactions(process)

    assert report["decision"] == "BLOCKED"
    assert any(
        f"lineage predecessor is invalid: {phase.phase_ref}:missing-predecessor" in error
        for error in report["errors"]
    )


def test_lineage_fork_is_blocked_even_when_one_successor_matches_current_bytes(
    tmp_path: Path,
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    for work_id in ("W-001", "W-002", "W-003"):
        _close_phase_work(release, process, phase, work_id)
    manifest_path = (
        process / ".meta-flow-runtime/work-close/transactions/close-w-003/manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["lineage"][phase.phase_ref] = "close-w-001"
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    report = inspect_work_close_transactions(process)

    assert report["decision"] == "BLOCKED"
    assert any(
        f"lineage has multiple successors: {phase.phase_ref}:close-w-001" in error
        for error in report["errors"]
    )

    work = make_work(process, "W-004", phase.phase_ref)
    with pytest.raises(ValueError, match="multiple successors"):
        apply_work_init(plan_work_init_from_release_root(release, work))
    assert not (process / work.work_ref).exists()


def test_latest_work_close_generation_drift_remains_blocked(tmp_path: Path) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    _close_phase_work(release, process, phase, "W-001")
    _close_phase_work(release, process, phase, "W-002")
    phase_path = process / phase.phase_ref
    phase_path.write_bytes(phase_path.read_bytes() + b"# external drift\n")

    report = inspect_work_close_transactions(process)

    assert report["decision"] == "BLOCKED"
    assert any(
        f"terminal generation mismatch: {phase.phase_ref}:COMMITTED" in error
        for error in report["errors"]
    )


def test_close_blocks_before_write_when_governance_baseline_is_stale(
    tmp_path: Path,
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    work = make_work(process, "W-001", phase.phase_ref)
    apply_work_init(plan_work_init_from_release_root(release, work))
    update_work_status(process, "W-001", expected_status="planned", new_status="active")
    result_ref = "works/W-001/RESULT.json"
    (process / result_ref).write_text(
        json.dumps({"schema_version": 1, "work_id": "W-001", "decision": "PASS"}) + "\n",
        encoding="utf-8",
    )
    projection_path = process / GOVERNANCE_PROJECTION_REL
    stale = json.loads(projection_path.read_text(encoding="utf-8"))
    stale["active_result_refs"] = []
    stale["semantic_digest"] = semantic_digest(stale)
    projection_path.write_text(json.dumps(stale) + "\n", encoding="utf-8")
    phase_before = (process / phase.phase_ref).read_bytes()

    plan = plan_work_close(
        process,
        "W-001",
        expected_status="active",
        outcome="completed",
        result_ref=result_ref,
    )

    assert plan.decision == "BLOCKED"
    assert "governance projection must be current" in "; ".join(plan.blockers)
    assert (process / phase.phase_ref).read_bytes() == phase_before
    assert load_work(process, "W-001").status == "active"


def test_work_init_plan_blocks_stale_governance_before_domain_write(
    tmp_path: Path,
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    projection_path = process / GOVERNANCE_PROJECTION_REL
    stale = json.loads(projection_path.read_text(encoding="utf-8"))
    stale["active_result_refs"] = []
    stale["semantic_digest"] = semantic_digest(stale)
    projection_path.write_text(json.dumps(stale) + "\n", encoding="utf-8")
    work = make_work(process, "W-001", phase.phase_ref)

    plan = plan_work_init_from_release_root(release, work)

    assert plan.blocked
    assert {conflict.code for conflict in plan.conflicts} >= {
        "WORK_INIT_GOVERNANCE_PREFLIGHT_BLOCKED"
    }
    assert not (process / work.work_ref).exists()
    assert work.work_ref not in load_project(process).active_work_refs
    assert work.work_ref not in load_phase(process, phase.phase_ref).work_refs


def test_fourth_target_failure_rolls_back_phase_and_governance_baseline(
    tmp_path: Path,
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    work = make_work(process, "W-001", phase.phase_ref)
    apply_work_init(plan_work_init_from_release_root(release, work))
    update_work_status(process, "W-001", expected_status="planned", new_status="active")
    result_ref = "works/W-001/RESULT.json"
    (process / result_ref).write_text(
        json.dumps({"schema_version": 1, "work_id": "W-001", "decision": "PASS"}) + "\n",
        encoding="utf-8",
    )
    plan = plan_work_close(
        process,
        "W-001",
        expected_status="active",
        outcome="completed",
        result_ref=result_ref,
    )
    before = {target.ref: (process / target.ref).read_bytes() for target in plan.targets}
    from meta_flow.work import lifecycle_transaction

    real_replace = lifecycle_transaction._replace_bytes
    calls = 0

    def fail_fourth(path: Path, content: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 4:
            raise OSError("injected governance target failure")
        real_replace(path, content)

    with patch.object(lifecycle_transaction, "_replace_bytes", side_effect=fail_fourth):
        receipt = apply_work_close(
            process,
            plan,
            _authorization(plan, "close-governance-recovered"),
        )

    assert receipt.decision == "RECOVERED"
    assert receipt.recovery_required is False
    assert {ref: (process / ref).read_bytes() for ref in before} == before
    assert inspect_work_close_transactions(process)["decision"] == "PASS"


def test_historical_manifest_digest_corruption_remains_blocked(
    tmp_path: Path,
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    _close_phase_work(release, process, phase, "W-001")
    _close_phase_work(release, process, phase, "W-002")
    manifest_path = process / ".meta-flow-runtime/work-close/transactions/close-w-001/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["targets"][0]["after_digest"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    report = inspect_work_close_transactions(process)

    assert report["decision"] == "BLOCKED"
    assert any("bytes/digest mismatch" in error for error in report["errors"])


def test_recovered_close_can_be_retried_with_a_new_authorization(
    tmp_path: Path,
) -> None:
    _release, process, result_ref = _active_fixture(tmp_path)
    first_plan = plan_work_close(
        process,
        "W-001",
        expected_status="active",
        outcome="completed",
        result_ref=result_ref,
    )
    from meta_flow.work import lifecycle_transaction

    real_replace = lifecycle_transaction._replace_bytes
    calls = 0

    def fail_second(path: Path, content: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected retryable close failure")
        real_replace(path, content)

    with patch.object(lifecycle_transaction, "_replace_bytes", side_effect=fail_second):
        recovered = apply_work_close(
            process,
            first_plan,
            _authorization(first_plan, "close-first-recovered"),
        )
    assert recovered.decision == "RECOVERED"

    retry_plan = plan_work_close(
        process,
        "W-001",
        expected_status="active",
        outcome="completed",
        result_ref=result_ref,
    )
    committed = apply_work_close(
        process,
        retry_plan,
        _authorization(retry_plan, "close-retry-committed"),
    )

    assert committed.decision == "PASS"
    assert inspect_work_close_transactions(process)["decision"] == "PASS"


def test_idempotent_close_repairs_legacy_stale_governance_baseline(
    tmp_path: Path,
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    _plan, receipt = _close_phase_work(release, process, phase, "W-001")
    assert receipt.decision == "PASS"
    baseline_path = process / GOVERNANCE_PROJECTION_REL
    current_baseline = baseline_path.read_bytes()
    manifest = json.loads(
        (
            process / ".meta-flow-runtime/work-close/transactions/close-w-001/manifest.json"
        ).read_text(encoding="utf-8")
    )
    baseline_target = next(
        target
        for target in manifest["targets"]
        if target["ref"] == GOVERNANCE_PROJECTION_REL.as_posix()
    )
    baseline_path.write_bytes(base64.b64decode(baseline_target["before_bytes_b64"], validate=True))
    assert baseline_path.read_bytes() != current_baseline
    assert validate_governance_projection(release, process)["decision"] == "BLOCKED"

    repair_plan = plan_work_close(
        process,
        "W-001",
        expected_status="active",
        outcome="completed",
        result_ref="works/W-001/RESULT.json",
    )

    assert repair_plan.ready, repair_plan.blockers
    assert [target.ref for target in repair_plan.targets] == [GOVERNANCE_PROJECTION_REL.as_posix()]
    repaired = apply_work_close(
        process,
        repair_plan,
        _authorization(repair_plan, "close-w-001-baseline-repair"),
    )
    assert repaired.decision == "PASS"
    assert baseline_path.read_bytes() == current_baseline
    assert validate_governance_projection(release, process)["decision"] == "PASS"
    assert inspect_work_close_transactions(process)["decision"] == "PASS"


def test_lineage_drift_after_plan_releases_writer_lock(tmp_path: Path) -> None:
    _release, process, result_ref = _active_fixture(tmp_path)
    plan = plan_work_close(
        process,
        "W-001",
        expected_status="active",
        outcome="completed",
        result_ref=result_ref,
    )
    drifted = replace(
        plan,
        lineage=(("PROJECT.yaml", "missing-predecessor"),),
    )

    with pytest.raises(ValueError, match="lineage changed after planning"):
        apply_work_close(
            process,
            drifted,
            _authorization(drifted, "close-lineage-drift"),
        )

    lock = process / ".meta-flow-runtime/work-close/writer.lock"
    assert not lock.exists()
