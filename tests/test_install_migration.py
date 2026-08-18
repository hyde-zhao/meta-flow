from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from meta_flow import cli
from meta_flow.installation.migration import (
    MigrationError,
    create_migration_backup,
    dispatch_lifecycle_adapter,
    execute_migration,
    inspect_v1_for_migration,
    map_v1_to_v2,
    migration_manifest_facts,
    normalize_lifecycle_reinstall,
)

OID = "a" * 40
DIGEST = "b" * 64


def _facts(**updates: object) -> dict[str, object]:
    facts: dict[str, object] = {
        "source_oid": OID,
        "platform": "codex",
        "scope": "project",
        "target_ref": "fixture/project",
        "rules_source_digest": DIGEST,
        "rules_inventory_digest": DIGEST,
        "rules_ready": True,
        "active_operation": "",
        "portable_target_map": {},
    }
    facts.update(updates)
    return facts


def _v1_manifest() -> dict[str, object]:
    return {
        "manifest_version": 1,
        "installs": [
            {
                "platform": "codex",
                "scope": "project",
                "canonical_commit": OID,
                "entries": [
                    {
                        "kind": "managed-block",
                        "path": "AGENTS.md",
                        "source_ref": "delivery/rules/AGENTS.md",
                    },
                    {
                        "kind": "agent",
                        "path": ".codex/agents/meta-dev.toml",
                        "source_ref": "delivery/agents/meta-dev.toml",
                    },
                    {
                        "kind": "skill",
                        "path": ".agents/skills/state-router/SKILL.md",
                        "source_ref": "delivery/skills/state-router/SKILL.md",
                        "remove_path": ".agents/skills/state-router",
                    },
                ],
            }
        ],
    }


def test_valid_v1_is_read_only_candidate_with_exact_mapping() -> None:
    candidate = inspect_v1_for_migration(_v1_manifest(), _facts())
    mapped = map_v1_to_v2(candidate)

    assert candidate.decision == "CANDIDATE"
    assert candidate.mutation_count == 0
    assert [entry["ownership_type"] for entry in mapped] == [
        "managed_block",
        "exact_file",
        "exact_leaf_set",
    ]
    assert mapped[2]["target_ref"].endswith("SKILL.md")
    assert all(
        entry["target_ref"] != ".agents/skills/state-router"
        for entry in mapped
    )


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (None, "manifest-missing"),
        (b"{broken", "manifest-corrupt"),
        ({"manifest_version": 2, "installs": []}, "manifest-not-v1"),
    ],
)
def test_missing_or_corrupt_v1_is_blocked_without_mutation(
    payload,
    reason: str,
) -> None:
    candidate = inspect_v1_for_migration(payload, _facts())

    assert candidate.decision == "BLOCKED"
    assert candidate.reason.startswith(reason)
    assert candidate.mutation_count == 0


def test_unknown_owner_and_source_drift_are_blocked() -> None:
    manifest = _v1_manifest()
    manifest["installs"][0]["entries"][0]["kind"] = "directory"
    unknown = inspect_v1_for_migration(manifest, _facts())
    drifted = inspect_v1_for_migration(
        _v1_manifest(),
        _facts(source_oid="c" * 40),
    )

    assert unknown.reason.startswith("manifest-v1-unknown-entry")
    assert drifted.reason == "manifest-source-drift"
    assert unknown.mutation_count == drifted.mutation_count == 0


def test_rules_must_be_frozen_before_candidate_is_admitted() -> None:
    blocked = inspect_v1_for_migration(
        _v1_manifest(),
        _facts(rules_ready=False),
    )
    admitted = inspect_v1_for_migration(_v1_manifest(), _facts())

    assert blocked.reason == "rules-not-frozen"
    assert admitted.decision == "CANDIDATE"


def test_backup_is_readable_before_mutator_runs(tmp_path: Path) -> None:
    candidate = inspect_v1_for_migration(_v1_manifest(), _facts())
    observations: list[bool] = []

    def mutator(_entries) -> int:
        observations.append((tmp_path / "backups/v1.json").is_file())
        return 1

    result = execute_migration(
        candidate,
        backup_root=tmp_path,
        backup_ref="backups/v1.json",
        mutator=mutator,
    )

    assert observations == [True]
    assert result.state == "migrated"
    assert result.mutation_count == 1
    assert (tmp_path / result.backup_ref).read_bytes() == candidate.raw_bytes


def test_partial_migration_preserves_backup_and_true_result(tmp_path: Path) -> None:
    candidate = inspect_v1_for_migration(_v1_manifest(), _facts())

    result = execute_migration(
        candidate,
        backup_root=tmp_path,
        backup_ref="backups/v1.json",
        mutator=lambda _entries: (_ for _ in ()).throw(OSError("injected")),
    )

    assert result.state == "partial"
    assert result.reason == "adapter-failure:OSError"
    assert result.mutation_count == 0
    assert (tmp_path / result.backup_ref).is_file()


