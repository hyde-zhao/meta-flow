from __future__ import annotations

import subprocess
from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from meta_flow.workspace.git_sync import GitCommandResult, create_remote_ref_once, remote_ref_oid
from meta_flow.workspace.project_artifact_routing import (
    PathRef,
    ProjectArtifactConfig,
    resolve_project_artifact_route,
)
from meta_flow.workspace.project_worktree import (
    OperationAuthorization,
    PreparedSwitchTarget,
    RemovalAuthorization,
    UnknownValue,
    WorktreeIdentity,
    bootstrap_integration,
    build_worktree_observation,
    canonical_active_ref,
    canonical_integration_ref,
    check_project_worktree,
    create_project_worktree,
    evaluate_worktree_health,
    execute_switch,
    list_project_worktrees,
    observe_worktree,
    plan_worktree_operation,
    prepare_switch_operation,
    register_project_worktree,
    resume_worktree_operation,
    safe_remove,
)
from meta_flow.workspace.worktree_capacity import (
    CalibrationEvidence,
    CapacityProbe,
    CheckoutEntry,
    CheckoutSnapshot,
    prove_checkout_capacity,
)
from meta_flow.workspace.worktree_journal import DurableIntent, DurableRecord, WorktreeJournal


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return result.stdout.strip()


def _repo_fixture(tmp_path: Path) -> tuple[Path, Path, str]:
    remote = tmp_path / "remotes" / "artifact.git"
    control = tmp_path / "artifact-control"
    remote.parent.mkdir(parents=True)
    _git(tmp_path, "init", "--bare", remote.as_posix())
    control.mkdir()
    _git(control, "init")
    _git(control, "switch", "-c", "main")
    _git(control, "config", "user.name", "Meta Flow Fixture")
    _git(control, "config", "user.email", "fixture@example.invalid")
    (control / "README.md").write_text("fixture\n", encoding="utf-8")
    _git(control, "add", "README.md")
    _git(control, "commit", "-m", "initial")
    _git(control, "remote", "add", "origin", remote.as_posix())
    _git(control, "push", "origin", "main")
    _git(remote, "symbolic-ref", "HEAD", "refs/heads/main")
    return control, remote, _git(control, "rev-parse", "HEAD")


def _identity(tmp_path: Path, project_id: str = "meta-flow") -> WorktreeIdentity:
    target = tmp_path / "projects" / project_id
    common = tmp_path / "artifact-control" / ".git"
    return WorktreeIdentity(
        project_id=project_id,
        repository_id="artifact-fixture",
        repository_fingerprint="repo-fingerprint",
        worktree_id=f"worktree-{project_id}",
        repo_common_dir=common,
        common_dir_digest="common-digest",
        target_path=target,
        target_path_digest=f"target-{project_id}",
        expected_gitdir=None,
        integration_ref=canonical_integration_ref(project_id),
    )


def _route(tmp_path: Path, project_id: str = "meta-flow"):
    config = ProjectArtifactConfig(
        schema_version=1,
        project_id=project_id,
        layout_version="project-first-worktree-v1",
        artifact_control_root=PathRef("project_root", "artifact-control"),
        sibling_root=PathRef("project_root", "projects"),
        project_worktree=PathRef("sibling_root", project_id),
        docs_relative=PathRef("project_worktree", "docs"),
        process_relative=PathRef("project_worktree", "process"),
        branch_namespace=f"projects/{project_id}",
        owned_paths=("docs", "process"),
    )
    return resolve_project_artifact_route(
        config,
        project_root=tmp_path,
        target_kind="process",
        intent="write",
        observed_at="2026-07-18T00:00:00+00:00",
    )


def _observation(tmp_path: Path, **overrides: object):
    values: dict[str, object] = {
        "identity": _identity(tmp_path),
        "observed_at": datetime.now(UTC),
        "route_config_digest": "route-digest",
        "worktree_state": "ORIGINAL",
        "head_ref": canonical_integration_ref("meta-flow"),
        "head_oid": "a" * 40,
        "integration_oid": "a" * 40,
        "dirty": False,
        "staged": False,
        "untracked": False,
        "git_operation": "NONE",
        "registry_state": "CONSISTENT",
        "role": "IDLE_INTEGRATION",
    }
    values.update(overrides)
    return build_worktree_observation(**values)


