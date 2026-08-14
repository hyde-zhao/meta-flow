from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from meta_flow.execution_control.contract import ExecutionUnitV1
from meta_flow.project import governance_projection, phase_metadata, phase_transition
from meta_flow.project.governance import load_phase
from meta_flow.project.scale import dump_yaml
from meta_flow.state import current as state_current
from meta_flow.state.formal_projection import build_formal_truth_snapshot
from meta_flow.work.lifecycle import update_work_status
from meta_flow.work.lifecycle_transaction import (
    AUTHORIZATION_KIND as CLOSE_AUTHORIZATION_KIND,
)
from meta_flow.work.lifecycle_transaction import (
    WorkCloseAuthorizationV1,
    apply_work_close,
    inspect_work_close_transactions,
    plan_work_close,
)
from meta_flow.work.model import build_work, load_work
from meta_flow.work.risk import RiskFacts, classify_work
from meta_flow.work.scope import WorkScope
from meta_flow.work.store import apply_work_init, plan_work_init_from_release_root


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


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


def _work(
    process: Path,
    *,
    work_id: str,
    reads: tuple[str, ...],
    writes: tuple[str, ...],
):
    request_ref = f"works/{work_id}/REQUEST.md"
    _write(process / request_ref, "# 请求\n\n用户确认：是。\n")
    work = build_work(
        work_id=work_id,
        project_id="demo",
        objective="验证 Phase metadata 原生事务",
        request_ref=request_ref,
        phase_ref="phases/P1/PHASE.yaml",
        scope=WorkScope(
            1,
            tuple(dict.fromkeys((request_ref, *reads))),
            writes,
            ("targeted",),
        ),
        classification=classify_work(
            RiskFacts(change_kind="code", touched_path_count=len(writes), multi_step=True)
        ),
        release_base_oid="a" * 40,
        process_base_oid="b" * 40,
    )
    return replace(
        work,
        execution_unit=ExecutionUnitV1(
            unit_id=work_id,
            root_concept="phase-metadata",
            slice_id=work_id,
            container_role="primary",
            revision=1,
            supersedes_unit_id="",
            contract_ref=request_ref,
            contract_digest="c" * 64,
        ),
    )


def _close(process: Path, work_id: str, result_ref: str) -> None:
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
            CLOSE_AUTHORIZATION_KIND,
            "close-" + work_id.lower(),
            work_id,
            plan.plan_digest,
            tuple(target.ref for target in plan.targets),
            "2099-01-01T00:00:00+00:00",
        ),
    )
    assert receipt.decision == "PASS"


