"""Validated published-leg aggregation without persistence or runtime mutation."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol

from meta_flow.project.process_route import _resolve_runtime_path, _resolve_runtime_ref
from meta_flow.workflow.artifact_policy import (
    ARTIFACT_MODE,
    SOURCE_MODE,
    target_policy_errors,
)

LEG_SCHEMA_VERSION = 1
AGGREGATE_SCHEMA_VERSION = 1
CANONICAL_REQUIRED_LEGS = ("source", "artifact")
CANONICAL_EXPECTED_MODES = (
    ("source", SOURCE_MODE),
    ("artifact", ARTIFACT_MODE),
)
CORRELATION_FIELDS = (
    "operation_id",
    "logical_attempt",
    "cr_id",
    "project_id",
    "leg_kind",
)


class AggregateStatus(StrEnum):
    BLOCKED = "BLOCKED"
    FAIL = "FAIL"
    IN_PROGRESS = "IN_PROGRESS"
    PASS = "PASS"


class ProjectionDecision(StrEnum):
    HOLD = "HOLD"
    ELIGIBLE = "ELIGIBLE"


class ValidationCode(StrEnum):
    INVALID_REQUIRED_SET = "invalid-required-set"
    INVALID_HANDLE = "invalid-handle"
    UNSUPPORTED_SCHEMA = "unsupported-schema"
    UNPUBLISHED_RESULT = "unpublished-result"
    READ_FAILED = "read-failed"
    INVALID_PAYLOAD = "invalid-payload"
    DIGEST_MISMATCH = "digest-mismatch"
    RECEIPT_MISMATCH = "receipt-mismatch"
    SINGLE_WRITE_KEY_MISMATCH = "single-write-key-mismatch"
    CORRELATION_MISMATCH = "correlation-mismatch"
    MODE_MISMATCH = "mode-mismatch"
    TARGET_POLICY_MISMATCH = "target-policy-mismatch"


class LegResultReader(Protocol):
    def read(self, result_ref: str) -> Any: ...


@dataclass(frozen=True)
class AggregateRequest:
    operation_id: str
    logical_attempt: int
    cr_id: str
    project_id: str
    required_legs: tuple[str, ...] = CANONICAL_REQUIRED_LEGS
    expected_modes: tuple[tuple[str, str], ...] = CANONICAL_EXPECTED_MODES
    policy_version: str = "aggregate-v1"

    def __post_init__(self) -> None:
        if not all((self.operation_id, self.cr_id, self.project_id, self.policy_version)):
            raise ValueError("aggregate request identity fields must be non-empty")
        if self.logical_attempt < 1:
            raise ValueError("logical_attempt must be a positive integer")
        if self.required_legs != CANONICAL_REQUIRED_LEGS:
            raise ValueError("aggregate required_legs must be the canonical source/artifact pair")
        if self.expected_modes != CANONICAL_EXPECTED_MODES:
            raise ValueError(
                "aggregate expected_modes must use the canonical source/artifact policy"
            )

    @property
    def mode_by_leg(self) -> Mapping[str, str]:
        return MappingProxyType(dict(self.expected_modes))

    def identity_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "logical_attempt": self.logical_attempt,
            "cr_id": self.cr_id,
            "project_id": self.project_id,
            "required_legs": list(self.required_legs),
            "expected_modes": dict(self.expected_modes),
            "policy_version": self.policy_version,
        }


@dataclass(frozen=True)
class ValidationError:
    code: ValidationCode
    message: str
    leg_kind: str | None = None
    result_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "leg_kind": self.leg_kind,
            "result_ref": self.result_ref,
        }


@dataclass(frozen=True)
class ValidatedPublishedLegResult:
    leg_kind: str
    mode: str
    status: AggregateStatus
    terminal: bool
    result_ref: str
    payload_digest: str
    single_write_key: str
    receipt_digest: str
    writer_id: str
    written_at: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class ValidatedLegSet:
    request: AggregateRequest
    legs: tuple[ValidatedPublishedLegResult, ...]

    def by_leg(self) -> Mapping[str, ValidatedPublishedLegResult]:
        return MappingProxyType({leg.leg_kind: leg for leg in self.legs})


@dataclass(frozen=True)
class ValidationOutcome:
    validated: ValidatedLegSet | None
    errors: tuple[ValidationError, ...]

    @property
    def ok(self) -> bool:
        return self.validated is not None and not self.errors


@dataclass(frozen=True)
class ValidationBlockedDecision:
    overall: AggregateStatus
    terminal: bool
    projection_decision: ProjectionDecision
    blockers: tuple[dict[str, Any], ...]
    next_route: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall.value,
            "terminal": self.terminal,
            "projection_decision": self.projection_decision.value,
            "blockers": list(self.blockers),
            "next_route": self.next_route,
        }


@dataclass(frozen=True)
class AggregateResult:
    schema_version: int
    aggregate_id: str
    operation_id: str
    logical_attempt: int
    cr_id: str
    project_id: str
    required_legs: tuple[str, ...]
    published_handle_refs: tuple[tuple[str, Mapping[str, str]], ...]
    validated_correlation: Mapping[str, Any]
    precedence_version: str
    overall: AggregateStatus
    terminal: bool
    progress: Mapping[str, Any]
    effect: str
    blockers: tuple[str, ...]
    next_route: str
    projection_decision: ProjectionDecision
    input_digest: str
    created_at: str
    payload_digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "aggregate_id": self.aggregate_id,
            "operation_id": self.operation_id,
            "logical_attempt": self.logical_attempt,
            "cr_id": self.cr_id,
            "project_id": self.project_id,
            "required_legs": list(self.required_legs),
            "published_handle_refs": {
                leg_kind: dict(handle_ref) for leg_kind, handle_ref in self.published_handle_refs
            },
            "validated_correlation": dict(self.validated_correlation),
            "precedence_version": self.precedence_version,
            "overall": self.overall.value,
            "terminal": self.terminal,
            "progress": dict(self.progress),
            "effect": self.effect,
            "blockers": list(self.blockers),
            "next_route": self.next_route,
            "projection_decision": self.projection_decision.value,
            "input_digest": self.input_digest,
            "created_at": self.created_at,
            "payload_digest": self.payload_digest,
        }


def _jsonable(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_jsonable(item) for item in value]
    return value


def canonical_json_digest(value: Any, *, omit_keys: set[str] | frozenset[str] = frozenset()) -> str:
    normalized = _jsonable(value)
    if isinstance(normalized, dict):
        excluded = frozenset(omit_keys)
        normalized = {key: item for key, item in normalized.items() if key not in excluded}
    canonical = json.dumps(
        normalized,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _as_mapping(value: Any, *, label: str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value) and not isinstance(value, type):
        rendered = asdict(value)
        if isinstance(rendered, dict):
            return rendered
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        rendered = to_dict()
        if isinstance(rendered, Mapping):
            return dict(rendered)
    raise TypeError(f"{label} must be a mapping, dataclass, or expose to_dict()")


def _canonical_correlation(value: Any) -> dict[str, Any]:
    correlation = _as_mapping(value, label="leg correlation")
    missing = [field for field in CORRELATION_FIELDS if correlation.get(field) in (None, "")]
    if missing:
        raise ValueError(f"leg correlation missing fields: {', '.join(missing)}")
    logical_attempt = correlation["logical_attempt"]
    if (
        isinstance(logical_attempt, bool)
        or not isinstance(logical_attempt, int)
        or logical_attempt < 1
    ):
        raise ValueError("leg correlation logical_attempt must be a positive integer")
    return {field: correlation[field] for field in CORRELATION_FIELDS}


def derive_leg_single_write_key(correlation: Any) -> str:
    return canonical_json_digest(_canonical_correlation(correlation))


def canonical_leg_receipt_digest(
    *,
    single_write_key: str,
    result_ref: str,
    payload_digest: str,
    writer_id: str,
    written_at: str,
) -> str:
    return canonical_json_digest(
        {
            "single_write_key": single_write_key,
            "result_ref": result_ref,
            "payload_digest": payload_digest,
            "writer_id": writer_id,
            "written_at": written_at,
        }
    )


def _reader_callable(reader: LegResultReader | Callable[[str], Any]) -> Callable[[str], Any]:
    if callable(reader):
        return reader
    for method_name in ("read", "read_payload", "read_result"):
        method = getattr(reader, method_name, None)
        if callable(method):
            return method
    raise TypeError("reader must be callable or expose read/read_payload/read_result")


def _handle_leg_kind(handle: Mapping[str, Any]) -> str:
    try:
        correlation = _as_mapping(handle.get("correlation"), label="handle correlation")
    except (TypeError, ValueError):
        return ""
    return str(correlation.get("leg_kind") or "")


def _required_set_errors(
    request: AggregateRequest,
    handles: Sequence[Mapping[str, Any]],
) -> tuple[ValidationError, ...]:
    errors: list[ValidationError] = []
    if request.required_legs != CANONICAL_REQUIRED_LEGS:
        errors.append(
            ValidationError(
                ValidationCode.INVALID_REQUIRED_SET,
                "required_legs must be the canonical ordered source/artifact pair",
            )
        )
    kinds = [_handle_leg_kind(handle) for handle in handles]
    if len(handles) != len(CANONICAL_REQUIRED_LEGS) or sorted(kinds) != sorted(
        CANONICAL_REQUIRED_LEGS
    ):
        errors.append(
            ValidationError(
                ValidationCode.INVALID_REQUIRED_SET,
                "published handles must contain source and artifact exactly once",
            )
        )
    return tuple(errors)


def _expected_correlation(request: AggregateRequest, leg_kind: str) -> dict[str, Any]:
    return {
        "operation_id": request.operation_id,
        "logical_attempt": request.logical_attempt,
        "cr_id": request.cr_id,
        "project_id": request.project_id,
        "leg_kind": leg_kind,
    }


def _error(
    errors: list[ValidationError],
    code: ValidationCode,
    message: str,
    *,
    leg_kind: str = "",
    result_ref: str = "",
) -> None:
    errors.append(
        ValidationError(
            code=code,
            message=message,
            leg_kind=leg_kind or None,
            result_ref=result_ref or None,
        )
    )


def _validate_one_handle(
    request: AggregateRequest,
    raw_handle: Mapping[str, Any],
    *,
    read_result: Callable[[str], Any],
) -> tuple[ValidatedPublishedLegResult | None, tuple[ValidationError, ...]]:
    errors: list[ValidationError] = []
    handle = dict(raw_handle)
    leg_kind = _handle_leg_kind(handle)
    result_ref = str(handle.get("result_ref") or "")
    if handle.get("schema_version") != LEG_SCHEMA_VERSION:
        _error(
            errors,
            ValidationCode.UNSUPPORTED_SCHEMA,
            "unsupported handle schema",
            leg_kind=leg_kind,
        )
    if handle.get("published") is False:
        _error(
            errors,
            ValidationCode.UNPUBLISHED_RESULT,
            "unpublished handle is forbidden",
            leg_kind=leg_kind,
        )
    required_handle_fields = (
        "single_write_key",
        "result_ref",
        "payload_digest",
        "receipt",
        "correlation",
        "mode",
    )
    missing_handle = [field for field in required_handle_fields if handle.get(field) in (None, "")]
    if missing_handle:
        _error(
            errors,
            ValidationCode.INVALID_HANDLE,
            f"handle missing fields: {', '.join(missing_handle)}",
            leg_kind=leg_kind,
            result_ref=result_ref,
        )
        return None, tuple(errors)

    try:
        handle_correlation = _canonical_correlation(handle["correlation"])
    except (TypeError, ValueError) as exc:
        _error(
            errors,
            ValidationCode.INVALID_HANDLE,
            str(exc),
            leg_kind=leg_kind,
            result_ref=result_ref,
        )
        return None, tuple(errors)
    leg_kind = str(handle_correlation["leg_kind"])
    expected_correlation = _expected_correlation(request, leg_kind)
    if handle_correlation != expected_correlation:
        _error(
            errors,
            ValidationCode.CORRELATION_MISMATCH,
            "handle correlation does not match aggregate request",
            leg_kind=leg_kind,
            result_ref=result_ref,
        )

    try:
        receipt = _as_mapping(handle["receipt"], label="leg write receipt")
    except TypeError as exc:
        _error(
            errors,
            ValidationCode.INVALID_HANDLE,
            str(exc),
            leg_kind=leg_kind,
            result_ref=result_ref,
        )
        return None, tuple(errors)
    required_receipt_fields = (
        "result_ref",
        "payload_digest",
        "writer_id",
        "written_at",
        "receipt_digest",
    )
    missing_receipt = [
        field for field in required_receipt_fields if receipt.get(field) in (None, "")
    ]
    if missing_receipt:
        _error(
            errors,
            ValidationCode.INVALID_HANDLE,
            f"receipt missing fields: {', '.join(missing_receipt)}",
            leg_kind=leg_kind,
            result_ref=result_ref,
        )
        return None, tuple(errors)
    if receipt["result_ref"] != result_ref or receipt["payload_digest"] != handle["payload_digest"]:
        _error(
            errors,
            ValidationCode.RECEIPT_MISMATCH,
            "receipt ref or payload digest does not match handle",
            leg_kind=leg_kind,
            result_ref=result_ref,
        )

    expected_key = derive_leg_single_write_key(handle_correlation)
    if handle["single_write_key"] != expected_key:
        _error(
            errors,
            ValidationCode.SINGLE_WRITE_KEY_MISMATCH,
            "handle single-write key does not match correlation",
            leg_kind=leg_kind,
            result_ref=result_ref,
        )
    expected_receipt_digest = canonical_leg_receipt_digest(
        single_write_key=expected_key,
        result_ref=str(receipt["result_ref"]),
        payload_digest=str(receipt["payload_digest"]),
        writer_id=str(receipt["writer_id"]),
        written_at=str(receipt["written_at"]),
    )
    if receipt["receipt_digest"] != expected_receipt_digest:
        _error(
            errors,
            ValidationCode.RECEIPT_MISMATCH,
            "receipt digest does not match external receipt fields",
            leg_kind=leg_kind,
            result_ref=result_ref,
        )

    try:
        payload = _as_mapping(read_result(result_ref), label="leg result payload")
    except (KeyError, OSError, TypeError, ValueError) as exc:
        _error(
            errors,
            ValidationCode.READ_FAILED,
            f"unable to reread result_ref: {exc}",
            leg_kind=leg_kind,
            result_ref=result_ref,
        )
        return None, tuple(errors)
    if payload.get("schema_version") != LEG_SCHEMA_VERSION:
        _error(
            errors,
            ValidationCode.UNSUPPORTED_SCHEMA,
            "unsupported payload schema",
            leg_kind=leg_kind,
            result_ref=result_ref,
        )
    try:
        payload_correlation = _canonical_correlation(payload.get("correlation"))
    except (TypeError, ValueError) as exc:
        _error(
            errors,
            ValidationCode.INVALID_PAYLOAD,
            str(exc),
            leg_kind=leg_kind,
            result_ref=result_ref,
        )
        return None, tuple(errors)
    if payload_correlation != expected_correlation or payload_correlation != handle_correlation:
        _error(
            errors,
            ValidationCode.CORRELATION_MISMATCH,
            "reread payload correlation does not match handle and request",
            leg_kind=leg_kind,
            result_ref=result_ref,
        )
    payload_digest = str(payload.get("payload_digest") or "")
    computed_payload_digest = canonical_json_digest(payload, omit_keys={"payload_digest"})
    if (
        not payload_digest
        or payload_digest != computed_payload_digest
        or payload_digest != handle["payload_digest"]
        or payload_digest != receipt["payload_digest"]
    ):
        _error(
            errors,
            ValidationCode.DIGEST_MISMATCH,
            "reread payload digest does not match payload, handle, and receipt",
            leg_kind=leg_kind,
            result_ref=result_ref,
        )
    expected_mode = request.mode_by_leg.get(leg_kind)
    payload_mode = str(payload.get("mode") or "")
    if (
        not payload_mode
        or payload_mode != str(handle["mode"])
        or (expected_mode is not None and payload_mode != expected_mode)
    ):
        _error(
            errors,
            ValidationCode.MODE_MISMATCH,
            "payload, handle, and requested leg mode do not match",
            leg_kind=leg_kind,
            result_ref=result_ref,
        )
    policy_errors = target_policy_errors(
        leg_kind=leg_kind,
        mode=payload_mode,
        project_id=request.project_id,
        cr_id=request.cr_id,
        base_ref=payload.get("base_ref"),
        target_ref=payload.get("target_ref"),
        active_ref=payload.get("active_ref"),
    )
    if policy_errors:
        _error(
            errors,
            ValidationCode.TARGET_POLICY_MISMATCH,
            "published leg target policy mismatch: " + ", ".join(policy_errors),
            leg_kind=leg_kind,
            result_ref=result_ref,
        )
    try:
        status = AggregateStatus(str(payload.get("status") or ""))
    except ValueError:
        _error(
            errors,
            ValidationCode.INVALID_PAYLOAD,
            "payload status must be BLOCKED, FAIL, IN_PROGRESS, or PASS",
            leg_kind=leg_kind,
            result_ref=result_ref,
        )
        return None, tuple(errors)
    terminal = payload.get("terminal")
    if not isinstance(terminal, bool):
        _error(
            errors,
            ValidationCode.INVALID_PAYLOAD,
            "payload terminal must be boolean",
            leg_kind=leg_kind,
            result_ref=result_ref,
        )
    elif status is AggregateStatus.PASS and not terminal:
        _error(
            errors,
            ValidationCode.INVALID_PAYLOAD,
            "PASS payload must be terminal",
            leg_kind=leg_kind,
            result_ref=result_ref,
        )
    elif status is AggregateStatus.IN_PROGRESS and terminal:
        _error(
            errors,
            ValidationCode.INVALID_PAYLOAD,
            "IN_PROGRESS payload must be non-terminal",
            leg_kind=leg_kind,
            result_ref=result_ref,
        )
    if errors:
        return None, tuple(errors)
    return (
        ValidatedPublishedLegResult(
            leg_kind=leg_kind,
            mode=payload_mode,
            status=status,
            terminal=bool(terminal),
            result_ref=result_ref,
            payload_digest=payload_digest,
            single_write_key=expected_key,
            receipt_digest=str(receipt["receipt_digest"]),
            writer_id=str(receipt["writer_id"]),
            written_at=str(receipt["written_at"]),
            payload=MappingProxyType(copy_mapping(payload)),
        ),
        (),
    )


def copy_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(_jsonable(value), ensure_ascii=False))


def validate_published_leg_results(
    request: AggregateRequest,
    handles: Sequence[Any],
    *,
    reader: LegResultReader | Callable[[str], Any],
) -> ValidationOutcome:
    mapped_handles: list[dict[str, Any]] = []
    conversion_errors: list[ValidationError] = []
    for raw_handle in handles:
        try:
            mapped_handles.append(_as_mapping(raw_handle, label="published leg handle"))
        except TypeError as exc:
            conversion_errors.append(ValidationError(ValidationCode.INVALID_HANDLE, str(exc)))
    required_errors = _required_set_errors(request, mapped_handles)
    if conversion_errors or required_errors:
        return ValidationOutcome(None, tuple(conversion_errors) + required_errors)

    read_result = _reader_callable(reader)
    validated_by_leg: dict[str, ValidatedPublishedLegResult] = {}
    errors: list[ValidationError] = []
    for handle in mapped_handles:
        validated, handle_errors = _validate_one_handle(request, handle, read_result=read_result)
        errors.extend(handle_errors)
        if validated is not None:
            validated_by_leg[validated.leg_kind] = validated
    if errors:
        return ValidationOutcome(None, tuple(errors))
    ordered = tuple(validated_by_leg[leg_kind] for leg_kind in request.required_legs)
    return ValidationOutcome(ValidatedLegSet(request=request, legs=ordered), ())


def blocked_from_validation(errors: Sequence[ValidationError]) -> ValidationBlockedDecision:
    blockers = tuple(error.to_dict() for error in errors)
    return ValidationBlockedDecision(
        overall=AggregateStatus.BLOCKED,
        terminal=True,
        projection_decision=ProjectionDecision.HOLD,
        blockers=blockers,
        next_route="repair-evidence-or-human-review",
    )


_STATUS_PRECEDENCE = {
    AggregateStatus.BLOCKED: 4,
    AggregateStatus.FAIL: 3,
    AggregateStatus.IN_PROGRESS: 2,
    AggregateStatus.PASS: 1,
}
_NEXT_ROUTE = {
    AggregateStatus.BLOCKED: "resolve-blocker-or-resume",
    AggregateStatus.FAIL: "preserve-facts-and-explicit-resume-or-abort",
    AggregateStatus.IN_PROGRESS: "wait-or-explicit-resume",
    AggregateStatus.PASS: "controlled-projection",
}


def _aggregate_effect(
    legs: tuple[ValidatedPublishedLegResult, ...], overall: AggregateStatus
) -> str:
    if overall is AggregateStatus.PASS:
        return "COMPLETE"
    effects = {str(leg.payload.get("effect") or "NONE") for leg in legs}
    statuses = {leg.status for leg in legs}
    if AggregateStatus.PASS in statuses or len(statuses) > 1 or effects - {"", "NONE"}:
        return "PARTIAL"
    return "NONE"


def _aggregate_blockers(
    legs: tuple[ValidatedPublishedLegResult, ...],
    overall: AggregateStatus,
) -> tuple[str, ...]:
    if overall is not AggregateStatus.BLOCKED:
        return ()
    blockers: list[str] = []
    for leg in legs:
        raw_blockers = leg.payload.get("blockers") or []
        if isinstance(raw_blockers, Sequence) and not isinstance(raw_blockers, (str, bytes)):
            blockers.extend(str(item) for item in raw_blockers if str(item))
        if leg.status is AggregateStatus.BLOCKED and not raw_blockers:
            blockers.append(f"{leg.leg_kind}-blocked")
    return tuple(dict.fromkeys(blockers))


def compute_aggregate(validated: ValidatedLegSet) -> AggregateResult:
    if tuple(leg.leg_kind for leg in validated.legs) != validated.request.required_legs:
        raise ValueError("validated legs must use the canonical request order")
    overall = max((leg.status for leg in validated.legs), key=_STATUS_PRECEDENCE.__getitem__)
    terminal = all(leg.terminal for leg in validated.legs)
    eligible = (
        overall is AggregateStatus.PASS
        and terminal
        and all(leg.status is AggregateStatus.PASS for leg in validated.legs)
    )
    handle_refs = tuple(
        (
            leg.leg_kind,
            MappingProxyType(
                {
                    "leg_result_ref": leg.result_ref,
                    "payload_digest": leg.payload_digest,
                    "receipt_digest": leg.receipt_digest,
                    "single_write_key": leg.single_write_key,
                }
            ),
        )
        for leg in validated.legs
    )
    input_digest = canonical_json_digest(
        {leg_kind: dict(handle_ref) for leg_kind, handle_ref in handle_refs}
    )
    aggregate_id = canonical_json_digest(
        {
            "request": validated.request.identity_dict(),
            "input_digest": input_digest,
        }
    )
    completed_legs = sum(1 for leg in validated.legs if leg.terminal)
    correlation = {
        "operation_id": validated.request.operation_id,
        "logical_attempt": validated.request.logical_attempt,
        "cr_id": validated.request.cr_id,
        "project_id": validated.request.project_id,
    }
    result = AggregateResult(
        schema_version=AGGREGATE_SCHEMA_VERSION,
        aggregate_id=aggregate_id,
        operation_id=validated.request.operation_id,
        logical_attempt=validated.request.logical_attempt,
        cr_id=validated.request.cr_id,
        project_id=validated.request.project_id,
        required_legs=validated.request.required_legs,
        published_handle_refs=handle_refs,
        validated_correlation=MappingProxyType(correlation),
        precedence_version=validated.request.policy_version,
        overall=overall,
        terminal=terminal,
        progress=MappingProxyType(
            {
                "completed_legs": completed_legs,
                "total_legs": len(validated.legs),
                "label": "COMPLETE" if completed_legs == len(validated.legs) else "IN_PROGRESS",
            }
        ),
        effect=_aggregate_effect(validated.legs, overall),
        blockers=_aggregate_blockers(validated.legs, overall),
        next_route=_NEXT_ROUTE[overall],
        projection_decision=(ProjectionDecision.ELIGIBLE if eligible else ProjectionDecision.HOLD),
        input_digest=input_digest,
        created_at=max(leg.written_at for leg in validated.legs),
        payload_digest="",
    )
    return replace(
        result,
        payload_digest=canonical_json_digest(result.to_dict(), omit_keys={"payload_digest"}),
    )


class PersistDisposition(StrEnum):
    WRITTEN = "written"
    IDEMPOTENT = "idempotent-existing"
    CONFLICT = "conflict"
    FAILED = "failed"


class ProjectionStatus(StrEnum):
    HOLD = "hold"
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True)
class StoreAppendOutcome:
    disposition: PersistDisposition
    aggregate_ref: str
    writer_id: str
    written_at: str
    error: str = ""


@dataclass(frozen=True)
class StoreSelectionOutcome:
    disposition: PersistDisposition
    current_ref: str
    error: str = ""


@dataclass(frozen=True)
class AggregateWriteReceipt:
    aggregate_id: str
    aggregate_ref: str
    payload_digest: str
    writer_id: str
    written_at: str
    receipt_digest: str
    readback_valid: bool
    current_selected: bool
    disposition: PersistDisposition
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "aggregate_id": self.aggregate_id,
            "aggregate_ref": self.aggregate_ref,
            "payload_digest": self.payload_digest,
            "writer_id": self.writer_id,
            "written_at": self.written_at,
            "receipt_digest": self.receipt_digest,
            "readback_valid": self.readback_valid,
            "current_selected": self.current_selected,
            "disposition": self.disposition.value,
            "error": self.error,
        }


@dataclass(frozen=True)
class ProjectionReceipt:
    status: ProjectionStatus
    called: bool
    aggregate_ref: str
    writer_receipts: Mapping[str, Any]
    retryable: bool
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "called": self.called,
            "aggregate_ref": self.aggregate_ref,
            "writer_receipts": dict(self.writer_receipts),
            "retryable": self.retryable,
            "error": self.error,
        }


@dataclass(frozen=True)
class AggregateCommandResult:
    overall: AggregateStatus
    validation_errors: tuple[ValidationError, ...]
    aggregate_result: AggregateResult | None
    write_receipt: AggregateWriteReceipt | None
    projection_receipt: ProjectionReceipt | None
    dry_run: bool
    next_route: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall.value,
            "validation_errors": [error.to_dict() for error in self.validation_errors],
            "aggregate_result": (
                self.aggregate_result.to_dict() if self.aggregate_result is not None else None
            ),
            "write_receipt": self.write_receipt.to_dict()
            if self.write_receipt is not None
            else None,
            "projection_receipt": (
                self.projection_receipt.to_dict() if self.projection_receipt is not None else None
            ),
            "dry_run": self.dry_run,
            "next_route": self.next_route,
        }


class AggregateStore(Protocol):
    def append_result(self, result: AggregateResult) -> StoreAppendOutcome: ...

    def read_result(self, aggregate_ref: str) -> dict[str, Any]: ...

    def compare_and_set_current(
        self,
        result: AggregateResult,
        *,
        expected_current_ref: str | None,
        aggregate_ref: str,
    ) -> StoreSelectionOutcome: ...

    def current_ref(self, result: AggregateResult) -> str | None: ...


class AggregateProjector(Protocol):
    def project_aggregate(
        self,
        *,
        result: AggregateResult,
        receipt: AggregateWriteReceipt,
    ) -> Mapping[str, Any]: ...


def _now_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _selector_key(result: AggregateResult) -> str:
    return canonical_json_digest(
        {
            "operation_id": result.operation_id,
            "logical_attempt": result.logical_attempt,
            "cr_id": result.cr_id,
            "project_id": result.project_id,
            "precedence_version": result.precedence_version,
        }
    )


def _canonical_result_payload(result: AggregateResult) -> dict[str, Any]:
    payload = result.to_dict()
    expected = canonical_json_digest(payload, omit_keys={"payload_digest"})
    if payload.get("payload_digest") != expected:
        raise ValueError("aggregate payload digest does not match canonical payload")
    return payload


def _aggregate_receipt_digest(
    *,
    aggregate_id: str,
    aggregate_ref: str,
    payload_digest: str,
    writer_id: str,
    written_at: str,
    readback_valid: bool,
    current_selected: bool,
    disposition: PersistDisposition,
) -> str:
    return canonical_json_digest(
        {
            "aggregate_id": aggregate_id,
            "aggregate_ref": aggregate_ref,
            "payload_digest": payload_digest,
            "writer_id": writer_id,
            "written_at": written_at,
            "readback_valid": readback_valid,
            "current_selected": current_selected,
            "disposition": disposition.value,
        }
    )


class InMemoryAggregateStore:
    """Deterministic fixture store with immutable append and selector CAS."""

    def __init__(self, *, writer_id: str = "memory-aggregate-writer") -> None:
        self.writer_id = writer_id
        self._results: dict[str, dict[str, Any]] = {}
        self._selectors: dict[str, str] = {}
        self._lock = threading.Lock()

    @property
    def result_count(self) -> int:
        return len(self._results)

    def append_result(self, result: AggregateResult) -> StoreAppendOutcome:
        payload = _canonical_result_payload(result)
        aggregate_ref = f"memory://aggregate/{result.aggregate_id}"
        written_at = _now_utc()
        with self._lock:
            existing = self._results.get(aggregate_ref)
            if existing is not None:
                if existing == payload:
                    return StoreAppendOutcome(
                        PersistDisposition.IDEMPOTENT,
                        aggregate_ref,
                        self.writer_id,
                        written_at,
                    )
                return StoreAppendOutcome(
                    PersistDisposition.CONFLICT,
                    aggregate_ref,
                    self.writer_id,
                    written_at,
                    "aggregate ID already exists with a different payload",
                )
            self._results[aggregate_ref] = copy_mapping(payload)
        return StoreAppendOutcome(
            PersistDisposition.WRITTEN,
            aggregate_ref,
            self.writer_id,
            written_at,
        )

    def read_result(self, aggregate_ref: str) -> dict[str, Any]:
        with self._lock:
            payload = self._results[aggregate_ref]
            return copy_mapping(payload)

    def compare_and_set_current(
        self,
        result: AggregateResult,
        *,
        expected_current_ref: str | None,
        aggregate_ref: str,
    ) -> StoreSelectionOutcome:
        selector_key = _selector_key(result)
        with self._lock:
            existing = self._selectors.get(selector_key)
            if existing == aggregate_ref:
                return StoreSelectionOutcome(PersistDisposition.IDEMPOTENT, aggregate_ref)
            if existing != expected_current_ref:
                return StoreSelectionOutcome(
                    PersistDisposition.CONFLICT,
                    existing or "",
                    "current aggregate selector does not match expected_current_ref",
                )
            self._selectors[selector_key] = aggregate_ref
        return StoreSelectionOutcome(PersistDisposition.WRITTEN, aggregate_ref)

    def current_ref(self, result: AggregateResult) -> str | None:
        with self._lock:
            return self._selectors.get(_selector_key(result))


class FileAggregateStore:
    """Project-local immutable JSON store; mutable selectors use fail-closed lock directories."""

    def __init__(
        self,
        *,
        project_root: Path,
        store_root: Path | None = None,
        writer_id: str = "meta-flow-aggregate-writer",
    ) -> None:
        self.project_root = project_root.resolve()
        self.process_root = _resolve_runtime_ref(
            self.project_root, "process/PROJECT.yaml"
        ).parent
        candidate = store_root or (
            _resolve_runtime_ref(self.project_root, "process/evidence") / "aggregates"
        )
        self.store_root = candidate.resolve()
        try:
            self.store_root.relative_to(self.process_root)
        except ValueError as exc:
            raise ValueError("aggregate store root must remain inside process repository") from exc
        self.writer_id = writer_id

    @property
    def _results_root(self) -> Path:
        return self.store_root / "results"

    @property
    def _selectors_root(self) -> Path:
        return self.store_root / "current"

    def _relative_ref(self, path: Path) -> str:
        return "process/" + path.resolve().relative_to(self.process_root).as_posix()

    def _resolve_ref(self, aggregate_ref: str) -> Path:
        if not aggregate_ref or Path(aggregate_ref).is_absolute():
            raise ValueError("aggregate_ref must be a non-empty project-relative path")
        path = _resolve_runtime_path(self.project_root, aggregate_ref)
        try:
            path.relative_to(self._results_root.resolve())
        except ValueError as exc:
            raise ValueError("aggregate_ref escapes immutable aggregate result root") from exc
        return path

    def append_result(self, result: AggregateResult) -> StoreAppendOutcome:
        payload = _canonical_result_payload(result)
        self._results_root.mkdir(parents=True, exist_ok=True)
        path = self._results_root / f"{result.aggregate_id}.json"
        aggregate_ref = self._relative_ref(path)
        written_at = _now_utc()
        rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        try:
            with path.open("x", encoding="utf-8") as stream:
                stream.write(rendered)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            existing: Any = None
            last_error: OSError | json.JSONDecodeError | None = None
            for _attempt in range(50):
                try:
                    existing = json.loads(path.read_text(encoding="utf-8"))
                    last_error = None
                    break
                except (OSError, json.JSONDecodeError) as exc:
                    last_error = exc
                    time.sleep(0.001)
            if last_error is not None:
                return StoreAppendOutcome(
                    PersistDisposition.CONFLICT,
                    aggregate_ref,
                    self.writer_id,
                    written_at,
                    f"existing aggregate is unreadable: {last_error}",
                )
            if existing == payload:
                return StoreAppendOutcome(
                    PersistDisposition.IDEMPOTENT,
                    aggregate_ref,
                    self.writer_id,
                    written_at,
                )
            return StoreAppendOutcome(
                PersistDisposition.CONFLICT,
                aggregate_ref,
                self.writer_id,
                written_at,
                "aggregate ID already exists with a different payload",
            )
        except OSError as exc:
            return StoreAppendOutcome(
                PersistDisposition.FAILED,
                aggregate_ref,
                self.writer_id,
                written_at,
                str(exc),
            )
        return StoreAppendOutcome(
            PersistDisposition.WRITTEN,
            aggregate_ref,
            self.writer_id,
            written_at,
        )

    def read_result(self, aggregate_ref: str) -> dict[str, Any]:
        path = self._resolve_ref(aggregate_ref)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("aggregate result must be a JSON object")
        return payload

    def _selector_path(self, result: AggregateResult) -> Path:
        return self._selectors_root / f"{_selector_key(result)}.json"

    def compare_and_set_current(
        self,
        result: AggregateResult,
        *,
        expected_current_ref: str | None,
        aggregate_ref: str,
    ) -> StoreSelectionOutcome:
        self._selectors_root.mkdir(parents=True, exist_ok=True)
        selector_path = self._selector_path(result)
        lock_path = selector_path.with_suffix(".lock")
        lock_acquired = False
        for _attempt in range(50):
            try:
                lock_path.mkdir()
                lock_acquired = True
                break
            except FileExistsError:
                time.sleep(0.001)
        if not lock_acquired:
            return StoreSelectionOutcome(
                PersistDisposition.CONFLICT,
                self.current_ref(result) or "",
                "current aggregate selector is locked by another writer",
            )
        try:
            existing = self.current_ref(result)
            if existing == aggregate_ref:
                return StoreSelectionOutcome(PersistDisposition.IDEMPOTENT, aggregate_ref)
            if existing != expected_current_ref:
                return StoreSelectionOutcome(
                    PersistDisposition.CONFLICT,
                    existing or "",
                    "current aggregate selector does not match expected_current_ref",
                )
            selector = {
                "aggregate_ref": aggregate_ref,
                "aggregate_id": result.aggregate_id,
                "payload_digest": result.payload_digest,
            }
            temporary = selector_path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
            try:
                with temporary.open("x", encoding="utf-8") as stream:
                    json.dump(selector, stream, ensure_ascii=False, indent=2, sort_keys=True)
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, selector_path)
            finally:
                if temporary.exists():
                    temporary.unlink()
            return StoreSelectionOutcome(PersistDisposition.WRITTEN, aggregate_ref)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return StoreSelectionOutcome(PersistDisposition.FAILED, "", str(exc))
        finally:
            try:
                lock_path.rmdir()
            except OSError:
                pass

    def current_ref(self, result: AggregateResult) -> str | None:
        selector_path = self._selector_path(result)
        if not selector_path.is_file():
            return None
        payload = json.loads(selector_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("aggregate selector must be a JSON object")
        value = payload.get("aggregate_ref")
        return str(value) if value else None


class ProjectFileLegResultReader:
    """Read only explicit project-relative leg result refs without directory discovery."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()

    def read(self, result_ref: str) -> dict[str, Any]:
        if not result_ref or Path(result_ref).is_absolute():
            raise ValueError("result_ref must be a non-empty project-relative path")
        path = (self.project_root / result_ref).resolve()
        try:
            path.relative_to(self.project_root)
        except ValueError as exc:
            raise ValueError("result_ref escapes project root") from exc
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("leg result payload must be a JSON object")
        return payload


