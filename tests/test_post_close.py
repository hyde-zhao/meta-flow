from __future__ import annotations

import json
import subprocess
from pathlib import Path

from meta_flow.checks import post_close


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fixture(root: Path) -> Path:
    release = root / "release"
    process = root / "process"
    for repository in (release, process):
        repository.mkdir(parents=True)
        subprocess.run(
            ["git", "init", "-b", "main"],
            cwd=repository,
            check=True,
            capture_output=True,
        )
    _write(
        release / ".meta-flow/workspace.yaml",
        """schema_version: 1
layout_version: independent-process-repo-v1
workflow_model: vnext
project_id: fixture
repo_role: release
route_mode: sibling-binding
process_repo:
  anchor: workspace_parent
  relative_path: process
""",
    )
    _write(
        process / ".meta-flow-process.yaml",
        """schema_version: 1
layout_version: independent-process-repo-v1
workflow_model: vnext
project_id: fixture
repo_role: process
route_mode: sibling-binding
release_repo:
  anchor: workspace_parent
  relative_path: release
""",
    )
    _write(
        process / "PROJECT.yaml",
        "schema_version: 1\nproject_id: fixture\nname: Fixture\nstatus: active\n",
    )
    _write(
        root / "process/changes/CR-101.md",
        """---
schema_version: 1
kind: cr
cr_id: CR-101
lifecycle_status: closed
readiness_status: READY_WITH_RISK
gate_status: cp8_closed
gate_profile: standard-code
impact_capability_refs: [cap-one]
---

## Checkpoint Index

| CP | 状态 | 机器结果 ref | 人工门禁 ref |
|---|---|---|---|
| CP8 | approved | `process/checks/CP8-FINAL.result.json` | `process/checkpoints/CP8-FINAL.md` |
""",
    )
    capability_resolution = {
        "kind": "capability",
        "mode": "audit",
        "results": [
            {
                "input_ref": "cap-one",
                "status": "resolved",
                "canonical_id": "CAP-ONE",
            }
        ],
        "summary": {"resolved": 1, "unresolved": 0, "deprecated": 0, "conflict": 0},
    }
    _write(
        root / "process/changes/summaries/CR-101.summary.json",
        json.dumps({"id": "CR-101", "impact_capability_resolution": capability_resolution}) + "\n",
    )
    _write(
        root / "process/changes/CR-INDEX.json",
        json.dumps(
            {"items": [{"id": "CR-101", "impact_capability_resolution": capability_resolution}]}
        )
        + "\n",
    )
    _write(
        root / "process/docs/design/FEATURE-REGISTRY.yaml",
        json.dumps(
            {
                "schema_version": 1,
                "features": [
                    {
                        "feature_id": "feature.one",
                        "title": "Feature one",
                        "owner_context": "fixture",
                        "status": "implemented",
                        "risk_profile": "standard-code",
                        "design_doc_policy": "registry-only",
                        "module_paths": ["meta_flow"],
                    }
                ],
            }
        )
        + "\n",
    )
    _write(
        root / "process/docs/design/CAPABILITY-REGISTRY.yaml",
        json.dumps(
            {
                "schema_version": 1,
                "capabilities": [
                    {
                        "id": "CAP-ONE",
                        "name": "Capability one",
                        "domain": "fixture",
                        "status": "active",
                        "owner_context": "fixture",
                        "feature_refs": ["feature.one"],
                        "concept_refs": [],
                        "aliases": ["cap-one"],
                        "deprecated_by": "",
                        "source_refs": ["meta_flow/example.py"],
                    }
                ],
            }
        )
        + "\n",
    )
    _write(
        root / "process/checks/CP8-FINAL.result.json",
        json.dumps(
            {
                "checkpoint": "CP8",
                "cr_id": "CR-101",
                "decision": "PASS",
                "release_decision": "READY_WITH_RISK",
            }
        )
        + "\n",
    )
    _write(root / "process/checks/CP8-FAILED.result.json", '{"decision":"BLOCKED"}\n')
    _write(root / "process/checkpoints/CP8-FINAL.md", "---\nstatus: approved\n---\n")
    _write(
        root / "process/phases/P5/PHASE.yaml",
        """schema_version: 1
project_id: fixture
phase_id: P5
objective: fixture closure
status: completed
work_refs: [works/WA/WORK.yaml]
result_refs: []
""",
    )
    _write(root / "process/works/WA/WORK.yaml", "status: completed\n")
    _write(root / "process/issues/ISSUE-001.md", "---\nstatus: resolved\n---\n")
    _write(
        root / "process/changes/CR-101-FOLLOW-UP-TRACKING-2026-08-19.md",
        """---
source_cr: CR-101
---

```yaml
follow_up_items:
  - id: FU-CR101-001
    title: cost
    status: candidate
    lifecycle_status: candidate
    readiness_status: NOT_READY
    gate_status: not_started
    gate_profile: architecture-major
    kind: implementation-gate
    formal_cr_path: ""
    blocked_by: ""
```
""",
    )
    _write(root / "process/state/STATE.current.json", '{"active_change":null}\n')
    _write(
        root / "process/release/RELEASE-CONTEXT.yaml",
        json.dumps(
            {
                "status": "released_remote_verified_native_closed",
                "cr_id": "CR-101",
                "release_execution": {"status": "RELEASED_REMOTE_VERIFIED_NATIVE_CLOSED"},
                "closure_reconciliation": {
                    "schema_version": 1,
                    "status": "completed",
                    "current_cp8": {
                        "result_ref": "process/checks/CP8-FINAL.result.json",
                        "checkpoint_ref": "process/checkpoints/CP8-FINAL.md",
                        "predecessor_result_refs": ["process/checks/CP8-FAILED.result.json"],
                    },
                    "native_close": {
                        "cr_ref": "process/changes/CR-101.md",
                        "phase_ref": "process/phases/P5/PHASE.yaml",
                        "work_refs": ["process/works/WA/WORK.yaml"],
                    },
                    "resolved_issue_refs": ["process/issues/ISSUE-001.md"],
                    "follow_up_tracking_ref": "process/changes/CR-101-FOLLOW-UP-TRACKING-2026-08-19.md",
                    "required_capability_refs": ["cap-one"],
                },
            }
        )
        + "\n",
    )
    return release


