from __future__ import annotations

import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from meta_flow.workflow.artifact_leg_lifecycle import (
    ExpectedPublishedLegResult,
    InMemoryLegResultStore,
    LegAuthorization,
    LegBlocker,
    LegExecutionOutcome,
    LegPlan,
    LegPreparationOutcome,
    LegRequest,
    LegResultPayload,
    LegRouteProof,
    StepReceipt,
    UnpublishedLegResultOutcome,
    abort_leg,
    build_leg_observation,
    build_leg_plan,
    canonical_artifact_active_ref,
    canonical_artifact_integration_ref,
    canonical_payload_digest,
    canonical_source_active_ref,
    derive_single_write_key,
    execute_leg,
    payload_from_dict,
    payload_to_dict,
    publish_leg_payload,
    resume_leg,
    retry_unpublished_payload,
    seal_leg_result_payload,
    validate_published_leg_result,
)
from meta_flow.workflow.git_branch_lifecycle import RepoOutcome, project_merge
from meta_flow.workspace.git_sync import GitCommandResult
from meta_flow.workspace.project_worktree import (
    WorktreeHealth,
    WorktreeIdentity,
    build_worktree_observation,
)

OID_A = "a" * 40
OID_B = "b" * 40
OID_C = "c" * 40
NOW = datetime(2026, 7, 18, 13, 30, tzinfo=UTC)


def _source_route(tmp_path: Path) -> LegRouteProof:
    return LegRouteProof(
        project_id="meta-flow",
        mode="source-default",
        repository_root=tmp_path / "source",
        repository_fingerprint="source-fingerprint",
        remote="origin",
        route_config_digest="1" * 64,
        source_default_ref="refs/heads/main",
        owned_target=True,
    )


def _artifact_route(tmp_path: Path) -> LegRouteProof:
    return LegRouteProof(
        project_id="meta-flow",
        mode="shared-artifact-project-first",
        repository_root=tmp_path / "artifact-project",
        repository_fingerprint="artifact-fingerprint",
        remote="origin",
        route_config_digest="2" * 64,
        source_default_ref="",
        owned_target=True,
    )


def _source_request(route: LegRouteProof, *, dry_run: bool = True) -> LegRequest:
    return LegRequest(
        schema_version=1,
        operation_id="op-051",
        logical_attempt=1,
        cr_id="CR-051",
        project_id="meta-flow",
        slug="artifact-worktree",
        leg_kind="source",
        mode="source-default",
        operation="publish",
        base_ref="refs/heads/main",
        target_ref="refs/heads/main",
        expected_base_oid=OID_A,
        expected_target_oid=OID_A,
        authorization_ref="" if dry_run else "AUTH-051",
        route_config_digest=route.route_config_digest,
        worktree_health_digest="",
        dry_run=dry_run,
    )


def _artifact_request(route: LegRouteProof, *, dry_run: bool = True) -> LegRequest:
    integration_ref = canonical_artifact_integration_ref("meta-flow")
    return LegRequest(
        schema_version=1,
        operation_id="op-051",
        logical_attempt=1,
        cr_id="CR-051",
        project_id="meta-flow",
        slug="artifact-worktree",
        leg_kind="artifact",
        mode="shared-artifact-project-first",
        operation="complete",
        base_ref=integration_ref,
        target_ref=integration_ref,
        expected_base_oid=OID_A,
        expected_target_oid=OID_A,
        authorization_ref="" if dry_run else "AUTH-051",
        route_config_digest=route.route_config_digest,
        worktree_health_digest="",
        dry_run=dry_run,
    )


def _source_observation(route: LegRouteProof):
    return build_leg_observation(
        repository_fingerprint=route.repository_fingerprint,
        base_ref=route.source_default_ref,
        target_ref=route.source_default_ref,
        active_ref=canonical_source_active_ref("CR-051", "artifact-worktree"),
        base_oid=OID_A,
        target_oid=OID_A,
        active_oid=OID_B,
        head_oid=OID_B,
        observed_at=NOW,
        dirty=False,
        staged=False,
        untracked=False,
        git_operation="NONE",
    )


def _artifact_health(
    route: LegRouteProof,
    *,
    dirty: bool = False,
    observed_at: datetime = NOW,
    integration_oid: str = OID_A,
) -> WorktreeHealth:
    integration_ref = canonical_artifact_integration_ref(route.project_id)
    active_ref = canonical_artifact_active_ref(route.project_id, "CR-051", "artifact-worktree")
    identity = WorktreeIdentity(
        project_id=route.project_id,
        repository_id="artifact-repository",
        repository_fingerprint=route.repository_fingerprint,
        worktree_id="meta-flow-worktree",
        repo_common_dir=route.repository_root.parent / ".git-common",
        common_dir_digest="3" * 64,
        target_path=route.repository_root,
        target_path_digest="4" * 64,
        expected_gitdir=route.repository_root / ".git",
        integration_ref=integration_ref,
    )
    observation = build_worktree_observation(
        identity=identity,
        observed_at=observed_at,
        route_config_digest=route.route_config_digest,
        worktree_state="ACTIVE_CR",
        head_ref=active_ref,
        head_oid=OID_B,
        integration_oid=integration_oid,
        dirty=dirty,
        staged=False,
        untracked=False,
        git_operation="NONE",
        registry_state="CONSISTENT",
        role="ACTIVE_CR",
    )
    return WorktreeHealth(
        project_id=route.project_id,
        decision="HEALTHY" if not dirty else "BLOCKED",
        observation=observation,
        observation_digest=observation.observation_digest,
        worktree_state="ACTIVE_CR",
        journal_state="VERIFIED_TARGET",
        active_operation_id=None,
        reason_codes=() if not dirty else ("dirty_state",),
    )


