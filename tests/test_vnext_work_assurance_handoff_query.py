from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from meta_flow.project.governance import PHASE_SCHEMA_VERSION, Phase, write_phase_create_only
from meta_flow.project.model import Project, write_project_create_only
from meta_flow.project.query import query_project_status
from meta_flow.work.assurance import build_review_plan, build_validation_plan
from meta_flow.work.budget import BudgetLimit
from meta_flow.work.handoff import (
    build_handoff,
    load_handoff,
    resume_precheck,
    write_handoff,
)
from meta_flow.work.model import build_work, write_work_create_only
from meta_flow.work.risk import RiskFacts, classify_work
from meta_flow.work.scope import WorkScope


def make_work(*, profile: str = "G0", phase_ref: str = ""):
    facts = RiskFacts(
        change_kind="documentation" if profile == "G0" else "code",
        touched_path_count=1 if profile == "G0" else 3,
        public_contract=profile == "G2",
    )
    classification = classify_work(
        facts,
        g2_budget=BudgetLimit(30, 30, 12, 160_000) if profile == "G2" else None,
    )
    return build_work(
        work_id="W-001",
        project_id="demo",
        objective="交付一个有界结果",
        request_ref="works/W-001/REQUEST.md",
        phase_ref=phase_ref,
        scope=WorkScope(
            version=1,
            allowed_reads=("PROJECT.yaml", "works/W-001/REQUEST.md"),
            allowed_writes=("README.md",),
            required_checks=("target-tests", "git-status"),
        ),
        classification=classification,
        release_base_oid="a" * 40,
        process_base_oid="b" * 40,
    )


@pytest.mark.parametrize(
    ("profile", "review_mode", "max_reviews"),
    [
        ("G0", "self-check", 0),
        ("G1", "work-scoped-lightweight", 1),
    ],
)
def test_review_plan_is_proportional_for_g0_g1(
    profile: str,
    review_mode: str,
    max_reviews: int,
) -> None:
    plan = build_review_plan(make_work(profile=profile))

    assert plan.decision == "READY"
    assert plan.review_mode == review_mode
    assert plan.max_independent_reviews == max_reviews
    assert plan.required_evidence == ()
    assert plan.route_mode == "routine-four-stage"
    assert plan.dispatch_mode == "direct"
    assert plan.stages == ("clarification", "design", "implementation", "verification")


def test_g2_review_requires_scope_goal_impact_gate_and_independent_reviewer() -> None:
    work = make_work(profile="G2")

    blocked = build_review_plan(work, evidence_refs={"scope_goal_note_refs": "notes.json"})
    ready = build_review_plan(
        work,
        evidence_refs={
            "scope_goal_note_refs": "notes.json",
            "architecture_impact_note_refs": "impact.json",
            "human_scope_gate_ref": "gates/G2.yaml",
            "independent_reviewer_ref": "reviews/G2.yaml",
        },
    )

    assert blocked.decision == "BLOCKED"
    assert set(blocked.missing_evidence) == {
        "architecture_impact_note_refs",
        "human_scope_gate_ref",
        "independent_reviewer_ref",
    }
    assert ready.decision == "READY"


def test_validation_plan_requires_exact_risk_mapping_and_g2_qa() -> None:
    g0 = make_work(profile="G0")
    missing = build_validation_plan(g0, check_risk_mapping={"target-tests": "功能正确性"})
    ready = build_validation_plan(
        g0,
        check_risk_mapping={
            "target-tests": "覆盖当前结果",
            "git-status": "证明无范围外变更",
        },
    )
    g2 = make_work(profile="G2")
    g2_blocked = build_validation_plan(
        g2,
        check_risk_mapping={
            "target-tests": "覆盖当前结果",
            "git-status": "证明无范围外变更",
        },
    )

    assert missing.decision == "BLOCKED"
    assert ready.decision == "READY"
    assert ready.full_regression_allowed is False
    assert ready.route_mode == "routine-four-stage"
    assert ready.stages == ("clarification", "design", "implementation", "verification")
    assert g2_blocked.decision == "BLOCKED"
    assert "G2 requires independent QA evidence" in g2_blocked.errors


def test_handoff_is_bounded_and_resume_checks_both_oids_and_scope(tmp_path: Path) -> None:
    paused = replace(make_work(), status="paused")
    write_work_create_only(tmp_path, paused)
    handoff = build_handoff(
        paused,
        release_oid="a" * 40,
        process_oid="b" * 40,
        completed=("已完成请求确认",),
        remaining=("运行目标测试",),
        blockers=(),
        next_step="运行 target-tests",
        evidence_refs=("works/W-001/REQUEST.md",),
    )

    path = write_handoff(tmp_path, handoff)
    loaded = load_handoff(tmp_path, "W-001")
    ready = resume_precheck(
        paused,
        loaded,
        actual_release_oid="a" * 40,
        actual_process_oid="b" * 40,
    )
    drifted = resume_precheck(
        replace(paused, scope=WorkScope(2, ("README.md",), (), ())),
        loaded,
        actual_release_oid="c" * 40,
        actual_process_oid="b" * 40,
    )

    assert path.name == "HANDOFF.yaml"
    assert ready.decision == "READY"
    assert drifted.decision == "BLOCKED"
    assert set(drifted.reasons) == {"scope_digest_mismatch", "release_oid_mismatch"}


