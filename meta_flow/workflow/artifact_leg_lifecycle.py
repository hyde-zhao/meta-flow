"""异构 source-default / artifact-integration Git leg 生命周期。

本模块提供不可变 schema、mode-specific target policy、typed authorization、
fresh observation / ``WorktreeHealth`` 校验、受限 Git 执行、单写结果发布，
以及 resume / abort 恢复入口。默认时钟会在每个观察端口返回后重新采样，
确保端口刚生成的快照可通过 freshness 校验；显式 ``now`` 仍保持确定性语义。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, fields, is_dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from threading import Lock
from typing import Any, Protocol

from meta_flow.workflow.artifact_policy import (
    ARTIFACT_MODE,
    SOURCE_MODE,
    is_protected_artifact_ref,
)
from meta_flow.workflow.artifact_policy import (
    canonical_artifact_active_ref as _policy_artifact_active_ref,
)
from meta_flow.workflow.artifact_policy import (
    canonical_artifact_integration_ref as _policy_artifact_integration_ref,
)
from meta_flow.workflow.artifact_policy import (
    canonical_source_active_ref as _policy_source_active_ref,
)
from meta_flow.workspace.git_sync import GitCommandResult, run_git
from meta_flow.workspace.project_worktree import (
    UnknownValue,
    WorktreeHealth,
    WorktreeObservation,
    build_worktree_observation,
)

SCHEMA_VERSION = 1
LEG_KINDS = {"source", "artifact"}
OPERATIONS = {"open", "publish", "complete", "finish", "resume", "abort"}
PROGRESS_VALUES = {"NONE", "PLANNED", "STARTED", "PARTIAL", "COMPLETE"}
EFFECT_VALUES = {"NONE", "LOCAL_ONLY", "REMOTE_PARTIAL", "TARGET_UPDATED", "UNKNOWN"}
RESULT_STATUS_VALUES = {"BLOCKED", "FAIL", "IN_PROGRESS", "PASS"}

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_SAFE_PROJECT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SAFE_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_CR_ID = re.compile(r"^CR-[0-9]+$")
_OID = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_REF_COMPONENT_FORBIDDEN = {".", ".."}
_PAYLOAD_FORBIDDEN_FIELDS = {
    "append_receipt",
    "receipt",
    "receipt_digest",
    "result_ref",
    "write_receipt",
    "writer_id",
    "written_at",
}


class LegLifecycleError(ValueError):
    """带稳定错误码的 fail-closed 校验错误。"""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail[:500]


@dataclass(frozen=True)
class LegCorrelation:
    operation_id: str
    logical_attempt: int
    cr_id: str
    project_id: str
    leg_kind: str


@dataclass(frozen=True)
class LegRequest:
    schema_version: int
    operation_id: str
    logical_attempt: int
    cr_id: str
    project_id: str
    slug: str
    leg_kind: str
    mode: str
    operation: str
    base_ref: str
    target_ref: str
    expected_base_oid: str
    expected_target_oid: str
    authorization_ref: str
    route_config_digest: str
    worktree_health_digest: str
    dry_run: bool
    resume_from_attempt: int | None = None
    resume_operation: str | None = None

    @property
    def correlation(self) -> LegCorrelation:
        return LegCorrelation(
            operation_id=self.operation_id,
            logical_attempt=self.logical_attempt,
            cr_id=self.cr_id,
            project_id=self.project_id,
            leg_kind=self.leg_kind,
        )


@dataclass(frozen=True)
class LegRouteProof:
    project_id: str
    mode: str
    repository_root: Path
    repository_fingerprint: str
    remote: str
    route_config_digest: str
    source_default_ref: str
    owned_target: bool


@dataclass(frozen=True)
class LegTarget:
    repository_root: Path
    repository_fingerprint: str
    remote: str
    base_ref: str
    target_ref: str
    active_ref: str
    mode: str


@dataclass(frozen=True)
class LegObservation:
    schema_version: int
    repository_fingerprint: str
    base_ref: str
    target_ref: str
    active_ref: str
    base_oid: str
    target_oid: str
    active_oid: str
    head_oid: str
    observed_at: datetime
    dirty: bool
    staged: bool
    untracked: bool
    git_operation: str
    observation_digest: str


@dataclass(frozen=True)
class LegAuthorization:
    authorization_id: str
    action: str
    correlation: LegCorrelation
    mode: str
    repository_fingerprint: str
    remote: str
    base_ref: str
    target_ref: str
    active_ref: str
    expected_base_oid: str
    expected_target_oid: str
    issued_at: datetime
    expires_at: datetime
    single_use: bool = True


@dataclass(frozen=True)
class LegPlanStep:
    step_id: str
    phase: str
    argv: tuple[str, ...]
    cwd_role: str
    before_oid: str
    expected_after_oid: str
    precondition: str
    mutation_scope: str


@dataclass(frozen=True)
class LegPlan:
    schema_version: int
    request: LegRequest
    target: LegTarget
    observation: LegObservation
    authorization: LegAuthorization | None
    authorization_id: str
    worktree_health_digest: str
    dry_run: bool
    steps: tuple[LegPlanStep, ...]
    plan_digest: str


@dataclass(frozen=True)
class LegPreparationOutcome:
    status: str
    code: str
    detail: str


@dataclass(frozen=True)
class LegBlocker:
    code: str
    detail: str


@dataclass(frozen=True)
class StepReceipt:
    step_id: str
    argv_digest: str
    returncode: int
    before_oid: str
    expected_oid: str
    after_oid: str
    mutation: bool
    effect: str
    started_at: str
    completed_at: str
    error: str = ""


@dataclass(frozen=True)
class LegResultPayload:
    schema_version: int
    correlation: LegCorrelation
    operation: str
    mode: str
    base_ref: str
    target_ref: str
    active_ref: str
    expected_base_oid: str
    expected_target_oid: str
    observed_base_oid_before: str
    observed_target_oid_before: str
    observed_active_oid_before: str
    observed_base_oid_after: str
    observed_target_oid_after: str
    observed_active_oid_after: str
    status: str
    terminal: bool
    progress: str
    effect: str
    step_receipts: tuple[StepReceipt, ...]
    blockers: tuple[LegBlocker, ...]
    resume_route: str
    abort_route: str
    fresh_observed_at: str
    payload_digest: str


@dataclass(frozen=True)
class LegResultWriteReceipt:
    result_ref: str
    payload_digest: str
    writer_id: str
    written_at: str
    receipt_digest: str


@dataclass(frozen=True)
class PublishedLegResultHandle:
    schema_version: int
    single_write_key: str
    result_ref: str
    payload_digest: str
    receipt: LegResultWriteReceipt
    correlation: LegCorrelation
    mode: str


@dataclass(frozen=True)
class ExpectedPublishedLegResult:
    correlation: LegCorrelation
    mode: str


@dataclass(frozen=True)
class UnpublishedLegResultOutcome:
    payload: LegResultPayload
    single_write_key: str
    error_code: str
    error_detail: str
    recovery_route: str = "evidence-only-retry"


@dataclass(frozen=True)
class ValidatedPublishedLegResult:
    handle: PublishedLegResultHandle
    payload: LegResultPayload


@dataclass(frozen=True)
class LegExecutionOutcome:
    plan: LegPlan | None
    payload: LegResultPayload
    published_handle: PublishedLegResultHandle | None
    unpublished: UnpublishedLegResultOutcome | None
    mutation_count: int


class LegResultWriter(Protocol):
    def append(self, single_write_key: str, payload: LegResultPayload) -> LegResultWriteReceipt: ...


class LegResultReader(Protocol):
    def read(self, result_ref: str) -> LegResultPayload | Mapping[str, Any]: ...


LegObserver = Callable[[LegTarget], LegObservation]
WorktreeHealthObserver = Callable[[LegTarget], WorktreeHealth]
GitRunner = Callable[[list[str], Path], GitCommandResult]


def _canonical_value(value: object) -> object:
    if isinstance(value, Path):
        return value.resolve().as_posix()
    if isinstance(value, datetime):
        normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return normalized.astimezone(UTC).isoformat(timespec="microseconds")
    if is_dataclass(value):
        return {str(key): _canonical_value(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _canonical_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_canonical_value(item) for item in value]
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def derive_single_write_key(correlation: LegCorrelation) -> str:
    """由五元 correlation 派生稳定 single-write key。"""

    return _digest(
        {
            "operation_id": correlation.operation_id,
            "logical_attempt": correlation.logical_attempt,
            "cr_id": correlation.cr_id,
            "project_id": correlation.project_id,
            "leg_kind": correlation.leg_kind,
        }
    )


def payload_to_dict(payload: LegResultPayload, *, include_digest: bool = True) -> dict[str, Any]:
    """把 payload 转为 canonical-friendly dict，不引入外置 receipt 字段。"""

    result = _canonical_value(payload)
    if not isinstance(result, dict):  # pragma: no cover - dataclass contract
        raise TypeError("payload serialization must produce an object")
    forbidden = _PAYLOAD_FORBIDDEN_FIELDS.intersection(result)
    if forbidden:
        raise LegLifecycleError(
            "payload_forbidden_field",
            f"payload contains append-time fields: {', '.join(sorted(forbidden))}",
        )
    if not include_digest:
        result.pop("payload_digest", None)
    return result


def canonical_payload_digest(payload: LegResultPayload) -> str:
    """计算写前 payload digest；排除 digest 字段自身，消除自引用。"""

    return _digest(payload_to_dict(payload, include_digest=False))


def canonical_receipt_digest(
    single_write_key: str,
    *,
    result_ref: str,
    payload_digest: str,
    writer_id: str,
    written_at: str,
) -> str:
    """计算外置 receipt digest；不包含 receipt_digest 自身。"""

    return _digest(
        {
            "single_write_key": single_write_key,
            "result_ref": result_ref,
            "payload_digest": payload_digest,
            "writer_id": writer_id,
            "written_at": written_at,
        }
    )


def payload_from_dict(raw: Mapping[str, Any]) -> LegResultPayload:
    """从外部 evidence 读取严格 payload schema。"""

    payload = dict(raw)
    forbidden = _PAYLOAD_FORBIDDEN_FIELDS.intersection(payload)
    if forbidden:
        raise LegLifecycleError(
            "payload_forbidden_field",
            f"payload contains append-time fields: {', '.join(sorted(forbidden))}",
        )
    expected_fields = {item.name for item in fields(LegResultPayload)}
    if set(payload) != expected_fields:
        raise LegLifecycleError("payload_schema_invalid", "payload field set is not canonical")
    correlation_raw = payload.get("correlation")
    if not isinstance(correlation_raw, Mapping):
        raise LegLifecycleError("payload_schema_invalid", "payload correlation must be an object")
    try:
        correlation = LegCorrelation(
            operation_id=str(correlation_raw["operation_id"]),
            logical_attempt=int(correlation_raw["logical_attempt"]),
            cr_id=str(correlation_raw["cr_id"]),
            project_id=str(correlation_raw["project_id"]),
            leg_kind=str(correlation_raw["leg_kind"]),
        )
        receipts_raw = payload.get("step_receipts")
        blockers_raw = payload.get("blockers")
        if not isinstance(receipts_raw, (list, tuple)) or not isinstance(
            blockers_raw, (list, tuple)
        ):
            raise TypeError("receipts and blockers must be arrays")
        receipts = tuple(StepReceipt(**dict(item)) for item in receipts_raw)
        blockers = tuple(LegBlocker(**dict(item)) for item in blockers_raw)
        result = LegResultPayload(
            schema_version=int(payload["schema_version"]),
            correlation=correlation,
            operation=str(payload["operation"]),
            mode=str(payload["mode"]),
            base_ref=str(payload["base_ref"]),
            target_ref=str(payload["target_ref"]),
            active_ref=str(payload["active_ref"]),
            expected_base_oid=str(payload["expected_base_oid"]),
            expected_target_oid=str(payload["expected_target_oid"]),
            observed_base_oid_before=str(payload["observed_base_oid_before"]),
            observed_target_oid_before=str(payload["observed_target_oid_before"]),
            observed_active_oid_before=str(payload["observed_active_oid_before"]),
            observed_base_oid_after=str(payload["observed_base_oid_after"]),
            observed_target_oid_after=str(payload["observed_target_oid_after"]),
            observed_active_oid_after=str(payload["observed_active_oid_after"]),
            status=str(payload["status"]),
            terminal=bool(payload["terminal"]),
            progress=str(payload["progress"]),
            effect=str(payload["effect"]),
            step_receipts=receipts,
            blockers=blockers,
            resume_route=str(payload["resume_route"]),
            abort_route=str(payload["abort_route"]),
            fresh_observed_at=str(payload["fresh_observed_at"]),
            payload_digest=str(payload["payload_digest"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise LegLifecycleError("payload_schema_invalid", "payload values are invalid") from exc
    _validate_result_payload(result)
    return result


def seal_leg_result_payload(payload: LegResultPayload) -> LegResultPayload:
    """为 immutable payload 填入写前 digest，并验证状态不变量。"""

    sealed = replace(payload, payload_digest=canonical_payload_digest(payload))
    _validate_result_payload(sealed)
    return sealed


def publish_leg_payload(
    single_write_key: str,
    payload: LegResultPayload,
    writer: LegResultWriter,
) -> PublishedLegResultHandle | UnpublishedLegResultOutcome:
    """append immutable payload once，并把 receipt 保持在 payload 外部。"""

    expected_key = derive_single_write_key(payload.correlation)
    if single_write_key != expected_key:
        return UnpublishedLegResultOutcome(
            payload=payload,
            single_write_key=single_write_key,
            error_code="single_write_key_mismatch",
            error_detail="single-write key does not match payload correlation",
        )
    try:
        _validate_result_payload(payload)
        receipt = writer.append(single_write_key, payload)
        _validate_write_receipt(single_write_key, payload, receipt)
    except LegLifecycleError as exc:
        return UnpublishedLegResultOutcome(
            payload=payload,
            single_write_key=single_write_key,
            error_code=exc.code,
            error_detail=exc.detail,
        )
    except Exception as exc:  # evidence port failure must not erase Git facts
        return UnpublishedLegResultOutcome(
            payload=payload,
            single_write_key=single_write_key,
            error_code="result_unpublished",
            error_detail=str(exc)[:500] or "result writer failed",
        )
    return PublishedLegResultHandle(
        schema_version=SCHEMA_VERSION,
        single_write_key=single_write_key,
        result_ref=receipt.result_ref,
        payload_digest=payload.payload_digest,
        receipt=receipt,
        correlation=payload.correlation,
        mode=payload.mode,
    )


def retry_unpublished_payload(
    outcome: UnpublishedLegResultOutcome,
    writer: LegResultWriter,
) -> PublishedLegResultHandle | UnpublishedLegResultOutcome:
    """只重试 evidence append；不接受 runner，因此不能重复 Git。"""

    return publish_leg_payload(outcome.single_write_key, outcome.payload, writer)


def validate_published_leg_result(
    handle: PublishedLegResultHandle,
    expected: ExpectedPublishedLegResult | LegCorrelation,
    *,
    reader: LegResultReader,
) -> ValidatedPublishedLegResult:
    """从 ``result_ref`` 重读并验证 payload/receipt/key/correlation/mode。"""

    if handle.schema_version != SCHEMA_VERSION:
        raise LegLifecycleError("published_handle_invalid", "handle schema is unsupported")
    expected_correlation = (
        expected.correlation if isinstance(expected, ExpectedPublishedLegResult) else expected
    )
    expected_mode = (
        expected.mode if isinstance(expected, ExpectedPublishedLegResult) else handle.mode
    )
    expected_key = derive_single_write_key(expected_correlation)
    if handle.correlation != expected_correlation or handle.mode != expected_mode:
        raise LegLifecycleError(
            "correlation_mismatch", "published handle correlation/mode mismatch"
        )
    if handle.single_write_key != expected_key:
        raise LegLifecycleError("single_write_key_mismatch", "published handle key mismatch")
    if handle.result_ref != handle.receipt.result_ref:
        raise LegLifecycleError("result_ref_mismatch", "handle and receipt result_ref mismatch")
    if handle.payload_digest != handle.receipt.payload_digest:
        raise LegLifecycleError(
            "payload_digest_mismatch", "handle and receipt payload digest mismatch"
        )
    try:
        raw = reader.read(handle.result_ref)
    except Exception as exc:
        raise LegLifecycleError(
            "result_ref_unreadable", "published payload cannot be reread"
        ) from exc
    payload = raw if isinstance(raw, LegResultPayload) else payload_from_dict(raw)
    _validate_result_payload(payload)
    if payload.correlation != expected_correlation or payload.mode != expected_mode:
        raise LegLifecycleError("correlation_mismatch", "reread payload correlation/mode mismatch")
    if payload.payload_digest != handle.payload_digest:
        raise LegLifecycleError("payload_digest_mismatch", "reread payload digest mismatch")
    _validate_write_receipt(handle.single_write_key, payload, handle.receipt)
    return ValidatedPublishedLegResult(handle=handle, payload=payload)


class InMemoryLegResultStore:
    """仅供单元测试/临时 fixture 的线程安全 external evidence store。"""

    def __init__(
        self,
        *,
        writer_id: str = "fixture-writer",
        now: Callable[[], datetime] | None = None,
    ) -> None:
        _validate_identifier(writer_id, "writer_id")
        self.writer_id = writer_id
        self._now = now or (lambda: datetime.now(UTC))
        self._lock = Lock()
        self._by_key: dict[str, tuple[LegResultPayload, LegResultWriteReceipt]] = {}
        self._by_ref: dict[str, LegResultPayload] = {}
        self.append_count = 0

    def append(self, single_write_key: str, payload: LegResultPayload) -> LegResultWriteReceipt:
        _validate_digest(single_write_key, "single_write_key")
        _validate_result_payload(payload)
        with self._lock:
            existing = self._by_key.get(single_write_key)
            if existing is not None:
                existing_payload, receipt = existing
                if existing_payload.payload_digest != payload.payload_digest:
                    raise LegLifecycleError(
                        "result_conflict", "single-write key already has a different payload"
                    )
                return receipt
            result_ref = f"memory://leg-results/{single_write_key}"
            written_at = _ensure_aware_utc(self._now(), "writer now").isoformat(
                timespec="microseconds"
            )
            receipt = LegResultWriteReceipt(
                result_ref=result_ref,
                payload_digest=payload.payload_digest,
                writer_id=self.writer_id,
                written_at=written_at,
                receipt_digest=canonical_receipt_digest(
                    single_write_key,
                    result_ref=result_ref,
                    payload_digest=payload.payload_digest,
                    writer_id=self.writer_id,
                    written_at=written_at,
                ),
            )
            self._by_key[single_write_key] = (payload, receipt)
            self._by_ref[result_ref] = payload
            self.append_count += 1
            return receipt

    def read(self, result_ref: str) -> LegResultPayload:
        with self._lock:
            try:
                return self._by_ref[result_ref]
            except KeyError as exc:
                raise LegLifecycleError("result_ref_unreadable", "unknown result_ref") from exc


def canonical_artifact_integration_ref(project_id: str) -> str:
    _validate_project_id(project_id)
    return _policy_artifact_integration_ref(project_id)


def canonical_artifact_active_ref(project_id: str, cr_id: str, slug: str) -> str:
    _validate_project_id(project_id)
    _validate_cr_id(cr_id)
    _validate_slug(slug)
    return _policy_artifact_active_ref(project_id, cr_id, slug)


def canonical_source_active_ref(cr_id: str, slug: str) -> str:
    _validate_cr_id(cr_id)
    _validate_slug(slug)
    return _policy_source_active_ref(cr_id, slug)


def build_leg_observation(
    *,
    repository_fingerprint: str,
    base_ref: str,
    target_ref: str,
    active_ref: str,
    base_oid: str,
    target_oid: str,
    active_oid: str,
    head_oid: str,
    observed_at: datetime,
    dirty: bool,
    staged: bool,
    untracked: bool,
    git_operation: str,
) -> LegObservation:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "repository_fingerprint": repository_fingerprint,
        "base_ref": base_ref,
        "target_ref": target_ref,
        "active_ref": active_ref,
        "base_oid": base_oid,
        "target_oid": target_oid,
        "active_oid": active_oid,
        "head_oid": head_oid,
        "observed_at": observed_at,
        "dirty": dirty,
        "staged": staged,
        "untracked": untracked,
        "git_operation": git_operation,
    }
    return LegObservation(**payload, observation_digest=_digest(payload))


def build_leg_plan(
    request: LegRequest,
    route: LegRouteProof,
    observation: LegObservation,
    *,
    authorization: LegAuthorization | None = None,
    worktree_health: WorktreeHealth | None = None,
    now: datetime | None = None,
    max_observation_age_seconds: int = 300,
) -> LegPlan | LegPreparationOutcome:
    """校验 request/route/fresh proof 并生成受限 Git 执行计划。

    任何失败都返回 stable ``BLOCKED`` outcome，调用方不得在该结果后调用
    mutation adapter；计划中的 argv 仍会在执行前接受安全边界复核。
    """

    evaluated_at = _ensure_aware_utc(now or datetime.now(UTC), "now")
    try:
        _validate_request(request)
        target = _resolve_target(request, route)
        _validate_leg_observation(
            request,
            target,
            observation,
            now=evaluated_at,
            max_age_seconds=max_observation_age_seconds,
        )
        health_digest = _validate_worktree_health(
            request,
            target,
            worktree_health,
            now=evaluated_at,
            max_age_seconds=max_observation_age_seconds,
        )
        _validate_authorization(request, target, authorization, evaluated_at)
        steps = _build_plan_steps(request, target, observation)
        plan_core = {
            "schema_version": SCHEMA_VERSION,
            "request": request,
            "target": target,
            "observation_digest": observation.observation_digest,
            "authorization": authorization,
            "authorization_id": authorization.authorization_id if authorization else "",
            "worktree_health_digest": health_digest,
            "dry_run": request.dry_run,
            "steps": steps,
        }
        return LegPlan(
            schema_version=SCHEMA_VERSION,
            request=request,
            target=target,
            observation=observation,
            authorization=authorization,
            authorization_id=authorization.authorization_id if authorization else "",
            worktree_health_digest=health_digest,
            dry_run=request.dry_run,
            steps=steps,
            plan_digest=_digest(plan_core),
        )
    except LegLifecycleError as exc:
        return LegPreparationOutcome(status="BLOCKED", code=exc.code, detail=exc.detail)


def _build_plan_steps(
    request: LegRequest,
    target: LegTarget,
    observation: LegObservation,
) -> tuple[LegPlanStep, ...]:
    operation = request.resume_operation if request.operation == "resume" else request.operation
    if operation == "abort":
        return ()
    if operation == "open":
        source_oid = observation.base_oid
        destination_ref = target.active_ref
        before_oid = observation.active_oid
        expected_after_oid = source_oid
    elif operation == "publish":
        source_oid = observation.head_oid
        destination_ref = target.active_ref
        before_oid = observation.active_oid
        expected_after_oid = source_oid
    elif operation == "complete":
        if not observation.active_oid:
            raise LegLifecycleError(
                "active_ref_missing", "complete requires a fresh active ref OID"
            )
        source_oid = observation.active_oid
        destination_ref = target.target_ref
        before_oid = observation.target_oid
        expected_after_oid = source_oid
    elif operation == "finish":
        if not observation.active_oid:
            raise LegLifecycleError("active_ref_missing", "finish requires a fresh active ref OID")
        if observation.target_oid != observation.active_oid:
            raise LegLifecycleError(
                "cleanup_containment_unproven",
                "finish requires fresh integration target OID to equal the CR tip",
            )
        source_oid = ""
        destination_ref = target.active_ref
        before_oid = observation.active_oid
        expected_after_oid = ""
    else:  # pragma: no cover - request validation owns the operation enum
        raise LegLifecycleError("invalid_input", "operation is not plannable")
    refspec = f"{source_oid}:{destination_ref}"
    argv = (
        (
            "git",
            "push",
            f"--force-with-lease={destination_ref}:{before_oid}",
            target.remote,
            refspec,
        )
        if operation == "finish"
        else ("git", "push", target.remote, refspec)
    )
    return (
        LegPlanStep(
            step_id=f"{operation}-remote-ref",
            phase=operation,
            argv=argv,
            cwd_role="current-leg-worktree",
            before_oid=before_oid,
            expected_after_oid=expected_after_oid,
            precondition=(
                f"fresh {destination_ref} == {before_oid or '<absent>'}; "
                f"source == {source_oid or '<delete>'}"
            ),
            mutation_scope=f"remote:{destination_ref}",
        ),
    )


def execute_leg(
    plan: LegPlan,
    *,
    observer: LegObserver,
    result_writer: LegResultWriter,
    runner: GitRunner | None = None,
    health_observer: WorktreeHealthObserver | None = None,
    now: datetime | None = None,
    max_observation_age_seconds: int = 300,
) -> LegExecutionOutcome:
    """执行单个 leg；从不观察、关闭或回滚另一条 leg。"""

    executed_at = _ensure_aware_utc(now or datetime.now(UTC), "now")
    if plan.dry_run:
        payload = _build_result_payload(
            plan,
            before=plan.observation,
            after=plan.observation,
            status="IN_PROGRESS",
            terminal=False,
            progress="PLANNED",
            effect="NONE",
            receipts=(),
            blockers=(),
            resume_route="execute-with-fresh-authz",
            observed_at=plan.observation.observed_at,
        )
        return LegExecutionOutcome(
            plan=plan,
            payload=payload,
            published_handle=None,
            unpublished=None,
            mutation_count=0,
        )
    git_runner = runner or _default_git_runner
    try:
        _validate_authorization(plan.request, plan.target, plan.authorization, executed_at)
        before = observer(plan.target)
        validation_at = (
            executed_at if now is not None else _ensure_aware_utc(datetime.now(UTC), "now")
        )
        _validate_leg_observation(
            plan.request,
            plan.target,
            before,
            now=validation_at,
            max_age_seconds=max_observation_age_seconds,
        )
        if not _same_observation_facts(plan.observation, before):
            raise LegLifecycleError("stale_observation", "leg facts drifted after planning")
        if plan.request.leg_kind == "artifact":
            if health_observer is None:
                raise LegLifecycleError(
                    "worktree_health_missing", "artifact execution requires fresh health observer"
                )
            health = health_observer(plan.target)
            health_validation_at = (
                executed_at if now is not None else _ensure_aware_utc(datetime.now(UTC), "now")
            )
            _validate_worktree_health(
                plan.request,
                plan.target,
                health,
                now=health_validation_at,
                max_age_seconds=max_observation_age_seconds,
            )
    except Exception as exc:
        error = (
            exc
            if isinstance(exc, LegLifecycleError)
            else LegLifecycleError(
                "observation_failed", str(exc)[:500] or "fresh observation failed"
            )
        )
        before = plan.observation
        payload = _build_result_payload(
            plan,
            before=before,
            after=before,
            status="BLOCKED",
            terminal=True,
            progress="NONE",
            effect="NONE",
            receipts=(),
            blockers=(LegBlocker(error.code, error.detail),),
            resume_route="fresh-resume",
            observed_at=executed_at,
        )
        return _publish_execution(plan, payload, result_writer, mutation_count=0)

    receipts: list[StepReceipt] = []
    mutation_count = 0
    after = before
    status = "PASS"
    effect = "NONE"
    blockers: tuple[LegBlocker, ...] = ()
    for step in plan.steps:
        _validate_safe_step(plan, step)
        started_at = executed_at.isoformat(timespec="microseconds")
        result = git_runner(list(step.argv[1:]), plan.target.repository_root)
        mutation_count += 1
        try:
            after = observer(plan.target)
            post_validation_at = (
                executed_at if now is not None else _ensure_aware_utc(datetime.now(UTC), "now")
            )
            _validate_post_observation(
                plan.target,
                after,
                now=post_validation_at,
                max_age_seconds=max_observation_age_seconds,
            )
            after_oid = _observed_oid_for_ref(after, step.mutation_scope.removeprefix("remote:"))
            post_matches = result.ok and after_oid == step.expected_after_oid
        except Exception:
            after = before
            after_oid = ""
            post_matches = False
        if post_matches:
            effect = (
                "TARGET_UPDATED"
                if step.mutation_scope == f"remote:{plan.target.target_ref}"
                else "REMOTE_PARTIAL"
            )
            receipt_error = ""
        else:
            status = "FAIL"
            effect = "UNKNOWN" if result.ok else _effect_from_observation(before, after)
            code = "post_proof_mismatch" if result.ok else "git_command_failed"
            detail = (
                "fresh post-observation does not prove the expected OID"
                if result.ok
                else _bounded_git_detail(result)
            )
            blockers = (LegBlocker(code, detail),)
            receipt_error = detail
        receipts.append(
            StepReceipt(
                step_id=step.step_id,
                argv_digest=_digest(step.argv),
                returncode=result.returncode,
                before_oid=step.before_oid,
                expected_oid=step.expected_after_oid,
                after_oid=after_oid,
                mutation=True,
                effect=effect,
                started_at=started_at,
                completed_at=executed_at.isoformat(timespec="microseconds"),
                error=receipt_error[:500],
            )
        )
        if status == "FAIL":
            break
    payload = _build_result_payload(
        plan,
        before=before,
        after=after,
        status=status,
        terminal=True,
        progress="COMPLETE" if status == "PASS" else "PARTIAL",
        effect=effect,
        receipts=tuple(receipts),
        blockers=blockers,
        resume_route="none" if status == "PASS" else "fresh-resume",
        observed_at=after.observed_at,
    )
    return _publish_execution(plan, payload, result_writer, mutation_count=mutation_count)


def resume_leg(
    request: LegRequest,
    previous: LegResultPayload | UnpublishedLegResultOutcome,
    *,
    result_writer: LegResultWriter,
    route: LegRouteProof | None = None,
    observation: LegObservation | None = None,
    authorization: LegAuthorization | None = None,
    worktree_health: WorktreeHealth | None = None,
    observer: LegObserver | None = None,
    health_observer: WorktreeHealthObserver | None = None,
    runner: GitRunner | None = None,
    now: datetime | None = None,
) -> LegExecutionOutcome:
    """恢复普通 attempt，或对 unpublished payload 做 evidence-only retry。"""

    if isinstance(previous, UnpublishedLegResultOutcome):
        if request.correlation != previous.payload.correlation:
            raise LegLifecycleError(
                "correlation_mismatch", "evidence-only retry must keep the original correlation"
            )
        published = retry_unpublished_payload(previous, result_writer)
        return LegExecutionOutcome(
            plan=None,
            payload=previous.payload,
            published_handle=(
                published if isinstance(published, PublishedLegResultHandle) else None
            ),
            unpublished=(published if isinstance(published, UnpublishedLegResultOutcome) else None),
            mutation_count=0,
        )
    _validate_resume_request(request, previous)
    if route is None or observation is None or observer is None:
        raise LegLifecycleError(
            "resume_context_missing", "ordinary resume requires fresh route/observation ports"
        )
    planned = build_leg_plan(
        request,
        route,
        observation,
        authorization=authorization,
        worktree_health=worktree_health,
        now=now,
    )
    if isinstance(planned, LegPreparationOutcome):
        raise LegLifecycleError(planned.code, planned.detail)
    return execute_leg(
        planned,
        observer=observer,
        result_writer=result_writer,
        runner=runner,
        health_observer=health_observer,
        now=now,
    )


def abort_leg(
    request: LegRequest,
    previous: LegResultPayload,
    *,
    result_writer: LegResultWriter,
    now: datetime | None = None,
) -> LegExecutionOutcome:
    """只追加协调态 abort evidence；Git mutation 和跨 leg 调用恒为零。"""

    aborted_at = _ensure_aware_utc(now or datetime.now(UTC), "now")
    _validate_result_payload(previous)
    if request.operation != "abort":
        raise LegLifecycleError("invalid_input", "abort_leg requires operation=abort")
    if (
        request.operation_id != previous.correlation.operation_id
        or request.cr_id != previous.correlation.cr_id
        or request.project_id != previous.correlation.project_id
        or request.leg_kind != previous.correlation.leg_kind
        or request.mode != previous.mode
        or request.logical_attempt <= previous.correlation.logical_attempt
        or request.resume_from_attempt != previous.correlation.logical_attempt
    ):
        raise LegLifecycleError(
            "correlation_mismatch", "abort request does not follow previous attempt"
        )
    raw = LegResultPayload(
        schema_version=SCHEMA_VERSION,
        correlation=request.correlation,
        operation="abort",
        mode=previous.mode,
        base_ref=previous.base_ref,
        target_ref=previous.target_ref,
        active_ref=previous.active_ref,
        expected_base_oid=request.expected_base_oid,
        expected_target_oid=request.expected_target_oid,
        observed_base_oid_before=previous.observed_base_oid_after,
        observed_target_oid_before=previous.observed_target_oid_after,
        observed_active_oid_before=previous.observed_active_oid_after,
        observed_base_oid_after=previous.observed_base_oid_after,
        observed_target_oid_after=previous.observed_target_oid_after,
        observed_active_oid_after=previous.observed_active_oid_after,
        status="FAIL",
        terminal=True,
        progress=previous.progress,
        effect=previous.effect,
        step_receipts=previous.step_receipts,
        blockers=(*previous.blockers, LegBlocker("aborted", "coordination aborted without Git")),
        resume_route="manual-review",
        abort_route="aborted-coordination-only",
        fresh_observed_at=aborted_at.isoformat(timespec="microseconds"),
        payload_digest="",
    )
    payload = seal_leg_result_payload(raw)
    return _publish_execution(None, payload, result_writer, mutation_count=0)


def _validate_request(request: LegRequest) -> None:
    if request.schema_version != SCHEMA_VERSION:
        raise LegLifecycleError("schema_unsupported", "LegRequest schema_version must be 1")
    _validate_identifier(request.operation_id, "operation_id")
    if not isinstance(request.logical_attempt, int) or request.logical_attempt < 1:
        raise LegLifecycleError("invalid_input", "logical_attempt must be a positive integer")
    _validate_cr_id(request.cr_id)
    _validate_project_id(request.project_id)
    _validate_slug(request.slug)
    if request.leg_kind not in LEG_KINDS:
        raise LegLifecycleError("invalid_input", "leg_kind must be source or artifact")
    if request.operation not in OPERATIONS:
        raise LegLifecycleError("invalid_input", "operation is not supported")
    expected_mode = SOURCE_MODE if request.leg_kind == "source" else ARTIFACT_MODE
    if request.mode != expected_mode:
        raise LegLifecycleError(
            "mode_mismatch", "leg_kind and mode must use the frozen 1:1 mapping"
        )
    _validate_ref(request.base_ref, "base_ref")
    _validate_ref(request.target_ref, "target_ref")
    _validate_oid(request.expected_base_oid, "expected_base_oid")
    _validate_oid(request.expected_target_oid, "expected_target_oid")
    _validate_digest(request.route_config_digest, "route_config_digest")
    if request.worktree_health_digest:
        _validate_digest(request.worktree_health_digest, "worktree_health_digest")
    if request.authorization_ref:
        _validate_identifier(request.authorization_ref, "authorization_ref")
    if request.operation == "resume":
        if request.resume_from_attempt is None or request.resume_from_attempt < 1:
            raise LegLifecycleError(
                "invalid_input", "resume requires a positive resume_from_attempt"
            )
        if request.resume_from_attempt >= request.logical_attempt:
            raise LegLifecycleError(
                "invalid_input", "resume logical_attempt must be newer than the previous attempt"
            )
        if request.resume_operation not in {"open", "publish", "complete", "finish"}:
            raise LegLifecycleError(
                "invalid_input", "resume_operation must identify the fresh replan"
            )


def _resolve_target(request: LegRequest, route: LegRouteProof) -> LegTarget:
    _validate_project_id(route.project_id)
    _validate_identifier(route.repository_fingerprint, "repository_fingerprint")
    _validate_remote(route.remote)
    _validate_digest(route.route_config_digest, "route_config_digest")
    if route.project_id != request.project_id:
        raise LegLifecycleError("route_identity_mismatch", "route project does not match request")
    if route.mode != request.mode:
        raise LegLifecycleError("route_mode_mismatch", "route mode does not match request")
    if route.route_config_digest != request.route_config_digest:
        raise LegLifecycleError(
            "route_digest_mismatch", "route config digest does not match request"
        )
    if not route.owned_target:
        raise LegLifecycleError("route_ownership_mismatch", "route target is not owned")
    if request.leg_kind == "source":
        base_ref = _validate_ref(route.source_default_ref, "source_default_ref")
        target_ref = base_ref
        active_ref = canonical_source_active_ref(request.cr_id, request.slug)
        if request.base_ref != base_ref or request.target_ref != target_ref:
            raise LegLifecycleError(
                "policy_target_mismatch",
                "source request must assert the fresh route source-default ref",
            )
    else:
        base_ref = canonical_artifact_integration_ref(request.project_id)
        target_ref = base_ref
        active_ref = canonical_artifact_active_ref(request.project_id, request.cr_id, request.slug)
        if request.base_ref != base_ref or request.target_ref != target_ref:
            if _is_protected_artifact_ref(request.base_ref) or _is_protected_artifact_ref(
                request.target_ref
            ):
                raise LegLifecycleError(
                    "policy_target_forbidden",
                    "artifact base/target cannot resolve to main/default/control refs",
                )
            raise LegLifecycleError(
                "policy_target_mismatch",
                "artifact request must assert the project integration ref",
            )
    return LegTarget(
        repository_root=route.repository_root.resolve(),
        repository_fingerprint=route.repository_fingerprint,
        remote=route.remote,
        base_ref=base_ref,
        target_ref=target_ref,
        active_ref=active_ref,
        mode=request.mode,
    )


def _validate_leg_observation(
    request: LegRequest,
    target: LegTarget,
    observation: LegObservation,
    *,
    now: datetime,
    max_age_seconds: int,
) -> None:
    if observation.schema_version != SCHEMA_VERSION:
        raise LegLifecycleError("observation_invalid", "leg observation schema is unsupported")
    rebuilt = build_leg_observation(
        repository_fingerprint=observation.repository_fingerprint,
        base_ref=observation.base_ref,
        target_ref=observation.target_ref,
        active_ref=observation.active_ref,
        base_oid=observation.base_oid,
        target_oid=observation.target_oid,
        active_oid=observation.active_oid,
        head_oid=observation.head_oid,
        observed_at=observation.observed_at,
        dirty=observation.dirty,
        staged=observation.staged,
        untracked=observation.untracked,
        git_operation=observation.git_operation,
    )
    if rebuilt.observation_digest != observation.observation_digest:
        raise LegLifecycleError("observation_digest_mismatch", "leg observation digest mismatch")
    if observation.repository_fingerprint != target.repository_fingerprint:
        raise LegLifecycleError("route_identity_mismatch", "observation repository mismatch")
    if (
        observation.base_ref != target.base_ref
        or observation.target_ref != target.target_ref
        or observation.active_ref != target.active_ref
    ):
        raise LegLifecycleError(
            "policy_target_mismatch", "fresh observation ref set mismatches policy"
        )
    for label, value in (
        ("base_oid", observation.base_oid),
        ("target_oid", observation.target_oid),
        ("active_oid", observation.active_oid),
        ("head_oid", observation.head_oid),
    ):
        _validate_oid(value, label, allow_empty=label == "active_oid")
    if (
        observation.base_oid != request.expected_base_oid
        or observation.target_oid != request.expected_target_oid
    ):
        raise LegLifecycleError("stale_observation", "expected OID mismatches fresh observation")
    if observation.dirty or observation.staged or observation.untracked:
        raise LegLifecycleError("worktree_dirty", "current leg worktree is dirty")
    if observation.git_operation != "NONE":
        raise LegLifecycleError("worktree_git_operation_active", "Git operation is active")
    _validate_freshness(
        observation.observed_at,
        now=now,
        max_age_seconds=max_age_seconds,
        code="stale_observation",
    )


def _validate_worktree_health(
    request: LegRequest,
    target: LegTarget,
    health: WorktreeHealth | None,
    *,
    now: datetime,
    max_age_seconds: int,
) -> str:
    if request.leg_kind == "source":
        if request.worktree_health_digest:
            raise LegLifecycleError(
                "worktree_health_unexpected", "source leg must not bind artifact worktree health"
            )
        return ""
    if health is None:
        raise LegLifecycleError("worktree_health_missing", "artifact leg requires WorktreeHealth")
    if health.project_id != request.project_id:
        raise LegLifecycleError(
            "worktree_identity_mismatch", "health project does not match request"
        )
    if health.decision != "HEALTHY":
        raise LegLifecycleError(
            "worktree_health_not_healthy",
            f"health decision is {health.decision or 'UNKNOWN'}",
        )
    nested = health.observation
    if nested is None:
        raise LegLifecycleError(
            "worktree_observation_missing", "HEALTHY health requires nested observation"
        )
    if not health.observation_digest or health.observation_digest != nested.observation_digest:
        raise LegLifecycleError(
            "worktree_observation_digest_mismatch",
            "health wrapper digest does not match nested observation",
        )
    if request.worktree_health_digest != health.observation_digest:
        raise LegLifecycleError(
            "worktree_observation_digest_mismatch",
            "request health digest does not match fresh health wrapper",
        )
    rebuilt = _rebuild_worktree_observation(nested)
    if rebuilt.observation_digest != nested.observation_digest:
        raise LegLifecycleError(
            "worktree_observation_digest_mismatch", "nested observation digest is invalid"
        )
    identity = nested.identity
    if (
        identity.project_id != request.project_id
        or identity.repository_fingerprint != target.repository_fingerprint
        or identity.target_path.resolve() != target.repository_root
        or identity.integration_ref != target.target_ref
    ):
        raise LegLifecycleError(
            "worktree_identity_mismatch", "nested observation identity/ownership mismatch"
        )
    if nested.route_config_digest != request.route_config_digest:
        raise LegLifecycleError(
            "worktree_route_digest_mismatch", "nested observation route digest mismatch"
        )
    if nested.dirty is not False or nested.staged is not False or nested.untracked is not False:
        raise LegLifecycleError("worktree_dirty", "current artifact worktree is dirty")
    if nested.git_operation != "NONE":
        raise LegLifecycleError("worktree_git_operation_active", "artifact Git operation is active")
    if nested.registry_state != "CONSISTENT":
        raise LegLifecycleError("worktree_registry_invalid", "artifact registry is inconsistent")
    if nested.role not in {"ACTIVE_CR", "IDLE_INTEGRATION"}:
        raise LegLifecycleError("worktree_role_invalid", "artifact worktree role is invalid")
    expected_head_ref = target.active_ref if nested.role == "ACTIVE_CR" else target.target_ref
    if not isinstance(nested.head_ref, str) or nested.head_ref != expected_head_ref:
        raise LegLifecycleError("worktree_identity_mismatch", "artifact HEAD ref mismatches role")
    if isinstance(nested.head_oid, UnknownValue) or isinstance(
        nested.integration_oid, UnknownValue
    ):
        raise LegLifecycleError("worktree_observation_incomplete", "artifact OID proof is unknown")
    if nested.integration_oid != request.expected_target_oid:
        raise LegLifecycleError("worktree_oid_stale", "artifact integration OID is stale")
    if health.active_operation_id is not None:
        raise LegLifecycleError("worktree_operation_active", "worktree operation is active")
    if health.journal_state not in {"IDLE", "VERIFIED_TARGET", "VERIFIED_ORIGINAL"}:
        raise LegLifecycleError("worktree_journal_invalid", "worktree journal is not terminal")
    _validate_freshness(
        nested.observed_at,
        now=now,
        max_age_seconds=max_age_seconds,
        code="worktree_observation_stale",
    )
    return health.observation_digest


def _validate_authorization(
    request: LegRequest,
    target: LegTarget,
    authorization: LegAuthorization | None,
    now: datetime,
) -> None:
    if authorization is None:
        if request.dry_run:
            return
        raise LegLifecycleError(
            "authorization_missing", "non-dry-run leg requires typed authorization"
        )
    if not request.authorization_ref or authorization.authorization_id != request.authorization_ref:
        raise LegLifecycleError("authorization_mismatch", "authorization_ref mismatch")
    _validate_identifier(authorization.authorization_id, "authorization_id")
    if (
        authorization.action != request.operation
        or authorization.correlation != request.correlation
        or authorization.mode != request.mode
        or authorization.repository_fingerprint != target.repository_fingerprint
        or authorization.remote != target.remote
        or authorization.base_ref != target.base_ref
        or authorization.target_ref != target.target_ref
        or authorization.active_ref != target.active_ref
        or authorization.expected_base_oid != request.expected_base_oid
        or authorization.expected_target_oid != request.expected_target_oid
        or authorization.single_use is not True
    ):
        raise LegLifecycleError(
            "authorization_mismatch",
            "authorization action/repo/target/OID/correlation binding mismatch",
        )
    issued_at = _ensure_aware_utc(authorization.issued_at, "authorization issued_at")
    expires_at = _ensure_aware_utc(authorization.expires_at, "authorization expires_at")
    if issued_at > now or expires_at <= now or expires_at <= issued_at:
        raise LegLifecycleError("authorization_expired", "authorization is not currently valid")


def _validate_result_payload(payload: LegResultPayload) -> None:
    if payload.schema_version != SCHEMA_VERSION:
        raise LegLifecycleError("payload_schema_invalid", "payload schema is unsupported")
    _validate_identifier(payload.correlation.operation_id, "operation_id")
    if payload.correlation.logical_attempt < 1:
        raise LegLifecycleError("payload_schema_invalid", "payload attempt must be positive")
    _validate_cr_id(payload.correlation.cr_id)
    _validate_project_id(payload.correlation.project_id)
    if payload.correlation.leg_kind not in LEG_KINDS:
        raise LegLifecycleError("payload_schema_invalid", "payload leg_kind is invalid")
    if payload.operation not in OPERATIONS:
        raise LegLifecycleError("payload_schema_invalid", "payload operation is invalid")
    expected_mode = SOURCE_MODE if payload.correlation.leg_kind == "source" else ARTIFACT_MODE
    if payload.mode != expected_mode:
        raise LegLifecycleError("payload_schema_invalid", "payload mode/leg mismatch")
    _validate_ref(payload.base_ref, "payload base_ref")
    _validate_ref(payload.target_ref, "payload target_ref")
    _validate_ref(payload.active_ref, "payload active_ref")
    for label, value in (
        ("expected_base_oid", payload.expected_base_oid),
        ("expected_target_oid", payload.expected_target_oid),
        ("observed_base_oid_before", payload.observed_base_oid_before),
        ("observed_target_oid_before", payload.observed_target_oid_before),
        ("observed_active_oid_before", payload.observed_active_oid_before),
        ("observed_base_oid_after", payload.observed_base_oid_after),
        ("observed_target_oid_after", payload.observed_target_oid_after),
        ("observed_active_oid_after", payload.observed_active_oid_after),
    ):
        _validate_oid(value, label, allow_empty="active_oid" in label)
    if payload.status not in RESULT_STATUS_VALUES:
        raise LegLifecycleError("payload_schema_invalid", "payload status is invalid")
    if payload.progress not in PROGRESS_VALUES or payload.effect not in EFFECT_VALUES:
        raise LegLifecycleError("payload_schema_invalid", "payload progress/effect is invalid")
    if payload.status == "IN_PROGRESS" and payload.terminal:
        raise LegLifecycleError("payload_schema_invalid", "IN_PROGRESS cannot be terminal")
    if payload.status != "IN_PROGRESS" and not payload.terminal:
        raise LegLifecycleError("payload_schema_invalid", "terminal status must set terminal=true")
    if payload.status == "PASS":
        if payload.progress != "COMPLETE" or payload.blockers:
            raise LegLifecycleError(
                "payload_schema_invalid", "PASS requires COMPLETE progress and zero blockers"
            )
        if not payload.step_receipts or any(
            receipt.returncode != 0 or receipt.after_oid != receipt.expected_oid
            for receipt in payload.step_receipts
        ):
            raise LegLifecycleError(
                "payload_schema_invalid", "PASS requires successful fresh step receipts"
            )
    for receipt in payload.step_receipts:
        _validate_identifier(receipt.step_id, "step_id")
        _validate_digest(receipt.argv_digest, "argv_digest")
        _validate_oid(receipt.before_oid, "receipt before_oid", allow_empty=True)
        _validate_oid(receipt.expected_oid, "receipt expected_oid", allow_empty=True)
        _validate_oid(receipt.after_oid, "receipt after_oid", allow_empty=True)
        if receipt.effect not in EFFECT_VALUES or not isinstance(receipt.mutation, bool):
            raise LegLifecycleError("payload_schema_invalid", "step receipt effect is invalid")
        if len(receipt.error) > 500:
            raise LegLifecycleError("payload_schema_invalid", "step receipt error is unbounded")
        _parse_timestamp(receipt.started_at, "step started_at")
        _parse_timestamp(receipt.completed_at, "step completed_at")
    for blocker in payload.blockers:
        _validate_identifier(blocker.code, "blocker code")
        if not blocker.detail or len(blocker.detail) > 500:
            raise LegLifecycleError("payload_schema_invalid", "blocker detail is invalid")
    _parse_timestamp(payload.fresh_observed_at, "fresh_observed_at")
    if payload.payload_digest:
        _validate_digest(payload.payload_digest, "payload_digest")
        if payload.payload_digest != canonical_payload_digest(payload):
            raise LegLifecycleError("payload_digest_mismatch", "payload digest is invalid")
    else:
        raise LegLifecycleError(
            "payload_digest_missing", "payload must be sealed before publication"
        )


def _validate_write_receipt(
    single_write_key: str,
    payload: LegResultPayload,
    receipt: LegResultWriteReceipt,
) -> None:
    if (
        not receipt.result_ref
        or any(char in receipt.result_ref for char in "\x00\r\n")
        or receipt.payload_digest != payload.payload_digest
    ):
        raise LegLifecycleError("receipt_mismatch", "receipt fields do not match payload")
    _validate_identifier(receipt.writer_id, "writer_id")
    _parse_timestamp(receipt.written_at, "written_at")
    expected_digest = canonical_receipt_digest(
        single_write_key,
        result_ref=receipt.result_ref,
        payload_digest=receipt.payload_digest,
        writer_id=receipt.writer_id,
        written_at=receipt.written_at,
    )
    if receipt.receipt_digest != expected_digest:
        raise LegLifecycleError("receipt_mismatch", "receipt digest mismatch")


def _build_result_payload(
    plan: LegPlan,
    *,
    before: LegObservation,
    after: LegObservation,
    status: str,
    terminal: bool,
    progress: str,
    effect: str,
    receipts: tuple[StepReceipt, ...],
    blockers: tuple[LegBlocker, ...],
    resume_route: str,
    observed_at: datetime,
) -> LegResultPayload:
    raw = LegResultPayload(
        schema_version=SCHEMA_VERSION,
        correlation=plan.request.correlation,
        operation=plan.request.operation,
        mode=plan.request.mode,
        base_ref=plan.target.base_ref,
        target_ref=plan.target.target_ref,
        active_ref=plan.target.active_ref,
        expected_base_oid=plan.request.expected_base_oid,
        expected_target_oid=plan.request.expected_target_oid,
        observed_base_oid_before=before.base_oid,
        observed_target_oid_before=before.target_oid,
        observed_active_oid_before=before.active_oid,
        observed_base_oid_after=after.base_oid,
        observed_target_oid_after=after.target_oid,
        observed_active_oid_after=after.active_oid,
        status=status,
        terminal=terminal,
        progress=progress,
        effect=effect,
        step_receipts=receipts,
        blockers=blockers,
        resume_route=resume_route,
        abort_route="coordination-only",
        fresh_observed_at=_ensure_aware_utc(observed_at, "observed_at").isoformat(
            timespec="microseconds"
        ),
        payload_digest="",
    )
    return seal_leg_result_payload(raw)


def _publish_execution(
    plan: LegPlan | None,
    payload: LegResultPayload,
    writer: LegResultWriter,
    *,
    mutation_count: int,
) -> LegExecutionOutcome:
    publication = publish_leg_payload(derive_single_write_key(payload.correlation), payload, writer)
    return LegExecutionOutcome(
        plan=plan,
        payload=payload,
        published_handle=(
            publication if isinstance(publication, PublishedLegResultHandle) else None
        ),
        unpublished=(publication if isinstance(publication, UnpublishedLegResultOutcome) else None),
        mutation_count=mutation_count,
    )


def _validate_resume_request(request: LegRequest, previous: LegResultPayload) -> None:
    _validate_request(request)
    _validate_result_payload(previous)
    if request.operation != "resume":
        raise LegLifecycleError("invalid_input", "ordinary resume requires operation=resume")
    if (
        request.operation_id != previous.correlation.operation_id
        or request.cr_id != previous.correlation.cr_id
        or request.project_id != previous.correlation.project_id
        or request.leg_kind != previous.correlation.leg_kind
        or request.mode != previous.mode
        or request.logical_attempt <= previous.correlation.logical_attempt
        or request.resume_from_attempt != previous.correlation.logical_attempt
    ):
        raise LegLifecycleError("correlation_mismatch", "resume does not follow previous attempt")


def _validate_post_observation(
    target: LegTarget,
    observation: LegObservation,
    *,
    now: datetime,
    max_age_seconds: int,
) -> None:
    rebuilt = build_leg_observation(
        repository_fingerprint=observation.repository_fingerprint,
        base_ref=observation.base_ref,
        target_ref=observation.target_ref,
        active_ref=observation.active_ref,
        base_oid=observation.base_oid,
        target_oid=observation.target_oid,
        active_oid=observation.active_oid,
        head_oid=observation.head_oid,
        observed_at=observation.observed_at,
        dirty=observation.dirty,
        staged=observation.staged,
        untracked=observation.untracked,
        git_operation=observation.git_operation,
    )
    if rebuilt.observation_digest != observation.observation_digest:
        raise LegLifecycleError("observation_digest_mismatch", "post observation digest mismatch")
    if (
        observation.repository_fingerprint != target.repository_fingerprint
        or observation.base_ref != target.base_ref
        or observation.target_ref != target.target_ref
        or observation.active_ref != target.active_ref
    ):
        raise LegLifecycleError("route_identity_mismatch", "post observation identity/ref mismatch")
    for label, value in (
        ("base_oid", observation.base_oid),
        ("target_oid", observation.target_oid),
        ("active_oid", observation.active_oid),
        ("head_oid", observation.head_oid),
    ):
        _validate_oid(value, label, allow_empty=label == "active_oid")
    if observation.dirty or observation.staged or observation.untracked:
        raise LegLifecycleError("worktree_dirty", "post observation worktree is dirty")
    if observation.git_operation != "NONE":
        raise LegLifecycleError("worktree_git_operation_active", "post Git operation is active")
    _validate_freshness(
        observation.observed_at,
        now=now,
        max_age_seconds=max_age_seconds,
        code="stale_observation",
    )


def _same_observation_facts(left: LegObservation, right: LegObservation) -> bool:
    return (
        replace(left, observed_at=right.observed_at, observation_digest=right.observation_digest)
        == right
    )


def _observed_oid_for_ref(observation: LegObservation, ref: str) -> str:
    if ref == observation.base_ref and ref == observation.target_ref:
        return observation.target_oid
    if ref == observation.target_ref:
        return observation.target_oid
    if ref == observation.active_ref:
        return observation.active_oid
    raise LegLifecycleError("post_proof_mismatch", "step ref is outside the current leg")


def _effect_from_observation(before: LegObservation, after: LegObservation) -> str:
    if _same_observation_facts(before, after):
        return "NONE"
    if before.target_oid != after.target_oid:
        return "TARGET_UPDATED"
    if before.active_oid != after.active_oid:
        return "REMOTE_PARTIAL"
    return "UNKNOWN"


def _validate_safe_step(plan: LegPlan, step: LegPlanStep) -> None:
    is_finish = step.phase == "finish"
    if is_finish:
        expected_lease = (
            f"--force-with-lease={plan.target.active_ref}:{plan.observation.active_oid}"
        )
        if (
            len(step.argv) != 5
            or step.argv[:2] != ("git", "push")
            or step.argv[2] != expected_lease
            or step.argv[3] != plan.target.remote
        ):
            raise LegLifecycleError(
                "unsafe_plan",
                "finish cleanup requires an exact expected-OID lease",
            )
        refspec = step.argv[4]
    else:
        if len(step.argv) != 4 or step.argv[:3] != ("git", "push", plan.target.remote):
            raise LegLifecycleError("unsafe_plan", "only one exact git push argv is allowed")
        refspec = step.argv[3]
    if refspec.count(":") != 1:
        raise LegLifecycleError("unsafe_plan", "push refspec must be exact")
    source_oid, destination_ref = refspec.split(":", 1)
    if is_finish and (
        source_oid
        or destination_ref != plan.target.active_ref
        or step.before_oid != plan.observation.active_oid
        or step.expected_after_oid != ""
    ):
        raise LegLifecycleError(
            "unsafe_plan",
            "finish cleanup may delete only the exact active CR ref",
        )
    if source_oid:
        _validate_oid(source_oid, "push source OID")
    _validate_ref(destination_ref, "push destination ref")
    if destination_ref not in {plan.target.active_ref, plan.target.target_ref}:
        raise LegLifecycleError("unsafe_plan", "push destination is outside the current leg")
    forbidden = {"--force", "reset", "clean", "stash", "rebase"}
    if any(token in forbidden for token in step.argv):
        raise LegLifecycleError("unsafe_plan", "destructive recovery argv is forbidden")
    lease_tokens = [token for token in step.argv if token.startswith("--force-with-lease")]
    if lease_tokens and (not is_finish or lease_tokens != [step.argv[2]]):
        raise LegLifecycleError("unsafe_plan", "lease is allowed only for exact finish cleanup")


def _default_git_runner(args: list[str], cwd: Path) -> GitCommandResult:
    return run_git(args, cwd=cwd)


def _bounded_git_detail(result: GitCommandResult) -> str:
    raw = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
    return raw.replace("\n", " ")[:500]


def _rebuild_worktree_observation(observation: WorktreeObservation) -> WorktreeObservation:
    return build_worktree_observation(
        identity=observation.identity,
        observed_at=observation.observed_at,
        route_config_digest=observation.route_config_digest,
        worktree_state=observation.worktree_state,
        head_ref=observation.head_ref,
        head_oid=observation.head_oid,
        integration_oid=observation.integration_oid,
        dirty=observation.dirty,
        staged=observation.staged,
        untracked=observation.untracked,
        git_operation=observation.git_operation,
        registry_state=observation.registry_state,
        role=observation.role,
    )


def _validate_identifier(value: str, label: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value) or value.startswith("-"):
        raise LegLifecycleError("invalid_input", f"{label} must be a safe non-option token")
    return value


def _validate_project_id(value: str) -> str:
    if (
        not isinstance(value, str)
        or not _SAFE_PROJECT.fullmatch(value)
        or value.startswith("-")
        or ".." in value
    ):
        raise LegLifecycleError("invalid_input", "project_id must be a safe non-option token")
    return value.lower()


def _validate_cr_id(value: str) -> str:
    if not isinstance(value, str) or not _CR_ID.fullmatch(value):
        raise LegLifecycleError("invalid_input", "cr_id must use CR-<digits>")
    return value


def _validate_slug(value: str) -> str:
    if not isinstance(value, str) or not _SAFE_SLUG.fullmatch(value):
        raise LegLifecycleError("invalid_input", "slug must be lowercase kebab-case")
    return value


def _validate_ref(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.startswith("refs/heads/") or value.startswith("-"):
        raise LegLifecycleError("invalid_input", f"{label} must be an exact heads ref")
    if any(char in value for char in "\x00\r\n ~^:?*[\\"):
        raise LegLifecycleError("invalid_input", f"{label} contains unsafe characters")
    if ".." in value or "@{" in value or "//" in value or value.endswith(("/", ".", ".lock")):
        raise LegLifecycleError("invalid_input", f"{label} is not a canonical ref")
    components = value.split("/")
    if any(
        component in _REF_COMPONENT_FORBIDDEN or component.startswith("-")
        for component in components
    ):
        raise LegLifecycleError("invalid_input", f"{label} contains an unsafe component")
    return value


def _validate_oid(value: str, label: str, *, allow_empty: bool = False) -> str:
    if allow_empty and value == "":
        return value
    if not isinstance(value, str) or not _OID.fullmatch(value):
        raise LegLifecycleError("invalid_input", f"{label} must be a lowercase full 40-char OID")
    return value


def _validate_digest(value: str, label: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise LegLifecycleError("invalid_input", f"{label} must be a lowercase SHA-256 digest")
    return value


def _validate_remote(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.startswith("-")
        or any(char in value for char in "\x00\r\n \t;&|`$<>")
    ):
        raise LegLifecycleError("invalid_input", "remote must be a safe argv token or fixture path")
    return value


def _validate_freshness(
    observed_at: datetime,
    *,
    now: datetime,
    max_age_seconds: int,
    code: str,
) -> None:
    observed = _ensure_aware_utc(observed_at, "observed_at")
    if max_age_seconds < 0:
        raise LegLifecycleError("invalid_input", "max_observation_age_seconds cannot be negative")
    age = (now - observed).total_seconds()
    if age < 0 or age > max_age_seconds:
        raise LegLifecycleError(code, "observation is outside the allowed freshness window")


def _ensure_aware_utc(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise LegLifecycleError("invalid_input", f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def _parse_timestamp(value: str, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise LegLifecycleError("payload_schema_invalid", f"{label} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LegLifecycleError(
            "payload_schema_invalid", f"{label} must be an ISO timestamp"
        ) from exc
    return _ensure_aware_utc(parsed, label)


def _is_protected_artifact_ref(ref: str) -> bool:
    return is_protected_artifact_ref(ref)