def _artifact_observation(
    route: LegRouteProof,
    *,
    target_oid: str = OID_A,
    active_oid: str = OID_B,
):
    integration_ref = canonical_artifact_integration_ref(route.project_id)
    return build_leg_observation(
        repository_fingerprint=route.repository_fingerprint,
        base_ref=integration_ref,
        target_ref=integration_ref,
        active_ref=canonical_artifact_active_ref(route.project_id, "CR-051", "artifact-worktree"),
        base_oid=OID_A,
        target_oid=target_oid,
        active_oid=active_oid,
        head_oid=OID_B,
        observed_at=NOW,
        dirty=False,
        staged=False,
        untracked=False,
        git_operation="NONE",
    )


def _authorization(request: LegRequest, route: LegRouteProof) -> LegAuthorization:
    active_ref = (
        canonical_source_active_ref(request.cr_id, request.slug)
        if request.leg_kind == "source"
        else canonical_artifact_active_ref(request.project_id, request.cr_id, request.slug)
    )
    return LegAuthorization(
        authorization_id=request.authorization_ref,
        action=request.operation,
        correlation=request.correlation,
        mode=request.mode,
        repository_fingerprint=route.repository_fingerprint,
        remote=route.remote,
        base_ref=request.base_ref,
        target_ref=request.target_ref,
        active_ref=active_ref,
        expected_base_oid=request.expected_base_oid,
        expected_target_oid=request.expected_target_oid,
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=5),
        single_use=True,
    )


def _live_authorization(
    request: LegRequest,
    route: LegRouteProof,
    *,
    reference: datetime,
) -> LegAuthorization:
    return replace(
        _authorization(request, route),
        issued_at=reference - timedelta(minutes=1),
        expires_at=reference + timedelta(minutes=5),
    )


def _observation_at(observation, observed_at: datetime, **changes):
    values = {
        "repository_fingerprint": observation.repository_fingerprint,
        "base_ref": observation.base_ref,
        "target_ref": observation.target_ref,
        "active_ref": observation.active_ref,
        "base_oid": observation.base_oid,
        "target_oid": observation.target_oid,
        "active_oid": observation.active_oid,
        "head_oid": observation.head_oid,
        "observed_at": observed_at,
        "dirty": observation.dirty,
        "staged": observation.staged,
        "untracked": observation.untracked,
        "git_operation": observation.git_operation,
    }
    values.update(changes)
    return build_leg_observation(**values)


def test_source_policy_derives_default_base_target_and_active_ref(tmp_path: Path) -> None:
    route = _source_route(tmp_path)
    request = _source_request(route)

    result = build_leg_plan(request, route, _source_observation(route), now=NOW)

    assert isinstance(result, LegPlan)
    assert result.target.base_ref == "refs/heads/main"
    assert result.target.target_ref == "refs/heads/main"
    assert result.target.active_ref == "refs/heads/cr/cr-051-artifact-worktree"
    assert result.dry_run is True


def test_artifact_policy_uses_only_project_integration_and_nested_health(tmp_path: Path) -> None:
    route = _artifact_route(tmp_path)
    health = _artifact_health(route)
    request = replace(
        _artifact_request(route), worktree_health_digest=health.observation_digest or ""
    )

    result = build_leg_plan(
        request,
        route,
        _artifact_observation(route),
        worktree_health=health,
        now=NOW,
    )

    assert isinstance(result, LegPlan)
    expected = "refs/heads/projects/meta-flow/integration"
    assert result.target.base_ref == expected
    assert result.target.target_ref == expected
    assert result.target.active_ref == ("refs/heads/projects/meta-flow/cr/cr-051-artifact-worktree")
    assert result.worktree_health_digest == health.observation_digest


def test_artifact_main_assertion_is_blocked_before_any_executor_exists(tmp_path: Path) -> None:
    route = _artifact_route(tmp_path)
    health = _artifact_health(route)
    request = replace(
        _artifact_request(route),
        base_ref="refs/heads/main",
        target_ref="refs/heads/main",
        worktree_health_digest=health.observation_digest or "",
    )

    result = build_leg_plan(
        request,
        route,
        _artifact_observation(route),
        worktree_health=health,
        now=NOW,
    )

    assert isinstance(result, LegPreparationOutcome)
    assert result.status == "BLOCKED"
    assert result.code == "policy_target_forbidden"


@pytest.mark.parametrize("case", ["missing", "digest-mismatch", "dirty"])
def test_artifact_health_failures_are_fail_closed(tmp_path: Path, case: str) -> None:
    route = _artifact_route(tmp_path)
    health = _artifact_health(route, dirty=case == "dirty")
    if case == "missing":
        health = replace(health, decision="HEALTHY", observation=None, observation_digest=None)
    elif case == "digest-mismatch":
        health = replace(health, observation_digest="f" * 64)
    request = replace(
        _artifact_request(route), worktree_health_digest=health.observation_digest or ""
    )

    result = build_leg_plan(
        request,
        route,
        _artifact_observation(route),
        worktree_health=health,
        now=NOW,
    )

    assert isinstance(result, LegPreparationOutcome)
    assert result.status == "BLOCKED"
    assert result.code.startswith("worktree_")


def test_fresh_expected_oid_mismatch_is_blocked(tmp_path: Path) -> None:
    route = _source_route(tmp_path)
    request = replace(_source_request(route), expected_target_oid=OID_C)

    result = build_leg_plan(request, route, _source_observation(route), now=NOW)

    assert isinstance(result, LegPreparationOutcome)
    assert result.code == "stale_observation"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("action", "finish"),
        ("repository_fingerprint", "wrong-repository"),
        ("target_ref", "refs/heads/other"),
        ("expected_target_oid", OID_C),
        ("mode", "shared-artifact-project-first"),
    ],
)
def test_typed_authorization_is_bound_to_action_repo_target_oid_attempt(
    tmp_path: Path, field: str, value: str
) -> None:
    route = _source_route(tmp_path)
    request = _source_request(route, dry_run=False)
    authorization = replace(_authorization(request, route), **{field: value})

    result = build_leg_plan(
        request,
        route,
        _source_observation(route),
        authorization=authorization,
        now=NOW,
    )

    assert isinstance(result, LegPreparationOutcome)
    assert result.code == "authorization_mismatch"


