"""S5 policy 与 fixed-locator provider activation receipt。

公开入口不接受 caller path、payload、环境或 process sidecar；receipt 仅报告
candidate qualification，绝不改变 enforce-new writer policy。
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from importlib import resources
from pathlib import Path, PurePosixPath
from typing import Any

from meta_flow.execution_control.contract import ContainerBudgetV1, canonical_digest

FIXED_RECEIPT_REF = "meta_flow/execution_control/provider/activation-receipt-v11.json"
LEGACY_RECEIPT_REFS = (
    "meta_flow/execution_control/provider/activation-receipt-v1.json",
    "meta_flow/execution_control/provider/activation-receipt-v2.json",
    "meta_flow/execution_control/provider/activation-receipt-v3.json",
    "meta_flow/execution_control/provider/activation-receipt-v4.json",
    "meta_flow/execution_control/provider/activation-receipt-v5.json",
    "meta_flow/execution_control/provider/activation-receipt-v6.json",
    "meta_flow/execution_control/provider/activation-receipt-v7.json",
    "meta_flow/execution_control/provider/activation-receipt-v8.json",
    "meta_flow/execution_control/provider/activation-receipt-v9.json",
    "meta_flow/execution_control/provider/activation-receipt-v10.json",
)
PACKAGE_NAME = "meta-flow"
PACKAGE_VERSION = "0.6.5"
POLICY_REVISION = 1
COHORT_REVISION = 1
CONTEXT_REVISION = 1
GENERATOR_IDENTITY = (
    "meta_flow.execution_control.migration:build_provider_activation_receipt:v11"
)
_SELF_EXCLUSION = FIXED_RECEIPT_REF
_SOURCE_OWNERS = frozenset(
    {
        "meta_flow/execution_control/runtime_context.py",
        "meta_flow/execution_control/migration.py",
        "meta_flow/execution_control/consumer_scan.py",
        "meta_flow/execution_control/contract.py",
        "meta_flow/execution_control/admission.py",
        "meta_flow/execution_control/repair_admission.py",
        "meta_flow/work/store.py",
        "meta_flow/work/assurance.py",
        "meta_flow/work/cli.py",
        "meta_flow/work/usage.py",
        "meta_flow/work/usage_admission.py",
        "meta_flow/evolution.py",
        "meta_flow/evolution_cli.py",
    }
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_EVIDENCE_KEYS = frozenset(
    f"{layer}.{part}"
    for layer in ("candidate_targeted", "candidate_compatibility", "candidate_full", "candidate_closure")
    for part in ("profile", "command", "result", "receipt")
)
_FIELDS = frozenset(
    {
        "schema_version", "package_name", "package_version", "policy_revision", "cohort_revision",
        "context_revision", "qualified_source_manifest", "evidence_digests", "generator_identity",
        "qualified_source_exclusions", "qualified_source_set_digest", "receipt_digest",
    }
)


def _receipt_path() -> Path:
    return Path(
        resources.files("meta_flow.execution_control").joinpath(
            "provider/activation-receipt-v11.json"
        )
    )


def _package_root() -> Path:
    return Path(resources.files("meta_flow"))


def _safe_ref(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or any(character in value for character in "\r\n\\")
    ):
        raise ValueError("manifest ref must be a string")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or path.parts[0] != "meta_flow"
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("manifest ref must be safe")
    return path.as_posix()


class UnknownProviderContractError(ValueError):
    """provider receipt 使用了当前 package 不认识的 versioned contract。"""


@dataclass(frozen=True, slots=True)
class ProviderActivationReceiptV1:
    schema_version: int
    package_name: str
    package_version: str
    policy_revision: int
    cohort_revision: int
    context_revision: int
    qualified_source_manifest: tuple[tuple[str, str, int], ...]
    evidence_digests: tuple[tuple[str, str], ...]
    generator_identity: str
    qualified_source_exclusions: tuple[str, ...]
    qualified_source_set_digest: str
    receipt_digest: str

    @staticmethod
    def digest_payload(payload: Mapping[str, object]) -> str:
        value = dict(payload)
        value.pop("receipt_digest", None)
        return canonical_digest(value)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> ProviderActivationReceiptV1:
        if not isinstance(payload, Mapping) or frozenset(payload) != _FIELDS:
            missing = ",".join(sorted(_FIELDS - frozenset(payload))) if isinstance(payload, Mapping) else "*"
            extra = ",".join(sorted(frozenset(payload) - _FIELDS)) if isinstance(payload, Mapping) else "*"
            raise ValueError(f"fields mismatch: missing={missing or '-'}; extra={extra or '-'}")
        if (
            payload["schema_version"] != 1
            or payload["policy_revision"] != POLICY_REVISION
            or payload["cohort_revision"] != COHORT_REVISION
            or payload["context_revision"] != CONTEXT_REVISION
            or payload["package_name"] != PACKAGE_NAME
            or payload["package_version"] != PACKAGE_VERSION
            or payload["generator_identity"] != GENERATOR_IDENTITY
        ):
            raise UnknownProviderContractError("unknown provider schema, policy or package identity")
        manifest = payload["qualified_source_manifest"]
        if not isinstance(manifest, list):
            raise ValueError("qualified_source_manifest must be a list")
        parsed_manifest: list[tuple[str, str, int]] = []
        for item in manifest:
            if not isinstance(item, Mapping) or frozenset(item) != {"ref", "sha256", "bytes"}:
                raise ValueError("manifest item fields mismatch")
            ref, digest, size = _safe_ref(item["ref"]), item["sha256"], item["bytes"]
            if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest) or not isinstance(size, int) or size < 0:
                raise ValueError("manifest item invalid")
            parsed_manifest.append((ref, digest, size))
        refs = tuple(ref for ref, _, _ in parsed_manifest)
        raw_exclusions = payload["qualified_source_exclusions"]
        if not isinstance(raw_exclusions, list):
            raise ValueError("qualified_source_exclusions must be a list")
        exclusions = tuple(_safe_ref(item) for item in raw_exclusions)
        if (
            parsed_manifest != sorted(parsed_manifest)
            or len(refs) != len(set(refs))
            or _SELF_EXCLUSION in refs
            or exclusions != (_SELF_EXCLUSION,)
        ):
            raise ValueError("manifest self/duplicate exclusion invariant failed")
        if set(refs) != _SOURCE_OWNERS:
            raise ValueError("manifest missing qualified source owner")
        evidence = payload["evidence_digests"]
        if not isinstance(evidence, Mapping) or frozenset(evidence) != _EVIDENCE_KEYS or not all(isinstance(value, str) and _SHA256_RE.fullmatch(value) for value in evidence.values()):
            raise ValueError("evidence digests invalid")
        source_set_digest = canonical_digest([{"ref": ref, "sha256": digest, "bytes": size} for ref, digest, size in sorted(parsed_manifest)])
        if payload["qualified_source_set_digest"] != source_set_digest:
            raise ValueError("source set digest drift")
        expected = cls.digest_payload(payload)
        if payload["receipt_digest"] != expected:
            raise ValueError("receipt digest drift")
        return cls(
            1, PACKAGE_NAME, PACKAGE_VERSION, POLICY_REVISION,
            payload["cohort_revision"], payload["context_revision"], tuple(sorted(parsed_manifest)),
            tuple(sorted(evidence.items())), GENERATOR_IDENTITY, exclusions, source_set_digest, expected,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version, "package_name": self.package_name,
            "package_version": self.package_version, "policy_revision": self.policy_revision,
            "cohort_revision": self.cohort_revision, "context_revision": self.context_revision,
            "qualified_source_manifest": [{"ref": ref, "sha256": digest, "bytes": size} for ref, digest, size in self.qualified_source_manifest],
            "evidence_digests": dict(self.evidence_digests), "generator_identity": self.generator_identity,
            "qualified_source_exclusions": list(self.qualified_source_exclusions), "receipt_digest": self.receipt_digest,
            "qualified_source_set_digest": self.qualified_source_set_digest,
        }


@dataclass(frozen=True, slots=True)
class ProviderReceiptLoadV1:
    status: str
    reason_codes: tuple[str, ...]
    receipt: ProviderActivationReceiptV1 | None
    mutation_count: int = 0


def load_provider_activation_receipt() -> ProviderReceiptLoadV1:
    """固定 locator loader，零 public inputs。"""
    path = _receipt_path()
    if not path.is_file():
        return ProviderReceiptLoadV1("MISSING", ("PROVIDER_RECEIPT_MISSING",), None)
    try:
        receipt = ProviderActivationReceiptV1.from_mapping(json.loads(path.read_text(encoding="utf-8")))
    except UnknownProviderContractError:
        return ProviderReceiptLoadV1(
            "BLOCKED", ("PROVIDER_RECEIPT_UNKNOWN_SCHEMA_OR_POLICY",), None
        )
    except ValueError:
        return ProviderReceiptLoadV1("STALE", ("PROVIDER_RECEIPT_STALE",), None)
    except (OSError, json.JSONDecodeError):
        return ProviderReceiptLoadV1("STALE", ("PROVIDER_RECEIPT_STALE",), None)
    for ref, digest, size in receipt.qualified_source_manifest:
        source = _package_root().joinpath(*PurePosixPath(ref).parts[1:])
        try:
            raw = source.read_bytes()
        except OSError:
            return ProviderReceiptLoadV1("STALE", ("PROVIDER_RECEIPT_SOURCE_DRIFT",), None)
        if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
            return ProviderReceiptLoadV1("STALE", ("PROVIDER_RECEIPT_SOURCE_DRIFT",), None)
    return ProviderReceiptLoadV1("CURRENT", (), receipt)


@dataclass(frozen=True, slots=True)
class ExecutionControlPolicyV1:
    effective_writer_mode: str
    budget: ContainerBudgetV1
    candidate_receipt_status: str
    reason_codes: tuple[str, ...]
    mutation_count: int = 0


def _policy_for_receipt(receipt: ProviderReceiptLoadV1) -> ExecutionControlPolicyV1:
    """固定 policy-v1；receipt 仅影响 candidate label。"""
    mode = "blocked" if receipt.status == "BLOCKED" else "enforce-new"
    return ExecutionControlPolicyV1(mode, ContainerBudgetV1.policy_v1(), receipt.status, (), 0)


def current_execution_control_policy() -> ExecutionControlPolicyV1:
    """固定 policy-v1；无 caller override。"""
    return _policy_for_receipt(load_provider_activation_receipt())


@dataclass(frozen=True, slots=True)
class ProviderReceiptMaterializationV1:
    decision: str
    reason_codes: tuple[str, ...]
    receipt_digest: str
    mutation_count: int
    durable_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProviderQualificationEvidenceV1:
    cohort_revision: int
    context_revision: int
    evidence_digests: tuple[tuple[str, str], ...]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> ProviderQualificationEvidenceV1:
        expected = {"cohort_revision", "context_revision", "evidence_digests"}
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ValueError("qualification evidence fields mismatch")
        evidence = payload["evidence_digests"]
        if not isinstance(evidence, Mapping) or frozenset(evidence) != _EVIDENCE_KEYS or not all(
            isinstance(value, str) and _SHA256_RE.fullmatch(value) for value in evidence.values()
        ):
            raise ValueError("qualification evidence digests invalid")
        if (
            payload["cohort_revision"] != COHORT_REVISION
            or payload["context_revision"] != CONTEXT_REVISION
        ):
            raise UnknownProviderContractError("unknown qualification evidence revision")
        return cls(
            COHORT_REVISION,
            CONTEXT_REVISION,
            tuple(sorted(evidence.items())),
        )


def build_provider_qualification_evidence(payload: Mapping[str, Any]) -> ProviderQualificationEvidenceV1:
    """闭合公开 evidence wire；不接受 receipt/path/source manifest。"""
    return ProviderQualificationEvidenceV1.from_mapping(payload)


def _build_receipt(evidence: ProviderQualificationEvidenceV1) -> ProviderActivationReceiptV1:
    manifest: list[dict[str, object]] = []
    root = _package_root()
    for ref in sorted(_SOURCE_OWNERS):
        raw = root.joinpath(*PurePosixPath(ref).parts[1:]).read_bytes()
        manifest.append({"ref": ref, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
    payload: dict[str, object] = {
        "schema_version": 1, "package_name": PACKAGE_NAME, "package_version": PACKAGE_VERSION,
        "policy_revision": POLICY_REVISION,
        "cohort_revision": evidence.cohort_revision, "context_revision": evidence.context_revision,
        "qualified_source_manifest": manifest, "qualified_source_set_digest": canonical_digest(manifest),
        "evidence_digests": dict(evidence.evidence_digests),
        "generator_identity": GENERATOR_IDENTITY,
        "qualified_source_exclusions": [_SELF_EXCLUSION],
    }
    payload["receipt_digest"] = ProviderActivationReceiptV1.digest_payload(payload)
    return ProviderActivationReceiptV1.from_mapping(payload)


def _write_receipt_exclusive(path: Path, rendered: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(rendered)


def _durable_ref(path: Path, package_root: Path) -> str:
    relative = path.relative_to(package_root)
    return PurePosixPath("meta_flow", *relative.parts).as_posix()


def _perform_receipt_create_only(
    capability: object,
    receipt: ProviderActivationReceiptV1,
) -> ProviderReceiptMaterializationV1:
    """唯一 writer；即使被直接调用也必须持有 live capability。"""
    state = _consume_live_capability(capability)
    if state is None:
        return ProviderReceiptMaterializationV1(
            "BLOCKED", ("MATERIALIZATION_CAPABILITY_INVALID_OR_REPLAYED",), "", 0
        )
    path = _receipt_path()
    if _path_preimage_digest(path) != state.target_preimage_digest:
        return ProviderReceiptMaterializationV1(
            "BLOCKED", ("MATERIALIZATION_TARGET_PREIMAGE_DRIFT",), "", 0
        )
    try:
        expected_receipt = _build_receipt(state.evidence)
    except OSError:
        return ProviderReceiptMaterializationV1(
            "BLOCKED", ("SOURCE_MANIFEST_UNAVAILABLE",), "", 0
        )
    if receipt != expected_receipt:
        return ProviderReceiptMaterializationV1(
            "BLOCKED", ("MATERIALIZATION_RECEIPT_BINDING_INVALID",), "", 0
        )
    package_root = _package_root().resolve()
    try:
        path.relative_to(package_root)
    except ValueError:
        return ProviderReceiptMaterializationV1(
            "BLOCKED", ("FIXED_RECEIPT_LOCATOR_INVALID",), receipt.receipt_digest, 0
        )
    rendered = (
        json.dumps(
            receipt.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        + "\n"
    ).encode("utf-8")
    if path.exists() or path.is_symlink():
        try:
            same = not path.is_symlink() and path.read_bytes() == rendered
        except OSError:
            same = False
        return ProviderReceiptMaterializationV1(
            "PASS" if same else "BLOCKED",
            () if same else ("RECEIPT_COLLISION",),
            receipt.receipt_digest,
            0,
        )
    missing_parents: list[Path] = []
    current = path.parent
    while current != package_root:
        if current.exists() or current.is_symlink():
            if not current.is_dir() or current.is_symlink():
                return ProviderReceiptMaterializationV1(
                    "BLOCKED",
                    ("FIXED_RECEIPT_PARENT_INVALID",),
                    receipt.receipt_digest,
                    0,
                )
            break
        missing_parents.append(current)
        current = current.parent
        if package_root not in current.parents and current != package_root:
            return ProviderReceiptMaterializationV1(
                "BLOCKED", ("FIXED_RECEIPT_LOCATOR_INVALID",), receipt.receipt_digest, 0
            )
    created: list[Path] = []
    try:
        for parent in reversed(missing_parents):
            parent.mkdir()
            created.append(parent)
        _write_receipt_exclusive(path, rendered)
        created.append(path)
    except FileExistsError:
        try:
            same = not path.is_symlink() and path.read_bytes() == rendered
        except OSError:
            same = False
        return ProviderReceiptMaterializationV1(
            "PASS" if same else "BLOCKED",
            () if same else ("RECEIPT_COLLISION",),
            receipt.receipt_digest,
            len(created),
            tuple(_durable_ref(item, package_root) for item in created),
        )
    except OSError:
        if path.exists() and path not in created:
            created.append(path)
        return ProviderReceiptMaterializationV1(
            "PARTIAL_MUTATION" if created else "BLOCKED",
            ("RECEIPT_WRITE_FAILED",),
            receipt.receipt_digest,
            len(created),
            tuple(_durable_ref(item, package_root) for item in created),
        )
    return ProviderReceiptMaterializationV1(
        "PASS",
        (),
        receipt.receipt_digest,
        len(created),
        tuple(_durable_ref(item, package_root) for item in created),
    )


@dataclass(frozen=True, slots=True)
class _NativeAuthorityDescriptorV1:
    """单个 activation revision 的闭合 native-authority 身份。"""

    revision: int
    cp7_revision: int
    project_id: str
    cr_id: str
    story_id: str
    contract_id: str
    dispatch_contract_id: str
    scanner_contract_id: str
    final_manifest_contract_id: str
    checkpoint_event_id: str
    checkpoint_event_type: str
    authorization_ref: str
    context_ref: str
    evidence_ref: str
    return_ref: str
    cp7_result_ref: str
    checkpoint_ledger_ref: str


_NATIVE_AUTHORITY_V11 = _NativeAuthorityDescriptorV1(
    revision=11,
    cp7_revision=1,
    project_id="meta-flow",
    cr_id="CR-077",
    story_id="STORY-CR077-S04",
    contract_id="CR077-PROVIDER-ACTIVATION-RECEIPT-V11-MATERIALIZATION",
    dispatch_contract_id="CR077-PROVIDER-ACTIVATION-RECEIPT-V11-DISPATCH",
    scanner_contract_id=(
        "CR077-PROVIDER-ACTIVATION-RECEIPT-V11-SCANNER-QUALIFICATION-RECEIPT"
    ),
    final_manifest_contract_id=(
        "CR077-PROVIDER-ACTIVATION-RECEIPT-V11-FINAL-CONSUMER-MANIFEST-RECEIPT"
    ),
    checkpoint_event_id="CP7-CR077-AGGREGATE-RESULT-V1",
    checkpoint_event_type="checkpoint_result",
    authorization_ref=(
        "process/release/"
        "CR-077-PROVIDER-RECEIPT-MATERIALIZATION-AUTHORIZATION-0.6.5.json"
    ),
    context_ref=(
        "process/context/stories/STORY-CR077-S04.CP7.verify-packet.json"
    ),
    evidence_ref="process/evidence/STORY-CR077-S04.CP7.index.json",
    return_ref="process/returns/STORY-CR077-S04.CP7.return.json",
    cp7_result_ref=(
        "process/checks/CP7-STORY-CR077-S04-AGGREGATE.result.json"
    ),
    checkpoint_ledger_ref="process/state/CHECKPOINT-LEDGER.ndjson",
)
MATERIALIZATION_AUTHORIZATION_REF = _NATIVE_AUTHORITY_V11.authorization_ref
_FREEZE_PAYLOAD_FIELDS = frozenset(
    {
        "schema_version",
        "package_name",
        "package_version",
        "receipt_revision",
        "policy_revision",
        "cohort_revision",
        "context_revision",
        "target_ref",
        "generator_identity",
        "qualified_source_exclusions",
        "qualified_source_owner_refs",
        "provider_evidence_digests",
    }
)
_MATERIALIZATION_AUTHORIZATION_FIELDS = frozenset(
    {
        "schema_version",
        "contract_id",
        "project_id",
        "cr_id",
        "story_id",
        "revision",
        "decision",
        "operation",
        "target_ref",
        "release_oid",
        "process_oid",
        "scope_digest",
        "freeze_payload",
        "freeze_payload_digest",
        "cp7_event_id",
        "context_ref",
        "context_sha256",
        "context_digest",
        "cp7_result_ref",
        "cp7_result_sha256",
        "cp7_result_digest",
        "checkpoint_ledger_ref",
        "checkpoint_ledger_sha256",
        "checkpoint_event_digest",
        "return_ref",
        "return_sha256",
        "return_digest",
        "evidence_ref",
        "evidence_sha256",
        "evidence_digest",
        "dispatch_ref",
        "dispatch_sha256",
        "dispatch_digest",
        "scanner_receipt_ref",
        "scanner_receipt_sha256",
        "scanner_qualification_receipt_digest",
        "final_manifest_receipt_ref",
        "final_manifest_receipt_sha256",
        "final_manifest_receipt_digest",
        "provider_evidence_digests",
        "native_chain_digest",
        "authorization_digest",
    }
)


def _safe_process_ref(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("materialization authority ref must be a string")
    ref = value.removeprefix("process/")
    path = PurePosixPath(ref)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("materialization authority ref must be safe")
    return path.as_posix()


def _raw_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class NativeMaterializationAuthorityV1:
    release_oid: str
    process_oid: str
    scope_digest: str
    freeze_payload_digest: str
    cp7_event_id: str
    context_digest: str
    cp7_result_digest: str
    checkpoint_event_digest: str
    return_digest: str
    evidence_digest: str
    dispatch_digest: str
    scanner_receipt_digest: str
    final_manifest_receipt_digest: str
    provider_evidence: ProviderQualificationEvidenceV1
    authorization_digest: str

    @property
    def authority_digest(self) -> str:
        return canonical_digest(
            {
                "scope_digest": self.scope_digest,
                "release_oid": self.release_oid,
                "process_oid": self.process_oid,
                "freeze_payload_digest": self.freeze_payload_digest,
                "cp7_event_id": self.cp7_event_id,
                "context_digest": self.context_digest,
                "cp7_result_digest": self.cp7_result_digest,
                "checkpoint_event_digest": self.checkpoint_event_digest,
                "return_digest": self.return_digest,
                "evidence_digest": self.evidence_digest,
                "dispatch_digest": self.dispatch_digest,
                "scanner_receipt_digest": self.scanner_receipt_digest,
                "final_manifest_receipt_digest": self.final_manifest_receipt_digest,
                "provider_evidence": {
                    "cohort_revision": self.provider_evidence.cohort_revision,
                    "context_revision": self.provider_evidence.context_revision,
                    "evidence_digests": dict(self.provider_evidence.evidence_digests),
                },
                "authorization_digest": self.authorization_digest,
            }
        )


_COMMON_AUTHORITY_FIELDS = frozenset(
    {
        "schema_version",
        "contract_id",
        "project_id",
        "cr_id",
        "story_id",
        "revision",
        "release_oid",
        "process_oid",
        "scope_digest",
        "cp7_event_id",
    }
)


def _closed_payload(
    payload: object, fields: frozenset[str], error_code: str
) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping) or frozenset(payload) != fields:
        raise ValueError(error_code)
    return payload


def _require_sha256(value: object, error_code: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(error_code)
    return value


def _require_oid(value: object, error_code: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError(error_code)
    return value


def _validate_common_authority_fields(
    payload: Mapping[str, Any],
    contract_id: str,
    descriptor: _NativeAuthorityDescriptorV1 = _NATIVE_AUTHORITY_V11,
) -> tuple[str, str, str, str]:
    if (
        payload["schema_version"] != 1
        or payload["contract_id"] != contract_id
        or payload["project_id"] != descriptor.project_id
        or payload["cr_id"] != descriptor.cr_id
        or payload["story_id"] != descriptor.story_id
        or payload["revision"] != descriptor.revision
    ):
        raise ValueError("MATERIALIZATION_NATIVE_IDENTITY_INVALID")
    release_oid = _require_oid(payload["release_oid"], "MATERIALIZATION_NATIVE_OID_INVALID")
    process_oid = _require_oid(payload["process_oid"], "MATERIALIZATION_NATIVE_OID_INVALID")
    scope_digest = _require_sha256(
        payload["scope_digest"], "MATERIALIZATION_NATIVE_SCOPE_INVALID"
    )
    event_id = payload["cp7_event_id"]
    if event_id != descriptor.checkpoint_event_id:
        raise ValueError("MATERIALIZATION_NATIVE_EVENT_INVALID")
    return release_oid, process_oid, scope_digest, event_id


def _validate_freeze_payload(
    value: object,
    provider_evidence_digests: object,
    descriptor: _NativeAuthorityDescriptorV1,
) -> tuple[Mapping[str, Any], str]:
    payload = _closed_payload(
        value, _FREEZE_PAYLOAD_FIELDS, "MATERIALIZATION_FREEZE_PAYLOAD_FIELDS_MISMATCH"
    )
    if (
        payload["schema_version"] != 1
        or payload["package_name"] != PACKAGE_NAME
        or payload["package_version"] != PACKAGE_VERSION
        or payload["receipt_revision"] != descriptor.revision
        or payload["policy_revision"] != POLICY_REVISION
        or payload["cohort_revision"] != COHORT_REVISION
        or payload["context_revision"] != CONTEXT_REVISION
        or payload["target_ref"] != FIXED_RECEIPT_REF
        or payload["generator_identity"] != GENERATOR_IDENTITY
        or payload["qualified_source_exclusions"] != [FIXED_RECEIPT_REF]
        or payload["qualified_source_owner_refs"] != sorted(_SOURCE_OWNERS)
        or payload["provider_evidence_digests"] != provider_evidence_digests
    ):
        raise ValueError("MATERIALIZATION_FREEZE_PAYLOAD_IDENTITY_INVALID")
    return payload, canonical_digest(payload)


def _require_payload_digest(
    payload: Mapping[str, Any], field: str, error_code: str
) -> str:
    actual = _require_sha256(payload[field], error_code)
    expected = canonical_digest({key: value for key, value in payload.items() if key != field})
    if actual != expected:
        raise ValueError(error_code)
    return actual


def _require_same_binding(
    expected: tuple[str, str, str, str], actual: tuple[str, str, str, str]
) -> None:
    if actual != expected:
        raise ValueError("MATERIALIZATION_NATIVE_CROSS_UNIT_BINDING_INVALID")


def _load_closed_json(path: Path, fields: frozenset[str], error_code: str) -> Mapping[str, Any]:
    return _closed_payload(json.loads(path.read_text(encoding="utf-8")), fields, error_code)


_DISPATCH_FIELDS = _COMMON_AUTHORITY_FIELDS | frozenset(
    {
        "decision",
        "agent_id",
        "thread_id",
        "tool_name",
        "codex_agent_name",
        "reasoning_profile",
        "dispatch_trigger",
        "completed_at",
        "dispatch_digest",
    }
)
_SCANNER_RECEIPT_FIELDS = _COMMON_AUTHORITY_FIELDS | frozenset(
    {
        "status",
        "decision",
        "dispatch_ref",
        "dispatch_sha256",
        "dispatch_digest",
        "scanner_callable_ref",
        "scanner_source_ref",
        "scanner_source_digest",
        "scanner_contract_digest",
        "parser_identity",
        "profile_digest",
        "command_identity_digest",
        "source_set_digest",
        "subject_set_digest",
        "edge_set_digest",
        "classification_digest",
        "source_count",
        "subject_count",
        "edge_count",
        "classification_count",
        "static_exit_counters",
        "receipt_digest",
    }
)
_FINAL_MANIFEST_FIELDS = _COMMON_AUTHORITY_FIELDS | frozenset(
    {
        "status",
        "decision",
        "dispatch_ref",
        "dispatch_sha256",
        "dispatch_digest",
        "scanner_receipt_ref",
        "scanner_receipt_sha256",
        "scanner_receipt_digest",
        "validation_receipts",
        "dynamic_exit_counters",
        "receipt_digest",
    }
)
_STATIC_SCANNER_COUNTERS = frozenset(
    {
        "syntax_error_count",
        "unclassified_consumer_count",
        "unclassified_legacy_writer_call_count",
        "unfingerprinted_scanned_or_excluded_path_count",
        "unresolved_exclusion_count",
        "unresolved_path_count",
        "security_call_edge_count",
        "explicit_dispatch_error_count",
    }
)
_DYNAMIC_FINAL_COUNTERS = frozenset(
    {
        "impacted_consumer_failure_count",
        "unresolved_fixture_capability_count",
        "unresolved_consumer_closure_count",
    }
)


def _require_ref_link(
    payload: Mapping[str, Any], prefix: str, expected_ref: str, expected_sha256: str
) -> None:
    if (
        _safe_process_ref(payload[f"{prefix}_ref"]) != expected_ref
        or payload[f"{prefix}_sha256"] != expected_sha256
    ):
        raise ValueError("MATERIALIZATION_NATIVE_REF_BINDING_INVALID")


def _validate_dispatch(
    path: Path, descriptor: _NativeAuthorityDescriptorV1
) -> tuple[Mapping[str, Any], tuple[str, str, str, str], str]:
    payload = _load_closed_json(path, _DISPATCH_FIELDS, "MATERIALIZATION_DISPATCH_FIELDS_MISMATCH")
    binding = _validate_common_authority_fields(
        payload, descriptor.dispatch_contract_id, descriptor
    )
    if (
        payload["decision"] != "COMPLETED"
        or payload["tool_name"] != "spawn_agent"
        or payload["codex_agent_name"] != "meta-qa-critical"
        or payload["reasoning_profile"] != "meta-qa-critical"
        or payload["dispatch_trigger"] != "cp7-candidate-independent-qa"
        or not all(isinstance(payload[field], str) and payload[field] for field in ("agent_id", "thread_id", "completed_at"))
    ):
        raise ValueError("MATERIALIZATION_DISPATCH_SEMANTICS_INVALID")
    return payload, binding, _require_payload_digest(payload, "dispatch_digest", "MATERIALIZATION_DISPATCH_DIGEST_DRIFT")


def _validate_zero_counters(value: object, fields: frozenset[str], error_code: str) -> None:
    payload = _closed_payload(value, fields, error_code)
    if any(type(payload[field]) is not int or payload[field] != 0 for field in fields):
        raise ValueError(error_code)


def _load_native_json(
    path: Path, required_fields: frozenset[str], error_code: str
) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping) or not required_fields.issubset(payload):
        raise ValueError(error_code)
    return payload


_CONTEXT_REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "packet_type",
        "project_id",
        "cr_id",
        "story_id",
        "stage",
        "revision",
        "expected_return_packet",
    }
)
_NATIVE_EVIDENCE_REQUIRED_FIELDS = frozenset(
    {"schema_version", "stage", "revision", "cr_id", "story_id", "return_ref"}
)
_NATIVE_RETURN_REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "packet_type",
        "stage",
        "revision",
        "cr_id",
        "story_id",
        "status",
        "boundary_check",
    }
)
_NATIVE_CP7_RESULT_REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "checkpoint",
        "event_id",
        "revision",
        "cr_id",
        "story_id",
        "context_ref",
        "return_packet_ref",
        "evidence_ref",
        "decision",
        "blockers",
        "check_harness_errors",
    }
)
_NATIVE_LEDGER_FIELDS = frozenset(
    {
        "checked_at",
        "checker_provenance",
        "checkpoint",
        "event_id",
        "event_type",
        "revision",
        "cr_id",
        "story_id",
        "context_ref",
        "result_ref",
        "evidence_ref",
        "decision",
        "dispatch_refs",
        "summary_ref",
        "supersedes_event_id",
        "supersedes_ref",
    }
)


def _load_native_materialization_authority(process_root: Path) -> NativeMaterializationAuthorityV1:
    """加载并闭合验证 activation revision 11 的 native CP7 authority chain。"""

    descriptor = _NATIVE_AUTHORITY_V11
    payload = _load_closed_json(
        process_root / _safe_process_ref(descriptor.authorization_ref),
        _MATERIALIZATION_AUTHORIZATION_FIELDS,
        "MATERIALIZATION_AUTHORITY_FIELDS_MISMATCH",
    )
    binding = _validate_common_authority_fields(
        payload, descriptor.contract_id, descriptor
    )
    if (
        payload["decision"] != "APPROVED"
        or payload["operation"] != "provider-receipt-create-only"
        or payload["target_ref"] != FIXED_RECEIPT_REF
    ):
        raise ValueError("MATERIALIZATION_AUTHORITY_IDENTITY_INVALID")
    _, freeze_payload_digest = _validate_freeze_payload(
        payload["freeze_payload"], payload["provider_evidence_digests"], descriptor
    )
    if payload["freeze_payload_digest"] != freeze_payload_digest:
        raise ValueError("MATERIALIZATION_FREEZE_PAYLOAD_DIGEST_DRIFT")

    raw_links = {
        "context": (payload["context_ref"], payload["context_sha256"]),
        "cp7_result": (payload["cp7_result_ref"], payload["cp7_result_sha256"]),
        "checkpoint_ledger": (
            payload["checkpoint_ledger_ref"],
            payload["checkpoint_ledger_sha256"],
        ),
        "return": (payload["return_ref"], payload["return_sha256"]),
        "evidence": (payload["evidence_ref"], payload["evidence_sha256"]),
        "dispatch": (payload["dispatch_ref"], payload["dispatch_sha256"]),
        "scanner_receipt": (
            payload["scanner_receipt_ref"],
            payload["scanner_receipt_sha256"],
        ),
        "final_manifest_receipt": (
            payload["final_manifest_receipt_ref"],
            payload["final_manifest_receipt_sha256"],
        ),
    }
    fixed_refs = {
        "context": descriptor.context_ref,
        "cp7_result": descriptor.cp7_result_ref,
        "checkpoint_ledger": descriptor.checkpoint_ledger_ref,
        "return": descriptor.return_ref,
        "evidence": descriptor.evidence_ref,
    }
    refs: dict[str, str] = {}
    paths: dict[str, Path] = {}
    raw_digests: dict[str, str] = {}
    for name, (raw_ref, raw_digest) in raw_links.items():
        ref = _safe_process_ref(raw_ref)
        if name in fixed_refs and ref != _safe_process_ref(fixed_refs[name]):
            raise ValueError("MATERIALIZATION_AUTHORITY_FIXED_REF_INVALID")
        digest = _require_sha256(
            raw_digest, "MATERIALIZATION_AUTHORITY_REF_DIGEST_INVALID"
        )
        path = process_root / PurePosixPath(ref)
        if not path.is_file() or _raw_digest(path) != digest:
            raise ValueError("MATERIALIZATION_AUTHORITY_REF_DRIFT")
        refs[name], paths[name], raw_digests[name] = ref, path, digest

    _, dispatch_binding, dispatch_digest = _validate_dispatch(
        paths["dispatch"], descriptor
    )
    _require_same_binding(binding, dispatch_binding)

    scanner = _load_closed_json(
        paths["scanner_receipt"],
        _SCANNER_RECEIPT_FIELDS,
        "MATERIALIZATION_SCANNER_RECEIPT_FIELDS_MISMATCH",
    )
    _require_same_binding(
        binding,
        _validate_common_authority_fields(
            scanner, descriptor.scanner_contract_id, descriptor
        ),
    )
    _require_ref_link(scanner, "dispatch", refs["dispatch"], raw_digests["dispatch"])
    if (
        scanner["dispatch_digest"] != dispatch_digest
        or scanner["status"] != "current"
        or scanner["decision"] != "PASS"
        or scanner["scanner_callable_ref"]
        != "meta_flow.execution_control.consumer_scan.scan_execution_control_consumers"
        or scanner["scanner_source_ref"] != "meta_flow/execution_control/consumer_scan.py"
        or scanner["parser_identity"] != "cpython-ast-python-3.11"
        or any(
            type(scanner[field]) is not int or scanner[field] <= 0
            for field in (
                "source_count",
                "subject_count",
                "edge_count",
                "classification_count",
            )
        )
    ):
        raise ValueError("MATERIALIZATION_SCANNER_RECEIPT_SEMANTICS_INVALID")
    for digest_field in (
        "scanner_source_digest",
        "scanner_contract_digest",
        "profile_digest",
        "command_identity_digest",
        "source_set_digest",
        "subject_set_digest",
        "edge_set_digest",
        "classification_digest",
    ):
        _require_sha256(
            scanner[digest_field], "MATERIALIZATION_SCANNER_RECEIPT_DIGEST_INVALID"
        )
    _validate_zero_counters(
        scanner["static_exit_counters"],
        _STATIC_SCANNER_COUNTERS,
        "MATERIALIZATION_SCANNER_COUNTERS_INVALID",
    )
    scanner_receipt_digest = _require_payload_digest(
        scanner, "receipt_digest", "MATERIALIZATION_SCANNER_RECEIPT_DIGEST_DRIFT"
    )

    final_manifest = _load_closed_json(
        paths["final_manifest_receipt"],
        _FINAL_MANIFEST_FIELDS,
        "MATERIALIZATION_FINAL_MANIFEST_FIELDS_MISMATCH",
    )
    _require_same_binding(
        binding,
        _validate_common_authority_fields(
            final_manifest, descriptor.final_manifest_contract_id, descriptor
        ),
    )
    _require_ref_link(final_manifest, "dispatch", refs["dispatch"], raw_digests["dispatch"])
    _require_ref_link(
        final_manifest,
        "scanner_receipt",
        refs["scanner_receipt"],
        raw_digests["scanner_receipt"],
    )
    if (
        final_manifest["dispatch_digest"] != dispatch_digest
        or final_manifest["scanner_receipt_digest"] != scanner_receipt_digest
        or final_manifest["status"] != "current"
        or final_manifest["decision"] != "PASS"
    ):
        raise ValueError("MATERIALIZATION_FINAL_MANIFEST_SEMANTICS_INVALID")
    validation_receipts = _closed_payload(
        final_manifest["validation_receipts"],
        _EVIDENCE_KEYS,
        "MATERIALIZATION_FINAL_VALIDATION_RECEIPTS_INVALID",
    )
    for value in validation_receipts.values():
        _require_sha256(value, "MATERIALIZATION_FINAL_VALIDATION_RECEIPTS_INVALID")
    _validate_zero_counters(
        final_manifest["dynamic_exit_counters"],
        _DYNAMIC_FINAL_COUNTERS,
        "MATERIALIZATION_FINAL_DYNAMIC_COUNTERS_INVALID",
    )
    final_manifest_digest = _require_payload_digest(
        final_manifest,
        "receipt_digest",
        "MATERIALIZATION_FINAL_MANIFEST_DIGEST_DRIFT",
    )

    context_payload = _load_native_json(
        paths["context"],
        _CONTEXT_REQUIRED_FIELDS,
        "MATERIALIZATION_CONTEXT_FIELDS_MISMATCH",
    )
    if (
        context_payload["schema_version"] != 3
        or context_payload["packet_type"] != "story_verify_packet"
        or context_payload["project_id"] != descriptor.project_id
        or context_payload["cr_id"] != descriptor.cr_id
        or context_payload["story_id"] != descriptor.story_id
        or context_payload["stage"] != "CP7"
        or context_payload["revision"] != descriptor.cp7_revision
        or _safe_process_ref(context_payload["expected_return_packet"])
        != refs["return"]
    ):
        raise ValueError("MATERIALIZATION_CONTEXT_BINDING_INVALID")
    context_digest = canonical_digest(context_payload)

    evidence_payload = _load_native_json(
        paths["evidence"],
        _NATIVE_EVIDENCE_REQUIRED_FIELDS,
        "MATERIALIZATION_EVIDENCE_FIELDS_MISMATCH",
    )
    if (
        evidence_payload["schema_version"] != 1
        or evidence_payload["stage"] != "CP7"
        or evidence_payload["revision"] != descriptor.cp7_revision
        or evidence_payload["cr_id"] != descriptor.cr_id
        or evidence_payload["story_id"] != descriptor.story_id
        or _safe_process_ref(evidence_payload["return_ref"]) != refs["return"]
    ):
        raise ValueError("MATERIALIZATION_EVIDENCE_BINDING_INVALID")
    evidence_digest = canonical_digest(evidence_payload)

    return_payload = _load_native_json(
        paths["return"],
        _NATIVE_RETURN_REQUIRED_FIELDS,
        "MATERIALIZATION_RETURN_FIELDS_MISMATCH",
    )
    boundary = return_payload["boundary_check"]
    if (
        return_payload["schema_version"] != 1
        or return_payload["packet_type"] != "story_return_packet"
        or return_payload["stage"] != "CP7"
        or return_payload["revision"] != descriptor.cp7_revision
        or return_payload["cr_id"] != descriptor.cr_id
        or return_payload["story_id"] != descriptor.story_id
        or return_payload["status"] != "verified_with_risk"
        or not isinstance(boundary, Mapping)
        or boundary.get("allowed_paths_only") is not True
        or boundary.get("release_source_mutation_count") != 0
        or boundary.get("git_mutation_count") != 0
        or boundary.get("checkpoint_ledger_append_count") != 1
    ):
        raise ValueError("MATERIALIZATION_RETURN_BINDING_INVALID")
    return_digest = canonical_digest(return_payload)

    cp7_result = _load_native_json(
        paths["cp7_result"],
        _NATIVE_CP7_RESULT_REQUIRED_FIELDS,
        "MATERIALIZATION_CP7_RESULT_FIELDS_MISMATCH",
    )
    if (
        cp7_result["checkpoint"] != "CP7"
        or cp7_result["event_id"] != descriptor.checkpoint_event_id
        or cp7_result["revision"] != descriptor.cp7_revision
        or cp7_result["cr_id"] != descriptor.cr_id
        or cp7_result["story_id"] != descriptor.story_id
        or cp7_result["decision"] != "PASS_WITH_RISK"
        or cp7_result["blockers"] != []
        or cp7_result["check_harness_errors"] != []
        or _safe_process_ref(cp7_result["context_ref"]) != refs["context"]
        or _safe_process_ref(cp7_result["return_packet_ref"]) != refs["return"]
        or _safe_process_ref(cp7_result["evidence_ref"]) != refs["evidence"]
    ):
        raise ValueError("MATERIALIZATION_CP7_RESULT_NOT_CURRENT_PASS")
    cp7_result_digest = canonical_digest(cp7_result)

    ledger_lines = tuple(
        line
        for line in paths["checkpoint_ledger"].read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    if not ledger_lines:
        raise ValueError("MATERIALIZATION_CHECKPOINT_LEDGER_HEAD_INVALID")
    ledger_events = tuple(json.loads(line) for line in ledger_lines)
    candidate_events = tuple(
        event
        for event in ledger_events
        if isinstance(event, Mapping)
        and event.get("cr_id") == descriptor.cr_id
        and event.get("story_id") == descriptor.story_id
        and event.get("checkpoint") == "CP7"
    )
    if not candidate_events:
        raise ValueError("MATERIALIZATION_CHECKPOINT_LEDGER_HEAD_INVALID")
    head = _closed_payload(
        candidate_events[-1],
        _NATIVE_LEDGER_FIELDS,
        "MATERIALIZATION_CHECKPOINT_LEDGER_EVENT_FIELDS_MISMATCH",
    )
    head_digest = canonical_digest(head)
    if (
        head["event_id"] != descriptor.checkpoint_event_id
        or head["event_type"] != descriptor.checkpoint_event_type
        or head["revision"] != descriptor.cp7_revision
        or head["checkpoint"] != "CP7"
        or head["decision"] != "PASS_WITH_RISK"
        or _safe_process_ref(head["context_ref"]) != refs["context"]
        or _safe_process_ref(head["result_ref"]) != refs["cp7_result"]
        or _safe_process_ref(head["evidence_ref"]) != refs["evidence"]
    ):
        raise ValueError("MATERIALIZATION_CHECKPOINT_LEDGER_HEAD_INVALID")

    evidence = ProviderQualificationEvidenceV1.from_mapping(
        {
            "cohort_revision": COHORT_REVISION,
            "context_revision": CONTEXT_REVISION,
            "evidence_digests": payload["provider_evidence_digests"],
        }
    )
    if dict(evidence.evidence_digests) != validation_receipts:
        raise ValueError("MATERIALIZATION_PROVIDER_EVIDENCE_BINDING_INVALID")
    if (
        payload["cp7_result_digest"] != cp7_result_digest
        or payload["context_digest"] != context_digest
        or payload["checkpoint_event_digest"] != head_digest
        or payload["return_digest"] != return_digest
        or payload["evidence_digest"] != evidence_digest
        or payload["dispatch_digest"] != dispatch_digest
        or payload["scanner_qualification_receipt_digest"] != scanner_receipt_digest
        or payload["final_manifest_receipt_digest"] != final_manifest_digest
    ):
        raise ValueError("MATERIALIZATION_AUTHORITY_NATIVE_DIGEST_BINDING_INVALID")
    native_chain_digest = canonical_digest(
        {
            "release_oid": binding[0],
            "process_oid": binding[1],
            "scope_digest": binding[2],
            "cp7_event_id": binding[3],
            "raw_preimages": raw_digests,
            "typed_digests": {
                "context": context_digest,
                "dispatch": dispatch_digest,
                "scanner_receipt": scanner_receipt_digest,
                "final_manifest_receipt": final_manifest_digest,
                "evidence": evidence_digest,
                "return": return_digest,
                "cp7_result": cp7_result_digest,
                "checkpoint_head": head_digest,
            },
        }
    )
    if payload["native_chain_digest"] != native_chain_digest:
        raise ValueError("MATERIALIZATION_AUTHORITY_NATIVE_CHAIN_DRIFT")
    expected_authorization_digest = canonical_digest(
        {
            "contract_id": descriptor.contract_id,
            "operation": "provider-receipt-create-only",
            "target_ref": FIXED_RECEIPT_REF,
            "cr_id": descriptor.cr_id,
            "story_id": descriptor.story_id,
            "revision": descriptor.revision,
            "release_oid": binding[0],
            "process_oid": binding[1],
            "scope_digest": binding[2],
            "freeze_payload_digest": freeze_payload_digest,
            "native_chain_digest": native_chain_digest,
        }
    )
    if payload["authorization_digest"] != expected_authorization_digest:
        raise ValueError("MATERIALIZATION_AUTHORITY_DIGEST_DRIFT")

    return NativeMaterializationAuthorityV1(
        release_oid=binding[0],
        process_oid=binding[1],
        scope_digest=binding[2],
        freeze_payload_digest=payload["freeze_payload_digest"],
        cp7_event_id=binding[3],
        context_digest=context_digest,
        cp7_result_digest=cp7_result_digest,
        checkpoint_event_digest=head_digest,
        return_digest=return_digest,
        evidence_digest=evidence_digest,
        dispatch_digest=dispatch_digest,
        scanner_receipt_digest=scanner_receipt_digest,
        final_manifest_receipt_digest=final_manifest_digest,
        provider_evidence=evidence,
        authorization_digest=expected_authorization_digest,
    )


def _path_preimage_digest(path: Path) -> str:
    if path.is_symlink():
        return canonical_digest({"kind": "symlink", "target": str(path.readlink())})
    if path.is_file():
        return canonical_digest({"kind": "file", "sha256": _raw_digest(path), "bytes": path.stat().st_size})
    if path.exists():
        return canonical_digest({"kind": "other"})
    return canonical_digest({"kind": "missing"})


@dataclass(frozen=True, slots=True)
class _MaterializationSnapshotV1:
    release_root: Path
    release_identity_digest: str
    process_identity_digest: str
    release_oid: str
    process_oid: str
    dirty_digest: str
    route_digest: str
    target_preimage_digest: str
    authority: NativeMaterializationAuthorityV1

    @property
    def snapshot_digest(self) -> str:
        return canonical_digest(
            {
                "release_identity_digest": self.release_identity_digest,
                "process_identity_digest": self.process_identity_digest,
                "release_oid": self.release_oid,
                "process_oid": self.process_oid,
                "dirty_digest": self.dirty_digest,
                "route_digest": self.route_digest,
                "target_preimage_digest": self.target_preimage_digest,
                "authority_digest": self.authority.authority_digest,
            }
        )


def _snapshot_materialization_inputs(release_root: Path) -> _MaterializationSnapshotV1:
    from meta_flow.execution_control.runtime_context import _repository_facts
    from meta_flow.project.process_route import require_project_process_route

    root = release_root.resolve()
    route = require_project_process_route(root, project_id="meta-flow")
    release_oid, process_oid, dirty_digest, repository_digest = _repository_facts(
        root, route.process_root
    )
    target = _receipt_path().resolve(strict=False)
    if target != root / FIXED_RECEIPT_REF:
        raise ValueError("MATERIALIZATION_TARGET_OUTSIDE_RELEASE")
    authority = _load_native_materialization_authority(route.process_root)
    if authority.release_oid != release_oid or authority.process_oid != process_oid:
        raise ValueError("MATERIALIZATION_NATIVE_OID_BINDING_INVALID")
    return _MaterializationSnapshotV1(
        release_root=root,
        release_identity_digest=canonical_digest(
            {
                "project_id": route.project_id,
                "kind": "release-root",
                "resolved_path": str(root),
            }
        ),
        process_identity_digest=canonical_digest(
            {
                "project_id": route.project_id,
                "kind": "process-root",
                "resolved_path": str(route.process_root.resolve()),
            }
        ),
        release_oid=release_oid,
        process_oid=process_oid,
        dirty_digest=dirty_digest,
        route_digest=canonical_digest(
            {
                "project_id": route.project_id,
                "route_mode": route.route_mode,
                "repository_digest": repository_digest,
            }
        ),
        target_preimage_digest=_path_preimage_digest(target),
        authority=authority,
    )


@dataclass(frozen=True, slots=True)
class ProviderMaterializationPlanV3:
    decision: str
    reason_codes: tuple[str, ...]
    release_identity_digest: str
    process_identity_digest: str
    release_oid: str
    process_oid: str
    dirty_digest: str
    route_digest: str
    scope_digest: str
    authorization_digest: str
    freeze_payload_digest: str
    native_cp7_authority_digest: str
    scanner_qualification_receipt_digest: str
    final_manifest_receipt_digest: str
    provider_evidence_digest: str
    target_preimage_digest: str
    snapshot_digest: str
    plan_digest: str
    mutation_count: int = 0
    _release_root: Path | None = field(default=None, repr=False, compare=False)

    def digest_payload(self) -> dict[str, object]:
        return {
            "schema_version": 3,
            "decision": self.decision,
            "reason_codes": list(self.reason_codes),
            "release_identity_digest": self.release_identity_digest,
            "process_identity_digest": self.process_identity_digest,
            "release_oid": self.release_oid,
            "process_oid": self.process_oid,
            "dirty_digest": self.dirty_digest,
            "route_digest": self.route_digest,
            "scope_digest": self.scope_digest,
            "authorization_digest": self.authorization_digest,
            "freeze_payload_digest": self.freeze_payload_digest,
            "native_cp7_authority_digest": self.native_cp7_authority_digest,
            "scanner_qualification_receipt_digest": self.scanner_qualification_receipt_digest,
            "final_manifest_receipt_digest": self.final_manifest_receipt_digest,
            "provider_evidence_digest": self.provider_evidence_digest,
            "target_preimage_digest": self.target_preimage_digest,
            "snapshot_digest": self.snapshot_digest,
            "mutation_count": self.mutation_count,
        }

    def as_dict(self) -> dict[str, object]:
        return {**self.digest_payload(), "plan_digest": self.plan_digest}


def _blocked_materialization_plan(reason: str) -> ProviderMaterializationPlanV3:
    values = ("",) * 15
    plan = ProviderMaterializationPlanV3(
        "BLOCKED", (reason,), *values, "", 0, None
    )
    return plan


def _plan_from_snapshot(snapshot: _MaterializationSnapshotV1) -> ProviderMaterializationPlanV3:
    authority = snapshot.authority
    evidence_digest = canonical_digest(
        {
            "cohort_revision": authority.provider_evidence.cohort_revision,
            "context_revision": authority.provider_evidence.context_revision,
            "evidence_digests": dict(authority.provider_evidence.evidence_digests),
        }
    )
    plan = ProviderMaterializationPlanV3(
        "READY",
        (),
        snapshot.release_identity_digest,
        snapshot.process_identity_digest,
        snapshot.release_oid,
        snapshot.process_oid,
        snapshot.dirty_digest,
        snapshot.route_digest,
        authority.scope_digest,
        authority.authorization_digest,
        authority.freeze_payload_digest,
        authority.authority_digest,
        authority.scanner_receipt_digest,
        authority.final_manifest_receipt_digest,
        evidence_digest,
        snapshot.target_preimage_digest,
        snapshot.snapshot_digest,
        "",
        0,
        snapshot.release_root,
    )
    return replace(plan, plan_digest=canonical_digest(plan.digest_payload()))


def plan_provider_receipt_materialization(
    release_root: Path,
) -> ProviderMaterializationPlanV3:
    """零写 public plan；不接受 manifest、receipt、digest、PASS 或 capability。"""

    try:
        snapshot = _snapshot_materialization_inputs(release_root)
    except (OSError, ValueError, json.JSONDecodeError):
        return _blocked_materialization_plan("MATERIALIZATION_NATIVE_AUTHORITY_UNAVAILABLE")
    return _plan_from_snapshot(snapshot)


class _MaterializationCapabilityV1:
    __slots__ = ("_nonce",)

    def __init__(self, nonce: str, *, _sentinel: object) -> None:
        if _sentinel is not _CAPABILITY_SENTINEL:
            raise TypeError("MaterializationCapabilityV1 has no public constructor")
        self._nonce = nonce

    def __reduce__(self) -> object:
        raise TypeError("MaterializationCapabilityV1 cannot be serialized")


@dataclass(frozen=True, slots=True)
class _CapabilityStateV1:
    nonce: str
    plan_digest: str
    target_preimage_digest: str
    evidence: ProviderQualificationEvidenceV1


_CAPABILITY_SENTINEL = object()
_LIVE_CAPABILITIES: dict[int, _CapabilityStateV1] = {}
_PROOF_SENTINEL = object()
_LIVE_PROOFS: dict[int, tuple[str, _MaterializationSnapshotV1, ProviderMaterializationPlanV3]] = {}


class FreshMaterializationProofV1:
    """仅 fresh apply 可登记的不可序列化 proof。"""
    __slots__ = ("_nonce",)

    def __init__(self, nonce: str, *, _sentinel: object) -> None:
        if _sentinel is not _PROOF_SENTINEL:
            raise TypeError("FreshMaterializationProofV1 has no public constructor")
        self._nonce = nonce

    def __reduce__(self) -> object:
        raise TypeError("FreshMaterializationProofV1 cannot be serialized")


def _register_fresh_materialization_proof(
    snapshot: _MaterializationSnapshotV1, plan: ProviderMaterializationPlanV3
) -> FreshMaterializationProofV1 | None:
    if (
        type(snapshot) is not _MaterializationSnapshotV1
        or type(plan) is not ProviderMaterializationPlanV3
        or plan.decision != "READY"
        or plan._release_root != snapshot.release_root
        or plan.plan_digest != canonical_digest(plan.digest_payload())
        or plan.plan_digest != _plan_from_snapshot(snapshot).plan_digest
    ):
        return None
    proof = FreshMaterializationProofV1(secrets.token_hex(32), _sentinel=_PROOF_SENTINEL)
    _LIVE_PROOFS[id(proof)] = (proof._nonce, snapshot, plan)
    return proof


def _mint_materialization_capability(
    proof: object,
) -> _MaterializationCapabilityV1 | None:
    if type(proof) is not FreshMaterializationProofV1:
        return None
    state = _LIVE_PROOFS.pop(id(proof), None)
    if state is None or proof._nonce != state[0]:
        return None
    snapshot, plan = state[1], state[2]
    nonce = secrets.token_hex(32)
    capability = _MaterializationCapabilityV1(nonce, _sentinel=_CAPABILITY_SENTINEL)
    _LIVE_CAPABILITIES[id(capability)] = _CapabilityStateV1(
        nonce,
        plan.plan_digest,
        snapshot.target_preimage_digest,
        snapshot.authority.provider_evidence,
    )
    return capability


def _consume_live_capability(capability: object) -> _CapabilityStateV1 | None:
    if type(capability) is not _MaterializationCapabilityV1:
        return None
    state = _LIVE_CAPABILITIES.pop(id(capability), None)
    if state is None or capability._nonce != state.nonce:
        return None
    return state


def _live_capability_state(capability: object) -> _CapabilityStateV1 | None:
    if type(capability) is not _MaterializationCapabilityV1:
        return None
    state = _LIVE_CAPABILITIES.get(id(capability))
    return state if state is not None and capability._nonce == state.nonce else None


def _materialize_provider_activation_receipt_create_only(
    capability: object,
) -> ProviderReceiptMaterializationV1:
    """唯一 gated low-level writer；consume capability 后才允许首次 filesystem write。"""

    state = _live_capability_state(capability)
    if state is None:
        return ProviderReceiptMaterializationV1(
            "BLOCKED", ("MATERIALIZATION_CAPABILITY_INVALID_OR_REPLAYED",), "", 0
        )
    path = _receipt_path()
    if _path_preimage_digest(path) != state.target_preimage_digest:
        return ProviderReceiptMaterializationV1(
            "BLOCKED", ("MATERIALIZATION_TARGET_PREIMAGE_DRIFT",), "", 0
        )
    try:
        receipt = _build_receipt(state.evidence)
    except OSError:
        return ProviderReceiptMaterializationV1(
            "BLOCKED", ("SOURCE_MANIFEST_UNAVAILABLE",), "", 0
        )
    return _perform_receipt_create_only(capability, receipt)


def apply_provider_receipt_materialization(
    plan: ProviderMaterializationPlanV3,
) -> ProviderReceiptMaterializationV1:
    """fresh apply；任一漂移均在 capability mint 与 filesystem mutation 前停止。"""

    if (
        not isinstance(plan, ProviderMaterializationPlanV3)
        or plan.decision != "READY"
        or plan._release_root is None
        or plan.plan_digest != canonical_digest(plan.digest_payload())
    ):
        return ProviderReceiptMaterializationV1(
            "BLOCKED", ("MATERIALIZATION_PLAN_INVALID",), "", 0
        )
    try:
        fresh = _snapshot_materialization_inputs(plan._release_root)
    except (OSError, ValueError, json.JSONDecodeError):
        return ProviderReceiptMaterializationV1(
            "BLOCKED", ("MATERIALIZATION_FRESH_AUTHORITY_UNAVAILABLE",), "", 0
        )
    fresh_plan = _plan_from_snapshot(fresh)
    if fresh_plan.plan_digest != plan.plan_digest:
        return ProviderReceiptMaterializationV1(
            "BLOCKED", ("MATERIALIZATION_FRESH_PREIMAGE_DRIFT",), "", 0
        )
    proof = _register_fresh_materialization_proof(fresh, fresh_plan)
    if proof is None:
        return ProviderReceiptMaterializationV1(
            "BLOCKED", ("MATERIALIZATION_FRESH_PROOF_INVALID",), "", 0
        )
    capability = _mint_materialization_capability(proof)
    if capability is None:
        return ProviderReceiptMaterializationV1(
            "BLOCKED", ("MATERIALIZATION_FRESH_PROOF_INVALID",), "", 0
        )
    return _materialize_provider_activation_receipt_create_only(capability)


def materialize_provider_activation_receipt(
    evidence: ProviderQualificationEvidenceV1,
) -> ProviderReceiptMaterializationV1:
    """历史 public 入口 fail closed；T4 只能经 plan/fresh apply/capability。"""

    del evidence
    return ProviderReceiptMaterializationV1(
        "BLOCKED", ("MATERIALIZATION_APPLY_REQUIRED",), "", 0
    )


__all__ = [
    "ExecutionControlPolicyV1",
    "FIXED_RECEIPT_REF",
    "GENERATOR_IDENTITY",
    "LEGACY_RECEIPT_REFS",
    "NativeMaterializationAuthorityV1",
    "PACKAGE_NAME",
    "PACKAGE_VERSION",
    "ProviderActivationReceiptV1",
    "ProviderMaterializationPlanV3",
    "ProviderQualificationEvidenceV1",
    "ProviderReceiptLoadV1",
    "ProviderReceiptMaterializationV1",
    "UnknownProviderContractError",
    "apply_provider_receipt_materialization",
    "build_provider_qualification_evidence",
    "current_execution_control_policy",
    "load_provider_activation_receipt",
    "materialize_provider_activation_receipt",
    "plan_provider_receipt_materialization",
]
