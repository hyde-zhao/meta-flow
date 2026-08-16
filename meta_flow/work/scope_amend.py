"""Append-only Work scope amendment planning and recoverable apply."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Any

from meta_flow.execution_control.contract import canonical_digest
from meta_flow.execution_control.runtime_context import (
    build_execution_control_context,
    target_preimage_digest,
)
from meta_flow.project.process_route import require_process_route
from meta_flow.project.scale import dump_yaml
from meta_flow.work.init_transaction import (
    apply_work_init_transaction_targets,
    begin_work_init_transaction,
    build_transaction_target,
    commit_work_init_transaction,
    rollback_work_init_transaction,
)
from meta_flow.work.model import (
    PredecessorInventoryReceiptV1,
    ScopeAmendPlanV1,
    ScopeDeltaV1,
    Work,
    WorkRevisionV2,
    apply_scope_amend,
    load_work,
    plan_scope_amend,
)
from meta_flow.work.production_validation import (
    ProductionValidationV1,
    validate_production_write_plan,
)
from meta_flow.work.scope import WorkScope
from meta_flow.workflow.cr_index import (
    load_terminal_predecessor_inventory,
    rebuild_scope_amend_index,
)

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True)
class ScopeAmendAuthorizationV1:
    schema_version: int
    operation: str
    authorization_id: str
    cr_id: str
    work_id: str
    predecessor_revision_id: str
    successor_revision_id: str
    predecessor_revision_bytes_digest: str
    authorized_leaves: tuple[str, ...]
    effective_at: str

    def __post_init__(self) -> None:
        if (
            self.schema_version != 1
            or self.operation != "work.scope-amend"
            or not all(
                _ID_RE.fullmatch(value)
                for value in (
                    self.authorization_id,
                    self.cr_id,
                    self.work_id,
                    self.predecessor_revision_id,
                    self.successor_revision_id,
                )
            )
            or not _DIGEST_RE.fullmatch(self.predecessor_revision_bytes_digest)
            or tuple(sorted(set(self.authorized_leaves))) != self.authorized_leaves
            or any(
                not item
                or item.startswith("/")
                or "\\" in item
                or ".." in Path(item).parts
                for item in self.authorized_leaves
            )
            or not self.effective_at
        ):
            raise ValueError("scope amendment authorization is invalid")

    @property
    def digest(self) -> str:
        return canonical_digest(self.as_dict())

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "operation": self.operation,
            "authorization_id": self.authorization_id,
            "cr_id": self.cr_id,
            "work_id": self.work_id,
            "predecessor_revision_id": self.predecessor_revision_id,
            "successor_revision_id": self.successor_revision_id,
            "predecessor_revision_bytes_digest": self.predecessor_revision_bytes_digest,
            "authorized_leaves": list(self.authorized_leaves),
            "effective_at": self.effective_at,
        }

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> ScopeAmendAuthorizationV1:
        expected = {
            "schema_version",
            "operation",
            "authorization_id",
            "cr_id",
            "work_id",
            "predecessor_revision_id",
            "successor_revision_id",
            "predecessor_revision_bytes_digest",
            "authorized_leaves",
            "effective_at",
        }
        if set(payload) != expected or not isinstance(payload["authorized_leaves"], list):
            raise ValueError("scope amendment authorization fields mismatch")
        return cls(
            payload["schema_version"],
            payload["operation"],
            payload["authorization_id"],
            payload["cr_id"],
            payload["work_id"],
            payload["predecessor_revision_id"],
            payload["successor_revision_id"],
            payload["predecessor_revision_bytes_digest"],
            tuple(payload["authorized_leaves"]),
            payload["effective_at"],
        )


@dataclass(frozen=True)
class ScopeAmendTransactionPlanV1:
    release_root: Path
    process_root: Path
    work: Work
    successor_work: Work
    authorization: ScopeAmendAuthorizationV1
    delta: ScopeDeltaV1
    predecessor: PredecessorInventoryReceiptV1
    core_plan: ScopeAmendPlanV1
    validation: ProductionValidationV1
    target_preimages: tuple[tuple[str, str], ...]
    target_postimages: tuple[tuple[str, bytes], ...]
    revision: WorkRevisionV2
    receipt_payload: dict[str, object]
    operation: str

    @property
    def plan_digest(self) -> str:
        return self.core_plan.plan_digest

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "decision": "READY",
            "operation": self.operation,
            "cr_id": self.authorization.cr_id,
            "work_id": self.work.work_id,
            "predecessor_revision_id": self.predecessor.predecessor_revision_id,
            "successor_revision_id": self.core_plan.revision_id,
            "scope_digest": self.core_plan.scope_digest,
            "plan_digest": self.plan_digest,
            "target_preimages": dict(self.target_preimages),
            "target_postimage_digests": {
                ref: canonical_digest({"bytes_sha256": _bytes_digest(value)})
                for ref, value in self.target_postimages
            },
            "invalidated_refs": list(self.core_plan.invalidated_refs),
            "validation": self.validation.as_dict(),
            "mutation_count": 0,
        }


def load_scope_amend_authorization(path: Path) -> ScopeAmendAuthorizationV1:
    if path.is_symlink() or not path.is_file():
        raise ValueError("scope amendment authorization path is unsafe")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("scope amendment authorization is unreadable") from exc
    if not isinstance(payload, dict):
        raise ValueError("scope amendment authorization must be an object")
    return ScopeAmendAuthorizationV1.from_mapping(payload)


def admit_scope_amend_predecessor(
    authorization: ScopeAmendAuthorizationV1,
    predecessor_receipts: list[dict[str, Any]],
) -> PredecessorInventoryReceiptV1:
    """Run mandatory BL-001 admission before any delta normalization."""

    expected_inventory_digest = str(
        next(
            (
                item.get("inventory_digest")
                for item in predecessor_receipts
                if item.get("cr_id") == authorization.cr_id
                and item.get("predecessor_revision_id")
                == authorization.predecessor_revision_id
            ),
            "",
        )
    )
    raw_receipt = load_terminal_predecessor_inventory(
        predecessor_receipts,
        cr_id=authorization.cr_id,
        predecessor_revision_id=authorization.predecessor_revision_id,
        expected_digest=expected_inventory_digest,
        expected_revision_bytes_digest=authorization.predecessor_revision_bytes_digest,
    )
    return PredecessorInventoryReceiptV1(
        cr_id=raw_receipt["cr_id"],
        predecessor_revision_id=raw_receipt["predecessor_revision_id"],
        terminal_status=raw_receipt["terminal_status"],
        inventory=tuple(raw_receipt["inventory"]),
        inventory_digest=raw_receipt["inventory_digest"],
        revision_bytes_digest=raw_receipt["revision_bytes_digest"],
    )


def plan_scope_amend_from_release_root(
    release_root: Path,
    *,
    authorization: ScopeAmendAuthorizationV1,
    delta: ScopeDeltaV1,
    predecessor_receipts: list[dict[str, Any]],
    operation: str = "plan",
) -> ScopeAmendTransactionPlanV1:
    if operation not in {"plan", "apply"}:
        raise ValueError("scope amendment operation must be plan or apply")
    root = release_root.resolve()
    route = require_process_route(root)
    process_root = route.process_root
    work = load_work(process_root, authorization.work_id)
    if work.project_id != route.project_id or work.kind != "cr":
        raise ValueError("scope amendment Work/CR identity mismatch")
    if authorization.successor_revision_id == authorization.predecessor_revision_id:
        raise ValueError("scope amendment successor must differ from predecessor")
    predecessor = admit_scope_amend_predecessor(
        authorization,
        predecessor_receipts,
    )

    current_scope = tuple(
        sorted(
            set(
                work.scope.allowed_reads
                + work.scope.allowed_writes
                + work.scope.required_checks
            )
        )
    )
    result_scope = _result_work_scope(work.scope, delta)
    if (
        len(result_scope.allowed_reads) > work.budget.reads
        or len(result_scope.allowed_writes) > work.budget.writes
        or len(result_scope.required_checks) > work.budget.check_groups
    ):
        raise ValueError("scope amendment exceeds Work budget")
    successor_work = replace(
        work,
        scope=result_scope,
        updated_at=authorization.effective_at,
    )
    invalidated_refs = tuple(
        sorted(
            {
                *(filter(None, (work.result_ref,))),
                f"works/{work.work_id}/HANDOFF.yaml",
                f"works/{work.work_id}/validation-receipts",
            }
        )
    )
    revision_ref = (
        f"works/{work.work_id}/revisions/{authorization.successor_revision_id}.json"
    )
    receipt_ref = (
        f"works/{work.work_id}/scope-amendments/"
        f"{authorization.successor_revision_id}.receipt.json"
    )
    write_refs = tuple(sorted((work.work_ref, revision_ref, receipt_ref)))
    target_preimages = tuple(
        (ref, target_preimage_digest(process_root / ref)) for ref in write_refs
    )
    if any(
        ref != work.work_ref
        and ((process_root / ref).exists() or (process_root / ref).is_symlink())
        for ref in write_refs
    ):
        raise ValueError("scope amendment successor targets must be create-only")

    context = build_execution_control_context(root, work, operation=operation)
    validation = validate_production_write_plan(
        operation="scope-amend-plan" if operation == "plan" else "scope-amend-apply",
        process_root=process_root,
        release_oid=context.release_oid,
        process_oid=context.process_oid,
        dirty_inventory_digest=context.dirty_path_digest,
        dirty_owned=context.decision == "READY",
        owner_id=work.work_id,
        wave_id="scope-amend",
        merge_order=0,
        write_refs=write_refs,
        target_preimages=target_preimages,
        scope_digest=result_scope.digest,
        budget_digest=canonical_digest(work.budget.as_dict()),
        authorization_digest=authorization.digest,
        resolver_identity=context.route_digest,
        policy_identity=context.policy_digest,
        risk_class=work.risk_profile,
        dependency_receipt_status="PASS",
        execution_context_status=context.decision,
    )
    if not validation.passed:
        raise ValueError("scope amendment validation graph is blocked")
    snapshot_bindings = tuple(
        sorted(
            {
                "release_oid": context.release_oid,
                "process_oid": context.process_oid,
                "dirty_inventory_digest": context.dirty_path_digest,
                "predecessor_inventory_digest": predecessor.inventory_digest,
                "predecessor_revision_bytes_digest": predecessor.revision_bytes_digest,
                "authorization_digest": authorization.digest,
                "validation_graph_digest": validation.graph.graph_digest,
                **{f"preimage:{ref}": digest for ref, digest in target_preimages},
            }.items()
        )
    )
    core_plan = plan_scope_amend(
        revision_id=authorization.successor_revision_id,
        current_scope=current_scope,
        delta=delta,
        authorized_leaves=authorization.authorized_leaves,
        predecessor=predecessor,
        snapshot_digest=validation.snapshot.source_digest,
        cr_id=authorization.cr_id,
        work_id=authorization.work_id,
        authorization_digest=authorization.digest,
        envelope_digest=validation.envelope_digest,
        validation_graph_digest=validation.graph.graph_digest,
        snapshot_bindings=snapshot_bindings,
        invalidated_refs=invalidated_refs,
    )
    result = apply_scope_amend(
        core_plan,
        fresh_snapshot_digest=validation.snapshot.source_digest,
        fresh_snapshot_bindings=snapshot_bindings,
    )
    revision = result.get("revision")
    if result["decision"] != "READY" or not isinstance(revision, WorkRevisionV2):
        raise ValueError("scope amendment successor revision was not admitted")
    receipt_payload = {
        "schema_version": 1,
        "kind": "ScopeAmendReceiptV1",
        "decision": "PASS",
        "cr_id": authorization.cr_id,
        "work_id": authorization.work_id,
        "predecessor_revision_id": predecessor.predecessor_revision_id,
        "successor_revision_id": revision.revision_id,
        "scope_digest": revision.scope_digest,
        "plan_digest": core_plan.plan_digest,
        "authorization_digest": authorization.digest,
        "validation_graph_digest": validation.graph.graph_digest,
        "invalidated_refs": list(invalidated_refs),
        "derived_index": rebuild_scope_amend_index(revision.as_dict()),
        "mutation_count": 3,
    }
    target_postimages = tuple(
        sorted(
            (
                (work.work_ref, (dump_yaml(successor_work.as_dict()) + "\n").encode("utf-8")),
                (revision_ref, _json_bytes(revision.as_dict())),
                (receipt_ref, _json_bytes(receipt_payload)),
            )
        )
    )
    return ScopeAmendTransactionPlanV1(
        root,
        process_root,
        work,
        successor_work,
        authorization,
        delta,
        predecessor,
        core_plan,
        validation,
        target_preimages,
        target_postimages,
        revision,
        receipt_payload,
        operation,
    )


def apply_scope_amend_transaction(
    plan: ScopeAmendTransactionPlanV1,
    *,
    expected_plan_digest: str,
    predecessor_receipts: list[dict[str, Any]],
) -> dict[str, object]:
    if not _DIGEST_RE.fullmatch(expected_plan_digest) or expected_plan_digest != plan.plan_digest:
        return {
            "decision": "BLOCKED",
            "reason_code": "PLAN_DIGEST_MISMATCH",
            "mutation_count": 0,
        }
    try:
        fresh = plan_scope_amend_from_release_root(
            plan.release_root,
            authorization=plan.authorization,
            delta=plan.delta,
            predecessor_receipts=predecessor_receipts,
            operation="apply",
        )
    except (OSError, ValueError):
        return {
            "decision": "REPLAN_REQUIRED",
            "reason_code": "FRESH_VALIDATION_FAILED",
            "mutation_count": 0,
        }
    if (
        fresh.plan_digest != plan.plan_digest
        or fresh.target_preimages != plan.target_preimages
        or fresh.validation.graph.graph_digest != plan.validation.graph.graph_digest
        or fresh.target_postimages != plan.target_postimages
    ):
        return {
            "decision": "REPLAN_REQUIRED",
            "reason_code": "SNAPSHOT_DRIFT",
            "mutation_count": 0,
        }
    targets = tuple(
        build_transaction_target(fresh.process_root, ref=ref, after_bytes=value)
        for ref, value in fresh.target_postimages
    )
    transaction_id = begin_work_init_transaction(
        fresh.process_root,
        operation="work.scope-amend",
        work_id=fresh.work.work_id,
        plan_digest=fresh.plan_digest,
        release_oid=fresh.validation.snapshot.release_oid,
        process_oid=fresh.validation.snapshot.process_oid,
        targets=targets,
    )
    try:
        applied_refs = apply_work_init_transaction_targets(
            fresh.process_root,
            transaction_id,
        )
        for ref, expected in fresh.target_postimages:
            if (fresh.process_root / ref).read_bytes() != expected:
                raise ValueError("scope amendment transaction postimage drift")
        transaction = commit_work_init_transaction(
            fresh.process_root,
            transaction_id,
            successor_id=fresh.revision.revision_id,
        )
    except Exception as exc:
        recovery = rollback_work_init_transaction(
            fresh.process_root,
            transaction_id,
            failure=str(exc),
        )
        if recovery.recovery_required:
            raise ValueError("scope amendment transaction recovery failed") from exc
        return {
            "decision": "REPLAN_REQUIRED",
            "reason_code": "TRANSACTION_RECOVERED",
            "mutation_count": 0,
        }
    return {
        "decision": "PASS",
        "plan_digest": fresh.plan_digest,
        "transaction_id": transaction.transaction_id,
        "transaction_state": "COMMITTED",
        "revision_ref": next(
            ref for ref in applied_refs if "/revisions/" in ref
        ),
        "receipt_ref": next(
            ref for ref in applied_refs if "/scope-amendments/" in ref
        ),
        "work_ref": fresh.work.work_ref,
        "invalidated_refs": list(fresh.core_plan.invalidated_refs),
        "derived_index": fresh.receipt_payload["derived_index"],
        "mutation_count": len(applied_refs),
    }


def _result_work_scope(current: WorkScope, delta: ScopeDeltaV1) -> WorkScope:
    return WorkScope(
        current.version,
        tuple(
            sorted(
                set(current.allowed_reads)
                | set(delta.add_story_ids)
                | set(delta.add_dependency_edges)
                | set(delta.add_acceptance_refs)
            )
        ),
        tuple(sorted(set(current.allowed_writes) | set(delta.add_owned_leaves))),
        current.required_checks,
    )


def _json_bytes(payload: dict[str, object]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _bytes_digest(value: bytes) -> str:
    return sha256(value).hexdigest()


__all__ = [
    "ScopeAmendAuthorizationV1",
    "ScopeAmendTransactionPlanV1",
    "admit_scope_amend_predecessor",
    "apply_scope_amend_transaction",
    "load_scope_amend_authorization",
    "plan_scope_amend_from_release_root",
]