def test_non_dry_run_requires_typed_authorization(tmp_path: Path) -> None:
    route = _source_route(tmp_path)
    request = _source_request(route, dry_run=False)

    result = build_leg_plan(request, route, _source_observation(route), now=NOW)

    assert isinstance(result, LegPreparationOutcome)
    assert result.code == "authorization_missing"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("project_id", "../escape"),
        ("base_ref", "refs/heads/main\nrefs/heads/pwn"),
        ("target_ref", "-refs/heads/main"),
    ],
)
def test_unsafe_identity_or_ref_is_rejected(tmp_path: Path, field: str, value: str) -> None:
    route = _source_route(tmp_path)
    request = replace(_source_request(route), **{field: value})

    result = build_leg_plan(request, route, _source_observation(route), now=NOW)

    assert isinstance(result, LegPreparationOutcome)
    assert result.code == "invalid_input"


def _payload(
    request: LegRequest,
    *,
    status: str = "PASS",
    progress: str = "COMPLETE",
    effect: str = "TARGET_UPDATED",
    blockers: tuple[LegBlocker, ...] = (),
) -> LegResultPayload:
    receipt = StepReceipt(
        step_id="complete-remote-target",
        argv_digest="5" * 64,
        returncode=0,
        before_oid=OID_A,
        expected_oid=OID_B,
        after_oid=OID_B,
        mutation=True,
        effect=effect,
        started_at=NOW.isoformat(),
        completed_at=(NOW + timedelta(seconds=1)).isoformat(),
    )
    raw = LegResultPayload(
        schema_version=1,
        correlation=request.correlation,
        operation=request.operation,
        mode=request.mode,
        base_ref=request.base_ref,
        target_ref=request.target_ref,
        active_ref=canonical_source_active_ref(request.cr_id, request.slug),
        expected_base_oid=request.expected_base_oid,
        expected_target_oid=request.expected_target_oid,
        observed_base_oid_before=OID_A,
        observed_target_oid_before=OID_A,
        observed_active_oid_before=OID_B,
        observed_base_oid_after=OID_A,
        observed_target_oid_after=OID_B,
        observed_active_oid_after=OID_B,
        status=status,
        terminal=status != "IN_PROGRESS",
        progress=progress,
        effect=effect,
        step_receipts=(receipt,),
        blockers=blockers,
        resume_route="none" if status == "PASS" else "fresh-resume",
        abort_route="coordination-only",
        fresh_observed_at=(NOW + timedelta(seconds=1)).isoformat(),
        payload_digest="",
    )
    return seal_leg_result_payload(raw)


def test_payload_digest_is_prewrite_stable_and_has_no_append_time_fields(
    tmp_path: Path,
) -> None:
    request = _source_request(_source_route(tmp_path), dry_run=False)
    payload = _payload(request)

    serialized = payload_to_dict(payload)

    assert payload.payload_digest == canonical_payload_digest(payload)
    assert {
        "result_ref",
        "receipt",
        "writer_id",
        "written_at",
        "receipt_digest",
    }.isdisjoint(serialized)


def test_single_write_is_idempotent_for_same_payload_and_conflicts_for_other_digest(
    tmp_path: Path,
) -> None:
    request = _source_request(_source_route(tmp_path), dry_run=False)
    payload = _payload(request)
    store = InMemoryLegResultStore(writer_id="fixture-writer", now=lambda: NOW)
    key = derive_single_write_key(payload.correlation)

    first = publish_leg_payload(key, payload, store)
    second = publish_leg_payload(key, payload, store)
    conflicting = replace(payload, effect="REMOTE_PARTIAL", payload_digest="")
    conflicting = seal_leg_result_payload(conflicting)
    conflict = publish_leg_payload(key, conflicting, store)

    assert first == second
    assert store.append_count == 1
    assert isinstance(conflict, UnpublishedLegResultOutcome)
    assert conflict.error_code == "result_conflict"


def test_published_handle_is_reread_and_all_digest_correlation_fields_are_checked(
    tmp_path: Path,
) -> None:
    request = _source_request(_source_route(tmp_path), dry_run=False)
    payload = _payload(request)
    store = InMemoryLegResultStore(writer_id="fixture-writer", now=lambda: NOW)
    key = derive_single_write_key(payload.correlation)
    handle = publish_leg_payload(key, payload, store)
    assert not isinstance(handle, UnpublishedLegResultOutcome)

    validated = validate_published_leg_result(
        handle,
        ExpectedPublishedLegResult(correlation=payload.correlation, mode=payload.mode),
        reader=store,
    )

    assert validated.payload == payload
    with pytest.raises(ValueError, match="receipt"):
        validate_published_leg_result(
            replace(handle, receipt=replace(handle.receipt, receipt_digest="f" * 64)),
            ExpectedPublishedLegResult(correlation=payload.correlation, mode=payload.mode),
            reader=store,
        )


class _FailingWriter:
    def __init__(self) -> None:
        self.calls = 0

    def append(self, single_write_key: str, payload: LegResultPayload):
        self.calls += 1
        raise OSError("fixture writer unavailable")


def test_writer_failure_has_no_handle_and_evidence_retry_does_not_need_git(
    tmp_path: Path,
) -> None:
    request = _source_request(_source_route(tmp_path), dry_run=False)
    payload = _payload(request)
    key = derive_single_write_key(payload.correlation)
    failing = _FailingWriter()

    unpublished = publish_leg_payload(key, payload, failing)

    assert isinstance(unpublished, UnpublishedLegResultOutcome)
    assert unpublished.payload == payload
    assert unpublished.recovery_route == "evidence-only-retry"
    store = InMemoryLegResultStore(writer_id="fixture-writer", now=lambda: NOW)
    recovered = retry_unpublished_payload(unpublished, store)
    assert not isinstance(recovered, UnpublishedLegResultOutcome)
    assert recovered.payload_digest == payload.payload_digest
    assert store.append_count == 1