def _health(observation, **overrides: object):
    values: dict[str, object] = {
        "journal_state": "IDLE",
        "active_operation_id": None,
        "project_id": observation.identity.project_id,
        "expected_route_config_digest": observation.route_config_digest,
        "evaluated_at": observation.observed_at + timedelta(seconds=1),
        "max_observation_age_seconds": 30,
    }
    values.update(overrides)
    return evaluate_worktree_health(observation, **values)


def _durable_intent(tmp_path: Path, target_ref: str, target_oid: str) -> DurableIntent:
    base = DurableRecord(
        sequence=1,
        phase="INTENT",
        payload={
            "authorization_id": "AUTH-FIXTURE-1",
            "capacity_proof_ref": "capacity://fixture-pass",
            "project_id": "meta-flow",
            "route_digest": "route-digest",
            "target_ref": target_ref,
            "target_oid": target_oid,
        },
        previous_record_ref=None,
        previous_record_digest=None,
        record_digest="1" * 64,
        path=tmp_path / "intent.json",
    )
    seal = DurableRecord(
        sequence=2,
        phase="INTENT_SEAL",
        payload={"sealed_record_digest": base.record_digest},
        previous_record_ref=base.path.name,
        previous_record_digest=base.record_digest,
        record_digest="2" * 64,
        path=tmp_path / "seal.json",
    )
    return DurableIntent("op-1", "attempt-1", base, seal, sealed=True)


def _prepared_switch(
    tmp_path: Path,
    before,
    target_ref: str,
    target_oid: str,
    *,
    operation: str = "SWITCH",
    authorization_id: str = "AUTH-SWITCH-1",
):
    calibration = CalibrationEvidence(
        profile_id="plain-checkout",
        profile_version="1",
        profile_digest="profile-digest",
        status="CALIBRATED",
        false_safe_count=0,
        underestimate_count=0,
        calibration_ref="fixture://capacity/plain-v1",
    )
    snapshot = CheckoutSnapshot(
        profile_id=calibration.profile_id,
        profile_version=calibration.profile_version,
        profile_digest=calibration.profile_digest,
        tree_oid=target_oid,
        index_digest="index-digest",
        sparse_digest="sparse-digest",
        entries=(CheckoutEntry("docs/file.md", 4096),),
        current_index_size=4096,
        target_index_encoded_size=4096,
        block_size=4096,
        enumeration_complete=True,
        transform_safe=True,
    )
    capacity = prove_checkout_capacity(
        snapshot,
        checkout_fs=CapacityProbe("checkout-fs", 1024 * 1024 * 1024, 4096),
        journal_fs=CapacityProbe("journal-fs", 1024 * 1024 * 1024, 4096),
        calibration=calibration,
    )
    authorization = OperationAuthorization(
        authorization_id=authorization_id,
        operation=operation,
        project_id=before.identity.project_id,
        expected_route_digest=before.route_config_digest,
        expected_ref=before.head_ref,
        expected_oid=before.head_oid,
    )
    plan = plan_worktree_operation(
        operation,
        before,
        desired_ref=target_ref,
        desired_oid=target_oid,
        checkout_capacity_ref="pending://checkout",
        journal_capacity_ref="pending://journal",
        operation_id="op-switch",
        attempt_id="attempt-1",
        created_at=before.observed_at,
    )
    journal = WorktreeJournal(
        store_root=tmp_path / "state" / before.identity.project_id,
        target_path=before.identity.target_path,
        project_id=before.identity.project_id,
        repository_id=before.identity.repository_id,
    )
    intent = prepare_switch_operation(
        plan,
        PreparedSwitchTarget(before, target_ref, target_oid),
        capacity,
        calibration,
        authorization,
        journal=journal,
        created_at=before.observed_at,
    )
    return journal, intent, authorization


