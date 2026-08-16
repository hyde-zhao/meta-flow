from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

from meta_flow.execution_control.contract import ExecutionUnitV1, canonical_digest
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
from meta_flow.work.model import ScopeDeltaV1, build_work, load_work
from meta_flow.work.risk import RiskFacts, classify_work
from meta_flow.work.scope import WorkScope
from meta_flow.work.scope_amend import (
    ScopeAmendAuthorizationV1,
    apply_scope_amend_transaction,
    plan_scope_amend_from_release_root,
)
from meta_flow.work.store import apply_work_init, plan_work_init_from_release_root
from meta_flow.workflow import cr_cli


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