class _RunnerSpy:
    def __init__(self, *, returncode: int = 0) -> None:
        self.calls: list[tuple[list[str], Path]] = []
        self.returncode = returncode

    def __call__(self, args: list[str], cwd: Path) -> GitCommandResult:
        self.calls.append((list(args), cwd))
        return GitCommandResult(
            argv=("git", *args),
            cwd=cwd,
            returncode=self.returncode,
            stdout="",
            stderr="" if self.returncode == 0 else "fixture failure",
        )


class _ObservationSequence:
    def __init__(self, *items) -> None:
        self.items = list(items)
        self.calls = 0

    def __call__(self, target):
        del target
        self.calls += 1
        if len(self.items) == 1:
            return self.items[0]
        return self.items.pop(0)


class _LiveObservationSequence:
    def __init__(self, *items, refresh: tuple[bool, ...] | None = None) -> None:
        self.items = list(items)
        self.refresh = list(refresh or (True,) * len(items))
        self.calls = 0

    def __call__(self, target):
        del target
        index = min(self.calls, len(self.items) - 1)
        self.calls += 1
        item = self.items[index]
        if not self.refresh[index]:
            return item
        # 保证端口返回的快照严格晚于 execute_leg 入口采样时刻。
        time.sleep(0.002)
        return _observation_at(item, datetime.now(UTC))


def test_default_clock_source_complete_accepts_fresh_observer_snapshots(
    tmp_path: Path,
) -> None:
    route = _source_route(tmp_path)
    reference = datetime.now(UTC)
    request = replace(_source_request(route, dry_run=False), operation="complete")
    authorization = _live_authorization(request, route, reference=reference)
    before = _observation_at(_source_observation(route), reference)
    after = _observation_at(before, reference, target_oid=OID_B)
    plan = build_leg_plan(request, route, before, authorization=authorization, now=reference)
    assert isinstance(plan, LegPlan)
    runner = _RunnerSpy()
    store = InMemoryLegResultStore(writer_id="fixture-writer", now=lambda: reference)

    result = execute_leg(
        plan,
        observer=_LiveObservationSequence(before, after),
        runner=runner,
        result_writer=store,
        now=None,
    )

    assert result.payload.status == "PASS"
    assert result.mutation_count == 1
    assert len(runner.calls) == 1


def test_default_clock_artifact_complete_accepts_fresh_observer_and_health(
    tmp_path: Path,
) -> None:
    route = _artifact_route(tmp_path)
    reference = datetime.now(UTC)
    health = _artifact_health(route, observed_at=reference)
    request = replace(
        _artifact_request(route, dry_run=False),
        worktree_health_digest=health.observation_digest or "",
    )
    authorization = _live_authorization(request, route, reference=reference)
    before = _observation_at(_artifact_observation(route), reference)
    after = _observation_at(before, reference, base_oid=OID_B, target_oid=OID_B)
    plan = build_leg_plan(
        request,
        route,
        before,
        authorization=authorization,
        worktree_health=health,
        now=reference,
    )
    assert isinstance(plan, LegPlan)
    runner = _RunnerSpy()
    store = InMemoryLegResultStore(writer_id="fixture-writer", now=lambda: reference)

    result = execute_leg(
        plan,
        observer=_LiveObservationSequence(before, after),
        health_observer=lambda target: health,
        runner=runner,
        result_writer=store,
        now=None,
    )

    assert result.payload.status == "PASS"
    assert result.mutation_count == 1
    assert len(runner.calls) == 1


def test_default_clock_ordinary_resume_accepts_new_attempt_fresh_snapshots(
    tmp_path: Path,
) -> None:
    route = _source_route(tmp_path)
    reference = datetime.now(UTC)
    original_request = replace(_source_request(route, dry_run=False), operation="complete")
    previous = _payload(
        original_request,
        status="FAIL",
        progress="PARTIAL",
        effect="REMOTE_PARTIAL",
        blockers=(LegBlocker("recovery_required", "fresh proof required"),),
    )
    request = replace(
        original_request,
        logical_attempt=2,
        operation="resume",
        authorization_ref="AUTH-052",
        resume_from_attempt=1,
        resume_operation="complete",
    )
    authorization = _live_authorization(request, route, reference=reference)
    before = _observation_at(_source_observation(route), reference)
    after = _observation_at(before, reference, base_oid=OID_B, target_oid=OID_B)
    runner = _RunnerSpy()
    store = InMemoryLegResultStore(writer_id="fixture-writer", now=lambda: reference)

    result = resume_leg(
        request,
        previous,
        route=route,
        observation=before,
        authorization=authorization,
        observer=_LiveObservationSequence(before, after),
        runner=runner,
        result_writer=store,
        now=None,
    )

    assert result.payload.status == "PASS"
    assert result.payload.correlation.logical_attempt == 2
    assert result.mutation_count == 1


def test_default_clock_post_observe_accepts_snapshot_created_after_runner(
    tmp_path: Path,
) -> None:
    route = _source_route(tmp_path)
    reference = datetime.now(UTC)
    request = replace(_source_request(route, dry_run=False), operation="complete")
    authorization = _live_authorization(request, route, reference=reference)
    before = _observation_at(_source_observation(route), reference)
    after = _observation_at(before, reference, target_oid=OID_B)
    plan = build_leg_plan(request, route, before, authorization=authorization, now=reference)
    assert isinstance(plan, LegPlan)
    runner = _RunnerSpy()
    store = InMemoryLegResultStore(writer_id="fixture-writer", now=lambda: reference)

    result = execute_leg(
        plan,
        observer=_LiveObservationSequence(before, after, refresh=(False, True)),
        runner=runner,
        result_writer=store,
        now=None,
    )

    assert result.payload.status == "PASS"
    assert result.mutation_count == 1
    assert len(runner.calls) == 1


