from __future__ import annotations

import inspect
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from meta_flow.evolution import (
    AcceptanceCriterion,
    CriterionResult,
    EvolutionStartAuthorization,
    build_evolution_package,
    build_evolution_start_plan,
    evaluate_evolution_result,
    evolution_from_payload,
    load_evolution_package,
    materialize_evolution_work,
    record_recommendation_decision,
    validate_evolution_provenance,
    write_evolution_package_create_only,
)
from meta_flow.project.model import Project, load_project, write_project_create_only
from meta_flow.project.onboarding import (
    ProjectInitRequest,
    apply_project_init,
    plan_project_init,
)
from meta_flow.project.onboarding_contract import (
    AUTHORIZATION_KIND,
    AUTHORIZATION_SOURCE,
    OnboardingAuthorization,
)
from meta_flow.project.scale import dump_yaml, load_yaml_object
from meta_flow.retrospective import (
    RETROSPECTIVE_DIMENSIONS,
    ImprovementCandidate,
    Retrospective,
    RetrospectiveDimension,
    StageUsage,
    confirm_retrospective_facts,
    load_retrospective,
    retrospective_from_payload,
    validate_retrospective,
    write_retrospective_create_only,
)
from meta_flow.work.budget import G1_BUDGET, BudgetLimit
from meta_flow.work.model import load_work
from meta_flow.work.scope import WorkScope
from meta_flow.work.store import WorkInitApplyError


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def init_bound_project(root: Path) -> tuple[Path, Path]:
    release = root / "demo"
    release.mkdir()
    git(release, "init", "-b", "main")
    (release / "README.md").write_text("# Demo\n", encoding="utf-8")
    git(release, "add", "README.md")
    git(
        release,
        "-c",
        "user.name=Meta Flow Test",
        "-c",
        "user.email=meta-flow@example.invalid",
        "commit",
        "-m",
        "initial",
    )
    plan = plan_project_init(ProjectInitRequest(release, "demo", "Demo"))
    payload = plan.as_dict()
    apply_project_init(
        plan,
        OnboardingAuthorization(
            1,
            "evolution-fixture",
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
    process = root / "demo-process"
    git(process, "add", ".")
    git(
        process,
        "-c",
        "user.name=Meta Flow Test",
        "-c",
        "user.email=meta-flow@example.invalid",
        "commit",
        "-m",
        "initial process",
    )
    return release, process


def dimensions() -> tuple[RetrospectiveDimension, ...]:
    return tuple(
        RetrospectiveDimension(
            dimension_id=dimension_id,
            measurement_quality="measured",
            facts=(f"{dimension_id} 的事实",),
            inferences=(f"{dimension_id} 的推断",),
            human_judgments=(f"{dimension_id} 待用户判断",),
            evidence_refs=("evidence/summary.json",),
            conclusion=f"{dimension_id} 结论",
        )
        for dimension_id in RETROSPECTIVE_DIMENSIONS
    )


def make_retro(*, applicability: str = "meta-flow-common") -> Retrospective:
    return Retrospective(
        retro_id="RETRO-001",
        project_id="demo",
        scope_kind="phase",
        scope_ref="phases/PH-001/PHASE.yaml",
        window_start="2026-07-01T00:00:00+08:00",
        window_end="2026-07-18T00:00:00+08:00",
        frozen_at="2026-07-19T09:00:00+08:00",
        approver_summary="本阶段完成目标，但需求确认存在重复读取。",
        dimensions=dimensions(),
        stage_usage=(
            StageUsage("discovery", "measured", 12_000, 7, 1, 1, 32_000),
            StageUsage(
                "review",
                "unavailable",
                None,
                2,
                0,
                1,
                unavailable_reason="旧阶段未接入 token telemetry",
            ),
        ),
        candidates=(
            ImprovementCandidate(
                candidate_id="CAND-001",
                objective="减少需求阶段重复读取",
                problem="同一摘要被多个步骤重复读取",
                applicability=applicability,
                evidence_refs=("evidence/summary.json",),
                expected_benefit="在不降低追溯覆盖率的前提下降低 token",
                risks=("摘要不足可能增加返工",),
            ),
        ),
        residual_risks=("旧阶段 token 数据不可用",),
        evidence_quality_summary="主要证据已测量，旧 review token 为 unavailable。",
    )


def make_package(retro: Retrospective, *, risk_profile: str = "G1"):
    budget = G1_BUDGET if risk_profile == "G1" else BudgetLimit(24, 18, 10, 120_000)
    return build_evolution_package(
        retro=retro,
        candidate_id="CAND-001",
        recommendation_decision="accepted",
        recommendation_decision_ref="decisions/EVO-001.yaml",
        evolution_id="EVO-001",
        work_id="EVOW-001",
        independent_evidence_sources=("project-a/W-001", "project-b/W-002"),
        baseline_oid="a" * 40,
        risk_profile=risk_profile,
        scope=WorkScope(
            version=1,
            allowed_reads=(
                "works/EVOW-001/REQUEST.md",
                "retrospectives/RETRO-001.yaml",
                "meta_flow/work/**",
            ),
            allowed_writes=("meta_flow/work/**", "tests/**"),
            required_checks=("reproduce", "target-tests", "non-regression"),
        ),
        budget=budget,
        reproduction_steps=("在 fixture 中重现重复扩读",),
        acceptance_criteria=(
            AcceptanceCriterion(
                criterion_id="AC-001",
                metric="discovery_token_reduction",
                operator=">=",
                threshold=30.0,
                unit="percent",
            ),
            AcceptanceCriterion(
                criterion_id="AC-002",
                metric="traceability_coverage",
                operator="==",
                threshold=100.0,
                unit="percent",
                non_regression=True,
            ),
        ),
        canary_scope=("fixture", "meta-flow-dogfood"),
        rollback_conditions=("追溯覆盖率低于 100%", "返工率上升"),
        reviewer_ref="reviews/EVO-001.yaml",
        expires_at="2099-01-01T00:00:00+00:00",
    )


def accept_candidate(process_root: Path) -> None:
    record_recommendation_decision(
        process_root,
        retro_id="RETRO-001",
        candidate_id="CAND-001",
        decision="accepted",
        rationale="证据、收益、风险和试点边界足以形成有界进化包。",
        decision_ref="decisions/EVO-001.yaml",
    )


def test_retrospective_round_trip_renders_all_six_dimensions_and_boundaries(
    tmp_path: Path,
) -> None:
    retro = make_retro()

    data_path, report_path = write_retrospective_create_only(tmp_path, retro)
    loaded = load_retrospective(tmp_path, "RETRO-001")
    report = report_path.read_text(encoding="utf-8")

    assert data_path.name == "RETRO-001.yaml"
    assert loaded == retro
    assert all(dimension_id in report for dimension_id in RETROSPECTIVE_DIMENSIONS)
    assert "token=unavailable (`unavailable`)" in report
    assert "不授权实现、commit、push" in report
    assert loaded.implementation_authorized is False
    assert loaded.publication_authorized is False


def test_unavailable_token_cannot_be_encoded_as_zero() -> None:
    retro = replace(
        make_retro(),
        stage_usage=(
            StageUsage(
                "review",
                "unavailable",
                0,
                1,
                0,
                1,
                unavailable_reason="未接入",
            ),
        ),
    )

    with pytest.raises(ValueError, match="tokens=null"):
        validate_retrospective(retro)


def test_retrospective_requires_exact_six_dimensions_and_never_carries_authorization() -> None:
    with pytest.raises(ValueError, match="six dimensions"):
        validate_retrospective(replace(make_retro(), dimensions=dimensions()[:-1]))
    with pytest.raises(ValueError, match="cannot authorize"):
        validate_retrospective(replace(make_retro(), implementation_authorized=True))
    with pytest.raises(ValueError, match="cannot authorize"):
        validate_retrospective(replace(make_retro(), implementation_authorized=0))


def test_retrospective_rejects_unknown_nested_fields_and_non_boolean_boundaries() -> None:
    unknown = make_retro().as_dict()
    unknown["dimensions"][0]["unexpected"] = "must-fail"
    with pytest.raises(ValueError, match="dimension schema"):
        retrospective_from_payload(unknown)

    non_boolean = make_retro().as_dict()
    non_boolean["authorization_boundaries"]["publication_authorized"] = "false"
    with pytest.raises(ValueError, match="cannot authorize"):
        retrospective_from_payload(non_boolean)


def test_fact_confirmation_is_separate_and_does_not_authorize_evolution(tmp_path: Path) -> None:
    write_retrospective_create_only(tmp_path, make_retro())

    confirmed = confirm_retrospective_facts(
        tmp_path,
        "RETRO-001",
        confirmation_ref="decisions/RETRO-001-facts.yaml",
    )

    assert confirmed.status == "facts_confirmed"
    assert confirmed.facts_confirmation_ref == "decisions/RETRO-001-facts.yaml"
    assert confirmed.implementation_authorized is False
    with pytest.raises(ValueError, match="only be confirmed from draft"):
        confirm_retrospective_facts(
            tmp_path,
            "RETRO-001",
            confirmation_ref="decisions/again.yaml",
        )


def test_only_accepted_supported_candidate_can_create_package(tmp_path: Path) -> None:
    write_retrospective_create_only(tmp_path, make_retro())
    retro = confirm_retrospective_facts(
        tmp_path,
        "RETRO-001",
        confirmation_ref="decisions/RETRO-001-facts.yaml",
    )

    with pytest.raises(ValueError, match="only an accepted"):
        build_evolution_package(
            retro=retro,
            candidate_id="CAND-001",
            recommendation_decision="deferred",
            recommendation_decision_ref="decisions/EVO-001.yaml",
            evolution_id="EVO-001",
            work_id="EVOW-001",
            independent_evidence_sources=("a", "b"),
            baseline_oid="a" * 40,
            risk_profile="G1",
            scope=WorkScope(1, ("works/EVOW-001/REQUEST.md",), (), ()),
            budget=G1_BUDGET,
            reproduction_steps=("重现",),
            acceptance_criteria=(AcceptanceCriterion("AC-1", "metric", ">=", 1, "count"),),
            canary_scope=("fixture",),
            rollback_conditions=("失败",),
            reviewer_ref="reviews/EVO.yaml",
            expires_at="2099-01-01T00:00:00+00:00",
        )


def test_common_package_requires_two_sources_and_separate_decision_records(tmp_path: Path) -> None:
    write_retrospective_create_only(tmp_path, make_retro())
    retro = confirm_retrospective_facts(
        tmp_path,
        "RETRO-001",
        confirmation_ref="decisions/RETRO-001-facts.yaml",
    )
    accept_candidate(tmp_path)
    package = make_package(retro)
    write_evolution_package_create_only(tmp_path, package)

    loaded = load_evolution_package(tmp_path, "EVO-001")

    assert loaded == package
    assert loaded.status == "approved_not_started"
    assert loaded.implementation_authorized is False
    assert loaded.publication_authorized is False
    assert loaded.facts_confirmation_ref != loaded.recommendation_decision_ref

    with pytest.raises(ValueError, match="two independent"):
        replace(package, independent_evidence_sources=("one",))
        # 构造后显式校验发生在写入路径。
        write_evolution_package_create_only(
            tmp_path / "other",
            replace(package, independent_evidence_sources=("one",)),
        )


def test_evolution_rejects_unknown_nested_fields_and_non_boolean_boundaries(
    tmp_path: Path,
) -> None:
    write_retrospective_create_only(tmp_path, make_retro())
    retro = confirm_retrospective_facts(
        tmp_path,
        "RETRO-001",
        confirmation_ref="decisions/RETRO-001-facts.yaml",
    )
    package = make_package(retro)

    unknown = package.as_dict()
    unknown["acceptance_criteria"][0]["unexpected"] = "must-fail"
    with pytest.raises(ValueError, match="criterion schema"):
        evolution_from_payload(unknown)

    non_boolean = package.as_dict()
    non_boolean["authorization_boundaries"]["implementation_authorized"] = 0
    with pytest.raises(ValueError, match="cannot authorize"):
        evolution_from_payload(non_boolean)


def test_evolution_provenance_rejects_tampered_fact_confirmation(tmp_path: Path) -> None:
    write_retrospective_create_only(tmp_path, make_retro())
    retro = confirm_retrospective_facts(
        tmp_path,
        "RETRO-001",
        confirmation_ref="decisions/RETRO-001-facts.yaml",
    )
    accept_candidate(tmp_path)
    package = make_package(retro)
    facts_path = tmp_path / "decisions/RETRO-001-facts.yaml"
    facts = load_yaml_object(facts_path)
    facts["publication_authorized"] = True
    facts_path.write_text(dump_yaml(facts) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="confirmation evidence is invalid"):
        validate_evolution_provenance(tmp_path, package)


def test_separate_typed_authorization_materializes_normal_work_without_publication(
    tmp_path: Path,
) -> None:
    release, process = init_bound_project(tmp_path)
    write_retrospective_create_only(process, make_retro())
    retro = confirm_retrospective_facts(
        process,
        "RETRO-001",
        confirmation_ref="decisions/RETRO-001-facts.yaml",
    )
    accept_candidate(process)
    baseline = git(release, "rev-parse", "HEAD")
    package = replace(make_package(retro), baseline_oid=baseline)
    write_evolution_package_create_only(process, package)
    plan = build_evolution_start_plan(package, observed_baseline_oid=baseline)
    authorization = EvolutionStartAuthorization(
        authorization_id="AUTH-EVO-001",
        evolution_id="EVO-001",
        purpose="implementation_start",
        plan_digest=plan.plan_digest,
        baseline_oid=baseline,
        expires_at="2099-01-01T00:00:00+00:00",
    )

    receipt = materialize_evolution_work(release, plan, authorization)

    assert receipt.decision == "PASS"
    assert receipt.publication_count == 0
    assert receipt.recursive_trigger_count == 0
    assert load_work(process, "EVOW-001").kind == "work"
    assert load_work(process, "EVOW-001").execution_unit is not None
    assert load_project(process).active_work_refs == ("works/EVOW-001/WORK.yaml",)


def test_evolution_request_is_not_written_before_fresh_package_check(
    tmp_path: Path,
) -> None:
    release, process = init_bound_project(tmp_path)
    write_retrospective_create_only(process, make_retro())
    retro = confirm_retrospective_facts(
        process,
        "RETRO-001",
        confirmation_ref="decisions/RETRO-001-facts.yaml",
    )
    accept_candidate(process)
    baseline = git(release, "rev-parse", "HEAD")
    package = replace(make_package(retro), baseline_oid=baseline)
    package_path = write_evolution_package_create_only(process, package)
    plan = build_evolution_start_plan(package, observed_baseline_oid=baseline)
    authorization = EvolutionStartAuthorization(
        authorization_id="AUTH-EVO-001",
        evolution_id=package.evolution_id,
        purpose="implementation_start",
        plan_digest=plan.plan_digest,
        baseline_oid=baseline,
        expires_at="2099-01-01T00:00:00+00:00",
    )
    package_path.write_text(
        package_path.read_text(encoding="utf-8").replace(
            package.objective,
            package.objective + "（drift）",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="package changed"):
        materialize_evolution_work(release, plan, authorization)

    assert not (process / plan.work.request_ref).exists()
    assert not (process / plan.work.work_ref).exists()
    assert load_project(process).active_work_refs == ()


def test_evolution_writer_failure_rolls_back_request_work_and_project(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    release, process = init_bound_project(tmp_path)
    write_retrospective_create_only(process, make_retro())
    retro = confirm_retrospective_facts(
        process,
        "RETRO-001",
        confirmation_ref="decisions/RETRO-001-facts.yaml",
    )
    accept_candidate(process)
    baseline = git(release, "rev-parse", "HEAD")
    package = replace(make_package(retro), baseline_oid=baseline)
    write_evolution_package_create_only(process, package)
    plan = build_evolution_start_plan(package, observed_baseline_oid=baseline)
    authorization = EvolutionStartAuthorization(
        authorization_id="AUTH-EVO-001",
        evolution_id=package.evolution_id,
        purpose="implementation_start",
        plan_digest=plan.plan_digest,
        baseline_oid=baseline,
        expires_at="2099-01-01T00:00:00+00:00",
    )

    from meta_flow.work import init_transaction

    original_replace = init_transaction._replace_target
    calls = 0

    def fail_project(path: Path, value: bytes | None) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("injected project writer failure")
        original_replace(path, value)

    monkeypatch.setattr(init_transaction, "_replace_target", fail_project)
    with pytest.raises(WorkInitApplyError) as raised:
        materialize_evolution_work(release, plan, authorization)

    receipt = raised.value.receipt
    assert receipt.decision == "RECOVERED"
    assert receipt.domain_mutation_count == 0
    assert receipt.transaction_state == "RECOVERED"
    assert not receipt.recovery_required
    assert receipt.recovery_route == "stop-and-replan"
    assert not (process / plan.work.request_ref).exists()
    assert not (process / plan.work.work_ref).exists()
    assert load_project(process).active_work_refs == ()


def test_evolution_materializer_has_no_direct_request_writer_or_compensating_unlink() -> None:
    source = inspect.getsource(materialize_evolution_work)
    assert ".write_text(" not in source
    assert ".write_bytes(" not in source
    assert ".mkdir(" not in source
    assert ".unlink(" not in source
    assert "plan_work_init_from_release_root" in source
    assert "apply_work_init" in source


def test_start_blocks_baseline_drift_and_authorization_cannot_include_publication(tmp_path: Path) -> None:
    write_project_create_only(
        tmp_path,
        Project(schema_version=1, project_id="demo", name="Demo", status="active"),
    )
    write_retrospective_create_only(tmp_path, make_retro())
    retro = confirm_retrospective_facts(
        tmp_path,
        "RETRO-001",
        confirmation_ref="decisions/RETRO-001-facts.yaml",
    )
    accept_candidate(tmp_path)
    package = make_package(retro)
    write_evolution_package_create_only(tmp_path, package)
    drifted = build_evolution_start_plan(package, observed_baseline_oid="b" * 40)
    assert drifted.blocked
    assert drifted.reasons == ("baseline_oid_mismatch",)

    ready = build_evolution_start_plan(package, observed_baseline_oid="a" * 40)
    authorization = EvolutionStartAuthorization(
        authorization_id="AUTH-EVO-001",
        evolution_id="EVO-001",
        purpose="implementation_start",
        plan_digest=ready.plan_digest,
        baseline_oid="a" * 40,
        expires_at="2099-01-01T00:00:00+00:00",
        publication_authorized=True,
    )
    with pytest.raises(ValueError, match="does not match"):
        materialize_evolution_work(tmp_path, ready, authorization)


def test_result_stops_on_regression_and_never_recursively_triggers(tmp_path: Path) -> None:
    write_retrospective_create_only(tmp_path, make_retro())
    retro = confirm_retrospective_facts(
        tmp_path,
        "RETRO-001",
        confirmation_ref="decisions/RETRO-001-facts.yaml",
    )
    accept_candidate(tmp_path)
    package = make_package(retro)
    criterion_results = (
        CriterionResult("AC-001", 35.0, True, "evidence/ac-001.json"),
        CriterionResult("AC-002", 100.0, True, "evidence/ac-002.json"),
    )

    stopped = evaluate_evolution_result(
        package,
        reproduction_passed=True,
        criterion_results=criterion_results,
        regression_passed=False,
        recovery_passed=True,
        canary_passed=True,
    )
    promoted = evaluate_evolution_result(
        package,
        reproduction_passed=True,
        criterion_results=criterion_results,
        regression_passed=True,
        recovery_passed=True,
        canary_passed=True,
    )
    assert stopped.decision == "STOP_OR_ROLLBACK"
    assert promoted.decision == "PROMOTE_CANDIDATE"
    assert stopped.publication_authorized is False
    assert stopped.recursive_triggered is False

    with pytest.raises(ValueError, match="passed flag"):
        evaluate_evolution_result(
            package,
            reproduction_passed=True,
            criterion_results=(
                CriterionResult("AC-001", 5.0, True, "evidence/ac-001.json"),
                CriterionResult("AC-002", 100.0, True, "evidence/ac-002.json"),
            ),
            regression_passed=True,
            recovery_passed=True,
            canary_passed=True,
        )


def test_g2_result_requires_independent_review(tmp_path: Path) -> None:
    write_retrospective_create_only(tmp_path, make_retro())
    retro = confirm_retrospective_facts(
        tmp_path,
        "RETRO-001",
        confirmation_ref="decisions/RETRO-001-facts.yaml",
    )
    accept_candidate(tmp_path)
    package = make_package(retro, risk_profile="G2")
    results = (
        CriterionResult("AC-001", 35.0, True, "evidence/ac-001.json"),
        CriterionResult("AC-002", 100.0, True, "evidence/ac-002.json"),
    )

    with pytest.raises(ValueError, match="independent review"):
        evaluate_evolution_result(
            package,
            reproduction_passed=True,
            criterion_results=results,
            regression_passed=True,
            recovery_passed=True,
            canary_passed=True,
        )
