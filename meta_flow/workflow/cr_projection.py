"""CR projection and shared writer primitives."""

# ruff: noqa: I001, UP034
from __future__ import annotations

import json
import os
import re
import stat
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meta_flow.project.model import is_safe_ref
from meta_flow.checks import cr_tracking
from meta_flow.project.read_contract import ReadContextProtocol
from meta_flow.project.scale import _load_compatible_yaml
from meta_flow.state import checkpoint_projection, current, event_ledger
from meta_flow.workflow.cr_model import now_utc, parse_frontmatter
from meta_flow.workflow.cr_records import (
    CR_SUMMARY_ROOT_REL,
    _first_section_summary,
    _git_fact,
    _impact_split_payload,
    _normalized_capability_refs,
    _process_root,
    _record_required_evidence,
    _rel,
    _resolve_runtime_ref,
    _section_summary,
    classify_cp1_review_profile,
    collect_archive_isolation_findings,
    collect_governance_dependency_findings,
    collect_scope_authz_findings,
    discover_formal_crs,
    record_from_cr_file,
)

CR_LEDGER_REL = Path("process/state/CR-LEDGER.ndjson")

CR_ARCHIVE_ROOT_REL = Path("process/archive")

STATE_CURRENT_REL = Path("process/state/STATE.current.json")

DECISION_STATUSES = frozenset({"n/a", "pending", "approved", "rejected", "closed"})
GATE_LEDGER_REF = "process/state/GATE-LEDGER.ndjson"
SUMMARY_FOLLOW_UP_DISPOSITIONS = frozenset({"DEFERRED_FOLLOW_UP", "RISK_ACCEPTED_FOR_RELEASE"})
_SUMMARY_CANDIDATE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _resolve_summary_owner_ref(
    project_root: Path,
    logical_ref: str,
    read_context: ReadContextProtocol | None,
) -> Path:
    return (
        _resolve_runtime_ref(project_root, logical_ref)
        if read_context is None
        else read_context.resolve_path(logical_ref)
    )


def _load_gate_decision_events(
    project_root: Path,
    *,
    read_context: ReadContextProtocol | None,
) -> list[dict[str, Any]]:
    path = _resolve_summary_owner_ref(project_root, GATE_LEDGER_REF, read_context)
    if not path.exists():
        return []
    events, errors = event_ledger.load_events(
        path,
        read_context=read_context,
        logical_ref=GATE_LEDGER_REF if read_context is not None else "",
    )
    if errors:
        raise ValueError("gate decision owner is invalid: " + "; ".join(errors))
    return events


def _decision_status_from_owners(
    project_root: Path,
    cr_id: str,
    cr_text: str,
    *,
    read_context: ReadContextProtocol | None,
) -> str:
    events = _load_gate_decision_events(
        project_root,
        read_context=read_context,
    )
    approval_by_id = {
        approval.event_id: approval
        for approval in event_ledger.project_gate_approvals(events)
        if approval.cr_id == cr_id
    }
    resolved_non_passage_gates = {
        str(event.get("gate") or "")
        for event in events
        if (
            (approval := approval_by_id.get(str(event.get("event_id") or "")))
            is not None
            and not approval.finding_codes
            and not approval.passage
            and str(event.get("gate") or "")
        )
    }
    for event in reversed(events):
        if str(event.get("cr_id") or "") != cr_id:
            continue
        approval = approval_by_id.get(str(event.get("event_id") or ""))
        event_type = str(event.get("event_type") or "")
        decision = str(event.get("decision") or "").strip().lower()
        status = str(event.get("status") or "").strip().lower()
        if approval is not None:
            if approval.finding_codes:
                raise ValueError(
                    "gate decision owner approval is invalid: " + ",".join(approval.finding_codes)
                )
            if approval.passage:
                return "approved"
            if decision in {"reject", "rejected"} or status == "rejected":
                return "rejected"
            continue
        if event_type in {"human_gate_rejected", "human_gate_rejection"}:
            return "rejected"
        if event_type in {
            "human_gate_launched",
            "human_gate_changes_requested",
            "human_gate_postlaunch_evidence",
        } and (decision.startswith("pending") or status.startswith("pending")):
            # scope/recovery/evidence 类授权会批准该操作，但不会推进 checkpoint。
            # 它们仍应关闭自己的 launch，不能把更早的 passage 决策重新投影为 pending。
            if str(event.get("gate") or "") in resolved_non_passage_gates:
                continue
            return "pending"

    formal_decision = str(parse_frontmatter(cr_text).get("approval_result") or "").lower()
    return {
        "approve": "approved",
        "approved": "approved",
        "reject": "rejected",
        "rejected": "rejected",
        "pending": "pending",
        "closed": "closed",
    }.get(formal_decision, "n/a")


def _load_summary_release_context(
    project_root: Path,
    cr_id: str,
    *,
    read_context: ReadContextProtocol | None,
) -> tuple[str, dict[str, Any]] | None:
    compact = cr_id.replace("-", "")
    candidate_refs = (
        f"process/release/RELEASE-CONTEXT-{compact}.yaml",
        "process/release/RELEASE-CONTEXT.yaml",
        f"process/release/RELEASE-CONTEXT-{compact}.json",
    )
    matches: list[tuple[str, dict[str, Any]]] = []
    for logical_ref in candidate_refs:
        path = _resolve_summary_owner_ref(project_root, logical_ref, read_context)
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError(f"release context owner path is unsafe: {logical_ref}")
        if not path.is_file():
            continue
        text = (
            path.read_text(encoding="utf-8")
            if read_context is None
            else read_context.read_text(logical_ref)
        )
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = _load_compatible_yaml(text)
        if not isinstance(payload, dict):
            raise ValueError(f"release context owner is not an object: {logical_ref}")
        if str(payload.get("cr_id") or "") == cr_id:
            matches.append((logical_ref, payload))
    if len(matches) > 1:
        raise ValueError(f"multiple release context owners found for {cr_id}")
    return matches[0] if matches else None


