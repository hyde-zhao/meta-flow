"""Deterministic, provenance-bearing audit report for Meta Flow ledgers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from meta_flow.state import event_ledger
from meta_flow.evidence.telemetry import aggregate_usage, usage_from_event


def build_audit_report(project_root: Path, *, cr_id: str) -> dict[str, Any]:
    root = project_root.resolve()
    dispatch_path = root / "process/state/AGENT-DISPATCH-LEDGER.ndjson"
    events, errors = event_ledger.load_events(dispatch_path)
    scoped = [event for event in events if str(event.get("cr_id") or "") == cr_id]
    attempts = {(str(event.get("dispatch_id") or ""), str(event.get("attempt_id") or "")) for event in scoped if event.get("attempt_id")}
    threads = {str(event.get("thread_id") or "") for event in scoped if event.get("thread_id")}
    terminal = [event for event in scoped if str(event.get("status") or "") in {"completed", "failed", "interrupted", "cancelled", "superseded"}]
    usages = [usage for event in scoped if (usage := usage_from_event(event)) is not None]
    usage_summary = aggregate_usage(usages)
    digest = hashlib.sha256(dispatch_path.read_bytes()).hexdigest() if dispatch_path.is_file() else ""
    return {
        "schema_version": 1,
        "cr_id": cr_id,
        "checker_provenance": {"checker_name": "meta-flow audit-report", "checker_commit": "working-tree", "input_sha256": f"sha256:{digest}" if digest else None},
        "counts": {"event_rows": len(scoped), "attempts": len(attempts), "threads": len(threads), "terminal_events": len(terminal)},
        "errors": errors,
        "token_measurement": usage_summary if usages else {"measurement_status_counts": {"estimated": 0, "measured": 0, "unavailable": 0}, "measured_total_tokens": None, "measurement_status": "unavailable", "reason": "not-yet-ingested"},
    }


def write_audit_report(project_root: Path, *, cr_id: str, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(build_audit_report(project_root, cr_id=cr_id), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output
