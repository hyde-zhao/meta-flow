from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from meta_flow.checks import state_transition
from meta_flow.checks.frozen_cp6_evidence import FrozenCp6EvidenceV1
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
    def _ready_c0_result(
        self,
        *,
        scope_digest: str = "c" * 64,
    ) -> state_transition.C0ResultV1:
        frozen = [
            FrozenCp6EvidenceV1(
                story_id=f"STORY-CR061-S0{index}",
                release_oid="a" * 40,
                process_oid="b" * 40,
                scope_digest=scope_digest,
                implementation_digest=chr(99 + index) * 64,
                dependency_digests={"upstream": str(index) * 64},
                cp6_result_ref=f"process/checks/CP6-STORY-CR061-S0{index}.result.json",
            ).as_dict()
            for index in range(1, 4)
        ]
        consumers = [
            state_transition.project_c0_consumer(
                consumer_id=consumer_id,
                operation=operation,
                attempts=[{"returncode": 0, "stdout": "PASS", "stderr": ""}],
                absolute_process_path="/bound/process",
            )
            for consumer_id, operation in route_plan.C0_CONSUMERS
        ]
        return state_transition.build_c0_result(
            cr_id="CR-061",
            release_oid="a" * 40,
            process_oid="b" * 40,
            scope_digest=scope_digest,
            input_evidence_refs=[
                f"process/{kind}/STORY-CR061-S0{index}.json"
                for index in range(1, 4)
                for kind in ("checks", "returns", "evidence")
            ],
            frozen_evidence=frozen,
            consumer_inventory=consumers,
            planned_transitions=[
                {
                    "subject": f"STORY-CR061-S0{index}",
                    "from": "bootstrap-cp6-pass",
                    "to": "ready-for-verification",
                }
                for index in range(1, 4)
            ],
            mutation_allowlist=[
                "process/DEVELOPMENT-PLAN.yaml",
                "process/checks/C0-CR-061-PROJECTOR-CUTOVER.result.json",
                "process/checks/C0-CR-061-PROJECTOR-CUTOVER.summary.md",
                "process/state/CHECKPOINT-LEDGER.ndjson",
                "process/state/GATE-LEDGER.ndjson",
            ],
        )

    def _c0_authorization(
        self,
        plan: state_transition.C0ResultV1,
        *,
        authorization_id: str = "AUTH-CR061-C0-TEST-001",
    ) -> route_plan.C0AuthorizationV1:
        return route_plan.C0AuthorizationV1.from_dict(
            {
                "schema_version": 1,
                "authorization_id": authorization_id,
                "authorization_source": route_plan.C0_AUTHORIZATION_SOURCE,
                "authorization_kind": route_plan.C0_AUTHORIZATION_KIND,
                "operation": route_plan.C0_APPLY_OPERATION,
                "decision_ref": "process/checkpoints/C0-CR-061-PROJECTOR-CUTOVER-AUTHORIZATION.md",
                "cr_id": "CR-061",
                "work_id": "GOV-006-KERNEL-001",
                "expected_release_oid": plan.release_oid,
                "expected_process_oid": plan.process_oid,
                "scope_digest": plan.scope_digest,
                "plan_digest": plan.as_dict()["plan_digest"],
                "mutation_allowlist": list(plan.mutation_allowlist),
                "expires_at": "2099-01-01T00:00:00+00:00",
                "single_use": True,
            }
        )

    def test_c0_dry_run_cli_uses_public_route_entry_and_prints_21_key_result(self) -> None:
        expected = self._ready_c0_result()
        output = StringIO()
        with (
            patch.object(route_plan, "build_c0_dry_run", return_value=expected) as builder,
            redirect_stdout(output),
        ):
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
        self.assertEqual(0, exit_code)
        self.assertEqual(21, len(payload))
        self.assertEqual("READY", payload["decision"])
        builder.assert_called_once()

    def test_release_root_process_entry_detection_is_fail_closed_for_all_entry_types(self) -> None:
        def create_directory(path: Path) -> None:
            path.mkdir()

        def create_file(path: Path) -> None:
            path.write_text("not a process root\n", encoding="utf-8")

        def create_symlink(path: Path) -> None:
            target = path.parent / "installed-process"
            target.mkdir()
            path.symlink_to(target, target_is_directory=True)

        def create_broken_symlink(path: Path) -> None:
            path.symlink_to(path.parent / "missing-process", target_is_directory=True)

        creators = {
            "directory": create_directory,
            "file": create_file,
            "symlink": create_symlink,
            "broken-symlink": create_broken_symlink,
        }
        with tempfile.TemporaryDirectory() as directory:
            self.assertFalse(route_plan._release_root_has_process_entry(Path(directory)))

        for label, creator in creators.items():
            with self.subTest(entry_type=label), tempfile.TemporaryDirectory() as directory:
                release_root = Path(directory)
                creator(release_root / "process")
                self.assertTrue(route_plan._release_root_has_process_entry(release_root))

    def test_c0_return_ref_prefers_versioned_result_contract_and_rejects_noncanonical_ref(
        self,
    ) -> None:
        self.assertEqual(
            "process/returns/STORY-CR061-S01.CP6.revalidation-01.return.json",
            route_plan._c0_return_ref(
                {
                    "return_ref": (
                        "process/returns/"
                        "STORY-CR061-S01.CP6.revalidation-01.return.json"
                    )
                },
                story_id="STORY-CR061-S01",
            ),
        )
        self.assertEqual(
            "process/returns/STORY-CR061-S01.CP6.return.json",
            route_plan._c0_return_ref({}, story_id="STORY-CR061-S01"),
        )
        with self.assertRaisesRegex(ValueError, "canonical process/returns"):
            route_plan._c0_return_ref(
                {"return_ref": "process/checks/not-a-return.json"},
                story_id="STORY-CR061-S01",
            )

    def test_c0_authorization_rejects_unknown_field(self) -> None:
        plan = self._ready_c0_result()
        payload = {
            **self._c0_authorization(plan).__dict__,
            "mutation_allowlist": list(plan.mutation_allowlist),
            "unknown": True,
        }

        with self.assertRaisesRegex(ValueError, "fields mismatch"):
            route_plan.C0AuthorizationV1.from_dict(payload)

    def test_c0_v1_python_apply_is_disabled_before_any_dry_run_or_io(self) -> None:
        with patch.object(
            route_plan,
            "build_c0_dry_run",
            side_effect=AssertionError("V1 apply must not build a semantic plan"),
        ) as builder:
            result = route_plan.apply_c0_cutover(
                project_root=Path("/must-not-be-read"),
                cr_id="CR-061",
                work_id="GOV-006-KERNEL-001",
                story_result_refs=["S01", "S02", "S03"],
                expected_plan_digest="ignored",
                authorization=None,
            )

        builder.assert_not_called()
        self.assertEqual("BLOCKED", result["status"])
        self.assertEqual("C0_V1_MUTATION_DISABLED", result["reason"])
        self.assertEqual("route-c0-cutover-apply", result["replacement_operation"])
        self.assertEqual(0, result["mutation_count"])

    def test_c0_v1_cli_apply_is_disabled_before_authorization_parsing_or_io(self) -> None:
        output = StringIO()
        with (
            patch.object(
                route_plan,
                "build_c0_dry_run",
                side_effect=AssertionError("V1 CLI apply must not build a semantic plan"),
            ) as builder,
            redirect_stdout(output),
        ):
            exit_code = route_plan.main(
                [
                    "c0-apply",
                    "--project-root",
                    "/must-not-be-read",
                    "--cr-id",
                    "CR-061",
                    "--authorization-json",
                    "{not-json",
                    "--apply",
                ]
            )

        builder.assert_not_called()
        self.assertEqual(2, exit_code)
        self.assertEqual(
            {
                "status": "BLOCKED",
                "decision": "BLOCKED",
                "reason": "C0_V1_MUTATION_DISABLED",
                "replacement_operation": "route-c0-cutover-apply",
                "mutation_count": 0,
            },
            json.loads(output.getvalue()),
        )

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
                    ["plan", "--from-cr", str(cr_path), "--output", str(artifact), "--project-root", str(root)]
                )

            self.assertEqual(0, exit_code)
            self.assertTrue(artifact.is_file())
            payload = json.loads(artifact.read_text(encoding="utf-8"))
            self.assertEqual(["CP0", "CP2", "CP8"], checkpoints(payload))
            self.assertEqual("N/A", payload["checkpoint_applicability"]["CP6"]["decision"])
            self.assertIn("wrote:", output.getvalue())

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
