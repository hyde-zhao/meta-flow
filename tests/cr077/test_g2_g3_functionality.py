from __future__ import annotations

import json
from pathlib import Path

import pytest

from meta_flow.checks.cp_result import validate_cp_result
from meta_flow.design.lightweight_design import (
    ARCHITECTURE_DELTA_FIELDS,
    CONSENT_TRIGGERS,
    ArchitectureImpactNoteV1,
    ScopeGoalNoteV1,
    evaluate_lightweight_design,
    evaluate_story_design_policy,
    extract_scope_goal_note_from_story,
)
from meta_flow.policies.route_plan import derive_route_plan
from meta_flow.release.risk_policy import RiskGrade
from meta_flow.state.gate_frontier import derive_gate_frontier
from meta_flow.work.assurance import build_review_plan, build_validation_plan
from meta_flow.work.budget import BudgetLimit
from meta_flow.work.governance_profile import (
    G3SelectionRecordV1,
    build_profile_binding,
    effective_governance_profile,
    plan_profile_transition,
)
from meta_flow.work.model import build_work, work_from_payload
from meta_flow.work.risk import HIGH_RISK_FIELDS, RiskFacts, classify_work
from meta_flow.work.scope import WorkScope
from meta_flow.workflow.story_evidence import validate_lld_structure

OID = "a" * 40
SHA = "b" * 64
BUDGET = BudgetLimit(30, 30, 12, 160_000)


def selection(**overrides: object) -> G3SelectionRecordV1:
    payload: dict[str, object] = {
        "schema_version": 1,
        "kind": "G3SelectionRecordV1",
        "cr_id": "CR-123",
        "requested_profile": "G3",
        "selection_source": "user-explicit",
        "selection_reason": "full-lld-requested",
        "authorization_ref": "process/authorizations/g3.json",
        "decided_at": "2098-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return G3SelectionRecordV1.from_mapping(payload)


def high_risk_facts(**overrides: object) -> RiskFacts:
    values: dict[str, object] = {"change_kind": "code", "touched_path_count": 4}
    values.update(overrides or {"public_contract": True})
    return RiskFacts(**values)


def make_work(profile: str, *, selection_record: G3SelectionRecordV1 | None = None):
    decision = classify_work(
        high_risk_facts(),
        requested_profile=profile,
        g2_budget=BUDGET,
        g3_selection=selection_record,
        selection_cr_id="CR-123",
        selection_source_oid=OID,
        selection_authorization_digest=SHA if selection_record else "",
        selection_channel="host-injection",
    )
    return build_work(
        work_id="CR-123",
        project_id="demo",
        objective="验证治理等级分流",
        request_ref="works/CR-123/REQUEST.md",
        scope=WorkScope(
            version=1,
            allowed_reads=("works/CR-123/REQUEST.md",),
            allowed_writes=("meta_flow/work/risk.py",),
            required_checks=("targeted",),
        ),
        classification=decision,
        release_base_oid=OID,
        process_base_oid="c" * 40,
    )


def scope_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 1,
        "kind": "ScopeGoalNoteV1",
        "story_id": "STORY-CR123-S01",
        "design_evidence_type": "scope-goal-note",
        "risk_profile_schema_version": 2,
        "governance_profile": "G2",
        "scope": {"in": ["校验输入合同"], "out": ["不执行发布"]},
        "goal": "为新 G2 提供可验证的范围和目标合同",
        "acceptance_boundary": {
            "requirement_refs": ["REQ-077-S03"],
            "scenario_refs": ["SCN-077-05"],
            "must": ["缺字段必须阻断"],
            "must_not": ["不得执行外部写入"],
        },
        "file_impact": {
            "create": [],
            "modify": ["meta_flow/design/lightweight_design.py"],
            "delete": [],
            "forbidden": ["meta_flow/release/risk_policy.py"],
            "primary_owner": "STORY-CR123-S01",
        },
        "dependencies": {"contract": [], "runtime": [], "file_conflict": []},
        "escalation_triggers": [],
        "limits": {"max_lines": 120, "max_tokens": 3000},
    }
    payload.update(overrides)
    return payload


def scope_note(**overrides: object) -> ScopeGoalNoteV1:
    return ScopeGoalNoteV1.from_mapping(scope_payload(**overrides), effective_profile="G2")


