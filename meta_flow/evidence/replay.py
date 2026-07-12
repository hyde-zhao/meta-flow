"""Read-only evidence replay and platform-conformance decisions.

The module keeps repository replayability separate from runtime platform
attestation.  It is intentionally conservative: missing historical checker or
platform receipts report ``unavailable`` rather than being reconstructed from
labels, TOML files, or current checker behaviour.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .platform_contract import CapabilityProbe, needs_reprobe


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


@dataclass(frozen=True)
class ReplayOutcome:
    as_executed: str
    current_checker: str
    diff: str
    findings: tuple[str, ...]


def replay_outcome(result: dict[str, Any], *, current_checker: str, current_commit: str) -> ReplayOutcome:
    provenance = result.get("checker_provenance") if isinstance(result.get("checker_provenance"), dict) else {}
    historical_name = str(provenance.get("checker_name") or "")
    historical_commit = str(provenance.get("checker_commit") or provenance.get("checker_version") or "")
    decision = str(result.get("decision") or "UNAVAILABLE")
    if not historical_name or not historical_commit:
        as_executed = "unavailable"
        findings = ("NULL_CHECKER_PROVENANCE",)
    elif historical_name != current_checker or historical_commit != current_commit:
        as_executed = "unavailable"
        findings = ("HISTORICAL_CHECKER_UNAVAILABLE",)
    else:
        as_executed = decision
        findings = ()
    current = decision
    diff = "identical" if as_executed == current else "unavailable-or-changed"
    return ReplayOutcome(as_executed, current, diff, findings)


def legacy_profile_annotation(event: dict[str, Any]) -> dict[str, Any]:
    """Classify old self-declared names without resolving them from config."""

    return {
        "declared_profile": event.get("requested_agent_profile") or event.get("codex_agent_name") or None,
        "evidence_class": "D3-self-declared-unverifiable",
        "resolved_profile": None,
        "resolved_model": None,
        "resolved_reasoning_effort": None,
    }


def admission_requires_reprobe(
    probe: CapabilityProbe | None,
    *,
    now: datetime,
    session_id: str,
    session_epoch: str,
    config_sha256: str,
    selector_schema_version: str,
    reload_generation: str,
) -> dict[str, Any]:
    required, reasons = needs_reprobe(
        probe,
        now=now,
        session_id=session_id,
        session_epoch=session_epoch,
        config_sha256=config_sha256,
        selector_schema_version=selector_schema_version,
        reload_generation=reload_generation,
    )
    return {"reprobe_required": required, "reasons": list(reasons)}


def render_replay_manifest(result_path: Path, *, current_checker: str, current_commit: str) -> dict[str, Any]:
    original = result_path.read_bytes()
    result = json.loads(original)
    outcome = replay_outcome(result, current_checker=current_checker, current_commit=current_commit)
    return {
        "schema_version": 1,
        "result_ref": result_path.as_posix(),
        "input_sha256": f"sha256:{hashlib.sha256(original).hexdigest()}",
        "outcome": asdict(outcome),
        "historical_input_mutated": False,
    }
