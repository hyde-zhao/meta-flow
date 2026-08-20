"""Governed paired-repository Git branch lifecycle.

The module deliberately uses native Git argv calls.  It never invokes a shell,
stages or commits files, creates merge commits, rebases, force-updates refs, or
silently treats a one-repository result as a paired workflow success.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from meta_flow.workspace.git_sync import (
    GitCommandResult,
    git_root,
    remote_default_branch,
    remote_ref_oid,
    repo_fingerprint,
    run_git,
    workspace_repositories,
)

CR_ID_RE = re.compile(r"CR-\d+")
OID_RE = re.compile(r"[0-9a-f]{40}")
SAFE_TOKEN_RE = re.compile(r"[^a-z0-9._-]+")
SAFE_GIT_INPUT_RE = re.compile(r"[A-Za-z0-9._/-]+")
TERMINAL_SUCCESS = {"PASS", "NO_CHANGE"}
REPOSITORY_ORDER = ("project", "artifact")
DESTRUCTIVE_ORDER = ("artifact", "project")
PROTECTED_BRANCHES = {"main", "master", "develop", "development", "trunk"}


class LifecycleError(ValueError):
    """Expected fail-closed validation error with a stable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RepositoryTarget:
    label: str
    root: Path
    fingerprint: str
    remote: str = "origin"


@dataclass(frozen=True)
class RefSnapshot:
    label: str
    root: str
    fingerprint: str
    remote: str
    current_branch: str
    head_oid: str
    dirty: bool
    upstream: str
    default_branch: str
    default_local_oid: str
    default_remote_oid: str
    cr_local_oid: str
    cr_remote_oid: str
    observed_at: str


@dataclass(frozen=True)
class OperationAuthorization:
    authorization_id: str
    operation: str
    cr_id: str
    branch: str
    remote: str
    repository_labels: tuple[str, ...]
    expected_oids: dict[str, dict[str, str]]
    issued_by: str
    issued_at: str
    expires_at: str
    single_use: bool = True


@dataclass(frozen=True)
class BranchLifecycleIntent:
    operation: str
    cr_id: str
    branch: str
    targets: tuple[RepositoryTarget, ...]
    remote: str
    default_branch_override: str = ""
    dry_run: bool = False
    authorization_ref: str = ""


@dataclass(frozen=True)
class PlanStep:
    repository: str
    phase: str
    argv: tuple[str, ...]
    before_oid: str
    expected_after_oid: str
    precondition: str


@dataclass(frozen=True)
class BranchOperationPlan:
    schema_version: int
    operation: str
    cr_id: str
    branch: str
    dry_run: bool
    repository_order: tuple[str, ...]
    snapshots: tuple[RefSnapshot, ...]
    steps: tuple[PlanStep, ...]
    authorization_id: str
    plan_digest: str


@dataclass(frozen=True)
class RepoOutcome:
    repository: str
    terminal: str
    before_oid: str = ""
    expected_oid: str = ""
    after_oid: str = ""
    mutation: bool = False
    executed_steps: tuple[str, ...] = ()
    skipped_steps: tuple[str, ...] = ()
    error_code: str = ""
    error_summary: str = ""
    resume_route: str = ""


@dataclass(frozen=True)
class PublishEvidence:
    cr_id: str
    repository: str
    branch: str
    entry_local_oid: str
    remote_before_oid: str
    remote_after_oid: str
    terminal: str
    observed_at: str
    result_ref: str


@dataclass(frozen=True)
class PairedMergeProjection:
    attempt_ref: str
    repo_terminals: dict[str, str]
    paired_complete: bool
    paired_projection_advanced: bool
    finish_allowed: bool
    cr_close_allowed: bool


@dataclass(frozen=True)
class BranchOperationAttempt:
    schema_version: int
    attempt_id: str
    operation: str
    cr_id: str
    branch: str
    plan_digest: str
    authorization_id: str
    dry_run: bool
    repository_order: tuple[str, ...]
    repo_outcomes: tuple[RepoOutcome, ...]
    overall: str
    started_at: str
    completed_at: str
    resume_route: str
    publish_evidence: tuple[PublishEvidence, ...] = ()
    paired_projection: PairedMergeProjection | None = None
    recovery_refs: dict[str, str] = field(default_factory=dict)


GitRunner = Callable[[list[str], Path], GitCommandResult]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _default_runner(args: list[str], cwd: Path) -> GitCommandResult:
    return run_git(args, cwd=cwd)


def _bounded_detail(result: GitCommandResult) -> str:
    raw = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
    return raw.replace("\n", " ")[:500]


def _validate_plain_token(value: str, label: str) -> str:
    if (
        not value
        or value.startswith("-")
        or not SAFE_GIT_INPUT_RE.fullmatch(value)
        or any(char in value for char in ("\x00", "\n", "\r"))
    ):
        raise LifecycleError("invalid_input", f"invalid {label}")
    return value


def canonical_branch_name(cr_id: str, slug: str = "") -> str:
    """Build the deterministic CR branch name used when ``--branch`` is omitted."""

    validate_cr_id(cr_id)
    normalized = SAFE_TOKEN_RE.sub("-", slug.strip().lower()).strip("-._")
    suffix = f"-{normalized}" if normalized else ""
    return f"cr/{cr_id.lower()}{suffix}"


def validate_cr_id(cr_id: str) -> str:
    if not CR_ID_RE.fullmatch(cr_id):
        raise LifecycleError("invalid_cr_id", "CR ID must use CR-<digits>")
    return cr_id


def validate_branch(branch: str, *, root: Path) -> str:
    try:
        _validate_plain_token(branch, "branch")
    except LifecycleError as exc:
        raise LifecycleError("invalid_branch", str(exc)) from exc
    result = run_git(["check-ref-format", "--branch", branch], cwd=root)
    if not result.ok:
        raise LifecycleError("invalid_branch", "branch does not satisfy git check-ref-format --branch")
    return branch


def _validate_oid(value: str, label: str, *, allow_empty: bool = False) -> str:
    if allow_empty and not value:
        return value
    if not OID_RE.fullmatch(value):
        raise LifecycleError("invalid_oid", f"{label} must be a full 40-character OID")
    return value


