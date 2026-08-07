from __future__ import annotations

import subprocess
from hashlib import sha256
from pathlib import Path

import pytest

from meta_flow.project.scale import dump_yaml
from meta_flow.workflow import cr_index, cr_records
from meta_flow.workflow.legacy_evidence_registry import (
    ALLOWED_OPERATIONS,
    EVIDENCE_KIND,
    LegacyEvidenceError,
    LegacyEvidenceRegistration,
    convert_to_formal_cr,
    get_registered_follow_up,
    inspect_registered_legacy_evidence,
    list_registered_follow_ups,
    load_declared_legacy_evidence_registry,
    query_declared_legacy_evidence,
    validate_legacy_evidence_registry,
)


def _git_init(root: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)


def _binding_fixture(tmp_path: Path) -> tuple[Path, Path]:
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
    (process / "PROJECT.yaml").write_text(
        "schema_version: 1\nproject_id: consumer\nname: Consumer\nstatus: active\n",
        encoding="utf-8",
    )
    return release, process


def _registration(process: Path) -> LegacyEvidenceRegistration:
    evidence_ref = "process/legacy/CR-174.md"
    follow_up_ref = "process/legacy/CR-174-FOLLOW-UPS.yaml"
    evidence = process / evidence_ref.removeprefix("process/")
    follow_ups = process / follow_up_ref.removeprefix("process/")
    evidence.parent.mkdir(parents=True)
    evidence.write_bytes(
        b"# CR-174 legacy evidence\nstatus: closed\ndecision: PASS_WITH_RISK\n"
    )
    follow_ups.write_bytes(
        b"- id: FU-174-01\n  status: open\n  relationship: risk-follow-up\n"
        b"- id: FU-174-02\n  status: open\n  relationship: compatibility-follow-up\n"
        b"- id: FU-174-03\n  status: closed\n  relationship: evidence-follow-up\n"
    )
    return LegacyEvidenceRegistration(
        schema_version=1,
        registration_id="legacy-cr174-v1",
        project_id="consumer",
        consumer_id="provider-acceptance",
        evidence_kind=EVIDENCE_KIND,
        evidence_logical_ref=evidence_ref,
        evidence_sha256=sha256(evidence.read_bytes()).hexdigest(),
        follow_up_logical_ref=follow_up_ref,
        follow_up_sha256=sha256(follow_ups.read_bytes()).hexdigest(),
        expected_lifecycle="closed",
        expected_decision="PASS_WITH_RISK",
        expected_follow_up_count=3,
        expected_follow_up_ids=("FU-174-01", "FU-174-02", "FU-174-03"),
        expected_follow_up_statuses=(
            ("FU-174-01", "open"),
            ("FU-174-02", "open"),
            ("FU-174-03", "closed"),
        ),
        allowed_operations=ALLOWED_OPERATIONS,
    )


def test_exact_registered_legacy_evidence_and_follow_ups_are_queryable(
    tmp_path: Path,
) -> None:
    release, process = _binding_fixture(tmp_path)
    registration = _registration(process)
    assert validate_legacy_evidence_registry([registration]) == (registration,)

    view = inspect_registered_legacy_evidence(
        release,
        registration=registration,
        consumer_id="provider-acceptance",
    )

    assert view.compatibility_kind == "registered_legacy_closed_evidence"
    assert (view.lifecycle_view, view.readiness_view, view.gate_view) == (
        "closed",
        "ready_with_risk",
        "closed",
    )
    assert tuple(item.follow_up_id for item in list_registered_follow_ups(view)) == (
        "FU-174-01",
        "FU-174-02",
        "FU-174-03",
    )
    assert get_registered_follow_up(view, follow_up_id="FU-174-02").status == "open"
    with pytest.raises(LegacyEvidenceError) as conversion:
        convert_to_formal_cr(view)
    assert conversion.value.code == "legacy_evidence_formal_conversion_unsupported"


def test_registry_is_exact_bound_and_fails_closed_before_compatibility(
    tmp_path: Path,
) -> None:
    release, process = _binding_fixture(tmp_path)
    registration = _registration(process)
    evidence = process / registration.evidence_logical_ref.removeprefix("process/")
    evidence.write_bytes(evidence.read_bytes() + b"drift\n")

    with pytest.raises(LegacyEvidenceError) as mismatch:
        inspect_registered_legacy_evidence(
            release,
            registration=registration,
            consumer_id="provider-acceptance",
        )
    assert mismatch.value.code == "legacy_evidence_digest_mismatch"

    with pytest.raises(LegacyEvidenceError) as consumer:
        inspect_registered_legacy_evidence(
            release,
            registration=registration,
            consumer_id="other-consumer",
        )
    assert consumer.value.code == "legacy_evidence_consumer_mismatch"


