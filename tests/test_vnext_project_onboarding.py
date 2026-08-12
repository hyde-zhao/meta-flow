from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict
from pathlib import Path

import pytest

from meta_flow import cli
from meta_flow.project import onboarding
from meta_flow.project.model import load_project
from meta_flow.project.onboarding import (
    LAYOUT_VERSION,
    PROCESS_LINK_MODE_RELATIVE_SYMLINK,
    PROCESS_METADATA_REL,
    ROUTE_MODE_RELATIVE_SYMLINK,
    ROUTE_MODE_SIBLING_BINDING,
    WORKSPACE_BINDING_REL,
    ProjectInitApplyError,
    ProjectInitRequest,
    apply_project_init,
    check_independent_process_route,
    init_main,
    plan_project_init,
    resolve_process_repo_root,
    status_main,
)
from meta_flow.project.onboarding_contract import (
    AUTHORIZATION_KIND,
    AUTHORIZATION_SOURCE,
    PLAN_FIELDS,
    OnboardingAuthorization,
    load_transaction_manifest,
)
from meta_flow.project.process_route import resolve_ref_main
from meta_flow.project.scale import dump_yaml, load_yaml_object


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def init_release(root: Path, *, name: str = "release") -> Path:
    release = root / name
    release.mkdir(parents=True)
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
    return release


def init_source_snapshot(root: Path) -> Path:
    source = root / "snapshot-process"
    source.mkdir(parents=True)
    git(source, "init", "-b", "main")
    (source / "PROJECT.yaml").write_text(
        "schema_version: 1\n"
        "project_id: demo\n"
        "name: Demo Project\n"
        "objective: 已有项目当前有效治理快照\n"
        "status: active\n"
        "active_work_refs:\n"
        "  - works/W-001/WORK.yaml\n",
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
        "current snapshot",
    )
    return source


def common_dir(root: Path) -> Path:
    value = git(root, "rev-parse", "--git-common-dir")
    path = Path(value)
    return (root / path).resolve() if not path.is_absolute() else path.resolve()


def request_for(
    release: Path,
    *,
    project_id: str = "demo",
    process_link_mode: str = "none",
) -> ProjectInitRequest:
    return ProjectInitRequest(
        project_root=release,
        project_id=project_id,
        project_name="Demo Project",
        process_link_mode=process_link_mode,
    )


def authorize(plan, authorization_id: str | None = None) -> OnboardingAuthorization:
    payload = plan.as_dict()
    return OnboardingAuthorization(
        schema_version=1,
        authorization_id=authorization_id or f"auth-{plan.plan_digest[:12]}",
        authorization_source=AUTHORIZATION_SOURCE,
        authorization_kind=AUTHORIZATION_KIND,
        operation=payload["operation"],
        decision_ref=payload["decision_ref"],
        project_id=payload["project_id"],
        plan_digest=payload["plan_digest"],
        expected_oids=payload["base_oids"],
        expires_at="2099-01-01T00:00:00+00:00",
    )


def apply_init(plan, authorization_id: str | None = None):
    return apply_project_init(plan, authorize(plan, authorization_id))


def test_dry_run_is_deterministic_and_has_zero_mutation(tmp_path: Path) -> None:
    release = init_release(tmp_path)
    request = request_for(release)

    first = plan_project_init(request)
    second = plan_project_init(request)

    assert not first.blocked
    assert first.plan_digest == second.plan_digest
    assert tuple(first.as_dict()) == PLAN_FIELDS
    assert not (tmp_path / "demo-process").exists()
    assert not (release / "process").exists()
    assert not (release / WORKSPACE_BINDING_REL).exists()


