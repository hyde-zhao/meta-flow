from __future__ import annotations

import hashlib
import importlib
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import pytest

from meta_flow.checks.frozen_cp6_evidence import build_cp6_revalidation_receipt
from meta_flow.policies import public_operations
from meta_flow.project.onboarding_contract import canonical_digest
from meta_flow.work.io_metrics import IOMetrics
from meta_flow.work.read_context import OperationReadContext
from meta_flow.workflow import story_evidence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONSOLE = Path(sys.executable).with_name("meta-flow")


def build_public_revalidation_authorization(
    *, attempt_id: str = "attempt-public-61e9",
    release_oid: str = "b" * 40,
    process_oid: str = "c" * 40,
    scope_digest: str = "d" * 64,
    downstream_set: list[dict] | None = None,
) -> dict:
    frozen_downstream_set = downstream_set or [{
        "producer": "I01", "receipt_digest": "a" * 64, "attempt_id": attempt_id,
    }]
    return build_cp6_revalidation_receipt(
        kind="authorization", cr_id="CR-X", story_id="STORY-X", work_id="W-X",
        attempt_id=attempt_id, release_oid=release_oid, process_oid=process_oid,
        scope_digest=scope_digest,
        payload={
            "previous_cp6_ref": "process/checks/previous.json",
            "superseding_cp5_ref": "process/checks/cp5.json",
            "approval_ref": "process/checkpoints/approval.json",
            "work_authorization_ref": "process/works/W-X/WORK.yaml",
            "plan_preimage_digest": "e" * 64,
            "downstream_set_digest": canonical_digest(frozen_downstream_set),
            "downstream_set": frozen_downstream_set,
        },
    ).as_dict()


def test_p02_bootstrap_public_authority_grammar_is_generic_and_closed() -> None:
    """BS-TC-01：仅 story child dispatch；不需要也不允许顶层 CLI 改动。"""
    help_output = StringIO()
    with redirect_stdout(help_output):
        assert story_evidence.main(["issue-revalidation-authority", "--help"]) == 0
    usage = help_output.getvalue()
    assert "{plan,apply}" in usage
    assert "--previous-cp6-result-ref" in usage
    assert "--superseding-cp5-result-ref" in usage
    assert "--expected-plan-digest" in usage
    # Missing, short, duplicate, new-recover and plan-with-expected grammar all
    # reject before any resolver or target I/O.
    invalid_argvs = (
        ["issue-revalidation-authority", "recover"],
        ["issue-revalidation-authority", "plan", "-p", "."],
        ["issue-revalidation-authority", "plan", "--project-root", ".", "--project-root", "."],
        ["issue-revalidation-authority", "plan", "--expected-plan-digest", "a" * 64],
    )
    for argv in invalid_argvs:
        assert story_evidence.main(argv) == 3

    registry = public_operations.load_public_operation_registry(PROJECT_ROOT)
    contract = next(
        item
        for item in registry
        if item.operation == "story.issue-revalidation-authority"
    )
    assert contract.entry == (
        "meta-flow",
        "story",
        "issue-revalidation-authority",
    )
    assert contract.output_version == "Cp6RevalidationAuthorityPairV2"
    assert contract.mutation_mode == "dry-run-digest-apply"
    assert contract.authorization_mode == "expected-plan-digest"


def test_p02_bootstrap_apply_input_error_uses_closed_wire() -> None:
    """generic apply BLOCKED 也必须保留 counters/pair/plan/targets。"""

    expected_digest = "a" * 64
    stdout = StringIO()
    with redirect_stdout(stdout):
        exit_code = story_evidence.main(
            [
                "issue-revalidation-authority",
                "apply",
                "--project-root",
                ".",
                "--work-ref",
                "process/works/W-X/WORK.yaml",
                "--story-id",
                "STORY-X",
                "--attempt-id",
                "attempt-x",
                "--approval-ref",
                "process/missing/approval.json",
                "--previous-cp6-result-ref",
                "process/missing/previous.json",
                "--superseding-cp5-result-ref",
                "process/missing/superseding.json",
                "--scope-digest",
                "b" * 64,
                "--expected-plan-digest",
                expected_digest,
            ]
        )
    result = json.loads(stdout.getvalue())
    assert exit_code == 3
    assert set(result) == {
        "schema_version",
        "action",
        "status",
        "decision",
        "mutation_count",
        "receipt_mutation_count",
        "sidecar_mutation_count",
        "pair_state",
        "recovery_origin",
        "plan_digest",
        "targets",
        "error",
        "exit_code",
    }
    assert (
        result["status"],
        result["decision"],
        result["mutation_count"],
        result["receipt_mutation_count"],
        result["sidecar_mutation_count"],
        result["pair_state"],
        result["recovery_origin"],
        result["plan_digest"],
        result["targets"],
        result["error"]["code"],
    ) == ("BLOCKED", "BLOCKED", 0, 0, 0, "nonactive", None, expected_digest, [], "E_INPUT_INVALID")


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def _write_process_json(process: Path, logical_ref: str, payload: dict) -> None:
    assert logical_ref.startswith("process/")
    path = process / logical_ref.removeprefix("process/")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def init_public_revalidation_project(
    root: Path,
    *,
    attempt_id: str = "attempt-public-61e9",
    downstream_set: list[dict] | None = None,
) -> tuple[Path, Path, dict, str, str, str]:
    """构造有真实双 Git HEAD、sibling binding 和 canonical Work 的 public fixture。"""

    release = root / "release"
    process = root / "process-repository"
    release.mkdir()
    process.mkdir()
    for repository in (release, process):
        _git(repository, "init", "-b", "main")
    (process / ".meta-flow-process.yaml").write_text(
        "schema_version: 1\n"
        "layout_version: independent-process-repo-v1\n"
        "workflow_model: vnext\n"
        "project_id: public-fixture\n"
        "repo_role: process\n"
        "route_mode: sibling-binding\n"
        "release_repo:\n"
        "  anchor: workspace_parent\n"
        "  relative_path: release\n",
        encoding="utf-8",
    )
    (process / "PROJECT.yaml").write_text(
        "schema_version: 1\nproject_id: public-fixture\nname: Public Fixture\nstatus: active\n",
        encoding="utf-8",
    )
    _git(process, "add", ".meta-flow-process.yaml", "PROJECT.yaml")
    _git(
        process,
        "-c",
        "user.name=Meta Flow Test",
        "-c",
        "user.email=meta-flow@example.invalid",
        "commit",
        "-m",
        "initial process",
    )
    binding = release / ".meta-flow" / "workspace.yaml"
    binding.parent.mkdir()
    binding.write_text(
        "schema_version: 1\n"
        "layout_version: independent-process-repo-v1\n"
        "workflow_model: vnext\n"
        "project_id: public-fixture\n"
        "repo_role: release\n"
        "route_mode: sibling-binding\n"
        "process_repo:\n"
        "  anchor: workspace_parent\n"
        "  relative_path: process-repository\n",
        encoding="utf-8",
    )
    (release / "README.md").write_text("public fixture\n", encoding="utf-8")
    _git(release, "add", ".meta-flow/workspace.yaml", "README.md")
    _git(
        release,
        "-c",
        "user.name=Meta Flow Test",
        "-c",
        "user.email=meta-flow@example.invalid",
        "commit",
        "-m",
        "initial release",
    )
    release_oid = _git(release, "rev-parse", "HEAD")
    process_oid = _git(process, "rev-parse", "HEAD")
    scope_digest = "d" * 64
    authorization = build_public_revalidation_authorization(
        attempt_id=attempt_id,
        release_oid=release_oid,
        process_oid=process_oid,
        scope_digest=scope_digest,
        downstream_set=downstream_set,
    )
    namespace = f"process/works/W-X/revalidation/{attempt_id}"
    authorization_ref = f"{namespace}/OWNER-AUTHORIZATION.json"
    target_ref = f"process/works/W-X/revalidation/{attempt_id}/receipts/authorization.json"
    policy_ref = f"{namespace}/CURRENT-DOWNSTREAM-POLICY.json"
    consumers = {"I01": ["P02"]}
    _write_process_json(
        process,
        policy_ref,
        {
            "schema_version": 1,
            "consumers": consumers,
            "policy_digest": canonical_digest(consumers),
            "current_receipts": authorization["payload"]["downstream_set"],
        },
    )
    _write_process_json(process, authorization_ref, authorization)
    selector_ref = f"{namespace}/CURRENT-DOWNSTREAM-SELECTIONS.json"
    selector_entries = [{
        "producer": entry["producer"],
        "consumer": "W2",
        "current_ref": "process/receipts/downstream.json",
        "superseded_by": "",
    } for entry in authorization["payload"]["downstream_set"]]
    _write_process_json(
        process,
        selector_ref,
        {
            "schema_version": 1,
            "selections": selector_entries,
            "selection_digest": canonical_digest(selector_entries),
        },
    )
    admission_plan_ref = f"{namespace}/DOWNSTREAM-ADMISSION-PLAN.json"
    admission_policy_payload = {
        "schema_version": 1,
        "consumers": {
            "W2": [
                entry["producer"]
                for entry in authorization["payload"]["downstream_set"]
            ],
        },
    }
    admission_policy = {
        **admission_policy_payload,
        "policy_digest": canonical_digest(admission_policy_payload),
    }
    admission_payload = {
        "authorization_digest": authorization["payload_digest"],
        "bound_policy": admission_policy,
    }
    _write_process_json(
        process,
        admission_plan_ref,
        {
            **admission_payload,
            "plan_digest": canonical_digest(admission_payload),
        },
    )
    lineage_refs = {
        "previous_cp6": authorization["payload"]["previous_cp6_ref"],
        "superseding_cp5": authorization["payload"]["superseding_cp5_ref"],
        "approval": authorization["payload"]["approval_ref"],
    }
    for logical_ref in lineage_refs.values():
        _write_process_json(process, logical_ref, {"schema_version": 1})

    def bytes_digest(logical_ref: str) -> str:
        return hashlib.sha256(
            (process / logical_ref.removeprefix("process/")).read_bytes()
        ).hexdigest()

    work = process / "works" / "W-X" / "WORK.yaml"
    work.parent.mkdir(parents=True, exist_ok=True)
    work.write_text(
        "schema_version: 1\n"
        "work_id: W-X\n"
        f"scope_digest: {scope_digest}\n"
        "base_oids:\n"
        f"  release: {release_oid}\n"
        f"  process: {process_oid}\n"
        "revalidation_authority:\n"
        "  schema_version: 1\n"
        "  story_id: STORY-X\n"
        f"  attempt_id: {attempt_id}\n"
        f"  authorization_ref: {authorization_ref}\n"
        f"  authorization_bytes_digest: {bytes_digest(authorization_ref)}\n"
        f"  authorization_payload_digest: {authorization['payload_digest']}\n"
        "  allowed_target_kinds:\n"
        "    - authorization\n"
        "    - completion\n"
        "  lineage:\n"
        f"    previous_cp6_ref: {lineage_refs['previous_cp6']}\n"
        f"    previous_cp6_bytes_digest: {bytes_digest(lineage_refs['previous_cp6'])}\n"
        f"    superseding_cp5_ref: {lineage_refs['superseding_cp5']}\n"
        f"    superseding_cp5_bytes_digest: {bytes_digest(lineage_refs['superseding_cp5'])}\n"
        f"    approval_ref: {lineage_refs['approval']}\n"
        f"    approval_bytes_digest: {bytes_digest(lineage_refs['approval'])}\n"
        "  inputs:\n"
        f"    downstream_policy_ref: {policy_ref}\n"
        f"    downstream_policy_bytes_digest: {bytes_digest(policy_ref)}\n"
        f"    admission_plan_ref: {admission_plan_ref}\n"
        f"    admission_plan_bytes_digest: {bytes_digest(admission_plan_ref)}\n"
        f"    current_selections_ref: {selector_ref}\n"
        f"    current_selections_bytes_digest: {bytes_digest(selector_ref)}\n",
        encoding="utf-8",
    )
    return release, process, authorization, authorization_ref, target_ref, policy_ref


