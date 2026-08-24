"""CR-075 S06：Phase green baseline lifecycle（STORY-CR075-S06）。"""

from __future__ import annotations

import json
from pathlib import Path

from meta_flow.execution_control.exact_file_transaction import (
    ExactFileAuthorizationV1,
)
from meta_flow.validation.baseline import (
    apply_baseline,
    check_baseline,
    inspect_baseline,
    plan_baseline,
    plan_invalidation,
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


def _invalidate_typed(process: Path, phase_ref: str, *, at: str, suffix: str = "R1") -> dict:
    from meta_flow.validation.baseline import apply_invalidation, plan_invalidation

    plan = plan_invalidation(
        process, phase_ref=phase_ref, reasons=["SOURCE_FINGERPRINT_DRIFT"], at=at
    )
    assert plan["decision"] == "READY", plan
    authorization = ExactFileAuthorizationV1(
        f"AUTH-CR075-S06-INVL-{suffix}",
        "phase-baseline.invalidate",
        plan["exact_plan_digest"],
        tuple(item["ref"] for item in plan["exact_plan"]["targets"]),
        "2999-01-01T00:00:00Z",
    )
    return apply_invalidation(process, plan_payload=plan, authorization=authorization)


def test_typed_invalidate_appends_version_then_rebaseline_blocked(tmp_path: Path) -> None:
    process = tmp_path
    phase_ref = _phase(process)
    _apply_fresh(process, phase_ref)

    first = _invalidate_typed(process, phase_ref, at="2026-08-24T00:00:00Z")
    assert first["decision"] == "PASS"
    payload = json.loads((process / "phases" / "P6-TEST" / "BASELINE.json").read_text(encoding="utf-8"))
    assert payload["version"] == 2
    assert payload["invalidated_at"] == "2026-08-24T00:00:00Z"

    # 二次失效：NO_CHANGE（幂等，零 mutation）。
    second_plan = plan_invalidation(
        process, phase_ref=phase_ref, reasons=["SOURCE_FINGERPRINT_DRIFT"], at="2026-08-24T01:00:00Z"
    )
    assert second_plan["decision"] == "NO_CHANGE"
    assert second_plan["idempotent"] is True

    # 失效后的 check 转 NEEDS_REVIEW。
    check = check_baseline(
        process, phase_ref=phase_ref, current_fingerprint=dict(_FINGERPRINT), failing_checks=[]
    )
    assert check["decision"] == "NEEDS_REVIEW"
    assert check["reason_codes"] == ["BASELINE_INVALIDATED"]

    # 失效后允许 rebaseline（version+1）。
    rebaseline = plan_baseline(
        process, phase_ref=phase_ref, entries=_ENTRIES, fingerprint=_FINGERPRINT
    )
    assert rebaseline["decision"] == "READY"


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


# ---- S06 整改：负向与语义修正 ----


def test_valid_baseline_cannot_be_rebaselined_in_place(tmp_path: Path) -> None:
    process = tmp_path
    phase_ref = _phase(process)
    _apply_fresh(process, phase_ref)

    again = plan_baseline(
        process, phase_ref=phase_ref, entries=_ENTRIES, fingerprint=_FINGERPRINT
    )

    assert again["decision"] == "BLOCKED"
    assert again["reason_codes"] == ["BASELINE_ALREADY_ACTIVE"]


def test_failing_checks_present_is_not_pass(tmp_path: Path) -> None:
    process = tmp_path
    phase_ref = _phase(process)
    _apply_fresh(process, phase_ref)

    result = check_baseline(
        process,
        phase_ref=phase_ref,
        current_fingerprint=dict(_FINGERPRINT),
        failing_checks=["CHECK-A"],
    )

    assert result["decision"] == "FAILINGS_PRESENT"
    assert result["failing_count"] == 1


def test_green_turned_failing_without_drift_is_unattributable(tmp_path: Path) -> None:
    process = tmp_path
    phase_ref = _phase(process)
    _apply_fresh(process, phase_ref)

    result = check_baseline(
        process,
        phase_ref=phase_ref,
        current_fingerprint=dict(_FINGERPRINT),
        failing_checks=["CHECK-A"],
    )

    assert result["attribution"]["UNATTRIBUTABLE"] == ["CHECK-A"]


def test_invalidate_apply_without_authorization_is_typed_blocked(tmp_path: Path) -> None:
    process = tmp_path
    phase_ref = _phase(process)
    _apply_fresh(process, phase_ref)

    import contextlib

    from meta_flow.validation.baseline import baseline_main

    with contextlib.redirect_stdout(__import__("io").StringIO()) as buffer:
        code = baseline_main(
            ["--project-root", str(process), "invalidate", "--phase-ref", phase_ref,
             "--plan", "/nonexistent-plan.json", "--authorization", "/nonexistent-auth.json"]
        )
    payload = json.loads(buffer.getvalue())
    assert code == 2
    assert payload["decision"] == "BLOCKED"


def test_invalidate_apply_plan_drift_is_blocked(tmp_path: Path) -> None:
    from meta_flow.validation.baseline import apply_invalidation, plan_invalidation

    process = tmp_path
    phase_ref = _phase(process)
    _apply_fresh(process, phase_ref)
    plan = plan_invalidation(
        process, phase_ref=phase_ref, reasons=["SOURCE_FINGERPRINT_DRIFT"], at="2026-08-24T00:00:00Z"
    )
    plan["exact_plan_digest"] = "0" * 64  # 漂移

    authorization = ExactFileAuthorizationV1(
        "AUTH-CR075-S06-INVL-DRIFT",
        "phase-baseline.invalidate",
        "0" * 64,
        ("phases/P6-TEST/BASELINE.json",),
        "2999-01-01T00:00:00Z",
    )
    result = apply_invalidation(process, plan_payload=plan, authorization=authorization)
    assert result["decision"] == "BLOCKED"
    assert result["reason_codes"] == ["PLAN_DIGEST_MISMATCH"]


def test_apply_with_missing_authorization_fails_closed(tmp_path: Path) -> None:
    """apply 的 typed authorization 缺失（CLI 无 --authorization）-> BLOCKED。"""

    import contextlib

    from meta_flow.validation.baseline import baseline_main

    process = tmp_path
    phase_ref = _phase(process)
    with contextlib.redirect_stdout(__import__("io").StringIO()) as buffer:
        code = baseline_main(
            ["--project-root", str(process), "apply", "--phase-ref", phase_ref,
             "--plan", "/nonexistent.json", "--authorization", "/nonexistent-auth.json"]
        )
    payload = json.loads(buffer.getvalue())
    assert code == 2
    assert payload["decision"] == "BLOCKED"


def test_unsafe_phase_ref_is_blocked(tmp_path: Path) -> None:
    for bad_ref in ("../escape/PHASE.yaml", "/abs/PHASE.yaml", "a/../b/PHASE.yaml"):
        result = plan_baseline(
            tmp_path, phase_ref=bad_ref, entries=_ENTRIES, fingerprint=_FINGERPRINT
        )
        assert result["reason_codes"] == ["PHASE_REF_UNSAFE"], bad_ref


def test_symlink_phase_file_is_blocked(tmp_path: Path) -> None:
    import os

    real = tmp_path / "real-PHASE.yaml"
    real.write_text("schema_version: 1\n", encoding="utf-8")
    phase_dir = tmp_path / "phases" / "P6-LINK"
    phase_dir.mkdir(parents=True)
    os.symlink(real, phase_dir / "PHASE.yaml")

    result = plan_baseline(
        tmp_path, phase_ref="phases/P6-LINK/PHASE.yaml", entries=_ENTRIES, fingerprint=_FINGERPRINT
    )
    assert result["reason_codes"] == ["PHASE_FILE_MISSING"]
