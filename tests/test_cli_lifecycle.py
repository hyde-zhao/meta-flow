from __future__ import annotations

import json
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

import pytest

from meta_flow import cli
from meta_flow.installation.authorization import ClaimedAuthorization
from meta_flow.installation.canonical import canonical_digest
from meta_flow.installation.cli_executor import (
    CliExecutionContext,
    CliExecutionError,
    UvToolReceipt,
    UvToolRequest,
    bootstrap_main,
    build_cli_diagnostics,
    execute_cli_action,
    normalize_reinstall,
    uv_tool_argv,
)

DIGEST = "a" * 64
IDENTITY = {
    "source": "checkout/meta-flow",
    "version": "1.2.3",
    "oid": "b" * 40,
    "delivery_tree_digest": "c" * 64,
    "rules_source_digest": "d" * 64,
    "inventory_digest": "e" * 64,
}


def _action(
    *,
    operation: str = "cli.install",
    force_refresh: bool = False,
) -> dict[str, object]:
    unsigned = {
        "action_id": "uv-1",
        "action_kind": "invoke_uv_tool",
        "component": "cli",
        "ownership_kind": "uv_tool",
        "source_ref": "checkout/meta-flow",
        "target_ref": "uv-tool/meta-flow",
        "before_state": {"installed": operation != "cli.install"},
        "desired_state": {
            "source_identity": IDENTITY,
            "force_refresh": force_refresh,
        },
        "preconditions": [],
        "rollback_action": None,
        "ordinal": 1,
    }
    return {**unsigned, "action_digest": canonical_digest(unsigned)}


def _claimed() -> ClaimedAuthorization:
    return ClaimedAuthorization(
        transaction_id="txn-1",
        authorization_id="auth-1",
        plan_digest=DIGEST,
        source_digest=DIGEST,
        target_digest=DIGEST,
        scope_digest=DIGEST,
        facts_digest=DIGEST,
    )


def _context(
    runner,
    *,
    operation: str = "cli.install",
    platform: str = "linux",
    identity=IDENTITY,
) -> CliExecutionContext:
    return CliExecutionContext(
        claimed=_claimed(),
        expected_plan_digest=DIGEST,
        operation=operation,
        platform=platform,
        journal_prepared=True,
        source_identity=identity,
        source_argument="checkout/meta-flow",
        runner=runner,
    )


@pytest.mark.parametrize(
    ("uv_request", "expected"),
    [
        (
            UvToolRequest("cli.install", "meta-flow", "checkout/meta-flow", IDENTITY),
            ("uv", "tool", "install", "--from", "checkout/meta-flow", "meta-flow"),
        ),
        (
            UvToolRequest("cli.upgrade", "meta-flow", "checkout/meta-flow", IDENTITY),
            (
                "uv",
                "tool",
                "install",
                "--force",
                "--from",
                "checkout/meta-flow",
                "meta-flow",
            ),
        ),
        (
            UvToolRequest("cli.uninstall", "meta-flow", "", IDENTITY),
            ("uv", "tool", "uninstall", "meta-flow"),
        ),
    ],
)
def test_uv_tool_argv_is_structured(
    uv_request: UvToolRequest,
    expected: tuple[str, ...],
) -> None:
    assert uv_tool_argv(uv_request) == expected
    assert "pip" not in expected
    assert "python" not in expected
    assert all(token not in {"sh", "bash", "-c"} for token in expected)


def test_execute_cli_action_uses_one_uv_call_and_exact_identity() -> None:
    calls: list[tuple[str, ...]] = []

    def runner(argv):
        calls.append(tuple(argv))
        return UvToolReceipt(0, "", "", IDENTITY)

    outcome = execute_cli_action(_context(runner), _action())

    assert outcome.state == "applied"
    assert outcome.mutation_count == 1
    assert calls == [
        ("uv", "tool", "install", "--from", "checkout/meta-flow", "meta-flow")
    ]


def test_source_drift_blocks_before_uv_call() -> None:
    calls = 0
    drifted = {**IDENTITY, "oid": "f" * 40}

    def runner(_argv):
        nonlocal calls
        calls += 1
        return UvToolReceipt(0, "", "", IDENTITY)

    with pytest.raises(CliExecutionError, match="source identity conflicts"):
        execute_cli_action(_context(runner, identity=drifted), _action())

    assert calls == 0


