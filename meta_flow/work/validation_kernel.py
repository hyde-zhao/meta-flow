"""The sole authoritative, pure Work validation decision facade."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class RuleDomainV1(StrEnum):
    IDENTITY_CONTRACTS = "IDENTITY_CONTRACTS"
    SCOPE_BUDGET = "SCOPE_BUDGET"
    AUTHORIZATION_GATES = "AUTHORIZATION_GATES"
    REPOSITORY_PREIMAGE_ENVELOPE = "REPOSITORY_PREIMAGE_ENVELOPE"
    DEPENDENCY_RECEIPT = "DEPENDENCY_RECEIPT"


class DecisionStatus(StrEnum):
    PASS = "PASS"
    BLOCKED = "BLOCKED"
    FAIL = "FAIL"


class AdmissionDispositionV2(StrEnum):
    """V2 预检的公共终态；它描述计划，不授予任何写权限。"""

    READY = "READY"
    BLOCKED = "BLOCKED"
    NO_CHANGE = "NO_CHANGE"


PRECEDENCE = tuple(RuleDomainV1)

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_BASE_CONTEXT_KEYS = {"release_oid", "process_oid", "dirty_owned"}
_PRODUCTION_CONTEXT_KEYS = {
    "profile",
    "typed_ref_digest",
    "validation_policy_digest",
    "scope_digest",
    "budget_digest",
    "authorization_digest",
    "dirty_inventory_digest",
    "envelope_digest",
    "envelope_decision",
    "preimage_digest",
    "dependency_receipt_status",
    "gate_status",
    "execution_context_status",
    "planned_write_refs",
}


@dataclass(frozen=True)
class ValidationSnapshotV1:
    operation: str
    facts: tuple[tuple[str, str], ...]
    release_oid: str
    process_oid: str
    dirty_owned: bool
    source_digest: str
    planned_writes: tuple[str, ...] = ()

    @property
    def snapshot_id(self) -> str:
        return self.source_digest

    def fact(self, key: str) -> str | None:
        return dict(self.facts).get(key)


@dataclass(frozen=True)
class RuleEvaluationV1:
    domain: RuleDomainV1
    rule_id: str
    decision: DecisionStatus
    code: str
    owner: str = "validation_kernel"


@dataclass(frozen=True)
class NormalizedDecisionGraphV1:
    snapshot_digest: str
    items: tuple[RuleEvaluationV1, ...]
    decision: DecisionStatus
    graph_digest: str
    authoritative_decision_path_count: int = 1
    duplicate_rule_owner_count: int = 0
    planned_writes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ValidationDecisionV1:
    graph_digest: str
    decision: DecisionStatus
    mutation_count: int = 0


@dataclass(frozen=True)
class ShadowParityReceiptV1:
    same_snapshot: bool
    graph_parity: bool
    cutover_eligible: bool
    authoritative_decision_path_count: int = 1


@dataclass(frozen=True)
class AdmissionItemV2:
    """V2 准入图中的确定性单项。"""

    owner: str
    code: str
    decision: DecisionStatus
    detail: str = ""


@dataclass(frozen=True)
class AdmissionDecisionV2:
    """成功、失败和 no-op 模拟汇合后的唯一只读决策。"""

    decision: AdmissionDispositionV2
    items: tuple[AdmissionItemV2, ...]
    lifecycle_digest: str
    graph_digest: str
    authoritative_decision_path_count: int = 1
    duplicate_rule_owner_count: int = 0
    mutation_count: int = 0


class LifecycleSimulationLike(Protocol):
    path: object
    terminal_disposition: str
    conflicts: tuple[str, ...]

    def as_digest_input(self) -> Mapping[str, object]: ...


AdmissionValidatorV2 = Callable[
    [tuple[LifecycleSimulationLike, ...]],
    Iterable[AdmissionItemV2],
]


def capture_validation_snapshot(operation: str, context: dict[str, object]) -> ValidationSnapshotV1:
    if operation not in {"init-preflight", "init-apply", "scope-amend-plan", "scope-amend-apply"}:
        raise ValueError("unknown operation")
    keys = set(context)
    production = bool(keys & _PRODUCTION_CONTEXT_KEYS)
    required = _BASE_CONTEXT_KEYS | (_PRODUCTION_CONTEXT_KEYS if production else set())
    if keys != required:
        raise ValueError("closed snapshot context required")
    if not all(isinstance(context[key], str) and context[key] for key in ("release_oid", "process_oid")):
        raise ValueError("missing repository OID")
    if not isinstance(context["dirty_owned"], bool):
        raise ValueError("dirty_owned must be boolean")
    planned_writes: tuple[str, ...] = ()
    if production:
        if context["profile"] != "production-v2":
            raise ValueError("unknown validation snapshot profile")
        digest_fields = {
            "typed_ref_digest",
            "validation_policy_digest",
            "scope_digest",
            "budget_digest",
            "authorization_digest",
            "dirty_inventory_digest",
            "envelope_digest",
            "preimage_digest",
        }
        if any(
            not isinstance(context[field], str)
            or not _DIGEST_RE.fullmatch(context[field])
            for field in digest_fields
        ):
            raise ValueError("production snapshot digests must be lowercase SHA-256")
        for field, allowed in {
            "envelope_decision": {"ADMITTED", "NO_WRITES"},
            "dependency_receipt_status": {"PASS", "BLOCKED"},
            "gate_status": {"PASS", "PENDING", "PARTIAL", "RECOVERED", "BLOCKED"},
            "execution_context_status": {"READY", "BLOCKED"},
        }.items():
            if context[field] not in allowed:
                raise ValueError(f"production snapshot {field} is invalid")
        raw_writes = context["planned_write_refs"]
        if (
            not isinstance(raw_writes, tuple)
            or tuple(sorted(set(raw_writes))) != raw_writes
            or any(not isinstance(ref, str) or not ref for ref in raw_writes)
        ):
            raise ValueError("planned_write_refs must be a canonical tuple")
        planned_writes = raw_writes
    facts = tuple(
        sorted(
            (key, json.dumps(value, sort_keys=True, separators=(",", ":")))
            for key, value in context.items()
            if key != "planned_write_refs"
        )
    )
    # Operation selects the adapter.  It is deliberately excluded from the
    # semantic digest so a separately captured apply snapshot can prove exact
    # parity with its plan snapshot when every authoritative fact is unchanged.
    digest = _digest({"facts": facts, "planned_writes": planned_writes})
    return ValidationSnapshotV1(
        operation,
        facts,
        str(context["release_oid"]),
        str(context["process_oid"]),
        context["dirty_owned"],
        digest,
        planned_writes,
    )


def _result(domain: RuleDomainV1, rule_id: str, decision: DecisionStatus, code: str) -> tuple[RuleEvaluationV1, ...]:
    return (RuleEvaluationV1(domain, rule_id, decision, code),)


def evaluate_identity_contracts(snapshot: ValidationSnapshotV1) -> tuple[RuleEvaluationV1, ...]:
    if _production(snapshot) and not all(
        _fact_digest(snapshot, field)
        for field in ("typed_ref_digest", "validation_policy_digest")
    ):
        return _result(RuleDomainV1.IDENTITY_CONTRACTS, "identity-closed", DecisionStatus.FAIL, "IDENTITY_CONTRACT_INVALID")
    return _result(RuleDomainV1.IDENTITY_CONTRACTS, "identity-closed", DecisionStatus.PASS, "IDENTITY_OK")


def evaluate_scope_budget(snapshot: ValidationSnapshotV1) -> tuple[RuleEvaluationV1, ...]:
    if _production(snapshot) and not all(
        _fact_digest(snapshot, field) for field in ("scope_digest", "budget_digest")
    ):
        return _result(RuleDomainV1.SCOPE_BUDGET, "scope-closed", DecisionStatus.BLOCKED, "SCOPE_BUDGET_INVALID")
    return _result(RuleDomainV1.SCOPE_BUDGET, "scope-closed", DecisionStatus.PASS, "SCOPE_OK")


def evaluate_authorization_gates(snapshot: ValidationSnapshotV1) -> tuple[RuleEvaluationV1, ...]:
    if _production(snapshot):
        gate = _fact_value(snapshot, "gate_status")
        if not _fact_digest(snapshot, "authorization_digest") or gate != "PASS":
            code = "GATE_NOT_PASS" if gate in {"PENDING", "PARTIAL", "RECOVERED", "BLOCKED"} else "AUTHORIZATION_INVALID"
            return _result(RuleDomainV1.AUTHORIZATION_GATES, "gates-closed", DecisionStatus.BLOCKED, code)
    return _result(RuleDomainV1.AUTHORIZATION_GATES, "gates-closed", DecisionStatus.PASS, "GATES_OK")


def evaluate_repository_preimage_envelope(snapshot: ValidationSnapshotV1) -> tuple[RuleEvaluationV1, ...]:
    if not snapshot.dirty_owned:
        return _result(RuleDomainV1.REPOSITORY_PREIMAGE_ENVELOPE, "dirty-owned", DecisionStatus.BLOCKED, "DIRTY_UNOWNED")
    if _production(snapshot):
        valid = all(
            _fact_digest(snapshot, field)
            for field in ("dirty_inventory_digest", "envelope_digest", "preimage_digest")
        )
        if not valid or _fact_value(snapshot, "envelope_decision") not in {"ADMITTED", "NO_WRITES"}:
            return _result(
                RuleDomainV1.REPOSITORY_PREIMAGE_ENVELOPE,
                "repository-binding",
                DecisionStatus.BLOCKED,
                "REPLAN_REQUIRED",
            )
    return _result(RuleDomainV1.REPOSITORY_PREIMAGE_ENVELOPE, "repository-binding", DecisionStatus.PASS, "REPOSITORY_OK")


def evaluate_dependency_receipt(snapshot: ValidationSnapshotV1) -> tuple[RuleEvaluationV1, ...]:
    if _production(snapshot) and (
        _fact_value(snapshot, "dependency_receipt_status") != "PASS"
        or _fact_value(snapshot, "execution_context_status") != "READY"
    ):
        return _result(RuleDomainV1.DEPENDENCY_RECEIPT, "receipt-closed", DecisionStatus.BLOCKED, "DEPENDENCY_RECEIPT_BLOCKED")
    return _result(RuleDomainV1.DEPENDENCY_RECEIPT, "receipt-closed", DecisionStatus.PASS, "RECEIPT_OK")


_EVALUATORS = {
    RuleDomainV1.IDENTITY_CONTRACTS: evaluate_identity_contracts,
    RuleDomainV1.SCOPE_BUDGET: evaluate_scope_budget,
    RuleDomainV1.AUTHORIZATION_GATES: evaluate_authorization_gates,
    RuleDomainV1.REPOSITORY_PREIMAGE_ENVELOPE: evaluate_repository_preimage_envelope,
    RuleDomainV1.DEPENDENCY_RECEIPT: evaluate_dependency_receipt,
}


def evaluate_work(snapshot: ValidationSnapshotV1, rule_set: tuple[RuleDomainV1, ...] = PRECEDENCE) -> NormalizedDecisionGraphV1:
    if rule_set != PRECEDENCE or len(set(rule_set)) != len(PRECEDENCE):
        items = (RuleEvaluationV1(RuleDomainV1.IDENTITY_CONTRACTS, "rule-set", DecisionStatus.FAIL, "RULE_SET_INVALID"),)
        return _graph(snapshot, items, duplicate_owners=0, authority=1)
    items = tuple(item for domain in PRECEDENCE for item in _EVALUATORS[domain](snapshot))
    duplicate = len(items) - len({item.rule_id for item in items})
    return _graph(snapshot, items, duplicate_owners=duplicate, authority=1)


def _graph(snapshot: ValidationSnapshotV1, items: tuple[RuleEvaluationV1, ...], *, duplicate_owners: int, authority: int) -> NormalizedDecisionGraphV1:
    decision = DecisionStatus.FAIL if duplicate_owners or authority != 1 or any(item.decision is DecisionStatus.FAIL for item in items) else (DecisionStatus.BLOCKED if any(item.decision is DecisionStatus.BLOCKED for item in items) else DecisionStatus.PASS)
    payload = {"snapshot": snapshot.source_digest, "items": [(i.domain, i.rule_id, i.decision, i.code) for i in items], "decision": decision, "authority": authority, "duplicates": duplicate_owners, "planned_writes": snapshot.planned_writes}
    return NormalizedDecisionGraphV1(snapshot.source_digest, items, decision, _digest(payload), authority, duplicate_owners, snapshot.planned_writes)


def compare_shadow_graph(authoritative: NormalizedDecisionGraphV1, shadow: NormalizedDecisionGraphV1) -> ShadowParityReceiptV1:
    same_snapshot = authoritative.snapshot_digest == shadow.snapshot_digest
    graph_parity = authoritative.graph_digest == shadow.graph_digest
    eligible = same_snapshot and graph_parity and authoritative.authoritative_decision_path_count == 1 and authoritative.duplicate_rule_owner_count == 0
    return ShadowParityReceiptV1(same_snapshot, graph_parity, eligible)


def decision_from_graph(graph: NormalizedDecisionGraphV1) -> ValidationDecisionV1:
    return ValidationDecisionV1(graph.graph_digest, graph.decision, mutation_count=0)


def build_admission_decision_v2(
    simulations: Iterable[LifecycleSimulationLike],
    validators: Iterable[tuple[str, AdmissionValidatorV2]] = (),
) -> AdmissionDecisionV2:
    """聚合一次完整 lifecycle 模拟；validator 只能返回事实，不能写入。"""

    ordered = tuple(sorted(simulations, key=lambda value: str(value.path)))
    path_names = tuple(str(getattr(value.path, "value", value.path)) for value in ordered)
    required_paths = ("failure", "no_op", "success")
    lifecycle_payload = [value.as_digest_input() for value in ordered]
    lifecycle_digest = _digest(lifecycle_payload)
    items: list[AdmissionItemV2] = []
    if path_names != required_paths:
        items.append(
            AdmissionItemV2(
                "lifecycle-simulator",
                "LIFECYCLE_PATH_SET_INCOMPLETE",
                DecisionStatus.BLOCKED,
                ",".join(path_names),
            )
        )
    for simulation in ordered:
        for conflict in sorted(set(simulation.conflicts)):
            items.append(
                AdmissionItemV2(
                    "lifecycle-simulator",
                    conflict,
                    DecisionStatus.BLOCKED,
                    str(getattr(simulation.path, "value", simulation.path)),
                )
            )

    validator_entries = tuple(validators)
    owners = tuple(owner for owner, _validator in validator_entries)
    duplicate_owner_count = len(owners) - len(set(owners))
    if any(not owner or owner.strip() != owner for owner in owners):
        items.append(
            AdmissionItemV2(
                "validation-kernel",
                "VALIDATOR_OWNER_INVALID",
                DecisionStatus.FAIL,
            )
        )
    for owner, validator in validator_entries:
        produced = tuple(validator(ordered))
        for item in produced:
            if not isinstance(item, AdmissionItemV2) or item.owner != owner:
                items.append(
                    AdmissionItemV2(
                        "validation-kernel",
                        "VALIDATOR_OUTPUT_INVALID",
                        DecisionStatus.FAIL,
                        owner,
                    )
                )
                break
            items.append(item)
    if duplicate_owner_count:
        items.append(
            AdmissionItemV2(
                "validation-kernel",
                "DUPLICATE_RULE_OWNER",
                DecisionStatus.FAIL,
                ",".join(sorted(owner for owner in set(owners) if owners.count(owner) > 1)),
            )
        )

    canonical_items = tuple(
        sorted(items, key=lambda item: (item.owner, item.code, item.decision.value, item.detail))
    )
    blocked = duplicate_owner_count > 0 or any(
        item.decision in {DecisionStatus.BLOCKED, DecisionStatus.FAIL}
        for item in canonical_items
    )
    no_change = (
        not blocked
        and len(ordered) == 3
        and all(
            simulation.terminal_disposition in {"NO_CHANGE", "NOT_APPLICABLE"}
            for simulation in ordered
        )
        and any(simulation.terminal_disposition == "NO_CHANGE" for simulation in ordered)
    )
    decision = (
        AdmissionDispositionV2.BLOCKED
        if blocked
        else AdmissionDispositionV2.NO_CHANGE
        if no_change
        else AdmissionDispositionV2.READY
    )
    graph_digest = _digest(
        {
            "schema_version": 2,
            "lifecycle_digest": lifecycle_digest,
            "items": [
                (item.owner, item.code, item.decision.value, item.detail)
                for item in canonical_items
            ],
            "decision": decision.value,
            "authority": 1,
            "duplicate_rule_owner_count": duplicate_owner_count,
        }
    )
    return AdmissionDecisionV2(
        decision=decision,
        items=canonical_items,
        lifecycle_digest=lifecycle_digest,
        graph_digest=graph_digest,
        authoritative_decision_path_count=1,
        duplicate_rule_owner_count=duplicate_owner_count,
        mutation_count=0,
    )


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, default=str, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _fact_value(snapshot: ValidationSnapshotV1, key: str) -> object | None:
    raw = snapshot.fact(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _fact_digest(snapshot: ValidationSnapshotV1, key: str) -> bool:
    value = _fact_value(snapshot, key)
    return isinstance(value, str) and _DIGEST_RE.fullmatch(value) is not None


def _production(snapshot: ValidationSnapshotV1) -> bool:
    return _fact_value(snapshot, "profile") == "production-v2"
