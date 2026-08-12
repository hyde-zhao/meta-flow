from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from meta_flow.policies import governance
from meta_flow.project import governance_projection


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _commit_all(root: Path, message: str) -> str:
    _git(root, "add", ".")
    _git(
        root,
        "-c",
        "user.name=Meta Flow Test",
        "-c",
        "user.email=meta-flow@example.invalid",
        "commit",
        "-m",
        message,
    )
    return _git(root, "rev-parse", "HEAD")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _bind(release: Path, process: Path, *, project_id: str = "demo") -> None:
    _write(
        release / ".meta-flow/workspace.yaml",
        json.dumps(
            {
                "schema_version": 1,
                "layout_version": "independent-process-repo-v1",
                "workflow_model": "vnext",
                "project_id": project_id,
                "repo_role": "release",
                "route_mode": "sibling-binding",
                "process_repo": {
                    "anchor": "workspace_parent",
                    "relative_path": process.name,
                },
            }
        )
        + "\n",
    )
    _write(
        process / ".meta-flow-process.yaml",
        json.dumps(
            {
                "schema_version": 1,
                "layout_version": "independent-process-repo-v1",
                "workflow_model": "vnext",
                "project_id": project_id,
                "repo_role": "process",
                "route_mode": "sibling-binding",
                "release_repo": {
                    "anchor": "workspace_parent",
                    "relative_path": release.name,
                },
            }
        )
        + "\n",
    )


def _fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    release = tmp_path / "release"
    process = tmp_path / "process"
    release.mkdir()
    process.mkdir()
    _git(release, "init", "-b", "main")
    _git(process, "init", "-b", "main")
    _bind(release, process)
    _write(release / "README.md", "# release\n")
    release_oid = _commit_all(release, "release baseline")

    _write(
        process / "PROJECT.yaml",
        """schema_version: 1
project_id: demo
name: Demo
status: active
objective: demo governance
roadmap_ref: ROADMAP.yaml
""",
    )
    _write(
        process / "ROADMAP.yaml",
        """schema_version: 1
project_id: demo
outcome: demo
status: active
phase_refs:
  - phases/P1/PHASE.yaml
  - phases/P2/PHASE.yaml
""",
    )
    _write(
        process / "phases/P1/PHASE.yaml",
        """schema_version: 1
project_id: demo
phase_id: P1
objective: completed
status: completed
work_refs: []
result_refs:
  - phases/P1/RESULT.json
""",
    )
    _write(process / "phases/P1/RESULT.json", "{}\n")
    _write(
        process / "phases/P2/PHASE.yaml",
        """schema_version: 1
project_id: demo
phase_id: P2
objective: active
status: active
work_refs: []
result_refs:
  - governance/GOVERNANCE-BASELINE.json
  - phases/P2/RESULT.json
""",
    )
    _write(process / "phases/P2/RESULT.json", "{}\n")
    projection_path = process / governance_projection.GOVERNANCE_PROJECTION_REL
    _write(projection_path, "{}\n")
    process_baseline_oid = _commit_all(process, "process truth baseline")

    payload: dict[str, object] = {
        "schema_version": 1,
        "kind": governance_projection.GOVERNANCE_PROJECTION_KIND,
        **governance_projection.build_governance_truth(process),
        "immutable_commit_roles": [
            {
                "role": "release_input_baseline",
                "repository": "release",
                "oid": release_oid,
            },
            {
                "role": "process_evidence_baseline",
                "repository": "process",
                "oid": process_baseline_oid,
            },
        ],
        "runtime_identity_roles": list(governance_projection.RUNTIME_IDENTITY_ROLES),
    }
    payload["semantic_digest"] = governance_projection.semantic_digest(payload)
    projection_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _commit_all(process, "publish governance projection")
    return release, process, payload


def _writer_fixture(
    tmp_path: Path,
) -> tuple[Path, Path, tuple[governance_projection.ImmutableCommitRole, ...]]:
    release, process, _payload = _fixture(tmp_path)
    (process / governance_projection.GOVERNANCE_PROJECTION_REL).unlink()
    process_oid = _commit_all(process, "remove manually maintained projection")
    roles = (
        governance_projection.ImmutableCommitRole(
            "release_input_baseline",
            "release",
            _git(release, "rev-parse", "HEAD"),
        ),
        governance_projection.ImmutableCommitRole(
            "process_evidence_baseline",
            "process",
            process_oid,
        ),
    )
    return release, process, roles


