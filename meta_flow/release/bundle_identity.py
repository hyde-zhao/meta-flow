"""CR-076 S03：不可变 bundle 身份对象集、transport receipt 与前驱链校验。

权威 = STORY-CR076-S03-bundle-identity-transport-LLD（v1.2）+ 冻结 schema
release-bundle-identity-v1（rev3）。双域语义（最易错点）：
``manifest.assets.sidecar`` 是零槽预像域（信封槽位 ``b"\\x00"*4096`` 后整体
sha256）；``TransportReceiptV1.transported_assets.sidecar`` 是物理 sha256 域
（provider==carrier==landing 三端相等）。两域值不同、各司其职，禁直接相等比较。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from hashlib import sha256
from typing import Any

from meta_flow.installation.canonical import canonical_bytes, canonical_digest
from meta_flow.installation.identity import require_full_digest, require_full_oid

BUNDLE_MANIFEST_KIND = "ImmutableBaseBundleManifestV1"
TRANSPORT_RECEIPT_KIND = "TransportReceiptV1"
LINEAGE_INDEX_KIND = "BundleLineageIndexV1"
BUNDLE_SCHEMA_VERSION = 1
ASSET_FIELDS = ("wheel", "sdist", "build_receipt", "sidecar")
NAMING_FIELDS = ("project_name", "wheel_tag", "normalized_prefix")
MANIFEST_FIELDS = (
    "schema_version", "kind", "bundle_id", "bundle_digest", "semver",
    "source", "assets", "naming", "built_at", "build_authorization_digest",
)
SOURCE_FIELDS = ("release_oid", "process_oid", "frozen_at")
ZERO_DIGEST_PLACEHOLDER = "0" * 64
SIDECAR_ENVELOPE_HEADER_SIZE = 8
SIDECAR_ENVELOPE_SLOT_SIZE = 4096
_TIMESTAMP_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(\.[0-9]+)?(Z|[+-][0-9]{2}:[0-9]{2})$"
)
_SEMVER_RE = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$"
)
_AUTH_DIGEST_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
_NAME_TOKEN_RE = re.compile(r"^[A-Za-z0-9._:/-]{1,256}$")


def _require_timestamp(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _TIMESTAMP_RE.fullmatch(value):
        raise ValueError(f"MANIFEST-FIELD-INVALID: {field} must be an ISO-8601 timestamp: {value!r}")
    return value


def _require_semver(value: object, *, field: str = "semver") -> str:
    if not isinstance(value, str) or not _SEMVER_RE.fullmatch(value):
        raise ValueError(f"MANIFEST-FIELD-INVALID: {field} must be a semver string: {value!r}")
    return value


def require_name_token(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _NAME_TOKEN_RE.fullmatch(value):
        raise ValueError(f"MANIFEST-FIELD-INVALID: {field} must match ^[A-Za-z0-9._:/-]{{1,256}}$: {value!r}")
    return value


def _require_auth_digest(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _AUTH_DIGEST_RE.fullmatch(value):
        raise ValueError(f"MANIFEST-FIELD-INVALID: {field} must be sha256:<64-hex>: {value!r}")
    return value


def _require_fields(payload: object, expected: tuple[str, ...], *, field: str) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or set(payload) != set(expected):
        raise ValueError(f"MANIFEST-FIELD-INVALID: {field} must contain exactly {list(expected)}")
    return {key: payload[key] for key in expected}


def _require_digest_group(payload: object, *, field: str) -> dict[str, str]:
    group = _require_fields(payload, ASSET_FIELDS, field=field)
    for name in ASSET_FIELDS:
        require_full_digest(group[name], field_name=f"{field}.{name}")
    return group


# --- 原语区（S04 复用） -----------------------------------------------------


def canonical_payload_digest(payload: object) -> str:
    """canonical payload 的 sha256；口径与 installation.canonical 一致。"""

    return canonical_digest(payload)


def slotted_zero_digest(
    payload: Mapping[str, Any],
    slot_field: str,
    zero_value: str,
) -> str:
    """把 ``slot_field`` 槽位值替换为显式 ``zero_value`` 后求 canonical digest。"""

    if not isinstance(payload, Mapping) or slot_field not in payload:
        raise ValueError(f"MANIFEST-FIELD-INVALID: payload must carry slot field {slot_field!r}")
    slotted = dict(payload)
    slotted[slot_field] = zero_value
    return canonical_digest(slotted)


def require_object_kind(payload: object, expected_kind: str) -> str:
    """要求 ``payload.kind == expected_kind``；不符即前驱链断裂信号。"""

    kind = payload.get("kind") if isinstance(payload, Mapping) else None
    if kind != expected_kind:
        raise ValueError(f"OBJECT-KIND-MISMATCH: expected {expected_kind}, got {kind!r}")
    return str(kind)


# --- manifest 区：sidecar 信封（本地格式，LCQ-S03-01 冻结） ------------------


def build_sidecar_envelope(manifest_bytes: bytes) -> bytes:
    """物理域信封：8 字节大端 manifest_len 头部 + 定长 4096 字节槽位。

    槽位 = manifest canonical bytes + 零 padding；manifest 超过槽位长度即拒绝。
    """

    if not isinstance(manifest_bytes, (bytes, bytearray)) or not manifest_bytes:
        raise ValueError("SIDECAR-ENVELOPE-INVALID: manifest bytes must be non-empty")
    if len(manifest_bytes) > SIDECAR_ENVELOPE_SLOT_SIZE:
        raise ValueError(f"SIDECAR-ENVELOPE-INVALID: manifest exceeds {SIDECAR_ENVELOPE_SLOT_SIZE}-byte slot ({len(manifest_bytes)} bytes)")
    header = len(manifest_bytes).to_bytes(SIDECAR_ENVELOPE_HEADER_SIZE, "big")
    padding = b"\x00" * (SIDECAR_ENVELOPE_SLOT_SIZE - len(manifest_bytes))
    return header + bytes(manifest_bytes) + padding


def sidecar_preimage_digest(envelope: bytes) -> str:
    """预像域 digest：槽位整体置 ``b"\\x00"*4096`` 后对信封整体求 sha256。"""

    expected_size = SIDECAR_ENVELOPE_HEADER_SIZE + SIDECAR_ENVELOPE_SLOT_SIZE
    if not isinstance(envelope, (bytes, bytearray)) or len(envelope) != expected_size:
        raise ValueError(f"SIDECAR-ENVELOPE-INVALID: envelope must be {expected_size} bytes")
    header = bytes(envelope[:SIDECAR_ENVELOPE_HEADER_SIZE])
    return sha256(header + b"\x00" * SIDECAR_ENVELOPE_SLOT_SIZE).hexdigest()


def materialize_sidecar_envelope(manifest: Mapping[str, Any]) -> bytes:
    """校验 manifest 后产出物理信封 bytes（落盘/传输域输入）。"""

    return build_sidecar_envelope(canonical_bytes(validate_base_bundle_manifest(manifest)))


def derive_sidecar_preimage(manifest_like: Mapping[str, Any]) -> str:
    """三槽位置占位后由 canonical 长度推导零槽预像（消除自引用，推导唯一）。"""

    skeleton = dict(manifest_like)
    skeleton["assets"] = {**dict(skeleton.get("assets", {})), "sidecar": ZERO_DIGEST_PLACEHOLDER}
    skeleton["bundle_id"] = ZERO_DIGEST_PLACEHOLDER
    skeleton["bundle_digest"] = ZERO_DIGEST_PLACEHOLDER
    return sidecar_preimage_digest(build_sidecar_envelope(canonical_bytes(skeleton)))


# --- manifest 区：构建 / 校验 / 重复注册 ------------------------------------


def validate_base_bundle_manifest(payload: object) -> dict[str, Any]:
    """按冻结 schema rev3 分支校验 ImmutableBaseBundleManifestV1（含自 digest 复核）。"""

    manifest = _require_fields(payload, MANIFEST_FIELDS, field="manifest")
    if manifest["schema_version"] != BUNDLE_SCHEMA_VERSION or manifest["kind"] != BUNDLE_MANIFEST_KIND:
        raise ValueError("MANIFEST-FIELD-INVALID: manifest schema_version/kind mismatch")
    require_full_digest(manifest["bundle_id"], field_name="bundle_id")
    require_full_digest(manifest["bundle_digest"], field_name="bundle_digest")
    _require_semver(manifest["semver"])
    source = _require_fields(manifest["source"], SOURCE_FIELDS, field="manifest.source")
    require_full_oid(source["release_oid"], field_name="source.release_oid")
    require_full_oid(source["process_oid"], field_name="source.process_oid")
    _require_timestamp(source["frozen_at"], field="source.frozen_at")
    _require_digest_group(manifest["assets"], field="manifest.assets")
    naming = _require_fields(manifest["naming"], NAMING_FIELDS, field="manifest.naming")
    for field in NAMING_FIELDS:
        require_name_token(naming[field], field=f"naming.{field}")
    _require_timestamp(manifest["built_at"], field="built_at")
    _require_auth_digest(manifest["build_authorization_digest"], field="build_authorization_digest")
    expected = slotted_zero_digest(manifest, "bundle_digest", ZERO_DIGEST_PLACEHOLDER)
    if manifest["bundle_digest"] != expected:
        raise ValueError("MANIFEST-FIELD-INVALID: bundle_digest does not match zero-slotted canonical payload")
    return manifest


def build_base_bundle_manifest(
    *,
    release_oid: str,
    process_oid: str,
    frozen_at: str,
    semver: str,
    asset_digests: Mapping[str, str],
    naming: Mapping[str, str],
    built_at: str,
    build_authorization_digest: str,
    registered_index: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """构造不可变基座 manifest；同 bundle_id 已注册即拒绝（禁重建在数据层成立）。

    ``bundle_id = sha256(canonical(release_oid, process_oid, semver, assets
    四槽含 sidecar 预像, naming))``：``built_at``/``build_authorization_digest``
    不入 id，同输入重建保持同 id。``asset_digests["sidecar"]`` 必须是零槽预像
    域值（由 manifest canonical 长度推导；物理 sha256 误入在此阻断 BIT-N02）。
    """

    require_full_oid(release_oid, field_name="release_oid")
    require_full_oid(process_oid, field_name="process_oid")
    _require_timestamp(frozen_at, field="frozen_at")
    _require_semver(semver)
    _require_timestamp(built_at, field="built_at")
    _require_auth_digest(build_authorization_digest, field="build_authorization_digest")
    assets = _require_digest_group(asset_digests, field="asset_digests")
    normalized_naming = _require_fields(naming, NAMING_FIELDS, field="naming")
    draft: dict[str, Any] = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "kind": BUNDLE_MANIFEST_KIND,
        "bundle_id": ZERO_DIGEST_PLACEHOLDER,
        "bundle_digest": ZERO_DIGEST_PLACEHOLDER,
        "semver": semver,
        "source": {"release_oid": release_oid, "process_oid": process_oid, "frozen_at": frozen_at},
        "assets": assets,
        "naming": normalized_naming,
        "built_at": built_at,
        "build_authorization_digest": build_authorization_digest,
    }
    derived_preimage = derive_sidecar_preimage(draft)
    if assets["sidecar"] != derived_preimage:
        raise ValueError(
            "SIDECAR-PREIMAGE-MISMATCH: asset_digests.sidecar must be the derived "
            f"zero-slotted preimage digest ({derived_preimage}), not the physical sha256"
        )
    bundle_id = canonical_payload_digest(
        {
            "assets": assets,
            "naming": normalized_naming,
            "process_oid": process_oid,
            "release_oid": release_oid,
            "semver": semver,
        }
    )
    for registered in registered_index:
        require_object_kind(registered, BUNDLE_MANIFEST_KIND)
        if registered.get("bundle_id") == bundle_id:
            raise ValueError(f"BUNDLE-ALREADY-REGISTERED: bundle_id {bundle_id} is already registered")
    draft["bundle_id"] = bundle_id
    draft["bundle_digest"] = slotted_zero_digest(draft, "bundle_digest", ZERO_DIGEST_PLACEHOLDER)
    return validate_base_bundle_manifest(draft)


# --- transport/index 区：receipt 构建 / lineage 索引 / supersede -------------


RECEIPT_FIELDS = (
    "schema_version", "kind", "receipt_digest", "predecessor_digest",
    "predecessor_kind", "attempt_id", "transported_assets", "transported_at",
    "transport_authorization_digest", "outcome", "predecessor_attempt", "reason_codes",
)
TRANSPORT_OUTCOMES = ("DELIVERED", "PARTIAL", "FAILED")
LINEAGE_ENTRY_KINDS = (
    "transport", "acceptance", "publication", "published-verified", "installation",
)
LINEAGE_INDEX_FIELDS = ("schema_version", "kind", "index_id", "bundle_digest", "entries", "updated_at")
LINEAGE_ENTRY_FIELDS = ("entry_kind", "entry_digest", "recorded_at", "superseded_by")
LINEAGE_INDEX_MAX_ENTRIES = 256
REASON_CODE_RE = re.compile(r"^[A-Z][A-Z0-9-]{1,95}$")
_PREDECESSOR_DIGEST_FIELD = {
    BUNDLE_MANIFEST_KIND: "bundle_digest",
    TRANSPORT_RECEIPT_KIND: "receipt_digest",
}


def _require_reason_codes(values: object, *, outcome: str) -> tuple[str, ...]:
    if values is None:
        values = ()
    if isinstance(values, str) or not isinstance(values, (list, tuple)):
        raise ValueError(f"RECEIPT-REASON-CODES-REQUIRED: reason_codes must be a list for outcome {outcome}")
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str) or not REASON_CODE_RE.fullmatch(value.strip()):
            raise ValueError(f"RECEIPT-REASON-CODES-REQUIRED: invalid reason code {value!r}")
        if value.strip() and value.strip() not in normalized:
            normalized.append(value.strip())
    normalized.sort()
    if outcome in ("PARTIAL", "FAILED") and not normalized:
        raise ValueError(f"RECEIPT-REASON-CODES-REQUIRED: outcome {outcome} requires non-empty reason_codes")
    if outcome == "DELIVERED" and normalized:
        raise ValueError("RECEIPT-REASON-CODES-REQUIRED: outcome DELIVERED must not carry reason_codes")
    if len(normalized) > 16:
        raise ValueError("RECEIPT-REASON-CODES-REQUIRED: reason_codes exceed 16 items")
    return tuple(normalized)


def validate_transport_receipt(payload: object) -> dict[str, Any]:
    """按冻结 schema rev3 分支校验 TransportReceiptV1（含自 digest 复核）。"""

    if not isinstance(payload, Mapping):
        raise ValueError("MANIFEST-FIELD-INVALID: receipt must be a JSON object")
    if set(payload) - set(RECEIPT_FIELDS):
        raise ValueError(f"MANIFEST-FIELD-INVALID: receipt carries unexpected fields {sorted(set(payload) - set(RECEIPT_FIELDS))}")
    receipt = {key: payload[key] for key in RECEIPT_FIELDS if key in payload}
    # RECEIPT_FIELDS 末两位是可选键（predecessor_attempt / reason_codes），其余必填。
    missing = [key for key in RECEIPT_FIELDS[:-2] if key not in payload]
    if missing:
        raise ValueError(f"MANIFEST-FIELD-INVALID: receipt missing required fields {missing}")
    if receipt["schema_version"] != BUNDLE_SCHEMA_VERSION or receipt["kind"] != TRANSPORT_RECEIPT_KIND:
        raise ValueError("MANIFEST-FIELD-INVALID: receipt schema_version/kind mismatch")
    require_full_digest(receipt["receipt_digest"], field_name="receipt_digest")
    require_full_digest(receipt["predecessor_digest"], field_name="predecessor_digest")
    if receipt["predecessor_kind"] != BUNDLE_MANIFEST_KIND:
        raise ValueError("MANIFEST-FIELD-INVALID: receipt predecessor_kind must be ImmutableBaseBundleManifestV1")
    require_name_token(receipt["attempt_id"], field="attempt_id")
    _require_digest_group(receipt["transported_assets"], field="receipt.transported_assets")
    _require_timestamp(receipt["transported_at"], field="transported_at")
    _require_auth_digest(receipt["transport_authorization_digest"], field="transport_authorization_digest")
    if receipt["outcome"] not in TRANSPORT_OUTCOMES:
        raise ValueError(f"MANIFEST-FIELD-INVALID: outcome must be one of {TRANSPORT_OUTCOMES}")
    if "predecessor_attempt" in receipt and receipt["predecessor_attempt"] is not None:
        require_name_token(receipt["predecessor_attempt"], field="predecessor_attempt")
    codes = _require_reason_codes(receipt.get("reason_codes"), outcome=receipt["outcome"])
    receipt["reason_codes"] = list(codes)
    unsigned = {key: value for key, value in receipt.items() if key != "receipt_digest"}
    expected = canonical_digest(unsigned)
    if receipt["receipt_digest"] != expected:
        raise ValueError("MANIFEST-FIELD-INVALID: receipt_digest does not match canonical payload")
    return receipt


def build_transport_receipt(
    *,
    predecessor: Mapping[str, Any],
    attempt_id: str,
    transported_assets: Mapping[str, str],
    transported_at: str,
    transport_authorization_digest: str,
    outcome: str,
    reason_codes: Iterable[str] = (),
    predecessor_attempt: str | None = None,
) -> dict[str, Any]:
    """构造 TransportReceiptV1；前驱必须是不可变基座 manifest（ADR-07 消费合同）。

    ``transported_assets`` 是物理 sha256 域断言值（三端相等比对基准）；
    ``receipt_digest`` 为自身 canonical payload 槽位置零（``"0"*64``）后的
    digest。重试必须新授权 + 新 attempt，``predecessor_attempt`` 指向失败
    attempt；旧 receipt 不删除、不修改。
    """

    require_object_kind(predecessor, BUNDLE_MANIFEST_KIND)
    require_full_digest(predecessor.get("bundle_digest"), field_name="predecessor.bundle_digest")
    validate_base_bundle_manifest(predecessor)
    require_name_token(attempt_id, field="attempt_id")
    assets = _require_digest_group(transported_assets, field="transported_assets")
    _require_timestamp(transported_at, field="transported_at")
    _require_auth_digest(transport_authorization_digest, field="transport_authorization_digest")
    if outcome not in TRANSPORT_OUTCOMES:
        raise ValueError(f"MANIFEST-FIELD-INVALID: outcome must be one of {TRANSPORT_OUTCOMES}")
    codes = _require_reason_codes(reason_codes, outcome=outcome)
    if predecessor_attempt is not None:
        require_name_token(predecessor_attempt, field="predecessor_attempt")
    receipt: dict[str, Any] = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "kind": TRANSPORT_RECEIPT_KIND,
        "receipt_digest": ZERO_DIGEST_PLACEHOLDER,
        "predecessor_digest": predecessor["bundle_digest"],
        "predecessor_kind": BUNDLE_MANIFEST_KIND,
        "attempt_id": attempt_id,
        "transported_assets": assets,
        "transported_at": transported_at,
        "transport_authorization_digest": transport_authorization_digest,
        "outcome": outcome,
        "predecessor_attempt": predecessor_attempt,
        "reason_codes": list(codes),
    }
    unsigned = {key: value for key, value in receipt.items() if key != "receipt_digest"}
    receipt["receipt_digest"] = canonical_digest(unsigned)
    return validate_transport_receipt(receipt)


def validate_lineage_index(payload: object) -> dict[str, Any]:
    """按冻结 schema rev3 分支校验 BundleLineageIndexV1。"""

    index = _require_fields(payload, LINEAGE_INDEX_FIELDS, field="lineage_index")
    if index["schema_version"] != BUNDLE_SCHEMA_VERSION or index["kind"] != LINEAGE_INDEX_KIND:
        raise ValueError("MANIFEST-FIELD-INVALID: lineage index schema_version/kind mismatch")
    require_name_token(index["index_id"], field="index_id")
    require_full_digest(index["bundle_digest"], field_name="index.bundle_digest")
    entries = index["entries"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= LINEAGE_INDEX_MAX_ENTRIES:
        raise ValueError(f"MANIFEST-FIELD-INVALID: entries must be a list of 1..{LINEAGE_INDEX_MAX_ENTRIES} items")
    for position, raw in enumerate(entries):
        if not isinstance(raw, Mapping) or set(raw) - set(LINEAGE_ENTRY_FIELDS):
            raise ValueError(f"MANIFEST-FIELD-INVALID: entries[{position}] carries unexpected fields")
        if raw.get("entry_kind") not in LINEAGE_ENTRY_KINDS:
            raise ValueError(f"MANIFEST-FIELD-INVALID: entries[{position}].entry_kind is invalid")
        require_full_digest(raw.get("entry_digest"), field_name=f"entries[{position}].entry_digest")
        _require_timestamp(raw.get("recorded_at"), field=f"entries[{position}].recorded_at")
        if raw.get("superseded_by") is not None:
            require_name_token(raw["superseded_by"], field=f"entries[{position}].superseded_by")
    _require_timestamp(index["updated_at"], field="index.updated_at")
    return index


def build_lineage_index(*, index_id: str, bundle_digest: str, recorded_at: str) -> dict[str, Any]:
    """构造只含基座 manifest 首条的空链索引（后续全部走 append）。"""

    return validate_lineage_index({
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "kind": LINEAGE_INDEX_KIND,
        "index_id": index_id,
        "bundle_digest": bundle_digest,
        "entries": [
            {"entry_kind": "transport", "entry_digest": bundle_digest, "recorded_at": recorded_at, "superseded_by": None}
        ],
        "updated_at": recorded_at,
    })


def append_lineage_entry(
    index: Mapping[str, Any],
    *,
    entry_kind: str,
    entry_digest: str,
    recorded_at: str,
) -> dict[str, Any]:
    """返回追加了新 entry 的 index 副本；不改入参、不改既有 entry bytes。"""

    base = validate_lineage_index(index)
    if entry_kind not in LINEAGE_ENTRY_KINDS:
        raise ValueError(f"MANIFEST-FIELD-INVALID: entry_kind must be one of {LINEAGE_ENTRY_KINDS}")
    require_full_digest(entry_digest, field_name="entry_digest")
    _require_timestamp(recorded_at, field="recorded_at")
    if len(base["entries"]) >= LINEAGE_INDEX_MAX_ENTRIES:
        raise ValueError(f"LINEAGE-INDEX-FULL: entries already reach {LINEAGE_INDEX_MAX_ENTRIES}")
    appended = dict(base)
    appended["entries"] = [
        *base["entries"],
        {"entry_kind": entry_kind, "entry_digest": entry_digest, "recorded_at": recorded_at, "superseded_by": None},
    ]
    appended["updated_at"] = recorded_at
    return validate_lineage_index(appended)


def mark_superseded(
    index: Mapping[str, Any],
    *,
    entry_digest: str,
    superseded_by: str,
) -> dict[str, Any]:
    """对匹配 ``entry_digest`` 的 entry 标记 ``superseded_by``（返回新 index）。"""

    base = validate_lineage_index(index)
    require_full_digest(entry_digest, field_name="entry_digest")
    require_name_token(superseded_by, field="superseded_by")
    marked: list[dict[str, Any]] = []
    matched = False
    for entry in base["entries"]:
        copy = dict(entry)
        if copy["entry_digest"] == entry_digest:
            matched = True
            if copy.get("superseded_by") is not None:
                raise ValueError(f"ENTRY-ALREADY-SUPERSEDED: entry {entry_digest} already superseded by {copy['superseded_by']}")
            copy["superseded_by"] = superseded_by
        marked.append(copy)
    if not matched:
        raise ValueError(f"LINEAGE-ENTRY-MISSING: no entry matches digest {entry_digest}")
    superseded = dict(base)
    superseded["entries"] = marked
    return validate_lineage_index(superseded)


# --- 链校验区（schema $comment 验证器落地；S03/S04/S05 共用） ----------------


def validate_predecessor(payload: Mapping[str, Any], predecessor: Mapping[str, Any]) -> None:
    """逐对象比对：前驱 kind 字段 == payload.predecessor_kind，且 digest 指向。"""

    declared = payload.get("predecessor_kind") if isinstance(payload, Mapping) else None
    actual = predecessor.get("kind") if isinstance(predecessor, Mapping) else None
    if declared != actual:
        raise ValueError(f"PREDECESSOR-KIND-MISMATCH: declared {declared!r} but predecessor kind is {actual!r}")
    digest_field = _PREDECESSOR_DIGEST_FIELD.get(str(actual))
    if digest_field is None:
        raise ValueError(f"PREDECESSOR-KIND-MISMATCH: unknown predecessor kind {actual!r}")
    if payload.get("predecessor_digest") != predecessor.get(digest_field):
        raise ValueError(
            f"PREDECESSOR-DIGEST-MISMATCH: payload points to {payload.get('predecessor_digest')!r} "
            f"but predecessor {digest_field} is {predecessor.get(digest_field)!r}"
        )


def verify_predecessor_chain(objects: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
    """校验有序序列相邻前驱关系；空序列通过（conflicts 元组，不 raise）。"""

    chain = list(objects)
    conflicts: list[str] = []
    for position in range(1, len(chain)):
        try:
            validate_predecessor(chain[position], chain[position - 1])
        except ValueError as exc:
            conflicts.append(f"CHAIN[{position}]:{exc}")
    return tuple(conflicts)


def verify_quadruple_consistency(
    *,
    manifest: Mapping[str, Any],
    physical_assets: Mapping[str, str],
    physical_sidecar_envelope: bytes,
    transported_assets: Mapping[str, str],
    discovery_report: Mapping[str, str],
) -> tuple[str, ...]:
    """四重一致性：三类四向直比；sidecar 双域分流（预像复算 + 物理三端）。

    wheel/sdist/build_receipt：``manifest.assets == 物理 == transported ==
    discovery`` 四向相等。sidecar：``manifest.assets.sidecar`` 只与零槽预像
    复算值比对（BIT-N02 禁直比物理 sha256）；物理 sha256 三端
    （物理==transported==discovery）单独比对；另复核信封槽位内嵌的
    manifest canonical bytes 与传入 manifest 逐字节一致（预像域只绑定
    信封结构，槽位内容的 tamper-evidence 由内容复核承担）。
    """

    validated = validate_base_bundle_manifest(manifest)
    observations = {
        "physical": dict(physical_assets),
        "transported": _require_digest_group(transported_assets, field="transported_assets"),
        "discovery": dict(discovery_report),
    }
    conflicts: list[str] = []
    for name in ASSET_FIELDS:
        if name == "sidecar":
            continue
        reference = validated["assets"][name]
        for source, values in observations.items():
            if values.get(name) != reference:
                conflicts.append(f"QUADRUPLE-{name.upper()}-MISMATCH:{source}")
    preimage = sidecar_preimage_digest(physical_sidecar_envelope)
    if validated["assets"]["sidecar"] != preimage:
        conflicts.append("SIDECAR-PREIMAGE-MISMATCH:manifest-assets-vs-zero-slotted-envelope")
    manifest_len = int.from_bytes(physical_sidecar_envelope[:SIDECAR_ENVELOPE_HEADER_SIZE], "big")
    embedded = physical_sidecar_envelope[
        SIDECAR_ENVELOPE_HEADER_SIZE : SIDECAR_ENVELOPE_HEADER_SIZE + manifest_len
    ]
    if embedded != canonical_bytes(validated):
        conflicts.append("SIDECAR-ENVELOPE-CONTENT-MISMATCH:embedded-manifest-bytes")
    physical_sidecar = observations["physical"].get("sidecar")
    for source in ("transported", "discovery"):
        if observations[source].get("sidecar") != physical_sidecar:
            conflicts.append(f"QUADRUPLE-SIDECAR-MISMATCH:{source}")
    return tuple(sorted(conflicts))
