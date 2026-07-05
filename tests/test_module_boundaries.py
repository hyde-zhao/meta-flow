from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from meta_flow.design import module_boundaries


def write_boundaries(root: Path) -> Path:
    path = root / "docs" / "design" / "MODULE-BOUNDARIES.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "module_boundaries": {
                    "core": {
                        "package": "quant_lab.core",
                        "paths": ["quant_lab/core"],
                        "may_import": [],
                        "must_not_import": ["quant_lab.data", "quant_lab.trading"],
                        "risk_profile": "standard-code",
                    },
                    "data": {
                        "package": "quant_lab.data",
                        "paths": ["quant_lab/data"],
                        "may_import": ["quant_lab.core"],
                        "must_not_import": ["quant_lab.research", "quant_lab.trading"],
                        "risk_profile": "standard-code",
                    },
                    "research": {
                        "package": "quant_lab.research",
                        "paths": ["quant_lab/research"],
                        "may_import": ["quant_lab.core", "quant_lab.data"],
                        "must_not_import": ["quant_lab.trading"],
                        "risk_profile": "standard-code",
                    },
                    "adapters": {
                        "package": "quant_lab.adapters",
                        "paths": ["quant_lab/adapters"],
                        "may_import": ["quant_lab.core"],
                        "must_not_import": [],
                        "risk_profile": "runtime-high-risk",
                    },
                    "trading": {
                        "package": "quant_lab.trading",
                        "paths": ["quant_lab/trading"],
                        "may_import": ["quant_lab.core"],
                        "must_not_import": ["quant_lab.research"],
                        "risk_profile": "runtime-high-risk",
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


def write_py(root: Path, rel_path: str, text: str) -> Path:
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class ModuleBoundaryTests(unittest.TestCase):
    def test_init_writes_default_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            exit_code = module_boundaries.main(["init", "--project-root", str(root)])

            self.assertEqual(0, exit_code)
            self.assertTrue((root / "docs" / "design" / "MODULE-BOUNDARIES.yaml").is_file())

    def test_check_boundaries_passes_valid_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_boundaries(root)

            output = StringIO()
            with redirect_stdout(output):
                exit_code = module_boundaries.main(["check-boundaries", "--project-root", str(root)])

            self.assertEqual(0, exit_code)
            self.assertIn("Module Boundary Check: OK", output.getvalue())

    def test_check_boundaries_rejects_missing_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = write_boundaries(root)
            data = json.loads(path.read_text(encoding="utf-8"))
            data["module_boundaries"]["core"]["paths"] = []
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            errors = module_boundaries.validate_boundaries(root)

            self.assertIn("core paths must be a non-empty list", errors)

    def test_import_check_rejects_forbidden_import(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_boundaries(root)
            write_py(root, "quant_lab/core/main.py", "from quant_lab.data.reader import Reader\n")

            errors, _warnings = module_boundaries.check_imports(root)

            self.assertTrue(any("core must not import quant_lab.data.reader" in error for error in errors))

    def test_import_check_allows_declared_direction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_boundaries(root)
            write_py(root, "quant_lab/data/reader.py", "from quant_lab.core.ids import Symbol\n")

            errors, _warnings = module_boundaries.check_imports(root)

            self.assertEqual([], errors)

    def test_architecture_fitness_runs_import_scan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_boundaries(root)
            write_py(root, "quant_lab/research/backtest.py", "import quant_lab.trading.runtime\n")

            errors, _warnings = module_boundaries.check_architecture_fitness(root)

            self.assertTrue(any("research must not import quant_lab.trading.runtime" in error for error in errors))

    def test_risk_rings_report_runtime_profile_for_trading_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_boundaries(root)

            errors, _warnings, details = module_boundaries.check_risk_rings(
                root,
                changed_files=["quant_lab/trading/order.py"],
            )

            self.assertEqual([], errors)
            self.assertEqual("runtime-high-risk", details["classification"]["profile"])
            self.assertIn("trading", details["touched_boundaries"])

    def test_risk_rings_reject_runtime_boundary_without_high_risk_classification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = write_boundaries(root)
            data = json.loads(path.read_text(encoding="utf-8"))
            data["module_boundaries"]["runtime_ext"] = {
                "package": "quant_lab.runtime_ext",
                "paths": ["quant_lab/runtime_ext"],
                "may_import": ["quant_lab.core"],
                "must_not_import": [],
                "risk_profile": "runtime-high-risk",
            }
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            errors, _warnings, details = module_boundaries.check_risk_rings(
                root,
                changed_files=["quant_lab/runtime_ext/local.py"],
            )

            self.assertEqual("standard-lite", details["classification"]["profile"])
            self.assertIn("touching runtime-high-risk boundary requires runtime-high-risk profile: runtime_ext", errors)

    def test_check_alias_imports_uses_module_checker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_boundaries(root)
            write_py(root, "quant_lab/data/reader.py", "from quant_lab.core.ids import Symbol\n")

            output = StringIO()
            with redirect_stdout(output):
                exit_code = module_boundaries.main(["check-imports", "--project-root", str(root)])

            self.assertEqual(0, exit_code)
            self.assertIn("Import Boundary Check: OK", output.getvalue())


if __name__ == "__main__":
    unittest.main()
