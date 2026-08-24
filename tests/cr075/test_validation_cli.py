"""CR-075 S04：ValidationReusePlanV2 公共 CLI（STORY-CR075-S04，MF-BUG-05）。"""

from __future__ import annotations

import json
from pathlib import Path

from meta_flow.validation.cli import build_reuse_plan

_FULL_RECEIPT = {
    "decision": "PASS",
    "fingerprint_digest": "f" * 64,
    "profile_digest": "p" * 64,
    "command_identity": "pytest#tests/x.py",
    "environment": "linux#py3.11",
    "source_manifest_digest": "m" * 64,
    "provider_identity_digest": "d" * 64,
}


def _matching_current() -> dict[str, str]:
    return {
        "source_fingerprint": _FULL_RECEIPT["fingerprint_digest"],
        "profile_digest": _FULL_RECEIPT["profile_digest"],
        "command_identity": _FULL_RECEIPT["command_identity"],
        "environment": _FULL_RECEIPT["environment"],
        "source_manifest_digest": _FULL_RECEIPT["source_manifest_digest"],
        "provider_identity_digest": _FULL_RECEIPT["provider_identity_digest"],
    }


def _write_receipt(process: Path, work_id: str, name: str, payload: dict) -> None:
    root = process / "works" / work_id / "validation-receipts"
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(json.dumps(payload), encoding="utf-8")


def test_same_fingerprint_reuses(tmp_path: Path) -> None:
    _write_receipt(tmp_path, "W", "CHECK-1.json", dict(_FULL_RECEIPT))
    plan = build_reuse_plan(tmp_path, work_id="W", current=_matching_current())
    assert plan["decision"] == "PASS"
    assert plan["receipts"][0]["action"] == "REUSE"
    assert plan["receipts"][0]["attribution"] == "REUSABLE"
    assert plan["mutation_count"] == 0


def test_v1_receipt_missing_secure_field_runs_without_forged_reuse(tmp_path: Path) -> None:
    partial = {
        key: value
        for key, value in _FULL_RECEIPT.items()
        if key not in {"provider_identity_digest", "source_manifest_digest"}
    }
    _write_receipt(tmp_path, "W", "CHECK-1.json", partial)
    plan = build_reuse_plan(tmp_path, work_id="W", current=_matching_current())
    assert plan["receipts"][0]["action"] == "RUN"
    assert "V1_RECEIPT_MISSING_SECURE_FIELD" in plan["receipts"][0]["reason_codes"]
    assert plan["receipts"][0]["attribution"] == "UNATTRIBUTABLE"


def test_command_identity_drift_runs(tmp_path: Path) -> None:
    _write_receipt(tmp_path, "W", "CHECK-1.json", dict(_FULL_RECEIPT))
    current = _matching_current()
    current["command_identity"] = "pytest#tests/other.py"
    plan = build_reuse_plan(tmp_path, work_id="W", current=current)
    assert plan["receipts"][0]["action"] == "RUN"
    assert "COMMAND_IDENTITY_DRIFT" in plan["receipts"][0]["reason_codes"]


def test_environment_drift_attributed(tmp_path: Path) -> None:
    _write_receipt(tmp_path, "W", "CHECK-1.json", dict(_FULL_RECEIPT))
    current = _matching_current()
    current["environment"] = "windows#py3.12"
    plan = build_reuse_plan(tmp_path, work_id="W", current=current)
    assert plan["receipts"][0]["attribution"] == "ENVIRONMENT_DRIFT"


def test_provider_drift_attributed(tmp_path: Path) -> None:
    _write_receipt(tmp_path, "W", "CHECK-1.json", dict(_FULL_RECEIPT))
    current = _matching_current()
    current["provider_identity_digest"] = "e" * 64
    plan = build_reuse_plan(tmp_path, work_id="W", current=current)
    assert plan["receipts"][0]["attribution"] == "PROVIDER_DRIFT"


