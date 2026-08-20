from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from test_cr_status_sync import write_termination_fixture
from test_post_close import _fixture as post_close_fixture
from test_status_sync_partition import _enable_registered_legacy

from meta_flow.checks import adoption_readiness, cr_tracking, post_close
from meta_flow.project.scale import dump_yaml, load_yaml_object
from meta_flow.state import formal_projection
from meta_flow.workflow import cr_analysis
from meta_flow.workflow.legacy_evidence_registry import load_formal_cr_partition


def test_registered_legacy_is_excluded_from_authoritative_cr_check(
    tmp_path: Path,
) -> None:
    release, process, _cr_path, _scope = write_termination_fixture(tmp_path)
    paths = _enable_registered_legacy(release, process)
    protected = {name: paths[name].read_bytes() for name in ("legacy", "follow_ups", "registry")}

    _registry, snapshot, partition = load_formal_cr_partition(
        release,
        consumer_id="cr074-authoritative-fixture",
    )
    lifecycle = cr_analysis.build_cr_lifecycle_check_report(
        release,
        partition_snapshot=snapshot,
        partition_report=partition,
    )
    tracking = cr_tracking.build_cr_tracking_report(partition)

    assert partition.decision == "PASS"
    assert tracking.native_cr_ids == ("CR-101",)
    assert tracking.registered_legacy_ids == ("CR-174",)
    assert tracking.partition_snapshot_digest == lifecycle.partition_snapshot_digest
    assert not any("CR-174" in error for error in lifecycle.errors)
    assert not any("non-native formal CR contamination" in error for error in lifecycle.errors)
    assert {
        name: paths[name].read_bytes() for name in ("legacy", "follow_ups", "registry")
    } == protected