def init_public_apply_operation(root: Path) -> dict[str, object]:
    """构造已冻结 plan、可执行 apply 的公共操作 fixture。"""

    release, process, authorization, authorization_ref, target_ref, policy_ref = (
        init_public_revalidation_project(root)
    )
    plan_context_ref = "process/contexts/r13-plan.json"
    _write_process_json(
        process,
        plan_context_ref,
        {
            "schema_version": 1,
            "action": "plan",
            "payload": {"downstream_policy_ref": policy_ref},
        },
    )
    plan_stdout = StringIO()
    with redirect_stdout(plan_stdout):
        plan_exit = story_evidence.main([
            "revalidate-cp6", "--action", "plan", "--output", "json",
            "--authorization", authorization_ref, "--target", target_ref,
            "--context", plan_context_ref, "--project-root", str(release),
        ])
    assert plan_exit == 0
    plan_result = json.loads(plan_stdout.getvalue())
    plan_ref = "process/contexts/r13-plan-result.json"
    _write_process_json(process, plan_ref, plan_result)
    apply_context_ref = "process/contexts/r13-apply.json"
    _write_process_json(
        process,
        apply_context_ref,
        {
            "schema_version": 1,
            "action": "apply",
            "payload": {
                "plan_ref": plan_ref,
                "expected_plan_digest": plan_result["plan_digest"],
                "downstream_policy_ref": policy_ref,
            },
        },
    )
    return {
        "release": release,
        "process": process,
        "authorization": authorization,
        "authorization_ref": authorization_ref,
        "context_ref": apply_context_ref,
        "target_ref": target_ref,
        "policy_ref": policy_ref,
    }


def init_public_completion_operation(
    root: Path,
) -> dict[str, object]:
    """构造可写 completion 的完整公共操作 fixture。"""

    attempt_id = "attempt-public-61e9"
    downstream_payload = {
        "schema_version": 1,
        "producer": "I01",
        "consumer": "W2",
        "story_id": "STORY-X",
        "attempt_id": attempt_id,
    }
    downstream_bytes = (
        json.dumps(downstream_payload, sort_keys=True) + "\n"
    ).encode()
    release, process, authorization, authorization_ref, _target_ref, _policy_ref = (
        init_public_revalidation_project(
            root,
            attempt_id=attempt_id,
            downstream_set=[{
                "producer": "I01",
                "receipt_digest": hashlib.sha256(downstream_bytes).hexdigest(),
                "attempt_id": attempt_id,
            }],
        )
    )
    packet = {
        "schema_version": 3,
        "lld_policy": "full-lld",
        "read_if_needed": [{
            "path": "process/stories/STORY-X-LLD.md",
            "trigger": "full_lld_required_by_policy",
            "consumer_requirement": "required",
        }],
    }
    selected = ["process/stories/STORY-X-LLD.md"]
    event = {
        "packet": packet,
        "selected_refs": selected,
        "selection_digest": canonical_digest(selected),
        "story_id": authorization["story_id"],
        "work_id": authorization["work_id"],
        "attempt_id": authorization["attempt_id"],
        "stage": "CP6",
        "context_ref": "process/context/X.json",
        "scope_digest": authorization["scope_digest"],
        "reason": "summary_insufficient",
        "reason_evidence": {"missing_slots": ["full_lld_body"]},
        "requested_ref": selected[0],
        "preregistered_by": "host",
        "bytes_digest": "b" * 64,
    }
    event_ref = "process/events/p01.json"
    event_bytes = (json.dumps(event, sort_keys=True) + "\n").encode()
    event_path = process / event_ref.removeprefix("process/")
    event_path.parent.mkdir(parents=True, exist_ok=True)
    event_path.write_bytes(event_bytes)
    required = {key: "f" * 64 for key in (
        "packet_digest",
        "read_log_digest",
        "return_digest",
        "evidence_digest",
        "result_digest",
        "checkpoint_digest",
        "plan_digest",
        "downstream_set_digest",
    )}
    required["downstream_set_digest"] = authorization["payload"][
        "downstream_set_digest"
    ]
    event_digest = hashlib.sha256(event_bytes).hexdigest()
    preflight = story_evidence.validate_cp6_revalidation_preflight(
        authorization,
        required_digests=required,
        p01_event={
            "logical_ref": event_ref,
            "event_bytes": event_bytes,
            "event_bytes_digest": event_digest,
            "current_event_bytes_digest": event_digest,
        },
    )
    assert preflight["decision"] == "READY"
    projection_inner = {
        "schema_version": 1,
        "kind": "projection",
        "cr_id": authorization["cr_id"],
        "story_id": authorization["story_id"],
        "work_id": authorization["work_id"],
        "attempt_id": authorization["attempt_id"],
        "preflight_digest": preflight["receipt"]["payload_digest"],
        "phase": "COMPLETE",
    }
    projection_ref = "process/receipts/projection.json"
    _write_process_json(process, projection_ref, projection_inner)
    downstream_ref = "process/receipts/downstream.json"
    _write_process_json(process, downstream_ref, downstream_payload)
    namespace = f"process/works/W-X/revalidation/{authorization['attempt_id']}"
    completion_context_ref = "process/contexts/completion-race.json"
    _write_process_json(
        process,
        completion_context_ref,
        {
            "schema_version": 1,
            "action": "completion",
            "payload": {
                "required_digests": required,
                "p01_event_ref": event_ref,
                "projection_ref": projection_ref,
                "consumer": "W2",
                "receipt_refs": [downstream_ref],
                "admission_plan_ref": (
                    f"{namespace}/DOWNSTREAM-ADMISSION-PLAN.json"
                ),
                "current_selections_ref": (
                    f"{namespace}/CURRENT-DOWNSTREAM-SELECTIONS.json"
                ),
            },
        },
    )
    return {
        "release": release,
        "process": process,
        "authorization": authorization,
        "authorization_ref": authorization_ref,
        "context_ref": completion_context_ref,
        "target_ref": f"{namespace}/receipts/completion.json",
        "admission_plan_ref": f"{namespace}/DOWNSTREAM-ADMISSION-PLAN.json",
        "current_selections_ref": (
            f"{namespace}/CURRENT-DOWNSTREAM-SELECTIONS.json"
        ),
    }


def resolved_authorization(payload: dict) -> dict:
    return {
        "status": "READY", "mutation_count": 0, "payload": payload,
    }


def current_observation(*, target_exists: bool = False) -> dict:
    return {
        "status": "CURRENT", "mutation_count": 0,
        "observation": {"target_exists": target_exists},
    }


def applied_result() -> dict:
    return {"status": "APPLIED", "mutation_count": 1}


def verified_payload(payload: dict) -> dict:
    return {"status": "VERIFIED", "mutation_count": 0, "payload": payload}

# A3 mapping: TC23 validates generic child plan/apply/replay/inspect/recover
# contract; COMP04 checks public operation discovery/help without cli.py edits.
A3_TEST_MAPPING = {
    "P02-TC-01": "test_frozen_cp6_evidence::FrozenCp6EvidenceTests::test_a3_tc01_rejects_escape_paths_and_tc16_rejects_downstream_lineage",
    "P02-TC-02": "test_state_transition.py::StateTransitionTests::test_cp6_pass_projects_story_and_only_satisfied_downstream_to_dev_ready",
    "P02-TC-03": "test_state_transition.py::StateTransitionTests::test_cp6_projection_rejects_closed_gate",
    "P02-TC-04": "test_state_transition.py::StateTransitionTests::test_a3_tc04_tc05_bare_phase_mappings_cannot_complete_attempt",
    "P02-TC-05": "test_state_transition.py::StateTransitionTests::test_a3_tc04_tc05_bare_phase_mappings_cannot_complete_attempt",
    "P02-TC-06": "test_story_evidence::StoryEvidenceTests::test_a003_pgr3_f003_plan_apply_requires_real_observations",
    "P02-TC-07": "test_story_evidence::StoryEvidenceTests::test_a003_pgr3_f003_plan_apply_requires_real_observations",
    "P02-TC-08": "test_story_evidence::StoryEvidenceTests::test_a003_pgr3_f003_plan_apply_requires_real_observations",
    "P02-TC-09": "test_story_evidence::StoryEvidenceTests::test_a003_pgr3_f003_plan_apply_requires_real_observations",
    "P02-TC-10": "test_story_evidence::StoryEvidenceTests::test_a003_pgr3_f003_plan_apply_requires_real_observations",
    "P02-TC-11": "test_story_evidence::StoryEvidenceTests::test_a003_pgr3_f004_real_p01_packet_and_input_spec",
    "P02-TC-12": "test_story_evidence::StoryEvidenceTests::test_a3_tc12_tc14_triple_preflight_contract_cases_are_independent",
    "P02-TC-13": "test_story_evidence::StoryEvidenceTests::test_a3_tc12_tc14_triple_preflight_contract_cases_are_independent",
    "P02-TC-14": "test_story_evidence::StoryEvidenceTests::test_a3_tc12_tc14_triple_preflight_contract_cases_are_independent",
    "P02-TC-15": "test_story_evidence::StoryEvidenceTests::test_a003_pgr3_f005_spine_recovery_downstream_observations",
    "P02-TC-16": "test_frozen_cp6_evidence::FrozenCp6EvidenceTests::test_a3_tc01_rejects_escape_paths_and_tc16_rejects_downstream_lineage",
    "P02-TC-17": "test_story_evidence::StoryEvidenceTests::test_a3_tc17_real_atomic_write_faults_are_typed_and_create_once_is_race_safe",
    "P02-TC-18": "test_story_evidence::StoryEvidenceTests::test_a3_tc18_same_attempt_completion_recovery_contract",
    "P02-TC-19": "test_story_evidence::StoryEvidenceTests::test_a3_tc19_tc22_validated_downstream_fixture_matrix",
    "P02-TC-20": "test_story_evidence::StoryEvidenceTests::test_a3_tc19_tc22_validated_downstream_fixture_matrix",
    "P02-TC-21": "test_story_evidence::StoryEvidenceTests::test_a3_tc19_tc22_validated_downstream_fixture_matrix",
    "P02-TC-22": "test_story_evidence::StoryEvidenceTests::test_a3_tc19_tc22_validated_downstream_fixture_matrix",
    "P02-TC-23": "test_public_operation_contracts::test_a003_pgr3_f006_public_dispatcher_requires_real_action_execution",
    "P02-TC-24": "test_frozen_cp6_evidence::FrozenCp6EvidenceTests::test_a3_tc24_schema_mutations_fail_for_the_target_reason",
    "P02-COMP-01": "test_frozen_cp6_evidence::FrozenCp6EvidenceTests::test_c10_valid_v1_freezes_and_unknown_schema_blocks",
    "P02-COMP-02": "test_state_transition::StateTransitionTests::test_cp6_pass_projects_story_and_only_satisfied_downstream_to_dev_ready",
    "P02-COMP-03": "test_story_evidence::StoryEvidenceTests::test_public_cp6_projection_dry_run_apply_and_idempotent_replay",
    "P02-COMP-04": "test_public_operation_contracts::test_story_revalidation_public_child_operation_remains_available_without_cli_owner_change",
    "P02-COMP-05": "test_story_evidence::StoryEvidenceTests::test_a003_pgr3_f003_plan_apply_requires_real_observations",
    "P02-COMP-06": "test_story_evidence::StoryEvidenceTests::test_p02_preflight_partial_and_downstream_admission_fail_closed",
    "P02-COMP-07": "test_story_evidence::StoryEvidenceTests::test_public_story_evidence_commands_resolve_sibling_binding",
}

def semantic_case(identifier: str, positive: str, negative: str) -> dict[str, str]:
    return {
        "id": identifier, "node": A3_TEST_MAPPING[identifier],
        "positive": positive, "negative": negative,
    }


