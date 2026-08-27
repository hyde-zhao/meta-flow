from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from meta_flow.execution_control.contract import ExecutionUnitV1
from meta_flow.work.budget import BudgetLimit
from meta_flow.work.lifecycle import ALLOWED_TRANSITIONS, transition_work, update_work_status
from meta_flow.work.model import (
    WORK_MAX_BYTES,
    PredecessorInventoryReceiptV1,
    ScopeDeltaV1,
    apply_scope_amend,
    build_work,
    load_work,
    plan_scope_amend,
    validate_work_payload,
    work_from_payload,
    write_work_create_only,
)
from meta_flow.work.risk import RiskFacts, classify_work
from meta_flow.work.route_profile import (
    BRANCH_NAME_TEMPLATE,
    BRANCH_NAME_TYPES,
    RouteProfile,
    check_slice_mutation,
    route_profile_from_payload,
)
from meta_flow.work.scope import WorkScope, exact_scope_difference

RELEASE_OID = "a" * 40


def _process_route(root: Path) -> None:
    # update_work_status 现要求 process 侧身份文件、sibling release 仓与双侧已提交 HEAD。
    release = root.parent / f"{root.name}-release"
    release.mkdir()
    for repo in (root, release):
        subprocess.run(
            ["git", "-C", str(repo), "init", "-b", "main"],
            check=True,
            capture_output=True,
        )
        (repo / ".gitkeep").write_text("", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "-c",
                "user.name=Meta Flow Test",
                "-c",
                "user.email=meta-flow@example.invalid",
                "commit",
                "-m",
                "fixture baseline",
            ],
            check=True,
            capture_output=True,
        )
    (root / ".meta-flow-process.yaml").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "layout_version": "independent-process-repo-v1",
                "workflow_model": "vnext",
                "project_id": "demo",
                "repo_role": "process",
                "route_mode": "sibling-binding",
                "release_repo": {
                    "anchor": "workspace_parent",
                    "relative_path": release.name,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_scope_delta_is_add_only_and_apply_requires_fresh_snapshot() -> None:
    delta = ScopeDeltaV1(1, add_story_ids=("STORY-NEW",), add_owned_leaves=("leaf.py",))
    receipt = PredecessorInventoryReceiptV1("CR-071", "R1", "verified", ("old",), "a" * 64, "b" * 64)
    plan = plan_scope_amend(revision_id="R2", current_scope=("old",), delta=delta, authorized_leaves=("leaf.py",), predecessor=receipt, snapshot_digest="c" * 64)
    assert plan.mutation_count == 0
    assert apply_scope_amend(plan, fresh_snapshot_digest="d" * 64)["decision"] == "REPLAN_REQUIRED"


def test_scope_delta_rejects_unknown_or_noop_additions() -> None:
    receipt = PredecessorInventoryReceiptV1("CR-071", "R1", "verified", ("old",), "a" * 64, "b" * 64)
    with pytest.raises(ValueError, match="SCOPE_NARROWING"):
        plan_scope_amend(revision_id="R2", current_scope=("old",), delta=ScopeDeltaV1(1, add_story_ids=("STORY-OLD",), add_owned_leaves=("bad.py",)), authorized_leaves=(), predecessor=receipt, snapshot_digest="c" * 64)


def test_scope_delta_accepts_safe_root_dotfile_owned_leaf() -> None:
    delta = ScopeDeltaV1(1, add_owned_leaves=(".gitignore",))

    assert delta.add_owned_leaves == (".gitignore",)


@pytest.mark.parametrize(
    "leaf",
    (
        "",
        "/.gitignore",
        ".",
        "..",
        "./.gitignore",
        "../.gitignore",
        "config/../.gitignore",
        "config//settings",
        "config\\settings",
    ),
)
def test_scope_delta_rejects_unsafe_owned_leaf(leaf: str) -> None:
    with pytest.raises(ValueError, match="INVALID_SCOPE_DELTA"):
        ScopeDeltaV1(1, add_owned_leaves=(leaf,))


def test_exact_scope_difference_never_treats_partial_staging_as_pass() -> None:
    result = exact_scope_difference(
        ("release/a.py", "process/WORK.yaml"),
        ("release/a.py",),
    )

    assert result["decision"] == "BLOCKED"
    assert result["missing"] == ["process/WORK.yaml"]


def make_work(*, work_id: str = "W-001", profile: str = "G0"):
    facts = RiskFacts(
        change_kind="documentation" if profile == "G0" else "code",
        touched_path_count=1 if profile == "G0" else 3,
        public_contract=profile == "G2",
    )
    decision = classify_work(
        facts,
        g2_budget=BudgetLimit(30, 30, 12, 160_000) if profile == "G2" else None,
    )
    scope = WorkScope(
        version=1,
        allowed_reads=("README.md",),
        allowed_writes=("README.md",),
        required_checks=("pytest-docs",),
    )
    return build_work(
        work_id=work_id,
        project_id="demo",
        objective="更新用户文档",
        request_ref=f"works/{work_id}/REQUEST.md",
        scope=scope,
        classification=decision,
        release_base_oid=RELEASE_OID,
        process_base_oid="",
    )


@pytest.mark.parametrize("profile", ["G0", "G1", "G2"])
def test_build_work_round_trips_all_profiles(tmp_path: Path, profile: str) -> None:
    work = make_work(profile=profile)

    path = write_work_create_only(tmp_path, work)

    assert path == tmp_path / "works" / "W-001" / "WORK.yaml"
    assert load_work(tmp_path, "W-001") == work
    assert validate_work_payload(work.as_dict()) == []
    assert work.scope.digest == work.as_dict()["scope_digest"]


def test_formal_cr_execution_envelope_accepts_typed_execution_unit() -> None:
    work = make_work(profile="G2")
    payload = work.as_dict()
    payload["execution_unit"] = ExecutionUnitV1(
        unit_id=work.work_id,
        root_concept="formal-cr-execution",
        slice_id=work.work_id,
        container_role="primary",
        revision=1,
        supersedes_unit_id="",
        contract_ref="process/changes/CR-001.md",
        contract_digest="c" * 64,
    ).as_dict()

    assert payload["kind"] == "cr"
    assert validate_work_payload(payload) == []


def test_blocked_g2_classification_cannot_create_work() -> None:
    decision = classify_work(
        RiskFacts(change_kind="code", touched_path_count=2, security=True)
    )

    with pytest.raises(ValueError, match="blocked classification"):
        build_work(
            work_id="W-001",
            project_id="demo",
            objective="修改安全边界",
            request_ref="works/W-001/REQUEST.md",
            scope=WorkScope(1, (), (), ()),
            classification=decision,
            release_base_oid=RELEASE_OID,
            process_base_oid="",
        )


def test_work_rejects_tampered_scope_digest() -> None:
    payload = make_work().as_dict()
    payload["scope_digest"] = "0" * 64

    findings = validate_work_payload(payload)

    assert "scope_digest" in {finding.code for finding in findings}


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    [
        ("request_ref", "../REQUEST.md", "ref_path"),
        ("usage_ref", "works/OTHER/USAGE.json", "ref_path"),
        ("phase_ref", "works/W-001/WORK.yaml", "ref_path"),
        ("base_oids", {"release": "short", "process": ""}, "base_oid"),
        ("request_confirmed", False, "request_confirmation"),
    ],
)
def test_work_rejects_unsafe_contract_fields(field: str, value: object, expected_code: str) -> None:
    payload = make_work().as_dict()
    payload[field] = value

    findings = validate_work_payload(payload)

    assert expected_code in {finding.code for finding in findings}


