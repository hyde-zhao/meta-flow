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
from meta_flow.state.event_ledger import validate_exact_checkpoint_approval_binding
from meta_flow.work.init_transaction import (
    apply_work_init_transaction_targets,
    begin_work_init_transaction,
    build_transaction_target,
    commit_work_init_transaction,
    inspect_work_init_transactions,
    recover_work_init_transaction,
    rollback_work_init_transaction,
)
from meta_flow.work.lifecycle_transaction import (
    STATE_PROJECTION_REFS,
    acquire_shared_projection_writer_lock,
    assert_work_close_shared_projection_lineage,
    build_state_projection_candidates,
    refresh_state_projection_if_initialized,
    release_shared_projection_writer_lock,
)
from meta_flow.work.model import (
    G1ScopeDeltaV1,
    PredecessorInventoryReceiptV1,
    ScopeAmendPlanV1,
    ScopeDeltaV1,
    Work,
    WorkRevisionV2,
    WorkRevisionV3,
    WorkScopeRevisionV2,
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
from meta_flow.workspace.git_sync import run_git

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
                not item or item.startswith("/") or "\\" in item or ".." in Path(item).parts
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
class ScopeAmendAuthorizationV2:
    """V2 binds one objective replacement into the same successor transaction."""

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
    predecessor_objective: str
    replacement_objective: str

    def __post_init__(self) -> None:
        if (
            self.schema_version != 2
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
                not item or item.startswith("/") or "\\" in item or ".." in Path(item).parts
                for item in self.authorized_leaves
            )
            or not self.effective_at
            or not self.predecessor_objective.strip()
            or not self.replacement_objective.strip()
            or self.predecessor_objective == self.replacement_objective
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
            "predecessor_objective": self.predecessor_objective,
            "replacement_objective": self.replacement_objective,
        }

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> ScopeAmendAuthorizationV2:
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
            "predecessor_objective",
            "replacement_objective",
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
            payload["predecessor_objective"],
            payload["replacement_objective"],
        )


ScopeAmendAuthorization = ScopeAmendAuthorizationV1 | ScopeAmendAuthorizationV2


@dataclass(frozen=True)
class ScopeAmendTransactionPlanV1:
    release_root: Path
    process_root: Path
    work: Work
    successor_work: Work
    authorization: ScopeAmendAuthorization
    delta: ScopeDeltaV1
    predecessor: PredecessorInventoryReceiptV1
    core_plan: ScopeAmendPlanV1
    validation: ProductionValidationV1
    target_preimages: tuple[tuple[str, str], ...]
    projection_preimages: tuple[tuple[str, str], ...]
    target_postimages: tuple[tuple[str, bytes], ...]
    revision: WorkRevisionV2 | WorkRevisionV3
    receipt_payload: dict[str, object]
    operation: str

    @property
    def plan_digest(self) -> str:
        return self.core_plan.plan_digest

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
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
            "projection_preimages": dict(self.projection_preimages),
            "target_postimage_digests": {
                ref: canonical_digest({"bytes_sha256": _bytes_digest(value)})
                for ref, value in self.target_postimages
            },
            "invalidated_refs": list(self.core_plan.invalidated_refs),
            "validation": self.validation.as_dict(),
            "mutation_count": 0,
        }
        if isinstance(self.authorization, ScopeAmendAuthorizationV2):
            payload["objective_transition"] = {
                "previous": self.authorization.predecessor_objective,
                "replacement": self.authorization.replacement_objective,
            }
        return payload


def load_scope_amend_authorization(path: Path) -> ScopeAmendAuthorization:
    if path.is_symlink() or not path.is_file():
        raise ValueError("scope amendment authorization path is unsafe")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("scope amendment authorization is unreadable") from exc
    if not isinstance(payload, dict):
        raise ValueError("scope amendment authorization must be an object")
    if payload.get("schema_version") == 1:
        return ScopeAmendAuthorizationV1.from_mapping(payload)
    if payload.get("schema_version") == 2:
        return ScopeAmendAuthorizationV2.from_mapping(payload)
    raise ValueError("scope amendment authorization version is invalid")


