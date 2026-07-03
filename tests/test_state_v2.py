from __future__ import annotations

import json
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


def write_state_fixture(root: Path, state: dict) -> None:
    path = root / "process" / "state" / "STATE.current.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    current.ensure_base_ledgers(root)


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
            write_state_fixture(root, state)

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

    def test_unknown_current_state_key_warns_in_audit_and_errors_in_enforce(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = current.default_current_state(root)
            state["surprise"] = "extra"
            write_state_fixture(root, state)

            audit_output = StringIO()
            with redirect_stdout(audit_output):
                audit_code = current.main(["check", "--project-root", str(root), "--mode", "audit"])
            enforce_output = StringIO()
            with redirect_stdout(enforce_output):
                enforce_code = current.main(["check", "--project-root", str(root), "--mode", "enforce"])

            self.assertEqual(0, audit_code)
            self.assertIn("- WARN: STATE.current.json contains unknown field: surprise", audit_output.getvalue())
            self.assertEqual(1, enforce_code)
            self.assertIn("- ERROR: STATE.current.json contains unknown field: surprise", enforce_output.getvalue())

    def test_optional_current_state_keys_are_explicitly_allowed_and_budgeted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = current.default_current_state(root)
            state["pending_checklist_path"] = "process/checkpoints/CP5-ALL-STORIES-LLD-BATCH.md"
            state["project_state_ref"] = "process/state/STATE.current.json"
            current.write_current_state(root, state)

            output = StringIO()
            with redirect_stdout(output):
                exit_code = current.main(["check", "--project-root", str(root), "--mode", "enforce"])

            self.assertEqual(0, exit_code, output.getvalue())
            self.assertNotIn("unknown field", output.getvalue())

    def test_default_current_state_keys_are_partitioned_by_required_and_optional_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_keys = set(current.default_current_state(root))

            self.assertIn("routing_ref", current.CURRENT_REQUIRED_KEYS)
            self.assertNotIn("routing_ref", current.CURRENT_OPTIONAL_KEYS)
            self.assertTrue(current.CURRENT_REQUIRED_KEYS <= state_keys)
            self.assertEqual(set(), current.CURRENT_REQUIRED_KEYS & current.CURRENT_OPTIONAL_KEYS)
            self.assertTrue(state_keys <= current.CURRENT_ALLOWED_KEYS)

    def test_routing_ref_is_required_for_current_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = current.default_current_state(root)
            state.pop("routing_ref")
            write_state_fixture(root, state)

            output = StringIO()
            with redirect_stdout(output):
                exit_code = current.main(["check", "--project-root", str(root), "--mode", "enforce"])

            self.assertEqual(1, exit_code)
            self.assertIn("missing required field: routing_ref", output.getvalue())

    def test_current_state_field_budgets_cover_all_budgeted_fields(self) -> None:
        cases = {
            "next_action": {"type": "continue", "text": "x" * 513},
            "source_refs": [{"path": f"process/context/{index}.json", "kind": "context"} for index in range(25)],
            "open_risks": [{"id": f"R-{index}", "summary": "x"} for index in range(17)],
            "authz_policy_refs": [f"POLICY-{index}" for index in range(17)],
            "routing_ref": "x" * 257,
            "active_context_ref": "x" * 257,
            "pending_checklist_path": "x" * 257,
            "project_state_ref": "x" * 257,
        }
        for field, value in cases.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                state = current.default_current_state(root)
                state[field] = value
                write_state_fixture(root, state)

                output = StringIO()
                with redirect_stdout(output):
                    exit_code = current.main(["check", "--project-root", str(root), "--mode", "enforce"])

                self.assertEqual(1, exit_code)
                self.assertIn(field, output.getvalue())
                self.assertIn("budget", output.getvalue())

    def test_current_state_field_budget_warns_in_audit_and_errors_in_enforce(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = current.default_current_state(root)
            state["next_action"] = {"type": "continue", "text": "x" * 513}
            write_state_fixture(root, state)

            audit_output = StringIO()
            with redirect_stdout(audit_output):
                audit_code = current.main(["check", "--project-root", str(root), "--mode", "audit"])
            enforce_output = StringIO()
            with redirect_stdout(enforce_output):
                enforce_code = current.main(["check", "--project-root", str(root), "--mode", "enforce"])

            self.assertEqual(0, audit_code)
            self.assertIn("- WARN: next_action.text exceeds budget", audit_output.getvalue())
            self.assertEqual(1, enforce_code)
            self.assertIn("- ERROR: next_action.text exceeds budget", enforce_output.getvalue())

    def test_current_state_budget_values_match_cp5_approved_contract(self) -> None:
        self.assertEqual({"max_text_bytes": 512, "max_json_bytes": 768}, {
            "max_text_bytes": current.CURRENT_FIELD_BUDGETS["next_action"]["max_text_bytes"],
            "max_json_bytes": current.CURRENT_FIELD_BUDGETS["next_action"]["max_json_bytes"],
        })
        self.assertEqual(24, current.CURRENT_FIELD_BUDGETS["source_refs"]["max_items"])
        self.assertEqual(256, current.CURRENT_FIELD_BUDGETS["source_refs"]["max_item_json_bytes"])
        self.assertEqual(4096, current.CURRENT_FIELD_BUDGETS["source_refs"]["max_json_bytes"])
        self.assertEqual(16, current.CURRENT_FIELD_BUDGETS["open_risks"]["max_items"])
        self.assertEqual(256, current.CURRENT_FIELD_BUDGETS["open_risks"]["max_item_json_bytes"])
        self.assertEqual(2048, current.CURRENT_FIELD_BUDGETS["open_risks"]["max_json_bytes"])
        self.assertEqual(16, current.CURRENT_FIELD_BUDGETS["authz_policy_refs"]["max_items"])
        self.assertEqual(128, current.CURRENT_FIELD_BUDGETS["authz_policy_refs"]["max_item_json_bytes"])
        self.assertEqual(1024, current.CURRENT_FIELD_BUDGETS["authz_policy_refs"]["max_json_bytes"])
        self.assertEqual(256, current.CURRENT_FIELD_BUDGETS["routing_ref"]["max_bytes"])
        self.assertEqual(256, current.CURRENT_FIELD_BUDGETS["active_context_ref"]["max_bytes"])
        self.assertEqual(256, current.CURRENT_FIELD_BUDGETS["pending_checklist_path"]["max_bytes"])
        self.assertEqual(256, current.CURRENT_FIELD_BUDGETS["project_state_ref"]["max_bytes"])

    def test_secret_like_current_state_fields_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = current.default_current_state(root)
            state["next_action"] = {"type": "continue", "secret_token": "redacted"}
            write_state_fixture(root, state)

            output = StringIO()
            with redirect_stdout(output):
                exit_code = current.main(["check", "--project-root", str(root), "--mode", "enforce"])

            self.assertEqual(1, exit_code)
            self.assertIn("credential/secret/token/cookie/private-key", output.getvalue())

    def test_disallowed_current_state_fields_still_regress_to_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = current.default_current_state(root)
            state["parallel_execution"] = {}
            write_state_fixture(root, state)

            output = StringIO()
            with redirect_stdout(output):
                exit_code = current.main(["check", "--project-root", str(root), "--mode", "audit"])

            self.assertEqual(1, exit_code)
            self.assertIn("must not store long-running field: parallel_execution", output.getvalue())

    def test_write_current_state_rejects_invalid_payload_without_partial_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = current.default_current_state(root)
            state["history"] = []

            with self.assertRaises(ValueError):
                current.write_current_state(root, state)

            self.assertFalse((root / "process" / "state" / "STATE.current.json").exists())

    def test_update_current_state_rejects_unknown_patch_key_without_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = current.default_current_state(root)
            current.write_current_state(root, state)
            path = root / "process" / "state" / "STATE.current.json"
            before = path.read_text(encoding="utf-8")

            with self.assertRaises(current.StateValidationError) as raised:
                current.update_current_state(root, {"last_actions": []}, actor="test", reason="unknown key")

            self.assertIn("unknown_patch_key", str(raised.exception))
            self.assertEqual(before, path.read_text(encoding="utf-8"))

    def test_update_current_state_deep_merges_dict_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = current.default_current_state(root)
            state["next_action"] = {"type": "old", "text": "old text"}
            current.write_current_state(root, state)

            updated = current.update_current_state(root, {"next_action": {"text": "new text"}})

            self.assertEqual({"type": "old", "text": "new text"}, updated["next_action"])
            persisted = current.load_current_state(root)
            self.assertEqual({"type": "old", "text": "new text"}, persisted["next_action"])

    def test_update_current_state_replaces_lists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = current.default_current_state(root)
            state["source_refs"] = [{"path": "process/context/old.json", "kind": "context"}]
            current.write_current_state(root, state)

            updated = current.update_current_state(
                root,
                {"source_refs": [{"path": "process/context/new.json", "kind": "context"}]},
            )

            self.assertEqual([{"path": "process/context/new.json", "kind": "context"}], updated["source_refs"])

    def test_update_current_state_none_is_replacement_not_delete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = current.default_current_state(root)
            state["active_context_ref"] = "process/context/old.json"
            current.write_current_state(root, state)

            updated = current.update_current_state(root, {"active_context_ref": None})

            self.assertIn("active_context_ref", updated)
            self.assertIsNone(updated["active_context_ref"])
            self.assertIn("active_context_ref", current.load_current_state(root))

    def test_update_current_state_budget_failure_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = current.default_current_state(root)
            state["next_action"] = {"type": "continue", "text": "short"}
            current.write_current_state(root, state)
            path = root / "process" / "state" / "STATE.current.json"
            before = path.read_text(encoding="utf-8")

            with self.assertRaises(current.StateValidationError) as raised:
                current.update_current_state(root, {"next_action": {"text": "x" * 513}})

            self.assertIn("field_budget", str(raised.exception))
            self.assertEqual(before, path.read_text(encoding="utf-8"))

    def test_update_current_state_missing_state_is_not_created(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            with self.assertRaises(FileNotFoundError):
                current.update_current_state(root, {"active_change": "CR-001"})

            self.assertFalse((root / "process" / "state" / "STATE.current.json").exists())


if __name__ == "__main__":
    unittest.main()
