"""GOV-006 六个隔离 lifecycle execution 的本地 runner。"""

from __future__ import annotations

import json
import shutil
from contextlib import redirect_stdout
from hashlib import sha256
from io import StringIO
from pathlib import Path
from typing import Any

from meta_flow.installation.asset_executor import (
    AssetExecutionContext,
    AssetExecutionError,
    execute_asset_action,
)
from meta_flow.installation.authorization import ClaimedAuthorization
from meta_flow.installation.canonical import canonical_digest
from meta_flow.installation.cli_executor import (
    CliExecutionContext,
    UvToolReceipt,
    bootstrap_main,
    execute_cli_action,
)

ISOLATED_FIXTURE_IDS = (
    "FIX-F3-01",
    "FIX-F3-02",
    "FIX-F4-CODEX-01",
    "FIX-F4-CODEX-02",
    "FIX-F4-CLAUDE-01",
    "FIX-F4-CLAUDE-02",
)
RESULT_FIELDS = (
    "fixture_id",
    "public_entry",
    "state",
    "terminal",
    "mutation_count",
    "authorization_count",
    "transaction_count",
    "network_calls",
    "real_home_hits",
    "external_project_hits",
    "mutation_allowlist",
    "evidence_ref",
    "cleanup_complete",
)
DIGEST = "a" * 64
IDENTITY = {
    "source": "checkout/meta-flow",
    "version": "0.4.1",
    "oid": "b" * 40,
    "delivery_tree_digest": "c" * 64,
    "rules_source_digest": "d" * 64,
    "inventory_digest": "e" * 64,
}


def run_isolated_fixture(
    fixture_id: str,
    sandbox_root: Path,
    *,
    external_project_root: Path,
) -> dict[str, Any]:
    """运行一个 fixture，先持久化取证，再清理已知 runtime root。"""

    if fixture_id not in ISOLATED_FIXTURE_IDS:
        raise ValueError(f"unknown GOV-006 fixture: {fixture_id}")
    root = _guard_sandbox(
        sandbox_root,
        external_project_root=external_project_root,
    )
    runtime = root / "runtime"
    home = runtime / "home"
    target = runtime / "target"
    cache = runtime / "cache"
    tool = runtime / "uv-tool"
    evidence_root = root / "evidence"
    for directory in (home, target, cache, tool, evidence_root):
        directory.mkdir(parents=True, exist_ok=True)

    try:
        result = (
            _run_cli_fixture(fixture_id)
            if fixture_id.startswith("FIX-F3")
            else _run_asset_fixture(fixture_id, target)
        )
        evidence_ref = f"evidence/{fixture_id}.json"
        evidence = {
            **result,
            "fixture_id": fixture_id,
            "public_entry": result["public_entry"],
            "network_calls": 0,
            "real_home_hits": 0,
            "external_project_hits": 0,
            "mutation_allowlist": list(result["mutation_allowlist"]),
            "evidence_ref": evidence_ref,
            "cleanup_complete": False,
        }
        _write_evidence(evidence_root / f"{fixture_id}.json", evidence)
    finally:
        if runtime.exists():
            shutil.rmtree(runtime)

    evidence["cleanup_complete"] = not runtime.exists()
    _write_evidence(evidence_root / f"{fixture_id}.json", evidence)
    return {field: evidence[field] for field in RESULT_FIELDS}


def _run_cli_fixture(fixture_id: str) -> dict[str, Any]:
    if fixture_id == "FIX-F3-01":
        output = StringIO()
        with redirect_stdout(output):
            returncode = bootstrap_main(
                [
                    "install",
                    "--source",
                    "checkout/meta-flow",
                    "--dry-run",
                ]
            )
        payload = json.loads(output.getvalue())
        return {
            "public_entry": "delivery/scripts/install-cli.py",
            "state": payload["decision"].lower(),
            "terminal": "dry-run",
            "mutation_count": payload["mutation_count"],
            "authorization_count": 0,
            "transaction_count": payload["transaction_count"],
            "mutation_allowlist": ["uv-tool/meta-flow"],
            "returncode": returncode,
        }

    calls = 0

    def runner(_argv) -> UvToolReceipt:
        nonlocal calls
        calls += 1
        return UvToolReceipt(7, "", "injected uv failure", None)

    outcome = execute_cli_action(
        CliExecutionContext(
            claimed=_claimed(),
            expected_plan_digest=DIGEST,
            operation="cli.upgrade",
            platform="linux",
            journal_prepared=True,
            source_identity=IDENTITY,
            source_argument="checkout/meta-flow",
            runner=runner,
        ),
        _cli_action(),
    )
    return {
        "public_entry": "meta_flow.installation.cli_executor.execute_cli_action",
        "state": outcome.state,
        "terminal": "partial",
        "mutation_count": outcome.mutation_count,
        "authorization_count": 1,
        "transaction_count": 1,
        "mutation_allowlist": ["uv-tool/meta-flow"],
        "runner_calls": calls,
    }


