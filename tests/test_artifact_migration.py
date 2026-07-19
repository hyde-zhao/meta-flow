from __future__ import annotations

import hashlib
import json
import os
from dataclasses import FrozenInstanceError
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

import meta_flow.workspace.artifact_migration as migration
from meta_flow.workspace.artifact_migration import (
    ExplicitMigrationProject,
    ManualSyncMetricsSummary,
    MigrationRoot,
    WeeklySyncCount,
    build_migration_manifest,
    evaluate_manual_sync_follow_up,
    migration_manifest_to_dict,
)
from meta_flow.workspace.project_artifact_routing import (
    PathRef,
    RouteDecision,
    RouteTarget,
)
from meta_flow.workspace.project_worktree import (
    WorktreeHealth,
    WorktreeIdentity,
    WorktreeObservation,
)

FIXED_TIME = "2026-07-18T12:00:00+00:00"
OID = "a" * 40


def _route(
    project_id: str,
    runtime_root: Path,
    *,
    decision: str = "PASS",
    source_relative: str = "process/meta-flow",
    target_relative: str = "process",
) -> RouteDecision:
    target = RouteTarget(
        kind="process",
        role="primary",
        canonical_ref=PathRef(anchor="project_worktree", relative_path=target_relative),
        runtime_path=runtime_root,
        read_only=False,
    )
    compatibility = RouteTarget(
        kind="process",
        role="compatibility",
        canonical_ref=PathRef(anchor="artifact_control_root", relative_path=source_relative),
        runtime_path=runtime_root.parent / "source",
        read_only=True,
    )
    return RouteDecision(
        schema_version=1,
        project_id=project_id,
        layout_version="project-first-worktree-v1",
        target_kind="process",
        intent="read",
        decision=decision,  # type: ignore[arg-type]
        read_targets=(target, compatibility) if decision == "PASS" else (),
        write_target=None,
        conflicts=(),
        error=None,
        config_digest="route-digest",
        decision_digest="decision-digest",
        observed_at=FIXED_TIME,
    )


def _health(project_id: str, runtime_root: Path, *, decision: str = "HEALTHY") -> WorktreeHealth:
    identity = WorktreeIdentity(
        project_id=project_id,
        repository_id="artifact-repo",
        repository_fingerprint="repo-fingerprint",
        worktree_id=f"wt-{project_id}",
        repo_common_dir=runtime_root.parent / ".git",
        common_dir_digest="common-digest",
        target_path=runtime_root,
        target_path_digest="target-digest",
        expected_gitdir=None,
        integration_ref=f"refs/heads/projects/{project_id}/integration",
    )
    observed_at = datetime.fromisoformat(FIXED_TIME)
    observation = WorktreeObservation(
        schema_version="1",
        identity=identity,
        observed_at=observed_at,
        route_config_digest="route-digest",
        worktree_state="ORIGINAL",
        head_ref=identity.integration_ref,
        head_oid=OID,
        integration_oid=OID,
        dirty=False,
        staged=False,
        untracked=False,
        git_operation="NONE",
        registry_state="CONSISTENT",
        role="IDLE_INTEGRATION",
        observation_digest="observation-digest",
    )
    return WorktreeHealth(
        project_id=project_id,
        decision=decision,
        observation=observation,
        observation_digest=observation.observation_digest,
        worktree_state="ORIGINAL",
        journal_state="IDLE",
        active_operation_id=None,
        reason_codes=(),
    )


def _metrics(
    *,
    weekly: tuple[int, ...] = (0, 0, 0, 0),
    durations: tuple[float, ...] = (60.0,),
    avoidable: int = 0,
    attempts: int = 10,
    complete: bool = True,
    classified: bool = True,
) -> ManualSyncMetricsSummary:
    return ManualSyncMetricsSummary(
        project_id="meta-flow",
        weekly_sync_counts=tuple(
            WeeklySyncCount(
                week_start=(date(2026, 1, 5) + timedelta(weeks=index)).isoformat(),
                sync_count=count,
            )
            for index, count in enumerate(weekly)
        ),
        durations_seconds=durations,
        avoidable_scheduling_blockers=avoidable,
        total_scheduling_attempts=attempts,
        window_complete=complete,
        blocker_classification_complete=classified,
    )


