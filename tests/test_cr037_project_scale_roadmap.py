from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from meta_flow import cli
from meta_flow.project import roadmap, scale
from meta_flow.project import state as project_state


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_yaml(path: Path, payload: dict) -> None:
    scale.write_yaml_file(path, payload)


def valid_scale(project_id: str = "demo-project") -> dict:
    return {
        "schema_version": 1,
        "project_id": project_id,
        "scale_level": "standard",
        "scale_reason": ["cross-module project governance change"],
        "gate_profile_bias": {
            "mode": "recommendation",
            "default_profile": "standard-code",
            "reason": "project governance checker work",
            "applies_to": ["CP5", "CP8"],
        },
        "review_cadence_bias": {
            "mode": "recommendation",
            "cadence": "per-story CP6/CP7",
            "reason": "shared governance objects",
        },
        "not_authorized": [
            "skip_human_gate",
            "modify_gate_profiles",
            "runtime_authorization",
            "publish_authorization",
        ],
        "source_refs": [],
        "updated_at": "2026-07-03T00:00:00+00:00",
    }


def valid_roadmap(project_id: str = "demo-project") -> dict:
    return {
        "schema_version": 1,
        "roadmap_id": "RM-DEMO",
        "project_id": project_id,
        "horizon": "2026-Q3",
        "items": [
            {
                "id": "RM-001",
                "title": "Project governance baseline",
                "status": "active",
                "milestone_refs": ["MS-001"],
                "source_refs": [],
            }
        ],
        "source_refs": [],
    }


def valid_milestones(project_id: str = "demo-project") -> dict:
    return {
        "schema_version": 1,
        "project_id": project_id,
        "milestones": [
            {
                "milestone_id": "MS-001",
                "title": "Governance baseline verified",
                "target_window": "2026-Q3",
                "status": "active",
                "roadmap_item_refs": ["RM-001"],
                "source_refs": [],
            }
        ],
        "source_refs": [],
    }


def write_project_objects(root: Path, *, project_id: str = "demo-project") -> None:
    write_json(
        root / project_state.PROJECT_CURRENT_REL,
        {
            "schema_version": 1,
            "project_id": project_id,
            "project_name": project_id,
            "scale_ref": "process/project/PROJECT-SCALE.yaml",
            "roadmap_ref": "process/project/ROADMAP.yaml",
            "milestones_ref": "process/project/MILESTONES.yaml",
            "active_governance_refs": [],
            "source_refs": [],
            "updated_at": "2026-07-03T00:00:00+00:00",
        },
    )
    write_yaml(root / scale.PROJECT_SCALE_REL, valid_scale(project_id))
    write_yaml(root / roadmap.ROADMAP_REL, valid_roadmap(project_id))
    write_yaml(root / roadmap.MILESTONES_REL, valid_milestones(project_id))


