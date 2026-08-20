from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from meta_flow.checks import cp_result, state_transition
from meta_flow.execution_control.failure import (
    FrozenFailureEvidenceV1,
    FrozenFailureResultItemV1,
)
from meta_flow.state import current, formal_projection
from meta_flow.state.failure_observation import (
    FailureObservationFactV1,
    FailureReceiptFactV1,
    FailureTruthStatusV1,
    GateHeadFactV1,
    correlate_failure_truth,
    evaluate_projection_safety,
)

HEX_A = "a" * 64
HEX_B = "b" * 64


def _receipt(*, current_head: bool = True, superseded_by: str = "") -> FailureReceiptFactV1:
    return FailureReceiptFactV1(
        work_id="W-1",
        evidence_ref="process/works/W-1/FAILURE-EVIDENCE.json",
        evidence_digest=HEX_A,
        check_result_digest=HEX_B,
        decision="FAIL",
        current=current_head,
        superseded_by=superseded_by,
    )


def _observation(*, status: str = "recorded") -> FailureObservationFactV1:
    return FailureObservationFactV1(
        observation_ref="EC-OBS-1",
        evidence_ref="process/works/W-1/FAILURE-EVIDENCE.json",
        check_result_digest=HEX_B,
        registration_status=status,
    )


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
            "active_work_refs": ["works/W-1/WORK.yaml"],
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
            "phase_id": "P1",
            "status": "active",
            "work_refs": [],
            "result_refs": [],
        },
    )
    _write_json(
        root / "process/works/W-1/WORK.yaml",
        {
            "schema_version": 1,
            "work_id": "W-1",
            "project_id": "fixture",
            "status": "active",
        },
    )
    (root / "process/changes").mkdir(parents=True, exist_ok=True)
    current.write_current_state(root, current.default_current_state(root, project_id="fixture"))
    current.render_state_file(root, force=True)


def _write_failure_evidence(root: Path) -> FrozenFailureEvidenceV1:
    item = FrozenFailureResultItemV1(
        item_id="targeted-result",
        check_group_id="targeted",
        status="FAIL",
        reason_codes=("REAL_CONTENT_FAILURE",),
    )
    evidence = FrozenFailureEvidenceV1.build(
        unit_id="W-1",
        check_profile_digest=sha256(b"profile").hexdigest(),
        required_check_ids=("targeted",),
        contract_revision=1,
        target_scope_digest=sha256(b"scope").hexdigest(),
        result_item=item,
        observed_at="2026-08-20T00:00:00Z",
    )
    _write_json(root / "process/works/W-1/FAILURE-EVIDENCE.json", evidence.as_dict())
    return evidence


def test_orphan_fail_and_registration_failure_are_non_healthy() -> None:
    orphan = correlate_failure_truth((_receipt(),), ())
    failed_registration = correlate_failure_truth(
        (_receipt(),),
        (_observation(status="failed"),),
    )

    assert orphan.status is FailureTruthStatusV1.ORPHAN_FAIL
    assert orphan.finding_codes == ("ORPHAN_FAIL_RECEIPT",)
    assert evaluate_projection_safety(orphan)[0].next_action == "blocked"
    assert failed_registration.status is FailureTruthStatusV1.BLOCKED
    assert failed_registration.finding_codes == (
        "FAILURE_OBSERVATION_REGISTRATION_FAILED",
    )


def test_recorded_observation_is_healthy_and_historical_fail_is_ignored() -> None:
    recorded = correlate_failure_truth((_receipt(),), (_observation(),))
    historical = correlate_failure_truth(
        (_receipt(current_head=False, superseded_by="PASS-2"),),
        (),
    )

    assert recorded.status is FailureTruthStatusV1.HEALTHY
    assert historical.status is FailureTruthStatusV1.HEALTHY


