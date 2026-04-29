#!/usr/bin/env python3
"""Check repository guardrails for delivery asset ownership and Python cache hygiene."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DELIVERY_ROOT = ROOT / "delivery"
PROCESS_ROOT = ROOT / "process"
CHANGE_ROOT = PROCESS_ROOT / "changes"
PLATFORM_CONTRACTS = DELIVERY_ROOT / "doc" / "PLATFORM-CONTRACTS.yaml"
ALLOWED_DELIVERY_DIRS = {"agents", "doc", "rules", "scripts", "skills"}
ALLOWED_DELIVERY_SCRIPT_FILES = {"install.py", "install.sh", "install.ps1"}
REVISION_RECORD_TARGETS = {
    "process/USE-CASES.md": PROCESS_ROOT / "USE-CASES.md",
    "process/REQUIREMENTS.md": PROCESS_ROOT / "REQUIREMENTS.md",
}
FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)
SKILL_ROOT_ASSET_REF_RE = re.compile(r"<skill-root>/(?P<kind>templates|scripts)/(?P<path>[A-Za-z0-9_./-]+)")
TEMPLATE_REF_RE = re.compile(r"(?<![A-Za-z0-9_./-])templates/(?P<path>[A-Za-z0-9_./-]+)")
DELIVERY_SCRIPT_REF_RE = re.compile(r"delivery/scripts/(?P<name>[A-Za-z0-9_.-]+)")


def load_platform_contracts(errors: list[str]) -> dict[str, object]:
    if not PLATFORM_CONTRACTS.is_file():
        errors.append(f"missing platform contract source: {PLATFORM_CONTRACTS.relative_to(ROOT)}")
        return {}
    try:
        return json.loads(PLATFORM_CONTRACTS.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"platform contract must be JSON-compatible YAML: {PLATFORM_CONTRACTS.relative_to(ROOT)} -> {exc}")
        return {}


def collect_platform_contract_errors(payload: dict[str, object]) -> list[str]:
    errors: list[str] = []
    try:
        codex = payload["contracts"]["codex"]  # type: ignore[index]
        project = codex["scopes"]["project"]  # type: ignore[index]
        user = codex["scopes"]["user"]  # type: ignore[index]
        forbidden_project = codex["forbidden"]["project"]  # type: ignore[index]
        forbidden_user = codex["forbidden"]["user"]  # type: ignore[index]
    except (AttributeError, KeyError, TypeError):
        return ["platform contract missing codex scopes/forbidden entries"]

    expected = {
        "codex project agents": (project.get("agents"), ".codex/agents"),
        "codex project skills": (project.get("skills"), ".agents/skills"),
        "codex user agents": (user.get("agents"), "~/.codex/agents"),
        "codex user skills": (user.get("skills"), "~/.agents/skills"),
    }
    for label, (actual, required) in expected.items():
        if actual != required:
            errors.append(f"platform contract mismatch: {label} must be {required}, got {actual}")

    if ".codex/skills" not in forbidden_project:
        errors.append("platform contract must forbid codex project .codex/skills")
    if "~/.codex/skills" not in forbidden_user:
        errors.append("platform contract must forbid codex user ~/.codex/skills")
    return errors


def collect_codex_dry_run_errors(payload: dict[str, object]) -> list[str]:
    errors: list[str] = []
    install_script = DELIVERY_ROOT / "scripts" / "install.py"
    if not install_script.is_file():
        return [f"missing installer: {install_script.relative_to(ROOT)}"]

    with tempfile.TemporaryDirectory(prefix="scope-pack-guardrail-") as tmp:
        project_root = Path(tmp)
        cases = [
            ("project", project_root / ".agents" / "skills" / "context-handoff" / "SKILL.md", ".codex/skills"),
            ("user", Path.home() / ".agents" / "skills" / "context-handoff" / "SKILL.md", str(Path.home() / ".codex" / "skills")),
        ]
        for scope, required_path, forbidden_path in cases:
            result = subprocess.run(
                [
                    sys.executable,
                    str(install_script),
                    "--platform",
                    "codex",
                    "--scope",
                    scope,
                    "--project-dir",
                    str(project_root),
                    "--content",
                    "skills",
                    "--skill",
                    "context-handoff",
                    "--dry-run",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            output = result.stdout + result.stderr
            if result.returncode != 0:
                errors.append(f"codex {scope} dry-run failed with exit {result.returncode}: {output.strip()}")
                continue
            if str(required_path) not in output:
                errors.append(f"codex {scope} dry-run missing required skill path: {required_path}")
            if forbidden_path in output or ".codex/skills" in output:
                errors.append(f"codex {scope} dry-run must not target forbidden skill path: {forbidden_path}")

        conflict_root = project_root / "path-conflict"
        conflict_root.mkdir()
        blocker = conflict_root / ".codex"
        blocker.write_text("file occupying a directory path\n", encoding="utf-8")
        conflict_result = subprocess.run(
            [
                sys.executable,
                str(install_script),
                "--platform",
                "codex",
                "--scope",
                "project",
                "--project-dir",
                str(conflict_root),
                "--content",
                "agents",
                "--agent",
                "meta-po",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        conflict_output = conflict_result.stdout + conflict_result.stderr
        if conflict_result.returncode == 0:
            errors.append("codex project install must fail when .codex is a file")
        if "安装路径被非目录占用:" not in conflict_output or str(blocker) not in conflict_output:
            errors.append("codex path conflict must report a clear occupied-path error")
        if "Traceback" in conflict_output or "NotADirectoryError" in conflict_output:
            errors.append("codex path conflict must not expose a Python traceback")

    contract_errors = collect_platform_contract_errors(payload)
    errors.extend(contract_errors)
    return errors


def parse_frontmatter(content: str) -> dict[str, str]:
    match = FRONTMATTER_RE.match(content)
    if not match:
        return {}
    result: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def collect_git_changed_paths() -> set[str]:
    targets = list(REVISION_RECORD_TARGETS)
    result = subprocess.run(
        ["git", "diff", "--name-only", "--", *targets],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def has_revision_record(content: str) -> bool:
    return "## 修订记录" in content


def cr_marks_document_changed(cr_path: Path, rel_path: str) -> bool:
    doc_name = Path(rel_path).name
    text = cr_path.read_text(encoding="utf-8")
    for line in text.splitlines():
        normalized = line.replace("`", "")
        if rel_path not in normalized and doc_name not in normalized:
            continue
        if re.search(r"\|\s*false\s*\|", normalized):
            continue
        if re.search(r"\|\s*true\s*\|", normalized) or any(
            word in normalized for word in ("原文档更新", "新增", "修改", "更新", "重定义", "删除", "归档")
        ):
            return True
    return False


def collect_revision_record_errors() -> list[str]:
    errors: list[str] = []
    changed_paths = collect_git_changed_paths()
    cr_paths = sorted(CHANGE_ROOT.glob("CR-*.md")) if CHANGE_ROOT.is_dir() else []

    for rel_path, abs_path in REVISION_RECORD_TARGETS.items():
        if not abs_path.is_file():
            continue

        changed_now = rel_path in changed_paths
        changed_by_cr = any(cr_marks_document_changed(cr_path, rel_path) for cr_path in cr_paths)
        if not changed_now and not changed_by_cr:
            continue

        content = abs_path.read_text(encoding="utf-8")
        if not has_revision_record(content):
            errors.append(f"{rel_path} changed under CR flow but is missing required '## 修订记录'")

    return errors


def collect_errors() -> list[str]:
    errors: list[str] = []
    platform_contracts = load_platform_contracts(errors)
    if platform_contracts:
        errors.extend(collect_codex_dry_run_errors(platform_contracts))
    errors.extend(collect_revision_record_errors())

    for child in sorted(path for path in DELIVERY_ROOT.iterdir() if path.is_dir()):
        if child.name not in ALLOWED_DELIVERY_DIRS:
            errors.append(f"delivery top-level directory not allowed: {child.relative_to(ROOT)}")

    for path in ROOT.rglob("__pycache__"):
        if path.is_dir():
            errors.append(f"python cache directory must not exist: {path.relative_to(ROOT)}")
    for path in ROOT.rglob("*.pyc"):
        if path.is_file():
            errors.append(f"python bytecode file must not exist: {path.relative_to(ROOT)}")

    delivery_scripts = DELIVERY_ROOT / "scripts"
    for path in sorted(delivery_scripts.glob("*")):
        if path.is_file() and path.name not in ALLOWED_DELIVERY_SCRIPT_FILES:
            errors.append(f"delivery/scripts only allows install entrypoints: {path.relative_to(ROOT)}")

    for path in DELIVERY_ROOT.rglob("*"):
        if not path.is_dir():
            continue
        rel = path.relative_to(DELIVERY_ROOT)
        if path.name == "templates" and (len(rel.parts) != 3 or rel.parts[0] != "skills"):
            errors.append(f"templates directory must live under delivery/skills/<skill>/templates: {path.relative_to(ROOT)}")
        if path.name == "scripts" and rel.parts[:1] != ("scripts",):
            if len(rel.parts) != 3 or rel.parts[0] != "skills":
                errors.append(f"scripts directory must live under delivery/skills/<skill>/scripts or delivery/scripts: {path.relative_to(ROOT)}")

    skills_root = DELIVERY_ROOT / "skills"
    for skill_dir in sorted(path for path in skills_root.iterdir() if path.is_dir()):
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.is_file():
            continue
        content = skill_file.read_text(encoding="utf-8")
        fields = parse_frontmatter(content)
        if fields.get("status") != "active":
            continue

        for match in DELIVERY_SCRIPT_REF_RE.finditer(content):
            if match.group("name") not in ALLOWED_DELIVERY_SCRIPT_FILES:
                errors.append(
                    f"active skill must not reference non-installer delivery/scripts assets: {skill_file.relative_to(ROOT)} -> {match.group('name')}"
                )
        if "delivery/review-templates" in content:
            errors.append(f"active skill must not reference shared review template directories: {skill_file.relative_to(ROOT)}")
        if re.search(r"\bpython\s+scripts/", content):
            errors.append(f"active skill must not use cwd-dependent 'python scripts/...' entrypoints: {skill_file.relative_to(ROOT)}")

        for match in SKILL_ROOT_ASSET_REF_RE.finditer(content):
            rel_path = Path(match.group("kind")) / match.group("path")
            if not (skill_dir / rel_path).exists():
                errors.append(f"active skill references missing asset: {skill_file.relative_to(ROOT)} -> {rel_path.as_posix()}")

        for match in TEMPLATE_REF_RE.finditer(content):
            rel_path = Path("templates") / match.group("path")
            if not (skill_dir / rel_path).exists():
                errors.append(f"active skill references missing asset: {skill_file.relative_to(ROOT)} -> {rel_path.as_posix()}")

    gitignore = ROOT / ".gitignore"
    if gitignore.is_file():
        text = gitignore.read_text(encoding="utf-8")
        for required in ("__pycache__/", "*.pyc"):
            if required not in text:
                errors.append(f".gitignore missing python cache rule: {required}")

    return errors


def main() -> int:
    errors = collect_errors()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
