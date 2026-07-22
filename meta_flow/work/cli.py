"""vNext Work 命令行入口。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

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
from meta_flow.work.lifecycle import update_work_status
from meta_flow.work.model import build_work, load_work
from meta_flow.work.risk import HIGH_RISK_FIELDS, RiskFacts, classify_work
from meta_flow.work.scope import WorkScope
from meta_flow.work.store import (
    WorkInitApplyError,
    apply_work_init,
    close_work,
    plan_work_init,
)
from meta_flow.work.usage import UsageEvent, append_usage_event
from meta_flow.workspace.git_sync import run_git

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
    parser.add_argument("--apply", action="store_true")
    _add_risk_arguments(parser)
    parsed = parser.parse_args(argv or [])
    try:
        release_root, process_root = _resolve_roots(parsed.project_root)
        project = load_project(process_root)
        classification = classify_work(
            _risk_facts(parsed),
            requested_cr=parsed.requested_cr,
            requested_profile=parsed.upgrade_to,
            g2_budget=_g2_budget(parsed),
        )
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
        )
        plan = plan_work_init(process_root, work)
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


def status_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow work status")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--work-id", required=True)
    parsed = parser.parse_args(argv or [])
    try:
        _release_root, process_root = _resolve_roots(parsed.project_root)
        work = load_work(process_root, parsed.work_id)
    except (OSError, ValueError) as exc:
        print(json.dumps({"decision": "BLOCKED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    payload = {
        "decision": "PASS",
        "work": work.as_dict(),
        "default_objects_read": 1,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


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
    else:
        parser.add_argument("--expected-status", default=defaults[command][0])
    parsed = parser.parse_args(argv or [])
    try:
        release_root, process_root = _resolve_roots(parsed.project_root)
        if command == "close":
            updated = close_work(
                process_root,
                parsed.work_id,
                expected_status=parsed.expected_status,
                outcome=parsed.outcome,
                result_ref=parsed.result_ref,
            )
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
    parsed = parser.parse_args(argv or [])
    try:
        _release_root, process_root = _resolve_roots(parsed.project_root)
        mapping: dict[str, str] = {}
        for item in parsed.check_risk:
            check_id, separator, risk = item.partition("=")
            if not separator or not check_id or not risk or check_id in mapping:
                raise ValueError("--check-risk must use unique check-id=risk entries")
            mapping[check_id] = risk
        plan = build_validation_plan(
            load_work(process_root, parsed.work_id),
            check_risk_mapping=mapping,
            independent_qa_ref=parsed.independent_qa_ref,
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
            {"decision": "PASS", "handoff_ref": path.relative_to(process_root).as_posix(), **handoff.as_dict()},
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
        )
        result = append_usage_event(process_root, parsed.work_id, event)
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
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.decision in {"RECORDED", "NO_CHANGE"} else 1


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
            "  start     Move a planned Work to active.\n"
            "  pause     Pause an active Work.\n"
            "  resume    Resume a paused Work.\n"
            "  block     Mark an active Work blocked.\n"
            "  close     Complete or cancel a Work and remove its active Project ref.\n"
            "  usage-add Record one scoped usage event after a pre-mutation budget check.\n"
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
    if command in {"start", "pause", "resume", "block", "close"}:
        return transition_main(command, forwarded)
    if command == "usage-add":
        return usage_add_main(forwarded)
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
    if command in {"status", "check"}:
        return status_main(forwarded)
    raise SystemExit(
        f"未知 work 命令: {command}. 目前支持: classify, init, start, pause, resume, block, close, usage-add, review-plan, validation-plan, handoff, resume-check, decision-bundle-check, git-inventory, status, check"
    )
