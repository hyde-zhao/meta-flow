from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from meta_flow.design import feature_registry


def write_feature_design(root: Path, feature_slug: str = "data-manifest") -> Path:
    feature_dir = root / "docs" / "features" / feature_slug
    feature_dir.mkdir(parents=True, exist_ok=True)
    design = feature_dir / "DESIGN.md"
    design.write_text("# Data Manifest\n\nFeature design.\n", encoding="utf-8")
    (feature_dir / "TEST-PLAN.md").write_text("# Test Plan\n", encoding="utf-8")
    (feature_dir / "TASKS.md").write_text("# Tasks\n", encoding="utf-8")
    return design


def write_registry(root: Path, *, risk_profile: str = "standard-code", module_paths: list[str] | None = None) -> Path:
    paths = ["quant_lab/data/manifest"] if module_paths is None else module_paths
    path = root / "docs" / "design" / "FEATURE-REGISTRY.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "features": [
                    {
                        "feature_id": "data.manifest",
                        "title": "Data Manifest",
                        "product_domain": "Data Platform",
                        "capability": "Market Data Contract",
                        "owner_context": "data",
                        "status": "implemented",
                        "risk_profile": risk_profile,
                        "design_doc_policy": "full-design",
                        "design_doc": "docs/features/data-manifest/DESIGN.md",
                        "test_plan": "docs/features/data-manifest/TEST-PLAN.md",
                        "tasks_doc": "docs/features/data-manifest/TASKS.md",
                        "module_paths": paths,
                        "public_api": ["quant_lab.data.Manifest"],
                        "forbidden_dependencies": ["quant_lab.trading"],
                        "authz_policy_refs": [],
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def write_story(root: Path, *, feature_ref: str = "data.manifest", lld_policy: str = "technical-note") -> Path:
    path = root / "process" / "stories" / "STORY-CR123-S01.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
story_id: STORY-CR123-S01
feature_refs:
  - {feature_ref}
feature_design_refs:
  - docs/features/data-manifest/DESIGN.md
lld_policy: {lld_policy}
risk_profile: standard-code
---

# Story
""",
        encoding="utf-8",
    )
    return path


class FeatureRegistryTests(unittest.TestCase):
    def test_build_registry_from_docs_features(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_feature_design(root)

            exit_code = feature_registry.main(["build", "--project-root", str(root)])

            self.assertEqual(0, exit_code)
            registry = json.loads((root / "docs" / "design" / "FEATURE-REGISTRY.yaml").read_text(encoding="utf-8"))
            self.assertEqual("data.manifest", registry["features"][0]["feature_id"])
            self.assertEqual("Data Manifest", registry["features"][0]["title"])

    def test_check_passes_for_valid_registry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_feature_design(root)
            write_registry(root)

            output = StringIO()
            with redirect_stdout(output):
                exit_code = feature_registry.main(["check", "--project-root", str(root)])

            self.assertEqual(0, exit_code)
            self.assertIn("Feature Registry Check: OK", output.getvalue())

    def test_check_rejects_missing_owner_and_module_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_feature_design(root)
            write_registry(root, module_paths=[])
            registry_path = root / "docs" / "design" / "FEATURE-REGISTRY.yaml"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["features"][0]["owner_context"] = ""
            registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            errors, _warnings = feature_registry.validate_registry(root)

            self.assertIn("data.manifest missing owner_context", errors)
            self.assertIn("data.manifest module_paths must be a non-empty list", errors)

    def test_trace_passes_for_story_bound_to_feature(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_feature_design(root)
            write_registry(root)
            write_story(root)

            output = StringIO()
            with redirect_stdout(output):
                exit_code = feature_registry.main(["trace", "--project-root", str(root)])

            self.assertEqual(0, exit_code)
            self.assertIn("Story Feature Trace Check: OK", output.getvalue())
            self.assertIn("data.manifest: STORY-CR123-S01", output.getvalue())

    def test_trace_rejects_unknown_feature_ref(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_feature_design(root)
            write_registry(root)
            write_story(root, feature_ref="research.backtest")

            errors, _warnings, _traces = feature_registry.trace_stories(root)

            self.assertIn("process/stories/STORY-CR123-S01.md references unknown feature_id: research.backtest", errors)

    def test_runtime_high_risk_feature_requires_full_lld(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_feature_design(root)
            write_registry(root, risk_profile="runtime-high-risk")
            write_story(root, lld_policy="technical-note")

            errors, _warnings, _traces = feature_registry.trace_stories(root)

            self.assertIn("process/stories/STORY-CR123-S01.md runtime-high-risk Story must use lld_policy=full-lld", errors)

    def test_architecture_major_feature_requires_product_domain_and_capability(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_feature_design(root)
            write_registry(root, risk_profile="architecture-major")
            registry_path = root / "docs" / "design" / "FEATURE-REGISTRY.yaml"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["features"][0]["product_domain"] = ""
            registry["features"][0]["capability"] = ""
            registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            errors, _warnings = feature_registry.validate_registry(root)

            self.assertIn("data.manifest architecture-major requires product_domain", errors)
            self.assertIn("data.manifest architecture-major requires capability", errors)

    def test_registry_only_feature_does_not_require_design_doc(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_feature_design(root)
            write_registry(root)
            registry_path = root / "docs" / "design" / "FEATURE-REGISTRY.yaml"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["features"][0]["design_doc_policy"] = "registry-only"
            registry["features"][0]["design_doc"] = ""
            registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            errors, _warnings = feature_registry.validate_registry(root)

            self.assertEqual([], errors)

    def test_check_alias_design_ownership_uses_feature_registry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_feature_design(root)
            write_registry(root)

            output = StringIO()
            with redirect_stdout(output):
                exit_code = feature_registry.main(["check", "--project-root", str(root)])

            self.assertEqual(0, exit_code)
            self.assertIn("Feature Registry Check: OK", output.getvalue())


if __name__ == "__main__":
    unittest.main()