def _project(source: Path, target: Path) -> ExplicitMigrationProject:
    return ExplicitMigrationProject(
        manifest_id="migration-meta-flow-process-v1",
        project_id="meta-flow",
        route_mode="project-first-worktree-v1",
        source_repository_id="artifact-control",
        target_repository_id="artifact-project-worktree",
        observed_at=FIXED_TIME,
        roots=(
            MigrationRoot(
                source_anchor="artifact_control_root",
                source_relative="process/meta-flow",
                source_runtime_root=source,
                target_anchor="project_worktree",
                target_relative="process",
                target_runtime_root=target,
            ),
        ),
        denied_paths=("process/quant-lab/**", "sibling-projects/**"),
        input_refs=("route:decision-digest", "worktree:observation-digest"),
    )


def _write_identical_trees(source: Path, target: Path) -> None:
    for root in (source, target):
        (root / "nested").mkdir(parents=True)
        (root / "alpha.txt").write_text("alpha\n", encoding="utf-8")
        (root / "nested" / "数据.txt").write_text("payload\n", encoding="utf-8")
        (root / "empty").mkdir()
        (root / "alpha-link").symlink_to("alpha.txt")


def _snapshot(root: Path) -> str:
    rows: list[tuple[str, str, int, str]] = []
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs.sort()
        files.sort()
        current_path = Path(current)
        for name in [*dirs, *files]:
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            stat_result = path.lstat()
            if path.is_symlink():
                payload = os.readlink(path)
                kind = "link"
            elif path.is_file():
                payload = hashlib.sha256(path.read_bytes()).hexdigest()
                kind = "file"
            else:
                payload = ""
                kind = "dir"
            rows.append((relative, kind, stat_result.st_mode, payload))
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()


