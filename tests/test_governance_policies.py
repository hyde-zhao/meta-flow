from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from meta_flow.policies import governance


class GovernancePolicyTests(unittest.TestCase):
    def test_init_check_and_render_default_governance_policies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            output = StringIO()
            with redirect_stdout(output):
                exit_code = governance.main(["init", "--project-root", str(root)])

            self.assertEqual(0, exit_code)
            self.assertTrue((root / "process" / "policies" / "SOURCE-OF-TRUTH-MAP.yaml").is_file())
            self.assertTrue((root / "process" / "policies" / "RETENTION-POLICY.json").is_file())
            self.assertEqual(([], []), governance.validate_truth_map(root))
            self.assertEqual(([], []), governance.validate_retention_policy(root))
            policy = json.loads(
                (root / "process" / "policies" / "RETENTION-POLICY.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                {
                    "window_days": 90,
                    "keep_latest_n_events": 500,
                    "keep_latest_n_cr": 20,
                    "archive_rule": "summary-index-backup",
                },
                policy["ledgers"]["compaction"],
            )

            render_code = governance.main(["truth-map-render", "--project-root", str(root)])

            self.assertEqual(0, render_code)
            rendered = root / "docs" / "design" / "SOURCE-OF-TRUTH-MAP.md"
            self.assertTrue(rendered.is_file())
            self.assertIn("process/policies/SOURCE-OF-TRUTH-MAP.yaml", rendered.read_text(encoding="utf-8"))

    def test_truth_map_rejects_generated_summary_as_machine_truth(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            governance.write_default_truth_map(root)
            path = root / "process" / "policies" / "SOURCE-OF-TRUTH-MAP.yaml"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["objects"]["human_state_summary"]["machine_truth"] = True
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            errors, _warnings = governance.validate_truth_map(root)

            self.assertIn("human_state_summary truth_role=generated_summary must not set machine_truth=true", errors)
            self.assertIn("process/STATE.md must not be machine_truth", errors)

    def test_retention_policy_rejects_closed_cr_full_default_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            governance.write_default_retention_policy(root)
            path = root / "process" / "policies" / "RETENTION-POLICY.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["closed_cr"]["default_context"] = "full"
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            errors, _warnings = governance.validate_retention_policy(root)

            self.assertIn("closed_cr.default_context must be summary_only", errors)

    def test_retention_policy_rejects_invalid_or_unknown_compaction_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            governance.write_default_retention_policy(root)
            path = root / "process" / "policies" / "RETENTION-POLICY.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["ledgers"]["compaction"]["window_days"] = 0
            data["ledgers"]["compaction"]["unexpected"] = True
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            errors, _warnings = governance.validate_retention_policy(root)

            self.assertTrue(any("unknown fields: unexpected" in error for error in errors))

            del data["ledgers"]["compaction"]["unexpected"]
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            errors, _warnings = governance.validate_retention_policy(root)
            self.assertTrue(any("window_days must be a positive integer" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
