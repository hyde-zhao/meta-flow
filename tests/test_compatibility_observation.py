from __future__ import annotations

from datetime import UTC, datetime
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
    CompatibilityObservationV1,
    ObservationStore,
    observe_compatibility_decision,
)

D = sha256(b"identity").hexdigest()
NOW = datetime(2026, 8, 16, tzinfo=UTC)


def _store(tmp_path):
    return ObservationStore(AtomicFileObservationPersistence(tmp_path / "observations.json"))


def _typed_result(*, legacy: bool = False):
    value = (
        {
            "schema_version": 1,
            "repository_role": "release",
            "object_kind": "story",
            "logical_ref": "stories/S01.md",
        }
        if legacy
        else TypedRefV2(
            2,
            RepositoryRole.RELEASE,
            TypedRefObjectKind.STORY,
            "stories/S01.md",
        )
    )
    return parse_typed_ref_v2(value, resolver_identity=D)


def test_real_s04_result_is_persisted_digest_only(tmp_path) -> None:
    store = _store(tmp_path)
    receipt = observe_compatibility_decision(
        result=_typed_result(legacy=True),
        store=store,
        run_identity_digest=D,
        profile_digest=D,
        command_identity_digest=D,
        observed_at=NOW,
    )
    event = store.read_verified_events()[0]
    assert receipt.sequence == 1
    assert event.payload["input_class"] == "v1-deterministic"
    assert "canonical_ref" not in event.payload
    assert "stories/S01.md" not in repr(event.payload)
    assert event.payload["payload_digest"] == event.payload["source_identity_digest"] or len(
        event.payload["payload_digest"]
    ) == 64


def test_direct_observation_construction_and_old_raw_api_are_rejected(tmp_path) -> None:
    with pytest.raises(TypeError, match="trusted adapter"):
        CompatibilityObservationV1(observation_id=D)
    with pytest.raises(TypeError):
        observe_compatibility_decision(
            input_class="v1-deterministic",  # type: ignore[call-arg]
            decision="NORMALIZED_V1",  # type: ignore[call-arg]
            store=_store(tmp_path),
        )


def test_untrusted_result_object_is_rejected_without_persistence(tmp_path) -> None:
    store = _store(tmp_path)
    with pytest.raises(ValueError, match="UNTRUSTED_COMPATIBILITY_RESULT"):
        observe_compatibility_decision(
            result={"input_class": "v2"},  # type: ignore[arg-type]
            store=store,
            run_identity_digest=D,
            profile_digest=D,
            command_identity_digest=D,
            observed_at=NOW,
        )
    assert store.read_verified_events() == ()
