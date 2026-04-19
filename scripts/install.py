#!/usr/bin/env python3
"""
SCOPE-Pack installer.

Installs workflow assets from the canonical delivery directories:
  - agents/
  - skills/
  - rules/
  - skills/<skill-name>/templates/ (private, when present)

Examples:
  python scripts/install.py --platform claude-code
  python scripts/install.py --platform copilot --scope user --content skills
  python scripts/install.py --platform codex --project-dir D:\\work\\demo
  python scripts/install.py --platform openclaw --scope user --agent meta-po
  python scripts/install.py --platform copilot --content rules --dry-run
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


VALID_PLATFORMS = ("copilot", "claude-code", "codex", "openclaw")
VALID_SCOPES = ("project", "user")
VALID_CONTENTS = ("all", "agents", "skills", "rules")
KEBAB_CASE_RE = re.compile(r"^[a-z][a-z0-9-]*$")
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


@dataclass(frozen=True)
class SourceLayout:
    root: Path
    agents_dir: Path
    skills_dir: Path
    rules_dir: Path | None
    agents_rule: Path | None
    copilot_rule: Path | None
    claude_rule: Path | None


def fail(message: str) -> None:
    print(f"[ERROR] {message}", file=sys.stderr)
    raise SystemExit(1)


def parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    items = [item.strip() for item in value.split(",") if item.strip()]
    seen: list[str] = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen


def ensure_kebab_case(items: list[str], kind: str) -> None:
    invalid = [item for item in items if not KEBAB_CASE_RE.fullmatch(item)]
    if invalid:
        fail(f"{kind} 名称必须为 kebab-case: {', '.join(invalid)}")


def find_repo_root(script_path: Path) -> Path:
    return script_path.resolve().parent.parent


def choose_existing(*candidates: Path) -> Path | None:
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def detect_source_layout(root: Path) -> SourceLayout:
    canonical_agents = root / "agents"
    canonical_skills = root / "skills"
    canonical_rules = root / "rules"
    legacy_agents = root / ".agents" / "agents"
    legacy_skills = root / ".agents" / "skills"

    if canonical_agents.is_dir() and canonical_skills.is_dir():
        return SourceLayout(
            root=root,
            agents_dir=canonical_agents,
            skills_dir=canonical_skills,
            rules_dir=canonical_rules if canonical_rules.is_dir() else None,
            agents_rule=choose_existing(canonical_rules / "AGENTS.md", root / "AGENTS.md"),
            copilot_rule=choose_existing(
                canonical_rules / "copilot-instructions.md",
                root / ".github" / "copilot-instructions.md",
            ),
            claude_rule=choose_existing(
                canonical_rules / "CLAUDE.md",
                root / "CLAUDE.md",
                root / ".claude" / "CLAUDE.md",
            ),
        )

    if legacy_agents.is_dir() and legacy_skills.is_dir():
        return SourceLayout(
            root=root,
            agents_dir=legacy_agents,
            skills_dir=legacy_skills,
            rules_dir=canonical_rules if canonical_rules.is_dir() else None,
            agents_rule=choose_existing(root / "AGENTS.md"),
            copilot_rule=choose_existing(root / ".github" / "copilot-instructions.md"),
            claude_rule=choose_existing(root / "CLAUDE.md", root / ".claude" / "CLAUDE.md"),
        )

    fail("无法自动识别源目录。需要存在 agents + skills，或兼容旧结构的 .agents/agents + .agents/skills。")


def list_agent_files(layout: SourceLayout) -> list[Path]:
    return sorted(layout.agents_dir.glob("*.md"))


def list_skill_dirs(layout: SourceLayout) -> list[Path]:
    return sorted(path for path in layout.skills_dir.iterdir() if path.is_dir() and (path / "SKILL.md").is_file())


def select_agent_files(files: list[Path], requested: list[str]) -> list[Path]:
    if not requested:
        return files

    requested_set = set(requested)
    selected = [file_path for file_path in files if file_path.stem in requested_set]
    missing = requested_set - {file_path.stem for file_path in selected}
    if missing:
        fail(f"未找到这些 agent: {', '.join(sorted(missing))}")
    return selected


def select_skill_dirs(skill_dirs: list[Path], requested: list[str]) -> list[Path]:
    if not requested:
        return skill_dirs

    requested_set = set(requested)
    selected = [path for path in skill_dirs if path.name in requested_set]
    missing = requested_set - {path.name for path in selected}
    if missing:
        fail(f"未找到这些 skill: {', '.join(sorted(missing))}")
    return selected


def parse_frontmatter(content: str) -> tuple[dict[str, str], str]:
    match = FRONTMATTER_RE.match(content)
    if not match:
        return {}, content

    fields: dict[str, str] = {}
    for raw_line in match.group(1).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip().strip('"').strip("'")
    body = content[match.end() :].lstrip()
    return fields, body


def yaml_scalar(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def yaml_block(text: str, indent: int = 2) -> str:
    indent_str = " " * indent
    lines = text.splitlines() or [""]
    return "\n".join(f"{indent_str}{line}" for line in lines)


def convert_md_agent_to_codex_yaml(agent_file: Path, agent_name: str) -> str:
    content = agent_file.read_text(encoding="utf-8")
    fields, body = parse_frontmatter(content)
    description = fields.get("description", f"SCOPE-Pack agent {agent_name}")
    version = fields.get("version", "1.0.0")

    return (
        f"name: {yaml_scalar(agent_name)}\n"
        f"description: {yaml_scalar(description)}\n"
        f"version: {yaml_scalar(version)}\n"
        "instructions: |\n"
        f"{yaml_block(body.rstrip(), indent=2)}\n"
    )


def build_openclaw_manifest(agent_entries: list[tuple[str, str]], skill_entries: list[tuple[str, str]]) -> str:
    if not agent_entries:
        agents_text = "agents: []"
    else:
        agent_lines = ["agents:"]
        for name, rel_path in agent_entries:
            agent_lines.append(f"  - name: {yaml_scalar(name)}")
            agent_lines.append(f"    file: {yaml_scalar(rel_path)}")
        agents_text = "\n".join(agent_lines)

    if not skill_entries:
        skills_text = "skills: []"
    else:
        skill_lines = ["skills:"]
        for name, rel_path in skill_entries:
            skill_lines.append(f"  - name: {yaml_scalar(name)}")
            skill_lines.append(f"    file: {yaml_scalar(rel_path)}")
        skills_text = "\n".join(skill_lines)

    return f'version: "1.0"\n{agents_text}\n{skills_text}\n'


def resolve_target_root(platform: str, scope: str, project_dir: Path | None) -> Path:
    if scope == "project":
        if project_dir is None:
            fail("project scope 需要 project_dir")
        return project_dir.resolve()

    home = Path.home()
    user_roots = {
        "copilot": home / ".copilot",
        "claude-code": home / ".claude",
        "codex": home / ".codex",
        "openclaw": home / ".openclaw",
    }
    return user_roots[platform]


def copy_file(src: Path, dest: Path, dry_run: bool, installed: list[Path]) -> None:
    if dry_run:
        print(f"[DryRun] {src} -> {dest}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    installed.append(dest)


def write_text(dest: Path, content: str, dry_run: bool, installed: list[Path]) -> None:
    if dry_run:
        print(f"[DryRun] write -> {dest}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding="utf-8")
    installed.append(dest)


def install_skill_private_templates(
    target_root: Path,
    skill_dir: Path,
    dry_run: bool,
    installed: list[Path],
) -> None:
    private_templates_dir = skill_dir / "templates"
    if not private_templates_dir.is_dir():
        return

    dest_base = target_root / "skills" / skill_dir.name / "templates"
    for src in sorted(private_templates_dir.rglob("*")):
        if src.is_file():
            copy_file(src, dest_base / src.relative_to(private_templates_dir), dry_run, installed)


def install_rules(
    platform: str,
    scope: str,
    target_root: Path,
    layout: SourceLayout,
    dry_run: bool,
    installed: list[Path],
) -> None:
    if scope == "project" and layout.agents_rule:
        copy_file(layout.agents_rule, target_root / "AGENTS.md", dry_run, installed)

    if platform == "copilot" and layout.copilot_rule:
        destination = target_root / ".github" / "copilot-instructions.md" if scope == "project" else target_root / "copilot-instructions.md"
        copy_file(layout.copilot_rule, destination, dry_run, installed)

    if platform == "claude-code" and layout.claude_rule:
        destination = target_root / ".claude" / "CLAUDE.md" if scope == "project" else target_root / "CLAUDE.md"
        copy_file(layout.claude_rule, destination, dry_run, installed)


def install_agents(
    platform: str,
    scope: str,
    target_root: Path,
    agent_files: list[Path],
    dry_run: bool,
    installed: list[Path],
) -> list[tuple[str, str]]:
    manifest_entries: list[tuple[str, str]] = []

    if platform == "copilot":
        base_dir = target_root / ".github" / "agents" if scope == "project" else target_root / "agents"
        for src in agent_files:
            dest = base_dir / f"{src.stem}.agent.md"
            copy_file(src, dest, dry_run, installed)
            rel = dest.relative_to(target_root).as_posix()
            manifest_entries.append((src.stem, rel))
        return manifest_entries

    if platform == "claude-code":
        base_dir = target_root / ".claude" / "agents" if scope == "project" else target_root / "agents"
        for src in agent_files:
            dest = base_dir / src.name
            copy_file(src, dest, dry_run, installed)
            rel = dest.relative_to(target_root).as_posix()
            manifest_entries.append((src.stem, rel))
        return manifest_entries

    if platform == "codex":
        base_dir = target_root / ".codex" / "agents" if scope == "project" else target_root / "agents"
        for src in agent_files:
            dest = base_dir / f"{src.stem}.yaml"
            write_text(dest, convert_md_agent_to_codex_yaml(src, src.stem), dry_run, installed)
            rel = dest.relative_to(target_root).as_posix()
            manifest_entries.append((src.stem, rel))
        return manifest_entries

    base_dir = target_root / ".openclaw" / "agents" if scope == "project" else target_root / "agents"
    for src in agent_files:
        dest = base_dir / src.name
        copy_file(src, dest, dry_run, installed)
        rel = dest.relative_to(target_root).as_posix()
        manifest_entries.append((src.stem, rel))
    return manifest_entries


def install_skills(
    platform: str,
    scope: str,
    target_root: Path,
    skill_dirs: list[Path],
    dry_run: bool,
    installed: list[Path],
) -> list[tuple[str, str]]:
    manifest_entries: list[tuple[str, str]] = []

    if platform == "claude-code":
        base_dir = target_root / ".claude" / "skills" if scope == "project" else target_root / "skills"
        for skill_dir in skill_dirs:
            src = skill_dir / "SKILL.md"
            dest = base_dir / skill_dir.name / "SKILL.md"
            copy_file(src, dest, dry_run, installed)
            install_skill_private_templates(target_root, skill_dir, dry_run, installed)
            rel = dest.relative_to(target_root).as_posix()
            manifest_entries.append((skill_dir.name, rel))
        return manifest_entries

    if platform == "copilot":
        base_dir = target_root / ".github" / "copilot" / "skills" if scope == "project" else target_root / "skills"
    elif platform == "codex":
        base_dir = target_root / ".codex" / "skills" if scope == "project" else target_root / "skills"
    else:
        base_dir = target_root / ".openclaw" / "skills" if scope == "project" else target_root / "skills"

    for skill_dir in skill_dirs:
        src = skill_dir / "SKILL.md"
        dest = base_dir / f"{skill_dir.name}.md"
        copy_file(src, dest, dry_run, installed)
        install_skill_private_templates(target_root, skill_dir, dry_run, installed)
        rel = dest.relative_to(target_root).as_posix()
        manifest_entries.append((skill_dir.name, rel))
    return manifest_entries


def scan_openclaw_entries(target_root: Path, scope: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    base_dir = target_root / ".openclaw" if scope == "project" else target_root
    agent_entries: list[tuple[str, str]] = []
    skill_entries: list[tuple[str, str]] = []

    agents_dir = base_dir / "agents"
    skills_dir = base_dir / "skills"

    if agents_dir.is_dir():
        for file_path in sorted(agents_dir.glob("*.md")):
            agent_entries.append((file_path.stem, file_path.relative_to(base_dir).as_posix()))

    if skills_dir.is_dir():
        for file_path in sorted(skills_dir.glob("*.md")):
            skill_entries.append((file_path.stem, file_path.relative_to(base_dir).as_posix()))

    return agent_entries, skill_entries


def write_openclaw_manifest(
    scope: str,
    target_root: Path,
    agent_entries: list[tuple[str, str]],
    skill_entries: list[tuple[str, str]],
    dry_run: bool,
    installed: list[Path],
) -> None:
    manifest_dest = target_root / ".openclaw" / "manifest.yaml" if scope == "project" else target_root / "manifest.yaml"
    if not dry_run:
        agent_entries, skill_entries = scan_openclaw_entries(target_root, scope)
    write_text(manifest_dest, build_openclaw_manifest(agent_entries, skill_entries), dry_run, installed)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install SCOPE-Pack assets into a platform directory.")
    parser.add_argument("--platform", required=True, choices=VALID_PLATFORMS, help="目标平台")
    parser.add_argument("--scope", default="project", choices=VALID_SCOPES, help="安装范围")
    parser.add_argument("--project-dir", default=".", help="project scope 的目标项目目录，默认当前目录")
    parser.add_argument("--content", default="all", choices=VALID_CONTENTS, help="安装内容")
    parser.add_argument("--agent", default="", help="仅安装指定 agent，逗号分隔")
    parser.add_argument("--skill", default="", help="仅安装指定 skill，逗号分隔")
    parser.add_argument("--dry-run", action="store_true", help="仅打印将执行的安装操作")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    script_root = find_repo_root(Path(__file__))
    layout = detect_source_layout(script_root)

    requested_agents = parse_csv(args.agent)
    requested_skills = parse_csv(args.skill)
    ensure_kebab_case(requested_agents, "agent")
    ensure_kebab_case(requested_skills, "skill")

    target_root = resolve_target_root(
        platform=args.platform,
        scope=args.scope,
        project_dir=Path(args.project_dir) if args.scope == "project" else None,
    )

    install_rules_enabled = args.content in ("all", "rules")
    install_agents_enabled = args.content in ("all", "agents") or bool(requested_agents)
    install_skills_enabled = args.content in ("all", "skills") or bool(requested_skills)

    agent_files = select_agent_files(list_agent_files(layout), requested_agents)
    skill_dirs = select_skill_dirs(list_skill_dirs(layout), requested_skills)

    if install_agents_enabled and not agent_files:
        fail(f"{args.platform} 平台没有可安装的 agent 源文件")
    if install_skills_enabled and not skill_dirs:
        fail(f"{args.platform} 平台没有可安装的 skill 源文件")

    if requested_agents and not install_agents_enabled:
        fail("指定了 --agent，但内容类型未包含 agents")
    if requested_skills and not install_skills_enabled:
        fail("指定了 --skill，但内容类型未包含 skills")

    installed: list[Path] = []

    print(f"Installing for platform: {args.platform}")
    print(f"Scope: {args.scope}")
    print(f"Source root: {layout.root}")
    print(f"Target root: {target_root}")

    if install_rules_enabled:
        install_rules(args.platform, args.scope, target_root, layout, args.dry_run, installed)

    agent_entries: list[tuple[str, str]] = []
    if install_agents_enabled:
        agent_entries = install_agents(
            platform=args.platform,
            scope=args.scope,
            target_root=target_root,
            agent_files=agent_files,
            dry_run=args.dry_run,
            installed=installed,
        )
    skill_entries: list[tuple[str, str]] = []
    if install_skills_enabled:
        skill_entries = install_skills(
            platform=args.platform,
            scope=args.scope,
            target_root=target_root,
            skill_dirs=skill_dirs,
            dry_run=args.dry_run,
            installed=installed,
        )

    if args.platform == "openclaw" and (install_agents_enabled or install_skills_enabled):
        write_openclaw_manifest(args.scope, target_root, agent_entries, skill_entries, args.dry_run, installed)

    if args.dry_run:
        print("Dry run completed.")
        return

    print(f"Installed {len(installed)} file(s).")


if __name__ == "__main__":
    main()
