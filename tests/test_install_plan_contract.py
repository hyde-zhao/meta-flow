from __future__ import annotations

import builtins
import subprocess

import pytest

from meta_flow.installation.canonical import build_plan, canonical_bytes, canonical_digest
from meta_flow.installation.contracts import (
    ACTION_FIELDS,
    ACTION_KINDS,
    CANONICAL_COMPONENTS,
    DECISIONS,
    GLOBAL_CHECKPOINTS,
    OPERATIONS,
    PLAN_FIELDS,
    SUBJECT_FIELDS,
    ContractErrorCode,
    InstallationContractError,
    validate_plan,
)
from meta_flow.installation.identity import (
    normalize_component,
    observe_checkout_delivery_status,
    resolve_source_identity,
    validate_source_identity,
)


def source_identity(**updates: str) -> dict[str, str]:
    payload = {
        "source": "meta-flow-delivery",
        "version": "0.4.1",
        "oid": "a" * 40,
        "delivery_tree_digest": "b" * 64,
        "rules_source_digest": "c" * 64,
        "inventory_digest": "d" * 64,
    }
    payload.update(updates)
    return payload


def unsigned_action(
    *,
    action_id: str,
    action_kind: str,
    component: str,
    ownership_kind: str,
    source_ref: str | None,
    target_ref: str,
    ordinal: int,
) -> dict[str, object]:
    return {
        "action_id": action_id,
        "action_kind": action_kind,
        "component": component,
        "ownership_kind": ownership_kind,
        "source_ref": source_ref,
        "target_ref": target_ref,
        "before_state": {"exists": False, "digest": None},
        "desired_state": {"exists": True, "digest": "f" * 64},
        "preconditions": [],
        "rollback_action": None,
        "ordinal": ordinal,
    }


def make_plan(**updates: object) -> dict[str, object]:
    values: dict[str, object] = {
        "operation": "assets.install",
        "decision_ref": "decisions/GOV-006-S02.json",
        "request_intent": "安装已审核的 Meta Flow 组件",
        "component": "agent",
        "scope": "project",
        "platform": "codex",
        "source_identity": source_identity(),
        "target_identity": {"project_id": "demo", "target_digest": "e" * 64},
        "base_facts": {"risk": "architecture-major", "target_complete": True},
        "actions": [
            unsigned_action(
                action_id="A-002",
                action_kind="write_manifest",
                component="manifest",
                ownership_kind="manifest",
                source_ref=None,
                target_ref=".meta-flow/INSTALL-MANIFEST.yaml",
                ordinal=2,
            ),
            unsigned_action(
                action_id="A-001",
                action_kind="write_exact_file",
                component="agents",
                ownership_kind="exact_file",
                source_ref="delivery/agents/example.md",
                target_ref=".codex/agents/example.toml",
                ordinal=1,
            ),
        ],
        "rollback_plan": {
            "strategy": "replan-required",
            "transaction_ref": "transactions/GOV-006-S02.json",
        },
    }
    values.update(updates)
    return build_plan(**values)  # type: ignore[arg-type]


def test_plan_schema_enums_and_checkpoints_are_exact() -> None:
    plan = make_plan()

    assert tuple(plan) == PLAN_FIELDS
    assert len(plan) == 12
    assert tuple(plan["subject"]) == SUBJECT_FIELDS
    assert plan["subject"]["action_count"] == len(plan["actions"])
    assert all(tuple(action) == ACTION_FIELDS for action in plan["actions"])
    assert [action["ordinal"] for action in plan["actions"]] == [1, 2]
    assert plan["actions"][-1]["action_kind"] == "write_manifest"
    assert ACTION_KINDS == (
        "invoke_uv_tool",
        "upsert_managed_block",
        "write_exact_file",
        "write_exact_leaf",
        "remove_owned_entry",
        "write_manifest",
        "restore_owned_entry",
    )
    assert OPERATIONS == (
        "cli.install",
        "cli.upgrade",
        "cli.uninstall",
        "assets.install",
        "assets.upgrade",
        "assets.uninstall",
        "lifecycle.recover",
    )
    assert len(DECISIONS) == 3
    assert len(GLOBAL_CHECKPOINTS) == 4
    validate_plan(plan)


