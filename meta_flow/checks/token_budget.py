"""Token and artifact budget checks for Meta Flow workspaces."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

from meta_flow.project.process_route import (
    _resolve_injected_process_ref,
    _resolve_runtime_ref,
)

DEFAULT_BUDGETS = {
    "state_current_max_bytes": 20480,
    "state_md_max_bytes": 12288,
    "context_pack": {
        "CP2": 12000,
        "CP3": 16000,
        "CP5": 22000,
        "CP6": 16000,
        "CP7": 18000,
        "CP8": 14000,
    },
    "artifact_max_bytes": {
        "cr_summary": 4096,
        "story_summary": 4096,
        "compact_decision_brief": 12288,
        "full_lld": 20480,
        "cp_check_lite": 8192,
    },
    "output_profiles": {
        "story_return_summary": {"max_words": 800},
        "cp_summary": {"max_words": 600},
        "decision_brief_compact": {"max_words": 1200},
        "feature_design_summary": {"max_words": 1000},
    },
}

DEFAULT_READ_DENY_PATTERNS = (
    "process/STATE.md",
    "process/DEVELOPMENT-PLAN.yaml",
    "process/STORY-STATUS.md",
    "process/changes/*.md",
    "process/stories/*-LLD.md",
    "process/stories/*-IMPLEMENTATION.md",
    "process/archive/**",
    "process/discussions/**",
)

DEFAULT_SCAN_ROOTS = ("process", "docs", "delivery", "meta_flow", "tests")
SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}
TEXT_SUFFIXES = {
    ".cfg",
    ".css",
    ".html",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".ps1",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}


@dataclass(frozen=True)
class FileBudgetInfo:
    path: Path
    rel_path: str
    byte_count: int
    estimated_tokens: int
    default_read_status: str
    artifact_kind: str
    budget_bytes: int | None

    @property
    def over_budget(self) -> bool:
        return self.budget_bytes is not None and self.byte_count > self.budget_bytes


@dataclass(frozen=True)
class BudgetDisposition:
    row: FileBudgetInfo
    lifecycle_class: str
    read_class: str
    severity: str
    remediation_ref: str
    related_cr: str = ""

    @property
    def blocking(self) -> bool:
        return self.severity == "BLOCKER"


def estimate_tokens(text: str) -> int:
    """Use a stable zero-dependency approximation for token budgeting."""

    return math.ceil(len(text) / 4)


def _as_posix(path: Path) -> str:
    return path.as_posix()


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def load_budgets(project_root: Path, *, process_root: Path | None = None) -> dict:
    budgets = json.loads(json.dumps(DEFAULT_BUDGETS))
    policy_path = (
        _resolve_injected_process_ref(
            process_root, "process/policies/ARTIFACT-BUDGETS.json"
        )
        if process_root is not None
        else _resolve_runtime_ref(
            project_root, "process/policies/ARTIFACT-BUDGETS.json"
        )
    )
    configured = _load_json(policy_path)
    if not configured:
        return budgets
    for key, value in configured.items():
        if isinstance(value, dict) and isinstance(budgets.get(key), dict):
            budgets[key].update(value)
        else:
            budgets[key] = value
    return budgets


def is_text_file(path: Path) -> bool:
    if path.suffix in TEXT_SUFFIXES:
        return True
    if path.name in {"AGENTS.md", "CLAUDE.md", "README", "LICENSE"}:
        return True
    return False


def iter_workspace_files(project_root: Path, scan_roots: tuple[str, ...] = DEFAULT_SCAN_ROOTS) -> list[Path]:
    files: list[Path] = []
    for root_name in scan_roots:
        root = project_root / root_name
        if not root.exists():
            continue
        if root.is_file():
            if is_text_file(root):
                files.append(root)
            continue
        for path in root.rglob("*"):
            if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
                continue
            if path.is_file() and is_text_file(path):
                files.append(path)
    return sorted(files)


def classify_default_read(rel_path: str) -> str:
    for pattern in DEFAULT_READ_DENY_PATTERNS:
        if fnmatch(rel_path, pattern):
            return "DENY_DEFAULT"
    if rel_path.startswith("process/context/"):
        return "ALLOW_CONTEXT"
    if rel_path.startswith("process/changes/summaries/"):
        return "ALLOW_SUMMARY"
    return "READ_IF_NEEDED"


def classify_artifact(rel_path: str) -> str:
    if rel_path == "process/state/STATE.current.json":
        return "state_current"
    if rel_path == "process/STATE.md":
        return "state_md"
    if rel_path.startswith("process/changes/summaries/"):
        return "cr_summary"
    if rel_path.startswith("process/stories/summaries/"):
        return "story_summary"
    if rel_path.startswith("process/checks/"):
        return "cp_check_lite"
    if rel_path.startswith("process/stories/") and rel_path.endswith("-LLD.md"):
        return "full_lld"
    return ""


def budget_for_kind(kind: str, budgets: dict) -> int | None:
    if kind == "state_current":
        return int(budgets.get("state_current_max_bytes", 0) or 0)
    if kind == "state_md":
        return int(budgets.get("state_md_max_bytes", 0) or 0)
    artifact_budgets = budgets.get("artifact_max_bytes", {})
    if kind in artifact_budgets:
        return int(artifact_budgets[kind])
    return None


def scan_workspace(project_root: Path) -> list[FileBudgetInfo]:
    project_root = project_root.resolve()
    budgets = load_budgets(project_root)
    rows: list[FileBudgetInfo] = []
    for path in iter_workspace_files(project_root):
        rel_path = _as_posix(path.relative_to(project_root))
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        kind = classify_artifact(rel_path)
        rows.append(
            FileBudgetInfo(
                path=path,
                rel_path=rel_path,
                byte_count=path.stat().st_size,
                estimated_tokens=estimate_tokens(text),
                default_read_status=classify_default_read(rel_path),
                artifact_kind=kind,
                budget_bytes=budget_for_kind(kind, budgets),
            )
        )
    return rows


def _active_change(project_root: Path) -> str:
    state = _load_json(_resolve_runtime_ref(project_root, "process/state/STATE.current.json"))
    return str(state.get("active_change") or "")


def _related_cr(rel_path: str) -> str:
    match = re.search(r"CR-?(\d{3})", rel_path, flags=re.IGNORECASE)
    if match:
        return f"CR-{match.group(1)}"
    if "ST-EI-" in rel_path:
        return "CR-046"
    return ""


def _remediation_ref(project_root: Path, related_cr: str) -> str:
    if related_cr:
        archive_ref = f"process/archive/{related_cr}/evidence-index.json"
        if _resolve_runtime_ref(project_root, archive_ref).is_file():
            return archive_ref
        summary_ref = f"process/changes/summaries/{related_cr}.summary.json"
        if _resolve_runtime_ref(project_root, summary_ref).is_file():
            return summary_ref
    return "process/policies/LEDGER-RETENTION.yaml"


def classify_over_budget(project_root: Path, row: FileBudgetInfo) -> BudgetDisposition:
    """Classify an over-budget object without rewriting historical evidence."""

    root = project_root.resolve()
    active_change = _active_change(root)
    related_cr = _related_cr(row.rel_path)
    remediation_ref = _remediation_ref(root, related_cr)
    if related_cr and related_cr == active_change:
        return BudgetDisposition(
            row=row,
            lifecycle_class="active",
            read_class="default-required",
            severity="BLOCKER",
            remediation_ref=remediation_ref,
            related_cr=related_cr,
        )
    if related_cr:
        return BudgetDisposition(
            row=row,
            lifecycle_class="closed-or-non-active",
            read_class="reference-only",
            severity="WARN",
            remediation_ref=remediation_ref,
            related_cr=related_cr,
        )
    if re.search(r"(?:^|/)(?:MF-\d+)[.-]", row.rel_path, flags=re.IGNORECASE):
        return BudgetDisposition(
            row=row,
            lifecycle_class="legacy",
            read_class="reference-only",
            severity="WARN",
            remediation_ref=remediation_ref,
        )
    return BudgetDisposition(
        row=row,
        lifecycle_class="unclassified",
        read_class="default-required",
        severity="BLOCKER",
        remediation_ref=remediation_ref,
    )


def classify_over_budget_rows(project_root: Path, rows: list[FileBudgetInfo]) -> list[BudgetDisposition]:
    return [classify_over_budget(project_root, row) for row in rows if row.over_budget]


def format_bytes(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.2f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"


def _print_top_files(rows: list[FileBudgetInfo], *, limit: int) -> None:
    print("Top default-read candidates:")
    default_rows = [row for row in rows if row.default_read_status == "DENY_DEFAULT"]
    for index, row in enumerate(sorted(default_rows, key=lambda item: item.byte_count, reverse=True)[:limit], start=1):
        print(
            f"{index}. {row.rel_path:<42} {format_bytes(row.byte_count):>9} "
            f"~{row.estimated_tokens} tokens   {row.default_read_status}"
        )
    if not default_rows:
        print("- none")


def _print_artifact_budgets(rows: list[FileBudgetInfo]) -> list[FileBudgetInfo]:
    over_budget = [row for row in rows if row.over_budget]
    print("Artifact budgets:")
    budgeted = [row for row in rows if row.budget_bytes is not None]
    if not budgeted:
        print("- no budgeted artifacts found")
        return over_budget
    for row in sorted(budgeted, key=lambda item: (not item.over_budget, item.rel_path)):
        status = "FAIL" if row.over_budget else "OK"
        assert row.budget_bytes is not None
        print(f"- {status:<4} {row.rel_path} ({format_bytes(row.byte_count)} / {format_bytes(row.budget_bytes)})")
    return over_budget


def _print_output_profiles(project_root: Path) -> list[str]:
    budgets = load_budgets(project_root)
    errors: list[str] = []
    profiles = budgets.get("output_profiles", {})
    print("Output profile word budgets:")
    if not isinstance(profiles, dict) or not profiles:
        print("- none")
        return ["output_profiles must be a non-empty object"]
    for name in sorted(profiles):
        profile = profiles[name]
        if not isinstance(profile, dict):
            errors.append(f"output_profiles.{name} must be an object")
            continue
        max_words = profile.get("max_words")
        if not isinstance(max_words, int) or max_words <= 0:
            errors.append(f"output_profiles.{name}.max_words must be a positive integer")
            continue
        print(f"- {name}: {max_words} words")
    return errors


def run_tokens(project_root: Path, *, limit: int) -> int:
    project_root = project_root.resolve()
    rows = scan_workspace(project_root)
    denied_rows = [row for row in rows if row.default_read_status == "DENY_DEFAULT"]
    dispositions = classify_over_budget_rows(project_root, rows)
    blocking = [item for item in dispositions if item.blocking]
    status = "FAIL" if blocking else "OK"
    print(f"Token Doctor: {status}")
    print(f"project_root: {project_root}")
    print(f"scanned_files: {len(rows)}")
    print(f"deny_default_files: {len(denied_rows)}")
    print(f"over_budget_observed: {len(dispositions)}")
    print(f"over_budget_blocking_active_or_default_required: {len(blocking)}")
    print(f"over_budget_unclassified: {sum(item.lifecycle_class == 'unclassified' for item in dispositions)}")
    _print_top_files(rows, limit=limit)
    if dispositions:
        print("Over-budget artifact classifications:")
        for item in sorted(dispositions, key=lambda value: value.row.byte_count, reverse=True):
            row = item.row
            assert row.budget_bytes is not None
            print(
                f"- {item.severity} {row.rel_path}: {format_bytes(row.byte_count)} > "
                f"{format_bytes(row.budget_bytes)}; lifecycle={item.lifecycle_class}; "
                f"read_class={item.read_class}; remediation_ref={item.remediation_ref}"
            )
    return 1 if blocking else 0


def run_artifacts(project_root: Path) -> int:
    project_root = project_root.resolve()
    rows = scan_workspace(project_root)
    print("Artifact Doctor:")
    print(f"project_root: {project_root}")
    over_budget = _print_artifact_budgets(rows)
    dispositions = classify_over_budget_rows(project_root, rows)
    blocking = [item for item in dispositions if item.blocking]
    print(f"over_budget_observed: {len(dispositions)}")
    print(f"over_budget_blocking_active_or_default_required: {len(blocking)}")
    for item in dispositions:
        print(
            f"- {item.severity}: {item.row.rel_path}; lifecycle={item.lifecycle_class}; "
            f"read_class={item.read_class}; remediation_ref={item.remediation_ref}"
        )
    output_errors = _print_output_profiles(project_root)
    if blocking or output_errors:
        for error in output_errors:
            print(f"- ERROR: {error}")
        print("Artifact Doctor: FAIL")
        return 1
    if over_budget:
        print("Artifact Doctor: OK_WITH_WARNINGS")
        return 0
    print("Artifact Doctor: OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow doctor tokens")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--mode", choices=("tokens", "artifacts"), default="tokens")
    args = parser.parse_args(argv)

    if args.mode == "artifacts":
        return run_artifacts(args.project_root)
    return run_tokens(args.project_root, limit=args.limit)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
