"""Trusted adapters from S04 safe results to privacy-closed observations."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from typing import TYPE_CHECKING

from meta_flow.contracts.typed_ref import (
    RepositoryRole,
    TypedRefContractError,
    TypedRefParseResult,
)
from meta_flow.contracts.validation_policy import (
    ValidationPolicyContractError,
    ValidationPolicyNormalizationResult,
)

if TYPE_CHECKING:
    from .observation_storage import ObservationStore, PersistedObservationReceiptV1

_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


class InputClassV1(StrEnum):
    V2 = "v2"
    V1_DETERMINISTIC = "v1-deterministic"
    AMBIGUOUS = "ambiguous"
    UNKNOWN = "unknown"


class ReaderContractV1(StrEnum):
    TYPED_REF_V2 = "typed-ref-v2"
    VALIDATION_POLICY_V2 = "validation-policy-v2"


ALLOWED_INPUT_CLASSES = frozenset(item.value for item in InputClassV1)
ALLOWED_REPOSITORY_ROLES = frozenset(item.value for item in RepositoryRole)
ALLOWED_OBJECT_KINDS = frozenset(
    {
        "work",
        "story",
        "check",
        "checkpoint",
        "context",
        "handoff",
        "return_packet",
        "evidence_index",
        "feature_design",
        "other",
        "validation_policy",
    }
)
_ALLOWED_SUCCESS_DECISIONS = frozenset({"ACCEPTED_V2", "NORMALIZED_V1"})


class ObservationError(ValueError):
    """Closed error that never renders rejected caller data."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"compatibility observation rejected: {code}")


