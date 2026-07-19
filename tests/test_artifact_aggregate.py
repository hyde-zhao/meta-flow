from __future__ import annotations

import copy
import inspect
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from itertools import product
from pathlib import Path
from typing import Any

import pytest

from meta_flow.state import current as current_state
from meta_flow.workflow import artifact_aggregate as aggregate_module
from meta_flow.workflow import cr_lifecycle
from meta_flow.workflow.artifact_aggregate import (
    AggregateRequest,
    AggregateStatus,
    FileAggregateStore,
    InMemoryAggregateStore,
    PersistDisposition,
    ProjectionDecision,
    ProjectionStatus,
    canonical_json_digest,
    canonical_leg_receipt_digest,
    compute_aggregate,
    coordinate_aggregate,
    derive_leg_single_write_key,
    persist_aggregate,
    project_if_eligible,
    validate_published_leg_results,
)

STATUSES = (
    AggregateStatus.BLOCKED,
    AggregateStatus.FAIL,
    AggregateStatus.IN_PROGRESS,
    AggregateStatus.PASS,
)
PRECEDENCE = {
    AggregateStatus.BLOCKED: 4,
    AggregateStatus.FAIL: 3,
    AggregateStatus.IN_PROGRESS: 2,
    AggregateStatus.PASS: 1,
}


class MemoryLegReader:
    def __init__(self, payloads: dict[str, dict[str, Any]]) -> None:
        self.payloads = copy.deepcopy(payloads)
        self.calls: list[str] = []

    def read(self, result_ref: str) -> dict[str, Any]:
        self.calls.append(result_ref)
        return copy.deepcopy(self.payloads[result_ref])


def _correlation(leg_kind: str) -> dict[str, Any]:
    return {
        "operation_id": "operation-001",
        "logical_attempt": 1,
        "cr_id": "CR-051",
        "project_id": "meta-flow",
        "leg_kind": leg_kind,
    }


def _mode(leg_kind: str) -> str:
    return "source-default" if leg_kind == "source" else "shared-artifact-project-first"


def _payload(leg_kind: str, status: AggregateStatus) -> dict[str, Any]:
    terminal = status is not AggregateStatus.IN_PROGRESS
    if leg_kind == "source":
        base_ref = target_ref = "refs/heads/main"
        active_ref = "refs/heads/cr/cr-051-fixture"
    else:
        base_ref = target_ref = "refs/heads/projects/meta-flow/integration"
        active_ref = "refs/heads/projects/meta-flow/cr/cr-051-fixture"
    payload: dict[str, Any] = {
        "schema_version": 1,
        "correlation": _correlation(leg_kind),
        "operation": "switch",
        "mode": _mode(leg_kind),
        "base_ref": base_ref,
        "target_ref": target_ref,
        "active_ref": active_ref,
        "expected_base_oid": "a" * 40,
        "expected_target_oid": "b" * 40,
        "observed_base_oid_before": "a" * 40,
        "observed_target_oid_before": "b" * 40,
        "observed_active_oid_before": "a" * 40,
        "observed_base_oid_after": "a" * 40,
        "observed_target_oid_after": "b" * 40,
        "observed_active_oid_after": "b" * 40,
        "status": status.value,
        "terminal": terminal,
        "progress": "COMPLETE" if terminal else "IN_PROGRESS",
        "effect": "APPLIED" if status is AggregateStatus.PASS else "NONE",
        "step_receipts": [],
        "blockers": [f"{leg_kind}-blocked"] if status is AggregateStatus.BLOCKED else [],
        "resume_route": f"resume-{leg_kind}",
        "abort_route": f"abort-{leg_kind}",
        "fresh_observed_at": "2026-07-18T13:00:00+00:00",
    }
    payload["payload_digest"] = canonical_json_digest(payload, omit_keys={"payload_digest"})
    return payload


def _handle(payload: dict[str, Any]) -> dict[str, Any]:
    correlation = copy.deepcopy(payload["correlation"])
    result_ref = f"process/evidence/legs/{correlation['leg_kind']}.json"
    single_write_key = derive_leg_single_write_key(correlation)
    receipt_fields = {
        "single_write_key": single_write_key,
        "result_ref": result_ref,
        "payload_digest": payload["payload_digest"],
        "writer_id": f"writer-{correlation['leg_kind']}",
        "written_at": "2026-07-18T13:01:00+00:00",
    }
    receipt = {key: value for key, value in receipt_fields.items() if key != "single_write_key"}
    receipt["receipt_digest"] = canonical_leg_receipt_digest(**receipt_fields)
    return {
        "schema_version": 1,
        "single_write_key": single_write_key,
        "result_ref": result_ref,
        "payload_digest": payload["payload_digest"],
        "receipt": receipt,
        "correlation": correlation,
        "mode": payload["mode"],
    }