def test_port_w_01_rich_observation_is_immutable_and_complete(tmp_path: Path) -> None:
    observation = _observation(tmp_path)

    assert observation.observation_digest
    assert {field.name for field in fields(observation)} >= {
        "identity",
        "head_ref",
        "head_oid",
        "dirty",
        "staged",
        "untracked",
        "git_operation",
        "registry_state",
        "role",
        "observed_at",
        "route_config_digest",
    }
    with pytest.raises(FrozenInstanceError):
        observation.dirty = True  # type: ignore[misc]


def test_port_w_02_unknown_is_typed_and_fails_closed(tmp_path: Path) -> None:
    observation = _observation(tmp_path, dirty=UnknownValue("status_unknown", "fixture://status"))

    health = _health(observation)

    assert health.decision == "BLOCKED"
    assert "observation_incomplete" in health.reason_codes


def test_port_w_03_healthy_envelope_carries_exact_observation(tmp_path: Path) -> None:
    observation = _observation(tmp_path)

    health = _health(observation)

    assert health.decision == "HEALTHY"
    assert health.observation is observation
    assert health.observation_digest == observation.observation_digest


def test_port_w_04_missing_observation_is_not_healthy() -> None:
    health = evaluate_worktree_health(
        None,
        journal_state="IDLE",
        active_operation_id=None,
        project_id="meta-flow",
        expected_route_config_digest="route-digest",
        evaluated_at=datetime.now(UTC),
        max_observation_age_seconds=30,
    )

    assert health.decision == "BLOCKED"
    assert "observation_missing" in health.reason_codes


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"project_id": "other"}, "project_mismatch"),
        ({"expected_route_config_digest": "other"}, "route_digest_mismatch"),
        ({"evaluated_at": datetime.now(UTC) + timedelta(days=1)}, "observation_stale"),
    ],
)
def test_port_w_05_to_06_mismatch_or_stale_is_non_healthy(
    tmp_path: Path, overrides: dict[str, object], reason: str
) -> None:
    observation = _observation(tmp_path)
    if "evaluated_at" in overrides:
        overrides["evaluated_at"] = observation.observed_at + timedelta(days=1)

    health = _health(observation, **overrides)

    assert health.decision != "HEALTHY"
    assert reason in health.reason_codes


def test_port_w_07_health_evaluator_is_pure(tmp_path: Path) -> None:
    observation = _observation(tmp_path)

    first = _health(observation)
    second = _health(observation)

    assert first == second


def test_port_w_08_health_has_no_flattened_snapshot_schema(tmp_path: Path) -> None:
    health = _health(_observation(tmp_path))
    field_names = {field.name for field in fields(health)}

    assert {"head_ref", "head_oid", "dirty", "repo_common_dir"}.isdisjoint(field_names)


def test_wt_01_absent_integration_is_created_exactly_once(tmp_path: Path) -> None:
    control, _, seed = _repo_fixture(tmp_path)
    ref = canonical_integration_ref("meta-flow")

    result = create_remote_ref_once(control, "origin", ref, seed)

    assert result.decision == "CREATED"
    assert result.mutation_count == 1
    assert remote_ref_oid(control, "origin", ref) == seed
    assert all("--force" not in arg and not arg.startswith("+") for arg in result.argv)


def test_wt_02_existing_integration_is_never_recreated(tmp_path: Path) -> None:
    control, _, seed = _repo_fixture(tmp_path)
    ref = canonical_integration_ref("meta-flow")
    assert create_remote_ref_once(control, "origin", ref, seed).decision == "CREATED"

    result = create_remote_ref_once(control, "origin", ref, seed)

    assert result.decision == "NO_CHANGE"
    assert result.mutation_count == 0
    assert result.argv == ()


