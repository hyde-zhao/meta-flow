"""Project-first sibling worktree 的 typed lifecycle 契约。

公共读取端口固定为 ``WorktreeObservation``，健康裁决只通过
``WorktreeHealth.observation`` 包裹原 snapshot；本模块不暴露第二套平铺字段。
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from meta_flow.workspace.git_sync import (
    CreateOnlyRefResult,
    GitRunner,
    create_remote_ref_once,
    probe_common_git_dir,
    probe_head_oid,
    probe_status_porcelain,
    probe_symbolic_head,
    probe_worktree_porcelain,
    run_git,
)
from meta_flow.workspace.project_artifact_routing import RouteDecision
from meta_flow.workspace.worktree_capacity import (
    CalibrationEvidence,
    CapacityDecision,
    CapacityProof,
    build_capacity_proof,
    validate_capacity_proof,
)
from meta_flow.workspace.worktree_journal import (
    DurableIntent,
    JournalError,
    WorktreeJournal,
)

_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SAFE_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_ROOT_BRANCH_ONLY = "root-branch-only"


class WorktreePolicyProtocol(Protocol):
    worktree_policy: str


class OperationState(StrEnum):
    PLANNED = "PLANNED"
    PRECHECKED = "PRECHECKED"
    CAPACITY_PROVED = "CAPACITY_PROVED"
    INTENT_PREPARED = "INTENT_PREPARED"
    INTENT_DURABLE = "INTENT_DURABLE"
    OBSERVATION_REQUIRED = "OBSERVATION_REQUIRED"
    VERIFIED = "VERIFIED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


@dataclass(frozen=True)
class UnknownValue:
    reason_code: str
    evidence_ref: str | None


@dataclass(frozen=True)
class WorktreeIdentity:
    project_id: str
    repository_id: str
    repository_fingerprint: str
    worktree_id: str
    repo_common_dir: Path
    common_dir_digest: str
    target_path: Path
    target_path_digest: str
    expected_gitdir: Path | None
    integration_ref: str


@dataclass(frozen=True)
class WorktreeObservation:
    schema_version: str
    identity: WorktreeIdentity
    observed_at: datetime
    route_config_digest: str
    worktree_state: str
    head_ref: str | None | UnknownValue
    head_oid: str | None | UnknownValue
    integration_oid: str | None | UnknownValue
    dirty: bool | UnknownValue
    staged: bool | UnknownValue
    untracked: bool | UnknownValue
    git_operation: str | UnknownValue
    registry_state: str | UnknownValue
    role: str | UnknownValue
    observation_digest: str


@dataclass(frozen=True)
class WorktreeHealth:
    project_id: str
    decision: str
    observation: WorktreeObservation | None
    observation_digest: str | None
    worktree_state: str
    journal_state: str
    active_operation_id: str | None
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class PreparedSwitchTarget:
    before: WorktreeObservation
    target_ref: str
    target_oid: str


@dataclass(frozen=True)
class ProjectWorktreeRegistration:
    schema_version: str
    identity: WorktreeIdentity
    route_config_digest: str
    branch_role: str
    expected_head_oid: str
    registered_at: datetime


@dataclass(frozen=True)
class WorktreeOperationPlan:
    operation_id: str
    attempt_id: str
    operation: str
    route_digest: str
    before_observation_digest: str
    target_ref: str | None
    target_oid: str | None
    original_ref: str | None
    original_oid: str | None
    checkout_capacity_ref: str
    journal_capacity_ref: str
    created_at: datetime


@dataclass(frozen=True)
class WorktreeOperationResult:
    operation_id: str
    attempt_id: str
    decision: str
    reason: str
    observed_state: str
    before_observation_ref: str
    after_observation_ref: str | None
    capacity_proof_ref: str
    journal_head_ref: str
    mutation_count: int
    operation_state: str = ""


@dataclass(frozen=True)
class OperationAuthorization:
    authorization_id: str
    operation: str
    project_id: str
    expected_route_digest: str
    expected_ref: str | None | UnknownValue
    expected_oid: str | None | UnknownValue

    def matches(self, observation: WorktreeObservation) -> bool:
        return bool(
            self.authorization_id
            and self.operation in {"SWITCH", "ROLLBACK", "CREATE"}
            and self.project_id == observation.identity.project_id
            and self.expected_route_digest == observation.route_config_digest
            and isinstance(self.expected_ref, str)
            and isinstance(self.expected_oid, str)
            and self.expected_ref == observation.head_ref
            and self.expected_oid == observation.head_oid
            and observation.dirty is False
            and observation.staged is False
            and observation.untracked is False
            and observation.git_operation == "NONE"
        )


@dataclass(frozen=True)
class RemovalAuthorization:
    authorization_id: str
    expected_project_id: str
    expected_target_digest: str
    expected_role: str
    authorized: bool


def _safe_project(project_id: str) -> str:
    if not _SAFE_TOKEN.fullmatch(project_id) or project_id.startswith("-"):
        raise ValueError("project_id must be a safe non-option token")
    return project_id.lower()


def canonical_integration_ref(project_id: str) -> str:
    return f"refs/heads/projects/{_safe_project(project_id)}/integration"


def canonical_active_ref(project_id: str, cr_id: str, slug: str) -> str:
    project = _safe_project(project_id)
    normalized_cr = cr_id.lower()
    normalized_slug = slug.lower()
    if not _SAFE_TOKEN.fullmatch(cr_id) or not _SAFE_SLUG.fullmatch(normalized_slug):
        raise ValueError("cr_id and slug must be safe branch components")
    return f"refs/heads/projects/{project}/cr/{normalized_cr}-{normalized_slug}"


def _default_git(args: list[str], cwd: Path):
    return run_git(args, cwd=cwd)


def _unknown(reason: str) -> UnknownValue:
    return UnknownValue(reason, None)


def _route_owns_identity(route: RouteDecision, identity: WorktreeIdentity) -> bool:
    target = route.write_target
    if route.decision != "PASS" or target is None or route.project_id != identity.project_id:
        return False
    try:
        target.runtime_path.resolve(strict=False).relative_to(
            identity.target_path.resolve(strict=False)
        )
    except ValueError:
        return False
    return True


def observe_worktree(
    route: RouteDecision,
    *,
    identity: WorktreeIdentity,
    git: GitRunner = _default_git,
    observed_at: datetime | None = None,
) -> WorktreeObservation:
    """生成 fresh rich snapshot；单个 probe 失败显式保留 typed unknown。"""

    observed_at = observed_at or datetime.now(UTC)
    if not _route_owns_identity(route, identity):
        raise ValueError("route_unproven: route does not own the supplied project worktree")
    target = identity.target_path
    if not target.exists():
        return build_worktree_observation(
            identity=identity,
            observed_at=observed_at,
            route_config_digest=route.config_digest,
            worktree_state="ABSENT",
            head_ref=None,
            head_oid=None,
            integration_oid=None,
            dirty=False,
            staged=False,
            untracked=False,
            git_operation="NONE",
            registry_state="MISSING",
            role=_unknown("worktree_absent"),
        )
    common = probe_common_git_dir(target, runner=git)
    head = probe_symbolic_head(target, runner=git)
    oid = probe_head_oid(target, runner=git)
    status = probe_status_porcelain(target, runner=git)
    registry = probe_worktree_porcelain(target, runner=git)
    integration_result = git(
        ["rev-parse", "--verify", f"{identity.integration_ref}^{{commit}}"], target
    )

    head_ref: str | UnknownValue = (
        head.value if head.decision == "KNOWN" else _unknown("head_ref_unknown")
    )
    head_oid: str | UnknownValue = (
        oid.value if oid.decision == "KNOWN" else _unknown("head_oid_unknown")
    )
    integration_oid: str | UnknownValue = (
        integration_result.stdout.strip()
        if integration_result.ok
        else _unknown("integration_oid_unknown")
    )
    if status.decision == "KNOWN":
        rows = [line for line in status.value.splitlines() if line]
        untracked: bool | UnknownValue = any(line.startswith("??") for line in rows)
        staged: bool | UnknownValue = any(
            len(line) >= 2 and line[0] not in {" ", "?"} for line in rows
        )
        dirty: bool | UnknownValue = bool(rows)
    else:
        dirty = staged = untracked = _unknown("status_unknown")

    if isinstance(head_ref, UnknownValue):
        role: str | UnknownValue = _unknown("role_unknown")
        worktree_state = "UNKNOWN"
    elif head_ref == identity.integration_ref:
        role = "IDLE_INTEGRATION"
        worktree_state = "ORIGINAL"
    elif head_ref.startswith(f"refs/heads/projects/{_safe_project(identity.project_id)}/cr/"):
        role = "ACTIVE_CR"
        worktree_state = "TARGET"
    else:
        role = _unknown("main_or_foreign_branch")
        worktree_state = "THIRD"

    if common.decision != "KNOWN":
        registry_state: str | UnknownValue = _unknown("common_dir_unknown")
    else:
        common_path = Path(common.value)
        if not common_path.is_absolute():
            common_path = (target / common_path).resolve(strict=False)
        expected_common = identity.repo_common_dir.resolve(strict=False)
        registry_has_target = (
            registry.decision == "KNOWN"
            and f"worktree {target.resolve(strict=False).as_posix()}" in registry.value
        )
        registry_state = (
            "CONSISTENT" if common_path == expected_common and registry_has_target else "CONFLICT"
        )

    git_operation: str | UnknownValue = "NONE"
    for operation, marker in (
        ("MERGE", "MERGE_HEAD"),
        ("REBASE", "rebase-merge"),
        ("REBASE", "rebase-apply"),
        ("CHERRY_PICK", "CHERRY_PICK_HEAD"),
        ("REVERT", "REVERT_HEAD"),
        ("BISECT", "BISECT_LOG"),
        ("SEQUENCER", "sequencer"),
    ):
        marker_result = git(["rev-parse", "--git-path", marker], target)
        if not marker_result.ok:
            git_operation = _unknown("git_operation_unknown")
            break
        marker_path = Path(marker_result.stdout.strip())
        if not marker_path.is_absolute():
            marker_path = target / marker_path
        if marker_path.exists():
            git_operation = operation
            break
    return build_worktree_observation(
        identity=identity,
        observed_at=observed_at,
        route_config_digest=route.config_digest,
        worktree_state=worktree_state,
        head_ref=head_ref,
        head_oid=head_oid,
        integration_oid=integration_oid,
        dirty=dirty,
        staged=staged,
        untracked=untracked,
        git_operation=git_operation,
        registry_state=registry_state,
        role=role,
    )


def _canonical_value(value: object) -> object:
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat(timespec="microseconds")
    if is_dataclass(value):
        return {key: _canonical_value(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _canonical_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_canonical_value(item) for item in value]
    return value


def _observation_payload(
    *,
    identity: WorktreeIdentity,
    observed_at: datetime,
    route_config_digest: str,
    worktree_state: str,
    head_ref: str | None | UnknownValue,
    head_oid: str | None | UnknownValue,
    integration_oid: str | None | UnknownValue,
    dirty: bool | UnknownValue,
    staged: bool | UnknownValue,
    untracked: bool | UnknownValue,
    git_operation: str | UnknownValue,
    registry_state: str | UnknownValue,
    role: str | UnknownValue,
) -> dict[str, object]:
    return {
        "schema_version": "1",
        "identity": _canonical_value(identity),
        "observed_at": _canonical_value(observed_at),
        "route_config_digest": route_config_digest,
        "worktree_state": worktree_state,
        "head_ref": _canonical_value(head_ref),
        "head_oid": _canonical_value(head_oid),
        "integration_oid": _canonical_value(integration_oid),
        "dirty": _canonical_value(dirty),
        "staged": _canonical_value(staged),
        "untracked": _canonical_value(untracked),
        "git_operation": _canonical_value(git_operation),
        "registry_state": _canonical_value(registry_state),
        "role": _canonical_value(role),
    }


def build_worktree_observation(
    *,
    identity: WorktreeIdentity,
    observed_at: datetime,
    route_config_digest: str,
    worktree_state: str,
    head_ref: str | None | UnknownValue,
    head_oid: str | None | UnknownValue,
    integration_oid: str | None | UnknownValue,
    dirty: bool | UnknownValue,
    staged: bool | UnknownValue,
    untracked: bool | UnknownValue,
    git_operation: str | UnknownValue,
    registry_state: str | UnknownValue,
    role: str | UnknownValue,
) -> WorktreeObservation:
    payload = _observation_payload(
        identity=identity,
        observed_at=observed_at,
        route_config_digest=route_config_digest,
        worktree_state=worktree_state,
        head_ref=head_ref,
        head_oid=head_oid,
        integration_oid=integration_oid,
        dirty=dirty,
        staged=staged,
        untracked=untracked,
        git_operation=git_operation,
        registry_state=registry_state,
        role=role,
    )
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return WorktreeObservation(
        schema_version="1",
        identity=identity,
        observed_at=observed_at,
        route_config_digest=route_config_digest,
        worktree_state=worktree_state,
        head_ref=head_ref,
        head_oid=head_oid,
        integration_oid=integration_oid,
        dirty=dirty,
        staged=staged,
        untracked=untracked,
        git_operation=git_operation,
        registry_state=registry_state,
        role=role,
        observation_digest=digest,
    )


def _digest_is_valid(observation: WorktreeObservation) -> bool:
    rebuilt = build_worktree_observation(
        identity=observation.identity,
        observed_at=observation.observed_at,
        route_config_digest=observation.route_config_digest,
        worktree_state=observation.worktree_state,
        head_ref=observation.head_ref,
        head_oid=observation.head_oid,
        integration_oid=observation.integration_oid,
        dirty=observation.dirty,
        staged=observation.staged,
        untracked=observation.untracked,
        git_operation=observation.git_operation,
        registry_state=observation.registry_state,
        role=observation.role,
    )
    return rebuilt.observation_digest == observation.observation_digest


def evaluate_worktree_health(
    observation: WorktreeObservation | None,
    journal_state: str,
    active_operation_id: str | None,
    *,
    project_id: str,
    expected_route_config_digest: str,
    evaluated_at: datetime,
    max_observation_age_seconds: int,
) -> WorktreeHealth:
    """纯函数裁决；非 HEALTHY 永不形成 mutation 授权。"""

    if observation is None:
        return WorktreeHealth(
            project_id=project_id,
            decision="BLOCKED",
            observation=None,
            observation_digest=None,
            worktree_state="UNKNOWN",
            journal_state=journal_state,
            active_operation_id=active_operation_id,
            reason_codes=("observation_missing",),
        )
    reasons: list[str] = []
    if project_id != observation.identity.project_id:
        reasons.append("project_mismatch")
    if expected_route_config_digest != observation.route_config_digest:
        reasons.append("route_digest_mismatch")
    if not _digest_is_valid(observation):
        reasons.append("observation_digest_mismatch")
    age = (evaluated_at - observation.observed_at).total_seconds()
    if age < 0 or age > max_observation_age_seconds:
        reasons.append("observation_stale")
    probe_values = (
        observation.head_ref,
        observation.head_oid,
        observation.integration_oid,
        observation.dirty,
        observation.staged,
        observation.untracked,
        observation.git_operation,
        observation.registry_state,
        observation.role,
    )
    if any(isinstance(value, UnknownValue) for value in probe_values):
        reasons.append("observation_incomplete")
    if (
        observation.dirty is not False
        or observation.staged is not False
        or observation.untracked is not False
    ):
        reasons.append("dirty_state")
    if observation.git_operation != "NONE":
        reasons.append("git_operation_active")
    if observation.registry_state != "CONSISTENT":
        reasons.append("registry_inconsistent")
    if observation.role not in {"IDLE_INTEGRATION", "ACTIVE_CR"}:
        reasons.append("role_invalid")
    if journal_state not in {"IDLE", "VERIFIED_TARGET", "VERIFIED_ORIGINAL"}:
        reasons.append("journal_not_terminal")
    if active_operation_id is not None:
        reasons.append("active_operation")
    reasons = list(dict.fromkeys(reasons))
    recovery = bool(
        journal_state == "RECOVERY_REQUIRED"
        or active_operation_id is not None
        or observation.role == "RECOVERY_REQUIRED"
    )
    decision = "HEALTHY" if not reasons else ("RECOVERY_REQUIRED" if recovery else "BLOCKED")
    return WorktreeHealth(
        project_id=project_id,
        decision=decision,
        observation=observation,
        observation_digest=observation.observation_digest,
        worktree_state=observation.worktree_state,
        journal_state=journal_state,
        active_operation_id=active_operation_id,
        reason_codes=tuple(reasons),
    )


def register_project_worktree(observation: WorktreeObservation) -> ProjectWorktreeRegistration:
    """把 fresh、可确定的项目身份冻结为 registration value object。"""

    if (
        isinstance(observation.role, UnknownValue)
        or not isinstance(observation.head_oid, str)
        or observation.registry_state != "CONSISTENT"
        or not _digest_is_valid(observation)
    ):
        raise ValueError("registration_unproven: observation is not registration-safe")
    return ProjectWorktreeRegistration(
        schema_version="1",
        identity=observation.identity,
        route_config_digest=observation.route_config_digest,
        branch_role=observation.role,
        expected_head_oid=observation.head_oid,
        registered_at=observation.observed_at,
    )


def check_project_worktree(
    registration: ProjectWorktreeRegistration,
    observation: WorktreeObservation | None,
    *,
    journal_state: str,
    active_operation_id: str | None,
    evaluated_at: datetime,
    max_observation_age_seconds: int = 30,
) -> WorktreeHealth:
    health = evaluate_worktree_health(
        observation,
        journal_state,
        active_operation_id,
        project_id=registration.identity.project_id,
        expected_route_config_digest=registration.route_config_digest,
        evaluated_at=evaluated_at,
        max_observation_age_seconds=max_observation_age_seconds,
    )
    if observation is None:
        return health
    extra = list(health.reason_codes)
    if observation.identity != registration.identity:
        extra.append("registration_identity_mismatch")
    if observation.role != registration.branch_role and observation.role != "ACTIVE_CR":
        extra.append("registration_role_mismatch")
    if extra == list(health.reason_codes):
        return health
    return WorktreeHealth(
        project_id=health.project_id,
        decision="BLOCKED",
        observation=health.observation,
        observation_digest=health.observation_digest,
        worktree_state=health.worktree_state,
        journal_state=health.journal_state,
        active_operation_id=health.active_operation_id,
        reason_codes=tuple(dict.fromkeys(extra)),
    )


def list_project_worktrees(
    registrations: tuple[ProjectWorktreeRegistration, ...],
    observations: dict[str, WorktreeObservation | None],
    *,
    evaluated_at: datetime,
    max_observation_age_seconds: int = 30,
) -> tuple[WorktreeHealth, ...]:
    """稳定排序列出各项目健康；缺失 observation 只诊断，不 repair。"""

    return tuple(
        check_project_worktree(
            registration,
            observations.get(registration.identity.project_id),
            journal_state="IDLE",
            active_operation_id=None,
            evaluated_at=evaluated_at,
            max_observation_age_seconds=max_observation_age_seconds,
        )
        for registration in sorted(registrations, key=lambda item: item.identity.project_id)
    )


def plan_worktree_operation(
    operation: str,
    before: WorktreeObservation,
    *,
    desired_ref: str | None,
    desired_oid: str | None,
    checkout_capacity_ref: str,
    journal_capacity_ref: str,
    operation_id: str,
    attempt_id: str,
    created_at: datetime | None = None,
) -> WorktreeOperationPlan:
    allowed = {"CREATE", "BOOTSTRAP", "SWITCH", "ROLLBACK", "REMOVE"}
    if operation not in allowed or not _digest_is_valid(before):
        raise ValueError("operation_plan_invalid")
    if any(
        isinstance(value, UnknownValue)
        for value in (before.head_ref, before.head_oid, before.dirty, before.git_operation)
    ):
        raise ValueError("observation_incomplete")
    if desired_ref == "refs/heads/main":
        raise ValueError("main_is_not_project_working_branch")
    if desired_ref is not None and not desired_ref.startswith(
        f"refs/heads/projects/{_safe_project(before.identity.project_id)}/"
    ):
        raise ValueError("target_ref_outside_project_namespace")
    if desired_oid is not None and (
        len(desired_oid) not in {40, 64}
        or any(char not in "0123456789abcdefABCDEF" for char in desired_oid)
    ):
        raise ValueError("target_oid_invalid")
    return WorktreeOperationPlan(
        operation_id=operation_id,
        attempt_id=attempt_id,
        operation=operation,
        route_digest=before.route_config_digest,
        before_observation_digest=before.observation_digest,
        target_ref=desired_ref,
        target_oid=desired_oid.lower() if desired_oid else None,
        original_ref=before.head_ref if isinstance(before.head_ref, str) else None,
        original_oid=before.head_oid if isinstance(before.head_oid, str) else None,
        checkout_capacity_ref=checkout_capacity_ref,
        journal_capacity_ref=journal_capacity_ref,
        created_at=created_at or datetime.now(UTC),
    )


def bootstrap_integration(
    durable_intent: DurableIntent,
    *,
    root: Path,
    remote: str,
    integration_ref: str,
    git: GitRunner = _default_git,
) -> CreateOnlyRefResult:
    """执行一次 ordinary exact-OID create-only bootstrap。"""

    payload = durable_intent.intent_record.payload
    seed_oid = payload.get("target_oid")
    target_ref = payload.get("target_ref")
    if (
        not durable_intent.sealed
        or durable_intent.seal_record.payload.get("sealed_record_digest")
        != durable_intent.intent_record.record_digest
        or not isinstance(payload.get("authorization_id"), str)
        or not payload.get("authorization_id")
        or not isinstance(payload.get("capacity_proof_ref"), str)
        or not payload.get("capacity_proof_ref")
        or target_ref != integration_ref
        or not isinstance(seed_oid, str)
    ):
        return CreateOnlyRefResult(
            "BLOCKED",
            "journal_not_durable",
            integration_ref,
            "",
            "",
            "",
            0,
            (),
        )
    return create_remote_ref_once(
        root,
        remote,
        integration_ref,
        seed_oid,
        runner=git,
    )


def create_project_worktree(
    durable_intent: DurableIntent,
    bootstrap: CreateOnlyRefResult,
    *,
    identity: WorktreeIdentity,
    route_profile: WorktreePolicyProtocol | None = None,
    git: GitRunner = _default_git,
    observe: Callable[[], WorktreeObservation],
) -> WorktreeOperationResult:
    """在 sibling target 上创建 integration worktree，并由 fresh observe 决定终态。"""

    if route_profile is not None and route_profile.worktree_policy == _ROOT_BRANCH_ONLY:
        return WorktreeOperationResult(
            durable_intent.operation_id,
            durable_intent.attempt_id,
            "BLOCKED",
            "root_branch_only: use git checkout -b <branch> in the root worktree",
            "ABSENT",
            "",
            None,
            "",
            durable_intent.seal_record.path.as_posix(),
            0,
        )

    payload = durable_intent.intent_record.payload
    seed_oid = bootstrap.after_oid or bootstrap.before_oid
    authorized = bool(
        durable_intent.sealed
        and isinstance(payload.get("authorization_id"), str)
        and bool(payload.get("authorization_id"))
        and isinstance(payload.get("capacity_proof_ref"), str)
        and bool(payload.get("capacity_proof_ref"))
        and payload.get("project_id") == identity.project_id
        and payload.get("target_ref") == identity.integration_ref
        and payload.get("target_oid") == seed_oid
        and bootstrap.decision in {"CREATED", "NO_CHANGE"}
        and seed_oid
        and not identity.target_path.exists()
    )
    if not authorized:
        return WorktreeOperationResult(
            durable_intent.operation_id,
            durable_intent.attempt_id,
            "BLOCKED",
            "create_precheck_failed",
            "ABSENT" if not identity.target_path.exists() else "UNKNOWN",
            "",
            None,
            str(payload.get("capacity_proof_ref", "")),
            durable_intent.seal_record.path.as_posix(),
            0,
        )
    branch = identity.integration_ref.removeprefix("refs/heads/")
    control_root = (
        identity.repo_common_dir.parent
        if identity.repo_common_dir.name == ".git"
        else identity.repo_common_dir
    )
    local = git(["show-ref", "--verify", identity.integration_ref], control_root)
    args = (
        ["worktree", "add", identity.target_path.as_posix(), branch]
        if local.ok
        else ["worktree", "add", "-b", branch, identity.target_path.as_posix(), seed_oid]
    )
    git(args, control_root)
    after = observe()
    verified = bool(
        after.identity == identity
        and after.head_ref == identity.integration_ref
        and after.head_oid == seed_oid
        and after.role == "IDLE_INTEGRATION"
        and after.registry_state == "CONSISTENT"
        and after.dirty is False
        and after.git_operation == "NONE"
    )
    return WorktreeOperationResult(
        durable_intent.operation_id,
        durable_intent.attempt_id,
        "CHANGED" if verified else "RECOVERY_REQUIRED",
        "target_verified" if verified else "post_observation_mismatch",
        after.worktree_state,
        "",
        after.observation_digest,
        str(payload.get("capacity_proof_ref", "")),
        durable_intent.seal_record.path.as_posix(),
        1,
    )


def prepare_switch_operation(
    plan: WorktreeOperationPlan,
    prepared_target: PreparedSwitchTarget,
    capacity_decision: CapacityDecision,
    calibration: CalibrationEvidence,
    authorization: OperationAuthorization,
    *,
    journal: WorktreeJournal,
    created_at: datetime | None = None,
) -> DurableIntent:
    """把一次 switch/rollback 的证明与意图持久化为同 attempt sealed chain。"""

    before = prepared_target.before
    if (
        plan.operation not in {"SWITCH", "ROLLBACK"}
        or plan.operation != authorization.operation
        or plan.operation_id == ""
        or plan.attempt_id == ""
        or plan.before_observation_digest != before.observation_digest
        or plan.route_digest != before.route_config_digest
        or plan.target_ref != prepared_target.target_ref
        or plan.target_oid != prepared_target.target_oid
        or journal.project_id != before.identity.project_id
        or journal.repository_id != before.identity.repository_id
        or not authorization.matches(before)
    ):
        raise ValueError("switch_preparation_invalid")
    proof = build_capacity_proof(
        capacity_decision,
        calibration,
        project_id=before.identity.project_id,
        repository_id=before.identity.repository_id,
        operation_id=plan.operation_id,
        attempt_id=plan.attempt_id,
        before_observation_digest=before.observation_digest,
        target_ref=prepared_target.target_ref,
        target_oid=prepared_target.target_oid,
        created_at=created_at,
    )
    return journal.persist_switch_intent(
        proof,
        calibration,
        {
            "operation_state": OperationState.INTENT_PREPARED.value,
            "operation": plan.operation,
            "authorization_id": authorization.authorization_id,
            "project_id": before.identity.project_id,
            "repository_id": before.identity.repository_id,
            "route_digest": before.route_config_digest,
            "before_observation_digest": before.observation_digest,
            "target_ref": prepared_target.target_ref,
            "target_oid": prepared_target.target_oid,
            "original_ref": before.head_ref,
            "original_oid": before.head_oid,
        },
    )


def resume_worktree_operation(
    operation_id: str,
    attempt_id: str,
    *,
    route: RouteDecision,
    identity: WorktreeIdentity,
    journal: WorktreeJournal,
    observe: Callable[[], WorktreeObservation],
) -> WorktreeOperationResult:
    """先校验 chain/seal 再 fresh observe；默认不盲重放任何 Git mutation。"""

    scan = journal.scan_attempt(operation_id, attempt_id)
    if (
        scan.decision != "PASS"
        or scan.durable_intent is None
        or not _route_owns_identity(route, identity)
    ):
        return WorktreeOperationResult(
            operation_id,
            attempt_id,
            "BLOCKED",
            scan.reason if scan.decision != "PASS" else "route_unproven",
            "UNKNOWN",
            "",
            None,
            "",
            "",
            0,
            OperationState.RECOVERY_REQUIRED.value,
        )
    observation = observe()
    payload = scan.durable_intent.intent_record.payload
    target_ref = payload.get("target_ref")
    target_oid = payload.get("target_oid")
    original_ref = payload.get("original_ref")
    original_oid = payload.get("original_oid")
    unsafe = bool(
        observation.dirty is not False
        or observation.staged is not False
        or observation.untracked is not False
        or observation.git_operation != "NONE"
        or observation.registry_state != "CONSISTENT"
    )
    if not unsafe and observation.head_ref == target_ref and observation.head_oid == target_oid:
        decision, reason = "NO_CHANGE", "target_verified"
    elif (
        not unsafe and observation.head_ref == original_ref and observation.head_oid == original_oid
    ):
        decision, reason = "NO_CHANGE", "original_verified"
    else:
        decision, reason = "RECOVERY_REQUIRED", "dirty_state" if unsafe else "third_state"
    return WorktreeOperationResult(
        operation_id,
        attempt_id,
        decision,
        reason,
        observation.worktree_state,
        str(payload.get("before_observation_digest", "")),
        observation.observation_digest,
        str(payload.get("capacity_proof_ref", "")),
        scan.durable_intent.seal_record.path.as_posix(),
        0,
        (
            OperationState.VERIFIED.value
            if decision == "NO_CHANGE"
            else OperationState.RECOVERY_REQUIRED.value
        ),
    )


def _classify_switch_observation(
    after: WorktreeObservation,
    prepared_target: PreparedSwitchTarget,
) -> tuple[str, str]:
    before = prepared_target.before
    unsafe_probe = next(
        (
            reason
            for condition, reason in (
                (after.dirty is not False, "dirty_state"),
                (after.staged is not False, "dirty_state"),
                (after.untracked is not False, "dirty_state"),
                (after.git_operation != "NONE", "git_operation_active"),
                (after.registry_state != "CONSISTENT", "registry_inconsistent"),
            )
            if condition
        ),
        "",
    )
    if unsafe_probe:
        return "RECOVERY_REQUIRED", unsafe_probe
    expected_target_state = (
        "ORIGINAL" if prepared_target.target_ref == before.identity.integration_ref else "TARGET"
    )
    if (
        after.head_ref == prepared_target.target_ref
        and after.head_oid == prepared_target.target_oid
        and after.worktree_state == expected_target_state
    ):
        return "CHANGED", "target_verified"
    if (
        after.head_ref == before.head_ref
        and after.head_oid == before.head_oid
        and after.worktree_state == before.worktree_state
    ):
        return "NO_CHANGE", "original_verified"
    return "RECOVERY_REQUIRED", "third_state"


def execute_switch(
    durable_intent: DurableIntent,
    prepared_target: PreparedSwitchTarget,
    *,
    journal: WorktreeJournal,
    authorization: OperationAuthorization,
    git: GitRunner,
    observe: Callable[[], WorktreeObservation],
    now: datetime | None = None,
) -> WorktreeOperationResult:
    """在单一 project lock 内重验证明、执行一次 switch 并持久化终态。"""

    before = prepared_target.before
    payload = durable_intent.intent_record.payload

    def blocked(reason: str, *, journal_head: str = "") -> WorktreeOperationResult:
        return WorktreeOperationResult(
            operation_id=durable_intent.operation_id,
            attempt_id=durable_intent.attempt_id,
            decision="BLOCKED",
            reason=reason,
            observed_state=before.worktree_state,
            before_observation_ref=before.observation_digest,
            after_observation_ref=None,
            capacity_proof_ref=str(payload.get("capacity_proof_ref", "")),
            journal_head_ref=journal_head or durable_intent.seal_record.path.as_posix(),
            mutation_count=0,
            operation_state=OperationState.RECOVERY_REQUIRED.value,
        )

    try:
        with journal.operation_session() as session:
            scan = session.scan_attempt(durable_intent.operation_id, durable_intent.attempt_id)
            scanned_intent = scan.durable_intent
            if (
                scan.decision != "PASS"
                or scanned_intent is None
                or not durable_intent.sealed
                or scanned_intent.intent_record.record_digest
                != durable_intent.intent_record.record_digest
                or scanned_intent.intent_record.payload != durable_intent.intent_record.payload
                or scanned_intent.seal_record.record_digest
                != durable_intent.seal_record.record_digest
                or scanned_intent.seal_record.payload != durable_intent.seal_record.payload
            ):
                return blocked(scan.reason if scan.decision != "PASS" else "journal_not_durable")

            if scan.records[-1].phase == "FINAL_OBSERVATION":
                after = observe()
                decision, reason = _classify_switch_observation(after, prepared_target)
                if decision == "CHANGED":
                    decision = "NO_CHANGE"
                return WorktreeOperationResult(
                    durable_intent.operation_id,
                    durable_intent.attempt_id,
                    decision,
                    reason,
                    after.worktree_state,
                    before.observation_digest,
                    after.observation_digest,
                    str(payload.get("capacity_proof_ref", "")),
                    scan.records[-1].path.as_posix(),
                    0,
                    (
                        OperationState.VERIFIED.value
                        if decision == "NO_CHANGE"
                        else OperationState.RECOVERY_REQUIRED.value
                    ),
                )

            fresh_before = observe()
            if (
                fresh_before.observation_digest != before.observation_digest
                or fresh_before.identity != before.identity
            ):
                return blocked("before_observation_drift")
            if (
                not authorization.matches(fresh_before)
                or authorization.authorization_id != payload.get("authorization_id")
                or authorization.operation != payload.get("operation")
                or payload.get("project_id") != before.identity.project_id
                or payload.get("repository_id") != before.identity.repository_id
                or payload.get("route_digest") != before.route_config_digest
                or payload.get("before_observation_digest") != before.observation_digest
                or payload.get("target_ref") != prepared_target.target_ref
                or payload.get("target_oid") != prepared_target.target_oid
            ):
                return blocked("authorization_or_intent_mismatch")

            proof_records = [record for record in scan.records if record.phase == "CAPACITY_PROOF"]
            if len(proof_records) != 1:
                return blocked("capacity_proof_missing")
            proof_record = proof_records[0]
            try:
                proof = CapacityProof.from_dict(proof_record.payload)
                calibration = session.load_calibration(proof.profile_digest)
            except (ValueError, JournalError) as error:
                reason = error.code if isinstance(error, JournalError) else str(error)
                return blocked(reason)
            if (
                payload.get("capacity_proof_ref") != proof_record.path.as_posix()
                or payload.get("capacity_proof_digest") != proof.proof_digest
                or payload.get("capacity_record_digest") != proof_record.record_digest
            ):
                return blocked("capacity_proof_reference_mismatch")
            proved, proof_reason = validate_capacity_proof(
                proof,
                calibration,
                project_id=before.identity.project_id,
                repository_id=before.identity.repository_id,
                operation_id=durable_intent.operation_id,
                attempt_id=durable_intent.attempt_id,
                before_observation_digest=before.observation_digest,
                target_ref=prepared_target.target_ref,
                target_oid=prepared_target.target_oid,
                now=now,
            )
            if not proved:
                return blocked(proof_reason)

            observation_required = session.persist_phase(
                durable_intent.operation_id,
                durable_intent.attempt_id,
                "OBSERVATION_REQUIRED",
                {
                    "operation_state": OperationState.OBSERVATION_REQUIRED.value,
                    "intent_seal_digest": scanned_intent.seal_record.record_digest,
                    "capacity_proof_digest": proof.proof_digest,
                },
            )
            branch = prepared_target.target_ref.removeprefix("refs/heads/")
            runner_error = ""
            try:
                git(["switch", branch], before.identity.target_path)
            except Exception as error:  # runner 异常不作为终态真相源
                runner_error = type(error).__name__
            try:
                after = observe()
                decision, reason = _classify_switch_observation(after, prepared_target)
                final = session.persist_phase(
                    durable_intent.operation_id,
                    durable_intent.attempt_id,
                    "FINAL_OBSERVATION",
                    {
                        "operation_state": (
                            OperationState.VERIFIED.value
                            if decision in {"CHANGED", "NO_CHANGE"}
                            else OperationState.RECOVERY_REQUIRED.value
                        ),
                        "decision": decision,
                        "reason": reason,
                        "runner_error": runner_error,
                        "observation_digest": after.observation_digest,
                        "observation_required_ref": observation_required.path.name,
                    },
                )
            except Exception as error:
                return WorktreeOperationResult(
                    durable_intent.operation_id,
                    durable_intent.attempt_id,
                    "RECOVERY_REQUIRED",
                    f"post_observation_failed:{type(error).__name__}",
                    "UNKNOWN",
                    before.observation_digest,
                    None,
                    proof_record.path.as_posix(),
                    observation_required.path.as_posix(),
                    1,
                    OperationState.RECOVERY_REQUIRED.value,
                )
            return WorktreeOperationResult(
                durable_intent.operation_id,
                durable_intent.attempt_id,
                decision,
                reason,
                after.worktree_state,
                before.observation_digest,
                after.observation_digest,
                proof_record.path.as_posix(),
                final.path.as_posix(),
                1,
                (
                    OperationState.VERIFIED.value
                    if decision in {"CHANGED", "NO_CHANGE"}
                    else OperationState.RECOVERY_REQUIRED.value
                ),
            )
    except JournalError as error:
        return blocked(error.code)


def safe_remove(
    identity: WorktreeIdentity,
    health: WorktreeHealth,
    authorization: RemovalAuthorization,
    *,
    git: GitRunner,
    observe_absent: Callable[[], bool],
) -> WorktreeOperationResult:
    observation = health.observation
    authorized = bool(
        authorization.authorized
        and authorization.authorization_id
        and authorization.expected_project_id == identity.project_id
        and authorization.expected_target_digest == identity.target_path_digest
        and authorization.expected_role == "IDLE_INTEGRATION"
        and health.decision == "HEALTHY"
        and health.active_operation_id is None
        and health.journal_state in {"IDLE", "VERIFIED_ORIGINAL"}
        and observation is not None
        and observation.identity == identity
        and observation.role == "IDLE_INTEGRATION"
        and observation.dirty is False
        and observation.staged is False
        and observation.untracked is False
        and observation.git_operation == "NONE"
        and observation.registry_state == "CONSISTENT"
    )
    operation_id = f"remove-{identity.worktree_id}"
    if not authorized:
        return WorktreeOperationResult(
            operation_id=operation_id,
            attempt_id=authorization.authorization_id or "unauthorized",
            decision="BLOCKED",
            reason="remove_not_authorized",
            observed_state=health.worktree_state,
            before_observation_ref=health.observation_digest or "",
            after_observation_ref=None,
            capacity_proof_ref="",
            journal_head_ref="",
            mutation_count=0,
        )
    control_root = (
        identity.repo_common_dir.parent
        if identity.repo_common_dir.name == ".git"
        else identity.repo_common_dir
    )
    git(["worktree", "remove", identity.target_path.as_posix()], control_root)
    absent = observe_absent()
    return WorktreeOperationResult(
        operation_id=operation_id,
        attempt_id=authorization.authorization_id,
        decision="CHANGED" if absent else "RECOVERY_REQUIRED",
        reason="removed_verified" if absent else "remove_post_observation_mismatch",
        observed_state="ABSENT" if absent else "UNKNOWN",
        before_observation_ref=health.observation_digest or "",
        after_observation_ref=None,
        capacity_proof_ref="",
        journal_head_ref="",
        mutation_count=1,
    )