def _request() -> AggregateRequest:
    return AggregateRequest(
        operation_id="operation-001",
        logical_attempt=1,
        cr_id="CR-051",
        project_id="meta-flow",
        required_legs=("source", "artifact"),
        expected_modes=(
            ("source", "source-default"),
            ("artifact", "shared-artifact-project-first"),
        ),
        policy_version="aggregate-v1",
    )


def _validated_pair(
    source_status: AggregateStatus,
    artifact_status: AggregateStatus,
) -> tuple[Any, MemoryLegReader]:
    source_payload = _payload("source", source_status)
    artifact_payload = _payload("artifact", artifact_status)
    handles = [_handle(source_payload), _handle(artifact_payload)]
    reader = MemoryLegReader(
        {
            handles[0]["result_ref"]: source_payload,
            handles[1]["result_ref"]: artifact_payload,
        }
    )
    outcome = validate_published_leg_results(_request(), handles, reader=reader)
    assert outcome.errors == ()
    assert outcome.validated is not None
    return outcome.validated, reader


@pytest.mark.parametrize(("source_status", "artifact_status"), list(product(STATUSES, repeat=2)))
def test_fixed_precedence_covers_all_16_status_combinations(
    source_status: AggregateStatus,
    artifact_status: AggregateStatus,
) -> None:
    validated, reader = _validated_pair(source_status, artifact_status)

    result = compute_aggregate(validated)

    expected = max((source_status, artifact_status), key=PRECEDENCE.__getitem__)
    assert result.overall is expected
    assert result.projection_decision is (
        ProjectionDecision.ELIGIBLE
        if source_status is AggregateStatus.PASS and artifact_status is AggregateStatus.PASS
        else ProjectionDecision.HOLD
    )
    assert reader.calls == [
        "process/evidence/legs/source.json",
        "process/evidence/legs/artifact.json",
    ]


def test_partial_effect_is_not_an_overall_status() -> None:
    validated, _reader = _validated_pair(AggregateStatus.PASS, AggregateStatus.FAIL)

    result = compute_aggregate(validated)

    assert result.overall is AggregateStatus.FAIL
    assert result.effect == "PARTIAL"
    assert result.projection_decision is ProjectionDecision.HOLD
    assert "PARTIAL" not in {status.value for status in AggregateStatus}


def test_aggregate_identity_and_digest_are_deterministic_and_have_no_self_reference() -> None:
    validated, _reader = _validated_pair(AggregateStatus.PASS, AggregateStatus.PASS)

    first = compute_aggregate(validated)
    second = compute_aggregate(validated)

    assert first.aggregate_id == second.aggregate_id
    assert first.payload_digest == second.payload_digest
    payload = first.to_dict()
    assert set(payload).isdisjoint(
        {"aggregate_ref", "write_receipt", "receipt", "receipt_digest", "writer_id", "written_at"}
    )
    assert payload["payload_digest"] == canonical_json_digest(payload, omit_keys={"payload_digest"})


def test_aggregate_digest_omits_only_its_own_digest_and_binds_nested_leg_digests() -> None:
    result = _result()
    payload = result.to_dict()
    payload["payload_digest"] = "caller-supplied-value-does-not-participate"

    assert canonical_json_digest(payload, omit_keys={"payload_digest"}) == result.payload_digest

    payload["published_handle_refs"]["source"]["payload_digest"] = "0" * 64
    assert canonical_json_digest(payload, omit_keys={"payload_digest"}) != result.payload_digest


