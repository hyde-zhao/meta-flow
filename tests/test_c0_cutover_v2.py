from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from meta_flow.policies import c0_cutover
from meta_flow.project.onboarding import (
    ProjectInitRequest,
    apply_project_init,
    plan_project_init,
)
from meta_flow.project.onboarding_contract import (
    AUTHORIZATION_KIND,
    AUTHORIZATION_SOURCE,
    OnboardingAuthorization,
    canonical_digest,
)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@dataclass(frozen=True)
class _SemanticPlan:
    payload: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return dict(self.payload)


def _fixture(parent: Path) -> tuple[Path, Path, _SemanticPlan]:
    release = parent / "release"
    release.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=release,
        check=True,
        capture_output=True,
    )
    (release / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "README.md"],
        cwd=release,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Meta Flow Test",
            "-c",
            "user.email=meta-flow@example.invalid",
            "commit",
            "-m",
            "initial",
        ],
        cwd=release,
        check=True,
        capture_output=True,
    )
    init_plan = plan_project_init(
        ProjectInitRequest(release, "c0-v2", "C0 V2"),
    )
    init_payload = init_plan.as_dict()
    init_authorization = OnboardingAuthorization(
        schema_version=1,
        authorization_id=f"auth-{init_plan.plan_digest[:12]}",
        authorization_source=AUTHORIZATION_SOURCE,
        authorization_kind=AUTHORIZATION_KIND,
        operation=init_payload["operation"],
        decision_ref=init_payload["decision_ref"],
        project_id=init_payload["project_id"],
        plan_digest=init_plan.plan_digest,
        expected_oids=init_payload["base_oids"],
        expires_at="2099-01-01T00:00:00+00:00",
    )
    apply_project_init(init_plan, init_authorization)
    process = parent / "c0-v2-process"
    if not (process / ".git").exists():
        subprocess.run(
            ["git", "init", "-b", "main"],
            cwd=process,
            check=True,
            capture_output=True,
        )
    (process / "state").mkdir(parents=True, exist_ok=True)
    (process / "checks").mkdir(parents=True, exist_ok=True)
    (process / "state" / "CHECKPOINT-LEDGER.ndjson").write_text(
        "",
        encoding="utf-8",
    )
    (process / "state" / "GATE-LEDGER.ndjson").write_text("", encoding="utf-8")
    development_plan = {
        "schema_version": 1,
        "waves": [
            {
                "stories": [
                    {
                        "story_id": f"STORY-CR063-S0{index}",
                        "status": "lld-ready",
                        "lld_gate": {"status": "ready-for-review"},
                        "dev_gate": {
                            "lld_confirmed": False,
                            "cp5_confirmed": False,
                            "dependencies_satisfied": False,
                            "file_conflict_free": False,
                            "implementation_authorized": False,
                        },
                    }
                    for index in range(1, 6)
                ]
            }
        ],
    }
    (process / "DEVELOPMENT-PLAN.yaml").write_text(
        json.dumps(
            development_plan,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    if not (process / "PROJECT.yaml").is_file():
        (process / "PROJECT.yaml").write_text(
            "schema_version: 1\nproject_id: c0-v2\n",
            encoding="utf-8",
        )
    subprocess.run(
        ["git", "add", "."],
        cwd=process,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Meta Flow Test",
            "-c",
            "user.email=meta-flow@example.invalid",
            "commit",
            "-m",
            "process fixture",
        ],
        cwd=process,
        check=True,
        capture_output=True,
    )
    release_oid = _git(release, "rev-parse", "HEAD")
    process_oid = _git(process, "rev-parse", "HEAD")
    allowlist = [
        "process/DEVELOPMENT-PLAN.yaml",
        "process/checks/C0-CR-063-PROJECTOR-CUTOVER.result.json",
        "process/checks/C0-CR-063-PROJECTOR-CUTOVER.summary.md",
        "process/state/CHECKPOINT-LEDGER.ndjson",
        "process/state/GATE-LEDGER.ndjson",
    ]
    seed: dict[str, object] = {
        "schema_version": 1,
        "kind": "C0ResultV1",
        "decision": "READY",
        "dry_run": True,
        "mutation_count": 0,
        "cr_id": "CR-063",
        "release_oid": release_oid,
        "process_oid": process_oid,
        "scope_digest": "a" * 64,
        "mutation_allowlist": allowlist,
    }
    seed["plan_digest"] = canonical_digest(seed)
    return release, process, _SemanticPlan(seed)


def _authorization(
    plan: c0_cutover.C0CutoverPlanV2,
    *,
    authorization_id: str,
) -> c0_cutover.C0CutoverAuthorizationV2:
    payload = plan.as_dict()
    return c0_cutover.C0CutoverAuthorizationV2.from_dict(
        {
            "schema_version": 2,
            "authorization_id": authorization_id,
            "authorization_source": c0_cutover.C0_AUTHORIZATION_SOURCE,
            "authorization_kind": c0_cutover.C0_AUTHORIZATION_KIND,
            "operation": c0_cutover.C0_CUTOVER_OPERATION,
            "cr_id": plan.cr_id,
            "work_id": plan.work_id,
            "expected_release_oid": plan.release_oid,
            "expected_process_oid": plan.process_oid,
            "scope_digest": plan.scope_digest,
            "process_dirty_path_digest": plan.process_dirty_path_digest,
            "plan_digest": payload["plan_digest"],
            "mutation_allowlist": list(plan.mutation_allowlist),
            "expires_at": "2099-01-01T00:00:00+00:00",
            "single_use": True,
        }
    )


def test_c0_v2_plan_freezes_history_and_five_target_digests(
    tmp_path: Path,
) -> None:
    release, _process, semantic = _fixture(tmp_path)
    first = c0_cutover.build_c0_cutover_plan(
        project_root=release,
        work_id="WORK-063",
        semantic_plan=semantic,
    )
    second = c0_cutover.build_c0_cutover_plan(
        project_root=release,
        work_id="WORK-063",
        semantic_plan=semantic,
    )

    assert first.decision == "READY"
    assert first.as_dict() == second.as_dict()
    assert first.checkpoint_history_count == 0
    assert first.gate_history_count == 0
    assert len(first.targets) == 5
    assert first.as_dict()["planned_mutation_count"] == 5
    assert first.as_dict()["actual_mutation_count"] == 0
    assert [target["carry_mode"] for target in first.as_dict()["targets"]] == [
        "replace",
        "create",
        "create",
        "replace",
        "replace",
    ]


def test_c0_v2_apply_is_transactional_and_receipt_is_idempotent(
    tmp_path: Path,
) -> None:
    release, process, semantic = _fixture(tmp_path)
    plan = c0_cutover.build_c0_cutover_plan(
        project_root=release,
        work_id="WORK-063",
        semantic_plan=semantic,
    )
    authorization = _authorization(
        plan,
        authorization_id="AUTH-CR063-C0-V2-001",
    )

    first = c0_cutover.apply_c0_cutover(
        project_root=release,
        work_id="WORK-063",
        expected_plan_digest=plan.as_dict()["plan_digest"],
        authorization=authorization,
        semantic_plan_factory=lambda: semantic,
    )
    second = c0_cutover.apply_c0_cutover(
        project_root=release,
        work_id="WORK-063",
        expected_plan_digest=plan.as_dict()["plan_digest"],
        authorization=None,
        semantic_plan_factory=lambda: (_ for _ in ()).throw(
            AssertionError("NO_CHANGE must not rebuild semantic plan")
        ),
    )

    assert first["status"] == "PASS"
    assert first["mutation_count"] == 5
    assert second["status"] == "NO_CHANGE"
    result = json.loads(
        (process / "checks" / "C0-CR-063-PROJECTOR-CUTOVER.result.json").read_text(encoding="utf-8")
    )
    assert result["kind"] == c0_cutover.C0_RESULT_KIND
    assert result["cutover_revision"] == 1
    assert (
        len(
            (process / "state" / "CHECKPOINT-LEDGER.ndjson")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        == 1
    )


def test_c0_v2_failure_restores_every_preimage(tmp_path: Path) -> None:
    release, process, semantic = _fixture(tmp_path)
    plan = c0_cutover.build_c0_cutover_plan(
        project_root=release,
        work_id="WORK-063",
        semantic_plan=semantic,
    )
    authorization = _authorization(
        plan,
        authorization_id="AUTH-CR063-C0-V2-ROLLBACK",
    )
    before = {
        target.logical_ref: (
            target.path.read_text(encoding="utf-8") if target.path.is_file() else None
        )
        for target in plan.targets
    }

    result = c0_cutover.apply_c0_cutover(
        project_root=release,
        work_id="WORK-063",
        expected_plan_digest=plan.as_dict()["plan_digest"],
        authorization=authorization,
        semantic_plan_factory=lambda: semantic,
        _fail_after_replace=3,
    )

    assert result["status"] == "RECOVERED"
    for target in plan.targets:
        actual = target.path.read_text(encoding="utf-8") if target.path.is_file() else None
        assert actual == before[target.logical_ref]
    assert not (process / "checks" / "C0-CR-063-PROJECTOR-CUTOVER.result.json").exists()


def test_c0_v2_receipt_failure_restores_all_five_targets(
    tmp_path: Path,
) -> None:
    release, process, semantic = _fixture(tmp_path)
    plan = c0_cutover.build_c0_cutover_plan(
        project_root=release,
        work_id="WORK-063",
        semantic_plan=semantic,
    )
    authorization = _authorization(
        plan,
        authorization_id="AUTH-CR063-C0-V2-RECEIPT",
    )
    before = {
        target.logical_ref: (
            target.path.read_text(encoding="utf-8") if target.path.is_file() else None
        )
        for target in plan.targets
    }

    result = c0_cutover.apply_c0_cutover(
        project_root=release,
        work_id="WORK-063",
        expected_plan_digest=plan.as_dict()["plan_digest"],
        authorization=authorization,
        semantic_plan_factory=lambda: semantic,
        _fail_before_receipt=True,
    )

    assert result["status"] == "RECOVERED"
    assert result["mutation_count"] == 5
    assert result["durable_leaf_refs"] == []
    for target in plan.targets:
        actual = target.path.read_text(encoding="utf-8") if target.path.is_file() else None
        assert actual == before[target.logical_ref]
    assert not (process / "checks" / "C0-CR-063-PROJECTOR-CUTOVER.result.json").exists()


def test_c0_v2_partial_reports_durable_leaf_and_recovery_contract(
    tmp_path: Path,
) -> None:
    release, _process, semantic = _fixture(tmp_path)
    plan = c0_cutover.build_c0_cutover_plan(
        project_root=release,
        work_id="WORK-063",
        semantic_plan=semantic,
    )
    authorization = _authorization(
        plan,
        authorization_id="AUTH-CR063-C0-V2-PARTIAL",
    )

    result = c0_cutover.apply_c0_cutover(
        project_root=release,
        work_id="WORK-063",
        expected_plan_digest=plan.as_dict()["plan_digest"],
        authorization=authorization,
        semantic_plan_factory=lambda: semantic,
        _fail_after_replace=2,
        _rollback_failure_ref=plan.targets[0].logical_ref,
    )

    assert result["status"] == "PARTIAL"
    assert result["durable_leaf_refs"] == [plan.targets[0].logical_ref]
    assert result["recovery_contract"]["retry_allowed_after"] == (
        "all target before_digest restored"
    )


def test_c0_v2_nonempty_history_is_fail_closed(tmp_path: Path) -> None:
    release, process, semantic = _fixture(tmp_path)
    (process / "state" / "CHECKPOINT-LEDGER.ndjson").write_text(
        json.dumps(
            {
                "event_id": "existing",
                "event_type": "checkpoint_result",
                "checkpoint": "C0",
                "decision": "PASS",
                "result_ref": ("process/checks/C0-CR-063-PROJECTOR-CUTOVER.result.json"),
                "cr_id": "CR-063",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    plan = c0_cutover.build_c0_cutover_plan(
        project_root=release,
        work_id="WORK-063",
        semantic_plan=semantic,
    )

    assert plan.decision == "BLOCKED"
    assert "C0_V2_FIRST_ACTIVATION_HISTORY_MUST_BE_EMPTY" in plan.blockers
    assert plan.targets == ()