def _run_asset_fixture(fixture_id: str, target: Path) -> dict[str, Any]:
    platform = "codex" if "CODEX" in fixture_id else "claude"
    target_ref = (
        ".codex/agents/meta-dev.toml"
        if platform == "codex"
        else ".claude/agents/meta-dev.md"
    )
    desired = f"{platform} managed agent\n".encode()
    observer = None
    before_exists = False
    before_digest = ""
    expected_state = "applied"
    expected_terminal = "applied"
    if fixture_id == "FIX-F4-CODEX-02":
        foreign = target.joinpath(*Path(target_ref).parts)
        foreign.parent.mkdir(parents=True)
        foreign.write_bytes(b"foreign user file\n")
        before_exists = True
        before_digest = sha256(b"other bytes\n").hexdigest()
        expected_state = "blocked"
        expected_terminal = "blocked"
    elif fixture_id == "FIX-F4-CLAUDE-01":

        def injected_handoff_failure(_outcome) -> None:
            raise OSError("injected outcome handoff failure")

        observer = injected_handoff_failure
        expected_state = "partial"
        expected_terminal = "partial"

    action = _asset_action(
        platform=platform,
        target_ref=target_ref,
        desired=desired,
        before_exists=before_exists,
        before_digest=before_digest,
    )
    context = AssetExecutionContext(
        claimed=_claimed(),
        expected_plan_digest=DIGEST,
        operation="assets.install",
        platform=platform,
        scope="project",
        target_root=target,
        allowed_target_refs=frozenset({target_ref}),
        source_reader=lambda _ref: desired,
        journal_prepared=True,
        ownership_by_target={},
        outcome_observer=observer,
    )
    try:
        outcome = execute_asset_action(context, action)
    except AssetExecutionError:
        state = "blocked"
        mutation_count = 0
    else:
        state = outcome.state
        mutation_count = outcome.mutation_count
    if state != expected_state:
        raise AssertionError(
            f"{fixture_id} expected {expected_state}, observed {state}"
        )
    return {
        "public_entry": (
            "meta_flow.installation.asset_executor.execute_asset_action"
        ),
        "state": state,
        "terminal": expected_terminal,
        "mutation_count": mutation_count,
        "authorization_count": 1,
        "transaction_count": 1,
        "mutation_allowlist": [target_ref],
    }


def _claimed() -> ClaimedAuthorization:
    return ClaimedAuthorization(
        transaction_id="txn-fixture",
        authorization_id="auth-fixture",
        plan_digest=DIGEST,
        source_digest=DIGEST,
        target_digest=DIGEST,
        scope_digest=DIGEST,
        facts_digest=DIGEST,
    )


def _cli_action() -> dict[str, object]:
    unsigned = {
        "action_id": "uv-fixture",
        "action_kind": "invoke_uv_tool",
        "component": "cli",
        "ownership_kind": "uv_tool",
        "source_ref": "checkout/meta-flow",
        "target_ref": "uv-tool/meta-flow",
        "before_state": {"installed": True},
        "desired_state": {
            "source_identity": IDENTITY,
            "force_refresh": True,
        },
        "preconditions": [],
        "rollback_action": None,
        "ordinal": 1,
    }
    return {**unsigned, "action_digest": canonical_digest(unsigned)}


def _asset_action(
    *,
    platform: str,
    target_ref: str,
    desired: bytes,
    before_exists: bool,
    before_digest: str,
) -> dict[str, object]:
    source_ref = (
        "delivery/agents/meta-dev.toml"
        if platform == "codex"
        else "delivery/agents/meta-dev.md"
    )
    unsigned = {
        "action_id": f"{platform}-fixture",
        "action_kind": "write_exact_file",
        "component": "agents",
        "ownership_kind": "exact_file",
        "source_ref": source_ref,
        "target_ref": target_ref,
        "before_state": {
            "exists": before_exists,
            "digest": before_digest,
        },
        "desired_state": {"digest": sha256(desired).hexdigest()},
        "preconditions": [],
        "rollback_action": None,
        "ordinal": 1,
    }
    return {**unsigned, "action_digest": canonical_digest(unsigned)}


def _guard_sandbox(
    sandbox_root: Path,
    *,
    external_project_root: Path,
) -> Path:
    if not sandbox_root.is_absolute():
        raise ValueError("isolated fixture root must be absolute")
    root = sandbox_root.resolve(strict=False)
    forbidden = (Path.home().resolve(), external_project_root.resolve())
    if any(root == item or root.is_relative_to(item) for item in forbidden):
        raise ValueError("isolated fixture root overlaps a forbidden root")
    if sandbox_root.exists() and sandbox_root.is_symlink():
        raise ValueError("isolated fixture root must not be a symlink")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _write_evidence(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )


__all__ = [
    "ISOLATED_FIXTURE_IDS",
    "RESULT_FIELDS",
    "run_isolated_fixture",
]
