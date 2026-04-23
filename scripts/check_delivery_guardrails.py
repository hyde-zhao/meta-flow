#!/usr/bin/env python3
"""Check repository guardrails for delivery asset ownership and Python cache hygiene."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DELIVERY_ROOT = ROOT / "delivery"
ALLOWED_DELIVERY_DIRS = {".github", "agents", "doc", "rules", "scripts", "skills"}
ALLOWED_DELIVERY_SCRIPT_FILES = {"install.py", "install.sh", "install.ps1"}
FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)
SKILL_ROOT_ASSET_REF_RE = re.compile(r"<skill-root>/(?P<kind>templates|scripts)/(?P<path>[A-Za-z0-9_./-]+)")
TEMPLATE_REF_RE = re.compile(r"(?<![A-Za-z0-9_./-])templates/(?P<path>[A-Za-z0-9_./-]+)")
DELIVERY_SCRIPT_REF_RE = re.compile(r"delivery/scripts/(?P<name>[A-Za-z0-9_.-]+)")


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


def collect_errors() -> list[str]:
    errors: list[str] = []

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
