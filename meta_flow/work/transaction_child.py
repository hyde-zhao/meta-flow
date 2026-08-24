"""Work coordinator 的 CURRENT/HANDOFF child transaction 单一适配入口。"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from meta_flow.state import current as state_current
from meta_flow.work import handoff as work_handoff
from meta_flow.execution_control.primitives import digest_bytes, now_utc
from meta_flow.work.lifecycle_transaction import (
    status_handoff_transaction_id,
    validate_work_close_manifest,
    work_close_manifest_path,
)

HANDOFF_TRANSACTION_ROOT_REL = Path(".meta-flow-runtime/work-handoff")


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    from meta_flow.work import lifecycle_transaction

    lifecycle_transaction._write_json_atomic(path, payload)


def _replace_bytes(path: Path, content: bytes) -> None:
    from meta_flow.work import lifecycle_transaction

    path.parent.mkdir(parents=True, exist_ok=True)
    lifecycle_transaction._replace_bytes(path, content)


def current_transaction_id(
    plan: state_current.CurrentProjectionPlanV2,
    *,
    parent_plan_digest: str,
    authorization_id: str,
) -> str:
    return state_current.current_projection_transaction_id(
        plan,
        parent_plan_digest=parent_plan_digest,
        authorization_id=authorization_id,
    )


def apply_current(
    release_root: Path,
    plan: state_current.CurrentProjectionPlanV2,
    *,
    parent_plan_digest: str,
    authorization_id: str,
) -> dict[str, Any]:
    if not plan.targets:
        return {"decision": "NO_CHANGE", "transaction_id": "", "applied_refs": []}
    return state_current.apply_current_projection_targets(
        release_root,
        plan,
        parent_plan_digest=parent_plan_digest,
        authorization_id=authorization_id,
    )


def inspect_current(release_root: Path) -> dict[str, Any]:
    return state_current.inspect_current_projection_transactions(release_root)


def current_for_parent(
    release_root: Path,
    *,
    authorization_id: str,
    parent_plan_digest: str,
) -> dict[str, Any] | None:
    return state_current.current_projection_transaction_for_parent(
        release_root,
        authorization_id=authorization_id,
        parent_plan_digest=parent_plan_digest,
    )


def recover_current(release_root: Path, transaction_id: str) -> dict[str, Any]:
    return state_current.recover_current_projection_targets(release_root, transaction_id)


def handoff_transaction_id(
    plan: work_handoff.HandoffTransitionPlanV1,
    *,
    parent_plan_digest: str,
    authorization_id: str,
) -> str:
    return status_handoff_transaction_id(
        authorization_id=authorization_id,
        parent_plan_digest=parent_plan_digest,
        handoff_plan_digest=plan.plan_digest,
        route_policy_digest=plan.route_policy_digest,
        desired_digest=plan.desired_digest,
    )


def _handoff_manifest_path(root: Path, transaction_id: str) -> Path:
    if len(transaction_id) != 32 or any(char not in "0123456789abcdef" for char in transaction_id):
        raise ValueError("handoff transaction identity is invalid")
    return root / HANDOFF_TRANSACTION_ROOT_REL / f"{transaction_id}.json"


def _validate_handoff_manifest(
    payload: Mapping[str, Any],
    *,
    expected_transaction_id: str,
) -> work_handoff.HandoffTransitionPlanV1:
    expected = {
        "schema_version",
        "kind",
        "transaction_id",
        "authorization_id",
        "parent_plan_digest",
        "state",
        "created_at",
        "updated_at",
        "attempted",
        "applied",
        "plan",
        "before_bytes_b64",
        "failure",
        "recovery_failures",
    }
    if (
        set(payload) != expected
        or payload.get("schema_version") != 1
        or payload.get("kind") != "HandoffTransitionTransactionV1"
    ):
        raise ValueError("handoff transaction manifest fields mismatch")
    if payload.get("transaction_id") != expected_transaction_id or payload.get("state") not in {
        "PREPARED",
        "APPLYING",
        "COMMITTED",
        "RECOVERED",
        "PARTIAL",
    }:
        raise ValueError("handoff transaction manifest identity/state is invalid")
    if not isinstance(payload.get("plan"), dict):
        raise ValueError("handoff transaction plan is invalid")
    plan = work_handoff.HandoffTransitionPlanV1.from_mapping(dict(payload["plan"]))
    authorization_id = str(payload.get("authorization_id") or "")
    parent_digest = str(payload.get("parent_plan_digest") or "")
    if (
        handoff_transaction_id(
            plan,
            parent_plan_digest=parent_digest,
            authorization_id=authorization_id,
        )
        != expected_transaction_id
    ):
        raise ValueError("handoff transaction parent binding mismatch")
    if (
        not isinstance(payload.get("attempted"), bool)
        or not isinstance(payload.get("applied"), bool)
        or (payload["applied"] and not payload["attempted"])
    ):
        raise ValueError("handoff transaction accounting is invalid")
    try:
        before_bytes = base64.b64decode(str(payload["before_bytes_b64"]), validate=True)
    except (TypeError, ValueError) as exc:
        raise ValueError("handoff transaction before bytes are invalid") from exc
    if (bool(before_bytes) or plan.before_exists) and digest_bytes(
        before_bytes
    ) != plan.before_digest:
        raise ValueError("handoff transaction before bytes/digest mismatch")
    if not isinstance(payload.get("recovery_failures"), list):
        raise ValueError("handoff transaction recovery failures are invalid")
    return plan


def _restore_handoff(root: Path, manifest: dict[str, Any]) -> list[str]:
    if not manifest["attempted"]:
        return []
    plan = work_handoff.HandoffTransitionPlanV1.from_mapping(dict(manifest["plan"]))
    path = work_handoff.handoff_path(root, plan.work_id)
    try:
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError("HANDOFF_TARGET_UNSAFE")
        current = path.read_bytes() if path.is_file() else b""
        if digest_bytes(current) not in {plan.before_digest, plan.desired_digest}:
            raise ValueError("HANDOFF_GENERATION_DRIFT")
        if plan.before_exists:
            _replace_bytes(
                path,
                base64.b64decode(str(manifest["before_bytes_b64"]), validate=True),
            )
        elif path.is_file():
            path.unlink()
    except (OSError, ValueError) as exc:
        return [str(exc)]
    return []


def apply_handoff(
    root: Path,
    plan: work_handoff.HandoffTransitionPlanV1,
    *,
    parent_plan_digest: str,
    authorization_id: str,
) -> dict[str, Any]:
    if not plan.target_ref:
        return {"decision": "NO_CHANGE", "transaction_id": "", "applied_refs": []}
    work_handoff.validate_handoff_transition_plan(root, plan, verify_preimage=True)
    transaction_id = handoff_transaction_id(
        plan,
        parent_plan_digest=parent_plan_digest,
        authorization_id=authorization_id,
    )
    manifest_path = _handoff_manifest_path(root, transaction_id)
    if manifest_path.exists() or manifest_path.is_symlink():
        raise ValueError("handoff child authorization was already consumed")
    runtime = manifest_path.parent
    if runtime.is_symlink() or (runtime.exists() and not runtime.is_dir()):
        raise ValueError("handoff child runtime is unsafe")
    runtime.mkdir(parents=True, exist_ok=True)
    target = work_handoff.handoff_path(root, plan.work_id)
    before = target.read_bytes() if target.is_file() else b""
    now = now_utc()
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "kind": "HandoffTransitionTransactionV1",
        "transaction_id": transaction_id,
        "authorization_id": authorization_id,
        "parent_plan_digest": parent_plan_digest,
        "state": "PREPARED",
        "created_at": now,
        "updated_at": now,
        "attempted": False,
        "applied": False,
        "plan": plan.as_dict(),
        "before_bytes_b64": base64.b64encode(before).decode("ascii"),
        "failure": "",
        "recovery_failures": [],
    }
    _validate_handoff_manifest(manifest, expected_transaction_id=transaction_id)
    _write_json_atomic(manifest_path, manifest)
    try:
        manifest["state"] = "APPLYING"
        manifest["attempted"] = True
        manifest["updated_at"] = now_utc()
        _write_json_atomic(manifest_path, manifest)
        _replace_bytes(target, plan.desired_bytes)
        manifest["applied"] = True
        manifest["updated_at"] = now_utc()
        _write_json_atomic(manifest_path, manifest)
        manifest["state"] = "COMMITTED"
        manifest["updated_at"] = now_utc()
        _write_json_atomic(manifest_path, manifest)
        return {
            "decision": "PASS",
            "transaction_id": transaction_id,
            "applied_refs": [plan.target_ref],
        }
    except Exception as exc:
        failures = _restore_handoff(root, manifest)
        manifest["state"] = "PARTIAL" if failures else "RECOVERED"
        manifest["failure"] = str(exc)
        manifest["recovery_failures"] = failures
        manifest["updated_at"] = now_utc()
        _write_json_atomic(manifest_path, manifest)
        return {
            "decision": manifest["state"],
            "transaction_id": transaction_id,
            "applied_refs": [plan.target_ref] if manifest["applied"] else [],
            "reason_codes": ["HANDOFF_CHILD_APPLY_FAILED"],
        }


def _load_handoff_children(root: Path) -> list[dict[str, Any]]:
    runtime = root / HANDOFF_TRANSACTION_ROOT_REL
    if runtime.is_symlink() or (runtime.exists() and not runtime.is_dir()):
        raise ValueError("handoff child runtime is unsafe")
    payloads: list[dict[str, Any]] = []
    if not runtime.is_dir():
        return payloads
    for path in sorted(runtime.glob("*.json")):
        if path.is_symlink() or not path.is_file():
            raise ValueError("handoff child manifest path is unsafe")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("handoff child manifest payload is invalid")
        _validate_handoff_manifest(payload, expected_transaction_id=path.stem)
        payloads.append(payload)
    return payloads


def handoff_for_parent(
    root: Path,
    *,
    authorization_id: str,
    parent_plan_digest: str,
) -> dict[str, Any] | None:
    matched = [
        payload
        for payload in _load_handoff_children(root)
        if payload["authorization_id"] == authorization_id
        and payload["parent_plan_digest"] == parent_plan_digest
    ]
    if len(matched) > 1:
        raise ValueError("status transition parent owns duplicate handoff children")
    return matched[0] if matched else None


def recover_handoff(root: Path, transaction_id: str) -> dict[str, Any]:
    path = _handoff_manifest_path(root, transaction_id)
    if path.is_symlink() or not path.is_file():
        raise ValueError("handoff child manifest is missing")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("handoff child manifest is invalid")
    _validate_handoff_manifest(manifest, expected_transaction_id=transaction_id)
    parent_path = work_close_manifest_path(root, str(manifest["authorization_id"]))
    if parent_path.is_symlink() or not parent_path.is_file():
        raise ValueError("handoff child parent manifest is missing")
    parent = json.loads(parent_path.read_text(encoding="utf-8"))
    if not isinstance(parent, dict):
        raise ValueError("handoff child parent manifest is invalid")
    validate_work_close_manifest(parent, expected_authorization_id=str(manifest["authorization_id"]))
    if parent["plan_digest"] != manifest["parent_plan_digest"]:
        raise ValueError("handoff child parent binding mismatch")
    if parent["state"] == "COMMITTED":
        raise ValueError("committed parent forbids handoff child rollback")
    if parent["state"] in {"PREPARED", "APPLYING", "PARTIAL"}:
        raise ValueError("handoff child parent requires recovery first")
    if manifest["state"] == "RECOVERED":
        return {"decision": "RECOVERED", "transaction_id": transaction_id}
    failures = _restore_handoff(root, manifest)
    manifest["state"] = "PARTIAL" if failures else "RECOVERED"
    manifest["recovery_failures"] = failures
    manifest["updated_at"] = now_utc()
    _write_json_atomic(path, manifest)
    return {
        "decision": manifest["state"],
        "transaction_id": transaction_id,
        "reason_codes": ["HANDOFF_CHILD_RECOVERY_FAILED"] if failures else [],
    }


def _digest_reachable(start: str, current: str, edges: Mapping[str, set[str]]) -> bool:
    pending = [start]
    seen: set[str] = set()
    while pending:
        candidate = pending.pop()
        if candidate == current:
            return True
        if candidate in seen:
            continue
        seen.add(candidate)
        pending.extend(edges.get(candidate, ()))
    return False


def inspect_handoff(root: Path) -> dict[str, Any]:
    findings: list[str] = []
    transactions: list[dict[str, Any]] = []
    try:
        payloads = _load_handoff_children(root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        payloads = []
        findings.append(f"HANDOFF_CHILD_MANIFEST_INVALID:{exc}")
    edges: dict[str, set[str]] = {}
    for payload in payloads:
        if payload["state"] == "COMMITTED":
            plan = work_handoff.HandoffTransitionPlanV1.from_mapping(dict(payload["plan"]))
            edges.setdefault(plan.before_digest, set()).add(plan.desired_digest)
    for payload in payloads:
        transaction_id = str(payload["transaction_id"])
        state = str(payload["state"])
        plan = work_handoff.HandoffTransitionPlanV1.from_mapping(dict(payload["plan"]))
        parent_state = "INVALID"
        try:
            parent_path = work_close_manifest_path(root, str(payload["authorization_id"]))
            parent = json.loads(parent_path.read_text(encoding="utf-8"))
            if not isinstance(parent, dict):
                raise ValueError("parent payload is invalid")
            validate_work_close_manifest(parent, expected_authorization_id=str(payload["authorization_id"]))
            if parent["plan_digest"] != payload["parent_plan_digest"]:
                raise ValueError("parent plan binding mismatch")
            parent_state = str(parent["state"])
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            findings.append(f"HANDOFF_CHILD_PARENT_INVALID:{transaction_id}:{exc}")
        if state not in {"COMMITTED", "RECOVERED"}:
            findings.append(f"HANDOFF_CHILD_UNRESOLVED:{transaction_id}:{state}")
        if state == "COMMITTED" and parent_state != "COMMITTED":
            findings.append(f"HANDOFF_CHILD_PARENT_NOT_COMMITTED:{transaction_id}:{parent_state}")
        if state == "RECOVERED" and parent_state == "COMMITTED":
            findings.append(f"HANDOFF_CHILD_PARENT_DIVERGED:{transaction_id}")
        path = work_handoff.handoff_path(root, plan.work_id)
        current = path.read_bytes() if path.is_file() and not path.is_symlink() else b""
        expected = plan.desired_digest if state == "COMMITTED" else plan.before_digest
        classification = state
        if digest_bytes(current) != expected:
            if state in {"COMMITTED", "RECOVERED"} and _digest_reachable(
                expected, digest_bytes(current), edges
            ):
                classification = "SUPERSEDED"
            else:
                findings.append(f"HANDOFF_CHILD_GENERATION_DRIFT:{transaction_id}")
        transactions.append(
            {
                "transaction_id": transaction_id,
                "authorization_id": str(payload["authorization_id"]),
                "state": state,
                "classification": classification,
                "parent_state": parent_state,
            }
        )
    return {
        "decision": "BLOCKED" if findings else "PASS",
        "transactions": transactions,
        "findings": findings,
    }


__all__ = [
    "apply_current",
    "apply_handoff",
    "current_for_parent",
    "current_transaction_id",
    "handoff_for_parent",
    "handoff_transaction_id",
    "inspect_current",
    "inspect_handoff",
    "recover_current",
    "recover_handoff",
]
