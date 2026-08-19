from __future__ import annotations

import ast
import copy
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import FrozenInstanceError
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from meta_flow import cli, package_cli
from meta_flow.workflow.package_compiler import admit_compiled_plan, compile_package_plan
from meta_flow.workflow.package_plan import PackagePlanInputV1


def valid_mapping() -> dict[str, object]:
    stories: list[dict[str, object]] = []
    dependencies = {
        1: [(3, "runtime")],
        2: [(3, "runtime")],
        3: [],
        4: [(3, "contract")],
        5: [(4, "runtime")],
        6: [(1, "runtime"), (2, "runtime"), (5, "runtime")],
    }
    waves = {1: 1, 2: 1, 3: 0, 4: 2, 5: 3, 6: 4}
    for number in range(1, 7):
        story_id = f"STORY-CR072-S{number:02d}"
        core_path = f"meta_flow/workflow/story_{number}.py"
        stories.append(
            {
                "story_id": story_id,
                "work_id": (
                    "CR-072-WA-STABILIZATION-001"
                    if number in {1, 2}
                    else "CR-072-WB-GOVERNANCE-001"
                ),
                "priority": "P0",
                "requirement_priority": "P0",
                "wave": f"CR072-W{waves[number]}",
                "dependencies": [
                    {
                        "upstream": f"STORY-CR072-S{upstream:02d}",
                        "edge_type": edge_type,
                    }
                    for upstream, edge_type in dependencies[number]
                ],
                "primary_paths": [core_path],
                "shared_paths": ["meta_flow/cli.py"],
                "merge_owner": "STORY-CR072-S06",
                "feature_refs": ["cr072.package"],
                "production_entrypoints": [core_path],
                "reachable_core_paths": [core_path],
                "public_operation_ids": ["package.compile"] if number == 4 else [],
            }
        )
    operation = {
        "operation_id": "package.compile",
        "entry": ["meta-flow", "package", "compile"],
        "mutation_mode": "zero-write",
    }
    return {
        "schema_version": 1,
        "package_id": "0.6.1-release-package",
        "target_version": "0.6.1",
        "cr_id": "CR-072",
        "works": [
            {
                "work_id": "CR-072-WA-STABILIZATION-001",
                "release_value": "0.6.1",
            },
            {
                "work_id": "CR-072-WB-GOVERNANCE-001",
                "release_value": "0.6.1",
            },
        ],
        "stories": stories,
        "required_public_operations": [operation],
        "operation_registry": [operation],
        "asset_set": [
            "meta_flow-0.6.1-py3-none-any.whl",
            "meta_flow-0.6.1.tar.gz",
            "ProviderArtifactReceiptV1.json",
            "ProviderArtifactReceiptV1.digest-policy.json",
        ],
        "semver_bootstrap_ref": "docs/product/REQUIREMENTS.md#CP2-DQ-02-072",
        "source_objects": [
            {
                "ref": "process/DEVELOPMENT-PLAN.yaml",
                "bytes_digest": "a" * 64,
                "semantic_digest": "b" * 64,
            },
            {
                "ref": "delivery/doc/PUBLIC-OPERATION-CONTRACTS.yaml",
                "bytes_digest": "c" * 64,
                "semantic_digest": "d" * 64,
            },
        ],
    }


def compile_mapping(mapping: dict[str, object]):
    return compile_package_plan(PackagePlanInputV1.from_mapping(mapping))


def diagnostic_codes(result) -> set[str]:
    return {item.code for item in result.diagnostics}


