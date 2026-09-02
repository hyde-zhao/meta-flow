"""共享授权信封与 exactly-one resolver（CR-076 Feature A，STORY-CR076-S02）。

FA1 envelope 闭合校验；FA2 三源恰一解析（file/ref/id）；FA3 operation
payload registry（七 kind；publication/transport/observation 由 T4 的
publication_authorization 经 register_operation_payload 注册）；FA4/FA5 双
账本与 attempt 状态机（登记先于副作用，登记即消费，ADR-076-07）；FA6 11
项阻断枚举（全部 mutation=0、typed findings；退出码 2 由 CLI 层映射）。
exact_file_transaction 原语只 import 不修改。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# --- 常量与 11 项阻断枚举（FA6，冻结清单，权威 = Feature DESIGN 数据模型表） ---

ENVELOPE_SCHEMA_VERSION = 1
ENVELOPE_KIND = "authorization-envelope"
ENVELOPE_AUTHORIZATION_SOURCE = "typed-user-confirmation"

ENVELOPE_FIELDS: frozenset[str] = frozenset(
    "schema_version kind authorization_id operation target_refs plan_digest "
    "issued_at expires_at single_use authorization_source payload".split()
)

ENVELOPE_SOURCE_NOT_EXACTLY_ONE = "ENVELOPE_SOURCE_NOT_EXACTLY_ONE"
ENVELOPE_SCHEMA_INVALID = "ENVELOPE_SCHEMA_INVALID"
ENVELOPE_KIND_UNKNOWN = "ENVELOPE_KIND_UNKNOWN"
OPERATION_NOT_REGISTERED = "OPERATION_NOT_REGISTERED"
ENVELOPE_EXPIRED = "ENVELOPE_EXPIRED"
ENVELOPE_ALREADY_CONSUMED = "ENVELOPE_ALREADY_CONSUMED"
TARGET_NAMESPACE_MISMATCH = "TARGET_NAMESPACE_MISMATCH"
OID_DRIFT_DETECTED = "OID_DRIFT_DETECTED"
PREDECESSOR_RECEIPT_MISSING = "PREDECESSOR_RECEIPT_MISSING"
PREDECESSOR_DIGEST_MISMATCH = "PREDECESSOR_DIGEST_MISMATCH"
TOCTOU_PREIMAGE_DRIFT = "TOCTOU_PREIMAGE_DRIFT"

_ALL_CODES = (
    ENVELOPE_SOURCE_NOT_EXACTLY_ONE, ENVELOPE_SCHEMA_INVALID, ENVELOPE_KIND_UNKNOWN,
    OPERATION_NOT_REGISTERED, ENVELOPE_EXPIRED, ENVELOPE_ALREADY_CONSUMED,
    TARGET_NAMESPACE_MISMATCH, OID_DRIFT_DETECTED, PREDECESSOR_RECEIPT_MISSING,
    PREDECESSOR_DIGEST_MISMATCH, TOCTOU_PREIMAGE_DRIFT,
)
BLOCKING_CODES: frozenset[str] = frozenset(_ALL_CODES)


class AuthorizationBlockedError(Exception):
    """确定性阻断（FA6）：code 必属 ``BLOCKING_CODES``，mutation=0。

    CLI 层捕获后以 typed findings JSON + 退出码 2 呈现（BLOCKED 先例）；
    不承载凭据，findings 只含 code/detail。
    """

    def __init__(self, code: str, detail: str = "") -> None:
        if code not in BLOCKING_CODES:
            # 枚举外 code 属调用方编程错误，与授权内容阻断分层（不得伪装）。
            raise ValueError(f"unknown blocking code: {code}")
        self.code = code
        self.detail = detail
        self.findings: list[dict[str, Any]] = [
            {"code": code, "severity": "ERROR", "mutation": 0, "detail": detail}
        ]
        super().__init__(f"{code}: {detail}" if detail else code)


# --- AuthorizationEnvelopeV1（FA1，字段集权威 = Feature DESIGN / HLD §6.3） ---


@dataclass(frozen=True, slots=True)
class AuthorizationEnvelopeV1:
    """共享授权信封：payload 为 versioned operation payload 原样透传。"""

    schema_version: int
    kind: str
    authorization_id: str
    operation: str
    target_refs: tuple[str, ...]
    plan_digest: str
    issued_at: str
    expires_at: str
    single_use: bool
    authorization_source: str
    payload: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "authorization_id": self.authorization_id,
            "operation": self.operation,
            "target_refs": list(self.target_refs),
            "plan_digest": self.plan_digest,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "single_use": self.single_use,
            "authorization_source": self.authorization_source,
            "payload": dict(self.payload),
        }


def _invalid(detail: str) -> AuthorizationBlockedError:
    # FA6 形态简写：schema 无效即确定性阻断（mutation=0）
    return AuthorizationBlockedError(ENVELOPE_SCHEMA_INVALID, detail)


def _require_nonempty_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuthorizationBlockedError(
            ENVELOPE_SCHEMA_INVALID, f"field {field} must be a non-empty string"
        )
    return value


def _parse_iso_timestamp(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AuthorizationBlockedError(
            ENVELOPE_SCHEMA_INVALID, f"field {field} is not an ISO-8601 timestamp: {value!r}"
        ) from exc
    if parsed.tzinfo is None:
        raise AuthorizationBlockedError(
            ENVELOPE_SCHEMA_INVALID, f"field {field} must carry a timezone: {value!r}"
        )
    return parsed


def parse_authorization_envelope(payload: Mapping[str, Any]) -> AuthorizationEnvelopeV1:
    """闭合校验并构造 envelope（FA1）。字段集不闭合 / single_use!=True /
    source 非常量 / 类型形态错误 → ``ENVELOPE_SCHEMA_INVALID``；
    kind 非 envelope → ``ENVELOPE_KIND_UNKNOWN``。"""
    if not isinstance(payload, Mapping):
        raise _invalid("envelope payload must be a JSON object")
    fields = set(payload)
    if fields != set(ENVELOPE_FIELDS):
        missing = sorted(set(ENVELOPE_FIELDS) - fields)
        extra = sorted(fields - set(ENVELOPE_FIELDS))
        raise _invalid(f"envelope fields mismatch: missing={missing}, extra={extra}")
    if payload["schema_version"] != ENVELOPE_SCHEMA_VERSION:
        raise _invalid(
            f"schema_version must be {ENVELOPE_SCHEMA_VERSION}: {payload['schema_version']!r}"
        )
    if payload["kind"] != ENVELOPE_KIND:
        # 旧授权文件（如 kind=ExactFileAuthorizationV1）直喂时命中本阻断（AE-N03）。
        raise AuthorizationBlockedError(
            ENVELOPE_KIND_UNKNOWN, f"unexpected kind: {payload['kind']!r}"
        )
    if payload["single_use"] is not True:
        raise _invalid("single_use must be true (envelope is single-use)")
    if payload["authorization_source"] != ENVELOPE_AUTHORIZATION_SOURCE:
        raise _invalid(
            "authorization_source must be const "
            f"{ENVELOPE_AUTHORIZATION_SOURCE!r}: {payload['authorization_source']!r}"
        )
    target_refs = payload["target_refs"]
    if not isinstance(target_refs, list) or not target_refs:
        raise _invalid("target_refs must be a non-empty list of logical refs")
    refs = tuple(_require_nonempty_str(ref, "target_refs[]") for ref in target_refs)
    inner_payload = payload["payload"]
    if not isinstance(inner_payload, Mapping):
        raise _invalid("payload must be a JSON object (versioned operation payload)")
    _parse_iso_timestamp(payload["issued_at"], "issued_at")
    _parse_iso_timestamp(payload["expires_at"], "expires_at")
    return AuthorizationEnvelopeV1(
        schema_version=ENVELOPE_SCHEMA_VERSION,
        kind=ENVELOPE_KIND,
        authorization_id=_require_nonempty_str(payload["authorization_id"], "authorization_id"),
        operation=_require_nonempty_str(payload["operation"], "operation"),
        target_refs=refs,
        plan_digest=_require_nonempty_str(payload["plan_digest"], "plan_digest"),
        issued_at=payload["issued_at"],
        expires_at=payload["expires_at"],
        single_use=True,
        authorization_source=ENVELOPE_AUTHORIZATION_SOURCE,
        payload=dict(inner_payload),
    )


def ensure_not_expired(
    envelope: AuthorizationEnvelopeV1, *, now: datetime | None = None
) -> None:
    """有效期检查（AE-N04）：过期 → ``ENVELOPE_EXPIRED``，授权不消费。"""
    expires = _parse_iso_timestamp(envelope.expires_at, "expires_at")
    current = now or datetime.now(UTC)
    if current >= expires:
        raise AuthorizationBlockedError(
            ENVELOPE_EXPIRED,
            f"authorization expired at {envelope.expires_at} (now={current.isoformat()})",
        )


# --- exactly-one resolver（FA2，ADR-076-05r2） ---


def _load_envelope_json(path: Path) -> AuthorizationEnvelopeV1:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        # 文件不可读 / 非 JSON 均属授权源不可解析（AE-N02 同形态）
        raise _invalid(f"authorization source unreadable/invalid: {path} ({exc})") from exc
    return parse_authorization_envelope(document)


class AuthorizationResolver:
    """三源 exactly-one 解析器：file / ref / id 恰一（FA2）。

    ref_resolver：``process/...`` 逻辑引用 → 物理路径（CLI 注入 resolve-ref
    运行时）；issuance_lookup：authorization_id → envelope JSON（接 issuance
    registry）。未配置时用对应源属调用方配置错误（ValueError），不冒充阻断。
    """

    def __init__(
        self,
        *,
        ref_resolver: Callable[[str], Path] | None = None,
        issuance_lookup: Callable[[str], Mapping[str, Any]] | None = None,
    ) -> None:
        self._ref_resolver = ref_resolver
        self._issuance_lookup = issuance_lookup

    def resolve(
        self,
        *,
        file: Path | str | None = None,
        ref: str | None = None,
        authorization_id: str | None = None,
    ) -> AuthorizationEnvelopeV1:
        """解析恰一授权源 → envelope；none/多选确定性阻断（AE-N01）。"""
        provided = {
            name: value
            for name, value in (("file", file), ("ref", ref), ("id", authorization_id))
            if value is not None
        }
        if len(provided) != 1:
            raise AuthorizationBlockedError(
                ENVELOPE_SOURCE_NOT_EXACTLY_ONE,
                "exactly one of --authorization-file/--authorization-ref/"
                f"--authorization-id required, got {len(provided)}: {sorted(provided)}",
            )
        if "file" in provided:
            return _load_envelope_json(Path(provided["file"]))
        if "ref" in provided:
            if self._ref_resolver is None:
                raise ValueError("ref source requires a configured ref_resolver")
            return _load_envelope_json(self._ref_resolver(str(provided["ref"])))
        if self._issuance_lookup is None:
            raise ValueError("id source requires a configured issuance_lookup")
        document = self._issuance_lookup(str(provided["id"]))
        if document is None:
            raise _invalid(
                f"authorization_id not found in issuance registry: {provided['id']}"
            )
        return parse_authorization_envelope(document)


# --- operation payload registry（FA3，七 kind；权威 = Feature DESIGN registry 表） ---

#: operation key → payload 解析器（versioned）。内建：exact-file-mutation /
#: status-sync / release-transition / work-publication-close（既有授权字段集
#: 零改动适配）。T4 注册：publication-mutation / transport-mutation /
#: observation-verification。transport 语义（ADR-076-07）：任何 bytes 离开
#: provider 即消费，PARTIAL/FAILED 终态同样消费（见 AuthorizationLedger）。
OperationPayloadParser = Callable[[Mapping[str, Any]], Any]

_OPERATION_PAYLOAD_REGISTRY: dict[str, OperationPayloadParser] = {}


def register_operation_payload(
    kind: str, parser: OperationPayloadParser, *, replace: bool = False
) -> None:
    """静态注册 operation payload 解析器（T4/S05 消费同一入口）。"""
    if not isinstance(kind, str) or not kind.strip():
        raise ValueError("operation kind must be a non-empty string")
    if kind in _OPERATION_PAYLOAD_REGISTRY and not replace:
        raise ValueError(f"operation kind already registered: {kind}")
    _OPERATION_PAYLOAD_REGISTRY[kind] = parser


def registered_operation_kinds() -> tuple[str, ...]:
    return tuple(sorted(_OPERATION_PAYLOAD_REGISTRY))


def parse_operation_payload(envelope: AuthorizationEnvelopeV1) -> Any:
    """按 envelope.operation 分派 payload 解析器（AE-03/N03）。

    未注册 → ``OPERATION_NOT_REGISTERED``；既有授权解析失败（ValueError）
    → ``ENVELOPE_SCHEMA_INVALID``（适配器不重定义其字段集）。
    """
    parser = _OPERATION_PAYLOAD_REGISTRY.get(envelope.operation)
    if parser is None:
        raise AuthorizationBlockedError(
            OPERATION_NOT_REGISTERED,
            f"operation not registered: {envelope.operation!r} "
            f"(registered={registered_operation_kinds()})",
        )
    try:
        return parser(envelope.payload)
    except AuthorizationBlockedError:
        raise
    except ValueError as exc:
        raise AuthorizationBlockedError(
            ENVELOPE_SCHEMA_INVALID,
            f"payload rejected for operation {envelope.operation!r}: {exc}",
        ) from exc


def _adapt_exact_file_payload(payload: Mapping[str, Any]) -> Any:
    from meta_flow.execution_control.exact_file_transaction import (
        ExactFileAuthorizationV1,
    )

    return ExactFileAuthorizationV1.from_mapping(payload)


def _adapt_status_sync_payload(payload: Mapping[str, Any]) -> Any:
    from meta_flow.workflow.cr_status_sync import StatusSyncAuthorization

    return StatusSyncAuthorization.from_dict(dict(payload))


def _adapt_release_transition_payload(payload: Mapping[str, Any]) -> Any:
    from meta_flow.workflow.release_order import ReleaseTransitionAuthorizationV1

    return ReleaseTransitionAuthorizationV1.from_mapping(payload)


def _adapt_work_publication_close_payload(payload: Mapping[str, Any]) -> Any:
    # DQ-FD-076-03：close 迁移合同——payload 携带既有
    # WorkPublicationCloseAuthorizationV1 全字段，零改动经既有 from_mapping
    # 适配消费；close guard 物理迁移（消费 receipts）归 S05。
    from meta_flow.work.publication_close import WorkPublicationCloseAuthorizationV1

    return WorkPublicationCloseAuthorizationV1.from_mapping(payload)


register_operation_payload("exact-file-mutation", _adapt_exact_file_payload)
register_operation_payload("status-sync", _adapt_status_sync_payload)
register_operation_payload("release-transition", _adapt_release_transition_payload)
register_operation_payload("work-publication-close", _adapt_work_publication_close_payload)


# --- 双账本与 attempt 状态机（FA4/FA5，ADR-076-07：登记先于副作用，登记即消费） ---

ATTEMPT_STARTED = "STARTED"
#: terminal 终态（PARTIAL/FAILED 同样消费——结果已发生，不得复用授权）
ATTEMPT_TERMINAL_STATES = ("SUCCEEDED", "PARTIAL", "FAILED")


def authorization_digest(envelope: AuthorizationEnvelopeV1) -> str:
    """envelope 规范摘要（账本只记 digest，不落凭据）。"""
    import hashlib

    blob = json.dumps(envelope.as_dict(), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class AuthorizationLedger:
    """双账本（O-S02-1 已决分工，两对象分离，均 append-only）。

    issuance registry（.meta-flow-runtime/authorization/issuance-registry.ndjson）：
    签发登记 + envelope 全文档，供 --authorization-id 解析；只记签发不记消费。
    consumption ledger（.../consumption-ledger.ndjson）：每行 = digest /
    operation / attempt_id / attempt_state / consumed_at / preimage_digests；
    STARTED→terminal（崩溃恢复：STARTED 无 terminal 一律视为已消费）。
    """

    root: Path

    @property
    def _dir(self) -> Path:
        return self.root / ".meta-flow-runtime" / "authorization"

    @property
    def issuance_path(self) -> Path:
        return self._dir / "issuance-registry.ndjson"

    @property
    def consumption_path(self) -> Path:
        return self._dir / "consumption-ledger.ndjson"

    def _append(self, path: Path, row: Mapping[str, Any]) -> dict[str, Any]:
        self._dir.mkdir(parents=True, exist_ok=True)
        line = json.dumps(dict(row), sort_keys=True, ensure_ascii=False)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return dict(row)

    def _rows(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    # -- issuance -----------------------------------------------------------

    def register_issuance(
        self, envelope: AuthorizationEnvelopeV1, *, issued_at: str | None = None
    ) -> str:
        digest = authorization_digest(envelope)
        self._append(
            self.issuance_path,
            {
                "authorization_id": envelope.authorization_id,
                "authorization_digest": digest,
                "operation": envelope.operation,
                "issued_at": issued_at or envelope.issued_at,
                "envelope": envelope.as_dict(),
            },
        )
        return digest

    def lookup_issuance_document(self, authorization_id: str) -> Mapping[str, Any] | None:
        for row in self._rows(self.issuance_path):
            if row.get("authorization_id") == authorization_id:
                return row.get("envelope")
        return None

    # -- consumption --------------------------------------------------------

    def _consumption_rows(self) -> list[dict[str, Any]]:
        return self._rows(self.consumption_path)

    def attempts(self, digest: str) -> list[dict[str, Any]]:
        return [row for row in self._consumption_rows() if row.get("authorization_digest") == digest]

    def attempt_by_id(self, attempt_id: str) -> dict[str, Any] | None:
        # 同一 attempt 可有多行（STARTED + terminal）；最新行才是当前状态，
        # 否则 terminal 判定永远命中 STARTED 行（AE-FI3 防御失效）。
        latest: dict[str, Any] | None = None
        for row in self._consumption_rows():
            if row.get("attempt_id") == attempt_id:
                latest = row
        return latest

    def _check_predecessor(self, payload: Mapping[str, Any]) -> None:
        predecessor = payload.get("predecessor_attempt")
        if not predecessor:
            return
        record = self.attempt_by_id(str(predecessor))
        if record is None:
            raise AuthorizationBlockedError(
                PREDECESSOR_RECEIPT_MISSING,
                f"predecessor attempt not found in ledger: {predecessor}",
            )
        expected_digest = payload.get("predecessor_digest")
        if expected_digest and record.get("authorization_digest") != expected_digest:
            raise AuthorizationBlockedError(
                PREDECESSOR_DIGEST_MISMATCH,
                f"predecessor digest mismatch: {predecessor}",
            )

    def consume(
        self,
        envelope: AuthorizationEnvelopeV1,
        *,
        attempt_id: str,
        preimage_digests: Mapping[str, str],
        expected_preimage_digests: Mapping[str, str] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """原子登记 attempt=STARTED（持久化边界：先于任何外部副作用）。

        校验顺序（全部通过才登记；任一阻断 → mutation=0 且授权不消费）：
        过期 → 已消费 → 前驱 receipt → TOCTOU preimage 重验。
        """
        if not str(attempt_id).strip():
            raise ValueError("attempt_id must be a non-empty string")
        ensure_not_expired(envelope, now=now)
        digest = authorization_digest(envelope)
        if self.attempts(digest):
            raise AuthorizationBlockedError(
                ENVELOPE_ALREADY_CONSUMED,
                f"authorization already consumed: {envelope.authorization_id}",
            )
        self._check_predecessor(envelope.payload)
        if expected_preimage_digests is not None and dict(expected_preimage_digests) != dict(preimage_digests):
            raise AuthorizationBlockedError(
                TOCTOU_PREIMAGE_DRIFT,
                "preimage digests drifted between plan and consume (TOCTOU)",
            )
        return self._append(
            self.consumption_path,
            {
                "authorization_digest": digest,
                "operation": envelope.operation,
                "attempt_id": attempt_id,
                "attempt_state": ATTEMPT_STARTED,
                "consumed_at": (now or datetime.now(UTC)).isoformat(),
                "preimage_digests": dict(preimage_digests),
            },
        )

    def complete_attempt(
        self, attempt_id: str, outcome: str, *, now: datetime | None = None
    ) -> dict[str, Any]:
        """副作用完成后 append terminal receipt（SUCCEEDED/PARTIAL/FAILED）。

        崩溃语义（AE-FI/AE-08）：terminal 已存在 → 编程错误（ValueError），
        不静默改写历史行；ledger 无 terminal → 结果未知，不可补记成功。
        """
        if outcome not in ATTEMPT_TERMINAL_STATES:
            raise ValueError(f"outcome must be one of {ATTEMPT_TERMINAL_STATES}: {outcome}")
        record = self.attempt_by_id(attempt_id)
        if record is None:
            raise ValueError(f"attempt not found in ledger: {attempt_id}")
        if record.get("attempt_state") in ATTEMPT_TERMINAL_STATES:
            raise ValueError(f"attempt already terminal: {attempt_id}")
        return self._append(
            self.consumption_path,
            {**record, "attempt_state": outcome, "consumed_at": (now or datetime.now(UTC)).isoformat()},
        )


def validate_envelope_context(
    envelope: AuthorizationEnvelopeV1,
    *,
    allowed_target_refs: tuple[str, ...] | None = None,
    current_release_oid: str | None = None,
    current_process_oid: str | None = None,
) -> None:
    """有效性检查（DESIGN 关键流程步骤 3）：namespace 与双仓 OID。"""
    if allowed_target_refs is not None:
        allowed = set(allowed_target_refs)
        outside = [ref for ref in envelope.target_refs if ref not in allowed]
        if outside:
            raise AuthorizationBlockedError(
                TARGET_NAMESPACE_MISMATCH,
                f"target_refs outside command namespace: {outside}",
            )
    payload = envelope.payload
    for field, current in (
        ("expected_release_oid", current_release_oid),
        ("expected_process_oid", current_process_oid),
    ):
        expected = payload.get(field)
        if expected is not None and current is not None and expected != current:
            raise AuthorizationBlockedError(
                OID_DRIFT_DETECTED,
                f"{field} drift: authorization={expected!r}, current={current!r}",
            )
