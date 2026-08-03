from __future__ import annotations

import ast
import json
import tempfile
import unittest
from functools import partial
from pathlib import Path

from cr_lifecycle_test_support import LifecycleFixtureCollaborators
from cr_lifecycle_test_support import write_cr as _write_cr

from meta_flow.project.onboarding import (
    ProjectInitRequest,
    apply_project_init,
    plan_project_init,
)
from meta_flow.project.onboarding_contract import (
    AUTHORIZATION_KIND,
    AUTHORIZATION_SOURCE,
    OnboardingAuthorization,
)
from meta_flow.project.process_route import _resolve_runtime_ref
from meta_flow.project.scale import dump_yaml, load_yaml_object
from meta_flow.work.scope import WorkScope
from meta_flow.workflow import cr_analysis, cr_index, cr_projection

_FIXTURE_COLLABORATORS = LifecycleFixtureCollaborators(
    project_init_request=ProjectInitRequest,
    plan_project_init=plan_project_init,
    apply_project_init=apply_project_init,
    onboarding_authorization=OnboardingAuthorization,
    authorization_source=AUTHORIZATION_SOURCE,
    authorization_kind=AUTHORIZATION_KIND,
    resolve_runtime_ref=_resolve_runtime_ref,
    dump_yaml=dump_yaml,
    load_yaml_object=load_yaml_object,
    work_scope=WorkScope,
)
write_cr = partial(_write_cr, collaborators=_FIXTURE_COLLABORATORS)


def write_feature_registry(root: Path) -> Path:
    path = _resolve_runtime_ref(root, "process/docs/design/FEATURE-REGISTRY.yaml")
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
    path = _resolve_runtime_ref(root, "process/docs/design/CAPABILITY-REGISTRY.yaml")
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
                        "deprecated_by": (
                            "CAP-PG-REGISTRY-REFS-V2" if status == "deprecated" else ""
                        ),
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


def write_impact_rules(root: Path, rules: list[dict[str, str | bool]]) -> Path:
    path = root / "process" / "project" / "IMPACT-SURFACE-RULES.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema_version": 1, "rules": rules}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return path


