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


def _findings(
    root: Path,
    *,
    next_action_refs: list[tuple[str, int]] | None = None,
) -> tuple[list[str], list[str]]:
    formal = cr_tracking.discover_formal_crs(
        _resolve_runtime_ref(root, "process/changes")
    )
    rows = cr_tracking.discover_follow_up_rows(root, [])
    return cr_tracking.collect_errors_and_warnings(
        project_root=root,
        formal_crs=formal,
        rows=rows,
        index_items=[],
        next_action_refs=next_action_refs or [],
        state_refs=[],
        allow_multiple_active=False,
    )


def test_active_source_follow_up_row_with_related_active_cr_passes(tmp_path: Path) -> None:
    _formal_cr(tmp_path, "CR-120")
    _tracking(tmp_path, "related_active_cr=CR-120; blocked_by=cp5_pending")

    assert _errors(tmp_path) == []


def test_formal_only_index_does_not_warn_for_legal_candidate_or_next_action(
    tmp_path: Path,
) -> None:
    path = _resolve_runtime_ref(
        tmp_path, "process/changes/CR-116-FOLLOW-UP-TRACKING-2026-06-22.md"
    )
    _write(
        path,
        """# Tracking

| 候选编号 | 标题 | 状态 | 类型 | 正式 CR 路径 | 下一步 |
|---|---|---|---|---|---|
| FU-CR116-001 | later | candidate | spike | - | 保留候选 |
""",
    )

    errors, warnings = _findings(
        tmp_path,
        next_action_refs=[("FU-CR116-001", 1)],
    )

    assert errors == []
    assert not any("missing from CR-INDEX" in warning for warning in warnings)
    assert not any("next_action_queue" in warning for warning in warnings)


def test_dangling_formal_link_remains_an_error(tmp_path: Path) -> None:
    path = _resolve_runtime_ref(
        tmp_path, "process/changes/CR-116-FOLLOW-UP-TRACKING-2026-06-22.md"
    )
    _write(
        path,
        """# Tracking

| 候选编号 | 标题 | 状态 | 类型 | 正式 CR 路径 | 下一步 |
|---|---|---|---|---|---|
| FU-CR116-002 | active | active | requirement-change | process/changes/CR-999-MISSING.md | inspect |
""",
    )

    errors, _warnings = _findings(tmp_path)

    assert any("formal CR path does not exist" in error for error in errors)


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


def test_native_formal_cr_accepts_direct_terminal_tuple(tmp_path: Path) -> None:
    path = _resolve_runtime_ref(tmp_path, "process/changes/CR-120-NATIVE.md")
    _write(
        path,
        """---
schema_version: 1
cr_id: CR-120
kind: cr
title: direct terminal fixture
lifecycle_status: closed
readiness_status: READY_WITH_RISK
gate_status: closed
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

    assert not any("illegal native status tuple" in error for error in errors)


def test_native_formal_cr_rejects_jointly_stale_gate_checkpoint_result_and_adr(
    tmp_path: Path,
) -> None:
    formal_path = _resolve_runtime_ref(tmp_path, "process/changes/CR-120-NATIVE.md")
    _write(
        formal_path,
        """---
schema_version: 1
cr_id: CR-120
kind: cr
title: stale projection fixture
lifecycle_status: active
readiness_status: NOT_READY
gate_status: cp3_pending
---

## Checkpoint Index

| CP | 状态 |
|---|---|
| CP3 | pending |
| CP6 | pending |
""",
    )
    gate_ledger = _resolve_runtime_ref(tmp_path, "process/state/GATE-LEDGER.ndjson")
    _write(
        gate_ledger,
        '{"event_id":"CR120-CP3-APPROVED","event_type":"human_gate_approval",'
        '"cr_id":"CR-120","work_id":"W-120","gate":"CP3-CR-120-DESIGN",'
        '"status":"approved"}\n',
    )
    cp6_result = _resolve_runtime_ref(
        tmp_path,
        "process/checks/CP6-CR-120-IMPLEMENTATION.result.json",
    )
    _write(
        cp6_result,
        '{"checkpoint":"CP6","cr_id":"CR-120","work_id":"W-120","decision":"PASS"}\n',
    )
    adr_path = _resolve_runtime_ref(
        tmp_path,
        "process/works/W-120/ARCHITECTURE-DECISION.md",
    )
    _write(
        adr_path,
        """---
status: accepted
---

| 决策 ID | 状态 |
|---|---|
| CP3-DQ-120-01 | OPEN |
""",
    )

    errors = _errors(tmp_path)

    assert any("Checkpoint Index CP3 is stale" in error for error in errors)
    assert any("Checkpoint Index CP6=PENDING is stale" in error for error in errors)
    assert any("frontmatter gate_status=cp3_pending is stale" in error for error in errors)
    assert any("accepted ADR has stale OPEN decision queue" in error for error in errors)


def test_native_formal_cr_accepts_cp8_machine_pass_before_human_approval(
    tmp_path: Path,
) -> None:
    formal_path = _resolve_runtime_ref(tmp_path, "process/changes/CR-120-NATIVE.md")
    _write(
        formal_path,
        """---
schema_version: 1
cr_id: CR-120
kind: cr
status: active
lifecycle_status: active
readiness_status: NOT_READY
gate_status: cp8_pending
---

## Checkpoint Index

| CP | 状态 |
|---|---|
| CP8 | PASS |
""",
    )
    result_path = _resolve_runtime_ref(
        tmp_path,
        "process/checks/CP8-CR-120-DELIVERY-READINESS.result.json",
    )
    _write(
        result_path,
        '{"checkpoint":"CP8","cr_id":"CR-120","work_id":"W-120",'
        '"decision":"PASS","release_decision":"READY_WITH_RISK"}\n',
    )

    errors = _errors(tmp_path)

    assert not any("Checkpoint Index CP8" in error for error in errors)
    assert not any("frontmatter gate_status=cp8_pending is stale" in error for error in errors)


def test_native_formal_cr_accepts_cp8_approval_before_independent_native_close(
    tmp_path: Path,
) -> None:
    formal_path = _resolve_runtime_ref(tmp_path, "process/changes/CR-120-NATIVE.md")
    _write(
        formal_path,
        """---
schema_version: 1
cr_id: CR-120
kind: cr
status: active
lifecycle_status: active
readiness_status: NOT_READY
gate_status: cp8_pending
---

## Checkpoint Index

| CP | 状态 |
|---|---|
| CP8 | approved |
""",
    )
    gate_ledger = _resolve_runtime_ref(
        tmp_path, "process/state/GATE-LEDGER.ndjson"
    )
    _write(
        gate_ledger,
        '{"event_id":"CR120-CP8-APPROVED","event_type":"human_gate_approval",'
        '"cr_id":"CR-120","work_id":"W-120","gate":"CP8-DELIVERY-READINESS",'
        '"decision":"approve","status":"approved"}\n',
    )
    result_path = _resolve_runtime_ref(
        tmp_path,
        "process/checks/CP8-CR-120-DELIVERY-READINESS.result.json",
    )
    _write(
        result_path,
        '{"checkpoint":"CP8","cr_id":"CR-120","work_id":"W-120",'
        '"decision":"PASS","release_decision":"READY_WITH_RISK"}\n',
    )

    errors = _errors(tmp_path)

    assert not any("Checkpoint Index CP8" in error for error in errors)
    assert not any("frontmatter gate_status=cp8_pending is stale" in error for error in errors)