def test_governance_projection_rebuilds_declared_truth_and_runtime_identity(
    tmp_path: Path,
) -> None:
    release, process, payload = _fixture(tmp_path)

    result = governance_projection.validate_governance_projection(release, process)

    assert result["decision"] == "PASS"
    assert result["errors"] == []
    assert result["runtime_identity"] == {
        "release_head": _git(release, "rev-parse", "HEAD"),
        "process_head": _git(process, "rev-parse", "HEAD"),
    }
    assert "release_head_oid" not in payload
    assert "process_head_oid" not in payload
    assert payload["active_phase_refs"] == ["process/phases/P2/PHASE.yaml"]


def test_governance_projection_blocks_phase_status_drift(tmp_path: Path) -> None:
    release, process, _payload = _fixture(tmp_path)
    phase = process / "phases/P1/PHASE.yaml"
    phase.write_text(
        phase.read_text(encoding="utf-8").replace("status: completed", "status: planned"),
        encoding="utf-8",
    )

    result = governance_projection.validate_governance_projection(release, process)

    assert result["decision"] == "BLOCKED"
    assert "governance projection phase_statuses differs from declared truth" in result["errors"]


def test_governance_projection_blocks_duplicate_active_phase(tmp_path: Path) -> None:
    release, process, _payload = _fixture(tmp_path)
    phase = process / "phases/P1/PHASE.yaml"
    phase.write_text(
        phase.read_text(encoding="utf-8").replace("status: completed", "status: active"),
        encoding="utf-8",
    )

    result = governance_projection.validate_governance_projection(release, process)

    assert result["decision"] == "BLOCKED"
    assert result["errors"] == [
        "an active PROJECT must have exactly one active declared Phase: found 2"
    ]


def test_governance_projection_blocks_repository_role_mixup(tmp_path: Path) -> None:
    release, process, payload = _fixture(tmp_path)
    roles = payload["immutable_commit_roles"]
    assert isinstance(roles, list)
    roles[0]["repository"] = "process"  # type: ignore[index]
    payload["semantic_digest"] = governance_projection.semantic_digest(payload)
    (process / governance_projection.GOVERNANCE_PROJECTION_REL).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    result = governance_projection.validate_governance_projection(release, process)

    assert result["decision"] == "BLOCKED"
    assert any(
        "immutable commit role release_input_baseline does not exist in process" in error
        for error in result["errors"]
    )


def test_governance_baseline_refresh_plan_is_zero_write_and_supports_first_create(
    tmp_path: Path,
) -> None:
    release, process, roles = _writer_fixture(tmp_path)
    target = process / governance_projection.GOVERNANCE_PROJECTION_REL

    plan = governance_projection.plan_governance_baseline_refresh(
        release,
        process,
        project_id="demo",
        immutable_commit_roles=roles,
    )

    assert plan.decision == "READY"
    assert plan.target_preimage == "absent"
    assert plan.planned_mutation_count == 1
    assert plan.as_dict()["mutation_count"] == 0
    assert plan.as_dict()["transaction"] == {
        "strategy": "single-file-atomic-replace",
        "recovery_required": False,
    }
    assert not target.exists()


def test_governance_baseline_refresh_apply_and_noop_are_typed_and_validated(
    tmp_path: Path,
) -> None:
    release, process, roles = _writer_fixture(tmp_path)
    plan = governance_projection.plan_governance_baseline_refresh(
        release,
        process,
        project_id="demo",
        immutable_commit_roles=roles,
    )

    receipt = governance_projection.apply_governance_baseline_refresh(
        plan,
        expected_plan_digest=plan.plan_digest,
        expected_release_oid=plan.release_oid,
        expected_process_oid=plan.process_oid,
        expected_preimage=plan.target_preimage,
    )

    assert receipt["decision"] == "PASS"
    assert receipt["disposition"] == "APPLIED"
    assert receipt["mutation_count"] == 1
    assert (
        governance_projection.validate_governance_projection(release, process)["decision"] == "PASS"
    )

    noop = governance_projection.plan_governance_baseline_refresh(
        release,
        process,
        project_id="demo",
        immutable_commit_roles=roles,
    )
    assert noop.decision == "NOOP"
    before = (process / governance_projection.GOVERNANCE_PROJECTION_REL).read_bytes()
    noop_receipt = governance_projection.apply_governance_baseline_refresh(
        noop,
        expected_plan_digest=noop.plan_digest,
        expected_release_oid=noop.release_oid,
        expected_process_oid=noop.process_oid,
        expected_preimage=noop.target_preimage,
    )
    assert noop_receipt["disposition"] == "NOOP"
    assert noop_receipt["mutation_count"] == 0
    assert (process / governance_projection.GOVERNANCE_PROJECTION_REL).read_bytes() == before


