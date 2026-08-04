from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from meta_flow.context_pack import builder, capsule_delta, story_contract
from meta_flow.project.onboarding import ProjectInitRequest, apply_project_init, plan_project_init
from meta_flow.project.onboarding_contract import (
    AUTHORIZATION_KIND,
    AUTHORIZATION_SOURCE,
    OnboardingAuthorization,
)
from meta_flow.project.process_route import _resolve_runtime_ref
from meta_flow.state import current
from meta_flow.work.io_metrics import IOMetrics
from meta_flow.work.read_context import OperationReadContext


def init_binding_project(root: Path) -> tuple[Path, Path]:
    release = root / "fixture-release"
    release.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=release, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Meta Flow Test",
            "-c",
            "user.email=meta-flow@example.invalid",
            "commit",
            "--allow-empty",
            "-m",
            "initial",
        ],
        cwd=release,
        check=True,
        capture_output=True,
    )
    plan = plan_project_init(ProjectInitRequest(release, "fixture", "Fixture Project"))
    payload = plan.as_dict()
    apply_project_init(
        plan,
        OnboardingAuthorization(
            1,
            "context-pack-fixture",
            AUTHORIZATION_SOURCE,
            AUTHORIZATION_KIND,
            payload["operation"],
            payload["decision_ref"],
            payload["project_id"],
            payload["plan_digest"],
            payload["base_oids"],
            "2099-01-01T00:00:00+00:00",
        ),
    )
    return release, root / "fixture-process"


def test_read_policy_loader_reuses_one_operation_snapshot(tmp_path: Path) -> None:
    policy_path = tmp_path / builder.READ_POLICY_REL
    policy_path.parent.mkdir(parents=True)
    policy_path.write_text(
        json.dumps(builder.default_read_policy()),
        encoding="utf-8",
    )
    metrics = IOMetrics("read-policy", enabled=True)
    context = OperationReadContext(
        tmp_path / "process",
        operation_id="read-policy",
        operation_kind="plan",
        allowed_reads=(builder.READ_POLICY_REL.as_posix(),),
        metrics=metrics,
    )

    first = builder.load_read_policy(tmp_path, read_context=context)
    second = builder.load_read_policy(tmp_path, read_context=context)

    assert first == second
    assert metrics.summary()["totals"]["physical_reads"] == 1
    assert metrics.summary()["totals"]["cache_hits"] == 1


def write_minimal_state(root: Path) -> None:
    state = current.default_current_state(root)
    state["project_id"] = "fixture-project"
    current.write_current_state(root, state)


def write_cr_summary(root: Path, cr_id: str) -> None:
    path = _resolve_runtime_ref(
        root, f"process/changes/summaries/{cr_id}.summary.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "id": cr_id,
                "title": f"{cr_id} summary",
                "status": "active",
                "authz_policy_refs": ["NO_CREDENTIAL_READ"],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    index = _resolve_runtime_ref(root, "process/changes/CR-INDEX.json")
    items = [
        {
            "id": cr_id,
            "cr_type": "architecture",
            "title": f"{cr_id} summary",
            "status": "active",
            "lifecycle_status": "active",
            "readiness": "not_ready",
            "readiness_status": "not_ready",
            "gate_status": "cp5_pending",
            "formal_cr_path": f"process/changes/{cr_id}.md",
            "summary_ref": f"process/changes/summaries/{cr_id}.summary.json",
        }
    ]
    semantic = json.dumps(
        {"schema_version": 1, "items": items},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    index.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "2026-07-21T00:00:00+00:00",
                "semantic_digest": hashlib.sha256(semantic.encode("utf-8")).hexdigest(),
                "items": items,
            }
        )
        + "\n",
        encoding="utf-8",
    )


