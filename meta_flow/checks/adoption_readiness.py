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
from meta_flow.workspace.routing import ProcessRouteHealth, inspect_legacy_consumer_route


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


def _state_item(
    root: Path,
    process_root: Path | None,
    *,
    binding_aware: bool = False,
) -> ReadinessItem:
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
        next_action=(
            "Run meta-flow state init --project-root . --project-id <project-id>, "
            "then meta-flow state render --project-root . and meta-flow state "
            "current-refresh --project-root ."
            if binding_aware
            else "Run meta-flow workspace bootstrap or meta-flow state init --project-root . followed by meta-flow state render."
        ),
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


def _legacy_registry_item(
    root: Path,
    process_root: Path | None,
    *,
    binding_aware: bool,
) -> ReadinessItem:
    if not binding_aware or process_root is None:
        return ReadinessItem(
            item_id="legacy-registry-ownership",
            status="PASS",
            evidence=[],
            impact="Legacy registry ownership is evaluated only for vNext binding projects.",
            next_action="No vNext legacy registry migration is required for this route.",
            messages=[],
        )
    from meta_flow.workflow.legacy_evidence_registry import (
        LegacyEvidenceError,
        load_declared_legacy_evidence_registry,
        registered_legacy_cr_ids,
    )

    try:
        bundle = load_declared_legacy_evidence_registry(
            root,
            consumer_id="adoption-readiness",
        )
    except LegacyEvidenceError as exc:
        return ReadinessItem(
            item_id="legacy-registry-ownership",
            status="FAIL",
            evidence=["process/PROJECT.yaml"],
            impact="Invalid legacy registry ownership can contaminate native formal CR truth.",
            next_action="Repair the exact registry declaration and rerun meta-flow check cr-tracking.",
            messages=[f"{exc.code}: {exc}"],
        )
    if not bundle.registrations:
        return ReadinessItem(
            item_id="legacy-registry-ownership",
            status="PASS",
            evidence=["process/PROJECT.yaml"],
            impact="No registered legacy CR evidence currently requires persistent ownership.",
            next_action="No legacy registry migration is required.",
            messages=[],
        )
    registered = ", ".join(registered_legacy_cr_ids(bundle))
    if bundle.ownership_scope == "project":
        return ReadinessItem(
            item_id="legacy-registry-ownership",
            status="PASS",
            evidence=["process/PROJECT.yaml", bundle.registry_logical_ref],
            impact="Project-level ownership keeps immutable legacy CR classification across Phases.",
            next_action="Keep the project-level ref and immutable evidence digests unchanged.",
            messages=[f"registered legacy evidence: {registered}"],
        )
    return ReadinessItem(
        item_id="legacy-registry-ownership",
        status="WARN",
        evidence=["process/PROJECT.yaml", bundle.registry_logical_ref],
        impact="Active-Phase-only ownership can lose legacy CR classification at Phase transition.",
        next_action=(
            "Use a scoped meta-flow project phase-metadata plan/apply to append the exact registry "
            "ref and atomically adopt PROJECT.legacy_evidence_registry_ref."
        ),
        messages=[
            f"registered legacy evidence: {registered}",
            "legacy_evidence_registry_ref is using Phase compatibility fallback",
        ],
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


def _workflow_item(
    root: Path,
    process_root: Path | None,
    *,
    binding_aware: bool = False,
) -> ReadinessItem:
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
        next_action=(
            "Run meta-flow state init --project-root . --project-id <project-id>; "
            "the native State initializer creates all base ledgers."
            if binding_aware
            else "Run meta-flow workspace bootstrap --project-root . --artifact-root <relative-artifact-root> --project-name <project-name>."
        ),
        messages=[f"base ledger missing: {path}" for path in missing],
    )


def _human_gate_item(
    root: Path,
    process_root: Path | None,
    *,
    binding_aware: bool = False,
) -> ReadinessItem:
    required_dirs = [Path("process/checks"), Path("process/checkpoints"), Path("process/context")]
    routed_root = process_root or (root / "process")
    missing = [
        rel.as_posix()
        for rel in required_dirs
        if not (routed_root / rel.relative_to("process")).is_dir()
    ]
    gate_required, route_errors, route_messages = _human_gate_requirement(
        root,
        routed_root,
    )
    if route_errors:
        status = "FAIL"
    elif missing and gate_required:
        status = "FAIL"
    elif missing:
        status = "WARN"
    else:
        status = "PASS"
    if route_errors:
        next_action = (
            "Repair STATE.current.json, the native CR index, and the active CR route_plan_ref; "
            "then run meta-flow check human-gate --project-root ."
        )
    elif gate_required:
        next_action = (
            "Run meta-flow context build for the active CR and generate the applicable native "
            "checkpoint evidence, then run meta-flow check human-gate --project-root ."
        )
    else:
        next_action = (
            "No gate scaffold is required for the current G0/G1 route. When a formal G2 change "
            "starts, use meta-flow cr bootstrap and meta-flow context build, then validate with "
            "meta-flow check human-gate."
            if binding_aware
            else "No gate scaffold is required until a formal G2 route starts."
        )
    return ReadinessItem(
        item_id="human-gate-readiness",
        status=status,
        evidence=[rel.as_posix() for rel in required_dirs],
        impact="Human gates need checks, checkpoints, and context directories before CP2/CP3/CP5/CP8 launch.",
        next_action=next_action,
        messages=[
            *route_messages,
            *route_errors,
            *(f"directory missing: {path}" for path in missing),
        ],
    )


