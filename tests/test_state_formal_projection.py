from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from cr_lifecycle_test_support import LifecycleFixtureCollaborators, init_binding_project

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
from meta_flow.project.process_route import _resolve_runtime_ref
from meta_flow.project.scale import dump_yaml, load_yaml_object
from meta_flow.state import current, formal_projection
from meta_flow.work.scope import WorkScope

_FIXTURE_COLLABORATORS = LifecycleFixtureCollaborators(
    project_init_request=ProjectInitRequest,
    plan_project_init=plan_project_init,
    apply_project_init=apply_project_init,
    onboarding_authorization=OnboardingAuthorization,
    authorization_source=AUTHORIZATION_SOURCE,
    authorization_kind=AUTHORIZATION_KIND,
    resolve_runtime_ref=_resolve_runtime_ref,
    dump_yaml=dump_yaml,
    load_yaml_object=load_yaml_object,
    work_scope=WorkScope,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _formal_fixture(root: Path) -> tuple[Path, Path]:
    release, process = init_binding_project(
        root,
        collaborators=_FIXTURE_COLLABORATORS,
    )
    _write_json(
        process / "PROJECT.yaml",
        {
            "schema_version": 1,
            "project_id": "fixture",
            "name": "Fixture Project",
            "status": "active",
            "roadmap_ref": "ROADMAP.yaml",
        },
    )
    _write_json(
        process / "ROADMAP.yaml",
        {
            "schema_version": 1,
            "project_id": "fixture",
            "status": "active",
            "phase_refs": ["phases/P1/PHASE.yaml"],
        },
    )
    _write_json(
        process / "phases/P1/PHASE.yaml",
        {
            "schema_version": 1,
            "project_id": "fixture",
            "phase_id": "P1",
            "status": "active",
            "work_refs": [],
            "result_refs": [],
        },
    )
    (process / "changes").mkdir(parents=True, exist_ok=True)
    current.write_current_state(
        release,
        current.default_current_state(release, project_id="fixture"),
    )
    current.render_state_file(release, force=True)
    return release, process


def _native_cr_text(cr_id: str, *, closed: bool = False) -> str:
    lifecycle = "closed" if closed else "active"
    readiness = "READY" if closed else "NOT_READY"
    gate = "cp8_closed" if closed else "cp2_pending"
    return (
        "---\n"
        "schema_version: 1\n"
        "kind: cr\n"
        f"cr_id: {cr_id}\n"
        f"lifecycle_status: {lifecycle}\n"
        f"readiness_status: {readiness}\n"
        f"gate_status: {gate}\n"
        "gate_profile: standard-code\n"
        "---\n"
    )


def test_enforce_rejects_state_that_is_internally_consistent_but_formally_stale(
    tmp_path: Path,
) -> None:
    project_root, _process_root = _formal_fixture(tmp_path)

    errors, _warnings = current.check_current_state(project_root, mode="enforce")

    assert any("formal_truth_projection_stale" in error for error in errors)
    assert any("formal_truth_field_stale: current_phase" in error for error in errors)
    assert any("formal_truth_field_stale: next_action" in error for error in errors)


def test_projection_refresh_is_zero_write_then_transactionally_converges(
    tmp_path: Path,
) -> None:
    project_root, process_root = _formal_fixture(tmp_path)
    before = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    plan = current.plan_formal_truth_refresh(project_root)

    after_plan = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert before == after_plan
    assert plan["decision"] == "READY"
    assert plan["mutation_count"] == 0
    assert plan["planned_mutation_count"] == 3

    state = current.refresh_formal_truth_projection(project_root)
    errors, warnings = current.check_current_state(project_root, mode="enforce")

    assert errors == []
    assert warnings == []
    assert state["current_phase"] == "P1"
    assert state["next_action"]["type"] == "continue_active_phase"
    projected = json.loads((process_root / "current/CURRENT.json").read_text(encoding="utf-8"))
    assert projected["phase"] == "P1"
    assert projected["updated_at"] == state["updated_at"]
    assert "Phase: P1" in (process_root / "STATE.md").read_text(encoding="utf-8")


def test_formal_snapshot_includes_direct_project_work(tmp_path: Path) -> None:
    project_root, process_root = _formal_fixture(tmp_path)
    project_path = process_root / "PROJECT.yaml"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project["active_work_refs"] = ["works/W-DIRECT/WORK.yaml"]
    _write_json(project_path, project)
    _write_json(
        process_root / "works/W-DIRECT/WORK.yaml",
        {
            "schema_version": 1,
            "work_id": "W-DIRECT",
            "project_id": "fixture",
            "status": "active",
        },
    )

    snapshot = formal_projection.build_formal_truth_snapshot(project_root)

    assert snapshot["active_work_ids"] == ["W-DIRECT"]
    assert "process/works/W-DIRECT/WORK.yaml" in snapshot["source_refs"]


def test_formal_snapshot_rejects_unsafe_direct_project_work_ref(tmp_path: Path) -> None:
    project_root, process_root = _formal_fixture(tmp_path)
    project_path = process_root / "PROJECT.yaml"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project["active_work_refs"] = ["works/../outside/WORK.yaml"]
    _write_json(project_path, project)

    with pytest.raises(ValueError, match="active_work_refs must be safe paths under works/"):
        formal_projection.build_formal_truth_snapshot(project_root)


def test_typed_formal_root_replacement_removes_stale_keys_but_normal_merge_preserves(
    tmp_path: Path,
) -> None:
    _ = tmp_path
    base = {
        "formal_truth_projection": {
            "phase_statuses": {"P0": "completed", "P1": "active"},
            "metadata": {"old": True},
        },
        "next_action": {"type": "continue", "text": "old", "stop_reason": None},
    }
    patch = {
        "formal_truth_projection": {
            "phase_statuses": {"P1": "active"},
            "metadata": {"new": True},
        },
        "next_action": {"text": "new"},
    }

    replaced = current.merge_current_state(
        base,
        patch,
        replace_paths=formal_projection.FORMAL_TRUTH_REPLACE_PATHS,
    )
    merged = current.merge_current_state(base, patch)

    assert replaced["formal_truth_projection"]["phase_statuses"] == {"P1": "active"}
    assert replaced["formal_truth_projection"]["metadata"] == {"new": True}
    assert replaced["next_action"] == {
        "type": "continue",
        "text": "new",
        "stop_reason": None,
    }
    assert "P0" in merged["formal_truth_projection"]["phase_statuses"]
    with pytest.raises(current.StateValidationError, match="unknown current-state replace paths"):
        current.merge_current_state(base, patch, replace_paths=frozenset({"next_action"}))


def test_formal_refresh_exactly_replaces_stale_phase_collection(tmp_path: Path) -> None:
    project_root, _process_root = _formal_fixture(tmp_path)
    current.update_current_state(
        project_root,
        {
            "formal_truth_projection": {
                "schema_version": 1,
                "phase_statuses": {"P0": "completed", "P1": "active"},
                "active_phase_ids": ["P1"],
                "active_work_ids": [],
                "active_cr_ids": [],
                "source_refs": [],
                "source_digest": "0" * 64,
            },
            "updated_at": current.now_utc(),
        },
        actor="tests.formal_projection",
        reason="install stale typed collection fixture",
        mode="enforce",
    )

    refreshed = current.refresh_formal_truth_projection(project_root)

    assert refreshed["formal_truth_projection"]["phase_statuses"] == {"P1": "active"}
    assert "P0" not in refreshed["formal_truth_projection"]["phase_statuses"]


def _cost_report(*, decision: str = "PASS", soft_risks: list[str] | None = None) -> dict:
    report = {
        "schema_version": 1,
        "kind": "ProcessCostReportV1",
        "mode": {"empirical": "measure-only", "structural_safety": "hard"},
        "soft_risks": list(soft_risks or []),
        "decision": decision,
    }
    canonical = json.dumps(
        report, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    report["report_digest"] = hashlib.sha256(canonical).hexdigest()
    return report


def test_process_cost_health_projection_is_closed_zero_write_and_preimage_bound(
    tmp_path: Path,
) -> None:
    project_root, _process_root = _formal_fixture(tmp_path)
    report = _cost_report(decision="PASS_WITH_RISK", soft_risks=["RATIO_HIGH"])
    report_ref = "process/works/CR-072-WB-GOVERNANCE-001/evidence/cost.json"
    summary = current.build_process_cost_health_summary(report_ref, report)

    assert summary == {
        "report_ref": report_ref,
        "report_digest": report["report_digest"],
        "mode": "measure-only",
        "structural_decision": "PASS_WITH_RISK",
        "soft_risk_count": 1,
    }
    before = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    empty_preimage = hashlib.sha256(b"").hexdigest()
    plan = current.plan_cost_health_projection(
        project_root,
        report,
        report_ref=report_ref,
        expected_preimage=empty_preimage,
    )
    blocked = current.plan_cost_health_projection(
        project_root,
        report,
        report_ref=report_ref,
        expected_preimage="f" * 64,
    )
    after = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    assert plan["decision"] == "READY"
    assert plan["mutation_count"] == 0
    assert plan["planned_mutation_count"] == 2
    assert blocked["decision"] == "BLOCKED"
    assert before == after


def test_process_cost_health_summary_rejects_detail_or_digest_drift(tmp_path: Path) -> None:
    _ = tmp_path
    report = _cost_report()
    report["soft_risks"].append("DRIFT")

    with pytest.raises(ValueError, match="digest mismatch"):
        current.build_process_cost_health_summary("process/evidence/cost.json", report)


def test_projection_refresh_preserves_pending_human_gate_stop_semantics(
    tmp_path: Path,
) -> None:
    project_root, process_root = _formal_fixture(tmp_path)
    checkpoint_ref = "process/checkpoints/CP2-BASELINE.md"
    checkpoint_path = process_root / checkpoint_ref.removeprefix("process/")
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_text("# CP2\n", encoding="utf-8")
    current.update_current_state(
        project_root,
        {
            "pending_gate": "CP2",
            "pending_checklist_path": checkpoint_ref,
            "next_action": {
                "type": "human_gate",
                "text": "Review CP2.",
                "stop_reason": "required_human_gate",
            },
            "updated_at": current.now_utc(),
        },
        actor="tests.formal_projection",
        reason="install pending human gate fixture through the transaction kernel",
        mode="enforce",
    )

    refreshed = current.refresh_formal_truth_projection(project_root)
    errors, warnings = current.check_current_state(project_root, mode="enforce")

    assert errors == []
    assert warnings == []
    assert refreshed["current_phase"] == "P1"
    assert refreshed["pending_gate"] == "CP2"
    assert refreshed["pending_checklist_path"] == checkpoint_ref
    assert refreshed["next_action"] == {
        "type": "human_gate",
        "text": "Review pending human gate CP2.",
        "stop_reason": "required_human_gate",
    }


def test_projection_refresh_preserves_single_active_cr_failure_stop(
    tmp_path: Path,
) -> None:
    project_root, process_root = _formal_fixture(tmp_path)
    formal_ref = process_root / "changes/CR-072.md"
    formal_ref.write_text(_native_cr_text("CR-072"), encoding="utf-8")
    current.refresh_formal_truth_projection(project_root)
    current.update_current_state(
        project_root,
        {
            "blocked": True,
            "next_action": {
                "type": "blocked",
                "text": "CP8 automatic precheck failed.",
                "stop_reason": "blocked",
            },
            "updated_at": current.now_utc(),
        },
        actor="tests.formal_projection",
        reason="install an explicit single-CR failure stop",
        mode="enforce",
    )

    refreshed = current.refresh_formal_truth_projection(project_root)
    errors, warnings = current.check_current_state(project_root, mode="enforce")

    assert errors == []
    assert warnings == []
    assert refreshed["active_change"] == "CR-072"
    assert refreshed["blocked"] is True
    assert refreshed["next_action"] == {
        "type": "blocked",
        "text": "CP8 automatic precheck failed.",
        "stop_reason": "blocked",
    }


def test_projection_refresh_clears_failure_stop_after_formal_cr_closes(
    tmp_path: Path,
) -> None:
    project_root, process_root = _formal_fixture(tmp_path)
    formal_ref = process_root / "changes/CR-072.md"
    formal_ref.write_text(_native_cr_text("CR-072"), encoding="utf-8")
    current.refresh_formal_truth_projection(project_root)
    current.update_current_state(
        project_root,
        {
            "blocked": True,
            "next_action": {
                "type": "blocked",
                "text": "CP8 automatic precheck failed.",
                "stop_reason": "blocked",
            },
            "updated_at": current.now_utc(),
        },
        actor="tests.formal_projection",
        reason="install an explicit single-CR failure stop",
        mode="enforce",
    )
    formal_ref.write_text(_native_cr_text("CR-072", closed=True), encoding="utf-8")

    refreshed = current.refresh_formal_truth_projection(project_root)

    assert refreshed["active_change"] is None
    assert refreshed["blocked"] is False
    assert refreshed["next_action"]["type"] == "continue_active_phase"


def test_projection_refresh_converges_pending_gate_bound_to_current_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root, process_root = _formal_fixture(tmp_path)
    current.update_current_state(
        project_root,
        {
            "active_change": "CR-072",
            "pending_gate": "CP5",
            "pending_checklist_path": "process/checkpoints/CP5.md",
            "updated_at": current.now_utc(),
        },
        actor="tests.formal_projection",
        reason="install stale approved gate projection",
        mode="enforce",
    )
    from meta_flow.state import checkpoint_projection, event_ledger

    head = SimpleNamespace(result_ref="process/checks/CP5-current.result.json")
    projection = SimpleNamespace(
        findings=(),
        head=lambda checkpoint: head if checkpoint == "CP5" else None,
    )
    approval = SimpleNamespace(
        passage=True,
        cr_id="CR-072",
        checkpoint="CP5",
        result_ref=head.result_ref,
        event_id="GATE-CP5-APPROVED",
    )
    gate_path = process_root / "state/GATE-LEDGER.ndjson"
    gate_path.parent.mkdir(parents=True, exist_ok=True)
    gate_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        checkpoint_projection,
        "load_checkpoint_projection",
        lambda *args, **kwargs: projection,
    )
    monkeypatch.setattr(event_ledger, "load_events", lambda path: ([{}], []))
    monkeypatch.setattr(
        event_ledger, "project_gate_approvals", lambda events: [approval]
    )

    _patch, gate_convergence = current._derive_approved_pending_gate_patch(
        project_root, current.load_current_state(project_root)
    )
    plan = current.plan_formal_truth_refresh(project_root)
    refreshed = current.refresh_formal_truth_projection(project_root)

    assert gate_convergence["decision"] == "CONVERGE"
    assert plan["decision"] == "READY"
    assert refreshed["pending_gate"] is None
    assert refreshed["pending_checklist_path"] is None
    assert refreshed["next_action"]["type"] == "continue_active_phase"


def test_projection_refresh_keeps_pending_gate_when_approval_targets_old_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root, process_root = _formal_fixture(tmp_path)
    current.update_current_state(
        project_root,
        {
            "active_change": "CR-072",
            "pending_gate": "CP5",
            "pending_checklist_path": "process/checkpoints/CP5.md",
            "updated_at": current.now_utc(),
        },
        actor="tests.formal_projection",
        reason="install pending gate projection",
        mode="enforce",
    )
    from meta_flow.state import checkpoint_projection, event_ledger

    head = SimpleNamespace(result_ref="process/checks/CP5-current.result.json")
    projection = SimpleNamespace(findings=(), head=lambda checkpoint: head)
    old_approval = SimpleNamespace(
        passage=True,
        cr_id="CR-072",
        checkpoint="CP5",
        result_ref="process/checks/CP5-old.result.json",
        event_id="GATE-CP5-OLD-APPROVED",
    )
    gate_path = process_root / "state/GATE-LEDGER.ndjson"
    gate_path.parent.mkdir(parents=True, exist_ok=True)
    gate_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        checkpoint_projection,
        "load_checkpoint_projection",
        lambda *args, **kwargs: projection,
    )
    monkeypatch.setattr(event_ledger, "load_events", lambda path: ([{}], []))
    monkeypatch.setattr(
        event_ledger, "project_gate_approvals", lambda events: [old_approval]
    )

    refreshed = current.refresh_formal_truth_projection(project_root)

    assert refreshed["pending_gate"] == "CP5"


