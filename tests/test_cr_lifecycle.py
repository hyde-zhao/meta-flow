from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from meta_flow.state import current
from meta_flow.context_pack import builder
from meta_flow.checks import cp_result
from meta_flow.workflow import cr_lifecycle


def write_cr(root: Path, cr_id: str, *, status: str = "active", conflict_keys: str = "", impact_surface: str = "") -> Path:
    path = root / "process" / "changes" / f"{cr_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
cr_id: "{cr_id}"
cr_type: "architecture"
title: "{cr_id} title"
lifecycle_status: "{status}"
readiness_status: "not_ready"
gate_status: "cp6_pending"
gate_profile: "standard"
conflict_keys: [{conflict_keys}]
impact_surface: [{impact_surface}]
authz_policy_refs: [NO_CREDENTIAL_READ]
risk_refs: [RISK-001]
---

## 变更描述

本 CR 用于测试生命周期治理。
""",
        encoding="utf-8",
    )
    return path


class CRLifecycleTests(unittest.TestCase):
    def test_bootstrap_cr_writes_active_cr_cp0_context_and_state_refs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = current.default_current_state(root, project_id="target-project")
            current.write_current_state(root, state)
            current.render_state_file(root)

            paths = cr_lifecycle.bootstrap_cr(
                root,
                cr_id="CR-001",
                title="target adoption bootstrap",
                scope="Initialize target project adoption readiness.",
                readiness="ready_with_risk",
            )

            self.assertTrue(paths["cr"].is_file())
            self.assertTrue(paths["summary"].is_file())
            self.assertTrue(paths["index"].is_file())
            self.assertTrue(paths["legacy_index"].is_file())
            self.assertTrue(paths["context"].is_file())
            self.assertTrue(paths["cp0_result"].is_file())
            current_state = current.load_current_state(root)
            self.assertEqual("CR-001", current_state["active_change"])
            self.assertEqual("process/context/CP0-CR001.context.json", current_state["active_context_ref"])
            index = json.loads((root / "process" / "changes" / "CR-INDEX.json").read_text(encoding="utf-8"))
            self.assertEqual("CR-001", index["items"][0]["id"])
            self.assertEqual("ready_with_risk", index["items"][0]["readiness"])
            legacy_index = (root / "process" / "changes" / "CR-INDEX.yaml").read_text(encoding="utf-8")
            self.assertIn('active_crs: ["CR-001"]', legacy_index)
            self.assertIn('readiness_status: "ready_with_risk"', legacy_index)
            context_errors, _context_warnings = builder.validate_context_pack(paths["context"], project_root=root)
            self.assertEqual([], context_errors)
            cp0_errors, _cp0_warnings = cp_result.validate_cp_result(paths["cp0_result"], project_root=root)
            self.assertEqual([], cp0_errors)
            events = [
                json.loads(line)
                for line in (root / "process" / "state" / "CR-LEDGER.ndjson").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual("active", events[0]["event"])
            self.assertEqual("ready_with_risk", events[0]["readiness"])
            self.assertEqual("process/checks/CP0-CR-001-BOOTSTRAP.result.json", events[0]["cp0_result_ref"])

            cr_text = paths["cr"].read_text(encoding="utf-8")
            self.assertIn('readiness_status: "ready_with_risk"', cr_text)

    def test_index_and_summary_generate_machine_readable_refs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_cr(root, "CR-101", conflict_keys="data_contract", impact_surface="quant_lab/data")

            self.assertEqual(0, cr_lifecycle.main(["index", "--project-root", str(root)]))
            self.assertEqual(0, cr_lifecycle.main(["summary", "--id", "CR-101", "--project-root", str(root)]))

            index = json.loads((root / "process" / "changes" / "CR-INDEX.json").read_text(encoding="utf-8"))
            self.assertEqual("CR-101", index["items"][0]["id"])
            self.assertEqual("architecture", index["items"][0]["cr_type"])
            self.assertEqual(["data_contract"], index["items"][0]["conflict_keys"])
            summary = json.loads(
                (root / "process" / "changes" / "summaries" / "CR-101.summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual("CR-101", summary["id"])
            self.assertEqual("architecture", summary["cr_type"])
            self.assertEqual("process/changes/CR-101.md", summary["full_ref"])

    def test_close_writes_summary_evidence_index_and_ledger_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_cr(root, "CR-101")

            exit_code = cr_lifecycle.main(
                ["close", "--id", "CR-101", "--readiness", "READY_WITH_RISK", "--project-root", str(root)]
            )

            self.assertEqual(0, exit_code)
            summary = json.loads(
                (root / "process" / "changes" / "summaries" / "CR-101.summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual("closed", summary["status"])
            self.assertEqual("READY_WITH_RISK", summary["readiness"])
            self.assertTrue((root / "process" / "archive" / "CR-101" / "evidence-index.json").is_file())
            events = [
                json.loads(line)
                for line in (root / "process" / "state" / "CR-LEDGER.ndjson").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual("closed", events[0]["event"])
            self.assertEqual("process/changes/summaries/CR-101.summary.json", events[0]["summary_ref"])

    def test_check_fails_when_closed_cr_is_still_active_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_cr(root, "CR-101")
            cr_lifecycle.close_cr(root, "CR-101", readiness="READY")
            state = current.default_current_state(root)
            state["active_change"] = "CR-101"
            current.write_current_state(root, state)

            output = StringIO()
            with redirect_stdout(output):
                exit_code = cr_lifecycle.main(["check", "--project-root", str(root)])

            self.assertEqual(1, exit_code)
            self.assertIn("active_change points to closed CR: CR-101", output.getvalue())

    def test_conflicts_detects_active_overlap_from_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_cr(root, "CR-101", conflict_keys="data_contract", impact_surface="quant_lab/data")
            write_cr(root, "CR-102", conflict_keys="data_contract", impact_surface="quant_lab/research")
            cr_lifecycle.write_index(root)

            output = StringIO()
            with redirect_stdout(output):
                exit_code = cr_lifecycle.main(["conflicts", "--id", "CR-102", "--project-root", str(root)])

            self.assertEqual(1, exit_code)
            self.assertIn("CR-102 overlaps CR-101", output.getvalue())

    def test_check_rejects_invalid_cr_type_from_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_cr(root, "CR-101")
            cr_lifecycle.write_index(root)
            index_path = root / "process" / "changes" / "CR-INDEX.json"
            index = json.loads(index_path.read_text(encoding="utf-8"))
            index["items"][0]["cr_type"] = "requirement-change"
            index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            errors = cr_lifecycle.collect_check_errors(root)

            self.assertIn("CR index item CR-101: invalid cr_type requirement-change", errors)


if __name__ == "__main__":
    unittest.main()
