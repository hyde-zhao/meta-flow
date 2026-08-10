"""CR termination 私有 coordination journal。

该模块只拥有 Git common-dir 下的私有事务证据，不拥有 CR/Work/STATE
等领域语义。所有记录均为 closed schema、append-only、hash-chained。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any

JOURNAL_SCHEMA_VERSION = 2
OWNER_IDENTITY = "meta-flow.workflow.cr_termination/coordination-journal/v2"
JOURNAL_REL = Path("meta-flow") / "cr-termination-v2"

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_FAILURE_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_FIXED_ROLES = {
    "formal_cr",
    "work",
    "project",
    "phase",
    "state",
    "current_view",
    "summary",
    "ledger",
    "index",
}
_RECORD_COMMON_FIELDS = {
    "schema_version",
    "sequence",
    "transaction_id",
    "owner_identity",
    "phase",
    "previous_record_digest",
    "payload",
    "record_digest",
}
_OWNER_FIELDS = {
    "schema_version",
    "owner_identity",
    "project_id",
    "process_git_common_dir_identity",
    "owner_digest",
}
_TARGET_FIELDS = {
    "sequence",
    "role",
    "ref",
    "before_exists",
    "before_digest",
    "after_digest",
    "before_text",
    "after_text",
}
_PHASE_PAYLOAD_FIELDS = {
    "PREPARED": {
        "authorization_id",
        "authority_digest",
        "source_tuple_digest",
        "target_set_digest",
        "target_preimage_digest",
        "mutation_allowlist_digest",
        "preservation_digest",
        "plan_digest",
        "targets",
    },
    "ATTEMPTED": {
        "target_sequence",
        "role",
        "ref",
        "before_exists",
        "before_digest",
        "after_digest",
    },
    "APPLIED": {
        "attempted_record_digest",
        "role",
        "ref",
        "observed_after_digest",
    },
    "RESTORED": {
        "attempted_record_digest",
        "role",
        "ref",
        "observed_before_digest",
        "restore_mode",
    },
    "ABORTED": {"reason", "domain_mutation_count"},
    "COMMITTED": {
        "attempted_count",
        "applied_count",
        "domain_mutation_count",
        "result_digest",
    },
    "RECOVERED": {"attempted_count", "restored_count", "already_before_count"},
    "PARTIAL": {"failure_code", "target_ref"},
}
_TERMINAL_PHASES = {"ABORTED", "COMMITTED", "RECOVERED", "PARTIAL"}
_PROMOTABLE_PHASES = {"ABORTED", "COMMITTED", "RECOVERED"}
_ALLOWED_TRANSITIONS = {
    "PREPARED": {"ATTEMPTED", "ABORTED", "COMMITTED"},
    "ATTEMPTED": {"APPLIED", "RESTORED", "RECOVERED", "PARTIAL"},
    "APPLIED": {"ATTEMPTED", "RESTORED", "COMMITTED", "RECOVERED", "PARTIAL"},
    "RESTORED": {"RESTORED", "RECOVERED", "PARTIAL"},
}


class JournalBlocked(RuntimeError):
    """私有 journal 不能安全读取或推进。"""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _require_exact_fields(payload: Mapping[str, Any], expected: set[str], subject: str) -> None:
    actual = set(payload)
    if actual != expected:
        raise JournalBlocked(
            f"{subject} fields mismatch: missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def _require_safe_id(value: Any, subject: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise JournalBlocked(f"{subject} is not one safe ID")
    return value


def _require_digest(value: Any, subject: str, *, allow_empty: bool = False) -> str:
    if allow_empty and value == "":
        return ""
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise JournalBlocked(f"{subject} is not one SHA-256 digest")
    return value


def _require_nonnegative_int(value: Any, subject: str, *, positive: bool = False) -> int:
    minimum = 1 if positive else 0
    if type(value) is not int or value < minimum:
        qualifier = "positive" if positive else "non-negative"
        raise JournalBlocked(f"{subject} must be one {qualifier} integer")
    return value


def _require_role(value: Any, subject: str) -> str:
    if not isinstance(value, str) or value not in _FIXED_ROLES:
        raise JournalBlocked(f"{subject} is outside the fixed role set")
    return value


def _require_process_ref(value: Any, subject: str) -> str:
    if not isinstance(value, str) or any(character in value for character in "\r\n\\"):
        raise JournalBlocked(f"{subject} is not one process logical ref")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or path.parts[0] != "process"
        or len(path.parts) < 2
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise JournalBlocked(f"{subject} is not one process logical ref")
    return path.as_posix()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _ensure_directory_chain(root: Path, parts: tuple[str, ...]) -> Path:
    current = root
    root_info = os.lstat(root)
    if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
        raise JournalBlocked("journal root anchor is not a plain directory")
    for part in parts:
        current /= part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            current.mkdir()
            _fsync_directory(current.parent)
            info = os.lstat(current)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise JournalBlocked("journal directory chain contains a non-directory or symlink")
    return current


def _require_plain_directory(path: Path) -> None:
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise JournalBlocked("journal parent is not a plain directory")


def _read_regular_bytes(path: Path) -> bytes:
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise JournalBlocked(f"journal leaf is not a regular file: {path.name}")
    flags = os.O_RDONLY
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if not isinstance(nofollow, int):
        raise JournalBlocked("safe no-follow journal read is unavailable")
    flags |= nofollow
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            raise JournalBlocked("journal leaf identity changed during open")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if (after.st_dev, after.st_ino, after.st_size) != (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
        ):
            raise JournalBlocked("journal leaf changed during read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _atomic_create_bytes(path: Path, value: bytes, *, mode: int = 0o600) -> None:
    """以 create-only 语义持久化 bytes，不覆盖既有对象。"""

    _require_plain_directory(path.parent)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            raise
        except OSError as exc:
            raise JournalBlocked("journal create-only promotion failed") from exc
        temporary.unlink()
        _fsync_directory(path.parent)
        if _read_regular_bytes(path) != value:
            raise JournalBlocked("journal create-only readback mismatch")
    finally:
        temporary.unlink(missing_ok=True)


def _load_json_object(path: Path, subject: str) -> dict[str, Any]:
    try:
        payload = json.loads(_read_regular_bytes(path).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JournalBlocked(f"{subject} is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise JournalBlocked(f"{subject} must be one JSON object")
    return payload


def _validate_prepared_target(payload: Mapping[str, Any]) -> None:
    _require_exact_fields(payload, _TARGET_FIELDS, "PREPARED target")
    _require_nonnegative_int(payload["sequence"], "PREPARED target sequence", positive=True)
    _require_role(payload["role"], "PREPARED target role")
    _require_process_ref(payload["ref"], "PREPARED target ref")
    if payload["before_exists"] is not True and payload["before_exists"] is not False:
        raise JournalBlocked("PREPARED target before_exists must be boolean")
    _require_digest(payload["before_digest"], "PREPARED target before_digest")
    _require_digest(payload["after_digest"], "PREPARED target after_digest")
    if not isinstance(payload["before_text"], str) or not isinstance(payload["after_text"], str):
        raise JournalBlocked("PREPARED target snapshots must be strings")
    expected_before = (
        canonical_digest({"exists": False})
        if payload["before_exists"] is False
        else hashlib.sha256(payload["before_text"].encode("utf-8")).hexdigest()
    )
    expected_after = hashlib.sha256(payload["after_text"].encode("utf-8")).hexdigest()
    if payload["before_exists"] is False and payload["before_text"] != "":
        raise JournalBlocked("PREPARED missing target must use an empty before snapshot")
    if payload["before_digest"] != expected_before or payload["after_digest"] != expected_after:
        raise JournalBlocked("PREPARED target snapshot digest mismatch")


def _validate_phase_payload(phase: str, payload: Mapping[str, Any]) -> None:
    if phase == "PREPARED":
        _require_safe_id(payload["authorization_id"], "PREPARED authorization_id")
        for key in (
            "authority_digest",
            "source_tuple_digest",
            "target_set_digest",
            "target_preimage_digest",
            "mutation_allowlist_digest",
            "preservation_digest",
            "plan_digest",
        ):
            _require_digest(payload[key], f"PREPARED {key}")
        targets = payload["targets"]
        if not isinstance(targets, list):
            raise JournalBlocked("PREPARED targets must be one list")
        for target in targets:
            if not isinstance(target, dict):
                raise JournalBlocked("PREPARED target must be one object")
            _validate_prepared_target(target)
        if [item["sequence"] for item in targets] != list(range(1, len(targets) + 1)):
            raise JournalBlocked("PREPARED target sequence is not contiguous")
        refs = [item["ref"] for item in targets]
        if len(refs) != len(set(refs)):
            raise JournalBlocked("PREPARED target refs must be unique")
        return
    if phase == "ATTEMPTED":
        _require_nonnegative_int(
            payload["target_sequence"], "ATTEMPTED target_sequence", positive=True
        )
        _require_role(payload["role"], "ATTEMPTED role")
        _require_process_ref(payload["ref"], "ATTEMPTED ref")
        if type(payload["before_exists"]) is not bool:
            raise JournalBlocked("ATTEMPTED before_exists must be boolean")
        _require_digest(payload["before_digest"], "ATTEMPTED before_digest")
        _require_digest(payload["after_digest"], "ATTEMPTED after_digest")
        return
    if phase in {"APPLIED", "RESTORED"}:
        _require_digest(payload["attempted_record_digest"], f"{phase} attempted_record_digest")
        _require_role(payload["role"], f"{phase} role")
        _require_process_ref(payload["ref"], f"{phase} ref")
        observed_key = "observed_after_digest" if phase == "APPLIED" else "observed_before_digest"
        _require_digest(payload[observed_key], f"{phase} {observed_key}")
        if phase == "RESTORED" and payload["restore_mode"] not in {
            "write-before",
            "remove-created",
        }:
            raise JournalBlocked("RESTORED restore_mode is unknown")
        return
    if phase == "ABORTED":
        if not isinstance(payload["reason"], str) or not payload["reason"].strip():
            raise JournalBlocked("ABORTED reason must be one non-empty string")
        _require_nonnegative_int(payload["domain_mutation_count"], "ABORTED domain_mutation_count")
        return
    if phase == "COMMITTED":
        attempted = _require_nonnegative_int(
            payload["attempted_count"], "COMMITTED attempted_count"
        )
        applied = _require_nonnegative_int(payload["applied_count"], "COMMITTED applied_count")
        mutations = _require_nonnegative_int(
            payload["domain_mutation_count"], "COMMITTED domain_mutation_count"
        )
        if attempted != applied or applied != mutations:
            raise JournalBlocked("COMMITTED counts must agree")
        _require_digest(payload["result_digest"], "COMMITTED result_digest")
        return
    if phase == "RECOVERED":
        attempted = _require_nonnegative_int(
            payload["attempted_count"], "RECOVERED attempted_count"
        )
        restored = _require_nonnegative_int(payload["restored_count"], "RECOVERED restored_count")
        already = _require_nonnegative_int(
            payload["already_before_count"], "RECOVERED already_before_count"
        )
        if restored + already != attempted:
            raise JournalBlocked("RECOVERED counts must cover every attempt")
        return
    if phase == "PARTIAL":
        if not isinstance(payload["failure_code"], str) or not _FAILURE_CODE_RE.fullmatch(
            payload["failure_code"]
        ):
            raise JournalBlocked("PARTIAL failure_code is invalid")
        _require_process_ref(payload["target_ref"], "PARTIAL target_ref")


def validate_owner(payload: Mapping[str, Any]) -> None:
    _require_exact_fields(payload, _OWNER_FIELDS, "journal owner")
    if payload["schema_version"] != JOURNAL_SCHEMA_VERSION:
        raise JournalBlocked("journal owner schema_version mismatch")
    if payload["owner_identity"] != OWNER_IDENTITY:
        raise JournalBlocked("journal owner identity mismatch")
    _require_safe_id(payload["project_id"], "journal project_id")
    _require_digest(
        payload["process_git_common_dir_identity"],
        "journal process_git_common_dir_identity",
    )
    body = dict(payload)
    observed = body.pop("owner_digest")
    if observed != canonical_digest(body):
        raise JournalBlocked("journal owner digest mismatch")


def validate_record(payload: Mapping[str, Any]) -> None:
    _require_exact_fields(payload, _RECORD_COMMON_FIELDS, "journal record")
    if payload["schema_version"] != JOURNAL_SCHEMA_VERSION:
        raise JournalBlocked("journal record schema_version mismatch")
    if payload["owner_identity"] != OWNER_IDENTITY:
        raise JournalBlocked("journal record owner mismatch")
    if not isinstance(payload["sequence"], int) or payload["sequence"] < 1:
        raise JournalBlocked("journal record sequence is invalid")
    _require_safe_id(payload["transaction_id"], "journal transaction_id")
    phase = payload["phase"]
    if not isinstance(phase, str) or phase not in _PHASE_PAYLOAD_FIELDS:
        raise JournalBlocked("journal record phase is unknown")
    _require_digest(
        payload["previous_record_digest"],
        "journal previous_record_digest",
        allow_empty=True,
    )
    phase_payload = payload["payload"]
    if not isinstance(phase_payload, dict):
        raise JournalBlocked("journal phase payload must be one object")
    _require_exact_fields(
        phase_payload,
        _PHASE_PAYLOAD_FIELDS[phase],
        f"journal {phase} payload",
    )
    _validate_phase_payload(phase, phase_payload)
    body = dict(payload)
    observed = body.pop("record_digest")
    if observed != canonical_digest(body):
        raise JournalBlocked("journal record digest mismatch")


def validate_record_sequence(
    records: Iterable[Mapping[str, Any]],
    transaction_id: str,
) -> None:
    """校验一个 transaction 的 hash chain、阶段图和 target accounting。"""

    _require_safe_id(transaction_id, "transaction_id")
    sequence = tuple(records)
    if not sequence:
        return
    previous_digest = ""
    previous_phase = ""
    terminal_seen = False
    for offset, record in enumerate(sequence, 1):
        validate_record(record)
        if record["sequence"] != offset:
            raise JournalBlocked("journal record sequence has a gap")
        if record["transaction_id"] != transaction_id:
            raise JournalBlocked("journal record transaction identity mismatch")
        if record["previous_record_digest"] != previous_digest:
            raise JournalBlocked("journal record hash chain mismatch")
        phase = record["phase"]
        if terminal_seen:
            raise JournalBlocked("journal contains a record after terminal")
        if previous_phase and phase not in _ALLOWED_TRANSITIONS.get(previous_phase, set()):
            raise JournalBlocked(
                f"invalid persisted journal transition: {previous_phase} -> {phase}"
            )
        previous_digest = record["record_digest"]
        previous_phase = phase
        terminal_seen = phase in _TERMINAL_PHASES
    if sequence[0]["phase"] != "PREPARED":
        raise JournalBlocked("journal transaction does not start with PREPARED")

    prepared_targets = sequence[0]["payload"]["targets"]
    prepared_by_sequence = {item["sequence"]: item for item in prepared_targets}
    attempts: list[Mapping[str, Any]] = []
    attempts_by_digest: dict[str, Mapping[str, Any]] = {}
    applied_digests: set[str] = set()
    restored_digests: set[str] = set()
    for record in sequence[1:]:
        phase = record["phase"]
        payload = record["payload"]
        if phase == "ATTEMPTED":
            expected_sequence = len(attempts) + 1
            if payload["target_sequence"] != expected_sequence:
                raise JournalBlocked("ATTEMPTED target sequence is not contiguous")
            target = prepared_by_sequence.get(expected_sequence)
            if target is None or any(
                payload[key] != target[key]
                for key in ("role", "ref", "before_exists", "before_digest", "after_digest")
            ):
                raise JournalBlocked("ATTEMPTED target does not match PREPARED authority")
            attempts.append(record)
            attempts_by_digest[record["record_digest"]] = record
        elif phase in {"APPLIED", "RESTORED"}:
            attempted_digest = payload["attempted_record_digest"]
            attempted = attempts_by_digest.get(attempted_digest)
            if attempted is None:
                raise JournalBlocked(f"{phase} does not reference one ATTEMPTED record")
            attempted_payload = attempted["payload"]
            if (
                payload["role"] != attempted_payload["role"]
                or payload["ref"] != attempted_payload["ref"]
            ):
                raise JournalBlocked(f"{phase} role/ref differs from ATTEMPTED")
            if phase == "APPLIED":
                if attempted_digest in applied_digests:
                    raise JournalBlocked("ATTEMPTED record has duplicate APPLIED accounting")
                if payload["observed_after_digest"] != attempted_payload["after_digest"]:
                    raise JournalBlocked("APPLIED observed digest differs from ATTEMPTED")
                applied_digests.add(attempted_digest)
            else:
                if attempted_digest in restored_digests:
                    raise JournalBlocked("ATTEMPTED record has duplicate RESTORED accounting")
                if payload["observed_before_digest"] != attempted_payload["before_digest"]:
                    raise JournalBlocked("RESTORED observed digest differs from ATTEMPTED")
                restored_digests.add(attempted_digest)

    terminal = sequence[-1]
    phase = terminal["phase"]
    payload = terminal["payload"]
    if phase == "ABORTED" and (attempts or payload["domain_mutation_count"] != 0):
        raise JournalBlocked("ABORTED transaction cannot contain domain attempts")
    if phase == "COMMITTED":
        if (
            payload["attempted_count"] != len(attempts)
            or payload["applied_count"] != len(applied_digests)
            or payload["domain_mutation_count"] != len(applied_digests)
            or len(attempts) != len(prepared_targets)
        ):
            raise JournalBlocked("COMMITTED accounting differs from journal records")
    if phase == "RECOVERED":
        if (
            payload["attempted_count"] != len(attempts)
            or payload["restored_count"] != len(restored_digests)
            or payload["already_before_count"] != len(attempts) - len(restored_digests)
        ):
            raise JournalBlocked("RECOVERED accounting differs from journal records")


class CoordinationJournal:
    """固定在 trusted process Git common-dir 下的私有 journal。"""

    def __init__(
        self,
        *,
        process_git_common_dir: Path,
        project_id: str,
        process_git_common_dir_identity: str,
        faults: Iterable[str] = (),
    ) -> None:
        _require_safe_id(project_id, "journal project_id")
        _require_digest(
            process_git_common_dir_identity,
            "journal process_git_common_dir_identity",
        )
        common = Path(os.path.abspath(process_git_common_dir))
        info = os.lstat(common)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise JournalBlocked("process Git common-dir is not a regular directory")
        self.root = _ensure_directory_chain(common, tuple(JOURNAL_REL.parts))
        self.project_id = project_id
        self.common_identity = process_git_common_dir_identity
        self._faults = frozenset(faults)
        self._initialize_owner()

    def _hit(self, point: str) -> None:
        if point in self._faults:
            raise JournalBlocked(f"injected journal fault: {point}")

    def _initialize_owner(self) -> None:
        body = {
            "schema_version": JOURNAL_SCHEMA_VERSION,
            "owner_identity": OWNER_IDENTITY,
            "project_id": self.project_id,
            "process_git_common_dir_identity": self.common_identity,
        }
        expected = {**body, "owner_digest": canonical_digest(body)}
        path = self.root / "owner.json"
        if path.exists() or path.is_symlink():
            observed = _load_json_object(path, "journal owner")
            validate_owner(observed)
            if observed != expected:
                raise JournalBlocked("journal owner does not match the fixed environment")
            return
        _atomic_create_bytes(path, canonical_bytes(expected) + b"\n")
        validate_owner(_load_json_object(path, "journal owner"))

    def claim_authorization(self, authorization_id: str, payload: Mapping[str, Any]) -> Path:
        _require_safe_id(authorization_id, "authorization_id")
        expected_fields = {
            "schema_version",
            "authorization_id",
            "operation",
            "cr_id",
            "work_id",
            "authority_revision",
            "source_tuple_digest",
            "plan_digest",
        }
        _require_exact_fields(payload, expected_fields, "authorization claim")
        if payload["schema_version"] != JOURNAL_SCHEMA_VERSION:
            raise JournalBlocked("authorization claim schema_version mismatch")
        if payload["authorization_id"] != authorization_id:
            raise JournalBlocked("authorization claim identity mismatch")
        if payload["operation"] != "cr.terminate":
            raise JournalBlocked("authorization claim operation mismatch")
        _require_safe_id(payload["cr_id"], "authorization claim cr_id")
        _require_safe_id(payload["work_id"], "authorization claim work_id")
        if payload["authority_revision"] != 2:
            raise JournalBlocked("authorization claim authority revision mismatch")
        _require_digest(
            payload["source_tuple_digest"],
            "authorization claim source_tuple_digest",
        )
        _require_digest(payload["plan_digest"], "authorization claim plan_digest")
        parent = _ensure_directory_chain(self.root, ("authorizations",))
        path = parent / f"{authorization_id}.json"
        try:
            _atomic_create_bytes(path, canonical_bytes(payload) + b"\n")
        except FileExistsError as exc:
            raise JournalBlocked("termination authorization was already consumed") from exc
        self._hit("claim.after_persist")
        return path

    def transaction_dir(self, transaction_id: str, *, terminal: bool = False) -> Path:
        _require_safe_id(transaction_id, "transaction_id")
        return self.root / ("terminal" if terminal else "active") / transaction_id

    def records(self, transaction_id: str, *, terminal: bool = False) -> tuple[dict[str, Any], ...]:
        directory = self.transaction_dir(transaction_id, terminal=terminal)
        if not directory.exists():
            if directory.is_symlink():
                raise JournalBlocked("journal transaction entry is a broken symlink")
            return ()
        info = os.lstat(directory)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise JournalBlocked("journal transaction entry is not a directory")
        paths = sorted(directory.iterdir(), key=lambda item: item.name)
        records: list[dict[str, Any]] = []
        previous = ""
        previous_phase = ""
        terminal_seen = False
        for expected_sequence, path in enumerate(paths, 1):
            info = os.lstat(path)
            if (
                stat.S_ISLNK(info.st_mode)
                or not stat.S_ISREG(info.st_mode)
                or re.fullmatch(r"\d{6}-[A-Z]+\.json", path.name) is None
            ):
                raise JournalBlocked("journal transaction contains an unexpected entry")
            record = _load_json_object(path, "journal record")
            validate_record(record)
            if record["sequence"] != expected_sequence:
                raise JournalBlocked("journal record sequence has a gap")
            expected_name = f"{expected_sequence:06d}-{record['phase']}.json"
            if path.name != expected_name:
                raise JournalBlocked("journal record filename does not match its content")
            if record["previous_record_digest"] != previous:
                raise JournalBlocked("journal record hash chain mismatch")
            if record["transaction_id"] != transaction_id:
                raise JournalBlocked("journal record transaction identity mismatch")
            if terminal_seen:
                raise JournalBlocked("journal contains a record after terminal")
            if previous_phase and record["phase"] not in _ALLOWED_TRANSITIONS.get(
                previous_phase, set()
            ):
                raise JournalBlocked(
                    f"invalid persisted journal transition: {previous_phase} -> {record['phase']}"
                )
            terminal_seen = record["phase"] in _TERMINAL_PHASES
            records.append(record)
            previous = record["record_digest"]
            previous_phase = record["phase"]
        validate_record_sequence(records, transaction_id)
        return tuple(records)

    def append(self, transaction_id: str, phase: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        _require_safe_id(transaction_id, "transaction_id")
        expected = _PHASE_PAYLOAD_FIELDS.get(phase)
        if expected is None:
            raise JournalBlocked("journal phase is unknown")
        _require_exact_fields(payload, expected, f"journal {phase} payload")
        _validate_phase_payload(phase, payload)
        directory = _ensure_directory_chain(self.root, ("active", transaction_id))
        records = self.records(transaction_id)
        if not records and phase != "PREPARED":
            raise JournalBlocked("journal transaction must begin with PREPARED")
        if records:
            previous_phase = records[-1]["phase"]
            if previous_phase in _TERMINAL_PHASES:
                raise JournalBlocked("cannot append after terminal journal record")
            if phase not in _ALLOWED_TRANSITIONS.get(previous_phase, set()):
                raise JournalBlocked(f"invalid journal transition: {previous_phase} -> {phase}")
        sequence = len(records) + 1
        body = {
            "schema_version": JOURNAL_SCHEMA_VERSION,
            "sequence": sequence,
            "transaction_id": transaction_id,
            "owner_identity": OWNER_IDENTITY,
            "phase": phase,
            "previous_record_digest": records[-1]["record_digest"] if records else "",
            "payload": dict(payload),
        }
        record = {**body, "record_digest": canonical_digest(body)}
        validate_record(record)
        path = directory / f"{sequence:06d}-{phase}.json"
        _atomic_create_bytes(path, canonical_bytes(record) + b"\n")
        self._hit(f"record.{phase}.after_persist")
        return record

    def active_transaction_ids(self) -> tuple[str, ...]:
        root = self.root / "active"
        if not root.exists():
            if root.is_symlink():
                raise JournalBlocked("journal active root is a broken symlink")
            return ()
        info = os.lstat(root)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise JournalBlocked("journal active root is not a directory")
        result: list[str] = []
        for path in sorted(root.iterdir(), key=lambda item: item.name):
            _require_safe_id(path.name, "active transaction ID")
            child = os.lstat(path)
            if stat.S_ISLNK(child.st_mode) or not stat.S_ISDIR(child.st_mode):
                raise JournalBlocked("unexpected active journal entry")
            result.append(path.name)
        return tuple(result)

    def retry_terminal_promotions(self) -> int:
        promoted = 0
        for transaction_id in self.active_transaction_ids():
            records = self.records(transaction_id)
            if records and records[-1]["phase"] in _PROMOTABLE_PHASES:
                self.promote_terminal(transaction_id)
                promoted += 1
        return promoted

    def promote_terminal(self, transaction_id: str) -> Path:
        source = self.transaction_dir(transaction_id)
        target = self.transaction_dir(transaction_id, terminal=True)
        if target.exists() and not source.exists():
            records = self.records(transaction_id, terminal=True)
            if not records or records[-1]["phase"] not in _PROMOTABLE_PHASES:
                raise JournalBlocked("terminal transaction lacks a promotable record")
            return target
        records = self.records(transaction_id)
        if not records or records[-1]["phase"] not in _PROMOTABLE_PHASES:
            raise JournalBlocked("active transaction lacks a promotable terminal record")
        _ensure_directory_chain(self.root, ("terminal",))
        if target.exists() or target.is_symlink():
            raise JournalBlocked("terminal transaction target already exists")
        self._hit("promotion.before_replace")
        os.replace(source, target)
        _fsync_directory(source.parent)
        _fsync_directory(target.parent)
        self._hit("promotion.after_replace")
        return target

    @staticmethod
    def prepared_targets(records: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
        if not records or records[0]["phase"] != "PREPARED":
            raise JournalBlocked("transaction has no PREPARED record")
        targets = records[0]["payload"]["targets"]
        return tuple(dict(item) for item in targets)

    @staticmethod
    def private_ref(transaction_id: str, *, terminal: bool = False) -> str:
        _require_safe_id(transaction_id, "transaction_id")
        bucket = "terminal" if terminal else "active"
        return f"private://process-git-common-dir/meta-flow/cr-termination-v2/{bucket}/{transaction_id}"
