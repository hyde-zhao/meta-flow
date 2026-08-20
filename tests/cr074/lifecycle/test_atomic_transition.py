from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from test_work_lifecycle_transaction import (
    _close_phase_work,
    _enable_state_projection,
    _git,
    _governance_fixture,
    make_work,
)

from meta_flow.project.governance_projection import GOVERNANCE_PROJECTION_REL
from meta_flow.project.scale import dump_yaml
from meta_flow.state import current as state_current
from meta_flow.work.lifecycle_transaction import (
    SharedProjectionRepairAuthorizationV1,
    apply_shared_projection_repair,
    inspect_shared_projection_repair,
    inspect_work_close_transactions,
    plan_shared_projection_repair,
)
from meta_flow.work.model import load_work
from meta_flow.work.scope import WorkScope
from meta_flow.work.status_transition import (
    WorkStatusTransitionAuthorizationV2,
    apply_work_status_transition,
    inspect_work_status_transitions,
    plan_work_status_transition,
    recover_work_status_transition,
)
from meta_flow.work.store import apply_work_init, plan_work_init_from_release_root


def _authorization(plan) -> WorkStatusTransitionAuthorizationV2:
    return WorkStatusTransitionAuthorizationV2(
        authorization_id=f"cr074-status-{plan.plan_digest[:24]}",
        work_id=plan.parent_plan.work_id,
        plan_digest=plan.plan_digest,
        parent_plan_digest=plan.parent_plan.plan_digest,
        target_refs=plan.target_refs,
        expires_at=(datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
    )


def _plan_with_alias_child(
    process: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    change = process / "changes/NOTE-074.md"
    change.parent.mkdir(exist_ok=True)
    change.write_text("# CR-074\n", encoding="utf-8")
    original = state_current.plan_current_projection_targets

    def plan_with_change(project_root: Path, *, current_entry=None, future_existing_refs=()):
        entry = dict(current_entry or state_current.build_current_entry(project_root))
        entry["change_ref"] = "process/changes/NOTE-074.md"
        return original(
            project_root,
            current_entry=entry,
            future_existing_refs=future_existing_refs,
        )

    monkeypatch.setattr(state_current, "plan_current_projection_targets", plan_with_change)
    plan = plan_work_status_transition(
        process,
        "W-001",
        expected_status="planned",
        new_status="active",
    )
    assert plan.current_projection_plan.targets, plan.parent_plan.blockers
    return plan


def test_status_transition_plan_is_zero_write_and_apply_matches_exact_targets(
    tmp_path: Path,
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    _enable_state_projection(release, process)
    work = make_work(process, "W-001", phase.phase_ref)
    apply_work_init(plan_work_init_from_release_root(release, work))
    work_path = process / work.work_ref
    before = work_path.read_bytes()

    first = plan_work_status_transition(
        process,
        "W-001",
        expected_status="planned",
        new_status="active",
    )
    second = plan_work_status_transition(
        process,
        "W-001",
        expected_status="planned",
        new_status="active",
    )

    assert first.ready
    assert first.as_dict() == second.as_dict()
    assert work_path.read_bytes() == before
    assert first.target_refs[0] == "works/W-001/WORK.yaml"
    assert set(first.target_refs) <= {
        "works/W-001/WORK.yaml",
        "state/STATE.current.json",
        "STATE.md",
        "current/CURRENT.json",
        "process/.gitignore",
        *(f"process/current/{name}.ref" for name in state_current.CURRENT_ALIAS_NAMES),
        *(f"process/current/{name}" for name in state_current.CURRENT_ALIAS_NAMES),
    }

    receipt = apply_work_status_transition(process, first, _authorization(first))

    assert receipt.decision == "PASS"
    assert set(receipt.planned_refs) == set(receipt.actual_mutation_refs)
    assert not receipt.recovery_required
    assert inspect_work_close_transactions(process)["decision"] == "PASS"
    errors, warnings = state_current.check_current_state(release, mode="enforce")
    assert errors == []
    assert warnings == []
    manifest = json.loads(
        (
            process
            / ".meta-flow-runtime/work-close/transactions"
            / _authorization(first).authorization_id
            / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert manifest["operation"] == "work.status-transition"
    assert manifest["operation_admission_digest"] == first.admission.admission_digest
    assert manifest["mutation_plan_digest"] == first.mutation_plan.plan_digest
    manifest["operation_admission_digest"] = "invalid"
    manifest_path = (
        process
        / ".meta-flow-runtime/work-close/transactions"
        / _authorization(first).authorization_id
        / "manifest.json"
    )
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    tampered_report = inspect_work_close_transactions(process)
    assert tampered_report["decision"] == "BLOCKED"
    assert any("coordinator binding" in error for error in tampered_report["errors"])


def test_status_transition_preimage_drift_blocks_before_domain_write(
    tmp_path: Path,
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    _enable_state_projection(release, process)
    work = make_work(process, "W-001", phase.phase_ref)
    apply_work_init(plan_work_init_from_release_root(release, work))
    plan = plan_work_status_transition(
        process,
        "W-001",
        expected_status="planned",
        new_status="active",
    )
    work_path = process / work.work_ref
    work_path.write_bytes(work_path.read_bytes() + b"\n")
    protected = {
        ref: (process / ref).read_bytes()
        for ref in ("state/STATE.current.json", "STATE.md", "current/CURRENT.json")
    }

    receipt = apply_work_status_transition(process, plan, _authorization(plan))

    assert receipt.decision == "BLOCKED"
    assert receipt.actual_mutation_refs == ()
    assert {
        ref: (process / ref).read_bytes()
        for ref in ("state/STATE.current.json", "STATE.md", "current/CURRENT.json")
    } == protected
    assert not (
        process
        / ".meta-flow-runtime/work-close/transactions"
        / _authorization(plan).authorization_id
    ).exists()


@pytest.mark.parametrize("drift", ("scope", "oid", "provider", "writer-inventory"))
def test_status_transition_frozen_admission_drift_is_typed_zero_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    _enable_state_projection(release, process)
    work = make_work(process, "W-001", phase.phase_ref)
    apply_work_init(plan_work_init_from_release_root(release, work))
    plan = plan_work_status_transition(
        process,
        "W-001",
        expected_status="planned",
        new_status="active",
    )
    import meta_flow.work.status_transition as status_owner

    if drift == "scope":
        current_work = load_work(process, "W-001")
        changed_scope = WorkScope(
            current_work.scope.version,
            (*current_work.scope.allowed_reads, "docs/scope-drift.md"),
            current_work.scope.allowed_writes,
            current_work.scope.required_checks,
        )
        (process / current_work.work_ref).write_text(
            dump_yaml(replace(current_work, scope=changed_scope).as_dict()) + "\n",
            encoding="utf-8",
        )
    elif drift == "oid":
        _git(process, "add", "-A")
        _git(process, "commit", "-m", "status admission oid drift")
    elif drift == "provider":
        monkeypatch.setattr(status_owner, "provider_source_identity_digest", lambda *_: "f" * 64)
    else:
        original_inventory = status_owner._status_writer_inventory

        def changed_inventory(current_work, refs):
            _inventory, namespace = original_inventory(current_work, refs)
            return "e" * 64, namespace

        monkeypatch.setattr(status_owner, "_status_writer_inventory", changed_inventory)

    protected = {
        ref: (process / ref).read_bytes()
        for ref in plan.target_refs
        if (process / ref).is_file() and not (process / ref).is_symlink()
    }
    authorization = replace(
        _authorization(plan),
        authorization_id=f"cr074-status-drift-{drift}",
    )

    receipt = apply_work_status_transition(process, plan, authorization)

    assert receipt.decision == "BLOCKED"
    assert receipt.actual_mutation_refs == ()
    assert receipt.as_dict()["mutation_count"] == 0
    assert {ref: (process / ref).read_bytes() for ref in protected} == protected
    assert not (
        process
        / ".meta-flow-runtime/work-close/transactions"
        / authorization.authorization_id
    ).exists()


def test_pointer_inventory_reads_alias_lexically_without_following_target(
    tmp_path: Path,
) -> None:
    state_current.write_current_state(
        tmp_path,
        state_current.default_current_state(tmp_path),
    )

    plan = state_current.plan_current_projection_targets(tmp_path)

    assert plan.targets == ()
    alias = tmp_path / "process/current/state"
    assert alias.is_symlink()
    assert alias.readlink().as_posix() == "../state/STATE.current.json"
    assert (tmp_path / "process/state/STATE.current.json").is_file()


def test_current_projection_hard_interrupt_is_inspectable_and_recoverable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_current.write_current_state(
        tmp_path,
        state_current.default_current_state(tmp_path),
    )
    change = tmp_path / "process/changes/CR-001.md"
    change.parent.mkdir(parents=True)
    change.write_text("# CR-001\n", encoding="utf-8")
    entry = state_current.build_current_entry(tmp_path)
    entry["change_ref"] = "process/changes/CR-001.md"
    plan = state_current.plan_current_projection_targets(
        tmp_path,
        current_entry=entry,
    )
    original_write = state_current._write_projection_image
    calls = 0

    def interrupt_second(path: Path, kind: str, value) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt
        original_write(path, kind, value)

    monkeypatch.setattr(state_current, "_write_projection_image", interrupt_second)
    with pytest.raises(KeyboardInterrupt):
        state_current.apply_current_projection_targets(
            tmp_path,
            plan,
            parent_plan_digest="a" * 64,
            authorization_id="AUTH-CR074-INTERRUPT",
        )

    inspection = state_current.inspect_current_projection_transactions(tmp_path)
    assert inspection["decision"] == "BLOCKED"
    transaction_id = next(
        item["transaction_id"]
        for item in inspection["transactions"]
        if item["authorization_id"] == "AUTH-CR074-INTERRUPT"
    )
    monkeypatch.setattr(state_current, "_write_projection_image", original_write)
    recovery = state_current.recover_current_projection_targets(
        tmp_path,
        transaction_id,
    )

    assert recovery["decision"] == "RECOVERED"
    assert state_current.inspect_current_projection_transactions(tmp_path)["decision"] == "PASS"
    assert not (tmp_path / "process/current/change.ref").exists()


def test_status_plan_tamper_and_same_authorization_replay_are_zero_write(
    tmp_path: Path,
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    _enable_state_projection(release, process)
    work = make_work(process, "W-001", phase.phase_ref)
    apply_work_init(plan_work_init_from_release_root(release, work))
    plan = plan_work_status_transition(
        process,
        "W-001",
        expected_status="planned",
        new_status="active",
    )
    target = plan.parent_plan.targets[0]
    tampered_parent = replace(
        plan.parent_plan,
        targets=(
            replace(target, after_bytes=target.after_bytes + b"tamper"),
            *plan.parent_plan.targets[1:],
        ),
    )
    tampered = replace(plan, parent_plan=tampered_parent)
    before = {ref: (process / ref).read_bytes() for ref in ("state/STATE.current.json", "STATE.md")}

    with pytest.raises(ValueError, match="parent plan integrity"):
        apply_work_status_transition(process, tampered, _authorization(plan))
    assert {ref: (process / ref).read_bytes() for ref in before} == before
    assert not (
        process
        / ".meta-flow-runtime/work-close/transactions"
        / _authorization(plan).authorization_id
    ).exists()

    authorization = _authorization(plan)
    assert (
        WorkStatusTransitionAuthorizationV2.from_mapping(authorization.as_dict()) == authorization
    )
    assert apply_work_status_transition(process, plan, authorization).decision == "PASS"
    committed = {
        ref: (process / ref).read_bytes() for ref in ("state/STATE.current.json", "STATE.md")
    }
    with pytest.raises(ValueError, match="already consumed"):
        apply_work_status_transition(process, plan, authorization)
    assert {ref: (process / ref).read_bytes() for ref in committed} == committed


@pytest.mark.parametrize(
    "window",
    ("child_replace_accounting", "child_committed_before_parent", "parent_applying"),
)
def test_status_transition_interrupt_windows_recover_parent_then_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    window: str,
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    _enable_state_projection(release, process)
    work = make_work(process, "W-001", phase.phase_ref)
    apply_work_init(plan_work_init_from_release_root(release, work))
    plan = _plan_with_alias_child(process, monkeypatch)
    authorization = _authorization(plan)
    original_child_write = state_current._write_projection_image
    original_parent_manifest_write = __import__(
        "meta_flow.work.lifecycle_transaction", fromlist=["_write_json_atomic"]
    )._write_json_atomic
    original_parent_replace = __import__(
        "meta_flow.work.lifecycle_transaction", fromlist=["_replace_bytes"]
    )._replace_bytes

    if window == "child_replace_accounting":
        fired = False

        def interrupt_after_child_replace(path: Path, kind: str, value) -> None:
            nonlocal fired
            original_child_write(path, kind, value)
            if not fired:
                fired = True
                raise KeyboardInterrupt

        monkeypatch.setattr(
            state_current,
            "_write_projection_image",
            interrupt_after_child_replace,
        )
    elif window == "child_committed_before_parent":

        def interrupt_parent_applying(path: Path, payload) -> None:
            if (
                path.name == "manifest.json"
                and path.parent.name == authorization.authorization_id
                and payload.get("state") == "APPLYING"
            ):
                raise KeyboardInterrupt
            original_parent_manifest_write(path, payload)

        monkeypatch.setattr(
            "meta_flow.work.lifecycle_transaction._write_json_atomic",
            interrupt_parent_applying,
        )
    else:
        fired = False

        def interrupt_after_parent_replace(path: Path, content: bytes) -> None:
            nonlocal fired
            original_parent_replace(path, content)
            if not fired:
                fired = True
                raise KeyboardInterrupt

        monkeypatch.setattr(
            "meta_flow.work.lifecycle_transaction._replace_bytes",
            interrupt_after_parent_replace,
        )

    with pytest.raises(KeyboardInterrupt):
        apply_work_status_transition(process, plan, authorization)
    assert inspect_work_status_transitions(process)["decision"] == "BLOCKED"

    monkeypatch.setattr(state_current, "_write_projection_image", original_child_write)
    monkeypatch.setattr(
        "meta_flow.work.lifecycle_transaction._write_json_atomic",
        original_parent_manifest_write,
    )
    monkeypatch.setattr(
        "meta_flow.work.lifecycle_transaction._replace_bytes",
        original_parent_replace,
    )
    recovery = recover_work_status_transition(process, authorization.authorization_id)

    assert recovery.decision == "RECOVERED"
    assert inspect_work_status_transitions(process)["decision"] == "PASS"
    assert not (process / "current/change.ref").exists()


def test_status_transition_child_oserror_after_commit_returns_typed_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    _enable_state_projection(release, process)
    work = make_work(process, "W-001", phase.phase_ref)
    apply_work_init(plan_work_init_from_release_root(release, work))
    plan = _plan_with_alias_child(process, monkeypatch)
    authorization = replace(
        _authorization(plan),
        authorization_id="cr074-status-child-oserror",
    )
    from meta_flow.work import transaction_child

    original = transaction_child.apply_current

    def commit_then_raise(*args, **kwargs):
        result = original(*args, **kwargs)
        assert result["decision"] == "PASS"
        raise OSError("injected child API failure after commit")

    monkeypatch.setattr(transaction_child, "apply_current", commit_then_raise)

    receipt = apply_work_status_transition(process, plan, authorization)

    assert receipt.decision == "RECOVERED"
    assert receipt.actual_mutation_refs
    assert receipt.as_dict()["mutation_count"] > 0
    manifest = json.loads(
        (
            process
            / ".meta-flow-runtime/work-close/transactions"
            / authorization.authorization_id
            / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert manifest["state"] == "RECOVERED"
    assert inspect_work_status_transitions(process)["decision"] == "PASS"


def test_committed_parent_forbids_child_rollback_and_recovered_history_is_superseded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    _enable_state_projection(release, process)
    work = make_work(process, "W-001", phase.phase_ref)
    apply_work_init(plan_work_init_from_release_root(release, work))
    plan = _plan_with_alias_child(process, monkeypatch)
    authorization = _authorization(plan)
    receipt = apply_work_status_transition(process, plan, authorization)
    assert receipt.decision == "PASS"
    child = state_current.current_projection_transaction_for_parent(
        release,
        authorization_id=authorization.authorization_id,
        parent_plan_digest=plan.parent_plan.plan_digest,
    )
    assert child is not None
    with pytest.raises(ValueError, match="committed parent"):
        state_current.recover_current_projection_targets(release, child["transaction_id"])
    (
        release / state_current.CURRENT_PROJECTION_RUNTIME_REL / f"{child['transaction_id']}.json"
    ).unlink()
    report = inspect_work_status_transitions(process)
    assert report["decision"] == "BLOCKED"
    assert any("committed child is missing" in error for error in report["errors"])
    with pytest.raises(ValueError, match="child is missing"):
        recover_work_status_transition(process, authorization.authorization_id)


def test_recovered_child_is_superseded_by_fresh_authorization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    _enable_state_projection(release, process)
    work = make_work(process, "W-001", phase.phase_ref)
    apply_work_init(plan_work_init_from_release_root(release, work))
    first = _plan_with_alias_child(process, monkeypatch)
    original_replace = __import__(
        "meta_flow.work.lifecycle_transaction", fromlist=["_replace_bytes"]
    )._replace_bytes

    def fail_parent(*_args, **_kwargs) -> None:
        raise OSError("injected parent failure")

    monkeypatch.setattr("meta_flow.work.lifecycle_transaction._replace_bytes", fail_parent)
    assert (
        apply_work_status_transition(process, first, _authorization(first)).decision == "RECOVERED"
    )
    monkeypatch.setattr(
        "meta_flow.work.lifecycle_transaction._replace_bytes",
        original_replace,
    )
    retry = plan_work_status_transition(
        process,
        "W-001",
        expected_status="planned",
        new_status="active",
    )
    retry_authorization = replace(
        _authorization(retry),
        authorization_id="cr074-status-retry",
    )

    assert apply_work_status_transition(process, retry, retry_authorization).decision == "PASS"
    report = state_current.inspect_current_projection_transactions(release)

    assert report["decision"] == "PASS", report["findings"]
    assert any(
        item["classification"] == "SUPERSEDED"
        and item["authorization_id"] == _authorization(first).authorization_id
        for item in report["transactions"]
    )


def test_shared_projection_repair_only_appends_successor_receipt(
    tmp_path: Path,
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    _close_phase_work(release, process, phase, "W-001")
    project_path = process / "PROJECT.yaml"
    project_path.write_bytes(project_path.read_bytes() + b"\n")
    formal_before = {
        ref: (process / ref).read_bytes()
        for ref in ("PROJECT.yaml", phase.phase_ref, GOVERNANCE_PROJECTION_REL.as_posix())
    }
    plan = plan_shared_projection_repair(process)
    assert plan.classification == "COMMITTED_STALE_REPAIRABLE"
    assert type(plan).from_mapping(plan.as_dict()) == plan
    authorization = SharedProjectionRepairAuthorizationV1(
        "CR074-R1",
        plan.plan_digest,
        tuple(target.ref for target in plan.targets),
        (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
    )
    assert (
        SharedProjectionRepairAuthorizationV1.from_mapping(authorization.as_dict()) == authorization
    )

    receipt = apply_shared_projection_repair(process, plan, authorization)

    assert receipt.decision == "PASS"
    assert receipt.mutation_count == 1
    assert inspect_shared_projection_repair(process)["classification"] == "COMMITTED_CURRENT"
    assert (
        inspect_shared_projection_repair(
            process,
            expected_plan_digest=plan.plan_digest,
        )["classification"]
        == "SUPERSEDED"
    )
    assert {ref: (process / ref).read_bytes() for ref in formal_before} == formal_before
    with pytest.raises(ValueError, match="already consumed"):
        apply_shared_projection_repair(process, plan, authorization)


def test_shared_projection_repair_rejects_partial_and_corrupted_lineage(
    tmp_path: Path,
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    _close_phase_work(release, process, phase, "W-001")
    manifest_path = process / ".meta-flow-runtime/work-close/transactions/close-w-001/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["state"] = "PARTIAL"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")

    partial = plan_shared_projection_repair(process)
    assert partial.classification == "PARTIAL"
    blocked_authorization = SharedProjectionRepairAuthorizationV1(
        "CR074-R-PARTIAL",
        partial.plan_digest,
        tuple(target.ref for target in partial.targets),
        (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
    )
    with pytest.raises(ValueError, match="binding mismatch"):
        blocked_authorization.validate_for(partial)

    manifest["unexpected"] = True
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    assert plan_shared_projection_repair(process).classification == "CORRUPTED"


def test_shared_projection_repair_post_inspect_fault_keeps_mutation_accounting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    _close_phase_work(release, process, phase, "W-001")
    project_path = process / "PROJECT.yaml"
    project_path.write_bytes(project_path.read_bytes() + b"\n")
    formal_before = {
        ref: (process / ref).read_bytes()
        for ref in ("PROJECT.yaml", phase.phase_ref, GOVERNANCE_PROJECTION_REL.as_posix())
        if (process / ref).is_file()
    }
    plan = plan_shared_projection_repair(process)
    authorization = SharedProjectionRepairAuthorizationV1(
        "CR074-R-POST-FAULT",
        plan.plan_digest,
        tuple(target.ref for target in plan.targets),
        (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
    )
    lifecycle = __import__("meta_flow.work.lifecycle_transaction", fromlist=["x"])
    original_record = lifecycle.record_shared_projection_successor
    original_plan = lifecycle.plan_shared_projection_repair
    committed = False

    def record_then_mark(*args, **kwargs):
        nonlocal committed
        successor_id = original_record(*args, **kwargs)
        committed = True
        return successor_id

    def fail_only_post_inspect(*args, **kwargs):
        if committed:
            raise RuntimeError("injected post-inspect failure")
        return original_plan(*args, **kwargs)

    monkeypatch.setattr(lifecycle, "record_shared_projection_successor", record_then_mark)
    monkeypatch.setattr(lifecycle, "plan_shared_projection_repair", fail_only_post_inspect)
    receipt = apply_shared_projection_repair(process, plan, authorization)

    assert receipt.decision == "PARTIAL"
    assert receipt.mutation_count == 1
    assert receipt.successor_id
    monkeypatch.setattr(lifecycle, "plan_shared_projection_repair", original_plan)
    assert inspect_shared_projection_repair(process)["classification"] == "COMMITTED_CURRENT"
    assert {ref: (process / ref).read_bytes() for ref in formal_before} == formal_before


def test_shared_projection_repair_oid_drift_blocks_with_zero_write(tmp_path: Path) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    _close_phase_work(release, process, phase, "W-001")
    project_path = process / "PROJECT.yaml"
    project_path.write_bytes(project_path.read_bytes() + b"\n")
    plan = plan_shared_projection_repair(process)
    assert plan.classification == "COMMITTED_STALE_REPAIRABLE"
    authorization = SharedProjectionRepairAuthorizationV1(
        "CR074-R-OID-DRIFT",
        plan.plan_digest,
        tuple(target.ref for target in plan.targets),
        (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
    )
    formal_before = {
        ref: (process / ref).read_bytes()
        for ref in ("PROJECT.yaml", phase.phase_ref, GOVERNANCE_PROJECTION_REL.as_posix())
    }
    successor_root = process / ".meta-flow-runtime/work-close/successors"
    successor_before = {
        path.name: path.read_bytes() for path in successor_root.glob("*.json") if path.is_file()
    }
    _git(process, "add", "-A")
    _git(process, "commit", "-m", "process oid drift after repair plan")

    receipt = apply_shared_projection_repair(process, plan, authorization)

    assert receipt.decision == "BLOCKED"
    assert receipt.mutation_count == 0
    assert receipt.post_classification == "SUPERSEDED"
    assert {ref: (process / ref).read_bytes() for ref in formal_before} == formal_before
    assert {
        path.name: path.read_bytes() for path in successor_root.glob("*.json") if path.is_file()
    } == successor_before


def test_coordinator_fields_are_forbidden_on_non_status_manifest(
    tmp_path: Path,
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    _close_phase_work(release, process, phase, "W-001")
    manifest_path = process / ".meta-flow-runtime/work-close/transactions/close-w-001/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        {
            "coordinator_plan_digest": "a" * 64,
            "current_projection_plan_digest": "b" * 64,
            "current_projection_transaction_id": "c" * 32,
            "handoff_plan_digest": "d" * 64,
            "handoff_transaction_id": "e" * 32,
            "handoff_route_policy_digest": "f" * 64,
            "handoff_desired_digest": "0" * 64,
        }
    )
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")

    report = inspect_work_close_transactions(process)

    assert report["decision"] == "BLOCKED"
    assert any("non-status manifest" in error for error in report["errors"])
