from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from meta_flow.checks import adoption_readiness
from meta_flow.checks import quality_governance
from meta_flow.design import product_governance
from meta_flow.workspace.routing import bootstrap_process_workspace


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


class AdoptionReadinessTests(unittest.TestCase):
    def test_adoption_doctor_passes_for_bootstrapped_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            project_root = tmp_path / "target-project"
            artifact_root = tmp_path / "artifacts"
            project_root.mkdir()
            bootstrap_process_workspace(project_root, artifact_root, "target-project")
            write_identity_fixture(project_root)
            quality_governance.write_default_quality_policies(project_root)

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
            bootstrap_process_workspace(project_root, artifact_root, "target-project")
            quality_governance.write_default_quality_policies(project_root)

            items = adoption_readiness.collect_adoption_readiness(project_root)

            package_item = next(item for item in items if item.item_id == "package-identity")
            self.assertEqual("FAIL", package_item.status)
            self.assertTrue(any("PACKAGE-IDENTITY missing" in message for message in package_item.messages))
            self.assertEqual(1, adoption_readiness.run_adoption_doctor(project_root))


if __name__ == "__main__":
    unittest.main()
