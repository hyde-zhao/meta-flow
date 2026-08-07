"""只读、精确绑定的 legacy closed evidence sidecar provider。

本模块刻意不接入 formal CR、index、lifecycle 或 CLI。调用方必须显式提供
registration；模块不会发现、持久化或修改任何 registry / evidence。
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Final

from meta_flow.project.process_route import ProcessRouteError, require_process_route
from meta_flow.project.scale import load_yaml_object

SUPPORTED_SCHEMA_VERSION: Final = 1
EVIDENCE_KIND: Final = "legacy_closed_cr_evidence"
ALLOWED_OPERATIONS: Final = frozenset(
    {"inspect_evidence", "list_follow_ups", "get_follow_up"}
)
SUPPORTED_LEGACY_OUTCOMES: Final = frozenset(
    {
        ("closed", "PASS_WITH_RISK"),
        ("closed-pass-with-risk", "PASS_WITH_RISK"),
    }
)
_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID_RE: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*\Z")
_OUTCOME_FIELD_RE: Final = re.compile(r"(?mi)^\s*(?P<key>status|lifecycle|decision|outcome)\s*:\s*(?P<value>[^#\r\n]+?)\s*$")
_FIELD_RE: Final = re.compile(r"(?m)^\s*(?P<key>id|status|relationship)\s*:\s*(?P<value>[^#\r\n]+?)\s*$")
_FOLLOW_UP_ID_RE: Final = re.compile(r"(?m)^\s*(?:-\s*)?id\s*:\s*(?P<id>[A-Za-z0-9][A-Za-z0-9._:-]*)\s*$")


class LegacyEvidenceError(ValueError):
    """携带稳定 failure taxonomy 的 fail-closed 错误。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class LegacyEvidenceRegistration:
    """调用方显式注入的一条 exact-bound registration。"""

    schema_version: int
    registration_id: str
    project_id: str
    consumer_id: str
    evidence_kind: str
    evidence_logical_ref: str
    evidence_sha256: str
    follow_up_logical_ref: str
    follow_up_sha256: str
    expected_lifecycle: str
    expected_decision: str
    expected_follow_up_count: int
    expected_follow_up_ids: tuple[str, ...]
    expected_follow_up_statuses: tuple[tuple[str, str], ...]
    allowed_operations: frozenset[str]


@dataclass(frozen=True)
class LegacyFollowUpView:
    """已作为完整 evidence 验证的一部分读取的单个 follow-up。"""

    follow_up_id: str
    status: str
    relationship: str
    source_logical_ref: str
    source_anchor: str


@dataclass(frozen=True)
class LegacyEvidenceView:
    """不可变、明确非 formal 的 verified sidecar view。"""

    source_kind: str
    compatibility_kind: str
    registration_id: str
    project_id: str
    consumer_id: str
    evidence_kind: str
    evidence_logical_ref: str
    evidence_sha256: str
    follow_up_logical_ref: str
    follow_up_sha256: str
    legacy_lifecycle: str
    legacy_decision: str
    lifecycle_view: str
    readiness_view: str
    gate_view: str
    follow_up_ids: tuple[str, ...]
    follow_ups: tuple[LegacyFollowUpView, ...]


@dataclass(frozen=True)
class DeclaredLegacyEvidenceRegistry:
    """由 PROJECT → active Phase → result_ref 显式声明的 registry。"""

    registry_logical_ref: str
    registry_sha256: str
    registrations: tuple[LegacyEvidenceRegistration, ...]
    evidence_paths: tuple[Path, ...]


def validate_legacy_evidence_registry(
    registrations: Iterable[LegacyEvidenceRegistration],
) -> tuple[LegacyEvidenceRegistration, ...]:
    """验证显式 registry；同一 project/consumer/ref 绝不采用 last-wins。"""

    items = tuple(registrations)
    keys: set[tuple[str, str, str]] = set()
    registration_ids: set[str] = set()
    for registration in items:
        _validate_registration(registration)
        key = (
            registration.project_id,
            registration.consumer_id,
            registration.evidence_logical_ref,
        )
        if key in keys or registration.registration_id in registration_ids:
            raise LegacyEvidenceError(
                "legacy_registry_conflict",
                "legacy evidence registry contains a duplicate exact registration",
            )
        keys.add(key)
        registration_ids.add(registration.registration_id)
    return items


