"""Read-only adoption readiness doctor."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

from meta_flow.design import product_governance
from meta_flow.project.process_route_adapter import (
    RouteConsumerError,
    RouteConsumerView,
    resolve_configured_consumer_route,
)
from meta_flow.state import current
from meta_flow.workspace.routing import ProcessRouteHealth, check_process_route


@dataclass(frozen=True)
class ReadinessItem:
    item_id: str
    status: str
    evidence: list[str] = field(default_factory=list)
    impact: str = ""
    next_action: str = ""
    messages: list[str] = field(default_factory=list)


def _rel(root: Path, path: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(root.resolve(strict=False)).as_posix()
    except ValueError:
        return path.as_posix()


def _item_status(errors: list[str], warnings: list[str] | None = None, *, warning_status: str = "WARN") -> str:
    if errors:
        return "FAIL"
    if warnings:
        return warning_status
    return "PASS"


def _workspace_item(root: Path, health: ProcessRouteHealth) -> ReadinessItem:
    messages = [*health.warnings, *health.errors]
    return ReadinessItem(
        item_id="workspace-route",
        status="FAIL" if health.blocking else ("WARN" if health.warnings else "PASS"),
        evidence=[
            _rel(root, health.link_path),
            *([_rel(root, health.metadata_path)] if health.metadata_path else []),
        ],
        impact="process route health controls whether Meta Flow can safely write process artifacts.",
        next_action="Run meta-flow workspace bootstrap --artifact-root <relative-artifact-root> --project-name <project-name>.",
        messages=messages,
    )


def _binding_workspace_item(root: Path, route: RouteConsumerView) -> ReadinessItem:
    return ReadinessItem(
        item_id="workspace-route",
        status="PASS",
        evidence=[
            _rel(root, root / ".meta-flow" / "workspace.yaml"),
            route.source,
        ],
        impact="tracked sibling binding resolves the canonical process repository.",
        next_action="No legacy link/bootstrap action is required.",
        messages=[
            f"route_mode={route.route_mode}",
            f"process_root={route.process_root}",
        ],
    )


def _blocked_binding_workspace_item(error: RouteConsumerError) -> ReadinessItem:
    return ReadinessItem(
        item_id="workspace-route",
        status="FAIL",
        evidence=[".meta-flow/workspace.yaml"],
        impact="tracked process route is present but cannot be resolved safely.",
        next_action="Repair the tracked binding; do not restore a legacy process symlink.",
        messages=[f"{error.code}: {error}"],
    )


def _state_item(root: Path, process_root: Path | None) -> ReadinessItem:
    errors, warnings = current.check_current_state(
        root, process_root=process_root
    )
    return ReadinessItem(
        item_id="state-v2",
        status=_item_status(errors, warnings),
        evidence=[
            current.STATE_CURRENT_REL.as_posix(),
            current.STATE_MD_REL.as_posix(),
        ],
        impact="STATE.current.json and base ledgers are required before CR, CP, and handoff events can be audited.",
        next_action="Run meta-flow workspace bootstrap or meta-flow state init --project-root . followed by meta-flow state render.",
        messages=[*warnings, *errors],
    )


def _cr_tracking_item(root: Path, process_root: Path | None) -> ReadinessItem:
    routed_root = process_root or (root / "process")
    index = routed_root / "changes" / "CR-INDEX.json"
    legacy_index = routed_root / "changes" / "CR-INDEX.yaml"
    if index.is_file():
        status = "PASS"
        messages: list[str] = []
        try:
            data = json.loads(index.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            data = {}
            status = "FAIL"
            messages.append(f"CR-INDEX.json invalid JSON: {exc}")
        if status != "FAIL":
            from meta_flow.workflow.cr_lifecycle import validate_index_payload

            projection_errors = validate_index_payload(data)
            if projection_errors:
                status = "FAIL"
                messages.extend(f"CR-INDEX.json projection error: {error}" for error in projection_errors)
        blocked = [
            str(item.get("id") or item.get("cr_id") or "")
            for item in data.get("items", [])
            if isinstance(item, dict)
            and str(item.get("lifecycle_status") or item.get("status") or "").strip().lower() == "blocked"
        ]
        if blocked and status != "FAIL":
            status = "WARN"
            messages.append("blocked CRs are present in CR-INDEX.json; resolve or explicitly carry them before adoption.")
        if legacy_index.is_file():
            messages.append("legacy CR-INDEX.yaml is present; CR-INDEX.json is canonical and YAML is read-only legacy fallback.")
            if status == "PASS":
                status = "WARN"
        return ReadinessItem(
            item_id="cr-tracking",
            status=status,
            evidence=["process/changes/CR-INDEX.json"],
            impact="CR-INDEX.json prevents conflicting active or blocked formal CRs.",
            next_action="Run meta-flow check cr-tracking --project-root . after creating or updating bootstrap CR records.",
            messages=messages,
        )
    if legacy_index.is_file():
        return ReadinessItem(
            item_id="cr-tracking",
            status="WARN",
            evidence=["process/changes/CR-INDEX.yaml"],
            impact="A legacy YAML CR index exists, but new Meta Flow tracking is JSON-only.",
            next_action="Review `meta-flow cr index --project-root .`, then apply it with explicit --apply and expected process OID; YAML remains read-only legacy fallback.",
            messages=["CR-INDEX.json missing; legacy CR-INDEX.yaml is not a new-flow truth source"],
        )
    return ReadinessItem(
        item_id="cr-tracking",
        status="WARN",
        evidence=["process/changes/"],
        impact="No CR index exists yet; this is acceptable before the first bootstrap CR but must be closed before execution.",
        next_action="Create a formal CR, review `meta-flow cr index --project-root .`, then explicitly apply the projection before execution.",
        messages=["CR-INDEX.json missing"],
    )


def _identity_item(root: Path) -> ReadinessItem:
    report = product_governance.scan_delivery_routing(root)
    return ReadinessItem(
        item_id="package-identity",
        status=_item_status(report.errors, report.warnings, warning_status="WARN"),
        evidence=report.evidence or [product_governance.PACKAGE_IDENTITY_REL.as_posix()],
        impact="Package identity and delivery routing prevent Meta Flow defaults from overwriting target project conventions.",
        next_action="Run meta-flow identity init/check/scan --project-root . and confirm delivery routing before production adoption.",
        messages=[*report.warnings, *report.errors],
    )


def _quality_item(root: Path, process_root: Path | None) -> ReadinessItem:
    from meta_flow.checks import quality_governance

    model_errors, model_warnings = quality_governance.validate_quality_model(
        root, process_root=process_root
    )
    eval_errors, eval_warnings = quality_governance.validate_eval_matrix(
        root, process_root=process_root
    )
    missing_only = [*model_errors, *eval_errors] and all("policy missing:" in error for error in [*model_errors, *eval_errors])
    errors = [] if missing_only else [*model_errors, *eval_errors]
    warnings = [*model_warnings, *eval_warnings, *([*model_errors, *eval_errors] if missing_only else [])]
    return ReadinessItem(
        item_id="quality-governance",
        status=_item_status(errors, warnings),
        evidence=[
            quality_governance.QUALITY_MODEL_REL.as_posix(),
            quality_governance.EVAL_MATRIX_REL.as_posix(),
        ],
        impact="Quality policies define derived-only checks and prevent manual dashboard metrics from becoming truth sources.",
        next_action="Run meta-flow quality init --project-root . and meta-flow doctor quality --project-root .",
        messages=[*warnings, *errors],
    )


def _workflow_item(root: Path, process_root: Path | None) -> ReadinessItem:
    routed_root = process_root or (root / "process")
    missing = [
        rel.as_posix()
        for rel in current.BASE_LEDGER_RELS
        if not (routed_root / rel.relative_to("process")).is_file()
    ]
    return ReadinessItem(
        item_id="workflow-ledgers",
        status="FAIL" if missing else "PASS",
        evidence=[rel.as_posix() for rel in current.BASE_LEDGER_RELS],
        impact="Event ledgers are required for CP result, handoff, run, gate, and read expansion audit trails.",
        next_action="Run meta-flow workspace bootstrap --project-root . --artifact-root <relative-artifact-root> --project-name <project-name>.",
        messages=[f"base ledger missing: {path}" for path in missing],
    )


def _human_gate_item(root: Path, process_root: Path | None) -> ReadinessItem:
    required_dirs = [Path("process/checks"), Path("process/checkpoints"), Path("process/context")]
    routed_root = process_root or (root / "process")
    missing = [
        rel.as_posix()
        for rel in required_dirs
        if not (routed_root / rel.relative_to("process")).is_dir()
    ]
    return ReadinessItem(
        item_id="human-gate-readiness",
        status="FAIL" if missing else "PASS",
        evidence=[rel.as_posix() for rel in required_dirs],
        impact="Human gates need checks, checkpoints, and context directories before CP2/CP3/CP5/CP8 launch.",
        next_action="Run workspace bootstrap, then validate each gate with meta-flow check human-gate before asking the user.",
        messages=[f"directory missing: {path}" for path in missing],
    )


def collect_adoption_readiness(project_root: Path) -> list[ReadinessItem]:
    root = project_root.resolve()
    try:
        route = resolve_configured_consumer_route(
            root,
            consumer_id="adoption-readiness",
        )
    except RouteConsumerError as error:
        workspace_item = _blocked_binding_workspace_item(error)
        process_root = None
    else:
        if route is None:
            health = check_process_route(root)
            workspace_item = _workspace_item(root, health)
            process_root = health.project_process_root if health.ok else None
        else:
            workspace_item = _binding_workspace_item(root, route)
            process_root = route.process_root
    return [
        workspace_item,
        _state_item(root, process_root),
        _cr_tracking_item(root, process_root),
        _identity_item(root),
        _quality_item(root, process_root),
        _workflow_item(root, process_root),
        _human_gate_item(root, process_root),
    ]


def run_adoption_doctor(project_root: Path) -> int:
    root = project_root.resolve()
    items = collect_adoption_readiness(root)
    has_fail = any(item.status == "FAIL" for item in items)
    has_warn = any(item.status == "WARN" for item in items)
    print("Adoption Readiness Doctor: " + ("FAIL" if has_fail else "WARN" if has_warn else "OK"))
    print(f"project_root: {root}")
    print("authorization_boundary: no credentials, no runtime, no SaaS, no production write, no trading, CR-033 deferred")
    for item in items:
        print(f"\n[{item.status}] {item.item_id}")
        print(f"impact: {item.impact}")
        print("evidence:")
        for evidence in item.evidence:
            print(f"- {evidence}")
        if item.messages:
            print("messages:")
            for message in item.messages:
                print(f"- {message}")
        print(f"next_action: {item.next_action}")
    return 1 if has_fail else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow doctor adoption")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parsed = parser.parse_args(list(argv or []))
    return run_adoption_doctor(parsed.project_root)