def test_apply_creates_binding_only_independent_repo_and_minimal_project(tmp_path: Path) -> None:
    release = init_release(tmp_path)
    before_oid = git(release, "rev-parse", "HEAD")
    plan = plan_project_init(request_for(release))

    receipt = apply_init(plan)

    process_repo = tmp_path / "demo-process"
    assert receipt.decision == "PASS"
    assert receipt.release_oid_before == before_oid
    assert receipt.process_oid_after == ""
    assert git(process_repo, "branch", "--show-current") == "main"
    assert common_dir(release) != common_dir(process_repo)
    assert not (release / "process").exists()
    assert load_project(process_repo).as_dict() == {
        "schema_version": 1,
        "project_id": "demo",
        "name": "Demo Project",
        "status": "active",
    }
    assert not (process_repo / "docs").exists()
    assert not (process_repo / "phases").exists()
    assert not (process_repo / "works").exists()
    assert "process" not in git(release, "status", "--short")
    assert git(release, "rev-parse", "HEAD") == before_oid
    assert git(process_repo, "remote") == ""
    assert git(process_repo, "tag") == ""

    health = check_independent_process_route(release)
    assert health.ok
    assert health.status == "healthy"
    assert health.route_mode == ROUTE_MODE_SIBLING_BINDING
    assert health.link_text == ""
    assert health.project_id == "demo"
    assert health.process_repo_root == process_repo.resolve()


def test_existing_project_init_seed_binds_source_oid_digest_and_original_bytes(
    tmp_path: Path,
) -> None:
    release = init_release(tmp_path)
    source = init_source_snapshot(tmp_path)
    request = ProjectInitRequest(
        release,
        "demo",
        "Demo Project",
        source_process_root=source,
    )
    plan = plan_project_init(request)

    assert not plan.blocked
    assert plan.envelope["base_oids"]["source_snapshot"] == {
        "state": "commit",
        "oid": git(source, "rev-parse", "HEAD"),
    }
    project_action = next(
        item for item in plan.envelope["actions"] if item["target_ref"] == "process/PROJECT.yaml"
    )
    assert project_action["source_ref"] == "source/PROJECT.yaml"
    assert project_action["source_digest"] == plan.source_project_digest

    receipt = apply_init(plan, "seed-init")
    process = tmp_path / "demo-process"
    assert receipt.decision == "PASS"
    assert (process / "PROJECT.yaml").read_bytes() == (source / "PROJECT.yaml").read_bytes()
    manifest = load_transaction_manifest(release, "seed-init")
    assert manifest["intent"] == {
        "project_name": "Demo Project",
        "process_repo_relative_path": "demo-process",
        "process_link_mode": "none",
        "source_ref": "source/PROJECT.yaml",
        "source_oid": git(source, "rev-parse", "HEAD"),
        "source_project_digest": plan.source_project_digest,
    }
    assert str(source) not in json.dumps(manifest, ensure_ascii=False)

    second = plan_project_init(request)
    assert second.envelope["decision"] == "NOOP"
    assert apply_project_init(second).decision == "NOOP"


@pytest.mark.parametrize("drift_stage", ["authorization-consume", "apply-final"])
def test_init_seed_source_oid_drift_at_authorization_stages_blocks_before_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift_stage: str,
) -> None:
    release = init_release(tmp_path)
    source = init_source_snapshot(tmp_path)
    request = ProjectInitRequest(
        release,
        "demo",
        "Demo Project",
        source_process_root=source,
    )
    plan = plan_project_init(request)
    original_assert = onboarding.assert_expected_observations
    drifted = False

    def inject_source_drift(*, stage: str, **kwargs) -> None:
        nonlocal drifted
        if stage == drift_stage and not drifted:
            drifted = True
            (source / "OID-DRIFT.txt").write_text(f"{stage}\n", encoding="utf-8")
            git(source, "add", "OID-DRIFT.txt")
            git(
                source,
                "-c",
                "user.name=Meta Flow Test",
                "-c",
                "user.email=meta-flow@example.invalid",
                "commit",
                "-m",
                f"drift at {stage}",
            )
        original_assert(stage=stage, **kwargs)

    monkeypatch.setattr(onboarding, "assert_expected_observations", inject_source_drift)

    with pytest.raises(ValueError, match=f"OID observation drift at {drift_stage}"):
        apply_init(plan, f"seed-{drift_stage}")

    assert not (tmp_path / "demo-process").exists()
    assert not (release / WORKSPACE_BINDING_REL).exists()


def test_relative_symlink_mode_is_legacy_only_and_blocked_by_project_init(tmp_path: Path) -> None:
    release = init_release(tmp_path)
    request = request_for(
        release,
        process_link_mode=PROCESS_LINK_MODE_RELATIVE_SYMLINK,
    )

    plan = plan_project_init(request)

    assert plan.blocked
    assert "invalid_process_link_mode" in {item.code for item in plan.conflicts}
    assert not (release / "process").exists()
    assert not (release / ".gitignore").exists()