def load_declared_legacy_evidence_registry(
    project_root: Path,
    *,
    consumer_id: str,
) -> DeclaredLegacyEvidenceRegistry:
    """加载 active Phase 明确声明的 consumer acceptance registry。

    只接受一个精确命名的 result ref；不扫描目录、不匹配 wildcard，也不从
    non-native CR 文件反向推断兼容资格。registry 中的每个 evidence/follow-up
    必须先通过 exact digest，再允许解析。
    """

    if not isinstance(consumer_id, str) or not _SAFE_ID_RE.fullmatch(consumer_id):
        raise LegacyEvidenceError("legacy_registry_invalid", "consumer_id is invalid")
    try:
        route = require_process_route(project_root)
        project_path = route.resolve_ref("process/PROJECT.yaml")
        project = load_yaml_object(project_path)
    except (OSError, ProcessRouteError, ValueError) as exc:
        raise LegacyEvidenceError("legacy_evidence_route_unavailable", str(exc)) from exc
    if str(project.get("project_id") or "") != route.project_id:
        raise LegacyEvidenceError(
            "legacy_evidence_project_mismatch",
            "PROJECT project_id does not match route project_id",
        )
    active_phase_ref = _normalize_declared_ref(str(project.get("active_phase_ref") or ""))
    if not active_phase_ref:
        return DeclaredLegacyEvidenceRegistry("", "", (), ())
    try:
        phase = load_yaml_object(route.resolve_ref(active_phase_ref))
    except (OSError, ProcessRouteError, ValueError) as exc:
        raise LegacyEvidenceError("legacy_evidence_route_unavailable", str(exc)) from exc
    if str(phase.get("project_id") or "") != route.project_id:
        raise LegacyEvidenceError(
            "legacy_evidence_project_mismatch",
            "active Phase project_id does not match route project_id",
        )
    result_refs = phase.get("result_refs")
    if result_refs is None:
        return DeclaredLegacyEvidenceRegistry("", "", (), ())
    if not isinstance(result_refs, list) or not all(
        isinstance(item, str) for item in result_refs
    ):
        raise LegacyEvidenceError(
            "legacy_registry_invalid", "active Phase result_refs must be a string list"
        )
    registry_refs = tuple(
        _normalize_declared_ref(item)
        for item in result_refs
        if Path(item).name == "CONSUMER-ACCEPTANCE-SPEC.yaml"
    )
    if not registry_refs:
        return DeclaredLegacyEvidenceRegistry("", "", (), ())
    if len(registry_refs) != 1:
        raise LegacyEvidenceError(
            "legacy_registry_conflict",
            "active Phase must declare at most one consumer acceptance registry",
        )
    registry_ref = registry_refs[0]
    try:
        registry_path = route.resolve_ref(registry_ref)
        registry_raw = registry_path.read_bytes()
        registry = load_yaml_object(registry_path)
    except (OSError, ProcessRouteError, ValueError) as exc:
        raise LegacyEvidenceError("legacy_evidence_route_unavailable", str(exc)) from exc
    registrations, evidence_paths = _registrations_from_consumer_spec(
        route=route,
        registry=registry,
        consumer_id=consumer_id,
    )
    return DeclaredLegacyEvidenceRegistry(
        registry_logical_ref=registry_ref,
        registry_sha256=sha256(registry_raw).hexdigest(),
        registrations=validate_legacy_evidence_registry(registrations),
        evidence_paths=tuple(evidence_paths),
    )


