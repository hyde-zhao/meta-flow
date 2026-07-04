from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from meta_flow.workflow import story_evidence


def write_plan(root: Path, stories: list[dict]) -> Path:
    path = root / "process" / "DEVELOPMENT-PLAN.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "project_id": "test-project",
                "version": 1,
                "story_management_truth_source": "process/DEVELOPMENT-PLAN.yaml",
                "waves": [
                    {
                        "wave": "W1",
                        "parallel_lld": True,
                        "parallel_dev": False,
                        "stories": stories,
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


class StoryPlanCheckTests(unittest.TestCase):
    def test_plan_check_accepts_development_plan_truth_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_plan(
                root,
                [
                    {
                        "story_id": "STORY-001",
                        "title": "Build validator",
                        "status": "dev-ready",
                        "tasks": [{"task_id": "TASK-001"}],
                    }
                ],
            )

            errors, warnings = story_evidence.validate_story_plan(root)

            self.assertEqual([], errors)
            self.assertEqual([], warnings)

    def test_plan_check_rejects_duplicate_story_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_plan(
                root,
                [
                    {"story_id": "STORY-001", "title": "A", "status": "draft"},
                    {"story_id": "STORY-001", "title": "B", "status": "draft"},
                ],
            )

            errors, _warnings = story_evidence.validate_story_plan(root)

            self.assertTrue(any("duplicate story_id" in error for error in errors))

    def test_plan_check_rejects_legacy_story_status_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_plan(root, [{"story_id": "STORY-001", "title": "A", "status": "dev-ready"}])
            status = root / "process" / "STORY-STATUS.md"
            status.write_text(
                "| Story ID | 标题 | Wave | 状态 |\n"
                "|---|---|---|---|\n"
                "| STORY-001 | A | W1 | verified |\n",
                encoding="utf-8",
            )

            errors, _warnings = story_evidence.validate_story_plan(root)

            self.assertEqual(
                ["legacy STORY-STATUS status conflict for STORY-001: plan=dev-ready legacy=verified"],
                errors,
            )

    def test_plan_check_reports_unknown_legacy_refs_as_warning_or_strict_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_plan(root, [{"story_id": "STORY-001", "title": "A", "status": "draft"}])
            backlog = root / "process" / "STORY-BACKLOG.md"
            backlog.write_text("- STORY-999 stale story\n", encoding="utf-8")
            feature = root / "docs" / "features" / "feature-a" / "TASKS.md"
            feature.parent.mkdir(parents=True, exist_ok=True)
            feature.write_text("- TASK-999 stale task for STORY-999\n", encoding="utf-8")

            errors, warnings = story_evidence.validate_story_plan(root)
            strict_errors, _strict_warnings = story_evidence.validate_story_plan(root, strict_legacy=True)

            self.assertEqual([], errors)
            self.assertTrue(any("STORY-999" in warning for warning in warnings))
            self.assertTrue(any("TASK-999" in warning for warning in warnings))
            self.assertTrue(any("STORY-999" in error for error in strict_errors))
            self.assertTrue(any("TASK-999" in error for error in strict_errors))

    def test_plan_check_cli_prints_warning_without_failing_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_plan(root, [{"story_id": "STORY-001", "title": "A", "status": "draft"}])
            (root / "process" / "STORY-BACKLOG.md").write_text("- STORY-999 stale story\n", encoding="utf-8")

            output = StringIO()
            with redirect_stdout(output):
                status = story_evidence.main(["plan-check", "--project-root", str(root)])

            self.assertEqual(0, status)
            self.assertIn("Story Plan Check: OK", output.getvalue())
            self.assertIn("WARN", output.getvalue())


if __name__ == "__main__":
    unittest.main()
