"""CR termination typed plan, authorization, apply and recovery owner."""
# ruff: noqa: I001

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from meta_flow.checks import cr_tracking
from meta_flow.project.governance import load_phase
from meta_flow.project.model import load_project
from meta_flow.project.process_route import require_process_route
from meta_flow.project.scale import dump_yaml
from meta_flow.state import current, event_ledger
from meta_flow.work.lifecycle import transition_work
from meta_flow.work.model import load_work
from meta_flow.work.scope import check_scope
from meta_flow.workflow.cr_index import CR_INDEX_REL, _canonical_digest, _dirty_path_digest
from meta_flow.workflow.cr_index import build_index, validate_index_payload
from meta_flow.workflow.cr_model import CR_ID_RE, DIGEST_RE, FINISHED_STATUSES, OID_RE
from meta_flow.workflow.cr_model import SAFE_AUTHORIZATION_ID_RE, normalize_cr_type, now_utc
from meta_flow.workflow.cr_model import parse_frontmatter, render_frontmatter_fields
from meta_flow.workflow.cr_projection import CR_LEDGER_REL, STATE_CURRENT_REL
from meta_flow.workflow.cr_projection import _acquire_status_sync_writer_lock, _atomic_write_text
from meta_flow.workflow.cr_projection import _release_status_sync_writer_lock
from meta_flow.workflow.cr_projection import _render_exact_section_rows, _transaction_root
from meta_flow.workflow.cr_projection import load_ledger_events, summary_from_cr_file
from meta_flow.workflow.cr_records import CR_SUMMARY_ROOT_REL, _git_fact, _load_json_object
from meta_flow.workflow.cr_records import _rel, _resolve_runtime_ref, discover_formal_crs

TERMINATION_TUPLES = {
    "cancelled": {
        "lifecycle_status": "cancelled",
        "readiness_status": "n/a",
        "gate_status": "closed",
    },
    "superseded": {
        "lifecycle_status": "superseded",
        "readiness_status": "n/a",
        "gate_status": "closed",
    },
}

TERMINATION_AUTHORIZATION_FIELDS = {
    "schema_version",
    "authorization_id",
    "authorization_source",
    "authorization_kind",
    "operation",
    "cr_id",
    "work_id",
    "termination_reason",
    "terminal_tuple",
    "expected_release_oid",
    "expected_process_oid",
    "scope_digest",
    "plan_digest",
    "expires_at",
    "single_use",
}

TERMINATION_AUTHORIZATION_SOURCE = "typed-user-confirmation"

TERMINATION_AUTHORIZATION_KIND = "cr-termination"

TERMINATION_OPERATION = "cr.terminate"

@dataclass(frozen=True)
class TerminationAuthorization:
    schema_version: int
    authorization_id: str
    authorization_source: str
    authorization_kind: str
    operation: str
    cr_id: str
    work_id: str
    termination_reason: str
    terminal_tuple: dict[str, str]
    expected_release_oid: str
    expected_process_oid: str
    scope_digest: str
    plan_digest: str
    expires_at: str
    single_use: bool = True

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> TerminationAuthorization:
        if set(payload) != TERMINATION_AUTHORIZATION_FIELDS:
            missing = sorted(TERMINATION_AUTHORIZATION_FIELDS - set(payload))
            extra = sorted(set(payload) - TERMINATION_AUTHORIZATION_FIELDS)
            raise ValueError(
                f"termination authorization fields mismatch: missing={missing}, extra={extra}"
            )
        return cls(**payload)

@dataclass(frozen=True)
class TerminationTarget:
    order: int
    ref: str
    path: Path
    truth_or_derived: str
    before: str | None
    after: str

    @property
    def before_digest(self) -> str:
        return _canonical_digest(self.before if self.before is not None else "")

    @property
    def after_digest(self) -> str:
        return _canonical_digest(self.after)

    def as_dict(self) -> dict[str, Any]:
        return {
            "order": self.order,
            "ref": self.ref,
            "truth_or_derived": self.truth_or_derived,
            "before_exists": self.before is not None,
            "before_digest": self.before_digest,
            "after_digest": self.after_digest,
        }