def _receipt(
    result: AggregateResult,
    append: StoreAppendOutcome,
    *,
    readback_valid: bool,
    current_selected: bool,
    disposition: PersistDisposition,
    error: str = "",
) -> AggregateWriteReceipt:
    digest = _aggregate_receipt_digest(
        aggregate_id=result.aggregate_id,
        aggregate_ref=append.aggregate_ref,
        payload_digest=result.payload_digest,
        writer_id=append.writer_id,
        written_at=append.written_at,
        readback_valid=readback_valid,
        current_selected=current_selected,
        disposition=disposition,
    )
    return AggregateWriteReceipt(
        aggregate_id=result.aggregate_id,
        aggregate_ref=append.aggregate_ref,
        payload_digest=result.payload_digest,
        writer_id=append.writer_id,
        written_at=append.written_at,
        receipt_digest=digest,
        readback_valid=readback_valid,
        current_selected=current_selected,
        disposition=disposition,
        error=error,
    )


def persist_aggregate(
    result: AggregateResult,
    store: AggregateStore,
    *,
    expected_current_ref: str | None,
) -> AggregateWriteReceipt:
    try:
        _canonical_result_payload(result)
        append = store.append_result(result)
    except (OSError, TypeError, ValueError) as exc:
        failed_append = StoreAppendOutcome(
            PersistDisposition.FAILED,
            "",
            "aggregate-writer",
            _now_utc(),
            str(exc),
        )
        return _receipt(
            result,
            failed_append,
            readback_valid=False,
            current_selected=False,
            disposition=PersistDisposition.FAILED,
            error=str(exc),
        )
    if append.disposition in {PersistDisposition.CONFLICT, PersistDisposition.FAILED}:
        return _receipt(
            result,
            append,
            readback_valid=False,
            current_selected=False,
            disposition=append.disposition,
            error=append.error,
        )
    try:
        readback = store.read_result(append.aggregate_ref)
        readback_valid = (
            readback == result.to_dict()
            and canonical_json_digest(readback, omit_keys={"payload_digest"})
            == result.payload_digest
        )
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return _receipt(
            result,
            append,
            readback_valid=False,
            current_selected=False,
            disposition=PersistDisposition.FAILED,
            error=f"aggregate readback failed: {exc}",
        )
    if not readback_valid:
        return _receipt(
            result,
            append,
            readback_valid=False,
            current_selected=False,
            disposition=PersistDisposition.FAILED,
            error="aggregate readback digest mismatch",
        )
    selection = store.compare_and_set_current(
        result,
        expected_current_ref=expected_current_ref,
        aggregate_ref=append.aggregate_ref,
    )
    if selection.disposition in {PersistDisposition.CONFLICT, PersistDisposition.FAILED}:
        return _receipt(
            result,
            append,
            readback_valid=True,
            current_selected=False,
            disposition=selection.disposition,
            error=selection.error,
        )
    disposition = (
        PersistDisposition.IDEMPOTENT
        if append.disposition is PersistDisposition.IDEMPOTENT
        or selection.disposition is PersistDisposition.IDEMPOTENT
        else PersistDisposition.WRITTEN
    )
    return _receipt(
        result,
        append,
        readback_valid=True,
        current_selected=True,
        disposition=disposition,
    )


