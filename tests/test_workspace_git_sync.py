import subprocess
from pathlib import Path

from meta_flow.workspace.git_sync import (
    probe_common_git_dir,
    probe_head_oid,
    probe_status_porcelain,
    probe_symbolic_head,
    probe_worktree_porcelain,
    push_workspace,
    query_exact_remote_ref,
    workspace_repositories,
)
from meta_flow.workspace.routing import bootstrap_process_workspace


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=True,
    )


def _init_repo(path: Path, remote: Path | None = None) -> None:
    _git(path, "init")
    _git(path, "checkout", "-b", "main")
    _git(path, "config", "user.name", "Meta Flow Test")
    _git(path, "config", "user.email", "meta-flow-test@example.invalid")
    if remote is not None:
        _git(path, "remote", "add", "origin", remote.as_posix())


def _commit_all(path: Path, message: str) -> None:
    _git(path, "add", ".")
    _git(path, "commit", "-m", message)


def _init_bare(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--bare", path.as_posix()], text=True, check=True)


def test_workspace_git_status_reports_project_and_artifact_repositories(tmp_path: Path) -> None:
    project_root = tmp_path / "meta-flow"
    artifact_root = tmp_path / "meta-flow-artifacts"
    project_root.mkdir()
    (project_root / ".gitignore").write_text("/process\n", encoding="utf-8")
    _init_repo(project_root)
    _commit_all(project_root, "init project")

    bootstrap_process_workspace(project_root, artifact_root, "meta-flow")
    _init_repo(artifact_root)
    _commit_all(artifact_root, "init artifacts")
    (artifact_root / "process" / "meta-flow" / "checks" / "CP0.result.json").write_text("{}", encoding="utf-8")

    repos, warnings = workspace_repositories(project_root)
    by_label = {repo.label: repo for repo in repos}

    assert warnings == []
    assert by_label["project"].is_git_repo
    assert by_label["artifact"].is_git_repo
    assert by_label["project"].dirty is False
    assert by_label["artifact"].dirty is True


def test_workspace_push_blocks_dirty_artifact_repository(tmp_path: Path) -> None:
    project_root = tmp_path / "meta-flow"
    artifact_root = tmp_path / "meta-flow-artifacts"
    project_root.mkdir()
    (project_root / ".gitignore").write_text("/process\n", encoding="utf-8")
    _init_repo(project_root)
    _commit_all(project_root, "init project")

    bootstrap_process_workspace(project_root, artifact_root, "meta-flow")
    _init_repo(artifact_root)
    _commit_all(artifact_root, "init artifacts")
    (artifact_root / "process" / "meta-flow" / "checks" / "CP0.result.json").write_text("{}", encoding="utf-8")

    status, lines = push_workspace(project_root, dry_run=True)

    assert status == 1
    assert any("artifact: dirty working tree" in line for line in lines)


def test_workspace_push_dry_run_targets_project_and_artifact_repositories(tmp_path: Path) -> None:
    project_root = tmp_path / "meta-flow"
    artifact_root = tmp_path / "meta-flow-artifacts"
    project_remote = tmp_path / "remotes" / "meta-flow.git"
    artifact_remote = tmp_path / "remotes" / "meta-flow-artifacts.git"
    _init_bare(project_remote)
    _init_bare(artifact_remote)

    project_root.mkdir()
    (project_root / ".gitignore").write_text("/process\n", encoding="utf-8")
    (project_root / "README.md").write_text("project\n", encoding="utf-8")
    _init_repo(project_root, project_remote)
    _commit_all(project_root, "init project")
    _git(project_root, "push", "-u", "origin", "main")

    bootstrap_process_workspace(project_root, artifact_root, "meta-flow")
    _init_repo(artifact_root, artifact_remote)
    _commit_all(artifact_root, "init artifacts")
    _git(artifact_root, "push", "-u", "origin", "main")

    (project_root / "README.md").write_text("project update\n", encoding="utf-8")
    _commit_all(project_root, "project update")
    (artifact_root / "process" / "meta-flow" / "checks" / "CP0.result.json").write_text("{}", encoding="utf-8")
    _commit_all(artifact_root, "artifact update")

    status, lines = push_workspace(project_root, dry_run=True)

    assert status == 0
    assert any("- project: git push --dry-run origin main" in line for line in lines)
    assert any("- artifact: git push --dry-run origin main" in line for line in lines)


def test_exact_remote_ref_distinguishes_present_absent_and_unknown(tmp_path: Path) -> None:
    remote = tmp_path / "remotes" / "project.git"
    project = tmp_path / "project"
    _init_bare(remote)
    project.mkdir()
    _init_repo(project, remote)
    (project / "README.md").write_text("project\n", encoding="utf-8")
    _commit_all(project, "initial")
    _git(project, "push", "origin", "main")

    present = query_exact_remote_ref(project, "origin", "refs/heads/main")
    absent = query_exact_remote_ref(project, "origin", "refs/heads/missing")

    assert present.decision == "PRESENT"
    assert present.oid == _git(project, "rev-parse", "HEAD").stdout.strip()
    assert absent.decision == "ABSENT"
    assert absent.oid == ""


def test_worktree_probes_are_read_only_and_typed(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _init_repo(project)
    (project / "README.md").write_text("project\n", encoding="utf-8")
    _commit_all(project, "initial")
    before = _git(project, "show-ref").stdout

    common = probe_common_git_dir(project)
    head = probe_symbolic_head(project)
    oid = probe_head_oid(project)
    status = probe_status_porcelain(project)
    worktrees = probe_worktree_porcelain(project)

    assert all(probe.decision == "KNOWN" for probe in (common, head, oid, status, worktrees))
    assert head.value == "refs/heads/main"
    assert oid.value == _git(project, "rev-parse", "HEAD").stdout.strip()
    assert status.value == ""
    assert before == _git(project, "show-ref").stdout
