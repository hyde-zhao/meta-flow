"""Work-init 的持久 target 事务与原生 inspect/recover。

该模块只拥有文件集的 preimage/postimage、manifest 状态和 exact rollback。
Work、Project、Phase、lineage 与 State 的领域语义仍由 ``work.store`` 组合。
"""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any

from meta_flow.execution_control.contract import ExecutionUnitV1, canonical_digest
from meta_flow.project.process_route_adapter import resolve_typed_repository_ref
from meta_flow.state.projection_transaction import atomic_remove_regular_file
from meta_flow.work.model import SuccessorContractV1, TypedRepositoryRefV2
from meta_flow.work.validation_kernel import AdmissionItemV2, DecisionStatus

TRANSACTION_ROOT_REL = Path(".meta-flow-runtime/work-init/transactions")
TERMINAL_STATES = frozenset({"COMMITTED", "RECOVERED"})
TRANSACTION_STATES = frozenset({"PREPARED", "APPLYING", "PARTIAL", *TERMINAL_STATES})
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTITY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MISSING = "missing"


class ExecutionContractAdmissionError(ValueError):
    """init mutation 前的稳定合同拒绝，不泄露物理路径或 payload。"""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ExecutionContractAdmissionV1:
    contract: SuccessorContractV1
    typed_ref: TypedRepositoryRefV2
    file_sha256: str
    mutation_count: int = 0


def _typed_contract_ref(
    value: TypedRepositoryRefV2 | Mapping[str, Any] | str,
) -> TypedRepositoryRefV2:
    if isinstance(value, TypedRepositoryRefV2):
        return value
    try:
        if isinstance(value, Mapping):
            return TypedRepositoryRefV2.from_mapping(value)
        return TypedRepositoryRefV2.from_legacy_ref(value)
    except (TypeError, ValueError) as exc:
        raise ExecutionContractAdmissionError("EXECUTION_CONTRACT_REF_INVALID") from exc


def load_and_validate_execution_contract(
    project_root: Path,
    *,
    ref: TypedRepositoryRefV2 | Mapping[str, Any] | str,
    unit: ExecutionUnitV1,
    transaction_identity: Mapping[str, Any] | None = None,
) -> ExecutionContractAdmissionV1:
    """一次打开合同并校验 ref/digest/revision/root/slice/unit，全程零写。"""

    typed_ref = _typed_contract_ref(ref)
    try:
        path = resolve_typed_repository_ref(project_root, typed_ref)
    except (OSError, ValueError) as exc:
        raise ExecutionContractAdmissionError("EXECUTION_CONTRACT_REF_UNRESOLVED") from exc
    try:
        raw = path.read_bytes()
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise ExecutionContractAdmissionError("EXECUTION_CONTRACT_UNREADABLE") from exc
    if not isinstance(payload, Mapping):
        raise ExecutionContractAdmissionError("EXECUTION_CONTRACT_NOT_OBJECT")
    try:
        contract = SuccessorContractV1.from_mapping(payload)
    except (TypeError, ValueError) as exc:
        code = getattr(exc, "args", ("EXECUTION_CONTRACT_INVALID",))[0]
        stable = code if isinstance(code, str) and code.startswith("EXECUTION_CONTRACT_") else "EXECUTION_CONTRACT_INVALID"
        raise ExecutionContractAdmissionError(stable) from exc
    expected = {
        "contract_revision": unit.revision,
        "root_concept": unit.root_concept,
        "slice_id": unit.slice_id,
        "unit_id": unit.unit_id,
    }
    observed = contract.semantic_payload
    mismatches = sorted(key for key in expected if observed[key] != expected[key])
    if mismatches:
        raise ExecutionContractAdmissionError(
            "EXECUTION_CONTRACT_TUPLE_MISMATCH:" + ",".join(mismatches)
        )
    if contract.payload_digest != unit.contract_digest:
        raise ExecutionContractAdmissionError("EXECUTION_CONTRACT_CALLER_DIGEST_MISMATCH")
    if transaction_identity is not None:
        if set(transaction_identity) != set(expected) or any(
            transaction_identity[key] != expected[key] for key in expected
        ):
            raise ExecutionContractAdmissionError("EXECUTION_CONTRACT_TRANSACTION_TUPLE_MISMATCH")
    return ExecutionContractAdmissionV1(
        contract=contract,
        typed_ref=typed_ref,
        file_sha256=sha256(raw).hexdigest(),
        mutation_count=0,
    )


