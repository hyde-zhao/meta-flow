"""Portable, fail-closed installation manifest v2 contract.

This module deliberately models data only.  It never resolves a target path or
performs I/O, so a caller must pass the validated result to a later executor.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from meta_flow.installation.canonical import canonical_bytes, canonical_digest
from meta_flow.installation.contracts import (
    ContractErrorCode,
    InstallationContractError,
    require_exact_keys,
    validate_canonical_value,
    validate_portable_ref,
)
from meta_flow.installation.identity import validate_source_identity

MANIFEST_V2_SCHEMA_VERSION = 2
MANIFEST_V2_FIELDS = (
    "schema_version",
    "manifest_id",
    "source_identity",
    "target_ref",
    "plan_ref",
    "installation",
    "ownership",
    "transaction_ref",
    "integrity",
    "migration",
    "state",
    "manifest_digest",
)
INSTALLATION_FIELDS = (
    "installation_id",
    "platform",
    "scope",
    "component_set",
    "source_version",
    "source_oid",
    "target_digest",
    "facts_digest",
    "ownership_count",
    "operation",
    "decision_ref",
    "status",
    "transaction_generation",
    "install_digest",
)
INTEGRITY_FIELDS = ("algorithm", "content_digest", "ownership_digest", "canonical_version")
MIGRATION_FIELDS = ("from_schema", "candidate", "backup_ref", "status", "source_match")
MANIFEST_STATES = ("active", "complete", "blocked", "migrated")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


def _require_digest(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise InstallationContractError(
            ContractErrorCode.NONCANONICAL_VALUE,
            f"{field} must be one lowercase 64-hex digest",
        )
    return value


def _require_nonempty_string(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InstallationContractError(
            ContractErrorCode.NONCANONICAL_VALUE,
            f"{field} must be a non-empty string",
        )
    return value


def _validate_installation(payload: object) -> dict[str, Any]:
    installation = require_exact_keys(payload, INSTALLATION_FIELDS, field="manifest.installation")
    normalized = {key: installation[key] for key in INSTALLATION_FIELDS}
    for key in ("installation_id", "platform", "source_version", "source_oid", "operation", "status"):
        _require_nonempty_string(normalized[key], field=f"manifest.installation.{key}")
    if normalized["scope"] not in {"project", "user"}:
        raise InstallationContractError(ContractErrorCode.INVALID_ENUM, "manifest.installation.scope must be project or user")
    components = normalized["component_set"]
    if not isinstance(components, list) or not components or any(component not in {"rules", "agents", "skills"} for component in components):
        raise InstallationContractError(ContractErrorCode.INVALID_ENUM, "manifest.installation.component_set must be canonical components")
    if components != sorted(set(components), key=("rules", "agents", "skills").index):
        raise InstallationContractError(ContractErrorCode.INVALID_ENUM, "manifest.installation.component_set must be ordered and unique")
    for key in ("target_digest", "facts_digest", "install_digest"):
        _require_digest(normalized[key], field=f"manifest.installation.{key}")
    if not isinstance(normalized["ownership_count"], int) or normalized["ownership_count"] < 0:
        raise InstallationContractError(ContractErrorCode.NONCANONICAL_VALUE, "manifest.installation.ownership_count must be a non-negative integer")
    if not isinstance(normalized["transaction_generation"], int) or normalized["transaction_generation"] < 0:
        raise InstallationContractError(ContractErrorCode.NONCANONICAL_VALUE, "manifest.installation.transaction_generation must be a non-negative integer")
    validate_portable_ref(normalized["decision_ref"], field="manifest.installation.decision_ref")
    return normalized


def _validate_integrity(payload: object) -> dict[str, Any]:
    integrity = require_exact_keys(payload, INTEGRITY_FIELDS, field="manifest.integrity")
    normalized = {key: integrity[key] for key in INTEGRITY_FIELDS}
    if normalized["algorithm"] != "sha256" or normalized["canonical_version"] != 1:
        raise InstallationContractError(ContractErrorCode.INVALID_ENUM, "manifest.integrity requires sha256 and canonical_version=1")
    _require_digest(normalized["content_digest"], field="manifest.integrity.content_digest")
    _require_digest(normalized["ownership_digest"], field="manifest.integrity.ownership_digest")
    return normalized


def _validate_migration(payload: object) -> dict[str, Any]:
    migration = require_exact_keys(payload, MIGRATION_FIELDS, field="manifest.migration")
    normalized = {key: migration[key] for key in MIGRATION_FIELDS}
    if normalized["from_schema"] not in {0, 1, 2} or not isinstance(normalized["candidate"], bool) or not isinstance(normalized["source_match"], bool):
        raise InstallationContractError(ContractErrorCode.INVALID_ENUM, "manifest.migration has invalid migration flags")
    if normalized["status"] not in {"not-needed", "candidate", "migrated", "blocked"}:
        raise InstallationContractError(ContractErrorCode.INVALID_ENUM, "manifest.migration.status is invalid")
    validate_portable_ref(normalized["backup_ref"], field="manifest.migration.backup_ref")
    return normalized


def validate_manifest_v2(payload: object) -> dict[str, Any]:
    """Return a detached strict v2 manifest or raise a stable contract error.

    The validator rejects every path-like field that cannot be represented as a
    portable POSIX reference and verifies both the ownership count and the
    canonical self-digest.  No target mutation can follow a validation failure.
    """

    manifest = require_exact_keys(payload, MANIFEST_V2_FIELDS, field="manifest")
    if manifest["schema_version"] != MANIFEST_V2_SCHEMA_VERSION:
        raise InstallationContractError(ContractErrorCode.INVALID_ENUM, "manifest.schema_version must be 2")
    _require_nonempty_string(manifest["manifest_id"], field="manifest.manifest_id")
    validate_portable_ref(manifest["target_ref"], field="manifest.target_ref")
    validate_portable_ref(manifest["plan_ref"], field="manifest.plan_ref")
    validate_portable_ref(manifest["transaction_ref"], field="manifest.transaction_ref")
    if manifest["state"] not in MANIFEST_STATES:
        raise InstallationContractError(ContractErrorCode.INVALID_ENUM, f"manifest.state must be one of {list(MANIFEST_STATES)}")

    normalized: dict[str, Any] = {key: manifest[key] for key in MANIFEST_V2_FIELDS}
    normalized["source_identity"] = validate_source_identity(manifest["source_identity"])
    normalized["installation"] = _validate_installation(manifest["installation"])
    normalized["integrity"] = _validate_integrity(manifest["integrity"])
    normalized["migration"] = _validate_migration(manifest["migration"])
    ownership = manifest["ownership"]
    if not isinstance(ownership, list):
        raise InstallationContractError(ContractErrorCode.NONCANONICAL_VALUE, "manifest.ownership must be a list")
    from meta_flow.installation.ownership import validate_ownership_entry

    normalized["ownership"] = [validate_ownership_entry(entry) for entry in ownership]
    if normalized["installation"]["ownership_count"] != len(normalized["ownership"]):
        raise InstallationContractError(ContractErrorCode.NONCANONICAL_VALUE, "manifest.installation.ownership_count must equal len(manifest.ownership)")
    ownership_ids = [entry["ownership_id"] for entry in normalized["ownership"]]
    if len(ownership_ids) != len(set(ownership_ids)):
        raise InstallationContractError(ContractErrorCode.NONCANONICAL_VALUE, "manifest.ownership contains duplicate ownership_id")
    _require_digest(manifest["manifest_digest"], field="manifest.manifest_digest")
    validate_canonical_value(normalized, field="manifest")
    unsigned = {key: normalized[key] for key in MANIFEST_V2_FIELDS if key != "manifest_digest"}
    if normalized["manifest_digest"] != canonical_digest(unsigned):
        raise InstallationContractError(ContractErrorCode.NONCANONICAL_VALUE, "manifest.manifest_digest does not match canonical content")
    return normalized


def canonical_manifest_bytes(payload: object) -> bytes:
    """Validate then return canonical bytes; this has no filesystem effects."""

    return canonical_bytes(validate_manifest_v2(payload))


INSTALLATION_IDENTITY_FIELDS = (
    "installation_id",
    "platform",
    "scope",
    "component_set",
    "source_version",
    "source_oid",
    "target_digest",
)


def installation_identity_digest(payload: object) -> str:
    """Installation 身份关键组的 canonical digest（CR-076 S03，S04 验收点口径）。

    纯函数无 I/O：输入先过 ``validate_manifest_v2``，再对
    ``source_identity`` + installation 关键组（INSTALLATION_IDENTITY_FIELDS）
    求 canonical digest；同身份重建必然同值。
    """

    normalized = validate_manifest_v2(payload)
    keyset: dict[str, Any] = {
        field: normalized["installation"][field]
        for field in INSTALLATION_IDENTITY_FIELDS
    }
    keyset["source_identity"] = normalized["source_identity"]
    return canonical_digest(keyset)


def scan_migration_candidate(payload: object | None, target_facts: Mapping[str, object]) -> dict[str, object]:
    """Classify v1/missing evidence without reading or mutating a target.

    A migration is only a candidate when its declared source, target, entry and
    schema facts all match.  The returned ``mutation_count`` is permanently
    zero: execution and backup creation belong to later Stories.
    """

    required_facts = {"source_digest", "target_digest", "entry_digest", "schema_version"}
    if set(target_facts) != required_facts:
        raise InstallationContractError(ContractErrorCode.MISSING_KEY, "target_facts must contain exactly source_digest, target_digest, entry_digest, schema_version")
    for field in ("source_digest", "target_digest", "entry_digest"):
        _require_digest(target_facts[field], field=f"target_facts.{field}")
    if target_facts["schema_version"] not in {1, 2}:
        raise InstallationContractError(ContractErrorCode.INVALID_ENUM, "target_facts.schema_version must be 1 or 2")
    result: dict[str, object] = {"decision": "BLOCKED", "mutation_count": 0, "reason": "manifest-missing"}
    if payload is None:
        return result
    if not isinstance(payload, Mapping) or payload.get("schema_version") != 1:
        result["reason"] = "manifest-not-v1"
        return result
    legacy_fields = {"schema_version", "source_digest", "target_digest", "entry_digest"}
    if not legacy_fields.issubset(payload):
        result["reason"] = "manifest-v1-incomplete"
        return result
    matches = all(payload[field] == target_facts[field] for field in legacy_fields)
    if matches:
        return {"decision": "CANDIDATE", "mutation_count": 0, "reason": "v1-facts-match"}
    result["reason"] = "manifest-v1-facts-mismatch"
    return result


__all__ = [
    "INTEGRITY_FIELDS",
    "INSTALLATION_FIELDS",
    "INSTALLATION_IDENTITY_FIELDS",
    "MANIFEST_STATES",
    "MANIFEST_V2_FIELDS",
    "MANIFEST_V2_SCHEMA_VERSION",
    "MIGRATION_FIELDS",
    "canonical_manifest_bytes",
    "installation_identity_digest",
    "scan_migration_candidate",
    "validate_manifest_v2",
]
