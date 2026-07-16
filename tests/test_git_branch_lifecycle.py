from __future__ import annotations

import subprocess
from dataclasses import asdict
from pathlib import Path

import pytest

from meta_flow.workflow.git_branch_lifecycle import (
    BranchLifecycleIntent,
    GitCommandResult,
    LifecycleError,
    OperationAuthorization,
    RepositoryTarget,
    canonical_branch_name,
    execute_finish,
    execute_merge,
    execute_open,
    execute_publish,
    observe_repo,
    plan_finish,
    plan_merge,
    plan_open,
    plan_publish,
    validate_branch,
)
from meta_flow.workspace.git_sync import remote_ref_oid, repo_fingerprint, run_git


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, text=True, capture_output=True, check=False
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return result.stdout.strip()


def _git_ok(cwd: Path, *args: str) -> bool:
    return subprocess.run(
        ["git", *args], cwd=cwd, text=True, capture_output=True, check=False
    ).returncode == 0


def _make_repository(tmp_path: Path, label: str) -> tuple[RepositoryTarget, Path]:
    remote = tmp_path / "remotes" / f"{label}.git"
    worktree = tmp_path / label
    remote.parent.mkdir(parents=True, exist_ok=True)
    _git(tmp_path, "init", "--bare", remote.as_posix())
    worktree.mkdir()
    _git(worktree, "init")
    _git(worktree, "switch", "-c", "main")
    _git(worktree, "config", "user.name", "Meta Flow Test")
    _git(worktree, "config", "user.email", "meta-flow-test@example.invalid")
    (worktree / "README.md").write_text(f"{label}\n", encoding="utf-8")
    _git(worktree, "add", "README.md")
    _git(worktree, "commit", "-m", "initial")
    _git(worktree, "remote", "add", "origin", remote.as_posix())
    _git(worktree, "push", "-u", "origin", "main")
    _git(remote, "symbolic-ref", "HEAD", "refs/heads/main")
    target = RepositoryTarget(
        label=label,
        root=worktree,
        fingerprint=repo_fingerprint(worktree),
        remote="origin",
    )
    return target, remote


def _pair(tmp_path: Path) -> tuple[tuple[RepositoryTarget, ...], dict[str, Path]]:
    project, project_remote = _make_repository(tmp_path, "project")
    artifact, artifact_remote = _make_repository(tmp_path, "artifact")
    return (project, artifact), {"project": project_remote, "artifact": artifact_remote}


def _snapshots(
    targets: tuple[RepositoryTarget, ...], branch: str
) -> tuple:
    return tuple(observe_repo(target, branch) for target in targets)


def _intent(
    operation: str,
    targets: tuple[RepositoryTarget, ...],
    branch: str,
    *,
    dry_run: bool = False,
) -> BranchLifecycleIntent:
    return BranchLifecycleIntent(
        operation=operation,
        cr_id="CR-050",
        branch=branch,
        targets=targets,
        remote="origin",
        dry_run=dry_run,
    )


def _authorization(
    operation: str,
    snapshots: tuple,
    branch: str,
    values: dict[str, dict[str, str]],
) -> OperationAuthorization:
    repositories: dict[str, dict[str, str]] = {}
    for snapshot in snapshots:
        repositories[snapshot.label] = {
            "fingerprint": snapshot.fingerprint,
            "default_branch": snapshot.default_branch,
            **values[snapshot.label],
        }
    return OperationAuthorization(
        authorization_id=f"AUTH-{operation.upper()}-001",
        operation=operation,
        cr_id="CR-050",
        branch=branch,
        remote="origin",
        repository_labels=tuple(repositories),
        expected_oids=repositories,
        issued_by="test-user",
        issued_at="2026-07-16T00:00:00Z",
        expires_at="2099-01-01T00:00:00Z",
    )


def _open_pair(
    targets: tuple[RepositoryTarget, ...], branch: str
) -> tuple:
    snapshots = _snapshots(targets, branch)
    auth = _authorization(
        "open",
        snapshots,
        branch,
        {
            snapshot.label: {"default_oid": snapshot.default_remote_oid}
            for snapshot in snapshots
        },
    )
    plan = plan_open(_intent("open", targets, branch), snapshots, auth)
    result = execute_open(plan)
    assert result.overall == "PASS"
    return result


