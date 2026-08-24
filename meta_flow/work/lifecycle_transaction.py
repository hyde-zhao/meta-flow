"""Work 关闭的可恢复多对象事务。
本模块只拥有 Work close 的 plan/authorization/apply/recovery。CR status-sync 与
CR termination 保留各自既有 owner；统一检查入口只聚合它们的事务状态，不接管
其领域语义。
"""

from __future__ import annotations

import base64
import warnings
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, ClassVar, Protocol

from meta_flow.execution_control.contract import canonical_digest
from meta_flow.execution_control.primitives import (
    SHARED_WRITER_LOCK_REL as SHARED_WRITER_LOCK_REL,
    SharedProjectionWriterLock,
    acquire_shared_projection_writer_lock,
    acquire_writer_lock,
    digest_bytes,
    ensure_runtime_chain,
    fsync_directory,
    manifest_path,
    now_utc,
    plan_digest,
    release_shared_projection_writer_lock,
    release_writer_lock,
    render_yaml_bytes,
    safe_authorization_id,
    validate_shared_projection_writer_lock,
    write_atomic,
    write_json_atomic,
    replace_bytes,
    DIGEST_RE,
)
from meta_flow.execution_control.operation_admission import (
    OperationAdmissionV1,
    provider_source_identity_digest,
    repository_head_oid,
)
from meta_flow.project.governance import load_phase
from meta_flow.project.governance_projection import (
    GOVERNANCE_PROJECTION_REL,
    build_governance_projection_for_phase_postimage,
    render_governance_projection,
)
from meta_flow.project.model import is_safe_ref, load_project
from meta_flow.project.scale import load_yaml_object
from meta_flow.semantics.generation_lineage import committed_generation_heads
from meta_flow.state import current as state_current
from meta_flow.state.formal_projection import (
    build_formal_truth_snapshot,
    derive_formal_truth_patch,
)
from meta_flow.work.lifecycle import transition_work
from meta_flow.work.model import load_work, with_status

TRANSACTION_SCHEMA_VERSION = 1
AUTHORIZATION_KIND = "work-close-authorization-v1"
TRANSACTION_ROOT_REL = Path(".meta-flow-runtime/work-close/transactions")
HANDOFF_TRANSACTION_ROOT_REL = Path(".meta-flow-runtime/work-handoff")
SUCCESSOR_ROOT_REL = Path(".meta-flow-runtime/work-close/successors")
LOCK_REL = Path(".meta-flow-runtime/work-close/writer.lock")
TERMINAL_TRANSACTION_STATES = {"COMMITTED", "RECOVERED"}
TRANSACTION_STATES = {"PREPARED", "APPLYING", "PARTIAL", *TERMINAL_TRANSACTION_STATES}
_MANIFEST_FIELDS = {
    "schema_version",
    "kind",
    "authorization_id",
    "work_id",
    "plan_digest",
    "state",
    "created_at",
    "updated_at",
    "attempted_refs",
    "applied_refs",
    "targets",
}
_MANIFEST_OPTIONAL_FIELDS = {
    "failure",
    "recovery_failures",
    "lineage",
    "operation",
    "publication_binding",
    "coordinator_plan_digest",
    "operation_admission_digest",
    "mutation_plan_digest",
    "current_projection_plan_digest",
    "current_projection_transaction_id",
    "handoff_plan_digest",
    "handoff_transaction_id",
    "handoff_route_policy_digest",
    "handoff_desired_digest",
}
_TARGET_FIELDS = {
    "ref",
    "before_digest",
    "after_digest",
    "before_bytes_b64",
    "after_bytes_b64",
}
_SUCCESSOR_FIELDS = {
    "schema_version",
    "kind",
    "successor_id",
    "operation",
    "created_at",
    "targets",
}
_SUCCESSOR_IDENTITY_FIELDS = {"writer_id", "work_id"}
_SUCCESSOR_TARGET_FIELDS = {
    "ref",
    "anchor_close_authorization_id",
    "predecessor_successor_id",
    "before_digest",
    "after_digest",
    "after_bytes_b64",
}
STATE_CURRENT_REF = "state/STATE.current.json"
STATE_MD_REF = "STATE.md"
CURRENT_REF = "current/CURRENT.json"
STATE_PROJECTION_REFS = (STATE_CURRENT_REF, STATE_MD_REF, CURRENT_REF)
SHARED_SUCCESSOR_OPERATIONS = frozenset(
    {
        "work.init",
        "work.status-transition",
        "project.phase-transition",
        "project.phase-metadata",
        "shared-projection.repair",
    }
)
PHASE_METADATA_MANIFEST_REL = Path(".meta-flow-runtime/phase-metadata/transaction.json")
EMPTY_CURRENT_PROJECTION_PLAN_DIGEST = canonical_digest(
    {"schema_version": 2, "kind": "CurrentProjectionPlanV2", "targets": []}
)

# P0 原语收敛兼容层：旧私有名保留一个版本周期后删除（fault-injection seam 不变）。
_DIGEST_RE = DIGEST_RE
_digest_bytes = digest_bytes
_render = render_yaml_bytes
_now = now_utc
_safe_authorization_id = safe_authorization_id
_plan_digest = plan_digest
_fsync_directory = fsync_directory
_write_atomic = write_atomic
_write_json_atomic = write_json_atomic
_replace_bytes = replace_bytes


def release_root_from_process(root: Path) -> Path:
    metadata = load_yaml_object(root / ".meta-flow-process.yaml")
    release = metadata.get("release_repo")
    if not isinstance(release, Mapping):
        raise ValueError("process metadata release_repo is invalid")
    if release.get("anchor") != "workspace_parent":
        raise ValueError("process metadata release_repo anchor is invalid")
    relative = str(release.get("relative_path") or "")
    path = Path(relative)
    if (
        not relative
        or path.is_absolute()
        or len(path.parts) != 1
        or path.parts[0] in {"", ".", ".."}
    ):
        raise ValueError("process metadata release_repo relative_path is invalid")
    release_root = (root.parent / relative).resolve()
    if release_root.parent != root.parent or not release_root.is_dir():
        raise ValueError("process metadata release repository is unavailable")
    return release_root


