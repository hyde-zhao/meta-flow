from __future__ import annotations

import subprocess
from hashlib import sha256
from pathlib import Path

from meta_flow.project.scale import dump_yaml
from meta_flow.workflow.legacy_evidence_registry import (
    build_partition_report,
    discover_formal_cr_snapshot,
    load_legacy_registry_snapshot,
    snapshot_excluded_legacy_paths,
)


def _git_init(root: Path) -> None:
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=root,
        check=True,
        capture_output=True,
    )


def _write_native_cr(process: Path, cr_id: str, *, suffix: str = "") -> Path:
    path = process / "changes" / f"{cr_id}{suffix}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        "schema_version: 1\n"
        "kind: cr\n"
        f"cr_id: {cr_id}\n"
        "cr_type: architecture\n"
        'title: "native fixture"\n'
        "lifecycle_status: active\n"
        "readiness_status: NOT_READY\n"
        "gate_status: cp2_pending\n"
        "gate_profile: standard-code\n"
        "---\n\n"
        "native body\n",
        encoding="utf-8",
    )
    return path


def _formal_partition_fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, Path]]:
    release = tmp_path / "consumer"
    process = tmp_path / "consumer-process"
    release.mkdir()
    process.mkdir()
    _git_init(release)
    _git_init(process)

    (release / ".meta-flow").mkdir()
    (release / ".meta-flow" / "workspace.yaml").write_text(
        dump_yaml(
            {
                "schema_version": 1,
                "layout_version": "independent-process-repo-v1",
                "workflow_model": "vnext",
                "project_id": "consumer",
                "repo_role": "release",
                "route_mode": "sibling-binding",
                "process_repo": {
                    "anchor": "workspace_parent",
                    "relative_path": "consumer-process",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (process / ".meta-flow-process.yaml").write_text(
        dump_yaml(
            {
                "schema_version": 1,
                "layout_version": "independent-process-repo-v1",
                "workflow_model": "vnext",
                "project_id": "consumer",
                "repo_role": "process",
                "route_mode": "sibling-binding",
                "release_repo": {
                    "anchor": "workspace_parent",
                    "relative_path": "consumer",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    registry_ref = "process/governance/CONSUMER-ACCEPTANCE-SPEC.yaml"
    project = process / "PROJECT.yaml"
    project.write_text(
        dump_yaml(
            {
                "schema_version": 1,
                "project_id": "consumer",
                "name": "Consumer",
                "status": "active",
                "legacy_evidence_registry_ref": registry_ref,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    legacy = process / "changes/CR-174-legacy.md"
    follow_ups = process / "works/CR-174/FOLLOW-UPS.yaml"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    follow_ups.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_bytes(b"# CR-174\nstatus: closed-pass-with-risk\n")
    follow_ups.write_bytes(
        b"- id: FU-CR174-001\n  status: deferred_required\n- id: FU-CR174-002\n  status: deferred\n"
    )

    registry = process / "governance/CONSUMER-ACCEPTANCE-SPEC.yaml"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(
        dump_yaml(
            {
                "schema_version": 1,
                "project_id": "consumer",
                "spec_id": "consumer-provider-acceptance-v1",
                "spec_status": "ready-for-provider-delivery",
                "immutable_consumer_inputs": [
                    {
                        "id": "CR174-BODY",
                        "ref": "changes/CR-174-legacy.md",
                        "sha256": sha256(legacy.read_bytes()).hexdigest(),
                    },
                    {
                        "id": "CR174-FOLLOW-UPS",
                        "ref": "works/CR-174/FOLLOW-UPS.yaml",
                        "sha256": sha256(follow_ups.read_bytes()).hexdigest(),
                    },
                ],
                "fixture_contract": [
                    {
                        "id": "FOLLOW-UPS-IMMUTABLE",
                        "source": "CR174-FOLLOW-UPS",
                        "expected": {
                            "FU-CR174-001": "deferred_required",
                            "FU-CR174-002": "deferred",
                        },
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    native = _write_native_cr(process, "CR-175")
    return (
        release,
        process,
        {
            "project": project,
            "registry": registry,
            "legacy": legacy,
            "follow_ups": follow_ups,
            "native": native,
        },
    )


def test_registered_legacy_and_native_cr_share_one_consistent_partition(
    tmp_path: Path,
) -> None:
    release, _process, paths = _formal_partition_fixture(tmp_path)
    protected_bytes = {
        name: paths[name].read_bytes() for name in ("registry", "legacy", "follow_ups")
    }

    registry = load_legacy_registry_snapshot(release)
    snapshot = discover_formal_cr_snapshot(release, registry)
    report = build_partition_report(snapshot)

    assert registry.registered_legacy_ids == ("CR-174",)
    assert registry.excluded_legacy_refs == ("process/changes/CR-174-legacy.md",)
    assert snapshot.native_formal_cr_refs == ("process/changes/CR-175.md",)
    assert snapshot.registered_legacy_refs == ("process/changes/CR-174-legacy.md",)
    assert snapshot.unregistered_contamination_refs == ()
    assert snapshot.overlap_conflicts == ()
    assert report.decision == "PASS"
    assert report.reason_codes == ("FORMAL_CR_PARTITION_CONSISTENT",)
    assert snapshot_excluded_legacy_paths(release, snapshot) == frozenset(
        {paths["legacy"].resolve()}
    )
    assert {
        name: paths[name].read_bytes() for name in ("registry", "legacy", "follow_ups")
    } == protected_bytes


def test_unregistered_non_native_cr_is_preserved_as_blocking_contamination(
    tmp_path: Path,
) -> None:
    release, process, _paths = _formal_partition_fixture(tmp_path)
    contamination = process / "changes/CR-176-unregistered.md"
    contamination.write_text("# non-native CR evidence\nstatus: closed\n", encoding="utf-8")

    snapshot = discover_formal_cr_snapshot(
        release,
        load_legacy_registry_snapshot(release),
    )
    report = build_partition_report(snapshot)

    assert snapshot.unregistered_contamination_refs == ("process/changes/CR-176-unregistered.md",)
    assert report.decision == "BLOCKED"
    assert report.reason_codes == ("UNREGISTERED_NON_NATIVE_CR",)
    assert "process/changes/CR-176-unregistered.md" in report.evidence_refs


def test_snapshot_digests_are_deterministic_and_sensitive_to_discovery_inputs(
    tmp_path: Path,
) -> None:
    release, _process, paths = _formal_partition_fixture(tmp_path)

    registry_first = load_legacy_registry_snapshot(release)
    registry_second = load_legacy_registry_snapshot(release)
    snapshot_first = discover_formal_cr_snapshot(release, registry_first)
    snapshot_second = discover_formal_cr_snapshot(release, registry_second)

    assert registry_first == registry_second
    assert snapshot_first == snapshot_second
    assert snapshot_first.snapshot_digest == snapshot_second.snapshot_digest

    paths["native"].write_text(
        paths["native"].read_text(encoding="utf-8") + "native drift\n",
        encoding="utf-8",
    )
    source_changed = discover_formal_cr_snapshot(release, registry_first)
    assert source_changed.process_tree_manifest_digest != (
        snapshot_first.process_tree_manifest_digest
    )
    assert source_changed.snapshot_digest != snapshot_first.snapshot_digest
    assert source_changed.excluded_paths_digest == snapshot_first.excluded_paths_digest

    paths["registry"].write_text(
        paths["registry"].read_text(encoding="utf-8") + "audit_note: registry-byte-drift\n",
        encoding="utf-8",
    )
    registry_changed = load_legacy_registry_snapshot(release)
    registry_changed_snapshot = discover_formal_cr_snapshot(release, registry_changed)
    assert registry_changed.registry_payload_digest != (registry_first.registry_payload_digest)
    assert registry_changed.excluded_paths_digest == registry_first.excluded_paths_digest
    assert registry_changed_snapshot.snapshot_digest != source_changed.snapshot_digest


def test_native_and_registered_legacy_id_overlap_is_blocking(
    tmp_path: Path,
) -> None:
    release, process, _paths = _formal_partition_fixture(tmp_path)
    native_overlap = _write_native_cr(process, "CR-174", suffix="-native")

    snapshot = discover_formal_cr_snapshot(
        release,
        load_legacy_registry_snapshot(release),
    )
    report = build_partition_report(snapshot)

    assert native_overlap.exists()
    assert "process/changes/CR-174-native.md" in snapshot.native_formal_cr_refs
    assert any(
        conflict.startswith("native_legacy_id_overlap:CR-174:")
        for conflict in snapshot.overlap_conflicts
    )
    assert report.decision == "BLOCKED"
    assert report.reason_codes == ("LEGACY_NATIVE_OVERLAP_OR_CONFLICT",)