def test_manifest_has_all_11_immutable_portable_sections(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    _write_identical_trees(source, target)

    manifest = build_migration_manifest(
        _project(source, target),
        _route("meta-flow", target),
        _health("meta-flow", target),
        _metrics(),
    )
    payload = migration_manifest_to_dict(manifest)

    assert tuple(payload) == migration.REQUIRED_MANIFEST_SECTIONS
    assert manifest.readiness.decision == "READY"
    assert manifest.scope.enumeration_complete is True
    assert manifest.summary == migration.MigrationSummary(
        file_count=2,
        link_count=1,
        directory_count=2,
        total_bytes=14,
        hash_algorithm="sha256",
        missing_count=0,
        unreadable_count=0,
        conflicting_count=0,
    )
    assert all(not item.source.relative_path.startswith("/") for item in manifest.mapping)
    assert all(not item.target.relative_path.startswith("/") for item in manifest.mapping)
    assert all(step.executed is False for step in manifest.link_plan.steps)
    assert manifest.readiness.authorization_status == "NOT_AUTHORIZED"
    assert manifest.validation.executed is False
    assert manifest.rollback.executed is False
    assert len(manifest.evidence.content_digest) == 64
    with pytest.raises(FrozenInstanceError):
        manifest.identity.project_id = "other"  # type: ignore[misc]


def test_missing_mapping_target_is_manual_review_not_ready(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    _write_identical_trees(source, target)
    (target / "alpha.txt").unlink()

    manifest = build_migration_manifest(
        _project(source, target),
        _route("meta-flow", target),
        _health("meta-flow", target),
        _metrics(),
    )

    assert manifest.readiness.decision == "MANUAL_REVIEW"
    assert "missing-target" in manifest.readiness.reason_codes
    assert "manual-migration-required" in manifest.readiness.reason_codes
    assert manifest.summary.missing_count == 1


def test_missing_target_root_blocks_before_source_enumeration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "secret.txt").write_text("must-not-be-read", encoding="utf-8")
    target = tmp_path / "missing-target"
    scans: list[Path] = []
    real_scandir = migration._scandir

    def spy_scandir(path: Path):
        scans.append(Path(path))
        return real_scandir(path)

    monkeypatch.setattr(migration, "_scandir", spy_scandir)
    manifest = build_migration_manifest(
        _project(source, target),
        _route("meta-flow", target),
        _health("meta-flow", target),
        _metrics(),
    )

    assert manifest.readiness.decision == "BLOCKED"
    assert "target-root-missing" in manifest.readiness.reason_codes
    assert scans == []
    assert manifest.mapping == ()


def test_identity_or_route_mismatch_blocks_with_zero_enumeration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    _write_identical_trees(source, target)
    scans: list[Path] = []
    monkeypatch.setattr(migration, "_scandir", lambda path: scans.append(Path(path)))

    manifest = build_migration_manifest(
        _project(source, target),
        _route("other-project", target, decision="BLOCKED"),
        _health("meta-flow", target),
        _metrics(),
    )

    assert manifest.readiness.decision == "BLOCKED"
    assert "route-not-pass" in manifest.readiness.reason_codes
    assert "route-project-mismatch" in manifest.readiness.reason_codes
    assert scans == []


def test_out_of_scope_symlink_is_not_followed_or_leaked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    sibling = tmp_path / "sibling"
    source.mkdir()
    target.mkdir()
    sibling.mkdir()
    sentinel = sibling / "quant-lab-secret.txt"
    sentinel.write_text("TOP-SECRET-SENTINEL", encoding="utf-8")
    (source / "outside").symlink_to(sentinel)
    (target / "outside").symlink_to(sentinel)
    accessed: list[Path] = []
    real_lstat = migration._lstat

    def spy_lstat(path: Path):
        accessed.append(Path(path))
        return real_lstat(path)

    monkeypatch.setattr(migration, "_lstat", spy_lstat)
    manifest = build_migration_manifest(
        _project(source, target),
        _route("meta-flow", target),
        _health("meta-flow", target),
        _metrics(),
    )
    payload = json.dumps(migration_manifest_to_dict(manifest), ensure_ascii=False)

    assert manifest.readiness.decision == "MANUAL_REVIEW"
    assert "out-of-scope-symlink" in manifest.readiness.reason_codes
    assert all(sibling not in path.parents and path != sibling for path in accessed)
    assert "TOP-SECRET-SENTINEL" not in payload
    assert str(sentinel) not in payload
    link = next(item for item in manifest.mapping if item.object_type == "symlink")
    assert link.link_target is None
    assert link.link_target_class == "absolute-out-of-scope"


def test_broken_symlink_and_unreadable_file_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "broken").symlink_to("missing.txt")
    (target / "broken").symlink_to("missing.txt")
    (source / "unreadable.txt").write_text("secret", encoding="utf-8")
    (target / "unreadable.txt").write_text("secret", encoding="utf-8")
    real_open = migration._open_binary

    def deny_one(path: Path):
        if Path(path).name == "unreadable.txt":
            raise PermissionError("fixture-denied")
        return real_open(path)

    monkeypatch.setattr(migration, "_open_binary", deny_one)
    manifest = build_migration_manifest(
        _project(source, target),
        _route("meta-flow", target),
        _health("meta-flow", target),
        _metrics(),
    )

    assert manifest.readiness.decision == "MANUAL_REVIEW"
    assert "broken-symlink" in manifest.readiness.reason_codes
    assert "unreadable-object" in manifest.readiness.reason_codes
    assert manifest.scope.enumeration_complete is False
    assert manifest.summary.unreadable_count >= 1
    assert any(error.code == "read-permission-denied" for error in manifest.evidence.read_errors)


