from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from meta_flow.installation.asset_executor import (
    AssetExecutionContext,
    AssetExecutionError,
    execute_asset_action,
    fresh_asset_action_count,
    resolve_asset_target,
)
from meta_flow.installation.authorization import ClaimedAuthorization
from meta_flow.installation.canonical import canonical_digest
from meta_flow.installation.contracts import ACTION_FIELDS

DIGEST = "a" * 64


def _digest(content: bytes) -> str:
    return sha256(content).hexdigest()


def _action(
    *,
    action_id: str,
    action_kind: str,
    component: str,
    ownership_kind: str,
    target_ref: str,
    source_ref: str | None,
    before_exists: bool,
    before_digest: str,
    desired_state: dict[str, object],
    ordinal: int = 1,
) -> dict[str, object]:
    unsigned = {
        "action_id": action_id,
        "action_kind": action_kind,
        "component": component,
        "ownership_kind": ownership_kind,
        "source_ref": source_ref,
        "target_ref": target_ref,
        "before_state": {
            "exists": before_exists,
            "digest": before_digest,
        },
        "desired_state": desired_state,
        "preconditions": [],
        "rollback_action": None,
        "ordinal": ordinal,
    }
    return {
        **unsigned,
        "action_digest": canonical_digest(unsigned),
    }


def _context(
    root: Path,
    *,
    allowed: frozenset[str],
    sources: dict[str, bytes] | None = None,
    ownership: dict[str, dict[str, object]] | None = None,
    observer=None,
) -> AssetExecutionContext:
    claimed = ClaimedAuthorization(
        transaction_id="txn-1",
        authorization_id="auth-1",
        plan_digest=DIGEST,
        source_digest=DIGEST,
        target_digest=DIGEST,
        scope_digest=DIGEST,
        facts_digest=DIGEST,
    )
    source_map = sources or {}
    return AssetExecutionContext(
        claimed=claimed,
        expected_plan_digest=DIGEST,
        operation="assets.install",
        platform="codex",
        scope="project",
        target_root=root,
        allowed_target_refs=allowed,
        source_reader=lambda ref: source_map[ref],
        journal_prepared=True,
        ownership_by_target=ownership or {},
        outcome_observer=observer,
    )


@pytest.mark.parametrize(
    ("platform", "component", "expected"),
    [
        ("codex", "rules", 2),
        ("codex", "agents", 9),
        ("codex", "skills", 112),
        ("codex", "agent", 120),
        ("codex", "full", 121),
        ("claude", "rules", 2),
        ("claude", "agents", 6),
        ("claude", "skills", 112),
        ("claude", "agent", 117),
        ("claude", "full", 118),
    ],
)
def test_fresh_asset_action_counts(
    platform: str,
    component: str,
    expected: int,
) -> None:
    assert fresh_asset_action_count(platform, component) == expected


def test_platform_targets_are_read_from_separate_contract_entries() -> None:
    contracts = {
        "contracts": {
            "codex": {
                "scopes": {
                    "project": {
                        "rules": "AGENTS.md",
                        "agents": ".codex/agents",
                        "skills": ".agents/skills",
                    }
                }
            },
            "claude": {
                "scopes": {
                    "project": {
                        "rules": "CLAUDE.md",
                        "agents": ".claude/agents",
                        "skills": ".claude/skills",
                    }
                }
            },
        }
    }

    assert (
        resolve_asset_target(
            contracts,
            platform="codex",
            scope="project",
            component="agents",
        )
        == ".codex/agents"
    )
    assert (
        resolve_asset_target(
            contracts,
            platform="codex",
            scope="project",
            component="skills",
        )
        == ".agents/skills"
    )
    assert (
        resolve_asset_target(
            contracts,
            platform="claude",
            scope="project",
            component="skills",
        )
        == ".claude/skills"
    )


def test_managed_block_preserves_outside_bytes(tmp_path: Path) -> None:
    target = tmp_path / "AGENTS.md"
    outside = b"# User content\n"
    target.write_bytes(outside)
    body = b"# Meta Flow rules\n"
    begin = "<!-- managed begin -->"
    end = "<!-- managed end -->"
    block = begin.encode() + b"\n" + body + end.encode() + b"\n"
    action = _action(
        action_id="rules-1",
        action_kind="upsert_managed_block",
        component="rules",
        ownership_kind="managed_block",
        target_ref="AGENTS.md",
        source_ref="delivery/rules/AGENTS.md",
        before_exists=True,
        before_digest=_digest(outside),
        desired_state={
            "begin_marker": begin,
            "end_marker": end,
            "digest": _digest(block),
        },
    )

    outcome = execute_asset_action(
        _context(
            tmp_path,
            allowed=frozenset({"AGENTS.md"}),
            sources={"delivery/rules/AGENTS.md": body},
        ),
        action,
    )

    assert outcome.mutation_count == 1
    assert target.read_bytes().startswith(outside)
    assert target.read_bytes().endswith(block)


