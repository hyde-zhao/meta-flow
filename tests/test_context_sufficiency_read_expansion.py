from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from meta_flow.checks import context_doctor, cp_result
from meta_flow.context_pack import read_expansion, story_contract
from meta_flow.state import current
from meta_flow.work.budget import BudgetLimit
from meta_flow.work.io_metrics import IOMetrics
from meta_flow.work.model import build_work, write_work_create_only
from meta_flow.work.read_context import OperationReadContext
from meta_flow.work.risk import RiskFacts, classify_work
from meta_flow.work.scope import WorkScope

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONSOLE = Path(sys.executable).with_name("meta-flow")


def write_minimal_state(root: Path) -> None:
    state = current.default_current_state(root)
    state["project_id"] = "fixture-project"
    current.write_current_state(root, state)
    current.refresh_current_entry(root)


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


def write_preregistration_fixture(
    parent: Path,
) -> tuple[Path, Path, str, str]:
    release = parent / "meta-flow"
    process = parent / "meta-flow-process"
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
    story_ref = "process/stories/STORY-CR123-S01.md"
    story = process / "stories" / "STORY-CR123-S01.md"
    story.parent.mkdir(parents=True)
    story.write_text(
        """---
story_id: STORY-CR123-S01
cr_id: CR-123
title: Host preregistration
feature_refs: [governance.kernel]
feature_design_refs: [process/docs/features/kernel/DESIGN.md]
feature_contract_summary: Host pre-dispatch reads use one native ledger operation.
cr_delta_summary: Wire the existing read-log operation before dispatch.
dependency_inputs: [ROOT]
lld_policy: full-lld
risk_profile: runtime-high-risk
allowed_write_paths: [meta_flow/context_pack/**]
forbidden_write_paths: [process/state/**]
acceptance: [Host preregistration is idempotent]
verification_plan: [pytest tests/test_context_sufficiency_read_expansion.py]
authz_policy_refs: [process/policies/AUTHZ-POLICY.json]
---

# Story
""",
        encoding="utf-8",
    )
    (process / "stories" / "STORY-CR123-S01-LLD.md").write_text(
        "# LLD\n\nHost pre-dispatch read-expansion fixture.\n",
        encoding="utf-8",
    )
    summary = process / "changes" / "summaries" / "CR-123.summary.json"
    summary.parent.mkdir(parents=True)
    summary.write_text('{"id":"CR-123","status":"active"}\n', encoding="utf-8")
    scope = WorkScope(
        version=1,
        allowed_reads=("stories/**",),
        allowed_writes=("state/**",),
        required_checks=("read-log-check",),
    )
    classification = classify_work(
        RiskFacts(
            change_kind="code",
            touched_path_count=2,
            public_contract=True,
        ),
        requested_cr=True,
        g2_budget=BudgetLimit(30, 30, 12, 160_000),
    )
    work = build_work(
        work_id="WORK-CR123",
        project_id="fixture-project",
        objective="Validate Host preregistration",
        request_ref="works/WORK-CR123/REQUEST.md",
        scope=scope,
        classification=classification,
        release_base_oid="a" * 40,
        process_base_oid="b" * 40,
    )
    write_work_create_only(process, work)
    _packet, packet_path = story_contract.build_story_packet(
        release,
        story_path=Path(story_ref),
        stage="CP6",
        budget=8000,
    )
    packet_ref = "process/context/stories/STORY-CR123-S01.CP6.work-packet.json"
    assert packet_path == process / "context" / "stories" / "STORY-CR123-S01.CP6.work-packet.json"
    return release, process, packet_ref, work.scope.digest


