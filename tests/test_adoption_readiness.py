from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from meta_flow.checks import adoption_readiness, quality_governance
from meta_flow.workspace.legacy_route_adapter import _LegacyRouteAuthorization
from meta_flow.workspace.routing import bootstrap_process_workspace, legacy_workspace_plan


def init_git(root: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
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
        cwd=root,
        check=True,
        capture_output=True,
    )


def bootstrap_capability(project_root: Path, artifact_root: Path, authorization_id: str) -> _LegacyRouteAuthorization:
    plan = legacy_workspace_plan(
        "workspace bootstrap", project_root, artifact_root, "target-project"
    )
    return _LegacyRouteAuthorization(
        schema_version=1,
        authorization_id=authorization_id,
        command="workspace bootstrap",
        authorization_source="typed-user-confirmation",
        authorization_kind="workspace-operation",
        decision_ref="works/TEST/GATE.yaml",
        project_id="target-project",
        operation_digest=str(plan["operation_digest"]),
        expected_oids=dict(plan["expected_oids"]),
        expires_at="2099-01-01T00:00:00+00:00",
    )


def write_identity_fixture(root: Path) -> None:
    path = root / "docs" / "design" / "PACKAGE-IDENTITY.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "product_name": root.name,
                "repo_name": root.name,
                "python_import": root.name.replace("-", "_"),
                "cli_name": "target_cli",
                "legacy_aliases": [],
                "package_mode": True,
                "public_api_files": [f"{root.name.replace('-', '_')}/__init__.py"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    package_root = root / root.name.replace("-", "_")
    package_root.mkdir()
    (package_root / "__init__.py").write_text("", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "{root.name}"\n[project.scripts]\ntarget_cli = "{root.name.replace("-", "_")}.cli:main"\n',
        encoding="utf-8",
    )
    (root / "README.md").write_text(
        f"# {root.name}\n\nRelease deliverables are documented under docs/release.\n",
        encoding="utf-8",
    )


def write_quality_fixture(process_root: Path) -> None:
    policies = process_root / "policies"
    policies.mkdir(parents=True, exist_ok=True)
    (policies / "QUALITY-MODEL.yaml").write_text(
        quality_governance.QUALITY_MODEL_TEMPLATE, encoding="utf-8"
    )
    (policies / "EVAL-MATRIX.yaml").write_text(
        quality_governance.EVAL_MATRIX_TEMPLATE, encoding="utf-8"
    )


def write_gate_route_fixture(
    process_root: Path,
    *,
    active_change: str = "CR-001",
    human_gate: str = "required",
) -> None:
    state = process_root / "state/STATE.current.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(
        json.dumps({"active_change": active_change, "pending_gate": None}) + "\n",
        encoding="utf-8",
    )
    cr_path = process_root / "changes/CR-001.md"
    route_path = process_root / "routes/CR-001.route-plan.json"
    cr_path.parent.mkdir(parents=True, exist_ok=True)
    route_path.parent.mkdir(parents=True, exist_ok=True)
    cr_path.write_text(
        """---
schema_version: 1
kind: cr
cr_id: CR-001
route_plan_ref: process/routes/CR-001.route-plan.json
---
""",
        encoding="utf-8",
    )
    route_path.write_text(
        json.dumps(
            {
                "decision": "PASS",
                "checkpoint_applicability": {
                    "CP2": {
                        "applies": True,
                        "decision": "REQUIRED",
                        "human_gate": human_gate,
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    item = {
        "id": "CR-001",
        "cr_type": "process",
        "title": "fixture",
        "lifecycle_status": "active",
        "readiness_status": "READY",
        "gate_status": "cp2_pending",
        "formal_cr_path": "process/changes/CR-001.md",
        "summary_ref": "process/changes/summaries/CR-001.summary.json",
    }
    semantic = {"schema_version": 1, "items": [item]}
    digest = hashlib.sha256(
        json.dumps(semantic, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    (process_root / "changes/CR-INDEX.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "2026-08-12T00:00:00Z",
                "semantic_digest": digest,
                "items": [item],
            }
        )
        + "\n",
        encoding="utf-8",
    )


class AdoptionReadinessTests(unittest.TestCase):
    def test_human_gate_dirs_are_on_demand_before_g2(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            process = root / "process"
            process.mkdir()

            item = adoption_readiness._human_gate_item(
                root,
                process,
                binding_aware=True,
            )

            self.assertEqual("WARN", item.status)
            self.assertIn("meta-flow cr bootstrap", item.next_action)
            self.assertNotIn("workspace bootstrap", item.next_action)
            self.assertTrue(any("on-demand" in message for message in item.messages))

    def test_human_gate_dirs_fail_when_active_route_requires_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            process = root / "process"
            process.mkdir()
            write_gate_route_fixture(process, human_gate="required")

            item = adoption_readiness._human_gate_item(
                root,
                process,
                binding_aware=True,
            )

            self.assertEqual("FAIL", item.status)
            self.assertTrue(any("requires a human gate" in message for message in item.messages))
            self.assertIn("meta-flow context build", item.next_action)
            self.assertIn("meta-flow check human-gate", item.next_action)

    def test_human_gate_dirs_warn_when_active_route_has_no_required_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            process = root / "process"
            process.mkdir()
            write_gate_route_fixture(process, human_gate="none")

            item = adoption_readiness._human_gate_item(
                root,
                process,
                binding_aware=True,
            )

            self.assertEqual("WARN", item.status)
            self.assertTrue(
                any("no applicable required human gate" in message for message in item.messages)
            )

    def test_human_gate_truth_conflict_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            process = root / "process"
            process.mkdir()
            write_gate_route_fixture(process, active_change="CR-002")

            item = adoption_readiness._human_gate_item(
                root,
                process,
                binding_aware=True,
            )

            self.assertEqual("FAIL", item.status)
            self.assertTrue(any("differ" in message for message in item.messages))

    def test_adoption_doctor_fails_on_cr_index_semantic_digest_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            process = root / "process"
            index = process / "changes/CR-INDEX.json"
            index.parent.mkdir(parents=True)
            index.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "generated_at": "2026-07-21T00:00:00Z",
                        "semantic_digest": "0" * 64,
                        "items": [],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            item = adoption_readiness._cr_tracking_item(root, process)

            self.assertEqual("FAIL", item.status)
            self.assertTrue(any("semantic_digest" in message for message in item.messages))

    def test_adoption_doctor_passes_for_bootstrapped_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            project_root = tmp_path / "target-project"
            artifact_root = tmp_path / "artifacts"
            project_root.mkdir()
            init_git(project_root)
            bootstrap_process_workspace(
                project_root,
                artifact_root,
                "target-project",
                capability=bootstrap_capability(project_root, artifact_root, "adoption-001"),
            )
            write_identity_fixture(project_root)
            write_quality_fixture(artifact_root / "process" / "target-project")

            items = adoption_readiness.collect_adoption_readiness(project_root)

            statuses = {item.item_id: item.status for item in items}
            self.assertEqual("PASS", statuses["workspace-route"])
            self.assertEqual("PASS", statuses["state-v2"])
            self.assertEqual("PASS", statuses["package-identity"])
            self.assertEqual("PASS", statuses["quality-governance"])
            self.assertEqual("PASS", statuses["workflow-ledgers"])
            self.assertEqual(0, adoption_readiness.run_adoption_doctor(project_root))

    def test_adoption_doctor_fails_when_process_route_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_root = Path(directory) / "target-project"
            project_root.mkdir()

            items = adoption_readiness.collect_adoption_readiness(project_root)

            statuses = {item.item_id: item.status for item in items}
            self.assertEqual("FAIL", statuses["workspace-route"])
            self.assertEqual("FAIL", statuses["state-v2"])
            self.assertEqual(1, adoption_readiness.run_adoption_doctor(project_root))

    def test_adoption_doctor_fails_when_package_identity_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            project_root = tmp_path / "target-project"
            artifact_root = tmp_path / "artifacts"
            project_root.mkdir()
            init_git(project_root)
            bootstrap_process_workspace(
                project_root,
                artifact_root,
                "target-project",
                capability=bootstrap_capability(project_root, artifact_root, "adoption-002"),
            )
            write_quality_fixture(artifact_root / "process" / "target-project")

            items = adoption_readiness.collect_adoption_readiness(project_root)

            package_item = next(item for item in items if item.item_id == "package-identity")
            self.assertEqual("FAIL", package_item.status)
            self.assertTrue(any("PACKAGE-IDENTITY missing" in message for message in package_item.messages))
            self.assertEqual(1, adoption_readiness.run_adoption_doctor(project_root))

    def test_legacy_adoption_doctor_does_not_enable_ordinary_quality_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            project_root = tmp_path / "target-project"
            artifact_root = tmp_path / "artifacts"
            project_root.mkdir()
            init_git(project_root)
            bootstrap_process_workspace(
                project_root,
                artifact_root,
                "target-project",
                capability=bootstrap_capability(
                    project_root, artifact_root, "adoption-003"
                ),
            )

            with self.assertRaisesRegex(
                ValueError, "vNext project is not initialized"
            ):
                quality_governance.write_default_quality_policies(project_root)


if __name__ == "__main__":
    unittest.main()
