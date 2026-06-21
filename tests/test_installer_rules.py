from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from delivery.scripts import install


class InstallerRulesTests(unittest.TestCase):
    def test_codex_rules_install_creates_agents_md_when_source_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_rule = root / "source" / "rules" / "AGENTS.md"
            source_rule.parent.mkdir(parents=True)
            source_rule.write_text("# Rules\n", encoding="utf-8")
            target = root / "target"
            target.mkdir()
            contracts = {
                "contracts": {
                    "codex": {
                        "scopes": {
                            "project": {
                                "rules": "AGENTS.md",
                                "agents": ".codex/agents",
                                "skills": ".agents/skills",
                            }
                        }
                    }
                }
            }
            layout = install.SourceLayout(
                root=root / "source",
                canonical_agents_dir=root / "source" / "agents",
                canonical_skills_dir=root / "source" / "skills",
                platform_contracts=root / "source" / "doc" / "PLATFORM-CONTRACTS.yaml",
                agents_rule=source_rule,
                claude_rule=None,
            )
            manifest_entries: list[dict[str, str]] = []

            install.install_rules(
                "codex",
                "project",
                target,
                contracts,
                layout,
                install.Transaction(),
                False,
                "test-commit",
                "2026-06-21T00:00:00Z",
                manifest_entries,
            )

            agents_md = target / "AGENTS.md"
            self.assertTrue(agents_md.is_file())
            self.assertIn("myflow:managed:begin", agents_md.read_text(encoding="utf-8"))
            self.assertEqual([{"kind": "managed-block", "path": str(agents_md), "remove_path": str(agents_md)}], manifest_entries)

    def test_codex_rules_install_fails_when_source_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.mkdir()
            contracts = {
                "contracts": {
                    "codex": {
                        "scopes": {
                            "project": {
                                "rules": "AGENTS.md",
                                "agents": ".codex/agents",
                                "skills": ".agents/skills",
                            }
                        }
                    }
                }
            }
            layout = install.SourceLayout(
                root=root / "source",
                canonical_agents_dir=root / "source" / "agents",
                canonical_skills_dir=root / "source" / "skills",
                platform_contracts=root / "source" / "doc" / "PLATFORM-CONTRACTS.yaml",
                agents_rule=None,
                claude_rule=None,
            )

            with self.assertRaises(SystemExit) as raised:
                install.install_rules(
                    "codex",
                    "project",
                    target,
                    contracts,
                    layout,
                    install.Transaction(),
                    True,
                    "test-commit",
                    "2026-06-21T00:00:00Z",
                    [],
                )

            self.assertEqual(1, raised.exception.code)


if __name__ == "__main__":
    unittest.main()
