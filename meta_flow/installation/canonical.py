"""安装生命周期计划的确定性序列化、digest 与纯计算构造器。"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from hashlib import sha256
from typing import Any

from meta_flow.installation.contracts import (
    ACTION_FIELDS,
    GLOBAL_CHECKPOINTS,
    PLAN_FIELDS,
    PLAN_SCHEMA_VERSION,
    ContractErrorCode,
    InstallationContractError,
    require_exact_keys,
    validate_action,
    validate_canonical_value,
    validate_plan,
)
from meta_flow.installation.identity import (
    normalize_component,
    source_identity_conflicts,
    validate_source_identity,
)


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _json_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def canonical_bytes(payload: object) -> bytes:
    """按 sorted compact JSON + UTF-8 生成唯一 bytes。"""

    validate_canonical_value(payload)
    try:
        rendered = json.dumps(
            _json_value(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise InstallationContractError(
            ContractErrorCode.NONCANONICAL_VALUE,
            f"payload is not canonical JSON: {exc}",
        ) from exc
    return rendered.encode("utf-8")


def canonical_digest(payload: object) -> str:
    """使用 Python 原生 SHA-256 计算 canonical payload digest。"""

    return sha256(canonical_bytes(payload)).hexdigest()


def canonical_serialize(payload: object) -> bytes:
    """``canonical_bytes`` 的公共语义别名。"""

    return canonical_bytes(payload)


def _sorted_records(
    records: Iterable[Mapping[str, Any]],
    *,
    required_key: str,
) -> list[dict[str, Any]]:
    normalized = [dict(record) for record in records]
    for record in normalized:
        value = record.get(required_key)
        if not isinstance(value, str) or not value:
            raise InstallationContractError(
                ContractErrorCode.MISSING_KEY,
                f"record requires non-empty {required_key}",
            )
    return sorted(normalized, key=lambda record: (str(record[required_key]), canonical_bytes(record)))


def _normalized_actions(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """接受 exact action 或不含 self-digest 的 11-key action，并按 ordinal 排序。"""

    normalized: list[dict[str, Any]] = []
    unsigned_fields = ACTION_FIELDS[:-1]
    for index, record in enumerate(records):
        expected_fields = ACTION_FIELDS if "action_digest" in record else unsigned_fields
        action = dict(
            require_exact_keys(
                record,
                expected_fields,
                field=f"actions[{index}]",
            )
        )
        if "action_digest" not in action:
            action["action_digest"] = canonical_digest(action)
        normalized.append(validate_action(action, field=f"actions[{index}]"))
    return sorted(normalized, key=lambda action: int(action["ordinal"]))


def build_plan(
    *,
    operation: str,
    decision_ref: str,
    request_intent: str,
    component: str | Iterable[str],
    scope: str,
    platform: str,
    source_identity: Mapping[str, Any],
    target_identity: Mapping[str, Any],
    base_facts: Mapping[str, Any],
    actions: Iterable[Mapping[str, Any]],
    rollback_plan: Mapping[str, Any],
    decision: str = "READY",
    conflicts: Iterable[Mapping[str, Any]] = (),
    source_observation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """构造一个无 I/O、无授权消费的 12-key canonical lifecycle plan。"""

    component_set = normalize_component(component)
    legacy_alias = "agent" if isinstance(component, str) and component.strip().lower() == "agent" else ""
    normalized_source = validate_source_identity(source_identity)
    normalized_actions = _normalized_actions(actions)
    normalized_conflicts = _sorted_records(conflicts, required_key="code")

    if source_observation is not None:
        normalized_conflicts.extend(source_identity_conflicts(normalized_source, source_observation))
        normalized_conflicts = sorted(
            normalized_conflicts,
            key=lambda record: (
                str(record["code"]),
                str(record.get("field", "")),
                canonical_bytes(record),
            ),
        )
    if normalized_conflicts:
        decision = "BLOCKED"
        normalized_actions = []

    normalized_base_facts = dict(base_facts)
    existing_checkpoints = normalized_base_facts.get("checkpoint_expectations")
    if existing_checkpoints not in (None, list(GLOBAL_CHECKPOINTS), tuple(GLOBAL_CHECKPOINTS)):
        raise InstallationContractError(
            ContractErrorCode.IDENTITY_CONFLICT,
            "base_facts.checkpoint_expectations conflicts with the global contract",
        )
    normalized_base_facts["checkpoint_expectations"] = list(GLOBAL_CHECKPOINTS)

    payload: dict[str, Any] = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "operation": operation,
        "decision": decision,
        "decision_ref": decision_ref,
        "subject": {
            "request_intent": request_intent,
            "platform": platform,
            "scope": scope,
            "component_set": list(component_set),
            "legacy_alias": legacy_alias,
            "action_count": len(normalized_actions),
        },
        "source_identity": normalized_source,
        "target_identity": dict(target_identity),
        "base_facts": normalized_base_facts,
        "actions": normalized_actions,
        "conflicts": normalized_conflicts,
        "rollback_plan": dict(rollback_plan),
    }
    payload["plan_digest"] = canonical_digest(payload)
    payload = {key: payload[key] for key in PLAN_FIELDS}
    validate_plan(payload)
    return payload


__all__ = [
    "build_plan",
    "canonical_bytes",
    "canonical_digest",
    "canonical_serialize",
]