def test_handoff_cannot_capture_active_work_or_transcript(tmp_path: Path) -> None:
    active = replace(make_work(), status="active")
    with pytest.raises(ValueError, match="paused or blocked"):
        build_handoff(
            active,
            release_oid="a" * 40,
            process_oid="b" * 40,
            completed=(),
            remaining=(),
            blockers=(),
            next_step="继续",
        )

    paused = replace(active, status="paused")
    with pytest.raises(ValueError, match="safe"):
        build_handoff(
            paused,
            release_oid="a" * 40,
            process_oid="b" * 40,
            completed=(),
            remaining=(),
            blockers=(),
            next_step="继续",
            evidence_refs=("../full-transcript.txt",),
        )


def test_query_reads_only_direct_active_objects(tmp_path: Path) -> None:
    phase_ref = "phases/PH-001/PHASE.yaml"
    work = make_work(phase_ref=phase_ref)
    project = Project(
        schema_version=1,
        project_id="demo",
        name="Demo",
        status="active",
        active_phase_ref=phase_ref,
        active_work_refs=(work.work_ref,),
    )
    write_project_create_only(tmp_path, project)
    write_phase_create_only(
        tmp_path,
        Phase(
            schema_version=PHASE_SCHEMA_VERSION,
            project_id="demo",
            phase_id="PH-001",
            objective="首个阶段",
            status="active",
            work_refs=(work.work_ref,),
        ),
    )
    write_work_create_only(tmp_path, work)

    result = query_project_status(tmp_path)

    assert result.decision == "PASS"
    assert result.objects_read == 3
    assert result.refs == ("PROJECT.yaml", phase_ref, work.work_ref)
    assert result.work is not None and result.work["work_id"] == "W-001"


def test_query_blocks_inactive_work_without_reading_it(tmp_path: Path) -> None:
    project = Project(
        schema_version=1,
        project_id="demo",
        name="Demo",
        status="active",
    )
    write_project_create_only(tmp_path, project)
    write_work_create_only(tmp_path, make_work())

    result = query_project_status(tmp_path, work_id="W-001")

    assert result.decision == "BLOCKED"
    assert result.objects_read == 1
    assert result.work is None
    assert result.refs == ("PROJECT.yaml",)


def test_query_detects_active_ref_shape_tampering(tmp_path: Path) -> None:
    project = Project(
        schema_version=1,
        project_id="demo",
        name="Demo",
        status="active",
        active_work_refs=("works/W-001/unexpected.yaml",),
    )
    write_project_create_only(tmp_path, project)

    result = query_project_status(tmp_path)

    assert result.decision == "BLOCKED"
    assert result.objects_read == 1
    assert any("invalid shape" in error for error in result.errors)


def test_query_blocks_project_work_identity_mismatch(tmp_path: Path) -> None:
    work = make_work()
    write_project_create_only(
        tmp_path,
        Project(
            schema_version=1,
            project_id="demo",
            name="Demo",
            status="active",
            active_work_refs=(work.work_ref,),
        ),
    )
    write_work_create_only(tmp_path, replace(work, project_id="other"))

    result = query_project_status(tmp_path)

    # 查询器必须在返回前证明 Project/Work 属于同一项目。
    assert result.decision == "BLOCKED"
    assert result.work is None


def test_query_object_budget_blocks_referenced_phase_before_its_read(
    tmp_path: Path,
) -> None:
    phase_ref = "phases/PH-001/PHASE.yaml"
    write_project_create_only(
        tmp_path,
        Project(
            schema_version=1,
            project_id="demo",
            name="Demo",
            status="active",
            active_phase_ref=phase_ref,
        ),
    )
    write_phase_create_only(
        tmp_path,
        Phase(
            schema_version=PHASE_SCHEMA_VERSION,
            project_id="demo",
            phase_id="PH-001",
            objective="首个阶段",
            status="active",
        ),
    )

    result = query_project_status(tmp_path, max_objects=1)

    assert result.decision == "BLOCKED"
    assert result.objects_read == 1
    assert result.refs == ("PROJECT.yaml",)
    assert result.blocked_ref == phase_ref
    assert result.error_codes == ("QUERY_OBJECT_BUDGET_EXCEEDED",)
