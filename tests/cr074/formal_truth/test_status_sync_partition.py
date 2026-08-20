from __future__ import annotations

import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

import pytest
from test_cr_status_sync import _authorization, write_termination_fixture

from meta_flow.project.scale import dump_yaml, load_yaml_object
from meta_flow.workflow import cr_index, cr_status_sync
from meta_flow.workflow.legacy_evidence_registry import (
    discover_formal_cr_snapshot,
    load_legacy_registry_snapshot,
    snapshot_excluded_legacy_paths,
)


def _enable_registered_legacy(release: Path, process: Path) -> dict[str, Path]:
    project_path = process / "PROJECT.yaml"
    project = load_yaml_object(project_path)
    project["legacy_evidence_registry_ref"] = "process/governance/CONSUMER-ACCEPTANCE-SPEC.yaml"
    project_path.write_text(dump_yaml(project) + "\n", encoding="utf-8")

    legacy = process / "changes/CR-174-legacy.md"
    follow_ups = process / "works/CR-174/FOLLOW-UPS.yaml"
    registry = process / "governance/CONSUMER-ACCEPTANCE-SPEC.yaml"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    follow_ups.parent.mkdir(parents=True, exist_ok=True)
    registry.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_bytes(b"# CR-174\nstatus: closed-pass-with-risk\n")
    follow_ups.write_bytes(b"- id: FU-CR174-001\n  status: deferred_required\n")
    registry.write_text(
        dump_yaml(
            {
                "schema_version": 1,
                "project_id": project["project_id"],
                "spec_id": "cr074-status-sync-fixture-v1",
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
                        "expected": {"FU-CR174-001": "deferred_required"},
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    snapshot = discover_formal_cr_snapshot(
        release,
        load_legacy_registry_snapshot(release),
    )
    index = cr_index.build_index(
        release,
        excluded_legacy_paths=snapshot_excluded_legacy_paths(release, snapshot),
        discovery_snapshot=snapshot,
    )
    index_path = process / "changes/CR-INDEX.json"
    index_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "project": project_path,
        "legacy": legacy,
        "follow_ups": follow_ups,
        "registry": registry,
    }


def _plan(release: Path) -> cr_status_sync.StatusSyncPlan:
    return cr_status_sync.plan_status_sync(
        release,
        "CR-101",
        status="closed",
        readiness="READY_WITH_RISK",
        gate_status="cp8_closed",
        work_id="WORK-101",
        effective_at="2026-08-20T09:00:00+00:00",
    )


def test_plan_uses_one_snapshot_for_discovery_and_both_index_projections(
    tmp_path: Path,
) -> None:
    release, process, _cr_path, _scope = write_termination_fixture(tmp_path)
    paths = _enable_registered_legacy(release, process)
    protected = {name: paths[name].read_bytes() for name in ("legacy", "follow_ups", "registry")}

    with patch.object(
        cr_status_sync,
        "build_index",
        wraps=cr_status_sync.build_index,
    ) as index_builder:
        plan = _plan(release)

    assert plan.decision == "READY"
    assert plan.admission is not None
    assert (
        plan.admission.snapshot_digest
        == (plan.expected_facts["formal_cr_discovery_snapshot_digest"])
    )
    assert index_builder.call_count == 2
    snapshots = [call.kwargs["discovery_snapshot"] for call in index_builder.call_args_list]
    assert snapshots[0] is snapshots[1]
    assert snapshots[0].registered_legacy_ids == ("CR-174",)
    assert {
        name: paths[name].read_bytes() for name in ("legacy", "follow_ups", "registry")
    } == protected


def test_snapshot_mode_forbids_consumer_local_rediscovery(tmp_path: Path) -> None:
    release, process, _cr_path, _scope = write_termination_fixture(tmp_path)
    _enable_registered_legacy(release, process)

    with patch.object(
        cr_index,
        "discover_formal_crs",
        side_effect=AssertionError("snapshot consumer must not rediscover formal CR files"),
    ):
        plan = _plan(release)

    assert plan.decision == "READY"
    assert plan.mutation_plan.target_preimages


def test_mutation_plan_v2_has_path_ordered_closed_identity(tmp_path: Path) -> None:
    release, process, _cr_path, _scope = write_termination_fixture(tmp_path)
    _enable_registered_legacy(release, process)
    plan = _plan(release)
    mutation = plan.mutation_plan
    reversed_mutation = replace(plan, targets=tuple(reversed(plan.targets))).mutation_plan

    assert mutation.exact_target_refs == tuple(sorted(mutation.exact_target_refs))
    assert mutation.as_dict()["exact_target_set_digest"] == mutation.exact_target_set_digest
    assert mutation.as_dict()["target_preimages_digest"] == mutation.target_preimages_digest
    assert mutation.as_dict()["operation_digest"] == mutation.operation_digest
    assert mutation.plan_digest == reversed_mutation.plan_digest

    changed_preimages = list(mutation.target_preimages)
    changed_preimages[0] = (changed_preimages[0][0], "f" * 64)
    preimage_drift = replace(mutation, target_preimages=tuple(changed_preimages))
    assert preimage_drift.target_preimages_digest != mutation.target_preimages_digest
    assert preimage_drift.plan_digest != mutation.plan_digest

    changed_refs = list(mutation.target_preimages)
    changed_afters = list(mutation.target_afterimages)
    changed_refs[0] = ("process/changes/CR-000.md", changed_refs[0][1])
    changed_afters[0] = ("process/changes/CR-000.md", changed_afters[0][1])
    ref_drift = replace(
        mutation,
        target_preimages=tuple(sorted(changed_refs)),
        target_afterimages=tuple(sorted(changed_afters)),
    )
    assert ref_drift.exact_target_set_digest != mutation.exact_target_set_digest
    assert ref_drift.plan_digest != mutation.plan_digest

    operation_drift = replace(
        mutation,
        operation="cr.status-sync.other",
        operation_digest="e" * 64,
    )
    assert operation_drift.operation_digest != mutation.operation_digest
    assert operation_drift.plan_digest != mutation.plan_digest

    duplicate = (mutation.target_preimages[0], mutation.target_preimages[0])
    with pytest.raises(ValueError, match="unique path ordering"):
        replace(
            mutation,
            target_preimages=duplicate,
            target_afterimages=duplicate,
        )


def test_registry_drift_after_outer_compare_is_blocked_under_writer_lock(
    tmp_path: Path,
) -> None:
    release, process, _cr_path, _scope = write_termination_fixture(tmp_path)
    paths = _enable_registered_legacy(release, process)
    plan = _plan(release)
    authorization = _authorization(
        plan,
        authorization_id="AUTH-CR074-LOCK-DRIFT-001",
    )
    target_preimages = {
        target.ref: (target.path.read_bytes() if target.path.is_file() else None)
        for target in plan.targets
    }
    original_apply = cr_status_sync._apply_status_sync_transaction

    def drift_then_enter_transaction(*args: object, **kwargs: object) -> dict[str, object]:
        paths["registry"].write_text(
            paths["registry"].read_text(encoding="utf-8")
            + "audit_note: drift-after-outer-compare\n",
            encoding="utf-8",
        )
        return original_apply(*args, **kwargs)

    with (
        patch.object(
            cr_status_sync,
            "_dirty_path_digest",
            return_value=plan.expected_facts["dirty_path_digest"],
        ),
        patch.object(
            cr_status_sync,
            "_apply_status_sync_transaction",
            side_effect=drift_then_enter_transaction,
        ),
    ):
        result = cr_status_sync.apply_status_sync(
            release,
            plan,
            authorization=authorization,
            expected_plan_digest=plan.plan_digest,
        )

    assert result["status"] == "BLOCKED"
    assert "lock-bound OperationAdmissionV1 drifted" in str(result["reason"])
    assert result["mutation_count"] == 0
    assert {
        target.ref: (target.path.read_bytes() if target.path.is_file() else None)
        for target in plan.targets
    } == target_preimages
    assert not list(process.rglob(f"{authorization.authorization_id}.json"))


def test_registry_drift_after_preview_blocks_before_any_mutation_or_claim(
    tmp_path: Path,
) -> None:
    release, process, _cr_path, _scope = write_termination_fixture(tmp_path)
    paths = _enable_registered_legacy(release, process)
    plan = _plan(release)
    authorization = _authorization(
        plan,
        authorization_id="AUTH-CR074-REGISTRY-DRIFT-001",
    )
    target_preimages = {
        target.ref: (target.path.read_bytes() if target.path.is_file() else None)
        for target in plan.targets
    }

    paths["registry"].write_text(
        paths["registry"].read_text(encoding="utf-8") + "audit_note: preview-after-drift\n",
        encoding="utf-8",
    )
    with patch.object(
        cr_status_sync,
        "_dirty_path_digest",
        return_value=plan.expected_facts["dirty_path_digest"],
    ):
        result = cr_status_sync.apply_status_sync(
            release,
            plan,
            authorization=authorization,
            expected_plan_digest=plan.plan_digest,
        )

    assert result == {
        "status": "BLOCKED",
        "reason": "status-sync OperationAdmissionV1 drifted",
        "mutation_count": 0,
    }
    assert {
        target.ref: (target.path.read_bytes() if target.path.is_file() else None)
        for target in plan.targets
    } == target_preimages
    assert not list(process.rglob(f"{authorization.authorization_id}.json"))
    assert (
        json.loads((process / "changes/CR-INDEX.json").read_text(encoding="utf-8"))["items"][0][
            "id"
        ]
        == "CR-101"
    )


def test_successful_apply_keeps_registered_legacy_bytes_immutable(
    tmp_path: Path,
) -> None:
    release, process, _cr_path, _scope = write_termination_fixture(tmp_path)
    paths = _enable_registered_legacy(release, process)
    protected = {name: paths[name].read_bytes() for name in ("legacy", "follow_ups", "registry")}
    plan = _plan(release)

    result = cr_status_sync.apply_status_sync(
        release,
        plan,
        authorization=_authorization(
            plan,
            authorization_id="AUTH-CR074-REGISTRY-SUCCESS-001",
        ),
        expected_plan_digest=plan.plan_digest,
    )

    assert result["status"] == "PASS"
    assert result["mutation_count"] > 0
    assert {
        name: paths[name].read_bytes() for name in ("legacy", "follow_ups", "registry")
    } == protected
    index = json.loads((process / "changes/CR-INDEX.json").read_text(encoding="utf-8"))
    assert [item["id"] for item in index["items"]] == ["CR-101"]
