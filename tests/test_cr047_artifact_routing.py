from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from meta_flow.workspace.routing import check_process_route, link_process_workspace


def test_relink_is_idempotent_and_preserves_created_at(tmp_path: Path) -> None:
    project_root = tmp_path / "meta-flow"
    artifact_root = tmp_path / "meta-flow-artifacts"
    project_root.mkdir()
    link_process_workspace(project_root, artifact_root, "meta-flow")
    metadata = artifact_root / "process" / "meta-flow" / ".meta-flow-process.yaml"
    first = metadata.read_bytes()

    health = link_process_workspace(project_root, Path("../meta-flow-artifacts"), "meta-flow")

    assert health.status == "state_missing"
    assert metadata.read_bytes() == first


def test_relative_route_survives_parent_directory_relocation(tmp_path: Path) -> None:
    original = tmp_path / "device-a"
    relocated = tmp_path / "device-b"
    project_root = original / "meta-flow"
    artifact_root = original / "meta-flow-artifacts"
    project_root.mkdir(parents=True)
    link_process_workspace(project_root, artifact_root, "meta-flow")
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
    (project_root / "process").mkdir()

    with pytest.raises(SystemExit, match="already exists as a regular path"):
        link_process_workspace(project_root, tmp_path / "artifacts", "meta-flow")


def test_directory_contract_declares_single_internal_canonical_copy() -> None:
    contract = Path("delivery/rules/DIRECTORY-CONTRACT.yaml").read_text(encoding="utf-8")

    assert "canonical_root: process/docs" in contract
    assert "expected_internal_canonical_copies: 1" in contract
    assert "generated_or_ignored_root_internal_views: false" in contract
