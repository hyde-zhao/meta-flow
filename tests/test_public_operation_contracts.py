from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from meta_flow.policies import public_operations
from meta_flow.project.onboarding_contract import canonical_digest
from meta_flow.work.io_metrics import IOMetrics
from meta_flow.work.read_context import OperationReadContext

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONSOLE = Path(sys.executable).with_name("meta-flow")


def test_public_operation_registry_reuses_release_snapshot() -> None:
    metrics = IOMetrics("public-registry", enabled=True)
    context = OperationReadContext(
        PROJECT_ROOT,
        operation_id="public-registry",
        operation_kind="check",
        allowed_reads=(public_operations.DEFAULT_REGISTRY_REL.as_posix(),),
        logical_root="release-repository",
        metrics=metrics,
    )

    first = public_operations.load_public_operation_registry(
        PROJECT_ROOT,
        read_context=context,
    )
    second = public_operations.load_public_operation_registry(
        PROJECT_ROOT,
        read_context=context,
    )

    assert first == second
    assert metrics.summary()["totals"]["physical_reads"] == 1
    assert metrics.summary()["totals"]["cache_hits"] == 1


def write_cp6_projection_fixture(root: Path) -> None:
    process = root / "process"
    plan = {
        "story_management_truth_source": "process/DEVELOPMENT-PLAN.yaml",
        "waves": [
            {
                "wave_id": "W1",
                "stories": [
                    {
                        "story_id": "STORY-CR999-S01",
                        "title": "Projection",
                        "wave": "W1",
                        "status": "dev-ready",
                        "depends_on": [],
                        "dev_gate": {
                            "cp5_confirmed": True,
                            "dependencies_satisfied": True,
                            "file_conflict_free": True,
                            "implementation_authorized": True,
                            "lld_confirmed": True,
                        },
                    }
                ],
            }
        ],
    }
    (process / "DEVELOPMENT-PLAN.yaml").parent.mkdir(parents=True)
    (process / "DEVELOPMENT-PLAN.yaml").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    result = {
        "schema_version": 1,
        "checkpoint": "CP6",
        "checkpoint_id": "CP6-STORY-CR999-S01",
        "profile": "standard-code",
        "story_id": "STORY-CR999-S01",
        "cr_id": "CR-999",
        "context_ref": "process/context/STORY-CR999-S01.json",
        "dispatch_refs": ["DISPATCH-CR999-S01"],
        "evidence_ref": "process/evidence/STORY-CR999-S01.json",
        "items": [
            {
                "id": "CP6-01",
                "name": "implementation",
                "status": "PASS",
                "severity": "BLOCKER",
                "evidence_refs": ["process/evidence/STORY-CR999-S01.json"],
            }
        ],
        "blockers": [],
        "waivers": [],
        "decision": "PASS",
        "event_id": "CP6-STORY-CR999-S01-RESULT-V1",
    }
    result_path = process / "checks" / "CP6-STORY-CR999-S01.result.json"
    result_path.parent.mkdir(parents=True)
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    checkpoint = process / "state" / "CHECKPOINT-LEDGER.ndjson"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text(
        json.dumps(
            {
                "event_id": result["event_id"],
                "event_type": "checkpoint_result",
                "checkpoint": "CP6",
                "decision": "PASS",
                "result_ref": "process/checks/CP6-STORY-CR999-S01.result.json",
                "story_id": "STORY-CR999-S01",
                "cr_id": "CR-999",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


class PublicOperationContractTests(unittest.TestCase):
    def test_registry_matches_inventory_and_all_six_l3_journeys(self) -> None:
        result = public_operations.validate_public_operations(
            PROJECT_ROOT,
            check_console=True,
        )

        self.assertEqual("PASS", result["decision"], result["errors"])
        self.assertEqual(15, result["documented_operation_count"])
        self.assertEqual([], result["undocumented_public_operations"])
        self.assertEqual([], result["unknown_registry_operations"])
        self.assertEqual(6, result["l3_journey_count"])
        self.assertTrue(all(item["discovered"] for item in result["console_results"]))

    def test_registry_unknown_field_missing_operation_and_path_drift_fail_closed(
        self,
    ) -> None:
        source = json.loads(
            (PROJECT_ROOT / public_operations.DEFAULT_REGISTRY_REL).read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry = root / public_operations.DEFAULT_REGISTRY_REL
            registry.parent.mkdir(parents=True)
            unknown = json.loads(json.dumps(source))
            unknown["operations"][0]["unknown"] = True
            registry.write_text(
                json.dumps(unknown, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            invalid_shape = public_operations.validate_public_operations(
                root,
                check_console=False,
            )
            missing = json.loads(json.dumps(source))
            removed_operation = missing["operations"][0]["operation"]
            missing["operations"] = missing["operations"][1:]
            registry.write_text(
                json.dumps(missing, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            missing_operation = public_operations.validate_public_operations(
                root,
                check_console=False,
            )
            path_drift = json.loads(json.dumps(source))
            path_drift["operations"][-1]["path_contract"]["absolute_process_path_limit"] = 1
            registry.write_text(
                json.dumps(path_drift, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            invalid_path_contract = public_operations.validate_public_operations(
                root,
                check_console=False,
            )
            undiscoverable_argument = json.loads(json.dumps(source))
            undiscoverable_argument["operations"][-1]["path_contract"][
                "logical_process_arguments"
            ].append("--not-a-public-argument")
            registry.write_text(
                json.dumps(
                    undiscoverable_argument,
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            invalid_argument_contract = public_operations.validate_public_operations(
                root,
                check_console=True,
            )

        self.assertEqual("FAIL", invalid_shape["decision"])
        self.assertIn("extra=['unknown']", invalid_shape["errors"][0])
        self.assertEqual("FAIL", missing_operation["decision"])
        self.assertEqual(
            [removed_operation],
            missing_operation["undocumented_public_operations"],
        )
        self.assertEqual("FAIL", invalid_path_contract["decision"])
        self.assertIn(
            "absolute_process_path_limit must be 0",
            invalid_path_contract["errors"][0],
        )
        self.assertEqual("FAIL", invalid_argument_contract["decision"])
        self.assertIn(
            "human-gate.check public entry does not expose declared logical "
            "process argument --not-a-public-argument",
            invalid_argument_contract["errors"],
        )

    def test_four_real_console_l3_journeys_and_failure_injections(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            bad_event = root / "bad-event.json"
            bad_event.write_text(
                json.dumps(
                    {
                        "event_id": "E-BAD",
                        "event_type": "subgate_passed",
                        "status": "passed",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            gate_ledger = root / "process" / "state" / "GATE-LEDGER.ndjson"
            event_result = subprocess.run(
                [
                    str(CONSOLE),
                    "event",
                    "append",
                    "--project-root",
                    str(root),
                    "--ledger",
                    "process/state/GATE-LEDGER.ndjson",
                    "--event-file",
                    str(bad_event),
                ],
                cwd=PROJECT_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(0, event_result.returncode)
            self.assertFalse(gate_ledger.exists())

            read_ledger = root / "process" / "state" / "READ-EXPANSION-LEDGER.ndjson"
            context_result = subprocess.run(
                [
                    str(CONSOLE),
                    "context",
                    "read-log",
                    "--project-root",
                    str(root),
                    "--path",
                    "process/STATE.md",
                    "--reason",
                    "not-a-policy-enum",
                    "--stage",
                    "CP6",
                    "--agent",
                    "meta-dev",
                    "--context-ref",
                    "process/context/fixture.json",
                ],
                cwd=PROJECT_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(2, context_result.returncode)
            self.assertIn("mutation_count: 0", context_result.stdout)
            self.assertFalse(read_ledger.exists())

            write_cp6_projection_fixture(root)
            plan_before = (root / "process" / "DEVELOPMENT-PLAN.yaml").read_bytes()
            story_result = subprocess.run(
                [
                    str(CONSOLE),
                    "story",
                    "project-cp6",
                    "--project-root",
                    str(root),
                    "--result",
                    "process/checks/CP6-STORY-CR999-S01.result.json",
                ],
                cwd=PROJECT_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            story_plan = json.loads(story_result.stdout)
            self.assertEqual(0, story_result.returncode, story_result.stderr)
            self.assertEqual("READY", story_plan["decision"])
            self.assertEqual(1, story_plan["mutation_count"])
            self.assertEqual(
                plan_before,
                (root / "process" / "DEVELOPMENT-PLAN.yaml").read_bytes(),
            )

            cr_result = subprocess.run(
                [
                    str(CONSOLE),
                    "cr",
                    "conflicts",
                    "--proposed",
                    "--id",
                    "CR-998",
                    "--conflict-key",
                    canonical_digest({"fixture": "public-operation"}),
                    "--project-root",
                    str(root),
                ],
                cwd=PROJECT_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            cr_preview = json.loads(cr_result.stdout)
            self.assertEqual(0, cr_result.returncode, cr_result.stderr)
            self.assertEqual("NO_CONFLICT", cr_preview["decision"])
            self.assertEqual(0, cr_preview["mutation_count"])
            self.assertFalse((root / "process" / "changes" / "CR-998.md").exists())

            cr_path = root / "process" / "changes" / "CR-997.md"
            cr_path.parent.mkdir(parents=True, exist_ok=True)
            cr_path.write_text(
                """---
schema_version: 1
kind: cr
cr_id: "CR-997"
cr_type: "process"
title: "public close dry-run"
lifecycle_status: "active"
readiness_status: "NOT_READY"
gate_status: "cp8_pending"
---

## 变更描述

验证公共 close/status-sync 均为零写 dry-run。
""",
                encoding="utf-8",
            )
            cr_before = cr_path.read_bytes()
            close_result = subprocess.run(
                [
                    str(CONSOLE),
                    "cr",
                    "close",
                    "--id",
                    "CR-997",
                    "--readiness",
                    "READY_WITH_RISK",
                    "--effective-at",
                    "2026-07-27T00:00:00+00:00",
                    "--project-root",
                    str(root),
                ],
                cwd=PROJECT_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            close_plan = json.loads(close_result.stdout)
            status_sync_result = subprocess.run(
                [
                    str(CONSOLE),
                    "cr",
                    "status-sync",
                    "--id",
                    "CR-997",
                    "--status",
                    "closed",
                    "--readiness",
                    "READY_WITH_RISK",
                    "--gate-status",
                    "cp8_closed",
                    "--effective-at",
                    "2026-07-27T00:00:00+00:00",
                    "--project-root",
                    str(root),
                ],
                cwd=PROJECT_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            status_sync_plan = json.loads(status_sync_result.stdout)
            self.assertEqual(0, close_result.returncode, close_result.stderr)
            self.assertEqual(
                0,
                status_sync_result.returncode,
                status_sync_result.stderr,
            )
            self.assertEqual(close_plan, status_sync_plan)
            self.assertEqual(0, close_plan["mutation_count"])
            self.assertEqual(cr_before, cr_path.read_bytes())

            registry_result = subprocess.run(
                [
                    str(CONSOLE),
                    "cr",
                    "public-operations-check",
                    "--project-root",
                    str(PROJECT_ROOT),
                ],
                cwd=PROJECT_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            registry_check = json.loads(registry_result.stdout)
            self.assertEqual(0, registry_result.returncode, registry_result.stderr)
            self.assertEqual("PASS", registry_check["decision"])


if __name__ == "__main__":
    unittest.main()