def admit_scope_amend_predecessor(
    authorization: ScopeAmendAuthorization,
    predecessor_receipts: list[dict[str, Any]],
) -> PredecessorInventoryReceiptV1:
    """Run mandatory BL-001 admission before any delta normalization."""

    expected_inventory_digest = str(
        next(
            (
                item.get("inventory_digest")
                for item in predecessor_receipts
                if item.get("cr_id") == authorization.cr_id
                and item.get("predecessor_revision_id") == authorization.predecessor_revision_id
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
    authorization: ScopeAmendAuthorization,
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
    if (
        isinstance(authorization, ScopeAmendAuthorizationV2)
        and authorization.predecessor_objective != work.objective
    ):
        raise ValueError("scope amendment predecessor objective drifted")
    predecessor = admit_scope_amend_predecessor(
        authorization,
        predecessor_receipts,
    )

    current_scope = tuple(
        sorted(
            set(work.scope.allowed_reads + work.scope.allowed_writes + work.scope.required_checks)
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
        objective=(
            authorization.replacement_objective
            if isinstance(authorization, ScopeAmendAuthorizationV2)
            else work.objective
        ),
        scope=result_scope,
        updated_at=authorization.effective_at,
    )
    successor_work_bytes = (dump_yaml(successor_work.as_dict()) + "\n").encode("utf-8")
    # Scope amendment changes the canonical Work bytes even though the active Work
    # identity is stable.  That bytes change is part of formal truth and therefore
    # changes the projection source digest.  Prove the State post-image can be built
    # during both plan and apply, and bind its current preimages into the plan.
    projection_candidates = build_state_projection_candidates(
        process_root,
        object_overrides={
            "process/" + work.work_ref: (
                successor_work.as_dict(),
                successor_work_bytes,
            )
        },
    )
    projection_preimages = tuple(
        (ref, target_preimage_digest(process_root / ref))
        for ref, _candidate in projection_candidates
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
    revision_ref = f"works/{work.work_id}/revisions/{authorization.successor_revision_id}.json"
    receipt_ref = (
        f"works/{work.work_id}/scope-amendments/{authorization.successor_revision_id}.receipt.json"
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
                **{f"projection_preimage:{ref}": digest for ref, digest in projection_preimages},
                **(
                    {
                        "predecessor_objective_digest": canonical_digest(
                            {"objective": authorization.predecessor_objective}
                        ),
                        "replacement_objective_digest": canonical_digest(
                            {"objective": authorization.replacement_objective}
                        ),
                    }
                    if isinstance(authorization, ScopeAmendAuthorizationV2)
                    else {}
                ),
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
        previous_objective=(
            authorization.predecessor_objective
            if isinstance(authorization, ScopeAmendAuthorizationV2)
            else ""
        ),
        result_objective=(
            authorization.replacement_objective
            if isinstance(authorization, ScopeAmendAuthorizationV2)
            else ""
        ),
    )
    result = apply_scope_amend(
        core_plan,
        fresh_snapshot_digest=validation.snapshot.source_digest,
        fresh_snapshot_bindings=snapshot_bindings,
    )
    revision = result.get("revision")
    if result["decision"] != "READY" or not isinstance(
        revision,
        (WorkRevisionV2, WorkRevisionV3),
    ):
        raise ValueError("scope amendment successor revision was not admitted")
    objective_amendment = isinstance(authorization, ScopeAmendAuthorizationV2)
    receipt_payload: dict[str, object] = {
        "schema_version": 2 if objective_amendment else 1,
        "kind": "ScopeAmendReceiptV2" if objective_amendment else "ScopeAmendReceiptV1",
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
    if objective_amendment:
        receipt_payload["previous_objective"] = authorization.predecessor_objective
        receipt_payload["objective"] = authorization.replacement_objective
    target_postimages = tuple(
        sorted(
            (
                (work.work_ref, successor_work_bytes),
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
        projection_preimages,
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
    writer_id = (
        "scope-amend-"
        + sha256(plan.authorization.authorization_id.encode("utf-8")).hexdigest()[:32]
    )
    try:
        shared_lock = acquire_shared_projection_writer_lock(
            plan.process_root,
            writer_id,
        )
    except (OSError, ValueError):
        return {
            "decision": "REPLAN_REQUIRED",
            "reason_code": "SHARED_PROJECTION_LOCK_UNAVAILABLE",
            "mutation_count": 0,
        }

    transaction_id = ""
    domain_applied = False
    fresh: ScopeAmendTransactionPlanV1 | None = None
    try:
        assert_work_close_shared_projection_lineage(plan.process_root)
        fresh = plan_scope_amend_from_release_root(
            plan.release_root,
            authorization=plan.authorization,
            delta=plan.delta,
            predecessor_receipts=predecessor_receipts,
            operation="apply",
        )
        if (
            fresh.plan_digest != plan.plan_digest
            or fresh.target_preimages != plan.target_preimages
            or fresh.projection_preimages != plan.projection_preimages
            or fresh.validation.graph.graph_digest != plan.validation.graph.graph_digest
            or fresh.target_postimages != plan.target_postimages
        ):
            return {
                "decision": "REPLAN_REQUIRED",
                "reason_code": "SNAPSHOT_DRIFT",
                "mutation_count": 0,
            }
        if any(
            target_preimage_digest(fresh.process_root / ref) != digest
            for ref, digest in fresh.projection_preimages
        ):
            return {
                "decision": "REPLAN_REQUIRED",
                "reason_code": "PROJECTION_PREIMAGE_DRIFT",
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
        applied_refs = apply_work_init_transaction_targets(
            fresh.process_root,
            transaction_id,
        )
        domain_applied = True
        for ref, expected in fresh.target_postimages:
            if (fresh.process_root / ref).read_bytes() != expected:
                raise ValueError("scope amendment transaction postimage drift")
        refreshed_refs = refresh_state_projection_if_initialized(fresh.process_root)
        _validate_scope_amend_postimage(fresh)
        transaction = commit_work_init_transaction(
            fresh.process_root,
            transaction_id,
            successor_id=fresh.revision.revision_id,
        )
    except Exception as exc:
        if not transaction_id or fresh is None:
            return {
                "decision": "REPLAN_REQUIRED",
                "reason_code": "FRESH_VALIDATION_FAILED",
                "mutation_count": 0,
            }
        recovery = rollback_work_init_transaction(
            fresh.process_root,
            transaction_id,
            failure=str(exc),
        )
        if recovery.recovery_required:
            raise ValueError("scope amendment transaction recovery failed") from exc
        # 即使 State writer 在完成持久化后才抛错，赋值语句也不会留下成功
        # 标志。因此只要领域目标曾落盘且 State 已初始化，就在领域回滚后
        # 无条件用同一原生 owner 收敛回旧 formal truth。
        if domain_applied and fresh.projection_preimages:
            try:
                refresh_state_projection_if_initialized(fresh.process_root)
            except Exception as recovery_exc:
                raise ValueError("scope amendment State recovery failed") from recovery_exc
        return {
            "decision": "REPLAN_REQUIRED",
            "reason_code": "TRANSACTION_RECOVERED",
            "mutation_count": 0,
        }
    finally:
        release_shared_projection_writer_lock(shared_lock, writer_id)
    return {
        "decision": "PASS",
        "plan_digest": fresh.plan_digest,
        "transaction_id": transaction.transaction_id,
        "transaction_state": "COMMITTED",
        "revision_ref": next(ref for ref in applied_refs if "/revisions/" in ref),
        "receipt_ref": next(ref for ref in applied_refs if "/scope-amendments/" in ref),
        "work_ref": fresh.work.work_ref,
        "invalidated_refs": list(fresh.core_plan.invalidated_refs),
        "derived_index": fresh.receipt_payload["derived_index"],
        "domain_mutation_count": len(applied_refs),
        "coordination_mutation_count": len(refreshed_refs),
        "mutation_count": len(applied_refs) + len(refreshed_refs),
    }


def _validate_scope_amend_postimage(plan: ScopeAmendTransactionPlanV1) -> None:
    """成功返回前证明 State/CURRENT 已消费新的 Work bytes。"""

    state_paths = [plan.process_root / ref for ref in STATE_PROJECTION_REFS]
    present = [path.is_file() and not path.is_symlink() for path in state_paths]
    if not any(present):
        return
    if not all(present):
        raise ValueError("scope amendment State projection target set is incomplete")

    from meta_flow.state import current as state_current
    from meta_flow.state.formal_projection import (
        build_formal_truth_snapshot,
        derive_formal_truth_patch,
    )

    state = state_current.load_current_state(plan.release_root)
    snapshot = build_formal_truth_snapshot(
        plan.release_root,
        process_root=plan.process_root,
    )
    patch = derive_formal_truth_patch(state, snapshot)
    if state.get("formal_truth_projection") != snapshot or any(
        state.get(field) != patch[field]
        for field in ("current_phase", "active_change", "blocked", "next_action")
    ):
        raise ValueError("scope amendment State formal truth postimage is stale")
    findings = state_current.validate_current_projection(plan.release_root)
    if findings:
        raise ValueError(
            "scope amendment CURRENT postimage is stale: "
            + "; ".join(item.message for item in findings)
        )


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
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _bytes_digest(value: bytes) -> str:
    return sha256(value).hexdigest()


@dataclass(frozen=True)
class G1ScopeAmendAuthorizationV1:
    schema_version: int
    operation: str
    authorization_id: str
    work_id: str
    successor_revision_id: str
    release_oid: str
    process_oid: str
    release_dirty_digest: str
    process_dirty_digest: str
    work_preimage_digest: str
    delta_digest: str
    issued_at: str

    def __post_init__(self) -> None:
        if (
            self.schema_version != 1
            or self.operation != "work.scope-amend.g1"
            or not all(
                _ID_RE.fullmatch(value)
                for value in (
                    self.authorization_id,
                    self.work_id,
                    self.successor_revision_id,
                )
            )
            or not re.fullmatch(r"[0-9a-f]{40}", self.release_oid)
            or not re.fullmatch(r"[0-9a-f]{40}", self.process_oid)
            or not _DIGEST_RE.fullmatch(self.release_dirty_digest)
            or not _DIGEST_RE.fullmatch(self.process_dirty_digest)
            or not _DIGEST_RE.fullmatch(self.work_preimage_digest)
            or not _DIGEST_RE.fullmatch(self.delta_digest)
            or not self.issued_at
        ):
            raise ValueError("G1_SCOPE_AMEND_AUTHORIZATION_INVALID")

    @property
    def digest(self) -> str:
        return canonical_digest(self.as_dict())

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "operation": self.operation,
            "authorization_id": self.authorization_id,
            "work_id": self.work_id,
            "successor_revision_id": self.successor_revision_id,
            "release_oid": self.release_oid,
            "process_oid": self.process_oid,
            "release_dirty_digest": self.release_dirty_digest,
            "process_dirty_digest": self.process_dirty_digest,
            "work_preimage_digest": self.work_preimage_digest,
            "delta_digest": self.delta_digest,
            "issued_at": self.issued_at,
        }

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> G1ScopeAmendAuthorizationV1:
        expected = {
            "schema_version",
            "operation",
            "authorization_id",
            "work_id",
            "successor_revision_id",
            "release_oid",
            "process_oid",
            "release_dirty_digest",
            "process_dirty_digest",
            "work_preimage_digest",
            "delta_digest",
            "issued_at",
        }
        if set(payload) != expected:
            raise ValueError("G1_SCOPE_AMEND_AUTHORIZATION_FIELDS_INVALID")
        return cls(**payload)


@dataclass(frozen=True)
class G2CurrentCRScopeAmendAuthorizationV2:
    """为 G2 当前 CR Work 冻结一次 add-only successor 授权。"""

    schema_version: int
    operation: str
    authorization_id: str
    cr_id: str
    work_id: str
    successor_revision_id: str
    release_oid: str
    process_oid: str
    release_dirty_digest: str
    process_dirty_digest: str
    work_preimage_digest: str
    predecessor_scope_digest: str
    delta_digest: str
    authorized_add_writes: tuple[str, ...]
    invalidation_refs: tuple[str, ...]
    checkpoint_ref: str
    checkpoint_digest: str
    approval_event_id: str
    approval_event_digest: str
    approval_decision_id: str
    issued_at: str

    def __post_init__(self) -> None:
        ids = (
            self.authorization_id,
            self.cr_id,
            self.work_id,
            self.successor_revision_id,
            self.approval_event_id,
            self.approval_decision_id,
        )
        if (
            self.schema_version != 2
            or self.operation != "work.scope-amend.current-cr.g2"
            or not all(_ID_RE.fullmatch(value) for value in ids)
            or not re.fullmatch(r"[0-9a-f]{40}", self.release_oid)
            or not re.fullmatch(r"[0-9a-f]{40}", self.process_oid)
            or any(
                not _DIGEST_RE.fullmatch(value)
                for value in (
                    self.release_dirty_digest,
                    self.process_dirty_digest,
                    self.work_preimage_digest,
                    self.predecessor_scope_digest,
                    self.delta_digest,
                    self.checkpoint_digest,
                    self.approval_event_digest,
                )
            )
            or not self.authorized_add_writes
            or tuple(sorted(set(self.authorized_add_writes)))
            != self.authorized_add_writes
            or not self.invalidation_refs
            or tuple(sorted(set(self.invalidation_refs))) != self.invalidation_refs
            or any(
                not value
                or value.startswith("/")
                or "\\" in value
                or any(part in {"", ".", ".."} for part in value.split("/"))
                or any(marker in value for marker in ("*", "?", "["))
                for value in self.authorized_add_writes
            )
            or any(
                not value
                or value.startswith("/")
                or "\\" in value
                or any(part in {"", ".", ".."} for part in value.split("/"))
                for value in self.invalidation_refs
            )
            or not self.checkpoint_ref.startswith("process/checkpoints/")
            or self.checkpoint_ref.startswith("/")
            or "\\" in self.checkpoint_ref
            or ".." in Path(self.checkpoint_ref).parts
            or not self.issued_at
        ):
            raise ValueError("G2_CURRENT_CR_SCOPE_AMEND_AUTHORIZATION_INVALID")

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
            "successor_revision_id": self.successor_revision_id,
            "release_oid": self.release_oid,
            "process_oid": self.process_oid,
            "release_dirty_digest": self.release_dirty_digest,
            "process_dirty_digest": self.process_dirty_digest,
            "work_preimage_digest": self.work_preimage_digest,
            "predecessor_scope_digest": self.predecessor_scope_digest,
            "delta_digest": self.delta_digest,
            "authorized_add_writes": list(self.authorized_add_writes),
            "invalidation_refs": list(self.invalidation_refs),
            "checkpoint_ref": self.checkpoint_ref,
            "checkpoint_digest": self.checkpoint_digest,
            "approval_event_id": self.approval_event_id,
            "approval_event_digest": self.approval_event_digest,
            "approval_decision_id": self.approval_decision_id,
            "issued_at": self.issued_at,
        }

    @classmethod
    def from_mapping(
        cls,
        payload: dict[str, Any],
    ) -> G2CurrentCRScopeAmendAuthorizationV2:
        expected = {
            "schema_version",
            "operation",
            "authorization_id",
            "cr_id",
            "work_id",
            "successor_revision_id",
            "release_oid",
            "process_oid",
            "release_dirty_digest",
            "process_dirty_digest",
            "work_preimage_digest",
            "predecessor_scope_digest",
            "delta_digest",
            "authorized_add_writes",
            "invalidation_refs",
            "checkpoint_ref",
            "checkpoint_digest",
            "approval_event_id",
            "approval_event_digest",
            "approval_decision_id",
            "issued_at",
        }
        if (
            set(payload) != expected
            or not isinstance(payload["authorized_add_writes"], list)
            or not isinstance(payload["invalidation_refs"], list)
        ):
            raise ValueError("G2_CURRENT_CR_SCOPE_AMEND_AUTHORIZATION_FIELDS_INVALID")
        values = dict(payload)
        values["authorized_add_writes"] = tuple(payload["authorized_add_writes"])
        values["invalidation_refs"] = tuple(payload["invalidation_refs"])
        return cls(**values)


CurrentScopeAmendAuthorization = (
    G1ScopeAmendAuthorizationV1 | G2CurrentCRScopeAmendAuthorizationV2
)


@dataclass(frozen=True)
class G1ScopeAmendPlanV1:
    decision: str
    release_root: Path
    process_root: Path
    work: Work
    delta: G1ScopeDeltaV1
    authorization: CurrentScopeAmendAuthorization
    result_scope: WorkScope
    invalidated_refs: tuple[str, ...]
    target_preimages: tuple[tuple[str, str], ...]
    plan_digest: str
    blockers: tuple[str, ...] = ()
    mutation_count: int = 0

    def as_dict(self) -> dict[str, object]:
        is_g2_current = isinstance(
            self.authorization,
            G2CurrentCRScopeAmendAuthorizationV2,
        )
        return {
            "schema_version": 2 if is_g2_current else 1,
            "kind": (
                "G2CurrentCRScopeAmendPlanV2"
                if is_g2_current
                else "G1ScopeAmendPlanV1"
            ),
            "profile": "g2-current-cr" if is_g2_current else "g1-work",
            "decision": self.decision,
            "work_id": self.work.work_id,
            "delta_digest": self.delta.digest,
            "authorization_digest": self.authorization.digest,
            "predecessor_scope_digest": self.work.scope.digest,
            "successor_scope_digest": self.result_scope.digest,
            "invalidated_refs": list(self.invalidated_refs),
            "target_preimages": dict(self.target_preimages),
            "plan_digest": self.plan_digest,
            "blockers": list(self.blockers),
            "mutation_count": self.mutation_count,
        }


def load_current_scope_amend_authorization(
    path: Path,
) -> CurrentScopeAmendAuthorization:
    if path.is_symlink() or not path.is_file():
        raise ValueError("CURRENT_SCOPE_AMEND_AUTHORIZATION_PATH_INVALID")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("CURRENT_SCOPE_AMEND_AUTHORIZATION_NOT_OBJECT")
    if payload.get("schema_version") == 1:
        return G1ScopeAmendAuthorizationV1.from_mapping(payload)
    if (
        payload.get("schema_version") == 2
        and payload.get("operation") == "work.scope-amend.current-cr.g2"
    ):
        return G2CurrentCRScopeAmendAuthorizationV2.from_mapping(payload)
    raise ValueError("CURRENT_SCOPE_AMEND_AUTHORIZATION_VERSION_INVALID")


def load_g1_scope_amend_authorization(
    path: Path,
) -> CurrentScopeAmendAuthorization:
    """向后兼容的 loader 名称；V2 通过 operation 显式隔离。"""

    return load_current_scope_amend_authorization(path)


def _result_g1_scope(current: WorkScope, delta: G1ScopeDeltaV1) -> WorkScope:
    return WorkScope(
        current.version,
        tuple(sorted(set(current.allowed_reads) | set(delta.add_reads))),
        tuple(sorted(set(current.allowed_writes) | set(delta.add_writes))),
        tuple(sorted(set(current.required_checks) | set(delta.add_checks))),
    )


def _git_snapshot(root: Path) -> tuple[str, str]:
    head = run_git(["rev-parse", "--verify", "HEAD"], cwd=root)
    status = run_git(["status", "--porcelain=v1", "--untracked-files=all"], cwd=root)
    oid = head.stdout.strip() if head.ok else ""
    if not re.fullmatch(r"[0-9a-f]{40}", oid) or not status.ok:
        raise ValueError("G1_SCOPE_AMEND_GIT_SNAPSHOT_UNAVAILABLE")
    return oid, canonical_digest({"status_lines": status.stdout.splitlines()})


def _g2_current_cr_approval_blockers(
    process_root: Path,
    authorization: G2CurrentCRScopeAmendAuthorizationV2,
) -> tuple[str, ...]:
    blockers: list[str] = []
    checkpoint_path = process_root / authorization.checkpoint_ref.removeprefix(
        "process/"
    )
    if checkpoint_path.is_symlink() or not checkpoint_path.is_file():
        blockers.append("G2_CURRENT_CR_SCOPE_AMEND_CHECKPOINT_MISSING")
    elif sha256(checkpoint_path.read_bytes()).hexdigest() != authorization.checkpoint_digest:
        blockers.append("G2_CURRENT_CR_SCOPE_AMEND_CHECKPOINT_DIGEST_MISMATCH")

    approval_findings = validate_exact_checkpoint_approval_binding(
        process_root,
        event_id=authorization.approval_event_id,
        event_digest=authorization.approval_event_digest,
        cr_id=authorization.cr_id,
        work_id=authorization.work_id,
        checkpoint_ref=authorization.checkpoint_ref,
        checkpoint_digest=authorization.checkpoint_digest,
        decision_id=authorization.approval_decision_id,
    )
    if approval_findings:
        blockers.append("G2_CURRENT_CR_SCOPE_AMEND_APPROVAL_BINDING_INVALID")
    return tuple(sorted(set(blockers)))


def _g1_target_refs(
    work_id: str,
    authorization_id: str,
    successor_revision_id: str,
) -> tuple[str, ...]:
    root = f"works/{work_id}"
    return (
        f"{root}/WORK.yaml",
        f"{root}/revisions/{successor_revision_id}.json",
        f"{root}/evidence/scope-amend/{authorization_id}.invalidation.json",
        f"{root}/evidence/scope-amend/{authorization_id}.receipt.json",
    )


def plan_g1_scope_amend(
    release_root: Path,
    *,
    work_id: str,
    delta: G1ScopeDeltaV1,
    authorization: CurrentScopeAmendAuthorization,
    release_oid: str,
    process_oid: str,
) -> G1ScopeAmendPlanV1:
    """为 G1 Work 或显式批准的 G2 current CR 构造零写 successor 计划。"""

    root = release_root.resolve()
    route = require_process_route(root)
    process_root = route.process_root.resolve()
    work = load_work(process_root, work_id)
    work_path = process_root / work.work_ref
    work_preimage = sha256(work_path.read_bytes()).hexdigest()
    actual_release_oid, actual_release_dirty = _git_snapshot(root)
    actual_process_oid, actual_process_dirty = _git_snapshot(process_root)
    blockers: list[str] = []
    is_g2_current = isinstance(
        authorization,
        G2CurrentCRScopeAmendAuthorizationV2,
    )
    prefix = "G2_CURRENT_CR_SCOPE_AMEND" if is_g2_current else "G1_SCOPE_AMEND"
    if is_g2_current:
        if work.kind != "cr":
            blockers.append("G2_CURRENT_CR_SCOPE_AMEND_WORK_KIND_INVALID")
        if work.risk_profile != "G2":
            blockers.append("G2_CURRENT_CR_SCOPE_AMEND_RISK_INVALID")
        if work.status not in {"planned", "blocked"}:
            blockers.append("G2_CURRENT_CR_SCOPE_AMEND_STATUS_INVALID")
        if delta.add_reads or delta.add_checks:
            blockers.append("G2_CURRENT_CR_SCOPE_AMEND_DELTA_PROFILE_INVALID")
        if delta.add_writes != authorization.authorized_add_writes:
            blockers.append("G2_CURRENT_CR_SCOPE_AMEND_AUTHORIZED_WRITES_MISMATCH")
        if authorization.predecessor_scope_digest != work.scope.digest:
            blockers.append("G2_CURRENT_CR_SCOPE_AMEND_PREDECESSOR_SCOPE_MISMATCH")
        blockers.extend(_g2_current_cr_approval_blockers(process_root, authorization))
    else:
        if work.kind != "work":
            blockers.append("G1_SCOPE_AMEND_WORK_KIND_INVALID")
        if work.risk_profile not in {"G0", "G1"}:
            blockers.append("G1_SCOPE_AMEND_RISK_INVALID")
        if work.status not in {"paused", "blocked"}:
            blockers.append("G1_SCOPE_AMEND_STATUS_INVALID")
    if authorization.work_id != work_id:
        blockers.append(f"{prefix}_AUTH_WORK_MISMATCH")
    if (
        authorization.release_oid != release_oid
        or authorization.process_oid != process_oid
        or actual_release_oid != release_oid
        or actual_process_oid != process_oid
    ):
        blockers.append(f"{prefix}_OID_MISMATCH")
    if (
        authorization.release_dirty_digest != actual_release_dirty
        or authorization.process_dirty_digest != actual_process_dirty
    ):
        blockers.append(f"{prefix}_DIRTY_SET_MISMATCH")
    if authorization.work_preimage_digest != work_preimage:
        blockers.append(f"{prefix}_WORK_PREIMAGE_MISMATCH")
    if authorization.delta_digest != delta.digest:
        blockers.append(f"{prefix}_DELTA_MISMATCH")
    result_scope = _result_g1_scope(work.scope, delta)
    if blockers:
        decision = "BLOCKED"
    elif result_scope.digest == work.scope.digest:
        decision = "NO_CHANGE"
    else:
        decision = "READY"
    native_invalidated_refs = tuple(
        sorted(
            {
                *(filter(None, (work.result_ref,))),
                f"works/{work_id}/evidence/validation/**",
                f"works/{work_id}/AUTHORIZATION.json",
                f"works/{work_id}/HANDOFF.yaml",
            }
        )
    )
    invalidated_refs = (
        authorization.invalidation_refs
        if is_g2_current
        else native_invalidated_refs
    )
    if is_g2_current and not set(native_invalidated_refs).issubset(
        invalidated_refs
    ):
        blockers.append("G2_CURRENT_CR_SCOPE_AMEND_INVALIDATION_INCOMPLETE")
        decision = "BLOCKED"
    target_refs = _g1_target_refs(
        work_id,
        authorization.authorization_id,
        authorization.successor_revision_id,
    )
    target_preimages = tuple(
        (ref, target_preimage_digest(process_root / ref)) for ref in target_refs
    )
    if any(
        preimage != canonical_digest({"kind": "missing"})
        for ref, preimage in target_preimages
        if ref != f"works/{work_id}/WORK.yaml"
    ):
        blockers.append(f"{prefix}_AUTHORIZATION_CONSUMED")
        decision = "BLOCKED"
    identity = {
        "profile": "g2-current-cr" if is_g2_current else "g1-work",
        "work_id": work_id,
        "delta_digest": delta.digest,
        "authorization_digest": authorization.digest,
        "release_oid": release_oid,
        "process_oid": process_oid,
        "release_dirty_digest": actual_release_dirty,
        "process_dirty_digest": actual_process_dirty,
        "work_preimage_digest": work_preimage,
        "predecessor_scope_digest": work.scope.digest,
        "successor_scope_digest": result_scope.digest,
        "invalidated_refs": invalidated_refs,
        "target_preimages": target_preimages,
        "decision": decision,
        "blockers": tuple(sorted(set(blockers))),
    }
    return G1ScopeAmendPlanV1(
        decision,
        root,
        process_root,
        work,
        delta,
        authorization,
        result_scope,
        invalidated_refs,
        target_preimages,
        canonical_digest(identity),
        tuple(sorted(set(blockers))),
        0,
    )


def apply_g1_scope_amend(
    plan: G1ScopeAmendPlanV1,
    *,
    expected_plan_digest: str,
    current_authorization: CurrentScopeAmendAuthorization,
    release_oid: str,
    process_oid: str,
) -> dict[str, object]:
    if plan.decision != "READY":
        return {"decision": plan.decision, "blockers": list(plan.blockers), "mutation_count": 0}
    if expected_plan_digest != plan.plan_digest:
        return {"decision": "BLOCKED", "reason_code": "PLAN_DIGEST_MISMATCH", "mutation_count": 0}
    if current_authorization.digest != plan.authorization.digest:
        return {"decision": "BLOCKED", "reason_code": "AUTHORIZATION_DRIFT", "mutation_count": 0}
    fresh = plan_g1_scope_amend(
        plan.release_root,
        work_id=plan.work.work_id,
        delta=plan.delta,
        authorization=current_authorization,
        release_oid=release_oid,
        process_oid=process_oid,
    )
    if fresh.plan_digest != plan.plan_digest or fresh.target_preimages != plan.target_preimages:
        return {"decision": "BLOCKED", "reason_code": "REPLAN_REQUIRED", "mutation_count": 0}
    revision = WorkScopeRevisionV2(
        2,
        current_authorization.successor_revision_id,
        plan.work.work_id,
        current_authorization.work_preimage_digest,
        plan.work.scope.digest,
        plan.result_scope.digest,
        plan.delta.digest,
        current_authorization.digest,
        plan.plan_digest,
        plan.invalidated_refs,
    )
    is_g2_current = isinstance(
        current_authorization,
        G2CurrentCRScopeAmendAuthorizationV2,
    )
    updated_work = replace(
        plan.work,
        scope=plan.result_scope,
        **({"updated_at": current_authorization.issued_at} if is_g2_current else {}),
    )
    receipt = {
        "schema_version": 2,
        "kind": (
            "G2CurrentCRScopeAmendReceiptV2"
            if is_g2_current
            else "ScopeAmendReceiptV2"
        ),
        "profile": "g2-current-cr" if is_g2_current else "g1-work",
        "authorization_id": current_authorization.authorization_id,
        "authorization_digest": current_authorization.digest,
        "work_id": plan.work.work_id,
        "revision_id": revision.revision_id,
        "plan_digest": plan.plan_digest,
        "release_oid": release_oid,
        "process_oid": process_oid,
        "predecessor_work_digest": current_authorization.work_preimage_digest,
        "successor_scope_digest": plan.result_scope.digest,
        "invalidation_digest": canonical_digest(list(plan.invalidated_refs)),
    }
    if is_g2_current:
        receipt.update(
            {
                "cr_id": current_authorization.cr_id,
                "predecessor_scope_digest": current_authorization.predecessor_scope_digest,
                "checkpoint_ref": current_authorization.checkpoint_ref,
                "checkpoint_digest": current_authorization.checkpoint_digest,
                "approval_event_id": current_authorization.approval_event_id,
                "approval_event_digest": current_authorization.approval_event_digest,
                "approval_decision_id": current_authorization.approval_decision_id,
                "invalidated_refs": list(plan.invalidated_refs),
            }
        )
    invalidation = {
        "schema_version": 1,
        "kind": "ScopeAmendInvalidationV1",
        "work_id": plan.work.work_id,
        "revision_id": revision.revision_id,
        "stale_refs": list(plan.invalidated_refs),
        "reason": (
            "G2_CURRENT_CR_SCOPE_SUCCESSOR"
            if is_g2_current
            else "G1_SCOPE_SUCCESSOR"
        ),
    }
    refs = _g1_target_refs(
        plan.work.work_id,
        current_authorization.authorization_id,
        current_authorization.successor_revision_id,
    )
    postimages = (
        (refs[0], (dump_yaml(updated_work.as_dict()) + "\n").encode("utf-8")),
        (refs[1], _json_bytes(revision.as_dict())),
        (refs[2], _json_bytes(invalidation)),
        (refs[3], _json_bytes(receipt)),
    )
    writer_id = (
        "scope-amend-"
        + sha256(current_authorization.authorization_id.encode("utf-8")).hexdigest()[:32]
    )
    shared_lock = None
    if is_g2_current:
        try:
            shared_lock = acquire_shared_projection_writer_lock(
                plan.process_root,
                writer_id,
            )
        except (OSError, ValueError):
            return {
                "decision": "BLOCKED",
                "reason_code": "G2_CURRENT_CR_SCOPE_AMEND_SHARED_LOCK_UNAVAILABLE",
                "mutation_count": 0,
            }
    transaction_id = ""
    domain_applied = False
    refreshed_refs: tuple[str, ...] = ()
    try:
        if is_g2_current:
            assert_work_close_shared_projection_lineage(plan.process_root)
        targets = tuple(
            build_transaction_target(plan.process_root, ref=ref, after_bytes=value)
            for ref, value in postimages
        )
        transaction_id = begin_work_init_transaction(
            plan.process_root,
            operation="work.scope-amend",
            work_id=plan.work.work_id,
            plan_digest=plan.plan_digest,
            release_oid=release_oid,
            process_oid=process_oid,
            targets=targets,
        )
        applied_refs = apply_work_init_transaction_targets(plan.process_root, transaction_id)
        domain_applied = True
        if is_g2_current:
            refreshed_refs = refresh_state_projection_if_initialized(plan.process_root)
            _validate_scope_amend_postimage(plan)  # type: ignore[arg-type]
        transaction = commit_work_init_transaction(
            plan.process_root,
            transaction_id,
            successor_id=revision.revision_id,
        )
    except Exception as exc:
        if not transaction_id:
            return {
                "decision": "BLOCKED",
                "reason_code": "TRANSACTION_NOT_STARTED",
                "mutation_count": 0,
            }
        recovery = rollback_work_init_transaction(
            plan.process_root,
            transaction_id,
            failure=str(exc),
        )
        if domain_applied and is_g2_current:
            try:
                refresh_state_projection_if_initialized(plan.process_root)
            except Exception as recovery_exc:
                raise ValueError(
                    "G2 current CR scope amendment State recovery failed"
                ) from recovery_exc
        return {
            "decision": "PARTIAL" if recovery.recovery_required else "RECOVERED",
            "transaction_id": transaction_id,
            "reason_codes": list(recovery.reason_codes),
            "mutation_count": 0,
        }
    finally:
        if shared_lock is not None:
            release_shared_projection_writer_lock(shared_lock, writer_id)
    return {
        "decision": "PASS",
        "transaction_id": transaction.transaction_id,
        "transaction_state": "COMMITTED",
        "revision_ref": refs[1],
        "receipt_ref": refs[3],
        "invalidated_refs": list(plan.invalidated_refs),
        "domain_mutation_count": len(applied_refs),
        "coordination_mutation_count": len(refreshed_refs),
        "mutation_count": len(applied_refs) + len(refreshed_refs),
    }


def inspect_g1_scope_amend(process_root: Path, *, work_id: str = "") -> dict[str, Any]:
    inspection = inspect_work_init_transactions(process_root, work_id=work_id)
    transactions = [
        item for item in inspection["transactions"] if item["operation"] == "work.scope-amend"
    ]
    unresolved = [item for item in transactions if item["state"] not in {"COMMITTED", "RECOVERED"}]
    return {
        "schema_version": 1,
        "kind": "G1ScopeAmendInspectionV1",
        "decision": "BLOCKED" if unresolved else "PASS",
        "transactions": transactions,
        "unresolved_count": len(unresolved),
        "mutation_count": 0,
    }


def recover_g1_scope_amend(
    process_root: Path,
    *,
    transaction_id: str,
    expected_plan_digest: str,
    release_oid: str,
    process_oid: str,
) -> dict[str, object]:
    receipt = recover_work_init_transaction(
        process_root,
        transaction_id,
        expected_plan_digest=expected_plan_digest,
        release_oid=release_oid,
        process_oid=process_oid,
    )
    return receipt.as_dict()


__all__ = [
    "ScopeAmendAuthorizationV2",
    "ScopeAmendAuthorizationV1",
    "ScopeAmendTransactionPlanV1",
    "G1ScopeAmendAuthorizationV1",
    "G2CurrentCRScopeAmendAuthorizationV2",
    "CurrentScopeAmendAuthorization",
    "G1ScopeAmendPlanV1",
    "admit_scope_amend_predecessor",
    "apply_scope_amend_transaction",
    "load_scope_amend_authorization",
    "load_g1_scope_amend_authorization",
    "load_current_scope_amend_authorization",
    "plan_g1_scope_amend",
    "apply_g1_scope_amend",
    "inspect_g1_scope_amend",
    "recover_g1_scope_amend",
    "plan_scope_amend_from_release_root",
]