def test_uv_failure_is_partial_without_retry() -> None:
    calls = 0

    def runner(_argv):
        nonlocal calls
        calls += 1
        return UvToolReceipt(7, "", "failed", None)

    outcome = execute_cli_action(
        _context(runner, operation="cli.upgrade"),
        _action(operation="cli.upgrade", force_refresh=True),
    )

    assert calls == 1
    assert outcome.state == "partial"
    assert outcome.error_code == "UV_TOOL_FAILED"
    assert outcome.mutation_count == 0


def test_non_linux_target_is_blocked_without_uv_call() -> None:
    calls = 0

    def runner(_argv):
        nonlocal calls
        calls += 1
        return UvToolReceipt(0, "", "", IDENTITY)

    with pytest.raises(CliExecutionError, match="Linux only"):
        execute_cli_action(_context(runner, platform="windows"), _action())

    assert calls == 0


def test_diagnostics_are_ready_only_when_manifest_and_receipt_match() -> None:
    source_digest = canonical_digest(IDENTITY)
    ready = build_cli_diagnostics(
        IDENTITY,
        manifest_facts={"source_identity_digest": source_digest},
        receipt_facts={
            "source_identity_digest": source_digest,
            "terminal": "applied",
        },
    )
    missing = build_cli_diagnostics(
        IDENTITY,
        manifest_facts=None,
        receipt_facts=None,
    )

    assert ready == {
        "ready": True,
        "status": "READY",
        "version": "1.2.3",
        "source": "checkout/meta-flow",
        "git_oid": "b" * 40,
        "delivery_tree_digest": "c" * 64,
        "findings": [],
    }
    assert missing["ready"] is False
    assert missing["findings"] == ["MANIFEST_MISSING", "RECEIPT_MISSING"]


def test_version_reports_identity_readiness_separately_from_exact_delivery() -> None:
    output = StringIO()
    identity = {
        "schema_version": 2,
        "kind": "ProviderRuntimeIdentityV2",
        "distribution_name": "meta-flow",
        "distribution_version": "0.5.1",
        "module_path": "/tmp/source/meta_flow/__init__.py",
        "distribution_path": "/tmp/source",
        "editable": True,
        "identity_source": "editable-checkout",
        "source_root": "/tmp/source",
        "source_commit": "a" * 40,
        "source_dirty": True,
        "source_tree_digest": "b" * 64,
        "artifact_sha256": None,
        "installed_files_digest": "c" * 64,
        "capability_profile_digest": "d" * 64,
        "schema_versions": {"provider_runtime_identity": 2},
        "source_discovery": {"decision": "PASS", "reason_codes": []},
        "release_readiness": {
            "decision": "BLOCKED",
            "reason_codes": ["EDITABLE_INSTALL", "SOURCE_DIRTY"],
        },
        "worktree_clean": False,
        "exact_commit_delivery": False,
        "identity_digest": "e" * 64,
    }

    with (
        patch(
            "meta_flow.installation.identity.observe_provider_runtime_identity",
            return_value=identity,
        ),
        redirect_stdout(output),
    ):
        cli._run_version(["--format", "json"])

    payload = json.loads(output.getvalue())
    assert payload["ready"] is True
    assert payload["status"] == "SOURCE_READY_RELEASE_BLOCKED"
    assert payload["provider_admission"]["decision"] == "BLOCKED"
    assert payload["worktree_clean"] is False
    assert payload["exact_commit_delivery"] is False


@pytest.mark.parametrize("surface", ["cli", "assets"])
def test_reinstall_is_one_upgrade_transaction(surface: str) -> None:
    normalized = normalize_reinstall(
        surface=surface,
        selector={"component": "rules"},
    )

    assert normalized == {
        "operation": f"{surface}.upgrade",
        "selector": {"component": "rules", "force_refresh": True},
        "transaction_count": 1,
        "authorization_count": 1,
    }


def test_bootstrap_is_dry_run_only_without_typed_authorization() -> None:
    output = StringIO()
    with redirect_stdout(output):
        result = bootstrap_main(["install", "--source", "checkout/meta-flow", "--dry-run"])
    dry_run = json.loads(output.getvalue())

    assert result == 0
    assert dry_run["operation"] == "cli.install"
    assert dry_run["decision"] == "READY"
    assert dry_run["mutation_count"] == 0

    output = StringIO()
    with redirect_stdout(output):
        result = bootstrap_main(["install", "--source", "checkout/meta-flow"])
    blocked = json.loads(output.getvalue())

    assert result == 2
    assert blocked["decision"] == "BLOCKED"
    assert blocked["reason"] == "typed-authorization-required"
