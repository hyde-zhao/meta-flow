"""Revision-aware Decision Bundle and independently evidenced subgates."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

BUNDLE_EVENT_TYPES = {
    "bundle_authorized",
    "bundle_started",
    "bundle_completed",
    "bundle_stopped",
}
SUBGATE_EVENT_TYPES = {
    "subgate_planned",
    "subgate_started",
    "subgate_passed",
    "subgate_failed",
    "subgate_blocked",
    "subgate_skipped_by_stop",
    "subgate_retry_authorized",
    "subgate_reauthorized_after_retry",
}
SUBGATE_STATES = {
    "planned",
    "authorized",
    "started",
    "passed",
    "failed",
    "blocked",
    "not-started-by-stop-propagation",
}
STOP_RESULTS = {"failed", "blocked"}


@dataclass(frozen=True)
class BundleFinding:
    code: str
    message: str


def _canonical_digest(payload: object) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def subgate_idempotency_key(
    bundle_id: str,
    revision: int,
    subgate_id: str,
    attempt: int,
) -> str:
    """Return the stable semantic identity for one subgate attempt."""

    if not bundle_id or revision < 1 or not subgate_id or attempt < 1:
        raise ValueError("bundle/revision/subgate/attempt identity is invalid")
    return _canonical_digest(
        {
            "bundle_id": bundle_id,
            "revision": revision,
            "subgate_id": subgate_id,
            "attempt": attempt,
        }
    )


def build_retry_revalidation_receipt(
    payload: Mapping[str, Any],
    *,
    subgate_id: str,
    reviewed_attempt: int,
    approved_attempt: int,
    reviewed_at: str,
) -> dict[str, Any]:
    """Freeze the facts that permit one same-revision execution retry.

    The receipt is evidence only.  It does not broaden the bundle's original
    authorization and becomes invalid as soon as facts, scope, or authz drift.
    """

    findings = validate_bundle(payload)
    if findings:
        raise ValueError("invalid Decision Bundle: " + "; ".join(item.message for item in findings))
    if not subgate_id or reviewed_attempt < 1 or approved_attempt != reviewed_attempt + 1:
        raise ValueError("retry receipt requires one exact attempt+1 transition")
    if subgate_id not in {str(item["id"]) for item in payload["subgates"]}:
        raise ValueError(f"unknown or unauthorized subgate: {subgate_id}")
    return {
        "subgate_id": subgate_id,
        "reviewed_attempt": reviewed_attempt,
        "approved_attempt": approved_attempt,
        "expected_facts": copy.deepcopy(payload["expected_facts"]),
        "scope_digest": str(payload["scope_digest"]),
        "authorization_id": str(payload["authorization_snapshot"]["authorization_id"]),
        "reviewed_at": reviewed_at,
    }


def _validate_retry_revalidation(
    payload: Mapping[str, Any],
    receipt: Mapping[str, Any] | None,
    *,
    subgate_id: str,
    reviewed_attempt: int,
    approved_attempt: int,
) -> None:
    if not isinstance(receipt, Mapping):
        raise ValueError("execution retry requires an explicit revalidation receipt")
    expected = {
        "subgate_id": subgate_id,
        "reviewed_attempt": reviewed_attempt,
        "approved_attempt": approved_attempt,
        "expected_facts": payload["expected_facts"],
        "scope_digest": str(payload["scope_digest"]),
        "authorization_id": str(payload["authorization_snapshot"]["authorization_id"]),
    }
    mismatched = [key for key, value in expected.items() if receipt.get(key) != value]
    if mismatched:
        raise ValueError(
            "retry revalidation receipt drifted: " + ", ".join(sorted(mismatched))
        )
    if not str(receipt.get("reviewed_at") or ""):
        raise ValueError("retry revalidation receipt is missing reviewed_at")


def validate_bundle(payload: Mapping[str, Any]) -> list[BundleFinding]:
    """Validate the bundle envelope without granting or executing authority."""

    findings: list[BundleFinding] = []
    required = {
        "bundle_id",
        "revision",
        "work_id",
        "authorization_snapshot",
        "expected_facts",
        "scope_digest",
        "subgates",
        "stop_policy",
        "created_at",
    }
    for field in sorted(required - set(payload)):
        findings.append(BundleFinding("missing_field", f"missing required field: {field}"))
    if findings:
        return findings
    if not isinstance(payload.get("revision"), int) or int(payload["revision"]) < 1:
        findings.append(BundleFinding("revision", "revision must be a positive integer"))
    scope_digest = str(payload.get("scope_digest") or "")
    if len(scope_digest) != 64 or any(char not in "0123456789abcdef" for char in scope_digest):
        findings.append(BundleFinding("scope_digest", "scope_digest must be one lowercase SHA-256 digest"))
    expected = payload.get("expected_facts")
    expected_keys = {"release_oid", "process_oid", "branch", "dirty_path_digest"}
    if not isinstance(expected, Mapping) or not expected_keys.issubset(expected):
        findings.append(BundleFinding("expected_facts", "expected_facts is incomplete"))
    authorization = payload.get("authorization_snapshot")
    authorization_keys = {
        "authorization_id",
        "authorized_by",
        "authorized_at",
        "exact_subgate_ids",
        "excluded_actions",
        "expiry_or_revalidation_rule",
    }
    if not isinstance(authorization, Mapping) or not authorization_keys.issubset(authorization):
        findings.append(BundleFinding("authorization_snapshot", "authorization_snapshot is incomplete"))
        authorized_ids: list[str] = []
    else:
        authorized_ids = [str(item) for item in authorization.get("exact_subgate_ids") or []]
    subgates = payload.get("subgates")
    if not isinstance(subgates, list) or not subgates:
        findings.append(BundleFinding("subgates", "subgates must be one non-empty list"))
        return findings
    seen_ids: set[str] = set()
    seen_orders: set[int] = set()
    actual_ids: list[str] = []
    for offset, subgate in enumerate(subgates, 1):
        if not isinstance(subgate, Mapping):
            findings.append(BundleFinding("subgate_type", f"subgates[{offset}] must be an object"))
            continue
        required_subgate = {
            "id",
            "order",
            "action",
            "preconditions",
            "authorization_required",
            "evidence_refs",
            "result",
        }
        missing = sorted(required_subgate - set(subgate))
        if missing:
            findings.append(BundleFinding("subgate_fields", f"subgates[{offset}] missing: {','.join(missing)}"))
        subgate_id = str(subgate.get("id") or "")
        order = subgate.get("order")
        result = str(subgate.get("result") or "")
        if not subgate_id or subgate_id in seen_ids:
            findings.append(BundleFinding("subgate_id", f"subgates[{offset}] has empty or duplicate id"))
        else:
            seen_ids.add(subgate_id)
            actual_ids.append(subgate_id)
        if not isinstance(order, int) or order < 1 or order in seen_orders:
            findings.append(BundleFinding("subgate_order", f"subgates[{offset}] has invalid or duplicate order"))
        else:
            seen_orders.add(order)
        if result not in SUBGATE_STATES:
            findings.append(BundleFinding("subgate_state", f"subgates[{offset}] has invalid result: {result}"))
    if seen_orders and seen_orders != set(range(1, len(subgates) + 1)):
        findings.append(BundleFinding("subgate_order", "subgate orders must be contiguous from 1"))
    if authorized_ids != actual_ids:
        findings.append(BundleFinding("authorization_scope", "authorized subgate IDs must exactly match bundle subgates"))
    stop_policy = payload.get("stop_policy")
    if not isinstance(stop_policy, Mapping) or set(stop_policy.get("stop_results") or []) != STOP_RESULTS:
        findings.append(BundleFinding("stop_policy", "stop_policy must stop on failed and blocked"))
    return findings


def execute_subgate_result(
    payload: Mapping[str, Any],
    *,
    subgate_id: str,
    result: str,
    attempt: int,
    observed_at: str,
    evidence_refs: Sequence[str] = (),
    retry_revalidation: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Record one result and deterministically propagate stop state.

    The caller still owns the real action.  This function only records the
    independently checked outcome and never broadens authorization.
    """

    findings = validate_bundle(payload)
    if findings:
        raise ValueError("invalid Decision Bundle: " + "; ".join(item.message for item in findings))
    if result not in {"passed", "failed", "blocked"}:
        raise ValueError("subgate result must be passed, failed, or blocked")
    if not isinstance(attempt, int) or attempt < 1:
        raise ValueError("subgate attempt must be a positive integer")
    updated = copy.deepcopy(dict(payload))
    subgates = sorted(updated["subgates"], key=lambda item: int(item["order"]))
    target_index = next((index for index, item in enumerate(subgates) if item["id"] == subgate_id), None)
    if target_index is None:
        raise ValueError(f"unknown or unauthorized subgate: {subgate_id}")
    for prior in subgates[:target_index]:
        if prior["result"] != "passed":
            raise ValueError(f"prior subgate has not passed: {prior['id']}")
    target = subgates[target_index]
    retrying = False
    retry_events: list[dict[str, Any]] = []
    if target["result"] in {"passed", "failed", "blocked"}:
        prior_result = str(target["result"])
        prior_attempt = int(target.get("attempt") or 1)
        if prior_result == result and attempt == prior_attempt:
            return updated, []
        if prior_result == "passed":
            raise ValueError(f"passed subgate cannot be execution-retried: {subgate_id}")
        if attempt != prior_attempt + 1:
            raise ValueError(
                f"execution retry must use attempt {prior_attempt + 1}: {subgate_id}"
            )
        _validate_retry_revalidation(
            updated,
            retry_revalidation,
            subgate_id=subgate_id,
            reviewed_attempt=prior_attempt,
            approved_attempt=attempt,
        )
        retrying = True
        retry_key = _canonical_digest(
            {
                "idempotency_key": subgate_idempotency_key(
                    str(updated["bundle_id"]), int(updated["revision"]), subgate_id, attempt
                ),
                "event_type": "subgate_retry_authorized",
            }
        )
        retry_events.append(
            {
                "event_id": retry_key,
                "event_type": "subgate_retry_authorized",
                "gate": subgate_id,
                "status": "authorized",
                "bundle_id": updated["bundle_id"],
                "bundle_revision": updated["revision"],
                "work_id": updated["work_id"],
                "attempt": attempt,
                "prior_attempt": prior_attempt,
                "prior_result": prior_result,
                "revalidation_receipt_digest": _canonical_digest(dict(retry_revalidation or {})),
                "observed_at": observed_at,
            }
        )
    target["result"] = result
    target["evidence_refs"] = list(evidence_refs)
    target["attempt"] = attempt
    event_type = f"subgate_{result}"
    key = subgate_idempotency_key(
        str(updated["bundle_id"]), int(updated["revision"]), subgate_id, attempt
    )
    events = [
        *retry_events,
        {
            "event_id": key,
            "event_type": event_type,
            "gate": subgate_id,
            "status": result,
            "bundle_id": updated["bundle_id"],
            "bundle_revision": updated["revision"],
            "work_id": updated["work_id"],
            "attempt": attempt,
            "idempotency_key": key,
            "evidence_refs": list(evidence_refs),
            "observed_at": observed_at,
        }
    ]
    if retrying and result == "passed":
        for later in subgates[target_index + 1 :]:
            if later["result"] != "not-started-by-stop-propagation":
                continue
            later["result"] = "authorized"
            released_key = _canonical_digest(
                {
                    "bundle_id": updated["bundle_id"],
                    "revision": updated["revision"],
                    "subgate_id": later["id"],
                    "retry_gate": subgate_id,
                    "attempt": attempt,
                    "event_type": "subgate_reauthorized_after_retry",
                }
            )
            events.append(
                {
                    "event_id": released_key,
                    "event_type": "subgate_reauthorized_after_retry",
                    "gate": later["id"],
                    "status": "authorized",
                    "bundle_id": updated["bundle_id"],
                    "bundle_revision": updated["revision"],
                    "work_id": updated["work_id"],
                    "released_by": subgate_id,
                    "attempt": attempt,
                    "observed_at": observed_at,
                }
            )
    if result in STOP_RESULTS:
        for later in subgates[target_index + 1 :]:
            if later["result"] not in {"planned", "authorized"}:
                continue
            later["result"] = "not-started-by-stop-propagation"
            skipped_key = subgate_idempotency_key(
                str(updated["bundle_id"]),
                int(updated["revision"]),
                str(later["id"]),
                attempt,
            )
            events.append(
                {
                    "event_id": skipped_key,
                    "event_type": "subgate_skipped_by_stop",
                    "gate": later["id"],
                    "status": "not-started-by-stop-propagation",
                    "bundle_id": updated["bundle_id"],
                    "bundle_revision": updated["revision"],
                    "work_id": updated["work_id"],
                    "stopped_by": subgate_id,
                    "attempt": attempt,
                    "idempotency_key": skipped_key,
                    "observed_at": observed_at,
                }
            )
    updated["subgates"] = subgates
    return updated, events