def build_execution_contract_admission_validator(
    project_root: Path,
    *,
    ref: TypedRepositoryRefV2 | Mapping[str, Any] | str,
    unit: ExecutionUnitV1,
    transaction_identity: Mapping[str, Any] | None = None,
) -> tuple[str, object]:
    """把合同 loader 作为 S01 `AdmissionDecisionV2` 的单一注入 validator。"""

    def validator(_simulations: object) -> tuple[AdmissionItemV2, ...]:
        try:
            load_and_validate_execution_contract(
                project_root,
                ref=ref,
                unit=unit,
                transaction_identity=transaction_identity,
            )
        except ExecutionContractAdmissionError as exc:
            return (
                AdmissionItemV2(
                    "execution-contract",
                    exc.code,
                    DecisionStatus.BLOCKED,
                ),
            )
        return (
            AdmissionItemV2(
                "execution-contract",
                "EXECUTION_CONTRACT_READY",
                DecisionStatus.PASS,
            ),
        )

    return "execution-contract", validator


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _digest(value: bytes | None) -> str:
    return _MISSING if value is None else sha256(value).hexdigest()


def _safe_identity(value: str, *, field: str) -> str:
    if not _IDENTITY_RE.fullmatch(value):
        raise ValueError(f"Work-init transaction {field} is invalid")
    return value


def _safe_ref(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or ".." in path.parts
        or "." in path.parts
        or path.as_posix() != value
    ):
        raise ValueError("Work-init transaction target ref is unsafe")
    return value


def _ensure_plain_directory(path: Path) -> None:
    missing: list[Path] = []
    cursor = path
    while not cursor.exists() and not cursor.is_symlink():
        missing.append(cursor)
        cursor = cursor.parent
    if cursor.is_symlink() or not cursor.is_dir():
        raise ValueError("Work-init transaction directory ancestor is unsafe")
    for directory in reversed(missing):
        directory.mkdir()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_atomic(path: Path, value: bytes) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError(f"Work-init transaction target is not regular: {path}")
    _ensure_plain_directory(path.parent)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.work-init.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if temporary.exists() and not temporary.is_symlink():
            temporary.unlink()


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    _write_atomic(
        path,
        (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )


def _read_target(path: Path) -> bytes | None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError(f"Work-init transaction target is not regular: {path}")
    return path.read_bytes() if path.is_file() else None


def _replace_target(path: Path, value: bytes | None) -> None:
    if value is None:
        atomic_remove_regular_file(path)
    else:
        _write_atomic(path, value)


def _created_directory_refs(
    process_root: Path,
    targets: tuple[WorkInitTransactionTargetV1, ...],
) -> tuple[str, ...]:
    """冻结 target 写入可能创建、事务开始时尚不存在的目录。"""

    root = process_root.resolve()
    created: set[str] = set()
    for target in targets:
        if target.after_bytes is None:
            continue
        parent = PurePosixPath(target.ref).parent
        while parent != PurePosixPath("."):
            ref = _safe_ref(parent.as_posix())
            path = root / ref
            if path.is_symlink():
                raise ValueError(
                    f"Work-init transaction directory ancestor is unsafe: {ref}"
                )
            if path.exists():
                if not path.is_dir():
                    raise ValueError(
                        f"Work-init transaction directory ancestor is unsafe: {ref}"
                    )
                break
            created.add(ref)
            parent = parent.parent
    return tuple(sorted(created, key=lambda item: (len(PurePosixPath(item).parts), item)))


def _remove_created_directories(
    process_root: Path,
    refs: tuple[str, ...],
) -> list[str]:
    """只移除事务创建且仍为空的目录；非空或类型漂移时 fail-closed。"""

    root = process_root.resolve()
    failures: list[str] = []
    for ref in reversed(refs):
        path = root / ref
        try:
            if path.is_symlink() or (path.exists() and not path.is_dir()):
                raise ValueError("created directory is no longer a plain directory")
            if not path.exists():
                continue
            path.rmdir()
            _fsync_directory(path.parent)
        except (OSError, ValueError) as exc:
            failures.append(f"{ref}: {exc}")
    return failures


@dataclass(frozen=True, slots=True)
class WorkInitTransactionTargetV1:
    ref: str
    before_bytes: bytes | None
    after_bytes: bytes | None

    @property
    def before_digest(self) -> str:
        return _digest(self.before_bytes)

    @property
    def after_digest(self) -> str:
        return _digest(self.after_bytes)

    def as_plan_dict(self) -> dict[str, str]:
        return {
            "ref": self.ref,
            "before_digest": self.before_digest,
            "after_digest": self.after_digest,
        }

    def as_manifest_dict(self) -> dict[str, str]:
        return {
            **self.as_plan_dict(),
            "before_bytes_b64": base64.b64encode(self.before_bytes or b"").decode("ascii"),
            "after_bytes_b64": base64.b64encode(self.after_bytes or b"").decode("ascii"),
        }


@dataclass(frozen=True, slots=True)
class WorkInitTransactionReceiptV1:
    decision: str
    transaction_id: str
    operation: str
    work_id: str
    plan_digest: str
    applied_refs: tuple[str, ...]
    recovery_required: bool
    reason_codes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "decision": self.decision,
            "transaction_id": self.transaction_id,
            "operation": self.operation,
            "work_id": self.work_id,
            "plan_digest": self.plan_digest,
            "applied_refs": list(self.applied_refs),
            "mutation_count": len(self.applied_refs),
            "recovery_required": self.recovery_required,
            "reason_codes": list(self.reason_codes),
        }