def test_state_projection_consumes_same_partition_digest_and_excludes_legacy(
    tmp_path: Path,
) -> None:
    release, process, _cr_path, _scope = write_termination_fixture(tmp_path)
    _enable_registered_legacy(release, process)
    project_path = process / "PROJECT.yaml"
    project = load_yaml_object(project_path)
    project["roadmap_ref"] = "ROADMAP.yaml"
    project_path.write_text(dump_yaml(project) + "\n", encoding="utf-8")
    (process / "ROADMAP.yaml").write_text(
        dump_yaml(
            {
                "schema_version": 1,
                "project_id": project["project_id"],
                "status": "active",
                "phase_refs": ["phases/P1/PHASE.yaml"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    phase_path = process / "phases/P1/PHASE.yaml"
    phase_path.parent.mkdir(parents=True, exist_ok=True)
    phase_path.write_text(
        dump_yaml(
            {
                "schema_version": 1,
                "phase_id": "P1",
                "status": "active",
                "work_refs": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _registry, snapshot, partition = load_formal_cr_partition(
        release,
        consumer_id="cr074-state-fixture",
    )

    projected = formal_projection.build_formal_truth_snapshot(release)

    assert partition.decision == "PASS"
    assert projected["partition_snapshot_digest"] == snapshot.snapshot_digest
    assert "process/changes/CR-101.md" in projected["source_refs"]
    assert "CR-174" not in projected["active_cr_ids"]
    assert "process/changes/CR-174-legacy.md" not in projected["source_refs"]


def test_public_cr_tracking_path_does_not_rediscover_after_partition(
    tmp_path: Path,
) -> None:
    release, process, _cr_path, _scope = write_termination_fixture(tmp_path)
    _enable_registered_legacy(release, process)

    with patch.object(
        cr_tracking,
        "discover_formal_crs",
        side_effect=AssertionError("tracking consumer must use the shared partition"),
    ):
        exit_code = cr_tracking.main(["--project-root", str(release)])

    # fixture 可以因未完成的非分区治理证据返回普通 audit FAIL，但不能因
    # legacy contamination 或二次 discovery 进入 operational BLOCKED。
    assert exit_code in {0, 1}


def test_unregistered_contamination_propagates_without_doctor_downgrade(
    tmp_path: Path,
) -> None:
    release, process, _cr_path, _scope = write_termination_fixture(tmp_path)
    contamination = process / "changes/CR-174-unregistered.md"
    contamination.write_text("# legacy but unregistered\nstatus: closed\n", encoding="utf-8")

    lifecycle = cr_analysis.build_cr_lifecycle_check_report(release)
    item = adoption_readiness._cr_tracking_item(
        release,
        process,
        authoritative_report=lifecycle,
    )

    assert lifecycle.decision == "BLOCKED"
    assert lifecycle.reason_codes == ("UNREGISTERED_NON_NATIVE_CR",)
    assert item.status == "FAIL"
    assert item.messages[-1] == lifecycle.errors[0]
    assert "process/changes/CR-174-unregistered.md" in lifecycle.errors[0]


def test_doctor_fails_closed_when_authoritative_child_reports_are_missing(
    tmp_path: Path,
) -> None:
    process = tmp_path / "process"
    process.mkdir()

    tracking = adoption_readiness._cr_tracking_item(
        tmp_path,
        process,
        authoritative_report=None,
        authoritative_required=True,
    )
    human_gate = adoption_readiness._human_gate_item(
        tmp_path,
        process,
        binding_aware=True,
        partition_report=None,
        authoritative_required=True,
    )

    assert tracking.status == "FAIL"
    assert tracking.messages == ["AUTHORITATIVE_CR_CHILD_REPORT_MISSING"]
    assert human_gate.status == "FAIL"
    assert "AUTHORITATIVE_FORMAL_CR_PARTITION_REPORT_MISSING" in human_gate.messages


def test_post_close_accepts_ready_no_issue_no_follow_up_profile(
    tmp_path: Path,
) -> None:
    release = post_close_fixture(tmp_path)
    process = tmp_path / "process"
    cr_path = process / "changes/CR-101.md"
    cr_path.write_text(
        cr_path.read_text(encoding="utf-8").replace(
            "readiness_status: READY_WITH_RISK",
            "readiness_status: READY",
        ),
        encoding="utf-8",
    )
    result_path = process / "checks/CP8-FINAL.result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["release_decision"] = "READY"
    result_path.write_text(json.dumps(result) + "\n", encoding="utf-8")
    release_context_path = process / "release/RELEASE-CONTEXT.yaml"
    release_context = json.loads(release_context_path.read_text(encoding="utf-8"))
    reconciliation = release_context["closure_reconciliation"]
    reconciliation["resolved_issue_refs"] = []
    reconciliation.pop("follow_up_tracking_ref")
    release_context_path.write_text(json.dumps(release_context) + "\n", encoding="utf-8")

    checked = post_close.check_post_close(release, "CR-101")

    assert checked["decision"] == "PASS"
    assert checked["post_close_profile"] == {
        "allowed_readiness": ["READY", "READY_WITH_RISK"],
        "allowed_phase_statuses": ["active", "completed"],
        "issue_refs_required": False,
        "follow_up_tracking_required": False,
        "follow_up_candidate_required": False,
    }
    assert checked["partition_snapshot_digest"]


def test_required_set_does_not_expand_when_registry_adds_unrelated_alias(
    tmp_path: Path,
) -> None:
    release = post_close_fixture(tmp_path)
    process = tmp_path / "process"
    first = post_close.check_post_close(release, "CR-101")
    registry_path = process / "docs/design/CAPABILITY-REGISTRY.yaml"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["capabilities"].append(
        {
            "id": "CAP-UNRELATED",
            "name": "Unrelated",
            "domain": "fixture",
            "status": "active",
            "owner_context": "fixture",
            "feature_refs": ["feature.one"],
            "concept_refs": [],
            "aliases": ["unrelated-alias"],
            "deprecated_by": "",
            "source_refs": ["meta_flow/example.py"],
        }
    )
    registry_path.write_text(json.dumps(registry) + "\n", encoding="utf-8")

    second = post_close.check_post_close(release, "CR-101")

    assert first["decision"] == second["decision"] == "PASS"
    assert first["required_capability_set"]["required_aliases"] == ["cap-one"]
    assert (
        first["required_capability_set"]["required_set_digest"]
        == (second["required_capability_set"]["required_set_digest"])
    )
    assert (
        first["capability_resolution"]["registry_digest"]
        != (second["capability_resolution"]["registry_digest"])
    )


def test_release_context_cannot_expand_empty_approved_capability_scope(
    tmp_path: Path,
) -> None:
    release = post_close_fixture(tmp_path)
    cr_path = tmp_path / "process/changes/CR-101.md"
    cr_path.write_text(
        cr_path.read_text(encoding="utf-8").replace(
            "impact_capability_refs: [cap-one]\n",
            "impact_capability_refs: []\n",
        ),
        encoding="utf-8",
    )

    result = post_close.check_post_close(release, "CR-101")

    assert result["decision"] == "BLOCKED"
    assert "POST_CLOSE_REQUIRED_CAPABILITY_SCOPE_MISMATCH" in {
        finding["code"] for finding in result["findings"]
    }
    assert result["required_capability_set"]["approved_scope_ref"] == (
        "process/changes/CR-101.md"
    )
    assert result["required_capability_set"]["required_aliases"] == []
