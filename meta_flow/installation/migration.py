"""Manifest v1→v2 的严格识别、backup 与 shared adapter 输入。"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any

from meta_flow.installation.cli_executor import normalize_reinstall
from meta_flow.installation.contracts import (
    ContractErrorCode,
    InstallationContractError,
    validate_portable_ref,
)

V1_ENTRY_KIND_MAP = {
    "managed-block": "managed_block",
    "agent": "exact_file",
    "skill": "exact_leaf_set",
}
MIGRATION_FACT_FIELDS = (
    "source_oid",
    "platform",
    "scope",
    "target_ref",
    "rules_source_digest",
    "rules_inventory_digest",
    "rules_ready",
    "active_operation",
    "portable_target_map",
)


class MigrationError(InstallationContractError):
    """迁移前置、backup 或映射的稳定阻断。"""


@dataclass(frozen=True)
class V1MigrationCandidate:
    decision: str
    reason: str
    manifest_digest: str
    source_match: bool
    entries: tuple[Mapping[str, str], ...]
    raw_bytes: bytes
    mutation_count: int = 0


@dataclass(frozen=True)
class MigrationBackup:
    backup_ref: str
    backup_digest: str
    readable: bool


@dataclass(frozen=True)
class MigrationResult:
    state: str
    reason: str
    backup_ref: str
    backup_digest: str
    mutation_count: int
    mapped_entries: tuple[Mapping[str, str], ...]


@dataclass(frozen=True)
class AdapterDispatch:
    """S05/S06 public adapter 的唯一选择与规范化结果。"""

    operation: str
    selector: Mapping[str, object]
    transaction_count: int
    authorization_count: int
    adapter_result: object


def inspect_v1_for_migration(
    payload: bytes | Mapping[str, Any] | None,
    facts: Mapping[str, Any],
) -> V1MigrationCandidate:
    """只读验证 v1；missing/corrupt/unknown 永不获得 mutation authority。"""

    _validate_migration_facts(facts)
    if not facts["rules_ready"]:
        return _blocked_candidate("rules-not-frozen")
    if facts["active_operation"]:
        return _blocked_candidate("active-v1-operation")
    if payload is None:
        return _blocked_candidate("manifest-missing")
    try:
        raw_bytes, manifest = _decode_v1(payload)
    except MigrationError as exc:
        return _blocked_candidate(
            "manifest-corrupt",
            raw_bytes=payload if isinstance(payload, bytes) else b"",
            detail=exc.code.value,
        )
    if manifest.get("manifest_version", manifest.get("schema_version")) != 1:
        return _blocked_candidate("manifest-not-v1", raw_bytes=raw_bytes)
    installs = manifest.get("installs")
    if not isinstance(installs, list):
        return _blocked_candidate("manifest-v1-incomplete", raw_bytes=raw_bytes)
    matching = [
        entry
        for entry in installs
        if isinstance(entry, Mapping)
        and entry.get("platform") == facts["platform"]
        and entry.get("scope") == facts["scope"]
    ]
    if len(matching) != 1:
        return _blocked_candidate(
            "manifest-target-not-unique",
            raw_bytes=raw_bytes,
        )
    install = matching[0]
    source_match = install.get("canonical_commit") == facts["source_oid"]
    if not source_match:
        return _blocked_candidate(
            "manifest-source-drift",
            raw_bytes=raw_bytes,
        )
    raw_entries = install.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        return _blocked_candidate(
            "manifest-v1-entries-missing",
            raw_bytes=raw_bytes,
        )
    try:
        entries = tuple(
            _normalize_v1_entry(
                entry,
                target_map=facts["portable_target_map"],
            )
            for entry in raw_entries
        )
    except MigrationError as exc:
        return _blocked_candidate(
            "manifest-v1-unknown-entry",
            raw_bytes=raw_bytes,
            detail=exc.code.value,
        )
    return V1MigrationCandidate(
        decision="CANDIDATE",
        reason="v1-facts-match",
        manifest_digest=sha256(raw_bytes).hexdigest(),
        source_match=True,
        entries=entries,
        raw_bytes=raw_bytes,
    )


def create_migration_backup(
    candidate: V1MigrationCandidate,
    *,
    backup_root: Path,
    backup_ref: str,
) -> MigrationBackup:
    """在任何 v2 mutation 前创建一份可读、digest 可验证的 v1 backup。"""

    if candidate.decision != "CANDIDATE" or not candidate.source_match:
        raise MigrationError(
            ContractErrorCode.IDENTITY_CONFLICT,
            "only one verified v1 candidate may be backed up",
        )
    validate_portable_ref(backup_ref, field="migration.backup_ref")
    root = backup_root.resolve()
    if not root.is_dir() or backup_root.is_symlink():
        raise MigrationError(
            ContractErrorCode.UNSAFE_PATH,
            "backup root must be one existing non-symlink directory",
        )
    target = root.joinpath(*PurePosixPath(backup_ref).parts)
    if not target.resolve(strict=False).is_relative_to(root):
        raise MigrationError(
            ContractErrorCode.UNSAFE_PATH,
            "backup ref escapes the scope-local backup root",
        )
    current = root
    for part in PurePosixPath(backup_ref).parts:
        current = current / part
        if current.is_symlink():
            raise MigrationError(
                ContractErrorCode.UNSAFE_PATH,
                "backup ref traverses a symlink",
            )
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        existing_digest = sha256(target.read_bytes()).hexdigest()
        if existing_digest != candidate.manifest_digest:
            raise MigrationError(
                ContractErrorCode.IDENTITY_CONFLICT,
                "existing migration backup digest does not match",
            )
    else:
        target.write_bytes(candidate.raw_bytes)
    readable = target.is_file() and target.read_bytes() == candidate.raw_bytes
    if not readable:
        raise MigrationError(
            ContractErrorCode.IDENTITY_CONFLICT,
            "migration backup is not readable or exact",
        )
    return MigrationBackup(
        backup_ref=backup_ref,
        backup_digest=candidate.manifest_digest,
        readable=True,
    )


def map_v1_to_v2(
    candidate: V1MigrationCandidate,
) -> tuple[Mapping[str, str], ...]:
    """把 verified v1 entry 映射为三类 v2 ownership 输入。"""

    if candidate.decision != "CANDIDATE":
        raise MigrationError(
            ContractErrorCode.IDENTITY_CONFLICT,
            "v1 mapping requires a verified candidate",
        )
    return tuple(
        {
            "legacy_kind": entry["kind"],
            "ownership_type": V1_ENTRY_KIND_MAP[entry["kind"]],
            "target_ref": entry["target_ref"],
            "source_ref": entry["source_ref"],
        }
        for entry in candidate.entries
    )


def execute_migration(
    candidate: V1MigrationCandidate,
    *,
    backup_root: Path,
    backup_ref: str,
    mutator: Callable[[tuple[Mapping[str, str], ...]], int],
) -> MigrationResult:
    """先 backup，再调用受控 adapter；异常保留 backup 并返回 partial。"""

    backup = create_migration_backup(
        candidate,
        backup_root=backup_root,
        backup_ref=backup_ref,
    )
    mapped = map_v1_to_v2(candidate)
    try:
        mutation_count = mutator(mapped)
    except Exception as exc:
        return MigrationResult(
            state="partial",
            reason=f"adapter-failure:{type(exc).__name__}",
            backup_ref=backup.backup_ref,
            backup_digest=backup.backup_digest,
            mutation_count=0,
            mapped_entries=mapped,
        )
    if (
        not isinstance(mutation_count, int)
        or isinstance(mutation_count, bool)
        or mutation_count < 0
    ):
        raise MigrationError(
            ContractErrorCode.NONCANONICAL_VALUE,
            "migration mutator must return a non-negative mutation count",
        )
    return MigrationResult(
        state="migrated",
        reason="",
        backup_ref=backup.backup_ref,
        backup_digest=backup.backup_digest,
        mutation_count=mutation_count,
        mapped_entries=mapped,
    )


def migration_manifest_facts(
    candidate: V1MigrationCandidate,
    backup: MigrationBackup,
) -> dict[str, object]:
    """生成当前 S03 exact 5-key migration object。"""

    if candidate.decision != "CANDIDATE" or not backup.readable:
        raise MigrationError(
            ContractErrorCode.IDENTITY_CONFLICT,
            "completed migration facts require candidate and readable backup",
        )
    return {
        "from_schema": 1,
        "candidate": False,
        "backup_ref": backup.backup_ref,
        "status": "migrated",
        "source_match": candidate.source_match,
    }


def normalize_lifecycle_reinstall(
    *,
    surface: str,
    selector: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """S08 shared adapter 使用的唯一 reinstall normalization。"""

    return normalize_reinstall(surface=surface, selector=selector)


def dispatch_lifecycle_adapter(
    *,
    surface: str,
    intent: str,
    selector: Mapping[str, object] | None,
    asset_adapter: Callable[[str, Mapping[str, object]], object],
    cli_adapter: Callable[[str, Mapping[str, object]], object],
) -> AdapterDispatch:
    """规范化 intent 后只调用一个 qualified public adapter。

    此函数不构造授权、不调用 executor internal，也不把 ``reinstall``
    暴露为第八个 operation。调用方必须把返回的 canonical operation 交给
    planner/auth/journal 链路。
    """

    if surface not in {"assets", "cli"}:
        raise MigrationError(
            ContractErrorCode.INVALID_ENUM,
            "lifecycle adapter surface must be assets or cli",
        )
    if intent not in {"install", "upgrade", "uninstall", "reinstall"}:
        raise MigrationError(
            ContractErrorCode.INVALID_ENUM,
            "lifecycle adapter intent is invalid",
        )
    normalized_selector = dict(selector or {})
    if intent == "reinstall":
        normalized = normalize_lifecycle_reinstall(
            surface=surface,
            selector=normalized_selector,
        )
        operation = str(normalized["operation"])
        normalized_selector = dict(normalized["selector"])
        transaction_count = int(normalized["transaction_count"])
        authorization_count = int(normalized["authorization_count"])
    else:
        operation = f"{surface}.{intent}"
        normalized_selector.setdefault("force_refresh", False)
        transaction_count = 1
        authorization_count = 1
    adapter = asset_adapter if surface == "assets" else cli_adapter
    result = adapter(operation, normalized_selector)
    return AdapterDispatch(
        operation=operation,
        selector=normalized_selector,
        transaction_count=transaction_count,
        authorization_count=authorization_count,
        adapter_result=result,
    )


def _decode_v1(
    payload: bytes | Mapping[str, Any],
) -> tuple[bytes, Mapping[str, Any]]:
    if isinstance(payload, bytes):
        try:
            decoded = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MigrationError(
                ContractErrorCode.NONCANONICAL_VALUE,
                "v1 manifest is not JSON-compatible YAML",
            ) from exc
        if not isinstance(decoded, Mapping):
            raise MigrationError(
                ContractErrorCode.NONCANONICAL_VALUE,
                "v1 manifest must be one mapping",
            )
        return payload, decoded
    if not isinstance(payload, Mapping):
        raise MigrationError(
            ContractErrorCode.NONCANONICAL_VALUE,
            "v1 manifest must be bytes or mapping",
        )
    raw_bytes = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return raw_bytes, payload


def _validate_migration_facts(facts: Mapping[str, Any]) -> None:
    if set(facts) != set(MIGRATION_FACT_FIELDS):
        raise MigrationError(
            ContractErrorCode.MISSING_KEY,
            f"migration facts require exactly {list(MIGRATION_FACT_FIELDS)}",
        )
    if (
        not isinstance(facts["source_oid"], str)
        or len(facts["source_oid"]) != 40
        or any(character not in "0123456789abcdef" for character in facts["source_oid"])
    ):
        raise MigrationError(
            ContractErrorCode.IDENTITY_INCOMPLETE,
            "migration source_oid must be full lowercase 40-hex",
        )
    if facts["platform"] not in {"codex", "claude"}:
        raise MigrationError(
            ContractErrorCode.INVALID_ENUM,
            "migration platform must be codex or claude",
        )
    if facts["scope"] not in {"project", "user"}:
        raise MigrationError(
            ContractErrorCode.INVALID_ENUM,
            "migration scope must be project or user",
        )
    validate_portable_ref(facts["target_ref"], field="migration.target_ref")
    for field in ("rules_source_digest", "rules_inventory_digest"):
        value = facts[field]
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise MigrationError(
                ContractErrorCode.IDENTITY_INCOMPLETE,
                f"migration {field} must be lowercase 64-hex",
            )
    if not isinstance(facts["rules_ready"], bool):
        raise MigrationError(
            ContractErrorCode.NONCANONICAL_VALUE,
            "migration rules_ready must be boolean",
        )
    if facts["active_operation"] not in {"", "install", "uninstall", "upgrade"}:
        raise MigrationError(
            ContractErrorCode.INVALID_ENUM,
            "migration active_operation is invalid",
        )
    if not isinstance(facts["portable_target_map"], Mapping):
        raise MigrationError(
            ContractErrorCode.NONCANONICAL_VALUE,
            "migration portable_target_map must be a mapping",
        )


def _normalize_v1_entry(
    entry: object,
    *,
    target_map: Mapping[str, str],
) -> Mapping[str, str]:
    if not isinstance(entry, Mapping):
        raise MigrationError(
            ContractErrorCode.NONCANONICAL_VALUE,
            "v1 entry must be one mapping",
        )
    kind = entry.get("kind")
    if kind not in V1_ENTRY_KIND_MAP:
        raise MigrationError(
            ContractErrorCode.INVALID_ENUM,
            f"unknown v1 ownership kind: {kind}",
        )
    raw_target = entry.get("path")
    if not isinstance(raw_target, str) or not raw_target:
        raise MigrationError(
            ContractErrorCode.MISSING_KEY,
            "v1 entry requires path",
        )
    target_ref = target_map.get(raw_target, raw_target)
    validate_portable_ref(target_ref, field="v1.entry.target_ref")
    source_ref = entry.get("source_ref")
    if not isinstance(source_ref, str) or not source_ref:
        source_ref = {
            "managed-block": "delivery/rules/AGENTS.md",
            "agent": f"delivery/agents/{Path(target_ref).name}",
            "skill": f"delivery/skills/{target_ref}",
        }[str(kind)]
    validate_portable_ref(source_ref, field="v1.entry.source_ref")
    return {
        "kind": str(kind),
        "target_ref": target_ref,
        "source_ref": source_ref,
    }


def _blocked_candidate(
    reason: str,
    *,
    raw_bytes: bytes = b"",
    detail: str = "",
) -> V1MigrationCandidate:
    suffix = f":{detail}" if detail else ""
    return V1MigrationCandidate(
        decision="BLOCKED",
        reason=f"{reason}{suffix}",
        manifest_digest=sha256(raw_bytes).hexdigest() if raw_bytes else "",
        source_match=False,
        entries=(),
        raw_bytes=raw_bytes,
    )


__all__ = [
    "MIGRATION_FACT_FIELDS",
    "V1_ENTRY_KIND_MAP",
    "MigrationBackup",
    "MigrationError",
    "MigrationResult",
    "AdapterDispatch",
    "V1MigrationCandidate",
    "create_migration_backup",
    "dispatch_lifecycle_adapter",
    "execute_migration",
    "inspect_v1_for_migration",
    "map_v1_to_v2",
    "migration_manifest_facts",
    "normalize_lifecycle_reinstall",
]
