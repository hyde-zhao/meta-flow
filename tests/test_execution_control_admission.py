from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import meta_flow.execution_control.admission as admission_module
from meta_flow.execution_control.admission import (
    AdmissionLockHandleV1,
    acquire_admission_lock,
    audit_execution_budget,
    evaluate_execution_budget,
    execution_inventory_digest,
    inspect_admission_lock,
    load_self_budget_receipt,
    plan_admission,
    plan_lock_recovery,
    release_admission_lock,
    validate_admission_preimage,
)
from meta_flow.execution_control.contract import (
    AdmissionFactsV1,
    ContainerBudgetV1,
    ExecutionUnitV1,
)
from meta_flow.work.cli import _execution_unit
from meta_flow.work.model import build_work, validate_work_payload, work_from_payload
from meta_flow.work.risk import RiskFacts, classify_work
from meta_flow.work.scope import WorkScope

SHA = "a" * 64
OID = "b" * 40


def _unit(
    unit_id: str,
    *,
    role: str = "primary",
    revision: int = 1,
    supersedes: str = "",
    root: str = "execution-control",
    slice_id: str = "S2",
) -> ExecutionUnitV1:
    return ExecutionUnitV1(
        unit_id=unit_id,
        root_concept=root,
        slice_id=slice_id,
        container_role=role,
        revision=revision,
        supersedes_unit_id=supersedes,
        contract_ref="process/contracts/execution-control-v1.json",
        contract_digest=SHA,
    )


def _facts(inventory: tuple[ExecutionUnitV1, ...] = ()) -> AdmissionFactsV1:
    return AdmissionFactsV1(
        release_oid=OID,
        process_oid=OID,
        dirty_path_digest=SHA,
        scope_digest=SHA,
        authorization_digest=SHA,
        profile_digest=SHA,
        inventory_digest=execution_inventory_digest(inventory),
        target_preimage_digest=SHA,
        project_active_owner_digest=SHA,
    )


def _work(unit: ExecutionUnitV1 | None):
    return build_work(
        work_id="W-001",
        project_id="demo",
        objective="验证 typed admission",
        request_ref="works/W-001/REQUEST.md",
        scope=WorkScope(1, ("PROJECT.yaml",), ("works/W-001/WORK.yaml",), ("pytest",)),
        classification=classify_work(RiskFacts(change_kind="code", touched_path_count=1)),
        release_base_oid=OID,
        process_base_oid=OID,
        execution_unit=unit,
    )


def test_work_wire_adds_optional_closed_execution_unit_without_rewriting_history() -> None:
    legacy = _work(None).as_dict()
    assert "execution_unit" not in legacy
    assert work_from_payload(legacy).execution_unit is None

    unit = _unit("W-001")
    typed = _work(unit).as_dict()
    assert typed["execution_unit"] == unit.as_dict()
    assert work_from_payload(typed).execution_unit == unit
    assert validate_work_payload(typed) == []

    typed["execution_unit"] = {**unit.as_dict(), "unknown": True}
    assert "execution_unit" in {finding.code for finding in validate_work_payload(typed)}

    formal_cr = _work(unit).as_dict()
    formal_cr["kind"] = "cr"
    # A0-KIND-CR-EXECUTION-UNIT-ADR-V1：CR 是合法 execution envelope，
    # scope-amend 的真实 successor Work 已依赖该组合，不能由旧测试反向禁止。
    assert validate_work_payload(formal_cr) == []
    assert work_from_payload(formal_cr).execution_unit == unit


@pytest.mark.parametrize("kind", ["work", "cr"])
def test_work_validator_and_admission_share_execution_envelope_kind_domain(
    kind: str,
) -> None:
    unit = _unit("W-001")
    payload = _work(unit).as_dict()
    payload["kind"] = kind

    assert validate_work_payload(payload) == []
    assert work_from_payload(payload).execution_unit == unit
    assert plan_admission(
        unit,
        (),
        ContainerBudgetV1.policy_v1(),
        _facts(),
    ).decision == "READY"