def query_declared_legacy_evidence(
    project_root: Path,
    *,
    query_id: str,
) -> dict[str, Any]:
    """按 exact CR/follow-up ID 查询已声明的 legacy sidecar lane。"""

    if not isinstance(query_id, str) or not _SAFE_ID_RE.fullmatch(query_id):
        raise LegacyEvidenceError("legacy_evidence_query_invalid", "query ID is invalid")
    bundle = load_declared_legacy_evidence_registry(
        project_root,
        consumer_id="cr-query",
    )
    for registration in bundle.registrations:
        cr_match = re.search(r"CR-\d+", registration.evidence_logical_ref)
        cr_id = cr_match.group(0) if cr_match else ""
        if query_id != cr_id and query_id not in registration.expected_follow_up_ids:
            continue
        view = inspect_registered_legacy_evidence(
            project_root,
            registration=registration,
            consumer_id="cr-query",
        )
        base = {
            "schema_version": 1,
            "decision": "PASS",
            "classification": "immutable_legacy_closed_evidence",
            "source_kind": view.source_kind,
            "compatibility_kind": view.compatibility_kind,
            "project_id": view.project_id,
            "query_id": query_id,
            "registry_ref": bundle.registry_logical_ref,
            "registry_sha256": bundle.registry_sha256,
            "evidence_ref": view.evidence_logical_ref,
            "evidence_sha256": view.evidence_sha256,
            "legacy_lifecycle": view.legacy_lifecycle,
            "legacy_decision": view.legacy_decision,
            "native_lifecycle_event_count": 0,
            "mutation_count": 0,
        }
        if query_id == cr_id:
            return {
                **base,
                "follow_up_ref": view.follow_up_logical_ref,
                "follow_up_sha256": view.follow_up_sha256,
                "follow_up_ids": list(view.follow_up_ids),
            }
        follow_up = get_registered_follow_up(view, follow_up_id=query_id)
        return {
            **base,
            "follow_up_ref": follow_up.source_logical_ref,
            "follow_up_sha256": view.follow_up_sha256,
            "follow_up_status": follow_up.status,
            "follow_up_relationship": follow_up.relationship,
            "source_anchor": follow_up.source_anchor,
        }
    raise LegacyEvidenceError(
        "legacy_evidence_not_registered",
        "query ID is not present in the declared exact registry",
    )


def _normalize_declared_ref(value: str) -> str:
    raw = value.strip()
    if not raw:
        return ""
    logical_ref = raw if raw.startswith("process/") else f"process/{raw}"
    _validate_logical_ref(logical_ref)
    return logical_ref