class ContextSufficiencyReadExpansionTests(unittest.TestCase):
    def test_preregistration_plan_reuses_packet_policy_and_work_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process, packet_ref, scope_digest = write_preregistration_fixture(
                Path(directory)
            )
            metrics = IOMetrics("read-expansion-plan", enabled=True)
            context = OperationReadContext(
                process,
                operation_id="read-expansion-plan",
                operation_kind="plan",
                allowed_reads=(
                    packet_ref,
                    "process/policies/READ-POLICY.json",
                    "works/WORK-CR123/WORK.yaml",
                    "process/state/READ-EXPANSION-LEDGER.ndjson",
                ),
                metrics=metrics,
            )

            first = read_expansion.build_host_preregistration_plan(
                release,
                story_packet_ref=packet_ref,
                work_id="WORK-CR123",
                scope_digest=scope_digest,
                read_context=context,
            )
            second = read_expansion.build_host_preregistration_plan(
                release,
                story_packet_ref=packet_ref,
                work_id="WORK-CR123",
                scope_digest=scope_digest,
                read_context=context,
            )

            self.assertEqual(first.plan_digest, second.plan_digest)
            totals = metrics.summary()["totals"]
            self.assertEqual(3, totals["physical_reads"])
            self.assertEqual(3, totals["cache_hits"])

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
                reason_evidence={
                    "authorization_ref": "process/checkpoints/AUDIT.md"
                },
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

    def test_manual_read_log_cli_requires_and_forwards_reason_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = json.dumps(
                {"authorization_ref": "process/checkpoints/AUDIT.md"}
            )

            output = StringIO()
            with redirect_stdout(output):
                exit_code = read_expansion.main(
                    [
                        "read-log",
                        "--project-root",
                        str(root),
                        "--path",
                        "process/STATE.md",
                        "--reason",
                        "human_audit",
                        "--reason-evidence-json",
                        evidence,
                        "--stage",
                        "CP6",
                        "--agent",
                        "meta-dev",
                        "--context-ref",
                        "process/context/CP6.json",
                    ]
                )

            self.assertEqual(0, exit_code, output.getvalue())
            events, errors = read_expansion.load_events(
                read_expansion.default_ledger_path(root)
            )
            self.assertEqual([], errors)
            self.assertEqual(
                {"authorization_ref": "process/checkpoints/AUDIT.md"},
                events[0]["reason_evidence"],
            )

            missing_output = StringIO()
            with redirect_stdout(missing_output):
                missing_exit = read_expansion.main(
                    [
                        "read-log",
                        "--project-root",
                        str(root),
                        "--path",
                        "process/STATE.md",
                        "--reason",
                        "human_audit",
                        "--stage",
                        "CP6",
                        "--agent",
                        "meta-dev",
                        "--context-ref",
                        "process/context/CP6.json",
                    ]
                )
            self.assertEqual(2, missing_exit)
            self.assertIn("reason-evidence-json", missing_output.getvalue())

    def test_read_log_rejects_unknown_reason_before_ledger_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = read_expansion.default_ledger_path(root)

            with self.assertRaisesRegex(ValueError, "mutation=0"):
                read_expansion.append_event(
                    root,
                    requested_path="process/STATE.md",
                    reason="curiosity",
                    stage="CP6",
                    agent="meta-dev",
                    context_ref="process/context/stories/STORY-CR123-S01.CP6.work-packet.json",
                )

            self.assertFalse(ledger.exists())

    def test_manual_read_log_without_reason_blocks_before_target_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "process" / "STATE.md"
            target.parent.mkdir(parents=True)
            target.write_text("secret body must not be read", encoding="utf-8")
            ledger = read_expansion.default_ledger_path(root)
            target_reads = 0
            original_read_text = Path.read_text

            def tracked_read_text(path: Path, *args: object, **kwargs: object) -> str:
                nonlocal target_reads
                if path.resolve(strict=False) == target.resolve(strict=False):
                    target_reads += 1
                return original_read_text(path, *args, **kwargs)

            output = StringIO()
            with (
                patch.object(Path, "read_text", tracked_read_text),
                redirect_stdout(output),
            ):
                exit_code = read_expansion.main(
                    [
                        "read-log",
                        "--project-root",
                        str(root),
                        "--path",
                        "process/STATE.md",
                        "--reason-evidence-json",
                        "{}",
                        "--stage",
                        "CP6",
                        "--agent",
                        "meta-dev",
                        "--context-ref",
                        "process/context/CP6.json",
                    ]
                )

            self.assertEqual(2, exit_code)
            self.assertIn("--reason", output.getvalue())
            self.assertIn("mutation_count: 0", output.getvalue())
            self.assertEqual(0, target_reads)
            self.assertFalse(ledger.exists())

    def test_deep_review_is_rejected_for_new_events_but_legacy_event_remains_readable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "process" / "STATE.md"
            target.parent.mkdir(parents=True)
            target.write_text("secret body must not be read", encoding="utf-8")
            ledger = read_expansion.default_ledger_path(root)

            with self.assertRaisesRegex(ValueError, "target bytes=0"):
                read_expansion.append_event(
                    root,
                    requested_path="process/STATE.md",
                    reason="deep_review",
                    reason_evidence={},
                    stage="CP6",
                    agent="meta-dev",
                    context_ref="process/context/legacy.json",
                )
            self.assertFalse(ledger.exists())

            legacy = {
                "event_id": "RE-LEGACY-001",
                "event_type": "read_expansion",
                "agent": "meta-dev",
                "stage": "CP6",
                "requested_path": "process/STATE.md",
                "reason": "deep_review",
                "allowed_by_policy": True,
                "estimated_tokens": 10,
                "context_ref": "process/context/legacy.json",
                "created_at": "2026-01-01T00:00:00+00:00",
            }
            ledger.parent.mkdir(parents=True)
            ledger.write_text(json.dumps(legacy) + "\n", encoding="utf-8")

            errors, warnings = read_expansion.validate_ledger(root, ledger=ledger)

            self.assertEqual([], errors)
            self.assertTrue(any("legacy read-expansion" in warning for warning in warnings))

    def test_all_v2_read_expansion_reasons_require_exact_machine_evidence(self) -> None:
        fixtures = {
            "capsule_missing": {"capsule_ref": "process/context/missing.json"},
            "field_conflict": {
                "conflict_field": "scope_digest",
                "sources": [
                    {"ref": "works/W-001/WORK.yaml", "digest": "0" * 64},
                    {"ref": "process/context/base.json", "digest": "1" * 64},
                ],
            },
            "schema_validation_failed": {
                "schema_id": "work-v1",
                "error_code": "missing_required",
                "target_ref": "works/W-001/WORK.yaml",
            },
            "human_audit": {"authorization_ref": "process/checkpoints/AUDIT.md"},
            "summary_insufficient": {"missing_slots": ["acceptance"]},
        }

        for reason, evidence in fixtures.items():
            with self.subTest(reason=reason):
                self.assertEqual(
                    [],
                    read_expansion.validate_reason_evidence(reason, evidence),
                )
                self.assertTrue(
                    read_expansion.validate_reason_evidence(reason, {})
                )

    def test_read_log_append_only_correction_supersedes_invalid_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = read_expansion.default_ledger_path(root)
            ledger.parent.mkdir(parents=True)
            invalid = read_expansion.build_event(
                root,
                requested_path="process/STATE.md",
                reason="human_audit",
                reason_evidence={
                    "authorization_ref": "process/checkpoints/AUDIT.md"
                },
                stage="CP6",
                agent="meta-dev",
                context_ref="process/context/stories/STORY-CR123-S01.CP6.work-packet.json",
                story_id="STORY-CR123-S01",
            )
            invalid["reason"] = "curiosity"
            invalid["reason_evidence"] = {}
            invalid["allowed_by_policy"] = False
            ledger.write_text(
                json.dumps(invalid, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            before = ledger.read_bytes()

            successor, _path = read_expansion.append_event(
                root,
                requested_path="process/STATE.md",
                reason="human_audit",
                reason_evidence={
                    "authorization_ref": "process/checkpoints/AUDIT.md"
                },
                stage="CP6",
                agent="meta-dev",
                context_ref="process/context/stories/STORY-CR123-S01.CP6.work-packet.json",
                story_id="STORY-CR123-S01",
                supersedes_event_id=str(invalid["event_id"]),
            )
            errors, warnings = read_expansion.validate_ledger(root, ledger=ledger)

            self.assertEqual([], errors)
            self.assertTrue(warnings)
            self.assertEqual(invalid["event_id"], successor["supersedes_event_id"])
            self.assertTrue(ledger.read_bytes().startswith(before))

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
                    reason_evidence={
                        "conflict_field": "contract.version",
                        "sources": [
                            {
                                "ref": "docs/features/data-manifest/DESIGN.md",
                                "digest": "0" * 64,
                            },
                            {
                                "ref": "docs/design/FEATURE-REGISTRY.yaml",
                                "digest": "1" * 64,
                            },
                        ],
                    },
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
                reason_evidence={
                    "authorization_ref": "process/checkpoints/AUDIT.md"
                },
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

    def test_host_preregister_real_console_dry_run_apply_and_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process, packet_ref, scope_digest = write_preregistration_fixture(
                Path(directory)
            )
            command = [
                str(CONSOLE),
                "context",
                "read-log",
                "--project-root",
                str(release),
                "--story-packet",
                packet_ref,
                "--work-id",
                "WORK-CR123",
                "--scope-digest",
                scope_digest,
            ]
            env = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT)}

            dry_run = subprocess.run(
                [*command, "--dry-run"],
                cwd=PROJECT_ROOT,
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
            dry_plan = json.loads(dry_run.stdout)
            self.assertEqual(0, dry_run.returncode, dry_run.stderr)
            self.assertEqual("READY", dry_plan["decision"])
            self.assertEqual(1, dry_plan["planned_mutation_count"])
            self.assertEqual(0, dry_plan["mutation_count"])

            applied = subprocess.run(
                command,
                cwd=PROJECT_ROOT,
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
            applied_result = json.loads(applied.stdout)
            self.assertEqual(0, applied.returncode, applied.stderr)
            self.assertEqual("APPLIED", applied_result["decision"])
            self.assertEqual(1, applied_result["mutation_count"])

            replay = subprocess.run(
                command,
                cwd=PROJECT_ROOT,
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
            replay_result = json.loads(replay.stdout)
            self.assertEqual(0, replay.returncode, replay.stderr)
            self.assertEqual("NO_CHANGE", replay_result["decision"])
            self.assertEqual(0, replay_result["mutation_count"])
            self.assertNotIn(str(process), dry_run.stdout + applied.stdout + replay.stdout)

            errors, warnings = read_expansion.validate_ledger(release)
            self.assertEqual([], errors)
            self.assertEqual([], warnings)

    def test_host_preregister_invalid_reason_and_scope_are_mutation_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process, packet_ref, scope_digest = write_preregistration_fixture(
                Path(directory)
            )
            ledger = process / "state" / "READ-EXPANSION-LEDGER.ndjson"

            output = StringIO()
            with redirect_stdout(output):
                bad_reason = read_expansion.main(
                    [
                        "read-log",
                        "--project-root",
                        str(release),
                        "--story-packet",
                        packet_ref,
                        "--work-id",
                        "WORK-CR123",
                        "--scope-digest",
                        scope_digest,
                        "--reason",
                        "curiosity",
                        "--dry-run",
                    ]
                )
            self.assertEqual(2, bad_reason)
            self.assertEqual(0, json.loads(output.getvalue())["mutation_count"])
            self.assertFalse(ledger.exists())

            output = StringIO()
            with redirect_stdout(output):
                bad_scope = read_expansion.main(
                    [
                        "read-log",
                        "--project-root",
                        str(release),
                        "--story-packet",
                        packet_ref,
                        "--work-id",
                        "WORK-CR123",
                        "--scope-digest",
                        "0" * 64,
                        "--dry-run",
                    ]
                )
            self.assertEqual(2, bad_scope)
            self.assertEqual(0, json.loads(output.getvalue())["mutation_count"])
            self.assertFalse(ledger.exists())

    def test_host_preregister_invalid_binding_is_mutation_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process, packet_ref, scope_digest = write_preregistration_fixture(
                Path(directory)
            )
            binding = release / ".meta-flow" / "workspace.yaml"
            binding.write_text(
                binding.read_text(encoding="utf-8").replace(
                    "relative_path: meta-flow-process",
                    "relative_path: missing-process",
                ),
                encoding="utf-8",
            )
            output = StringIO()
            with redirect_stdout(output):
                exit_code = read_expansion.main(
                    [
                        "read-log",
                        "--project-root",
                        str(release),
                        "--story-packet",
                        packet_ref,
                        "--work-id",
                        "WORK-CR123",
                        "--scope-digest",
                        scope_digest,
                        "--dry-run",
                    ]
                )

            self.assertEqual(2, exit_code)
            self.assertEqual(0, json.loads(output.getvalue())["mutation_count"])
            self.assertFalse(
                (process / "state" / "READ-EXPANSION-LEDGER.ndjson").exists()
            )


if __name__ == "__main__":
    unittest.main()
