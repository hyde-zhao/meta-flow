"""P02 authority receipt/sidecar pair 的封闭 wire contract。"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from meta_flow.project.onboarding_contract import canonical_digest
from meta_flow.semantics import outcome

AUTHORITY_BINDING_SCHEMA = "Cp6RevalidationAuthorizationBindingV2"
AUTHORITY_BINDING_FIELDS = frozenset(
    {
        "schema_version",
        "receipt_ref",
        "receipt_digest",
        "cr_id",
        "story_id",
        "work_id",
        "attempt_id",
        "approval_ref",
        "approval_digest",
        "owner_authority",
        "binding_payload_digest",
        "plan_preimage_digest",
        "release_oid",
        "process_oid",
        "scope_digest",
    }
)
AUTHORITY_APPLY_FIELDS = frozenset(
    {
        "schema_version",
        "action",
        "status",
        "decision",
        "mutation_count",
        "receipt_mutation_count",
        "sidecar_mutation_count",
        "pair_state",
        "recovery_origin",
        "plan_digest",
        "targets",
        "error",
        "exit_code",
    }
)

_PROCESS_REF_RE = re.compile(r"^process/(?!.*(?:^|/)\.\.?/)[A-Za-z0-9][A-Za-z0-9._/-]*$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_OID_RE = re.compile(r"^[0-9a-f]{40}$")


def _require_process_ref(value: object, field: str) -> str:
    if not isinstance(value, str) or not _PROCESS_REF_RE.fullmatch(value) or "//" in value:
        raise ValueError(f"{field} must be a canonical process ref")
    return value


def _require_digest(value: object, field: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise ValueError(f"{field} must be a lowercase sha256 digest")
    return value


def validate_authority_binding(
    payload: Mapping[str, Any],
    *,
    receipt: Mapping[str, Any],
    approval_ref: str,
    approval_digest: str,
) -> None:
    """在 candidate digest 之前验证 sidecar 的 closed schema 与交叉字段。"""

    if set(payload) != AUTHORITY_BINDING_FIELDS:
        missing = sorted(AUTHORITY_BINDING_FIELDS - set(payload))
        extra = sorted(set(payload) - AUTHORITY_BINDING_FIELDS)
        raise ValueError(
            f"authority binding fields mismatch: missing={missing}, extra={extra}"
        )
    if payload.get("schema_version") != AUTHORITY_BINDING_SCHEMA:
        raise ValueError("authority binding schema_version mismatch")
    receipt_ref = _require_process_ref(payload.get("receipt_ref"), "receipt_ref")
    bound_approval_ref = _require_process_ref(payload.get("approval_ref"), "approval_ref")
    if bound_approval_ref != approval_ref:
        raise ValueError("authority binding approval_ref mismatch")
    if _require_digest(payload.get("approval_digest"), "approval_digest") != approval_digest:
        raise ValueError("authority binding approval_digest mismatch")
    for field in (
        "receipt_digest",
        "binding_payload_digest",
        "plan_preimage_digest",
        "scope_digest",
    ):
        _require_digest(payload.get(field), field)
    for field in ("release_oid", "process_oid"):
        value = payload.get(field)
        if not isinstance(value, str) or not _OID_RE.fullmatch(value):
            raise ValueError(f"{field} must be a lowercase Git OID")
    for field in ("cr_id", "story_id", "work_id", "attempt_id"):
        if not isinstance(payload.get(field), str) or not payload[field]:
            raise ValueError(f"authority binding {field} must be non-empty")
        if payload[field] != receipt.get(field):
            raise ValueError(f"authority binding {field} does not match receipt")
    expected_receipt_ref = (
        f"process/works/{payload['work_id']}/revalidation/{payload['attempt_id']}"
        "/receipts/authorization.json"
    )
    if receipt_ref != expected_receipt_ref:
        raise ValueError("authority binding receipt_ref is outside the exact attempt namespace")
    owner_authority = payload.get("owner_authority")
    expected_owner = "oa-v2-" + canonical_digest(
        {
            "receipt_digest": payload["receipt_digest"],
            "approval_digest": approval_digest,
            "scope_digest": payload["scope_digest"],
        }
    )
    if owner_authority != expected_owner:
        raise ValueError("authority binding owner_authority mismatch")
    expected_binding_digest = canonical_digest(
        {
            "receipt_digest": payload["receipt_digest"],
            "approval_digest": approval_digest,
            "previous_cp6_digest": receipt.get("previous_cp6_digest"),
            "superseding_cp5_digest": receipt.get("superseding_cp5_digest"),
        }
    )
    if payload.get("binding_payload_digest") != expected_binding_digest:
        raise ValueError("authority binding payload digest mismatch")
    for field in ("plan_preimage_digest", "release_oid", "process_oid", "scope_digest"):
        if payload.get(field) != receipt.get(field):
            raise ValueError(f"authority binding {field} does not match receipt")


def render_authority_apply_result(
    *,
    plan_digest: str,
    targets: Sequence[Mapping[str, Any]],
    status: str,
    receipt_count: int,
    sidecar_count: int,
    pair_state: str,
    recovery_origin: str | None,
    error: str | None = None,
) -> dict[str, Any]:
    """验证并渲染唯一的 authority apply outcome。"""

    decision = outcome.authority_apply_decision(status)
    if (
        type(receipt_count) is not int
        or type(sidecar_count) is not int
        or receipt_count not in {0, 1}
        or sidecar_count not in {0, 1}
    ):
        raise ValueError("authority issue per-target counters must be 0 or 1")
    if pair_state not in {"active", "nonactive", "unknown"}:
        raise ValueError("unknown authority issue pair state")
    if recovery_origin not in {None, "receipt-only"}:
        raise ValueError("unknown authority issue recovery origin")
    mutation_count = receipt_count + sidecar_count
    if status == "APPLIED":
        valid = (
            mutation_count,
            receipt_count,
            sidecar_count,
            pair_state,
            recovery_origin,
            error,
        ) == (2, 1, 1, "active", None, None)
    elif status == "RECOVERED":
        valid = (
            mutation_count,
            receipt_count,
            sidecar_count,
            pair_state,
            recovery_origin,
            error,
        ) == (1, 0, 1, "active", "receipt-only", None)
    elif status == "NO_CHANGE":
        valid = (
            mutation_count,
            receipt_count,
            sidecar_count,
            pair_state,
            recovery_origin,
            error,
        ) == (0, 0, 0, "active", None, None)
    elif status == "BLOCKED":
        valid = (
            mutation_count,
            receipt_count,
            sidecar_count,
            pair_state,
            recovery_origin,
            error,
        ) == (0, 0, 0, "nonactive", None, "E_FAULT_BEFORE_RECEIPT")
    elif error == "E_FAULT_AFTER_RECEIPT":
        valid = sidecar_count == 0 and pair_state in {"nonactive", "unknown"}
    elif error == "E_FAULT_AFTER_SIDECAR":
        valid = sidecar_count == 1 and pair_state in {"nonactive", "unknown"}
    elif error == "E_POSTCHECK_UNKNOWN":
        valid = pair_state == "unknown"
    else:
        valid = False
    if not valid:
        raise ValueError(f"invalid {status.lower()} authority result")

    result = {
        "schema_version": 1,
        "action": "apply",
        "status": status,
        "decision": decision,
        "mutation_count": mutation_count,
        "receipt_mutation_count": receipt_count,
        "sidecar_mutation_count": sidecar_count,
        "pair_state": pair_state,
        "recovery_origin": recovery_origin,
        "plan_digest": plan_digest,
        "targets": [dict(target) for target in targets],
        "error": None if error is None else {"code": error},
        "exit_code": 0 if decision == "PASS" else 3 if decision == "BLOCKED" else 4,
    }
    if set(result) != AUTHORITY_APPLY_FIELDS:  # pragma: no cover - owner self-check
        raise AssertionError("authority apply renderer emitted an open schema")
    return result


def render_authority_input_blocked(
    *,
    action: str,
    message: str,
    expected_plan_digest: object = "",
) -> dict[str, Any]:
    """输入错误发生在 mutation 前；apply 仍输出完整 closed wire。"""

    common: dict[str, Any] = {
        "schema_version": 1,
        "action": action,
        "status": "BLOCKED",
        "decision": "BLOCKED",
        "mutation_count": 0,
        "error": {"code": "E_INPUT_INVALID", "message": message},
        "exit_code": 3,
    }
    if action == "apply":
        common.update(
            {
                "receipt_mutation_count": 0,
                "sidecar_mutation_count": 0,
                "pair_state": "nonactive",
                "recovery_origin": None,
                "plan_digest": (
                    expected_plan_digest
                    if isinstance(expected_plan_digest, str)
                    and _DIGEST_RE.fullmatch(expected_plan_digest)
                    else ""
                ),
                "targets": [],
            }
        )
        if set(common) != AUTHORITY_APPLY_FIELDS:
            raise AssertionError("authority input blocker emitted an open apply schema")
    return common


def render_human_wire(payload: Mapping[str, Any]) -> str:
    """无损 human renderer；每个顶层字段均保留 canonical JSON value。"""

    return "\n".join(
        f"{key}={json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}"
        for key, value in sorted(payload.items())
    )


__all__ = [
    "AUTHORITY_APPLY_FIELDS",
    "AUTHORITY_BINDING_FIELDS",
    "AUTHORITY_BINDING_SCHEMA",
    "render_authority_apply_result",
    "render_authority_input_blocked",
    "render_human_wire",
    "validate_authority_binding",
]