def test_formal_cr_truth_overrides_stale_active_ledger_event(tmp_path: Path) -> None:
    project_root, process_root = _formal_fixture(tmp_path)
    formal_ref = "process/changes/CR-064-closed.md"
    ledger_path = process_root / "state/CR-LEDGER.ndjson"
    ledger_path.write_text(
        json.dumps({"id": "CR-064", "status": "active", "full_ref": formal_ref})
        + "\n",
        encoding="utf-8",
    )
    formal_path = process_root / formal_ref.removeprefix("process/")
    formal_path.parent.mkdir(parents=True, exist_ok=True)
    formal_path.write_text(_native_cr_text("CR-064", closed=True), encoding="utf-8")

    state = current.refresh_formal_truth_projection(project_root)

    assert state["active_change"] is None
    assert state["formal_truth_projection"]["active_cr_ids"] == []
    assert formal_ref in state["formal_truth_projection"]["source_refs"]


def test_formal_cr_identity_mismatch_fails_closed(tmp_path: Path) -> None:
    project_root, process_root = _formal_fixture(tmp_path)
    formal_ref = "process/changes/CR-064-closed.md"
    ledger_path = process_root / "state/CR-LEDGER.ndjson"
    ledger_path.write_text(
        json.dumps({"id": "CR-064", "status": "active", "full_ref": formal_ref})
        + "\n",
        encoding="utf-8",
    )
    formal_path = process_root / formal_ref.removeprefix("process/")
    formal_path.parent.mkdir(parents=True, exist_ok=True)
    formal_path.write_text(
        "---\nkind: cr\ncr_id: CR-OTHER\nlifecycle_status: closed\n---\n",
        encoding="utf-8",
    )

    try:
        current.plan_formal_truth_refresh(project_root)
    except ValueError as exc:
        assert "UNREGISTERED_NON_NATIVE_CR" in str(exc)
    else:
        raise AssertionError("mismatched formal CR identity must fail closed")