def impact_payload(
    *,
    active_delta: str = "",
    triggers: list[str] | None = None,
) -> dict[str, object]:
    deltas = {field: "none" for field in ARCHITECTURE_DELTA_FIELDS}
    notes: dict[str, str] = {}
    if active_delta:
        deltas[active_delta] = "has"
        notes[active_delta] = "该变化需要标准架构人工评审"
    active_triggers = triggers or []
    return {
        "schema_version": 1,
        "kind": "ArchitectureImpactNoteV1",
        "cr_id": "CR-123",
        "risk_profile_schema_version": 2,
        "governance_profile": "G2",
        "reused_architecture_refs": ["process/docs/design/BLUEPRINT.md"],
        "affected_modules": ["meta_flow.design"],
        "deltas": deltas,
        "delta_notes": notes,
        "failure_fallback_boundary": "任一未知或敏感变化都恢复标准 CP3 人工评审",
        "consent_triggers": active_triggers,
        "path_simulations": {
            "happy": "全部 delta 为 none 时允许继续轻量路径",
            "failure": "任一 delta 为 has 时恢复标准人工评审",
        },
        "cp3_disposition": (
            "standard-escalation" if active_delta or active_triggers else "auto-clean-eligible"
        ),
    }


def impact(**kwargs: object) -> ArchitectureImpactNoteV1:
    return ArchitectureImpactNoteV1.from_mapping(impact_payload(**kwargs))


def test_legacy_g2_is_read_as_g3_without_rewriting_bytes() -> None:
    assert effective_governance_profile("G2", 1) == "G3"
    with pytest.raises(ValueError, match="does not support G3"):
        effective_governance_profile("G3", 1)
    legacy = make_work("G2").as_dict()
    for key in (
        "risk_profile_schema_version",
        "governance_selection_source",
        "governance_selection_record_digest",
        "governance_selection_authorization_digest",
        "governance_selection_source_oid",
        "governance_route_revision",
    ):
        legacy.pop(key)
    loaded = work_from_payload(legacy)
    assert loaded.effective_risk_profile == "G3"
    assert "legacy_g2_effective_profile" not in loaded.as_dict()
    assert len(loaded.governance_profile_digest) == 64


@pytest.mark.parametrize(
    "facts",
    [
        RiskFacts(change_kind="documentation", touched_path_count=1),
        RiskFacts(change_kind="code", touched_path_count=2),
    ],
)
def test_g0_g1_classification_payload_remains_legacy_shape(facts: RiskFacts) -> None:
    payload = classify_work(facts).as_dict()
    assert "risk_profile_schema_version" not in payload
    assert "selection_record_digest" not in payload


@pytest.mark.parametrize("field", sorted(HIGH_RISK_FIELDS))
def test_each_high_risk_fact_defaults_to_v2_g2(field: str) -> None:
    decision = classify_work(high_risk_facts(**{field: True}), g2_budget=BUDGET)
    assert (decision.risk_profile, decision.risk_profile_schema_version, decision.blocked) == (
        "G2",
        2,
        False,
    )


def test_g3_requires_exact_cr_oid_route_and_authorization_binding() -> None:
    record = selection()
    accepted = classify_work(
        high_risk_facts(),
        requested_profile="G3",
        g2_budget=BUDGET,
        g3_selection=record,
        selection_cr_id="CR-123",
        selection_source_oid=OID,
        selection_authorization_digest=SHA,
        selection_channel="host-injection",
    )
    assert not accepted.blocked
    assert accepted.risk_profile == "G3"
    for kwargs, reason in (
        ({"selection_cr_id": "CR-999", "selection_authorization_digest": SHA}, "CR_ID"),
        ({"selection_cr_id": "CR-123", "selection_authorization_digest": ""}, "DIGEST_REQUIRED"),
        ({"selection_cr_id": "CR-123", "selection_authorization_digest": "invalid"}, "DIGEST_REQUIRED"),
    ):
        decision = classify_work(
            high_risk_facts(),
            requested_profile="G3",
            g2_budget=BUDGET,
            g3_selection=record,
            selection_source_oid=OID,
            selection_channel="host-injection",
            **kwargs,
        )
        assert decision.blocked
        assert any(reason in item for item in decision.reason_codes)


def test_g3_selection_matches_frozen_schema_and_rejects_config_provenance() -> None:
    record = selection()
    assert set(record.as_dict()) == {
        "schema_version",
        "kind",
        "requested_profile",
        "selection_source",
        "selection_reason",
        "authorization_ref",
        "decided_at",
        "cr_id",
    }
    with pytest.raises(ValueError, match="FIELDS_INVALID"):
        selection(selection_id="forbidden-extra-field")
    blocked = classify_work(
        high_risk_facts(),
        requested_profile="G3",
        g2_budget=BUDGET,
        g3_selection=record,
        selection_cr_id="CR-123",
        selection_source_oid=OID,
        selection_authorization_digest=SHA,
    )
    assert blocked.blocked
    assert "G3_SELECTION_PROVENANCE_INVALID" in blocked.reason_codes


