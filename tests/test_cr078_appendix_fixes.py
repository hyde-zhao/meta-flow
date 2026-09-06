"""CR-078 S3/S4 扩展回归：附录 A 修复 + 0.6.5 顺带缺陷。"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from test_work_lifecycle_transaction import (
    _governance_fixture,
    make_work,
)

from meta_flow.work import cli as work_cli
from meta_flow.work.model import load_work
from meta_flow.work.scope_amend import (
    plan_g1_scope_amend,
)
from meta_flow.work.store import apply_work_init, plan_work_init_from_release_root


def test_cr_query_distinguishes_native_cr(tmp_path: Path, capsys) -> None:
    from meta_flow.workflow import cr_cli

    release, process, phase = _governance_fixture(tmp_path)
    work = make_work(process, "W-001", phase.phase_ref)
    apply_work_init(plan_work_init_from_release_root(release, work))

    # 无 native CR 时：保持 legacy registry fail-closed 语义
    code = cr_cli.main(
        ["query", "--project-root", str(release), "--id", "CR-999", "--format", "json"]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert payload["error_code"] == "legacy_evidence_not_registered"


def test_work_authorization_template_fills_mechanical_fields(
    tmp_path: Path, capsys
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    work = replace(make_work(process, "W-001", phase.phase_ref), status="paused")
    apply_work_init(plan_work_init_from_release_root(release, work))

    delta_path = tmp_path / "delta.json"
    delta_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "add_reads": [],
                "add_writes": ["src/new-output.py"],
                "add_checks": [],
                "reason": "template fixture",
            }
        ),
        encoding="utf-8",
    )
    code = work_cli.authorization_template_main(
        [
            "--project-root", str(release),
            "--operation", "work.scope-amend",
            "--work-id", "W-001",
            "--delta", str(delta_path),
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["decision"] == "PASS"
    template = payload["template"]
    assert template["authorized_add_writes"] == ["src/new-output.py"]
    assert template["predecessor_scope_digest"] == load_work(process, "W-001").scope.digest
    assert "works/W-001/evidence/validation/**" in template["invalidation_refs"]
    assert template["authorization_id"].startswith("<fill:")


def test_work_authorization_template_rejects_g2_wildcard(tmp_path: Path, capsys) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    work = replace(make_work(process, "W-001", phase.phase_ref), status="paused")
    apply_work_init(plan_work_init_from_release_root(release, work))
    delta_path = tmp_path / "delta-wildcard.json"
    delta_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "add_reads": [],
                "add_writes": ["src/**"],
                "add_checks": [],
                "reason": "wildcard fixture",
            }
        ),
        encoding="utf-8",
    )
    code = work_cli.authorization_template_main(
        [
            "--project-root", str(release),
            "--operation", "work.scope-amend",
            "--work-id", "W-001",
            "--delta", str(delta_path),
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert "G2_CURRENT_CR_SCOPE_AMEND_WILDCARD_UNSUPPORTED" in payload["error"]


def test_g2_plan_reports_explicit_wildcard_blocker(tmp_path: Path) -> None:
    from test_scope_amend_shared_projection_successor import (
        _g2_delta_and_authorization,
        _g2_work_fixture,
    )

    release, process, checkpoint_ref, checkpoint_digest, event = _g2_work_fixture(tmp_path)
    delta, authorization = _g2_delta_and_authorization(
        release,
        process,
        checkpoint_ref,
        checkpoint_digest,
        event,
        add_writes=("governance/**",),
        exact_authorized=False,
    )
    plan = plan_g1_scope_amend(
        release,
        work_id="W-001",
        delta=delta,
        authorization=authorization,
        release_oid=authorization.release_oid,
        process_oid=authorization.process_oid,
    )
    assert "G2_CURRENT_CR_SCOPE_AMEND_WILDCARD_UNSUPPORTED" in plan.blockers


def test_resume_check_reports_typed_reason_without_handoff(
    tmp_path: Path, capsys
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    work = replace(make_work(process, "W-001", phase.phase_ref), status="paused")
    apply_work_init(plan_work_init_from_release_root(release, work))

    code = work_cli.resume_check_main(
        ["--project-root", str(release), "--work-id", "W-001"]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["reason_code"] == "HANDOFF_NOT_INITIALIZED"
