from __future__ import annotations

import hashlib
import json
from contextlib import redirect_stdout
from datetime import UTC, datetime
from io import StringIO

import pytest

from meta_flow import package_cli
from meta_flow.workflow.package_plan import canonical_digest
from meta_flow.workflow.release_order import (
    ACTION_COUNT_KEYS,
    AggregateReleaseStateV1,
    FileReleaseWriter,
    InMemoryReleaseWriter,
    ReleaseEventV1,
    ReleaseSnapshotV1,
    ReleaseTransitionAuthorizationV1,
    apply_release_advance,
    build_initial_release_state,
    check_release_transition,
    inspect_release_journal,
    plan_release_advance,
    recover_release_transition,
)

_TARGETS = {
    "candidate-ready": "source-candidate-ready",
    "freeze-source": "source-frozen",
    "decide-version": "version-decided",
    "fingerprint": "fingerprinted",
    "qualify-provider-source": "provider-qualified",
    "build-artifacts": "artifacts-built",
    "pass-canary": "canary-passed",
    "approve-cp8": "cp8-approved",
    "release": "released",
}


def _initial(*, work_digests: list[str] | None = None) -> AggregateReleaseStateV1:
    return build_initial_release_state(
        package_id="0.6.1-release-package",
        cr_id="CR-072",
        version="0.6.1",
        source_fingerprint="a" * 64,
        plan_digest="b" * 64,
        cost_digest="c" * 64,
        compatibility_digest="d" * 64,
        work_verification_digests=work_digests or ["e" * 64, "f" * 64],
        predecessor_receipt_digest="0" * 64,
    )


def _event(
    state: AggregateReleaseStateV1,
    action: str,
    *,
    event_id: str | None = None,
    evidence_digest: str = "1" * 64,
    execution_class: str = "release-action",
    harness_error_count: int = 0,
) -> ReleaseEventV1:
    wheel_build_count = 1 if action == "build-artifacts" else 0
    qualification_increment = 1 if action == "qualify-provider-source" else 0
    materialization_count = 1 if action == "build-artifacts" else 0
    bootstrap_key = "2" * 64 if action == "decide-version" else ""
    assets = [f"{index:x}" * 64 for index in range(3, 7)] if action == "build-artifacts" else []
    return ReleaseEventV1.from_mapping(
        {
            "schema_version": 1,
            "event_id": event_id or f"EV-{len(state.event_records) + 1}-{action}",
            "action": action,
            "target_state": _TARGETS[action],
            "package_id": state.package_id,
            "cr_id": state.cr_id,
            "version": state.version,
            "predecessor_receipt_digest": state.predecessor_receipt_digest,
            "source_fingerprint": state.source_fingerprint,
            "plan_digest": state.plan_digest,
            "cost_digest": state.cost_digest,
            "compatibility_digest": state.compatibility_digest,
            "evidence_ref": f"process/evidence/{action}.json",
            "evidence_digest": evidence_digest,
            "execution_class": execution_class,
            "reservation_id": f"RES-{action}",
            "attempt_id": f"ATTEMPT-{action}",
            "bootstrap_consumption_key": bootstrap_key,
            "source_qualification_receipt_digest": "8" * 64
            if action == "build-artifacts"
            else "",
            "wheel_build_count": wheel_build_count,
            "qualification_increment": qualification_increment,
            "materialization_count": materialization_count,
            "intermediate_release_count": 0,
            "harness_error_count": harness_error_count,
            "asset_digests": assets,
        }
    )


def _snapshot(
    state: AggregateReleaseStateV1,
    writer: InMemoryReleaseWriter,
    *,
    journal_status: str = "clean",
    source_fingerprint: str | None = None,
) -> ReleaseSnapshotV1:
    ledger_digest, projection_digest = writer.preimage_digests()
    return ReleaseSnapshotV1.from_mapping(
        {
            "schema_version": 1,
            "state_digest": state.state_digest,
            "source_fingerprint": source_fingerprint or state.source_fingerprint,
            "plan_digest": state.plan_digest,
            "cost_digest": state.cost_digest,
            "compatibility_digest": state.compatibility_digest,
            "dirty_inventory_digest": "7" * 64,
            "ledger_preimage_digest": ledger_digest,
            "projection_preimage_digest": projection_digest,
            "journal_status": journal_status,
        }
    )


def _authorization(
    plan,
    *,
    action: str | None = None,
    issued_at: str = "2026-08-19T00:00:00+00:00",
    expires_at: str = "2026-08-20T00:00:00+00:00",
) -> ReleaseTransitionAuthorizationV1:
    payload = {
        "schema_version": 1,
        "authorization_id": f"AUTH-{plan.event.event_id}",
        "authorization_ref": f"process/authorizations/{plan.event.event_id}.json",
        "action": action or plan.event.action,
        "event_id": plan.event.event_id,
        "plan_digest": plan.plan_digest,
        "before_state_digest": plan.before_state.state_digest,
        "source_fingerprint": plan.before_state.source_fingerprint,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "reusable": False,
    }
    payload["authorization_digest"] = canonical_digest(payload)
    return ReleaseTransitionAuthorizationV1.from_mapping(payload)