@dataclass(frozen=True)
class TerminationPlan:
    decision: str
    cr_id: str
    work_id: str
    termination_reason: str
    terminal_tuple: dict[str, str]
    expected_facts: dict[str, str]
    binding: dict[str, str]
    scope_digest: str
    targets: tuple[TerminationTarget, ...]
    reason: str = ""

    def _digest_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "operation": TERMINATION_OPERATION,
            "decision": self.decision,
            "cr_id": self.cr_id,
            "work_id": self.work_id,
            "termination_reason": self.termination_reason,
            "terminal_tuple": self.terminal_tuple,
            "expected_facts": self.expected_facts,
            "binding": self.binding,
            "scope_digest": self.scope_digest,
            "targets": [target.as_dict() for target in self.targets],
            "reason": self.reason,
        }

    @property
    def plan_digest(self) -> str:
        return _canonical_digest(self._digest_payload())

    def as_dict(self) -> dict[str, Any]:
        target_refs = [target.ref for target in self.targets]
        return {
            **self._digest_payload(),
            "expected_oids": {
                "producer_release": self.expected_facts.get("producer_release_oid", ""),
                "target_release": self.expected_facts.get("target_release_oid", ""),
                "process": self.expected_facts.get("process_head_oid", ""),
            },
            "mutation_count": 0,
            "planned_mutation_count": len(self.targets),
            "mutation_allowlist": target_refs,
            "exact_changed_leaf_paths": target_refs,
            "transaction_order": [
                {
                    "order": target.order,
                    "ref": target.ref,
                    "truth_or_derived": target.truth_or_derived,
                }
                for target in self.targets
            ],
            "rollback": {
                "strategy": "reverse-order-exact-preimage-restore",
                "order": list(reversed(target_refs)),
                "partial_evidence": "private://cr-termination/transactions/<transaction-id>/manifest.json",
            },
            "apply_private_effects": [
                "single-use authorization claim",
                "recoverable transaction evidence",
            ],
            "plan_digest": self.plan_digest,
        }

def _portable_termination_error(
    exc: Exception,
    *,
    project_root: Path,
    process_root: Path | None = None,
) -> str:
    text = str(exc)
    replacements = [(str(project_root.resolve()), "<release-root>")]
    if process_root is not None:
        replacements.append((str(process_root.resolve()), "<process-root>"))
    for source, replacement in replacements:
        text = text.replace(source, replacement)
    return text

def _termination_facts(
    project_root: Path,
    *,
    work_id: str,
) -> tuple[dict[str, str], dict[str, str], str, Path]:
    release_root = project_root.resolve()
    route = require_process_route(release_root)
    process_root = route.process_root
    producer_root = Path(__file__).resolve().parents[2]
    facts = {
        "producer_release_oid": _git_fact(producer_root, "rev-parse", "--verify", "HEAD").lower(),
        "target_release_oid": _git_fact(release_root, "rev-parse", "--verify", "HEAD").lower(),
        "process_head_oid": _git_fact(process_root, "rev-parse", "--verify", "HEAD").lower(),
        "process_git_common_dir_identity": _canonical_digest(
            _git_fact(process_root, "rev-parse", "--git-common-dir") or "non-git-fixture"
        ),
        "process_dirty_path_digest": _dirty_path_digest(process_root),
    }
    for key in ("producer_release_oid", "target_release_oid", "process_head_oid"):
        if not OID_RE.fullmatch(facts[key]):
            raise ValueError(f"{key} is not one exact Git OID")
    work = load_work(process_root, work_id)
    binding = {
        "status": "healthy",
        "project_id": route.project_id,
        "layout_version": route.layout_version,
        "route_mode": route.route_mode,
    }
    return facts, binding, work.scope.digest, process_root

def _termination_target(
    project_root: Path,
    order: int,
    path: Path,
    after: str,
    truth_or_derived: str,
) -> TerminationTarget | None:
    before = path.read_text(encoding="utf-8") if path.is_file() else None
    if before == after:
        return None
    return TerminationTarget(
        order=order,
        ref=_rel(project_root, path),
        path=path,
        truth_or_derived=truth_or_derived,
        before=before,
        after=after,
    )

def _render_termination_body_projection(
    text: str,
    *,
    terminal_tuple: dict[str, str],
) -> str:
    rendered = _render_exact_section_rows(
        text,
        "CR 类型与门禁策略",
        {
            "生命周期状态": terminal_tuple["lifecycle_status"],
            "就绪状态": terminal_tuple["readiness_status"],
            "门禁状态": terminal_tuple["gate_status"],
        },
    )
    return _render_exact_section_rows(
        rendered,
        "Checkpoint Index",
        {"CP8": "not-applicable"},
    )

