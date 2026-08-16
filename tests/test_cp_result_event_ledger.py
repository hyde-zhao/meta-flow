from __future__ import annotations

import ast
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from meta_flow.checks import cp_result
from meta_flow.state import current, event_ledger, ledger_migration
from meta_flow.work import usage
from meta_flow.work.io_metrics import IOMetrics
from meta_flow.work.read_context import OperationReadContext

GATE_SEMANTIC_REGISTRY = {
    "meta_flow/state/event_ledger.py": "producer-validator-projector-owner",
    "meta_flow/state/dispatch_correction.py": "correction-transaction-writer-source-binding",
    "meta_flow/checks/cr_tracking.py": "passage-consumer",
    "meta_flow/checks/state_transition.py": "passage-consumer",
    "meta_flow/repository/publisher.py": "passage-consumer",
    "meta_flow/work/usage.py": "count-only-exception",
    "meta_flow/workflow/cr_status_sync.py": "transport-adapter",
    "meta_flow/policies/route_plan.py": "mutation-reference-only",
    "meta_flow/policies/c0_cutover.py": "mutation-reference-only",
    "meta_flow/policies/failure_routing.py": "metadata-reference-only",
    "meta_flow/state/current.py": "inventory-reference-only",
    "meta_flow/workflow/terminal_lineage.py": "inventory-reference-only",
    "meta_flow/cli.py": "optional-public-adapter",
    "meta_flow/state/checkpoint_projection.py": "adjacent-owner-boundary",
}
GATE_OPTIONAL_REGISTERED_ONLY = {
    "meta_flow/cli.py",
    "meta_flow/state/checkpoint_projection.py",
}


def test_event_ledger_loader_reuses_one_operation_snapshot(tmp_path: Path) -> None:
    logical_ref = "process/state/CHECKPOINT-LEDGER.ndjson"
    path = tmp_path / logical_ref
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"event_id": "E-1", "event_type": "checkpoint"}) + "\n",
        encoding="utf-8",
    )
    metrics = IOMetrics("ledger-load", enabled=True)
    context = OperationReadContext(
        tmp_path / "process",
        operation_id="ledger-load",
        operation_kind="check",
        allowed_reads=(logical_ref,),
        metrics=metrics,
    )

    first = event_ledger.load_events(
        path,
        read_context=context,
        logical_ref=logical_ref,
    )
    second = event_ledger.load_events(
        path,
        read_context=context,
        logical_ref=logical_ref,
    )

    assert first == second
    assert metrics.summary()["totals"]["physical_reads"] == 1
    assert metrics.summary()["totals"]["cache_hits"] == 1


def _discover_gate_semantic_paths(root: Path) -> dict[str, frozenset[str]]:
    """在整个产品包发现 gate 语义、读取、传输和清单引用。"""

    discovered: dict[str, frozenset[str]] = {}
    product_root = root / "meta_flow"
    for path in sorted(product_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        tokens: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value
                if value == "human_gate_approval":
                    tokens.add("raw-human-gate-approval")
                if "GATE-LEDGER" in value:
                    tokens.add("gate-ledger-ref")
                if value in {
                    "gate_approval_kind_correction",
                    "gate_approval_kind_cutover",
                }:
                    tokens.add(value)
                if value in {
                    "checkpoint_passage",
                    "scope_amendment",
                    "recovery_authorization",
                    "evidence_acknowledgement",
                }:
                    tokens.add("approval-kind-value")
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "project_gate_approvals"
            ):
                tokens.add("canonical-projector-call")
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "project_gate_approvals"
            ):
                tokens.add("canonical-projector-owner")
        if tokens:
            discovered[path.relative_to(root).as_posix()] = frozenset(tokens)
    return discovered


def _gate_guardrail_differences(
    root: Path,
    *,
    registry: dict[str, str] | None = None,
) -> dict[str, object]:
    effective_registry = GATE_SEMANTIC_REGISTRY if registry is None else registry
    discovered = _discover_gate_semantic_paths(root)
    registered = set(effective_registry)
    actual = set(discovered)
    role_mismatches: list[str] = []
    for path, role in sorted(effective_registry.items()):
        tokens = discovered.get(path, frozenset())
        if role == "producer-validator-projector-owner" and (
            "canonical-projector-owner" not in tokens
            or "approval-kind-value" not in tokens
        ):
            role_mismatches.append(f"{path}:owner-contract")
        elif role == "passage-consumer" and "canonical-projector-call" not in tokens:
            role_mismatches.append(f"{path}:missing-canonical-projector-call")
        elif role == "count-only-exception" and (
            "raw-human-gate-approval" not in tokens
            or "canonical-projector-call" in tokens
        ):
            role_mismatches.append(f"{path}:count-only-contract")
        elif role in {
            "transport-adapter",
            "mutation-reference-only",
            "metadata-reference-only",
            "inventory-reference-only",
        } and "gate-ledger-ref" not in tokens:
            role_mismatches.append(f"{path}:reference-contract")
    forbidden_raw_semantic = sorted(
        path
        for path, tokens in discovered.items()
        if "raw-human-gate-approval" in tokens
        and path
        not in {
            "meta_flow/state/event_ledger.py",
            "meta_flow/work/usage.py",
        }
    )
    return {
        "registered_only": sorted(registered - actual),
        "discovered_only": sorted(actual - registered),
        "role_mismatch": role_mismatches,
        "forbidden_raw_semantic": forbidden_raw_semantic,
        "discovered": discovered,
    }


def write_minimal_state(root: Path) -> None:
    state = current.default_current_state(root)
    state["project_id"] = "fixture-project"
    current.write_current_state(root, state)


def init_paired_binding(root: Path) -> tuple[Path, Path]:
    release = root / "meta-flow"
    process = root / "meta-flow-process"
    release.mkdir()
    process.mkdir()
    for repository in (release, process):
        subprocess.run(
            ["git", "init", "-b", "main"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        )
    binding = release / ".meta-flow" / "workspace.yaml"
    binding.parent.mkdir()
    binding.write_text(
        "schema_version: 1\n"
        "layout_version: independent-process-repo-v1\n"
        "workflow_model: vnext\n"
        "project_id: fixture-project\n"
        "repo_role: release\n"
        "route_mode: sibling-binding\n"
        "process_repo:\n"
        "  anchor: workspace_parent\n"
        "  relative_path: meta-flow-process\n",
        encoding="utf-8",
    )
    (process / ".meta-flow-process.yaml").write_text(
        "schema_version: 1\n"
        "layout_version: independent-process-repo-v1\n"
        "workflow_model: vnext\n"
        "project_id: fixture-project\n"
        "repo_role: process\n"
        "route_mode: sibling-binding\n"
        "release_repo:\n"
        "  anchor: workspace_parent\n"
        "  relative_path: meta-flow\n",
        encoding="utf-8",
    )
    (process / "PROJECT.yaml").write_text(
        "schema_version: 1\n"
        "project_id: fixture-project\n"
        "name: Fixture Project\n"
        "status: active\n",
        encoding="utf-8",
    )
    return release, process


def cp6_result_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "checkpoint": "CP6",
        "checkpoint_id": "CP6-STORY-CR123-S01",
        "profile": "standard-code",
        "story_id": "STORY-CR123-S01",
        "cr_id": "CR-123",
        "context_ref": "process/context/stories/STORY-CR123-S01.CP6.work-packet.json",
        "dispatch_refs": ["ADE-0001"],
        "evidence_ref": "process/evidence/STORY-CR123-S01.CP6.index.json",
        "items": [
            {
                "id": "CP6-01",
                "category": "implementation",
                "name": "Implementation matches Story Context Contract",
                "status": "PASS",
                "severity": "BLOCKER",
                "evidence_refs": ["process/evidence/STORY-CR123-S01.CP6.index.json#changed_files"],
                "owner": "meta-dev",
                "route_on_fail": "rework_same_story",
                "waiver_ref": None,
                "notes": "",
            }
        ],
        "blockers": [],
        "waivers": [],
        "decision": "PASS",
        "next_route": "CP7",
        "checked_at": "2026-06-21T00:00:00+00:00",
    }


