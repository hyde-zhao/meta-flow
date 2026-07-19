from __future__ import annotations

import json
import os
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from meta_flow.project.scale import dump_yaml
from meta_flow.repository.cli import commit_main, push_main
from meta_flow.repository.publisher import (
    RepositoryApplyError,
    RepositoryAuthorization,
    apply_commit,
    apply_push,
    execute_push_sequence,
    plan_commit,
    plan_push,
)


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def configure_identity(root: Path) -> None:
    git(root, "config", "user.name", "Meta Flow Test")
    git(root, "config", "user.email", "meta-flow@example.invalid")


def init_remote_pair(root: Path, name: str) -> tuple[Path, Path]:
    bare = root / f"{name}.git"
    bare.mkdir()
    git(bare, "init", "--bare", "--initial-branch=main")
    local = root / name
    local.mkdir()
    git(local, "init", "-b", "main")
    configure_identity(local)
    (local / "README.md").write_text(f"# {name}\n", encoding="utf-8")
    git(local, "add", "README.md")
    git(local, "commit", "-m", "initial")
    git(local, "remote", "add", "origin", str(bare))
    git(local, "push", "-u", "origin", "main")
    return local, bare


def commit_auth(plan, authorization_id: str = "commit-auth") -> RepositoryAuthorization:
    return RepositoryAuthorization(
        authorization_id=authorization_id,
        operation="commit",
        project_id=plan.project_id,
        work_id=plan.work_id,
        repo_role=plan.repo_role,
        plan_digest=plan.plan_digest,
        expected_oid=plan.expected_head_oid,
        expires_at="2099-01-01T00:00:00+00:00",
    )


def push_auth(plan, authorization_id: str) -> RepositoryAuthorization:
    return RepositoryAuthorization(
        authorization_id=authorization_id,
        operation="push",
        project_id=plan.project_id,
        work_id=plan.work_id,
        repo_role=plan.repo_role,
        plan_digest=plan.plan_digest,
        expected_oid=plan.expected_remote_oid,
        expires_at="2099-01-01T00:00:00+00:00",
    )


def make_local_commit(local: Path, path: str, text: str) -> str:
    target = local / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    git(local, "add", "--", path)
    git(local, "commit", "-m", f"update {path}")
    return git(local, "rev-parse", "HEAD")


def test_commit_plan_is_dry_run_and_stages_only_allowlisted_paths(tmp_path: Path) -> None:
    local, _bare = init_remote_pair(tmp_path, "release")
    before = git(local, "rev-parse", "HEAD")
    (local / "README.md").write_text("updated\n", encoding="utf-8")

    plan = plan_commit(
        project_id="demo",
        work_id="W-001",
        repo_role="release",
        repo_root=local,
        allowed_paths=("README.md",),
        message="docs: update readme",
        expected_head_oid=before,
    )

    assert not plan.blocked
    assert plan.as_dict()["mutation_count"] == 0
    assert git(local, "rev-parse", "HEAD") == before
    assert git(local, "diff", "--cached", "--name-only") == ""

    receipt = apply_commit(plan, commit_auth(plan))

    assert receipt.decision == "PASS"
    assert receipt.before_oid == before
    assert receipt.after_oid == git(local, "rev-parse", "HEAD")
    assert receipt.committed_paths == ("README.md",)
    assert git(local, "status", "--porcelain=v1") == ""


def test_commit_plan_blocks_unexpected_or_pre_staged_paths(tmp_path: Path) -> None:
    local, _bare = init_remote_pair(tmp_path, "release")
    before = git(local, "rev-parse", "HEAD")
    (local / "README.md").write_text("updated\n", encoding="utf-8")
    (local / "unexpected.txt").write_text("unexpected\n", encoding="utf-8")
    git(local, "add", "unexpected.txt")

    plan = plan_commit(
        project_id="demo",
        work_id="W-001",
        repo_role="release",
        repo_root=local,
        allowed_paths=("README.md",),
        message="docs: update readme",
        expected_head_oid=before,
    )

    assert plan.blocked
    assert "unexpected_paths" in plan.reason
    assert "unexpected_staged_paths" in plan.reason
    with pytest.raises(ValueError, match="blocked"):
        apply_commit(plan, commit_auth(plan))
    assert git(local, "rev-parse", "HEAD") == before