def test_validator_rereads_result_ref_instead_of_trusting_embedded_payload() -> None:
    source_payload = _payload("source", AggregateStatus.FAIL)
    artifact_payload = _payload("artifact", AggregateStatus.PASS)
    handles = [_handle(source_payload), _handle(artifact_payload)]
    handles[0]["payload"] = _payload("source", AggregateStatus.PASS)
    reader = MemoryLegReader(
        {
            handles[0]["result_ref"]: source_payload,
            handles[1]["result_ref"]: artifact_payload,
        }
    )

    outcome = validate_published_leg_results(_request(), handles, reader=reader)

    assert outcome.validated is not None
    assert compute_aggregate(outcome.validated).overall is AggregateStatus.FAIL
    assert len(reader.calls) == 2


def test_target_policy_is_independently_revalidated_after_readback() -> None:
    source_payload = _payload("source", AggregateStatus.PASS)
    artifact_payload = _payload("artifact", AggregateStatus.PASS)
    artifact_payload["target_ref"] = "refs/heads/main"
    artifact_payload["payload_digest"] = canonical_json_digest(
        artifact_payload, omit_keys={"payload_digest"}
    )
    handles = [_handle(source_payload), _handle(artifact_payload)]
    reader = MemoryLegReader(
        {
            handles[0]["result_ref"]: source_payload,
            handles[1]["result_ref"]: artifact_payload,
        }
    )

    outcome = validate_published_leg_results(_request(), handles, reader=reader)

    assert outcome.validated is None
    assert {error.code.value for error in outcome.errors} >= {"target-policy-mismatch"}


@pytest.mark.parametrize(
    "case",
    (
        "raw-payload",
        "missing-leg",
        "duplicate-leg",
        "wrong-attempt",
        "wrong-project",
        "wrong-mode",
        "wrong-result-ref",
        "wrong-payload-digest",
        "wrong-single-write-key",
        "wrong-receipt-digest",
        "wrong-handle-correlation",
        "wrong-handle-schema",
        "wrong-payload-schema",
        "reader-failure",
    ),
)
def test_invalid_or_unpublished_handles_are_rejected_before_aggregate(case: str) -> None:
    source_payload = _payload("source", AggregateStatus.PASS)
    artifact_payload = _payload("artifact", AggregateStatus.PASS)
    handles: list[dict[str, Any]] = [_handle(source_payload), _handle(artifact_payload)]
    payloads = {
        handles[0]["result_ref"]: source_payload,
        handles[1]["result_ref"]: artifact_payload,
    }

    if case == "raw-payload":
        handles[0] = copy.deepcopy(source_payload)
    elif case == "missing-leg":
        handles.pop()
    elif case == "duplicate-leg":
        handles[1] = copy.deepcopy(handles[0])
    elif case == "wrong-attempt":
        payloads[handles[0]["result_ref"]]["correlation"]["logical_attempt"] = 2
        payloads[handles[0]["result_ref"]]["payload_digest"] = canonical_json_digest(
            payloads[handles[0]["result_ref"]], omit_keys={"payload_digest"}
        )
    elif case == "wrong-project":
        payloads[handles[0]["result_ref"]]["correlation"]["project_id"] = "other"
        payloads[handles[0]["result_ref"]]["payload_digest"] = canonical_json_digest(
            payloads[handles[0]["result_ref"]], omit_keys={"payload_digest"}
        )
    elif case == "wrong-mode":
        handles[0]["mode"] = "artifact-integration"
    elif case == "wrong-result-ref":
        handles[0]["receipt"]["result_ref"] = handles[1]["result_ref"]
    elif case == "wrong-payload-digest":
        handles[0]["payload_digest"] = "0" * 64
    elif case == "wrong-single-write-key":
        handles[0]["single_write_key"] = "0" * 64
    elif case == "wrong-receipt-digest":
        handles[0]["receipt"]["receipt_digest"] = "0" * 64
    elif case == "wrong-handle-correlation":
        handles[0]["correlation"]["cr_id"] = "CR-999"
    elif case == "wrong-handle-schema":
        handles[0]["schema_version"] = 999
    elif case == "wrong-payload-schema":
        payloads[handles[0]["result_ref"]]["schema_version"] = 999
        payloads[handles[0]["result_ref"]]["payload_digest"] = canonical_json_digest(
            payloads[handles[0]["result_ref"]], omit_keys={"payload_digest"}
        )
    elif case == "reader-failure":
        payloads.pop(handles[0]["result_ref"])

    reader = MemoryLegReader(payloads)
    outcome = validate_published_leg_results(_request(), handles, reader=reader)

    assert outcome.validated is None
    assert outcome.errors