def test_exact_file_rejects_foreign_or_drifted_target(tmp_path: Path) -> None:
    target = tmp_path / ".codex" / "agents" / "meta-dev.toml"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"user file\n")
    desired = b"managed file\n"
    action = _action(
        action_id="agent-1",
        action_kind="write_exact_file",
        component="agents",
        ownership_kind="exact_file",
        target_ref=".codex/agents/meta-dev.toml",
        source_ref="delivery/agents/meta-dev.toml",
        before_exists=True,
        before_digest=_digest(b"other bytes\n"),
        desired_state={"digest": _digest(desired)},
    )

    with pytest.raises(AssetExecutionError, match="target digest drifted"):
        execute_asset_action(
            _context(
                tmp_path,
                allowed=frozenset({".codex/agents/meta-dev.toml"}),
                sources={"delivery/agents/meta-dev.toml": desired},
            ),
            action,
        )

    assert target.read_bytes() == b"user file\n"


def test_skill_write_preserves_foreign_sibling(tmp_path: Path) -> None:
    sibling = tmp_path / ".agents" / "skills" / "foreign" / "SKILL.md"
    sibling.parent.mkdir(parents=True)
    sibling.write_bytes(b"foreign\n")
    desired = b"managed\n"
    target_ref = ".agents/skills/state-router/SKILL.md"
    action = _action(
        action_id="skill-1",
        action_kind="write_exact_leaf",
        component="skills",
        ownership_kind="exact_leaf_set",
        target_ref=target_ref,
        source_ref="delivery/skills/state-router/SKILL.md",
        before_exists=False,
        before_digest="",
        desired_state={"digest": _digest(desired)},
    )

    outcome = execute_asset_action(
        _context(
            tmp_path,
            allowed=frozenset({target_ref}),
            sources={"delivery/skills/state-router/SKILL.md": desired},
        ),
        action,
    )

    assert outcome.mutation_count == 1
    assert sibling.read_bytes() == b"foreign\n"
    assert (tmp_path / target_ref).read_bytes() == desired


def test_unknown_target_and_missing_journal_block_before_write(
    tmp_path: Path,
) -> None:
    desired = b"managed\n"
    action = _action(
        action_id="agent-1",
        action_kind="write_exact_file",
        component="agents",
        ownership_kind="exact_file",
        target_ref=".codex/agents/meta-dev.toml",
        source_ref="delivery/agents/meta-dev.toml",
        before_exists=False,
        before_digest="",
        desired_state={"digest": _digest(desired)},
    )
    context = _context(
        tmp_path,
        allowed=frozenset(),
        sources={"delivery/agents/meta-dev.toml": desired},
    )

    with pytest.raises(AssetExecutionError, match="mutation allowlist"):
        execute_asset_action(context, action)

    assert not (tmp_path / ".codex").exists()


def test_symlink_escape_is_blocked(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "link").symlink_to(outside, target_is_directory=True)
    desired = b"managed\n"
    action = _action(
        action_id="agent-1",
        action_kind="write_exact_file",
        component="agents",
        ownership_kind="exact_file",
        target_ref="link/meta-dev.toml",
        source_ref="delivery/agents/meta-dev.toml",
        before_exists=False,
        before_digest="",
        desired_state={"digest": _digest(desired)},
    )

    with pytest.raises(AssetExecutionError, match="symlink"):
        execute_asset_action(
            _context(
                tmp_path,
                allowed=frozenset({"link/meta-dev.toml"}),
                sources={"delivery/agents/meta-dev.toml": desired},
            ),
            action,
        )

    assert list(outside.iterdir()) == []


def test_post_write_observer_failure_reports_partial_without_retry(
    tmp_path: Path,
) -> None:
    desired = b"managed\n"
    action = _action(
        action_id="agent-1",
        action_kind="write_exact_file",
        component="agents",
        ownership_kind="exact_file",
        target_ref=".codex/agents/meta-dev.toml",
        source_ref="delivery/agents/meta-dev.toml",
        before_exists=False,
        before_digest="",
        desired_state={"digest": _digest(desired)},
    )
    observer_calls = 0

    def fail_observer(_outcome) -> None:
        nonlocal observer_calls
        observer_calls += 1
        raise OSError("journal unavailable")

    outcome = execute_asset_action(
        _context(
            tmp_path,
            allowed=frozenset({".codex/agents/meta-dev.toml"}),
            sources={"delivery/agents/meta-dev.toml": desired},
            observer=fail_observer,
        ),
        action,
    )

    assert observer_calls == 1
    assert outcome.state == "partial"
    assert outcome.error_code == "OUTCOME_HANDOFF_FAILED"
    assert outcome.mutation_count == 1
    assert (tmp_path / ".codex/agents/meta-dev.toml").read_bytes() == desired


def test_action_fixture_has_exact_contract_keys() -> None:
    action = _action(
        action_id="agent-1",
        action_kind="write_exact_file",
        component="agents",
        ownership_kind="exact_file",
        target_ref=".codex/agents/meta-dev.toml",
        source_ref="delivery/agents/meta-dev.toml",
        before_exists=False,
        before_digest="",
        desired_state={"digest": DIGEST},
    )

    assert tuple(action) == ACTION_FIELDS
