"""为历史 CR 生成不伪造旧 PASS 的 append-only 审计绑定。"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any

from meta_flow.project.onboarding_contract import canonical_digest
from meta_flow.project.process_route import _resolve_runtime_ref

HISTORICAL_FACT_STATUSES = frozenset(
    {"proven", "contradicted", "audited-known-historical-fact"}
)


class HistoricalReframeError(ValueError):
    """历史对账契约无法安全执行。"""


@dataclass(frozen=True)
class HistoricalClaimV1:
    """一个需要与原始 bytes 绑定的历史声明。"""

    claim_id: str
    source_ref: str
    claim: str
    expected_source_digest: str = ""

    def __post_init__(self) -> None:
        if not self.claim_id or not self.claim_id.replace("-", "").replace("_", "").isalnum():
            raise HistoricalReframeError("claim_id must be a non-empty safe identifier")
        _validate_logical_ref(self.source_ref)
        if not self.claim.strip():
            raise HistoricalReframeError("claim must be non-empty")
        if self.expected_source_digest and not _is_digest(self.expected_source_digest):
            raise HistoricalReframeError("expected_source_digest must be one lowercase SHA-256")


@dataclass(frozen=True)
class HistoricalProviderIdentityV1:
    """生成审计绑定的最小、可重放 provider identity。"""

    package: str
    version: str
    source_kind: str
    release_oid: str
    process_oid: str
    route_digest: str

    def __post_init__(self) -> None:
        if not self.package or not self.version:
            raise HistoricalReframeError("provider package/version are required")
        if self.source_kind not in {"candidate-source", "installed-artifact"}:
            raise HistoricalReframeError("unsupported provider source_kind")
        if not _is_oid(self.release_oid) or not _is_oid(self.process_oid):
            raise HistoricalReframeError("provider release/process OIDs must be lowercase 40-hex")
        if not _is_digest(self.route_digest):
            raise HistoricalReframeError("provider route_digest must be one lowercase SHA-256")

    def as_dict(self) -> dict[str, str]:
        return {
            "package": self.package,
            "version": self.version,
            "source_kind": self.source_kind,
            "release_oid": self.release_oid,
            "process_oid": self.process_oid,
            "route_digest": self.route_digest,
        }


@dataclass(frozen=True)
class HistoricalEvidenceFactV1:
    claim_id: str
    claim: str
    status: str
    source_ref: str
    source_digest: str
    expected_source_digest: str
    reason: str

    def __post_init__(self) -> None:
        if self.status not in HISTORICAL_FACT_STATUSES:
            raise HistoricalReframeError("unsupported historical fact status")
        if self.source_digest and not _is_digest(self.source_digest):
            raise HistoricalReframeError("source_digest must be empty or lowercase SHA-256")

    def as_dict(self) -> dict[str, str]:
        return {
            "claim_id": self.claim_id,
            "claim": self.claim,
            "status": self.status,
            "source_ref": self.source_ref,
            "source_digest": self.source_digest,
            "expected_source_digest": self.expected_source_digest,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class HistoricalReframePlanV1:
    cr_id: str
    target_ref: str
    provider_identity: HistoricalProviderIdentityV1
    authorization_ref: str
    source_preimages: tuple[tuple[str, str], ...]
    target_preimage: str
    record: Mapping[str, Any] | None
    decision: str
    blockers: tuple[str, ...]
    mutation_count: int
    schema_version: int = 1
    kind: str = "HistoricalReframePlanV1"

    @property
    def plan_digest(self) -> str:
        return canonical_digest(
            {
                "schema_version": self.schema_version,
                "kind": self.kind,
                "cr_id": self.cr_id,
                "target_ref": self.target_ref,
                "provider_identity": self.provider_identity.as_dict(),
                "authorization_ref": self.authorization_ref,
                "source_preimages": list(self.source_preimages),
                "target_preimage": self.target_preimage,
                "record": dict(self.record) if self.record is not None else None,
                "decision": self.decision,
                "blockers": list(self.blockers),
                "mutation_count": self.mutation_count,
            }
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "cr_id": self.cr_id,
            "target_ref": self.target_ref,
            "provider_identity": self.provider_identity.as_dict(),
            "authorization_ref": self.authorization_ref,
            "source_preimages": [list(item) for item in self.source_preimages],
            "target_preimage": self.target_preimage,
            "record": dict(self.record) if self.record is not None else None,
            "decision": self.decision,
            "blockers": list(self.blockers),
            "mutation_count": self.mutation_count,
            "plan_digest": self.plan_digest,
        }


def _is_digest(value: object) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _is_oid(value: object) -> bool:
    text = str(value or "")
    return len(text) == 40 and all(character in "0123456789abcdef" for character in text)


def _validate_logical_ref(ref: str) -> None:
    if not isinstance(ref, str) or not ref or "\\" in ref or ref.startswith("/"):
        raise HistoricalReframeError("source_ref must be a repository logical ref")
    parts = PurePosixPath(ref).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise HistoricalReframeError("source_ref contains an unsafe segment")


def _resolve_declared_ref(project_root: Path, ref: str) -> Path:
    _validate_logical_ref(ref)
    if ref.startswith("process/"):
        # 先让 canonical route provider 完成边界校验，再保留未解引用的 leaf，
        # 否则 ``Path.resolve`` 会吞掉 symlink 身份，安全检查将看不到真实输入。
        resolved = _resolve_runtime_ref(project_root.resolve(), ref)
        process_root = _resolve_runtime_ref(
            project_root.resolve(), "process/.meta-flow-process.yaml"
        ).parent
        raw = process_root.joinpath(*PurePosixPath(ref).parts[1:])
        if raw.resolve(strict=False) != resolved:
            raise HistoricalReframeError("logical ref and canonical route disagree")
        return raw
    root = project_root.resolve()
    raw = root.joinpath(*PurePosixPath(ref).parts)
    if not raw.resolve(strict=False).is_relative_to(root):
        raise HistoricalReframeError("release logical ref escapes its repository")
    return raw


def _read_regular_file(path: Path) -> tuple[bytes | None, str]:
    if path.is_symlink():
        return None, "SOURCE_SYMLINK_FORBIDDEN"
    if not path.exists():
        return None, "SOURCE_MISSING"
    if not path.is_file():
        return None, "SOURCE_NOT_REGULAR_FILE"
    return path.read_bytes(), ""


def classify_historical_fact(
    claim: HistoricalClaimV1,
    *,
    observed_bytes: bytes | None,
    observation_error: str = "",
) -> HistoricalEvidenceFactV1:
    """只按原始 bytes 的可证明性分类；未知事实永远不会变成 PASS。"""

    if observation_error or observed_bytes is None:
        return HistoricalEvidenceFactV1(
            claim_id=claim.claim_id,
            claim=claim.claim,
            status="audited-known-historical-fact",
            source_ref=claim.source_ref,
            source_digest="",
            expected_source_digest=claim.expected_source_digest,
            reason=observation_error or "SOURCE_EVIDENCE_UNAVAILABLE",
        )
    observed_digest = sha256(observed_bytes).hexdigest()
    if not claim.expected_source_digest:
        status = "audited-known-historical-fact"
        reason = "EXPECTED_SOURCE_DIGEST_NOT_AVAILABLE"
    elif observed_digest == claim.expected_source_digest:
        status = "proven"
        reason = "SOURCE_BYTES_MATCH_EXPECTED_DIGEST"
    else:
        status = "contradicted"
        reason = "SOURCE_BYTES_CONTRADICT_EXPECTED_DIGEST"
    return HistoricalEvidenceFactV1(
        claim_id=claim.claim_id,
        claim=claim.claim,
        status=status,
        source_ref=claim.source_ref,
        source_digest=observed_digest,
        expected_source_digest=claim.expected_source_digest,
        reason=reason,
    )


def _build_record(
    *,
    cr_id: str,
    target_ref: str,
    provider_identity: HistoricalProviderIdentityV1,
    authorization_ref: str,
    facts: Sequence[HistoricalEvidenceFactV1],
) -> dict[str, Any]:
    unsigned: dict[str, Any] = {
        "schema_version": 1,
        "kind": "HistoricalReframeRecordV1",
        "cr_id": cr_id,
        "target_ref": target_ref,
        "provider_identity": provider_identity.as_dict(),
        "authorization_ref": authorization_ref,
        "facts": [fact.as_dict() for fact in facts],
        "zero_fabrication": True,
        "original_bytes_mutated": False,
    }
    return {**unsigned, "record_digest": canonical_digest(unsigned)}


def plan_historical_reframe(
    project_root: Path,
    *,
    cr_id: str,
    claims: Sequence[HistoricalClaimV1],
    provider_identity: HistoricalProviderIdentityV1,
    authorization_ref: str,
    target_ref: str | None = None,
) -> HistoricalReframePlanV1:
    """构造零写计划；只读取显式声明的 refs。"""

    blockers: list[str] = []
    if not cr_id or not cr_id.startswith("CR-"):
        blockers.append("CR_ID_INVALID")
    if not claims or len({claim.claim_id for claim in claims}) != len(claims):
        blockers.append("CLAIMS_MUST_BE_NONEMPTY_UNIQUE")
    if not authorization_ref.startswith("process/") or "#" not in authorization_ref:
        blockers.append("TYPED_AUTHORIZATION_REF_REQUIRED")
    resolved_target_ref = target_ref or f"process/archive/{cr_id}/{cr_id}-HISTORICAL-REFRAME.json"
    try:
        _validate_logical_ref(resolved_target_ref)
    except HistoricalReframeError:
        blockers.append("TARGET_REF_INVALID")

    facts: list[HistoricalEvidenceFactV1] = []
    source_preimages: list[tuple[str, str]] = []
    for claim in sorted(claims, key=lambda item: item.claim_id):
        try:
            source_path = _resolve_declared_ref(project_root, claim.source_ref)
            observed, error = _read_regular_file(source_path)
        except Exception:
            observed, error = None, "SOURCE_ROUTE_INVALID"
        if error in {"SOURCE_SYMLINK_FORBIDDEN", "SOURCE_NOT_REGULAR_FILE", "SOURCE_ROUTE_INVALID"}:
            blockers.append(f"{error}:{claim.source_ref}")
        fact = classify_historical_fact(
            claim,
            observed_bytes=observed,
            observation_error=error,
        )
        facts.append(fact)
        source_preimages.append((claim.source_ref, fact.source_digest))

    record = _build_record(
        cr_id=cr_id,
        target_ref=resolved_target_ref,
        provider_identity=provider_identity,
        authorization_ref=authorization_ref,
        facts=facts,
    )
    try:
        target_path = _resolve_declared_ref(project_root, resolved_target_ref)
        target_bytes, target_error = _read_regular_file(target_path)
    except Exception:
        target_bytes, target_error = None, "TARGET_ROUTE_INVALID"
    if target_error in {"SOURCE_SYMLINK_FORBIDDEN", "SOURCE_NOT_REGULAR_FILE", "TARGET_ROUTE_INVALID"}:
        blockers.append(target_error.replace("SOURCE_", "TARGET_"))
    expected_bytes = (json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    target_preimage = sha256(target_bytes or b"").hexdigest()
    if target_bytes is not None and target_bytes != expected_bytes:
        blockers.append("TARGET_CONFLICT")

    if blockers:
        decision, mutation_count, planned_record = "BLOCKED", 0, None
    elif target_bytes == expected_bytes:
        decision, mutation_count, planned_record = "NO_CHANGE", 0, record
    else:
        decision, mutation_count, planned_record = "READY", 1, record
    return HistoricalReframePlanV1(
        cr_id=cr_id,
        target_ref=resolved_target_ref,
        provider_identity=provider_identity,
        authorization_ref=authorization_ref,
        source_preimages=tuple(source_preimages),
        target_preimage=target_preimage,
        record=planned_record,
        decision=decision,
        blockers=tuple(sorted(set(blockers))),
        mutation_count=mutation_count,
    )


def _create_only_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def apply_historical_reframe(
    project_root: Path,
    *,
    plan: HistoricalReframePlanV1,
    expected_plan_digest: str,
    current_provider_identity: HistoricalProviderIdentityV1,
    current_authorization_ref: str,
) -> dict[str, Any]:
    """在 fresh source/target/provider/auth 全匹配时 create-only apply。"""

    if expected_plan_digest != plan.plan_digest:
        return {"decision": "BLOCKED", "blockers": ["PLAN_DIGEST_MISMATCH"], "mutation_count": 0}
    if plan.decision == "NO_CHANGE":
        return {"decision": "NO_CHANGE", "blockers": [], "mutation_count": 0}
    if plan.decision != "READY" or plan.record is None:
        return {"decision": "BLOCKED", "blockers": list(plan.blockers), "mutation_count": 0}
    if current_provider_identity != plan.provider_identity:
        return {"decision": "BLOCKED", "blockers": ["PROVIDER_IDENTITY_DRIFT"], "mutation_count": 0}
    if current_authorization_ref != plan.authorization_ref:
        return {"decision": "BLOCKED", "blockers": ["AUTHORIZATION_DRIFT"], "mutation_count": 0}

    for ref, expected_digest in plan.source_preimages:
        try:
            source = _resolve_declared_ref(project_root, ref)
            observed, error = _read_regular_file(source)
        except Exception:
            observed, error = None, "SOURCE_ROUTE_INVALID"
        current_digest = sha256(observed).hexdigest() if observed is not None else ""
        if error not in {"", "SOURCE_MISSING"} or current_digest != expected_digest:
            return {"decision": "BLOCKED", "blockers": ["SOURCE_PREIMAGE_DRIFT"], "mutation_count": 0}

    target = _resolve_declared_ref(project_root, plan.target_ref)
    target_bytes, target_error = _read_regular_file(target)
    current_preimage = sha256(target_bytes or b"").hexdigest()
    if target_error not in {"", "SOURCE_MISSING"} or current_preimage != plan.target_preimage:
        return {"decision": "BLOCKED", "blockers": ["TARGET_PREIMAGE_DRIFT"], "mutation_count": 0}
    payload = (json.dumps(dict(plan.record), ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    if target_bytes == payload:
        return {"decision": "NO_CHANGE", "blockers": [], "mutation_count": 0}
    try:
        _create_only_atomic(target, payload)
    except FileExistsError:
        return {"decision": "BLOCKED", "blockers": ["TARGET_CREATE_CONFLICT"], "mutation_count": 0}
    return {
        "schema_version": 1,
        "kind": "HistoricalReframeReceiptV1",
        "decision": "APPLIED",
        "target_ref": plan.target_ref,
        "record_digest": str(plan.record.get("record_digest") or ""),
        "plan_digest": plan.plan_digest,
        "mutation_count": 1,
    }


__all__ = [
    "HISTORICAL_FACT_STATUSES",
    "HistoricalClaimV1",
    "HistoricalEvidenceFactV1",
    "HistoricalProviderIdentityV1",
    "HistoricalReframeError",
    "HistoricalReframePlanV1",
    "apply_historical_reframe",
    "classify_historical_fact",
    "plan_historical_reframe",
]
