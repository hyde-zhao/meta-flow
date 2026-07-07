"""Tests for package_builder single-source platform entry generation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts import package_builder


class PackageBuilderClaudeEntryTests(unittest.TestCase):
    def test_claude_platform_generates_claude_md_from_agents_md(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # AGENTS.md 是唯一 canonical 源；不存在 CLAUDE.md 源
            entry_src = root / "source" / "rules" / "AGENTS.md"
            entry_src.parent.mkdir(parents=True)
            entry_src.write_text("# Package Rules\n", encoding="utf-8")
            self.assertFalse((root / "source" / "rules" / "CLAUDE.md").exists())
            agents_src = root / "source" / "agents"
            agents_src.mkdir(parents=True)
            skills_src = root / "source" / "skills"
            skills_src.mkdir(parents=True)
            output_root = root / "packages"

            _checksums, issues = package_builder.build_platform(
                "claude",
                package_builder.PLATFORM_CONFIGS["claude"],
                agents_src,
                skills_src,
                entry_src,
                output_root,
                dry_run=False,
            )

            self.assertEqual([], issues)
            claude_md = output_root / "claude" / ".claude" / "CLAUDE.md"
            self.assertTrue(claude_md.is_file())
            self.assertEqual("# Package Rules\n", claude_md.read_text(encoding="utf-8"))
            # 源 AGENTS.md 仍存在（复制而非移动）
            self.assertTrue(entry_src.is_file())

    def test_resolve_platform_entry_returns_agents_md_for_claude(self) -> None:
        # 单源：claude 不再查找 CLAUDE.md，直接返回 AGENTS.md
        with tempfile.TemporaryDirectory() as directory:
            agents_md = Path(directory) / "AGENTS.md"
            agents_md.write_text("# Rules\n", encoding="utf-8")
            result = package_builder.resolve_platform_entry("claude", agents_md)
            self.assertEqual(agents_md, result)

    def test_codex_platform_uses_agents_md_entry(self) -> None:
        # codex 入口仍是 AGENTS.md
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entry_src = root / "source" / "rules" / "AGENTS.md"
            entry_src.parent.mkdir(parents=True)
            entry_src.write_text("# Codex Rules\n", encoding="utf-8")
            agents_src = root / "source" / "agents"
            agents_src.mkdir(parents=True)
            skills_src = root / "source" / "skills"
            skills_src.mkdir(parents=True)
            output_root = root / "packages"

            package_builder.build_platform(
                "codex",
                package_builder.PLATFORM_CONFIGS["codex"],
                agents_src,
                skills_src,
                entry_src,
                output_root,
                dry_run=False,
            )

            agents_md = output_root / "codex" / ".codex" / "AGENTS.md"
            self.assertTrue(agents_md.is_file())
            self.assertEqual("# Codex Rules\n", agents_md.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