def _projector_callable(
    projector: AggregateProjector | Callable[..., Mapping[str, Any]],
) -> Callable[..., Mapping[str, Any]]:
    if callable(projector):
        return projector
    method = getattr(projector, "project_aggregate", None)
    if callable(method):
        return method
    raise TypeError("projector must be callable or expose project_aggregate")


def _hold_projection(aggregate_ref: str, error: str) -> ProjectionReceipt:
    return ProjectionReceipt(
        status=ProjectionStatus.HOLD,
        called=False,
        aggregate_ref=aggregate_ref,
        writer_receipts=MappingProxyType({}),
        retryable=True,
        error=error,
    )


def project_if_eligible(
    result: AggregateResult,
    receipt: AggregateWriteReceipt,
    *,
    store: AggregateStore,
    projector: AggregateProjector | Callable[..., Mapping[str, Any]],
) -> ProjectionReceipt:
    if (
        result.overall is not AggregateStatus.PASS
        or not result.terminal
        or result.projection_decision is not ProjectionDecision.ELIGIBLE
    ):
        return _hold_projection(receipt.aggregate_ref, "aggregate is not 2/2 terminal PASS")
    if (
        receipt.aggregate_id != result.aggregate_id
        or receipt.payload_digest != result.payload_digest
        or not receipt.readback_valid
        or not receipt.current_selected
        or receipt.disposition in {PersistDisposition.CONFLICT, PersistDisposition.FAILED}
    ):
        return _hold_projection(
            receipt.aggregate_ref, "aggregate receipt is not persisted/readback current"
        )
    try:
        reread = store.read_result(receipt.aggregate_ref)
        if reread != result.to_dict():
            return _hold_projection(receipt.aggregate_ref, "aggregate changed after persistence")
        if store.current_ref(result) != receipt.aggregate_ref:
            return _hold_projection(receipt.aggregate_ref, "aggregate is no longer current")
        projected = _projector_callable(projector)(result=result, receipt=receipt)
        projected_mapping = _as_mapping(projected, label="projection result")
        status = ProjectionStatus(str(projected_mapping.get("status") or ""))
        writer_receipts = projected_mapping.get("writer_receipts") or {}
        if not isinstance(writer_receipts, Mapping):
            raise ValueError("projection writer_receipts must be an object")
        return ProjectionReceipt(
            status=status,
            called=True,
            aggregate_ref=receipt.aggregate_ref,
            writer_receipts=MappingProxyType(dict(writer_receipts)),
            retryable=status is not ProjectionStatus.COMPLETE,
            error=str(projected_mapping.get("error") or ""),
        )
    except (KeyError, OSError, TypeError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        return ProjectionReceipt(
            status=ProjectionStatus.FAILED,
            called=True,
            aggregate_ref=receipt.aggregate_ref,
            writer_receipts=MappingProxyType({}),
            retryable=True,
            error=str(exc),
        )


def coordinate_aggregate(
    request: AggregateRequest,
    handles: Sequence[Any],
    *,
    reader: LegResultReader | Callable[[str], Any],
    store: AggregateStore | None = None,
    projector: AggregateProjector | Callable[..., Mapping[str, Any]] | None = None,
    expected_current_ref: str | None = None,
    dry_run: bool = False,
    project: bool = False,
) -> AggregateCommandResult:
    validation = validate_published_leg_results(request, handles, reader=reader)
    if not validation.ok or validation.validated is None:
        blocked = blocked_from_validation(validation.errors)
        return AggregateCommandResult(
            overall=blocked.overall,
            validation_errors=validation.errors,
            aggregate_result=None,
            write_receipt=None,
            projection_receipt=None,
            dry_run=dry_run,
            next_route=blocked.next_route,
        )
    result = compute_aggregate(validation.validated)
    if dry_run:
        return AggregateCommandResult(
            overall=result.overall,
            validation_errors=(),
            aggregate_result=result,
            write_receipt=None,
            projection_receipt=None,
            dry_run=True,
            next_route=result.next_route,
        )
    if store is None:
        raise ValueError("aggregate store is required unless dry_run=true")
    write_receipt = persist_aggregate(
        result,
        store,
        expected_current_ref=expected_current_ref,
    )
    if write_receipt.disposition in {PersistDisposition.CONFLICT, PersistDisposition.FAILED}:
        return AggregateCommandResult(
            overall=AggregateStatus.BLOCKED,
            validation_errors=(),
            aggregate_result=result,
            write_receipt=write_receipt,
            projection_receipt=None,
            dry_run=False,
            next_route="resolve-persistence-conflict-or-retry",
        )
    projection_receipt: ProjectionReceipt | None = None
    next_route = result.next_route
    if project:
        if projector is None:
            raise ValueError("projector is required when project=true")
        projection_receipt = project_if_eligible(
            result,
            write_receipt,
            store=store,
            projector=projector,
        )
        if projection_receipt.status in {ProjectionStatus.PARTIAL, ProjectionStatus.FAILED}:
            next_route = "retry-controlled-projection"
        elif projection_receipt.status is ProjectionStatus.HOLD:
            next_route = result.next_route
        else:
            next_route = "continue-workflow-after-projection"
    elif result.projection_decision is ProjectionDecision.ELIGIBLE:
        next_route = "await-explicit-controlled-projection"
    return AggregateCommandResult(
        overall=result.overall,
        validation_errors=(),
        aggregate_result=result,
        write_receipt=write_receipt,
        projection_receipt=projection_receipt,
        dry_run=False,
        next_route=next_route,
    )


__all__ = [
    "AggregateRequest",
    "AggregateResult",
    "AggregateStatus",
    "AggregateCommandResult",
    "AggregateWriteReceipt",
    "FileAggregateStore",
    "InMemoryAggregateStore",
    "PersistDisposition",
    "ProjectionDecision",
    "ProjectionReceipt",
    "ProjectionStatus",
    "ProjectFileLegResultReader",
    "ValidatedLegSet",
    "ValidatedPublishedLegResult",
    "ValidationBlockedDecision",
    "ValidationCode",
    "ValidationError",
    "ValidationOutcome",
    "blocked_from_validation",
    "canonical_json_digest",
    "canonical_leg_receipt_digest",
    "compute_aggregate",
    "coordinate_aggregate",
    "derive_leg_single_write_key",
    "persist_aggregate",
    "project_if_eligible",
    "validate_published_leg_results",
]