def build_transaction_target(
    process_root: Path,
    *,
    ref: str,
    after_bytes: bytes | None,
) -> WorkInitTransactionTargetV1:
    safe_ref = _safe_ref(ref)
    return WorkInitTransactionTargetV1(
        safe_ref,
        _read_target(process_root.resolve() / safe_ref),
        after_bytes,
    )


def _transaction_id(
    *,
    operation: str,
    work_id: str,
    plan_digest: str,
    release_oid: str,
    process_oid: str,
    targets: tuple[WorkInitTransactionTargetV1, ...],
) -> str:
    digest = canonical_digest(
        {
            "operation": operation,
            "work_id": work_id,
            "plan_digest": plan_digest,
            "release_oid": release_oid,
            "process_oid": process_oid,
            "targets": [target.as_plan_dict() for target in targets],
        }
    )
    return f"work-init-{digest[:32]}"


def _manifest_path(process_root: Path, transaction_id: str) -> Path:
    return (
        process_root.resolve()
        / TRANSACTION_ROOT_REL
        / _safe_identity(transaction_id, field="transaction_id")
        / "manifest.json"
    )


def _validate_digest(value: object) -> str:
    digest = str(value or "")
    if digest != _MISSING and not _DIGEST_RE.fullmatch(digest):
        raise ValueError("Work-init transaction digest is invalid")
    return digest


