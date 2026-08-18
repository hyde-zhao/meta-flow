from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from meta_flow.execution_control.contract import ExecutionUnitV1, canonical_digest
from meta_flow.execution_control.runtime_context import target_preimage_digest
from meta_flow.project.governance import (
    Phase,
    Roadmap,
    write_phase_create_only,
    write_roadmap_create_only,
)
from meta_flow.project.model import load_project, replace_project
from meta_flow.project.onboarding import (
    ProjectInitRequest,
    apply_project_init,
    plan_project_init,
)
from meta_flow.project.onboarding_contract import (
    AUTHORIZATION_KIND,
    AUTHORIZATION_SOURCE,
    OnboardingAuthorization,
)
from meta_flow.state import current as state_current
from meta_flow.state.formal_projection import build_formal_truth_snapshot
from meta_flow.work import scope_amend as scope_amend_module
from meta_flow.work.model import ScopeDeltaV1, build_work, load_work
from meta_flow.work.risk import RiskFacts, classify_work
from meta_flow.work.scope import WorkScope
from meta_flow.work.scope_amend import (
    ScopeAmendAuthorizationV1,
    ScopeAmendAuthorizationV2,
    apply_scope_amend_transaction,
    plan_scope_amend_from_release_root,
)
from meta_flow.work.store import apply_work_init, plan_work_init_from_release_root
from meta_flow.workflow import cr_cli


def objective_authorization(
    authorization: ScopeAmendAuthorizationV1,
    *,
    predecessor: str = "Scope amendment integration",
    replacement: str = "Scope amendment integration; publish 0.6.0",
) -> ScopeAmendAuthorizationV2:
    return ScopeAmendAuthorizationV2(
        2,
        authorization.operation,
        authorization.authorization_id + "-objective",
        authorization.cr_id,
        authorization.work_id,
        authorization.predecessor_revision_id,
        authorization.successor_revision_id,
        authorization.predecessor_revision_bytes_digest,
        authorization.authorized_leaves,
        authorization.effective_at,
        predecessor,
        replacement,
    )


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def fixture(tmp_path: Path) -> tuple[Path, Path, ScopeAmendAuthorizationV1, list[dict[str, object]]]:
    release = tmp_path / "demo"
    release.mkdir()
    git(release, "init", "-b", "main")
    (release / "README.md").write_text("# Demo\n", encoding="utf-8")
    git(release, "add", "README.md")
    git(release, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "initial")
    onboarding = plan_project_init(ProjectInitRequest(release, "demo", "Demo"))
    payload = onboarding.as_dict()
    apply_project_init(
        onboarding,
        OnboardingAuthorization(
            1,
            "scope-amend-fixture",
            AUTHORIZATION_SOURCE,
            AUTHORIZATION_KIND,
            payload["operation"],
            payload["decision_ref"],
            payload["project_id"],
            payload["plan_digest"],
            payload["base_oids"],
            "2099-01-01T00:00:00+00:00",
        ),
    )
    process = tmp_path / "demo-process"
    phase = Phase(1, "demo", "P1", "Scope amendment fixture", "active")
    write_phase_create_only(process, phase)
    write_roadmap_create_only(
        process,
        Roadmap(1, "demo", "Scope amendment fixture", "active", (phase.phase_ref,)),
    )
    project = load_project(process)
    replace_project(
        process,
        replace(
            project,
            roadmap_ref="ROADMAP.yaml",
            active_phase_ref=phase.phase_ref,
        ),
        expected_project_id=project.project_id,
    )
    git(process, "add", ".")
    git(process, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "process")
    request_ref = "works/CR-071-R2/REQUEST.md"
    request = process / request_ref
    request.parent.mkdir(parents=True)
    request.write_text("# Confirmed request\n", encoding="utf-8")
    work = build_work(
        work_id="CR-071-R2",
        project_id="demo",
        objective="Scope amendment integration",
        request_ref=request_ref,
        scope=WorkScope(
            1,
            (request_ref,),
            ("existing.py",),
            ("targeted",),
        ),
        classification=classify_work(
            RiskFacts(change_kind="code", touched_path_count=2, multi_step=True),
        ),
        release_base_oid=git(release, "rev-parse", "HEAD"),
        process_base_oid=git(process, "rev-parse", "HEAD"),
        kind="cr",
    )
    work = replace(
        work,
        execution_unit=ExecutionUnitV1(
            unit_id=work.work_id,
            root_concept="scope-amend",
            slice_id=work.work_id,
            container_role="primary",
            revision=1,
            supersedes_unit_id="",
            contract_ref=work.request_ref,
            contract_digest="c" * 64,
        ),
    )
    init_plan = plan_work_init_from_release_root(release, work)
    assert init_plan.validation is not None
    assert init_plan.validation.passed
    assert init_plan.validation.graph.authoritative_decision_path_count == 1
    assert init_plan.validation.graph.planned_writes
    apply_work_init(init_plan)
    git(process, "add", ".")
    git(process, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "work")

    predecessor_bytes = b"immutable predecessor revision R1\n"
    inventory = ["existing.py", request_ref]
    inventory_digest = canonical_digest(inventory)
    receipts: list[dict[str, object]] = [
        {
            "cr_id": "CR-071",
            "predecessor_revision_id": "R1",
            "terminal_status": "verified",
            "inventory": inventory,
            "inventory_digest": inventory_digest,
            "revision_bytes_digest": sha256(predecessor_bytes).hexdigest(),
        }
    ]
    authorization = ScopeAmendAuthorizationV1(
        1,
        "work.scope-amend",
        "auth-cr071-r2",
        "CR-071",
        "CR-071-R2",
        "R1",
        "R2",
        sha256(predecessor_bytes).hexdigest(),
        ("new.py",),
        "2026-08-16T12:00:00Z",
    )
    return release, process, authorization, receipts


