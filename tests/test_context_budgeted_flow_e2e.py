from __future__ import annotations

import fnmatch
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from meta_flow.checks import cp_result
from meta_flow.context_pack import builder, story_contract
from meta_flow.state import event_ledger
from meta_flow.workflow import story_evidence


FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "evals" / "fixtures" / "context-budgeted-meta-flow"


def copy_fixture(target: Path) -> Path:
    root = target / "context-budgeted-meta-flow"
    shutil.copytree(FIXTURE_ROOT, root)
    return root


def assert_no_denied_allowed_reads(testcase: unittest.TestCase, payload: dict[str, object]) -> None:
    denied = [str(item) for item in payload.get("denied_default_reads", [])]
    allowed = payload.get("allowed_reads", [])
    testcase.assertIsInstance(allowed, list)
    for entry in allowed:  # type: ignore[assignment]
        testcase.assertIsInstance(entry, dict)
        rel_path = str(entry.get("path") or "")
        testcase.assertTrue(rel_path)
        for pattern in denied:
            testcase.assertFalse(
                fnmatch.fnmatch(rel_path, pattern),
                f"allowed_reads must not include deny-default path {rel_path!r} matching {pattern!r}",
            )


class ContextBudgetedFlowE2ETests(unittest.TestCase):
    def test_fixture_runs_context_budgeted_chain_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = copy_fixture(Path(directory))
            story_path = root / "process" / "stories" / "STORY-MF013-S01.md"

            context, context_path = builder.build_context_pack(
                root,
                stage="CP6",
                profile="process-lite",
                cr_id="CR-001",
                story_id="STORY-MF013-S01",
                budget=12000,
                output=root / "process" / "context" / "CP6-CR001.context.json",
                write_policy=False,
            )
            context_errors, context_warnings = builder.validate_context_pack(context_path, project_root=root)
            self.assertEqual([], context_errors)
            self.assertEqual([], context_warnings)
            assert_no_denied_allowed_reads(self, context)
            context_allowed = {entry["path"] for entry in context["allowed_reads"]}
            self.assertIn("process/state/STATE.current.json", context_allowed)
            self.assertIn("process/changes/summaries/CR-001.summary.json", context_allowed)
            self.assertNotIn("process/STATE.md", context_allowed)
            self.assertNotIn("process/DEVELOPMENT-PLAN.yaml", context_allowed)
            self.assertNotIn("process/changes/CR-001.md", context_allowed)

            base_packet, base_packet_path = story_contract.build_story_packet(
                root,
                story_path=story_path,
                stage="BASE",
                cr_id="CR-001",
                budget=8000,
                write_policy=False,
            )
            base_errors, base_warnings = story_contract.validate_story_packet(base_packet_path, project_root=root)
            self.assertEqual([], base_errors)
            self.assertEqual([], base_warnings)
            assert_no_denied_allowed_reads(self, base_packet)

            work_packet, work_packet_path = story_contract.build_story_packet(
                root,
                story_path=story_path,
                stage="CP6",
                cr_id="CR-001",
                budget=8000,
                parent_context_ref=base_packet_path.relative_to(root).as_posix(),
                write_policy=False,
            )
            work_errors, work_warnings = story_contract.validate_story_packet(work_packet_path, project_root=root)
            self.assertEqual([], work_errors)
            self.assertEqual([], work_warnings)
            assert_no_denied_allowed_reads(self, work_packet)
            self.assertEqual("process/returns/STORY-MF013-S01.CP6.return.json", work_packet["expected_return_packet"])

            return_path = root / "process" / "returns" / "STORY-MF013-S01.CP6.return.json"
            return_errors, return_warnings = story_evidence.validate_return_packet(
                return_path,
                packet_path=work_packet_path,
                project_root=root,
            )
            self.assertEqual([], return_errors)
            self.assertEqual([], return_warnings)

            evidence, evidence_path = story_evidence.build_evidence_index(root, return_path=return_path)
            evidence_errors, evidence_warnings = story_evidence.validate_evidence_index(evidence_path, project_root=root)
            self.assertEqual([], evidence_errors)
            self.assertEqual([], evidence_warnings)
            self.assertEqual("process/returns/STORY-MF013-S01.CP6.return.json", evidence["return_ref"])

            result_path = root / "process" / "checks" / "CP6-STORY-MF013-S01.result.json"
            result_errors, result_warnings = cp_result.validate_cp_result(result_path, project_root=root)
            self.assertEqual([], result_errors)
            self.assertEqual([], result_warnings)

            summary_path = cp_result.render_summary_file(result_path)
            self.assertTrue(summary_path.is_file())
            self.assertIn("Decision: PASS", summary_path.read_text(encoding="utf-8"))

            ledger_path = cp_result.append_checkpoint_ledger(root, result_path=result_path)
            ledger_errors, ledger_warnings = event_ledger.validate_event_ledger(ledger_path, ledger_type="checkpoint")
            self.assertEqual([], ledger_errors)
            self.assertEqual([], ledger_warnings)

            dispatch_errors, dispatch_warnings = event_ledger.validate_event_ledger(
                root / "process" / "state" / "AGENT-DISPATCH-LEDGER.ndjson",
                ledger_type="dispatch",
            )
            self.assertEqual([], dispatch_errors)
            self.assertEqual([], dispatch_warnings)

    def test_fixture_rejects_return_that_escapes_story_write_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = copy_fixture(Path(directory))
            story_path = root / "process" / "stories" / "STORY-MF013-S01.md"
            _packet, work_packet_path = story_contract.build_story_packet(
                root,
                story_path=story_path,
                stage="CP6",
                cr_id="CR-001",
                budget=8000,
                write_policy=False,
            )
            return_path = root / "process" / "returns" / "STORY-MF013-S01.CP6.return.json"
            packet = json.loads(return_path.read_text(encoding="utf-8"))
            packet["touched_files"] = [{"path": "process/STATE.md", "change_type": "modified"}]
            return_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            errors, _warnings = story_evidence.validate_return_packet(
                return_path,
                packet_path=work_packet_path,
                project_root=root,
            )

            self.assertIn("touched file outside allowed_write_paths: process/STATE.md", errors)
            self.assertIn("touched file matches forbidden_write_paths: process/STATE.md", errors)


if __name__ == "__main__":
    unittest.main()