def _registrations_from_consumer_spec(
    *,
    route: Any,
    registry: dict[str, Any],
    consumer_id: str,
) -> tuple[list[LegacyEvidenceRegistration], list[Path]]:
    if (
        registry.get("schema_version") != 1
        or str(registry.get("project_id") or "") != route.project_id
        or str(registry.get("spec_status") or "") != "ready-for-provider-delivery"
    ):
        raise LegacyEvidenceError(
            "legacy_registry_invalid",
            "consumer acceptance registry identity or readiness is invalid",
        )
    spec_id = str(registry.get("spec_id") or "")
    if not _SAFE_ID_RE.fullmatch(spec_id):
        raise LegacyEvidenceError("legacy_registry_invalid", "registry spec_id is invalid")
    raw_inputs = registry.get("immutable_consumer_inputs")
    raw_fixtures = registry.get("fixture_contract")
    if not isinstance(raw_inputs, list) or not isinstance(raw_fixtures, list):
        raise LegacyEvidenceError(
            "legacy_registry_invalid",
            "registry immutable inputs and fixture contract must be lists",
        )
    inputs: dict[str, dict[str, Any]] = {}
    for item in raw_inputs:
        if not isinstance(item, dict):
            raise LegacyEvidenceError(
                "legacy_registry_invalid", "registry immutable input must be an object"
            )
        item_id = str(item.get("id") or "")
        if not _SAFE_ID_RE.fullmatch(item_id) or item_id in inputs:
            raise LegacyEvidenceError(
                "legacy_registry_conflict", "registry immutable input ID is invalid or duplicate"
            )
        inputs[item_id] = item
    follow_up_expectations: dict[str, dict[str, str]] = {}
    for fixture in raw_fixtures:
        if not isinstance(fixture, dict):
            continue
        source_id = str(fixture.get("source") or "")
        expected = fixture.get("expected")
        if not source_id or not isinstance(expected, dict):
            continue
        if source_id in follow_up_expectations:
            raise LegacyEvidenceError(
                "legacy_registry_conflict", "follow-up fixture source is declared more than once"
            )
        follow_up_expectations[source_id] = {
            str(item_id): str(status) for item_id, status in expected.items()
        }

    registrations: list[LegacyEvidenceRegistration] = []
    evidence_paths: list[Path] = []
    for body_id, body in inputs.items():
        match = re.fullmatch(r"(?P<compact>CR(?P<number>\d+))-BODY", body_id)
        if match is None:
            continue
        compact = match.group("compact")
        cr_id = f"CR-{match.group('number')}"
        follow_up_id = f"{compact}-FOLLOW-UPS"
        follow_up = inputs.get(follow_up_id)
        expected_statuses = follow_up_expectations.get(follow_up_id)
        if follow_up is None or not expected_statuses:
            raise LegacyEvidenceError(
                "legacy_registry_invalid",
                f"{body_id} lacks an exact follow-up input and status fixture",
            )
        evidence_ref = _normalize_declared_ref(str(body.get("ref") or ""))
        follow_up_ref = _normalize_declared_ref(str(follow_up.get("ref") or ""))
        if (
            not evidence_ref.startswith(f"process/changes/{cr_id}")
            or follow_up_ref != f"process/works/{cr_id}/FOLLOW-UPS.yaml"
        ):
            raise LegacyEvidenceError(
                "legacy_registry_invalid", "legacy evidence refs do not match their exact CR ID"
            )
        evidence_digest = str(body.get("sha256") or "")
        follow_up_digest = str(follow_up.get("sha256") or "")
        if not _SHA256_RE.fullmatch(evidence_digest) or not _SHA256_RE.fullmatch(
            follow_up_digest
        ):
            raise LegacyEvidenceError(
                "legacy_registry_invalid", "legacy evidence digests must be lowercase SHA-256"
            )
        try:
            evidence_path = route.resolve_ref(evidence_ref)
            follow_up_path = route.resolve_ref(follow_up_ref)
            evidence_raw = evidence_path.read_bytes()
            follow_up_raw = follow_up_path.read_bytes()
        except (OSError, ProcessRouteError) as exc:
            raise LegacyEvidenceError("legacy_evidence_route_unavailable", str(exc)) from exc
        if sha256(evidence_raw).hexdigest() != evidence_digest or sha256(
            follow_up_raw
        ).hexdigest() != follow_up_digest:
            raise LegacyEvidenceError(
                "legacy_evidence_digest_mismatch",
                "declared legacy evidence does not match the registry digest",
            )
        lifecycle, decision = _parse_legacy_outcome(evidence_raw)
        parsed_follow_ups = _parse_follow_ups(follow_up_raw, follow_up_ref)
        parsed_statuses = {item.follow_up_id: item.status for item in parsed_follow_ups}
        if parsed_statuses != expected_statuses:
            raise LegacyEvidenceError(
                "legacy_follow_up_query_failed",
                "follow-up IDs or statuses do not match the declared fixture",
            )
        registrations.append(
            LegacyEvidenceRegistration(
                schema_version=1,
                registration_id=f"{spec_id}-{compact.lower()}",
                project_id=route.project_id,
                consumer_id=consumer_id,
                evidence_kind=EVIDENCE_KIND,
                evidence_logical_ref=evidence_ref,
                evidence_sha256=evidence_digest,
                follow_up_logical_ref=follow_up_ref,
                follow_up_sha256=follow_up_digest,
                expected_lifecycle=lifecycle,
                expected_decision=decision,
                expected_follow_up_count=len(expected_statuses),
                expected_follow_up_ids=tuple(expected_statuses),
                expected_follow_up_statuses=tuple(expected_statuses.items()),
                allowed_operations=ALLOWED_OPERATIONS,
            )
        )
        evidence_paths.append(evidence_path.resolve())
    return registrations, evidence_paths


