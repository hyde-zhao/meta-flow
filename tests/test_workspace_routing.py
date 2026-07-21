import json
import subprocess
from dataclasses import replace
from pathlib import Path

from meta_flow.workspace.legacy_route_adapter import _LegacyRouteAuthorization
from meta_flow.workspace.project_artifact_routing import (
    load_project_artifact_config,
    resolve_project_artifact_route,
)
from meta_flow.workspace.routing import (
    bootstrap_process_workspace,
    check_process_route,
    legacy_workspace_plan,
    link_process_workspace,
    project_route_to_process_health,
)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def _init_project(root: Path) -> None:
    _git(root, "init", "-b", "main")
    _git(root, "-c", "user.name=Meta Flow Test", "-c", "user.email=meta-flow@example.invalid", "commit", "--allow-empty", "-m", "initial")


def _capability(
    command: str,
    project_root: Path,
    artifact_root: Path,
    project_name: str,
    authorization_id: str,
    *,
    force: bool = False,
) -> _LegacyRouteAuthorization:
    plan = legacy_workspace_plan(
        command, project_root, artifact_root, project_name, force=force
    )
    assert plan["decision"] == "READY"
    return _LegacyRouteAuthorization(
        schema_version=1,
        authorization_id=authorization_id,
        command=command,
        authorization_source="typed-user-confirmation",
        authorization_kind="workspace-operation",
        decision_ref="works/TEST/GATE.yaml",
        project_id=project_name,
        operation_digest=str(plan["operation_digest"]),
        expected_oids=dict(plan["expected_oids"]),
        expires_at="2099-01-01T00:00:00+00:00",
    )


def test_workspace_link_writes_portable_relative_metadata(tmp_path: Path) -> None:
    project_root = tmp_path / "meta-flow"
    artifact_root = tmp_path / "meta-flow-artifacts"
    project_root.mkdir()
    _init_project(project_root)

    health = link_process_workspace(
        project_root,
        artifact_root,
        "meta-flow",
        capability=_capability(
            "workspace link", project_root, artifact_root, "meta-flow", "link-001"
        ),
    )

    process_link = project_root / "process"
    assert process_link.is_symlink()
    assert not Path(process_link.readlink()).is_absolute()
    assert health.status == "state_missing"

    metadata = (artifact_root / "process" / "meta-flow" / ".meta-flow-process.yaml").read_text(
        encoding="utf-8"
    )
    assert 'path_format: "portable-relative-v1"' in metadata
    assert 'project_root: "."' in metadata
    assert 'artifact_root: "../meta-flow-artifacts"' in metadata
    assert 'project_process_root: "process/meta-flow"' in metadata
    assert 'link_path: "process"' in metadata
    assert str(tmp_path) not in metadata


def test_workspace_bootstrap_initializes_state_summary_and_ledgers(tmp_path: Path) -> None:
    project_root = tmp_path / "target-project"
    artifact_root = tmp_path / "artifacts"
    project_root.mkdir()
    _init_project(project_root)

    health = bootstrap_process_workspace(
        project_root,
        artifact_root,
        "target-project",
        capability=_capability(
            "workspace bootstrap", project_root, artifact_root, "target-project", "bootstrap-001"
        ),
    )

    assert health.ok
    assert (project_root / "process").is_symlink()
    assert (project_root / "process" / "state" / "STATE.current.json").is_file()
    assert (project_root / "process" / "STATE.md").is_file()
    for name in (
        "CR-LEDGER.ndjson",
        "STORY-LEDGER.ndjson",
        "CHECKPOINT-LEDGER.ndjson",
        "HANDOFF-LEDGER.ndjson",
        "AGENT-DISPATCH-LEDGER.ndjson",
        "GATE-LEDGER.ndjson",
        "RUN-LEDGER.ndjson",
        "READ-EXPANSION-LEDGER.ndjson",
    ):
        assert (project_root / "process" / "state" / name).is_file()

    metadata = (artifact_root / "process" / "target-project" / ".meta-flow-process.yaml").read_text(
        encoding="utf-8"
    )
    assert str(tmp_path) not in metadata


def test_workspace_bootstrap_resolves_relative_artifact_root_against_project_root(tmp_path: Path) -> None:
    project_root = tmp_path / "target-project"
    project_root.mkdir()
    _init_project(project_root)

    health = bootstrap_process_workspace(
        project_root,
        Path("../artifacts"),
        "target-project",
        capability=_capability(
            "workspace bootstrap", project_root, Path("../artifacts"), "target-project", "bootstrap-002"
        ),
    )

    expected_artifact_root = tmp_path / "artifacts"
    assert health.ok
    assert health.artifact_root == expected_artifact_root.resolve()
    assert health.project_process_root == (expected_artifact_root / "process" / "target-project").resolve()
    assert (expected_artifact_root / "process" / "target-project" / ".meta-flow-process.yaml").is_file()