def discover_branch_targets(project_root: Path, remote: str = "origin") -> tuple[RepositoryTarget, ...]:
    _validate_plain_token(remote, "remote")
    statuses, warnings = workspace_repositories(project_root.resolve())
    if warnings and not statuses:
        raise LifecycleError("route_invalid", "; ".join(warnings))
    targets: list[RepositoryTarget] = []
    seen: set[Path] = set()
    for status in statuses:
        if not status.is_git_repo:
            raise LifecycleError("route_invalid", f"{status.label}: {status.error or 'not a git repository'}")
        root = status.root.resolve()
        if root in seen:
            raise LifecycleError("duplicate_root", f"duplicate repository root: {root}")
        seen.add(root)
        targets.append(
            RepositoryTarget(
                label=status.label,
                root=root,
                fingerprint=repo_fingerprint(root),
                remote=remote,
            )
        )
    labels = {target.label for target in targets}
    if "project" not in labels:
        raise LifecycleError("route_invalid", "workspace route does not contain project repository")
    return tuple(_ordered_targets(targets, REPOSITORY_ORDER))


def _ordered_targets(
    targets: Iterable[RepositoryTarget], order: tuple[str, ...]
) -> list[RepositoryTarget]:
    by_label = {target.label: target for target in targets}
    return [by_label[label] for label in order if label in by_label]


def _local_oid(root: Path, ref: str) -> str:
    result = run_git(["rev-parse", "--verify", ref], cwd=root)
    return result.stdout.strip() if result.ok else ""


def _branch_upstream(root: Path, branch: str) -> str:
    result = run_git(
        ["for-each-ref", "--format=%(upstream:short)", f"refs/heads/{branch}"], cwd=root
    )
    return result.stdout.strip() if result.ok else ""


def observe_repo(
    target: RepositoryTarget,
    branch: str,
    default_branch_override: str = "",
) -> RefSnapshot:
    root = git_root(target.root)
    if root is None or root != target.root.resolve():
        raise LifecycleError("not_git", f"{target.label}: invalid repository root")
    validate_branch(branch, root=root)
    default_branch = remote_default_branch(root, target.remote, default_branch_override)
    validate_branch(default_branch, root=root)
    current = run_git(["symbolic-ref", "--quiet", "--short", "HEAD"], cwd=root)
    current_branch = current.stdout.strip() if current.ok else ""
    head_oid = _local_oid(root, "HEAD")
    dirty_result = run_git(["status", "--porcelain=v1", "--untracked-files=all"], cwd=root)
    if not dirty_result.ok:
        raise LifecycleError("status_failed", f"{target.label}: cannot inspect working tree")
    default_ref = f"refs/heads/{default_branch}"
    cr_ref = f"refs/heads/{branch}"
    try:
        default_remote_oid = remote_ref_oid(root, target.remote, default_ref)
        cr_remote_oid = remote_ref_oid(root, target.remote, cr_ref)
    except ValueError as exc:
        raise LifecycleError("remote_query_failed", f"{target.label}: {exc}") from exc
    return RefSnapshot(
        label=target.label,
        root=root.as_posix(),
        fingerprint=target.fingerprint,
        remote=target.remote,
        current_branch=current_branch,
        head_oid=head_oid,
        dirty=bool(dirty_result.stdout.strip()),
        upstream=_branch_upstream(root, branch),
        default_branch=default_branch,
        default_local_oid=_local_oid(root, default_ref),
        default_remote_oid=default_remote_oid,
        cr_local_oid=_local_oid(root, cr_ref),
        cr_remote_oid=cr_remote_oid,
        observed_at=_now(),
    )


def load_authorization(path: Path) -> OperationAuthorization:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LifecycleError("authorization_invalid", f"cannot read authorization: {path}") from exc
    if payload.get("schema_version") != 1:
        raise LifecycleError("authorization_invalid", "authorization schema_version must be 1")
    repositories = payload.get("repositories")
    if not isinstance(repositories, dict) or not repositories:
        raise LifecycleError("authorization_invalid", "authorization repositories must be a non-empty object")
    expected: dict[str, dict[str, str]] = {}
    for label, item in repositories.items():
        if not isinstance(item, dict):
            raise LifecycleError("authorization_invalid", f"authorization repository {label} must be an object")
        expected[str(label)] = {str(key): str(value) for key, value in item.items()}
    return OperationAuthorization(
        authorization_id=str(payload.get("authorization_id") or ""),
        operation=str(payload.get("operation") or ""),
        cr_id=str(payload.get("cr_id") or ""),
        branch=str(payload.get("branch") or ""),
        remote=str(payload.get("remote") or ""),
        repository_labels=tuple(str(label) for label in repositories),
        expected_oids=expected,
        issued_by=str(payload.get("issued_by") or ""),
        issued_at=str(payload.get("issued_at") or ""),
        expires_at=str(payload.get("expires_at") or ""),
        single_use=bool(payload.get("single_use", True)),
    )