@pytest.mark.parametrize("release_exists", [False, True])
def test_init_can_create_release_repo_from_missing_or_empty_directory(
    tmp_path: Path,
    release_exists: bool,
) -> None:
    release = tmp_path / "new-project"
    if release_exists:
        release.mkdir()
    request = ProjectInitRequest(
        project_root=release,
        project_id="new-project",
        project_name="New Project",
    )

    plan = plan_project_init(request)

    assert not plan.blocked
    assert not (release / ".git").exists()
    receipt = apply_init(plan)
    process_repo = tmp_path / "new-project-process"
    assert receipt.decision == "PASS"
    assert git(release, "branch", "--show-current") == "main"
    assert git(process_repo, "branch", "--show-current") == "main"
    assert common_dir(release) != common_dir(process_repo)
    assert check_independent_process_route(release).ok


def test_init_failure_after_release_bootstrap_records_release_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = tmp_path / "new-project"
    request = ProjectInitRequest(release, "new-project", "New Project")
    plan = plan_project_init(request)
    process = tmp_path / "new-project-process"
    original_mkdir = Path.mkdir

    def fail_process_mkdir(path: Path, *args, **kwargs):
        if path == process:
            raise OSError("fixture process directory failure")
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fail_process_mkdir)

    with pytest.raises(ProjectInitApplyError) as raised:
        apply_init(plan, "release-partial")

    assert raised.value.receipt.decision == "PARTIAL"
    assert (release / ".git").is_dir()
    assert not process.exists()
    manifest = load_transaction_manifest(release, "release-partial")
    assert manifest["state"] == "release_partial"


def test_init_rejects_nonempty_non_git_release_directory(tmp_path: Path) -> None:
    release = tmp_path / "not-a-repo"
    release.mkdir()
    (release / "user-file.txt").write_text("preserve\n", encoding="utf-8")

    plan = plan_project_init(request_for(release))

    assert plan.blocked
    assert "release_not_git_root" in {conflict.code for conflict in plan.conflicts}
    assert (release / "user-file.txt").read_text(encoding="utf-8") == "preserve\n"


def test_binding_and_process_metadata_are_portable_and_mutually_identified(tmp_path: Path) -> None:
    release = init_release(tmp_path)
    apply_init(plan_project_init(request_for(release)))
    process_repo = tmp_path / "demo-process"

    binding = load_yaml_object(release / WORKSPACE_BINDING_REL)
    process_metadata = load_yaml_object(process_repo / PROCESS_METADATA_REL)

    assert binding == {
        "schema_version": 1,
        "layout_version": LAYOUT_VERSION,
        "workflow_model": "vnext",
        "project_id": "demo",
        "repo_role": "release",
        "route_mode": ROUTE_MODE_SIBLING_BINDING,
        "process_repo": {
            "anchor": "workspace_parent",
            "relative_path": "demo-process",
        },
    }
    assert process_metadata["project_id"] == "demo"
    assert process_metadata["repo_role"] == "process"
    assert process_metadata["route_mode"] == ROUTE_MODE_SIBLING_BINDING
    assert process_metadata["release_repo"] == {
        "anchor": "workspace_parent",
        "relative_path": "release",
    }
    assert str(tmp_path) not in (release / WORKSPACE_BINDING_REL).read_text(encoding="utf-8")
    assert str(tmp_path) not in (process_repo / PROCESS_METADATA_REL).read_text(encoding="utf-8")


def test_valid_existing_initialization_is_idempotent_noop(tmp_path: Path) -> None:
    release = init_release(tmp_path)
    apply_init(plan_project_init(request_for(release)))

    second = plan_project_init(request_for(release))
    receipt = apply_project_init(second)

    assert not second.blocked
    assert {action.action for action in second.actions} == {"noop"}
    assert receipt.decision == "NOOP"
    assert receipt.mutation_count == 0
    assert receipt.created_paths == ()


