from __future__ import annotations

import json
from pathlib import Path

import pytest
from cr065_io_harness import (
    load_cases,
    measure_default_disabled_overhead,
    run_after_case,
    run_case,
)

from meta_flow.work.io_metrics import IOMetrics, classify_logical_ref

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "cr065" / "workflow_io_cases.json"


def test_six_fixture_slots_and_selection_evidence_are_frozen() -> None:
    payload = load_cases(FIXTURE_PATH)

    assert payload["baseline_revision"] == "C65-I0-before-v1"
    assert payload["measurement_kind"] == "deterministic-logical-proxy"
    assert payload["governance_denominator_frozen"] is True
    assert [case["risk_profile"] for case in payload["cases"]] == [
        "G0",
        "G0",
        "G1",
        "G1",
        "G2",
        "G2",
    ]
    evidence = payload["selection_evidence"]
    assert evidence["native_cr_053_064"]["representativeness"] == ("insufficient-for-routine-g0-g1")
    assert evidence["existing_work_count"] == 17


def test_each_fixture_is_logically_deterministic_across_three_runs() -> None:
    payload = load_cases(FIXTURE_PATH)

    for case in payload["cases"]:
        runs = [run_case(case) for _ in range(3)]
        assert runs[0] == runs[1] == runs[2]
        assert runs[0]["measurement"] == "enabled"
        assert runs[0]["persistence_writes"] == 0
        assert runs[0]["totals"]["check_groups"] == case["check_groups"]
        assert runs[0]["token_proxy"]["status"] == "proxy"


def test_after_proxy_is_six_of_six_deterministic_and_keeps_before_revision() -> None:
    payload = load_cases(FIXTURE_PATH)

    for case in payload["cases"]:
        runs = [run_after_case(case) for _ in range(3)]
        assert runs[0] == runs[1] == runs[2]
        assert runs[0]["baseline_revision"] == "C65-I0-before-v1"
        assert runs[0]["measurement"] == "enabled"
        assert runs[0]["persistence_writes"] == 0


def test_after_proxy_meets_read_token_and_capsule_reduction_targets() -> None:
    cases = load_cases(FIXTURE_PATH)["cases"]
    routine_cases = [case for case in cases if case["risk_profile"] in {"G0", "G1"}]
    before = [run_case(case) for case in routine_cases]
    after = [run_after_case(case) for case in routine_cases]
    before_reads = sum(item["governance_totals"]["physical_reads"] for item in before)
    after_reads = sum(item["governance_totals"]["physical_reads"] for item in after)
    before_tokens = sum(item["token_proxy"]["value"] for item in before)
    after_tokens = sum(item["token_proxy"]["value"] for item in after)

    assert (before_reads - after_reads) / before_reads >= 0.50
    assert (before_tokens - after_tokens) / before_tokens >= 0.40
    assert sum(item["governance_totals"]["actual_mutations"] for item in before) == 0
    assert sum(item["governance_totals"]["actual_mutations"] for item in after) == 0

    g2_context = next(case for case in cases if case["id"].startswith("G2-F1"))
    before_context = run_case(g2_context)
    after_context = run_after_case(g2_context)
    before_capsule_bytes = next(
        entry["bytes"]
        for entry in before_context["entries"]
        if entry["action"] == "write" and entry["logical_ref"] == "context/CP5-CAPSULE.yaml"
    )
    after_capsule_bytes = next(
        entry["bytes"]
        for entry in after_context["entries"]
        if entry["action"] == "write" and entry["logical_ref"] == "context/CP5-CAPSULE.yaml"
    )
    assert (before_capsule_bytes - after_capsule_bytes) / before_capsule_bytes >= 0.60


def test_governance_denominator_excludes_source_test_git_and_external() -> None:
    metrics = IOMetrics("denominator", enabled=True)
    for ref in (
        ".meta-flow/workspace.yaml",
        "PROJECT.yaml",
        "changes/CR-065-example.md",
        "state/STATE.current.json",
        "state/CR-LEDGER.ndjson",
        "context/CAPSULE.yaml",
    ):
        metrics.record_read(ref, byte_count=10)
    for ref in ("meta_flow/work/model.py", "tests/test_model.py", ".git/index", "README.md"):
        metrics.record_read(ref, byte_count=100)

    summary = metrics.summary()

    assert summary["totals"]["read_count"] == 10
    assert summary["totals"]["bytes"] == 460
    assert summary["governance_totals"]["read_count"] == 6
    assert summary["governance_totals"]["bytes"] == 60


def test_cache_hit_counts_logical_read_without_physical_bytes() -> None:
    metrics = IOMetrics("cache", enabled=True)

    metrics.record_read("PROJECT.yaml", byte_count=600)
    metrics.record_read("PROJECT.yaml", byte_count=600, cache_hit=True)

    totals = metrics.summary()["totals"]
    assert totals["read_count"] == 2
    assert totals["physical_reads"] == 1
    assert totals["bytes"] == 600
    assert totals["cache_hits"] == 1


def test_default_disabled_mode_is_a_noop_and_never_persists() -> None:
    metrics = IOMetrics("normal-mode")

    metrics.record_read("/absolute/path-is-not-inspected-while-disabled", byte_count=-1)
    metrics.record_write_attempt("../same", byte_count=-1, actual_mutation=True)
    metrics.record_check_group(-1)

    assert metrics.summary() == {
        "schema_version": 1,
        "operation_id": "normal-mode",
        "measurement": "disabled",
        "persistence_writes": 0,
        "totals": {
            "read_count": 0,
            "physical_reads": 0,
            "bytes": 0,
            "cache_hits": 0,
            "write_attempts": 0,
            "actual_mutations": 0,
            "check_groups": 0,
        },
        "governance_totals": {
            "read_count": 0,
            "physical_reads": 0,
            "bytes": 0,
            "cache_hits": 0,
            "write_attempts": 0,
            "actual_mutations": 0,
        },
        "entries": [],
    }


def test_default_disabled_instrumentation_overhead_is_at_most_five_percent(
    tmp_path: Path,
) -> None:
    fixture_path = tmp_path / "PROJECT.json"
    fixture_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_id": "fixture-project",
                "name": "Fixture Project",
                "status": "active",
                "phase_refs": [f"phases/P{index}/PHASE.yaml" for index in range(20)],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    result = measure_default_disabled_overhead(fixture_path)

    assert result["instrumentation_mode"] == "normal-default-disabled"
    assert result["operations_per_sample"] == 100
    assert result["persistence_writes"] == 0
    assert result["overhead_percent"] <= result["threshold_percent"], result
    assert result["decision"] == "PASS"


@pytest.mark.parametrize(
    "ref",
    ["/absolute/path", "../outside", "safe/../outside"],
)
def test_enabled_metrics_reject_absolute_or_parent_paths(ref: str) -> None:
    metrics = IOMetrics("safe", enabled=True)

    with pytest.raises(ValueError, match="safe relative"):
        metrics.record_read(ref, byte_count=1)


def test_classification_matches_frozen_governance_categories() -> None:
    assert classify_logical_ref(".meta-flow/workspace.yaml") == "binding_policy"
    assert classify_logical_ref("works/W-1/WORK.yaml") == "project_work"
    assert classify_logical_ref("changes/CR-065-example.md") == "cr_design"
    assert classify_logical_ref("state/STATE.current.json") == "state_projection"
    assert classify_logical_ref("state/CR-LEDGER.ndjson") == "ledger"
    assert classify_logical_ref("context/CAPSULE.yaml") == "context_evidence"
    assert classify_logical_ref("meta_flow/work/model.py") == "product_source"
