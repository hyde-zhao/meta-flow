#!/usr/bin/env python3
"""
SCOPE-Pack installer.

Installs workflow assets from the canonical delivery directories:
  - agents/
  - skills/
  - rules/

Examples:
  uv run --python 3.11 python scripts/install.py --platform claude-code
  uv run --python 3.11 python scripts/install.py --platform codex --scope user
  uv run --python 3.11 python scripts/install.py --platform codex --project-dir D:\\work\\demo
  uv run --python 3.11 python scripts/install.py --platform claude-code --dry-run
  uv run --python 3.11 python scripts/install.py --platform codex --scope user --uninstall
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


VALID_PLATFORMS = ("copilot", "claude-code", "codex", "openclaw")
VALID_SCOPES = ("project", "user")
VALID_CONTENTS = ("all", "agents", "skills", "rules")
KEBAB_CASE_RE = re.compile(r"^[a-z][a-z0-9-]{2,39}$")
FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)
BUILT_IN_CODEX_AGENTS = {"default", "worker", "explorer"}
MANAGED_VERSION = "1.0.0"


@dataclass(frozen=True)
class SourceLayout:
    root: Path
    canonical_agents_dir: Path
    canonical_skills_dir: Path
    copilot_agents_dir: Path | None
    agents_rule: Path | None
    copilot_rule: Path | None
    claude_rule: Path | None


@dataclass(frozen=True)
class AgentDefinition:
    source: Path
    name: str
    description: str
    instructions: str
    model: str | None
    extra_fields: tuple[str, ...]


@dataclass
class Transaction:
    original_text: dict[Path, str | None] = field(default_factory=dict)
    removed_dirs: dict[Path, list[tuple[Path, bytes]]] = field(default_factory=dict)


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
        fail(f"{kind} 名称必须为 kebab-case 且长度为 3-40: {', '.join(invalid)}")


def script_repo_root(script_path: Path) -> Path:
    return script_path.resolve().parent.parent


def find_git_repo_root(start: Path) -> Path | None:
    current = start.resolve()
    for candidate in (current, *current.parents):
        git_dir = candidate / ".git"
        if git_dir.is_dir() or git_dir.is_file():
            return candidate
    return None


def choose_existing(*candidates: Path) -> Path | None:
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def detect_source_layout(root: Path) -> SourceLayout:
    canonical_agents = root / "agents"
    canonical_skills = root / "skills"
    if not canonical_agents.is_dir() or not canonical_skills.is_dir():
        fail("需要存在 canonical 源目录 agents/ 和 skills/。")

    rules_dir = root / "rules"
    return SourceLayout(
        root=root,
        canonical_agents_dir=canonical_agents,
        canonical_skills_dir=canonical_skills,
        copilot_agents_dir=(root / ".github" / "agents") if (root / ".github" / "agents").is_dir() else None,
        agents_rule=choose_existing(rules_dir / "AGENTS.md", root / "AGENTS.md"),
        copilot_rule=choose_existing(rules_dir / "copilot-instructions.md", root / ".github" / "copilot-instructions.md"),
        claude_rule=choose_existing(rules_dir / "CLAUDE.md", root / "CLAUDE.md", root / ".claude" / "CLAUDE.md"),
    )


def parse_frontmatter(content: str) -> tuple[dict[str, object], str]:
    match = FRONTMATTER_RE.match(content)
    if not match:
        return {}, content

    fields = parse_yaml_like(match.group(1))
    body = content[match.end() :].lstrip()
    return fields, body


def parse_yaml_like(block: str) -> dict[str, object]:
    fields: dict[str, object] = {}
    lines = block.splitlines()
    index = 0

    while index < len(lines):
        raw_line = lines[index]
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            index += 1
            continue
        if ":" not in raw_line:
            fail(f"无法解析 frontmatter 行: {raw_line}")

        key, raw_value = raw_line.split(":", 1)
        key = key.strip()
        value = raw_value.strip()

        if value in {"|", "|-", ">", ">-"}:
            block_lines: list[str] = []
            index += 1
            while index < len(lines):
                nested_line = lines[index]
                if nested_line.startswith("  "):
                    block_lines.append(nested_line[2:])
                    index += 1
                    continue
                if not nested_line.strip():
                    block_lines.append("")
                    index += 1
                    continue
                break

            text = "\n".join(block_lines).rstrip()
            if value.startswith(">"):
                fields[key] = " ".join(part.strip() for part in text.splitlines() if part.strip()).strip()
            else:
                fields[key] = text
            continue

        if value.startswith("[") or value.startswith("{"):
            fields[key] = ast.literal_eval(value)
        else:
            fields[key] = value.strip('"').strip("'")
        index += 1

    return fields


def load_canonical_agent(path: Path, permissive: bool) -> AgentDefinition | None:
    content = path.read_text(encoding="utf-8")
    fields, body = parse_frontmatter(content)
    if not fields:
        return None

    name = str(fields.get("name", "")).strip()
    description = str(fields.get("description", "")).strip()
    instructions = body.rstrip()
    if not name or not description or not instructions:
        fail(f"canonical agent 缺少必填字段或正文为空: {path}")
    if path.stem != name:
        fail(f"agent 文件名必须与 name 一致: {path.name} != {name}")
    if not KEBAB_CASE_RE.fullmatch(name):
        fail(f"agent name 必须为 kebab-case: {path}")

    unsupported = sorted(key for key in fields if key not in {"name", "description", "model"})
    if unsupported and not permissive:
        fail(f"canonical agent 存在未支持字段（请改用 --permissive 或先清理字段）: {path} -> {', '.join(unsupported)}")

    model = str(fields["model"]).strip() if "model" in fields and str(fields["model"]).strip() else None
    return AgentDefinition(
        source=path,
        name=name,
        description=description,
        instructions=instructions,
        model=model,
        extra_fields=tuple(unsupported),
    )


def list_canonical_agents(layout: SourceLayout, permissive: bool) -> list[AgentDefinition]:
    agents: list[AgentDefinition] = []
    for path in sorted(layout.canonical_agents_dir.glob("*.md")):
        definition = load_canonical_agent(path, permissive)
        if definition is not None:
            agents.append(definition)
    return agents


def list_copilot_agent_files(layout: SourceLayout) -> list[Path]:
    if layout.copilot_agents_dir is None:
        return []
    return sorted(layout.copilot_agents_dir.glob("*.agent.md"))


def list_skill_dirs(layout: SourceLayout) -> list[Path]:
    return sorted(path for path in layout.canonical_skills_dir.iterdir() if path.is_dir() and (path / "SKILL.md").is_file())


def select_agent_definitions(definitions: list[AgentDefinition], requested: list[str]) -> list[AgentDefinition]:
    if not requested:
        return definitions

    requested_set = set(requested)
    selected = [definition for definition in definitions if definition.name in requested_set]
    missing = requested_set - {definition.name for definition in selected}
    if missing:
        fail(f"未找到这些 canonical agent: {', '.join(sorted(missing))}")
    return selected


def select_copilot_agent_files(files: list[Path], requested: list[str]) -> list[Path]:
    if not requested:
        return files

    requested_set = set(requested)
    selected = [file_path for file_path in files if file_path.name.endswith(".agent.md") and file_path.name[:-9] in requested_set]
    missing = requested_set - {file_path.name[:-9] for file_path in selected}
    if missing:
        fail(f"未找到这些 Copilot agent: {', '.join(sorted(missing))}")
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


def resolve_workspace_root(project_dir: str | None) -> Path:
    if project_dir:
        return Path(project_dir).expanduser().resolve()

    detected = find_git_repo_root(Path.cwd())
    if detected is None:
        fail("无法自动确定 WORKSPACE_ROOT。请在 git 仓库内运行，或显式传入 --project-dir。")
    return detected


def resolve_user_home_root(platform: str) -> Path:
    home = Path.home()
    roots = {
        "copilot": home / ".copilot",
        "claude-code": home / ".claude",
        "codex": home / ".codex",
        "openclaw": home / ".openclaw",
    }
    return roots[platform]


def project_meta_root(workspace_root: Path) -> Path:
    return workspace_root / ".meta-workflow"


def manifest_path(workspace_root: Path) -> Path:
    return project_meta_root(workspace_root) / "delivery" / "doc" / "INSTALL-MANIFEST.yaml"


def canonical_commit(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def yaml_scalar(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def toml_multiline(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"""', '\\"""')


def markdown_audit(commit: str, generated: str) -> str:
    return f"<!-- myflow-managed: version={MANAGED_VERSION} canonical-commit={commit} generated={generated} -->"


def toml_audit(commit: str, generated: str) -> str:
    return f"# myflow-managed: version={MANAGED_VERSION} canonical-commit={commit} generated={generated}"


def inject_markdown_audit(content: str, commit: str, generated: str) -> str:
    audit = markdown_audit(commit, generated)
    match = FRONTMATTER_RE.match(content)
    if not match:
        return f"{audit}\n\n{content.lstrip()}"

    prefix = content[: match.end()].rstrip()
    body = content[match.end() :].lstrip()
    return f"{prefix}\n{audit}\n\n{body}"


def render_claude_agent(agent: AgentDefinition, commit: str, generated: str) -> str:
    frontmatter = [
        "---",
        f"name: {yaml_scalar(agent.name)}",
        f"description: {yaml_scalar(agent.description)}",
    ]
    if agent.model:
        frontmatter.append(f"model: {yaml_scalar(agent.model)}")
    frontmatter.append("---")
    return "\n".join(frontmatter) + f"\n{markdown_audit(commit, generated)}\n\n{agent.instructions.rstrip()}\n"


def render_codex_agent(agent: AgentDefinition, commit: str, generated: str) -> str:
    lines = [
        toml_audit(commit, generated),
        f"name = {toml_string(agent.name)}",
        "description = \"\"\"",
        toml_multiline(agent.description),
        "\"\"\"",
    ]
    if agent.model:
        lines.append(f"model = {toml_string(agent.model)}")
    lines.extend(
        [
            "developer_instructions = \"\"\"",
            toml_multiline(agent.instructions.rstrip()),
            "\"\"\"",
            "",
        ]
    )
    return "\n".join(lines)


def build_openclaw_manifest(agent_entries: list[dict[str, str]], skill_entries: list[dict[str, str]]) -> str:
    payload = {
        "version": "1.0",
        "agents": agent_entries,
        "skills": skill_entries,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def record_original_text(transaction: Transaction, path: Path) -> None:
    if path not in transaction.original_text:
        transaction.original_text[path] = path.read_text(encoding="utf-8") if path.exists() else None


def write_text(path: Path, content: str, transaction: Transaction, dry_run: bool) -> None:
    if dry_run:
        print(f"[DryRun] write -> {path}")
        return
    record_original_text(transaction, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def copy_text_with_audit(src: Path, dest: Path, transaction: Transaction, dry_run: bool, commit: str, generated: str) -> None:
    content = src.read_text(encoding="utf-8")
    write_text(dest, inject_markdown_audit(content, commit, generated), transaction, dry_run)


def remove_path(path: Path, transaction: Transaction, dry_run: bool) -> None:
    if dry_run:
        print(f"[DryRun] remove -> {path}")
        return

    if path.is_dir():
        removed_files: list[tuple[Path, bytes]] = []
        for file_path in sorted(p for p in path.rglob("*") if p.is_file()):
            removed_files.append((file_path.relative_to(path), file_path.read_bytes()))
        transaction.removed_dirs[path] = removed_files
        shutil.rmtree(path)
        return

    if path.exists():
        record_original_text(transaction, path)
        path.unlink()


def rollback_transaction(transaction: Transaction) -> None:
    for path, files in transaction.removed_dirs.items():
        path.mkdir(parents=True, exist_ok=True)
        for relative_path, payload in files:
            restored = path / relative_path
            restored.parent.mkdir(parents=True, exist_ok=True)
            restored.write_bytes(payload)

    for path in sorted(transaction.original_text, reverse=True):
        original = transaction.original_text[path]
        if original is None:
            if path.exists():
                path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(original, encoding="utf-8")


def managed_block_markers(commit: str, generated: str) -> tuple[str, str]:
    begin = f"<!-- myflow:managed:begin v=1 commit={commit} generated={generated} -->"
    end = "<!-- myflow:managed:end -->"
    return begin, end


def render_managed_block(content: str, commit: str, generated: str) -> str:
    begin, end = managed_block_markers(commit, generated)
    managed_content = inject_markdown_audit(content.rstrip() + "\n", commit, generated).rstrip()
    return f"{begin}\n{managed_content}\n{end}"


def upsert_managed_block(path: Path, canonical_content: str, transaction: Transaction, dry_run: bool, commit: str, generated: str) -> None:
    block = render_managed_block(canonical_content, commit, generated)
    begin_prefix = "<!-- myflow:managed:begin"
    end_marker = "<!-- myflow:managed:end -->"

    if not path.exists():
        write_text(path, block + "\n", transaction, dry_run)
        return

    existing = path.read_text(encoding="utf-8")
    begin_index = existing.find(begin_prefix)
    end_index = existing.find(end_marker)
    if (begin_index == -1) ^ (end_index == -1):
        fail(f"managed block 哨兵损坏，请先手工修复: {path}")

    if begin_index == -1 and end_index == -1:
        separator = "\n\n" if existing and not existing.endswith("\n\n") else ""
        merged = existing.rstrip() + separator + block + "\n"
        write_text(path, merged if existing.strip() else block + "\n", transaction, dry_run)
        return

    if begin_index > end_index:
        fail(f"managed block 哨兵顺序错误，请先手工修复: {path}")

    end_index += len(end_marker)
    replaced = existing[:begin_index].rstrip()
    suffix = existing[end_index:].lstrip("\r\n")
    parts = [part for part in [replaced, block, suffix.rstrip()] if part]
    write_text(path, "\n\n".join(parts) + "\n", transaction, dry_run)


def clear_managed_block(path: Path, transaction: Transaction, dry_run: bool) -> None:
    begin_prefix = "<!-- myflow:managed:begin"
    end_marker = "<!-- myflow:managed:end -->"
    if not path.exists():
        return

    existing = path.read_text(encoding="utf-8")
    begin_index = existing.find(begin_prefix)
    end_index = existing.find(end_marker)
    if begin_index == -1 or end_index == -1:
        return
    if begin_index > end_index:
        fail(f"managed block 哨兵顺序错误，请先手工修复: {path}")

    end_index += len(end_marker)
    begin_line_end = existing.find("\n", begin_index)
    if begin_line_end == -1:
        begin_line_end = begin_index + len(existing[begin_index:end_index])
    retained = existing[:begin_line_end] + "\n" + end_marker
    prefix = existing[:begin_index].rstrip()
    suffix = existing[end_index:].lstrip("\r\n")
    parts = [part for part in [prefix, retained, suffix.rstrip()] if part]
    write_text(path, "\n\n".join(parts) + "\n", transaction, dry_run)


def copy_skill_tree(src_dir: Path, dest_dir: Path, transaction: Transaction, dry_run: bool, commit: str, generated: str) -> None:
    for src_path in sorted(src_dir.rglob("*")):
        if src_path.is_dir():
            continue
        relative_path = src_path.relative_to(src_dir)
        dest_path = dest_dir / relative_path
        if relative_path == Path("SKILL.md"):
            copy_text_with_audit(src_path, dest_path, transaction, dry_run, commit, generated)
            continue
        if dry_run:
            print(f"[DryRun] {src_path} -> {dest_path}")
            continue
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        if dest_path.exists():
            record_original_text(transaction, dest_path)
        else:
            record_original_text(transaction, dest_path)
        shutil.copy2(src_path, dest_path)


def counterpart_paths(platform: str, workspace_root: Path) -> dict[str, Path]:
    home = Path.home()
    mapping = {
        "codex-agent-user": home / ".codex" / "agents",
        "codex-agent-project": workspace_root / ".codex" / "agents",
        "codex-skill-user": home / ".agents" / "skills",
        "codex-skill-project": workspace_root / ".agents" / "skills",
        "claude-agent-user": home / ".claude" / "agents",
        "claude-agent-project": workspace_root / ".claude" / "agents",
        "claude-skill-user": home / ".claude" / "skills",
        "claude-skill-project": workspace_root / ".claude" / "skills",
    }
    if platform not in {"codex", "claude-code"}:
        return {}
    return mapping


def scan_name_conflicts(platform: str, scope: str, workspace_root: Path, agent_names: list[str], skill_names: list[str]) -> list[dict[str, str]]:
    conflicts: list[dict[str, str]] = []
    paths = counterpart_paths(platform, workspace_root)
    current_scope = "user" if scope == "user" else "project"
    other_scope = "project" if current_scope == "user" else "user"

    if platform == "codex":
        for name in agent_names:
            if name in BUILT_IN_CODEX_AGENTS:
                fail(f"Codex subagent 名称禁止与 built-in 重名: {name}")
            other_path = paths[f"codex-agent-{other_scope}"] / f"{name}.toml"
            if other_path.exists():
                conflicts.append({"kind": "agent", "name": name, "scope": other_scope, "path": str(other_path)})
        for name in skill_names:
            other_path = paths[f"codex-skill-{other_scope}"] / name / "SKILL.md"
            if other_path.exists():
                conflicts.append({"kind": "skill", "name": name, "scope": other_scope, "path": str(other_path)})
        return conflicts

    for name in agent_names:
        other_path = paths[f"claude-agent-{other_scope}"] / f"{name}.md"
        if other_path.exists():
            conflicts.append({"kind": "agent", "name": name, "scope": other_scope, "path": str(other_path)})
    for name in skill_names:
        other_path = paths[f"claude-skill-{other_scope}"] / name / "SKILL.md"
        if other_path.exists():
            conflicts.append({"kind": "skill", "name": name, "scope": other_scope, "path": str(other_path)})
    return conflicts


def runtime_override_warnings(platform: str, scope: str, workspace_root: Path) -> list[str]:
    warnings: list[str] = []
    if scope != "user":
        return warnings

    if platform == "codex":
        for candidate in [workspace_root / "AGENTS.override.md", workspace_root / "AGENTS.md", workspace_root / ".codex" / "agents"]:
            if candidate.exists():
                warnings.append(f"检测到可能覆盖用户级 Codex 安装的项目层对象: {candidate}")
    if platform == "claude-code":
        for candidate in [workspace_root / "CLAUDE.md", workspace_root / "CLAUDE.local.md", workspace_root / ".claude" / "CLAUDE.md", workspace_root / ".claude" / "agents"]:
            if candidate.exists():
                warnings.append(f"检测到可能覆盖用户级 Claude Code 安装的项目层对象: {candidate}")
    return warnings


def load_manifest(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"manifest_version": 1, "installs": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"无法解析 INSTALL-MANIFEST.yaml（当前实现使用 JSON 兼容 YAML 存储）: {path} -> {exc}")
    return {"manifest_version": 1, "installs": []}


def save_manifest(path: Path, payload: dict[str, object], transaction: Transaction, dry_run: bool) -> None:
    write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n", transaction, dry_run)


def upsert_manifest_entry(payload: dict[str, object], entry: dict[str, object]) -> None:
    installs = list(payload.get("installs", []))
    installs = [existing for existing in installs if not (existing.get("platform") == entry["platform"] and existing.get("scope") == entry["scope"])]
    installs.append(entry)
    payload["installs"] = installs


def install_rules(
    platform: str,
    scope: str,
    workspace_root: Path,
    layout: SourceLayout,
    transaction: Transaction,
    dry_run: bool,
    commit: str,
    generated: str,
    manifest_entries: list[dict[str, str]],
) -> None:
    if platform == "copilot" and layout.copilot_rule:
        dest = (workspace_root / ".github" / "copilot-instructions.md") if scope == "project" else (resolve_user_home_root("copilot") / "copilot-instructions.md")
        copy_text_with_audit(layout.copilot_rule, dest, transaction, dry_run, commit, generated)
        manifest_entries.append({"kind": "rule", "path": str(dest), "remove_path": str(dest)})
        return

    if platform == "codex" and layout.agents_rule:
        dest = (workspace_root / "AGENTS.md") if scope == "project" else (resolve_user_home_root("codex") / "AGENTS.md")
        upsert_managed_block(dest, layout.agents_rule.read_text(encoding="utf-8"), transaction, dry_run, commit, generated)
        manifest_entries.append({"kind": "managed-block", "path": str(dest), "remove_path": str(dest)})
        return

    if platform == "claude-code" and layout.claude_rule:
        dest = (workspace_root / ".claude" / "CLAUDE.md") if scope == "project" else (resolve_user_home_root("claude-code") / "CLAUDE.md")
        upsert_managed_block(dest, layout.claude_rule.read_text(encoding="utf-8"), transaction, dry_run, commit, generated)
        manifest_entries.append({"kind": "managed-block", "path": str(dest), "remove_path": str(dest)})


def install_agents(
    platform: str,
    scope: str,
    workspace_root: Path,
    layout: SourceLayout,
    canonical_agents: list[AgentDefinition],
    requested_agents: list[str],
    transaction: Transaction,
    dry_run: bool,
    commit: str,
    generated: str,
    manifest_entries: list[dict[str, str]],
) -> list[str]:
    installed_names: list[str] = []

    if platform == "copilot":
        files = select_copilot_agent_files(list_copilot_agent_files(layout), requested_agents)
        if not files:
            fail("Copilot 平台没有可安装的 agent 文件。")
        base_dir = (workspace_root / ".github" / "agents") if scope == "project" else (resolve_user_home_root("copilot") / "agents")
        for src in files:
            dest = base_dir / src.name
            copy_text_with_audit(src, dest, transaction, dry_run, commit, generated)
            name = src.name[:-9]
            installed_names.append(name)
            manifest_entries.append({"kind": "agent", "name": name, "path": str(dest), "remove_path": str(dest)})
        return installed_names

    selected_agents = select_agent_definitions(canonical_agents, requested_agents)
    if not selected_agents:
        fail(f"{platform} 平台没有可安装的 canonical agent。")

    if platform == "claude-code":
        base_dir = (workspace_root / ".claude" / "agents") if scope == "project" else (resolve_user_home_root("claude-code") / "agents")
        for agent in selected_agents:
            dest = base_dir / f"{agent.name}.md"
            write_text(dest, render_claude_agent(agent, commit, generated), transaction, dry_run)
            installed_names.append(agent.name)
            manifest_entries.append({"kind": "agent", "name": agent.name, "path": str(dest), "remove_path": str(dest)})
        return installed_names

    if platform == "codex":
        base_dir = (workspace_root / ".codex" / "agents") if scope == "project" else (resolve_user_home_root("codex") / "agents")
        for agent in selected_agents:
            dest = base_dir / f"{agent.name}.toml"
            write_text(dest, render_codex_agent(agent, commit, generated), transaction, dry_run)
            installed_names.append(agent.name)
            manifest_entries.append({"kind": "agent", "name": agent.name, "path": str(dest), "remove_path": str(dest)})
        return installed_names

    base_dir = (workspace_root / ".openclaw" / "agents") if scope == "project" else (resolve_user_home_root("openclaw") / "agents")
    for agent in selected_agents:
        dest = base_dir / f"{agent.name}.md"
        copy_text_with_audit(agent.source, dest, transaction, dry_run, commit, generated)
        installed_names.append(agent.name)
        manifest_entries.append({"kind": "agent", "name": agent.name, "path": str(dest), "remove_path": str(dest)})
    return installed_names


def install_skills(
    platform: str,
    scope: str,
    workspace_root: Path,
    skill_dirs: list[Path],
    transaction: Transaction,
    dry_run: bool,
    commit: str,
    generated: str,
    manifest_entries: list[dict[str, str]],
) -> list[str]:
    installed_names: list[str] = []
    if platform == "codex":
        base_dir = (workspace_root / ".agents" / "skills") if scope == "project" else (Path.home() / ".agents" / "skills")
    elif platform == "claude-code":
        base_dir = (workspace_root / ".claude" / "skills") if scope == "project" else (resolve_user_home_root("claude-code") / "skills")
    elif platform == "copilot":
        base_dir = (workspace_root / ".github" / "copilot" / "skills") if scope == "project" else (resolve_user_home_root("copilot") / "skills")
    else:
        base_dir = (workspace_root / ".openclaw" / "skills") if scope == "project" else (resolve_user_home_root("openclaw") / "skills")

    for skill_dir in skill_dirs:
        dest_dir = base_dir / skill_dir.name
        copy_skill_tree(skill_dir, dest_dir, transaction, dry_run, commit, generated)
        installed_names.append(skill_dir.name)
        manifest_entries.append(
            {
                "kind": "skill",
                "name": skill_dir.name,
                "path": str(dest_dir / "SKILL.md"),
                "remove_path": str(dest_dir),
            }
        )
    return installed_names


def write_openclaw_manifest(
    scope: str,
    workspace_root: Path,
    manifest_entries: list[dict[str, str]],
    transaction: Transaction,
    dry_run: bool,
) -> None:
    base_dir = (workspace_root / ".openclaw") if scope == "project" else resolve_user_home_root("openclaw")
    agents: list[dict[str, str]] = []
    skills: list[dict[str, str]] = []
    for entry in manifest_entries:
        remove_path = Path(entry["remove_path"])
        if entry["kind"] == "agent":
            agents.append({"name": entry["name"], "file": remove_path.relative_to(base_dir).as_posix()})
        if entry["kind"] == "skill":
            skills.append({"name": entry["name"], "file": (remove_path / "SKILL.md").relative_to(base_dir).as_posix()})
    write_text(base_dir / "manifest.yaml", build_openclaw_manifest(agents, skills), transaction, dry_run)


def uninstall_platform(
    platform: str,
    scope: str,
    workspace_root: Path,
    manifest_payload: dict[str, object],
    transaction: Transaction,
    dry_run: bool,
) -> dict[str, object]:
    installs = list(manifest_payload.get("installs", []))
    matching = next((entry for entry in installs if entry.get("platform") == platform and entry.get("scope") == scope and entry.get("status") == "installed"), None)
    if matching is None:
        fail(f"INSTALL-MANIFEST 中未找到 {platform}/{scope} 的已安装记录。")

    for entry in matching.get("entries", []):
        remove_target = Path(entry["remove_path"])
        if entry["kind"] == "managed-block":
            clear_managed_block(remove_target, transaction, dry_run)
            continue
        remove_path(remove_target, transaction, dry_run)

    matching["status"] = "uninstalled"
    matching["uninstalled_at"] = iso_now()
    return matching


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install SCOPE-Pack assets into a platform directory.")
    parser.add_argument("--platform", required=True, choices=VALID_PLATFORMS, help="目标平台")
    parser.add_argument("--scope", default="project", choices=VALID_SCOPES, help="安装范围")
    parser.add_argument("--project-dir", default=None, help="WORKSPACE_ROOT；未提供时从当前目录向上查找 git repo root")
    parser.add_argument("--content", default="all", choices=VALID_CONTENTS, help="安装内容")
    parser.add_argument("--agent", default="", help="仅安装指定 agent，逗号分隔")
    parser.add_argument("--skill", default="", help="仅安装指定 skill，逗号分隔")
    parser.add_argument("--dry-run", action="store_true", help="仅打印将执行的操作")
    parser.add_argument("--uninstall", action="store_true", help="按 INSTALL-MANIFEST 精确卸载当前平台与 scope")
    parser.add_argument("--permissive", action="store_true", help="允许忽略 canonical agent 中的未支持字段，并将其记录到 warnings")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    workspace_root = resolve_workspace_root(args.project_dir)
    repo_root = script_repo_root(Path(__file__))
    layout = detect_source_layout(repo_root)
    commit = canonical_commit(repo_root)
    generated = iso_now()
    target_manifest_path = manifest_path(workspace_root)

    requested_agents = parse_csv(args.agent)
    requested_skills = parse_csv(args.skill)
    ensure_kebab_case(requested_agents, "agent")
    ensure_kebab_case(requested_skills, "skill")

    if args.uninstall and (args.content != "all" or requested_agents or requested_skills):
        fail("--uninstall 当前仅支持按 platform + scope 整体卸载，不支持 --content/--agent/--skill 过滤。")

    print(f"Workspace root: {workspace_root}")
    print(f"Canonical source root: {layout.root}")
    print(f"Manifest path: {target_manifest_path}")
    print(f"Platform: {args.platform}")
    print(f"Scope: {args.scope}")

    transaction = Transaction()
    manifest_payload = load_manifest(target_manifest_path)

    if args.uninstall:
        try:
            entry = uninstall_platform(args.platform, args.scope, workspace_root, manifest_payload, transaction, args.dry_run)
            if not args.dry_run:
                save_manifest(target_manifest_path, manifest_payload, transaction, args.dry_run)
        except Exception:
            if not args.dry_run:
                rollback_transaction(transaction)
            raise
        print(f"Uninstalled {args.platform}/{args.scope}.")
        return

    canonical_agents = list_canonical_agents(layout, args.permissive)
    selected_skill_dirs = select_skill_dirs(list_skill_dirs(layout), requested_skills)

    install_rules_enabled = args.content in ("all", "rules")
    install_agents_enabled = args.content in ("all", "agents") or bool(requested_agents)
    install_skills_enabled = args.content in ("all", "skills") or bool(requested_skills)

    if requested_agents and not install_agents_enabled:
        fail("指定了 --agent，但内容类型未包含 agents。")
    if requested_skills and not install_skills_enabled:
        fail("指定了 --skill，但内容类型未包含 skills。")

    warnings: list[str] = runtime_override_warnings(args.platform, args.scope, workspace_root)
    manifest_entries: list[dict[str, str]] = []
    installed_agent_names: list[str] = []
    installed_skill_names: list[str] = []

    try:
        if install_rules_enabled:
            install_rules(args.platform, args.scope, workspace_root, layout, transaction, args.dry_run, commit, generated, manifest_entries)

        if install_agents_enabled:
            installed_agent_names = install_agents(
                args.platform,
                args.scope,
                workspace_root,
                layout,
                canonical_agents,
                requested_agents,
                transaction,
                args.dry_run,
                commit,
                generated,
                manifest_entries,
            )

        if install_skills_enabled:
            installed_skill_names = install_skills(
                args.platform,
                args.scope,
                workspace_root,
                selected_skill_dirs,
                transaction,
                args.dry_run,
                commit,
                generated,
                manifest_entries,
            )

        conflicts = scan_name_conflicts(args.platform, args.scope, workspace_root, installed_agent_names, installed_skill_names)

        if args.platform == "openclaw" and (install_agents_enabled or install_skills_enabled):
            write_openclaw_manifest(args.scope, workspace_root, manifest_entries, transaction, args.dry_run)

        entry: dict[str, object] = {
            "platform": args.platform,
            "scope": args.scope,
            "status": "installed",
            "installed_at": generated,
            "workspace_root": str(workspace_root),
            "project_meta_root": str(project_meta_root(workspace_root)),
            "canonical_commit": commit,
            "warnings": warnings
            + [
                f"canonical agent {agent.name} 忽略未支持字段: {', '.join(agent.extra_fields)}"
                for agent in canonical_agents
                if agent.extra_fields and (not requested_agents or agent.name in requested_agents)
            ],
            "conflicts": conflicts,
            "entries": manifest_entries,
        }

        upsert_manifest_entry(manifest_payload, entry)
        if not args.dry_run:
            save_manifest(target_manifest_path, manifest_payload, transaction, args.dry_run)
    except Exception:
        if not args.dry_run:
            rollback_transaction(transaction)
        raise

    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"  - {warning}")

    if args.dry_run:
        print("Dry run completed.")
        return

    print(f"Installed {len(manifest_entries)} item(s).")


if __name__ == "__main__":
    main()