def test_moving_workspace_parent_preserves_binding_and_health(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    release = init_release(bundle)
    apply_init(plan_project_init(request_for(release)))
    original_binding = (release / WORKSPACE_BINDING_REL).read_text(encoding="utf-8")

    moved = tmp_path / "moved-bundle"
    shutil.move(str(bundle), moved)
    moved_release = moved / "release"

    assert (moved_release / WORKSPACE_BINDING_REL).read_text(encoding="utf-8") == original_binding
    assert not (moved_release / "process").exists()
    assert check_independent_process_route(moved_release).ok


@pytest.mark.parametrize("conflict_kind", ["regular-process", "wrong-link"])
def test_existing_process_conflicts_fail_closed_without_mutation(tmp_path: Path, conflict_kind: str) -> None:
    release = init_release(tmp_path)
    if conflict_kind == "regular-process":
        (release / "process").mkdir()
    else:
        other = tmp_path / "other-process"
        other.mkdir()
        (release / "process").symlink_to("../other-process", target_is_directory=True)
    before_status = git(release, "status", "--short")

    plan = plan_project_init(request_for(release))

    assert plan.blocked
    assert not (tmp_path / "demo-process").exists()
    assert git(release, "status", "--short") == before_status


def test_non_sibling_process_repo_is_rejected(tmp_path: Path) -> None:
    release = init_release(tmp_path / "workspace")
    outside = tmp_path / "outside" / "demo-process"

    plan = plan_project_init(
        ProjectInitRequest(
            project_root=release,
            project_id="demo",
            project_name="Demo Project",
            process_repo_root=outside,
        )
    )

    assert plan.blocked
    assert "not_sibling" in {conflict.code for conflict in plan.conflicts}
    assert not outside.exists()


def test_existing_process_repo_owned_by_other_project_is_rejected(tmp_path: Path) -> None:
    first_release = init_release(tmp_path, name="first")
    process_root = tmp_path / "shared-process"
    first_request = ProjectInitRequest(first_release, "first", "First", process_root)
    apply_init(plan_project_init(first_request))
    second_release = init_release(tmp_path, name="second")

    second = plan_project_init(
        ProjectInitRequest(second_release, "second", "Second", process_root)
    )

    assert second.blocked
    codes = {conflict.code for conflict in second.conflicts}
    assert "project_identity_conflict" in codes or "metadata_conflict" in codes


def test_release_oid_drift_blocks_before_any_init_mutation(tmp_path: Path) -> None:
    release = init_release(tmp_path)
    plan = plan_project_init(request_for(release))
    (release / "changed.txt").write_text("changed\n", encoding="utf-8")
    git(release, "add", "changed.txt")
    git(
        release,
        "-c",
        "user.name=Meta Flow Test",
        "-c",
        "user.email=meta-flow@example.invalid",
        "commit",
        "-m",
        "advance",
    )

    with pytest.raises(ValueError, match="stale"):
        apply_init(plan)

    assert not (tmp_path / "demo-process").exists()
    assert not (release / WORKSPACE_BINDING_REL).exists()
    assert not (release / "process").exists()


def test_two_projects_are_physically_isolated_when_one_switches_branch(tmp_path: Path) -> None:
    release_a = init_release(tmp_path, name="A")
    release_b = init_release(tmp_path, name="B")
    apply_init(plan_project_init(request_for(release_a, project_id="A")))
    apply_init(plan_project_init(request_for(release_b, project_id="B")))
    process_b = tmp_path / "B-process"
    before = {
        "release_head": git(release_b, "rev-parse", "HEAD"),
        "release_status": git(release_b, "status", "--porcelain=v1"),
        "process_branch": git(process_b, "branch", "--show-current"),
        "process_status": git(process_b, "status", "--porcelain=v1"),
        "project_text": (process_b / "PROJECT.yaml").read_text(encoding="utf-8"),
        "binding_text": (release_b / WORKSPACE_BINDING_REL).read_text(encoding="utf-8"),
        "release_common": str(common_dir(release_b)),
        "process_common": str(common_dir(process_b)),
    }

    git(release_a, "switch", "-c", "feature-a")
    (release_a / "A.txt").write_text("A\n", encoding="utf-8")

    after = {
        "release_head": git(release_b, "rev-parse", "HEAD"),
        "release_status": git(release_b, "status", "--porcelain=v1"),
        "process_branch": git(process_b, "branch", "--show-current"),
        "process_status": git(process_b, "status", "--porcelain=v1"),
        "project_text": (process_b / "PROJECT.yaml").read_text(encoding="utf-8"),
        "binding_text": (release_b / WORKSPACE_BINDING_REL).read_text(encoding="utf-8"),
        "release_common": str(common_dir(release_b)),
        "process_common": str(common_dir(process_b)),
    }

    assert after == before
    assert common_dir(release_a) != common_dir(release_b)
    assert common_dir(tmp_path / "A-process") != common_dir(process_b)


def test_cli_init_and_auto_detecting_project_check(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    release = init_release(tmp_path)

    dry_code = init_main(["--project-root", str(release), "--project-id", "demo"])
    dry_payload = json.loads(capsys.readouterr().out)
    assert dry_code == 0
    assert dry_payload["decision"] == "READY"
    assert set(dry_payload) == set(PLAN_FIELDS)
    assert "create-link" not in {item["kind"] for item in dry_payload["actions"]}

    plan = plan_project_init(request_for(release))
    authorization_path = tmp_path / "init-authorization.json"
    authorization_path.write_text(
        json.dumps(asdict(authorize(plan)), ensure_ascii=False),
        encoding="utf-8",
    )

    apply_code = init_main(
        [
            "--project-root",
            str(release),
            "--project-id",
            "demo",
            "--apply",
            "--authorization",
            str(authorization_path),
        ]
    )
    apply_payload = json.loads(capsys.readouterr().out)
    assert apply_code == 0
    assert apply_payload["receipt"]["decision"] == "PASS"

    status_code = status_main(["--project-root", str(release)])
    status_payload = json.loads(capsys.readouterr().out)
    assert status_code == 0
    assert status_payload["layout_version"] == LAYOUT_VERSION
    assert status_payload["ok"] is True
    assert status_payload["route_mode"] == ROUTE_MODE_SIBLING_BINDING

    with pytest.raises(SystemExit) as raised:
        cli._run_project(["check", "--project-root", str(release)])
    auto_payload = json.loads(capsys.readouterr().out)
    assert raised.value.code == 0
    assert auto_payload["status"] == "healthy"

    with pytest.raises(SystemExit) as help_exit:
        cli._run_project(["check", "--project-root", str(release), "--help"])
    help_text = capsys.readouterr().out
    assert help_exit.value.code == 0
    assert "usage: meta-flow project check" in help_text
    assert "usage: meta-flow project status" not in help_text


def test_resolve_ref_cli_maps_logical_ref_without_process_entry(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release = init_release(tmp_path)
    apply_init(plan_project_init(request_for(release)))
    process = tmp_path / "demo-process"
    work = process / "works" / "W-001" / "WORK.yaml"
    work.parent.mkdir(parents=True)
    work.write_text("schema_version: 1\n", encoding="utf-8")

    exit_code = resolve_ref_main(
        [
            "--project-root",
            str(release),
            "--logical-ref",
            "process/works/W-001/WORK.yaml",
            "--format",
            "json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["logical_ref"] == "process/works/W-001/WORK.yaml"
    assert Path(payload["resolved_path"]) == work
    assert not (release / "process").exists()


def test_project_init_preserves_evolved_project_fields_on_rerun(tmp_path: Path) -> None:
    release = init_release(tmp_path)
    request = request_for(release)
    apply_init(plan_project_init(request))
    process = tmp_path / "demo-process"
    (process / "PROJECT.yaml").write_text(
        "schema_version: 1\n"
        "project_id: demo\n"
        "name: Demo Project\n"
        "objective: 长期交付目标\n"
        "status: active\n"
        "active_work_refs:\n"
        "  - works/W-001/WORK.yaml\n",
        encoding="utf-8",
    )

    plan = plan_project_init(request)

    assert not plan.blocked
    assert any(
        action.action == "noop" and "preserve evolved" in action.reason
        for action in plan.actions
    )


def test_project_init_rejects_existing_process_repo_non_main_branch(tmp_path: Path) -> None:
    release = init_release(tmp_path)
    process = tmp_path / "demo-process"
    process.mkdir()
    git(process, "init", "-b", "other")

    plan = plan_project_init(
        ProjectInitRequest(release, "demo", "Demo Project", process)
    )

    assert plan.blocked
    assert "process_branch_conflict" in {item.code for item in plan.conflicts}


def test_binding_only_rejects_preexisting_process_entry(tmp_path: Path) -> None:
    release = init_release(tmp_path)
    (release / "process").symlink_to("../demo-process", target_is_directory=True)

    plan = plan_project_init(request_for(release))

    assert plan.blocked
    assert "unexpected_process_entry" in {item.code for item in plan.conflicts}


@pytest.mark.parametrize(
    ("target", "value", "expected_error"),
    [
        ("metadata-route", "other-release", "process metadata release_repo route mismatch"),
        ("metadata-mode", ROUTE_MODE_RELATIVE_SYMLINK, "release/process binding route_mode mismatch"),
    ],
)
def test_reciprocal_binding_mismatch_fails_closed(
    tmp_path: Path,
    target: str,
    value: str,
    expected_error: str,
) -> None:
    release = init_release(tmp_path)
    apply_init(plan_project_init(request_for(release)))
    process = tmp_path / "demo-process"
    if target == "metadata-route":
        metadata = load_yaml_object(process / PROCESS_METADATA_REL)
        metadata["release_repo"]["relative_path"] = value
        (process / PROCESS_METADATA_REL).write_text(
            dump_yaml(metadata) + "\n",
            encoding="utf-8",
        )
    elif target == "metadata-mode":
        metadata = load_yaml_object(process / PROCESS_METADATA_REL)
        metadata["route_mode"] = value
        (process / PROCESS_METADATA_REL).write_text(
            dump_yaml(metadata) + "\n",
            encoding="utf-8",
        )

    health = check_independent_process_route(release)

    assert not health.ok
    assert expected_error in "\n".join(health.errors)


def test_unsupported_or_missing_layout_fails_closed(tmp_path: Path) -> None:
    release = init_release(tmp_path)
    binding_path = release / WORKSPACE_BINDING_REL
    binding_path.parent.mkdir(parents=True)
    binding_path.write_text(
        "schema_version: 1\n"
        "workflow_model: vnext\n"
        "project_id: demo\n"
        "repo_role: release\n"
        "route_mode: sibling-binding\n"
        "process_repo:\n"
        "  anchor: workspace_parent\n"
        "  relative_path: demo-process\n",
        encoding="utf-8",
    )

    health = check_independent_process_route(release)

    assert not health.ok
    assert "not a supported vNext layout" in "\n".join(health.errors)


def test_missing_project_reports_initialization_action(tmp_path: Path) -> None:
    release = init_release(tmp_path)
    apply_init(plan_project_init(request_for(release)))
    (tmp_path / "demo-process" / "PROJECT.yaml").unlink()

    health = check_independent_process_route(release)

    assert not health.ok
    assert "run meta-flow project init --apply" in "\n".join(health.errors)


def test_resolver_rejects_absolute_parent_escape_and_does_not_discover_siblings(tmp_path: Path) -> None:
    release = init_release(tmp_path)
    unsafe_binding = {
        "schema_version": 1,
        "layout_version": LAYOUT_VERSION,
        "workflow_model": "vnext",
        "project_id": "demo",
        "repo_role": "release",
        "route_mode": ROUTE_MODE_SIBLING_BINDING,
        "process_repo": {
            "anchor": "workspace_parent",
            "relative_path": "../outside",
        },
    }

    with pytest.raises(ValueError, match="safe sibling"):
        resolve_process_repo_root(release, unsafe_binding)


def test_resolver_rejects_sibling_symlink_escape(tmp_path: Path) -> None:
    release = init_release(tmp_path / "workspace")
    outside = tmp_path / "outside" / "demo-process"
    outside.mkdir(parents=True)
    (release.parent / "demo-process").symlink_to(outside, target_is_directory=True)
    binding = {
        "schema_version": 1,
        "layout_version": LAYOUT_VERSION,
        "workflow_model": "vnext",
        "project_id": "demo",
        "repo_role": "release",
        "route_mode": ROUTE_MODE_SIBLING_BINDING,
        "process_repo": {
            "anchor": "workspace_parent",
            "relative_path": "demo-process",
        },
    }

    with pytest.raises(ValueError, match="resolve to one sibling"):
        resolve_process_repo_root(release, binding)