def test_requested_lld_fact_cannot_upgrade_without_typed_selection() -> None:
    decision = classify_work(
        high_risk_facts(requested_lld=True),
        g2_budget=BUDGET,
    )
    assert decision.risk_profile == "G2"
    assert decision.blocked
    assert "G3_SELECTION_REQUIRED" in decision.reason_codes


@pytest.mark.parametrize(
    ("checkpoint", "resume", "invalidated"),
    [
        ("CP2", "CP2", ()),
        ("CP4", "CP3", ("CP3", "CP4", "CP5")),
        ("CP5", "CP3", ("CP3", "CP4", "CP5")),
    ],
)
def test_late_g2_to_g3_upgrade_has_explicit_invalidation_boundary(
    checkpoint: str,
    resume: str,
    invalidated: tuple[str, ...],
) -> None:
    transition = plan_profile_transition(
        build_profile_binding("G2"),
        "G3",
        selection_record=selection(),
        selection_cr_id="CR-123",
        selection_source_oid=OID,
        selection_authorization_digest=SHA,
        selection_channel="host-injection",
        current_checkpoint=checkpoint,
    )
    assert transition.decision == "READY"
    assert transition.route_revision == 2
    assert transition.resume_checkpoint == resume
    assert transition.invalidated_checkpoints == invalidated
    downgrade = plan_profile_transition(
        build_profile_binding(
            "G3",
            selection_record=selection(),
            selection_authorization_digest=SHA,
            selection_source_oid=OID,
        ),
        "G2",
        current_checkpoint=checkpoint,
    )
    assert downgrade.decision == "BLOCKED"
    assert downgrade.reason_codes == ("DOWNGRADE_REJECTED",)


def test_g2_and_g3_share_budget_gates_and_qa_but_not_design_depth() -> None:
    g2 = make_work("G2")
    g3 = make_work("G3", selection_record=selection())
    assert g2.budget == g3.budget
    assert g2.required_gates == g3.required_gates == ("GATE-SCOPE", "GATE-DESIGN")
    g2_review = build_review_plan(
        g2,
        evidence_refs={
            "scope_goal_note_refs": "process/design/notes.json",
            "architecture_impact_note_refs": "process/design/impact.json",
            "human_scope_gate_ref": "process/checkpoints/CP5.md",
            "independent_reviewer_ref": "process/reviews/qa.json",
        },
    )
    assert g2_review.decision == "READY"
    assert g2_review.review_mode == "scope-goal-and-impact-review"
    assert build_review_plan(g3).review_mode == "full-architecture-and-independent-review"
    for work in (g2, g3):
        plan = build_validation_plan(
            work,
            check_risk_mapping={"targeted": "profile routing"},
            independent_qa_ref="process/reviews/qa.json",
        )
        assert plan.decision == "READY"
        assert plan.independent_qa_required


@pytest.mark.parametrize("missing", ["scope", "goal", "acceptance_boundary", "file_impact"])
def test_scope_goal_note_requires_each_human_confirmation_axis(missing: str) -> None:
    payload = scope_payload()
    payload.pop(missing)
    with pytest.raises(ValueError, match="SCOPE_GOAL_NOTE"):
        ScopeGoalNoteV1.from_mapping(payload, effective_profile="G2")