def validate_authorization(
    authorization: OperationAuthorization | None,
    intent: BranchLifecycleIntent,
    snapshots: tuple[RefSnapshot, ...],
    expected_key: str,
    observed_oids: dict[str, str] | None = None,
) -> None:
    if intent.dry_run and authorization is None:
        return
    if authorization is None:
        raise LifecycleError("authorization_missing", f"{intent.operation} requires typed authorization")
    if not authorization.authorization_id or not authorization.issued_by:
        raise LifecycleError("authorization_mismatch", "authorization identity/issuer is missing")
    if (
        authorization.operation != intent.operation
        or authorization.cr_id != intent.cr_id
        or authorization.branch != intent.branch
        or authorization.remote != intent.remote
    ):
        raise LifecycleError("authorization_mismatch", "authorization operation/ref identity mismatch")
    labels = tuple(snapshot.label for snapshot in snapshots)
    if set(authorization.repository_labels) != set(labels):
        raise LifecycleError("authorization_mismatch", "authorization repository set mismatch")
    if authorization.expires_at:
        try:
            expiry = datetime.fromisoformat(authorization.expires_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise LifecycleError("authorization_invalid", "authorization expires_at is invalid") from exc
        if expiry.tzinfo is None or expiry <= datetime.now(UTC):
            raise LifecycleError("authorization_expired", "authorization has expired")
    for snapshot in snapshots:
        item = authorization.expected_oids.get(snapshot.label, {})
        if item.get("fingerprint") != snapshot.fingerprint:
            raise LifecycleError(
                "authorization_mismatch",
                f"{snapshot.label}: authorization repository fingerprint mismatch",
            )
        if item.get("default_branch") and item.get("default_branch") != snapshot.default_branch:
            raise LifecycleError(
                "authorization_mismatch",
                f"{snapshot.label}: authorization default branch mismatch",
            )
        expected = item.get(expected_key, "")
        actual = (observed_oids or {}).get(snapshot.label) or {
            "default_oid": snapshot.default_remote_oid,
            "local_oid": snapshot.cr_local_oid or snapshot.head_oid,
            "published_oid": snapshot.cr_remote_oid,
            "known_tip": snapshot.cr_remote_oid,
        }.get(expected_key, "")
        if not expected or expected != actual:
            raise LifecycleError(
                "authorization_mismatch",
                f"{snapshot.label}: authorization {expected_key} does not match fresh observation",
            )


def _is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    if not ancestor or not descendant:
        return False
    result = run_git(["merge-base", "--is-ancestor", ancestor, descendant], cwd=root)
    return result.returncode == 0


def _plan_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def _build_plan(
    intent: BranchLifecycleIntent,
    snapshots: tuple[RefSnapshot, ...],
    steps: list[PlanStep],
    authorization: OperationAuthorization | None,
    order: tuple[str, ...],
) -> BranchOperationPlan:
    digest_payload = {
        "operation": intent.operation,
        "cr_id": intent.cr_id,
        "branch": intent.branch,
        "dry_run": intent.dry_run,
        "repository_order": order,
        "snapshots": [asdict(snapshot) | {"observed_at": "<fresh>"} for snapshot in snapshots],
        "steps": [asdict(step) for step in steps],
        "authorization_id": authorization.authorization_id if authorization else "",
    }
    return BranchOperationPlan(
        schema_version=1,
        operation=intent.operation,
        cr_id=intent.cr_id,
        branch=intent.branch,
        dry_run=intent.dry_run,
        repository_order=order,
        snapshots=snapshots,
        steps=tuple(steps),
        authorization_id=authorization.authorization_id if authorization else "",
        plan_digest=_plan_digest(digest_payload),
    )


def plan_open(
    intent: BranchLifecycleIntent,
    snapshots: tuple[RefSnapshot, ...],
    authorization: OperationAuthorization | None,
) -> BranchOperationPlan:
    if intent.operation != "open":
        raise LifecycleError("invalid_operation", "open planner requires operation=open")
    validate_authorization(authorization, intent, snapshots, "default_oid")
    steps: list[PlanStep] = []
    for snapshot in snapshots:
        if snapshot.dirty:
            raise LifecycleError("dirty_tree", f"{snapshot.label}: working tree is dirty")
        if not snapshot.current_branch:
            raise LifecycleError("detached_head", f"{snapshot.label}: detached HEAD")
        if snapshot.current_branch != snapshot.default_branch:
            raise LifecycleError(
                "wrong_branch", f"{snapshot.label}: open must start on local default branch"
            )
        if not snapshot.default_remote_oid or not snapshot.default_local_oid:
            raise LifecycleError("default_unknown", f"{snapshot.label}: default branch OID unavailable")
        if snapshot.cr_local_oid or snapshot.cr_remote_oid:
            raise LifecycleError("branch_collision", f"{snapshot.label}: CR branch already exists")
        root = Path(snapshot.root)
        if not _is_ancestor(root, snapshot.default_local_oid, snapshot.default_remote_oid):
            raise LifecycleError(
                "default_diverged_or_ahead",
                f"{snapshot.label}: local default is not a fast-forward ancestor of remote default",
            )
        steps.extend(
            [
                PlanStep(snapshot.label, "local_mutation", ("git", "fetch", "--prune", intent.remote), snapshot.default_local_oid, snapshot.default_remote_oid, "all repositories preflighted"),
                PlanStep(snapshot.label, "local_mutation", ("git", "pull", "--ff-only", intent.remote, snapshot.default_branch), snapshot.default_local_oid, snapshot.default_remote_oid, "fresh remote default unchanged"),
                PlanStep(snapshot.label, "local_mutation", ("git", "switch", "-c", intent.branch, f"{intent.remote}/{snapshot.default_branch}"), "", snapshot.default_remote_oid, "CR branch absent"),
                PlanStep(snapshot.label, "remote_mutation", ("git", "push", "-u", intent.remote, intent.branch), "", snapshot.default_remote_oid, "local CR branch exact"),
            ]
        )
    return _build_plan(intent, snapshots, steps, authorization, REPOSITORY_ORDER)


def _overall(outcomes: list[RepoOutcome], required_count: int) -> str:
    if len(outcomes) == required_count and all(item.terminal in TERMINAL_SUCCESS for item in outcomes):
        return "PASS"
    if any(item.mutation or item.terminal == "PASS" for item in outcomes):
        return "PARTIAL"
    if any(item.terminal == "FAILED" for item in outcomes):
        return "FAILED"
    return "BLOCKED"


def _attempt(
    plan: BranchOperationPlan,
    outcomes: list[RepoOutcome],
    started_at: str,
    *,
    publish_evidence: tuple[PublishEvidence, ...] = (),
    projection: PairedMergeProjection | None = None,
    recovery_refs: dict[str, str] | None = None,
) -> BranchOperationAttempt:
    overall = _overall(outcomes, len(plan.snapshots))
    resume = "none" if overall == "PASS" else f"fresh-reobserve-and-resume-{plan.operation}"
    return BranchOperationAttempt(
        schema_version=1,
        attempt_id=f"{plan.cr_id}-{plan.operation}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}",
        operation=plan.operation,
        cr_id=plan.cr_id,
        branch=plan.branch,
        plan_digest=plan.plan_digest,
        authorization_id=plan.authorization_id,
        dry_run=plan.dry_run,
        repository_order=plan.repository_order,
        repo_outcomes=tuple(outcomes),
        overall=overall,
        started_at=started_at,
        completed_at=_now(),
        resume_route=resume,
        publish_evidence=publish_evidence,
        paired_projection=projection,
        recovery_refs=recovery_refs or {},
    )


def execute_open(
    plan: BranchOperationPlan,
    *,
    runner: GitRunner = _default_runner,
) -> BranchOperationAttempt:
    started = _now()
    if plan.dry_run:
        outcomes = [
            RepoOutcome(
                repository=snapshot.label,
                terminal="NO_CHANGE",
                before_oid=snapshot.default_remote_oid,
                expected_oid=snapshot.default_remote_oid,
                after_oid=snapshot.default_remote_oid,
                skipped_steps=("fetch", "pull-ff-only", "switch-create", "push-upstream"),
                resume_route="execute-open-with-current-typed-authorization",
            )
            for snapshot in plan.snapshots
        ]
        return _attempt(plan, outcomes, started)
    outcomes: list[RepoOutcome] = []
    # Refresh every repository first, then pin the remote defaults to the OIDs
    # authorized by the immutable plan before creating either CR branch.
    for snapshot in plan.snapshots:
        root = Path(snapshot.root)
        result = runner(["fetch", "--prune", snapshot.remote], root)
        if not result.ok:
            outcomes.append(
                RepoOutcome(
                    repository=snapshot.label,
                    terminal="FAILED",
                    before_oid=snapshot.default_local_oid,
                    expected_oid=snapshot.default_remote_oid,
                    after_oid=_local_oid(root, "HEAD"),
                    mutation=False,
                    executed_steps=("fetch",),
                    error_code="refresh_failed",
                    error_summary=_bounded_detail(result),
                    resume_route="inspect-local-refs-then-run-fresh-open-attempt",
                )
            )
            return _attempt(plan, outcomes, started)
        fresh_default = remote_ref_oid(
            root, snapshot.remote, f"refs/heads/{snapshot.default_branch}"
        )
        if fresh_default != snapshot.default_remote_oid:
            outcomes.append(
                RepoOutcome(
                    repository=snapshot.label,
                    terminal="BLOCKED",
                    before_oid=snapshot.default_remote_oid,
                    expected_oid=snapshot.default_remote_oid,
                    after_oid=fresh_default,
                    mutation=False,
                    executed_steps=("fetch", "fresh-default-query"),
                    error_code="ref_drift",
                    error_summary="remote default changed after authorization/planning",
                    resume_route="create-new-open-plan-and-authorization-from-fresh-defaults",
                )
            )
            return _attempt(plan, outcomes, started)
    prepared: list[RefSnapshot] = []
    for snapshot in plan.snapshots:
        root = Path(snapshot.root)
        commands = [
            ["pull", "--ff-only", snapshot.remote, snapshot.default_branch],
            ["switch", "-c", plan.branch, snapshot.default_remote_oid],
        ]
        executed = ["fetch"]
        for command in commands:
            result = runner(command, root)
            executed.append(command[0])
            if not result.ok:
                outcomes.append(
                    RepoOutcome(
                        repository=snapshot.label,
                        terminal="FAILED",
                        before_oid=snapshot.default_local_oid,
                        expected_oid=snapshot.default_remote_oid,
                        after_oid=_local_oid(root, "HEAD"),
                        mutation=True,
                        executed_steps=tuple(executed),
                        error_code="local_prepare_failed",
                        error_summary=_bounded_detail(result),
                        resume_route="inspect-local-refs-then-run-fresh-open-attempt",
                    )
                )
                return _attempt(plan, outcomes, started)
            if command[0] == "pull" and _local_oid(root, "HEAD") != snapshot.default_remote_oid:
                outcomes.append(
                    RepoOutcome(
                        repository=snapshot.label,
                        terminal="BLOCKED",
                        before_oid=snapshot.default_local_oid,
                        expected_oid=snapshot.default_remote_oid,
                        after_oid=_local_oid(root, "HEAD"),
                        mutation=False,
                        executed_steps=tuple(executed),
                        error_code="post_refresh_mismatch",
                        error_summary="local default is not the authorized exact remote default",
                        resume_route="inspect-default-divergence-and-create-new-open-plan",
                    )
                )
                return _attempt(plan, outcomes, started)
        prepared.append(snapshot)
    for snapshot in prepared:
        root = Path(snapshot.root)
        result = runner(["push", "-u", snapshot.remote, plan.branch], root)
        if not result.ok:
            outcomes.append(
                RepoOutcome(
                    repository=snapshot.label,
                    terminal="FAILED",
                    before_oid="",
                    expected_oid=snapshot.default_remote_oid,
                    after_oid="",
                    mutation=True,
                    executed_steps=("fetch", "pull-ff-only", "switch-create", "push-upstream"),
                    error_code="remote_policy_rejected",
                    error_summary=_bounded_detail(result),
                    resume_route="fresh-query-branch-and-resume-open",
                )
            )
            return _attempt(plan, outcomes, started)
        after = remote_ref_oid(root, snapshot.remote, f"refs/heads/{plan.branch}")
        upstream = _branch_upstream(root, plan.branch)
        terminal = "PASS" if after == snapshot.default_remote_oid and upstream == f"{snapshot.remote}/{plan.branch}" else "FAILED"
        outcomes.append(
            RepoOutcome(
                repository=snapshot.label,
                terminal=terminal,
                before_oid="",
                expected_oid=snapshot.default_remote_oid,
                after_oid=after,
                mutation=True,
                executed_steps=("fetch", "pull-ff-only", "switch-create", "push-upstream", "post-query"),
                error_code="" if terminal == "PASS" else "post_verify_failed",
                error_summary="" if terminal == "PASS" else "remote OID or upstream mismatch",
                resume_route="none" if terminal == "PASS" else "fresh-query-branch-and-resume-open",
            )
        )
        if terminal != "PASS":
            return _attempt(plan, outcomes, started)
    return _attempt(plan, outcomes, started)


def plan_publish(
    intent: BranchLifecycleIntent,
    snapshots: tuple[RefSnapshot, ...],
    authorization: OperationAuthorization | None,
) -> BranchOperationPlan:
    if intent.operation != "publish":
        raise LifecycleError("invalid_operation", "publish planner requires operation=publish")
    validate_authorization(authorization, intent, snapshots, "local_oid")
    steps: list[PlanStep] = []
    for snapshot in snapshots:
        if snapshot.dirty:
            raise LifecycleError("dirty_tree", f"{snapshot.label}: publish requires a clean tree")
        if snapshot.current_branch != intent.branch:
            raise LifecycleError("wrong_branch", f"{snapshot.label}: current branch is not {intent.branch}")
        if not snapshot.cr_local_oid or snapshot.cr_local_oid != snapshot.head_oid:
            raise LifecycleError("ref_drift", f"{snapshot.label}: local CR ref does not equal captured HEAD")
        if snapshot.upstream != f"{intent.remote}/{intent.branch}":
            raise LifecycleError("wrong_upstream", f"{snapshot.label}: CR branch upstream mismatch")
        if snapshot.cr_remote_oid and not _is_ancestor(
            Path(snapshot.root), snapshot.cr_remote_oid, snapshot.cr_local_oid
        ):
            raise LifecycleError("non_fast_forward", f"{snapshot.label}: remote CR ref cannot fast-forward")
        steps.append(
            PlanStep(
                snapshot.label,
                "remote_mutation",
                ("git", "push", "--porcelain", intent.remote, f"{snapshot.cr_local_oid}:refs/heads/{intent.branch}"),
                snapshot.cr_remote_oid,
                snapshot.cr_local_oid,
                "clean committed exact local ref",
            )
        )
    return _build_plan(intent, snapshots, steps, authorization, REPOSITORY_ORDER)


def execute_publish(
    plan: BranchOperationPlan, *, runner: GitRunner = _default_runner, result_ref: str = ""
) -> BranchOperationAttempt:
    started = _now()
    outcomes: list[RepoOutcome] = []
    evidence: list[PublishEvidence] = []
    for snapshot in plan.snapshots:
        if plan.dry_run:
            terminal = "NO_CHANGE"
            after = snapshot.cr_remote_oid
            mutation = False
            executed: tuple[str, ...] = ()
            skipped = ("push-exact-committed-ref",)
        elif snapshot.cr_remote_oid == snapshot.cr_local_oid:
            terminal = "NO_CHANGE"
            after = snapshot.cr_remote_oid
            mutation = False
            executed = ("fresh-query",)
            skipped = ("push-exact-committed-ref",)
        else:
            root = Path(snapshot.root)
            result = runner(
                ["push", "--porcelain", snapshot.remote, f"{snapshot.cr_local_oid}:refs/heads/{plan.branch}"],
                root,
            )
            if not result.ok:
                outcomes.append(
                    RepoOutcome(
                        repository=snapshot.label,
                        terminal="FAILED",
                        before_oid=snapshot.cr_remote_oid,
                        expected_oid=snapshot.cr_local_oid,
                        after_oid=remote_ref_oid(root, snapshot.remote, f"refs/heads/{plan.branch}"),
                        mutation=False,
                        executed_steps=("push-exact-committed-ref",),
                        error_code="remote_policy_rejected",
                        error_summary=_bounded_detail(result),
                        resume_route="fresh-query-and-resume-publish",
                    )
                )
                return _attempt(plan, outcomes, started, publish_evidence=tuple(evidence))
            after = remote_ref_oid(root, snapshot.remote, f"refs/heads/{plan.branch}")
            terminal = "PASS" if after == snapshot.cr_local_oid else "FAILED"
            mutation = after != snapshot.cr_remote_oid
            executed = ("push-exact-committed-ref", "post-query")
            skipped = ()
        outcome = RepoOutcome(
            repository=snapshot.label,
            terminal=terminal,
            before_oid=snapshot.cr_remote_oid,
            expected_oid=snapshot.cr_local_oid,
            after_oid=after,
            mutation=mutation,
            executed_steps=executed,
            skipped_steps=skipped,
            error_code="" if terminal in TERMINAL_SUCCESS else "post_verify_failed",
            error_summary="" if terminal in TERMINAL_SUCCESS else "remote CR ref differs from captured local OID",
            resume_route="none" if terminal in TERMINAL_SUCCESS else "fresh-query-and-resume-publish",
        )
        outcomes.append(outcome)
        if terminal in TERMINAL_SUCCESS and not plan.dry_run:
            evidence.append(
                PublishEvidence(
                    cr_id=plan.cr_id,
                    repository=snapshot.label,
                    branch=plan.branch,
                    entry_local_oid=snapshot.cr_local_oid,
                    remote_before_oid=snapshot.cr_remote_oid,
                    remote_after_oid=after,
                    terminal=terminal,
                    observed_at=_now(),
                    result_ref=result_ref,
                )
            )
        if terminal not in TERMINAL_SUCCESS:
            break
    return _attempt(plan, outcomes, started, publish_evidence=tuple(evidence))


def _publish_tips(payload: dict[str, Any], cr_id: str, branch: str) -> dict[str, str]:
    tips: dict[str, str] = {}
    for item in payload.get("publish_evidence") or []:
        if not isinstance(item, dict):
            continue
        if item.get("cr_id") != cr_id or item.get("branch") != branch:
            raise LifecycleError("publish_evidence_mismatch", "publish evidence identity mismatch")
        terminal = str(item.get("terminal") or "")
        tip = str(item.get("remote_after_oid") or "")
        if terminal not in TERMINAL_SUCCESS:
            raise LifecycleError("publish_evidence_mismatch", "publish evidence terminal is not successful")
        tips[str(item.get("repository") or "")] = _validate_oid(tip, "published tip")
    return tips


def plan_merge(
    intent: BranchLifecycleIntent,
    snapshots: tuple[RefSnapshot, ...],
    authorization: OperationAuthorization | None,
    publish_payload: dict[str, Any],
) -> BranchOperationPlan:
    if intent.operation != "merge":
        raise LifecycleError("invalid_operation", "merge planner requires operation=merge")
    tips = _publish_tips(publish_payload, intent.cr_id, intent.branch)
    validate_authorization(authorization, intent, snapshots, "published_oid")
    validate_authorization(authorization, intent, snapshots, "default_oid")
    steps: list[PlanStep] = []
    for snapshot in snapshots:
        tip = tips.get(snapshot.label, "")
        if not tip or snapshot.cr_remote_oid != tip:
            raise LifecycleError("publish_evidence_mismatch", f"{snapshot.label}: fresh CR ref differs from publish evidence")
        if not snapshot.default_remote_oid:
            raise LifecycleError("default_unknown", f"{snapshot.label}: remote default OID unavailable")
        if snapshot.default_remote_oid != tip and not _is_ancestor(
            Path(snapshot.root), snapshot.default_remote_oid, tip
        ):
            raise LifecycleError("non_fast_forward", f"{snapshot.label}: default cannot fast-forward to published tip")
        steps.append(
            PlanStep(
                snapshot.label,
                "remote_mutation",
                ("git", "push", "--porcelain", intent.remote, f"{tip}:refs/heads/{snapshot.default_branch}"),
                snapshot.default_remote_oid,
                tip,
                "matching publish, fresh ancestry, typed default-write authorization",
            )
        )
    return _build_plan(intent, snapshots, steps, authorization, DESTRUCTIVE_ORDER)


def project_merge(attempt_ref: str, outcomes: list[RepoOutcome], required: int) -> PairedMergeProjection:
    exact = (
        len(outcomes) == required
        and all(item.terminal in TERMINAL_SUCCESS for item in outcomes)
        and all(item.after_oid == item.expected_oid for item in outcomes)
    )
    return PairedMergeProjection(
        attempt_ref=attempt_ref,
        repo_terminals={item.repository: item.terminal for item in outcomes},
        paired_complete=exact,
        paired_projection_advanced=exact,
        finish_allowed=exact,
        cr_close_allowed=exact,
    )


def execute_merge(
    plan: BranchOperationPlan, *, runner: GitRunner = _default_runner, attempt_ref: str = ""
) -> BranchOperationAttempt:
    started = _now()
    by_label = {snapshot.label: snapshot for snapshot in plan.snapshots}
    outcomes: list[RepoOutcome] = []
    for label in DESTRUCTIVE_ORDER:
        snapshot = by_label.get(label)
        if snapshot is None:
            continue
        expected = next(step.expected_after_oid for step in plan.steps if step.repository == label)
        if plan.dry_run:
            outcomes.append(
                RepoOutcome(
                    repository=label,
                    terminal="NO_CHANGE",
                    before_oid=snapshot.default_remote_oid,
                    expected_oid=expected,
                    after_oid=snapshot.default_remote_oid,
                    skipped_steps=("push-exact-default-ref",),
                    resume_route="execute-merge-with-current-typed-authorization",
                )
            )
            continue
        root = Path(snapshot.root)
        current_default = remote_ref_oid(root, snapshot.remote, f"refs/heads/{snapshot.default_branch}")
        current_cr = remote_ref_oid(root, snapshot.remote, f"refs/heads/{plan.branch}")
        if current_cr != expected or current_default != snapshot.default_remote_oid:
            outcomes.append(
                RepoOutcome(
                    repository=label,
                    terminal="BLOCKED",
                    before_oid=current_default,
                    expected_oid=expected,
                    after_oid=current_default,
                    error_code="ref_drift",
                    error_summary="fresh remote ref changed after planning",
                    resume_route="fresh-observe-and-create-new-merge-attempt",
                )
            )
            break
        if current_default == expected:
            outcomes.append(
                RepoOutcome(
                    repository=label,
                    terminal="NO_CHANGE",
                    before_oid=current_default,
                    expected_oid=expected,
                    after_oid=current_default,
                    executed_steps=("fresh-query",),
                    skipped_steps=("push-exact-default-ref",),
                    resume_route="none",
                )
            )
            continue
        result = runner(
            ["push", "--porcelain", snapshot.remote, f"{expected}:refs/heads/{snapshot.default_branch}"],
            root,
        )
        after = remote_ref_oid(root, snapshot.remote, f"refs/heads/{snapshot.default_branch}")
        terminal = "PASS" if result.ok and after == expected else "FAILED"
        outcomes.append(
            RepoOutcome(
                repository=label,
                terminal=terminal,
                before_oid=current_default,
                expected_oid=expected,
                after_oid=after,
                mutation=after != current_default,
                executed_steps=("push-exact-default-ref", "post-query"),
                error_code="" if terminal == "PASS" else "remote_policy_rejected",
                error_summary="" if terminal == "PASS" else _bounded_detail(result),
                resume_route="none" if terminal == "PASS" else "fresh-observe-and-resume-merge",
            )
        )
        if terminal != "PASS":
            break
    projection = project_merge(attempt_ref, outcomes, len(plan.snapshots))
    return _attempt(plan, outcomes, started, projection=projection)


def plan_finish(
    intent: BranchLifecycleIntent,
    snapshots: tuple[RefSnapshot, ...],
    authorization: OperationAuthorization | None,
    merge_payload: dict[str, Any],
) -> BranchOperationPlan:
    if intent.operation != "finish":
        raise LifecycleError("invalid_operation", "finish planner requires operation=finish")
    projection = merge_payload.get("paired_projection") or {}
    if not all(
        projection.get(key) is True
        for key in ("paired_complete", "paired_projection_advanced", "finish_allowed")
    ):
        raise LifecycleError("merge_projection_incomplete", "current paired merge projection does not allow finish")
    if intent.branch in PROTECTED_BRANCHES:
        raise LifecycleError("protected_ref", "target branch is protected")
    tips = {
        str(item.get("repository")): str(item.get("expected_oid") or item.get("after_oid") or "")
        for item in merge_payload.get("repo_outcomes") or []
        if isinstance(item, dict)
    }
    validate_authorization(authorization, intent, snapshots, "known_tip", tips)
    validate_authorization(authorization, intent, snapshots, "default_oid")
    steps: list[PlanStep] = []
    for snapshot in snapshots:
        known_tip = _validate_oid(tips.get(snapshot.label, ""), "known merge tip")
        if snapshot.dirty:
            raise LifecycleError("dirty_tree", f"{snapshot.label}: finish requires a clean tree")
        if snapshot.current_branch not in {intent.branch, snapshot.default_branch}:
            raise LifecycleError(
                "wrong_branch",
                f"{snapshot.label}: finish must start on the CR or default branch",
            )
        if snapshot.cr_remote_oid and snapshot.cr_remote_oid != known_tip:
            raise LifecycleError("ref_drift", f"{snapshot.label}: remote CR tip drifted")
        if not snapshot.default_remote_oid or not _is_ancestor(
            Path(snapshot.root), known_tip, snapshot.default_remote_oid
        ):
            raise LifecycleError("ancestry_unproven", f"{snapshot.label}: known tip is not in remote default")
        recovery = f"refs/meta-flow/recovery/{intent.cr_id.lower()}/{snapshot.fingerprint}"
        existing = _local_oid(Path(snapshot.root), recovery)
        if existing and existing != known_tip:
            raise LifecycleError("recovery_ref_collision", f"{snapshot.label}: recovery ref has another OID")
        steps.extend(
            [
                PlanStep(snapshot.label, "local_mutation", ("git", "update-ref", recovery, known_tip), existing, known_tip, "fresh 2/2 finish proof"),
                PlanStep(snapshot.label, "remote_mutation", ("git", "push", "--porcelain", intent.remote, f":refs/heads/{intent.branch}"), snapshot.cr_remote_oid, "", "recovery ref exists and branch is not protected"),
                PlanStep(snapshot.label, "local_mutation", ("git", "switch", "--detach", snapshot.default_remote_oid), snapshot.head_oid, snapshot.default_remote_oid, "2/2 remote CR refs absent"),
                PlanStep(snapshot.label, "local_mutation", ("git", "branch", "-d", intent.branch), snapshot.cr_local_oid, "", "2/2 remote CR refs absent"),
                PlanStep(snapshot.label, "local_mutation", ("git", "switch", snapshot.default_branch), snapshot.default_remote_oid, snapshot.default_local_oid, "local CR branch deleted; do not update local default implicitly"),
            ]
        )
    return _build_plan(intent, snapshots, steps, authorization, DESTRUCTIVE_ORDER)


def execute_finish(
    plan: BranchOperationPlan, *, runner: GitRunner = _default_runner
) -> BranchOperationAttempt:
    started = _now()
    by_label = {snapshot.label: snapshot for snapshot in plan.snapshots}
    outcomes: list[RepoOutcome] = []
    recovery_refs: dict[str, str] = {}
    known_tips: dict[str, str] = {}
    for step in plan.steps:
        if len(step.argv) >= 4 and step.argv[1] == "update-ref":
            known_tips[step.repository] = step.expected_after_oid
            recovery_refs[step.repository] = step.argv[2]
    if plan.dry_run:
        outcomes = [
            RepoOutcome(
                repository=label,
                terminal="NO_CHANGE",
                before_oid=by_label[label].cr_remote_oid,
                expected_oid=known_tips[label],
                after_oid=by_label[label].cr_remote_oid,
                skipped_steps=("create-recovery-ref", "delete-remote-cr-ref", "delete-local-cr-ref"),
                resume_route="execute-finish-with-current-delete-authorization",
            )
            for label in DESTRUCTIVE_ORDER
            if label in by_label
        ]
        return _attempt(plan, outcomes, started, recovery_refs=recovery_refs)
    # Re-prove every repository immediately before the first recovery/delete
    # mutation.  A branch that moved after planning is never deleted.
    for label in DESTRUCTIVE_ORDER:
        snapshot = by_label.get(label)
        if snapshot is None:
            continue
        root = Path(snapshot.root)
        fresh_cr = remote_ref_oid(root, snapshot.remote, f"refs/heads/{plan.branch}")
        fresh_default = remote_ref_oid(
            root, snapshot.remote, f"refs/heads/{snapshot.default_branch}"
        )
        if fresh_cr and fresh_cr != known_tips[label]:
            outcomes.append(
                RepoOutcome(
                    repository=label,
                    terminal="BLOCKED",
                    before_oid=fresh_cr,
                    expected_oid=known_tips[label],
                    after_oid=fresh_cr,
                    error_code="ref_drift",
                    error_summary="remote CR branch moved after finish planning",
                    resume_route="create-new-finish-plan-from-fresh-refs",
                )
            )
            return _attempt(plan, outcomes, started, recovery_refs=recovery_refs)
        if not fresh_default or not _is_ancestor(root, known_tips[label], fresh_default):
            outcomes.append(
                RepoOutcome(
                    repository=label,
                    terminal="BLOCKED",
                    before_oid=fresh_default,
                    expected_oid=known_tips[label],
                    after_oid=fresh_default,
                    error_code="ancestry_unproven",
                    error_summary="fresh remote default no longer proves the known tip",
                    resume_route="restore-proof-or-provide-trusted-receipt",
                )
            )
            return _attempt(plan, outcomes, started, recovery_refs=recovery_refs)
    # Recovery refs for every repository precede any remote deletion.
    for label in DESTRUCTIVE_ORDER:
        snapshot = by_label.get(label)
        if snapshot is None:
            continue
        root = Path(snapshot.root)
        recovery = recovery_refs[label]
        known_tip = known_tips[label]
        existing = _local_oid(root, recovery)
        if not existing:
            result = runner(["update-ref", recovery, known_tip], root)
            if not result.ok:
                outcomes.append(
                    RepoOutcome(
                        repository=label,
                        terminal="FAILED",
                        expected_oid=known_tip,
                        error_code="recovery_ref_failed",
                        error_summary=_bounded_detail(result),
                        resume_route="repair-local-recovery-ref-before-cleanup",
                    )
                )
                return _attempt(plan, outcomes, started, recovery_refs=recovery_refs)
    # Remote deletes use the same artifact -> project order as default updates.
    for label in DESTRUCTIVE_ORDER:
        snapshot = by_label.get(label)
        if snapshot is None:
            continue
        root = Path(snapshot.root)
        current = remote_ref_oid(root, snapshot.remote, f"refs/heads/{plan.branch}")
        current_default = remote_ref_oid(
            root, snapshot.remote, f"refs/heads/{snapshot.default_branch}"
        )
        if current and current != known_tips[label]:
            outcomes.append(
                RepoOutcome(
                    repository=label,
                    terminal="BLOCKED",
                    before_oid=current,
                    expected_oid=known_tips[label],
                    after_oid=current,
                    error_code="ref_drift",
                    error_summary="remote CR branch drifted before delete",
                    resume_route="create-new-finish-plan-from-fresh-refs",
                )
            )
            return _attempt(plan, outcomes, started, recovery_refs=recovery_refs)
        if not current_default or not _is_ancestor(root, known_tips[label], current_default):
            outcomes.append(
                RepoOutcome(
                    repository=label,
                    terminal="BLOCKED",
                    before_oid=current_default,
                    expected_oid=known_tips[label],
                    after_oid=current_default,
                    error_code="ancestry_unproven",
                    error_summary="remote default proof drifted before delete",
                    resume_route="restore-proof-or-provide-trusted-receipt",
                )
            )
            return _attempt(plan, outcomes, started, recovery_refs=recovery_refs)
        if not current:
            outcomes.append(
                RepoOutcome(
                    repository=label,
                    terminal="NO_CHANGE",
                    before_oid="",
                    expected_oid=known_tips[label],
                    after_oid="",
                    executed_steps=("fresh-proof", "recovery-ref-check", "remote-absent-query"),
                    skipped_steps=("delete-remote-cr-ref",),
                    resume_route="continue-paired-remote-cleanup",
                )
            )
            continue
        result = runner(
            ["push", "--porcelain", snapshot.remote, f":refs/heads/{plan.branch}"], root
        )
        after = remote_ref_oid(root, snapshot.remote, f"refs/heads/{plan.branch}")
        terminal = "PASS" if result.ok and not after else "FAILED"
        outcomes.append(
            RepoOutcome(
                repository=label,
                terminal=terminal,
                before_oid=current,
                expected_oid=known_tips[label],
                after_oid=after,
                mutation=bool(current and not after),
                executed_steps=("fresh-proof", "recovery-ref-check", "delete-remote-cr-ref", "post-query"),
                error_code="" if terminal == "PASS" else "remote_policy_rejected",
                error_summary="" if terminal == "PASS" else _bounded_detail(result),
                resume_route="none" if terminal == "PASS" else "fresh-proof-and-resume-finish",
            )
        )
        if terminal != "PASS":
            return _attempt(plan, outcomes, started, recovery_refs=recovery_refs)
    if len(outcomes) != len(plan.snapshots) or not all(
        item.terminal in TERMINAL_SUCCESS for item in outcomes
    ):
        return _attempt(plan, outcomes, started, recovery_refs=recovery_refs)
    # Only after 2/2 remote refs are absent may local CR branches be deleted.
    for snapshot in plan.snapshots:
        root = Path(snapshot.root)
        if not _local_oid(root, f"refs/heads/{plan.branch}"):
            continue
        detach = runner(["switch", "--detach", snapshot.default_remote_oid], root)
        if not detach.ok:
            return _attempt(
                plan,
                [
                    *outcomes,
                    RepoOutcome(
                        repository=snapshot.label,
                        terminal="FAILED",
                        expected_oid=known_tips[snapshot.label],
                        error_code="safe_detach_failed",
                        error_summary=_bounded_detail(detach),
                        resume_route="checkout-a-commit-containing-known-tip-and-resume-local-cleanup",
                    ),
                ],
                started,
                recovery_refs=recovery_refs,
            )
        delete = runner(["branch", "-d", plan.branch], root)
        if not delete.ok:
            return _attempt(
                plan,
                [
                    *outcomes,
                    RepoOutcome(
                        repository=snapshot.label,
                        terminal="FAILED",
                        expected_oid=known_tips[snapshot.label],
                        error_code="local_delete_failed",
                        error_summary=_bounded_detail(delete),
                        resume_route="verify-default-ancestry-and-resume-local-cleanup",
                    ),
                ],
                started,
                recovery_refs=recovery_refs,
            )
        restore = runner(["switch", snapshot.default_branch], root)
        if not restore.ok:
            return _attempt(
                plan,
                [
                    *outcomes,
                    RepoOutcome(
                        repository=snapshot.label,
                        terminal="FAILED",
                        expected_oid=known_tips[snapshot.label],
                        error_code="default_restore_failed",
                        error_summary=_bounded_detail(restore),
                        resume_route="switch-back-to-local-default; recovery-ref-retained",
                    ),
                ],
                started,
                recovery_refs=recovery_refs,
            )
    return _attempt(plan, outcomes, started, recovery_refs=recovery_refs)


def attempt_to_dict(attempt: BranchOperationAttempt) -> dict[str, Any]:
    return asdict(attempt)


def plan_to_dict(plan: BranchOperationPlan) -> dict[str, Any]:
    return asdict(plan)


def write_json_result(path: Path, payload: dict[str, Any]) -> Path:
    """Create an append-only result file; existing evidence is never overwritten."""

    resolved = path.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    try:
        with resolved.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
    except FileExistsError as exc:
        raise LifecycleError("result_exists", f"result already exists: {resolved}") from exc
    return resolved


def _read_payload(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LifecycleError("result_invalid", f"cannot read {label}: {path}") from exc
    if not isinstance(payload, dict):
        raise LifecycleError("result_invalid", f"{label} must be a JSON object")
    return payload


def _snapshots(intent: BranchLifecycleIntent) -> tuple[RefSnapshot, ...]:
    return tuple(
        observe_repo(target, intent.branch, intent.default_branch_override)
        for target in intent.targets
    )


def _print_branch_help() -> None:
    print(
        "usage: meta-flow cr branch-{open|publish|merge|finish} --id CR-050 "
        "[--slug text|--branch ref] [options]\n\n"
        "All actual remote mutations require --authorization. Dry-run never mutates refs.\n"
        "branch-publish consumes committed clean refs only; it never stages or commits.\n"
        "branch-merge additionally requires --publish-result.\n"
        "branch-finish additionally requires --merge-result and performs fresh proof."
    )


def branch_main(command: str, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog=f"meta-flow cr {command}")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--id", dest="cr_id", required=True)
    parser.add_argument("--title", default="")
    parser.add_argument("--scope", default="")
    parser.add_argument("--slug", default="")
    parser.add_argument("--branch", default="")
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--default-branch", default="")
    parser.add_argument("--authorization", type=Path, default=None)
    parser.add_argument("--publish-result", type=Path, default=None)
    parser.add_argument("--merge-result", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parsed = parser.parse_args(argv)
    operation = command.removeprefix("branch-")
    validate_cr_id(parsed.cr_id)
    targets = discover_branch_targets(parsed.project_root.resolve(), parsed.remote)
    branch = parsed.branch or canonical_branch_name(parsed.cr_id, parsed.slug)
    for target in targets:
        validate_branch(branch, root=target.root)
    intent = BranchLifecycleIntent(
        operation=operation,
        cr_id=parsed.cr_id,
        branch=branch,
        targets=targets,
        remote=parsed.remote,
        default_branch_override=parsed.default_branch,
        dry_run=parsed.dry_run,
        authorization_ref=parsed.authorization.as_posix() if parsed.authorization else "",
    )
    snapshots = _snapshots(intent)
    authorization = load_authorization(parsed.authorization) if parsed.authorization else None
    if not parsed.dry_run and parsed.output is None:
        raise LifecycleError("output_required", "actual branch lifecycle operations require --output")
    if operation == "open":
        plan = plan_open(intent, snapshots, authorization)
        if not parsed.dry_run:
            from meta_flow.workflow.cr_lifecycle import discover_formal_crs

            formal_crs = discover_formal_crs(parsed.project_root.resolve())
            if parsed.cr_id not in formal_crs:
                raise LifecycleError(
                    "typed_bootstrap_required",
                    "CR is missing; run typed `meta-flow cr bootstrap` preview/apply before branch-open",
                )

        result: BranchOperationPlan | BranchOperationAttempt = (
            plan if parsed.dry_run else execute_open(plan)
        )
    elif operation == "publish":
        plan = plan_publish(intent, snapshots, authorization)
        result = plan if parsed.dry_run else execute_publish(
            plan, result_ref=parsed.output.as_posix() if parsed.output else ""
        )
    elif operation == "merge":
        if parsed.publish_result is None:
            raise LifecycleError("publish_evidence_missing", "--publish-result is required")
        plan = plan_merge(
            intent, snapshots, authorization, _read_payload(parsed.publish_result, "publish result")
        )
        result = plan if parsed.dry_run else execute_merge(
            plan, attempt_ref=parsed.output.as_posix() if parsed.output else ""
        )
    elif operation == "finish":
        if parsed.merge_result is None:
            raise LifecycleError("merge_result_missing", "--merge-result is required")
        plan = plan_finish(
            intent, snapshots, authorization, _read_payload(parsed.merge_result, "merge result")
        )
        result = plan if parsed.dry_run else execute_finish(plan)
    else:
        _print_branch_help()
        return 2
    payload = plan_to_dict(result) if isinstance(result, BranchOperationPlan) else attempt_to_dict(result)
    if parsed.output:
        write_json_result(parsed.output, payload)
        print(f"wrote: {parsed.output.resolve()}")
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    if isinstance(result, BranchOperationAttempt) and result.overall not in {"PASS", "NO_CHANGE"}:
        return 1
    return 0