def test_cli_requires_complete_identity_contract_and_has_no_policy_override() -> None:
    parsed = SimpleNamespace(
        work_id="W-001",
        execution_unit_id="W-001",
        execution_root_concept="execution-control",
        execution_slice_id="S2",
        execution_container_role="primary",
        execution_revision=1,
        execution_supersedes_unit_id="",
        execution_contract_ref="process/contracts/execution-control-v1.json",
        execution_contract_digest=SHA,
    )
    assert _execution_unit(parsed) == _unit("W-001")
    with pytest.raises(ValueError, match="missing=contract_digest"):
        _execution_unit(SimpleNamespace(**{**vars(parsed), "execution_contract_digest": None}))
    with pytest.raises(ValueError, match="unit_id must equal work_id"):
        _execution_unit(SimpleNamespace(**{**vars(parsed), "execution_unit_id": "W-OTHER"}))

    source = Path(admission_module.__file__).parents[1] / "work" / "cli.py"
    cli_source = source.read_text(encoding="utf-8")
    for forbidden in ("--activation-mode", "--container-budget", "--occurrence"):
        assert forbidden not in cli_source


def test_plan_is_pure_and_uses_one_budget_evaluator_for_all_conflicts() -> None:
    candidate = _unit("W-NEW")
    ready = plan_admission(
        candidate,
        (),
        ContainerBudgetV1.policy_v1(),
        _facts(),
    )
    assert ready.decision == "READY"
    assert ready.planned_domain_mutation_count == 0
    assert ready.coordination_required

    existing = (_unit("W-EXISTING"),)
    duplicate = plan_admission(
        candidate,
        existing,
        ContainerBudgetV1.policy_v1(),
        _facts(existing),
    )
    assert duplicate.blocked
    assert "DUPLICATE_ACTIVE_SLICE_OWNER" in duplicate.conflicts
    assert "CONTAINER_BUDGET_EXCEEDED" in duplicate.conflicts
    assert not duplicate.coordination_required

    for role in ("auxiliary", "repair"):
        blocked = plan_admission(
            _unit(f"W-{role}", role=role),
            (),
            ContainerBudgetV1.policy_v1(),
            _facts(),
        )
        expected = {"CONTAINER_BUDGET_EXCEEDED"}
        if role == "repair":
            expected.add("REPAIR_AUTHORIZATION_REQUIRED")
        assert set(blocked.conflicts) == expected

    concurrent = plan_admission(
        candidate,
        (),
        ContainerBudgetV1.policy_v1(),
        _facts(),
        active_concurrent_writer_count=1,
    )
    assert concurrent.conflicts == ("CONCURRENT_WRITE_BUDGET_EXCEEDED",)


def test_plan_binds_inventory_and_requires_terminal_supersession_evidence() -> None:
    candidate = _unit("W-V2", revision=2, supersedes="W-V1")
    drifted = replace(_facts(), inventory_digest="c" * 64)
    blocked = plan_admission(
        candidate,
        (),
        ContainerBudgetV1.policy_v1(),
        drifted,
    )
    assert {
        "ADMISSION_PREIMAGE_DRIFT",
        "SUPERSESSION_PREDECESSOR_NOT_TERMINAL",
    } <= set(blocked.conflicts)

    predecessor = _unit("W-V1")
    ready = plan_admission(
        candidate,
        (),
        ContainerBudgetV1.policy_v1(),
        _facts(),
        terminal_predecessors=(predecessor,),
    )
    assert ready.decision == "READY"


