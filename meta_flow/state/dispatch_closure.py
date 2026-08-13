"""TerminalLineageDisposition 支持的 append-only dispatch closure 事务。"""

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
from meta_flow.workflow.terminal_lineage import load_terminal_lineage_dispositions

LEDGER_REF = "process/state/AGENT-DISPATCH-LEDGER.ndjson"
DISPOSITIONS_REF = "process/policies/TERMINAL-LINEAGE-DISPOSITIONS.json"


def _clean(event: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in event.items() if key != "_line_no"}


def _process_oid(project_root: Path) -> str:
    process_root = _resolve_runtime_ref(project_root.resolve(), "process/PROJECT.yaml").parent
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=process_root,
        check=False,
        capture_output=True,
        text=True,
    )
    value = result.stdout.strip().lower()
    if (
        result.returncode != 0
        or len(value) != 40
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ValueError("process HEAD must be one lowercase 40-hex OID")
    return value


def build_dispatch_closure(
    source: Mapping[str, Any],
    *,
    disposition: Mapping[str, Any],
    created_at: str,
) -> dict[str, Any]:
    """从 exact source 与已验证 disposition 构造确定性 closure 事件。"""

    source_payload = _clean(source)
    source_digest = canonical_digest(source_payload)
    dispatch_id = str(source_payload.get("dispatch_id") or "")
    status = event_ledger.normalize_terminal_status(disposition.get("terminal_status"))
    terminal_result = event_ledger.DISPATCH_DISPOSITION_RESULT_BY_STATUS.get(status, "")
    identity = {
        "closes_event_id": str(source_payload.get("event_id") or ""),
        "original_event_digest": source_digest,
        "disposition_key": f"dispatch:{dispatch_id}",
        "terminal_status": status,
    }
    return {
        "schema_version": 1,
        "event_id": f"DISPATCH-CLOSURE-{canonical_digest(identity)[:32]}",
        "event_type": "dispatch_attempt_closure",
        "dispatch_id": dispatch_id,
        "attempt_id": str(source_payload.get("attempt_id") or ""),
        "story_id": str(source_payload.get("story_id") or ""),
        "canonical_role": str(source_payload.get("canonical_role") or ""),
        "checkpoint": str(source_payload.get("checkpoint") or ""),
        "dispatch_mode": str(source_payload.get("dispatch_mode") or ""),
        "tool_name": str(source_payload.get("tool_name") or ""),
        "closes_event_id": identity["closes_event_id"],
        "original_event_digest": source_digest,
        "disposition_key": identity["disposition_key"],
        "disposition_source_digest": str(disposition.get("source_digest") or ""),
        "status": status,
        "terminal_result": terminal_result,
        "reason": str(disposition.get("reason") or ""),
        "evidence_refs": list(disposition.get("evidence_refs") or []),
        "evidence_digests": dict(disposition.get("evidence_digests") or {}),
        "created_at": created_at,
    }


@dataclass(frozen=True)
class DispatchClosurePlanV1:
    dispatch_ids: tuple[str, ...]
    process_oid: str
    ledger_preimage: str
    dispositions_preimage: str
    closures: tuple[dict[str, Any], ...]
    decision: str
    blockers: tuple[str, ...]
    mutation_count: int
    schema_version: int = 1
    kind: str = "DispatchClosurePlanV1"

    @property
    def plan_digest(self) -> str:
        return canonical_digest(
            {
                "schema_version": self.schema_version,
                "kind": self.kind,
                "dispatch_ids": list(self.dispatch_ids),
                "process_oid": self.process_oid,
                "ledger_preimage": self.ledger_preimage,
                "dispositions_preimage": self.dispositions_preimage,
                "closures": list(self.closures),
                "decision": self.decision,
                "blockers": list(self.blockers),
                "mutation_count": self.mutation_count,
            }
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "dispatch_ids": list(self.dispatch_ids),
            "process_oid": self.process_oid,
            "ledger_preimage": self.ledger_preimage,
            "dispositions_preimage": self.dispositions_preimage,
            "closures": list(self.closures),
            "decision": self.decision,
            "blockers": list(self.blockers),
            "mutation_count": self.mutation_count,
            "plan_digest": self.plan_digest,
        }


def plan_dispatch_closures(
    project_root: Path,
    *,
    dispatch_ids: tuple[str, ...],
    process_oid: str | None = None,
    created_at: str | None = None,
) -> DispatchClosurePlanV1:
    root = project_root.resolve()
    blockers: list[str] = []
    if not dispatch_ids or len(set(dispatch_ids)) != len(dispatch_ids):
        blockers.append("DISPATCH_IDS_MUST_BE_NONEMPTY_UNIQUE")
    ledger = _resolve_runtime_ref(root, LEDGER_REF)
    dispositions_path = _resolve_runtime_ref(root, DISPOSITIONS_REF)
    ledger_before = ledger.read_bytes() if ledger.is_file() and not ledger.is_symlink() else b""
    dispositions_before = (
        dispositions_path.read_bytes()
        if dispositions_path.is_file() and not dispositions_path.is_symlink()
        else b""
    )
    process_root = ledger.parent.parent
    events, load_errors = event_ledger.load_events(ledger)
    blockers.extend(f"LEDGER_INVALID:{error}" for error in load_errors)
    dispositions, disposition_errors = load_terminal_lineage_dispositions(process_root)
    blockers.extend(f"DISPOSITION_INVALID:{error}" for error in disposition_errors)
    existing, closure_errors = event_ledger.dispatch_closure_index(
        events,
        process_root=process_root,
    )
    blockers.extend(f"EXISTING_CLOSURE_INVALID:{error}" for error in closure_errors)
    timestamp = created_at or datetime.now(UTC).isoformat(timespec="seconds")
    closures: list[dict[str, Any]] = []
    for dispatch_id in dispatch_ids:
        disposition_key = f"dispatch:{dispatch_id}"
        disposition = dispositions.get(disposition_key)
        if disposition is None:
            blockers.append(f"DISPOSITION_NOT_FOUND:{disposition_key}")
            continue
        status = event_ledger.normalize_terminal_status(disposition.get("terminal_status"))
        if status not in event_ledger.DISPATCH_DISPOSITION_RESULT_BY_STATUS:
            blockers.append(f"DISPOSITION_STATUS_NOT_CLOSABLE:{disposition_key}:{status or '-'}")
            continue
        expected_digest = str(disposition.get("source_digest") or "")
        sources = [
            event
            for event in events
            if event.get("event_type") in {"dispatch", "inline_fallback"}
            and str(event.get("dispatch_id") or "") == dispatch_id
            and canonical_digest(_clean(event)) == expected_digest
        ]
        if len(sources) != 1:
            blockers.append(f"DISPOSITION_SOURCE_NOT_UNIQUE:{disposition_key}:{len(sources)}")
            continue
        source = sources[0]
        source_id = str(source.get("event_id") or "")
        if source_id in existing:
            continue
        closure = build_dispatch_closure(
            source,
            disposition=disposition,
            created_at=timestamp,
        )
        _index, simulated_errors = event_ledger.dispatch_closure_index(
            [*events, *closures, closure],
            process_root=process_root,
        )
        blockers.extend(f"CLOSURE_INVALID:{error}" for error in simulated_errors)
        closures.append(closure)
    if blockers:
        decision, closures = "BLOCKED", []
    elif closures:
        decision = "READY"
    else:
        decision = "NO_CHANGE"
    return DispatchClosurePlanV1(
        dispatch_ids=dispatch_ids,
        process_oid=process_oid or _process_oid(root),
        ledger_preimage=sha256(ledger_before).hexdigest(),
        dispositions_preimage=sha256(dispositions_before).hexdigest(),
        closures=tuple(closures),
        decision=decision,
        blockers=tuple(sorted(set(blockers))),
        mutation_count=len(closures),
    )


def _replace(path: Path, content: bytes) -> None:
    atomic_replace_bytes(path, content)


def apply_dispatch_closures(
    project_root: Path,
    *,
    plan: DispatchClosurePlanV1,
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
    dispositions = _resolve_runtime_ref(root, DISPOSITIONS_REF)
    before = ledger.read_bytes()
    if sha256(before).hexdigest() != plan.ledger_preimage:
        return {"decision": "BLOCKED", "blockers": ["LEDGER_PREIMAGE_DRIFT"], "mutation_count": 0}
    disposition_bytes = dispositions.read_bytes()
    if sha256(disposition_bytes).hexdigest() != plan.dispositions_preimage:
        return {
            "decision": "BLOCKED",
            "blockers": ["DISPOSITIONS_PREIMAGE_DRIFT"],
            "mutation_count": 0,
        }
    events, load_errors = event_ledger.load_events(ledger)
    if load_errors:
        return {
            "decision": "BLOCKED",
            "blockers": [f"LEDGER_INVALID:{item}" for item in load_errors],
            "mutation_count": 0,
        }
    _index, closure_errors = event_ledger.dispatch_closure_index(
        [*events, *plan.closures],
        process_root=ledger.parent.parent,
    )
    if closure_errors:
        return {
            "decision": "BLOCKED",
            "blockers": [f"CLOSURE_INVALID:{item}" for item in closure_errors],
            "mutation_count": 0,
        }
    text = before.decode("utf-8")
    if text and not text.endswith("\n"):
        text += "\n"
    text += "".join(
        json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n" for event in plan.closures
    )
    _replace(ledger, text.encode("utf-8"))
    return {
        "schema_version": 1,
        "kind": "DispatchClosureReceiptV1",
        "decision": "APPLIED",
        "appended_event_ids": [event["event_id"] for event in plan.closures],
        "plan_digest": plan.plan_digest,
        "mutation_count": len(plan.closures),
    }


__all__ = [
    "DispatchClosurePlanV1",
    "apply_dispatch_closures",
    "build_dispatch_closure",
    "plan_dispatch_closures",
]
