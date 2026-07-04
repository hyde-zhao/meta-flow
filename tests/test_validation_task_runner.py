from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from meta_flow.validation import task_runner


class ValidationTaskRunnerTests(unittest.TestCase):
    def test_real_lake_readonly_dry_run_writes_structured_evidence_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            status = task_runner.main(
                [
                    "run",
                    "--cr",
                    "CR-155",
                    "--profile",
                    "real-lake-readonly",
                    "--reruns",
                    "2",
                    "--project-root",
                    str(root),
                ]
            )

            self.assertEqual(0, status)
            latest = root / "process" / "evidence" / "CR-155.real-lake-readonly.validation.index.json"
            self.assertTrue(latest.is_file())
            evidence = json.loads(latest.read_text(encoding="utf-8"))
            self.assertEqual("PLANNED", evidence["status"])
            self.assertFalse(evidence["execute"])
            self.assertEqual(2, len(evidence["runs"]))
            self.assertEqual(["real_lake_read"], evidence["allowed_capabilities"])
            self.assertIn("lake_write", evidence["forbidden_operations"])
            self.assertIn("rerun_consistency", evidence["required_evidence"])
            rerun = json.loads((root / evidence["rerun_comparison_ref"]).read_text(encoding="utf-8"))
            self.assertEqual("PLANNED", rerun["status"])

    def test_execute_requires_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            status = task_runner.main(
                [
                    "run",
                    "--cr",
                    "CR-155",
                    "--profile",
                    "real-lake-readonly",
                    "--reruns",
                    "2",
                    "--execute",
                    "--project-root",
                    str(root),
                ]
            )

            self.assertEqual(2, status)

    def test_execute_records_consistent_reruns_for_successful_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command = f"{sys.executable} -c 'print(42)'"

            status = task_runner.main(
                [
                    "run",
                    "--cr",
                    "CR-155",
                    "--profile",
                    "real-lake-readonly",
                    "--reruns",
                    "2",
                    "--command",
                    command,
                    "--execute",
                    "--project-root",
                    str(root),
                ]
            )

            self.assertEqual(0, status)
            evidence = json.loads(
                (root / "process" / "evidence" / "CR-155.real-lake-readonly.validation.index.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual("PASS", evidence["status"])
            self.assertTrue(evidence["execute"])
            self.assertTrue(all(run["status"] == "PASS" for run in evidence["runs"]))
            rerun = json.loads((root / evidence["rerun_comparison_ref"]).read_text(encoding="utf-8"))
            self.assertEqual("PASS", rerun["status"])
            self.assertTrue(rerun["consistent"])

    def test_ops_counter_detects_forbidden_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ops = root / "ops-counter.json"
            ops.write_text(
                json.dumps(
                    {
                        "real_lake_read_count": 12,
                        "lake_write_count": 1,
                        "catalog_write_count": 0,
                        "runtime_connection_count": 0,
                        "trading_count": 0,
                        "broker_access_count": 0,
                        "repository_publication_count": 0,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            status = task_runner.main(
                [
                    "run",
                    "--cr",
                    "CR-155",
                    "--profile",
                    "real-lake-readonly",
                    "--reruns",
                    "2",
                    "--ops-counter",
                    str(ops),
                    "--project-root",
                    str(root),
                ]
            )

            self.assertEqual(1, status)
            evidence = json.loads(
                (root / "process" / "evidence" / "CR-155.real-lake-readonly.validation.index.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual("FAIL", evidence["status"])
            forbidden = json.loads((root / evidence["forbidden_ops_summary_ref"]).read_text(encoding="utf-8"))
            self.assertEqual("FAIL", forbidden["status"])
            self.assertEqual(["lake_write"], forbidden["violations"])


if __name__ == "__main__":
    unittest.main()