def _termination_projection_is_complete(
    project_root: Path,
    *,
    cr_id: str,
    work_id: str,
    terminal_tuple: dict[str, str],
    process_root: Path,
) -> tuple[bool, str]:
    work = load_work(process_root, work_id)
    if work.status not in {"cancelled", "archived"}:
        return False, f"Work remains non-terminal: {work.status}"
    project = load_project(process_root)
    if work.work_ref in project.active_work_refs:
        return False, "Project still references the terminated Work"
    if work.phase_ref:
        phase = load_phase(process_root, work.phase_ref)
        if work.work_ref in phase.work_refs:
            return False, "Phase still references the terminated Work"
    summary_path = _resolve_runtime_ref(
        project_root, (CR_SUMMARY_ROOT_REL / f"{cr_id}.summary.json").as_posix()
    )
    if not summary_path.is_file():
        return False, "termination summary is missing"
    summary = _load_json_object(summary_path, subject="termination summary")
    if (
        str(summary.get("status") or "") != terminal_tuple["lifecycle_status"]
        or str(summary.get("readiness") or "").lower() != terminal_tuple["readiness_status"]
        or str(summary.get("gate_status") or "").lower() != terminal_tuple["gate_status"]
    ):
        return False, "termination summary tuple is inconsistent"
    index_path = _resolve_runtime_ref(project_root, CR_INDEX_REL.as_posix())
    if not index_path.is_file():
        return False, "CR-INDEX is missing"
    index = _load_json_object(index_path, subject="CR-INDEX")
    index_errors = validate_index_payload(index)
    if index_errors:
        return False, "; ".join(index_errors)
    expected_index = build_index(project_root)
    if index.get("semantic_digest") != expected_index.get("semantic_digest"):
        return False, "CR-INDEX differs from formal truth"
    ledger_path = _resolve_runtime_ref(project_root, CR_LEDGER_REL.as_posix())
    if not ledger_path.is_file():
        return False, "CR ledger is missing"
    matching_event = any(
        str(event.get("event_type") or "") == "cr_termination"
        and str(event.get("id") or "") == cr_id
        and str(event.get("status") or "") == terminal_tuple["lifecycle_status"]
        for event in load_ledger_events(project_root)
    )
    if not matching_event:
        return False, "CR termination ledger event is missing"
    state_path = _resolve_runtime_ref(project_root, STATE_CURRENT_REL.as_posix())
    if state_path.is_file():
        state = _load_json_object(state_path, subject="STATE.current.json")
        if state.get("active_change") == cr_id:
            return False, "STATE.current.json still references the terminated CR"
    return True, ""

def _blocked_termination_plan(
    *,
    cr_id: str,
    work_id: str,
    termination_reason: str,
    terminal_tuple: dict[str, str],
    expected_facts: dict[str, str],
    binding: dict[str, str],
    scope_digest: str,
    reason: str,
) -> TerminationPlan:
    return TerminationPlan(
        decision="BLOCKED",
        cr_id=cr_id,
        work_id=work_id,
        termination_reason=termination_reason,
        terminal_tuple=terminal_tuple,
        expected_facts=expected_facts,
        binding=binding,
        scope_digest=scope_digest,
        targets=(),
        reason=reason,
    )