def _apply_one(
    state: AggregateReleaseStateV1,
    action: str,
    writer: InMemoryReleaseWriter,
) -> tuple[AggregateReleaseStateV1, ReleaseEventV1]:
    event = _event(state, action)
    snapshot = _snapshot(state, writer)
    plan = plan_release_advance(state, event, snapshot)
    assert plan.decision == "PASS", [item.code for item in plan.diagnostics]
    receipt = apply_release_advance(
        plan,
        _authorization(plan),
        snapshot,
        writer,
        now=datetime(2026, 8, 19, 12, tzinfo=UTC),
    )
    assert receipt.status == "PASS"
    assert receipt.decision == "PASS"
    assert receipt.mutation_count == 3
    assert plan.after_state is not None
    return plan.after_state, event


def test_rl001_exact_predecessor_sequence_reaches_one_released_lineage() -> None:
    writer = InMemoryReleaseWriter()
    state = _initial()
    actions = list(_TARGETS)
    for action in actions:
        state, _event_value = _apply_one(state, action, writer)
    assert state.current_state == "released"
    counts = dict(state.action_counts)
    assert set(counts) == set(ACTION_COUNT_KEYS)
    assert all(counts[key] == 1 for key in ACTION_COUNT_KEYS if key != "intermediate-release")
    assert counts["intermediate-release"] == 0
    assert state.consumed_bootstrap_keys == ("2" * 64,)
    assert len(state.event_records) == 9
    assert inspect_release_journal(writer, state.event_records[-1].event_id)["status"] == "PASS"


def test_rl002_skip_and_reverse_are_zero_write_blocked() -> None:
    state = _initial()
    for action in ("freeze-source", "release"):
        result = check_release_transition(state, _event(state, action))
        assert result.decision == "BLOCKED"
        assert result.mutation_count == 0
        codes = {item.code for item in result.diagnostics}
        assert codes & {"RELEASE_ORDER_VIOLATION", "INTERMEDIATE_RELEASE_FORBIDDEN"}


def test_rl003_work_a_only_cannot_create_an_intermediate_lineage() -> None:
    state = _initial(work_digests=["e" * 64])
    result = check_release_transition(state, _event(state, "candidate-ready"))
    assert result.decision == "BLOCKED"
    assert "INTERMEDIATE_RELEASE_FORBIDDEN" in {item.code for item in result.diagnostics}


def test_rl004_freeze_drift_and_unclean_journal_block_planning() -> None:
    writer = InMemoryReleaseWriter()
    state = _initial()
    event = _event(state, "candidate-ready")
    drift = plan_release_advance(
        state,
        event,
        _snapshot(state, writer, source_fingerprint="9" * 64),
    )
    assert drift.decision == "BLOCKED"
    assert "SOURCE_FREEZE_DRIFT" in {item.code for item in drift.diagnostics}
    partial = plan_release_advance(
        state,
        event,
        _snapshot(state, writer, journal_status="partial"),
    )
    assert partial.decision == "BLOCKED"
    assert "RELEASE_JOURNAL_NOT_CLEAN" in {item.code for item in partial.diagnostics}


def test_rl005_stale_predecessor_and_binding_drift_are_blocked() -> None:
    state = _initial()
    raw = _event(state, "candidate-ready").as_dict()
    raw["predecessor_receipt_digest"] = "8" * 64
    raw["plan_digest"] = "9" * 64
    result = check_release_transition(state, ReleaseEventV1.from_mapping(raw))
    assert {item.code for item in result.diagnostics} >= {
        "RELEASE_PREDECESSOR_STALE",
        "RELEASE_BINDING_DRIFT",
    }


def test_rl006_same_event_replay_is_noop_but_different_evidence_conflicts() -> None:
    writer = InMemoryReleaseWriter()
    initial = _initial()
    state, event = _apply_one(initial, "candidate-ready", writer)
    same = check_release_transition(state, event)
    assert same.decision == "NO_CHANGE"
    raw = event.as_dict()
    raw["evidence_digest"] = "9" * 64
    conflict = check_release_transition(state, ReleaseEventV1.from_mapping(raw))
    assert conflict.decision == "BLOCKED"
    assert [item.code for item in conflict.diagnostics] == ["RELEASE_EVENT_CONFLICT"]


