"""冻结的 CP6 证据与依赖摘要准入投影。"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from meta_flow.project.onboarding_contract import canonical_digest

FROZEN_CP6_EVIDENCE_SCHEMA_VERSION = 1
CP6_REVALIDATION_SCHEMA_VERSION = 1
_OID_RE = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTITY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_PROJECTED_GATE_FIELDS = {"story_id", "status", "dev_gate"}
_DEV_GATE_FIELDS = {
    "cp5_confirmed",
    "dependencies_satisfied",
    "file_conflict_free",
    "implementation_authorized",
    "lld_confirmed",
}
_REVALIDATION_AUTHORIZATION_FIELDS = frozenset(
    {
        "schema_version", "cr_id", "story_id", "work_id", "attempt_id",
        "release_oid", "process_oid", "scope_digest", "previous_cp6_ref",
        "previous_cp6_digest", "superseding_cp5_ref", "superseding_cp5_digest",
        "plan_preimage_digest", "allowed_write_paths",
    }
)


class FrozenCp6EvidenceError(ValueError):
    """冻结证据不满足 V1 契约时阻断准入。"""


@dataclass(frozen=True)
class Cp6RevalidationAuthorizationV1:
    """P01 的显式 A2 authorization：闭集、可摘要且只适用于一个 attempt。"""

    cr_id: str
    story_id: str
    work_id: str
    attempt_id: str
    release_oid: str
    process_oid: str
    scope_digest: str
    previous_cp6_ref: str
    previous_cp6_digest: str
    superseding_cp5_ref: str
    superseding_cp5_digest: str
    plan_preimage_digest: str
    allowed_write_paths: list[str]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise FrozenCp6EvidenceError("unknown CP6 revalidation authorization schema_version")
        if not all(isinstance(value, str) and _IDENTITY_RE.fullmatch(value) for value in (self.cr_id, self.story_id, self.work_id, self.attempt_id)):
            raise FrozenCp6EvidenceError("revalidation authorization identity fields are required")
        _require_oid(self.release_oid, "release_oid")
        _require_oid(self.process_oid, "process_oid")
        for field in ("scope_digest", "previous_cp6_digest", "superseding_cp5_digest", "plan_preimage_digest"):
            _require_digest(getattr(self, field), field)
        _require_logical_ref(self.previous_cp6_ref, "previous_cp6_ref")
        _require_logical_ref(self.superseding_cp5_ref, "superseding_cp5_ref")
        if not isinstance(self.allowed_write_paths, list) or not self.allowed_write_paths:
            raise FrozenCp6EvidenceError("allowed_write_paths must be a non-empty list")
        if not all(
            _safe_process_work_pattern(
                item,
                work_id=self.work_id,
                attempt_id=self.attempt_id,
            )
            for item in self.allowed_write_paths
        ):
            raise FrozenCp6EvidenceError("allowed_write_paths must contain safe process work refs")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version, "cr_id": self.cr_id, "story_id": self.story_id,
            "work_id": self.work_id, "attempt_id": self.attempt_id, "release_oid": self.release_oid,
            "process_oid": self.process_oid, "scope_digest": self.scope_digest,
            "previous_cp6_ref": self.previous_cp6_ref, "previous_cp6_digest": self.previous_cp6_digest,
            "superseding_cp5_ref": self.superseding_cp5_ref, "superseding_cp5_digest": self.superseding_cp5_digest,
            "plan_preimage_digest": self.plan_preimage_digest,
            "allowed_write_paths": list(self.allowed_write_paths),
        }

    @property
    def authorization_digest(self) -> str:
        return canonical_digest(self.as_dict())

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Cp6RevalidationAuthorizationV1:
        if set(raw) != _REVALIDATION_AUTHORIZATION_FIELDS:
            raise FrozenCp6EvidenceError("CP6 revalidation authorization fields mismatch")
        paths = raw["allowed_write_paths"]
        string_fields = _REVALIDATION_AUTHORIZATION_FIELDS - {"schema_version", "allowed_write_paths"}
        if type(raw["schema_version"]) is not int or any(not isinstance(raw[field], str) for field in string_fields):
            raise FrozenCp6EvidenceError("CP6 revalidation authorization field types are invalid")
        return cls(
            schema_version=raw["schema_version"], cr_id=raw["cr_id"], story_id=raw["story_id"],
            work_id=raw["work_id"], attempt_id=raw["attempt_id"], release_oid=raw["release_oid"],
            process_oid=raw["process_oid"], scope_digest=raw["scope_digest"],
            previous_cp6_ref=raw["previous_cp6_ref"], previous_cp6_digest=raw["previous_cp6_digest"],
            superseding_cp5_ref=raw["superseding_cp5_ref"], superseding_cp5_digest=raw["superseding_cp5_digest"],
            plan_preimage_digest=raw["plan_preimage_digest"], allowed_write_paths=list(paths) if isinstance(paths, list) else [],
        )


def freeze_cp6_revalidation_authorization(**payload: Any) -> Cp6RevalidationAuthorizationV1:
    return Cp6RevalidationAuthorizationV1.from_dict(payload)


def _safe_process_work_pattern(
    value: object,
    *,
    work_id: str,
    attempt_id: str,
) -> bool:
    if not isinstance(value, str) or not value.startswith("process/works/") or "\\" in value or "://" in value:
        return False
    namespace = f"process/works/{work_id}/revalidation/{attempt_id}/artifacts/"
    return value.startswith(namespace) and all(
        segment not in {"", ".", ".."} for segment in value.split("/")
    )


def _require_logical_ref(value: object, field: str) -> str:
    """只接受持久化的 process 逻辑引用，拒绝绝对路径和 legacy alias。"""

    result = str(value or "")
    segments = result.split("/")
    if (
        not result.startswith("process/")
        or "\\" in result
        or any(not segment or segment in {".", ".."} for segment in segments)
    ):
        raise FrozenCp6EvidenceError(f"{field} must be a process logical ref")
    return result


def _require_digest(value: object, field: str) -> str:
    result = str(value or "")
    if not _DIGEST_RE.fullmatch(result):
        raise FrozenCp6EvidenceError(f"{field} must be a lowercase sha256 digest")
    return result


def _require_oid(value: object, field: str) -> str:
    result = str(value or "")
    if not _OID_RE.fullmatch(result):
        raise FrozenCp6EvidenceError(f"{field} must be a lowercase 40-hex OID")
    return result


_AUTHORIZATION_PAYLOAD_FIELDS = frozenset(
    {
        "previous_cp6_ref", "superseding_cp5_ref", "approval_ref",
        "work_authorization_ref", "plan_preimage_digest", "downstream_set_digest",
        "downstream_set",
    }
)
_PREFLIGHT_PAYLOAD_FIELDS = frozenset(
    {
        "authorization_digest", "packet_digest", "read_log_digest", "return_digest",
        "evidence_digest", "result_digest", "checkpoint_digest", "plan_digest",
        "downstream_set_digest", "p01_event_ref",
    }
)
_COMPLETION_PAYLOAD_FIELDS = frozenset(
    {"authorization_digest", "preflight_digest", "projection_digest", "downstream_set_digest"}
)
_RECOVERY_PAYLOAD_FIELDS = frozenset(
    {"authorization_digest", "completion_digest", "phase", "after_digest"}
)


def _validate_downstream_set(value: object, *, attempt_id: str, digest: object) -> None:
    if not isinstance(value, list) or not value:
        raise FrozenCp6EvidenceError("downstream_set must be a non-empty ordered list")
    previous = ""
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"producer", "receipt_digest", "attempt_id"}:
            raise FrozenCp6EvidenceError("downstream_set item fields mismatch")
        producer = str(item["producer"])
        if not producer or producer <= previous:
            raise FrozenCp6EvidenceError("downstream_set must be strictly producer-sorted")
        previous = producer
        _require_digest(item["receipt_digest"], "downstream_set.receipt_digest")
        if str(item["attempt_id"] or "") != attempt_id:
            raise FrozenCp6EvidenceError("downstream_set attempt lineage mismatch")
    if canonical_digest(value) != _require_digest(digest, "downstream_set_digest"):
        raise FrozenCp6EvidenceError("downstream_set_digest does not match canonical downstream_set")


def _validate_revalidation_payload(kind: str, payload: Mapping[str, Any], *, attempt_id: str) -> None:
    required_by_kind = {
        "authorization": _AUTHORIZATION_PAYLOAD_FIELDS,
        "preflight": _PREFLIGHT_PAYLOAD_FIELDS,
        "completion": _COMPLETION_PAYLOAD_FIELDS,
        "recovery": _RECOVERY_PAYLOAD_FIELDS,
    }
    required = required_by_kind[kind]
    if set(payload) != required:
        raise FrozenCp6EvidenceError(f"{kind} payload fields mismatch")
    if kind == "authorization":
        for field in ("previous_cp6_ref", "superseding_cp5_ref", "approval_ref", "work_authorization_ref"):
            _require_logical_ref(payload[field], field)
        for field in ("plan_preimage_digest", "downstream_set_digest"):
            _require_digest(payload[field], field)
        _validate_downstream_set(
            payload["downstream_set"],
            attempt_id=attempt_id,
            digest=payload["downstream_set_digest"],
        )
        return
    if kind == "preflight":
        for field in required - {"p01_event_ref"}:
            _require_digest(payload[field], field)
        _require_logical_ref(payload["p01_event_ref"], "p01_event_ref")
        return
    if kind == "completion":
        for field in required:
            _require_digest(payload[field], field)
        return
    for field in ("authorization_digest", "completion_digest", "after_digest"):
        _require_digest(payload[field], field)
    if payload["phase"] not in {"AUTHORIZED", "PREREGISTERED", "EVIDENCE_CORRELATED", "PROJECTED", "COMPLETE"}:
        raise FrozenCp6EvidenceError("recovery phase is invalid")


@dataclass(frozen=True)
class Cp6RevalidationReceiptV1:
    """P02 的严格、可摘要且不可变的 revalidation receipt 基类。

    每种 receipt 使用闭集字段、同一 attempt 身份及排除 ``payload_digest``
    后的 canonical digest；因此未知字段和跨 attempt 引用均不能静默通过。
    """

    kind: str
    cr_id: str
    story_id: str
    work_id: str
    attempt_id: str
    release_oid: str
    process_oid: str
    scope_digest: str
    payload: dict[str, Any]
    payload_digest: str = ""
    schema_version: int = CP6_REVALIDATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != CP6_REVALIDATION_SCHEMA_VERSION:
            raise FrozenCp6EvidenceError("unknown CP6 revalidation schema_version")
        if self.kind not in {
            "authorization",
            "preflight",
            "completion",
            "recovery",
        }:
            raise FrozenCp6EvidenceError("unknown CP6 revalidation receipt kind")
        if not all(isinstance(value, str) and value for value in (
            self.cr_id, self.story_id, self.work_id, self.attempt_id,
        )):
            raise FrozenCp6EvidenceError("revalidation identity fields are required")
        _require_oid(self.release_oid, "release_oid")
        _require_oid(self.process_oid, "process_oid")
        _require_digest(self.scope_digest, "scope_digest")
        if not isinstance(self.payload, dict):
            raise FrozenCp6EvidenceError("payload must be an object")
        _validate_revalidation_payload(self.kind, self.payload, attempt_id=self.attempt_id)
        expected = canonical_digest(self._without_digest())
        if self.payload_digest and self.payload_digest != expected:
            raise FrozenCp6EvidenceError("payload_digest does not match canonical payload")

    def _without_digest(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "cr_id": self.cr_id,
            "story_id": self.story_id,
            "work_id": self.work_id,
            "attempt_id": self.attempt_id,
            "release_oid": self.release_oid,
            "process_oid": self.process_oid,
            "scope_digest": self.scope_digest,
            "payload": dict(sorted(self.payload.items())),
        }

    def as_dict(self) -> dict[str, Any]:
        payload = self._without_digest()
        payload["payload_digest"] = canonical_digest(payload)
        return payload

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Cp6RevalidationReceiptV1:
        required = {
            "schema_version", "kind", "cr_id", "story_id", "work_id", "attempt_id",
            "release_oid", "process_oid", "scope_digest", "payload", "payload_digest",
        }
        if set(raw) != required:
            raise FrozenCp6EvidenceError("CP6 revalidation receipt fields mismatch")
        instance = cls(
            schema_version=raw["schema_version"], kind=str(raw["kind"]),
            cr_id=str(raw["cr_id"]), story_id=str(raw["story_id"]),
            work_id=str(raw["work_id"]), attempt_id=str(raw["attempt_id"]),
            release_oid=str(raw["release_oid"]), process_oid=str(raw["process_oid"]),
            scope_digest=str(raw["scope_digest"]), payload=dict(raw["payload"]),
            payload_digest=str(raw["payload_digest"]),
        )
        instance.as_dict()
        return instance


def freeze_cp6_revalidation_receipt(**payload: Any) -> Cp6RevalidationReceiptV1:
    """在任意 writer 前严格校验 P02 receipt，并返回不可变对象。"""

    return Cp6RevalidationReceiptV1.from_dict(payload)


def build_cp6_revalidation_receipt(
    *, kind: str, cr_id: str, story_id: str, work_id: str, attempt_id: str,
    release_oid: str, process_oid: str, scope_digest: str, payload: Mapping[str, Any],
) -> Cp6RevalidationReceiptV1:
    """从已校验的调用方输入构造 canonical receipt。"""

    return Cp6RevalidationReceiptV1(
        kind=kind, cr_id=cr_id, story_id=story_id, work_id=work_id,
        attempt_id=attempt_id, release_oid=release_oid, process_oid=process_oid,
        scope_digest=scope_digest, payload=dict(payload),
    )


def validate_revalidation_lineage(
    receipt: Cp6RevalidationReceiptV1 | Mapping[str, Any],
    *, cr_id: str, story_id: str, work_id: str, attempt_id: str,
) -> Cp6RevalidationReceiptV1:
    """确保 receipt 只被同 CR/Story/Work/attempt 的操作消费。"""

    frozen = receipt if isinstance(receipt, Cp6RevalidationReceiptV1) else Cp6RevalidationReceiptV1.from_dict(receipt)
    expected = (cr_id, story_id, work_id, attempt_id)
    actual = (frozen.cr_id, frozen.story_id, frozen.work_id, frozen.attempt_id)
    if actual != expected:
        raise FrozenCp6EvidenceError("CP6 revalidation receipt lineage mismatch")
    return frozen


def validate_revalidation_receipt_chain(
    authorization: Cp6RevalidationReceiptV1 | Mapping[str, Any],
    preflight: Cp6RevalidationReceiptV1 | Mapping[str, Any],
    completion: Cp6RevalidationReceiptV1 | Mapping[str, Any],
    recovery: Cp6RevalidationReceiptV1 | Mapping[str, Any],
) -> dict[str, Any]:
    """校验 CP6 immutable receipt chain 的身份与每条内链，失败原因稳定可消费。"""

    try:
        auth = authorization if isinstance(authorization, Cp6RevalidationReceiptV1) else Cp6RevalidationReceiptV1.from_dict(authorization)
        pre = preflight if isinstance(preflight, Cp6RevalidationReceiptV1) else Cp6RevalidationReceiptV1.from_dict(preflight)
        done = completion if isinstance(completion, Cp6RevalidationReceiptV1) else Cp6RevalidationReceiptV1.from_dict(completion)
        rec = recovery if isinstance(recovery, Cp6RevalidationReceiptV1) else Cp6RevalidationReceiptV1.from_dict(recovery)
    except (FrozenCp6EvidenceError, TypeError):
        return {"decision": "BLOCKED", "reason_codes": ["REVALIDATION_CHAIN_RECEIPT_INVALID"]}
    if any(item.kind != kind for item, kind in ((auth, "authorization"), (pre, "preflight"), (done, "completion"), (rec, "recovery"))):
        return {"decision": "BLOCKED", "reason_codes": ["REVALIDATION_CHAIN_KIND_MISMATCH"]}
    identity = (auth.cr_id, auth.story_id, auth.work_id, auth.attempt_id, auth.release_oid, auth.process_oid, auth.scope_digest)
    if any((item.cr_id, item.story_id, item.work_id, item.attempt_id, item.release_oid, item.process_oid, item.scope_digest) != identity for item in (pre, done, rec)):
        return {"decision": "BLOCKED", "reason_codes": ["REVALIDATION_CHAIN_IDENTITY_MISMATCH"]}
    auth_digest = auth.as_dict()["payload_digest"]
    pre_digest = pre.as_dict()["payload_digest"]
    done_digest = done.as_dict()["payload_digest"]
    links = (
        (pre.payload.get("authorization_digest"), auth_digest, "REVALIDATION_CHAIN_PREFLIGHT_AUTHORIZATION_MISMATCH"),
        (done.payload.get("authorization_digest"), auth_digest, "REVALIDATION_CHAIN_COMPLETION_AUTHORIZATION_MISMATCH"),
        (done.payload.get("preflight_digest"), pre_digest, "REVALIDATION_CHAIN_COMPLETION_PREFLIGHT_MISMATCH"),
        (done.payload.get("downstream_set_digest"), auth.payload.get("downstream_set_digest"), "REVALIDATION_CHAIN_COMPLETION_DOWNSTREAM_SET_MISMATCH"),
        (rec.payload.get("authorization_digest"), auth_digest, "REVALIDATION_CHAIN_RECOVERY_AUTHORIZATION_MISMATCH"),
        (rec.payload.get("completion_digest"), done_digest, "REVALIDATION_CHAIN_RECOVERY_COMPLETION_MISMATCH"),
    )
    for actual, expected, code in links:
        if actual != expected:
            return {"decision": "BLOCKED", "reason_codes": [code]}
    return {"decision": "READY", "reason_codes": []}


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
    revalidation_authorization: Cp6RevalidationAuthorizationV1 | Mapping[str, Any] | None = None,
    revalidation_identity: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """唯一 READY 入口；bootstrap 仅保留 provenance，绝不短路准入。"""

    del bootstrap  # 明确禁止 virtual bootstrap 对 decision 施加影响。
    if revalidation_authorization is not None:
        try:
            authorization = (
                revalidation_authorization
                if isinstance(revalidation_authorization, Cp6RevalidationAuthorizationV1)
                else Cp6RevalidationAuthorizationV1.from_dict(revalidation_authorization)
            )
        except (FrozenCp6EvidenceError, TypeError):
            return {"decision": "BLOCKED", "reason_codes": ["REVALIDATION_AUTHORIZATION_INVALID"], "dependency_state": "invalid"}
        expected = dict(revalidation_identity or {})
        actual = {key: getattr(authorization, key) for key in ("cr_id", "story_id", "work_id", "attempt_id", "release_oid", "process_oid", "scope_digest")}
        if any(expected.get(key) != value for key, value in actual.items()):
            return {"decision": "BLOCKED", "reason_codes": ["REVALIDATION_AUTHORIZATION_IDENTITY_MISMATCH"], "dependency_state": "blocked"}
        if projected_gate is None or set(projected_gate) != _PROJECTED_GATE_FIELDS or projected_gate.get("story_id") != authorization.story_id or projected_gate.get("status") != "ready-for-verification":
            return {"decision": "BLOCKED", "reason_codes": ["REVALIDATION_AUTHORIZATION_GATE_MISMATCH"], "dependency_state": "blocked"}
        return {"decision": "READY", "reason_codes": ["REVALIDATION_AUTHORIZATION_READY"], "dependency_state": "revalidation", "authorization_digest": authorization.authorization_digest}
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