class RecordingProjector:
    def __init__(self, *, fail: bool = False, status: str = "complete") -> None:
        self.fail = fail
        self.status = status
        self.calls: list[tuple[Any, Any]] = []

    def project_aggregate(self, *, result: Any, receipt: Any) -> dict[str, Any]:
        self.calls.append((result, receipt))
        if self.fail:
            raise RuntimeError("projection failed")
        return {
            "status": self.status,
            "writer_receipts": {
                "cr": "cr-receipt",
                "state_current": "state-receipt",
            },
        }


def _result(
    source_status: AggregateStatus = AggregateStatus.PASS,
    artifact_status: AggregateStatus = AggregateStatus.PASS,
) -> Any:
    validated, _reader = _validated_pair(source_status, artifact_status)
    return compute_aggregate(validated)


def _redigest(result: Any, **changes: Any) -> Any:
    changed = replace(result, **changes, payload_digest="")
    return replace(
        changed,
        payload_digest=canonical_json_digest(changed.to_dict(), omit_keys={"payload_digest"}),
    )


def test_persist_same_input_is_idempotent_and_readback_valid() -> None:
    result = _result()
    store = InMemoryAggregateStore(writer_id="test-writer")

    first = persist_aggregate(result, store, expected_current_ref=None)
    second = persist_aggregate(result, store, expected_current_ref=None)

    assert first.disposition is PersistDisposition.WRITTEN
    assert second.disposition is PersistDisposition.IDEMPOTENT
    assert first.aggregate_ref == second.aggregate_ref
    assert first.readback_valid is second.readback_valid is True
    assert first.current_selected is second.current_selected is True
    assert store.result_count == 1
    assert store.current_ref(result) == first.aggregate_ref


def test_same_aggregate_id_with_conflicting_payload_is_blocked_without_overwrite() -> None:
    result = _result()
    conflicting = _redigest(result, effect="TAMPERED")
    store = InMemoryAggregateStore(writer_id="test-writer")
    first = persist_aggregate(result, store, expected_current_ref=None)

    conflict = persist_aggregate(conflicting, store, expected_current_ref=first.aggregate_ref)

    assert conflict.disposition is PersistDisposition.CONFLICT
    assert conflict.current_selected is False
    assert store.read_result(first.aggregate_ref) == result.to_dict()
    assert store.result_count == 1


def test_current_selector_cas_conflict_never_uses_last_write_wins() -> None:
    first_result = _result()
    second_result = _redigest(first_result, input_digest="f" * 64, aggregate_id="e" * 64)
    store = InMemoryAggregateStore(writer_id="test-writer")
    first = persist_aggregate(first_result, store, expected_current_ref=None)

    conflict = persist_aggregate(second_result, store, expected_current_ref=None)

    assert first.current_selected is True
    assert conflict.disposition is PersistDisposition.CONFLICT
    assert conflict.current_selected is False
    assert store.current_ref(first_result) == first.aggregate_ref
    assert store.result_count == 2


def test_file_store_writes_immutable_result_and_explicit_selector(tmp_path: Path) -> None:
    result = _result()
    store = FileAggregateStore(project_root=tmp_path, writer_id="file-writer")

    receipt = persist_aggregate(result, store, expected_current_ref=None)

    assert receipt.disposition is PersistDisposition.WRITTEN
    assert receipt.readback_valid is True
    assert receipt.current_selected is True
    assert store.read_result(receipt.aggregate_ref) == result.to_dict()
    result_path = tmp_path / receipt.aggregate_ref
    assert result_path.is_file()
    assert json.loads(result_path.read_text(encoding="utf-8")) == result.to_dict()


def test_concurrent_same_payload_is_single_node_and_idempotent(tmp_path: Path) -> None:
    result = _result()
    store = FileAggregateStore(project_root=tmp_path, writer_id="file-writer")

    with ThreadPoolExecutor(max_workers=2) as executor:
        receipts = list(
            executor.map(
                lambda _index: persist_aggregate(result, store, expected_current_ref=None),
                range(2),
            )
        )

    dispositions = {receipt.disposition for receipt in receipts}
    assert dispositions <= {PersistDisposition.WRITTEN, PersistDisposition.IDEMPOTENT}
    assert PersistDisposition.IDEMPOTENT in dispositions
    assert all(receipt.readback_valid and receipt.current_selected for receipt in receipts)
    assert len({receipt.aggregate_ref for receipt in receipts}) == 1


