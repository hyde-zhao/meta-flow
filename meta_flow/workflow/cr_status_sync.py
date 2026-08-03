"""Public CR status-sync planning and authorization owner."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from meta_flow.checks import cr_tracking, state_transition
from meta_flow.project.process_route import _resolve_runtime_ref
from meta_flow.project.scale import load_yaml_object
from meta_flow.state import checkpoint_projection, current, event_ledger
from meta_flow.work.model import load_work
from meta_flow.work.scope import check_scope
from meta_flow.workflow.cr_index import (
    CR_INDEX_REL,
    _canonical_digest,
    _dirty_path_digest,
    build_index,
    validate_index_payload,
)
from meta_flow.workflow.cr_model import (
    CLOSED_GATE_STATUS,
    DIGEST_RE,
    FINISHED_STATUSES,
    OID_RE,
    SAFE_AUTHORIZATION_ID_RE,
    now_utc,
    parse_frontmatter,
    render_frontmatter_fields,
)
from meta_flow.workflow.cr_projection import (
    CR_ARCHIVE_ROOT_REL,
    CR_LEDGER_REL,
    STATE_CURRENT_REL,
    _checkpoint_result_projection,
    render_status_body_projection,
    summary_from_cr_file,
)
from meta_flow.workflow.cr_records import (
    CR_SUMMARY_ROOT_REL,
    _load_json_object,
    _process_root,
    _rel,
    discover_formal_crs,
)
from meta_flow.workflow.cr_status_transaction import (
    _apply_status_sync_transaction,
    _status_sync_facts,
)

STATUS_SYNC_AUTHORIZATION_FIELDS = {
    "schema_version",
    "authorization_id",
    "authorization_source",
    "authorization_kind",
    "operation",
    "cr_id",
    "work_id",
    "desired_transition",
    "effective_at",
    "expected_release_oid",
    "expected_process_oid",
    "scope_digest",
    "targets",
    "plan_digest",
    "expires_at",
    "single_use",
}
STATUS_SYNC_AUTHORIZATION_SOURCE = "typed-user-confirmation"
STATUS_SYNC_AUTHORIZATION_KIND = "cr-status-sync"
STATUS_SYNC_OPERATION = "cr.status-sync"


@dataclass(frozen=True)
class StatusSyncTarget:
    order: int
    ref: str
    path: Path
    truth_or_derived: str
    before: str | None
    after: str

    @property
    def before_digest(self) -> str:
        return _canonical_digest(self.before) if self.before is not None else _canonical_digest("")

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
class StatusSyncAuthorization:
    schema_version: int
    authorization_id: str
    authorization_source: str
    authorization_kind: str
    operation: str
    cr_id: str
    work_id: str
    desired_transition: dict[str, str]
    effective_at: str
    expected_release_oid: str
    expected_process_oid: str
    scope_digest: str
    targets: list[dict[str, Any]]
    plan_digest: str
    expires_at: str
    single_use: bool = True

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> StatusSyncAuthorization:
        if set(payload) != STATUS_SYNC_AUTHORIZATION_FIELDS:
            missing = sorted(STATUS_SYNC_AUTHORIZATION_FIELDS - set(payload))
            extra = sorted(set(payload) - STATUS_SYNC_AUTHORIZATION_FIELDS)
            raise ValueError(
                f"status-sync authorization fields mismatch: missing={missing}, extra={extra}"
            )
        return cls(**payload)


@dataclass(frozen=True)
class StatusSyncPlan:
    decision: str
    cr_id: str
    work_id: str
    desired_transition: dict[str, str]
    expected_facts: dict[str, str]
    scope_digest: str
    targets: tuple[StatusSyncTarget, ...]
    reason: str = ""
    effective_at: str = ""

    def _digest_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "operation": STATUS_SYNC_OPERATION,
            "decision": self.decision,
            "cr_id": self.cr_id,
            "work_id": self.work_id,
            "desired_transition": self.desired_transition,
            "effective_at": self.effective_at,
            "expected_facts": self.expected_facts,
            "scope_digest": self.scope_digest,
            "targets": [target.as_dict() for target in self.targets],
            "reason": self.reason,
        }

    @property
    def plan_digest(self) -> str:
        return _canonical_digest(self._digest_payload())

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "operation": STATUS_SYNC_OPERATION,
            "decision": self.decision,
            "cr_id": self.cr_id,
            "work_id": self.work_id,
            "desired_transition": self.desired_transition,
            "effective_at": self.effective_at,
            "expected_facts": self.expected_facts,
            "scope_digest": self.scope_digest,
            "targets": [target.as_dict() for target in self.targets],
            "mutation_allowlist": [target.ref for target in self.targets],
            "planned_mutation_count": (len(self.targets) if self.decision == "READY" else 0),
            "mutation_count": 0,
            "plan_digest": self.plan_digest,
            "reason": self.reason,
        }


def _target(
    project_root: Path,
    order: int,
    path: Path,
    after: str,
    truth_or_derived: str,
) -> StatusSyncTarget:
    return StatusSyncTarget(
        order=order,
        ref=_rel(project_root, path),
        path=path,
        truth_or_derived=truth_or_derived,
        before=path.read_text(encoding="utf-8") if path.is_file() else None,
        after=after,
    )


def _json_semantically_matches(
    path: Path,
    expected: dict[str, Any],
    *,
    volatile_fields: tuple[str, ...] = (),
) -> bool:
    if not path.is_file():
        return False
    try:
        observed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    if not isinstance(observed, dict):
        return False
    observed = dict(observed)
    expected = dict(expected)
    for field in volatile_fields:
        observed.pop(field, None)
        expected.pop(field, None)
    return observed == expected


def _ledger_contains_status_sync_transition(
    path: Path,
    *,
    cr_id: str,
    lifecycle_status: str,
    readiness_status: str,
    gate_status: str,
) -> bool:
    """Match semantic status truth; dirty-path facts remain transaction preconditions only."""

    if not path.is_file():
        return False
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return False
        if (
            isinstance(event, dict)
            and event.get("event_type") == "status_sync"
            and str(event.get("id") or "") == cr_id
            and cr_tracking.normalize_lifecycle_status(str(event.get("status") or ""))
            == cr_tracking.normalize_lifecycle_status(lifecycle_status)
            and cr_tracking.normalize_readiness_status(str(event.get("readiness") or ""))
            == cr_tracking.normalize_readiness_status(readiness_status)
            and cr_tracking.normalize_gate_status(str(event.get("gate_status") or ""))
            == cr_tracking.normalize_gate_status(gate_status)
        ):
            return True
    return False


def _normalize_status_sync_effective_at(value: str) -> str:
    if not value:
        return now_utc()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("status-sync effective_at is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError("status-sync effective_at must include timezone")
    return parsed.astimezone(UTC).isoformat(timespec="seconds")


def plan_status_sync(
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
    rebuild_corrupt_index: bool = False,
    effective_at: str = "",
) -> StatusSyncPlan:
    """Build a zero-mutation status-sync transaction plan."""

    project_root = project_root.resolve()
    timestamp = _normalize_status_sync_effective_at(effective_at)
    facts, scope_digest = _status_sync_facts(
        project_root,
        work_id=work_id,
        canonical_digest=_canonical_digest,
        dirty_path_digest=_dirty_path_digest,
    )
    if expected_process_oid and facts["process_head_oid"] != expected_process_oid:
        return StatusSyncPlan(
            "BLOCKED",
            cr_id,
            work_id,
            {},
            facts,
            scope_digest,
            (),
            "process HEAD differs from expected OID",
            timestamp,
        )
    crs = discover_formal_crs(project_root)
    if cr_id not in crs:
        raise FileNotFoundError(f"未找到正式 CR: {cr_id}")
    cr_path = crs[cr_id]
    before_text = cr_path.read_text(encoding="utf-8")
    fields = parse_frontmatter(before_text)
    before_status = str(fields.get("lifecycle_status") or fields.get("status") or "active")
    before_readiness = str(fields.get("readiness_status") or "not_ready")
    before_gate = str(fields.get("gate_status") or "not_started")
    target_status = status or before_status
    target_readiness = readiness or before_readiness
    target_gate = gate_status or before_gate
    if target_status == "closed":
        if gate_status and gate_status != CLOSED_GATE_STATUS:
            raise ValueError(f"status=closed requires gate_status={CLOSED_GATE_STATUS}")
        target_gate = CLOSED_GATE_STATUS
    elif target_gate and target_gate not in cr_tracking.ALLOWED_GATE_STATUSES:
        raise ValueError(f"invalid gate_status: {target_gate}")
    native = (
        str(fields.get("schema_version") or "") == "1" and str(fields.get("kind") or "") == "cr"
    )
    if native:
        transition_errors = cr_tracking.validate_native_transition(
            (before_status, before_readiness, before_gate),
            (target_status, target_readiness, target_gate),
            historical_migration=historical_migration,
        )
        if transition_errors:
            return StatusSyncPlan(
                "BLOCKED",
                cr_id,
                work_id,
                {},
                facts,
                scope_digest,
                (),
                "; ".join(transition_errors),
            )
    index_path = _resolve_runtime_ref(project_root, CR_INDEX_REL.as_posix())
    if index_path.is_file():
        try:
            formal_truth_index = build_index(project_root)
        except ValueError as exc:
            return StatusSyncPlan("BLOCKED", cr_id, work_id, {}, facts, scope_digest, (), str(exc))
        try:
            existing_index = json.loads(index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            if not rebuild_corrupt_index:
                return StatusSyncPlan(
                    "BLOCKED",
                    cr_id,
                    work_id,
                    {},
                    facts,
                    scope_digest,
                    (),
                    f"CR-INDEX invalid JSON: {exc}",
                )
        else:
            index_errors = validate_index_payload(existing_index)
            if index_errors and not rebuild_corrupt_index:
                return StatusSyncPlan(
                    "BLOCKED", cr_id, work_id, {}, facts, scope_digest, (), "; ".join(index_errors)
                )
            if (
                not index_errors
                and existing_index.get("semantic_digest")
                != formal_truth_index.get("semantic_digest")
                and not rebuild_corrupt_index
            ):
                return StatusSyncPlan(
                    "BLOCKED",
                    cr_id,
                    work_id,
                    {},
                    facts,
                    scope_digest,
                    (),
                    "CR-INDEX stale projection differs from formal truth rebuild digest",
                )
    updates = {
        "lifecycle_status": target_status,
        "readiness_status": target_readiness,
        "gate_status": target_gate,
        "historical_gate_status": historical_gate_status,
        "historical_lifecycle_status": historical_lifecycle_status,
    }
    if "status" in fields:
        updates["status"] = target_status
    cr_after = render_frontmatter_fields(before_text, updates)
    cr_after = render_status_body_projection(
        cr_after,
        lifecycle_status=target_status,
        readiness_status=target_readiness,
        gate_status=target_gate,
        checkpoint_results=_checkpoint_result_projection(project_root, cr_id),
    )
    summary = summary_from_cr_file(project_root, cr_path, readiness=target_readiness)
    summary["status"] = target_status
    summary["readiness"] = target_readiness
    summary["gate_status"] = target_gate
    summary["updated_at"] = timestamp
    summary_path = _resolve_runtime_ref(
        project_root, (CR_SUMMARY_ROOT_REL / f"{cr_id}.summary.json").as_posix()
    )
    summary_after = (
        json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    )
    evidence_path = _resolve_runtime_ref(
        project_root, (CR_ARCHIVE_ROOT_REL / cr_id / "evidence-index.json").as_posix()
    )
    evidence = {
        "cr_id": cr_id,
        "summary_ref": (CR_SUMMARY_ROOT_REL / f"{cr_id}.summary.json").as_posix(),
        "full_ref": summary.get("full_ref"),
        "evidence_refs": [],
        "created_at": timestamp,
    }
    evidence_after = json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ledger_path = _resolve_runtime_ref(project_root, CR_LEDGER_REL.as_posix())
    ledger_event = {
        "event_id": _canonical_digest(
            {"event": "status_sync", "id": cr_id, "transition": updates, "facts": facts}
        ),
        "event": "status_sync",
        "event_type": "status_sync",
        "id": cr_id,
        "cr_type": summary.get("cr_type"),
        "status": target_status,
        "readiness": target_readiness,
        "gate_status": target_gate,
        "summary_ref": _rel(project_root, summary_path),
        "full_ref": summary.get("full_ref"),
        "evidence_index_ref": _rel(project_root, evidence_path),
        "frontmatter_changed": cr_after != before_text,
        "historical_migration": historical_migration,
        "synced_at": timestamp,
    }
    ledger_after = event_ledger.render_appended_event(ledger_path, ledger_event)
    expected_index = build_index(
        project_root,
        record_overrides={cr_id: updates},
    )
    expected_index["generated_at"] = timestamp
    index_after = json.dumps(expected_index, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    targets: list[StatusSyncTarget] = [
        _target(project_root, 10, cr_path, cr_after, "truth"),
    ]
    state_path = _resolve_runtime_ref(project_root, STATE_CURRENT_REL.as_posix())
    if state_path.is_file() and not historical_migration:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state_patch: dict[str, Any] = {"updated_at": timestamp}
        if target_status in FINISHED_STATUSES and state.get("active_change") == cr_id:
            state_patch.update(
                {
                    "active_change": None,
                    "active_context_ref": None,
                    "current_phase": "delivered"
                    if target_status == "closed"
                    else str(state.get("current_phase") or "delivered"),
                    "pending_gate": None,
                    "pending_checklist_path": None,
                    "next_action": {
                        "type": "done",
                        "text": f"{cr_id} status synced as {target_status}; choose next CR.",
                        "stop_reason": "delivered"
                        if target_status == "closed"
                        else "no_remaining_route",
                    },
                }
            )
        elif target_status in {"active", "blocked"} and not state.get("active_change"):
            state_patch.update(
                {
                    "active_change": cr_id,
                    "next_action": {
                        "type": "status_synced",
                        "text": f"{cr_id} status synced as {target_status}; continue from the Work route.",
                    },
                }
            )
        if len(state_patch) > 1:
            state_after = current.render_current_state_candidate(
                current.build_current_state_candidate(
                    project_root,
                    state_patch,
                    actor="meta_flow.workflow.cr_lifecycle",
                    reason=f"status-sync {cr_id}",
                )
            )
            targets.append(_target(project_root, 20, state_path, state_after, "truth"))
    if target_gate == "implementation_in_progress":
        cp5_projection = checkpoint_projection.load_checkpoint_projection(
            project_root,
            cr_id=cr_id,
            checkpoint="CP5",
        )
        if cp5_projection.findings or cp5_projection.head("CP5") is None:
            reason = (
                "; ".join(
                    f"{finding.code}:{finding.message}" for finding in cp5_projection.findings
                )
                or "CP5 canonical current head is unavailable"
            )
            return StatusSyncPlan(
                "BLOCKED",
                cr_id,
                work_id,
                {},
                facts,
                scope_digest,
                (),
                reason + "; mutation=0",
                timestamp,
            )
        gate_ledger_path = _resolve_runtime_ref(
            project_root,
            "process/state/GATE-LEDGER.ndjson",
        )
        gate_events, gate_errors = event_ledger.load_events(gate_ledger_path)
        if gate_errors:
            return StatusSyncPlan(
                "BLOCKED",
                cr_id,
                work_id,
                {},
                facts,
                scope_digest,
                (),
                "invalid Gate Ledger: " + "; ".join(gate_errors),
                timestamp,
            )
        development_plan_path = _resolve_runtime_ref(
            project_root,
            "process/DEVELOPMENT-PLAN.yaml",
        )
        if not development_plan_path.is_file():
            return StatusSyncPlan(
                "BLOCKED",
                cr_id,
                work_id,
                {},
                facts,
                scope_digest,
                (),
                "DEVELOPMENT-PLAN is unavailable; mutation=0",
                timestamp,
            )
        try:
            development_plan = load_yaml_object(development_plan_path)
            projected_plan, _story_transitions = state_transition.project_cp5_development_plan(
                development_plan,
                cr_id=cr_id,
                projection=cp5_projection,
                gate_events=gate_events,
            )
        except ValueError as exc:
            return StatusSyncPlan(
                "BLOCKED",
                cr_id,
                work_id,
                {},
                facts,
                scope_digest,
                (),
                str(exc),
                timestamp,
            )
        development_plan_after = (
            json.dumps(
                projected_plan,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        targets.append(
            _target(
                project_root,
                25,
                development_plan_path,
                development_plan_after,
                "truth",
            )
        )
    targets.extend(
        [
            _target(project_root, 30, summary_path, summary_after, "derived"),
            _target(project_root, 40, evidence_path, evidence_after, "derived"),
            _target(project_root, 50, ledger_path, ledger_after, "derived"),
            _target(project_root, 90, index_path, index_after, "derived"),
        ]
    )
    if work_id:
        work = load_work(_process_root(project_root), work_id)
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
            return StatusSyncPlan(
                "BLOCKED",
                cr_id,
                work_id,
                {},
                facts,
                scope_digest,
                (),
                "targets outside Work write scope: " + ", ".join(denied),
            )
    desired_transition = {
        "lifecycle_status": target_status,
        "readiness_status": target_readiness,
        "gate_status": target_gate,
    }
    truth_current = all(
        target.before is not None and target.before_digest == target.after_digest
        for target in targets
        if target.truth_or_derived == "truth"
    )
    derived_current = (
        _json_semantically_matches(
            summary_path,
            summary,
            volatile_fields=("updated_at",),
        )
        and _json_semantically_matches(
            evidence_path,
            evidence,
            volatile_fields=("created_at",),
        )
        and _ledger_contains_status_sync_transition(
            ledger_path,
            cr_id=cr_id,
            lifecycle_status=target_status,
            readiness_status=target_readiness,
            gate_status=target_gate,
        )
        and index_path.is_file()
        and json.loads(index_path.read_text(encoding="utf-8")).get("semantic_digest")
        == expected_index.get("semantic_digest")
    )
    if truth_current and derived_current:
        return StatusSyncPlan(
            "NO_CHANGE",
            cr_id,
            work_id,
            desired_transition,
            facts,
            scope_digest,
            (),
            "status tuple and native projections are already synchronized",
            timestamp,
        )
    return StatusSyncPlan(
        "READY",
        cr_id,
        work_id,
        desired_transition,
        facts,
        scope_digest,
        tuple(sorted(targets, key=lambda item: item.order)),
        effective_at=timestamp,
    )


def load_status_sync_authorization(path: Path) -> StatusSyncAuthorization:
    payload = _load_json_object(path, subject="status-sync authorization")
    return StatusSyncAuthorization.from_dict(payload)


def validate_status_sync_authorization(
    plan: StatusSyncPlan,
    authorization: StatusSyncAuthorization,
) -> None:
    if plan.decision != "READY":
        raise ValueError("status-sync authorization requires one READY plan")
    if not plan.work_id or not plan.scope_digest:
        raise ValueError("status-sync typed apply requires work_id and scope digest")
    if authorization.schema_version != 1:
        raise ValueError("status-sync authorization schema_version must be 1")
    if not SAFE_AUTHORIZATION_ID_RE.fullmatch(authorization.authorization_id):
        raise ValueError("status-sync authorization_id is invalid")
    if authorization.authorization_source != STATUS_SYNC_AUTHORIZATION_SOURCE:
        raise ValueError("status-sync authorization_source must be typed-user-confirmation")
    if authorization.authorization_kind != STATUS_SYNC_AUTHORIZATION_KIND:
        raise ValueError("status-sync authorization_kind must be cr-status-sync")
    if authorization.operation != STATUS_SYNC_OPERATION:
        raise ValueError("status-sync authorization operation mismatch")
    if authorization.single_use is not True:
        raise ValueError("status-sync authorization must be single-use")
    expected = (
        plan.cr_id,
        plan.work_id,
        plan.desired_transition,
        plan.effective_at,
        plan.expected_facts.get("release_head_oid", ""),
        plan.expected_facts.get("process_head_oid", ""),
        plan.scope_digest,
        [target.as_dict() for target in plan.targets],
        plan.plan_digest,
    )
    actual = (
        authorization.cr_id,
        authorization.work_id,
        authorization.desired_transition,
        authorization.effective_at,
        authorization.expected_release_oid,
        authorization.expected_process_oid,
        authorization.scope_digest,
        authorization.targets,
        authorization.plan_digest,
    )
    if actual != expected:
        raise ValueError(
            "status-sync authorization does not match "
            "CR/Work/transition/effective_at/OIDs/scope/targets/plan"
        )
    if not OID_RE.fullmatch(authorization.expected_release_oid):
        raise ValueError("status-sync expected_release_oid is invalid")
    if not OID_RE.fullmatch(authorization.expected_process_oid):
        raise ValueError("status-sync expected_process_oid is invalid")
    if not DIGEST_RE.fullmatch(authorization.scope_digest):
        raise ValueError("status-sync scope_digest is invalid")
    if not DIGEST_RE.fullmatch(authorization.plan_digest):
        raise ValueError("status-sync plan_digest is invalid")
    try:
        expires_at = datetime.fromisoformat(authorization.expires_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("status-sync authorization expires_at is invalid") from exc
    if expires_at.tzinfo is None:
        raise ValueError("status-sync authorization expires_at must include timezone")
    if expires_at.astimezone(UTC) <= datetime.now(UTC):
        raise ValueError("status-sync authorization is expired")



def apply_status_sync(project_root: Path, plan: StatusSyncPlan, *, authorization: StatusSyncAuthorization | None = None, expected_plan_digest: str = "", _fail_after_replace: int | None = None, _fail_recovery: bool = False, _fault: str = "") -> dict[str, Any]:
    """Validate public status input, then delegate only structural values to transaction."""
    project_root = project_root.resolve()
    if plan.decision == "NO_CHANGE":
        return {"status": "NO_CHANGE", "reason": plan.reason, "mutation_count": 0}
    if plan.decision != "READY":
        return {"status": "BLOCKED", "reason": plan.reason, "mutation_count": 0}
    if not expected_plan_digest or expected_plan_digest != plan.plan_digest:
        return {"status": "BLOCKED", "reason": "expected plan digest does not match the current plan", "mutation_count": 0}
    if authorization is None:
        return {"status": "BLOCKED", "reason": "status-sync apply requires typed authorization", "mutation_count": 0}
    try:
        validate_status_sync_authorization(plan, authorization)
    except ValueError as exc:
        return {"status": "BLOCKED", "reason": str(exc), "mutation_count": 0}
    observed_facts, observed_scope = _status_sync_facts(
        project_root,
        work_id=plan.work_id,
        canonical_digest=_canonical_digest,
        dirty_path_digest=_dirty_path_digest,
    )
    if observed_facts != plan.expected_facts or observed_scope != plan.scope_digest:
        return {"status": "BLOCKED", "reason": "expected facts or scope digest drifted", "mutation_count": 0}
    validated = {
        "plan": {
            "cr_id": plan.cr_id, "work_id": plan.work_id, "desired_transition": dict(plan.desired_transition),
            "effective_at": plan.effective_at, "expected_facts": dict(plan.expected_facts),
            "scope_digest": plan.scope_digest, "plan_digest": plan.plan_digest,
            "targets": [{"order": target.order, "ref": target.ref, "path": target.path, "truth_or_derived": target.truth_or_derived, "before": target.before, "before_digest": target.before_digest, "after": target.after, "after_digest": target.after_digest} for target in plan.targets],
        },
        "authorization": dict(authorization.__dict__),
    }
    return _apply_status_sync_transaction(
        project_root,
        validated,
        canonical_digest=_canonical_digest,
        index_ref=CR_INDEX_REL.as_posix(),
        fail_after_replace=_fail_after_replace,
        fail_recovery=_fail_recovery,
        fault=_fault,
    )

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
) -> dict[str, Path]:
    """Compatibility API backed by the typed recoverable plan/apply transaction."""

    plan = plan_status_sync(
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
    )
    result = apply_status_sync(
        project_root,
        plan,
        authorization=authorization,
        expected_plan_digest=expected_plan_digest,
    )
    if result["status"] not in {"PASS", "NO_CHANGE"}:
        raise RuntimeError(f"status-sync {result['status']}: {result.get('reason', '')}")
    if result["status"] == "NO_CHANGE":
        cr_path = discover_formal_crs(project_root)[cr_id]
        return {
            "cr": cr_path,
            "summary": _resolve_runtime_ref(
                project_root,
                (CR_SUMMARY_ROOT_REL / f"{cr_id}.summary.json").as_posix(),
            ),
            "evidence_index": _resolve_runtime_ref(
                project_root,
                (CR_ARCHIVE_ROOT_REL / cr_id / "evidence-index.json").as_posix(),
            ),
            "index": _resolve_runtime_ref(project_root, CR_INDEX_REL.as_posix()),
            "ledger": _resolve_runtime_ref(project_root, CR_LEDGER_REL.as_posix()),
        }
    by_ref = result["paths"]
    return {
        "cr": by_ref[_rel(project_root, discover_formal_crs(project_root)[cr_id])],
        "summary": by_ref[(CR_SUMMARY_ROOT_REL / f"{cr_id}.summary.json").as_posix()],
        "evidence_index": by_ref[(CR_ARCHIVE_ROOT_REL / cr_id / "evidence-index.json").as_posix()],
        "index": by_ref[CR_INDEX_REL.as_posix()],
        "ledger": by_ref[CR_LEDGER_REL.as_posix()],
    }