def test_wt_03_rejected_concurrent_same_oid_converges_without_retry(tmp_path: Path) -> None:
    calls = 0

    def runner(args: list[str], cwd: Path) -> GitCommandResult:
        nonlocal calls
        calls += 1
        if args[0] == "ls-remote" and calls == 1:
            return GitCommandResult(("git", *args), cwd, 0, "", "")
        if args[0] == "push":
            return GitCommandResult(("git", *args), cwd, 1, "", "rejected")
        return GitCommandResult(("git", *args), cwd, 0, f"{'a' * 40}\t{args[-1]}\n", "")

    result = create_remote_ref_once(
        tmp_path, "origin", canonical_integration_ref("meta-flow"), "a" * 40, runner=runner
    )

    assert result.decision == "NO_CHANGE"
    assert result.reason == "race_same_oid"
    assert result.mutation_count == 1
    assert calls == 3


def test_wt_04_rejected_concurrent_different_oid_is_blocked(tmp_path: Path) -> None:
    calls = 0

    def runner(args: list[str], cwd: Path) -> GitCommandResult:
        nonlocal calls
        calls += 1
        if args[0] == "ls-remote" and calls == 1:
            return GitCommandResult(("git", *args), cwd, 0, "", "")
        if args[0] == "push":
            return GitCommandResult(("git", *args), cwd, 1, "", "rejected")
        return GitCommandResult(("git", *args), cwd, 0, f"{'b' * 40}\t{args[-1]}\n", "")

    result = create_remote_ref_once(
        tmp_path, "origin", canonical_integration_ref("meta-flow"), "a" * 40, runner=runner
    )

    assert result.decision == "BLOCKED"
    assert result.reason == "remote_race_conflict"
    assert calls == 3


class RecordingRunner:
    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, args: list[str], cwd: Path) -> GitCommandResult:
        self.calls.append(tuple(args))
        return GitCommandResult(("git", *args), cwd, self.returncode, "", "fixture")


@pytest.mark.parametrize(
    ("case_id", "after_overrides", "decision", "reason"),
    [
        (
            "WT-05",
            {"head_ref": "refs/heads/unexpected", "head_oid": "c" * 40, "worktree_state": "THIRD"},
            "RECOVERY_REQUIRED",
            "third_state",
        ),
        ("WT-06", {}, "CHANGED", "target_verified"),
        (
            "WT-07",
            {
                "head_ref": canonical_integration_ref("meta-flow"),
                "head_oid": "a" * 40,
                "role": "IDLE_INTEGRATION",
                "worktree_state": "ORIGINAL",
            },
            "NO_CHANGE",
            "original_verified",
        ),
        ("WT-08", {"dirty": True}, "RECOVERY_REQUIRED", "dirty_state"),
    ],
)
def test_wt_05_to_08_switch_always_uses_fresh_observation(
    tmp_path: Path,
    case_id: str,
    after_overrides: dict[str, object],
    decision: str,
    reason: str,
) -> None:
    target_ref = canonical_active_ref("meta-flow", "CR-051", "recoverable")
    target_oid = "b" * 40
    before = _observation(tmp_path)
    default_after = {
        "head_ref": target_ref,
        "head_oid": target_oid,
        "role": "ACTIVE_CR",
        "worktree_state": "TARGET",
    }
    default_after.update(after_overrides)
    after = _observation(tmp_path, **default_after)
    runner = RecordingRunner(returncode=0 if case_id == "WT-05" else 124)
    journal, intent, authorization = _prepared_switch(tmp_path, before, target_ref, target_oid)
    observation_values = iter((before, after))
    observations = 0

    def observe():
        nonlocal observations
        observations += 1
        return next(observation_values)

    result = execute_switch(
        intent,
        PreparedSwitchTarget(before, target_ref, target_oid),
        journal=journal,
        authorization=authorization,
        git=runner,
        observe=observe,
        now=before.observed_at,
    )

    assert observations == 2
    assert result.decision == decision
    assert result.reason == reason
    assert len(runner.calls) == 1
    assert [record.phase for record in journal.scan_attempt("op-switch", "attempt-1").records] == [
        "CAPACITY_PROOF",
        "INTENT",
        "INTENT_SEAL",
        "OBSERVATION_REQUIRED",
        "FINAL_OBSERVATION",
    ]


