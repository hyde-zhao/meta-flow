from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from meta_flow.checks import cp_result
from meta_flow.state import current
from meta_flow.state import event_ledger


def write_minimal_state(root: Path) -> None:
    state = current.default_current_state(root)
    state["project_id"] = "fixture-project"
    current.write_current_state(root, state)


def cp6_result_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "checkpoint": "CP6",
        "checkpoint_id": "CP6-STORY-CR123-S01",
        "profile": "standard-code",
        "story_id": "STORY-CR123-S01",
        "cr_id": "CR-123",
        "context_ref": "process/context/stories/STORY-CR123-S01.CP6.work-packet.json",
        "dispatch_refs": ["ADE-0001"],
        "evidence_ref": "process/evidence/STORY-CR123-S01.CP6.index.json",
        "items": [
            {
                "id": "CP6-01",
                "category": "implementation",
                "name": "Implementation matches Story Context Contract",
                "status": "PASS",
                "severity": "BLOCKER",
                "evidence_refs": ["process/evidence/STORY-CR123-S01.CP6.index.json#changed_files"],
                "owner": "meta-dev",
                "route_on_fail": "rework_same_story",
                "waiver_ref": None,
                "notes": "",
            }
        ],
        "blockers": [],
        "waivers": [],
        "decision": "PASS",
        "next_route": "CP7",
        "checked_at": "2026-06-21T00:00:00+00:00",
    }


def write_cp6_result(root: Path, payload: dict[str, object] | None = None) -> Path:
    path = root / "process" / "checks" / "CP6-STORY-CR123-S01.result.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload or cp6_result_payload(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


class CPResultEventLedgerTests(unittest.TestCase):
    def test_cp_result_check_passes_for_valid_cp6_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = write_cp6_result(root)

            stream = StringIO()
            with redirect_stdout(stream):
                exit_code = cp_result.main(["result-check", "--result", str(result), "--project-root", str(root)])

            self.assertEqual(0, exit_code)
            self.assertIn("CP Result Check: OK", stream.getvalue())

    def test_cp_result_rejects_pass_with_blocking_item(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = cp6_result_payload()
            payload["items"] = [
                {
                    "id": "CP6-01",
                    "category": "implementation",
                    "name": "Forbidden paths not touched",
                    "status": "FAIL",
                    "severity": "BLOCKER",
                    "evidence_refs": [],
                    "owner": "meta-dev",
                    "route_on_fail": "rework_same_story",
                    "waiver_ref": None,
                    "notes": "",
                }
            ]
            result = write_cp6_result(root, payload)

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root)

            self.assertIn("decision cannot be PASS/PASS_WITH_RISK when blocking items exist", errors)

    def test_cp7_result_allows_needs_rework(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = cp6_result_payload()
            payload["checkpoint"] = "CP7"
            payload["checkpoint_id"] = "CP7-STORY-CR123-S01"
            payload["decision"] = "NEEDS_REWORK"
            payload["next_route"] = "NEEDS_REWORK"
            result = write_cp6_result(root, payload)

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root)

            self.assertEqual([], errors)

    def test_render_summary_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = write_cp6_result(root)

            output = cp_result.render_summary_file(result)

            self.assertTrue(output.is_file())
            self.assertIn("Decision: PASS", output.read_text(encoding="utf-8"))

    def test_checkpoint_ledger_append_and_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            result = write_cp6_result(root)
            cp_result.render_summary_file(result)

            ledger = cp_result.append_checkpoint_ledger(root, result_path=result)
            errors, warnings = event_ledger.validate_event_ledger(ledger, ledger_type="checkpoint")

            self.assertTrue(ledger.is_file())
            self.assertEqual([], errors)
            self.assertEqual([], warnings)

    def test_event_ledger_check_rejects_missing_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "process" / "state" / "CHECKPOINT-LEDGER.ndjson"
            ledger.parent.mkdir(parents=True, exist_ok=True)
            ledger.write_text(json.dumps({"event_id": "E-1", "event_type": "checkpoint_result"}) + "\n", encoding="utf-8")

            errors, _warnings = event_ledger.validate_event_ledger(ledger, ledger_type="checkpoint")

            self.assertIn("line 1: missing required field: checkpoint", errors)
            self.assertIn("line 1: missing required field: decision", errors)
            self.assertIn("line 1: missing required field: result_ref", errors)

    def test_event_cli_append_and_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "process" / "state" / "HANDOFF-LEDGER.ndjson"
            event_file = root / "event.json"
            event_file.write_text(
                json.dumps(
                    {
                        "event_id": "HE-0001",
                        "event_type": "handoff",
                        "stage": "CP6",
                        "from_role": "host-orchestrator",
                        "to_role": "meta-dev",
                        "context_ref": "process/context/stories/STORY.CP6.work-packet.json",
                        "status": "created",
                        "created_at": "2026-06-21T00:00:00+00:00",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            self.assertEqual(0, event_ledger.main(["append", "--ledger", str(ledger), "--event-file", str(event_file)]))
            self.assertEqual(0, event_ledger.main(["check", "--ledger", str(ledger), "--type", "handoff"]))
            stream = StringIO()
            with redirect_stdout(stream):
                exit_code = event_ledger.main(["list", "--ledger", str(ledger)])

            self.assertEqual(0, exit_code)
            self.assertIn("HE-0001\thandoff\tcreated", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
