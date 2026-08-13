from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from meta_flow.execution_control.contract import ExecutionUnitV1
from meta_flow.project import governance_projection, phase_transition
from meta_flow.project.governance import load_phase
from meta_flow.project.scale import load_yaml_object
from meta_flow.state import current, projection_transaction
from meta_flow.work.lifecycle import update_work_status
from meta_flow.work.lifecycle_transaction import (
    AUTHORIZATION_KIND,
    SUCCESSOR_ROOT_REL,
    WorkCloseAuthorizationV1,
    acquire_shared_projection_writer_lock,
    apply_work_close,
    inspect_work_close_transactions,
    plan_work_close,
    release_shared_projection_writer_lock,
)
from meta_flow.work.model import build_work
from meta_flow.work.risk import RiskFacts, classify_work
from meta_flow.work.scope import WorkScope
from meta_flow.work.store import apply_work_init, plan_work_init_from_release_root


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit(root: Path, message: str) -> str:
    _git(root, "add", ".")
    _git(
        root,
        "-c",
        "user.name=Meta Flow Test",
        "-c",
        "user.email=meta-flow@example.invalid",
        "commit",
        "-m",
        message,
    )
    return _git(root, "rev-parse", "HEAD")


def _fixture(
    tmp_path: Path,
) -> tuple[Path, Path, tuple[governance_projection.ImmutableCommitRole, ...]]:
    release = tmp_path / "demo"
    process = tmp_path / "demo-process"
    release.mkdir()
    process.mkdir()
    _git(release, "init", "-b", "main")
    _git(process, "init", "-b", "main")
    _write(release / "README.md", "# demo\n")
    _write(
        release / ".meta-flow/workspace.yaml",
        json.dumps(
            {
                "schema_version": 1,
                "layout_version": "independent-process-repo-v1",
                "workflow_model": "vnext",
                "project_id": "demo",
                "repo_role": "release",
                "route_mode": "sibling-binding",
                "process_repo": {
                    "anchor": "workspace_parent",
                    "relative_path": process.name,
                },
            }
        )
        + "\n",
    )
    release_oid = _commit(release, "release baseline")
    _write(
        process / ".meta-flow-process.yaml",
        json.dumps(
            {
                "schema_version": 1,
                "layout_version": "independent-process-repo-v1",
                "workflow_model": "vnext",
                "project_id": "demo",
                "repo_role": "process",
                "route_mode": "sibling-binding",
                "release_repo": {
                    "anchor": "workspace_parent",
                    "relative_path": release.name,
                },
            }
        )
        + "\n",
    )
    _write(
        process / "PROJECT.yaml",
        """schema_version: 1
project_id: demo
name: Demo
status: active
roadmap_ref: ROADMAP.yaml
active_phase_ref: phases/P1/PHASE.yaml
active_work_refs: []
updated_at: 2026-08-01T00:00:00Z
""",
    )
    _write(
        process / "ROADMAP.yaml",
        """schema_version: 1
project_id: demo
outcome: lifecycle
status: active
phase_refs:
  - phases/P1/PHASE.yaml
  - phases/P2/PHASE.yaml
updated_at: 2026-08-01T00:00:00Z
""",
    )
    _write(
        process / "phases/P1/PHASE.yaml",
        """schema_version: 1
project_id: demo
phase_id: P1
objective: finish P1
status: active
work_refs: []
result_refs:
  - phases/P1/CLOSURE.json
  - governance/GOVERNANCE-BASELINE.json
updated_at: 2026-08-01T00:00:00Z
""",
    )
    _write(
        process / "phases/P2/PHASE.yaml",
        """schema_version: 1
project_id: demo
phase_id: P2
objective: start P2
status: planned
work_refs: []
result_refs:
  - governance/GOVERNANCE-BASELINE.json
updated_at: 2026-08-01T00:00:00Z
""",
    )
    _write(process / "phases/P1/CLOSURE.json", '{"decision":"PASS"}\n')
    _write(process / "governance/GOVERNANCE-BASELINE.json", "{}\n")
    _write(process / "changes/.gitkeep", "")
    state = current.default_current_state(release, project_id="demo")
    state["current_phase"] = "P1"
    state["updated_at"] = "2026-08-01T00:00:00Z"
    current.write_current_state(release, state)
    process_oid = _commit(process, "phase transition baseline")
    roles = (
        governance_projection.ImmutableCommitRole(
            "release_input",
            "release",
            release_oid,
        ),
        governance_projection.ImmutableCommitRole(
            "process_input",
            "process",
            process_oid,
        ),
    )
    return release, process, roles


