from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from meta_flow.checks import token_budget


class TokenBudgetTests(unittest.TestCase):
    def test_estimate_tokens_uses_chars_div_four_ceiling(self) -> None:
        self.assertEqual(0, token_budget.estimate_tokens(""))
        self.assertEqual(1, token_budget.estimate_tokens("a"))
        self.assertEqual(1, token_budget.estimate_tokens("abcd"))
        self.assertEqual(2, token_budget.estimate_tokens("abcde"))

    def test_scan_marks_large_default_read_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            process = root / "process"
            process.mkdir()
            (process / "STATE.md").write_text("x" * 13000, encoding="utf-8")
            (process / "DEVELOPMENT-PLAN.yaml").write_text("plan: true\n", encoding="utf-8")

            rows = {row.rel_path: row for row in token_budget.scan_workspace(root)}

            self.assertEqual("DENY_DEFAULT", rows["process/STATE.md"].default_read_status)
            self.assertTrue(rows["process/STATE.md"].over_budget)
            self.assertEqual("DENY_DEFAULT", rows["process/DEVELOPMENT-PLAN.yaml"].default_read_status)

    def test_doctor_tokens_does_not_require_state_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "process").mkdir()
            (root / "process" / "changes").mkdir()
            (root / "process" / "changes" / "CR-001.md").write_text("short", encoding="utf-8")

            output = StringIO()
            with redirect_stdout(output):
                exit_code = token_budget.main(["--mode", "tokens", "--project-root", str(root)])

            self.assertEqual(0, exit_code)
            self.assertIn("Token Doctor: OK", output.getvalue())
            self.assertIn("process/changes/CR-001.md", output.getvalue())

    def test_doctor_artifacts_fails_when_state_summary_over_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            process = root / "process"
            process.mkdir()
            (process / "STATE.md").write_text("x" * 13000, encoding="utf-8")

            output = StringIO()
            with redirect_stdout(output):
                exit_code = token_budget.main(["--mode", "artifacts", "--project-root", str(root)])

            self.assertEqual(1, exit_code)
            self.assertIn("Artifact Doctor: FAIL", output.getvalue())
            self.assertIn("process/STATE.md", output.getvalue())

    def test_cr_summary_is_budgeted_and_not_deny_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary = root / "process" / "changes" / "summaries" / "CR-001.summary.json"
            summary.parent.mkdir(parents=True)
            summary.write_text('{"id":"CR-001"}\n', encoding="utf-8")
            full = root / "process" / "changes" / "CR-001.md"
            full.write_text("# full CR\n", encoding="utf-8")

            rows = {row.rel_path: row for row in token_budget.scan_workspace(root)}

            self.assertEqual("ALLOW_SUMMARY", rows["process/changes/summaries/CR-001.summary.json"].default_read_status)
            self.assertEqual("cr_summary", rows["process/changes/summaries/CR-001.summary.json"].artifact_kind)
            self.assertEqual("DENY_DEFAULT", rows["process/changes/CR-001.md"].default_read_status)

    def test_unowned_budget_remediation_uses_canonical_retention_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            self.assertEqual(
                "process/policies/RETENTION-POLICY.json",
                token_budget._remediation_ref(root, ""),
            )


if __name__ == "__main__":
    unittest.main()