def test_existing_backup_must_match_exact_v1_bytes(tmp_path: Path) -> None:
    candidate = inspect_v1_for_migration(_v1_manifest(), _facts())
    path = tmp_path / "backups/v1.json"
    path.parent.mkdir()
    path.write_bytes(b"different")

    with pytest.raises(MigrationError, match="backup digest"):
        create_migration_backup(
            candidate,
            backup_root=tmp_path,
            backup_ref="backups/v1.json",
        )


def test_migration_manifest_facts_use_current_s03_contract(tmp_path: Path) -> None:
    candidate = inspect_v1_for_migration(_v1_manifest(), _facts())
    backup = create_migration_backup(
        candidate,
        backup_root=tmp_path,
        backup_ref="backups/v1.json",
    )

    assert migration_manifest_facts(candidate, backup) == {
        "from_schema": 1,
        "candidate": False,
        "backup_ref": "backups/v1.json",
        "status": "migrated",
        "source_match": True,
    }


@pytest.mark.parametrize("surface", ["assets", "cli"])
def test_reinstall_is_one_upgrade_force_refresh_transaction(
    surface: str,
) -> None:
    normalized = normalize_lifecycle_reinstall(
        surface=surface,
        selector={"component": "rules"},
    )

    assert normalized["operation"] == f"{surface}.upgrade"
    assert normalized["selector"]["force_refresh"] is True
    assert normalized["transaction_count"] == 1
    assert normalized["authorization_count"] == 1


def test_bytes_and_mapping_payloads_have_stable_candidate_digest() -> None:
    payload = _v1_manifest()
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()

    mapping_candidate = inspect_v1_for_migration(payload, _facts())
    bytes_candidate = inspect_v1_for_migration(rendered, _facts())

    assert mapping_candidate.manifest_digest == bytes_candidate.manifest_digest


@pytest.mark.parametrize("surface", ["assets", "cli"])
def test_shared_dispatch_selects_exactly_one_qualified_adapter(
    surface: str,
) -> None:
    calls: list[tuple[str, str, dict[str, object]]] = []

    def asset(operation: str, selector) -> str:
        calls.append(("assets", operation, dict(selector)))
        return "asset-result"

    def cli_adapter(operation: str, selector) -> str:
        calls.append(("cli", operation, dict(selector)))
        return "cli-result"

    result = dispatch_lifecycle_adapter(
        surface=surface,
        intent="reinstall",
        selector={"component": "rules"},
        asset_adapter=asset,
        cli_adapter=cli_adapter,
    )

    assert calls == [
        (
            surface,
            f"{surface}.upgrade",
            {"component": "rules", "force_refresh": True},
        )
    ]
    assert result.operation == f"{surface}.upgrade"
    assert result.transaction_count == result.authorization_count == 1


def test_public_reinstall_dispatches_one_upgrade_not_legacy_helper() -> None:
    calls: list[tuple[str, list[str]]] = []
    args = ["codex", "--scope", "project", "--project-dir", "fixture"]

    with (
        patch.object(
            cli,
            "_run_installer",
            side_effect=lambda command, forwarded: calls.append(
                (command, forwarded)
            ),
        ),
        patch.object(cli, "_run_reinstaller") as legacy,
    ):
        cli._run_lifecycle_reinstaller(args)

    assert calls == [("upgrade", [*args, "--force-refresh"])]
    legacy.assert_not_called()


@pytest.mark.parametrize(
    ("intent", "expected_mode", "force_refresh"),
    [
        ("upgrade", "upgrade", False),
        ("reinstall", "upgrade", True),
    ],
)
def test_install_script_public_parser_normalizes_lifecycle_intent(
    intent: str,
    expected_mode: str,
    force_refresh: bool,
) -> None:
    script = Path(__file__).parents[1] / "delivery/scripts/install.py"
    namespace = runpy.run_path(
        str(script),
        run_name="__meta_flow_install_parser_test__",
    )
    with patch.object(
        sys,
        "argv",
        [
            "meta-flow",
            intent,
            "codex",
            "--scope",
            "project",
            "--project-dir",
            "fixture",
        ],
    ):
        parsed = namespace["parse_args"]()

    assert parsed.requested_intent == intent
    assert parsed.mode == expected_mode
    assert parsed.force_refresh is force_refresh


def test_public_main_never_references_two_transaction_reinstaller() -> None:
    import inspect

    boundary = inspect.getsource(cli.main)
    source = inspect.getsource(cli._dispatch_main)

    assert "_dispatch_main()" in boundary
    assert "_run_reinstaller(" not in source
    assert "_run_lifecycle_reinstaller(" in source
