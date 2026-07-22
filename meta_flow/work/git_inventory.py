"""Git-index based eight-class scope inventory."""

from __future__ import annotations

import subprocess
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

CLASSES = (
    "tracked_regular",
    "tracked_symlink",
    "prospective_untracked",
    "ignored_generated",
    "missing",
    "submodule",
    "outside_repo",
    "duplicate",
)
MUTATION_CLASSES = {"tracked_regular", "prospective_untracked"}
VALIDATION_CLASSES = {"tracked_symlink", "missing"}
GENERATED_CLASSES = {"ignored_generated"}
FORBIDDEN_CLASSES = {"submodule", "outside_repo", "duplicate"}


@dataclass(frozen=True)
class InventoryCandidate:
    repo: str
    subgate: str
    path: str
    missing_is_validation: bool = False


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )


def _safe_relative_path(value: str) -> PurePosixPath | None:
    if not value or "\\" in value or value.startswith("/"):
        return None
    path = PurePosixPath(value)
    if path.as_posix() != value or any(part in {"", ".", ".."} for part in path.parts):
        return None
    return path


def _tracked_mode(root: Path, path: str) -> str:
    result = _git(root, "ls-files", "--stage", "--", path)
    if result.returncode != 0 or not result.stdout.strip():
        return ""
    line = result.stdout.splitlines()[0]
    return line.split(maxsplit=1)[0]


def classify_candidate(root: Path, candidate: InventoryCandidate) -> str:
    """Classify one candidate from Git facts without changing index/worktree."""

    root = root.resolve()
    relative = _safe_relative_path(candidate.path)
    if relative is None:
        return "outside_repo"
    resolved = (root / Path(relative.as_posix())).resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError:
        return "outside_repo"
    mode = _tracked_mode(root, candidate.path)
    if mode == "120000":
        return "tracked_symlink"
    if mode == "160000":
        return "submodule"
    if mode:
        return "tracked_regular"
    ignored = _git(root, "check-ignore", "-q", "--", candidate.path)
    if ignored.returncode == 0:
        return "ignored_generated"
    if not resolved.exists() and candidate.missing_is_validation:
        return "missing"
    return "prospective_untracked"


def build_inventory(
    repo_roots: Mapping[str, Path],
    candidates: Iterable[InventoryCandidate],
) -> dict[str, Any]:
    """Build deterministic classes and repo/subgate partitions."""

    classes: dict[str, list[str]] = {name: [] for name in CLASSES}
    partitions: dict[str, dict[str, dict[str, list[str]]]] = {}
    seen: set[tuple[str, str]] = set()
    count = 0
    for candidate in candidates:
        count += 1
        key = (candidate.repo, candidate.path)
        logical = f"{candidate.repo}/{candidate.path}"
        if key in seen:
            class_name = "duplicate"
        elif candidate.repo not in repo_roots:
            class_name = "outside_repo"
        else:
            seen.add(key)
            class_name = classify_candidate(repo_roots[candidate.repo], candidate)
        classes[class_name].append(logical)
        partition = partitions.setdefault(candidate.repo, {}).setdefault(
            candidate.subgate,
            {name: [] for name in CLASSES},
        )
        partition[class_name].append(candidate.path)
    execution = {
        "mutation": sorted(path for name in MUTATION_CLASSES for path in classes[name]),
        "validation_only": sorted(path for name in VALIDATION_CLASSES for path in classes[name]),
        "generated_output": sorted(path for name in GENERATED_CLASSES for path in classes[name]),
        "forbidden": sorted(path for name in FORBIDDEN_CLASSES for path in classes[name]),
    }
    return {
        "schema_version": 1,
        "candidate_count": count,
        "classes": classes,
        "partitions": partitions,
        "execution_sets": {key: {"count": len(value), "paths": value} for key, value in execution.items()},
        "remaining": 0,
        "unknown": 0,
    }

def staged_symmetric_difference(root: Path, allowed_paths: Iterable[str]) -> dict[str, Any]:
    """Compare exact staged paths with one frozen allowlist."""

    result = _git(root.resolve(), "diff", "--cached", "--name-only", "--diff-filter=ACDMRTUXB")
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "unable to read staged paths")
    staged = {line for line in result.stdout.splitlines() if line}
    allowed = set(allowed_paths)
    unexpected = sorted(staged - allowed)
    missing = sorted(allowed - staged)
    return {
        "staged": sorted(staged),
        "unexpected": unexpected,
        "missing": missing,
        "symmetric_difference_count": len(unexpected) + len(missing),
        "decision": "PASS" if not unexpected and not missing else "BLOCKED",
    }