def test_symlink_swap_between_lstat_and_open_is_not_followed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    sibling = tmp_path / "sibling"
    source.mkdir()
    target.mkdir()
    sibling.mkdir()
    victim = source / "victim.txt"
    victim.write_text("safe-before-swap", encoding="utf-8")
    (target / "victim.txt").write_text("safe-before-swap", encoding="utf-8")
    sentinel = sibling / "secret.txt"
    sentinel.write_text("MUST-NOT-BE-READ", encoding="utf-8")
    real_lstat = migration._lstat
    real_open = migration._open_binary
    swapped = False
    successfully_opened: list[Path] = []

    def swap_after_lstat(path: Path):
        nonlocal swapped
        result = real_lstat(path)
        if Path(path) == victim and not swapped:
            swapped = True
            victim.unlink()
            victim.symlink_to(sentinel)
        return result

    def observe_successful_open(path: Path):
        stream = real_open(path)
        successfully_opened.append(Path(path))
        return stream

    monkeypatch.setattr(migration, "_lstat", swap_after_lstat)
    monkeypatch.setattr(migration, "_open_binary", observe_successful_open)
    manifest = build_migration_manifest(
        _project(source, target),
        _route("meta-flow", target),
        _health("meta-flow", target),
        _metrics(),
    )
    payload = json.dumps(migration_manifest_to_dict(manifest), ensure_ascii=False)

    assert swapped is True
    assert victim not in successfully_opened
    assert manifest.readiness.decision == "MANUAL_REVIEW"
    assert "unreadable-object" in manifest.readiness.reason_codes
    assert "MUST-NOT-BE-READ" not in payload
    assert str(sentinel) not in payload
    mapping = next(
        item for item in manifest.mapping if item.source.relative_path.endswith("victim.txt")
    )
    assert mapping.readable is False
    assert mapping.content_hash is None


def test_platform_without_no_follow_open_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    _write_identical_trees(source, target)
    monkeypatch.delattr(migration.os, "O_NOFOLLOW", raising=False)

    manifest = build_migration_manifest(
        _project(source, target),
        _route("meta-flow", target),
        _health("meta-flow", target),
        _metrics(),
    )

    assert manifest.readiness.decision == "MANUAL_REVIEW"
    assert "unreadable-object" in manifest.readiness.reason_codes
    assert manifest.scope.enumeration_complete is False
    assert all(item.content_hash is None for item in manifest.mapping if item.object_type == "file")


def test_same_relative_layout_has_same_digest_across_runtime_roots(tmp_path: Path) -> None:
    manifests = []
    for name in ("machine-a", "machine-b"):
        source = tmp_path / name / "source"
        target = tmp_path / name / "target"
        _write_identical_trees(source, target)
        manifests.append(
            build_migration_manifest(
                _project(source, target),
                _route("meta-flow", target),
                _health("meta-flow", target),
                _metrics(),
            )
        )

    assert manifests[0].mapping == manifests[1].mapping
    assert manifests[0].summary == manifests[1].summary
    assert manifests[0].readiness == manifests[1].readiness
    assert manifests[0].evidence.content_digest == manifests[1].evidence.content_digest
    payload = json.dumps(migration_manifest_to_dict(manifests[0]))
    assert str(tmp_path) not in payload


def test_preflight_does_not_mutate_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    _write_identical_trees(source, target)
    before = (_snapshot(source), _snapshot(target))
    mutation_calls: list[str] = []

    def reject_mutation(name: str):
        def reject(*args: object, **kwargs: object) -> None:
            mutation_calls.append(name)
            pytest.fail(f"unexpected mutation call: {name}")

        return reject

    for owner, name in (
        (Path, "write_text"),
        (Path, "write_bytes"),
        (Path, "mkdir"),
        (Path, "unlink"),
        (Path, "rename"),
        (Path, "replace"),
        (Path, "chmod"),
        (Path, "symlink_to"),
        (os, "rename"),
        (os, "replace"),
        (os, "unlink"),
        (os, "mkdir"),
        (os, "chmod"),
        (os, "symlink"),
    ):
        monkeypatch.setattr(owner, name, reject_mutation(f"{owner.__name__}.{name}"))

    manifest = build_migration_manifest(
        _project(source, target),
        _route("meta-flow", target),
        _health("meta-flow", target),
        _metrics(),
    )

    assert (_snapshot(source), _snapshot(target)) == before
    assert mutation_calls == []
    assert manifest.evidence.mutation_count == 0
    assert manifest.evidence.command_count == 0


