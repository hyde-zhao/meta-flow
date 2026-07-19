"""Git status and typed command helpers for paired workspace repositories."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from meta_flow.workspace.routing import check_process_route


@dataclass(frozen=True)
class GitRepoStatus:
    label: str
    root: Path
    is_git_repo: bool
    branch: str = ""
    upstream: str = ""
    dirty: bool = False
    ahead: int = 0
    behind: int = 0
    error: str = ""

    @property
    def pushable(self) -> bool:
        return self.is_git_repo and bool(self.branch)


@dataclass(frozen=True)
class GitCommandResult:
    """Bounded subprocess result used by branch-lifecycle planners and executors."""

    argv: tuple[str, ...]
    cwd: Path
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


GitRunner = Callable[[list[str], Path], GitCommandResult]


@dataclass(frozen=True)
class ExactRemoteRefObservation:
    """精确远端 ref 观测；UNKNOWN 与 ABSENT 严格区分。"""

    decision: str
    ref: str
    oid: str
    reason: str
    argv: tuple[str, ...]


@dataclass(frozen=True)
class CreateOnlyRefResult:
    """ordinary create-only push 的 fresh post-observation 结果。"""

    decision: str
    reason: str
    ref: str
    seed_oid: str
    before_oid: str
    after_oid: str
    mutation_count: int
    argv: tuple[str, ...]


@dataclass(frozen=True)
class GitProbe:
    decision: str
    value: str
    reason: str
    argv: tuple[str, ...]


def _default_runner(args: list[str], cwd: Path) -> GitCommandResult:
    return run_git(args, cwd=cwd)


def _validate_remote_and_ref(remote: str, ref: str) -> None:
    if not remote or remote.startswith("-") or any(char in remote for char in "\x00\r\n"):
        raise ValueError("remote must be a non-option token or path")
    if (
        not ref.startswith("refs/heads/")
        or ref.startswith("-")
        or any(char in ref for char in "\x00\r\n ~^:?*[\\")
        or ".." in ref
        or ref.endswith("/")
    ):
        raise ValueError("ref must be one exact safe heads ref")


def query_exact_remote_ref(
    root: Path,
    remote: str,
    ref: str,
    *,
    runner: GitRunner = _default_runner,
) -> ExactRemoteRefObservation:
    """只接受零或一个 exact ``ls-remote --refs`` 结果。"""

    _validate_remote_and_ref(remote, ref)
    args = ["ls-remote", "--refs", remote, ref]
    result = runner(args, root)
    if not result.ok:
        return ExactRemoteRefObservation("UNKNOWN", ref, "", "remote_query_failed", result.argv)
    rows: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        columns = line.split()
        if len(columns) != 2:
            return ExactRemoteRefObservation("UNKNOWN", ref, "", "remote_query_malformed", result.argv)
        rows.append((columns[0], columns[1]))
    exact = [(oid, name) for oid, name in rows if name == ref]
    if len(exact) > 1 or len(exact) != len(rows):
        return ExactRemoteRefObservation("UNKNOWN", ref, "", "remote_query_ambiguous", result.argv)
    if not exact:
        return ExactRemoteRefObservation("ABSENT", ref, "", "exact_ref_absent", result.argv)
    oid = exact[0][0]
    if len(oid) not in {40, 64} or any(char not in "0123456789abcdefABCDEF" for char in oid):
        return ExactRemoteRefObservation("UNKNOWN", ref, "", "remote_oid_invalid", result.argv)
    return ExactRemoteRefObservation("PRESENT", ref, oid.lower(), "exact_ref_present", result.argv)


def create_remote_ref_once(
    root: Path,
    remote: str,
    ref: str,
    seed_oid: str,
    *,
    runner: GitRunner = _default_runner,
) -> CreateOnlyRefResult:
    """从 exact OID 普通创建 ref；existing/race 永不 force、reset 或 delete。"""

    _validate_remote_and_ref(remote, ref)
    if len(seed_oid) not in {40, 64} or any(
        char not in "0123456789abcdefABCDEF" for char in seed_oid
    ):
        raise ValueError("seed_oid must be one full hexadecimal object id")
    seed_oid = seed_oid.lower()
    before = query_exact_remote_ref(root, remote, ref, runner=runner)
    if before.decision == "PRESENT":
        return CreateOnlyRefResult(
            "NO_CHANGE", "existing_ref", ref, seed_oid, before.oid, before.oid, 0, ()
        )
    if before.decision != "ABSENT":
        return CreateOnlyRefResult(
            "BLOCKED", "remote_observation_unknown", ref, seed_oid, "", "", 0, ()
        )
    args = ["push", remote, f"{seed_oid}:{ref}"]
    result = runner(args, root)
    after = query_exact_remote_ref(root, remote, ref, runner=runner)
    if after.decision == "PRESENT" and after.oid == seed_oid:
        reason = "created_exact_oid" if result.ok else "race_same_oid"
        decision = "CREATED" if result.ok else "NO_CHANGE"
        return CreateOnlyRefResult(
            decision, reason, ref, seed_oid, "", after.oid, 1, result.argv
        )
    reason = (
        "remote_race_conflict"
        if after.decision == "PRESENT"
        else "remote_observation_unknown"
    )
    return CreateOnlyRefResult(
        "BLOCKED", reason, ref, seed_oid, "", after.oid, 1, result.argv
    )


def _read_probe(root: Path, args: list[str], runner: GitRunner) -> GitProbe:
    result = runner(args, root)
    if not result.ok:
        return GitProbe("UNKNOWN", "", "git_probe_failed", result.argv)
    return GitProbe("KNOWN", result.stdout.strip(), "git_probe_known", result.argv)


def probe_common_git_dir(root: Path, *, runner: GitRunner = _default_runner) -> GitProbe:
    return _read_probe(root, ["rev-parse", "--git-common-dir"], runner)


def probe_symbolic_head(root: Path, *, runner: GitRunner = _default_runner) -> GitProbe:
    return _read_probe(root, ["symbolic-ref", "-q", "HEAD"], runner)


def probe_head_oid(root: Path, *, runner: GitRunner = _default_runner) -> GitProbe:
    return _read_probe(root, ["rev-parse", "--verify", "HEAD^{commit}"], runner)


def probe_status_porcelain(root: Path, *, runner: GitRunner = _default_runner) -> GitProbe:
    return _read_probe(root, ["status", "--porcelain=v1", "--untracked-files=all"], runner)


def probe_worktree_porcelain(root: Path, *, runner: GitRunner = _default_runner) -> GitProbe:
    return _read_probe(root, ["worktree", "list", "--porcelain"], runner)


def _git(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def run_git(args: list[str], *, cwd: Path, timeout: float = 30.0) -> GitCommandResult:
    """Run Git without a shell and return a stable, typed result.

    Callers must validate ref-like user input before it reaches this helper.  The
    function intentionally does not raise for ordinary Git rejection so a paired
    operation can preserve the first repository's observed outcome.
    """

    argv = ("git", *args)
    try:
        completed = subprocess.run(
            list(argv),
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return GitCommandResult(
            argv=argv,
            cwd=cwd,
            returncode=124,
            stdout=str(exc.stdout or ""),
            stderr="git command timed out",
        )
    return GitCommandResult(
        argv=argv,
        cwd=cwd,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def git_root(path: Path) -> Path | None:
    """Return the resolved repository root, or ``None`` outside a Git worktree."""

    result = run_git(["rev-parse", "--show-toplevel"], cwd=path.resolve())
    if not result.ok:
        return None
    return Path(result.stdout.strip()).resolve()


def git_stdout(args: list[str], *, cwd: Path, timeout: float = 30.0) -> str:
    """Return stripped stdout, raising a concise error for failed read probes."""

    result = run_git(args, cwd=cwd, timeout=timeout)
    if not result.ok:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise ValueError(detail)
    return result.stdout.strip()


def repo_fingerprint(root: Path) -> str:
    """Produce a stable local identity without exposing a remote URL."""

    resolved = root.resolve().as_posix().encode("utf-8")
    return sha256(resolved).hexdigest()[:16]


def remote_ref_oid(root: Path, remote: str, ref: str) -> str:
    """Query one exact remote ref without updating remote-tracking refs."""

    result = run_git(["ls-remote", "--refs", remote, ref], cwd=root)
    if not result.ok:
        detail = result.stderr.strip() or f"exit {result.returncode}"
        raise ValueError(f"remote query failed: {detail}")
    rows = [line.split() for line in result.stdout.splitlines() if line.strip()]
    matches = [row[0] for row in rows if len(row) >= 2 and row[1] == ref]
    if len(matches) > 1:
        raise ValueError(f"remote ref is ambiguous: {ref}")
    return matches[0] if matches else ""


def remote_default_branch(root: Path, remote: str, override: str = "") -> str:
    """Resolve the remote symbolic HEAD, requiring an override when unavailable."""

    if override:
        return override
    result = run_git(["ls-remote", "--symref", remote, "HEAD"], cwd=root)
    if not result.ok:
        detail = result.stderr.strip() or f"exit {result.returncode}"
        raise ValueError(f"remote HEAD query failed: {detail}")
    prefix = "ref: refs/heads/"
    branches = {
        line.split("\t", 1)[0][len(prefix) :]
        for line in result.stdout.splitlines()
        if line.startswith(prefix) and line.endswith("\tHEAD")
    }
    if len(branches) != 1:
        raise ValueError("remote symbolic HEAD is missing or ambiguous; pass --default-branch")
    return next(iter(branches))


def _git_root(path: Path) -> Path | None:
    return git_root(path)


def _rev_count(root: Path, revision_range: str) -> int:
    result = _git(["rev-list", "--count", revision_range], cwd=root)
    if result.returncode != 0:
        return 0
    try:
        return int(result.stdout.strip() or "0")
    except ValueError:
        return 0


def repo_status(label: str, path: Path) -> GitRepoStatus:
    root = _git_root(path.resolve())
    if root is None:
        return GitRepoStatus(label=label, root=path.resolve(), is_git_repo=False, error="not-a-git-repo")

    branch_result = _git(["branch", "--show-current"], cwd=root)
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else ""
    dirty_result = _git(["status", "--short"], cwd=root)
    dirty = bool(dirty_result.stdout.strip()) if dirty_result.returncode == 0 else True

    upstream_result = _git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], cwd=root)
    upstream = upstream_result.stdout.strip() if upstream_result.returncode == 0 else ""
    ahead = _rev_count(root, f"{upstream}..HEAD") if upstream else 0
    behind = _rev_count(root, f"HEAD..{upstream}") if upstream else 0

    error = ""
    if not branch:
        error = "detached-head-or-unknown-branch"
    return GitRepoStatus(
        label=label,
        root=root,
        is_git_repo=True,
        branch=branch,
        upstream=upstream,
        dirty=dirty,
        ahead=ahead,
        behind=behind,
        error=error,
    )


def workspace_repositories(project_root: Path) -> tuple[list[GitRepoStatus], list[str]]:
    health = check_process_route(project_root)
    warnings = list(health.warnings)
    if health.blocking:
        errors = "; ".join(health.errors) or health.status
        return (
            [
                GitRepoStatus(
                    label="workspace-route",
                    root=project_root.resolve(),
                    is_git_repo=False,
                    error=f"process-route-blocking: {errors}",
                )
            ],
            warnings,
        )

    candidates: list[tuple[str, Path]] = [("project", health.project_root)]
    artifact_path = health.artifact_root or health.project_process_root
    if artifact_path is not None:
        candidates.append(("artifact", artifact_path))

    repos: list[GitRepoStatus] = []
    seen_roots: set[Path] = set()
    for label, path in candidates:
        status = repo_status(label, path)
        if status.is_git_repo and status.root in seen_roots:
            warnings.append(f"{label} repo shares git root with another workspace repo: {status.root}")
            continue
        if status.is_git_repo:
            seen_roots.add(status.root)
        repos.append(status)
    return repos, warnings


def format_git_status(repos: list[GitRepoStatus], warnings: list[str]) -> list[str]:
    lines = ["workspace_git_status:"]
    for repo in repos:
        lines.extend(
            [
                f"- {repo.label}:",
                f"  root: {repo.root}",
                f"  is_git_repo: {str(repo.is_git_repo).lower()}",
                f"  branch: {repo.branch or '-'}",
                f"  upstream: {repo.upstream or '-'}",
                f"  dirty: {str(repo.dirty).lower()}",
                f"  ahead: {repo.ahead}",
                f"  behind: {repo.behind}",
            ]
        )
        if repo.error:
            lines.append(f"  error: {repo.error}")
    lines.extend(f"- WARN: {warning}" for warning in warnings)
    return lines


def push_workspace(
    project_root: Path,
    *,
    remote: str = "origin",
    branch: str | None = None,
    dry_run: bool = False,
    allow_dirty: bool = False,
) -> tuple[int, list[str]]:
    repos, warnings = workspace_repositories(project_root)
    lines = format_git_status(repos, warnings)

    problems: list[str] = []
    for repo in repos:
        if not repo.pushable:
            problems.append(f"{repo.label}: {repo.error or 'not-pushable'}")
        if repo.dirty and not allow_dirty:
            problems.append(f"{repo.label}: dirty working tree; commit or stash before workspace push")
    if problems:
        lines.append("workspace_push: BLOCKED")
        lines.extend(f"- ERROR: {problem}" for problem in problems)
        return 1, lines

    lines.append("workspace_push:")
    for repo in repos:
        target_branch = branch or repo.branch
        args = ["push", remote, target_branch]
        if dry_run:
            args.insert(1, "--dry-run")
        result = _git(args, cwd=repo.root)
        lines.append(f"- {repo.label}: git {' '.join(args)}")
        if result.stdout.strip():
            lines.append(f"  stdout: {result.stdout.strip()}")
        if result.stderr.strip():
            lines.append(f"  stderr: {result.stderr.strip()}")
        if result.returncode != 0:
            lines.append(f"  status: FAIL ({result.returncode})")
            return result.returncode, lines
        lines.append("  status: PASS")
    return 0, lines