def build_state_projection_candidates(
    root: Path,
    *,
    object_overrides: Mapping[str, tuple[dict[str, Any], bytes]],
) -> list[tuple[str, bytes]]:
    existing = [root / ref for ref in STATE_PROJECTION_REFS]
    present = [path.is_file() and not path.is_symlink() for path in existing]
    if not any(present):
        return []
    if not all(present):
        raise ValueError("State projection target set is incomplete before Work close")

    release_root = _release_root_from_process(root)
    state = state_current.load_current_state(release_root)
    if not state:
        raise ValueError("STATE.current.json is invalid before Work close")
    formal_snapshot = build_formal_truth_snapshot(
        release_root,
        process_root=root,
        object_overrides=object_overrides,
    )
    patch = derive_formal_truth_patch(state, formal_snapshot)
    state_candidate = state_current.build_current_state_candidate(
        release_root,
        patch,
        actor="meta_flow.work.lifecycle_transaction",
        reason="atomic Work close formal projection",
        base_state=state,
    )
    current_entry = state_current.build_current_entry(
        release_root,
        state_snapshot=state_candidate,
    )
    return [
        (
            STATE_CURRENT_REF,
            state_current.render_current_state_candidate(state_candidate).encode("utf-8"),
        ),
        (STATE_MD_REF, state_current.render_state_markdown(state_candidate).encode("utf-8")),
        (
            CURRENT_REF,
            (json.dumps(current_entry, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
                "utf-8"
            ),
        ),
    ]


def refresh_state_projection_if_initialized(process_root: Path) -> tuple[str, ...]:
    """正式真相 writer 成功后，同步已初始化的 State/CURRENT 三目标。"""

    root = process_root.resolve()
    paths = [root / ref for ref in STATE_PROJECTION_REFS]
    present = [path.is_file() and not path.is_symlink() for path in paths]
    if not any(present):
        return ()
    if not all(present):
        raise ValueError("State projection target set is incomplete after formal truth mutation")
    before = {ref: (root / ref).read_bytes() for ref in STATE_PROJECTION_REFS}
    release_root = _release_root_from_process(root)
    state_current.refresh_formal_truth_projection(release_root)
    return tuple(ref for ref in STATE_PROJECTION_REFS if (root / ref).read_bytes() != before[ref])


@dataclass(frozen=True, slots=True)
class WorkCloseTargetV1:
    ref: str
    before_digest: str
    after_digest: str
    after_bytes: bytes

    def as_plan_dict(self) -> dict[str, str]:
        return {
            "ref": self.ref,
            "before_digest": self.before_digest,
            "after_digest": self.after_digest,
        }


@dataclass(frozen=True, slots=True)
class WorkPublicationBindingV1:
    """专用 publication-close 冻结的不可变恢复上下文。"""

    work_id: str
    scope_digest: str
    result_ref: str
    handoff_ref: str
    handoff_digest: str
    publication_receipt_ref: str
    publication_receipt_digest: str
    repository_facts_digest: str
    paused_oids: tuple[tuple[str, str], ...]
    published_oids: tuple[tuple[str, str], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "WorkPublicationBindingV1",
            "work_id": self.work_id,
            "scope_digest": self.scope_digest,
            "result_ref": self.result_ref,
            "handoff_ref": self.handoff_ref,
            "handoff_digest": self.handoff_digest,
            "publication_receipt_ref": self.publication_receipt_ref,
            "publication_receipt_digest": self.publication_receipt_digest,
            "repository_facts_digest": self.repository_facts_digest,
            "paused_oids": dict(self.paused_oids),
            "published_oids": dict(self.published_oids),
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> WorkPublicationBindingV1:
        expected = {
            "schema_version",
            "kind",
            "work_id",
            "scope_digest",
            "result_ref",
            "handoff_ref",
            "handoff_digest",
            "publication_receipt_ref",
            "publication_receipt_digest",
            "repository_facts_digest",
            "paused_oids",
            "published_oids",
        }
        if set(payload) != expected:
            raise ValueError("publication binding fields mismatch")
        if payload.get("schema_version") != 1 or payload.get("kind") != "WorkPublicationBindingV1":
            raise ValueError("publication binding kind/version mismatch")
        work_id = _safe_authorization_id(str(payload.get("work_id") or ""))
        result_ref = str(payload.get("result_ref") or "")
        handoff_ref = str(payload.get("handoff_ref") or "")
        receipt_ref = str(payload.get("publication_receipt_ref") or "")
        if not all(is_safe_ref(ref) for ref in (result_ref, handoff_ref, receipt_ref)):
            raise ValueError("publication binding contains an unsafe ref")
        digests = {
            str(payload.get("scope_digest") or ""),
            str(payload.get("handoff_digest") or ""),
            str(payload.get("publication_receipt_digest") or ""),
            str(payload.get("repository_facts_digest") or ""),
        }
        if any(not _DIGEST_RE.fullmatch(value) for value in digests):
            raise ValueError("publication binding digest is invalid")
        oid_sets: list[tuple[tuple[str, str], ...]] = []
        for key in ("paused_oids", "published_oids"):
            value = payload.get(key)
            if not isinstance(value, Mapping) or set(value) != {"release", "process"}:
                raise ValueError(f"publication binding {key} fields mismatch")
            normalized = tuple((role, str(value[role])) for role in ("release", "process"))
            if any(
                not re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", oid) for _role, oid in normalized
            ):
                raise ValueError(f"publication binding {key} OID is invalid")
            oid_sets.append(normalized)
        return cls(
            work_id=work_id,
            scope_digest=str(payload["scope_digest"]),
            result_ref=result_ref,
            handoff_ref=handoff_ref,
            handoff_digest=str(payload["handoff_digest"]),
            publication_receipt_ref=receipt_ref,
            publication_receipt_digest=str(payload["publication_receipt_digest"]),
            repository_facts_digest=str(payload["repository_facts_digest"]),
            paused_oids=oid_sets[0],
            published_oids=oid_sets[1],
        )


@dataclass(frozen=True, slots=True)
class WorkClosePlanV1:
    operation: str
    decision: str
    work_id: str
    expected_status: str
    outcome: str
    result_ref: str
    targets: tuple[WorkCloseTargetV1, ...]
    lineage: tuple[tuple[str, str], ...]
    blockers: tuple[str, ...]
    plan_digest: str
    publication_binding: WorkPublicationBindingV1 | None = None

    @property
    def ready(self) -> bool:
        return self.decision == "READY" and not self.blockers

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": TRANSACTION_SCHEMA_VERSION,
            "operation": self.operation,
            "decision": self.decision,
            "work_id": self.work_id,
            "expected_status": self.expected_status,
            "outcome": self.outcome,
            "result_ref": self.result_ref,
            "targets": [target.as_plan_dict() for target in self.targets],
            "lineage": dict(self.lineage),
            "blockers": list(self.blockers),
            "plan_digest": self.plan_digest,
            "publication_binding": (
                None if self.publication_binding is None else self.publication_binding.as_dict()
            ),
            "mutation_count": 0,
        }


@dataclass(frozen=True, slots=True)
class WorkCloseAuthorizationV1:
    schema_version: int
    kind: str
    authorization_id: str
    work_id: str
    plan_digest: str
    target_refs: tuple[str, ...]
    expires_at: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> WorkCloseAuthorizationV1:
        expected = {
            "schema_version",
            "kind",
            "authorization_id",
            "work_id",
            "plan_digest",
            "target_refs",
            "expires_at",
        }
        if set(payload) != expected:
            raise ValueError("work close authorization fields mismatch")
        refs = payload["target_refs"]
        if not isinstance(refs, list) or not all(isinstance(ref, str) for ref in refs):
            raise ValueError("target_refs must be a list of strings")
        return cls(
            schema_version=int(payload["schema_version"]),
            kind=str(payload["kind"]),
            authorization_id=_safe_authorization_id(str(payload["authorization_id"])),
            work_id=str(payload["work_id"]),
            plan_digest=str(payload["plan_digest"]),
            target_refs=tuple(refs),
            expires_at=str(payload["expires_at"]),
        )

    def validate_for(self, plan: WorkClosePlanV1) -> None:
        if plan.operation != "work.close" or plan.publication_binding is not None:
            raise ValueError("standard work close authorization cannot approve publication-close")
        if self.schema_version != TRANSACTION_SCHEMA_VERSION or self.kind != AUTHORIZATION_KIND:
            raise ValueError("work close authorization kind/version mismatch")
        if self.work_id != plan.work_id or self.plan_digest != plan.plan_digest:
            raise ValueError("work close authorization does not bind the current plan")
        if self.target_refs != tuple(target.ref for target in plan.targets):
            raise ValueError("work close authorization target_refs mismatch")
        try:
            expiry = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("work close authorization expires_at is invalid") from exc
        if expiry.tzinfo is None or expiry.astimezone(UTC) <= datetime.now(UTC):
            raise ValueError("work close authorization is expired")


class WorkCloseAuthorizationProtocol(Protocol):
    authorization_id: str

    def validate_for(self, plan: WorkClosePlanV1) -> None: ...


@dataclass(frozen=True, slots=True)
class WorkCloseReceiptV1:
    decision: str
    authorization_id: str
    work_id: str
    plan_digest: str
    mutation_count: int
    applied_refs: tuple[str, ...]
    recovery_required: bool
    reason_codes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": TRANSACTION_SCHEMA_VERSION,
            "decision": self.decision,
            "authorization_id": self.authorization_id,
            "work_id": self.work_id,
            "plan_digest": self.plan_digest,
            "mutation_count": self.mutation_count,
            "applied_refs": list(self.applied_refs),
            "recovery_required": self.recovery_required,
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True, slots=True)
class SharedProjectionRepairTargetV1:
    ref: str
    anchor_close_authorization_id: str
    predecessor_successor_id: str
    predecessor_digest: str
    current_digest: str

    def as_dict(self) -> dict[str, str]:
        return {
            "ref": self.ref,
            "anchor_close_authorization_id": self.anchor_close_authorization_id,
            "predecessor_successor_id": self.predecessor_successor_id,
            "predecessor_digest": self.predecessor_digest,
            "current_digest": self.current_digest,
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> SharedProjectionRepairTargetV1:
        if set(payload) != {
            "ref",
            "anchor_close_authorization_id",
            "predecessor_successor_id",
            "predecessor_digest",
            "current_digest",
        }:
            raise ValueError("shared projection repair target fields mismatch")
        target = cls(
            str(payload.get("ref") or ""),
            str(payload.get("anchor_close_authorization_id") or ""),
            str(payload.get("predecessor_successor_id") or ""),
            str(payload.get("predecessor_digest") or ""),
            str(payload.get("current_digest") or ""),
        )
        parts = Path(target.ref).parts
        if (
            not _is_shared_projection_ref(target.ref)
            or target.ref in STATE_PROJECTION_REFS
            or not _safe_authorization_id(target.anchor_close_authorization_id)
            or (
                target.predecessor_successor_id
                and not _safe_authorization_id(target.predecessor_successor_id)
            )
            or not _DIGEST_RE.fullmatch(target.predecessor_digest)
            or not _DIGEST_RE.fullmatch(target.current_digest)
            or target.predecessor_digest == target.current_digest
            or target.ref.startswith("works/")
            or (len(parts) == 3 and parts[0] == "works")
        ):
            raise ValueError("shared projection repair target is invalid")
        return target


@dataclass(frozen=True, slots=True)
class SharedProjectionRepairPlanV1:
    classification: str
    targets: tuple[SharedProjectionRepairTargetV1, ...]
    blockers: tuple[str, ...]
    admission: OperationAdmissionV1
    plan_digest: str

    @property
    def ready(self) -> bool:
        return self.classification == "COMMITTED_STALE_REPAIRABLE" and not self.blockers

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "SharedProjectionRepairPlanV1",
            "decision": "READY" if self.ready else "BLOCKED",
            "classification": self.classification,
            "targets": [target.as_dict() for target in self.targets],
            "blockers": list(self.blockers),
            "admission": self.admission.as_dict(),
            "admission_digest": self.admission.admission_digest,
            "plan_digest": self.plan_digest,
            "mutation_count": 0,
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> SharedProjectionRepairPlanV1:
        if (
            set(payload)
            != {
                "schema_version",
                "kind",
                "decision",
                "classification",
                "targets",
                "blockers",
                "admission",
                "admission_digest",
                "plan_digest",
                "mutation_count",
            }
            or payload.get("schema_version") != 1
            or payload.get("kind") != "SharedProjectionRepairPlanV1"
        ):
            raise ValueError("shared projection repair plan fields mismatch")
        raw_targets = payload.get("targets")
        blockers = payload.get("blockers")
        if (
            not isinstance(raw_targets, list)
            or not isinstance(blockers, list)
            or any(not isinstance(item, str) for item in blockers)
        ):
            raise ValueError("shared projection repair plan collections are invalid")
        targets = tuple(SharedProjectionRepairTargetV1.from_mapping(item) for item in raw_targets)
        raw_admission = payload.get("admission")
        if not isinstance(raw_admission, Mapping) or set(raw_admission) != {
            "schema_version",
            "snapshot_digest",
            "release_oid",
            "process_oid",
            "provider_identity_digest",
            "route_profile_digest",
            "work_scope_digest",
            "authorization_identity_digest",
        }:
            raise ValueError("shared projection repair admission fields mismatch")
        admission = OperationAdmissionV1(
            snapshot_digest=str(raw_admission.get("snapshot_digest") or ""),
            release_oid=str(raw_admission.get("release_oid") or ""),
            process_oid=str(raw_admission.get("process_oid") or ""),
            provider_identity_digest=str(raw_admission.get("provider_identity_digest") or ""),
            route_profile_digest=str(raw_admission.get("route_profile_digest") or ""),
            work_scope_digest=str(raw_admission.get("work_scope_digest") or ""),
            authorization_identity_digest=str(
                raw_admission.get("authorization_identity_digest") or ""
            ),
        )
        classification = str(payload.get("classification") or "")
        if classification not in {
            "COMMITTED_CURRENT",
            "COMMITTED_STALE_REPAIRABLE",
            "SUPERSEDED",
            "PARTIAL",
            "CORRUPTED",
        }:
            raise ValueError("shared projection repair classification is invalid")
        fields = {
            "schema_version": 1,
            "kind": "SharedProjectionRepairPlanV1",
            "classification": classification,
            "targets": [target.as_dict() for target in targets],
            "blockers": blockers,
            "admission": admission.as_dict(),
            "admission_digest": admission.admission_digest,
        }
        plan_digest = str(payload.get("plan_digest") or "")
        plan = cls(classification, targets, tuple(blockers), admission, plan_digest)
        if (
            canonical_digest(fields) != plan_digest
            or payload.get("admission_digest") != admission.admission_digest
            or payload.get("decision") != ("READY" if plan.ready else "BLOCKED")
            or payload.get("mutation_count") != 0
        ):
            raise ValueError("shared projection repair plan integrity mismatch")
        return plan


@dataclass(frozen=True, slots=True)
class SharedProjectionRepairAuthorizationV1:
    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "SharedProjectionRepairAuthorizationV1"
    authorization_id: str
    plan_digest: str
    target_refs: tuple[str, ...]
    expires_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "authorization_id": self.authorization_id,
            "plan_digest": self.plan_digest,
            "target_refs": list(self.target_refs),
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> SharedProjectionRepairAuthorizationV1:
        if (
            set(payload)
            != {
                "schema_version",
                "kind",
                "authorization_id",
                "plan_digest",
                "target_refs",
                "expires_at",
            }
            or payload.get("schema_version") != 1
            or payload.get("kind") != cls.kind
        ):
            raise ValueError("shared projection repair authorization fields mismatch")
        refs = payload.get("target_refs")
        if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
            raise ValueError("shared projection repair authorization targets are invalid")
        return cls(
            str(payload.get("authorization_id") or ""),
            str(payload.get("plan_digest") or ""),
            tuple(refs),
            str(payload.get("expires_at") or ""),
        )

    def validate_for(self, plan: SharedProjectionRepairPlanV1) -> None:
        _safe_authorization_id(self.authorization_id)
        if (
            not plan.ready
            or self.plan_digest != plan.plan_digest
            or self.target_refs != tuple(target.ref for target in plan.targets)
            or not _DIGEST_RE.fullmatch(self.plan_digest)
        ):
            raise ValueError("shared projection repair authorization binding mismatch")
        try:
            expiry = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(
                "shared projection repair authorization expires_at is invalid"
            ) from exc
        if expiry.tzinfo is None or expiry.astimezone(UTC) <= datetime.now(UTC):
            raise ValueError("shared projection repair authorization is expired")


@dataclass(frozen=True, slots=True)
class SharedProjectionRepairReceiptV1:
    decision: str
    authorization_id: str
    plan_digest: str
    successor_id: str
    target_refs: tuple[str, ...]
    mutation_count: int
    post_classification: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "SharedProjectionRepairReceiptV1",
            "decision": self.decision,
            "authorization_id": self.authorization_id,
            "plan_digest": self.plan_digest,
            "successor_id": self.successor_id,
            "target_refs": list(self.target_refs),
            "mutation_count": self.mutation_count,
            "post_classification": self.post_classification,
        }


