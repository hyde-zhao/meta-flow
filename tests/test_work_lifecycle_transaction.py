from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from meta_flow.execution_control.contract import ExecutionUnitV1
from meta_flow.project.model import load_project
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
from meta_flow.work.lifecycle import update_work_status
from meta_flow.work.lifecycle_transaction import (
    AUTHORIZATION_KIND,
    WorkCloseAuthorizationV1,
    apply_work_close,
    inspect_work_close_transactions,
    plan_work_close,
    recover_work_close_transaction,
)
from meta_flow.work.model import build_work, load_work
from meta_flow.work.risk import RiskFacts, classify_work
from meta_flow.work.scope import WorkScope
from meta_flow.work.store import apply_work_init, plan_work_init_from_release_root


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


def make_work(process: Path):
    request_ref = "works/W-001/REQUEST.md"
    request_path = process / request_ref
    request_path.parent.mkdir(parents=True)
    request_path.write_text("# 请求\n\n用户确认：是。\n", encoding="utf-8")
    work = build_work(
        work_id="W-001",
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
        json.dumps({"schema_version": 1, "work_id": "W-001", "decision": "PASS"})
        + "\n",
        encoding="utf-8",
    )
    return release, process, result_ref


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
    assert not (process / ".meta-flow-runtime/work-close").exists()


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
        process
        / ".meta-flow-runtime/work-close/transactions"
        / authorization_id
        / "manifest.json"
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
        process
        / ".meta-flow-runtime/work-close/transactions"
        / authorization_id
        / "manifest.json"
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
