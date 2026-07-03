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


def write_feature_registry(root: Path) -> Path:
    path = root / "docs" / "design" / "FEATURE-REGISTRY.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "features": [
                    {
                        "id": "FEAT-PG-004",
                        "feature_id": "FEAT-PG-004",
                        "title": "Capability / Feature Registry",
                        "owner_context": "project-governance",
                        "status": "active",
                        "risk_profile": "standard-code",
                        "design_doc_policy": "registry-only",
                        "module_paths": ["meta_flow/design/feature_registry.py"],
                        "public_api": ["meta_flow.design.feature_registry.resolve_refs"],
                        "forbidden_dependencies": [],
                        "authz_policy_refs": [],
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def write_capability_registry(root: Path, *, status: str = "active") -> Path:
    path = root / "docs" / "design" / "CAPABILITY-REGISTRY.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "capabilities": [
                    {
                        "id": "CAP-PG-REGISTRY-REFS",
                        "name": "Registry-backed refs",
                        "domain": "project-governance",
                        "status": status,
                        "owner_context": "project-governance",
                        "feature_refs": ["FEAT-PG-004"],
                        "aliases": ["registry refs"],
                        "deprecated_by": "CAP-PG-REGISTRY-REFS-V2" if status == "deprecated" else "",
                        "source_refs": ["CR037-S07"],
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def write_impact_rules(root: Path, rules: list[dict]) -> Path:
    path = root / "process" / "project" / "IMPACT-SURFACE-RULES.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "rules": rules,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
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

    def test_index_summary_and_brief_include_split_impact_fields_with_capability_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_feature_registry(root)
            write_capability_registry(root)
            write_cr(
                root,
                "CR-201",
                extra_frontmatter=(
                    'impact_capability_refs: ["registry refs"]\n'
                    'impact_feature_refs: ["FEAT-PG-004"]\n'
                    'impact_module_paths: ["meta_flow/workflow/cr_lifecycle.py"]\n'
                    'impact_policy_refs: ["NO_RUNTIME"]\n'
                    'impact_process_refs: ["process/changes"]\n'
                    'impact_runtime_refs: ["runtime:none"]\n'
                    'impact_data_refs: ["data:none"]'
                ),
            )

            self.assertEqual(0, cr_lifecycle.main(["index", "--project-root", str(root)]))
            self.assertEqual(0, cr_lifecycle.main(["summary", "--id", "CR-201", "--project-root", str(root)]))

            index = json.loads((root / "process" / "changes" / "CR-INDEX.json").read_text(encoding="utf-8"))
            item = index["items"][0]
            self.assertEqual(["registry refs"], item["impact_capability_refs"])
            self.assertEqual(["FEAT-PG-004"], item["impact_feature_refs"])
            self.assertEqual(["meta_flow/workflow/cr_lifecycle.py"], item["impact_module_paths"])
            self.assertEqual(["CAP-PG-REGISTRY-REFS"], item["impact_capability_normalized"])
            self.assertEqual("resolved", item["impact_capability_resolution"]["results"][0]["status"])
            self.assertEqual("alias", item["impact_capability_resolution"]["results"][0]["source"])

            summary = json.loads(
                (root / "process" / "changes" / "summaries" / "CR-201.summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(["NO_RUNTIME"], summary["impact_policy_refs"])
            self.assertEqual(["CAP-PG-REGISTRY-REFS"], summary["impact_capability_normalized"])

            brief = cr_lifecycle.render_cr_brief(root, "CR-201")
            self.assertIn("capability: registry refs", brief)
            self.assertIn("module: meta_flow/workflow/cr_lifecycle.py", brief)
            self.assertIn("capability.normalized: CAP-PG-REGISTRY-REFS", brief)

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

    def test_conflicts_detect_split_field_capability_overlap_after_alias_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_feature_registry(root)
            write_capability_registry(root)
            write_cr(root, "CR-201", extra_frontmatter='impact_capability_refs: ["registry refs"]')
            write_cr(root, "CR-202", extra_frontmatter='impact_capability_refs: ["CAP-PG-REGISTRY-REFS"]')
            cr_lifecycle.write_index(root)

            output = StringIO()
            with redirect_stdout(output):
                exit_code = cr_lifecycle.main(["conflicts", "--id", "CR-202", "--project-root", str(root)])

            self.assertEqual(1, exit_code)
            self.assertIn("CR-202 overlaps CR-201", output.getvalue())
            self.assertIn("CAP-PG-REGISTRY-REFS", output.getvalue())

    def test_impact_report_marks_unresolved_capability_refs_as_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_feature_registry(root)
            write_capability_registry(root)
            write_cr(root, "CR-201", extra_frontmatter='impact_capability_refs: ["CAP-PG-UNKNOWN"]')

            output = StringIO()
            with redirect_stdout(output):
                exit_code = cr_lifecycle.main(["impact-report", "--project-root", str(root)])

            self.assertEqual(0, exit_code)
            report = json.loads(output.getvalue())
            self.assertEqual("enforce", report["mode"])
            self.assertEqual(1, report["summary"]["blocker_count"])
            self.assertEqual("CAP-PG-UNKNOWN", report["items"][0]["blockers"][0]["input_ref"])
            self.assertEqual("unresolved", report["items"][0]["blockers"][0]["status"])
            self.assertEqual("E_REF_UNRESOLVED", report["items"][0]["blockers"][0]["code"])

    def test_impact_report_preserves_uncategorized_legacy_surface_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_feature_registry(root)
            write_capability_registry(root)
            write_cr(root, "CR-201", impact_surface='"CAP-PG-REGISTRY-REFS", "some_custom_domain"')

            output = StringIO()
            with redirect_stdout(output):
                exit_code = cr_lifecycle.main(["impact-report", "--project-root", str(root)])

            self.assertEqual(0, exit_code)
            report = json.loads(output.getvalue())
            self.assertEqual(1, report["summary"]["uncategorized_cr_count"])
            self.assertEqual(1, report["summary"]["uncategorized_legacy_count"])
            item = report["items"][0]
            self.assertEqual(["CAP-PG-REGISTRY-REFS"], item["derived_from_legacy"]["impact_capability_refs"])
            self.assertEqual(["some_custom_domain"], item["uncategorized_legacy"])
            self.assertEqual(
                [
                    {
                        "candidate_id": "CR-201-IMPACT-UNCATEGORIZED",
                        "kind": "manual-impact-classification",
                        "summary": "CR-201: manually classify uncategorized legacy impact_surface values",
                        "input_refs": ["some_custom_domain"],
                        "recommended_action": "Add explicit impact_* split fields or extend classification rules in a follow-up Story.",
                        "write_policy": "candidate-only",
                    }
                ],
                item["followup_candidates"],
            )

    def test_brief_shows_uncategorized_legacy_impact_followup_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_feature_registry(root)
            write_capability_registry(root)
            write_cr(root, "CR-201", impact_surface='"CAP-PG-REGISTRY-REFS", "some_custom_domain"')
            cr_lifecycle.write_summary(root, "CR-201", cr_lifecycle.summary_from_cr_file(root, root / "process" / "changes" / "CR-201.md"))

            brief = cr_lifecycle.render_cr_brief(root, "CR-201")

            self.assertIn("## 未分类 legacy impact_surface", brief)
            self.assertIn("- some_custom_domain", brief)
            self.assertIn("follow-up candidate: CR-201-IMPACT-UNCATEGORIZED", brief)

    def test_brief_can_enforce_capability_resolution_mode_for_deprecated_refs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_feature_registry(root)
            write_capability_registry(root, status="deprecated")
            write_cr(root, "CR-201", extra_frontmatter='impact_capability_refs: ["CAP-PG-REGISTRY-REFS"]')
            cr_lifecycle.write_summary(root, "CR-201", cr_lifecycle.summary_from_cr_file(root, root / "process" / "changes" / "CR-201.md"))

            audit_brief = cr_lifecycle.render_cr_brief(root, "CR-201")
            enforce_brief = cr_lifecycle.render_cr_brief(root, "CR-201", mode="enforce")

            self.assertIn("capability.resolution_mode: audit", audit_brief)
            self.assertNotIn("capability ref blockers", audit_brief)
            self.assertIn("capability.resolution_mode: enforce", enforce_brief)
            self.assertIn("CAP-PG-REGISTRY-REFS: deprecated E_REF_DEPRECATED", enforce_brief)

    def test_impact_report_applies_project_legacy_classification_rules(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_feature_registry(root)
            write_capability_registry(root)
            write_impact_rules(
                root,
                [
                    {
                        "match": "prefix",
                        "pattern": "MOD-",
                        "target_field": "impact_module_paths",
                        "strip_prefix": True,
                    },
                    {
                        "match": "prefix",
                        "pattern": "SVC-",
                        "target_field": "impact_runtime_refs",
                    },
                ],
            )
            write_cr(root, "CR-201", impact_surface='"MOD-meta_flow/project/rules.py", "SVC-order-router"')

            output = StringIO()
            with redirect_stdout(output):
                exit_code = cr_lifecycle.main(["impact-report", "--project-root", str(root)])

            self.assertEqual(0, exit_code)
            item = json.loads(output.getvalue())["items"][0]
            self.assertEqual(["meta_flow/project/rules.py"], item["derived_from_legacy"]["impact_module_paths"])
            self.assertEqual(["SVC-order-router"], item["derived_from_legacy"]["impact_runtime_refs"])
            self.assertEqual([], item["uncategorized_legacy"])
            self.assertEqual([], item["followup_candidates"])

    def test_brief_uses_project_legacy_classification_rules(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_feature_registry(root)
            write_capability_registry(root)
            write_impact_rules(
                root,
                [
                    {
                        "match": "prefix",
                        "pattern": "MOD-",
                        "target_field": "impact_module_paths",
                        "strip_prefix": True,
                    }
                ],
            )
            write_cr(root, "CR-201", impact_surface='"MOD-meta_flow/project/rules.py"')
            cr_lifecycle.write_summary(root, "CR-201", cr_lifecycle.summary_from_cr_file(root, root / "process" / "changes" / "CR-201.md"))

            brief = cr_lifecycle.render_cr_brief(root, "CR-201")

            self.assertNotIn("## 未分类 legacy impact_surface", brief)

    def test_invalid_impact_rule_target_field_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_feature_registry(root)
            write_capability_registry(root)
            write_impact_rules(
                root,
                [
                    {
                        "match": "prefix",
                        "pattern": "MOD-",
                        "target_field": "impact_unknown_refs",
                    }
                ],
            )
            write_cr(root, "CR-201", impact_surface='"MOD-meta_flow/project/rules.py"')

            with self.assertRaises(ValueError) as raised:
                cr_lifecycle.build_impact_report(root)

            self.assertIn("target_field is invalid", str(raised.exception))

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