def test_component_alias_is_one_resolver_and_never_a_fifth_component() -> None:
    assert CANONICAL_COMPONENTS == ("rules", "agents", "skills", "full")
    assert normalize_component("agent") == ("agents", "skills")
    assert normalize_component(["skills", "agents", "skills"]) == ("agents", "skills")
    assert normalize_component("full") == ("rules", "agents", "skills")
    assert make_plan()["subject"]["component_set"] == ["agents", "skills"]
    assert make_plan()["subject"]["legacy_alias"] == "agent"


@pytest.mark.parametrize("field", ["version", "oid", "delivery_tree_digest", "rules_source_digest", "inventory_digest"])
def test_source_drift_blocks_plan_before_any_executor(field: str) -> None:
    calls = {"executor": 0}
    observed = source_identity(**{field: "f" * (40 if field == "oid" else 64)})

    plan = make_plan(source_observation=observed)
    if plan["decision"] == "READY":
        calls["executor"] += 1

    assert plan["decision"] == "BLOCKED"
    assert calls["executor"] == 0
    assert {conflict["field"] for conflict in plan["conflicts"]} == {field}


def test_source_identity_rejects_unknown_missing_short_oid_and_dirty() -> None:
    unknown = source_identity()
    unknown["dirty"] = "true"
    with pytest.raises(InstallationContractError) as unknown_error:
        validate_source_identity(unknown)
    assert unknown_error.value.code is ContractErrorCode.UNKNOWN_KEY

    missing = source_identity()
    missing.pop("version")
    with pytest.raises(InstallationContractError) as missing_error:
        validate_source_identity(missing)
    assert missing_error.value.code is ContractErrorCode.MISSING_KEY

    with pytest.raises(InstallationContractError) as oid_error:
        validate_source_identity(source_identity(oid="a" * 12))
    assert oid_error.value.code is ContractErrorCode.IDENTITY_INCOMPLETE


def test_resolve_source_identity_is_exact_and_returns_a_copy() -> None:
    expected = source_identity()
    resolved = resolve_source_identity(expected, dict(reversed(list(expected.items()))))

    assert resolved == expected
    assert resolved is not expected
    with pytest.raises(InstallationContractError) as exc_info:
        resolve_source_identity(expected, source_identity(version="0.4.2"))
    assert exc_info.value.code is ContractErrorCode.IDENTITY_CONFLICT


def test_checkout_delivery_status_distinguishes_clean_and_dirty_tree(tmp_path) -> None:
    root = tmp_path / "checkout"
    root.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
    tracked = root / "tracked.txt"
    tracked.write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Meta Flow Test",
            "-c",
            "user.email=meta-flow@example.invalid",
            "commit",
            "-m",
            "baseline",
        ],
        cwd=root,
        check=True,
        capture_output=True,
    )

    assert observe_checkout_delivery_status(root) == {
        "worktree_clean": True,
        "exact_commit_delivery": True,
    }

    (root / "prospective.txt").write_text("dirty\n", encoding="utf-8")
    assert observe_checkout_delivery_status(root) == {
        "worktree_clean": False,
        "exact_commit_delivery": False,
    }


def test_equivalent_unordered_inputs_have_byte_identical_plan_and_digest() -> None:
    first = make_plan(
        target_identity={"project_id": "demo", "target_digest": "e" * 64},
        base_facts={"target_complete": True, "risk": "architecture-major"},
    )
    second = make_plan(
        target_identity={"target_digest": "e" * 64, "project_id": "demo"},
        base_facts={"risk": "architecture-major", "target_complete": True},
        source_identity=dict(reversed(list(source_identity().items()))),
        actions=list(reversed(first["actions"])),
        component="agent",
    )

    assert canonical_bytes(first) == canonical_bytes(second)
    assert first["plan_digest"] == second["plan_digest"]
    assert canonical_digest({"b": 2, "a": 1}) == canonical_digest({"a": 1, "b": 2})


