from __future__ import annotations

from copy import deepcopy

import pytest

from meta_flow.installation.canonical import canonical_digest
from meta_flow.installation.contracts import ContractErrorCode, InstallationContractError
from meta_flow.installation.manifest import (
    INSTALLATION_FIELDS,
    INTEGRITY_FIELDS,
    MANIFEST_V2_FIELDS,
    MIGRATION_FIELDS,
    canonical_manifest_bytes,
    scan_migration_candidate,
    validate_manifest_v2,
)
from meta_flow.installation.ownership import (
    EXACT_FILE_METADATA_FIELDS,
    EXACT_LEAF_SET_METADATA_FIELDS,
    LEAF_FIELDS,
    MANAGED_BLOCK_METADATA_FIELDS,
    OWNERSHIP_COMMON_FIELDS,
    can_remove_owned,
    validate_ownership_entry,
)


def digest(value: str) -> str:
    return canonical_digest({"value": value})


def source_identity() -> dict[str, str]:
    return {
        "source": "meta-flow-delivery",
        "version": "0.5.1",
        "oid": "a" * 40,
        "delivery_tree_digest": "b" * 64,
        "rules_source_digest": "c" * 64,
        "inventory_digest": "d" * 64,
    }


def ownership(kind: str = "exact_file") -> dict[str, object]:
    common: dict[str, object] = {
        "ownership_id": f"ownership/{kind}",
        "ownership_type": kind,
        "target_ref": "targets/project",
        "source_ref": "delivery/agents/meta-dev.md",
        "source_digest": digest("source"),
        "installed_digest": digest("installed"),
        "owner_ref": "manifests/install-001",
        "generation": 1,
        "state": "active",
        "created_directories": ["targets"],
        "metadata": {},
        "ownership_digest": "",
    }
    if kind == "exact_file":
        common["metadata"] = {
            "file_ref": "targets/project/AGENTS.md",
            "recorded_digest": common["installed_digest"],
            "created": True,
            "mode": "replace-only",
            "write_policy": "digest-match",
        }
    elif kind == "exact_leaf_set":
        common["metadata"] = {
            "root_ref": "targets/project/.agents",
            "leaves": [
                {
                    "leaf_ref": "targets/project/.agents/skills/example/SKILL.md",
                    "source_ref": "delivery/skills/example/SKILL.md",
                    "installed_digest": digest("leaf"),
                    "state": "active",
                    "created": True,
                    "leaf_digest": digest("leaf-record"),
                }
            ],
            "created_directories": ["targets/project/.agents", "targets/project/.agents/skills"],
            "leaf_count": 1,
            "prune_policy": "empty-recorded-directories-only",
        }
    else:
        common["metadata"] = {
            "begin_marker": "<!-- myflow:managed:begin -->",
            "end_marker": "<!-- myflow:managed:end -->",
            "block_digest": digest("block"),
            "render_digest": digest("render"),
            "platform": "codex",
            "content_ref": "delivery/rules/AGENTS.md",
            "preimage_ref": "journals/install-001/preimage",
            "marker_version": 1,
        }
    common["ownership_digest"] = canonical_digest({key: common[key] for key in OWNERSHIP_COMMON_FIELDS if key != "ownership_digest"})
    return common


def manifest(entries: list[dict[str, object]] | None = None) -> dict[str, object]:
    entries = entries if entries is not None else [ownership()]
    payload: dict[str, object] = {
        "schema_version": 2,
        "manifest_id": "manifests/install-001",
        "source_identity": source_identity(),
        "target_ref": "targets/project",
        "plan_ref": "plans/install-001",
        "installation": {
            "installation_id": "install-001",
            "platform": "codex",
            "scope": "project",
            "component_set": ["agents", "skills"],
            "source_version": "0.5.1",
            "source_oid": "a" * 40,
            "target_digest": digest("target"),
            "facts_digest": digest("facts"),
            "ownership_count": len(entries),
            "operation": "install",
            "decision_ref": "decisions/install-001",
            "status": "complete",
            "transaction_generation": 1,
            "install_digest": digest("install"),
        },
        "ownership": entries,
        "transaction_ref": "transactions/install-001",
        "integrity": {
            "algorithm": "sha256",
            "content_digest": digest("content"),
            "ownership_digest": canonical_digest(entries),
            "canonical_version": 1,
        },
        "migration": {
            "from_schema": 2,
            "candidate": False,
            "backup_ref": "journals/install-001/backup",
            "status": "not-needed",
            "source_match": True,
        },
        "state": "complete",
        "manifest_digest": "",
    }
    payload["manifest_digest"] = canonical_digest({key: payload[key] for key in MANIFEST_V2_FIELDS if key != "manifest_digest"})
    return payload


