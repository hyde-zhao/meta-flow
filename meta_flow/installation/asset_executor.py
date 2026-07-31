"""只执行已 claim、已写 journal 的项目资产 action。"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any

from meta_flow.installation.authorization import ClaimedAuthorization
from meta_flow.installation.contracts import (
    ContractErrorCode,
    InstallationContractError,
    validate_action,
    validate_portable_ref,
)
from meta_flow.installation.engine import ExecutionOutcome
from meta_flow.installation.ownership import can_remove_owned, validate_ownership_entry

SourceReader = Callable[[str], bytes]
OutcomeObserver = Callable[["AssetActionOutcome"], None]

FRESH_ASSET_ACTION_COUNTS = {
    ("codex", "rules"): 2,
    ("codex", "agents"): 9,
    ("codex", "skills"): 112,
    ("codex", "agent"): 120,
    ("codex", "full"): 121,
    ("claude", "rules"): 2,
    ("claude", "agents"): 6,
    ("claude", "skills"): 112,
    ("claude", "agent"): 117,
    ("claude", "full"): 118,
}
ASSET_ACTION_KINDS = {
    "upsert_managed_block",
    "write_exact_file",
    "write_exact_leaf",
    "remove_owned_entry",
}
ASSET_OWNERSHIP_KINDS = {"managed_block", "exact_file", "exact_leaf_set"}


class AssetExecutionError(InstallationContractError):
    """资产 action 在写入前的稳定 fail-closed 错误。"""


@dataclass(frozen=True)
class AssetExecutionContext:
    """运行时资产边界；Path 与 reader 都不会进入持久对象。"""

    claimed: ClaimedAuthorization
    expected_plan_digest: str
    operation: str
    platform: str
    scope: str
    target_root: Path
    allowed_target_refs: frozenset[str]
    source_reader: SourceReader
    journal_prepared: bool
    ownership_by_target: Mapping[str, Mapping[str, Any]]
    outcome_observer: OutcomeObserver | None = None


@dataclass(frozen=True)
class AssetActionOutcome:
    """交给 journal owner 的 action 真实结果。"""

    action_id: str
    state: str
    target_ref: str
    before_digest: str
    after_digest: str
    error_code: str
    mutation_count: int

    def as_execution_outcome(self) -> ExecutionOutcome:
        return ExecutionOutcome(
            mutation_count=self.mutation_count,
            value={
                "action_id": self.action_id,
                "state": self.state,
                "target_ref": self.target_ref,
                "before_digest": self.before_digest,
                "after_digest": self.after_digest,
                "error_code": self.error_code,
            },
        )


def fresh_asset_action_count(platform: str, component: str) -> int:
    """返回冻结的 fresh plan 基线；upgrade/uninstall 不得使用该函数。"""

    try:
        return FRESH_ASSET_ACTION_COUNTS[(platform, component)]
    except KeyError as exc:
        raise AssetExecutionError(
            ContractErrorCode.INVALID_ENUM,
            f"unsupported fresh asset selector: {platform}/{component}",
        ) from exc


def resolve_asset_target(
    contracts: Mapping[str, Any],
    *,
    platform: str,
    scope: str,
    component: str,
) -> str:
    """只从 canonical platform contract 解析一个 portable target ref。"""

    if platform not in {"codex", "claude"}:
        raise AssetExecutionError(
            ContractErrorCode.INVALID_ENUM,
            f"unsupported asset platform: {platform}",
        )
    if scope not in {"project", "user"} or component not in {
        "rules",
        "agents",
        "skills",
    }:
        raise AssetExecutionError(
            ContractErrorCode.INVALID_ENUM,
            f"unsupported asset target selector: {scope}/{component}",
        )
    try:
        value = contracts["contracts"][platform]["scopes"][scope][component]
    except (KeyError, TypeError) as exc:
        raise AssetExecutionError(
            ContractErrorCode.MISSING_KEY,
            f"platform contract is missing {platform}/{scope}/{component}",
        ) from exc
    validate_portable_ref(value, field="platform_contract.target_ref")
    return str(value)


def execute_asset_action(
    context: AssetExecutionContext,
    action: object,
) -> AssetActionOutcome:
    """执行一个 exact asset action；所有 authority 检查都发生在首写前。"""

    normalized = validate_action(action)
    _validate_context(context, normalized)
    target_ref = str(normalized["target_ref"])
    target = _safe_target(context.target_root, target_ref)
    before_digest = _target_digest(target)
    _validate_before_state(normalized["before_state"], target, before_digest)

    if normalized["action_kind"] == "upsert_managed_block":
        after_digest = _apply_managed_block(
            target,
            action=normalized,
            source_reader=context.source_reader,
        )
        mutation_count = int(after_digest != before_digest)
    elif normalized["action_kind"] in {"write_exact_file", "write_exact_leaf"}:
        after_digest = _apply_exact_bytes(
            target,
            action=normalized,
            source_reader=context.source_reader,
        )
        mutation_count = int(after_digest != before_digest)
    else:
        after_digest, mutation_count = _remove_owned(
            context,
            target,
            normalized,
        )

    outcome = AssetActionOutcome(
        action_id=str(normalized["action_id"]),
        state="applied",
        target_ref=target_ref,
        before_digest=before_digest,
        after_digest=after_digest,
        error_code="",
        mutation_count=mutation_count,
    )
    if context.outcome_observer is None:
        return outcome
    try:
        context.outcome_observer(outcome)
    except Exception:
        return AssetActionOutcome(
            action_id=outcome.action_id,
            state="partial",
            target_ref=outcome.target_ref,
            before_digest=outcome.before_digest,
            after_digest=outcome.after_digest,
            error_code="OUTCOME_HANDOFF_FAILED",
            mutation_count=outcome.mutation_count,
        )
    return outcome


def execute_asset_actions(
    context: AssetExecutionContext,
    actions: Sequence[object],
) -> ExecutionOutcome:
    """按 ordinal 执行 assets actions，并汇总真实 mutation count。"""

    validated = [validate_action(action, field=f"actions[{index}]") for index, action in enumerate(actions)]
    ordinals = [item["ordinal"] for item in validated]
    if ordinals != list(range(1, len(validated) + 1)):
        raise AssetExecutionError(
            ContractErrorCode.NONCANONICAL_VALUE,
            "asset action ordinals must be continuous and pre-sorted",
        )
    outcomes = [execute_asset_action(context, action) for action in validated]
    return ExecutionOutcome(
        mutation_count=sum(outcome.mutation_count for outcome in outcomes),
        value=tuple(outcomes),
    )


def _validate_context(
    context: AssetExecutionContext,
    action: Mapping[str, Any],
) -> None:
    if not isinstance(context.claimed, ClaimedAuthorization):
        raise AssetExecutionError(
            ContractErrorCode.IDENTITY_CONFLICT,
            "asset executor requires one claimed authorization context",
        )
    if context.claimed.plan_digest != context.expected_plan_digest:
        raise AssetExecutionError(
            ContractErrorCode.IDENTITY_CONFLICT,
            "claimed plan digest does not match executor context",
        )
    if context.operation not in {
        "assets.install",
        "assets.upgrade",
        "assets.uninstall",
    }:
        raise AssetExecutionError(
            ContractErrorCode.INVALID_ENUM,
            "asset executor only accepts assets.* operations",
        )
    if context.platform not in {"codex", "claude"} or context.scope not in {
        "project",
        "user",
    }:
        raise AssetExecutionError(
            ContractErrorCode.INVALID_ENUM,
            "asset executor only supports Codex/Claude project or user scope",
        )
    if not context.journal_prepared:
        raise AssetExecutionError(
            ContractErrorCode.IDENTITY_CONFLICT,
            "durable journal/preimage must exist before asset mutation",
        )
    if action["action_kind"] not in ASSET_ACTION_KINDS:
        raise AssetExecutionError(
            ContractErrorCode.INVALID_ENUM,
            "asset executor received a non-asset action",
        )
    if action["ownership_kind"] not in ASSET_OWNERSHIP_KINDS:
        raise AssetExecutionError(
            ContractErrorCode.INVALID_ENUM,
            "asset executor requires exact asset ownership",
        )
    expected_component = {
        "managed_block": "rules",
        "exact_file": "agents",
        "exact_leaf_set": "skills",
    }[str(action["ownership_kind"])]
    if action["component"] != expected_component:
        raise AssetExecutionError(
            ContractErrorCode.IDENTITY_CONFLICT,
            "action component and ownership kind do not match",
        )
    if action["target_ref"] not in context.allowed_target_refs:
        raise AssetExecutionError(
            ContractErrorCode.UNSAFE_PATH,
            "action target is outside the claimed mutation allowlist",
        )


def _safe_target(root: Path, target_ref: str) -> Path:
    validate_portable_ref(target_ref, field="asset.target_ref")
    root_resolved = root.resolve()
    if not root_resolved.is_dir() or root.is_symlink():
        raise AssetExecutionError(
            ContractErrorCode.UNSAFE_PATH,
            "asset target root must be one existing non-symlink directory",
        )
    target = root.joinpath(*PurePosixPath(target_ref).parts)
    current = root_resolved
    for part in PurePosixPath(target_ref).parts:
        current = current / part
        if current.is_symlink():
            raise AssetExecutionError(
                ContractErrorCode.UNSAFE_PATH,
                f"asset target traverses symlink: {target_ref}",
            )
        if current.exists() and current != target and not current.is_dir():
            raise AssetExecutionError(
                ContractErrorCode.UNSAFE_PATH,
                f"asset target parent is not a directory: {target_ref}",
            )
    if not target.resolve(strict=False).is_relative_to(root_resolved):
        raise AssetExecutionError(
            ContractErrorCode.UNSAFE_PATH,
            "asset target escapes the allowed root",
        )
    return target


def _validate_before_state(
    before_state: Mapping[str, Any],
    target: Path,
    current_digest: str,
) -> None:
    expected_exists = before_state.get("exists")
    expected_digest = before_state.get("digest")
    if not isinstance(expected_exists, bool) or not isinstance(expected_digest, str):
        raise AssetExecutionError(
            ContractErrorCode.MISSING_KEY,
            "action.before_state requires exists and digest",
        )
    if target.exists() != expected_exists:
        raise AssetExecutionError(
            ContractErrorCode.IDENTITY_CONFLICT,
            "target existence drifted from the canonical action",
        )
    if expected_exists and expected_digest != current_digest:
        raise AssetExecutionError(
            ContractErrorCode.IDENTITY_CONFLICT,
            "target digest drifted from the canonical action",
        )
    if not expected_exists and expected_digest:
        raise AssetExecutionError(
            ContractErrorCode.NONCANONICAL_VALUE,
            "absent target must use an empty before digest",
        )


def _apply_exact_bytes(
    target: Path,
    *,
    action: Mapping[str, Any],
    source_reader: SourceReader,
) -> str:
    source_ref = action["source_ref"]
    if not isinstance(source_ref, str):
        raise AssetExecutionError(
            ContractErrorCode.MISSING_KEY,
            "write action requires source_ref",
        )
    desired = source_reader(source_ref)
    if not isinstance(desired, bytes):
        raise AssetExecutionError(
            ContractErrorCode.NONCANONICAL_VALUE,
            "source reader must return bytes",
        )
    desired_digest = action["desired_state"].get("digest")
    if desired_digest != _bytes_digest(desired):
        raise AssetExecutionError(
            ContractErrorCode.IDENTITY_CONFLICT,
            "desired bytes do not match the canonical digest",
        )
    if target.exists() and target.is_dir():
        raise AssetExecutionError(
            ContractErrorCode.UNSAFE_PATH,
            "exact file/leaf target is a directory",
        )
    if target.exists() and _bytes_digest(target.read_bytes()) == desired_digest:
        return str(desired_digest)
    _write_exact_bytes(target, desired)
    return str(desired_digest)


def _apply_managed_block(
    target: Path,
    *,
    action: Mapping[str, Any],
    source_reader: SourceReader,
) -> str:
    source_ref = action["source_ref"]
    desired_state = action["desired_state"]
    if not isinstance(source_ref, str):
        raise AssetExecutionError(
            ContractErrorCode.MISSING_KEY,
            "managed block action requires source_ref",
        )
    begin = desired_state.get("begin_marker")
    end = desired_state.get("end_marker")
    desired_digest = desired_state.get("digest")
    if not all(isinstance(value, str) and value for value in (begin, end, desired_digest)):
        raise AssetExecutionError(
            ContractErrorCode.MISSING_KEY,
            "managed block desired_state requires begin_marker/end_marker/digest",
        )
    body = source_reader(source_ref)
    if not isinstance(body, bytes):
        raise AssetExecutionError(
            ContractErrorCode.NONCANONICAL_VALUE,
            "source reader must return bytes",
        )
    rendered = (
        begin.encode()
        + b"\n"
        + body.rstrip(b"\n")
        + b"\n"
        + end.encode()
        + b"\n"
    )
    if _bytes_digest(rendered) != desired_digest:
        raise AssetExecutionError(
            ContractErrorCode.IDENTITY_CONFLICT,
            "managed block render does not match desired digest",
        )
    existing = target.read_bytes() if target.exists() else b""
    updated = _replace_managed_block(existing, begin.encode(), end.encode(), rendered)
    if updated != existing:
        _write_exact_bytes(target, updated)
    return _bytes_digest(updated)


def _replace_managed_block(
    existing: bytes,
    begin: bytes,
    end: bytes,
    replacement: bytes,
) -> bytes:
    begin_count = existing.count(begin)
    end_count = existing.count(end)
    if begin_count != end_count or begin_count > 1:
        raise AssetExecutionError(
            ContractErrorCode.IDENTITY_CONFLICT,
            "managed block markers are incomplete or duplicated",
        )
    if begin_count == 0:
        separator = b"" if not existing or existing.endswith(b"\n") else b"\n"
        return existing + separator + replacement
    start = existing.index(begin)
    finish = existing.index(end)
    if finish < start:
        raise AssetExecutionError(
            ContractErrorCode.IDENTITY_CONFLICT,
            "managed block markers are reversed",
        )
    finish += len(end)
    if finish < len(existing) and existing[finish : finish + 1] == b"\n":
        finish += 1
    return existing[:start] + replacement + existing[finish:]


def _remove_owned(
    context: AssetExecutionContext,
    target: Path,
    action: Mapping[str, Any],
) -> tuple[str, int]:
    target_ref = str(action["target_ref"])
    raw_entry = context.ownership_by_target.get(target_ref)
    if raw_entry is None:
        raise AssetExecutionError(
            ContractErrorCode.IDENTITY_CONFLICT,
            "remove action has no manifest ownership entry",
        )
    entry = validate_ownership_entry(
        raw_entry,
        target_facts={"target_ref": target_ref},
    )
    if entry["ownership_type"] != action["ownership_kind"]:
        raise AssetExecutionError(
            ContractErrorCode.IDENTITY_CONFLICT,
            "remove action ownership does not match manifest",
        )
    current_digest = _target_digest(target)
    removable = can_remove_owned(
        entry,
        current_digest,
        target_facts={"target_ref": target_ref},
    )
    if target_ref not in removable:
        raise AssetExecutionError(
            ContractErrorCode.IDENTITY_CONFLICT,
            "current target is not exactly removable by manifest authority",
        )
    if entry["ownership_type"] == "managed_block":
        metadata = entry["metadata"]
        existing = target.read_bytes()
        updated = _replace_managed_block(
            existing,
            str(metadata["begin_marker"]).encode(),
            str(metadata["end_marker"]).encode(),
            b"",
        )
        if updated.strip() or not entry["metadata"].get("created", False):
            _write_exact_bytes(target, updated)
            return _bytes_digest(updated), 1
    if target.exists():
        target.unlink()
        _prune_recorded_empty_directories(context.target_root, target.parent, entry)
        return "", 1
    return "", 0


def _prune_recorded_empty_directories(
    root: Path,
    start: Path,
    entry: Mapping[str, Any],
) -> None:
    recorded = {
        root.joinpath(*PurePosixPath(ref).parts)
        for ref in entry["created_directories"]
    }
    current = start
    while current != root and current in recorded:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def _write_exact_bytes(target: Path, content: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)


def _target_digest(target: Path) -> str:
    if not target.exists():
        return ""
    if not target.is_file():
        raise AssetExecutionError(
            ContractErrorCode.UNSAFE_PATH,
            "asset target must be a regular file",
        )
    return _bytes_digest(target.read_bytes())


def _bytes_digest(content: bytes) -> str:
    return sha256(content).hexdigest()


__all__ = [
    "ASSET_ACTION_KINDS",
    "ASSET_OWNERSHIP_KINDS",
    "FRESH_ASSET_ACTION_COUNTS",
    "AssetActionOutcome",
    "AssetExecutionContext",
    "AssetExecutionError",
    "execute_asset_action",
    "execute_asset_actions",
    "fresh_asset_action_count",
    "resolve_asset_target",
]
