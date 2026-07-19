"""一次只处理一个仓的 allowlist commit 与 exact-OID fast-forward push。"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from meta_flow.project.model import is_safe_ref
from meta_flow.workspace.git_sync import query_exact_remote_ref, run_git

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SAFE_REF_RE = re.compile(r"^refs/heads/[A-Za-z0-9][A-Za-z0-9._/-]{0,200}$")
_OID_RE = re.compile(r"^[0-9a-fA-F]{40}([0-9a-fA-F]{24})?$")


@dataclass(frozen=True)
class RepoObservation:
    root: Path
    branch: str
    head_oid: str
    changed_paths: tuple[str, ...]
    staged_paths: tuple[str, ...]


@dataclass(frozen=True)
class RepositoryAuthorization:
    authorization_id: str
    operation: str
    project_id: str
    work_id: str
    repo_role: str
    plan_digest: str
    expected_oid: str
    expires_at: str
    single_use: bool = True


@dataclass(frozen=True)
class CommitPlan:
    project_id: str
    work_id: str
    repo_role: str
    repo_root: Path
    message: str
    expected_head_oid: str
    changed_paths: tuple[str, ...]
    allowed_paths: tuple[str, ...]
    unexpected_paths: tuple[str, ...]
    decision: str
    reason: str
    plan_digest: str

    @property
    def blocked(self) -> bool:
        return self.decision == "BLOCKED"

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.__dict__,
            "repo_root": str(self.repo_root),
            "changed_paths": list(self.changed_paths),
            "allowed_paths": list(self.allowed_paths),
            "unexpected_paths": list(self.unexpected_paths),
            "mutation_count": 0,
        }


@dataclass(frozen=True)
class CommitReceipt:
    authorization_id: str
    project_id: str
    work_id: str
    repo_role: str
    before_oid: str
    after_oid: str
    committed_paths: tuple[str, ...]
    decision: str
    mutation_count: int


@dataclass(frozen=True)
class PushPlan:
    project_id: str
    work_id: str
    repo_role: str
    repo_root: Path
    remote: str
    ref: str
    local_oid: str
    expected_remote_oid: str
    observed_remote_oid: str
    decision: str
    reason: str
    argv: tuple[str, ...]
    plan_digest: str

    @property
    def blocked(self) -> bool:
        return self.decision == "BLOCKED"

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.__dict__,
            "repo_root": str(self.repo_root),
            "argv": list(self.argv),
            "mutation_count": 0,
        }


@dataclass(frozen=True)
class PushReceipt:
    authorization_id: str
    project_id: str
    work_id: str
    repo_role: str
    remote: str
    ref: str
    before_oid: str
    after_oid: str
    local_oid: str
    decision: str
    mutation_count: int
    argv: tuple[str, ...]


@dataclass(frozen=True)
class PushSequenceResult:
    decision: str
    repository_status: dict[str, str]
    receipts: tuple[PushReceipt, ...]
    errors: dict[str, str]
    rollback_count: int = 0


@dataclass(frozen=True)
class RepositoryFailureReceipt:
    operation: str
    project_id: str
    work_id: str
    repo_role: str
    decision: str
    before_oid: str
    observed_oid: str
    staged_paths: tuple[str, ...]
    mutation_count: int
    failed_stage: str
    error: str
    recovery_route: str


class RepositoryApplyError(ValueError):
    def __init__(self, message: str, receipt: RepositoryFailureReceipt) -> None:
        super().__init__(message)
        self.receipt = receipt


def _git_value(root: Path, args: list[str]) -> str:
    result = run_git(args, cwd=root)
    if not result.ok:
        return ""
    return result.stdout.strip()


def _nul_paths(root: Path, args: list[str]) -> tuple[str, ...]:
    result = run_git(args, cwd=root)
    if not result.ok:
        raise ValueError(result.stderr.strip() or "Git path observation failed")
    paths = [item for item in result.stdout.split("\0") if item]
    for path in paths:
        if not is_safe_ref(path):
            raise ValueError(f"Git reported unsafe path: {path}")
    return tuple(paths)


def observe_repo(root: Path) -> RepoObservation:
    resolved = root.resolve()
    top = _git_value(resolved, ["rev-parse", "--show-toplevel"])
    if not top or Path(top).resolve() != resolved:
        raise ValueError("repository root is missing or nested")
    unstaged = _nul_paths(resolved, ["diff", "--name-only", "-z"])
    staged = _nul_paths(resolved, ["diff", "--cached", "--name-only", "-z"])
    untracked = _nul_paths(resolved, ["ls-files", "--others", "--exclude-standard", "-z"])
    changed = tuple(sorted(set((*unstaged, *staged, *untracked))))
    return RepoObservation(
        root=resolved,
        branch=_git_value(resolved, ["branch", "--show-current"]),
        head_oid=_git_value(resolved, ["rev-parse", "--verify", "HEAD"]),
        changed_paths=changed,
        staged_paths=tuple(sorted(set(staged))),
    )


def _validate_identity(project_id: str, work_id: str, repo_role: str) -> None:
    for label, value in (("project_id", project_id), ("work_id", work_id), ("repo_role", repo_role)):
        if not _ID_RE.fullmatch(value):
            raise ValueError(f"{label} is invalid")


def _validate_paths(paths: Iterable[str]) -> tuple[str, ...]:
    normalized = tuple(sorted(set(paths)))
    if not normalized:
        raise ValueError("allowed_paths must not be empty")
    for path in normalized:
        if not is_safe_ref(path):
            raise ValueError(f"unsafe allowed path: {path}")
    return normalized


def _digest(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def plan_commit(
    *,
    project_id: str,
    work_id: str,
    repo_role: str,
    repo_root: Path,
    allowed_paths: Iterable[str],
    message: str,
    expected_head_oid: str,
) -> CommitPlan:
    _validate_identity(project_id, work_id, repo_role)
    if not _OID_RE.fullmatch(expected_head_oid):
        raise ValueError("expected_head_oid must be one exact full OID")
    if not message.strip() or "\n" in message or "\r" in message:
        raise ValueError("commit message must be one non-empty line")
    allowed = _validate_paths(allowed_paths)
    observation = observe_repo(repo_root)
    unexpected = tuple(path for path in observation.changed_paths if path not in allowed)
    reasons: list[str] = []
    if observation.head_oid != expected_head_oid:
        reasons.append("head_oid_mismatch")
    if not observation.branch:
        reasons.append("detached_head")
    if not observation.changed_paths:
        reasons.append("no_changes")
    if unexpected:
        reasons.append("unexpected_paths")
    if any(path not in allowed for path in observation.staged_paths):
        reasons.append("unexpected_staged_paths")
    decision = "BLOCKED" if reasons else "READY"
    digest_source = {
        "schema_version": 1,
        "project_id": project_id,
        "work_id": work_id,
        "repo_role": repo_role,
        "repo_root": str(observation.root),
        "message": message,
        "expected_head_oid": expected_head_oid,
        "branch": observation.branch,
        "changed_paths": observation.changed_paths,
        "staged_paths": observation.staged_paths,
        "allowed_paths": allowed,
        "unexpected_paths": unexpected,
        "decision": decision,
        "reasons": reasons,
    }
    return CommitPlan(
        project_id=project_id,
        work_id=work_id,
        repo_role=repo_role,
        repo_root=observation.root,
        message=message,
        expected_head_oid=expected_head_oid,
        changed_paths=observation.changed_paths,
        allowed_paths=allowed,
        unexpected_paths=unexpected,
        decision=decision,
        reason=",".join(reasons) if reasons else "ready",
        plan_digest=_digest(digest_source),
    )


def _validate_authorization(
    authorization: RepositoryAuthorization,
    *,
    operation: str,
    project_id: str,
    work_id: str,
    repo_role: str,
    plan_digest: str,
    expected_oid: str,
) -> None:
    _validate_identity(project_id, work_id, repo_role)
    if not _ID_RE.fullmatch(authorization.authorization_id):
        raise ValueError("authorization_id is invalid")
    if authorization.single_use is not True:
        raise ValueError("repository authorization must be single-use")
    if not _OID_RE.fullmatch(authorization.expected_oid):
        raise ValueError("repository authorization expected_oid must be one exact full OID")
    expected = (operation, project_id, work_id, repo_role, plan_digest, expected_oid)
    actual = (
        authorization.operation,
        authorization.project_id,
        authorization.work_id,
        authorization.repo_role,
        authorization.plan_digest,
        authorization.expected_oid,
    )
    if actual != expected:
        raise ValueError("repository authorization does not match operation/plan/OID")
    if not isinstance(authorization.expires_at, str):
        raise ValueError("authorization expires_at is invalid")
    try:
        expiry = datetime.fromisoformat(authorization.expires_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("authorization expires_at is invalid") from exc
    if expiry.tzinfo is None or expiry.astimezone(UTC) <= datetime.now(UTC):
        raise ValueError("repository authorization is expired")


def apply_commit(plan: CommitPlan, authorization: RepositoryAuthorization) -> CommitReceipt:
    if plan.blocked:
        raise ValueError(f"commit plan is blocked: {plan.reason}")
    _validate_authorization(
        authorization,
        operation="commit",
        project_id=plan.project_id,
        work_id=plan.work_id,
        repo_role=plan.repo_role,
        plan_digest=plan.plan_digest,
        expected_oid=plan.expected_head_oid,
    )
    fresh = plan_commit(
        project_id=plan.project_id,
        work_id=plan.work_id,
        repo_role=plan.repo_role,
        repo_root=plan.repo_root,
        allowed_paths=plan.allowed_paths,
        message=plan.message,
        expected_head_oid=plan.expected_head_oid,
    )
    if fresh.plan_digest != plan.plan_digest:
        raise ValueError("commit plan is stale")
    add_result = run_git(["add", "--", *plan.changed_paths], cwd=plan.repo_root)
    if not add_result.ok:
        message = add_result.stderr.strip() or "git add failed"
        after_failure = observe_repo(plan.repo_root)
        raise RepositoryApplyError(
            message,
            RepositoryFailureReceipt(
                operation="commit",
                project_id=plan.project_id,
                work_id=plan.work_id,
                repo_role=plan.repo_role,
                decision="PARTIAL" if after_failure.staged_paths else "FAILED",
                before_oid=plan.expected_head_oid,
                observed_oid=after_failure.head_oid,
                staged_paths=after_failure.staged_paths,
                mutation_count=1 if after_failure.staged_paths else 0,
                failed_stage="git_add",
                error=message,
                recovery_route="inspect-index-and-replan; no automatic reset/rollback",
            ),
        )
    staged = _nul_paths(plan.repo_root, ["diff", "--cached", "--name-only", "-z"])
    if tuple(sorted(staged)) != tuple(sorted(plan.changed_paths)):
        message = "staged paths do not exactly match planned changed paths"
        raise RepositoryApplyError(
            message,
            RepositoryFailureReceipt(
                operation="commit",
                project_id=plan.project_id,
                work_id=plan.work_id,
                repo_role=plan.repo_role,
                decision="PARTIAL",
                before_oid=plan.expected_head_oid,
                observed_oid=observe_repo(plan.repo_root).head_oid,
                staged_paths=staged,
                mutation_count=1,
                failed_stage="staged_path_verification",
                error=message,
                recovery_route="inspect-index-and-replan; no automatic reset/rollback",
            ),
        )
    commit_result = run_git(["commit", "-m", plan.message], cwd=plan.repo_root)
    if not commit_result.ok:
        message = commit_result.stderr.strip() or "git commit failed"
        after_failure = observe_repo(plan.repo_root)
        raise RepositoryApplyError(
            message,
            RepositoryFailureReceipt(
                operation="commit",
                project_id=plan.project_id,
                work_id=plan.work_id,
                repo_role=plan.repo_role,
                decision="PARTIAL",
                before_oid=plan.expected_head_oid,
                observed_oid=after_failure.head_oid,
                staged_paths=after_failure.staged_paths,
                mutation_count=1,
                failed_stage="git_commit",
                error=message,
                recovery_route="fix-commit-precondition-and-replan; preserve staged truth",
            ),
        )
    after = observe_repo(plan.repo_root)
    if not after.head_oid or after.head_oid == plan.expected_head_oid:
        raise ValueError("commit did not create one new HEAD")
    return CommitReceipt(
        authorization_id=authorization.authorization_id,
        project_id=plan.project_id,
        work_id=plan.work_id,
        repo_role=plan.repo_role,
        before_oid=plan.expected_head_oid,
        after_oid=after.head_oid,
        committed_paths=plan.changed_paths,
        decision="PASS",
        mutation_count=1,
    )


def _validate_remote_ref(remote: str, ref: str) -> None:
    if not remote or remote.startswith("-") or any(char in remote for char in "\x00\r\n"):
        raise ValueError("remote is invalid")
    if not _SAFE_REF_RE.fullmatch(ref) or ".." in ref or ref.endswith("/"):
        raise ValueError("ref must be one safe refs/heads ref")


def plan_push(
    *,
    project_id: str,
    work_id: str,
    repo_role: str,
    repo_root: Path,
    remote: str,
    ref: str,
    expected_remote_oid: str,
) -> PushPlan:
    _validate_identity(project_id, work_id, repo_role)
    _validate_remote_ref(remote, ref)
    if expected_remote_oid and not _OID_RE.fullmatch(expected_remote_oid):
        raise ValueError("expected_remote_oid must be one exact full OID")
    observation = observe_repo(repo_root)
    remote_observation = query_exact_remote_ref(observation.root, remote, ref)
    reasons: list[str] = []
    if observation.changed_paths:
        reasons.append("dirty_repository")
    if not observation.head_oid:
        reasons.append("local_head_missing")
    if remote_observation.decision != "PRESENT":
        reasons.append("remote_ref_not_present")
    elif remote_observation.oid != expected_remote_oid:
        reasons.append("expected_remote_oid_mismatch")
    if observation.head_oid and remote_observation.decision == "PRESENT":
        ancestor = run_git(
            ["merge-base", "--is-ancestor", remote_observation.oid, observation.head_oid],
            cwd=observation.root,
        )
        if not ancestor.ok:
            reasons.append("not_fast_forward")
    decision = "BLOCKED" if reasons else "READY"
    argv = ("push", remote, f"{observation.head_oid}:{ref}")
    digest_source = {
        "schema_version": 1,
        "project_id": project_id,
        "work_id": work_id,
        "repo_role": repo_role,
        "repo_root": str(observation.root),
        "remote": remote,
        "ref": ref,
        "local_oid": observation.head_oid,
        "expected_remote_oid": expected_remote_oid,
        "observed_remote_oid": remote_observation.oid,
        "decision": decision,
        "reasons": reasons,
        "argv": argv,
    }
    return PushPlan(
        project_id=project_id,
        work_id=work_id,
        repo_role=repo_role,
        repo_root=observation.root,
        remote=remote,
        ref=ref,
        local_oid=observation.head_oid,
        expected_remote_oid=expected_remote_oid,
        observed_remote_oid=remote_observation.oid,
        decision=decision,
        reason=",".join(reasons) if reasons else "ready",
        argv=argv,
        plan_digest=_digest(digest_source),
    )


def apply_push(plan: PushPlan, authorization: RepositoryAuthorization) -> PushReceipt:
    if plan.blocked:
        raise ValueError(f"push plan is blocked: {plan.reason}")
    _validate_authorization(
        authorization,
        operation="push",
        project_id=plan.project_id,
        work_id=plan.work_id,
        repo_role=plan.repo_role,
        plan_digest=plan.plan_digest,
        expected_oid=plan.expected_remote_oid,
    )
    fresh = plan_push(
        project_id=plan.project_id,
        work_id=plan.work_id,
        repo_role=plan.repo_role,
        repo_root=plan.repo_root,
        remote=plan.remote,
        ref=plan.ref,
        expected_remote_oid=plan.expected_remote_oid,
    )
    if fresh.plan_digest != plan.plan_digest:
        raise ValueError("push plan is stale")
    result = run_git(list(plan.argv), cwd=plan.repo_root)
    after = query_exact_remote_ref(plan.repo_root, plan.remote, plan.ref)
    if not result.ok or after.decision != "PRESENT" or after.oid != plan.local_oid:
        message = result.stderr.strip() or "push did not publish the planned local OID"
        changed = after.decision == "PRESENT" and after.oid != plan.expected_remote_oid
        raise RepositoryApplyError(
            message,
            RepositoryFailureReceipt(
                operation="push",
                project_id=plan.project_id,
                work_id=plan.work_id,
                repo_role=plan.repo_role,
                decision="PARTIAL" if changed else "FAILED",
                before_oid=plan.expected_remote_oid,
                observed_oid=after.oid,
                staged_paths=(),
                mutation_count=1 if changed else 0,
                failed_stage="git_push_or_remote_verification",
                error=message,
                recovery_route="re-observe-remote-and-replan-only-failed-repository",
            ),
        )
    return PushReceipt(
        authorization_id=authorization.authorization_id,
        project_id=plan.project_id,
        work_id=plan.work_id,
        repo_role=plan.repo_role,
        remote=plan.remote,
        ref=plan.ref,
        before_oid=plan.expected_remote_oid,
        after_oid=after.oid,
        local_oid=plan.local_oid,
        decision="PASS",
        mutation_count=1,
        argv=result.argv,
    )


def execute_push_sequence(
    operations: Iterable[tuple[PushPlan, RepositoryAuthorization]],
) -> PushSequenceResult:
    items = tuple(operations)
    if not items:
        raise ValueError("push sequence must contain at least one repository")
    roles = tuple(plan.repo_role for plan, _authorization in items)
    if len(roles) != len(set(roles)):
        raise ValueError("push sequence repo_role values must be unique")
    statuses = {plan.repo_role: "not_started" for plan, _authorization in items}
    receipts: list[PushReceipt] = []
    errors: dict[str, str] = {}
    for plan, authorization in items:
        try:
            receipt = apply_push(plan, authorization)
        except ValueError as exc:
            statuses[plan.repo_role] = "failed"
            errors[plan.repo_role] = str(exc)
            break
        statuses[plan.repo_role] = "success"
        receipts.append(receipt)
    success_count = sum(value == "success" for value in statuses.values())
    if success_count == len(items):
        decision = "PASS"
    elif success_count:
        decision = "PARTIAL"
    else:
        decision = "FAILED"
    return PushSequenceResult(
        decision=decision,
        repository_status=statuses,
        receipts=tuple(receipts),
        errors=errors,
        rollback_count=0,
    )
