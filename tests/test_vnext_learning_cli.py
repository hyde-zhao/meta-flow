from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from meta_flow.evolution import AcceptanceCriterion, build_evolution_package
from meta_flow.evolution_cli import (
    check_main as evolution_check_main,
)
from meta_flow.evolution_cli import (
    decision_main,
    package_main,
    result_main,
    start_main,
)
from meta_flow.project.onboarding import ProjectInitRequest, apply_project_init, plan_project_init
from meta_flow.project.onboarding_contract import (
    AUTHORIZATION_KIND,
    AUTHORIZATION_SOURCE,
    OnboardingAuthorization,
)
from meta_flow.project.scale import dump_yaml
from meta_flow.retrospective import (
    RETROSPECTIVE_DIMENSIONS,
    ImprovementCandidate,
    Retrospective,
    RetrospectiveDimension,
    StageUsage,
    load_retrospective,
)
from meta_flow.retrospective_cli import build_main, check_main, confirm_main
from meta_flow.work.budget import G1_BUDGET
from meta_flow.work.lifecycle import update_work_status
from meta_flow.work.scope import WorkScope


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def init_project(root: Path) -> tuple[Path, Path, str]:
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
            "learning-cli-fixture",
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
    return release, process, git(release, "rev-parse", "HEAD")


def retro_payload() -> dict[str, object]:
    dimensions = tuple(
        RetrospectiveDimension(
            dimension_id=dimension_id,
            measurement_quality="measured",
            facts=("存在可重放证据",),
            inferences=("流程可进一步缩短",),
            human_judgments=("是否推广需用户决定",),
            evidence_refs=("evidence/summary.json",),
            conclusion="当前结果可接受，但存在有证据的改进候选。",
        )
        for dimension_id in RETROSPECTIVE_DIMENSIONS
    )
    return Retrospective(
        retro_id="RETRO-001",
        project_id="demo",
        scope_kind="phase",
        scope_ref="phases/PH-001/PHASE.yaml",
        window_start="2026-07-01T00:00:00+08:00",
        window_end="2026-07-18T00:00:00+08:00",
        frozen_at="2026-07-19T09:00:00+08:00",
        approver_summary="本阶段成功，但存在重复读取。",
        dimensions=dimensions,
        stage_usage=(StageUsage("discovery", "measured", 12_000, 6, 1, 1, 32_000),),
        candidates=(
            ImprovementCandidate(
                candidate_id="CAND-001",
                objective="减少重复读取",
                problem="同一摘要被重复读取",
                applicability="meta-flow-common",
                evidence_refs=("evidence/summary.json",),
                expected_benefit="降低 token 且不降低追溯率",
                risks=("摘要不足导致返工",),
            ),
        ),
        residual_risks=("第二项目仍需 canary",),
        evidence_quality_summary="关键证据为 measured。",
    ).as_dict()


