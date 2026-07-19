from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from delivery.scripts import install


class InstallerRulesTests(unittest.TestCase):
    def test_project_manifest_is_routed_inside_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            self.assertEqual(
                root / ".meta-flow" / "INSTALL-MANIFEST.yaml",
                install.manifest_path(root, "project"),
            )
            self.assertEqual(root / ".meta-flow", install.install_state_root(root, "project"))

    def test_user_manifest_keeps_user_scoped_state_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            self.assertEqual(
                Path.home() / ".meta-flow" / "delivery" / "doc" / "INSTALL-MANIFEST.yaml",
                install.manifest_path(root, "user"),
            )
            self.assertEqual(Path.home() / ".meta-flow", install.install_state_root(root, "user"))

    def test_manifest_dry_run_reports_write_without_creating_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".meta-flow" / "INSTALL-MANIFEST.yaml"
            output = StringIO()

            with redirect_stdout(output):
                install.save_manifest(
                    path,
                    {"manifest_version": 1, "installs": []},
                    install.Transaction(),
                    True,
                )

            self.assertIn(f"[DryRun] write -> {path}", output.getvalue())
            self.assertFalse(path.exists())

    def test_codex_model_routing_is_explicit_and_platform_specific(self) -> None:
        source_agents = [
            install.AgentDefinition(
                source=Path(f"{name}.md"),
                name=name,
                description=f"{name} agent",
                instructions=f"You are {name}.",
                model=None,
                model_reasoning_effort="medium",
                tools=None,
                extra_fields=(),
            )
            for name in ("meta-pm", "meta-se", "meta-dev", "meta-qa", "meta-doc")
        ]

        rendered_agents = install.codex_install_agent_definitions(source_agents)
        models = {agent.name: agent.model for agent in rendered_agents}

        self.assertEqual("gpt-5.6-terra", models["meta-pm"])
        self.assertEqual("gpt-5.6-terra", models["meta-se"])
        self.assertEqual("gpt-5.6-terra", models["meta-dev"])
        self.assertEqual("gpt-5.6-terra", models["meta-qa"])
        self.assertEqual("gpt-5.6-luna", models["meta-doc"])
        self.assertEqual("gpt-5.6-sol", models["meta-dev-debugger"])
        self.assertEqual("gpt-5.6-sol", models["meta-se-critical"])
        self.assertEqual("gpt-5.6-sol", models["meta-qa-critical"])
        self.assertTrue(all(agent.model is None for agent in source_agents))

        codex_toml = install.render_codex_agent(rendered_agents[0], "abc", "2026-07-10T00:00:00Z")
        self.assertIn('model = "gpt-5.6-terra"', codex_toml)
        claude_markdown = install.render_claude_agent(source_agents[0], "abc", "2026-07-10T00:00:00Z")
        qoder_markdown = install.render_qoder_agent(source_agents[0], "abc", "2026-07-10T00:00:00Z")
        self.assertNotIn("gpt-5.6-", claude_markdown)
        self.assertNotIn("gpt-5.6-", qoder_markdown)

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

    def test_claude_rules_install_generates_claude_md_from_agents_md(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_rule = root / "source" / "rules" / "AGENTS.md"
            source_rule.parent.mkdir(parents=True)
            source_rule.write_text("# Canonical Rules\n", encoding="utf-8")
            # 确认不存在 CLAUDE.md 源；claude 入口必须从 AGENTS.md 生成
            self.assertFalse((root / "source" / "rules" / "CLAUDE.md").exists())
            target = root / "target"
            target.mkdir()
            contracts = {
                "contracts": {
                    "claude": {
                        "scopes": {
                            "project": {
                                "rules": "CLAUDE.md",
                                "agents": ".claude/agents",
                                "skills": ".claude/skills",
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
            )
            manifest_entries: list[dict[str, str]] = []

            install.install_rules(
                "claude",
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

            claude_md = target / "CLAUDE.md"
            self.assertTrue(claude_md.is_file())
            content = claude_md.read_text(encoding="utf-8")
            self.assertIn("myflow:managed:begin platform=claude", content)
            self.assertIn("myflow:managed:end platform=claude", content)
            self.assertIn("# Canonical Rules", content)
            self.assertEqual([{"kind": "managed-block", "path": str(claude_md), "remove_path": str(claude_md)}], manifest_entries)

    def test_claude_rules_install_fails_when_agents_source_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.mkdir()
            contracts = {
                "contracts": {
                    "claude": {
                        "scopes": {
                            "project": {
                                "rules": "CLAUDE.md",
                                "agents": ".claude/agents",
                                "skills": ".claude/skills",
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
            )

            with self.assertRaises(SystemExit) as raised:
                install.install_rules(
                    "claude",
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


class QoderInstallerTests(unittest.TestCase):
    def _make_layout(self, root: Path, agents_rule: Path | None) -> install.SourceLayout:
        return install.SourceLayout(
            root=root / "source",
            canonical_agents_dir=root / "source" / "agents",
            canonical_skills_dir=root / "source" / "skills",
            platform_contracts=root / "source" / "doc" / "PLATFORM-CONTRACTS.yaml",
            agents_rule=agents_rule,
        )

    def _make_contracts(self) -> dict:
        return {
            "contracts": {
                "codex": {
                    "scopes": {
                        "project": {"rules": "AGENTS.md", "agents": ".codex/agents", "skills": ".agents/skills"},
                    }
                },
                "qoder": {
                    "scopes": {
                        "project": {"rules": "AGENTS.md", "agents": ".qoder/agents", "skills": ".qoder/skills"},
                    }
                },
            }
        }

    def test_qoder_rules_install_creates_platform_tagged_block(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_rule = root / "source" / "rules" / "AGENTS.md"
            source_rule.parent.mkdir(parents=True)
            source_rule.write_text("# Qoder Rules\n", encoding="utf-8")
            target = root / "target"
            target.mkdir()
            manifest_entries: list[dict[str, str]] = []

            install.install_rules(
                "qoder", "project", target, self._make_contracts(), self._make_layout(root, source_rule),
                install.Transaction(), False, "test-commit", "2026-06-29T00:00:00Z", manifest_entries,
            )

            agents_md = target / "AGENTS.md"
            content = agents_md.read_text(encoding="utf-8")
            self.assertIn("myflow:managed:begin platform=qoder", content)
            self.assertIn("myflow:managed:end platform=qoder", content)
            self.assertEqual([{"kind": "managed-block", "path": str(agents_md), "remove_path": str(agents_md)}], manifest_entries)

    def test_qoder_rules_install_fails_when_source_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.mkdir()

            with self.assertRaises(SystemExit) as raised:
                install.install_rules(
                    "qoder", "project", target, self._make_contracts(), self._make_layout(root, None),
                    install.Transaction(), True, "test-commit", "2026-06-29T00:00:00Z", [],
                )
            self.assertEqual(1, raised.exception.code)

    def test_codex_and_qoder_managed_blocks_coexist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_rule = root / "source" / "rules" / "AGENTS.md"
            source_rule.parent.mkdir(parents=True)
            source_rule.write_text("# Shared Rules\n", encoding="utf-8")
            target = root / "target"
            target.mkdir()
            contracts = self._make_contracts()
            layout = self._make_layout(root, source_rule)
            txn = install.Transaction()

            install.install_rules("codex", "project", target, contracts, layout, txn, False, "c1", "2026-01-01T00:00:00Z", [])
            install.install_rules("qoder", "project", target, contracts, layout, txn, False, "c2", "2026-01-02T00:00:00Z", [])

            content = (target / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("myflow:managed:begin platform=codex", content)
            self.assertIn("myflow:managed:end platform=codex", content)
            self.assertIn("myflow:managed:begin platform=qoder", content)
            self.assertIn("myflow:managed:end platform=qoder", content)

    def test_clear_qoder_block_preserves_codex_block(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_rule = root / "source" / "rules" / "AGENTS.md"
            source_rule.parent.mkdir(parents=True)
            source_rule.write_text("# Shared Rules\n", encoding="utf-8")
            target = root / "target"
            target.mkdir()
            contracts = self._make_contracts()
            layout = self._make_layout(root, source_rule)
            txn = install.Transaction()

            install.install_rules("codex", "project", target, contracts, layout, txn, False, "c1", "2026-01-01T00:00:00Z", [])
            install.install_rules("qoder", "project", target, contracts, layout, txn, False, "c2", "2026-01-02T00:00:00Z", [])

            agents_md = target / "AGENTS.md"
            install.clear_managed_block(agents_md, install.Transaction(), False, "qoder")

            content = agents_md.read_text(encoding="utf-8")
            self.assertIn("myflow:managed:begin platform=codex", content)
            self.assertIn("myflow:managed:end platform=codex", content)
            self.assertNotIn("platform=qoder", content)

    def test_legacy_untagged_block_migrated_on_install(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_rule = root / "source" / "rules" / "AGENTS.md"
            source_rule.parent.mkdir(parents=True)
            source_rule.write_text("# Rules\n", encoding="utf-8")
            target = root / "target"
            target.mkdir()

            legacy_content = (
                "<!-- myflow:managed:begin v=1 commit=old generated=2025-01-01T00:00:00Z -->\n"
                "# Legacy Rules\n"
                "<!-- myflow:managed:end -->\n"
            )
            agents_md = target / "AGENTS.md"
            agents_md.write_text(legacy_content, encoding="utf-8")

            install.install_rules(
                "codex", "project", target, self._make_contracts(), self._make_layout(root, source_rule),
                install.Transaction(), False, "new-commit", "2026-06-29T00:00:00Z", [],
            )

            content = agents_md.read_text(encoding="utf-8")
            self.assertIn("myflow:managed:begin platform=codex", content)
            self.assertIn("myflow:managed:end platform=codex", content)
            self.assertNotIn("myflow:managed:begin v=", content)

    def test_render_qoder_agent_has_effort_and_color(self) -> None:
        agent = install.AgentDefinition(
            source=Path("meta-pm.md"),
            name="meta-pm",
            description="PM agent",
            instructions="You are a PM.",
            model=None,
            model_reasoning_effort="medium",
            tools="Read,Write",
            extra_fields=(),
        )
        content = install.render_qoder_agent(agent, "abc", "2026-06-29T00:00:00Z")
        self.assertIn('name: "meta-pm"', content)
        self.assertIn("effort: medium", content)
        self.assertIn('color: "orange"', content)
        self.assertIn('tools: "Read,Write"', content)
        self.assertIn("myflow-managed:", content)
        self.assertIn("You are a PM.", content)

    def test_render_qoder_agent_minimal_effort_maps_to_low(self) -> None:
        agent = install.AgentDefinition(
            source=Path("meta-dev.md"),
            name="meta-dev",
            description="Dev agent",
            instructions="You are a dev.",
            model=None,
            model_reasoning_effort="minimal",
            tools=None,
            extra_fields=(),
        )
        content = install.render_qoder_agent(agent, "abc", "2026-06-29T00:00:00Z")
        self.assertIn("effort: low", content)
        self.assertNotIn("effort: minimal", content)


if __name__ == "__main__":
    unittest.main()