def test_work_rejects_unknown_and_over_budget_payload() -> None:
    payload = make_work().as_dict()
    payload["transcript"] = "not allowed"

    findings = validate_work_payload(payload, byte_size=WORK_MAX_BYTES + 1)

    assert {"unknown_key", "work_over_budget"} <= {finding.code for finding in findings}


def test_legacy_work_without_route_profile_uses_safe_default() -> None:
    payload = make_work().as_dict()
    payload.pop("route_profile")

    restored = work_from_payload(payload)

    assert restored.route_profile == RouteProfile()
    assert restored.as_dict()["route_profile"] == RouteProfile().as_dict()


def test_route_profile_defaults_to_root_branch_only_and_accepts_legacy_payload() -> None:
    profile = RouteProfile()
    legacy_payload = profile.as_dict()
    legacy_payload.pop("worktree_policy")

    restored = route_profile_from_payload(legacy_payload)

    assert profile.worktree_policy == "root-branch-only"
    assert restored == profile
    assert BRANCH_NAME_TEMPLATE == "<type>/<work-id>-<description>"
    assert BRANCH_NAME_TYPES == ("feat", "fix", "refactor", "docs", "chore")


def test_direct_dispatch_rejects_paired_worktree_outside_legacy_route() -> None:
    with pytest.raises(ValueError, match="direct dispatch requires root-branch-only"):
        RouteProfile(worktree_policy="paired-worktree")

    paired = RouteProfile(
        dispatch_mode="functional-agent",
        worktree_policy="paired-worktree",
    )
    legacy = RouteProfile(
        mode="legacy-cp0-cp8",
        legacy_cp_compatibility=True,
        worktree_policy="paired-worktree",
    )

    assert paired.worktree_policy == "paired-worktree"
    assert legacy.worktree_policy == "paired-worktree"


