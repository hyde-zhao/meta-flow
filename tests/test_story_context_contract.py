from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from meta_flow.context_pack import builder
from meta_flow.context_pack import story_contract
from meta_flow.state import current


def write_minimal_state(root: Path) -> None:
    state = current.default_current_state(root)
    state["project_id"] = "fixture-project"
    current.write_current_state(root, state)


def write_cr_summary(root: Path, cr_id: str = "CR-123") -> None:
    path = root / "process" / "changes" / "summaries" / f"{cr_id}.summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"id": cr_id, "status": "active"}) + "\n", encoding="utf-8")


def write_story(root: Path, *, lld_policy: str = "technical-note") -> Path:
    path = root / "process" / "stories" / "STORY-CR123-S01.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
story_id: STORY-CR123-S01
cr_id: CR-123
title: Migrate manifest owner
feature_refs:
  - data.manifest
feature_design_refs:
  - docs/features/data-manifest/DESIGN.md
lld_policy: {lld_policy}
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


class StoryContextContractTests(unittest.TestCase):
    def test_build_base_story_context_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_story(root)

            packet, output = story_contract.build_story_packet(root, story_path=story, stage="BASE", budget=8000)

            self.assertTrue(output.is_file())
            self.assertEqual("story_context_contract", packet["packet_type"])
            self.assertEqual("STORY-CR123-S01", packet["story_id"])
            self.assertIn("data.manifest", packet["feature_refs"])
            allowed = {entry["path"] for entry in packet["allowed_reads"]}
            self.assertIn("process/state/STATE.current.json", allowed)
            self.assertIn("process/stories/STORY-CR123-S01.md", allowed)
            self.assertIn("process/changes/summaries/CR-123.summary.json", allowed)

    def test_build_cp6_work_packet_has_parent_and_return_ref(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_story(root)

            packet, output = story_contract.build_story_packet(root, story_path=story, stage="CP6", budget=8000)

            self.assertTrue(output.name.endswith(".CP6.work-packet.json"))
            self.assertEqual("story_work_packet", packet["packet_type"])
            self.assertEqual("process/context/stories/STORY-CR123-S01.base.context.json", packet["parent_context_ref"])
            self.assertEqual("process/returns/STORY-CR123-S01.CP6.return.json", packet["expected_return_packet"])

    def test_build_cp7_verify_packet_has_implementation_return_ref(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_story(root)

            packet, _output = story_contract.build_story_packet(root, story_path=story, stage="CP7", budget=8000)

            self.assertEqual("story_verify_packet", packet["packet_type"])
            self.assertEqual("process/returns/STORY-CR123-S01.CP6.return.json", packet["implementation_return_ref"])
            self.assertEqual("process/returns/STORY-CR123-S01.CP7.return.json", packet["expected_return_packet"])

    def test_full_lld_story_puts_lld_in_read_if_needed_not_allowed_reads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_story(root, lld_policy="full-lld")

            packet, _output = story_contract.build_story_packet(root, story_path=story, stage="CP6", budget=8000)

            allowed = {entry["path"] for entry in packet["allowed_reads"]}
            read_if_needed = {entry["path"] for entry in packet["read_if_needed"]}
            self.assertNotIn("process/stories/STORY-CR123-S01-LLD.md", allowed)
            self.assertIn("process/stories/STORY-CR123-S01-LLD.md", read_if_needed)

    def test_check_passes_for_valid_packet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_story(root)
            _packet, output = story_contract.build_story_packet(root, story_path=story, stage="CP6", budget=8000)

            stream = StringIO()
            with redirect_stdout(stream):
                exit_code = story_contract.main(["check-story-packet", "--packet", str(output), "--project-root", str(root)])

            self.assertEqual(0, exit_code)
            self.assertIn("Story Context Packet Check: OK", stream.getvalue())

    def test_check_rejects_deny_default_allowed_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_story(root)
            packet, output = story_contract.build_story_packet(root, story_path=story, stage="CP6", budget=8000)
            packet["allowed_reads"].append(
                {
                    "path": "process/STATE.md",
                    "mode": "full",
                    "estimated_tokens": 1,
                    "required": False,
                    "reason": "legacy_state",
                }
            )
            output.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            errors, _warnings = story_contract.validate_story_packet(output, project_root=root)

            self.assertIn("allowed_reads contains deny-default path: process/STATE.md", errors)

    def test_check_rejects_missing_write_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_story(root)
            packet, output = story_contract.build_story_packet(root, story_path=story, stage="CP6", budget=8000)
            packet["allowed_write_paths"] = []
            output.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            errors, _warnings = story_contract.validate_story_packet(output, project_root=root)

            self.assertIn("allowed_write_paths must be non-empty", errors)

    def test_cli_build_story_packet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_story(root)

            output = StringIO()
            with redirect_stdout(output):
                exit_code = story_contract.main(
                    ["build-story-packet", "--story", str(story), "--stage", "CP6", "--project-root", str(root)]
                )

            self.assertEqual(0, exit_code)
            self.assertIn("wrote:", output.getvalue())

    def test_context_builder_dispatches_story_packet_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_story(root)

            output = StringIO()
            with redirect_stdout(output):
                exit_code = builder.main(
                    ["build-story-packet", "--story", str(story), "--stage", "CP6", "--project-root", str(root)]
                )

            self.assertEqual(0, exit_code)
            self.assertIn("wrote:", output.getvalue())


if __name__ == "__main__":
    unittest.main()