@pytest.mark.parametrize(
    ("observed_at", "max_age_seconds"),
    (
        (lambda reference: reference - timedelta(minutes=5), 1),
        (lambda reference: reference + timedelta(minutes=1), 300),
    ),
    ids=("genuine-stale", "genuine-future-skew"),
)
def test_default_clock_rejects_genuine_stale_or_future_observation_before_runner(
    tmp_path: Path,
    observed_at,
    max_age_seconds: int,
) -> None:
    route = _source_route(tmp_path)
    reference = datetime.now(UTC)
    request = replace(_source_request(route, dry_run=False), operation="complete")
    authorization = _live_authorization(request, route, reference=reference)
    planned = _observation_at(_source_observation(route), reference)
    invalid = _observation_at(planned, observed_at(reference))
    plan = build_leg_plan(request, route, planned, authorization=authorization, now=reference)
    assert isinstance(plan, LegPlan)
    runner = _RunnerSpy()
    store = InMemoryLegResultStore(writer_id="fixture-writer", now=lambda: reference)

    result = execute_leg(
        plan,
        observer=_ObservationSequence(invalid),
        runner=runner,
        result_writer=store,
        now=None,
        max_observation_age_seconds=max_age_seconds,
    )

    assert result.payload.status == "BLOCKED"
    assert result.mutation_count == 0
    assert runner.calls == []


def test_dry_run_emits_exact_argv_but_calls_no_runner_or_writer(tmp_path: Path) -> None:
    route = _source_route(tmp_path)
    request = _source_request(route)
    observation = _source_observation(route)
    plan = build_leg_plan(request, route, observation, now=NOW)
    assert isinstance(plan, LegPlan)
    runner = _RunnerSpy()
    writer = _FailingWriter()

    result = execute_leg(
        plan,
        observer=_ObservationSequence(observation),
        runner=runner,
        result_writer=writer,
        now=NOW,
    )

    assert isinstance(result, LegExecutionOutcome)
    assert plan.steps[0].argv == (
        "git",
        "push",
        "origin",
        f"{OID_B}:refs/heads/cr/cr-051-artifact-worktree",
    )
    assert result.payload.status == "IN_PROGRESS"
    assert result.mutation_count == 0
    assert runner.calls == []
    assert writer.calls == 0


def test_complete_executes_one_leg_and_publishes_only_after_fresh_post_proof(
    tmp_path: Path,
) -> None:
    route = _source_route(tmp_path)
    request = replace(_source_request(route, dry_run=False), operation="complete")
    authorization = _authorization(request, route)
    before = _source_observation(route)
    after = replace(before, target_oid=OID_B, observed_at=NOW + timedelta(seconds=1))
    after = build_leg_observation(
        repository_fingerprint=after.repository_fingerprint,
        base_ref=after.base_ref,
        target_ref=after.target_ref,
        active_ref=after.active_ref,
        base_oid=after.base_oid,
        target_oid=after.target_oid,
        active_oid=after.active_oid,
        head_oid=after.head_oid,
        observed_at=after.observed_at,
        dirty=False,
        staged=False,
        untracked=False,
        git_operation="NONE",
    )
    plan = build_leg_plan(request, route, before, authorization=authorization, now=NOW)
    assert isinstance(plan, LegPlan)
    runner = _RunnerSpy()
    store = InMemoryLegResultStore(writer_id="fixture-writer", now=lambda: NOW)

    result = execute_leg(
        plan,
        observer=_ObservationSequence(before, after),
        runner=runner,
        result_writer=store,
        now=NOW + timedelta(seconds=1),
    )

    assert result.payload.status == "PASS"
    assert result.published_handle is not None
    assert result.mutation_count == 1
    assert runner.calls == [
        (["push", "origin", f"{OID_B}:refs/heads/main"], route.repository_root.resolve())
    ]


def test_pre_execute_drift_blocks_before_runner(tmp_path: Path) -> None:
    route = _source_route(tmp_path)
    request = replace(_source_request(route, dry_run=False), operation="complete")
    authorization = _authorization(request, route)
    before = _source_observation(route)
    drifted = build_leg_observation(
        repository_fingerprint=before.repository_fingerprint,
        base_ref=before.base_ref,
        target_ref=before.target_ref,
        active_ref=before.active_ref,
        base_oid=before.base_oid,
        target_oid=OID_C,
        active_oid=before.active_oid,
        head_oid=before.head_oid,
        observed_at=NOW + timedelta(seconds=1),
        dirty=False,
        staged=False,
        untracked=False,
        git_operation="NONE",
    )
    plan = build_leg_plan(request, route, before, authorization=authorization, now=NOW)
    assert isinstance(plan, LegPlan)
    runner = _RunnerSpy()
    store = InMemoryLegResultStore(writer_id="fixture-writer", now=lambda: NOW)

    result = execute_leg(
        plan,
        observer=_ObservationSequence(drifted),
        runner=runner,
        result_writer=store,
        now=NOW + timedelta(seconds=1),
    )

    assert result.payload.status == "BLOCKED"
    assert result.payload.blockers[0].code == "stale_observation"
    assert result.mutation_count == 0
    assert runner.calls == []