def test_governance_baseline_refresh_rejects_source_drift_before_write(
    tmp_path: Path,
) -> None:
    release, process, roles = _writer_fixture(tmp_path)
    plan = governance_projection.plan_governance_baseline_refresh(
        release,
        process,
        project_id="demo",
        immutable_commit_roles=roles,
    )
    phase = process / "phases/P1/PHASE.yaml"
    phase.write_text(
        phase.read_text(encoding="utf-8").replace("status: completed", "status: planned"),
        encoding="utf-8",
    )

    with pytest.raises(
        governance_projection.GovernanceProjectionApplyError,
        match="drifted after planning",
    ):
        governance_projection.apply_governance_baseline_refresh(
            plan,
            expected_plan_digest=plan.plan_digest,
            expected_release_oid=plan.release_oid,
            expected_process_oid=plan.process_oid,
            expected_preimage=plan.target_preimage,
        )

    assert not (process / governance_projection.GOVERNANCE_PROJECTION_REL).exists()


def test_governance_baseline_refresh_blocks_missing_active_phase_result_ref(
    tmp_path: Path,
) -> None:
    release, process, roles = _writer_fixture(tmp_path)
    phase = process / "phases/P2/PHASE.yaml"
    phase.write_text(
        phase.read_text(encoding="utf-8").replace("  - governance/GOVERNANCE-BASELINE.json\n", ""),
        encoding="utf-8",
    )

    plan = governance_projection.plan_governance_baseline_refresh(
        release,
        process,
        project_id="demo",
        immutable_commit_roles=roles,
    )

    assert plan.decision == "BLOCKED"
    assert plan.planned_mutation_count == 0
    assert any("must declare" in error for error in plan.errors)


def test_governance_baseline_refresh_cli_emits_plan_and_requires_expected_inputs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release, process, roles = _writer_fixture(tmp_path)
    role_args = [
        value
        for role in roles
        for value in (
            "--immutable-commit-role",
            f"{role.role}={role.repository}:{role.oid}",
        )
    ]

    exit_code = governance.main(
        [
            "baseline-refresh",
            "--project-root",
            str(release),
            "--project-id",
            "demo",
            *role_args,
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["kind"] == "GovernanceBaselineRefreshPlanV1"
    assert payload["decision"] == "READY"
    assert payload["mutation_count"] == 0
    assert not (process / governance_projection.GOVERNANCE_PROJECTION_REL).exists()

    apply_code = governance.main(
        [
            "baseline-refresh",
            "--project-root",
            str(release),
            "--project-id",
            "demo",
            *role_args,
            "--apply",
            "--expected-plan-digest",
            payload["plan_digest"],
            "--expected-release-oid",
            payload["expected_oids"]["release_head"],
            "--expected-process-oid",
            payload["expected_oids"]["process_head"],
            "--expected-preimage",
            payload["expected_preimage"],
        ]
    )
    applied = json.loads(capsys.readouterr().out)
    assert apply_code == 0
    assert applied["receipt"]["disposition"] == "APPLIED"
    assert applied["receipt"]["mutation_count"] == 1


def test_governance_baseline_refresh_cli_preserves_route_error_code(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release, _process, roles = _writer_fixture(tmp_path)
    role_args = [
        value
        for role in roles
        for value in (
            "--immutable-commit-role",
            f"{role.role}={role.repository}:{role.oid}",
        )
    ]

    exit_code = governance.main(
        [
            "baseline-refresh",
            "--project-root",
            str(release),
            "--project-id",
            "other",
            *role_args,
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert payload["decision"] == "BLOCKED"
    assert payload["error_code"] == "route_project_mismatch"
    assert payload["mutation_count"] == 0
