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


def write_v2_registry(root: Path) -> Path:
    write_feature_design(root)
    path = root / "docs" / "design" / "FEATURE-REGISTRY.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "features": [
                    {
                        "id": "FEAT-PG-004",
                        "feature_id": "FEAT-PG-004",
                        "title": "Capability / Feature Registry",
                        "product_domain": "Project Governance",
                        "capability": "Registry-backed refs",
                        "owner_context": "project-governance",
                        "status": "active",
                        "risk_profile": "standard-code",
                        "design_doc_policy": "full-design",
                        "design_doc": "docs/features/data-manifest/DESIGN.md",
                        "test_plan": "docs/features/data-manifest/TEST-PLAN.md",
                        "tasks_doc": "docs/features/data-manifest/TASKS.md",
                        "module_paths": ["meta_flow/design/feature_registry.py"],
                        "public_api": ["meta_flow.design.feature_registry.resolve_ref"],
                        "forbidden_dependencies": [],
                        "authz_policy_refs": [],
                        "aliases": ["capability-feature-registry"],
                        "deprecated_by": "",
                        "source_refs": ["CR037-S07"],
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


def write_capability_registry(root: Path, *, alias: str = "registry refs", status: str = "active") -> Path:
    path = root / "docs" / "design" / "CAPABILITY-REGISTRY.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "capabilities": [
                    {
                        "id": "CAP-PG-REGISTRY-REFS",
                        "name": "Registry-backed refs",
                        "domain": "project-governance",
                        "status": status,
                        "owner_context": "project-governance",
                        "feature_refs": ["FEAT-PG-004"],
                        "aliases": [alias],
                        "deprecated_by": "CAP-PG-REGISTRY-REFS-V2" if status == "deprecated" else "",
                        "source_refs": ["CR037-S07"],
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

    def test_feature_registry_v2_supports_id_aliases_and_source_refs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_v2_registry(root)

            errors, warnings = feature_registry.validate_registry(root)
            result = feature_registry.resolve_ref(root, "capability-feature-registry", kind="feature")

            self.assertEqual([], errors)
            self.assertEqual([], warnings)
            self.assertEqual("resolved", result.status)
            self.assertEqual("FEAT-PG-004", result.canonical_id)
            self.assertEqual("REF_RESOLVED", result.code)
            self.assertEqual("INFO", result.severity)

    def test_capability_registry_check_validates_refs_and_sensitive_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_v2_registry(root)
            write_capability_registry(root)

            errors, _warnings = feature_registry.validate_registry(root, include_capabilities=True)
            self.assertEqual([], errors)

            capability_path = root / "docs" / "design" / "CAPABILITY-REGISTRY.yaml"
            registry = json.loads(capability_path.read_text(encoding="utf-8"))
            registry["capabilities"][0]["source_refs"].append("private_token_should_not_be_here")
            capability_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            errors, _warnings = feature_registry.validate_registry(root, include_capabilities=True)
            self.assertTrue(any("E_SENSITIVE_VALUE CAP-PG-REGISTRY-REFS" in error for error in errors))

    def test_resolver_returns_unresolved_deprecated_and_conflict_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_v2_registry(root)
            write_capability_registry(root, status="deprecated")

            unresolved = feature_registry.resolve_ref(root, "CAP-PG-UNKNOWN", kind="capability")
            deprecated_audit = feature_registry.resolve_ref(root, "CAP-PG-REGISTRY-REFS", kind="capability")
            deprecated_enforce = feature_registry.resolve_ref(
                root, "CAP-PG-REGISTRY-REFS", kind="capability", mode="enforce"
            )

            self.assertEqual("unresolved", unresolved.status)
            self.assertEqual("E_REF_UNRESOLVED", unresolved.code)
            self.assertEqual("BLOCKED", unresolved.severity)
            self.assertEqual("deprecated", deprecated_audit.status)
            self.assertEqual("WARN", deprecated_audit.severity)
            self.assertEqual("ERROR", deprecated_enforce.severity)
            self.assertEqual("CAP-PG-REGISTRY-REFS-V2", deprecated_enforce.deprecated_by)

            capability_path = root / "docs" / "design" / "CAPABILITY-REGISTRY.yaml"
            registry = json.loads(capability_path.read_text(encoding="utf-8"))
            registry["capabilities"].append(
                {
                    "id": "CAP-PG-REGISTRY-OTHER",
                    "name": "Other Registry",
                    "domain": "project-governance",
                    "status": "active",
                    "owner_context": "project-governance",
                    "feature_refs": ["FEAT-PG-004"],
                    "aliases": ["registry refs"],
                    "deprecated_by": "",
                    "source_refs": ["CR037-S07"],
                }
            )
            capability_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            conflict = feature_registry.resolve_ref(root, "registry refs", kind="capability")
            self.assertEqual("conflict", conflict.status)
            self.assertEqual("E_REF_CONFLICT", conflict.code)
            self.assertEqual("ERROR", conflict.severity)
            self.assertEqual({"CAP-PG-REGISTRY-OTHER", "CAP-PG-REGISTRY-REFS"}, set(conflict.candidates))

    def test_candidate_report_does_not_create_canonical_capability_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_v2_registry(root)
            write_capability_registry(root)

            report = feature_registry.build_candidate_report(
                root,
                ["CAP-PG-UNKNOWN", "CAP-PG-UNKNOWN", "CAP-PG-REGISTRY-REFS"],
                kind="capability",
                source_ref="synthetic-consumer",
            )
            registry = json.loads((root / "docs" / "design" / "CAPABILITY-REGISTRY.yaml").read_text(encoding="utf-8"))

            self.assertFalse(report["canonical_registry_written"])
            self.assertEqual([{"input_ref": "CAP-PG-UNKNOWN", "kind": "capability", "source_ref": "synthetic-consumer", "reason": "E_REF_UNRESOLVED", "status": "candidate-only"}], report["candidates"])
            self.assertEqual(["CAP-PG-REGISTRY-REFS"], [item["id"] for item in registry["capabilities"]])

    def test_synthetic_downstream_consumers_must_use_resolver_results(self) -> None:
        def synthetic_impact_consumer(root: Path, capability_refs: list[str]) -> dict[str, list[dict[str, str]]]:
            payload = feature_registry.resolve_refs(root, capability_refs, kind="capability", mode="enforce")
            normalized: list[dict[str, str]] = []
            blocked: list[dict[str, str]] = []
            for result in payload["results"]:
                if result["status"] == "resolved":
                    normalized.append({"capability_ref": result["canonical_id"]})
                else:
                    blocked.append(
                        {
                            "input_ref": result["input_ref"],
                            "code": result["code"],
                            "severity": result["severity"],
                        }
                    )
            return {"normalized": normalized, "blocked": blocked}

        def synthetic_roadmap_consumer(root: Path, capability_ref: str) -> dict[str, str]:
            result = feature_registry.resolve_ref(root, capability_ref, kind="capability", mode="enforce")
            if result.status != "resolved":
                return {"status": "blocked", "code": result.code, "input_ref": result.input_ref}
            return {"status": "ready", "capability_ref": result.canonical_id}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_v2_registry(root)
            write_capability_registry(root)

            impact = synthetic_impact_consumer(root, ["registry refs", "CAP-PG-FREE-TEXT"])
            roadmap = synthetic_roadmap_consumer(root, "unregistered free string")

            self.assertEqual([{"capability_ref": "CAP-PG-REGISTRY-REFS"}], impact["normalized"])
            self.assertEqual(
                [{"input_ref": "CAP-PG-FREE-TEXT", "code": "E_REF_UNRESOLVED", "severity": "BLOCKED"}],
                impact["blocked"],
            )
            self.assertEqual(
                {"status": "blocked", "code": "E_REF_UNRESOLVED", "input_ref": "unregistered free string"},
                roadmap,
            )

    def test_feature_cli_check_and_resolve_support_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_v2_registry(root)
            write_capability_registry(root)

            check_output = StringIO()
            with redirect_stdout(check_output):
                check_code = feature_registry.main(["check", "--project-root", str(root), "--include-capabilities"])
            resolve_output = StringIO()
            with redirect_stdout(resolve_output):
                resolve_code = feature_registry.main(
                    ["resolve", "--project-root", str(root), "--kind", "capability", "--ref", "registry refs"]
                )

            self.assertEqual(0, check_code)
            self.assertIn("Feature Registry Check: OK", check_output.getvalue())
            self.assertEqual(0, resolve_code)
            self.assertIn("capability registry refs: resolved REF_RESOLVED INFO -> CAP-PG-REGISTRY-REFS", resolve_output.getvalue())


if __name__ == "__main__":
    unittest.main()
