from __future__ import annotations

import copy
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from test_cr072_package_compiler import valid_mapping

from meta_flow import package_cli
from meta_flow.workflow.closure_build import (
    CanonicalOperationRecordV1,
    ClosureGraphEdgeV1,
    ClosureRequestV1,
    build_affected_closure,
    build_operation_receipt,
    graph_from_package_plan,
    plan_operation_record_append,
)
from meta_flow.workflow.package_compiler import compile_package_plan
from meta_flow.workflow.package_plan import PackagePlanInputV1


def compiled_plan(mapping: dict[str, object] | None = None):
    return compile_package_plan(PackagePlanInputV1.from_mapping(mapping or valid_mapping()))


def closure_request(plan, *, changed_roots=None, base_sha="a" * 40, head_sha="b" * 40, prior="", edges=None):
    nodes, default_edges = graph_from_package_plan(plan)
    return ClosureRequestV1.from_mapping(
        {
            "schema_version": 1,
            "package_plan_digest": plan.semantic_digest,
            "base_sha": base_sha,
            "head_sha": head_sha,
            "changed_roots": changed_roots or ["meta_flow/workflow/story_1.py"],
            "graph_nodes": [item.as_dict() for item in nodes],
            "graph_edges": [item.as_dict() for item in (edges or default_edges)],
            "prior_fingerprint": prior,
        }
    )