def _canonical_result_ref(result_ref: str) -> str:
    """MF-BUG-14：result_ref 统一消费 canonical ``process/...`` logical ref。

    过程仓相对路径（如 ``works/X/RESULT.yaml``）保留为显式 legacy 形态并发出
    DeprecationWarning；绝对路径、越界与 ``..`` 段一律拒绝。
    """

    if not result_ref:
        raise ValueError("completed Work requires result_ref")
    if result_ref.startswith("process/"):
        inner = result_ref[len("process/") :]
        if not is_safe_ref(inner):
            raise ValueError(f"Work result_ref escapes process root: {result_ref}")
        return inner
    if is_safe_ref(result_ref):
        warnings.warn(
            "result_ref as process-relative path is legacy; "
            "use the canonical process/... logical ref",
            DeprecationWarning,
            stacklevel=3,
        )
        return result_ref
    raise ValueError(f"Work result_ref is not a safe logical ref: {result_ref}")


def _validate_result(process_root: Path, work_id: str, outcome: str, result_ref: str) -> None:
    if outcome not in {"completed", "cancelled"}:
        raise ValueError("outcome must be completed or cancelled")
    if outcome == "cancelled":
        if result_ref:
            raise ValueError("cancelled Work must not add result_ref")
        return
    canonical = _canonical_result_ref(result_ref)
    path = process_root.resolve() / canonical
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Work result is missing or not regular: {result_ref}")
    payload = load_yaml_object(path)
    # MF-BUG-11：接受闭合超集 schema——必填字段（schema_version/work_id/decision）
    # 缺失或不匹配仍 fail closed；实现证据新增字段（如 summary、evidence_ref）容忍。
    required = {"schema_version", "work_id", "decision"}
    if (
        not required.issubset(payload)
        or payload.get("schema_version") != 1
        or payload.get("work_id") != work_id
        or payload.get("decision") != "PASS"
    ):
        raise ValueError("completed Work requires one exact matching PASS result")


def plan_work_close(
    process_root: Path,
    work_id: str,
    *,
    expected_status: str,
    outcome: str,
    result_ref: str = "",
    _publication_binding: WorkPublicationBindingV1 | None = None,
) -> WorkClosePlanV1:
    """只读生成 Work/Project/Phase 的完整关闭候选。"""

    # MF-BUG-14：canonical 与 legacy 两种输入形态在此收敛为同一内部形态，
    # 保证 plan/digest/WORK.yaml 语义与既有消费方完全一致。
    result_ref = _canonical_result_ref(result_ref) if outcome == "completed" else result_ref
    root = process_root.resolve()
    blockers: list[str] = []
    targets: list[WorkCloseTargetV1] = []
    try:
        _validate_result(root, work_id, outcome, result_ref)
        current = load_work(root, work_id)
        already_closed = current.status == outcome and (
            outcome == "cancelled" or current.result_ref == result_ref
        )
        if already_closed:
            closed = current
        elif _publication_binding is not None:
            if expected_status != "paused" or current.status != "paused" or outcome != "completed":
                raise ValueError("publication-close requires paused -> completed")
            if (
                _publication_binding.work_id != current.work_id
                or _publication_binding.scope_digest != current.scope.digest
                or _publication_binding.result_ref != result_ref
            ):
                raise ValueError("publication-close binding does not match Work/scope/result")
            closed = with_status(current, outcome, result_ref=result_ref)
        else:
            if current.status != expected_status:
                raise ValueError(
                    f"Work status changed: expected {expected_status}, current {current.status}"
                )
            closed = transition_work(current, outcome, result_ref=result_ref)

        project = load_project(root)
        updated_project = replace(
            project,
            active_work_refs=tuple(
                ref for ref in project.active_work_refs if ref != closed.work_ref
            ),
        )
        candidates: list[tuple[str, bytes]] = [
            (closed.work_ref, _render(closed.as_dict())),
            ("PROJECT.yaml", _render(updated_project.as_dict())),
        ]
        overrides: dict[str, tuple[dict[str, Any], bytes]] = {
            "process/PROJECT.yaml": (
                updated_project.as_dict(),
                _render(updated_project.as_dict()),
            ),
            "process/" + closed.work_ref: (
                closed.as_dict(),
                _render(closed.as_dict()),
            ),
        }
        if closed.phase_ref:
            phase = load_phase(root, closed.phase_ref)
            phase_results = phase.result_refs
            if result_ref and result_ref not in phase_results:
                phase_results = (*phase_results, result_ref)
            updated_phase = replace(
                phase,
                work_refs=tuple(ref for ref in phase.work_refs if ref != closed.work_ref),
                result_refs=phase_results,
            )
            candidates.append((closed.phase_ref, _render(updated_phase.as_dict())))
            baseline_ref = GOVERNANCE_PROJECTION_REL.as_posix()
            if phase.status == "active" and result_ref and baseline_ref in phase.result_refs:
                governance = build_governance_projection_for_phase_postimage(
                    root,
                    phase_ref=closed.phase_ref,
                    phase_payload=updated_phase.as_dict(),
                    require_current=not already_closed,
                )
                candidates.append((baseline_ref, render_governance_projection(governance)))
            overrides["process/" + closed.phase_ref] = (
                updated_phase.as_dict(),
                _render(updated_phase.as_dict()),
            )
        candidates.extend(build_state_projection_candidates(root, object_overrides=overrides))

        for ref, after in candidates:
            path = root / ref
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"transaction target is not a regular file: {ref}")
            before = path.read_bytes()
            if before != after:
                targets.append(
                    WorkCloseTargetV1(ref, _digest_bytes(before), _digest_bytes(after), after)
                )
    except (OSError, ValueError) as exc:
        blockers.append(str(exc))

    lineage: dict[str, str] = {}
    if not blockers:
        try:
            lineage = _lineage_for_targets(root, tuple(targets))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            blockers.append(str(exc))
    fields = {
        "schema_version": TRANSACTION_SCHEMA_VERSION,
        "operation": (
            "work.publication-close" if _publication_binding is not None else "work.close"
        ),
        "work_id": work_id,
        "expected_status": expected_status,
        "outcome": outcome,
        "result_ref": result_ref,
        "targets": [target.as_plan_dict() for target in targets],
        "lineage": lineage,
        "blockers": blockers,
        "publication_binding": (
            None if _publication_binding is None else _publication_binding.as_dict()
        ),
    }
    return WorkClosePlanV1(
        operation=str(fields["operation"]),
        decision="BLOCKED" if blockers else "READY",
        work_id=work_id,
        expected_status=expected_status,
        outcome=outcome,
        result_ref=result_ref,
        targets=tuple(targets),
        lineage=tuple(sorted(lineage.items())),
        blockers=tuple(blockers),
        plan_digest=_plan_digest(fields),
        publication_binding=_publication_binding,
    )


def _transaction_dir(root: Path, authorization_id: str) -> Path:
    return root / TRANSACTION_ROOT_REL / _safe_authorization_id(authorization_id)


def work_close_manifest_path(root: Path, authorization_id: str) -> Path:
    return manifest_path(root, authorization_id, transaction_root_rel=TRANSACTION_ROOT_REL)


def require_work_close_runtime_chain(
    root: Path,
    authorization_id: str | None = None,
    *,
    create: bool,
) -> None:
    parts = [Path(".meta-flow-runtime"), Path("work-close")]
    if authorization_id is not None:
        parts.extend([Path("transactions"), Path(safe_authorization_id(authorization_id))])
    ensure_runtime_chain(root, parts, create=create)


def acquire_work_close_writer_lock(root: Path, authorization_id: str) -> Path:
    return acquire_writer_lock(
        root,
        authorization_id,
        lock_rel=LOCK_REL,
        runtime_parts=(Path(".meta-flow-runtime"), Path("work-close")),
    )


def release_work_close_writer_lock(path: Path, authorization_id: str) -> None:
    release_writer_lock(path, authorization_id)


def _is_shared_projection_ref(ref: str) -> bool:
    parts = Path(ref).parts
    return (
        ref
        in {
            "PROJECT.yaml",
            GOVERNANCE_PROJECTION_REL.as_posix(),
            *STATE_PROJECTION_REFS,
        }
        or (
            len(parts) == 3 and parts[0] == "phases" and bool(parts[1]) and parts[2] == "PHASE.yaml"
        )
        or (len(parts) == 3 and parts[0] == "works" and bool(parts[1]) and parts[2] == "WORK.yaml")
    )


def _manifest_sort_key(manifest: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(manifest.get("updated_at") or ""),
        str(manifest.get("created_at") or ""),
        str(manifest.get("authorization_id") or ""),
    )


