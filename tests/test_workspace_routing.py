from pathlib import Path

from meta_flow.workspace.routing import bootstrap_process_workspace, check_process_route, link_process_workspace


def test_workspace_link_writes_portable_relative_metadata(tmp_path: Path) -> None:
    project_root = tmp_path / "meta-flow"
    artifact_root = tmp_path / "meta-flow-artifacts"
    project_root.mkdir()

    health = link_process_workspace(project_root, artifact_root, "meta-flow")

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

    health = bootstrap_process_workspace(project_root, artifact_root, "target-project")

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

    health = bootstrap_process_workspace(project_root, Path("../artifacts"), "target-project")

    expected_artifact_root = tmp_path / "artifacts"
    assert health.ok
    assert health.artifact_root == expected_artifact_root.resolve()
    assert health.project_process_root == (expected_artifact_root / "process" / "target-project").resolve()
    assert (expected_artifact_root / "process" / "target-project" / ".meta-flow-process.yaml").is_file()


def test_workspace_check_resolves_relative_state_routing(tmp_path: Path) -> None:
    project_root = tmp_path / "meta-flow"
    artifact_root = tmp_path / "meta-flow-artifacts"
    project_root.mkdir()
    link_process_workspace(project_root, artifact_root, "meta-flow")

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
