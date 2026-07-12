"""Canonical machine audit report derived from immutable ledger rows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from meta_flow.checks.audit_report import build_audit_report


def build_machine_audit(project_root: Path, *, cr_id: str) -> dict[str, Any]:
    report = build_audit_report(project_root, cr_id=cr_id)
    report["report_kind"] = "machine-generated-audit"
    report["counting_dimensions"] = {
        "event_rows": "unique ledger event_id rows",
        "attempts": "unique dispatch_id + attempt_id pairs",
        "threads": "unique thread_id values",
        "terminal_events": "terminal ledger rows; not attempts",
        "token_usage": "only platform-reported measured usage contributes a total",
    }
    return report