def test_lock_is_create_only_owner_bound_and_fresh_cas_is_zero_domain_write(
    tmp_path: Path,
) -> None:
    candidate = _unit("W-NEW")
    facts = _facts()
    plan = plan_admission(candidate, (), ContainerBudgetV1.policy_v1(), facts)

    acquired = acquire_admission_lock(
        tmp_path,
        plan,
        owner_token="owner-token",
        owner_process_identity="pid:1:instance:test",
    )
    assert acquired.decision == "PASS"
    assert acquired.coordination_mutation_count == 1
    assert acquired.durable_lock_count == 1
    assert acquired.handle is not None
    assert inspect_admission_lock(tmp_path).state == "HELD"
    assert acquired.handle.metadata.policy_revision == 1
    assert "owner-token" not in acquired.handle.lock_path.read_text(encoding="utf-8")

    contention = acquire_admission_lock(
        tmp_path,
        plan,
        owner_token="other-token",
        owner_process_identity="pid:2:instance:test",
    )
    assert contention.decision == "BLOCKED"
    assert contention.coordination_mutation_count == 0

    reservation = validate_admission_preimage(
        plan,
        acquired.handle,
        tmp_path,
        candidate,
        (),
        ContainerBudgetV1.policy_v1(),
        facts,
    )
    assert reservation.decision == "READY"
    assert reservation.domain_mutation_count == 0
    assert reservation.coordination_mutation_count == 0

    wrong_handle = replace(acquired.handle, owner_token="wrong-token")
    wrong_release = release_admission_lock(tmp_path, wrong_handle)
    assert wrong_release.decision == "BLOCKED"
    assert inspect_admission_lock(tmp_path).state == "HELD"

    released = release_admission_lock(tmp_path, acquired.handle)
    assert released.decision == "PASS"
    assert released.coordination_mutation_count == 1
    assert released.durable_lock_count == 0
    assert inspect_admission_lock(tmp_path).state == "ABSENT"


def test_inspection_cannot_reconstruct_owner_capability_or_release_lock(tmp_path: Path) -> None:
    plan = plan_admission(
        _unit("W-NEW"),
        (),
        ContainerBudgetV1.policy_v1(),
        _facts(),
    )
    acquired = acquire_admission_lock(
        tmp_path,
        plan,
        owner_token="unpublished-secret",
        owner_process_identity="pid:1:instance:test",
    )
    assert acquired.handle is not None
    inspection = inspect_admission_lock(tmp_path)
    assert inspection.metadata is not None
    forged = AdmissionLockHandleV1(
        inspection.lock_path,
        inspection.metadata,
        inspection.preimage_digest,
        "token-derived-only-from-inspection",
    )

    assert release_admission_lock(tmp_path, forged).decision == "BLOCKED"
    assert inspection.lock_path.is_file()
    assert release_admission_lock(tmp_path, acquired.handle).decision == "PASS"


def test_concurrent_lock_acquire_allows_exactly_one_owner(tmp_path: Path) -> None:
    plan = plan_admission(
        _unit("W-NEW"),
        (),
        ContainerBudgetV1.policy_v1(),
        _facts(),
    )

    def acquire(index: int):
        return acquire_admission_lock(
            tmp_path,
            plan,
            owner_token=f"owner-{index}",
            owner_process_identity=f"pid:{index}:instance:test",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(acquire, (1, 2)))
    assert sorted(result.decision for result in results) == ["BLOCKED", "PASS"]
    assert sum(result.coordination_mutation_count for result in results) == 1
    winner = next(result for result in results if result.handle is not None)
    assert release_admission_lock(tmp_path, winner.handle).decision == "PASS"


@pytest.mark.parametrize(
    "field",
    [
        "release_oid",
        "process_oid",
        "dirty_path_digest",
        "scope_digest",
        "authorization_digest",
        "profile_digest",
        "inventory_digest",
        "target_preimage_digest",
        "project_active_owner_digest",
    ],
)
def test_lock_held_fresh_facts_drift_blocks_before_domain_writer(
    tmp_path: Path,
    field: str,
) -> None:
    candidate = _unit("W-NEW")
    facts = _facts()
    plan = plan_admission(candidate, (), ContainerBudgetV1.policy_v1(), facts)
    acquired = acquire_admission_lock(
        tmp_path,
        plan,
        owner_token="owner-token",
        owner_process_identity="pid:1:instance:test",
    )
    assert acquired.handle is not None
    changed = "c" * (40 if field in {"release_oid", "process_oid"} else 64)
    drifted = replace(facts, **{field: changed})

    reservation = validate_admission_preimage(
        plan,
        acquired.handle,
        tmp_path,
        candidate,
        (),
        ContainerBudgetV1.policy_v1(),
        drifted,
    )
    assert reservation.decision == "BLOCKED"
    assert "ADMISSION_PREIMAGE_DRIFT" in reservation.conflicts
    assert reservation.domain_mutation_count == 0
    assert release_admission_lock(tmp_path, acquired.handle).decision == "PASS"


