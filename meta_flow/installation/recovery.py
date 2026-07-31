"""安装生命周期的 durable journal、状态机与受限 recovery。"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from threading import Lock
from typing import Any

from meta_flow.installation.authorization import ClaimedAuthorization
from meta_flow.installation.contracts import (
    OPERATIONS,
    ContractErrorCode,
    InstallationContractError,
    require_exact_keys,
    validate_action,
    validate_portable_ref,
)

JOURNAL_SCHEMA_VERSION = 1
JOURNAL_FIELDS = (
    "schema_version",
    "transaction_id",
    "operation",
    "state",
    "plan_digest",
    "authorization_claim_ref",
    "source_identity_digest",
    "target_identity_digest",
    "started_at",
    "updated_at",
    "action_receipts",
    "terminal_receipt_ref",
)
ACTION_RECEIPT_FIELDS = (
    "action_id",
    "ordinal",
    "state",
    "target_ref",
    "before_digest",
    "after_digest",
    "preimage_ref",
    "started_at",
    "completed_at",
    "error_code",
)
JOURNAL_STATES = (
    "planned",
    "authorized",
    "applying",
    "applied",
    "rollback_pending",
    "rolled_back",
    "partial",
    "blocked",
    "receipt_missing",
    "abandoned",
)
ACTION_RECEIPT_STATES = ("planned", "applied", "verified", "compensated")
RECOVERY_ACTIONS = ("inspect", "resume", "rollback", "abandon")
ALLOWED_TRANSITIONS = {
    "planned": frozenset({"authorized", "blocked"}),
    "authorized": frozenset({"applying", "blocked"}),
    "applying": frozenset(
        {"applied", "rollback_pending", "partial", "receipt_missing"}
    ),
    "rollback_pending": frozenset({"rolled_back", "partial"}),
    "partial": frozenset({"planned", "abandoned"}),
    "blocked": frozenset({"planned"}),
    "receipt_missing": frozenset({"planned", "abandoned"}),
    "applied": frozenset(),
    "rolled_back": frozenset(),
    "abandoned": frozenset(),
}
TERMINAL_STATES = frozenset({"applied", "rolled_back", "abandoned"})

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_FORBIDDEN_PERSISTED_KEYS = frozenset(
    {"password", "token", "secret", "credential", "preimage_body", "content"}
)


class RecoveryError(InstallationContractError):
    """journal/recovery 契约型阻断。"""


@dataclass(frozen=True)
class RecoveryObservation:
    transaction_id: str
    state: str
    planned_actions: int
    applied_actions: int
    compensated_actions: int
    terminal_receipt_ref: str
    authorization_required: bool
    mutation_count: int = 0


@dataclass(frozen=True)
class RecoveryPlan:
    recovery_action: str
    recovery_of: str
    prior_state: str
    next_state: str
    action_ids: tuple[str, ...]
    authorization_id: str
    mutation_count: int = 0


class DurableJournalStore:
    """scope-local journal store，使用 atomic replace 与 digest CAS。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = Lock()

    def journal_path(self, transaction_id: str) -> Path:
        _require_id(transaction_id, field="transaction_id")
        return self.root / f"{transaction_id}.journal.json"

    def persist(
        self,
        journal: object,
        *,
        expected_digest: str | None = None,
    ) -> str:
        normalized = validate_journal(journal)
        path = self.journal_path(normalized["transaction_id"])
        rendered = _journal_bytes(normalized)
        digest = sha256(rendered).hexdigest()
        with self._lock:
            if path.exists():
                current_digest = sha256(path.read_bytes()).hexdigest()
                if expected_digest is None or current_digest != expected_digest:
                    raise RecoveryError(
                        ContractErrorCode.IDENTITY_CONFLICT,
                        "durable journal compare-and-set failed",
                    )
            elif expected_digest is not None:
                raise RecoveryError(
                    ContractErrorCode.IDENTITY_CONFLICT,
                    "durable journal preimage is missing",
                )
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(rendered)
            temporary.replace(path)
        return digest

    def load(self, transaction_id: str) -> dict[str, Any]:
        path = self.journal_path(transaction_id)
        if not path.is_file():
            raise RecoveryError(
                ContractErrorCode.MISSING_KEY,
                "durable journal is missing",
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RecoveryError(
                ContractErrorCode.NONCANONICAL_VALUE,
                "durable journal cannot be decoded",
            ) from exc
        return validate_journal(payload)


def create_journal(
    claimed_context: ClaimedAuthorization,
    *,
    operation: str,
    source_identity_digest: str,
    target_identity_digest: str,
    timestamp: str,
) -> dict[str, Any]:
    """从已 claim context 创建 ``authorized`` journal。"""

    if not isinstance(claimed_context, ClaimedAuthorization):
        raise RecoveryError(
            ContractErrorCode.IDENTITY_CONFLICT,
            "journal creation requires claimed authorization",
        )
    payload = {
        "schema_version": JOURNAL_SCHEMA_VERSION,
        "transaction_id": claimed_context.transaction_id,
        "operation": operation,
        "state": "authorized",
        "plan_digest": claimed_context.plan_digest,
        "authorization_claim_ref": (
            f"authorization-claims/{claimed_context.authorization_id}"
        ),
        "source_identity_digest": source_identity_digest,
        "target_identity_digest": target_identity_digest,
        "started_at": timestamp,
        "updated_at": timestamp,
        "action_receipts": [],
        "terminal_receipt_ref": "",
    }
    return validate_journal(payload)


def validate_journal(payload: object) -> dict[str, Any]:
    journal = _require_recovery_keys(payload, JOURNAL_FIELDS, field="journal")
    normalized = {key: deepcopy(journal[key]) for key in JOURNAL_FIELDS}
    if normalized["schema_version"] != JOURNAL_SCHEMA_VERSION:
        raise RecoveryError(
            ContractErrorCode.INVALID_ENUM,
            "journal.schema_version must be 1",
        )
    _require_id(normalized["transaction_id"], field="journal.transaction_id")
    if normalized["operation"] not in OPERATIONS:
        raise RecoveryError(
            ContractErrorCode.INVALID_ENUM,
            "journal.operation is not canonical",
        )
    if normalized["state"] not in JOURNAL_STATES:
        raise RecoveryError(
            ContractErrorCode.INVALID_ENUM,
            "journal.state is not canonical",
        )
    for field in (
        "plan_digest",
        "source_identity_digest",
        "target_identity_digest",
    ):
        _require_digest(normalized[field], field=f"journal.{field}")
    validate_portable_ref(
        normalized["authorization_claim_ref"],
        field="journal.authorization_claim_ref",
    )
    _require_timestamp(normalized["started_at"], field="journal.started_at")
    _require_timestamp(normalized["updated_at"], field="journal.updated_at")
    if normalized["terminal_receipt_ref"]:
        validate_portable_ref(
            normalized["terminal_receipt_ref"],
            field="journal.terminal_receipt_ref",
        )
    receipts = normalized["action_receipts"]
    if not isinstance(receipts, list):
        raise RecoveryError(
            ContractErrorCode.NONCANONICAL_VALUE,
            "journal.action_receipts must be a list",
        )
    normalized["action_receipts"] = [
        validate_action_receipt(receipt, index=index)
        for index, receipt in enumerate(receipts)
    ]
    action_ids = [receipt["action_id"] for receipt in normalized["action_receipts"]]
    ordinals = [receipt["ordinal"] for receipt in normalized["action_receipts"]]
    if len(action_ids) != len(set(action_ids)) or len(ordinals) != len(set(ordinals)):
        raise RecoveryError(
            ContractErrorCode.NONCANONICAL_VALUE,
            "journal action receipts must have unique action_id and ordinal",
        )
    _reject_forbidden_keys(normalized)
    return normalized


def validate_action_receipt(
    payload: object,
    *,
    index: int = 0,
) -> dict[str, Any]:
    receipt = _require_recovery_keys(
        payload,
        ACTION_RECEIPT_FIELDS,
        field=f"journal.action_receipts[{index}]",
    )
    normalized = {key: deepcopy(receipt[key]) for key in ACTION_RECEIPT_FIELDS}
    _require_id(
        normalized["action_id"],
        field=f"journal.action_receipts[{index}].action_id",
    )
    if (
        not isinstance(normalized["ordinal"], int)
        or isinstance(normalized["ordinal"], bool)
        or normalized["ordinal"] < 1
    ):
        raise RecoveryError(
            ContractErrorCode.NONCANONICAL_VALUE,
            "action receipt ordinal must be positive",
        )
    if normalized["state"] not in ACTION_RECEIPT_STATES:
        raise RecoveryError(
            ContractErrorCode.INVALID_ENUM,
            "action receipt state is not canonical",
        )
    validate_portable_ref(
        normalized["target_ref"],
        field=f"journal.action_receipts[{index}].target_ref",
    )
    validate_portable_ref(
        normalized["preimage_ref"],
        field=f"journal.action_receipts[{index}].preimage_ref",
    )
    for field in ("before_digest", "after_digest"):
        if normalized[field]:
            _require_digest(
                normalized[field],
                field=f"journal.action_receipts[{index}].{field}",
            )
    _require_timestamp(
        normalized["started_at"],
        field=f"journal.action_receipts[{index}].started_at",
    )
    if normalized["completed_at"]:
        _require_timestamp(
            normalized["completed_at"],
            field=f"journal.action_receipts[{index}].completed_at",
        )
    if not isinstance(normalized["error_code"], str):
        raise RecoveryError(
            ContractErrorCode.NONCANONICAL_VALUE,
            "action receipt error_code must be a string",
        )
    return normalized


def transition(
    journal: object,
    next_state: str,
    *,
    timestamp: str,
) -> dict[str, Any]:
    """执行唯一状态表中的一步 transition。"""

    normalized = validate_journal(journal)
    if next_state not in JOURNAL_STATES:
        raise RecoveryError(
            ContractErrorCode.INVALID_ENUM,
            f"unknown journal state: {next_state}",
        )
    if next_state not in ALLOWED_TRANSITIONS[normalized["state"]]:
        raise RecoveryError(
            ContractErrorCode.IDENTITY_CONFLICT,
            f"illegal journal transition: {normalized['state']}->{next_state}",
        )
    updated = deepcopy(normalized)
    updated["state"] = next_state
    updated["updated_at"] = timestamp
    return validate_journal(updated)


def record_action_started(
    journal: object,
    action: object,
    *,
    preimage_ref: str,
    before_digest: str,
    timestamp: str,
) -> dict[str, Any]:
    """在 executor 写入前记录 durable preimage 与 planned receipt。"""

    normalized = validate_journal(journal)
    exact_action = validate_action(action)
    if normalized["state"] == "authorized":
        normalized = transition(normalized, "applying", timestamp=timestamp)
    if normalized["state"] != "applying":
        raise RecoveryError(
            ContractErrorCode.IDENTITY_CONFLICT,
            "action can only start while journal is applying",
        )
    if any(
        receipt["action_id"] == exact_action["action_id"]
        for receipt in normalized["action_receipts"]
    ):
        raise RecoveryError(
            ContractErrorCode.IDENTITY_CONFLICT,
            "action receipt already exists",
        )
    validate_portable_ref(preimage_ref, field="preimage_ref")
    if before_digest:
        _require_digest(before_digest, field="before_digest")
    updated = deepcopy(normalized)
    updated["action_receipts"].append(
        {
            "action_id": exact_action["action_id"],
            "ordinal": exact_action["ordinal"],
            "state": "planned",
            "target_ref": exact_action["target_ref"],
            "before_digest": before_digest,
            "after_digest": "",
            "preimage_ref": preimage_ref,
            "started_at": timestamp,
            "completed_at": "",
            "error_code": "",
        }
    )
    updated["updated_at"] = timestamp
    return validate_journal(updated)


def record_action_outcome(
    journal: object,
    *,
    action_id: str,
    after_digest: str,
    error_code: str,
    timestamp: str,
) -> dict[str, Any]:
    """记录 executor 的真实 after/error；不推断 terminal success。"""

    normalized = validate_journal(journal)
    if normalized["state"] != "applying":
        raise RecoveryError(
            ContractErrorCode.IDENTITY_CONFLICT,
            "action outcome requires applying journal",
        )
    if after_digest:
        _require_digest(after_digest, field="after_digest")
    updated = deepcopy(normalized)
    matching = [
        receipt
        for receipt in updated["action_receipts"]
        if receipt["action_id"] == action_id
    ]
    if len(matching) != 1 or matching[0]["state"] != "planned":
        raise RecoveryError(
            ContractErrorCode.IDENTITY_CONFLICT,
            "action outcome has no unique planned receipt",
        )
    matching[0]["state"] = "applied"
    matching[0]["after_digest"] = after_digest
    matching[0]["completed_at"] = timestamp
    matching[0]["error_code"] = error_code
    updated["updated_at"] = timestamp
    return validate_journal(updated)


def finalize_journal(
    journal: object,
    *,
    terminal_state: str,
    terminal_receipt_ref: str,
    timestamp: str,
) -> dict[str, Any]:
    """写入唯一 terminal ref；receipt 写失败用空 ref + receipt_missing。"""

    normalized = validate_journal(journal)
    if normalized["terminal_receipt_ref"]:
        raise RecoveryError(
            ContractErrorCode.IDENTITY_CONFLICT,
            "terminal receipt already exists",
        )
    if terminal_state not in {
        "applied",
        "rolled_back",
        "partial",
        "blocked",
        "receipt_missing",
        "abandoned",
    }:
        raise RecoveryError(
            ContractErrorCode.INVALID_ENUM,
            "terminal state is not supported",
        )
    updated = (
        normalized
        if normalized["state"] == terminal_state
        else transition(normalized, terminal_state, timestamp=timestamp)
    )
    updated = deepcopy(updated)
    if terminal_state == "receipt_missing":
        if terminal_receipt_ref:
            raise RecoveryError(
                ContractErrorCode.NONCANONICAL_VALUE,
                "receipt_missing must not invent a terminal receipt ref",
            )
    else:
        validate_portable_ref(
            terminal_receipt_ref,
            field="terminal_receipt_ref",
        )
        updated["terminal_receipt_ref"] = terminal_receipt_ref
    updated["updated_at"] = timestamp
    return validate_journal(updated)


def inspect_journal(journal: object) -> RecoveryObservation:
    """只读解释 journal，不消费 authorization。"""

    normalized = validate_journal(journal)
    return RecoveryObservation(
        transaction_id=normalized["transaction_id"],
        state=normalized["state"],
        planned_actions=len(normalized["action_receipts"]),
        applied_actions=sum(
            receipt["state"] in {"applied", "verified", "compensated"}
            for receipt in normalized["action_receipts"]
        ),
        compensated_actions=sum(
            receipt["state"] == "compensated"
            for receipt in normalized["action_receipts"]
        ),
        terminal_receipt_ref=normalized["terminal_receipt_ref"],
        authorization_required=False,
    )


def recover(
    journal: object,
    recovery_action: str,
    *,
    new_claim_context: ClaimedAuthorization | None = None,
    current_digests: Mapping[str, str] | None = None,
    available_preimage_refs: frozenset[str] = frozenset(),
) -> RecoveryObservation | RecoveryPlan:
    """生成受限 recovery plan；本函数本身不写 target。"""

    normalized = validate_journal(journal)
    if recovery_action not in RECOVERY_ACTIONS:
        raise RecoveryError(
            ContractErrorCode.INVALID_ENUM,
            f"unknown recovery action: {recovery_action}",
        )
    if recovery_action == "inspect":
        if new_claim_context is not None:
            raise RecoveryError(
                ContractErrorCode.NONCANONICAL_VALUE,
                "inspect must not consume authorization",
            )
        return inspect_journal(normalized)
    if not isinstance(new_claim_context, ClaimedAuthorization):
        raise RecoveryError(
            ContractErrorCode.IDENTITY_CONFLICT,
            f"{recovery_action} requires one new claimed authorization",
        )
    if new_claim_context.authorization_id in normalized["authorization_claim_ref"]:
        raise RecoveryError(
            ContractErrorCode.IDENTITY_CONFLICT,
            "recovery cannot reuse the original authorization",
        )
    if recovery_action == "abandon":
        if normalized["state"] not in {"partial", "receipt_missing"}:
            raise RecoveryError(
                ContractErrorCode.IDENTITY_CONFLICT,
                "abandon requires partial or receipt_missing",
            )
        return RecoveryPlan(
            recovery_action="abandon",
            recovery_of=normalized["transaction_id"],
            prior_state=normalized["state"],
            next_state="abandoned",
            action_ids=(),
            authorization_id=new_claim_context.authorization_id,
        )
    if normalized["state"] not in {"partial", "blocked", "receipt_missing"}:
        raise RecoveryError(
            ContractErrorCode.IDENTITY_CONFLICT,
            f"{recovery_action} is not allowed from {normalized['state']}",
        )
    if recovery_action == "resume":
        pending = tuple(
            receipt["action_id"]
            for receipt in normalized["action_receipts"]
            if receipt["state"] == "planned"
        )
        return RecoveryPlan(
            recovery_action="resume",
            recovery_of=normalized["transaction_id"],
            prior_state=normalized["state"],
            next_state="planned",
            action_ids=pending,
            authorization_id=new_claim_context.authorization_id,
        )

    current = current_digests or {}
    rollback_ids: list[str] = []
    for receipt in reversed(normalized["action_receipts"]):
        if receipt["state"] not in {"applied", "verified"}:
            continue
        if (
            not receipt["after_digest"]
            or current.get(receipt["target_ref"]) != receipt["after_digest"]
            or receipt["preimage_ref"] not in available_preimage_refs
        ):
            raise RecoveryError(
                ContractErrorCode.IDENTITY_CONFLICT,
                "rollback digest/preimage guard failed",
            )
        rollback_ids.append(receipt["action_id"])
    return RecoveryPlan(
        recovery_action="rollback",
        recovery_of=normalized["transaction_id"],
        prior_state=normalized["state"],
        next_state="rollback_pending",
        action_ids=tuple(rollback_ids),
        authorization_id=new_claim_context.authorization_id,
    )


def journal_digest(journal: object) -> str:
    return sha256(_journal_bytes(validate_journal(journal))).hexdigest()


def _require_id(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise RecoveryError(
            ContractErrorCode.NONCANONICAL_VALUE,
            f"{field} must be one portable identifier",
        )
    return value


def _require_recovery_keys(
    payload: object,
    expected: tuple[str, ...],
    *,
    field: str,
) -> Mapping[str, Any]:
    try:
        return require_exact_keys(payload, expected, field=field)
    except InstallationContractError as exc:
        raise RecoveryError(
            exc.code,
            str(exc).split(": ", 1)[-1],
        ) from exc


def _require_digest(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise RecoveryError(
            ContractErrorCode.NONCANONICAL_VALUE,
            f"{field} must be one lowercase 64-hex digest",
        )
    return value


def _require_timestamp(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise RecoveryError(
            ContractErrorCode.NONCANONICAL_VALUE,
            f"{field} must be ISO-8601",
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RecoveryError(
            ContractErrorCode.NONCANONICAL_VALUE,
            f"{field} must be ISO-8601",
        ) from exc
    if parsed.tzinfo is None:
        raise RecoveryError(
            ContractErrorCode.NONCANONICAL_VALUE,
            f"{field} requires timezone",
        )
    return value


def _reject_forbidden_keys(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in _FORBIDDEN_PERSISTED_KEYS:
                raise RecoveryError(
                    ContractErrorCode.UNKNOWN_KEY,
                    f"journal contains forbidden persisted key: {key}",
                )
            _reject_forbidden_keys(item)
    elif isinstance(value, list):
        for item in value:
            _reject_forbidden_keys(item)


def _journal_bytes(journal: Mapping[str, Any]) -> bytes:
    return json.dumps(
        journal,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


__all__ = [
    "ACTION_RECEIPT_FIELDS",
    "ACTION_RECEIPT_STATES",
    "ALLOWED_TRANSITIONS",
    "JOURNAL_FIELDS",
    "JOURNAL_SCHEMA_VERSION",
    "JOURNAL_STATES",
    "RECOVERY_ACTIONS",
    "TERMINAL_STATES",
    "DurableJournalStore",
    "RecoveryError",
    "RecoveryObservation",
    "RecoveryPlan",
    "create_journal",
    "finalize_journal",
    "inspect_journal",
    "journal_digest",
    "record_action_outcome",
    "record_action_started",
    "recover",
    "transition",
    "validate_action_receipt",
    "validate_journal",
]
