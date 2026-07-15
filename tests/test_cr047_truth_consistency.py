from __future__ import annotations

import json
from pathlib import Path

from meta_flow.checks import cr_tracking
from meta_flow.state import current


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _formal_cr(root: Path, cr_id: str, *, lifecycle: str = "active", status: str = "active") -> None:
    _write(
        root / "process" / "changes" / f"{cr_id}.md",
        f'''---
cr_id: "{cr_id}"
title: "truth fixture"
cr_kind: "requirement-change"
lifecycle_status: "{lifecycle}"
readiness_status: "ready"
gate_status: "implementation_in_progress"
gate_profile: "standard"
status: "{status}"
---
''',
    )


def _index_item(cr_id: str, *, lifecycle: str = "active") -> cr_tracking.IndexItem:
    return cr_tracking.IndexItem(
        item_id=cr_id,
        title="truth fixture",
        status=lifecycle,
        lifecycle_status=lifecycle,
        readiness_status="ready",
        gate_status="implementation_in_progress",
        gate_profile="standard",
        kind="requirement-change",
        formal_path=f"process/changes/{cr_id}.md",
        source_tracking="",
        blocked_by=[],
        candidate_id="",
        next_action="",
        line_no=1,
    )


def test_state_v2_active_change_is_canonical_over_state_markdown(tmp_path: Path) -> None:
    _write(
        tmp_path / "process" / "state" / "STATE.current.json",
        json.dumps({"active_change": "CR-047"}),
    )
    _write(tmp_path / "process" / "STATE.md", "active_change: CR-037\n")

    refs = cr_tracking.find_state_v2_refs(tmp_path / "process" / "state" / "STATE.current.json")

    assert [(ref.key, ref.value) for ref in refs] == [("active_change", "CR-047")]


def test_active_change_rejects_terminal_formal_cr(tmp_path: Path) -> None:
    _formal_cr(tmp_path, "CR-037", lifecycle="closed", status="closed")
    formal = cr_tracking.discover_formal_crs(tmp_path / "process" / "changes")

    errors, _warnings = cr_tracking.collect_errors_and_warnings(
        project_root=tmp_path,
        formal_crs=formal,
        rows=[],
        index_items=[_index_item("CR-037", lifecycle="closed")],
        next_action_refs=[],
        state_refs=[cr_tracking.StateRef(key="active_change", value="CR-037", line_no=1)],
        allow_multiple_active=False,
    )

    assert any("points to finished CR CR-037" in error for error in errors)
    assert any("terminal CR-INDEX lifecycle_status=closed" in error for error in errors)


def test_active_change_must_exist_in_canonical_json_index(tmp_path: Path) -> None:
    _formal_cr(tmp_path, "CR-047")
    formal = cr_tracking.discover_formal_crs(tmp_path / "process" / "changes")

    errors, _warnings = cr_tracking.collect_errors_and_warnings(
        project_root=tmp_path,
        formal_crs=formal,
        rows=[],
        index_items=[],
        next_action_refs=[],
        state_refs=[cr_tracking.StateRef(key="active_change", value="CR-047", line_no=1)],
        allow_multiple_active=False,
    )

    assert any("missing from canonical CR-INDEX.json" in error for error in errors)


def test_current_projection_detects_state_drift(tmp_path: Path) -> None:
    _write(
        tmp_path / "process" / "changes" / "CR-INDEX.json",
        '{"schema_version": 1, "items": []}\n',
    )
    state = current.default_current_state(tmp_path, project_id="demo")
    state["active_change"] = "CR-047"
    current.write_current_state(tmp_path, state)
    current.refresh_current_entry(tmp_path)
    entry_path = tmp_path / "process" / "current" / "CURRENT.json"
    entry = json.loads(entry_path.read_text(encoding="utf-8"))
    entry["active_change"] = "CR-037"
    entry_path.write_text(json.dumps(entry), encoding="utf-8")

    findings = current.validate_current_projection(tmp_path)

    assert any(
        finding.code == "current_projection_drift" and finding.key == "active_change"
        for finding in findings
    )


def test_current_projection_passes_after_refresh(tmp_path: Path) -> None:
    _write(
        tmp_path / "process" / "changes" / "CR-INDEX.json",
        '{"schema_version": 1, "items": []}\n',
    )
    current.write_current_state(tmp_path, current.default_current_state(tmp_path, project_id="demo"))
    current.refresh_current_entry(tmp_path)

    assert current.validate_current_projection(tmp_path) == []
