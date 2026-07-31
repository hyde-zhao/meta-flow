"""一次性 typed authorization 的 fail-closed 契约与原子 claim。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import Any
from uuid import uuid4

from meta_flow.installation.contracts import (
    ContractErrorCode,
    InstallationContractError,
    require_exact_keys,
)

AUTHORIZATION_FIELDS = (
    "schema_version",
    "authorization_id",
    "authorization_source",
    "authorization_kind",
    "decision_ref",
    "plan_digest",
    "source_digest",
    "target_digest",
    "scope_digest",
    "facts_digest",
    "expires_at",
    "single_use",
)
AUTHORIZATION_SOURCE = "typed-user-confirmation"
AUTHORIZATION_SCHEMA_VERSION = 1


class AuthorizationError(InstallationContractError):
    """不会进入 executor 的授权边界错误。"""


@dataclass(frozen=True)
class ClaimedAuthorization:
    """executor 唯一允许接收的已 claim transaction context。"""

    transaction_id: str
    authorization_id: str
    plan_digest: str
    source_digest: str
    target_digest: str
    scope_digest: str
    facts_digest: str


class AuthorizationClaims:
    """进程内 compare-and-set claim store；同一 authorization 只会成功一次。"""

    def __init__(self) -> None:
        self._claimed: set[str] = set()
        self._lock = Lock()

    def claim_once(self, authorization: object, *, plan: Mapping[str, Any], now: datetime | None = None) -> ClaimedAuthorization:
        """验证后在单个临界区内消费 authorization；replay 一律拒绝。"""

        validated = validate_authorization(authorization, plan=plan, now=now)
        authorization_id = validated["authorization_id"]
        with self._lock:
            if authorization_id in self._claimed:
                raise AuthorizationError(ContractErrorCode.IDENTITY_CONFLICT, "authorization is already consumed")
            self._claimed.add(authorization_id)
        return ClaimedAuthorization(
            transaction_id=f"txn-{uuid4().hex}",
            authorization_id=authorization_id,
            plan_digest=validated["plan_digest"],
            source_digest=validated["source_digest"],
            target_digest=validated["target_digest"],
            scope_digest=validated["scope_digest"],
            facts_digest=validated["facts_digest"],
        )


def validate_authorization(
    authorization: object,
    *,
    plan: Mapping[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    """校验 12-key authorization 与 immutable plan 的 exact binding。"""

    payload = require_exact_keys(authorization, AUTHORIZATION_FIELDS, field="authorization")
    normalized = {key: payload[key] for key in AUTHORIZATION_FIELDS}
    if normalized["schema_version"] != AUTHORIZATION_SCHEMA_VERSION:
        _fail(ContractErrorCode.INVALID_ENUM, "authorization.schema_version must be 1")
    if not isinstance(normalized["authorization_id"], str) or not normalized["authorization_id"]:
        _fail(ContractErrorCode.NONCANONICAL_VALUE, "authorization.authorization_id must be non-empty")
    if normalized["authorization_source"] != AUTHORIZATION_SOURCE:
        _fail(ContractErrorCode.INVALID_ENUM, "authorization_source must be typed-user-confirmation")
    if not isinstance(normalized["authorization_kind"], str) or not normalized["authorization_kind"]:
        _fail(ContractErrorCode.NONCANONICAL_VALUE, "authorization.authorization_kind must be non-empty")
    if normalized["single_use"] is not True:
        _fail(ContractErrorCode.INVALID_ENUM, "authorization.single_use must be true")

    expected = authorization_binding(plan)
    for field, value in expected.items():
        if normalized[field] != value:
            _fail(ContractErrorCode.IDENTITY_CONFLICT, f"authorization.{field} does not match plan")

    expiry = _parse_expiry(normalized["expires_at"])
    reference = now or datetime.now(UTC)
    if expiry <= reference:
        _fail(ContractErrorCode.IDENTITY_CONFLICT, "authorization is expired")
    return normalized


def authorization_binding(plan: Mapping[str, Any]) -> dict[str, str]:
    """从 canonical plan 派生 authorization 的六个 exact binding scalar。"""

    from meta_flow.installation.canonical import canonical_digest

    try:
        return {
            "decision_ref": str(plan["decision_ref"]),
            "plan_digest": str(plan["plan_digest"]),
            "source_digest": canonical_digest(plan["source_identity"]),
            "target_digest": canonical_digest(plan["target_identity"]),
            "scope_digest": canonical_digest(plan["subject"]),
            "facts_digest": canonical_digest(plan["base_facts"]),
        }
    except KeyError as exc:
        raise AuthorizationError(ContractErrorCode.MISSING_KEY, f"plan is missing {exc.args[0]}") from exc


def _parse_expiry(value: object) -> datetime:
    if not isinstance(value, str):
        _fail(ContractErrorCode.NONCANONICAL_VALUE, "authorization.expires_at must be ISO-8601")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AuthorizationError(ContractErrorCode.NONCANONICAL_VALUE, "authorization.expires_at is invalid") from exc
    if parsed.tzinfo is None:
        _fail(ContractErrorCode.NONCANONICAL_VALUE, "authorization.expires_at requires timezone")
    return parsed


def _fail(code: ContractErrorCode, message: str) -> None:
    raise AuthorizationError(code, message)


__all__ = [
    "AUTHORIZATION_FIELDS",
    "AUTHORIZATION_SCHEMA_VERSION",
    "AUTHORIZATION_SOURCE",
    "AuthorizationClaims",
    "AuthorizationError",
    "ClaimedAuthorization",
    "authorization_binding",
    "validate_authorization",
]
