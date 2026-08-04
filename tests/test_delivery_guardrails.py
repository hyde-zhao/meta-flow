from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest

from meta_flow.installation import (
    DurableJournalStore,
    build_plan,
    dispatch_lifecycle_adapter,
    normalize_component,
    validate_plan,
)
from meta_flow.installation.contracts import OPERATIONS

ROOT = Path(__file__).parents[1]
GUARDRAIL = runpy.run_path(
    str(ROOT / "scripts/check_delivery_guardrails.py"),
    run_name="__installation_guardrail_test__",
)
build_report = GUARDRAIL["build_installation_guardrail_report"]
collect_read_expansion_errors = GUARDRAIL[
    "collect_read_expansion_delivery_contract_errors"
]


def test_installation_registry_and_discovery_are_exactly_closed() -> None:
    report = build_report(ROOT)

    assert report["registry_version"] == "InstallationGuardrailRegistryV1"
    assert len(report["registered"]) == 39
    assert len(report["discovered"]) == 39
    assert report["registered_only"] == []
    assert report["discovered_only"] == []
    assert report["role_mismatch"] == []
    assert report["forbidden_hits"] == []
    assert report["fixture_exclusions"] == {
        "tests/fixtures/gov006/fixture_runner.py": (
            "task-specific temp runtime cleanup may use shutil.rmtree; "
            "real HOME/external roots are rejected first"
        )
    }


def test_discovery_finds_unregistered_consumer_and_forbidden_delete() -> None:
    report = build_report(
        ROOT,
        extra_sources={
            "meta_flow/rogue_installation.py": (
                "from meta_flow.installation import build_plan\n"
                "import shutil\n"
                "def mutate(path):\n"
                "    shutil.rmtree(path)\n"
            )
        },
    )

    assert report["discovered_only"] == [
        "meta_flow/rogue_installation.py"
    ]
    assert {
        item["rule"] for item in report["forbidden_hits"]
    } == {"recursive-delete-outside-isolated-fixture"}


def test_role_mismatch_is_reported_from_defined_source_symbol() -> None:
    report = build_report(
        ROOT,
        extra_sources={
            "meta_flow/installation/identity.py": (
                "def execute_asset_action():\n"
                "    return None\n"
            )
        },
    )

    assert report["role_mismatch"] == [
        {
            "path": "meta_flow/installation/identity.py",
            "registered_role": "source_identity",
            "discovered_role": "asset_executor",
        }
    ]


def test_platform_contract_freezes_qualified_lifecycle_surface() -> None:
    contract = json.loads(
        (
            ROOT / "delivery/doc/PLATFORM-CONTRACTS.yaml"
        ).read_text(encoding="utf-8")
    )
    lifecycle = contract["installation_lifecycle"]

    assert lifecycle["contract_version"] == "InstallationLifecycleV2"
    assert lifecycle["qualified_host_platforms"] == ["linux"]
    assert lifecycle["qualified_asset_platforms"] == ["codex", "claude"]
    assert tuple(lifecycle["canonical_operations"]) == OPERATIONS
    assert lifecycle["reinstall_normalization"] == {
        "operation": "*.upgrade",
        "force_refresh": True,
        "transaction_count": 1,
        "authorization_count": 1,
    }
    assert contract["contracts"]["codex"]["scopes"]["project"] == {
        "rules": "AGENTS.md",
        "agents": ".codex/agents",
        "skills": ".agents/skills",
    }
    assert contract["contracts"]["claude"]["scopes"]["project"] == {
        "rules": "CLAUDE.md",
        "agents": ".claude/agents",
        "skills": ".claude/skills",
    }


@pytest.mark.parametrize(
    "relative",
    ["README.md", "delivery/README.md", "delivery/doc/USER-MANUAL.md"],
)
def test_docs_expose_all_six_intents_and_safety_boundaries(
    relative: str,
) -> None:
    content = (ROOT / relative).read_text(encoding="utf-8")

    for token in (
        "Installation Lifecycle V2",
        "install",
        "upgrade",
        "uninstall",
        "reinstall",
        "recover",
        "version",
        "single-use",
        "force_refresh",
        "mutation=0",
    ):
        assert token in content
    assert "uninstall→install" in content


def test_facade_is_lazy_and_exports_owner_apis() -> None:
    assert normalize_component("agent") == ("agents", "skills")
    assert callable(build_plan)
    assert callable(validate_plan)
    assert callable(dispatch_lifecycle_adapter)
    assert DurableJournalStore.__module__ == (
        "meta_flow.installation.recovery"
    )


def test_active_delivery_read_expansion_contract_is_exact_and_evidence_bound() -> None:
    assert collect_read_expansion_errors() == []

    templates = ROOT / "delivery/skills/context-manifest-builder/templates"
    read_policy = json.loads(
        (templates / "READ-POLICY-TEMPLATE.json").read_text(encoding="utf-8")
    )
    expected = [
        "capsule_missing",
        "field_conflict",
        "schema_validation_failed",
        "human_audit",
        "summary_insufficient",
    ]
    assert read_policy["full_doc_read_allowed_when"] == expected
    assert list(read_policy["full_doc_read_reason_evidence"]) == expected


def test_active_delivery_contract_does_not_publish_legacy_expansion_reason() -> None:
    legacy_reason = "deep" + "_review"
    for relative in GUARDRAIL["ACTIVE_READ_EXPANSION_TEXT_TARGETS"]:
        assert legacy_reason not in (ROOT / relative).read_text(encoding="utf-8")
