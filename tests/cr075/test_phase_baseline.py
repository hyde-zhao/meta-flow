"""CR-075 S06：Phase green baseline lifecycle（STORY-CR075-S06）。"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from meta_flow.execution_control.exact_file_transaction import (
    ExactFileAuthorizationV1,
)
from meta_flow.validation.baseline import (
    apply_baseline,
    check_baseline,
    inspect_baseline,
    invalidate_baseline,
    plan_baseline,
)

_FINGERPRINT = {
    "source_fingerprint": "f" * 64,
    "command_identity": "pytest",
    "environment": "linux#py3.11",
    "provider_identity_digest": "d" * 64,
    "source_manifest_digest": "m" * 64,
    "profile_digest": "p" * 64,
}
_ENTRIES = [
    {"check_id": "CHECK-A", "result_digest": "1" * 64},
    {"check_id": "CHECK-B", "result_digest": "2" * 64},
]


def _phase(process: Path) -> str:
    phase_dir = process / "phases" / "P6-TEST"
    phase_dir.mkdir(parents=True, exist_ok=True)
    (phase_dir / "PHASE.yaml").write_text("schema_version: 1\nphase_id: P6-TEST\n", encoding="utf-8")
    # exact-file shared writer lock 的锚文件（fixture-only）。
    if not (process / ".meta-flow-process.yaml").is_file():
        (process / ".meta-flow-process.yaml").write_text(
            "schema_version: 1\nproject_id: fixture\n", encoding="utf-8"
        )
    return "phases/P6-TEST/PHASE.yaml"


def _apply_fresh(process: Path, phase_ref: str) -> dict:
    plan = plan_baseline(
        process, phase_ref=phase_ref, entries=_ENTRIES, fingerprint=_FINGERPRINT
    )
    assert plan["decision"] == "READY", plan
    exact = plan["exact_plan"]
    authorization = ExactFileAuthorizationV1(
        "AUTH-CR075-S06-BASELINE-20260824-001",
        "phase-baseline.apply",
        plan["exact_plan_digest"],
        tuple(item["ref"] for item in exact["targets"]),
        "2999-01-01T00:00:00Z",
    )
    return apply_baseline(process, plan_payload=plan, authorization=authorization)


def test_plan_apply_freezes_system_namespace_baseline(tmp_path: Path) -> None:
    process = tmp_path
    phase_ref = _phase(process)
    receipt = _apply_fresh(process, phase_ref)

    assert receipt["decision"] == "PASS"
    baseline_path = process / "phases" / "P6-TEST" / "BASELINE.json"
    payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    assert payload["kind"] == "PhaseGreenBaselineV1"
    assert payload["version"] == 1
    assert payload["fingerprint"]["environment"] == "linux#py3.11"
    # P0 成果：target 以 system namespace 冻结。
    assert receipt["planned_refs"] == ["phases/P6-TEST/BASELINE.json"]


def test_check_same_state_passes_with_empty_attribution(tmp_path: Path) -> None:
    process = tmp_path
    phase_ref = _phase(process)
    _apply_fresh(process, phase_ref)

    result = check_baseline(
        process,
        phase_ref=phase_ref,
        current_fingerprint=dict(_FINGERPRINT),
        failing_checks=[],
    )

    assert result["decision"] == "PASS"
    assert result["attribution"] == {}


def test_check_new_regression_when_green_check_now_failing(tmp_path: Path) -> None:
    process = tmp_path
    phase_ref = _phase(process)
    _apply_fresh(process, phase_ref)

    result = check_baseline(
        process,
        phase_ref=phase_ref,
        current_fingerprint=dict(_FINGERPRINT),
        failing_checks=["CHECK-C"],
    )

    assert result["attribution"]["NEW_REGRESSION"] == ["CHECK-C"]


def test_check_existing_drift_attribution(tmp_path: Path) -> None:
    process = tmp_path
    phase_ref = _phase(process)
    _apply_fresh(process, phase_ref)
    current = dict(_FINGERPRINT, source_fingerprint="a" * 64)

    result = check_baseline(
        process, phase_ref=phase_ref, current_fingerprint=current, failing_checks=["CHECK-A"]
    )

    assert result["attribution"]["EXISTING_SOURCE_DRIFT"] == ["CHECK-A"]


def test_check_provider_drift_attribution(tmp_path: Path) -> None:
    process = tmp_path
    phase_ref = _phase(process)
    _apply_fresh(process, phase_ref)
    current = dict(_FINGERPRINT, provider_identity_digest="e" * 64)

    result = check_baseline(
        process, phase_ref=phase_ref, current_fingerprint=current, failing_checks=["CHECK-A"]
    )

    assert result["attribution"]["PROVIDER_DRIFT"] == ["CHECK-A"]


def test_invalidate_is_idempotent_and_appends_version(tmp_path: Path) -> None:
    process = tmp_path
    phase_ref = _phase(process)
    _apply_fresh(process, phase_ref)

    first = invalidate_baseline(
        process, phase_ref=phase_ref, reasons=["SOURCE_FINGERPRINT_DRIFT"], at="2026-08-24T00:00:00Z"
    )
    second = invalidate_baseline(
        process, phase_ref=phase_ref, reasons=["SOURCE_FINGERPRINT_DRIFT"], at="2026-08-24T01:00:00Z"
    )

    assert first["idempotent"] is False and first["version"] == 2
    assert second["idempotent"] is True and second["mutation_count"] == 0
    payload = json.loads((process / "phases" / "P6-TEST" / "BASELINE.json").read_text(encoding="utf-8"))
    assert payload["invalidated_at"] == "2026-08-24T00:00:00Z"

    # 失效后的 check 转 NEEDS_REVIEW。
    check = check_baseline(
        process, phase_ref=phase_ref, current_fingerprint=dict(_FINGERPRINT), failing_checks=[]
    )
    assert check["decision"] == "NEEDS_REVIEW"
    assert check["reason_codes"] == ["BASELINE_INVALIDATED"]


def test_inspect_is_zero_mutation(tmp_path: Path) -> None:
    process = tmp_path
    phase_ref = _phase(process)
    _apply_fresh(process, phase_ref)
    baseline_path = process / "phases" / "P6-TEST" / "BASELINE.json"
    before = baseline_path.read_bytes()

    result = inspect_baseline(process, phase_ref=phase_ref)

    assert result["decision"] == "PASS"
    assert result["mutation_count"] == 0
    assert baseline_path.read_bytes() == before


def test_missing_baseline_is_typed_blocked(tmp_path: Path) -> None:
    result = check_baseline(
        tmp_path, phase_ref="phases/GHOST/PHASE.yaml", current_fingerprint={}, failing_checks=[]
    )
    assert result["decision"] == "BLOCKED"
    assert result["reason_codes"] == ["BASELINE_MISSING"]
