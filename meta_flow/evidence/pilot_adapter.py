"""Guarded, synthetic-only CR-163 correction-pilot adapter.

It plans and preflights targets but does not write a target repository.  A
real apply remains blocked without a separate, fresh authorization object.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def _file_hash(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}" if path.is_file() else ""


def build_pilot_manifest(*, targets: list[str], authorization_ref: str | None, checker_provenance: dict[str, Any]) -> dict[str, Any]:
    if len(targets) != 23:
        raise ValueError("CR-163 pilot manifest requires exactly 23 targets")
    return {
        "schema_version": 1,
        "pilot_id": "CR-163-evidence-migration",
        "execution_mode": "dry-run",
        "targets": targets,
        "authorization_ref": authorization_ref,
        "checker_provenance": checker_provenance,
        "protected_paths": ["quant-lab lineage business source"],
    }


def preflight_pilot(manifest: dict[str, Any], *, project_root: Path) -> dict[str, Any]:
    findings: list[str] = []
    if manifest.get("execution_mode") != "dry-run":
        findings.append("real pilot apply is not authorized by CR-046")
    if len(manifest.get("targets") or []) != 23:
        findings.append("pilot must retain exactly 23 target refs")
    if manifest.get("authorization_ref"):
        findings.append("CR-046 accepts authorization references for planning only; external target apply needs separate approval")
    return {"decision": "BLOCKED" if findings else "PASS", "findings": findings, "target_count": len(manifest.get("targets") or []), "target_repository_written": False}