def enable_state_projection(release: Path, process: Path) -> None:
    (process / "changes").mkdir(exist_ok=True)
    state_current.init_current_state(release, project_id="demo")
    state_current.render_state_file(release, force=True)
    state_current.refresh_current_entry(release)
    state_current.refresh_formal_truth_projection(release)


def test_scope_amend_apply_appends_revision_projection_receipt_and_invalidation(tmp_path: Path) -> None:
    release, process, authorization, receipts = fixture(tmp_path)
    delta = ScopeDeltaV1(
        1,
        add_story_ids=("STORY-NEW",),
        add_owned_leaves=("new.py",),
        add_acceptance_refs=("checks/new.json",),
    )
    plan = plan_scope_amend_from_release_root(
        release,
        authorization=authorization,
        delta=delta,
        predecessor_receipts=receipts,
    )

    assert plan.validation.passed
    assert plan.validation.graph.authoritative_decision_path_count == 1
    result = apply_scope_amend_transaction(
        plan,
        expected_plan_digest=plan.plan_digest,
        predecessor_receipts=receipts,
    )

    assert result["decision"] == "PASS"
    assert result["mutation_count"] == 3
    assert (process / result["revision_ref"]).is_file()
    receipt = json.loads((process / result["receipt_ref"]).read_text(encoding="utf-8"))
    assert receipt["plan_digest"] == plan.plan_digest
    assert receipt["invalidated_refs"] == list(plan.core_plan.invalidated_refs)
    projected = load_work(process, "CR-071-R2")
    assert "new.py" in projected.scope.allowed_writes
    assert "STORY-NEW" in projected.scope.allowed_reads


def test_scope_amend_production_path_accepts_root_dotfile_owned_leaf(
    tmp_path: Path,
) -> None:
    release, process, authorization, receipts = fixture(tmp_path)
    authorization = replace(
        authorization,
        authorized_leaves=(".gitignore",),
    )
    plan = plan_scope_amend_from_release_root(
        release,
        authorization=authorization,
        delta=ScopeDeltaV1(1, add_owned_leaves=(".gitignore",)),
        predecessor_receipts=receipts,
    )

    assert plan.validation.passed
    assert plan.core_plan.result_scope == (
        ".gitignore",
        "existing.py",
        "targeted",
        "works/CR-071-R2/REQUEST.md",
    )
    result = apply_scope_amend_transaction(
        plan,
        expected_plan_digest=plan.plan_digest,
        predecessor_receipts=receipts,
    )

    assert result["decision"] == "PASS"
    assert ".gitignore" in load_work(process, "CR-071-R2").scope.allowed_writes


