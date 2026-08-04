from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cr066_external_fixture_harness import (
    CANARY_AUTHORIZATION_FIELDS,
    plan_canary_activation,
    validate_canary_authorization,
)

SOURCE_OID = "34ff8b7781fb88528923fb577832f33503ebab45"
SOURCE_TREE_OID = "6b684948fd6e8c9f0255474259ee6d4421ce96c1"
FIXED_NOW = datetime(2026, 8, 4, 4, 0, tzinfo=UTC)


def _authorization(source: Path, target: Path) -> dict[str, object]:
    before = "1" * 64
    return {
        "schema_version": 1,
        "kind": "C66CanaryAuthorizationV1",
        "authorization_id": "C66-CANARY-AUTH-fixture",
        "authorization_source": "typed-user-confirmation",
        "source_root": str(source),
        "source_oid": SOURCE_OID,
        "source_tree_oid": SOURCE_TREE_OID,
        "source_status_digest": "2" * 64,
        "target_root": str(target),
        "mode": "dry-run-then-authorized-reversible-apply",
        "allowed_reads": [
            str(source),
            str(source / ".codex" / "hooks.json"),
            str(source / "pyproject.toml"),
        ],
        "allowed_writes": [
            str(target),
            str(target / ".codex" / "hooks.json"),
            str(target / "src" / "agent_memory" / "install.py"),
            str(target / "src" / "agent_memory" / "service.py"),
            str(target / "tests" / "test_hooks_bootstrap.py"),
            str(target / ".canary"),
        ],
        "before_manifest_digest": before,
        "expected_after_manifest_digest": "3" * 64,
        "rollback_target_digest": before,
        "rollback_steps": [
            "meta-flow uninstall codex --scope project --component full",
            "restore exact tracked target files",
            "remove only journaled target-generated paths",
            "verify before manifest digest",
        ],
        "time_window_start": "2026-08-04T03:00:00+00:00",
        "time_window_end": "2026-08-04T05:00:00+00:00",
        "human_reviewer": "hyde",
        "single_use": True,
    }


def test_g2_approval_alone_cannot_activate_external_canary(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"

    plan = plan_canary_activation(
        source_root=source,
        target_root=target,
        source_oid=SOURCE_OID,
        source_tree_oid=SOURCE_TREE_OID,
    )

    assert plan == {
        "schema_version": 1,
        "kind": "C66CanaryActivationPlanV1",
        "decision": "BLOCKED",
        "blockers": ["C66_CANARY_AUTH_REQUIRED"],
        "planned_mutation_count": 0,
        "mutation_count": 0,
        "external_mutation": 0,
        "real_install": 0,
        "credential_access": 0,
        "production_write": 0,
    }
    assert not target.exists()

    with pytest.raises(ValueError, match="structured object"):
        plan_canary_activation(
            source_root=source,
            target_root=target,
            source_oid=SOURCE_OID,
            source_tree_oid=SOURCE_TREE_OID,
            authorization="approve C66-G2",
            now=FIXED_NOW,
        )
    assert not target.exists()


def test_exact_canary_authorization_is_plan_only_and_target_scoped(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    authorization = _authorization(source, target)

    validated = validate_canary_authorization(
        authorization,
        expected_source_root=source,
        expected_target_root=target,
        expected_source_oid=SOURCE_OID,
        expected_source_tree_oid=SOURCE_TREE_OID,
        now=FIXED_NOW,
    )
    plan = plan_canary_activation(
        source_root=source,
        target_root=target,
        source_oid=SOURCE_OID,
        source_tree_oid=SOURCE_TREE_OID,
        authorization=authorization,
        now=FIXED_NOW,
    )

    assert tuple(validated) == CANARY_AUTHORIZATION_FIELDS
    assert plan["decision"] == "READY"
    assert plan["mutation_count"] == 0
    assert plan["planned_mutation_count"] == len(authorization["allowed_writes"])
    assert plan["credential_access"] == 0
    assert plan["production_write"] == 0
    assert all(
        Path(path).resolve(strict=False).is_relative_to(target.resolve())
        or Path(path).resolve(strict=False) == target.resolve()
        for path in plan["allowed_writes"]
    )
    assert not target.exists()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"source_oid": "f" * 40}, "source OID drifted"),
        ({"source_tree_oid": "e" * 40}, "source tree OID drifted"),
        ({"rollback_target_digest": "9" * 64}, "rollback target"),
        ({"time_window_end": "2026-08-04T03:30:00+00:00"}, "time window"),
        ({"human_reviewer": "automatic-agent"}, "human reviewer"),
        ({"single_use": False}, "single-use"),
    ],
)
def test_canary_authorization_drift_fails_closed(
    tmp_path: Path,
    mutation: dict[str, object],
    message: str,
) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    authorization = {**_authorization(source, target), **mutation}

    with pytest.raises(ValueError, match=message):
        validate_canary_authorization(
            authorization,
            expected_source_root=source,
            expected_target_root=target,
            expected_source_oid=SOURCE_OID,
            expected_source_tree_oid=SOURCE_TREE_OID,
            now=FIXED_NOW,
        )
    assert not target.exists()


def test_canary_writes_cannot_escape_target_or_touch_user_hooks(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    authorization = _authorization(source, target)
    escaped = deepcopy(authorization)
    escaped["allowed_writes"] = [str(source / ".codex" / "hooks.json")]

    with pytest.raises(ValueError, match="write escapes target root"):
        validate_canary_authorization(
            escaped,
            expected_source_root=source,
            expected_target_root=target,
            expected_source_oid=SOURCE_OID,
            expected_source_tree_oid=SOURCE_TREE_OID,
            now=FIXED_NOW,
        )

    user_hook = deepcopy(authorization)
    user_hook["allowed_writes"] = [str(Path.home() / ".codex" / "hooks.json")]
    with pytest.raises(ValueError, match="write escapes target root"):
        validate_canary_authorization(
            user_hook,
            expected_source_root=source,
            expected_target_root=target,
            expected_source_oid=SOURCE_OID,
            expected_source_tree_oid=SOURCE_TREE_OID,
            now=FIXED_NOW,
        )
    assert not target.exists()


def test_canary_configuration_freezes_approved_option_b_paths() -> None:
    source = Path("/home/hyde/workspace/agent-memery")
    target = Path("/home/hyde/workspace/canary-agent-memery")

    assert source != target
    assert target.parent == source.parent
    assert target.name == "canary-agent-memery"
    assert SOURCE_OID == "34ff8b7781fb88528923fb577832f33503ebab45"
    assert SOURCE_TREE_OID == "6b684948fd6e8c9f0255474259ee6d4421ce96c1"
