from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest

from meta_flow.contracts.typed_ref import parse_typed_ref_v2
from meta_flow.migration import (
    AtomicFileObservationPersistence,
    ComparisonBasisV1,
    FullValidationObservationSnapshotV1,
    ObservationError,
    ObservationStore,
    RetirementAdmissionV1,
    StabilizationEpochV1,
    activate_comparison_basis,
    assess_retirement,
    build_full_snapshot,
    compare_snapshots,
    observe_compatibility_decision,
    record_validation_scan,
    start_stabilization_epoch,
)
from meta_flow.migration.observation_storage import canonical_bytes

NOW = datetime(2026, 8, 16, tzinfo=UTC)


def _digest(value: str) -> str:
    return sha256(value.encode()).hexdigest()


IMPL = _digest("implementation")
PROFILE = _digest("profile")
COMMAND = _digest("command")


def _setup(tmp_path):
    store = ObservationStore(AtomicFileObservationPersistence(tmp_path / "observations.json"))
    basis = activate_comparison_basis(
        store,
        observer_implementation_digest=IMPL,
        typed_ref_schema_digest=_digest("typed-ref-schema"),
        policy_schema_digest=_digest("policy-schema"),
        raw_observation_schema_digest=_digest("raw-schema"),
        aggregator_schema_digest=_digest("aggregator-schema"),
        validation_profile_digest=PROFILE,
        command_identity_digest=COMMAND,
        scope_digest=_digest("scope"),
        query_digest=_digest("query"),
        activated_at=NOW,
    )
    epoch = start_stabilization_epoch(
        store,
        implementation_digest=IMPL,
        profile_digest=PROFILE,
        command_digest=COMMAND,
        started_at=NOW,
    )
    return store, basis, epoch


def _scan_bytes(
    *,
    writer_versions: list[int] | None = None,
    residual: list[str] | None = None,
    ambiguity: list[bool] | None = None,
    release_oid: str = "a" * 40,
) -> bytes:
    return canonical_bytes(
        {
            "schema_version": 1,
            "writer_schema_versions": writer_versions or [2],
            "declared_scope_input_classes": residual or ["v2"],
            "ambiguity_outcomes": ambiguity or [],
            "release_oid": release_oid,
            "process_oid": "b" * 40,
        }
    )


def _record(store: ObservationStore, *, offset: int, scan_bytes: bytes | None = None) -> str:
    return record_validation_scan(
        store,
        scan_bytes=scan_bytes or _scan_bytes(),
        implementation_digest=IMPL,
        profile_digest=PROFILE,
        command_digest=COMMAND,
        observed_at=NOW + timedelta(minutes=offset),
    )


def test_two_stored_zero_snapshots_are_only_eligible_to_propose(tmp_path) -> None:
    store, basis, epoch = _setup(tmp_path)
    first = _record(store, offset=1, scan_bytes=_scan_bytes(release_oid="a" * 40))
    second = _record(store, offset=2, scan_bytes=_scan_bytes(release_oid="c" * 40))
    comparison = compare_snapshots(
        store, previous_scan_id=first, current_scan_id=second
    )
    assert basis.basis_digest == comparison.current.basis_digest
    assert epoch.epoch_id == comparison.current.epoch_id
    assert comparison.comparable
    assert (
        assess_retirement(store, previous_scan_id=first, current_scan_id=second)
        is RetirementAdmissionV1.ELIGIBLE_TO_PROPOSE
    )
    assert "retired" not in {item.value for item in RetirementAdmissionV1}


def test_fake_counts_are_not_part_of_scan_schema(tmp_path) -> None:
    store, _, _ = _setup(tmp_path)
    forged = canonical_bytes(
        {
            "schema_version": 1,
            "writer_schema_versions": [1],
            "declared_scope_input_classes": ["v1-deterministic"],
            "ambiguity_outcomes": [],
            "release_oid": "a" * 40,
            "process_oid": "b" * 40,
            "writer_v1_count": 0,
            "v1_input_observed": 0,
        }
    )
    with pytest.raises(ObservationError, match="VALIDATION_SCAN_SCHEMA_INVALID"):
        _record(store, offset=1, scan_bytes=forged)


def test_stored_v1_observation_makes_current_snapshot_ineligible(tmp_path) -> None:
    store, _, _ = _setup(tmp_path)
    first = _record(store, offset=1)
    result = parse_typed_ref_v2(
        {
            "schema_version": 1,
            "repository_role": "release",
            "object_kind": "story",
            "logical_ref": "stories/S01.md",
        },
        resolver_identity=_digest("resolver"),
    )
    observe_compatibility_decision(
        result=result,
        store=store,
        run_identity_digest=_digest("run"),
        profile_digest=PROFILE,
        command_identity_digest=COMMAND,
        observed_at=NOW + timedelta(minutes=2),
    )
    second = _record(store, offset=3)
    snapshot = build_full_snapshot(store, scan_id=second)
    assert snapshot.v1_input_observed == 1
    assert (
        assess_retirement(store, previous_scan_id=first, current_scan_id=second)
        is RetirementAdmissionV1.INELIGIBLE
    )


def test_epoch_identity_drift_is_recorded_and_breaks_continuity(tmp_path) -> None:
    store, _, _ = _setup(tmp_path)
    with pytest.raises(ObservationError, match="EPOCH_DRIFT"):
        record_validation_scan(
            store,
            scan_bytes=_scan_bytes(),
            implementation_digest=_digest("drifted"),
            profile_digest=PROFILE,
            command_digest=COMMAND,
            observed_at=NOW + timedelta(minutes=1),
        )
    assert store.read_verified_events()[-1].event_type == "epoch_reset"
    with pytest.raises(ObservationError, match="NO_ACTIVE_EPOCH"):
        _record(store, offset=2)


def test_nonconsecutive_snapshots_and_direct_construction_fail_closed(tmp_path) -> None:
    store, _, _ = _setup(tmp_path)
    first = _record(store, offset=1)
    _record(store, offset=2)
    third = _record(store, offset=3)
    assert not compare_snapshots(
        store, previous_scan_id=first, current_scan_id=third
    ).comparable
    with pytest.raises(TypeError):
        ComparisonBasisV1("forged")
    with pytest.raises(TypeError):
        StabilizationEpochV1("forged")
    with pytest.raises(TypeError):
        FullValidationObservationSnapshotV1("forged")