# 显式 registry 让 pytest 收集 31 个唯一 param-id；每个 ID 绑定真实 node 与具体正/负断言，
# 不再从 ID 字符串自动生成伪语义 metadata。
A3_SEMANTIC_CASES = (
    semantic_case("P02-TC-01", "closed authorization accepted", "escape ref/digest mismatch blocked"),
    semantic_case("P02-TC-02", "CP6 PASS admits satisfied story", "unsatisfied dependency unchanged"),
    semantic_case("P02-TC-03", "open gate projects", "closed gate blocked"),
    semantic_case("P02-TC-04", "receipt prefix projects", "bare phase mapping blocked"),
    semantic_case("P02-TC-05", "monotonic prefix completes", "skip/duplicate blocked"),
    semantic_case("P02-TC-06", "release observation matches", "release drift writer zero"),
    semantic_case("P02-TC-07", "process observation matches", "process drift writer zero"),
    semantic_case("P02-TC-08", "scope observation matches", "scope drift writer zero"),
    semantic_case("P02-TC-09", "target preimage matches", "target drift writer zero"),
    semantic_case("P02-TC-10", "current receipt set matches", "policy/current drift writer zero"),
    semantic_case("P02-TC-11", "one canonical P01 event ready", "zero/multiple/fabricated blocked"),
    semantic_case("P02-TC-12", "required route and target read once", "route failure reads zero"),
    semantic_case("P02-TC-13", "required digest and lineage match", "missing/digest/lineage blocked"),
    semantic_case("P02-TC-14", "optional NA forbidden skip IO", "unexpected resolver IO fails"),
    semantic_case("P02-TC-15", "eight-item spine ready", "missing/ref/digest/lineage/order blocked"),
    semantic_case("P02-TC-16", "same receipt chain ready", "inner cross-lineage link blocked"),
    semantic_case("P02-TC-17", "production create-once applies once", "race/fault/postcheck partial typed"),
    semantic_case("P02-TC-18", "runtime attempt recovers once", "cross chain/conflict blocked"),
    semantic_case("P02-TC-19", "I01 policy current receipt ready", "wrong producer/current/policy blocked"),
    semantic_case("P02-TC-20", "R01 policy current receipt ready", "wrong producer/current/policy blocked"),
    semantic_case("P02-TC-21", "C01 policy current receipt ready", "wrong producer/current/policy blocked"),
    semantic_case("P02-TC-22", "W2 ordered current set ready", "missing/extra/order/superseded blocked"),
    semantic_case("P02-TC-23", "six real CLI actions dispatch", "service failure/invalid action propagated"),
    semantic_case("P02-TC-24", "four receipt kinds closed", "major/kind/OID/SHA/ref/enum/fields blocked"),
    semantic_case("P02-COMP-01", "FrozenCp6Evidence V1 accepted", "unknown version blocked"),
    semantic_case("P02-COMP-02", "native CP6 admission preserved", "formal status unchanged"),
    semantic_case("P02-COMP-03", "public projection apply/replay", "stale plan blocked"),
    semantic_case("P02-COMP-04", "story help exposes revalidate", "cli owner unchanged"),
    semantic_case("P02-COMP-05", "observation plan/apply/replay", "all drift axes blocked"),
    semantic_case("P02-COMP-06", "real preflight/downstream ready", "fabricated/stale blocked"),
    semantic_case("P02-COMP-07", "sibling route command works", "missing/malformed route blocked"),
)


@pytest.mark.parametrize("case", A3_SEMANTIC_CASES, ids=[case["id"] for case in A3_SEMANTIC_CASES])
def test_a3_mapping_integrity_has_exact_keys_and_concrete_existing_nodes(case: dict[str, str]) -> None:
    expected = {*(f"P02-TC-{index:02d}" for index in range(1, 25)), *(f"P02-COMP-{index:02d}" for index in range(1, 8))}
    assert {entry["id"] for entry in A3_SEMANTIC_CASES} == expected
    assert case["node"] == A3_TEST_MAPPING[case["id"]]
    assert case["positive"] and case["negative"] and case["positive"] != case["negative"]
    parts = case["node"].split("::")
    module = importlib.import_module(parts[0].removesuffix(".py"))
    if len(parts) == 2:
        semantic_test = getattr(module, parts[1])
        semantic_test()
    else:
        assert len(parts) == 3, case["id"]
        test_case = getattr(module, parts[1])(parts[2])
        result = unittest.TestResult()
        test_case.run(result)
        assert result.wasSuccessful(), {
            "id": case["id"],
            "errors": [(str(test), str(error)) for test, error in result.errors],
            "failures": [(str(test), str(error)) for test, error in result.failures],
        }


def test_public_operation_registry_reuses_release_snapshot() -> None:
    metrics = IOMetrics("public-registry", enabled=True)
    context = OperationReadContext(
        PROJECT_ROOT,
        operation_id="public-registry",
        operation_kind="check",
        allowed_reads=(public_operations.DEFAULT_REGISTRY_REL.as_posix(),),
        logical_root="release-repository",
        metrics=metrics,
    )

    first = public_operations.load_public_operation_registry(
        PROJECT_ROOT,
        read_context=context,
    )
    second = public_operations.load_public_operation_registry(
        PROJECT_ROOT,
        read_context=context,
    )

    assert first == second
    assert metrics.summary()["totals"]["physical_reads"] == 1
    assert metrics.summary()["totals"]["cache_hits"] == 1


def test_story_revalidation_public_child_operation_remains_available_without_cli_owner_change() -> None:
    stream = subprocess.run(
        [str(CONSOLE), "story", "--help"], cwd=PROJECT_ROOT, check=False,
        capture_output=True, text=True,
    )
    assert stream.returncode == 0
    assert "project-cp6" in stream.stdout
    assert "revalidate-cp6" in stream.stdout
    assert callable(story_evidence.plan_cp6_revalidation)


def test_a3_tc23_public_child_operation_has_plan_apply_replay_inspect_recover_completion_contract() -> None:
    actions = ("plan", "apply", "replay", "inspect", "recover", "completion")
    statuses = {
        "plan": "READY", "apply": "APPLIED", "replay": "NO_CHANGE",
        "inspect": "READY", "recover": "RECOVERED", "completion": "COMPLETE",
    }
    traces = {
        "plan": ["resolve", "observe"],
        "apply": ["resolve", "observe", "write", "postcheck"],
        "replay": ["resolve", "observe", "postcheck"],
        "inspect": ["resolve", "postcheck"],
        "recover": ["resolve", "observe", "write", "postcheck"],
        "completion": ["resolve", "observe", "project", "write", "postcheck"],
    }
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        authorization = root / "authorization.json"
        receipt = build_public_revalidation_authorization()
        authorization.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")

        for action in actions:
            for output_format in ("json", "human"):
                target = root / f"{action}-{output_format}.json"
                if action in {"replay", "inspect"}:
                    target.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
                calls: list[str] = []

                def resolve(path: Path, trace=calls):
                    trace.append("resolve")
                    return json.loads(Path(path).read_text(encoding="utf-8"))

                def observe_current(*_args, trace=calls, current_target=target, **_kwargs):
                    trace.append("observe")
                    return current_observation(target_exists=current_target.exists())

                def create_once_writer(path: Path, payload: dict, trace=calls):
                    trace.append("write")
                    with Path(path).open("x", encoding="utf-8") as stream:
                        json.dump(payload, stream, sort_keys=True)
                        stream.write("\n")
                    return applied_result()

                def postcheck_reader(path: Path, trace=calls):
                    trace.append("postcheck")
                    return json.loads(Path(path).read_text(encoding="utf-8"))

                def projector(*_args, trace=calls, **_kwargs):
                    trace.append("project")
                    return {"decision": "READY", "phase": "COMPLETE", "complete": True}

                services = {
                    "resolve": resolve, "observe_current": observe_current,
                    "create_once_writer": create_once_writer,
                    "postcheck_reader": postcheck_reader, "projector": projector,
                }
                stdout = StringIO()
                with redirect_stdout(stdout):
                    exit_code = story_evidence.main([
                        "revalidate-cp6", "--action", action, "--output", output_format,
                        "--authorization", str(authorization), "--target", str(target),
                        "--project-root", str(root),
                    ], services=services)
                assert exit_code == 0
                assert calls == traces[action]
                if action in {"apply", "recover", "completion"}:
                    assert target.is_file()
                if output_format == "json":
                    output = json.loads(stdout.getvalue())
                    assert output["action"] == action
                    assert output["status"] == statuses[action]
                    assert output["mutation_count"] == (1 if action in {"apply", "recover", "completion"} else 0)
                    assert output["postcondition"] == "VERIFIED"
                else:
                    output = stdout.getvalue()
                    for fragment in (
                        f"action={action}", f"status={statuses[action]}",
                        "decision=PASS", "postcondition=VERIFIED",
                    ):
                        assert fragment in output

        help_output = StringIO()
        with redirect_stdout(help_output):
            assert story_evidence.main(["revalidate-cp6", "--help"], services={}) == 0
        for action in actions:
            assert action in help_output.getvalue()
        assert story_evidence.main([
            "revalidate-cp6", "--action", "invalid", "--authorization", str(authorization),
            "--target", str(root / "invalid.json"), "--project-root", str(root),
        ], services={}) == 2


def test_a003_pgr3_f006_public_dispatcher_requires_real_action_execution() -> None:
    """PGR3-F006：dispatcher 必须调用 action-specific production services。"""
    expected_calls = {
        "plan": ["resolve", "observe"],
        "apply": ["resolve", "observe", "write", "postcheck"],
        "replay": ["resolve", "observe", "postcheck"],
        "inspect": ["resolve", "postcheck"],
        "recover": ["resolve", "observe", "write", "postcheck"],
        "completion": ["resolve", "observe", "project", "write", "postcheck"],
    }
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        authorization_payload = build_public_revalidation_authorization()
        for action, expected in expected_calls.items():
            target = root / f"{action}.json"
            if action in {"replay", "inspect"}:
                target.write_text("{}\n", encoding="utf-8")
            calls: list[str] = []

            def service(name, result, trace=calls):
                def invoke(*args, **_kwargs):
                    trace.append(name)
                    if name == "write":
                        path = Path(args[0])
                        path.write_text("{}\n", encoding="utf-8")
                    return result
                return invoke

            services = {
                "resolve": service("resolve", resolved_authorization(authorization_payload)),
                "observe_current": service("observe", current_observation()),
                "create_once_writer": service("write", applied_result()),
                "postcheck_reader": service(
                    "postcheck", verified_payload(authorization_payload)
                ),
                "projector": service(
                    "project", {"decision": "READY", "phase": "COMPLETE", "complete": True}
                ),
            }
            result = story_evidence.run_cp6_revalidation_operation(
                request={
                    "action": action, "output": "json",
                    "authorization": authorization_payload,
                    "target": target,
                },
                services=services,
            )
            assert calls == expected
            assert result["action"] == action
            assert result["status"] == {
                "plan": "READY", "apply": "APPLIED", "replay": "NO_CHANGE",
                "inspect": "READY", "recover": "RECOVERED", "completion": "COMPLETE",
            }[action]
            assert result["mutation_count"] == (1 if action in {"apply", "recover", "completion"} else 0)

        failure_profiles = {
            "plan": {"BLOCKED": ("observe", ["resolve", "observe"], 0), "PARTIAL": ("observe", ["resolve", "observe"], 0)},
            "apply": {"BLOCKED": ("observe", ["resolve", "observe"], 0), "PARTIAL": ("postcheck", ["resolve", "observe", "write", "postcheck"], 1)},
            "replay": {"BLOCKED": ("postcheck", ["resolve", "observe", "postcheck"], 0), "PARTIAL": ("postcheck", ["resolve", "observe", "postcheck"], 0)},
            "inspect": {"BLOCKED": ("postcheck", ["resolve", "postcheck"], 0), "PARTIAL": ("postcheck", ["resolve", "postcheck"], 0)},
            "recover": {"BLOCKED": ("observe", ["resolve", "observe"], 0), "PARTIAL": ("postcheck", ["resolve", "observe", "write", "postcheck"], 1)},
            "completion": {"BLOCKED": ("project", ["resolve", "observe", "project"], 0), "PARTIAL": ("postcheck", ["resolve", "observe", "project", "write", "postcheck"], 1)},
        }
        authorization_path = root / "q.json"
        authorization_path.write_text(
            json.dumps(authorization_payload, sort_keys=True) + "\n", encoding="utf-8"
        )
        for action, decisions in failure_profiles.items():
            for decision, (failure_service, expected_trace, mutation_count) in decisions.items():
                for output_format in ("json", "human"):
                    calls: list[str] = []
                    target = root / f"z-{action}-{decision.lower()}-{output_format}.json"
                    if action in {"replay", "inspect"}:
                        target.write_text("{}\n", encoding="utf-8")

                    def service(
                        name: str,
                        normal: dict,
                        *,
                        trace=calls,
                        failed_service=failure_service,
                        outcome=decision,
                        count=mutation_count,
                    ):
                        def invoke(*args, **_kwargs):
                            trace.append(name)
                            if name == failed_service:
                                return {
                                    "status": outcome,
                                    "decision": outcome,
                                    "mutation_count": count,
                                    "exit_code": 2,
                                    "reason_codes": [f"SERVICE_{outcome}"],
                                }
                            if name == "write":
                                Path(args[0]).write_text("{}\n", encoding="utf-8")
                            return normal
                        return invoke

                    def formal_truth_writer(*_args, trace=calls, **_kwargs):
                        trace.append("formal-write")
                        raise AssertionError("formal truth writer must not run in child revalidation")

                    services = {
                        "resolve": service(
                            "resolve", resolved_authorization(authorization_payload)
                        ),
                        "observe_current": service("observe", current_observation()),
                        "create_once_writer": service("write", applied_result()),
                        "postcheck_reader": service(
                            "postcheck", verified_payload(authorization_payload)
                        ),
                        "projector": service(
                            "project",
                            {"decision": "READY", "phase": "COMPLETE", "complete": True},
                        ),
                        "formal_truth_writer": formal_truth_writer,
                    }
                    stdout = StringIO()
                    with redirect_stdout(stdout):
                        exit_code = story_evidence.main([
                            "revalidate-cp6", "--action", action, "--output", output_format,
                            "--authorization", str(authorization_path), "--target", str(target),
                            "--project-root", str(root),
                        ], services=services)
                    assert exit_code == 2
                    assert calls == expected_trace
                    if output_format == "json":
                        output = json.loads(stdout.getvalue())
                        assert (output["action"], output["decision"], output["status"]) == (action, decision, decision)
                        assert output["mutation_count"] == mutation_count
                    else:
                        output = stdout.getvalue()
                        for fragment in (
                            f"action={action}", f"decision={decision}",
                            f"status={decision}", f"mutation_count={mutation_count}",
                        ):
                            assert fragment in output


