from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from meta_flow.context_pack import builder, story_contract
from meta_flow.state import current


def write_minimal_state(root: Path) -> None:
    state = current.default_current_state(root)
    state["project_id"] = "fixture-project"
    current.write_current_state(root, state)
    current.refresh_current_entry(root)


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
feature_contract_summary: data.manifest is the single manifest contract
cr_delta_summary: replace the legacy manifest owner
dependency_inputs:
  - ROOT: no upstream Story
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


def write_projected_story(root: Path) -> Path:
    story = root / "process" / "stories" / "STORY-CR123-S04.md"
    story.parent.mkdir(parents=True, exist_ok=True)
    story.write_text(
        """---
story_id: STORY-CR123-S04
cr_id: CR-123
title: Ledger migration
feature_refs: [governance.kernel]
feature_design_refs: [process/docs/features/kernel/DESIGN.md]
lld_policy: full-lld
risk_profile: runtime-high-risk
---

# Story

## 目标

对四类 ledger 执行 append-only 版本迁移。

## 量化验收

- ledger types：4。
- history rewrites：0。
""",
        encoding="utf-8",
    )
    lld = story.with_name("STORY-CR123-S04-LLD.md")
    lld.write_text(
        """# LLD

## 10. 测试设计

| Case | 操作 | 预期 |
|---|---|---|
| C20 | dispatch migration | PASS |
| C21 | replay | NO_CHANGE |
""",
        encoding="utf-8",
    )
    plan = root / "process" / "DEVELOPMENT-PLAN.yaml"
    plan.write_text(
        json.dumps(
            {
                "waves": [
                    {
                        "stories": [
                            {
                                "story_id": "STORY-CR123-S04",
                                "status": "dev-ready",
                                "dependency_type": [
                                    {
                                        "upstream": "STORY-CR123-S01",
                                        "type": "contract",
                                        "gate": "CP6 PASS",
                                    }
                                ],
                                "dev_gate": {
                                    "cp5_confirmed": True,
                                    "dependencies_satisfied": True,
                                    "file_conflict_free": True,
                                    "implementation_authorized": True,
                                    "lld_confirmed": True,
                                },
                                "file_ownership": {
                                    "primary": ["meta_flow/state/ledger_migration.py"],
                                    "shared": ["tests/test_cp_result_event_ledger.py"],
                                    "forbidden": ["process/state/**"],
                                },
                                "output_files": [
                                    "meta_flow/state/ledger_migration.py",
                                    "tests/test_cp_result_event_ledger.py",
                                ],
                            }
                        ]
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return story


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

    def test_cp6_packet_projects_contract_and_admission_from_native_development_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_projected_story(root)

            packet, output = story_contract.build_story_packet(
                root,
                story_path=story,
                stage="CP6",
                budget=8000,
            )

            self.assertEqual("READY", packet["admission"]["decision"])
            self.assertEqual(
                ["meta_flow/state/ledger_migration.py", "tests/test_cp_result_event_ledger.py"],
                packet["allowed_write_paths"],
            )
            self.assertEqual(["process/state/**"], packet["forbidden_write_paths"])
            self.assertEqual(2, len(packet["acceptance"]))
            self.assertEqual(4, len(packet["verification_plan"]))
            self.assertIn("STORY-CR123-S01:contract:CP6 PASS", packet["dependency_inputs"])
            self.assertTrue(packet["feature_contract_summary"])
            self.assertTrue(packet["cr_delta"]["summary"])
            errors, _warnings = story_contract.validate_story_packet(output, project_root=root)
            self.assertEqual([], errors)

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

    def test_legal_missing_runtime_state_is_optional_and_does_not_create_state_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_cr_summary(root)
            write_story(root)

            packet, output = story_contract.build_story_packet(
                root,
                story_path=Path("process/stories/STORY-CR123-S01.md"),
                stage="CP6",
                budget=8000,
            )

            self.assertTrue(output.is_file())
            self.assertEqual("process/stories/STORY-CR123-S01.md", packet["story_ref"])
            self.assertNotIn(str(root), json.dumps(packet, ensure_ascii=False))
            state_entries = {
                entry["path"]: entry for entry in packet["allowed_reads"] if entry["path"].startswith("process/")
            }
            self.assertFalse(state_entries["process/state/STATE.current.json"]["required"])
            self.assertFalse(state_entries["process/current/CURRENT.json"]["required"])
            must_read = {entry["path"] for entry in packet["must_read"]}
            self.assertNotIn("process/state/STATE.current.json", must_read)
            self.assertNotIn("process/current/CURRENT.json", must_read)
            self.assertFalse((root / "process" / "state" / "STATE.current.json").exists())
            self.assertFalse((root / "process" / "current" / "CURRENT.json").exists())

    def test_state_without_current_entry_is_projected_before_and_after_packet_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = current.default_current_state(root)
            state["active_story"] = "STORY-CR123-S01"
            current.write_current_state(root, state)
            write_cr_summary(root)
            story = write_story(root)

            _packet, output = story_contract.build_story_packet(
                root,
                story_path=story,
                stage="CP6",
                budget=8000,
            )

            current_entry = json.loads(
                (root / "process" / "current" / "CURRENT.json").read_text(encoding="utf-8")
            )
            self.assertTrue(output.is_file())
            self.assertEqual(
                "process/context/stories/STORY-CR123-S01.CP6.work-packet.json",
                current_entry["story_packet_ref"],
            )
            self.assertEqual([], current.validate_current_projection(root))

    def test_current_entry_without_state_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current_path = root / "process" / "current" / "CURRENT.json"
            current_path.parent.mkdir(parents=True, exist_ok=True)
            current_path.write_text("{}\n", encoding="utf-8")
            write_cr_summary(root)
            story = write_story(root)

            with self.assertRaisesRegex(ValueError, "runtime state contract is partial"):
                story_contract.build_story_packet(
                    root,
                    story_path=story,
                    stage="CP6",
                    budget=8000,
                )

    def test_invalid_runtime_state_payload_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = root / "process" / "state" / "STATE.current.json"
            current_path = root / "process" / "current" / "CURRENT.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            current_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text("{invalid\n", encoding="utf-8")
            current_path.write_text("{}\n", encoding="utf-8")
            write_cr_summary(root)
            story = write_story(root)

            with self.assertRaisesRegex(ValueError, "runtime state payload is empty or invalid"):
                story_contract.build_story_packet(root, story_path=story, stage="CP6", budget=8000)

    def test_runtime_state_projection_drift_is_refreshed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            current_path = root / "process" / "current" / "CURRENT.json"
            current_entry = json.loads(current_path.read_text(encoding="utf-8"))
            current_entry["active_story"] = "STORY-DRIFT"
            current_path.write_text(json.dumps(current_entry) + "\n", encoding="utf-8")
            write_cr_summary(root)
            story = write_story(root)

            story_contract.build_story_packet(
                root,
                story_path=story,
                stage="CP6",
                budget=8000,
            )

            current_entry = json.loads(current_path.read_text(encoding="utf-8"))
            self.assertNotEqual("STORY-DRIFT", current_entry["active_story"])
            self.assertEqual([], current.validate_current_projection(root))

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
            self.assertEqual(
                [
                    {
                        "operation": "context.read-log",
                        "input_contract": "ReadExpansionPlanV1",
                        "actor": "host-orchestrator",
                        "required_before": "story-dispatch",
                        "requested_refs": [
                            "process/stories/STORY-CR123-S01-LLD.md"
                        ],
                        "reason": "deep_review",
                    }
                ],
                packet["pre_dispatch_actions"],
            )

    def test_full_lld_packet_rejects_missing_host_preregistration_action(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_story(root, lld_policy="full-lld")
            packet, output = story_contract.build_story_packet(
                root,
                story_path=story,
                stage="CP6",
                budget=8000,
            )
            packet["pre_dispatch_actions"] = []
            output.write_text(
                json.dumps(packet, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            errors, _warnings = story_contract.validate_story_packet(
                output,
                project_root=root,
            )

            self.assertIn(
                "deny-default read_if_needed requires exactly one Host pre_dispatch_action",
                errors,
            )

    def test_legacy_v1_packet_remains_readable_but_requires_regeneration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_story(root, lld_policy="full-lld")
            packet, output = story_contract.build_story_packet(
                root,
                story_path=story,
                stage="CP6",
                budget=8000,
            )
            packet["schema_version"] = 1
            packet["pre_dispatch_actions"] = []
            output.write_text(
                json.dumps(packet, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            errors, warnings = story_contract.validate_story_packet(
                output,
                project_root=root,
            )

            self.assertEqual([], errors)
            self.assertTrue(
                any(
                    "regenerate before the next Story dispatch" in warning
                    for warning in warnings
                )
            )

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

    def test_check_rejects_absolute_path_without_echoing_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_story(root)
            packet, output = story_contract.build_story_packet(root, story_path=story, stage="CP6", budget=8000)
            packet["story_ref"] = str(story)
            output.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            errors, _warnings = story_contract.validate_story_packet(output, project_root=root)

            self.assertIn("Story packet contains absolute path values at: $.story_ref", errors)
            self.assertNotIn(str(root), "\n".join(errors))

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