def test_post_proof_failure_preserves_partial_effect_and_never_rolls_back_other_leg(
    tmp_path: Path,
) -> None:
    route = _source_route(tmp_path)
    request = replace(_source_request(route, dry_run=False), operation="complete")
    authorization = _authorization(request, route)
    before = _source_observation(route)
    unknown_after = build_leg_observation(
        repository_fingerprint=before.repository_fingerprint,
        base_ref=before.base_ref,
        target_ref=before.target_ref,
        active_ref=before.active_ref,
        base_oid=before.base_oid,
        target_oid=OID_C,
        active_oid=before.active_oid,
        head_oid=before.head_oid,
        observed_at=NOW + timedelta(seconds=1),
        dirty=False,
        staged=False,
        untracked=False,
        git_operation="NONE",
    )
    plan = build_leg_plan(request, route, before, authorization=authorization, now=NOW)
    assert isinstance(plan, LegPlan)
    runner = _RunnerSpy()
    store = InMemoryLegResultStore(writer_id="fixture-writer", now=lambda: NOW)

    result = execute_leg(
        plan,
        observer=_ObservationSequence(before, unknown_after),
        runner=runner,
        result_writer=store,
        now=NOW,
    )

    assert result.payload.status == "FAIL"
    assert result.payload.progress == "PARTIAL"
    assert result.payload.effect == "UNKNOWN"
    flattened = [token for args, _ in runner.calls for token in args]
    assert {"reset", "clean", "stash", "rebase", "--force", "--force-with-lease"}.isdisjoint(
        flattened
    )
    assert all("projects/" not in token for token in flattened)


def test_abort_is_coordination_only_and_preserves_previous_effect(tmp_path: Path) -> None:
    route = _source_route(tmp_path)
    previous_request = replace(_source_request(route, dry_run=False), operation="complete")
    previous = _payload(
        previous_request,
        status="FAIL",
        progress="PARTIAL",
        effect="REMOTE_PARTIAL",
        blockers=(LegBlocker("recovery_required", "post proof uncertain"),),
    )
    abort_request = replace(
        previous_request,
        logical_attempt=2,
        operation="abort",
        authorization_ref="",
        resume_from_attempt=1,
    )
    store = InMemoryLegResultStore(writer_id="fixture-writer", now=lambda: NOW)

    result = abort_leg(abort_request, previous, result_writer=store, now=NOW)

    assert result.mutation_count == 0
    assert result.payload.status == "FAIL"
    assert result.payload.effect == "REMOTE_PARTIAL"
    assert result.payload.abort_route == "aborted-coordination-only"


def test_payload_reader_rejects_append_time_fields(tmp_path: Path) -> None:
    payload = _payload(_source_request(_source_route(tmp_path), dry_run=False))
    raw = payload_to_dict(payload)
    raw["result_ref"] = "memory://forbidden"

    with pytest.raises(ValueError, match="append-time"):
        payload_from_dict(raw)


def test_payload_reader_round_trips_canonical_schema(tmp_path: Path) -> None:
    payload = _payload(_source_request(_source_route(tmp_path), dry_run=False))

    assert payload_from_dict(payload_to_dict(payload)) == payload


def test_published_validator_rejects_handle_key_ref_digest_and_correlation_tamper(
    tmp_path: Path,
) -> None:
    payload = _payload(_source_request(_source_route(tmp_path), dry_run=False))
    store = InMemoryLegResultStore(writer_id="fixture-writer", now=lambda: NOW)
    handle = publish_leg_payload(derive_single_write_key(payload.correlation), payload, store)
    assert not isinstance(handle, UnpublishedLegResultOutcome)
    expected = ExpectedPublishedLegResult(correlation=payload.correlation, mode=payload.mode)
    tampered = (
        replace(handle, single_write_key="f" * 64),
        replace(handle, result_ref="memory://wrong"),
        replace(handle, payload_digest="f" * 64),
        replace(
            handle,
            correlation=replace(payload.correlation, logical_attempt=2),
        ),
        replace(handle, mode="shared-artifact-project-first"),
    )

    for candidate in tampered:
        with pytest.raises(ValueError):
            validate_published_leg_result(candidate, expected, reader=store)


def test_single_write_same_digest_is_thread_safe(tmp_path: Path) -> None:
    payload = _payload(_source_request(_source_route(tmp_path), dry_run=False))
    key = derive_single_write_key(payload.correlation)
    store = InMemoryLegResultStore(writer_id="fixture-writer", now=lambda: NOW)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: publish_leg_payload(key, payload, store), range(8)))

    assert len(set(results)) == 1
    assert store.append_count == 1


def test_artifact_execute_revalidates_health_before_mutation(tmp_path: Path) -> None:
    route = _artifact_route(tmp_path)
    healthy = _artifact_health(route)
    request = replace(
        _artifact_request(route, dry_run=False),
        worktree_health_digest=healthy.observation_digest or "",
    )
    authorization = _authorization(request, route)
    before = _artifact_observation(route)
    plan = build_leg_plan(
        request,
        route,
        before,
        authorization=authorization,
        worktree_health=healthy,
        now=NOW,
    )
    assert isinstance(plan, LegPlan)
    runner = _RunnerSpy()
    store = InMemoryLegResultStore(writer_id="fixture-writer", now=lambda: NOW)

    result = execute_leg(
        plan,
        observer=_ObservationSequence(before),
        health_observer=lambda target: _artifact_health(route, dirty=True),
        runner=runner,
        result_writer=store,
        now=NOW,
    )

    assert result.payload.status == "BLOCKED"
    assert result.payload.blockers[0].code == "worktree_health_not_healthy"
    assert runner.calls == []
    assert result.mutation_count == 0