def test_route_profile_is_strict_and_g0_cannot_dispatch_functional_agent() -> None:
    payload = make_work().as_dict()
    payload["route_profile"]["unexpected"] = True
    assert "route_profile" in {item.code for item in validate_work_payload(payload)}

    with pytest.raises(ValueError, match="G0/G1 functional-agent"):
        build_work(
            work_id="W-002",
            project_id="demo",
            objective="错误调度",
            request_ref="works/W-002/REQUEST.md",
            scope=WorkScope(1, (), (), ()),
            classification=classify_work(
                RiskFacts(change_kind="documentation", touched_path_count=1)
            ),
            release_base_oid=RELEASE_OID,
            process_base_oid="",
            route_profile=RouteProfile(dispatch_mode="functional-agent"),
        )


def test_current_slice_allowlist_blocks_cross_slice_mutation() -> None:
    profile = RouteProfile()

    allowed = check_slice_mutation(
        profile,
        work_allowed_writes=("meta_flow/**", "tests/**"),
        slice_allowed_writes=("meta_flow/work/model.py",),
        requested_ref="meta_flow/work/model.py",
    )
    blocked = check_slice_mutation(
        profile,
        work_allowed_writes=("meta_flow/**", "tests/**"),
        slice_allowed_writes=("meta_flow/work/model.py",),
        requested_ref="tests/test_other_slice.py",
    )

    assert allowed.allowed
    assert not blocked.allowed
    assert blocked.reason == "path is outside current slice"


def test_work_write_is_create_only(tmp_path: Path) -> None:
    work = make_work()
    write_work_create_only(tmp_path, work)

    with pytest.raises(FileExistsError):
        write_work_create_only(tmp_path, work)


def test_every_declared_transition_edge_is_accepted() -> None:
    for source, targets in ALLOWED_TRANSITIONS.items():
        for target in targets:
            work = make_work()
            payload = work.as_dict()
            payload["status"] = source
            if source == "completed":
                payload["result_ref"] = "works/W-001/RESULT.json"
            source_work = work_from_payload(payload)
            result_ref = "works/W-001/RESULT.json" if target == "completed" else ""

            updated = transition_work(source_work, target, result_ref=result_ref)

            assert updated.status == target


def test_undeclared_transition_edges_are_rejected() -> None:
    statuses = set(ALLOWED_TRANSITIONS)
    for source, targets in ALLOWED_TRANSITIONS.items():
        for target in statuses - targets - {source}:
            work = make_work()
            payload = work.as_dict()
            payload["status"] = source
            if source == "completed":
                payload["result_ref"] = "works/W-001/RESULT.json"
            source_work = work_from_payload(payload)

            with pytest.raises(ValueError, match="invalid Work transition"):
                transition_work(source_work, target)


def test_completed_transition_requires_result_ref() -> None:
    active = transition_work(make_work(), "active")

    with pytest.raises(ValueError, match="result_ref"):
        transition_work(active, "completed")


def test_atomic_status_update_requires_expected_status(tmp_path: Path) -> None:
    _process_route(tmp_path)
    write_work_create_only(tmp_path, make_work())

    active = update_work_status(
        tmp_path,
        "W-001",
        expected_status="planned",
        new_status="active",
    )

    assert active.status == "active"
    with pytest.raises(ValueError, match="expected planned, current active"):
        update_work_status(
            tmp_path,
            "W-001",
            expected_status="planned",
            new_status="cancelled",
        )
    assert load_work(tmp_path, "W-001").status == "active"


def test_cancelled_work_can_archive_without_result(tmp_path: Path) -> None:
    _process_route(tmp_path)
    write_work_create_only(tmp_path, make_work())
    update_work_status(
        tmp_path,
        "W-001",
        expected_status="planned",
        new_status="cancelled",
    )

    archived = update_work_status(
        tmp_path,
        "W-001",
        expected_status="cancelled",
        new_status="archived",
    )

    assert archived.status == "archived"