def _recoverable_assessment() -> formal_projection.FailureAssessmentV1:
    expected = {
        "schema_digest": "e" * 64,
        "producer_contract_digest": "p" * 64,
        "derived_from_failure_projection": False,
    }
    candidate = {
        "candidate_count": 1,
        "source_identity_matches": True,
        "predicate_results": {
            "location": True,
            "owner": True,
            "current_lineage": True,
            "integrity": True,
            "completeness": True,
            "freshness": True,
            "validity": True,
        },
    }
    return formal_projection.evaluate_reprojection(
        expected,
        {"reason_code": "missing-evidence", "source_evidence_digest": "s" * 64},
        candidate,
        [{"class": "missing-evidence"}],
    )


def test_reprojection_assessment_and_plan_are_positive_sufficient_and_pure() -> None:
    assessment = _recoverable_assessment()
    assert assessment.decision == "RECOVERABLE"
    assert assessment.mutation_count == 0
    plan = formal_projection.plan_reprojection(
        assessment,
        {
            "target_projection_ref": "process/current/DERIVED.json",
            "target_projection_preimage_digest": "t" * 64,
            "target_blocker_id": "BLK-missing-evidence",
            "target_blocker_preimage_digest": "b" * 64,
        },
        {
            "release_oid": "r" * 40,
            "process_oid": "p" * 40,
            "dirty_inventory_digest": "d" * 64,
            "scope_authz_plan_digest": "a" * 64,
            "native_writer_id": "formal-projection-writer-v1",
        },
    )
    assert (plan.decision, plan.mutation_count) == ("READY", 0)
    denied = formal_projection.evaluate_reprojection(
        {"schema_digest": "e" * 64},
        {"reason_code": "missing-evidence"},
        {"candidate_count": 1, "source_identity_matches": True, "predicate_results": {}},
        [{"class": "PARTIAL"}],
    )
    assert denied.decision == "DENY"
    assert denied.reason_code == "VALID_ARTIFACT_BUT_INSUFFICIENT"


