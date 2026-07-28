from __future__ import annotations

import json
import subprocess
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
    current.refresh_current_entry(root)


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


def return_packet_payload(*, touched_path: str = "quant_lab/data/manifest/reader.py") -> dict[str, object]:
    return {
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


def write_return_packet(root: Path, *, touched_path: str = "quant_lab/data/manifest/reader.py") -> Path:
    path = root / "process" / "returns" / "STORY-CR123-S01.CP6.return.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    packet = return_packet_payload(touched_path=touched_path)
    path.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def init_paired_binding(root: Path) -> tuple[Path, Path]:
    release = root / "meta-flow"
    process = root / "meta-flow-process"
    release.mkdir()
    process.mkdir()
    for repository in (release, process):
        subprocess.run(
            ["git", "init", "-b", "main"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        )
    binding = release / ".meta-flow" / "workspace.yaml"
    binding.parent.mkdir()
    binding.write_text(
        "schema_version: 1\n"
        "layout_version: independent-process-repo-v1\n"
        "workflow_model: vnext\n"
        "project_id: fixture-project\n"
        "repo_role: release\n"
        "route_mode: sibling-binding\n"
        "process_repo:\n"
        "  anchor: workspace_parent\n"
        "  relative_path: meta-flow-process\n",
        encoding="utf-8",
    )
    (process / ".meta-flow-process.yaml").write_text(
        "schema_version: 1\n"
        "layout_version: independent-process-repo-v1\n"
        "workflow_model: vnext\n"
        "project_id: fixture-project\n"
        "repo_role: process\n"
        "route_mode: sibling-binding\n"
        "release_repo:\n"
        "  anchor: workspace_parent\n"
        "  relative_path: meta-flow\n",
        encoding="utf-8",
    )
    (process / "PROJECT.yaml").write_text(
        "schema_version: 1\n"
        "project_id: fixture-project\n"
        "name: Fixture Project\n"
        "status: active\n",
        encoding="utf-8",
    )
    return release, process


def write_bound_return_contract(process: Path) -> None:
    packet_path = process / "context" / "stories" / "STORY-CR123-S01.CP6.work-packet.json"
    packet_path.parent.mkdir(parents=True)
    packet_path.write_text(
        json.dumps(
            {
                "story_id": "STORY-CR123-S01",
                "stage": "CP6",
                "expected_return_packet": "process/returns/STORY-CR123-S01.CP6.return.json",
                "allowed_write_paths": ["quant_lab/data/manifest/**"],
                "forbidden_write_paths": ["quant_lab/trading/**"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return_path = process / "returns" / "STORY-CR123-S01.CP6.return.json"
    return_path.parent.mkdir(parents=True)
    return_path.write_text(
        json.dumps(return_packet_payload(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_bound_verify_story(process: Path) -> None:
    summary = process / "changes" / "summaries" / "CR-123.summary.json"
    summary.parent.mkdir(parents=True)
    summary.write_text(
        json.dumps({"id": "CR-123", "status": "active"}) + "\n",
        encoding="utf-8",
    )
    story = process / "stories" / "STORY-CR123-S01.md"
    story.parent.mkdir(parents=True)
    story.write_text(
        """---
story_id: STORY-CR123-S01
cr_id: CR-123
title: Migrate manifest owner
feature_refs:
  - data.manifest
feature_design_refs:
  - docs/features/data-manifest/DESIGN.md
feature_contract_summary: Manifest ownership is explicit.
cr_delta_summary: Verify the CP6 implementation.
dependency_inputs:
  - CP6 Return Packet
lld_policy: technical-note
risk_profile: standard-code
allowed_write_paths:
  - process/checks/**
forbidden_write_paths:
  - meta_flow/**
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


def write_cp6_projection_fixture(process: Path) -> Path:
    plan_path = process / "DEVELOPMENT-PLAN.yaml"
    plan_path.write_text(
        json.dumps(
            {
                "story_management_truth_source": "process/DEVELOPMENT-PLAN.yaml",
                "waves": [
                    {
                        "wave_id": "W1",
                        "stories": [
                            {
                                "story_id": "STORY-CR123-S01",
                                "title": "Upstream",
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
                            },
                            {
                                "story_id": "STORY-CR123-S02",
                                "title": "Downstream",
                                "wave": "W1",
                                "status": "lld-approved",
                                "depends_on": ["STORY-CR123-S01"],
                                "dev_gate": {
                                    "cp5_confirmed": True,
                                    "dependencies_satisfied": False,
                                    "file_conflict_free": True,
                                    "implementation_authorized": False,
                                    "lld_confirmed": True,
                                },
                            },
                        ],
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    result = {
        "schema_version": 1,
        "checkpoint": "CP6",
        "checkpoint_id": "CP6-STORY-CR123-S01",
        "profile": "standard-code",
        "story_id": "STORY-CR123-S01",
        "cr_id": "CR-123",
        "context_ref": "process/context/stories/STORY-CR123-S01.CP6.work-packet.json",
        "dispatch_refs": ["DISPATCH-CR123-S01"],
        "evidence_ref": "process/evidence/STORY-CR123-S01.CP6.index.json",
        "items": [
            {
                "id": "CP6-01",
                "name": "implementation",
                "status": "PASS",
                "severity": "BLOCKER",
                "evidence_refs": ["process/evidence/STORY-CR123-S01.CP6.index.json"],
            }
        ],
        "blockers": [],
        "waivers": [],
        "decision": "PASS",
        "next_route": "STORY-CR123-S02-CP6",
        "checked_at": "2026-07-26T00:00:00+00:00",
        "event_id": "CP6-STORY-CR123-S01-RESULT-V1",
    }
    result_path = process / "checks" / "CP6-STORY-CR123-S01.result.json"
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
                "result_ref": "process/checks/CP6-STORY-CR123-S01.result.json",
                "story_id": "STORY-CR123-S01",
                "cr_id": "CR-123",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return result_path


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

    def test_public_story_evidence_commands_resolve_sibling_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process = init_paired_binding(Path(directory))
            write_bound_return_contract(process)
            write_bound_verify_story(process)

            outputs: list[str] = []
            for argv in (
                [
                    "return-check",
                    "--packet",
                    "process/context/stories/STORY-CR123-S01.CP6.work-packet.json",
                    "--return",
                    "process/returns/STORY-CR123-S01.CP6.return.json",
                    "--project-root",
                    str(release),
                ],
                [
                    "evidence-index",
                    "--return",
                    "process/returns/STORY-CR123-S01.CP6.return.json",
                    "--project-root",
                    str(release),
                ],
                [
                    "evidence-check",
                    "--index",
                    "process/evidence/STORY-CR123-S01.CP6.index.json",
                    "--project-root",
                    str(release),
                ],
                [
                    "verify-packet",
                    "--from-return",
                    "process/returns/STORY-CR123-S01.CP6.return.json",
                    "--story",
                    "process/stories/STORY-CR123-S01.md",
                    "--project-root",
                    str(release),
                ],
            ):
                stream = StringIO()
                with redirect_stdout(stream):
                    exit_code = story_evidence.main(argv)
                self.assertEqual(0, exit_code, stream.getvalue())
                self.assertNotIn("WARN", stream.getvalue())
                outputs.append(stream.getvalue())

            evidence = json.loads(
                (process / "evidence" / "STORY-CR123-S01.CP6.index.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                "process/returns/STORY-CR123-S01.CP6.return.json",
                evidence["return_ref"],
            )
            verify_packet = json.loads(
                (
                    process
                    / "context"
                    / "stories"
                    / "STORY-CR123-S01.CP7.verify-packet.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(
                "process/returns/STORY-CR123-S01.CP6.return.json",
                verify_packet["implementation_return_ref"],
            )
            self.assertFalse((release / "process").exists())
            rendered = "\n".join(outputs)
            self.assertNotIn(str(release.resolve()), rendered)
            self.assertNotIn(str(process.resolve()), rendered)

    def test_public_return_check_fails_closed_on_broken_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process = init_paired_binding(Path(directory))
            write_bound_return_contract(process)
            binding = release / ".meta-flow" / "workspace.yaml"
            binding.write_text(
                binding.read_text(encoding="utf-8").replace(
                    "relative_path: meta-flow-process",
                    "relative_path: missing-process",
                ),
                encoding="utf-8",
            )

            stream = StringIO()
            with redirect_stdout(stream):
                exit_code = story_evidence.main(
                    [
                        "return-check",
                        "--packet",
                        "process/context/stories/STORY-CR123-S01.CP6.work-packet.json",
                        "--return",
                        "process/returns/STORY-CR123-S01.CP6.return.json",
                        "--project-root",
                        str(release),
                    ]
                )

            self.assertEqual(1, exit_code)
            self.assertIn("Story Return Packet Check: FAIL", stream.getvalue())
            self.assertFalse((release / "process").exists())
            self.assertNotIn(str(release.resolve()), stream.getvalue())
            self.assertNotIn(str(process.resolve()), stream.getvalue())

    def test_public_cp6_projection_dry_run_apply_and_idempotent_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process = init_paired_binding(Path(directory))
            write_cp6_projection_fixture(process)
            before = (process / "DEVELOPMENT-PLAN.yaml").read_bytes()

            dry_run = StringIO()
            with redirect_stdout(dry_run):
                exit_code = story_evidence.main(
                    [
                        "project-cp6",
                        "--project-root",
                        str(release),
                        "--result",
                        "process/checks/CP6-STORY-CR123-S01.result.json",
                    ]
                )
            self.assertEqual(0, exit_code, dry_run.getvalue())
            plan = json.loads(dry_run.getvalue())
            self.assertEqual("READY", plan["decision"])
            self.assertEqual(1, plan["mutation_count"])
            self.assertEqual(before, (process / "DEVELOPMENT-PLAN.yaml").read_bytes())

            applied = StringIO()
            with redirect_stdout(applied):
                exit_code = story_evidence.main(
                    [
                        "project-cp6",
                        "--project-root",
                        str(release),
                        "--result",
                        "process/checks/CP6-STORY-CR123-S01.result.json",
                        "--expected-plan-digest",
                        plan["plan_digest"],
                        "--apply",
                    ]
                )
            self.assertEqual(0, exit_code, applied.getvalue())
            result = json.loads(applied.getvalue())
            self.assertEqual("PASS", result["status"])
            projected = json.loads(
                (process / "DEVELOPMENT-PLAN.yaml").read_text(encoding="utf-8")
            )
            stories = {
                story["story_id"]: story
                for story in projected["waves"][0]["stories"]
            }
            self.assertEqual(
                "ready-for-verification",
                stories["STORY-CR123-S01"]["status"],
            )
            self.assertEqual("dev-ready", stories["STORY-CR123-S02"]["status"])

            replay = StringIO()
            with redirect_stdout(replay):
                exit_code = story_evidence.main(
                    [
                        "project-cp6",
                        "--project-root",
                        str(release),
                        "--result",
                        "process/checks/CP6-STORY-CR123-S01.result.json",
                        "--apply",
                    ]
                )
            self.assertEqual(0, exit_code, replay.getvalue())
            self.assertEqual("NO_CHANGE", json.loads(replay.getvalue())["status"])
            self.assertNotIn(str(process.resolve()), dry_run.getvalue())

    def test_public_cp6_projection_fails_closed_without_checkpoint_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process = init_paired_binding(Path(directory))
            write_cp6_projection_fixture(process)
            checkpoint = process / "state" / "CHECKPOINT-LEDGER.ndjson"
            checkpoint.write_text("", encoding="utf-8")
            before = (process / "DEVELOPMENT-PLAN.yaml").read_bytes()

            stream = StringIO()
            with redirect_stdout(stream):
                exit_code = story_evidence.main(
                    [
                        "project-cp6",
                        "--project-root",
                        str(release),
                        "--result",
                        "process/checks/CP6-STORY-CR123-S01.result.json",
                        "--expected-plan-digest",
                        "0" * 64,
                        "--apply",
                    ]
                )

            self.assertEqual(2, exit_code)
            self.assertEqual("BLOCKED", json.loads(stream.getvalue())["status"])
            self.assertEqual(before, (process / "DEVELOPMENT-PLAN.yaml").read_bytes())

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