def test_combined_legacy_status_and_relationship_free_follow_ups_are_preserved(
    tmp_path: Path,
) -> None:
    release, process = _binding_fixture(tmp_path)
    evidence_ref = "process/legacy/CR-174.md"
    follow_up_ref = "process/legacy/CR-174-FOLLOW-UPS.yaml"
    evidence = process / evidence_ref.removeprefix("process/")
    follow_ups = process / follow_up_ref.removeprefix("process/")
    evidence.parent.mkdir(parents=True)
    evidence.write_bytes(b"# CR-174\nstatus: closed-pass-with-risk\n")
    follow_ups.write_bytes(
        b"- id: FU-CR174-001\n  status: deferred_required\n"
        b"- id: FU-CR174-002\n  status: deferred\n"
        b"- id: FU-CR174-003\n  status: deferred\n"
    )
    registration = LegacyEvidenceRegistration(
        schema_version=1,
        registration_id="legacy-cr174-combined-v1",
        project_id="consumer",
        consumer_id="provider-acceptance",
        evidence_kind=EVIDENCE_KIND,
        evidence_logical_ref=evidence_ref,
        evidence_sha256=sha256(evidence.read_bytes()).hexdigest(),
        follow_up_logical_ref=follow_up_ref,
        follow_up_sha256=sha256(follow_ups.read_bytes()).hexdigest(),
        expected_lifecycle="closed-pass-with-risk",
        expected_decision="PASS_WITH_RISK",
        expected_follow_up_count=3,
        expected_follow_up_ids=(
            "FU-CR174-001",
            "FU-CR174-002",
            "FU-CR174-003",
        ),
        expected_follow_up_statuses=(
            ("FU-CR174-001", "deferred_required"),
            ("FU-CR174-002", "deferred"),
            ("FU-CR174-003", "deferred"),
        ),
        allowed_operations=ALLOWED_OPERATIONS,
    )

    view = inspect_registered_legacy_evidence(
        release,
        registration=registration,
        consumer_id="provider-acceptance",
    )

    assert view.legacy_lifecycle == "closed-pass-with-risk"
    assert view.legacy_decision == "PASS_WITH_RISK"
    assert all(item.relationship == "" for item in view.follow_ups)
    assert tuple(item.follow_up_id for item in view.follow_ups) == (
        "FU-CR174-001",
        "FU-CR174-002",
        "FU-CR174-003",
    )


def test_declared_consumer_registry_partitions_formal_discovery_and_exact_query(
    tmp_path: Path,
) -> None:
    release, process = _binding_fixture(tmp_path)
    evidence = process / "changes/CR-174-legacy.md"
    follow_ups = process / "works/CR-174/FOLLOW-UPS.yaml"
    evidence.parent.mkdir(parents=True)
    follow_ups.parent.mkdir(parents=True)
    evidence.write_bytes(b"# CR-174\nstatus: closed-pass-with-risk\n")
    follow_ups.write_bytes(
        b"- id: FU-CR174-001\n  status: deferred_required\n"
        b"- id: FU-CR174-002\n  status: deferred\n"
        b"- id: FU-CR174-003\n  status: deferred\n"
    )
    phase_ref = "phases/transition/PHASE.yaml"
    registry_ref = "phases/transition/CONSUMER-ACCEPTANCE-SPEC.yaml"
    (process / "PROJECT.yaml").write_text(
        dump_yaml(
            {
                "schema_version": 1,
                "project_id": "consumer",
                "name": "Consumer",
                "status": "active",
                "active_phase_ref": phase_ref,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    phase = process / phase_ref
    phase.parent.mkdir(parents=True)
    phase.write_text(
        dump_yaml(
            {
                "schema_version": 1,
                "project_id": "consumer",
                "phase_id": "transition",
                "status": "active",
                "result_refs": [registry_ref],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    registry = process / registry_ref
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
                        "sha256": sha256(evidence.read_bytes()).hexdigest(),
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
                            "FU-CR174-003": "deferred",
                        },
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    bundle = load_declared_legacy_evidence_registry(
        release,
        consumer_id="formal-cr-discovery",
    )
    cr_view = query_declared_legacy_evidence(release, query_id="CR-174")
    follow_up_view = query_declared_legacy_evidence(
        release,
        query_id="FU-CR174-002",
    )

    assert bundle.evidence_paths == (evidence.resolve(),)
    assert cr_view["classification"] == "immutable_legacy_closed_evidence"
    assert cr_view["legacy_lifecycle"] == "closed-pass-with-risk"
    assert cr_view["native_lifecycle_event_count"] == 0
    assert follow_up_view["follow_up_status"] == "deferred"
    excluded = frozenset(bundle.evidence_paths)
    assert cr_records.discover_formal_crs(
        release,
        excluded_legacy_paths=excluded,
    ) == {}
    assert cr_index.build_index(
        release,
        excluded_legacy_paths=excluded,
    )["items"] == []

    unregistered = process / "changes/CR-175-unregistered.md"
    unregistered.write_text("# not native\nstatus: closed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="non-native formal CR contamination"):
        cr_index.build_index(release, excluded_legacy_paths=excluded)


def test_legacy_registry_has_no_formal_index_or_lifecycle_dependency() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "meta_flow/workflow/legacy_evidence_registry.py"
    ).read_text(encoding="utf-8")
    assert "cr_tracking" not in source
    assert "cr_index" not in source
    assert "cr_lifecycle" not in source
    assert "convert_to_formal_cr" in source
