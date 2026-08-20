"""CR lifecycle 兼容 facade：显式重导出、调用时注入和 CLI 转发。"""
# ruff: noqa: I001

from __future__ import annotations

import inspect
import sys
from functools import partial
from pathlib import Path
from typing import Any

from meta_flow.state import current as current
from meta_flow.workflow import cr_cli as _cr_cli
from meta_flow.workflow.cr_analysis import (
    _conflict_surface as _conflict_surface,
    _load_summary as _load_summary,
    build_impact_report as build_impact_report,
    build_cr_lifecycle_check_report as build_cr_lifecycle_check_report,
    collect_check_errors as collect_check_errors,
    collect_check_warnings as collect_check_warnings,
    conflict_report as conflict_report,
    proposed_conflict_report as proposed_conflict_report,
    render_cr_brief as render_cr_brief,
    render_goal_brief as render_goal_brief,
    write_impact_report as write_impact_report,
)
from meta_flow.workflow.cr_cli import (
    _print_cr_help as _print_cr_help,
    aggregate_main as aggregate_main,
)
from meta_flow.workflow.cr_index import (
    BootstrapCRPlanV1 as BootstrapCRPlanV1,
    CR_INDEX_REL as CR_INDEX_REL,
    INDEX_SCHEMA_VERSION as INDEX_SCHEMA_VERSION,
    _canonical_digest as _canonical_digest,
    _cr_numeric_sort_key as _cr_numeric_sort_key,
    _dirty_path_digest as _dirty_path_digest,
    _index_item as _index_item,
    _native_cr_minimum as _native_cr_minimum,
    _record_override as _record_override,
    _update_current_active_change as _update_current_active_change,
    _validate_native_formal_cr as _validate_native_formal_cr,
    _write_bootstrap_cr_file as _write_bootstrap_cr_file,
    _write_cp0_result as _write_cp0_result,
    apply_bootstrap_cr as apply_bootstrap_cr,
    build_index as build_index,
    inspect_bootstrap_transactions as inspect_bootstrap_transactions,
    load_index as load_index,
    plan_bootstrap_cr as plan_bootstrap_cr,
    plan_index as plan_index,
    recover_bootstrap_transaction as recover_bootstrap_transaction,
    validate_index_payload as validate_index_payload,
    write_index as write_index,
)
from meta_flow.workflow.cr_index import close_cr as _index_close_cr
from meta_flow.workflow.cr_model import (
    ALLOWED_CR_TYPES as ALLOWED_CR_TYPES,
    ALLOWED_LIFECYCLE_STATUSES as ALLOWED_LIFECYCLE_STATUSES,
    CLOSED_GATE_STATUS as CLOSED_GATE_STATUS,
    CR_ID_RE as CR_ID_RE,
    DIGEST_RE as DIGEST_RE,
    FINISHED_STATUSES as FINISHED_STATUSES,
    OID_RE as OID_RE,
    SAFE_AUTHORIZATION_ID_RE as SAFE_AUTHORIZATION_ID_RE,
    CRRecord as CRRecord,
    normalize_cr_type as normalize_cr_type,
    now_utc as now_utc,
    parse_frontmatter as parse_frontmatter,
    render_frontmatter_fields as render_frontmatter_fields,
)
from meta_flow.workflow.cr_projection import (
    CR_ARCHIVE_ROOT_REL as CR_ARCHIVE_ROOT_REL,
    CR_LEDGER_REL as CR_LEDGER_REL,
    STATE_CURRENT_REL as STATE_CURRENT_REL,
    NativeCRStatusProjectionV1 as NativeCRStatusProjectionV1,
    _acquire_status_sync_writer_lock as _acquire_status_sync_writer_lock,
    _atomic_write_text as _atomic_write_text,
    _checkpoint_result_projection as _checkpoint_result_projection,
    _gate_checkpoint_projection as _gate_checkpoint_projection,
    _release_status_sync_writer_lock as _release_status_sync_writer_lock,
    _render_exact_section_rows as _render_exact_section_rows,
    _status_sync_writer_lock_path as _status_sync_writer_lock_path,
    _transaction_root as _transaction_root,
    load_ledger_events as load_ledger_events,
    render_status_body_projection as render_status_body_projection,
    summary_from_cr_file as summary_from_cr_file,
    write_evidence_index as write_evidence_index,
    write_summary as write_summary,
)
from meta_flow.workflow.cr_projection import (
    AggregateCompletionProjector as _ProjectionAggregateCompletionProjector,
)
from meta_flow.workflow.cr_projection import (
    append_ledger_event as _projection_append_ledger_event,
)
from meta_flow.workflow.cr_projection import (
    project_native_cr_status as _projection_project_native_cr_status,
)
from meta_flow.workflow.cr_records import (
    CR_SUMMARY_ROOT_REL as CR_SUMMARY_ROOT_REL,
    IMPACT_SPLIT_FIELDS as IMPACT_SPLIT_FIELDS,
    LEGACY_SOURCE_REL as LEGACY_SOURCE_REL,
    OPEN_DEPENDENCY_STATUSES as OPEN_DEPENDENCY_STATUSES,
    _capability_blockers as _capability_blockers,
    _categorized_legacy_impact as _categorized_legacy_impact,
    _effective_impact_fields as _effective_impact_fields,
    _first_section_summary as _first_section_summary,
    _git_fact as _git_fact,
    _impact_followup_candidates as _impact_followup_candidates,
    _impact_split_payload as _impact_split_payload,
    _load_json_object as _load_json_object,
    _normalized_capability_refs as _normalized_capability_refs,
    _process_root as _process_root,
    _record_required_evidence as _record_required_evidence,
    _rel as _rel,
    _resolve_capability_refs as _resolve_capability_refs,
    _resolve_runtime_ref as _resolve_runtime_ref,
    _section_summary as _section_summary,
    _uncategorized_legacy_impact as _uncategorized_legacy_impact,
    classify_cp1_review_profile as classify_cp1_review_profile,
    collect_archive_isolation_findings as collect_archive_isolation_findings,
    collect_governance_dependency_findings as collect_governance_dependency_findings,
    collect_scope_authz_findings as collect_scope_authz_findings,
    discover_formal_crs as discover_formal_crs,
    record_from_cr_file as record_from_cr_file,
)
from meta_flow.workflow.cr_status_sync import (
    STATUS_SYNC_AUTHORIZATION_FIELDS as STATUS_SYNC_AUTHORIZATION_FIELDS,
    STATUS_SYNC_AUTHORIZATION_KIND as STATUS_SYNC_AUTHORIZATION_KIND,
    STATUS_SYNC_AUTHORIZATION_SOURCE as STATUS_SYNC_AUTHORIZATION_SOURCE,
    STATUS_SYNC_OPERATION as STATUS_SYNC_OPERATION,
    StatusSyncAuthorization as StatusSyncAuthorization,
    StatusSyncPlan as StatusSyncPlan,
    StatusSyncTarget as StatusSyncTarget,
    _json_semantically_matches as _json_semantically_matches,
    _ledger_contains_status_sync_transition as _ledger_contains_status_sync_transition,
    _normalize_status_sync_effective_at as _normalize_status_sync_effective_at,
    _target as _target,
    apply_status_sync as apply_status_sync,
    load_status_sync_authorization as load_status_sync_authorization,
    plan_status_sync as plan_status_sync,
    validate_status_sync_authorization as validate_status_sync_authorization,
)
from meta_flow.workflow.cr_status_sync import sync_cr_status as _status_sync_cr_status
from meta_flow.workflow.cr_status_transaction import (
    _claim_status_sync_authorization as _claim_status_sync_authorization,
    _current_target_digest as _current_target_digest,
    _status_sync_claim_path as _status_sync_claim_path,
    _status_sync_facts as _status_sync_facts,
    inspect_status_sync_transactions as inspect_status_sync_transactions,
)
from meta_flow.workflow.cr_status_transaction import (
    recover_status_sync_transaction as _recover_status_sync_transaction,
)
from meta_flow.workflow.cr_termination import (
    TERMINATION_AUTHORIZATION_KIND as TERMINATION_AUTHORIZATION_KIND,
    TERMINATION_AUTHORIZATION_SOURCE as TERMINATION_AUTHORIZATION_SOURCE,
    TERMINATION_OPERATION as TERMINATION_OPERATION,
    TerminationAuthorization as TerminationAuthorization,
    TerminationPlan as TerminationPlan,
    apply_cr_termination as apply_cr_termination,
    load_termination_authorization as load_termination_authorization,
    plan_cr_termination as plan_cr_termination,
)