def _follow_up_projection(
    release_ref: str,
    release_context: dict[str, Any],
) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    release_decision = str(release_context.get("release_decision") or "").upper()
    publication_result = release_context.get("publication_result")
    publication_result = publication_result if isinstance(publication_result, dict) else {}
    publication_decision = str(publication_result.get("decision") or "").upper()
    risk_disposition = publication_result.get("risk_disposition")
    risk_disposition = risk_disposition if isinstance(risk_disposition, dict) else {}
    fact_diff = release_context.get("fact_diff")
    fact_diff_items = fact_diff.get("items") if isinstance(fact_diff, dict) else fact_diff
    for raw in fact_diff_items if isinstance(fact_diff_items, list) else []:
        if not isinstance(raw, dict):
            continue
        status = str(raw.get("status") or "").upper()
        decision_impact = str(raw.get("decision_impact") or "").upper()
        candidate_id = str(raw.get("promise_ref") or raw.get("risk_ref") or "")
        risk_ref = str(raw.get("risk_ref") or "")
        evidence_refs = raw.get("evidence_refs")
        evidence = [str(ref) for ref in evidence_refs] if isinstance(evidence_refs, list) else []
        disposition = ""
        if status == "DEFERRED_FOLLOW_UP":
            disposition = status
        elif (
            status == "EXECUTED_NEGATIVE_RESULT"
            and risk_ref
            and decision_impact == "READY_WITH_RISK"
            and release_decision in {"READY_WITH_RISK", "RELEASED"}
            and publication_decision == "RELEASED"
            and risk_disposition
        ):
            candidate_id = risk_ref
            disposition = "RISK_ACCEPTED_FOR_RELEASE"
        if not candidate_id or not disposition:
            continue
        if not _SUMMARY_CANDIDATE_ID_RE.fullmatch(candidate_id):
            raise ValueError(f"follow-up disposition candidate id is invalid: {candidate_id}")
        if risk_ref and not _SUMMARY_CANDIDATE_ID_RE.fullmatch(risk_ref):
            raise ValueError(f"follow-up disposition risk ref is invalid: {risk_ref}")
        if not evidence:
            raise ValueError(f"follow-up disposition evidence is missing: {candidate_id}")
        if any(not is_safe_ref(ref, prefix="process") for ref in evidence):
            raise ValueError(f"follow-up disposition evidence ref is invalid: {candidate_id}")
        candidate = {
            "candidate_id": candidate_id,
            "disposition": disposition,
            "risk_ref": risk_ref or None,
            "evidence_refs": evidence,
            "source_ref": release_ref,
        }
        if candidate_id in candidates:
            raise ValueError(f"follow-up disposition candidate is duplicated: {candidate_id}")
        candidates[candidate_id] = candidate
    return [candidates[key] for key in sorted(candidates)]


def validate_summary_semantics(
    project_root: Path,
    cr_id: str,
    summary: dict[str, Any],
    *,
    read_context: ReadContextProtocol | None = None,
) -> list[str]:
    findings: list[str] = []
    decision_status = str(summary.get("decision_status") or "n/a").lower()
    if decision_status not in DECISION_STATUSES:
        findings.append(f"invalid decision_status: {decision_status}")
    if "decision_status" in summary:
        formal_ref = summary.get("full_ref")
        if not isinstance(formal_ref, str) or not is_safe_ref(
            formal_ref,
            prefix="process",
        ):
            findings.append("decision_status has no valid formal CR owner ref")
        else:
            formal_path = _resolve_summary_owner_ref(
                project_root,
                formal_ref,
                read_context,
            )
            if not formal_path.is_file():
                findings.append("decision_status formal CR owner is missing")
            else:
                formal_text = (
                    formal_path.read_text(encoding="utf-8")
                    if read_context is None
                    else read_context.read_text(formal_ref)
                )
                expected_decision_status = _decision_status_from_owners(
                    project_root,
                    cr_id,
                    formal_text,
                    read_context=read_context,
                )
                if decision_status != expected_decision_status:
                    findings.append("decision_status diverges from its gate decision owner")
    if str(summary.get("status") or "").lower() == "closed" and decision_status == "pending":
        findings.append("closed CR cannot have decision_status=pending")
    candidates = summary.get("followup_candidates")
    if candidates is not None and not isinstance(candidates, list):
        findings.append("followup_candidates must be a list when present")
        candidates = []
    tracking_ref = str(summary.get("follow_up_tracking_ref") or "")
    owner = _load_summary_release_context(
        project_root,
        cr_id,
        read_context=read_context,
    )
    if owner is None:
        if candidates or tracking_ref:
            findings.append("follow-up projection has no release/disposition owner")
        return findings
    release_ref, release_context = owner
    expected_candidates = _follow_up_projection(release_ref, release_context)
    follow_up_summary = release_context.get("follow_up_summary")
    fact_diff = release_context.get("fact_diff")
    release_has_follow_up = (
        bool(follow_up_summary)
        or bool(expected_candidates)
        or any(
            isinstance(item, dict) and str(item.get("status") or "").upper() == "DEFERRED_FOLLOW_UP"
            for item in fact_diff
            if isinstance(fact_diff, list)
        )
    )
    if release_has_follow_up and not candidates and not tracking_ref:
        findings.append("release follow-up has no disposition or tracking ref")
    if tracking_ref and tracking_ref != release_ref:
        findings.append("follow_up_tracking_ref does not identify its release owner")
    for candidate in candidates or []:
        if not isinstance(candidate, dict):
            findings.append("followup candidate must be an object")
            continue
        if set(candidate) != {
            "candidate_id",
            "disposition",
            "risk_ref",
            "evidence_refs",
            "source_ref",
        }:
            findings.append("followup candidate fields mismatch")
            continue
        candidate_id = str(candidate.get("candidate_id") or "")
        disposition = str(candidate.get("disposition") or "")
        evidence_refs = candidate.get("evidence_refs")
        risk_ref = candidate.get("risk_ref")
        if (
            not _SUMMARY_CANDIDATE_ID_RE.fullmatch(candidate_id)
            or disposition not in SUMMARY_FOLLOW_UP_DISPOSITIONS
            or not isinstance(evidence_refs, list)
            or any(
                not isinstance(ref, str) or not is_safe_ref(ref, prefix="process")
                for ref in evidence_refs
            )
            or (
                risk_ref is not None
                and (
                    not isinstance(risk_ref, str)
                    or not _SUMMARY_CANDIDATE_ID_RE.fullmatch(risk_ref)
                )
            )
            or candidate.get("source_ref") != release_ref
        ):
            findings.append("followup candidate is not traceable to its disposition owner")
    if candidates is not None and candidates != expected_candidates:
        findings.append("followup_candidates diverge from disposition owner")
    if expected_candidates and tracking_ref != release_ref:
        findings.append("owned follow-up candidates require their tracking ref")
    return findings


