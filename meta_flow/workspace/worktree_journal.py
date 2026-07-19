"""外置、追加式 worktree intent journal。

记录只有完成同目录临时写、file fsync、atomic replace、parent-dir fsync、
readback 和 checksum/chain 校验后才会返回。调用方必须在取得 sealed
``DurableIntent`` 后才可执行 Git mutation。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import BinaryIO

from meta_flow.workspace.worktree_capacity import CalibrationEvidence, CapacityProof

_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class JournalError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


class JournalFileOps:
    """可注入故障的最小文件系统适配层。"""

    def checkpoint(self, name: str) -> None:
        del name

    def open_exclusive(self, path: Path) -> BinaryIO:
        return path.open("x+b")

    def fsync_file(self, handle: BinaryIO) -> None:
        os.fsync(handle.fileno())

    def replace(self, source: Path, destination: Path) -> None:
        os.replace(source, destination)

    def fsync_directory(self, directory: Path) -> None:
        flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        descriptor = os.open(directory, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def read_bytes(self, path: Path) -> bytes:
        return path.read_bytes()


@dataclass(frozen=True)
class DurableRecord:
    sequence: int
    phase: str
    payload: dict[str, object]
    previous_record_ref: str | None
    previous_record_digest: str | None
    record_digest: str
    path: Path


@dataclass(frozen=True)
class DurableIntent:
    operation_id: str
    attempt_id: str
    intent_record: DurableRecord
    seal_record: DurableRecord
    sealed: bool


@dataclass(frozen=True)
class JournalScan:
    decision: str
    reason: str
    records: tuple[DurableRecord, ...]
    durable_intent: DurableIntent | None


@dataclass(frozen=True)
class JournalOwner:
    schema_version: int
    project_id: str
    repository_id: str
    sibling_root_digest: str
    target_path_digest: str
    owner_digest: str


class WorktreeJournalSession:
    """在同一个 project lock 内完成证明、意图、mutation 与终态记录。"""

    def __init__(self, journal: WorktreeJournal) -> None:
        self._journal = journal

    def scan_attempt(self, operation_id: str, attempt_id: str) -> JournalScan:
        return self._journal._scan_attempt_unlocked(operation_id, attempt_id)

    def persist_phase(
        self,
        operation_id: str,
        attempt_id: str,
        phase: str,
        payload: dict[str, object],
    ) -> DurableRecord:
        return self._journal._persist_phase_unlocked(operation_id, attempt_id, phase, payload)

    def load_calibration(self, profile_digest: str) -> CalibrationEvidence:
        return self._journal._load_calibration_unlocked(profile_digest)


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _record_digest(payload: dict[str, object]) -> str:
    unsigned = {key: value for key, value in payload.items() if key != "record_digest"}
    return hashlib.sha256(_canonical_bytes(unsigned)).hexdigest()


def _document_digest(payload: dict[str, object], digest_field: str) -> str:
    unsigned = {key: value for key, value in payload.items() if key != digest_field}
    return hashlib.sha256(_canonical_bytes(unsigned)).hexdigest()


def _safe_token(value: str, field: str) -> str:
    if not _SAFE_TOKEN.fullmatch(value):
        raise JournalError("journal_identity_invalid", f"{field} is not a safe token")
    return value


class WorktreeJournal:
    def __init__(
        self,
        *,
        store_root: Path,
        target_path: Path,
        project_id: str,
        repository_id: str,
        file_ops: JournalFileOps | None = None,
    ) -> None:
        self.store_root = store_root.resolve(strict=False)
        self.target_path = target_path.resolve(strict=False)
        self.project_id = _safe_token(project_id, "project_id")
        self.repository_id = _safe_token(repository_id, "repository_id")
        self.sibling_root = self.target_path.parent
        self.file_ops = file_ops or JournalFileOps()
        if self.store_root == self.target_path or self.target_path in self.store_root.parents:
            raise JournalError(
                "journal_inside_target",
                "durable journal must be outside the target worktree",
            )

    def attempt_path(self, operation_id: str, attempt_id: str) -> Path:
        operation_id = _safe_token(operation_id, "operation_id")
        attempt_id = _safe_token(attempt_id, "attempt_id")
        return self.store_root / "operations" / operation_id / attempt_id

    @contextmanager
    def project_lock(self) -> Iterator[None]:
        """持有 OS handle lock；不按时间戳偷取所谓 stale lock。"""

        self.store_root.mkdir(parents=True, exist_ok=True)
        lock_path = self.store_root / "project.lock"
        handle = lock_path.open("a+b")
        backend = ""
        try:
            if os.name == "posix":
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                backend = "fcntl"
            elif os.name == "nt":
                import msvcrt

                if lock_path.stat().st_size == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                backend = "msvcrt"
            else:
                raise OSError("unsupported project-lock backend")
        except (OSError, ImportError) as error:
            handle.close()
            raise JournalError("lock_unavailable", str(error)) from error
        try:
            self._ensure_owner_unlocked()
            yield
        finally:
            try:
                if backend == "fcntl":
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                elif backend == "msvcrt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            finally:
                handle.close()

    @contextmanager
    def operation_session(self) -> Iterator[WorktreeJournalSession]:
        """把 mutation 前重验、mutation 与终态记录串在同一项目锁内。"""

        with self.project_lock():
            yield WorktreeJournalSession(self)

    def _owner_payload(self) -> dict[str, object]:
        sibling_digest = hashlib.sha256(self.sibling_root.as_posix().encode("utf-8")).hexdigest()
        target_digest = hashlib.sha256(self.target_path.as_posix().encode("utf-8")).hexdigest()
        payload: dict[str, object] = {
            "schema_version": 1,
            "project_id": self.project_id,
            "repository_id": self.repository_id,
            "sibling_root_digest": sibling_digest,
            "target_path_digest": target_digest,
            "owner_digest": "",
        }
        payload["owner_digest"] = _document_digest(payload, "owner_digest")
        return payload

    def _parse_owner(self, document: object) -> JournalOwner:
        if not isinstance(document, dict):
            raise JournalError("journal_owner_invalid", "owner document must be a mapping")
        expected = self._owner_payload()
        if document.get("owner_digest") != _document_digest(document, "owner_digest"):
            raise JournalError("journal_owner_invalid", "owner digest mismatch")
        if any(document.get(key) != value for key, value in expected.items()):
            raise JournalError("journal_owner_mismatch", "journal owner does not match target")
        return JournalOwner(
            schema_version=1,
            project_id=self.project_id,
            repository_id=self.repository_id,
            sibling_root_digest=str(document["sibling_root_digest"]),
            target_path_digest=str(document["target_path_digest"]),
            owner_digest=str(document["owner_digest"]),
        )

    def _ensure_owner_unlocked(self) -> JournalOwner:
        owner_path = self.store_root / "owner.json"
        if owner_path.exists():
            try:
                return self._parse_owner(json.loads(self.file_ops.read_bytes(owner_path)))
            except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
                raise JournalError("journal_owner_invalid", str(error)) from error
        document = self._owner_payload()
        self._persist_json_document(
            owner_path, document, create_only=True, checkpoint_prefix="owner_"
        )
        return self._parse_owner(document)

    def _validate_owner_readonly(self) -> None:
        owner_path = self.store_root / "owner.json"
        if not owner_path.exists():
            raise JournalError("journal_owner_missing", "owner.json is required")
        try:
            self._parse_owner(json.loads(self.file_ops.read_bytes(owner_path)))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
            raise JournalError("journal_owner_invalid", str(error)) from error

    def _translate_error(self, error: OSError, stage: str) -> JournalError:
        if error.errno == getattr(os, "EXDEV", 18):
            return JournalError("cross_device_store", str(error))
        if error.errno == getattr(os, "ENOSPC", 28):
            return JournalError("journal_enospc", str(error))
        if error.errno in {getattr(os, "EACCES", 13), getattr(os, "EPERM", 1)}:
            return JournalError("journal_eacces", str(error))
        codes = {
            "file_fsync": "journal_fsync_failed",
            "replace": "journal_replace_failed",
            "dir_fsync": "journal_dir_fsync_failed",
            "readback": "journal_readback_failed",
        }
        return JournalError(codes.get(stage, "journal_write_failed"), str(error))

    def _persist_json_document(
        self,
        final: Path,
        document: dict[str, object],
        *,
        create_only: bool,
        checkpoint_prefix: str = "",
    ) -> None:
        if create_only and final.exists():
            raise JournalError("journal_record_exists", f"document already exists: {final.name}")
        encoded = _canonical_bytes(document)
        final.parent.mkdir(parents=True, exist_ok=True)
        temp = final.parent / f".{final.name}.{uuid.uuid4().hex}.tmp"
        stage = "temp_open"
        try:
            self.file_ops.checkpoint(f"{checkpoint_prefix}temp_open_eacces")
            self.file_ops.checkpoint(f"{checkpoint_prefix}temp_open")
            with self.file_ops.open_exclusive(temp) as handle:
                stage = "temp_write"
                self.file_ops.checkpoint(f"{checkpoint_prefix}temp_write_enospc")
                self.file_ops.checkpoint(f"{checkpoint_prefix}temp_write")
                handle.write(encoded)
                stage = "file_flush"
                self.file_ops.checkpoint(f"{checkpoint_prefix}file_flush")
                handle.flush()
                stage = "file_fsync"
                self.file_ops.checkpoint(f"{checkpoint_prefix}file_fsync")
                self.file_ops.fsync_file(handle)
                stage = "after_file_fsync"
                self.file_ops.checkpoint(f"{checkpoint_prefix}after_file_fsync")
            stage = "replace"
            self.file_ops.checkpoint(f"{checkpoint_prefix}replace_cross_device")
            self.file_ops.checkpoint(f"{checkpoint_prefix}replace")
            self.file_ops.replace(temp, final)
            stage = "dir_fsync"
            self.file_ops.checkpoint(f"{checkpoint_prefix}dir_fsync")
            self.file_ops.fsync_directory(final.parent)
            stage = "readback"
            self.file_ops.checkpoint(f"{checkpoint_prefix}readback")
            readback = self.file_ops.read_bytes(final)
        except OSError as error:
            raise self._translate_error(error, stage) from error
        finally:
            if temp.exists():
                try:
                    temp.unlink()
                except OSError:
                    pass
        if readback != encoded:
            raise JournalError(
                "journal_readback_failed", "readback bytes differ from committed document"
            )

    def _persist_record(self, directory: Path, document: dict[str, object]) -> DurableRecord:
        sequence = int(document["sequence"])
        phase = str(document["phase"])
        normalized_phase = phase.lower().replace("_", "-")
        final = directory / f"{sequence:06d}-{normalized_phase}.json"
        if final.exists():
            raise JournalError("journal_record_exists", f"record already exists: {final.name}")
        document = dict(document)
        document["record_digest"] = _record_digest(document)
        self._persist_json_document(final, document, create_only=True)
        readback = self.file_ops.read_bytes(final)
        try:
            decoded = json.loads(readback)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise JournalError(
                "journal_readback_failed", "readback is not canonical JSON"
            ) from error
        if not isinstance(decoded, dict) or decoded.get("record_digest") != _record_digest(decoded):
            raise JournalError("journal_readback_failed", "readback checksum mismatch")
        return DurableRecord(
            sequence=sequence,
            phase=phase,
            payload=dict(document["payload"]),
            previous_record_ref=document.get("previous_record_ref"),  # type: ignore[arg-type]
            previous_record_digest=document.get("previous_record_digest"),  # type: ignore[arg-type]
            record_digest=str(document["record_digest"]),
            path=final,
        )

    def _persist_phase_unlocked(
        self,
        operation_id: str,
        attempt_id: str,
        phase: str,
        payload: dict[str, object],
    ) -> DurableRecord:
        directory = self.attempt_path(operation_id, attempt_id)
        scan = self._scan_attempt_unlocked(operation_id, attempt_id)
        sealing_prepared_intent = bool(
            phase == "INTENT_SEAL"
            and scan.reason == "journal_not_durable"
            and scan.records
            and scan.records[-1].phase == "INTENT"
        )
        if scan.records and scan.decision == "BLOCKED" and not sealing_prepared_intent:
            raise JournalError("journal_chain_invalid", "cannot append to an invalid chain")
        previous = scan.records[-1] if scan.records else None
        allowed_next = {
            None: {"CAPACITY_PROOF", "INTENT"},
            "CAPACITY_PROOF": {"INTENT"},
            "INTENT": {"INTENT_SEAL"},
            "INTENT_SEAL": {"OBSERVATION_REQUIRED"},
            "OBSERVATION_REQUIRED": {"FINAL_OBSERVATION"},
            "FINAL_OBSERVATION": set(),
        }
        previous_phase = previous.phase if previous else None
        if phase not in allowed_next.get(previous_phase, set()):
            raise JournalError(
                "journal_phase_invalid",
                f"cannot append {phase} after {previous_phase or 'EMPTY'}",
            )
        document: dict[str, object] = {
            "schema_version": 1,
            "project_id": self.project_id,
            "repository_id": self.repository_id,
            "operation_id": operation_id,
            "attempt_id": attempt_id,
            "sequence": 1 if previous is None else previous.sequence + 1,
            "phase": phase,
            "payload": payload,
            "previous_record_ref": previous.path.name if previous else None,
            "previous_record_digest": previous.record_digest if previous else None,
        }
        return self._persist_record(directory, document)

    def _calibration_path(self, profile_digest: str) -> Path:
        key = hashlib.sha256(profile_digest.encode("utf-8")).hexdigest()
        return self.store_root / "calibrations" / f"{key}.json"

    def _save_calibration_unlocked(self, calibration: CalibrationEvidence) -> Path:
        payload: dict[str, object] = asdict(calibration)
        payload["schema_version"] = 1
        payload["calibration_digest"] = ""
        payload["calibration_digest"] = _document_digest(payload, "calibration_digest")
        path = self._calibration_path(calibration.profile_digest)
        self._persist_json_document(
            path,
            payload,
            create_only=False,
            checkpoint_prefix="calibration_",
        )
        return path

    def save_calibration(self, calibration: CalibrationEvidence) -> Path:
        with self.project_lock():
            return self._save_calibration_unlocked(calibration)

    def _load_calibration_unlocked(self, profile_digest: str) -> CalibrationEvidence:
        path = self._calibration_path(profile_digest)
        try:
            document = json.loads(self.file_ops.read_bytes(path))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
            raise JournalError("calibration_unavailable", str(error)) from error
        if not isinstance(document, dict) or document.get("calibration_digest") != _document_digest(
            document, "calibration_digest"
        ):
            raise JournalError("calibration_invalid", "calibration digest mismatch")
        if document.get("profile_digest") != profile_digest:
            raise JournalError("calibration_invalid", "calibration profile mismatch")
        try:
            return CalibrationEvidence(
                profile_id=str(document["profile_id"]),
                profile_version=str(document["profile_version"]),
                profile_digest=str(document["profile_digest"]),
                status=str(document["status"]),
                false_safe_count=int(document["false_safe_count"]),
                underestimate_count=int(document["underestimate_count"]),
                calibration_ref=(
                    str(document["calibration_ref"])
                    if document.get("calibration_ref") is not None
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise JournalError("calibration_invalid", str(error)) from error

    def load_calibration(self, profile_digest: str) -> CalibrationEvidence:
        self._validate_owner_readonly()
        return self._load_calibration_unlocked(profile_digest)

    def persist_switch_intent(
        self,
        proof: CapacityProof,
        calibration: CalibrationEvidence,
        payload: dict[str, object],
    ) -> DurableIntent:
        """在单一锁内持久化 calibration、proof、intent 与 seal。"""

        with self.operation_session() as session:
            self._save_calibration_unlocked(calibration)
            proof_record = session.persist_phase(
                proof.operation_id,
                proof.attempt_id,
                "CAPACITY_PROOF",
                proof.to_dict(),
            )
            intent_payload = dict(payload)
            intent_payload.update(
                {
                    "capacity_proof_ref": proof_record.path.as_posix(),
                    "capacity_proof_digest": proof.proof_digest,
                    "capacity_record_digest": proof_record.record_digest,
                }
            )
            intent = session.persist_phase(
                proof.operation_id,
                proof.attempt_id,
                "INTENT",
                intent_payload,
            )
            seal = session.persist_phase(
                proof.operation_id,
                proof.attempt_id,
                "INTENT_SEAL",
                {
                    "sealed_record_ref": intent.path.name,
                    "sealed_record_digest": intent.record_digest,
                },
            )
        return DurableIntent(proof.operation_id, proof.attempt_id, intent, seal, True)

    def persist_phase(
        self,
        operation_id: str,
        attempt_id: str,
        phase: str,
        payload: dict[str, object],
    ) -> DurableRecord:
        with self.project_lock():
            return self._persist_phase_unlocked(
                operation_id,
                attempt_id,
                phase,
                payload,
            )

    def persist_intent(
        self,
        operation_id: str,
        attempt_id: str,
        payload: dict[str, object],
    ) -> DurableIntent:
        with self.project_lock():
            intent = self._persist_phase_unlocked(operation_id, attempt_id, "INTENT", payload)
            seal = self._persist_phase_unlocked(
                operation_id,
                attempt_id,
                "INTENT_SEAL",
                {
                    "sealed_record_ref": intent.path.name,
                    "sealed_record_digest": intent.record_digest,
                },
            )
        return DurableIntent(
            operation_id=operation_id,
            attempt_id=attempt_id,
            intent_record=intent,
            seal_record=seal,
            sealed=True,
        )

    def _scan_attempt_unlocked(self, operation_id: str, attempt_id: str) -> JournalScan:
        directory = self.attempt_path(operation_id, attempt_id)
        if not directory.exists():
            return JournalScan("PASS", "empty", (), None)
        parsed: list[DurableRecord] = []
        try:
            paths = sorted(directory.glob("[0-9][0-9][0-9][0-9][0-9][0-9]-*.json"))
            previous: DurableRecord | None = None
            for expected_sequence, path in enumerate(paths, start=1):
                raw = path.read_bytes()
                document = json.loads(raw)
                if not isinstance(document, dict):
                    raise ValueError("record must be a mapping")
                if document.get("schema_version") != 1:
                    raise ValueError("record schema mismatch")
                if document.get("project_id") != self.project_id:
                    raise ValueError("record project mismatch")
                if document.get("repository_id") != self.repository_id:
                    raise ValueError("record repository mismatch")
                if document.get("operation_id") != operation_id:
                    raise ValueError("record operation mismatch")
                if document.get("attempt_id") != attempt_id:
                    raise ValueError("record attempt mismatch")
                sequence = int(document.get("sequence", -1))
                if sequence != expected_sequence:
                    raise ValueError("sequence gap or duplicate")
                if document.get("record_digest") != _record_digest(document):
                    raise ValueError("record checksum mismatch")
                expected_ref = previous.path.name if previous else None
                expected_digest = previous.record_digest if previous else None
                if document.get("previous_record_ref") != expected_ref:
                    raise ValueError("previous record ref mismatch")
                if document.get("previous_record_digest") != expected_digest:
                    raise ValueError("previous record digest mismatch")
                payload = document.get("payload")
                if not isinstance(payload, dict):
                    raise ValueError("record payload must be a mapping")
                previous = DurableRecord(
                    sequence=sequence,
                    phase=str(document.get("phase", "")),
                    payload=payload,
                    previous_record_ref=document.get("previous_record_ref"),
                    previous_record_digest=document.get("previous_record_digest"),
                    record_digest=str(document["record_digest"]),
                    path=path,
                )
                parsed.append(previous)
        except (OSError, ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
            return JournalScan("BLOCKED", "journal_chain_invalid", tuple(parsed), None)

        phases = tuple(record.phase for record in parsed)
        allowed_sequences = {
            (),
            ("CAPACITY_PROOF",),
            ("CAPACITY_PROOF", "INTENT"),
            ("CAPACITY_PROOF", "INTENT", "INTENT_SEAL"),
            ("CAPACITY_PROOF", "INTENT", "INTENT_SEAL", "OBSERVATION_REQUIRED"),
            (
                "CAPACITY_PROOF",
                "INTENT",
                "INTENT_SEAL",
                "OBSERVATION_REQUIRED",
                "FINAL_OBSERVATION",
            ),
            ("INTENT",),
            ("INTENT", "INTENT_SEAL"),
            ("INTENT", "INTENT_SEAL", "OBSERVATION_REQUIRED"),
            ("INTENT", "INTENT_SEAL", "OBSERVATION_REQUIRED", "FINAL_OBSERVATION"),
        }
        if phases not in allowed_sequences:
            return JournalScan("BLOCKED", "journal_phase_invalid", tuple(parsed), None)

        durable_intent: DurableIntent | None = None
        for index, record in enumerate(parsed[:-1]):
            successor = parsed[index + 1]
            if (
                record.phase == "INTENT"
                and successor.phase == "INTENT_SEAL"
                and successor.payload.get("sealed_record_ref") == record.path.name
                and successor.payload.get("sealed_record_digest") == record.record_digest
            ):
                durable_intent = DurableIntent(
                    operation_id=operation_id,
                    attempt_id=attempt_id,
                    intent_record=record,
                    seal_record=successor,
                    sealed=True,
                )
        if any(record.phase == "INTENT" for record in parsed) and durable_intent is None:
            return JournalScan("BLOCKED", "journal_not_durable", tuple(parsed), None)
        return JournalScan("PASS", "journal_valid", tuple(parsed), durable_intent)

    def scan_attempt(self, operation_id: str, attempt_id: str) -> JournalScan:
        if self.store_root.exists():
            try:
                self._validate_owner_readonly()
            except JournalError as error:
                return JournalScan("BLOCKED", error.code, (), None)
        return self._scan_attempt_unlocked(operation_id, attempt_id)
