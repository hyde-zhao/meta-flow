"""CR lifecycle 命令行解析、分组分发与退出码映射。"""

from __future__ import annotations

import argparse
import json
import sys
from functools import partial
from pathlib import Path
from typing import Any

from meta_flow.workflow.cr_analysis import (
    build_impact_report,
    collect_check_errors,
    collect_check_warnings,
    conflict_report,
    proposed_conflict_report,
    render_cr_brief,
    render_goal_brief,
    write_impact_report,
)
from meta_flow.workflow.cr_index import (
    _canonical_digest,
    _dirty_path_digest,
    bootstrap_cr,
    plan_index,
    write_index,
)
from meta_flow.workflow.cr_model import CLOSED_GATE_STATUS, CR_ID_RE
from meta_flow.workflow.cr_projection import (
    AggregateCompletionProjector,
    summary_from_cr_file,
    write_summary,
)
from meta_flow.workflow.cr_records import _rel, discover_formal_crs
from meta_flow.workflow.cr_status_sync import (
    apply_status_sync,
    load_status_sync_authorization,
    plan_status_sync,
)
from meta_flow.workflow.cr_status_transaction import (
    inspect_status_sync_transactions,
    recover_status_sync_transaction,
)
from meta_flow.workflow.cr_termination import (
    apply_cr_termination,
    load_termination_authorization,
    plan_cr_termination,
)


