from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from meta_flow import cli
from meta_flow.project.model import load_project
from meta_flow.project.onboarding import (
    LAYOUT_VERSION,
    PROCESS_LINK_MODE_RELATIVE_SYMLINK,
    PROCESS_METADATA_REL,
    ROUTE_MODE_RELATIVE_SYMLINK,
    ROUTE_MODE_SIBLING_BINDING,
    WORKSPACE_BINDING_REL,
    ProjectInitRequest,
    apply_project_init,
    check_independent_process_route,
    init_main,
    plan_project_init,
    resolve_process_repo_root,
    status_main,
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


def test_dry_run_is_deterministic_and_has_zero_mutation(tmp_path: Path) -> None:
    release = init_release(tmp_path)
    request = request_for(release)

    first = plan_project_init(request)
    second = plan_project_init(request)

    assert not first.blocked
    assert first.plan_digest == second.plan_digest
    assert first.as_dict()["mutation_count"] == 0
    assert not (tmp_path / "demo-process").exists()
    assert not (release / "process").exists()
    assert not (release / WORKSPACE_BINDING_REL).exists()


def test_apply_creates_binding_only_independent_repo_and_minimal_project(tmp_path: Path) -> None:
    release = init_release(tmp_path)
    before_oid = git(release, "rev-parse", "HEAD")
    plan = plan_project_init(request_for(release))

    receipt = apply_project_init(plan)

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


def test_relative_symlink_compatibility_mode_is_explicit(tmp_path: Path) -> None:
    release = init_release(tmp_path)
    request = request_for(
        release,
        process_link_mode=PROCESS_LINK_MODE_RELATIVE_SYMLINK,
    )

    apply_project_init(plan_project_init(request))

    process_repo = tmp_path / "demo-process"
    assert (release / "process").is_symlink()
    link_text = os.readlink(release / "process")
    assert link_text == "../demo-process"
    assert not Path(link_text).is_absolute()
    assert (release / "process").resolve() == process_repo.resolve()
    assert "/process" in (release / ".gitignore").read_text(encoding="utf-8")
    health = check_independent_process_route(release)
    assert health.ok
    assert health.route_mode == ROUTE_MODE_RELATIVE_SYMLINK


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
    receipt = apply_project_init(plan)
    process_repo = tmp_path / "new-project-process"
    assert receipt.decision == "PASS"
    assert git(release, "branch", "--show-current") == "main"
    assert git(process_repo, "branch", "--show-current") == "main"
    assert common_dir(release) != common_dir(process_repo)
    assert check_independent_process_route(release).ok


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
    apply_project_init(plan_project_init(request_for(release)))
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
    apply_project_init(plan_project_init(request_for(release)))

    second = plan_project_init(request_for(release))
    receipt = apply_project_init(second)

    assert not second.blocked
    assert {action.action for action in second.actions} == {"noop"}
    assert receipt.decision == "PASS"
    assert receipt.mutation_count == 0
    assert receipt.created_paths == ()


def test_moving_workspace_parent_preserves_binding_and_health(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    release = init_release(bundle)
    apply_project_init(plan_project_init(request_for(release)))
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
    apply_project_init(plan_project_init(first_request))
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
        apply_project_init(plan)

    assert not (tmp_path / "demo-process").exists()
    assert not (release / WORKSPACE_BINDING_REL).exists()
    assert not (release / "process").exists()


def test_two_projects_are_physically_isolated_when_one_switches_branch(tmp_path: Path) -> None:
    release_a = init_release(tmp_path, name="A")
    release_b = init_release(tmp_path, name="B")
    apply_project_init(plan_project_init(request_for(release_a, project_id="A")))
    apply_project_init(plan_project_init(request_for(release_b, project_id="B")))
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
    assert dry_payload["mutation_count"] == 0
    assert dry_payload["process_link_mode"] == "none"
    assert "create-link" not in {item["action"] for item in dry_payload["actions"]}

    apply_code = init_main(
        ["--project-root", str(release), "--project-id", "demo", "--apply"]
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


def test_resolve_ref_cli_maps_logical_ref_without_process_entry(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release = init_release(tmp_path)
    apply_project_init(plan_project_init(request_for(release)))
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
    apply_project_init(plan_project_init(request))
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
    apply_project_init(plan_project_init(request_for(release)))
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
    apply_project_init(plan_project_init(request_for(release)))
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
