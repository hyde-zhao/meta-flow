from __future__ import annotations

import pytest

from meta_flow.checks.audit_report import (
    IncidentJourneyRowV1,
    build_incident_journey_coverage,
    validate_cr073_scope_budget,
    validate_incident_journey_coverage,
)

EXPECTED_SCENARIOS = tuple(f"SCN-073-{index:02d}" for index in range(1, 13))


def _row(
    incident_id: str,
    journeys: tuple[str, ...],
    scenarios: tuple[str, ...],
) -> IncidentJourneyRowV1:
    return IncidentJourneyRowV1(
        incident_id=incident_id,
        journeys=journeys,
        scenarios=scenarios,
        fixtures=(f"fixture-{incident_id}",),
        owner="meta-flow",
        expected_evidence=(f"evidence-{incident_id}",),
    )


def canonical_rows() -> tuple[IncidentJourneyRowV1, ...]:
    return (
        _row("R1", ("J1",), ("SCN-073-01", "SCN-073-03")),
        _row(
            "R1-recovery",
            ("J1", "J2"),
            ("SCN-073-02", "SCN-073-04"),
        ),
        _row("R2-admission", ("J1", "J2"), ("SCN-073-05",)),
        _row("R2-failure", ("J2",), ("SCN-073-06", "SCN-073-07")),
        _row("W1", ("J3",), ("SCN-073-08", "SCN-073-09")),
        _row(
            "R3",
            ("J1", "J2", "J3"),
            ("SCN-073-10", "SCN-073-11", "SCN-073-12"),
        ),
    )


def test_six_rounds_map_many_to_many_without_losing_scenarios() -> None:
    coverage = build_incident_journey_coverage(
        canonical_rows(),
        expected_scenario_ids=EXPECTED_SCENARIOS,
    )

    assert coverage.decision == "PASS"
    assert validate_incident_journey_coverage(coverage) == ()
    assert coverage.covered_journey_ids == ("J1", "J2", "J3")
    assert coverage.covered_scenario_ids == EXPECTED_SCENARIOS
    r3 = next(item for item in coverage.rows if item.incident_id == "R3")
    assert r3.journeys == ("J1", "J2", "J3")


@pytest.mark.parametrize(
    ("rows", "expected_code"),
    [
        (canonical_rows()[:-1], "INCIDENT_ROUND_MISSING"),
        (canonical_rows() + (canonical_rows()[0],), "INCIDENT_ID_DUPLICATE"),
        (
            tuple(
                _row(
                    item.incident_id,
                    ("J2",)
                    if item.incident_id == "W1"
                    else tuple(j for j in item.journeys if j != "J3"),
                    item.scenarios,
                )
                if item.incident_id in {"W1", "R3"}
                else item
                for item in canonical_rows()
            ),
            "JOURNEY_ORPHAN",
        ),
    ],
)
def test_missing_duplicate_or_orphan_rounds_fail(
    rows: tuple[IncidentJourneyRowV1, ...],
    expected_code: str,
) -> None:
    coverage = build_incident_journey_coverage(
        rows,
        expected_scenario_ids=EXPECTED_SCENARIOS,
    )
    assert expected_code in coverage.finding_codes


def test_scenario_orphan_is_not_hidden_by_journey_coverage() -> None:
    coverage = build_incident_journey_coverage(
        canonical_rows(),
        expected_scenario_ids=EXPECTED_SCENARIOS + ("SCN-073-13",),
    )

    assert coverage.decision == "FAIL"
    assert "SCENARIO_ORPHAN" in coverage.finding_codes


def test_cr073_budget_is_exact_and_p7_paths_are_isolated() -> None:
    story_ids = tuple(f"STORY-CR073-S{index:02d}" for index in range(7))
    exact = validate_cr073_scope_budget(
        story_ids=story_ids,
        work_ids=("CR-073-WA-ADMISSION-SAFETY-001", "CR-073-WB-VALIDATION-TRUTH-001"),
        touched_paths=("meta_flow/checks/audit_report.py",),
    )
    leaked = validate_cr073_scope_budget(
        story_ids=story_ids + ("STORY-CR073-S07",),
        work_ids=("WA", "WB", "WC"),
        touched_paths=("process/phases/P7-governance/PHASE.yaml",),
    )

    assert exact.decision == "PASS"
    assert leaked.decision == "FAIL"
    assert set(leaked.finding_codes) == {
        "CR073_STORY_BUDGET_EXCEEDED_OR_INCOMPLETE",
        "CR073_WORK_BUDGET_EXCEEDED_OR_INCOMPLETE",
        "P7_IMPLEMENTATION_SCOPE_LEAK",
    }