def test_post_close_passes_complete_reconciliation(tmp_path: Path) -> None:
    release = _fixture(tmp_path)

    result = post_close.check_post_close(release, "CR-101")

    assert result["decision"] == "PASS"
    assert result["finding_count"] == 0
    assert result["mutation_count"] == 0


def test_post_close_accepts_closed_cr_in_truthfully_active_phase(tmp_path: Path) -> None:
    release = _fixture(tmp_path)
    project_path = tmp_path / "process/PROJECT.yaml"
    project_path.write_text(
        project_path.read_text(encoding="utf-8")
        + "active_phase_ref: phases/P5/PHASE.yaml\n",
        encoding="utf-8",
    )
    phase_path = tmp_path / "process/phases/P5/PHASE.yaml"
    phase_path.write_text(
        phase_path.read_text(encoding="utf-8").replace(
            "status: completed", "status: active"
        ),
        encoding="utf-8",
    )

    result = post_close.check_post_close(release, "CR-101")

    assert result["decision"] == "PASS"
    assert result["post_close_profile"]["allowed_phase_statuses"] == [
        "active",
        "completed",
    ]


def test_post_close_rejects_active_phase_without_project_binding(tmp_path: Path) -> None:
    release = _fixture(tmp_path)
    phase_path = tmp_path / "process/phases/P5/PHASE.yaml"
    phase_path.write_text(
        phase_path.read_text(encoding="utf-8").replace(
            "status: completed", "status: active"
        ),
        encoding="utf-8",
    )

    result = post_close.check_post_close(release, "CR-101")

    assert result["decision"] == "BLOCKED"
    assert {item["code"] for item in result["findings"]} == {
        "POST_CLOSE_ACTIVE_PHASE_BINDING_MISMATCH"
    }


def test_post_close_rejects_non_active_non_completed_phase(tmp_path: Path) -> None:
    release = _fixture(tmp_path)
    phase_path = tmp_path / "process/phases/P5/PHASE.yaml"
    phase_path.write_text(
        phase_path.read_text(encoding="utf-8").replace(
            "status: completed", "status: planned"
        ),
        encoding="utf-8",
    )

    result = post_close.check_post_close(release, "CR-101")

    assert result["decision"] == "BLOCKED"
    assert "POST_CLOSE_PHASE_STATUS_INVALID" in {
        item["code"] for item in result["findings"]
    }


