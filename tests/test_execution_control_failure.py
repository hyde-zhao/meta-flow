from __future__ import annotations

import hashlib
import inspect
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from meta_flow.execution_control.contract import ExecutionUnitV1, canonical_digest
from meta_flow.execution_control.failure import (
    FailureAttemptV1,
    FrozenFailureContractV1,
    FrozenFailureEvidenceV1,
    FrozenFailureResultItemV1,
    plan_finding_observation,
)
from meta_flow.policies.failure_routing import classify_failure, route_slice_failure
from meta_flow.semantics.attempt import VALIDATION_LAYERS
from meta_flow.state.event_ledger import (
    FindingObservationEventV1,
    append_execution_control_event,
    execution_control_ledger_preimage,
    load_events,
    project_execution_control_ledger,
    project_finding_occurrence,
    validate_event_ledger,
)
from meta_flow.work.lifecycle import apply_execution_failure, plan_execution_failure
from meta_flow.work.model import build_work, load_work, write_work_create_only
from meta_flow.work.risk import RiskFacts, classify_work
from meta_flow.work.scope import WorkScope

SHA = "a" * 64
OID = "b" * 40
OBSERVED_AT = "2026-08-08T00:00:00Z"


def _paired_binding(tmp_path: Path) -> tuple[Path, Path]:
    release = tmp_path / "meta-flow"
    process = tmp_path / "meta-flow-process"
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


def _contract(
    *, root: str = "execution-control", slice_id: str = "S3"
) -> FrozenFailureContractV1:
    return FrozenFailureContractV1.build(
        root_concept=root,
        slice_id=slice_id,
        contract_revision=1,
        required_check_ids=("GROUP-001",),
    )


def _unit(
    work_id: str,
    *,
    root: str = "execution-control",
    slice_id: str = "S3",
    contract_digest: str = SHA,
) -> ExecutionUnitV1:
    return ExecutionUnitV1(
        unit_id=work_id,
        root_concept=root,
        slice_id=slice_id,
        container_role="primary",
        revision=1,
        supersedes_unit_id="",
        contract_ref="process/contracts/execution-control-v1.json",
        contract_digest=contract_digest,
    )


