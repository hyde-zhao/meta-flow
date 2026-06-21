from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from meta_flow.context_pack import story_contract
from meta_flow.state import current
from meta_flow.workflow import story_evidence


def write_minimal_state(root: Path) -> None:
    state = current.default_current_state(root)
    state["project_id"] = "fixture-project"
    current.write_current_state(root, state)


def write_cr_summary(root: Path, cr_id: str = "CR-123") -> None:
    path = root / "process" / "changes" / "summaries" / f"{cr_id}.summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"id": cr_id, "status": "active"}) + "\n", encoding="utf-8")


def write_story(root: Path) -> Path:
    path = root / "process" / "stories" / "STORY-CR123-S01.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """---
story_id: STORY-CR123-S01
cr_id: CR-123
title: Migrate manifest owner
feature_refs:
  - data.manifest
feature_design_refs:
  - docs/features/data-manifest/DESIGN.md
lld_policy: technical-note
risk_profile: standard-code
allowed_write_paths:
  - quant_lab/data/manifest/**
  - tests/data/manifest/**
forbidden_write_paths:
  - quant_lab/trading/**
acceptance:
  - legacy manifest can load
verification_plan:
  - pytest tests/data/manifest
authz_policy_refs:
  - NO_CREDENTIAL_READ
---

# Story
""",
        encoding="utf-8",
    )
    return path


def write_feature_doc(root: Path) -> None:
    path = root / "docs" / "features" / "data-manifest" / "DESIGN.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Data Manifest Design\n", encoding="utf-8")


def write_return_packet(root: Path, *, touched_path: str = "quant_lab/data/manifest/reader.py") -> Path:
    path = root / "process" / "returns" / "STORY-CR123-S01.CP6.return.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    packet = {
        "schema_version": 1,
        "packet_type": "story_return_packet",
        "stage": "CP6",
        "cr_id": "CR-123",
        "story_id": "STORY-CR123-S01",
        "status": "implemented",
        "touched_files": [{"path": touched_path, "change_type": "modified"}],
        "contract_changes": {
            "public_api_changed": False,
            "data_contract_changed": False,
            "design_delta_required": False,
            "design_delta_ref": None,
        },
        "boundary_check": {
            "allowed_paths_only": True,
            "forbidden_paths_touched": [],
            "unexpected_imports": [],
        },
        "verification": {
            "commands_run": [{"command": "pytest tests/data/manifest", "result": "pass"}],
            "tests": [],
            "skipped": [],
        },
        "open_questions": [],
        "risks": [],
        "waivers": [],
        "next_stage_recommendation": "ready_for_cp7",
    }
    path.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


class StoryEvidenceTests(unittest.TestCase):
    def test_return_check_passes_for_valid_cp6_return(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_story(root)
            _packet, work_packet = story_contract.build_story_packet(root, story_path=story, stage="CP6", budget=8000)
            return_path = write_return_packet(root)

            stream = StringIO()
            with redirect_stdout(stream):
                exit_code = story_evidence.main(
                    [
                        "return-check",
                        "--packet",
                        str(work_packet),
                        "--return",
                        str(return_path),
                        "--project-root",
                        str(root),
                    ]
                )

            self.assertEqual(0, exit_code)
            self.assertIn("Story Return Packet Check: OK", stream.getvalue())

    def test_return_check_rejects_touched_file_outside_allowed_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_story(root)
            _packet, work_packet = story_contract.build_story_packet(root, story_path=story, stage="CP6", budget=8000)
            return_path = write_return_packet(root, touched_path="quant_lab/research/scanner.py")

            errors, _warnings = story_evidence.validate_return_packet(return_path, packet_path=work_packet, project_root=root)

            self.assertIn("touched file outside allowed_write_paths: quant_lab/research/scanner.py", errors)

    def test_return_check_rejects_forbidden_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_story(root)
            _packet, work_packet = story_contract.build_story_packet(root, story_path=story, stage="CP6", budget=8000)
            return_path = write_return_packet(root, touched_path="quant_lab/trading/order.py")

            errors, _warnings = story_evidence.validate_return_packet(return_path, packet_path=work_packet, project_root=root)

            self.assertIn("touched file outside allowed_write_paths: quant_lab/trading/order.py", errors)
            self.assertIn("touched file matches forbidden_write_paths: quant_lab/trading/order.py", errors)

    def test_return_check_requires_design_delta_ref_when_needed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_story(root)
            _packet, work_packet = story_contract.build_story_packet(root, story_path=story, stage="CP6", budget=8000)
            return_path = write_return_packet(root)
            packet = json.loads(return_path.read_text(encoding="utf-8"))
            packet["contract_changes"]["design_delta_required"] = True
            packet["contract_changes"]["design_delta_ref"] = ""
            return_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            errors, _warnings = story_evidence.validate_return_packet(return_path, packet_path=work_packet, project_root=root)

            self.assertIn("contract_changes.design_delta_ref is required when design_delta_required=true", errors)

    def test_return_check_accepts_partial_status_without_touched_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_story(root)
            _packet, work_packet = story_contract.build_story_packet(root, story_path=story, stage="CP6", budget=8000)
            return_path = write_return_packet(root)
            packet = json.loads(return_path.read_text(encoding="utf-8"))
            packet["status"] = "partial"
            packet["touched_files"] = []
            packet["verification"]["commands_run"] = []
            return_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            errors, _warnings = story_evidence.validate_return_packet(return_path, packet_path=work_packet, project_root=root)

            self.assertEqual([], errors)

    def test_evidence_index_build_and_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            return_path = write_return_packet(root)

            evidence, output = story_evidence.build_evidence_index(root, return_path=return_path)
            errors, warnings = story_evidence.validate_evidence_index(output, project_root=root)

            self.assertEqual("STORY-CR123-S01", evidence["story_id"])
            self.assertTrue(output.is_file())
            self.assertEqual([], errors)
            self.assertEqual([], warnings)

    def test_design_delta_check_warns_pending_and_can_require_merged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_feature_doc(root)
            delta = root / "process" / "design-deltas" / "STORY-CR123-S01.delta.json"
            delta.parent.mkdir(parents=True, exist_ok=True)
            delta.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "story_id": "STORY-CR123-S01",
                        "feature_id": "data.manifest",
                        "delta_type": "patch",
                        "target_doc": "docs/features/data-manifest/DESIGN.md",
                        "changes": [
                            {
                                "section": "Schema Versioning",
                                "operation": "add",
                                "summary": "Add legacy schema_version compatibility.",
                            }
                        ],
                        "requires_feature_doc_update": True,
                        "status": "pending",
                        "merged_ref": None,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            errors, warnings = story_evidence.validate_design_delta(delta, project_root=root)
            merged_errors, _merged_warnings = story_evidence.validate_design_delta(delta, project_root=root, require_merged=True)

            self.assertEqual([], errors)
            self.assertIn("design delta requires feature doc update but is not merged", warnings)
            self.assertIn("design delta status must be merged", merged_errors)

    def test_verify_packet_builds_from_cp6_return(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_story(root)
            return_path = write_return_packet(root)

            packet, output = story_evidence.build_verify_packet_from_return(root, return_path=return_path, story_path=story)

            self.assertEqual("story_verify_packet", packet["packet_type"])
            self.assertEqual("process/returns/STORY-CR123-S01.CP6.return.json", packet["implementation_return_ref"])
            self.assertTrue(output.name.endswith(".CP7.verify-packet.json"))


if __name__ == "__main__":
    unittest.main()