def inspect_registered_legacy_evidence(
    project_root: Path,
    *,
    registration: LegacyEvidenceRegistration,
    consumer_id: str,
) -> LegacyEvidenceView:
    """验证两份 raw source 后返回完整 immutable sidecar view。

    所有身份、operation 与 logical-ref 检查均发生在 route 或 target I/O 之前；
    两份 digest 都匹配之前不会调用任一 parser。
    """

    if registration is None:
        raise LegacyEvidenceError("legacy_evidence_not_registered", "registration is required")
    _validate_registration(registration)
    if consumer_id != registration.consumer_id:
        raise LegacyEvidenceError(
            "legacy_evidence_consumer_mismatch", "consumer_id does not match registration"
        )
    for operation in ("inspect_evidence", "list_follow_ups", "get_follow_up"):
        _require_operation(registration, operation)

    try:
        route = require_process_route(project_root)
    except ProcessRouteError as exc:
        raise LegacyEvidenceError("legacy_evidence_route_unavailable", str(exc)) from exc
    except Exception as exc:  # pragma: no cover - harness boundary
        raise LegacyEvidenceError("CHECK_HARNESS_ERROR", str(exc)) from exc

    if route.project_id != registration.project_id:
        raise LegacyEvidenceError(
            "legacy_evidence_project_mismatch", "route project_id does not match registration"
        )

    try:
        evidence_path = route.resolve_ref(registration.evidence_logical_ref)
        follow_up_path = route.resolve_ref(registration.follow_up_logical_ref)
    except ProcessRouteError as exc:
        raise LegacyEvidenceError("legacy_evidence_ref_invalid", str(exc)) from exc
    except Exception as exc:  # pragma: no cover - resolver harness boundary
        raise LegacyEvidenceError("CHECK_HARNESS_ERROR", str(exc)) from exc

    try:
        evidence_raw = evidence_path.read_bytes()
        follow_up_raw = follow_up_path.read_bytes()
    except OSError as exc:
        raise LegacyEvidenceError("legacy_evidence_route_unavailable", str(exc)) from exc
    except Exception as exc:  # pragma: no cover - unexpected read boundary
        raise LegacyEvidenceError("CHECK_HARNESS_ERROR", str(exc)) from exc

    if sha256(evidence_raw).hexdigest() != registration.evidence_sha256:
        raise LegacyEvidenceError(
            "legacy_evidence_digest_mismatch", "evidence raw bytes do not match registration digest"
        )
    if sha256(follow_up_raw).hexdigest() != registration.follow_up_sha256:
        raise LegacyEvidenceError(
            "legacy_evidence_digest_mismatch", "follow-up raw bytes do not match registration digest"
        )

    lifecycle, decision = _parse_legacy_outcome(evidence_raw)
    if (
        lifecycle != registration.expected_lifecycle
        or decision != registration.expected_decision
    ):
        raise LegacyEvidenceError(
            "legacy_evidence_outcome_mismatch", "legacy outcome does not match registration"
        )
    follow_ups = _parse_follow_ups(follow_up_raw, registration.follow_up_logical_ref)
    _validate_follow_ups(registration, follow_ups)

    return LegacyEvidenceView(
        source_kind="registered_legacy_evidence",
        compatibility_kind="registered_legacy_closed_evidence",
        registration_id=registration.registration_id,
        project_id=registration.project_id,
        consumer_id=registration.consumer_id,
        evidence_kind=registration.evidence_kind,
        evidence_logical_ref=registration.evidence_logical_ref,
        evidence_sha256=registration.evidence_sha256,
        follow_up_logical_ref=registration.follow_up_logical_ref,
        follow_up_sha256=registration.follow_up_sha256,
        legacy_lifecycle=lifecycle,
        legacy_decision=decision,
        lifecycle_view="closed",
        readiness_view="ready_with_risk",
        gate_view="closed",
        follow_up_ids=registration.expected_follow_up_ids,
        follow_ups=follow_ups,
    )


def list_registered_follow_ups(
    verified: LegacyEvidenceView,
) -> tuple[LegacyFollowUpView, ...]:
    """返回已整体验证的完整 follow-up 集合，绝不在这里重新读取 target。"""

    _validate_verified_view(verified)
    return verified.follow_ups


def get_registered_follow_up(
    verified: LegacyEvidenceView, *, follow_up_id: str
) -> LegacyFollowUpView:
    """仅以 exact ID 查询已验证集合；不作大小写、前缀或模糊匹配。"""

    _validate_verified_view(verified)
    for follow_up in verified.follow_ups:
        if follow_up.follow_up_id == follow_up_id:
            return follow_up
    raise LegacyEvidenceError("follow_up_not_found", "follow-up ID is not present in verified view")