def test_scope_amend_v2_replaces_objective_in_same_successor_transaction(
    tmp_path: Path,
) -> None:
    release, process, authorization_v1, receipts = fixture(tmp_path)
    authorization = objective_authorization(authorization_v1)
    delta = ScopeDeltaV1(1, add_owned_leaves=("new.py",))
    plan = plan_scope_amend_from_release_root(
        release,
        authorization=authorization,
        delta=delta,
        predecessor_receipts=receipts,
    )

    assert plan.as_dict()["objective_transition"] == {
        "previous": "Scope amendment integration",
        "replacement": "Scope amendment integration; publish 0.6.0",
    }
    assert plan.successor_work.objective == authorization.replacement_objective
    result = apply_scope_amend_transaction(
        plan,
        expected_plan_digest=plan.plan_digest,
        predecessor_receipts=receipts,
    )

    assert result["decision"] == "PASS"
    projected = load_work(process, "CR-071-R2")
    assert projected.objective == authorization.replacement_objective
    revision = json.loads((process / result["revision_ref"]).read_text(encoding="utf-8"))
    assert revision["schema_version"] == 3
    assert revision["previous_objective"] == authorization.predecessor_objective
    assert revision["objective"] == authorization.replacement_objective
    receipt = json.loads((process / result["receipt_ref"]).read_text(encoding="utf-8"))
    assert receipt["schema_version"] == 2
    assert receipt["kind"] == "ScopeAmendReceiptV2"
    assert receipt["previous_objective"] == authorization.predecessor_objective
    assert receipt["objective"] == authorization.replacement_objective
    assert receipt["derived_index"]["objective"] == authorization.replacement_objective
    assert len(receipt["derived_index"]["objective_transition_digest"]) == 64


def test_scope_amend_v2_rejects_predecessor_objective_drift(tmp_path: Path) -> None:
    release, _process, authorization_v1, receipts = fixture(tmp_path)
    authorization = objective_authorization(
        authorization_v1,
        predecessor="stale objective",
    )

    with pytest.raises(ValueError, match="predecessor objective drifted"):
        plan_scope_amend_from_release_root(
            release,
            authorization=authorization,
            delta=ScopeDeltaV1(1, add_owned_leaves=("new.py",)),
            predecessor_receipts=receipts,
        )


def test_scope_amend_refreshes_initialized_state_in_the_locked_operation(
    tmp_path: Path,
) -> None:
    release, process, authorization, receipts = fixture(tmp_path)
    enable_state_projection(release, process)
    before_snapshot = build_formal_truth_snapshot(release)
    plan = plan_scope_amend_from_release_root(
        release,
        authorization=authorization,
        delta=ScopeDeltaV1(1, add_owned_leaves=("new.py",)),
        predecessor_receipts=receipts,
    )

    assert dict(plan.projection_preimages) == {
        ref: target_preimage_digest(process / ref)
        for ref in (
            "state/STATE.current.json",
            "STATE.md",
            "current/CURRENT.json",
        )
    }
    result = apply_scope_amend_transaction(
        plan,
        expected_plan_digest=plan.plan_digest,
        predecessor_receipts=receipts,
    )

    assert result["decision"] == "PASS"
    assert result["domain_mutation_count"] == 3
    assert result["coordination_mutation_count"] == 2
    assert result["mutation_count"] == 5
    state = state_current.load_current_state(release)
    after_snapshot = build_formal_truth_snapshot(release)
    assert after_snapshot["source_digest"] != before_snapshot["source_digest"]
    assert state["formal_truth_projection"] == after_snapshot
    assert state_current.validate_current_projection(release) == []


