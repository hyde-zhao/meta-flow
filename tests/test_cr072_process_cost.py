from __future__ import annotations

import dataclasses
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from meta_flow import cli, package_cli
from meta_flow.checks.process_cost import (
    ProcessCostInputV1,
    SourceEvidenceV1,
    build_process_cost_report,
)


def policy() -> dict[str, object]:
    return {
        "schema_version": 1,
        "release_package_profiles": {
            "CR-072": {
                "formal_cr": {"exact": 1},
                "implementation_work": {"exact": 2},
                "process_story": {"min": 6, "max": 8},
                "context_capsule": {
                    "max": 5,
                    "max_per_stage": 1,
                    "included_stages": ["CP2", "CP3", "CP5", "CP7", "CP8"],
                    "identity": "one-per-CP2-CP3-CP5-CP7-CP8",
                },
                "canonical_work_handoff_return_group": {"max_per_work": 1},
                "process_to_product_artifact_ratio": {"soft_max": 2.0},
            }
        },
    }


def cost_input(**overrides: object) -> ProcessCostInputV1:
    base = ProcessCostInputV1(
        cr_id="CR-072",
        package_id="CR-072-0.6.1-release-package",
        work_ids=("CR-072-WA-STABILIZATION-001", "CR-072-WB-GOVERNANCE-001"),
        story_ids=tuple(f"STORY-CR072-S0{index}" for index in range(1, 7)),
        feature_refs=("feature-a", "feature-b", "feature-c", "feature-d"),
        lld_refs=tuple(f"process/stories/S0{index}-LLD.md" for index in range(1, 7)),
        context_refs=("process/context/CP2.yaml", "process/context/CP3.yaml", "process/context/CP5.yaml"),
        checkpoint_refs=("process/checkpoints/CP2.md", "process/checkpoints/CP3.md", "process/checkpoints/CP5.md"),
        result_refs=("process/checks/CP2.json", "process/checks/CP3.json", "process/checks/CP5.json"),
        result_reference_count=6,
        handoff_count=1,
        return_count=1,
        phase_handoff_count=0,
        phase_return_count=0,
        reads=12,
        writes=4,
        check_groups=3,
        token_count=2400,
        token_measurement_status="measured",
        token_unavailable_reason="",
        expanded_reads=2,
        actual_mutations=3,
        semantic_noops=1,
        source_bytes=4096,
        changed_release_paths=4,
        changed_process_paths=3,
        validation_layer_executions=(("compatibility", 1), ("targeted", 2)),
        retry_count=0,
        rework_count=0,
        harness_errors=(),
        release_action_attempts=(("build", 0), ("canary", 0), ("cp8", 0), ("qualification", 0), ("release", 0)),
        intermediate_release_count=0,
        breaking_change_count=0,
        process_artifact_count=8,
        product_artifact_count=8,
        source_evidence=(SourceEvidenceV1("process/DEVELOPMENT-PLAN.yaml", "a" * 64),),
        telemetry_complete=True,
    )
    return dataclasses.replace(base, **overrides)