def aggregate_main(
    argv: list[str] | None = None,
    *,
    projector_factory: Any | None = None,
) -> int:
    """运行显式 aggregate evidence gate，不隐式推进 lifecycle。"""
    from meta_flow.workflow.artifact_aggregate import (
        AggregateRequest,
        FileAggregateStore,
        PersistDisposition,
        ProjectFileLegResultReader,
        ProjectionStatus,
        coordinate_aggregate,
    )

    parser = argparse.ArgumentParser(
        prog="meta-flow cr aggregate",
        description=(
            "Validate explicit source/artifact published handles, compute the aggregate, and "
            "optionally persist or project a 2/2 PASS through controlled writers."
        ),
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--id", dest="cr_id", required=True)
    parser.add_argument("--project-id", default="")
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--attempt", type=int, required=True)
    parser.add_argument("--source-handle", type=Path, required=True)
    parser.add_argument("--artifact-handle", type=Path, required=True)
    parser.add_argument("--source-mode", choices=("source-default",), default="source-default")
    parser.add_argument(
        "--artifact-mode",
        choices=("shared-artifact-project-first",),
        default="shared-artifact-project-first",
    )
    parser.add_argument("--policy-version", default="aggregate-v1")
    parser.add_argument("--expected-current-ref", default=None)
    parser.add_argument("--store-root", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--project-completion", action="store_true")
    parser.add_argument("--expected-state-updated-at", default="")
    parsed = parser.parse_args(list(argv or []))
    if not CR_ID_RE.fullmatch(parsed.cr_id):
        parser.error("--id must use CR-xxx naming")
    if parsed.project_completion and parsed.dry_run:
        parser.error("--project-completion cannot be combined with --dry-run")
    if parsed.project_completion and not parsed.expected_state_updated_at:
        parser.error("--expected-state-updated-at is required with --project-completion")

    project_root = parsed.project_root.resolve()
    handles: list[dict[str, Any]] = []
    for label, path in (("source", parsed.source_handle), ("artifact", parsed.artifact_handle)):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            parser.error(f"unable to read {label} handle: {exc}")
        if not isinstance(payload, dict):
            parser.error(f"{label} handle must be a JSON object")
        handles.append(payload)

    request = AggregateRequest(
        operation_id=parsed.operation_id,
        logical_attempt=parsed.attempt,
        cr_id=parsed.cr_id,
        project_id=parsed.project_id or project_root.name,
        required_legs=("source", "artifact"),
        expected_modes=(
            ("source", parsed.source_mode),
            ("artifact", parsed.artifact_mode),
        ),
        policy_version=parsed.policy_version,
    )
    store_root = parsed.store_root
    if store_root is not None and not store_root.is_absolute():
        store_root = project_root / store_root
    store = None if parsed.dry_run else FileAggregateStore(
        project_root=project_root,
        store_root=store_root,
    )
    factory = projector_factory or AggregateCompletionProjector
    projector = (
        factory(
            project_root=project_root,
            expected_state_updated_at=parsed.expected_state_updated_at,
        )
        if parsed.project_completion
        else None
    )
    command = coordinate_aggregate(
        request,
        handles,
        reader=ProjectFileLegResultReader(project_root),
        store=store,
        projector=projector,
        expected_current_ref=parsed.expected_current_ref,
        dry_run=parsed.dry_run,
        project=parsed.project_completion,
    )
    print(json.dumps(command.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    if command.validation_errors:
        return 2
    if command.write_receipt is not None and command.write_receipt.disposition in {
        PersistDisposition.CONFLICT,
        PersistDisposition.FAILED,
    }:
        return 3
    if command.projection_receipt is not None and command.projection_receipt.status in {
        ProjectionStatus.PARTIAL,
        ProjectionStatus.FAILED,
    }:
        return 4
    return 0


def _print_cr_help() -> None:
    print(
        "usage: meta-flow cr <command> [options]\n\n"
        "Commands:\n"
        "  bootstrap  Create an active bootstrap CR plus summary, index, ledger, CP0 result, and context.\n"
        "  index      Preview a pure CR-INDEX projection; --apply writes it and --rebuild acknowledges corrupt bytes.\n"
        "  summary    Generate process/changes/summaries/<CR>.summary.json.\n"
        "  brief      Print a goal-oriented CR brief from summary/frontmatter.\n"
        "  goal-brief Print all CRs attached to one goal_ref.\n"
        "  impact-report Print a side-effect-free impact surface migration report as JSON.\n"
        "  terminate  Plan or apply an exact-OID, typed, recoverable native CR termination.\n"
        "  status-sync Plan or apply a typed CR status projection transaction.\n"
        "  status-sync-inspect Inspect unresolved private status-sync manifests.\n"
        "  status-sync-resume Resume one explicitly selected unresolved transaction.\n"
        "  status-sync-rollback Roll back one explicitly selected unresolved transaction.\n"
        "  status-sync-abandon Mark one inspected transaction abandoned with typed authorization.\n"
        "  aggregate  Validate explicit published leg handles and persist/project a guarded aggregate.\n"
        "  branch-open Open paired project/artifact CR branches from fresh remote defaults.\n"
        "  branch-publish Publish existing committed CR refs; never stage or commit.\n"
        "  branch-merge Explicitly fast-forward paired remote defaults from published tips.\n"
        "  branch-finish Re-prove merge facts, retain recovery refs, then clean CR branches.\n"
        "  close      Compatibility alias for a typed closed status-sync transaction.\n"
        "  check      Validate CR ledger, index, summaries, and active state refs.\n"
        "  public-operations-check Validate the public operation registry and console discovery.\n"
        "  conflicts  Compare active/proposed/blocked CR conflict keys from CR-INDEX.json.\n\n"
        "Examples:\n"
        '  meta-flow cr bootstrap --id CR-001 --title "target adoption bootstrap" --scope "Initialize Meta Flow adoption readiness." --project-root .\n'
        "  meta-flow cr index --project-root .\n"
        "  meta-flow cr index --project-root . --apply --expected-process-oid <oid>\n"
        "  meta-flow cr summary --id CR-101 --project-root .\n"
        "  meta-flow cr brief --id CR-101 --project-root .\n"
        "  meta-flow cr brief --id CR-101 --mode enforce --project-root .\n"
        "  meta-flow cr goal-brief --goal-ref GOAL-001 --project-root .\n"
        "  meta-flow cr impact-report --project-root .\n"
        '  meta-flow cr terminate --id CR-101 --work-id WORK-101 --status cancelled --reason "superseded by a clean replacement" --expected-process-oid <oid> --project-root .\n'
        '  meta-flow cr terminate --id CR-101 --work-id WORK-101 --status cancelled --reason "superseded by a clean replacement" --expected-process-oid <oid> --expected-plan-digest <digest> --authorization-file authorization.json --apply --project-root .\n'
        "  meta-flow cr status-sync --id CR-101 --status closed --readiness READY_WITH_RISK --gate-status cp8_closed --work-id WORK-101 --effective-at <timestamp> --project-root .\n"
        "  meta-flow cr status-sync --id CR-101 --status closed --work-id WORK-101 --effective-at <timestamp> --project-root . --apply --expected-process-oid <oid> --expected-plan-digest <digest> --authorization-file authorization.json\n"
        "  meta-flow cr aggregate --id CR-051 --operation-id operation-001 --attempt 1 --source-handle source.json --artifact-handle artifact.json --dry-run --project-root .\n"
        "  meta-flow cr branch-open --id CR-101 --slug safe-change --dry-run --project-root .\n"
        "  meta-flow cr branch-publish --id CR-101 --branch cr/cr-101-safe-change --dry-run --project-root .\n"
        "  meta-flow cr branch-merge --id CR-101 --branch cr/cr-101-safe-change --publish-result publish.json --dry-run --project-root .\n"
        "  meta-flow cr branch-finish --id CR-101 --branch cr/cr-101-safe-change --merge-result merge.json --dry-run --project-root .\n"
        "  meta-flow cr close --id CR-101 --readiness READY_WITH_RISK --work-id WORK-101 --effective-at <timestamp> --project-root .\n"
        "  meta-flow cr public-operations-check --project-root .\n"
        "  meta-flow cr conflicts --id CR-102 --project-root .\n"
    )


def _build_cr_command_parser(command: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"meta-flow cr {command}")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--id", dest="cr_id", default="")
    parser.add_argument("--title", default="Meta Flow adoption bootstrap")
    parser.add_argument(
        "--scope",
        default="Bootstrap Meta Flow adoption readiness for this target project.",
    )
    parser.add_argument(
        "--gate-status",
        default="cp2_pending",
        help="Gate status; status-sync --status closed uses and requires cp8_closed.",
    )
    parser.add_argument("--readiness", default="READY")
    parser.add_argument("--status", default="")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--expected-process-oid", default="")
    parser.add_argument("--expected-plan-digest", default="")
    parser.add_argument("--effective-at", default="")
    parser.add_argument("--work-id", default="")
    parser.add_argument("--reason", default="")
    parser.add_argument("--authorization-file", type=Path, default=None)
    parser.add_argument("--historical-migration", action="store_true")
    parser.add_argument("--historical-gate-status", default="")
    parser.add_argument("--historical-lifecycle-status", default="")
    parser.add_argument("--transaction-id", default="")
    parser.add_argument("--typed-authorized", action="store_true")
    parser.add_argument("--goal-ref", default="")
    parser.add_argument("--mode", choices=["audit", "enforce"], default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--proposed", action="store_true")
    parser.add_argument("--conflict-key", action="append", default=[])
    parser.add_argument("--impact-surface", action="append", default=[])
    parser.add_argument("--impact-capability-ref", action="append", default=[])
    parser.add_argument("--impact-feature-ref", action="append", default=[])
    parser.add_argument("--impact-module-path", action="append", default=[])
    parser.add_argument("--impact-policy-ref", action="append", default=[])
    parser.add_argument("--impact-process-ref", action="append", default=[])
    parser.add_argument("--impact-runtime-ref", action="append", default=[])
    parser.add_argument("--impact-data-ref", action="append", default=[])
    return parser


def _dispatch_cr_projection_command(
    command: str,
    parsed: argparse.Namespace,
    project_root: Path,
    dependencies: dict[str, Any],
) -> int | None:
    if command == "bootstrap":
        if not parsed.cr_id:
            raise SystemExit("--id is required and must use CR-xxx naming")
        paths = dependencies["bootstrap_cr"](
            project_root,
            cr_id=parsed.cr_id,
            title=parsed.title,
            scope=parsed.scope,
            gate_status=parsed.gate_status,
            readiness=parsed.readiness,
        )
        for key, path in paths.items():
            print(f"{key}: {path}")
        return 0
    if command == "index":
        plan = dependencies["plan_index"](project_root, rebuild_corrupt=parsed.rebuild)
        printable = {key: value for key, value in plan.items() if key != "expected"}
        if not parsed.apply or plan["decision"] != "READY":
            print(json.dumps(printable, ensure_ascii=False, indent=2, sort_keys=True))
            return 0 if not parsed.apply and plan["decision"] == "READY" else 1
        path = dependencies["write_index"](
            project_root,
            rebuild_corrupt=parsed.rebuild,
            expected_process_oid=parsed.expected_process_oid,
        )
        printable["wrote"] = dependencies["rel"](project_root, path)
        print(json.dumps(printable, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if command == "summary":
        if not parsed.cr_id:
            raise SystemExit("--id is required")
        crs = dependencies["discover_formal_crs"](project_root)
        if parsed.cr_id not in crs:
            raise SystemExit(f"未找到正式 CR: {parsed.cr_id}")
        summary = dependencies["summary_from_cr_file"](project_root, crs[parsed.cr_id])
        path = dependencies["write_summary"](project_root, parsed.cr_id, summary)
        print(f"wrote: {path}")
        return 0
    if command == "brief":
        if not parsed.cr_id:
            raise SystemExit("--id is required")
        print(
            dependencies["render_cr_brief"](
                project_root,
                parsed.cr_id,
                mode=parsed.mode or "audit",
            ),
            end="",
        )
        return 0
    if command == "goal-brief":
        if not parsed.goal_ref:
            raise SystemExit("--goal-ref is required")
        print(dependencies["render_goal_brief"](project_root, parsed.goal_ref), end="")
        return 0
    if command == "impact-report":
        report = dependencies["build_impact_report"](
            project_root,
            mode=parsed.mode or "enforce",
        )
        if parsed.output:
            path = dependencies["write_impact_report"](parsed.output, report)
            print(f"wrote: {path}")
        else:
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    return None


def _dispatch_cr_close_or_termination_command(
    command: str,
    parsed: argparse.Namespace,
    project_root: Path,
    dependencies: dict[str, Any],
) -> int | None:
    if command not in {"close", "terminate"}:
        return None
    if not parsed.cr_id:
        raise SystemExit("--id is required")
    if command == "close":
        plan = dependencies["plan_status_sync"](
            project_root,
            parsed.cr_id,
            status="closed",
            readiness=parsed.readiness,
            gate_status=CLOSED_GATE_STATUS,
            work_id=parsed.work_id,
            expected_process_oid=parsed.expected_process_oid,
            effective_at=parsed.effective_at,
        )
        load_authorization = dependencies["load_status_sync_authorization"]
        apply_plan = dependencies["apply_status_sync"]
        missing_message = "close apply requires --authorization-file"
    else:
        plan = dependencies["plan_cr_termination"](
            project_root,
            parsed.cr_id,
            work_id=parsed.work_id,
            termination_status=parsed.status,
            termination_reason=parsed.reason,
            expected_process_oid=parsed.expected_process_oid,
        )
        load_authorization = dependencies["load_termination_authorization"]
        apply_plan = dependencies["apply_cr_termination"]
        missing_message = "termination apply requires --authorization-file"
    if not parsed.apply:
        print(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if plan.decision in {"READY", "NO_CHANGE"} else 1

    authorization = None
    authorization_error = ""
    if parsed.authorization_file is None:
        authorization_error = missing_message
    else:
        try:
            authorization = load_authorization(parsed.authorization_file)
        except (OSError, ValueError) as exc:
            authorization_error = str(exc)
    if authorization_error:
        result = {
            "status": "BLOCKED",
            "reason": authorization_error,
            "mutation_count": 0,
        }
    elif command == "close" and dependencies["close_cr"] is not None:
        result = dependencies["close_cr"](
            project_root,
            parsed.cr_id,
            readiness=parsed.readiness,
            work_id=parsed.work_id,
            effective_at=parsed.effective_at,
            expected_process_oid=parsed.expected_process_oid,
            expected_plan_digest=parsed.expected_plan_digest,
            authorization=authorization,
            _return_apply_result=True,
        )
    else:
        result = apply_plan(
            project_root,
            plan,
            authorization=authorization,
            expected_plan_digest=parsed.expected_plan_digest,
        )
    printable = {key: value for key, value in result.items() if key != "paths"}
    if "paths" in result:
        printable["path_refs"] = sorted(result["paths"])
    print(json.dumps(printable, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] in {"PASS", "NO_CHANGE"} else 1


def _dispatch_cr_status_sync_command(
    command: str,
    args: list[str],
    parsed: argparse.Namespace,
    project_root: Path,
    dependencies: dict[str, Any],
) -> int | None:
    if command != "status-sync":
        return None
    if not parsed.cr_id:
        raise SystemExit("--id is required")
    plan = dependencies["plan_status_sync"](
        project_root,
        parsed.cr_id,
        status=parsed.status,
        readiness=parsed.readiness if "--readiness" in args else "",
        gate_status=parsed.gate_status if "--gate-status" in args else "",
        work_id=parsed.work_id,
        historical_migration=parsed.historical_migration,
        historical_gate_status=parsed.historical_gate_status,
        historical_lifecycle_status=parsed.historical_lifecycle_status,
        expected_process_oid=parsed.expected_process_oid,
        rebuild_corrupt_index=parsed.rebuild,
        effective_at=parsed.effective_at,
    )
    if not parsed.apply:
        print(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if plan.decision in {"READY", "NO_CHANGE"} else 1
    authorization = None
    authorization_error = ""
    if parsed.authorization_file is None:
        authorization_error = "status-sync apply requires --authorization-file"
    else:
        try:
            authorization = dependencies["load_status_sync_authorization"](
                parsed.authorization_file
            )
        except (OSError, ValueError) as exc:
            authorization_error = str(exc)
    if authorization_error:
        result = {
            "status": "BLOCKED",
            "reason": authorization_error,
            "mutation_count": 0,
        }
    elif dependencies["sync_cr_status"] is not None:
        result = dependencies["sync_cr_status"](
            project_root,
            parsed.cr_id,
            status=parsed.status,
            readiness=parsed.readiness if "--readiness" in args else "",
            gate_status=parsed.gate_status if "--gate-status" in args else "",
            work_id=parsed.work_id,
            historical_migration=parsed.historical_migration,
            historical_gate_status=parsed.historical_gate_status,
            historical_lifecycle_status=parsed.historical_lifecycle_status,
            expected_process_oid=parsed.expected_process_oid,
            effective_at=parsed.effective_at,
            expected_plan_digest=parsed.expected_plan_digest,
            authorization=authorization,
            _plan=plan,
            _return_apply_result=True,
        )
    else:
        result = dependencies["apply_status_sync"](
            project_root,
            plan,
            authorization=authorization,
            expected_plan_digest=parsed.expected_plan_digest,
        )
    printable = {key: value for key, value in result.items() if key != "paths"}
    if "paths" in result:
        printable["path_refs"] = sorted(result["paths"])
    print(json.dumps(printable, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] in {"PASS", "NO_CHANGE"} else 1


def _dispatch_cr_status_sync_recovery_command(
    command: str,
    parsed: argparse.Namespace,
    project_root: Path,
    dependencies: dict[str, Any],
) -> int | None:
    if command == "status-sync-inspect":
        result = dependencies["inspect_status_sync_transactions"](project_root)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if command not in {
        "status-sync-resume",
        "status-sync-rollback",
        "status-sync-abandon",
    }:
        return None
    if not parsed.transaction_id:
        raise SystemExit("--transaction-id is required")
    result = dependencies["recover_status_sync_transaction"](
        project_root,
        parsed.transaction_id,
        action=command.removeprefix("status-sync-"),
        typed_authorized=parsed.typed_authorized,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] in {"PASS", "RECOVERED"} else 1


def _dispatch_cr_diagnostic_command(
    command: str,
    args: list[str],
    parsed: argparse.Namespace,
    project_root: Path,
    dependencies: dict[str, Any],
) -> int | None:
    if command == "check":
        errors = dependencies["collect_check_errors"](project_root)
        warnings = dependencies["collect_check_warnings"](project_root)
        print("CR Lifecycle Check: " + ("FAIL" if errors else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    if command != "conflicts":
        return None
    if not parsed.cr_id:
        raise SystemExit("--id is required")
    proposed_fields = {
        "impact_capability_refs": parsed.impact_capability_ref,
        "impact_feature_refs": parsed.impact_feature_ref,
        "impact_module_paths": parsed.impact_module_path,
        "impact_policy_refs": parsed.impact_policy_ref,
        "impact_process_refs": parsed.impact_process_ref,
        "impact_runtime_refs": parsed.impact_runtime_ref,
        "impact_data_refs": parsed.impact_data_ref,
    }
    has_candidate_fields = bool(
        parsed.conflict_key or parsed.impact_surface or any(proposed_fields.values())
    )
    if parsed.proposed:
        if parsed.output is not None:
            result = {
                "decision": "INVALID",
                "code": "CR_CONFLICT_PROPOSED_INPUT_INVALID",
                "cr_id": parsed.cr_id,
                "mutation_count": 0,
                "planned_mutation_count": 0,
                "conflicts": [],
                "warnings": ["--output is forbidden for zero-write proposed preview"],
            }
        else:
            result = dependencies["proposed_conflict_report"](
                project_root,
                cr_id=parsed.cr_id,
                conflict_keys=parsed.conflict_key,
                impact_surface=parsed.impact_surface,
                impact_fields=proposed_fields,
                title=parsed.title if "--title" in args else "",
                scope=parsed.scope if "--scope" in args else "",
            )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 2 if result["decision"] == "INVALID" else int(
            result["decision"] == "CONFLICT"
        )
    if has_candidate_fields:
        result = {
            "decision": "INVALID",
            "code": "CR_CONFLICT_PROPOSED_INPUT_INVALID",
            "cr_id": parsed.cr_id,
            "mutation_count": 0,
            "planned_mutation_count": 0,
            "conflicts": [],
            "warnings": ["candidate fields require --proposed"],
        }
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 2
    conflicts, warnings = dependencies["conflict_report"](project_root, parsed.cr_id)
    print("CR Conflicts: " + ("FAIL" if conflicts else "OK"))
    for warning in warnings:
        print(f"- WARN: {warning}")
    for conflict in conflicts:
        print(f"- CONFLICT: {conflict}")
    return 1 if conflicts else 0


def main(
    argv: list[str] | None = None,
    *,
    dispatch_dependencies: dict[str, Any] | None = None,
) -> int:
    args = list(argv or [])
    if not args or args[0] in {"-h", "--help"}:
        _print_cr_help()
        return 0
    command = args[0]
    dependencies = dispatch_dependencies or {
        "AggregateCompletionProjector": AggregateCompletionProjector,
        "apply_cr_termination": apply_cr_termination, "apply_status_sync": apply_status_sync,
        "bootstrap_cr": bootstrap_cr, "build_impact_report": build_impact_report,
        "close_cr": None, "collect_check_errors": collect_check_errors,
        "collect_check_warnings": collect_check_warnings, "conflict_report": conflict_report,
        "discover_formal_crs": discover_formal_crs, "plan_index": plan_index,
        "inspect_status_sync_transactions": inspect_status_sync_transactions,
        "load_status_sync_authorization": load_status_sync_authorization,
        "load_termination_authorization": load_termination_authorization,
        "plan_cr_termination": plan_cr_termination, "plan_status_sync": plan_status_sync,
        "proposed_conflict_report": proposed_conflict_report,
        "recover_status_sync_transaction": partial(
            recover_status_sync_transaction,
            canonical_digest=_canonical_digest,
            dirty_path_digest=_dirty_path_digest,
        ),
        "rel": _rel, "render_cr_brief": render_cr_brief,
        "render_goal_brief": render_goal_brief, "summary_from_cr_file": summary_from_cr_file,
        "sync_cr_status": None, "write_impact_report": write_impact_report,
        "write_index": write_index, "write_summary": write_summary,
    }
    if command == "aggregate":
        return aggregate_main(
            args[1:],
            projector_factory=dependencies["AggregateCompletionProjector"],
        )
    if command == "public-operations-check":
        from meta_flow.policies import public_operations

        return public_operations.main(args[1:])
    if command in {"branch-open", "branch-publish", "branch-merge", "branch-finish"}:
        from meta_flow.workflow.git_branch_lifecycle import branch_main

        return branch_main(command, args[1:])
    parsed = _build_cr_command_parser(command).parse_args(args[1:])
    project_root = parsed.project_root.resolve()
    dispatches = (
        lambda: _dispatch_cr_projection_command(command, parsed, project_root, dependencies),
        lambda: _dispatch_cr_close_or_termination_command(command, parsed, project_root, dependencies),
        lambda: _dispatch_cr_status_sync_command(command, args, parsed, project_root, dependencies),
        lambda: _dispatch_cr_status_sync_recovery_command(command, parsed, project_root, dependencies),
        lambda: _dispatch_cr_diagnostic_command(command, args, parsed, project_root, dependencies),
    )
    for dispatch in dispatches:
        result = dispatch()
        if result is not None:
            return result
    raise SystemExit(
        f"未知 cr 命令: {command}. 目前支持: bootstrap, index, summary, brief, goal-brief, impact-report, "
        "terminate, status-sync, status-sync-inspect, status-sync-resume, status-sync-rollback, status-sync-abandon, "
        "aggregate, branch-open, branch-publish, branch-merge, branch-finish, close, check, "
        "public-operations-check, conflicts"
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