def write_cp2_result_with_required_evidence(root: Path, cr_id: str) -> Path:
    path = _resolve_runtime_ref(root, f"process/checks/CP2-{cr_id}.result.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "checkpoint": "CP2",
                "checkpoint_id": f"CP2-{cr_id}",
                "cr_id": cr_id,
                "decision": "PASS",
                "context_ref": f"process/context/CP2-{cr_id}.context.json",
                "evidence_ref": "",
                "dispatch_refs": [],
                "items": [
                    {
                        "id": "CP2-01",
                        "name": "scope approved",
                        "status": "PASS",
                        "severity": "INFO",
                        "evidence_refs": [],
                    }
                ],
                "blockers": [],
                "waivers": [],
                "commitments": {
                    "required_evidence": [
                        {
                            "id": "REQ-EVID-REAL-LAKE",
                            "kind": "real_lake_validation",
                            "required_stage": "CP7",
                            "minimum_evidence": {"run_refs_min": 2},
                        }
                    ]
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


class ContextPackTests(unittest.TestCase):
    def test_incremental_capsule_composes_and_reduces_repeated_bytes_by_sixty_percent(self) -> None:
        invariant = "stable-contract-" * 400
        contexts = [
            {
                "project": "fixture",
                "invariant": invariant,
                "stage": stage,
                "stage_value": index,
            }
            for index, stage in enumerate(
                ("base", "clarification", "design", "implementation", "verification")
            )
        ]
        refs = [
            "process/context/W-001.base.json",
            "process/context/W-001.clarification.delta.json",
            "process/context/W-001.design.delta.json",
            "process/context/W-001.implementation.delta.json",
            "process/context/W-001.verification.delta.json",
        ]
        payloads: dict[str, dict[str, object]] = {}
        payloads[refs[0]] = builder.build_incremental_capsule_base(
            contexts[0],
            owner_kind="work",
            owner_id="W-001",
            revision="r1",
            evidence_refs=("works/W-001/REQUEST.md",),
        )
        for index, stage in enumerate(capsule_delta.CAPSULE_STAGES, 1):
            parent = payloads[refs[index - 1]]
            payloads[refs[index]] = builder.build_incremental_capsule_delta(
                contexts[index - 1],
                contexts[index],
                owner_kind="work",
                owner_id="W-001",
                revision="r1",
                parent_ref=refs[index - 1],
                parent_digest=str(parent["semantic_digest"]),
                stage=stage,
                stage_evidence=(f"works/W-001/{stage}.md",),
            )

        composed = capsule_delta.compose_capsule(refs[-1], payloads.__getitem__)
        full_bytes = sum(
            len(json.dumps(context, ensure_ascii=False, sort_keys=True).encode())
            for context in contexts
        )
        incremental_bytes = sum(
            len(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode())
            for payload in payloads.values()
        )
        materialized = capsule_delta.materialize_capsule_base(composed)

        self.assertEqual(contexts[-1], composed.fields)
        self.assertLessEqual(incremental_bytes, int(full_bytes * 0.4))
        self.assertEqual(contexts[-1], materialized["fields"])
        self.assertEqual(5, len(composed.chain_refs))

    def test_capsule_chain_fails_closed_on_digest_stage_owner_depth_and_absolute_path(self) -> None:
        base_ref = "process/context/W-001.base.json"
        base = capsule_delta.create_capsule_base(
            owner_kind="work",
            owner_id="W-001",
            revision="r1",
            fields={"value": 1},
            evidence_refs=("works/W-001/REQUEST.md",),
        )
        drift_ref = "process/context/W-001.design.delta.json"
        drift = capsule_delta.create_capsule_delta(
            owner_kind="work",
            owner_id="W-001",
            revision="r1",
            parent_ref=base_ref,
            parent_digest="0" * 64,
            stage="design",
            changed_fields={"value": 2},
            stage_evidence=("works/W-001/DESIGN.md",),
        )

        with self.assertRaisesRegex(ValueError, "digest drift"):
            capsule_delta.compose_capsule(
                drift_ref,
                {base_ref: base, drift_ref: drift}.__getitem__,
            )
        with self.assertRaisesRegex(ValueError, "absolute path"):
            capsule_delta.create_capsule_base(
                owner_kind="work",
                owner_id="W-001",
                revision="r1",
                fields={"resolved": "/tmp/secret"},
                evidence_refs=("works/W-001/REQUEST.md",),
            )

        missing = capsule_delta.create_capsule_delta(
            owner_kind="work",
            owner_id="W-001",
            revision="r1",
            parent_ref="process/context/missing.json",
            parent_digest="0" * 64,
            stage="clarification",
            changed_fields={"value": 2},
            stage_evidence=("works/W-001/REQUEST.md",),
        )
        with self.assertRaisesRegex(ValueError, "parent is missing"):
            capsule_delta.compose_capsule(
                "process/context/missing.delta.json",
                {"process/context/missing.delta.json": missing}.__getitem__,
            )

        cycle_ref = "process/context/cycle.delta.json"
        cycle = capsule_delta.create_capsule_delta(
            owner_kind="work",
            owner_id="W-001",
            revision="r1",
            parent_ref=cycle_ref,
            parent_digest="0" * 64,
            stage="clarification",
            changed_fields={"value": 2},
            stage_evidence=("works/W-001/REQUEST.md",),
        )
        with self.assertRaisesRegex(ValueError, "cycle"):
            capsule_delta.compose_capsule(cycle_ref, {cycle_ref: cycle}.__getitem__)

        first_ref = "process/context/W-001.clarification.delta.json"
        first = capsule_delta.create_capsule_delta(
            owner_kind="work",
            owner_id="W-001",
            revision="r1",
            parent_ref=base_ref,
            parent_digest=str(base["semantic_digest"]),
            stage="clarification",
            changed_fields={"value": 2},
            stage_evidence=("works/W-001/REQUEST.md",),
        )
        repeated_ref = "process/context/W-001.clarification-2.delta.json"
        repeated = capsule_delta.create_capsule_delta(
            owner_kind="work",
            owner_id="W-001",
            revision="r1",
            parent_ref=first_ref,
            parent_digest=str(first["semantic_digest"]),
            stage="clarification",
            changed_fields={"value": 3},
            stage_evidence=("works/W-001/REQUEST.md",),
        )
        with self.assertRaisesRegex(ValueError, "stage order"):
            capsule_delta.compose_capsule(
                repeated_ref,
                {base_ref: base, first_ref: first, repeated_ref: repeated}.__getitem__,
            )

    def test_story_public_entries_use_binding_logical_refs_without_absolute_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process = init_binding_project(Path(directory))
            write_cr_summary(release, "CR-101")
            story = _resolve_runtime_ref(release, "process/stories/STORY-CR101-S01.md")
            story.parent.mkdir(parents=True, exist_ok=True)
            story.write_text(
                """---
story_id: STORY-CR101-S01
cr_id: CR-101
title: Binding packet
feature_refs: [governance.kernel]
feature_design_refs: [docs/features/kernel/DESIGN.md]
feature_contract_summary: binding-aware public entry
cr_delta_summary: resolve logical process refs
dependency_inputs: [ROOT]
lld_policy: technical-note
risk_profile: standard-code
allowed_write_paths: [meta_flow/context_pack/story_contract.py]
forbidden_write_paths: [delivery/**]
acceptance: [logical refs resolve]
verification_plan: [pytest]
authz_policy_refs: [NO_CREDENTIAL_READ]
---
""",
                encoding="utf-8",
            )
            logical_story = "process/stories/STORY-CR101-S01.md"
            logical_packet = "process/context/stories/STORY-CR101-S01.CP6.work-packet.json"
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    0,
                    story_contract.main(
                        [
                            "build-story-packet", "--project-root", str(release), "--story", logical_story,
                            "--stage", "CP6", "--output", logical_packet,
                        ]
                    ),
                )
            self.assertIn(logical_packet, output.getvalue())
            self.assertNotIn(str(process), output.getvalue())
            self.assertFalse((release / "process").exists())
            packet = json.loads(_resolve_runtime_ref(release, logical_packet).read_text(encoding="utf-8"))
            self.assertEqual("BLOCKED", packet["admission"]["decision"])
            self.assertEqual(["FROZEN_CP6_EVIDENCE_MISSING"], packet["admission"]["reason_codes"])
            self.assertEqual(
                0,
                story_contract.main(
                    ["check-story-packet", "--project-root", str(release), "--packet", logical_packet]
                ),
            )
            self.assertEqual(
                0,
                story_contract.main(
                    ["sufficiency-check", "--project-root", str(release), "--packet", logical_packet]
                ),
            )
            explain_output = StringIO()
            with redirect_stdout(explain_output):
                self.assertEqual(
                    0,
                    story_contract.main(
                        [
                            "explain-story-packet",
                            "--project-root",
                            str(release),
                            "--packet",
                            logical_packet,
                        ]
                    ),
                )
            self.assertIn(f"- path: {logical_packet}", explain_output.getvalue())
            self.assertNotIn(str(process), explain_output.getvalue())

    def test_build_routes_binding_only_context_to_process_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process = init_binding_project(Path(directory))
            write_minimal_state(release)
            write_cr_summary(release, "CR-101")

            context, output = builder.build_context_pack(
                release,
                stage="CP6",
                profile="standard-code",
                cr_id="CR-101",
                budget=16000,
            )

            self.assertEqual(process / "context" / "CP6-CR101.context.json", output)
            self.assertFalse((release / "process").exists())
            self.assertEqual(
                "process/state/STATE.current.json",
                context["state_ref"],
            )

    def test_build_projects_missing_current_and_refreshes_after_context_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = current.default_current_state(root)
            state["active_story"] = "STORY-CR101-S01"
            state["active_context_ref"] = "process/context/CP6-CR101.context.json"
            current.write_current_state(root, state)
            write_cr_summary(root, "CR-101")

            _context, output = builder.build_context_pack(
                root,
                stage="CP6",
                profile="standard-code",
                cr_id="CR-101",
                budget=16000,
            )

            current_entry = json.loads(
                (root / "process" / "current" / "CURRENT.json").read_text(encoding="utf-8")
            )
            self.assertTrue(output.is_file())
            self.assertEqual(
                "process/context/CP6-CR101.context.json",
                current_entry["context_ref"],
            )
            self.assertEqual([], current_entry["stale_refs"])

    def test_build_rejects_current_entry_without_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current_path = root / "process" / "current" / "CURRENT.json"
            current_path.parent.mkdir(parents=True, exist_ok=True)
            current_path.write_text("{}\n", encoding="utf-8")

            with self.assertRaisesRegex(
                ValueError,
                "STATE.current.json and CURRENT.json must both exist or both be absent",
            ):
                builder.build_context_pack(
                    root,
                    stage="CP6",
                    profile="standard-code",
                    budget=16000,
                )

    def test_build_rejects_invalid_state_without_projecting_current(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = root / "process" / "state" / "STATE.current.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text("{invalid\n", encoding="utf-8")

            with self.assertRaisesRegex(
                ValueError,
                "runtime state payload is empty or invalid",
            ):
                builder.build_context_pack(
                    root,
                    stage="CP6",
                    profile="standard-code",
                    budget=16000,
                )

            self.assertFalse(
                (root / "process" / "current" / "CURRENT.json").exists()
            )

    def test_cp7_context_accepts_legal_missing_state_in_sibling_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process = init_binding_project(Path(directory))
            write_cr_summary(release, "CR-101")

            context, output = builder.build_context_pack(
                release,
                stage="CP7",
                profile="high-risk",
                cr_id="CR-101",
                budget=16000,
            )
            errors, warnings = builder.validate_context_pack(
                output,
                project_root=release,
            )

            self.assertEqual([], errors)
            self.assertFalse(
                {
                    "process/state/STATE.current.json",
                    "process/current/CURRENT.json",
                }
                & {
                    str(entry["path"])
                    for entry in context["must_read"]
                }
            )
            state_reads = {
                str(entry["path"]): entry
                for entry in context["allowed_reads"]
                if str(entry["path"])
                in {
                    "process/state/STATE.current.json",
                    "process/current/CURRENT.json",
                }
            }
            self.assertEqual(2, len(state_reads))
            self.assertTrue(
                all(entry["required"] is False for entry in state_reads.values())
            )
            self.assertNotIn(
                "must_read does not include process/current/CURRENT.json",
                warnings,
            )

            stream = StringIO()
            with redirect_stdout(stream):
                self.assertEqual(
                    0,
                    builder.main(
                        [
                            "explain",
                            "--project-root",
                            str(release),
                            "--context",
                            "process/context/CP7-CR101.context.json",
                        ]
                    ),
                )
            self.assertIn(
                "- path: process/context/CP7-CR101.context.json",
                stream.getvalue(),
            )
            self.assertNotIn(str(process.resolve()), stream.getvalue())

    def test_build_writes_context_pack_and_read_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root, "CR-101")

            output = root / "process" / "context" / "CP6-CR101.context.json"
            exit_code = builder.main(
                [
                    "build",
                    "--project-root",
                    str(root),
                    "--stage",
                    "CP6",
                    "--profile",
                    "standard-code",
                    "--cr",
                    "CR-101",
                    "--budget",
                    "16000",
                    "--output",
                    str(output),
                ]
            )

            self.assertEqual(0, exit_code)
            self.assertTrue(output.is_file())
            self.assertTrue((root / "process" / "policies" / "READ-POLICY.json").is_file())
            context = json.loads(output.read_text(encoding="utf-8"))
            allowed = {entry["path"] for entry in context["allowed_reads"]}
            must = {entry["path"] for entry in context["must_read"]}
            do_not = {entry["path_or_pattern"] for entry in context["do_not_read_by_default"]}
            self.assertIn("process/state/STATE.current.json", allowed)
            self.assertIn("process/current/CURRENT.json", allowed)
            self.assertIn("process/state/STATE.current.json", must)
            self.assertIn("process/current/CURRENT.json", must)
            self.assertIn("process/changes/summaries/CR-101.summary.json", allowed)
            self.assertIn("process/policies/READ-POLICY.json", allowed)
            self.assertIn("process/STATE.md", context["denied_default_reads"])
            self.assertIn("process/archive/**", context["denied_default_reads"])
            self.assertIn("process/archive/**", do_not)

    def test_check_passes_for_valid_generated_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root, "CR-101")
            _context, output = builder.build_context_pack(
                root,
                stage="CP6",
                profile="standard-code",
                cr_id="CR-101",
                budget=16000,
            )

            stream = StringIO()
            with redirect_stdout(stream):
                exit_code = builder.main(["check", "--project-root", str(root), "--context", str(output)])

            self.assertEqual(0, exit_code)
            self.assertIn("Context Pack Check: OK", stream.getvalue())

    def test_check_rejects_deny_default_allowed_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root, "CR-101")
            context, output = builder.build_context_pack(
                root,
                stage="CP6",
                profile="standard-code",
                cr_id="CR-101",
                budget=16000,
            )
            context["allowed_reads"].append(
                {
                    "path": "process/STATE.md",
                    "mode": "full",
                    "estimated_tokens": 1,
                    "required": False,
                    "reason": "legacy_state",
                }
            )
            output.write_text(json.dumps(context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            errors, _warnings = builder.validate_context_pack(output, project_root=root)

            self.assertIn("allowed_reads contains deny-default path: process/STATE.md", errors)

    def test_check_fails_when_context_exceeds_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root, "CR-101")
            context, output = builder.build_context_pack(
                root,
                stage="CP6",
                profile="standard-code",
                cr_id="CR-101",
                budget=1,
            )
            self.assertGreater(context["budget"]["estimated_tokens"], context["budget"]["max_tokens"])

            errors, _warnings = builder.validate_context_pack(output, project_root=root)

            self.assertTrue(any("estimated_tokens exceeds budget" in error for error in errors))

    def test_check_fails_when_required_cr_summary_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            _context, output = builder.build_context_pack(
                root,
                stage="CP6",
                profile="standard-code",
                cr_id="CR-404",
                budget=16000,
            )

            errors, _warnings = builder.validate_context_pack(output, project_root=root)

            self.assertIn("required allowed_read missing on disk: process/changes/summaries/CR-404.summary.json", errors)
            self.assertIn("cr_summary_ref missing on disk: process/changes/summaries/CR-404.summary.json", errors)

    def test_check_rejects_empty_zone_controls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root, "CR-101")
            context, output = builder.build_context_pack(
                root,
                stage="CP6",
                profile="standard-code",
                cr_id="CR-101",
                budget=16000,
            )
            context["must_read"] = []
            context["do_not_read_by_default"] = []
            output.write_text(json.dumps(context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            errors, _warnings = builder.validate_context_pack(output, project_root=root)

            self.assertIn("must_read must be a non-empty list", errors)
            self.assertIn("do_not_read_by_default must be a non-empty list", errors)

    def test_cp7_context_includes_required_evidence_from_cp2_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root, "CR-101")
            write_cp2_result_with_required_evidence(root, "CR-101")

            context, output = builder.build_context_pack(
                root,
                stage="CP7",
                profile="standard-code",
                cr_id="CR-101",
                budget=16000,
            )
            errors, _warnings = builder.validate_context_pack(output, project_root=root)

            self.assertEqual([], errors)
            self.assertEqual("REQ-EVID-REAL-LAKE", context["must_verify"][0]["id"])
            self.assertEqual("process/checks/CP2-CR-101.result.json", context["must_verify"][0]["source_result_ref"])

    def test_context_check_warns_when_capsule_duplicates_checkpoint_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root, "CR-101")
            context, output = builder.build_context_pack(
                root,
                stage="CP5",
                profile="standard-code",
                cr_id="CR-101",
                budget=16000,
            )
            repeated = "Decision Brief\n" + ("This checkpoint paragraph is intentionally repeated. " * 12)
            checkpoint = root / "process" / "checkpoints" / "CP5.md"
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            checkpoint.write_text(repeated, encoding="utf-8")
            context["checkpoint_ref"] = "process/checkpoints/CP5.md"
            context["inline_decision_brief"] = repeated
            output.write_text(json.dumps(context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            _errors, warnings = builder.validate_context_pack(output, project_root=root)

            self.assertTrue(any("capsule_content_redundant" in warning for warning in warnings))

    def test_context_check_warns_when_single_paragraph_duplicates_checkpoint_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root, "CR-101")
            context, output = builder.build_context_pack(
                root,
                stage="CP5",
                profile="standard-code",
                cr_id="CR-101",
                budget=16000,
            )
            repeated = "This checkpoint paragraph is intentionally repeated without line breaks. " * 6
            checkpoint = root / "process" / "checkpoints" / "CP5.md"
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            checkpoint.write_text(repeated, encoding="utf-8")
            context["checkpoint_ref"] = "process/checkpoints/CP5.md"
            context["inline_decision_brief"] = repeated
            output.write_text(json.dumps(context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            _errors, warnings = builder.validate_context_pack(output, project_root=root)

            self.assertTrue(any("capsule_content_redundant" in warning for warning in warnings))


if __name__ == "__main__":
    unittest.main()