def test_scope_amend_rolls_back_domain_and_reprojects_old_truth_on_late_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    release, process, authorization, receipts = fixture(tmp_path)
    enable_state_projection(release, process)
    original_work = (process / "works/CR-071-R2/WORK.yaml").read_bytes()
    original_snapshot = build_formal_truth_snapshot(release)
    plan = plan_scope_amend_from_release_root(
        release,
        authorization=authorization,
        delta=ScopeDeltaV1(1, add_owned_leaves=("new.py",)),
        predecessor_receipts=receipts,
    )

    def fail_postimage(_plan) -> None:
        raise OSError("injected late postimage failure")

    monkeypatch.setattr(
        scope_amend_module,
        "_validate_scope_amend_postimage",
        fail_postimage,
    )
    result = apply_scope_amend_transaction(
        plan,
        expected_plan_digest=plan.plan_digest,
        predecessor_receipts=receipts,
    )

    assert result == {
        "decision": "REPLAN_REQUIRED",
        "reason_code": "TRANSACTION_RECOVERED",
        "mutation_count": 0,
    }
    assert (process / "works/CR-071-R2/WORK.yaml").read_bytes() == original_work
    assert not (process / "works/CR-071-R2/revisions/R2.json").exists()
    assert not (
        process / "works/CR-071-R2/scope-amendments/R2.receipt.json"
    ).exists()
    assert build_formal_truth_snapshot(release) == original_snapshot
    state = state_current.load_current_state(release)
    assert state["formal_truth_projection"] == original_snapshot
    assert state_current.validate_current_projection(release) == []


def test_scope_amend_v2_late_failure_restores_predecessor_objective(
    tmp_path: Path,
    monkeypatch,
) -> None:
    release, process, authorization_v1, receipts = fixture(tmp_path)
    enable_state_projection(release, process)
    authorization = objective_authorization(authorization_v1)
    original_work = (process / "works/CR-071-R2/WORK.yaml").read_bytes()
    plan = plan_scope_amend_from_release_root(
        release,
        authorization=authorization,
        delta=ScopeDeltaV1(1, add_owned_leaves=("new.py",)),
        predecessor_receipts=receipts,
    )

    def fail_postimage(_plan) -> None:
        raise OSError("injected objective postimage failure")

    monkeypatch.setattr(
        scope_amend_module,
        "_validate_scope_amend_postimage",
        fail_postimage,
    )
    result = apply_scope_amend_transaction(
        plan,
        expected_plan_digest=plan.plan_digest,
        predecessor_receipts=receipts,
    )

    assert result["decision"] == "REPLAN_REQUIRED"
    assert result["reason_code"] == "TRANSACTION_RECOVERED"
    assert (process / "works/CR-071-R2/WORK.yaml").read_bytes() == original_work
    assert load_work(process, "CR-071-R2").objective == "Scope amendment integration"
    assert not (process / "works/CR-071-R2/revisions/R2.json").exists()
    assert not (
        process / "works/CR-071-R2/scope-amendments/R2.receipt.json"
    ).exists()


def test_scope_amend_apply_replans_on_fresh_dirty_or_preimage_drift(tmp_path: Path) -> None:
    release, process, authorization, receipts = fixture(tmp_path)
    delta = ScopeDeltaV1(1, add_owned_leaves=("new.py",))
    plan = plan_scope_amend_from_release_root(
        release,
        authorization=authorization,
        delta=delta,
        predecessor_receipts=receipts,
    )
    before = (process / "works/CR-071-R2/WORK.yaml").read_bytes()
    (release / "README.md").write_text("# drift\n", encoding="utf-8")

    result = apply_scope_amend_transaction(
        plan,
        expected_plan_digest=plan.plan_digest,
        predecessor_receipts=receipts,
    )

    assert result["decision"] == "REPLAN_REQUIRED"
    assert result["mutation_count"] == 0
    assert (process / "works/CR-071-R2/WORK.yaml").read_bytes() == before
    assert not (process / "works/CR-071-R2/revisions/R2.json").exists()


