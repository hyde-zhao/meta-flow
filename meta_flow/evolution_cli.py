"""有界进化 CLI；报告、建议、实现和发布授权互不替代。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from meta_flow.evolution import (
    CriterionResult,
    EvolutionStartAuthorization,
    build_evolution_start_plan,
    build_recommendation_decision,
    evaluate_evolution_result,
    evolution_from_payload,
    load_evolution_package,
    materialize_evolution_work,
    record_recommendation_decision,
    validate_evolution_provenance,
    write_evolution_package_create_only,
    write_evolution_result_create_only,
)
from meta_flow.project.onboarding import check_independent_process_route
from meta_flow.project.scale import load_yaml_object


def _process_root(project_root: Path) -> Path:
    health = check_independent_process_route(project_root)
    if not health.ok or health.process_repo_root is None:
        raise ValueError("vNext project route is not healthy: " + "; ".join(health.errors))
    return health.process_repo_root


def decision_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow evolution decision")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--retro-id", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--decision", choices=["accepted", "changed", "deferred", "rejected"], required=True)
    parser.add_argument("--rationale", required=True)
    parser.add_argument("--decision-ref", required=True)
    parser.add_argument("--restart-condition", default="")
    parser.add_argument("--apply", action="store_true")
    parsed = parser.parse_args(argv)
    kwargs = {
        "retro_id": parsed.retro_id,
        "candidate_id": parsed.candidate_id,
        "decision": parsed.decision,
        "rationale": parsed.rationale,
        "decision_ref": parsed.decision_ref,
        "restart_condition": parsed.restart_condition,
    }
    try:
        process_root = _process_root(parsed.project_root)
        result = (
            record_recommendation_decision(process_root, **kwargs)
            if parsed.apply
            else build_recommendation_decision(process_root, **kwargs)
        )
    except (OSError, ValueError) as exc:
        print(json.dumps({"decision": "BLOCKED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(
        json.dumps(
            {
                **result.as_dict(),
                "operation_decision": "PASS" if parsed.apply else "READY",
                "mutation_count": 1 if parsed.apply else 0,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def package_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow evolution package")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parsed = parser.parse_args(argv)
    try:
        process_root = _process_root(parsed.project_root)
        package = evolution_from_payload(load_yaml_object(parsed.input))
        validate_evolution_provenance(process_root, package)
        if parsed.apply:
            path = write_evolution_package_create_only(process_root, package)
    except (OSError, TypeError, ValueError) as exc:
        print(json.dumps({"decision": "BLOCKED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    payload = {
        "decision": "PASS" if parsed.apply else "READY",
        "evolution_id": package.evolution_id,
        "status": package.status,
        "package_digest": package.digest,
        "mutation_count": 1 if parsed.apply else 0,
        "implementation_authorized": False,
        "publication_authorized": False,
        "recursive_trigger_allowed": False,
    }
    if parsed.apply:
        payload["package_ref"] = path.relative_to(process_root).as_posix()
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def check_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow evolution check")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--id", required=True)
    parsed = parser.parse_args(argv)
    try:
        process_root = _process_root(parsed.project_root)
        package = load_evolution_package(process_root, parsed.id)
        validate_evolution_provenance(process_root, package)
    except (OSError, TypeError, ValueError) as exc:
        print(json.dumps({"decision": "BLOCKED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(
        json.dumps(
            {
                "decision": "PASS",
                "evolution_id": package.evolution_id,
                "status": package.status,
                "risk_profile": package.risk_profile,
                "scope_digest": package.scope.digest,
                "package_digest": package.digest,
                "implementation_authorized": False,
                "publication_authorized": False,
                "recursive_trigger_allowed": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _authorization(path: Path) -> EvolutionStartAuthorization:
    payload = load_yaml_object(path)
    allowed = {
        "authorization_id",
        "evolution_id",
        "purpose",
        "plan_digest",
        "baseline_oid",
        "expires_at",
        "single_use",
        "publication_authorized",
    }
    if set(payload) != allowed:
        raise ValueError("evolution start authorization contains missing or unknown fields")
    return EvolutionStartAuthorization(**payload)


def start_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow evolution start")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--id", required=True)
    parser.add_argument("--observed-baseline-oid", required=True)
    parser.add_argument("--authorization", type=Path, default=None)
    parser.add_argument("--apply", action="store_true")
    parsed = parser.parse_args(argv)
    try:
        process_root = _process_root(parsed.project_root)
        package = load_evolution_package(process_root, parsed.id)
        validate_evolution_provenance(process_root, package)
        plan = build_evolution_start_plan(
            package,
            observed_baseline_oid=parsed.observed_baseline_oid,
        )
        if parsed.apply:
            if parsed.authorization is None:
                raise ValueError("--apply requires a typed --authorization file")
            receipt = materialize_evolution_work(
                process_root,
                plan,
                _authorization(parsed.authorization),
            )
    except (OSError, TypeError, ValueError) as exc:
        print(json.dumps({"decision": "BLOCKED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    payload = {
        "decision": receipt.decision if parsed.apply else plan.decision,
        "evolution_id": package.evolution_id,
        "work_id": package.work_id,
        "plan_digest": plan.plan_digest,
        "reasons": list(plan.reasons),
        "mutation_count": receipt.work_receipt.mutation_count if parsed.apply else 0,
        "publication_count": receipt.publication_count if parsed.apply else 0,
        "recursive_trigger_count": receipt.recursive_trigger_count if parsed.apply else 0,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["decision"] in {"READY", "PASS"} else 1


def result_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow evolution result")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parsed = parser.parse_args(argv)
    try:
        process_root = _process_root(parsed.project_root)
        payload = load_yaml_object(parsed.input)
        package = load_evolution_package(process_root, str(payload.get("evolution_id") or ""))
        results_payload = payload.get("criterion_results")
        if not isinstance(results_payload, list) or not all(isinstance(item, dict) for item in results_payload):
            raise ValueError("criterion_results must be a list of objects")
        result = evaluate_evolution_result(
            package,
            reproduction_passed=payload.get("reproduction_passed"),
            criterion_results=tuple(
                CriterionResult(
                    criterion_id=str(item.get("criterion_id") or ""),
                    observed_value=float(item.get("observed_value")),
                    passed=item.get("passed"),
                    evidence_ref=str(item.get("evidence_ref") or ""),
                )
                for item in results_payload
            ),
            regression_passed=payload.get("regression_passed"),
            recovery_passed=payload.get("recovery_passed"),
            canary_passed=payload.get("canary_passed"),
            independent_review_ref=str(payload.get("independent_review_ref") or ""),
        )
        if parsed.apply:
            path = write_evolution_result_create_only(process_root, result)
    except (OSError, TypeError, ValueError) as exc:
        print(json.dumps({"decision": "BLOCKED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    output = {
        **result.as_dict(),
        "operation_decision": "PASS" if parsed.apply else "READY",
        "mutation_count": 1 if parsed.apply else 0,
    }
    if parsed.apply:
        output["result_ref"] = path.relative_to(process_root).as_posix()
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = argv or []
    if not args or args[0] in {"-h", "--help"}:
        print(
            "usage: meta-flow evolution <decision|package|check|start|result> [options]\n\n"
            "Mutations are dry-run by default; implementation start additionally requires typed authorization.\n"
        )
        return 0
    command, forwarded = args[0], args[1:]
    if command == "decision":
        return decision_main(forwarded)
    if command == "package":
        return package_main(forwarded)
    if command == "check":
        return check_main(forwarded)
    if command == "start":
        return start_main(forwarded)
    if command == "result":
        return result_main(forwarded)
    raise SystemExit("未知 evolution 命令，目前支持: decision, package, check, start, result")
