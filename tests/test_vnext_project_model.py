from __future__ import annotations

from pathlib import Path

import pytest

from meta_flow.project.model import (
    PROJECT_FILE,
    PROJECT_MAX_BYTES,
    build_minimal_project,
    load_project,
    validate_project_payload,
    write_project_create_only,
)


def test_minimal_project_has_no_empty_governance_layers(tmp_path: Path) -> None:
    project = build_minimal_project(project_id="demo", name="Demo")

    assert project.as_dict() == {
        "schema_version": 1,
        "project_id": "demo",
        "name": "Demo",
        "status": "active",
    }
    assert validate_project_payload(project.as_dict()) == []


def test_project_allows_optional_roadmap_phase_and_work_refs() -> None:
    payload = {
        "schema_version": 1,
        "project_id": "demo",
        "name": "Demo",
        "objective": "交付可恢复的项目治理",
        "status": "active",
        "roadmap_ref": "ROADMAP.yaml",
        "active_phase_ref": "phases/PH-001/PHASE.yaml",
        "active_work_refs": ["works/W-001/WORK.yaml"],
    }

    assert validate_project_payload(payload) == []


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("roadmap_ref", "../ROADMAP.yaml", "ref_path"),
        ("active_phase_ref", "works/W-001/WORK.yaml", "ref_path"),
        ("active_work_refs", ["phases/PH-001/PHASE.yaml"], "ref_path"),
        ("active_work_refs", ["works/W-001/WORK.yaml", "works/W-001/WORK.yaml"], "duplicate_ref"),
    ],
)
def test_project_rejects_unsafe_or_duplicate_refs(field: str, value: object, code: str) -> None:
    payload = build_minimal_project(project_id="demo", name="Demo").as_dict()
    payload[field] = value

    findings = validate_project_payload(payload)

    assert code in {finding.code for finding in findings}


def test_project_rejects_unknown_sensitive_and_over_budget_fields() -> None:
    payload = build_minimal_project(project_id="demo", name="Demo").as_dict()
    payload["secret_token"] = "redacted"

    findings = validate_project_payload(payload, byte_size=PROJECT_MAX_BYTES + 1)

    codes = {finding.code for finding in findings}
    assert {"unknown_key", "forbidden_key", "project_over_budget"} <= codes


def test_project_write_is_create_only_and_round_trips(tmp_path: Path) -> None:
    project = build_minimal_project(project_id="demo", name="Demo")

    path = write_project_create_only(tmp_path, project)

    assert path == tmp_path / PROJECT_FILE
    assert load_project(tmp_path) == project
    with pytest.raises(FileExistsError):
        write_project_create_only(tmp_path, project)
