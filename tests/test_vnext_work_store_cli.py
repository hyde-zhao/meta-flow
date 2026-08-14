from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from meta_flow import cli
from meta_flow.execution_control import repair_admission as repair_admission_module
from meta_flow.execution_control.admission import (
    acquire_admission_lock,
    release_admission_lock,
)
from meta_flow.execution_control.contract import ExecutionUnitV1
from meta_flow.execution_control.repair_admission import (
    AUTHORIZATION_KIND as REPAIR_AUTHORIZATION_KIND,
)
from meta_flow.execution_control.repair_admission import (
    claim_repair_authorization,
    repair_admission_binding_ref,
    repair_authorization_claim_path,
    repair_blocker_fingerprint,
)
from meta_flow.project.governance import (
    Phase,
    load_governance_snapshot,
    load_phase,
    write_phase_create_only,
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
from meta_flow.project.query import main as project_query_main
from meta_flow.work.budget import G1_BUDGET, BudgetLimit
from meta_flow.work.cli import (
    check_main,
    classify_main,
    init_main,
    review_plan_main,
    status_main,
    transition_main,
    usage_add_main,
    usage_plan_main,
    validation_plan_main,
)
from meta_flow.work.io_metrics import IOMetrics
from meta_flow.work.lifecycle import update_work_status
from meta_flow.work.lifecycle_transaction import (
    AUTHORIZATION_KIND as WORK_CLOSE_AUTHORIZATION_KIND,
)
from meta_flow.work.lifecycle_transaction import (
    WorkCloseAuthorizationV1,
    plan_work_close,
)
from meta_flow.work.model import build_work, load_work, write_work_create_only
from meta_flow.work.read_context import OperationReadContext
from meta_flow.work.risk import RiskFacts, classify_work
from meta_flow.work.route_profile import RouteProfile
from meta_flow.work.scope import WorkScope
from meta_flow.work.store import (
    WorkInitApplyError,
    apply_work_init,
    close_work,
    plan_work_init,
    plan_work_init_from_release_root,
)
from meta_flow.work.usage import load_usage


def test_work_check_help_uses_its_public_command_name(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        check_main(["--help"])

    assert raised.value.code == 0
    assert "usage: meta-flow work check" in capsys.readouterr().out


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def init_project(root: Path) -> tuple[Path, Path]:
    release = root / "demo"
    release.mkdir()
    git(release, "init", "-b", "main")
    (release / "README.md").write_text("# Demo\n", encoding="utf-8")
    git(release, "add", "README.md")
    git(
        release,
        "-c",
        "user.name=Meta Flow Test",
        "-c",
        "user.email=meta-flow@example.invalid",
        "commit",
        "-m",
        "initial",
    )
    request = ProjectInitRequest(release, "demo", "Demo")
    plan = plan_project_init(request)
    payload = plan.as_dict()
    apply_project_init(
        plan,
        OnboardingAuthorization(
            1,
            "work-store-fixture",
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
    process = root / "demo-process"
    git(process, "add", ".")
    git(
        process,
        "-c",
        "user.name=Meta Flow Test",
        "-c",
        "user.email=meta-flow@example.invalid",
        "commit",
        "-m",
        "initial process",
    )
    return release, process


def make_request(process: Path, work_id: str = "W-001") -> str:
    ref = f"works/{work_id}/REQUEST.md"
    path = process / ref
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# 请求\n\n目标：更新 README。\n\n用户确认：是。\n",
        encoding="utf-8",
    )
    return ref


def make_work(process: Path, work_id: str = "W-001"):
    request_ref = make_request(process, work_id)
    return build_work(
        work_id=work_id,
        project_id="demo",
        objective="更新 README",
        request_ref=request_ref,
        scope=WorkScope(
            version=1,
            allowed_reads=(request_ref, "README.md"),
            allowed_writes=("README.md",),
            required_checks=("pytest-docs",),
        ),
        classification=classify_work(
            RiskFacts(change_kind="documentation", touched_path_count=1)
        ),
        release_base_oid="a" * 40,
        process_base_oid="",
    )


def typed_work(work):
    return replace(
        work,
        execution_unit=ExecutionUnitV1(
            unit_id=work.work_id,
            root_concept="work-init",
            slice_id=work.work_id,
            container_role="primary",
            revision=1,
            supersedes_unit_id="",
            contract_ref=work.request_ref,
            contract_digest="c" * 64,
        ),
    )


def execution_work(
    process: Path,
    work_id: str,
    *,
    role: str,
    root_concept: str = "repair-root",
    slice_id: str = "repair-slice",
):
    work = make_work(process, work_id)
    return replace(
        work,
        execution_unit=ExecutionUnitV1(
            unit_id=work_id,
            root_concept=root_concept,
            slice_id=slice_id,
            container_role=role,
            revision=1,
            supersedes_unit_id="",
            contract_ref=work.request_ref,
            contract_digest="c" * 64,
        ),
    )


def prepare_repair_authorization(
    tmp_path: Path,
    release: Path,
    process: Path,
    predecessor,
    candidate,
    *,
    overrides: dict[str, object] | None = None,
) -> Path:
    blocker_ref = f"works/{predecessor.work_id}/BLOCKER.json"
    blocker_path = process / blocker_ref
    blocker_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "WorkBlockerEvidenceV1",
                "work_id": predecessor.work_id,
                "decision": "BLOCKED",
                "blocker_id": "USAGE_HARD_STOP_100_PERCENT",
                "classification": "usage_budget_hard_stop",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    blocker_digest = hashlib.sha256(blocker_path.read_bytes()).hexdigest()
    payload: dict[str, object] = {
        "schema_version": 1,
        "kind": REPAIR_AUTHORIZATION_KIND,
        "authorization_id": f"repair-{candidate.work_id}",
        "authorization_source": "typed-user-confirmation",
        "project_id": candidate.project_id,
        "candidate_work_id": candidate.work_id,
        "predecessor_work_id": predecessor.work_id,
        "root_concept": candidate.execution_unit.root_concept,
        "slice_id": candidate.execution_unit.slice_id,
        "predecessor_scope_digest": predecessor.scope.digest,
        "predecessor_status": "blocked",
        "predecessor_blocker_category": "usage-hard-stop",
        "predecessor_blocker_code": "USAGE_HARD_STOP_100_PERCENT",
        "predecessor_blocker_ref": blocker_ref,
        "predecessor_blocker_digest": blocker_digest,
        "predecessor_blocker_fingerprint": repair_blocker_fingerprint(
            predecessor_work_id=predecessor.work_id,
            predecessor_status="blocked",
            predecessor_scope_digest=predecessor.scope.digest,
            predecessor_blocker_category="usage-hard-stop",
            predecessor_blocker_code="USAGE_HARD_STOP_100_PERCENT",
            predecessor_blocker_digest=blocker_digest,
        ),
        "candidate_scope_digest": candidate.scope.digest,
        "release_oid": git(release, "rev-parse", "HEAD"),
        "process_oid": git(process, "rev-parse", "HEAD"),
        "expires_at": "2099-01-01T00:00:00+00:00",
        "single_use": True,
    }
    payload.update(overrides or {})
    if overrides and any(
        field in overrides
        for field in (
            "predecessor_scope_digest",
            "predecessor_blocker_category",
            "predecessor_blocker_code",
            "predecessor_blocker_digest",
        )
    ) and "predecessor_blocker_fingerprint" not in overrides:
        payload["predecessor_blocker_fingerprint"] = repair_blocker_fingerprint(
            predecessor_work_id=str(payload["predecessor_work_id"]),
            predecessor_status=str(payload["predecessor_status"]),
            predecessor_scope_digest=str(payload["predecessor_scope_digest"]),
            predecessor_blocker_category=str(payload["predecessor_blocker_category"]),
            predecessor_blocker_code=str(payload["predecessor_blocker_code"]),
            predecessor_blocker_digest=str(payload["predecessor_blocker_digest"]),
        )
    path = tmp_path / f"{candidate.work_id}.repair-authorization.json"
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return path


def blocked_repair_fixture(tmp_path: Path):
    release, process = init_project(tmp_path)
    predecessor = execution_work(process, "W-PRIMARY", role="primary")
    apply_work_init(plan_work_init_from_release_root(release, predecessor))
    update_work_status(
        process,
        predecessor.work_id,
        expected_status="planned",
        new_status="active",
    )
    update_work_status(
        process,
        predecessor.work_id,
        expected_status="active",
        new_status="blocked",
    )
    predecessor = load_work(process, predecessor.work_id)
    candidate = execution_work(process, "W-REPAIR", role="repair")
    authorization = prepare_repair_authorization(
        tmp_path, release, process, predecessor, candidate
    )
    return release, process, predecessor, candidate, authorization


def snapshot_domain_files(process: Path) -> dict[str, bytes]:
    return {
        path.relative_to(process).as_posix(): path.read_bytes()
        for path in sorted(process.rglob("*"))
        if path.is_file() and ".git" not in path.parts
    }


def work_close_authorization(plan, authorization_id: str = "work-close-test"):
    return WorkCloseAuthorizationV1(
        schema_version=1,
        kind=WORK_CLOSE_AUTHORIZATION_KIND,
        authorization_id=authorization_id,
        work_id=plan.work_id,
        plan_digest=plan.plan_digest,
        target_refs=tuple(target.ref for target in plan.targets),
        expires_at="2099-01-01T00:00:00+00:00",
    )


@pytest.mark.parametrize(
    ("target_state", "typed", "context_kind", "expected", "blocked"),
    (
        ("missing", False, "canonical", "BLOCKED_NEW_OBJECT_REQUIRES_EXECUTION_UNIT", True),
        ("missing", False, "legacy", "BLOCKED_NEW_OBJECT_REQUIRES_EXECUTION_UNIT", True),
        ("missing", True, "canonical", "ADMISSION_REQUIRED", False),
        ("missing", True, "legacy", "BLOCKED_EXECUTION_CONTEXT_REQUIRED", True),
        ("current", False, "canonical", "NOOP_GRANDFATHERED_READ_ONLY", False),
        ("current", False, "legacy", "NOOP_GRANDFATHERED_READ_ONLY", False),
        ("repair", False, "canonical", "BLOCKED_LEGACY_HISTORY_WRITE_FORBIDDEN", True),
        ("repair", False, "legacy", "BLOCKED_LEGACY_HISTORY_WRITE_FORBIDDEN", True),
        ("current", True, "canonical", "NOOP_TYPED_CURRENT", False),
        ("current", True, "legacy", "NOOP_TYPED_EXISTING_READ_ONLY", False),
        ("repair", True, "canonical", "TYPED_REPAIR_AFTER_ADMISSION", False),
        ("repair", True, "legacy", "BLOCKED_EXECUTION_CONTEXT_REQUIRED", True),
    ),
)
def test_work_init_revision7_closed_compatibility_matrix_is_zero_write(
    tmp_path: Path,
    target_state: str,
    typed: bool,
    context_kind: str,
    expected: str,
    blocked: bool,
) -> None:
    release, process = init_project(tmp_path)
    work = make_work(process)
    if typed:
        work = typed_work(work)
    if target_state in {"current", "repair"}:
        write_work_create_only(process, work)
    if target_state == "current":
        project = load_project(process)
        replace_project(
            process,
            replace(project, active_work_refs=(work.work_ref,)),
            expected_project_id=project.project_id,
        )

    before = snapshot_domain_files(process)
    plan = (
        plan_work_init_from_release_root(release, work)
        if context_kind == "canonical"
        else plan_work_init(process, work)
    )
    after = snapshot_domain_files(process)

    assert plan.compatibility_decision == expected
    assert plan.blocked is blocked
    assert before == after
    payload = plan.as_dict()
    assert payload["domain_mutation_count"] == 0
    assert payload["coordination_mutation_count"] == 0
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    assert str(release) not in rendered
    assert str(process) not in rendered


def test_work_init_dry_run_then_apply_indexes_project(tmp_path: Path) -> None:
    release, process = init_project(tmp_path)
    work = typed_work(make_work(process))

    plan = plan_work_init_from_release_root(release, work)
    assert not plan.blocked
    assert plan.as_dict()["mutation_count"] == 0
    assert not (process / work.work_ref).exists()

    receipt = apply_work_init(plan)

    assert receipt.decision == "PASS"
    assert receipt.domain_mutation_count == 2
    assert receipt.coordination_mutation_count == 3
    assert receipt.mutation_count == 5
    assert receipt.transaction_state == "COMMITTED"
    assert receipt.transaction_id.startswith("work-init-")
    assert receipt.project_index_updated
    assert load_work(process, "W-001") == work
    assert load_project(process).active_work_refs == ("works/W-001/WORK.yaml",)
    snapshot, findings = load_governance_snapshot(process)
    assert findings == []
    assert snapshot is not None
    assert snapshot.objects_read == 2


def test_repair_work_requires_typed_authorization_and_keeps_global_policy_closed(
    tmp_path: Path,
) -> None:
    release, _process, _predecessor, candidate, _authorization = (
        blocked_repair_fixture(tmp_path)
    )

    plan = plan_work_init_from_release_root(release, candidate)

    assert plan.blocked
    assert {
        "CONTAINER_BUDGET_EXCEEDED",
        "REPAIR_AUTHORIZATION_REQUIRED",
    } <= {conflict.code for conflict in plan.conflicts}
    assert plan.repair_admission_binding is None


def test_typed_repair_authorization_creates_and_starts_one_native_repair_work(
    tmp_path: Path,
) -> None:
    release, process, predecessor, candidate, authorization = (
        blocked_repair_fixture(tmp_path)
    )
    predecessor_bytes = (process / predecessor.work_ref).read_bytes()

    plan = plan_work_init_from_release_root(
        release,
        candidate,
        repair_authorization_path=authorization,
    )
    receipt = apply_work_init(plan)
    started = update_work_status(
        process,
        candidate.work_id,
        expected_status="planned",
        new_status="active",
    )

    assert not plan.blocked
    assert plan.repair_admission_binding is not None
    assert plan.as_dict()["repair_admission"]["predecessor_work_id"] == predecessor.work_id
    assert str(authorization) not in json.dumps(plan.as_dict(), sort_keys=True)
    assert receipt.decision == "PASS"
    assert receipt.transaction_state == "COMMITTED"
    assert started.status == "active"
    assert (process / predecessor.work_ref).read_bytes() == predecessor_bytes
    claim = repair_authorization_claim_path(
        process, plan.repair_admission_binding.authorization_id
    )
    assert json.loads(claim.read_text(encoding="utf-8"))["state"] == "CONSUMED"
    durable_binding = process / repair_admission_binding_ref(candidate.work_id)
    assert json.loads(durable_binding.read_text(encoding="utf-8")) == (
        plan.repair_admission_binding.as_dict()
    )
    with pytest.raises(ValueError, match="already consumed"):
        claim_repair_authorization(process, plan.repair_admission_binding)
    idempotent = plan_work_init_from_release_root(
        release, load_work(process, candidate.work_id)
    )
    assert not idempotent.blocked
    assert idempotent.compatibility_decision == "NOOP_TYPED_CURRENT"
    followup = execution_work(
        process,
        "W-FOLLOWUP",
        role="primary",
        root_concept="followup-root",
        slice_id="followup-slice",
    )
    followup_plan = plan_work_init_from_release_root(release, followup)
    assert not followup_plan.blocked


def test_repair_claim_failure_never_unlinks_a_replaced_foreign_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release, process, _predecessor, candidate, authorization = (
        blocked_repair_fixture(tmp_path)
    )
    plan = plan_work_init_from_release_root(
        release,
        candidate,
        repair_authorization_path=authorization,
    )
    assert plan.repair_admission_binding is not None
    claim_path = repair_authorization_claim_path(
        process, plan.repair_admission_binding.authorization_id
    )
    real_fdopen = repair_admission_module.os.fdopen

    def replace_then_fail(descriptor: int, *args, **kwargs):
        stream = real_fdopen(descriptor, *args, **kwargs)
        stream.close()
        claim_path.unlink()
        claim_path.write_text("foreign-owner\n", encoding="utf-8")
        raise OSError("simulated post-create failure")

    monkeypatch.setattr(repair_admission_module.os, "fdopen", replace_then_fail)

    with pytest.raises(OSError, match="post-create failure"):
        claim_repair_authorization(process, plan.repair_admission_binding)

    assert claim_path.read_text(encoding="utf-8") == "foreign-owner\n"


@pytest.mark.parametrize("binding_state", ("missing", "invalid"))
def test_existing_repair_requires_its_portable_durable_binding(
    tmp_path: Path,
    binding_state: str,
) -> None:
    release, process, _predecessor, candidate, authorization = (
        blocked_repair_fixture(tmp_path)
    )
    plan = plan_work_init_from_release_root(
        release,
        candidate,
        repair_authorization_path=authorization,
    )
    apply_work_init(plan)
    binding_path = process / repair_admission_binding_ref(candidate.work_id)
    if binding_state == "missing":
        binding_path.unlink()
    else:
        binding_path.write_text("{}\n", encoding="utf-8")
    followup = execution_work(
        process,
        "W-FOLLOWUP",
        role="primary",
        root_concept="followup-root",
        slice_id="followup-slice",
    )
    before = snapshot_domain_files(process)

    followup_plan = plan_work_init_from_release_root(release, followup)

    assert followup_plan.blocked
    assert "REPAIR_INVENTORY_AUTHORIZATION_INVALID" in {
        conflict.code for conflict in followup_plan.conflicts
    }
    assert snapshot_domain_files(process) == before


def test_repair_work_cli_consumes_the_same_canonical_authorization(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release, process, _predecessor, candidate, authorization = (
        blocked_repair_fixture(tmp_path)
    )
    args = [
        "--project-root",
        str(release),
        "--work-id",
        candidate.work_id,
        "--objective",
        candidate.objective,
        "--request-ref",
        candidate.request_ref,
        "--allowed-read",
        candidate.request_ref,
        "--allowed-read",
        "README.md",
        "--allowed-write",
        "README.md",
        "--required-check",
        "pytest-docs",
        "--change-kind",
        "documentation",
        "--touched-path-count",
        "1",
        "--execution-unit-id",
        candidate.work_id,
        "--execution-root-concept",
        candidate.execution_unit.root_concept,
        "--execution-slice-id",
        candidate.execution_unit.slice_id,
        "--execution-container-role",
        "repair",
        "--execution-revision",
        "1",
        "--execution-contract-ref",
        candidate.request_ref,
        "--execution-contract-digest",
        "c" * 64,
        "--repair-authorization",
        str(authorization),
    ]

    dry_code = init_main(args)
    dry = json.loads(capsys.readouterr().out)
    apply_code = init_main([*args, "--apply"])
    applied = json.loads(capsys.readouterr().out)

    assert dry_code == 0
    assert dry["decision"] == "READY"
    assert dry["repair_admission"]["candidate_work_id"] == candidate.work_id
    assert apply_code == 0
    assert applied["receipt"]["decision"] == "PASS"
    assert load_work(process, candidate.work_id).status == "planned"


def test_repair_authorization_rejects_active_predecessor_but_not_other_slice(
    tmp_path: Path,
) -> None:
    release, process = init_project(tmp_path)
    predecessor = execution_work(process, "W-PRIMARY", role="primary")
    apply_work_init(plan_work_init_from_release_root(release, predecessor))
    update_work_status(
        process,
        predecessor.work_id,
        expected_status="planned",
        new_status="active",
    )
    predecessor = load_work(process, predecessor.work_id)
    candidate = execution_work(process, "W-REPAIR", role="repair")
    authorization = prepare_repair_authorization(
        tmp_path, release, process, predecessor, candidate
    )

    active_plan = plan_work_init_from_release_root(
        release, candidate, repair_authorization_path=authorization
    )
    assert "REPAIR_PREDECESSOR_STATUS_DRIFT" in {
        conflict.code for conflict in active_plan.conflicts
    }

    update_work_status(
        process,
        predecessor.work_id,
        expected_status="active",
        new_status="blocked",
    )
    other = execution_work(
        process,
        "W-OTHER",
        role="primary",
        root_concept="other-root",
        slice_id="other-slice",
    )
    apply_work_init(plan_work_init_from_release_root(release, other))
    update_work_status(
        process,
        other.work_id,
        expected_status="planned",
        new_status="active",
    )
    authorization = prepare_repair_authorization(
        tmp_path,
        release,
        process,
        load_work(process, predecessor.work_id),
        candidate,
    )

    other_slice_plan = plan_work_init_from_release_root(
        release, candidate, repair_authorization_path=authorization
    )
    assert "CONCURRENT_WRITE_BUDGET_EXCEEDED" not in {
        conflict.code for conflict in other_slice_plan.conflicts
    }


def test_repair_authorization_blocks_another_active_writer_in_the_same_slice(
    tmp_path: Path,
) -> None:
    release, process, predecessor, candidate, _authorization = (
        blocked_repair_fixture(tmp_path)
    )
    other = replace(
        execution_work(process, "W-SAME-SLICE", role="primary"),
        status="active",
    )
    write_work_create_only(process, other)
    project = load_project(process)
    replace_project(
        process,
        replace(project, active_work_refs=(*project.active_work_refs, other.work_ref)),
        expected_project_id=project.project_id,
    )
    authorization = prepare_repair_authorization(
        tmp_path, release, process, predecessor, candidate
    )

    plan = plan_work_init_from_release_root(
        release, candidate, repair_authorization_path=authorization
    )

    assert "CONCURRENT_WRITE_BUDGET_EXCEEDED" in {
        conflict.code for conflict in plan.conflicts
    }


@pytest.mark.parametrize(
    ("overrides", "expected"),
    (
        ({"candidate_scope_digest": "f" * 64}, "REPAIR_AUTHORIZATION_CANDIDATE_SCOPE_DRIFT"),
        ({"predecessor_scope_digest": "f" * 64}, "REPAIR_PREDECESSOR_SCOPE_DRIFT"),
        ({"release_oid": "f" * 40}, "REPAIR_AUTHORIZATION_OID_DRIFT"),
        ({"process_oid": "f" * 40}, "REPAIR_AUTHORIZATION_OID_DRIFT"),
        ({"project_id": "other-project"}, "REPAIR_AUTHORIZATION_PROJECT_MISMATCH"),
        ({"candidate_work_id": "W-OTHER"}, "REPAIR_AUTHORIZATION_CANDIDATE_MISMATCH"),
        (
            {
                "predecessor_work_id": "W-OTHER",
                "predecessor_blocker_ref": "works/W-OTHER/BLOCKER.json",
            },
            "REPAIR_PREDECESSOR_UNAVAILABLE",
        ),
        ({"root_concept": "other-root"}, "REPAIR_AUTHORIZATION_ROOT_MISMATCH"),
        ({"slice_id": "other-slice"}, "REPAIR_AUTHORIZATION_SLICE_MISMATCH"),
        ({"expires_at": "2000-01-01T00:00:00+00:00"}, "REPAIR_AUTHORIZATION_EXPIRED"),
    ),
)
def test_repair_authorization_fails_closed_on_bound_fact_drift(
    tmp_path: Path,
    overrides: dict[str, object],
    expected: str,
) -> None:
    release, process, predecessor, candidate, _authorization = (
        blocked_repair_fixture(tmp_path)
    )
    authorization = prepare_repair_authorization(
        tmp_path,
        release,
        process,
        predecessor,
        candidate,
        overrides=overrides,
    )

    plan = plan_work_init_from_release_root(
        release, candidate, repair_authorization_path=authorization
    )

    assert plan.blocked
    assert expected in {conflict.code for conflict in plan.conflicts}
    assert not (process / candidate.work_ref).exists()


def test_repair_apply_revalidates_predecessor_under_lock_before_domain_mutation(
    tmp_path: Path,
) -> None:
    release, process, predecessor, candidate, authorization = (
        blocked_repair_fixture(tmp_path)
    )
    plan = plan_work_init_from_release_root(
        release, candidate, repair_authorization_path=authorization
    )
    project_before = (process / "PROJECT.yaml").read_bytes()
    update_work_status(
        process,
        predecessor.work_id,
        expected_status="blocked",
        new_status="active",
    )

    with pytest.raises(WorkInitApplyError) as raised:
        apply_work_init(plan)

    assert raised.value.receipt.domain_mutation_count == 0
    assert not (process / candidate.work_ref).exists()
    assert (process / "PROJECT.yaml").read_bytes() == project_before
    assert not repair_authorization_claim_path(
        process, plan.repair_admission_binding.authorization_id
    ).exists()


def test_repair_authorization_blocks_when_blocker_evidence_bytes_drift(
    tmp_path: Path,
) -> None:
    release, process, predecessor, candidate, authorization = (
        blocked_repair_fixture(tmp_path)
    )
    blocker = process / f"works/{predecessor.work_id}/BLOCKER.json"
    blocker.write_bytes(blocker.read_bytes() + b"\n")

    plan = plan_work_init_from_release_root(
        release, candidate, repair_authorization_path=authorization
    )

    assert plan.blocked
    assert "REPAIR_PREDECESSOR_BLOCKER_DRIFT" in {
        conflict.code for conflict in plan.conflicts
    }
    assert not (process / candidate.work_ref).exists()


def test_work_init_plan_reuses_project_and_request_in_one_snapshot(
    tmp_path: Path,
) -> None:
    _release, process = init_project(tmp_path)
    work = make_work(process)
    write_work_create_only(process, work)
    project = load_project(process)
    replace_project(
        process,
        replace(project, active_work_refs=(work.work_ref,)),
        expected_project_id=project.project_id,
    )
    metrics = IOMetrics("work-init-plan", enabled=True)
    context = OperationReadContext(
        process,
        operation_id="work-init-plan",
        operation_kind="plan",
        allowed_reads=("PROJECT.yaml", work.request_ref, work.work_ref),
        metrics=metrics,
    )

    first = plan_work_init(process, work, read_context=context)
    second = plan_work_init(process, work, read_context=context)

    assert first.plan_digest == second.plan_digest
    totals = metrics.summary()["totals"]
    assert totals["physical_reads"] == 2
    assert totals["cache_hits"] == 2


def test_work_init_is_idempotent(tmp_path: Path) -> None:
    release, process = init_project(tmp_path)
    work = typed_work(make_work(process))
    apply_work_init(plan_work_init_from_release_root(release, work))

    second = plan_work_init_from_release_root(release, work)
    receipt = apply_work_init(second)

    assert {action.action for action in second.actions} == {"noop"}
    assert receipt.mutation_count == 0
    assert not receipt.project_index_updated


def test_work_init_can_repair_matching_unindexed_work_after_partial_state(tmp_path: Path) -> None:
    release, process = init_project(tmp_path)
    work = typed_work(make_work(process))
    write_work_create_only(process, work)

    plan = plan_work_init_from_release_root(release, work)
    receipt = apply_work_init(plan)

    assert not plan.blocked
    assert receipt.domain_mutation_count == 1
    assert receipt.coordination_mutation_count == 3
    assert receipt.project_index_updated
    assert load_project(process).active_work_refs == (work.work_ref,)


def test_request_change_makes_work_plan_stale_before_mutation(tmp_path: Path) -> None:
    release, process = init_project(tmp_path)
    work = typed_work(make_work(process))
    plan = plan_work_init_from_release_root(release, work)
    (process / work.request_ref).write_text("changed\n", encoding="utf-8")

    with pytest.raises(WorkInitApplyError) as raised:
        apply_work_init(plan)

    assert raised.value.receipt.decision == "BLOCKED"
    assert raised.value.receipt.domain_mutation_count == 0
    assert raised.value.receipt.coordination_mutation_count == 2
    assert not (process / work.work_ref).exists()
    assert load_project(process).active_work_refs == ()


def test_work_init_lock_contention_blocks_without_domain_mutation(tmp_path: Path) -> None:
    release, process = init_project(tmp_path)
    work = typed_work(make_work(process))
    plan = plan_work_init_from_release_root(release, work)
    assert plan.admission_plan is not None
    git_common = process / git(process, "rev-parse", "--git-common-dir")
    held = acquire_admission_lock(
        git_common,
        plan.admission_plan,
        owner_token="independent-holder",
        owner_process_identity="test-holder",
    )
    assert held.decision == "PASS" and held.handle is not None
    try:
        with pytest.raises(WorkInitApplyError) as raised:
            apply_work_init(plan)
        receipt = raised.value.receipt
        assert receipt.decision == "BLOCKED"
        assert receipt.domain_mutation_count == 0
        assert receipt.coordination_mutation_count == 0
        assert receipt.durable_lock_count == 1
        assert not (process / work.work_ref).exists()
    finally:
        assert release_admission_lock(git_common, held.handle).decision == "PASS"


def test_work_init_rolls_back_exactly_after_first_domain_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    release, process = init_project(tmp_path)
    work = typed_work(make_work(process))
    plan = plan_work_init_from_release_root(release, work)

    from meta_flow.work import init_transaction

    project_before = (process / "PROJECT.yaml").read_bytes()
    request_before = (process / work.request_ref).read_bytes()
    original_replace = init_transaction._replace_target
    calls = 0

    def fail_project(path: Path, value: bytes | None) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected project writer failure")
        original_replace(path, value)

    monkeypatch.setattr(init_transaction, "_replace_target", fail_project)
    with pytest.raises(WorkInitApplyError) as raised:
        apply_work_init(plan)

    receipt = raised.value.receipt
    assert receipt.decision == "RECOVERED"
    assert receipt.domain_mutation_count == 0
    assert receipt.transaction_state == "RECOVERED"
    assert not receipt.recovery_required
    assert receipt.recovery_route == "stop-and-replan"
    assert (process / "PROJECT.yaml").read_bytes() == project_before
    assert (process / work.request_ref).read_bytes() == request_before
    assert not (process / work.work_ref).exists()
    assert load_project(process).active_work_refs == ()
    inspection = init_transaction.inspect_work_init_transactions(
        process,
        work_id=work.work_id,
    )
    assert inspection["decision"] == "PASS"
    assert inspection["transactions"][0]["state"] == "RECOVERED"
    from meta_flow.work.lifecycle_transaction import (
        acquire_shared_projection_writer_lock,
        release_shared_projection_writer_lock,
    )

    lock = acquire_shared_projection_writer_lock(process, "test-lock-after-recovery")
    release_shared_projection_writer_lock(lock, "test-lock-after-recovery")


def test_work_plan_blocks_missing_or_out_of_scope_request(tmp_path: Path) -> None:
    release, process = init_project(tmp_path)
    missing = build_work(
        work_id="W-001",
        project_id="demo",
        objective="x",
        request_ref="works/W-001/REQUEST.md",
        scope=WorkScope(1, ("README.md",), ("README.md",), ()),
        classification=classify_work(
            RiskFacts(change_kind="documentation", touched_path_count=1)
        ),
        release_base_oid="a" * 40,
        process_base_oid="",
    )

    plan = plan_work_init_from_release_root(release, typed_work(missing))

    assert plan.blocked
    assert {item.code for item in plan.conflicts} >= {"request_missing", "request_out_of_scope"}


def test_scope_declaration_cannot_exceed_profile_budget(tmp_path: Path) -> None:
    release, process = init_project(tmp_path)
    request_ref = make_request(process)
    reads = (request_ref, *(f"docs/{index}.md" for index in range(8)))
    work = build_work(
        work_id="W-001",
        project_id="demo",
        objective="x",
        request_ref=request_ref,
        scope=WorkScope(1, reads, (), ()),
        classification=classify_work(
            RiskFacts(change_kind="documentation", touched_path_count=1)
        ),
        release_base_oid="a" * 40,
        process_base_oid="",
    )

    plan = plan_work_init_from_release_root(release, typed_work(work))

    assert plan.blocked
    assert "read_scope_over_budget" in {item.code for item in plan.conflicts}


def test_work_classify_cli_reports_explainable_decision(capsys: pytest.CaptureFixture[str]) -> None:
    code = classify_main(
        [
            "--change-kind",
            "documentation",
            "--touched-path-count",
            "1",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["container_kind"] == "work"
    assert payload["risk_profile"] == "G0"
    assert payload["budget"] == {
        "reads": 8,
        "writes": 8,
        "check_groups": 3,
        "tokens": 32_000,
    }
    assert payload["cannot_silently_downgrade"] is True


def test_work_cli_end_to_end_and_top_level_dispatch(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    release, process = init_project(tmp_path)
    request_ref = make_request(process)
    common = [
        "--project-root",
        str(release),
        "--work-id",
        "W-001",
        "--objective",
        "更新 README",
        "--request-ref",
        request_ref,
        "--allowed-read",
        request_ref,
        "--allowed-read",
        "README.md",
        "--allowed-write",
        "README.md",
        "--required-check",
        "pytest-docs",
        "--change-kind",
        "documentation",
        "--touched-path-count",
        "1",
        "--execution-unit-id",
        "W-001",
        "--execution-root-concept",
        "work-init",
        "--execution-slice-id",
        "W-001",
        "--execution-container-role",
        "primary",
        "--execution-revision",
        "1",
        "--execution-contract-ref",
        request_ref,
        "--execution-contract-digest",
        "c" * 64,
    ]

    dry_code = init_main(common)
    dry_payload = json.loads(capsys.readouterr().out)
    assert dry_code == 0
    assert dry_payload["decision"] == "READY"
    assert dry_payload["mutation_count"] == 0
    assert dry_payload["route"] == {
        "decision": "READY",
        "mode": "routine-four-stage",
        "dispatch_mode": "direct",
        "stages": ["clarification", "design", "implementation", "verification"],
        "functional_agent_dispatches": 0,
        "legacy_cp_artifacts_allowed": False,
        "errors": [],
    }

    apply_code = init_main([*common, "--apply"])
    apply_payload = json.loads(capsys.readouterr().out)
    assert apply_code == 0
    assert apply_payload["receipt"]["decision"] == "PASS"

    status_code = status_main(
        ["--project-root", str(release), "--work-id", "W-001"]
    )
    status_payload = json.loads(capsys.readouterr().out)
    assert status_code == 0
    assert status_payload["default_objects_read"] == 1
    assert status_payload["work"]["work_id"] == "W-001"

    with pytest.raises(SystemExit) as raised:
        cli._run_work(["status", "--project-root", str(release), "--work-id", "W-001"])
    dispatched = json.loads(capsys.readouterr().out)
    assert raised.value.code == 0
    assert dispatched["work"]["risk_profile"] == "G0"
    assert dispatched["work"]["route_profile"]["dispatch_mode"] == "direct"


def test_g0_functional_agent_override_blocks_before_root_resolution(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = init_main(
        [
            "--project-root",
            str(tmp_path / "missing-release"),
            "--work-id",
            "W-001",
            "--objective",
            "不应调度",
            "--request-ref",
            "works/W-001/REQUEST.md",
            "--change-kind",
            "documentation",
            "--touched-path-count",
            "1",
            "--dispatch-mode",
            "functional-agent",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert payload["decision"] == "BLOCKED"
    assert "explicit G2 upgrade" in payload["error"]
    assert not (tmp_path / "missing-release").exists()


def test_legacy_cp_route_requires_g2_formal_cr_gate_evidence_and_scope(tmp_path: Path) -> None:
    release, process = init_project(tmp_path)
    request_ref = make_request(process)
    gate_ref = "gates/G2-DESIGN.md"
    classification = classify_work(
        RiskFacts(change_kind="code", touched_path_count=4, public_contract=True),
        requested_cr=True,
        g2_budget=BudgetLimit(30, 30, 12, 160_000),
    )
    work = build_work(
        work_id="W-001",
        project_id="demo",
        objective="显式 legacy 兼容",
        request_ref=request_ref,
        scope=WorkScope(1, (request_ref, gate_ref), (), ("full",)),
        classification=classification,
        release_base_oid="a" * 40,
        process_base_oid="",
        route_profile=RouteProfile(
            mode="legacy-cp0-cp8",
            legacy_cp_compatibility=True,
        ),
    )
    work = typed_work(work)

    missing_ref = plan_work_init_from_release_root(release, work)
    missing_file = plan_work_init_from_release_root(
        release, work, human_design_gate_ref=gate_ref
    )
    gate_path = process / gate_ref
    gate_path.parent.mkdir(parents=True)
    gate_path.write_text("approved: true\n", encoding="utf-8")
    ready = plan_work_init_from_release_root(
        release, work, human_design_gate_ref=gate_ref
    )

    assert "route_profile_blocked" in {item.code for item in missing_ref.conflicts}
    assert "human_design_gate_missing" in {item.code for item in missing_file.conflicts}
    assert not ready.blocked
    assert ready.route_decision.stages == tuple(f"CP{index}" for index in range(9))


def test_usage_add_cli_requires_fresh_plan_and_blocks_over_limit_before_mutation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release, process = init_project(tmp_path)
    work = typed_work(make_work(process))
    apply_work_init(plan_work_init_from_release_root(release, work))

    plan_exit = usage_plan_main(
        [
            "--project-root",
            str(release),
            "--work-id",
            "W-001",
            "--event-id",
            "usage-over-limit",
            "--stage",
            "implementation",
            "--reads",
            "9",
            "--tokens",
            "100",
        ]
    )
    plan_payload = json.loads(capsys.readouterr().out)
    exit_code = usage_add_main(
        [
            "--project-root",
            str(release),
            "--work-id",
            "W-001",
            "--event-id",
            "usage-over-limit",
            "--stage",
            "implementation",
            "--reads",
            "9",
            "--tokens",
            "100",
            "--admission-digest",
            plan_payload["plan_digest"],
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert plan_exit == 1
    assert exit_code == 1
    assert plan_payload["decision"] == "BLOCKED"
    assert payload["decision"] == "BLOCKED"
    assert "operation admission blocks execution" in payload["error"]
    ledger = load_usage(process, load_work(process, "W-001"))
    assert [event.event_id for event in ledger.events] == ["usage-over-limit"]


def test_sibling_binding_g1_cli_admits_exact_verification_stage_unit(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release, process = init_project(tmp_path)
    work = replace(
        make_work(process),
        risk_profile="G1",
        risk_reason_codes=("STANDARD_MULTI_FILE_OR_MULTI_STEP_CHANGE",),
        budget=G1_BUDGET,
    )
    apply_work_init(plan_work_init_from_release_root(release, typed_work(work)))
    arguments = [
        "--project-root",
        str(release),
        "--work-id",
        "W-001",
        "--event-id",
        "targeted-validation-1",
        "--stage",
        "verification",
        "--reads",
        "1",
        "--check-groups",
        "1",
        "--tokens",
        "1500",
    ]

    plan_exit = usage_plan_main(arguments)
    plan = json.loads(capsys.readouterr().out)
    add_exit = usage_add_main(
        [*arguments, "--admission-digest", plan["plan_digest"]]
    )
    receipt = json.loads(capsys.readouterr().out)

    assert not (release / "process").exists()
    assert plan_exit == 0
    assert plan["decision"] == "REVIEW"
    assert plan["post_action"] == "PAUSE_AFTER_EXECUTION"
    assert plan["stage_budget"]["check_groups"] == 1
    assert plan["projected_stage"]["check_groups"] == 1
    assert add_exit == 0
    assert receipt["decision"] == "RECORDED"
    assert receipt["admission_decision"] == "REVIEW"
    assert receipt["post_action"] == "PAUSE_AFTER_EXECUTION"
    assert receipt["remaining"]["check_groups"] == 7


def test_usage_add_cli_rejects_stale_admission_digest_without_mutation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release, process = init_project(tmp_path)
    apply_work_init(
        plan_work_init_from_release_root(release, typed_work(make_work(process)))
    )
    stale_arguments = [
        "--project-root",
        str(release),
        "--work-id",
        "W-001",
        "--event-id",
        "stale-event",
        "--stage",
        "implementation",
        "--tokens",
        "10",
    ]
    assert usage_plan_main(stale_arguments) == 0
    stale_plan = json.loads(capsys.readouterr().out)
    concurrent_arguments = [
        "--project-root",
        str(release),
        "--work-id",
        "W-001",
        "--event-id",
        "concurrent-event",
        "--stage",
        "implementation",
        "--tokens",
        "1",
    ]
    assert usage_plan_main(concurrent_arguments) == 0
    concurrent_plan = json.loads(capsys.readouterr().out)
    assert usage_add_main(
        [
            *concurrent_arguments,
            "--admission-digest",
            concurrent_plan["plan_digest"],
        ]
    ) == 0
    capsys.readouterr()

    exit_code = usage_add_main(
        [*stale_arguments, "--admission-digest", stale_plan["plan_digest"]]
    )
    blocked = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert blocked["decision"] == "BLOCKED"
    assert "digest drifted" in blocked["error"]
    assert [
        event.event_id
        for event in load_usage(process, load_work(process, "W-001")).events
    ] == ["concurrent-event"]


def test_work_start_pause_resume_and_close_minimally_updates_project(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release, process = init_project(tmp_path)
    work = typed_work(make_work(process))
    apply_work_init(plan_work_init_from_release_root(release, work))

    assert transition_main(
        "start", ["--project-root", str(release), "--work-id", "W-001"]
    ) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "active"
    assert transition_main(
        "pause", ["--project-root", str(release), "--work-id", "W-001"]
    ) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "paused"
    assert (process / "works" / "W-001" / "HANDOFF.yaml").is_file()
    assert transition_main(
        "resume", ["--project-root", str(release), "--work-id", "W-001"]
    ) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "active"

    result_ref = "works/W-001/RESULT.json"
    (process / result_ref).write_text(
        json.dumps({"schema_version": 1, "work_id": "W-001", "decision": "PASS"}) + "\n",
        encoding="utf-8",
    )
    close_plan = plan_work_close(
        process,
        "W-001",
        expected_status="active",
        outcome="completed",
        result_ref=result_ref,
    )
    authorization_path = tmp_path / "work-close-authorization.json"
    authorization_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": WORK_CLOSE_AUTHORIZATION_KIND,
                "authorization_id": "work-close-cli-test",
                "work_id": close_plan.work_id,
                "plan_digest": close_plan.plan_digest,
                "target_refs": [target.ref for target in close_plan.targets],
                "expires_at": "2099-01-01T00:00:00+00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert transition_main(
        "close",
        [
            "--project-root",
            str(release),
            "--work-id",
            "W-001",
            "--result-ref",
            result_ref,
            "--apply",
            "--authorization",
            str(authorization_path),
        ],
    ) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "completed"
    assert load_work(process, "W-001").result_ref == result_ref
    assert load_project(process).active_work_refs == ()


def test_phase_work_index_is_added_on_init_and_projected_on_close(tmp_path: Path) -> None:
    release, process = init_project(tmp_path)
    phase = Phase(1, "demo", "PH-001", "完成首个阶段", "active")
    write_phase_create_only(process, phase)
    project = load_project(process)
    replace_project(
        process,
        replace(project, active_phase_ref=phase.phase_ref),
        expected_project_id=project.project_id,
    )
    work = typed_work(replace(make_work(process), phase_ref=phase.phase_ref))

    receipt = apply_work_init(plan_work_init_from_release_root(release, work))

    assert receipt.domain_mutation_count == 3
    assert receipt.coordination_mutation_count == 3
    assert load_phase(process, phase.phase_ref).work_refs == (work.work_ref,)
    update_work_status(
        process,
        work.work_id,
        expected_status="planned",
        new_status="active",
    )
    result_ref = "works/W-001/RESULT.json"
    (process / result_ref).write_text(
        json.dumps({"schema_version": 1, "work_id": "W-001", "decision": "PASS"}) + "\n",
        encoding="utf-8",
    )
    # 模拟 Work 真相已落盘、Project/Phase 投影尚未更新的中断现场。
    update_work_status(
        process,
        work.work_id,
        expected_status="active",
        new_status="completed",
        result_ref=result_ref,
    )
    assert load_project(process).active_work_refs == (work.work_ref,)
    assert load_phase(process, phase.phase_ref).work_refs == (work.work_ref,)
    close_plan = plan_work_close(
        process,
        work.work_id,
        expected_status="active",
        outcome="completed",
        result_ref=result_ref,
    )
    close_work(
        process,
        work.work_id,
        expected_status="active",
        outcome="completed",
        result_ref=result_ref,
        authorization=work_close_authorization(
            close_plan,
            "work-close-phase-projection-test",
        ),
    )

    projected = load_phase(process, phase.phase_ref)
    assert projected.work_refs == ()
    assert projected.result_refs == (result_ref,)
    assert load_project(process).active_work_refs == ()


def test_resume_blocks_after_release_oid_drift(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release, process = init_project(tmp_path)
    work = typed_work(make_work(process))
    apply_work_init(plan_work_init_from_release_root(release, work))
    transition_main("start", ["--project-root", str(release), "--work-id", "W-001"])
    capsys.readouterr()
    transition_main("pause", ["--project-root", str(release), "--work-id", "W-001"])
    capsys.readouterr()
    (release / "drift.txt").write_text("drift\n", encoding="utf-8")
    git(release, "add", "drift.txt")
    git(
        release,
        "-c",
        "user.name=Meta Flow Test",
        "-c",
        "user.email=meta-flow@example.invalid",
        "commit",
        "-m",
        "drift",
    )

    code = transition_main(
        "resume", ["--project-root", str(release), "--work-id", "W-001"]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert "release_oid_mismatch" in payload["error"]
    assert load_work(process, "W-001").status == "paused"


def test_review_and_validation_cli_are_work_scoped(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "meta_flow.execution_control.migration._receipt_path",
        lambda: tmp_path / "missing-provider-receipt.json",
    )
    release, process = init_project(tmp_path)
    work = typed_work(make_work(process))
    apply_work_init(plan_work_init_from_release_root(release, work))

    assert review_plan_main(
        ["--project-root", str(release), "--work-id", "W-001"]
    ) == 0
    review = json.loads(capsys.readouterr().out)
    assert review["review_mode"] == "self-check"
    assert review["max_independent_reviews"] == 0
    assert review["execution_control_mode"] == "enforce-new"
    assert review["provider_receipt_status"] == "MISSING"
    assert review["provider_readiness"] == "UNAVAILABLE_PENDING_CP7_CP8"

    assert validation_plan_main(
        [
            "--project-root",
            str(release),
            "--work-id",
            "W-001",
            "--check-risk",
            "pytest-docs=覆盖文档行为",
        ]
    ) == 0
    validation = json.loads(capsys.readouterr().out)
    assert validation["decision"] == "READY"
    assert validation["check_ids"] == ["pytest-docs"]
    assert validation["execution_control_mode"] == "enforce-new"
    assert validation["provider_readiness"] == "UNAVAILABLE_PENDING_CP7_CP8"

    assert project_query_main(["--project-root", str(release)]) == 0
    query = json.loads(capsys.readouterr().out)
    assert query["objects_read"] == 2
    assert query["work"]["work_id"] == "W-001"


def test_close_fails_without_result_and_keeps_work_active(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release, process = init_project(tmp_path)
    work = typed_work(make_work(process))
    apply_work_init(plan_work_init_from_release_root(release, work))
    transition_main("start", ["--project-root", str(release), "--work-id", "W-001"])
    capsys.readouterr()

    code = transition_main(
        "close", ["--project-root", str(release), "--work-id", "W-001"]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert payload["decision"] == "BLOCKED"
    assert load_work(process, "W-001").status == "active"
    assert load_project(process).active_work_refs == ("works/W-001/WORK.yaml",)