@dataclass(frozen=True)
class NativeCRStatusProjectionV1:
    """由四个原生 CR 真相源收敛得到的单一状态投影。"""

    cr_id: str
    lifecycle_status: str
    readiness_status: str
    gate_status: str
    formal_cr_ref: str
    summary_ref: str
    ledger_event_id: str
    decision: str
    findings: tuple[str, ...]
    partition_snapshot_digest: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.__dict__,
            "kind": "NativeCRStatusProjectionV1",
            "schema_version": 1,
            "findings": list(self.findings),
        }


@dataclass(frozen=True)
class CheckpointIndexRowV1:
    """Checkpoint Index 的非持久化 typed row。"""

    checkpoint: str
    status: str
    result_ref: str = ""

    def __post_init__(self) -> None:
        if not re.fullmatch(r"CP[0-8]", self.checkpoint):
            raise ValueError(f"invalid checkpoint index row: {self.checkpoint}")
        if not self.status or any(char in self.status for char in ("\n", "\r", "|")):
            raise ValueError(f"invalid checkpoint index status: {self.checkpoint}")
        if any(char in self.result_ref for char in ("\n", "\r", "|", "`")):
            raise ValueError(f"invalid checkpoint result ref: {self.checkpoint}")


class AggregateCompletionProjector:
    """Project one persisted PASS aggregate through CR ledger and current-state writers."""

    def __init__(
        self,
        *,
        project_root: Path,
        expected_state_updated_at: str,
        append_ledger_event_fn: Any | None = None,
        rel_fn: Any | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.expected_state_updated_at = expected_state_updated_at
        self._append_ledger_event_fn = append_ledger_event_fn
        self._rel_fn = rel_fn

    def project_aggregate(self, *, result: Any, receipt: Any) -> dict[str, Any]:
        if not getattr(result, "cr_id", "") or not getattr(receipt, "aggregate_id", ""):
            raise ValueError("aggregate projection receipt identity is missing")
        if getattr(result, "aggregate_id", "") != getattr(receipt, "aggregate_id", ""):
            raise ValueError("aggregate projection result/receipt identity mismatch")
        if (
            str(getattr(result, "overall", "")) != "PASS"
            or getattr(result, "terminal", False) is not True
            or str(getattr(result, "projection_decision", "")) != "ELIGIBLE"
            or (getattr(receipt, "readback_valid", False) is not True)
            or (getattr(receipt, "current_selected", False) is not True)
        ):
            raise ValueError("aggregate projection requires persisted/readback current 2/2 PASS")
        cr_id = str(getattr(result, "cr_id", "") or "")
        aggregate_ref = str(getattr(receipt, "aggregate_ref", "") or "")
        writer_receipts: dict[str, Any] = {}
        try:
            state_receipt = current.project_aggregate_completion(
                self.project_root,
                cr_id=cr_id,
                aggregate_id=str(result.aggregate_id),
                aggregate_ref=aggregate_ref,
                payload_digest=str(result.payload_digest),
                expected_updated_at=self.expected_state_updated_at,
            )
        except (OSError, RuntimeError, ValueError) as error:
            return {
                "status": "failed",
                "writer_receipts": writer_receipts,
                "error": f"state_current:{type(error).__name__}:{error}",
            }
        writer_receipts["state_current"] = state_receipt
        existing_event = next(
            (
                event
                for event in load_ledger_events(self.project_root)
                if event.get("event") == "aggregate_projection"
                and event.get("id") == cr_id
                and (event.get("aggregate_ref") == aggregate_ref)
            ),
            None,
        )
        try:
            if existing_event is None:
                append = self._append_ledger_event_fn or append_ledger_event
                ledger_path = append(
                    self.project_root,
                    {
                        "event": "aggregate_projection",
                        "id": cr_id,
                        "status": "active",
                        "aggregate_id": result.aggregate_id,
                        "aggregate_ref": aggregate_ref,
                        "payload_digest": result.payload_digest,
                        "projection_disposition": state_receipt.get("status"),
                        "projected_at": now_utc(),
                    },
                )
                ledger_receipt = {
                    "status": "projected",
                    "ledger_ref": (self._rel_fn or _rel)(self.project_root, ledger_path),
                }
            else:
                ledger_receipt = {
                    "status": "idempotent-existing",
                    "ledger_ref": CR_LEDGER_REL.as_posix(),
                }
        except (OSError, RuntimeError, ValueError) as error:
            return {
                "status": "partial",
                "writer_receipts": writer_receipts,
                "error": f"cr_ledger:{type(error).__name__}:{error}",
            }
        writer_receipts["cr_ledger"] = ledger_receipt
        return {"status": "complete", "writer_receipts": writer_receipts}


def _gate_checkpoint_projection(gate_status: str) -> tuple[str, str] | None:
    """Map the lifecycle gate to the exact Checkpoint Index row projection."""
    mapping = {
        "cp2_pending": ("CP2", "pending"),
        "cp3_pending": ("CP3", "pending"),
        "cp5_pending": ("CP5", "pending"),
        "implementation_in_progress": ("CP6", "in-progress"),
        "cp7_pending": ("CP7", "pending"),
        "verification_in_progress": ("CP7", "in-progress"),
        "cp8_pending": ("CP8", "pending"),
        "cp8_closed": ("CP8", "approved"),
        "cp8_recovery_closed": ("CP8", "approved"),
        "closed": ("CP8", "approved"),
    }
    return mapping.get(gate_status)


def _checkpoint_result_projection(
    project_root: Path,
    cr_id: str,
    *,
    resolver: Any | None = None,
    read_context: ReadContextProtocol | None = None,
) -> dict[str, CheckpointIndexRowV1]:
    """只消费 canonical owner 选出的 CR-level current heads，并保留 exact ref。"""
    kwargs = {"resolver": resolver} if resolver is not None else {}
    projection = checkpoint_projection.load_checkpoint_projection(
        project_root,
        cr_id=cr_id,
        read_context=read_context,
        **kwargs,
    )
    if projection.findings:
        raise ValueError(
            "checkpoint projection failed: "
            + "; ".join((f"{finding.code}:{finding.message}" for finding in projection.findings))
        )
    rows: dict[str, CheckpointIndexRowV1] = {}
    for head in projection.heads:
        if head.subject_id != cr_id:
            continue
        if not re.fullmatch(r"CP[0-8]", head.checkpoint):
            raise ValueError(f"invalid canonical checkpoint head: {head.checkpoint}")
        if head.checkpoint in rows:
            raise ValueError(f"duplicate canonical checkpoint head: {head.checkpoint}")
        if not head.result_ref or head.result_ref == "—":
            raise ValueError(f"canonical checkpoint head missing result_ref: {head.checkpoint}")
        rows[head.checkpoint] = CheckpointIndexRowV1(
            checkpoint=head.checkpoint,
            status=head.decision,
            result_ref=head.result_ref,
        )
    gate_events = _load_gate_decision_events(
        project_root,
        read_context=read_context,
    )
    for approval in event_ledger.project_gate_approvals(gate_events):
        if approval.cr_id != cr_id or not approval.passage:
            continue
        existing = rows.get(approval.checkpoint)
        if existing is not None:
            if existing.result_ref != approval.result_ref:
                raise ValueError(
                    "checkpoint result and passage approval refs diverge: "
                    f"{approval.checkpoint}"
                )
            continue
        rows[approval.checkpoint] = CheckpointIndexRowV1(
            checkpoint=approval.checkpoint,
            status="APPROVED",
            result_ref=approval.result_ref,
        )
    return rows


def _render_exact_section_rows(text: str, heading: str, replacements: dict[str, str]) -> str:
    """Replace exact first-column table rows inside one optional section."""
    heading_pattern = re.compile(f"^## (?:(?:\\d+(?:\\.\\d+)*)\\.?\\s+)?{re.escape(heading)}$")
    lines = text.splitlines(keepends=True)
    starts = [
        index for index, line in enumerate(lines) if heading_pattern.fullmatch(line.rstrip("\r\n"))
    ]
    if not starts:
        return text
    if len(starts) != 1:
        raise ValueError(f"duplicate CR body section: {heading}")
    start = starts[0] + 1
    end = next(
        (index for index in range(start, len(lines)) if lines[index].startswith("## ")), len(lines)
    )
    seen: set[str] = set()
    for index in range(start, end):
        raw = lines[index]
        line_ending = "\n" if raw.endswith("\n") else ""
        cells = [cell.strip() for cell in raw.rstrip("\r\n").split("|")]
        if len(cells) < 4 or cells[0] != "":
            continue
        key = cells[1]
        if key not in replacements:
            continue
        if key in seen:
            raise ValueError(f"duplicate CR body table row: {heading}/{key}")
        cells[2] = replacements[key]
        lines[index] = "| " + " | ".join(cells[1:-1]) + " |" + line_ending
        seen.add(key)
    return "".join(lines)


def _markdown_line_ending(raw: str) -> str:
    if raw.endswith("\r\n"):
        return "\r\n"
    if raw.endswith("\n"):
        return "\n"
    return ""


def _markdown_table_cells(raw: str) -> list[str] | None:
    line = raw.rstrip("\r\n")
    if not line.startswith("|") or not line.endswith("|"):
        return None
    return [cell.strip() for cell in line[1:-1].split("|")]


def _render_markdown_table_row(cells: list[str], line_ending: str) -> str:
    return "| " + " | ".join(cells) + " |" + line_ending


def _checkpoint_number(checkpoint: str) -> int:
    if not re.fullmatch(r"CP[0-8]", checkpoint):
        raise ValueError(f"invalid Checkpoint Index key: {checkpoint}")
    return int(checkpoint[2:])


def _checkpoint_ref_cell(result_ref: str, *, template: str = "") -> str:
    if not result_ref:
        return "—"
    normalized_template = template.strip()
    if normalized_template and normalized_template != "—":
        if normalized_template.startswith("`") and normalized_template.endswith("`"):
            return f"`{result_ref}`"
        return result_ref
    return f"`{result_ref}`"


def _render_checkpoint_index_rows(
    text: str,
    replacements: dict[str, CheckpointIndexRowV1],
) -> str:
    """在唯一且合法的 Checkpoint Index table 内确定性更新或插入行。"""
    heading_pattern = re.compile(r"^## (?:(?:\d+(?:\.\d+)*)\.?\s+)?Checkpoint Index$")
    lines = text.splitlines(keepends=True)
    starts = [
        index for index, line in enumerate(lines) if heading_pattern.fullmatch(line.rstrip("\r\n"))
    ]
    if not starts:
        if not replacements:
            return text
        for checkpoint, row in replacements.items():
            _checkpoint_number(checkpoint)
            if row.checkpoint != checkpoint:
                raise ValueError(f"checkpoint row identity mismatch: {checkpoint}/{row.checkpoint}")
        line_ending = "\r\n" if "\r\n" in text else "\n"
        rendered = text
        if rendered and not rendered.endswith(("\n", "\r")):
            rendered += line_ending
        if rendered and not rendered.endswith(line_ending * 2):
            rendered += line_ending
        rendered += (
            "## Checkpoint Index"
            + line_ending
            + line_ending
            + "| Checkpoint | Status | Ref |"
            + line_ending
            + "|---|---|---|"
            + line_ending
        )
        for checkpoint, row in sorted(
            replacements.items(), key=lambda item: _checkpoint_number(item[0])
        ):
            rendered += _render_markdown_table_row(
                [checkpoint, row.status, _checkpoint_ref_cell(row.result_ref)],
                line_ending,
            )
        return rendered
    if len(starts) != 1:
        raise ValueError("duplicate CR body section: Checkpoint Index")
    for checkpoint, row in replacements.items():
        _checkpoint_number(checkpoint)
        if row.checkpoint != checkpoint:
            raise ValueError(f"checkpoint row identity mismatch: {checkpoint}/{row.checkpoint}")

    section_start = starts[0] + 1
    section_end = next(
        (index for index in range(section_start, len(lines)) if lines[index].startswith("## ")),
        len(lines),
    )
    header_index = next(
        (index for index in range(section_start, section_end) if lines[index].strip()),
        None,
    )
    if header_index is None:
        raise ValueError("Checkpoint Index table header is missing")
    header = _markdown_table_cells(lines[header_index])
    if header is None or len(header) < 2:
        raise ValueError("Checkpoint Index table header is malformed")
    normalized_header = [cell.strip().lower().replace("_", " ") for cell in header]
    checkpoint_names = {"checkpoint", "cp", "检查点"}
    status_names = {"status", "状态"}
    if normalized_header[0] not in checkpoint_names:
        raise ValueError("Checkpoint Index table schema is unsupported")
    status_indexes = [index for index, name in enumerate(normalized_header) if name in status_names]
    if len(status_indexes) != 1:
        raise ValueError("Checkpoint Index table schema is unsupported")
    status_index = status_indexes[0]
    if status_index == 0:
        raise ValueError("Checkpoint Index status column is malformed")
    ref_names = {"ref", "result ref", "machine result ref", "机器结果 ref", "机器结果引用"}
    ref_indexes = [index for index, name in enumerate(normalized_header) if name in ref_names]
    if len(header) == 2:
        if ref_indexes:
            raise ValueError("two-column Checkpoint Index must not declare a result ref column")
        ref_index: int | None = None
    else:
        if len(ref_indexes) != 1:
            raise ValueError("Checkpoint Index result ref column is missing or ambiguous")
        ref_index = ref_indexes[0]

    separator_index = header_index + 1
    if separator_index >= section_end:
        raise ValueError("Checkpoint Index table separator is missing")
    separator = _markdown_table_cells(lines[separator_index])
    if (
        separator is None
        or len(separator) != len(header)
        or not all(re.fullmatch(r":?-{3,}:?", cell) for cell in separator)
    ):
        raise ValueError("Checkpoint Index table separator is malformed")

    data_start = separator_index + 1
    data_end = data_start
    entries: list[tuple[str, str]] = []
    seen: set[str] = set()
    previous_number = -1
    table_ref_template = ""
    while data_end < section_end:
        raw = lines[data_end]
        if not raw.strip():
            break
        cells = _markdown_table_cells(raw)
        if cells is None:
            break
        if len(cells) != len(header):
            raise ValueError("Checkpoint Index table column count drift")
        checkpoint = cells[0]
        number = _checkpoint_number(checkpoint)
        if checkpoint in seen:
            raise ValueError(f"duplicate CR body table row: Checkpoint Index/{checkpoint}")
        if number <= previous_number:
            raise ValueError("Checkpoint Index rows are not in numeric order")
        seen.add(checkpoint)
        previous_number = number
        if (
            ref_index is not None
            and cells[ref_index]
            and cells[ref_index] != "—"
            and not table_ref_template
        ):
            table_ref_template = cells[ref_index]
        replacement = replacements.get(checkpoint)
        rendered_row = raw
        if replacement is not None:
            cells[status_index] = replacement.status
            if ref_index is not None and replacement.result_ref:
                cells[ref_index] = _checkpoint_ref_cell(
                    replacement.result_ref,
                    template=cells[ref_index],
                )
            rendered_row = _render_markdown_table_row(cells, _markdown_line_ending(raw))
        entries.append((checkpoint, rendered_row))
        data_end += 1

    if any(
        _markdown_table_cells(lines[index]) is not None for index in range(data_end, section_end)
    ):
        raise ValueError("Checkpoint Index contains a non-contiguous table")

    line_ending = _markdown_line_ending(lines[header_index]) or "\n"
    for checkpoint, row in replacements.items():
        if checkpoint in seen:
            continue
        cells = ["—"] * len(header)
        cells[0] = checkpoint
        cells[status_index] = row.status
        if ref_index is not None:
            cells[ref_index] = _checkpoint_ref_cell(
                row.result_ref,
                template=table_ref_template,
            )
        entries.append((checkpoint, _render_markdown_table_row(cells, line_ending)))
    entries.sort(key=lambda item: _checkpoint_number(item[0]))
    table_ends_at_eof = data_end == len(lines)
    preserve_final_newline = not table_ends_at_eof or text.endswith(("\n", "\r"))
    rendered_entries: list[str] = []
    for index, (_checkpoint, raw) in enumerate(entries):
        is_final = index == len(entries) - 1
        existing_ending = _markdown_line_ending(raw)
        desired_ending = (
            (existing_ending or line_ending) if not is_final or preserve_final_newline else ""
        )
        rendered_entries.append(raw.rstrip("\r\n") + desired_ending)
    if rendered_entries and data_start > 0 and not _markdown_line_ending(lines[data_start - 1]):
        lines[data_start - 1] = lines[data_start - 1] + line_ending
    lines[data_start:data_end] = rendered_entries
    return "".join(lines)


def render_status_body_projection(
    text: str,
    *,
    lifecycle_status: str,
    readiness_status: str,
    gate_status: str,
    checkpoint_results: dict[str, CheckpointIndexRowV1 | str] | None = None,
) -> str:
    """Project lifecycle truth into the optional CR body status tables."""
    rendered = _render_exact_section_rows(
        text,
        "CR 类型与门禁策略",
        {"生命周期状态": lifecycle_status, "就绪状态": readiness_status, "门禁状态": gate_status},
    )
    checkpoint_projection = {
        checkpoint: (
            row
            if isinstance(row, CheckpointIndexRowV1)
            else CheckpointIndexRowV1(checkpoint=checkpoint, status=row)
        )
        for checkpoint, row in (checkpoint_results or {}).items()
    }
    checkpoint = _gate_checkpoint_projection(gate_status)
    if checkpoint is not None:
        checkpoint_id, checkpoint_status = checkpoint
        if checkpoint_status == "approved" or checkpoint_id not in checkpoint_projection:
            existing = checkpoint_projection.get(checkpoint_id)
            checkpoint_projection[checkpoint_id] = CheckpointIndexRowV1(
                checkpoint=checkpoint_id,
                status=checkpoint_status,
                result_ref=existing.result_ref if existing is not None else "",
            )
    if not checkpoint_projection:
        return rendered
    return _render_checkpoint_index_rows(rendered, checkpoint_projection)


def summary_from_cr_file(
    project_root: Path,
    path: Path,
    *,
    status: str | None = None,
    readiness: str | None = None,
    gate_status: str | None = None,
    read_context: ReadContextProtocol | None = None,
    text: str | None = None,
    rel_fn: Any | None = None,
) -> dict[str, Any]:
    relative = rel_fn or _rel
    if text is None:
        text = (
            path.read_text(encoding="utf-8")
            if read_context is None
            else read_context.read_text(relative(project_root, path))
        )
    record = record_from_cr_file(
        project_root,
        path,
        _rel_fn=relative,
        read_context=read_context,
        text=text,
    )
    projected_status = status or record.status
    decision_status = _decision_status_from_owners(
        project_root,
        record.cr_id,
        text,
        read_context=read_context,
    )
    if projected_status == "closed" and decision_status == "pending":
        raise ValueError("closed CR cannot have decision_status=pending")
    release_owner = _load_summary_release_context(
        project_root,
        record.cr_id,
        read_context=read_context,
    )
    summary = {
        "id": record.cr_id,
        "cr_type": record.cr_type,
        "title": record.title,
        "status": projected_status,
        "readiness": readiness or record.readiness,
        "gate_status": gate_status or record.gate_status,
        "gate_profile": record.gate_profile,
        "decision_status": decision_status,
        "scope_summary": _section_summary(text, "## 变更描述") or [record.title],
        "impact_surface": record.impact_surface,
        **_impact_split_payload(record),
        "impact_capability_resolution": record.impact_capability_resolution,
        "impact_capability_normalized": _normalized_capability_refs(
            record.impact_capability_resolution
        ),
        "conflict_keys": record.conflict_keys,
        "remaining_risks": record.risk_refs,
        "authz_policy_refs": record.authz_policy_refs,
        "goal_ref": record.goal_ref,
        "goal_statement": record.goal_statement or _first_section_summary(text, "## 目标影响摘要"),
        "user_goal_impact": record.user_goal_impact,
        "split_rationale": record.split_rationale or _first_section_summary(text, "## 拆分理由"),
        "why_not_merge_with_parent": record.why_not_merge_with_parent,
        "why_not_story_or_task": record.why_not_story_or_task,
        "approval_focus": record.approval_focus,
        "decision_burden": record.decision_burden,
        "approve_effect": record.approve_effect or _first_section_summary(text, "## approve 后果"),
        "reject_effect": record.reject_effect,
        "not_authorized_by_approve": record.not_authorized_by_approve
        or _section_summary(text, "## 不授权范围"),
        "product_baseline_refresh_required": record.product_baseline_refresh_required,
        "required_phase": record.required_phase,
        "required_agent": record.required_agent,
        "required_gate": record.required_gate,
        "block_story_decomposition_until": record.block_story_decomposition_until,
        "affected_product_docs": record.affected_product_docs,
        "affected_use_cases": record.affected_use_cases,
        "routing_design_ref": record.routing_design_ref,
        "required_evidence": _record_required_evidence(record, text),
        "required_capabilities": record.required_capabilities,
        "full_ref": record.full_ref,
        "evidence_index_ref": (
            CR_ARCHIVE_ROOT_REL / record.cr_id / "evidence-index.json"
        ).as_posix(),
        "updated_at": now_utc(),
    }
    if release_owner is not None:
        release_ref, release_context = release_owner
        follow_up_candidates = _follow_up_projection(release_ref, release_context)
        if follow_up_candidates:
            summary["followup_candidates"] = follow_up_candidates
            summary["follow_up_tracking_ref"] = release_ref
    blockers, needs_review = collect_scope_authz_findings(record, text=text)
    summary["scope_authz_consistency"] = {
        "decision": "BLOCKED" if blockers else "NEEDS_REVIEW" if needs_review else "PASS",
        "blockers": blockers,
        "needs_review": needs_review,
    }
    governance_findings = collect_governance_dependency_findings(project_root, record)
    summary["governance_dependency_review"] = {
        "decision": "NEEDS_REVIEW" if governance_findings else "PASS",
        "findings": governance_findings,
    }
    archive_findings = collect_archive_isolation_findings(record, project_root=project_root)
    summary["cp1_review_profile"] = classify_cp1_review_profile(record)
    summary["archive_isolation_review"] = {
        "decision": "NEEDS_REVIEW" if archive_findings else "PASS",
        "findings": archive_findings,
    }
    return summary


def write_summary(project_root: Path, cr_id: str, summary: dict[str, Any]) -> Path:
    path = (
        _resolve_runtime_ref(project_root, CR_SUMMARY_ROOT_REL.as_posix()) / f"{cr_id}.summary.json"
    )
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = None
        if isinstance(existing, dict):
            existing_semantic = dict(existing)
            candidate_semantic = dict(summary)
            existing_semantic.pop("updated_at", None)
            candidate_semantic.pop("updated_at", None)
            if existing_semantic == candidate_semantic:
                return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return path


def write_evidence_index(project_root: Path, cr_id: str, summary: dict[str, Any]) -> Path:
    path = (
        _resolve_runtime_ref(project_root, CR_ARCHIVE_ROOT_REL.as_posix())
        / cr_id
        / "evidence-index.json"
    )
    data = {
        "cr_id": cr_id,
        "summary_ref": (CR_SUMMARY_ROOT_REL / f"{cr_id}.summary.json").as_posix(),
        "full_ref": summary.get("full_ref"),
        "evidence_refs": [],
        "created_at": now_utc(),
    }
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = None
        if isinstance(existing, dict):
            existing_semantic = dict(existing)
            candidate_semantic = dict(data)
            existing_semantic.pop("created_at", None)
            candidate_semantic.pop("created_at", None)
            if existing_semantic == candidate_semantic:
                return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def append_ledger_event(
    project_root: Path, event: dict[str, Any], *, resolve_runtime_ref_fn: Any | None = None
) -> Path:
    resolve = resolve_runtime_ref_fn or _resolve_runtime_ref
    path = resolve(project_root, CR_LEDGER_REL.as_posix())
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def load_ledger_events(
    project_root: Path, *, resolve_runtime_ref_fn: Any | None = None
) -> list[dict[str, Any]]:
    resolve = resolve_runtime_ref_fn or _resolve_runtime_ref
    path = resolve(project_root, CR_LEDGER_REL.as_posix())
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no} invalid JSON: {exc}") from exc
    return events


