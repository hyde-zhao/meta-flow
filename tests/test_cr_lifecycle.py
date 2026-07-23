from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from meta_flow.checks import cp_result, cr_tracking
from meta_flow.context_pack import builder
from meta_flow.project.onboarding import ProjectInitRequest, apply_project_init, plan_project_init
from meta_flow.project.onboarding_contract import (
    AUTHORIZATION_KIND,
    AUTHORIZATION_SOURCE,
    OnboardingAuthorization,
)
from meta_flow.project.process_route import _resolve_runtime_ref
from meta_flow.state import current
from meta_flow.workflow import cr_lifecycle


def init_binding_project(root: Path) -> tuple[Path, Path]:
    release = root / "fixture-release"
    release.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=release, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Meta Flow Test",
            "-c",
            "user.email=meta-flow@example.invalid",
            "commit",
            "--allow-empty",
            "-m",
            "initial",
        ],
        cwd=release,
        check=True,
        capture_output=True,
    )
    plan = plan_project_init(ProjectInitRequest(release, "fixture", "Fixture Project"))
    payload = plan.as_dict()
    apply_project_init(
        plan,
        OnboardingAuthorization(
            1,
            "cr-lifecycle-fixture",
            AUTHORIZATION_SOURCE,
            AUTHORIZATION_KIND,
            payload["operation"],
            payload["decision_ref"],
            payload["project_id"],
            payload["plan_digest"],
            payload["base_oids"],
            "2099-01-01T00:00:00+00:00",
        ),
    )
    return release, root / "fixture-process"


