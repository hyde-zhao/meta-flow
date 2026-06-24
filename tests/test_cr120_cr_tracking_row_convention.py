from __future__ import annotations

from pathlib import Path

from meta_flow.checks import cr_tracking


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
    path = root / "process" / "changes" / f"{cr_id}-ROW-CONVENTION.md"
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
    path = root / "process" / "changes" / "CR-116-FOLLOW-UP-TRACKING-2026-06-22.md"
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
    formal = cr_tracking.discover_formal_crs(root / "process" / "changes")
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