def test_scope_amend_apply_denies_wrong_plan_digest_and_work_preimage_drift(
    tmp_path: Path,
) -> None:
    release, process, authorization, receipts = fixture(tmp_path)
    delta = ScopeDeltaV1(1, add_owned_leaves=("new.py",))
    plan = plan_scope_amend_from_release_root(
        release,
        authorization=authorization,
        delta=delta,
        predecessor_receipts=receipts,
    )

    wrong_digest = apply_scope_amend_transaction(
        plan,
        expected_plan_digest="0" * 64,
        predecessor_receipts=receipts,
    )
    assert wrong_digest == {
        "decision": "BLOCKED",
        "reason_code": "PLAN_DIGEST_MISMATCH",
        "mutation_count": 0,
    }

    work_path = process / "works/CR-071-R2/WORK.yaml"
    drifted = work_path.read_text(encoding="utf-8").replace(
        "objective: Scope amendment integration",
        "objective: Scope amendment integration drift",
    )
    work_path.write_text(drifted, encoding="utf-8")
    before_apply = work_path.read_bytes()

    result = apply_scope_amend_transaction(
        plan,
        expected_plan_digest=plan.plan_digest,
        predecessor_receipts=receipts,
    )

    assert result["decision"] == "REPLAN_REQUIRED"
    assert result["mutation_count"] == 0
    assert work_path.read_bytes() == before_apply
    assert not (process / "works/CR-071-R2/revisions/R2.json").exists()
    assert not (
        process / "works/CR-071-R2/scope-amendments/R2.receipt.json"
    ).exists()


def test_scope_amend_real_cli_dispatches_plan_bound_apply(
    tmp_path: Path,
    capsys,
) -> None:
    release, process, authorization, receipts = fixture(tmp_path)
    delta = ScopeDeltaV1(1, add_owned_leaves=("new.py",))
    plan = plan_scope_amend_from_release_root(
        release,
        authorization=authorization,
        delta=delta,
        predecessor_receipts=receipts,
    )
    authorization_path = tmp_path / "scope-amend-auth.json"
    authorization_path.write_text(
        json.dumps(authorization.as_dict()) + "\n",
        encoding="utf-8",
    )
    receipt_path = tmp_path / "predecessor.json"
    receipt_path.write_text(
        json.dumps({"schema_version": 1, "receipts": receipts}) + "\n",
        encoding="utf-8",
    )

    status = cr_cli.main(
        [
            "scope-amend",
            "--project-root",
            str(release),
            "--authorization-file",
            str(authorization_path),
            "--predecessor-receipt",
            str(receipt_path),
            "--add-owned-leaf",
            "new.py",
            "--apply",
            "--expected-plan-digest",
            plan.plan_digest,
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert status == 0
    assert payload["decision"] == "PASS"
    assert payload["mutation_count"] == 3
    assert (process / payload["revision_ref"]).is_file()


def test_scope_amend_v2_cli_requires_exact_replacement_objective(
    tmp_path: Path,
    capsys,
) -> None:
    release, _process, authorization_v1, receipts = fixture(tmp_path)
    authorization = objective_authorization(authorization_v1)
    authorization_path = tmp_path / "scope-amend-auth-v2.json"
    authorization_path.write_text(
        json.dumps(authorization.as_dict()) + "\n",
        encoding="utf-8",
    )
    receipt_path = tmp_path / "predecessor-v2.json"
    receipt_path.write_text(
        json.dumps({"schema_version": 1, "receipts": receipts}) + "\n",
        encoding="utf-8",
    )

    status = cr_cli.main(
        [
            "scope-amend",
            "--project-root",
            str(release),
            "--authorization-file",
            str(authorization_path),
            "--predecessor-receipt",
            str(receipt_path),
            "--add-owned-leaf",
            "new.py",
            "--replace-objective",
            "different objective",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert status == 1
    assert payload["decision"] == "BLOCKED"
    assert payload["mutation_count"] == 0
    assert "does not match authorization" in payload["error"]