def test_guarded_reprojection_writer_is_one_shot_and_fails_closed_on_drift() -> None:
    plan = formal_projection.plan_reprojection(
        _recoverable_assessment(),
        {
            "target_projection_ref": "process/current/DERIVED.json",
            "target_projection_preimage_digest": "t" * 64,
            "target_blocker_id": "BLK-missing-evidence",
            "target_blocker_preimage_digest": "b" * 64,
        },
        {
            "release_oid": "r" * 40,
            "process_oid": "p" * 40,
            "dirty_inventory_digest": "d" * 64,
            "scope_authz_plan_digest": "a" * 64,
            "native_writer_id": "formal-projection-writer-v1",
        },
    )
    fresh = {
        "release_oid": plan.release_oid,
        "process_oid": plan.process_oid,
        "dirty_inventory_digest": plan.dirty_inventory_digest,
        "target_projection_preimage_digest": plan.target_projection_preimage_digest,
        "target_blocker_preimage_digest": plan.target_blocker_preimage_digest,
        "scope_authz_plan_digest": plan.scope_authz_plan_digest,
        "native_writer_id": plan.native_writer_id,
        "source_evidence_digest": plan.source_evidence_digest,
        "blockers": [{"class": "missing-evidence"}],
    }
    calls: list[formal_projection.ReprojectionPlanV1] = []

    def native_writer(argument: formal_projection.ReprojectionPlanV1, _fresh: dict) -> dict:
        calls.append(argument)
        return {"decision": "APPLIED", "mutation_count": 1}

    applied = formal_projection.apply_reprojection_plan(plan, fresh, native_writer)
    assert (applied.decision, applied.mutation_count, len(calls)) == ("APPLIED", 1, 1)
    drifted = formal_projection.apply_reprojection_plan(
        plan, {**fresh, "release_oid": "x" * 40}, native_writer
    )
    assert (drifted.decision, drifted.mutation_count, len(calls)) == ("BLOCKED_REPLAN", 0, 1)
    replay = formal_projection.apply_reprojection_plan(
        plan,
        {**fresh, "applied_source_keys": [(plan.source_evidence_digest, plan.expected_schema_digest, plan.target_blocker_id)]},
        native_writer,
    )
    assert (replay.decision, replay.mutation_count, len(calls)) == ("NO_CHANGE", 0, 1)
