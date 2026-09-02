"""Publication/Transport/Observation payload 与 receipt producer（FA7/FA10/FA11）。

FA7 per-target publication 授权；transport（bytes 离开 provider 即消费，
ADR-076-07）；FA11 观测合同（P0-3，不载实测）+ RemoteObservationResultV1；
FA10 两 builder（append-only canonical ref）。观测/发布执行不在本模块——
需独立 typed authorization 与发布窗口。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

PUBLICATION_PAYLOAD_KIND = "publication-mutation-authorization"
TRANSPORT_PAYLOAD_KIND = "transport-mutation"
OBSERVATION_PAYLOAD_KIND = "observation-verification"
TARGET_KINDS = frozenset({"git-tag", "github-release", "registry-upload", "asset-upload"})
RECEIPT_OUTCOMES = ("SUCCEEDED", "PARTIAL", "FAILED")
VERIFIED, NOT_VERIFIED, BLOCKED = "VERIFIED", "NOT_VERIFIED", "BLOCKED"
PUBLICATION_RECEIPTS_REF = "process/release/receipts/publication-receipts.ndjson"
PUBLISHED_VERIFIED_RECEIPTS_REF = "process/release/receipts/published-verified-receipts.ndjson"
_HEX = frozenset("0123456789abcdef")


def _require_digest(value: object, field_name: str, *, allow_sha1: bool = False) -> str:
    text = value if isinstance(value, str) else ""
    if len(text) not in ((64, 40) if allow_sha1 else (64,)) or any(
        c not in _HEX for c in text.lower()
    ):
        raise ValueError(f"{field_name} must be a valid digest: {value!r}")
    return text


def _require_str(payload: Mapping[str, Any], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _parse_ts(value: object, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp: {value!r}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must carry a timezone")
    return parsed


def _digest_map(payload: Mapping[str, Any], field_name: str) -> dict[str, tuple[str, ...]]:
    raw = payload.get(field_name)
    if not isinstance(raw, Mapping) or not raw:
        raise ValueError(f"{field_name} must be a non-empty JSON object")
    result = {}
    for target, digests in raw.items():
        if not isinstance(target, str) or not isinstance(digests, (list, tuple)) or not digests:
            raise ValueError(f"{field_name}[{target!r}] must be a non-empty digest list")
        result[target] = tuple(_require_digest(d, f"{field_name}[{target!r}]") for d in digests)
    return result


def _digest_list(payload: Mapping[str, Any], field_name: str) -> tuple[str, ...]:
    raw = payload.get(field_name)
    if not isinstance(raw, (list, tuple)) or not raw:
        raise ValueError(f"{field_name} must be a non-empty digest list")
    return tuple(_require_digest(d, field_name) for d in raw)


def _closed(payload: Mapping[str, Any], allowed: set[str]) -> None:
    extra = set(payload) - allowed
    if extra:
        raise ValueError(f"unexpected fields: {sorted(extra)}")


# --- FA7/FA3 新增 payload（闭合校验；多余/缺失/类型不符 = ValueError） ---


@dataclass(frozen=True, slots=True)
class PublicationMutationAuthorizationV1:
    """per-target publication 授权（tag/release/registry/upload 各自独立）。"""

    schema_version: int
    kind: str
    target_kind: str
    target_identity: str
    remote_namespace: str
    remote_name: str
    remote_version: str
    consumer_accepted_digest: str
    predecessor_attempt: str | None = None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> PublicationMutationAuthorizationV1:
        _closed(payload, {
            "schema_version", "kind", "target_kind", "target_identity",
            "remote_namespace", "remote_name", "remote_version",
            "consumer_accepted_digest", "predecessor_attempt",
        })
        if payload.get("schema_version") != 1 or payload.get("kind") != PUBLICATION_PAYLOAD_KIND:
            raise ValueError("schema_version/kind mismatch for publication-mutation payload")
        target_kind = _require_str(payload, "target_kind")
        if target_kind not in TARGET_KINDS:
            raise ValueError(f"target_kind must be one of {sorted(TARGET_KINDS)}")
        predecessor = payload.get("predecessor_attempt")
        if predecessor is not None and not (
            isinstance(predecessor, str) and predecessor.strip()
        ):
            raise ValueError("predecessor_attempt must be a non-empty string or null")
        return cls(
            schema_version=1, kind=PUBLICATION_PAYLOAD_KIND, target_kind=target_kind,
            **{
                name: _require_str(payload, name)
                for name in ("target_identity", "remote_namespace", "remote_name", "remote_version")
            },
            consumer_accepted_digest=_require_digest(
                payload.get("consumer_accepted_digest"), "consumer_accepted_digest",
                allow_sha1=(target_kind == "git-tag"),  # 40 hex 仅 Git SHA-1 OID
            ),
            predecessor_attempt=predecessor,
        )


@dataclass(frozen=True, slots=True)
class TransportMutationAuthorizationV1:
    """transport 授权：任何 bytes 离开 provider 即消费（ADR-076-07）。"""

    schema_version: int
    kind: str
    target_refs: tuple[str, ...]
    preimage_digests: dict[str, str]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> TransportMutationAuthorizationV1:
        _closed(payload, {"schema_version", "kind", "target_refs", "preimage_digests"})
        if payload.get("schema_version") != 1 or payload.get("kind") != TRANSPORT_PAYLOAD_KIND:
            raise ValueError("schema_version/kind mismatch for transport-mutation payload")
        refs = payload.get("target_refs")
        if not isinstance(refs, (list, tuple)) or not refs or not all(
            isinstance(r, str) and r.strip() for r in refs
        ):
            raise ValueError("target_refs must be a non-empty list of logical refs")
        preimages_raw = payload.get("preimage_digests")
        if not isinstance(preimages_raw, Mapping) or not preimages_raw:
            raise ValueError("preimage_digests must be a non-empty JSON object")
        return cls(
            schema_version=1, kind=TRANSPORT_PAYLOAD_KIND, target_refs=tuple(refs),
            preimage_digests={
                str(ref): _require_digest(d, f"preimage_digests[{ref!r}]")
                for ref, d in preimages_raw.items()
            },
        )


@dataclass(frozen=True, slots=True)
class ObservationAuthorizationV1:
    """观测授权（P0-3 收窄）：只载合同；实测=RemoteObservationResultV1。"""

    schema_version: int
    kind: str
    target_set: tuple[str, ...]
    publication_receipt_digest_set: tuple[str, ...]
    expected_accepted_digest_set: dict[str, tuple[str, ...]]
    freshness_seconds: int
    principal_uid: str
    device_uid: str
    project_uid: str
    not_before: str
    not_after: str
    single_use: bool

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> ObservationAuthorizationV1:
        _closed(payload, {
            "schema_version", "kind", "target_set", "publication_receipt_digest_set",
            "expected_accepted_digest_set", "freshness_seconds", "principal_uid",
            "device_uid", "project_uid", "not_before", "not_after", "single_use",
        })
        if payload.get("schema_version") != 1 or payload.get("kind") != OBSERVATION_PAYLOAD_KIND:
            raise ValueError("schema_version/kind mismatch for observation-verification payload")
        if payload.get("single_use") is not True:
            raise ValueError("single_use must be true")
        targets = payload.get("target_set")
        if not isinstance(targets, (list, tuple)) or not targets or not all(
            isinstance(t, str) and t.strip() for t in targets
        ):
            raise ValueError("target_set must be a non-empty list of target identities")
        expected = _digest_map(payload, "expected_accepted_digest_set")
        if set(expected) != set(targets):
            raise ValueError("expected_accepted_digest_set must cover target_set exactly")
        freshness = payload.get("freshness_seconds")
        if not isinstance(freshness, int) or isinstance(freshness, bool) or freshness <= 0:
            raise ValueError("freshness_seconds must be a positive integer")
        if _parse_ts(payload.get("not_after"), "not_after") <= _parse_ts(
            payload.get("not_before"), "not_before"
        ):
            raise ValueError("not_after must be after not_before")
        return cls(
            schema_version=1, kind=OBSERVATION_PAYLOAD_KIND, target_set=tuple(targets),
            publication_receipt_digest_set=_digest_list(payload, "publication_receipt_digest_set"),
            expected_accepted_digest_set=expected, freshness_seconds=freshness,
            **{
                name: _require_str(payload, name)
                for name in (
                    "principal_uid", "device_uid", "project_uid", "not_before", "not_after",
                )
            },
            single_use=True,
        )


@dataclass(frozen=True, slots=True)
class RemoteObservationResultV1:
    """真实远端只读观测产物（非授权对象；VERIFIED 判定唯一实测来源）。"""

    observed_digest_sets: dict[str, tuple[str, ...]]
    observed_at: str
    command_identity: str
    attempt_id: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> RemoteObservationResultV1:
        _closed(payload, {"observed_digest_sets", "observed_at", "command_identity", "attempt_id"})
        _parse_ts(payload.get("observed_at"), "observed_at")  # 只验格式，判定归 builder
        return cls(
            observed_digest_sets=_digest_map(payload, "observed_digest_sets"),
            observed_at=_require_str(payload, "observed_at"),
            command_identity=_require_str(payload, "command_identity"),
            attempt_id=_require_str(payload, "attempt_id"),
        )


# --- FA10 receipt producer（append-only；canonical ref 见模块常量） ---


def _receipt_digest(receipt: Mapping[str, Any]) -> str:
    blob = json.dumps(dict(receipt), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _append_receipt(path: Path, receipt: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(receipt), sort_keys=True, ensure_ascii=False) + "\n")


def _receipt_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@dataclass(frozen=True, slots=True)
class PublicationReceiptV1:
    """每 mutation attempt 恰一（attempt 与 consumption ledger 同 attempt_id）。"""

    receipt_digest: str
    attempt_id: str
    target_kind: str
    target_identity: str
    outcome: str
    digests: tuple[str, ...]
    recorded_at: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> PublicationReceiptV1:
        return cls(
            receipt_digest=_require_digest(row.get("receipt_digest"), "receipt_digest"),
            attempt_id=_require_str(row, "attempt_id"), target_kind=_require_str(row, "target_kind"),
            target_identity=_require_str(row, "target_identity"),
            outcome=_require_str(row, "outcome"),
            digests=tuple(_require_digest(d, "digests") for d in row.get("digests", [])),
            recorded_at=_require_str(row, "recorded_at"),
        )


def build_publication_receipt(
    *, receipts_path: Path, attempt_id: str, target_kind: str, target_identity: str,
    outcome: str, digests: tuple[str, ...] | list[str], now: datetime | None = None,
) -> tuple[PublicationReceiptV1, str]:
    """构造并 append PublicationReceiptV1；返回 (receipt, canonical ref)。

    崩溃补记幂等（AE-08）：同 attempt 已有 receipt 且内容一致 → 返回既有行
    不重复 append；outcome 冲突 → ValueError（不静默改写历史行）。
    """
    if outcome not in RECEIPT_OUTCOMES:
        raise ValueError(f"outcome must be one of {RECEIPT_OUTCOMES}: {outcome}")
    if target_kind not in TARGET_KINDS:
        raise ValueError(f"target_kind must be one of {sorted(TARGET_KINDS)}")
    digest_tuple = tuple(
        _require_digest(d, "digests", allow_sha1=(target_kind == "git-tag")) for d in digests
    )
    body = {
        "attempt_id": attempt_id, "target_kind": target_kind,
        "target_identity": target_identity, "outcome": outcome,
        "digests": list(digest_tuple),
        "recorded_at": (now or datetime.now(UTC)).isoformat(),
    }
    for row in _receipt_rows(receipts_path):
        if row.get("attempt_id") == attempt_id:
            # 崩溃补记幂等：内容一致返回既有行；冲突=编程错误（不改写历史行）
            if (
                row.get("outcome") == outcome
                and row.get("digests") == body["digests"]
                and row.get("target_identity") == target_identity
            ):
                return PublicationReceiptV1.from_mapping(row), PUBLICATION_RECEIPTS_REF
            raise ValueError(f"receipt already exists for attempt {attempt_id}: {row}")
    receipt = PublicationReceiptV1(
        receipt_digest=_receipt_digest(body), attempt_id=attempt_id,
        target_kind=target_kind, target_identity=target_identity, outcome=outcome,
        digests=digest_tuple, recorded_at=body["recorded_at"],
    )
    _append_receipt(receipts_path, asdict(receipt))
    return receipt, PUBLICATION_RECEIPTS_REF


@dataclass(frozen=True, slots=True)
class PublishedVerifiedReceiptV1:
    """published-verified 判定 receipt（聚合 publication 链 + 远端观测）。"""

    receipt_digest: str
    verification: str
    authorization_id: str
    authorization_attempt_id: str | None
    observation_attempt_id: str | None
    publication_receipt_digest_set: tuple[str, ...]
    mismatched_targets: tuple[str, ...]
    observed_at: str | None
    valid_until: str | None
    recorded_at: str
    reasons: tuple[str, ...] = ()


def build_published_verified_receipt(
    *, receipts_path: Path, authorization: Mapping[str, Any] | ObservationAuthorizationV1,
    publication_receipts: list[Mapping[str, Any]],
    observation_result: Mapping[str, Any] | RemoteObservationResultV1 | None,
    authorization_attempt_id: str | None = None, now: datetime | None = None,
) -> tuple[PublishedVerifiedReceiptV1, str]:
    """三参验证（P0-3 四规则）；任何违规不得构造 VERIFIED。

    BLOCKED=结构性违规；NOT_VERIFIED=结构合法但 digest-set 不等或超窗；
    两者都 append 审计行（mutation=0 指不产生外部副作用）。
    """
    auth = authorization if isinstance(authorization, ObservationAuthorizationV1) else (
        ObservationAuthorizationV1.from_mapping(authorization)
    )
    result = observation_result if isinstance(observation_result, RemoteObservationResultV1) else (
        RemoteObservationResultV1.from_mapping(observation_result)
        if observation_result is not None else None
    )
    checked_at = now or datetime.now(UTC)
    reasons: list[str] = []
    mismatched: list[str] = []
    observed_at: str | None = None
    valid_until: str | None = None

    receipts = [PublicationReceiptV1.from_mapping(r) for r in publication_receipts]
    by_target = {r.target_identity: r for r in receipts}
    if len(by_target) != len(receipts):
        reasons.append("duplicate receipt target(s)")
    actual_digest_set = tuple(r.receipt_digest for r in receipts)

    verification = BLOCKED
    if not reasons:
        # 规则 3：三方 attempt 与 target 一致；规则 2：实测缺任一 target=BLOCKED
        if result is None:
            reasons.append("no observation result")
        elif authorization_attempt_id is None or result.attempt_id != authorization_attempt_id:
            reasons.append("observation attempt not bound to authorization attempt")
        elif set(by_target) != set(auth.target_set):
            delta = sorted(set(auth.target_set) ^ set(by_target))
            reasons.append(f"publication receipts must cover target_set exactly: {delta}")
        elif any(r.outcome != "SUCCEEDED" for r in receipts):
            reasons.append("all publication receipts must be SUCCEEDED")
        elif actual_digest_set != auth.publication_receipt_digest_set:
            reasons.append("publication receipt digest set does not match authorization")
        elif any(t not in result.observed_digest_sets for t in auth.target_set):
            reasons.append("observed result missing target(s)")
    if not reasons and result is not None:
        observed_at = result.observed_at
        observed_time = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        fresh_end = observed_time + timedelta(seconds=auth.freshness_seconds)
        valid_until = fresh_end.isoformat()
        # freshness 超窗 / 时效超窗 → NOT_VERIFIED（时效用解析值比较，避免
        # ISO 字符串序在跨时区表示下失真）；逐 target 比对（规则 1）
        in_window = (
            _parse_ts(auth.not_before, "not_before")
            <= observed_time
            <= _parse_ts(auth.not_after, "not_after")
        )
        if checked_at > fresh_end or not in_window:
            verification = NOT_VERIFIED
            reasons.append("freshness or validity window exceeded")
        else:
            mismatched = [
                t for t in auth.target_set
                if tuple(result.observed_digest_sets.get(t, ()))
                != auth.expected_accepted_digest_set[t]
            ]
            verification = NOT_VERIFIED if mismatched else VERIFIED
    content = {
        "verification": verification,
        "authorization_id": _authorization_label(auth),
        "authorization_attempt_id": authorization_attempt_id,
        "observation_attempt_id": None if result is None else result.attempt_id,
        "publication_receipt_digest_set": actual_digest_set,
        "mismatched_targets": tuple(mismatched),
        "observed_at": observed_at, "valid_until": valid_until,
        "recorded_at": checked_at.isoformat(), "reasons": tuple(reasons),
    }
    receipt = PublishedVerifiedReceiptV1(
        receipt_digest=_receipt_digest(content), **content
    )
    _append_receipt(receipts_path, asdict(receipt))
    return receipt, PUBLISHED_VERIFIED_RECEIPTS_REF


def _authorization_label(auth: ObservationAuthorizationV1) -> str:
    # 观测 payload 无独立 authorization_id 字段（id 在 envelope 层）；
    # 以 target_set+时效的稳定 sha256 指纹作审计标签（跨进程一致）
    fingerprint = json.dumps(
        [list(auth.target_set), auth.not_before, auth.not_after],
        sort_keys=True, ensure_ascii=False,
    ).encode("utf-8")
    return f"{OBSERVATION_PAYLOAD_KIND}:{hashlib.sha256(fingerprint).hexdigest()[:16]}"


# --- registry 注册（lazy import 防循环依赖；S05 消费） ---


def register_release_payloads() -> None:
    from meta_flow.execution_control.authorization import register_operation_payload

    payload_kinds = {
        "publication-mutation": PublicationMutationAuthorizationV1,
        "transport-mutation": TransportMutationAuthorizationV1,
        "observation-verification": ObservationAuthorizationV1,
    }
    for operation, payload_cls in payload_kinds.items():
        register_operation_payload(operation, lambda p, c=payload_cls: c.from_mapping(p))


register_release_payloads()