def test_wt_08a_completed_attempt_is_idempotent_and_never_mutates_twice(tmp_path: Path) -> None:
    target_ref = canonical_active_ref("meta-flow", "CR-051", "idempotent")
    target_oid = "b" * 40
    before = _observation(tmp_path)
    after = _observation(
        tmp_path,
        head_ref=target_ref,
        head_oid=target_oid,
        role="ACTIVE_CR",
        worktree_state="TARGET",
    )
    journal, intent, authorization = _prepared_switch(tmp_path, before, target_ref, target_oid)
    runner = RecordingRunner()
    first_observations = iter((before, after))

    first = execute_switch(
        intent,
        PreparedSwitchTarget(before, target_ref, target_oid),
        journal=journal,
        authorization=authorization,
        git=runner,
        observe=lambda: next(first_observations),
        now=before.observed_at,
    )
    second = execute_switch(
        intent,
        PreparedSwitchTarget(before, target_ref, target_oid),
        journal=journal,
        authorization=authorization,
        git=runner,
        observe=lambda: after,
        now=before.observed_at,
    )

    assert first.decision == "CHANGED"
    assert second.decision == "NO_CHANGE"
    assert second.mutation_count == 0
    assert runner.calls == [("switch", "projects/meta-flow/cr/cr-051-idempotent")]


def test_wt_08b_expired_capacity_proof_blocks_before_git(tmp_path: Path) -> None:
    target_ref = canonical_active_ref("meta-flow", "CR-051", "expired")
    before = _observation(tmp_path)
    journal, intent, authorization = _prepared_switch(tmp_path, before, target_ref, "b" * 40)
    runner = RecordingRunner()

    result = execute_switch(
        intent,
        PreparedSwitchTarget(before, target_ref, "b" * 40),
        journal=journal,
        authorization=authorization,
        git=runner,
        observe=lambda: before,
        now=before.observed_at + timedelta(minutes=6),
    )

    assert result.decision == "BLOCKED"
    assert result.reason == "capacity_proof_expired"
    assert result.mutation_count == 0
    assert runner.calls == []


def test_wt_08c_persisted_calibration_revocation_blocks_before_git(tmp_path: Path) -> None:
    target_ref = canonical_active_ref("meta-flow", "CR-051", "revoked")
    before = _observation(tmp_path)
    journal, intent, authorization = _prepared_switch(tmp_path, before, target_ref, "b" * 40)
    calibration = journal.load_calibration("profile-digest")
    journal.save_calibration(replace(calibration, status="REVOKED", false_safe_count=1))
    runner = RecordingRunner()

    result = execute_switch(
        intent,
        PreparedSwitchTarget(before, target_ref, "b" * 40),
        journal=journal,
        authorization=authorization,
        git=runner,
        observe=lambda: before,
        now=before.observed_at,
    )

    assert result.decision == "BLOCKED"
    assert result.reason == "calibration_revoked_or_mismatch"
    assert runner.calls == []


def test_wt_09_rollback_requires_a_fresh_durable_authorization(tmp_path: Path) -> None:
    active_ref = canonical_active_ref("meta-flow", "CR-051", "rollback")
    current = _observation(
        tmp_path,
        head_ref=active_ref,
        head_oid="b" * 40,
        role="ACTIVE_CR",
        worktree_state="TARGET",
    )
    original = _observation(tmp_path)
    authorization = OperationAuthorization(
        authorization_id="AUTH-ROLLBACK-1",
        operation="ROLLBACK",
        project_id="meta-flow",
        expected_route_digest="route-digest",
        expected_ref=current.head_ref,
        expected_oid=current.head_oid,
    )
    journal, intent, prepared_authorization = _prepared_switch(
        tmp_path,
        current,
        original.head_ref,  # type: ignore[arg-type]
        original.head_oid,  # type: ignore[arg-type]
        operation="ROLLBACK",
        authorization_id=authorization.authorization_id,
    )
    runner = RecordingRunner()
    observations = iter((current, original))

    assert authorization.matches(current)
    result = execute_switch(
        intent,
        PreparedSwitchTarget(
            current,
            original.head_ref,  # type: ignore[arg-type]
            original.head_oid,  # type: ignore[arg-type]
        ),
        journal=journal,
        authorization=prepared_authorization,
        git=runner,
        observe=lambda: next(observations),
        now=current.observed_at,
    )

    assert intent.sealed is True
    assert result.decision == "CHANGED"
    assert result.reason == "target_verified"
    assert result.mutation_count == 1
    assert runner.calls == [("switch", "projects/meta-flow/integration")]