def test_a003_r7_dispatcher_and_default_main_fail_closed_on_untyped_or_invalid_inputs() -> None:
    actions = ("plan", "apply", "replay", "inspect", "recover", "completion")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        authorization_payload = build_public_revalidation_authorization()
        for action in actions:
            target = root / f"u-{action}.json"
            if action in {"replay", "inspect"}:
                target.write_text("{}\n", encoding="utf-8")
            services = {
                "resolve": lambda *_args, **_kwargs: None,
                "observe_current": lambda *_args, **_kwargs: None,
                "create_once_writer": lambda *_args, **_kwargs: None,
                "postcheck_reader": lambda *_args, **_kwargs: None,
                "projector": lambda *_args, **_kwargs: None,
            }
            blocked = story_evidence.run_cp6_revalidation_operation(
                request={"action": action, "authorization": {}, "target": target},
                services=services,
            )
            assert (blocked["decision"], blocked["mutation_count"], blocked["exit_code"]) == (
                "BLOCKED", 0, 2,
            )

        malformed_resolve = story_evidence.run_cp6_revalidation_operation(
            request={
                "action": "plan", "authorization": authorization_payload,
                "target": root / "malformed.json",
            },
            services={
                "resolve": lambda *_args, **_kwargs: {"unexpected": True},
                "observe_current": lambda *_args, **_kwargs: {"status": "current"},
            },
        )
        assert (malformed_resolve["decision"], malformed_resolve["mutation_count"]) == (
            "BLOCKED", 0,
        )

        incomplete_target = root / "u-incomplete.json"
        incomplete = story_evidence.run_cp6_revalidation_operation(
            request={
                "action": "completion", "authorization": authorization_payload,
                "target": incomplete_target,
            },
            services={
                "resolve": lambda *_args, **_kwargs: resolved_authorization(
                    authorization_payload
                ),
                "observe_current": lambda *_args, **_kwargs: current_observation(),
                "projector": lambda *_args, **_kwargs: {
                    "decision": "READY", "phase": "PROJECTED", "complete": False,
                },
                "create_once_writer": lambda *_args, **_kwargs: pytest.fail(
                    "writer called for incomplete projector"
                ),
                "postcheck_reader": lambda *_args, **_kwargs: pytest.fail(
                    "postcheck called for incomplete projector"
                ),
            },
        )
        assert (incomplete["decision"], incomplete["mutation_count"]) == ("BLOCKED", 0)
        assert not incomplete_target.exists()

        mutated_target = root / "u-mutated.json"

        def corrupt_then_raise(path: Path, _payload: dict) -> None:
            path.write_bytes(b"corrupt")
            raise OSError("interrupted")

        partial = story_evidence.run_cp6_revalidation_operation(
            request={
                "action": "apply", "authorization": authorization_payload,
                "target": mutated_target,
            },
            services={
                "resolve": lambda *_args, **_kwargs: resolved_authorization(
                    authorization_payload
                ),
                "observe_current": lambda *_args, **_kwargs: current_observation(),
                "create_once_writer": corrupt_then_raise,
                "postcheck_reader": lambda *_args, **_kwargs: pytest.fail(
                    "postcheck called after writer exception"
                ),
                "projector": lambda *_args, **_kwargs: {},
            },
        )
        assert (partial["decision"], partial["mutation_count"], partial["exit_code"]) == (
            "PARTIAL", 1, 2,
        )
        assert mutated_target.read_bytes() == b"corrupt"

        typed_failures = (
            {"decision": "PASS", "status": "BLOCKED", "mutation_count": 0},
            {"status": "READY", "mutation_count": 0},
            {"status": "READY", "mutation_count": 0, "unexpected": True},
            {"decision": "BLOCKED", "mutation_count": "abc", "reason_codes": ["X"]},
            {"decision": "PARTIAL", "mutation_count": True, "reason_codes": ["X"]},
            {"decision": "PARTIAL", "mutation_count": -1, "reason_codes": ["X"]},
        )
        for result in typed_failures:
            calls = []
            blocked = story_evidence.run_cp6_revalidation_operation(
                request={
                    "action": "plan", "authorization": authorization_payload,
                    "target": root / "typed-invalid.json",
                },
                services={
                    "resolve": lambda *_args, value=result, **_kwargs: value,
                    "observe_current": (
                        lambda *_args, trace=calls, **_kwargs: trace.append("observe")
                    ),
                },
            )
            assert (blocked["decision"], blocked["mutation_count"], calls) == (
                "BLOCKED", 0, [],
            )

        writer_target = root / "typed-writer.json"

        def conflicting_writer(path: Path, payload: dict) -> dict:
            path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
            return {"decision": "PASS", "status": "BLOCKED", "mutation_count": 1}

        writer_conflict = story_evidence.run_cp6_revalidation_operation(
            request={
                "action": "apply", "authorization": authorization_payload,
                "target": writer_target,
            },
            services={
                "resolve": lambda *_args, **_kwargs: resolved_authorization(
                    authorization_payload
                ),
                "observe_current": lambda *_args, **_kwargs: current_observation(),
                "create_once_writer": conflicting_writer,
                "postcheck_reader": lambda *_args, **_kwargs: pytest.fail(
                    "postcheck called after conflicting writer result"
                ),
            },
        )
        assert (writer_conflict["decision"], writer_conflict["mutation_count"]) == (
            "PARTIAL", 1,
        )

        string_count_target = root / "typed-string-count.json"

        def string_count_writer(path: Path, payload: dict) -> dict:
            path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
            return {"status": "APPLIED", "mutation_count": "1"}

        string_count = story_evidence.run_cp6_revalidation_operation(
            request={
                "action": "apply", "authorization": authorization_payload,
                "target": string_count_target,
            },
            services={
                "resolve": lambda *_args, **_kwargs: resolved_authorization(
                    authorization_payload
                ),
                "observe_current": lambda *_args, **_kwargs: current_observation(),
                "create_once_writer": string_count_writer,
                "postcheck_reader": lambda *_args, **_kwargs: pytest.fail(
                    "postcheck called after invalid writer count"
                ),
            },
        )
        assert (string_count["decision"], string_count["mutation_count"]) == (
            "PARTIAL", 1,
        )

        authorization = root / "u-authorization.json"
        authorization.write_text("{}\n", encoding="utf-8")
        default_target = root / "u-default.json"
        output = StringIO()
        with redirect_stdout(output):
            exit_code = story_evidence.main([
                "revalidate-cp6", "--action", "apply", "--output", "json",
                "--authorization", str(authorization), "--target", str(default_target),
                "--project-root", str(root),
            ])
        assert exit_code == 2
        assert json.loads(output.getvalue())["decision"] == "BLOCKED"
        assert not default_target.exists()


def test_a003_r8_default_cli_executes_real_plan_apply_replay_and_inspect() -> None:
    with tempfile.TemporaryDirectory() as directory:
        release, process, authorization, authorization_ref, target_ref, policy_ref = (
            init_public_revalidation_project(Path(directory))
        )
        target_observation = {
            "logical_ref": target_ref, "exists": False, "preimage_digest": "",
        }
        plan_context_ref = "process/contexts/plan.json"
        _write_process_json(
            process,
            plan_context_ref,
            {
                "schema_version": 1,
                "action": "plan",
                "payload": {"downstream_policy_ref": policy_ref},
            },
        )
        plan_stdout = StringIO()
        with redirect_stdout(plan_stdout):
            plan_exit = story_evidence.main([
                "revalidate-cp6", "--action", "plan", "--output", "json",
                "--authorization", authorization_ref, "--target", target_ref,
                "--context", plan_context_ref, "--project-root", str(release),
            ])
        assert plan_exit == 0
        plan_result = json.loads(plan_stdout.getvalue())
        assert (plan_result["decision"], plan_result["status"], plan_result["mutation_count"]) == (
            "PASS", "READY", 0,
        )
        assert plan_result["plan"]["target_observation"] == target_observation

        stale_authorization = build_public_revalidation_authorization(
            release_oid="0" * 40,
            process_oid=authorization["process_oid"],
            scope_digest=authorization["scope_digest"],
        )
        _write_process_json(process, authorization_ref, stale_authorization)
        stale_stdout = StringIO()
        with redirect_stdout(stale_stdout):
            stale_exit = story_evidence.main([
                "revalidate-cp6", "--action", "plan", "--output", "json",
                "--authorization", authorization_ref, "--target", target_ref,
                "--context", plan_context_ref, "--project-root", str(release),
            ])
        stale_result = json.loads(stale_stdout.getvalue())
        assert (stale_exit, stale_result["decision"], stale_result["mutation_count"]) == (
            2, "BLOCKED", 0,
        )
        _write_process_json(process, authorization_ref, authorization)

        alternate_policy_ref = (
            f"process/works/W-X/revalidation/{authorization['attempt_id']}/"
            "CALLER-REBIND-POLICY.json"
        )
        arbitrary_consumers = {"ARBITRARY": ["OTHER"]}
        _write_process_json(
            process,
            alternate_policy_ref,
            {
                "schema_version": 1,
                "consumers": arbitrary_consumers,
                "policy_digest": canonical_digest(arbitrary_consumers),
                "current_receipts": authorization["payload"]["downstream_set"],
            },
        )
        alternate_context_ref = "process/contexts/plan-caller-rebound.json"
        _write_process_json(
            process,
            alternate_context_ref,
            {
                "schema_version": 1,
                "action": "plan",
                "payload": {"downstream_policy_ref": alternate_policy_ref},
            },
        )
        alternate_stdout = StringIO()
        with redirect_stdout(alternate_stdout):
            alternate_exit = story_evidence.main([
                "revalidate-cp6", "--action", "plan", "--output", "json",
                "--authorization", authorization_ref, "--target", target_ref,
                "--context", alternate_context_ref, "--project-root", str(release),
            ])
        alternate_result = json.loads(alternate_stdout.getvalue())
        assert (
            alternate_exit,
            alternate_result["decision"],
            alternate_result["mutation_count"],
        ) == (2, "BLOCKED", 0)

        plan_ref = "process/contexts/plan-result.json"
        _write_process_json(process, plan_ref, plan_result)
        apply_context_ref = "process/contexts/apply.json"
        _write_process_json(
            process,
            apply_context_ref,
            {
                "schema_version": 1,
                "action": "apply",
                "payload": {
                    "plan_ref": plan_ref,
                    "expected_plan_digest": plan_result["plan_digest"],
                    "downstream_policy_ref": policy_ref,
                },
            },
        )
        policy_path = process / policy_ref.removeprefix("process/")
        canonical_policy_bytes = policy_path.read_bytes()
        rebound_consumers = {"ARBITRARY": ["OTHER"]}
        _write_process_json(
            process,
            policy_ref,
            {
                "schema_version": 1,
                "consumers": rebound_consumers,
                "policy_digest": canonical_digest(rebound_consumers),
                "current_receipts": authorization["payload"]["downstream_set"],
            },
        )
        drift_stdout = StringIO()
        with redirect_stdout(drift_stdout):
            drift_exit = story_evidence.main([
                "revalidate-cp6", "--action", "apply", "--output", "json",
                "--authorization", authorization_ref, "--target", target_ref,
                "--context", apply_context_ref, "--project-root", str(release),
            ])
        drift_result = json.loads(drift_stdout.getvalue())
        assert (drift_exit, drift_result["decision"], drift_result["mutation_count"]) == (
            2, "BLOCKED", 0,
        )
        target_path = process / target_ref.removeprefix("process/")
        assert not target_path.exists()
        policy_path.write_bytes(canonical_policy_bytes)

        apply_stdout = StringIO()
        with redirect_stdout(apply_stdout):
            apply_exit = story_evidence.main([
                "revalidate-cp6", "--action", "apply", "--output", "json",
                "--authorization", authorization_ref, "--target", target_ref,
                "--context", apply_context_ref, "--project-root", str(release),
            ])
        assert apply_exit == 0
        apply_result = json.loads(apply_stdout.getvalue())
        assert (apply_result["decision"], apply_result["status"], apply_result["mutation_count"]) == (
            "PASS", "APPLIED", 1,
        )
        assert json.loads(target_path.read_text(encoding="utf-8")) == authorization

        for action, expected_status in (("replay", "NO_CHANGE"), ("inspect", "READY")):
            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = story_evidence.main([
                    "revalidate-cp6", "--action", action, "--output", "json",
                    "--authorization", authorization_ref, "--target", target_ref,
                    "--project-root", str(release),
                ])
            result = json.loads(stdout.getvalue())
            assert exit_code == 0
            assert (result["decision"], result["status"], result["mutation_count"]) == (
                "PASS", expected_status, 0,
            )

        human_stdout = StringIO()
        with redirect_stdout(human_stdout):
            human_exit = story_evidence.main([
                "revalidate-cp6", "--action", "plan", "--output", "human",
                "--authorization", authorization_ref, "--target", target_ref,
                "--context", plan_context_ref, "--project-root", str(release),
            ])
        assert human_exit == 0
        for fragment in ("action=plan", "status=READY", "decision=PASS", "mutation_count=0"):
            assert fragment in human_stdout.getvalue()