def test_artifact_complete_updates_only_project_integration_with_command_spy(
    tmp_path: Path,
) -> None:
    route = _artifact_route(tmp_path)
    healthy = _artifact_health(route)
    request = replace(
        _artifact_request(route, dry_run=False),
        worktree_health_digest=healthy.observation_digest or "",
    )
    authorization = _authorization(request, route)
    before = _artifact_observation(route)
    after = build_leg_observation(
        repository_fingerprint=before.repository_fingerprint,
        base_ref=before.base_ref,
        target_ref=before.target_ref,
        active_ref=before.active_ref,
        base_oid=OID_B,
        target_oid=OID_B,
        active_oid=before.active_oid,
        head_oid=before.head_oid,
        observed_at=NOW + timedelta(seconds=1),
        dirty=False,
        staged=False,
        untracked=False,
        git_operation="NONE",
    )
    plan = build_leg_plan(
        request,
        route,
        before,
        authorization=authorization,
        worktree_health=healthy,
        now=NOW,
    )
    assert isinstance(plan, LegPlan)
    runner = _RunnerSpy()
    store = InMemoryLegResultStore(writer_id="fixture-writer", now=lambda: NOW)

    result = execute_leg(
        plan,
        observer=_ObservationSequence(before, after),
        health_observer=lambda target: healthy,
        runner=runner,
        result_writer=store,
        now=NOW + timedelta(seconds=1),
    )

    integration_ref = "refs/heads/projects/meta-flow/integration"
    assert result.payload.status == "PASS"
    assert runner.calls == [
        (["push", "origin", f"{OID_B}:{integration_ref}"], route.repository_root.resolve())
    ]
    flattened = [token for args, _ in runner.calls for token in args]
    assert "refs/heads/main" not in flattened
    assert all("projects/other" not in token for token in flattened)


@pytest.mark.parametrize("operation", ["open", "publish", "complete", "finish", "abort"])
def test_all_artifact_operations_are_project_scoped_and_dry_run_only(
    tmp_path: Path, operation: str
) -> None:
    route = _artifact_route(tmp_path)
    health = _artifact_health(
        route,
        integration_oid=OID_B if operation == "finish" else OID_A,
    )
    request = replace(
        _artifact_request(route),
        operation=operation,
        expected_target_oid=OID_B if operation == "finish" else OID_A,
        worktree_health_digest=health.observation_digest or "",
    )

    observation = (
        _artifact_observation(route, target_oid=OID_B)
        if operation == "finish"
        else _artifact_observation(route)
    )
    plan = build_leg_plan(
        request,
        route,
        observation,
        worktree_health=health,
        now=NOW,
    )

    assert isinstance(plan, LegPlan)
    assert plan.dry_run is True
    for step in plan.steps:
        joined = " ".join(step.argv)
        assert "refs/heads/projects/meta-flow/" in joined
        assert "refs/heads/main" not in joined
        if operation == "finish":
            assert f"--force-with-lease={observation.active_ref}:{OID_B}" in step.argv
            assert step.argv[-1] == f":{observation.active_ref}"
        else:
            assert "--force" not in joined
    assert plan.steps == () if operation == "abort" else len(plan.steps) == 1


def test_tp_03_004_cr050_paired_default_projection_remains_compatible() -> None:
    outcomes = [
        RepoOutcome("project", "PASS", expected_oid=OID_B, after_oid=OID_B),
        RepoOutcome("artifact", "PASS", expected_oid=OID_C, after_oid=OID_C),
    ]

    projection = project_merge("fixture://cr050/attempt", outcomes, required=2)

    assert projection.paired_complete is True
    assert projection.finish_allowed is True
    assert projection.cr_close_allowed is True


def test_tp_03_006_source_pass_is_preserved_when_artifact_leg_aborts(tmp_path: Path) -> None:
    source_route = _source_route(tmp_path)
    artifact_route = _artifact_route(tmp_path)
    source_payload = _payload(_source_request(source_route, dry_run=False), status="PASS")
    artifact_request = replace(
        _artifact_request(artifact_route, dry_run=False), operation="complete"
    )
    artifact_failed = seal_leg_result_payload(
        replace(
            _payload(
                artifact_request,
                status="FAIL",
                progress="PARTIAL",
                effect="REMOTE_PARTIAL",
                blockers=(LegBlocker("artifact_failed", "fixture failure"),),
            ),
            active_ref=canonical_artifact_active_ref("meta-flow", "CR-051", "artifact-worktree"),
            payload_digest="",
        )
    )
    abort_request = replace(
        artifact_request,
        logical_attempt=2,
        operation="abort",
        authorization_ref="",
        resume_from_attempt=1,
    )
    store = InMemoryLegResultStore(writer_id="fixture-writer", now=lambda: NOW)

    aborted = abort_leg(abort_request, artifact_failed, result_writer=store, now=NOW)

    assert source_payload.status == "PASS"
    assert source_payload.effect == "TARGET_UPDATED"
    assert aborted.payload.status == "FAIL"
    assert aborted.payload.effect == "REMOTE_PARTIAL"
    assert aborted.payload.abort_route == "aborted-coordination-only"
    assert store.append_count == 1


