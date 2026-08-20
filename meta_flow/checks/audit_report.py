"""Deterministic, provenance-bearing audit report for Meta Flow ledgers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meta_flow.evidence.telemetry import aggregate_usage, usage_from_event
from meta_flow.project.process_route import _resolve_runtime_ref
from meta_flow.state import event_ledger

CR073_INCIDENT_IDS = frozenset(
    {"R1", "R1-recovery", "R2-admission", "R2-failure", "W1", "R3"}
)
CR073_JOURNEY_IDS = frozenset({"J1", "J2", "J3"})
CR073_STORY_IDS = frozenset(f"STORY-CR073-S{index:02d}" for index in range(7))


@dataclass(frozen=True, slots=True)
class IncidentJourneyRowV1:
    incident_id: str
    journeys: tuple[str, ...]
    scenarios: tuple[str, ...]
    fixtures: tuple[str, ...]
    owner: str
    expected_evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.incident_id or not self.owner:
            raise ValueError("incident row identity and owner are required")
        for field in ("journeys", "scenarios", "fixtures", "expected_evidence"):
            values = getattr(self, field)
            if not values or len(set(values)) != len(values):
                raise ValueError(f"incident row {field} must be non-empty and unique")

    def as_dict(self) -> dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "journeys": list(self.journeys),
            "scenarios": list(self.scenarios),
            "fixtures": list(self.fixtures),
            "owner": self.owner,
            "expected_evidence": list(self.expected_evidence),
        }


@dataclass(frozen=True, slots=True)
class IncidentJourneyCoverageV1:
    rows: tuple[IncidentJourneyRowV1, ...]
    expected_scenario_ids: tuple[str, ...]
    covered_journey_ids: tuple[str, ...]
    covered_scenario_ids: tuple[str, ...]
    finding_codes: tuple[str, ...]

    @property
    def decision(self) -> str:
        return "PASS" if not self.finding_codes else "FAIL"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "IncidentJourneyCoverageV1",
            "decision": self.decision,
            "rows": [item.as_dict() for item in self.rows],
            "expected_scenario_ids": list(self.expected_scenario_ids),
            "covered_journey_ids": list(self.covered_journey_ids),
            "covered_scenario_ids": list(self.covered_scenario_ids),
            "finding_codes": list(self.finding_codes),
        }


@dataclass(frozen=True, slots=True)
class Cr073ScopeBudgetV1:
    story_ids: tuple[str, ...]
    work_ids: tuple[str, ...]
    touched_paths: tuple[str, ...]
    finding_codes: tuple[str, ...]

    @property
    def decision(self) -> str:
        return "PASS" if not self.finding_codes else "FAIL"


def build_incident_journey_coverage(
    rows: Sequence[IncidentJourneyRowV1],
    *,
    expected_scenario_ids: Sequence[str],
) -> IncidentJourneyCoverageV1:
    """保留六轮事故事实，以多对多映射检查三个 journey 与场景覆盖。"""

    normalized = tuple(rows)
    incidents = [item.incident_id for item in normalized]
    findings: set[str] = set()
    if len(incidents) != len(set(incidents)):
        findings.add("INCIDENT_ID_DUPLICATE")
    actual_incidents = set(incidents)
    if CR073_INCIDENT_IDS - actual_incidents:
        findings.add("INCIDENT_ROUND_MISSING")
    if actual_incidents - CR073_INCIDENT_IDS:
        findings.add("INCIDENT_ROUND_UNKNOWN")
    journeys = {journey for item in normalized for journey in item.journeys}
    if journeys - CR073_JOURNEY_IDS:
        findings.add("JOURNEY_ID_UNKNOWN")
    if CR073_JOURNEY_IDS - journeys:
        findings.add("JOURNEY_ORPHAN")
    scenarios = {scenario for item in normalized for scenario in item.scenarios}
    expected = tuple(sorted(set(expected_scenario_ids)))
    if set(expected) - scenarios:
        findings.add("SCENARIO_ORPHAN")
    if scenarios - set(expected):
        findings.add("SCENARIO_ID_UNKNOWN")
    return IncidentJourneyCoverageV1(
        rows=normalized,
        expected_scenario_ids=expected,
        covered_journey_ids=tuple(sorted(journeys)),
        covered_scenario_ids=tuple(sorted(scenarios)),
        finding_codes=tuple(sorted(findings)),
    )


def validate_incident_journey_coverage(
    coverage: IncidentJourneyCoverageV1,
) -> tuple[str, ...]:
    """供 CP7/CP8 consumer 使用的稳定 finding 入口。"""

    return coverage.finding_codes


def validate_cr073_scope_budget(
    *,
    story_ids: Sequence[str],
    work_ids: Sequence[str],
    touched_paths: Sequence[str],
) -> Cr073ScopeBudgetV1:
    """约束 1 CR / 2 Work / 7 Story，并隔离 P7 产品实现路径。"""

    stories = tuple(story_ids)
    works = tuple(work_ids)
    paths = tuple(touched_paths)
    findings: set[str] = set()
    if set(stories) != CR073_STORY_IDS or len(stories) != 7:
        findings.add("CR073_STORY_BUDGET_EXCEEDED_OR_INCOMPLETE")
    if len(set(works)) != 2 or len(works) != 2:
        findings.add("CR073_WORK_BUDGET_EXCEEDED_OR_INCOMPLETE")
    if any(
        path.startswith("process/phases/P7-")
        or path.startswith("meta_flow/state/pause")
        or path.startswith("meta_flow/state/resume")
        for path in paths
    ):
        findings.add("P7_IMPLEMENTATION_SCOPE_LEAK")
    return Cr073ScopeBudgetV1(stories, works, paths, tuple(sorted(findings)))


def build_audit_report(project_root: Path, *, cr_id: str) -> dict[str, Any]:
    root = project_root.resolve()
    dispatch_path = _resolve_runtime_ref(root, "process/state/AGENT-DISPATCH-LEDGER.ndjson")
    events, errors = event_ledger.load_events(dispatch_path)
    scoped = [event for event in events if str(event.get("cr_id") or "") == cr_id]
    attempts = {(str(event.get("dispatch_id") or ""), str(event.get("attempt_id") or "")) for event in scoped if event.get("attempt_id")}
    threads = {str(event.get("thread_id") or "") for event in scoped if event.get("thread_id")}
    terminal_projection = event_ledger.project_terminal_successes(
        event_ledger.ProjectionInputV1(tuple(scoped), "dispatch")
    )
    usages = [usage for event in scoped if (usage := usage_from_event(event)) is not None]
    usage_summary = aggregate_usage(usages)
    digest = hashlib.sha256(dispatch_path.read_bytes()).hexdigest() if dispatch_path.is_file() else ""
    return {
        "schema_version": 1,
        "cr_id": cr_id,
        "checker_provenance": {"checker_name": "meta-flow audit-report", "checker_commit": "working-tree", "input_sha256": f"sha256:{digest}" if digest else None},
        "counts": {
            "event_rows": len(scoped),
            "attempts": len(attempts),
            "threads": len(threads),
            "terminal_events": len(terminal_projection.terminal_event_ids),
        },
        "errors": errors,
        "token_measurement": usage_summary if usages else {"measurement_status_counts": {"estimated": 0, "measured": 0, "unavailable": 0}, "measured_total_tokens": None, "measurement_status": "unavailable", "reason": "not-yet-ingested"},
    }


def write_audit_report(project_root: Path, *, cr_id: str, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(build_audit_report(project_root, cr_id=cr_id), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output
