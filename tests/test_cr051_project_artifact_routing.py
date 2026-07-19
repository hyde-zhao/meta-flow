"""CR-051 路由契约测试。

追踪：TC-AW-001/002/003/010/012；REQ-AW-001..003/013；NF-AW-001..002。
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from meta_flow.workspace.project_artifact_routing import (
    STABLE_ERROR_CODES,
    RoutingValidationError,
    assert_owned_target,
    load_project_artifact_config,
    resolve_project_artifact_route,
    route_decision_to_dict,
)


def _project_first_payload(project_id: str = "meta-flow") -> dict[str, object]:
    return {
        "schema_version": 1,
        "project_id": project_id,
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
            "relative_path": project_id,
        },
        "docs_relative": {
            "anchor": "project_worktree",
            "relative_path": "docs",
        },
        "process_relative": {
            "anchor": "project_worktree",
            "relative_path": "process",
        },
        "legacy_docs": {
            "anchor": "artifact_control_root",
            "relative_path": f"docs/{project_id}",
        },
        "legacy_process": {
            "anchor": "artifact_control_root",
            "relative_path": f"process/{project_id}",
        },
        "branch_namespace": f"projects/{project_id}",
        "owned_paths": ["docs", "process"],
    }


def _write_metadata(
    project_root: Path,
    payload: dict[str, object],
    *,
    metadata_path: Path | None = None,
) -> Path:
    path = metadata_path or project_root / "process" / ".meta-flow-process.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _load(project_root: Path, payload: dict[str, object] | None = None):
    _write_metadata(project_root, payload or _project_first_payload())
    return load_project_artifact_config(
        project_root=project_root,
        requested_project_id="meta-flow",
    )


def test_stable_error_code_contract_is_frozen() -> None:
    assert STABLE_ERROR_CODES == (
        "config_missing",
        "schema_unsupported",
        "layout_unsupported",
        "project_mismatch",
        "anchor_unknown",
        "anchor_parent_invalid",
        "anchor_cycle",
        "absolute_canonical_path",
        "path_escape",
        "control_nested_worktree",
        "write_target_ambiguous",
        "target_not_owned",
        "route_conflict",
    )


def test_loader_uses_explicit_or_single_default_metadata_path(tmp_path: Path) -> None:
    project_root = tmp_path / "source" / "meta-flow"
    project_root.mkdir(parents=True)
    default_path = _write_metadata(project_root, _project_first_payload())

    default_config = load_project_artifact_config(
        project_root=project_root,
        requested_project_id="meta-flow",
    )
    explicit_config = load_project_artifact_config(
        project_root=project_root,
        requested_project_id="meta-flow",
        metadata_path=default_path,
    )

    assert default_config == explicit_config
    with pytest.raises(RoutingValidationError, match="config_missing") as exc_info:
        load_project_artifact_config(
            project_root=project_root,
            requested_project_id="meta-flow",
            metadata_path=project_root / "missing.yaml",
        )
    assert exc_info.value.code == "config_missing"


def test_loader_accepts_simple_yaml_without_external_yaml_dependency(tmp_path: Path) -> None:
    project_root = tmp_path / "source" / "meta-flow"
    project_root.mkdir(parents=True)
    metadata = project_root / "route.yaml"
    metadata.write_text(
        """schema_version: 1
project_id: meta-flow
layout_version: project-first-worktree-v1
artifact_control_root:
  anchor: project_root
  relative_path: artifact-control
sibling_root:
  anchor: project_root
  relative_path: artifact-worktrees
project_worktree:
  anchor: sibling_root
  relative_path: meta-flow
docs_relative:
  anchor: project_worktree
  relative_path: docs
process_relative:
  anchor: project_worktree
  relative_path: process
legacy_docs:
  anchor: artifact_control_root
  relative_path: docs/meta-flow
legacy_process:
  anchor: artifact_control_root
  relative_path: process/meta-flow
branch_namespace: projects/meta-flow
owned_paths:
  - docs
  - process
