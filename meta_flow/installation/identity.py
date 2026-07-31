"""安装来源 identity 与 component alias 的唯一规范化入口。"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterable, Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any

from meta_flow.installation.contracts import (
    COMPONENT_SET_MEMBERS,
    SOURCE_IDENTITY_FIELDS,
    ContractErrorCode,
    InstallationContractError,
    require_exact_keys,
)

_OID_RE = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_COMPONENT_EXPANSIONS = {
    "rules": ("rules",),
    "agents": ("agents",),
    "skills": ("skills",),
    "full": COMPONENT_SET_MEMBERS,
    "agent": ("agents", "skills"),
}


def normalize_component(selector: str | Iterable[str]) -> tuple[str, ...]:
    """把 component selector 规范化为有序、唯一的实际 component_set。

    legacy ``agent`` 的唯一语义是 ``agents+skills``，不会产生第五个
    canonical component，也不会降格为仅 ``agents``。
    """

    raw = [selector] if isinstance(selector, str) else list(selector)
    if not raw:
        raise InstallationContractError(
            ContractErrorCode.MISSING_KEY,
            "component selector must not be empty",
        )
    selected: set[str] = set()
    for value in raw:
        if not isinstance(value, str):
            raise InstallationContractError(
                ContractErrorCode.NONCANONICAL_VALUE,
                "component selector values must be strings",
            )
        token = value.strip().lower()
        expansion = _COMPONENT_EXPANSIONS.get(token)
        if expansion is None:
            raise InstallationContractError(
                ContractErrorCode.INVALID_ENUM,
                f"unknown component selector: {token or '-'}",
            )
        selected.update(expansion)
    return tuple(component for component in COMPONENT_SET_MEMBERS if component in selected)


def component_display(selector: str | Iterable[str]) -> str:
    """返回稳定的人类可读 component selection。"""

    return "+".join(normalize_component(selector))


def validate_source_identity(payload: object) -> dict[str, str]:
    """校验并返回 canonical source identity 的独立副本。"""

    identity = require_exact_keys(payload, SOURCE_IDENTITY_FIELDS, field="source_identity")
    normalized = {key: identity[key] for key in SOURCE_IDENTITY_FIELDS}
    for key in ("source", "version"):
        value = normalized[key]
        if not isinstance(value, str) or not value.strip():
            raise InstallationContractError(
                ContractErrorCode.IDENTITY_INCOMPLETE,
                f"source_identity.{key} must be non-empty",
            )
        if value.startswith("/") or "\\" in value or "\x00" in value:
            raise InstallationContractError(
                ContractErrorCode.UNSAFE_PATH,
                f"source_identity.{key} must not contain an absolute workspace path",
            )
        normalized[key] = value.strip()

    oid = normalized["oid"]
    if not isinstance(oid, str) or not _OID_RE.fullmatch(oid.lower()):
        raise InstallationContractError(
            ContractErrorCode.IDENTITY_INCOMPLETE,
            "source_identity.oid must be one full 40-hex OID",
        )
    normalized["oid"] = oid.lower()
    for key in ("delivery_tree_digest", "rules_source_digest", "inventory_digest"):
        digest = normalized[key]
        if not isinstance(digest, str) or not _DIGEST_RE.fullmatch(digest.lower()):
            raise InstallationContractError(
                ContractErrorCode.IDENTITY_INCOMPLETE,
                f"source_identity.{key} must be one 64-hex digest",
            )
        normalized[key] = digest.lower()
    return normalized


def source_identity_conflicts(
    expected: Mapping[str, Any],
    observed: Mapping[str, Any],
) -> tuple[dict[str, str], ...]:
    """返回 expected/observed source identity 的稳定字段级冲突。"""

    expected_identity = validate_source_identity(expected)
    observed_identity = validate_source_identity(observed)
    return tuple(
        {
            "code": ContractErrorCode.IDENTITY_CONFLICT.value,
            "field": field,
            "expected": expected_identity[field],
            "actual": observed_identity[field],
        }
        for field in SOURCE_IDENTITY_FIELDS
        if expected_identity[field] != observed_identity[field]
    )


def resolve_source_identity(
    expected: Mapping[str, Any],
    observed: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """解析 exact source identity；任一 drift 都 fail-closed。"""

    identity = validate_source_identity(expected)
    if observed is None:
        return identity
    conflicts = source_identity_conflicts(identity, observed)
    if conflicts:
        fields = [conflict["field"] for conflict in conflicts]
        raise InstallationContractError(
            ContractErrorCode.IDENTITY_CONFLICT,
            f"source identity conflicts at fields: {fields}",
        )
    return identity


def observe_checkout_source_identity(repo_root: Path) -> dict[str, str]:
    """从一个 source checkout 产生 exact OID/tree/rules/inventory identity。

    文件树 digest 覆盖当前 delivery bytes，因此即使工作树含未提交候选，
    diagnostics 也不会把 HEAD OID 单独冒充为完整来源身份。
    """

    root = repo_root.resolve()
    delivery = root / "delivery"
    if not delivery.is_dir():
        raise ValueError("source checkout has no delivery directory")
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    oid = completed.stdout.strip().lower()
    files = sorted(
        path
        for path in delivery.rglob("*")
        if path.is_file() and not path.is_symlink()
    )
    tree_records = {
        path.relative_to(root).as_posix(): sha256(path.read_bytes()).hexdigest()
        for path in files
    }
    from meta_flow import __version__
    from meta_flow.installation.canonical import canonical_digest

    rules = delivery / "rules" / "AGENTS.md"
    inventory = delivery / "doc" / "RULES-SEMANTIC-INVENTORY.json"
    if not rules.is_file() or not inventory.is_file():
        raise ValueError("source checkout has incomplete rules identity")
    return validate_source_identity(
        {
            "source": "checkout/meta-flow",
            "version": __version__,
            "oid": oid,
            "delivery_tree_digest": canonical_digest(tree_records),
            "rules_source_digest": sha256(rules.read_bytes()).hexdigest(),
            "inventory_digest": sha256(inventory.read_bytes()).hexdigest(),
        }
    )


__all__ = [
    "component_display",
    "normalize_component",
    "observe_checkout_source_identity",
    "resolve_source_identity",
    "source_identity_conflicts",
    "validate_source_identity",
]
