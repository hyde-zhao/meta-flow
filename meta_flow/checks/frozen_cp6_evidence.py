"""冻结的 CP6 证据与依赖摘要准入投影。"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from meta_flow.project.onboarding_contract import canonical_digest

FROZEN_CP6_EVIDENCE_SCHEMA_VERSION = 1
_OID_RE = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_PROJECTED_GATE_FIELDS = {"story_id", "status", "dev_gate"}
_DEV_GATE_FIELDS = {
    "cp5_confirmed",
    "dependencies_satisfied",
    "file_conflict_free",
    "implementation_authorized",
    "lld_confirmed",
}


class FrozenCp6EvidenceError(ValueError):
    """冻结证据不满足 V1 契约时阻断准入。"""


@dataclass(frozen=True)
class FrozenCp6EvidenceV1:
    """不可变的 CP6 证据快照；所有摘要均为原生 canonical digest。"""

    story_id: str
    release_oid: str
    process_oid: str
    scope_digest: str
    implementation_digest: str
    dependency_digests: dict[str, str]
    cp6_result_ref: str
    schema_version: int = FROZEN_CP6_EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != FROZEN_CP6_EVIDENCE_SCHEMA_VERSION:
            raise FrozenCp6EvidenceError("unknown FrozenCp6Evidence schema_version")
        if not self.story_id:
            raise FrozenCp6EvidenceError("story_id is required")
        if not _OID_RE.fullmatch(self.release_oid) or not _OID_RE.fullmatch(self.process_oid):
            raise FrozenCp6EvidenceError("release_oid and process_oid must be lowercase 40-hex OIDs")
        for name, value in {
            "scope_digest": self.scope_digest,
            "implementation_digest": self.implementation_digest,
            **self.dependency_digests,
        }.items():
            if not _DIGEST_RE.fullmatch(value):
                raise FrozenCp6EvidenceError(f"{name} must be a lowercase sha256 digest")
        if not self.cp6_result_ref.startswith("process/checks/"):
            raise FrozenCp6EvidenceError("cp6_result_ref must be a process/checks logical ref")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "story_id": self.story_id,
            "release_oid": self.release_oid,
            "process_oid": self.process_oid,
            "scope_digest": self.scope_digest,
            "implementation_digest": self.implementation_digest,
            "dependency_digests": dict(sorted(self.dependency_digests.items())),
            "cp6_result_ref": self.cp6_result_ref,
        }

    @property
    def evidence_digest(self) -> str:
        return canonical_digest(self.as_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> FrozenCp6EvidenceV1:
        required = {
            "schema_version", "story_id", "release_oid", "process_oid", "scope_digest",
            "implementation_digest", "dependency_digests", "cp6_result_ref",
        }
        if set(payload) != required:
            raise FrozenCp6EvidenceError("FrozenCp6EvidenceV1 fields mismatch")
        dependencies = payload["dependency_digests"]
        if not isinstance(dependencies, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in dependencies.items()
        ):
            raise FrozenCp6EvidenceError("dependency_digests must be a string mapping")
        return cls(
            story_id=str(payload["story_id"]),
            release_oid=str(payload["release_oid"]),
            process_oid=str(payload["process_oid"]),
            scope_digest=str(payload["scope_digest"]),
            implementation_digest=str(payload["implementation_digest"]),
            dependency_digests=dict(sorted(dependencies.items())),
            cp6_result_ref=str(payload["cp6_result_ref"]),
            schema_version=payload["schema_version"],
        )


def freeze_cp6_evidence(**payload: Any) -> FrozenCp6EvidenceV1:
    """校验并冻结 V1 证据；未知 schema 或字段一律 fail-closed。"""

    return FrozenCp6EvidenceV1.from_dict(payload)


def compare_frozen_evidence(
    previous: FrozenCp6EvidenceV1 | Mapping[str, Any],
    current: FrozenCp6EvidenceV1 | Mapping[str, Any],
) -> dict[str, Any]:
    """比较依赖摘要：未变只 reconfirm，变化则要求下游重验。"""

    old = previous if isinstance(previous, FrozenCp6EvidenceV1) else FrozenCp6EvidenceV1.from_dict(previous)
    new = current if isinstance(current, FrozenCp6EvidenceV1) else FrozenCp6EvidenceV1.from_dict(current)
    if old.story_id != new.story_id:
        raise FrozenCp6EvidenceError("cannot compare evidence for different stories")
    changed = sorted(
        key for key in set(old.dependency_digests) | set(new.dependency_digests)
        if old.dependency_digests.get(key) != new.dependency_digests.get(key)
    )
    return {
        "decision": "revalidation-required" if changed else "reconfirmed",
        "reason_codes": ["DEPENDENCY_DIGEST_CHANGED"] if changed else ["DEPENDENCY_DIGEST_RECONFIRMED"],
        "changed_dependencies": changed,
        "evidence_digest": new.evidence_digest,
    }


def project_story_admission(
    evidence: FrozenCp6EvidenceV1 | Mapping[str, Any] | None,
    *,
    expected_dependency_digests: Mapping[str, str],
    bootstrap: Mapping[str, Any] | None = None,
    projected_gate: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """唯一 READY 入口；bootstrap 仅保留 provenance，绝不短路准入。"""

    del bootstrap  # 明确禁止 virtual bootstrap 对 decision 施加影响。
    if evidence is None:
        if projected_gate is not None:
            if set(projected_gate) != _PROJECTED_GATE_FIELDS:
                return {
                    "decision": "BLOCKED",
                    "reason_codes": ["NATIVE_PLAN_GATE_INVALID"],
                    "dependency_state": "invalid",
                }
            dev_gate = projected_gate.get("dev_gate")
            if not isinstance(dev_gate, Mapping) or set(dev_gate) != _DEV_GATE_FIELDS:
                return {
                    "decision": "BLOCKED",
                    "reason_codes": ["NATIVE_PLAN_GATE_INVALID"],
                    "dependency_state": "invalid",
                }
            if (
                str(projected_gate.get("story_id") or "")
                and str(projected_gate.get("status") or "") == "dev-ready"
                and all(dev_gate.get(field) is True for field in sorted(_DEV_GATE_FIELDS))
            ):
                return {
                    "decision": "READY",
                    "reason_codes": ["NATIVE_DEVELOPMENT_PLAN_GATE_READY"],
                    "dependency_state": "projected",
                }
            return {
                "decision": "BLOCKED",
                "reason_codes": ["NATIVE_DEVELOPMENT_PLAN_GATE_NOT_READY"],
                "dependency_state": "blocked",
            }
        return {"decision": "BLOCKED", "reason_codes": ["FROZEN_CP6_EVIDENCE_MISSING"], "dependency_state": "missing"}
    try:
        frozen = evidence if isinstance(evidence, FrozenCp6EvidenceV1) else FrozenCp6EvidenceV1.from_dict(evidence)
    except FrozenCp6EvidenceError as exc:
        return {"decision": "BLOCKED", "reason_codes": ["FROZEN_CP6_EVIDENCE_INVALID"], "detail": str(exc), "dependency_state": "invalid"}
    if dict(sorted(expected_dependency_digests.items())) != frozen.dependency_digests:
        return {
            "decision": "revalidation-required",
            "reason_codes": ["DEPENDENCY_DIGEST_CHANGED"],
            "dependency_state": "changed",
            "evidence_digest": frozen.evidence_digest,
        }
    return {
        "decision": "READY",
        "reason_codes": ["FROZEN_CP6_EVIDENCE_VALID", "DEPENDENCY_DIGEST_RECONFIRMED"],
        "dependency_state": "reconfirmed",
        "evidence_digest": frozen.evidence_digest,
    }


def project_story_admissions(
    evidence_by_story: Mapping[str, FrozenCp6EvidenceV1 | Mapping[str, Any] | None],
    *,
    expected_dependency_digests_by_story: Mapping[str, Mapping[str, str]],
    projected_gates_by_story: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """按稳定 Story ID 顺序批量投影，且每项只调用唯一 admission projector。"""

    story_ids = sorted(set(evidence_by_story) | set(expected_dependency_digests_by_story))
    return {
        story_id: project_story_admission(
            evidence_by_story.get(story_id),
            expected_dependency_digests=expected_dependency_digests_by_story.get(story_id, {}),
            projected_gate=(projected_gates_by_story or {}).get(story_id),
        )
        for story_id in story_ids
    }