def test_value_change_changes_digest() -> None:
    first = make_plan()
    second = make_plan(target_identity={"project_id": "other", "target_digest": "e" * 64})

    assert first["plan_digest"] != second["plan_digest"]


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda action: action.update({"unknown": True}), ContractErrorCode.UNKNOWN_KEY),
        (lambda action: action.pop("desired_state"), ContractErrorCode.MISSING_KEY),
        (lambda action: action.update({"ordinal": 0}), ContractErrorCode.NONCANONICAL_VALUE),
        (lambda action: action.update({"action_kind": "delete_tree"}), ContractErrorCode.INVALID_ENUM),
    ],
)
def test_action_schema_failures_are_deterministic(
    mutation: object,
    code: ContractErrorCode,
) -> None:
    action = unsigned_action(
        action_id="A-001",
        action_kind="write_manifest",
        component="manifest",
        ownership_kind="manifest",
        source_ref=None,
        target_ref=".meta-flow/INSTALL-MANIFEST.yaml",
        ordinal=1,
    )
    mutation(action)  # type: ignore[operator]

    with pytest.raises(InstallationContractError) as exc_info:
        make_plan(actions=[action])
    assert exc_info.value.code is code


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda plan: plan.update({"unknown": True}), ContractErrorCode.UNKNOWN_KEY),
        (lambda plan: plan.pop("rollback_plan"), ContractErrorCode.MISSING_KEY),
        (lambda plan: plan["subject"].update({"action_count": 0}), ContractErrorCode.NONCANONICAL_VALUE),
        (lambda plan: plan.update({"operation": "publish"}), ContractErrorCode.INVALID_ENUM),
    ],
)
def test_schema_failures_are_deterministic(
    mutation: object,
    code: ContractErrorCode,
) -> None:
    plan = make_plan()
    mutation(plan)  # type: ignore[operator]

    with pytest.raises(InstallationContractError) as exc_info:
        validate_plan(plan)
    assert exc_info.value.code is code


@pytest.mark.parametrize(
    "operation",
    [
        "install",
        "upgrade",
        "uninstall",
        "reinstall",
        "repair",
        "migrate",
        "recover",
    ],
)
def test_generic_or_two_transaction_operations_are_not_public_contract_values(
    operation: str,
) -> None:
    with pytest.raises(InstallationContractError) as exc_info:
        make_plan(operation=operation)

    assert exc_info.value.code is ContractErrorCode.INVALID_ENUM


@pytest.mark.parametrize(
    "change",
    [
        {"decision_ref": "/home/demo/decision.json"},
        {"rollback_plan": {"strategy": "replan-required", "remove_path": "AGENTS.md"}},
        {"base_facts": {"generated_at": "2026-07-24T00:00:00Z"}},
        {
            "actions": [
                unsigned_action(
                    action_id="A-001",
                    action_kind="write_manifest",
                    component="manifest",
                    ownership_kind="manifest",
                    source_ref=None,
                    target_ref="/tmp/AGENTS.md",
                    ordinal=1,
                )
            ]
        },
        {"base_facts": {"score": 1.5}},
    ],
)
def test_plan_rejects_absolute_dynamic_or_noncanonical_values(change: dict[str, object]) -> None:
    with pytest.raises(InstallationContractError):
        make_plan(**change)


def test_planner_does_not_mutate_files_call_uv_or_consume_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"open": 0, "subprocess": 0}

    def forbidden_open(*args: object, **kwargs: object) -> object:
        calls["open"] += 1
        raise AssertionError("planner attempted file I/O")

    def forbidden_run(*args: object, **kwargs: object) -> object:
        calls["subprocess"] += 1
        raise AssertionError("planner attempted subprocess/uv")

    monkeypatch.setattr(builtins, "open", forbidden_open)
    monkeypatch.setattr(subprocess, "run", forbidden_run)

    plan = make_plan()

    assert plan["decision"] == "READY"
    assert calls == {"open": 0, "subprocess": 0}


def test_plan_contains_no_dynamic_or_absolute_workspace_remove_paths() -> None:
    rendered = canonical_bytes(make_plan()).decode("utf-8")

    assert "created_at" not in rendered
    assert "generated_at" not in rendered
    assert "workspace_path" not in rendered
    assert "remove_path" not in rendered
    assert '"/home/' not in rendered