def project_native_cr_status(
    project_root: Path,
    *,
    cr_id: str,
    resolve_runtime_ref: Any,
    rel: Any,
    load_index: Any,
    excluded_legacy_paths: frozenset[Path] | None = None,
    partition_report: Any | None = None,
) -> NativeCRStatusProjectionV1:
    """交叉验证 formal CR、summary、index 和 append-only ledger 的状态。

    publisher 等下游只能消费这个投影，不再各自解释 frontmatter。
    """
    findings: list[str] = []
    partition_digest = ""
    if partition_report is not None:
        partition_digest = str(partition_report.snapshot_digest)
        if partition_report.decision != "PASS":
            return NativeCRStatusProjectionV1(
                cr_id=cr_id,
                lifecycle_status="",
                readiness_status="",
                gate_status="",
                formal_cr_ref="",
                summary_ref="",
                ledger_event_id="",
                decision="BLOCKED",
                findings=tuple(partition_report.reason_codes),
                partition_snapshot_digest=partition_digest,
            )
        formal_crs = {}
        for logical_ref in partition_report.native_formal_cr_refs:
            match = re.search(r"CR-\d+", Path(logical_ref).name)
            if match is not None:
                formal_crs[match.group(0)] = resolve_runtime_ref(project_root, logical_ref)
    else:
        formal_crs = discover_formal_crs(
            project_root,
            _resolve_runtime_ref_fn=resolve_runtime_ref,
            _rel_fn=rel,
            excluded_legacy_paths=excluded_legacy_paths,
        )
    formal_path = formal_crs.get(cr_id)
    if formal_path is None:
        return NativeCRStatusProjectionV1(
            cr_id=cr_id,
            lifecycle_status="",
            readiness_status="",
            gate_status="",
            formal_cr_ref="",
            summary_ref="",
            ledger_event_id="",
            decision="BLOCKED",
            findings=("FORMAL_CR_MISSING",),
        )
    record = record_from_cr_file(project_root, formal_path, _rel_fn=rel)
    formal_ref = record.full_ref
    summary_ref = record.summary_ref
    formal_tuple = (
        cr_tracking.normalize_lifecycle_status(record.status),
        cr_tracking.normalize_readiness_status(record.readiness),
        cr_tracking.normalize_gate_status(record.gate_status),
    )
    if cr_tracking.validate_native_status_tuple(*formal_tuple):
        findings.append("FORMAL_CR_STATUS_TUPLE_INVALID")
    index = load_index(project_root)
    index_items = index.get("items") if isinstance(index, dict) else None
    index_item = next(
        (
            item
            for item in index_items or []
            if isinstance(item, dict) and str(item.get("id") or "") == cr_id
        ),
        None,
    )
    if index_item is None:
        findings.append("CR_INDEX_ITEM_MISSING")
    else:
        index_tuple = (
            cr_tracking.normalize_lifecycle_status(
                str(index_item.get("lifecycle_status") or ""),
                fallback_status=str(index_item.get("status") or ""),
            ),
            cr_tracking.normalize_readiness_status(
                str(index_item.get("readiness_status") or index_item.get("readiness") or "")
            ),
            cr_tracking.normalize_gate_status(str(index_item.get("gate_status") or "")),
        )
        if index_tuple != formal_tuple:
            findings.append("CR_INDEX_STATUS_DIVERGED")
        if str(index_item.get("full_ref") or index_item.get("formal_cr_path") or "") != formal_ref:
            findings.append("CR_INDEX_FORMAL_REF_DIVERGED")
        if str(index_item.get("summary_ref") or "") != summary_ref:
            findings.append("CR_INDEX_SUMMARY_REF_DIVERGED")
    summary_path = resolve_runtime_ref(project_root, summary_ref)
    summary: dict[str, Any] = {}
    if not summary_path.is_file():
        findings.append("CR_SUMMARY_MISSING")
    else:
        try:
            loaded_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            findings.append("CR_SUMMARY_INVALID_JSON")
        else:
            if not isinstance(loaded_summary, dict):
                findings.append("CR_SUMMARY_INVALID_SHAPE")
            else:
                summary = loaded_summary
    if summary:
        summary_tuple = (
            cr_tracking.normalize_lifecycle_status(str(summary.get("status") or "")),
            cr_tracking.normalize_readiness_status(str(summary.get("readiness") or "")),
            cr_tracking.normalize_gate_status(str(summary.get("gate_status") or "")),
        )
        if str(summary.get("id") or "") != cr_id:
            findings.append("CR_SUMMARY_ID_DIVERGED")
        if str(summary.get("full_ref") or "") != formal_ref:
            findings.append("CR_SUMMARY_FORMAL_REF_DIVERGED")
        if summary_tuple != formal_tuple:
            findings.append("CR_SUMMARY_STATUS_DIVERGED")
        findings.extend(
            "CR_SUMMARY_SEMANTIC:" + finding
            for finding in validate_summary_semantics(project_root, cr_id, summary)
        )
    ledger_events = [
        event
        for event in load_ledger_events(project_root, resolve_runtime_ref_fn=resolve_runtime_ref)
        if str(event.get("id") or event.get("cr_id") or "") == cr_id
        and all((key in event for key in ("status", "readiness", "gate_status")))
    ]
    ledger_event = ledger_events[-1] if ledger_events else None
    ledger_event_id = ""
    if ledger_event is None:
        findings.append("CR_LEDGER_STATUS_EVENT_MISSING")
    else:
        ledger_event_id = str(ledger_event.get("event_id") or "")
        ledger_tuple = (
            cr_tracking.normalize_lifecycle_status(str(ledger_event.get("status") or "")),
            cr_tracking.normalize_readiness_status(str(ledger_event.get("readiness") or "")),
            cr_tracking.normalize_gate_status(str(ledger_event.get("gate_status") or "")),
        )
        if not ledger_event_id:
            findings.append("CR_LEDGER_EVENT_ID_MISSING")
        if str(ledger_event.get("full_ref") or "") != formal_ref:
            findings.append("CR_LEDGER_FORMAL_REF_DIVERGED")
        if str(ledger_event.get("summary_ref") or "") != summary_ref:
            findings.append("CR_LEDGER_SUMMARY_REF_DIVERGED")
        if ledger_tuple != formal_tuple:
            findings.append("CR_LEDGER_STATUS_DIVERGED")
    return NativeCRStatusProjectionV1(
        cr_id=cr_id,
        lifecycle_status=formal_tuple[0],
        readiness_status=formal_tuple[1],
        gate_status=formal_tuple[2],
        formal_cr_ref=formal_ref,
        summary_ref=summary_ref,
        ledger_event_id=ledger_event_id,
        decision="PASS" if not findings else "BLOCKED",
        findings=tuple(findings),
        partition_snapshot_digest=partition_digest,
    )