def _plan(
    release: Path,
    process: Path,
    roles: tuple[governance_projection.ImmutableCommitRole, ...],
) -> phase_transition.PhaseTransitionPlan:
    return phase_transition.plan_phase_transition(
        release,
        process,
        project_id="demo",
        from_phase_ref="process/phases/P1/PHASE.yaml",
        to_phase_ref="process/phases/P2/PHASE.yaml",
        closure_evidence_ref="process/phases/P1/CLOSURE.json",
        effective_at="2026-08-12T00:00:00Z",
        immutable_commit_roles=roles,
    )


def _close_active_phase_work(release: Path, process: Path, work_id: str) -> None:
    phase = load_phase(process, "phases/P1/PHASE.yaml")
    request_ref = f"works/{work_id}/REQUEST.md"
    _write(process / request_ref, "# request\n")
    work = build_work(
        work_id=work_id,
        project_id="demo",
        objective="验证 Phase transition 后继 lineage",
        request_ref=request_ref,
        phase_ref=phase.phase_ref,
        scope=WorkScope(1, (request_ref,), ("README.md",), ("targeted",)),
        classification=classify_work(
            RiskFacts(change_kind="code", touched_path_count=2, multi_step=True)
        ),
        release_base_oid="a" * 40,
        process_base_oid="b" * 40,
    )
    work = replace(
        work,
        execution_unit=ExecutionUnitV1(
            unit_id=work_id,
            root_concept="phase-transition-lineage",
            slice_id=work_id,
            container_role="primary",
            revision=1,
            supersedes_unit_id="",
            contract_ref=request_ref,
            contract_digest="c" * 64,
        ),
    )
    apply_work_init(plan_work_init_from_release_root(release, work))
    update_work_status(process, work_id, expected_status="planned", new_status="active")
    result_ref = f"works/{work_id}/RESULT.json"
    _write(
        process / result_ref,
        json.dumps({"schema_version": 1, "work_id": work_id, "decision": "PASS"})
        + "\n",
    )
    plan = plan_work_close(
        process,
        work_id,
        expected_status="active",
        outcome="completed",
        result_ref=result_ref,
    )
    receipt = apply_work_close(
        process,
        plan,
        WorkCloseAuthorizationV1(
            1,
            AUTHORIZATION_KIND,
            "close-" + work_id.lower(),
            work_id,
            plan.plan_digest,
            tuple(target.ref for target in plan.targets),
            "2099-01-01T00:00:00+00:00",
        ),
    )
    assert receipt.decision == "PASS"


def test_phase_transition_plan_is_zero_write_and_freezes_seven_targets(
    tmp_path: Path,
) -> None:
    release, process, roles = _fixture(tmp_path)
    before = {path: path.read_bytes() for path in process.rglob("*") if path.is_file()}

    plan = _plan(release, process, roles)

    assert plan.decision == "READY", plan.errors
    assert len(plan.targets) == 7
    assert plan.as_dict()["mutation_count"] == 0
    assert plan.as_dict()["planned_mutation_count"] == 7
    assert plan.as_dict()["transaction"]["recovery_required_on_partial"] is True
    assert before == {path: path.read_bytes() for path in process.rglob("*") if path.is_file()}