def test_learning_cli_end_to_end_keeps_four_authorizations_separate(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release, process, baseline_oid = init_project(tmp_path)
    retro_input = tmp_path / "retro-input.yaml"
    retro_input.write_text(dump_yaml(retro_payload()) + "\n", encoding="utf-8")
    build_args = ["--project-root", str(release), "--input", str(retro_input)]

    assert build_main(build_args) == 0
    assert json.loads(capsys.readouterr().out)["mutation_count"] == 0
    assert build_main([*build_args, "--apply"]) == 0
    built = json.loads(capsys.readouterr().out)
    assert built["dimension_count"] == 6
    assert built["implementation_authorized"] is False
    assert check_main(["--project-root", str(release), "--id", "RETRO-001"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "draft"

    confirm_args = [
        "--project-root",
        str(release),
        "--id",
        "RETRO-001",
        "--confirmation-ref",
        "decisions/RETRO-001-facts.yaml",
    ]
    assert confirm_main(confirm_args) == 0
    assert json.loads(capsys.readouterr().out)["mutation_count"] == 0
    assert confirm_main([*confirm_args, "--apply"]) == 0
    confirmed_payload = json.loads(capsys.readouterr().out)
    assert confirmed_payload["implementation_authorized"] is False

    decision_args = [
        "--project-root",
        str(release),
        "--retro-id",
        "RETRO-001",
        "--candidate-id",
        "CAND-001",
        "--decision",
        "accepted",
        "--rationale",
        "两个独立 Work 的证据足以支持受控试点。",
        "--decision-ref",
        "decisions/EVO-001.yaml",
    ]
    assert decision_main(decision_args) == 0
    assert json.loads(capsys.readouterr().out)["mutation_count"] == 0
    assert decision_main([*decision_args, "--apply"]) == 0
    decision_payload = json.loads(capsys.readouterr().out)
    assert decision_payload["implementation_authorized"] is False
    assert decision_payload["publication_authorized"] is False

    confirmed = load_retrospective(process, "RETRO-001")
    package = build_evolution_package(
        retro=confirmed,
        candidate_id="CAND-001",
        recommendation_decision="accepted",
        recommendation_decision_ref="decisions/EVO-001.yaml",
        evolution_id="EVO-001",
        work_id="EVOW-001",
        independent_evidence_sources=("project-a/W-001", "project-b/W-002"),
        baseline_oid=baseline_oid,
        risk_profile="G1",
        scope=WorkScope(
            1,
            (
                "works/EVOW-001/REQUEST.md",
                "retrospectives/RETRO-001.yaml",
                "meta_flow/work/**",
            ),
            ("meta_flow/work/**", "tests/**"),
            ("reproduce", "target-tests", "non-regression"),
        ),
        budget=G1_BUDGET,
        reproduction_steps=("重现摘要重复读取",),
        acceptance_criteria=(
            AcceptanceCriterion("AC-001", "token_reduction", ">=", 30.0, "percent"),
            AcceptanceCriterion(
                "AC-002",
                "traceability_coverage",
                "==",
                100.0,
                "percent",
                non_regression=True,
            ),
        ),
        canary_scope=("fixture", "meta-flow-dogfood"),
        rollback_conditions=("追溯覆盖率低于 100%",),
        reviewer_ref="reviews/EVO-001.yaml",
        expires_at="2099-01-01T00:00:00+00:00",
    )
    package_input = tmp_path / "package-input.yaml"
    package_input.write_text(dump_yaml(package.as_dict()) + "\n", encoding="utf-8")
    package_args = ["--project-root", str(release), "--input", str(package_input)]
    assert package_main(package_args) == 0
    assert json.loads(capsys.readouterr().out)["mutation_count"] == 0
    assert package_main([*package_args, "--apply"]) == 0
    packaged = json.loads(capsys.readouterr().out)
    assert packaged["implementation_authorized"] is False
    assert evolution_check_main(
        ["--project-root", str(release), "--id", "EVO-001"]
    ) == 0
    assert json.loads(capsys.readouterr().out)["decision"] == "PASS"

    start_args = [
        "--project-root",
        str(release),
        "--id",
        "EVO-001",
        "--observed-baseline-oid",
        baseline_oid,
    ]
    assert start_main(start_args) == 0
    start_plan = json.loads(capsys.readouterr().out)
    assert start_plan["decision"] == "READY"
    assert start_plan["mutation_count"] == 0
    authorization_path = tmp_path / "start-auth.yaml"
    authorization_path.write_text(
        dump_yaml(
            {
                "authorization_id": "AUTH-EVO-001",
                "evolution_id": "EVO-001",
                "purpose": "implementation_start",
                "plan_digest": start_plan["plan_digest"],
                "baseline_oid": baseline_oid,
                "expires_at": "2099-01-01T00:00:00+00:00",
                "single_use": True,
                "publication_authorized": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert start_main(
        [*start_args, "--apply", "--authorization", str(authorization_path)]
    ) == 0
    started = json.loads(capsys.readouterr().out)
    assert started["publication_count"] == 0
    assert started["recursive_trigger_count"] == 0

    update_work_status(
        process,
        "EVOW-001",
        expected_status="planned",
        new_status="active",
    )
    update_work_status(
        process,
        "EVOW-001",
        expected_status="active",
        new_status="ready_for_verification",
    )
    result_input = tmp_path / "result-input.yaml"
    result_input.write_text(
        dump_yaml(
            {
                "evolution_id": "EVO-001",
                "reproduction_passed": True,
                "criterion_results": [
                    {
                        "criterion_id": "AC-001",
                        "observed_value": 35.0,
                        "passed": True,
                        "evidence_ref": "evidence/ac-001.json",
                    },
                    {
                        "criterion_id": "AC-002",
                        "observed_value": 100.0,
                        "passed": True,
                        "evidence_ref": "evidence/ac-002.json",
                    },
                ],
                "regression_passed": True,
                "recovery_passed": True,
                "canary_passed": True,
                "independent_review_ref": "",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result_args = ["--project-root", str(release), "--input", str(result_input)]
    assert result_main(result_args) == 0
    assert json.loads(capsys.readouterr().out)["mutation_count"] == 0
    assert result_main([*result_args, "--apply"]) == 0
    result_payload = json.loads(capsys.readouterr().out)
    assert result_payload["decision"] == "PROMOTE_CANDIDATE"
    assert result_payload["publication_authorized"] is False
    assert result_payload["recursive_triggered"] is False
    assert (process / "evolution" / "EVO-001.result.yaml").is_file()
