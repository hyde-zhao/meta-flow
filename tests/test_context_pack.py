from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from meta_flow.context_pack import builder
from meta_flow.project.onboarding import ProjectInitRequest, apply_project_init, plan_project_init
from meta_flow.project.onboarding_contract import (
    AUTHORIZATION_KIND,
    AUTHORIZATION_SOURCE,
    OnboardingAuthorization,
)
from meta_flow.project.process_route import _resolve_runtime_ref
from meta_flow.state import current


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
