"""Production write-plan validation through the sole Work decision graph.

The adapter captures repository facts but owns no writer.  Both plan and apply
call this module independently; only an exact graph digest match can cross the
imperative transaction boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from meta_flow.contracts.typed_ref import (
    RepositoryRole,
    TypedRefObjectKind,
    TypedRefV2,
    parse_typed_ref_v2,
)
from meta_flow.contracts.validation_policy import (
    ValidationLayer,
    ValidationPolicyV2,
    ValidationStrategy,
    normalize_validation_policy,
)
from meta_flow.execution_control.contract import canonical_digest
from meta_flow.execution_control.runtime_context import target_preimage_digest
from meta_flow.work.directory_envelope import (
    DirectoryWriteEnvelopeV1,
    EnvelopeDecisionV1,
    MatcherNode,
    MatcherOp,
    ObjectClass,
    PathFactsV1,
    PlanApplyBindingV1,
    match_write_envelope,
)
from meta_flow.work.git_inventory import InventoryCandidate, classify_candidate
from meta_flow.work.model import GovernanceProviderIdentityV1, admit_governance_provider
from meta_flow.work.validation_kernel import (
    AdmissionItemV2,
    DecisionStatus,
    NormalizedDecisionGraphV1,
    ValidationSnapshotV1,
    capture_validation_snapshot,
    evaluate_work,
)


def build_governance_provider_admission_validator(
    observed: GovernanceProviderIdentityV1,
    expected: GovernanceProviderIdentityV1,
) -> tuple[str, object]:
    """将 provider identity 作为 S01 V2 graph 的薄 validator 注入。"""

    def validator(_simulations: object) -> tuple[AdmissionItemV2, ...]:
        admission = admit_governance_provider(observed, expected)
        if admission.decision == "READY":
            return (
                AdmissionItemV2(
                    "governance-provider",
                    "GOVERNANCE_PROVIDER_READY",
                    DecisionStatus.PASS,
                ),
            )
        return tuple(
            AdmissionItemV2(
                "governance-provider",
                code,
                DecisionStatus.BLOCKED,
            )
            for code in admission.reason_codes
        )

    return "governance-provider", validator


@dataclass(frozen=True)
class ProductionValidationV1:
    snapshot: ValidationSnapshotV1
    graph: NormalizedDecisionGraphV1
    typed_ref_digest: str
    validation_policy_digest: str
    envelope_digest: str
    envelope_decisions: tuple[EnvelopeDecisionV1, ...]
    provider_identity_digest: str = ""

    @property
    def passed(self) -> bool:
        return (
            self.graph.decision is DecisionStatus.PASS
            and self.graph.authoritative_decision_path_count == 1
            and self.graph.duplicate_rule_owner_count == 0
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "decision": self.graph.decision.value,
            "snapshot_digest": self.snapshot.source_digest,
            "graph_digest": self.graph.graph_digest,
            "authoritative_decision_path_count": self.graph.authoritative_decision_path_count,
            "duplicate_rule_owner_count": self.graph.duplicate_rule_owner_count,
            "planned_writes": list(self.graph.planned_writes),
            "typed_ref_digest": self.typed_ref_digest,
            "validation_policy_digest": self.validation_policy_digest,
            "envelope_digest": self.envelope_digest,
            "envelope_codes": [item.reason_code.value for item in self.envelope_decisions],
            "provider_identity_digest": self.provider_identity_digest,
            "mutation_count": 0,
        }


def validate_production_write_plan(
    *,
    operation: str,
    process_root: Path,
    release_oid: str,
    process_oid: str,
    dirty_inventory_digest: str,
    dirty_owned: bool,
    owner_id: str,
    wave_id: str,
    merge_order: int,
    write_refs: tuple[str, ...],
    target_preimages: tuple[tuple[str, str], ...],
    scope_digest: str,
    budget_digest: str,
    authorization_digest: str,
    resolver_identity: str,
    policy_identity: str,
    risk_class: str,
    gate_status: str = "PASS",
    dependency_receipt_status: str = "PASS",
    execution_context_status: str = "READY",
    governance_provider: GovernanceProviderIdentityV1 | None = None,
    expected_governance_provider: GovernanceProviderIdentityV1 | None = None,
) -> ProductionValidationV1:
    """Validate one exact write set and return the only authoritative graph."""

    if (governance_provider is None) != (expected_governance_provider is None):
        raise ValueError("provider identity requires observed and expected values")
    provider_identity_digest = ""
    if governance_provider is not None and expected_governance_provider is not None:
        admission = admit_governance_provider(
            governance_provider,
            expected_governance_provider,
        )
        if admission.decision != "READY":
            raise ValueError("GOVERNANCE_PROVIDER_BLOCKED:" + ",".join(admission.reason_codes))
        provider_identity_digest = governance_provider.identity_digest

    refs = tuple(sorted(set(write_refs)))
    if refs != write_refs:
        raise ValueError("write_refs must be a canonical unique tuple")
    preimages = dict(target_preimages)
    if any(ref not in preimages for ref in refs):
        raise ValueError("every write ref requires an exact target preimage")

    parsed_refs = tuple(
        parse_typed_ref_v2(
            TypedRefV2(
                2,
                RepositoryRole.PROCESS,
                TypedRefObjectKind.OTHER,
                f"process/{ref}",
            ),
            resolver_identity=resolver_identity,
        )
        for ref in refs
    )
    typed_ref_digest = canonical_digest(
        [
            {
                "role": result.value.repository_role.value,
                "kind": result.value.object_kind.value,
                "ref": result.value.canonical_ref,
                "decision": result.provenance.decision_code,
            }
            for result in parsed_refs
        ]
    )
    policy_result = normalize_validation_policy(
        ValidationPolicyV2(
            2,
            ValidationStrategy.TARGETED_COMPATIBILITY_FULL,
            tuple(ValidationLayer),
            risk_class,
            scope_digest,
            2,
        ),
        policy_identity=policy_identity,
    )
    validation_policy_digest = canonical_digest(
        {
            "schema_version": policy_result.value.schema_version,
            "strategy": policy_result.value.default_strategy.value,
            "required_layers": [item.value for item in policy_result.value.required_layers],
            "risk_class": policy_result.value.risk_class,
            "scope_digest": policy_result.value.scope_digest,
            "profile_revision": policy_result.value.profile_revision,
            "decision": policy_result.provenance.decision_code,
        }
    )

    envelope_decisions: tuple[EnvelopeDecisionV1, ...]
    if refs:
        matcher = MatcherNode(
            MatcherOp.ANY_OF,
            rules=tuple(MatcherNode(MatcherOp.EXACT_LEAF, value=ref) for ref in refs),
        )
        envelope = DirectoryWriteEnvelopeV1(
            owner_story_id=owner_id,
            wave_id=wave_id,
            merge_order=merge_order,
            exact_dirs=tuple(
                sorted(
                    {
                        Path(ref).parent.as_posix()
                        for ref in refs
                        if Path(ref).parent != Path(".")
                    }
                )
            ),
            matcher=matcher,
            exclusions=(".git",),
            fallback_exact_leaves=refs,
        )
        binding = PlanApplyBindingV1(
            envelope.digest,
            envelope.digest,
            release_oid,
            process_oid,
            tuple((ref, preimages[ref]) for ref in refs),
        )
        envelope_decisions = tuple(
            match_write_envelope(
                envelope,
                ref,
                owner_id,
                wave_id,
                _path_facts(process_root, ref, preimages[ref]),
                binding,
                merge_order=merge_order,
            )
            for ref in refs
        )
        envelope_digest = envelope.digest
        envelope_decision = (
            "ADMITTED" if all(item.admitted for item in envelope_decisions) else "BLOCKED"
        )
    else:
        envelope_decisions = ()
        envelope_digest = canonical_digest({"kind": "DirectoryWriteEnvelopeV1", "writes": []})
        envelope_decision = "NO_WRITES"

    context: dict[str, object] = {
        "release_oid": release_oid,
        "process_oid": process_oid,
        "dirty_owned": dirty_owned,
        "profile": "production-v2",
        "typed_ref_digest": typed_ref_digest,
        "validation_policy_digest": validation_policy_digest,
        "scope_digest": scope_digest,
        "budget_digest": budget_digest,
        "authorization_digest": authorization_digest,
        "dirty_inventory_digest": dirty_inventory_digest,
        "envelope_digest": envelope_digest,
        "envelope_decision": envelope_decision,
        "preimage_digest": canonical_digest(dict(target_preimages)),
        "dependency_receipt_status": dependency_receipt_status,
        "gate_status": gate_status,
        "execution_context_status": execution_context_status,
        "planned_write_refs": refs,
    }
    snapshot = capture_validation_snapshot(operation, context)
    graph = evaluate_work(snapshot)
    return ProductionValidationV1(
        snapshot,
        graph,
        typed_ref_digest,
        validation_policy_digest,
        envelope_digest,
        envelope_decisions,
        provider_identity_digest,
    )


def _path_facts(process_root: Path, ref: str, expected_preimage: str) -> PathFactsV1:
    root = process_root.resolve()
    target = root / ref
    candidate_class = classify_candidate(root, InventoryCandidate("process", "write-plan", ref))
    object_class = {
        "tracked_regular": ObjectClass.REGULAR_EXISTING,
        "tracked_symlink": ObjectClass.SYMLINK,
        "ignored_generated": ObjectClass.IGNORED,
        "submodule": ObjectClass.SUBMODULE,
        "outside_repo": ObjectClass.OUTSIDE,
        "duplicate": ObjectClass.DUPLICATE_LOGICAL_OWNER,
        "missing": ObjectClass.MISSING_PARENT,
        "prospective_untracked": (
            ObjectClass.REGULAR_EXISTING if target.is_file() else ObjectClass.APPROVED_MISSING_LEAF
        ),
    }[candidate_class]
    return PathFactsV1(
        path=ref,
        object_class=object_class,
        parent_safe=_parent_chain_safe(root, target.parent),
        repository_contained=_contained(root, target),
        ignored=candidate_class == "ignored_generated",
        submodule=candidate_class == "submodule",
        logical_owner_count=1,
        expected_preimage_digest=expected_preimage,
        current_preimage_digest=target_preimage_digest(target),
    )


def _contained(root: Path, target: Path) -> bool:
    try:
        target.resolve(strict=False).relative_to(root)
    except ValueError:
        return False
    return True


def _parent_chain_safe(root: Path, parent: Path) -> bool:
    if not _contained(root, parent):
        return False
    current = parent
    while current != root:
        if current.is_symlink() or (current.exists() and not current.is_dir()):
            return False
        current = current.parent
    return root.is_dir() and not root.is_symlink()
