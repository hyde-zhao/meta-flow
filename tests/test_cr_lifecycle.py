from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from meta_flow.state import current
from meta_flow.context_pack import builder
from meta_flow.checks import cp_result
from meta_flow.workflow import cr_lifecycle


def write_cr(
    root: Path,
    cr_id: str,
    *,
    status: str = "active",
    conflict_keys: str = "",
    impact_surface: str = "",
    extra_frontmatter: str = "",
) -> Path:
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
{extra_frontmatter}
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

    def test_update_current_active_change_uses_controlled_state_api(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = current.default_current_state(root, project_id="target-project")
            current.write_current_state(root, state)

            with patch.object(cr_lifecycle.current, "update_current_state", wraps=current.update_current_state) as update:
                cr_lifecycle._update_current_active_change(root, "CR-001", "process/context/CP0-CR001.context.json")

            update.assert_called_once()
            _project_root, patch_payload = update.call_args.args
            self.assertEqual("CR-001", patch_payload["active_change"])
            self.assertEqual("process/context/CP0-CR001.context.json", patch_payload["active_context_ref"])
            self.assertEqual("meta_flow.workflow.cr_lifecycle", update.call_args.kwargs["actor"])
            self.assertEqual("bootstrap active change", update.call_args.kwargs["reason"])
            current_state = current.load_current_state(root)
            self.assertEqual("CR-001", current_state["active_change"])
            self.assertEqual("process/context/CP0-CR001.context.json", current_state["active_context_ref"])

    def test_index_and_summary_generate_machine_readable_refs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_cr(
                root,
                "CR-101",
                conflict_keys="data_contract",
                impact_surface="quant_lab/data",
                extra_frontmatter='goal_ref: "GOAL-001"\ngoal_statement: "建立目标导向 CR 汇总"\napproval_focus: "确认目标包而不是细任务"\ndecision_burden: "medium"\nsplit_rationale: "需要独立审计"\napprove_effect: "进入实现"\nnot_authorized_by_approve: ["runtime", "publish"]\nproduct_baseline_refresh_required: true\nrequired_phase: "requirement-clarification"\nrequired_agent: "meta-pm"\nrequired_gate: "CP2"\nblock_story_decomposition_until: "CP2-approved"\naffected_product_docs: ["docs/product/USE-CASES.md", "docs/product/REQUIREMENTS.md"]\naffected_use_cases: ["UC-08"]\nrouting_design_ref: "process/USE-CASES.md#UC-08"',
            )

            self.assertEqual(0, cr_lifecycle.main(["index", "--project-root", str(root)]))
            self.assertEqual(0, cr_lifecycle.main(["summary", "--id", "CR-101", "--project-root", str(root)]))

            index = json.loads((root / "process" / "changes" / "CR-INDEX.json").read_text(encoding="utf-8"))
            self.assertEqual("CR-101", index["items"][0]["id"])
            self.assertEqual("architecture", index["items"][0]["cr_type"])
            self.assertEqual(["data_contract"], index["items"][0]["conflict_keys"])
            self.assertEqual("GOAL-001", index["items"][0]["goal_ref"])
            self.assertEqual("确认目标包而不是细任务", index["items"][0]["approval_focus"])
            self.assertEqual("medium", index["items"][0]["decision_burden"])
            self.assertTrue(index["items"][0]["product_baseline_refresh_required"])
            self.assertEqual("requirement-clarification", index["items"][0]["required_phase"])
            self.assertEqual("meta-pm", index["items"][0]["required_agent"])
            self.assertEqual("CP2", index["items"][0]["required_gate"])
            self.assertEqual("CP2-approved", index["items"][0]["block_story_decomposition_until"])
            self.assertEqual(["docs/product/USE-CASES.md", "docs/product/REQUIREMENTS.md"], index["items"][0]["affected_product_docs"])
            self.assertEqual(["UC-08"], index["items"][0]["affected_use_cases"])
            self.assertEqual("process/USE-CASES.md#UC-08", index["items"][0]["routing_design_ref"])
            summary = json.loads(
                (root / "process" / "changes" / "summaries" / "CR-101.summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual("CR-101", summary["id"])
            self.assertEqual("architecture", summary["cr_type"])
            self.assertEqual("process/changes/CR-101.md", summary["full_ref"])
            self.assertEqual("建立目标导向 CR 汇总", summary["goal_statement"])
            self.assertEqual("cp6_pending", summary["gate_status"])
            self.assertEqual("确认目标包而不是细任务", summary["approval_focus"])
            self.assertEqual("需要独立审计", summary["split_rationale"])
            self.assertEqual(["runtime", "publish"], summary["not_authorized_by_approve"])
            self.assertTrue(summary["product_baseline_refresh_required"])
            self.assertEqual("requirement-clarification", summary["required_phase"])
            self.assertEqual("meta-pm", summary["required_agent"])
            self.assertEqual("CP2", summary["required_gate"])
            self.assertEqual("CP2-approved", summary["block_story_decomposition_until"])
            self.assertEqual(["docs/product/USE-CASES.md", "docs/product/REQUIREMENTS.md"], summary["affected_product_docs"])
            self.assertEqual(["UC-08"], summary["affected_use_cases"])
            self.assertEqual("process/USE-CASES.md#UC-08", summary["routing_design_ref"])
            legacy_index = (root / "process" / "changes" / "CR-INDEX.yaml").read_text(encoding="utf-8")
            self.assertIn('product_baseline_refresh_required: "true"', legacy_index)
            self.assertIn('required_phase: "requirement-clarification"', legacy_index)
            self.assertIn('required_agent: "meta-pm"', legacy_index)
            self.assertIn('required_gate: "CP2"', legacy_index)
            self.assertIn('block_story_decomposition_until: "CP2-approved"', legacy_index)

    def test_brief_and_goal_brief_render_goal_oriented_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_cr(
                root,
                "CR-101",
                extra_frontmatter='goal_ref: "GOAL-001"\ngoal_statement: "降低人工确认理解成本"\nuser_goal_impact: "用户先看目标影响"\ndecision_burden: "low"\nsplit_rationale: "与 runtime 授权边界不同"\napprove_effect: "进入 CP5"\nreject_effect: "回退需求澄清"\nnot_authorized_by_approve: ["credentials", "production_write"]',
            )
            cr_lifecycle.write_summary(root, "CR-101", cr_lifecycle.summary_from_cr_file(root, root / "process" / "changes" / "CR-101.md"))
            cr_lifecycle.write_index(root)

            brief = cr_lifecycle.render_cr_brief(root, "CR-101")
            goal_brief = cr_lifecycle.render_goal_brief(root, "GOAL-001")

            self.assertIn("降低人工确认理解成本", brief)
            self.assertIn("与 runtime 授权边界不同", brief)
            self.assertIn("credentials", brief)
            self.assertIn("CR-101", goal_brief)
            self.assertIn("用户先看目标影响", goal_brief)

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