class PackageCompilerTests(unittest.TestCase):
    def test_workflow_core_does_not_import_cli_state_writer_or_validation_kernel(self) -> None:
        project_root = Path(__file__).parents[1]
        forbidden = {
            "meta_flow.cli",
            "meta_flow.package_cli",
            "meta_flow.state",
            "meta_flow.work.validation_kernel",
        }
        imported: set[str] = set()
        for relative in (
            "meta_flow/workflow/package_plan.py",
            "meta_flow/workflow/package_compiler.py",
        ):
            tree = ast.parse((project_root / relative).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module)

        self.assertFalse(
            any(
                module == prefix or module.startswith(prefix + ".")
                for module in imported
                for prefix in forbidden
            ),
            imported,
        )

    def test_pc001_exact_package_compiles_to_authoritative_immutable_ir(self) -> None:
        result = compile_mapping(valid_mapping())

        self.assertEqual("PASS", result.decision)
        self.assertTrue(result.authoritative)
        self.assertEqual(0, result.mutation_count)
        self.assertEqual(2, len(result.works))
        self.assertEqual(6, len(result.stories))
        self.assertEqual((), admit_compiled_plan(result, expected_fingerprint=result.source_fingerprint))
        with self.assertRaises(FrozenInstanceError):
            result.decision = "BLOCKED"

    def test_pc002_and_pc003_missing_asset_and_work_cardinality_block(self) -> None:
        mapping = valid_mapping()
        mapping["asset_set"] = []
        mapping["works"] = list(mapping["works"])[:1]

        result = compile_mapping(mapping)

        self.assertEqual("BLOCKED", result.decision)
        self.assertEqual(
            {"PACKAGE_FIELD_MISSING", "WORK_CARDINALITY_INVALID"},
            diagnostic_codes(result),
        )
        self.assertEqual(0, result.mutation_count)

    def test_pc004_priority_conflict_names_story_owner(self) -> None:
        mapping = valid_mapping()
        mapping["stories"][0]["requirement_priority"] = "P1"

        result = compile_mapping(mapping)

        self.assertIn("STORY_PRIORITY_INVALID", diagnostic_codes(result))
        self.assertEqual("STORY-CR072-S01", result.diagnostics[0].subject_id)

    def test_pc005_primary_owner_overlap_blocks(self) -> None:
        mapping = valid_mapping()
        mapping["stories"][1]["primary_paths"] = list(
            mapping["stories"][0]["primary_paths"]
        )
        mapping["stories"][1]["reachable_core_paths"] = list(
            mapping["stories"][0]["primary_paths"]
        )

        result = compile_mapping(mapping)

        self.assertIn("FILE_OWNER_CONFLICT", diagnostic_codes(result))

    def test_pc006_shared_path_without_merge_owner_blocks(self) -> None:
        mapping = valid_mapping()
        mapping["stories"][0]["merge_owner"] = ""

        result = compile_mapping(mapping)

        self.assertIn("FILE_OWNER_CONFLICT", diagnostic_codes(result))

    def test_pc007_unregistered_public_operation_blocks(self) -> None:
        mapping = valid_mapping()
        mapping["operation_registry"] = []

        result = compile_mapping(mapping)

        self.assertIn("PUBLIC_OPERATION_UNREGISTERED", diagnostic_codes(result))

    def test_pc008_helper_only_story_blocks(self) -> None:
        mapping = valid_mapping()
        mapping["stories"][3]["primary_paths"] = ["tests/helpers/package_compiler.py"]
        mapping["stories"][3]["production_entrypoints"] = [
            "tests/helpers/package_compiler.py"
        ]
        mapping["stories"][3]["reachable_core_paths"] = [
            "tests/helpers/package_compiler.py"
        ]

        result = compile_mapping(mapping)

        self.assertIn("PRODUCTION_ENTRYPOINT_UNREACHABLE", diagnostic_codes(result))

    def test_pc009_invalid_endpoint_cycle_and_same_wave_are_deterministic(self) -> None:
        cases = []
        missing = valid_mapping()
        missing["stories"][3]["dependencies"] = [
            {"upstream": "STORY-CR072-S99", "edge_type": "contract"}
        ]
        cases.append(missing)
        cycle = valid_mapping()
        cycle["stories"][2]["dependencies"] = [
            {"upstream": "STORY-CR072-S06", "edge_type": "runtime"}
        ]
        cases.append(cycle)
        same_wave = valid_mapping()
        same_wave["stories"][1]["dependencies"] = [
            {"upstream": "STORY-CR072-S01", "edge_type": "runtime"}
        ]
        cases.append(same_wave)

        for mapping in cases:
            with self.subTest(mapping=mapping["stories"]):
                first = compile_mapping(mapping)
                second = compile_mapping(copy.deepcopy(mapping))
                self.assertIn("PACKAGE_DEPENDENCY_INVALID", diagnostic_codes(first))
                self.assertEqual(first.as_dict(), second.as_dict())

    def test_pc010_serialized_or_handwritten_plan_is_not_authoritative(self) -> None:
        result = compile_mapping(valid_mapping())
        reloaded = json.loads(json.dumps(result.as_dict()))

        self.assertEqual(
            ("HANDWRITTEN_PLAN_NON_AUTHORITATIVE",),
            admit_compiled_plan(reloaded, expected_fingerprint=result.source_fingerprint),
        )

    def test_pc011_input_reordering_does_not_change_semantic_digest(self) -> None:
        first_mapping = valid_mapping()
        second_mapping = copy.deepcopy(first_mapping)
        for field in (
            "works",
            "stories",
            "required_public_operations",
            "operation_registry",
            "source_objects",
        ):
            second_mapping[field] = list(reversed(second_mapping[field]))
        for story in second_mapping["stories"]:
            story["primary_paths"] = list(reversed(story["primary_paths"]))
            story["shared_paths"] = list(reversed(story["shared_paths"]))

        first = compile_mapping(first_mapping)
        second = compile_mapping(second_mapping)

        self.assertEqual(first.semantic_digest, second.semantic_digest)
        self.assertEqual(first.source_fingerprint, second.source_fingerprint)

    def test_pc012_unknown_field_and_ref_escape_fail_closed(self) -> None:
        unknown = valid_mapping()
        unknown["opaque_extra"] = True
        with self.assertRaisesRegex(ValueError, "PACKAGE_INPUT_FIELDS_MISMATCH"):
            PackagePlanInputV1.from_mapping(unknown)

        escaped = valid_mapping()
        escaped["source_objects"][0]["ref"] = "process/../secret"
        with self.assertRaisesRegex(ValueError, "PACKAGE_SOURCE_REF_INVALID"):
            PackagePlanInputV1.from_mapping(escaped)

    def test_root_cli_reaches_compile_adapter_and_remains_zero_write(self) -> None:
        value = PackagePlanInputV1.from_mapping(valid_mapping())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "user-owned.txt"
            marker.write_text("unchanged\n", encoding="utf-8")
            before = marker.read_bytes()
            output = StringIO()
            with (
                patch.object(sys, "argv", ["meta-flow", "package", "compile", "--cr", "CR-072"]),
                patch.object(cli, "_guard_provider_mutation"),
                patch.object(package_cli, "collect_package_plan_input", return_value=value),
                redirect_stdout(output),
            ):
                with self.assertRaises(SystemExit) as raised:
                    cli._dispatch_main()

            self.assertEqual(0, raised.exception.code)
            self.assertEqual(before, marker.read_bytes())
            self.assertEqual("PackagePlanIRV1", json.loads(output.getvalue())["kind"])


if __name__ == "__main__":
    unittest.main()