def _write_work(process: Path, work_id: str = "W-001") -> ExecutionUnitV1:
    contract = _contract()
    contract_path = process / "contracts" / "execution-control-v1.json"
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_bytes = (
        json.dumps(contract.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    contract_path.write_bytes(contract_bytes)
    unit = _unit(work_id, contract_digest=hashlib.sha256(contract_bytes).hexdigest())
    work = build_work(
        work_id=work_id,
        project_id="fixture-project",
        objective="验证 same-slice failure control",
        request_ref=f"works/{work_id}/REQUEST.md",
        scope=WorkScope(
            1,
            ("PROJECT.yaml",),
            (f"works/{work_id}/WORK.yaml",),
            ("pytest",),
        ),
        classification=classify_work(RiskFacts(change_kind="code", touched_path_count=1)),
        release_base_oid=OID,
        process_base_oid=OID,
        execution_unit=unit,
    )
    write_work_create_only(process, work)
    return unit


def _reason_for(kind: str) -> tuple[str, dict[str, object], str]:
    fixtures: dict[str, tuple[str, dict[str, object], str]] = {
        "harness": (
            "HARNESS_ERROR_WITH_UNCHANGED_SEMANTICS",
            {"check_harness_error": True, "semantic_digest_unchanged": True},
            "FAIL",
        ),
        "schema": (
            "DETERMINISTIC_REPAIR_PROVEN",
            {
                "deterministic_schema_repair": True,
                "repair_path_in_scope": True,
                "before_digest_matches": True,
            },
            "FAIL",
        ),
        "content": (
            "CONTENT_OR_CONTRACT_FAILURE",
            {"real_content_failure": True},
            "FAIL",
        ),
        "partial": (
            "PARTIAL_MUTATION_OBSERVED",
            {"partial_mutation": True},
            "FAIL",
        ),
        "unknown": (
            "FAILURE_CLASSIFICATION_INSUFFICIENT",
            {},
            "FAIL",
        ),
        "blocked": (
            "FAILURE_CLASSIFICATION_INSUFFICIENT",
            {},
            "BLOCKED",
        ),
        "pass": ("CHECK_PASSED", {}, "PASS"),
    }
    return fixtures[kind]


def _evidence(
    unit: ExecutionUnitV1,
    *,
    kind: str = "content",
    target_scope_digest: str = SHA,
) -> FrozenFailureEvidenceV1:
    reason, _facts, status = _reason_for(kind)
    item = FrozenFailureResultItemV1(
        item_id="CHECK-ITEM-001",
        check_group_id="GROUP-001",
        status=status,
        reason_codes=(reason,),
    )
    return FrozenFailureEvidenceV1.build(
        unit_id=unit.unit_id,
        check_profile_digest=unit.contract_digest,
        required_check_ids=("GROUP-001",),
        contract_revision=unit.revision,
        target_scope_digest=target_scope_digest,
        result_item=item,
        observed_at=OBSERVED_AT,
    )


def _write_evidence(
    process: Path,
    unit: ExecutionUnitV1,
    *,
    kind: str = "content",
    name: str = "failure-evidence.json",
) -> str:
    evidence = _evidence(
        unit,
        kind=kind,
        target_scope_digest=load_work(process, unit.unit_id).scope.digest,
    )
    path = process / "checks" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(evidence.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return f"process/checks/{name}"


def _attempt(
    work_id: str = "W-001",
    *,
    previous: int = 1,
    next_value: int = 2,
    source_changed: bool = False,
    command_changed: bool = False,
) -> FailureAttemptV1:
    return FailureAttemptV1(
        previous_work_id=work_id,
        next_work_id=work_id,
        previous_thread_id="THREAD-001",
        next_thread_id="THREAD-001",
        previous_attempt_id=f"ATTEMPT-{previous}",
        next_attempt_id=f"ATTEMPT-{next_value}",
        previous_dispatch_id=f"DISPATCH-{previous}",
        next_dispatch_id=f"DISPATCH-{next_value}",
        source_changed=source_changed,
        command_changed=command_changed,
    )


def test_public_lifecycle_api_exposes_ref_but_no_identity_or_occurrence_override() -> None:
    parameters = inspect.signature(plan_execution_failure).parameters
    assert "evidence_ref" in parameters
    assert not {
        "identity",
        "identity_digest",
        "occurrence",
        "root_cause_id",
        "finding_code",
        "canonical_finding_code",
    } & set(parameters)


@pytest.mark.parametrize(
    ("kind", "expected_action", "append_required"),
    [
        ("harness", "RETRY_CURRENT_LAYER", True),
        ("schema", "REWORK_CURRENT_SLICE", True),
        ("content", "REWORK_CURRENT_SLICE", True),
        ("partial", "RECOVER_PARTIAL_AND_STOP", True),
        ("unknown", "CLASSIFY_BEFORE_CONTINUE", True),
        ("blocked", "WAIT_IN_CONTAINER", True),
        ("pass", "COMPLETE_CURRENT_LAYER_ONLY", False),
    ],
)
def test_canonical_failure_composition_has_one_action(
    kind: str, expected_action: str, append_required: bool
) -> None:
    unit = _unit("W-001")
    evidence = _evidence(unit, kind=kind)
    _reason, facts, _status = _reason_for(kind)
    plan = plan_finding_observation(
        unit,
        _contract(),
        evidence,
        evidence_ref="process/checks/failure-evidence.json",
        facts=facts,
        failed_layer="targeted",
        attempt=_attempt(),
        ledger_preimage_digest=execution_control_ledger_preimage(Path("missing")),
    )
    assert plan.decision == "READY"
    assert plan.route is not None
    assert plan.route.execution_action == expected_action
    assert plan.append_required is append_required


def test_pass_evidence_cannot_hide_partial_failure_facts() -> None:
    unit = _unit("W-001")
    plan = plan_finding_observation(
        unit,
        _contract(),
        _evidence(unit, kind="pass"),
        evidence_ref="process/checks/pass-evidence.json",
        facts={"partial_mutation": True},
        failed_layer="targeted",
        attempt=_attempt(),
        ledger_preimage_digest="0" * 64,
    )

    assert plan.blocked
    assert plan.conflicts == ("FROZEN_PASS_FACTS_CONFLICT",)


def test_route_digests_equal_canonical_owner_outputs_and_drift_restarts_static() -> None:
    unit = _unit("W-001")
    facts = {"real_content_failure": True}
    attempt = _attempt(source_changed=True)
    plan = plan_finding_observation(
        unit,
        _contract(),
        _evidence(unit),
        evidence_ref="process/checks/failure-evidence.json",
        facts=facts,
        failed_layer="compatibility",
        attempt=attempt,
        ledger_preimage_digest="0" * 64,
    )
    classification = classify_failure(facts)
    slice_route = route_slice_failure(
        failure_class=classification.failure_class,
        failed_layer="compatibility",
        current_slice_id=unit.slice_id,
    )
    rework = attempt.plan(failed_layer="compatibility")
    rework_payload = {
        "decision": rework.decision,
        "reuse_work": rework.reuse_work,
        "reuse_thread": rework.reuse_thread,
        "new_attempt": rework.new_attempt,
        "new_dispatch": rework.new_dispatch,
        "create_worktree": rework.create_worktree,
        "restart_layer": rework.restart_layer,
        "layers": list(rework.layers),
        "reason_codes": list(rework.reason_codes),
    }

    assert plan.route is not None
    assert plan.route.classification_digest == canonical_digest(classification.as_dict())
    assert plan.route.slice_route_digest == canonical_digest(slice_route.as_dict())
    assert plan.route.attempt_plan_digest == canonical_digest(rework_payload)
    assert (rework.restart_layer, rework.layers) == ("static", VALIDATION_LAYERS)


def test_identity_does_not_use_work_thread_message_or_attempt_names() -> None:
    first_unit = _unit("W-001")
    second_unit = _unit("W-002")
    first = plan_finding_observation(
        first_unit,
        _contract(),
        _evidence(first_unit),
        evidence_ref="process/checks/one.json",
        facts={"real_content_failure": True},
        failed_layer="targeted",
        attempt=_attempt("W-001"),
        ledger_preimage_digest="0" * 64,
    )
    changed_names = replace(
        _attempt("W-002"),
        previous_thread_id="THREAD-OTHER",
        next_thread_id="THREAD-OTHER",
        previous_attempt_id="ATTEMPT-OTHER-1",
        next_attempt_id="ATTEMPT-OTHER-2",
        previous_dispatch_id="DISPATCH-OTHER-1",
        next_dispatch_id="DISPATCH-OTHER-2",
    )
    second = plan_finding_observation(
        second_unit,
        _contract(),
        _evidence(second_unit),
        evidence_ref="process/checks/two.json",
        facts={"real_content_failure": True},
        failed_layer="targeted",
        attempt=changed_names,
        ledger_preimage_digest="0" * 64,
    )
    assert first.identity_digest == second.identity_digest


def test_apply_projects_occurrence_one_two_three_and_replay_is_idempotent(
    tmp_path: Path,
) -> None:
    release, process = _paired_binding(tmp_path)
    unit = _write_work(process)
    evidence_ref = _write_evidence(process, unit)
    common_dir = process / ".git"

    first_plan = plan_execution_failure(
        release,
        work_id="W-001",
        evidence_ref=evidence_ref,
        facts={"real_content_failure": True},
        failed_layer="targeted",
        attempt=_attempt(previous=1, next_value=2),
    )
    first = apply_execution_failure(
        release,
        common_dir,
        first_plan,
        work_id="W-001",
        evidence_ref=evidence_ref,
        facts={"real_content_failure": True},
        failed_layer="targeted",
        attempt=_attempt(previous=1, next_value=2),
        owner_token="owner-1",
        owner_process_identity="pytest-1",
    )
    assert (first.decision, first.occurrence, first.domain_mutation_count) == ("PASS", 1, 1)
    assert first.coordination_mutation_count == 2

    replay_plan = plan_execution_failure(
        release,
        work_id="W-001",
        evidence_ref=evidence_ref,
        facts={"real_content_failure": True},
        failed_layer="targeted",
        attempt=_attempt(previous=1, next_value=2),
    )
    replay = apply_execution_failure(
        release,
        common_dir,
        replay_plan,
        work_id="W-001",
        evidence_ref=evidence_ref,
        facts={"real_content_failure": True},
        failed_layer="targeted",
        attempt=_attempt(previous=1, next_value=2),
        owner_token="owner-replay",
        owner_process_identity="pytest-replay",
    )
    assert (replay.decision, replay.occurrence, replay.domain_mutation_count) == ("PASS", 1, 0)
    assert replay.idempotent is True

    for previous, next_value, expected_action in (
        (2, 3, "REWORK_CURRENT_SLICE"),
        (3, 4, "REQUIRE_DESIGN_CLARIFICATION"),
        (4, 5, "REQUIRE_DESIGN_CLARIFICATION"),
    ):
        attempt = _attempt(previous=previous, next_value=next_value)
        plan = plan_execution_failure(
            release,
            work_id="W-001",
            evidence_ref=evidence_ref,
            facts={"real_content_failure": True},
            failed_layer="targeted",
            attempt=attempt,
        )
        result = apply_execution_failure(
            release,
            common_dir,
            plan,
            work_id="W-001",
            evidence_ref=evidence_ref,
            facts={"real_content_failure": True},
            failed_layer="targeted",
            attempt=attempt,
            owner_token=f"owner-{next_value}",
            owner_process_identity=f"pytest-{next_value}",
        )
        assert result.decision == "PASS"
        assert result.occurrence == next_value - 1
        assert result.route is not None
        assert result.route.execution_action == expected_action

    ledger = process / "state" / "EXECUTION-CONTROL-LEDGER.ndjson"
    events, errors = load_events(ledger)
    assert errors == []
    projection = project_finding_occurrence(
        events, identity_digest=first_plan.identity_digest
    )
    assert (projection.decision, projection.occurrence) == ("PASS", 4)
    assert len(list((process / "works").iterdir())) == 1


def test_pass_apply_rechecks_fresh_inputs_before_zero_domain_result(tmp_path: Path) -> None:
    release, process = _paired_binding(tmp_path)
    unit = _write_work(process)
    evidence_ref = _write_evidence(process, unit, kind="pass")
    evidence_path = process / "checks" / "failure-evidence.json"
    common_dir = process / ".git"
    planned = plan_execution_failure(
        release,
        work_id="W-001",
        evidence_ref=evidence_ref,
        facts={},
        failed_layer="targeted",
        attempt=_attempt(),
    )
    assert planned.decision == "READY"
    assert planned.append_required is False

    evidence_path.unlink()
    result = apply_execution_failure(
        release,
        common_dir,
        planned,
        work_id="W-001",
        evidence_ref=evidence_ref,
        facts={},
        failed_layer="targeted",
        attempt=_attempt(),
        owner_token="owner-pass-drift",
        owner_process_identity="pytest-pass-drift",
    )

    assert result.decision == "BLOCKED"
    assert result.domain_mutation_count == 0
    assert result.coordination_mutation_count == 2
    assert not (process / "state" / "EXECUTION-CONTROL-LEDGER.ndjson").exists()
    assert not (common_dir / "meta-flow" / "execution-control" / "admission.lock").exists()


def test_pass_apply_with_fresh_inputs_uses_cas_and_writes_no_domain_event(
    tmp_path: Path,
) -> None:
    release, process = _paired_binding(tmp_path)
    unit = _write_work(process)
    evidence_ref = _write_evidence(process, unit, kind="pass")
    common_dir = process / ".git"
    planned = plan_execution_failure(
        release,
        work_id="W-001",
        evidence_ref=evidence_ref,
        facts={},
        failed_layer="targeted",
        attempt=_attempt(),
    )
    result = apply_execution_failure(
        release,
        common_dir,
        planned,
        work_id="W-001",
        evidence_ref=evidence_ref,
        facts={},
        failed_layer="targeted",
        attempt=_attempt(),
        owner_token="owner-pass",
        owner_process_identity="pytest-pass",
    )

    assert (result.decision, result.domain_mutation_count) == ("PASS", 0)
    assert result.coordination_mutation_count == 2
    assert result.idempotent is True
    assert not (process / "state" / "EXECUTION-CONTROL-LEDGER.ndjson").exists()


def test_same_observation_key_with_changed_payload_fails_before_append(tmp_path: Path) -> None:
    release, process = _paired_binding(tmp_path)
    unit = _write_work(process)
    evidence_ref = _write_evidence(process, unit)
    common_dir = process / ".git"
    attempt = _attempt()
    planned = plan_execution_failure(
        release,
        work_id="W-001",
        evidence_ref=evidence_ref,
        facts={"real_content_failure": True},
        failed_layer="targeted",
        attempt=attempt,
    )
    first = apply_execution_failure(
        release,
        common_dir,
        planned,
        work_id="W-001",
        evidence_ref=evidence_ref,
        facts={"real_content_failure": True},
        failed_layer="targeted",
        attempt=attempt,
        owner_token="owner-first",
        owner_process_identity="pytest-first",
    )
    assert first.decision == "PASS"
    ledger = process / "state" / "EXECUTION-CONTROL-LEDGER.ndjson"
    before = ledger.read_bytes()

    changed_attempt = replace(attempt, source_changed=True)
    changed = plan_execution_failure(
        release,
        work_id="W-001",
        evidence_ref=evidence_ref,
        facts={"real_content_failure": True},
        failed_layer="targeted",
        attempt=changed_attempt,
    )
    result = apply_execution_failure(
        release,
        common_dir,
        changed,
        work_id="W-001",
        evidence_ref=evidence_ref,
        facts={"real_content_failure": True},
        failed_layer="targeted",
        attempt=changed_attempt,
        owner_token="owner-changed",
        owner_process_identity="pytest-changed",
    )
    assert result.decision == "BLOCKED"
    assert result.domain_mutation_count == 0
    assert "EXECUTION_CONTROL_OBSERVATION_REPLAY_MISMATCH" in result.conflicts
    assert ledger.read_bytes() == before


def test_append_preimage_drift_is_zero_write(tmp_path: Path) -> None:
    unit = _unit("W-001")
    plan = plan_finding_observation(
        unit,
        _contract(),
        _evidence(unit),
        evidence_ref="process/checks/failure-evidence.json",
        facts={"real_content_failure": True},
        failed_layer="targeted",
        attempt=_attempt(),
        ledger_preimage_digest=hashlib.sha256(b"").hexdigest(),
    )
    assert plan.event is not None
    ledger = tmp_path / "EXECUTION-CONTROL-LEDGER.ndjson"

    result = append_execution_control_event(
        ledger,
        plan.event,
        expected_preimage_digest="f" * 64,
    )

    assert result.decision == "BLOCKED"
    assert result.conflicts == ("EXECUTION_CONTROL_LEDGER_PREIMAGE_DRIFT",)
    assert result.domain_mutation_count == 0
    assert not ledger.exists()


def test_missing_tampered_ambiguous_and_invalid_layer_are_zero_write(tmp_path: Path) -> None:
    release, process = _paired_binding(tmp_path)
    unit = _write_work(process)
    evidence_ref = _write_evidence(process, unit)
    evidence_path = process / "checks" / "failure-evidence.json"
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    payload["payload_digest"] = "f" * 64
    evidence_path.write_text(json.dumps(payload), encoding="utf-8")

    tampered = plan_execution_failure(
        release,
        work_id="W-001",
        evidence_ref=evidence_ref,
        facts={"real_content_failure": True},
        failed_layer="targeted",
        attempt=_attempt(),
    )
    missing = plan_execution_failure(
        release,
        work_id="W-001",
        evidence_ref="process/checks/missing.json",
        facts={"real_content_failure": True},
        failed_layer="targeted",
        attempt=_attempt(),
    )
    assert tampered.blocked and missing.blocked

    clean = _evidence(unit).as_dict()
    clean["result_items"] = [*clean["result_items"], clean["result_items"][0]]
    seed = {key: value for key, value in clean.items() if key != "payload_digest"}
    clean["payload_digest"] = canonical_digest(seed)
    evidence_path.write_text(json.dumps(clean), encoding="utf-8")
    ambiguous = plan_execution_failure(
        release,
        work_id="W-001",
        evidence_ref=evidence_ref,
        facts={"real_content_failure": True},
        failed_layer="targeted",
        attempt=_attempt(),
    )
    assert ambiguous.blocked

    valid_ref = _write_evidence(process, unit, name="valid.json")
    invalid_layer = plan_execution_failure(
        release,
        work_id="W-001",
        evidence_ref=valid_ref,
        facts={"real_content_failure": True},
        failed_layer="unknown-layer",
        attempt=_attempt(),
    )
    assert invalid_layer.blocked
    assert not (process / "state" / "EXECUTION-CONTROL-LEDGER.ndjson").exists()


def test_frozen_result_status_rejects_non_routable_canonical_terminal() -> None:
    with pytest.raises(ValueError, match="status is not routable"):
        FrozenFailureResultItemV1(
            item_id="CHECK-ITEM-001",
            check_group_id="GROUP-001",
            status="WAIVED",
            reason_codes=("CHECK_WAIVED",),
        )


def test_missing_process_route_is_structured_zero_write_block() -> None:
    project_root = Path("missing-release-root")
    plan = plan_execution_failure(
        project_root,
        work_id="W-001",
        evidence_ref="process/checks/failure-evidence.json",
        facts={"real_content_failure": True},
        failed_layer="targeted",
        attempt=_attempt(),
    )

    assert plan.blocked
    assert plan.conflicts == ("FROZEN_FAILURE_EVIDENCE_OR_ROUTE_INVALID",)
    assert plan.expected_ledger_preimage_digest == hashlib.sha256(b"").hexdigest()


def test_recomputed_contract_digest_cannot_override_execution_unit_binding(tmp_path: Path) -> None:
    release, process = _paired_binding(tmp_path)
    unit = _write_work(process)
    evidence_ref = _write_evidence(process, unit)
    contract_path = process / "contracts" / "execution-control-v1.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["required_check_ids"] = ["GROUP-RENAMED"]
    contract_seed = {key: value for key, value in contract.items() if key != "payload_digest"}
    contract["payload_digest"] = canonical_digest(contract_seed)
    contract_path.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    plan = plan_execution_failure(
        release,
        work_id="W-001",
        evidence_ref=evidence_ref,
        facts={"real_content_failure": True},
        failed_layer="targeted",
        attempt=_attempt(),
    )

    assert plan.blocked
    assert plan.conflicts == ("EXECUTION_CONTRACT_DIGEST_MISMATCH",)
    assert not (process / "state" / "EXECUTION-CONTROL-LEDGER.ndjson").exists()


def test_recomputed_evidence_cannot_rename_frozen_required_check(tmp_path: Path) -> None:
    release, process = _paired_binding(tmp_path)
    unit = _write_work(process)
    evidence_ref = _write_evidence(process, unit)
    evidence_path = process / "checks" / "failure-evidence.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["required_check_ids"] = ["GROUP-RENAMED"]
    evidence["result_items"][0]["check_group_id"] = "GROUP-RENAMED"
    evidence["check_result_digest"] = canonical_digest(evidence["result_items"][0])
    evidence_seed = {key: value for key, value in evidence.items() if key != "payload_digest"}
    evidence["payload_digest"] = canonical_digest(evidence_seed)
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    plan = plan_execution_failure(
        release,
        work_id="W-001",
        evidence_ref=evidence_ref,
        facts={"real_content_failure": True},
        failed_layer="targeted",
        attempt=_attempt(),
    )

    assert plan.blocked
    assert plan.conflicts == ("FROZEN_CONTRACT_OR_EVIDENCE_BINDING_MISMATCH",)
    assert not (process / "state" / "EXECUTION-CONTROL-LEDGER.ndjson").exists()


def test_recomputed_evidence_cannot_change_work_scope_identity(tmp_path: Path) -> None:
    release, process = _paired_binding(tmp_path)
    unit = _write_work(process)
    evidence_ref = _write_evidence(process, unit)
    evidence_path = process / "checks" / "failure-evidence.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["target_scope_digest"] = "c" * 64
    evidence_seed = {key: value for key, value in evidence.items() if key != "payload_digest"}
    evidence["payload_digest"] = canonical_digest(evidence_seed)
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    plan = plan_execution_failure(
        release,
        work_id="W-001",
        evidence_ref=evidence_ref,
        facts={"real_content_failure": True},
        failed_layer="targeted",
        attempt=_attempt(),
    )

    assert plan.blocked
    assert plan.conflicts == ("FROZEN_TARGET_SCOPE_DIGEST_MISMATCH",)
    assert not (process / "state" / "EXECUTION-CONTROL-LEDGER.ndjson").exists()


def test_concurrent_apply_has_exactly_one_domain_append(tmp_path: Path) -> None:
    release, process = _paired_binding(tmp_path)
    unit = _write_work(process)
    evidence_ref = _write_evidence(process, unit)
    common_dir = process / ".git"
    attempt = _attempt()
    plan = plan_execution_failure(
        release,
        work_id="W-001",
        evidence_ref=evidence_ref,
        facts={"real_content_failure": True},
        failed_layer="targeted",
        attempt=attempt,
    )

    def apply(index: int):
        return apply_execution_failure(
            release,
            common_dir,
            plan,
            work_id="W-001",
            evidence_ref=evidence_ref,
            facts={"real_content_failure": True},
            failed_layer="targeted",
            attempt=attempt,
            owner_token=f"owner-{index}",
            owner_process_identity=f"pytest-{index}",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(apply, (1, 2)))
    assert sum(result.domain_mutation_count for result in results) == 1
    assert sum(result.decision == "PASS" for result in results) == 1
    assert not (common_dir / "meta-flow" / "execution-control" / "admission.lock").exists()


def test_event_projector_rejects_extra_fields_and_duplicate_observation_key(tmp_path: Path) -> None:
    unit = _unit("W-001")
    evidence = _evidence(unit)
    plan = plan_finding_observation(
        unit,
        _contract(),
        evidence,
        evidence_ref="process/checks/failure-evidence.json",
        facts={"real_content_failure": True},
        failed_layer="targeted",
        attempt=_attempt(),
        ledger_preimage_digest="0" * 64,
    )
    assert plan.event is not None
    payload = plan.event.as_dict()
    with pytest.raises(ValueError, match="fields mismatch"):
        FindingObservationEventV1.from_mapping({**payload, "extra": True})
    projection = project_finding_occurrence(
        [payload, payload], identity_digest=plan.identity_digest
    )
    assert projection.decision == "BLOCKED"
    assert "EXECUTION_CONTROL_OBSERVATION_KEY_DUPLICATE" in projection.finding_codes

    ledger = tmp_path / "EXECUTION-CONTROL-LEDGER.ndjson"
    ledger.write_text(json.dumps({**payload, "extra": True}) + "\n", encoding="utf-8")
    errors, _warnings = validate_event_ledger(ledger, ledger_type="execution-control")
    assert any("invalid execution-control event" in error for error in errors)


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("unit_id", "W-OTHER"),
        ("attempt_id", "ATTEMPT-OTHER"),
        ("check_result_digest", "f" * 64),
        ("identity_digest", "f" * 64),
    ],
)
def test_event_rejects_re_signed_observation_key_constituent_drift(
    field: str,
    changed: str,
) -> None:
    unit = _unit("W-001")
    plan = plan_finding_observation(
        unit,
        _contract(),
        _evidence(unit),
        evidence_ref="process/checks/failure-evidence.json",
        facts={"real_content_failure": True},
        failed_layer="targeted",
        attempt=_attempt(),
        ledger_preimage_digest="0" * 64,
    )
    assert plan.event is not None
    payload = {**plan.event.as_dict(), field: changed}
    seed = {key: value for key, value in payload.items() if key != "payload_digest"}
    payload["payload_digest"] = canonical_digest(seed)

    with pytest.raises(ValueError, match="key is not canonically derived"):
        FindingObservationEventV1.from_mapping(payload)
    projection = project_execution_control_ledger([payload])
    assert projection.decision == "BLOCKED"
    assert projection.finding_codes == ("EXECUTION_CONTROL_EVENT_INVALID",)


def test_event_rejects_re_signed_forged_key_and_event_id() -> None:
    unit = _unit("W-001")
    plan = plan_finding_observation(
        unit,
        _contract(),
        _evidence(unit),
        evidence_ref="process/checks/failure-evidence.json",
        facts={"real_content_failure": True},
        failed_layer="targeted",
        attempt=_attempt(),
        ledger_preimage_digest="0" * 64,
    )
    assert plan.event is not None
    payload = plan.event.as_dict()
    payload["observation_key_digest"] = "f" * 64
    payload["event_id"] = f"EC-OBS-{'f' * 32}"
    seed = {key: value for key, value in payload.items() if key != "payload_digest"}
    payload["payload_digest"] = canonical_digest(seed)
    with pytest.raises(ValueError, match="key is not canonically derived"):
        FindingObservationEventV1.from_mapping(payload)

    event_id_only = plan.event.as_dict()
    event_id_only["event_id"] = "EC-OBS-FORGED"
    seed = {key: value for key, value in event_id_only.items() if key != "payload_digest"}
    event_id_only["payload_digest"] = canonical_digest(seed)
    with pytest.raises(ValueError, match="event_id is not canonically derived"):
        FindingObservationEventV1.from_mapping(event_id_only)


def test_projected_identity_and_observation_key_lookup_are_precomputed() -> None:
    unit = _unit("W-001")
    plan = plan_finding_observation(
        unit,
        _contract(),
        _evidence(unit),
        evidence_ref="process/checks/failure-evidence.json",
        facts={"real_content_failure": True},
        failed_layer="targeted",
        attempt=_attempt(),
        ledger_preimage_digest="0" * 64,
    )
    assert plan.event is not None
    index = project_execution_control_ledger([plan.event.as_dict()])

    assert index.by_identity[plan.identity_digest].occurrence == 1
    assert index.by_observation_key[plan.event.observation_key_digest] == plan.event
    assert project_finding_occurrence(index, identity_digest=plan.identity_digest).occurrence == 1


def test_failure_module_imports_canonical_owners_without_failure_class_literal_family() -> None:
    import meta_flow.execution_control.failure as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "from meta_flow.policies.failure_routing import (" in source
    assert "classify_failure" in source
    assert "route_slice_failure" in source
    assert "from meta_flow.semantics.attempt import ReworkPlan, plan_rework" in source
    for copied_failure_class in (
        "CHECK_HARNESS_ERROR",
        "DETERMINISTIC_SCHEMA_REPAIR",
        "REAL_CONTENT_FAILURE",
        "PARTIAL_MUTATION",
    ):
        assert copied_failure_class not in source