class AggregateCompletionProjector(_ProjectionAggregateCompletionProjector):
    """在每次投影时解析 facade 当前的可替换协作者。"""

    def __init__(self, *, project_root: Path, expected_state_updated_at: str) -> None:
        super().__init__(
            project_root=project_root,
            expected_state_updated_at=expected_state_updated_at,
        )

    def project_aggregate(self, *, result: Any, receipt: Any) -> dict[str, Any]:
        self._append_ledger_event_fn = append_ledger_event
        self._rel_fn = _rel
        return super().project_aggregate(result=result, receipt=receipt)


def append_ledger_event(project_root: Path, event: dict[str, Any]) -> Path:
    return _projection_append_ledger_event(
        project_root,
        event,
        resolve_runtime_ref_fn=_resolve_runtime_ref,
    )


def project_native_cr_status(
    project_root: Path,
    *,
    cr_id: str,
    excluded_legacy_paths: frozenset[Path] | None = None,
    partition_report: Any | None = None,
) -> NativeCRStatusProjectionV1:
    return _projection_project_native_cr_status(
        project_root,
        cr_id=cr_id,
        resolve_runtime_ref=_resolve_runtime_ref,
        rel=_rel,
        load_index=lambda root: load_index(
            root,
            resolve_runtime_ref_fn=_resolve_runtime_ref,
        ),
        excluded_legacy_paths=excluded_legacy_paths,
        partition_report=partition_report,
    )


