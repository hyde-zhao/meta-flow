from __future__ import annotations

import json
import subprocess
import sys
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
from meta_flow.project.scale import dump_yaml, load_yaml_object
from meta_flow.state import current
from meta_flow.work.scope import WorkScope
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


def write_termination_fixture(
    root: Path,
    *,
    cr_id: str = "CR-101",
    work_id: str = "WORK-101",
) -> tuple[Path, Path, Path, WorkScope]:
    release, process = init_binding_project(root)
    subprocess.run(
        ["git", "add", "--all"],
        cwd=process,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Meta Flow Test",
            "-c",
            "user.email=meta-flow@example.invalid",
            "commit",
            "-m",
            "initial process truth",
        ],
        cwd=process,
        check=True,
        capture_output=True,
    )
    cr_path = write_cr(release, cr_id)
    phase_ref = "phases/P1-termination/PHASE.yaml"
    work_ref = f"works/{work_id}/WORK.yaml"
    scope = WorkScope(
        version=1,
        allowed_reads=(
            "PROJECT.yaml",
            phase_ref,
            work_ref,
            "archive/**",
            "changes/**",
            "state/**",
        ),
        allowed_writes=(
            "PROJECT.yaml",
            phase_ref,
            work_ref,
            "archive/**",
            "changes/**",
            "state/**",
        ),
        required_checks=("cr-termination",),
    )
    release_oid = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=release,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    process_oid = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=process,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    project = load_yaml_object(process / "PROJECT.yaml")
    project["active_phase_ref"] = phase_ref
    project["active_work_refs"] = [work_ref]
    (process / "PROJECT.yaml").write_text(
        dump_yaml(project) + "\n",
        encoding="utf-8",
    )
    phase_path = process / phase_ref
    phase_path.parent.mkdir(parents=True, exist_ok=True)
    phase_path.write_text(
        dump_yaml(
            {
                "schema_version": 1,
                "project_id": "fixture",
                "phase_id": "P1-termination",
                "objective": "验证原生 CR 终止事务",
                "status": "active",
                "work_refs": [work_ref],
                "result_refs": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    work_path = process / work_ref
    work_path.parent.mkdir(parents=True, exist_ok=True)
    work_path.write_text(
        dump_yaml(
            {
                "schema_version": 1,
                "work_id": work_id,
                "project_id": "fixture",
                "kind": "cr",
                "objective": "验证原生 CR 终止事务",
                "status": "active",
                "request_ref": f"works/{work_id}/REQUEST.md",
                "request_confirmed": True,
                "phase_ref": phase_ref,
                "risk_profile": "G2",
                "risk_reason_codes": ["PUBLIC_CONTRACT"],
                "required_gates": ["GATE-DESIGN"],
                "scope": scope.as_dict(),
                "scope_digest": scope.digest,
                "budget": {
                    "reads": 20,
                    "writes": 20,
                    "check_groups": 4,
                    "tokens": 100000,
                },
                "usage_ref": f"works/{work_id}/USAGE.json",
                "base_oids": {
                    "release": release_oid,
                    "process": process_oid,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    request_path = process / "works" / work_id / "REQUEST.md"
    request_path.write_text("# fixture\n", encoding="utf-8")
    return release, process, cr_path, scope


def termination_authorization(
    plan: cr_lifecycle.TerminationPlan,
    *,
    authorization_id: str = "AUTH-TERMINATE-001",
) -> cr_lifecycle.TerminationAuthorization:
    return cr_lifecycle.TerminationAuthorization(
        schema_version=1,
        authorization_id=authorization_id,
        authorization_source=cr_lifecycle.TERMINATION_AUTHORIZATION_SOURCE,
        authorization_kind=cr_lifecycle.TERMINATION_AUTHORIZATION_KIND,
        operation=cr_lifecycle.TERMINATION_OPERATION,
        cr_id=plan.cr_id,
        work_id=plan.work_id,
        termination_reason=plan.termination_reason,
        terminal_tuple=plan.terminal_tuple,
        expected_release_oid=plan.expected_facts["target_release_oid"],
        expected_process_oid=plan.expected_facts["process_head_oid"],
        scope_digest=plan.scope_digest,
        plan_digest=plan.plan_digest,
        expires_at="2099-01-01T00:00:00+00:00",
        single_use=True,
    )


def status_sync_authorization(
    plan: cr_lifecycle.StatusSyncPlan,
    *,
    authorization_id: str = "AUTH-STATUS-SYNC-001",
) -> cr_lifecycle.StatusSyncAuthorization:
    return cr_lifecycle.StatusSyncAuthorization(
        schema_version=1,
        authorization_id=authorization_id,
        authorization_source=cr_lifecycle.STATUS_SYNC_AUTHORIZATION_SOURCE,
        authorization_kind=cr_lifecycle.STATUS_SYNC_AUTHORIZATION_KIND,
        operation=cr_lifecycle.STATUS_SYNC_OPERATION,
        cr_id=plan.cr_id,
        work_id=plan.work_id,
        desired_transition=plan.desired_transition,
        effective_at=plan.effective_at,
        expected_release_oid=plan.expected_facts["release_head_oid"],
        expected_process_oid=plan.expected_facts["process_head_oid"],
        scope_digest=plan.scope_digest,
        targets=[target.as_dict() for target in plan.targets],
        plan_digest=plan.plan_digest,
        expires_at="2099-01-01T00:00:00+00:00",
        single_use=True,
    )


def apply_ready_status_sync(
    root: Path,
    plan: cr_lifecycle.StatusSyncPlan,
    *,
    authorization_id: str = "AUTH-STATUS-SYNC-001",
    **kwargs: object,
) -> dict[str, object]:
    return cr_lifecycle.apply_status_sync(
        root,
        plan,
        authorization=status_sync_authorization(
            plan,
            authorization_id=authorization_id,
        ),
        expected_plan_digest=plan.plan_digest,
        **kwargs,
    )


def write_feature_registry(root: Path) -> Path:
    path = _resolve_runtime_ref(
        root,
        "process/docs/design/FEATURE-REGISTRY.yaml",
    )
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
    path = _resolve_runtime_ref(
        root,
        "process/docs/design/CAPABILITY-REGISTRY.yaml",
    )
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
            release, process, cr_path, _scope = write_termination_fixture(
                Path(directory),
                cr_id="CR-055",
                work_id="WORK-055",
            )
            cr_path.chmod(0o644)
            plan = cr_lifecycle.plan_status_sync(
                release,
                "CR-055",
                status="closed",
                readiness="READY_WITH_RISK",
                gate_status="cp8_closed",
                work_id="WORK-055",
                effective_at="2026-07-27T00:00:00+00:00",
            )

            result = apply_ready_status_sync(release, plan)

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
            release, process, cr_path, _scope = write_termination_fixture(
                Path(directory)
            )
            process_oid = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=process,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            effective_at = "2026-07-27T01:02:03+00:00"
            before_text = cr_path.read_text(encoding="utf-8")
            output = StringIO()
            with redirect_stdout(output):
                dry_run_exit = cr_lifecycle.main(
                    [
                        "close",
                        "--id",
                        "CR-101",
                        "--readiness",
                        "READY_WITH_RISK",
                        "--work-id",
                        "WORK-101",
                        "--effective-at",
                        effective_at,
                        "--expected-process-oid",
                        process_oid,
                        "--project-root",
                        str(release),
                    ]
                )
            payload = json.loads(output.getvalue())
            self.assertEqual(before_text, cr_path.read_text(encoding="utf-8"))
            plan = cr_lifecycle.plan_status_sync(
                release,
                "CR-101",
                status="closed",
                readiness="READY_WITH_RISK",
                gate_status="cp8_closed",
                work_id="WORK-101",
                effective_at=effective_at,
                expected_process_oid=process_oid,
            )
            authorization = status_sync_authorization(plan)
            authorization_path = Path(directory) / "authorization.json"
            authorization_path.write_text(
                json.dumps(authorization.__dict__, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            apply_output = StringIO()
            with redirect_stdout(apply_output):
                apply_exit = cr_lifecycle.main(
                    [
                        "close",
                        "--id",
                        "CR-101",
                        "--readiness",
                        "READY_WITH_RISK",
                        "--work-id",
                        "WORK-101",
                        "--effective-at",
                        effective_at,
                        "--expected-process-oid",
                        process_oid,
                        "--expected-plan-digest",
                        plan.plan_digest,
                        "--authorization-file",
                        str(authorization_path),
                        "--apply",
                        "--project-root",
                        str(release),
                    ]
                )

            self.assertEqual(0, dry_run_exit)
            self.assertEqual(0, payload["mutation_count"])
            self.assertEqual(5, payload["planned_mutation_count"])
            self.assertEqual(0, apply_exit, apply_output.getvalue())
            summary = json.loads(
                (
                    process
                    / "changes"
                    / "summaries"
                    / "CR-101.summary.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual("closed", summary["status"])
            self.assertEqual("READY_WITH_RISK", summary["readiness"])
            self.assertEqual("cp8_closed", summary["gate_status"])
            formal_text = cr_path.read_text(encoding="utf-8")
            self.assertIn('lifecycle_status: "closed"', formal_text)
            self.assertIn('gate_status: "cp8_closed"', formal_text)
            index = json.loads(
                (process / "changes" / "CR-INDEX.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual("cp8_closed", index["items"][0]["gate_status"])
            self.assertTrue(
                (process / "archive" / "CR-101" / "evidence-index.json").is_file()
            )
            events = [
                json.loads(line)
                for line in (
                    process / "state" / "CR-LEDGER.ndjson"
                ).read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual("status_sync", events[0]["event"])
            self.assertEqual("process/changes/summaries/CR-101.summary.json", events[0]["summary_ref"])

    def test_status_sync_updates_frontmatter_summary_index_ledger_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process, _cr_path, _scope = write_termination_fixture(
                Path(directory)
            )
            current.write_current_state(
                release,
                current.default_current_state(release),
            )
            current.update_current_state(
                release,
                {
                    "active_change": "CR-101",
                    "current_phase": "documentation",
                    "next_action": {"type": "await_user", "text": "review CP8"},
                },
            )
            effective_at = "2026-07-27T02:00:00+00:00"
            plan = cr_lifecycle.plan_status_sync(
                release,
                "CR-101",
                status="closed",
                readiness="READY_WITH_RISK",
                gate_status="cp8_closed",
                work_id="WORK-101",
                effective_at=effective_at,
            )
            paths = cr_lifecycle.sync_cr_status(
                release,
                "CR-101",
                status="closed",
                readiness="READY_WITH_RISK",
                gate_status="cp8_closed",
                work_id="WORK-101",
                effective_at=effective_at,
                expected_plan_digest=plan.plan_digest,
                authorization=status_sync_authorization(plan),
            )

            self.assertTrue(paths["summary"].is_file())
            text = (process / "changes" / "CR-101.md").read_text(
                encoding="utf-8"
            )
            self.assertIn('lifecycle_status: "closed"', text)
            self.assertIn('readiness_status: "READY_WITH_RISK"', text)
            self.assertIn('gate_status: "cp8_closed"', text)
            summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
            self.assertEqual("closed", summary["status"])
            self.assertEqual("READY_WITH_RISK", summary["readiness"])
            self.assertEqual("cp8_closed", summary["gate_status"])
            index = json.loads(paths["index"].read_text(encoding="utf-8"))
            self.assertEqual("closed", index["items"][0]["status"])
            state = current.load_current_state(release)
            self.assertIsNone(state["active_change"])
            self.assertEqual("delivered", state["current_phase"])
            self.assertEqual("delivered", state["next_action"]["stop_reason"])
            events = cr_lifecycle.load_ledger_events(release)
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

## 8. Checkpoint Index

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

    def test_status_sync_projects_canonical_checkpoint_result_without_regressing_pending_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cr_path = write_cr(root, "CR-101", status="active")
            cr_path.write_text(
                cr_path.read_text(encoding="utf-8")
                + """
## Checkpoint Index

| CP | 状态 | 机器结果 ref |
|---|---|---|
| CP7 | pending | process/checks/CP7-CR-101-AGGREGATE.result.json |
| CP8 | pending | process/checks/CP8-CR-101-DELIVERY.result.json |
""",
                encoding="utf-8",
            )
            result_path = root / "process/checks/CP7-CR-101-AGGREGATE.result.json"
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(
                json.dumps(
                    {
                        "checkpoint": "CP7",
                        "decision": "PASS",
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            plan = cr_lifecycle.plan_status_sync(
                root,
                "CR-101",
                status="active",
                readiness="NOT_READY",
                gate_status="cp8_pending",
            )

            self.assertEqual("READY", plan.decision)
            formal_target = next(
                target for target in plan.targets if target.ref == "process/changes/CR-101.md"
            )
            self.assertIn(
                "| CP7 | PASS | process/checks/CP7-CR-101-AGGREGATE.result.json |",
                formal_target.after,
            )
            self.assertIn(
                "| CP8 | pending | process/checks/CP8-CR-101-DELIVERY.result.json |",
                formal_target.after,
            )

    def test_status_sync_same_tuple_and_projection_is_no_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, _process, _cr_path, _scope = write_termination_fixture(
                Path(directory)
            )
            effective_at = "2026-07-27T03:00:00+00:00"
            initial = cr_lifecycle.plan_status_sync(
                release,
                "CR-101",
                status="active",
                readiness="NOT_READY",
                gate_status="cp8_pending",
                work_id="WORK-101",
                effective_at=effective_at,
            )
            paths = cr_lifecycle.sync_cr_status(
                release,
                "CR-101",
                status="active",
                readiness="NOT_READY",
                gate_status="cp8_pending",
                work_id="WORK-101",
                effective_at=effective_at,
                expected_plan_digest=initial.plan_digest,
                authorization=status_sync_authorization(initial),
            )
            ledger_before = paths["ledger"].read_bytes()

            plan = cr_lifecycle.plan_status_sync(
                release,
                "CR-101",
                status="active",
                readiness="NOT_READY",
                gate_status="cp8_pending",
                work_id="WORK-101",
                effective_at=effective_at,
            )
            result = cr_lifecycle.apply_status_sync(release, plan)

            self.assertEqual("NO_CHANGE", plan.decision)
            self.assertEqual("NO_CHANGE", result["status"])
            self.assertEqual(0, result["mutation_count"])
            self.assertEqual(ledger_before, paths["ledger"].read_bytes())

    def test_status_sync_no_change_ignores_unrelated_paired_dirty_path_growth(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process, _cr_path, _scope = write_termination_fixture(
                Path(directory)
            )
            effective_at = "2026-07-27T04:00:00+00:00"
            initial = cr_lifecycle.plan_status_sync(
                release,
                "CR-101",
                status="active",
                readiness="NOT_READY",
                gate_status="cp8_pending",
                work_id="WORK-101",
                effective_at=effective_at,
            )
            paths = cr_lifecycle.sync_cr_status(
                release,
                "CR-101",
                status="active",
                readiness="NOT_READY",
                gate_status="cp8_pending",
                work_id="WORK-101",
                effective_at=effective_at,
                expected_plan_digest=initial.plan_digest,
                authorization=status_sync_authorization(initial),
            )
            ledger_before = paths["ledger"].read_bytes()
            unrelated = process / "checks/UNRELATED.result.json"
            unrelated.parent.mkdir(parents=True, exist_ok=True)
            unrelated.write_text('{"decision":"PASS"}\n', encoding="utf-8")

            plan = cr_lifecycle.plan_status_sync(
                release,
                "CR-101",
                status="active",
                readiness="NOT_READY",
                gate_status="cp8_pending",
                work_id="WORK-101",
                effective_at=effective_at,
            )
            result = cr_lifecycle.apply_status_sync(release, plan)

            self.assertEqual("NO_CHANGE", plan.decision)
            self.assertEqual("NO_CHANGE", result["status"])
            self.assertEqual(0, result["mutation_count"])
            self.assertEqual(ledger_before, paths["ledger"].read_bytes())

    def test_status_sync_closed_defaults_gate_status_to_cp8_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process, _cr_path, _scope = write_termination_fixture(
                Path(directory)
            )
            effective_at = "2026-07-27T05:00:00+00:00"
            plan = cr_lifecycle.plan_status_sync(
                release,
                "CR-101",
                status="closed",
                readiness="READY",
                work_id="WORK-101",
                effective_at=effective_at,
            )
            paths = cr_lifecycle.sync_cr_status(
                release,
                "CR-101",
                status="closed",
                readiness="READY",
                work_id="WORK-101",
                effective_at=effective_at,
                expected_plan_digest=plan.plan_digest,
                authorization=status_sync_authorization(plan),
            )

            text = (process / "changes" / "CR-101.md").read_text(
                encoding="utf-8"
            )
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

    def test_status_sync_frozen_effective_at_produces_byte_identical_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, _process, _cr_path, _scope = write_termination_fixture(
                Path(directory)
            )
            inputs = {
                "status": "closed",
                "readiness": "READY_WITH_RISK",
                "gate_status": "cp8_closed",
                "work_id": "WORK-101",
                "effective_at": "2026-07-27T11:00:00+00:00",
            }

            first = cr_lifecycle.plan_status_sync(
                release,
                "CR-101",
                **inputs,
            )
            second = cr_lifecycle.plan_status_sync(
                release,
                "CR-101",
                **inputs,
            )
            changed_time = cr_lifecycle.plan_status_sync(
                release,
                "CR-101",
                **{
                    **inputs,
                    "effective_at": "2026-07-27T11:00:01+00:00",
                },
            )

            first_bytes = json.dumps(
                first.as_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            second_bytes = json.dumps(
                second.as_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            self.assertEqual(first_bytes, second_bytes)
            self.assertEqual(first.plan_digest, second.plan_digest)
            self.assertNotEqual(first.plan_digest, changed_time.plan_digest)
            self.assertEqual(0, first.as_dict()["mutation_count"])
            self.assertEqual(5, first.as_dict()["planned_mutation_count"])

    def test_status_sync_typed_authorization_fail_closed_and_single_use(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, _process, cr_path, _scope = write_termination_fixture(
                Path(directory)
            )
            before = cr_path.read_bytes()
            plan = cr_lifecycle.plan_status_sync(
                release,
                "CR-101",
                status="closed",
                readiness="READY_WITH_RISK",
                gate_status="cp8_closed",
                work_id="WORK-101",
                effective_at="2026-07-27T12:00:00+00:00",
            )
            authorization = status_sync_authorization(plan)
            wrong_payload = dict(authorization.__dict__)
            wrong_payload["expected_release_oid"] = "0" * 40
            wrong = cr_lifecycle.StatusSyncAuthorization.from_dict(
                wrong_payload
            )

            missing = cr_lifecycle.apply_status_sync(
                release,
                plan,
                expected_plan_digest=plan.plan_digest,
            )
            wrong_digest = cr_lifecycle.apply_status_sync(
                release,
                plan,
                authorization=authorization,
                expected_plan_digest="0" * 64,
            )
            wrong_authorization = cr_lifecycle.apply_status_sync(
                release,
                plan,
                authorization=wrong,
                expected_plan_digest=plan.plan_digest,
            )
            first_attempt = cr_lifecycle.apply_status_sync(
                release,
                plan,
                authorization=authorization,
                expected_plan_digest=plan.plan_digest,
                _fault="before-first-replace",
            )
            replay = cr_lifecycle.apply_status_sync(
                release,
                plan,
                authorization=authorization,
                expected_plan_digest=plan.plan_digest,
            )

            self.assertEqual("BLOCKED", missing["status"])
            self.assertEqual("BLOCKED", wrong_digest["status"])
            self.assertEqual("BLOCKED", wrong_authorization["status"])
            self.assertEqual("BLOCKED", first_attempt["status"])
            self.assertEqual("BLOCKED", replay["status"])
            self.assertIn("already consumed", replay["reason"])
            self.assertEqual(before, cr_path.read_bytes())
            self.assertTrue(
                all(
                    result["mutation_count"] == 0
                    for result in (
                        missing,
                        wrong_digest,
                        wrong_authorization,
                        first_attempt,
                        replay,
                    )
                )
            )

    def test_status_sync_authorization_unknown_field_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, _process, _cr_path, _scope = write_termination_fixture(
                Path(directory)
            )
            plan = cr_lifecycle.plan_status_sync(
                release,
                "CR-101",
                status="closed",
                readiness="READY_WITH_RISK",
                gate_status="cp8_closed",
                work_id="WORK-101",
                effective_at="2026-07-27T13:00:00+00:00",
            )
            payload = dict(status_sync_authorization(plan).__dict__)
            payload["unknown"] = True
            authorization_path = Path(directory) / "authorization.json"
            authorization_path.write_text(
                json.dumps(payload, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ValueError,
                "fields mismatch",
            ):
                cr_lifecycle.load_status_sync_authorization(
                    authorization_path
                )

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
                root, _process, cr_path, _scope = write_termination_fixture(
                    Path(directory)
                )
                before = cr_path.read_text(encoding="utf-8")
                plan = cr_lifecycle.plan_status_sync(
                    root,
                    "CR-101",
                    status="closed",
                    readiness="READY_WITH_RISK",
                    work_id="WORK-101",
                    effective_at="2026-07-27T06:00:00+00:00",
                )

                result = apply_ready_status_sync(root, plan, _fault=fault)

                self.assertEqual(expected, result["status"])
                self.assertEqual(before, cr_path.read_text(encoding="utf-8"))
                self.assertFalse(
                    _resolve_runtime_ref(
                        root,
                        "process/changes/CR-INDEX.json",
                    ).exists()
                )

    def test_status_sync_partial_is_queryable_and_explicit_rollback_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, _process, cr_path, _scope = write_termination_fixture(
                Path(directory)
            )
            before = cr_path.read_text(encoding="utf-8")
            plan = cr_lifecycle.plan_status_sync(
                root,
                "CR-101",
                status="closed",
                readiness="READY_WITH_RISK",
                work_id="WORK-101",
                effective_at="2026-07-27T07:00:00+00:00",
            )

            partial = apply_ready_status_sync(
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
            root, _process, _cr_path, _scope = write_termination_fixture(
                Path(directory)
            )
            plan = cr_lifecycle.plan_status_sync(
                root,
                "CR-101",
                status="closed",
                readiness="READY_WITH_RISK",
                work_id="WORK-101",
                effective_at="2026-07-27T08:00:00+00:00",
            )
            partial = apply_ready_status_sync(
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
            root, _process, _cr_path, _scope = write_termination_fixture(
                Path(directory)
            )
            plan = cr_lifecycle.plan_status_sync(
                root,
                "CR-101",
                status="closed",
                readiness="READY_WITH_RISK",
                work_id="WORK-101",
                effective_at="2026-07-27T09:00:00+00:00",
            )
            partial = apply_ready_status_sync(
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

    def test_terminate_dry_run_supports_both_native_tuples_and_mutates_nothing(
        self,
    ) -> None:
        for termination_status in ("cancelled", "superseded"):
            with self.subTest(status=termination_status), tempfile.TemporaryDirectory() as directory:
                release, process, cr_path, scope = write_termination_fixture(
                    Path(directory)
                )
                before = cr_path.read_text(encoding="utf-8")
                process_oid = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=process,
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
                output = StringIO()

                with redirect_stdout(output):
                    exit_code = cr_lifecycle.main(
                        [
                            "terminate",
                            "--id",
                            "CR-101",
                            "--work-id",
                            "WORK-101",
                            "--status",
                            termination_status,
                            "--reason",
                            "由替代路线接管",
                            "--expected-process-oid",
                            process_oid,
                            "--project-root",
                            str(release),
                        ]
                    )

                payload = json.loads(output.getvalue())
                self.assertEqual(0, exit_code)
                self.assertEqual("READY", payload["decision"])
                self.assertEqual(
                    {
                        "lifecycle_status": termination_status,
                        "readiness_status": "n/a",
                        "gate_status": "closed",
                    },
                    payload["terminal_tuple"],
                )
                self.assertEqual(0, payload["mutation_count"])
                self.assertEqual(7, payload["planned_mutation_count"])
                self.assertEqual(scope.digest, payload["scope_digest"])
                self.assertNotIn(
                    "process/state/STATE.current.json",
                    payload["mutation_allowlist"],
                )
                self.assertEqual(before, cr_path.read_text(encoding="utf-8"))
                self.assertFalse((process / "changes" / "CR-INDEX.json").exists())
                self.assertNotIn(str(process), output.getvalue())

    def test_terminate_apply_projects_cr_work_project_phase_summary_ledger_and_index(
        self,
    ) -> None:
        for termination_status in ("cancelled", "superseded"):
            with self.subTest(status=termination_status), tempfile.TemporaryDirectory() as directory:
                release, process, _cr_path, _scope = write_termination_fixture(
                    Path(directory)
                )
                plan = cr_lifecycle.plan_cr_termination(
                    release,
                    "CR-101",
                    work_id="WORK-101",
                    termination_status=termination_status,
                    termination_reason="由替代路线接管",
                )
                authorization = termination_authorization(
                    plan,
                    authorization_id=f"AUTH-{termination_status.upper()}",
                )

                result = cr_lifecycle.apply_cr_termination(
                    release,
                    plan,
                    authorization=authorization,
                    expected_plan_digest=plan.plan_digest,
                )

                self.assertEqual("PASS", result["status"])
                self.assertEqual(7, result["mutation_count"])
                fields = cr_lifecycle.parse_frontmatter(
                    (
                        process / "changes" / "CR-101.md"
                    ).read_text(encoding="utf-8")
                )
                self.assertEqual(
                    (
                        termination_status,
                        "n/a",
                        "closed",
                    ),
                    (
                        fields["lifecycle_status"],
                        fields["readiness_status"],
                        fields["gate_status"],
                    ),
                )
                work = load_yaml_object(
                    process / "works" / "WORK-101" / "WORK.yaml"
                )
                project = load_yaml_object(process / "PROJECT.yaml")
                phase = load_yaml_object(
                    process
                    / "phases"
                    / "P1-termination"
                    / "PHASE.yaml"
                )
                summary = json.loads(
                    (
                        process
                        / "changes"
                        / "summaries"
                        / "CR-101.summary.json"
                    ).read_text(encoding="utf-8")
                )
                index = json.loads(
                    (
                        process / "changes" / "CR-INDEX.json"
                    ).read_text(encoding="utf-8")
                )
                ledger = [
                    json.loads(line)
                    for line in (
                        process / "state" / "CR-LEDGER.ndjson"
                    )
                    .read_text(encoding="utf-8")
                    .splitlines()
                    if line.strip()
                ]
                self.assertEqual("cancelled", work["status"])
                self.assertEqual([], project.get("active_work_refs", []))
                self.assertEqual([], phase["work_refs"])
                self.assertEqual(termination_status, summary["status"])
                self.assertEqual("n/a", summary["readiness"])
                self.assertEqual("closed", summary["gate_status"])
                self.assertEqual(
                    termination_status,
                    index["items"][0]["lifecycle_status"],
                )
                self.assertEqual("n/a", index["items"][0]["readiness_status"])
                self.assertEqual("closed", index["items"][0]["gate_status"])
                self.assertEqual("cr_termination", ledger[-1]["event_type"])
                self.assertEqual(termination_status, ledger[-1]["status"])
                repeated = cr_lifecycle.plan_cr_termination(
                    release,
                    "CR-101",
                    work_id="WORK-101",
                    termination_status=termination_status,
                    termination_reason="由替代路线接管",
                )
                self.assertEqual("NO_CHANGE", repeated.decision)
                no_change = cr_lifecycle.apply_cr_termination(
                    release,
                    repeated,
                    authorization=authorization,
                    expected_plan_digest=repeated.plan_digest,
                )
                self.assertEqual("NO_CHANGE", no_change["status"])
                self.assertEqual(0, no_change["mutation_count"])

    def test_terminate_rejects_illegal_tuple_process_oid_and_plan_digest_drift(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, _process, _cr_path, _scope = write_termination_fixture(
                Path(directory)
            )
            illegal = cr_lifecycle.plan_cr_termination(
                release,
                "CR-101",
                work_id="WORK-101",
                termination_status="closed",
                termination_reason="非法枚举",
            )
            oid_drift = cr_lifecycle.plan_cr_termination(
                release,
                "CR-101",
                work_id="WORK-101",
                termination_status="cancelled",
                termination_reason="由替代路线接管",
                expected_process_oid="0" * 40,
            )
            plan = cr_lifecycle.plan_cr_termination(
                release,
                "CR-101",
                work_id="WORK-101",
                termination_status="cancelled",
                termination_reason="由替代路线接管",
            )
            authorization = termination_authorization(plan)

            digest_drift = cr_lifecycle.apply_cr_termination(
                release,
                plan,
                authorization=authorization,
                expected_plan_digest="0" * 64,
            )

            self.assertEqual("BLOCKED", illegal.decision)
            self.assertEqual("BLOCKED", oid_drift.decision)
            self.assertEqual("BLOCKED", digest_drift["status"])
            self.assertIn("plan digest", digest_drift["reason"])

    def test_terminate_apply_rejects_missing_wrong_unknown_and_replayed_authorization(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, _process, _cr_path, _scope = write_termination_fixture(
                Path(directory)
            )
            plan = cr_lifecycle.plan_cr_termination(
                release,
                "CR-101",
                work_id="WORK-101",
                termination_status="cancelled",
                termination_reason="由替代路线接管",
            )
            authorization = termination_authorization(plan)
            missing = cr_lifecycle.apply_cr_termination(
                release,
                plan,
                authorization=None,
                expected_plan_digest=plan.plan_digest,
            )
            wrong = cr_lifecycle.TerminationAuthorization(
                **{
                    **authorization.__dict__,
                    "expected_process_oid": "0" * 40,
                }
            )
            wrong_result = cr_lifecycle.apply_cr_termination(
                release,
                plan,
                authorization=wrong,
                expected_plan_digest=plan.plan_digest,
            )
            authorization_path = Path(directory) / "authorization.json"
            authorization_path.write_text(
                json.dumps(
                    {
                        **authorization.__dict__,
                        "unknown": True,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            output = StringIO()
            with redirect_stdout(output):
                unknown_exit = cr_lifecycle.main(
                    [
                        "terminate",
                        "--id",
                        "CR-101",
                        "--work-id",
                        "WORK-101",
                        "--status",
                        "cancelled",
                        "--reason",
                        "由替代路线接管",
                        "--expected-plan-digest",
                        plan.plan_digest,
                        "--authorization-file",
                        str(authorization_path),
                        "--apply",
                        "--project-root",
                        str(release),
                    ]
                )
            first_consumption = cr_lifecycle.apply_cr_termination(
                release,
                plan,
                authorization=authorization,
                expected_plan_digest=plan.plan_digest,
                _fault="after-claim-before-first-replace",
            )
            replay = cr_lifecycle.apply_cr_termination(
                release,
                plan,
                authorization=authorization,
                expected_plan_digest=plan.plan_digest,
            )

            self.assertEqual("BLOCKED", missing["status"])
            self.assertEqual("BLOCKED", wrong_result["status"])
            self.assertEqual(1, unknown_exit)
            self.assertIn("extra=['unknown']", output.getvalue())
            self.assertEqual("BLOCKED", first_consumption["status"])
            self.assertEqual("BLOCKED", replay["status"])
            self.assertIn("already consumed", replay["reason"])

    def test_terminate_partial_mutation_reports_private_rollback_evidence(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, _process, _cr_path, _scope = write_termination_fixture(
                Path(directory)
            )
            plan = cr_lifecycle.plan_cr_termination(
                release,
                "CR-101",
                work_id="WORK-101",
                termination_status="cancelled",
                termination_reason="由替代路线接管",
            )
            authorization = termination_authorization(plan)

            result = cr_lifecycle.apply_cr_termination(
                release,
                plan,
                authorization=authorization,
                expected_plan_digest=plan.plan_digest,
                _fail_after_replace=1,
                _fail_recovery=True,
            )

            self.assertEqual("PARTIAL", result["status"])
            self.assertEqual(1, result["mutation_count"])
            self.assertTrue(result["rollback_errors"])
            self.assertEqual(
                (
                    "private://cr-termination/transactions/"
                    f"{result['transaction_id']}/manifest.json"
                ),
                result["rollback_evidence_ref"],
            )

    def test_terminate_is_discoverable_from_real_top_level_console(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process, cr_path, _scope = write_termination_fixture(
                Path(directory)
            )
            before = cr_path.read_text(encoding="utf-8")
            process_oid = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=process,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            console = Path(sys.executable).with_name("meta-flow")

            result = subprocess.run(
                [
                    str(console),
                    "cr",
                    "terminate",
                    "--id",
                    "CR-101",
                    "--work-id",
                    "WORK-101",
                    "--status",
                    "cancelled",
                    "--reason",
                    "由替代路线接管",
                    "--expected-process-oid",
                    process_oid,
                    "--project-root",
                    str(release),
                ],
                cwd=Path(__file__).resolve().parents[1],
                check=False,
                capture_output=True,
                text=True,
            )

            payload = json.loads(result.stdout)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("READY", payload["decision"])
            self.assertEqual(0, payload["mutation_count"])
            self.assertEqual(7, payload["planned_mutation_count"])
            self.assertEqual(before, cr_path.read_text(encoding="utf-8"))
            self.assertNotIn(str(process), result.stdout)

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
            root, _process, _cr_path, _scope = write_termination_fixture(
                Path(directory)
            )
            plan = cr_lifecycle.plan_status_sync(
                root,
                "CR-101",
                status="closed",
                readiness="READY",
                gate_status="cp8_closed",
                work_id="WORK-101",
                effective_at="2026-07-27T10:00:00+00:00",
            )
            result = apply_ready_status_sync(root, plan)
            self.assertEqual("PASS", result["status"])
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

    def test_conflicts_proposed_is_zero_write_and_preserves_indexed_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_cr(
                root,
                "CR-101",
                conflict_keys="data_contract",
                impact_surface="quant_lab/data",
            )
            write_cr(
                root,
                "CR-102",
                conflict_keys="data_contract",
                impact_surface="quant_lab/research",
            )
            cr_lifecycle.write_index(root)
            index = root / cr_lifecycle.CR_INDEX_REL
            frozen_index = index.read_bytes()
            frozen_paths = sorted(path.relative_to(root) for path in root.rglob("*"))

            proposed_stdout = StringIO()
            with redirect_stdout(proposed_stdout):
                proposed_code = cr_lifecycle.main(
                    [
                        "conflicts",
                        "--proposed",
                        "--id",
                        "CR-999",
                        "--conflict-key",
                        "data_contract",
                        "--project-root",
                        str(root),
                    ]
                )
            proposed = json.loads(proposed_stdout.getvalue())

            self.assertEqual(1, proposed_code)
            self.assertEqual("CONFLICT", proposed["decision"])
            self.assertEqual("CR-101", proposed["conflicts"][0]["existing_cr_id"])
            self.assertEqual(frozen_index, index.read_bytes())
            self.assertEqual(
                frozen_paths,
                sorted(path.relative_to(root) for path in root.rglob("*")),
            )
            self.assertFalse((root / "process" / "changes" / "CR-999.md").exists())

            indexed_stdout = StringIO()
            with redirect_stdout(indexed_stdout):
                indexed_code = cr_lifecycle.main(
                    ["conflicts", "--id", "CR-102", "--project-root", str(root)]
                )
            self.assertEqual(1, indexed_code)
            self.assertIn("CR-102 overlaps CR-101", indexed_stdout.getvalue())

    def test_conflicts_proposed_rejects_missing_payload_existing_id_and_output(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_cr(root, "CR-101", conflict_keys="data_contract")
            cr_lifecycle.write_index(root)

            for extra in (
                [],
                ["--conflict-key", "data_contract"],
                ["--impact-surface", "quant_lab/data", "--output", "preview.json"],
            ):
                cr_id = (
                    "CR-101"
                    if extra == ["--conflict-key", "data_contract"]
                    else "CR-999"
                )
                stdout = StringIO()
                with redirect_stdout(stdout):
                    code = cr_lifecycle.main(
                        [
                            "conflicts",
                            "--proposed",
                            "--id",
                            cr_id,
                            *extra,
                            "--project-root",
                            str(root),
                        ]
                    )
                result = json.loads(stdout.getvalue())
                self.assertEqual(2, code)
                self.assertEqual("INVALID", result["decision"])

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

    def test_native_cr_status_projection_requires_four_source_convergence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cr_path = write_cr(root, "CR-101")
            text = cr_path.read_text(encoding="utf-8")
            cr_path.write_text(
                text.replace(
                    'lifecycle_status: "active"\nreadiness_status: "NOT_READY"\n'
                    'gate_status: "cp8_pending"',
                    'lifecycle_status: "closed"\n'
                    'readiness_status: "READY_WITH_RISK"\n'
                    'gate_status: "cp8_closed"',
                ),
                encoding="utf-8",
            )
            cr_lifecycle.write_index(root)
            cr_lifecycle.write_summary(
                root,
                "CR-101",
                cr_lifecycle.summary_from_cr_file(root, cr_path),
            )
            cr_lifecycle.append_ledger_event(
                root,
                {
                    "event": "status_sync",
                    "event_id": "CR-101-CLOSED",
                    "event_type": "status_sync",
                    "id": "CR-101",
                    "status": "closed",
                    "readiness": "READY_WITH_RISK",
                    "gate_status": "cp8_closed",
                    "full_ref": "process/changes/CR-101.md",
                    "summary_ref": "process/changes/summaries/CR-101.summary.json",
                },
            )

            projection = cr_lifecycle.project_native_cr_status(
                root,
                cr_id="CR-101",
            )

            self.assertEqual("PASS", projection.decision)
            self.assertEqual(
                ("closed", "ready_with_risk", "cp8_closed"),
                (
                    projection.lifecycle_status,
                    projection.readiness_status,
                    projection.gate_status,
                ),
            )
            self.assertEqual((), projection.findings)

    def test_native_cr_status_projection_blocks_derived_status_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cr_path = write_cr(root, "CR-101")
            cr_lifecycle.write_index(root)
            summary = cr_lifecycle.summary_from_cr_file(root, cr_path)
            summary["status"] = "closed"
            cr_lifecycle.write_summary(root, "CR-101", summary)
            cr_lifecycle.append_ledger_event(
                root,
                {
                    "event": "status_sync",
                    "event_id": "CR-101-ACTIVE",
                    "event_type": "status_sync",
                    "id": "CR-101",
                    "status": "active",
                    "readiness": "NOT_READY",
                    "gate_status": "cp8_pending",
                    "full_ref": "process/changes/CR-101.md",
                    "summary_ref": "process/changes/summaries/CR-101.summary.json",
                },
            )

            projection = cr_lifecycle.project_native_cr_status(
                root,
                cr_id="CR-101",
            )

            self.assertEqual("BLOCKED", projection.decision)
            self.assertIn("CR_SUMMARY_STATUS_DIVERGED", projection.findings)


if __name__ == "__main__":
    unittest.main()
