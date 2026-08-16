"""Durable append-only observation truth with injected atomic persistence."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import BinaryIO, Protocol

if os.name == "nt":  # pragma: no cover - exercised by Windows platform CI
    import msvcrt
else:  # pragma: no cover - branch selected by the host platform
    import fcntl

from .compatibility_observation import CompatibilityObservationV1, ObservationError

SEGMENT_EVENT_LIMIT = 10_000
SEGMENT_BYTE_LIMIT = 8 * 1024 * 1024
PROJECT_CAPACITY = 512 * 1024 * 1024
_EVENT_TYPES = frozenset(
    {
        "compatibility_observation",
        "archive_manifest",
        "basis_activated",
        "epoch_started",
        "epoch_reset",
        "validation_scan",
    }
)


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def digest_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def digest_object(value: object) -> str:
    return digest_bytes(canonical_bytes(value))


class AtomicObservationPersistence(Protocol):
    def load(self) -> bytes | None: ...

    def compare_and_swap(self, expected_digest: str | None, payload: bytes) -> str: ...


def _lock_file(stream: BinaryIO) -> None:
    if os.name == "nt":  # pragma: no cover - exercised by Windows platform CI
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
    else:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)


def _unlock_file(stream: BinaryIO) -> None:
    if os.name == "nt":  # pragma: no cover - exercised by Windows platform CI
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


@dataclass(frozen=True)
class AtomicFileObservationPersistence:
    """Atomic file CAS; the target path is injected by the caller."""

    path: Path

    def __post_init__(self) -> None:
        if not isinstance(self.path, Path) or self.path.name in {"", ".", ".."}:
            raise ValueError("persistence requires one explicit file path")
        if not self.path.parent.is_dir():
            raise ValueError("persistence parent must already exist")

    def load(self) -> bytes | None:
        if not self.path.exists():
            return None
        if not self.path.is_file() or self.path.is_symlink():
            raise ObservationError("STORAGE_OBJECT_CLASS_INVALID")
        return self.path.read_bytes()

    def compare_and_swap(self, expected_digest: str | None, payload: bytes) -> str:
        if not isinstance(payload, bytes) or not payload:
            raise ObservationError("STORAGE_PAYLOAD_INVALID")
        lock_path = self.path.with_name(f".{self.path.name}.lock")
        with lock_path.open("a+b") as lock:
            if os.name == "nt":  # pragma: no cover - exercised by Windows platform CI
                lock.seek(0)
                if lock.read(1) == b"":
                    lock.write(b"\0")
                    lock.flush()
                lock.seek(0)
            _lock_file(lock)
            try:
                current = self.load()
                current_digest = digest_bytes(current) if current is not None else None
                if current_digest != expected_digest:
                    raise ObservationError("STORAGE_CONFLICT")
                descriptor, temporary_name = tempfile.mkstemp(
                    dir=self.path.parent,
                    prefix=f".{self.path.name}.",
                    suffix=".tmp",
                )
                temporary = Path(temporary_name)
                try:
                    with os.fdopen(descriptor, "wb") as stream:
                        stream.write(payload)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temporary, self.path)
                    if os.name != "nt":
                        directory_fd = os.open(self.path.parent, os.O_RDONLY)
                        try:
                            os.fsync(directory_fd)
                        finally:
                            os.close(directory_fd)
                finally:
                    temporary.unlink(missing_ok=True)
            finally:
                _unlock_file(lock)
            return digest_bytes(payload)


@dataclass(frozen=True)
class StoredObservationEventV1:
    sequence: int
    event_type: str
    payload: Mapping[str, object]
    previous_event_digest: str
    event_digest: str

    def as_dict(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "event_type": self.event_type,
            "payload": dict(self.payload),
            "previous_event_digest": self.previous_event_digest,
            "event_digest": self.event_digest,
        }


@dataclass(frozen=True)
class PersistedObservationReceiptV1:
    observation_id: str
    sequence: int
    event_digest: str
    storage_digest: str
    capacity_state: str
    eligible_snapshot_allowed: bool


@dataclass(frozen=True)
class RawObservationSegmentV1:
    first_sequence: int
    last_sequence: int
    event_digests: tuple[str, ...]
    segment_digest: str
    archive_ref: str = ""
    archive_digest: str = ""
    replay_digest: str = ""


@dataclass(frozen=True)
class ArchiveManifestV1:
    first_sequence: int
    last_sequence: int
    segment_digest: str
    archive_ref: str
    archive_digest: str
    replay_digest: str
    sealed_at: str


class ObservationStore:
    """Verifies the full hash chain before every read or append."""

    def __init__(self, persistence: AtomicObservationPersistence) -> None:
        self._persistence = persistence

    def read_verified_events(self) -> tuple[StoredObservationEventV1, ...]:
        payload = self._persistence.load()
        return _decode_state(payload)

    def storage_digest(self) -> str:
        payload = self._persistence.load()
        return digest_bytes(payload) if payload is not None else digest_bytes(_empty_state())

    def append_observation(
        self, observation: CompatibilityObservationV1
    ) -> PersistedObservationReceiptV1:
        if not isinstance(observation, CompatibilityObservationV1):
            raise ObservationError("UNTRUSTED_OBSERVATION")
        events = self.read_verified_events()
        if any(
            event.event_type == "compatibility_observation"
            and event.payload.get("observation_id") == observation.observation_id
            for event in events
        ):
            raise ObservationError("OBSERVATION_REPLAY")
        event, state_bytes, storage_digest = self._append_event(
            "compatibility_observation", observation.as_dict(), events=events
        )
        state = capacity_state(len(state_bytes))
        if state == "blocked":
            # The CAS already persisted one exact observation. It must never be silently
            # discarded; the read remains blocked and the state is auditable.
            if observation.input_class != "v2":
                raise ObservationError("OBSERVATION_BACKPRESSURE_BLOCKED")
        return PersistedObservationReceiptV1(
            observation.observation_id,
            event.sequence,
            event.event_digest,
            storage_digest,
            state,
            state not in {"blocked", "ineligible"},
        )

    def _append_event(
        self,
        event_type: str,
        payload: Mapping[str, object],
        *,
        events: tuple[StoredObservationEventV1, ...] | None = None,
    ) -> tuple[StoredObservationEventV1, bytes, str]:
        if event_type not in _EVENT_TYPES or not isinstance(payload, Mapping):
            raise ObservationError("STORAGE_EVENT_SCHEMA_INVALID")
        current_bytes = self._persistence.load()
        current_digest = digest_bytes(current_bytes) if current_bytes is not None else None
        verified = _decode_state(current_bytes) if events is None else events
        if events is not None and verified != _decode_state(current_bytes):
            raise ObservationError("STORAGE_CONFLICT")
        sequence = len(verified) + 1
        previous = verified[-1].event_digest if verified else "0" * 64
        semantic = {
            "sequence": sequence,
            "event_type": event_type,
            "payload": dict(payload),
            "previous_event_digest": previous,
        }
        event = StoredObservationEventV1(
            sequence,
            event_type,
            dict(payload),
            previous,
            digest_object(semantic),
        )
        next_bytes = canonical_bytes(
            {"schema_version": 1, "events": [item.as_dict() for item in (*verified, event)]}
        )
        if len(next_bytes) >= PROJECT_CAPACITY:
            if (
                event_type == "compatibility_observation"
                and payload.get("input_class") != "v2"
            ):
                raise ObservationError("OBSERVATION_BACKPRESSURE_BLOCKED")
            raise ObservationError("STORAGE_CAPACITY_BLOCKED")
        committed = self._persistence.compare_and_swap(current_digest, next_bytes)
        return event, next_bytes, committed


def _empty_state() -> bytes:
    return canonical_bytes({"schema_version": 1, "events": []})


def _decode_state(payload: bytes | None) -> tuple[StoredObservationEventV1, ...]:
    if payload is None:
        return ()
    try:
        parsed = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ObservationError("STORAGE_RECOVERY_REQUIRED") from error
    if canonical_bytes(parsed) != payload:
        raise ObservationError("STORAGE_NONCANONICAL")
    if set(parsed) != {"schema_version", "events"} or parsed["schema_version"] != 1:
        raise ObservationError("STORAGE_SCHEMA_INVALID")
    raw_events = parsed["events"]
    if not isinstance(raw_events, list):
        raise ObservationError("STORAGE_SCHEMA_INVALID")
    events: list[StoredObservationEventV1] = []
    observation_ids: set[str] = set()
    previous = "0" * 64
    for index, raw in enumerate(raw_events, start=1):
        if not isinstance(raw, dict) or set(raw) != {
            "sequence",
            "event_type",
            "payload",
            "previous_event_digest",
            "event_digest",
        }:
            raise ObservationError("STORAGE_EVENT_SCHEMA_INVALID")
        if (
            raw["sequence"] != index
            or raw["event_type"] not in _EVENT_TYPES
            or raw["previous_event_digest"] != previous
            or not isinstance(raw["payload"], dict)
        ):
            raise ObservationError("STORAGE_CHAIN_INVALID")
        semantic = {key: raw[key] for key in raw if key != "event_digest"}
        if digest_object(semantic) != raw["event_digest"]:
            raise ObservationError("STORAGE_TAMPERED")
        event = StoredObservationEventV1(
            raw["sequence"],
            raw["event_type"],
            raw["payload"],
            raw["previous_event_digest"],
            raw["event_digest"],
        )
        if event.event_type == "compatibility_observation":
            observation = CompatibilityObservationV1._from_stored_payload(dict(event.payload))
            if observation.observation_id in observation_ids:
                raise ObservationError("OBSERVATION_REPLAY")
            observation_ids.add(observation.observation_id)
        events.append(event)
        previous = event.event_digest
    return tuple(events)


def capacity_state(raw_bytes: int) -> str:
    if type(raw_bytes) is not int or raw_bytes < 0:
        raise ValueError("trusted raw byte count must be non-negative")
    if raw_bytes >= PROJECT_CAPACITY:
        return "blocked"
    if raw_bytes >= PROJECT_CAPACITY * 0.9:
        return "ineligible"
    if raw_bytes >= PROJECT_CAPACITY * 0.8:
        return "warning"
    return "normal"


def _observation_events(
    events: tuple[StoredObservationEventV1, ...],
    *,
    after_sequence: int = 0,
    through_sequence: int | None = None,
) -> tuple[StoredObservationEventV1, ...]:
    ceiling = through_sequence if through_sequence is not None else len(events)
    return tuple(
        event
        for event in events
        if event.event_type == "compatibility_observation"
        and after_sequence < event.sequence <= ceiling
    )


def seal_and_archive_segment(
    store: ObservationStore,
    archive_persistence: AtomicObservationPersistence,
    *,
    archive_ref: str,
    sealed_at: datetime,
) -> tuple[RawObservationSegmentV1, ArchiveManifestV1]:
    if (
        not isinstance(archive_ref, str)
        or not archive_ref
        or archive_ref.startswith("/")
        or "\\" in archive_ref
    ):
        raise ObservationError("INVALID_ARCHIVE_REF")
    if sealed_at.tzinfo is None:
        raise ObservationError("INVALID_SEALED_AT")
    events = store.read_verified_events()
    prior_manifests = [event for event in events if event.event_type == "archive_manifest"]
    after = int(prior_manifests[-1].payload["last_sequence"]) if prior_manifests else 0
    observations = _observation_events(events, after_sequence=after)
    if not observations:
        raise ObservationError("EMPTY_SEGMENT")
    event_digests = tuple(event.event_digest for event in observations)
    segment_digest = digest_object(event_digests)
    archive_payload = canonical_bytes(
        {
            "schema_version": 1,
            "first_sequence": observations[0].sequence,
            "last_sequence": observations[-1].sequence,
            "segment_digest": segment_digest,
            "events": [event.as_dict() for event in observations],
        }
    )
    archive_digest = archive_persistence.compare_and_swap(None, archive_payload)
    replay_digest = _verify_archive_bytes(archive_payload, observations)
    sealed = sealed_at.astimezone(UTC).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )
    manifest_payload = {
        "first_sequence": observations[0].sequence,
        "last_sequence": observations[-1].sequence,
        "segment_digest": segment_digest,
        "archive_ref": archive_ref,
        "archive_digest": archive_digest,
        "replay_digest": replay_digest,
        "sealed_at": sealed,
    }
    store._append_event("archive_manifest", manifest_payload, events=events)
    manifest = ArchiveManifestV1(**manifest_payload)
    segment = RawObservationSegmentV1(
        observations[0].sequence,
        observations[-1].sequence,
        event_digests,
        segment_digest,
        archive_ref,
        archive_digest,
        replay_digest,
    )
    return segment, manifest


def _verify_archive_bytes(
    payload: bytes, expected: tuple[StoredObservationEventV1, ...]
) -> str:
    try:
        parsed = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ObservationError("ARCHIVE_REPLAY_MISMATCH") from error
    if canonical_bytes(parsed) != payload or parsed.get("events") != [
        event.as_dict() for event in expected
    ]:
        raise ObservationError("ARCHIVE_REPLAY_MISMATCH")
    if parsed.get("segment_digest") != digest_object(
        tuple(event.event_digest for event in expected)
    ):
        raise ObservationError("ARCHIVE_REPLAY_MISMATCH")
    return digest_object(tuple(event.event_digest for event in expected))


def verify_archived_segment(
    store: ObservationStore,
    archive_persistence: AtomicObservationPersistence,
    manifest: ArchiveManifestV1,
) -> bool:
    payload = archive_persistence.load()
    if payload is None or digest_bytes(payload) != manifest.archive_digest:
        raise ObservationError("ARCHIVE_TAMPERED")
    events = store.read_verified_events()
    expected = _observation_events(
        events,
        after_sequence=manifest.first_sequence - 1,
        through_sequence=manifest.last_sequence,
    )
    replay = _verify_archive_bytes(payload, expected)
    if replay != manifest.replay_digest or replay != manifest.segment_digest:
        raise ObservationError("ARCHIVE_REPLAY_MISMATCH")
    return True


def rebuild_rollup(
    store: ObservationStore, *, through_sequence: int | None = None
) -> dict[tuple[str, ...], int]:
    events = store.read_verified_events()
    counts: dict[tuple[str, ...], int] = {}
    for event in _observation_events(events, through_sequence=through_sequence):
        observation = CompatibilityObservationV1._from_stored_payload(dict(event.payload))
        key = (
            observation.reader_contract_version,
            observation.input_class,
            observation.decision,
            observation.diagnostic_code,
            observation.logical_object_kind,
            observation.profile_digest[:12],
        )
        counts[key] = counts.get(key, 0) + 1
        if len(counts) > 4096:
            raise ObservationError("ROLLUP_CAPACITY_BLOCKED")
    rendered = {"|".join(key): count for key, count in counts.items()}
    if len(canonical_bytes(rendered)) > 8 * 1024 * 1024:
        raise ObservationError("ROLLUP_CAPACITY_BLOCKED")
    return counts