def write_cp6_result(root: Path, payload: dict[str, object] | None = None) -> Path:
    path = root / "process" / "checks" / "CP6-STORY-CR123-S01.result.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload or cp6_result_payload(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def write_cp8_result(root: Path, payload: dict[str, object] | None = None) -> Path:
    path = root / "process" / "checks" / "CP8-CR123.result.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    base = cp6_result_payload()
    base.update(
        {
            "checkpoint": "CP8",
            "checkpoint_id": "CP8-CR123",
            "story_id": "",
            "context_ref": "process/context/CP8-CR123.context.json",
            "dispatch_refs": [],
            "evidence_ref": "process/evidence/CR123.CP8.index.json",
            "release_decision": "READY",
            "next_route": "delivered",
        }
    )
    base.update(payload or {})
    path.write_text(json.dumps(base, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _s00_baseline() -> tuple[dict[str, object], ...]:
    return (
        {
            "finding_id": "CR071-LEDGER-RAW-001",
            "source_ledger_ref": "process/state/GATE-LEDGER.ndjson",
            "source_line": 175,
            "source_event_id": "GATE-CR071-CP2-CHANGES-REQUESTED-20260815-V1",
            "original_bytes_digest": "2460f014e141e1ce74c60ca691f3c32b640c57cc48408f6bcbabd65d161d3744",
            "allowed_correction_fields": ("gate",),
        },
        {
            "finding_id": "CR071-LEDGER-RAW-002",
            "source_ledger_ref": "process/state/AGENT-DISPATCH-LEDGER.ndjson",
            "source_line": 539,
            "source_event_id": "DISPATCH-CR071-CP2-META-PM-REV2-RESUMED-20260815-V1",
            "original_bytes_digest": "f481829d6580c11749796aea07177a987c074e25fd8c5fa7df8814ab41b2bf41",
            "allowed_correction_fields": ("dispatch_id", "canonical_role"),
        },
        {
            "finding_id": "CR071-LEDGER-RAW-003",
            "source_ledger_ref": "process/state/AGENT-DISPATCH-LEDGER.ndjson",
            "source_line": 540,
            "source_event_id": "DISPATCH-CR071-CP2-META-PM-REV2-COMPLETED-20260815-V1",
            "original_bytes_digest": "3492d2e3d57399fd12a03ed56696d890aad507e4755a0b99ca01ef7c3832e509",
            "allowed_correction_fields": ("dispatch_id", "canonical_role"),
        },
    )


def _s00_event(*, baseline_index: int = 0, **overrides: object) -> dict[str, object]:
    source = _s00_baseline()[baseline_index]
    event: dict[str, object] = {
        "schema_version": 1,
        "event_id": "CORR-001",
        "event_type": "compensates",
        "source_ledger_ref": source["source_ledger_ref"],
        "source_line": source["source_line"],
        "source_event_id": source["source_event_id"],
        "original_bytes_digest": source["original_bytes_digest"],
        "preimage_release_oid": "1" * 40,
        "preimage_process_oid": "2" * 40,
        "target_preimage_digest": "6" * 64,
        "correction_fields": event_ledger.canonical_correction_fields(
            str(source["finding_id"])
        ),
        "authoritative_evidence_refs": ("process/checks/CP5-CR071-FORMAL.result.json",),
        "authoritative_evidence_digests": ("3" * 64,),
        "remediation_story_ref": "process/stories/CR-071/STORY-CR071-S00-ledger-remediation-lineage.md",
        "implementation_completion_evidence_ref": "process/evidence/STORY-CR071-S00.CP6.index.json",
        "implementation_completion_evidence_digest": "4" * 64,
        "previous_effective_event_id": "",
        "previous_effective_event_digest": "",
        "typed_authorization_ref": "process/authorizations/CR-071-S00.json",
        "created_by": "native-ledger-owner",
        "created_at": "2026-08-16T00:00:00Z",
    }
    event.update(overrides)
    return event


def test_s00_closed_lineage_validation_and_dual_reports_are_pure() -> None:
    baseline = _s00_baseline()
    events = (_s00_event(), _s00_event(baseline_index=1, event_id="CORR-002"), _s00_event(baseline_index=2, event_id="CORR-003"))
    completion = {"digest": "4" * 64}
    assert all(event_ledger.validate_typed_correction_event(event, baseline, completion).decision == "PASS" for event in events)
    assert event_ledger.validate_typed_correction_event(_s00_event(correction_fields={"waiver": True}), baseline, completion).code == "CORRECTION_FIELD_NOT_ALLOWED"
    assert event_ledger.validate_typed_correction_event(_s00_event(correction_fields={"gate": "WRONG"}), baseline, completion).code == "CORRECTION_VALUE_MISMATCH"
    assert event_ledger.validate_typed_correction_event(_s00_event(preimage_release_oid="bad"), baseline, completion).code == "REPOSITORY_PREIMAGE_INVALID"
    assert event_ledger.validate_typed_correction_event(_s00_event(event_type="legacy"), baseline, completion).code == "UNKNOWN_CORRECTION_EVENT_TYPE"
    lineage = event_ledger.build_correction_lineage(events, baseline, completion)
    assert lineage.decision == "PASS"
    raw = event_ledger.build_raw_history_report(baseline)
    assert (raw.raw_history_finding_count, raw.raw_schema_failure_count) == (3, 5)
    assert event_ledger.build_effective_lineage_report(lineage, None).availability == "unavailable"
    receipt = {
        "decision": "APPLIED",
        "atomic": True,
        "lineage_digest": event_ledger.correction_lineage_digest(lineage),
        "head_set_digest": event_ledger.canonical_digest(list(lineage.heads)),
        "accepted_event_digest_set": event_ledger.canonical_digest(list(lineage.accepted_event_digests)),
        "plan_digest": "5" * 64,
        "completion_digest": "4" * 64,
    }
    assert event_ledger.build_effective_lineage_report(lineage, receipt).effective_global_failure_count == 0
    assert event_ledger.build_effective_lineage_report(lineage, {"decision": "APPLIED", "atomic": True}).availability == "unavailable"
    empty_lineage = event_ledger.build_correction_lineage((), baseline, completion)
    assert event_ledger.build_effective_lineage_report(empty_lineage, receipt).availability == "unavailable"


def test_s00_lineage_denies_fork_cycle_and_dangling_predecessor() -> None:
    baseline = _s00_baseline()
    root = _s00_event()
    fork = _s00_event(event_id="CORR-002")
    completion = {"digest": "4" * 64}
    assert "FORK_DETECTED" in event_ledger.build_correction_lineage((root, fork), baseline, completion).errors
    cycle = _s00_event(previous_effective_event_id="CORR-001", previous_effective_event_digest="5" * 64)
    assert "PREDECESSOR_DIGEST_MISMATCH" in event_ledger.build_correction_lineage((cycle,), baseline, completion).errors
    dangling = _s00_event(previous_effective_event_id="MISSING", previous_effective_event_digest="5" * 64)
    assert "DANGLING_PREDECESSOR" in event_ledger.build_correction_lineage((dangling,), baseline, completion).errors
    duplicate = _s00_event()
    assert event_ledger.build_correction_lineage((root, duplicate), baseline, completion).errors == ("DUPLICATE_EVENT_ID",)


def test_s00_raw_report_requires_exact_complete_unique_canonical_baseline() -> None:
    baseline = _s00_baseline()
    assert event_ledger.build_raw_history_report(baseline).decision == "PASS"
    assert event_ledger.build_raw_history_report(baseline[:2]).decision == "BLOCKED"
    assert event_ledger.build_raw_history_report((baseline[0], baseline[0], baseline[2])).decision == "BLOCKED"
    wrong = ({**baseline[0], "source_line": 176}, baseline[1], baseline[2])
    assert event_ledger.build_raw_history_report(wrong).decision == "BLOCKED"


def test_s00_rejects_forged_baseline_and_minimal_events_before_effective_report() -> None:
    baseline = _s00_baseline()
    completion = {"digest": "4" * 64}
    forged = tuple({"event_id": f"FORGED-{index}", **{key: value for key, value in event.items() if key.startswith("source_") or key == "original_bytes_digest"}} for index, event in enumerate((_s00_event(), _s00_event(baseline_index=1), _s00_event(baseline_index=2))))
    fake_baseline = ({**baseline[0], "finding_id": "FAKE"}, baseline[1], baseline[2])
    assert event_ledger.validate_typed_correction_event(_s00_event(), fake_baseline, completion).code == "CANONICAL_BASELINE_REQUIRED"
    lineage = event_ledger.build_correction_lineage(forged, baseline, completion)
    assert lineage.decision == "BLOCKED"
    completion_mismatch = _s00_event(implementation_completion_evidence_digest="5" * 64)
    assert event_ledger.build_correction_lineage((completion_mismatch,), baseline, completion).errors == ("COMPLETION_EVIDENCE_DRIFT",)
    assert event_ledger.build_effective_lineage_report(lineage, {"decision": "APPLIED", "atomic": True, "lineage_digest": "0" * 64, "head_set_digest": "0" * 64, "accepted_event_digest_set": "0" * 64, "plan_digest": "0" * 64, "completion_digest": "4" * 64}).availability == "unavailable"


class CPResultEventLedgerTests(unittest.TestCase):
    def test_render_appended_event_is_pure_until_caller_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "process/state/GATE-LEDGER.ndjson"
            rendered = event_ledger.render_appended_event(
                path,
                {"event_id": "E-1", "event_type": "subgate_passed", "gate": "B2", "status": "passed"},
            )

            self.assertFalse(path.exists())
            self.assertEqual("subgate_passed", json.loads(rendered)["event_type"])

    def test_cp_result_check_passes_for_valid_cp6_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = write_cp6_result(root)

            stream = StringIO()
            with redirect_stdout(stream):
                exit_code = cp_result.main(["result-check", "--result", str(result), "--project-root", str(root)])

            self.assertEqual(0, exit_code)
            self.assertIn("CP Result Check: OK", stream.getvalue())

    def test_cp_result_check_silent_mode_prints_single_pass_line(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = write_cp6_result(root)

            stream = StringIO()
            with redirect_stdout(stream):
                exit_code = cp_result.main(
                    ["result-check", "--result", str(result), "--project-root", str(root), "--mode", "silent"]
                )

            self.assertEqual(0, exit_code)
            self.assertEqual("PASS", stream.getvalue().strip())

    def test_strict_correlation_requires_attempt_and_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = write_cp6_result(root)
            errors, _warnings = cp_result.validate_cp_result(result, project_root=root, correlation_profile="strict")
            self.assertIn("LEGACY_ATTEMPT_UNAVAILABLE: check_attempt must be a positive integer", errors)
            self.assertIn("LEGACY_INPUT_HASH_UNAVAILABLE: input_artifact_hashes must be non-empty", errors)

    def test_cp5_result_check_consumes_canonical_current_head(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checks = root / "process" / "checks"
            checks.mkdir(parents=True)
            old_ref = "process/checks/CP5-CR123-old.result.json"
            current_ref = "process/checks/CP5-CR123-current.result.json"
            base = cp6_result_payload()
            base.update(
                {
                    "checkpoint": "CP5",
                    "checkpoint_id": "CP5-CR123",
                    "story_id": "",
                    "dispatch_refs": [],
                    "context_ref": "process/context/CP5-CR123.context.json",
                    "evidence_ref": "process/evidence/CR123.CP5.index.json",
                }
            )
            (root / old_ref).write_text(
                json.dumps(base, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            (root / current_ref).write_text(
                json.dumps(base, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            ledger = root / "process" / "state" / "CHECKPOINT-LEDGER.ndjson"
            ledger.parent.mkdir(parents=True)
            ledger.write_text(
                "\n".join(
                    json.dumps(
                        {
                            "event_id": event_id,
                            "event_type": "checkpoint_result",
                            "checkpoint": "CP5",
                            "cr_id": "CR-123",
                            "decision": "PASS",
                            "result_ref": result_ref,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    for event_id, result_ref in (
                        ("CP5-CR123-OLD", old_ref),
                        ("CP5-CR123-CURRENT", current_ref),
                    )
                )
                + "\n",
                encoding="utf-8",
            )

            old_errors, _warnings = cp_result.validate_cp_result(
                root / old_ref,
                project_root=root,
                correlation_profile="strict",
            )
            current_errors, _warnings = cp_result.validate_cp_result(
                root / current_ref,
                project_root=root,
                correlation_profile="strict",
            )

            self.assertIn(
                f"CHECKPOINT_RESULT_NOT_CURRENT_HEAD: expected={current_ref}, actual={old_ref}",
                old_errors,
            )
            self.assertNotIn(
                "CHECKPOINT_RESULT_NOT_CURRENT_HEAD",
                "\n".join(current_errors),
            )

    def test_strict_correlation_rejects_stale_input_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "artifact.txt"
            artifact.write_text("current", encoding="utf-8")
            payload = cp6_result_payload()
            payload["check_attempt"] = 1
            payload["input_artifact_hashes"] = {"artifact.txt": "sha256:" + "0" * 64}
            result = write_cp6_result(root, payload)
            errors, _warnings = cp_result.validate_cp_result(result, project_root=root, correlation_profile="strict")
            self.assertIn("INPUT_HASH_MISMATCH: artifact.txt", errors)

    def test_native_input_hashes_accept_sibling_bound_process_refs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process = init_paired_binding(Path(directory))
            artifact = process / "returns" / "STORY-CR123-S04.CP6.return.json"
            artifact.parent.mkdir(parents=True)
            artifact.write_text('{"status":"implemented"}\n', encoding="utf-8")

            hashes = cp_result.build_input_artifact_hashes(
                release,
                ["process/returns/STORY-CR123-S04.CP6.return.json"],
            )

            self.assertRegex(
                hashes["process/returns/STORY-CR123-S04.CP6.return.json"],
                r"^sha256:[0-9a-f]{64}$",
            )
            stream = StringIO()
            with redirect_stdout(stream):
                exit_code = cp_result.main(
                    [
                        "input-hashes",
                        "--project-root",
                        str(release),
                        "--ref",
                        "process/returns/STORY-CR123-S04.CP6.return.json",
                    ]
                )
            self.assertEqual(0, exit_code)
            self.assertNotIn(str(process), stream.getvalue())

    def test_strict_correlation_rejects_missing_typed_final_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "artifact.txt"
            artifact.write_text("current", encoding="utf-8")
            payload = cp6_result_payload()
            payload["check_attempt"] = 1
            payload["input_artifact_hashes"] = {"artifact.txt": "sha256:" + __import__("hashlib").sha256(b"current").hexdigest()}
            result = write_cp6_result(root, payload)
            errors, _warnings = cp_result.validate_cp_result(result, project_root=root, correlation_profile="strict")
            self.assertIn("FINAL_ATTEMPT_UNAVAILABLE: ADE-0001", errors)

    def test_strict_correlation_consumes_canonical_dispatch_projector(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "artifact.txt"
            artifact.write_text("current", encoding="utf-8")
            payload = cp6_result_payload()
            payload["check_attempt"] = 1
            payload["input_artifact_hashes"] = {
                "artifact.txt": "sha256:" + __import__("hashlib").sha256(b"current").hexdigest()
            }
            result = write_cp6_result(root, payload)
            event_ledger.append_dispatch_event(
                root,
                event_ledger.build_inline_fallback_event(
                    event_id="ADE-0001-completed",
                    dispatch_id="ADE-0001",
                    attempt_id="ATTEMPT-0001",
                    story_id="STORY-CR123-S01",
                    canonical_role="meta-dev",
                    fallback_reason="fixture inline implementation",
                    approved_by="test",
                    checkpoint="CP6",
                    result_ref="process/checks/CP6-STORY-CR123-S01.result.json",
                ),
            )

            errors, _warnings = cp_result.validate_cp_result(
                result,
                project_root=root,
                correlation_profile="strict",
            )

            self.assertNotIn("FINAL_ATTEMPT_UNAVAILABLE: ADE-0001", errors)
            self.assertNotIn("FINAL_ATTEMPT_NOT_UNIQUE_SUCCESS: ADE-0001", errors)

    def test_cp_result_rejects_pass_with_blocking_item(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = cp6_result_payload()
            payload["items"] = [
                {
                    "id": "CP6-01",
                    "category": "implementation",
                    "name": "Forbidden paths not touched",
                    "status": "FAIL",
                    "severity": "BLOCKER",
                    "evidence_refs": [],
                    "owner": "meta-dev",
                    "route_on_fail": "rework_same_story",
                    "waiver_ref": None,
                    "notes": "",
                }
            ]
            result = write_cp6_result(root, payload)

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root)

            self.assertIn("decision cannot be PASS/PASS_WITH_RISK when blocking items exist", errors)

    def test_ledger_append_validates_full_cp_result_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = cp6_result_payload()
            payload["items"][0]["route_on_fail"] = "unknown-route"  # type: ignore[index]
            result = write_cp6_result(root, payload)
            ledger = root / "process" / "state" / "CHECKPOINT-LEDGER.ndjson"

            with self.assertRaisesRegex(
                ValueError,
                "checkpoint result is invalid; ledger mutation=0",
            ):
                cp_result.append_checkpoint_ledger(root, result_path=result)

            self.assertFalse(ledger.exists())

    def test_cp7_result_allows_needs_rework(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = cp6_result_payload()
            payload["checkpoint"] = "CP7"
            payload["checkpoint_id"] = "CP7-STORY-CR123-S01"
            payload["decision"] = "NEEDS_REWORK"
            payload["next_route"] = "NEEDS_REWORK"
            result = write_cp6_result(root, payload)

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root)

            self.assertEqual([], errors)

    def test_na_cp6_result_does_not_require_story_dispatch_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = cp6_result_payload()
            payload.update(
                {
                    "checkpoint": "CP6",
                    "checkpoint_id": "CP6-CR123",
                    "decision": "N/A",
                    "story_id": "",
                    "context_ref": "",
                    "dispatch_refs": [],
                    "evidence_ref": "",
                    "not_applicable_reason": "route_plan marks CP6 N/A because this CR has no new implementation",
                    "items": [
                        {
                            "id": "CP6-NA",
                            "category": "route_plan",
                            "name": "CP6 applicability",
                            "status": "N/A",
                            "severity": "INFO",
                            "evidence_refs": [],
                            "owner": "host-orchestrator",
                            "route_on_fail": "",
                            "waiver_ref": None,
                            "notes": "No implementation stage applies.",
                        }
                    ],
                    "next_route": "CP8",
                }
            )
            result = write_cp6_result(root, payload)

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root)

            self.assertEqual([], errors)

    def test_na_cp_result_requires_applicability_reason_or_route_ref(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = cp6_result_payload()
            payload.update({"checkpoint": "CP3", "checkpoint_id": "CP3-CR123", "decision": "N/A"})
            result = write_cp6_result(root, payload)

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root)

            self.assertIn(
                "decision=N/A requires not_applicable_reason, route_plan_ref, or checkpoint_applicability",
                errors,
            )

    def test_waived_cp_result_requires_waiver_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = cp6_result_payload()
            payload.update({"decision": "WAIVED", "waivers": []})
            result = write_cp6_result(root, payload)

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root)

            self.assertIn("decision=WAIVED requires waivers", errors)

    def test_cp2_commitments_required_evidence_schema_is_validated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = cp6_result_payload()
            payload["checkpoint"] = "CP2"
            payload["checkpoint_id"] = "CP2-CR123"
            payload["story_id"] = ""
            payload["context_ref"] = "process/context/CP2-CR123.context.json"
            payload["evidence_ref"] = ""
            payload["dispatch_refs"] = []
            payload["commitments"] = {
                "required_evidence": [
                    {
                        "id": "REQ-EVID-REAL-LAKE",
                        "kind": "real_lake_validation",
                        "required_stage": "CP7",
                        "minimum_evidence": {"run_refs_min": 2},
                    }
                ]
            }
            result = write_cp6_result(root, payload)

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root)

            self.assertEqual([], errors)

    def test_cp7_missing_required_evidence_blocks_pass_with_risk(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = cp6_result_payload()
            payload["checkpoint"] = "CP7"
            payload["checkpoint_id"] = "CP7-STORY-CR123-S01"
            payload["decision"] = "PASS_WITH_RISK"
            payload["promise_evidence_alignment"] = [
                {
                    "promise_ref": "REQ-EVID-REAL-LAKE",
                    "evidence_status": "MISSING_REQUIRED_EVIDENCE",
                    "result": "BLOCKED",
                    "evidence_refs": [],
                }
            ]
            result = write_cp6_result(root, payload)

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root)

            self.assertIn("CP7 decision must be BLOCKED when required evidence is missing", errors)

    def test_cp7_executed_negative_result_can_pass_with_risk_when_evidenced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = cp6_result_payload()
            payload["checkpoint"] = "CP7"
            payload["checkpoint_id"] = "CP7-STORY-CR123-S01"
            payload["decision"] = "PASS_WITH_RISK"
            payload["promise_evidence_alignment"] = [
                {
                    "promise_ref": "REQ-EVID-ADMISSION",
                    "evidence_status": "EXECUTED_NEGATIVE_RESULT",
                    "result": "PASS_WITH_RISK",
                    "evidence_refs": ["process/evidence/real-lake-validation.json#admission"],
                }
            ]
            result = write_cp6_result(root, payload)

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root)

            self.assertEqual([], errors)

    def test_cp8_fact_diff_rejects_pass_when_required_evidence_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = write_cp8_result(
                root,
                {
                    "decision": "PASS",
                    "release_decision": "READY",
                    "fact_diff": [
                        {
                            "promise_ref": "REQ-EVID-REAL-LAKE",
                            "promise": "Real lake validation must execute",
                            "status": "MISSING_REQUIRED_EVIDENCE",
                            "decision_impact": "NOT_READY",
                            "evidence_refs": [],
                            "risk_ref": "R-REAL-LAKE-MISSING",
                        }
                    ],
                },
            )

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root)

            self.assertIn("CP8 decision cannot be PASS/WAIVED when fact_diff has missing required evidence", errors)
            self.assertIn("CP8 release_decision must be NOT_READY when fact_diff has missing required evidence", errors)

    def test_cp8_fact_diff_allows_ready_with_risk_for_executed_negative_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = write_cp8_result(
                root,
                {
                    "decision": "PASS",
                    "release_decision": "READY_WITH_RISK",
                    "fact_diff": [
                        {
                            "promise_ref": "REQ-EVID-ADMISSION",
                            "promise": "Admission package exists",
                            "status": "EXECUTED_NEGATIVE_RESULT",
                            "decision_impact": "READY_WITH_RISK",
                            "evidence_refs": ["process/evidence/CR123.CP7.index.json#admission"],
                            "risk_ref": "R-ADMISSION-BLOCKED",
                        }
                    ],
                },
            )

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root)

            self.assertEqual([], errors)

    def test_cp8_fact_diff_rejects_ready_for_deferred_follow_up(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = write_cp8_result(
                root,
                {
                    "decision": "PASS",
                    "release_decision": "READY",
                    "fact_diff": [
                        {
                            "promise_ref": "REQ-FOLLOW-UP-001",
                            "promise": "Non-blocking follow-up must be tracked before closeout",
                            "status": "DEFERRED_FOLLOW_UP",
                            "decision_impact": "READY_WITH_RISK",
                            "evidence_refs": ["process/changes/CR123-FOLLOW-UP-TRACKING.md#FU-001"],
                            "risk_ref": "R-FOLLOW-UP-DEFERRED",
                        }
                    ],
                },
            )

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root)

            self.assertIn("CP8 release_decision cannot be READY when fact_diff has risk or not-ready impacts", errors)

    def test_checker_provenance_requires_review_ref_when_fallback_used(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = cp6_result_payload()
            payload["checker_provenance"] = {
                "checker_name": "meta-flow cp result-check",
                "checker_version": "1.0.0",
                "invocation": "meta-flow cp result-check --result process/checks/CP6.result.json",
                "generated_by": "tool",
                "fallback_used": True,
                "fallback_reason": "checker unavailable in current checkout",
            }
            result = write_cp6_result(root, payload)

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root)

            self.assertIn("checker_provenance fallback_used=true requires fallback_review_ref", errors)

    def test_checker_provenance_is_rendered_and_added_to_checkpoint_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = cp6_result_payload()
            payload["checker_provenance"] = {
                "checker_name": "meta-flow cp result-check",
                "checker_commit": "abc1234",
                "invocation": "meta-flow cp result-check --result process/checks/CP6.result.json",
                "generated_by": "tool",
                "fallback_used": False,
            }
            result = write_cp6_result(root, payload)

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root)
            summary = cp_result.render_summary(cp_result.load_cp_result(result))
            event = cp_result.build_checkpoint_event(root, result)

            self.assertEqual([], errors)
            self.assertIn("## Checker Provenance", summary)
            self.assertEqual("meta-flow cp result-check", event["checker_provenance"]["checker_name"])

    def test_render_summary_includes_cp8_release_decision_and_fact_diff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = write_cp8_result(
                root,
                {
                    "decision": "PASS",
                    "release_decision": "READY_WITH_RISK",
                    "fact_diff": [
                        {
                            "promise_ref": "REQ-EVID-ADMISSION",
                            "promise": "Admission package exists",
                            "status": "EXECUTED_NEGATIVE_RESULT",
                            "decision_impact": "READY_WITH_RISK",
                            "evidence_refs": ["process/evidence/CR123.CP7.index.json#admission"],
                            "risk_ref": "R-ADMISSION-BLOCKED",
                        }
                    ],
                },
            )

            summary = cp_result.render_summary(cp_result.load_cp_result(result))

            self.assertIn("Release Decision: READY_WITH_RISK", summary)
            self.assertIn("## Fact Diff", summary)
            self.assertIn("REQ-EVID-ADMISSION", summary)
            self.assertIn("EXECUTED_NEGATIVE_RESULT", summary)

    def test_result_check_consistency_rejects_stale_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = write_cp6_result(root)
            result.with_suffix(".summary.md").write_text("# CP6 Summary\n\nDecision: FAIL\nCR: CR-123\n", encoding="utf-8")

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root, check_consistency=True)

            self.assertTrue(any("summary decision does not match result JSON" in error for error in errors))

    def test_render_summary_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = write_cp6_result(root)

            output = cp_result.render_summary_file(result)

            self.assertTrue(output.is_file())
            self.assertIn("Decision: PASS", output.read_text(encoding="utf-8"))

    def test_checkpoint_ledger_append_and_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            result = write_cp6_result(root)
            cp_result.render_summary_file(result)

            ledger = cp_result.append_checkpoint_ledger(root, result_path=result)
            errors, warnings = event_ledger.validate_event_ledger(ledger, ledger_type="checkpoint")

            self.assertTrue(ledger.is_file())
            self.assertEqual([], errors)
            self.assertEqual([], warnings)

    def test_cp_result_consistency_rejects_missing_dispatch_ref(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = write_cp6_result(root)

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root, check_consistency=True)

            self.assertIn("dispatch_refs require AGENT-DISPATCH-LEDGER entries: ADE-0001", errors)

    def test_cp_result_consistency_runs_state_transition_when_route_plan_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = current.default_current_state(root)
            state["project_id"] = "fixture-project"
            state["active_change"] = "CR-123"
            state["current_phase"] = "story-planning"
            state["next_action"] = {"type": "continue", "text": "manual continue to CP5"}
            current.write_current_state(root, state)
            route_path = root / "process" / "checks" / "CP0-CR123.route-plan.json"
            route_path.parent.mkdir(parents=True, exist_ok=True)
            route_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "decision": "PASS",
                        "stages": [
                            {"checkpoint": "CP3", "mode": "standard", "human_gate": "required"},
                            {"checkpoint": "CP4", "mode": "standard", "human_gate": "none"},
                            {"checkpoint": "CP5", "mode": "standard", "human_gate": "required"},
                        ],
                        "checkpoint_applicability": {},
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            payload = cp6_result_payload()
            payload.update(
                {
                    "checkpoint": "CP4",
                    "checkpoint_id": "CP4-CR123",
                    "story_id": "",
                    "context_ref": "process/context/CP4.context.json",
                    "dispatch_refs": [],
                    "evidence_ref": "",
                    "route_plan_ref": "process/checks/CP0-CR123.route-plan.json",
                }
            )
            result = write_cp6_result(root, payload)

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root, check_consistency=True)

            self.assertTrue(any("pending_gate=CP5" in error for error in errors))

    def test_cp_result_consistency_accepts_dispatch_ref_in_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = write_cp6_result(root)
            event = event_ledger.build_inline_fallback_event(
                event_id="ADE-0001-completed",
                dispatch_id="ADE-0001",
                attempt_id="ATTEMPT-0001",
                story_id="STORY-CR123-S01",
                canonical_role="meta-dev",
                fallback_reason="fixture inline implementation",
                approved_by="test",
                cr_id="CR-123",
                checkpoint="CP6",
                result_ref="process/checks/CP6-STORY-CR123-S01.result.json",
                created_at="2026-07-05T00:00:00+00:00",
            )
            event_ledger.append_dispatch_event(root, event)

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root, check_consistency=True)

            self.assertNotIn("dispatch_refs require AGENT-DISPATCH-LEDGER entries: ADE-0001", errors)
            self.assertFalse(any("dispatch_refs missing" in error for error in errors))

    def test_cp_result_consistency_rejects_wrong_dispatch_role(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = write_cp6_result(root)
            event = event_ledger.build_inline_fallback_event(
                event_id="ADE-0001-completed", dispatch_id="ADE-0001", attempt_id="ATTEMPT-0001",
                story_id="STORY-CR123-S01", canonical_role="meta-qa", fallback_reason="fixture",
                approved_by="test", checkpoint="CP6",
            )
            event_ledger.append_dispatch_event(root, event)

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root, check_consistency=True)

            self.assertTrue(any("canonical_role must be meta-dev" in error for error in errors))

    def test_cp_result_consistency_rejects_wrong_dispatch_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = write_cp6_result(root)
            event = event_ledger.build_inline_fallback_event(
                event_id="ADE-0001-completed", dispatch_id="ADE-0001", attempt_id="ATTEMPT-0001",
                story_id="STORY-CR123-S01", canonical_role="meta-dev", fallback_reason="fixture",
                approved_by="test", checkpoint="CP7",
            )
            event_ledger.append_dispatch_event(root, event)

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root, check_consistency=True)

            self.assertTrue(any("checkpoint must be CP6" in error for error in errors))

    def test_cp_result_consistency_rejects_failed_and_running_dispatches(self) -> None:
        for status in ("failed", "running"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                result = write_cp6_result(root)
                event = event_ledger.build_inline_fallback_event(
                    event_id="ADE-0001-completed", dispatch_id="ADE-0001", attempt_id="ATTEMPT-0001",
                    story_id="STORY-CR123-S01", canonical_role="meta-dev", fallback_reason="fixture",
                    approved_by="test", checkpoint="CP6", status=status,
                )
                event_ledger.append_dispatch_event(root, event)

                errors, _warnings = cp_result.validate_cp_result(result, project_root=root, check_consistency=True)

                self.assertTrue(any("status must be terminal and successful" in error for error in errors))

    def test_cp_result_consistency_rejects_dispatch_not_required(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = write_cp6_result(root)
            event = event_ledger.build_dispatch_not_required_event(
                dispatch_id="ADE-0001", canonical_role="meta-dev", reason="fixture",
                checkpoint="CP6", status="completed",
            )
            event_ledger.append_dispatch_event(root, event)

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root, check_consistency=True)

            self.assertTrue(any("dispatch_not_required is invalid" in error for error in errors))

    def test_cp_result_consistency_rejects_incomplete_inline_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = write_cp6_result(root)
            ledger = root / "process/state/AGENT-DISPATCH-LEDGER.ndjson"
            ledger.parent.mkdir(parents=True, exist_ok=True)
            ledger.write_text(json.dumps({
                "dispatch_id": "ADE-0001", "event_type": "inline_fallback",
                "dispatch_mode": "inline-fallback", "canonical_role": "meta-dev",
                "checkpoint": "CP6", "fallback_reason": "fixture", "tool_name": "host-inline",
                "status": "completed",
            }) + "\n", encoding="utf-8")

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root, check_consistency=True)

            self.assertTrue(any("inline fallback requires approved_by" in error for error in errors))

    def test_cp7_result_consistency_accepts_valid_real_spawn_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = cp6_result_payload()
            payload.update({
                "checkpoint": "CP7", "checkpoint_id": "CP7-STORY-CR123-S01",
                "dispatch_refs": ["ADE-0001"],
                "promise_evidence_alignment": [{"promise_ref": "P-1", "evidence_status": "EXECUTED_POSITIVE_RESULT", "result": "PASS", "evidence_refs": ["evidence"]}],
            })
            result = write_cp6_result(root, payload)
            event_ledger.append_dispatch_event(root, {
                "event_id": "ADE-0001-completed", "attempt_id": "ATTEMPT-0001", "story_id": "STORY-CR123-S01",
                "dispatch_id": "ADE-0001", "event_type": "dispatch", "canonical_role": "meta-qa",
                "checkpoint": "CP7", "dispatch_mode": "subagent", "tool_name": "spawn_agent", "agent_id": "/root/qa",
                "status": "completed", "dispatch_trigger": "critical-checkpoint",
                "terminal_result": "PASS", "spawned_at": "2026-07-05T00:00:00+00:00", "completed_at": "2026-07-05T00:05:00+00:00",
            })

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root, check_consistency=True)

            self.assertFalse(any("dispatch_ref ADE-0001" in error for error in errors))

    def test_cp7_result_consistency_rejects_wrong_real_dispatch_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = cp6_result_payload()
            payload.update({
                "checkpoint": "CP7", "checkpoint_id": "CP7-STORY-CR123-S01",
                "dispatch_refs": ["ADE-0001"],
                "promise_evidence_alignment": [{"promise_ref": "P-1", "evidence_status": "EXECUTED_POSITIVE_RESULT", "result": "PASS", "evidence_refs": ["evidence"]}],
            })
            result = write_cp6_result(root, payload)
            event_ledger.append_dispatch_event(root, {
                "event_id": "ADE-0001-completed", "attempt_id": "ATTEMPT-0001", "story_id": "STORY-CR123-S01",
                "dispatch_id": "ADE-0001", "event_type": "dispatch", "dispatch_mode": "inline-fallback",
                "canonical_role": "meta-qa", "checkpoint": "CP7", "tool_name": "spawn_agent",
                "agent_id": "/root/qa", "status": "completed", "dispatch_trigger": "critical-checkpoint",
                "approved_by": "test", "terminal_result": "PASS", "spawned_at": "2026-07-05T00:00:00+00:00", "completed_at": "2026-07-05T00:05:00+00:00",
            })

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root, check_consistency=True)

            self.assertTrue(any("incompatible dispatch_mode" in error for error in errors))

    def test_event_ledger_check_silent_mode_prints_single_pass_line(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            result = write_cp6_result(root)
            cp_result.render_summary_file(result)
            ledger = cp_result.append_checkpoint_ledger(root, result_path=result)

            stream = StringIO()
            with redirect_stdout(stream):
                exit_code = event_ledger.main(["check", "--ledger", str(ledger), "--type", "checkpoint", "--mode", "silent"])

            self.assertEqual(0, exit_code)
            self.assertEqual("PASS", stream.getvalue().strip())

    def test_applicability_aggregate_build_and_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            route_plan = root / "process" / "checks" / "CP0-CR156.route-plan.json"
            aggregate = root / "process" / "checks" / "CP8-CR156.applicability.json"
            route_plan.parent.mkdir(parents=True, exist_ok=True)
            route_plan.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "decision": "PASS",
                        "stages": [{"checkpoint": "CP0", "mode": "standard", "human_gate": "none"}],
                        "checkpoint_applicability": {
                            "CP0": {"applies": True, "mode": "standard", "human_gate": "none"},
                            "CP3": {"applies": False, "decision": "N/A", "reason": "uses existing evidence only"},
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            output = cp_result.write_applicability_aggregate(root, route_plan, aggregate, cr_id="CR-156")
            errors, warnings = cp_result.validate_applicability_aggregate(root, output)

            self.assertTrue(output.is_file())
            self.assertEqual([], errors)
            self.assertEqual([], warnings)

    def test_applicability_public_commands_resolve_paired_process_refs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process = init_paired_binding(Path(directory))
            route_plan = process / "checks" / "CP0-CR156.route-plan.json"
            aggregate = process / "checks" / "CP8-CR156.applicability.json"
            route_plan.parent.mkdir(parents=True, exist_ok=True)
            route_plan.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "decision": "PASS",
                        "stages": [{"checkpoint": "CP8", "mode": "standard", "human_gate": "required"}],
                        "checkpoint_applicability": {
                            "CP8": {"applies": True, "mode": "standard", "human_gate": "required"}
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            stream = StringIO()
            with redirect_stdout(stream):
                build_exit = cp_result.main(
                    [
                        "applicability-build",
                        "--route-plan",
                        "process/checks/CP0-CR156.route-plan.json",
                        "--output",
                        "process/checks/CP8-CR156.applicability.json",
                        "--cr-id",
                        "CR-156",
                        "--project-root",
                        str(release),
                    ]
                )
                check_exit = cp_result.main(
                    [
                        "applicability-check",
                        "--aggregate",
                        "process/checks/CP8-CR156.applicability.json",
                        "--project-root",
                        str(release),
                    ]
                )

            self.assertEqual(0, build_exit)
            self.assertEqual(0, check_exit)
            self.assertTrue(aggregate.is_file())
            self.assertFalse((release / "process").exists())
            self.assertNotIn(str(process.resolve()), stream.getvalue())
            self.assertIn("wrote: process/checks/CP8-CR156.applicability.json", stream.getvalue())
            payload = json.loads(aggregate.read_text(encoding="utf-8"))
            self.assertEqual(
                "process/checks/CP0-CR156.route-plan.json",
                payload["source_route_plan_ref"],
            )

    def test_applicability_aggregate_rejects_stale_route_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            route_plan = root / "process" / "checks" / "CP0-CR156.route-plan.json"
            aggregate = root / "process" / "checks" / "CP8-CR156.applicability.json"
            route_plan.parent.mkdir(parents=True, exist_ok=True)
            route_plan.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "decision": "PASS",
                        "stages": [],
                        "checkpoint_applicability": {
                            "CP3": {"applies": False, "decision": "N/A", "reason": "uses existing evidence only"},
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            cp_result.write_applicability_aggregate(root, route_plan, aggregate, cr_id="CR-156")
            payload = json.loads(aggregate.read_text(encoding="utf-8"))
            payload["checkpoint_applicability"]["CP3"]["decision"] = "WAIVED"
            aggregate.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            errors, _warnings = cp_result.validate_applicability_aggregate(root, aggregate)

            self.assertIn("checkpoint_applicability does not match source route plan", errors)

    def test_dispatch_not_required_event_uses_structured_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "process" / "state" / "AGENT-DISPATCH-LEDGER.ndjson"
            event = event_ledger.build_dispatch_not_required_event(
                dispatch_id="ADE-NA-001",
                canonical_role="meta-dev",
                reason="route_plan marks CP6 N/A",
                created_at="2026-07-05T00:00:00+00:00",
            )
            event_ledger.append_dispatch_event(root, event, ledger=ledger)

            errors, warnings = event_ledger.validate_event_ledger(ledger, ledger_type="dispatch")

            self.assertEqual([], errors)
            self.assertEqual([], warnings)

    def test_inline_fallback_dispatch_event_requires_approval_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "process" / "state" / "AGENT-DISPATCH-LEDGER.ndjson"
            ledger.parent.mkdir(parents=True, exist_ok=True)
            ledger.write_text(
                json.dumps(
                    {
                        "dispatch_id": "ADE-INLINE-001",
                        "event_type": "inline_fallback",
                        "canonical_role": "meta-dev",
                        "dispatch_mode": "inline-fallback",
                        "fallback_reason": "current platform has no subagent dispatch tool",
                        "status": "completed",
                        "created_at": "2026-07-05T00:00:00+00:00",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            errors, _warnings = event_ledger.validate_event_ledger(ledger, ledger_type="dispatch")

            self.assertIn("line 1: missing required field: approved_by", errors)

    def test_event_ledger_check_rejects_missing_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "process" / "state" / "CHECKPOINT-LEDGER.ndjson"
            ledger.parent.mkdir(parents=True, exist_ok=True)
            ledger.write_text(json.dumps({"event_id": "E-1", "event_type": "checkpoint_result"}) + "\n", encoding="utf-8")

            errors, _warnings = event_ledger.validate_event_ledger(ledger, ledger_type="checkpoint")

            self.assertIn("line 1: missing required field: checkpoint", errors)
            self.assertIn("line 1: missing required field: decision", errors)
            self.assertIn("line 1: missing required field: result_ref", errors)

    def test_event_cli_append_and_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "process" / "state" / "HANDOFF-LEDGER.ndjson"
            event_file = root / "event.json"
            event_file.write_text(
                json.dumps(
                    {
                        "event_id": "HE-0001",
                        "event_type": "handoff",
                        "stage": "CP6",
                        "from_role": "host-orchestrator",
                        "to_role": "meta-dev",
                        "context_ref": "process/context/stories/STORY.CP6.work-packet.json",
                        "status": "created",
                        "created_at": "2026-06-21T00:00:00+00:00",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            self.assertEqual(0, event_ledger.main(["append", "--ledger", str(ledger), "--event-file", str(event_file)]))
            self.assertEqual(0, event_ledger.main(["check", "--ledger", str(ledger), "--type", "handoff"]))
            stream = StringIO()
            with redirect_stdout(stream):
                exit_code = event_ledger.main(["list", "--ledger", str(ledger)])

            self.assertEqual(0, exit_code)
            self.assertIn("HE-0001\thandoff\tcreated", stream.getvalue())


class DispatchEvidenceTests(unittest.TestCase):
    """subagent dispatch 事件字段完整性 + cp_result dispatch_refs 强化校验。"""

    def _write_dispatch_event(self, ledger: Path, event: dict) -> None:
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text(json.dumps(event) + "\n", encoding="utf-8")

    def test_complete_subagent_dispatch_event_passes(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ledger = Path(d) / "process/state/AGENT-DISPATCH-LEDGER.ndjson"
            self._write_dispatch_event(ledger, {
                "dispatch_id": "ADE-001",
                "event_type": "dispatch",
                "canonical_role": "meta-dev",
                "tool_name": "spawn_agent",
                "status": "completed",
                "dispatch_trigger": "phase-default",
                "agent_id": "a-123",
                "spawned_at": "2026-07-05T00:00:00+00:00",
                "completed_at": "2026-07-05T00:05:00+00:00",
            })
            errors, _warnings = event_ledger.validate_event_ledger(ledger, ledger_type="dispatch")
            self.assertEqual([], errors)

    def test_subagent_dispatch_event_missing_agent_id_fails(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ledger = Path(d) / "process/state/AGENT-DISPATCH-LEDGER.ndjson"
            self._write_dispatch_event(ledger, {
                "dispatch_id": "ADE-001",
                "event_type": "dispatch",
                "canonical_role": "meta-dev",
                "tool_name": "spawn_agent",
                "status": "completed",
                "dispatch_trigger": "phase-default",
                "spawned_at": "2026-07-05T00:00:00+00:00",
                "completed_at": "2026-07-05T00:05:00+00:00",
            })
            errors, warnings = event_ledger.validate_event_ledger(ledger, ledger_type="dispatch")
            self.assertEqual([], errors)
            self.assertIn("line 1: legacy dispatch event lacks agent_id or thread_id", warnings)

    def test_subagent_dispatch_event_missing_spawned_at_fails(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ledger = Path(d) / "process/state/AGENT-DISPATCH-LEDGER.ndjson"
            self._write_dispatch_event(ledger, {
                "dispatch_id": "ADE-001",
                "event_type": "dispatch",
                "canonical_role": "meta-dev",
                "tool_name": "spawn_agent",
                "status": "completed",
                "dispatch_trigger": "phase-default",
                "thread_id": "t-1",
                "completed_at": "2026-07-05T00:05:00+00:00",
            })
            errors, warnings = event_ledger.validate_event_ledger(ledger, ledger_type="dispatch")
            self.assertEqual([], errors)
            self.assertIn("line 1: legacy dispatch event lacks spawned_at or resumed_at", warnings)

    def test_subagent_dispatch_event_missing_dispatch_trigger_fails(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ledger = Path(d) / "process/state/AGENT-DISPATCH-LEDGER.ndjson"
            self._write_dispatch_event(ledger, {
                "dispatch_id": "ADE-001",
                "event_type": "dispatch",
                "canonical_role": "meta-dev",
                "tool_name": "spawn_agent",
                "status": "completed",
                "agent_id": "a-1",
                "spawned_at": "2026-07-05T00:00:00+00:00",
                "completed_at": "2026-07-05T00:05:00+00:00",
            })
            errors, warnings = event_ledger.validate_event_ledger(ledger, ledger_type="dispatch")
            self.assertEqual([], errors)
            self.assertIn("line 1: legacy dispatch event lacks dispatch_trigger", warnings)

    def test_cp_result_rejects_dispatch_ref_with_incomplete_subagent_event(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            result = write_cp6_result(root)
            ledger = root / "process/state/AGENT-DISPATCH-LEDGER.ndjson"
            self._write_dispatch_event(ledger, {
                "event_id": "ADE-0001-completed", "attempt_id": "ATTEMPT-0001", "story_id": "STORY-CR123-S01",
                "dispatch_id": "ADE-0001",
                "event_type": "dispatch",
                "canonical_role": "meta-dev",
                "checkpoint": "CP6", "dispatch_mode": "subagent",
                "tool_name": "spawn_agent",
                "status": "completed",
                "dispatch_trigger": "phase-default",
                "spawned_at": "2026-07-05T00:00:00+00:00",
                "terminal_result": "PASS", "completed_at": "2026-07-05T00:05:00+00:00",
            })  # 缺 agent_id/thread_id
            errors, _warnings = cp_result.validate_cp_result(result, project_root=root, check_consistency=True)
            self.assertTrue(any("ADE-0001" in e and "agent_id or thread_id" in e for e in errors))

    def test_cp_result_accepts_dispatch_ref_with_complete_subagent_event(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            result = write_cp6_result(root)
            ledger = root / "process/state/AGENT-DISPATCH-LEDGER.ndjson"
            self._write_dispatch_event(ledger, {
                "event_id": "ADE-0001-completed",
                "attempt_id": "ATTEMPT-0001",
                "story_id": "STORY-CR123-S01",
                "dispatch_id": "ADE-0001",
                "event_type": "dispatch",
                "canonical_role": "meta-dev",
                "checkpoint": "CP6",
                "dispatch_mode": "subagent",
                "tool_name": "spawn_agent",
                "status": "completed",
                "dispatch_trigger": "phase-default",
                "agent_id": "a-123",
                "spawned_at": "2026-07-05T00:00:00+00:00",
                "terminal_result": "PASS",
                "completed_at": "2026-07-05T00:05:00+00:00",
            })
            errors, _warnings = cp_result.validate_cp_result(result, project_root=root, check_consistency=True)
            self.assertFalse(any("dispatch_ref ADE-0001" in e for e in errors))

    def test_cp_result_accepts_split_typed_attempt_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            result = write_cp6_result(root)
            ledger = root / "process/state/AGENT-DISPATCH-LEDGER.ndjson"
            for event in (
                {
                    "event_id": "ADE-0001-running",
                    "dispatch_id": "ADE-0001",
                    "attempt_id": "attempt-1",
                    "story_id": "STORY-CR123-S01",
                    "event_type": "dispatch",
                    "canonical_role": "meta-dev",
                    "checkpoint": "CP6", "dispatch_mode": "subagent",
                    "tool_name": "spawn_agent",
                    "dispatch_trigger": "phase-default",
                    "agent_id": "a-123",
                    "status": "running",
                    "spawned_at": "2026-07-05T00:00:00+00:00",
                },
                {
                    "event_id": "ADE-0001-completed",
                    "dispatch_id": "ADE-0001",
                    "attempt_id": "attempt-1",
                    "story_id": "STORY-CR123-S01",
                    "event_type": "dispatch",
                    "canonical_role": "meta-dev",
                    "checkpoint": "CP6", "dispatch_mode": "subagent",
                    "tool_name": "spawn_agent",
                    "status": "completed",
                    "terminal_result": "PASS",
                    "completed_at": "2026-07-05T00:05:00+00:00",
                },
            ):
                event_ledger.append_dispatch_event(root, event, ledger=ledger)

            errors, _warnings = cp_result.validate_cp_result(result, project_root=root, check_consistency=True)

            self.assertFalse(any("dispatch_ref ADE-0001" in error for error in errors))

    def test_cp_result_does_not_require_subagent_fields_for_inline_fallback_ref(self) -> None:
        # inline_fallback 事件不应被 subagent 字段校验误判
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            result = write_cp6_result(root)
            event = event_ledger.build_inline_fallback_event(
                event_id="ADE-0001-completed",
                dispatch_id="ADE-0001",
                attempt_id="ATTEMPT-0001",
                story_id="STORY-CR123-S01",
                canonical_role="meta-dev",
                fallback_reason="fixture inline implementation",
                approved_by="test",
                cr_id="CR-123",
                checkpoint="CP6",
                result_ref="process/checks/CP6-STORY-CR123-S01.result.json",
                created_at="2026-07-05T00:00:00+00:00",
            )
            event_ledger.append_dispatch_event(root, event)
            errors, _warnings = cp_result.validate_cp_result(result, project_root=root, check_consistency=True)
            self.assertFalse(any("subagent event missing" in e for e in errors))


class S01ProjectionContractTests(unittest.TestCase):
    """C01-C09：只通过公共事件入口与唯一 projector 断言 S01 契约。"""

    def test_terminal_projector_normalizes_without_event_id_identity_fallback(self) -> None:
        events = (
            {"event_id": "event-running", "dispatch_id": "DISPATCH-1", "status": " running "},
            {"event_id": "event-terminal", "dispatch_id": "DISPATCH-1", "status": " PASSED "},
        )
        projected = event_ledger.project_terminal_successes(
            event_ledger.ProjectionInputV1(events, "dispatch")
        )

        self.assertTrue(projected.terminal_success)
        self.assertEqual(("event-terminal",), projected.terminal_event_ids)
        self.assertEqual((), projected.typed_attempt_ids)

    def test_typed_inline_attempt_requires_approval_and_identity(self) -> None:
        projected = event_ledger.project_dispatch_attempt(
            event_ledger.ProjectionInputV1(
                (
                    {
                        "event_id": "event-inline",
                        "dispatch_id": "DISPATCH-1",
                        "attempt_id": "ATTEMPT-1",
                        "story_id": "STORY-CR123-S01",
                        "canonical_role": "meta-dev",
                        "checkpoint": "CP6",
                        "dispatch_mode": "inline-fallback",
                        "event_type": "inline_fallback",
                        "status": "completed",
                        "terminal_result": "PASS",
                    },
                ),
                "dispatch",
                "DISPATCH-1",
            )
        )

        self.assertFalse(projected.terminal_success)
        self.assertIn("MISSING_INLINE_FALLBACK_APPROVAL", projected.finding_codes)

    def test_gate_approval_kind_v1_projects_only_checkpoint_passage(self) -> None:
        base = {
            "event_id": "GATE-TYPED-V1",
            "event_type": "human_gate_approval",
            "gate": "EXPLICIT_TYPED_GATE",
            "status": "approved",
            "decision": "approve",
            "cr_id": "CR-200",
            "work_id": "W-200",
            "approval_kind_version": 1,
        }
        events = [
            {
                **base,
                "event_id": "GATE-PASSAGE-V1",
                "approval_kind": "checkpoint_passage",
                "checkpoint": "CP5",
                "result_ref": "process/checks/CP5-CR-200.result.json",
            },
            {
                **base,
                "event_id": "GATE-SCOPE-V1",
                "approval_kind": "scope_amendment",
                "scope_version": 2,
                "scope_digest": "a" * 64,
                "authorized_actions": ["add-one-leaf"],
                "decision_ref": "process/checkpoints/CP3-CR-200.md",
            },
            {
                **base,
                "event_id": "GATE-RECOVERY-V1",
                "approval_kind": "recovery_authorization",
                "recovery_ordinal": 3,
                "authorized_actions": ["retry-once"],
                "decision_ref": "process/checkpoints/CP3-CR-200.md",
            },
            {
                **base,
                "event_id": "GATE-EVIDENCE-V1",
                "approval_kind": "evidence_acknowledgement",
                "evidence_refs": ["process/evidence/example.index.json"],
                "evidence_digests": ["b" * 64],
                "acknowledgement_decision": "acknowledged",
            },
        ]

        projections = event_ledger.project_gate_approvals(events)

        self.assertEqual(
            [True, False, False, False],
            [projection.passage for projection in projections],
        )
        self.assertEqual("CP5", projections[0].checkpoint)
        self.assertEqual(
            "process/checks/CP5-CR-200.result.json",
            projections[0].result_ref,
        )
        self.assertTrue(
            all(not projection.finding_codes for projection in projections)
        )

    def test_gate_approval_append_rejects_missing_or_unknown_kind(self) -> None:
        ledger = Path("process/state/GATE-LEDGER.ndjson")
        base = {
            "event_id": "GATE-INVALID-V1",
            "event_type": "human_gate_approval",
            "gate": "CP5_SHOULD_NOT_BE_INFERRED",
            "status": "approved",
            "decision": "approve",
            "cr_id": "CR-200",
            "work_id": "W-200",
        }
        for payload in (
            base,
            {
                **base,
                "approval_kind_version": 1,
                "approval_kind": "not-a-kind",
            },
        ):
            with self.subTest(payload=payload), self.assertRaisesRegex(
                ValueError,
                "invalid gate human approval",
            ):
                event_ledger.validate_event_before_append(
                    ledger,
                    payload,
                    ledger_type="gate",
                )
            projection = event_ledger.project_gate_approvals([payload])[0]
            self.assertFalse(projection.passage)

    def test_public_gate_append_rejects_untyped_approval_before_mutation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger_ref = "process/state/GATE-LEDGER.ndjson"
            payload = {
                "event_id": "GATE-UNTYPED-V1",
                "event_type": "human_gate_approval",
                "gate": "CP5_SHOULD_NOT_BE_INFERRED",
                "status": "approved",
                "decision": "approve",
                "cr_id": "CR-200",
                "work_id": "W-200",
            }

            output = StringIO()
            with redirect_stdout(output):
                exit_code = event_ledger.main(
                    [
                        "append",
                        "--project-root",
                        str(root),
                        "--ledger",
                        ledger_ref,
                        "--event-json",
                        json.dumps(payload),
                    ]
                )

            self.assertEqual(2, exit_code)
            result = json.loads(output.getvalue())
            self.assertEqual("BLOCKED", result["status"])
            self.assertEqual(0, result["mutation_count"])
            self.assertFalse((root / ledger_ref).exists())

    def test_legacy_gate_manifest_and_migration_dry_run_are_exact(self) -> None:
        legacy_events = []
        for event_id, (
            _approval_kind,
            _checkpoint,
            _result_ref,
        ) in event_ledger._LEGACY_GATE_APPROVAL_MANIFEST_V1.items():
            legacy_events.append(
                {
                    "event_id": event_id,
                    "event_type": "human_gate_approval",
                    "gate": "LEGACY_VALUE_MUST_NOT_BE_PARSED",
                    "status": "approved",
                    "decision": "approve",
                    "cr_id": "CR-LEGACY",
                    "work_id": "W-LEGACY",
                    "interaction_id": event_id,
                }
            )
        projections = event_ledger.project_gate_approvals(legacy_events)
        counts = {
            kind.value: sum(
                projection.approval_kind == kind.value
                for projection in projections
            )
            for kind in event_ledger.GateApprovalKindV1
        }
        self.assertEqual(
            {
                "checkpoint_passage": 13,
                "scope_amendment": 2,
                "recovery_authorization": 1,
                "evidence_acknowledgement": 0,
            },
            counts,
        )
        self.assertEqual(13, sum(projection.passage for projection in projections))

        decision_ref = (
            "process/checkpoints/"
            "CP3-CR-062-GATE-APPROVAL-KIND-REFACTOR.md"
        )
        plan = event_ledger.build_gate_approval_kind_migration_plan(
            legacy_events,
            decision_ref=decision_ref,
        )

        self.assertEqual("READY", plan["decision"])
        self.assertTrue(plan["dry_run"])
        self.assertEqual(0, plan["mutation_count"])
        self.assertEqual(17, plan["planned_append_count"])
        self.assertEqual(counts, plan["classification_counts"])
        self.assertEqual(64, len(plan["gate_ledger_preimage_digest"]))
        self.assertEqual(64, len(plan["legacy_manifest_digest"]))
        self.assertEqual(64, len(plan["plan_digest"]))
        migrated = event_ledger.project_gate_approvals(
            [*legacy_events, *plan["append_events"]]
        )
        self.assertEqual(13, sum(projection.passage for projection in migrated))
        partial = event_ledger.project_gate_approvals(
            [*legacy_events, plan["append_events"][0]]
        )
        self.assertEqual(0, sum(projection.passage for projection in partial))

        before_count = usage._deduplicated_human_interactions(legacy_events)
        after_count = usage._deduplicated_human_interactions(
            [*legacy_events, *plan["append_events"]]
        )
        self.assertEqual(16, before_count)
        self.assertEqual(before_count, after_count)

    def test_unknown_legacy_gate_is_fail_closed_and_plan_is_zero_mutation(self) -> None:
        event = {
            "event_id": "UNKNOWN-LEGACY-CP8-NAME",
            "event_type": "human_gate_approval",
            "gate": "CP8",
            "status": "approved",
            "decision": "approve",
            "cr_id": "CR-999",
            "work_id": "W-999",
        }
        projection = event_ledger.project_gate_approvals([event])[0]
        plan = event_ledger.build_gate_approval_kind_migration_plan(
            [event],
            decision_ref="process/checkpoints/CP3-CR-062.md",
        )

        self.assertFalse(projection.passage)
        self.assertIn("GATE_APPROVAL_LEGACY_UNKNOWN", projection.finding_codes)
        self.assertEqual("BLOCKED", plan["decision"])
        self.assertEqual(0, plan["mutation_count"])
        self.assertEqual([], plan["append_events"])

    def test_gate_semantic_guardrail_covers_repo_wide_registry(self) -> None:
        root = Path(__file__).resolve().parents[1]

        report = _gate_guardrail_differences(root)

        self.assertEqual([], report["discovered_only"])
        self.assertEqual([], report["role_mismatch"])
        self.assertEqual([], report["forbidden_raw_semantic"])
        self.assertEqual(
            sorted(GATE_OPTIONAL_REGISTERED_ONLY),
            report["registered_only"],
        )
        roles = tuple(GATE_SEMANTIC_REGISTRY.values())
        self.assertEqual(1, roles.count("producer-validator-projector-owner"))
        self.assertEqual(3, roles.count("passage-consumer"))
        self.assertEqual(1, roles.count("count-only-exception"))

    def test_gate_semantic_guardrail_positive_fixture_finds_rogue_consumer(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "meta_flow"
            package.mkdir()
            (package / "rogue.py").write_text(
                "def admits(event):\n"
                "    return event.get('event_type') == 'human_gate_approval'\n",
                encoding="utf-8",
            )

            report = _gate_guardrail_differences(root, registry={})

        self.assertEqual(["meta_flow/rogue.py"], report["discovered_only"])
        self.assertEqual(
            ["meta_flow/rogue.py"],
            report["forbidden_raw_semantic"],
        )

    def test_public_append_rejects_invalid_event_before_ledger_creation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger_ref = "process/state/GATE-LEDGER.ndjson"
            payload = {"event_id": "G-1", "event_type": "gate", "status": "passed"}

            output = StringIO()
            with redirect_stdout(output):
                exit_code = event_ledger.main(
                    [
                        "append",
                        "--project-root",
                        str(root),
                        "--ledger",
                        ledger_ref,
                        "--event-json",
                        json.dumps(payload),
                    ]
                )

            self.assertEqual(2, exit_code)
            result = json.loads(output.getvalue())
            self.assertEqual("BLOCKED", result["status"])
            self.assertEqual(0, result["mutation_count"])
            self.assertFalse((root / ledger_ref).exists())

    def test_dispatch_terminal_source_owner_invariant(self) -> None:
        root = Path(__file__).resolve().parents[1]
        semantic_owner = root / "meta_flow" / "semantics" / "attempt.py"
        projector_owner = root / "meta_flow" / "state" / "event_ledger.py"
        consumers = (
            projector_owner,
            root / "meta_flow" / "checks" / "cp_result.py",
            root / "meta_flow" / "checks" / "audit_report.py",
            root / "meta_flow" / "checks" / "handoff_dispatch.py",
            root / "meta_flow" / "evidence" / "dispatch.py",
        )
        protected_names = {
            "TERMINAL_SUCCESS_STATUSES",
            "TERMINAL_SUCCESS_RESULTS",
            "TERMINAL_ATTEMPT_STATUSES",
            "NONTERMINAL_ATTEMPT_STATUSES",
            "ALL_ATTEMPT_STATUSES",
        }

        owner_tree = ast.parse(semantic_owner.read_text(encoding="utf-8"))
        owner_assignments = {
            target.id
            for node in ast.walk(owner_tree)
            if isinstance(node, (ast.Assign, ast.AnnAssign))
            for target in (
                node.targets
                if isinstance(node, ast.Assign)
                else [node.target]
            )
            if isinstance(target, ast.Name) and target.id in protected_names
        }
        projector_tree = ast.parse(projector_owner.read_text(encoding="utf-8"))
        projector_owners = [
            node
            for node in ast.walk(projector_tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "project_dispatch_attempt"
        ]

        private_owners: list[str] = []
        for consumer in consumers:
            tree = ast.parse(consumer.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                    continue
                targets = (
                    node.targets
                    if isinstance(node, ast.Assign)
                    else [node.target]
                )
                if any(
                    isinstance(target, ast.Name)
                    and target.id in protected_names
                    for target in targets
                ):
                    private_owners.append(consumer.relative_to(root).as_posix())

        self.assertEqual(protected_names, owner_assignments)
        self.assertEqual(1, len(projector_owners))
        self.assertEqual([], private_owners)

    def test_public_cp_result_commands_resolve_sibling_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process = init_paired_binding(Path(directory))
            result_path = process / "checks" / "CP6-STORY-CR123-S01.result.json"
            result_path.parent.mkdir(parents=True)
            payload = cp6_result_payload()
            payload["summary_ref"] = (
                "process/checks/CP6-STORY-CR123-S01-CODING-DONE.md"
            )
            result_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            outputs: list[str] = []
            for argv in (
                [
                    "result-check",
                    "--result",
                    "process/checks/CP6-STORY-CR123-S01.result.json",
                    "--project-root",
                    str(release),
                ],
                [
                    "render-summary",
                    "--result",
                    "process/checks/CP6-STORY-CR123-S01.result.json",
                    "--output",
                    "process/checks/CP6-STORY-CR123-S01-CODING-DONE.md",
                    "--project-root",
                    str(release),
                ],
                [
                    "ledger-append",
                    "--result",
                    "process/checks/CP6-STORY-CR123-S01.result.json",
                    "--project-root",
                    str(release),
                ],
            ):
                stream = StringIO()
                with redirect_stdout(stream):
                    exit_code = cp_result.main(argv)
                self.assertEqual(0, exit_code, stream.getvalue())
                outputs.append(stream.getvalue())

            event = json.loads(
                (process / "state" / "CHECKPOINT-LEDGER.ndjson")
                .read_text(encoding="utf-8")
                .splitlines()[-1]
            )
            self.assertEqual(
                "process/checks/CP6-STORY-CR123-S01.result.json",
                event["result_ref"],
            )
            self.assertEqual(
                "process/checks/CP6-STORY-CR123-S01-CODING-DONE.md",
                event["summary_ref"],
            )
            self.assertTrue(
                (process / "checks" / "CP6-STORY-CR123-S01-CODING-DONE.md").is_file()
            )
            self.assertFalse((release / "process").exists())
            rendered = "\n".join(outputs)
            self.assertNotIn(str(release.resolve()), rendered)
            self.assertNotIn(str(process.resolve()), rendered)


class LedgerMigrationTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path, dict[str, dict[str, object]]]:
        release, process = init_paired_binding(root)
        events: dict[str, dict[str, object]] = {
            "dispatch": {
                "schema_version": 1,
                "event_id": "ADE-CR123-S04-completed",
                "dispatch_id": "ADE-CR123-S04",
                "attempt_id": "attempt-1",
                "story_id": "STORY-CR123-S04",
                "event_type": "dispatch",
                "canonical_role": "meta-dev",
                "checkpoint": "CP6",
                "dispatch_mode": "subagent",
                "tool_name": "spawn_agent",
                "status": "completed",
                "terminal_result": "PASS",
                "agent_id": "agent-1",
                "spawned_at": "2026-07-26T00:00:00+00:00",
                "completed_at": "2026-07-26T00:01:00+00:00",
            },
            "handoff": {
                "schema_version": 1,
                "event_id": "HE-CR123-S04",
                "event_type": "handoff",
                "stage": "CP6",
                "from_role": "host-orchestrator",
                "to_role": "meta-dev",
                "context_ref": "process/context/stories/STORY-CR123-S04.CP6.work-packet.json",
                "status": "created",
            },
            "checkpoint": {
                "schema_version": 1,
                "event_id": "CP6-CR123-S04",
                "event_type": "checkpoint_result",
                "checkpoint": "CP6",
                "decision": "PASS",
                "result_ref": "process/checks/CP6-STORY-CR123-S04.result.json",
            },
            "read-expansion": {
                "schema_version": 1,
                "event_id": "RE-CR123-S04",
                "event_type": "read_expansion",
                "requested_path": "process/stories/STORY-CR123-S04-LLD.md",
                "reason": "deep_review",
                "stage": "CP6",
                "agent": "meta-dev",
                "context_ref": "process/context/stories/STORY-CR123-S04.CP6.work-packet.json",
                "allowed_by_policy": True,
                "estimated_tokens": 100,
            },
        }
        for ledger_type, event in events.items():
            ref = ledger_migration.LEDGER_REFS[ledger_type]
            path = process / ref.removeprefix("process/")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        for command in (
            ["git", "config", "user.name", "Meta Flow Test"],
            ["git", "config", "user.email", "meta-flow-test@example.invalid"],
            ["git", "add", "."],
            ["git", "commit", "-m", "fixture"],
        ):
            subprocess.run(
                command,
                cwd=process,
                check=True,
                capture_output=True,
                text=True,
            )
        return release, process, events

    def _authorization(
        self,
        plan: ledger_migration.LedgerMigrationPlanV1,
        *,
        authorization_id: str,
    ) -> ledger_migration.MigrationAuthorizationV1:
        return ledger_migration.MigrationAuthorizationV1.from_dict(
            {
                "schema_version": 1,
                "authorization_id": authorization_id,
                "authorization_source": "typed-user-confirmation",
                "authorization_kind": "ledger-migration",
                "operation": "ledger-migration-apply",
                "decision_ref": "process/checkpoints/CP6-STORY-CR123-S04.md",
                "ledger_type": plan.ledger_type,
                "source_event_ids": list(plan.source_event_ids),
                "expected_process_oid": plan.process_oid,
                "expected_plan_digest": plan.plan_digest,
                "single_use": True,
            }
        )

    def test_c20_c23_four_ledgers_append_successors_without_rewriting_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process, events = self._fixture(Path(directory))

            for index, (ledger_type, event) in enumerate(events.items(), 20):
                with self.subTest(ledger_type=ledger_type):
                    ledger = (
                        process
                        / ledger_migration.LEDGER_REFS[ledger_type].removeprefix("process/")
                    )
                    before = ledger.read_bytes()
                    plan = ledger_migration.plan_ledger_migration(
                        release,
                        ledger_type=ledger_type,
                        source_event_ids=[str(event["event_id"])],
                    )

                    self.assertEqual("READY", plan.decision)
                    self.assertEqual(1, plan.as_dict()["mutation_count"])
                    self.assertNotIn(
                        str(process.resolve()),
                        json.dumps(plan.as_dict(), ensure_ascii=False),
                    )
                    receipt = ledger_migration.apply_ledger_migration(
                        release,
                        plan=plan,
                        authorization=self._authorization(
                            plan,
                            authorization_id=f"AUTH-CR123-S04-C{index}",
                        ),
                    )

                    self.assertEqual("PASS", receipt["decision"])
                    self.assertEqual(1, receipt["mutation_count"])
                    after = ledger.read_bytes()
                    self.assertTrue(after.startswith(before))
                    rows = [
                        json.loads(line)
                        for line in after.decode("utf-8").splitlines()
                        if line.strip()
                    ]
                    successor = rows[-1]
                    self.assertEqual(event["event_id"], successor["supersedes_event_id"])
                    self.assertEqual(2, successor["schema_version"])
                    self.assertEqual(
                        "append-only-successor",
                        successor["migration_kind"],
                    )
                    repeated = ledger_migration.apply_ledger_migration(
                        release,
                        plan=plan,
                        authorization=None,
                    )
                    self.assertEqual("NO_CHANGE", repeated["decision"])
                    self.assertEqual(0, repeated["mutation_count"])

    def test_migration_fails_closed_on_preimage_drift_and_ambiguous_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process, events = self._fixture(Path(directory))
            dispatch = events["dispatch"]
            plan = ledger_migration.plan_ledger_migration(
                release,
                ledger_type="dispatch",
                source_event_ids=[str(dispatch["event_id"])],
            )
            ledger = process / "state" / "AGENT-DISPATCH-LEDGER.ndjson"
            with ledger.open("a", encoding="utf-8") as stream:
                stream.write(
                    json.dumps(
                        {
                            **dispatch,
                            "event_id": "ADE-CR123-S04-running",
                            "status": "running",
                            "terminal_result": "PENDING",
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )

            blocked = ledger_migration.apply_ledger_migration(
                release,
                plan=plan,
                authorization=self._authorization(
                    plan,
                    authorization_id="AUTH-CR123-S04-DRIFT",
                ),
            )

            self.assertEqual("BLOCKED", blocked["decision"])
            self.assertEqual(0, blocked["mutation_count"])
            ambiguous = dict(dispatch)
            ambiguous.pop("attempt_id")
            ledger.write_text(
                json.dumps(ambiguous, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            invalid_plan = ledger_migration.plan_ledger_migration(
                release,
                ledger_type="dispatch",
                source_event_ids=[str(dispatch["event_id"])],
            )
            self.assertEqual("BLOCKED", invalid_plan.decision)
            self.assertIn(
                f"{dispatch['event_id']}:MISSING_SOURCE_FIELD:attempt_id",
                invalid_plan.blockers,
            )

    def test_migration_authorization_rejects_unknown_fields(self) -> None:
        payload = {
            "schema_version": 1,
            "authorization_id": "AUTH-CR123-S04-C20",
            "authorization_source": "typed-user-confirmation",
            "authorization_kind": "ledger-migration",
            "operation": "ledger-migration-apply",
            "decision_ref": "process/checkpoints/CP6-STORY-CR123-S04.md",
            "ledger_type": "dispatch",
            "source_event_ids": ["ADE-CR123-S04-completed"],
            "expected_process_oid": "a" * 40,
            "expected_plan_digest": "b" * 64,
            "single_use": True,
            "unknown": True,
        }
        with self.assertRaisesRegex(
            ledger_migration.LedgerMigrationError,
            "authorization fields mismatch",
        ):
            ledger_migration.MigrationAuthorizationV1.from_dict(payload)


if __name__ == "__main__":
    unittest.main()
