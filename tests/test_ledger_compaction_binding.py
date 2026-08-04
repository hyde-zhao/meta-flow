from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from meta_flow.state import ledger_compaction


def _init_sibling_binding(root: Path, *, process_path: str = "meta-flow-process") -> tuple[Path, Path]:
    release = root / "meta-flow"
    process = root / "meta-flow-process"
    for repository in (release, process):
        repository.mkdir(parents=True)
        subprocess.run(["git", "init", "-b", "main"], cwd=repository, check=True, capture_output=True)
    binding = release / ".meta-flow" / "workspace.yaml"
    binding.parent.mkdir()
    binding.write_text(
        "schema_version: 1\nlayout_version: independent-process-repo-v1\nworkflow_model: vnext\n"
        "project_id: fixture-project\nrepo_role: release\nroute_mode: sibling-binding\nprocess_repo:\n"
        f"  anchor: workspace_parent\n  relative_path: {process_path}\n",
        encoding="utf-8",
    )
    (process / ".meta-flow-process.yaml").write_text(
        "schema_version: 1\nlayout_version: independent-process-repo-v1\nworkflow_model: vnext\n"
        "project_id: fixture-project\nrepo_role: process\nroute_mode: sibling-binding\nrelease_repo:\n"
        "  anchor: workspace_parent\n  relative_path: meta-flow\n",
        encoding="utf-8",
    )
    (process / "PROJECT.yaml").write_text("schema_version: 1\nproject_id: fixture-project\nname: Fixture\nstatus: active\n", encoding="utf-8")
    return release, process


class LedgerCompactionBindingTests(unittest.TestCase):
    def test_default_policy_resolves_canonical_json_through_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process = _init_sibling_binding(Path(directory))
            policy = process / "policies/RETENTION-POLICY.json"
            policy.parent.mkdir(parents=True)
            policy.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "ledgers": {
                            "compaction": {
                                "window_days": 14,
                                "keep_latest_n_events": 25,
                                "keep_latest_n_cr": 4,
                                "archive_rule": "summary-index-backup",
                            }
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            retention = ledger_compaction.load_retention_policy(project_root=release)

            self.assertEqual(14, retention.window_days)
            self.assertEqual(25, retention.keep_latest_n_events)
            self.assertEqual(4, retention.keep_latest_n_cr)

    def test_sibling_ledger_policy_and_apply_receipt_use_logical_refs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process = _init_sibling_binding(Path(directory))
            ledger = process / "state/custom.ndjson"
            ledger.parent.mkdir(parents=True)
            ledger.write_text(
                "".join(json.dumps({"event_id": f"E-{index}", "event_type": "fixture", "timestamp": f"2020-01-0{index + 1}T00:00:00+00:00"}) + "\n" for index in range(3)),
                encoding="utf-8",
            )
            policy = process / "policies/custom.yaml"
            policy.parent.mkdir(parents=True)
            policy.write_text("window_days: 1\nkeep_latest_n_events: 1\nkeep_latest_n_cr: 1\n", encoding="utf-8")

            retention = ledger_compaction.load_retention_policy(Path("process/policies/custom.yaml"), project_root=release)
            plan = ledger_compaction.plan_ledger_compaction(Path("process/state/custom.ndjson"), project_root=release, policy=retention)
            dry_run = ledger_compaction.format_plan(plan)
            result = ledger_compaction.apply_compaction(plan)

            self.assertIn("ledger: process/state/custom.ndjson", dry_run)
            self.assertEqual("process/state/custom.ndjson", result["source_ledger"])
            self.assertTrue(result["summary_ref"].startswith("process/archive/ledger/"))
            self.assertNotIn(str(process.resolve()), json.dumps(result))

    def test_outside_quant_lab_symlink_and_invalid_binding_block_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release, process = _init_sibling_binding(root)
            outside = root / "outside.ndjson"
            outside.write_text("", encoding="utf-8")
            (process / "state").mkdir()
            (process / "state/escape.ndjson").symlink_to(outside)
            (process / "policies").mkdir()
            (process / "policies/escape.yaml").symlink_to(outside)

            for ref in (Path(str(outside)), Path("process/quant-lab/state/ledger.ndjson"), Path("process/state/escape.ndjson")):
                with self.assertRaises(ValueError):
                    ledger_compaction.plan_ledger_compaction(ref, project_root=release)
            for ref in (Path(str(outside)), Path("process/policies/escape.yaml")):
                with self.assertRaises(ValueError):
                    ledger_compaction.load_retention_policy(ref, project_root=release)
            self.assertFalse((process / "archive").exists())

            invalid_release, _ = _init_sibling_binding(root / "invalid", process_path="missing-process")
            output = StringIO()
            with redirect_stdout(output):
                code = ledger_compaction.main(["compact", "--project-root", str(invalid_release), "--ledger", "checkpoint"])
            self.assertEqual(2, code)
            self.assertIn("Ledger Compact BLOCKED", output.getvalue())


if __name__ == "__main__":
    unittest.main()