def _atomic_write_text(path: Path, text: str) -> None:
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    target_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 420
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(target_mode)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _transaction_root(project_root: Path, *, process_root: Path | None = None) -> Path:
    process_root = _process_root(project_root) if process_root is None else process_root.resolve()
    common = _git_fact(process_root, "rev-parse", "--git-common-dir")
    if common:
        path = Path(common)
        common_root = path if path.is_absolute() else process_root / path
    else:
        common_root = process_root / ".meta-flow-fixture-git"
    return common_root.resolve(strict=False) / "meta-flow" / "transactions"


def _status_sync_writer_lock_path(
    project_root: Path,
    *,
    transaction_root: Path | None = None,
) -> Path:
    root = (
        _transaction_root(project_root.resolve()) if transaction_root is None else transaction_root
    )
    return root.parent / "status-sync.lock"


def _acquire_status_sync_writer_lock(
    project_root: Path,
    *,
    transaction_id: str,
    purpose: str,
    transaction_root: Path | None = None,
) -> dict[str, Any] | None:
    """Acquire the cooperative global writer lock and persist owner identity."""
    lock_path = _status_sync_writer_lock_path(
        project_root,
        transaction_root=transaction_root,
    )
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    acquired_at = now_utc()
    owner = {
        "schema_version": 1,
        "owner_token": uuid.uuid4().hex,
        "owner_process_identity": f"pid:{os.getpid()}:instance:{uuid.uuid4().hex}",
        "owner_started_at": acquired_at,
        "acquired_at": acquired_at,
        "transaction_id": transaction_id,
        "purpose": purpose,
        "lease_state": "held",
    }
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 384)
    except FileExistsError:
        return None
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(owner, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        lock_path.unlink(missing_ok=True)
        raise
    return owner


def _release_status_sync_writer_lock(
    project_root: Path,
    owner: dict[str, Any],
    *,
    transaction_root: Path | None = None,
) -> bool:
    """Release only the lock whose persisted owner token matches the caller."""
    lock_path = _status_sync_writer_lock_path(
        project_root,
        transaction_root=transaction_root,
    )
    try:
        first_stat = lock_path.stat()
        persisted = json.loads(lock_path.read_text(encoding="utf-8"))
        second_stat = lock_path.stat()
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return False
    if (
        persisted.get("owner_token") != owner.get("owner_token")
        or persisted.get("owner_process_identity") != owner.get("owner_process_identity")
        or (first_stat.st_dev, first_stat.st_ino) != (second_stat.st_dev, second_stat.st_ino)
    ):
        return False
    try:
        lock_path.unlink()
    except FileNotFoundError:
        return False
    return True