def _decode_target(raw: object) -> dict[str, Any]:
    fields = {
        "ref",
        "before_digest",
        "after_digest",
        "before_bytes_b64",
        "after_bytes_b64",
    }
    if not isinstance(raw, Mapping) or set(raw) != fields:
        raise ValueError("Work-init transaction target fields mismatch")
    ref = _safe_ref(str(raw.get("ref") or ""))
    before_digest = _validate_digest(raw.get("before_digest"))
    after_digest = _validate_digest(raw.get("after_digest"))
    try:
        before_encoded = base64.b64decode(
            str(raw.get("before_bytes_b64") or ""), validate=True
        )
        after_encoded = base64.b64decode(
            str(raw.get("after_bytes_b64") or ""), validate=True
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("Work-init transaction target bytes are invalid") from exc
    before = None if before_digest == _MISSING else before_encoded
    after = None if after_digest == _MISSING else after_encoded
    if _digest(before) != before_digest or _digest(after) != after_digest:
        raise ValueError("Work-init transaction target bytes/digest mismatch")
    return {
        "ref": ref,
        "before_digest": before_digest,
        "after_digest": after_digest,
        "before_bytes": before,
        "after_bytes": after,
        "before_bytes_b64": str(raw.get("before_bytes_b64") or ""),
        "after_bytes_b64": str(raw.get("after_bytes_b64") or ""),
    }


def _load_manifest(path: Path) -> dict[str, Any]:
    if path.parent.is_symlink() or path.is_symlink() or not path.is_file():
        raise ValueError("Work-init transaction manifest path is unsafe")
    payload = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "schema_version",
        "kind",
        "transaction_id",
        "operation",
        "work_id",
        "plan_digest",
        "release_oid",
        "process_oid",
        "state",
        "created_at",
        "updated_at",
        "attempted_refs",
        "applied_refs",
        "successor_id",
        "created_directory_refs",
        "targets",
    }
    optional = {"failure", "recovery_failures"}
    if not isinstance(payload, dict) or not required <= set(payload) or set(payload) - required - optional:
        raise ValueError("Work-init transaction manifest fields mismatch")
    transaction_id = _safe_identity(str(payload.get("transaction_id") or ""), field="transaction_id")
    if (
        payload.get("schema_version") != 1
        or payload.get("kind") != "work-init-transaction-v1"
        or transaction_id != path.parent.name
        or payload.get("state") not in TRANSACTION_STATES
        or payload.get("operation") not in {
            "work.init",
            "work.init.recover-legacy-partial",
            "work.scope-amend",
        }
        or not _IDENTITY_RE.fullmatch(str(payload.get("work_id") or ""))
        or not _DIGEST_RE.fullmatch(str(payload.get("plan_digest") or ""))
        or not re.fullmatch(r"[0-9a-f]{40}", str(payload.get("release_oid") or ""))
        or not re.fullmatch(r"[0-9a-f]{40}", str(payload.get("process_oid") or ""))
    ):
        raise ValueError("Work-init transaction manifest identity is invalid")
    raw_targets = payload.get("targets")
    if not isinstance(raw_targets, list) or not raw_targets or len(raw_targets) > 7:
        raise ValueError("Work-init transaction target set is invalid")
    targets = [_decode_target(raw) for raw in raw_targets]
    refs = [target["ref"] for target in targets]
    if len(refs) != len(set(refs)):
        raise ValueError("Work-init transaction target refs are duplicated")
    raw_created_directories = payload.get("created_directory_refs")
    if not isinstance(raw_created_directories, list) or len(
        raw_created_directories
    ) > 16:
        raise ValueError("Work-init transaction created directory refs are invalid")
    created_directory_refs = tuple(
        _safe_ref(str(ref or "")) for ref in raw_created_directories
    )
    if (
        len(created_directory_refs) != len(set(created_directory_refs))
        or created_directory_refs
        != tuple(
            sorted(
                created_directory_refs,
                key=lambda item: (len(PurePosixPath(item).parts), item),
            )
        )
    ):
        raise ValueError("Work-init transaction created directory refs are invalid")
    for field in ("attempted_refs", "applied_refs"):
        value = payload.get(field)
        if not isinstance(value, list) or value != refs[: len(value)]:
            raise ValueError(f"Work-init transaction {field} is invalid")
    if payload["applied_refs"] != payload["attempted_refs"][: len(payload["applied_refs"])]:
        raise ValueError("Work-init transaction applied refs exceed attempted refs")
    return {
        **payload,
        "created_directory_refs": created_directory_refs,
        "targets": targets,
    }


def begin_work_init_transaction(
    process_root: Path,
    *,
    operation: str,
    work_id: str,
    plan_digest: str,
    release_oid: str,
    process_oid: str,
    targets: tuple[WorkInitTransactionTargetV1, ...],
) -> str:
    if not targets or len({target.ref for target in targets}) != len(targets):
        raise ValueError("Work-init transaction requires unique targets")
    created_directory_refs = _created_directory_refs(process_root, targets)
    transaction_id = _transaction_id(
        operation=operation,
        work_id=work_id,
        plan_digest=plan_digest,
        release_oid=release_oid,
        process_oid=process_oid,
        targets=targets,
    )
    path = _manifest_path(process_root, transaction_id)
    if path.exists() or path.is_symlink():
        raise ValueError("Work-init transaction identity was already consumed")
    _ensure_plain_directory(path.parent)
    now = _now()
    payload = {
        "schema_version": 1,
        "kind": "work-init-transaction-v1",
        "transaction_id": transaction_id,
        "operation": operation,
        "work_id": work_id,
        "plan_digest": plan_digest,
        "release_oid": release_oid,
        "process_oid": process_oid,
        "state": "PREPARED",
        "created_at": now,
        "updated_at": now,
        "attempted_refs": [],
        "applied_refs": [],
        "successor_id": "",
        "created_directory_refs": list(created_directory_refs),
        "targets": [target.as_manifest_dict() for target in targets],
    }
    _write_json_atomic(path, payload)
    _load_manifest(path)
    return transaction_id


