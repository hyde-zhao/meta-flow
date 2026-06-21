from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from meta_flow.design import product_governance


def write_capability_status(root: Path, *, status: str = "future-slot", runtime_authorized: bool = False) -> Path:
    path = root / "docs" / "design" / "CAPABILITY-STATUS.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "capabilities": {
                    "qmt_terminal_direct": {
                        "status": status,
                        "implemented_target": status == "implemented",
                        "runtime_authorized": runtime_authorized,
                        "docs_claim_level": "guarded" if status != "implemented" else "implemented",
                        "test_scope": "fixture",
                        "aliases": ["QMT direct"],
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def write_concept_owners(root: Path) -> Path:
    path = root / "docs" / "design" / "CONCEPT-OWNERS.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "concept_owners": {
                    "data_contracts": {
                        "owner": "quant_lab.data.contracts",
                        "conflict_keys": ["data_contracts", "manifest_contract"],
                        "legacy_aliases": ["engine.contracts", "market_data.contracts"],
                        "forbidden_aliases": [],
                    },
                    "trading_runtime": {
                        "owner": "quant_lab.trading",
                        "conflict_keys": ["trading_runtime"],
                        "legacy_aliases": [],
                        "forbidden_aliases": ["engine.paper_simulation"],
                    },
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def write_package_identity(root: Path, *, repo_name: str = "quant-lab") -> Path:
    path = root / "docs" / "design" / "PACKAGE-IDENTITY.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "product_name": "quant-lab",
                "repo_name": repo_name,
                "python_import": "quant_lab",
                "cli_name": "qlab",
                "legacy_aliases": ["local-backtest"],
                "package_mode": True,
                "public_api_files": ["quant_lab/__init__.py"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


class CapabilityGovernanceTests(unittest.TestCase):
    def test_capability_init_writes_default_registry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            exit_code = product_governance.capability_main(["init", "--project-root", str(root)])

            self.assertEqual(0, exit_code)
            self.assertTrue((root / "docs" / "design" / "CAPABILITY-STATUS.yaml").is_file())

    def test_capability_check_rejects_future_capability_overclaim(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_capability_status(root, status="future-slot")
            readme = root / "README.md"
            readme.write_text("QMT direct is implemented and available.\n", encoding="utf-8")

            errors, _warnings = product_governance.check_capability_claims(root, readme)

            self.assertTrue(any("overclaims non-implemented capability qmt_terminal_direct" in error for error in errors))

    def test_capability_check_rejects_runtime_ready_without_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_capability_status(root, status="offline-fixture-only", runtime_authorized=False)
            readme = root / "README.md"
            readme.write_text("QMT direct is runtime-ready.\n", encoding="utf-8")

            errors, _warnings = product_governance.check_capability_claims(root, readme)

            self.assertTrue(any("claims runtime-ready capability without authorization" in error for error in errors))


class ConceptGovernanceTests(unittest.TestCase):
    def test_concept_init_writes_default_registry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            exit_code = product_governance.concept_main(["init", "--project-root", str(root)])

            self.assertEqual(0, exit_code)
            self.assertTrue((root / "docs" / "design" / "CONCEPT-OWNERS.yaml").is_file())

    def test_concept_overlap_warns_on_legacy_alias(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_concept_owners(root)

            errors, warnings = product_governance.check_concept_overlap(root, ["quant_lab/engine/contracts.py"])

            self.assertEqual([], errors)
            self.assertTrue(any("touches legacy alias for data_contracts" in warning for warning in warnings))

    def test_concept_overlap_rejects_forbidden_alias(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_concept_owners(root)

            errors, _warnings = product_governance.check_concept_overlap(root, ["quant_lab/engine/paper_simulation.py"])

            self.assertIn(
                "quant_lab/engine/paper_simulation.py touches forbidden alias for trading_runtime; owner is quant_lab.trading",
                errors,
            )

    def test_concept_owner_check_rejects_duplicate_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = write_concept_owners(root)
            data = json.loads(path.read_text(encoding="utf-8"))
            data["concept_owners"]["source_registry"] = {
                "owner": "quant_lab.data.source_registry",
                "legacy_aliases": ["engine.contracts"],
                "forbidden_aliases": [],
            }
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            errors = product_governance.validate_concept_owners(root)

            self.assertTrue(any("alias assigned to multiple concepts: engine.contracts" in error for error in errors))

    def test_concept_owner_check_rejects_duplicate_conflict_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = write_concept_owners(root)
            data = json.loads(path.read_text(encoding="utf-8"))
            data["concept_owners"]["source_registry"] = {
                "owner": "quant_lab.data.source_registry",
                "conflict_keys": ["manifest_contract"],
                "legacy_aliases": [],
                "forbidden_aliases": [],
            }
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            errors = product_governance.validate_concept_owners(root)

            self.assertTrue(any("conflict_key assigned to multiple concepts: manifest_contract" in error for error in errors))


class PackageIdentityTests(unittest.TestCase):
    def test_identity_init_writes_default_registry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            exit_code = product_governance.identity_main(["init", "--project-root", str(root)])

            self.assertEqual(0, exit_code)
            self.assertTrue((root / "docs" / "design" / "PACKAGE-IDENTITY.yaml").is_file())

    def test_package_identity_passes_for_matching_pyproject_and_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_package_identity(root)
            (root / "quant_lab").mkdir()
            (root / "quant_lab" / "__init__.py").write_text("", encoding="utf-8")
            (root / "README.md").write_text("# quant-lab\n", encoding="utf-8")
            (root / "pyproject.toml").write_text(
                '[project]\nname = "quant-lab"\n[project.scripts]\nqlab = "quant_lab.cli:main"\n',
                encoding="utf-8",
            )

            errors, warnings = product_governance.validate_package_identity(root)

            self.assertEqual([], errors)
            self.assertEqual([], warnings)

    def test_package_identity_rejects_name_and_public_api_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_package_identity(root, repo_name="quant-lab")
            (root / "README.md").write_text("# quant-lab\n", encoding="utf-8")
            (root / "pyproject.toml").write_text('[project]\nname = "local-backtest"\n', encoding="utf-8")

            errors, _warnings = product_governance.validate_package_identity(root)

            self.assertIn("pyproject project.name=local-backtest does not match repo_name=quant-lab", errors)
            self.assertIn("python_import package path missing: quant_lab", errors)
            self.assertIn("public_api_file missing: quant_lab/__init__.py", errors)

    def test_check_alias_package_identity_uses_identity_checker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_package_identity(root)
            (root / "quant_lab").mkdir()
            (root / "quant_lab" / "__init__.py").write_text("", encoding="utf-8")
            (root / "README.md").write_text("# quant-lab\n", encoding="utf-8")
            (root / "pyproject.toml").write_text(
                '[project]\nname = "quant-lab"\n[project.scripts]\nqlab = "quant_lab.cli:main"\n',
                encoding="utf-8",
            )

            output = StringIO()
            with redirect_stdout(output):
                exit_code = product_governance.identity_main(["check", "--project-root", str(root)])

            self.assertEqual(0, exit_code)
            self.assertIn("Package Identity Check: OK", output.getvalue())


if __name__ == "__main__":
    unittest.main()
