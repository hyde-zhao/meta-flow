"""CR-078 S1 回归：scope-amend 共享投影 successor receipt 全链。

覆盖 blocked→amend→resume→close 全链、无 close head 不写 receipt、
连续 amend receipt 链、存量楔死 plan 期零写阻断、record 失败 PARTIAL、
G1 lane 新守卫、foreign ref receipt fail-closed、G2 current CR lane。
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest
from test_work_lifecycle_transaction import (
    _enable_state_projection,
    _governance_fixture,
    make_work,
)

from meta_flow.execution_control.contract import canonical_digest
from meta_flow.work import scope_amend as scope_amend_module
from meta_flow.work.budget import BudgetLimit
from meta_flow.work.lifecycle_transaction import (
    AUTHORIZATION_KIND as WORK_CLOSE_AUTHORIZATION_KIND,
)
from meta_flow.work.lifecycle_transaction import (
    WorkCloseAuthorizationV1,
    apply_work_close,
    inspect_work_close_transactions,
    plan_work_close,
)
from meta_flow.work.model import G1ScopeDeltaV1, load_work
from meta_flow.work.risk import RiskFacts, classify_work
from meta_flow.work.scope import WorkScope
from meta_flow.work.scope_amend import (
    G1ScopeAmendAuthorizationV1,
    apply_g1_scope_amend,
    plan_g1_scope_amend,
)
from meta_flow.work.status_transition import (
    WorkStatusTransitionAuthorizationV2,
    apply_work_status_transition,
    plan_work_status_transition,
)
from meta_flow.work.store import apply_work_init, plan_work_init_from_release_root


def _transition_authorization(plan) -> WorkStatusTransitionAuthorizationV2:
    return WorkStatusTransitionAuthorizationV2(
        authorization_id=f"cr078-status-{plan.plan_digest[:24]}",
        work_id=plan.parent_plan.work_id,
        plan_digest=plan.plan_digest,
        parent_plan_digest=plan.parent_plan.plan_digest,
        target_refs=plan.target_refs,
        expires_at=(datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
    )


def _transition(process: Path, work_id: str, expected: str, new: str, auth_id: str):
    plan = plan_work_status_transition(
        process, work_id, expected_status=expected, new_status=new
    )
    assert plan.ready, plan.parent_plan.blockers
    authorization = _transition_authorization(plan)
    authorization = replace(authorization, authorization_id=auth_id)
    receipt = apply_work_status_transition(process, plan, authorization)
    assert receipt.decision == "PASS"
    return authorization


def _blocked_fixture(tmp_path: Path):
    release, process, phase = _governance_fixture(tmp_path)
    _enable_state_projection(release, process)
    work = make_work(process, "W-001", phase.phase_ref)
    apply_work_init(plan_work_init_from_release_root(release, work))
    _transition(process, "W-001", "planned", "active", "cr078-w1-active")
    block_authorization = _transition(
        process, "W-001", "active", "blocked", "cr078-w1-block"
    )
    return release, process, block_authorization


def _g1_authorization(
    release: Path,
    process: Path,
    delta: G1ScopeDeltaV1,
    authorization_id: str,
    revision_id: str = "R2",
) -> G1ScopeAmendAuthorizationV1:
    release_oid, release_dirty = scope_amend_module._git_snapshot(release)
    process_oid, process_dirty = scope_amend_module._git_snapshot(process)
    work_path = process / "works/W-001/WORK.yaml"
    return G1ScopeAmendAuthorizationV1(
        schema_version=1,
        operation="work.scope-amend.g1",
        authorization_id=authorization_id,
        work_id="W-001",
        successor_revision_id=revision_id,
        release_oid=release_oid,
        process_oid=process_oid,
        release_dirty_digest=release_dirty,
        process_dirty_digest=process_dirty,
        work_preimage_digest=sha256(work_path.read_bytes()).hexdigest(),
        delta_digest=delta.digest,
        issued_at="2026-09-06T00:00:00Z",
    )


def _delta() -> G1ScopeDeltaV1:
    return G1ScopeDeltaV1(
        1,
        ("docs/new-input.md",),
        ("src/new-output.py",),
        ("compatibility",),
        "补充预检遗漏的业务读写和检查",
    )


def _amend(release: Path, process: Path, authorization_id: str, revision_id: str = "R2"):
    delta = _delta()
    authorization = _g1_authorization(release, process, delta, authorization_id, revision_id)
    plan = plan_g1_scope_amend(
        release,
        work_id="W-001",
        delta=delta,
        authorization=authorization,
        release_oid=authorization.release_oid,
        process_oid=authorization.process_oid,
    )
    assert plan.decision == "READY", plan.blockers
    result = apply_g1_scope_amend(
        plan,
        expected_plan_digest=plan.plan_digest,
        current_authorization=authorization,
        release_oid=authorization.release_oid,
        process_oid=authorization.process_oid,
    )
    return plan, result


def test_blocked_work_scope_amend_then_resume_and_close_full_chain(tmp_path: Path) -> None:
    release, process, block_authorization = _blocked_fixture(tmp_path)
    plan, result = _amend(release, process, "auth-w001-r2")

    assert result["decision"] == "PASS"
    successor_id = result["shared_projection_successor_id"]
    assert successor_id.startswith("work-scope-amend-")

    receipt = json.loads(
        (process / ".meta-flow-runtime/work-close/successors" / f"{successor_id}.json").read_text(
            encoding="utf-8"
        )
    )
    assert receipt["kind"] == "shared-projection-successor-v1"
    assert receipt["operation"] == "work.scope-amend"
    target = receipt["targets"][0]
    assert target["ref"] == "works/W-001/WORK.yaml"
    assert target["anchor_close_authorization_id"] == block_authorization.authorization_id
    block_manifest = json.loads(
        (
            process
            / ".meta-flow-runtime/work-close/transactions"
            / block_authorization.authorization_id
            / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    block_work_after = next(
        entry["after_digest"]
        for entry in block_manifest["targets"]
        if entry["ref"] == "works/W-001/WORK.yaml"
    )
    assert target["before_digest"] == block_work_after
    current = (process / "works/W-001/WORK.yaml").read_bytes()
    assert target["after_digest"] == sha256(current).hexdigest()

    assert inspect_work_close_transactions(process)["decision"] == "PASS"

    # resume（blocked→active）与 close 在登记后必须可用
    _transition(process, "W-001", "blocked", "active", "cr078-w1-resume")
    result_path = process / "works/W-001/RESULT.json"
    result_path.write_text(
        json.dumps({"schema_version": 1, "work_id": "W-001", "decision": "PASS"}) + "\n",
        encoding="utf-8",
    )
    close_plan = plan_work_close(
        process, "W-001", expected_status="active", outcome="completed",
        result_ref="works/W-001/RESULT.json",
    )
    assert close_plan.ready, close_plan.blockers
    close_receipt = apply_work_close(
        process,
        close_plan,
        WorkCloseAuthorizationV1(
            1,
            WORK_CLOSE_AUTHORIZATION_KIND,
            "cr078-w1-close",
            "W-001",
            close_plan.plan_digest,
            tuple(t.ref for t in close_plan.targets),
            "2099-01-01T00:00:00+00:00",
        ),
    )
    assert close_receipt.decision == "PASS"


def test_amend_without_close_history_writes_no_receipt(tmp_path: Path) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    work = replace(make_work(process, "W-001", phase.phase_ref), status="paused")
    apply_work_init(plan_work_init_from_release_root(release, work))
    assert not (process / ".meta-flow-runtime/work-close/transactions").exists() or not list(
        (process / ".meta-flow-runtime/work-close/transactions").glob("*/manifest.json")
    )
    plan, result = _amend(release, process, "auth-w001-noreceipt")

    assert result["decision"] == "PASS"
    assert result["shared_projection_successor_id"] == ""
    assert not (process / ".meta-flow-runtime/work-close/successors").exists() or not list(
        (process / ".meta-flow-runtime/work-close/successors").glob("*.json")
    )


def test_successive_amends_chain_single_successor_lineage(tmp_path: Path) -> None:
    release, process, _block = _blocked_fixture(tmp_path)
    _plan_a, result_a = _amend(release, process, "auth-w001-r2", "R2")
    _plan_b, result_b = _amend(release, process, "auth-w001-r3", "R3")
    assert result_a["decision"] == "PASS"
    assert result_b["decision"] == "PASS"

    receipt_b = json.loads(
        (
            process
            / ".meta-flow-runtime/work-close/successors"
            / f"{result_b['shared_projection_successor_id']}.json"
        ).read_text(encoding="utf-8")
    )
    assert receipt_b["targets"][0]["predecessor_successor_id"] == result_a[
        "shared_projection_successor_id"
    ]
    assert inspect_work_close_transactions(process)["decision"] == "PASS"
    _transition(process, "W-001", "blocked", "active", "cr078-w1-resume2")


def test_wedged_work_yaml_blocks_plan_zero_write(tmp_path: Path) -> None:
    release, process, _block = _blocked_fixture(tmp_path)
    _plan, result = _amend(release, process, "auth-w001-r2")
    assert result["decision"] == "PASS"
    successor_id = result["shared_projection_successor_id"]
    receipt_path = process / ".meta-flow-runtime/work-close/successors" / f"{successor_id}.json"
    snapshot = {
        path: path.read_bytes()
        for path in sorted(process.rglob("*"))
        if path.is_file() and ".meta-flow-runtime" not in path.parts
    }
    receipt_path.unlink()

    delta = _delta()
    authorization = _g1_authorization(release, process, delta, "auth-w001-wedged")
    plan = plan_g1_scope_amend(
        release,
        work_id="W-001",
        delta=delta,
        authorization=authorization,
        release_oid=authorization.release_oid,
        process_oid=authorization.process_oid,
    )
    assert plan.decision == "BLOCKED"
    assert "G1_SCOPE_AMEND_LINEAGE_PREFLIGHT_BLOCKED" in plan.blockers
    after = {
        path: path.read_bytes()
        for path in sorted(process.rglob("*"))
        if path.is_file() and ".meta-flow-runtime" not in path.parts
    }
    assert after == snapshot
    report = inspect_work_close_transactions(process)
    assert report["decision"] == "BLOCKED"
    assert any("terminal generation mismatch" in error for error in report["errors"])


def test_apply_returns_partial_when_successor_record_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release, process, _block = _blocked_fixture(tmp_path)
    delta = _delta()
    authorization = _g1_authorization(release, process, delta, "auth-w001-partial")
    plan = plan_g1_scope_amend(
        release,
        work_id="W-001",
        delta=delta,
        authorization=authorization,
        release_oid=authorization.release_oid,
        process_oid=authorization.process_oid,
    )

    def _fail(*args: object, **kwargs: object) -> str:
        raise OSError("simulated successor receipt write failure")

    monkeypatch.setattr(scope_amend_module, "record_shared_projection_successor", _fail)
    result = apply_g1_scope_amend(
        plan,
        expected_plan_digest=plan.plan_digest,
        current_authorization=authorization,
        release_oid=authorization.release_oid,
        process_oid=authorization.process_oid,
    )
    assert result["decision"] == "PARTIAL"
    assert "SCOPE_AMEND_SHARED_SUCCESSOR_RECORD_FAILED" in result["reason_codes"]
    assert result["transaction_state"] == "COMMITTED"
    assert result["domain_mutation_count"] == 4


def test_g1_lane_shared_lock_and_lineage_assert_guards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    work = replace(make_work(process, "W-001", phase.phase_ref), status="paused")
    apply_work_init(plan_work_init_from_release_root(release, work))

    def _lock_fail(*args: object, **kwargs: object):
        raise ValueError("lock unavailable")

    monkeypatch.setattr(scope_amend_module, "acquire_shared_projection_writer_lock", _lock_fail)
    delta = _delta()
    authorization = _g1_authorization(release, process, delta, "auth-w001-lock")
    plan = plan_g1_scope_amend(
        release,
        work_id="W-001",
        delta=delta,
        authorization=authorization,
        release_oid=authorization.release_oid,
        process_oid=authorization.process_oid,
    )
    result = apply_g1_scope_amend(
        plan,
        expected_plan_digest=plan.plan_digest,
        current_authorization=authorization,
        release_oid=authorization.release_oid,
        process_oid=authorization.process_oid,
    )
    assert result["decision"] == "BLOCKED"
    assert result["reason_code"] == "G1_SCOPE_AMEND_SHARED_LOCK_UNAVAILABLE"
    monkeypatch.undo()

    def _assert_fail(*args: object, **kwargs: object) -> None:
        raise ValueError("work close terminal generation mismatch: boom")

    monkeypatch.setattr(
        scope_amend_module, "assert_work_close_shared_projection_lineage", _assert_fail
    )
    result = apply_g1_scope_amend(
        plan,
        expected_plan_digest=plan.plan_digest,
        current_authorization=authorization,
        release_oid=authorization.release_oid,
        process_oid=authorization.process_oid,
    )
    assert result["decision"] == "BLOCKED"
    assert result["reason_code"] == "SCOPE_AMEND_CLOSE_LINEAGE_BLOCKED"
    assert result["mutation_count"] == 0


def test_scope_amend_receipt_rejects_foreign_refs(tmp_path: Path) -> None:
    release, process, _block = _blocked_fixture(tmp_path)
    successors = process / ".meta-flow-runtime/work-close/successors"
    successors.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "kind": "shared-projection-successor-v1",
        "successor_id": "work-scope-amend-foreign-ref-fixture",
        "operation": "work.scope-amend",
        "writer_id": "scope-amend-foreign",
        "created_at": "2026-09-06T00:00:00Z",
        "targets": [
            {
                "ref": "PROJECT.yaml",
                "anchor_close_authorization_id": "cr078-w1-block",
                "predecessor_successor_id": "",
                "before_digest": "a" * 64,
                "after_digest": "b" * 64,
                "after_bytes_b64": "",
            }
        ],
    }
    (successors / "work-scope-amend-foreign-ref-fixture.json").write_text(
        json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8"
    )
    report = inspect_work_close_transactions(process)
    assert report["decision"] == "BLOCKED"


def _g2_work_fixture(tmp_path: Path):
    """G2 current CR lane 共享 fixture：blocked CR Work + 已批准 checkpoint/台账。"""

    release, process, phase = _governance_fixture(tmp_path)
    _enable_state_projection(release, process)
    classification = classify_work(
        RiskFacts(change_kind="code", touched_path_count=2, multi_step=True),
        requested_cr=True,
        g2_budget=BudgetLimit(reads=128, writes=64, check_groups=20, tokens=384_000),
    )
    from meta_flow.work.model import ExecutionUnitV1, build_work

    request_ref = "works/W-001/REQUEST.md"
    request_path = process / request_ref
    request_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_text("# 请求\n\n用户确认：是。\n", encoding="utf-8")
    work = build_work(
        work_id="W-001",
        project_id="demo",
        objective="G2 current CR scope successor",
        request_ref=request_ref,
        scope=WorkScope(1, (request_ref,), ("README.md",), ("targeted",)),
        classification=classification,
        release_base_oid="a" * 40,
        process_base_oid="",
        phase_ref=phase.phase_ref,
    )
    work = replace(
        work,
        execution_unit=ExecutionUnitV1(
            unit_id="W-001",
            root_concept="work-close",
            slice_id="W-001",
            container_role="primary",
            revision=1,
            supersedes_unit_id="",
            contract_ref=request_ref,
            contract_digest="c" * 64,
        ),
    )
    apply_work_init(plan_work_init_from_release_root(release, work))
    _transition(process, "W-001", "planned", "active", "cr078-g2-active")
    _transition(process, "W-001", "active", "blocked", "cr078-g2-block")

    checkpoint_ref = "process/checkpoints/CP5-CR078-TEST-G2.md"
    checkpoint = process / checkpoint_ref.removeprefix("process/")
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_text(
        "---\ncheckpoint_id: CP5-CR078-TEST-G2\nstatus: approved\n---\n",
        encoding="utf-8",
    )
    checkpoint_digest = sha256(checkpoint.read_bytes()).hexdigest()
    event = {
        "schema_version": 1,
        "event_id": "GATE-CR078-TEST-G2-APPROVED-V1",
        "event_type": "human_gate_approval",
        "approval_kind": "checkpoint_passage",
        "approval_kind_version": 1,
        "gate": "GATE_CR078_TEST_G2",
        "cr_id": "CR-TEST-078",
        "work_id": "W-001",
        "work_ids": ["W-001"],
        "checkpoint": "CP5",
        "checkpoint_ref": checkpoint_ref,
        "approved_checkpoint_digest": checkpoint_digest,
        "decision_ids": ["CP5A-D1"],
        "result_ref": "process/checks/CP5-CR078-TEST-G2.result.json",
        "status": "approved",
        "decision": "approve",
        "risk_acceptance": False,
    }
    ledger = process / "state/GATE-LEDGER.ndjson"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(json.dumps(event, sort_keys=True) + "\n", encoding="utf-8")
    return release, process, checkpoint_ref, checkpoint_digest, event


def _g2_delta_and_authorization(
    release: Path,
    process: Path,
    checkpoint_ref: str,
    checkpoint_digest: str,
    event: dict,
    *,
    add_writes: tuple[str, ...] = ("governance/DETECTOR-INCREMENTAL.json",),
    exact_authorized: bool = True,
    authorization_id: str = "auth-w001-g2-r2",
):
    from meta_flow.work.scope_amend import G2CurrentCRScopeAmendAuthorizationV2

    delta = G1ScopeDeltaV1(
        1, (), add_writes, (), "G2 detector baseline successor"
    )
    release_oid, release_dirty = scope_amend_module._git_snapshot(release)
    process_oid, process_dirty = scope_amend_module._git_snapshot(process)
    authorized = (
        tuple(sorted(delta.add_writes))
        if exact_authorized
        else ("governance/EXACT-REF.json",)
    )
    authorization = G2CurrentCRScopeAmendAuthorizationV2(
        schema_version=2,
        operation="work.scope-amend.current-cr.g2",
        authorization_id=authorization_id,
        cr_id="CR-TEST-078",
        work_id="W-001",
        successor_revision_id="REV-W1-SCOPE-20260906-01",
        release_oid=release_oid,
        process_oid=process_oid,
        release_dirty_digest=release_dirty,
        process_dirty_digest=process_dirty,
        work_preimage_digest=sha256(
            (process / "works/W-001/WORK.yaml").read_bytes()
        ).hexdigest(),
        predecessor_scope_digest=load_work(process, "W-001").scope.digest,
        delta_digest=delta.digest,
        authorized_add_writes=authorized,
        invalidation_refs=tuple(
            sorted(
                [
                    "works/W-001/RESULT.json",
                    "works/W-001/evidence/validation/**",
                    "works/W-001/AUTHORIZATION.json",
                    "works/W-001/HANDOFF.yaml",
                ]
            )
        ),
        checkpoint_ref=checkpoint_ref,
        checkpoint_digest=checkpoint_digest,
        approval_event_id=event["event_id"],
        approval_event_digest=canonical_digest(event),
        approval_decision_id="CP5A-D1",
        issued_at="2026-09-06T00:00:00Z",
    )
    return delta, authorization


def test_g2_current_cr_lane_full_chain(tmp_path: Path) -> None:
    (
        release,
        process,
        checkpoint_ref,
        checkpoint_digest,
        event,
    ) = _g2_work_fixture(tmp_path)
    delta, authorization = _g2_delta_and_authorization(
        release, process, checkpoint_ref, checkpoint_digest, event
    )
    release_oid = authorization.release_oid
    process_oid = authorization.process_oid
    plan = plan_g1_scope_amend(
        release,
        work_id="W-001",
        delta=delta,
        authorization=authorization,
        release_oid=release_oid,
        process_oid=process_oid,
    )
    assert plan.decision == "READY", plan.blockers
    assert plan.lineage_preflight, "G2 lane must freeze lineage anchors at plan time"
    result = apply_g1_scope_amend(
        plan,
        expected_plan_digest=plan.plan_digest,
        current_authorization=authorization,
        release_oid=release_oid,
        process_oid=process_oid,
    )
    assert result["decision"] == "PASS"
    assert result["shared_projection_successor_id"].startswith("work-scope-amend-")
    assert inspect_work_close_transactions(process)["decision"] == "PASS"
    _transition(process, "W-001", "blocked", "active", "cr078-g2-resume")