def test_commit_plan_head_drift_blocks_before_staging(tmp_path: Path) -> None:
    local, _bare = init_remote_pair(tmp_path, "release")
    before = git(local, "rev-parse", "HEAD")
    (local / "README.md").write_text("planned\n", encoding="utf-8")
    plan = plan_commit(
        project_id="demo",
        work_id="W-001",
        repo_role="release",
        repo_root=local,
        allowed_paths=("README.md",),
        message="docs: planned",
        expected_head_oid=before,
    )
    git(local, "add", "README.md")
    git(local, "commit", "-m", "advance")
    (local / "README.md").write_text("second\n", encoding="utf-8")

    with pytest.raises(ValueError, match="stale"):
        apply_commit(plan, commit_auth(plan))

    assert git(local, "diff", "--cached", "--name-only") == ""


def test_push_is_exact_oid_fast_forward_without_force(tmp_path: Path) -> None:
    local, _bare = init_remote_pair(tmp_path, "release")
    expected = git(local, "rev-parse", "origin/main")
    local_oid = make_local_commit(local, "README.md", "next\n")

    plan = plan_push(
        project_id="demo",
        work_id="W-001",
        repo_role="release",
        repo_root=local,
        remote="origin",
        ref="refs/heads/main",
        expected_remote_oid=expected,
    )

    assert not plan.blocked
    assert plan.local_oid == local_oid
    assert plan.argv == ("push", "origin", f"{local_oid}:refs/heads/main")
    assert all("force" not in arg for arg in plan.argv)
    receipt = apply_push(plan, push_auth(plan, "push-release"))
    assert receipt.decision == "PASS"
    assert receipt.before_oid == expected
    assert receipt.after_oid == local_oid
    assert all("force" not in arg for arg in receipt.argv)


def advance_remote(tmp_path: Path, bare: Path, name: str) -> str:
    other = tmp_path / name
    git(tmp_path, "clone", str(bare), str(other))
    configure_identity(other)
    oid = make_local_commit(other, "other.txt", "remote advance\n")
    git(other, "push", "origin", "main")
    return oid


def test_remote_oid_drift_blocks_old_push_plan_without_mutation(tmp_path: Path) -> None:
    local, bare = init_remote_pair(tmp_path, "release")
    expected = git(local, "rev-parse", "origin/main")
    make_local_commit(local, "README.md", "local next\n")
    plan = plan_push(
        project_id="demo",
        work_id="W-001",
        repo_role="release",
        repo_root=local,
        remote="origin",
        ref="refs/heads/main",
        expected_remote_oid=expected,
    )
    advanced = advance_remote(tmp_path, bare, "other-release")

    with pytest.raises(ValueError, match="stale"):
        apply_push(plan, push_auth(plan, "push-release"))

    assert git(bare, "rev-parse", "refs/heads/main") == advanced