def test_lock_held_policy_drift_is_bound_even_when_both_plans_are_ready(
    tmp_path: Path,
) -> None:
    candidate = _unit("W-NEW")
    facts = _facts()
    policy = ContainerBudgetV1.policy_v1()
    plan = plan_admission(candidate, (), policy, facts)
    acquired = acquire_admission_lock(
        tmp_path,
        plan,
        owner_token="owner-token",
        owner_process_identity="pid:1:instance:test",
    )
    assert acquired.handle is not None
    relaxed_policy = ContainerBudgetV1(2, 0, 0, 2)
    relaxed = plan_admission(candidate, (), relaxed_policy, facts)
    assert relaxed.decision == "READY"
    assert relaxed != plan

    reservation = validate_admission_preimage(
        plan,
        acquired.handle,
        tmp_path,
        candidate,
        (),
        relaxed_policy,
        facts,
    )
    assert reservation.decision == "BLOCKED"
    assert "ADMISSION_PREIMAGE_DRIFT" in reservation.conflicts
    assert release_admission_lock(tmp_path, acquired.handle).decision == "PASS"


def test_stale_lock_recovery_is_read_only_and_requires_dead_owner_exact_authorization(
    tmp_path: Path,
) -> None:
    candidate = _unit("W-NEW")
    plan = plan_admission(candidate, (), ContainerBudgetV1.policy_v1(), _facts())
    acquired = acquire_admission_lock(
        tmp_path,
        plan,
        owner_token="owner-token",
        owner_process_identity="pid:1:instance:test",
    )
    assert acquired.handle is not None
    inspection = inspect_admission_lock(tmp_path)

    live = plan_lock_recovery(
        inspection,
        owner_liveness="live",
        expected_preimage_digest=inspection.preimage_digest,
        authorization_digest=SHA,
        expected_authorization_digest=SHA,
    )
    assert live.decision == "BLOCKED"
    assert inspection.lock_path.is_file()

    ready = plan_lock_recovery(
        inspection,
        owner_liveness="dead",
        expected_preimage_digest=inspection.preimage_digest,
        authorization_digest=SHA,
        expected_authorization_digest=SHA,
    )
    assert ready.decision == "READY"
    assert ready.planned_domain_mutation_count == 0
    assert ready.planned_coordination_mutation_count == 0
    assert inspection.lock_path.is_file()
    assert release_admission_lock(tmp_path, acquired.handle).decision == "PASS"


def test_cleanup_failure_is_partial_mutation_and_preserves_durable_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _unit("W-NEW")
    plan = plan_admission(candidate, (), ContainerBudgetV1.policy_v1(), _facts())
    acquired = acquire_admission_lock(
        tmp_path,
        plan,
        owner_token="owner-token",
        owner_process_identity="pid:1:instance:test",
    )
    assert acquired.handle is not None
    original_unlink = Path.unlink

    def fail_lock_unlink(path: Path, *args: object, **kwargs: object) -> None:
        if path == acquired.handle.lock_path:
            raise OSError("injected cleanup failure")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_lock_unlink)
    failed = release_admission_lock(tmp_path, acquired.handle)
    assert failed.decision == "PARTIAL_MUTATION"
    assert failed.durable_lock_count == 1
    assert acquired.handle.lock_path.is_file()