def test_post_close_rejects_stale_final_cp8_binding(tmp_path: Path) -> None:
    release = _fixture(tmp_path)
    cr_path = tmp_path / "process/changes/CR-101.md"
    cr_path.write_text(
        cr_path.read_text(encoding="utf-8").replace(
            "process/checks/CP8-FINAL.result.json",
            "process/checks/CP8-FAILED.result.json",
        ),
        encoding="utf-8",
    )

    result = post_close.check_post_close(release, "CR-101")

    assert result["decision"] == "BLOCKED"
    assert {item["code"] for item in result["findings"]} == {"POST_CLOSE_CP8_CURRENT_BINDING_STALE"}


def test_post_close_reports_typed_unresolved_capability_without_creating_issue(
    tmp_path: Path,
) -> None:
    release = _fixture(tmp_path)
    cr_path = tmp_path / "process/changes/CR-101.md"
    cr_path.write_text(
        cr_path.read_text(encoding="utf-8").replace("[cap-one]", "[cap-missing]"),
        encoding="utf-8",
    )
    context_path = tmp_path / "process/release/RELEASE-CONTEXT.yaml"
    context = json.loads(context_path.read_text(encoding="utf-8"))
    context["closure_reconciliation"]["required_capability_refs"] = ["cap-missing"]
    context_path.write_text(json.dumps(context) + "\n", encoding="utf-8")
    issue_inventory_before = sorted((tmp_path / "process/issues").glob("*"))

    result = post_close.check_post_close(release, "CR-101")

    assert result["decision"] == "BLOCKED"
    assert result["capability_resolution"]["decision"] == "UNRESOLVED"
    assert result["capability_resolution"]["unresolved_aliases"] == ["cap-missing"]
    assert "POST_CLOSE_CAPABILITY_UNRESOLVED" in {
        finding["code"] for finding in result["findings"]
    }
    assert sorted((tmp_path / "process/issues").glob("*")) == issue_inventory_before


def test_post_close_rejects_ghost_active_change(tmp_path: Path) -> None:
    release = _fixture(tmp_path)
    state_path = tmp_path / "process/state/STATE.current.json"
    state_path.write_text(json.dumps({"active_change": "CR-101"}) + "\n", encoding="utf-8")

    result = post_close.check_post_close(release, "CR-101")

    assert result["decision"] == "BLOCKED"
    assert "POST_CLOSE_ACTIVE_CHANGE_STALE" in {
        finding["code"] for finding in result["findings"]
    }


def test_post_close_accepts_lowercase_canonical_readiness(tmp_path: Path) -> None:
    """CR-078 S4-2：frontmatter 为 canonical 小写时不得误报 tuple mismatch。"""

    release = _fixture(tmp_path)
    cr_path = release.parent / "process/changes/CR-101.md"
    cr_path.write_text(
        cr_path.read_text(encoding="utf-8").replace(
            "readiness_status: READY_WITH_RISK", "readiness_status: ready_with_risk"
        ),
        encoding="utf-8",
    )
    result = post_close.check_post_close(release, "CR-101")
    assert not any(
        finding["code"] == "POST_CLOSE_CR_TUPLE_MISMATCH"
        for finding in result["findings"]
    )


def test_post_close_supports_workless_release_cr_via_declared_policy(tmp_path: Path) -> None:
    """CR-078 S4-3：work_binding_policy: not_required 豁免无 Work 的 release CR。"""

    release = _fixture(tmp_path)
    release_context_path = release.parent / "process/release/RELEASE-CONTEXT.yaml"
    payload = json.loads(release_context_path.read_text(encoding="utf-8"))
    payload["closure_reconciliation"]["work_binding_policy"] = "not_required"
    payload["closure_reconciliation"]["native_close"]["work_refs"] = []
    release_context_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    result = post_close.check_post_close(release, "CR-101")
    assert not any(
        finding["code"] == "POST_CLOSE_WORK_BINDING_MISSING"
        for finding in result["findings"]
    )