def test_phase_transition_apply_updates_formal_truth_and_all_projections(
    tmp_path: Path,
) -> None:
    release, process, roles = _fixture(tmp_path)
    plan = _plan(release, process, roles)

    receipt = phase_transition.apply_phase_transition(
        plan,
        expected_plan_digest=plan.plan_digest,
        expected_release_oid=plan.release_oid,
        expected_process_oid=plan.process_oid,
    )

    assert receipt["decision"] == "PASS"
    assert receipt["mutation_count"] == 7
    assert load_yaml_object(process / "phases/P1/PHASE.yaml")["status"] == "completed"
    assert load_yaml_object(process / "phases/P2/PHASE.yaml")["status"] == "active"
    assert load_yaml_object(process / "PROJECT.yaml")["active_phase_ref"] == "phases/P2/PHASE.yaml"
    assert current.load_current_state(release)["current_phase"] == "P2"
    assert current.validate_current_projection(release) == []
    assert (
        governance_projection.validate_governance_projection(release, process)["decision"] == "PASS"
    )
    assert phase_transition.inspect_phase_transition(release, process)["decision"] == "PASS"

    noop = _plan(release, process, roles)
    assert noop.decision == "NOOP", noop.errors
    noop_receipt = phase_transition.apply_phase_transition(
        noop,
        expected_plan_digest=noop.plan_digest,
        expected_release_oid=noop.release_oid,
        expected_process_oid=noop.process_oid,
    )
    assert noop_receipt["disposition"] == "NOOP"
    assert noop_receipt["mutation_count"] == 0


def test_phase_transition_blocks_before_write_when_shared_writer_is_held(
    tmp_path: Path,
) -> None:
    release, process, roles = _fixture(tmp_path)
    plan = _plan(release, process, roles)
    before = {
        ref: (process / ref.removeprefix("process/")).read_bytes()
        for ref in plan.targets
    }
    writer_id = "concurrent-work-close"
    lock = acquire_shared_projection_writer_lock(process, writer_id)
    try:
        with pytest.raises(ValueError, match="shared projection writer lock"):
            phase_transition.apply_phase_transition(
                plan,
                expected_plan_digest=plan.plan_digest,
                expected_release_oid=plan.release_oid,
                expected_process_oid=plan.process_oid,
            )
    finally:
        release_shared_projection_writer_lock(lock, writer_id)

    assert before == {
        ref: (process / ref.removeprefix("process/")).read_bytes()
        for ref in plan.targets
    }
    assert not (release / phase_transition.MANIFEST_REL).exists()