def test_a003_r12_apply_detects_policy_drift_inside_writer_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        release, process, authorization, authorization_ref, target_ref, policy_ref = (
            init_public_revalidation_project(Path(directory))
        )
        plan_context_ref = "process/contexts/r12-plan.json"
        _write_process_json(
            process,
            plan_context_ref,
            {
                "schema_version": 1,
                "action": "plan",
                "payload": {"downstream_policy_ref": policy_ref},
            },
        )
        plan_stdout = StringIO()
        with redirect_stdout(plan_stdout):
            plan_exit = story_evidence.main([
                "revalidate-cp6", "--action", "plan", "--output", "json",
                "--authorization", authorization_ref, "--target", target_ref,
                "--context", plan_context_ref, "--project-root", str(release),
            ])
        assert plan_exit == 0
        plan_result = json.loads(plan_stdout.getvalue())
        plan_ref = "process/contexts/r12-plan-result.json"
        _write_process_json(process, plan_ref, plan_result)
        apply_context_ref = "process/contexts/r12-apply.json"
        _write_process_json(
            process,
            apply_context_ref,
            {
                "schema_version": 1,
                "action": "apply",
                "payload": {
                    "plan_ref": plan_ref,
                    "expected_plan_digest": plan_result["plan_digest"],
                    "downstream_policy_ref": policy_ref,
                },
            },
        )
        policy_path = process / policy_ref.removeprefix("process/")
        original_writer = story_evidence._create_once_json

        def race_writer(path: Path, payload: dict) -> dict:
            rebound_consumers = {"RACE": ["POST-PRECOMMIT"]}
            _write_process_json(
                process,
                policy_ref,
                {
                    "schema_version": 1,
                    "consumers": rebound_consumers,
                    "policy_digest": canonical_digest(rebound_consumers),
                    "current_receipts": authorization["payload"]["downstream_set"],
                },
            )
            assert policy_path.exists()
            return original_writer(path, payload)

        monkeypatch.setattr(story_evidence, "_create_once_json", race_writer)
        apply_stdout = StringIO()
        with redirect_stdout(apply_stdout):
            apply_exit = story_evidence.main([
                "revalidate-cp6", "--action", "apply", "--output", "json",
                "--authorization", authorization_ref, "--target", target_ref,
                "--context", apply_context_ref, "--project-root", str(release),
            ])
        apply_result = json.loads(apply_stdout.getvalue())
        target_path = process / target_ref.removeprefix("process/")
        assert (apply_exit, apply_result["decision"], apply_result["mutation_count"]) == (
            2, "PARTIAL", 1,
        )
        assert target_path.exists()


def test_a003_r12_completion_blocks_admission_drift_before_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        fixture = init_public_completion_operation(Path(directory))
        process = fixture["process"]
        assert isinstance(process, Path)
        admission_plan_ref = fixture["admission_plan_ref"]
        assert isinstance(admission_plan_ref, str)
        original_reader = story_evidence._current_revalidation_admission_plan

        def race_reader(*args, **kwargs):
            snapshot = original_reader(*args, **kwargs)
            drifted_payload = {
                "authorization_digest": "0" * 64,
                "bound_policy": snapshot["bound_policy"],
            }
            _write_process_json(
                process,
                admission_plan_ref,
                {
                    **drifted_payload,
                    "plan_digest": canonical_digest(drifted_payload),
                },
            )
            return snapshot

        monkeypatch.setattr(
            story_evidence,
            "_current_revalidation_admission_plan",
            race_reader,
        )
        completion_stdout = StringIO()
        with redirect_stdout(completion_stdout):
            completion_exit = story_evidence.main([
                "revalidate-cp6", "--action", "completion", "--output", "json",
                "--authorization", str(fixture["authorization_ref"]),
                "--target", str(fixture["target_ref"]),
                "--context", str(fixture["context_ref"]),
                "--project-root", str(fixture["release"]),
            ])
        completion_result = json.loads(completion_stdout.getvalue())
        target_path = process / str(fixture["target_ref"]).removeprefix("process/")
        assert (
            completion_exit,
            completion_result["decision"],
            completion_result["mutation_count"],
        ) == (2, "BLOCKED", 0)
        assert not target_path.exists()


def test_a003_r12_completion_detects_selector_drift_inside_writer_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        fixture = init_public_completion_operation(Path(directory))
        process = fixture["process"]
        assert isinstance(process, Path)
        selector_ref = fixture["current_selections_ref"]
        assert isinstance(selector_ref, str)
        original_writer = story_evidence._create_once_json

        def race_writer(path: Path, payload: dict) -> dict:
            superseded = [{
                "producer": "I01",
                "consumer": "W2",
                "current_ref": "process/receipts/downstream.json",
                "superseded_by": "process/receipts/downstream-v2.json",
            }]
            _write_process_json(
                process,
                selector_ref,
                {
                    "schema_version": 1,
                    "selections": superseded,
                    "selection_digest": canonical_digest(superseded),
                },
            )
            return original_writer(path, payload)

        monkeypatch.setattr(story_evidence, "_create_once_json", race_writer)
        completion_stdout = StringIO()
        with redirect_stdout(completion_stdout):
            completion_exit = story_evidence.main([
                "revalidate-cp6", "--action", "completion", "--output", "json",
                "--authorization", str(fixture["authorization_ref"]),
                "--target", str(fixture["target_ref"]),
                "--context", str(fixture["context_ref"]),
                "--project-root", str(fixture["release"]),
            ])
        completion_result = json.loads(completion_stdout.getvalue())
        target_path = process / str(fixture["target_ref"]).removeprefix("process/")
        assert (
            completion_exit,
            completion_result["decision"],
            completion_result["mutation_count"],
        ) == (2, "PARTIAL", 1)
        assert target_path.exists()