def apply_work_init_transaction_targets(
    process_root: Path,
    transaction_id: str,
) -> tuple[str, ...]:
    path = _manifest_path(process_root, transaction_id)
    manifest = _load_manifest(path)
    if manifest["state"] != "PREPARED":
        raise ValueError("Work-init transaction is not PREPARED")
    manifest["state"] = "APPLYING"
    manifest["updated_at"] = _now()
    manifest["targets"] = [
        {
            key: value
            for key, value in target.items()
            if key not in {"before_bytes", "after_bytes"}
        }
        for target in manifest["targets"]
    ]
    _write_json_atomic(path, manifest)
    applied: list[str] = []
    for target in _load_manifest(path)["targets"]:
        current = _read_target(process_root.resolve() / target["ref"])
        if _digest(current) != target["before_digest"]:
            raise ValueError(f"Work-init transaction target preimage drift: {target['ref']}")
        manifest = _load_manifest(path)
        manifest["attempted_refs"] = [*manifest["attempted_refs"], target["ref"]]
        manifest["updated_at"] = _now()
        manifest["targets"] = [
            {key: value for key, value in item.items() if key not in {"before_bytes", "after_bytes"}}
            for item in manifest["targets"]
        ]
        _write_json_atomic(path, manifest)
        _replace_target(process_root.resolve() / target["ref"], target["after_bytes"])
        applied.append(target["ref"])
        manifest = _load_manifest(path)
        manifest["applied_refs"] = list(applied)
        manifest["updated_at"] = _now()
        manifest["targets"] = [
            {key: value for key, value in item.items() if key not in {"before_bytes", "after_bytes"}}
            for item in manifest["targets"]
        ]
        _write_json_atomic(path, manifest)
    return tuple(applied)


def commit_work_init_transaction(
    process_root: Path,
    transaction_id: str,
    *,
    successor_id: str,
) -> WorkInitTransactionReceiptV1:
    path = _manifest_path(process_root, transaction_id)
    manifest = _load_manifest(path)
    if manifest["state"] != "APPLYING" or len(manifest["applied_refs"]) != len(manifest["targets"]):
        raise ValueError("Work-init transaction cannot commit an incomplete target set")
    manifest["state"] = "COMMITTED"
    manifest["successor_id"] = successor_id
    manifest["updated_at"] = _now()
    manifest["targets"] = [
        {key: value for key, value in item.items() if key not in {"before_bytes", "after_bytes"}}
        for item in manifest["targets"]
    ]
    _write_json_atomic(path, manifest)
    return WorkInitTransactionReceiptV1(
        "PASS",
        transaction_id,
        str(manifest["operation"]),
        str(manifest["work_id"]),
        str(manifest["plan_digest"]),
        tuple(manifest["applied_refs"]),
        False,
    )


