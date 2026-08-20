from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from test_work_lifecycle_transaction import (
    _enable_state_projection,
    _governance_fixture,
    make_work,
)

from meta_flow.work import cli as work_cli
from meta_flow.work.model import load_work
from meta_flow.work.status_transition import (
    WorkStatusTransitionAuthorizationV2,
    WorkStatusTransitionReceiptV2,
    plan_work_status_transition,
)
from meta_flow.work.store import apply_work_init, plan_work_init_from_release_root


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    release, process, phase = _governance_fixture(tmp_path)
    _enable_state_projection(release, process)
    work = make_work(process, "W-001", phase.phase_ref)
    apply_work_init(plan_work_init_from_release_root(release, work))
    return release, process


def _authorization_file(tmp_path: Path, plan) -> Path:
    authorization = WorkStatusTransitionAuthorizationV2(
        authorization_id=f"cr074-cli-{plan.plan_digest[:24]}",
        work_id=plan.parent_plan.work_id,
        plan_digest=plan.plan_digest,
        parent_plan_digest=plan.parent_plan.plan_digest,
        target_refs=plan.target_refs,
        expires_at=(datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
    )
    path = tmp_path / "status-transition-authorization.json"
    path.write_text(
        json.dumps(authorization.as_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def test_start_alias_is_zero_write_then_uses_typed_apply(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release, process = _fixture(tmp_path)
    work_path = process / "works/W-001/WORK.yaml"
    before = work_path.read_bytes()

    code = work_cli.main(["start", "--project-root", str(release), "--work-id", "W-001"])
    preview = json.loads(capsys.readouterr().out)

    assert code == 0, preview
    assert preview["kind"] == "WorkStatusTransitionPlanV2"
    assert preview["decision"] == "READY"
    assert preview["mutation_count"] == 0
    assert work_path.read_bytes() == before
    assert load_work(process, "W-001").status == "planned"

    plan = plan_work_status_transition(
        process,
        "W-001",
        expected_status="planned",
        new_status="active",
        handoff=None,
    )
    authorization = _authorization_file(tmp_path, plan)
    code = work_cli.main(
        [
            "start",
            "--project-root",
            str(release),
            "--work-id",
            "W-001",
            "--apply",
            "--authorization-file",
            str(authorization),
        ]
    )
    receipt = json.loads(capsys.readouterr().out)

    assert code == 0, receipt
    assert receipt["kind"] == "WorkStatusTransitionReceiptV2"
    assert receipt["decision"] == "PASS"
    assert set(receipt["planned_refs"]) == set(receipt["actual_mutation_refs"])
    assert load_work(process, "W-001").status == "active"


def test_apply_without_typed_authorization_is_zero_write_blocked(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release, process = _fixture(tmp_path)
    work_path = process / "works/W-001/WORK.yaml"
    before = work_path.read_bytes()

    code = work_cli.main(
        [
            "status-transition",
            "--project-root",
            str(release),
            "--work-id",
            "W-001",
            "--expected-status",
            "planned",
            "--new-status",
            "active",
            "--apply",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert payload["decision"] == "BLOCKED"
    assert payload["mutation_count"] == 0
    assert "--authorization-file" in payload["error"]
    assert work_path.read_bytes() == before


def test_status_transition_inspect_and_direct_handoff_boundary(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release, process = _fixture(tmp_path)

    code = work_cli.main(["status-transition-inspect", "--project-root", str(release)])
    inspection = json.loads(capsys.readouterr().out)
    assert code == 0
    assert inspection["kind"] == "WorkStatusTransitionInspectionV2"
    assert inspection["decision"] == "PASS"
    assert inspection["mutation_count"] == 0

    code = work_cli.main(
        [
            "handoff",
            "--project-root",
            str(release),
            "--work-id",
            "W-001",
            "--next-step",
            "must use status-transition",
        ]
    )
    blocked = json.loads(capsys.readouterr().out)
    assert code == 1
    assert blocked["decision"] == "BLOCKED"
    assert blocked["reason_codes"] == ["HANDOFF_DIRECT_MUTATION_DISABLED"]
    assert blocked["mutation_count"] == 0
    assert not (process / "works/W-001/HANDOFF.yaml").exists()


def test_status_transition_recover_requires_explicit_apply(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release, _process = _fixture(tmp_path)

    code = work_cli.main(
        [
            "status-transition-recover",
            "--project-root",
            str(release),
            "--authorization-id",
            "cr074-missing",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert payload["decision"] == "BLOCKED"
    assert payload["reason_codes"] == ["RECOVERY_APPLY_REQUIRED"]
    assert payload["mutation_count"] == 0


def test_public_cli_preserves_typed_child_failure_accounting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release, process = _fixture(tmp_path)
    plan = plan_work_status_transition(
        process,
        "W-001",
        expected_status="planned",
        new_status="active",
    )
    authorization_file = _authorization_file(tmp_path, plan)

    def typed_recovered(_root, supplied_plan, authorization):
        return WorkStatusTransitionReceiptV2(
            "RECOVERED",
            authorization.authorization_id,
            authorization.work_id,
            supplied_plan.plan_digest,
            supplied_plan.target_refs,
            (supplied_plan.target_refs[0],),
            "RECOVERED",
            "RECOVERED",
            "NO_CHANGE",
            False,
            ("WORK_STATUS_CHILD_APPLY_EXCEPTION",),
        )

    monkeypatch.setattr(work_cli, "apply_work_status_transition", typed_recovered)

    code = work_cli.main(
        [
            "status-transition",
            "--project-root",
            str(release),
            "--work-id",
            "W-001",
            "--expected-status",
            "planned",
            "--new-status",
            "active",
            "--apply",
            "--authorization-file",
            str(authorization_file),
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert payload["kind"] == "WorkStatusTransitionReceiptV2"
    assert payload["decision"] == "RECOVERED"
    assert payload["mutation_count"] == 1
    assert payload["actual_mutation_refs"] == [plan.target_refs[0]]
    assert "error" not in payload
