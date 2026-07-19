"""项目 worktree 的保守容量证明。

该模块只计算和校准容量证据，不执行任何 Git 或文件系统写操作。无法完整
枚举、转换语义未知、校准失效或任一文件系统探针失败时一律 fail closed。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta

MIB = 1024 * 1024
DEFAULT_CAPACITY_FLOOR_BYTES = 512 * MIB
SAFETY_FACTOR_NUMERATOR = 3
SAFETY_FACTOR_DENOMINATOR = 2


def _round_up(value: int, block_size: int) -> int:
    if value < 0 or block_size <= 0:
        raise ValueError("capacity values must be non-negative and block size must be positive")
    return ((value + block_size - 1) // block_size) * block_size


def capacity_required_bytes(upper_bound_bytes: int) -> int:
    """应用 3/2 安全系数和已校准 bounded profile 的 512 MiB floor。"""

    if upper_bound_bytes < 0:
        raise ValueError("upper_bound_bytes must be non-negative")
    profile_required = (
        upper_bound_bytes * SAFETY_FACTOR_NUMERATOR + SAFETY_FACTOR_DENOMINATOR - 1
    ) // SAFETY_FACTOR_DENOMINATOR
    return max(DEFAULT_CAPACITY_FLOOR_BYTES, profile_required)


@dataclass(frozen=True)
class CheckoutEntry:
    path: str
    blob_size: int

    @property
    def encoded_path_length(self) -> int:
        return len(self.path.encode("utf-8"))


@dataclass(frozen=True)
class CheckoutSnapshot:
    profile_id: str
    profile_version: str
    profile_digest: str
    tree_oid: str
    index_digest: str
    sparse_digest: str
    entries: tuple[CheckoutEntry, ...]
    current_index_size: int
    target_index_encoded_size: int
    block_size: int
    enumeration_complete: bool
    transform_safe: bool
    error_reason: str = ""


@dataclass(frozen=True)
class CapacityProbe:
    filesystem_id: str
    available_bytes: int
    block_size: int
    error_reason: str = ""


@dataclass(frozen=True)
class CalibrationEvidence:
    profile_id: str
    profile_version: str
    profile_digest: str
    status: str
    false_safe_count: int
    underestimate_count: int
    calibration_ref: str | None


@dataclass(frozen=True)
class FilesystemCapacityObservation:
    schema_version: str
    profile_id: str
    profile_version: str
    profile_digest: str
    filesystem_id: str
    tree_oid: str
    index_digest: str
    sparse_digest: str
    enumeration_coverage: str
    estimated_checkout_write_bytes: int
    upper_bound_bytes: int
    required_bytes: int
    available_bytes: int
    safety_factor_numerator: int
    safety_factor_denominator: int
    bounded_512_eligible: bool
    calibration_ref: str | None
    false_safe_count: int | None
    underestimate_count: int | None
    decision: str
    reason: str


@dataclass(frozen=True)
class CapacityDecision:
    decision: str
    reason: str
    checkout: FilesystemCapacityObservation
    journal: FilesystemCapacityObservation


@dataclass(frozen=True)
class CapacityProof:
    """一次 mutation attempt 专属、可持久化并可重验的容量证明。"""

    schema_version: str
    project_id: str
    repository_id: str
    operation_id: str
    attempt_id: str
    before_observation_digest: str
    target_ref: str
    target_oid: str
    profile_id: str
    profile_version: str
    profile_digest: str
    calibration_ref: str
    calibration_status: str
    false_safe_count: int
    underestimate_count: int
    checkout_filesystem_id: str
    checkout_available_bytes: int
    checkout_required_bytes: int
    journal_filesystem_id: str
    journal_available_bytes: int
    journal_required_bytes: int
    decision: str
    created_at: str
    expires_at: str
    proof_digest: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> CapacityProof:
        try:
            return cls(
                schema_version=str(value["schema_version"]),
                project_id=str(value["project_id"]),
                repository_id=str(value["repository_id"]),
                operation_id=str(value["operation_id"]),
                attempt_id=str(value["attempt_id"]),
                before_observation_digest=str(value["before_observation_digest"]),
                target_ref=str(value["target_ref"]),
                target_oid=str(value["target_oid"]),
                profile_id=str(value["profile_id"]),
                profile_version=str(value["profile_version"]),
                profile_digest=str(value["profile_digest"]),
                calibration_ref=str(value["calibration_ref"]),
                calibration_status=str(value["calibration_status"]),
                false_safe_count=int(value["false_safe_count"]),
                underestimate_count=int(value["underestimate_count"]),
                checkout_filesystem_id=str(value["checkout_filesystem_id"]),
                checkout_available_bytes=int(value["checkout_available_bytes"]),
                checkout_required_bytes=int(value["checkout_required_bytes"]),
                journal_filesystem_id=str(value["journal_filesystem_id"]),
                journal_available_bytes=int(value["journal_available_bytes"]),
                journal_required_bytes=int(value["journal_required_bytes"]),
                decision=str(value["decision"]),
                created_at=str(value["created_at"]),
                expires_at=str(value["expires_at"]),
                proof_digest=str(value["proof_digest"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("capacity_proof_invalid") from error


def _capacity_proof_digest(value: CapacityProof | dict[str, object]) -> str:
    payload = value.to_dict() if isinstance(value, CapacityProof) else dict(value)
    payload.pop("proof_digest", None)
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_capacity_proof(
    decision: CapacityDecision,
    calibration: CalibrationEvidence,
    *,
    project_id: str,
    repository_id: str,
    operation_id: str,
    attempt_id: str,
    before_observation_digest: str,
    target_ref: str,
    target_oid: str,
    created_at: datetime | None = None,
    ttl: timedelta = timedelta(minutes=5),
) -> CapacityProof:
    """把双文件系统 PASS 结果绑定到一次具体 mutation attempt。"""

    now = (created_at or datetime.now(UTC)).astimezone(UTC)
    if ttl <= timedelta(0):
        raise ValueError("capacity_proof_ttl_invalid")
    if (
        decision.decision != "PASS"
        or decision.checkout.decision != "PASS"
        or decision.journal.decision != "PASS"
    ):
        raise ValueError("capacity_unproven")
    if not _profile_matches(
        CheckoutSnapshot(
            profile_id=decision.checkout.profile_id,
            profile_version=decision.checkout.profile_version,
            profile_digest=decision.checkout.profile_digest,
            tree_oid=decision.checkout.tree_oid,
            index_digest=decision.checkout.index_digest,
            sparse_digest=decision.checkout.sparse_digest,
            entries=(),
            current_index_size=0,
            target_index_encoded_size=0,
            block_size=1,
            enumeration_complete=True,
            transform_safe=True,
        ),
        calibration,
    ):
        raise ValueError("calibration_unproven")
    if not calibration.calibration_ref:
        raise ValueError("calibration_ref_missing")
    proof = CapacityProof(
        schema_version="1",
        project_id=project_id,
        repository_id=repository_id,
        operation_id=operation_id,
        attempt_id=attempt_id,
        before_observation_digest=before_observation_digest,
        target_ref=target_ref,
        target_oid=target_oid.lower(),
        profile_id=decision.checkout.profile_id,
        profile_version=decision.checkout.profile_version,
        profile_digest=decision.checkout.profile_digest,
        calibration_ref=calibration.calibration_ref,
        calibration_status=calibration.status,
        false_safe_count=calibration.false_safe_count,
        underestimate_count=calibration.underestimate_count,
        checkout_filesystem_id=decision.checkout.filesystem_id,
        checkout_available_bytes=decision.checkout.available_bytes,
        checkout_required_bytes=decision.checkout.required_bytes,
        journal_filesystem_id=decision.journal.filesystem_id,
        journal_available_bytes=decision.journal.available_bytes,
        journal_required_bytes=decision.journal.required_bytes,
        decision=decision.decision,
        created_at=now.isoformat(),
        expires_at=(now + ttl).isoformat(),
        proof_digest="",
    )
    return replace(proof, proof_digest=_capacity_proof_digest(proof))


def validate_capacity_proof(
    proof: CapacityProof,
    calibration: CalibrationEvidence,
    *,
    project_id: str,
    repository_id: str,
    operation_id: str,
    attempt_id: str,
    before_observation_digest: str,
    target_ref: str,
    target_oid: str,
    now: datetime | None = None,
) -> tuple[bool, str]:
    """在 mutation 前重验绑定、校准、容量下界与有效期。"""

    current = (now or datetime.now(UTC)).astimezone(UTC)
    try:
        expires_at = datetime.fromisoformat(proof.expires_at).astimezone(UTC)
        created_at = datetime.fromisoformat(proof.created_at).astimezone(UTC)
    except ValueError:
        return False, "capacity_proof_time_invalid"
    expected_identity = (
        proof.schema_version == "1"
        and proof.project_id == project_id
        and proof.repository_id == repository_id
        and proof.operation_id == operation_id
        and proof.attempt_id == attempt_id
        and proof.before_observation_digest == before_observation_digest
        and proof.target_ref == target_ref
        and proof.target_oid == target_oid.lower()
    )
    if not expected_identity:
        return False, "capacity_proof_binding_mismatch"
    if proof.proof_digest != _capacity_proof_digest(proof):
        return False, "capacity_proof_digest_mismatch"
    if current < created_at or current > expires_at:
        return False, "capacity_proof_expired"
    calibration_matches = bool(
        calibration.status == "CALIBRATED"
        and calibration.false_safe_count == 0
        and calibration.underestimate_count == 0
        and calibration.profile_id == proof.profile_id
        and calibration.profile_version == proof.profile_version
        and calibration.profile_digest == proof.profile_digest
        and calibration.calibration_ref == proof.calibration_ref
        and proof.calibration_status == "CALIBRATED"
        and proof.false_safe_count == 0
        and proof.underestimate_count == 0
    )
    if not calibration_matches:
        return False, "calibration_revoked_or_mismatch"
    if (
        proof.decision != "PASS"
        or proof.checkout_available_bytes < proof.checkout_required_bytes
        or proof.journal_available_bytes < proof.journal_required_bytes
        or not proof.checkout_filesystem_id
        or not proof.journal_filesystem_id
    ):
        return False, "capacity_unproven"
    return True, "capacity_proved"


def _profile_matches(snapshot: CheckoutSnapshot, calibration: CalibrationEvidence | None) -> bool:
    return bool(
        calibration is not None
        and calibration.status == "CALIBRATED"
        and calibration.false_safe_count == 0
        and calibration.underestimate_count == 0
        and calibration.profile_id == snapshot.profile_id
        and calibration.profile_version == snapshot.profile_version
        and calibration.profile_digest == snapshot.profile_digest
    )


def _checkout_upper_bound(snapshot: CheckoutSnapshot) -> tuple[int, int]:
    block = snapshot.block_size
    blob_upper = sum(_round_up(entry.blob_size, block) for entry in snapshot.entries)
    # fixed_dirent_header 是显式 profile 常量；任何变化都应改变 profile digest。
    fixed_dirent_header = 256
    metadata_upper = sum(
        _round_up(entry.encoded_path_length + fixed_dirent_header, block)
        for entry in snapshot.entries
    )
    index_upper = 2 * _round_up(
        max(snapshot.current_index_size, snapshot.target_index_encoded_size), block
    )
    largest_blob = max((entry.blob_size for entry in snapshot.entries), default=0)
    temp_upper = _round_up(max(largest_blob, snapshot.target_index_encoded_size), block)
    estimated = blob_upper + index_upper
    return estimated, blob_upper + metadata_upper + index_upper + temp_upper


def _observation(
    *,
    snapshot: CheckoutSnapshot,
    probe: CapacityProbe,
    calibration: CalibrationEvidence | None,
    estimated: int,
    upper: int,
    required: int,
    bounded: bool,
    decision: str,
    reason: str,
    coverage: str,
) -> FilesystemCapacityObservation:
    return FilesystemCapacityObservation(
        schema_version="1",
        profile_id=snapshot.profile_id,
        profile_version=snapshot.profile_version,
        profile_digest=snapshot.profile_digest,
        filesystem_id=probe.filesystem_id,
        tree_oid=snapshot.tree_oid,
        index_digest=snapshot.index_digest,
        sparse_digest=snapshot.sparse_digest,
        enumeration_coverage=coverage,
        estimated_checkout_write_bytes=estimated,
        upper_bound_bytes=upper,
        required_bytes=required,
        available_bytes=max(probe.available_bytes, 0),
        safety_factor_numerator=SAFETY_FACTOR_NUMERATOR,
        safety_factor_denominator=SAFETY_FACTOR_DENOMINATOR,
        bounded_512_eligible=bounded,
        calibration_ref=calibration.calibration_ref if calibration else None,
        false_safe_count=calibration.false_safe_count if calibration else None,
        underestimate_count=calibration.underestimate_count if calibration else None,
        decision=decision,
        reason=reason,
    )


def prove_checkout_capacity(
    snapshot: CheckoutSnapshot,
    *,
    checkout_fs: CapacityProbe,
    journal_fs: CapacityProbe,
    calibration: CalibrationEvidence | None,
    journal_record_bytes: int = 4096,
    journal_record_count: int = 5,
) -> CapacityDecision:
    """分别证明 checkout 与 journal 文件系统，任一未知均整体阻断。"""

    profile_ok = _profile_matches(snapshot, calibration)
    bounded = bool(
        profile_ok
        and snapshot.enumeration_complete
        and snapshot.transform_safe
        and not snapshot.error_reason
        and snapshot.block_size > 0
        and all(entry.blob_size >= 0 and entry.path for entry in snapshot.entries)
    )
    if bounded:
        estimated, upper = _checkout_upper_bound(snapshot)
        checkout_required = capacity_required_bytes(upper)
    else:
        estimated, upper, checkout_required = 0, 0, DEFAULT_CAPACITY_FLOOR_BYTES

    checkout_pass = bool(
        bounded
        and not checkout_fs.error_reason
        and checkout_fs.block_size > 0
        and checkout_fs.available_bytes >= checkout_required
    )
    checkout_reason = "capacity_proved" if checkout_pass else "capacity_unproven"
    checkout = _observation(
        snapshot=snapshot,
        probe=checkout_fs,
        calibration=calibration,
        estimated=estimated,
        upper=upper,
        required=checkout_required,
        bounded=bounded,
        decision="PASS" if checkout_pass else "BLOCKED",
        reason=checkout_reason,
        coverage="complete" if snapshot.enumeration_complete else "incomplete",
    )

    if journal_record_bytes < 0 or journal_record_count <= 0 or journal_fs.block_size <= 0:
        journal_upper = 0
        journal_required = 0
        journal_shape_ok = False
    else:
        per_record = (
            2 * _round_up(journal_record_bytes, journal_fs.block_size) + journal_fs.block_size
        )
        journal_upper = per_record * journal_record_count
        journal_required = (
            journal_upper * SAFETY_FACTOR_NUMERATOR + SAFETY_FACTOR_DENOMINATOR - 1
        ) // SAFETY_FACTOR_DENOMINATOR
        journal_shape_ok = True
    journal_pass = bool(
        bounded
        and journal_shape_ok
        and not journal_fs.error_reason
        and journal_fs.available_bytes >= journal_required
    )
    journal = _observation(
        snapshot=snapshot,
        probe=journal_fs,
        calibration=calibration,
        estimated=journal_upper,
        upper=journal_upper,
        required=journal_required,
        bounded=bounded,
        decision="PASS" if journal_pass else "BLOCKED",
        reason="capacity_proved" if journal_pass else "capacity_unproven",
        coverage="complete" if bounded else "incomplete",
    )

    passed = checkout_pass and journal_pass
    return CapacityDecision(
        decision="PASS" if passed else "BLOCKED",
        reason="capacity_proved" if passed else "capacity_unproven",
        checkout=checkout,
        journal=journal,
    )


def record_capacity_outcome(
    calibration: CalibrationEvidence,
    observation: FilesystemCapacityObservation,
    *,
    actual_write_bytes: int,
    enospc: bool,
) -> CalibrationEvidence:
    """记录 measured oracle；任何低估或 PASS 后 ENOSPC 立即撤销 profile。"""

    if actual_write_bytes < 0:
        raise ValueError("actual_write_bytes must be non-negative")
    underestimated = actual_write_bytes > observation.upper_bound_bytes
    false_safe = observation.decision == "PASS" and enospc
    underestimate_count = calibration.underestimate_count + int(underestimated)
    false_safe_count = calibration.false_safe_count + int(false_safe)
    status = "REVOKED" if underestimated or false_safe else calibration.status
    return replace(
        calibration,
        status=status,
        false_safe_count=false_safe_count,
        underestimate_count=underestimate_count,
    )
