from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest

from meta_flow.contracts.typed_ref import (
    RepositoryRole,
    TypedRefObjectKind,
    TypedRefV2,
    parse_typed_ref_v2,
)
from meta_flow.migration import (
    AtomicFileObservationPersistence,
    ObservationError,
    ObservationStore,
    observe_compatibility_decision,
    rebuild_rollup,
    seal_and_archive_segment,
    verify_archived_segment,
)

D = sha256(b"identity").hexdigest()
NOW = datetime(2026, 8, 16, tzinfo=UTC)


def _result(ref: str = "stories/S01.md"):
    return parse_typed_ref_v2(
        TypedRefV2(2, RepositoryRole.RELEASE, TypedRefObjectKind.STORY, ref),
        resolver_identity=D,
    )


def _observe(store: ObservationStore, *, at: datetime = NOW, ref: str = "stories/S01.md"):
    return observe_compatibility_decision(
        result=_result(ref),
        store=store,
        run_identity_digest=D,
        profile_digest=D,
        command_identity_digest=D,
        observed_at=at,
    )


def test_atomic_store_is_durable_and_rebuilds_rollup_from_verified_events(tmp_path) -> None:
    path = tmp_path / "observations.json"
    store = ObservationStore(AtomicFileObservationPersistence(path))
    _observe(store)
    _observe(store, at=NOW + timedelta(seconds=1), ref="stories/S02.md")
    recovered = ObservationStore(AtomicFileObservationPersistence(path))
    assert len(recovered.read_verified_events()) == 2
    assert sum(rebuild_rollup(recovered).values()) == 2


def test_replay_of_same_observation_is_rejected(tmp_path) -> None:
    store = ObservationStore(AtomicFileObservationPersistence(tmp_path / "observations.json"))
    _observe(store)
    with pytest.raises(ObservationError, match="OBSERVATION_REPLAY"):
        _observe(store)
    assert len(store.read_verified_events()) == 1


def test_tamper_and_truncated_storage_fail_closed(tmp_path) -> None:
    path = tmp_path / "observations.json"
    store = ObservationStore(AtomicFileObservationPersistence(path))
    _observe(store)
    payload = json.loads(path.read_text())
    payload["events"][0]["payload"]["decision"] = "FORGED"
    path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    with pytest.raises(ObservationError, match="STORAGE_TAMPERED"):
        store.read_verified_events()

    recovery_path = tmp_path / "recovery.json"
    recovery_path.write_bytes(b'{"schema_version":1,"events":[')
    recovery = ObservationStore(AtomicFileObservationPersistence(recovery_path))
    with pytest.raises(ObservationError, match="STORAGE_RECOVERY_REQUIRED"):
        recovery.read_verified_events()


def test_archive_replay_is_verified_and_archive_tamper_denies(tmp_path) -> None:
    store = ObservationStore(
        AtomicFileObservationPersistence(tmp_path / "observations.json")
    )
    archive_persistence = AtomicFileObservationPersistence(tmp_path / "archive.json")
    _observe(store)
    segment, manifest = seal_and_archive_segment(
        store,
        archive_persistence,
        archive_ref="archive/segment-1.json",
        sealed_at=NOW,
    )
    assert segment.segment_digest == manifest.replay_digest
    assert verify_archived_segment(store, archive_persistence, manifest)
    archive_persistence.path.write_bytes(archive_persistence.path.read_bytes() + b" ")
    with pytest.raises(ObservationError, match="ARCHIVE_TAMPERED"):
        verify_archived_segment(store, archive_persistence, manifest)


def test_atomic_compare_and_swap_rejects_stale_writer(tmp_path) -> None:
    persistence = AtomicFileObservationPersistence(tmp_path / "cas.json")
    first = b'{"events":[],"schema_version":1}'
    second = b'{"events":[{"candidate":2}],"schema_version":1}'
    first_digest = persistence.compare_and_swap(None, first)
    with pytest.raises(ObservationError, match="STORAGE_CONFLICT"):
        persistence.compare_and_swap(None, second)
    assert persistence.path.read_bytes() == first
    assert sha256(persistence.path.read_bytes()).hexdigest() == first_digest
    assert list(tmp_path.glob(".cas.json.*.tmp")) == []


def test_atomic_compare_and_swap_pre_replace_failure_is_zero_write_and_cleans_temp(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    persistence = AtomicFileObservationPersistence(tmp_path / "cas.json")
    payload = b'{"events":[],"schema_version":1}'

    def fail_replace(_source, _target) -> None:
        raise OSError("injected pre-commit replace failure")

    monkeypatch.setattr("meta_flow.migration.observation_storage.os.replace", fail_replace)
    with pytest.raises(OSError, match="pre-commit replace failure"):
        persistence.compare_and_swap(None, payload)
    assert not persistence.path.exists()
    assert list(tmp_path.glob(".cas.json.*.tmp")) == []


@pytest.mark.skipif(os.name == "nt", reason="directory fsync is POSIX-only")
def test_atomic_compare_and_swap_post_replace_fsync_failure_is_recoverable(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    persistence = AtomicFileObservationPersistence(tmp_path / "cas.json")
    payload = b'{"events":[],"schema_version":1}'
    real_fsync = os.fsync
    calls = 0

    def fail_directory_fsync(descriptor: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected post-replace directory fsync failure")
        real_fsync(descriptor)

    monkeypatch.setattr("meta_flow.migration.observation_storage.os.fsync", fail_directory_fsync)
    with pytest.raises(OSError, match="post-replace directory fsync failure"):
        persistence.compare_and_swap(None, payload)
    assert persistence.load() == payload
    assert sha256(persistence.load()).hexdigest() == sha256(payload).hexdigest()
    assert list(tmp_path.glob(".cas.json.*.tmp")) == []


def test_lock_file_is_bound_to_the_persistence_target(tmp_path) -> None:
    persistence = AtomicFileObservationPersistence(tmp_path / "cas.json")
    persistence.compare_and_swap(None, b'{"events":[],"schema_version":1}')
    lock_path = persistence.path.with_name(f".{persistence.path.name}.lock")
    assert lock_path.is_file() and not lock_path.is_symlink()
    assert lock_path.parent == persistence.path.parent


def test_append_api_has_no_caller_supplied_raw_byte_count(tmp_path) -> None:
    store = ObservationStore(AtomicFileObservationPersistence(tmp_path / "observations.json"))
    with pytest.raises(TypeError):
        store.append_observation(object(), raw_bytes=0)  # type: ignore[call-arg]