def test_existing_source_drift_attributed(tmp_path: Path) -> None:
    _write_receipt(tmp_path, "W", "CHECK-1.json", dict(_FULL_RECEIPT))
    current = _matching_current()
    current["source_fingerprint"] = "a" * 64
    plan = build_reuse_plan(tmp_path, work_id="W", current=current)
    assert plan["receipts"][0]["attribution"] == "EXISTING_SOURCE_DRIFT"


def test_declared_check_without_receipt_is_new_regression(tmp_path: Path) -> None:
    plan = build_reuse_plan(
        tmp_path,
        work_id="W",
        current=_matching_current(),
        declared_checks=["CHECK-NEW"],
    )
    entry = next(item for item in plan["receipts"] if item.get("check_id") == "CHECK-NEW")
    assert entry["action"] == "RUN"
    assert entry["attribution"] == "NEW_REGRESSION"
    assert plan["summary"]["NEW_REGRESSION"] == 1


def test_empty_receipts_dir_yields_pass_with_empty_summary(tmp_path: Path) -> None:
    plan = build_reuse_plan(tmp_path, work_id="W", current={})
    assert plan["decision"] == "PASS"
    assert plan["receipts"] == []
    assert plan["summary"] == {}


# ---- S02+S04 联合回修 ----


def test_invalidated_receipt_forces_run(tmp_path: Path) -> None:
    _write_receipt(
        tmp_path,
        "W",
        "CHECK-1.json",
        {**_FULL_RECEIPT, "invalidated_by_scope_version": 2,
         "invalidation_reason": "INVALIDATED_BY_SCOPE_VERSION"},
    )
    plan = build_reuse_plan(tmp_path, work_id="W", current=_matching_current())
    entry = plan["receipts"][0]
    assert entry["action"] == "RUN"
    assert "RECEIPT_INVALIDATED_BY_SCOPE_VERSION" in entry["reason_codes"]
    assert entry["attribution"] == "INVALIDATED_BY_SCOPE_VERSION"
    assert plan["decision"] == "RUN_REQUIRED"
    assert plan["run_count"] == 1


def test_missing_receipts_with_declared_checks_is_not_empty_pass(tmp_path: Path) -> None:
    plan = build_reuse_plan(
        tmp_path, work_id="W", current=_matching_current(), declared_checks=["CHECK-X"]
    )
    assert plan["decision"] == "RUN_REQUIRED"
    assert plan["run_count"] == 1
    assert plan["summary"]["NEW_REGRESSION"] == 1


def test_cross_story_scope_amend_invalidates_then_validation_plan_runs(tmp_path: Path) -> None:
    """跨 Story 集成：scope amendment 失效标记 -> validation-plan 强制 RUN。"""

    from meta_flow.work import scope_amend
    from meta_flow.work.model import G1ScopeDeltaV1

    work_id = "W"
    receipts = tmp_path / "works" / work_id / "validation-receipts"
    receipts.mkdir(parents=True)
    receipt_path = receipts / "CHECK-1.json"
    receipt_path.write_text(
        json.dumps({**_FULL_RECEIPT, "paths": ["meta_flow/alpha/x.py"]}),
        encoding="utf-8",
    )
    delta = G1ScopeDeltaV1.from_mapping(
        {
            "schema_version": 1,
            "add_reads": [],
            "add_writes": ["meta_flow/alpha/**"],
            "add_checks": [],
            "reason": "cross-story integration",
        }
    )
    entries = scope_amend.plan_receipt_invalidation(tmp_path, work_id, delta)
    invalidated = next(e for e in entries if e["decision"] == "invalidated")

    # 手工执行 S02 apply 的标记写入（_mark_invalidated_receipts 需要 plan 视图）。
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["invalidated_by_scope_version"] = 2
    payload["invalidation_reason"] = invalidated["reason"]
    receipt_path.write_text(json.dumps(payload), encoding="utf-8")

    plan = build_reuse_plan(tmp_path, work_id=work_id, current=_matching_current())
    entry = plan["receipts"][0]
    assert entry["action"] == "RUN"
    assert entry["attribution"] == "INVALIDATED_BY_SCOPE_VERSION"
