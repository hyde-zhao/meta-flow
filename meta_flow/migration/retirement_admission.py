"""Stored-event-derived comparison epochs, snapshots, and proposal admission."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from .compatibility_observation import ALLOWED_INPUT_CLASSES, ObservationError
from .observation_storage import (
    PROJECT_CAPACITY,
    ObservationStore,
    StoredObservationEventV1,
    canonical_bytes,
    digest_bytes,
    digest_object,
    rebuild_rollup,
)

_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_OID_RE = re.compile(r"^[0-9a-f]{40,64}$")
_BASIS_FIELDS = (
    "observer_implementation_digest",
    "typed_ref_schema_digest",
    "policy_schema_digest",
    "raw_observation_schema_digest",
    "aggregator_schema_digest",
    "validation_profile_digest",
    "command_identity_digest",
    "scope_digest",
    "query_digest",
)
_SCAN_INPUT_FIELDS = {
    "schema_version",
    "writer_schema_versions",
    "declared_scope_input_classes",
    "ambiguity_outcomes",
    "release_oid",
    "process_oid",
}


class RetirementAdmissionV1(StrEnum):
    INELIGIBLE = "ineligible"
    ELIGIBLE_TO_PROPOSE = "eligible-to-propose"


@dataclass(frozen=True, init=False)
class ComparisonBasisV1:
    basis_id: str
    basis_digest: str
    activated_sequence: int
    invariants: tuple[tuple[str, str], ...]

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("ComparisonBasisV1 must be derived from stored events")

    @classmethod
    def _derived(
        cls,
        basis_id: str,
        basis_digest: str,
        activated_sequence: int,
        invariants: tuple[tuple[str, str], ...],
    ) -> ComparisonBasisV1:
        instance = object.__new__(cls)
        for name, value in (
            ("basis_id", basis_id),
            ("basis_digest", basis_digest),
            ("activated_sequence", activated_sequence),
            ("invariants", invariants),
        ):
            object.__setattr__(instance, name, value)
        return instance


@dataclass(frozen=True, init=False)
class StabilizationEpochV1:
    epoch_id: str
    basis_digest: str
    implementation_digest: str
    profile_digest: str
    command_digest: str
    started_sequence: int
    status: str

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("StabilizationEpochV1 must be derived from stored events")

    @classmethod
    def _derived(cls, payload: dict[str, object], sequence: int) -> StabilizationEpochV1:
        _validate_epoch_payload(payload)
        expected_epoch_id = digest_object(
            {
                "basis_digest": payload["basis_digest"],
                "implementation_digest": payload["implementation_digest"],
                "profile_digest": payload["profile_digest"],
                "command_digest": payload["command_digest"],
                "sequence": sequence,
            }
        )
        if payload["epoch_id"] != expected_epoch_id:
            raise ObservationError("EPOCH_DIGEST_MISMATCH")
        instance = object.__new__(cls)
        values = {
            "epoch_id": payload["epoch_id"],
            "basis_digest": payload["basis_digest"],
            "implementation_digest": payload["implementation_digest"],
            "profile_digest": payload["profile_digest"],
            "command_digest": payload["command_digest"],
            "started_sequence": sequence,
            "status": "active",
        }
        for name, value in values.items():
            object.__setattr__(instance, name, value)
        return instance


@dataclass(frozen=True, init=False)
class FullValidationObservationSnapshotV1:
    snapshot_id: str
    scan_id: str
    scan_sequence: int
    basis_digest: str
    epoch_id: str
    raw_range_digest: str
    rollup_digest: str
    source_scan_digest: str
    writer_v1_count: int
    declared_scope_v1_residual: int
    ambiguity_detected: int
    ambiguity_total: int
    v1_input_observed: int
    raw_valid: bool
    replay_valid: bool
    privacy_valid: bool
    capacity_valid: bool
    release_oid: str
    process_oid: str

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError(
            "FullValidationObservationSnapshotV1 must be derived from stored events"
        )

    @classmethod
    def _derived(cls, values: dict[str, object]) -> FullValidationObservationSnapshotV1:
        instance = object.__new__(cls)
        for name, value in values.items():
            object.__setattr__(instance, name, value)
        return instance

    @property
    def gates_pass(self) -> bool:
        return (
            self.raw_valid
            and self.replay_valid
            and self.privacy_valid
            and self.capacity_valid
            and self.writer_v1_count == 0
            and self.declared_scope_v1_residual == 0
            and self.ambiguity_detected == self.ambiguity_total
            and self.v1_input_observed == 0
        )


@dataclass(frozen=True)
class SnapshotComparisonV1:
    comparable: bool
    reason: str
    previous: FullValidationObservationSnapshotV1
    current: FullValidationObservationSnapshotV1


def _require_digest(value: object, field: str) -> str:
    if not isinstance(value, str) or _HEX_RE.fullmatch(value) is None:
        raise ObservationError(f"INVALID_{field.upper()}")
    return value


def _timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ObservationError("INVALID_OBSERVED_AT")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def activate_comparison_basis(
    store: ObservationStore,
    *,
    observer_implementation_digest: str,
    typed_ref_schema_digest: str,
    policy_schema_digest: str,
    raw_observation_schema_digest: str,
    aggregator_schema_digest: str,
    validation_profile_digest: str,
    command_identity_digest: str,
    scope_digest: str,
    query_digest: str,
    activated_at: datetime,
) -> ComparisonBasisV1:
    invariants = {
        name: _require_digest(value, name)
        for name, value in locals().items()
        if name in _BASIS_FIELDS
    }
    basis_digest = digest_object({"schema_version": 1, **invariants})
    events = store.read_verified_events()
    payload: dict[str, object] = {
        "basis_id": digest_object(
            {"basis_digest": basis_digest, "sequence": len(events) + 1}
        ),
        "basis_digest": basis_digest,
        "invariants": invariants,
        "activated_at": _timestamp(activated_at),
    }
    event, _, _ = store._append_event("basis_activated", payload, events=events)
    return _basis_from_event(event)


def start_stabilization_epoch(
    store: ObservationStore,
    *,
    implementation_digest: str,
    profile_digest: str,
    command_digest: str,
    started_at: datetime,
) -> StabilizationEpochV1:
    events = store.read_verified_events()
    basis = _latest_basis(events)
    if basis is None:
        raise ObservationError("MISSING_COMPARISON_BASIS")
    identities = {
        "implementation_digest": _require_digest(
            implementation_digest, "implementation_digest"
        ),
        "profile_digest": _require_digest(profile_digest, "profile_digest"),
        "command_digest": _require_digest(command_digest, "command_digest"),
    }
    invariant_map = dict(basis.invariants)
    if (
        identities["implementation_digest"]
        != invariant_map["observer_implementation_digest"]
        or identities["profile_digest"]
        != invariant_map["validation_profile_digest"]
        or identities["command_digest"] != invariant_map["command_identity_digest"]
    ):
        raise ObservationError("EPOCH_IDENTITY_MISMATCH")
    active = _active_epoch(events)
    if active is not None:
        store._append_event(
            "epoch_reset",
            {
                "epoch_id": active.epoch_id,
                "reason": "NEW_EPOCH",
                "reset_at": _timestamp(started_at),
            },
            events=events,
        )
        events = store.read_verified_events()
    payload: dict[str, object] = {
        "epoch_id": digest_object(
            {
                "basis_digest": basis.basis_digest,
                **identities,
                "sequence": len(events) + 1,
            }
        ),
        "basis_digest": basis.basis_digest,
        **identities,
        "started_at": _timestamp(started_at),
    }
    event, _, _ = store._append_event("epoch_started", payload, events=events)
    return StabilizationEpochV1._derived(dict(event.payload), event.sequence)


def record_validation_scan(
    store: ObservationStore,
    *,
    scan_bytes: bytes,
    implementation_digest: str,
    profile_digest: str,
    command_digest: str,
    observed_at: datetime,
) -> str:
    """Persist safe scan observations; no caller-supplied aggregate counts exist."""

    try:
        parsed = json.loads(scan_bytes.decode("utf-8"))
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ObservationError("VALIDATION_SCAN_INVALID") from error
    if canonical_bytes(parsed) != scan_bytes or not isinstance(parsed, dict):
        raise ObservationError("VALIDATION_SCAN_NONCANONICAL")
    _validate_scan_input(parsed)
    events = store.read_verified_events()
    basis = _latest_basis(events)
    epoch = _active_epoch(events)
    if basis is None or epoch is None:
        raise ObservationError("NO_ACTIVE_EPOCH")
    identities = (
        _require_digest(implementation_digest, "implementation_digest"),
        _require_digest(profile_digest, "profile_digest"),
        _require_digest(command_digest, "command_digest"),
    )
    if identities != (
        epoch.implementation_digest,
        epoch.profile_digest,
        epoch.command_digest,
    ) or basis.basis_digest != epoch.basis_digest:
        store._append_event(
            "epoch_reset",
            {
                "epoch_id": epoch.epoch_id,
                "reason": "IDENTITY_DRIFT",
                "reset_at": _timestamp(observed_at),
            },
            events=events,
        )
        raise ObservationError("EPOCH_DRIFT")
    scan_digest = digest_bytes(scan_bytes)
    scan_id = digest_object(
        {"scan_digest": scan_digest, "epoch_id": epoch.epoch_id, "sequence": len(events) + 1}
    )
    payload: dict[str, object] = {
        "scan_id": scan_id,
        "scan_digest": scan_digest,
        "basis_digest": basis.basis_digest,
        "epoch_id": epoch.epoch_id,
        "implementation_digest": identities[0],
        "profile_digest": identities[1],
        "command_digest": identities[2],
        "observed_at": _timestamp(observed_at),
        **parsed,
    }
    store._append_event("validation_scan", payload, events=events)
    return scan_id


def build_full_snapshot(
    store: ObservationStore, *, scan_id: str
) -> FullValidationObservationSnapshotV1:
    events = store.read_verified_events()
    scan = next(
        (
            event
            for event in events
            if event.event_type == "validation_scan"
            and event.payload.get("scan_id") == scan_id
        ),
        None,
    )
    if scan is None:
        raise ObservationError("VALIDATION_SCAN_NOT_FOUND")
    payload = dict(scan.payload)
    _validate_stored_scan(payload)
    expected_scan_id = digest_object(
        {
            "scan_digest": payload["scan_digest"],
            "epoch_id": payload["epoch_id"],
            "sequence": scan.sequence,
        }
    )
    if payload["scan_id"] != expected_scan_id:
        raise ObservationError("VALIDATION_SCAN_DIGEST_MISMATCH")
    basis = _latest_basis(events, through_sequence=scan.sequence)
    epoch = _active_epoch(events, through_sequence=scan.sequence)
    if (
        basis is None
        or epoch is None
        or basis.basis_digest != payload["basis_digest"]
        or epoch.epoch_id != payload["epoch_id"]
    ):
        raise ObservationError("SNAPSHOT_EPOCH_INVALID")
    prior_scans = [
        event
        for event in events
        if event.event_type == "validation_scan"
        and event.sequence < scan.sequence
        and event.payload.get("epoch_id") == epoch.epoch_id
    ]
    interval_start = prior_scans[-1].sequence if prior_scans else epoch.started_sequence
    observations = [
        event
        for event in events
        if event.event_type == "compatibility_observation"
        and interval_start < event.sequence <= scan.sequence
    ]
    raw_range_digest = digest_object(tuple(event.event_digest for event in observations))
    rollup = rebuild_rollup(store, through_sequence=scan.sequence)
    prefix_bytes = canonical_bytes(
        {
            "schema_version": 1,
            "events": [event.as_dict() for event in events if event.sequence <= scan.sequence],
        }
    )
    writer_versions = payload["writer_schema_versions"]
    residual_classes = payload["declared_scope_input_classes"]
    ambiguity = payload["ambiguity_outcomes"]
    values: dict[str, object] = {
        "scan_id": scan_id,
        "scan_sequence": scan.sequence,
        "basis_digest": basis.basis_digest,
        "epoch_id": epoch.epoch_id,
        "raw_range_digest": raw_range_digest,
        "rollup_digest": digest_object(
            {"|".join(key): count for key, count in sorted(rollup.items())}
        ),
        "source_scan_digest": payload["scan_digest"],
        "writer_v1_count": sum(item == 1 for item in writer_versions),
        "declared_scope_v1_residual": sum(
            item == "v1-deterministic" for item in residual_classes
        ),
        "ambiguity_detected": sum(bool(item) for item in ambiguity),
        "ambiguity_total": len(ambiguity),
        "v1_input_observed": sum(
            event.payload["input_class"] == "v1-deterministic" for event in observations
        ),
        "raw_valid": True,
        "replay_valid": True,
        "privacy_valid": True,
        "capacity_valid": len(prefix_bytes) < PROJECT_CAPACITY * 0.9,
        "release_oid": payload["release_oid"],
        "process_oid": payload["process_oid"],
    }
    values["snapshot_id"] = digest_object(values)
    return FullValidationObservationSnapshotV1._derived(values)


def compare_snapshots(
    store: ObservationStore, *, previous_scan_id: str, current_scan_id: str
) -> SnapshotComparisonV1:
    previous = build_full_snapshot(store, scan_id=previous_scan_id)
    current = build_full_snapshot(store, scan_id=current_scan_id)
    events = store.read_verified_events()
    epoch_scans = [
        event.payload["scan_id"]
        for event in events
        if event.event_type == "validation_scan"
        and event.payload.get("epoch_id") == current.epoch_id
    ]
    if previous.epoch_id != current.epoch_id:
        return SnapshotComparisonV1(False, "EPOCH_RESET", previous, current)
    if previous.basis_digest != current.basis_digest:
        return SnapshotComparisonV1(False, "BASIS_RESET", previous, current)
    try:
        previous_index = epoch_scans.index(previous_scan_id)
        current_index = epoch_scans.index(current_scan_id)
    except ValueError:
        return SnapshotComparisonV1(False, "SCAN_LINEAGE_INVALID", previous, current)
    if current_index != previous_index + 1:
        return SnapshotComparisonV1(False, "SNAPSHOTS_NOT_CONSECUTIVE", previous, current)
    if not all(
        (
            previous.raw_valid,
            previous.replay_valid,
            previous.privacy_valid,
            previous.capacity_valid,
            current.raw_valid,
            current.replay_valid,
            current.privacy_valid,
            current.capacity_valid,
        )
    ):
        return SnapshotComparisonV1(False, "SAFETY_RESET", previous, current)
    return SnapshotComparisonV1(True, "COMPARABLE", previous, current)


def assess_retirement(
    store: ObservationStore, *, previous_scan_id: str, current_scan_id: str
) -> RetirementAdmissionV1:
    comparison = compare_snapshots(
        store,
        previous_scan_id=previous_scan_id,
        current_scan_id=current_scan_id,
    )
    if (
        comparison.comparable
        and comparison.previous.gates_pass
        and comparison.current.gates_pass
    ):
        return RetirementAdmissionV1.ELIGIBLE_TO_PROPOSE
    return RetirementAdmissionV1.INELIGIBLE


def _validate_scan_input(payload: dict[str, object]) -> None:
    if set(payload) != _SCAN_INPUT_FIELDS or payload.get("schema_version") != 1:
        raise ObservationError("VALIDATION_SCAN_SCHEMA_INVALID")
    writer_versions = payload["writer_schema_versions"]
    residual = payload["declared_scope_input_classes"]
    ambiguity = payload["ambiguity_outcomes"]
    if (
        not isinstance(writer_versions, list)
        or any(type(item) is not int or item < 1 for item in writer_versions)
        or not isinstance(residual, list)
        or any(item not in ALLOWED_INPUT_CLASSES for item in residual)
        or not isinstance(ambiguity, list)
        or any(type(item) is not bool for item in ambiguity)
        or len(writer_versions) > 100_000
        or len(residual) > 100_000
        or len(ambiguity) > 100_000
    ):
        raise ObservationError("VALIDATION_SCAN_VALUE_INVALID")
    for field in ("release_oid", "process_oid"):
        value = payload[field]
        if not isinstance(value, str) or _OID_RE.fullmatch(value) is None:
            raise ObservationError("VALIDATION_SCAN_OID_INVALID")


def _validate_stored_scan(payload: dict[str, object]) -> None:
    required = _SCAN_INPUT_FIELDS | {
        "scan_id",
        "scan_digest",
        "basis_digest",
        "epoch_id",
        "implementation_digest",
        "profile_digest",
        "command_digest",
        "observed_at",
    }
    if set(payload) != required:
        raise ObservationError("VALIDATION_SCAN_SCHEMA_INVALID")
    _validate_scan_input({key: payload[key] for key in _SCAN_INPUT_FIELDS})
    for field in (
        "scan_id",
        "scan_digest",
        "basis_digest",
        "epoch_id",
        "implementation_digest",
        "profile_digest",
        "command_digest",
    ):
        _require_digest(payload[field], field)
    source_payload = {key: payload[key] for key in _SCAN_INPUT_FIELDS}
    if digest_bytes(canonical_bytes(source_payload)) != payload["scan_digest"]:
        raise ObservationError("VALIDATION_SCAN_DIGEST_MISMATCH")


def _basis_from_event(event: StoredObservationEventV1) -> ComparisonBasisV1:
    payload = dict(event.payload)
    if set(payload) != {"basis_id", "basis_digest", "invariants", "activated_at"}:
        raise ObservationError("BASIS_EVENT_INVALID")
    invariants = payload["invariants"]
    if not isinstance(invariants, dict) or set(invariants) != set(_BASIS_FIELDS):
        raise ObservationError("BASIS_EVENT_INVALID")
    normalized = tuple((name, _require_digest(invariants[name], name)) for name in _BASIS_FIELDS)
    expected = digest_object({"schema_version": 1, **dict(normalized)})
    if payload["basis_digest"] != expected:
        raise ObservationError("BASIS_DIGEST_MISMATCH")
    _require_digest(payload["basis_id"], "basis_id")
    expected_basis_id = digest_object(
        {"basis_digest": expected, "sequence": event.sequence}
    )
    if payload["basis_id"] != expected_basis_id:
        raise ObservationError("BASIS_DIGEST_MISMATCH")
    return ComparisonBasisV1._derived(
        str(payload["basis_id"]), expected, event.sequence, normalized
    )


def _latest_basis(
    events: tuple[StoredObservationEventV1, ...], *, through_sequence: int | None = None
) -> ComparisonBasisV1 | None:
    ceiling = through_sequence if through_sequence is not None else len(events)
    candidates = [
        _basis_from_event(event)
        for event in events
        if event.event_type == "basis_activated" and event.sequence <= ceiling
    ]
    return candidates[-1] if candidates else None


def _validate_epoch_payload(payload: dict[str, object]) -> None:
    if set(payload) != {
        "epoch_id",
        "basis_digest",
        "implementation_digest",
        "profile_digest",
        "command_digest",
        "started_at",
    }:
        raise ObservationError("EPOCH_EVENT_INVALID")
    for field in (
        "epoch_id",
        "basis_digest",
        "implementation_digest",
        "profile_digest",
        "command_digest",
    ):
        _require_digest(payload[field], field)


def _active_epoch(
    events: tuple[StoredObservationEventV1, ...], *, through_sequence: int | None = None
) -> StabilizationEpochV1 | None:
    ceiling = through_sequence if through_sequence is not None else len(events)
    active: StabilizationEpochV1 | None = None
    for event in events:
        if event.sequence > ceiling:
            break
        if event.event_type == "epoch_started":
            active = StabilizationEpochV1._derived(dict(event.payload), event.sequence)
        elif event.event_type == "epoch_reset":
            payload = event.payload
            if set(payload) != {"epoch_id", "reason", "reset_at"}:
                raise ObservationError("EPOCH_RESET_EVENT_INVALID")
            if active is not None and payload["epoch_id"] == active.epoch_id:
                active = None
    return active
