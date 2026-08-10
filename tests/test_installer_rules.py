from __future__ import annotations

import json
import sys
import tempfile
import tomllib
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from delivery.scripts import install


def _tree_snapshot(root: Path) -> dict[str, tuple[str, bytes]]:
    """记录隔离安装根的完整文件/目录状态，用于断言 mutation=0。"""

    snapshot: dict[str, tuple[str, bytes]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        snapshot[relative] = (
            ("directory", b"") if path.is_dir() else ("file", path.read_bytes())
        )
    return snapshot


def _run_project_installer(target: Path, mode: str = "install") -> tuple[str, str]:
    argv = ["install.py"]
    if mode != "install":
        argv.append(mode)
    argv.extend(
        [
            "codex",
            "--scope",
            "project",
            "--project-dir",
            str(target),
            "--component",
            "full",
        ]
    )
    stdout = StringIO()
    stderr = StringIO()
    with (
        patch.object(sys, "argv", argv),
        redirect_stdout(stdout),
        redirect_stderr(stderr),
    ):
        install.main()
    return stdout.getvalue(), stderr.getvalue()


def _rewrite_skill_entries_as_legacy_directories(target: Path) -> Path:
    manifest_path = install.manifest_path(target, "project")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    current = payload["installs"][0]
    retained = [entry for entry in current["entries"] if entry["kind"] != "skill"]
    skill_names = sorted(
        {entry["name"] for entry in current["entries"] if entry["kind"] == "skill"}
    )
    retained.extend(
        {
            "kind": "skill",
            "name": name,
            "path": str(target / ".agents" / "skills" / name),
            "remove_path": str(target / ".agents" / "skills" / name),
        }
        for name in skill_names
    )
    current["entries"] = retained
    manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest_path


class InstallerRulesTests(unittest.TestCase):
    def test_delivery_runtime_contract_renders_skill_and_agent_mirrors(self) -> None:
        contract = json.loads(
            Path("delivery/rules/DELIVERY-RUNTIME-CONTRACT.json").read_text(
                encoding="utf-8"
            )
        )
        marker_commit = "abc1234"
        generated = "2026-08-10T00:00:00Z"

        for pair in contract["source_mirror_pairs"]:
            canonical = Path(pair["canonical_ref"])
            renderer = pair["renderer"]
            with self.subTest(mirror=pair["mirror_ref"]):
                if renderer == "markdown-audit":
                    source = canonical.read_text(encoding="utf-8")
                    rendered = install.inject_markdown_audit(
                        source, marker_commit, generated
                    )
                    self.assertIn("myflow-managed: version=1.0.0", rendered)
                    _, source_body = install.parse_frontmatter(source)
                    marker = install.markdown_audit(marker_commit, generated)
                    _, rendered_body = install.parse_frontmatter(
                        rendered.replace(marker, "", 1)
                    )
                    self.assertEqual(
                        source_body.strip(),
                        rendered_body.strip(),
                    )
                    continue

                agent = install.load_canonical_agent(canonical, permissive=False)
                self.assertIsNotNone(agent)
                assert agent is not None
                if renderer == "claude-agent":
                    rendered = install.render_claude_agent(
                        agent, marker_commit, generated
                    )
                    self.assertTrue(rendered.endswith(agent.instructions + "\n"))
                else:
                    codex_agent = install.codex_agent_definition(agent)
                    rendered = install.render_codex_agent(
                        codex_agent, marker_commit, generated
                    )
                    payload = tomllib.loads(rendered)
                    self.assertEqual(
                        agent.instructions,
                        payload["developer_instructions"].rstrip(),
                    )
                    self.assertEqual("meta-doc", payload["name"])

    def test_canonical_rules_publish_routine_work_efficiency_contract(self) -> None:
        content = Path("delivery/rules/AGENTS.md").read_text(encoding="utf-8")

        for expected in (
            "mode=routine-four-stage",
            "dispatch_mode=direct",
            "legacy_cp_compatibility=false",
            "targeted → compatibility → full",
            "最多读取 5 个对象",
            "plan 与 apply 不得共享 context",
            "summary_insufficient",
            "actual mutation 为 0",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, content)

    def test_process_consuming_canonical_skills_require_portable_resolver_contract(self) -> None:
        skill_files = sorted(Path("delivery/skills").glob("*/SKILL.md"))
        process_consumers = [
            path for path in skill_files if "process/" in path.read_text(encoding="utf-8")
        ]

        self.assertEqual(29, len(process_consumers))
        for path in process_consumers:
            content = path.read_text(encoding="utf-8")
            with self.subTest(path=path.as_posix()):
                self.assertIn("## vNext 过程引用契约", content)
                self.assertIn("meta-flow project resolve-ref", content)
                self.assertIn("resolved_path", content)
                self.assertIn("不得自行拼 sibling", content)
                self.assertIn("不构造 legacy capability", content)

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
        claude_markdown = install.render_claude_agent(
            source_agents[0], "abc", "2026-07-10T00:00:00Z"
        )
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
            self.assertEqual(
                [{"kind": "managed-block", "path": str(agents_md), "remove_path": str(agents_md)}],
                manifest_entries,
            )

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

    def test_transaction_guard_rolls_back_system_exit_after_prior_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            managed_leaf = root / "managed.md"
            managed_leaf.write_text("before\n", encoding="utf-8")
            transaction = install.Transaction()

            with self.assertRaises(SystemExit) as raised:
                with install.rollback_on_failure(transaction, dry_run=False):
                    install.remove_path(managed_leaf, transaction, dry_run=False)
                    install.fail("injected failure after first mutation")

            self.assertEqual(1, raised.exception.code)
            self.assertEqual(b"before\n", managed_leaf.read_bytes())

    def test_legacy_directory_uninstall_blocks_before_any_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target"
            target.mkdir()
            (target / "README.md").write_text("user readme\n", encoding="utf-8")
            user_skill_file = target / ".agents" / "skills" / "state-router" / "user-note.txt"
            user_skill_file.parent.mkdir(parents=True)
            user_skill_file.write_text("preserve\n", encoding="utf-8")
            _run_project_installer(target)
            manifest_path = _rewrite_skill_entries_as_legacy_directories(target)
            before = _tree_snapshot(target)
            manifest_before = manifest_path.read_bytes()

            with self.assertRaises(SystemExit) as raised:
                _run_project_installer(target, "uninstall")

            self.assertEqual(1, raised.exception.code)
            self.assertEqual(before, _tree_snapshot(target))
            self.assertEqual(manifest_before, manifest_path.read_bytes())
            self.assertEqual("preserve\n", user_skill_file.read_text(encoding="utf-8"))

    def test_install_migrates_legacy_skill_directories_before_safe_uninstall(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target"
            target.mkdir()
            (target / "README.md").write_text("user readme\n", encoding="utf-8")
            (target / "AGENTS.md").write_text("# User rules\n", encoding="utf-8")
            user_skill_file = target / ".agents" / "skills" / "state-router" / "user-note.txt"
            user_skill_file.parent.mkdir(parents=True)
            user_skill_file.write_text("preserve\n", encoding="utf-8")
            baseline = _tree_snapshot(target)

            _run_project_installer(target)
            manifest_path = _rewrite_skill_entries_as_legacy_directories(target)
            _run_project_installer(target)

            migrated = json.loads(manifest_path.read_text(encoding="utf-8"))["installs"][0]
            skill_entries = [entry for entry in migrated["entries"] if entry["kind"] == "skill"]
            self.assertTrue(skill_entries)
            self.assertTrue(all(Path(entry["remove_path"]).is_file() for entry in skill_entries))

            _run_project_installer(target, "uninstall")

            self.assertEqual(baseline, _tree_snapshot(target))
            self.assertEqual("preserve\n", user_skill_file.read_text(encoding="utf-8"))

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
            self.assertEqual(
                [{"kind": "managed-block", "path": str(claude_md), "remove_path": str(claude_md)}],
                manifest_entries,
            )

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
                        "project": {
                            "rules": "AGENTS.md",
                            "agents": ".codex/agents",
                            "skills": ".agents/skills",
                        },
                    }
                },
                "qoder": {
                    "scopes": {
                        "project": {
                            "rules": "AGENTS.md",
                            "agents": ".qoder/agents",
                            "skills": ".qoder/skills",
                        },
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
                "qoder",
                "project",
                target,
                self._make_contracts(),
                self._make_layout(root, source_rule),
                install.Transaction(),
                False,
                "test-commit",
                "2026-06-29T00:00:00Z",
                manifest_entries,
            )

            agents_md = target / "AGENTS.md"
            content = agents_md.read_text(encoding="utf-8")
            self.assertIn("myflow:managed:begin platform=qoder", content)
            self.assertIn("myflow:managed:end platform=qoder", content)
            self.assertEqual(
                [{"kind": "managed-block", "path": str(agents_md), "remove_path": str(agents_md)}],
                manifest_entries,
            )

    def test_qoder_rules_install_fails_when_source_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.mkdir()

            with self.assertRaises(SystemExit) as raised:
                install.install_rules(
                    "qoder",
                    "project",
                    target,
                    self._make_contracts(),
                    self._make_layout(root, None),
                    install.Transaction(),
                    True,
                    "test-commit",
                    "2026-06-29T00:00:00Z",
                    [],
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

            install.install_rules(
                "codex",
                "project",
                target,
                contracts,
                layout,
                txn,
                False,
                "c1",
                "2026-01-01T00:00:00Z",
                [],
            )
            install.install_rules(
                "qoder",
                "project",
                target,
                contracts,
                layout,
                txn,
                False,
                "c2",
                "2026-01-02T00:00:00Z",
                [],
            )

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

            install.install_rules(
                "codex",
                "project",
                target,
                contracts,
                layout,
                txn,
                False,
                "c1",
                "2026-01-01T00:00:00Z",
                [],
            )
            install.install_rules(
                "qoder",
                "project",
                target,
                contracts,
                layout,
                txn,
                False,
                "c2",
                "2026-01-02T00:00:00Z",
                [],
            )

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
                "codex",
                "project",
                target,
                self._make_contracts(),
                self._make_layout(root, source_rule),
                install.Transaction(),
                False,
                "new-commit",
                "2026-06-29T00:00:00Z",
                [],
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