@pytest.mark.parametrize(
    ("action", "count_code"),
    [
        ("qualify-provider-source", "PROVIDER_QUALIFICATION_COUNT_EXCEEDED"),
        ("build-artifacts", "ARTIFACT_BUILD_COUNT_EXCEEDED"),
        ("pass-canary", "CANARY_COUNT_EXCEEDED"),
        ("approve-cp8", "CP8_COUNT_EXCEEDED"),
        ("release", "RELEASE_COUNT_EXCEEDED"),
    ],
)
def test_rl008_009_second_action_attempt_hard_fails(action: str, count_code: str) -> None:
    writer = InMemoryReleaseWriter()
    state = _initial()
    for current in _TARGETS:
        state, _ = _apply_one(state, current, writer)
        if current == action:
            break
    second = _event(state, action, event_id=f"EV-second-{action}")
    result = check_release_transition(state, second)
    assert result.decision == "BLOCKED"
    assert count_code in {item.code for item in result.diagnostics}


def test_rl010_harness_error_blocks_qualification() -> None:
    writer = InMemoryReleaseWriter()
    state = _initial()
    for action in ("candidate-ready", "freeze-source", "decide-version", "fingerprint"):
        state, _ = _apply_one(state, action, writer)
    result = check_release_transition(
        state,
        _event(state, "qualify-provider-source", harness_error_count=1),
    )
    assert "CHECK_HARNESS_ERROR_UNRESOLVED" in {item.code for item in result.diagnostics}


def test_plan_apply_revalidates_typed_scope_expiry_and_fresh_preimage() -> None:
    writer = InMemoryReleaseWriter()
    state = _initial()
    event = _event(state, "candidate-ready")
    snapshot = _snapshot(state, writer)
    plan = plan_release_advance(state, event, snapshot)
    wrong_scope = _authorization(plan, action="freeze-source")
    receipt = apply_release_advance(
        plan,
        wrong_scope,
        snapshot,
        writer,
        now=datetime(2026, 8, 19, 12, tzinfo=UTC),
    )
    assert (receipt.status, receipt.error_code, receipt.mutation_count) == (
        "BLOCKED",
        "RELEASE_AUTHORIZATION_SCOPE_MISMATCH",
        0,
    )
    expired = _authorization(
        plan,
        issued_at="2026-08-17T00:00:00+00:00",
        expires_at="2026-08-18T00:00:00+00:00",
    )
    receipt = apply_release_advance(
        plan,
        expired,
        snapshot,
        writer,
        now=datetime(2026, 8, 19, 12, tzinfo=UTC),
    )
    assert receipt.error_code == "RELEASE_AUTHORIZATION_EXPIRED"
    drift_raw = snapshot.as_dict()
    drift_raw["dirty_inventory_digest"] = "9" * 64
    receipt = apply_release_advance(
        plan,
        _authorization(plan),
        ReleaseSnapshotV1.from_mapping(drift_raw),
        writer,
        now=datetime(2026, 8, 19, 12, tzinfo=UTC),
    )
    assert receipt.error_code == "RELEASE_FRESH_PREIMAGE_MISMATCH"


def test_projection_failure_is_partial_and_recovery_is_terminal_for_review() -> None:
    writer = InMemoryReleaseWriter(fail_at="projection")
    state = _initial()
    event = _event(state, "candidate-ready")
    snapshot = _snapshot(state, writer)
    plan = plan_release_advance(state, event, snapshot)
    authorization = _authorization(plan)
    receipt = apply_release_advance(
        plan,
        authorization,
        snapshot,
        writer,
        now=datetime(2026, 8, 19, 12, tzinfo=UTC),
    )
    assert (receipt.status, receipt.error_code, receipt.mutation_count) == (
        "PARTIAL",
        "RELEASE_PROJECTION_FAILED",
        1,
    )
    assert inspect_release_journal(writer, event.event_id)["status"] == "PARTIAL"
    writer.fail_at = ""
    ledger_digest, projection_digest = writer.preimage_digests()
    partial_snapshot = ReleaseSnapshotV1.from_mapping(
        {
            **snapshot.as_dict(),
            "ledger_preimage_digest": ledger_digest,
            "projection_preimage_digest": projection_digest,
            "journal_status": "partial",
        }
    )
    recovered = recover_release_transition(
        plan,
        authorization,
        partial_snapshot,
        writer,
        now=datetime(2026, 8, 19, 12, tzinfo=UTC),
    )
    assert recovered.status == "RECOVERED"
    assert recovered.decision == "BLOCKED"
    assert recovered.error_code == "RELEASE_RECOVERED_REVIEW_REQUIRED"
    assert inspect_release_journal(writer, event.event_id)["status"] == "RECOVERED"