def convert_to_formal_cr(_: LegacyEvidenceView) -> None:
    """明确拒绝把 sidecar view 转换为 native formal object。"""

    raise LegacyEvidenceError(
        "legacy_evidence_formal_conversion_unsupported",
        "registered legacy evidence cannot be converted to FormalCR or an index item",
    )


def _validate_registration(registration: LegacyEvidenceRegistration) -> None:
    if not isinstance(registration, LegacyEvidenceRegistration):
        raise LegacyEvidenceError("legacy_registry_invalid", "registration has an unsupported type")
    if registration.schema_version != SUPPORTED_SCHEMA_VERSION:
        raise LegacyEvidenceError("legacy_registry_invalid", "unsupported registration schema_version")
    if (
        isinstance(registration.expected_follow_up_count, bool)
        or not isinstance(registration.expected_follow_up_count, int)
        or not isinstance(registration.expected_follow_up_ids, tuple)
        or not isinstance(registration.expected_follow_up_statuses, tuple)
        or not isinstance(registration.allowed_operations, frozenset)
    ):
        raise LegacyEvidenceError("legacy_registry_invalid", "registration immutable field types are invalid")
    if not all(
        isinstance(value, str) and _SAFE_ID_RE.fullmatch(value)
        for value in (registration.registration_id, registration.project_id, registration.consumer_id)
    ):
        raise LegacyEvidenceError("legacy_registry_invalid", "registration identity fields are invalid")
    if registration.evidence_kind != EVIDENCE_KIND:
        raise LegacyEvidenceError("legacy_registry_invalid", "unsupported evidence_kind")
    _validate_logical_ref(registration.evidence_logical_ref)
    _validate_logical_ref(registration.follow_up_logical_ref)
    if not _SHA256_RE.fullmatch(registration.evidence_sha256) or not _SHA256_RE.fullmatch(
        registration.follow_up_sha256
    ):
        raise LegacyEvidenceError("legacy_registry_invalid", "SHA-256 digests must be lowercase hex")
    if (
        registration.expected_lifecycle,
        registration.expected_decision,
    ) not in SUPPORTED_LEGACY_OUTCOMES:
        raise LegacyEvidenceError("legacy_registry_invalid", "unsupported expected legacy outcome")
    if (
        registration.expected_follow_up_count < 0
        or registration.expected_follow_up_count != len(registration.expected_follow_up_ids)
        or registration.expected_follow_up_count
        != len(registration.expected_follow_up_statuses)
        or len(set(registration.expected_follow_up_ids)) != len(registration.expected_follow_up_ids)
        or not all(isinstance(item, str) and _SAFE_ID_RE.fullmatch(item) for item in registration.expected_follow_up_ids)
        or tuple(item_id for item_id, _status in registration.expected_follow_up_statuses)
        != registration.expected_follow_up_ids
        or not all(
            isinstance(status, str) and bool(status)
            for _item_id, status in registration.expected_follow_up_statuses
        )
    ):
        raise LegacyEvidenceError("legacy_registry_invalid", "follow-up count and IDs are not exact")
    if not registration.allowed_operations or not all(isinstance(item, str) for item in registration.allowed_operations) or not registration.allowed_operations <= ALLOWED_OPERATIONS:
        raise LegacyEvidenceError("legacy_registry_invalid", "registration operation allowlist is invalid")


def _validate_logical_ref(logical_ref: str) -> None:
    parts = logical_ref.split("/") if isinstance(logical_ref, str) else []
    if (
        len(parts) < 2
        or parts[0] != "process"
        or any(part in {"", ".", ".."} for part in parts)
        or any(character in logical_ref for character in ("\\", "*", "?", "[", "]", ":", "\x00"))
        or logical_ref.startswith("/")
    ):
        raise LegacyEvidenceError("legacy_evidence_ref_invalid", "logical ref must be canonical process/<relative>")


def _require_operation(registration: LegacyEvidenceRegistration, operation: str) -> None:
    if operation not in registration.allowed_operations:
        raise LegacyEvidenceError("legacy_evidence_operation_denied", f"operation denied: {operation}")


