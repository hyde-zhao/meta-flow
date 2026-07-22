from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from meta_flow.project import onboarding
from meta_flow.project.onboarding import (
    ProjectInitApplyError,
    ProjectInitRequest,
    apply_project_init,
    check_independent_process_route,
    plan_project_init,
)
from meta_flow.project.onboarding_contract import (
    AUTHORIZATION_KIND,
    AUTHORIZATION_SOURCE,
    PLAN_FIELDS,
    OnboardingAuthorization,
    canonical_digest,
    load_transaction_manifest,
    transaction_manifest_path,
    validate_plan_envelope,
)
from meta_flow.project.recovery import (
    RecoveryRequest,
    apply_recovery,
    plan_recovery,
)
from meta_flow.project.recovery import (
    main as recovery_main,
)


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def init_release(tmp_path: Path) -> Path:
    release = tmp_path / "release"
    release.mkdir()
    git(release, "init", "-b", "main")
    (release / "README.md").write_text("demo\n", encoding="utf-8")
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
    return release


def authorize(plan, authorization_id: str) -> OnboardingAuthorization:
    payload = plan.as_dict()
    return OnboardingAuthorization(
        schema_version=1,
        authorization_id=authorization_id,
        authorization_source=AUTHORIZATION_SOURCE,
        authorization_kind=AUTHORIZATION_KIND,
        operation=payload["operation"],
        decision_ref=payload["decision_ref"],
        project_id=payload["project_id"],
        plan_digest=payload["plan_digest"],
        expected_oids=payload["base_oids"],
        expires_at="2099-01-01T00:00:00+00:00",
    )


def create_process_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    authorization_id: str = "init-partial",
) -> tuple[Path, Path]:
    release = init_release(tmp_path)
    plan = plan_project_init(ProjectInitRequest(release, "demo", "Demo"))
    original = onboarding._write_yaml_create_only

    def fail_binding(path: Path, payload: dict[str, object]) -> None:
        if path.as_posix().endswith(".meta-flow/workspace.yaml"):
            raise OSError("fixture binding failure")
        original(path, payload)

    with monkeypatch.context() as scoped:
        scoped.setattr(onboarding, "_write_yaml_create_only", fail_binding)
        with pytest.raises(ProjectInitApplyError) as raised:
            apply_project_init(plan, authorize(plan, authorization_id))
    assert raised.value.receipt.decision == "PARTIAL"
    process = tmp_path / "demo-process"
    assert (process / "PROJECT.yaml").is_file()
    assert (process / ".meta-flow-process.yaml").is_file()
    assert not (release / ".meta-flow/workspace.yaml").exists()
    return release, process


def test_inspect_and_resume_complete_process_partial_without_cross_repo_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release, process = create_process_partial(tmp_path, monkeypatch)
    manifest = load_transaction_manifest(release, "init-partial")

    assert manifest["state"] == "process_partial"
    assert str(tmp_path) not in json.dumps(manifest, ensure_ascii=False)

    inspect_plan = plan_recovery(RecoveryRequest(release, "init-partial", "inspect"))
    inspected = apply_recovery(inspect_plan)
    assert inspect_plan.envelope["decision"] == "READY"
    assert len(inspect_plan.envelope) == 12
    assert inspect_plan.envelope["actions"]
    for action in inspect_plan.envelope["actions"]:
        assert {
            "side",
            "state",
            "target_ref",
            "kind",
            "ownership",
            "outcome",
            "before_digest",
            "after_digest",
            "digest_matches",
            "allowed_next_actions",
            "blocked_reason",
        }.issubset(action)
        assert action["expected_effect"].startswith("next-action=")
    assert inspected.decision == "NOOP"
    assert inspected.mutation_count == 0

    resume_plan = plan_recovery(RecoveryRequest(release, "init-partial", "resume"))
    resumed = apply_recovery(resume_plan, authorize(resume_plan, "recover-resume"))

    assert resumed.decision == "PASS"
    assert check_independent_process_route(release).ok
    assert not (release / "process").exists()
    assert (process / "PROJECT.yaml").is_file()
    old = load_transaction_manifest(release, "init-partial")
    assert old["state"] == "abandoned"
    assert old["resumed_by"] == "recover-resume"