def plan_cr_termination(
    project_root: Path,
    cr_id: str,
    *,
    work_id: str,
    termination_status: str,
    termination_reason: str,
    expected_process_oid: str = "",
) -> TerminationPlan:
    """Build a deterministic, zero-mutation CR termination transaction."""

    release_root = project_root.resolve()
    terminal_tuple = dict(TERMINATION_TUPLES.get(termination_status) or {})
    facts: dict[str, str] = {}
    binding: dict[str, str] = {}
    scope_digest = ""
    process_root: Path | None = None
    if not CR_ID_RE.fullmatch(cr_id):
        return _blocked_termination_plan(
            cr_id=cr_id,
            work_id=work_id,
            termination_reason=termination_reason,
            terminal_tuple=terminal_tuple,
            expected_facts=facts,
            binding=binding,
            scope_digest=scope_digest,
            reason="CR id must use CR-xxx naming",
        )
    if not terminal_tuple:
        return _blocked_termination_plan(
            cr_id=cr_id,
            work_id=work_id,
            termination_reason=termination_reason,
            terminal_tuple={},
            expected_facts=facts,
            binding=binding,
            scope_digest=scope_digest,
            reason="termination status must be cancelled or superseded",
        )
    normalized_reason = termination_reason.strip()
    if not normalized_reason or len(normalized_reason) > 1000:
        return _blocked_termination_plan(
            cr_id=cr_id,
            work_id=work_id,
            termination_reason=normalized_reason,
            terminal_tuple=terminal_tuple,
            expected_facts=facts,
            binding=binding,
            scope_digest=scope_digest,
            reason="termination reason must contain 1-1000 characters",
        )
    if not work_id:
        return _blocked_termination_plan(
            cr_id=cr_id,
            work_id=work_id,
            termination_reason=normalized_reason,
            terminal_tuple=terminal_tuple,
            expected_facts=facts,
            binding=binding,
            scope_digest=scope_digest,
            reason="work_id is required",
        )
    try:
        facts, binding, scope_digest, process_root = _termination_facts(
            release_root, work_id=work_id
        )
        if expected_process_oid and expected_process_oid != facts["process_head_oid"]:
            raise ValueError("process HEAD differs from expected OID")
        crs = discover_formal_crs(release_root)
        if cr_id not in crs:
            raise ValueError(f"formal CR is missing: {cr_id}")
        cr_path = crs[cr_id]
        cr_before = cr_path.read_text(encoding="utf-8")
        fields = parse_frontmatter(cr_before)
        source_follow_up_id = str(fields.get("source_follow_up_id") or "")
        if source_follow_up_id and source_follow_up_id != work_id:
            raise ValueError("CR source_follow_up_id does not match work_id")
        current_tuple = {
            "lifecycle_status": cr_tracking.normalize_lifecycle_status(
                fields.get("lifecycle_status") or fields.get("status") or ""
            ),
            "readiness_status": cr_tracking.normalize_readiness_status(
                fields.get("readiness_status") or ""
            ),
            "gate_status": cr_tracking.normalize_gate_status(fields.get("gate_status") or ""),
        }
        current_values = tuple(current_tuple.values())
        target_values = tuple(terminal_tuple.values())
        if current_values == target_values:
            complete, incomplete_reason = _termination_projection_is_complete(
                release_root,
                cr_id=cr_id,
                work_id=work_id,
                terminal_tuple=terminal_tuple,
                process_root=process_root,
            )
            if not complete:
                raise ValueError("terminal CR has incomplete projection: " + incomplete_reason)
            return TerminationPlan(
                decision="NO_CHANGE",
                cr_id=cr_id,
                work_id=work_id,
                termination_reason=normalized_reason,
                terminal_tuple=terminal_tuple,
                expected_facts=facts,
                binding=binding,
                scope_digest=scope_digest,
                targets=(),
            )
        if current_tuple["lifecycle_status"] in FINISHED_STATUSES:
            raise ValueError("a terminal CR cannot be changed to a different terminal state")
        source_errors = cr_tracking.validate_native_status_tuple(*current_values)
        target_errors = cr_tracking.validate_native_status_tuple(*target_values)
        if source_errors or target_errors:
            raise ValueError("; ".join([*source_errors, *target_errors]))

        work = load_work(process_root, work_id)
        terminated_work = transition_work(work, "cancelled")
        project = load_project(process_root)
        if work.work_ref not in project.active_work_refs:
            raise ValueError("Project active_work_refs does not contain the target Work")
        terminated_project = replace(
            project,
            active_work_refs=tuple(ref for ref in project.active_work_refs if ref != work.work_ref),
        )
        phase = load_phase(process_root, work.phase_ref) if work.phase_ref else None
        if phase is not None and work.work_ref not in phase.work_refs:
            raise ValueError("Phase work_refs does not contain the target Work")
        terminated_phase = (
            replace(
                phase,
                work_refs=tuple(ref for ref in phase.work_refs if ref != work.work_ref),
            )
            if phase is not None
            else None
        )

        index_path = _resolve_runtime_ref(release_root, CR_INDEX_REL.as_posix())
        existing_index: dict[str, Any] | None = None
        if index_path.is_file():
            existing_index = _load_json_object(index_path, subject="CR-INDEX")
            index_errors = validate_index_payload(existing_index)
            if index_errors:
                raise ValueError("; ".join(index_errors))
            formal_truth_index = build_index(release_root)
            if existing_index.get("semantic_digest") != formal_truth_index.get("semantic_digest"):
                raise ValueError("CR-INDEX differs from current formal truth")

        cr_after = render_frontmatter_fields(
            cr_before,
            {
                "lifecycle_status": terminal_tuple["lifecycle_status"],
                "readiness_status": terminal_tuple["readiness_status"],
                "gate_status": terminal_tuple["gate_status"],
                "status": terminal_tuple["lifecycle_status"],
            },
        )
        cr_after = _render_termination_body_projection(cr_after, terminal_tuple=terminal_tuple)
        summary_path = _resolve_runtime_ref(
            release_root,
            (CR_SUMMARY_ROOT_REL / f"{cr_id}.summary.json").as_posix(),
        )
        if summary_path.is_file():
            summary = _load_json_object(summary_path, subject="CR summary")
            if str(summary.get("id") or "") != cr_id:
                raise ValueError("CR summary identity mismatch")
            if str(summary.get("full_ref") or "") != _rel(release_root, cr_path):
                raise ValueError("CR summary full_ref mismatch")
        else:
            summary = summary_from_cr_file(release_root, cr_path)
            summary.pop("updated_at", None)
        summary.update(
            {
                "status": terminal_tuple["lifecycle_status"],
                "readiness": terminal_tuple["readiness_status"],
                "gate_status": terminal_tuple["gate_status"],
                "decision": terminal_tuple["lifecycle_status"],
                "termination_reason": normalized_reason,
                "terminal_tuple": terminal_tuple,
            }
        )
        summary_after = (
            json.dumps(
                summary,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
        ledger_path = _resolve_runtime_ref(release_root, CR_LEDGER_REL.as_posix())
        ledger_event = {
            "event_id": _canonical_digest(
                {
                    "operation": TERMINATION_OPERATION,
                    "id": cr_id,
                    "work_id": work_id,
                    "termination_reason": normalized_reason,
                    "terminal_tuple": terminal_tuple,
                    "expected_facts": facts,
                    "scope_digest": scope_digest,
                }
            ),
            "event": "terminated",
            "event_type": "cr_termination",
            "id": cr_id,
            "work_id": work_id,
            "cr_type": normalize_cr_type(
                fields.get("cr_type") or fields.get("cr_kind") or "feature"
            ),
            "status": terminal_tuple["lifecycle_status"],
            "readiness": terminal_tuple["readiness_status"],
            "gate_status": terminal_tuple["gate_status"],
            "summary_ref": _rel(release_root, summary_path),
            "full_ref": _rel(release_root, cr_path),
            "termination_reason": normalized_reason,
            "terminal_tuple": terminal_tuple,
        }
        ledger_after = event_ledger.render_appended_event(ledger_path, ledger_event)
        projected_index = build_index(
            release_root,
            record_overrides={
                cr_id: {
                    "lifecycle_status": terminal_tuple["lifecycle_status"],
                    "readiness_status": terminal_tuple["readiness_status"],
                    "gate_status": terminal_tuple["gate_status"],
                    "status": terminal_tuple["lifecycle_status"],
                }
            },
        )
        projected_index["generated_at"] = (
            str(existing_index.get("generated_at") or "")
            if existing_index is not None
            else "1970-01-01T00:00:00+00:00"
        )
        index_after = (
            json.dumps(
                projected_index,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )

        candidate_targets: list[TerminationTarget | None] = [
            _termination_target(release_root, 10, cr_path, cr_after, "truth"),
            _termination_target(
                release_root,
                20,
                process_root / work.work_ref,
                dump_yaml(terminated_work.as_dict()) + "\n",
                "truth",
            ),
            _termination_target(
                release_root,
                30,
                process_root / "PROJECT.yaml",
                dump_yaml(terminated_project.as_dict()) + "\n",
                "truth",
            ),
        ]
        if terminated_phase is not None:
            candidate_targets.append(
                _termination_target(
                    release_root,
                    40,
                    process_root / terminated_phase.phase_ref,
                    dump_yaml(terminated_phase.as_dict()) + "\n",
                    "truth",
                )
            )
        state_path = _resolve_runtime_ref(release_root, STATE_CURRENT_REL.as_posix())
        if state_path.is_file():
            state = _load_json_object(state_path, subject="STATE.current.json")
            if state.get("active_change") == cr_id:
                state_after = current.render_current_state_candidate(
                    current.build_current_state_candidate(
                        release_root,
                        {
                            "active_change": None,
                            "active_context_ref": None,
                            "pending_gate": None,
                            "pending_checklist_path": None,
                            "next_action": {
                                "type": "done",
                                "text": (
                                    f"{cr_id} terminated as {terminal_tuple['lifecycle_status']}."
                                ),
                                "stop_reason": "no_remaining_route",
                            },
                        },
                        actor="meta_flow.workflow.cr_lifecycle",
                        reason=f"terminate {cr_id}",
                    )
                )
                candidate_targets.append(
                    _termination_target(release_root, 45, state_path, state_after, "truth")
                )
        candidate_targets.extend(
            [
                _termination_target(release_root, 50, summary_path, summary_after, "derived"),
                _termination_target(release_root, 60, ledger_path, ledger_after, "derived"),
                _termination_target(release_root, 90, index_path, index_after, "derived"),
            ]
        )
        targets = tuple(
            sorted(
                (target for target in candidate_targets if target is not None),
                key=lambda target: target.order,
            )
        )
        denied = [
            target.ref
            for target in targets
            if not check_scope(
                work.scope,
                "write",
                target.ref.removeprefix("process/"),
            ).allowed
        ]
        if denied:
            raise ValueError("termination targets outside Work write scope: " + ", ".join(denied))
        return TerminationPlan(
            decision="READY",
            cr_id=cr_id,
            work_id=work_id,
            termination_reason=normalized_reason,
            terminal_tuple=terminal_tuple,
            expected_facts=facts,
            binding=binding,
            scope_digest=scope_digest,
            targets=targets,
        )
    except Exception as exc:
        return _blocked_termination_plan(
            cr_id=cr_id,
            work_id=work_id,
            termination_reason=normalized_reason,
            terminal_tuple=terminal_tuple,
            expected_facts=facts,
            binding=binding,
            scope_digest=scope_digest,
            reason=_portable_termination_error(
                exc,
                project_root=release_root,
            process_root=process_root,
        ),
    )

def load_termination_authorization(path: Path) -> TerminationAuthorization:
    payload = _load_json_object(path, subject="termination authorization")
    return TerminationAuthorization.from_dict(payload)

def validate_termination_authorization(
    plan: TerminationPlan,
    authorization: TerminationAuthorization,
) -> None:
    if plan.decision != "READY":
        raise ValueError("termination authorization requires one READY plan")
    if authorization.schema_version != 1:
        raise ValueError("termination authorization schema_version must be 1")
    if not SAFE_AUTHORIZATION_ID_RE.fullmatch(authorization.authorization_id):
        raise ValueError("termination authorization_id is invalid")
    if authorization.authorization_source != TERMINATION_AUTHORIZATION_SOURCE:
        raise ValueError("termination authorization_source must be typed-user-confirmation")
    if authorization.authorization_kind != TERMINATION_AUTHORIZATION_KIND:
        raise ValueError("termination authorization_kind must be cr-termination")
    if authorization.operation != TERMINATION_OPERATION:
        raise ValueError("termination authorization operation mismatch")
    if authorization.single_use is not True:
        raise ValueError("termination authorization must be single-use")
    expected = (
        plan.cr_id,
        plan.work_id,
        plan.termination_reason,
        plan.terminal_tuple,
        plan.expected_facts.get("target_release_oid", ""),
        plan.expected_facts.get("process_head_oid", ""),
        plan.scope_digest,
        plan.plan_digest,
    )
    actual = (
        authorization.cr_id,
        authorization.work_id,
        authorization.termination_reason,
        authorization.terminal_tuple,
        authorization.expected_release_oid,
        authorization.expected_process_oid,
        authorization.scope_digest,
        authorization.plan_digest,
    )
    if actual != expected:
        raise ValueError(
            "termination authorization does not match CR/Work/reason/tuple/OIDs/scope/plan"
        )
    if not OID_RE.fullmatch(authorization.expected_release_oid):
        raise ValueError("termination expected_release_oid is invalid")
    if not OID_RE.fullmatch(authorization.expected_process_oid):
        raise ValueError("termination expected_process_oid is invalid")
    if not DIGEST_RE.fullmatch(authorization.scope_digest):
        raise ValueError("termination scope_digest is invalid")
    if not DIGEST_RE.fullmatch(authorization.plan_digest):
        raise ValueError("termination plan_digest is invalid")
    try:
        expires_at = datetime.fromisoformat(authorization.expires_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("termination authorization expires_at is invalid") from exc
    if expires_at.tzinfo is None:
        raise ValueError("termination authorization expires_at must include timezone")
    if expires_at.astimezone(UTC) <= datetime.now(UTC):
        raise ValueError("termination authorization is expired")

def _termination_private_root(project_root: Path) -> Path:
    return _transaction_root(project_root).parent / "cr-termination"

def _termination_claim_path(
    project_root: Path,
    authorization_id: str,
) -> Path:
    if not SAFE_AUTHORIZATION_ID_RE.fullmatch(authorization_id):
        raise ValueError("termination authorization_id is invalid")
    return _termination_private_root(project_root) / "authorizations" / f"{authorization_id}.json"

def _claim_termination_authorization(
    project_root: Path,
    plan: TerminationPlan,
    authorization: TerminationAuthorization,
) -> Path:
    validate_termination_authorization(plan, authorization)
    path = _termination_claim_path(project_root, authorization.authorization_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "authorization_id": authorization.authorization_id,
        "operation": authorization.operation,
        "cr_id": authorization.cr_id,
        "work_id": authorization.work_id,
        "plan_digest": authorization.plan_digest,
        "expected_release_oid": authorization.expected_release_oid,
        "expected_process_oid": authorization.expected_process_oid,
        "scope_digest": authorization.scope_digest,
        "claimed_at": now_utc(),
    }
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            )
    except FileExistsError as exc:
        raise ValueError("termination authorization was already consumed") from exc
    return path

def _termination_current_digest(target: TerminationTarget) -> str:
    if not target.path.is_file():
        return _canonical_digest("")
    return _canonical_digest(target.path.read_text(encoding="utf-8"))

def apply_cr_termination(
    project_root: Path,
    plan: TerminationPlan,
    *,
    authorization: TerminationAuthorization | None,
    expected_plan_digest: str,
    _fail_after_replace: int | None = None,
    _fail_recovery: bool = False,
    _fault: str = "",
) -> dict[str, Any]:
    """Apply one typed, exact-preimage termination transaction."""

    release_root = project_root.resolve()
    if plan.decision == "NO_CHANGE":
        return {
            "status": "NO_CHANGE",
            "plan_digest": plan.plan_digest,
            "mutation_count": 0,
            "path_refs": [],
        }
    if plan.decision != "READY":
        return {
            "status": "BLOCKED",
            "reason": plan.reason,
            "mutation_count": 0,
        }
    if not expected_plan_digest or expected_plan_digest != plan.plan_digest:
        return {
            "status": "BLOCKED",
            "reason": "expected plan digest does not match the current plan",
            "mutation_count": 0,
        }
    if authorization is None:
        return {
            "status": "BLOCKED",
            "reason": "termination apply requires typed authorization",
            "mutation_count": 0,
        }
    fresh = plan_cr_termination(
        release_root,
        plan.cr_id,
        work_id=plan.work_id,
        termination_status=plan.terminal_tuple["lifecycle_status"],
        termination_reason=plan.termination_reason,
        expected_process_oid=plan.expected_facts["process_head_oid"],
    )
    if fresh.decision != "READY" or fresh.plan_digest != plan.plan_digest:
        return {
            "status": "BLOCKED",
            "reason": "termination plan drifted before apply",
            "mutation_count": 0,
        }
    drifted = [
        target.ref
        for target in plan.targets
        if _termination_current_digest(target) != target.before_digest
    ]
    if drifted:
        return {
            "status": "BLOCKED",
            "reason": "termination target preimage drift: " + ", ".join(drifted),
            "mutation_count": 0,
        }
    try:
        validate_termination_authorization(plan, authorization)
    except ValueError as exc:
        return {
            "status": "BLOCKED",
            "reason": str(exc),
            "mutation_count": 0,
        }
    transaction_root = _termination_private_root(release_root) / "transactions"
    transaction_root.mkdir(parents=True, exist_ok=True)
    unresolved = list(transaction_root.glob("*/manifest.json"))
    if unresolved:
        return {
            "status": "BLOCKED",
            "reason": "unresolved CR termination transaction exists",
            "mutation_count": 0,
        }
    transaction_id = uuid.uuid4().hex
    lock_owner = _acquire_status_sync_writer_lock(
        release_root,
        transaction_id=transaction_id,
        purpose="cr-terminate",
    )
    if lock_owner is None:
        return {
            "status": "BLOCKED",
            "reason": "process writer lock exists",
            "mutation_count": 0,
        }
    transaction_dir = transaction_root / transaction_id
    backup_root = transaction_dir / "backups"
    after_root = transaction_dir / "after"
    backup_root.mkdir(parents=True)
    after_root.mkdir(parents=True)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "transaction_id": transaction_id,
        "command": "cr terminate",
        "cr_id": plan.cr_id,
        "work_id": plan.work_id,
        "termination_reason": plan.termination_reason,
        "terminal_tuple": plan.terminal_tuple,
        "expected_facts": plan.expected_facts,
        "scope_digest": plan.scope_digest,
        "plan_digest": plan.plan_digest,
        "authorization_id": authorization.authorization_id,
        "lock": dict(lock_owner),
        "targets": [],
        "receipts": [],
        "recovery_state": "prepared",
        "created_at": now_utc(),
        "updated_at": now_utc(),
    }
    applied: list[TerminationTarget] = []
    manifest_path = transaction_dir / "manifest.json"
    try:
        _claim_termination_authorization(release_root, plan, authorization)
        if _fault == "after-claim-before-first-replace":
            raise RuntimeError("injected failure after authorization claim")
        for target in plan.targets:
            backup = backup_root / f"{target.order:03d}.before"
            prepared_after = after_root / f"{target.order:03d}.after"
            backup.write_text(target.before or "", encoding="utf-8")
            prepared_after.write_text(target.after, encoding="utf-8")
            if _canonical_digest(backup.read_text(encoding="utf-8")) != target.before_digest:
                raise RuntimeError(f"backup digest mismatch: {target.ref}")
            if _canonical_digest(prepared_after.read_text(encoding="utf-8")) != target.after_digest:
                raise RuntimeError(f"prepared after digest mismatch: {target.ref}")
            manifest["targets"].append(
                {
                    **target.as_dict(),
                    "before_content_ref": f"backups/{backup.name}",
                    "after_content_ref": f"after/{prepared_after.name}",
                    "apply_status": "prepared",
                    "rollback_status": "not-required",
                }
            )
        manifest_path.write_text(
            json.dumps(
                manifest,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        manifest["recovery_state"] = "applying"
        for offset, target in enumerate(plan.targets, 1):
            _atomic_write_text(target.path, target.after)
            applied.append(target)
            manifest["targets"][offset - 1]["apply_status"] = "applied"
            manifest["receipts"].append(
                {
                    "target_ref": target.ref,
                    "observed_before_digest": target.before_digest,
                    "observed_after_digest": _termination_current_digest(target),
                    "completed_at": now_utc(),
                }
            )
            manifest["updated_at"] = now_utc()
            manifest_path.write_text(
                json.dumps(
                    manifest,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            if _fail_after_replace == offset:
                raise RuntimeError(f"injected failure after replace {offset}")
        readback_failures = [
            target.ref
            for target in plan.targets
            if _termination_current_digest(target) != target.after_digest
        ]
        if readback_failures:
            raise RuntimeError("termination read-back mismatch: " + ", ".join(readback_failures))
        manifest["recovery_state"] = "committed"
        manifest["lock"]["lease_state"] = "released"
        manifest["updated_at"] = now_utc()
        manifest_path.write_text(
            json.dumps(
                manifest,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        shutil.rmtree(transaction_dir)
        return {
            "status": "PASS",
            "transaction_id": transaction_id,
            "plan_digest": plan.plan_digest,
            "authorization_id": authorization.authorization_id,
            "mutation_count": len(plan.targets),
            "path_refs": [target.ref for target in plan.targets],
        }
    except Exception as exc:
        recovery_errors: list[str] = []
        for target in reversed(applied):
            try:
                if _fail_recovery:
                    raise RuntimeError("injected rollback failure")
                if target.before is None:
                    target.path.unlink(missing_ok=True)
                else:
                    _atomic_write_text(target.path, target.before)
                if _termination_current_digest(target) != target.before_digest:
                    raise RuntimeError("rollback digest mismatch")
                for entry in manifest["targets"]:
                    if entry["ref"] == target.ref:
                        entry["rollback_status"] = "restored"
            except Exception as recovery_error:
                recovery_errors.append(f"{target.ref}: {recovery_error}")
        status = "PARTIAL" if recovery_errors else "RECOVERED" if applied else "BLOCKED"
        manifest["recovery_state"] = status.lower()
        manifest["lock"]["lease_state"] = "released"
        manifest["updated_at"] = now_utc()
        if manifest_path.parent.is_dir():
            manifest_path.write_text(
                json.dumps(
                    manifest,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
        if status in {"BLOCKED", "RECOVERED"}:
            shutil.rmtree(transaction_dir)
        result = {
            "status": status,
            "transaction_id": transaction_id,
            "plan_digest": plan.plan_digest,
            "authorization_id": authorization.authorization_id,
            "mutation_count": len(applied),
            "reason": str(exc),
            "rollback_errors": recovery_errors,
        }
        if status == "PARTIAL":
            result["rollback_evidence_ref"] = (
                f"private://cr-termination/transactions/{transaction_id}/manifest.json"
            )
        return result
    finally:
        _release_status_sync_writer_lock(release_root, lock_owner)
