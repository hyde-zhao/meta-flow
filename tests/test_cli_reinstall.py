from __future__ import annotations

import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from meta_flow import cli


class CLIReinstallTests(unittest.TestCase):
    def test_reinstall_runs_uninstall_then_install(self) -> None:
        calls: list[tuple[str, list[str]]] = []
        args = ["codex", "--scope", "user", "--component", "rules", "--dry-run"]

        with patch.object(cli, "_run_installer", side_effect=lambda command, forwarded: calls.append((command, forwarded))):
            cli._run_reinstaller(args)

        self.assertEqual(
            [
                ("uninstall", ["codex", "--scope", "user", "--component", "rules", "--dry-run"]),
                ("install", args),
            ],
            calls,
        )

    def test_reinstall_strips_install_only_args_from_uninstall_phase(self) -> None:
        calls: list[tuple[str, list[str]]] = []
        args = [
            "claude",
            "--scope",
            "project",
            "--project-dir",
            "/tmp/project",
            "--component",
            "agent",
            "--agent",
            "meta-dev",
            "--skill",
            "state-router",
            "--permissive",
        ]

        with patch.object(cli, "_run_installer", side_effect=lambda command, forwarded: calls.append((command, forwarded))):
            cli._run_reinstaller(args)

        self.assertEqual(
            [
                (
                    "uninstall",
                    ["claude", "--scope", "project", "--project-dir", "/tmp/project", "--component", "agent"],
                ),
                ("install", args),
            ],
            calls,
        )

    def test_reinstall_supports_legacy_platform_option(self) -> None:
        self.assertEqual(
            ["codex", "--scope", "user"],
            cli._reinstall_uninstall_args(["--platform", "codex", "--scope", "user"]),
        )

    def test_reinstall_requires_platform(self) -> None:
        with self.assertRaises(SystemExit):
            cli._reinstall_uninstall_args(["--scope", "user"])

    def test_reinstall_help_does_not_invoke_installer(self) -> None:
        output = StringIO()
        with patch.object(cli, "_run_installer") as installer:
            with redirect_stdout(output):
                cli._run_reinstaller(["--help"])

        installer.assert_not_called()
        self.assertIn("usage: meta-flow reinstall", output.getvalue())

    def test_top_level_help_human_audit_example_includes_required_evidence(self) -> None:
        output = StringIO()

        with redirect_stdout(output):
            cli._print_help()

        help_text = output.getvalue()
        self.assertIn("context read-log --path process/STATE.md --reason human_audit", help_text)
        self.assertIn(
            "--reason-evidence-json "
            "'{\"authorization_ref\":\"process/checkpoints/AUDIT.md\"}'",
            help_text,
        )


if __name__ == "__main__":
    unittest.main()