def _safe_process_ref(process_root: Path, value: object, *, subject: str) -> Path:
    ref = str(value or "").split("#", 1)[0].strip().strip('"').strip("'")
    path = Path(ref)
    if (
        not ref.startswith("process/")
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"{subject} must be one safe process/... logical ref")
    candidate = (process_root / Path(*path.parts[1:])).resolve(strict=False)
    if not candidate.is_relative_to(process_root.resolve()):
        raise ValueError(f"{subject} escapes the process repository")
    return candidate


def _read_json_object(path: Path, *, subject: str) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{subject} missing or not a regular file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{subject} invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{subject} must contain a JSON object")
    return payload


def _human_gate_requirement(
    project_root: Path,
    process_root: Path,
) -> tuple[bool, list[str], list[str]]:
    """从 bounded State/CR/route truth 判定当前是否需要人工门基础设施。"""

    errors: list[str] = []
    messages: list[str] = []
    state_path = process_root / "state/STATE.current.json"
    index_path = process_root / "changes/CR-INDEX.json"
    state: dict[str, object] = {}
    if state_path.is_symlink() or (state_path.exists() and not state_path.is_file()):
        return False, ["STATE.current.json is not a regular file"], messages
    if state_path.is_file():
        try:
            state = _read_json_object(state_path, subject="STATE.current.json")
        except ValueError as exc:
            return False, [str(exc)], messages

    active_items: list[dict[str, object]] = []
    if index_path.is_symlink() or (index_path.exists() and not index_path.is_file()):
        return False, ["CR-INDEX.json is not a regular file"], messages
    if index_path.is_file():
        try:
            index = _read_json_object(index_path, subject="CR-INDEX.json")
        except ValueError as exc:
            return False, [str(exc)], messages
        from meta_flow.workflow.cr_lifecycle import validate_index_payload

        index_errors = validate_index_payload(index)
        if index_errors:
            return False, [f"CR-INDEX.json projection error: {item}" for item in index_errors], messages
        active_items = [
            item
            for item in index.get("items", [])
            if isinstance(item, dict)
            and str(item.get("lifecycle_status") or "").strip().lower()
            in {"active", "blocked"}
        ]

    active_change = str(state.get("active_change") or "").strip()
    pending_gate = str(state.get("pending_gate") or "").strip()
    if not state and active_items:
        return False, ["active formal CR exists while STATE.current.json is missing"], messages
    if len(active_items) > 1:
        identities = ", ".join(str(item.get("id") or "") for item in active_items)
        return False, [f"multiple active/blocked formal CRs make the current route ambiguous: {identities}"], messages
    indexed_change = str(active_items[0].get("id") or "") if active_items else ""
    if active_change != indexed_change:
        if active_change or indexed_change:
            return False, [
                "STATE.active_change and CR-INDEX active/blocked formal truth differ: "
                f"{active_change or '-'} != {indexed_change or '-'}"
            ], messages
    if pending_gate:
        messages.append(f"pending_gate={pending_gate}")
        return True, errors, messages
    if not active_items:
        messages.append("no active/blocked formal CR; gate scaffold is on-demand")
        return False, errors, messages

    active = active_items[0]
    try:
        cr_path = _safe_process_ref(
            process_root,
            active.get("formal_cr_path"),
            subject="active CR formal_cr_path",
        )
        if cr_path.is_symlink() or not cr_path.is_file():
            raise ValueError("active CR formal truth missing or not a regular file")
        from meta_flow.policies.route_plan import parse_cr_frontmatter

        frontmatter = parse_cr_frontmatter(cr_path)
        route_path = _safe_process_ref(
            process_root,
            frontmatter.get("route_plan_ref"),
            subject="active CR route_plan_ref",
        )
        route = _read_json_object(route_path, subject="active CR route plan")
    except (OSError, ValueError) as exc:
        return False, [str(exc)], messages
    if route.get("decision") == "BLOCKED":
        return False, ["active CR route plan decision is BLOCKED"], messages
    applicability = route.get("checkpoint_applicability")
    if not isinstance(applicability, dict):
        return False, ["active CR route plan checkpoint_applicability is missing or invalid"], messages
    required = any(
        isinstance(item, dict)
        and bool(item.get("applies"))
        and item.get("decision") != "WAIVED"
        and item.get("human_gate") == "required"
        for item in applicability.values()
    )
    messages.append(
        "active formal CR route requires a human gate"
        if required
        else "active formal CR route has no applicable required human gate"
    )
    return required, errors, messages


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
        binding_aware = True
    else:
        if route is None:
            health = inspect_legacy_consumer_route(
                root,
                consumer_id="adoption-readiness",
            )
            workspace_item = _workspace_item(root, health)
            process_root = health.project_process_root if health.ok else None
            binding_aware = False
        else:
            workspace_item = _binding_workspace_item(root, route)
            process_root = route.process_root
            binding_aware = True
    return [
        workspace_item,
        _state_item(root, process_root, binding_aware=binding_aware),
        _cr_tracking_item(root, process_root),
        _legacy_registry_item(
            root,
            process_root,
            binding_aware=binding_aware,
        ),
        _identity_item(root),
        _quality_item(root, process_root),
        _workflow_item(root, process_root, binding_aware=binding_aware),
        _human_gate_item(root, process_root, binding_aware=binding_aware),
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
