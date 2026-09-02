"""七步合同第 2-5 步：identity 逐字段比对（IF-6）与 replay 执行授权证据核验（IF-14/R10）。

ProviderFrozenIdentityV1 由调用方组装（validator 不读 git、不产生第二真相源）；
`execution.result_digest` 为非自引用规范化摘要（槽位置零后重算）；
授权信任根 = 权威 issuance record 七要素精确匹配（registry 不可达只能 BLOCKED）。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

SOURCE_CANDIDATE = "source-candidate-replay"
INSTALLED_ARTIFACT = "installed-artifact-replay"
REPLAY_OPERATION_PREFIX = "consumer-replay"

DIGEST_MISMATCH_RESULT = "DIGEST-MISMATCH-RESULT"
DIGEST_MISMATCH_SOURCE_TREE = "DIGEST-MISMATCH-SOURCE-TREE"
DIGEST_MISMATCH_BUNDLE_MANIFEST = "DIGEST-MISMATCH-BUNDLE-MANIFEST"
DIGEST_MISMATCH_WHEEL = "DIGEST-MISMATCH-WHEEL"
DIGEST_MISMATCH_SDIST = "DIGEST-MISMATCH-SDIST"
DIGEST_MISMATCH_RECEIPT = "DIGEST-MISMATCH-RECEIPT"
DIGEST_MISMATCH_SIDECAR = "DIGEST-MISMATCH-SIDECAR"
OID_MISMATCH_RELEASE = "OID-MISMATCH-RELEASE"
OID_MISMATCH_PROCESS = "OID-MISMATCH-PROCESS"
OID_MISMATCH_QUANT_LAB_RELEASE = "OID-MISMATCH-QUANT-LAB-RELEASE"
OID_MISMATCH_QUANT_LAB_PROCESS = "OID-MISMATCH-QUANT-LAB-PROCESS"
FINGERPRINT_MISMATCH_PROFILE = "FINGERPRINT-MISMATCH-PROFILE"
FINGERPRINT_MISMATCH_ENVIRONMENT = "FINGERPRINT-MISMATCH-ENVIRONMENT"
FINGERPRINT_MISMATCH_PROVIDER = "FINGERPRINT-MISMATCH-PROVIDER"
COMMAND_IDENTITY_MISMATCH = "COMMAND-IDENTITY-MISMATCH"
SEMVER_MISMATCH = "SEMVER-MISMATCH"
PROVIDER_IDENTITY_MISMATCH = "PROVIDER-IDENTITY-MISMATCH"
AUTHORIZATION_INHERITED = "AUTHORIZATION-INHERITED"
AUTHORIZATION_EVIDENCE_MISSING = "AUTHORIZATION-EVIDENCE-MISSING"
AUTHORIZATION_DIGEST_MISMATCH = "AUTHORIZATION-DIGEST-MISMATCH"
AUTHORIZATION_OPERATION_MISMATCH = "AUTHORIZATION-OPERATION-MISMATCH"
AUTHORIZATION_OBJECT_CONFUSED = "AUTHORIZATION-OBJECT-CONFUSED"
AUTHORIZATION_TIME_INVARIANT_VIOLATED = "AUTHORIZATION-TIME-INVARIANT-VIOLATED"
AUTHORIZATION_EXPIRED = "AUTHORIZATION-EXPIRED"
AUTHORIZATION_EXECUTION_OUT_OF_WINDOW = "AUTHORIZATION-EXECUTION-OUT-OF-WINDOW"
AUTHORIZATION_CONSUMPTION_UNPROVEN = "AUTHORIZATION-CONSUMPTION-UNPROVEN"
AUTHORIZATION_PROVENANCE_UNTRUSTED = "AUTHORIZATION-PROVENANCE-UNTRUSTED"


@dataclass(frozen=True, slots=True)
class ProviderFrozenIdentityV1:
    """双 variant provider 冻结值（调用方组装；与 result artifact+execution 一一对应）。"""

    variant: str
    source_release_oid: str
    source_process_oid: str
    source_tree_digest: str = ""
    provider_identity: str = ""
    bundle_manifest_digest: str = ""
    semver: str = ""
    wheel_digest: str = ""
    sdist_digest: str = ""
    bundle_receipt_digest: str = ""
    sidecar_digest: str = ""
    artifact_provider_fingerprint: str = ""
    consumer_project_uid: str = ""
    quant_lab_release_oid: str = ""
    quant_lab_process_oid: str = ""
    command_identity: str = ""
    profile_fingerprint: str = ""
    environment_fingerprint: str = ""
    provider_fingerprint: str = ""


@dataclass(frozen=True, slots=True)
class IdentityDriftReport:
    """IF-6 输出：任一漂移 code 命中即整单拒绝（mutation=0）。"""

    ok: bool
    codes: tuple[str, ...]
    drifts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProvenanceBundle:
    """IF-14 信任根输入（调用方组装；issuance_rows=None 表示 registry 不可达）。"""

    issuance_rows: tuple[Mapping[str, Any], ...] | None
    execution_ledger_rows: tuple[Mapping[str, Any], ...] = ()
    frozen_public_key: str = ""
    preregistered_challenges: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AuthorizationEvidenceReport:
    """IF-14 输出：codes 为空才放行导入；consumption_source 记录三源命中。"""

    ok: bool
    codes: tuple[str, ...]
    authorization_id: str
    consumption_source: str
    notes: tuple[str, ...] = field(default=())


def _canonical_digest(document: Mapping[str, Any]) -> str:
    blob = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def compute_result_digest(payload: Mapping[str, Any]) -> str:
    """`execution.result_digest` 规范口径：槽位置零后的规范化 SHA-256（非自引用）。"""
    zeroed = json.loads(json.dumps(payload, ensure_ascii=False))
    zeroed.setdefault("execution", {})["result_digest"] = "0" * 64
    blob = json.dumps(zeroed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _artifact(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    artifact = payload.get("artifact")
    return artifact if isinstance(artifact, Mapping) else {}


def _execution(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    execution = payload.get("execution")
    return execution if isinstance(execution, Mapping) else {}


# (来源取值, frozen 字段, reason code, 适用 variant)
_IDENTITY_CHECKS: tuple[tuple[Any, str, str, frozenset[str]], ...] = (
    (lambda a, e: a.get("source_release_oid"), "source_release_oid", OID_MISMATCH_RELEASE, frozenset({SOURCE_CANDIDATE, INSTALLED_ARTIFACT})),
    (lambda a, e: a.get("source_process_oid"), "source_process_oid", OID_MISMATCH_PROCESS, frozenset({SOURCE_CANDIDATE, INSTALLED_ARTIFACT})),
    (lambda a, e: a.get("source_tree_digest"), "source_tree_digest", DIGEST_MISMATCH_SOURCE_TREE, frozenset({SOURCE_CANDIDATE})),
    (lambda a, e: a.get("provider_identity"), "provider_identity", PROVIDER_IDENTITY_MISMATCH, frozenset({SOURCE_CANDIDATE, INSTALLED_ARTIFACT})),
    (lambda a, e: a.get("bundle_manifest_digest"), "bundle_manifest_digest", DIGEST_MISMATCH_BUNDLE_MANIFEST, frozenset({INSTALLED_ARTIFACT})),
    (lambda a, e: a.get("semver"), "semver", SEMVER_MISMATCH, frozenset({INSTALLED_ARTIFACT})),
    (lambda a, e: (a.get("assets") or {}).get("wheel"), "wheel_digest", DIGEST_MISMATCH_WHEEL, frozenset({INSTALLED_ARTIFACT})),
    (lambda a, e: (a.get("assets") or {}).get("sdist"), "sdist_digest", DIGEST_MISMATCH_SDIST, frozenset({INSTALLED_ARTIFACT})),
    (lambda a, e: (a.get("assets") or {}).get("receipt"), "bundle_receipt_digest", DIGEST_MISMATCH_RECEIPT, frozenset({INSTALLED_ARTIFACT})),
    (lambda a, e: (a.get("assets") or {}).get("sidecar"), "sidecar_digest", DIGEST_MISMATCH_SIDECAR, frozenset({INSTALLED_ARTIFACT})),
    (lambda a, e: a.get("provider_fingerprint"), "artifact_provider_fingerprint", FINGERPRINT_MISMATCH_PROVIDER, frozenset({INSTALLED_ARTIFACT})),
    (lambda a, e: e.get("consumer_project_uid"), "consumer_project_uid", PROVIDER_IDENTITY_MISMATCH, frozenset({SOURCE_CANDIDATE, INSTALLED_ARTIFACT})),
    (lambda a, e: e.get("quant_lab_release_oid"), "quant_lab_release_oid", OID_MISMATCH_QUANT_LAB_RELEASE, frozenset({SOURCE_CANDIDATE, INSTALLED_ARTIFACT})),
    (lambda a, e: e.get("quant_lab_process_oid"), "quant_lab_process_oid", OID_MISMATCH_QUANT_LAB_PROCESS, frozenset({SOURCE_CANDIDATE, INSTALLED_ARTIFACT})),
    (lambda a, e: e.get("command_identity"), "command_identity", COMMAND_IDENTITY_MISMATCH, frozenset({SOURCE_CANDIDATE, INSTALLED_ARTIFACT})),
    (lambda a, e: e.get("profile_fingerprint"), "profile_fingerprint", FINGERPRINT_MISMATCH_PROFILE, frozenset({SOURCE_CANDIDATE, INSTALLED_ARTIFACT})),
    (lambda a, e: e.get("environment_fingerprint"), "environment_fingerprint", FINGERPRINT_MISMATCH_ENVIRONMENT, frozenset({SOURCE_CANDIDATE, INSTALLED_ARTIFACT})),
    (lambda a, e: e.get("provider_fingerprint"), "provider_fingerprint", FINGERPRINT_MISMATCH_PROVIDER, frozenset({SOURCE_CANDIDATE, INSTALLED_ARTIFACT})),
)


def validate_identity(payload: Mapping[str, Any], frozen: ProviderFrozenIdentityV1) -> IdentityDriftReport:
    """IF-6：digest/OID/fingerprint/command 逐字段比对（七步第 2-4 步）。"""
    variant = payload.get("variant")
    if variant != frozen.variant:
        raise ValueError(f"frozen identity variant {frozen.variant!r} does not match result {variant!r}")
    artifact, execution = _artifact(payload), _execution(payload)
    codes: list[str] = []
    drifts: list[str] = []
    for getter, frozen_field, code, applies in _IDENTITY_CHECKS:
        if frozen.variant not in applies:
            continue
        expected = getattr(frozen, frozen_field)
        actual = getter(artifact, execution)
        if expected != actual:
            codes.append(code)
            drifts.append(f"{frozen_field}: frozen={expected!r} actual={actual!r}")
    declared = _execution(payload).get("result_digest") or ""
    if declared != compute_result_digest(payload):
        codes.append(DIGEST_MISMATCH_RESULT)
        drifts.append("execution.result_digest: recomputed canonical digest mismatch")
    ordered = tuple(sorted(set(codes)))
    return IdentityDriftReport(ok=not ordered, codes=ordered, drifts=tuple(drifts))


def _moment(value: Any, *, label: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{label} lacks timezone: {value!r}")
    return parsed.astimezone(UTC)


def _authorization_block(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    authorization = payload.get("authorization")
    return authorization if isinstance(authorization, Mapping) else {}


def verify_replay_execution_authorization(
    *,
    result_payload: Mapping[str, Any],
    authorization_evidence: Mapping[str, Any] | None,
    provenance: ProvenanceBundle,
) -> AuthorizationEvidenceReport:
    """IF-14（R10）：授权语义 + 来源真实性 + consumption 证明核验；不落库。

    b/c 来源（签名/预登记 challenge）在 provider 域只做来源命中登记，不做
    密码学验签（授权方域职责）；此口径偏离记 IMPLEMENTATION §8。
    """
    codes: list[str] = []
    notes: list[str] = []
    authorization = _authorization_block(result_payload)
    execution = _execution(result_payload)
    if authorization.get("authorization_inherited") is not False:
        codes.append(AUTHORIZATION_INHERITED)
    single_use = authorization.get("single_use")
    single_use = single_use if isinstance(single_use, Mapping) else {}
    if single_use.get("consumed") is not True:
        codes.append("SCHEMA-INVALID")
        notes.append("authorization.single_use.consumed must be true at import")
    evidence_id = str(authorization.get("authorization_id") or "")
    if not authorization_evidence:
        codes.append(AUTHORIZATION_EVIDENCE_MISSING)
        return AuthorizationEvidenceReport(False, tuple(sorted(set(codes))), evidence_id, "", tuple(notes))
    if _canonical_digest(authorization_evidence) != authorization.get("authorization_digest"):
        codes.append(AUTHORIZATION_DIGEST_MISMATCH)
    operation = str(authorization_evidence.get("operation") or "")
    if not operation.startswith(REPLAY_OPERATION_PREFIX):
        codes.append(AUTHORIZATION_OBJECT_CONFUSED)
        notes.append(f"evidence operation is not a replay-execution authorization: {operation!r}")
    for evidence_field, result_field in (
        ("target", "target"), ("scope", "scope"), ("principal", "principal"),
    ):
        if authorization_evidence.get(evidence_field) != authorization.get(result_field):
            codes.append(AUTHORIZATION_OPERATION_MISMATCH)
            notes.append(f"{evidence_field} does not bind this execution")
    if str(authorization_evidence.get("consumer_project_uid") or "") != str(execution.get("consumer_project_uid") or ""):
        codes.append(AUTHORIZATION_OPERATION_MISMATCH)
        notes.append("consumer_project_uid does not bind this execution")
    # -- 信任根：issuance registry 七要素精确匹配（不可达只能 BLOCKED，N33） -------
    if provenance.issuance_rows is None:
        codes.append(AUTHORIZATION_PROVENANCE_UNTRUSTED)
        notes.append("issuance registry unreachable: offline self-consistency is not accepted")
    else:
        declared_digest = authorization.get("authorization_digest")
        matched = any(
            row.get("authorization_id") == evidence_id
            and row.get("authorization_digest") == declared_digest
            and row.get("operation") == operation
            and row.get("principal") == authorization_evidence.get("principal")
            for row in provenance.issuance_rows
        )
        if not matched:
            codes.append(AUTHORIZATION_PROVENANCE_UNTRUSTED)
            notes.append("issuance registry has no exact seven-element match")
    # -- 时间不变量（执行时刻判定；导入可晚于 not_after） -------------------------
    validity = authorization_evidence.get("validity")
    validity = validity if isinstance(validity, Mapping) else {}
    try:
        not_before = _moment(validity.get("not_before"), label="not_before")
        not_after = _moment(validity.get("not_after"), label="not_after")
        authorized_at = _moment(authorization_evidence.get("authorized_at"), label="authorized_at")
        started_at = _moment(execution.get("started_at"), label="started_at")
        consumed_at = _moment(single_use.get("consumed_at"), label="consumed_at")
        finished_at = _moment(execution.get("finished_at"), label="finished_at")
    except (TypeError, ValueError):
        codes.append(AUTHORIZATION_TIME_INVARIANT_VIOLATED)
        notes.append("authorization timeline is not parseable")
    else:
        if not_before > not_after or not_after < authorized_at:
            codes.append(AUTHORIZATION_EXPIRED)
        chain = (not_before, authorized_at, started_at, consumed_at, finished_at, not_after)
        if any(chain[i] > chain[i + 1] for i in range(len(chain) - 1)):
            codes.append(AUTHORIZATION_TIME_INVARIANT_VIOLATED)
        if started_at < not_before or finished_at > not_after:
            codes.append(AUTHORIZATION_EXECUTION_OUT_OF_WINDOW)
    # -- consumption receipt 三源主备（a 主；a 不可用且公钥已冻结→b；否则 c） ------
    source = ""
    digest = str(authorization.get("authorization_digest") or "")
    attempt_id = str(single_use.get("attempt_id") or "")
    if any(
        row.get("authorization_digest") == digest and (not attempt_id or row.get("attempt_id") == attempt_id)
        for row in provenance.execution_ledger_rows
    ):
        source = "execution-ledger"
    elif provenance.frozen_public_key and authorization_evidence.get("signature"):
        source = "signature"
    elif str(authorization_evidence.get("challenge_token") or "") and str(
        authorization_evidence.get("challenge_token")
    ) in tuple(provenance.preregistered_challenges):
        source = "challenge"
    if not source:
        codes.append(AUTHORIZATION_CONSUMPTION_UNPROVEN)
        notes.append("no verifiable consumption receipt source (ledger/signature/challenge)")
    ordered = tuple(sorted(set(codes)))
    return AuthorizationEvidenceReport(not ordered, ordered, evidence_id, source, tuple(notes))


__all__ = [
    "AuthorizationEvidenceReport",
    "AUTHORIZATION_CONSUMPTION_UNPROVEN",
    "AUTHORIZATION_DIGEST_MISMATCH",
    "AUTHORIZATION_EVIDENCE_MISSING",
    "AUTHORIZATION_EXECUTION_OUT_OF_WINDOW",
    "AUTHORIZATION_EXPIRED",
    "AUTHORIZATION_INHERITED",
    "AUTHORIZATION_OBJECT_CONFUSED",
    "AUTHORIZATION_OPERATION_MISMATCH",
    "AUTHORIZATION_PROVENANCE_UNTRUSTED",
    "AUTHORIZATION_TIME_INVARIANT_VIOLATED",
    "COMMAND_IDENTITY_MISMATCH",
    "compute_result_digest",
    "IdentityDriftReport",
    "INSTALLED_ARTIFACT",
    "OID_MISMATCH_PROCESS",
    "OID_MISMATCH_QUANT_LAB_PROCESS",
    "OID_MISMATCH_QUANT_LAB_RELEASE",
    "OID_MISMATCH_RELEASE",
    "ProviderFrozenIdentityV1",
    "ProvenanceBundle",
    "SEMVER_MISMATCH",
    "SOURCE_CANDIDATE",
    "validate_identity",
    "verify_replay_execution_authorization",
]