""",
        encoding="utf-8",
    )

    config = load_project_artifact_config(
        project_root=project_root,
        requested_project_id="meta-flow",
        metadata_path=metadata,
    )

    assert config.project_worktree is not None
    assert config.project_worktree.anchor == "sibling_root"
    assert config.owned_paths == ("docs", "process")


@pytest.mark.parametrize("kind", ["docs", "process"])
def test_project_first_returns_only_current_project_targets(tmp_path: Path, kind: str) -> None:
    project_root = tmp_path / "source" / "meta-flow"
    project_root.mkdir(parents=True)
    config = _load(project_root)

    read_decision = resolve_project_artifact_route(
        config,
        project_root=project_root,
        target_kind=kind,
        intent="read",
    )
    write_decision = resolve_project_artifact_route(
        config,
        project_root=project_root,
        target_kind=kind,
        intent="write",
    )

    expected = (project_root / "artifact-worktrees" / "meta-flow" / kind).resolve()
    assert read_decision.decision == "PASS"
    assert [target.role for target in read_decision.read_targets] == [
        "primary",
        "compatibility",
    ]
    assert read_decision.write_target is None
    assert write_decision.decision == "PASS"
    assert write_decision.write_target is not None
    assert write_decision.write_target.runtime_path == expected
    assert sum(target.runtime_path == expected for target in write_decision.read_targets) == 1
    assert not any("other-project" in str(target.runtime_path) for target in write_decision.read_targets)


@pytest.mark.parametrize("kind", ["docs", "process"])
def test_explicit_legacy_layout_stays_the_unique_write_target(
    tmp_path: Path,
    kind: str,
) -> None:
    project_root = tmp_path / "source" / "meta-flow"
    project_root.mkdir(parents=True)
    payload = _project_first_payload()
    payload["layout_version"] = "legacy-shared-v1"
    config = _load(project_root, payload)
    project_first_candidate = project_root / "artifact-worktrees" / "meta-flow" / kind
    project_first_candidate.mkdir(parents=True)

    decision = resolve_project_artifact_route(
        config,
        project_root=project_root,
        target_kind=kind,
        intent="write",
    )

    assert decision.decision == "PASS"
    assert decision.write_target is not None
    assert decision.write_target.runtime_path == (
        project_root / "artifact-control" / kind / "meta-flow"
    ).resolve()
    assert project_first_candidate.is_dir()


def test_legacy_non_string_owned_path_uses_structured_error(tmp_path: Path) -> None:
    project_root = tmp_path / "source" / "meta-flow"
    project_root.mkdir(parents=True)
    payload = _project_first_payload()
    payload["layout_version"] = "legacy-shared-v1"
    payload["owned_paths"] = [7, "process"]
    _write_metadata(project_root, payload)

    with pytest.raises(RoutingValidationError) as exc_info:
        load_project_artifact_config(
            project_root=project_root,
            requested_project_id="meta-flow",
        )

    assert exc_info.value.code == "route_conflict"
    assert exc_info.value.field == "owned_paths.0"
    assert exc_info.value.repair_route == "use normalized POSIX relative paths"


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (lambda value: value.update(schema_version=2), "schema_unsupported"),
        (lambda value: value.update(layout_version="future-v9"), "layout_unsupported"),
        (lambda value: value.update(project_id="other-project"), "project_mismatch"),
        (
            lambda value: value["docs_relative"].update(anchor="unknown"),
            "anchor_unknown",
        ),
        (
            lambda value: value["artifact_control_root"].update(anchor="sibling_root"),
            "anchor_parent_invalid",
        ),
        (
            lambda value: value["project_worktree"].update(anchor="project_worktree"),
            "anchor_cycle",
        ),
        (
            lambda value: (
                value["artifact_control_root"].update(anchor="sibling_root"),
                value["sibling_root"].update(anchor="artifact_control_root"),
            ),
            "anchor_cycle",
        ),
        (
            lambda value: value["artifact_control_root"].update(relative_path="/tmp/control"),
            "absolute_canonical_path",
        ),
        (
            lambda value: value["artifact_control_root"].update(relative_path="../escape/../control"),
            "path_escape",
        ),
        (
            lambda value: (
                value["artifact_control_root"].update(relative_path="artifacts"),
                value["sibling_root"].update(relative_path="artifacts/worktrees"),
            ),
            "control_nested_worktree",
        ),
        (
            lambda value: value["docs_relative"].update(relative_path="docs/./internal"),
            "path_escape",
        ),
        (
            lambda value: value["docs_relative"].update(relative_path="docs\x00internal"),
            "path_escape",
        ),
        (
            lambda value: value["process_relative"].update(relative_path="process\ninternal"),
            "path_escape",
        ),
        (
            lambda value: value["project_worktree"].update(relative_path="other-project"),
            "project_mismatch",
        ),
        (
            lambda value: value.update(branch_namespace="projects/other-project"),
            "project_mismatch",
        ),
        (
            lambda value: value["process_relative"].update(relative_path="docs/internal"),
            "route_conflict",
        ),
    ],
)
def test_invalid_config_is_rejected_before_target_construction(
    tmp_path: Path,
    mutate,
    expected_code: str,
) -> None:
    project_root = tmp_path / "source" / "meta-flow"
    project_root.mkdir(parents=True)
    payload = deepcopy(_project_first_payload())
    mutate(payload)
    _write_metadata(project_root, payload)

    with pytest.raises(RoutingValidationError) as exc_info:
        load_project_artifact_config(
            project_root=project_root,
            requested_project_id="meta-flow",
        )

    error = exc_info.value
    assert error.code == expected_code
    assert error.field
    assert error.repair_route


@pytest.mark.parametrize("bad_project", ["-meta-flow", "../meta-flow", "meta\nflow", ""])
def test_invalid_requested_project_is_rejected_before_metadata_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bad_project: str,
) -> None:
    project_root = tmp_path / "source" / "meta-flow"
    project_root.mkdir(parents=True)
    reads: list[Path] = []
    original = Path.read_bytes

    def tracked_read_bytes(path: Path) -> bytes:
        reads.append(path)
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", tracked_read_bytes)

    with pytest.raises(RoutingValidationError) as exc_info:
        load_project_artifact_config(
            project_root=project_root,
            requested_project_id=bad_project,
        )

    assert exc_info.value.code == "project_mismatch"
    assert reads == []


def test_missing_layout_fails_closed_without_write_target(tmp_path: Path) -> None:
    project_root = tmp_path / "source" / "meta-flow"
    project_root.mkdir(parents=True)
    payload = _project_first_payload()
    del payload["layout_version"]
    _write_metadata(project_root, payload)

    with pytest.raises(RoutingValidationError) as exc_info:
        load_project_artifact_config(
            project_root=project_root,
            requested_project_id="meta-flow",
        )

    assert exc_info.value.code == "layout_unsupported"
    assert exc_info.value.logical_candidates == (
        "legacy-shared-v1",
        "project-first-worktree-v1",
    )


def test_owned_target_proof_rejects_sibling_control_common_prefix_and_kind_mismatch(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "source" / "meta-flow"
    project_root.mkdir(parents=True)
    config = _load(project_root)
    decision = resolve_project_artifact_route(
        config,
        project_root=project_root,
        target_kind="docs",
        intent="write",
    )
    owned_file = project_root / "artifact-worktrees" / "meta-flow" / "docs" / "guide.md"

    proof = assert_owned_target(decision, candidate=owned_file, target_kind="docs")

    assert proof.project_id == "meta-flow"
    assert proof.candidate_relative == "guide.md"
    for candidate, kind in (
        (project_root / "artifact-worktrees" / "other-project" / "docs", "docs"),
        (project_root / "artifact-control" / "docs" / "meta-flow", "docs"),
        (project_root / "artifact-worktrees" / "meta-flow" / "docs-other", "docs"),
        (owned_file, "process"),
    ):
        with pytest.raises(RoutingValidationError) as exc_info:
            assert_owned_target(decision, candidate=candidate, target_kind=kind)
        assert exc_info.value.code == "target_not_owned"


def test_relocation_and_repeated_resolution_keep_portable_digests(tmp_path: Path) -> None:
    decisions = []
    payloads = []
    for device in ("device-a", "device-b"):
        project_root = tmp_path / device / "source" / "meta-flow"
        project_root.mkdir(parents=True)
        config = _load(project_root)
        for iteration in range(10):
            decision = resolve_project_artifact_route(
                config,
                project_root=project_root,
                target_kind="process",
                intent="write",
                observed_at=f"2026-07-18T00:00:{iteration:02d}Z",
            )
            decisions.append(decision)
            payloads.append(route_decision_to_dict(decision))

    assert len({decision.config_digest for decision in decisions}) == 1
    assert len({decision.decision_digest for decision in decisions}) == 1
    assert len({tuple(target.role for target in decision.read_targets) for decision in decisions}) == 1
    serialized = json.dumps(payloads, sort_keys=True)
    assert str(tmp_path / "device-a") not in serialized
    assert str(tmp_path / "device-b") not in serialized


def test_resolver_does_not_read_sibling_content_or_mutate_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "source" / "meta-flow"
    project_root.mkdir(parents=True)
    metadata = _write_metadata(project_root, _project_first_payload())
    sentinel = project_root / "artifact-worktrees" / "other-project" / "sentinel.txt"
    sentinel.parent.mkdir(parents=True)
    sentinel.write_text("do-not-read", encoding="utf-8")
    reads: list[Path] = []
    writes: list[Path] = []
    original_read = Path.read_bytes

    def tracked_read(path: Path) -> bytes:
        reads.append(path)
        return original_read(path)

    def blocked_write(path: Path, *args, **kwargs):
        writes.append(path)
        raise AssertionError(f"resolver attempted write: {path}")

    monkeypatch.setattr(Path, "read_bytes", tracked_read)
    monkeypatch.setattr(Path, "write_text", blocked_write)
    config = load_project_artifact_config(
        project_root=project_root,
        requested_project_id="meta-flow",
    )
    decision = resolve_project_artifact_route(
        config,
        project_root=project_root,
        target_kind="docs",
        intent="write",
    )

    assert decision.decision == "PASS"
    assert reads == [metadata]
    assert writes == []
    assert original_read(sentinel) == b"do-not-read"