def test_wt_10_unknown_rollback_condition_never_calls_git(tmp_path: Path) -> None:
    observation = _observation(tmp_path, dirty=UnknownValue("dirty_unknown", None))
    authorization = OperationAuthorization(
        authorization_id="AUTH-ROLLBACK-1",
        operation="ROLLBACK",
        project_id="meta-flow",
        expected_route_digest="route-digest",
        expected_ref=observation.head_ref,
        expected_oid=observation.head_oid,
    )
    runner = RecordingRunner()

    assert authorization.matches(observation) is False
    assert runner.calls == []


def test_wt_10_missing_capacity_or_authorization_blocks_switch_before_git(tmp_path: Path) -> None:
    target_ref = canonical_active_ref("meta-flow", "CR-051", "blocked")
    target_oid = "b" * 40
    before = _observation(tmp_path)
    journal, intent, authorization = _prepared_switch(tmp_path, before, target_ref, target_oid)
    broken_record = DurableRecord(
        sequence=intent.intent_record.sequence,
        phase=intent.intent_record.phase,
        payload={"target_ref": target_ref, "target_oid": target_oid},
        previous_record_ref=intent.intent_record.previous_record_ref,
        previous_record_digest=intent.intent_record.previous_record_digest,
        record_digest=intent.intent_record.record_digest,
        path=intent.intent_record.path,
    )
    broken = DurableIntent(
        intent.operation_id,
        intent.attempt_id,
        broken_record,
        intent.seal_record,
        sealed=True,
    )
    runner = RecordingRunner()

    result = execute_switch(
        broken,
        PreparedSwitchTarget(before, target_ref, target_oid),
        journal=journal,
        authorization=authorization,
        git=runner,
        observe=lambda: pytest.fail(
            "blocked switch must not observe after a non-existent mutation"
        ),
        now=before.observed_at,
    )

    assert result.decision == "BLOCKED"
    assert result.mutation_count == 0
    assert runner.calls == []


def test_wt_11_sibling_branch_roles_are_project_scoped_and_main_is_invalid() -> None:
    refs = {
        canonical_integration_ref("project-a"),
        canonical_active_ref("project-a", "CR-051", "work"),
        canonical_integration_ref("project-b"),
        canonical_active_ref("project-b", "CR-051", "work"),
    }

    assert len(refs) == 4
    assert "refs/heads/main" not in refs


def test_wt_12_dirty_current_health_blocks_mutation(tmp_path: Path) -> None:
    health = _health(_observation(tmp_path, dirty=True))

    assert health.decision == "BLOCKED"
    assert "dirty_state" in health.reason_codes


@pytest.mark.parametrize(
    "change",
    [
        {"authorized": False},
        {"expected_project_id": "other"},
        {"expected_role": "ACTIVE_CR"},
    ],
)
def test_wt_13_unsafe_remove_never_calls_git(tmp_path: Path, change: dict[str, object]) -> None:
    observation = _observation(tmp_path)
    health = _health(observation)
    values: dict[str, object] = {
        "authorization_id": "AUTH-REMOVE-1",
        "expected_project_id": "meta-flow",
        "expected_target_digest": observation.identity.target_path_digest,
        "expected_role": "IDLE_INTEGRATION",
        "authorized": True,
    }
    values.update(change)
    runner = RecordingRunner()

    result = safe_remove(
        observation.identity,
        health,
        RemovalAuthorization(**values),
        git=runner,
        observe_absent=lambda: True,
    )

    assert result.decision == "BLOCKED"
    assert runner.calls == []