def _load_shared_successor_receipts(root: Path) -> list[dict[str, Any]]:
    successor_root = root / SUCCESSOR_ROOT_REL
    if successor_root.is_symlink() or (successor_root.exists() and not successor_root.is_dir()):
        raise ValueError("shared projection successor root is unsafe")
    if not successor_root.is_dir():
        return []
    receipts: list[dict[str, Any]] = []
    for path in sorted(successor_root.glob("*.json")):
        if path.is_symlink() or not path.is_file():
            raise ValueError("shared projection successor receipt path is unsafe")
        payload = json.loads(path.read_text(encoding="utf-8"))
        identity_fields = (
            set(payload) & _SUCCESSOR_IDENTITY_FIELDS if isinstance(payload, Mapping) else set()
        )
        if (
            not isinstance(payload, Mapping)
            or set(payload) - _SUCCESSOR_IDENTITY_FIELDS != _SUCCESSOR_FIELDS
            or len(identity_fields) != 1
        ):
            raise ValueError("shared projection successor receipt fields mismatch")
        successor_id = _safe_authorization_id(str(payload.get("successor_id") or ""))
        writer_id = _safe_authorization_id(
            str(payload.get("writer_id") or payload.get("work_id") or "")
        )
        operation = str(payload.get("operation") or "")
        if (
            payload.get("schema_version") != 1
            or payload.get("kind") != "shared-projection-successor-v1"
            or operation not in SHARED_SUCCESSOR_OPERATIONS
            or ("work_id" in payload and operation != "work.init")
            or path.stem != successor_id
        ):
            raise ValueError("shared projection successor receipt identity is invalid")
        raw_targets = payload.get("targets")
        if not isinstance(raw_targets, list) or not raw_targets:
            raise ValueError("shared projection successor targets must be non-empty")
        targets: list[dict[str, str]] = []
        for raw in raw_targets:
            if not isinstance(raw, Mapping) or set(raw) != _SUCCESSOR_TARGET_FIELDS:
                raise ValueError("shared projection successor target fields mismatch")
            ref = str(raw.get("ref") or "")
            anchor = _safe_authorization_id(str(raw.get("anchor_close_authorization_id") or ""))
            predecessor = str(raw.get("predecessor_successor_id") or "")
            if predecessor:
                predecessor = _safe_authorization_id(predecessor)
            before_digest = str(raw.get("before_digest") or "")
            after_digest = str(raw.get("after_digest") or "")
            if operation == "work.status-transition":
                operation_ref_allowed = (
                    len(Path(ref).parts) == 3
                    and Path(ref).parts[0] == "works"
                    and Path(ref).name == "WORK.yaml"
                )
            elif operation == "work.init":
                operation_ref_allowed = ref not in {
                    GOVERNANCE_PROJECTION_REL.as_posix(),
                    *STATE_PROJECTION_REFS,
                }
            elif operation == "project.phase-metadata":
                parts = Path(ref).parts
                operation_ref_allowed = ref in {
                    "PROJECT.yaml",
                    GOVERNANCE_PROJECTION_REL.as_posix(),
                } or (
                    len(parts) == 3
                    and parts[0] == "phases"
                    and bool(parts[1])
                    and parts[2] == "PHASE.yaml"
                )
            else:
                operation_ref_allowed = ref not in STATE_PROJECTION_REFS
            if (
                not _is_shared_projection_ref(ref)
                or not operation_ref_allowed
                or not _DIGEST_RE.fullmatch(before_digest)
                or not _DIGEST_RE.fullmatch(after_digest)
                or predecessor == successor_id
            ):
                raise ValueError("shared projection successor target is invalid")
            try:
                after_bytes = base64.b64decode(str(raw.get("after_bytes_b64") or ""), validate=True)
            except (TypeError, ValueError) as exc:
                raise ValueError("shared projection successor target bytes are invalid") from exc
            if _digest_bytes(after_bytes) != after_digest:
                raise ValueError("shared projection successor target bytes/digest mismatch")
            targets.append(
                {
                    "ref": ref,
                    "anchor_close_authorization_id": anchor,
                    "predecessor_successor_id": predecessor,
                    "before_digest": before_digest,
                    "after_digest": after_digest,
                    "after_bytes_b64": str(raw["after_bytes_b64"]),
                }
            )
        if len({target["ref"] for target in targets}) != len(targets):
            raise ValueError("shared projection successor target refs are duplicated")
        receipts.append(
            {
                "successor_id": successor_id,
                "writer_id": writer_id,
                "operation": operation,
                "created_at": str(payload.get("created_at") or ""),
                "targets": targets,
            }
        )
    return receipts


def _shared_successor_head(
    receipts: list[dict[str, Any]],
    *,
    ref: str,
    close_authorization_id: str,
    close_digest: str,
) -> tuple[str, str]:
    candidates = [
        (receipt, target)
        for receipt in receipts
        for target in receipt["targets"]
        if target["ref"] == ref
        and target["anchor_close_authorization_id"] == close_authorization_id
    ]
    if not candidates:
        return "", close_digest
    by_id = {str(receipt["successor_id"]): (receipt, target) for receipt, target in candidates}
    if len(by_id) != len(candidates):
        raise ValueError(f"shared projection successor identity is duplicated: {ref}")
    successors: dict[str, str] = {}
    for receipt, target in candidates:
        successor_id = str(receipt["successor_id"])
        predecessor = target["predecessor_successor_id"]
        if predecessor:
            previous = by_id.get(predecessor)
            if previous is None or previous[1]["after_digest"] != target["before_digest"]:
                raise ValueError(f"shared projection successor predecessor is invalid: {ref}")
        elif target["before_digest"] != close_digest:
            raise ValueError(f"shared projection successor anchor digest is invalid: {ref}")
        existing = successors.get(predecessor)
        if existing and existing != successor_id:
            raise ValueError(f"shared projection successor lineage fork: {ref}")
        successors[predecessor] = successor_id
    heads = [item for item in candidates if str(item[0]["successor_id"]) not in successors]
    if len(heads) != 1:
        raise ValueError(f"shared projection successor head is ambiguous: {ref}")
    receipt, target = heads[0]
    return str(receipt["successor_id"]), target["after_digest"]


def _load_terminal_manifests(root: Path) -> list[dict[str, Any]]:
    transaction_root = root / TRANSACTION_ROOT_REL
    manifests: list[dict[str, Any]] = []
    if not transaction_root.is_dir() or transaction_root.is_symlink():
        return manifests
    for path in sorted(transaction_root.glob("*/manifest.json")):
        if path.parent.is_symlink() or path.is_symlink():
            raise ValueError("transaction path is a symlink")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError("work close manifest must be an object")
        _validate_manifest(payload, expected_authorization_id=path.parent.name)
        state = str(payload.get("state") or "")
        if state not in TERMINAL_TRANSACTION_STATES:
            raise ValueError(
                f"unresolved work close transaction requires recovery: {path.parent.name}:{state}"
            )
        manifests.append(dict(payload))
    return manifests


def lineage_for_targets(
    root: Path,
    targets: tuple[WorkCloseTargetV1, ...],
    *,
    ignore_state_lock: bool = False,
) -> dict[str, str]:
    """冻结本次 close 对共享投影所接管的前一 close generation。"""

    _load_terminal_manifests(root)
    shared_targets = tuple(target for target in targets if _is_shared_projection_ref(target.ref))
    heads = committed_generation_heads(
        root / TRANSACTION_ROOT_REL,
        refs=tuple(target.ref for target in shared_targets),
        current_digests={target.ref: target.before_digest for target in shared_targets},
    )
    receipts = _load_shared_successor_receipts(root)
    state_successors: dict[str, str] | None = None
    lineage: dict[str, str] = {}
    for target in shared_targets:
        head = heads.get(target.ref)
        if head is None:
            continue
        _successor_id, successor_digest = _shared_successor_head(
            receipts,
            ref=target.ref,
            close_authorization_id=head["authorization_id"],
            close_digest=head["after_digest"],
        )
        authorized_successor = successor_digest in {
            target.before_digest,
            target.after_digest,
        }
        if not authorized_successor and target.ref in STATE_PROJECTION_REFS:
            if state_successors is None:
                from meta_flow.state.projection_transaction import (
                    state_projection_successor_head_digests,
                )

                state_successors = state_projection_successor_head_digests(
                    _release_root_from_process(root),
                    close_heads={
                        ref: candidate
                        for ref, candidate in heads.items()
                        if ref in STATE_PROJECTION_REFS
                    },
                    _ignore_lock=ignore_state_lock,
                )
            authorized_successor = state_successors.get(target.ref) in {
                target.before_digest,
                target.after_digest,
            }
        if not authorized_successor:
            raise ValueError(
                f"work close shared projection preimage has no authorized successor: {target.ref}"
            )
        lineage[target.ref] = head["authorization_id"]
    return lineage


def build_work_close_manifest(
    root: Path,
    plan: WorkClosePlanV1,
    authorization: WorkCloseAuthorizationProtocol,
) -> dict[str, Any]:
    planned_lineage = dict(plan.lineage)
    current_lineage = _lineage_for_targets(
        root,
        plan.targets,
        ignore_state_lock=True,
    )
    if current_lineage != planned_lineage:
        raise ValueError("work close lineage changed after planning")
    return {
        "schema_version": TRANSACTION_SCHEMA_VERSION,
        "kind": "work-close-transaction-v1",
        "operation": plan.operation,
        "publication_binding": (
            None if plan.publication_binding is None else plan.publication_binding.as_dict()
        ),
        "authorization_id": authorization.authorization_id,
        "work_id": plan.work_id,
        "plan_digest": plan.plan_digest,
        "state": "PREPARED",
        "created_at": _now(),
        "updated_at": _now(),
        "attempted_refs": [],
        "applied_refs": [],
        "lineage": planned_lineage,
        "targets": [
            {
                **target.as_plan_dict(),
                "before_bytes_b64": base64.b64encode(b"").decode("ascii"),
                "after_bytes_b64": base64.b64encode(target.after_bytes).decode("ascii"),
            }
            for target in plan.targets
        ],
    }


def attach_before_bytes(root: Path, manifest: dict[str, Any]) -> None:
    for target in manifest["targets"]:
        path = root / target["ref"]
        current = path.read_bytes()
        if _digest_bytes(current) != target["before_digest"]:
            raise ValueError(f"work close target preimage drift: {target['ref']}")
        target["before_bytes_b64"] = base64.b64encode(current).decode("ascii")


def status_handoff_transaction_id(
    *,
    authorization_id: str,
    parent_plan_digest: str,
    handoff_plan_digest: str,
    route_policy_digest: str,
    desired_digest: str,
) -> str:
    """parent 与 HANDOFF child 共用的稳定 transaction identity。"""

    _safe_authorization_id(authorization_id)
    if any(
        not _DIGEST_RE.fullmatch(value)
        for value in (
            parent_plan_digest,
            handoff_plan_digest,
            route_policy_digest,
            desired_digest,
        )
    ):
        raise ValueError("status handoff transaction identity fields are invalid")
    return sha256(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "HandoffTransitionTransactionIdentityV1",
                "authorization_id": authorization_id,
                "parent_plan_digest": parent_plan_digest,
                "handoff_plan_digest": handoff_plan_digest,
                "route_policy_digest": route_policy_digest,
                "desired_digest": desired_digest,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:32]


