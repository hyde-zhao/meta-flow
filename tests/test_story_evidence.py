from __future__ import annotations

import hashlib
import inspect
import json
import subprocess
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from meta_flow.checks.frozen_cp6_evidence import build_cp6_revalidation_receipt
from meta_flow.context_pack import story_contract
from meta_flow.project.onboarding_contract import canonical_digest
from meta_flow.state import current
from meta_flow.workflow import story_evidence


def write_minimal_state(root: Path) -> None:
    state = current.default_current_state(root)
    state["project_id"] = "fixture-project"
    current.write_current_state(root, state)
    current.refresh_current_entry(root)


def write_cr_summary(root: Path, cr_id: str = "CR-123") -> None:
    path = root / "process" / "changes" / "summaries" / f"{cr_id}.summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"id": cr_id, "status": "active"}) + "\n", encoding="utf-8")


def write_story(root: Path) -> Path:
    path = root / "process" / "stories" / "STORY-CR123-S01.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """---
story_id: STORY-CR123-S01
cr_id: CR-123
title: Migrate manifest owner
feature_refs:
  - data.manifest
feature_design_refs:
  - docs/features/data-manifest/DESIGN.md
lld_policy: technical-note
risk_profile: standard-code
allowed_write_paths:
  - quant_lab/data/manifest/**
  - tests/data/manifest/**
forbidden_write_paths:
  - quant_lab/trading/**
acceptance:
  - legacy manifest can load
verification_plan:
  - pytest tests/data/manifest
authz_policy_refs:
  - NO_CREDENTIAL_READ
---

# Story
""",
        encoding="utf-8",
    )
    return path


def write_feature_doc(root: Path) -> None:
    path = root / "docs" / "features" / "data-manifest" / "DESIGN.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Data Manifest Design\n", encoding="utf-8")


def return_packet_payload(*, touched_path: str = "quant_lab/data/manifest/reader.py") -> dict[str, object]:
    return {
        "schema_version": 1,
        "packet_type": "story_return_packet",
        "stage": "CP6",
        "cr_id": "CR-123",
        "story_id": "STORY-CR123-S01",
        "status": "implemented",
        "touched_files": [{"path": touched_path, "change_type": "modified"}],
        "contract_changes": {
            "public_api_changed": False,
            "data_contract_changed": False,
            "design_delta_required": False,
            "design_delta_ref": None,
        },
        "boundary_check": {
            "allowed_paths_only": True,
            "forbidden_paths_touched": [],
            "unexpected_imports": [],
        },
        "verification": {
            "commands_run": [{"command": "pytest tests/data/manifest", "result": "pass"}],
            "tests": [],
            "skipped": [],
        },
        "open_questions": [],
        "risks": [],
        "waivers": [],
        "next_stage_recommendation": "ready_for_cp7",
    }


def write_return_packet(root: Path, *, touched_path: str = "quant_lab/data/manifest/reader.py") -> Path:
    path = root / "process" / "returns" / "STORY-CR123-S01.CP6.return.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    packet = return_packet_payload(touched_path=touched_path)
    path.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


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


def write_bound_return_contract(process: Path) -> None:
    packet_path = process / "context" / "stories" / "STORY-CR123-S01.CP6.work-packet.json"
    packet_path.parent.mkdir(parents=True)
    packet_path.write_text(
        json.dumps(
            {
                "story_id": "STORY-CR123-S01",
                "stage": "CP6",
                "expected_return_packet": "process/returns/STORY-CR123-S01.CP6.return.json",
                "allowed_write_paths": ["quant_lab/data/manifest/**"],
                "forbidden_write_paths": ["quant_lab/trading/**"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return_path = process / "returns" / "STORY-CR123-S01.CP6.return.json"
    return_path.parent.mkdir(parents=True)
    return_path.write_text(
        json.dumps(return_packet_payload(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_bound_verify_story(process: Path) -> None:
    summary = process / "changes" / "summaries" / "CR-123.summary.json"
    summary.parent.mkdir(parents=True)
    summary.write_text(
        json.dumps({"id": "CR-123", "status": "active"}) + "\n",
        encoding="utf-8",
    )
    story = process / "stories" / "STORY-CR123-S01.md"
    story.parent.mkdir(parents=True)
    story.write_text(
        """---
story_id: STORY-CR123-S01
cr_id: CR-123
title: Migrate manifest owner
feature_refs:
  - data.manifest
feature_design_refs:
  - docs/features/data-manifest/DESIGN.md
feature_contract_summary: Manifest ownership is explicit.
cr_delta_summary: Verify the CP6 implementation.
dependency_inputs:
  - CP6 Return Packet
lld_policy: technical-note
risk_profile: standard-code
allowed_write_paths:
  - process/checks/**
forbidden_write_paths:
  - meta_flow/**
acceptance:
  - legacy manifest can load
verification_plan:
  - pytest tests/data/manifest
authz_policy_refs:
  - NO_CREDENTIAL_READ
---

# Story
""",
        encoding="utf-8",
    )


def write_cp6_projection_fixture(process: Path) -> Path:
    plan_path = process / "DEVELOPMENT-PLAN.yaml"
    plan_path.write_text(
        json.dumps(
            {
                "story_management_truth_source": "process/DEVELOPMENT-PLAN.yaml",
                "waves": [
                    {
                        "wave_id": "W1",
                        "stories": [
                            {
                                "story_id": "STORY-CR123-S01",
                                "title": "Upstream",
                                "wave": "W1",
                                "status": "dev-ready",
                                "depends_on": [],
                                "dev_gate": {
                                    "cp5_confirmed": True,
                                    "dependencies_satisfied": True,
                                    "file_conflict_free": True,
                                    "implementation_authorized": True,
                                    "lld_confirmed": True,
                                },
                            },
                            {
                                "story_id": "STORY-CR123-S02",
                                "title": "Downstream",
                                "wave": "W1",
                                "status": "lld-approved",
                                "depends_on": ["STORY-CR123-S01"],
                                "dev_gate": {
                                    "cp5_confirmed": True,
                                    "dependencies_satisfied": False,
                                    "file_conflict_free": True,
                                    "implementation_authorized": False,
                                    "lld_confirmed": True,
                                },
                            },
                        ],
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    result = {
        "schema_version": 1,
        "checkpoint": "CP6",
        "checkpoint_id": "CP6-STORY-CR123-S01",
        "profile": "standard-code",
        "story_id": "STORY-CR123-S01",
        "cr_id": "CR-123",
        "context_ref": "process/context/stories/STORY-CR123-S01.CP6.work-packet.json",
        "dispatch_refs": ["DISPATCH-CR123-S01"],
        "evidence_ref": "process/evidence/STORY-CR123-S01.CP6.index.json",
        "items": [
            {
                "id": "CP6-01",
                "name": "implementation",
                "status": "PASS",
                "severity": "BLOCKER",
                "evidence_refs": ["process/evidence/STORY-CR123-S01.CP6.index.json"],
            }
        ],
        "blockers": [],
        "waivers": [],
        "decision": "PASS",
        "next_route": "STORY-CR123-S02-CP6",
        "checked_at": "2026-07-26T00:00:00+00:00",
        "event_id": "CP6-STORY-CR123-S01-RESULT-V1",
    }
    result_path = process / "checks" / "CP6-STORY-CR123-S01.result.json"
    result_path.parent.mkdir(parents=True)
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    checkpoint = process / "state" / "CHECKPOINT-LEDGER.ndjson"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text(
        json.dumps(
            {
                "event_id": result["event_id"],
                "event_type": "checkpoint_result",
                "checkpoint": "CP6",
                "decision": "PASS",
                "result_ref": "process/checks/CP6-STORY-CR123-S01.result.json",
                "story_id": "STORY-CR123-S01",
                "cr_id": "CR-123",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return result_path


class StoryEvidenceTests(unittest.TestCase):
    def test_a3_tc12_tc14_triple_preflight_contract_cases_are_independent(self) -> None:
        """TC12/13/14: 每个 route/requirement case 都需要 resolver 与 I/O 观测 API。"""
        counters = {"resolve": 0, "exists": 0, "read": 0}
        def resolve(_ref):
            counters["resolve"] += 1
            return {"status": "ready"}
        def exists(_ref):
            counters["exists"] += 1
            return True
        def read(_ref):
            counters["read"] += 1
            return b"payload"
        required = {"logical_ref": "process/targets/X.json", "consumer_requirement": "required", "expected_bytes_digest": hashlib.sha256(b"payload").hexdigest()}
        ready = story_evidence.validate_cp6_revalidation_input_contract(input_spec=required, resolve=resolve, exists=exists, read=read)
        self.assertEqual(("READY", 1), (ready["decision"], ready["read_count"]))
        self.assertEqual({"resolve": 1, "exists": 1, "read": 1}, counters)
        for status in ("missing", "malformed", "provider-unavailable"):
            counters.update(resolve=0, exists=0, read=0)
            result = story_evidence.validate_cp6_revalidation_input_contract(input_spec=required, resolve=lambda _ref, s=status: {"status": s}, exists=exists, read=read)
            self.assertEqual(("BLOCKED", 0), (result["decision"], result["read_count"]))
            self.assertEqual(0, counters["read"])
        counters.update(resolve=0, exists=0, read=0)
        missing_target = story_evidence.validate_cp6_revalidation_input_contract(
            input_spec=required, resolve=resolve, exists=lambda _ref: False, read=read,
        )
        self.assertEqual(("BLOCKED", 0), (missing_target["decision"], missing_target["read_count"]))
        self.assertEqual(0, counters["read"])
        counters.update(resolve=0, exists=0, read=0)
        digest_mismatch = story_evidence.validate_cp6_revalidation_input_contract(
            input_spec=required, resolve=resolve, exists=exists, read=lambda _ref: b"different",
        )
        self.assertEqual(("BLOCKED", 1), (digest_mismatch["decision"], digest_mismatch["read_count"]))
        for requirement in ("optional", "N/A", "forbidden"):
            counters.update(resolve=0, exists=0, read=0)
            result = story_evidence.validate_cp6_revalidation_input_contract(input_spec={**required, "consumer_requirement": requirement}, resolve=resolve, exists=exists, read=read)
            self.assertIn(result["decision"], {"READY", "NOT_REQUIRED"})
            self.assertEqual({"resolve": 0, "exists": 0, "read": 0}, counters)

    def test_a3_tc11_tc15_exact_one_and_spine_mismatch_cases_are_independent(self) -> None:
        """TC11/15: P01 0/1/>1/current/stale 和八项 spine/lineage 各自有子测试。"""
        self.test_a003_pgr3_f004_real_p01_packet_and_input_spec()
        self.test_a003_pgr3_f005_spine_recovery_downstream_observations()

    def test_a3_tc18_same_attempt_completion_recovery_contract(self) -> None:
        attempt = f"attempt-{uuid.uuid4().hex}"
        downstream_set = [{"producer": "I01", "receipt_digest": "a" * 64, "attempt_id": attempt}]
        identity = {
            "cr_id": "CR-X", "story_id": "STORY-X", "work_id": "W-X",
            "attempt_id": attempt, "release_oid": "b" * 40,
            "process_oid": "c" * 40, "scope_digest": "d" * 64,
        }
        authorization = build_cp6_revalidation_receipt(
            kind="authorization", **identity,
            payload={
                "previous_cp6_ref": "process/checks/previous.json",
                "superseding_cp5_ref": "process/checks/cp5.json",
                "approval_ref": "process/checkpoints/approval.json",
                "work_authorization_ref": "process/works/W-X/WORK.yaml",
                "plan_preimage_digest": "e" * 64,
                "downstream_set_digest": canonical_digest(downstream_set),
                "downstream_set": downstream_set,
            },
        )
        preflight = build_cp6_revalidation_receipt(
            kind="preflight", **identity,
            payload={
                "authorization_digest": authorization.as_dict()["payload_digest"],
                "packet_digest": "1" * 64, "read_log_digest": "2" * 64,
                "return_digest": "3" * 64, "evidence_digest": "4" * 64,
                "result_digest": "5" * 64, "checkpoint_digest": "6" * 64,
                "plan_digest": "7" * 64,
                "downstream_set_digest": canonical_digest(downstream_set),
                "p01_event_ref": "process/state/READ-EXPANSION-LEDGER.ndjson",
            },
        )

        def projection_observation(*, current_attempt=attempt, preflight_digest=None):
            inner = {
                "schema_version": 1, "kind": "projection", "cr_id": "CR-X",
                "story_id": "STORY-X", "work_id": "W-X", "attempt_id": current_attempt,
                "preflight_digest": preflight_digest or preflight.as_dict()["payload_digest"],
                "phase": "COMPLETE",
            }
            raw = (json.dumps(inner, sort_keys=True) + "\n").encode()
            return {
                "logical_ref": "process/receipts/projection.json", "bytes": raw,
                "bytes_digest": hashlib.sha256(raw).hexdigest(), **inner,
            }

        projection = projection_observation()

        def recover(target: Path, *, current_preflight=preflight, current_projection=projection,
                    writer=None, reader=story_evidence._read_json) -> dict:
            observation = {
                "logical_ref": "process/receipts/completion.json", "path": target,
                "exists": target.exists(),
                "preimage_digest": hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else "",
            }
            return story_evidence.recover_missing_cp6_revalidation_completion(
                authorization=authorization, preflight=current_preflight,
                projection=current_projection, target_observation=observation,
                create_once_writer=writer or story_evidence._create_once_json,
                postcheck_reader=reader,
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "completion.json"
            recovered = recover(target)
            self.assertEqual(("RECOVERED", 1), (recovered["status"], recovered["mutation_count"]))
            self.assertTrue(target.is_file())
            replay = recover(target)
            self.assertEqual(("NO_CHANGE", 0), (replay["status"], replay["mutation_count"]))

            for name, changed_preflight, changed_projection in (
                ("cross-attempt", preflight, projection_observation(current_attempt="attempt-other")),
                (
                    "cross-authorization",
                    build_cp6_revalidation_receipt(
                        kind="preflight", **identity,
                        payload={**preflight.payload, "authorization_digest": "0" * 64},
                    ),
                    projection,
                ),
                ("cross-projection", preflight, projection_observation(preflight_digest="0" * 64)),
            ):
                blocked_target = root / f"{name}.json"
                blocked = recover(
                    blocked_target, current_preflight=changed_preflight,
                    current_projection=changed_projection,
                )
                self.assertEqual(("BLOCKED", 0), (blocked["decision"], blocked["mutation_count"]))
                self.assertFalse(blocked_target.exists())

            conflict = root / "conflict.json"
            conflict.write_text('{"different":true}\n', encoding="utf-8")
            conflict_before = conflict.read_bytes()
            conflict_result = recover(conflict)
            self.assertEqual(("BLOCKED", 0), (conflict_result["decision"], conflict_result["mutation_count"]))
            self.assertEqual(conflict_before, conflict.read_bytes())

            corrupt_target = root / "corrupt-completion.json"

            def corrupt_then_fail(path: Path, _data: dict) -> None:
                path.write_bytes(b"corrupt")
                raise OSError("post-mutation-interrupt")

            corrupt = recover(corrupt_target, writer=corrupt_then_fail)
            self.assertEqual(("PARTIAL", 1), (corrupt["decision"], corrupt["mutation_count"]))
            self.assertEqual(b"corrupt", corrupt_target.read_bytes())

            for name, reader in (
                ("postcheck-unavailable", lambda _path: (_ for _ in ()).throw(OSError("unavailable"))),
                ("postcheck-mismatch", lambda _path: {"unexpected": True}),
            ):
                partial_target = root / f"{name}.json"
                partial = recover(partial_target, reader=reader)
                self.assertEqual(("PARTIAL", 1), (partial["decision"], partial["mutation_count"]))
                self.assertTrue(partial_target.is_file())

    def test_a3_tc19_tc22_validated_downstream_fixture_matrix(self) -> None:
        consumers = {
            "I01": ["P02"], "R01": ["I01"], "C01": ["I01"],
            "W2": ["I01", "R01", "C01"],
        }
        policy_payload = {"schema_version": 1, "consumers": consumers}
        bound_policy = {**policy_payload, "policy_digest": canonical_digest(policy_payload)}
        plan_payload = {"authorization_digest": "f" * 64, "bound_policy": bound_policy}
        plan_observation = {**plan_payload, "plan_digest": canonical_digest(plan_payload)}
        current_attempt = {
            "story_id": "STORY-X", "attempt_id": "attempt-policy-9c2d",
            "plan_digest": plan_observation["plan_digest"],
        }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case_ordinals = {
                name: index for index, name in enumerate((
                    "ready", "wrong-producer", "wrong-story", "wrong-consumer",
                    "wrong-attempt", "not-current", "superseded", "wrong-policy",
                    "missing", "extra", "wrong-order", "bad-version", "bad-auth",
                    "valid-wrong-auth", "wrong-digest", "selector-missing",
                ), start=1)
            }
            consumer_ordinals = {name: index for index, name in enumerate(consumers, start=1)}
            expected_reasons = {
                "wrong-producer": "DOWNSTREAM_RECEIPT_PRODUCER_MISMATCH",
                "wrong-story": "DOWNSTREAM_RECEIPT_STORY_MISMATCH",
                "wrong-consumer": "DOWNSTREAM_RECEIPT_CONSUMER_MISMATCH",
                "wrong-attempt": "DOWNSTREAM_RECEIPT_ATTEMPT_MISMATCH",
                "not-current": "DOWNSTREAM_RECEIPT_NOT_CURRENT",
                "superseded": "DOWNSTREAM_RECEIPT_SUPERSEDED",
                "wrong-policy": "DOWNSTREAM_POLICY_DIGEST_MISMATCH",
                "missing": "DOWNSTREAM_RECEIPT_SET_MISSING",
                "extra": "DOWNSTREAM_RECEIPT_SET_EXTRA",
                "wrong-order": "DOWNSTREAM_RECEIPT_ORDER_MISMATCH",
                "bad-version": "DOWNSTREAM_POLICY_VERSION_INVALID",
                "bad-auth": "DOWNSTREAM_AUTHORIZATION_DIGEST_INVALID",
                "valid-wrong-auth": "DOWNSTREAM_AUTHORIZATION_DIGEST_MISMATCH",
                "wrong-digest": "DOWNSTREAM_RECEIPT_DIGEST_MISMATCH",
                "selector-missing": "DOWNSTREAM_CURRENT_SELECTOR_INVALID",
            }

            def execute(consumer: str, case: str):
                # API-visible path/ref 只使用中性序号，case label 不进入 production 输入。
                case_root = root / f"d{case_ordinals[case]:02d}" / f"c{consumer_ordinals[consumer]:02d}"
                case_root.mkdir(parents=True)
                payloads = [
                    {
                        "schema_version": 1, "producer": producer, "consumer": consumer,
                        "story_id": "STORY-X", "attempt_id": current_attempt["attempt_id"],
                    }
                    for producer in consumers[consumer]
                ]
                if case == "wrong-producer":
                    payloads[0]["producer"] = "X01"
                elif case == "wrong-story":
                    payloads[0]["story_id"] = "STORY-OTHER"
                elif case == "wrong-consumer":
                    payloads[0]["consumer"] = "OTHER"
                elif case == "wrong-attempt":
                    payloads[0]["attempt_id"] = "attempt-old"
                refs = []
                paths = {}
                expected_current = {}
                for index, payload in enumerate(payloads):
                    ref = f"process/receipts/r{index:02d}.json"
                    path = case_root / f"r{index:02d}.json"
                    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
                    refs.append(ref)
                    paths[ref] = path
                    expected_producer = consumers[consumer][index]
                    expected_current[(expected_producer, consumer)] = ref
                if case == "missing":
                    refs = refs[:-1]
                elif case == "extra":
                    extra_ref = "process/receipts/r99.json"
                    extra_path = case_root / "r99.json"
                    extra_path.write_text(
                        json.dumps({**payloads[0], "producer": "EXTRA"}, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    refs.append(extra_ref)
                    paths[extra_ref] = extra_path
                elif case == "wrong-order":
                    refs = list(reversed(refs))

                authorized_downstream_set = [
                    {
                        "producer": producer,
                        "receipt_digest": hashlib.sha256(
                            paths[f"process/receipts/r{index:02d}.json"].read_bytes()
                        ).hexdigest(),
                        "attempt_id": current_attempt["attempt_id"],
                    }
                    for index, producer in enumerate(consumers[consumer])
                ]

                resolve_calls = []
                selector_calls = []

                def resolve_receipt(ref: str) -> bytes:
                    resolve_calls.append(ref)
                    return paths[ref].read_bytes()

                def select_current(producer: str, selected_consumer: str) -> dict:
                    selector_calls.append((producer, selected_consumer))
                    current_ref = expected_current.get((producer, selected_consumer), "")
                    if case == "not-current":
                        current_ref = "process/receipts/r98.json"
                    if case == "selector-missing":
                        return {"current_ref": current_ref}
                    return {
                        "current_ref": current_ref,
                        "superseded_by": "process/receipts/r98.json" if case == "superseded" else "",
                    }

                observed_plan = dict(plan_observation)
                if case == "wrong-policy":
                    observed_plan["bound_policy"] = {
                        **bound_policy, "policy_digest": "0" * 64,
                    }
                elif case == "bad-version":
                    invalid_policy_payload = {"schema_version": 999, "consumers": consumers}
                    invalid_policy = {
                        **invalid_policy_payload,
                        "policy_digest": canonical_digest(invalid_policy_payload),
                    }
                    invalid_plan = {
                        "authorization_digest": plan_observation["authorization_digest"],
                        "bound_policy": invalid_policy,
                    }
                    observed_plan = {
                        **invalid_plan, "plan_digest": canonical_digest(invalid_plan),
                    }
                elif case == "bad-auth":
                    invalid_plan = {
                        "authorization_digest": "not-a-digest",
                        "bound_policy": bound_policy,
                    }
                    observed_plan = {
                        **invalid_plan, "plan_digest": canonical_digest(invalid_plan),
                    }
                elif case == "valid-wrong-auth":
                    invalid_plan = {
                        "authorization_digest": "e" * 64,
                        "bound_policy": bound_policy,
                    }
                    observed_plan = {
                        **invalid_plan, "plan_digest": canonical_digest(invalid_plan),
                    }
                if case == "wrong-digest":
                    authorized_downstream_set[0] = {
                        **authorized_downstream_set[0],
                        "receipt_digest": "0" * 64,
                    }
                result = story_evidence.admit_revalidation_downstream_receipts(
                    consumer=consumer, receipt_refs=refs, plan_observation=observed_plan,
                    current_attempt=current_attempt, resolve_receipt=resolve_receipt,
                    expected_authorization_digest=plan_observation["authorization_digest"],
                    authorized_downstream_set=authorized_downstream_set,
                    select_current=select_current,
                )
                return result, refs, resolve_calls, selector_calls

            for consumer, producers in consumers.items():
                result, refs, resolve_calls, selector_calls = execute(consumer, "ready")
                with self.subTest(consumer=consumer, case="ready"):
                    self.assertEqual(("READY", 0), (result["decision"], result["mutation_count"]))
                    self.assertEqual(refs, resolve_calls)
                    self.assertEqual([(producer, consumer) for producer in producers], selector_calls)
                for case in (
                    "wrong-producer", "wrong-story", "wrong-consumer", "wrong-attempt",
                    "not-current", "superseded", "wrong-policy", "bad-version", "bad-auth",
                    "valid-wrong-auth", "wrong-digest", "selector-missing",
                ):
                    blocked, _refs, _resolve_calls, _selector_calls = execute(consumer, case)
                    with self.subTest(consumer=consumer, case=case):
                        self.assertEqual(("BLOCKED", 0), (blocked["decision"], blocked["mutation_count"]))
                        self.assertIn(expected_reasons[case], blocked["reason_codes"])

            for case in ("missing", "extra", "wrong-order"):
                blocked, _refs, _resolve_calls, _selector_calls = execute("W2", case)
                with self.subTest(consumer="W2", case=case):
                    self.assertEqual(("BLOCKED", 0), (blocked["decision"], blocked["mutation_count"]))
                    self.assertIn(expected_reasons[case], blocked["reason_codes"])

    # A3 mapping: TC06..18 plan/preflight/write/recovery; TC19..22 downstream;
    # COMP03/05/06/07 command, P01, chain and route boundaries.
    def test_a3_tc19_tc22_downstream_rejects_unvalidated_short_caller_mapping(self) -> None:
        result = story_evidence.admit_revalidation_downstream(
            consumer="W2", expected_digests={"I01": "1", "R01": "2", "C01": "3"},
            current_digests={"I01": "1", "R01": "2", "C01": "3"},
        )
        self.assertEqual(("BLOCKED", 0), (result["decision"], result["mutation_count"]))

    def test_a3_tc17_real_atomic_write_faults_are_typed_and_create_once_is_race_safe(self) -> None:
        def authorization(attempt_id: str, receipt_digest: str):
            downstream_set = [
                {"producer": "I01", "receipt_digest": receipt_digest, "attempt_id": attempt_id},
            ]
            return build_cp6_revalidation_receipt(
                kind="authorization", cr_id="CR-X", story_id="STORY-X", work_id="W-X",
                attempt_id=attempt_id, release_oid="a" * 40, process_oid="b" * 40,
                scope_digest="c" * 64,
                payload={
                    "previous_cp6_ref": "process/checks/previous.json",
                    "superseding_cp5_ref": "process/checks/cp5.json",
                    "approval_ref": "process/checkpoints/approval.json",
                    "work_authorization_ref": "process/works/W-X/WORK.yaml",
                    "plan_preimage_digest": "d" * 64,
                    "downstream_set_digest": canonical_digest(downstream_set),
                    "downstream_set": downstream_set,
                },
            )

        source = {"release_oid": "a" * 40, "process_oid": "b" * 40, "scope_digest": "c" * 64}
        target_observation = {
            "logical_ref": "process/receipts/race.json", "exists": False, "preimage_digest": "",
        }

        def make_plan(receipt):
            policy = {
                "schema_version": 1,
                "logical_ref": "process/works/W-X/revalidation/POLICY.json",
                "bytes_digest": "9" * 64,
                "consumers": {"I01": ["P02"]},
                "policy_digest": canonical_digest({"I01": ["P02"]}),
                "current_receipts": receipt.payload["downstream_set"],
            }
            plan = story_evidence.plan_cp6_revalidation(
                receipt, source_observation=source, target_observation=target_observation,
                downstream_policy=policy,
            )
            current = {
                "source_observation": source, "target_observation": target_observation,
                "downstream_policy": policy,
            }
            return plan, current

        first = authorization("attempt-race-a", "1" * 64)
        second = authorization("attempt-race-b", "2" * 64)
        first_plan, first_current = make_plan(first)
        second_plan, second_current = make_plan(second)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prewrite_target = root / "prewrite.json"
            before_write = story_evidence.apply_cp6_revalidation_receipt(
                prewrite_target, first, expected_plan_digest=first_plan["plan_digest"],
                plan=first_plan["plan"], observe_current=lambda: first_current,
                create_once_writer=lambda _path, _data: (_ for _ in ()).throw(OSError("disk-full")),
                postcheck_reader=story_evidence._read_json,
            )
            self.assertEqual(("BLOCKED", 0), (before_write["decision"], before_write["mutation_count"]))
            self.assertFalse(prewrite_target.exists())

            corrupt_target = root / "corrupt.json"

            def corrupt_then_fail(path: Path, _data: dict) -> None:
                path.write_bytes(b"corrupt")
                raise OSError("post-mutation-interrupt")

            corrupt = story_evidence.apply_cp6_revalidation_receipt(
                corrupt_target, first, expected_plan_digest=first_plan["plan_digest"],
                plan=first_plan["plan"], observe_current=lambda: first_current,
                create_once_writer=corrupt_then_fail,
                postcheck_reader=story_evidence._read_json,
            )
            self.assertEqual(("PARTIAL", 1), (corrupt["decision"], corrupt["mutation_count"]))
            self.assertEqual(b"corrupt", corrupt_target.read_bytes())

            target = root / "race.json"

            def apply(receipt, plan, current):
                return story_evidence.apply_cp6_revalidation_receipt(
                    target, receipt, expected_plan_digest=plan["plan_digest"], plan=plan["plan"],
                    observe_current=lambda: current,
                    create_once_writer=story_evidence._create_once_json,
                    postcheck_reader=story_evidence._read_json,
                )

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(
                    lambda arguments: apply(*arguments),
                    ((first, first_plan, first_current), (second, second_plan, second_current)),
                ))
            self.assertEqual(1, sum(result["status"] == "APPLIED" for result in results))
            self.assertEqual(1, sum(result["decision"] == "BLOCKED" for result in results))
            self.assertIn(story_evidence._read_json(target), (first.as_dict(), second.as_dict()))

            interrupted_target = root / "interrupted.json"

            def write_then_fail(path: Path, data: dict) -> None:
                story_evidence._create_once_json(path, data)
                raise OSError("post-write-interrupt")

            interrupted = story_evidence.apply_cp6_revalidation_receipt(
                interrupted_target, first, expected_plan_digest=first_plan["plan_digest"],
                plan=first_plan["plan"], observe_current=lambda: first_current,
                create_once_writer=write_then_fail, postcheck_reader=story_evidence._read_json,
            )
            self.assertEqual(("PARTIAL", 1), (interrupted["decision"], interrupted["mutation_count"]))
            self.assertEqual(first.as_dict(), story_evidence._read_json(interrupted_target))

    def _p02_authorization(self):
        downstream_set = [
            {"producer": "I01", "receipt_digest": "f" * 64, "attempt_id": "attempt-1"},
        ]
        return build_cp6_revalidation_receipt(
            kind="authorization", cr_id="CR-068", story_id="STORY-CR068-P02",
            work_id="CR-068-P02-IMPLEMENTATION-001", attempt_id="attempt-1",
            release_oid="a" * 40, process_oid="b" * 40, scope_digest="c" * 64,
            payload={
                "previous_cp6_ref": "process/checks/CP6-P01.json",
                "superseding_cp5_ref": "process/checks/CP5-P02.json",
                "approval_ref": "process/checkpoints/GATE-P02.md",
                "work_authorization_ref": "process/works/CR-068-P02-IMPLEMENTATION-001/WORK.yaml",
                "plan_preimage_digest": "d" * 64,
                "downstream_set_digest": canonical_digest(downstream_set),
                "downstream_set": downstream_set,
            },
        )

    def test_p02_preflight_partial_and_downstream_admission_fail_closed(self) -> None:
        authorization = self._p02_authorization()
        required = {key: "f" * 64 for key in (
            "packet_digest", "read_log_digest", "return_digest", "evidence_digest",
            "result_digest", "checkpoint_digest", "plan_digest", "downstream_set_digest",
        )}
        required["downstream_set_digest"] = authorization.payload["downstream_set_digest"]
        packet = {
            "schema_version": 3, "lld_policy": "full-lld",
            "read_if_needed": [{
                "path": "process/stories/STORY-CR068-P02-LLD.md",
                "trigger": "full_lld_required_by_policy", "consumer_requirement": "required",
            }],
        }
        selected = ["process/stories/STORY-CR068-P02-LLD.md"]
        p01_event = {
            "packet": packet, "selected_refs": selected,
            "selection_digest": canonical_digest(selected),
            "story_id": authorization.story_id, "work_id": authorization.work_id,
            "attempt_id": authorization.attempt_id, "stage": "CP6",
            "context_ref": "process/context/P02.json", "scope_digest": authorization.scope_digest,
            "reason": "summary_insufficient", "reason_evidence": {"missing_slots": ["full_lld_body"]},
            "requested_ref": selected[0], "preregistered_by": "host", "bytes_digest": "b" * 64,
        }

        def observe_event(event: dict) -> dict:
            raw = (json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n").encode()
            digest = hashlib.sha256(raw).hexdigest()
            return {
                "logical_ref": "process/state/READ-EXPANSION-LEDGER.ndjson#event-p02",
                "event_bytes": raw,
                "event_bytes_digest": digest,
                "current_event_bytes_digest": digest,
            }

        preflight = story_evidence.validate_cp6_revalidation_preflight(
            authorization, required_digests=required, p01_event=observe_event(p01_event),
        )
        self.assertEqual("READY", preflight["decision"])
        self.assertEqual("preflight", preflight["receipt"]["kind"])
        fabricated = story_evidence.validate_cp6_revalidation_preflight(
            authorization, required_digests=required,
            p01_event=observe_event({
                **p01_event,
                "story_id": "STORY-OTHER",
                "work_id": "W-OTHER",
                "attempt_id": "attempt-other",
                "scope_digest": "0" * 64,
            }),
        )
        self.assertEqual(("BLOCKED", 0), (fabricated["decision"], fabricated["mutation_count"]))

    def test_p02_preflight_rejects_nonhex_digest_before_writer(self) -> None:
        authorization = self._p02_authorization()
        required = {key: "f" * 64 for key in (
            "packet_digest", "read_log_digest", "return_digest", "evidence_digest",
            "result_digest", "checkpoint_digest", "plan_digest", "downstream_set_digest",
        )}
        required["plan_digest"] = "z" * 64
        result = story_evidence.validate_cp6_revalidation_preflight(
            authorization, required_digests=required,
            p01_event={
                "story_id": "STORY-CR068-P01-CANONICAL-PREREGISTRATION",
                "event_id": "RE-P01", "selection_digest": "a" * 64, "read_log_digest": "a" * 64,
            },
        )
        self.assertEqual(("BLOCKED", 0), (result["decision"], result["mutation_count"]))
        self.assertEqual(
            "BLOCKED",
            story_evidence.admit_revalidation_downstream(
                consumer="W2", expected_digests={"I01": "1", "R01": "2", "C01": "3"},
                current_digests={"I01": "1", "R01": "stale", "C01": "3"},
            )["decision"],
        )

    def test_return_check_passes_for_valid_cp6_return(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_story(root)
            _packet, work_packet = story_contract.build_story_packet(root, story_path=story, stage="CP6", budget=8000)
            return_path = write_return_packet(root)

            stream = StringIO()
            with redirect_stdout(stream):
                exit_code = story_evidence.main(
                    [
                        "return-check",
                        "--packet",
                        str(work_packet),
                        "--return",
                        str(return_path),
                        "--project-root",
                        str(root),
                    ]
                )

            self.assertEqual(0, exit_code)
            self.assertIn("Story Return Packet Check: OK", stream.getvalue())

    def test_return_check_rejects_touched_file_outside_allowed_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_story(root)
            _packet, work_packet = story_contract.build_story_packet(root, story_path=story, stage="CP6", budget=8000)
            return_path = write_return_packet(root, touched_path="quant_lab/research/scanner.py")

            errors, _warnings = story_evidence.validate_return_packet(return_path, packet_path=work_packet, project_root=root)

            self.assertIn("touched file outside allowed_write_paths: quant_lab/research/scanner.py", errors)

    def test_return_check_rejects_forbidden_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_story(root)
            _packet, work_packet = story_contract.build_story_packet(root, story_path=story, stage="CP6", budget=8000)
            return_path = write_return_packet(root, touched_path="quant_lab/trading/order.py")

            errors, _warnings = story_evidence.validate_return_packet(return_path, packet_path=work_packet, project_root=root)

            self.assertIn("touched file outside allowed_write_paths: quant_lab/trading/order.py", errors)
            self.assertIn("touched file matches forbidden_write_paths: quant_lab/trading/order.py", errors)

    def test_return_check_requires_design_delta_ref_when_needed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_story(root)
            _packet, work_packet = story_contract.build_story_packet(root, story_path=story, stage="CP6", budget=8000)
            return_path = write_return_packet(root)
            packet = json.loads(return_path.read_text(encoding="utf-8"))
            packet["contract_changes"]["design_delta_required"] = True
            packet["contract_changes"]["design_delta_ref"] = ""
            return_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            errors, _warnings = story_evidence.validate_return_packet(return_path, packet_path=work_packet, project_root=root)

            self.assertIn("contract_changes.design_delta_ref is required when design_delta_required=true", errors)

    def test_return_check_accepts_partial_status_without_touched_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_story(root)
            _packet, work_packet = story_contract.build_story_packet(root, story_path=story, stage="CP6", budget=8000)
            return_path = write_return_packet(root)
            packet = json.loads(return_path.read_text(encoding="utf-8"))
            packet["status"] = "partial"
            packet["touched_files"] = []
            packet["verification"]["commands_run"] = []
            return_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            errors, _warnings = story_evidence.validate_return_packet(return_path, packet_path=work_packet, project_root=root)

            self.assertEqual([], errors)

    def test_evidence_index_build_and_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            return_path = write_return_packet(root)

            evidence, output = story_evidence.build_evidence_index(root, return_path=return_path)
            errors, warnings = story_evidence.validate_evidence_index(output, project_root=root)

            self.assertEqual("STORY-CR123-S01", evidence["story_id"])
            self.assertTrue(output.is_file())
            self.assertEqual([], errors)
            self.assertEqual([], warnings)

    def test_public_story_evidence_commands_resolve_sibling_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process = init_paired_binding(Path(directory))
            write_bound_return_contract(process)
            write_bound_verify_story(process)

            outputs: list[str] = []
            for argv in (
                [
                    "return-check",
                    "--packet",
                    "process/context/stories/STORY-CR123-S01.CP6.work-packet.json",
                    "--return",
                    "process/returns/STORY-CR123-S01.CP6.return.json",
                    "--project-root",
                    str(release),
                ],
                [
                    "evidence-index",
                    "--return",
                    "process/returns/STORY-CR123-S01.CP6.return.json",
                    "--project-root",
                    str(release),
                ],
                [
                    "evidence-check",
                    "--index",
                    "process/evidence/STORY-CR123-S01.CP6.index.json",
                    "--project-root",
                    str(release),
                ],
                [
                    "verify-packet",
                    "--from-return",
                    "process/returns/STORY-CR123-S01.CP6.return.json",
                    "--story",
                    "process/stories/STORY-CR123-S01.md",
                    "--project-root",
                    str(release),
                ],
            ):
                stream = StringIO()
                with redirect_stdout(stream):
                    exit_code = story_evidence.main(argv)
                self.assertEqual(0, exit_code, stream.getvalue())
                self.assertNotIn("WARN", stream.getvalue())
                outputs.append(stream.getvalue())

            evidence = json.loads(
                (process / "evidence" / "STORY-CR123-S01.CP6.index.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                "process/returns/STORY-CR123-S01.CP6.return.json",
                evidence["return_ref"],
            )
            verify_packet = json.loads(
                (
                    process
                    / "context"
                    / "stories"
                    / "STORY-CR123-S01.CP7.verify-packet.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(
                "process/returns/STORY-CR123-S01.CP6.return.json",
                verify_packet["implementation_return_ref"],
            )
            self.assertFalse((release / "process").exists())
            rendered = "\n".join(outputs)
            self.assertNotIn(str(release.resolve()), rendered)
            self.assertNotIn(str(process.resolve()), rendered)

    def test_public_return_check_fails_closed_on_broken_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process = init_paired_binding(Path(directory))
            write_bound_return_contract(process)
            binding = release / ".meta-flow" / "workspace.yaml"
            binding.write_text(
                binding.read_text(encoding="utf-8").replace(
                    "relative_path: meta-flow-process",
                    "relative_path: missing-process",
                ),
                encoding="utf-8",
            )

            stream = StringIO()
            with redirect_stdout(stream):
                exit_code = story_evidence.main(
                    [
                        "return-check",
                        "--packet",
                        "process/context/stories/STORY-CR123-S01.CP6.work-packet.json",
                        "--return",
                        "process/returns/STORY-CR123-S01.CP6.return.json",
                        "--project-root",
                        str(release),
                    ]
                )

            self.assertEqual(1, exit_code)
            self.assertIn("Story Return Packet Check: FAIL", stream.getvalue())
            self.assertFalse((release / "process").exists())
            self.assertNotIn(str(release.resolve()), stream.getvalue())
            self.assertNotIn(str(process.resolve()), stream.getvalue())

    def test_public_cp6_projection_dry_run_apply_and_idempotent_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process = init_paired_binding(Path(directory))
            write_cp6_projection_fixture(process)
            before = (process / "DEVELOPMENT-PLAN.yaml").read_bytes()

            dry_run = StringIO()
            with redirect_stdout(dry_run):
                exit_code = story_evidence.main(
                    [
                        "project-cp6",
                        "--project-root",
                        str(release),
                        "--result",
                        "process/checks/CP6-STORY-CR123-S01.result.json",
                    ]
                )
            self.assertEqual(0, exit_code, dry_run.getvalue())
            plan = json.loads(dry_run.getvalue())
            self.assertEqual("READY", plan["decision"])
            self.assertEqual(1, plan["mutation_count"])
            self.assertEqual(before, (process / "DEVELOPMENT-PLAN.yaml").read_bytes())

            applied = StringIO()
            with redirect_stdout(applied):
                exit_code = story_evidence.main(
                    [
                        "project-cp6",
                        "--project-root",
                        str(release),
                        "--result",
                        "process/checks/CP6-STORY-CR123-S01.result.json",
                        "--expected-plan-digest",
                        plan["plan_digest"],
                        "--apply",
                    ]
                )
            self.assertEqual(0, exit_code, applied.getvalue())
            result = json.loads(applied.getvalue())
            self.assertEqual("PASS", result["status"])
            projected = json.loads(
                (process / "DEVELOPMENT-PLAN.yaml").read_text(encoding="utf-8")
            )
            stories = {
                story["story_id"]: story
                for story in projected["waves"][0]["stories"]
            }
            self.assertEqual(
                "ready-for-verification",
                stories["STORY-CR123-S01"]["status"],
            )
            self.assertEqual("dev-ready", stories["STORY-CR123-S02"]["status"])

            replay = StringIO()
            with redirect_stdout(replay):
                exit_code = story_evidence.main(
                    [
                        "project-cp6",
                        "--project-root",
                        str(release),
                        "--result",
                        "process/checks/CP6-STORY-CR123-S01.result.json",
                        "--apply",
                    ]
                )
            self.assertEqual(0, exit_code, replay.getvalue())
            self.assertEqual("NO_CHANGE", json.loads(replay.getvalue())["status"])
            self.assertNotIn(str(process.resolve()), dry_run.getvalue())

    def test_public_cp6_projection_fails_closed_without_checkpoint_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process = init_paired_binding(Path(directory))
            write_cp6_projection_fixture(process)
            checkpoint = process / "state" / "CHECKPOINT-LEDGER.ndjson"
            checkpoint.write_text("", encoding="utf-8")
            before = (process / "DEVELOPMENT-PLAN.yaml").read_bytes()

            stream = StringIO()
            with redirect_stdout(stream):
                exit_code = story_evidence.main(
                    [
                        "project-cp6",
                        "--project-root",
                        str(release),
                        "--result",
                        "process/checks/CP6-STORY-CR123-S01.result.json",
                        "--expected-plan-digest",
                        "0" * 64,
                        "--apply",
                    ]
                )

            self.assertEqual(2, exit_code)
            self.assertEqual("BLOCKED", json.loads(stream.getvalue())["status"])
            self.assertEqual(before, (process / "DEVELOPMENT-PLAN.yaml").read_bytes())

    def test_design_delta_check_warns_pending_and_can_require_merged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_feature_doc(root)
            delta = root / "process" / "design-deltas" / "STORY-CR123-S01.delta.json"
            delta.parent.mkdir(parents=True, exist_ok=True)
            delta.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "story_id": "STORY-CR123-S01",
                        "feature_id": "data.manifest",
                        "delta_type": "patch",
                        "target_doc": "docs/features/data-manifest/DESIGN.md",
                        "changes": [
                            {
                                "section": "Schema Versioning",
                                "operation": "add",
                                "summary": "Add legacy schema_version compatibility.",
                            }
                        ],
                        "requires_feature_doc_update": True,
                        "status": "pending",
                        "merged_ref": None,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            errors, warnings = story_evidence.validate_design_delta(delta, project_root=root)
            merged_errors, _merged_warnings = story_evidence.validate_design_delta(delta, project_root=root, require_merged=True)

            self.assertEqual([], errors)
            self.assertIn("design delta requires feature doc update but is not merged", warnings)
            self.assertIn("design delta status must be merged", merged_errors)

    def test_verify_packet_builds_from_cp6_return(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_story(root)
            return_path = write_return_packet(root)

            packet, output = story_evidence.build_verify_packet_from_return(root, return_path=return_path, story_path=story)

            self.assertEqual("story_verify_packet", packet["packet_type"])
            self.assertEqual("process/returns/STORY-CR123-S01.CP6.return.json", packet["implementation_return_ref"])
        self.assertTrue(output.name.endswith(".CP7.verify-packet.json"))

    def test_a003_pgr3_f003_plan_apply_requires_real_observations(self) -> None:
        """PGR3-F003：plan/apply 必须从 source/target/downstream observation 建立绑定。"""
        authorization = self._p02_authorization()
        source = {
            "release_oid": authorization.release_oid, "process_oid": authorization.process_oid,
            "scope_digest": authorization.scope_digest,
        }
        target_observation = {
            "logical_ref": "process/receipts/a.json", "exists": False, "preimage_digest": "",
        }
        downstream_policy = {
            "schema_version": 1,
            "logical_ref": "process/works/CR-068-P02-IMPLEMENTATION-001/revalidation/POLICY.json",
            "bytes_digest": "9" * 64,
            "consumers": {"I01": ["P02"]},
            "policy_digest": canonical_digest({"I01": ["P02"]}),
            "current_receipts": authorization.payload["downstream_set"],
        }
        plan = story_evidence.plan_cp6_revalidation(
            authorization, source_observation=source, target_observation=target_observation,
            downstream_policy=downstream_policy,
        )
        self.assertEqual("READY", plan["decision"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "a.json"
            current = {
                "source_observation": source, "target_observation": target_observation,
                "downstream_policy": downstream_policy,
            }
            applied = story_evidence.apply_cp6_revalidation_receipt(
                target, authorization, expected_plan_digest=plan["plan_digest"], plan=plan["plan"],
                observe_current=lambda: current,
                create_once_writer=story_evidence._create_once_json,
                postcheck_reader=story_evidence._read_json,
            )
            self.assertEqual("APPLIED", applied["status"])
            replay_current = {
                **current,
                "target_observation": {
                    **target_observation, "exists": True,
                    "preimage_digest": hashlib.sha256(target.read_bytes()).hexdigest(),
                },
            }
            replay = story_evidence.apply_cp6_revalidation_receipt(
                target, authorization, expected_plan_digest=plan["plan_digest"], plan=plan["plan"],
                observe_current=lambda: replay_current,
                create_once_writer=story_evidence._create_once_json,
                postcheck_reader=story_evidence._read_json,
            )
            self.assertEqual("NO_CHANGE", replay["status"])

            drift_cases = (
                ("release", "source_observation", "release_oid", "0" * 40),
                ("process", "source_observation", "process_oid", "0" * 40),
                ("scope", "source_observation", "scope_digest", "0" * 64),
                ("target-ref", "target_observation", "logical_ref", "process/receipts/other.json"),
                ("target-exists", "target_observation", "exists", True),
                ("target-preimage", "target_observation", "preimage_digest", "0" * 64),
                ("policy-version", "downstream_policy", "schema_version", 2),
                ("policy-ref", "downstream_policy", "logical_ref", "process/works/OTHER/POLICY.json"),
                ("policy-bytes", "downstream_policy", "bytes_digest", "0" * 64),
                ("policy", "downstream_policy", "policy_digest", "0" * 64),
                ("current-receipts", "downstream_policy", "current_receipts", []),
            )
            for name, section, key, value in drift_cases:
                drifted = json.loads(json.dumps(current))
                drifted[section][key] = value
                with tempfile.TemporaryDirectory() as isolated_directory:
                    # API 只看到与 logical_ref 对应的中性 a.json；case 名只存在于 subTest。
                    drift_target = Path(isolated_directory) / "a.json"
                    before = drift_target.read_bytes() if drift_target.exists() else None
                    calls = {"observer": 0, "writer": 0}

                    def observe(value=drifted, counter=calls):
                        counter["observer"] += 1
                        return value

                    def fail_writer(_path, _payload, counter=calls):
                        counter["writer"] += 1
                        self.fail("writer called after a plan-bound observation drift")

                    blocked = story_evidence.apply_cp6_revalidation_receipt(
                        drift_target, authorization, expected_plan_digest=plan["plan_digest"],
                        plan=plan["plan"], observe_current=observe,
                        create_once_writer=fail_writer,
                        postcheck_reader=story_evidence._read_json,
                    )
                    with self.subTest(axis=name):
                        self.assertEqual(("BLOCKED", 0), (blocked["decision"], blocked["mutation_count"]))
                        self.assertEqual({"observer": 1, "writer": 0}, calls)
                        after = drift_target.read_bytes() if drift_target.exists() else None
                        self.assertEqual(before, after)

            for name, reader in (
                ("unavailable", lambda _path: (_ for _ in ()).throw(OSError("unavailable"))),
                ("mismatch", lambda _path: {"unexpected": True}),
            ):
                partial_target = root / f"apply-postcheck-{name}.json"
                partial = story_evidence.apply_cp6_revalidation_receipt(
                    partial_target, authorization, expected_plan_digest=plan["plan_digest"],
                    plan=plan["plan"], observe_current=lambda: current,
                    create_once_writer=story_evidence._create_once_json,
                    postcheck_reader=reader,
                )
                self.assertEqual(("PARTIAL", 1), (partial["decision"], partial["mutation_count"]))
                self.assertTrue(partial_target.is_file())

    def test_a003_pgr3_f004_real_p01_packet_and_input_spec(self) -> None:
        """PGR3-F004：P01 selector 消费真实 packet/selected refs，不允许 case sentinel。"""
        packet = {"schema_version": 3, "lld_policy": "full-lld", "read_if_needed": [{"path": "process/stories/STORY-X-LLD.md", "trigger": "full_lld_required_by_policy", "consumer_requirement": "required"}]}
        selected = ["process/stories/STORY-X-LLD.md"]
        event = {"packet": packet, "selected_refs": selected, "selection_digest": canonical_digest(selected),
                 "story_id": "STORY-X", "stage": "CP6", "context_ref": "process/context/X.json", "work_id": "W-X",
                 "scope_digest": "a" * 64, "reason": "summary_insufficient", "reason_evidence": {"missing_slots": ["full_lld_body"]},
                 "requested_ref": selected[0], "preregistered_by": "host",
                 "bytes_digest": hashlib.sha256(b"lld-bytes").hexdigest()}
        identity = {
            "story_id": "STORY-X", "work_id": "W-X", "stage": "CP6",
            "context_ref": "process/context/X.json", "scope_digest": "a" * 64,
        }

        def observe_event(payload: dict, *, current_digest: str | None = None) -> dict:
            raw = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode()
            event_digest = hashlib.sha256(raw).hexdigest()
            return {
                "logical_ref": "process/state/READ-EXPANSION-LEDGER.ndjson#event-0001",
                "event_bytes": raw,
                "event_bytes_digest": event_digest,
                "current_event_bytes_digest": current_digest or event_digest,
            }

        observation = observe_event(event)
        self.assertEqual(
            "READY",
            story_evidence.validate_p01_preregistration_exact_one(
                packet=packet, ledger_events=[observation], expected_identity=identity,
                current_selection_digest=event["selection_digest"],
            )["decision"],
        )
        field_mutations = (
            ("stage", "CP5"), ("context_ref", "process/context/OTHER.json"),
            ("scope_digest", "0" * 64), ("reason", "capsule_missing"),
            ("reason_evidence", {"missing_slots": []}),
            ("requested_ref", "process/stories/OTHER.md"),
            ("preregistered_by", "unknown"), ("packet", {"schema_version": 3}),
            ("story_id", "STORY-OTHER"), ("work_id", "W-OTHER"),
        )
        event_sets = [[], [observation, observation]] + [
            [observe_event({**event, field: value})] for field, value in field_mutations
        ]
        # 两个值都是合法 SHA；拒绝依据必须是 immutable event bytes 与 current head 不一致。
        event_sets.append([
            observe_event(
                {**event, "bytes_digest": "0" * 64},
                current_digest=observation["current_event_bytes_digest"],
            )
        ])
        for events in event_sets:
            self.assertEqual(
                "BLOCKED",
                story_evidence.validate_p01_preregistration_exact_one(
                    packet=packet, ledger_events=events, expected_identity=identity,
                    current_selection_digest=event["selection_digest"],
                )["decision"],
            )

        spec = {
            "logical_ref": "process/targets/X.json", "consumer_requirement": "required",
            "expected_bytes_digest": hashlib.sha256(b"target").hexdigest(),
            "expected_lineage": identity,
        }

        def validate(*, requirement="required", route=None, target_exists=True, payload=b"target"):
            calls = {"resolve": 0, "exists": 0, "read": 0}

            def resolve(_ref):
                calls["resolve"] += 1
                return route or {"status": "ready", **identity}

            def exists(_ref):
                calls["exists"] += 1
                return target_exists

            def read(_ref):
                calls["read"] += 1
                return payload

            result = story_evidence.validate_cp6_revalidation_input_contract(
                input_spec={**spec, "consumer_requirement": requirement},
                resolve=resolve, exists=exists, read=read,
            )
            return result, calls

        ready, calls = validate()
        self.assertEqual(("READY", 1), (ready["decision"], ready["read_count"]))
        self.assertEqual({"resolve": 1, "exists": 1, "read": 1}, calls)
        for status in ("missing", "malformed", "provider-unavailable"):
            blocked, calls = validate(route={"status": status})
            self.assertEqual(("BLOCKED", 0), (blocked["decision"], blocked["read_count"]))
            self.assertEqual({"resolve": 1, "exists": 0, "read": 0}, calls)
        missing, calls = validate(target_exists=False)
        self.assertEqual(("BLOCKED", 0), (missing["decision"], missing["read_count"]))
        self.assertEqual({"resolve": 1, "exists": 1, "read": 0}, calls)
        mismatch, calls = validate(payload=b"different")
        self.assertEqual(("BLOCKED", 1), (mismatch["decision"], mismatch["read_count"]))
        self.assertEqual({"resolve": 1, "exists": 1, "read": 1}, calls)
        lineage, calls = validate(route={"status": "ready", **identity, "story_id": "STORY-OTHER"})
        self.assertEqual(("BLOCKED", 0), (lineage["decision"], lineage["read_count"]))
        self.assertEqual({"resolve": 1, "exists": 0, "read": 0}, calls)
        for requirement in ("optional", "N/A", "forbidden"):
            outcome, calls = validate(requirement=requirement)
            self.assertIn(outcome["decision"], {"READY", "NOT_REQUIRED"})
            self.assertEqual({"resolve": 0, "exists": 0, "read": 0}, calls)

    def test_a003_pgr3_f005_spine_recovery_downstream_observations(self) -> None:
        """PGR3-F005：真实观察 API 必须分别拥有 spine/recovery/policy 入口。"""
        attempt_id = "attempt-spine-5e91"
        authorization = {
            "story_id": "STORY-X", "work_id": "W-X", "attempt_id": attempt_id,
            "payload_digest": "f" * 64,
        }
        roles = (
            ("packet", "context-packet"), ("read_log", "read-expansion-log"),
            ("return", "story-return"), ("evidence", "evidence-index"),
            ("result", "cp6-result"), ("checkpoint", "checkpoint-result"),
            ("plan", "development-plan"), ("downstream", "downstream-receipt-set"),
        )
        observations = []
        previous_digest = ""
        for role, kind in roles:
            inner = {
                "schema_version": 1, "role": role, "kind": kind,
                "story_id": "STORY-X", "work_id": "W-X", "attempt_id": attempt_id,
                "authorization_digest": "f" * 64, "previous_digest": previous_digest,
            }
            raw = (json.dumps(inner, sort_keys=True) + "\n").encode()
            digest = hashlib.sha256(raw).hexdigest()
            observations.append({
                "role": role, "kind": kind, "logical_ref": f"process/evidence/{role}.json",
                "bytes": raw, "bytes_digest": digest,
                "story_id": "STORY-X", "work_id": "W-X", "attempt_id": attempt_id,
                "authorization_digest": "f" * 64, "previous_digest": previous_digest,
            })
            previous_digest = digest
        ready = story_evidence.validate_cp6_revalidation_spine(
            authorization=authorization, observations=observations,
        )
        self.assertEqual("READY", ready["decision"])
        for index, (role, _kind) in enumerate(roles):
            cases = {}
            cases["missing"] = [dict(item) for offset, item in enumerate(observations) if offset != index]
            for name, field, value in (
                ("ref", "logical_ref", "process/../escape"),
                ("digest", "bytes_digest", "0" * 64),
                ("story", "story_id", "STORY-OTHER"),
                ("work", "work_id", "W-OTHER"),
                ("attempt", "attempt_id", "attempt-other"),
                ("authorization", "authorization_digest", "0" * 64),
                ("previous", "previous_digest", "0" * 64),
            ):
                changed = [dict(item) for item in observations]
                changed[index][field] = value
                cases[name] = changed
            for name, changed in cases.items():
                with self.subTest(role=role, mutation=name):
                    result = story_evidence.validate_cp6_revalidation_spine(
                        authorization=authorization, observations=changed,
                    )
                    self.assertEqual(("BLOCKED", 0), (result["decision"], result["mutation_count"]))
            for name, field, value in (
                ("inner-role", "role", "other-role"),
                ("inner-kind", "kind", "other-kind"),
                ("inner-story", "story_id", "STORY-OTHER"),
                ("inner-work", "work_id", "W-OTHER"),
                ("inner-attempt", "attempt_id", "attempt-other"),
                ("inner-authorization", "authorization_digest", "0" * 64),
                ("inner-previous", "previous_digest", "0" * 64),
                ("inner-extra", "extra", True),
            ):
                changed = [dict(item) for item in observations]
                inner = json.loads(changed[index]["bytes"])
                inner[field] = value
                raw = (json.dumps(inner, ensure_ascii=False, sort_keys=True) + "\n").encode()
                changed[index]["bytes"] = raw
                changed[index]["bytes_digest"] = hashlib.sha256(raw).hexdigest()
                with self.subTest(role=role, mutation=name):
                    result = story_evidence.validate_cp6_revalidation_spine(
                        authorization=authorization, observations=changed,
                    )
                    self.assertEqual(("BLOCKED", 0), (result["decision"], result["mutation_count"]))
        reordered = [dict(item) for item in observations]
        reordered[0], reordered[1] = reordered[1], reordered[0]
        extra = [*observations, dict(observations[-1])]
        for name, changed in (("reordered", reordered), ("extra", extra)):
            result = story_evidence.validate_cp6_revalidation_spine(
                authorization=authorization, observations=changed,
            )
            self.assertEqual(("BLOCKED", 0), (result["decision"], result["mutation_count"]), name)

    def test_a003_pgr3_f006_production_has_no_fixture_sentinels(self) -> None:
        """PGR3-F006：阻止 case/literal/fixed-count/统一 READY helper 伪造 GREEN。"""
        source = Path(story_evidence.__file__).read_text(encoding="utf-8")
        for token in ('set(event) == {"case"}', 'attempt_id != "attempt-1"', 'len(receipts) != 3', 'return {"exit_code": 0'):
            with self.subTest(token=token):
                self.assertNotIn(token, source)
        self.assertNotIn("fault", inspect.signature(story_evidence.apply_cp6_revalidation_receipt).parameters)
        self.assertEqual(
            {"request", "services"},
            set(inspect.signature(story_evidence.run_cp6_revalidation_operation).parameters),
        )
        self.assertIn("services", inspect.signature(story_evidence.main).parameters)

    def test_p02_bootstrap_authority_pair_is_create_once_and_never_reads_work(self) -> None:
        """BS-TC-02/04/06/09/10/15：只用临时 fixture 验证两目标闭包。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def resolver(_root: Path, logical: object) -> Path:
                ref = str(logical)
                self.assertFalse(ref.endswith("/WORK.yaml"), "bootstrap must not resolve WORK.yaml")
                return root / ref

            def write(ref: str, payload: dict) -> None:
                path = root / ref
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")

            approval_ref = "process/checkpoints/approval.json"
            previous_ref = "process/checks/previous.json"
            superseding_ref = "process/checks/superseding.json"
            oids = {"release_head": "a" * 40, "process_head": "b" * 40}
            write(approval_ref, {"cr_id": "CR-068"})
            write(previous_ref, {"repository_oids": oids})
            write(superseding_ref, {"repository_oids": oids})
            common = [
                "--project-root", str(root), "--work-ref", "process/works/W-BOOT/WORK.yaml",
                "--story-id", "STORY-CR068-P02-NATIVE-CP6-REVALIDATION",
                "--attempt-id", "attempt-v23", "--approval-ref", approval_ref,
                "--previous-cp6-result-ref", previous_ref,
                "--superseding-cp5-result-ref", superseding_ref,
                "--scope-digest", "c" * 64,
            ]
            with patch.object(story_evidence, "_resolve_runtime_path", side_effect=resolver), patch.object(story_evidence, "_resolve_runtime_ref", side_effect=resolver):
                plan_out = StringIO()
                with redirect_stdout(plan_out):
                    self.assertEqual(0, story_evidence.main(["issue-revalidation-authority", "plan", *common]))
                plan = json.loads(plan_out.getvalue())
                self.assertEqual(("READY", 0), (plan["status"], plan["mutation_count"]))
                self.assertEqual(["authorization-receipt", "authority-binding"], [item["target_kind"] for item in plan["targets"]])
                self.assertEqual(approval_ref, plan["sidecar"]["approval_ref"])
                self.assertIsInstance(plan["sidecar"]["approval_ref"], str)
                self.assertEqual(
                    {
                        "schema_version", "receipt_ref", "receipt_digest", "cr_id",
                        "story_id", "work_id", "attempt_id", "approval_ref",
                        "approval_digest", "owner_authority", "binding_payload_digest",
                        "plan_preimage_digest", "release_oid", "process_oid", "scope_digest",
                    },
                    set(plan["sidecar"]),
                )
                human_out = StringIO()
                with redirect_stdout(human_out):
                    self.assertEqual(
                        0,
                        story_evidence.main(
                            ["issue-revalidation-authority", "plan", *common, "--format", "human"]
                        ),
                    )
                human_plan = {
                    key: json.loads(value)
                    for key, value in (
                        line.split("=", 1) for line in human_out.getvalue().splitlines()
                    )
                }
                self.assertEqual(plan, human_plan)
                applied_out = StringIO()
                with redirect_stdout(applied_out):
                    self.assertEqual(0, story_evidence.main([
                        "issue-revalidation-authority", "apply", *common,
                        "--expected-plan-digest", plan["plan_digest"],
                    ]))
                applied = json.loads(applied_out.getvalue())
                self.assertEqual(("APPLIED", 2, 1, 1, "active", None), (
                    applied["status"], applied["mutation_count"], applied["receipt_mutation_count"],
                    applied["sidecar_mutation_count"], applied["pair_state"], applied["recovery_origin"],
                ))
                sidecar = root / plan["targets"][1]["logical_ref"]
                sidecar.unlink()
                recovered_out = StringIO()
                with redirect_stdout(recovered_out):
                    self.assertEqual(0, story_evidence.main([
                        "issue-revalidation-authority", "apply", *common,
                        "--expected-plan-digest", plan["plan_digest"],
                    ]))
                recovered = json.loads(recovered_out.getvalue())
                self.assertEqual(("RECOVERED", 1, 0, 1, "active", "receipt-only"), (
                    recovered["status"], recovered["mutation_count"], recovered["receipt_mutation_count"],
                    recovered["sidecar_mutation_count"], recovered["pair_state"], recovered["recovery_origin"],
                ))
                replay_out = StringIO()
                with redirect_stdout(replay_out):
                    self.assertEqual(0, story_evidence.main([
                        "issue-revalidation-authority", "apply", *common,
                        "--expected-plan-digest", plan["plan_digest"],
                    ]))
                replay = json.loads(replay_out.getvalue())
                self.assertEqual(("NO_CHANGE", 0, 0, 0, "active", None), (
                    replay["status"], replay["mutation_count"], replay["receipt_mutation_count"],
                    replay["sidecar_mutation_count"], replay["pair_state"], replay["recovery_origin"],
                ))

    def test_p02_bootstrap_authority_rejects_collision_and_invalid_counter_tuple(self) -> None:
        """BS-TC-07/13：不同 bytes 不覆盖，closed counter tuple 不可构造。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def resolver(_root: Path, logical: object) -> Path:
                return root / str(logical)
            def write(ref: str, payload: dict) -> None:
                path = root / ref
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
            approval_ref = "process/checkpoints/approval.json"
            previous_ref = "process/checks/previous.json"
            superseding_ref = "process/checks/superseding.json"
            oids = {"release_head": "a" * 40, "process_head": "b" * 40}
            write(approval_ref, {"cr_id": "CR-068"})
            write(previous_ref, {"repository_oids": oids})
            write(superseding_ref, {"repository_oids": oids})
            with patch.object(story_evidence, "_resolve_runtime_path", side_effect=resolver), patch.object(story_evidence, "_resolve_runtime_ref", side_effect=resolver):
                plan = story_evidence._authority_issue_plan(
                    root, work_ref="process/works/W-BOOT/WORK.yaml",
                    story_id="STORY-CR068-P02-NATIVE-CP6-REVALIDATION", attempt_id="attempt-v23",
                    approval_ref=approval_ref, previous_ref=previous_ref, superseding_ref=superseding_ref,
                    scope_digest="c" * 64,
                )
                target = root / plan["targets"][0]["logical_ref"]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b'{"different":true}\n')
                before = target.read_bytes()
                with self.assertRaises(ValueError, msg="different target bytes must block"):
                    story_evidence._apply_authority_issue(root, plan, plan["plan_digest"])
                self.assertEqual(before, target.read_bytes())
                with self.assertRaises(ValueError):
                    story_evidence._authority_issue_result(
                        plan, status="RECOVERED", receipt_count=0, sidecar_count=0,
                        pair_state="active", recovery_origin="receipt-only",
                    )

    def test_p02_bootstrap_authority_fault_matrix_has_closed_result_tuples(self) -> None:
        """BS-V23-HOST-001 / BS-TC-13/14：所有 writer 故障均为确定闭包。"""
        cases = (
            ("before-receipt", "create", ("BLOCKED", "BLOCKED", 3, "E_FAULT_BEFORE_RECEIPT", 0, 0, 0, "nonactive", None)),
            ("after-receipt", "sidecar", ("PARTIAL", "PARTIAL", 4, "E_FAULT_AFTER_RECEIPT", 1, 1, 0, "nonactive", None)),
            ("after-sidecar", "corrupt", ("PARTIAL", "PARTIAL", 4, "E_FAULT_AFTER_SIDECAR", 2, 1, 1, "nonactive", None)),
            ("postcheck-unknown", "postcheck", ("PARTIAL", "PARTIAL", 4, "E_POSTCHECK_UNKNOWN", 2, 1, 1, "unknown", None)),
        )
        for name, fault, expected in cases:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                def resolver(_root: Path, logical: object, fixture_root: Path = root) -> Path:
                    self.assertFalse(str(logical).endswith("/WORK.yaml"))
                    return fixture_root / str(logical)
                for ref, payload in (
                    ("process/checkpoints/approval.json", {"cr_id": "CR-068"}),
                    ("process/checks/previous.json", {"repository_oids": {"release_head": "a" * 40, "process_head": "b" * 40}}),
                    ("process/checks/superseding.json", {"repository_oids": {"release_head": "a" * 40, "process_head": "b" * 40}}),
                ):
                    path = root / ref
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
                with patch.object(story_evidence, "_resolve_runtime_path", side_effect=resolver), patch.object(story_evidence, "_resolve_runtime_ref", side_effect=resolver):
                    plan = story_evidence._authority_issue_plan(
                        root, work_ref="process/works/W-BOOT/WORK.yaml",
                        story_id="STORY-CR068-P02-NATIVE-CP6-REVALIDATION", attempt_id="attempt-v23",
                        approval_ref="process/checkpoints/approval.json",
                        previous_ref="process/checks/previous.json",
                        superseding_ref="process/checks/superseding.json", scope_digest="c" * 64,
                    )
                    original_create = story_evidence._authority_issue_create_once
                    if fault == "create":
                        create_patch = patch.object(story_evidence, "_authority_issue_create_once", side_effect=OSError("before receipt"))
                        postcheck_patch = patch.object(story_evidence, "_authority_issue_postcheck_bytes", wraps=story_evidence._authority_issue_postcheck_bytes)
                    elif fault == "sidecar":
                        def fail_sidecar(path: Path, data: bytes, create_once: object = original_create) -> None:
                            if path.name == "authorization-binding.v2.json":
                                raise OSError("before sidecar")
                            create_once(path, data)
                        create_patch = patch.object(story_evidence, "_authority_issue_create_once", side_effect=fail_sidecar)
                        postcheck_patch = patch.object(story_evidence, "_authority_issue_postcheck_bytes", wraps=story_evidence._authority_issue_postcheck_bytes)
                    elif fault == "corrupt":
                        def corrupt_sidecar(path: Path, data: bytes, create_once: object = original_create) -> None:
                            create_once(path, data)
                            if path.name == "authorization-binding.v2.json":
                                path.write_bytes(b"corrupt")
                        create_patch = patch.object(story_evidence, "_authority_issue_create_once", side_effect=corrupt_sidecar)
                        postcheck_patch = patch.object(story_evidence, "_authority_issue_postcheck_bytes", wraps=story_evidence._authority_issue_postcheck_bytes)
                    else:
                        create_patch = patch.object(story_evidence, "_authority_issue_create_once", wraps=original_create)
                        postcheck_patch = patch.object(story_evidence, "_authority_issue_postcheck_bytes", side_effect=OSError("postcheck unknown"))
                    with create_patch, postcheck_patch:
                        result = story_evidence._apply_authority_issue(root, plan, plan["plan_digest"])
                self.assertEqual(expected, (
                    result["status"], result["decision"], result["exit_code"], result["error"]["code"],
                    result["mutation_count"], result["receipt_mutation_count"], result["sidecar_mutation_count"],
                    result["pair_state"], result["recovery_origin"],
                ))

        plan = {"plan_digest": "a" * 64, "targets": []}
        for kwargs in (
            {"status": "UNKNOWN", "receipt_count": 0, "sidecar_count": 0, "pair_state": "active", "recovery_origin": None},
            {"status": "PARTIAL", "receipt_count": 0, "sidecar_count": 0, "pair_state": "active", "recovery_origin": None, "error": "E_POSTCHECK_UNKNOWN"},
            {"status": "PARTIAL", "receipt_count": 1, "sidecar_count": 0, "pair_state": "nonactive", "recovery_origin": None, "error": "E_UNKNOWN"},
        ):
            with self.assertRaises(ValueError):
                story_evidence._authority_issue_result(plan, **kwargs)

    def test_p02_bootstrap_writer_exception_observes_created_target_mutation(self) -> None:
        """after-create/partial-write/close fault 不能把 durable target 误报为零 mutation。"""

        for failed_target in ("receipt", "sidecar"):
            for persisted_bytes in ("partial", "exact"):
                with self.subTest(target=failed_target, bytes=persisted_bytes), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)

                    def resolver(_root: Path, logical: object, fixture_root: Path = root) -> Path:
                        return fixture_root / str(logical)

                    for ref, payload in (
                        ("process/checkpoints/approval.json", {"cr_id": "CR-068"}),
                        ("process/checks/previous.json", {"repository_oids": {"release_head": "a" * 40, "process_head": "b" * 40}}),
                        ("process/checks/superseding.json", {"repository_oids": {"release_head": "a" * 40, "process_head": "b" * 40}}),
                    ):
                        path = root / ref
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
                    with patch.object(story_evidence, "_resolve_runtime_path", side_effect=resolver), patch.object(story_evidence, "_resolve_runtime_ref", side_effect=resolver):
                        plan = story_evidence._authority_issue_plan(
                            root,
                            work_ref="process/works/W-BOOT/WORK.yaml",
                            story_id="STORY-CR068-P02-NATIVE-CP6-REVALIDATION",
                            attempt_id="attempt-v23",
                            approval_ref="process/checkpoints/approval.json",
                            previous_ref="process/checks/previous.json",
                            superseding_ref="process/checks/superseding.json",
                            scope_digest="c" * 64,
                        )
                        original_create = story_evidence._authority_issue_create_once

                        def write_then_raise(
                            path: Path,
                            data: bytes,
                            target: str = failed_target,
                            persisted: str = persisted_bytes,
                            create_once: object = original_create,
                        ) -> None:
                            is_sidecar = path.name == "authorization-binding.v2.json"
                            if (target == "sidecar") != is_sidecar:
                                create_once(path, data)
                                return
                            path.parent.mkdir(parents=True, exist_ok=True)
                            path.write_bytes(data if persisted == "exact" else data[:7])
                            raise OSError("injected after target creation")

                        with patch.object(
                            story_evidence,
                            "_authority_issue_create_once",
                            side_effect=write_then_raise,
                        ):
                            result = story_evidence._apply_authority_issue(
                                root, plan, plan["plan_digest"]
                            )
                        expected = (
                            ("E_FAULT_AFTER_RECEIPT", 1, 1, 0)
                            if failed_target == "receipt"
                            else ("E_FAULT_AFTER_SIDECAR", 2, 1, 1)
                        )
                        self.assertEqual(
                            expected,
                            (
                                result["error"]["code"],
                                result["mutation_count"],
                                result["receipt_mutation_count"],
                                result["sidecar_mutation_count"],
                            ),
                        )
                        self.assertEqual(("PARTIAL", "PARTIAL", "nonactive", 4), (
                            result["status"], result["decision"], result["pair_state"], result["exit_code"],
                        ))
                        if persisted_bytes == "partial":
                            with self.assertRaises(ValueError):
                                story_evidence._apply_authority_issue(
                                    root, plan, plan["plan_digest"]
                                )
                        else:
                            retry = story_evidence._apply_authority_issue(
                                root, plan, plan["plan_digest"]
                            )
                            self.assertEqual(
                                "RECOVERED" if failed_target == "receipt" else "NO_CHANGE",
                                retry["status"],
                            )


if __name__ == "__main__":
    unittest.main()