def _commit_pair(targets: tuple[RepositoryTarget, ...], marker: str) -> None:
    for target in targets:
        path = target.root / f"{marker}.txt"
        path.write_text(f"{target.label}-{marker}\n", encoding="utf-8")
        _git(target.root, "add", path.name)
        _git(target.root, "commit", "-m", f"{marker} {target.label}")


def _publish_pair(targets: tuple[RepositoryTarget, ...], branch: str):
    snapshots = _snapshots(targets, branch)
    auth = _authorization(
        "publish",
        snapshots,
        branch,
        {
            snapshot.label: {"local_oid": snapshot.cr_local_oid}
            for snapshot in snapshots
        },
    )
    plan = plan_publish(_intent("publish", targets, branch), snapshots, auth)
    result = execute_publish(plan, result_ref="publish.json")
    assert result.overall == "PASS"
    assert len(result.publish_evidence) == 2
    return result


def _merge_authorization(snapshots: tuple, branch: str) -> OperationAuthorization:
    return _authorization(
        "merge",
        snapshots,
        branch,
        {
            snapshot.label: {
                "published_oid": snapshot.cr_remote_oid,
                "default_oid": snapshot.default_remote_oid,
            }
            for snapshot in snapshots
        },
    )


def _merge_pair(targets: tuple[RepositoryTarget, ...], branch: str, publish_result):
    snapshots = _snapshots(targets, branch)
    plan = plan_merge(
        _intent("merge", targets, branch),
        snapshots,
        _merge_authorization(snapshots, branch),
        asdict(publish_result),
    )
    result = execute_merge(plan, attempt_ref="merge.json")
    assert result.overall == "PASS"
    assert result.paired_projection is not None
    assert result.paired_projection.finish_allowed is True
    return result


def _finish_authorization(
    snapshots: tuple, branch: str, merge_result
) -> OperationAuthorization:
    known = {item.repository: item.expected_oid for item in merge_result.repo_outcomes}
    return _authorization(
        "finish",
        snapshots,
        branch,
        {
            snapshot.label: {
                "known_tip": known[snapshot.label],
                "default_oid": snapshot.default_remote_oid,
            }
            for snapshot in snapshots
        },
    )


def test_canonical_branch_name_is_predictable_and_valid(tmp_path: Path) -> None:
    target, _ = _make_repository(tmp_path, "project")

    branch = canonical_branch_name("CR-050", "Git Branch Safety")

    assert branch == "cr/cr-050-git-branch-safety"
    assert run_git(["check-ref-format", "--branch", branch], cwd=target.root).ok
    for unsafe in ("foo;bar", "foo$(id)", "--upload-pack=bad", "foo bar", "foo\nbar"):
        with pytest.raises(LifecycleError) as error:
            validate_branch(unsafe, root=target.root)
        assert error.value.code == "invalid_branch"


def test_open_dry_run_is_deterministic_and_has_zero_ref_mutation(tmp_path: Path) -> None:
    targets, remotes = _pair(tmp_path)
    branch = canonical_branch_name("CR-050", "safe-open")
    before_local = {target.label: _git(target.root, "show-ref") for target in targets}
    before_remote = {label: _git(remote, "show-ref") for label, remote in remotes.items()}
    snapshots = _snapshots(targets, branch)
    plan = plan_open(_intent("open", targets, branch, dry_run=True), snapshots, None)

    result = execute_open(plan)

    assert result.overall == "PASS"
    assert all(not outcome.mutation for outcome in result.repo_outcomes)
    assert before_local == {target.label: _git(target.root, "show-ref") for target in targets}
    assert before_remote == {label: _git(remote, "show-ref") for label, remote in remotes.items()}


def test_open_creates_exact_paired_branches_and_upstreams(tmp_path: Path) -> None:
    targets, _ = _pair(tmp_path)
    branch = canonical_branch_name("CR-050", "safe-open")

    _open_pair(targets, branch)

    for target in targets:
        local = _git(target.root, "rev-parse", branch)
        remote = remote_ref_oid(target.root, "origin", f"refs/heads/{branch}")
        default = remote_ref_oid(target.root, "origin", "refs/heads/main")
        assert local == remote == default
        assert _git(target.root, "rev-parse", "--abbrev-ref", "@{u}") == f"origin/{branch}"


