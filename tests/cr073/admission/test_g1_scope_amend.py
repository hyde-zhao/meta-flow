from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from meta_flow.execution_control.contract import canonical_digest
from meta_flow.work.budget import BudgetLimit
from meta_flow.work.cli import init_preflight_main, scope_amend_main
from meta_flow.work.model import G1ScopeDeltaV1, build_work, load_work, write_work_create_only
from meta_flow.work.risk import RiskFacts, classify_work
from meta_flow.work.scope import WorkScope
from meta_flow.work.scope_amend import (
    G1ScopeAmendAuthorizationV1,
    G2CurrentCRScopeAmendAuthorizationV2,
    apply_g1_scope_amend,
    inspect_g1_scope_amend,
    plan_g1_scope_amend,
    recover_g1_scope_amend,
)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _commit(root: Path, message: str) -> None:
    _git(root, "add", ".")
    _git(
        root,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        message,
    )


def _fixture(
    tmp_path: Path,
    *,
    status: str = "paused",
    g2_current_cr: bool = False,
) -> tuple[Path, Path, str]:
    release = tmp_path / "meta-flow"
    process = tmp_path / "meta-flow-process"
    (release / ".meta-flow").mkdir(parents=True)
    process.mkdir()
    _git(release, "init", "-b", "main")
    _git(process, "init", "-b", "main")
    (release / ".meta-flow" / "workspace.yaml").write_text(
        "schema_version: 1\n"
        "layout_version: independent-process-repo-v1\n"
        "workflow_model: vnext\n"
        "project_id: fixture\n"
        "repo_role: release\n"
        "route_mode: sibling-binding\n"
        "process_repo:\n"
        "  anchor: workspace_parent\n"
        "  relative_path: meta-flow-process\n",
        encoding="utf-8",
    )
    (release / "README.md").write_text("# Fixture\n", encoding="utf-8")
    (process / ".meta-flow-process.yaml").write_text(
        "schema_version: 1\n"
        "layout_version: independent-process-repo-v1\n"
        "workflow_model: vnext\n"
        "project_id: fixture\n"
        "repo_role: process\n"
        "route_mode: sibling-binding\n"
        "release_repo:\n"
        "  anchor: workspace_parent\n"
        "  relative_path: meta-flow\n",
        encoding="utf-8",
    )
    (process / "PROJECT.yaml").write_text(
        "schema_version: 1\nproject_id: fixture\nname: Fixture\nstatus: active\n",
        encoding="utf-8",
    )
    _commit(release, "release baseline")
    _commit(process, "process baseline")
    release_oid = _git(release, "rev-parse", "HEAD")
    process_oid = _git(process, "rev-parse", "HEAD")
    request_ref = "works/W-001/REQUEST.md"
    classification = classify_work(
        RiskFacts(change_kind="code", touched_path_count=2, multi_step=True),
        requested_cr=g2_current_cr,
        g2_budget=(
            BudgetLimit(reads=128, writes=64, check_groups=20, tokens=384_000)
            if g2_current_cr
            else None
        ),
    )
    work = build_work(
        work_id="W-001",
        project_id="fixture",
        objective="验证 G1 additive scope successor",
        request_ref=request_ref,
        scope=WorkScope(1, (request_ref,), ("src/existing.py",), ("targeted",)),
        classification=classification,
        release_base_oid=release_oid,
        process_base_oid=process_oid,
    )
    work = replace(work, status=status, result_ref="works/W-001/RESULT.json")
    request_path = process / request_ref
    request_path.parent.mkdir(parents=True)
    request_path.write_text("# Confirmed\n", encoding="utf-8")
    write_work_create_only(process, work)
    _commit(process, "work baseline")
    return release, process, _git(process, "rev-parse", "HEAD")


def _delta() -> G1ScopeDeltaV1:
    return G1ScopeDeltaV1(
        1,
        ("docs/new-input.md",),
        ("src/new-output.py",),
        ("compatibility",),
        "补充预检遗漏的业务读写和检查",
    )


