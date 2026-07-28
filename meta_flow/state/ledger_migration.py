"""Append-only、版本化的治理 ledger successor migration。"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

from meta_flow.project.onboarding_contract import canonical_digest
from meta_flow.project.process_route import _resolve_runtime_ref

LEDGER_REFS = {
    "dispatch": "process/state/AGENT-DISPATCH-LEDGER.ndjson",
    "handoff": "process/state/HANDOFF-LEDGER.ndjson",
    "checkpoint": "process/state/CHECKPOINT-LEDGER.ndjson",
    "read-expansion": "process/state/READ-EXPANSION-LEDGER.ndjson",
}
TARGET_SCHEMA_VERSION = 2
AUTHORIZATION_SOURCE = "typed-user-confirmation"
AUTHORIZATION_KIND = "ledger-migration"
APPLY_OPERATION = "ledger-migration-apply"
_OID_RE = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_AUTH_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
_AUTH_FIELDS = {
    "schema_version",
    "authorization_id",
    "authorization_source",
    "authorization_kind",
    "operation",
    "decision_ref",
    "ledger_type",
    "source_event_ids",
    "expected_process_oid",
    "expected_plan_digest",
    "single_use",
}
_SOURCE_REQUIRED_FIELDS = {
    "dispatch": {
        "event_id",
        "dispatch_id",
        "attempt_id",
        "story_id",
        "event_type",
        "canonical_role",
        "checkpoint",
        "dispatch_mode",
        "tool_name",
        "status",
        "terminal_result",
    },
    "handoff": {
        "event_id",
        "event_type",
        "stage",
        "from_role",
        "to_role",
        "context_ref",
        "status",
    },
    "checkpoint": {
        "event_id",
        "event_type",
        "checkpoint",
        "decision",
        "result_ref",
    },
    "read-expansion": {
        "event_id",
        "event_type",
        "requested_path",
        "reason",
        "stage",
        "agent",
        "context_ref",
        "allowed_by_policy",
        "estimated_tokens",
    },
}


class LedgerMigrationError(ValueError):
    """迁移输入不满足 fail-closed 契约。"""


@dataclass(frozen=True)
class LedgerMigrationPlanV1:
    ledger_type: str
    ledger_ref: str
    source_event_ids: tuple[str, ...]
    target_version: int
    process_oid: str
    ledger_preimage_digest: str
    source_preimage_digests: tuple[tuple[str, str], ...]
    successors: tuple[dict[str, Any], ...]
    decision: str
    blockers: tuple[str, ...]
    schema_version: int = 1
    kind: str = "LedgerMigrationPlanV1"

    def _unsigned_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "ledger_type": self.ledger_type,
            "ledger_ref": self.ledger_ref,
            "source_event_ids": list(self.source_event_ids),
            "target_version": self.target_version,
            "process_oid": self.process_oid,
            "ledger_preimage_digest": self.ledger_preimage_digest,
            "source_preimage_digests": dict(self.source_preimage_digests),
            "successors": list(self.successors),
            "decision": self.decision,
            "blockers": list(self.blockers),
            "mutation_count": len(self.successors) if self.decision == "READY" else 0,
        }

    @property
    def plan_digest(self) -> str:
        return canonical_digest(self._unsigned_dict())

    def as_dict(self) -> dict[str, Any]:
        return {**self._unsigned_dict(), "plan_digest": self.plan_digest}


@dataclass(frozen=True)
class MigrationAuthorizationV1:
    schema_version: int
    authorization_id: str
    authorization_source: str
    authorization_kind: str
    operation: str
    decision_ref: str
    ledger_type: str
    source_event_ids: tuple[str, ...]
    expected_process_oid: str
    expected_plan_digest: str
    single_use: bool

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> MigrationAuthorizationV1:
        if set(payload) != _AUTH_FIELDS:
            missing = sorted(_AUTH_FIELDS - set(payload))
            extra = sorted(set(payload) - _AUTH_FIELDS)
            raise LedgerMigrationError(
                f"migration authorization fields mismatch: missing={missing}, extra={extra}"
            )
        source_ids = payload.get("source_event_ids")
        if not isinstance(source_ids, list):
            raise LedgerMigrationError("source_event_ids must be a list")
        values = dict(payload)
        values["source_event_ids"] = tuple(str(item) for item in source_ids)
        return cls(**values)


def _git_output(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise LedgerMigrationError(f"git {' '.join(args)} failed for repository")
    return result.stdout.strip()


def _process_root(project_root: Path) -> Path:
    return _resolve_runtime_ref(project_root.resolve(), "process/PROJECT.yaml").parent


def _process_oid(project_root: Path) -> str:
    oid = _git_output(_process_root(project_root), "rev-parse", "HEAD").lower()
    if not _OID_RE.fullmatch(oid):
        raise LedgerMigrationError("process HEAD must be a lowercase 40-hex OID")
    return oid


def _git_common_dir(root: Path) -> Path:
    value = _git_output(root, "rev-parse", "--git-common-dir")
    path = Path(value)
    return (root / path).resolve() if not path.is_absolute() else path.resolve()


def _read_events(path: Path) -> tuple[str, list[dict[str, Any]], list[str]]:
    if not path.is_file():
        return "", [], ["LEDGER_MISSING"]
    text = path.read_text(encoding="utf-8")
    events: list[dict[str, Any]] = []
    blockers: list[str] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            blockers.append(f"INVALID_JSON_LINE:{line_number}")
            continue
        if not isinstance(event, dict):
            blockers.append(f"EVENT_NOT_OBJECT:{line_number}")
            continue
        events.append(event)
    return text, events, blockers


def _absolute_value_locations(value: Any, location: str = "$") -> list[str]:
    if isinstance(value, Mapping):
        return [
            child
            for key, item in value.items()
            for child in _absolute_value_locations(item, f"{location}.{key}")
        ]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [
            child
            for index, item in enumerate(value)
            for child in _absolute_value_locations(item, f"{location}[{index}]")
        ]
    if isinstance(value, str) and (
        Path(value).is_absolute() or PureWindowsPath(value).is_absolute()
    ):
        return [location]
    return []


def _validate_source(ledger_type: str, event: Mapping[str, Any]) -> list[str]:
    missing = sorted(
        field for field in _SOURCE_REQUIRED_FIELDS[ledger_type] if event.get(field) in {None, ""}
    )
    blockers = [f"MISSING_SOURCE_FIELD:{field}" for field in missing]
    if ledger_type == "dispatch":
        mode = str(event.get("dispatch_mode") or "")
        if mode == "inline-fallback" and not (
            event.get("approval_ref") or event.get("approved_by")
        ):
            blockers.append("MISSING_INLINE_FALLBACK_APPROVAL")
    if ledger_type == "read-expansion":
        if event.get("event_type") != "read_expansion":
            blockers.append("READ_EXPANSION_EVENT_TYPE_INVALID")
        if event.get("allowed_by_policy") is not True:
            blockers.append("READ_EXPANSION_POLICY_AUTHORIZATION_INVALID")
        if not isinstance(event.get("estimated_tokens"), int):
            blockers.append("READ_EXPANSION_ESTIMATED_TOKENS_INVALID")
    if _absolute_value_locations(event):
        blockers.append("ABSOLUTE_PATH_IN_SOURCE_EVENT")
    return blockers


def _successor(
    ledger_type: str,
    event: Mapping[str, Any],
    *,
    target_version: int,
) -> dict[str, Any]:
    source = dict(event)
    source_id = str(source["event_id"])
    source_digest = canonical_digest(source)
    identity = {
        "ledger_type": ledger_type,
        "source_event_id": source_id,
        "source_event_digest": source_digest,
        "target_version": target_version,
    }
    successor = {
        **source,
        "event_id": f"{source_id}.v{target_version}.{canonical_digest(identity)[:12]}",
        "schema_version": target_version,
        "supersedes_event_id": source_id,
        "source_event_digest": source_digest,
        "migration_kind": "append-only-successor",
    }
    return successor


def plan_ledger_migration(
    project_root: Path,
    *,
    ledger_type: str,
    source_event_ids: Sequence[str],
    target_version: int = TARGET_SCHEMA_VERSION,
) -> LedgerMigrationPlanV1:
    """生成零 mutation、logical-ref-only 的迁移计划。"""

    root = project_root.resolve()
    blockers: list[str] = []
    if ledger_type not in LEDGER_REFS:
        raise LedgerMigrationError(f"unsupported ledger type: {ledger_type}")
    if target_version != TARGET_SCHEMA_VERSION:
        blockers.append("TARGET_SCHEMA_VERSION_UNSUPPORTED")
    normalized_ids = tuple(str(item) for item in source_event_ids)
    if not normalized_ids or len(set(normalized_ids)) != len(normalized_ids):
        blockers.append("SOURCE_EVENT_IDS_MUST_BE_NONEMPTY_UNIQUE")
    ledger_ref = LEDGER_REFS[ledger_type]
    path = _resolve_runtime_ref(root, ledger_ref)
    text, events, parse_blockers = _read_events(path)
    blockers.extend(parse_blockers)
    by_id = {
        str(event.get("event_id") or ""): event
        for event in events
        if str(event.get("event_id") or "")
    }
    source_digests: list[tuple[str, str]] = []
    successors: list[dict[str, Any]] = []
    for source_id in normalized_ids:
        event = by_id.get(source_id)
        if event is None:
            blockers.append(f"SOURCE_EVENT_NOT_FOUND:{source_id}")
            continue
        source_digests.append((source_id, canonical_digest(event)))
        event_blockers = _validate_source(ledger_type, event)
        blockers.extend(f"{source_id}:{item}" for item in event_blockers)
        if event_blockers:
            continue
        successor = _successor(ledger_type, event, target_version=target_version)
        existing = [
            candidate
            for candidate in events
            if candidate.get("supersedes_event_id") == source_id
            and candidate.get("schema_version") == target_version
        ]
        if len(existing) > 1:
            blockers.append(f"MULTIPLE_SUCCESSORS:{source_id}")
        elif existing:
            if canonical_digest(existing[0]) != canonical_digest(successor):
                blockers.append(f"SUCCESSOR_CONFLICT:{source_id}")
        else:
            successors.append(successor)
    if blockers:
        decision = "BLOCKED"
        successors = []
    elif successors:
        decision = "READY"
    else:
        decision = "NO_CHANGE"
    return LedgerMigrationPlanV1(
        ledger_type=ledger_type,
        ledger_ref=ledger_ref,
        source_event_ids=normalized_ids,
        target_version=target_version,
        process_oid=_process_oid(root),
        ledger_preimage_digest=canonical_digest(text),
        source_preimage_digests=tuple(sorted(source_digests)),
        successors=tuple(successors),
        decision=decision,
        blockers=tuple(sorted(set(blockers))),
    )


def validate_migration_authorization(
    plan: LedgerMigrationPlanV1,
    authorization: MigrationAuthorizationV1,
) -> None:
    if authorization.schema_version != 1:
        raise LedgerMigrationError("authorization schema_version must be 1")
    if not _AUTH_ID_RE.fullmatch(authorization.authorization_id):
        raise LedgerMigrationError("authorization_id is invalid")
    if authorization.authorization_source != AUTHORIZATION_SOURCE:
        raise LedgerMigrationError("authorization_source mismatch")
    if authorization.authorization_kind != AUTHORIZATION_KIND:
        raise LedgerMigrationError("authorization_kind mismatch")
    if authorization.operation != APPLY_OPERATION:
        raise LedgerMigrationError("authorization operation mismatch")
    if authorization.single_use is not True:
        raise LedgerMigrationError("authorization must be single-use")
    if not authorization.decision_ref.startswith("process/checkpoints/"):
        raise LedgerMigrationError("decision_ref must be one process checkpoint logical ref")
    expected = (
        plan.ledger_type,
        plan.source_event_ids,
        plan.process_oid,
        plan.plan_digest,
    )
    actual = (
        authorization.ledger_type,
        authorization.source_event_ids,
        authorization.expected_process_oid,
        authorization.expected_plan_digest,
    )
    if actual != expected:
        raise LedgerMigrationError(
            "authorization does not match ledger/source IDs/process OID/plan digest"
        )
    if not _OID_RE.fullmatch(authorization.expected_process_oid):
        raise LedgerMigrationError("expected_process_oid is invalid")
    if not _DIGEST_RE.fullmatch(authorization.expected_plan_digest):
        raise LedgerMigrationError("expected_plan_digest is invalid")


def _claim_authorization(
    process_root: Path,
    authorization: MigrationAuthorizationV1,
) -> Path:
    path = (
        _git_common_dir(process_root)
        / "meta-flow"
        / "ledger-migration"
        / "authorizations"
        / f"{authorization.authorization_id}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "authorization_id": authorization.authorization_id,
        "operation": authorization.operation,
        "ledger_type": authorization.ledger_type,
        "plan_digest": authorization.expected_plan_digest,
        "process_oid": authorization.expected_process_oid,
    }
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            )
    except FileExistsError as exc:
        raise LedgerMigrationError("authorization was already consumed") from exc
    return path


def _atomic_write(path: Path, text: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def apply_ledger_migration(
    project_root: Path,
    *,
    plan: LedgerMigrationPlanV1,
    authorization: MigrationAuthorizationV1 | None,
) -> dict[str, Any]:
    """校验 preimage/OID/authorization 后，单次原子追加 successor events。"""

    root = project_root.resolve()
    current = plan_ledger_migration(
        root,
        ledger_type=plan.ledger_type,
        source_event_ids=plan.source_event_ids,
        target_version=plan.target_version,
    )
    if current.decision == "NO_CHANGE":
        return {
            "schema_version": 1,
            "kind": "MigrationReceiptV1",
            "decision": "NO_CHANGE",
            "ledger_type": plan.ledger_type,
            "ledger_ref": plan.ledger_ref,
            "plan_digest": plan.plan_digest,
            "appended_event_ids": [],
            "mutation_count": 0,
        }
    if current.decision != "READY":
        return {
            "schema_version": 1,
            "kind": "MigrationReceiptV1",
            "decision": "BLOCKED",
            "ledger_type": plan.ledger_type,
            "ledger_ref": plan.ledger_ref,
            "blockers": list(current.blockers),
            "mutation_count": 0,
        }
    if current.plan_digest != plan.plan_digest:
        return {
            "schema_version": 1,
            "kind": "MigrationReceiptV1",
            "decision": "BLOCKED",
            "ledger_type": plan.ledger_type,
            "ledger_ref": plan.ledger_ref,
            "blockers": ["PLAN_OR_PREIMAGE_DRIFT"],
            "mutation_count": 0,
        }
    if authorization is None:
        return {
            "schema_version": 1,
            "kind": "MigrationReceiptV1",
            "decision": "BLOCKED",
            "ledger_type": plan.ledger_type,
            "ledger_ref": plan.ledger_ref,
            "blockers": ["TYPED_AUTHORIZATION_REQUIRED"],
            "mutation_count": 0,
        }
    validate_migration_authorization(plan, authorization)
    process_root = _process_root(root)
    ledger_path = _resolve_runtime_ref(root, plan.ledger_ref)
    before = ledger_path.read_text(encoding="utf-8")
    if canonical_digest(before) != plan.ledger_preimage_digest:
        return {
            "schema_version": 1,
            "kind": "MigrationReceiptV1",
            "decision": "BLOCKED",
            "ledger_type": plan.ledger_type,
            "ledger_ref": plan.ledger_ref,
            "blockers": ["LEDGER_PREIMAGE_DRIFT"],
            "mutation_count": 0,
        }
    claim = _claim_authorization(process_root, authorization)
    lock = (
        _git_common_dir(process_root)
        / "meta-flow"
        / "ledger-migration"
        / f"{plan.ledger_type}.lock"
    )
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        with lock.open("x", encoding="utf-8") as stream:
            stream.write(plan.plan_digest + "\n")
    except FileExistsError as exc:
        claim.unlink(missing_ok=True)
        raise LedgerMigrationError("ledger migration writer lock exists") from exc
    try:
        prefix = before + ("\n" if before and not before.endswith("\n") else "")
        appended = "".join(
            json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
            for event in plan.successors
        )
        _atomic_write(ledger_path, prefix + appended)
    except Exception:
        claim.unlink(missing_ok=True)
        raise
    finally:
        lock.unlink(missing_ok=True)
    return {
        "schema_version": 1,
        "kind": "MigrationReceiptV1",
        "decision": "PASS",
        "ledger_type": plan.ledger_type,
        "ledger_ref": plan.ledger_ref,
        "plan_digest": plan.plan_digest,
        "process_oid": plan.process_oid,
        "authorization_id": authorization.authorization_id,
        "appended_event_ids": [
            str(event["event_id"]) for event in plan.successors
        ],
        "mutation_count": len(plan.successors),
    }