def test_manifest_and_ownership_common_schemas_have_exact_keys() -> None:
    value = manifest()
    entry = value["ownership"][0]

    assert tuple(value) == MANIFEST_V2_FIELDS
    assert len(value) == 12
    assert tuple(entry) == OWNERSHIP_COMMON_FIELDS
    assert len(entry) == 12
    assert tuple(value["installation"]) == INSTALLATION_FIELDS
    assert tuple(value["integrity"]) == INTEGRITY_FIELDS
    assert tuple(value["migration"]) == MIGRATION_FIELDS
    validate_manifest_v2(value)


def test_portable_manifest_round_trip_has_stable_bytes_and_digest() -> None:
    first = manifest()
    second = deepcopy(first)
    second["source_identity"] = dict(reversed(list(first["source_identity"].items())))

    assert canonical_manifest_bytes(first) == canonical_manifest_bytes(second)
    assert validate_manifest_v2(first)["manifest_digest"] == validate_manifest_v2(second)["manifest_digest"]


@pytest.mark.parametrize("field", ["target_ref", "plan_ref", "transaction_ref"])
def test_manifest_rejects_absolute_portable_refs(field: str) -> None:
    value = manifest()
    value[field] = "/workspace/unsafe"
    with pytest.raises(InstallationContractError) as exc_info:
        validate_manifest_v2(value)
    assert exc_info.value.code is ContractErrorCode.UNSAFE_PATH


@pytest.mark.parametrize(
    ("kind", "metadata_fields"),
    [
        ("managed_block", MANAGED_BLOCK_METADATA_FIELDS),
        ("exact_file", EXACT_FILE_METADATA_FIELDS),
        ("exact_leaf_set", EXACT_LEAF_SET_METADATA_FIELDS),
    ],
)
def test_each_ownership_type_has_exact_metadata_and_positive_removal(kind: str, metadata_fields: tuple[str, ...]) -> None:
    entry = ownership(kind)
    normalized = validate_ownership_entry(entry)
    assert tuple(normalized["metadata"]) == metadata_fields
    if kind == "managed_block":
        assert can_remove_owned(entry, entry["metadata"]["block_digest"]) == (entry["target_ref"],)
    elif kind == "exact_file":
        assert can_remove_owned(entry, entry["installed_digest"]) == (entry["target_ref"],)
    else:
        leaf = entry["metadata"]["leaves"][0]
        assert tuple(leaf) == LEAF_FIELDS
        assert can_remove_owned(entry, {leaf["leaf_ref"]: leaf["installed_digest"]}) == (leaf["leaf_ref"],)


@pytest.mark.parametrize("kind", ["managed_block", "exact_file"])
def test_modified_file_or_block_is_never_selected_for_removal(kind: str) -> None:
    entry = ownership(kind)
    assert can_remove_owned(entry, digest("user-modified")) == ()


def test_leaf_set_preserves_foreign_sibling_and_unrecorded_leaf() -> None:
    entry = ownership("exact_leaf_set")
    leaf = entry["metadata"]["leaves"][0]
    observed = {
        leaf["leaf_ref"]: leaf["installed_digest"],
        "targets/project/.agents/skills/user/SKILL.md": digest("foreign"),
    }

    assert can_remove_owned(entry, observed) == (leaf["leaf_ref"],)
    assert can_remove_owned(entry, {"targets/project/.agents/skills/user/SKILL.md": digest("foreign")}) == ()


def test_ownership_rejects_unknown_leaf_and_absolute_metadata_ref() -> None:
    entry = ownership("exact_leaf_set")
    entry["metadata"]["leaves"][0]["foreign"] = True
    with pytest.raises(InstallationContractError) as unknown:
        validate_ownership_entry(entry)
    assert unknown.value.code is ContractErrorCode.UNKNOWN_KEY

    entry = ownership("exact_file")
    entry["metadata"]["file_ref"] = "C:/workspace/AGENTS.md"
    with pytest.raises(InstallationContractError) as unsafe:
        validate_ownership_entry(entry)
    assert unsafe.value.code is ContractErrorCode.UNSAFE_PATH


def test_missing_or_mismatched_v1_scan_is_read_only_and_fail_closed() -> None:
    facts = {
        "source_digest": digest("source"),
        "target_digest": digest("target"),
        "entry_digest": digest("entry"),
        "schema_version": 1,
    }
    assert scan_migration_candidate(None, facts) == {"decision": "BLOCKED", "mutation_count": 0, "reason": "manifest-missing"}
    assert scan_migration_candidate({"schema_version": 1, "source_digest": facts["source_digest"], "target_digest": digest("other"), "entry_digest": facts["entry_digest"]}, facts)["mutation_count"] == 0
    assert scan_migration_candidate({"schema_version": 1, "source_digest": facts["source_digest"], "target_digest": facts["target_digest"], "entry_digest": facts["entry_digest"]}, facts) == {"decision": "CANDIDATE", "mutation_count": 0, "reason": "v1-facts-match"}
