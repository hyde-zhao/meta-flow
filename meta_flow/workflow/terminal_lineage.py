"""Work/CR/dispatch/gate/evidence 的统一终态 lineage 投影。"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Any

from meta_flow.execution_control.contract import canonical_digest
from meta_flow.project.process_route import require_process_route
from meta_flow.project.scale import load_yaml_object
from meta_flow.workflow.cr_model import parse_frontmatter

PUBLIC_OPERATION_DECLARATIONS = (
    ("terminal-lineage.check", ("meta-flow", "check", "terminal-lineage")),
)
DISPOSITIONS_REL = Path("policies/TERMINAL-LINEAGE-DISPOSITIONS.json")
WORK_TERMINAL = {"completed", "cancelled", "archived"}
CR_TERMINAL = {"closed", "cancelled", "superseded", "archived"}
DISPATCH_TERMINAL = {
    "completed",
    "blocked",
    "failed",
    "cancelled",
    "superseded",
    "closed",
    "interrupted",
}
GATE_TERMINAL = {
    "approved",
    "passed",
    "blocked",
    "stopped",
    "rejected",
    "cancelled",
    "closed",
    "complete",
    "completed",
    "superseded",
    "switched_to_approved_fallback",
    "approved-by-current-bundle",
    "approved_design_only",
    "applied",
    "recorded_non_product_finding",
    "corrected_append_only",
}
EVIDENCE_TERMINAL = {
    "available",
    "artifact-available",
    "complete",
    "completed",
    "current",
    "superseded",
    "archived",
    "pass",
}
TERMINAL_VALUES_BY_KIND = {
    "work": WORK_TERMINAL,
    "cr": CR_TERMINAL,
    "dispatch": DISPATCH_TERMINAL,
    "gate": GATE_TERMINAL,
    "evidence": EVIDENCE_TERMINAL,
}
_ATTEMPT_RE = re.compile(r"(?:attempt[-_]?|revision[-_]?|revalidation[-_]?)(\d+)", re.I)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class TerminalLineageRecordV1:
    kind: str
    identity: str
    revision: int
    ordinal: int
    event_id: str
    status: str
    terminal: bool
    source_ref: str
    source_digest: str
    disposition_applied: bool = False
    status_source: str = "explicit-source"
    verification_decision: str = ""

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.identity}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "identity": self.identity,
            "revision": self.revision,
            "ordinal": self.ordinal,
            "event_id": self.event_id,
            "status": self.status,
            "terminal": self.terminal,
            "source_ref": self.source_ref,
            "source_digest": self.source_digest,
            "disposition_applied": self.disposition_applied,
            "status_source": self.status_source,
            "verification_decision": self.verification_decision,
        }


def _record(
    kind: str,
    identity: str,
    revision: int,
    ordinal: int,
    event_id: str,
    status: object,
    source_ref: str,
    source: Mapping[str, Any],
    terminal_values: set[str],
    *,
    status_source: str = "explicit-source",
    verification_decision: object = "",
) -> TerminalLineageRecordV1:
    normalized = str(status or "").strip().lower()
    return TerminalLineageRecordV1(
        kind=kind,
        identity=identity,
        revision=revision,
        ordinal=ordinal,
        event_id=event_id,
        status=normalized,
        terminal=normalized in terminal_values,
        source_ref=source_ref,
        source_digest=canonical_digest(dict(source)),
        status_source=status_source,
        verification_decision=str(verification_decision or "").strip().lower(),
    )


def _load_ndjson(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    if not path.is_file() or path.is_symlink():
        return [], [f"ledger missing or not regular: {path}"]
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{path.name}:{line_no}: invalid JSON: {exc}")
            continue
        if not isinstance(value, dict):
            errors.append(f"{path.name}:{line_no}: event must be an object")
            continue
        rows.append(value)
    return rows, errors


def _attempt_revision(value: object, fallback: int) -> int:
    text = str(value or "")
    match = _ATTEMPT_RE.search(text)
    if match:
        return int(match.group(1))
    if text.isdigit() and int(text) > 0:
        return int(text)
    return fallback


def _work_records(process_root: Path) -> tuple[list[TerminalLineageRecordV1], list[str]]:
    records: list[TerminalLineageRecordV1] = []
    errors: list[str] = []
    works_root = process_root / "works"
    if not works_root.is_dir():
        return records, errors
    for ordinal, path in enumerate(sorted(works_root.glob("*/WORK.yaml")), 1):
        ref = path.relative_to(process_root).as_posix()
        try:
            payload = load_yaml_object(path)
            work_id = str(payload.get("work_id") or path.parent.name)
            execution = payload.get("execution_unit")
            revision = (
                int(execution.get("revision") or 1)
                if isinstance(execution, dict)
                else 1
            )
            records.append(
                _record(
                    "work",
                    work_id,
                    revision,
                    ordinal,
                    f"{work_id}-snapshot-r{revision}",
                    payload.get("status"),
                    ref,
                    payload,
                    WORK_TERMINAL,
                )
            )
        except (OSError, ValueError, TypeError) as exc:
            errors.append(f"{ref}: unreadable Work lineage: {exc}")
    return records, errors


def _cr_records(process_root: Path) -> tuple[list[TerminalLineageRecordV1], list[str]]:
    path = process_root / "state/CR-LEDGER.ndjson"
    rows, errors = _load_ndjson(path)
    revisions: dict[str, int] = {}
    records: list[TerminalLineageRecordV1] = []
    for ordinal, row in enumerate(rows, 1):
        identity = str(row.get("id") or row.get("cr_id") or "")
        if not identity:
            continue
        revisions[identity] = revisions.get(identity, 0) + 1
        records.append(
            _record(
                "cr",
                identity,
                revisions[identity],
                ordinal,
                str(row.get("event_id") or f"{identity}-event-{ordinal}"),
                row.get("status") or row.get("lifecycle_status"),
                "state/CR-LEDGER.ndjson",
                row,
                CR_TERMINAL,
            )
        )
    changes_root = process_root / "changes"
    for path in sorted(changes_root.glob("CR-*.md")) if changes_root.is_dir() else []:
        ref = path.relative_to(process_root).as_posix()
        try:
            fields = parse_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            errors.append(f"{ref}: unreadable formal CR lineage: {exc}")
            continue
        if fields.get("kind") != "cr":
            continue
        identity = str(fields.get("cr_id") or "")
        if not identity:
            errors.append(f"{ref}: formal CR cr_id is required")
            continue
        revisions[identity] = revisions.get(identity, 0) + 1
        records.append(
            _record(
                "cr",
                identity,
                revisions[identity],
                len(rows) + len(records) + 1,
                f"{identity}-formal-truth-r{revisions[identity]}",
                fields.get("lifecycle_status") or fields.get("status"),
                ref,
                fields,
                CR_TERMINAL,
                status_source="formal-cr-truth",
            )
        )
        if str(fields.get("lifecycle_status") or fields.get("status") or "").lower() in CR_TERMINAL:
            errors.extend(
                _validate_terminal_cr_evidence(
                    process_root,
                    cr_id=identity,
                    formal_ref=f"process/{ref}",
                )
            )
    return records, errors


def _validate_terminal_cr_evidence(
    process_root: Path,
    *,
    cr_id: str,
    formal_ref: str,
) -> list[str]:
    """验证终态 CR 的 summary/evidence 引用确实存在且不逃逸过程仓。"""

    expected_summary_ref = f"process/changes/summaries/{cr_id}.summary.json"
    evidence_path = process_root / "archive" / cr_id / "evidence-index.json"
    findings: list[str] = []
    summary_path = process_root / expected_summary_ref.removeprefix("process/")
    if summary_path.is_symlink() or not summary_path.is_file():
        findings.append(f"TERMINAL_CR_SUMMARY_MISSING:cr:{cr_id}:{expected_summary_ref}")
    if evidence_path.is_symlink() or not evidence_path.is_file():
        findings.append(
            f"TERMINAL_CR_EVIDENCE_INDEX_MISSING:cr:{cr_id}:"
            f"process/archive/{cr_id}/evidence-index.json"
        )
        return findings
    try:
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"TERMINAL_CR_EVIDENCE_INDEX_INVALID:cr:{cr_id}:{exc}"]
    if not isinstance(payload, dict):
        return [f"TERMINAL_CR_EVIDENCE_INDEX_INVALID:cr:{cr_id}:not-object"]
    for key, expected in (
        ("cr_id", cr_id),
        ("full_ref", formal_ref),
        ("summary_ref", expected_summary_ref),
    ):
        if payload.get(key) != expected:
            findings.append(f"TERMINAL_CR_EVIDENCE_BINDING_DRIFT:cr:{cr_id}:{key}")
    evidence_refs = payload.get("evidence_refs")
    if not isinstance(evidence_refs, list):
        findings.append(f"TERMINAL_CR_EVIDENCE_REFS_INVALID:cr:{cr_id}")
        return findings
    for raw_ref in evidence_refs:
        ref = str(raw_ref or "")
        rel = Path(ref.removeprefix("process/"))
        if (
            not ref.startswith("process/")
            or rel.is_absolute()
            or ".." in rel.parts
        ):
            findings.append(f"TERMINAL_CR_EVIDENCE_REF_INVALID:cr:{cr_id}:{ref or '-'}")
            continue
        candidate = (process_root / rel).resolve(strict=False)
        if (
            not candidate.is_relative_to(process_root.resolve())
            or candidate.is_symlink()
            or not candidate.is_file()
        ):
            findings.append(f"TERMINAL_CR_EVIDENCE_REF_MISSING:cr:{cr_id}:{ref}")
    return findings


def _dispatch_records(process_root: Path) -> tuple[list[TerminalLineageRecordV1], list[str]]:
    path = process_root / "state/AGENT-DISPATCH-LEDGER.ndjson"
    rows, errors = _load_ndjson(path)
    records: list[TerminalLineageRecordV1] = []
    attempt_order: dict[tuple[str, str], int] = {}
    dispatch_attempts: dict[str, int] = {}
    for ordinal, row in enumerate(rows, 1):
        identity = str(row.get("dispatch_id") or "")
        if not identity:
            continue
        attempt = str(row.get("attempt_id") or "attempt-1")
        pair = (identity, attempt)
        if pair not in attempt_order:
            dispatch_attempts[identity] = dispatch_attempts.get(identity, 0) + 1
            attempt_order[pair] = _attempt_revision(
                attempt,
                dispatch_attempts[identity],
            )
        records.append(
            _record(
                "dispatch",
                identity,
                attempt_order[pair],
                ordinal,
                str(row.get("event_id") or f"{identity}-{attempt}-{ordinal}"),
                row.get("status"),
                "state/AGENT-DISPATCH-LEDGER.ndjson",
                row,
                DISPATCH_TERMINAL,
            )
        )
    return records, errors


def _gate_identity(row: Mapping[str, Any], ordinal: int) -> str:
    bundle = str(row.get("bundle_id") or "")
    if bundle:
        return f"bundle:{bundle}"
    owner = str(row.get("work_id") or row.get("cr_id") or "unowned")
    gate = str(row.get("gate") or row.get("checkpoint") or row.get("event_type") or ordinal)
    return f"gate:{owner}:{gate}"


def _gate_records(process_root: Path) -> tuple[list[TerminalLineageRecordV1], list[str]]:
    path = process_root / "state/GATE-LEDGER.ndjson"
    rows, errors = _load_ndjson(path)
    records: list[TerminalLineageRecordV1] = []
    fallback_revisions: dict[str, int] = {}
    revision_keys: dict[tuple[str, str], int] = {}
    for ordinal, row in enumerate(rows, 1):
        identity = _gate_identity(row, ordinal)
        explicit = row.get("bundle_revision") or row.get("scope_version") or row.get("attempt")
        revision_text = str(explicit or "")
        key = (identity, revision_text)
        if key not in revision_keys:
            fallback_revisions[identity] = fallback_revisions.get(identity, 0) + 1
            revision_keys[key] = (
                int(explicit)
                if isinstance(explicit, int) and not isinstance(explicit, bool) and explicit > 0
                else fallback_revisions[identity]
            )
        records.append(
            _record(
                "gate",
                identity,
                revision_keys[key],
                ordinal,
                str(row.get("event_id") or f"{identity}-{ordinal}"),
                row.get("status") or row.get("decision"),
                "state/GATE-LEDGER.ndjson",
                row,
                GATE_TERMINAL,
            )
        )
    return records, errors


def _evidence_identity(path: Path) -> tuple[str, int]:
    stem = path.name.removesuffix(".index.json")
    revision = _attempt_revision(stem, 1)
    canonical = re.sub(
        r"(?:[._-](?:revalidation|revision|attempt)[._-]?\d+)$",
        "",
        stem,
        flags=re.I,
    )
    return canonical, revision


def _evidence_records(process_root: Path) -> tuple[list[TerminalLineageRecordV1], list[str]]:
    records: list[TerminalLineageRecordV1] = []
    errors: list[str] = []
    evidence_root = process_root / "evidence"
    if not evidence_root.is_dir():
        return records, errors
    for ordinal, path in enumerate(sorted(evidence_root.glob("*.index.json")), 1):
        ref = path.relative_to(process_root).as_posix()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("evidence index must be an object")
            if payload.get("schema_version") != 1:
                raise ValueError("evidence index schema_version must be 1")
            if not str(payload.get("story_id") or "").strip():
                raise ValueError("evidence index story_id is required")
            identity, revision = _evidence_identity(path)
            explicit_status = payload.get("status")
            explicit_decision = payload.get("decision")
            if explicit_status:
                status = explicit_status
                status_source = "explicit-status"
            elif explicit_decision:
                status = explicit_decision
                status_source = "explicit-decision"
            else:
                if str(payload.get("stage") or "") not in {"CP6", "CP7"}:
                    raise ValueError(
                        "evidence index without explicit status/decision requires CP6/CP7 stage"
                    )
                if not str(payload.get("return_ref") or "").strip():
                    raise ValueError(
                        "evidence index without explicit status/decision requires return_ref"
                    )
                status = "artifact-available"
                status_source = "derived-artifact-presence"
            records.append(
                _record(
                    "evidence",
                    identity,
                    revision,
                    ordinal,
                    str(payload.get("event_id") or identity),
                    status,
                    ref,
                    payload,
                    EVIDENCE_TERMINAL,
                    status_source=status_source,
                    verification_decision=explicit_decision,
                )
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{ref}: invalid evidence index: {exc}")
    return records, errors


def discover_terminal_lineage(
    process_root: Path,
) -> tuple[tuple[TerminalLineageRecordV1, ...], tuple[str, ...]]:
    records: list[TerminalLineageRecordV1] = []
    errors: list[str] = []
    for discover in (
        _work_records,
        _cr_records,
        _dispatch_records,
        _gate_records,
        _evidence_records,
    ):
        discovered, findings = discover(process_root.resolve())
        records.extend(discovered)
        errors.extend(findings)
    return tuple(records), tuple(errors)


def _load_dispositions(process_root: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    path = process_root / DISPOSITIONS_REL
    if not path.exists():
        return {}, []
    if path.is_symlink() or not path.is_file():
        return {}, ["terminal lineage dispositions must be a regular file"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [f"terminal lineage dispositions invalid: {exc}"]
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        return {}, ["terminal lineage dispositions schema_version is invalid"]
    items = payload.get("dispositions")
    if not isinstance(items, list):
        return {}, ["terminal lineage dispositions must be a list"]
    result: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    expected = {
        "key",
        "source_digest",
        "terminal_status",
        "reason",
        "evidence_refs",
        "evidence_digests",
    }
    for item in items:
        if not isinstance(item, dict) or set(item) != expected:
            errors.append("terminal lineage disposition fields mismatch")
            continue
        key = str(item.get("key") or "")
        if not key or key in result:
            errors.append(f"terminal lineage disposition key duplicate/invalid: {key}")
            continue
        evidence_refs = item.get("evidence_refs")
        evidence_digests = item.get("evidence_digests")
        if not isinstance(evidence_refs, list) or not evidence_refs:
            errors.append(f"terminal lineage disposition evidence missing: {key}")
        elif (
            not isinstance(evidence_digests, dict)
            or set(evidence_digests) != set(evidence_refs)
        ):
            errors.append(f"terminal lineage disposition evidence digests mismatch: {key}")
        else:
            for ref in evidence_refs:
                if not isinstance(ref, str) or not ref.startswith("process/"):
                    errors.append(
                        f"terminal lineage disposition evidence ref invalid: {key}:{ref}"
                    )
                    continue
                candidate = process_root / ref.removeprefix("process/")
                if candidate.is_symlink() or not candidate.is_file():
                    errors.append(
                        f"terminal lineage disposition evidence missing: {key}:{ref}"
                    )
                    continue
                expected_digest = str(evidence_digests.get(ref) or "")
                if not _SHA256_RE.fullmatch(expected_digest):
                    errors.append(
                        f"terminal lineage disposition evidence digest invalid: {key}:{ref}"
                    )
                elif sha256(candidate.read_bytes()).hexdigest() != expected_digest:
                    errors.append(
                        f"terminal lineage disposition evidence drift: {key}:{ref}"
                    )
        result[key] = item
    return result, errors


def project_terminal_lineage(
    records: Iterable[TerminalLineageRecordV1],
    *,
    dispositions: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    grouped: dict[str, list[TerminalLineageRecordV1]] = {}
    for record in records:
        grouped.setdefault(record.key, []).append(record)
    current: list[TerminalLineageRecordV1] = []
    history: list[TerminalLineageRecordV1] = []
    findings: list[str] = []
    unused_dispositions = set(dispositions or {})
    for key, items in sorted(grouped.items()):
        ordered = sorted(items, key=lambda item: (item.revision, item.ordinal, item.event_id))
        latest = ordered[-1]
        history.extend(ordered[:-1])
        disposition = (dispositions or {}).get(key)
        if disposition is not None:
            unused_dispositions.discard(key)
            terminal_status = str(disposition.get("terminal_status") or "").lower()
            if str(disposition.get("source_digest") or "") != latest.source_digest:
                findings.append(f"DISPOSITION_SOURCE_DRIFT:{key}")
            elif not terminal_status:
                findings.append(f"DISPOSITION_TERMINAL_STATUS_MISSING:{key}")
            elif terminal_status not in TERMINAL_VALUES_BY_KIND.get(latest.kind, set()):
                findings.append(
                    f"DISPOSITION_STATUS_NOT_TERMINAL:{key}:{terminal_status}"
                )
            else:
                latest = replace(
                    latest,
                    status=terminal_status,
                    terminal=True,
                    disposition_applied=True,
                )
        if not latest.terminal:
            findings.append(f"LATEST_NOT_TERMINAL:{key}:{latest.status or '-'}")
        current.append(latest)
    findings.extend(f"DISPOSITION_TARGET_MISSING:{key}" for key in sorted(unused_dispositions))
    counts: dict[str, dict[str, int]] = {}
    for record in current:
        item = counts.setdefault(record.kind, {"current": 0, "terminal": 0, "active": 0})
        item["current"] += 1
        item["terminal" if record.terminal else "active"] += 1
    current_evidence = [record for record in current if record.kind == "evidence"]
    verification_decisions: dict[str, int] = {}
    for record in current_evidence:
        if record.verification_decision:
            verification_decisions[record.verification_decision] = (
                verification_decisions.get(record.verification_decision, 0) + 1
            )
    payload = {
        "schema_version": 1,
        "kind": "TerminalLineageManifestV1",
        "algorithm": "typed-identity-max-revision-then-append-ordinal-v1",
        "decision": "BLOCKED" if findings else "PASS",
        "counts": counts,
        "evidence_semantics": {
            "current_count": len(current_evidence),
            "explicit_status_or_decision_count": len(
                [
                    record
                    for record in current_evidence
                    if record.status_source.startswith("explicit-")
                ]
            ),
            "derived_artifact_availability_count": len(
                [
                    record
                    for record in current_evidence
                    if record.status_source == "derived-artifact-presence"
                ]
            ),
            "verification_decision_counts": dict(sorted(verification_decisions.items())),
            "terminal_does_not_imply_verification_pass": True,
        },
        "current": [record.as_dict() for record in current],
        "history": [record.as_dict() for record in history],
        "findings": sorted(set(findings)),
    }
    payload["manifest_digest"] = canonical_digest(payload)
    return payload


def check_terminal_lineage(project_root: Path) -> dict[str, Any]:
    route = require_process_route(project_root.resolve())
    records, discovery_errors = discover_terminal_lineage(route.process_root)
    dispositions, disposition_errors = _load_dispositions(route.process_root)
    report = project_terminal_lineage(records, dispositions=dispositions)
    report["findings"] = sorted(
        set([*report["findings"], *discovery_errors, *disposition_errors])
    )
    report["decision"] = "BLOCKED" if report["findings"] else "PASS"
    report["manifest_digest"] = canonical_digest(
        {key: value for key, value in report.items() if key != "manifest_digest"}
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow check terminal-lineage")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--include-records", action="store_true")
    parsed = parser.parse_args(argv or [])
    try:
        report = check_terminal_lineage(parsed.project_root)
    except (OSError, ValueError) as exc:
        print(json.dumps({"decision": "BLOCKED", "errors": [str(exc)]}, ensure_ascii=False))
        return 1
    if not parsed.include_records:
        report = {
            key: value
            for key, value in report.items()
            if key not in {"current", "history"}
        }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["decision"] == "PASS" else 1


__all__ = [
    "TerminalLineageRecordV1",
    "check_terminal_lineage",
    "discover_terminal_lineage",
    "project_terminal_lineage",
]