def _authorization(
    release: Path,
    process: Path,
    process_oid: str,
    delta: G1ScopeDeltaV1,
    **updates: str,
) -> G1ScopeAmendAuthorizationV1:
    work_path = process / "works/W-001/WORK.yaml"
    values = {
        "schema_version": 1,
        "operation": "work.scope-amend.g1",
        "authorization_id": "auth-w001-r2",
        "work_id": "W-001",
        "successor_revision_id": "R2",
        "release_oid": _git(release, "rev-parse", "HEAD"),
        "process_oid": process_oid,
        "release_dirty_digest": canonical_digest({"status_lines": []}),
        "process_dirty_digest": canonical_digest({"status_lines": []}),
        "work_preimage_digest": sha256(work_path.read_bytes()).hexdigest(),
        "delta_digest": delta.digest,
        "issued_at": "2026-08-20T00:00:00Z",
    }
    values.update(updates)
    return G1ScopeAmendAuthorizationV1(**values)  # type: ignore[arg-type]


def _g2_delta() -> G1ScopeDeltaV1:
    return G1ScopeDeltaV1(
        1,
        (),
        ("governance/DETECTOR-INCREMENTAL-BASELINE.json",),
        (),
        "批准的 G2 current CR detector baseline scope successor",
    )


def _install_g2_approval(process: Path) -> tuple[str, str, dict[str, object], str]:
    checkpoint_ref = "process/checkpoints/CP5-TEST-G2-CURRENT-SCOPE.md"
    checkpoint = process / checkpoint_ref.removeprefix("process/")
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_text(
        "---\ncheckpoint_id: CP5-TEST-G2-CURRENT-SCOPE\nstatus: approved\n---\n",
        encoding="utf-8",
    )
    checkpoint_digest = sha256(checkpoint.read_bytes()).hexdigest()
    event: dict[str, object] = {
        "schema_version": 1,
        "event_id": "GATE-TEST-G2-CURRENT-SCOPE-APPROVED-V1",
        "event_type": "human_gate_approval",
        "approval_kind": "checkpoint_passage",
        "approval_kind_version": 1,
        "gate": "GATE_TEST_G2_CURRENT_SCOPE",
        "cr_id": "CR-TEST",
        "work_id": "W-001",
        "work_ids": ["W-001"],
        "checkpoint": "CP5",
        "checkpoint_ref": checkpoint_ref,
        "approved_checkpoint_digest": checkpoint_digest,
        "decision_ids": ["CP5A-D1"],
        "result_ref": "process/checks/CP5-TEST-G2-CURRENT-SCOPE.result.json",
        "status": "approved",
        "decision": "approve",
        "risk_acceptance": False,
    }
    ledger = process / "state/GATE-LEDGER.ndjson"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(
        json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _commit(process, "approved G2 current CR amendment")
    return checkpoint_ref, checkpoint_digest, event, canonical_digest(event)


def _g2_authorization(
    release: Path,
    process: Path,
    process_oid: str,
    delta: G1ScopeDeltaV1,
    checkpoint_ref: str,
    checkpoint_digest: str,
    event: dict[str, object],
    event_digest: str,
    **updates: object,
) -> G2CurrentCRScopeAmendAuthorizationV2:
    work = load_work(process, "W-001")
    values: dict[str, object] = {
        "schema_version": 2,
        "operation": "work.scope-amend.current-cr.g2",
        "authorization_id": "auth-w001-g2-r2",
        "cr_id": "CR-TEST",
        "work_id": "W-001",
        "successor_revision_id": "R2",
        "release_oid": _git(release, "rev-parse", "HEAD"),
        "process_oid": process_oid,
        "release_dirty_digest": canonical_digest({"status_lines": []}),
        "process_dirty_digest": canonical_digest({"status_lines": []}),
        "work_preimage_digest": sha256(
            (process / "works/W-001/WORK.yaml").read_bytes()
        ).hexdigest(),
        "predecessor_scope_digest": work.scope.digest,
        "delta_digest": delta.digest,
        "authorized_add_writes": delta.add_writes,
        "invalidation_refs": tuple(
            sorted(
                {
                    "checks/CP6-STORY-TEST.result.json",
                    "evidence/STORY-TEST.CP6.index.json",
                    "returns/STORY-TEST.CP6.return.json",
                    "works/W-001/AUTHORIZATION.json",
                    "works/W-001/HANDOFF.yaml",
                    "works/W-001/RESULT.json",
                    "works/W-001/evidence/validation/**",
                }
            )
        ),
        "checkpoint_ref": checkpoint_ref,
        "checkpoint_digest": checkpoint_digest,
        "approval_event_id": str(event["event_id"]),
        "approval_event_digest": event_digest,
        "approval_decision_id": "CP5A-D1",
        "issued_at": "2026-08-20T00:00:00Z",
    }
    values.update(updates)
    return G2CurrentCRScopeAmendAuthorizationV2(**values)  # type: ignore[arg-type]


def test_paused_g1_additive_amendment_commits_successor_and_invalidation(
    tmp_path: Path,
) -> None:
    release, process, process_oid = _fixture(tmp_path)
    delta = _delta()
    authorization = _authorization(release, process, process_oid, delta)
    plan = plan_g1_scope_amend(
        release,
        work_id="W-001",
        delta=delta,
        authorization=authorization,
        release_oid=authorization.release_oid,
        process_oid=authorization.process_oid,
    )

    assert plan.decision == "READY"
    assert plan.mutation_count == 0
    result = apply_g1_scope_amend(
        plan,
        expected_plan_digest=plan.plan_digest,
        current_authorization=authorization,
        release_oid=authorization.release_oid,
        process_oid=authorization.process_oid,
    )

    assert result["decision"] == "PASS"
    successor = load_work(process, "W-001")
    assert successor.scope.allowed_reads == (
        "docs/new-input.md",
        "works/W-001/REQUEST.md",
    )
    assert successor.scope.allowed_writes == ("src/existing.py", "src/new-output.py")
    revision = json.loads((process / str(result["revision_ref"])).read_text())
    invalidation = json.loads(
        (process / "works/W-001/evidence/scope-amend/auth-w001-r2.invalidation.json").read_text()
    )
    assert revision["kind"] == "WorkScopeRevisionV2"
    assert "works/W-001/evidence/validation/**" in invalidation["stale_refs"]
    assert inspect_g1_scope_amend(process, work_id="W-001")["decision"] == "PASS"

    replay = plan_g1_scope_amend(
        release,
        work_id="W-001",
        delta=delta,
        authorization=authorization,
        release_oid=authorization.release_oid,
        process_oid=authorization.process_oid,
    )
    assert replay.decision == "BLOCKED"
    assert "G1_SCOPE_AMEND_AUTHORIZATION_CONSUMED" in replay.blockers


@pytest.mark.parametrize("status", ["planned", "blocked"])
def test_g2_current_cr_v2_commits_exact_add_only_successor(
    tmp_path: Path,
    status: str,
) -> None:
    release, process, _process_oid = _fixture(
        tmp_path,
        status=status,
        g2_current_cr=True,
    )
    checkpoint_ref, checkpoint_digest, event, event_digest = _install_g2_approval(
        process
    )
    process_oid = _git(process, "rev-parse", "HEAD")
    delta = _g2_delta()
    authorization = _g2_authorization(
        release,
        process,
        process_oid,
        delta,
        checkpoint_ref,
        checkpoint_digest,
        event,
        event_digest,
    )

    plan = plan_g1_scope_amend(
        release,
        work_id="W-001",
        delta=delta,
        authorization=authorization,
        release_oid=authorization.release_oid,
        process_oid=authorization.process_oid,
    )

    assert plan.decision == "READY"
    assert plan.as_dict()["kind"] == "G2CurrentCRScopeAmendPlanV2"
    assert plan.as_dict()["profile"] == "g2-current-cr"
    result = apply_g1_scope_amend(
        plan,
        expected_plan_digest=plan.plan_digest,
        current_authorization=authorization,
        release_oid=authorization.release_oid,
        process_oid=authorization.process_oid,
    )

    assert result["decision"] == "PASS"
    successor = load_work(process, "W-001")
    assert successor.scope.allowed_writes == (
        "governance/DETECTOR-INCREMENTAL-BASELINE.json",
        "src/existing.py",
    )
    receipt = json.loads((process / str(result["receipt_ref"])).read_text())
    invalidation = json.loads(
        (
            process
            / "works/W-001/evidence/scope-amend/auth-w001-g2-r2.invalidation.json"
        ).read_text()
    )
    assert receipt["kind"] == "G2CurrentCRScopeAmendReceiptV2"
    assert receipt["checkpoint_digest"] == checkpoint_digest
    assert receipt["approval_event_digest"] == event_digest
    assert "checks/CP6-STORY-TEST.result.json" in receipt["invalidated_refs"]
    assert invalidation["reason"] == "G2_CURRENT_CR_SCOPE_SUCCESSOR"


@pytest.mark.parametrize(
    "status",
    [
        "active",
        "ready_for_review",
        "ready_for_verification",
        "completed",
        "cancelled",
        "archived",
    ],
)
def test_g2_current_cr_v2_rejects_active_and_terminal_states(
    tmp_path: Path,
    status: str,
) -> None:
    release, process, _process_oid = _fixture(
        tmp_path,
        status=status,
        g2_current_cr=True,
    )
    checkpoint_ref, checkpoint_digest, event, event_digest = _install_g2_approval(
        process
    )
    process_oid = _git(process, "rev-parse", "HEAD")
    delta = _g2_delta()
    authorization = _g2_authorization(
        release,
        process,
        process_oid,
        delta,
        checkpoint_ref,
        checkpoint_digest,
        event,
        event_digest,
    )

    plan = plan_g1_scope_amend(
        release,
        work_id="W-001",
        delta=delta,
        authorization=authorization,
        release_oid=authorization.release_oid,
        process_oid=authorization.process_oid,
    )

    assert plan.decision == "BLOCKED"
    assert "G2_CURRENT_CR_SCOPE_AMEND_STATUS_INVALID" in plan.blockers
    assert plan.mutation_count == 0
    assert not (process / "works/W-001/revisions/R2.json").exists()


@pytest.mark.parametrize(
    ("updates", "expected_blocker"),
    [
        (
            {"checkpoint_digest": "f" * 64},
            "G2_CURRENT_CR_SCOPE_AMEND_CHECKPOINT_DIGEST_MISMATCH",
        ),
        (
            {"approval_event_digest": "f" * 64},
            "G2_CURRENT_CR_SCOPE_AMEND_APPROVAL_BINDING_INVALID",
        ),
        (
            {"predecessor_scope_digest": "f" * 64},
            "G2_CURRENT_CR_SCOPE_AMEND_PREDECESSOR_SCOPE_MISMATCH",
        ),
        (
            {"authorized_add_writes": ("governance/OTHER.json",)},
            "G2_CURRENT_CR_SCOPE_AMEND_AUTHORIZED_WRITES_MISMATCH",
        ),
    ],
)
def test_g2_current_cr_v2_rejects_stale_or_unauthorized_bindings(
    tmp_path: Path,
    updates: dict[str, object],
    expected_blocker: str,
) -> None:
    release, process, _process_oid = _fixture(
        tmp_path,
        status="planned",
        g2_current_cr=True,
    )
    checkpoint_ref, checkpoint_digest, event, event_digest = _install_g2_approval(
        process
    )
    process_oid = _git(process, "rev-parse", "HEAD")
    delta = _g2_delta()
    authorization = _g2_authorization(
        release,
        process,
        process_oid,
        delta,
        checkpoint_ref,
        checkpoint_digest,
        event,
        event_digest,
    )
    authorization = replace(authorization, **updates)

    plan = plan_g1_scope_amend(
        release,
        work_id="W-001",
        delta=delta,
        authorization=authorization,
        release_oid=authorization.release_oid,
        process_oid=authorization.process_oid,
    )

    assert plan.decision == "BLOCKED"
    assert expected_blocker in plan.blockers
    assert plan.mutation_count == 0


def test_g2_current_cr_v2_requires_complete_invalidation_set(tmp_path: Path) -> None:
    release, process, _process_oid = _fixture(
        tmp_path,
        status="planned",
        g2_current_cr=True,
    )
    checkpoint_ref, checkpoint_digest, event, event_digest = _install_g2_approval(
        process
    )
    process_oid = _git(process, "rev-parse", "HEAD")
    delta = _g2_delta()
    authorization = _g2_authorization(
        release,
        process,
        process_oid,
        delta,
        checkpoint_ref,
        checkpoint_digest,
        event,
        event_digest,
        invalidation_refs=("checks/CP6-STORY-TEST.result.json",),
    )

    plan = plan_g1_scope_amend(
        release,
        work_id="W-001",
        delta=delta,
        authorization=authorization,
        release_oid=authorization.release_oid,
        process_oid=authorization.process_oid,
    )

    assert plan.decision == "BLOCKED"
    assert "G2_CURRENT_CR_SCOPE_AMEND_INVALIDATION_INCOMPLETE" in plan.blockers


@pytest.mark.parametrize("status", ["planned", "active", "completed"])
def test_wrong_status_is_zero_write_blocked(tmp_path: Path, status: str) -> None:
    release, process, process_oid = _fixture(tmp_path, status=status)
    delta = _delta()
    authorization = _authorization(release, process, process_oid, delta)
    plan = plan_g1_scope_amend(
        release,
        work_id="W-001",
        delta=delta,
        authorization=authorization,
        release_oid=authorization.release_oid,
        process_oid=authorization.process_oid,
    )

    assert plan.decision == "BLOCKED"
    assert "G1_SCOPE_AMEND_STATUS_INVALID" in plan.blockers
    assert plan.mutation_count == 0


def test_stale_oid_or_delta_authorization_is_zero_write_blocked(tmp_path: Path) -> None:
    release, process, process_oid = _fixture(tmp_path)
    delta = _delta()
    stale = _authorization(release, process, process_oid, delta, release_oid="f" * 40)
    plan = plan_g1_scope_amend(
        release,
        work_id="W-001",
        delta=delta,
        authorization=stale,
        release_oid=stale.release_oid,
        process_oid=stale.process_oid,
    )
    assert plan.decision == "BLOCKED"
    assert "G1_SCOPE_AMEND_OID_MISMATCH" in plan.blockers

    wrong_delta = _authorization(
        release,
        process,
        process_oid,
        delta,
        delta_digest="f" * 64,
    )
    plan = plan_g1_scope_amend(
        release,
        work_id="W-001",
        delta=delta,
        authorization=wrong_delta,
        release_oid=wrong_delta.release_oid,
        process_oid=wrong_delta.process_oid,
    )
    assert "G1_SCOPE_AMEND_DELTA_MISMATCH" in plan.blockers


def test_partial_transaction_blocks_until_native_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release, process, process_oid = _fixture(tmp_path)
    delta = _delta()
    authorization = _authorization(release, process, process_oid, delta)
    plan = plan_g1_scope_amend(
        release,
        work_id="W-001",
        delta=delta,
        authorization=authorization,
        release_oid=authorization.release_oid,
        process_oid=authorization.process_oid,
    )
    from meta_flow.work import init_transaction

    original_replace = init_transaction._replace_target
    calls = 0

    def flaky_replace(path: Path, value: bytes | None) -> None:
        nonlocal calls
        calls += 1
        if calls in {3, 4}:
            raise OSError("injected write/recovery failure")
        original_replace(path, value)

    monkeypatch.setattr(init_transaction, "_replace_target", flaky_replace)
    result = apply_g1_scope_amend(
        plan,
        expected_plan_digest=plan.plan_digest,
        current_authorization=authorization,
        release_oid=authorization.release_oid,
        process_oid=authorization.process_oid,
    )
    assert result["decision"] == "PARTIAL"
    assert inspect_g1_scope_amend(process, work_id="W-001")["decision"] == "BLOCKED"

    monkeypatch.setattr(init_transaction, "_replace_target", original_replace)
    recovery = recover_g1_scope_amend(
        process,
        transaction_id=str(result["transaction_id"]),
        expected_plan_digest=plan.plan_digest,
        release_oid=authorization.release_oid,
        process_oid=authorization.process_oid,
    )
    assert recovery["decision"] == "RECOVERED"
    assert inspect_g1_scope_amend(process, work_id="W-001")["decision"] == "PASS"


def test_non_additive_payload_shape_is_rejected() -> None:
    with pytest.raises(ValueError, match="G1_SCOPE_DELTA_FIELDS_INVALID"):
        G1ScopeDeltaV1.from_mapping(
            {
                "schema_version": 1,
                "add_reads": [],
                "add_writes": [],
                "add_checks": [],
                "remove_writes": ["src/existing.py"],
                "reason": "attempt narrowing",
            }
        )


def test_public_scope_amend_cli_defaults_to_zero_write_plan(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release, process, process_oid = _fixture(tmp_path)
    delta = _delta()
    authorization = _authorization(release, process, process_oid, delta)
    delta_path = tmp_path / "delta.json"
    authorization_path = tmp_path / "authorization.json"
    delta_path.write_text(json.dumps(delta.as_dict()), encoding="utf-8")
    authorization_path.write_text(
        json.dumps(authorization.as_dict()), encoding="utf-8"
    )

    exit_code = scope_amend_main(
        [
            "--project-root",
            str(release),
            "--work-id",
            "W-001",
            "--delta",
            str(delta_path),
            "--authorization",
            str(authorization_path),
        ]
    )

    assert exit_code == 0
    rendered = json.loads(capsys.readouterr().out)
    assert rendered["decision"] == "READY"
    assert rendered["mutation_count"] == 0
    assert not (process / "works/W-001/revisions/R2.json").exists()


def test_public_scope_amend_cli_routes_g2_v2_without_mutation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release, process, _process_oid = _fixture(
        tmp_path,
        status="planned",
        g2_current_cr=True,
    )
    checkpoint_ref, checkpoint_digest, event, event_digest = _install_g2_approval(
        process
    )
    process_oid = _git(process, "rev-parse", "HEAD")
    delta = _g2_delta()
    authorization = _g2_authorization(
        release,
        process,
        process_oid,
        delta,
        checkpoint_ref,
        checkpoint_digest,
        event,
        event_digest,
    )
    delta_path = tmp_path / "g2-delta.json"
    authorization_path = tmp_path / "g2-authorization.json"
    delta_path.write_text(json.dumps(delta.as_dict()), encoding="utf-8")
    authorization_path.write_text(
        json.dumps(authorization.as_dict()),
        encoding="utf-8",
    )

    exit_code = scope_amend_main(
        [
            "--project-root",
            str(release),
            "--work-id",
            "W-001",
            "--delta",
            str(delta_path),
            "--authorization",
            str(authorization_path),
        ]
    )

    assert exit_code == 0
    rendered = json.loads(capsys.readouterr().out)
    assert rendered["decision"] == "READY"
    assert rendered["kind"] == "G2CurrentCRScopeAmendPlanV2"
    assert rendered["mutation_count"] == 0
    assert not (process / "works/W-001/revisions/R2.json").exists()


def test_public_init_preflight_cli_renders_zero_write_decision(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = tmp_path / "preflight.json"
    input_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "candidate": {
                    "work_id": "W-001",
                    "business_reads": ["docs/input.md"],
                    "business_writes": ["src/output.py"],
                    "candidate_digest": "a" * 64,
                    "existing_digest": "b" * 64,
                },
                "context": {
                    "granted_business_reads": ["docs/input.md"],
                    "granted_business_writes": ["src/output.py"],
                },
            }
        ),
        encoding="utf-8",
    )

    assert init_preflight_main(["--input", str(input_path)]) == 0
    rendered = json.loads(capsys.readouterr().out)
    assert rendered["decision"] == "READY"
    assert rendered["mutation_count"] == 0