def test_snapshot_seeded_init_resume_requires_same_source_oid_and_project_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "snapshot-process"
    source.mkdir()
    git(source, "init", "-b", "main")
    (source / "PROJECT.yaml").write_text(
        "schema_version: 1\nproject_id: demo\nname: Demo\nstatus: active\n",
        encoding="utf-8",
    )
    git(source, "add", "PROJECT.yaml")
    git(
        source,
        "-c",
        "user.name=Meta Flow Test",
        "-c",
        "user.email=meta-flow@example.invalid",
        "commit",
        "-m",
        "snapshot",
    )
    release = init_release(tmp_path)
    init_plan = plan_project_init(
        ProjectInitRequest(
            release,
            "demo",
            "Demo",
            source_process_root=source,
        )
    )
    original = onboarding._write_yaml_create_only

    def fail_binding(path: Path, payload: dict[str, object]) -> None:
        if path.as_posix().endswith(".meta-flow/workspace.yaml"):
            raise OSError("fixture binding failure")
        original(path, payload)

    with monkeypatch.context() as scoped:
        scoped.setattr(onboarding, "_write_yaml_create_only", fail_binding)
        with pytest.raises(ProjectInitApplyError):
            apply_project_init(init_plan, authorize(init_plan, "seed-partial"))

    without_source = plan_recovery(RecoveryRequest(release, "seed-partial", "resume"))
    assert without_source.blocked
    assert "resume_plan_invalid" in {
        item["code"] for item in without_source.envelope["conflicts"]
    }

    resume = plan_recovery(
        RecoveryRequest(
            release,
            "seed-partial",
            "resume",
            source_process_root=source,
        )
    )
    assert not resume.blocked
    receipt = apply_recovery(resume, authorize(resume, "seed-resume"))
    assert receipt.decision == "PASS"
    assert check_independent_process_route(release).ok
    assert (tmp_path / "demo-process" / "PROJECT.yaml").read_bytes() == (
        source / "PROJECT.yaml"
    ).read_bytes()


def test_cleanup_deletes_only_unchanged_transaction_owned_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release, process = create_process_partial(tmp_path, monkeypatch)
    cleanup_plan = plan_recovery(RecoveryRequest(release, "init-partial", "cleanup"))

    assert cleanup_plan.envelope["decision"] == "READY"
    assert {item["target_ref"] for item in cleanup_plan.envelope["actions"]} == {
        "process/PROJECT.yaml",
        "process/.meta-flow-process.yaml",
    }
    receipt = apply_recovery(cleanup_plan, authorize(cleanup_plan, "recover-cleanup"))

    assert receipt.decision == "PASS"
    assert not (process / "PROJECT.yaml").exists()
    assert not (process / ".meta-flow-process.yaml").exists()
    assert (process / ".git").is_dir()
    assert load_transaction_manifest(release, "init-partial")["state"] == "abandoned"


def test_cleanup_digest_mismatch_blocks_without_deleting_user_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release, process = create_process_partial(tmp_path, monkeypatch)
    project = process / "PROJECT.yaml"
    project.write_text(project.read_text(encoding="utf-8") + "objective: user-change\n", encoding="utf-8")

    cleanup_plan = plan_recovery(RecoveryRequest(release, "init-partial", "cleanup"))

    assert cleanup_plan.blocked
    assert "cleanup_digest_mismatch" in {
        item["code"] for item in cleanup_plan.envelope["conflicts"]
    }
    assert "user-change" in project.read_text(encoding="utf-8")


def test_abandon_changes_only_transaction_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release, process = create_process_partial(tmp_path, monkeypatch)
    project_before = (process / "PROJECT.yaml").read_bytes()
    plan = plan_recovery(RecoveryRequest(release, "init-partial", "abandon"))

    receipt = apply_recovery(plan, authorize(plan, "recover-abandon"))

    assert receipt.decision == "PASS"
    assert (process / "PROJECT.yaml").read_bytes() == project_before
    assert load_transaction_manifest(release, "init-partial")["state"] == "abandoned"