def write_cr(
    root: Path,
    cr_id: str,
    *,
    status: str = "active",
    conflict_keys: str = "",
    impact_surface: str = "",
    extra_frontmatter: str = "",
) -> Path:
    path = _resolve_runtime_ref(root, f"process/changes/{cr_id}.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
schema_version: 1
kind: cr
cr_id: "{cr_id}"
cr_type: "architecture"
title: "{cr_id} title"
lifecycle_status: "{status}"
readiness_status: "NOT_READY"
gate_status: "cp8_pending"
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
    def test_atomic_write_preserves_existing_mode_and_defaults_new_files_to_0644(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing = root / "existing.json"
            created = root / "created.json"
            existing.write_text("before\n", encoding="utf-8")
            existing.chmod(0o640)

            cr_lifecycle._atomic_write_text(existing, "after\n")
            cr_lifecycle._atomic_write_text(created, "created\n")

            self.assertEqual(0o640, existing.stat().st_mode & 0o777)
            self.assertEqual(0o644, created.stat().st_mode & 0o777)

    def test_binding_only_index_and_summary_write_to_process_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process = init_binding_project(Path(directory))
            cr_path = write_cr(release, "CR-055")

            summary = cr_lifecycle.summary_from_cr_file(release, cr_path)
            summary_path = cr_lifecycle.write_summary(release, "CR-055", summary)
            index_path = cr_lifecycle.write_index(release)

            self.assertEqual(
                process / "changes" / "summaries" / "CR-055.summary.json",
                summary_path,
            )
            self.assertEqual(process / "changes" / "CR-INDEX.json", index_path)
            self.assertFalse((release / "process").exists())

    def test_binding_only_status_sync_check_resolves_summary_and_preserves_worktree_modes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process = init_binding_project(Path(directory))
            cr_path = write_cr(release, "CR-055")
            cr_path.chmod(0o644)
            plan = cr_lifecycle.plan_status_sync(
                release,
                "CR-055",
                status="closed",
                readiness="READY_WITH_RISK",
                gate_status="cp8_closed",
            )

            result = cr_lifecycle.apply_status_sync(release, plan)

            self.assertEqual("PASS", result["status"])
            self.assertEqual([], cr_lifecycle.collect_check_errors(release))
            self.assertFalse((release / "process").exists())
            expected_refs = (
                process / "changes" / "CR-055.md",
                process / "changes" / "CR-INDEX.json",
                process / "changes" / "summaries" / "CR-055.summary.json",
                process / "archive" / "CR-055" / "evidence-index.json",
                process / "state" / "CR-LEDGER.ndjson",
            )
            self.assertTrue(all(path.is_file() for path in expected_refs))
            self.assertTrue(all(path.stat().st_mode & 0o777 == 0o644 for path in expected_refs))

    def test_index_rebuild_does_not_preserve_non_formal_candidate_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_cr(root, "CR-047")
            index_path = root / "process" / "changes" / "CR-INDEX.json"
            index_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "items": [
                            {
                                "id": "CR-033",
                                "status": "candidate",
                                "lifecycle_status": "candidate",
                                "readiness_status": "n/a",
                                "gate_status": "not_started",
                                "gate_profile": "runtime",
                                "kind": "runtime-authorization",
                                "formal_cr_path": "",
                                "source_tracking": "process/changes/FOLLOW-UP.md",
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            cr_lifecycle.write_index(root, rebuild_corrupt=True)

            rebuilt = json.loads(index_path.read_text(encoding="utf-8"))
            by_id = {item["id"]: item for item in rebuilt["items"]}
            self.assertEqual({"CR-047"}, set(by_id))
            self.assertNotIn("CR-033", by_id)

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
            self.assertFalse((root / "process" / "changes" / "CR-INDEX.yaml").exists())
            self.assertTrue(paths["context"].is_file())
            self.assertTrue(paths["cp0_result"].is_file())
            current_state = current.load_current_state(root)
            self.assertEqual("CR-001", current_state["active_change"])
            self.assertEqual("process/context/CP0-CR001.context.json", current_state["active_context_ref"])
            index = json.loads((root / "process" / "changes" / "CR-INDEX.json").read_text(encoding="utf-8"))
            self.assertEqual("CR-001", index["items"][0]["id"])
            self.assertEqual("ready_with_risk", index["items"][0]["readiness"])
            self.assertEqual("active", index["items"][0]["lifecycle_status"])
            self.assertEqual("ready_with_risk", index["items"][0]["readiness_status"])
            self.assertEqual("process/changes/CR-001.md", index["items"][0]["formal_cr_path"])
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

            self.assertEqual(0, cr_lifecycle.main(["index", "--project-root", str(root), "--apply"]))
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
            self.assertEqual("active", index["items"][0]["lifecycle_status"])
            self.assertEqual("NOT_READY", index["items"][0]["readiness_status"])
            self.assertEqual("process/changes/CR-101.md", index["items"][0]["formal_cr_path"])
            summary = json.loads(
                (root / "process" / "changes" / "summaries" / "CR-101.summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual("CR-101", summary["id"])
            self.assertEqual("architecture", summary["cr_type"])
            self.assertEqual("process/changes/CR-101.md", summary["full_ref"])
            self.assertEqual("建立目标导向 CR 汇总", summary["goal_statement"])
            self.assertEqual("cp8_pending", summary["gate_status"])
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
            self.assertFalse((root / "process" / "changes" / "CR-INDEX.yaml").exists())

    def test_cr_check_blocks_required_real_lake_validation_forbidden_by_authz(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_cr(
                root,
                "CR-155",
                extra_frontmatter=(
                    'authz_policy_refs: ["NO_REAL_LAKE_READ_OR_WRITE"]\n'
                    'required_evidence: ["real_lake_validation"]'
                ),
            )
            cr_lifecycle.write_index(root)

            errors = cr_lifecycle.collect_check_errors(root)

            self.assertTrue(any("required_evidence_forbidden_by_authz" in error for error in errors))

    def test_cr_summary_records_l3_review_for_implicit_real_lake_authz_gap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = write_cr(
                root,
                "CR-156",
                extra_frontmatter='required_evidence: ["real_lake_validation"]',
            )

            summary = cr_lifecycle.summary_from_cr_file(root, path)

            self.assertEqual("NEEDS_REVIEW", summary["scope_authz_consistency"]["decision"])
            self.assertEqual(
                "high_risk_validation_authz_boundary_not_explicit",
                summary["scope_authz_consistency"]["needs_review"][0]["code"],
            )

    def test_l2_prerequisite_conflict_requires_review_not_blocking_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = write_cr(
                root,
                "CR-157",
                extra_frontmatter=(
                    'authz_policy_refs: ["NO_REAL_LAKE_READ"]\n'
                    'required_evidence: ["oos_walkforward"]'
                ),
            )
            cr_lifecycle.write_index(root)

            errors = cr_lifecycle.collect_check_errors(root)
            summary = cr_lifecycle.summary_from_cr_file(root, path)

            self.assertFalse(any("required_evidence_prerequisite_authz_conflict" in error for error in errors))
            self.assertEqual("NEEDS_REVIEW", summary["scope_authz_consistency"]["decision"])
            self.assertEqual(
                "required_evidence_prerequisite_authz_conflict",
                summary["scope_authz_consistency"]["needs_review"][0]["code"],
            )

    def test_cr_summary_records_governance_dependency_warning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_cr(
                root,
                "CR-200",
                extra_frontmatter=(
                    'cr_type: "process"\n'
                    'conflict_keys: ["governance-authz"]\n'
                    'impact_process_refs: ["process/policies/AUTHZ.md"]'
                ),
            )
            target = write_cr(
                root,
                "CR-201",
                extra_frontmatter='impact_process_refs: ["process/policies/AUTHZ.md"]',
            )

            summary = cr_lifecycle.summary_from_cr_file(root, target)

            self.assertEqual("NEEDS_REVIEW", summary["governance_dependency_review"]["decision"])
            self.assertEqual(
                "open_governance_dependency_needs_review",
                summary["governance_dependency_review"]["findings"][0]["code"],
            )
            self.assertEqual("CR-200", summary["governance_dependency_review"]["findings"][0]["governance_cr"])

    def test_cr_check_prints_governance_dependency_warning_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_cr(
                root,
                "CR-200",
                extra_frontmatter=(
                    'cr_type: "process"\n'
                    'conflict_keys: ["governance-authz"]\n'
                    'impact_process_refs: ["process/policies/AUTHZ.md"]'
                ),
            )
            write_cr(
                root,
                "CR-201",
                extra_frontmatter='impact_process_refs: ["process/policies/AUTHZ.md"]',
            )
            cr_lifecycle.write_index(root)

            output = StringIO()
            with redirect_stdout(output):
                exit_code = cr_lifecycle.main(["check", "--project-root", str(root)])

            self.assertEqual(0, exit_code)
            self.assertIn("CR Lifecycle Check: OK", output.getvalue())
            self.assertIn("- WARN: CR-201 governance dependency open_governance_dependency_needs_review", output.getvalue())
            self.assertIn("governance_cr=CR-200", output.getvalue())

    def test_closed_governance_cr_does_not_warn(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_cr(
                root,
                "CR-200",
                status="closed",
                extra_frontmatter=(
                    'cr_type: "process"\n'
                    'conflict_keys: ["governance-authz"]\n'
                    'impact_process_refs: ["process/policies/AUTHZ.md"]'
                ),
            )
            target = write_cr(
                root,
                "CR-201",
                extra_frontmatter='impact_process_refs: ["process/policies/AUTHZ.md"]',
            )

            summary = cr_lifecycle.summary_from_cr_file(root, target)

            self.assertEqual("PASS", summary["governance_dependency_review"]["decision"])
            self.assertEqual([], summary["governance_dependency_review"]["findings"])

    def test_cp1_profile_is_lightweight_for_existing_use_case_extension(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = write_cr(
                root,
                "CR-210",
                extra_frontmatter=(
                    'product_baseline_refresh_required: false\n'
                    'affected_use_cases: ["UC-58"]\n'
                    'impact_module_paths: ["meta_flow/workflow/cr_lifecycle.py"]'
                ),
            )

            summary = cr_lifecycle.summary_from_cr_file(root, path)

            self.assertEqual("LIGHTWEIGHT_CP1", summary["cp1_review_profile"]["decision"])
            self.assertEqual(
                ["cr_tracking", "impact_surface", "affected_use_case_refs"],
                summary["cp1_review_profile"]["required_checks"],
            )
            self.assertEqual(["UC-58"], summary["cp1_review_profile"]["affected_use_cases"])

    def test_cp1_profile_is_full_when_product_baseline_refresh_required(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = write_cr(
                root,
                "CR-211",
                extra_frontmatter=(
                    'product_baseline_refresh_required: true\n'
                    'affected_use_cases: ["UC-58"]\n'
                    'affected_product_docs: ["docs/product/USE-CASES.md"]'
                ),
            )

            summary = cr_lifecycle.summary_from_cr_file(root, path)

            self.assertEqual("FULL_CP1_REQUIRED", summary["cp1_review_profile"]["decision"])
            self.assertIn("use_case_completeness", summary["cp1_review_profile"]["required_checks"])
            self.assertIn("scenario_coverage", summary["cp1_review_profile"]["required_checks"])

    def test_archive_isolation_warns_for_business_cr_archive_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = write_cr(
                root,
                "CR-212",
                extra_frontmatter=(
                    'cr_type: "feature"\n'
                    'impact_process_refs: ["process/archive/legacy-migration/old.md"]'
                ),
            )

            summary = cr_lifecycle.summary_from_cr_file(root, path)

            self.assertEqual("NEEDS_REVIEW", summary["archive_isolation_review"]["decision"])
            self.assertEqual(
                "archive_backup_scope_needs_isolation",
                summary["archive_isolation_review"]["findings"][0]["code"],
            )
            self.assertEqual(
                ["process/archive/legacy-migration/old.md"],
                summary["archive_isolation_review"]["findings"][0]["archive_refs"],
            )

    def test_archive_isolation_allows_housekeeping_process_cr(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = write_cr(
                root,
                "CR-213",
                extra_frontmatter=(
                    'cr_type: "process"\n'
                    'title: "archive housekeeping cleanup"\n'
                    'conflict_keys: ["housekeeping"]\n'
                    'impact_process_refs: ["process/archive/legacy-migration/old.md"]'
                ),
            )

            summary = cr_lifecycle.summary_from_cr_file(root, path)

            self.assertEqual("PASS", summary["archive_isolation_review"]["decision"])
            self.assertEqual([], summary["archive_isolation_review"]["findings"])

    def test_cr_check_prints_archive_isolation_warning_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_cr(
                root,
                "CR-212",
                extra_frontmatter=(
                    'cr_type: "feature"\n'
                    'impact_process_refs: ["process/backups/stale-state.json"]'
                ),
            )
            cr_lifecycle.write_index(root)

            output = StringIO()
            with redirect_stdout(output):
                exit_code = cr_lifecycle.main(["check", "--project-root", str(root)])

            self.assertEqual(0, exit_code)
            self.assertIn("CR Lifecycle Check: OK", output.getvalue())
            self.assertIn("- WARN: CR-212 archive isolation archive_backup_scope_needs_isolation", output.getvalue())
            self.assertIn("process/backups/stale-state.json", output.getvalue())

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

            self.assertEqual(0, cr_lifecycle.main(["index", "--project-root", str(root), "--apply"]))
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
            self.assertEqual("cp8_closed", summary["gate_status"])
            formal_text = (root / "process/changes/CR-101.md").read_text(encoding="utf-8")
            self.assertIn('lifecycle_status: "closed"', formal_text)
            self.assertIn('gate_status: "cp8_closed"', formal_text)
            index = json.loads((root / "process/changes/CR-INDEX.json").read_text(encoding="utf-8"))
            self.assertEqual("cp8_closed", index["items"][0]["gate_status"])
            self.assertTrue((root / "process" / "archive" / "CR-101" / "evidence-index.json").is_file())
            events = [
                json.loads(line)
                for line in (root / "process" / "state" / "CR-LEDGER.ndjson").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual("closed", events[0]["event"])
            self.assertEqual("process/changes/summaries/CR-101.summary.json", events[0]["summary_ref"])

    def test_status_sync_updates_frontmatter_summary_index_ledger_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current.write_current_state(root, current.default_current_state(root))
            current.update_current_state(
                root,
                {
                    "active_change": "CR-101",
                    "current_phase": "documentation",
                    "next_action": {"type": "await_user", "text": "review CP8"},
                },
            )
            write_cr(root, "CR-101", status="active")

            paths = cr_lifecycle.sync_cr_status(
                root,
                "CR-101",
                status="closed",
                readiness="READY_WITH_RISK",
                gate_status="cp8_closed",
            )

            self.assertTrue(paths["summary"].is_file())
            text = (root / "process" / "changes" / "CR-101.md").read_text(encoding="utf-8")
            self.assertIn('lifecycle_status: "closed"', text)
            self.assertIn('readiness_status: "READY_WITH_RISK"', text)
            self.assertIn('gate_status: "cp8_closed"', text)
            summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
            self.assertEqual("closed", summary["status"])
            self.assertEqual("READY_WITH_RISK", summary["readiness"])
            self.assertEqual("cp8_closed", summary["gate_status"])
            index = json.loads(paths["index"].read_text(encoding="utf-8"))
            self.assertEqual("closed", index["items"][0]["status"])
            state = current.load_current_state(root)
            self.assertIsNone(state["active_change"])
            self.assertEqual("delivered", state["current_phase"])
            self.assertEqual("delivered", state["next_action"]["stop_reason"])
            events = cr_lifecycle.load_ledger_events(root)
            self.assertEqual("status_sync", events[-1]["event"])

    def test_status_sync_projects_body_status_and_checkpoint_in_same_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cr_path = write_cr(root, "CR-101", status="active")
            cr_path.write_text(
                cr_path.read_text(encoding="utf-8")
                + """
## CR 类型与门禁策略

| 字段 | 内容 |
|---|---|
| 生命周期状态 | active |
| 就绪状态 | NOT_READY |
| 门禁状态 | cp3_pending |
| 门禁模板 | architecture-major |

## Checkpoint Index

| CP | 状态 | 机器结果 ref |
|---|---|---|
| CP3 | approved | process/checks/CP3.result.json |
| CP8 | pending | process/checks/CP8.result.json |
""",
                encoding="utf-8",
            )

            plan = cr_lifecycle.plan_status_sync(
                root,
                "CR-101",
                status="closed",
                readiness="READY_WITH_RISK",
                gate_status="cp8_closed",
            )

            self.assertEqual("READY", plan.decision)
            formal_target = next(
                target for target in plan.targets if target.ref == "process/changes/CR-101.md"
            )
            self.assertIn("| 生命周期状态 | closed |", formal_target.after)
            self.assertIn("| 就绪状态 | READY_WITH_RISK |", formal_target.after)
            self.assertIn("| 门禁状态 | cp8_closed |", formal_target.after)
            self.assertIn(
                "| CP8 | approved | process/checks/CP8.result.json |",
                formal_target.after,
            )
            self.assertEqual(
                1,
                sum(
                    target.ref == "process/changes/CR-101.md"
                    for target in plan.targets
                ),
            )

    def test_status_sync_closed_defaults_gate_status_to_cp8_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_cr(root, "CR-101", status="active")

            paths = cr_lifecycle.sync_cr_status(
                root,
                "CR-101",
                status="closed",
                readiness="READY",
            )

            text = (root / "process/changes/CR-101.md").read_text(encoding="utf-8")
            self.assertIn('gate_status: "cp8_closed"', text)
            summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
            self.assertEqual("cp8_closed", summary["gate_status"])
            self.assertIn(summary["gate_status"], cr_tracking.ALLOWED_GATE_STATUSES)

    def test_status_sync_closed_rejects_noncanonical_gate_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_cr(root, "CR-101", status="active")

            with self.assertRaisesRegex(ValueError, "status=closed requires gate_status=cp8_closed"):
                cr_lifecycle.sync_cr_status(root, "CR-101", status="closed", gate_status="cp8_approved")

    def test_status_sync_cli_defaults_to_zero_mutation_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cr_path = write_cr(root, "CR-101", status="active")
            before = cr_path.read_text(encoding="utf-8")

            output = StringIO()
            with redirect_stdout(output):
                exit_code = cr_lifecycle.main(
                    [
                        "status-sync",
                        "--id",
                        "CR-101",
                        "--status",
                        "closed",
                        "--readiness",
                        "READY",
                        "--project-root",
                        str(root),
                    ]
                )

            self.assertEqual(0, exit_code)
            self.assertEqual(before, cr_path.read_text(encoding="utf-8"))
            self.assertFalse((root / "process/changes/CR-INDEX.json").exists())
            self.assertEqual("READY", json.loads(output.getvalue())["decision"])

    def test_status_sync_fault_points_recover_before_index_is_written(self) -> None:
        fault_expectations = {
            "before-first-replace": "BLOCKED",
            "after-replace-before-receipt": "RECOVERED",
            "after-receipt-before-next": "RECOVERED",
            "after-truth-before-derived": "RECOVERED",
            "before-index-last": "RECOVERED",
            "during-read-back": "RECOVERED",
        }
        for fault, expected in fault_expectations.items():
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                cr_path = write_cr(root, "CR-101", status="active")
                before = cr_path.read_text(encoding="utf-8")
                plan = cr_lifecycle.plan_status_sync(
                    root,
                    "CR-101",
                    status="closed",
                    readiness="READY_WITH_RISK",
                )

                result = cr_lifecycle.apply_status_sync(root, plan, _fault=fault)

                self.assertEqual(expected, result["status"])
                self.assertEqual(before, cr_path.read_text(encoding="utf-8"))
                self.assertFalse((root / "process/changes/CR-INDEX.json").exists())

    def test_status_sync_partial_is_queryable_and_explicit_rollback_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cr_path = write_cr(root, "CR-101", status="active")
            before = cr_path.read_text(encoding="utf-8")
            plan = cr_lifecycle.plan_status_sync(
                root,
                "CR-101",
                status="closed",
                readiness="READY_WITH_RISK",
            )

            partial = cr_lifecycle.apply_status_sync(
                root,
                plan,
                _fault="after-receipt-before-next",
                _fail_recovery=True,
            )
            inspected = cr_lifecycle.inspect_status_sync_transactions(root)
            recovered = cr_lifecycle.recover_status_sync_transaction(
                root,
                partial["transaction_id"],
                action="rollback",
            )

            self.assertEqual("PARTIAL", partial["status"])
            self.assertEqual(1, inspected["transaction_count"])
            self.assertEqual("RECOVERED", recovered["status"])
            self.assertEqual(before, cr_path.read_text(encoding="utf-8"))
            self.assertEqual(0, cr_lifecycle.inspect_status_sync_transactions(root)["transaction_count"])

    def test_status_sync_recovery_blocks_competing_writer_and_releases_only_its_owner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_cr(root, "CR-101", status="active")
            plan = cr_lifecycle.plan_status_sync(
                root,
                "CR-101",
                status="closed",
                readiness="READY_WITH_RISK",
            )
            partial = cr_lifecycle.apply_status_sync(
                root,
                plan,
                _fault="after-receipt-before-next",
                _fail_recovery=True,
            )
            owner = cr_lifecycle._acquire_status_sync_writer_lock(
                root,
                transaction_id=partial["transaction_id"],
                purpose="recovery:test-contender",
            )
            self.assertIsNotNone(owner)
            assert owner is not None
            lock_path = cr_lifecycle._status_sync_writer_lock_path(root)
            persisted = json.loads(lock_path.read_text(encoding="utf-8"))

            blocked = cr_lifecycle.recover_status_sync_transaction(
                root,
                partial["transaction_id"],
                action="rollback",
            )
            wrong_owner = dict(owner)
            wrong_owner["owner_token"] = "0" * 32

            self.assertEqual("BLOCKED", blocked["status"])
            self.assertIn("writer lock", blocked["reason"])
            self.assertFalse(cr_lifecycle._release_status_sync_writer_lock(root, wrong_owner))
            self.assertTrue(lock_path.is_file())
            self.assertEqual(
                persisted["owner_token"],
                json.loads(lock_path.read_text(encoding="utf-8"))["owner_token"],
            )
            self.assertTrue(cr_lifecycle._release_status_sync_writer_lock(root, owner))

            recovered = cr_lifecycle.recover_status_sync_transaction(
                root,
                partial["transaction_id"],
                action="rollback",
            )
            self.assertEqual("RECOVERED", recovered["status"])
            self.assertFalse(lock_path.exists())

    def test_status_sync_recovery_does_not_auto_remove_stale_owner_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_cr(root, "CR-101", status="active")
            plan = cr_lifecycle.plan_status_sync(
                root,
                "CR-101",
                status="closed",
                readiness="READY_WITH_RISK",
            )
            partial = cr_lifecycle.apply_status_sync(
                root,
                plan,
                _fault="after-receipt-before-next",
                _fail_recovery=True,
            )
            owner = cr_lifecycle._acquire_status_sync_writer_lock(
                root,
                transaction_id=partial["transaction_id"],
                purpose="recovery:stale-fixture",
            )
            assert owner is not None
            lock_path = cr_lifecycle._status_sync_writer_lock_path(root)
            stale = json.loads(lock_path.read_text(encoding="utf-8"))
            stale["acquired_at"] = "1970-01-01T00:00:00+00:00"
            lock_path.write_text(json.dumps(stale) + "\n", encoding="utf-8")

            blocked = cr_lifecycle.recover_status_sync_transaction(
                root,
                partial["transaction_id"],
                action="resume",
            )

            self.assertEqual("BLOCKED", blocked["status"])
            self.assertTrue(lock_path.is_file())
            self.assertTrue(cr_lifecycle._release_status_sync_writer_lock(root, owner))

    def test_index_default_is_dry_run_and_semantic_digest_excludes_generated_at(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_cr(root, "CR-101")
            first = cr_lifecycle.build_index(root)
            second = cr_lifecycle.build_index(root)

            output = StringIO()
            with redirect_stdout(output):
                exit_code = cr_lifecycle.main(["index", "--project-root", str(root)])

            self.assertEqual(0, exit_code)
            self.assertEqual(first["semantic_digest"], second["semantic_digest"])
            self.assertFalse((root / "process/changes/CR-INDEX.json").exists())
            self.assertEqual(1, json.loads(output.getvalue())["mutation_count"])

    def test_corrupt_index_requires_explicit_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_cr(root, "CR-101")
            index_path = root / "process/changes/CR-INDEX.json"
            index_path.write_text("{not-json\n", encoding="utf-8")

            blocked = cr_lifecycle.plan_index(root)
            rebuilt = cr_lifecycle.write_index(root, rebuild_corrupt=True)

            self.assertEqual("BLOCKED", blocked["decision"])
            self.assertEqual([], cr_lifecycle.validate_index_payload(json.loads(rebuilt.read_text(encoding="utf-8"))))

    def test_index_builder_rejects_non_native_and_legacy_boundary_contamination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy_source = root / "process/legacy/LEGACY-SOURCE.yaml"
            legacy_source.parent.mkdir(parents=True, exist_ok=True)
            legacy_source.write_text(
                "schema_version: 1\nnative_cr_minimum: CR-053\n",
                encoding="utf-8",
            )
            write_cr(root, "CR-052")

            blocked = cr_lifecycle.plan_index(root)

            self.assertEqual("BLOCKED", blocked["decision"])
            self.assertEqual(0, blocked["mutation_count"])
            self.assertIn("native_cr_minimum=CR-053", blocked["reason"])
            self.assertFalse((root / "process/changes/CR-INDEX.json").exists())

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_cr(root, "CR-053")
            contaminated = root / "process/changes/CR-054.md"
            contaminated.write_text(
                "---\ncr_id: CR-054\ntitle: non-native\n---\n",
                encoding="utf-8",
            )

            blocked = cr_lifecycle.plan_index(root)

            self.assertEqual("BLOCKED", blocked["decision"])
            self.assertIn("schema_version=1", blocked["reason"])
            self.assertIn("kind=cr", blocked["reason"])
            with self.assertRaisesRegex(ValueError, "non-native formal CR contamination"):
                cr_lifecycle.build_index(root)

    def test_cr_help_uses_canonical_closed_gate_status(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            cr_lifecycle.main(["--help"])

        self.assertIn("--gate-status cp8_closed", output.getvalue())
        self.assertNotIn("cp8_approved", output.getvalue())

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
