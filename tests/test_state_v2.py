from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from meta_flow import cli
from meta_flow.state import current


LEGACY_STATE = """---
project_id: "demo-project"
workflow_mode: "standard"
current_phase: "story-execution"
blocked: false
active_change: "CR-123"
next_action: "run CP6 for ready stories"
orchestrator_session:
  pending_gate: "CP5"
  pending_checklist_path: "process/checkpoints/CP5-ALL-STORIES-LLD-BATCH.md"
---

# Legacy State
"""


class StateV2Tests(unittest.TestCase):
    def test_init_creates_current_state_and_all_base_ledgers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            exit_code = current.main(["init", "--project-root", str(root), "--project-id", "demo-project"])

            self.assertEqual(0, exit_code)
            state = current.load_current_state(root)
            self.assertEqual("demo-project", state["project_id"])
            for name in (
                "CR-LEDGER.ndjson",
                "STORY-LEDGER.ndjson",
                "CHECKPOINT-LEDGER.ndjson",
                "HANDOFF-LEDGER.ndjson",
                "AGENT-DISPATCH-LEDGER.ndjson",
                "GATE-LEDGER.ndjson",
                "RUN-LEDGER.ndjson",
                "READ-EXPANSION-LEDGER.ndjson",
            ):
                self.assertTrue((root / "process" / "state" / name).is_file(), name)

    def test_init_is_idempotent_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current.main(["init", "--project-root", str(root), "--project-id", "demo-project"])
            first_text = (root / "process" / "state" / "STATE.current.json").read_text(encoding="utf-8")

            exit_code = current.main(["init", "--project-root", str(root), "--project-id", "other-project"])

            self.assertEqual(0, exit_code)
            second_text = (root / "process" / "state" / "STATE.current.json").read_text(encoding="utf-8")
            self.assertEqual(first_text, second_text)

    def test_migrate_v2_creates_lightweight_current_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "process").mkdir()
            (root / "process" / "STATE.md").write_text(LEGACY_STATE, encoding="utf-8")

            exit_code = current.main(["migrate-v2", "--project-root", str(root)])

            self.assertEqual(0, exit_code)
            state = current.load_current_state(root)
            self.assertEqual(2, state["schema_version"])
            self.assertEqual("demo-project", state["project_id"])
            self.assertEqual("story-execution", state["current_phase"])
            self.assertEqual("CR-123", state["active_change"])
            self.assertEqual("CP5", state["pending_gate"])
            self.assertNotIn("history", state)
            self.assertNotIn("cr_tracking", state)
            self.assertTrue((root / "process" / "state" / "GATE-LEDGER.ndjson").is_file())
            self.assertTrue((root / "process" / "state" / "RUN-LEDGER.ndjson").is_file())

    def test_render_writes_human_summary_from_current_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = current.default_current_state(root)
            state["project_id"] = "demo-project"
            state["active_change"] = "CR-123"
            current.write_current_state(root, state)

            exit_code = current.main(["render", "--project-root", str(root)])

            self.assertEqual(0, exit_code)
            text = (root / "process" / "STATE.md").read_text(encoding="utf-8")
            self.assertIn("# Current Meta Flow State", text)
            self.assertIn("Project: demo-project", text)
            self.assertIn("Active CR: CR-123", text)
            self.assertIn("process/state/STATE.current.json", text)

    def test_check_fails_when_current_state_contains_long_running_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = current.default_current_state(root)
            state["history"] = []
            current.write_current_state(root, state)

            output = StringIO()
            with redirect_stdout(output):
                exit_code = current.main(["check", "--project-root", str(root)])

            self.assertEqual(1, exit_code)
            self.assertIn("must not store long-running field: history", output.getvalue())

    def test_status_prefers_state_current_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = current.default_current_state(root)
            state["project_id"] = "demo-project"
            state["current_phase"] = "delivered"
            state["next_action"] = {"type": "done", "text": "choose next CR"}
            current.write_current_state(root, state)
            cwd = Path.cwd()
            try:
                import os

                os.chdir(root)
                output = StringIO()
                with redirect_stdout(output):
                    cli._print_status()
            finally:
                os.chdir(cwd)

            text = output.getvalue()
            self.assertIn("STATE:", text)
            self.assertIn("STATE.current.json", text)
            self.assertIn("current_phase: delivered", text)
            self.assertIn("next_action: choose next CR", text)


if __name__ == "__main__":
    unittest.main()