@pytest.mark.parametrize("integrity_case", ["missing", "corrupt-json", "missing-fields"])
def test_inspect_missing_or_corrupt_manifest_fails_closed_without_guessing_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    integrity_case: str,
) -> None:
    release, process = create_process_partial(tmp_path, monkeypatch)
    manifest_path = transaction_manifest_path(release, "init-partial")
    if integrity_case == "missing":
        manifest_path.unlink()
    elif integrity_case == "corrupt-json":
        manifest_path.write_text("{not-json\n", encoding="utf-8")
    else:
        manifest_path.write_text("{}\n", encoding="utf-8")

    control_root = release / ".git" / "meta-flow"

    def control_snapshot() -> dict[str, bytes]:
        return {
            path.relative_to(control_root).as_posix(): path.read_bytes()
            for path in control_root.rglob("*")
            if path.is_file()
        }

    controls_before = control_snapshot()
    release_status_before = git(release, "status", "--porcelain=v1")
    process_status_before = git(process, "status", "--porcelain=v1")

    plan = plan_recovery(RecoveryRequest(release, "init-partial", "inspect"))

    assert plan.blocked
    assert set(plan.envelope) == set(PLAN_FIELDS)
    validate_plan_envelope(plan.envelope)
    assert plan.envelope["plan_digest"] == canonical_digest(
        {key: plan.envelope[key] for key in PLAN_FIELDS[:-1]}
    )
    assert plan.envelope["actions"] == []
    assert {item["code"] for item in plan.envelope["conflicts"]} == {
        f"transaction_manifest_{'missing' if integrity_case == 'missing' else 'invalid'}"
    }
    assert plan.envelope["project_id"] == "unresolved"
    assert plan.envelope["process_repo"]["relative_path"] == "__meta_flow_unresolved_process__"
    assert plan.envelope["process_repo"]["observation"] == {"state": "absent", "oid": ""}
    assert all(
        plan.envelope["rollback_plan"][key] == []
        for key in (
            "release_actions",
            "process_actions",
            "resume_actions",
            "cleanup_actions",
            "manual_only_actions",
        )
    )

    exit_code = recovery_main(
        [
            "--project-root",
            str(release),
            "--authorization-id",
            "init-partial",
            "--action",
            "inspect",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert payload == plan.as_dict()
    assert set(payload) == set(PLAN_FIELDS)
    assert control_snapshot() == controls_before
    assert git(release, "status", "--porcelain=v1") == release_status_before
    assert git(process, "status", "--porcelain=v1") == process_status_before


def test_inspect_missing_manifest_uses_healthy_binding_observations(
    tmp_path: Path,
) -> None:
    release = init_release(tmp_path)
    init_plan = plan_project_init(ProjectInitRequest(release, "demo", "Demo"))
    init_receipt = apply_project_init(init_plan, authorize(init_plan, "init-complete"))
    assert init_receipt.decision == "PASS"
    process = tmp_path / "demo-process"
    transaction_manifest_path(release, "init-complete").unlink()

    plan = plan_recovery(RecoveryRequest(release, "init-complete", "inspect"))

    assert plan.blocked
    assert set(plan.envelope) == set(PLAN_FIELDS)
    validate_plan_envelope(plan.envelope)
    assert plan.envelope["project_id"] == "demo"
    assert plan.process_root == process.resolve()
    assert plan.envelope["process_repo"]["relative_path"] == process.name
    assert plan.envelope["process_repo"]["observation"] == {"state": "unborn", "oid": ""}
    assert plan.envelope["actions"] == []
    assert {item["code"] for item in plan.envelope["conflicts"]} == {
        "transaction_manifest_missing"
    }


def test_inspect_manifest_action_digest_drift_returns_blocked_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release, process = create_process_partial(tmp_path, monkeypatch)
    project = process / "PROJECT.yaml"
    project.write_text(project.read_text(encoding="utf-8") + "objective: drift\n", encoding="utf-8")

    plan = plan_recovery(RecoveryRequest(release, "init-partial", "inspect"))

    assert plan.blocked
    assert len(plan.envelope) == 12
    assert "manifest_action_integrity" in {
        item["code"] for item in plan.envelope["conflicts"]
    }
    project_action = next(
        item for item in plan.envelope["actions"] if item["target_ref"] == "process/PROJECT.yaml"
    )
    assert project_action["digest_matches"] is False
    assert project_action["allowed_next_actions"] == ["abandon"]