def rollback_work_init_transaction(
    process_root: Path,
    transaction_id: str,
    *,
    failure: str,
) -> WorkInitTransactionReceiptV1:
    path = _manifest_path(process_root, transaction_id)
    manifest = _load_manifest(path)
    failures: list[str] = []
    for target in reversed(manifest["targets"]):
        target_path = process_root.resolve() / target["ref"]
        try:
            current = _read_target(target_path)
            current_digest = _digest(current)
            if current_digest not in {target["before_digest"], target["after_digest"]}:
                raise ValueError("target bytes no longer match transaction generations")
            if current_digest == target["after_digest"]:
                _replace_target(target_path, target["before_bytes"])
        except (OSError, ValueError) as exc:
            failures.append(f"{target['ref']}: {exc}")
    failures.extend(
        _remove_created_directories(
            process_root,
            tuple(manifest["created_directory_refs"]),
        )
    )
    manifest = _load_manifest(path)
    manifest["state"] = "PARTIAL" if failures else "RECOVERED"
    manifest["failure"] = failure
    manifest["recovery_failures"] = failures
    manifest["updated_at"] = _now()
    manifest["targets"] = [
        {key: value for key, value in item.items() if key not in {"before_bytes", "after_bytes"}}
        for item in manifest["targets"]
    ]
    _write_json_atomic(path, manifest)
    return WorkInitTransactionReceiptV1(
        "PARTIAL" if failures else "RECOVERED",
        transaction_id,
        str(manifest["operation"]),
        str(manifest["work_id"]),
        str(manifest["plan_digest"]),
        tuple(manifest["applied_refs"]),
        bool(failures),
        (
            "WORK_INIT_TRANSACTION_APPLY_FAILED",
            *(("WORK_INIT_TRANSACTION_RECOVERY_FAILED",) if failures else ()),
        ),
    )


def recover_work_init_transaction(
    process_root: Path,
    transaction_id: str,
    *,
    expected_plan_digest: str,
    release_oid: str,
    process_oid: str,
) -> WorkInitTransactionReceiptV1:
    """按 manifest 身份与当前仓库 OID 恢复一个未终结 Work-init 事务。"""

    path = _manifest_path(process_root, transaction_id)
    manifest = _load_manifest(path)
    if manifest["state"] in TERMINAL_STATES:
        raise ValueError("Work-init transaction is already terminal")
    if (
        manifest["plan_digest"] != expected_plan_digest
        or manifest["release_oid"] != release_oid
        or manifest["process_oid"] != process_oid
    ):
        raise ValueError("Work-init transaction recovery identity drifted")
    return rollback_work_init_transaction(
        process_root,
        transaction_id,
        failure="native Work-init transaction recovery",
    )


def inspect_work_init_transactions(
    process_root: Path,
    *,
    work_id: str = "",
) -> dict[str, Any]:
    root = process_root.resolve()
    transaction_root = root / TRANSACTION_ROOT_REL
    transactions: list[dict[str, Any]] = []
    errors: list[str] = []
    if transaction_root.is_symlink() or (
        transaction_root.exists() and not transaction_root.is_dir()
    ):
        errors.append("Work-init transaction root is unsafe")
    elif transaction_root.is_dir():
        for path in sorted(transaction_root.glob("*/manifest.json")):
            try:
                manifest = _load_manifest(path)
                if work_id and manifest["work_id"] != work_id:
                    continue
                if manifest["state"] not in TERMINAL_STATES:
                    errors.append(
                        f"unresolved Work-init transaction: {manifest['transaction_id']}:{manifest['state']}"
                    )
                transactions.append(
                    {
                        "transaction_id": manifest["transaction_id"],
                        "operation": manifest["operation"],
                        "work_id": manifest["work_id"],
                        "plan_digest": manifest["plan_digest"],
                        "release_oid": manifest["release_oid"],
                        "process_oid": manifest["process_oid"],
                        "state": manifest["state"],
                        "created_directory_refs": list(
                            manifest["created_directory_refs"]
                        ),
                        "target_refs": [target["ref"] for target in manifest["targets"]],
                        "manifest_ref": path.relative_to(root).as_posix(),
                    }
                )
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"invalid Work-init transaction {path}: {exc}")
    return {
        "schema_version": 1,
        "kind": "WorkInitTransactionInspectionV1",
        "decision": "BLOCKED" if errors else "PASS",
        "transactions": transactions,
        "unresolved_count": len(errors),
        "errors": errors,
        "mutation_count": 0,
    }


__all__ = [
    "TRANSACTION_ROOT_REL",
    "WorkInitTransactionReceiptV1",
    "WorkInitTransactionTargetV1",
    "apply_work_init_transaction_targets",
    "begin_work_init_transaction",
    "build_transaction_target",
    "commit_work_init_transaction",
    "inspect_work_init_transactions",
    "recover_work_init_transaction",
    "rollback_work_init_transaction",
]
