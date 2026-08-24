"""Work status-transition 的 parent/child 原子协调器。"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, ClassVar

from meta_flow.execution_control.contract import canonical_digest
from meta_flow.execution_control.operation_admission import (
    MutationPlanV2,
    OperationAdmissionV1,
    build_mutation_plan,
    provider_source_identity_digest,
    repository_head_oid,
)
from meta_flow.state import current as state_current
from meta_flow.work import handoff as work_handoff
from meta_flow.work import transaction_child
from meta_flow.work.lifecycle import transition_work
from meta_flow.execution_control.primitives import (
    DIGEST_RE,
    acquire_shared_projection_writer_lock,
    digest_bytes,
    now_utc,
    plan_digest,
    release_shared_projection_writer_lock,
    render_yaml_bytes,
    safe_authorization_id,
)
from meta_flow.work.lifecycle_transaction import (
    CURRENT_REF,
    STATE_PROJECTION_REFS,
    TERMINAL_TRANSACTION_STATES,
    TRANSACTION_ROOT_REL,
    TRANSACTION_SCHEMA_VERSION,
    WorkClosePlanV1,
    WorkCloseTargetV1,
    acquire_work_close_writer_lock,
    attach_before_bytes,
    build_state_projection_candidates,
    build_work_close_manifest,
    inspect_work_close_transactions,
    lineage_for_targets,
    lineage_generation_errors,
    release_root_from_process,
    release_work_close_writer_lock,
    require_work_close_runtime_chain,
    validate_work_close_manifest,
    work_close_manifest_path,
)
from meta_flow.work.model import load_work
from meta_flow.work.scope import check_scope

EMPTY_CURRENT_PROJECTION_PLAN_DIGEST = canonical_digest(
    {"schema_version": 2, "kind": "CurrentProjectionPlanV2", "targets": []}
)
EMPTY_BYTES_DIGEST = sha256(b"").hexdigest()


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    """动态复用 parent writer，保留 fault-injection 与单一写内核。"""

    from meta_flow.work import lifecycle_transaction

    lifecycle_transaction._write_json_atomic(path, payload)


def _replace_bytes(path: Path, content: bytes) -> None:
    """动态复用 parent replace primitive。"""

    from meta_flow.work import lifecycle_transaction

    lifecycle_transaction._replace_bytes(path, content)


def _rollback(root: Path, manifest: dict[str, Any]) -> tuple[bool, list[str]]:
    """动态复用 parent rollback primitive。"""

    from meta_flow.work import lifecycle_transaction

    return lifecycle_transaction._rollback(root, manifest)


@dataclass(frozen=True, slots=True)
class WorkStatusTransitionPlanV2:
    """Work/core projection parent 与 CURRENT alias child 的封闭计划。"""

    parent_plan: WorkClosePlanV1
    current_projection_plan: state_current.CurrentProjectionPlanV2
    handoff_plan: work_handoff.HandoffTransitionPlanV1
    admission: OperationAdmissionV1
    mutation_plan: MutationPlanV2
    plan_digest: str

    @property
    def ready(self) -> bool:
        return self.parent_plan.ready and self.handoff_plan.ready

    @property
    def target_refs(self) -> tuple[str, ...]:
        return (
            *(target.ref for target in self.parent_plan.targets),
            *(target.ref for target in self.current_projection_plan.targets),
            *self.handoff_plan.target_refs,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "kind": "WorkStatusTransitionPlanV2",
            "decision": "READY" if self.ready else "BLOCKED",
            "parent_plan": self.parent_plan.as_dict(),
            "current_projection_plan": self.current_projection_plan.as_dict(),
            "handoff_plan": self.handoff_plan.as_dict(),
            "admission": self.admission.as_dict(),
            "admission_digest": self.admission.admission_digest,
            "mutation_plan": self.mutation_plan.as_dict(),
            "target_refs": list(self.target_refs),
            "plan_digest": self.plan_digest,
            "mutation_count": 0,
        }


@dataclass(frozen=True, slots=True)
class WorkStatusTransitionAuthorizationV2:
    schema_version: ClassVar[int] = 2
    kind: ClassVar[str] = "WorkStatusTransitionAuthorizationV2"
    authorization_id: str
    work_id: str
    plan_digest: str
    parent_plan_digest: str
    target_refs: tuple[str, ...]
    expires_at: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> WorkStatusTransitionAuthorizationV2:
        expected = {
            "schema_version",
            "kind",
            "authorization_id",
            "work_id",
            "plan_digest",
            "parent_plan_digest",
            "target_refs",
            "expires_at",
        }
        if (
            set(payload) != expected
            or payload.get("schema_version") != 2
            or payload.get("kind") != cls.kind
        ):
            raise ValueError("status transition authorization fields mismatch")
        raw_refs = payload.get("target_refs")
        if not isinstance(raw_refs, list) or any(not isinstance(ref, str) for ref in raw_refs):
            raise ValueError("status transition authorization targets are invalid")
        return cls(
            authorization_id=str(payload.get("authorization_id") or ""),
            work_id=str(payload.get("work_id") or ""),
            plan_digest=str(payload.get("plan_digest") or ""),
            parent_plan_digest=str(payload.get("parent_plan_digest") or ""),
            target_refs=tuple(raw_refs),
            expires_at=str(payload.get("expires_at") or ""),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "authorization_id": self.authorization_id,
            "work_id": self.work_id,
            "plan_digest": self.plan_digest,
            "parent_plan_digest": self.parent_plan_digest,
            "target_refs": list(self.target_refs),
            "expires_at": self.expires_at,
        }

    def validate_for(self, plan: WorkClosePlanV1) -> None:
        safe_authorization_id(self.authorization_id)
        if plan.operation != "work.status-transition":
            raise ValueError("status transition authorization operation mismatch")
        if self.work_id != plan.work_id or self.parent_plan_digest != plan.plan_digest:
            raise ValueError("status transition authorization parent binding mismatch")
        if tuple(target.ref for target in plan.targets) != self.target_refs[: len(plan.targets)]:
            raise ValueError("status transition authorization parent targets mismatch")
        if (
            not DIGEST_RE.fullmatch(self.plan_digest)
            or not DIGEST_RE.fullmatch(self.parent_plan_digest)
            or len(self.target_refs) != len(set(self.target_refs))
        ):
            raise ValueError("status transition authorization identity is invalid")
        try:
            expiry = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("status transition authorization expires_at is invalid") from exc
        if expiry.tzinfo is None or expiry.astimezone(UTC) <= datetime.now(UTC):
            raise ValueError("status transition authorization is expired")


@dataclass(frozen=True, slots=True)
class WorkStatusTransitionReceiptV2:
    decision: str
    authorization_id: str
    work_id: str
    plan_digest: str
    planned_refs: tuple[str, ...]
    actual_mutation_refs: tuple[str, ...]
    parent_decision: str
    child_decision: str
    handoff_decision: str
    recovery_required: bool
    reason_codes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "kind": "WorkStatusTransitionReceiptV2",
            "decision": self.decision,
            "authorization_id": self.authorization_id,
            "work_id": self.work_id,
            "plan_digest": self.plan_digest,
            "planned_refs": list(self.planned_refs),
            "actual_mutation_refs": list(self.actual_mutation_refs),
            "mutation_count": len(self.actual_mutation_refs),
            "parent_decision": self.parent_decision,
            "child_decision": self.child_decision,
            "handoff_decision": self.handoff_decision,
            "recovery_required": self.recovery_required,
            "reason_codes": list(self.reason_codes),
        }


def _status_writer_inventory(
    work: Any,
    refs: tuple[str, ...],
) -> tuple[str, str]:
    """把 exact writer refs 归类为系统命名空间或 Work business scope。"""

    rows: list[dict[str, str]] = []
    handoff_ref = f"works/{work.work_id}/HANDOFF.yaml"
    for ref in refs:
        system_owned = (
            ref == work.work_ref
            or ref in {*STATE_PROJECTION_REFS, "process/.gitignore"}
            or ref == handoff_ref
            or ref.startswith("process/current/")
        )
        if system_owned:
            owner = "SYSTEM_OWNED"
            matched_rule = "native-work-lifecycle-bounded-namespace"
        else:
            requested = ref.removeprefix("process/")
            decision = check_scope(work.scope, "write", requested)
            if not decision.allowed:
                raise ValueError(f"status transition writer is outside Work scope: {ref}")
            owner = "WORK_SCOPE"
            matched_rule = decision.matched_rule
        rows.append(
            {
                "ref": ref,
                "owner": owner,
                "matched_rule": matched_rule,
            }
        )
    inventory_digest = canonical_digest(
        {
            "schema_version": 1,
            "kind": "ExactWriterInventoryV1",
            "rows": rows,
        }
    )
    namespace_digest = canonical_digest(
        {
            "schema_version": 1,
            "kind": "SystemNamespaceDecisionV1",
            "work_id": work.work_id,
            "scope_digest": work.scope.digest,
            "rows": rows,
        }
    )
    return inventory_digest, namespace_digest


def _capture_status_admission(
    root: Path,
    work: Any,
    *,
    expected_status: str,
    new_status: str,
    result_ref: str,
    target_refs: tuple[str, ...],
) -> OperationAdmissionV1:
    release_root = release_root_from_process(root)
    inventory_digest, namespace_digest = _status_writer_inventory(work, target_refs)
    return OperationAdmissionV1(
        snapshot_digest=canonical_digest(
            {
                "schema_version": 1,
                "kind": "WorkStatusOperationSnapshotV1",
                "work_id": work.work_id,
                "status": work.status,
                "scope_digest": work.scope.digest,
                "route_profile_digest": canonical_digest(work.route_profile.as_dict()),
                "namespace_decision_digest": namespace_digest,
                "writer_inventory_digest": inventory_digest,
            }
        ),
        release_oid=repository_head_oid(release_root),
        process_oid=repository_head_oid(root),
        provider_identity_digest=provider_source_identity_digest(
            Path(__file__),
            Path(transaction_child.__file__),
            Path(work_handoff.__file__),
            Path(state_current.__file__),
            Path(__file__).with_name("lifecycle_transaction.py"),
            Path(__file__).parents[1] / "execution_control/exact_file_transaction.py",
            Path(__file__).parents[1] / "execution_control/operation_admission.py",
        ),
        route_profile_digest=canonical_digest(work.route_profile.as_dict()),
        work_scope_digest=work.scope.digest,
        authorization_identity_digest=canonical_digest(
            {
                "schema_version": 2,
                "kind": WorkStatusTransitionAuthorizationV2.kind,
                "source": "typed-user-confirmation",
                "single_use": True,
            }
        ),
    )


def _status_mutation_images(
    parent_targets: tuple[WorkCloseTargetV1, ...],
    current_plan: state_current.CurrentProjectionPlanV2,
    handoff_plan: work_handoff.HandoffTransitionPlanV1,
) -> tuple[tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]]:
    before: list[tuple[str, str]] = [
        (target.ref, target.before_digest) for target in parent_targets
    ]
    after: list[tuple[str, str]] = [
        (target.ref, target.after_digest) for target in parent_targets
    ]
    for target in current_plan.targets:
        rendered = target.as_dict()
        before.append((target.ref, canonical_digest(rendered["before"])))
        after.append((target.ref, canonical_digest(rendered["after"])))
    if handoff_plan.target_ref:
        before.append((handoff_plan.target_ref, handoff_plan.before_digest))
        after.append((handoff_plan.target_ref, handoff_plan.desired_digest))
    return tuple(sorted(before)), tuple(sorted(after))


def plan_work_status_transition(
    process_root: Path,
    work_id: str,
    *,
    expected_status: str,
    new_status: str,
    result_ref: str = "",
    handoff: work_handoff.WorkHandoff | None = None,
    _state_lock_handle: Any | None = None,
) -> WorkStatusTransitionPlanV2:
    """只读生成 Work + State/CURRENT + alias 的 exact transition 计划。"""

    root = process_root.resolve()
    blockers: list[str] = []
    targets: list[WorkCloseTargetV1] = []
    alias_plan = state_current.CurrentProjectionPlanV2(
        (),
        canonical_digest({"schema_version": 2, "kind": "CurrentProjectionPlanV2", "targets": []}),
    )
    handoff_plan = work_handoff.unavailable_handoff_transition_plan(
        work_id,
        "HANDOFF_POSTIMAGE_UNAVAILABLE",
    )
    ignore_owned_state_lock = False
    if _state_lock_handle is not None:
        try:
            from meta_flow.state.projection_transaction import (
                state_projection_lock_path,
                transaction_lock_identity,
                validate_transaction_lock,
            )

            expected_lock_path = state_projection_lock_path(release_root_from_process(root))
            validate_transaction_lock(
                _state_lock_handle,
                expected_path=expected_lock_path,
            )
            if (
                transaction_lock_identity(expected_lock_path)
                != _state_lock_handle.transaction_id
            ):
                raise ValueError("state projection writer lock capability identity drifted")
            ignore_owned_state_lock = True
        except (OSError, ValueError) as exc:
            blockers.append(f"STATE_PROJECTION_LOCK_CAPABILITY_INVALID:{exc}")
    current = None
    try:
        current = load_work(root, work_id)
        if current.status != expected_status:
            raise ValueError(
                f"Work status changed: expected {expected_status}, current {current.status}"
            )
        updated = transition_work(current, new_status, result_ref=result_ref)
        handoff_plan = work_handoff.plan_handoff_transition(
            root,
            updated,
            transition=new_status,
            handoff=handoff,
        )
        work_bytes = render_yaml_bytes(updated.as_dict())
        candidates: list[tuple[str, bytes]] = [(updated.work_ref, work_bytes)]
        candidates.extend(
            build_state_projection_candidates(
                root,
                object_overrides={"process/" + updated.work_ref: (updated.as_dict(), work_bytes)},
            )
        )
        for ref, after in candidates:
            path = root / ref
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"status transition target is not a regular file: {ref}")
            before = path.read_bytes()
            if before != after:
                targets.append(
                    WorkCloseTargetV1(
                        ref,
                        digest_bytes(before),
                        digest_bytes(after),
                        after,
                    )
                )
        current_candidate = next(
            (after for ref, after in candidates if ref == CURRENT_REF),
            None,
        )
        if current_candidate is not None:
            entry = json.loads(current_candidate.decode("utf-8"))
            alias_plan = state_current.plan_current_projection_targets(
                release_root_from_process(root),
                current_entry=entry,
                future_existing_refs=tuple(
                    "process/" + ref for ref, _after in candidates if ref in STATE_PROJECTION_REFS
                ),
            )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        blockers.append(str(exc))

    lineage: dict[str, str] = {}
    if not blockers:
        try:
            lineage = lineage_for_targets(
                root,
                tuple(targets),
                # 只供 apply 在已验证自身 state lock capability 后做 fresh
                # replan。公共 plan 默认仍把任何现存锁视为冲突并 fail-closed。
                ignore_state_lock=ignore_owned_state_lock,
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            blockers.append(str(exc))
    target_refs = (
        *(target.ref for target in targets),
        *(target.ref for target in alias_plan.targets),
        *handoff_plan.target_refs,
    )
    admission: OperationAdmissionV1 | None = None
    if not blockers and current is not None:
        try:
            admission = _capture_status_admission(
                root,
                current,
                expected_status=expected_status,
                new_status=new_status,
                result_ref=result_ref,
                target_refs=target_refs,
            )
        except (OSError, ValueError) as exc:
            blockers.append(str(exc))
    if admission is None:
        unavailable = canonical_digest(
            {
                "schema_version": 1,
                "kind": "WorkStatusOperationAdmissionUnavailableV1",
                "work_id": work_id,
                "blockers": blockers,
            }
        )
        admission = OperationAdmissionV1(
            unavailable,
            "",
            "",
            unavailable,
            unavailable,
            unavailable,
            unavailable,
        )
    parent_fields = {
        "schema_version": TRANSACTION_SCHEMA_VERSION,
        "operation": "work.status-transition",
        "work_id": work_id,
        "expected_status": expected_status,
        "outcome": new_status,
        "result_ref": result_ref,
        "targets": [target.as_plan_dict() for target in targets],
        "lineage": lineage,
        "blockers": blockers,
        "publication_binding": None,
    }
    parent_plan = WorkClosePlanV1(
        operation="work.status-transition",
        decision="BLOCKED" if blockers else "READY",
        work_id=work_id,
        expected_status=expected_status,
        outcome=new_status,
        result_ref=result_ref,
        targets=tuple(targets),
        lineage=tuple(sorted(lineage.items())),
        blockers=tuple(blockers),
        plan_digest=plan_digest(parent_fields),
    )
    preimages, afterimages = _status_mutation_images(
        parent_plan.targets,
        alias_plan,
        handoff_plan,
    )
    operation_digest = canonical_digest(
        {
            "operation": "work.status-transition",
            "work_id": work_id,
            "expected_status": expected_status,
            "new_status": new_status,
            "result_ref": result_ref,
            "current_projection_plan_digest": alias_plan.plan_digest,
            "handoff_plan_digest": handoff_plan.plan_digest,
        }
    )
    mutation_plan = build_mutation_plan(
        operation="work.status-transition",
        decision="BLOCKED" if blockers else "READY",
        admission_digest=admission.admission_digest,
        operation_digest=operation_digest,
        target_preimages=preimages,
        target_afterimages=afterimages,
    )
    aggregate_fields = {
        "schema_version": 2,
        "kind": "WorkStatusTransitionPlanV2",
        "parent_plan_digest": parent_plan.plan_digest,
        "current_projection_plan_digest": alias_plan.plan_digest,
        "handoff_plan_digest": handoff_plan.plan_digest,
        "admission_digest": admission.admission_digest,
        "mutation_plan_digest": mutation_plan.plan_digest,
        "target_refs": list(target_refs),
    }
    return WorkStatusTransitionPlanV2(
        parent_plan,
        alias_plan,
        handoff_plan,
        admission,
        mutation_plan,
        canonical_digest(aggregate_fields),
    )


def _validate_work_status_transition_plan(
    process_root: Path,
    release_root: Path,
    plan: WorkStatusTransitionPlanV2,
    *,
    verify_child_preimages: bool,
) -> None:
    """重算 supplied parent/child/aggregate，拒绝任何 after-image 篡改。"""

    parent = plan.parent_plan
    if any(
        not DIGEST_RE.fullmatch(target.before_digest)
        or not DIGEST_RE.fullmatch(target.after_digest)
        or digest_bytes(target.after_bytes) != target.after_digest
        for target in parent.targets
    ):
        raise ValueError("status transition parent plan integrity mismatch")
    parent_fields = {
        "schema_version": TRANSACTION_SCHEMA_VERSION,
        "operation": parent.operation,
        "work_id": parent.work_id,
        "expected_status": parent.expected_status,
        "outcome": parent.outcome,
        "result_ref": parent.result_ref,
        "targets": [target.as_plan_dict() for target in parent.targets],
        "lineage": dict(parent.lineage),
        "blockers": list(parent.blockers),
        "publication_binding": None,
    }
    if parent.operation != "work.status-transition" or parent.plan_digest != plan_digest(
        parent_fields
    ):
        raise ValueError("status transition parent plan integrity mismatch")
    state_current.validate_current_projection_plan(
        release_root,
        plan.current_projection_plan,
        verify_preimages=verify_child_preimages,
    )
    work_handoff.validate_handoff_transition_plan(
        process_root,
        plan.handoff_plan,
        verify_preimage=verify_child_preimages,
    )
    refs = plan.target_refs
    if len(refs) != len(set(refs)):
        raise ValueError("status transition aggregate target set is duplicated")
    admission = plan.admission
    if (
        len(admission.release_oid) not in {40, 64}
        or len(admission.process_oid) not in {40, 64}
        or any(char not in "0123456789abcdef" for char in admission.release_oid)
        or any(char not in "0123456789abcdef" for char in admission.process_oid)
        or any(
            not DIGEST_RE.fullmatch(value)
            for value in (
                admission.snapshot_digest,
                admission.provider_identity_digest,
                admission.route_profile_digest,
                admission.work_scope_digest,
                admission.authorization_identity_digest,
            )
        )
    ):
        raise ValueError("status transition admission identity is invalid")
    preimages, afterimages = _status_mutation_images(
        parent.targets,
        plan.current_projection_plan,
        plan.handoff_plan,
    )
    expected_mutation = build_mutation_plan(
        operation="work.status-transition",
        decision="READY" if plan.ready else "BLOCKED",
        admission_digest=admission.admission_digest,
        operation_digest=canonical_digest(
            {
                "operation": "work.status-transition",
                "work_id": parent.work_id,
                "expected_status": parent.expected_status,
                "new_status": parent.outcome,
                "result_ref": parent.result_ref,
                "current_projection_plan_digest": plan.current_projection_plan.plan_digest,
                "handoff_plan_digest": plan.handoff_plan.plan_digest,
            }
        ),
        target_preimages=preimages,
        target_afterimages=afterimages,
    )
    if plan.mutation_plan != expected_mutation:
        raise ValueError("status transition mutation plan integrity mismatch")
    aggregate_fields = {
        "schema_version": 2,
        "kind": "WorkStatusTransitionPlanV2",
        "parent_plan_digest": parent.plan_digest,
        "current_projection_plan_digest": plan.current_projection_plan.plan_digest,
        "handoff_plan_digest": plan.handoff_plan.plan_digest,
        "admission_digest": admission.admission_digest,
        "mutation_plan_digest": plan.mutation_plan.plan_digest,
        "target_refs": list(refs),
    }
    if plan.plan_digest != canonical_digest(aggregate_fields):
        raise ValueError("status transition aggregate plan integrity mismatch")


def _blocked_status_receipt(
    plan: WorkStatusTransitionPlanV2,
    authorization: WorkStatusTransitionAuthorizationV2,
    reason: str,
) -> WorkStatusTransitionReceiptV2:
    """准入失败不得消费 authorization，也不得伪装成普通异常。"""

    return WorkStatusTransitionReceiptV2(
        decision="BLOCKED",
        authorization_id=authorization.authorization_id,
        work_id=authorization.work_id,
        plan_digest=plan.plan_digest,
        planned_refs=plan.target_refs,
        actual_mutation_refs=(),
        parent_decision="BLOCKED",
        child_decision="NO_CHANGE",
        handoff_decision="NO_CHANGE",
        recovery_required=False,
        reason_codes=(reason,),
    )


def _recover_child_exception(
    root: Path,
    release_root: Path,
    *,
    plan: WorkStatusTransitionPlanV2,
    authorization: WorkStatusTransitionAuthorizationV2,
    manifest: dict[str, Any],
    current_child: Mapping[str, Any],
    handoff_child: Mapping[str, Any],
    failure: Exception,
) -> WorkStatusTransitionReceiptV2:
    """durable parent 后的普通 child 异常必须返回可审计 accounting。"""

    applied_refs = [
        *tuple(str(ref) for ref in current_child.get("applied_refs", ())),
        *tuple(str(ref) for ref in handoff_child.get("applied_refs", ())),
    ]
    failures: list[str] = []
    current_manifest: dict[str, Any] | None = None
    handoff_manifest: dict[str, Any] | None = None
    try:
        current_manifest = transaction_child.current_for_parent(
            release_root,
            authorization_id=authorization.authorization_id,
            parent_plan_digest=plan.parent_plan.plan_digest,
        )
        if current_manifest is not None:
            applied_refs.extend(str(ref) for ref in current_manifest.get("applied_refs", ()))
    except Exception as exc:  # noqa: BLE001 - inspector failure must remain typed
        failures.append(f"CURRENT_CHILD_INSPECT_FAILED:{exc}")
    try:
        handoff_manifest = transaction_child.handoff_for_parent(
            root,
            authorization_id=authorization.authorization_id,
            parent_plan_digest=plan.parent_plan.plan_digest,
        )
        if handoff_manifest is not None and handoff_manifest.get("applied"):
            applied_refs.extend(plan.handoff_plan.target_refs)
    except Exception as exc:  # noqa: BLE001 - inspector failure must remain typed
        failures.append(f"HANDOFF_CHILD_INSPECT_FAILED:{exc}")

    # parent 必须先进入 terminal，再允许任何 child rollback。
    manifest["state"] = "RECOVERED"
    manifest["failure"] = str(failure)
    manifest["recovery_failures"] = list(failures)
    manifest["updated_at"] = now_utc()
    _write_json_atomic(work_close_manifest_path(root, authorization.authorization_id), manifest)

    handoff_decision = str(handoff_child.get("decision", "NO_CHANGE"))
    current_decision = str(current_child.get("decision", "NO_CHANGE"))
    if handoff_manifest is not None and handoff_manifest.get("state") not in {
        "RECOVERED",
        "PARTIAL",
    }:
        try:
            result = transaction_child.recover_handoff(
                root,
                str(handoff_manifest["transaction_id"]),
            )
            handoff_decision = str(result["decision"])
            failures.extend(str(item) for item in result.get("reason_codes", ()))
        except Exception as exc:  # noqa: BLE001
            failures.append(f"HANDOFF_CHILD_RECOVERY_FAILED:{exc}")
            handoff_decision = "PARTIAL"
    if current_manifest is not None and current_manifest.get("state") not in {
        "RECOVERED",
        "PARTIAL",
    }:
        try:
            result = transaction_child.recover_current(
                release_root,
                str(current_manifest["transaction_id"]),
            )
            current_decision = str(result["decision"])
            failures.extend(str(item) for item in result.get("reason_codes", ()))
        except Exception as exc:  # noqa: BLE001
            failures.append(f"CURRENT_CHILD_RECOVERY_FAILED:{exc}")
            current_decision = "PARTIAL"
    recovered = not failures and handoff_decision != "PARTIAL" and current_decision != "PARTIAL"
    if not recovered:
        manifest["state"] = "PARTIAL"
        manifest["recovery_failures"] = failures
        manifest["updated_at"] = now_utc()
        _write_json_atomic(work_close_manifest_path(root, authorization.authorization_id), manifest)
    return WorkStatusTransitionReceiptV2(
        decision="RECOVERED" if recovered else "PARTIAL",
        authorization_id=authorization.authorization_id,
        work_id=authorization.work_id,
        plan_digest=plan.plan_digest,
        planned_refs=plan.target_refs,
        actual_mutation_refs=tuple(dict.fromkeys(applied_refs)),
        parent_decision=str(manifest["state"]),
        child_decision=current_decision,
        handoff_decision=handoff_decision,
        recovery_required=not recovered,
        reason_codes=(
            "WORK_STATUS_CHILD_APPLY_EXCEPTION",
            *(("WORK_STATUS_TRANSITION_RECOVERY_REQUIRED",) if not recovered else ()),
        ),
    )


def apply_work_status_transition(
    process_root: Path,
    plan: WorkStatusTransitionPlanV2,
    authorization: WorkStatusTransitionAuthorizationV2,
) -> WorkStatusTransitionReceiptV2:
    """在同一锁窗口内，以 durable parent 协调 alias child 与领域 parent。"""

    root = process_root.resolve()
    release_root = release_root_from_process(root)
    if not plan.ready:
        raise ValueError("blocked status transition plan cannot be applied")
    _validate_work_status_transition_plan(root, release_root, plan, verify_child_preimages=False)
    authorization.validate_for(plan.parent_plan)
    if (
        authorization.work_id != plan.parent_plan.work_id
        or authorization.plan_digest != plan.plan_digest
        or authorization.parent_plan_digest != plan.parent_plan.plan_digest
        or authorization.target_refs != plan.target_refs
    ):
        raise ValueError("status transition authorization does not bind exact plan")
    manifest_path = work_close_manifest_path(root, authorization.authorization_id)
    if manifest_path.exists() or manifest_path.is_symlink():
        raise ValueError("work close authorization_id was already consumed")

    writer_id = "work-status-" + sha256(authorization.authorization_id.encode()).hexdigest()[:32]
    shared_lock = acquire_shared_projection_writer_lock(root, writer_id)
    work_lock: Path | None = None
    state_lock = None
    child: dict[str, Any] = {
        "decision": "NO_CHANGE",
        "transaction_id": "",
        "applied_refs": [],
    }
    handoff_child: dict[str, Any] = {
        "decision": "NO_CHANGE",
        "transaction_id": "",
        "applied_refs": [],
    }
    manifest: dict[str, Any] | None = None
    try:
        work_lock = acquire_work_close_writer_lock(root, authorization.authorization_id)
        from meta_flow.state.projection_transaction import (
            acquire_transaction_lock,
            state_projection_lock_path,
        )

        state_lock = acquire_transaction_lock(
            state_projection_lock_path(release_root),
            sha256(f"work-status:{authorization.authorization_id}".encode()).hexdigest()[:32],
        )
        if manifest_path.exists() or manifest_path.is_symlink():
            raise ValueError("work close authorization_id was already consumed")
        try:
            _assert_work_transaction_admission_current(root, state_lock_handle=state_lock)
            if transaction_child.inspect_current(release_root)["decision"] != "PASS":
                raise ValueError("unresolved current projection transaction blocks admission")
            fresh = plan_work_status_transition(
                root,
                plan.parent_plan.work_id,
                expected_status=plan.parent_plan.expected_status,
                new_status=plan.parent_plan.outcome,
                result_ref=plan.parent_plan.result_ref,
                handoff=work_handoff.handoff_from_transition_plan(plan.handoff_plan),
                _state_lock_handle=state_lock,
            )
            if fresh.as_dict() != plan.as_dict():
                raise ValueError("status transition plan drifted before apply")
            _validate_work_status_transition_plan(
                root,
                release_root,
                plan,
                verify_child_preimages=True,
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return _blocked_status_receipt(
                plan,
                authorization,
                f"WORK_STATUS_FRESH_ADMISSION_FAILED:{exc}",
            )
        require_work_close_runtime_chain(root, authorization.authorization_id, create=True)
        manifest = build_work_close_manifest(root, plan.parent_plan, authorization)
        attach_before_bytes(root, manifest)
        child_transaction_id = transaction_child.current_transaction_id(
            plan.current_projection_plan,
            parent_plan_digest=plan.parent_plan.plan_digest,
            authorization_id=authorization.authorization_id,
        )
        handoff_transaction_id = transaction_child.handoff_transaction_id(
            plan.handoff_plan,
            parent_plan_digest=plan.parent_plan.plan_digest,
            authorization_id=authorization.authorization_id,
        )
        manifest.update(
            {
                "coordinator_plan_digest": plan.plan_digest,
                "operation_admission_digest": plan.admission.admission_digest,
                "mutation_plan_digest": plan.mutation_plan.plan_digest,
                "current_projection_plan_digest": plan.current_projection_plan.plan_digest,
                "current_projection_transaction_id": child_transaction_id,
                "handoff_plan_digest": plan.handoff_plan.plan_digest,
                "handoff_transaction_id": handoff_transaction_id,
                "handoff_route_policy_digest": plan.handoff_plan.route_policy_digest,
                "handoff_desired_digest": plan.handoff_plan.desired_digest,
            }
        )
        validate_work_close_manifest(manifest, expected_authorization_id=authorization.authorization_id)
        # 先持久化 coordinator identity；从此 authorization 已 single-use consumed。
        _write_json_atomic(manifest_path, manifest)

        if plan.current_projection_plan.targets:
            try:
                child = transaction_child.apply_current(
                    release_root,
                    plan.current_projection_plan,
                    parent_plan_digest=plan.parent_plan.plan_digest,
                    authorization_id=authorization.authorization_id,
                )
            except Exception as exc:  # noqa: BLE001 - durable parent requires typed accounting
                return _recover_child_exception(
                    root,
                    release_root,
                    plan=plan,
                    authorization=authorization,
                    manifest=manifest,
                    current_child=child,
                    handoff_child=handoff_child,
                    failure=exc,
                )
        if child["decision"] not in {"PASS", "NO_CHANGE"}:
            manifest["state"] = "PARTIAL" if child["decision"] == "PARTIAL" else "RECOVERED"
            manifest["failure"] = "current projection child apply failed"
            manifest["recovery_failures"] = list(child.get("reason_codes", ()))
            manifest["updated_at"] = now_utc()
            _write_json_atomic(manifest_path, manifest)
            return WorkStatusTransitionReceiptV2(
                decision=str(manifest["state"]),
                authorization_id=authorization.authorization_id,
                work_id=authorization.work_id,
                plan_digest=plan.plan_digest,
                planned_refs=plan.target_refs,
                actual_mutation_refs=tuple(child.get("applied_refs", ())),
                parent_decision=str(manifest["state"]),
                child_decision=str(child["decision"]),
                handoff_decision="NO_CHANGE",
                recovery_required=manifest["state"] == "PARTIAL",
                reason_codes=tuple(child.get("reason_codes", ())),
            )

        if plan.handoff_plan.target_ref:
            try:
                handoff_child = transaction_child.apply_handoff(
                    root,
                    plan.handoff_plan,
                    parent_plan_digest=plan.parent_plan.plan_digest,
                    authorization_id=authorization.authorization_id,
                )
            except Exception as exc:  # noqa: BLE001 - durable parent requires typed accounting
                return _recover_child_exception(
                    root,
                    release_root,
                    plan=plan,
                    authorization=authorization,
                    manifest=manifest,
                    current_child=child,
                    handoff_child=handoff_child,
                    failure=exc,
                )
        if handoff_child["decision"] not in {"PASS", "NO_CHANGE"}:
            # 领域 parent 尚未开始写；先终结 parent，再按 parent→child 顺序恢复。
            manifest["state"] = "RECOVERED"
            manifest["failure"] = "handoff child apply failed"
            manifest["recovery_failures"] = list(handoff_child.get("reason_codes", ()))
            manifest["updated_at"] = now_utc()
            _write_json_atomic(manifest_path, manifest)
            child_decision = str(child["decision"])
            if child_decision == "PASS":
                child_recovery = transaction_child.recover_current(
                    release_root,
                    str(child["transaction_id"]),
                )
                child_decision = str(child_recovery["decision"])
            recovered = handoff_child["decision"] == "RECOVERED" and child_decision in {
                "RECOVERED",
                "NO_CHANGE",
            }
            return WorkStatusTransitionReceiptV2(
                decision="RECOVERED" if recovered else "PARTIAL",
                authorization_id=authorization.authorization_id,
                work_id=authorization.work_id,
                plan_digest=plan.plan_digest,
                planned_refs=plan.target_refs,
                actual_mutation_refs=tuple(
                    (*child.get("applied_refs", ()), *handoff_child.get("applied_refs", ()))
                ),
                parent_decision="RECOVERED",
                child_decision=child_decision,
                handoff_decision=str(handoff_child["decision"]),
                recovery_required=not recovered,
                reason_codes=(
                    "HANDOFF_CHILD_APPLY_FAILED",
                    *(("WORK_STATUS_TRANSITION_RECOVERY_REQUIRED",) if not recovered else ()),
                ),
            )

        attempted: list[str] = []
        applied: list[str] = []
        try:
            manifest["state"] = "APPLYING"
            manifest["updated_at"] = now_utc()
            _write_json_atomic(manifest_path, manifest)
            for target in manifest["targets"]:
                path = root / target["ref"]
                if digest_bytes(path.read_bytes()) != target["before_digest"]:
                    raise ValueError(f"work close target preimage drift: {target['ref']}")
                attempted.append(target["ref"])
                manifest["attempted_refs"] = list(attempted)
                manifest["updated_at"] = now_utc()
                _write_json_atomic(manifest_path, manifest)
                _replace_bytes(path, base64.b64decode(target["after_bytes_b64"]))
                applied.append(target["ref"])
                manifest["applied_refs"] = list(applied)
                manifest["updated_at"] = now_utc()
                _write_json_atomic(manifest_path, manifest)
            manifest["state"] = "COMMITTED"
            manifest["updated_at"] = now_utc()
            _write_json_atomic(manifest_path, manifest)
            return WorkStatusTransitionReceiptV2(
                decision="PASS",
                authorization_id=authorization.authorization_id,
                work_id=authorization.work_id,
                plan_digest=plan.plan_digest,
                planned_refs=plan.target_refs,
                actual_mutation_refs=tuple(
                    (
                        *child.get("applied_refs", ()),
                        *handoff_child.get("applied_refs", ()),
                        *applied,
                    )
                ),
                parent_decision="PASS",
                child_decision=str(child["decision"]),
                handoff_decision=str(handoff_child["decision"]),
                recovery_required=False,
            )
        except Exception as exc:
            manifest["attempted_refs"] = list(attempted)
            manifest["applied_refs"] = list(applied)
            parent_recovered, failures = _rollback(root, manifest)
            manifest["state"] = "RECOVERED" if parent_recovered else "PARTIAL"
            manifest["failure"] = str(exc)
            manifest["recovery_failures"] = failures
            manifest["updated_at"] = now_utc()
            _write_json_atomic(manifest_path, manifest)
            child_decision = str(child["decision"])
            handoff_decision = str(handoff_child["decision"])
            if parent_recovered and handoff_decision == "PASS":
                handoff_recovery = transaction_child.recover_handoff(
                    root,
                    str(handoff_child["transaction_id"]),
                )
                handoff_decision = str(handoff_recovery["decision"])
            if parent_recovered and child_decision == "PASS":
                child_recovery = transaction_child.recover_current(
                    release_root,
                    str(child["transaction_id"]),
                )
                child_decision = str(child_recovery["decision"])
            recovered = (
                parent_recovered
                and handoff_decision in {"RECOVERED", "NO_CHANGE"}
                and child_decision in {"RECOVERED", "NO_CHANGE"}
            )
            return WorkStatusTransitionReceiptV2(
                decision="RECOVERED" if recovered else "PARTIAL",
                authorization_id=authorization.authorization_id,
                work_id=authorization.work_id,
                plan_digest=plan.plan_digest,
                planned_refs=plan.target_refs,
                actual_mutation_refs=tuple(
                    (
                        *child.get("applied_refs", ()),
                        *handoff_child.get("applied_refs", ()),
                        *applied,
                    )
                ),
                parent_decision=str(manifest["state"]),
                child_decision=child_decision,
                handoff_decision=handoff_decision,
                recovery_required=not recovered,
                reason_codes=(
                    "WORK_STATUS_TRANSITION_APPLY_FAILED",
                    *(("WORK_STATUS_TRANSITION_RECOVERY_REQUIRED",) if not recovered else ()),
                ),
            )
    finally:
        try:
            if state_lock is not None:
                from meta_flow.state.projection_transaction import release_transaction_lock

                release_transaction_lock(state_lock)
        finally:
            try:
                if work_lock is not None:
                    release_work_close_writer_lock(work_lock, authorization.authorization_id)
            finally:
                release_shared_projection_writer_lock(shared_lock, writer_id)


def _assert_work_transaction_admission_current(
    root: Path,
    *,
    state_lock_handle: Any,
) -> None:
    """在已持有 coordinator 锁时拒绝全部 unresolved/corrupted parent lineage。"""

    transaction_root = root / TRANSACTION_ROOT_REL
    if transaction_root.is_symlink() or (
        transaction_root.exists() and not transaction_root.is_dir()
    ):
        raise ValueError("work transaction runtime is unsafe")
    terminal: list[dict[str, Any]] = []
    if transaction_root.is_dir():
        for path in sorted(transaction_root.glob("*/manifest.json")):
            if path.parent.is_symlink() or path.is_symlink() or not path.is_file():
                raise ValueError("work transaction manifest path is unsafe")
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("work transaction manifest payload is invalid")
            validate_work_close_manifest(payload, expected_authorization_id=path.parent.name)
            if payload["state"] not in TERMINAL_TRANSACTION_STATES:
                raise ValueError(
                    "unresolved work transaction blocks admission: "
                    + str(payload["authorization_id"])
                )
            terminal.append(payload)
    lineage_errors = lineage_generation_errors(
        root,
        terminal,
        state_lock_handle=state_lock_handle,
    )
    if lineage_errors:
        raise ValueError("; ".join(lineage_errors))


def inspect_work_status_transitions(process_root: Path) -> dict[str, Any]:
    """单一库入口聚合 parent coordinator 与全部 child inspection。"""

    root = process_root.resolve()
    release_root = release_root_from_process(root)
    parent_report = inspect_work_close_transactions(root)
    child_report = transaction_child.inspect_current(release_root)
    handoff_report = transaction_child.inspect_handoff(root)
    transitions: list[dict[str, Any]] = []
    errors: list[str] = []
    transaction_root = root / TRANSACTION_ROOT_REL
    if transaction_root.is_dir() and not transaction_root.is_symlink():
        for path in sorted(transaction_root.glob("*/manifest.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("status transition manifest payload is invalid")
                validate_work_close_manifest(payload, expected_authorization_id=path.parent.name)
                if payload.get("operation") != "work.status-transition":
                    continue
                child = transaction_child.current_for_parent(
                    release_root,
                    authorization_id=path.parent.name,
                    parent_plan_digest=str(payload["plan_digest"]),
                )
                handoff_child = transaction_child.handoff_for_parent(
                    root,
                    authorization_id=path.parent.name,
                    parent_plan_digest=str(payload["plan_digest"]),
                )
                parent_state = str(payload["state"])
                child_state = "NO_CHANGE" if child is None else str(child["state"])
                handoff_state = (
                    "NO_CHANGE" if handoff_child is None else str(handoff_child["state"])
                )
                if (
                    parent_state == "COMMITTED"
                    and child is None
                    and payload["current_projection_plan_digest"]
                    != EMPTY_CURRENT_PROJECTION_PLAN_DIGEST
                ):
                    errors.append(
                        f"status transition committed child is missing: {path.parent.name}"
                    )
                if parent_state == "COMMITTED" and child_state not in {
                    "COMMITTED",
                    "NO_CHANGE",
                }:
                    errors.append(f"status transition parent/child diverged: {path.parent.name}")
                if (
                    parent_state == "COMMITTED"
                    and handoff_child is None
                    and payload["handoff_desired_digest"] != EMPTY_BYTES_DIGEST
                ):
                    errors.append(
                        f"status transition committed handoff child is missing: {path.parent.name}"
                    )
                if parent_state == "COMMITTED" and handoff_state not in {
                    "COMMITTED",
                    "NO_CHANGE",
                }:
                    errors.append(
                        f"status transition parent/handoff child diverged: {path.parent.name}"
                    )
                if (
                    handoff_child is not None
                    and handoff_child["transaction_id"] != payload["handoff_transaction_id"]
                ):
                    errors.append(
                        f"status transition handoff child identity diverged: {path.parent.name}"
                    )
                transitions.append(
                    {
                        "authorization_id": path.parent.name,
                        "work_id": str(payload["work_id"]),
                        "coordinator_plan_digest": str(payload["coordinator_plan_digest"]),
                        "parent_state": parent_state,
                        "child_state": child_state,
                        "child_transaction_id": (
                            "" if child is None else str(child["transaction_id"])
                        ),
                        "handoff_state": handoff_state,
                        "handoff_transaction_id": (
                            "" if handoff_child is None else str(handoff_child["transaction_id"])
                        ),
                    }
                )
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"invalid status transition coordinator {path}: {exc}")
    errors.extend(str(error) for error in parent_report.get("errors", ()))
    errors.extend(str(error) for error in child_report.get("findings", ()))
    errors.extend(str(error) for error in handoff_report.get("findings", ()))
    return {
        "schema_version": 2,
        "kind": "WorkStatusTransitionInspectionV2",
        "decision": "BLOCKED" if errors else "PASS",
        "transitions": transitions,
        "errors": list(dict.fromkeys(errors)),
        "mutation_count": 0,
    }


def recover_work_status_transition(
    process_root: Path,
    authorization_id: str,
) -> WorkStatusTransitionReceiptV2:
    """按 parent 后 child 顺序恢复被中断的 status-transition coordinator。"""

    root = process_root.resolve()
    release_root = release_root_from_process(root)
    path = work_close_manifest_path(root, authorization_id)
    if path.is_symlink() or not path.is_file():
        raise ValueError("status transition coordinator manifest is missing")
    initial = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(initial, dict):
        raise ValueError("status transition coordinator manifest is invalid")
    validate_work_close_manifest(initial, expected_authorization_id=authorization_id)
    if initial.get("operation") != "work.status-transition":
        raise ValueError("transaction is not a status transition coordinator")

    writer_id = "work-status-recover-" + sha256(authorization_id.encode()).hexdigest()[:24]
    shared_lock = acquire_shared_projection_writer_lock(root, writer_id)
    work_lock: Path | None = None
    state_lock = None
    try:
        work_lock = acquire_work_close_writer_lock(root, authorization_id)
        from meta_flow.state.projection_transaction import (
            acquire_transaction_lock,
            state_projection_lock_path,
        )

        state_lock = acquire_transaction_lock(
            state_projection_lock_path(release_root),
            sha256(f"work-status-recover:{authorization_id}".encode()).hexdigest()[:32],
        )
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("status transition coordinator manifest is invalid")
        validate_work_close_manifest(manifest, expected_authorization_id=authorization_id)
        parent_state = str(manifest["state"])
        if parent_state == "COMMITTED":
            child = transaction_child.current_for_parent(
                release_root,
                authorization_id=authorization_id,
                parent_plan_digest=str(manifest["plan_digest"]),
            )
            if child is not None and child["state"] != "COMMITTED":
                raise ValueError("committed parent owns a non-committed child")
            if (
                child is None
                and manifest["current_projection_plan_digest"]
                != EMPTY_CURRENT_PROJECTION_PLAN_DIGEST
            ):
                raise ValueError("committed parent current projection child is missing")
            handoff_child = transaction_child.handoff_for_parent(
                root,
                authorization_id=authorization_id,
                parent_plan_digest=str(manifest["plan_digest"]),
            )
            if handoff_child is not None and handoff_child["state"] != "COMMITTED":
                raise ValueError("committed parent owns a non-committed handoff child")
            if handoff_child is None and manifest["handoff_desired_digest"] != EMPTY_BYTES_DIGEST:
                raise ValueError("committed parent handoff child is missing")
            return WorkStatusTransitionReceiptV2(
                decision="NO_CHANGE",
                authorization_id=authorization_id,
                work_id=str(manifest["work_id"]),
                plan_digest=str(manifest["coordinator_plan_digest"]),
                planned_refs=tuple(target["ref"] for target in manifest["targets"]),
                actual_mutation_refs=(),
                parent_decision="COMMITTED",
                child_decision="NO_CHANGE" if child is None else "COMMITTED",
                handoff_decision=("NO_CHANGE" if handoff_child is None else "COMMITTED"),
                recovery_required=False,
            )

        parent_recovered, failures = _rollback(root, manifest)
        manifest["state"] = "RECOVERED" if parent_recovered else "PARTIAL"
        manifest["updated_at"] = now_utc()
        manifest["recovery_failures"] = failures
        _write_json_atomic(path, manifest)
        child = transaction_child.current_for_parent(
            release_root,
            authorization_id=authorization_id,
            parent_plan_digest=str(manifest["plan_digest"]),
        )
        handoff_child = transaction_child.handoff_for_parent(
            root,
            authorization_id=authorization_id,
            parent_plan_digest=str(manifest["plan_digest"]),
        )
        child_decision = "NO_CHANGE"
        handoff_decision = "NO_CHANGE"
        child_refs: tuple[str, ...] = ()
        handoff_refs: tuple[str, ...] = ()
        if parent_recovered and handoff_child is not None:
            handoff_plan = work_handoff.HandoffTransitionPlanV1.from_mapping(
                dict(handoff_child["plan"])
            )
            handoff_refs = handoff_plan.target_refs
            handoff_recovery = transaction_child.recover_handoff(
                root,
                str(handoff_child["transaction_id"]),
            )
            handoff_decision = str(handoff_recovery["decision"])
        if parent_recovered and child is not None:
            child_refs = tuple(child.get("applied_refs", ()))
            child_recovery = transaction_child.recover_current(
                release_root,
                str(child["transaction_id"]),
            )
            child_decision = str(child_recovery["decision"])
        recovered = (
            parent_recovered
            and handoff_decision in {"RECOVERED", "NO_CHANGE"}
            and child_decision in {"RECOVERED", "NO_CHANGE"}
        )
        return WorkStatusTransitionReceiptV2(
            decision="RECOVERED" if recovered else "PARTIAL",
            authorization_id=authorization_id,
            work_id=str(manifest["work_id"]),
            plan_digest=str(manifest["coordinator_plan_digest"]),
            planned_refs=tuple(
                dict.fromkeys(
                    (
                        *(target["ref"] for target in manifest["targets"]),
                        *(target["ref"] for target in (child or {}).get("targets", ())),
                        *handoff_refs,
                    )
                )
            ),
            actual_mutation_refs=tuple(
                (*child_refs, *handoff_refs, *manifest.get("applied_refs", ()))
            ),
            parent_decision=str(manifest["state"]),
            child_decision=child_decision,
            handoff_decision=handoff_decision,
            recovery_required=not recovered,
            reason_codes=(() if recovered else ("WORK_STATUS_TRANSITION_RECOVERY_REQUIRED",)),
        )
    finally:
        try:
            if state_lock is not None:
                from meta_flow.state.projection_transaction import release_transaction_lock

                release_transaction_lock(state_lock)
        finally:
            try:
                if work_lock is not None:
                    release_work_close_writer_lock(work_lock, authorization_id)
            finally:
                release_shared_projection_writer_lock(shared_lock, writer_id)