def test_scope_goal_note_enforces_closed_fields_lines_and_tokens(tmp_path: Path) -> None:
    payload = scope_payload()
    note = ScopeGoalNoteV1.from_mapping(payload, effective_profile="G2")
    path = tmp_path / "STORY-CR123-S01.scope-goal.json"
    path.write_text(json.dumps(note.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    errors, warnings = validate_lld_structure(
        path, evidence_type="scope-goal-note", project_root=tmp_path
    )
    assert errors == []
    assert warnings == []
    with pytest.raises(ValueError, match="LINE_LIMIT_EXCEEDED"):
        ScopeGoalNoteV1.from_mapping(payload, raw_text="x\n" * 121, effective_profile="G2")
    with pytest.raises(ValueError, match="TOKEN_LIMIT_EXCEEDED"):
        ScopeGoalNoteV1.from_mapping(payload, raw_text="x" * 10_501, effective_profile="G2")
    with pytest.raises(ValueError, match="FIELDS_INVALID"):
        ScopeGoalNoteV1.from_mapping(payload | {"duplicate_truth": True})


def test_scope_goal_note_can_be_consumed_from_story_section(tmp_path: Path) -> None:
    payload = scope_payload()
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    story = tmp_path / "STORY-CR123-S01.md"
    story.write_text(
        "---\nstory_id: STORY-CR123-S01\n---\n\n"
        "## 范围与目标\n\n```json\n"
        + rendered
        + "\n```\n\n## 后续章节\n",
        encoding="utf-8",
    )
    extracted, raw = extract_scope_goal_note_from_story(story.read_text(encoding="utf-8"))
    assert extracted == payload
    assert raw.strip().startswith("{")
    errors, warnings = validate_lld_structure(
        story,
        evidence_type="scope-goal-note",
        project_root=tmp_path,
    )
    assert errors == []
    assert warnings == []


@pytest.mark.parametrize("trigger", sorted(CONSENT_TRIGGERS))
def test_each_consent_trigger_blocks_without_automatic_upgrade(trigger: str) -> None:
    decision = evaluate_lightweight_design(
        scope_note(),
        impact(),
        mechanically_observed_impacts=[trigger],
    )
    assert decision["decision"] == "REQUIRES_FULL_LLD"
    policy = evaluate_story_design_policy(
        risk_profile="G2",
        risk_profile_schema_version=2,
        lld_policy="scope-goal-note",
        lightweight_decision=decision,
    )
    assert policy["decision"] == "BLOCKED"
    assert "G3_CONSENT_REQUIRED" in policy["reason_codes"]
    assert policy["mutation_count"] == 0


@pytest.mark.parametrize("field", ARCHITECTURE_DELTA_FIELDS)
def test_each_architecture_delta_restores_standard_cp3(field: str) -> None:
    note = impact(active_delta=field)
    assert note.active_deltas == (field,)
    common = {
        "cr_type": "process",
        "cr_trait": {
            "has_new_design": True,
            "has_new_implementation": True,
            "requires_story_decomposition": True,
        },
        "gate_profile": "standard-code",
        "governance_risk_profile": "G2",
        "governance_profile_schema_version": 2,
        "architecture_impact_note": note.as_dict(),
    }
    plan = derive_route_plan(**common)
    assert plan["decision"] == "PASS"
    stage = {item["checkpoint"]: item for item in plan["stages"]}
    assert stage["CP3"] == {"checkpoint": "CP3", "mode": "standard", "human_gate": "required"}


@pytest.mark.parametrize("field", ARCHITECTURE_DELTA_FIELDS)
def test_architecture_delta_does_not_silently_force_g3_story_design(field: str) -> None:
    decision = evaluate_lightweight_design(scope_note(), impact(active_delta=field))
    assert decision["decision"] == "PASS"
    assert decision["architecture_review_required"] is True
    assert evaluate_story_design_policy(
        risk_profile="G2",
        risk_profile_schema_version=2,
        lld_policy="scope-goal-note",
        lightweight_decision=decision,
    )["decision"] == "PASS"


def test_g2_lite_route_requires_valid_architecture_note() -> None:
    common = {
        "cr_type": "process",
        "cr_trait": {
            "has_new_design": True,
            "has_new_implementation": True,
            "requires_story_decomposition": True,
        },
        "gate_profile": "standard-code",
        "governance_risk_profile": "G2",
        "governance_profile_schema_version": 2,
    }
    blocked = derive_route_plan(**common)
    assert blocked["decision"] == "BLOCKED"
    plan = derive_route_plan(**(common | {"architecture_impact_note": impact().as_dict()}))
    assert plan["decision"] == "PASS"
    stage = {item["checkpoint"]: item for item in plan["stages"]}
    assert stage["CP2"] == {"checkpoint": "CP2", "mode": "lite", "human_gate": "required"}
    assert stage["CP3"] == {"checkpoint": "CP3", "mode": "lite", "human_gate": "none"}
    assert stage["CP5"] == {"checkpoint": "CP5", "mode": "lite", "human_gate": "required"}


@pytest.mark.parametrize("level", ["full-lld", "batch-lld", "technical-note", "waived"])
def test_g3_and_legacy_g2_reuse_every_existing_design_level(level: str) -> None:
    for profile, version in (("G3", 2), ("G2", 1)):
        decision = evaluate_story_design_policy(
            risk_profile=profile,
            risk_profile_schema_version=version,
            lld_policy=level,
        )
        assert decision["decision"] == "PASS"
    assert evaluate_story_design_policy(
        risk_profile="G3",
        risk_profile_schema_version=2,
        lld_policy="scope-goal-note",
    )["decision"] == "BLOCKED"


@pytest.mark.parametrize("level", ["full-lld", "batch-lld"])
def test_v2_g2_accepts_voluntary_stronger_design(level: str) -> None:
    decision = evaluate_story_design_policy(
        risk_profile="G2",
        risk_profile_schema_version=2,
        lld_policy=level,
    )
    assert decision["decision"] == "PASS"
    assert decision["voluntary_full_lld"] is True


def test_cp4_cp5_result_checker_enforces_profile_evidence_matrix(tmp_path: Path) -> None:
    base = {
        "schema_version": 1,
        "checkpoint": "CP5",
        "decision": "PASS",
        "items": [{"id": "I-1", "name": "design", "status": "PASS", "severity": "HIGH", "evidence_refs": []}],
        "blockers": [],
        "waivers": [],
        "governance_profile": {"schema_version": 2, "risk_profile": "G3"},
        "story_design_reviews": [{"story_id": "STORY-1", "lld_policy": "scope-goal-note"}],
    }
    path = tmp_path / "cp5.json"
    path.write_text(json.dumps(base), encoding="utf-8")
    errors, _ = validate_cp_result(path, project_root=None)
    assert any("G3_LEGACY_DESIGN_EVIDENCE_REQUIRED" in item for item in errors)
    base["story_design_reviews"] = [{"story_id": "STORY-1", "lld_policy": "technical-note"}]
    path.write_text(json.dumps(base), encoding="utf-8")
    errors, _ = validate_cp_result(path, project_root=None)
    assert not any("design evidence blocked" in item for item in errors)


def test_cp_result_recomputes_g2_lightweight_decision(tmp_path: Path) -> None:
    base = {
        "schema_version": 1,
        "checkpoint": "CP5",
        "decision": "PASS",
        "items": [
            {
                "id": "I-1",
                "name": "design",
                "status": "PASS",
                "severity": "HIGH",
                "evidence_refs": [],
            }
        ],
        "blockers": [],
        "waivers": [],
        "governance_profile": {"schema_version": 2, "risk_profile": "G2"},
        "story_design_reviews": [
            {
                "story_id": "STORY-CR123-S01",
                "lld_policy": "scope-goal-note",
                "lightweight_decision": {"decision": "PASS"},
            }
        ],
    }
    path = tmp_path / "cp5-g2.json"
    path.write_text(json.dumps(base), encoding="utf-8")
    errors, _ = validate_cp_result(path, project_root=None)
    assert any("requires canonical note" in item for item in errors)

    review = base["story_design_reviews"][0]
    review["scope_goal_note"] = scope_payload()
    review["architecture_impact_note"] = impact_payload()
    review.pop("lightweight_decision")
    path.write_text(json.dumps(base), encoding="utf-8")
    errors, _ = validate_cp_result(path, project_root=None)
    assert not any("lightweight" in item or "design evidence blocked" in item for item in errors)


def test_frontier_never_skips_missing_cp6_or_cp7_to_cp8() -> None:
    stages = [
        {"checkpoint": "CP5", "human_gate": "required"},
        {"checkpoint": "CP6", "human_gate": "none"},
        {"checkpoint": "CP7", "human_gate": "none"},
        {"checkpoint": "CP8", "human_gate": "required"},
    ]
    heads = {"CP5": {"decision": "PASS", "result_ref": "process/checks/cp5.json"}}
    frontier = derive_gate_frontier(
        stages,
        heads,
        {"CP5": "process/checks/cp5.json"},
        {},
    )
    assert frontier.status == "WAITING_CHECKPOINT"
    assert frontier.checkpoint == "CP6"
    assert frontier.pending_gate == ""


def test_profile_binding_separates_g2_g3_and_route_revisions() -> None:
    g2 = build_profile_binding("G2")
    g2_revision_2 = build_profile_binding("G2", route_revision=2)
    g3 = build_profile_binding(
        "G3",
        selection_record=selection(),
        selection_authorization_digest=SHA,
        selection_source_oid=OID,
    )
    g3_other_authorization = build_profile_binding(
        "G3",
        selection_record=selection(),
        selection_authorization_digest="c" * 64,
        selection_source_oid=OID,
    )
    assert len({g2.digest, g2_revision_2.digest, g3.digest, g3_other_authorization.digest}) == 4


def test_publication_operation_grade_remains_three_level_namespace() -> None:
    assert [item.name for item in RiskGrade] == ["G0", "G1", "G2"]
