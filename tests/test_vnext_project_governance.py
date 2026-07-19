from __future__ import annotations

from pathlib import Path

import pytest

from meta_flow.project.governance import (
    PHASE_SCHEMA_VERSION,
    ROADMAP_SCHEMA_VERSION,
    Phase,
    Roadmap,
    load_governance_snapshot,
    validate_phase_payload,
    validate_roadmap_payload,
    write_phase_create_only,
    write_roadmap_create_only,
)
from meta_flow.project.model import Project, write_project_create_only
from meta_flow.work.model import build_work, write_work_create_only
from meta_flow.work.risk import RiskFacts, classify_work
from meta_flow.work.scope import WorkScope


def make_project(
    *,
    roadmap_ref: str = "",
    phase_ref: str = "",
    work_ref: str = "works/W-001/WORK.yaml",
) -> Project:
    return Project(
        schema_version=1,
        project_id="demo",
        name="Demo",
        objective="交付项目目标",
        status="active",
        roadmap_ref=roadmap_ref,
        active_phase_ref=phase_ref,
        active_work_refs=(work_ref,),
    )


def make_work(*, phase_ref: str = ""):
    return build_work(
        work_id="W-001",
        project_id="demo",
        objective="完成一个可验证结果",
        request_ref="works/W-001/REQUEST.md",
        scope=WorkScope(
            1,
            ("PROJECT.yaml",),
            ("works/W-001/**",),
            ("pytest-work",),
        ),
        classification=classify_work(
            RiskFacts(change_kind="documentation", touched_path_count=1)
        ),
        release_base_oid="a" * 40,
        process_base_oid="",
        phase_ref=phase_ref,
    )


def write_direct_project_work(root: Path) -> None:
    write_project_create_only(root, make_project())
    write_work_create_only(root, make_work())


def write_phase_project_work(root: Path, *, with_roadmap: bool) -> None:
    phase_ref = "phases/PH-001/PHASE.yaml"
    roadmap_ref = "ROADMAP.yaml" if with_roadmap else ""
    write_project_create_only(
        root,
        make_project(roadmap_ref=roadmap_ref, phase_ref=phase_ref),
    )
    phase = Phase(
        schema_version=PHASE_SCHEMA_VERSION,
        project_id="demo",
        phase_id="PH-001",
        objective="完成首个阶段",
        status="active",
        work_refs=("works/W-001/WORK.yaml",),
    )
    write_phase_create_only(root, phase)
    if with_roadmap:
        write_roadmap_create_only(
            root,
            Roadmap(
                schema_version=ROADMAP_SCHEMA_VERSION,
                project_id="demo",
                outcome="达成长期结果",
                status="active",
                phase_refs=(phase_ref,),
            ),
        )
    write_work_create_only(root, make_work(phase_ref=phase_ref))


@pytest.mark.parametrize("mode", ["project-work", "project-phase-work", "project-roadmap-phase-work"])
def test_all_three_elastic_governance_modes_are_valid(tmp_path: Path, mode: str) -> None:
    if mode == "project-work":
        write_direct_project_work(tmp_path)
    else:
        write_phase_project_work(
            tmp_path,
            with_roadmap=mode == "project-roadmap-phase-work",
        )

    snapshot, findings = load_governance_snapshot(tmp_path)

    assert findings == []
    assert snapshot is not None
    assert snapshot.project.project_id == "demo"
    assert len(snapshot.active_works) == 1
    assert snapshot.objects_read <= 4
    if mode == "project-work":
        assert snapshot.roadmap is None
        assert snapshot.active_phase is None
    elif mode == "project-phase-work":
        assert snapshot.roadmap is None
        assert snapshot.active_phase is not None
    else:
        assert snapshot.roadmap is not None
        assert snapshot.active_phase is not None


def test_project_does_not_require_empty_roadmap_or_phase(tmp_path: Path) -> None:
    write_direct_project_work(tmp_path)

    snapshot, findings = load_governance_snapshot(tmp_path)

    assert findings == []
    assert snapshot is not None
    assert not (tmp_path / "ROADMAP.yaml").exists()
    assert not (tmp_path / "phases").exists()


def test_orphan_phase_is_rejected(tmp_path: Path) -> None:
    phase_ref = "phases/PH-001/PHASE.yaml"
    write_phase_project_work(tmp_path, with_roadmap=True)
    roadmap_path = tmp_path / "ROADMAP.yaml"
    roadmap_path.write_text(
        "schema_version: 1\nproject_id: demo\noutcome: x\nstatus: active\nphase_refs: []\n",
        encoding="utf-8",
    )

    snapshot, findings = load_governance_snapshot(tmp_path)

    assert snapshot is None
    assert phase_ref in {finding.ref for finding in findings if finding.code == "orphan_phase"}


def test_work_and_phase_parent_refs_must_be_bidirectional(tmp_path: Path) -> None:
    write_phase_project_work(tmp_path, with_roadmap=False)
    phase_path = tmp_path / "phases" / "PH-001" / "PHASE.yaml"
    phase_path.write_text(
        "schema_version: 1\nproject_id: demo\nphase_id: PH-001\nobjective: x\nstatus: active\nwork_refs: []\nresult_refs: []\n",
        encoding="utf-8",
    )

    snapshot, findings = load_governance_snapshot(tmp_path)

    assert snapshot is None
    assert any(finding.code == "work_parent" for finding in findings)


def test_cross_project_governance_objects_are_rejected(tmp_path: Path) -> None:
    write_phase_project_work(tmp_path, with_roadmap=True)
    roadmap_path = tmp_path / "ROADMAP.yaml"
    text = roadmap_path.read_text(encoding="utf-8").replace("project_id: demo", "project_id: other")
    roadmap_path.write_text(text, encoding="utf-8")

    snapshot, findings = load_governance_snapshot(tmp_path)

    assert snapshot is None
    assert any(finding.code == "project_id_mismatch" for finding in findings)


def test_governance_schema_rejects_unsafe_and_unknown_fields() -> None:
    roadmap_findings = validate_roadmap_payload(
        {
            "schema_version": 1,
            "project_id": "demo",
            "outcome": "x",
            "status": "active",
            "phase_refs": ["../PHASE.yaml"],
            "history": [],
        }
    )
    phase_findings = validate_phase_payload(
        {
            "schema_version": 1,
            "project_id": "demo",
            "phase_id": "PH-001",
            "objective": "x",
            "status": "active",
            "work_refs": ["../WORK.yaml"],
            "result_refs": [],
        }
    )

    assert {"phase_refs", "unknown_key"} <= {finding.code for finding in roadmap_findings}
    assert "work_refs" in {finding.code for finding in phase_findings}
