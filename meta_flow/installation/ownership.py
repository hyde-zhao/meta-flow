"""Exact, digest-gated ownership predicates for manifest v2."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from meta_flow.installation.canonical import canonical_digest
from meta_flow.installation.contracts import (
    ContractErrorCode,
    InstallationContractError,
    require_exact_keys,
    validate_canonical_value,
    validate_portable_ref,
)

OWNERSHIP_TYPES = ("managed_block", "exact_file", "exact_leaf_set")
OWNERSHIP_COMMON_FIELDS = (
    "ownership_id",
    "ownership_type",
    "target_ref",
    "source_ref",
    "source_digest",
    "installed_digest",
    "owner_ref",
    "generation",
    "state",
    "created_directories",
    "metadata",
    "ownership_digest",
)
EXACT_FILE_METADATA_FIELDS = ("file_ref", "recorded_digest", "created", "mode", "write_policy")
EXACT_LEAF_SET_METADATA_FIELDS = ("root_ref", "leaves", "created_directories", "leaf_count", "prune_policy")
LEAF_FIELDS = ("leaf_ref", "source_ref", "installed_digest", "state", "created", "leaf_digest")
MANAGED_BLOCK_METADATA_FIELDS = (
    "begin_marker",
    "end_marker",
    "block_digest",
    "render_digest",
    "platform",
    "content_ref",
    "preimage_ref",
    "marker_version",
)
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


def _digest(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise InstallationContractError(ContractErrorCode.NONCANONICAL_VALUE, f"{field} must be one lowercase 64-hex digest")
    return value


def _portable(value: object, *, field: str) -> str:
    validate_portable_ref(value, field=field)
    return value  # type: ignore[return-value]


def _validate_leaf(payload: object, *, index: int) -> dict[str, Any]:
    leaf = require_exact_keys(payload, LEAF_FIELDS, field=f"ownership.metadata.leaves[{index}]")
    normalized = {key: leaf[key] for key in LEAF_FIELDS}
    _portable(normalized["leaf_ref"], field=f"ownership.metadata.leaves[{index}].leaf_ref")
    _portable(normalized["source_ref"], field=f"ownership.metadata.leaves[{index}].source_ref")
    _digest(normalized["installed_digest"], field=f"ownership.metadata.leaves[{index}].installed_digest")
    _digest(normalized["leaf_digest"], field=f"ownership.metadata.leaves[{index}].leaf_digest")
    if normalized["state"] not in {"active", "stale", "removed"} or not isinstance(normalized["created"], bool):
        raise InstallationContractError(ContractErrorCode.INVALID_ENUM, f"ownership.metadata.leaves[{index}] has invalid state or created")
    return normalized


def _validate_metadata(ownership_type: str, payload: object) -> dict[str, Any]:
    if ownership_type == "exact_file":
        metadata = require_exact_keys(payload, EXACT_FILE_METADATA_FIELDS, field="ownership.metadata")
        normalized = {key: metadata[key] for key in EXACT_FILE_METADATA_FIELDS}
        _portable(normalized["file_ref"], field="ownership.metadata.file_ref")
        _digest(normalized["recorded_digest"], field="ownership.metadata.recorded_digest")
        if not isinstance(normalized["created"], bool) or normalized["mode"] not in {"replace-only", "create-only"} or normalized["write_policy"] not in {"digest-match", "never-force"}:
            raise InstallationContractError(ContractErrorCode.INVALID_ENUM, "exact_file metadata has invalid policy")
        return normalized
    if ownership_type == "exact_leaf_set":
        metadata = require_exact_keys(payload, EXACT_LEAF_SET_METADATA_FIELDS, field="ownership.metadata")
        normalized = {key: metadata[key] for key in EXACT_LEAF_SET_METADATA_FIELDS}
        _portable(normalized["root_ref"], field="ownership.metadata.root_ref")
        leaves = normalized["leaves"]
        if not isinstance(leaves, list) or not leaves:
            raise InstallationContractError(ContractErrorCode.NONCANONICAL_VALUE, "exact_leaf_set metadata.leaves must be a non-empty list")
        normalized["leaves"] = [_validate_leaf(leaf, index=index) for index, leaf in enumerate(leaves)]
        refs = [leaf["leaf_ref"] for leaf in normalized["leaves"]]
        if len(refs) != len(set(refs)) or normalized["leaf_count"] != len(refs):
            raise InstallationContractError(ContractErrorCode.NONCANONICAL_VALUE, "exact_leaf_set leaves must be unique and match leaf_count")
        directories = normalized["created_directories"]
        if not isinstance(directories, list):
            raise InstallationContractError(ContractErrorCode.NONCANONICAL_VALUE, "exact_leaf_set created_directories must be a list")
        for index, directory in enumerate(directories):
            _portable(directory, field=f"ownership.metadata.created_directories[{index}]")
        if normalized["prune_policy"] != "empty-recorded-directories-only":
            raise InstallationContractError(ContractErrorCode.INVALID_ENUM, "exact_leaf_set must only prune empty recorded directories")
        return normalized
    metadata = require_exact_keys(payload, MANAGED_BLOCK_METADATA_FIELDS, field="ownership.metadata")
    normalized = {key: metadata[key] for key in MANAGED_BLOCK_METADATA_FIELDS}
    for key in ("begin_marker", "end_marker", "platform"):
        if not isinstance(normalized[key], str) or not normalized[key]:
            raise InstallationContractError(ContractErrorCode.NONCANONICAL_VALUE, f"managed_block metadata.{key} must be non-empty")
    if normalized["begin_marker"] == normalized["end_marker"] or normalized["marker_version"] != 1:
        raise InstallationContractError(ContractErrorCode.INVALID_ENUM, "managed_block markers must be distinct and marker_version=1")
    for key in ("block_digest", "render_digest"):
        _digest(normalized[key], field=f"ownership.metadata.{key}")
    for key in ("content_ref", "preimage_ref"):
        _portable(normalized[key], field=f"ownership.metadata.{key}")
    return normalized


def validate_ownership_entry(payload: object, target_facts: Mapping[str, object] | None = None) -> dict[str, Any]:
    """Validate one exact ownership entry and return a detached copy.

    ``target_facts`` is intentionally optional: it lets executors assert the
    observed portable target before asking for removal, while schema consumers
    remain pure and do not need a target checkout.
    """

    entry = require_exact_keys(payload, OWNERSHIP_COMMON_FIELDS, field="ownership")
    normalized = {key: entry[key] for key in OWNERSHIP_COMMON_FIELDS}
    if not isinstance(normalized["ownership_id"], str) or not normalized["ownership_id"]:
        raise InstallationContractError(ContractErrorCode.NONCANONICAL_VALUE, "ownership.ownership_id must be non-empty")
    if normalized["ownership_type"] not in OWNERSHIP_TYPES:
        raise InstallationContractError(ContractErrorCode.INVALID_ENUM, f"ownership.ownership_type must be one of {list(OWNERSHIP_TYPES)}")
    for key in ("target_ref", "source_ref", "owner_ref"):
        _portable(normalized[key], field=f"ownership.{key}")
    for key in ("source_digest", "installed_digest", "ownership_digest"):
        _digest(normalized[key], field=f"ownership.{key}")
    if not isinstance(normalized["generation"], int) or normalized["generation"] < 0:
        raise InstallationContractError(ContractErrorCode.NONCANONICAL_VALUE, "ownership.generation must be a non-negative integer")
    if normalized["state"] not in {"active", "stale", "removed"}:
        raise InstallationContractError(ContractErrorCode.INVALID_ENUM, "ownership.state must be active, stale, or removed")
    if not isinstance(normalized["created_directories"], list):
        raise InstallationContractError(ContractErrorCode.NONCANONICAL_VALUE, "ownership.created_directories must be a list")
    for index, directory in enumerate(normalized["created_directories"]):
        _portable(directory, field=f"ownership.created_directories[{index}]")
    normalized["metadata"] = _validate_metadata(normalized["ownership_type"], normalized["metadata"])
    if target_facts is not None and target_facts.get("target_ref") != normalized["target_ref"]:
        raise InstallationContractError(ContractErrorCode.IDENTITY_CONFLICT, "ownership target facts do not match target_ref")
    validate_canonical_value(normalized, field="ownership")
    unsigned = {key: normalized[key] for key in OWNERSHIP_COMMON_FIELDS if key != "ownership_digest"}
    if normalized["ownership_digest"] != canonical_digest(unsigned):
        raise InstallationContractError(ContractErrorCode.NONCANONICAL_VALUE, "ownership.ownership_digest does not match canonical content")
    return normalized


def can_remove_owned(
    entry: object,
    current_digest: str | Mapping[str, str],
    *,
    target_facts: Mapping[str, object] | None = None,
) -> tuple[str, ...]:
    """Return precisely removable portable refs, otherwise an empty tuple.

    This predicate is fail-closed.  It neither opens paths nor assumes that an
    unrecorded leaf or a parent directory was installed by Meta Flow.
    """

    normalized = validate_ownership_entry(entry, target_facts)
    kind = normalized["ownership_type"]
    metadata = normalized["metadata"]
    if kind == "exact_file":
        return (normalized["target_ref"],) if isinstance(current_digest, str) and current_digest == normalized["installed_digest"] else ()
    if kind == "managed_block":
        return (normalized["target_ref"],) if isinstance(current_digest, str) and current_digest == metadata["block_digest"] else ()
    if not isinstance(current_digest, Mapping):
        return ()
    return tuple(
        leaf["leaf_ref"]
        for leaf in metadata["leaves"]
        if current_digest.get(leaf["leaf_ref"]) == leaf["installed_digest"]
    )


def assert_activatable(
    entry: object,
    current_digest: str | Mapping[str, str],
) -> tuple[str, ...]:
    """激活前置断言（S04）：目标就位且 state=active 才返回空 conflicts。

    比对口径复用 :func:`can_remove_owned`（exact_file=installed_digest、
    managed_block=block_digest、exact_leaf_set=逐 leaf 全量相等）；fail-closed，
    不匹配即返回 typed conflict 字符串，不抛异常。
    """

    normalized = validate_ownership_entry(entry)
    target_ref = normalized["target_ref"]
    if normalized["state"] != "active":
        return (f"OWNERSHIP-ACTIVATION-CONFLICT:{target_ref}:state={normalized['state']}",)
    kind = normalized["ownership_type"]
    if kind == "exact_file":
        matched = isinstance(current_digest, str) and current_digest == normalized["installed_digest"]
    elif kind == "managed_block":
        matched = isinstance(current_digest, str) and current_digest == normalized["metadata"]["block_digest"]
    else:
        matched = isinstance(current_digest, Mapping) and all(
            current_digest.get(leaf["leaf_ref"]) == leaf["installed_digest"]
            for leaf in normalized["metadata"]["leaves"]
        )
    return () if matched else (f"OWNERSHIP-ACTIVATION-CONFLICT:{target_ref}:digest-mismatch",)


__all__ = [
    "EXACT_FILE_METADATA_FIELDS",
    "EXACT_LEAF_SET_METADATA_FIELDS",
    "LEAF_FIELDS",
    "MANAGED_BLOCK_METADATA_FIELDS",
    "OWNERSHIP_COMMON_FIELDS",
    "OWNERSHIP_TYPES",
    "assert_activatable",
    "can_remove_owned",
    "validate_ownership_entry",
]