def test_wt_14_recovery_required_remove_is_diagnostic_only(tmp_path: Path) -> None:
    observation = _observation(tmp_path, registry_state="STALE")
    health = _health(observation, journal_state="RECOVERY_REQUIRED", active_operation_id="op-1")
    runner = RecordingRunner()
    auth = RemovalAuthorization(
        authorization_id="AUTH-REMOVE-1",
        expected_project_id="meta-flow",
        expected_target_digest=observation.identity.target_path_digest,
        expected_role="IDLE_INTEGRATION",
        authorized=True,
    )

    result = safe_remove(
        observation.identity, health, auth, git=runner, observe_absent=lambda: True
    )

    assert result.decision == "BLOCKED"
    assert runner.calls == []


def test_tc_aw_004_bootstrap_create_register_check_and_list_use_only_local_fixture(
    tmp_path: Path,
) -> None:
    control, _, seed = _repo_fixture(tmp_path)
    (tmp_path / "projects").mkdir()
    identity = _identity(tmp_path)
    route = _route(tmp_path)
    ref = identity.integration_ref
    intent = _durable_intent(tmp_path, ref, seed)

    bootstrap = bootstrap_integration(intent, root=control, remote="origin", integration_ref=ref)
    result = create_project_worktree(
        intent,
        bootstrap,
        identity=identity,
        observe=lambda: observe_worktree(route, identity=identity),
    )
    observation = observe_worktree(route, identity=identity)
    registration = register_project_worktree(observation)
    health = check_project_worktree(
        registration,
        observation,
        journal_state="IDLE",
        active_operation_id=None,
        evaluated_at=observation.observed_at + timedelta(seconds=1),
    )
    listed = list_project_worktrees(
        (registration,),
        {"meta-flow": observation},
        evaluated_at=observation.observed_at + timedelta(seconds=1),
    )

    assert bootstrap.decision == "CREATED"
    assert bootstrap.mutation_count == 1
    assert result.decision == "CHANGED"
    assert observation.role == "IDLE_INTEGRATION"
    assert observation.head_ref == ref
    assert observation.head_oid == seed
    assert health.decision == "HEALTHY"
    assert listed == (health,)
    assert _git(control, "symbolic-ref", "HEAD") == "refs/heads/main"


def test_tc_aw_005_two_project_namespaces_never_cross(tmp_path: Path) -> None:
    observations = (
        _observation(
            tmp_path, identity=_identity(tmp_path, "project-a"), route_config_digest="route-a"
        ),
        _observation(
            tmp_path, identity=_identity(tmp_path, "project-b"), route_config_digest="route-b"
        ),
    )
    registrations = tuple(register_project_worktree(item) for item in observations)
    listed = list_project_worktrees(
        registrations,
        {item.identity.project_id: item for item in observations},
        evaluated_at=max(item.observed_at for item in observations) + timedelta(seconds=1),
    )

    assert [item.project_id for item in listed] == ["project-a", "project-b"]
    assert all(item.decision == "HEALTHY" for item in listed)
    assert observations[0].identity.target_path != observations[1].identity.target_path
    assert canonical_active_ref("project-a", "CR-051", "work") != canonical_active_ref(
        "project-b", "CR-051", "work"
    )


