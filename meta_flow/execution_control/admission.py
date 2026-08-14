"""Execution Control 的纯准入计划、预算评估与 project-scoped 协调锁。"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from meta_flow.execution_control.contract import (
    AdmissionFactsV1,
    AdmissionPlanV1,
    ContainerBudgetV1,
    ExecutionUnitV1,
    canonical_digest,
)
from meta_flow.execution_control.repair_admission import RepairAdmissionBindingV1

POLICY_REVISION = 1
CANONICAL_EVALUATOR_IDENTITY = (
    "meta_flow.execution_control.admission.evaluate_execution_budget:v2"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,127}$")
_LOCK_FIELDS = frozenset(
    {
        "schema_version",
        "owner_token_digest",
        "owner_process_identity",
        "acquired_at",
        "policy_revision",
        "plan_digest",
        "facts_digest",
        "candidate_digest",
        "lease_state",
    }
)


def _require_non_empty(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value or any(char in value for char in "\r\n"):
        raise ValueError(f"{field} must be one non-empty single-line string")
    return value


def _require_sha256(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field} must be one lowercase SHA-256 digest")
    return value


def _normalize_inventory(
    units: Iterable[ExecutionUnitV1],
) -> tuple[ExecutionUnitV1, ...]:
    normalized = tuple(units)
    if not all(isinstance(unit, ExecutionUnitV1) for unit in normalized):
        raise ValueError("execution inventory must contain only ExecutionUnitV1 values")
    unit_ids = [unit.unit_id for unit in normalized]
    if len(unit_ids) != len(set(unit_ids)):
        raise ValueError("execution inventory must not repeat unit_id")
    return tuple(
        sorted(
            normalized,
            key=lambda unit: (
                unit.root_concept,
                unit.slice_id,
                unit.container_role,
                unit.revision,
                unit.unit_id,
            ),
        )
    )


def execution_inventory_digest(units: Iterable[ExecutionUnitV1]) -> str:
    """计算与目录顺序无关的 active execution inventory 摘要。"""

    return canonical_digest([unit.as_dict() for unit in _normalize_inventory(units)])


@dataclass(frozen=True, slots=True)
class BudgetEvaluationV1:
    decision: str
    conflicts: tuple[str, ...]
    role_counts: tuple[tuple[str, int], ...]
    concurrent_writer_count: int
    child_work_count: int
    domain_mutation_count: int = 0
    coordination_mutation_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "decision": self.decision,
            "conflicts": list(self.conflicts),
            "role_counts": dict(self.role_counts),
            "concurrent_writer_count": self.concurrent_writer_count,
            "child_work_count": self.child_work_count,
            "domain_mutation_count": self.domain_mutation_count,
            "coordination_mutation_count": self.coordination_mutation_count,
        }


def evaluate_execution_budget(
    units: Iterable[ExecutionUnitV1],
    policy: ContainerBudgetV1,
    *,
    concurrent_writer_count: int,
    child_work_count: int = 0,
    authorized_repair_slices: tuple[tuple[str, str], ...] = (),
) -> BudgetEvaluationV1:
    """唯一预算 evaluator；产品准入和 kernel 自审都必须调用本函数。"""

    inventory = _normalize_inventory(units)
    if not isinstance(policy, ContainerBudgetV1):
        raise ValueError("policy must be ContainerBudgetV1")
    for field, value in (
        ("concurrent_writer_count", concurrent_writer_count),
        ("child_work_count", child_work_count),
    ):
        if type(value) is not int or value < 0:
            raise ValueError(f"{field} must be a non-negative integer")
    if (
        not isinstance(authorized_repair_slices, tuple)
        or not all(
            isinstance(item, tuple)
            and len(item) == 2
            and all(isinstance(value, str) and value for value in item)
            for item in authorized_repair_slices
        )
        or len(set(authorized_repair_slices)) != len(authorized_repair_slices)
    ):
        raise ValueError("authorized_repair_slices must be unique root/slice pairs")

    conflicts: set[str] = set()
    grouped: dict[tuple[str, str], Counter[str]] = {}
    for unit in inventory:
        key = (unit.root_concept, unit.slice_id)
        grouped.setdefault(key, Counter())[unit.container_role] += 1

    for key, counts in grouped.items():
        if counts["primary"] > 1:
            conflicts.add("DUPLICATE_ACTIVE_SLICE_OWNER")
        if (
            counts["primary"] > policy.primary_max
            or counts["auxiliary"] > policy.auxiliary_max
            or counts["repair"]
            > policy.repair_max + int(key in authorized_repair_slices)
        ):
            conflicts.add("CONTAINER_BUDGET_EXCEEDED")
    if child_work_count > 0:
        conflicts.add("CONTAINER_BUDGET_EXCEEDED")
    if concurrent_writer_count > policy.concurrent_write_max:
        conflicts.add("CONCURRENT_WRITE_BUDGET_EXCEEDED")

    role_counts = Counter(unit.container_role for unit in inventory)
    ordered_conflicts = tuple(sorted(conflicts))
    return BudgetEvaluationV1(
        decision="BLOCKED" if ordered_conflicts else "READY",
        conflicts=ordered_conflicts,
        role_counts=tuple(
            (role, role_counts[role]) for role in ("primary", "auxiliary", "repair")
        ),
        concurrent_writer_count=concurrent_writer_count,
        child_work_count=child_work_count,
    )


_CANONICAL_BUDGET_EVALUATOR = evaluate_execution_budget
CANONICAL_EVALUATOR_DIGEST = canonical_digest(
    {
        "identity": CANONICAL_EVALUATOR_IDENTITY,
        "policy_revision": POLICY_REVISION,
    }
)


def _supersession_conflicts(
    candidate: ExecutionUnitV1,
    terminal_predecessors: tuple[ExecutionUnitV1, ...],
) -> tuple[str, ...]:
    if candidate.revision == 1:
        return ()
    matching = tuple(
        unit
        for unit in terminal_predecessors
        if unit.unit_id == candidate.supersedes_unit_id
        and unit.root_concept == candidate.root_concept
        and unit.slice_id == candidate.slice_id
        and unit.revision < candidate.revision
    )
    return () if len(matching) == 1 else ("SUPERSESSION_PREDECESSOR_NOT_TERMINAL",)


def _candidate_context_digest(
    candidate: ExecutionUnitV1,
    terminal_predecessors: tuple[ExecutionUnitV1, ...],
    policy: ContainerBudgetV1,
    repair_binding: RepairAdmissionBindingV1 | None,
    existing_repair_bindings: tuple[RepairAdmissionBindingV1, ...],
) -> str:
    return canonical_digest(
        {
            "candidate": candidate.as_dict(),
            "terminal_predecessors": [
                unit.as_dict() for unit in _normalize_inventory(terminal_predecessors)
            ],
            "policy_revision": POLICY_REVISION,
            "policy": policy.as_dict(),
            "evaluator_identity": CANONICAL_EVALUATOR_IDENTITY,
            "evaluator_digest": CANONICAL_EVALUATOR_DIGEST,
            "repair_binding": (
                repair_binding.as_dict() if repair_binding is not None else None
            ),
            "existing_repair_bindings": [
                binding.as_dict() for binding in existing_repair_bindings
            ],
        }
    )


def _repair_binding_conflicts(
    candidate: ExecutionUnitV1,
    inventory: tuple[ExecutionUnitV1, ...],
    repair_binding: RepairAdmissionBindingV1 | None,
    existing_repair_bindings: tuple[RepairAdmissionBindingV1, ...],
) -> tuple[str, ...]:
    conflicts: set[str] = set()
    binding_by_candidate = {
        binding.candidate_work_id: binding for binding in existing_repair_bindings
    }
    if len(binding_by_candidate) != len(existing_repair_bindings):
        conflicts.add("REPAIR_INVENTORY_AUTHORIZATION_DUPLICATE")
    inventory_by_id = {unit.unit_id: unit for unit in inventory}
    for unit in inventory:
        binding = binding_by_candidate.get(unit.unit_id)
        if unit.container_role == "repair":
            if binding is None:
                conflicts.add("REPAIR_INVENTORY_AUTHORIZATION_REQUIRED")
            elif (
                binding.candidate_unit_digest != canonical_digest(unit)
                or binding.root_concept != unit.root_concept
                or binding.slice_id != unit.slice_id
            ):
                conflicts.add("REPAIR_INVENTORY_AUTHORIZATION_DRIFT")
        elif binding is not None:
            conflicts.add("REPAIR_INVENTORY_AUTHORIZATION_ROLE_MISMATCH")
    if set(binding_by_candidate) - set(inventory_by_id):
        conflicts.add("REPAIR_INVENTORY_AUTHORIZATION_ORPHANED")
    if candidate.container_role != "repair":
        if repair_binding is not None:
            conflicts.add("REPAIR_AUTHORIZATION_ROLE_MISMATCH")
        return tuple(sorted(conflicts))
    if repair_binding is None:
        return ("REPAIR_AUTHORIZATION_REQUIRED",)
    if (
        repair_binding.candidate_work_id != candidate.unit_id
        or repair_binding.candidate_unit_digest != canonical_digest(candidate)
    ):
        conflicts.add("REPAIR_AUTHORIZATION_CANDIDATE_MISMATCH")
    if (
        repair_binding.root_concept != candidate.root_concept
        or repair_binding.slice_id != candidate.slice_id
    ):
        conflicts.add("REPAIR_AUTHORIZATION_SLICE_MISMATCH")
    predecessor = tuple(
        unit for unit in inventory if unit.unit_id == repair_binding.predecessor_work_id
    )
    if len(predecessor) != 1:
        conflicts.add("REPAIR_PREDECESSOR_NOT_ACTIVE_OWNER")
    elif canonical_digest(predecessor[0]) != repair_binding.predecessor_unit_digest:
        conflicts.add("REPAIR_PREDECESSOR_EXECUTION_UNIT_DRIFT")
    return tuple(sorted(conflicts))


def plan_admission(
    candidate: ExecutionUnitV1,
    active_inventory: Iterable[ExecutionUnitV1],
    policy: ContainerBudgetV1,
    facts: AdmissionFactsV1,
    *,
    terminal_predecessors: Iterable[ExecutionUnitV1] = (),
    active_concurrent_writer_count: int = 0,
    repair_binding: RepairAdmissionBindingV1 | None = None,
    existing_repair_bindings: Iterable[RepairAdmissionBindingV1] = (),
) -> AdmissionPlanV1:
    """构造零写入准入计划；不发现目录，也不调用任何 domain writer。"""

    if not isinstance(candidate, ExecutionUnitV1):
        raise ValueError("candidate must be ExecutionUnitV1")
    if not isinstance(facts, AdmissionFactsV1):
        raise ValueError("facts must be AdmissionFactsV1")
    inventory = _normalize_inventory(active_inventory)
    predecessors = _normalize_inventory(terminal_predecessors)
    existing_bindings = tuple(
        sorted(existing_repair_bindings, key=lambda item: item.candidate_work_id)
    )
    if not all(
        isinstance(binding, RepairAdmissionBindingV1)
        for binding in existing_bindings
    ):
        raise ValueError(
            "existing_repair_bindings must contain RepairAdmissionBindingV1 values"
        )
    conflicts = set(_supersession_conflicts(candidate, predecessors))
    repair_conflicts = _repair_binding_conflicts(
        candidate, inventory, repair_binding, existing_bindings
    )
    conflicts.update(repair_conflicts)
    if execution_inventory_digest(inventory) != facts.inventory_digest:
        conflicts.add("ADMISSION_PREIMAGE_DRIFT")

    evaluation = evaluate_execution_budget(
        (*inventory, candidate),
        policy,
        concurrent_writer_count=active_concurrent_writer_count + 1,
        authorized_repair_slices=tuple(
            sorted(
                {
                    *(
                        (binding.root_concept, binding.slice_id)
                        for binding in existing_bindings
                    ),
                    *(
                        ((candidate.root_concept, candidate.slice_id),)
                        if candidate.container_role == "repair"
                        and repair_binding is not None
                        and not repair_conflicts
                        else ()
                    ),
                }
            )
        ),
    )
    conflicts.update(evaluation.conflicts)
    ordered_conflicts = tuple(sorted(conflicts))
    return AdmissionPlanV1(
        decision="BLOCKED" if ordered_conflicts else "READY",
        facts_digest=canonical_digest(facts),
        scope_digest=facts.scope_digest,
        candidate_digest=_candidate_context_digest(
            candidate,
            predecessors,
            policy,
            repair_binding,
            existing_bindings,
        ),
        conflicts=ordered_conflicts,
        planned_domain_mutation_count=0,
        coordination_required=not ordered_conflicts,
    )


@dataclass(frozen=True, slots=True)
class SelfBudgetReceiptV1:
    decision: str
    conflicts: tuple[str, ...]
    role_counts: tuple[tuple[str, int], ...]
    concurrent_writer_count: int
    child_work_count: int
    policy_digest: str
    scope_digest: str
    inventory_digest: str
    evaluator_digest: str
    source_fingerprint: str
    profile_fingerprint: str
    command_identity: str
    result_digest: str

    def __post_init__(self) -> None:
        normalized_conflicts = tuple(
            sorted(
                {
                    conflict
                    for conflict in self.conflicts
                    if isinstance(conflict, str) and _SAFE_CODE_RE.fullmatch(conflict)
                }
            )
        )
        if normalized_conflicts != self.conflicts:
            raise ValueError("self-budget conflicts must be unique sorted safe codes")
        roles = dict(self.role_counts)
        if len(roles) != len(self.role_counts) or set(roles) != {
            "primary",
            "auxiliary",
            "repair",
        }:
            raise ValueError("self-budget role_counts must contain exact canonical roles")
        for field, value in (
            *roles.items(),
            ("concurrent_writer_count", self.concurrent_writer_count),
            ("child_work_count", self.child_work_count),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"{field} must be a non-negative integer")
        expected_decision = "BLOCKED" if self.conflicts else "SELF_BUDGET_PASS"
        if self.decision != expected_decision:
            raise ValueError("self-budget decision conflicts with reason codes")
        for field in (
            "policy_digest",
            "scope_digest",
            "inventory_digest",
            "evaluator_digest",
            "source_fingerprint",
            "profile_fingerprint",
            "command_identity",
            "result_digest",
        ):
            _require_sha256(getattr(self, field), field=field)
        if self.policy_digest != canonical_digest(ContainerBudgetV1.policy_v1()):
            raise ValueError("self-budget policy digest is not canonical policy-v1")
        if self.evaluator_digest != CANONICAL_EVALUATOR_DIGEST:
            raise ValueError("self-budget evaluator digest drifted")
        if self.result_digest != _self_budget_result_digest(
            decision=self.decision,
            conflicts=self.conflicts,
            role_counts=self.role_counts,
            concurrent_writer_count=self.concurrent_writer_count,
            child_work_count=self.child_work_count,
        ):
            raise ValueError("self-budget result digest mismatch")

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "decision": self.decision,
            "conflicts": list(self.conflicts),
            "role_counts": dict(self.role_counts),
            "concurrent_writer_count": self.concurrent_writer_count,
            "child_work_count": self.child_work_count,
            "policy_revision": POLICY_REVISION,
            "policy_digest": self.policy_digest,
            "scope_digest": self.scope_digest,
            "inventory_digest": self.inventory_digest,
            "evaluator_identity": CANONICAL_EVALUATOR_IDENTITY,
            "evaluator_digest": self.evaluator_digest,
            "source_fingerprint": self.source_fingerprint,
            "profile_fingerprint": self.profile_fingerprint,
            "command_identity": self.command_identity,
            "result_digest": self.result_digest,
            "domain_mutation_count": 0,
            "coordination_mutation_count": 0,
        }

    @property
    def receipt_digest(self) -> str:
        return canonical_digest(self._payload())

    def as_dict(self) -> dict[str, Any]:
        return {**self._payload(), "receipt_digest": self.receipt_digest}

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> SelfBudgetReceiptV1:
        expected = {
            "schema_version",
            "decision",
            "conflicts",
            "role_counts",
            "concurrent_writer_count",
            "child_work_count",
            "policy_revision",
            "policy_digest",
            "scope_digest",
            "inventory_digest",
            "evaluator_identity",
            "evaluator_digest",
            "source_fingerprint",
            "profile_fingerprint",
            "command_identity",
            "result_digest",
            "domain_mutation_count",
            "coordination_mutation_count",
            "receipt_digest",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ValueError("self-budget receipt fields mismatch")
        if payload.get("schema_version") != 1 or payload.get("policy_revision") != POLICY_REVISION:
            raise ValueError("self-budget receipt revision mismatch")
        if payload.get("evaluator_identity") != CANONICAL_EVALUATOR_IDENTITY:
            raise ValueError("self-budget evaluator identity drifted")
        if payload.get("domain_mutation_count") != 0 or payload.get(
            "coordination_mutation_count"
        ) != 0:
            raise ValueError("self-budget receipt must be zero mutation")
        conflicts = payload.get("conflicts")
        role_counts = payload.get("role_counts")
        if not isinstance(conflicts, list) or not all(
            isinstance(item, str) for item in conflicts
        ):
            raise ValueError("self-budget conflicts must be a list of strings")
        if not isinstance(role_counts, Mapping):
            raise ValueError("self-budget role_counts must be a mapping")
        canonical_roles = {"primary", "auxiliary", "repair"}
        if not all(isinstance(role, str) for role in role_counts) or set(role_counts) != canonical_roles:
            raise ValueError("self-budget role_counts must contain exact canonical roles")
        value = cls(
            decision=str(payload["decision"]),
            conflicts=tuple(conflicts),
            role_counts=tuple(
                (role, role_counts[role])
                for role in ("primary", "auxiliary", "repair")
            ),
            concurrent_writer_count=payload["concurrent_writer_count"],
            child_work_count=payload["child_work_count"],
            policy_digest=str(payload["policy_digest"]),
            scope_digest=str(payload["scope_digest"]),
            inventory_digest=str(payload["inventory_digest"]),
            evaluator_digest=str(payload["evaluator_digest"]),
            source_fingerprint=str(payload["source_fingerprint"]),
            profile_fingerprint=str(payload["profile_fingerprint"]),
            command_identity=str(payload["command_identity"]),
            result_digest=str(payload["result_digest"]),
        )
        if payload.get("receipt_digest") != value.receipt_digest:
            raise ValueError("self-budget receipt digest mismatch")
        return value


def load_self_budget_receipt(path: Path) -> SelfBudgetReceiptV1:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("self-budget receipt must be a JSON object")
    return SelfBudgetReceiptV1.from_mapping(payload)


def _self_budget_result_digest(
    *,
    decision: str,
    conflicts: tuple[str, ...],
    role_counts: tuple[tuple[str, int], ...],
    concurrent_writer_count: int,
    child_work_count: int,
) -> str:
    return canonical_digest(
        {
            "decision": decision,
            "conflicts": list(conflicts),
            "role_counts": dict(role_counts),
            "concurrent_writer_count": concurrent_writer_count,
            "child_work_count": child_work_count,
            "domain_mutation_count": 0,
            "coordination_mutation_count": 0,
        }
    )


def audit_execution_budget(
    inventory: Iterable[ExecutionUnitV1],
    facts: AdmissionFactsV1,
    *,
    concurrent_writer_count: int,
    child_work_count: int,
    source_fingerprint: str,
    profile_fingerprint: str,
    command_identity: str,
) -> SelfBudgetReceiptV1:
    """用 canonical evaluator 只读审计 kernel 自身预算。"""

    if evaluate_execution_budget is not _CANONICAL_BUDGET_EVALUATOR:
        raise ValueError("canonical budget evaluator identity drift")
    source = _require_sha256(source_fingerprint, field="source_fingerprint")
    profile = _require_sha256(profile_fingerprint, field="profile_fingerprint")
    command = _require_sha256(command_identity, field="command_identity")
    normalized = _normalize_inventory(inventory)
    actual_inventory_digest = execution_inventory_digest(normalized)
    evaluation = _CANONICAL_BUDGET_EVALUATOR(
        normalized,
        ContainerBudgetV1.policy_v1(),
        concurrent_writer_count=concurrent_writer_count,
        child_work_count=child_work_count,
    )
    conflicts = set(evaluation.conflicts)
    if facts.inventory_digest != actual_inventory_digest:
        conflicts.add("ADMISSION_PREIMAGE_DRIFT")
    ordered_conflicts = tuple(sorted(conflicts))
    decision = "BLOCKED" if ordered_conflicts else "SELF_BUDGET_PASS"
    result_digest = _self_budget_result_digest(
        decision=decision,
        conflicts=ordered_conflicts,
        role_counts=evaluation.role_counts,
        concurrent_writer_count=concurrent_writer_count,
        child_work_count=child_work_count,
    )
    return SelfBudgetReceiptV1(
        decision=decision,
        conflicts=ordered_conflicts,
        role_counts=evaluation.role_counts,
        concurrent_writer_count=concurrent_writer_count,
        child_work_count=child_work_count,
        policy_digest=canonical_digest(ContainerBudgetV1.policy_v1()),
        scope_digest=facts.scope_digest,
        inventory_digest=actual_inventory_digest,
        evaluator_digest=CANONICAL_EVALUATOR_DIGEST,
        source_fingerprint=source,
        profile_fingerprint=profile,
        command_identity=command,
        result_digest=result_digest,
    )


@dataclass(frozen=True, slots=True)
class AdmissionLockMetadataV1:
    schema_version: int
    owner_token_digest: str
    owner_process_identity: str
    acquired_at: str
    policy_revision: int
    plan_digest: str
    facts_digest: str
    candidate_digest: str
    lease_state: str

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("admission lock schema_version must be 1")
        _require_sha256(self.owner_token_digest, field="owner_token_digest")
        _require_non_empty(self.owner_process_identity, field="owner_process_identity")
        _require_non_empty(self.acquired_at, field="acquired_at")
        if self.policy_revision != POLICY_REVISION:
            raise ValueError("admission lock policy_revision mismatch")
        for field in ("plan_digest", "facts_digest", "candidate_digest"):
            _require_sha256(getattr(self, field), field=field)
        if self.lease_state != "held":
            raise ValueError("admission lock lease_state must be held")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> AdmissionLockMetadataV1:
        if not isinstance(payload, Mapping) or frozenset(payload) != _LOCK_FIELDS:
            raise ValueError("admission lock metadata fields mismatch")
        return cls(**{field: payload[field] for field in _LOCK_FIELDS})

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "owner_token_digest": self.owner_token_digest,
            "owner_process_identity": self.owner_process_identity,
            "acquired_at": self.acquired_at,
            "policy_revision": self.policy_revision,
            "plan_digest": self.plan_digest,
            "facts_digest": self.facts_digest,
            "candidate_digest": self.candidate_digest,
            "lease_state": self.lease_state,
        }


@dataclass(frozen=True, slots=True)
class AdmissionLockHandleV1:
    lock_path: Path
    metadata: AdmissionLockMetadataV1
    preimage_digest: str
    owner_token: str


@dataclass(frozen=True, slots=True)
class AdmissionLockResultV1:
    decision: str
    conflicts: tuple[str, ...]
    coordination_mutation_count: int
    durable_lock_count: int
    handle: AdmissionLockHandleV1 | None = None

    @property
    def partial(self) -> bool:
        return self.decision == "PARTIAL_MUTATION"


@dataclass(frozen=True, slots=True)
class AdmissionLockInspectionV1:
    state: str
    lock_path: Path
    preimage_digest: str
    metadata: AdmissionLockMetadataV1 | None
    mutation_count: int = 0


def admission_lock_path(process_git_common_dir: Path) -> Path:
    return (
        process_git_common_dir.resolve(strict=False)
        / "meta-flow"
        / "execution-control"
        / "admission.lock"
    )


def _lock_bytes(metadata: AdmissionLockMetadataV1) -> bytes:
    return (
        json.dumps(metadata.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def acquire_admission_lock(
    process_git_common_dir: Path,
    plan: AdmissionPlanV1,
    *,
    owner_token: str,
    owner_process_identity: str,
) -> AdmissionLockResultV1:
    """create-only 获取 project lock；blocked plan 不产生任何协调写。"""

    if plan.blocked:
        return AdmissionLockResultV1("BLOCKED", plan.conflicts, 0, 0)
    token = _require_non_empty(owner_token, field="owner_token")
    identity = _require_non_empty(owner_process_identity, field="owner_process_identity")
    path = admission_lock_path(process_git_common_dir)
    metadata = AdmissionLockMetadataV1(
        schema_version=1,
        owner_token_digest=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        owner_process_identity=identity,
        acquired_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        policy_revision=POLICY_REVISION,
        plan_digest=canonical_digest(plan),
        facts_digest=plan.facts_digest,
        candidate_digest=plan.candidate_digest,
        lease_state="held",
    )
    data = _lock_bytes(metadata)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return AdmissionLockResultV1(
            "BLOCKED", ("ADMISSION_LOCK_OR_CAS_FAILED",), 0, 1
        )
    except OSError:
        return AdmissionLockResultV1(
            "BLOCKED", ("ADMISSION_LOCK_OR_CAS_FAILED",), 0, int(path.exists())
        )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_directory(path.parent)
    except Exception:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            return AdmissionLockResultV1(
                "PARTIAL_MUTATION", ("ADMISSION_LOCK_CLEANUP_FAILED",), 1, 1
            )
        return AdmissionLockResultV1(
            "BLOCKED", ("ADMISSION_LOCK_OR_CAS_FAILED",), 2, 0
        )
    handle = AdmissionLockHandleV1(path, metadata, hashlib.sha256(data).hexdigest(), token)
    return AdmissionLockResultV1("PASS", (), 1, 1, handle)


def inspect_admission_lock(process_git_common_dir: Path) -> AdmissionLockInspectionV1:
    """只读检查 lock；malformed/stale 均不自动删除。"""

    path = admission_lock_path(process_git_common_dir)
    try:
        first = path.stat()
        data = path.read_bytes()
        second = path.stat()
    except FileNotFoundError:
        return AdmissionLockInspectionV1("ABSENT", path, "", None)
    except OSError:
        return AdmissionLockInspectionV1("MALFORMED", path, "", None)
    if (first.st_dev, first.st_ino, first.st_size) != (
        second.st_dev,
        second.st_ino,
        second.st_size,
    ):
        return AdmissionLockInspectionV1("MALFORMED", path, "", None)
    digest = hashlib.sha256(data).hexdigest()
    try:
        payload = json.loads(data)
        metadata = AdmissionLockMetadataV1.from_mapping(payload)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
        return AdmissionLockInspectionV1("MALFORMED", path, digest, None)
    return AdmissionLockInspectionV1("HELD", path, digest, metadata)


def _inspection_matches_handle(
    inspection: AdmissionLockInspectionV1,
    handle: AdmissionLockHandleV1,
) -> bool:
    return (
        inspection.state == "HELD"
        and inspection.lock_path == handle.lock_path
        and inspection.preimage_digest == handle.preimage_digest
        and inspection.metadata == handle.metadata
        and inspection.metadata is not None
        and inspection.metadata.owner_token_digest
        == hashlib.sha256(handle.owner_token.encode("utf-8")).hexdigest()
    )


def release_admission_lock(
    process_git_common_dir: Path,
    handle: AdmissionLockHandleV1,
) -> AdmissionLockResultV1:
    """仅匹配 exact owner/preimage 的持有者可释放锁。"""

    inspection = inspect_admission_lock(process_git_common_dir)
    if not _inspection_matches_handle(inspection, handle):
        return AdmissionLockResultV1(
            "BLOCKED",
            ("ADMISSION_LOCK_OR_CAS_FAILED",),
            0,
            0 if inspection.state == "ABSENT" else 1,
        )
    try:
        handle.lock_path.unlink()
        _fsync_directory(handle.lock_path.parent)
    except OSError:
        durable = int(handle.lock_path.exists())
        return AdmissionLockResultV1(
            "PARTIAL_MUTATION",
            ("ADMISSION_LOCK_CLEANUP_FAILED",),
            int(not durable),
            durable,
        )
    return AdmissionLockResultV1("PASS", (), 1, 0)


@dataclass(frozen=True, slots=True)
class AdmissionReservationV1:
    decision: str
    conflicts: tuple[str, ...]
    planned_plan_digest: str
    fresh_plan_digest: str
    domain_mutation_count: int = 0
    coordination_mutation_count: int = 0


def validate_admission_preimage(
    planned: AdmissionPlanV1,
    lock_handle: AdmissionLockHandleV1,
    process_git_common_dir: Path,
    fresh_candidate: ExecutionUnitV1,
    fresh_active_inventory: Iterable[ExecutionUnitV1],
    policy: ContainerBudgetV1,
    fresh_facts: AdmissionFactsV1,
    *,
    terminal_predecessors: Iterable[ExecutionUnitV1] = (),
    active_concurrent_writer_count: int = 0,
    repair_binding: RepairAdmissionBindingV1 | None = None,
    existing_repair_bindings: Iterable[RepairAdmissionBindingV1] = (),
) -> AdmissionReservationV1:
    """在持锁后重建 plan，并用 exact digest 完成 fresh CAS。"""

    planned_digest = canonical_digest(planned)
    inspection = inspect_admission_lock(process_git_common_dir)
    if (
        not _inspection_matches_handle(inspection, lock_handle)
        or lock_handle.metadata.plan_digest != planned_digest
    ):
        return AdmissionReservationV1(
            "BLOCKED",
            ("ADMISSION_LOCK_OR_CAS_FAILED",),
            planned_digest,
            "",
        )
    fresh = plan_admission(
        fresh_candidate,
        fresh_active_inventory,
        policy,
        fresh_facts,
        terminal_predecessors=terminal_predecessors,
        active_concurrent_writer_count=active_concurrent_writer_count,
        repair_binding=repair_binding,
        existing_repair_bindings=existing_repair_bindings,
    )
    fresh_digest = canonical_digest(fresh)
    if fresh_digest != planned_digest or fresh.blocked:
        return AdmissionReservationV1(
            "BLOCKED",
            tuple(sorted({"ADMISSION_PREIMAGE_DRIFT", *fresh.conflicts})),
            planned_digest,
            fresh_digest,
        )
    return AdmissionReservationV1("READY", (), planned_digest, fresh_digest)


@dataclass(frozen=True, slots=True)
class AdmissionLockRecoveryPlanV1:
    decision: str
    conflicts: tuple[str, ...]
    lock_preimage_digest: str
    authorization_digest: str
    planned_domain_mutation_count: int = 0
    planned_coordination_mutation_count: int = 0


def plan_lock_recovery(
    inspection: AdmissionLockInspectionV1,
    *,
    owner_liveness: str,
    expected_preimage_digest: str,
    authorization_digest: str,
    expected_authorization_digest: str,
) -> AdmissionLockRecoveryPlanV1:
    """只生成 recovery plan；本模块不提供真实 stale-lock 删除入口。"""

    conflicts: set[str] = set()
    if inspection.state != "HELD" or inspection.metadata is None:
        conflicts.add("ADMISSION_LOCK_OR_CAS_FAILED")
    if owner_liveness != "dead":
        conflicts.add("ADMISSION_LOCK_OWNER_NOT_PROVEN_DEAD")
    if inspection.preimage_digest != expected_preimage_digest:
        conflicts.add("ADMISSION_PREIMAGE_DRIFT")
    if authorization_digest != expected_authorization_digest:
        conflicts.add("ADMISSION_RECOVERY_AUTHORIZATION_MISMATCH")
    for field, value in (
        ("expected_preimage_digest", expected_preimage_digest),
        ("authorization_digest", authorization_digest),
        ("expected_authorization_digest", expected_authorization_digest),
    ):
        _require_sha256(value, field=field)
    ordered = tuple(sorted(conflicts))
    return AdmissionLockRecoveryPlanV1(
        decision="BLOCKED" if ordered else "READY",
        conflicts=ordered,
        lock_preimage_digest=inspection.preimage_digest,
        authorization_digest=authorization_digest,
    )


__all__ = [
    "CANONICAL_EVALUATOR_DIGEST",
    "CANONICAL_EVALUATOR_IDENTITY",
    "POLICY_REVISION",
    "AdmissionLockHandleV1",
    "AdmissionLockInspectionV1",
    "AdmissionLockMetadataV1",
    "AdmissionLockRecoveryPlanV1",
    "AdmissionLockResultV1",
    "AdmissionReservationV1",
    "BudgetEvaluationV1",
    "SelfBudgetReceiptV1",
    "acquire_admission_lock",
    "admission_lock_path",
    "audit_execution_budget",
    "evaluate_execution_budget",
    "execution_inventory_digest",
    "inspect_admission_lock",
    "load_self_budget_receipt",
    "plan_admission",
    "plan_lock_recovery",
    "release_admission_lock",
    "validate_admission_preimage",
]
