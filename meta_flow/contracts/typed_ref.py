"""Closed, logical-only typed reference contracts.

The module deliberately performs no path resolution.  ``process/`` is a
logical namespace marker, never an instruction to find a sibling repository.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from typing import Any

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_REF_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class RepositoryRole(StrEnum):
    RELEASE = "release"
    PROCESS = "process"


class TypedRefObjectKind(StrEnum):
    WORK = "work"
    STORY = "story"
    CHECK = "check"
    CHECKPOINT = "checkpoint"
    CONTEXT = "context"
    HANDOFF = "handoff"
    RETURN_PACKET = "return_packet"
    EVIDENCE_INDEX = "evidence_index"
    FEATURE_DESIGN = "feature_design"
    OTHER = "other"


class TypedRefErrorCode(StrEnum):
    INVALID_SCHEMA_VERSION = "INVALID_SCHEMA_VERSION"
    UNKNOWN_REPOSITORY_ROLE = "UNKNOWN_REPOSITORY_ROLE"
    UNKNOWN_OBJECT_KIND = "UNKNOWN_OBJECT_KIND"
    INVALID_CANONICAL_REF = "INVALID_CANONICAL_REF"
    MIXED_PREFIX = "MIXED_PREFIX"
    AMBIGUOUS_LEGACY_REF = "AMBIGUOUS_LEGACY_REF"
    UNKNOWN_LEGACY_REF = "UNKNOWN_LEGACY_REF"


class TypedRefContractError(ValueError):
    """A safe, closed parse failure that never includes candidate payload text."""

    def __init__(self, code: TypedRefErrorCode, field: str) -> None:
        self.code = code
        self.field = field
        super().__init__(f"typed reference contract rejected: {code.value} ({field})")


@dataclass(frozen=True)
class TypedRefV2:
    schema_version: int
    repository_role: RepositoryRole
    object_kind: TypedRefObjectKind
    canonical_ref: str

    def __post_init__(self) -> None:
        if self.schema_version != 2:
            raise TypedRefContractError(TypedRefErrorCode.INVALID_SCHEMA_VERSION, "schema_version")
        _validate_ref_pair(self.repository_role, self.canonical_ref)


@dataclass(frozen=True)
class TypedRefProvenanceV1:
    input_schema_version: int
    input_class: str
    source_identity_digest: str
    parser_version: int
    decision_code: str


@dataclass(frozen=True)
class TypedRefParseResult:
    value: TypedRefV2
    provenance: TypedRefProvenanceV1


def parse_typed_ref_v2(
    value: TypedRefV2 | Mapping[str, Any], *, resolver_identity: str
) -> TypedRefParseResult:
    """Return a canonical v2 view of an exact v2 or deterministic v1 record.

    The sole supported v1 shape is ``schema_version/repository_role/object_kind/
    logical_ref``.  Any extra or alternate field makes the legacy meaning
    non-deterministic and is rejected.
    """

    _validate_digest(resolver_identity, "resolver_identity")
    if isinstance(value, TypedRefV2):
        return _result(value, 2, "v2", resolver_identity, "ACCEPTED_V2")
    if not isinstance(value, Mapping):
        raise TypedRefContractError(TypedRefErrorCode.UNKNOWN_LEGACY_REF, "value")
    schema_version = value.get("schema_version")
    if schema_version == 2:
        _require_exact_keys(
            value, {"schema_version", "repository_role", "object_kind", "canonical_ref"}, "v2"
        )
        return _result(
            TypedRefV2(
                2,
                _role(value["repository_role"]),
                _kind(value["object_kind"]),
                _ref(value["canonical_ref"]),
            ),
            2,
            "v2",
            resolver_identity,
            "ACCEPTED_V2",
        )
    if schema_version == 1:
        expected = {"schema_version", "repository_role", "object_kind", "logical_ref"}
        if set(value) != expected:
            raise TypedRefContractError(TypedRefErrorCode.AMBIGUOUS_LEGACY_REF, "legacy_shape")
        return _result(
            TypedRefV2(
                2,
                _role(value["repository_role"]),
                _kind(value["object_kind"]),
                _ref(value["logical_ref"]),
            ),
            1,
            "v1-deterministic",
            resolver_identity,
            "NORMALIZED_V1",
        )
    if "schema_version" in value:
        raise TypedRefContractError(TypedRefErrorCode.INVALID_SCHEMA_VERSION, "schema_version")
    raise TypedRefContractError(TypedRefErrorCode.UNKNOWN_LEGACY_REF, "legacy_shape")


def _result(
    value: TypedRefV2,
    input_schema_version: int,
    input_class: str,
    resolver_identity: str,
    decision_code: str,
) -> TypedRefParseResult:
    return TypedRefParseResult(
        value,
        TypedRefProvenanceV1(
            input_schema_version,
            input_class,
            sha256(resolver_identity.encode("ascii")).hexdigest(),
            2,
            decision_code,
        ),
    )


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], field: str) -> None:
    if set(value) != expected:
        raise TypedRefContractError(TypedRefErrorCode.UNKNOWN_LEGACY_REF, field)


def _role(value: object) -> RepositoryRole:
    try:
        return RepositoryRole(value)
    except (TypeError, ValueError) as error:
        raise TypedRefContractError(TypedRefErrorCode.UNKNOWN_REPOSITORY_ROLE, "repository_role") from error


def _kind(value: object) -> TypedRefObjectKind:
    try:
        return TypedRefObjectKind(value)
    except (TypeError, ValueError) as error:
        raise TypedRefContractError(TypedRefErrorCode.UNKNOWN_OBJECT_KIND, "object_kind") from error


def _ref(value: object) -> str:
    if not isinstance(value, str):
        raise TypedRefContractError(TypedRefErrorCode.INVALID_CANONICAL_REF, "canonical_ref")
    return value


def _validate_ref_pair(role: RepositoryRole, canonical_ref: str) -> None:
    if not isinstance(canonical_ref, str) or not canonical_ref:
        raise TypedRefContractError(TypedRefErrorCode.INVALID_CANONICAL_REF, "canonical_ref")
    if canonical_ref.startswith("/") or "\\" in canonical_ref or "//" in canonical_ref:
        raise TypedRefContractError(TypedRefErrorCode.INVALID_CANONICAL_REF, "canonical_ref")
    segments = canonical_ref.split("/")
    if any(segment in {"", ".", ".."} or not _SAFE_REF_SEGMENT_RE.fullmatch(segment) for segment in segments):
        raise TypedRefContractError(TypedRefErrorCode.INVALID_CANONICAL_REF, "canonical_ref")
    has_process_prefix = segments[0] == "process"
    if role is RepositoryRole.PROCESS and not has_process_prefix:
        raise TypedRefContractError(TypedRefErrorCode.MIXED_PREFIX, "canonical_ref")
    if role is RepositoryRole.RELEASE and has_process_prefix:
        raise TypedRefContractError(TypedRefErrorCode.MIXED_PREFIX, "canonical_ref")


def _validate_digest(value: str, field: str) -> None:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise TypedRefContractError(TypedRefErrorCode.UNKNOWN_LEGACY_REF, field)