def test_tp_03_008_sibling_dirty_path_does_not_block_or_enter_argv(tmp_path: Path) -> None:
    route = _artifact_route(tmp_path)
    sibling = tmp_path / "projects" / "sibling-project"
    sibling.mkdir(parents=True)
    (sibling / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    health = _artifact_health(route)
    request = replace(
        _artifact_request(route),
        worktree_health_digest=health.observation_digest or "",
    )

    plan = build_leg_plan(
        request,
        route,
        _artifact_observation(route),
        worktree_health=health,
        now=NOW,
    )

    assert isinstance(plan, LegPlan)
    assert len(plan.steps) == 1
    assert all(sibling.as_posix() not in token for token in plan.steps[0].argv)
    assert plan.steps[0].cwd_role == "current-leg-worktree"


def test_tp_03_014_finish_requires_containment_and_uses_exact_cas_cleanup(
    tmp_path: Path,
) -> None:
    route = _artifact_route(tmp_path)
    health_before_complete = _artifact_health(route, integration_oid=OID_A)
    healthy_after_complete = _artifact_health(route, integration_oid=OID_B)
    request = replace(
        _artifact_request(route),
        operation="finish",
        expected_target_oid=OID_B,
        worktree_health_digest=healthy_after_complete.observation_digest or "",
    )

    blocked = build_leg_plan(
        replace(
            request,
            expected_target_oid=OID_A,
            worktree_health_digest=health_before_complete.observation_digest or "",
        ),
        route,
        _artifact_observation(route, target_oid=OID_A, active_oid=OID_B),
        worktree_health=health_before_complete,
        now=NOW,
    )
    plan = build_leg_plan(
        request,
        route,
        _artifact_observation(route, target_oid=OID_B, active_oid=OID_B),
        worktree_health=healthy_after_complete,
        now=NOW,
    )

    assert isinstance(blocked, LegPreparationOutcome)
    assert blocked.code == "cleanup_containment_unproven"
    assert isinstance(plan, LegPlan)
    active_ref = canonical_artifact_active_ref("meta-flow", "CR-051", "artifact-worktree")
    assert plan.target.target_ref == canonical_artifact_integration_ref("meta-flow")
    assert plan.steps[0].argv == (
        "git",
        "push",
        f"--force-with-lease={active_ref}:{OID_B}",
        "origin",
        f":{active_ref}",
    )
    assert "refs/heads/main" not in " ".join(plan.steps[0].argv)


def test_ordinary_resume_uses_new_attempt_and_fresh_replan(tmp_path: Path) -> None:
    route = _source_route(tmp_path)
    original_request = replace(_source_request(route, dry_run=False), operation="complete")
    previous = _payload(
        original_request,
        status="FAIL",
        progress="PARTIAL",
        effect="REMOTE_PARTIAL",
        blockers=(LegBlocker("recovery_required", "fresh proof required"),),
    )
    request = replace(
        original_request,
        logical_attempt=2,
        operation="resume",
        authorization_ref="AUTH-052",
        resume_from_attempt=1,
        resume_operation="complete",
    )
    authorization = _authorization(request, route)
    before = _source_observation(route)
    after = build_leg_observation(
        repository_fingerprint=before.repository_fingerprint,
        base_ref=before.base_ref,
        target_ref=before.target_ref,
        active_ref=before.active_ref,
        base_oid=OID_B,
        target_oid=OID_B,
        active_oid=before.active_oid,
        head_oid=before.head_oid,
        observed_at=NOW + timedelta(seconds=1),
        dirty=False,
        staged=False,
        untracked=False,
        git_operation="NONE",
    )
    runner = _RunnerSpy()
    store = InMemoryLegResultStore(writer_id="fixture-writer", now=lambda: NOW)

    result = resume_leg(
        request,
        previous,
        route=route,
        observation=before,
        authorization=authorization,
        observer=_ObservationSequence(before, after),
        runner=runner,
        result_writer=store,
        now=NOW + timedelta(seconds=1),
    )

    assert result.payload.status == "PASS"
    assert result.payload.correlation.logical_attempt == 2
    assert result.payload.operation == "resume"
    assert result.mutation_count == 1


def _run_fixture_git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    )
    return completed.stdout.strip()


def test_complete_against_temporary_bare_remote_updates_only_source_target(
    tmp_path: Path,
) -> None:
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    remote.mkdir()
    work.mkdir()
    _run_fixture_git(remote, "init", "--bare")
    _run_fixture_git(work, "init")
    _run_fixture_git(work, "config", "user.name", "Meta Flow Fixture")
    _run_fixture_git(work, "config", "user.email", "fixture@example.invalid")
    (work / "payload.txt").write_text("base\n", encoding="utf-8")
    _run_fixture_git(work, "add", "payload.txt")
    _run_fixture_git(work, "commit", "-m", "base")
    base_oid = _run_fixture_git(work, "rev-parse", "HEAD")
    _run_fixture_git(work, "remote", "add", "origin", remote.as_posix())
    _run_fixture_git(work, "push", "origin", f"{base_oid}:refs/heads/main")
    (work / "payload.txt").write_text("next\n", encoding="utf-8")
    _run_fixture_git(work, "commit", "-am", "next")
    next_oid = _run_fixture_git(work, "rev-parse", "HEAD")
    active_ref = canonical_source_active_ref("CR-051", "artifact-worktree")
    _run_fixture_git(work, "push", "origin", f"{next_oid}:{active_ref}")
    route = LegRouteProof(
        project_id="meta-flow",
        mode="source-default",
        repository_root=work,
        repository_fingerprint="fixture-repository",
        remote="origin",
        route_config_digest="1" * 64,
        source_default_ref="refs/heads/main",
        owned_target=True,
    )
    request = replace(
        _source_request(route, dry_run=False),
        operation="complete",
        expected_base_oid=base_oid,
        expected_target_oid=base_oid,
    )
    authorization = _authorization(request, route)

    def observe(target):
        del target
        rows = _run_fixture_git(
            work,
            "ls-remote",
            "--refs",
            "origin",
            "refs/heads/main",
            active_ref,
        ).splitlines()
        by_ref = {row.split()[1]: row.split()[0] for row in rows}
        return build_leg_observation(
            repository_fingerprint=route.repository_fingerprint,
            base_ref="refs/heads/main",
            target_ref="refs/heads/main",
            active_ref=active_ref,
            base_oid=by_ref["refs/heads/main"],
            target_oid=by_ref["refs/heads/main"],
            active_oid=by_ref[active_ref],
            head_oid=next_oid,
            observed_at=NOW,
            dirty=False,
            staged=False,
            untracked=False,
            git_operation="NONE",
        )

    before = observe(None)
    plan = build_leg_plan(request, route, before, authorization=authorization, now=NOW)
    assert isinstance(plan, LegPlan)
    store = InMemoryLegResultStore(writer_id="fixture-writer", now=lambda: NOW)

    result = execute_leg(plan, observer=observe, result_writer=store, now=NOW)

    assert result.payload.status == "PASS"
    assert (
        _run_fixture_git(work, "ls-remote", "--refs", "origin", "refs/heads/main").split()[0]
        == next_oid
    )
    assert all("projects/" not in token for step in plan.steps for token in step.argv)
