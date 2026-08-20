from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from meta_flow.policies import gate_profiles, route_plan
from meta_flow.project.onboarding import ProjectInitRequest, apply_project_init, plan_project_init
from meta_flow.project.onboarding_contract import (
    AUTHORIZATION_KIND,
    AUTHORIZATION_SOURCE,
    OnboardingAuthorization,
)


def checkpoints(plan: dict[str, object]) -> list[str]:
    return [str(stage["checkpoint"]) for stage in plan["stages"]]  # type: ignore[index]


class RoutePlanTests(unittest.TestCase):
    def test_c0_dry_run_cli_forwards_to_retired_stub_without_semantic_plan(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            exit_code = route_plan.main(
                [
                    "c0-dry-run",
                    "--project-root",
                    ".",
                    "--cr-id",
                    "CR-061",
                    "--story-result",
                    "process/checks/CP6-STORY-CR061-S01.result.json",
                    "--story-result",
                    "process/checks/CP6-STORY-CR061-S02.result.json",
                    "--story-result",
                    "process/checks/CP6-STORY-CR061-S03.result.json",
                    "--format",
                    "json",
                ]
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(1, exit_code)
        self.assertEqual("BLOCKED", payload["decision"])
        self.assertEqual(["C0_V2_RETIRED"], payload["blockers"])
        self.assertEqual(0, payload["planned_mutation_count"])

    def test_route_plan_check_resolves_logical_ref_through_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            release = parent / "release"
            release.mkdir()
            subprocess.run(["git", "init", "-b", "main"], cwd=release, check=True, capture_output=True)
            (release / "README.md").write_text("fixture\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=release, check=True, capture_output=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Meta Flow Test",
                    "-c",
                    "user.email=meta-flow@example.invalid",
                    "commit",
                    "-m",
                    "initial",
                ],
                cwd=release,
                check=True,
                capture_output=True,
            )
            plan = plan_project_init(ProjectInitRequest(release, "route-plan", "Route Plan"))
            payload = plan.as_dict()
            authorization = OnboardingAuthorization(
                schema_version=1,
                authorization_id=f"auth-{plan.plan_digest[:12]}",
                authorization_source=AUTHORIZATION_SOURCE,
                authorization_kind=AUTHORIZATION_KIND,
                operation=payload["operation"],
                decision_ref=payload["decision_ref"],
                project_id=payload["project_id"],
                plan_digest=plan.plan_digest,
                expected_oids=payload["base_oids"],
                expires_at="2099-01-01T00:00:00+00:00",
            )
            apply_project_init(plan, authorization)

            process = parent / "route-plan-process"
            cr_path = process / "changes" / "CR-156.md"
            artifact = process / "checks" / "CP0-CR156.route-plan.json"
            cr_path.parent.mkdir(parents=True)
            cr_path.write_text(
                """---
cr_id: "CR-156"
cr_type: "process"
gate_profile: "process-lite"
route_plan_ref: "process/checks/CP0-CR156.route-plan.json"
cr_trait_uses_existing_evidence_only: true
cr_trait_existing_evidence_refs: "process/evidence/CR156.index.json"
product_baseline_refresh_required: false
---

# CR-156
""",
                encoding="utf-8",
            )
            route_plan.write_route_plan(
                artifact,
                route_plan.derive_route_plan_from_mapping(route_plan.parse_cr_frontmatter(cr_path)),
            )

            errors, warnings = route_plan.validate_route_plan_for_cr(release, cr_path)

            self.assertEqual([], errors)
            self.assertEqual([], warnings)
            self.assertFalse((release / "process").exists())

    def test_process_lite_existing_evidence_routes_cp0_cp2_cp8(self) -> None:
        plan = route_plan.derive_route_plan(
            cr_type="process",
            gate_profile="process-lite",
            cr_trait={
                "uses_existing_evidence_only": True,
                "existing_evidence_refs": ["process/evidence/CR156.index.json"],
            },
        )

        self.assertEqual("PASS", plan["decision"])
        self.assertEqual(["CP0", "CP2", "CP8"], checkpoints(plan))
        self.assertEqual(["init", "requirement-clarification", "documentation"], plan["phase_sequence"])
        applicability = plan["checkpoint_applicability"]
        for checkpoint in ("CP3", "CP4", "CP5", "CP6", "CP7"):
            self.assertEqual("N/A", applicability[checkpoint]["decision"])  # type: ignore[index]
        self.assertEqual("optional", applicability["CP2"]["human_gate"])  # type: ignore[index]

    def test_existing_evidence_without_evidence_refs_upgrades_cp2_human_gate(self) -> None:
        plan = route_plan.derive_route_plan(
            cr_type="process",
            gate_profile="process-lite",
            cr_trait={"uses_existing_evidence_only": True},
        )

        self.assertEqual("required", plan["checkpoint_applicability"]["CP2"]["human_gate"])  # type: ignore[index]

    def test_process_lite_implementation_keeps_cp6_cp7_and_derives_verification(self) -> None:
        plan = route_plan.derive_route_plan(
            cr_type="process",
            gate_profile="process-lite",
            cr_trait={"has_new_implementation": True},
        )

        self.assertEqual("PASS", plan["decision"])
        self.assertIn("CP6", checkpoints(plan))
        self.assertIn("CP7", checkpoints(plan))
        self.assertIn("has_new_verification auto-derived from has_new_implementation", plan["warnings"])
        self.assertTrue(plan["checkpoint_applicability"]["CP6"]["applies"])  # type: ignore[index]
        self.assertTrue(plan["checkpoint_applicability"]["CP7"]["applies"])  # type: ignore[index]

    def test_standard_code_implementation_keeps_cp5_design_readiness(self) -> None:
        plan = route_plan.derive_route_plan(
            cr_type="process",
            gate_profile="standard-code",
            cr_trait={"has_new_implementation": True},
        )

        self.assertEqual("PASS", plan["decision"])
        self.assertIn("CP5", checkpoints(plan))
        self.assertEqual("required", plan["checkpoint_applicability"]["CP5"]["human_gate"])  # type: ignore[index]
        self.assertIn("CP6", checkpoints(plan))
        self.assertIn("CP7", checkpoints(plan))

    def test_new_implementation_with_verification_false_without_waiver_blocks(self) -> None:
        plan = route_plan.derive_route_plan(
            cr_type="process",
            gate_profile="process-lite",
            cr_trait={"has_new_implementation": True, "has_new_verification": False},
        )

        self.assertEqual("BLOCKED", plan["decision"])
        self.assertIn(
            "has_new_implementation=true requires CP7 unless both verification_waiver_reason and verification_waiver_ref are set",
            plan["blockers"],
        )

    def test_new_implementation_with_verification_waiver_reason_only_blocks(self) -> None:
        plan = route_plan.derive_route_plan(
            cr_type="process",
            gate_profile="process-lite",
            cr_trait={
                "has_new_implementation": True,
                "has_new_verification": False,
                "verification_waiver_reason": "reason without approval reference",
            },
        )

        self.assertEqual("BLOCKED", plan["decision"])
        self.assertNotEqual("WAIVED", plan["checkpoint_applicability"]["CP7"].get("decision"))  # type: ignore[index]

    def test_new_implementation_with_verification_waiver_ref_only_blocks(self) -> None:
        plan = route_plan.derive_route_plan(
            cr_type="process",
            gate_profile="process-lite",
            cr_trait={
                "has_new_implementation": True,
                "has_new_verification": False,
                "verification_waiver_ref": "process/checkpoints/CP8.md#DQ-001",
            },
        )

        self.assertEqual("BLOCKED", plan["decision"])
        self.assertNotEqual("WAIVED", plan["checkpoint_applicability"]["CP7"].get("decision"))  # type: ignore[index]

    def test_new_implementation_with_verification_waiver_marks_cp7_waived(self) -> None:
        plan = route_plan.derive_route_plan(
            cr_type="process",
            gate_profile="process-lite",
            cr_trait={
                "has_new_implementation": True,
                "has_new_verification": False,
                "verification_waiver_reason": "docs-only checker fixture update",
                "verification_waiver_ref": "process/checkpoints/CP8.md#DQ-001",
            },
        )

        self.assertEqual("PASS", plan["decision"])
        self.assertEqual("WAIVED", plan["checkpoint_applicability"]["CP7"]["decision"])  # type: ignore[index]
        self.assertNotIn("CP7", checkpoints(plan))

    def test_story_decomposition_outside_profile_requires_upgrade_and_keeps_cp5_human_gate(self) -> None:
        plan = route_plan.derive_route_plan(
            cr_type="process",
            gate_profile="process-lite",
            cr_trait={"requires_story_decomposition": True},
        )

        self.assertEqual("BLOCKED", plan["decision"])
        self.assertIn("CP5", checkpoints(plan))
        self.assertEqual("required", plan["checkpoint_applicability"]["CP5"]["human_gate"])  # type: ignore[index]
        self.assertTrue(
            any(item["checkpoint"] == "CP5" for item in plan["profile_upgrade_required"])  # type: ignore[index]
        )

    def test_architecture_review_outside_profile_requires_upgrade(self) -> None:
        plan = route_plan.derive_route_plan(
            cr_type="process",
            gate_profile="process-lite",
            cr_trait={"requires_architecture_review": True},
        )

        self.assertEqual("BLOCKED", plan["decision"])
        self.assertEqual("required", plan["checkpoint_applicability"]["CP3"]["human_gate"])  # type: ignore[index]
        self.assertEqual("architecture-major", plan["profile_upgrade_required"][0]["recommended_gate_profile"])  # type: ignore[index]

    def test_docs_lite_implementation_requires_profile_upgrade(self) -> None:
        plan = route_plan.derive_route_plan(
            cr_type="docs",
            gate_profile="docs-lite",
            cr_trait={"has_new_implementation": True},
        )

        self.assertEqual("BLOCKED", plan["decision"])
        self.assertIn("CP6", checkpoints(plan))
        self.assertTrue(
            any(item["checkpoint"] == "CP6" for item in plan["profile_upgrade_required"])  # type: ignore[index]
        )

    def test_micro_design_requires_profile_upgrade_and_human_gate(self) -> None:
        plan = route_plan.derive_route_plan(
            cr_type="process",
            gate_profile="micro",
            cr_trait={"has_new_design": True},
        )

        self.assertEqual("BLOCKED", plan["decision"])
        self.assertEqual("required", plan["checkpoint_applicability"]["CP3"]["human_gate"])  # type: ignore[index]
        self.assertTrue(
            any(item["checkpoint"] == "CP3" for item in plan["profile_upgrade_required"])  # type: ignore[index]
        )

    def test_product_baseline_adds_cp1(self) -> None:
        plan = route_plan.derive_route_plan(
            cr_type="process",
            gate_profile="process-lite",
            cr_trait={"uses_existing_evidence_only": True, "existing_evidence_refs": ["evidence.json"]},
            product_baseline_refresh_required=True,
        )

        self.assertIn("CP1", checkpoints(plan))
        self.assertTrue(plan["checkpoint_applicability"]["CP1"]["applies"])  # type: ignore[index]

    def test_phase_sequence_from_checkpoint_stages_deduplicates_phase_order(self) -> None:
        self.assertEqual(
            ["init", "requirement-clarification", "story-planning", "story-execution", "documentation"],
            route_plan.phase_sequence_from_stages(["CP0", "CP1", "CP2", "CP5", "CP6", "CP7", "CP8"]),
        )

    def test_optional_gate_auto_clean_decision_passes_only_when_no_human_signal_exists(self) -> None:
        decision = route_plan.optional_gate_auto_clean_decision(
            checkpoint="CP2",
            human_gate="optional",
            precheck_decision="PASS",
            decision_count=0,
        )

        self.assertTrue(decision["auto_clean"])
        self.assertEqual("auto-clean-gate", decision["approval_source"])

    def test_optional_gate_auto_clean_decision_upgrades_on_decision_items(self) -> None:
        decision = route_plan.optional_gate_auto_clean_decision(
            checkpoint="CP2",
            human_gate="optional",
            precheck_decision="PASS",
            decision_count=1,
        )

        self.assertFalse(decision["auto_clean"])
        self.assertEqual("required", decision["upgrade_to"])
        self.assertIn("decision_items_present", decision["blockers"])

    def test_lite_stage_normalizes_to_standard_checkpoint_id(self) -> None:
        profile = gate_profiles.default_gate_profiles()["profiles"]["process-lite"]
        stages = route_plan.normalize_profile(profile)

        self.assertEqual(
            [
                {"checkpoint": "CP0", "mode": "standard", "human_gate": "none"},
                {"checkpoint": "CP2", "mode": "lite", "human_gate": "optional"},
                {"checkpoint": "CP6", "mode": "lite", "human_gate": "none"},
                {"checkpoint": "CP7", "mode": "lite", "human_gate": "none"},
                {"checkpoint": "CP8", "mode": "lite", "human_gate": "required"},
            ],
            stages,
        )

    def test_route_plan_cli_prints_machine_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = StringIO()
            with redirect_stdout(output):
                exit_code = route_plan.main(
                    [
                        "plan",
                        "--project-root",
                        str(root),
                        "--cr-type",
                        "process",
                        "--gate-profile",
                        "process-lite",
                        "--cr-trait",
                        json.dumps({"uses_existing_evidence_only": True, "existing_evidence_refs": ["evidence.json"]}),
                    ]
                )

            self.assertEqual(0, exit_code)
            self.assertIn('"checkpoint_applicability"', output.getvalue())

    def test_cr_trait_from_flat_frontmatter_mapping(self) -> None:
        trait = route_plan.cr_trait_from_mapping(
            {
                "cr_trait_uses_existing_evidence_only": "false",
                "cr_trait_has_new_implementation": "true",
                "cr_trait_has_new_verification": "",
                "cr_trait_existing_evidence_refs": "[process/evidence/CR156.index.json]",
                "cr_trait_verification_waiver_reason": "",
            }
        )

        self.assertEqual(
            {
                "uses_existing_evidence_only": False,
                "has_new_implementation": True,
                "existing_evidence_refs": ["process/evidence/CR156.index.json"],
            },
            trait,
        )
        self.assertNotIn("has_new_verification", trait)
        self.assertNotIn("verification_waiver_reason", trait)

    def test_derive_route_plan_from_cr_frontmatter_mapping(self) -> None:
        plan = route_plan.derive_route_plan_from_mapping(
            {
                "cr_type": '"process"',
                "gate_profile": '"standard-code"',
                "cr_trait_has_new_implementation": "true",
                "product_baseline_refresh_required": "false",
            }
        )

        self.assertEqual("PASS", plan["decision"])
        self.assertEqual(["CP0", "CP2", "CP5", "CP6", "CP7", "CP8"], checkpoints(plan))

    def test_route_plan_cli_from_cr_writes_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cr_path = root / "process" / "changes" / "CR-156.md"
            cr_path.parent.mkdir(parents=True)
            cr_path.write_text(
                """---
cr_id: "CR-156"
cr_type: "process"
gate_profile: "process-lite"
cr_trait_uses_existing_evidence_only: true
cr_trait_existing_evidence_refs: "process/evidence/CR156.index.json"
product_baseline_refresh_required: false
---

# CR-156
""",
                encoding="utf-8",
            )
            artifact = root / "process" / "checks" / "CP0-CR156.route-plan.json"

            output = StringIO()
            with redirect_stdout(output):
                exit_code = route_plan.main(
                    [
                        "plan",
                        "--from-cr",
                        "process/changes/CR-156.md",
                        "--output",
                        "process/checks/CP0-CR156.route-plan.json",
                        "--project-root",
                        str(root),
                    ]
                )

            self.assertEqual(0, exit_code)
            self.assertTrue(artifact.is_file())
            payload = json.loads(artifact.read_text(encoding="utf-8"))
            self.assertEqual(["CP0", "CP2", "CP8"], checkpoints(payload))
            self.assertEqual("N/A", payload["checkpoint_applicability"]["CP6"]["decision"])
            self.assertIn("wrote:", output.getvalue())

    def test_route_plan_relative_refs_are_process_root_stable_across_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cr_path = root / "process/changes/CR-157.md"
            cr_path.parent.mkdir(parents=True)
            cr_path.write_text(
                "---\ncr_id: CR-157\ncr_type: process\n"
                "gate_profile: process-lite\n"
                "cr_trait_uses_existing_evidence_only: true\n"
                "cr_trait_existing_evidence_refs: process/evidence/CR157.json\n"
                "---\n",
                encoding="utf-8",
            )
            cwd_a = root / "a"
            cwd_b = root / "b"
            cwd_a.mkdir()
            cwd_b.mkdir()
            original_cwd = Path.cwd()
            try:
                for cwd, output_ref in (
                    (cwd_a, "checks/CP0-CR157-a.route-plan.json"),
                    (cwd_b, "process/checks/CP0-CR157-b.route-plan.json"),
                ):
                    os.chdir(cwd)
                    self.assertEqual(
                        0,
                        route_plan.main(
                            [
                                "plan",
                                "--from-cr",
                                "changes/CR-157.md",
                                "--output",
                                output_ref,
                                "--project-root",
                                str(root),
                            ]
                        ),
                    )
            finally:
                os.chdir(original_cwd)

            first = root / "process/checks/CP0-CR157-a.route-plan.json"
            second = root / "process/checks/CP0-CR157-b.route-plan.json"
            self.assertEqual(
                json.loads(first.read_text(encoding="utf-8")),
                json.loads(second.read_text(encoding="utf-8")),
            )
            self.assertFalse((cwd_a / "checks").exists())
            self.assertFalse((cwd_b / "process").exists())

            with self.assertRaisesRegex(SystemExit, "safe process logical ref"):
                route_plan.main(
                    [
                        "plan",
                        "--from-cr",
                        str(cr_path),
                        "--project-root",
                        str(root),
                    ]
                )

    def test_route_plan_check_from_cr_validates_matching_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cr_path = root / "process" / "changes" / "CR-156.md"
            artifact = root / "process" / "checks" / "CP0-CR156.route-plan.json"
            cr_path.parent.mkdir(parents=True)
            cr_path.write_text(
                """---
cr_id: "CR-156"
cr_type: "process"
gate_profile: "process-lite"
route_plan_ref: "process/checks/CP0-CR156.route-plan.json"
cr_trait_uses_existing_evidence_only: true
cr_trait_existing_evidence_refs: "process/evidence/CR156.index.json"
product_baseline_refresh_required: false
---

# CR-156
""",
                encoding="utf-8",
            )
            plan = route_plan.derive_route_plan_from_mapping(route_plan.parse_cr_frontmatter(cr_path))
            route_plan.write_route_plan(artifact, plan)

            errors, warnings = route_plan.validate_route_plan_for_cr(root, cr_path)
            self.assertEqual([], errors)
            self.assertEqual([], warnings)

    def test_route_plan_check_detects_stale_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cr_path = root / "process" / "changes" / "CR-156.md"
            artifact = root / "process" / "checks" / "CP0-CR156.route-plan.json"
            cr_path.parent.mkdir(parents=True)
            cr_path.write_text(
                """---
cr_id: "CR-156"
cr_type: "process"
gate_profile: "process-lite"
route_plan_ref: "process/checks/CP0-CR156.route-plan.json"
cr_trait_uses_existing_evidence_only: true
cr_trait_existing_evidence_refs: "process/evidence/CR156.index.json"
product_baseline_refresh_required: false
---

# CR-156
""",
                encoding="utf-8",
            )
            plan = route_plan.derive_route_plan_from_mapping(route_plan.parse_cr_frontmatter(cr_path))
            route_plan.write_route_plan(artifact, plan)
            cr_path.write_text(
                cr_path.read_text(encoding="utf-8").replace(
                    "cr_trait_uses_existing_evidence_only: true",
                    "cr_trait_uses_existing_evidence_only: false\ncr_trait_has_new_implementation: true",
                ),
                encoding="utf-8",
            )

            errors, _warnings = route_plan.validate_route_plan_for_cr(root, cr_path)
            self.assertTrue(any("stale or inconsistent" in error for error in errors))

    def test_route_plan_check_requires_route_plan_ref(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cr_path = root / "process" / "changes" / "CR-156.md"
            cr_path.parent.mkdir(parents=True)
            cr_path.write_text(
                """---
cr_id: "CR-156"
cr_type: "process"
gate_profile: "process-lite"
cr_trait_uses_existing_evidence_only: true
cr_trait_existing_evidence_refs: "process/evidence/CR156.index.json"
product_baseline_refresh_required: false
---

# CR-156
""",
                encoding="utf-8",
            )

            errors, _warnings = route_plan.validate_route_plan_for_cr(root, cr_path)
            self.assertEqual(["CR-156 missing route_plan_ref"], errors)


if __name__ == "__main__":
    unittest.main()