def test_concurrent_conflicting_payloads_fail_closed_without_last_write_wins(
    tmp_path: Path,
) -> None:
    first_result = _result()
    second_result = _redigest(first_result, input_digest="b" * 64, aggregate_id="c" * 64)
    store = FileAggregateStore(project_root=tmp_path, writer_id="file-writer")

    with ThreadPoolExecutor(max_workers=2) as executor:
        receipts = list(
            executor.map(
                lambda result: persist_aggregate(result, store, expected_current_ref=None),
                (first_result, second_result),
            )
        )

    assert sum(receipt.current_selected for receipt in receipts) == 1
    assert sum(receipt.disposition is PersistDisposition.CONFLICT for receipt in receipts) == 1
    assert store.current_ref(first_result) in {receipt.aggregate_ref for receipt in receipts}


def test_projection_requires_persisted_readback_current_2_of_2_pass() -> None:
    result = _result()
    store = InMemoryAggregateStore(writer_id="test-writer")
    receipt = persist_aggregate(result, store, expected_current_ref=None)
    projector = RecordingProjector()

    projection = project_if_eligible(result, receipt, store=store, projector=projector)

    assert projection.status is ProjectionStatus.COMPLETE
    assert projection.called is True
    assert len(projector.calls) == 1


@pytest.mark.parametrize(
    ("source_status", "artifact_status"),
    [
        pair
        for pair in product(STATUSES, repeat=2)
        if pair != (AggregateStatus.PASS, AggregateStatus.PASS)
    ],
)
def test_non_pass_results_persist_but_never_call_projection(
    source_status: AggregateStatus,
    artifact_status: AggregateStatus,
) -> None:
    result = _result(source_status, artifact_status)
    store = InMemoryAggregateStore(writer_id="test-writer")
    receipt = persist_aggregate(result, store, expected_current_ref=None)
    projector = RecordingProjector()

    projection = project_if_eligible(result, receipt, store=store, projector=projector)

    assert projection.status is ProjectionStatus.HOLD
    assert projection.called is False
    assert projector.calls == []


def test_stale_persisted_pass_is_held_before_projector_call() -> None:
    result = _result()
    successor = _redigest(result, input_digest="c" * 64, aggregate_id="d" * 64)
    store = InMemoryAggregateStore(writer_id="test-writer")
    first = persist_aggregate(result, store, expected_current_ref=None)
    second = persist_aggregate(successor, store, expected_current_ref=first.aggregate_ref)
    projector = RecordingProjector()

    projection = project_if_eligible(result, first, store=store, projector=projector)

    assert second.current_selected is True
    assert projection.status is ProjectionStatus.HOLD
    assert projection.called is False
    assert projector.calls == []


def test_projection_failure_preserves_aggregate_and_exposes_retryable_failure() -> None:
    result = _result()
    store = InMemoryAggregateStore(writer_id="test-writer")
    receipt = persist_aggregate(result, store, expected_current_ref=None)
    projector = RecordingProjector(fail=True)

    projection = project_if_eligible(result, receipt, store=store, projector=projector)

    assert projection.status is ProjectionStatus.FAILED
    assert projection.called is True
    assert projection.retryable is True
    assert store.read_result(receipt.aggregate_ref) == result.to_dict()
    assert len(projector.calls) == 1


def test_partial_projection_is_preserved_and_routes_to_retry() -> None:
    source_payload = _payload("source", AggregateStatus.PASS)
    artifact_payload = _payload("artifact", AggregateStatus.PASS)
    handles = [_handle(source_payload), _handle(artifact_payload)]
    reader = MemoryLegReader(
        {
            handles[0]["result_ref"]: source_payload,
            handles[1]["result_ref"]: artifact_payload,
        }
    )
    store = InMemoryAggregateStore(writer_id="test-writer")
    projector = RecordingProjector(status="partial")

    command = coordinate_aggregate(
        _request(),
        handles,
        reader=reader,
        store=store,
        projector=projector,
        project=True,
    )

    assert command.projection_receipt is not None
    assert command.projection_receipt.status is ProjectionStatus.PARTIAL
    assert command.projection_receipt.retryable is True
    assert command.next_route == "retry-controlled-projection"


