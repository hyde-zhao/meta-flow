"""Tests for handoff dispatch evidence validator."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from meta_flow.checks import handoff_dispatch


def _handoff(dispatch_lines: list[str], body: str = "body") -> str:
    return "---\n" + "\n".join(dispatch_lines) + "\n---\n\n" + body + "\n"


class HandoffDispatchCheckTests(unittest.TestCase):
    def _write(self, directory: str | Path, name: str, dispatch_lines: list[str]) -> Path:
        path = Path(directory) / name
        path.write_text(_handoff(dispatch_lines), encoding="utf-8")
        return path

    def test_complete_subagent_passes(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, "h1.md", [
                "dispatch:",
                '  mode: "subagent"',
                '  canonical_role: "meta-dev"',
                '  dispatch_trigger: "phase-default"',
                '  tool_name: "spawn_agent"',
                '  agent_id: "a-123"',
                '  spawned_at: "2026-07-05T00:00:00+00:00"',
                '  completed_at: "2026-07-05T00:05:00+00:00"',
            ])
            self.assertEqual([], handoff_dispatch.validate_handoff_dispatch(path))

    def test_subagent_with_thread_id_passes(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, "h1.md", [
                "dispatch:",
                '  mode: "subagent"',
                '  canonical_role: "meta-qa"',
                '  dispatch_trigger: "critical-checkpoint"',
                '  tool_name: "send_input"',
                '  thread_id: "t-1"',
                '  resumed_at: "2026-07-05T00:00:00+00:00"',
                '  completed_at: "2026-07-05T00:05:00+00:00"',
            ])
            self.assertEqual([], handoff_dispatch.validate_handoff_dispatch(path))

    def test_subagent_missing_agent_id_fails(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, "h1.md", [
                "dispatch:",
                '  mode: "subagent"',
                '  canonical_role: "meta-dev"',
                '  dispatch_trigger: "phase-default"',
                '  tool_name: "spawn_agent"',
                '  spawned_at: "2026-07-05T00:00:00+00:00"',
                '  completed_at: "2026-07-05T00:05:00+00:00"',
            ])
            errors = handoff_dispatch.validate_handoff_dispatch(path)
            self.assertTrue(any("agent_id or thread_id" in e for e in errors))

    def test_subagent_missing_completed_at_fails(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, "h1.md", [
                "dispatch:",
                '  mode: "subagent"',
                '  canonical_role: "meta-dev"',
                '  dispatch_trigger: "phase-default"',
                '  tool_name: "spawn_agent"',
                '  agent_id: "a-1"',
                '  spawned_at: "2026-07-05T00:00:00+00:00"',
            ])
            errors = handoff_dispatch.validate_handoff_dispatch(path)
            self.assertTrue(any("completed_at" in e for e in errors))

    def test_subagent_missing_dispatch_trigger_fails(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, "h1.md", [
                "dispatch:",
                '  mode: "subagent"',
                '  canonical_role: "meta-dev"',
                '  tool_name: "spawn_agent"',
                '  agent_id: "a-1"',
                '  spawned_at: "2026-07-05T00:00:00+00:00"',
                '  completed_at: "2026-07-05T00:05:00+00:00"',
            ])
            errors = handoff_dispatch.validate_handoff_dispatch(path)
            self.assertTrue(any("dispatch_trigger" in e for e in errors))

    def test_subagent_missing_canonical_role_fails(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, "h1.md", [
                "dispatch:",
                '  mode: "subagent"',
                '  dispatch_trigger: "phase-default"',
                '  tool_name: "spawn_agent"',
                '  agent_id: "a-1"',
                '  spawned_at: "2026-07-05T00:00:00+00:00"',
                '  completed_at: "2026-07-05T00:05:00+00:00"',
            ])
            errors = handoff_dispatch.validate_handoff_dispatch(path)
            self.assertTrue(any("canonical_role" in e for e in errors))

    def test_complete_inline_fallback_passes(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, "h1.md", [
                "dispatch:",
                '  mode: "inline-fallback"',
                '  canonical_role: "meta-dev"',
                '  fallback_reason: "no subagent tool"',
                '  approved_by: "user"',
                '  approved_at: "2026-07-05T00:00:00+00:00"',
            ])
            self.assertEqual([], handoff_dispatch.validate_handoff_dispatch(path))

    def test_inline_fallback_missing_approved_by_fails(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, "h1.md", [
                "dispatch:",
                '  mode: "inline-fallback"',
                '  canonical_role: "meta-dev"',
                '  fallback_reason: "no subagent tool"',
            ])
            errors = handoff_dispatch.validate_handoff_dispatch(path)
            self.assertTrue(any("approved_by" in e for e in errors))

    def test_handoff_only_clean_passes(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, "h1.md", [
                "dispatch:",
                '  mode: "handoff-only"',
                '  canonical_role: "meta-dev"',
            ])
            self.assertEqual([], handoff_dispatch.validate_handoff_dispatch(path))

    def test_handoff_only_with_completed_at_fails(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, "h1.md", [
                "dispatch:",
                '  mode: "handoff-only"',
                '  canonical_role: "meta-dev"',
                '  completed_at: "2026-07-05T00:05:00+00:00"',
            ])
            errors = handoff_dispatch.validate_handoff_dispatch(path)
            self.assertTrue(any("handoff-only" in e and "completed_at" in e for e in errors))

    def test_unknown_mode_fails(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, "h1.md", [
                "dispatch:",
                '  mode: "dynamic"',
                '  canonical_role: "meta-dev"',
            ])
            errors = handoff_dispatch.validate_handoff_dispatch(path)
            self.assertTrue(any("not a known mode" in e for e in errors))

    def test_missing_dispatch_block_fails(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, "h1.md", [
                'semantic: "stage-dispatch"',
            ])
            errors = handoff_dispatch.validate_handoff_dispatch(path)
            self.assertTrue(any("missing dispatch block" in e for e in errors))

    def test_missing_frontmatter_fails(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "h1.md"
            path.write_text("no frontmatter here\n", encoding="utf-8")
            errors = handoff_dispatch.validate_handoff_dispatch(path)
            self.assertTrue(any("frontmatter" in e for e in errors))

    def test_empty_mode_fails(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, "h1.md", [
                "dispatch:",
                '  canonical_role: "meta-dev"',
            ])
            errors = handoff_dispatch.validate_handoff_dispatch(path)
            self.assertTrue(any("dispatch.mode is empty" in e for e in errors))

    def test_dir_scan_collects_multiple_files(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            handoff_dir = root / "process" / "handoffs"
            handoff_dir.mkdir(parents=True)
            self._write(handoff_dir, "good.md", [
                "dispatch:",
                '  mode: "subagent"',
                '  canonical_role: "meta-dev"',
                '  dispatch_trigger: "phase-default"',
                '  tool_name: "spawn_agent"',
                '  agent_id: "a-1"',
                '  spawned_at: "2026-07-05T00:00:00+00:00"',
                '  completed_at: "2026-07-05T00:05:00+00:00"',
            ])
            self._write(handoff_dir, "bad.md", [
                "dispatch:",
                '  mode: "subagent"',
                '  canonical_role: "meta-dev"',
            ])
            errors, checked = handoff_dispatch.validate_handoff_dispatch_dir(root)
            self.assertEqual(2, len(checked))
            self.assertTrue(any("bad.md" in e for e in errors))
            self.assertFalse(any("good.md" in e for e in errors))

    def test_dir_scan_skips_legacy_handoff_without_dispatch_contract(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            handoff_dir = root / "process" / "handoffs"
            handoff_dir.mkdir(parents=True)
            self._write(handoff_dir, "current.md", [
                "dispatch:",
                '  mode: "handoff-only"',
                '  canonical_role: "meta-dev"',
            ])
            self._write(handoff_dir, "legacy.md", ['semantic: "stage-dispatch"'])

            errors, checked = handoff_dispatch.validate_handoff_dispatch_dir(root)

            self.assertEqual([], errors)
            self.assertEqual(["current.md"], checked)

    def test_strict_dir_scan_requires_dispatch_contract_for_legacy_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            handoff_dir = root / "process" / "handoffs"
            handoff_dir.mkdir(parents=True)
            self._write(handoff_dir, "legacy.md", ['semantic: "stage-dispatch"'])

            errors, checked = handoff_dispatch.validate_handoff_dispatch_dir(root, strict_all=True)

            self.assertEqual(["legacy.md"], checked)
            self.assertTrue(any("missing dispatch block" in error for error in errors))

    def test_dir_scan_missing_handoff_dir_is_not_error(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            errors, checked = handoff_dispatch.validate_handoff_dispatch_dir(Path(d))
            self.assertEqual([], errors)
            self.assertEqual([], checked)

    def test_main_returns_nonzero_on_error(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, "bad.md", [
                "dispatch:",
                '  mode: "subagent"',
            ])
            exit_code = handoff_dispatch.main(["--handoff", str(path)])
            self.assertEqual(1, exit_code)

    def test_main_returns_zero_on_pass(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, "good.md", [
                "dispatch:",
                '  mode: "handoff-only"',
                '  canonical_role: "meta-dev"',
            ])
            exit_code = handoff_dispatch.main(["--handoff", str(path)])
            self.assertEqual(0, exit_code)


if __name__ == "__main__":
    unittest.main()