def _parse_legacy_outcome(raw: bytes) -> tuple[str, str]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LegacyEvidenceError("legacy_evidence_parse_failed", "evidence is not UTF-8") from exc
    fields: dict[str, list[str]] = {}
    for match in _OUTCOME_FIELD_RE.finditer(text):
        fields.setdefault(match.group("key"), []).append(match.group("value").strip())
    lifecycle_values = fields.get("status", []) + fields.get("lifecycle", [])
    decision_values = fields.get("decision", []) + fields.get("outcome", [])
    if lifecycle_values == ["closed-pass-with-risk"] and not decision_values:
        return "closed-pass-with-risk", "PASS_WITH_RISK"
    if len(lifecycle_values) != 1 or len(decision_values) != 1:
        raise LegacyEvidenceError(
            "legacy_evidence_parse_failed", "legacy closed/PASS_WITH_RISK outcome is not unambiguous"
        )
    return lifecycle_values[0], decision_values[0]


def _parse_follow_ups(raw: bytes, source_logical_ref: str) -> tuple[LegacyFollowUpView, ...]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LegacyEvidenceError("legacy_follow_up_query_failed", "follow-up source is not UTF-8") from exc
    id_matches = tuple(_FOLLOW_UP_ID_RE.finditer(text))
    if not id_matches:
        raise LegacyEvidenceError("legacy_follow_up_query_failed", "no stable follow-up IDs found")
    views: list[LegacyFollowUpView] = []
    for index, match in enumerate(id_matches):
        block_end = id_matches[index + 1].start() if index + 1 < len(id_matches) else len(text)
        block = text[match.start() : block_end]
        fields = {item.group("key"): item.group("value").strip() for item in _FIELD_RE.finditer(block)}
        follow_up_id = match.group("id")
        if fields.get("id", follow_up_id) != follow_up_id or not fields.get("status"):
            raise LegacyEvidenceError(
                "legacy_follow_up_query_failed", "follow-up lacks stable ID or status"
            )
        line_number = text.count("\n", 0, match.start()) + 1
        views.append(
            LegacyFollowUpView(
                follow_up_id=follow_up_id,
                status=fields["status"],
                relationship=fields.get("relationship", ""),
                source_logical_ref=source_logical_ref,
                source_anchor=f"line:{line_number}",
            )
        )
    return tuple(views)


def _validate_follow_ups(
    registration: LegacyEvidenceRegistration, follow_ups: tuple[LegacyFollowUpView, ...]
) -> None:
    ids = tuple(item.follow_up_id for item in follow_ups)
    statuses = tuple((item.follow_up_id, item.status) for item in follow_ups)
    if (
        len(ids) != registration.expected_follow_up_count
        or len(set(ids)) != len(ids)
        or frozenset(ids) != frozenset(registration.expected_follow_up_ids)
        or statuses != registration.expected_follow_up_statuses
    ):
        raise LegacyEvidenceError(
            "legacy_follow_up_query_failed",
            "follow-up count, exact ID set, order, or status does not match registration",
        )


def _validate_verified_view(verified: LegacyEvidenceView) -> None:
    if not isinstance(verified, LegacyEvidenceView) or (
        verified.source_kind != "registered_legacy_evidence"
        or verified.compatibility_kind != "registered_legacy_closed_evidence"
    ):
        raise LegacyEvidenceError("legacy_follow_up_query_failed", "view is not a verified legacy view")


__all__ = [
    "ALLOWED_OPERATIONS",
    "EVIDENCE_KIND",
    "SUPPORTED_SCHEMA_VERSION",
    "SUPPORTED_LEGACY_OUTCOMES",
    "LegacyEvidenceError",
    "LegacyEvidenceRegistration",
    "DeclaredLegacyEvidenceRegistry",
    "LegacyEvidenceView",
    "LegacyFollowUpView",
    "convert_to_formal_cr",
    "get_registered_follow_up",
    "inspect_registered_legacy_evidence",
    "load_declared_legacy_evidence_registry",
    "list_registered_follow_ups",
    "query_declared_legacy_evidence",
    "validate_legacy_evidence_registry",
]