class ProcessCostReportTests(unittest.TestCase):
    def test_report_has_six_machine_derived_groups_and_stable_digest(self) -> None:
        value = cost_input()

        first = build_process_cost_report(value, policy())
        second = build_process_cost_report(value, policy())

        self.assertEqual(first, second)
        self.assertEqual("PASS", first["decision"])
        for field in ("counts", "io", "validation", "usage", "release", "ratios"):
            self.assertIn(field, first)
        self.assertEqual(6, first["counts"]["story"])
        self.assertEqual(0, first["io"]["written_bytes"] or 0)
        self.assertEqual(64, len(first["report_digest"]))

    def test_unavailable_tokens_remain_null_and_are_not_zero(self) -> None:
        report = build_process_cost_report(
            cost_input(
                token_count=None,
                token_measurement_status="unavailable",
                token_unavailable_reason="provider did not expose usage",
                telemetry_complete=False,
            ),
            policy(),
        )

        self.assertIsNone(report["usage"]["tokens"])
        self.assertEqual("unavailable", report["usage"]["token_measurement_status"])
        self.assertIn("TOKEN_TELEMETRY_UNAVAILABLE", report["soft_risks"])
        self.assertEqual("PASS_WITH_RISK", report["decision"])

    def test_structural_budget_breach_is_blocked(self) -> None:
        report = build_process_cost_report(
            cost_input(story_ids=("ONLY-ONE",)), policy()
        )

        self.assertEqual("BLOCKED", report["decision"])
        self.assertTrue(
            any(item.startswith("process_story:min=6") for item in report["hard_findings"])
        )

    def test_context_budget_counts_only_declared_phase_capsules(self) -> None:
        report = build_process_cost_report(
            cost_input(
                context_refs=(
                    "process/context/CP0-CR072.context.json",
                    "process/context/CP2.yaml",
                    "process/context/CP3.yaml",
                    "process/context/CP5.yaml",
                    "process/context/stories/STORY-CR072-S01.CP6.work-packet.json",
                    "process/context/stories/STORY-CR072-S02.CP6.work-packet.json",
                    "process/context/stories/STORY-CR072-S03.CP6.work-packet.json",
                    "process/context/stories/STORY-CR072-S04.CP6.work-packet.json",
                    "process/context/stories/STORY-CR072-S05.CP6.work-packet.json",
                    "process/context/stories/STORY-CR072-S06.CP6.work-packet.json",
                )
            ),
            policy(),
        )

        self.assertEqual("PASS", report["decision"])
        self.assertEqual(10, report["counts"]["context"])
        self.assertEqual(3, report["counts"]["budgeted_context_capsule"])

    def test_duplicate_phase_capsule_is_hard_blocked(self) -> None:
        report = build_process_cost_report(
            cost_input(
                context_refs=(
                    "process/context/CP2-A.yaml",
                    "process/context/CP2-B.yaml",
                    "process/context/CP3.yaml",
                    "process/context/CP5.yaml",
                )
            ),
            policy(),
        )

        self.assertEqual("BLOCKED", report["decision"])
        self.assertIn(
            "context_capsule:CP2:max=1:actual=2",
            report["hard_findings"],
        )

    def test_ratio_over_two_is_soft_risk_only(self) -> None:
        report = build_process_cost_report(
            cost_input(process_artifact_count=21, product_artifact_count=10), policy()
        )

        self.assertEqual("PASS_WITH_RISK", report["decision"])
        self.assertEqual([], report["hard_findings"])
        self.assertTrue(report["soft_risks"][0].startswith("PROCESS_PRODUCT_RATIO_HIGH"))

    def test_harness_error_and_second_qualification_are_hard(self) -> None:
        attempts = dict(cost_input().release_action_attempts)
        attempts["qualification"] = 2
        report = build_process_cost_report(
            cost_input(
                harness_errors=("CHECK-H-001",),
                release_action_attempts=tuple(sorted(attempts.items())),
            ),
            policy(),
        )

        self.assertEqual("BLOCKED", report["decision"])
        self.assertIn("qualification_attempt_count:>1", report["hard_findings"])
        self.assertIn("unresolved_harness_errors:CHECK-H-001", report["hard_findings"])

    def test_hard_mode_requires_three_complete_terminal_packages_and_approval(self) -> None:
        uncalibrated = build_process_cost_report(cost_input(terminal_cohort_size=2), policy())
        candidate = build_process_cost_report(
            cost_input(terminal_cohort_size=3, hard_mode_approval_ref="process/decisions/COST-HARD.json"),
            policy(),
        )

        self.assertFalse(uncalibrated["mode"]["hard_mode_eligible"])
        self.assertEqual("MODE_NOT_CALIBRATED", uncalibrated["mode"]["hard_mode_reason"])
        self.assertTrue(candidate["mode"]["hard_mode_eligible"])

    def test_cost_report_cli_is_zero_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "user-owned.txt"
            marker.write_text("unchanged\n", encoding="utf-8")
            before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
            output = StringIO()
            with (
                patch.object(package_cli, "collect_process_cost_input", return_value=cost_input()),
                patch.object(package_cli, "load_process_cost_policy", return_value=policy()),
                redirect_stdout(output),
            ):
                result = package_cli.main(
                    ["cost-report", "--cr", "CR-072", "--project-root", str(root), "--format", "json"]
                )
            after = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}

            self.assertEqual(0, result)
            self.assertEqual(before, after)
            self.assertEqual("ProcessCostReportV1", json.loads(output.getvalue())["kind"])

    def test_root_cli_reaches_package_adapter_and_cost_core(self) -> None:
        output = StringIO()
        with (
            patch.object(sys, "argv", ["meta-flow", "package", "cost-report", "--cr", "CR-072"]),
            patch.object(cli, "_guard_provider_mutation"),
            patch.object(package_cli, "collect_process_cost_input", return_value=cost_input()),
            patch.object(package_cli, "load_process_cost_policy", return_value=policy()),
            redirect_stdout(output),
        ):
            with self.assertRaises(SystemExit) as raised:
                cli._dispatch_main()

        self.assertEqual(0, raised.exception.code)
        self.assertEqual("ProcessCostReportV1", json.loads(output.getvalue())["kind"])


if __name__ == "__main__":
    unittest.main()