def _require_digest(value: object) -> str:
    if not isinstance(value, str) or _HEX_RE.fullmatch(value) is None:
        raise ObservationError("INVALID_IDENTITY_DIGEST")
    return value


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _utc(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ObservationError("INVALID_OBSERVED_AT")
    normalized = value.astimezone(UTC)
    return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass(frozen=True, init=False)
class CompatibilityObservationV1:
    observation_id: str
    observed_at: str
    reader_contract_version: str
    input_class: str
    decision: str
    diagnostic_code: str
    repository_role: str
    logical_object_kind: str
    source_identity_digest: str
    payload_digest: str
    run_identity_digest: str
    profile_digest: str
    command_identity_digest: str
    privacy_schema_revision: int

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("CompatibilityObservationV1 must be created by a trusted adapter")

    @classmethod
    def _from_safe_fields(cls, fields: dict[str, object]) -> CompatibilityObservationV1:
        _validate_fields(fields)
        instance = object.__new__(cls)
        for key, value in fields.items():
            object.__setattr__(instance, key, value)
        return instance

    def as_dict(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in _OBSERVATION_FIELDS}

    @classmethod
    def _from_stored_payload(
        cls, payload: dict[str, object]
    ) -> CompatibilityObservationV1:
        return cls._from_safe_fields(payload)


_OBSERVATION_FIELDS = (
    "observation_id",
    "observed_at",
    "reader_contract_version",
    "input_class",
    "decision",
    "diagnostic_code",
    "repository_role",
    "logical_object_kind",
    "source_identity_digest",
    "payload_digest",
    "run_identity_digest",
    "profile_digest",
    "command_identity_digest",
    "privacy_schema_revision",
)


def _validate_fields(fields: dict[str, object]) -> None:
    if set(fields) != set(_OBSERVATION_FIELDS):
        raise ObservationError("INVALID_OBSERVATION_SCHEMA")
    if fields["privacy_schema_revision"] != 1:
        raise ObservationError("INVALID_PRIVACY_SCHEMA")
    if fields["reader_contract_version"] not in {item.value for item in ReaderContractV1}:
        raise ObservationError("UNKNOWN_READER_CONTRACT")
    if fields["input_class"] not in ALLOWED_INPUT_CLASSES:
        raise ObservationError("UNKNOWN_INPUT_CLASS")
    if fields["repository_role"] not in ALLOWED_REPOSITORY_ROLES:
        raise ObservationError("UNKNOWN_REPOSITORY_ROLE")
    if fields["logical_object_kind"] not in ALLOWED_OBJECT_KINDS:
        raise ObservationError("UNKNOWN_OBJECT_KIND")
    for field in (
        "observation_id",
        "source_identity_digest",
        "payload_digest",
        "run_identity_digest",
        "profile_digest",
        "command_identity_digest",
    ):
        _require_digest(fields[field])
    for field in ("decision", "diagnostic_code"):
        value = fields[field]
        if not isinstance(value, str) or _SAFE_CODE_RE.fullmatch(value) is None:
            raise ObservationError("INVALID_ALLOWLIST_VALUE")
    observed_at = fields["observed_at"]
    if not isinstance(observed_at, str) or not observed_at.endswith("Z"):
        raise ObservationError("INVALID_OBSERVED_AT")
    try:
        datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise ObservationError("INVALID_OBSERVED_AT") from error
    semantic = {key: fields[key] for key in _OBSERVATION_FIELDS if key != "observation_id"}
    if sha256(_canonical(semantic)).hexdigest() != fields["observation_id"]:
        raise ObservationError("OBSERVATION_ID_MISMATCH")


def _build_observation(
    *,
    reader: ReaderContractV1,
    input_class: str,
    decision: str,
    diagnostic_code: str,
    repository_role: str,
    logical_object_kind: str,
    source_identity_digest: str,
    payload: object,
    run_identity_digest: str,
    profile_digest: str,
    command_identity_digest: str,
    observed_at: datetime,
) -> CompatibilityObservationV1:
    if decision != "REJECTED" and decision not in _ALLOWED_SUCCESS_DECISIONS:
        raise ObservationError("UNKNOWN_DECISION")
    fields: dict[str, object] = {
        "observed_at": _utc(observed_at),
        "reader_contract_version": reader.value,
        "input_class": input_class,
        "decision": decision,
        "diagnostic_code": diagnostic_code,
        "repository_role": repository_role,
        "logical_object_kind": logical_object_kind,
        "source_identity_digest": _require_digest(source_identity_digest),
        "payload_digest": sha256(_canonical(payload)).hexdigest(),
        "run_identity_digest": _require_digest(run_identity_digest),
        "profile_digest": _require_digest(profile_digest),
        "command_identity_digest": _require_digest(command_identity_digest),
        "privacy_schema_revision": 1,
    }
    fields["observation_id"] = sha256(_canonical(fields)).hexdigest()
    return CompatibilityObservationV1._from_safe_fields(fields)


def observe_compatibility_decision(
    *,
    result: TypedRefParseResult | ValidationPolicyNormalizationResult,
    store: ObservationStore,
    run_identity_digest: str,
    profile_digest: str,
    command_identity_digest: str,
    observed_at: datetime,
    policy_repository_role: RepositoryRole | None = None,
) -> PersistedObservationReceiptV1:
    """Persist an observation derived from an exact S04 result object."""

    if isinstance(result, TypedRefParseResult):
        observation = _build_observation(
            reader=ReaderContractV1.TYPED_REF_V2,
            input_class=result.provenance.input_class,
            decision=result.provenance.decision_code,
            diagnostic_code="NONE",
            repository_role=result.value.repository_role.value,
            logical_object_kind=result.value.object_kind.value,
            source_identity_digest=result.provenance.source_identity_digest,
            payload=asdict(result.value),
            run_identity_digest=run_identity_digest,
            profile_digest=profile_digest,
            command_identity_digest=command_identity_digest,
            observed_at=observed_at,
        )
    elif isinstance(result, ValidationPolicyNormalizationResult):
        if not isinstance(policy_repository_role, RepositoryRole):
            raise ObservationError("MISSING_POLICY_REPOSITORY_ROLE")
        observation = _build_observation(
            reader=ReaderContractV1.VALIDATION_POLICY_V2,
            input_class=result.provenance.input_class,
            decision=result.provenance.decision_code,
            diagnostic_code="NONE",
            repository_role=policy_repository_role.value,
            logical_object_kind="validation_policy",
            source_identity_digest=result.provenance.policy_identity_digest,
            payload=asdict(result.value),
            run_identity_digest=run_identity_digest,
            profile_digest=profile_digest,
            command_identity_digest=command_identity_digest,
            observed_at=observed_at,
        )
    else:
        raise ObservationError("UNTRUSTED_COMPATIBILITY_RESULT")
    return store.append_observation(observation)


def observe_compatibility_failure(
    *,
    error: TypedRefContractError | ValidationPolicyContractError,
    store: ObservationStore,
    input_class: InputClassV1,
    repository_role: RepositoryRole,
    logical_object_kind: str,
    run_identity_digest: str,
    profile_digest: str,
    command_identity_digest: str,
    observed_at: datetime,
) -> PersistedObservationReceiptV1:
    """Persist a closed ambiguous/unknown S04 failure without its raw input."""

    if input_class not in {InputClassV1.AMBIGUOUS, InputClassV1.UNKNOWN}:
        raise ObservationError("INVALID_FAILURE_INPUT_CLASS")
    if isinstance(error, TypedRefContractError):
        reader = ReaderContractV1.TYPED_REF_V2
        code = error.code.value
    elif isinstance(error, ValidationPolicyContractError):
        reader = ReaderContractV1.VALIDATION_POLICY_V2
        code = error.code.value
    else:
        raise ObservationError("UNTRUSTED_COMPATIBILITY_ERROR")
    observation = _build_observation(
        reader=reader,
        input_class=input_class.value,
        decision="REJECTED",
        diagnostic_code=code,
        repository_role=repository_role.value,
        logical_object_kind=logical_object_kind,
        source_identity_digest=sha256(f"{reader.value}:{code}".encode("ascii")).hexdigest(),
        payload={"error_code": code, "reader": reader.value},
        run_identity_digest=run_identity_digest,
        profile_digest=profile_digest,
        command_identity_digest=command_identity_digest,
        observed_at=observed_at,
    )
    return store.append_observation(observation)
