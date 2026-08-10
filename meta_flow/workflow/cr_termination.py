"""CR negative-terminal 的 typed plan、Authorization v2 与可恢复事务 owner。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from meta_flow.checks import cr_tracking
from meta_flow.project.governance import phase_from_payload
from meta_flow.project.model import project_from_payload
from meta_flow.project.process_route import require_process_route
from meta_flow.project.scale import _parse_yaml_lines, _strip_comment, dump_yaml
from meta_flow.state import current, event_ledger
from meta_flow.work.lifecycle import transition_work
from meta_flow.work.model import WORK_MAX_BYTES, work_from_payload
from meta_flow.workflow.cr_index import (
    _canonical_digest,
    _dirty_path_digest,
    validate_index_payload,
)
from meta_flow.workflow.cr_model import (
    CR_ID_RE,
    DIGEST_RE,
    FINISHED_STATUSES,
    OID_RE,
    SAFE_AUTHORIZATION_ID_RE,
    normalize_cr_type,
    parse_frontmatter,
    render_frontmatter_fields,
)
from meta_flow.workflow.cr_projection import (
    _acquire_status_sync_writer_lock,
    _release_status_sync_writer_lock,
    _render_exact_section_rows,
)
from meta_flow.workflow.cr_records import (
    _git_fact,
    _load_json_object,
    _rel,
)
from meta_flow.workflow.cr_termination_journal import (
    JOURNAL_SCHEMA_VERSION,
    CoordinationJournal,
    JournalBlocked,
)
from meta_flow.workflow.cr_termination_journal import canonical_digest as _journal_digest

TERMINATION_TUPLES = {
    "cancelled": {
        "lifecycle_status": "cancelled",
        "readiness_status": "n/a",
        "gate_status": "closed",
    },
    "superseded": {
        "lifecycle_status": "superseded",
        "readiness_status": "n/a",
        "gate_status": "closed",
    },
}

SOURCE_TUPLE_FIELDS = {
    "provider_release_oid",
    "provider_implementation_digest",
    "target_release_oid",
    "process_oid",
    "process_git_common_dir_identity",
    "process_dirty_path_digest",
    "project_id",
    "route_mode",
    "route_digest",
}

TERMINATION_AUTHORIZATION_FIELDS = {
    "schema_version",
    "authorization_id",
    "authorization_source",
    "authorization_kind",
    "operation",
    "cr_id",
    "work_id",
    "termination_reason",
    "terminal_tuple",
    "authority_revision",
    "authority_digest",
    "source_tuple",
    "source_tuple_digest",
    "target_set_digest",
    "target_preimage_digest",
    "mutation_allowlist_digest",
    "preservation_digest",
    "lock_preimage_digest",
    "plan_digest",
    "expires_at",
    "single_use",
}

TERMINATION_AUTHORIZATION_SOURCE = "typed-user-confirmation"
TERMINATION_AUTHORIZATION_KIND = "cr-termination"
TERMINATION_OPERATION = "cr.terminate"
AUTHORITY_REVISION = 2
AUTHORITY_OWNER_IDENTITY = "meta-flow.workflow.cr_termination/control-plane-authority"

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_PHASE_VALUE_RE = re.compile(r"^[A-Za-z0-9._/-]+$")
_ROLE_ORDER = (
    "formal_cr",
    "work",
    "project",
    "phase",
    "state",
    "current_view",
    "summary",
    "ledger",
    "index",
)
_ROLE_NUMBERS = {
    "formal_cr": 10,
    "work": 20,
    "project": 30,
    "phase": 40,
    "state": 45,
    "current_view": 46,
    "summary": 50,
    "ledger": 60,
    "index": 90,
}
_KNOWN_WORK_TOP_LEVEL_KEYS = {
    "schema_version",
    "work_id",
    "project_id",
    "kind",
    "objective",
    "status",
    "request_ref",
    "request_confirmed",
    "phase_ref",
    "risk_profile",
    "risk_reason_codes",
    "required_gates",
    "route_profile",
    "execution_unit",
    "scope",
    "scope_digest",
    "budget",
    "usage_ref",
    "base_oids",
    "result_ref",
    "updated_at",
}
_WORK_HEADER_KEYS = {"schema_version", "work_id", "project_id", "phase_ref"}
_MUTABLE_FORMAL_FIELDS = {
    "lifecycle_status",
    "readiness_status",
    "gate_status",
    "status",
    "termination_reason",
}
_MUTABLE_SUMMARY_FIELDS = {
    "status",
    "readiness",
    "gate_status",
    "decision",
    "termination_reason",
    "terminal_tuple",
    "preservation_digest",
    "updated_at",
}
_ROLE_CONTRACT = (
    (10, "formal_cr", "changes/<cr_id>.md", True),
    (20, "work", "works/<work_id>/WORK.yaml", True),
    (30, "project", "PROJECT.yaml", True),
    (40, "phase", "<work.phase_ref>", False),
    (45, "state", "state/STATE.current.json", False),
    (46, "current_view", "current/CURRENT.json", False),
    (50, "summary", "changes/summaries/<cr_id>.summary.json", False),
    (60, "ledger", "state/CR-LEDGER.ndjson", False),
    (90, "index", "changes/CR-INDEX.json", False),
)
_ROLE_DERIVATION_CONTRACT_DIGEST = _canonical_digest(_ROLE_CONTRACT)


@dataclass(frozen=True)
class TerminationAuthorization:
    schema_version: int
    authorization_id: str
    authorization_source: str
    authorization_kind: str
    operation: str
    cr_id: str
    work_id: str
    termination_reason: str
    terminal_tuple: dict[str, str]
    authority_revision: int
    authority_digest: str
    source_tuple: dict[str, str]
    source_tuple_digest: str
    target_set_digest: str
    target_preimage_digest: str
    mutation_allowlist_digest: str
    preservation_digest: str
    lock_preimage_digest: str
    plan_digest: str
    expires_at: str
    single_use: bool = True

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> TerminationAuthorization:
        if set(payload) != TERMINATION_AUTHORIZATION_FIELDS:
            missing = sorted(TERMINATION_AUTHORIZATION_FIELDS - set(payload))
            extra = sorted(set(payload) - TERMINATION_AUTHORIZATION_FIELDS)
            raise ValueError(
                f"termination authorization fields mismatch: missing={missing}, extra={extra}"
            )
        source_tuple = payload.get("source_tuple")
        if not isinstance(source_tuple, dict) or set(source_tuple) != SOURCE_TUPLE_FIELDS:
            actual = set(source_tuple) if isinstance(source_tuple, dict) else set()
            raise ValueError(
                "termination source_tuple fields mismatch: "
                f"missing={sorted(SOURCE_TUPLE_FIELDS - actual)}, "
                f"extra={sorted(actual - SOURCE_TUPLE_FIELDS)}"
            )
        terminal_tuple = payload.get("terminal_tuple")
        if not isinstance(terminal_tuple, dict):
            raise ValueError("termination terminal_tuple must be one object")
        return cls(
            **{
                **payload,
                "source_tuple": dict(source_tuple),
                "terminal_tuple": dict(terminal_tuple),
            }
        )


@dataclass(frozen=True)
class TerminationTarget:
    order: int
    role: str
    ref: str
    path: Path
    required: bool
    truth_or_derived: str
    before: str | None
    after: str

    @property
    def before_exists(self) -> bool:
        return self.before is not None

    @property
    def changes(self) -> bool:
        return self.before != self.after

    @property
    def before_digest(self) -> str:
        if self.before is None:
            return _canonical_digest({"exists": False})
        return hashlib.sha256(self.before.encode("utf-8")).hexdigest()

    @property
    def after_digest(self) -> str:
        return hashlib.sha256(self.after.encode("utf-8")).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        return {
            "order": self.order,
            "role": self.role,
            "ref": self.ref,
            "required": self.required,
            "truth_or_derived": self.truth_or_derived,
            "before_exists": self.before_exists,
            "before_digest": self.before_digest,
            "after_digest": self.after_digest,
            "changes": self.changes,
        }

    def journal_projection(self, sequence: int) -> dict[str, Any]:
        return {
            "sequence": sequence,
            "role": self.role,
            "ref": self.ref,
            "before_exists": self.before_exists,
            "before_digest": self.before_digest,
            "after_digest": self.after_digest,
            "before_text": self.before or "",
            "after_text": self.after,
        }


@dataclass(frozen=True)
class TerminationPlan:
    decision: str
    cr_id: str
    work_id: str
    termination_reason: str
    terminal_tuple: dict[str, str]
    binding: dict[str, str]
    authority_digest: str
    source_tuple: dict[str, str]
    preservation: dict[str, str]
    eligible_targets: tuple[TerminationTarget, ...]
    targets: tuple[TerminationTarget, ...]
    read_audit: dict[str, int | bool]
    reason: str = ""

    @property
    def source_tuple_digest(self) -> str:
        return _canonical_digest({"domain": "cr-termination-source-v2", **self.source_tuple})

    @property
    def target_set_digest(self) -> str:
        return _canonical_digest(
            {
                "domain": "cr-termination-target-set-v2",
                "targets": [
                    {"role": item.role, "ref": item.ref, "required": item.required}
                    for item in self.eligible_targets
                ],
            }
        )

    @property
    def target_preimage_digest(self) -> str:
        return _canonical_digest(
            {
                "domain": "cr-termination-target-preimage-v2",
                "targets": [
                    {
                        "role": item.role,
                        "ref": item.ref,
                        "before_exists": item.before_exists,
                        "before_digest": item.before_digest,
                    }
                    for item in self.eligible_targets
                ],
            }
        )

    @property
    def mutation_allowlist_digest(self) -> str:
        return _canonical_digest(
            {
                "domain": "cr-termination-mutation-allowlist-v2",
                "targets": [{"role": item.role, "ref": item.ref} for item in self.targets],
            }
        )

    @property
    def preservation_digest(self) -> str:
        return _canonical_digest({"domain": "cr-termination-preservation-v2", **self.preservation})

    @property
    def lock_preimage_digest(self) -> str:
        return _canonical_digest(
            {
                "domain": "cr-termination-lock-preimage-v2",
                "authority_digest": self.authority_digest,
                "source_tuple_digest": self.source_tuple_digest,
                "target_set_digest": self.target_set_digest,
                "target_preimage_digest": self.target_preimage_digest,
                "mutation_allowlist_digest": self.mutation_allowlist_digest,
                "preservation_digest": self.preservation_digest,
            }
        )

    def _digest_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "operation": TERMINATION_OPERATION,
            "decision": self.decision,
            "cr_id": self.cr_id,
            "work_id": self.work_id,
            "termination_reason": self.termination_reason,
            "terminal_tuple": self.terminal_tuple,
            "binding": self.binding,
            "authority_revision": AUTHORITY_REVISION,
            "authority_digest": self.authority_digest,
            "source_tuple": self.source_tuple,
            "source_tuple_digest": self.source_tuple_digest,
            "target_set_digest": self.target_set_digest,
            "target_preimage_digest": self.target_preimage_digest,
            "mutation_allowlist_digest": self.mutation_allowlist_digest,
            "preservation": self.preservation,
            "preservation_digest": self.preservation_digest,
            "lock_preimage_digest": self.lock_preimage_digest,
            "eligible_targets": [target.as_dict() for target in self.eligible_targets],
            "mutation_targets": [target.as_dict() for target in self.targets],
            "read_audit": self.read_audit,
            "reason": self.reason,
        }

    @property
    def plan_digest(self) -> str:
        return _canonical_digest(self._digest_payload())

    def as_dict(self) -> dict[str, Any]:
        return {
            **self._digest_payload(),
            "mutation_count": 0,
            "planned_mutation_count": len(self.targets),
            "mutation_allowlist": [
                {"role": target.role, "ref": target.ref} for target in self.targets
            ],
            "exact_changed_leaf_paths": [target.ref for target in self.targets],
            "transaction_order": [
                {
                    "order": target.order,
                    "role": target.role,
                    "ref": target.ref,
                    "truth_or_derived": target.truth_or_derived,
                }
                for target in self.targets
            ],
            "rollback": {
                "strategy": "durable-attempted-reverse-exact-preimage-restore",
                "order": [target.ref for target in reversed(self.targets)],
                "partial_evidence": (
                    "private://process-git-common-dir/meta-flow/"
                    "cr-termination-v2/active/<transaction-id>"
                ),
            },
            "apply_private_effects": [
                "single-use authorization claim",
                "append-only coordination journal",
            ],
            "plan_digest": self.plan_digest,
        }


@dataclass(frozen=True)
class _WorkHeader:
    schema_version: int
    work_id: str
    project_id: str
    phase_ref: str


@dataclass(frozen=True)
class _RefSpec:
    role: str
    ref: str
    required: bool
    max_bytes: int | None = None


@dataclass(frozen=True)
class _GuardedRef:
    spec: _RefSpec
    path: Path
    exists: bool
    device: int | None
    inode: int | None
    size: int

    @property
    def identity(self) -> tuple[int, int] | None:
        if self.device is None or self.inode is None:
            return None
        return self.device, self.inode


def _portable_termination_error(
    exc: Exception,
    *,
    project_root: Path,
    process_root: Path | None = None,
) -> str:
    text = str(exc)
    replacements = [(str(project_root.resolve()), "<release-root>")]
    if process_root is not None:
        replacements.append((str(process_root.resolve()), "<process-root>"))
    for source, replacement in replacements:
        text = text.replace(source, replacement)
    return text


def _safe_id(value: str, subject: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise ValueError(f"{subject} must use safe ID characters")
    return value


def _safe_ref_parts(ref: str) -> tuple[str, ...]:
    if (
        not isinstance(ref, str)
        or not ref
        or "\x00" in ref
        or "\\" in ref
        or ":" in ref
        or ref.startswith("/")
        or ref.endswith("/")
    ):
        raise ValueError("logical ref is not one canonical relative POSIX ref")
    parts = tuple(ref.split("/"))
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("logical ref contains an empty or dot segment")
    return parts


def _guard_ref(process_root: Path, spec: _RefSpec) -> _GuardedRef:
    parts = _safe_ref_parts(spec.ref)
    root = Path(os.path.abspath(process_root))
    root_info = os.lstat(root)
    if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
        raise ValueError("process route root is not one non-symlink directory")
    path = root.joinpath(*parts)
    current_path = root
    missing = False
    leaf_info: os.stat_result | None = None
    for offset, part in enumerate(parts):
        current_path /= part
        if missing:
            continue
        try:
            info = os.lstat(current_path)
        except FileNotFoundError as exc:
            is_leaf = offset == len(parts) - 1
            if spec.required or not is_leaf:
                raise ValueError(f"required {spec.role} path is missing") from exc
            missing = True
            continue
        if stat.S_ISLNK(info.st_mode):
            raise ValueError(f"{spec.role} path contains a symlink segment")
        if offset == len(parts) - 1:
            if not stat.S_ISREG(info.st_mode):
                raise ValueError(f"{spec.role} leaf is not a regular file")
            leaf_info = info
        elif not stat.S_ISDIR(info.st_mode):
            raise ValueError(f"{spec.role} parent is not a directory")
    if missing:
        return _GuardedRef(spec, path, False, None, None, 0)
    if leaf_info is None:
        raise ValueError(f"{spec.role} leaf identity is unavailable")
    if spec.max_bytes is not None and leaf_info.st_size > spec.max_bytes:
        raise ValueError(f"{spec.role} exceeds bounded read size")
    return _GuardedRef(
        spec,
        path,
        True,
        leaf_info.st_dev,
        leaf_info.st_ino,
        leaf_info.st_size,
    )


def _read_guarded(guarded: _GuardedRef) -> bytes | None:
    if not guarded.exists:
        return None
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if not isinstance(nofollow, int):
        raise ValueError("safe no-follow open capability is unavailable")
    flags = os.O_RDONLY | nofollow
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor = os.open(guarded.path, flags)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ValueError(f"{guarded.spec.role} opened leaf is not regular")
        if (opened.st_dev, opened.st_ino) != guarded.identity:
            raise ValueError(f"{guarded.spec.role} lstat/open identity drift")
        if guarded.spec.max_bytes is not None and opened.st_size > guarded.spec.max_bytes:
            raise ValueError(f"{guarded.spec.role} exceeds bounded read size")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if guarded.spec.max_bytes is not None and total > guarded.spec.max_bytes:
                raise ValueError(f"{guarded.spec.role} bounded read overflow")
        after = os.fstat(descriptor)
        if (after.st_dev, after.st_ino, after.st_size) != (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
        ):
            raise ValueError(f"{guarded.spec.role} changed during guarded read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _decode_utf8(value: bytes | None, subject: str, *, missing: str | None = None) -> str | None:
    if value is None:
        return missing
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{subject} is not UTF-8") from exc


def _load_json_bytes(value: bytes | None, subject: str) -> dict[str, Any]:
    if value is None:
        raise FileNotFoundError(f"{subject} is missing")
    try:
        payload = json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{subject} is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{subject} must contain one JSON object")
    return payload


def _load_yaml_bytes(value: bytes | None, subject: str) -> dict[str, Any]:
    text = _decode_utf8(value, subject)
    if text is None:
        raise FileNotFoundError(f"{subject} is missing")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as json_error:
        prepared: list[tuple[int, str]] = []
        for raw_line in text.splitlines():
            line = _strip_comment(raw_line).rstrip()
            if not line.strip():
                continue
            prepared.append((len(line) - len(line.lstrip(" ")), line.strip()))
        payload, offset = _parse_yaml_lines(
            prepared,
            0,
            prepared[0][0] if prepared else 0,
        )
        if offset != len(prepared):
            raise ValueError(f"{subject} contains unsupported YAML structure") from json_error
    if not isinstance(payload, dict):
        raise ValueError(f"{subject} must contain one YAML object")
    return payload


def _parse_work_header(value: bytes, *, expected_work_id: str) -> _WorkHeader:
    if len(value) > WORK_MAX_BYTES:
        raise ValueError("WORK.yaml exceeds bounded header size")
    text = _decode_utf8(value, "WORK.yaml")
    assert text is not None
    found: dict[str, str] = {}
    for line in text.splitlines():
        if not line or line.lstrip().startswith("#") or line[0].isspace():
            continue
        if "\t" in line or ":" not in line:
            raise ValueError("WORK.yaml contains unsupported top-level syntax")
        key, raw = line.split(":", 1)
        key = key.strip()
        if key not in _KNOWN_WORK_TOP_LEVEL_KEYS:
            raise ValueError(f"WORK.yaml contains unknown top-level key: {key}")
        if key not in _WORK_HEADER_KEYS:
            continue
        if key in found:
            raise ValueError(f"WORK.yaml contains duplicate header key: {key}")
        scalar = raw.strip()
        if not scalar or scalar[0] in "'\"[{&*!|>" or " #" in scalar:
            raise ValueError(f"WORK.yaml header {key} must be a plain scalar")
        found[key] = scalar
    required = {"schema_version", "work_id", "project_id"}
    if not required.issubset(found):
        raise ValueError(f"WORK.yaml header missing {sorted(required - set(found))}")
    if found["schema_version"] != "1":
        raise ValueError("WORK.yaml schema_version must be 1")
    _safe_id(found["work_id"], "work_id")
    _safe_id(found["project_id"], "project_id")
    if found["work_id"] != expected_work_id:
        raise ValueError("WORK.yaml work_id does not match bootstrap identity")
    phase_ref = found.get("phase_ref", "")
    if phase_ref:
        if not _SAFE_PHASE_VALUE_RE.fullmatch(phase_ref):
            raise ValueError("WORK.yaml phase_ref has unsafe syntax")
        parts = _safe_ref_parts(phase_ref)
        if len(parts) < 3 or parts[0] != "phases" or parts[-1] != "PHASE.yaml":
            raise ValueError("WORK.yaml phase_ref must name phases/<id>/PHASE.yaml")
    return _WorkHeader(1, found["work_id"], found["project_id"], phase_ref)


def _role_specs(cr_id: str, header: _WorkHeader) -> tuple[_RefSpec, ...]:
    specs = [
        _RefSpec("formal_cr", f"changes/{cr_id}.md", True),
        _RefSpec("work", f"works/{header.work_id}/WORK.yaml", True, WORK_MAX_BYTES),
        _RefSpec("project", "PROJECT.yaml", True),
    ]
    if header.phase_ref:
        specs.append(_RefSpec("phase", header.phase_ref, True))
    specs.extend(
        (
            _RefSpec("state", "state/STATE.current.json", False),
            _RefSpec("current_view", "current/CURRENT.json", False),
            _RefSpec("summary", f"changes/summaries/{cr_id}.summary.json", False),
            _RefSpec("ledger", "state/CR-LEDGER.ndjson", False),
            _RefSpec("index", "changes/CR-INDEX.json", False),
        )
    )
    return tuple(sorted(specs, key=lambda item: _ROLE_ORDER.index(item.role)))


def _discover_guarded_inputs(
    release_root: Path,
    *,
    cr_id: str,
    work_id: str,
) -> tuple[
    Any, _WorkHeader, dict[str, _GuardedRef], dict[str, bytes | None], dict[str, int | bool]
]:
    route = require_process_route(release_root)
    bootstrap = _guard_ref(
        route.process_root,
        _RefSpec("work", f"works/{work_id}/WORK.yaml", True, WORK_MAX_BYTES),
    )
    bootstrap_bytes = _read_guarded(bootstrap)
    assert bootstrap_bytes is not None
    header = _parse_work_header(bootstrap_bytes, expected_work_id=work_id)
    specs = _role_specs(cr_id, header)
    guards = tuple(_guard_ref(route.process_root, spec) for spec in specs)
    identities = [guard.identity for guard in guards if guard.identity is not None]
    if len(identities) != len(set(identities)):
        raise ValueError("role inventory contains an inode alias")
    roles = [guard.spec.role for guard in guards]
    refs = [guard.spec.ref for guard in guards]
    if len(roles) != len(set(roles)) or len(refs) != len(set(refs)):
        raise ValueError("role inventory contains duplicate role/ref")
    values = {guard.spec.role: _read_guarded(guard) for guard in guards}
    if values["work"] != bootstrap_bytes:
        raise ValueError("bootstrap Work changed before full inventory read")
    return (
        route,
        header,
        {guard.spec.role: guard for guard in guards},
        values,
        {
            "bootstrap_byte_reads": 1,
            "target_byte_reads": sum(value is not None for value in values.values()),
            "auxiliary_guarded_reads": 0,
            "unsafe_byte_reads": 0,
            "inventory_complete_before_target_read": True,
        },
    )


def _git_common_dir(process_root: Path) -> Path:
    value = _git_fact(process_root, "rev-parse", "--git-common-dir")
    path = Path(value) if value else process_root / ".meta-flow-fixture-git"
    candidate = path if path.is_absolute() else process_root / path
    common = candidate.resolve(strict=True)
    info = os.lstat(common)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise ValueError("process Git common-dir is not one non-symlink directory")
    return common


def _common_dir_identity(common: Path) -> str:
    info = os.lstat(common)
    return _canonical_digest({"schema_version": 1, "device": info.st_dev, "inode": info.st_ino})


def _provider_implementation_digest() -> str:
    owner_root = Path(__file__).resolve().parents[2]
    refs = (
        "meta_flow/workflow/cr_termination.py",
        "meta_flow/workflow/cr_termination_journal.py",
    )
    inventory = []
    for ref in refs:
        path = owner_root / ref
        inventory.append({"ref": ref, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return _canonical_digest(inventory)


def _authority_digest() -> str:
    return _canonical_digest(
        {
            "owner_identity": AUTHORITY_OWNER_IDENTITY,
            "authority_revision": AUTHORITY_REVISION,
            "role_derivation_contract_digest": _ROLE_DERIVATION_CONTRACT_DIGEST,
        }
    )


def _source_tuple(release_root: Path, route: Any) -> dict[str, str]:
    provider_root = Path(__file__).resolve().parents[2]
    common = _git_common_dir(route.process_root)
    payload = {
        "provider_release_oid": _git_fact(provider_root, "rev-parse", "--verify", "HEAD").lower(),
        "provider_implementation_digest": _provider_implementation_digest(),
        "target_release_oid": _git_fact(release_root, "rev-parse", "--verify", "HEAD").lower(),
        "process_oid": _git_fact(route.process_root, "rev-parse", "--verify", "HEAD").lower(),
        "process_git_common_dir_identity": _common_dir_identity(common),
        "process_dirty_path_digest": _dirty_path_digest(route.process_root),
        "project_id": route.project_id,
        "route_mode": route.route_mode,
        "route_digest": _canonical_digest(
            {
                "schema_version": 1,
                "project_id": route.project_id,
                "layout_version": route.layout_version,
                "route_mode": route.route_mode,
                "source": route.source,
            }
        ),
    }
    for key in ("provider_release_oid", "target_release_oid", "process_oid"):
        if not OID_RE.fullmatch(payload[key]):
            raise ValueError(f"{key} is not one exact Git OID")
    for key in (
        "provider_implementation_digest",
        "process_git_common_dir_identity",
        "process_dirty_path_digest",
        "route_digest",
    ):
        if not DIGEST_RE.fullmatch(payload[key]):
            raise ValueError(f"{key} is not one SHA-256 digest")
    return payload


def _render_termination_body_projection(
    text: str,
    *,
    terminal_tuple: dict[str, str],
) -> str:
    rendered = _render_exact_section_rows(
        text,
        "CR 类型与门禁策略",
        {
            "生命周期状态": terminal_tuple["lifecycle_status"],
            "就绪状态": terminal_tuple["readiness_status"],
            "门禁状态": terminal_tuple["gate_status"],
        },
    )
    return _render_exact_section_rows(rendered, "Checkpoint Index", {"CP8": "not-applicable"})


def _formal_preserved_digest(text: str) -> str:
    fields = {
        key: value
        for key, value in parse_frontmatter(text).items()
        if key not in _MUTABLE_FORMAL_FIELDS
    }
    body = text
    if text.startswith("---\n"):
        closing = text.find("\n---\n", 4)
        if closing >= 0:
            body = text[closing + 5 :]
    neutral_body = _render_termination_body_projection(
        body,
        terminal_tuple={
            "lifecycle_status": "<mutable>",
            "readiness_status": "<mutable>",
            "gate_status": "<mutable>",
        },
    )
    return _canonical_digest({"frontmatter": fields, "body": neutral_body})


def _summary_preserved_digest(payload: Mapping[str, Any]) -> str:
    return _canonical_digest(
        {key: value for key, value in payload.items() if key not in _MUTABLE_SUMMARY_FIELDS}
    )


def _summary_base(
    existing: dict[str, Any] | None,
    *,
    cr_id: str,
    cr_path_ref: str,
    fields: Mapping[str, str],
    current_tuple: dict[str, str],
) -> dict[str, Any]:
    if existing is not None:
        if str(existing.get("id") or "") != cr_id:
            raise ValueError("CR summary identity mismatch")
        if str(existing.get("full_ref") or "") != cr_path_ref:
            raise ValueError("CR summary full_ref mismatch")
        return dict(existing)
    return {
        "id": cr_id,
        "cr_type": normalize_cr_type(fields.get("cr_type") or fields.get("cr_kind") or "feature"),
        "title": fields.get("title") or cr_id,
        "status": current_tuple["lifecycle_status"],
        "readiness": current_tuple["readiness_status"],
        "gate_status": current_tuple["gate_status"],
        "decision": "pending",
        "full_ref": cr_path_ref,
        "evidence_index_ref": "",
    }


def _evidence_digest(
    process_root: Path,
    evidence_ref: str,
) -> tuple[str, int]:
    if not evidence_ref:
        return _canonical_digest({"exists": False}), 0
    if not evidence_ref.startswith("process/"):
        raise ValueError("evidence_index_ref must use one process logical ref")
    relative = evidence_ref.removeprefix("process/")
    guarded = _guard_ref(process_root, _RefSpec("evidence_index", relative, True))
    value = _read_guarded(guarded)
    assert value is not None
    return hashlib.sha256(value).hexdigest(), 1


def _render_ledger(
    before: str,
    path: Path,
    event: dict[str, Any],
) -> str:
    matching: list[dict[str, Any]] = []
    for line in before.splitlines():
        if not line.strip():
            continue
        try:
            existing = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError("CR ledger contains invalid JSON") from exc
        if not isinstance(existing, dict):
            raise ValueError("CR ledger event must be one object")
        if existing.get("event_id") == event["event_id"]:
            matching.append(existing)
    if len(matching) > 1:
        raise ValueError("CR termination ledger event identity is duplicated")
    if matching:
        observed = dict(matching[0])
        expected = dict(event)
        observed_source = observed.pop("source_tuple_digest", "")
        expected.pop("source_tuple_digest", None)
        if (
            observed != expected
            or not isinstance(observed_source, str)
            or not DIGEST_RE.fullmatch(observed_source)
        ):
            raise ValueError("CR termination ledger event identity conflicts with existing bytes")
        return before
    return event_ledger.render_appended_event(path, event, before_text=before)


def _formal_cr_ids(process_root: Path) -> tuple[str, ...]:
    root = process_root / "changes"
    if not root.is_dir():
        return ()
    result: list[str] = []
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        match = re.fullmatch(r"(CR-\d+)\.md", path.name)
        if match is None or "FOLLOW-UP" in path.name:
            continue
        info = os.lstat(path)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise ValueError("formal CR directory contains an unsafe matching leaf")
        result.append(match.group(1))
    return tuple(result)


def _project_index(
    existing: dict[str, Any] | None,
    *,
    process_root: Path,
    cr_id: str,
    fields: Mapping[str, str],
    current_tuple: dict[str, str],
    terminal_tuple: dict[str, str],
    formal_ref: str,
    summary_ref: str,
) -> dict[str, Any]:
    if existing is None:
        other_ids = tuple(item for item in _formal_cr_ids(process_root) if item != cr_id)
        if other_ids:
            raise ValueError("CR-INDEX is missing while other formal CRs exist")
        item = {
            "id": cr_id,
            "cr_type": normalize_cr_type(
                fields.get("cr_type") or fields.get("cr_kind") or "feature"
            ),
            "title": fields.get("title") or cr_id,
            "status": terminal_tuple["lifecycle_status"],
            "lifecycle_status": terminal_tuple["lifecycle_status"],
            "readiness": terminal_tuple["readiness_status"],
            "readiness_status": terminal_tuple["readiness_status"],
            "gate_status": terminal_tuple["gate_status"],
            "gate_profile": fields.get("gate_profile") or "",
            "full_ref": formal_ref,
            "formal_cr_path": formal_ref,
            "summary_ref": summary_ref,
        }
        items = [item]
        generated_at = "1970-01-01T00:00:00+00:00"
    else:
        errors = validate_index_payload(existing)
        if errors:
            raise ValueError("; ".join(errors))
        items = [dict(item) for item in existing["items"]]
        matches = [item for item in items if str(item.get("id") or "") == cr_id]
        if len(matches) != 1:
            raise ValueError("CR-INDEX must contain exactly one target CR item")
        item = matches[0]
        observed_tuple = (
            cr_tracking.normalize_lifecycle_status(
                str(item.get("lifecycle_status") or item.get("status") or "")
            ),
            cr_tracking.normalize_readiness_status(
                str(item.get("readiness_status") or item.get("readiness") or "")
            ),
            cr_tracking.normalize_gate_status(str(item.get("gate_status") or "")),
        )
        if observed_tuple != tuple(current_tuple.values()):
            raise ValueError("CR-INDEX target item differs from current formal truth")
        item.update(
            {
                "status": terminal_tuple["lifecycle_status"],
                "lifecycle_status": terminal_tuple["lifecycle_status"],
                "readiness": terminal_tuple["readiness_status"],
                "readiness_status": terminal_tuple["readiness_status"],
                "gate_status": terminal_tuple["gate_status"],
            }
        )
        generated_at = str(existing["generated_at"])
    semantic = {"schema_version": 1, "items": items}
    projected = {
        "schema_version": 1,
        "generated_at": generated_at,
        "semantic_digest": _canonical_digest(semantic),
        "items": items,
    }
    errors = validate_index_payload(projected)
    if errors:
        raise ValueError("; ".join(errors))
    return projected


def _contains_identity(value: Any, identities: set[str]) -> bool:
    if isinstance(value, str):
        return any(identity in value for identity in identities)
    if isinstance(value, dict):
        return any(_contains_identity(item, identities) for item in value.values())
    if isinstance(value, list):
        return any(_contains_identity(item, identities) for item in value)
    return False


def _make_target(
    release_root: Path,
    guard: _GuardedRef,
    before_bytes: bytes | None,
    after: str,
    truth_or_derived: str,
) -> TerminationTarget:
    before = _decode_utf8(before_bytes, guard.spec.role, missing=None)
    return TerminationTarget(
        order=_ROLE_NUMBERS[guard.spec.role],
        role=guard.spec.role,
        ref=_rel(release_root, guard.path),
        path=guard.path,
        required=guard.spec.required,
        truth_or_derived=truth_or_derived,
        before=before,
        after=after,
    )


def _blocked_termination_plan(
    *,
    cr_id: str,
    work_id: str,
    termination_reason: str,
    terminal_tuple: dict[str, str],
    binding: dict[str, str] | None = None,
    authority_digest: str = "",
    source_tuple: dict[str, str] | None = None,
    read_audit: dict[str, int | bool] | None = None,
    reason: str,
) -> TerminationPlan:
    return TerminationPlan(
        decision="BLOCKED",
        cr_id=cr_id,
        work_id=work_id,
        termination_reason=termination_reason,
        terminal_tuple=terminal_tuple,
        binding=dict(binding or {}),
        authority_digest=authority_digest,
        source_tuple=dict(source_tuple or {}),
        preservation={},
        eligible_targets=(),
        targets=(),
        read_audit=dict(read_audit or {}),
        reason=reason,
    )


def plan_cr_termination(
    project_root: Path,
    cr_id: str,
    *,
    work_id: str,
    termination_status: str,
    termination_reason: str,
    expected_process_oid: str = "",
) -> TerminationPlan:
    """构建 caller 不可扩权、全目标先 guard、严格零写的 termination plan。"""

    release_root = project_root.resolve()
    terminal_tuple = dict(TERMINATION_TUPLES.get(termination_status) or {})
    normalized_reason = termination_reason.strip()
    route = None
    binding: dict[str, str] = {}
    source_tuple: dict[str, str] = {}
    authority_digest = ""
    read_audit: dict[str, int | bool] = {}
    if not CR_ID_RE.fullmatch(cr_id):
        return _blocked_termination_plan(
            cr_id=cr_id,
            work_id=work_id,
            termination_reason=normalized_reason,
            terminal_tuple=terminal_tuple,
            reason="CR id must use CR-xxx naming",
        )
    if not terminal_tuple:
        return _blocked_termination_plan(
            cr_id=cr_id,
            work_id=work_id,
            termination_reason=normalized_reason,
            terminal_tuple={},
            reason="termination status must be cancelled or superseded",
        )
    if not normalized_reason or len(normalized_reason) > 1000:
        return _blocked_termination_plan(
            cr_id=cr_id,
            work_id=work_id,
            termination_reason=normalized_reason,
            terminal_tuple=terminal_tuple,
            reason="termination reason must contain 1-1000 characters",
        )
    try:
        _safe_id(work_id, "work_id")
        route, header, guards, values, read_audit = _discover_guarded_inputs(
            release_root,
            cr_id=cr_id,
            work_id=work_id,
        )
        binding = {
            "status": "healthy",
            "project_id": route.project_id,
            "layout_version": route.layout_version,
            "route_mode": route.route_mode,
        }
        source_tuple = _source_tuple(release_root, route)
        authority_digest = _authority_digest()
        if expected_process_oid and expected_process_oid != source_tuple["process_oid"]:
            raise ValueError("process HEAD differs from expected OID")
        if header.project_id != route.project_id:
            raise ValueError("WORK.yaml project_id differs from process route")

        formal_before = _decode_utf8(values["formal_cr"], "formal CR")
        assert formal_before is not None
        fields = parse_frontmatter(formal_before)
        if str(fields.get("cr_id") or "") != cr_id:
            raise ValueError("formal CR frontmatter identity mismatch")
        source_follow_up_id = str(fields.get("source_follow_up_id") or "")
        expected_work_id = source_follow_up_id or cr_id
        if work_id != expected_work_id:
            raise ValueError("caller work_id does not match the fixed primary Work identity")

        current_tuple = {
            "lifecycle_status": cr_tracking.normalize_lifecycle_status(
                fields.get("lifecycle_status") or fields.get("status") or ""
            ),
            "readiness_status": cr_tracking.normalize_readiness_status(
                fields.get("readiness_status") or ""
            ),
            "gate_status": cr_tracking.normalize_gate_status(fields.get("gate_status") or ""),
        }
        source_errors = cr_tracking.validate_native_status_tuple(*current_tuple.values())
        target_errors = cr_tracking.validate_native_status_tuple(*terminal_tuple.values())
        if source_errors or target_errors:
            raise ValueError("; ".join([*source_errors, *target_errors]))
        if (
            current_tuple["lifecycle_status"] in FINISHED_STATUSES
            and current_tuple != terminal_tuple
        ):
            raise ValueError("a terminal CR cannot change to a different terminal tuple")
        existing_reason = str(fields.get("termination_reason") or "")
        if current_tuple == terminal_tuple and existing_reason not in {"", normalized_reason}:
            raise ValueError("terminal CR termination_reason cannot be rewritten")

        work = work_from_payload(_load_yaml_bytes(values["work"], "WORK.yaml"))
        if work.work_id != work_id or work.project_id != route.project_id:
            raise ValueError("primary Work identity/project mismatch")
        if work.status == "active":
            terminated_work = transition_work(work, "cancelled")
        elif work.status in {"cancelled", "archived"}:
            terminated_work = work
        else:
            raise ValueError(f"primary Work status is not terminable: {work.status}")

        project = project_from_payload(_load_yaml_bytes(values["project"], "PROJECT.yaml"))
        if project.project_id != route.project_id:
            raise ValueError("PROJECT.yaml identity mismatch")
        project_has_ref = work.work_ref in project.active_work_refs
        if work.status == "active" and not project_has_ref:
            raise ValueError("active primary Work is missing from PROJECT.active_work_refs")
        terminated_project = replace(
            project,
            active_work_refs=tuple(ref for ref in project.active_work_refs if ref != work.work_ref),
        )

        phase = None
        terminated_phase = None
        if header.phase_ref:
            phase = phase_from_payload(_load_yaml_bytes(values["phase"], "PHASE.yaml"))
            if phase.phase_ref != header.phase_ref or phase.project_id != route.project_id:
                raise ValueError("Phase identity differs from bootstrap Work")
            phase_has_ref = work.work_ref in phase.work_refs
            if work.status == "active" and not phase_has_ref:
                raise ValueError("active primary Work is missing from Phase.work_refs")
            terminated_phase = replace(
                phase,
                work_refs=tuple(ref for ref in phase.work_refs if ref != work.work_ref),
            )

        formal_after = render_frontmatter_fields(
            formal_before,
            {
                "lifecycle_status": terminal_tuple["lifecycle_status"],
                "readiness_status": terminal_tuple["readiness_status"],
                "gate_status": terminal_tuple["gate_status"],
                "status": terminal_tuple["lifecycle_status"],
                "termination_reason": normalized_reason,
            },
        )
        formal_after = _render_termination_body_projection(
            formal_after,
            terminal_tuple=terminal_tuple,
        )

        formal_ref = _rel(release_root, guards["formal_cr"].path)
        summary_ref = _rel(release_root, guards["summary"].path)
        summary_existing = (
            _load_json_bytes(values["summary"], "CR summary")
            if values["summary"] is not None
            else None
        )
        summary = _summary_base(
            summary_existing,
            cr_id=cr_id,
            cr_path_ref=formal_ref,
            fields=fields,
            current_tuple=current_tuple,
        )
        evidence_index_ref = str(summary.get("evidence_index_ref") or "")
        evidence_index_digest, auxiliary_reads = _evidence_digest(
            route.process_root,
            evidence_index_ref,
        )
        read_audit["auxiliary_guarded_reads"] = auxiliary_reads
        preservation = {
            "formal_non_status_digest": _formal_preserved_digest(formal_before),
            "summary_preserved_fields_digest": _summary_preserved_digest(summary),
            "evidence_index_ref": evidence_index_ref,
            "evidence_index_digest": evidence_index_digest,
        }
        preservation_digest = _canonical_digest(
            {"domain": "cr-termination-preservation-v2", **preservation}
        )
        summary.update(
            {
                "status": terminal_tuple["lifecycle_status"],
                "readiness": terminal_tuple["readiness_status"],
                "gate_status": terminal_tuple["gate_status"],
                "decision": terminal_tuple["lifecycle_status"],
                "termination_reason": normalized_reason,
                "terminal_tuple": terminal_tuple,
                "preservation_digest": preservation_digest,
                "evidence_index_ref": evidence_index_ref,
            }
        )
        if _formal_preserved_digest(formal_after) != preservation["formal_non_status_digest"]:
            raise ValueError("formal CR preservation projection changed")
        if _summary_preserved_digest(summary) != preservation["summary_preserved_fields_digest"]:
            raise ValueError("CR summary preservation projection changed")
        summary_after = (
            json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        )

        ledger_before = _decode_utf8(values["ledger"], "CR ledger", missing="")
        assert ledger_before is not None
        ledger_event = {
            "event_id": _canonical_digest(
                {
                    "operation": TERMINATION_OPERATION,
                    "cr_id": cr_id,
                    "work_id": work_id,
                    "termination_reason": normalized_reason,
                    "terminal_tuple": terminal_tuple,
                    "preservation_digest": preservation_digest,
                }
            ),
            "event": "terminated",
            "event_type": "cr_termination",
            "id": cr_id,
            "work_id": work_id,
            "cr_type": normalize_cr_type(
                fields.get("cr_type") or fields.get("cr_kind") or "feature"
            ),
            "status": terminal_tuple["lifecycle_status"],
            "readiness": terminal_tuple["readiness_status"],
            "gate_status": terminal_tuple["gate_status"],
            "summary_ref": summary_ref,
            "full_ref": formal_ref,
            "termination_reason": normalized_reason,
            "terminal_tuple": terminal_tuple,
            "authority_digest": authority_digest,
            "source_tuple_digest": _canonical_digest(
                {"domain": "cr-termination-source-v2", **source_tuple}
            ),
            "preservation_digest": preservation_digest,
            "evidence_index_ref": evidence_index_ref,
        }
        ledger_after = _render_ledger(ledger_before, guards["ledger"].path, ledger_event)

        existing_index = (
            _load_json_bytes(values["index"], "CR-INDEX") if values["index"] is not None else None
        )
        projected_index = _project_index(
            existing_index,
            process_root=route.process_root,
            cr_id=cr_id,
            fields=fields,
            current_tuple=current_tuple,
            terminal_tuple=terminal_tuple,
            formal_ref=formal_ref,
            summary_ref=summary_ref,
        )
        index_after = (
            json.dumps(projected_index, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )

        state_after = None
        state_payload = None
        identities = {cr_id, work_id}
        if values["state"] is not None:
            state_payload = _load_json_bytes(values["state"], "STATE.current.json")
            state_relevant = any(
                _contains_identity(state_payload.get(key), identities)
                for key in (
                    "active_change",
                    "active_context_ref",
                    "pending_gate",
                    "pending_checklist_path",
                )
            )
            if state_relevant:
                state_candidate = current.build_current_state_candidate(
                    release_root,
                    {
                        "active_change": None,
                        "active_context_ref": None,
                        "pending_gate": None,
                        "pending_checklist_path": None,
                        "next_action": {
                            "type": "done",
                            "text": f"{cr_id} terminated as {terminal_tuple['lifecycle_status']}.",
                            "stop_reason": "no_remaining_route",
                        },
                    },
                    actor="meta_flow.workflow.cr_termination",
                    reason=f"terminate {cr_id}",
                    base_state=state_payload,
                )
                state_after = current.render_current_state_candidate(state_candidate)
                state_payload = state_candidate

        current_after = None
        if values["current_view"] is not None:
            current_payload = _load_json_bytes(values["current_view"], "CURRENT.json")
            current_relevant = state_after is not None or _contains_identity(
                current_payload, identities
            )
            if current_relevant:
                if state_payload is None:
                    raise ValueError(
                        "CURRENT contains target refs but STATE.current.json is missing"
                    )
                projected_current = current.build_current_entry(
                    release_root,
                    state_snapshot=state_payload,
                )
                projected_current["updated_at"] = str(
                    current_payload.get("updated_at") or "1970-01-01T00:00:00+00:00"
                )
                current_after = (
                    json.dumps(
                        projected_current,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n"
                )

        eligible: list[TerminationTarget] = [
            _make_target(
                release_root,
                guards["formal_cr"],
                values["formal_cr"],
                formal_after,
                "truth",
            ),
            _make_target(
                release_root,
                guards["work"],
                values["work"],
                (
                    _decode_utf8(values["work"], "WORK.yaml")
                    if work.status in {"cancelled", "archived"}
                    else dump_yaml(terminated_work.as_dict()) + "\n"
                ),
                "truth",
            ),
            _make_target(
                release_root,
                guards["project"],
                values["project"],
                dump_yaml(terminated_project.as_dict()) + "\n",
                "truth",
            ),
        ]
        if terminated_phase is not None:
            eligible.append(
                _make_target(
                    release_root,
                    guards["phase"],
                    values["phase"],
                    dump_yaml(terminated_phase.as_dict()) + "\n",
                    "truth",
                )
            )
        if state_after is not None:
            eligible.append(
                _make_target(
                    release_root,
                    guards["state"],
                    values["state"],
                    state_after,
                    "truth",
                )
            )
        if current_after is not None:
            eligible.append(
                _make_target(
                    release_root,
                    guards["current_view"],
                    values["current_view"],
                    current_after,
                    "derived",
                )
            )
        eligible.extend(
            (
                _make_target(
                    release_root,
                    guards["summary"],
                    values["summary"],
                    summary_after,
                    "derived",
                ),
                _make_target(
                    release_root,
                    guards["ledger"],
                    values["ledger"],
                    ledger_after,
                    "derived",
                ),
                _make_target(
                    release_root,
                    guards["index"],
                    values["index"],
                    index_after,
                    "derived",
                ),
            )
        )
        eligible_targets = tuple(sorted(eligible, key=lambda item: item.order))
        targets = tuple(item for item in eligible_targets if item.changes)
        decision = "READY" if targets else "NO_CHANGE"
        return TerminationPlan(
            decision=decision,
            cr_id=cr_id,
            work_id=work_id,
            termination_reason=normalized_reason,
            terminal_tuple=terminal_tuple,
            binding=binding,
            authority_digest=authority_digest,
            source_tuple=source_tuple,
            preservation=preservation,
            eligible_targets=eligible_targets,
            targets=targets,
            read_audit=read_audit,
        )
    except Exception as exc:
        return _blocked_termination_plan(
            cr_id=cr_id,
            work_id=work_id,
            termination_reason=normalized_reason,
            terminal_tuple=terminal_tuple,
            binding=binding,
            authority_digest=authority_digest,
            source_tuple=source_tuple,
            read_audit=read_audit,
            reason=_portable_termination_error(
                exc,
                project_root=release_root,
                process_root=route.process_root if route is not None else None,
            ),
        )


def load_termination_authorization(path: Path) -> TerminationAuthorization:
    payload = _load_json_object(path, subject="termination authorization")
    return TerminationAuthorization.from_dict(payload)


def validate_termination_authorization(
    plan: TerminationPlan,
    authorization: TerminationAuthorization,
) -> None:
    if plan.decision != "READY":
        raise ValueError("termination authorization requires one READY plan")
    if authorization.schema_version != 2:
        raise ValueError("termination authorization schema_version must be 2")
    if not isinstance(
        authorization.authorization_id, str
    ) or not SAFE_AUTHORIZATION_ID_RE.fullmatch(authorization.authorization_id):
        raise ValueError("termination authorization_id is invalid")
    if authorization.authorization_source != TERMINATION_AUTHORIZATION_SOURCE:
        raise ValueError("termination authorization_source must be typed-user-confirmation")
    if authorization.authorization_kind != TERMINATION_AUTHORIZATION_KIND:
        raise ValueError("termination authorization_kind must be cr-termination")
    if authorization.operation != TERMINATION_OPERATION:
        raise ValueError("termination authorization operation mismatch")
    if authorization.single_use is not True:
        raise ValueError("termination authorization must be single-use")
    if authorization.authority_revision != AUTHORITY_REVISION:
        raise ValueError("termination authority_revision must be 2")
    if set(authorization.source_tuple) != SOURCE_TUPLE_FIELDS:
        raise ValueError("termination source_tuple schema mismatch")
    if set(authorization.terminal_tuple) != {
        "lifecycle_status",
        "readiness_status",
        "gate_status",
    }:
        raise ValueError("termination terminal_tuple schema mismatch")
    digest_fields = (
        authorization.authority_digest,
        authorization.source_tuple_digest,
        authorization.target_set_digest,
        authorization.target_preimage_digest,
        authorization.mutation_allowlist_digest,
        authorization.preservation_digest,
        authorization.lock_preimage_digest,
        authorization.plan_digest,
    )
    if not all(isinstance(value, str) and DIGEST_RE.fullmatch(value) for value in digest_fields):
        raise ValueError("termination authorization contains an invalid digest")
    for key in ("provider_release_oid", "target_release_oid", "process_oid"):
        if not OID_RE.fullmatch(str(authorization.source_tuple.get(key) or "")):
            raise ValueError(f"termination source_tuple.{key} is invalid")
    for key in (
        "provider_implementation_digest",
        "process_git_common_dir_identity",
        "process_dirty_path_digest",
        "route_digest",
    ):
        if not DIGEST_RE.fullmatch(str(authorization.source_tuple.get(key) or "")):
            raise ValueError(f"termination source_tuple.{key} is invalid")
    if not _SAFE_ID_RE.fullmatch(str(authorization.source_tuple.get("project_id") or "")):
        raise ValueError("termination source_tuple.project_id is invalid")
    route_mode = authorization.source_tuple.get("route_mode")
    if not isinstance(route_mode, str) or route_mode not in {
        "sibling-binding",
        "relative-symlink",
    }:
        raise ValueError("termination source_tuple.route_mode is invalid")
    if authorization.source_tuple_digest != _canonical_digest(
        {"domain": "cr-termination-source-v2", **authorization.source_tuple}
    ):
        raise ValueError("termination source_tuple_digest does not match source_tuple")
    expected = (
        plan.cr_id,
        plan.work_id,
        plan.termination_reason,
        plan.terminal_tuple,
        AUTHORITY_REVISION,
        plan.authority_digest,
        plan.source_tuple,
        plan.source_tuple_digest,
        plan.target_set_digest,
        plan.target_preimage_digest,
        plan.mutation_allowlist_digest,
        plan.preservation_digest,
        plan.lock_preimage_digest,
        plan.plan_digest,
    )
    actual = (
        authorization.cr_id,
        authorization.work_id,
        authorization.termination_reason,
        authorization.terminal_tuple,
        authorization.authority_revision,
        authorization.authority_digest,
        authorization.source_tuple,
        authorization.source_tuple_digest,
        authorization.target_set_digest,
        authorization.target_preimage_digest,
        authorization.mutation_allowlist_digest,
        authorization.preservation_digest,
        authorization.lock_preimage_digest,
        authorization.plan_digest,
    )
    if actual != expected:
        raise ValueError("termination authorization does not exactly match the frozen plan")
    try:
        expires_at = datetime.fromisoformat(authorization.expires_at.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValueError("termination authorization expires_at is invalid") from exc
    if expires_at.tzinfo is None:
        raise ValueError("termination authorization expires_at must include timezone")
    if expires_at.astimezone(UTC) <= datetime.now(UTC):
        raise ValueError("termination authorization is expired")


def _current_digest_for_path(
    process_root: Path, ref: str, role: str
) -> tuple[str, bytes | None, Path]:
    relative = ref.removeprefix("process/")
    guarded = _guard_ref(process_root, _RefSpec(role, relative, False))
    value = _read_guarded(guarded)
    digest = (
        _canonical_digest({"exists": False}) if value is None else hashlib.sha256(value).hexdigest()
    )
    return digest, value, guarded.path


def _open_anchored_parent(process_root: Path, relative_ref: str) -> tuple[int, str]:
    """逐段 no-follow 打开 parent，并返回锚定的 directory fd 与 leaf 名。"""

    parts = _safe_ref_parts(relative_ref)
    if not parts:
        raise ValueError("domain target must identify one leaf")
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if not isinstance(nofollow, int) or not isinstance(directory_flag, int):
        raise ValueError("anchored no-follow directory open is unavailable")
    flags = os.O_RDONLY | nofollow | directory_flag
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor = os.open(process_root, flags)
    try:
        for part in parts[:-1]:
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor, parts[-1]
    except Exception:
        os.close(descriptor)
        raise


def _atomic_write_guarded(process_root: Path, ref: str, text: str) -> None:
    """在锚定 parent fd 内 create temp + fsync + replace。"""

    relative = ref.removeprefix("process/")
    descriptor, leaf = _open_anchored_parent(process_root, relative)
    temporary = f".{leaf}.{uuid.uuid4().hex}.tmp"
    temp_descriptor = -1
    try:
        try:
            existing = os.stat(leaf, dir_fd=descriptor, follow_symlinks=False)
        except FileNotFoundError:
            mode = 0o644
        else:
            if stat.S_ISLNK(existing.st_mode) or not stat.S_ISREG(existing.st_mode):
                raise ValueError("domain target leaf is not one regular file")
            mode = stat.S_IMODE(existing.st_mode)
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if not isinstance(nofollow, int):
            raise ValueError("anchored no-follow file create is unavailable")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        temp_descriptor = os.open(temporary, flags, mode, dir_fd=descriptor)
        value = text.encode("utf-8")
        offset = 0
        while offset < len(value):
            written = os.write(temp_descriptor, value[offset:])
            if written <= 0:
                raise OSError("anchored domain write made no progress")
            offset += written
        os.fsync(temp_descriptor)
        os.close(temp_descriptor)
        temp_descriptor = -1
        os.replace(
            temporary,
            leaf,
            src_dir_fd=descriptor,
            dst_dir_fd=descriptor,
        )
        os.fsync(descriptor)
    finally:
        if temp_descriptor >= 0:
            os.close(temp_descriptor)
        try:
            os.unlink(temporary, dir_fd=descriptor)
        except FileNotFoundError:
            pass
        os.close(descriptor)


def _unlink_guarded(process_root: Path, ref: str) -> None:
    relative = ref.removeprefix("process/")
    descriptor, leaf = _open_anchored_parent(process_root, relative)
    try:
        info = os.stat(leaf, dir_fd=descriptor, follow_symlinks=False)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise ValueError("recovery target leaf is not one regular file")
        os.unlink(leaf, dir_fd=descriptor)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _validate_recovery_role_ref(role: str, ref: str) -> None:
    patterns = {
        "formal_cr": r"process/changes/CR-\d+\.md",
        "work": r"process/works/[A-Za-z0-9._-]+/WORK\.yaml",
        "project": r"process/PROJECT\.yaml",
        "phase": r"process/phases/[A-Za-z0-9._-]+/PHASE\.yaml",
        "state": r"process/state/STATE\.current\.json",
        "current_view": r"process/current/CURRENT\.json",
        "summary": r"process/changes/summaries/CR-\d+\.summary\.json",
        "ledger": r"process/state/CR-LEDGER\.ndjson",
        "index": r"process/changes/CR-INDEX\.json",
    }
    pattern = patterns.get(role)
    if pattern is None or re.fullmatch(pattern, ref) is None:
        raise JournalBlocked("journal recovery role/ref is outside the fixed projector")


def _recover_transaction(
    journal: CoordinationJournal,
    transaction_id: str,
    process_root: Path,
    *,
    fail_recovery: bool = False,
) -> tuple[str, int]:
    records = journal.records(transaction_id)
    if not records:
        raise JournalBlocked("active transaction contains no durable record")
    if records[-1]["phase"] == "PARTIAL":
        return "PARTIAL", 0
    if records[-1]["phase"] in {"ABORTED", "COMMITTED", "RECOVERED"}:
        journal.promote_terminal(transaction_id)
        return records[-1]["phase"], 0
    attempts = [record for record in records if record["phase"] == "ATTEMPTED"]
    if not attempts:
        journal.append(
            transaction_id,
            "ABORTED",
            {"reason": "no-domain-attempt", "domain_mutation_count": 0},
        )
        journal.promote_terminal(transaction_id)
        return "ABORTED", 0
    prepared = {item["ref"]: item for item in CoordinationJournal.prepared_targets(records)}
    restored = 0
    already_before = 0
    for attempt in reversed(attempts):
        payload = attempt["payload"]
        role = str(payload["role"])
        ref = str(payload["ref"])
        _validate_recovery_role_ref(role, ref)
        target = prepared.get(ref)
        if target is None or target["role"] != role:
            journal.append(
                transaction_id,
                "PARTIAL",
                {"failure_code": "TARGET_AUTHORITY_MISMATCH", "target_ref": ref},
            )
            return "PARTIAL", restored
        if (
            target["before_digest"] != payload["before_digest"]
            or target["after_digest"] != payload["after_digest"]
        ):
            journal.append(
                transaction_id,
                "PARTIAL",
                {"failure_code": "TARGET_DIGEST_MISMATCH", "target_ref": ref},
            )
            return "PARTIAL", restored
        current_digest, _current_bytes, _path = _current_digest_for_path(process_root, ref, role)
        if current_digest == target["before_digest"]:
            already_before += 1
            continue
        if current_digest != target["after_digest"]:
            journal.append(
                transaction_id,
                "PARTIAL",
                {"failure_code": "UNKNOWN_CURRENT_DIGEST", "target_ref": ref},
            )
            return "PARTIAL", restored
        if fail_recovery:
            journal.append(
                transaction_id,
                "PARTIAL",
                {"failure_code": "RESTORE_FAILED", "target_ref": ref},
            )
            return "PARTIAL", restored
        if target["before_exists"]:
            _atomic_write_guarded(process_root, ref, target["before_text"])
            restore_mode = "write-before"
        else:
            _unlink_guarded(process_root, ref)
            restore_mode = "remove-created"
        observed, _bytes, _path = _current_digest_for_path(process_root, ref, role)
        if observed != target["before_digest"]:
            journal.append(
                transaction_id,
                "PARTIAL",
                {"failure_code": "RESTORE_READBACK_FAILED", "target_ref": ref},
            )
            return "PARTIAL", restored
        restored += 1
        journal.append(
            transaction_id,
            "RESTORED",
            {
                "attempted_record_digest": attempt["record_digest"],
                "role": role,
                "ref": ref,
                "observed_before_digest": observed,
                "restore_mode": restore_mode,
            },
        )
    journal.append(
        transaction_id,
        "RECOVERED",
        {
            "attempted_count": len(attempts),
            "restored_count": restored,
            "already_before_count": already_before,
        },
    )
    journal.promote_terminal(transaction_id)
    return "RECOVERED", restored


def _prepared_payload(
    plan: TerminationPlan,
    authorization: TerminationAuthorization,
) -> dict[str, Any]:
    return {
        "authorization_id": authorization.authorization_id,
        "authority_digest": plan.authority_digest,
        "source_tuple_digest": plan.source_tuple_digest,
        "target_set_digest": plan.target_set_digest,
        "target_preimage_digest": plan.target_preimage_digest,
        "mutation_allowlist_digest": plan.mutation_allowlist_digest,
        "preservation_digest": plan.preservation_digest,
        "plan_digest": plan.plan_digest,
        "targets": [
            target.journal_projection(sequence) for sequence, target in enumerate(plan.targets, 1)
        ],
    }


def apply_cr_termination(
    project_root: Path,
    plan: TerminationPlan,
    *,
    authorization: TerminationAuthorization | None,
    expected_plan_digest: str,
    _fail_after_replace: int | None = None,
    _fail_recovery: bool = False,
    _fault: str = "",
) -> dict[str, Any]:
    """持共享 writer lock 重建 fresh plan，再消费单次 Authorization v2。"""

    release_root = project_root.resolve()
    if plan.decision == "NO_CHANGE":
        if expected_plan_digest and expected_plan_digest != plan.plan_digest:
            return {
                "status": "BLOCKED",
                "reason": "expected plan digest does not match the current no-change plan",
                "mutation_count": 0,
            }
        route = require_process_route(release_root)
        common = _git_common_dir(route.process_root)
        private_root = common / "meta-flow" / "cr-termination-v2"
        if not private_root.exists():
            return {
                "status": "NO_CHANGE",
                "plan_digest": plan.plan_digest,
                "mutation_count": 0,
                "path_refs": [],
                "promotion_retried": 0,
            }
        retry_id = uuid.uuid4().hex
        retry_lock = _acquire_status_sync_writer_lock(
            release_root,
            transaction_id=retry_id,
            purpose="cr-terminate-v2-promotion-retry",
        )
        if retry_lock is None:
            return {
                "status": "BLOCKED",
                "reason": "process writer lock exists",
                "mutation_count": 0,
            }
        try:
            journal = CoordinationJournal(
                process_git_common_dir=common,
                project_id=route.project_id,
                process_git_common_dir_identity=plan.source_tuple[
                    "process_git_common_dir_identity"
                ],
            )
            promoted = journal.retry_terminal_promotions()
            unresolved = journal.active_transaction_ids()
            if unresolved:
                return {
                    "status": "BLOCKED",
                    "reason": "unresolved CR termination transaction exists",
                    "mutation_count": 0,
                    "unresolved_transaction_ids": list(unresolved),
                }
            return {
                "status": "NO_CHANGE",
                "plan_digest": plan.plan_digest,
                "mutation_count": 0,
                "path_refs": [],
                "promotion_retried": promoted,
            }
        except (OSError, ValueError, JournalBlocked) as exc:
            return {"status": "BLOCKED", "reason": str(exc), "mutation_count": 0}
        finally:
            _release_status_sync_writer_lock(release_root, retry_lock)
    if plan.decision != "READY":
        return {"status": "BLOCKED", "reason": plan.reason, "mutation_count": 0}
    if not expected_plan_digest or expected_plan_digest != plan.plan_digest:
        return {
            "status": "BLOCKED",
            "reason": "expected plan digest does not match the current plan",
            "mutation_count": 0,
        }
    if authorization is None:
        return {
            "status": "BLOCKED",
            "reason": "termination apply requires typed Authorization v2",
            "mutation_count": 0,
        }
    try:
        validate_termination_authorization(plan, authorization)
    except ValueError as exc:
        return {"status": "BLOCKED", "reason": str(exc), "mutation_count": 0}

    transaction_id = uuid.uuid4().hex
    lock_owner = _acquire_status_sync_writer_lock(
        release_root,
        transaction_id=transaction_id,
        purpose="cr-terminate-v2",
    )
    if lock_owner is None:
        return {
            "status": "BLOCKED",
            "reason": "process writer lock exists",
            "mutation_count": 0,
        }
    journal: CoordinationJournal | None = None
    prepared = False
    write_count = 0
    result_digest = ""
    try:
        route = require_process_route(release_root)
        common = _git_common_dir(route.process_root)
        journal_faults = {
            _fault
            for _fault in (_fault,)
            if _fault
            in {
                "claim.after_persist",
                "record.PREPARED.after_persist",
                "record.ATTEMPTED.after_persist",
                "record.APPLIED.after_persist",
                "record.COMMITTED.after_persist",
                "promotion.before_replace",
                "promotion.after_replace",
            }
        }
        journal = CoordinationJournal(
            process_git_common_dir=common,
            project_id=route.project_id,
            process_git_common_dir_identity=plan.source_tuple["process_git_common_dir_identity"],
            faults=journal_faults,
        )
        journal.retry_terminal_promotions()
        for active_id in journal.active_transaction_ids():
            recovery_status, _restored = _recover_transaction(
                journal,
                active_id,
                route.process_root,
            )
            if recovery_status == "PARTIAL":
                return {
                    "status": "BLOCKED",
                    "reason": "unresolved PARTIAL CR termination transaction exists",
                    "mutation_count": 0,
                    "rollback_evidence_ref": CoordinationJournal.private_ref(active_id),
                }

        fresh = plan_cr_termination(
            release_root,
            plan.cr_id,
            work_id=plan.work_id,
            termination_status=plan.terminal_tuple["lifecycle_status"],
            termination_reason=plan.termination_reason,
            expected_process_oid=plan.source_tuple["process_oid"],
        )
        if fresh.decision != "READY" or fresh.plan_digest != plan.plan_digest:
            return {
                "status": "BLOCKED",
                "reason": "termination authority/source/preimage drifted under writer lock",
                "mutation_count": 0,
            }
        validate_termination_authorization(fresh, authorization)
        claim_payload = {
            "schema_version": JOURNAL_SCHEMA_VERSION,
            "authorization_id": authorization.authorization_id,
            "operation": authorization.operation,
            "cr_id": authorization.cr_id,
            "work_id": authorization.work_id,
            "authority_revision": authorization.authority_revision,
            "source_tuple_digest": authorization.source_tuple_digest,
            "plan_digest": authorization.plan_digest,
        }
        journal.claim_authorization(authorization.authorization_id, claim_payload)
        if _fault == "after-claim-before-first-replace":
            raise RuntimeError("injected failure after authorization claim")
        journal.append(transaction_id, "PREPARED", _prepared_payload(fresh, authorization))
        prepared = True

        for sequence, target in enumerate(fresh.targets, 1):
            attempt = journal.append(
                transaction_id,
                "ATTEMPTED",
                {
                    "target_sequence": sequence,
                    "role": target.role,
                    "ref": target.ref,
                    "before_exists": target.before_exists,
                    "before_digest": target.before_digest,
                    "after_digest": target.after_digest,
                },
            )
            current_digest, _current_bytes, _current_path = _current_digest_for_path(
                route.process_root,
                target.ref,
                target.role,
            )
            if current_digest != target.before_digest:
                raise RuntimeError(f"termination target drift before replace: {target.ref}")
            _atomic_write_guarded(route.process_root, target.ref, target.after)
            write_count += 1
            if _fail_after_replace == sequence or _fault == "replace-before-accounting":
                raise RuntimeError(f"injected failure after replace {sequence}")
            observed = hashlib.sha256(target.path.read_bytes()).hexdigest()
            if observed != target.after_digest:
                raise RuntimeError(f"termination readback mismatch: {target.ref}")
            journal.append(
                transaction_id,
                "APPLIED",
                {
                    "attempted_record_digest": attempt["record_digest"],
                    "role": target.role,
                    "ref": target.ref,
                    "observed_after_digest": observed,
                },
            )

        result_digest = _journal_digest(
            {
                "transaction_id": transaction_id,
                "plan_digest": fresh.plan_digest,
                "authorization_id": authorization.authorization_id,
                "path_refs": [target.ref for target in fresh.targets],
            }
        )
        journal.append(
            transaction_id,
            "COMMITTED",
            {
                "attempted_count": len(fresh.targets),
                "applied_count": len(fresh.targets),
                "domain_mutation_count": len(fresh.targets),
                "result_digest": result_digest,
            },
        )
        try:
            journal.promote_terminal(transaction_id)
        except JournalBlocked as exc:
            terminal_records = journal.records(transaction_id, terminal=True)
            terminal_committed = bool(
                terminal_records and terminal_records[-1]["phase"] == "COMMITTED"
            )
            return {
                "status": "PASS",
                "transaction_id": transaction_id,
                "plan_digest": fresh.plan_digest,
                "authorization_id": authorization.authorization_id,
                "result_digest": result_digest,
                "mutation_count": len(fresh.targets),
                "path_refs": [target.ref for target in fresh.targets],
                "promotion_pending": not terminal_committed,
                "journal_evidence_ref": CoordinationJournal.private_ref(
                    transaction_id,
                    terminal=terminal_committed,
                ),
                "promotion_error": str(exc),
            }
        return {
            "status": "PASS",
            "transaction_id": transaction_id,
            "plan_digest": fresh.plan_digest,
            "authorization_id": authorization.authorization_id,
            "result_digest": result_digest,
            "mutation_count": len(fresh.targets),
            "path_refs": [target.ref for target in fresh.targets],
            "promotion_pending": False,
            "journal_evidence_ref": CoordinationJournal.private_ref(transaction_id, terminal=True),
        }
    except Exception as exc:
        status = "BLOCKED"
        recovery_status = ""
        rollback_ref = ""
        if journal is not None and prepared:
            try:
                recovery_status, _restored = _recover_transaction(
                    journal,
                    transaction_id,
                    require_process_route(release_root).process_root,
                    fail_recovery=_fail_recovery,
                )
                if recovery_status == "PARTIAL":
                    status = "PARTIAL"
                    rollback_ref = CoordinationJournal.private_ref(transaction_id)
                elif recovery_status == "RECOVERED":
                    status = "RECOVERED"
                    rollback_ref = CoordinationJournal.private_ref(transaction_id, terminal=True)
                elif recovery_status == "COMMITTED":
                    return {
                        "status": "PASS",
                        "transaction_id": transaction_id,
                        "plan_digest": plan.plan_digest,
                        "authorization_id": authorization.authorization_id,
                        "result_digest": result_digest,
                        "mutation_count": write_count,
                        "path_refs": [target.ref for target in plan.targets],
                        "promotion_pending": False,
                        "journal_evidence_ref": CoordinationJournal.private_ref(
                            transaction_id,
                            terminal=True,
                        ),
                        "recovery_status": "COMMITTED",
                    }
            except Exception as recovery_error:
                status = "PARTIAL"
                rollback_ref = CoordinationJournal.private_ref(transaction_id)
                return {
                    "status": status,
                    "transaction_id": transaction_id,
                    "plan_digest": plan.plan_digest,
                    "authorization_id": authorization.authorization_id,
                    "mutation_count": write_count,
                    "reason": str(exc),
                    "rollback_errors": [str(recovery_error)],
                    "rollback_evidence_ref": rollback_ref,
                }
        result = {
            "status": status,
            "transaction_id": transaction_id,
            "plan_digest": plan.plan_digest,
            "authorization_id": authorization.authorization_id,
            "mutation_count": write_count,
            "reason": str(exc),
            "recovery_status": recovery_status,
            "rollback_errors": [],
        }
        if rollback_ref:
            result["rollback_evidence_ref"] = rollback_ref
        return result
    finally:
        _release_status_sync_writer_lock(release_root, lock_owner)
