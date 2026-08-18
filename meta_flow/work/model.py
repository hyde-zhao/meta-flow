"""文件化 Work Envelope 模型。"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from meta_flow.execution_control.contract import ExecutionUnitV1
from meta_flow.project.model import is_safe_ref
from meta_flow.project.read_contract import ReadContextProtocol
from meta_flow.project.scale import dump_yaml, load_yaml_object
from meta_flow.work.budget import BudgetLimit
from meta_flow.work.risk import RISK_PROFILES, ClassificationDecision
from meta_flow.work.route_profile import (
    SAFE_ROUTE_PROFILE,
    RouteProfile,
    evaluate_route_profile,
    route_profile_from_payload,
)
from meta_flow.work.scope import WorkScope

WORK_SCHEMA_VERSION = 1
WORK_MAX_BYTES = 16 * 1024
WORK_KINDS = {"work", "cr", "migration", "retro", "evolution"}
WORK_STATUSES = {
    "planned",
    "active",
    "paused",
    "blocked",
    "ready_for_review",
    "ready_for_verification",
    "completed",
    "cancelled",
    "archived",
}
WORK_ALLOWED_KEYS = {
    "schema_version",
    "work_id",
    "project_id",
    "kind",
    "objective",
    "status",
    "request_ref",
    "request_confirmed",
    "phase_ref",
    "risk_profile",
    "risk_reason_codes",
    "required_gates",
    "route_profile",
    "execution_unit",
    "scope",
    "scope_digest",
    "budget",
    "usage_ref",
    "base_oids",
    "result_ref",
    "updated_at",
}
WORK_REQUIRED_KEYS = WORK_ALLOWED_KEYS - {
    "phase_ref",
    "result_ref",
    "route_profile",
    "execution_unit",
    "updated_at",
}
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_REASON_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,127}$")
_GATE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SCOPE_VALUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_OWNED_LEAF_RE = re.compile(r"^[A-Za-z0-9.][A-Za-z0-9._/-]*$")


def _is_safe_owned_leaf(value: str) -> bool:
    """接受安全相对 leaf，包括仓库根目录下的 dotfile。"""
    return bool(_OWNED_LEAF_RE.fullmatch(value)) and all(
        part not in {"", ".", ".."} for part in value.split("/")
    )


@dataclass(frozen=True)
class WorkFinding:
    severity: str
    code: str
    message: str
    key: str | None = None


@dataclass(frozen=True)
class ScopeDeltaV1:
    """Closed, add-only scope amendment input; no removal vocabulary exists."""

    schema_version: int
    add_story_ids: tuple[str, ...] = ()
    add_owned_leaves: tuple[str, ...] = ()
    add_dependency_edges: tuple[str, ...] = ()
    add_acceptance_refs: tuple[str, ...] = ()
    reason: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("INVALID_SCOPE_DELTA")
        all_values = self.add_story_ids + self.add_owned_leaves + self.add_dependency_edges + self.add_acceptance_refs
        if not all_values:
            raise ValueError("INVALID_SCOPE_DELTA")
        for values in (
            self.add_story_ids,
            self.add_dependency_edges,
            self.add_acceptance_refs,
        ):
            if tuple(sorted(set(values))) != values or any(
                not _SCOPE_VALUE_RE.fullmatch(value) for value in values
            ):
                raise ValueError("INVALID_SCOPE_DELTA")
        if tuple(sorted(set(self.add_owned_leaves))) != self.add_owned_leaves or any(
            not _is_safe_owned_leaf(value) for value in self.add_owned_leaves
        ):
            raise ValueError("INVALID_SCOPE_DELTA")


@dataclass(frozen=True)
class PredecessorInventoryReceiptV1:
    cr_id: str
    predecessor_revision_id: str
    terminal_status: str
    inventory: tuple[str, ...]
    inventory_digest: str
    revision_bytes_digest: str

    def __post_init__(self) -> None:
        if (
            not _ID_RE.fullmatch(self.cr_id)
            or not _ID_RE.fullmatch(self.predecessor_revision_id)
            or self.terminal_status not in {"verified", "completed", "closed"}
            or tuple(sorted(set(self.inventory))) != self.inventory
            or not self.inventory
            or not re.fullmatch(r"[0-9a-f]{64}", self.inventory_digest)
            or not re.fullmatch(r"[0-9a-f]{64}", self.revision_bytes_digest)
        ):
            raise ValueError("STALE_PREDECESSOR_BINDING")


@dataclass(frozen=True)
class ScopeAmendPlanV1:
    revision_id: str
    predecessor: PredecessorInventoryReceiptV1 | None
    scope_digest: str
    snapshot_digest: str
    plan_digest: str
    mutation_count: int = 0
    cr_id: str = ""
    work_id: str = ""
    current_scope: tuple[str, ...] = ()
    result_scope: tuple[str, ...] = ()
    authorization_digest: str = ""
    envelope_digest: str = ""
    validation_graph_digest: str = ""
    snapshot_bindings: tuple[tuple[str, str], ...] = ()
    invalidated_refs: tuple[str, ...] = ()
    previous_objective: str = ""
    result_objective: str = ""


@dataclass(frozen=True)
class WorkRevisionV2:
    schema_version: int
    cr_id: str
    work_id: str
    revision_id: str
    predecessor_revision_id: str
    predecessor_revision_bytes_digest: str
    scope_digest: str
    previous_scope: tuple[str, ...]
    scope: tuple[str, ...]
    invalidated_refs: tuple[str, ...]
    plan_digest: str
    validation_graph_digest: str

    def __post_init__(self) -> None:
        if (
            self.schema_version != 2
            or not all(
                _ID_RE.fullmatch(value)
                for value in (
                    self.cr_id,
                    self.work_id,
                    self.revision_id,
                    self.predecessor_revision_id,
                )
            )
            or any(
                not re.fullmatch(r"[0-9a-f]{64}", value)
                for value in (
                    self.predecessor_revision_bytes_digest,
                    self.scope_digest,
                    self.plan_digest,
                    self.validation_graph_digest,
                )
            )
            or tuple(sorted(set(self.scope))) != self.scope
            or not set(self.previous_scope) < set(self.scope)
            or tuple(sorted(set(self.invalidated_refs))) != self.invalidated_refs
        ):
            raise ValueError("INVALID_SCOPE_AMEND_REVISION")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "cr_id": self.cr_id,
            "work_id": self.work_id,
            "revision_id": self.revision_id,
            "predecessor_revision_id": self.predecessor_revision_id,
            "predecessor_revision_bytes_digest": self.predecessor_revision_bytes_digest,
            "scope_digest": self.scope_digest,
            "previous_scope": list(self.previous_scope),
            "scope": list(self.scope),
            "invalidated_refs": list(self.invalidated_refs),
            "plan_digest": self.plan_digest,
            "validation_graph_digest": self.validation_graph_digest,
        }


@dataclass(frozen=True)
class WorkRevisionV3:
    """Scope successor that also records one typed objective replacement."""

    schema_version: int
    cr_id: str
    work_id: str
    revision_id: str
    predecessor_revision_id: str
    predecessor_revision_bytes_digest: str
    scope_digest: str
    previous_scope: tuple[str, ...]
    scope: tuple[str, ...]
    invalidated_refs: tuple[str, ...]
    plan_digest: str
    validation_graph_digest: str
    previous_objective: str
    objective: str

    def __post_init__(self) -> None:
        if (
            self.schema_version != 3
            or not all(
                _ID_RE.fullmatch(value)
                for value in (
                    self.cr_id,
                    self.work_id,
                    self.revision_id,
                    self.predecessor_revision_id,
                )
            )
            or any(
                not re.fullmatch(r"[0-9a-f]{64}", value)
                for value in (
                    self.predecessor_revision_bytes_digest,
                    self.scope_digest,
                    self.plan_digest,
                    self.validation_graph_digest,
                )
            )
            or tuple(sorted(set(self.scope))) != self.scope
            or not set(self.previous_scope) < set(self.scope)
            or tuple(sorted(set(self.invalidated_refs))) != self.invalidated_refs
            or not self.previous_objective.strip()
            or not self.objective.strip()
            or self.previous_objective == self.objective
        ):
            raise ValueError("INVALID_SCOPE_AMEND_REVISION")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "cr_id": self.cr_id,
            "work_id": self.work_id,
            "revision_id": self.revision_id,
            "predecessor_revision_id": self.predecessor_revision_id,
            "predecessor_revision_bytes_digest": self.predecessor_revision_bytes_digest,
            "scope_digest": self.scope_digest,
            "previous_scope": list(self.previous_scope),
            "scope": list(self.scope),
            "invalidated_refs": list(self.invalidated_refs),
            "plan_digest": self.plan_digest,
            "validation_graph_digest": self.validation_graph_digest,
            "previous_objective": self.previous_objective,
            "objective": self.objective,
        }


def validate_scope_delta(
    current_scope: tuple[str, ...],
    delta: ScopeDeltaV1,
    authorized_leaves: tuple[str, ...],
) -> tuple[str, ...]:
    """Return a strict canonical superset or fail closed before any plan/write."""
    additions = tuple(
        sorted(
            set(
                delta.add_story_ids
                + delta.add_owned_leaves
                + delta.add_dependency_edges
                + delta.add_acceptance_refs
            )
        )
    )
    if (
        not additions
        or any(leaf in current_scope for leaf in delta.add_owned_leaves)
        or not set(delta.add_owned_leaves).issubset(authorized_leaves)
    ):
        raise ValueError("SCOPE_NARROWING")
    result = tuple(sorted(set(current_scope) | set(additions)))
    if len(result) <= len(current_scope):
        raise ValueError("SCOPE_NARROWING")
    return result


def plan_scope_amend(
    *,
    revision_id: str,
    current_scope: tuple[str, ...],
    delta: ScopeDeltaV1,
    authorized_leaves: tuple[str, ...],
    predecessor: PredecessorInventoryReceiptV1 | None,
    snapshot_digest: str,
    cr_id: str = "",
    work_id: str = "",
    authorization_digest: str = "",
    envelope_digest: str = "",
    validation_graph_digest: str = "",
    snapshot_bindings: tuple[tuple[str, str], ...] = (),
    invalidated_refs: tuple[str, ...] = (),
    previous_objective: str = "",
    result_objective: str = "",
) -> ScopeAmendPlanV1:
    if not _ID_RE.fullmatch(revision_id) or not re.fullmatch(r"[0-9a-f]{64}", snapshot_digest):
        raise ValueError("INVALID_SCOPE_DELTA")
    if predecessor is None or predecessor.terminal_status not in {"verified", "completed", "closed"} or not predecessor.inventory:
        raise ValueError("MISSING_PREDECESSOR_INVENTORY")
    scope = validate_scope_delta(current_scope, delta, authorized_leaves)
    scope_digest = hashlib.sha256(
        json.dumps(scope, separators=(",", ":")).encode()
    ).hexdigest()
    bindings = tuple(sorted(snapshot_bindings))
    invalidations = tuple(sorted(set(invalidated_refs)))
    identity = {
        "revision_id": revision_id,
        "scope_digest": scope_digest,
        "predecessor": predecessor.inventory_digest,
        "snapshot": snapshot_digest,
        "cr_id": cr_id,
        "work_id": work_id,
        "authorization_digest": authorization_digest,
        "envelope_digest": envelope_digest,
        "validation_graph_digest": validation_graph_digest,
        "snapshot_bindings": bindings,
        "invalidated_refs": invalidations,
    }
    if previous_objective or result_objective:
        if (
            not previous_objective.strip()
            or not result_objective.strip()
            or previous_objective == result_objective
        ):
            raise ValueError("INVALID_OBJECTIVE_AMENDMENT")
        identity["previous_objective"] = previous_objective
        identity["result_objective"] = result_objective
    digest = hashlib.sha256(
        json.dumps(
            identity,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return ScopeAmendPlanV1(
        revision_id,
        predecessor,
        scope_digest,
        snapshot_digest,
        digest,
        0,
        cr_id,
        work_id,
        tuple(sorted(current_scope)),
        scope,
        authorization_digest,
        envelope_digest,
        validation_graph_digest,
        bindings,
        invalidations,
        previous_objective,
        result_objective,
    )


def apply_scope_amend(
    plan: ScopeAmendPlanV1,
    *,
    fresh_snapshot_digest: str,
    fresh_snapshot_bindings: tuple[tuple[str, str], ...] | None = None,
) -> dict[str, object]:
    """Return the append-only successor admitted by an exact fresh snapshot."""
    if (
        fresh_snapshot_digest != plan.snapshot_digest
        or (
            fresh_snapshot_bindings is not None
            and tuple(sorted(fresh_snapshot_bindings)) != plan.snapshot_bindings
        )
    ):
        return {"decision": "REPLAN_REQUIRED", "mutation_count": 0, "plan_digest": plan.plan_digest}
    if not all(
        (
            plan.cr_id,
            plan.work_id,
            plan.current_scope,
            plan.result_scope,
            plan.authorization_digest,
            plan.envelope_digest,
            plan.validation_graph_digest,
        )
    ):
        return {"decision": "READY", "mutation_count": 0, "plan_digest": plan.plan_digest}
    assert plan.predecessor is not None
    if plan.previous_objective or plan.result_objective:
        revision: WorkRevisionV2 | WorkRevisionV3 = WorkRevisionV3(
            3,
            plan.cr_id,
            plan.work_id,
            plan.revision_id,
            plan.predecessor.predecessor_revision_id,
            plan.predecessor.revision_bytes_digest,
            plan.scope_digest,
            plan.current_scope,
            plan.result_scope,
            plan.invalidated_refs,
            plan.plan_digest,
            plan.validation_graph_digest,
            plan.previous_objective,
            plan.result_objective,
        )
    else:
        revision = WorkRevisionV2(
            2,
            plan.cr_id,
            plan.work_id,
            plan.revision_id,
            plan.predecessor.predecessor_revision_id,
            plan.predecessor.revision_bytes_digest,
            plan.scope_digest,
            plan.current_scope,
            plan.result_scope,
            plan.invalidated_refs,
            plan.plan_digest,
            plan.validation_graph_digest,
        )
    return {
        "decision": "READY",
        "mutation_count": 0,
        "plan_digest": plan.plan_digest,
        "revision": revision,
    }


@dataclass(frozen=True)
class Work:
    schema_version: int
    work_id: str
    project_id: str
    kind: str
    objective: str
    status: str
    request_ref: str
    request_confirmed: bool
    phase_ref: str
    risk_profile: str
    risk_reason_codes: tuple[str, ...]
    required_gates: tuple[str, ...]
    route_profile: RouteProfile
    scope: WorkScope
    budget: BudgetLimit
    usage_ref: str
    release_base_oid: str
    process_base_oid: str
    execution_unit: ExecutionUnitV1 | None = None
    result_ref: str = ""
    updated_at: str = ""

    @property
    def directory_ref(self) -> str:
        return f"works/{self.work_id}"

    @property
    def work_ref(self) -> str:
        return f"{self.directory_ref}/WORK.yaml"

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "work_id": self.work_id,
            "project_id": self.project_id,
            "kind": self.kind,
            "objective": self.objective,
            "status": self.status,
            "request_ref": self.request_ref,
            "request_confirmed": self.request_confirmed,
            "risk_profile": self.risk_profile,
            "risk_reason_codes": list(self.risk_reason_codes),
            "required_gates": list(self.required_gates),
            "route_profile": self.route_profile.as_dict(),
            "scope": self.scope.as_dict(),
            "scope_digest": self.scope.digest,
            "budget": self.budget.as_dict(),
            "usage_ref": self.usage_ref,
            "base_oids": {
                "release": self.release_base_oid,
                "process": self.process_base_oid,
            },
        }
        if self.phase_ref:
            payload["phase_ref"] = self.phase_ref
        if self.execution_unit is not None:
            payload["execution_unit"] = self.execution_unit.as_dict()
        if self.result_ref:
            payload["result_ref"] = self.result_ref
        if self.updated_at:
            payload["updated_at"] = self.updated_at
        return payload


def _finding(
    findings: list[WorkFinding],
    code: str,
    message: str,
    *,
    key: str | None = None,
) -> None:
    findings.append(WorkFinding("ERROR", code, message, key))


def _safe_oid(value: Any) -> bool:
    return isinstance(value, str) and (
        value == ""
        or (len(value) in {40, 64} and all(char in "0123456789abcdefABCDEF" for char in value))
    )


def _expected_work_prefix(payload: Mapping[str, Any]) -> str:
    return f"works/{payload.get('work_id', '')}/"


def validate_work_payload(
    payload: Mapping[str, Any],
    *,
    byte_size: int | None = None,
) -> list[WorkFinding]:
    findings: list[WorkFinding] = []
    if byte_size is not None and byte_size > WORK_MAX_BYTES:
        _finding(
            findings, "work_over_budget", f"WORK.yaml exceeds {WORK_MAX_BYTES} bytes: {byte_size}"
        )
    for key in sorted(set(payload) - WORK_ALLOWED_KEYS):
        _finding(findings, "unknown_key", f"WORK.yaml contains unknown field: {key}", key=key)
    for key in sorted(WORK_REQUIRED_KEYS - set(payload)):
        _finding(findings, "missing_required", f"WORK.yaml missing required field: {key}", key=key)
    if payload.get("schema_version") != WORK_SCHEMA_VERSION:
        _finding(
            findings,
            "schema_version",
            f"schema_version must be {WORK_SCHEMA_VERSION}",
            key="schema_version",
        )
    for key in ("work_id", "project_id"):
        value = payload.get(key)
        if not isinstance(value, str) or not _ID_RE.fullmatch(value):
            _finding(findings, "id", f"{key} must use 1-64 safe ID characters", key=key)
    if payload.get("kind") not in WORK_KINDS:
        _finding(findings, "kind", "kind is not a supported Work kind", key="kind")
    objective = payload.get("objective")
    if not isinstance(objective, str) or not objective.strip():
        _finding(findings, "objective", "objective must be a non-empty string", key="objective")
    if payload.get("status") not in WORK_STATUSES:
        _finding(findings, "status", "status is not a supported Work status", key="status")
    if payload.get("request_confirmed") is not True:
        _finding(
            findings,
            "request_confirmation",
            "request_confirmed must be true before Work creation",
            key="request_confirmed",
        )

    prefix = _expected_work_prefix(payload)
    for key in ("request_ref", "usage_ref"):
        value = payload.get(key)
        if not isinstance(value, str) or not is_safe_ref(value) or not value.startswith(prefix):
            _finding(findings, "ref_path", f"{key} must be under {prefix}", key=key)
    phase_ref = payload.get("phase_ref", "")
    if phase_ref not in (None, "") and (
        not isinstance(phase_ref, str) or not is_safe_ref(phase_ref, prefix="phases")
    ):
        _finding(findings, "ref_path", "phase_ref must be under phases/", key="phase_ref")
    result_ref = payload.get("result_ref", "")
    if result_ref not in (None, "") and (
        not isinstance(result_ref, str)
        or not is_safe_ref(result_ref)
        or not result_ref.startswith(prefix)
    ):
        _finding(findings, "ref_path", f"result_ref must be under {prefix}", key="result_ref")

    risk_profile = payload.get("risk_profile")
    if risk_profile not in RISK_PROFILES:
        _finding(findings, "risk_profile", "risk_profile must be G0, G1, or G2", key="risk_profile")
    reasons = payload.get("risk_reason_codes")
    if (
        not isinstance(reasons, list)
        or not reasons
        or not all(isinstance(item, str) and _REASON_RE.fullmatch(item) for item in reasons)
    ):
        _finding(
            findings,
            "risk_reason_codes",
            "risk_reason_codes must be non-empty safe codes",
            key="risk_reason_codes",
        )
    elif len(reasons) != len(set(reasons)):
        _finding(
            findings, "duplicate", "risk_reason_codes contains duplicates", key="risk_reason_codes"
        )
    gates = payload.get("required_gates")
    if not isinstance(gates, list) or not all(
        isinstance(item, str) and _GATE_RE.fullmatch(item) for item in gates
    ):
        _finding(
            findings, "required_gates", "required_gates must be safe codes", key="required_gates"
        )
    elif len(gates) != len(set(gates)):
        _finding(findings, "duplicate", "required_gates contains duplicates", key="required_gates")

    try:
        route_profile = route_profile_from_payload(payload.get("route_profile"))
    except (TypeError, ValueError) as exc:
        _finding(findings, "route_profile", str(exc), key="route_profile")
    else:
        route_decision = evaluate_route_profile(
            route_profile,
            risk_profile=str(risk_profile or ""),
            work_kind=str(payload.get("kind") or ""),
            require_human_approval=False,
        )
        for error in route_decision.errors:
            _finding(findings, "route_profile", error, key="route_profile")

    execution_unit_payload = payload.get("execution_unit")
    if execution_unit_payload is not None:
        if payload.get("kind") not in {"work", "cr"}:
            _finding(
                findings,
                "execution_unit",
                "execution_unit v1 is supported only by Work/CR execution envelopes",
                key="execution_unit",
            )
        if not isinstance(execution_unit_payload, Mapping):
            _finding(
                findings,
                "execution_unit",
                "execution_unit must be a closed mapping",
                key="execution_unit",
            )
        else:
            try:
                ExecutionUnitV1.from_mapping(
                    execution_unit_payload,
                    work_id=str(payload.get("work_id") or ""),
                )
            except ValueError as exc:
                _finding(findings, "execution_unit", str(exc), key="execution_unit")

    scope_payload = payload.get("scope")
    if not isinstance(scope_payload, dict):
        _finding(findings, "scope", "scope must be an object", key="scope")
    else:
        try:
            scope = WorkScope(
                version=scope_payload.get("version"),
                allowed_reads=tuple(scope_payload.get("allowed_reads") or ()),
                allowed_writes=tuple(scope_payload.get("allowed_writes") or ()),
                required_checks=tuple(scope_payload.get("required_checks") or ()),
            )
        except (TypeError, ValueError) as exc:
            _finding(findings, "scope", str(exc), key="scope")
        else:
            if payload.get("scope_digest") != scope.digest:
                _finding(
                    findings,
                    "scope_digest",
                    "scope_digest does not match scope",
                    key="scope_digest",
                )

    budget_payload = payload.get("budget")
    if not isinstance(budget_payload, dict) or set(budget_payload) != {
        "reads",
        "writes",
        "check_groups",
        "tokens",
    }:
        _finding(
            findings, "budget", "budget must contain reads/writes/check_groups/tokens", key="budget"
        )
    else:
        try:
            BudgetLimit(**budget_payload)
        except (TypeError, ValueError) as exc:
            _finding(findings, "budget", str(exc), key="budget")

    base_oids = payload.get("base_oids")
    if not isinstance(base_oids, dict) or set(base_oids) != {"release", "process"}:
        _finding(
            findings, "base_oids", "base_oids must contain release and process", key="base_oids"
        )
    else:
        for role in ("release", "process"):
            if not _safe_oid(base_oids.get(role)):
                _finding(
                    findings,
                    "base_oid",
                    f"base_oids.{role} must be empty or one full hex OID",
                    key="base_oids",
                )
    if payload.get("status") == "completed" and not result_ref:
        _finding(
            findings, "result_required", "completed Work requires result_ref", key="result_ref"
        )
    return findings


def work_from_payload(payload: Mapping[str, Any]) -> Work:
    findings = validate_work_payload(payload)
    if findings:
        raise ValueError("; ".join(finding.message for finding in findings))
    scope_payload = payload["scope"]
    budget_payload = payload["budget"]
    base_oids = payload["base_oids"]
    assert isinstance(scope_payload, dict)
    assert isinstance(budget_payload, dict)
    assert isinstance(base_oids, dict)
    execution_unit_payload = payload.get("execution_unit")
    return Work(
        schema_version=int(payload["schema_version"]),
        work_id=str(payload["work_id"]),
        project_id=str(payload["project_id"]),
        kind=str(payload["kind"]),
        objective=str(payload["objective"]),
        status=str(payload["status"]),
        request_ref=str(payload["request_ref"]),
        request_confirmed=True,
        phase_ref=str(payload.get("phase_ref") or ""),
        risk_profile=str(payload["risk_profile"]),
        risk_reason_codes=tuple(str(item) for item in payload["risk_reason_codes"]),
        required_gates=tuple(str(item) for item in payload["required_gates"]),
        route_profile=route_profile_from_payload(payload.get("route_profile")),
        scope=WorkScope(
            version=int(scope_payload["version"]),
            allowed_reads=tuple(str(item) for item in scope_payload["allowed_reads"]),
            allowed_writes=tuple(str(item) for item in scope_payload["allowed_writes"]),
            required_checks=tuple(str(item) for item in scope_payload["required_checks"]),
        ),
        budget=BudgetLimit(**budget_payload),
        usage_ref=str(payload["usage_ref"]),
        release_base_oid=str(base_oids["release"]),
        process_base_oid=str(base_oids["process"]),
        execution_unit=(
            ExecutionUnitV1.from_mapping(
                execution_unit_payload,
                work_id=str(payload["work_id"]),
            )
            if isinstance(execution_unit_payload, Mapping)
            else None
        ),
        result_ref=str(payload.get("result_ref") or ""),
        updated_at=str(payload.get("updated_at") or ""),
    )


def build_work(
    *,
    work_id: str,
    project_id: str,
    objective: str,
    request_ref: str,
    scope: WorkScope,
    classification: ClassificationDecision,
    release_base_oid: str,
    process_base_oid: str,
    phase_ref: str = "",
    kind: str | None = None,
    route_profile: RouteProfile = SAFE_ROUTE_PROFILE,
    execution_unit: ExecutionUnitV1 | None = None,
) -> Work:
    if classification.blocked or classification.budget is None:
        raise ValueError("blocked classification cannot create a Work")
    resolved_kind = kind or classification.container_kind
    work = Work(
        schema_version=WORK_SCHEMA_VERSION,
        work_id=work_id,
        project_id=project_id,
        kind=resolved_kind,
        objective=objective,
        status="planned",
        request_ref=request_ref,
        request_confirmed=True,
        phase_ref=phase_ref,
        risk_profile=classification.risk_profile,
        risk_reason_codes=classification.reason_codes,
        required_gates=classification.required_gates,
        route_profile=route_profile,
        scope=scope,
        budget=classification.budget,
        usage_ref=f"works/{work_id}/USAGE.json",
        release_base_oid=release_base_oid,
        process_base_oid=process_base_oid,
        execution_unit=execution_unit,
    )
    findings = validate_work_payload(work.as_dict())
    if findings:
        raise ValueError("; ".join(finding.message for finding in findings))
    return work


def work_path(process_root: Path, work_id: str) -> Path:
    if not _ID_RE.fullmatch(work_id):
        raise ValueError("work_id must use 1-64 safe ID characters")
    return process_root.resolve() / "works" / work_id / "WORK.yaml"


def load_work(
    process_root: Path,
    work_id: str,
    *,
    read_context: ReadContextProtocol | None = None,
) -> Work:
    path = work_path(process_root, work_id)
    logical_ref = f"works/{work_id}/WORK.yaml"
    if read_context is None:
        payload = load_yaml_object(path)
        byte_size = path.stat().st_size
    else:
        payload = read_context.read_yaml_object(
            logical_ref,
            loader=load_yaml_object,
        )
        byte_size = read_context.byte_size(logical_ref)
    payload, _compatibility = normalize_legacy_work_payload(payload)
    findings = validate_work_payload(payload, byte_size=byte_size)
    if findings:
        raise ValueError("; ".join(finding.message for finding in findings))
    return work_from_payload(payload)


def normalize_legacy_work_payload(
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """只读适配已知 schema-v1 ``completed_at``，不改写历史 bytes。"""

    normalized = dict(payload)
    reasons: list[str] = []
    if "completed_at" not in normalized:
        return normalized, ()
    completed_at = normalized.get("completed_at")
    if normalized.get("schema_version") != WORK_SCHEMA_VERSION:
        raise ValueError("legacy completed_at is only supported for Work schema_version 1")
    if normalized.get("status") not in {"completed", "cancelled", "archived"}:
        raise ValueError("legacy completed_at is only valid on a terminal Work")
    if not isinstance(completed_at, str) or not completed_at.strip():
        raise ValueError("legacy completed_at must be a non-empty string")
    updated_at = normalized.get("updated_at")
    if updated_at not in (None, "") and updated_at != completed_at:
        reasons.append("LEGACY_COMPLETED_AT_PRESERVED_BY_EXISTING_UPDATED_AT")
    elif not updated_at:
        normalized["updated_at"] = completed_at
        reasons.append("LEGACY_COMPLETED_AT_MAPPED_TO_UPDATED_AT")
    normalized.pop("completed_at", None)
    reasons.append("LEGACY_COMPLETED_AT_READ_COMPATIBILITY")
    return normalized, tuple(reasons)


def write_work_create_only(process_root: Path, work: Work) -> Path:
    path = work_path(process_root, work.work_id)
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"WORK.yaml already exists: {path}")
    findings = validate_work_payload(work.as_dict())
    if findings:
        raise ValueError("; ".join(finding.message for finding in findings))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(dump_yaml(work.as_dict()) + "\n")
    return path


def with_status(work: Work, status: str, *, result_ref: str = "") -> Work:
    updated = replace(work, status=status, result_ref=result_ref or work.result_ref)
    findings = validate_work_payload(updated.as_dict())
    if findings:
        raise ValueError("; ".join(finding.message for finding in findings))
    return updated
