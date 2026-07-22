from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from meta_flow.project.onboarding_contract import (
    AUTHORIZATION_KIND,
    AUTHORIZATION_SOURCE,
    PLAN_FIELDS,
    OnboardingAuthorization,
    OnboardingContractError,
    assert_expected_observations,
    build_plan_envelope,
    claim_authorization,
    observe_repository,
    repository_descriptor,
    validate_authorization,
    validate_plan_envelope,
)


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def init_repo(root: Path, *, commit: bool) -> Path:
    root.mkdir()
    git(root, "init", "-b", "main")
    if commit:
        (root / "README.md").write_text("demo\n", encoding="utf-8")
        git(root, "add", "README.md")
        git(
            root,
            "-c",
            "user.name=Meta Flow Test",
            "-c",
            "user.email=meta-flow@example.invalid",
            "commit",
            "-m",
            "initial",
        )
    return root


def make_plan(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    release = init_repo(tmp_path / "release", commit=True)
    process = tmp_path / "demo-process"
    release_repo = repository_descriptor(release, role="release", workspace_parent=tmp_path)
    process_repo = repository_descriptor(process, role="process", workspace_parent=tmp_path)
    plan = build_plan_envelope(
        operation="project.init",
        decision="READY",
        decision_ref="decisions/DQ-001.json",
        project_id="demo",
        release_repo=release_repo,
        process_repo=process_repo,
        base_oids={
            "release": release_repo["observation"],
            "process": process_repo["observation"],
        },
        actions=[
            {
                "action_id": "INIT-001",
                "side": "process",
                "kind": "create",
                "target_ref": "process/PROJECT.yaml",
                "ownership": "project.init",
                "precondition": "absent",
                "expected_effect": "create minimal project",
            }
        ],
        conflicts=[],
        rollback_plan={
            "strategy": "explicit-non-atomic-recovery",
            "transaction_ref": "meta-flow/project-onboarding/transactions/authorization-id/manifest.json",
            "release_actions": [],
            "process_actions": ["process/PROJECT.yaml"],
            "resume_actions": ["process/PROJECT.yaml"],
            "cleanup_actions": ["process/PROJECT.yaml"],
            "manual_only_actions": [],
        },
    )
    return release, process, plan


def authorize(plan: dict[str, object], authorization_id: str = "auth-001") -> OnboardingAuthorization:
    return OnboardingAuthorization(
        schema_version=1,
        authorization_id=authorization_id,
        authorization_source=AUTHORIZATION_SOURCE,
        authorization_kind=AUTHORIZATION_KIND,
        operation=str(plan["operation"]),
        decision_ref=str(plan["decision_ref"]),
        project_id=str(plan["project_id"]),
        plan_digest=str(plan["plan_digest"]),
        expected_oids=dict(plan["base_oids"]),
        expires_at="2099-01-01T00:00:00+00:00",
    )


def test_envelope_has_exact_twelve_fields_and_canonical_digest(tmp_path: Path) -> None:
    _release, _process, plan = make_plan(tmp_path)

    assert tuple(plan) == PLAN_FIELDS
    assert len(plan) == 12
    validate_plan_envelope(plan)

    reordered = {key: plan[key] for key in reversed(PLAN_FIELDS)}
    validate_plan_envelope(reordered)
    unknown = dict(plan)
    unknown["mutation_count"] = 0
    with pytest.raises(OnboardingContractError, match="12 fields"):
        validate_plan_envelope(unknown)


def test_repository_observation_covers_absent_unborn_and_commit(tmp_path: Path) -> None:
    absent = tmp_path / "absent"
    unborn = init_repo(tmp_path / "unborn", commit=False)
    committed = init_repo(tmp_path / "committed", commit=True)

    assert observe_repository(absent) == {"state": "absent", "oid": ""}
    assert observe_repository(unborn) == {"state": "unborn", "oid": ""}
    assert observe_repository(committed) == {
        "state": "commit",
        "oid": git(committed, "rev-parse", "HEAD"),
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("operation", "project.unknown"),
        ("decision_ref", "/tmp/decision.json"),
        ("decision_ref", "decisions/../secret"),
        ("project_id", "bad/id"),
    ],
)
def test_envelope_rejects_unknown_operation_and_nonportable_refs(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    _release, _process, plan = make_plan(tmp_path)
    invalid = dict(plan)
    invalid[field] = value

    with pytest.raises(OnboardingContractError):
        validate_plan_envelope(invalid)


@pytest.mark.parametrize(
    "change",
    [
        {"operation": "project.recover"},
        {"decision_ref": "decisions/other.json"},
        {"project_id": "other"},
        {"plan_digest": "0" * 64},
        {"expected_oids": {"release": {"state": "absent", "oid": ""}, "process": {"state": "absent", "oid": ""}}},
        {"single_use": False},
        {"authorization_source": "implicit"},
        {"authorization_kind": "repository"},
    ],
)
def test_typed_authorization_binds_all_contract_fields(
    tmp_path: Path,
    change: dict[str, object],
) -> None:
    _release, _process, plan = make_plan(tmp_path)
    authorization = replace(authorize(plan), **change)

    with pytest.raises(OnboardingContractError):
        validate_authorization(plan, authorization)


def test_authorization_claim_is_exclusive_and_contains_no_process_absolute_path(tmp_path: Path) -> None:
    release, process, plan = make_plan(tmp_path)
    authorization = authorize(plan)

    claim = claim_authorization(release, plan, authorization)

    assert claim.is_file()
    assert str(process) not in claim.read_text(encoding="utf-8")
    with pytest.raises(OnboardingContractError, match="already consumed"):
        claim_authorization(release, plan, authorization)


def test_dry_run_records_both_release_and_process_oid_checkpoints(tmp_path: Path) -> None:
    release, process, plan = make_plan(tmp_path)

    assert plan["base_oids"] == {
        "release": observe_repository(release),
        "process": observe_repository(process),
    }


@pytest.mark.parametrize(
    ("side", "stage"),
    [
        ("release", "authorization-consume"),
        ("process", "authorization-consume"),
        ("release", "apply-final"),
        ("process", "apply-final"),
    ],
)
def test_each_authorization_and_apply_final_oid_checkpoint_blocks_drift(
    tmp_path: Path,
    side: str,
    stage: str,
) -> None:
    release, process, plan = make_plan(tmp_path)
    target = release if side == "release" else process
    if side == "process":
        init_repo(process, commit=False)
    (target / "changed.txt").write_text("changed\n", encoding="utf-8")
    git(target, "add", "changed.txt")
    git(
        target,
        "-c",
        "user.name=Meta Flow Test",
        "-c",
        "user.email=meta-flow@example.invalid",
        "commit",
        "-m",
        f"advance {side}",
    )

    with pytest.raises(OnboardingContractError, match=stage):
        assert_expected_observations(
            plan=plan,
            release_root=release,
            process_root=process,
            stage=stage,
        )