class CRAnalysisTests(unittest.TestCase):
    def test_exact_inventory_and_dependency_boundary(self) -> None:
        source = Path(cr_analysis.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        self.assertEqual(
            {
                "collect_check_errors",
                "collect_check_warnings",
                "_conflict_surface",
                "conflict_report",
                "proposed_conflict_report",
                "build_impact_report",
                "write_impact_report",
                "_load_summary",
                "render_cr_brief",
                "render_goal_brief",
            },
            {
                node.name
                for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.ClassDef))
            },
        )
        direct_modules = {
            node.module
            for node in tree.body
            if isinstance(node, ast.ImportFrom) and node.module
        }
        self.assertTrue(
            {
                "meta_flow.workflow.cr_status_sync",
                "meta_flow.workflow.cr_status_transaction",
                "meta_flow.workflow.cr_termination",
                "meta_flow.workflow.cr_lifecycle",
                "meta_flow.workflow.cr_cli",
            }.isdisjoint(direct_modules)
        )

    def test_collect_check_errors_rejects_invalid_index_cr_type(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_cr(root, "CR-101")
            cr_index.write_index(root)
            index_path = root / "process" / "changes" / "CR-INDEX.json"
            index = json.loads(index_path.read_text(encoding="utf-8"))
            index["items"][0]["cr_type"] = "requirement-change"
            index_path.write_text(
                json.dumps(index, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            errors = cr_analysis.collect_check_errors(root)

            self.assertIn("CR index item CR-101: invalid cr_type requirement-change", errors)

    def test_collect_check_warnings_reports_open_governance_overlap(self) -> None:
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

            warnings = cr_analysis.collect_check_warnings(root)

            self.assertTrue(
                any(
                    "CR-201 governance dependency open_governance_dependency_needs_review"
                    in warning
                    for warning in warnings
                )
            )

    def test_conflict_reports_cover_indexed_and_proposed_zero_write_paths(self) -> None:
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
            cr_index.write_index(root)
            index_path = root / "process" / "changes" / "CR-INDEX.json"
            frozen_index = index_path.read_bytes()
            frozen_paths = sorted(path.relative_to(root) for path in root.rglob("*"))

            conflicts, warnings = cr_analysis.conflict_report(root, "CR-102")
            proposed = cr_analysis.proposed_conflict_report(
                root,
                cr_id="CR-999",
                conflict_keys=["data_contract"],
                impact_surface=[],
                impact_fields={},
            )

            self.assertEqual([], warnings)
            self.assertIn("CR-102 overlaps CR-101", conflicts[0])
            self.assertEqual("CONFLICT", proposed["decision"])
            self.assertEqual("CR-101", proposed["conflicts"][0]["existing_cr_id"])
            self.assertEqual(frozen_index, index_path.read_bytes())
            self.assertEqual(
                frozen_paths,
                sorted(path.relative_to(root) for path in root.rglob("*")),
            )

    def test_proposed_conflict_rejects_invalid_and_existing_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_cr(root, "CR-101", conflict_keys="data_contract")
            cr_index.write_index(root)

            invalid = cr_analysis.proposed_conflict_report(
                root,
                cr_id="invalid",
                conflict_keys=["data_contract"],
                impact_surface=[],
                impact_fields={},
            )
            existing = cr_analysis.proposed_conflict_report(
                root,
                cr_id="CR-101",
                conflict_keys=["data_contract"],
                impact_surface=[],
                impact_fields={},
            )
            missing = cr_analysis.proposed_conflict_report(
                root,
                cr_id="CR-999",
                conflict_keys=[],
                impact_surface=[],
                impact_fields={},
            )

            self.assertEqual("CR_CONFLICT_PROPOSED_INPUT_INVALID", invalid["code"])
            self.assertEqual("CR_CONFLICT_PROPOSED_ID_EXISTS", existing["code"])
            self.assertEqual("CR_CONFLICT_PROPOSED_INPUT_REQUIRED", missing["code"])
            self.assertEqual(0, invalid["mutation_count"])
            self.assertEqual(0, existing["mutation_count"])
            self.assertEqual(0, missing["mutation_count"])

    def test_impact_report_preserves_blockers_and_uncategorized_legacy_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_feature_registry(root)
            write_capability_registry(root)
            cr_path = write_cr(
                root,
                "CR-201",
                impact_surface='"some_custom_domain"',
                extra_frontmatter='impact_capability_refs: ["CAP-PG-UNKNOWN"]',
            )

            report = cr_analysis.build_impact_report(root)
            cr_projection.write_summary(
                root,
                "CR-201",
                cr_projection.summary_from_cr_file(root, cr_path),
            )
            brief = cr_analysis.render_cr_brief(root, "CR-201")

            self.assertEqual("enforce", report["mode"])
            self.assertEqual(1, report["summary"]["blocker_count"])
            self.assertEqual(1, report["summary"]["uncategorized_cr_count"])
            self.assertEqual(["some_custom_domain"], report["items"][0]["uncategorized_legacy"])
            self.assertEqual("CAP-PG-UNKNOWN", report["items"][0]["blockers"][0]["input_ref"])
            self.assertEqual("E_REF_UNRESOLVED", report["items"][0]["blockers"][0]["code"])
            self.assertIn("## 未分类 legacy impact_surface", brief)
            self.assertIn("- some_custom_domain", brief)
            self.assertIn("follow-up candidate: CR-201-IMPACT-UNCATEGORIZED", brief)

    def test_write_impact_report_is_explicit_report_serialization_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "reports" / "impact.json"
            report = {"schema_version": 1, "kind": "fixture"}

            result = cr_analysis.write_impact_report(output, report)

            self.assertEqual(output, result)
            self.assertEqual(report, json.loads(output.read_text(encoding="utf-8")))
            self.assertEqual(
                [Path("reports"), Path("reports/impact.json")],
                sorted(path.relative_to(root) for path in root.rglob("*")),
            )

    def test_render_cr_and_goal_briefs_preserve_goal_and_impact_golden(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_feature_registry(root)
            write_capability_registry(root)
            cr_path = write_cr(
                root,
                "CR-101",
                extra_frontmatter=(
                    'goal_ref: "GOAL-001"\n'
                    'goal_statement: "降低人工确认理解成本"\n'
                    'user_goal_impact: "用户先看目标影响"\n'
                    'decision_burden: "low"\n'
                    'split_rationale: "与 runtime 授权边界不同"\n'
                    'not_authorized_by_approve: ["credentials"]\n'
                    'impact_capability_refs: ["registry refs"]'
                ),
            )
            summary = cr_projection.summary_from_cr_file(root, cr_path)
            cr_projection.write_summary(root, "CR-101", summary)
            cr_index.write_index(root)

            brief = cr_analysis.render_cr_brief(root, "CR-101")
            goal_brief = cr_analysis.render_goal_brief(root, "GOAL-001")

            self.assertIn("降低人工确认理解成本", brief)
            self.assertIn("与 runtime 授权边界不同", brief)
            self.assertIn("credentials", brief)
            self.assertIn("capability.normalized: CAP-PG-REGISTRY-REFS", brief)
            self.assertIn("CR-101", goal_brief)
            self.assertIn("用户先看目标影响", goal_brief)

    def test_render_brief_honors_enforce_and_project_classification_rules(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_feature_registry(root)
            write_capability_registry(root, status="deprecated")
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
            cr_path = write_cr(
                root,
                "CR-201",
                impact_surface='"MOD-meta_flow/project/rules.py"',
                extra_frontmatter=(
                    'impact_capability_refs: ["CAP-PG-REGISTRY-REFS"]'
                ),
            )
            cr_projection.write_summary(
                root,
                "CR-201",
                cr_projection.summary_from_cr_file(root, cr_path),
            )

            audit_brief = cr_analysis.render_cr_brief(root, "CR-201")
            enforce_brief = cr_analysis.render_cr_brief(root, "CR-201", mode="enforce")

            self.assertNotIn("## 未分类 legacy impact_surface", audit_brief)
            self.assertIn("capability.resolution_mode: audit", audit_brief)
            self.assertNotIn("capability ref blockers", audit_brief)
            self.assertIn("capability.resolution_mode: enforce", enforce_brief)
            self.assertIn(
                "CAP-PG-REGISTRY-REFS: deprecated E_REF_DEPRECATED",
                enforce_brief,
            )

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
                cr_analysis.build_impact_report(root)

            self.assertIn("target_field is invalid", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
