"""Execution Control 的 native-ledger 锚定只读终态闭合审计。"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from meta_flow.execution_control.contract import (
    FINGERPRINT_KEYS,
    INVALIDATABLE_LAYERS,
    ClosureAuditV1,
    _normalize_refs,
    _positive_int,
    _safe_id,
    _safe_ref,
    canonical_digest,
)
from meta_flow.project.process_route import _resolve_runtime_path, _resolve_runtime_ref
from meta_flow.state import event_ledger
from meta_flow.work.validation_receipt import load_validation_receipt
from meta_flow.workflow.cr_projection import NativeCRStatusProjectionV1

INVENTORY_KINDS = (
    "container",
    "dispatch",
    "result",
    "evidence",
    "projection",
    "receipt",
)
_COUNTER_BY_KIND = {kind: f"dangling_{kind}_count" for kind in INVENTORY_KINDS}
_OWNER_BY_KIND = {
    "container": "meta_flow.work.model",
    "dispatch": "meta_flow.state.event_ledger",
    "result": "meta_flow.checks.cp_result",
    "evidence": "meta_flow.checks.cp_result",
    "projection": "meta_flow.workflow.cr_lifecycle",
    "receipt": "meta_flow.work.validation_receipt",
}
_OWNER_SOURCE_BY_KIND = {
    "container": "meta_flow/work/model.py",
    "dispatch": "meta_flow/state/event_ledger.py",
    "result": "meta_flow/checks/cp_result.py",
    "evidence": "meta_flow/checks/cp_result.py",
    "projection": "meta_flow/workflow/cr_lifecycle.py",
    "receipt": "meta_flow/work/validation_receipt.py",
}
_OWNER_CALLABLE_BY_KIND = {
    "container": "meta_flow.work.model:load_work",
    "dispatch": "meta_flow.state.event_ledger:project_dispatch_attempt",
    "result": "meta_flow.checks.cp_result:project_cp_evidence_inventory",
    "evidence": "meta_flow.checks.cp_result:project_cp_evidence_inventory",
    "projection": "meta_flow.workflow.cr_lifecycle:project_native_cr_status",
    "receipt": "meta_flow.work.validation_receipt:load_validation_receipt",
}
_INVALIDATION_BY_KIND = {
    "container": ("closure",),
    "dispatch": ("closure",),
    "result": ("closure",),
    "evidence": ("closure",),
    "projection": ("closure",),
    "receipt": tuple(sorted(INVALIDATABLE_LAYERS)),
}
_REGISTRY_REVISION = "closure-projector-registry-v1"
_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
_PACKAGE_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class ClosureCohortV1:
    """由 native CP authority 确定的有界审计 cohort。"""

    unit_id: str
    root_concept: str
    slice_id: str
    cohort_revision: int
    descendant_unit_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _safe_id(self.unit_id, field="unit_id")
        _safe_id(self.root_concept, field="root_concept")
        _safe_id(self.slice_id, field="slice_id")
        _positive_int(self.cohort_revision, field="cohort_revision")
        descendants = tuple(
            sorted(_safe_id(item, field="descendant_unit_ids") for item in self.descendant_unit_ids)
        )
        if len(descendants) != len(set(descendants)) or self.unit_id in descendants:
            raise ValueError("descendant_unit_ids must be unique and exclude unit_id")
        object.__setattr__(self, "descendant_unit_ids", descendants)

    @property
    def unit_ids(self) -> frozenset[str]:
        return frozenset((self.unit_id, *self.descendant_unit_ids))

    def as_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "root_concept": self.root_concept,
            "slice_id": self.slice_id,
            "cohort_revision": self.cohort_revision,
            "descendant_unit_ids": list(self.descendant_unit_ids),
        }


@dataclass(frozen=True, slots=True)
class ClosureInventoryItemV1:
    kind: str
    ref: str
    unit_id: str
    root_concept: str
    slice_id: str
    cohort_revision: int
    dangling: bool

    def __post_init__(self) -> None:
        if self.kind not in INVENTORY_KINDS:
            raise ValueError("closure inventory kind is unsupported")
        object.__setattr__(self, "ref", _safe_ref(self.ref, field="ref"))
        _safe_id(self.unit_id, field="unit_id")
        _safe_id(self.root_concept, field="root_concept")
        _safe_id(self.slice_id, field="slice_id")
        _positive_int(self.cohort_revision, field="cohort_revision")
        if type(self.dangling) is not bool:
            raise ValueError("dangling must be a bool")

    def belongs_to(self, cohort: ClosureCohortV1) -> bool:
        return (
            self.unit_id in cohort.unit_ids
            and self.root_concept == cohort.root_concept
            and self.slice_id == cohort.slice_id
            and self.cohort_revision == cohort.cohort_revision
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "ref": self.ref,
            "unit_id": self.unit_id,
            "root_concept": self.root_concept,
            "slice_id": self.slice_id,
            "cohort_revision": self.cohort_revision,
            "dangling": self.dangling,
        }


def inventory_item(
    *,
    kind: str,
    ref: str,
    cohort: ClosureCohortV1,
    dangling: bool,
    unit_id: str | None = None,
) -> ClosureInventoryItemV1:
    return ClosureInventoryItemV1(
        kind=kind,
        ref=ref,
        unit_id=unit_id or cohort.unit_id,
        root_concept=cohort.root_concept,
        slice_id=cohort.slice_id,
        cohort_revision=cohort.cohort_revision,
        dangling=dangling,
    )


@dataclass(frozen=True, slots=True)
class ClosureOwnerCensusV1:
    kind: str
    items: tuple[ClosureInventoryItemV1, ...]
    source_refs: tuple[str, ...]
    findings: tuple[str, ...] = ()
    grandfathered_legacy_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in INVENTORY_KINDS:
            raise ValueError("closure census kind is unsupported")
        if any(item.kind != self.kind for item in self.items):
            raise ValueError("closure census contains a different inventory kind")
        ordered = tuple(sorted(self.items, key=lambda item: (item.ref, item.unit_id)))
        if len({(item.ref, item.unit_id) for item in ordered}) != len(ordered):
            raise ValueError("closure census contains duplicate identities")
        object.__setattr__(self, "items", ordered)
        object.__setattr__(
            self, "source_refs", _normalize_refs(self.source_refs, field="source_refs")
        )
        object.__setattr__(self, "findings", tuple(sorted(set(self.findings))))
        object.__setattr__(
            self,
            "grandfathered_legacy_refs",
            _normalize_refs(
                self.grandfathered_legacy_refs,
                field="grandfathered_legacy_refs",
            ),
        )

    @property
    def output_digest(self) -> str:
        return canonical_digest(
            {
                "kind": self.kind,
                "items": [item.as_dict() for item in self.items],
                "findings": list(self.findings),
                "grandfathered_legacy_refs": list(self.grandfathered_legacy_refs),
            }
        )


Projector = Callable[[Path, Any, ClosureCohortV1], ClosureOwnerCensusV1]


def _callable_ref(value: Callable[..., Any]) -> str:
    return f"{value.__module__}:{value.__qualname__}"


def _callable_contract_digest(value: Callable[..., Any]) -> str:
    try:
        source = inspect.getsource(value)
    except (OSError, TypeError):
        source = ""
    return canonical_digest(
        {
            "callable_ref": _callable_ref(value),
            "signature": str(inspect.signature(value)),
            "source": source,
        }
    )


def _package_source_digest(ref: str) -> str:
    path = (_PACKAGE_ROOT / ref).resolve()
    if not path.is_file() or not path.is_relative_to(_PACKAGE_ROOT):
        return _EMPTY_SHA256
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _declared_owner_callable_digest(kind: str) -> str:
    """从 package source 冻结 owner callable，而不是依赖运行时首次调用。"""

    ref = _OWNER_SOURCE_BY_KIND[kind]
    callable_ref = _OWNER_CALLABLE_BY_KIND[kind]
    function_name = callable_ref.rsplit(":", 1)[1]
    path = (_PACKAGE_ROOT / ref).resolve()
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, UnicodeDecodeError, SyntaxError):
        return _EMPTY_SHA256
    node = next(
        (
            item
            for item in tree.body
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            and item.name == function_name
        ),
        None,
    )
    segment = ast.get_source_segment(source, node) if node is not None else None
    if not segment:
        return _EMPTY_SHA256
    return canonical_digest({"callable_ref": callable_ref, "source": segment.strip()})


def _owner_callable(kind: str) -> Callable[..., Any]:
    if kind == "container":
        from meta_flow.work.model import load_work

        return load_work
    if kind == "dispatch":
        return event_ledger.project_dispatch_attempt
    if kind in {"result", "evidence"}:
        from meta_flow.checks.cp_result import project_cp_evidence_inventory

        return project_cp_evidence_inventory
    if kind == "projection":
        from meta_flow.workflow.cr_lifecycle import project_native_cr_status

        return project_native_cr_status
    return load_validation_receipt


def _runtime_owner_callable_digest(value: Callable[..., Any]) -> str:
    try:
        source = inspect.getsource(value)
    except (OSError, TypeError):
        return _EMPTY_SHA256
    return canonical_digest({"callable_ref": _callable_ref(value), "source": source.strip()})


@dataclass(frozen=True, slots=True)
class CanonicalClosureProjectorBindingV1:
    kind: str
    registry_revision: str
    callable_ref: str
    callable_contract_digest: str
    owner_identity: str
    owner_source_ref: str
    owner_source_digest: str
    owner_callable_ref: str
    owner_callable_contract_digest: str
    owner_callable: Callable[..., Any]
    projector: Projector

    def as_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "registry_revision": self.registry_revision,
            "callable_ref": self.callable_ref,
            "callable_contract_digest": self.callable_contract_digest,
            "owner_identity": self.owner_identity,
            "owner_source_ref": self.owner_source_ref,
            "owner_source_digest": self.owner_source_digest,
            "owner_callable_ref": self.owner_callable_ref,
            "owner_callable_contract_digest": self.owner_callable_contract_digest,
        }


@dataclass(frozen=True, slots=True)
class ClosureProjectorProvenanceV1:
    kind: str
    registry_revision: str
    expected_callable_ref: str
    expected_callable_contract_digest: str
    actual_callable_ref: str
    actual_callable_contract_digest: str
    callable_object_match: bool
    owner_identity: str
    owner_source_ref: str
    expected_owner_source_digest: str
    actual_owner_source_digest: str
    expected_owner_callable_ref: str
    expected_owner_callable_contract_digest: str
    actual_owner_callable_ref: str
    actual_owner_callable_contract_digest: str
    owner_callable_object_match: bool
    expected_refs: tuple[str, ...]
    output_digest: str
    executed: bool
    decision: str
    reason_codes: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "registry_revision": self.registry_revision,
            "expected_callable_ref": self.expected_callable_ref,
            "expected_callable_contract_digest": self.expected_callable_contract_digest,
            "actual_callable_ref": self.actual_callable_ref,
            "actual_callable_contract_digest": self.actual_callable_contract_digest,
            "callable_object_match": self.callable_object_match,
            "owner_identity": self.owner_identity,
            "owner_source_ref": self.owner_source_ref,
            "expected_owner_source_digest": self.expected_owner_source_digest,
            "actual_owner_source_digest": self.actual_owner_source_digest,
            "expected_owner_callable_ref": self.expected_owner_callable_ref,
            "expected_owner_callable_contract_digest": self.expected_owner_callable_contract_digest,
            "actual_owner_callable_ref": self.actual_owner_callable_ref,
            "actual_owner_callable_contract_digest": self.actual_owner_callable_contract_digest,
            "owner_callable_object_match": self.owner_callable_object_match,
            "expected_refs": list(self.expected_refs),
            "output_digest": self.output_digest,
            "executed": self.executed,
            "decision": self.decision,
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True, slots=True)
class ClosureAuditResultV1:
    audit: ClosureAuditV1
    cohort_decision: str
    strict_project_decision: str
    reason_codes: tuple[str, ...]
    dangling_refs: tuple[tuple[str, tuple[str, ...]], ...]
    invalidated_layers: tuple[str, ...]
    authority_decision: str
    authority_provenance_digest: str
    projector_provenance: tuple[ClosureProjectorProvenanceV1, ...]
    fingerprint_provenance_digest: str
    audit_digest: str
    mutation_count: int
    result_digest: str

    def as_dict(self, *, include_result_digest: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": 2,
            "audit": self.audit.as_dict(),
            "cohort_decision": self.cohort_decision,
            "strict_project_decision": self.strict_project_decision,
            "reason_codes": list(self.reason_codes),
            "dangling_refs": {kind: list(refs) for kind, refs in self.dangling_refs},
            "invalidated_layers": list(self.invalidated_layers),
            "authority_decision": self.authority_decision,
            "authority_provenance_digest": self.authority_provenance_digest,
            "projector_provenance": [item.as_dict() for item in self.projector_provenance],
            "fingerprint_provenance_digest": self.fingerprint_provenance_digest,
            "audit_digest": self.audit_digest,
            "mutation_count": self.mutation_count,
        }
        if include_result_digest:
            payload["result_digest"] = self.result_digest
        return payload


def project_dispatch_closure_inventory(
    *,
    cohort: ClosureCohortV1,
    events: tuple[Mapping[str, Any], ...],
    dispatch_ids: tuple[str, ...],
) -> tuple[ClosureInventoryItemV1, ...]:
    """只消费 event_ledger canonical terminal projector。"""

    normalized = tuple(sorted(_safe_id(item, field="dispatch_id") for item in dispatch_ids))
    if len(normalized) != len(set(normalized)):
        raise ValueError("dispatch_ids must not contain duplicates")
    return tuple(
        inventory_item(
            kind="dispatch",
            ref=dispatch_id,
            cohort=cohort,
            dangling=not event_ledger.project_dispatch_attempt(
                event_ledger.ProjectionInputV1(events, "dispatch", dispatch_id)
            ).terminal_success,
        )
        for dispatch_id in normalized
    )


def project_cr_consistency_inventory(
    *, cohort: ClosureCohortV1, projection: object
) -> tuple[ClosureInventoryItemV1, ...]:
    """只接受 canonical CR projection 的闭合类型，不猜 formal ref。"""

    if not isinstance(projection, NativeCRStatusProjectionV1):
        return (
            inventory_item(
                kind="projection",
                ref="projection/noncanonical-owner",
                cohort=cohort,
                dangling=True,
            ),
        )
    required = (
        projection.cr_id,
        projection.formal_cr_ref,
        projection.summary_ref,
        projection.ledger_event_id,
    )
    complete = all(str(value).strip() for value in required)
    return (
        inventory_item(
            kind="projection",
            ref=(projection.formal_cr_ref if complete else "projection/native-identity-missing"),
            cohort=cohort,
            dangling=not complete or projection.decision != "PASS" or bool(projection.findings),
        ),
    )


def _process_root(project_root: Path) -> Path:
    return _resolve_runtime_ref(project_root, "process/.meta-flow-process.yaml").parent


def project_container_closure_inventory(
    project_root: Path, authority: Any, cohort: ClosureCohortV1
) -> ClosureOwnerCensusV1:
    from meta_flow.work.model import load_work

    items: list[ClosureInventoryItemV1] = []
    findings: list[str] = []
    process_root = _process_root(project_root)
    for ref in authority.container_refs:
        work_id = Path(ref).parent.name
        dangling = False
        try:
            work = load_work(process_root, work_id)
            dangling = work.work_id != work_id
        except (OSError, TypeError, ValueError) as exc:
            dangling = True
            findings.append(f"CONTAINER_OWNER_INVALID:{ref}:{type(exc).__name__}")
        items.append(inventory_item(kind="container", ref=ref, cohort=cohort, dangling=dangling))
    return ClosureOwnerCensusV1(
        kind="container",
        items=tuple(items),
        source_refs=tuple((*authority.container_refs, _OWNER_SOURCE_BY_KIND["container"])),
        findings=tuple(findings),
    )


def project_dispatch_owner_inventory(
    project_root: Path, authority: Any, cohort: ClosureCohortV1
) -> ClosureOwnerCensusV1:
    ledger_ref = "process/state/AGENT-DISPATCH-LEDGER.ndjson"
    events, errors = event_ledger.load_events(_resolve_runtime_path(project_root, ledger_ref))
    items = project_dispatch_closure_inventory(
        cohort=cohort,
        events=tuple(events),
        dispatch_ids=authority.dispatch_refs,
    )
    return ClosureOwnerCensusV1(
        kind="dispatch",
        items=items,
        source_refs=(ledger_ref, _OWNER_SOURCE_BY_KIND["dispatch"]),
        findings=tuple(errors),
    )


def _project_cp_owner_inventory(
    project_root: Path, authority: Any, cohort: ClosureCohortV1, *, kind: str
) -> ClosureOwnerCensusV1:
    from meta_flow.checks import cp_result

    projection = cp_result.project_cp_evidence_inventory(
        project_root,
        cohort=cohort,
        result_refs=(authority.result_ref,),
    )
    items = projection.result_items if kind == "result" else projection.evidence_items
    return ClosureOwnerCensusV1(
        kind=kind,
        items=items,
        source_refs=tuple(
            sorted(
                {
                    authority.result_ref,
                    *(item.ref for item in items),
                    _OWNER_SOURCE_BY_KIND[kind],
                }
            )
        ),
        findings=projection.findings,
    )


def project_result_owner_inventory(
    project_root: Path, authority: Any, cohort: ClosureCohortV1
) -> ClosureOwnerCensusV1:
    return _project_cp_owner_inventory(project_root, authority, cohort, kind="result")


def project_evidence_owner_inventory(
    project_root: Path, authority: Any, cohort: ClosureCohortV1
) -> ClosureOwnerCensusV1:
    return _project_cp_owner_inventory(project_root, authority, cohort, kind="evidence")


def project_projection_owner_inventory(
    project_root: Path, authority: Any, cohort: ClosureCohortV1
) -> ClosureOwnerCensusV1:
    from meta_flow.workflow.cr_lifecycle import project_native_cr_status

    projection = project_native_cr_status(project_root, cr_id=authority.cr_id)
    items = project_cr_consistency_inventory(cohort=cohort, projection=projection)
    return ClosureOwnerCensusV1(
        kind="projection",
        items=items,
        source_refs=tuple(
            sorted(
                {
                    *(item.ref for item in items),
                    projection.summary_ref or "projection/native-summary-missing",
                    "process/changes/CR-INDEX.json",
                    "process/state/CR-LEDGER.ndjson",
                    _OWNER_SOURCE_BY_KIND["projection"],
                }
            )
        ),
        findings=projection.findings,
    )


def project_receipt_owner_inventory(
    project_root: Path, authority: Any, cohort: ClosureCohortV1
) -> ClosureOwnerCensusV1:
    items: list[ClosureInventoryItemV1] = []
    findings: list[str] = []
    for ref in authority.receipt_refs:
        dangling = False
        try:
            receipt = load_validation_receipt(_resolve_runtime_path(project_root, ref))
            dangling = receipt.decision != "PASS"
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            dangling = True
            findings.append(f"RECEIPT_OWNER_INVALID:{ref}:{type(exc).__name__}")
        items.append(inventory_item(kind="receipt", ref=ref, cohort=cohort, dangling=dangling))
    return ClosureOwnerCensusV1(
        kind="receipt",
        items=tuple(items),
        source_refs=tuple((*authority.receipt_refs, _OWNER_SOURCE_BY_KIND["receipt"])),
        findings=tuple(findings),
    )


def _binding(kind: str, projector: Projector) -> CanonicalClosureProjectorBindingV1:
    owner_callable = _owner_callable(kind)
    return CanonicalClosureProjectorBindingV1(
        kind=kind,
        registry_revision=_REGISTRY_REVISION,
        callable_ref=_callable_ref(projector),
        callable_contract_digest=_callable_contract_digest(projector),
        owner_identity=_OWNER_BY_KIND[kind],
        owner_source_ref=_OWNER_SOURCE_BY_KIND[kind],
        owner_source_digest=_package_source_digest(_OWNER_SOURCE_BY_KIND[kind]),
        owner_callable_ref=_OWNER_CALLABLE_BY_KIND[kind],
        owner_callable_contract_digest=_declared_owner_callable_digest(kind),
        owner_callable=owner_callable,
        projector=projector,
    )


# 在模块加载时冻结 callable 对象与 contract/code digest；运行时 caller 无法替换本表。
_CLOSED_PROJECTOR_REGISTRY = {
    binding.kind: binding
    for binding in (
        _binding("container", project_container_closure_inventory),
        _binding("dispatch", project_dispatch_owner_inventory),
        _binding("result", project_result_owner_inventory),
        _binding("evidence", project_evidence_owner_inventory),
        _binding("projection", project_projection_owner_inventory),
        _binding("receipt", project_receipt_owner_inventory),
    )
}


def _blocked_census(kind: str, cohort: ClosureCohortV1, code: str) -> ClosureOwnerCensusV1:
    return ClosureOwnerCensusV1(
        kind=kind,
        items=(
            inventory_item(
                kind=kind,
                ref=f"projector/{kind}/blocked",
                cohort=cohort,
                dangling=True,
            ),
        ),
        source_refs=(_OWNER_SOURCE_BY_KIND[kind],),
        findings=(code,),
    )


def _run_projector(
    *,
    project_root: Path,
    authority: Any,
    cohort: ClosureCohortV1,
    binding: CanonicalClosureProjectorBindingV1,
    actual: Projector | None,
) -> tuple[ClosureOwnerCensusV1, ClosureProjectorProvenanceV1]:
    reasons: list[str] = []
    callable_object_match = actual is binding.projector
    owner_callable: Callable[..., Any] | None = None
    owner_callable_object_match = False
    if actual is None:
        census = _blocked_census(binding.kind, cohort, "CANONICAL_PROJECTOR_BYPASSED")
        actual_ref = "projector/bypassed"
        actual_digest = _EMPTY_SHA256
        executed = False
    else:
        actual_ref = _callable_ref(actual)
        actual_digest = _callable_contract_digest(actual)
        source_digest = _package_source_digest(binding.owner_source_ref)
        if not callable_object_match:
            reasons.append("CANONICAL_PROJECTOR_OBJECT_MISMATCH")
        if actual_ref != binding.callable_ref or actual_digest != binding.callable_contract_digest:
            reasons.append("CANONICAL_PROJECTOR_CALLABLE_MISMATCH")
        if source_digest != binding.owner_source_digest:
            reasons.append("CANONICAL_PROJECTOR_SOURCE_DRIFT")
        owner_callable = _owner_callable(binding.kind)
        owner_callable_ref = _callable_ref(owner_callable)
        owner_callable_digest = _runtime_owner_callable_digest(owner_callable)
        owner_callable_object_match = owner_callable is binding.owner_callable
        if not owner_callable_object_match:
            reasons.append("CANONICAL_OWNER_CALLABLE_OBJECT_MISMATCH")
        if (
            owner_callable_ref != binding.owner_callable_ref
            or owner_callable_digest != binding.owner_callable_contract_digest
        ):
            reasons.append("CANONICAL_OWNER_CALLABLE_MISMATCH")
        if reasons:
            census = _blocked_census(binding.kind, cohort, *reasons[:1])
            executed = False
        else:
            try:
                census = actual(project_root, authority, cohort)
            except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
                reasons.append(f"CANONICAL_PROJECTOR_ERROR_{type(exc).__name__.upper()}")
                census = _blocked_census(binding.kind, cohort, reasons[-1])
            executed = not reasons
    if census.kind != binding.kind:
        reasons.append("CANONICAL_PROJECTOR_KIND_MISMATCH")
        census = _blocked_census(binding.kind, cohort, reasons[-1])
        executed = False
    reasons.extend(census.findings)
    decision = "PASS" if executed and not reasons else "BLOCKED"
    provenance = ClosureProjectorProvenanceV1(
        kind=binding.kind,
        registry_revision=binding.registry_revision,
        expected_callable_ref=binding.callable_ref,
        expected_callable_contract_digest=binding.callable_contract_digest,
        actual_callable_ref=actual_ref,
        actual_callable_contract_digest=actual_digest,
        callable_object_match=callable_object_match,
        owner_identity=binding.owner_identity,
        owner_source_ref=binding.owner_source_ref,
        expected_owner_source_digest=binding.owner_source_digest,
        actual_owner_source_digest=_package_source_digest(binding.owner_source_ref),
        expected_owner_callable_ref=binding.owner_callable_ref,
        expected_owner_callable_contract_digest=binding.owner_callable_contract_digest,
        actual_owner_callable_ref=(
            _callable_ref(owner_callable) if owner_callable is not None else "owner/bypassed"
        ),
        actual_owner_callable_contract_digest=(
            _runtime_owner_callable_digest(owner_callable)
            if owner_callable is not None
            else _EMPTY_SHA256
        ),
        owner_callable_object_match=owner_callable_object_match,
        expected_refs=tuple(item.ref for item in census.items),
        output_digest=census.output_digest,
        executed=executed,
        decision=decision,
        reason_codes=tuple(sorted(set(reasons))),
    )
    return census, provenance


def _empty_fingerprints() -> tuple[tuple[str, str], ...]:
    return tuple((key, _EMPTY_SHA256) for key in sorted(FINGERPRINT_KEYS))


def _make_result(
    *,
    audit: ClosureAuditV1,
    reasons: set[str],
    dangling: dict[str, set[str]],
    invalidated: set[str],
    authority_decision: str,
    authority_digest: str,
    provenance: tuple[ClosureProjectorProvenanceV1, ...],
    fingerprint_digest: str,
) -> ClosureAuditResultV1:
    partial = ClosureAuditResultV1(
        audit=audit,
        cohort_decision="PASS" if audit.cohort_pass else "BLOCKED",
        strict_project_decision="PASS" if audit.strict_project_pass else "BLOCKED",
        reason_codes=tuple(sorted(reasons)),
        dangling_refs=tuple(
            (kind, tuple(sorted(dangling.get(kind, set())))) for kind in INVENTORY_KINDS
        ),
        invalidated_layers=tuple(sorted(invalidated)),
        authority_decision=authority_decision,
        authority_provenance_digest=authority_digest,
        projector_provenance=provenance,
        fingerprint_provenance_digest=fingerprint_digest,
        audit_digest=canonical_digest(audit),
        mutation_count=0,
        result_digest=_EMPTY_SHA256,
    )
    return replace(
        partial,
        result_digest=canonical_digest(partial.as_dict(include_result_digest=False)),
    )


def _blocked_authority_result(
    *, story_id: str, expected_cohort_revision: int, reason_codes: tuple[str, ...]
) -> ClosureAuditResultV1:
    fingerprints = _empty_fingerprints()
    safe_scope = story_id
    try:
        _safe_id(safe_scope, field="audit_scope")
    except ValueError:
        safe_scope = "closure-invalid-input"
    audit = ClosureAuditV1(
        audit_scope=safe_scope,
        cohort_revision=(expected_cohort_revision if expected_cohort_revision > 0 else 1),
        dangling_container_count=0,
        dangling_dispatch_count=0,
        dangling_result_count=1,
        dangling_evidence_count=1,
        dangling_projection_count=0,
        dangling_receipt_count=1,
        grandfathered_legacy_count=0,
        grandfathered_legacy_refs=(),
        fingerprints=fingerprints,
    )
    return _make_result(
        audit=audit,
        reasons={"CLOSURE_AUTHORITY_INVALID", *reason_codes},
        dangling={
            "result": {"authority/native-cp6"},
            "evidence": {"authority/return-evidence"},
            "receipt": {"authority/provenance"},
        },
        invalidated=set(INVALIDATABLE_LAYERS),
        authority_decision="BLOCKED",
        authority_digest=_EMPTY_SHA256,
        provenance=(),
        fingerprint_digest=_EMPTY_SHA256,
    )


def _audit_closure(
    project_root: Path,
    *,
    story_id: str,
    expected_cohort_revision: int,
    projector_overrides: Mapping[str, Projector | None] | None = None,
) -> ClosureAuditResultV1:
    """私有测试缝只替换 actual callable；expected binding 永远来自 closed registry。"""

    try:
        _safe_id(story_id, field="story_id")
        _positive_int(expected_cohort_revision, field="expected_cohort_revision")
    except ValueError as exc:
        return _blocked_authority_result(
            story_id=story_id,
            expected_cohort_revision=expected_cohort_revision,
            reason_codes=(f"CLOSURE_PUBLIC_INPUT_INVALID_{type(exc).__name__.upper()}",),
        )
    from meta_flow.checks.cp_result import project_native_closure_authority

    try:
        authority = project_native_closure_authority(
            project_root,
            story_id=story_id,
            expected_cohort_revision=expected_cohort_revision,
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return _blocked_authority_result(
            story_id=story_id,
            expected_cohort_revision=expected_cohort_revision,
            reason_codes=(f"CLOSURE_AUTHORITY_ERROR_{type(exc).__name__.upper()}",),
        )
    if authority.decision != "PASS":
        return _blocked_authority_result(
            story_id=story_id,
            expected_cohort_revision=expected_cohort_revision,
            reason_codes=authority.reason_codes,
        )
    cohort = ClosureCohortV1(
        unit_id=authority.cr_id,
        root_concept="execution-control",
        slice_id="closure",
        cohort_revision=expected_cohort_revision,
    )
    overrides = dict(projector_overrides or {})
    unknown = set(overrides) - set(INVENTORY_KINDS)
    if unknown:
        return _blocked_authority_result(
            story_id=story_id,
            expected_cohort_revision=expected_cohort_revision,
            reason_codes=("CLOSURE_TEST_PROJECTOR_KIND_UNKNOWN",),
        )
    censuses: dict[str, ClosureOwnerCensusV1] = {}
    provenance: list[ClosureProjectorProvenanceV1] = []
    for kind in INVENTORY_KINDS:
        binding = _CLOSED_PROJECTOR_REGISTRY[kind]
        actual = overrides[kind] if kind in overrides else binding.projector
        census, item_provenance = _run_projector(
            project_root=project_root.resolve(),
            authority=authority,
            cohort=cohort,
            binding=binding,
            actual=actual,
        )
        censuses[kind] = census
        provenance.append(item_provenance)

    reasons: set[str] = set()
    dangling: dict[str, set[str]] = {kind: set() for kind in INVENTORY_KINDS}
    invalidated: set[str] = set()
    legacy: set[str] = set()
    for kind in INVENTORY_KINDS:
        census = censuses[kind]
        item_provenance = provenance[INVENTORY_KINDS.index(kind)]
        if item_provenance.decision != "PASS":
            reasons.update(item_provenance.reason_codes)
        for item in census.items:
            if not item.belongs_to(cohort):
                reasons.add(f"{kind.upper()}_INVENTORY_LINEAGE_MISMATCH")
                dangling[kind].add(f"lineage/{item.ref}")
            elif item.dangling:
                dangling[kind].add(item.ref)
        legacy.update(census.grandfathered_legacy_refs)
        if dangling[kind] or item_provenance.decision != "PASS":
            invalidated.update(_INVALIDATION_BY_KIND[kind])

    fingerprints = tuple(sorted(authority.fingerprints))
    fingerprint_digest = canonical_digest(
        {
            "authority_digest": authority.authority_digest,
            "fingerprints": list(fingerprints),
            "projectors": [item.as_dict() for item in provenance],
        }
    )
    counters = {_COUNTER_BY_KIND[kind]: len(dangling[kind]) for kind in INVENTORY_KINDS}
    audit = ClosureAuditV1(
        audit_scope=cohort.unit_id,
        cohort_revision=cohort.cohort_revision,
        **counters,
        grandfathered_legacy_count=len(legacy),
        grandfathered_legacy_refs=tuple(sorted(legacy)),
        fingerprints=fingerprints,
    )
    for field in audit.COUNTER_FIELDS:
        if getattr(audit, field):
            reasons.add(f"{field.upper()}_NONZERO")
    if legacy:
        reasons.add("GRANDFATHERED_LEGACY_LIMITATION")
        invalidated.add("closure")
    return _make_result(
        audit=audit,
        reasons=reasons,
        dangling=dangling,
        invalidated=invalidated,
        authority_decision=authority.decision,
        authority_digest=authority.authority_digest,
        provenance=tuple(provenance),
        fingerprint_digest=fingerprint_digest,
    )


def audit_closure(
    project_root: Path,
    *,
    story_id: str,
    expected_cohort_revision: int,
) -> ClosureAuditResultV1:
    """从 native CP/ledger authority 运行六 owner census；全程只读。"""

    return _audit_closure(
        project_root,
        story_id=story_id,
        expected_cohort_revision=expected_cohort_revision,
    )
