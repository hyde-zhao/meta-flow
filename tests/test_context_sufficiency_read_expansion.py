from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from meta_flow.checks import context_doctor, cp_result
from meta_flow.context_pack import read_expansion, story_contract
from meta_flow.state import current


def write_minimal_state(root: Path) -> None:
    state = current.default_current_state(root)
    state["project_id"] = "fixture-project"
    current.write_current_state(root, state)


def write_cr_summary(root: Path, cr_id: str = "CR-123") -> None:
    path = root / "process" / "changes" / "summaries" / f"{cr_id}.summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"id": cr_id, "status": "active"}) + "\n", encoding="utf-8")


def write_story(root: Path, *, risk_profile: str = "standard-code", include_sufficiency: bool = True) -> Path:
    path = root / "process" / "stories" / "STORY-CR123-S01.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    extra = ""
    if include_sufficiency:
        extra = """feature_contract_summary: Manifest reader preserves legacy compatibility.
cr_delta_summary: Move manifest ownership to the data context.
dependency_inputs:
  - FEATURE data.manifest is registered
"""
    path.write_text(
        f"""---
story_id: STORY-CR123-S01
cr_id: CR-123
title: Migrate manifest owner
feature_refs:
  - data.manifest
feature_design_refs:
  - docs/features/data-manifest/DESIGN.md
lld_policy: technical-note
risk_profile: {risk_profile}
{extra}allowed_write_paths:
  - quant_lab/data/manifest/**
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


def cp6_result_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "checkpoint": "CP6",
        "checkpoint_id": "CP6-STORY-CR123-S01",
        "story_id": "STORY-CR123-S01",
        "cr_id": "CR-123",
        "context_ref": "process/context/stories/STORY-CR123-S01.CP6.work-packet.json",
        "dispatch_refs": ["ADE-0001"],
        "evidence_ref": "process/evidence/STORY-CR123-S01.CP6.index.json",
        "items": [
            {
                "id": "CP6-01",
                "name": "Human audit read was justified",
                "status": "PASS",
                "severity": "LOW",
                "evidence_refs": ["process/STATE.md#human-audit"],
            }
        ],
        "blockers": [],
        "waivers": [],
        "decision": "PASS",
        "next_route": "CP7",
    }


class ContextSufficiencyReadExpansionTests(unittest.TestCase):
    def test_standard_profile_missing_sufficiency_slots_warns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_story(root, include_sufficiency=False)
            _packet, output = story_contract.build_story_packet(root, story_path=story, stage="CP6", budget=8000)

            errors, warnings = story_contract.validate_story_packet(output, project_root=root)

            self.assertEqual([], errors)
            self.assertTrue(any("context_sufficiency missing required slots" in warning for warning in warnings))

    def test_strict_profile_missing_sufficiency_slots_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_story(root, risk_profile="runtime-high-risk", include_sufficiency=False)
            _packet, output = story_contract.build_story_packet(root, story_path=story, stage="CP6", budget=8000)

            errors, _warnings = story_contract.validate_story_packet(output, project_root=root)

            self.assertTrue(any("context_sufficiency missing required slots" in error for error in errors))

    def test_read_log_writes_and_check_accepts_allowed_reason(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "process" / "STATE.md"
            state.parent.mkdir(parents=True, exist_ok=True)
            state.write_text("# State\n", encoding="utf-8")

            event, ledger = read_expansion.append_event(
                root,
                requested_path="process/STATE.md",
                reason="human_audit",
                stage="CP6",
                agent="meta-dev",
                context_ref="process/context/stories/STORY-CR123-S01.CP6.work-packet.json",
                story_id="STORY-CR123-S01",
            )
            errors, warnings = read_expansion.validate_ledger(root, ledger=ledger)

            self.assertTrue(ledger.is_file())
            self.assertTrue(event["allowed_by_policy"])
            self.assertEqual([], errors)
            self.assertEqual([], warnings)

    def test_read_log_check_rejects_unknown_reason(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _event, ledger = read_expansion.append_event(
                root,
                requested_path="process/STATE.md",
                reason="curiosity",
                stage="CP6",
                agent="meta-dev",
                context_ref="process/context/stories/STORY-CR123-S01.CP6.work-packet.json",
            )

            errors, _warnings = read_expansion.validate_ledger(root, ledger=ledger)

            self.assertTrue(any("reason not allowed by read policy" in error for error in errors))
            self.assertTrue(any("allowed_by_policy must be true" in error for error in errors))

    def test_context_doctor_reports_summary_feedback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            docs = root / "docs" / "features" / "data-manifest" / "DESIGN.md"
            docs.parent.mkdir(parents=True, exist_ok=True)
            docs.write_text("# Design\n" + ("contract\n" * 20), encoding="utf-8")
            for _ in range(2):
                read_expansion.append_event(
                    root,
                    requested_path="docs/features/data-manifest/DESIGN.md",
                    reason="field_conflict",
                    stage="CP6",
                    agent="meta-dev",
                    context_ref="process/context/stories/STORY-CR123-S01.CP6.work-packet.json",
                    feature_id="data.manifest",
                )

            stream = StringIO()
            with redirect_stdout(stream):
                exit_code = context_doctor.main(["--project-root", str(root)])

            self.assertEqual(0, exit_code)
            output = stream.getvalue()
            self.assertIn("Context Doctor: OK", output)
            self.assertIn("docs/features/data-manifest/DESIGN.md: 2", output)
            self.assertIn("feature_contract_summary", output)

    def test_cp_result_requires_read_expansion_refs_for_deny_default_refs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = root / "process" / "checks" / "CP6-STORY-CR123-S01.result.json"
            result.parent.mkdir(parents=True, exist_ok=True)
            payload = cp6_result_payload()
            result.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root)

            self.assertTrue(any("deny-default references require read_expansion_refs" in error for error in errors))

    def test_cp_result_accepts_read_expansion_refs_covering_deny_default_refs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            event, _ledger = read_expansion.append_event(
                root,
                requested_path="process/STATE.md",
                reason="human_audit",
                stage="CP6",
                agent="meta-dev",
                context_ref="process/context/stories/STORY-CR123-S01.CP6.work-packet.json",
                story_id="STORY-CR123-S01",
            )
            result = root / "process" / "checks" / "CP6-STORY-CR123-S01.result.json"
            result.parent.mkdir(parents=True, exist_ok=True)
            payload = cp6_result_payload()
            payload["read_expansion_refs"] = [event["event_id"]]
            result.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root)

            self.assertEqual([], errors)


if __name__ == "__main__":
    unittest.main()