def _fixture(
    tmp_path: Path,
) -> tuple[
    Path,
    Path,
    str,
    str,
    tuple[governance_projection.ImmutableCommitRole, ...],
]:
    release = tmp_path / "demo"
    process = tmp_path / "demo-process"
    release.mkdir()
    process.mkdir()
    _git(release, "init", "-b", "main")
    _git(process, "init", "-b", "main")
    _write(release / "README.md", "# Demo\n")
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
                "process_repo": {"anchor": "workspace_parent", "relative_path": process.name},
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
                "release_repo": {"anchor": "workspace_parent", "relative_path": release.name},
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
outcome: native phase metadata
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
objective: close P1
status: active
work_refs: []
result_refs:
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
result_refs: []
updated_at: 2026-08-01T00:00:00Z
""",
    )
    _write(process / "governance/GOVERNANCE-BASELINE.json", "{}\n")
    _write(process / "changes/.gitkeep", "")
    process_input_oid = _commit(process, "formal truth baseline")
    roles = (
        governance_projection.ImmutableCommitRole("release_input", "release", release_oid),
        governance_projection.ImmutableCommitRole("process_input", "process", process_input_oid),
    )
    projection = governance_projection.build_governance_projection(process, roles)
    _write(
        process / "governance/GOVERNANCE-BASELINE.json",
        json.dumps(projection, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    state_current.init_current_state(release, project_id="demo")
    state_current.refresh_formal_truth_projection(release)
    _commit(process, "governance and State baseline")

    owner_id = "W-EVIDENCE"
    evidence_ref = f"works/{owner_id}/PHASE-EXIT-EVALUATION.yaml"
    result_ref = f"works/{owner_id}/RESULT.json"
    owner = _work(
        process,
        work_id=owner_id,
        reads=(),
        writes=(evidence_ref, result_ref),
    )
    apply_work_init(plan_work_init_from_release_root(release, owner))
    update_work_status(process, owner_id, expected_status="planned", new_status="active")
    _write(
        process / evidence_ref,
        dump_yaml(
            {
                "schema_version": 1,
                "kind": "PhaseExitEvaluationV1",
                "work_id": owner_id,
                "decision": "PASS_WITH_RISK",
            }
        )
        + "\n",
    )
    _write(
        process / result_ref,
        json.dumps({"schema_version": 1, "work_id": owner_id, "decision": "PASS"}) + "\n",
    )
    _close(process, owner_id, result_ref)
    _write(
        process / f"works/{owner_id}/UNOWNED.json",
        json.dumps({"schema_version": 1, "work_id": owner_id, "decision": "PASS"}) + "\n",
    )
    _commit(process, "closed evidence Work")

    controller_id = "W-METADATA"
    controller_result = f"works/{controller_id}/RESULT.json"
    controller = _work(
        process,
        work_id=controller_id,
        reads=(
            evidence_ref,
            f"works/{owner_id}/UNOWNED.json",
            "governance/GOVERNANCE-BASELINE.json",
        ),
        writes=(
            "phases/P1/PHASE.yaml",
            "phases/P2/PHASE.yaml",
            "governance/GOVERNANCE-BASELINE.json",
            "state/STATE.current.json",
            "STATE.md",
            "current/CURRENT.json",
            controller_result,
        ),
    )
    apply_work_init(plan_work_init_from_release_root(release, controller))
    update_work_status(process, controller_id, expected_status="planned", new_status="active")
    assert (
        governance_projection.validate_governance_projection(release, process)["decision"] == "PASS"
    )
    assert state_current.load_current_state(release)[
        "formal_truth_projection"
    ] == build_formal_truth_snapshot(release, process_root=process)
    return release, process, evidence_ref, controller_id, roles


def _plan(
    release: Path,
    process: Path,
    *,
    evidence_ref: str,
    controller_id: str,
    phase_ref: str = "process/phases/P1/PHASE.yaml",
    effective_at: str = "2026-08-14T01:00:00Z",
) -> phase_metadata.PhaseMetadataPlan:
    return phase_metadata.plan_phase_metadata_update(
        release,
        process,
        project_id="demo",
        work_id=controller_id,
        phase_ref=phase_ref,
        append_result_refs=("process/" + evidence_ref.removeprefix("process/"),),
        scope_digest=load_work(process, controller_id).scope.digest,
        effective_at=effective_at,
    )


def _authorization(
    plan: phase_metadata.PhaseMetadataPlan,
    authorization_id: str = "phase-metadata-auth",
) -> phase_metadata.PhaseMetadataAuthorizationV1:
    return phase_metadata.PhaseMetadataAuthorizationV1(
        1,
        phase_metadata.AUTHORIZATION_KIND,
        authorization_id,
        plan.project_id,
        plan.work_id,
        plan.phase_ref,
        plan.append_result_refs,
        plan.scope_digest,
        plan.plan_digest,
        tuple(sorted(plan.targets)),
        plan.target_set_digest,
        plan.repository_facts_digest,
        plan.release_oid,
        plan.process_oid,
        "2099-01-01T00:00:00+00:00",
    )


def _target_bytes(plan: phase_metadata.PhaseMetadataPlan) -> dict[str, bytes]:
    return {
        ref: (plan.process_root / ref.removeprefix("process/")).read_bytes() for ref in plan.targets
    }


def test_active_phase_accepts_closed_work_evidence_and_keeps_all_projections_current(
    tmp_path: Path,
) -> None:
    release, process, evidence_ref, controller_id, _roles = _fixture(tmp_path)
    plan = _plan(
        release,
        process,
        evidence_ref=evidence_ref,
        controller_id=controller_id,
    )

    assert plan.decision == "READY", plan.errors
    assert plan.as_dict()["mutation_count"] == 0
    assert set(plan.targets) == {
        "process/phases/P1/PHASE.yaml",
        "process/governance/GOVERNANCE-BASELINE.json",
        "process/state/STATE.current.json",
        "process/STATE.md",
        "process/current/CURRENT.json",
    }
    receipt = phase_metadata.apply_phase_metadata_update(plan, _authorization(plan))

    assert receipt["decision"] == "PASS"
    assert receipt["mutation_count"] == 5
    assert evidence_ref in load_phase(process, "phases/P1/PHASE.yaml").result_refs
    assert (
        governance_projection.validate_governance_projection(release, process)["decision"] == "PASS"
    )
    assert state_current.load_current_state(release)[
        "formal_truth_projection"
    ] == build_formal_truth_snapshot(release, process_root=process)
    assert inspect_work_close_transactions(process)["decision"] == "PASS"
    assert phase_metadata.inspect_phase_metadata(release, process)["decision"] == "PASS"


def test_planned_phase_accepts_governance_baseline_and_repeat_is_exact_noop(
    tmp_path: Path,
) -> None:
    release, process, _evidence_ref, controller_id, _roles = _fixture(tmp_path)
    plan = _plan(
        release,
        process,
        evidence_ref="governance/GOVERNANCE-BASELINE.json",
        controller_id=controller_id,
        phase_ref="process/phases/P2/PHASE.yaml",
    )
    assert plan.decision == "READY", plan.errors
    phase_metadata.apply_phase_metadata_update(plan, _authorization(plan, "planned-auth"))
    assert (
        "governance/GOVERNANCE-BASELINE.json"
        in load_phase(process, "phases/P2/PHASE.yaml").result_refs
    )

    noop = _plan(
        release,
        process,
        evidence_ref="governance/GOVERNANCE-BASELINE.json",
        controller_id=controller_id,
        phase_ref="process/phases/P2/PHASE.yaml",
    )
    before = _target_bytes(noop)
    assert noop.decision == "NOOP", noop.errors
    receipt = phase_metadata.apply_phase_metadata_update(
        noop, _authorization(noop, "planned-noop-auth")
    )
    assert receipt["disposition"] == "NOOP"
    assert receipt["mutation_count"] == 0
    assert before == _target_bytes(noop)


@pytest.mark.parametrize(
    ("evidence_ref", "expected"),
    [
        ("process/ROADMAP.yaml", "only accepts canonical governance baseline"),
        (
            "process/works/W-EVIDENCE/UNOWNED.json",
            "outside owner Work scope",
        ),
    ],
)
def test_unknown_or_owner_scope_mismatched_evidence_is_blocked_before_write(
    tmp_path: Path,
    evidence_ref: str,
    expected: str,
) -> None:
    release, process, _owned, controller_id, _roles = _fixture(tmp_path)
    before = {
        path.relative_to(process).as_posix(): path.read_bytes()
        for path in process.rglob("*")
        if path.is_file() and ".git" not in path.parts
    }
    plan = _plan(
        release,
        process,
        evidence_ref=evidence_ref,
        controller_id=controller_id,
    )
    assert plan.decision == "BLOCKED"
    assert any(expected in error for error in plan.errors)
    assert plan.as_dict()["planned_mutation_count"] == 0
    assert before == {
        path.relative_to(process).as_posix(): path.read_bytes()
        for path in process.rglob("*")
        if path.is_file() and ".git" not in path.parts
    }


def test_repository_fact_drift_blocks_apply_without_target_mutation(tmp_path: Path) -> None:
    release, process, evidence_ref, controller_id, _roles = _fixture(tmp_path)
    plan = _plan(
        release,
        process,
        evidence_ref=evidence_ref,
        controller_id=controller_id,
    )
    before = _target_bytes(plan)
    _write(process / "unrelated.txt", "drift\n")

    with pytest.raises(ValueError, match="drifted"):
        phase_metadata.apply_phase_metadata_update(plan, _authorization(plan))
    assert before == _target_bytes(plan)
    assert not (process / phase_metadata.MANIFEST_REL).exists()


def test_authorization_and_oid_drift_are_fail_closed_before_transaction(
    tmp_path: Path,
) -> None:
    release, process, evidence_ref, controller_id, _roles = _fixture(tmp_path)
    plan = _plan(
        release,
        process,
        evidence_ref=evidence_ref,
        controller_id=controller_id,
    )
    before = _target_bytes(plan)
    bad_authorization = replace(_authorization(plan), scope_digest="0" * 64)

    with pytest.raises(ValueError, match="does not bind"):
        phase_metadata.apply_phase_metadata_update(plan, bad_authorization)
    assert before == _target_bytes(plan)
    assert not (process / phase_metadata.MANIFEST_REL).exists()

    _commit(process, "advance process OID without changing metadata target bytes")
    with pytest.raises(ValueError, match="drifted"):
        phase_metadata.apply_phase_metadata_update(plan, _authorization(plan))
    assert before == _target_bytes(plan)
    assert not (process / phase_metadata.MANIFEST_REL).exists()


def test_authorization_path_must_be_external_regular_file(tmp_path: Path) -> None:
    release = tmp_path / "release"
    process = tmp_path / "process"
    release.mkdir()
    process.mkdir()
    inside = process / "authorization.json"
    inside.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="outside release/process"):
        phase_metadata.require_external_phase_metadata_authorization_path(
            release,
            process,
            inside,
        )

    outside = tmp_path / "authorization.json"
    outside.write_text("{}\n", encoding="utf-8")
    assert (
        phase_metadata.require_external_phase_metadata_authorization_path(
            release,
            process,
            outside,
        )
        == outside.resolve()
    )


def test_domain_write_failure_rolls_back_exact_bytes_and_leaves_recovered_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release, process, evidence_ref, controller_id, _roles = _fixture(tmp_path)
    plan = _plan(
        release,
        process,
        evidence_ref=evidence_ref,
        controller_id=controller_id,
    )
    before = _target_bytes(plan)

    original_write = phase_metadata._write_target
    failed = False

    def fail_once(path: Path, value: bytes) -> None:
        nonlocal failed
        if not failed and path.name == "PHASE.yaml":
            failed = True
            raise RuntimeError("injected domain failure")
        original_write(path, value)

    monkeypatch.setattr(phase_metadata, "_write_target", fail_once)
    with pytest.raises(RuntimeError, match="injected domain failure"):
        phase_metadata.apply_phase_metadata_update(plan, _authorization(plan))

    assert before == _target_bytes(plan)
    inspection = phase_metadata.inspect_phase_metadata(release, process)
    assert inspection["decision"] == "PASS"
    assert inspection["state"] == "RECOVERED"
    assert inspect_work_close_transactions(process)["decision"] == "PASS"


def test_partial_transaction_is_recoverable_without_manual_phase_edit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release, process, evidence_ref, controller_id, _roles = _fixture(tmp_path)
    plan = _plan(
        release,
        process,
        evidence_ref=evidence_ref,
        controller_id=controller_id,
    )
    before = _target_bytes(plan)
    original_state_apply = phase_metadata.apply_state_projection_transaction
    original_restore = phase_metadata._restore

    def fail_state(*_args, **_kwargs):
        raise RuntimeError("injected state failure")

    monkeypatch.setattr(phase_metadata, "apply_state_projection_transaction", fail_state)
    monkeypatch.setattr(
        phase_metadata,
        "_restore",
        lambda *_args, **_kwargs: (["INJECTED_RESTORE_FAILURE"], []),
    )
    with pytest.raises(phase_metadata.PhaseMetadataPartialError) as exc_info:
        phase_metadata.apply_phase_metadata_update(plan, _authorization(plan))
    assert exc_info.value.result["decision"] == "PARTIAL"
    assert phase_metadata.inspect_phase_metadata(release, process)["decision"] == "BLOCKED"

    monkeypatch.setattr(phase_metadata, "apply_state_projection_transaction", original_state_apply)
    monkeypatch.setattr(phase_metadata, "_restore", original_restore)
    recovered = phase_metadata.recover_phase_metadata(release, process)
    assert recovered["decision"] == "RECOVERED"
    assert before == _target_bytes(plan)
    assert phase_metadata.inspect_phase_metadata(release, process)["decision"] == "PASS"
    assert inspect_work_close_transactions(process)["decision"] == "PASS"


def test_native_successor_is_accepted_but_direct_phase_edit_remains_blocked(
    tmp_path: Path,
) -> None:
    release, process, evidence_ref, controller_id, _roles = _fixture(tmp_path)
    plan = _plan(
        release,
        process,
        evidence_ref=evidence_ref,
        controller_id=controller_id,
    )
    phase_metadata.apply_phase_metadata_update(plan, _authorization(plan))
    assert inspect_work_close_transactions(process)["decision"] == "PASS"

    path = process / "phases/P1/PHASE.yaml"
    native_bytes = path.read_bytes()
    payload = load_phase(process, "phases/P1/PHASE.yaml").as_dict()
    payload["updated_at"] = "2026-08-14T02:00:00Z"
    path.write_text(dump_yaml(payload) + "\n", encoding="utf-8")
    assert inspect_work_close_transactions(process)["decision"] == "BLOCKED"
    path.write_bytes(native_bytes)
    assert inspect_work_close_transactions(process)["decision"] == "PASS"


def test_metadata_preconditions_make_follow_up_phase_transition_ready_after_publish(
    tmp_path: Path,
) -> None:
    release, process, evidence_ref, controller_id, roles = _fixture(tmp_path)
    current_plan = _plan(
        release,
        process,
        evidence_ref=evidence_ref,
        controller_id=controller_id,
    )
    phase_metadata.apply_phase_metadata_update(
        current_plan, _authorization(current_plan, "current-phase-auth")
    )
    next_plan = _plan(
        release,
        process,
        evidence_ref="governance/GOVERNANCE-BASELINE.json",
        controller_id=controller_id,
        phase_ref="process/phases/P2/PHASE.yaml",
        effective_at="2026-08-14T01:30:00Z",
    )
    phase_metadata.apply_phase_metadata_update(
        next_plan, _authorization(next_plan, "next-phase-auth")
    )
    controller_result = f"works/{controller_id}/RESULT.json"
    _write(
        process / controller_result,
        json.dumps({"schema_version": 1, "work_id": controller_id, "decision": "PASS"}) + "\n",
    )
    _close(process, controller_id, controller_result)
    _commit(process, "publish Phase metadata preconditions")

    transition = phase_transition.plan_phase_transition(
        release,
        process,
        project_id="demo",
        from_phase_ref="process/phases/P1/PHASE.yaml",
        to_phase_ref="process/phases/P2/PHASE.yaml",
        closure_evidence_ref="process/" + evidence_ref,
        effective_at="2026-08-14T03:00:00Z",
        immutable_commit_roles=roles,
    )
    assert transition.decision == "READY", transition.errors


def test_cli_plan_uses_real_sibling_binding_and_returns_structured_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release, process, evidence_ref, controller_id, _roles = _fixture(tmp_path)
    work = load_work(process, controller_id)
    exit_code = phase_metadata.main(
        [
            "plan",
            "--project-root",
            str(release),
            "--project-id",
            "demo",
            "--work-id",
            controller_id,
            "--phase-ref",
            "process/phases/P1/PHASE.yaml",
            "--append-result-ref",
            "process/" + evidence_ref,
            "--scope-digest",
            work.scope.digest,
            "--effective-at",
            "2026-08-14T01:00:00Z",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["decision"] == "READY"
    assert payload["operation"] == "project.phase-metadata"
    assert payload["mutation_count"] == 0
