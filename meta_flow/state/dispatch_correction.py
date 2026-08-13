"""DispatchCorrectionV1 的零写计划与单 ledger 原子 apply。"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from meta_flow.project.onboarding_contract import canonical_digest
from meta_flow.project.process_route import _resolve_runtime_ref
from meta_flow.state import event_ledger
from meta_flow.state.projection_transaction import atomic_replace_bytes

LEDGER_REF = "process/state/AGENT-DISPATCH-LEDGER.ndjson"


def _clean(event: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in event.items() if key != "_line_no"}


def _process_oid(project_root: Path) -> str:
    process = _resolve_runtime_ref(project_root.resolve(), "process/PROJECT.yaml").parent
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=process, check=False, capture_output=True, text=True
    )
    value = result.stdout.strip().lower()
    if (
        result.returncode != 0
        or len(value) != 40
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ValueError("process HEAD must be one lowercase 40-hex OID")
    return value


def build_dispatch_correction(
    source: Mapping[str, Any],
    *,
    terminal_result: str,
    reason: str,
    evidence_refs: tuple[str, ...],
    created_at: str,
) -> dict[str, Any]:
    source_payload = _clean(source)
    source_digest = canonical_digest(source_payload)
    identity = {
        "corrects_event_id": str(source_payload.get("event_id") or ""),
        "original_event_digest": source_digest,
        "dispatch_id": str(source_payload.get("dispatch_id") or ""),
        "attempt_id": str(source_payload.get("attempt_id") or ""),
        "terminal_result": terminal_result,
    }
    return {
        "schema_version": 1,
        "event_id": f"DISPATCH-CORRECTION-{canonical_digest(identity)[:32]}",
        "event_type": "dispatch_correction",
        "dispatch_id": identity["dispatch_id"],
        "attempt_id": identity["attempt_id"],
        "corrects_event_id": identity["corrects_event_id"],
        "original_event_digest": source_digest,
        "correction_fields": {"terminal_result": terminal_result},
        "reason": reason,
        "evidence_refs": list(evidence_refs),
        "created_at": created_at,
    }


@dataclass(frozen=True)
class DispatchCorrectionPlanV1:
    source_event_ids: tuple[str, ...]
    process_oid: str
    ledger_preimage: str
    corrections: tuple[dict[str, Any], ...]
    decision: str
    blockers: tuple[str, ...]
    mutation_count: int
    schema_version: int = 1
    kind: str = "DispatchCorrectionPlanV1"

    @property
    def plan_digest(self) -> str:
        return canonical_digest(
            {
                "schema_version": self.schema_version,
                "kind": self.kind,
                "source_event_ids": list(self.source_event_ids),
                "process_oid": self.process_oid,
                "ledger_preimage": self.ledger_preimage,
                "corrections": list(self.corrections),
                "decision": self.decision,
                "blockers": list(self.blockers),
                "mutation_count": self.mutation_count,
            }
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "source_event_ids": list(self.source_event_ids),
            "process_oid": self.process_oid,
            "ledger_preimage": self.ledger_preimage,
            "corrections": list(self.corrections),
            "decision": self.decision,
            "blockers": list(self.blockers),
            "mutation_count": self.mutation_count,
            "plan_digest": self.plan_digest,
        }


def plan_dispatch_corrections(
    project_root: Path,
    *,
    source_event_ids: tuple[str, ...],
    terminal_result: str,
    reason: str,
    evidence_refs: tuple[str, ...],
    process_oid: str | None = None,
    created_at: str | None = None,
) -> DispatchCorrectionPlanV1:
    root = project_root.resolve()
    blockers: list[str] = []
    if not source_event_ids or len(set(source_event_ids)) != len(source_event_ids):
        blockers.append("SOURCE_EVENT_IDS_MUST_BE_NONEMPTY_UNIQUE")
    if not terminal_result.strip():
        blockers.append("TERMINAL_RESULT_REQUIRED")
    if not reason.strip():
        blockers.append("REASON_REQUIRED")
    if not evidence_refs or any(not ref.startswith("process/") for ref in evidence_refs):
        blockers.append("EVIDENCE_REFS_MUST_BE_NONEMPTY_PROCESS_REFS")
    ledger = _resolve_runtime_ref(root, LEDGER_REF)
    before = ledger.read_bytes() if ledger.is_file() and not ledger.is_symlink() else b""
    events, load_errors = event_ledger.load_events(ledger)
    blockers.extend(f"LEDGER_INVALID:{error}" for error in load_errors)
    by_id = {
        str(event.get("event_id") or ""): event
        for event in events
        if str(event.get("event_id") or "")
    }
    existing, correction_errors = event_ledger.dispatch_correction_index(events)
    blockers.extend(f"EXISTING_CORRECTION_INVALID:{error}" for error in correction_errors)
    corrections: list[dict[str, Any]] = []
    timestamp = created_at or datetime.now(UTC).isoformat(timespec="seconds")
    for source_id in source_event_ids:
        source = by_id.get(source_id)
        if source is None:
            blockers.append(f"SOURCE_EVENT_NOT_FOUND:{source_id}")
            continue
        correction = build_dispatch_correction(
            source,
            terminal_result=terminal_result,
            reason=reason,
            evidence_refs=evidence_refs,
            created_at=timestamp,
        )
        current = existing.get(source_id)
        if current is not None:
            if current.get("correction_fields") != correction.get("correction_fields"):
                blockers.append(f"CORRECTION_CONFLICT:{source_id}")
            continue
        simulated = [*events, correction]
        _index, errors = event_ledger.dispatch_correction_index(simulated)
        blockers.extend(f"CORRECTION_INVALID:{error}" for error in errors)
        corrections.append(correction)
    if blockers:
        decision, corrections = "BLOCKED", []
    elif corrections:
        decision = "READY"
    else:
        decision = "NO_CHANGE"
    return DispatchCorrectionPlanV1(
        source_event_ids=source_event_ids,
        process_oid=process_oid or _process_oid(root),
        ledger_preimage=sha256(before).hexdigest(),
        corrections=tuple(corrections),
        decision=decision,
        blockers=tuple(sorted(set(blockers))),
        mutation_count=len(corrections),
    )


def _replace(path: Path, content: bytes) -> None:
    atomic_replace_bytes(path, content)


def apply_dispatch_corrections(
    project_root: Path,
    *,
    plan: DispatchCorrectionPlanV1,
    expected_plan_digest: str,
    expected_process_oid: str | None = None,
    current_process_oid: str | None = None,
) -> dict[str, Any]:
    root = project_root.resolve()
    if expected_plan_digest != plan.plan_digest:
        return {"decision": "BLOCKED", "blockers": ["PLAN_DIGEST_MISMATCH"], "mutation_count": 0}
    if plan.decision == "NO_CHANGE":
        return {"decision": "NO_CHANGE", "blockers": [], "mutation_count": 0}
    if plan.decision != "READY":
        return {"decision": "BLOCKED", "blockers": list(plan.blockers), "mutation_count": 0}
    actual_oid = current_process_oid or _process_oid(root)
    if expected_process_oid is not None and expected_process_oid != plan.process_oid:
        return {
            "decision": "BLOCKED",
            "blockers": ["PROCESS_OID_EXPECTATION_MISMATCH"],
            "mutation_count": 0,
        }
    if actual_oid != plan.process_oid:
        return {"decision": "BLOCKED", "blockers": ["PROCESS_OID_DRIFT"], "mutation_count": 0}
    ledger = _resolve_runtime_ref(root, LEDGER_REF)
    before = ledger.read_bytes()
    if sha256(before).hexdigest() != plan.ledger_preimage:
        return {"decision": "BLOCKED", "blockers": ["LEDGER_PREIMAGE_DRIFT"], "mutation_count": 0}
    text = before.decode("utf-8")
    if text and not text.endswith("\n"):
        text += "\n"
    text += "".join(
        json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n" for event in plan.corrections
    )
    _replace(ledger, text.encode("utf-8"))
    return {
        "schema_version": 1,
        "kind": "DispatchCorrectionReceiptV1",
        "decision": "APPLIED",
        "appended_event_ids": [event["event_id"] for event in plan.corrections],
        "plan_digest": plan.plan_digest,
        "mutation_count": len(plan.corrections),
    }


__all__ = [
    "DispatchCorrectionPlanV1",
    "apply_dispatch_corrections",
    "build_dispatch_correction",
    "plan_dispatch_corrections",
]