def test_dependency_boundary_and_exact_evidence_dag_order() -> None:
    module_source = inspect.getsource(aggregate_module)
    for forbidden_import in (
        "import subprocess",
        "workspace.git_sync",
        "project_worktree",
        "manual_sync",
    ):
        assert forbidden_import not in module_source

    operations: list[str] = []

    class OrderedStore(InMemoryAggregateStore):
        def append_result(self, result):
            operations.append("aggregate-append")
            return super().append_result(result)

        def read_result(self, aggregate_ref):
            operations.append("aggregate-readback")
            return super().read_result(aggregate_ref)

        def compare_and_set_current(self, result, *, expected_current_ref, aggregate_ref):
            operations.append("aggregate-current-cas")
            return super().compare_and_set_current(
                result,
                expected_current_ref=expected_current_ref,
                aggregate_ref=aggregate_ref,
            )

        def current_ref(self, result):
            operations.append("aggregate-current-read")
            return super().current_ref(result)

    class OrderedProjector(RecordingProjector):
        def project_aggregate(self, *, result, receipt):
            operations.append("controlled-projection")
            return super().project_aggregate(result=result, receipt=receipt)

    result = _result()
    store = OrderedStore(writer_id="ordered-writer")
    receipt = persist_aggregate(result, store, expected_current_ref=None)
    projection = project_if_eligible(
        result,
        receipt,
        store=store,
        projector=OrderedProjector(),
    )

    assert projection.status is ProjectionStatus.COMPLETE
    assert operations == [
        "aggregate-append",
        "aggregate-readback",
        "aggregate-current-cas",
        "aggregate-readback",
        "aggregate-current-read",
        "controlled-projection",
    ]


def test_invalid_coordinate_path_calls_neither_store_nor_projector() -> None:
    source_payload = _payload("source", AggregateStatus.PASS)
    artifact_payload = _payload("artifact", AggregateStatus.PASS)
    handles = [_handle(source_payload), _handle(artifact_payload)]
    handles[0]["receipt"]["receipt_digest"] = "0" * 64
    reader = MemoryLegReader(
        {
            handles[0]["result_ref"]: source_payload,
            handles[1]["result_ref"]: artifact_payload,
        }
    )
    store = InMemoryAggregateStore(writer_id="test-writer")
    projector = RecordingProjector()

    command = coordinate_aggregate(
        _request(),
        handles,
        reader=reader,
        store=store,
        projector=projector,
        project=True,
    )

    assert command.overall is AggregateStatus.BLOCKED
    assert command.aggregate_result is None
    assert command.write_receipt is None
    assert command.projection_receipt is None
    assert store.result_count == 0
    assert projector.calls == []


def test_dry_run_computes_decision_without_persist_or_projection() -> None:
    source_payload = _payload("source", AggregateStatus.PASS)
    artifact_payload = _payload("artifact", AggregateStatus.PASS)
    handles = [_handle(source_payload), _handle(artifact_payload)]
    reader = MemoryLegReader(
        {
            handles[0]["result_ref"]: source_payload,
            handles[1]["result_ref"]: artifact_payload,
        }
    )
    store = InMemoryAggregateStore(writer_id="test-writer")
    projector = RecordingProjector()

    command = coordinate_aggregate(
        _request(),
        handles,
        reader=reader,
        store=store,
        projector=projector,
        dry_run=True,
        project=True,
    )

    assert command.overall is AggregateStatus.PASS
    assert command.aggregate_result is not None
    assert command.write_receipt is None
    assert command.projection_receipt is None
    assert store.result_count == 0
    assert projector.calls == []


def _initialize_active_current_state(project_root: Path) -> dict[str, Any]:
    current_state.init_current_state(project_root, project_id="meta-flow")
    return current_state.update_current_state(
        project_root,
        {
            "active_change": "CR-051",
            "active_story": "ST-AW-004",
            "current_phase": "story-execution",
            "next_action": {
                "type": "aggregate_running",
                "text": "Run the validated aggregate evidence gate.",
            },
            "updated_at": "2026-07-18T13:30:00+00:00",
        },
        actor="test",
        reason="aggregate projection fixture",
    )