def test_workspace_check_resolves_relative_state_routing(tmp_path: Path) -> None:
    project_root = tmp_path / "meta-flow"
    artifact_root = tmp_path / "meta-flow-artifacts"
    project_root.mkdir()
    _init_project(project_root)
    link_process_workspace(
        project_root,
        artifact_root,
        "meta-flow",
        capability=_capability(
            "workspace link", project_root, artifact_root, "meta-flow", "link-002"
        ),
    )

    state_path = artifact_root / "process" / "meta-flow" / "STATE.md"
    state_path.write_text(
        """---
project_id: "meta-flow"
artifact_routing:
  routing_mode: "symlink"
  path_format: "portable-relative-v1"
  artifact_root: "../meta-flow-artifacts"
  artifact_root_anchor: "project_root"
  project_process_root: "process/meta-flow"
  project_process_root_anchor: "artifact_root"
  link_path: "process"
  link_path_anchor: "project_root"
  project_name: "meta-flow"
---
""",
        encoding="utf-8",
    )

    health = check_process_route(project_root)

    assert health.ok
    assert health.artifact_root == artifact_root.resolve()
    assert health.project_process_root == (artifact_root / "process" / "meta-flow").resolve()


def test_project_route_projection_preserves_legacy_health_shape(tmp_path: Path) -> None:
    project_root = tmp_path / "source" / "meta-flow"
    project_root.mkdir(parents=True)
    metadata_path = project_root / "project-artifact-route.json"
    metadata_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_id": "meta-flow",
                "layout_version": "project-first-worktree-v1",
                "artifact_control_root": {
                    "anchor": "project_root",
                    "relative_path": "artifact-control",
                },
                "sibling_root": {
                    "anchor": "project_root",
                    "relative_path": "artifact-worktrees",
                },
                "project_worktree": {
                    "anchor": "sibling_root",
                    "relative_path": "meta-flow",
                },
                "docs_relative": {
                    "anchor": "project_worktree",
                    "relative_path": "docs",
                },
                "process_relative": {
                    "anchor": "project_worktree",
                    "relative_path": "process",
                },
                "branch_namespace": "projects/meta-flow",
                "owned_paths": ["docs", "process"],
            }
        ),
        encoding="utf-8",
    )
    config = load_project_artifact_config(
        project_root=project_root,
        requested_project_id="meta-flow",
        metadata_path=metadata_path,
    )
    decision = resolve_project_artifact_route(
        config,
        project_root=project_root,
        target_kind="process",
        intent="write",
    )

    health = project_route_to_process_health(
        config,
        decision,
        project_root=project_root,
    )

    assert health.ok
    assert health.expected_project_name == "meta-flow"
    assert health.routing_mode == "project-first-worktree-v1"
    assert health.actual_target == (
        project_root / "artifact-worktrees" / "meta-flow" / "process"
    ).resolve()
    assert health.project_process_root == health.actual_target
    assert health.artifact_git_dirty == "unknown"


def test_project_route_projection_rejects_cross_project_decision(tmp_path: Path) -> None:
    project_root = tmp_path / "source" / "meta-flow"
    project_root.mkdir(parents=True)
    metadata_path = project_root / "project-artifact-route.json"
    metadata_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_id": "meta-flow",
                "layout_version": "project-first-worktree-v1",
                "artifact_control_root": {
                    "anchor": "project_root",
                    "relative_path": "artifact-control",
                },
                "sibling_root": {
                    "anchor": "project_root",
                    "relative_path": "artifact-worktrees",
                },
                "project_worktree": {
                    "anchor": "sibling_root",
                    "relative_path": "meta-flow",
                },
                "docs_relative": {
                    "anchor": "project_worktree",
                    "relative_path": "docs",
                },
                "process_relative": {
                    "anchor": "project_worktree",
                    "relative_path": "process",
                },
                "branch_namespace": "projects/meta-flow",
                "owned_paths": ["docs", "process"],
            }
        ),
        encoding="utf-8",
    )
    config = load_project_artifact_config(
        project_root=project_root,
        requested_project_id="meta-flow",
        metadata_path=metadata_path,
    )
    decision = resolve_project_artifact_route(
        config,
        project_root=project_root,
        target_kind="process",
        intent="write",
    )
    assert decision.write_target is not None
    cross_project_target = replace(
        decision.write_target,
        runtime_path=project_root / "artifact-worktrees" / "other-project" / "process",
    )
    cross_project_decision = replace(
        decision,
        project_id="other-project",
        write_target=cross_project_target,
    )

    health = project_route_to_process_health(
        config,
        cross_project_decision,
        project_root=project_root,
    )

    assert not health.ok
    assert health.status == "route_mismatch"
    assert health.actual_target is None
    assert health.project_process_root is None
    assert any(
        "decision project_id=other-project does not match config project_id=meta-flow" in error
        for error in health.errors
    )
