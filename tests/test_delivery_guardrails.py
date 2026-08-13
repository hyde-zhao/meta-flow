from __future__ import annotations

import json
import os
import runpy
from copy import deepcopy
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
collect_canonical_mirror_errors = GUARDRAIL["collect_canonical_mirror_errors"]
collect_delivery_runtime_contract_errors = GUARDRAIL[
    "collect_delivery_runtime_contract_errors"
]
collect_core_lifecycle_dogfood_errors = GUARDRAIL[
    "collect_core_lifecycle_dogfood_errors"
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


def test_core_lifecycle_dogfood_is_a_documented_release_hard_gate() -> None:
    assert collect_core_lifecycle_dogfood_errors() == []

    command = GUARDRAIL["CORE_LIFECYCLE_DOGFOOD_COMMAND"]
    for relative in GUARDRAIL["CORE_LIFECYCLE_DOGFOOD_DOCS"]:
        assert command in (ROOT / relative).read_text(encoding="utf-8")


def test_core_lifecycle_dogfood_forbids_manual_projection_refresh(tmp_path: Path) -> None:
    fixture = tmp_path / "tests/fixtures/core_lifecycle_dogfood.py"
    fixture.parent.mkdir(parents=True)
    fixture.write_text(
        "def _prepare_work():\n"
        "    refresh_formal_truth_projection()\n\n"
        "def _authorization_file():\n"
        "    pass\n",
        encoding="utf-8",
    )

    errors = collect_core_lifecycle_dogfood_errors(tmp_path)

    assert any("must not manually refresh" in error for error in errors)


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


def test_cr_guardrail_tokens_follow_real_owners_without_facade_backfill() -> None:
    assert GUARDRAIL["collect_native_cr_governance_errors"]() == []
    assert GUARDRAIL["collect_requirement_intake_routing_errors"]() == []
    assert GUARDRAIL["collect_cr058_execution_closure_errors"]() == []
    assert GUARDRAIL["collect_retired_cr_facade_token_errors"]() == []


def _write_mirror_fixture(root: Path, mirror_content: str) -> tuple[tuple[str, str], ...]:
    canonical = root / "canonical/SKILL.md"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("---\nname: fixture\n---\n\n# Canonical\n", encoding="utf-8")
    mirror = root / "mirror/SKILL.md"
    mirror.parent.mkdir(parents=True)
    mirror.write_text(mirror_content, encoding="utf-8")
    return (("canonical/SKILL.md", "mirror/SKILL.md"),)


def test_canonical_mirror_accepts_one_renderer_marker(tmp_path: Path) -> None:
    marker = (
        "<!-- myflow-managed: version=1.0.0 canonical-commit=abc1234 "
        "generated=2026-08-04T14:00:00Z -->"
    )
    pairs = _write_mirror_fixture(
        tmp_path,
        f"---\nname: fixture\n---\n{marker}\n\n# Canonical\n",
    )

    assert collect_canonical_mirror_errors(tmp_path, pairs) == []


@pytest.mark.parametrize(
    "mirror_content",
    [
        "---\nname: fixture\n---\n\n# Canonical\n",
        (
            "<!-- myflow-managed: version=1.0.0 canonical-commit=abc1234 "
            "generated=2026-08-04T14:00:00Z -->\n\n"
            "---\nname: fixture\n---\n\n# Canonical\n"
        ),
        (
            "---\nname: fixture\n---\n"
            "<!-- myflow-managed: version=1.0.0 canonical-commit=abc1234 "
            "generated=2026-08-04T14:00:00Z -->\n"
            "<!-- myflow-managed: version=1.0.0 canonical-commit=abc1234 "
            "generated=2026-08-04T14:00:00Z -->\n\n# Canonical\n"
        ),
        (
            "---\nname: fixture\n---\n"
            "<!-- myflow-managed: version=1.0.0 canonical-commit=abc1234 -->\n\n"
            "# Canonical\n"
        ),
        (
            "---\nname: changed\n---\n"
            "<!-- myflow-managed: version=1.0.0 canonical-commit=abc1234 "
            "generated=2026-08-04T14:00:00Z -->\n\n# Canonical\n"
        ),
        (
            "---\nname: fixture\n---\n"
            "<!-- myflow-managed: version=1.0.0 canonical-commit=abc1234 "
            "generated=2026-08-04T14:00:00Z -->\n\n# Drift\n"
        ),
    ],
)
def test_canonical_mirror_rejects_missing_misplaced_or_drifted_marker(
    tmp_path: Path,
    mirror_content: str,
) -> None:
    pairs = _write_mirror_fixture(tmp_path, mirror_content)

    assert collect_canonical_mirror_errors(tmp_path, pairs) == [
        "CR-058 canonical/mirror drift: canonical/SKILL.md / mirror/SKILL.md"
    ]


def test_canonical_mirror_rejects_directory_and_symlink(tmp_path: Path) -> None:
    canonical = tmp_path / "canonical/SKILL.md"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("canonical\n", encoding="utf-8")
    mirror = tmp_path / "mirror/SKILL.md"
    mirror.mkdir(parents=True)
    pairs = (("canonical/SKILL.md", "mirror/SKILL.md"),)

    assert collect_canonical_mirror_errors(tmp_path, pairs)

    mirror.rmdir()
    os.symlink(canonical, mirror)
    assert collect_canonical_mirror_errors(tmp_path, pairs)


def test_delivery_runtime_contract_is_closed_and_current() -> None:
    assert collect_delivery_runtime_contract_errors() == []

    payload = json.loads(
        (ROOT / "delivery/rules/DELIVERY-RUNTIME-CONTRACT.json").read_text(
            encoding="utf-8"
        )
    )
    payload["unexpected"] = True

    errors = collect_delivery_runtime_contract_errors(ROOT, payload)

    assert any("root keys must be exactly" in error for error in errors)


def test_delivery_runtime_forbidden_rules_are_data_owned() -> None:
    payload = json.loads(
        (ROOT / "delivery/rules/DELIVERY-RUNTIME-CONTRACT.json").read_text(
            encoding="utf-8"
        )
    )
    mutant = deepcopy(payload)
    mutant["forbidden_instructions"].append(
        {
            "rule_id": "fixture-new-rule-without-python-change",
            "token": "## Agent → Skill 关系",
            "target_refs": ["delivery/skills/README.md"],
        }
    )

    errors = collect_delivery_runtime_contract_errors(ROOT, mutant)

    assert (
        "delivery runtime forbidden instruction "
        "fixture-new-rule-without-python-change in delivery/skills/README.md"
    ) in errors