def test_push_plan_blocks_dirty_non_ff_and_missing_ref(tmp_path: Path) -> None:
    local, _bare = init_remote_pair(tmp_path, "release")
    expected = git(local, "rev-parse", "origin/main")
    (local / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    dirty = plan_push(
        project_id="demo",
        work_id="W-001",
        repo_role="release",
        repo_root=local,
        remote="origin",
        ref="refs/heads/main",
        expected_remote_oid=expected,
    )
    missing = plan_push(
        project_id="demo",
        work_id="W-001",
        repo_role="release",
        repo_root=local,
        remote="origin",
        ref="refs/heads/new",
        expected_remote_oid="",
    )

    assert dirty.blocked
    assert "dirty_repository" in dirty.reason
    assert missing.blocked
    assert "remote_ref_not_present" in missing.reason


def test_two_repo_sequence_reports_partial_and_never_rolls_back_success(tmp_path: Path) -> None:
    release, release_bare = init_remote_pair(tmp_path, "release")
    process, process_bare = init_remote_pair(tmp_path, "process")
    release_expected = git(release, "rev-parse", "origin/main")
    process_expected = git(process, "rev-parse", "origin/main")
    release_new = make_local_commit(release, "release.txt", "release\n")
    make_local_commit(process, "process.txt", "process\n")
    release_plan = plan_push(
        project_id="demo",
        work_id="W-001",
        repo_role="release",
        repo_root=release,
        remote="origin",
        ref="refs/heads/main",
        expected_remote_oid=release_expected,
    )
    process_plan = plan_push(
        project_id="demo",
        work_id="W-001",
        repo_role="process",
        repo_root=process,
        remote="origin",
        ref="refs/heads/main",
        expected_remote_oid=process_expected,
    )
    process_advanced = advance_remote(tmp_path, process_bare, "other-process")

    result = execute_push_sequence(
        (
            (release_plan, push_auth(release_plan, "push-release")),
            (process_plan, push_auth(process_plan, "push-process")),
        )
    )

    assert result.decision == "PARTIAL"
    assert result.repository_status == {"release": "success", "process": "failed"}
    assert result.rollback_count == 0
    assert git(release_bare, "rev-parse", "refs/heads/main") == release_new
    assert git(process_bare, "rev-parse", "refs/heads/main") == process_advanced


def test_first_push_failure_leaves_second_not_started(tmp_path: Path) -> None:
    release, release_bare = init_remote_pair(tmp_path, "release")
    process, process_bare = init_remote_pair(tmp_path, "process")
    release_expected = git(release, "rev-parse", "origin/main")
    process_expected = git(process, "rev-parse", "origin/main")
    make_local_commit(release, "release.txt", "release\n")
    process_new = make_local_commit(process, "process.txt", "process\n")
    release_plan = plan_push(
        project_id="demo",
        work_id="W-001",
        repo_role="release",
        repo_root=release,
        remote="origin",
        ref="refs/heads/main",
        expected_remote_oid=release_expected,
    )
    process_plan = plan_push(
        project_id="demo",
        work_id="W-001",
        repo_role="process",
        repo_root=process,
        remote="origin",
        ref="refs/heads/main",
        expected_remote_oid=process_expected,
    )
    release_advanced = advance_remote(tmp_path, release_bare, "other-release")

    result = execute_push_sequence(
        (
            (release_plan, push_auth(release_plan, "push-release")),
            (process_plan, push_auth(process_plan, "push-process")),
        )
    )

    assert result.decision == "FAILED"
    assert result.repository_status == {"release": "failed", "process": "not_started"}
    assert git(release_bare, "rev-parse", "refs/heads/main") == release_advanced
    assert git(process_bare, "rev-parse", "refs/heads/main") == process_expected
    assert process_new != process_expected


def test_authorization_cannot_cross_operation_or_plan(tmp_path: Path) -> None:
    local, _bare = init_remote_pair(tmp_path, "release")
    expected = git(local, "rev-parse", "origin/main")
    make_local_commit(local, "README.md", "next\n")
    plan = plan_push(
        project_id="demo",
        work_id="W-001",
        repo_role="release",
        repo_root=local,
        remote="origin",
        ref="refs/heads/main",
        expected_remote_oid=expected,
    )
    wrong = replace(push_auth(plan, "auth"), operation="commit")

    with pytest.raises(ValueError, match="does not match"):
        apply_push(plan, wrong)
    with pytest.raises(ValueError, match="single-use"):
        apply_push(plan, replace(push_auth(plan, "auth"), single_use=1))


def test_push_sequence_requires_nonempty_unique_repository_roles(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least one"):
        execute_push_sequence(())

    local, _bare = init_remote_pair(tmp_path, "release")
    expected = git(local, "rev-parse", "origin/main")
    make_local_commit(local, "README.md", "next\n")
    plan = plan_push(
        project_id="demo",
        work_id="W-001",
        repo_role="release",
        repo_root=local,
        remote="origin",
        ref="refs/heads/main",
        expected_remote_oid=expected,
    )
    with pytest.raises(ValueError, match="unique"):
        execute_push_sequence(
            (
                (plan, push_auth(plan, "push-release-1")),
                (plan, push_auth(plan, "push-release-2")),
            )
        )


def test_repository_cli_is_dry_run_then_requires_exact_authorization(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    local, _bare = init_remote_pair(tmp_path, "release")
    before = git(local, "rev-parse", "HEAD")
    remote_before = git(local, "rev-parse", "origin/main")
    (local / "README.md").write_text("updated\n", encoding="utf-8")
    commit_args = [
        "--project-id",
        "demo",
        "--work-id",
        "W-001",
        "--repo-role",
        "release",
        "--repo-root",
        str(local),
        "--allowed-path",
        "README.md",
        "--message",
        "docs: update",
        "--expected-head-oid",
        before,
    ]

    assert commit_main(commit_args) == 0
    dry_payload = json.loads(capsys.readouterr().out)
    assert dry_payload["decision"] == "READY"
    assert dry_payload["mutation_count"] == 0
    assert git(local, "rev-parse", "HEAD") == before

    commit_plan = plan_commit(
        project_id="demo",
        work_id="W-001",
        repo_role="release",
        repo_root=local,
        allowed_paths=("README.md",),
        message="docs: update",
        expected_head_oid=before,
    )
    commit_auth_path = tmp_path / "commit-auth.yaml"
    commit_auth_path.write_text(
        dump_yaml(commit_auth(commit_plan, "commit-cli").__dict__) + "\n",
        encoding="utf-8",
    )
    assert commit_main([*commit_args, "--apply", "--authorization", str(commit_auth_path)]) == 0
    committed = json.loads(capsys.readouterr().out)
    assert committed["receipt"]["decision"] == "PASS"

    push_plan = plan_push(
        project_id="demo",
        work_id="W-001",
        repo_role="release",
        repo_root=local,
        remote="origin",
        ref="refs/heads/main",
        expected_remote_oid=remote_before,
    )
    push_auth_path = tmp_path / "push-auth.yaml"
    push_auth_path.write_text(
        dump_yaml(push_auth(push_plan, "push-cli").__dict__) + "\n",
        encoding="utf-8",
    )
    push_args = [
        "--project-id",
        "demo",
        "--work-id",
        "W-001",
        "--repo-role",
        "release",
        "--repo-root",
        str(local),
        "--remote",
        "origin",
        "--ref",
        "refs/heads/main",
        "--expected-remote-oid",
        remote_before,
    ]
    assert push_main(push_args) == 0
    assert json.loads(capsys.readouterr().out)["mutation_count"] == 0
    assert push_main([*push_args, "--apply", "--authorization", str(push_auth_path)]) == 0
    pushed = json.loads(capsys.readouterr().out)
    assert pushed["receipt"]["decision"] == "PASS"
    assert git(local, "rev-parse", "origin/main") == git(local, "rev-parse", "HEAD")


def test_commit_hook_failure_returns_partial_receipt_and_preserves_staged_truth(
    tmp_path: Path,
) -> None:
    local, _bare = init_remote_pair(tmp_path, "release")
    before = git(local, "rev-parse", "HEAD")
    (local / "README.md").write_text("updated\n", encoding="utf-8")
    plan = plan_commit(
        project_id="demo",
        work_id="W-001",
        repo_role="release",
        repo_root=local,
        allowed_paths=("README.md",),
        message="docs: update",
        expected_head_oid=before,
    )
    hook = local / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    os.chmod(hook, 0o700)

    with pytest.raises(RepositoryApplyError) as raised:
        apply_commit(plan, commit_auth(plan))

    assert raised.value.receipt.decision == "PARTIAL"
    assert raised.value.receipt.failed_stage == "git_commit"
    assert raised.value.receipt.staged_paths == ("README.md",)
    assert raised.value.receipt.recovery_route.endswith("preserve staged truth")
    assert git(local, "rev-parse", "HEAD") == before
    assert git(local, "diff", "--cached", "--name-only") == "README.md"