class ClosureBuildTests(unittest.TestCase):
    def test_cl001_cl002_direct_transitive_and_unaffected_nodes(self) -> None:
        plan = compiled_plan()
        result = build_affected_closure(closure_request(plan), plan)

        self.assertEqual("PASS", result.decision)
        self.assertEqual(("path:meta_flow/workflow/story_1.py",), result.direct_nodes)
        self.assertIn("story:STORY-CR072-S01", result.transitive_nodes)
        self.assertIn("story:STORY-CR072-S06", result.transitive_nodes)
        self.assertNotIn("story:STORY-CR072-S02", result.build_set)
        self.assertEqual(0, result.mutation_count)

    def test_cl003_same_semantic_fingerprint_is_noop(self) -> None:
        plan = compiled_plan()
        first = build_affected_closure(closure_request(plan), plan)
        replay = build_affected_closure(
            closure_request(plan, prior=first.semantic_digest), plan
        )

        self.assertEqual(first.semantic_digest, replay.semantic_digest)
        self.assertTrue(replay.semantic_noop)
        self.assertEqual(0, replay.mutation_count)

    def test_cl004_unknown_changed_root_blocks(self) -> None:
        plan = compiled_plan()
        result = build_affected_closure(
            closure_request(plan, changed_roots=["outside/unregistered.py"]), plan
        )

        self.assertEqual("BLOCKED", result.decision)
        self.assertIn(
            "CLOSURE_CHANGED_ROOT_UNREGISTERED",
            {item.code for item in result.diagnostics},
        )

    def test_cl005_only_lowercase_literal_commit_oids_are_accepted(self) -> None:
        invalid_values = ["HEAD", "main", "abc1234", "A" * 40, "${BASE_SHA}", ""]
        plan = compiled_plan()

        for value in invalid_values:
            with self.subTest(value=value):
                result = build_affected_closure(
                    closure_request(plan, base_sha=value), plan
                )
                self.assertEqual("BLOCKED", result.decision)
                self.assertIn(
                    "INVALID_LITERAL_SHA", {item.code for item in result.diagnostics}
                )

    def test_cl006_cycle_is_stable_and_blocking(self) -> None:
        plan = compiled_plan()
        _nodes, edges = graph_from_package_plan(plan)
        cyclic = (*edges, ClosureGraphEdgeV1("story:STORY-CR072-S06", "story:STORY-CR072-S03", "runtime"))

        first = build_affected_closure(closure_request(plan, edges=cyclic), plan)
        second = build_affected_closure(closure_request(plan, edges=tuple(reversed(cyclic))), plan)

        self.assertIn("CLOSURE_GRAPH_CYCLE", {item.code for item in first.diagnostics})
        self.assertEqual(first.as_dict(), second.as_dict())

    def test_cl007_story_change_reaches_operation_feature_and_asset(self) -> None:
        mapping = valid_mapping()
        mapping["stories"][3]["shared_paths"].append("README.md")
        plan = compiled_plan(mapping)
        result = build_affected_closure(
            closure_request(plan, changed_roots=["meta_flow/workflow/story_4.py"]), plan
        )

        self.assertIn("operation:package.compile", result.affected_operations)
        self.assertIn("feature:cr072.package", result.affected_features)
        self.assertIn("path:README.md", result.affected_assets)

    def test_request_schema_and_plan_authority_fail_closed(self) -> None:
        mapping = valid_mapping()
        mapping["opaque"] = True
        with self.assertRaisesRegex(ValueError, "PACKAGE_INPUT_FIELDS_MISMATCH"):
            PackagePlanInputV1.from_mapping(mapping)

        plan = compiled_plan()
        request_mapping = {
            "schema_version": 1,
            "package_plan_digest": plan.semantic_digest,
            "base_sha": "a" * 40,
            "head_sha": "b" * 40,
            "changed_roots": ["meta_flow/workflow/story_1.py"],
            "graph_nodes": [],
            "graph_edges": [],
            "prior_fingerprint": "",
            "opaque": True,
        }
        with self.assertRaisesRegex(ValueError, "CLOSURE_REQUEST_FIELDS_MISMATCH"):
            ClosureRequestV1.from_mapping(request_mapping)

        wrong = closure_request(plan)
        wrong = ClosureRequestV1(
            **{**wrong.__dict__, "package_plan_digest": "0" * 64}
        )
        result = build_affected_closure(wrong, plan)
        self.assertIn(
            "PACKAGE_PLAN_NON_AUTHORITATIVE", {item.code for item in result.diagnostics}
        )

    def test_canonical_record_append_is_idempotent_and_conflict_safe(self) -> None:
        record = CanonicalOperationRecordV1.build(
            event_id="CLOSURE-001",
            operation_id="package.closure-build",
            input_digest="a" * 64,
            source_fingerprint="b" * 64,
            plan_digest="c" * 64,
            decision="PASS",
        )
        initial: list[dict[str, object]] = []

        append = plan_operation_record_append(initial, record)
        replay = plan_operation_record_append([record.as_dict()], record)
        changed = copy.deepcopy(record.as_dict())
        changed["record_digest"] = "d" * 64
        conflict = plan_operation_record_append([changed], record)

        self.assertEqual("APPEND", append["decision"])
        self.assertEqual("NO_CHANGE", replay["decision"])
        self.assertEqual("CONFLICT", conflict["decision"])
        self.assertEqual(initial, [])
        receipt = build_operation_receipt(
            record,
            ledger_preimage_digest="0" * 64,
            ledger_postimage_digest="1" * 64,
            projection_targets=["process/state/WORKFLOW-HEALTH.json"],
            transaction_id="txn-001",
        )
        self.assertEqual(64, len(receipt["receipt_digest"]))

    def test_public_cli_is_zero_write_and_uses_literal_arguments(self) -> None:
        value = PackagePlanInputV1.from_mapping(valid_mapping())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "user-owned.txt"
            marker.write_text("unchanged\n", encoding="utf-8")
            output = StringIO()
            with (
                patch.object(package_cli, "collect_package_plan_input", return_value=value),
                redirect_stdout(output),
            ):
                result = package_cli.main(
                    [
                        "closure-build",
                        "--cr",
                        "CR-072",
                        "--base-sha",
                        "a" * 40,
                        "--head-sha",
                        "b" * 40,
                        "--changed-root",
                        "meta_flow/workflow/story_1.py",
                        "--project-root",
                        str(root),
                        "--format",
                        "json",
                    ]
                )

            self.assertEqual(0, result)
            self.assertEqual(b"unchanged\n", marker.read_bytes())
            self.assertEqual("ClosureResultV1", json.loads(output.getvalue())["kind"])


if __name__ == "__main__":
    unittest.main()