def test_denied_quant_lab_scope_blocks_before_enumeration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    _write_identical_trees(source, target)
    project = _project(source, target)
    project = ExplicitMigrationProject(
        manifest_id=project.manifest_id,
        project_id=project.project_id,
        route_mode=project.route_mode,
        source_repository_id=project.source_repository_id,
        target_repository_id=project.target_repository_id,
        observed_at=project.observed_at,
        roots=(
            MigrationRoot(
                source_anchor="artifact_control_root",
                source_relative="process/quant-lab",
                source_runtime_root=source,
                target_anchor="project_worktree",
                target_relative="process",
                target_runtime_root=target,
            ),
        ),
        denied_paths=project.denied_paths,
        input_refs=project.input_refs,
    )
    scans: list[Path] = []
    monkeypatch.setattr(migration, "_scandir", lambda path: scans.append(Path(path)))

    manifest = build_migration_manifest(
        project,
        _route("meta-flow", target),
        _health("meta-flow", target),
        _metrics(),
    )

    assert manifest.readiness.decision == "BLOCKED"
    assert "denied-scope" in manifest.readiness.reason_codes
    assert scans == []


def test_denied_descendant_under_wide_source_root_is_not_read_mapped_or_descended(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    for root in (source, target):
        (root / "quant-lab").mkdir(parents=True)
        (root / "quant-lab" / "sentinel.txt").write_text(
            "DENIED-DESCENDANT-CONTENT", encoding="utf-8"
        )
        (root / "allowed.txt").write_text("allowed", encoding="utf-8")
    project = ExplicitMigrationProject(
        manifest_id="wide-source-root",
        project_id="meta-flow",
        route_mode="project-first-worktree-v1",
        source_repository_id="artifact-control",
        target_repository_id="artifact-project-worktree",
        observed_at=FIXED_TIME,
        roots=(
            MigrationRoot(
                source_anchor="artifact_control_root",
                source_relative="process",
                source_runtime_root=source,
                target_anchor="project_worktree",
                target_relative="process",
                target_runtime_root=target,
            ),
        ),
        denied_paths=("process/quant-lab/**",),
        input_refs=("route:decision-digest", "worktree:observation-digest"),
    )
    lstat_paths: list[Path] = []
    opened_paths: list[Path] = []
    scanned_paths: list[Path] = []
    real_lstat = migration._lstat
    real_open = migration._open_binary
    real_scandir = migration._scandir

    def spy_lstat(path: Path):
        lstat_paths.append(Path(path))
        return real_lstat(path)

    def spy_open(path: Path):
        opened_paths.append(Path(path))
        return real_open(path)

    def spy_scandir(path: Path):
        scanned_paths.append(Path(path))
        return real_scandir(path)

    monkeypatch.setattr(migration, "_lstat", spy_lstat)
    monkeypatch.setattr(migration, "_open_binary", spy_open)
    monkeypatch.setattr(migration, "_scandir", spy_scandir)

    manifest = build_migration_manifest(
        project,
        _route(
            "meta-flow",
            target,
            source_relative="process",
            target_relative="process",
        ),
        _health("meta-flow", target),
        _metrics(),
    )
    payload = json.dumps(migration_manifest_to_dict(manifest), ensure_ascii=False)
    denied_runtime_roots = (source / "quant-lab", target / "quant-lab")

    assert manifest.readiness.decision != "READY"
    assert "denied-descendant" in manifest.readiness.reason_codes
    assert all(
        denied not in path.parents and path != denied
        for path in [*lstat_paths, *opened_paths, *scanned_paths]
        for denied in denied_runtime_roots
    )
    assert all("quant-lab" not in item.source.relative_path for item in manifest.mapping)
    assert all("quant-lab" not in item.target.relative_path for item in manifest.mapping)
    assert "DENIED-DESCENDANT-CONTENT" not in payload
    assert hashlib.sha256(b"DENIED-DESCENDANT-CONTENT").hexdigest() not in payload


def test_denied_target_descendant_blocks_before_source_lstat_or_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    for root in (source, target):
        (root / "quant-lab").mkdir(parents=True)
        (root / "quant-lab" / "secret.txt").write_text("TARGET-DENY-SENTINEL", encoding="utf-8")
    project = ExplicitMigrationProject(
        manifest_id="target-denied-descendant",
        project_id="meta-flow",
        route_mode="project-first-worktree-v1",
        source_repository_id="artifact-control",
        target_repository_id="artifact-project-worktree",
        observed_at=FIXED_TIME,
        roots=(
            MigrationRoot(
                source_anchor="artifact_control_root",
                source_relative="legacy/meta-flow",
                source_runtime_root=source,
                target_anchor="project_worktree",
                target_relative="process",
                target_runtime_root=target,
            ),
        ),
        denied_paths=("process/quant-lab/**",),
        input_refs=("route:decision-digest", "worktree:observation-digest"),
    )
    touched: list[Path] = []
    real_lstat = migration._lstat
    real_open = migration._open_binary

    def spy_lstat(path: Path):
        touched.append(Path(path))
        return real_lstat(path)

    def spy_open(path: Path):
        touched.append(Path(path))
        return real_open(path)

    monkeypatch.setattr(migration, "_lstat", spy_lstat)
    monkeypatch.setattr(migration, "_open_binary", spy_open)
    manifest = build_migration_manifest(
        project,
        _route(
            "meta-flow",
            target,
            source_relative="legacy/meta-flow",
            target_relative="process",
        ),
        _health("meta-flow", target),
        _metrics(),
    )
    payload = json.dumps(migration_manifest_to_dict(manifest), ensure_ascii=False)

    assert manifest.readiness.decision != "READY"
    assert "denied-target-descendant" in manifest.readiness.reason_codes
    assert all(
        source / "quant-lab" not in path.parents and path != source / "quant-lab"
        for path in touched
    )
    assert all("quant-lab" not in item.source.relative_path for item in manifest.mapping)
    assert all("quant-lab" not in item.target.relative_path for item in manifest.mapping)
    assert "TARGET-DENY-SENTINEL" not in payload


def test_relative_symlink_to_denied_descendant_does_not_probe_or_leak_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    for root in (source, target):
        (root / "quant-lab").mkdir(parents=True)
        (root / "quant-lab" / "secret.txt").write_text("SYMLINK-DENY-SENTINEL", encoding="utf-8")
        (root / "allowed-link").symlink_to("quant-lab/secret.txt")
    project = ExplicitMigrationProject(
        manifest_id="symlink-denied-target",
        project_id="meta-flow",
        route_mode="project-first-worktree-v1",
        source_repository_id="artifact-control",
        target_repository_id="artifact-project-worktree",
        observed_at=FIXED_TIME,
        roots=(
            MigrationRoot(
                source_anchor="artifact_control_root",
                source_relative="legacy/meta-flow",
                source_runtime_root=source,
                target_anchor="project_worktree",
                target_relative="process",
                target_runtime_root=target,
            ),
        ),
        denied_paths=("process/quant-lab/**",),
        input_refs=("route:decision-digest", "worktree:observation-digest"),
    )
    probed: list[Path] = []
    real_lstat = migration._lstat
    real_open = migration._open_binary

    def spy_lstat(path: Path):
        probed.append(Path(path))
        return real_lstat(path)

    def spy_open(path: Path):
        probed.append(Path(path))
        return real_open(path)

    monkeypatch.setattr(migration, "_lstat", spy_lstat)
    monkeypatch.setattr(migration, "_open_binary", spy_open)
    manifest = build_migration_manifest(
        project,
        _route(
            "meta-flow",
            target,
            source_relative="legacy/meta-flow",
            target_relative="process",
        ),
        _health("meta-flow", target),
        _metrics(),
    )
    payload = json.dumps(migration_manifest_to_dict(manifest), ensure_ascii=False)
    link = next(
        item for item in manifest.mapping if item.source.relative_path.endswith("allowed-link")
    )

    assert manifest.readiness.decision != "READY"
    assert "denied-symlink-target" in manifest.readiness.reason_codes
    assert all(
        denied not in path.parents and path != denied
        for path in probed
        for denied in (source / "quant-lab", target / "quant-lab")
    )
    assert link.link_target is None
    assert link.link_target_class == "relative-denied"
    assert "quant-lab/secret.txt" not in payload
    assert "SYMLINK-DENY-SENTINEL" not in payload


@pytest.mark.parametrize(
    ("metrics", "expected"),
    [
        (_metrics(weekly=(2, 2, 2, 2)), False),
        (_metrics(weekly=(3, 3, 3)), False),
        (_metrics(weekly=(3, 3, 3, 3)), True),
    ],
)
def test_t1_requires_at_least_three_syncs_for_four_consecutive_weeks(
    metrics: ManualSyncMetricsSummary, expected: bool
) -> None:
    result = evaluate_manual_sync_follow_up(metrics)

    assert result.thresholds[0].threshold_id == "O-AW-03-T1"
    assert result.thresholds[0].met is expected
    assert (result.candidate is not None) is expected


@pytest.mark.parametrize(
    ("duration", "expected"),
    [(600.0, False), (600.001, True)],
)
def test_t2_is_strictly_greater_than_ten_minutes(duration: float, expected: bool) -> None:
    result = evaluate_manual_sync_follow_up(_metrics(durations=(duration,)))

    assert result.thresholds[1].threshold_id == "O-AW-03-T2"
    assert result.thresholds[1].met is expected


@pytest.mark.parametrize(
    ("avoidable", "attempts", "expected"),
    [(1, 20, False), (2, 20, True)],
)
def test_t3_is_strictly_greater_than_five_percent(
    avoidable: int, attempts: int, expected: bool
) -> None:
    result = evaluate_manual_sync_follow_up(_metrics(avoidable=avoidable, attempts=attempts))

    assert result.thresholds[2].threshold_id == "O-AW-03-T3"
    assert result.thresholds[2].met is expected


def test_multiple_thresholds_generate_one_deduplicated_candidate() -> None:
    result = evaluate_manual_sync_follow_up(
        _metrics(
            weekly=(3, 3, 3, 3),
            durations=(601.0, 700.0),
            avoidable=2,
            attempts=20,
        )
    )

    assert result.decision == "follow-up-candidate"
    assert result.candidate is not None
    assert result.candidate.candidate_id == "conditional-sync-helper:meta-flow"
    assert result.candidate.reason_codes == (
        "O-AW-03-T1",
        "O-AW-03-T2",
        "O-AW-03-T3",
    )
    assert result.candidate.executable is False
    assert result.candidate.helper_enabled is False
    assert result.candidate.scheduler_registered is False
    assert result.candidate.remote_write_count == 0


@pytest.mark.parametrize(
    "metrics",
    [
        _metrics(complete=False),
        _metrics(classified=False),
        _metrics(durations=()),
        _metrics(attempts=0),
    ],
)
def test_incomplete_metrics_are_insufficient_data(metrics: ManualSyncMetricsSummary) -> None:
    result = evaluate_manual_sync_follow_up(metrics)

    assert result.decision == "insufficient-data"
    assert result.candidate is None
    assert all(item.met is None for item in result.thresholds)
