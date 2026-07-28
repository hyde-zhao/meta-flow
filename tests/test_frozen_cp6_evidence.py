from __future__ import annotations

import json
import unittest

from meta_flow.checks.frozen_cp6_evidence import (
    FrozenCp6EvidenceError,
    compare_frozen_evidence,
    freeze_cp6_evidence,
    project_story_admission,
    project_story_admissions,
)


def evidence(*, dependency_digest: str = "a" * 64) -> dict[str, object]:
    return {
        "schema_version": 1,
        "story_id": "STORY-CR061-S02",
        "release_oid": "1" * 40,
        "process_oid": "2" * 40,
        "scope_digest": "3" * 64,
        "implementation_digest": "4" * 64,
        "dependency_digests": {"STORY-CR061-S01:contract": dependency_digest},
        "cp6_result_ref": "process/checks/CP6-STORY-CR061-S02.result.json",
    }


class FrozenCp6EvidenceTests(unittest.TestCase):
    def test_c10_valid_v1_freezes_and_unknown_schema_blocks(self) -> None:
        frozen = freeze_cp6_evidence(**evidence())
        self.assertEqual(1, frozen.schema_version)
        payload = evidence()
        payload["schema_version"] = 2
        with self.assertRaises(FrozenCp6EvidenceError):
            freeze_cp6_evidence(**payload)

    def test_c11_unchanged_dependency_only_reconfirms(self) -> None:
        result = compare_frozen_evidence(evidence(), evidence())
        self.assertEqual("reconfirmed", result["decision"])
        self.assertEqual([], result["changed_dependencies"])

    def test_c12_changed_dependency_requires_downstream_revalidation(self) -> None:
        result = compare_frozen_evidence(evidence(), evidence(dependency_digest="b" * 64))
        self.assertEqual("revalidation-required", result["decision"])
        self.assertEqual(["STORY-CR061-S01:contract"], result["changed_dependencies"])

    def test_c13_virtual_bootstrap_never_forces_ready(self) -> None:
        result = project_story_admission(None, expected_dependency_digests={}, bootstrap={"force_ready": True})
        self.assertEqual("BLOCKED", result["decision"])
        self.assertIn("FROZEN_CP6_EVIDENCE_MISSING", result["reason_codes"])

    def test_native_development_plan_gate_is_the_only_first_admission_ready_path(self) -> None:
        projected_gate = {
            "story_id": "STORY-CR061-S04",
            "status": "dev-ready",
            "dev_gate": {
                "cp5_confirmed": True,
                "dependencies_satisfied": True,
                "file_conflict_free": True,
                "implementation_authorized": True,
                "lld_confirmed": True,
            },
        }
        result = project_story_admission(
            None,
            expected_dependency_digests={},
            projected_gate=projected_gate,
        )
        self.assertEqual("READY", result["decision"])
        self.assertEqual(["NATIVE_DEVELOPMENT_PLAN_GATE_READY"], result["reason_codes"])

    def test_native_development_plan_gate_blocks_unknown_shape_or_false_gate(self) -> None:
        projected_gate = {
            "story_id": "STORY-CR061-S04",
            "status": "dev-ready",
            "dev_gate": {
                "cp5_confirmed": True,
                "dependencies_satisfied": False,
                "file_conflict_free": True,
                "implementation_authorized": True,
                "lld_confirmed": True,
            },
        }
        blocked = project_story_admission(
            None,
            expected_dependency_digests={},
            projected_gate=projected_gate,
        )
        self.assertEqual("BLOCKED", blocked["decision"])
        invalid = project_story_admission(
            None,
            expected_dependency_digests={},
            projected_gate={**projected_gate, "unknown": True},
        )
        self.assertEqual(["NATIVE_PLAN_GATE_INVALID"], invalid["reason_codes"])

    def test_c14_single_and_batch_project_same_decision_bytes(self) -> None:
        expected = {"STORY-CR061-S01:contract": "a" * 64}
        single = project_story_admission(evidence(), expected_dependency_digests=expected)
        batch = project_story_admissions(
            {"STORY-CR061-S02": evidence()},
            expected_dependency_digests_by_story={"STORY-CR061-S02": expected},
        )["STORY-CR061-S02"]
        self.assertEqual(
            json.dumps(single, sort_keys=True, separators=(",", ":")).encode(),
            json.dumps(batch, sort_keys=True, separators=(",", ":")).encode(),
        )

    def test_c14_batch_projection_has_stable_story_id_order(self) -> None:
        projected = project_story_admissions(
            {"STORY-Z": None, "STORY-A": None},
            expected_dependency_digests_by_story={"STORY-Z": {}, "STORY-A": {}},
        )
        self.assertEqual(["STORY-A", "STORY-Z"], list(projected))
