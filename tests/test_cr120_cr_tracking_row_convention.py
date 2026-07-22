from __future__ import annotations

import subprocess
from pathlib import Path

from meta_flow.checks import cr_tracking
from meta_flow.project.onboarding import ProjectInitRequest, apply_project_init, plan_project_init
from meta_flow.project.onboarding_contract import (
    AUTHORIZATION_KIND,
    AUTHORIZATION_SOURCE,
    OnboardingAuthorization,
)
from meta_flow.project.process_route import _resolve_runtime_ref


def _init_binding_project(root: Path) -> tuple[Path, Path]:
    release = root / "fixture-release"
    release.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=release, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Meta Flow Test",
            "-c",
            "user.email=meta-flow@example.invalid",
            "commit",
            "--allow-empty",
            "-m",
            "initial",
        ],
        cwd=release,
        check=True,
        capture_output=True,
    )
    plan = plan_project_init(ProjectInitRequest(release, "fixture", "Fixture Project"))
    payload = plan.as_dict()
    apply_project_init(
        plan,
        OnboardingAuthorization(
            1,
            "cr120-row-fixture",
            AUTHORIZATION_SOURCE,
            AUTHORIZATION_KIND,
            payload["operation"],
            payload["decision_ref"],
            payload["project_id"],
            payload["plan_digest"],
            payload["base_oids"],
            "2099-01-01T00:00:00+00:00",
        ),
    )
    return release, root / "fixture-process"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _formal_cr(
    root: Path,
    cr_id: str,
    *,
    status: str = "active",
    lifecycle_status: str = "active",
    source_follow_up_id: str = "FU-CR114-004",
) -> Path:
    path = _resolve_runtime_ref(
        root, f"process/changes/{cr_id}-ROW-CONVENTION.md"
    )
    _write(
        path,
        f"""---
cr_id: "{cr_id}"
title: "row convention"
cr_kind: "requirement-change"
lifecycle_status: "{lifecycle_status}"
readiness_status: "n/a"
gate_status: "cp5_pending"
gate_profile: "standard"
status: "{status}"
source: "cp8-follow-up"
source_follow_up_id: "{source_follow_up_id}"
---

# {cr_id}
""",
    )
    return path


def _tracking(root: Path, relation: str, *, formal_path: str = "process/changes/CR-120-ROW-CONVENTION.md") -> Path:
    path = _resolve_runtime_ref(
        root, "process/changes/CR-116-FOLLOW-UP-TRACKING-2026-06-22.md"
    )
    _write(
        path,
        f"""# Tracking

| 候选编号 | 标题 | 状态 | 类型 | 优先级 | 影响面 / 冲突键 | 正式 CR 路径 | 相关 active CR / blocked_by / superseded_by | 当前门控 | 阻塞原因 | 下一步 | 来源 |
|---|---|---|---|---:|---|---|---|---|---|---|---|
| CR-120 | CR Tracking Formal/FU Row Convention Hardening | active | requirement-change | 2 | cr_tracking_checker | `process/changes/CR-120-ROW-CONVENTION.md` | source_candidate=FU-CR114-004; blocked_by=cp5_pending | cp5_pending | CP5 待审查 | 审查 CR120 CP5 | DQ-CP8-CR116-02 |
| FU-CR114-004 | CR Tracking Formal/FU Row Convention Hardening | active | requirement-change | 2 | cr_tracking_checker | `{formal_path}` | {relation} | cp5_pending | CP5 待审查 | 审查 CR120 CP5 | DQ-CP8-CR116-02 |
""",
    )
    return path


def _errors(root: Path) -> list[str]:
    formal = cr_tracking.discover_formal_crs(
        _resolve_runtime_ref(root, "process/changes")
    )
    rows = cr_tracking.discover_follow_up_rows(root, [])
    errors, _warnings = cr_tracking.collect_errors_and_warnings(
        project_root=root,
        formal_crs=formal,
        rows=rows,
        index_items=[],
        next_action_refs=[],
        state_refs=[],
        allow_multiple_active=False,
    )
    return errors


def test_active_source_follow_up_row_with_related_active_cr_passes(tmp_path: Path) -> None:
    _formal_cr(tmp_path, "CR-120")
    _tracking(tmp_path, "related_active_cr=CR-120; blocked_by=cp5_pending")

    assert _errors(tmp_path) == []


def test_binding_only_follow_up_rows_resolve_in_process_repository(tmp_path: Path) -> None:
    release, process = _init_binding_project(tmp_path)
    _formal_cr(release, "CR-120")
    _tracking(release, "related_active_cr=CR-120; blocked_by=cp5_pending")

    assert _errors(release) == []
    assert (process / "changes" / "CR-120-ROW-CONVENTION.md").is_file()
    assert not (release / "process").exists()


def test_active_source_follow_up_row_requires_related_active_cr(tmp_path: Path) -> None:
    _formal_cr(tmp_path, "CR-120")
    _tracking(tmp_path, "blocked_by=cp5_pending")

    assert any("must include related_active_cr=CR-120" in error for error in _errors(tmp_path))


def test_source_follow_up_row_must_point_to_source_formal_cr(tmp_path: Path) -> None:
    _formal_cr(tmp_path, "CR-120")
    _formal_cr(tmp_path, "CR-121", source_follow_up_id="FU-CR999-001")
    _tracking(
        tmp_path,
        "related_active_cr=CR-121; blocked_by=cp5_pending",
        formal_path="process/changes/CR-121-ROW-CONVENTION.md",
    )

    assert any("source_follow_up_id=FU-CR114-004 has no follow-up row pointing to this CR" in error for error in _errors(tmp_path))


def test_source_follow_up_row_must_close_when_formal_cr_is_finished(tmp_path: Path) -> None:
    _formal_cr(tmp_path, "CR-120", status="closed-current-delivery", lifecycle_status="closed")
    _tracking(tmp_path, "related_active_cr=CR-120; blocked_by=cp5_pending")

    assert any("must be closed while source formal CR CR-120 is finished" in error for error in _errors(tmp_path))


def test_native_formal_cr_requires_one_legal_status_tuple(tmp_path: Path) -> None:
    path = _resolve_runtime_ref(tmp_path, "process/changes/CR-120-NATIVE.md")
    _write(
        path,
        """---
schema_version: 1
cr_id: CR-120
kind: cr
title: native tuple fixture
lifecycle_status: active
readiness_status: READY
gate_status: implementation_in_progress
---
""",
    )
    formal = cr_tracking.discover_formal_crs(path.parent)

    errors, _warnings = cr_tracking.collect_errors_and_warnings(
        project_root=tmp_path,
        formal_crs=formal,
        rows=[],
        index_items=[],
        next_action_refs=[],
        state_refs=[],
        allow_multiple_active=False,
    )

    assert any("illegal native status tuple" in error for error in errors)
