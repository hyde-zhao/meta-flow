#!/usr/bin/env python3
"""
Meta Flow Platform Package Builder
将已验证的 Agent/Skill 产物打包为各平台安装包。

用法：
  uv run --with pyyaml --python 3.11 python scripts/package_builder.py --manifest delivery/doc/PACKAGE-MANIFEST.yaml
  uv run --with pyyaml --python 3.11 python scripts/package_builder.py --manifest delivery/doc/PACKAGE-MANIFEST.yaml --targets claude-code,codex
  uv run --with pyyaml --python 3.11 python scripts/package_builder.py --manifest delivery/doc/PACKAGE-MANIFEST.yaml --dry-run
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

import yaml

PLATFORM_CONFIGS = {
    "claude-code": {
        "root": ".claude",
        "entry_file": "CLAUDE.md",
        "agents_dir": "agents",
        "skills_dir": "skills",
        "agent_format": "md",
    },
    "codex": {
        "root": ".codex",
        "entry_file": "AGENTS.md",
        "agents_dir": "agents",
        "skills_dir": None,
        "agent_format": "toml",
    },
    "openclaw": {
        "root": ".openclaw",
        "entry_file": "manifest.yaml",
        "agents_dir": "agents",
        "skills_dir": "skills",
        "agent_format": "md",
    },
}

KEBAB_CASE_RE = re.compile(r"^[a-z][a-z0-9-]+\.(md|toml)$")
META_FLOW_AGENTS = {"meta-po", "meta-pm", "meta-se", "meta-dm", "meta-dev", "meta-qa", "meta-doc"}
EXCLUDE_SKILLS = {"command-capability-map", "constraint-checker", "constraint-normalizer", "vendor-profile-loader"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_frontmatter(content: str, file_path: Path) -> list[str]:
    issues = []
    if not content.startswith("---"):
        issues.append(f"{file_path}: 缺少 Frontmatter")
        return issues
    end = content.find("---", 3)
    if end == -1:
        issues.append(f"{file_path}: Frontmatter 未闭合")
        return issues
    fm_text = content[3:end]
    has_name = "name:" in fm_text or "title:" in fm_text
    if not has_name:
        issues.append(f"{file_path}: Frontmatter 缺少 name/title 字段")
    if "description:" not in fm_text:
        issues.append(f"{file_path}: Frontmatter 缺少 description 字段")
    return issues


def convert_md_to_toml(md_path: Path, agent_name: str) -> str:
    content = md_path.read_text(encoding="utf-8")
    description = ""
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            fm_text = content[3:end]
            for line in fm_text.splitlines():
                if line.startswith("description:"):
                    description = line.split(":", 1)[1].strip()
            content = content[end + 3:].strip()
    description = description or f"Meta Flow Agent: {agent_name}"
    description = description.replace("\\", "\\\\").replace('"""', '\\"""')
    instructions = content.replace("\\", "\\\\").replace('"""', '\\"""')
    return (
        f'name = "{agent_name}"\n'
        f'description = """\n{description}\n"""\n'
        f'developer_instructions = """\n{instructions}\n"""\n'
    )


def build_openclaw_manifest(agents_dir: Path, skills_dir: Path) -> str:
    agents = []
    skills = []
    if agents_dir.exists():
        for f in sorted(agents_dir.iterdir()):
            if f.suffix == ".md":
                agents.append({"name": f.stem, "file": f"agents/{f.name}"})
    if skills_dir.exists():
        for f in sorted(skills_dir.iterdir()):
            if f.suffix == ".md":
                skills.append({"name": f.stem, "file": f"skills/{f.name}"})
    return yaml.dump({"version": "1.0", "agents": agents, "skills": skills}, allow_unicode=True, default_flow_style=False)


def build_platform(platform: str, config: dict, agents_src: Path, skills_src: Path, entry_src: Path | None, output_root: Path, dry_run: bool) -> tuple[list[str], list[str]]:
    checksums = []
    issues = []
    pkg_root = output_root / platform / config["root"]
    if not dry_run:
        pkg_root.mkdir(parents=True, exist_ok=True)

    if config["entry_file"] and entry_src and entry_src.exists():
        dest = pkg_root / config["entry_file"]
        if not dry_run:
            shutil.copy2(entry_src, dest)
            checksums.append(f"{sha256_file(dest)}  {dest.relative_to(output_root)}")
        else:
            print(f"  [DryRun] 复制入口文件: {entry_src} → {dest}")

    if config["agents_dir"] and agents_src.exists():
        agents_dest = pkg_root / config["agents_dir"]
        if not dry_run:
            agents_dest.mkdir(parents=True, exist_ok=True)
        for agent_file in sorted(agents_src.glob("*.md")):
            if agent_file.stem not in META_FLOW_AGENTS:
                if dry_run:
                    print(f"  [DryRun] 跳过非 Meta Flow Agent: {agent_file.name}")
                continue
            if not KEBAB_CASE_RE.match(agent_file.name):
                issues.append(f"命名规范: {agent_file.name} 不符合 kebab-case")
            content = agent_file.read_text(encoding="utf-8")
            if content.startswith("---"):
                issues.extend(validate_frontmatter(content, agent_file))
            if config["agent_format"] == "toml" and platform == "codex":
                dest = agents_dest / (agent_file.stem + ".toml")
                if not dry_run:
                    dest.write_text(convert_md_to_toml(agent_file, agent_file.stem), encoding="utf-8")
                    checksums.append(f"{sha256_file(dest)}  {dest.relative_to(output_root)}")
                else:
                    print(f"  [DryRun] 转换 TOML: {agent_file} → {dest}")
            else:
                dest = agents_dest / agent_file.name
                if not dry_run:
                    shutil.copy2(agent_file, dest)
                    checksums.append(f"{sha256_file(dest)}  {dest.relative_to(output_root)}")
                else:
                    print(f"  [DryRun] 复制 Agent: {agent_file} → {dest}")

    if config["skills_dir"] and skills_src.exists():
        skills_dest = pkg_root / config["skills_dir"]
        if not dry_run:
            skills_dest.mkdir(parents=True, exist_ok=True)
        for skill_dir in sorted(skills_src.iterdir()):
            if not skill_dir.is_dir():
                continue
            if skill_dir.name in EXCLUDE_SKILLS:
                if dry_run:
                    print(f"  [DryRun] 跳过专属 Skill: {skill_dir.name}")
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue
            dest_name = skill_dir.name + ".md"
            if not KEBAB_CASE_RE.match(dest_name):
                issues.append(f"命名规范: {dest_name} 不符合 kebab-case")
            content = skill_file.read_text(encoding="utf-8")
            issues.extend(validate_frontmatter(content, skill_file))
            dest = skills_dest / dest_name
            if not dry_run:
                shutil.copy2(skill_file, dest)
                checksums.append(f"{sha256_file(dest)}  {dest.relative_to(output_root)}")
            else:
                print(f"  [DryRun] 复制 Skill: {skill_file} → {dest}")

    if platform == "openclaw" and not dry_run:
        manifest_path = pkg_root / "manifest.yaml"
        manifest_path.write_text(build_openclaw_manifest(pkg_root / config["agents_dir"], pkg_root / config["skills_dir"]), encoding="utf-8")
        checksums.append(f"{sha256_file(manifest_path)}  {manifest_path.relative_to(output_root)}")

    return checksums, issues


def main():
    parser = argparse.ArgumentParser(description="Meta Flow Platform Package Builder")
    parser.add_argument("--manifest", default="delivery/doc/PACKAGE-MANIFEST.yaml", help="PACKAGE-MANIFEST.yaml 路径")
    parser.add_argument("--targets", default="claude-code,codex,openclaw", help="目标平台，逗号分隔")
    parser.add_argument("--agents-dir", default="delivery/agents", help="Agent 产物源文件目录")
    parser.add_argument("--skills-dir", default="delivery/skills", help="Skill 产物源文件目录")
    parser.add_argument("--entry-file", default="delivery/rules/AGENTS.md", help="平台主入口文件")
    parser.add_argument("--output", default="packages", help="输出目录")
    parser.add_argument("--dry-run", action="store_true", help="仅校验，不写文件")
    args = parser.parse_args()

    targets = [t.strip() for t in args.targets.split(",")]
    agents_src = Path(args.agents_dir)
    skills_src = Path(args.skills_dir)
    entry_src = Path(args.entry_file)
    output_root = Path(args.output)
    all_issues = []
    all_checksums = []

    print(f"Meta Flow Package Builder ({'DryRun' if args.dry_run else 'Build'})")
    print(f"目标平台: {', '.join(targets)}")
    print()

    for platform in targets:
        if platform not in PLATFORM_CONFIGS:
            print(f"  [跳过] 未知平台: {platform}")
            continue
        print(f"[{platform}] 构建中...")
        checksums, issues = build_platform(platform, PLATFORM_CONFIGS[platform], agents_src, skills_src, entry_src, output_root, args.dry_run)
        all_checksums.extend(checksums)
        all_issues.extend(issues)
        if issues:
            for issue in issues:
                print(f"  [WARN] {issue}")
        else:
            print("  [OK] Build complete")

    if not args.dry_run and all_checksums:
        checksum_file = output_root / "INSTALL-CHECKSUMS.sha256"
        checksum_file.write_text("\n".join(all_checksums) + "\n", encoding="utf-8")
        print(f"\nSHA256 校验文件已生成: {checksum_file}")

    print(f"\n{'='*50}")
    if all_issues:
        print(f"Found {len(all_issues)} issue(s):")
        for issue in all_issues:
            print(f"  - {issue}")
        sys.exit(1)
    print("All platforms built successfully.")
    sys.exit(0)


if __name__ == "__main__":
    main()