def test_controlled_projection_records_candidate_without_close_or_delivered_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = _initialize_active_current_state(tmp_path)
    result = _result()
    store = FileAggregateStore(project_root=tmp_path, writer_id="file-writer")
    receipt = persist_aggregate(result, store, expected_current_ref=None)

    def forbidden_call(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("projection must not close or status-sync the CR")

    monkeypatch.setattr(cr_lifecycle, "close_cr", forbidden_call)
    monkeypatch.setattr(cr_lifecycle, "sync_cr_status", forbidden_call)
    projector = cr_lifecycle.AggregateCompletionProjector(
        project_root=tmp_path,
        expected_state_updated_at=before["updated_at"],
    )

    projection = project_if_eligible(result, receipt, store=store, projector=projector)

    assert projection.status is ProjectionStatus.COMPLETE
    after = current_state.load_current_state(tmp_path)
    assert after["active_change"] == "CR-051"
    assert after["active_story"] == "ST-AW-004"
    assert after["current_phase"] == "story-execution"
    assert after["next_action"]["type"] == "aggregate_pass_persisted"
    assert receipt.aggregate_ref in after["source_refs"]
    ledger_path = tmp_path / "process/state/CR-LEDGER.ndjson"
    events = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()]
    assert [event["event"] for event in events] == ["aggregate_projection"]
    assert all(event.get("status") != "closed" for event in events)


def test_controlled_projection_returns_partial_after_state_write_and_retries_idempotently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = _initialize_active_current_state(tmp_path)
    result = _result()
    store = FileAggregateStore(project_root=tmp_path, writer_id="file-writer")
    receipt = persist_aggregate(result, store, expected_current_ref=None)
    original_append = cr_lifecycle.append_ledger_event

    def fail_ledger(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("fixture ledger unavailable")

    monkeypatch.setattr(cr_lifecycle, "append_ledger_event", fail_ledger)
    projector = cr_lifecycle.AggregateCompletionProjector(
        project_root=tmp_path,
        expected_state_updated_at=before["updated_at"],
    )

    partial = project_if_eligible(result, receipt, store=store, projector=projector)

    assert partial.status is ProjectionStatus.PARTIAL
    assert partial.retryable is True
    assert "state_current" in partial.writer_receipts
    assert "cr_ledger" not in partial.writer_receipts
    after_partial = current_state.load_current_state(tmp_path)
    assert receipt.aggregate_ref in after_partial["source_refs"]
    assert not (tmp_path / "process/state/CR-LEDGER.ndjson").read_text(encoding="utf-8").strip()

    monkeypatch.setattr(cr_lifecycle, "append_ledger_event", original_append)
    completed = project_if_eligible(result, receipt, store=store, projector=projector)

    assert completed.status is ProjectionStatus.COMPLETE
    assert completed.writer_receipts["state_current"]["status"] == "idempotent-existing"
    assert completed.writer_receipts["cr_ledger"]["status"] == "projected"


def _write_cli_fixture(project_root: Path) -> tuple[Path, Path]:
    source_payload = _payload("source", AggregateStatus.PASS)
    artifact_payload = _payload("artifact", AggregateStatus.PASS)
    source_handle = _handle(source_payload)
    artifact_handle = _handle(artifact_payload)
    for handle, payload in ((source_handle, source_payload), (artifact_handle, artifact_payload)):
        payload_path = project_root / handle["result_ref"]
        payload_path.parent.mkdir(parents=True, exist_ok=True)
        payload_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    source_path = project_root / "source-handle.json"
    artifact_path = project_root / "artifact-handle.json"
    source_path.write_text(json.dumps(source_handle), encoding="utf-8")
    artifact_path.write_text(json.dumps(artifact_handle), encoding="utf-8")
    return source_path, artifact_path


def test_cr_aggregate_cli_dry_run_outputs_refs_without_writes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_handle, artifact_handle = _write_cli_fixture(tmp_path)

    status = cr_lifecycle.main(
        [
            "aggregate",
            "--project-root",
            str(tmp_path),
            "--id",
            "CR-051",
            "--project-id",
            "meta-flow",
            "--operation-id",
            "operation-001",
            "--attempt",
            "1",
            "--source-handle",
            str(source_handle),
            "--artifact-handle",
            str(artifact_handle),
            "--dry-run",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert status == 0
    assert output["overall"] == "PASS"
    assert output["dry_run"] is True
    assert output["write_receipt"] is None
    assert output["projection_receipt"] is None
    assert not (tmp_path / "process/evidence/aggregates").exists()