def test_a003_r13_apply_detects_policy_drift_inside_target_postcheck(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        fixture = init_public_apply_operation(Path(directory))
        process = fixture["process"]
        assert isinstance(process, Path)
        target_path = process / str(fixture["target_ref"]).removeprefix("process/")
        policy_ref = fixture["policy_ref"]
        assert isinstance(policy_ref, str)
        authorization = fixture["authorization"]
        assert isinstance(authorization, dict)
        original_reader = story_evidence._read_json

        def race_reader(path: Path) -> dict:
            payload = original_reader(path)
            if path == target_path:
                rebound_consumers = {"RACE": ["TARGET-POSTCHECK"]}
                _write_process_json(
                    process,
                    policy_ref,
                    {
                        "schema_version": 1,
                        "consumers": rebound_consumers,
                        "policy_digest": canonical_digest(rebound_consumers),
                        "current_receipts": authorization["payload"][
                            "downstream_set"
                        ],
                    },
                )
            return payload

        monkeypatch.setattr(story_evidence, "_read_json", race_reader)
        apply_stdout = StringIO()
        with redirect_stdout(apply_stdout):
            apply_exit = story_evidence.main([
                "revalidate-cp6", "--action", "apply", "--output", "json",
                "--authorization", str(fixture["authorization_ref"]),
                "--target", str(fixture["target_ref"]),
                "--context", str(fixture["context_ref"]),
                "--project-root", str(fixture["release"]),
            ])
        apply_result = json.loads(apply_stdout.getvalue())
        assert (apply_exit, apply_result["decision"], apply_result["mutation_count"]) == (
            2, "PARTIAL", 1,
        )
        assert target_path.exists()


def test_a003_r13_completion_detects_selector_drift_inside_target_postcheck(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        fixture = init_public_completion_operation(Path(directory))
        process = fixture["process"]
        assert isinstance(process, Path)
        target_path = process / str(fixture["target_ref"]).removeprefix("process/")
        selector_ref = fixture["current_selections_ref"]
        assert isinstance(selector_ref, str)
        original_reader = story_evidence._read_json

        def race_reader(path: Path) -> dict:
            payload = original_reader(path)
            if path == target_path:
                superseded = [{
                    "producer": "I01",
                    "consumer": "W2",
                    "current_ref": "process/receipts/downstream.json",
                    "superseded_by": "process/receipts/downstream-v2.json",
                }]
                _write_process_json(
                    process,
                    selector_ref,
                    {
                        "schema_version": 1,
                        "selections": superseded,
                        "selection_digest": canonical_digest(superseded),
                    },
                )
            return payload

        monkeypatch.setattr(story_evidence, "_read_json", race_reader)
        completion_stdout = StringIO()
        with redirect_stdout(completion_stdout):
            completion_exit = story_evidence.main([
                "revalidate-cp6", "--action", "completion", "--output", "json",
                "--authorization", str(fixture["authorization_ref"]),
                "--target", str(fixture["target_ref"]),
                "--context", str(fixture["context_ref"]),
                "--project-root", str(fixture["release"]),
            ])
        completion_result = json.loads(completion_stdout.getvalue())
        assert (
            completion_exit,
            completion_result["decision"],
            completion_result["mutation_count"],
        ) == (2, "PARTIAL", 1)
        assert target_path.exists()


@pytest.mark.parametrize(
    ("action", "payload"),
    (
        (
            "plan",
            {
                "source_observation": {
                    "release_oid": "b" * 40,
                    "process_oid": "c" * 40,
                    "scope_digest": "d" * 64,
                },
                "downstream_policy": {
                    "consumers": {"ARBITRARY": ["OTHER"]},
                    "policy_digest": canonical_digest({"ARBITRARY": ["OTHER"]}),
                    "current_receipts": [],
                },
            },
        ),
        (
            "apply",
            {
                "plan_ref": "process/contexts/plan.json",
                "expected_plan_digest": "a" * 64,
                "current_observation": {
                    "source_observation": {},
                    "target_observation": {},
                    "downstream_policy": {},
                },
            },
        ),
        (
            "completion",
            {
                "required_digests": {},
                "p01_event_ref": "process/events/p01.json",
                "projection_ref": "process/receipts/projection.json",
                "consumer": "W2",
                "receipt_refs": [],
                "plan_observation": {},
                "current_attempt": {},
                "current_selections": [],
            },
        ),
    ),
)
def test_a003_r10_rejects_caller_inlined_currentness_claims(
    action: str,
    payload: dict,
) -> None:
    """R10：production context 只能携带 canonical refs，不能重述 current 事实。"""

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        context_ref = f"process/contexts/{action}.json"
        (root / context_ref).parent.mkdir(parents=True)
        (root / context_ref).write_text(
            json.dumps(
                {"schema_version": 1, "action": action, "payload": payload},
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="payload fields mismatch"):
            story_evidence._load_revalidation_action_context(
                root,
                context_ref,
                action=action,
            )


def test_a003_r10_default_plan_rejects_self_consistent_noncurrent_source() -> None:
    """R10：auth/context 即使内部自洽，也不能替代 live release/process/scope。"""

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        authorization = build_public_revalidation_authorization()
        authorization_ref = "process/receipts/input-authorization.json"
        target_ref = (
            "process/works/W-X/revalidation/attempt-public-61e9/authorization.json"
        )
        context_ref = "process/contexts/plan.json"
        for logical_ref, payload in (
            (authorization_ref, authorization),
            (
                context_ref,
                {
                    "schema_version": 1,
                    "action": "plan",
                    "payload": {
                        "source_observation": {
                            "release_oid": authorization["release_oid"],
                            "process_oid": authorization["process_oid"],
                            "scope_digest": authorization["scope_digest"],
                        },
                        "downstream_policy": {
                            "consumers": {"I01": ["P02"]},
                            "policy_digest": canonical_digest({"I01": ["P02"]}),
                            "current_receipts": authorization["payload"]["downstream_set"],
                        },
                    },
                },
            ),
        ):
            path = root / logical_ref
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")

        stdout = StringIO()
        with redirect_stdout(stdout):
            exit_code = story_evidence.main(
                [
                    "revalidate-cp6",
                    "--action",
                    "plan",
                    "--output",
                    "json",
                    "--authorization",
                    authorization_ref,
                    "--target",
                    target_ref,
                    "--context",
                    context_ref,
                    "--project-root",
                    str(root),
                ]
            )
        result = json.loads(stdout.getvalue())
        assert (exit_code, result["decision"], result["mutation_count"]) == (
            2,
            "BLOCKED",
            0,
        )


def test_a003_r10_default_apply_rejects_reserved_formal_truth_target() -> None:
    """R10：create-once 不能被用作任意 process/formal-truth 写能力。"""

    with tempfile.TemporaryDirectory() as directory:
        release, process, _authorization, authorization_ref, target_ref, _policy_ref = (
            init_public_revalidation_project(Path(directory))
        )
        context_ref = "process/contexts/not-consumed.json"
        invalid_targets = (
            "process/state/STATE.current.json",
            target_ref.replace("process/works/W-X/", "process/works/OTHER/"),
            target_ref.replace("attempt-public-61e9", "other-attempt"),
            target_ref.replace("authorization.json", "completion.json"),
        )
        for invalid_target_ref in invalid_targets:
            before = (
                process / invalid_target_ref.removeprefix("process/")
            ).read_bytes() if (
                process / invalid_target_ref.removeprefix("process/")
            ).is_file() else None
            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = story_evidence.main(
                    [
                        "revalidate-cp6",
                        "--action",
                        "apply",
                        "--output",
                        "json",
                        "--authorization",
                        authorization_ref,
                        "--target",
                        invalid_target_ref,
                        "--context",
                        context_ref,
                        "--project-root",
                        str(release),
                    ]
                )
            result = json.loads(stdout.getvalue())
            assert (exit_code, result["decision"], result["mutation_count"]) == (
                2,
                "BLOCKED",
                0,
            )
            path = process / invalid_target_ref.removeprefix("process/")
            after = path.read_bytes() if path.is_file() else None
            assert after == before


def test_a003_r11_rejects_live_but_owner_unauthorized_attempt() -> None:
    """R11：live OID/scope 不能让 caller 自签新 attempt 并获得写 capability。"""

    with tempfile.TemporaryDirectory() as directory:
        release, process, owner_authorization, _owner_ref, _target_ref, _policy_ref = (
            init_public_revalidation_project(Path(directory))
        )
        attacker_attempt = "attacker-attempt"
        attacker = build_public_revalidation_authorization(
            attempt_id=attacker_attempt,
            release_oid=owner_authorization["release_oid"],
            process_oid=owner_authorization["process_oid"],
            scope_digest=owner_authorization["scope_digest"],
        )
        namespace = f"process/works/W-X/revalidation/{attacker_attempt}"
        authorization_ref = f"{namespace}/OWNER-AUTHORIZATION.json"
        policy_ref = f"{namespace}/CURRENT-DOWNSTREAM-POLICY.json"
        target_ref = f"{namespace}/receipts/authorization.json"
        _write_process_json(process, authorization_ref, attacker)
        consumers = {"I01": ["P02"]}
        _write_process_json(
            process,
            policy_ref,
            {
                "schema_version": 1,
                "consumers": consumers,
                "policy_digest": canonical_digest(consumers),
                "current_receipts": attacker["payload"]["downstream_set"],
            },
        )
        plan_context_ref = "process/contexts/attacker-plan.json"
        _write_process_json(
            process,
            plan_context_ref,
            {
                "schema_version": 1,
                "action": "plan",
                "payload": {"downstream_policy_ref": policy_ref},
            },
        )
        plan_stdout = StringIO()
        with redirect_stdout(plan_stdout):
            plan_exit = story_evidence.main([
                "revalidate-cp6", "--action", "plan", "--output", "json",
                "--authorization", authorization_ref, "--target", target_ref,
                "--context", plan_context_ref, "--project-root", str(release),
            ])
        plan_result = json.loads(plan_stdout.getvalue())
        if plan_exit == 0:
            plan_ref = "process/contexts/attacker-plan-result.json"
            _write_process_json(process, plan_ref, plan_result)
            apply_context_ref = "process/contexts/attacker-apply.json"
            _write_process_json(
                process,
                apply_context_ref,
                {
                    "schema_version": 1,
                    "action": "apply",
                    "payload": {
                        "plan_ref": plan_ref,
                        "expected_plan_digest": plan_result["plan_digest"],
                        "downstream_policy_ref": policy_ref,
                    },
                },
            )
            apply_stdout = StringIO()
            with redirect_stdout(apply_stdout):
                apply_exit = story_evidence.main([
                    "revalidate-cp6", "--action", "apply", "--output", "json",
                    "--authorization", authorization_ref, "--target", target_ref,
                    "--context", apply_context_ref, "--project-root", str(release),
                ])
            apply_result = json.loads(apply_stdout.getvalue())
        else:
            apply_exit = 2
            apply_result = {"decision": "BLOCKED", "mutation_count": 0}
        assert (plan_exit, plan_result["decision"], plan_result["mutation_count"]) == (
            2, "BLOCKED", 0,
        )
        assert (apply_exit, apply_result["decision"], apply_result["mutation_count"]) == (
            2, "BLOCKED", 0,
        )
        assert not (process / target_ref.removeprefix("process/")).exists()


@pytest.mark.parametrize("tampered_input", ("policy", "admission", "selector"))
def test_a003_r11_owner_authority_rejects_self_rebound_canonical_input(
    tampered_input: str,
) -> None:
    """R11：确定性路径和自摘要不能替代 Work owner 绑定的 exact bytes。"""

    with tempfile.TemporaryDirectory() as directory:
        release, process, authorization, authorization_ref, target_ref, policy_ref = (
            init_public_revalidation_project(Path(directory))
        )
        namespace = f"process/works/W-X/revalidation/{authorization['attempt_id']}"
        if tampered_input == "policy":
            attacker_consumers = {"ATTACKER-CONSUMER": ["ATTACKER-PRODUCER"]}
            _write_process_json(
                process,
                policy_ref,
                {
                    "schema_version": 1,
                    "consumers": attacker_consumers,
                    "policy_digest": canonical_digest(attacker_consumers),
                    "current_receipts": authorization["payload"]["downstream_set"],
                },
            )
        elif tampered_input == "admission":
            admission_ref = f"{namespace}/DOWNSTREAM-ADMISSION-PLAN.json"
            bound_policy_payload = {"schema_version": 1, "consumers": {"W2": ["I01"]}}
            wrong_payload = {
                "authorization_digest": "f" * 64,
                "bound_policy": {
                    **bound_policy_payload,
                    "policy_digest": canonical_digest(bound_policy_payload),
                },
            }
            _write_process_json(
                process,
                admission_ref,
                {**wrong_payload, "plan_digest": canonical_digest(wrong_payload)},
            )
        else:
            selector_ref = f"{namespace}/CURRENT-DOWNSTREAM-SELECTIONS.json"
            rebound = [{
                "producer": "I01",
                "consumer": "W2",
                "current_ref": "process/receipts/attacker-selected.json",
                "superseded_by": "",
            }]
            _write_process_json(
                process,
                selector_ref,
                {
                    "schema_version": 1,
                    "selections": rebound,
                    "selection_digest": canonical_digest(rebound),
                },
            )
        context_ref = f"process/contexts/owner-input-{tampered_input}.json"
        _write_process_json(
            process,
            context_ref,
            {
                "schema_version": 1,
                "action": "plan",
                "payload": {"downstream_policy_ref": policy_ref},
            },
        )
        stdout = StringIO()
        with redirect_stdout(stdout):
            exit_code = story_evidence.main([
                "revalidate-cp6", "--action", "plan", "--output", "json",
                "--authorization", authorization_ref, "--target", target_ref,
                "--context", context_ref, "--project-root", str(release),
            ])
        result = json.loads(stdout.getvalue())
        assert (exit_code, result["decision"], result["mutation_count"]) == (
            2, "BLOCKED", 0,
        )


@pytest.mark.parametrize(
    "tampered_lineage",
    ("authorization", "previous_cp6", "superseding_cp5", "approval"),
)
def test_a003_r11_owner_authority_rejects_authorization_lineage_bytes_drift(
    tampered_lineage: str,
) -> None:
    """R11：owner authority 绑定 auth/approval/CP5/previous CP6 的 exact bytes。"""

    with tempfile.TemporaryDirectory() as directory:
        release, process, authorization, authorization_ref, target_ref, policy_ref = (
            init_public_revalidation_project(Path(directory))
        )
        refs = {
            "authorization": authorization_ref,
            "previous_cp6": authorization["payload"]["previous_cp6_ref"],
            "superseding_cp5": authorization["payload"]["superseding_cp5_ref"],
            "approval": authorization["payload"]["approval_ref"],
        }
        tampered_path = process / refs[tampered_lineage].removeprefix("process/")
        tampered_path.write_bytes(tampered_path.read_bytes() + b"\n")
        context_ref = f"process/contexts/lineage-{tampered_lineage}.json"
        _write_process_json(
            process,
            context_ref,
            {
                "schema_version": 1,
                "action": "plan",
                "payload": {"downstream_policy_ref": policy_ref},
            },
        )
        stdout = StringIO()
        with redirect_stdout(stdout):
            exit_code = story_evidence.main([
                "revalidate-cp6", "--action", "plan", "--output", "json",
                "--authorization", authorization_ref, "--target", target_ref,
                "--context", context_ref, "--project-root", str(release),
            ])
        result = json.loads(stdout.getvalue())
        assert (exit_code, result["decision"], result["mutation_count"]) == (
            2, "BLOCKED", 0,
        )


def test_a003_r9_default_cli_executes_real_completion_and_recover() -> None:
    with tempfile.TemporaryDirectory() as directory:
        attempt_id = "attempt-public-61e9"
        downstream_payload = {
            "schema_version": 1,
            "producer": "I01",
            "consumer": "W2",
            "story_id": "STORY-X",
            "attempt_id": attempt_id,
        }
        downstream_bytes = (
            json.dumps(downstream_payload, sort_keys=True) + "\n"
        ).encode()
        release, process, authorization, authorization_ref, _target_ref, _policy_ref = (
            init_public_revalidation_project(
                Path(directory),
                attempt_id=attempt_id,
                downstream_set=[{
                    "producer": "I01",
                    "receipt_digest": hashlib.sha256(downstream_bytes).hexdigest(),
                    "attempt_id": attempt_id,
                }],
            )
        )
        packet = {
            "schema_version": 3,
            "lld_policy": "full-lld",
            "read_if_needed": [{
                "path": "process/stories/STORY-X-LLD.md",
                "trigger": "full_lld_required_by_policy",
                "consumer_requirement": "required",
            }],
        }
        selected = ["process/stories/STORY-X-LLD.md"]
        event = {
            "packet": packet,
            "selected_refs": selected,
            "selection_digest": canonical_digest(selected),
            "story_id": authorization["story_id"],
            "work_id": authorization["work_id"],
            "attempt_id": authorization["attempt_id"],
            "stage": "CP6",
            "context_ref": "process/context/X.json",
            "scope_digest": authorization["scope_digest"],
            "reason": "summary_insufficient",
            "reason_evidence": {"missing_slots": ["full_lld_body"]},
            "requested_ref": selected[0],
            "preregistered_by": "host",
            "bytes_digest": "b" * 64,
        }
        event_ref = "process/events/p01.json"
        event_bytes = (json.dumps(event, sort_keys=True) + "\n").encode()
        event_path = process / event_ref.removeprefix("process/")
        event_path.parent.mkdir(parents=True, exist_ok=True)
        event_path.write_bytes(event_bytes)
        required = {key: "f" * 64 for key in (
            "packet_digest", "read_log_digest", "return_digest", "evidence_digest",
            "result_digest", "checkpoint_digest", "plan_digest", "downstream_set_digest",
        )}
        required["downstream_set_digest"] = authorization["payload"]["downstream_set_digest"]
        event_digest = hashlib.sha256(event_bytes).hexdigest()
        preflight = story_evidence.validate_cp6_revalidation_preflight(
            authorization,
            required_digests=required,
            p01_event={
                "logical_ref": event_ref,
                "event_bytes": event_bytes,
                "event_bytes_digest": event_digest,
                "current_event_bytes_digest": event_digest,
            },
        )
        assert preflight["decision"] == "READY"
        preflight_ref = "process/receipts/preflight.json"
        _write_process_json(process, preflight_ref, preflight["receipt"])
        projection_inner = {
            "schema_version": 1,
            "kind": "projection",
            "cr_id": authorization["cr_id"],
            "story_id": authorization["story_id"],
            "work_id": authorization["work_id"],
            "attempt_id": authorization["attempt_id"],
            "preflight_digest": preflight["receipt"]["payload_digest"],
            "phase": "COMPLETE",
        }
        projection_ref = "process/receipts/projection.json"
        _write_process_json(process, projection_ref, projection_inner)
        consumer = "W2"
        producer = "I01"
        downstream_ref = "process/receipts/downstream.json"
        _write_process_json(
            process,
            downstream_ref,
            downstream_payload,
        )
        consumers = {consumer: [producer]}
        policy_payload = {"schema_version": 1, "consumers": consumers}
        bound_policy = {
            **policy_payload,
            "policy_digest": canonical_digest(policy_payload),
        }
        plan_payload = {
            "authorization_digest": authorization["payload_digest"],
            "bound_policy": bound_policy,
        }
        plan_observation = {
            **plan_payload,
            "plan_digest": canonical_digest(plan_payload),
        }
        namespace = (
            f"process/works/W-X/revalidation/{authorization['attempt_id']}"
        )
        admission_plan_ref = f"{namespace}/DOWNSTREAM-ADMISSION-PLAN.json"
        _write_process_json(process, admission_plan_ref, plan_observation)
        selections = [{
            "producer": producer,
            "consumer": consumer,
            "current_ref": downstream_ref,
            "superseded_by": "",
        }]
        current_selections_ref = f"{namespace}/CURRENT-DOWNSTREAM-SELECTIONS.json"
        _write_process_json(
            process,
            current_selections_ref,
            {
                "schema_version": 1,
                "selections": selections,
                "selection_digest": canonical_digest(selections),
            },
        )
        completion_context_ref = "process/contexts/completion.json"
        _write_process_json(
            process,
            completion_context_ref,
            {
                "schema_version": 1,
                "action": "completion",
                "payload": {
                    "required_digests": required,
                    "p01_event_ref": event_ref,
                    "projection_ref": projection_ref,
                    "consumer": consumer,
                    "receipt_refs": [downstream_ref],
                    "admission_plan_ref": admission_plan_ref,
                    "current_selections_ref": current_selections_ref,
                },
            },
        )
        completion_target = f"{namespace}/receipts/completion.json"
        completion_stdout = StringIO()
        with redirect_stdout(completion_stdout):
            completion_exit = story_evidence.main([
                "revalidate-cp6", "--action", "completion", "--output", "json",
                "--authorization", authorization_ref, "--target", completion_target,
                "--context", completion_context_ref, "--project-root", str(release),
            ])
        completion_result = json.loads(completion_stdout.getvalue())
        assert completion_exit == 0
        assert (
            completion_result["decision"], completion_result["status"],
            completion_result["mutation_count"],
        ) == ("PASS", "COMPLETE", 1)
        completion_path = process / completion_target.removeprefix("process/")
        assert json.loads(completion_path.read_text(encoding="utf-8"))["kind"] == "completion"

        superseded = [{
            **selections[0],
            "superseded_by": "process/receipts/downstream-v2.json",
        }]
        _write_process_json(
            process,
            current_selections_ref,
            {
                "schema_version": 1,
                "selections": superseded,
                "selection_digest": canonical_digest(superseded),
            },
        )
        before_superseded_check = completion_path.read_bytes()
        superseded_stdout = StringIO()
        with redirect_stdout(superseded_stdout):
            superseded_exit = story_evidence.main([
                "revalidate-cp6", "--action", "completion", "--output", "json",
                "--authorization", authorization_ref, "--target", completion_target,
                "--context", completion_context_ref, "--project-root", str(release),
            ])
        superseded_result = json.loads(superseded_stdout.getvalue())
        assert (
            superseded_exit,
            superseded_result["decision"],
            superseded_result["mutation_count"],
        ) == (2, "BLOCKED", 0)
        assert completion_path.read_bytes() == before_superseded_check
        _write_process_json(
            process,
            current_selections_ref,
            {
                "schema_version": 1,
                "selections": selections,
                "selection_digest": canonical_digest(selections),
            },
        )

        recovery_context_ref = "process/contexts/recover.json"
        _write_process_json(
            process,
            recovery_context_ref,
            {
                "schema_version": 1,
                "action": "recover",
                "payload": {
                    "preflight_ref": preflight_ref,
                    "projection_ref": projection_ref,
                },
            },
        )
        recovery_target = completion_target
        recovery_stdout = StringIO()
        with redirect_stdout(recovery_stdout):
            recovery_exit = story_evidence.main([
                "revalidate-cp6", "--action", "recover", "--output", "json",
                "--authorization", authorization_ref, "--target", recovery_target,
                "--context", recovery_context_ref, "--project-root", str(release),
            ])
        recovery_result = json.loads(recovery_stdout.getvalue())
        assert recovery_exit == 0
        assert (
            recovery_result["decision"], recovery_result["status"],
            recovery_result["mutation_count"],
        ) == ("PASS", "NO_CHANGE", 0)


def write_cp6_projection_fixture(root: Path) -> None:
    process = root / "process"
    plan = {
        "story_management_truth_source": "process/DEVELOPMENT-PLAN.yaml",
        "waves": [
            {
                "wave_id": "W1",
                "stories": [
                    {
                        "story_id": "STORY-CR999-S01",
                        "title": "Projection",
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
                    }
                ],
            }
        ],
    }
    (process / "DEVELOPMENT-PLAN.yaml").parent.mkdir(parents=True)
    (process / "DEVELOPMENT-PLAN.yaml").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    result = {
        "schema_version": 1,
        "checkpoint": "CP6",
        "checkpoint_id": "CP6-STORY-CR999-S01",
        "profile": "standard-code",
        "story_id": "STORY-CR999-S01",
        "cr_id": "CR-999",
        "context_ref": "process/context/STORY-CR999-S01.json",
        "dispatch_refs": ["DISPATCH-CR999-S01"],
        "evidence_ref": "process/evidence/STORY-CR999-S01.json",
        "items": [
            {
                "id": "CP6-01",
                "name": "implementation",
                "status": "PASS",
                "severity": "BLOCKER",
                "evidence_refs": ["process/evidence/STORY-CR999-S01.json"],
            }
        ],
        "blockers": [],
        "waivers": [],
        "decision": "PASS",
        "event_id": "CP6-STORY-CR999-S01-RESULT-V1",
    }
    result_path = process / "checks" / "CP6-STORY-CR999-S01.result.json"
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
                "result_ref": "process/checks/CP6-STORY-CR999-S01.result.json",
                "story_id": "STORY-CR999-S01",
                "cr_id": "CR-999",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


class PublicOperationContractTests(unittest.TestCase):
    def test_registry_matches_inventory_and_all_six_l3_journeys(self) -> None:
        result = public_operations.validate_public_operations(
            PROJECT_ROOT,
            check_console=True,
        )

        self.assertEqual("PASS", result["decision"], result["errors"])
        self.assertEqual(3, result["schema_version"])
        self.assertEqual("PublicOperationRegistryCheckV3", result["kind"])
        self.assertEqual(30, result["documented_operation_count"])
        self.assertEqual([], result["undocumented_public_operations"])
        self.assertEqual([], result["unknown_registry_operations"])
        self.assertEqual(6, result["l3_journey_count"])
        self.assertTrue(all(item["discovered"] for item in result["console_results"]))
        self.assertEqual("package-source-declarations-v1", result["discovery"]["mode"])
        self.assertEqual(30, result["discovery"]["discovered_operation_count"])
        self.assertEqual("PASS", result["governed_cli_reverse_coverage"]["status"])
        self.assertEqual(1, result["governed_cli_reverse_coverage"]["entry_count"])
        self.assertEqual(
            [],
            result["governed_cli_reverse_coverage"]["missing_declaration_entries"],
        )
        self.assertEqual(
            [],
            result["governed_cli_reverse_coverage"]["missing_contract_entries"],
        )
        self.assertGreater(result["discovery"]["scanned_file_count"], 100)
        self.assertTrue(
            all(
                ref.startswith("meta_flow/")
                for ref in result["discovery"]["declaration_source_refs"]
            )
        )
        self.assertFalse(hasattr(public_operations, "PUBLIC_OPERATION_ENTRIES"))

    def test_package_declaration_discovery_is_open_world_without_checker_edits(self) -> None:
        source = json.loads(
            (PROJECT_ROOT / public_operations.DEFAULT_REGISTRY_REL).read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = root / "release"
            registry = release / public_operations.DEFAULT_REGISTRY_REL
            registry.parent.mkdir(parents=True)
            contract = json.loads(json.dumps(source["operations"][0]))
            contract["operation"] = "future.operation"
            contract["entry"] = ["meta-flow", "future", "operation"]
            contract["path_contract"]["logical_process_arguments"] = []
            registry.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "kind": "PublicOperationContractRegistryV2",
                        "operations": [contract],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            package = root / "source" / "meta_flow"
            package.mkdir(parents=True)
            (package / "future_owner.py").write_text(
                "PUBLIC_OPERATION_DECLARATIONS = "
                "((\"future.operation\", (\"meta-flow\", \"future\", \"operation\")),)\n",
                encoding="utf-8",
            )

            result = public_operations.validate_public_operations(
                release,
                check_console=False,
                declaration_root=package,
            )

        self.assertEqual("PASS", result["decision"], result["errors"])
        self.assertEqual(1, result["discovery"]["discovered_operation_count"])
        self.assertEqual(
            ["meta_flow/future_owner.py"],
            result["discovery"]["declaration_source_refs"],
        )

    def test_package_declaration_discovery_mutants_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "meta_flow"
            package.mkdir()
            owner = package / "owner.py"
            owner.write_text(
                "PUBLIC_OPERATION_DECLARATIONS = "
                "((\"future.operation\", (\"meta-flow\", \"future\")),)\n",
                encoding="utf-8",
            )
            duplicate = package / "duplicate.py"
            duplicate.write_text(owner.read_text(encoding="utf-8"), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate public operation declaration"):
                public_operations.discover_public_operation_declarations(package)

            duplicate.write_text(
                "PUBLIC_OPERATION_DECLARATIONS = "
                "((\"future.second\", (\"meta-flow\", \"future\")),)\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate public operation declaration entry"):
                public_operations.discover_public_operation_declarations(package)

            duplicate.unlink()
            owner.write_text(
                "PUBLIC_OPERATION_DECLARATIONS = build_at_runtime()\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "must be literal"):
                public_operations.discover_public_operation_declarations(package)

            owner.write_text("VALUE = 1\n", encoding="utf-8")
            symlink = package / "linked.py"
            symlink.symlink_to(owner.name)
            with self.assertRaisesRegex(ValueError, "contains symlink"):
                public_operations.discover_public_operation_declarations(package)

    def test_governed_cli_reverse_coverage_rejects_route_without_declaration(self) -> None:
        source = json.loads(
            (PROJECT_ROOT / public_operations.DEFAULT_REGISTRY_REL).read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry = root / public_operations.DEFAULT_REGISTRY_REL
            registry.parent.mkdir(parents=True)
            registry.write_text(
                json.dumps(source, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            package = root / "meta_flow"
            package.mkdir()
            (package / "owner.py").write_text(
                "PUBLIC_OPERATION_DECLARATIONS = "
                "((\"known.operation\", (\"meta-flow\", \"known\")),)\n",
                encoding="utf-8",
            )
            source["operations"] = [
                {
                    **source["operations"][0],
                    "operation": "known.operation",
                    "entry": ["meta-flow", "known"],
                }
            ]
            registry.write_text(
                json.dumps(source, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            result = public_operations.validate_public_operations(
                root,
                check_console=False,
                declaration_root=package,
                governed_cli_entries=(("meta-flow", "check", "missing"),),
            )

        self.assertEqual("FAIL", result["decision"])
        self.assertEqual(
            [["meta-flow", "check", "missing"]],
            result["governed_cli_reverse_coverage"]["missing_declaration_entries"],
        )
        self.assertEqual(
            [["meta-flow", "check", "missing"]],
            result["governed_cli_reverse_coverage"]["missing_contract_entries"],
        )

    def test_package_declaration_discovery_budget_fails_without_partial_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "meta_flow"
            package.mkdir()
            (package / "owner.py").write_text(
                "PUBLIC_OPERATION_DECLARATIONS = "
                "((\"future.operation\", (\"meta-flow\", \"future\")),)\n",
                encoding="utf-8",
            )
            original_files = public_operations.MAX_DECLARATION_SOURCE_FILES
            original_file_bytes = public_operations.MAX_DECLARATION_FILE_BYTES
            original_total_bytes = public_operations.MAX_DECLARATION_SOURCE_BYTES
            try:
                public_operations.MAX_DECLARATION_SOURCE_FILES = 0
                with self.assertRaisesRegex(ValueError, "file budget exceeded"):
                    public_operations.discover_public_operation_declarations(package)

                public_operations.MAX_DECLARATION_SOURCE_FILES = original_files
                public_operations.MAX_DECLARATION_FILE_BYTES = 0
                with self.assertRaisesRegex(ValueError, "source file budget exceeded"):
                    public_operations.discover_public_operation_declarations(package)

                public_operations.MAX_DECLARATION_FILE_BYTES = original_file_bytes
                public_operations.MAX_DECLARATION_SOURCE_BYTES = 0
                with self.assertRaisesRegex(ValueError, "source byte budget exceeded"):
                    public_operations.discover_public_operation_declarations(package)
            finally:
                public_operations.MAX_DECLARATION_SOURCE_FILES = original_files
                public_operations.MAX_DECLARATION_FILE_BYTES = original_file_bytes
                public_operations.MAX_DECLARATION_SOURCE_BYTES = original_total_bytes

    def test_registry_unknown_field_missing_operation_and_path_drift_fail_closed(
        self,
    ) -> None:
        source = json.loads(
            (PROJECT_ROOT / public_operations.DEFAULT_REGISTRY_REL).read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry = root / public_operations.DEFAULT_REGISTRY_REL
            registry.parent.mkdir(parents=True)
            unknown = json.loads(json.dumps(source))
            unknown["operations"][0]["unknown"] = True
            registry.write_text(
                json.dumps(unknown, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            invalid_shape = public_operations.validate_public_operations(
                root,
                check_console=False,
            )
            missing = json.loads(json.dumps(source))
            removed_operation = missing["operations"][0]["operation"]
            missing["operations"] = missing["operations"][1:]
            registry.write_text(
                json.dumps(missing, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            missing_operation = public_operations.validate_public_operations(
                root,
                check_console=False,
            )
            path_drift = json.loads(json.dumps(source))
            path_drift["operations"][-1]["path_contract"]["absolute_process_path_limit"] = 1
            registry.write_text(
                json.dumps(path_drift, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            invalid_path_contract = public_operations.validate_public_operations(
                root,
                check_console=False,
            )
            undiscoverable_argument = json.loads(json.dumps(source))
            undiscoverable_argument["operations"][-1]["path_contract"][
                "logical_process_arguments"
            ].append("--not-a-public-argument")
            registry.write_text(
                json.dumps(
                    undiscoverable_argument,
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            invalid_argument_contract = public_operations.validate_public_operations(
                root,
                check_console=True,
            )
            unknown_operation = json.loads(json.dumps(source))
            unknown_operation["operations"][-1]["operation"] = "future.unknown"
            registry.write_text(
                json.dumps(unknown_operation, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            unknown_registry_operation = public_operations.validate_public_operations(
                root,
                check_console=False,
            )

        self.assertEqual("FAIL", invalid_shape["decision"])
        self.assertIn("extra=['unknown']", invalid_shape["errors"][0])
        self.assertEqual("FAIL", missing_operation["decision"])
        self.assertEqual(
            [removed_operation],
            missing_operation["undocumented_public_operations"],
        )
        self.assertEqual("FAIL", invalid_path_contract["decision"])
        self.assertIn(
            "absolute_process_path_limit must be 0",
            invalid_path_contract["errors"][0],
        )
        self.assertEqual("FAIL", invalid_argument_contract["decision"])
        self.assertIn(
            "human-gate.check public entry does not expose declared logical "
            "process argument --not-a-public-argument",
            invalid_argument_contract["errors"],
        )
        self.assertEqual("FAIL", unknown_registry_operation["decision"])
        self.assertEqual(
            ["future.unknown"],
            unknown_registry_operation["unknown_registry_operations"],
        )

    def test_four_real_console_l3_journeys_and_failure_injections(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            bad_event = root / "bad-event.json"
            bad_event.write_text(
                json.dumps(
                    {
                        "event_id": "E-BAD",
                        "event_type": "subgate_passed",
                        "status": "passed",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            gate_ledger = root / "process" / "state" / "GATE-LEDGER.ndjson"
            event_result = subprocess.run(
                [
                    str(CONSOLE),
                    "event",
                    "append",
                    "--project-root",
                    str(root),
                    "--ledger",
                    "process/state/GATE-LEDGER.ndjson",
                    "--event-file",
                    str(bad_event),
                ],
                cwd=PROJECT_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(0, event_result.returncode)
            self.assertFalse(gate_ledger.exists())

            read_ledger = root / "process" / "state" / "READ-EXPANSION-LEDGER.ndjson"
            context_result = subprocess.run(
                [
                    str(CONSOLE),
                    "context",
                    "read-log",
                    "--project-root",
                    str(root),
                    "--path",
                    "process/STATE.md",
                    "--reason",
                    "not-a-policy-enum",
                    "--stage",
                    "CP6",
                    "--agent",
                    "meta-dev",
                    "--context-ref",
                    "process/context/fixture.json",
                ],
                cwd=PROJECT_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(2, context_result.returncode)
            self.assertIn("mutation_count: 0", context_result.stdout)
            self.assertFalse(read_ledger.exists())

            write_cp6_projection_fixture(root)
            plan_before = (root / "process" / "DEVELOPMENT-PLAN.yaml").read_bytes()
            story_result = subprocess.run(
                [
                    str(CONSOLE),
                    "story",
                    "project-cp6",
                    "--project-root",
                    str(root),
                    "--result",
                    "process/checks/CP6-STORY-CR999-S01.result.json",
                ],
                cwd=PROJECT_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            story_plan = json.loads(story_result.stdout)
            self.assertEqual(0, story_result.returncode, story_result.stderr)
            self.assertEqual("READY", story_plan["decision"])
            self.assertEqual(1, story_plan["mutation_count"])
            self.assertEqual(
                plan_before,
                (root / "process" / "DEVELOPMENT-PLAN.yaml").read_bytes(),
            )

            cr_result = subprocess.run(
                [
                    str(CONSOLE),
                    "cr",
                    "conflicts",
                    "--proposed",
                    "--id",
                    "CR-998",
                    "--conflict-key",
                    canonical_digest({"fixture": "public-operation"}),
                    "--project-root",
                    str(root),
                ],
                cwd=PROJECT_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            cr_preview = json.loads(cr_result.stdout)
            self.assertEqual(0, cr_result.returncode, cr_result.stderr)
            self.assertEqual("NO_CONFLICT", cr_preview["decision"])
            self.assertEqual(0, cr_preview["mutation_count"])
            self.assertFalse((root / "process" / "changes" / "CR-998.md").exists())

            cr_path = root / "process" / "changes" / "CR-997.md"
            cr_path.parent.mkdir(parents=True, exist_ok=True)
            cr_path.write_text(
                """---
schema_version: 1
kind: cr
cr_id: "CR-997"
cr_type: "process"
title: "public close dry-run"
lifecycle_status: "active"
readiness_status: "NOT_READY"
gate_status: "cp8_pending"
---

## 变更描述

验证公共 close/status-sync 均为零写 dry-run。
""",
                encoding="utf-8",
            )
            cr_before = cr_path.read_bytes()
            close_result = subprocess.run(
                [
                    str(CONSOLE),
                    "cr",
                    "close",
                    "--id",
                    "CR-997",
                    "--readiness",
                    "READY_WITH_RISK",
                    "--effective-at",
                    "2026-07-27T00:00:00+00:00",
                    "--project-root",
                    str(root),
                ],
                cwd=PROJECT_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            close_plan = json.loads(close_result.stdout)
            status_sync_result = subprocess.run(
                [
                    str(CONSOLE),
                    "cr",
                    "status-sync",
                    "--id",
                    "CR-997",
                    "--status",
                    "closed",
                    "--readiness",
                    "READY_WITH_RISK",
                    "--gate-status",
                    "cp8_closed",
                    "--effective-at",
                    "2026-07-27T00:00:00+00:00",
                    "--project-root",
                    str(root),
                ],
                cwd=PROJECT_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            status_sync_plan = json.loads(status_sync_result.stdout)
            self.assertEqual(0, close_result.returncode, close_result.stderr)
            self.assertEqual(
                0,
                status_sync_result.returncode,
                status_sync_result.stderr,
            )
            self.assertEqual(close_plan, status_sync_plan)
            self.assertEqual(0, close_plan["mutation_count"])
            self.assertEqual(cr_before, cr_path.read_bytes())

            registry_result = subprocess.run(
                [
                    str(CONSOLE),
                    "cr",
                    "public-operations-check",
                    "--project-root",
                    str(PROJECT_ROOT),
                ],
                cwd=PROJECT_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            registry_check = json.loads(registry_result.stdout)
            self.assertEqual(0, registry_result.returncode, registry_result.stderr)
            self.assertEqual("PASS", registry_check["decision"])


if __name__ == "__main__":
    unittest.main()