def test_file_writer_reuses_qualified_atomic_primitive_and_binds_preimages(tmp_path) -> None:
    state = _initial()
    event = _event(state, "candidate-ready")
    empty_digest = hashlib.sha256(b"").hexdigest()
    snapshot = ReleaseSnapshotV1.from_mapping(
        {
            "schema_version": 1,
            "state_digest": state.state_digest,
            "source_fingerprint": state.source_fingerprint,
            "plan_digest": state.plan_digest,
            "cost_digest": state.cost_digest,
            "compatibility_digest": state.compatibility_digest,
            "dirty_inventory_digest": "7" * 64,
            "ledger_preimage_digest": empty_digest,
            "projection_preimage_digest": empty_digest,
            "journal_status": "clean",
        }
    )
    plan = plan_release_advance(state, event, snapshot)
    writer = FileReleaseWriter(tmp_path / "ledger.ndjson", tmp_path / "CURRENT.json")
    receipt = apply_release_advance(
        plan,
        _authorization(plan),
        snapshot,
        writer,
        now=datetime(2026, 8, 19, 12, tzinfo=UTC),
    )
    assert receipt.status == "PASS"
    assert plan.after_state is not None
    assert AggregateReleaseStateV1.from_mapping(
        json.loads((tmp_path / "CURRENT.json").read_text(encoding="utf-8"))
    ).state_digest == plan.after_state.state_digest
    records = [
        json.loads(line)
        for line in (tmp_path / "ledger.ndjson").read_text(encoding="utf-8").splitlines()
    ]
    assert [item["journal_state"] for item in records] == ["PREPARED", "COMMITTED"]


def test_simulated_event_is_non_authoritative_and_build_contract_is_exact() -> None:
    state = _initial()
    simulated = check_release_transition(
        state,
        _event(state, "candidate-ready", execution_class="fixture"),
    )
    assert "SIMULATED_EVIDENCE_NON_AUTHORITATIVE" in {
        item.code for item in simulated.diagnostics
    }
    writer = InMemoryReleaseWriter()
    for action in ("candidate-ready", "freeze-source", "decide-version", "fingerprint", "qualify-provider-source"):
        state, _ = _apply_one(state, action, writer)
    raw = _event(state, "build-artifacts").as_dict()
    raw["qualification_increment"] = 1
    raw["asset_digests"] = ["3" * 64]
    result = check_release_transition(state, ReleaseEventV1.from_mapping(raw))
    assert "ARTIFACT_MATERIALIZATION_CONTRACT_INVALID" in {
        item.code for item in result.diagnostics
    }


def test_release_state_and_event_schemas_are_closed_and_digest_bound() -> None:
    state = _initial()
    state_raw = state.as_dict()
    with pytest.raises(ValueError, match="RELEASE_STATE_FIELDS_MISMATCH"):
        AggregateReleaseStateV1.from_mapping({**state_raw, "extra": True})
    state_raw["current_state"] = "released"
    with pytest.raises(ValueError, match="RELEASE_STATE_DIGEST_MISMATCH"):
        AggregateReleaseStateV1.from_mapping(state_raw)
    event_raw = _event(state, "candidate-ready").as_dict()
    with pytest.raises(ValueError, match="RELEASE_EVENT_FIELDS_MISMATCH"):
        ReleaseEventV1.from_mapping({**event_raw, "extra": True})


def test_release_public_check_and_plan_are_zero_write(tmp_path) -> None:
    writer = InMemoryReleaseWriter()
    state = _initial()
    event = _event(state, "candidate-ready")
    snapshot = _snapshot(state, writer)
    objects = {
        "state.json": state.as_dict(),
        "event.json": event.as_dict(),
        "snapshot.json": snapshot.as_dict(),
    }
    for name, value in objects.items():
        (tmp_path / name).write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    before = {name: (tmp_path / name).read_bytes() for name in objects}
    output = StringIO()
    with redirect_stdout(output):
        code = package_cli.main(
            [
                "release-check",
                "--cr",
                "CR-072",
                "--state",
                "state.json",
                "--candidate-event",
                "event.json",
                "--evidence",
                event.evidence_ref,
                "--project-root",
                str(tmp_path),
            ]
        )
    assert code == 0
    assert json.loads(output.getvalue())["decision"] == "PASS"
    output = StringIO()
    with redirect_stdout(output):
        code = package_cli.main(
            [
                "release-advance",
                "--cr",
                "CR-072",
                "--state",
                "state.json",
                "--candidate-event",
                "event.json",
                "--snapshot",
                "snapshot.json",
                "--project-root",
                str(tmp_path),
            ]
        )
    plan = json.loads(output.getvalue())
    assert code == 0
    assert plan["decision"] == "PASS"
    assert plan["mutation_count"] == 0
    assert before == {name: (tmp_path / name).read_bytes() for name in objects}
