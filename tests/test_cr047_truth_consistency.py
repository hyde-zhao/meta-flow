from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

from meta_flow.checks import cr_tracking
from meta_flow.state import current
from meta_flow.workflow import cr_lifecycle


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _vnext_route(root: Path) -> None:
    # formal CR partition 消费方要求健康 vNext 路由；sibling 过程仓 + relative-symlink
    # 保持本文件继续直写 root/process/... 物理路径。
    process = root.parent / f"{root.name}-process"
    process.mkdir()
    for repo in (root, process):
        subprocess.run(
            ["git", "-C", str(repo), "init", "-b", "main"],
            check=True,
            capture_output=True,
        )
    _write(
        root / ".meta-flow" / "workspace.yaml",
        json.dumps(
            {
                "schema_version": 1,
                "layout_version": "independent-process-repo-v1",
                "workflow_model": "vnext",
                "project_id": "demo",
                "repo_role": "release",
                "route_mode": "relative-symlink",
                "process_link": "process",
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
                "project_id": "demo",
                "repo_role": "process",
                "route_mode": "relative-symlink",
                "release_repo": {
                    "anchor": "workspace_parent",
                    "relative_path": root.name,
                },
            }
        )
        + "\n",
    )
    _write(
        process / "PROJECT.yaml",
        "schema_version: 1\nproject_id: demo\nname: demo\nstatus: active\n",
    )
    os.symlink(f"../{process.name}", root / "process")


def _formal_cr(root: Path, cr_id: str, *, lifecycle: str = "active", status: str = "active") -> None:
    _write(
        root / "process" / "changes" / f"{cr_id}.md",
        f'''---
schema_version: 1
kind: cr
cr_id: "{cr_id}"
title: "truth fixture"
cr_kind: "requirement-change"
lifecycle_status: "{lifecycle}"
readiness_status: "NOT_READY"
gate_status: "implementation_in_progress"
gate_profile: "standard-code"
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
        json.dumps(cr_lifecycle.build_index(tmp_path)) + "\n",
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
        json.dumps(cr_lifecycle.build_index(tmp_path)) + "\n",
    )
    current.write_current_state(tmp_path, current.default_current_state(tmp_path, project_id="demo"))
    current.refresh_current_entry(tmp_path)

    assert current.validate_current_projection(tmp_path) == []


def test_cr_index_semantic_digest_drift_is_not_accepted_as_projection_truth(tmp_path: Path) -> None:
    payload = cr_lifecycle.build_index(tmp_path)
    payload["semantic_digest"] = "0" * 64
    path = tmp_path / "process/changes/CR-INDEX.json"
    _write(path, json.dumps(payload) + "\n")

    assert "CR-INDEX.json semantic_digest mismatch" in cr_tracking.validate_cr_index_projection(path)


def test_self_consistent_stale_index_is_blocked_against_formal_truth(tmp_path: Path) -> None:
    _vnext_route(tmp_path)
    _formal_cr(tmp_path, "CR-053")
    expected = cr_lifecycle.build_index(tmp_path)
    stale = json.loads(json.dumps(expected))
    stale["items"][0]["title"] = "stale but internally self-consistent"
    semantic = json.dumps(
        {"schema_version": stale["schema_version"], "items": stale["items"]},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    stale["semantic_digest"] = hashlib.sha256(semantic.encode("utf-8")).hexdigest()
    path = tmp_path / "process/changes/CR-INDEX.json"
    _write(path, json.dumps(stale) + "\n")

    projection_errors = cr_tracking.validate_cr_index_projection(
        path,
        expected_semantic_digest=expected["semantic_digest"],
    )
    ordinary = cr_lifecycle.plan_index(tmp_path)
    explicit = cr_lifecycle.plan_index(tmp_path, rebuild_corrupt=True)
    status_sync = cr_lifecycle.plan_status_sync(
        tmp_path,
        "CR-053",
        status="blocked",
    )

    assert "CR-INDEX.json stale projection differs from formal truth rebuild digest" in projection_errors
    assert ordinary["decision"] == "BLOCKED"
    assert ordinary["mutation_count"] == 0
    assert explicit["decision"] == "READY"
    assert explicit["action"] == "rebuild"
    assert status_sync.decision == "BLOCKED"
    assert "formal truth rebuild digest" in status_sync.reason
