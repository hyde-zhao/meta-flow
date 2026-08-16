from __future__ import annotations

import pytest

from meta_flow.contracts import (
    RepositoryRole,
    TypedRefContractError,
    TypedRefErrorCode,
    TypedRefObjectKind,
    TypedRefV2,
    parse_typed_ref_v2,
)

IDENTITY = "a" * 64


@pytest.mark.parametrize(
    ("role", "ref"),
    [
        (RepositoryRole.RELEASE, "meta_flow/contracts/typed_ref.py"),
        (RepositoryRole.PROCESS, "process/checks/CP5-CR071-FORMAL.result.json"),
    ],
)
def test_v2_ref_is_canonical_and_deterministic(role: RepositoryRole, ref: str) -> None:
    candidate = TypedRefV2(2, role, TypedRefObjectKind.CHECK, ref)

    first = parse_typed_ref_v2(candidate, resolver_identity=IDENTITY)
    second = parse_typed_ref_v2(candidate, resolver_identity=IDENTITY)

    assert first == second
    assert first.value == candidate
    assert first.provenance.input_class == "v2"
    assert first.provenance.source_identity_digest != IDENTITY


def test_deterministic_v1_ref_normalizes_to_the_same_v2_value() -> None:
    v2 = {
        "schema_version": 2,
        "repository_role": "process",
        "object_kind": "story",
        "canonical_ref": "process/stories/CR-071/STORY-CR071-S04.md",
    }
    v1 = {
        "schema_version": 1,
        "repository_role": "process",
        "object_kind": "story",
        "logical_ref": "process/stories/CR-071/STORY-CR071-S04.md",
    }

    canonical = parse_typed_ref_v2(v2, resolver_identity=IDENTITY)
    legacy = parse_typed_ref_v2(v1, resolver_identity=IDENTITY)

    assert canonical.value == legacy.value
    assert legacy.provenance.input_class == "v1-deterministic"
    assert legacy.provenance.decision_code == "NORMALIZED_V1"


@pytest.mark.parametrize(
    ("candidate", "code"),
    [
        ({"schema_version": 2, "repository_role": "unknown", "object_kind": "story", "canonical_ref": "x"}, TypedRefErrorCode.UNKNOWN_REPOSITORY_ROLE),
        ({"schema_version": 2, "repository_role": "process", "object_kind": "future", "canonical_ref": "process/x"}, TypedRefErrorCode.UNKNOWN_OBJECT_KIND),
        ({"schema_version": 2, "repository_role": "process", "object_kind": "story", "canonical_ref": "story/x"}, TypedRefErrorCode.MIXED_PREFIX),
        ({"schema_version": 2, "repository_role": "release", "object_kind": "story", "canonical_ref": "process/story/x"}, TypedRefErrorCode.MIXED_PREFIX),
        ({"schema_version": 2, "repository_role": "release", "object_kind": "story", "canonical_ref": "/tmp/secret"}, TypedRefErrorCode.INVALID_CANONICAL_REF),
        ({"schema_version": 2, "repository_role": "release", "object_kind": "story", "canonical_ref": "a/../b"}, TypedRefErrorCode.INVALID_CANONICAL_REF),
        ({"schema_version": 2, "repository_role": "release", "object_kind": "story", "canonical_ref": "a//b"}, TypedRefErrorCode.INVALID_CANONICAL_REF),
        ({"schema_version": 2, "repository_role": "release", "object_kind": "story", "canonical_ref": "a\\b"}, TypedRefErrorCode.INVALID_CANONICAL_REF),
    ],
)
def test_unsafe_or_mixed_refs_fail_closed(candidate: dict[str, object], code: TypedRefErrorCode) -> None:
    with pytest.raises(TypedRefContractError) as raised:
        parse_typed_ref_v2(candidate, resolver_identity=IDENTITY)

    assert raised.value.code is code


def test_ambiguous_legacy_ref_and_error_do_not_expose_candidate() -> None:
    secret = "/physical/sibling/secret-token"
    candidate = {
        "schema_version": 1,
        "repository_role": "release",
        "object_kind": "story",
        "logical_ref": secret,
        "canonical_ref": "story/x",
    }

    with pytest.raises(TypedRefContractError) as raised:
        parse_typed_ref_v2(candidate, resolver_identity=IDENTITY)

    assert raised.value.code is TypedRefErrorCode.AMBIGUOUS_LEGACY_REF
    assert secret not in str(raised.value)


def test_public_parser_does_not_write_v1_shape() -> None:
    result = parse_typed_ref_v2(
        {
            "schema_version": 1,
            "repository_role": "release",
            "object_kind": "other",
            "logical_ref": "docs/contract.md",
        },
        resolver_identity=IDENTITY,
    )

    assert result.value.schema_version == 2
    assert not hasattr(result.value, "logical_ref")