def test_phase_transition_is_an_authorized_successor_of_prior_work_close(
    tmp_path: Path,
) -> None:
    release, process, roles = _fixture(tmp_path)
    baseline = governance_projection.build_governance_projection(process, roles)
    _write(
        process / governance_projection.GOVERNANCE_PROJECTION_REL,
        json.dumps(baseline, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    _close_active_phase_work(release, process, "W-001")
    _commit(process, "freeze Work close generation before Phase transition")
    plan = _plan(release, process, roles)

    receipt = phase_transition.apply_phase_transition(
        plan,
        expected_plan_digest=plan.plan_digest,
        expected_release_oid=plan.release_oid,
        expected_process_oid=plan.process_oid,
    )

    assert receipt["shared_projection_successor_id"].startswith(
        "project-phase-transition-"
    )
    assert inspect_work_close_transactions(process)["decision"] == "PASS"


def test_phase_transition_discards_successor_receipt_when_final_manifest_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release, process, roles = _fixture(tmp_path)
    baseline = governance_projection.build_governance_projection(process, roles)
    _write(
        process / governance_projection.GOVERNANCE_PROJECTION_REL,
        json.dumps(baseline, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    _close_active_phase_work(release, process, "W-001")
    _commit(process, "freeze Work close generation before Phase transition")
    plan = _plan(release, process, roles)
    before = {
        ref: (process / ref.removeprefix("process/")).read_bytes()
        for ref in plan.targets
    }
    original_write_manifest = phase_transition._write_manifest
    injected = False

    def fail_after_successor_receipt(path: Path, payload: Mapping[str, object]) -> None:
        nonlocal injected
        if payload.get("state") == "COMMITTED" and payload.get("successor_id") and not injected:
            injected = True
            raise OSError("injected final manifest write failure")
        original_write_manifest(path, payload)

    monkeypatch.setattr(phase_transition, "_write_manifest", fail_after_successor_receipt)
    with pytest.raises(OSError, match="injected final manifest write failure"):
        phase_transition.apply_phase_transition(
            plan,
            expected_plan_digest=plan.plan_digest,
            expected_release_oid=plan.release_oid,
            expected_process_oid=plan.process_oid,
        )

    assert injected is True
    assert before == {
        ref: (process / ref.removeprefix("process/")).read_bytes()
        for ref in plan.targets
    }
    successor_root = process / SUCCESSOR_ROOT_REL
    assert not list(successor_root.glob("project-phase-transition-*.json"))
    assert phase_transition.inspect_phase_transition(release, process)["decision"] == "PASS"
    assert inspect_work_close_transactions(process)["decision"] == "PASS"


def test_phase_transition_recover_finalizes_successor_after_process_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release, process, roles = _fixture(tmp_path)
    baseline = governance_projection.build_governance_projection(process, roles)
    _write(
        process / governance_projection.GOVERNANCE_PROJECTION_REL,
        json.dumps(baseline, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    _close_active_phase_work(release, process, "W-001")
    _commit(process, "freeze Work close generation before Phase transition")
    plan = _plan(release, process, roles)
    original_record = phase_transition.record_shared_projection_successor

    def crash_before_successor(*_args: object, **_kwargs: object) -> str:
        raise KeyboardInterrupt("injected process crash before successor receipt")

    monkeypatch.setattr(
        phase_transition,
        "record_shared_projection_successor",
        crash_before_successor,
    )
    with pytest.raises(KeyboardInterrupt, match="injected process crash"):
        phase_transition.apply_phase_transition(
            plan,
            expected_plan_digest=plan.plan_digest,
            expected_release_oid=plan.release_oid,
            expected_process_oid=plan.process_oid,
        )

    manifest = json.loads((release / phase_transition.MANIFEST_REL).read_text(encoding="utf-8"))
    assert manifest["state"] == "COMMITTED"
    assert "successor_id" not in manifest
    assert inspect_work_close_transactions(process)["decision"] == "BLOCKED"
    (release / phase_transition.LOCK_REL).write_text(
        manifest["transaction_id"] + "\n",
        encoding="utf-8",
    )
    (release / projection_transaction.LOCK_REL).write_text(
        manifest["transaction_id"] + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        phase_transition,
        "record_shared_projection_successor",
        original_record,
    )
    recovered = phase_transition.recover_phase_transition(release, process)

    assert recovered["decision"] == "NO_CHANGE"
    assert recovered["shared_projection_successor_id"].startswith(
        "project-phase-transition-"
    )
    assert not (release / phase_transition.LOCK_REL).exists()
    assert not (release / projection_transaction.LOCK_REL).exists()
    assert phase_transition.inspect_phase_transition(release, process)["decision"] == "PASS"
    assert inspect_work_close_transactions(process)["decision"] == "PASS"


def test_phase_transition_recover_reuses_successor_after_manifest_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release, process, roles = _fixture(tmp_path)
    baseline = governance_projection.build_governance_projection(process, roles)
    _write(
        process / governance_projection.GOVERNANCE_PROJECTION_REL,
        json.dumps(baseline, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    _close_active_phase_work(release, process, "W-001")
    _commit(process, "freeze Work close generation before Phase transition")
    plan = _plan(release, process, roles)
    original_write_manifest = phase_transition._write_manifest
    injected = False

    def crash_after_successor_receipt(path: Path, payload: Mapping[str, object]) -> None:
        nonlocal injected
        if payload.get("state") == "COMMITTED" and payload.get("successor_id") and not injected:
            injected = True
            raise KeyboardInterrupt("injected process crash after successor receipt")
        original_write_manifest(path, payload)

    monkeypatch.setattr(
        phase_transition,
        "_write_manifest",
        crash_after_successor_receipt,
    )
    with pytest.raises(KeyboardInterrupt, match="injected process crash"):
        phase_transition.apply_phase_transition(
            plan,
            expected_plan_digest=plan.plan_digest,
            expected_release_oid=plan.release_oid,
            expected_process_oid=plan.process_oid,
        )

    manifest = json.loads((release / phase_transition.MANIFEST_REL).read_text(encoding="utf-8"))
    assert manifest["state"] == "COMMITTED"
    assert "successor_id" not in manifest
    successor_paths = list(
        (process / SUCCESSOR_ROOT_REL).glob("project-phase-transition-*.json")
    )
    assert len(successor_paths) == 1
    expected_successor_id = successor_paths[0].stem

    monkeypatch.setattr(
        phase_transition,
        "_write_manifest",
        original_write_manifest,
    )
    recovered = phase_transition.recover_phase_transition(release, process)

    assert recovered["decision"] == "NO_CHANGE"
    assert recovered["shared_projection_successor_id"] == expected_successor_id
    assert len(
        list((process / SUCCESSOR_ROOT_REL).glob("project-phase-transition-*.json"))
    ) == 1
    assert inspect_work_close_transactions(process)["decision"] == "PASS"


def test_phase_transition_preserves_state_writer_lineage_for_follow_up_update(
    tmp_path: Path,
) -> None:
    release, process, roles = _fixture(tmp_path)
    plan = _plan(release, process, roles)
    phase_transition.apply_phase_transition(
        plan,
        expected_plan_digest=plan.plan_digest,
        expected_release_oid=plan.release_oid,
        expected_process_oid=plan.process_oid,
    )

    assert (
        projection_transaction.inspect_state_projection_transaction(release)["decision"] == "PASS"
    )
    updated = current.update_current_state(
        release,
        {"next_action": {"type": "continue", "text": "follow-up"}},
        actor="test",
        reason="verify Phase-to-State transaction lineage",
    )

    assert updated["next_action"]["text"] == "follow-up"
    assert (
        projection_transaction.inspect_state_projection_transaction(release)["decision"] == "PASS"
    )
    # Phase journal 是 recovery cursor；后续合法 State writer 不应被误判成 terminal drift。
    assert phase_transition.inspect_phase_transition(release, process)["decision"] == "PASS"


def test_phase_transition_noop_blocks_unresolved_journal(tmp_path: Path) -> None:
    release, process, roles = _fixture(tmp_path)
    plan = _plan(release, process, roles)
    phase_transition.apply_phase_transition(
        plan,
        expected_plan_digest=plan.plan_digest,
        expected_release_oid=plan.release_oid,
        expected_process_oid=plan.process_oid,
    )
    noop = _plan(release, process, roles)
    assert noop.decision == "NOOP"
    manifest_path = release / phase_transition.MANIFEST_REL
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["state"] = "APPLYING"
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="requires inspect/recover"):
        phase_transition.apply_phase_transition(
            noop,
            expected_plan_digest=noop.plan_digest,
            expected_release_oid=noop.release_oid,
            expected_process_oid=noop.process_oid,
        )


def test_phase_transition_recover_claims_matching_crash_locks(tmp_path: Path) -> None:
    release, process, roles = _fixture(tmp_path)
    plan = _plan(release, process, roles)
    receipt = phase_transition.apply_phase_transition(
        plan,
        expected_plan_digest=plan.plan_digest,
        expected_release_oid=plan.release_oid,
        expected_process_oid=plan.process_oid,
    )
    transaction_id = receipt["transaction_id"]
    phase_lock = release / phase_transition.LOCK_REL
    state_lock = release / projection_transaction.LOCK_REL
    phase_lock.write_text(transaction_id + "\n", encoding="utf-8")
    state_lock.write_text(transaction_id + "\n", encoding="utf-8")

    assert phase_transition.inspect_phase_transition(release, process)["decision"] == "BLOCKED"
    recovered = phase_transition.recover_phase_transition(release, process)

    assert recovered["decision"] == "NO_CHANGE"
    assert recovered["lock_recovered"] is True
    assert not phase_lock.exists()
    assert not state_lock.exists()
    assert phase_transition.inspect_phase_transition(release, process)["decision"] == "PASS"


def test_phase_transition_recover_handles_crash_before_phase_manifest(tmp_path: Path) -> None:
    release, process, _roles = _fixture(tmp_path)
    transaction_id = "b" * 32
    state_handle = projection_transaction.acquire_transaction_lock(
        projection_transaction.state_projection_lock_path(release),
        transaction_id,
    )
    phase_root, _manifest_path, phase_lock_path = phase_transition._runtime_paths(release)
    assert phase_root.is_dir()
    phase_handle = projection_transaction.acquire_transaction_lock(
        phase_lock_path,
        transaction_id,
    )
    # 模拟两个锁已创建、但 Phase PREPARED manifest 尚未落盘时进程退出。
    state_handle.stream.close()
    phase_handle.stream.close()

    assert phase_transition.inspect_phase_transition(release, process)["decision"] == "BLOCKED"
    recovered = phase_transition.recover_phase_transition(release, process)

    assert recovered["decision"] == "NO_CHANGE"
    assert recovered["lock_recovered"] is True
    assert not phase_lock_path.exists()
    assert not projection_transaction.state_projection_lock_path(release).exists()
    assert phase_transition.inspect_phase_transition(release, process)["decision"] == "PASS"


def test_phase_transition_recover_does_not_steal_live_writer_lock(tmp_path: Path) -> None:
    release, process, roles = _fixture(tmp_path)
    plan = _plan(release, process, roles)
    receipt = phase_transition.apply_phase_transition(
        plan,
        expected_plan_digest=plan.plan_digest,
        expected_release_oid=plan.release_oid,
        expected_process_oid=plan.process_oid,
    )
    lock_path = release / phase_transition.LOCK_REL
    handle = projection_transaction.acquire_transaction_lock(
        lock_path,
        receipt["transaction_id"],
    )
    try:
        recovered = phase_transition.recover_phase_transition(release, process)
        assert recovered["decision"] == "BLOCKED"
        assert "active writer" in recovered["findings"][0]
        assert lock_path.exists()
    finally:
        projection_transaction.release_transaction_lock(handle)


def test_phase_transition_recovery_blocks_while_shared_writer_is_active(
    tmp_path: Path,
) -> None:
    release, process, roles = _fixture(tmp_path)
    plan = _plan(release, process, roles)
    phase_transition.apply_phase_transition(
        plan,
        expected_plan_digest=plan.plan_digest,
        expected_release_oid=plan.release_oid,
        expected_process_oid=plan.process_oid,
    )
    manifest_path = release / phase_transition.MANIFEST_REL
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["state"] = "APPLYING"
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    writer_id = "concurrent-work-close"
    lock = acquire_shared_projection_writer_lock(process, writer_id)
    try:
        recovered = phase_transition.recover_phase_transition(release, process)
    finally:
        release_shared_projection_writer_lock(lock, writer_id)

    assert recovered["decision"] == "BLOCKED"
    assert "shared projection writer lock" in recovered["findings"][0]
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["state"] == "APPLYING"


def test_phase_transition_rejects_preimage_drift_before_write(tmp_path: Path) -> None:
    release, process, roles = _fixture(tmp_path)
    plan = _plan(release, process, roles)
    target = process / "PROJECT.yaml"
    target.write_text(target.read_text(encoding="utf-8") + "# drift\n", encoding="utf-8")
    before = target.read_bytes()

    with pytest.raises(ValueError, match="drifted after planning"):
        phase_transition.apply_phase_transition(
            plan,
            expected_plan_digest=plan.plan_digest,
            expected_release_oid=plan.release_oid,
            expected_process_oid=plan.process_oid,
        )

    assert target.read_bytes() == before
    assert load_yaml_object(process / "phases/P1/PHASE.yaml")["status"] == "active"


def test_phase_transition_fault_is_rolled_back_and_inspectable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release, process, roles = _fixture(tmp_path)
    plan = _plan(release, process, roles)
    before = {ref: (process / ref.removeprefix("process/")).read_bytes() for ref in plan.targets}
    original = phase_transition._write_target
    calls = 0

    def fail_once(path: Path, value: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 4:
            raise OSError("fault injection")
        original(path, value)

    monkeypatch.setattr(phase_transition, "_write_target", fail_once)

    with pytest.raises(OSError, match="fault injection"):
        phase_transition.apply_phase_transition(
            plan,
            expected_plan_digest=plan.plan_digest,
            expected_release_oid=plan.release_oid,
            expected_process_oid=plan.process_oid,
        )

    assert before == {
        ref: (process / ref.removeprefix("process/")).read_bytes() for ref in plan.targets
    }
    inspection = phase_transition.inspect_phase_transition(release, process)
    assert inspection["decision"] == "PASS"
    assert inspection["state"] == "RECOVERED"


def test_phase_transition_cli_reports_actual_unrecovered_mutation_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release, _process, roles = _fixture(tmp_path)
    plan = _plan(release, _process, roles)
    original = phase_transition._write_target
    calls = 0

    def fail_apply_then_restore(path: Path, value: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls in {2, 3}:
            raise OSError("partial fault injection")
        original(path, value)

    monkeypatch.setattr(phase_transition, "_write_target", fail_apply_then_restore)
    args = [
        "apply",
        "--project-root",
        str(release),
        "--project-id",
        "demo",
        "--from-phase-ref",
        "process/phases/P1/PHASE.yaml",
        "--to-phase-ref",
        "process/phases/P2/PHASE.yaml",
        "--closure-evidence-ref",
        "process/phases/P1/CLOSURE.json",
        "--effective-at",
        "2026-08-12T00:00:00Z",
        "--expected-plan-digest",
        plan.plan_digest,
        "--expected-release-oid",
        plan.release_oid,
        "--expected-process-oid",
        plan.process_oid,
    ]
    for role in roles:
        args.extend(["--immutable-commit-role", f"{role.role}={role.repository}:{role.oid}"])

    exit_code = phase_transition.main(args)
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert payload["receipt"]["decision"] == "PARTIAL"
    assert payload["receipt"]["mutation_count"] == 1
    assert len(payload["receipt"]["unrecovered_refs"]) == 1
    assert payload["receipt"]["unrecovered_refs"][0] in payload["receipt"]["attempted_refs"]


def test_phase_transition_cli_uses_real_sibling_binding(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release, _process, roles = _fixture(tmp_path)
    args = [
        "plan",
        "--project-root",
        str(release),
        "--project-id",
        "demo",
        "--from-phase-ref",
        "process/phases/P1/PHASE.yaml",
        "--to-phase-ref",
        "process/phases/P2/PHASE.yaml",
        "--closure-evidence-ref",
        "process/phases/P1/CLOSURE.json",
        "--effective-at",
        "2026-08-12T00:00:00Z",
    ]
    for role in roles:
        args.extend(["--immutable-commit-role", f"{role.role}={role.repository}:{role.oid}"])

    exit_code = phase_transition.main(args)
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["decision"] == "READY"
    assert payload["project_id"] == "demo"
    assert payload["mutation_count"] == 0