def close_cr(
    project_root: Path,
    cr_id: str,
    *,
    readiness: str,
    work_id: str,
    effective_at: str,
    expected_process_oid: str,
    expected_plan_digest: str,
    authorization: Any | None,
    _return_apply_result: bool = False,
) -> dict[str, Path]:
    captured: dict[str, Any] = {}

    def apply_and_capture(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = apply_status_sync(*args, **kwargs)
        captured["result"] = result
        return result

    paths = _index_close_cr(
        project_root,
        cr_id,
        readiness=readiness,
        work_id=work_id,
        effective_at=effective_at,
        expected_process_oid=expected_process_oid,
        expected_plan_digest=expected_plan_digest,
        authorization=authorization,
        plan_status_sync=plan_status_sync,
        apply_status_sync=apply_and_capture,
        append_ledger_event=append_ledger_event,
        resolve_runtime_ref=_resolve_runtime_ref,
        rel=_rel,
        current_state_updater=current.update_current_state,
        discover_formal_crs_fn=discover_formal_crs,
    )
    return captured["result"] if _return_apply_result else paths


def sync_cr_status(
    project_root: Path,
    cr_id: str,
    *,
    status: str = "",
    readiness: str = "",
    gate_status: str = "",
    work_id: str = "",
    historical_migration: bool = False,
    historical_gate_status: str = "",
    historical_lifecycle_status: str = "",
    expected_process_oid: str = "",
    effective_at: str = "",
    expected_plan_digest: str = "",
    authorization: StatusSyncAuthorization | None = None,
    _plan: Any | None = None,
    _return_apply_result: bool = False,
) -> dict[str, Path]:
    if _return_apply_result:
        if _plan is None:
            raise ValueError("internal status-sync dispatch requires a precomputed plan")
        return apply_status_sync(
            project_root,
            _plan,
            authorization=authorization,
            expected_plan_digest=expected_plan_digest,
        )
    return _status_sync_cr_status(
        project_root,
        cr_id,
        status=status,
        readiness=readiness,
        gate_status=gate_status,
        work_id=work_id,
        historical_migration=historical_migration,
        historical_gate_status=historical_gate_status,
        historical_lifecycle_status=historical_lifecycle_status,
        expected_process_oid=expected_process_oid,
        effective_at=effective_at,
        expected_plan_digest=expected_plan_digest,
        authorization=authorization,
    )


close_cr.__signature__ = inspect.signature(close_cr).replace(
    parameters=tuple(
        parameter
        for name, parameter in inspect.signature(close_cr).parameters.items()
        if name != "_return_apply_result"
    )
)
sync_cr_status.__signature__ = inspect.signature(sync_cr_status).replace(
    parameters=tuple(
        parameter
        for name, parameter in inspect.signature(sync_cr_status).parameters.items()
        if name not in {"_plan", "_return_apply_result"}
    )
)


recover_status_sync_transaction = partial(
    _recover_status_sync_transaction,
    canonical_digest=_canonical_digest,
    dirty_path_digest=_dirty_path_digest,
)
recover_status_sync_transaction.__signature__ = inspect.signature(
    _recover_status_sync_transaction
).replace(
    parameters=tuple(
        parameter
        for name, parameter in inspect.signature(
            _recover_status_sync_transaction
        ).parameters.items()
        if name not in {"canonical_digest", "dirty_path_digest"}
    )
)


def main(argv: list[str] | None = None) -> int:
    return _cr_cli.main(
        argv,
        dispatch_dependencies={
            "AggregateCompletionProjector": AggregateCompletionProjector,
            "apply_bootstrap_cr": apply_bootstrap_cr,
            "apply_cr_termination": apply_cr_termination,
            "apply_status_sync": apply_status_sync,
            "build_impact_report": build_impact_report,
            "build_cr_lifecycle_check_report": build_cr_lifecycle_check_report,
            "close_cr": close_cr,
            "collect_check_errors": collect_check_errors,
            "collect_check_warnings": collect_check_warnings,
            "conflict_report": conflict_report,
            "discover_formal_crs": discover_formal_crs,
            "inspect_bootstrap_transactions": inspect_bootstrap_transactions,
            "inspect_status_sync_transactions": inspect_status_sync_transactions,
            "load_status_sync_authorization": load_status_sync_authorization,
            "load_termination_authorization": load_termination_authorization,
            "plan_cr_termination": plan_cr_termination,
            "plan_bootstrap_cr": plan_bootstrap_cr,
            "plan_index": plan_index,
            "plan_status_sync": plan_status_sync,
            "proposed_conflict_report": proposed_conflict_report,
            "recover_status_sync_transaction": recover_status_sync_transaction,
            "recover_bootstrap_transaction": recover_bootstrap_transaction,
            "rel": _rel,
            "render_cr_brief": render_cr_brief,
            "render_goal_brief": render_goal_brief,
            "summary_from_cr_file": summary_from_cr_file,
            "sync_cr_status": sync_cr_status,
            "write_impact_report": write_impact_report,
            "write_index": write_index,
            "write_summary": write_summary,
        },
    )


__all__ = (
    "AggregateCompletionProjector",
    "BootstrapCRPlanV1",
    "CR_INDEX_REL",
    "CR_SUMMARY_ROOT_REL",
    "STATUS_SYNC_AUTHORIZATION_KIND",
    "STATUS_SYNC_AUTHORIZATION_SOURCE",
    "STATUS_SYNC_OPERATION",
    "StatusSyncAuthorization",
    "StatusSyncPlan",
    "TERMINATION_AUTHORIZATION_KIND",
    "TERMINATION_AUTHORIZATION_SOURCE",
    "TERMINATION_OPERATION",
    "TerminationAuthorization",
    "TerminationPlan",
    "append_ledger_event",
    "apply_bootstrap_cr",
    "apply_cr_termination",
    "apply_status_sync",
    "build_impact_report",
    "build_cr_lifecycle_check_report",
    "build_index",
    "collect_check_errors",
    "close_cr",
    "discover_formal_crs",
    "inspect_bootstrap_transactions",
    "inspect_status_sync_transactions",
    "load_ledger_events",
    "load_status_sync_authorization",
    "main",
    "parse_frontmatter",
    "plan_bootstrap_cr",
    "plan_cr_termination",
    "plan_index",
    "plan_status_sync",
    "project_native_cr_status",
    "recover_bootstrap_transaction",
    "recover_status_sync_transaction",
    "render_cr_brief",
    "render_goal_brief",
    "summary_from_cr_file",
    "sync_cr_status",
    "validate_index_payload",
    "write_index",
    "write_summary",
)


_PRIVATE_COMPATIBILITY_AVAILABILITY = {
    "_acquire_status_sync_writer_lock": "private-compat-re-export",
    "_atomic_write_text": "private-compat-re-export",
    "_release_status_sync_writer_lock": "private-compat-re-export",
    "_status_sync_writer_lock_path": "private-compat-re-export",
    "_update_current_active_change": "private-compat-re-export",
    "_resolve_runtime_ref": "injected-call-time-path-helper",
    "_rel": "injected-call-time-path-helper",
    "current": "external-private-alias",
}


_CALL_TIME_COMPATIBILITY_SURFACES = frozenset(
    {"close_cr", "sync_cr_status", "append_ledger_event", "_resolve_runtime_ref", "_rel"}
)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