def test_kernel_self_budget_reuses_canonical_evaluator_and_binds_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = (_unit("CR-069", slice_id="CR-069"),)
    facts = _facts(baseline)
    receipt = audit_execution_budget(
        baseline,
        facts,
        concurrent_writer_count=1,
        child_work_count=0,
        source_fingerprint=SHA,
        profile_fingerprint=SHA,
        command_identity=SHA,
    )
    assert receipt.decision == "SELF_BUDGET_PASS"
    assert dict(receipt.role_counts) == {"primary": 1, "auxiliary": 0, "repair": 0}
    assert receipt.as_dict()["receipt_digest"] == receipt.receipt_digest
    assert receipt.as_dict()["domain_mutation_count"] == 0
    assert receipt.as_dict()["coordination_mutation_count"] == 0
    assert receipt.as_dict()["command_identity"] == SHA
    assert receipt.as_dict()["result_digest"] == receipt.result_digest
    receipt_path = tmp_path / "self-budget.json"
    receipt_path.write_text(json.dumps(receipt.as_dict()), encoding="utf-8")
    assert load_self_budget_receipt(receipt_path) == receipt

    for field, value in (
        ("policy_digest", "b" * 64),
        ("evaluator_digest", "b" * 64),
        ("result_digest", "b" * 64),
        ("receipt_digest", "b" * 64),
        ("domain_mutation_count", 1),
    ):
        with pytest.raises(ValueError):
            admission_module.SelfBudgetReceiptV1.from_mapping(
                {**receipt.as_dict(), field: value}
            )
    with pytest.raises(ValueError, match="fields mismatch"):
        admission_module.SelfBudgetReceiptV1.from_mapping(
            {**receipt.as_dict(), "unknown": True}
        )
    for nested_roles in (
        {"primary": 1, "auxiliary": 0},
        {"primary": 1, "auxiliary": 0, "repair": 0, "observer": 0},
        {1: 1, "primary": 1, "auxiliary": 0, "repair": 0},
    ):
        with pytest.raises(ValueError, match="exact canonical roles"):
            admission_module.SelfBudgetReceiptV1.from_mapping(
                {**receipt.as_dict(), "role_counts": nested_roles}
            )

    mutants = [
        (
            baseline + (_unit("CR-069-SECOND", slice_id="CR-069"),),
            1,
            "DUPLICATE_ACTIVE_SLICE_OWNER",
        ),
        (
            baseline + (_unit("CR-069-AUX", role="auxiliary", slice_id="CR-069"),),
            1,
            "CONTAINER_BUDGET_EXCEEDED",
        ),
        (
            baseline + (_unit("CR-069-REPAIR", role="repair", slice_id="CR-069"),),
            1,
            "CONTAINER_BUDGET_EXCEEDED",
        ),
        (baseline, 2, "CONCURRENT_WRITE_BUDGET_EXCEEDED"),
    ]
    for inventory, writers, expected in mutants:
        blocked = audit_execution_budget(
            inventory,
            _facts(inventory),
            concurrent_writer_count=writers,
            child_work_count=0,
            source_fingerprint=SHA,
            profile_fingerprint=SHA,
            command_identity=SHA,
        )
        assert blocked.decision == "BLOCKED"
        assert expected in blocked.conflicts

    monkeypatch.setattr(admission_module, "evaluate_execution_budget", lambda *args: None)
    with pytest.raises(ValueError, match="evaluator identity drift"):
        audit_execution_budget(
            baseline,
            facts,
            concurrent_writer_count=1,
            child_work_count=0,
            source_fingerprint=SHA,
            profile_fingerprint=SHA,
            command_identity=SHA,
        )


def test_budget_evaluator_is_order_independent_and_rejects_invalid_counts() -> None:
    units = (
        _unit("W-A", root="root-a", slice_id="slice-a"),
        _unit("W-B", root="root-b", slice_id="slice-b"),
    )
    first = evaluate_execution_budget(
        units,
        ContainerBudgetV1.policy_v1(),
        concurrent_writer_count=1,
    )
    second = evaluate_execution_budget(
        reversed(units),
        ContainerBudgetV1.policy_v1(),
        concurrent_writer_count=1,
    )
    assert first == second
    with pytest.raises(ValueError, match="non-negative integer"):
        evaluate_execution_budget(
            units,
            ContainerBudgetV1.policy_v1(),
            concurrent_writer_count=-1,
        )


def test_repair_slot_is_scoped_to_exact_root_and_slice() -> None:
    authorized = _unit(
        "W-REPAIR-A",
        role="repair",
        root="root-a",
        slice_id="slice-a",
    )
    unrelated = _unit(
        "W-REPAIR-B",
        role="repair",
        root="root-b",
        slice_id="slice-b",
    )

    exact = evaluate_execution_budget(
        (authorized,),
        ContainerBudgetV1.policy_v1(),
        concurrent_writer_count=1,
        authorized_repair_slices=(("root-a", "slice-a"),),
    )
    leaked = evaluate_execution_budget(
        (authorized, unrelated),
        ContainerBudgetV1.policy_v1(),
        concurrent_writer_count=1,
        authorized_repair_slices=(("root-a", "slice-a"),),
    )

    assert exact.decision == "READY"
    assert leaked.conflicts == ("CONTAINER_BUDGET_EXCEEDED",)
