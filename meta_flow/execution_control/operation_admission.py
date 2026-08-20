"""跨领域 mutation operation 共用的准入与 MutationPlanV2 合同。"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from meta_flow.execution_control.contract import canonical_digest
from meta_flow.workspace.git_sync import run_git


def repository_head_oid(root: Path) -> str:
    result = run_git(["rev-parse", "--verify", "HEAD"], cwd=root.resolve())
    oid = result.stdout.strip() if result.ok else ""
    if len(oid) not in {40, 64} or any(char not in "0123456789abcdef" for char in oid):
        raise ValueError("OPERATION_ADMISSION_REPOSITORY_OID_UNAVAILABLE")
    return oid


def provider_source_identity_digest(*sources: Path) -> str:
    rows: list[dict[str, str]] = []
    for source in sorted((path.resolve() for path in sources), key=lambda path: path.as_posix()):
        if source.is_symlink() or not source.is_file():
            raise ValueError("OPERATION_ADMISSION_PROVIDER_SOURCE_UNAVAILABLE")
        rows.append({"name": source.name, "source_digest": sha256(source.read_bytes()).hexdigest()})
    if not rows:
        raise ValueError("OPERATION_ADMISSION_PROVIDER_SOURCE_UNAVAILABLE")
    return canonical_digest(
        {"schema_version": 1, "kind": "ProviderSourceIdentityV1", "sources": rows}
    )


@dataclass(frozen=True, slots=True)
class OperationAdmissionV1:
    """准入来源事实；不得混入 target/preimage mutation 事实。"""

    snapshot_digest: str
    release_oid: str
    process_oid: str
    provider_identity_digest: str
    route_profile_digest: str
    work_scope_digest: str
    authorization_identity_digest: str

    @property
    def admission_digest(self) -> str:
        return canonical_digest(self.as_dict())

    def as_dict(self) -> dict[str, str | int]:
        return {
            "schema_version": 1,
            "snapshot_digest": self.snapshot_digest,
            "release_oid": self.release_oid,
            "process_oid": self.process_oid,
            "provider_identity_digest": self.provider_identity_digest,
            "route_profile_digest": self.route_profile_digest,
            "work_scope_digest": self.work_scope_digest,
            "authorization_identity_digest": self.authorization_identity_digest,
        }


@dataclass(frozen=True, slots=True)
class MutationPlanV2:
    """按路径排序、同时绑定 admission/preimage/afterimage 的唯一 mutation 合同。"""

    operation: str
    decision: str
    admission_digest: str
    operation_digest: str
    target_preimages: tuple[tuple[str, str], ...]
    target_afterimages: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        preimage_refs = tuple(ref for ref, _digest in self.target_preimages)
        afterimage_refs = tuple(ref for ref, _digest in self.target_afterimages)
        if preimage_refs != tuple(sorted(preimage_refs)) or len(preimage_refs) != len(
            set(preimage_refs)
        ):
            raise ValueError("MutationPlanV2 target preimages must have unique path ordering")
        if afterimage_refs != preimage_refs:
            raise ValueError("MutationPlanV2 preimage/afterimage target sets must match exactly")

    @property
    def exact_target_refs(self) -> tuple[str, ...]:
        return tuple(ref for ref, _digest in self.target_preimages)

    @property
    def exact_target_set_digest(self) -> str:
        return canonical_digest(list(self.exact_target_refs))

    @property
    def target_preimages_digest(self) -> str:
        return canonical_digest(dict(self.target_preimages))

    @property
    def target_afterimages_digest(self) -> str:
        return canonical_digest(dict(self.target_afterimages))

    @property
    def plan_digest(self) -> str:
        return canonical_digest(self._payload())

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "kind": "MutationPlanV2",
            "operation": self.operation,
            "decision": self.decision,
            "admission_digest": self.admission_digest,
            "operation_digest": self.operation_digest,
            "exact_target_refs": list(self.exact_target_refs),
            "exact_target_set_digest": self.exact_target_set_digest,
            "target_preimages_digest": self.target_preimages_digest,
            "target_afterimages_digest": self.target_afterimages_digest,
            "target_preimages": [
                {"ref": ref, "digest": digest} for ref, digest in self.target_preimages
            ],
            "target_afterimages": [
                {"ref": ref, "digest": digest} for ref, digest in self.target_afterimages
            ],
        }

    def as_dict(self) -> dict[str, Any]:
        return {**self._payload(), "plan_digest": self.plan_digest}


def build_mutation_plan(
    *,
    operation: str,
    decision: str,
    admission_digest: str,
    operation_digest: str,
    target_preimages: tuple[tuple[str, str], ...],
    target_afterimages: tuple[tuple[str, str], ...],
) -> MutationPlanV2:
    return MutationPlanV2(
        operation=operation,
        decision=decision,
        admission_digest=admission_digest,
        operation_digest=operation_digest,
        target_preimages=tuple(sorted(target_preimages)),
        target_afterimages=tuple(sorted(target_afterimages)),
    )


__all__ = [
    "MutationPlanV2",
    "OperationAdmissionV1",
    "build_mutation_plan",
    "provider_source_identity_digest",
    "repository_head_oid",
]
