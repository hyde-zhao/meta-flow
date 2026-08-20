"""vNext Work 命令行入口。"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from meta_flow.execution_control.contract import CONTAINER_ROLES, ExecutionUnitV1
from meta_flow.project.model import load_project
from meta_flow.project.process_route import require_process_route
from meta_flow.project.scale import load_yaml_object
from meta_flow.work.assurance import build_review_plan, build_validation_plan
from meta_flow.work.budget import BudgetLimit
from meta_flow.work.decision_bundle import validate_bundle
from meta_flow.work.git_inventory import InventoryCandidate, build_inventory
from meta_flow.work.handoff import (
    build_handoff,
    load_handoff,
    resume_precheck,
    write_handoff,
)
from meta_flow.work.init_transaction import (
    build_execution_contract_admission_validator,
    inspect_work_init_transactions,
)
from meta_flow.work.lifecycle import update_work_status
from meta_flow.work.lifecycle_transaction import (
    WorkCloseAuthorizationV1,
    apply_work_close,
    inspect_work_close_transactions,
    plan_work_close,
    recover_work_close_transaction,
)
from meta_flow.work.model import (
    G1ScopeDeltaV1,
    GovernanceProviderIdentityV1,
    build_work,
    load_work,
)
from meta_flow.work.preflight import render_preflight_result, run_lifecycle_preflight
from meta_flow.work.production_validation import (
    build_governance_provider_admission_validator,
)
from meta_flow.work.publication_close import (
    WorkPublicationCloseAuthorizationV1,
    apply_work_publication_close,
    plan_work_publication_close,
    require_external_publication_authorization_path,
)
from meta_flow.work.read_context import OperationReadContext
from meta_flow.work.risk import HIGH_RISK_FIELDS, RiskFacts, classify_work
from meta_flow.work.route_profile import RouteProfile, evaluate_route_profile
from meta_flow.work.scope import WorkScope, check_scope
from meta_flow.work.scope_amend import (
    apply_g1_scope_amend,
    inspect_g1_scope_amend,
    load_g1_scope_amend_authorization,
    plan_g1_scope_amend,
    recover_g1_scope_amend,
)
from meta_flow.work.store import (
    WorkInitApplyError,
    apply_legacy_partial_work_init_recovery,
    apply_work_init,
    plan_legacy_partial_work_init_recovery,
    plan_work_init_from_release_root,
    recover_partial_work_init_transaction,
)
from meta_flow.work.usage import UsageEvent
from meta_flow.work.usage_admission import (
    execute_admitted_operation,
    plan_operation_admission,
    plan_usage_admission,
)
from meta_flow.work.validation_planner import build_validation_execution_plan
from meta_flow.work.validation_receipt import load_validation_receipt
from meta_flow.workspace.git_sync import run_git

PUBLIC_OPERATION_DECLARATIONS = (
    ("work.close", ("meta-flow", "work", "close")),
    ("work.close-inspect", ("meta-flow", "work", "close-inspect")),
    ("work.close-recover", ("meta-flow", "work", "close-recover")),
    ("work.publication-close", ("meta-flow", "work", "publication-close")),
    ("work.init-inspect", ("meta-flow", "work", "init-inspect")),
    ("work.init-recover", ("meta-flow", "work", "init-recover")),
    ("work.init-preflight", ("meta-flow", "work", "init-preflight")),
    ("work.scope-amend", ("meta-flow", "work", "scope-amend")),
    ("work.scope-amend-inspect", ("meta-flow", "work", "scope-amend-inspect")),
    ("work.scope-amend-recover", ("meta-flow", "work", "scope-amend-recover")),
    ("work.usage-plan", ("meta-flow", "work", "usage-plan")),
    ("work.usage-add", ("meta-flow", "work", "usage-add")),
)

_CLI_HIGH_RISK = {key.replace("_", "-"): key for key in HIGH_RISK_FIELDS}


def _add_risk_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--change-kind", required=True)
    parser.add_argument("--touched-path-count", type=int, required=True)
    parser.add_argument("--non-reversible", action="store_true")
    parser.add_argument("--multi-module", action="store_true")
    parser.add_argument("--internal-interface", action="store_true")
    parser.add_argument("--multi-step", action="store_true")
    parser.add_argument("--repository-push", action="store_true")
    parser.add_argument("--preauthorized-repo-ref", action="store_true")
    parser.add_argument("--high-risk", action="append", choices=sorted(_CLI_HIGH_RISK), default=[])
    parser.add_argument("--unknown-high-risk", action="append", default=[])
    parser.add_argument("--requested-cr", action="store_true")
    parser.add_argument("--upgrade-to", choices=["G0", "G1", "G2"], default=None)
    parser.add_argument("--g2-reads", type=int, default=None)
    parser.add_argument("--g2-writes", type=int, default=None)
    parser.add_argument("--g2-check-groups", type=int, default=None)
    parser.add_argument("--g2-tokens", type=int, default=None)


def _add_route_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--route-mode",
        choices=["routine-four-stage", "legacy-cp0-cp8"],
        default="routine-four-stage",
    )
    parser.add_argument(
        "--dispatch-mode",
        choices=["direct", "functional-agent"],
        default="direct",
    )
    parser.add_argument("--legacy-cp-compatibility", action="store_true")
    parser.add_argument("--human-design-gate-ref", default="")


def _route_profile(parsed: argparse.Namespace) -> RouteProfile:
    return RouteProfile(
        mode=parsed.route_mode,
        dispatch_mode=parsed.dispatch_mode,
        legacy_cp_compatibility=parsed.legacy_cp_compatibility,
    )


def _add_execution_unit_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--execution-unit-id")
    parser.add_argument("--execution-root-concept")
    parser.add_argument("--execution-slice-id")
    parser.add_argument("--execution-container-role", choices=sorted(CONTAINER_ROLES))
    parser.add_argument("--execution-revision", type=int)
    parser.add_argument("--execution-supersedes-unit-id", default="")
    parser.add_argument("--execution-contract-ref")
    parser.add_argument("--execution-contract-digest")


def _execution_unit(parsed: argparse.Namespace) -> ExecutionUnitV1 | None:
    required = {
        "unit_id": parsed.execution_unit_id,
        "root_concept": parsed.execution_root_concept,
        "slice_id": parsed.execution_slice_id,
        "container_role": parsed.execution_container_role,
        "revision": parsed.execution_revision,
        "contract_ref": parsed.execution_contract_ref,
        "contract_digest": parsed.execution_contract_digest,
    }
    supplied = {key for key, value in required.items() if value is not None}
    if not supplied and not parsed.execution_supersedes_unit_id:
        return None
    if supplied != set(required):
        missing = ",".join(sorted(set(required) - supplied))
        raise ValueError(f"execution unit requires all identity/contract fields: missing={missing}")
    return ExecutionUnitV1.from_mapping(
        {
            **required,
            "supersedes_unit_id": parsed.execution_supersedes_unit_id,
        },
        work_id=parsed.work_id,
    )


def _risk_facts(parsed: argparse.Namespace) -> RiskFacts:
    high = {_CLI_HIGH_RISK[item]: True for item in parsed.high_risk}
    return RiskFacts(
        change_kind=parsed.change_kind,
        touched_path_count=parsed.touched_path_count,
        reversible=not parsed.non_reversible,
        multi_module=parsed.multi_module,
        internal_interface=parsed.internal_interface,
        multi_step=parsed.multi_step,
        repository_push=parsed.repository_push,
        preauthorized_repo_ref=parsed.preauthorized_repo_ref,
        unknown_high_risk_facts=tuple(parsed.unknown_high_risk),
        **high,
    )


def _g2_budget(parsed: argparse.Namespace) -> BudgetLimit | None:
    values = (
        parsed.g2_reads,
        parsed.g2_writes,
        parsed.g2_check_groups,
        parsed.g2_tokens,
    )
    if all(value is None for value in values):
        return None
    if any(value is None for value in values):
        raise ValueError("G2 budget requires all four limits")
    return BudgetLimit(
        reads=parsed.g2_reads,
        writes=parsed.g2_writes,
        check_groups=parsed.g2_check_groups,
        tokens=parsed.g2_tokens,
    )


def classify_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow work classify")
    _add_risk_arguments(parser)
    parsed = parser.parse_args(argv or [])
    try:
        decision = classify_work(
            _risk_facts(parsed),
            requested_cr=parsed.requested_cr,
            requested_profile=parsed.upgrade_to,
            g2_budget=_g2_budget(parsed),
        )
    except ValueError as exc:
        print(json.dumps({"decision": "BLOCKED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(decision.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if decision.blocked else 0


def _resolve_roots(project_root: Path) -> tuple[Path, Path]:
    release_root = project_root.resolve()
    return release_root, require_process_route(release_root).process_root


def _head_oid(root: Path) -> str:
    result = run_git(["rev-parse", "--verify", "HEAD"], cwd=root)
    return result.stdout.strip() if result.ok else ""


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} path must be a regular file")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def init_preflight_main(argv: list[str] | None = None) -> int:
    """模拟 Work 成功/失败/no-op，并组合 execution/provider validators；永远零写。"""

    parser = argparse.ArgumentParser(prog="meta-flow work init-preflight")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--input", type=Path, required=True)
    parsed = parser.parse_args(argv or [])
    try:
        payload = _load_json_object(parsed.input, label="preflight input")
        allowed = {
            "schema_version",
            "candidate",
            "context",
            "execution_contract",
            "provider_identity",
        }
        if set(payload) - allowed or payload.get("schema_version") != 1:
            raise ValueError("PREFLIGHT_INPUT_FIELDS_INVALID")
        candidate = payload.get("candidate")
        context = payload.get("context")
        if not isinstance(candidate, Mapping) or not isinstance(context, Mapping):
            raise ValueError("PREFLIGHT_INPUT_CANDIDATE_CONTEXT_INVALID")
        work_id = str(candidate.get("work_id") or "")
        validators: list[tuple[str, object]] = []
        execution = payload.get("execution_contract")
        if execution is not None:
            if not isinstance(execution, Mapping) or set(execution) != {"ref", "unit"}:
                raise ValueError("PREFLIGHT_EXECUTION_CONTRACT_FIELDS_INVALID")
            unit_payload = execution["unit"]
            if not isinstance(unit_payload, Mapping):
                raise ValueError("PREFLIGHT_EXECUTION_UNIT_INVALID")
            unit = ExecutionUnitV1.from_mapping(unit_payload, work_id=work_id)
            validators.append(
                build_execution_contract_admission_validator(
                    parsed.project_root.resolve(),
                    ref=execution["ref"],
                    unit=unit,
                )
            )
        provider = payload.get("provider_identity")
        if provider is not None:
            if not isinstance(provider, Mapping) or set(provider) != {
                "observed",
                "expected",
            }:
                raise ValueError("PREFLIGHT_PROVIDER_FIELDS_INVALID")
            observed_payload = provider["observed"]
            expected_payload = provider["expected"]
            if not isinstance(observed_payload, Mapping) or not isinstance(
                expected_payload, Mapping
            ):
                raise ValueError("PREFLIGHT_PROVIDER_IDENTITY_INVALID")
            validators.append(
                build_governance_provider_admission_validator(
                    GovernanceProviderIdentityV1.from_mapping(observed_payload),
                    GovernanceProviderIdentityV1.from_mapping(expected_payload),
                )
            )
        report = run_lifecycle_preflight(candidate, context, validators=validators)
        rendered = render_preflight_result(report)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {"decision": "BLOCKED", "error": str(exc), "mutation_count": 0},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    print(json.dumps(rendered, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if rendered["decision"] in {"READY", "NO_CHANGE"} else 1


def scope_amend_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow work scope-amend")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--work-id", required=True)
    parser.add_argument("--delta", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--expected-plan-digest", default="")
    parser.add_argument("--apply", action="store_true")
    parsed = parser.parse_args(argv or [])
    try:
        release_root, process_root = _resolve_roots(parsed.project_root)
        delta = G1ScopeDeltaV1.from_mapping(_load_json_object(parsed.delta, label="scope delta"))
        authorization = load_g1_scope_amend_authorization(parsed.authorization)
        release_oid = _head_oid(release_root)
        process_oid = _head_oid(process_root)
        plan = plan_g1_scope_amend(
            release_root,
            work_id=parsed.work_id,
            delta=delta,
            authorization=authorization,
            release_oid=release_oid,
            process_oid=process_oid,
        )
        if not parsed.apply:
            payload = plan.as_dict()
            print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
            return 0 if plan.decision in {"READY", "NO_CHANGE"} else 1
        if not parsed.expected_plan_digest:
            raise ValueError("scope-amend --apply requires --expected-plan-digest")
        payload = apply_g1_scope_amend(
            plan,
            expected_plan_digest=parsed.expected_plan_digest,
            current_authorization=authorization,
            release_oid=release_oid,
            process_oid=process_oid,
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {"decision": "BLOCKED", "error": str(exc), "mutation_count": 0},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["decision"] in {"PASS", "NO_CHANGE"} else 1


def scope_amend_inspect_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow work scope-amend-inspect")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--work-id", default="")
    parsed = parser.parse_args(argv or [])
    try:
        _release_root, process_root = _resolve_roots(parsed.project_root)
        payload = inspect_g1_scope_amend(process_root, work_id=parsed.work_id)
    except (OSError, ValueError) as exc:
        print(json.dumps({"decision": "BLOCKED", "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["decision"] == "PASS" else 1


def scope_amend_recover_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow work scope-amend-recover")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--transaction-id", required=True)
    parser.add_argument("--expected-plan-digest", required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parsed = parser.parse_args(argv or [])
    try:
        release_root, process_root = _resolve_roots(parsed.project_root)
        authorization = load_g1_scope_amend_authorization(parsed.authorization)
        if authorization.release_oid != _head_oid(release_root) or (
            authorization.process_oid != _head_oid(process_root)
        ):
            raise ValueError("G1_SCOPE_AMEND_RECOVERY_OID_MISMATCH")
        payload = recover_g1_scope_amend(
            process_root,
            transaction_id=parsed.transaction_id,
            expected_plan_digest=parsed.expected_plan_digest,
            release_oid=authorization.release_oid,
            process_oid=authorization.process_oid,
        )
    except (OSError, ValueError) as exc:
        print(json.dumps({"decision": "BLOCKED", "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["decision"] == "RECOVERED" else 1


def init_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow work init")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--work-id", required=True)
    parser.add_argument("--objective", required=True)
    parser.add_argument("--request-ref", required=True)
    parser.add_argument("--phase-ref", default="")
    parser.add_argument("--allowed-read", action="append", default=[])
    parser.add_argument("--allowed-write", action="append", default=[])
    parser.add_argument("--required-check", action="append", default=[])
    parser.add_argument("--scope-version", type=int, default=1)
    parser.add_argument("--repair-authorization", type=Path)
    parser.add_argument("--apply", action="store_true")
    _add_risk_arguments(parser)
    _add_route_arguments(parser)
    _add_execution_unit_arguments(parser)
    parsed = parser.parse_args(argv or [])
    try:
        execution_unit = _execution_unit(parsed)
        classification = classify_work(
            _risk_facts(parsed),
            requested_cr=parsed.requested_cr,
            requested_profile=parsed.upgrade_to,
            g2_budget=_g2_budget(parsed),
        )
        profile = _route_profile(parsed)
        route_decision = evaluate_route_profile(
            profile,
            risk_profile=classification.risk_profile,
            work_kind=classification.container_kind,
            human_design_gate_ref=parsed.human_design_gate_ref,
        )
        if route_decision.blocked:
            raise ValueError("; ".join(route_decision.errors))
        release_root, process_root = _resolve_roots(parsed.project_root)
        project = load_project(process_root)
        scope = WorkScope(
            version=parsed.scope_version,
            allowed_reads=tuple(parsed.allowed_read),
            allowed_writes=tuple(parsed.allowed_write),
            required_checks=tuple(parsed.required_check),
        )
        work = build_work(
            work_id=parsed.work_id,
            project_id=project.project_id,
            objective=parsed.objective,
            request_ref=parsed.request_ref,
            phase_ref=parsed.phase_ref,
            scope=scope,
            classification=classification,
            release_base_oid=_head_oid(release_root),
            process_base_oid=_head_oid(process_root),
            route_profile=profile,
            execution_unit=execution_unit,
        )
        plan = plan_work_init_from_release_root(
            release_root,
            work,
            repair_authorization_path=parsed.repair_authorization,
            human_design_gate_ref=parsed.human_design_gate_ref,
        )
    except (OSError, ValueError) as exc:
        print(json.dumps({"decision": "BLOCKED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    if not parsed.apply:
        print(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        return 1 if plan.blocked else 0
    try:
        receipt = apply_work_init(plan)
    except (ValueError, WorkInitApplyError) as exc:
        payload: dict[str, Any] = {"plan": plan.as_dict(), "error": str(exc)}
        if isinstance(exc, WorkInitApplyError):
            payload["receipt"] = exc.receipt.as_dict()
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 1
    print(
        json.dumps(
            {"plan": plan.as_dict(), "receipt": receipt.as_dict()},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _status_main(command: str, argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=f"meta-flow work {command}")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--work-id", required=True)
    parsed = parser.parse_args(argv or [])
    try:
        route = require_process_route(parsed.project_root.resolve())
        with OperationReadContext.from_route(
            route,
            operation_id="work.status.cli",
            operation_kind="query",
            allowed_reads=(f"works/{parsed.work_id}/WORK.yaml",),
            max_objects=1,
        ) as read_context:
            work = load_work(
                route.process_root,
                parsed.work_id,
                read_context=read_context,
            )
            objects_read = read_context.objects_read
    except (OSError, ValueError) as exc:
        print(json.dumps({"decision": "BLOCKED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    payload = {
        "decision": "PASS",
        "work": work.as_dict(),
        "default_objects_read": objects_read,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def status_main(argv: list[str] | None = None) -> int:
    return _status_main("status", argv)


def check_main(argv: list[str] | None = None) -> int:
    return _status_main("check", argv)


def transition_main(command: str, argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=f"meta-flow work {command}")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--work-id", required=True)
    defaults = {
        "start": ("planned", "active"),
        "pause": ("active", "paused"),
        "resume": ("paused", "active"),
        "block": ("active", "blocked"),
    }
    if command == "close":
        parser.add_argument("--expected-status", default="active")
        parser.add_argument("--outcome", choices=["completed", "cancelled"], default="completed")
        parser.add_argument("--result-ref", default="")
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--authorization", type=Path)
    else:
        parser.add_argument("--expected-status", default=defaults[command][0])
    parsed = parser.parse_args(argv or [])
    try:
        release_root, process_root = _resolve_roots(parsed.project_root)
        if command == "close":
            plan = plan_work_close(
                process_root,
                parsed.work_id,
                expected_status=parsed.expected_status,
                outcome=parsed.outcome,
                result_ref=parsed.result_ref,
            )
            if not parsed.apply:
                print(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
                return 0 if plan.ready else 1
            if parsed.authorization is None:
                raise ValueError("Work close --apply requires --authorization")
            authorization_payload = json.loads(parsed.authorization.read_text(encoding="utf-8"))
            if not isinstance(authorization_payload, dict):
                raise ValueError("Work close authorization must be a JSON object")
            authorization = WorkCloseAuthorizationV1.from_mapping(authorization_payload)
            receipt = apply_work_close(process_root, plan, authorization)
            payload = {
                **receipt.as_dict(),
                "status": (
                    load_work(process_root, parsed.work_id).status
                    if receipt.decision == "PASS"
                    else ""
                ),
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
            return 0 if receipt.decision == "PASS" else 1
        elif command == "resume":
            current = load_work(process_root, parsed.work_id)
            handoff = load_handoff(process_root, parsed.work_id)
            precheck = resume_precheck(
                current,
                handoff,
                actual_release_oid=_head_oid(release_root),
                actual_process_oid=_head_oid(process_root),
            )
            if precheck.decision != "READY":
                raise ValueError("resume precheck failed: " + ",".join(precheck.reasons))
            updated = update_work_status(
                process_root,
                parsed.work_id,
                expected_status=parsed.expected_status,
                new_status=defaults[command][1],
            )
        else:
            updated = update_work_status(
                process_root,
                parsed.work_id,
                expected_status=parsed.expected_status,
                new_status=defaults[command][1],
            )
            if command in {"pause", "block"}:
                write_handoff(
                    process_root,
                    build_handoff(
                        updated,
                        release_oid=_head_oid(release_root),
                        process_oid=_head_oid(process_root),
                        completed=(),
                        remaining=("继续当前 Work",),
                        blockers=("等待解除阻塞",) if command == "block" else (),
                        next_step="恢复前先核对 release/process OID 与 scope digest",
                        evidence_refs=(updated.request_ref,),
                    ),
                )
    except (OSError, ValueError) as exc:
        print(json.dumps({"decision": "BLOCKED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(
        json.dumps(
            {"decision": "PASS", "work_id": updated.work_id, "status": updated.status},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def publication_close_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow work publication-close")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--work-id", required=True)
    parser.add_argument("--result-ref", required=True)
    parser.add_argument("--publication-receipt-ref", required=True)
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--apply", action="store_true")
    parsed = parser.parse_args(argv or [])
    try:
        authorization_path: Path | None = None
        if parsed.apply:
            if parsed.authorization is None:
                raise ValueError("Work publication-close --apply requires --authorization")
            authorization_path = require_external_publication_authorization_path(
                parsed.project_root,
                parsed.authorization,
            )
        plan = plan_work_publication_close(
            parsed.project_root,
            parsed.work_id,
            result_ref=parsed.result_ref,
            publication_receipt_ref=parsed.publication_receipt_ref,
        )
        if not parsed.apply:
            print(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
            return 0 if plan.ready else 1
        assert authorization_path is not None
        authorization_payload = json.loads(authorization_path.read_text(encoding="utf-8"))
        if not isinstance(authorization_payload, dict):
            raise ValueError("Work publication-close authorization must be a JSON object")
        authorization = WorkPublicationCloseAuthorizationV1.from_mapping(authorization_payload)
        receipt = apply_work_publication_close(
            parsed.project_root,
            plan,
            authorization,
        )
        payload = {
            **receipt.as_dict(),
            "operation": "work.publication-close",
            "status": (
                load_work(
                    require_process_route(parsed.project_root.resolve()).process_root,
                    parsed.work_id,
                ).status
                if receipt.decision == "PASS"
                else ""
            ),
        }
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {"decision": "BLOCKED", "error": str(exc)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if receipt.decision == "PASS" else 1


def review_plan_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow work review-plan")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--work-id", required=True)
    parser.add_argument("--evidence", action="append", default=[])
    parsed = parser.parse_args(argv or [])
    try:
        _release_root, process_root = _resolve_roots(parsed.project_root)
        evidence: dict[str, str] = {}
        for item in parsed.evidence:
            key, separator, value = item.partition("=")
            if not separator or not key or not value or key in evidence:
                raise ValueError("--evidence must use unique key=ref entries")
            evidence[key] = value
        plan = build_review_plan(load_work(process_root, parsed.work_id), evidence_refs=evidence)
    except (OSError, ValueError) as exc:
        print(json.dumps({"decision": "BLOCKED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(
        json.dumps(
            {
                **plan.__dict__,
                "required_evidence": list(plan.required_evidence),
                "missing_evidence": list(plan.missing_evidence),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if plan.decision == "READY" else 1


def validation_plan_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow work validation-plan")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--work-id", required=True)
    parser.add_argument("--check-risk", action="append", default=[])
    parser.add_argument("--independent-qa-ref", default="")
    parser.add_argument("--layer-fingerprint", action="append", default=[])
    parser.add_argument("--layer-command", action="append", default=[])
    parser.add_argument("--receipt-ref", action="append", default=[])
    parsed = parser.parse_args(argv or [])
    try:
        _release_root, process_root = _resolve_roots(parsed.project_root)
        work = load_work(process_root, parsed.work_id)
        mapping: dict[str, str] = {}
        for item in parsed.check_risk:
            check_id, separator, risk = item.partition("=")
            if not separator or not check_id or not risk or check_id in mapping:
                raise ValueError("--check-risk must use unique check-id=risk entries")
            mapping[check_id] = risk
        layer_fingerprints: dict[str, str] = {}
        layer_commands: dict[str, str] = {}
        for raw, destination, option in (
            (parsed.layer_fingerprint, layer_fingerprints, "--layer-fingerprint"),
            (parsed.layer_command, layer_commands, "--layer-command"),
        ):
            for item in raw:
                layer, separator, digest = item.partition("=")
                if not separator or not layer or not digest or layer in destination:
                    raise ValueError(f"{option} must use unique layer=sha256 entries")
                destination[layer] = digest
        execution_plan = None
        if layer_fingerprints or layer_commands or parsed.receipt_ref:
            receipts = []
            for ref in parsed.receipt_ref:
                if not check_scope(work.scope, "read", ref).allowed:
                    raise ValueError(f"receipt ref is outside Work read scope: {ref}")
                receipts.append(load_validation_receipt(process_root / ref))
            execution_plan = build_validation_execution_plan(
                fingerprints=layer_fingerprints,
                command_identities=layer_commands,
                receipts=tuple(receipts),
            )
        plan = build_validation_plan(
            work,
            check_risk_mapping=mapping,
            independent_qa_ref=parsed.independent_qa_ref,
            execution_plan=execution_plan,
        )
    except (OSError, ValueError) as exc:
        print(json.dumps({"decision": "BLOCKED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if plan.decision == "READY" else 1


def handoff_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow work handoff")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--work-id", required=True)
    parser.add_argument("--completed", action="append", default=[])
    parser.add_argument("--remaining", action="append", default=[])
    parser.add_argument("--blocker", action="append", default=[])
    parser.add_argument("--next-step", required=True)
    parser.add_argument("--evidence-ref", action="append", default=[])
    parsed = parser.parse_args(argv or [])
    try:
        release_root, process_root = _resolve_roots(parsed.project_root)
        handoff = build_handoff(
            load_work(process_root, parsed.work_id),
            release_oid=_head_oid(release_root),
            process_oid=_head_oid(process_root),
            completed=tuple(parsed.completed),
            remaining=tuple(parsed.remaining),
            blockers=tuple(parsed.blocker),
            next_step=parsed.next_step,
            evidence_refs=tuple(parsed.evidence_ref),
        )
        path = write_handoff(process_root, handoff)
    except (OSError, ValueError) as exc:
        print(json.dumps({"decision": "BLOCKED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(
        json.dumps(
            {
                "decision": "PASS",
                "handoff_ref": path.relative_to(process_root).as_posix(),
                **handoff.as_dict(),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def resume_check_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow work resume-check")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--work-id", required=True)
    parsed = parser.parse_args(argv or [])
    try:
        release_root, process_root = _resolve_roots(parsed.project_root)
        decision = resume_precheck(
            load_work(process_root, parsed.work_id),
            load_handoff(process_root, parsed.work_id),
            actual_release_oid=_head_oid(release_root),
            actual_process_oid=_head_oid(process_root),
        )
    except (OSError, ValueError) as exc:
        print(json.dumps({"decision": "BLOCKED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(
        json.dumps(
            {**decision.__dict__, "reasons": list(decision.reasons)},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if decision.decision == "READY" else 1


def usage_add_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow work usage-add")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--work-id", required=True)
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--reads", type=int, default=0)
    parser.add_argument("--writes", type=int, default=0)
    parser.add_argument("--check-groups", type=int, default=0)
    parser.add_argument("--human-interactions", type=int, default=0)
    parser.add_argument("--design-revisions", type=int, default=0)
    parser.add_argument("--qa-attempts", type=int, default=0)
    parser.add_argument("--final-full-suites", type=int, default=0)
    parser.add_argument("--tokens", type=int, default=None)
    parser.add_argument(
        "--token-status",
        choices=["measured", "proxy", "unavailable"],
        default="measured",
    )
    parser.add_argument("--proxy-method", default="")
    parser.add_argument("--unavailable-reason", default="")
    parser.add_argument("--admission-digest", required=True)
    parsed = parser.parse_args(argv or [])
    token_value = None if parsed.token_status == "unavailable" else (parsed.tokens or 0)
    try:
        _release_root, process_root = _resolve_roots(parsed.project_root)
        event = UsageEvent(
            event_id=parsed.event_id,
            stage=parsed.stage,
            reads=parsed.reads,
            writes=parsed.writes,
            check_groups=parsed.check_groups,
            tokens=token_value,
            token_measurement_status=parsed.token_status,
            proxy_method=parsed.proxy_method,
            unavailable_reason=parsed.unavailable_reason,
            human_interactions=parsed.human_interactions,
            design_revisions=parsed.design_revisions,
            qa_attempts=parsed.qa_attempts,
            final_full_suites=parsed.final_full_suites,
        )
        permit = plan_operation_admission(
            process_root,
            parsed.work_id,
            event,
            operation="usage-record",
        )
        if permit.usage_plan_digest != parsed.admission_digest:
            raise ValueError("usage admission digest drifted before operation reservation")
        operation_receipt, _operation_result = execute_admitted_operation(
            process_root,
            permit,
            event,
            lambda: None,
        )
        result = operation_receipt.reservation
        if result is None:
            raise ValueError("usage operation did not produce a reservation result")
    except (OSError, ValueError) as exc:
        print(json.dumps({"decision": "BLOCKED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    payload = {
        "decision": result.decision,
        "event_id": result.event_id,
        "appended": result.appended,
        "budget_decision": result.budget.decision,
        "exceeded_dimensions": list(result.budget.exceeded_dimensions),
        "remaining": result.budget.remaining,
        "ledger_ref": result.ledger_ref,
        "admission_decision": permit.decision,
        "post_action": permit.post_action,
        "operation_receipt": operation_receipt.as_dict(),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.decision in {"RECORDED", "NO_CHANGE"} else 1


def close_inspect_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow work close-inspect")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parsed = parser.parse_args(argv or [])
    try:
        _release_root, process_root = _resolve_roots(parsed.project_root)
        report = inspect_work_close_transactions(process_root)
    except (OSError, ValueError) as exc:
        print(json.dumps({"decision": "BLOCKED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["decision"] == "PASS" else 1


def close_recover_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow work close-recover")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--authorization-id", required=True)
    parsed = parser.parse_args(argv or [])
    try:
        _release_root, process_root = _resolve_roots(parsed.project_root)
        receipt = recover_work_close_transaction(
            process_root,
            parsed.authorization_id,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"decision": "BLOCKED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(receipt.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if receipt.decision in {"RECOVERED", "NO_CHANGE"} else 1


def init_inspect_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow work init-inspect")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--work-id", required=True)
    parsed = parser.parse_args(argv or [])
    try:
        release_root, process_root = _resolve_roots(parsed.project_root)
        transactions = inspect_work_init_transactions(
            process_root,
            work_id=parsed.work_id,
        )
        recovery_plan = plan_legacy_partial_work_init_recovery(
            release_root,
            parsed.work_id,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {"decision": "BLOCKED", "error": str(exc), "mutation_count": 0},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    payload = {
        "schema_version": 1,
        "kind": "WorkInitInspectionV1",
        "decision": ("RECOVERY_REQUIRED" if recovery_plan.ready else transactions["decision"]),
        "work_id": parsed.work_id,
        "transactions": transactions,
        "legacy_recovery_plan": recovery_plan.as_dict(),
        "mutation_count": 0,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["decision"] in {"PASS", "RECOVERY_REQUIRED"} else 1


def init_recover_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow work init-recover")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--work-id")
    parser.add_argument("--transaction-id")
    parser.add_argument("--plan-digest", required=True)
    parser.add_argument("--apply", action="store_true")
    parsed = parser.parse_args(argv or [])
    try:
        if bool(parsed.work_id) == bool(parsed.transaction_id):
            raise ValueError("choose exactly one of --work-id or --transaction-id")
        release_root, process_root = _resolve_roots(parsed.project_root)
        if parsed.transaction_id:
            inspection = inspect_work_init_transactions(process_root)
            matches = [
                item
                for item in inspection["transactions"]
                if item["transaction_id"] == parsed.transaction_id
            ]
            if len(matches) != 1:
                raise ValueError("Work-init transaction identity is unavailable")
            transaction = matches[0]
            if transaction["plan_digest"] != parsed.plan_digest:
                raise ValueError("Work-init transaction plan digest differs")
            if not parsed.apply:
                print(
                    json.dumps(
                        {
                            "decision": "READY",
                            "operation": "work.init.recover-transaction",
                            "transaction": transaction,
                            "mutation_count": 0,
                        },
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                )
                return 0
            receipt = recover_partial_work_init_transaction(
                release_root,
                transaction_id=parsed.transaction_id,
                expected_plan_digest=parsed.plan_digest,
            )
            print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
            return 0 if receipt["decision"] == "RECOVERED" else 1
        plan = plan_legacy_partial_work_init_recovery(
            release_root,
            str(parsed.work_id),
        )
        if parsed.plan_digest != plan.plan_digest:
            raise ValueError("legacy Work-init recovery plan digest differs")
        if not parsed.apply:
            print(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
            return 0 if plan.ready else 1
        receipt = apply_legacy_partial_work_init_recovery(
            plan,
            expected_plan_digest=parsed.plan_digest,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {"decision": "BLOCKED", "error": str(exc), "mutation_count": 0},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if receipt["decision"] == "RECOVERED" else 1


def usage_plan_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow work usage-plan")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--work-id", required=True)
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--reads", type=int, default=0)
    parser.add_argument("--writes", type=int, default=0)
    parser.add_argument("--check-groups", type=int, default=0)
    parser.add_argument("--human-interactions", type=int, default=0)
    parser.add_argument("--design-revisions", type=int, default=0)
    parser.add_argument("--qa-attempts", type=int, default=0)
    parser.add_argument("--final-full-suites", type=int, default=0)
    parser.add_argument("--tokens", type=int, default=None)
    parser.add_argument(
        "--token-status",
        choices=["measured", "proxy", "unavailable"],
        default="measured",
    )
    parser.add_argument("--proxy-method", default="")
    parser.add_argument("--unavailable-reason", default="")
    parsed = parser.parse_args(argv or [])
    token_value = None if parsed.token_status == "unavailable" else (parsed.tokens or 0)
    try:
        _release_root, process_root = _resolve_roots(parsed.project_root)
        event = UsageEvent(
            event_id=parsed.event_id,
            stage=parsed.stage,
            reads=parsed.reads,
            writes=parsed.writes,
            check_groups=parsed.check_groups,
            tokens=token_value,
            token_measurement_status=parsed.token_status,
            proxy_method=parsed.proxy_method,
            unavailable_reason=parsed.unavailable_reason,
            human_interactions=parsed.human_interactions,
            design_revisions=parsed.design_revisions,
            qa_attempts=parsed.qa_attempts,
            final_full_suites=parsed.final_full_suites,
        )
        plan = plan_usage_admission(process_root, parsed.work_id, event)
    except (OSError, ValueError) as exc:
        print(json.dumps({"decision": "BLOCKED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if plan.allowed else 1


def decision_bundle_check_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow work decision-bundle-check")
    parser.add_argument("--bundle", type=Path, required=True)
    parsed = parser.parse_args(argv or [])
    try:
        payload = load_yaml_object(parsed.bundle)
        findings = validate_bundle(payload)
    except (OSError, ValueError) as exc:
        print(json.dumps({"decision": "BLOCKED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(
        json.dumps(
            {
                "decision": "PASS" if not findings else "BLOCKED",
                "findings": [finding.__dict__ for finding in findings],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if not findings else 1


def git_inventory_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow work git-inventory")
    parser.add_argument("--repo", action="append", default=[], help="repo-id=path")
    parser.add_argument(
        "--candidate",
        action="append",
        default=[],
        help="repo-id:subgate:path or repo-id:subgate:path:missing",
    )
    parsed = parser.parse_args(argv or [])
    try:
        roots: dict[str, Path] = {}
        for item in parsed.repo:
            repo_id, separator, path = item.partition("=")
            if not separator or not repo_id or repo_id in roots:
                raise ValueError("--repo must use unique repo-id=path values")
            roots[repo_id] = Path(path).resolve()
        candidates: list[InventoryCandidate] = []
        for item in parsed.candidate:
            parts = item.split(":", 3)
            if len(parts) < 3:
                raise ValueError("--candidate must use repo-id:subgate:path[:missing]")
            repo_id, subgate, path = parts[:3]
            missing = len(parts) == 4 and parts[3] == "missing"
            candidates.append(InventoryCandidate(repo_id, subgate, path, missing))
        result = build_inventory(roots, candidates)
    except (OSError, ValueError) as exc:
        print(json.dumps({"decision": "BLOCKED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if result["execution_sets"]["forbidden"]["count"] else 0


def main(argv: list[str] | None = None) -> int:
    args = argv or []
    if not args or args[0] in {"-h", "--help"}:
        print(
            "usage: meta-flow work <command> [options]\n\n"
            "Commands:\n"
            "  classify  Explain Work/CR and G0/G1/G2 routing.\n"
            "  init      Preview or create one Work envelope.\n"
            "  init-preflight Simulate success/failure/no-op and semantic contracts with zero writes.\n"
            "  init-inspect Inspect Work-init transactions and exact legacy partial recovery.\n"
            "  init-recover Apply one plan-digest-bound legacy partial exact rollback.\n"
            "  scope-amend Plan/apply one typed paused/blocked G0/G1 additive scope successor.\n"
            "  scope-amend-inspect Inspect native G1 scope-amend transactions.\n"
            "  scope-amend-recover Recover one non-terminal G1 scope-amend transaction.\n"
            "  start     Move a planned Work to active.\n"
            "  pause     Pause an active Work.\n"
            "  resume    Resume a paused Work.\n"
            "  block     Mark an active Work blocked.\n"
            "  close     Atomically close Work/Project/Phase and refresh active governance baseline.\n"
            "  publication-close Close a paused Work after exact authorized publication OID changes.\n"
            "  close-inspect Inspect Work close manifests, locks and lineage head generations.\n"
            "  close-recover Recover one consumed Work close authorization by exact manifest.\n"
            "  usage-plan Build a zero-write 60/80/100 stage-aware usage admission plan.\n"
            "  usage-add Record one scoped usage event bound to a fresh admission digest.\n"
            "  review-plan Build a risk-proportional review plan for this Work.\n"
            "  validation-plan Map every declared check to a concrete risk.\n"
            "  handoff    Persist one bounded paused/blocked Work handoff.\n"
            "  resume-check Verify release/process OIDs and scope before resuming.\n"
            "  decision-bundle-check Validate one revision-aware Decision Bundle envelope.\n"
            "  git-inventory Classify candidate paths from Git index facts into eight classes.\n"
            "  status    Read one Work without scanning project history.\n"
        )
        return 0
    command, forwarded = args[0], args[1:]
    if command == "classify":
        return classify_main(forwarded)
    if command == "init":
        return init_main(forwarded)
    if command == "init-preflight":
        return init_preflight_main(forwarded)
    if command == "init-inspect":
        return init_inspect_main(forwarded)
    if command == "init-recover":
        return init_recover_main(forwarded)
    if command == "scope-amend":
        return scope_amend_main(forwarded)
    if command == "scope-amend-inspect":
        return scope_amend_inspect_main(forwarded)
    if command == "scope-amend-recover":
        return scope_amend_recover_main(forwarded)
    if command in {"start", "pause", "resume", "block", "close"}:
        return transition_main(command, forwarded)
    if command == "publication-close":
        return publication_close_main(forwarded)
    if command == "close-inspect":
        return close_inspect_main(forwarded)
    if command == "close-recover":
        return close_recover_main(forwarded)
    if command == "usage-add":
        return usage_add_main(forwarded)
    if command == "usage-plan":
        return usage_plan_main(forwarded)
    if command == "review-plan":
        return review_plan_main(forwarded)
    if command == "validation-plan":
        return validation_plan_main(forwarded)
    if command == "handoff":
        return handoff_main(forwarded)
    if command == "resume-check":
        return resume_check_main(forwarded)
    if command == "decision-bundle-check":
        return decision_bundle_check_main(forwarded)
    if command == "git-inventory":
        return git_inventory_main(forwarded)
    if command == "status":
        return status_main(forwarded)
    if command == "check":
        return check_main(forwarded)
    raise SystemExit(
        f"未知 work 命令: {command}. 目前支持: classify, init, init-preflight, init-inspect, init-recover, scope-amend, scope-amend-inspect, scope-amend-recover, start, pause, resume, block, close, publication-close, close-inspect, close-recover, usage-plan, usage-add, review-plan, validation-plan, handoff, resume-check, decision-bundle-check, git-inventory, status, check"
    )
