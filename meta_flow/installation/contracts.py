"""安装生命周期 canonical plan 的公共契约。"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from enum import StrEnum
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

PLAN_SCHEMA_VERSION = 2
PLAN_FIELDS = (
    "schema_version",
    "operation",
    "decision",
    "decision_ref",
    "subject",
    "source_identity",
    "target_identity",
    "base_facts",
    "actions",
    "conflicts",
    "rollback_plan",
    "plan_digest",
)
SUBJECT_FIELDS = (
    "request_intent",
    "platform",
    "scope",
    "component_set",
    "legacy_alias",
    "action_count",
)
SOURCE_IDENTITY_FIELDS = (
    "source",
    "version",
    "oid",
    "delivery_tree_digest",
    "rules_source_digest",
    "inventory_digest",
)
ACTION_FIELDS = (
    "action_id",
    "action_kind",
    "component",
    "ownership_kind",
    "source_ref",
    "target_ref",
    "before_state",
    "desired_state",
    "preconditions",
    "rollback_action",
    "ordinal",
    "action_digest",
)

OPERATIONS = (
    "cli.install",
    "cli.upgrade",
    "cli.uninstall",
    "assets.install",
    "assets.upgrade",
    "assets.uninstall",
    "lifecycle.recover",
)
ACTION_KINDS = (
    "invoke_uv_tool",
    "upsert_managed_block",
    "write_exact_file",
    "write_exact_leaf",
    "remove_owned_entry",
    "write_manifest",
    "restore_owned_entry",
)
ACTION_COMPONENTS = ("cli", "rules", "agents", "skills", "manifest")
ACTION_OWNERSHIP_KINDS = (
    "uv_tool",
    "managed_block",
    "exact_file",
    "exact_leaf_set",
    "manifest",
)
DECISIONS = ("READY", "NOOP", "BLOCKED")
GLOBAL_CHECKPOINTS = (
    "C1_REQUEST_SCOPE",
    "C2_SOURCE_IDENTITY",
    "C3_TARGET_IDENTITY",
    "C4_PLAN_DIGEST",
)
CANONICAL_COMPONENTS = ("rules", "agents", "skills", "full")
COMPONENT_SET_MEMBERS = ("rules", "agents", "skills")
SCOPES = ("project", "user")

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_OID_RE = re.compile(r"^[0-9a-f]{40}$")
_DYNAMIC_KEYS = frozenset({"created_at", "generated_at", "timestamp", "updated_at"})
_FORBIDDEN_PATH_KEYS = frozenset({"absolute_path", "remove_path", "workspace_path"})
_PORTABLE_REF_KEYS = frozenset({"decision_ref", "target_ref", "transaction_ref"})


class ContractErrorCode(StrEnum):
    """稳定、可审计的契约错误分类。"""

    UNKNOWN_KEY = "unknown-key"
    MISSING_KEY = "missing-key"
    INVALID_ENUM = "invalid-enum"
    IDENTITY_CONFLICT = "identity-conflict"
    IDENTITY_INCOMPLETE = "identity-incomplete"
    UNSAFE_PATH = "unsafe-path"
    NONCANONICAL_VALUE = "noncanonical-value"


class InstallationContractError(ValueError):
    """可预期且不会进入 executor 的安装契约阻断。"""

    def __init__(self, code: ContractErrorCode | str, message: str) -> None:
        self.code = ContractErrorCode(code)
        super().__init__(f"{self.code.value}: {message}")


def require_exact_keys(
    payload: object,
    expected: Sequence[str],
    *,
    field: str,
) -> Mapping[str, Any]:
    """校验 mapping 的 keys 与契约完全一致，并返回原 mapping。"""

    if not isinstance(payload, Mapping):
        raise InstallationContractError(
            ContractErrorCode.NONCANONICAL_VALUE,
            f"{field} must be a mapping",
        )
    expected_set = set(expected)
    actual_set = set(payload)
    unknown = sorted(str(key) for key in actual_set - expected_set)
    missing = sorted(expected_set - actual_set)
    if unknown:
        raise InstallationContractError(
            ContractErrorCode.UNKNOWN_KEY,
            f"{field} has unknown keys: {unknown}",
        )
    if missing:
        raise InstallationContractError(
            ContractErrorCode.MISSING_KEY,
            f"{field} is missing keys: {missing}",
        )
    return payload


def validate_portable_ref(value: object, *, field: str) -> None:
    """校验不依赖工作区绝对路径的 POSIX 逻辑引用。"""

    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise InstallationContractError(
            ContractErrorCode.UNSAFE_PATH,
            f"{field} must be a non-empty portable POSIX ref",
        )
    path = PurePosixPath(value)
    windows = PureWindowsPath(value)
    raw_parts = value.split("/")
    if (
        value.startswith("/")
        or windows.drive
        or windows.root
        or path.is_absolute()
        or path.parts != tuple(raw_parts)
        or any(part in {"", ".", ".."} for part in raw_parts)
    ):
        raise InstallationContractError(
            ContractErrorCode.UNSAFE_PATH,
            f"{field} must not be absolute or contain empty/dot/parent segments",
        )


def validate_canonical_value(value: object, *, field: str = "payload") -> None:
    """递归拒绝 JSON 之外、浮点、动态时间和危险路径字段。"""

    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        raise InstallationContractError(
            ContractErrorCode.NONCANONICAL_VALUE,
            f"{field} must not contain float or NaN values",
        )
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise InstallationContractError(
                    ContractErrorCode.NONCANONICAL_VALUE,
                    f"{field} keys must be strings",
                )
            if key in _DYNAMIC_KEYS:
                raise InstallationContractError(
                    ContractErrorCode.NONCANONICAL_VALUE,
                    f"{field}.{key} is dynamic and forbidden",
                )
            if key in _FORBIDDEN_PATH_KEYS:
                raise InstallationContractError(
                    ContractErrorCode.UNSAFE_PATH,
                    f"{field}.{key} is forbidden",
                )
            if key in _PORTABLE_REF_KEYS:
                validate_portable_ref(item, field=f"{field}.{key}")
            validate_canonical_value(item, field=f"{field}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            validate_canonical_value(item, field=f"{field}[{index}]")
        return
    raise InstallationContractError(
        ContractErrorCode.NONCANONICAL_VALUE,
        f"{field} contains unsupported value type {type(value).__name__}",
    )


def validate_action(payload: object, *, field: str = "action") -> dict[str, Any]:
    """验证 exact 12-key action、自 digest、枚举和 portable refs。"""

    action = require_exact_keys(payload, ACTION_FIELDS, field=field)
    normalized = {key: action[key] for key in ACTION_FIELDS}
    if not isinstance(normalized["action_id"], str) or not normalized["action_id"]:
        raise InstallationContractError(
            ContractErrorCode.NONCANONICAL_VALUE,
            f"{field}.action_id must be non-empty",
        )
    if normalized["action_kind"] not in ACTION_KINDS:
        raise InstallationContractError(
            ContractErrorCode.INVALID_ENUM,
            f"{field}.action_kind must be one of {list(ACTION_KINDS)}",
        )
    if normalized["component"] not in ACTION_COMPONENTS:
        raise InstallationContractError(
            ContractErrorCode.INVALID_ENUM,
            f"{field}.component must be one of {list(ACTION_COMPONENTS)}",
        )
    if normalized["ownership_kind"] not in ACTION_OWNERSHIP_KINDS:
        raise InstallationContractError(
            ContractErrorCode.INVALID_ENUM,
            f"{field}.ownership_kind must be one of {list(ACTION_OWNERSHIP_KINDS)}",
        )
    source_ref = normalized["source_ref"]
    if source_ref is not None:
        validate_portable_ref(source_ref, field=f"{field}.source_ref")
    validate_portable_ref(normalized["target_ref"], field=f"{field}.target_ref")
    for state_field in ("before_state", "desired_state"):
        if not isinstance(normalized[state_field], Mapping):
            raise InstallationContractError(
                ContractErrorCode.NONCANONICAL_VALUE,
                f"{field}.{state_field} must be a mapping",
            )
    if not isinstance(normalized["preconditions"], list):
        raise InstallationContractError(
            ContractErrorCode.NONCANONICAL_VALUE,
            f"{field}.preconditions must be a list",
        )
    if normalized["rollback_action"] is not None and not isinstance(normalized["rollback_action"], Mapping):
        raise InstallationContractError(
            ContractErrorCode.NONCANONICAL_VALUE,
            f"{field}.rollback_action must be null or a mapping",
        )
    if (
        not isinstance(normalized["ordinal"], int)
        or isinstance(normalized["ordinal"], bool)
        or normalized["ordinal"] < 1
    ):
        raise InstallationContractError(
            ContractErrorCode.NONCANONICAL_VALUE,
            f"{field}.ordinal must be a positive integer",
        )
    validate_canonical_value(normalized, field=field)
    digest = normalized["action_digest"]
    if not isinstance(digest, str) or not _DIGEST_RE.fullmatch(digest):
        raise InstallationContractError(
            ContractErrorCode.NONCANONICAL_VALUE,
            f"{field}.action_digest must be one lowercase 64-hex digest",
        )

    from meta_flow.installation.canonical import canonical_digest

    unsigned = {key: normalized[key] for key in ACTION_FIELDS if key != "action_digest"}
    if digest != canonical_digest(unsigned):
        raise InstallationContractError(
            ContractErrorCode.NONCANONICAL_VALUE,
            f"{field}.action_digest does not match canonical action content",
        )
    return normalized


def validate_plan(payload: object) -> None:
    """验证 12-key canonical plan、嵌套不变量和 self-digest。"""

    plan = require_exact_keys(payload, PLAN_FIELDS, field="plan")
    if plan["schema_version"] != PLAN_SCHEMA_VERSION:
        raise InstallationContractError(
            ContractErrorCode.INVALID_ENUM,
            f"schema_version must be {PLAN_SCHEMA_VERSION}",
        )
    if plan["operation"] not in OPERATIONS:
        raise InstallationContractError(
            ContractErrorCode.INVALID_ENUM,
            f"operation must be one of {list(OPERATIONS)}",
        )
    if plan["decision"] not in DECISIONS:
        raise InstallationContractError(
            ContractErrorCode.INVALID_ENUM,
            f"decision must be one of {list(DECISIONS)}",
        )
    validate_portable_ref(plan["decision_ref"], field="plan.decision_ref")

    subject = require_exact_keys(plan["subject"], SUBJECT_FIELDS, field="plan.subject")
    if not isinstance(subject["request_intent"], str) or not subject["request_intent"].strip():
        raise InstallationContractError(
            ContractErrorCode.NONCANONICAL_VALUE,
            "plan.subject.request_intent must be non-empty",
        )
    if not isinstance(subject["platform"], str) or not subject["platform"].strip():
        raise InstallationContractError(
            ContractErrorCode.NONCANONICAL_VALUE,
            "plan.subject.platform must be non-empty",
        )
    if subject["scope"] not in SCOPES:
        raise InstallationContractError(
            ContractErrorCode.INVALID_ENUM,
            f"scope must be one of {list(SCOPES)}",
        )
    component_set = subject["component_set"]
    if (
        not isinstance(component_set, list)
        or not component_set
        or component_set != sorted(set(component_set), key=COMPONENT_SET_MEMBERS.index)
        or any(component not in COMPONENT_SET_MEMBERS for component in component_set)
    ):
        raise InstallationContractError(
            ContractErrorCode.INVALID_ENUM,
            "plan.subject.component_set must be an ordered unique canonical component list",
        )
    if subject["legacy_alias"] not in {"", "agent"}:
        raise InstallationContractError(
            ContractErrorCode.INVALID_ENUM,
            "plan.subject.legacy_alias must be empty or agent",
        )

    actions = plan["actions"]
    conflicts = plan["conflicts"]
    if not isinstance(actions, list) or not isinstance(conflicts, list):
        raise InstallationContractError(
            ContractErrorCode.NONCANONICAL_VALUE,
            "plan actions/conflicts must be lists",
        )
    if subject["action_count"] != len(actions):
        raise InstallationContractError(
            ContractErrorCode.NONCANONICAL_VALUE,
            "plan.subject.action_count must equal len(plan.actions)",
        )
    normalized_actions = [
        validate_action(action, field=f"plan.actions[{index}]")
        for index, action in enumerate(actions)
    ]
    action_ids = [action["action_id"] for action in normalized_actions]
    if len(action_ids) != len(set(action_ids)):
        raise InstallationContractError(
            ContractErrorCode.NONCANONICAL_VALUE,
            "plan.actions contains duplicate action_id",
        )
    ordinals = [action["ordinal"] for action in normalized_actions]
    if ordinals != list(range(1, len(normalized_actions) + 1)):
        raise InstallationContractError(
            ContractErrorCode.NONCANONICAL_VALUE,
            "plan.actions ordinals must be continuous and start at 1",
        )
    if normalized_actions and normalized_actions[-1]["action_kind"] != "write_manifest":
        raise InstallationContractError(
            ContractErrorCode.NONCANONICAL_VALUE,
            "the final plan action must be write_manifest",
        )
    if plan["decision"] == "READY" and conflicts:
        raise InstallationContractError(
            ContractErrorCode.IDENTITY_CONFLICT,
            "READY plan must not contain conflicts",
        )
    if plan["decision"] == "READY" and not actions:
        raise InstallationContractError(
            ContractErrorCode.NONCANONICAL_VALUE,
            "READY plan must contain at least one action",
        )
    if plan["decision"] in {"NOOP", "BLOCKED"} and actions:
        raise InstallationContractError(
            ContractErrorCode.NONCANONICAL_VALUE,
            "NOOP/BLOCKED plan must not contain actions",
        )

    from meta_flow.installation.identity import validate_source_identity

    try:
        validate_source_identity(plan["source_identity"])
    except InstallationContractError:
        if plan["decision"] != "BLOCKED":
            raise

    checkpoints = plan["base_facts"].get("checkpoint_expectations")
    if checkpoints != list(GLOBAL_CHECKPOINTS):
        raise InstallationContractError(
            ContractErrorCode.MISSING_KEY,
            "plan.base_facts.checkpoint_expectations must contain the four global checkpoints",
        )

    validate_canonical_value(plan)
    digest = plan["plan_digest"]
    if not isinstance(digest, str) or not _DIGEST_RE.fullmatch(digest):
        raise InstallationContractError(
            ContractErrorCode.NONCANONICAL_VALUE,
            "plan.plan_digest must be one lowercase 64-hex digest",
        )
    from meta_flow.installation.canonical import canonical_digest

    unsigned = {key: plan[key] for key in PLAN_FIELDS if key != "plan_digest"}
    if digest != canonical_digest(unsigned):
        raise InstallationContractError(
            ContractErrorCode.NONCANONICAL_VALUE,
            "plan.plan_digest does not match canonical plan content",
        )


validate_plan_envelope = validate_plan


__all__ = [
    "ACTION_COMPONENTS",
    "ACTION_FIELDS",
    "ACTION_KINDS",
    "ACTION_OWNERSHIP_KINDS",
    "CANONICAL_COMPONENTS",
    "COMPONENT_SET_MEMBERS",
    "ContractErrorCode",
    "DECISIONS",
    "GLOBAL_CHECKPOINTS",
    "InstallationContractError",
    "OPERATIONS",
    "PLAN_FIELDS",
    "PLAN_SCHEMA_VERSION",
    "SCOPES",
    "SOURCE_IDENTITY_FIELDS",
    "SUBJECT_FIELDS",
    "require_exact_keys",
    "validate_canonical_value",
    "validate_action",
    "validate_plan",
    "validate_plan_envelope",
    "validate_portable_ref",
]