def test_open_dirty_repository_blocks_before_ref_mutation(tmp_path: Path) -> None:
    targets, remotes = _pair(tmp_path)
    branch = canonical_branch_name("CR-050", "blocked")
    (targets[1].root / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    before_remote = {label: _git(remote, "show-ref") for label, remote in remotes.items()}
    snapshots = _snapshots(targets, branch)
    auth = _authorization(
        "open",
        snapshots,
        branch,
        {
            snapshot.label: {"default_oid": snapshot.default_remote_oid}
            for snapshot in snapshots
        },
    )

    with pytest.raises(LifecycleError, match="working tree is dirty") as error:
        plan_open(_intent("open", targets, branch), snapshots, auth)

    assert error.value.code == "dirty_tree"
    assert before_remote == {label: _git(remote, "show-ref") for label, remote in remotes.items()}
    assert all(not remote_ref_oid(target.root, "origin", f"refs/heads/{branch}") for target in targets)


def test_open_rechecks_authorized_default_after_fetch_before_creating_refs(
    tmp_path: Path,
) -> None:
    targets, remotes = _pair(tmp_path)
    branch = canonical_branch_name("CR-050", "concurrent-default")
    snapshots = _snapshots(targets, branch)
    auth = _authorization(
        "open",
        snapshots,
        branch,
        {
            snapshot.label: {"default_oid": snapshot.default_remote_oid}
            for snapshot in snapshots
        },
    )
    plan = plan_open(_intent("open", targets, branch), snapshots, auth)
    attacker = tmp_path / "attacker"
    _git(tmp_path, "clone", remotes["project"].as_posix(), attacker.as_posix())
    _git(attacker, "config", "user.name", "Concurrent Writer")
    _git(attacker, "config", "user.email", "concurrent@example.invalid")
    (attacker / "concurrent.txt").write_text("advanced\n", encoding="utf-8")
    _git(attacker, "add", "concurrent.txt")
    _git(attacker, "commit", "-m", "advance default")
    advanced = False

    def advance_after_fetch(args: list[str], cwd: Path) -> GitCommandResult:
        nonlocal advanced
        result = run_git(args, cwd=cwd)
        if cwd.name == "project" and args[:2] == ["fetch", "--prune"] and not advanced:
            _git(attacker, "push", "origin", "main")
            advanced = True
        return result

    result = execute_open(plan, runner=advance_after_fetch)

    assert result.overall == "BLOCKED"
    assert result.repo_outcomes[0].error_code == "ref_drift"
    assert all(not remote_ref_oid(target.root, "origin", f"refs/heads/{branch}") for target in targets)
    assert all(not _git_ok(target.root, "show-ref", "--verify", f"refs/heads/{branch}") for target in targets)


def test_publish_only_pushes_clean_captured_commits(tmp_path: Path) -> None:
    targets, _ = _pair(tmp_path)
    branch = canonical_branch_name("CR-050", "publish")
    _open_pair(targets, branch)
    _commit_pair(targets, "published")

    result = _publish_pair(targets, branch)

    for target in targets:
        assert remote_ref_oid(target.root, "origin", f"refs/heads/{branch}") == _git(
            target.root, "rev-parse", "HEAD"
        )
    assert {item.repository for item in result.publish_evidence} == {"project", "artifact"}


def test_publish_dirty_tree_never_auto_commits(tmp_path: Path) -> None:
    targets, _ = _pair(tmp_path)
    branch = canonical_branch_name("CR-050", "publish-dirty")
    _open_pair(targets, branch)
    _commit_pair(targets, "published")
    before_heads = {target.label: _git(target.root, "rev-parse", "HEAD") for target in targets}
    (targets[0].root / "uncommitted.txt").write_text("do not commit\n", encoding="utf-8")
    snapshots = _snapshots(targets, branch)
    auth = _authorization(
        "publish",
        snapshots,
        branch,
        {
            snapshot.label: {"local_oid": snapshot.cr_local_oid}
            for snapshot in snapshots
        },
    )

    with pytest.raises(LifecycleError) as error:
        plan_publish(_intent("publish", targets, branch), snapshots, auth)

    assert error.value.code == "dirty_tree"
    assert before_heads == {target.label: _git(target.root, "rev-parse", "HEAD") for target in targets}


def test_merge_fast_forwards_artifact_then_project_without_force(tmp_path: Path) -> None:
    targets, _ = _pair(tmp_path)
    branch = canonical_branch_name("CR-050", "merge")
    _open_pair(targets, branch)
    _commit_pair(targets, "published")
    publish_result = _publish_pair(targets, branch)
    calls: list[tuple[str, tuple[str, ...]]] = []

    def recording_runner(args: list[str], cwd: Path) -> GitCommandResult:
        calls.append((cwd.name, tuple(args)))
        return run_git(args, cwd=cwd)

    snapshots = _snapshots(targets, branch)
    plan = plan_merge(
        _intent("merge", targets, branch),
        snapshots,
        _merge_authorization(snapshots, branch),
        asdict(publish_result),
    )
    result = execute_merge(plan, runner=recording_runner, attempt_ref="merge.json")

    assert result.overall == "PASS"
    assert [name for name, _ in calls] == ["artifact", "project"]
    assert all("--force" not in arg and not arg.startswith("+") for _, args in calls for arg in args)
    assert all(args[0] == "push" for _, args in calls)
    for target in targets:
        assert remote_ref_oid(target.root, "origin", "refs/heads/main") == remote_ref_oid(
            target.root, "origin", f"refs/heads/{branch}"
        )


def test_merge_partial_never_advances_paired_projection_and_can_resume(tmp_path: Path) -> None:
    targets, _ = _pair(tmp_path)
    branch = canonical_branch_name("CR-050", "partial")
    _open_pair(targets, branch)
    _commit_pair(targets, "published")
    publish_result = _publish_pair(targets, branch)
    snapshots = _snapshots(targets, branch)
    plan = plan_merge(
        _intent("merge", targets, branch),
        snapshots,
        _merge_authorization(snapshots, branch),
        asdict(publish_result),
    )

    def reject_project(args: list[str], cwd: Path) -> GitCommandResult:
        if cwd.name == "project" and args[0] == "push":
            return GitCommandResult(tuple(["git", *args]), cwd, 1, "", "protected branch")
        return run_git(args, cwd=cwd)

    partial = execute_merge(plan, runner=reject_project, attempt_ref="merge-partial.json")

    assert partial.overall == "PARTIAL"
    assert partial.paired_projection is not None
    assert partial.paired_projection.paired_projection_advanced is False
    assert partial.paired_projection.finish_allowed is False
    assert partial.paired_projection.cr_close_allowed is False
    assert all(remote_ref_oid(target.root, "origin", f"refs/heads/{branch}") for target in targets)

    refreshed = _snapshots(targets, branch)
    resume_plan = plan_merge(
        _intent("merge", targets, branch),
        refreshed,
        _merge_authorization(refreshed, branch),
        asdict(publish_result),
    )
    resumed = execute_merge(resume_plan, attempt_ref="merge-resumed.json")
    assert resumed.overall == "PASS"
    assert resumed.repo_outcomes[0].repository == "artifact"
    assert resumed.repo_outcomes[0].terminal == "NO_CHANGE"
    assert resumed.paired_projection is not None and resumed.paired_projection.finish_allowed


def test_finish_requires_current_projection_and_cleans_artifact_then_project(tmp_path: Path) -> None:
    targets, _ = _pair(tmp_path)
    branch = canonical_branch_name("CR-050", "finish")
    _open_pair(targets, branch)
    _commit_pair(targets, "published")
    publish_result = _publish_pair(targets, branch)
    merge_result = _merge_pair(targets, branch, publish_result)
    snapshots = _snapshots(targets, branch)
    plan = plan_finish(
        _intent("finish", targets, branch),
        snapshots,
        _finish_authorization(snapshots, branch, merge_result),
        asdict(merge_result),
    )
    delete_order: list[str] = []

    def recording_runner(args: list[str], cwd: Path) -> GitCommandResult:
        if args[0] == "push" and args[-1].startswith(":refs/heads/"):
            delete_order.append(cwd.name)
        return run_git(args, cwd=cwd)

    result = execute_finish(plan, runner=recording_runner)

    assert result.overall == "PASS"
    assert delete_order == ["artifact", "project"]
    for target in targets:
        assert not remote_ref_oid(target.root, "origin", f"refs/heads/{branch}")
        assert not _git_ok(target.root, "show-ref", "--verify", f"refs/heads/{branch}")
        recovery = result.recovery_refs[target.label]
        assert _git(target.root, "rev-parse", recovery)
        assert _git(target.root, "branch", "--show-current") == "main"


def test_finish_partial_resume_keeps_local_branches_until_both_remotes_absent(tmp_path: Path) -> None:
    targets, _ = _pair(tmp_path)
    branch = canonical_branch_name("CR-050", "finish-resume")
    _open_pair(targets, branch)
    _commit_pair(targets, "published")
    publish_result = _publish_pair(targets, branch)
    merge_result = _merge_pair(targets, branch, publish_result)
    snapshots = _snapshots(targets, branch)
    plan = plan_finish(
        _intent("finish", targets, branch),
        snapshots,
        _finish_authorization(snapshots, branch, merge_result),
        asdict(merge_result),
    )

    def reject_project_delete(args: list[str], cwd: Path) -> GitCommandResult:
        if cwd.name == "project" and args[0] == "push" and args[-1].startswith(":"):
            return GitCommandResult(tuple(["git", *args]), cwd, 1, "", "delete denied")
        return run_git(args, cwd=cwd)

    partial = execute_finish(plan, runner=reject_project_delete)

    assert partial.overall == "PARTIAL"
    assert not remote_ref_oid(targets[1].root, "origin", f"refs/heads/{branch}")
    assert remote_ref_oid(targets[0].root, "origin", f"refs/heads/{branch}")
    assert all(_git_ok(target.root, "show-ref", "--verify", f"refs/heads/{branch}") for target in targets)

    refreshed = _snapshots(targets, branch)
    resume_plan = plan_finish(
        _intent("finish", targets, branch),
        refreshed,
        _finish_authorization(refreshed, branch, merge_result),
        asdict(merge_result),
    )
    resumed = execute_finish(resume_plan)
    assert resumed.overall == "PASS"
    assert resumed.repo_outcomes[0].repository == "artifact"
    assert resumed.repo_outcomes[0].terminal == "NO_CHANGE"
    assert all(not remote_ref_oid(target.root, "origin", f"refs/heads/{branch}") for target in targets)
    assert all(not _git_ok(target.root, "show-ref", "--verify", f"refs/heads/{branch}") for target in targets)


def test_finish_rejects_incomplete_merge_projection(tmp_path: Path) -> None:
    targets, _ = _pair(tmp_path)
    branch = canonical_branch_name("CR-050", "no-proof")
    _open_pair(targets, branch)
    snapshots = _snapshots(targets, branch)
    payload = {
        "paired_projection": {
            "paired_complete": False,
            "paired_projection_advanced": False,
            "finish_allowed": False,
        },
        "repo_outcomes": [],
    }

    with pytest.raises(LifecycleError) as error:
        plan_finish(_intent("finish", targets, branch), snapshots, None, payload)

    assert error.value.code == "merge_projection_incomplete"


def test_finish_rechecks_cr_tip_after_plan_before_recovery_or_delete(tmp_path: Path) -> None:
    targets, _ = _pair(tmp_path)
    branch = canonical_branch_name("CR-050", "finish-drift")
    _open_pair(targets, branch)
    _commit_pair(targets, "published")
    publish_result = _publish_pair(targets, branch)
    merge_result = _merge_pair(targets, branch, publish_result)
    snapshots = _snapshots(targets, branch)
    plan = plan_finish(
        _intent("finish", targets, branch),
        snapshots,
        _finish_authorization(snapshots, branch, merge_result),
        asdict(merge_result),
    )
    (targets[0].root / "drift.txt").write_text("drift\n", encoding="utf-8")
    _git(targets[0].root, "add", "drift.txt")
    _git(targets[0].root, "commit", "-m", "drift CR tip")
    _git(targets[0].root, "push", "origin", branch)

    result = execute_finish(plan)

    assert result.overall == "BLOCKED"
    assert result.repo_outcomes[0].error_code == "ref_drift"
    assert all(remote_ref_oid(target.root, "origin", f"refs/heads/{branch}") for target in targets)
    assert all(
        not _git_ok(
            target.root,
            "show-ref",
            "--verify",
            f"refs/meta-flow/recovery/cr-050/{target.fingerprint}",
        )
        for target in targets
    )