def test_missing_formal_gate_has_stable_machine_finding() -> None:
    correlation = correlate_failure_truth(
        (),
        (),
        GateHeadFactV1(expected_gate="CP5", projected_gate=""),
    )

    assert correlation.status is FailureTruthStatusV1.PENDING_GATE_MISSING
    assert correlation.finding_codes == ("FORMAL_PENDING_GATE_MISSING",)
    assert evaluate_projection_safety(correlation)[0].stop_reason == "blocked"


def test_native_projection_blocks_orphan_then_converges_after_observation(
    tmp_path: Path,
) -> None:
    _formal_fixture(tmp_path)
    evidence = _write_failure_evidence(tmp_path)

    blocked = current.refresh_formal_truth_projection(tmp_path)
    assert blocked["blocked"] is True
    assert blocked["next_action"]["type"] == "blocked"
    assert blocked["formal_truth_projection"]["failure_truth"]["status"] == "orphan_fail"

    event_seed = {
        "event_id": "EC-OBS-" + "1" * 32,
        "event_type": "finding_observation",
        "unit_id": "W-1",
        "attempt_id": "A-1",
        "evidence_ref": "process/works/W-1/FAILURE-EVIDENCE.json",
        "check_result_digest": evidence.check_result_digest,
        "observation_key_digest": "2" * 64,
        "identity_digest": "3" * 64,
        "contract_revision": 1,
        "classification_digest": "4" * 64,
        "slice_route_digest": "5" * 64,
        "attempt_plan_digest": "6" * 64,
        "observed_at": "2026-08-20T00:00:00Z",
    }
    # 使用 canonical builder 保证 event identity 与 payload digest 自洽。
    from meta_flow.state.event_ledger import (
        FindingObservationEventV1,
        execution_control_digest,
    )

    observation_key = execution_control_digest(
        {
            "unit_id": "W-1",
            "attempt_id": "A-1",
            "check_result_digest": evidence.check_result_digest,
            "identity_digest": "3" * 64,
        }
    )

    event = FindingObservationEventV1.build(
        **{
            **event_seed,
            "event_id": "EC-OBS-" + observation_key[:32],
            "observation_key_digest": observation_key,
        }
    )
    ledger = tmp_path / "process/state/EXECUTION-CONTROL-LEDGER.ndjson"
    ledger.write_text(
        json.dumps(event.as_dict(), ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    recovered = current.refresh_formal_truth_projection(tmp_path)
    second_plan = current.plan_formal_truth_refresh(tmp_path)

    assert recovered["blocked"] is False
    assert recovered["formal_truth_projection"]["failure_truth"]["status"] == "healthy"
    assert second_plan["planned_mutation_count"] == 0


def test_derived_manual_edit_is_rejected_against_formal_failure_truth(tmp_path: Path) -> None:
    _formal_fixture(tmp_path)
    _write_failure_evidence(tmp_path)
    current.refresh_formal_truth_projection(tmp_path)
    state_path = tmp_path / "process/state/STATE.current.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["blocked"] = False
    state["next_action"] = {
        "type": "continue_active_work",
        "text": "unsafe manual edit",
        "stop_reason": None,
    }
    _write_json(state_path, state)

    errors, _warnings = current.check_current_state(tmp_path, mode="enforce")

    assert any("formal_truth_field_stale: blocked" in item for item in errors)
    assert any("formal_failure_truth_nonhealthy" in item for item in errors)


def test_formal_projection_maps_injected_failure_truth_to_blocked() -> None:
    snapshot = {
        "active_phase_ids": ["P1"],
        "active_work_ids": ["W-1"],
        "active_cr_ids": ["CR-1"],
        "source_refs": [],
        "failure_truth": {
            "schema_version": 1,
            "status": "orphan_fail",
            "receipt_refs": ["process/works/W-1/FAILURE-EVIDENCE.json"],
            "observation_refs": [],
            "finding_codes": ["ORPHAN_FAIL_RECEIPT"],
        },
    }
    patch = formal_projection.derive_formal_truth_patch({}, snapshot)

    assert patch["blocked"] is True
    assert patch["next_action"]["stop_reason"] == "blocked"


def _cp7_result(*, reason: str = "authorization_required") -> dict:
    return {
        "schema_version": 1,
        "checkpoint": "CP7",
        "checkpoint_id": "CP7-CR-073-AGGREGATE-R2",
        "story_id": "STORY-CR073-S06",
        "cr_id": "CR-073",
        "context_ref": "process/context/CP7-CR073.context.json",
        "evidence_ref": "process/evidence/STORY-CR073-S06.CP6.index.json",
        "dispatch_refs": ["ADE-CR073-QA"],
        "items": [
            {
                "id": "CP7-01",
                "name": "aggregate content verified",
                "status": "PASS",
                "severity": "BLOCKER",
                "evidence_refs": ["process/checks/CR073-CP7-FINAL-FRESH-FULL.result.json"],
            }
        ],
        "blockers": [],
        "waivers": [],
        "decision": "PASS_WITH_RISK",
        "transition_stop": {
            "schema_version": 1,
            "reason": reason,
            "expected_kind": "required_human_gate",
            "evidence_refs": [
                "process/checks/CR073-CP7-QUANT-LAB-IDENTITY-DISCOVERY-R2.result.json"
            ],
            "message": "Await exact quant-lab root authorization before victim replay.",
        },
        "next_route": "CP7-QUANT-LAB-EXACT-ROOT-AUTHORIZATION",
    }


def test_cp_result_transition_stop_is_closed_and_decision_compatible(tmp_path: Path) -> None:
    result_path = tmp_path / "CP7.result.json"
    _write_json(result_path, _cp7_result())

    errors, _warnings = cp_result.validate_cp_result(result_path, project_root=tmp_path)
    assert not [item for item in errors if "transition_stop" in item]

    invalid = _cp7_result(reason="delivered")
    _write_json(result_path, invalid)
    errors, _warnings = cp_result.validate_cp_result(result_path, project_root=tmp_path)
    assert errors == [
        "transition_stop.reason is incompatible with decision/expected_kind: delivered"
    ]


def test_canonical_cp7_transition_stop_projects_authorization_without_raw_state_edit(
    tmp_path: Path,
) -> None:
    _formal_fixture(tmp_path)
    (tmp_path / "process/changes/CR-073.md").write_text(
        "---\nkind: cr\ncr_id: CR-073\nlifecycle_status: active\nstatus: active\n---\n",
        encoding="utf-8",
    )
    result_ref = "process/checks/CP7-CR-073-AGGREGATE-R2.result.json"
    _write_json(tmp_path / result_ref, _cp7_result())
    ledger = tmp_path / "process/state/CHECKPOINT-LEDGER.ndjson"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(
        json.dumps(
            {
                "event_id": "CP7-CR-073-AGGREGATE-R2",
                "event_type": "checkpoint_result",
                "checkpoint": "CP7",
                "decision": "PASS_WITH_RISK",
                "result_ref": result_ref,
                "story_id": "STORY-CR073-S06",
                "cr_id": "CR-073",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    projected = current.refresh_formal_truth_projection(tmp_path)

    assert projected["blocked"] is False, projected
    assert projected["next_action"] == {
        "type": "await_user",
        "text": "Await exact quant-lab root authorization before victim replay.",
        "stop_reason": "authorization_required",
    }
    assert projected["formal_truth_projection"]["transition_stop"]["result_ref"] == result_ref
    errors, warnings = state_transition.validate_auto_cp_transition(
        route={
            "stages": [
                {"checkpoint": "CP7", "human_gate": "none"},
                {"checkpoint": "CP8", "human_gate": "required"},
            ]
        },
        state=projected,
        checkpoint="CP7",
        decision="PASS_WITH_RISK",
    )
    assert errors == []
    assert warnings == []
