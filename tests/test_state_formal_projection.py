from __future__ import annotations

import json
from pathlib import Path

from meta_flow.state import current, formal_projection


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _formal_fixture(root: Path) -> None:
    _write_json(
        root / "process/PROJECT.yaml",
        {
            "schema_version": 1,
            "project_id": "fixture",
            "status": "active",
            "roadmap_ref": "ROADMAP.yaml",
        },
    )
    _write_json(
        root / "process/ROADMAP.yaml",
        {
            "schema_version": 1,
            "project_id": "fixture",
            "status": "active",
            "phase_refs": ["phases/P1/PHASE.yaml"],
        },
    )
    _write_json(
        root / "process/phases/P1/PHASE.yaml",
        {
            "schema_version": 1,
            "project_id": "fixture",
            "phase_id": "P1",
            "status": "active",
            "work_refs": [],
            "result_refs": [],
        },
    )
    (root / "process/changes").mkdir(parents=True, exist_ok=True)
    current.write_current_state(root, current.default_current_state(root, project_id="fixture"))
    current.render_state_file(root, force=True)


def test_enforce_rejects_state_that_is_internally_consistent_but_formally_stale(
    tmp_path: Path,
) -> None:
    _formal_fixture(tmp_path)

    errors, _warnings = current.check_current_state(tmp_path, mode="enforce")

    assert any("formal_truth_projection_stale" in error for error in errors)
    assert any("formal_truth_field_stale: current_phase" in error for error in errors)
    assert any("formal_truth_field_stale: next_action" in error for error in errors)


def test_projection_refresh_is_zero_write_then_transactionally_converges(
    tmp_path: Path,
) -> None:
    _formal_fixture(tmp_path)
    before = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    plan = current.plan_formal_truth_refresh(tmp_path)

    after_plan = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert before == after_plan
    assert plan["decision"] == "READY"
    assert plan["mutation_count"] == 0
    assert plan["planned_mutation_count"] == 3

    state = current.refresh_formal_truth_projection(tmp_path)
    errors, warnings = current.check_current_state(tmp_path, mode="enforce")

    assert errors == []
    assert warnings == []
    assert state["current_phase"] == "P1"
    assert state["next_action"]["type"] == "continue_active_phase"
    projected = json.loads((tmp_path / "process/current/CURRENT.json").read_text(encoding="utf-8"))
    assert projected["phase"] == "P1"
    assert projected["updated_at"] == state["updated_at"]
    assert "Phase: P1" in (tmp_path / "process/STATE.md").read_text(encoding="utf-8")


def test_projection_refresh_preserves_pending_human_gate_stop_semantics(
    tmp_path: Path,
) -> None:
    _formal_fixture(tmp_path)
    checkpoint_ref = "process/checkpoints/CP2-BASELINE.md"
    checkpoint_path = tmp_path / checkpoint_ref
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_text("# CP2\n", encoding="utf-8")
    state = current.load_current_state(tmp_path)
    state.update(
        {
            "pending_gate": "CP2",
            "pending_checklist_path": checkpoint_ref,
            "next_action": {
                "type": "human_gate",
                "text": "Review CP2.",
                "stop_reason": "required_human_gate",
            },
        }
    )
    current.write_current_state(tmp_path, state, force=True)
    current.render_state_file(tmp_path, force=True)

    refreshed = current.refresh_formal_truth_projection(tmp_path)
    errors, warnings = current.check_current_state(tmp_path, mode="enforce")

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


def test_formal_cr_truth_overrides_stale_active_ledger_event(tmp_path: Path) -> None:
    _formal_fixture(tmp_path)
    formal_ref = "process/changes/CR-064-closed.md"
    ledger_path = tmp_path / "process/state/CR-LEDGER.ndjson"
    ledger_path.write_text(
        json.dumps({"id": "CR-064", "status": "active", "full_ref": formal_ref})
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / formal_ref).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / formal_ref).write_text(
        "---\nkind: cr\ncr_id: CR-064\nlifecycle_status: closed\nstatus: closed\n---\n",
        encoding="utf-8",
    )

    state = current.refresh_formal_truth_projection(tmp_path)

    assert state["active_change"] is None
    assert state["formal_truth_projection"]["active_cr_ids"] == []
    assert formal_ref in state["formal_truth_projection"]["source_refs"]


def test_formal_cr_identity_mismatch_fails_closed(tmp_path: Path) -> None:
    _formal_fixture(tmp_path)
    formal_ref = "process/changes/CR-064-closed.md"
    ledger_path = tmp_path / "process/state/CR-LEDGER.ndjson"
    ledger_path.write_text(
        json.dumps({"id": "CR-064", "status": "active", "full_ref": formal_ref})
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / formal_ref).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / formal_ref).write_text(
        "---\nkind: cr\ncr_id: CR-OTHER\nlifecycle_status: closed\n---\n",
        encoding="utf-8",
    )

    try:
        current.plan_formal_truth_refresh(tmp_path)
    except ValueError as exc:
        assert "truth missing" in str(exc)
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