@pytest.mark.parametrize(
    ("call", "args"),
    [
        (canonical_integration_ref, ("--upload-pack=bad",)),
        (canonical_integration_ref, ("project\nother",)),
        (canonical_active_ref, ("meta-flow", "CR-051", "bad slug")),
        (canonical_active_ref, ("meta-flow", "CR-051", "../escape")),
    ],
)
def test_tc_aw_007_unsafe_namespace_tokens_are_rejected(call, args: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        call(*args)


def test_tc_aw_010_cross_project_remove_authorization_is_rejected(tmp_path: Path) -> None:
    observation = _observation(tmp_path)
    health = _health(observation)
    runner = RecordingRunner()
    auth = RemovalAuthorization(
        authorization_id="AUTH-REMOVE-OTHER",
        expected_project_id="other-project",
        expected_target_digest=observation.identity.target_path_digest,
        expected_role="IDLE_INTEGRATION",
        authorized=True,
    )

    result = safe_remove(
        observation.identity, health, auth, git=runner, observe_absent=lambda: True
    )

    assert result.decision == "BLOCKED"
    assert runner.calls == []


def test_tc_aw_011_safe_remove_uses_only_non_force_exact_target(tmp_path: Path) -> None:
    observation = _observation(tmp_path)
    health = _health(observation)
    runner = RecordingRunner()
    auth = RemovalAuthorization(
        authorization_id="AUTH-REMOVE-1",
        expected_project_id="meta-flow",
        expected_target_digest=observation.identity.target_path_digest,
        expected_role="IDLE_INTEGRATION",
        authorized=True,
    )

    result = safe_remove(
        observation.identity, health, auth, git=runner, observe_absent=lambda: True
    )

    assert result.decision == "CHANGED"
    assert runner.calls == [("worktree", "remove", observation.identity.target_path.as_posix())]


def test_tc_aw_012_operation_plan_is_a_zero_mutation_dry_run(tmp_path: Path) -> None:
    observation = _observation(tmp_path)
    target_ref = canonical_active_ref("meta-flow", "CR-051", "dry-run")
    runner = RecordingRunner()

    plan = plan_worktree_operation(
        "SWITCH",
        observation,
        desired_ref=target_ref,
        desired_oid="b" * 40,
        checkout_capacity_ref="capacity://checkout",
        journal_capacity_ref="capacity://journal",
        operation_id="op-dry-run",
        attempt_id="attempt-1",
        created_at=observation.observed_at,
    )

    assert plan.target_ref == target_ref
    assert plan.before_observation_digest == observation.observation_digest
    assert runner.calls == []


def test_tc_aw_015_resume_observes_first_and_is_idempotent(tmp_path: Path) -> None:
    target = tmp_path / "projects" / "meta-flow"
    target.mkdir(parents=True)
    identity = _identity(tmp_path)
    route = _route(tmp_path)
    original = _observation(tmp_path)
    journal = WorktreeJournal(
        store_root=tmp_path / "state" / "meta-flow",
        target_path=target,
        project_id="meta-flow",
        repository_id="artifact-fixture",
    )
    journal.persist_intent(
        "op-1",
        "attempt-1",
        {
            "target_ref": original.head_ref,
            "target_oid": original.head_oid,
            "original_ref": original.head_ref,
            "original_oid": original.head_oid,
            "before_observation_digest": original.observation_digest,
        },
    )
    observations = 0

    def observe():
        nonlocal observations
        observations += 1
        return original

    results = [
        resume_worktree_operation(
            "op-1",
            "attempt-1",
            route=route,
            identity=identity,
            journal=journal,
            observe=observe,
        )
        for _ in range(10)
    ]

    assert observations == 10
    assert all(result.decision == "NO_CHANGE" for result in results)
    assert all(result.mutation_count == 0 for result in results)
    assert all(result == results[0] for result in results)


def test_tc_aw_fixture_never_contains_dangerous_recovery_argv(tmp_path: Path) -> None:
    runner = RecordingRunner()
    observation = _observation(tmp_path)
    health = _health(observation)
    auth = RemovalAuthorization(
        authorization_id="AUTH-REMOVE-1",
        expected_project_id="meta-flow",
        expected_target_digest=observation.identity.target_path_digest,
        expected_role="IDLE_INTEGRATION",
        authorized=True,
    )

    safe_remove(observation.identity, health, auth, git=runner, observe_absent=lambda: True)

    flattened = " ".join(arg for call in runner.calls for arg in call)
    for forbidden in ("reset --hard", "clean", "stash", "--force", "branch -D", "branch -d"):
        assert forbidden not in flattened
    assert runner.calls == [("worktree", "remove", observation.identity.target_path.as_posix())]