def validate_work_close_manifest(
    manifest: Mapping[str, Any],
    *,
    expected_authorization_id: str,
) -> None:
    fields = set(manifest)
    if not _MANIFEST_FIELDS <= fields or fields - _MANIFEST_FIELDS - _MANIFEST_OPTIONAL_FIELDS:
        raise ValueError("work close manifest fields mismatch")
    if (
        manifest.get("schema_version") != TRANSACTION_SCHEMA_VERSION
        or manifest.get("kind") != "work-close-transaction-v1"
    ):
        raise ValueError("work close manifest kind/version mismatch")
    operation = str(manifest.get("operation") or "work.close")
    if operation not in {
        "work.close",
        "work.publication-close",
        "work.status-transition",
    }:
        raise ValueError("work close manifest operation is invalid")
    publication_binding = manifest.get("publication_binding")
    if operation == "work.publication-close":
        if not isinstance(publication_binding, Mapping):
            raise ValueError("publication-close manifest binding is missing")
        WorkPublicationBindingV1.from_mapping(publication_binding)
    elif publication_binding is not None:
        raise ValueError("non-publication manifest must not contain publication binding")
    coordinator_digest = str(manifest.get("coordinator_plan_digest") or "")
    operation_admission_digest = str(manifest.get("operation_admission_digest") or "")
    mutation_plan_digest = str(manifest.get("mutation_plan_digest") or "")
    child_plan_digest = str(manifest.get("current_projection_plan_digest") or "")
    child_transaction_id = str(manifest.get("current_projection_transaction_id") or "")
    handoff_plan_digest = str(manifest.get("handoff_plan_digest") or "")
    handoff_transaction_id = str(manifest.get("handoff_transaction_id") or "")
    handoff_policy_digest = str(manifest.get("handoff_route_policy_digest") or "")
    handoff_desired_digest = str(manifest.get("handoff_desired_digest") or "")
    authorization_id = _safe_authorization_id(str(manifest.get("authorization_id") or ""))
    parent_plan_digest = str(manifest.get("plan_digest") or "")
    if operation == "work.status-transition":
        expected_current_transaction_id = sha256(
            json.dumps(
                {
                    "schema_version": 2,
                    "kind": "CurrentProjectionTransactionIdentityV2",
                    "authorization_id": authorization_id,
                    "parent_plan_digest": parent_plan_digest,
                    "current_projection_plan_digest": child_plan_digest,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:32]
        expected_handoff_transaction_id = _status_handoff_transaction_id(
            authorization_id=authorization_id,
            parent_plan_digest=parent_plan_digest,
            handoff_plan_digest=handoff_plan_digest,
            route_policy_digest=handoff_policy_digest,
            desired_digest=handoff_desired_digest,
        )
        if (
            not _DIGEST_RE.fullmatch(coordinator_digest)
            or not _DIGEST_RE.fullmatch(operation_admission_digest)
            or not _DIGEST_RE.fullmatch(mutation_plan_digest)
            or not _DIGEST_RE.fullmatch(parent_plan_digest)
            or not _DIGEST_RE.fullmatch(child_plan_digest)
            or child_transaction_id != expected_current_transaction_id
            or not _DIGEST_RE.fullmatch(handoff_plan_digest)
            or handoff_transaction_id != expected_handoff_transaction_id
            or not _DIGEST_RE.fullmatch(handoff_policy_digest)
            or not _DIGEST_RE.fullmatch(handoff_desired_digest)
        ):
            raise ValueError("status transition coordinator binding is invalid")
    elif any(
        (
            coordinator_digest,
            operation_admission_digest,
            mutation_plan_digest,
            child_plan_digest,
            child_transaction_id,
            handoff_plan_digest,
            handoff_transaction_id,
            handoff_policy_digest,
            handoff_desired_digest,
        )
    ):
        raise ValueError("non-status manifest must not contain coordinator binding")
    if authorization_id != expected_authorization_id:
        raise ValueError("work close manifest authorization identity mismatch")
    work_id = _safe_authorization_id(str(manifest.get("work_id") or ""))
    if not _DIGEST_RE.fullmatch(parent_plan_digest):
        raise ValueError("work close manifest plan digest is invalid")
    if manifest.get("state") not in TRANSACTION_STATES:
        raise ValueError("work close manifest state is invalid")
    raw_targets = manifest.get("targets")
    attempted_refs = manifest.get("attempted_refs")
    applied_refs = manifest.get("applied_refs")
    lineage = manifest.get("lineage", {})
    if (
        not isinstance(raw_targets, list)
        or not isinstance(attempted_refs, list)
        or not isinstance(applied_refs, list)
    ):
        raise ValueError("work close manifest target accounting is invalid")
    if not isinstance(lineage, Mapping) or any(
        not isinstance(ref, str) or not isinstance(predecessor, str)
        for ref, predecessor in lineage.items()
    ):
        raise ValueError("work close manifest lineage is invalid")
    target_refs: list[str] = []
    for target in raw_targets:
        if not isinstance(target, Mapping) or set(target) != _TARGET_FIELDS:
            raise ValueError("work close manifest target fields mismatch")
        ref = str(target.get("ref") or "")
        parts = Path(ref).parts
        phase_ref = (
            len(parts) == 3 and parts[0] == "phases" and bool(parts[1]) and parts[2] == "PHASE.yaml"
        )
        if (
            not is_safe_ref(ref)
            or ref
            not in {
                "PROJECT.yaml",
                f"works/{work_id}/WORK.yaml",
                GOVERNANCE_PROJECTION_REL.as_posix(),
                *STATE_PROJECTION_REFS,
            }
            and not phase_ref
        ):
            raise ValueError(f"work close manifest target is outside fixed projector: {ref}")
        before_digest = str(target.get("before_digest") or "")
        after_digest = str(target.get("after_digest") or "")
        if not _DIGEST_RE.fullmatch(before_digest) or not _DIGEST_RE.fullmatch(after_digest):
            raise ValueError("work close manifest target digest is invalid")
        try:
            before = base64.b64decode(str(target["before_bytes_b64"]), validate=True)
            after = base64.b64decode(str(target["after_bytes_b64"]), validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError("work close manifest target bytes are invalid") from exc
        if _digest_bytes(before) != before_digest or _digest_bytes(after) != after_digest:
            raise ValueError("work close manifest target bytes/digest mismatch")
        target_refs.append(ref)
    if len(target_refs) != len(set(target_refs)) or len(target_refs) > 7:
        raise ValueError("work close manifest target set is invalid")
    if any(
        ref not in target_refs
        or not _is_shared_projection_ref(ref)
        or not predecessor
        or predecessor == authorization_id
        or _safe_authorization_id(predecessor) != predecessor
        for ref, predecessor in lineage.items()
    ):
        raise ValueError("work close manifest lineage target is invalid")
    for field, refs in (
        ("attempted_refs", attempted_refs),
        ("applied_refs", applied_refs),
    ):
        if (
            any(not isinstance(ref, str) for ref in refs)
            or len(refs) != len(set(refs))
            or any(ref not in target_refs for ref in refs)
            or refs != target_refs[: len(refs)]
        ):
            raise ValueError(f"work close manifest {field} are invalid")
    if applied_refs != attempted_refs[: len(applied_refs)]:
        raise ValueError("work close manifest applied_refs exceed attempted_refs")


def rollback_work_close_transaction(root: Path, manifest: dict[str, Any]) -> tuple[bool, list[str]]:
    failed: list[str] = []
    for target in reversed(manifest["targets"]):
        ref = target["ref"]
        path = root / ref
        try:
            current = path.read_bytes()
            current_digest = _digest_bytes(current)
            if current_digest not in {target["after_digest"], target["before_digest"]}:
                raise ValueError("target bytes no longer match transaction generations")
            before = base64.b64decode(target["before_bytes_b64"], validate=True)
            if current_digest == target["after_digest"] and current != before:
                _replace_bytes(path, before)
        except (OSError, ValueError) as exc:
            failed.append(f"{ref}: {exc}")
    return not failed, failed


def lineage_generation_errors(
    root: Path,
    manifests: list[Mapping[str, Any]],
    *,
    state_lock_handle: Any | None = None,
) -> list[str]:
    """只把共享投影的 lineage head 与当前 generation 比较。

    历史 manifest 的 bytes/digest 完整性已经由 ``_validate_manifest`` 证明。
    PROJECT、Phase 与 governance baseline 会被后续 Work close 合法接管，因而
    不能再要求每个历史 after-image 永久等于当前文件。同一 Work 的失败关闭也
    可能先 RECOVERED、再由新授权成功关闭；所有 target 都只校验当前 lineage
    head，manifest 自身仍逐个做 bytes/digest 完整性校验。
    """

    errors: list[str] = []
    phase_metadata_manifest = root / PHASE_METADATA_MANIFEST_REL
    if phase_metadata_manifest.is_symlink() or (
        phase_metadata_manifest.exists() and not phase_metadata_manifest.is_file()
    ):
        errors.append("Phase metadata transaction manifest is unsafe")
    elif phase_metadata_manifest.is_file():
        try:
            phase_metadata_payload = json.loads(phase_metadata_manifest.read_text(encoding="utf-8"))
            if (
                not isinstance(phase_metadata_payload, Mapping)
                or phase_metadata_payload.get("kind") != "PhaseMetadataTransactionV1"
                or phase_metadata_payload.get("state") not in {"COMMITTED", "RECOVERED"}
            ):
                errors.append("unresolved Phase metadata transaction requires inspect/recover")
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"Phase metadata transaction manifest is invalid: {exc}")
    try:
        successor_receipts = _load_shared_successor_receipts(root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        successor_receipts = []
        errors.append(str(exc))
    state_projection_current_refs: set[str] | None = None
    by_id = {str(manifest["authorization_id"]): manifest for manifest in manifests}
    target_refs = {str(target["ref"]) for manifest in manifests for target in manifest["targets"]}
    current_by_ref: dict[str, str] = {}
    for ref in sorted(target_refs):
        try:
            current_by_ref[ref] = _digest_bytes((root / ref).read_bytes())
        except OSError as exc:
            errors.append(f"work close target unreadable: {ref}:{exc}")
    try:
        committed_heads = committed_generation_heads(
            root / TRANSACTION_ROOT_REL,
            refs=tuple(sorted(target_refs)),
            current_digests=current_by_ref,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
        return errors

    for ref in sorted(target_refs):
        committed = [
            manifest
            for manifest in manifests
            if manifest.get("state") == "COMMITTED"
            and any(target.get("ref") == ref for target in manifest["targets"])
        ]
        if committed:
            head = committed_heads.get(ref)
            if head is None:
                errors.append(f"work close lineage head is ambiguous: {ref}")
                continue
            expected_manifest = by_id[str(head["authorization_id"])]
            expected_generation = "after_digest"
        else:
            recovered = [
                manifest
                for manifest in manifests
                if manifest.get("state") == "RECOVERED"
                and any(target.get("ref") == ref for target in manifest["targets"])
            ]
            if not recovered:
                continue
            expected_manifest = max(recovered, key=_manifest_sort_key)
            expected_generation = "before_digest"
        target = next(target for target in expected_manifest["targets"] if target["ref"] == ref)
        expected_digest = target[expected_generation]
        if expected_generation == "after_digest":
            try:
                _successor_id, expected_digest = _shared_successor_head(
                    successor_receipts,
                    ref=ref,
                    close_authorization_id=str(expected_manifest["authorization_id"]),
                    close_digest=expected_digest,
                )
            except ValueError as exc:
                errors.append(str(exc))
                continue
        current_digest = current_by_ref.get(ref)
        if current_digest is None:
            continue
        if current_digest != expected_digest:
            if ref in STATE_PROJECTION_REFS:
                if state_projection_current_refs is None:
                    try:
                        from meta_flow.state.projection_transaction import (
                            inspect_state_projection_transaction,
                        )

                        inspection = inspect_state_projection_transaction(
                            _release_root_from_process(root),
                            _lock_handle=state_lock_handle,
                        )
                        ref_findings = {
                            finding.rsplit(":", 1)[1]
                            for finding in inspection.get("findings", [])
                            if isinstance(finding, str)
                            and finding.startswith(
                                (
                                    "TERMINAL_GENERATION_DRIFT:",
                                    "STATE_PROJECTION_LINEAGE_UNBOUND:",
                                )
                            )
                        }
                        global_findings = [
                            finding
                            for finding in inspection.get("findings", [])
                            if not isinstance(finding, str)
                            or not finding.startswith(
                                (
                                    "TERMINAL_GENERATION_DRIFT:",
                                    "STATE_PROJECTION_LINEAGE_UNBOUND:",
                                )
                            )
                        ]
                        state_projection_current_refs = (
                            set()
                            if global_findings
                            else {
                                candidate
                                for candidate in STATE_PROJECTION_REFS
                                if "process/" + candidate not in ref_findings
                            }
                        )
                    except (OSError, ValueError):
                        state_projection_current_refs = set()
                if ref in state_projection_current_refs:
                    continue
            errors.append(
                f"work close terminal generation mismatch: {ref}:{expected_manifest['state']}"
            )

    return errors


def assert_work_close_shared_projection_lineage(
    process_root: Path,
    *,
    _state_lock_handle: Any | None = None,
) -> None:
    """供其他 native writer 在修改共享 Project/Phase 前验证 close lineage。"""

    root = process_root.resolve()
    if _state_lock_handle is not None:
        from meta_flow.state.projection_transaction import (
            state_projection_lock_path,
            transaction_lock_identity,
            validate_transaction_lock,
        )

        expected_path = state_projection_lock_path(_release_root_from_process(root))
        validate_transaction_lock(_state_lock_handle, expected_path=expected_path)
        if transaction_lock_identity(expected_path) != _state_lock_handle.transaction_id:
            raise ValueError("state projection writer lock capability identity drifted")
    errors = _lineage_generation_errors(
        root,
        _load_terminal_manifests(root),
        state_lock_handle=_state_lock_handle,
    )
    if errors:
        raise ValueError("; ".join(errors))


def plan_shared_projection_successor_preflight(
    process_root: Path,
    *,
    operation: str,
    writer_id: str,
    before_digests: Mapping[str, str],
    allowed_refs: tuple[str, ...],
) -> tuple[tuple[str, str, str, str], ...]:
    """在领域写入前冻结共享投影 successor 的唯一 predecessor。

    返回项依次为 ``ref``、close anchor、前一 successor（可空）和 preimage
    digest。legacy manifest 的等价 generation 归一化、显式 fork 检查与
    close-inspect 共用 ``committed_generation_heads``，禁止 writer 自行猜 tail。
    """

    root = process_root.resolve()
    _safe_authorization_id(writer_id)
    if operation not in SHARED_SUCCESSOR_OPERATIONS:
        raise ValueError("shared projection successor operation is unsupported")
    manifests = _load_terminal_manifests(root)
    if not manifests:
        return ()
    receipts = _load_shared_successor_receipts(root)
    existing = [
        receipt
        for receipt in receipts
        if receipt["operation"] == operation and receipt["writer_id"] == writer_id
    ]
    if existing:
        raise ValueError("shared projection successor writer identity was already consumed")
    allowed = set(allowed_refs)
    relevant_refs = tuple(
        ref for ref in sorted(before_digests) if _is_shared_projection_ref(ref) and ref in allowed
    )
    close_heads = committed_generation_heads(
        root / TRANSACTION_ROOT_REL,
        refs=relevant_refs,
        current_digests=before_digests,
    )
    anchors: list[tuple[str, str, str, str]] = []
    for ref in relevant_refs:
        close_head = close_heads.get(ref)
        if close_head is None:
            continue
        predecessor_id, predecessor_digest = _shared_successor_head(
            receipts,
            ref=ref,
            close_authorization_id=close_head["authorization_id"],
            close_digest=close_head["after_digest"],
        )
        before_digest = before_digests[ref]
        if predecessor_digest != before_digest:
            raise ValueError(f"shared projection successor preimage drift: {ref}")
        anchors.append(
            (
                ref,
                close_head["authorization_id"],
                predecessor_id,
                before_digest,
            )
        )
    return tuple(anchors)


def record_shared_projection_successor(
    process_root: Path,
    *,
    operation: str,
    writer_id: str,
    before_digests: Mapping[str, str],
    allowed_refs: tuple[str, ...],
    expected_preflight: tuple[tuple[str, str, str, str], ...] | None = None,
) -> str:
    """为已成功的 native writer 登记共享投影合法后继 generation。"""

    root = process_root.resolve()
    _safe_authorization_id(writer_id)
    if operation not in SHARED_SUCCESSOR_OPERATIONS:
        raise ValueError("shared projection successor operation is unsupported")
    manifests = _load_terminal_manifests(root)
    if not manifests:
        return ""
    receipts = _load_shared_successor_receipts(root)
    relevant_refs = tuple(
        ref
        for ref in sorted(before_digests)
        if _is_shared_projection_ref(ref) and ref in set(allowed_refs)
    )
    close_heads = committed_generation_heads(
        root / TRANSACTION_ROOT_REL,
        refs=relevant_refs,
        current_digests=before_digests,
    )
    existing = [
        receipt
        for receipt in receipts
        if receipt["operation"] == operation and receipt["writer_id"] == writer_id
    ]
    if len(existing) > 1:
        raise ValueError("shared projection successor writer identity is duplicated")
    if existing:
        receipt = existing[0]
        expected_refs = {
            ref
            for ref in relevant_refs
            if close_heads.get(ref) is not None
            and _digest_bytes((root / ref).read_bytes()) != before_digests[ref]
        }
        receipt_refs = {target["ref"] for target in receipt["targets"]}
        if receipt_refs != expected_refs or any(
            before_digests.get(target["ref"]) != target["before_digest"]
            or _digest_bytes((root / target["ref"]).read_bytes()) != target["after_digest"]
            for target in receipt["targets"]
        ):
            raise ValueError("shared projection successor retry target mismatch")
        return str(receipt["successor_id"])
    preflight = plan_shared_projection_successor_preflight(
        root,
        operation=operation,
        writer_id=writer_id,
        before_digests=before_digests,
        allowed_refs=allowed_refs,
    )
    if expected_preflight is not None and preflight != expected_preflight:
        raise ValueError("shared projection successor preflight drifted")
    anchor_by_ref = {
        ref: (close_authorization_id, predecessor_successor_id, before_digest)
        for ref, close_authorization_id, predecessor_successor_id, before_digest in preflight
    }
    target_records: list[dict[str, str]] = []
    for ref in relevant_refs:
        before_digest = before_digests[ref]
        path = root / ref
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"shared projection successor target is not regular: {ref}")
        after_bytes = path.read_bytes()
        after_digest = _digest_bytes(after_bytes)
        if after_digest == before_digest:
            continue
        anchor = anchor_by_ref.get(ref)
        if anchor is None:
            continue
        close_authorization_id, predecessor_id, predecessor_digest = anchor
        if predecessor_digest != before_digest:
            raise ValueError(f"shared projection successor preimage drift: {ref}")
        target_records.append(
            {
                "ref": ref,
                "anchor_close_authorization_id": close_authorization_id,
                "predecessor_successor_id": predecessor_id,
                "before_digest": before_digest,
                "after_digest": after_digest,
                "after_bytes_b64": base64.b64encode(after_bytes).decode("ascii"),
            }
        )
    if not target_records:
        return ""
    successor_id = (
        operation.replace(".", "-")
        + "-"
        + sha256(
            json.dumps(
                {
                    "operation": operation,
                    "writer_id": writer_id,
                    "targets": target_records,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:32]
    )
    successor_root = root / SUCCESSOR_ROOT_REL
    _require_runtime_chain(root, create=True)
    if successor_root.is_symlink() or (successor_root.exists() and not successor_root.is_dir()):
        raise ValueError("shared projection successor root is unsafe")
    successor_root.mkdir(exist_ok=True)
    path = successor_root / f"{successor_id}.json"
    payload = {
        "schema_version": 1,
        "kind": "shared-projection-successor-v1",
        "successor_id": successor_id,
        "operation": operation,
        "writer_id": writer_id,
        "created_at": _now(),
        "targets": target_records,
    }
    if path.exists() or path.is_symlink():
        raise ValueError("shared projection successor receipt already exists")
    _write_json_atomic(path, payload)
    return successor_id


def _shared_projection_repair_admission(
    root: Path,
    *,
    classification: str,
    targets: tuple[SharedProjectionRepairTargetV1, ...],
    blockers: tuple[str, ...],
) -> OperationAdmissionV1:
    """冻结 repair 的仓库、route、provider 与 inspect snapshot 身份。"""

    route_path = root / ".meta-flow-process.yaml"
    if route_path.is_symlink() or not route_path.is_file():
        raise ValueError("shared projection repair route binding is unavailable")
    return OperationAdmissionV1(
        snapshot_digest=canonical_digest(
            {
                "schema_version": 1,
                "kind": "SharedProjectionRepairSnapshotV1",
                "classification": classification,
                "targets": [target.as_dict() for target in targets],
                "blockers": list(blockers),
            }
        ),
        release_oid=repository_head_oid(_release_root_from_process(root)),
        process_oid=repository_head_oid(root),
        provider_identity_digest=provider_source_identity_digest(
            Path(__file__),
            Path(__file__).parents[1] / "execution_control/exact_file_transaction.py",
            Path(__file__).parents[1] / "execution_control/operation_admission.py",
        ),
        route_profile_digest=_digest_bytes(route_path.read_bytes()),
        work_scope_digest=canonical_digest(
            {
                "schema_version": 1,
                "kind": "WorkScopeNotApplicableV1",
                "operation": "shared-projection.repair",
            }
        ),
        authorization_identity_digest=canonical_digest(
            {
                "schema_version": 1,
                "kind": "SharedProjectionRepairAuthorizationV1",
                "source": "typed-user-confirmation",
                "single_use": True,
            }
        ),
    )


def plan_shared_projection_repair(process_root: Path) -> SharedProjectionRepairPlanV1:
    """只读检查 PROJECT/Phase/governance lineage，并生成唯一可修复计划。"""

    root = process_root.resolve()
    blockers: list[str] = []
    classification = "COMMITTED_CURRENT"
    manifests: list[dict[str, Any]] = []
    transaction_root = root / TRANSACTION_ROOT_REL
    try:
        if transaction_root.is_symlink() or (
            transaction_root.exists() and not transaction_root.is_dir()
        ):
            raise ValueError("work close transaction root is unsafe")
        if transaction_root.is_dir():
            for path in sorted(transaction_root.glob("*/manifest.json")):
                if path.parent.is_symlink() or path.is_symlink() or not path.is_file():
                    raise ValueError("work close transaction path is unsafe")
                payload = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("work close transaction payload is invalid")
                _validate_manifest(payload, expected_authorization_id=path.parent.name)
                manifests.append(payload)
        unresolved = [
            str(payload["authorization_id"])
            for payload in manifests
            if payload["state"] not in TERMINAL_TRANSACTION_STATES
        ]
        if unresolved:
            classification = "PARTIAL"
            blockers.extend(f"unresolved transaction: {item}" for item in unresolved)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        classification = "CORRUPTED"
        blockers.append(str(exc))

    targets: list[SharedProjectionRepairTargetV1] = []
    if not blockers:
        repairable_refs = tuple(
            sorted(
                {
                    str(target["ref"])
                    for payload in manifests
                    if payload["state"] == "COMMITTED"
                    for target in payload["targets"]
                    if str(target["ref"]) in {"PROJECT.yaml", GOVERNANCE_PROJECTION_REL.as_posix()}
                    or (
                        len(Path(str(target["ref"])).parts) == 3
                        and Path(str(target["ref"])).parts[0] == "phases"
                        and Path(str(target["ref"])).parts[2] == "PHASE.yaml"
                    )
                }
            )
        )
        try:
            current_digests: dict[str, str] = {}
            for ref in repairable_refs:
                path = root / ref
                if path.is_symlink() or not path.is_file():
                    raise ValueError(f"shared projection repair target is unsafe: {ref}")
                current_digests[ref] = _digest_bytes(path.read_bytes())
            heads = committed_generation_heads(
                transaction_root,
                refs=repairable_refs,
                current_digests=current_digests,
            )
            receipts = _load_shared_successor_receipts(root)
            for ref in repairable_refs:
                head = heads.get(ref)
                if head is None:
                    continue
                predecessor_id, predecessor_digest = _shared_successor_head(
                    receipts,
                    ref=ref,
                    close_authorization_id=head["authorization_id"],
                    close_digest=head["after_digest"],
                )
                current_digest = current_digests[ref]
                if current_digest == predecessor_digest:
                    continue
                targets.append(
                    SharedProjectionRepairTargetV1(
                        ref,
                        head["authorization_id"],
                        predecessor_id,
                        predecessor_digest,
                        current_digest,
                    )
                )
            if targets:
                classification = "COMMITTED_STALE_REPAIRABLE"
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            classification = "CORRUPTED"
            blockers.append(str(exc))
            targets = []
    normalized_targets = tuple(targets)
    normalized_blockers = tuple(blockers)
    try:
        admission = _shared_projection_repair_admission(
            root,
            classification=classification,
            targets=normalized_targets,
            blockers=normalized_blockers,
        )
    except (OSError, ValueError) as exc:
        classification = "CORRUPTED"
        blockers.append(str(exc))
        normalized_targets = ()
        normalized_blockers = tuple(blockers)
        unavailable = canonical_digest(
            {
                "schema_version": 1,
                "kind": "SharedProjectionRepairAdmissionUnavailableV1",
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
    fields = {
        "schema_version": 1,
        "kind": "SharedProjectionRepairPlanV1",
        "classification": classification,
        "targets": [target.as_dict() for target in normalized_targets],
        "blockers": list(normalized_blockers),
        "admission": admission.as_dict(),
        "admission_digest": admission.admission_digest,
    }
    return SharedProjectionRepairPlanV1(
        classification,
        normalized_targets,
        normalized_blockers,
        admission,
        canonical_digest(fields),
    )


def inspect_shared_projection_repair(
    process_root: Path,
    *,
    expected_plan_digest: str = "",
) -> dict[str, Any]:
    """inspect-derived five-state 入口；本操作严格零写。"""

    plan = plan_shared_projection_repair(process_root)
    classification = plan.classification
    if (
        expected_plan_digest
        and expected_plan_digest != plan.plan_digest
        and classification not in {"PARTIAL", "CORRUPTED"}
    ):
        classification = "SUPERSEDED"
    return {
        "schema_version": 1,
        "kind": "SharedProjectionRepairInspectionV1",
        "decision": "PASS" if classification == "COMMITTED_CURRENT" else "BLOCKED",
        "classification": classification,
        "repair_plan": plan.as_dict(),
        "mutation_count": 0,
    }


def apply_shared_projection_repair(
    process_root: Path,
    plan: SharedProjectionRepairPlanV1,
    authorization: SharedProjectionRepairAuthorizationV1,
) -> SharedProjectionRepairReceiptV1:
    """仅追加 successor receipt；formal PROJECT/Phase/governance bytes 零修改。"""

    root = process_root.resolve()
    authorization.validate_for(plan)
    writer_id = "shared-repair-" + sha256(authorization.authorization_id.encode()).hexdigest()[:32]
    _safe_authorization_id(writer_id)
    shared_lock = acquire_shared_projection_writer_lock(root, writer_id)
    try:
        if any(
            receipt["operation"] == "shared-projection.repair" and receipt["writer_id"] == writer_id
            for receipt in _load_shared_successor_receipts(root)
        ):
            raise ValueError("shared projection repair authorization was already consumed")
        admission = inspect_shared_projection_repair(
            root,
            expected_plan_digest=plan.plan_digest,
        )
        if admission["classification"] == "SUPERSEDED":
            return SharedProjectionRepairReceiptV1(
                "BLOCKED",
                authorization.authorization_id,
                plan.plan_digest,
                "",
                tuple(target.ref for target in plan.targets),
                0,
                "SUPERSEDED",
            )
        fresh = plan_shared_projection_repair(root)
        if fresh.as_dict() != plan.as_dict():
            return SharedProjectionRepairReceiptV1(
                "BLOCKED",
                authorization.authorization_id,
                plan.plan_digest,
                "",
                tuple(target.ref for target in plan.targets),
                0,
                "SUPERSEDED",
            )
        before_digests = {target.ref: target.predecessor_digest for target in plan.targets}
        preflight = tuple(
            (
                target.ref,
                target.anchor_close_authorization_id,
                target.predecessor_successor_id,
                target.predecessor_digest,
            )
            for target in plan.targets
        )
        successor_id = record_shared_projection_successor(
            root,
            operation="shared-projection.repair",
            writer_id=writer_id,
            before_digests=before_digests,
            allowed_refs=tuple(target.ref for target in plan.targets),
            expected_preflight=preflight,
        )
        # successor receipt 已原子落盘后，post-inspect 故障不能再冒充零写异常。
        # 返回 typed PARTIAL，后续只读 inspect 可从 receipt 恢复真实 CURRENT。
        try:
            post = plan_shared_projection_repair(root)
        except Exception:  # noqa: BLE001 - 写后任何检查故障都必须保留 mutation accounting
            return SharedProjectionRepairReceiptV1(
                "PARTIAL",
                authorization.authorization_id,
                plan.plan_digest,
                successor_id,
                tuple(target.ref for target in plan.targets),
                1 if successor_id else 0,
                "CORRUPTED",
            )
        if post.classification != "COMMITTED_CURRENT":
            return SharedProjectionRepairReceiptV1(
                "PARTIAL",
                authorization.authorization_id,
                plan.plan_digest,
                successor_id,
                tuple(target.ref for target in plan.targets),
                1 if successor_id else 0,
                post.classification,
            )
        return SharedProjectionRepairReceiptV1(
            "PASS",
            authorization.authorization_id,
            plan.plan_digest,
            successor_id,
            tuple(target.ref for target in plan.targets),
            1 if successor_id else 0,
            post.classification,
        )
    finally:
        release_shared_projection_writer_lock(shared_lock, writer_id)


def discard_shared_projection_successor(
    process_root: Path,
    *,
    successor_id: str,
    operation: str,
    writer_id: str,
) -> bool:
    """回滚 writer 时删除它刚创建、且身份完全匹配的 successor receipt。"""

    root = process_root.resolve()
    safe_successor_id = _safe_authorization_id(successor_id)
    safe_writer_id = _safe_authorization_id(writer_id)
    if operation not in SHARED_SUCCESSOR_OPERATIONS:
        raise ValueError("shared projection successor operation is unsupported")
    successor_root = root / SUCCESSOR_ROOT_REL
    if successor_root.is_symlink() or (successor_root.exists() and not successor_root.is_dir()):
        raise ValueError("shared projection successor root is unsafe")
    path = successor_root / f"{safe_successor_id}.json"
    if not path.exists() and not path.is_symlink():
        return False
    if path.is_symlink() or not path.is_file():
        raise ValueError("shared projection successor receipt path is unsafe")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(payload, Mapping)
        or payload.get("successor_id") != safe_successor_id
        or payload.get("operation") != operation
        or payload.get("writer_id") != safe_writer_id
    ):
        raise ValueError("shared projection successor receipt ownership mismatch")
    path.unlink()
    return True


def shared_projection_successor_for_writer(
    process_root: Path,
    *,
    operation: str,
    writer_id: str,
) -> str:
    """返回 writer 唯一 successor；不存在时返回空，重复时 fail-closed。"""

    receipts = [
        receipt
        for receipt in _load_shared_successor_receipts(process_root.resolve())
        if receipt["operation"] == operation and receipt["writer_id"] == writer_id
    ]
    if len(receipts) > 1:
        raise ValueError("shared projection successor writer identity is duplicated")
    return str(receipts[0]["successor_id"]) if receipts else ""


def record_work_init_shared_projection_successor(
    process_root: Path,
    *,
    work_id: str,
    before_digests: Mapping[str, str],
    expected_preflight: tuple[tuple[str, str, str, str], ...] | None = None,
) -> str:
    """为已成功的 Work init 登记 Project/Phase 合法后继 generation。"""

    return record_shared_projection_successor(
        process_root,
        operation="work.init",
        writer_id=work_id,
        before_digests=before_digests,
        allowed_refs=(
            "PROJECT.yaml",
            *(ref for ref in before_digests if Path(ref).name == "PHASE.yaml"),
        ),
        expected_preflight=expected_preflight,
    )


def apply_work_close(
    process_root: Path,
    plan: WorkClosePlanV1,
    authorization: WorkCloseAuthorizationProtocol,
) -> WorkCloseReceiptV1:
    root = process_root.resolve()
    if not plan.ready:
        raise ValueError("blocked Work close plan cannot be applied")
    authorization.validate_for(plan)
    manifest_path = _manifest_path(root, authorization.authorization_id)
    if manifest_path.exists() or manifest_path.is_symlink():
        raise ValueError("work close authorization_id was already consumed")
    _require_runtime_chain(root, create=True)
    shared_writer_id = (
        "work-close-" + sha256(authorization.authorization_id.encode()).hexdigest()[:32]
    )
    shared_lock = acquire_shared_projection_writer_lock(
        root,
        shared_writer_id,
    )
    lock: Path | None = None
    state_lock = None
    try:
        lock = _acquire_lock(root, authorization.authorization_id)
        if any(target.ref in STATE_PROJECTION_REFS for target in plan.targets):
            from meta_flow.state.projection_transaction import (
                acquire_transaction_lock,
                state_projection_lock_path,
            )

            state_lock = acquire_transaction_lock(
                state_projection_lock_path(_release_root_from_process(root)),
                sha256(f"work-close:{authorization.authorization_id}".encode()).hexdigest()[:32],
            )
        _require_runtime_chain(root, authorization.authorization_id, create=True)
        manifest = _manifest(root, plan, authorization)
    except Exception:
        try:
            if state_lock is not None:
                from meta_flow.state.projection_transaction import (
                    release_transaction_lock,
                )

                release_transaction_lock(state_lock)
        finally:
            try:
                if lock is not None:
                    _release_lock(lock, authorization.authorization_id)
            finally:
                release_shared_projection_writer_lock(
                    shared_lock,
                    shared_writer_id,
                )
        raise
    attempted: list[str] = []
    applied: list[str] = []
    try:
        _attach_before_bytes(root, manifest)
        _validate_manifest(
            manifest,
            expected_authorization_id=authorization.authorization_id,
        )
        _write_json_atomic(manifest_path, manifest)
        manifest["state"] = "APPLYING"
        _write_json_atomic(manifest_path, manifest)
        for target in manifest["targets"]:
            path = root / target["ref"]
            current = path.read_bytes()
            if _digest_bytes(current) != target["before_digest"]:
                raise ValueError(f"work close target preimage drift: {target['ref']}")
            attempted.append(target["ref"])
            manifest["attempted_refs"] = list(attempted)
            manifest["updated_at"] = _now()
            _write_json_atomic(manifest_path, manifest)
            _replace_bytes(path, base64.b64decode(target["after_bytes_b64"]))
            applied.append(target["ref"])
            manifest["applied_refs"] = list(applied)
            manifest["updated_at"] = _now()
            _write_json_atomic(manifest_path, manifest)
        manifest["state"] = "COMMITTED"
        manifest["updated_at"] = _now()
        _write_json_atomic(manifest_path, manifest)
        return WorkCloseReceiptV1(
            "PASS",
            authorization.authorization_id,
            plan.work_id,
            plan.plan_digest,
            len(applied),
            tuple(applied),
            False,
        )
    except Exception as exc:
        manifest["attempted_refs"] = list(attempted)
        manifest["applied_refs"] = list(applied)
        recovered, failures = _rollback(root, manifest)
        manifest["state"] = "RECOVERED" if recovered else "PARTIAL"
        manifest["updated_at"] = _now()
        manifest["failure"] = str(exc)
        manifest["recovery_failures"] = failures
        _write_json_atomic(manifest_path, manifest)
        return WorkCloseReceiptV1(
            "RECOVERED" if recovered else "PARTIAL",
            authorization.authorization_id,
            plan.work_id,
            plan.plan_digest,
            len(applied),
            tuple(applied),
            not recovered,
            (
                "WORK_CLOSE_APPLY_FAILED",
                *(("WORK_CLOSE_RECOVERY_FAILED",) if failures else ()),
            ),
        )
    finally:
        try:
            if state_lock is not None:
                from meta_flow.state.projection_transaction import (
                    release_transaction_lock,
                )

                release_transaction_lock(state_lock)
        finally:
            try:
                if lock is not None:
                    _release_lock(lock, authorization.authorization_id)
            finally:
                release_shared_projection_writer_lock(
                    shared_lock,
                    shared_writer_id,
                )


def inspect_work_close_transactions(process_root: Path) -> dict[str, Any]:
    root = process_root.resolve()
    transaction_root = root / TRANSACTION_ROOT_REL
    transactions: list[dict[str, Any]] = []
    terminal_manifests: list[dict[str, Any]] = []
    errors: list[str] = []
    if transaction_root.is_symlink():
        errors.append("work close transaction root is a symlink")
        return {
            "schema_version": TRANSACTION_SCHEMA_VERSION,
            "decision": "BLOCKED",
            "transactions": transactions,
            "unresolved_count": len(errors),
            "errors": errors,
        }
    if transaction_root.is_dir():
        for path in sorted(transaction_root.glob("*/manifest.json")):
            try:
                if path.parent.is_symlink() or path.is_symlink():
                    raise ValueError("transaction path is a symlink")
                payload = json.loads(path.read_text(encoding="utf-8"))
                _validate_manifest(
                    payload,
                    expected_authorization_id=path.parent.name,
                )
                state = str(payload.get("state") or "")
                if state == "PARTIAL":
                    errors.append(
                        f"partial work close transaction requires recovery: {path.parent.name}"
                    )
                elif state not in TERMINAL_TRANSACTION_STATES:
                    errors.append(f"unresolved work close transaction: {path.parent.name}:{state}")
                else:
                    terminal_manifests.append(payload)
                transactions.append(
                    {
                        "authorization_id": path.parent.name,
                        "work_id": str(payload.get("work_id") or ""),
                        "state": state,
                        "manifest_ref": path.relative_to(root).as_posix(),
                    }
                )
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"invalid work close manifest {path}: {exc}")
        errors.extend(_lineage_generation_errors(root, terminal_manifests))
    lock = root / LOCK_REL
    if lock.exists() or lock.is_symlink():
        errors.append("work close writer lock remains present")
    return {
        "schema_version": TRANSACTION_SCHEMA_VERSION,
        "decision": "BLOCKED" if errors else "PASS",
        "transactions": transactions,
        "unresolved_count": len(errors),
        "errors": errors,
    }


def recover_work_close_transaction(
    process_root: Path,
    authorization_id: str,
) -> WorkCloseReceiptV1:
    root = process_root.resolve()
    _require_runtime_chain(root, authorization_id, create=False)
    path = _manifest_path(root, authorization_id)
    if not path.is_file() or path.is_symlink():
        raise ValueError("work close transaction manifest is missing")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    _validate_manifest(manifest, expected_authorization_id=authorization_id)
    if manifest.get("operation") == "work.status-transition":
        raise ValueError(
            "work.status-transition recovery requires the dedicated status-transition owner"
        )
    state = str(manifest.get("state") or "")
    if state in TERMINAL_TRANSACTION_STATES:
        generation_errors = _lineage_generation_errors(
            root,
            _load_terminal_manifests(root),
        )
        if generation_errors:
            raise ValueError("; ".join(generation_errors))
        return WorkCloseReceiptV1(
            "NO_CHANGE",
            authorization_id,
            str(manifest.get("work_id") or ""),
            str(manifest.get("plan_digest") or ""),
            0,
            tuple(manifest.get("applied_refs") or ()),
            state == "PARTIAL",
        )
    shared_writer_id = "work-recover-" + sha256(authorization_id.encode()).hexdigest()[:32]
    shared_lock = acquire_shared_projection_writer_lock(root, shared_writer_id)
    lock: Path | None = None
    state_lock = None
    try:
        lock = _acquire_lock(root, authorization_id)
        if any(
            str(target.get("ref") or "") in STATE_PROJECTION_REFS for target in manifest["targets"]
        ):
            from meta_flow.state.projection_transaction import (
                acquire_transaction_lock,
                state_projection_lock_path,
            )

            state_lock = acquire_transaction_lock(
                state_projection_lock_path(_release_root_from_process(root)),
                sha256(f"work-recover:{authorization_id}".encode()).hexdigest()[:32],
            )
        recovered, failures = _rollback(root, manifest)
        manifest["state"] = "RECOVERED" if recovered else "PARTIAL"
        manifest["updated_at"] = _now()
        manifest["recovery_failures"] = failures
        _write_json_atomic(path, manifest)
        return WorkCloseReceiptV1(
            "RECOVERED" if recovered else "PARTIAL",
            authorization_id,
            str(manifest.get("work_id") or ""),
            str(manifest.get("plan_digest") or ""),
            len(manifest.get("applied_refs") or ()),
            tuple(manifest.get("applied_refs") or ()),
            not recovered,
            ("WORK_CLOSE_RECOVERY_FAILED",) if failures else (),
        )
    finally:
        try:
            if state_lock is not None:
                from meta_flow.state.projection_transaction import (
                    release_transaction_lock,
                )

                release_transaction_lock(state_lock)
        finally:
            try:
                if lock is not None:
                    _release_lock(lock, authorization_id)
            finally:
                release_shared_projection_writer_lock(
                    shared_lock,
                    shared_writer_id,
                )


__all__ = [
    "AUTHORIZATION_KIND",
    "SharedProjectionWriterLock",
    "SharedProjectionRepairAuthorizationV1",
    "SharedProjectionRepairPlanV1",
    "SharedProjectionRepairReceiptV1",
    "SharedProjectionRepairTargetV1",
    "WorkCloseAuthorizationV1",
    "WorkCloseAuthorizationProtocol",
    "WorkClosePlanV1",
    "WorkCloseReceiptV1",
    "WorkPublicationBindingV1",
    "acquire_shared_projection_writer_lock",
    "apply_work_close",
    "apply_shared_projection_repair",
    "assert_work_close_shared_projection_lineage",
    "build_state_projection_candidates",
    "discard_shared_projection_successor",
    "inspect_work_close_transactions",
    "inspect_shared_projection_repair",
    "plan_work_close",
    "plan_shared_projection_repair",
    "plan_shared_projection_successor_preflight",
    "refresh_state_projection_if_initialized",
    "record_work_init_shared_projection_successor",
    "record_shared_projection_successor",
    "recover_work_close_transaction",
    "release_shared_projection_writer_lock",
    "shared_projection_successor_for_writer",
    "validate_shared_projection_writer_lock",
]


# P0 领域函数公开化兼容层：旧私有名保留一个版本周期后删除。
_validate_manifest = validate_work_close_manifest
_manifest = build_work_close_manifest
_attach_before_bytes = attach_before_bytes
_lineage_for_targets = lineage_for_targets
_lineage_generation_errors = lineage_generation_errors
_release_root_from_process = release_root_from_process
_status_handoff_transaction_id = status_handoff_transaction_id
_rollback = rollback_work_close_transaction
_manifest_path = work_close_manifest_path
_require_runtime_chain = require_work_close_runtime_chain
_acquire_lock = acquire_work_close_writer_lock
_release_lock = release_work_close_writer_lock