class ProjectScaleRoadmapTests(unittest.TestCase):
    def test_project_scale_accepts_legal_scale_and_gate_bias_recommendation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_yaml(root / scale.PROJECT_SCALE_REL, valid_scale())

            snapshot, findings = scale.validate_project_scale(root)

            self.assertEqual([], [finding.message for finding in findings if finding.severity == "ERROR"])
            self.assertIsNotNone(snapshot)
            self.assertEqual("standard", snapshot.scale_level)
            self.assertEqual("standard-code", snapshot.gate_profile_bias["default_profile"])
            self.assertIn("runtime_authorization", snapshot.not_authorized)

    def test_project_scale_rejects_authorization_semantics(self) -> None:
        unsafe_cases = [
            {"auto_approve": True},
            {"gate_profile_bias": {"mode": "recommendation", "default_profile": "standard-code", "reason": "ok", "skip_gate": True}},
            {"review_cadence_bias": {"mode": "recommendation", "cadence": "skip_gate"}},
            {"gate_policy_mutation": {"target": "process/policies/GATE-PROFILES.json"}},
        ]
        for extra in unsafe_cases:
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                payload = valid_scale()
                for key, value in extra.items():
                    if isinstance(value, dict) and isinstance(payload.get(key), dict):
                        payload[key].update(value)
                    else:
                        payload[key] = value
                write_yaml(root / scale.PROJECT_SCALE_REL, payload)

                _snapshot, findings = scale.validate_project_scale(root)

                self.assertIn("forbidden authorization", "\n".join(finding.message for finding in findings))

    def test_project_scale_rejects_unknown_gate_profile_bias(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = valid_scale()
            payload["gate_profile_bias"]["default_profile"] = "unknown-profile"
            write_yaml(root / scale.PROJECT_SCALE_REL, payload)

            _snapshot, findings = scale.validate_project_scale(root)

            self.assertIn("not a known gate profile", "\n".join(finding.message for finding in findings))

    def test_roadmap_and_milestone_schema_reject_duplicate_ids_and_invalid_status(self) -> None:
        duplicate_roadmap = valid_roadmap()
        duplicate_roadmap["items"].append(dict(duplicate_roadmap["items"][0]))
        invalid_milestones = valid_milestones()
        invalid_milestones["milestones"].append(
            {
                "milestone_id": "MS-002",
                "title": "Invalid status",
                "status": "started",
                "roadmap_item_refs": [],
            }
        )

        _roadmap_snapshot, roadmap_findings = roadmap.validate_roadmap_payload(duplicate_roadmap)
        _milestones_snapshot, milestone_findings = roadmap.validate_milestones_payload(invalid_milestones)

        self.assertIn("duplicate roadmap item id", "\n".join(finding.message for finding in roadmap_findings))
        self.assertIn("status must be one of", "\n".join(finding.message for finding in milestone_findings))

    def test_roadmap_milestone_cross_refs_reject_broken_and_mismatched_refs(self) -> None:
        roadmap_payload = valid_roadmap()
        milestones_payload = valid_milestones()
        milestones_payload["milestones"][0]["roadmap_item_refs"] = []

        roadmap_snapshot, roadmap_findings = roadmap.validate_roadmap_payload(roadmap_payload)
        milestones_snapshot, milestone_findings = roadmap.validate_milestones_payload(milestones_payload)
        cross_findings = roadmap.validate_roadmap_milestone_refs(roadmap_snapshot, milestones_snapshot)

        self.assertEqual([], [finding.message for finding in roadmap_findings + milestone_findings if finding.severity == "ERROR"])
        self.assertIn("does not reference the roadmap item", "\n".join(finding.message for finding in cross_findings))

        roadmap_payload["items"][0]["milestone_refs"] = ["MS-MISSING"]
        roadmap_snapshot, _roadmap_findings = roadmap.validate_roadmap_payload(roadmap_payload)
        broken_findings = roadmap.validate_roadmap_milestone_refs(roadmap_snapshot, milestones_snapshot)

        self.assertIn("references missing milestone", "\n".join(finding.message for finding in broken_findings))

    def test_load_project_snapshot_resolves_refs_and_blocks_broken_refs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_project_objects(root)

            snapshot, findings = project_state.load_project_snapshot(root)

            self.assertEqual([], [finding.message for finding in findings if finding.severity == "ERROR"])
            self.assertIsNotNone(snapshot)
            self.assertEqual("demo-project", snapshot.current["project_id"])
            self.assertEqual("standard", snapshot.scale.scale_level)
            self.assertEqual("RM-001", snapshot.roadmap.items[0].id)
            self.assertEqual("MS-001", snapshot.milestones.milestones[0].milestone_id)

            (root / roadmap.MILESTONES_REL).unlink()
            broken_snapshot, broken_findings = project_state.load_project_snapshot(root)

            self.assertIsNone(broken_snapshot)
            self.assertIn("milestones_ref points to missing file", "\n".join(finding.message for finding in broken_findings))

    def test_project_check_cli_validates_all_project_objects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_project_objects(root)

            output = StringIO()
            with redirect_stdout(output):
                with self.assertRaises(SystemExit) as raised:
                    cli._run_project(["check", "--project-root", str(root)])

            self.assertEqual(0, raised.exception.code)
            self.assertIn("Project Check: OK", output.getvalue())

            unsafe = valid_scale()
            unsafe["skip_gate"] = True
            write_yaml(root / scale.PROJECT_SCALE_REL, unsafe)
            failed_output = StringIO()
            with redirect_stdout(failed_output):
                with self.assertRaises(SystemExit) as failed:
                    cli._run_project(["check", "--project-root", str(root)])

            self.assertEqual(1, failed.exception.code)
            self.assertIn("Project Check: FAIL", failed_output.getvalue())
            self.assertIn("forbidden authorization", failed_output.getvalue())


if __name__ == "__main__":
    unittest.main()
