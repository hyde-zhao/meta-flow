from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from meta_flow.workspace.legacy_route_adapter import _LegacyRouteAuthorization
from meta_flow.workspace.routing import (
    check_process_route,
    legacy_workspace_plan,
    link_process_workspace,
)


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_project(root: Path) -> None:
    _git(root, "init", "-b", "main")
    _git(
        root,
        "-c",
        "user.name=Meta Flow Test",
        "-c",
        "user.email=meta-flow@example.invalid",
        "commit",
        "--allow-empty",
        "-m",
        "initial",
    )


def _capability(
    project_root: Path,
    artifact_root: Path,
    authorization_id: str,
) -> _LegacyRouteAuthorization:
    plan = legacy_workspace_plan(
        "workspace link",
        project_root,
        artifact_root,
        "meta-flow",
    )
    assert plan["decision"] == "READY"
    return _LegacyRouteAuthorization(
        schema_version=1,
        authorization_id=authorization_id,
        command="workspace link",
        authorization_source="typed-user-confirmation",
        authorization_kind="workspace-operation",
        decision_ref="works/TEST/GATE.yaml",
        project_id="meta-flow",
        operation_digest=str(plan["operation_digest"]),
        expected_oids=dict(plan["expected_oids"]),
        expires_at="2099-01-01T00:00:00+00:00",
    )


def test_relink_is_idempotent_and_preserves_created_at(tmp_path: Path) -> None:
    project_root = tmp_path / "meta-flow"
    artifact_root = tmp_path / "meta-flow-artifacts"
    project_root.mkdir()
    _init_project(project_root)
    link_process_workspace(
        project_root,
        artifact_root,
        "meta-flow",
        capability=_capability(project_root, artifact_root, "cr047-link-001"),
    )
    metadata = artifact_root / "process" / "meta-flow" / ".meta-flow-process.yaml"
    first = metadata.read_bytes()

    health = link_process_workspace(
        project_root,
        Path("../meta-flow-artifacts"),
        "meta-flow",
        capability=_capability(
            project_root,
            Path("../meta-flow-artifacts"),
            "cr047-link-002",
        ),
    )

    assert health.status == "state_missing"
    assert metadata.read_bytes() == first


def test_relative_route_survives_parent_directory_relocation(tmp_path: Path) -> None:
    original = tmp_path / "device-a"
    relocated = tmp_path / "device-b"
    project_root = original / "meta-flow"
    artifact_root = original / "meta-flow-artifacts"
    project_root.mkdir(parents=True)
    _init_project(project_root)
    link_process_workspace(
        project_root,
        artifact_root,
        "meta-flow",
        capability=_capability(project_root, artifact_root, "cr047-relocate-001"),
    )
    (artifact_root / "process" / "meta-flow" / "STATE.md").write_text(
        '---\nproject_id: "meta-flow"\n---\n', encoding="utf-8"
    )

    shutil.copytree(original, relocated, symlinks=True)
    relocated_project = relocated / "meta-flow"
    health = check_process_route(relocated_project)

    assert health.ok
    assert health.actual_target == (relocated / "meta-flow-artifacts" / "process" / "meta-flow").resolve()


def test_regular_process_path_fails_closed(tmp_path: Path) -> None:
    project_root = tmp_path / "meta-flow"
    project_root.mkdir()
    _init_project(project_root)
    (project_root / "process").mkdir()

    with pytest.raises(SystemExit, match="already exists as a regular path"):
        link_process_workspace(
            project_root,
            tmp_path / "artifacts",
            "meta-flow",
            capability=_capability(
                project_root,
                tmp_path / "artifacts",
                "cr047-conflict-001",
            ),
        )


def test_directory_contract_declares_single_internal_canonical_copy() -> None:
    contract = Path("delivery/rules/DIRECTORY-CONTRACT.yaml").read_text(encoding="utf-8")

    assert "canonical_root: process/docs" in contract
    assert "expected_internal_canonical_copies: 1" in contract
    assert "generated_or_ignored_root_internal_views: false" in contract
