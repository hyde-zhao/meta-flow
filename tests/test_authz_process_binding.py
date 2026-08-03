from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from meta_flow.policies import authz


def _init_sibling_binding(root: Path, *, process_path: str = "meta-flow-process") -> tuple[Path, Path]:
    release = root / "meta-flow"
    process = root / "meta-flow-process"
    for repository in (release, process):
        repository.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=repository, check=True, capture_output=True)
    binding = release / ".meta-flow" / "workspace.yaml"
    binding.parent.mkdir()
    binding.write_text(
        "schema_version: 1\nlayout_version: independent-process-repo-v1\nworkflow_model: vnext\n"
        "project_id: fixture-project\nrepo_role: release\nroute_mode: sibling-binding\nprocess_repo:\n"
        f"  anchor: workspace_parent\n  relative_path: {process_path}\n",
        encoding="utf-8",
    )
    (process / ".meta-flow-process.yaml").write_text(
        "schema_version: 1\nlayout_version: independent-process-repo-v1\nworkflow_model: vnext\n"
        "project_id: fixture-project\nrepo_role: process\nroute_mode: sibling-binding\nrelease_repo:\n"
        "  anchor: workspace_parent\n  relative_path: meta-flow\n",
        encoding="utf-8",
    )
    (process / "PROJECT.yaml").write_text(
        "schema_version: 1\nproject_id: fixture-project\nname: Fixture\nstatus: active\n",
        encoding="utf-8",
    )
    return release, process


class AuthzProcessBindingTests(unittest.TestCase):
    def test_logical_artifact_reads_bound_process_and_rejects_release_process_decoy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process = _init_sibling_binding(Path(directory))
            logical = "process/changes/CR-064.md"
            process_copy = process / "changes/CR-064.md"
            process_copy.parent.mkdir(parents=True)
            process_copy.write_text("credential\n", encoding="utf-8")

            errors, _warnings = authz.check_artifact(release, Path(logical))

            self.assertEqual(
                ["artifact mentions high-risk surface but lacks authz policy ref: NO_CREDENTIAL_READ"],
                errors,
            )
            release_copy = release / logical
            release_copy.parent.mkdir(parents=True)
            release_copy.write_text("NO_CREDENTIAL_READ credential\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "release process entry to be absent"):
                authz.check_artifact(release, Path(logical))

    def test_logical_artifact_invalid_binding_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, _process = _init_sibling_binding(Path(directory), process_path="missing-process")

            with self.assertRaisesRegex(ValueError, "independent process route is not healthy"):
                authz.check_artifact(release, Path("process/changes/CR-064.md"))
            completed = subprocess.run(
                [
                    "meta-flow",
                    "policy",
                    "check",
                    "--project-root",
                    str(release),
                    "--artifact",
                    "process/changes/CR-064.md",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(2, completed.returncode)
            self.assertIn("Authz Policy Check: BLOCKED", completed.stdout)
            self.assertNotIn(str(_process.resolve()), completed.stdout)

    def test_logical_checkpoint_keeps_human_artifact_classification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process = _init_sibling_binding(Path(directory))
            checkpoint = process / "checkpoints/CP8-fixture.md"
            checkpoint.parent.mkdir(parents=True)
            checkpoint.write_text("NO_CREDENTIAL_READ 不授权读取凭据、.env、账户、token、secret、原始日志中的敏感字段。\n", encoding="utf-8")

            errors, _warnings = authz.check_artifact(release, Path("process/checkpoints/CP8-fixture.md"))

            self.assertEqual([], errors)


if __name__ == "__main__":
    unittest.main()
