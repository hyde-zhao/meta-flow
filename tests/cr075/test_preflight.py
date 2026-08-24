"""CR-075 S01：work lifecycle-preflight 全旅程 + MF-BUG-15 + CHE（STORY-CR075-S01）。

覆盖：五 journey 正/负、R1-1/R2-1/R2-2 事故重放、evidence-kind registry
typed 判定、verify-packet acceptance 锚多形态、CLI 退出码。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from meta_flow.work import preflight_checks
from meta_flow.work.evidence_kind import (
    KNOWN_EVIDENCE_KINDS,
    REGISTRY_VERSION_DIGEST,
    evaluate_evidence_kind,
)
from meta_flow.work.preflight import (
    LIFECYCLE_JOURNEYS,
    run_journey_preflight,
)

_WORK_YAML = """schema_version: 1
work_id: WORK-S01-001
project_id: fixture-project
kind: cr
objective: lifecycle preflight fixture work
status: {status}
request_ref: works/WORK-S01-001/REQUEST.md
request_confirmed: true
risk_profile: G1
risk_reason_codes:
  - PUBLIC_CONTRACT
required_gates:
  - GATE-SCOPE
route_profile:
  schema_version: 1
  mode: routine-four-stage
  dispatch_mode: direct
  legacy_cp_compatibility: false
  validation_profile: layered-v1
  failure_scope: current-slice-only
  worktree_policy: root-branch-only
scope:
  version: 1
  allowed_reads:
    - works/WORK-S01-001/REQUEST.md
  allowed_writes:
    - meta_flow/work/preflight.py
  required_checks:
    - PREFLIGHT-SMOKE
scope_digest: __SCOPE_DIGEST__
budget:
  reads: 128
  writes: 64
  check_groups: 20
  tokens: 384000
usage_ref: works/WORK-S01-001/USAGE.json
base_oids:
  release: ""
  process: ""
"""


def _scope_digest() -> str:
    import hashlib
    import json

    canonical = json.dumps(
        {
            "version": 1,
            "allowed_reads": ["works/WORK-S01-001/REQUEST.md"],
            "allowed_writes": ["meta_flow/work/preflight.py"],
            "required_checks": ["PREFLIGHT-SMOKE"],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _process_fixture(tmp_path: Path, *, status: str = "active") -> Path:
    process = tmp_path / "proc"
    (process / "works" / "WORK-S01-001").mkdir(parents=True)
    (process / "works" / "WORK-S01-001" / "WORK.yaml").write_text(
        _WORK_YAML.format(status=status).replace("__SCOPE_DIGEST__", _scope_digest()),
        encoding="utf-8",
    )
    (process / "works" / "WORK-S01-001" / "REQUEST.md").write_text(
        "# REQUEST fixture\n", encoding="utf-8"
    )
    (process / "works" / "WORK-S01-001" / "USAGE.json").write_text("{}", encoding="utf-8")
    return process


def test_journeys_are_the_five_canonical_values() -> None:
    assert LIFECYCLE_JOURNEYS == {"init", "fail", "recover", "close", "publish"}


def test_init_journey_passes_for_well_formed_work(tmp_path: Path) -> None:
    process = _process_fixture(tmp_path)
    report = run_journey_preflight(process, "WORK-S01-001", "init")
    assert report.decision == "PASS"
    assert report.as_dict()["mutation_count"] == 0
    assert report.schema_version == 1
    assert any(check["id"] == "PREFLIGHT-INIT-02" for check in report.checks)


def test_init_journey_blocks_missing_work(tmp_path: Path) -> None:
    process = _process_fixture(tmp_path)
    report = run_journey_preflight(process, "WORK-UNKNOWN-001", "init")
    assert report.decision == "BLOCKED"
    assert report.checks[0]["code"] == "NATIVE_PLAN_RAISED"


def test_close_journey_blocks_missing_result_ref(tmp_path: Path) -> None:
    process = _process_fixture(tmp_path, status="paused")
    report = run_journey_preflight(process, "WORK-S01-001", "close")
    assert report.decision == "BLOCKED"
    assert any(check["code"] == "CLOSE_PRECONDITION_FAILED" for check in report.checks)


def test_publish_journey_requires_paused(tmp_path: Path) -> None:
    process = _process_fixture(tmp_path, status="active")
    report = run_journey_preflight(process, "WORK-S01-001", "publish")
    assert report.decision == "BLOCKED"
    assert any("paused" in str(check.get("detail", "")) for check in report.checks)


def test_recover_journey_passes_without_partial_transactions(tmp_path: Path) -> None:
    process = _process_fixture(tmp_path)
    report = run_journey_preflight(process, "WORK-S01-001", "recover")
    assert report.decision == "PASS"


def test_story_ref_attach_verify_packet_check(tmp_path: Path) -> None:
    process = _process_fixture(tmp_path)
    story_text = "# Story\n\n## 验收标准\n- 全部 journey 零写\n- typed findings\n"
    report = run_journey_preflight(process, "WORK-S01-001", "init", story_text=story_text)
    packet_check = next(c for c in report.checks if c["id"] == "PREFLIGHT-PACKET-01")
    assert packet_check["decision"] == "PASS"
    assert len(packet_check["anchors"]) == 2


def test_verify_packet_check_blocks_when_no_acceptance_anchors(tmp_path: Path) -> None:
    finding = preflight_checks.check_verify_packet_acceptance("# Story\n\n## 概述\n正文\n")
    assert finding["decision"] == "BLOCKED"
    assert finding["code"] == "VERIFY_PACKET_ACCEPTANCE_ANCHORS_MISSING"


# ---- MF-BUG-15：evidence-kind registry ----


def test_registry_known_kind_with_capabilities_passes() -> None:
    result = evaluate_evidence_kind(
        "real_lake_validation", granted_capabilities={"real_lake_read"}
    )
    assert result["decision"] == "PASS"
    assert result["registry_version_digest"] == REGISTRY_VERSION_DIGEST


def test_registry_known_kind_missing_capability_blocks() -> None:
    result = evaluate_evidence_kind("real_lake_validation", granted_capabilities=set())
    assert result["decision"] == "BLOCKED"
    assert result["code"] == "evidence_kind_capability_missing"
    assert result["missing_capabilities"] == ["real_lake_read"]


def test_registry_unknown_kind_is_typed_needs_review_not_silent() -> None:
    result = evaluate_evidence_kind("mystery_evidence")
    assert result["decision"] == "NEEDS_REVIEW"
    assert result["code"] == "unknown_evidence_kind"
    assert result["mutation_count"] == 0
    assert "mystery_evidence" not in KNOWN_EVIDENCE_KINDS


def test_registry_empty_kind_fails_closed() -> None:
    result = evaluate_evidence_kind("")
    assert result["decision"] == "BLOCKED"
    assert result["code"] == "evidence_kind_empty"


def test_registry_known_acceptance_and_legacy_kinds_pass() -> None:
    for kind in ("provider_fixture", "legacy_closed_cr_evidence"):
        assert evaluate_evidence_kind(kind)["decision"] == "PASS"


# ---- 事故重放：R1-1 / R2-1 / R2-2 ----


def test_r1_1_receipt_target_outside_business_scope_is_blocked() -> None:
    finding = preflight_checks.check_scope_targets(
        ("meta_flow/work/**",),
        ("meta_flow/work/preflight.py", "quant-lab/src/main.py"),
    )
    assert finding["decision"] == "BLOCKED"
    assert finding["code"] == "RECEIPT_TARGET_OUTSIDE_BUSINESS_SCOPE"
    assert finding["outside_targets"] == ["quant-lab/src/main.py"]


def test_r1_1_targets_inside_scope_pass() -> None:
    finding = preflight_checks.check_scope_targets(
        ("meta_flow/**", "tests/**"),
        ("meta_flow/work/preflight.py", "tests/cr075/test_preflight.py"),
    )
    assert finding["decision"] == "PASS"


def test_r2_1_contract_field_drift_is_blocked_per_field() -> None:
    finding = preflight_checks.check_contract_fields(
        {"revision": "2", "ref": "process/x.md", "digest": "a" * 64},
        {"revision": "3", "ref": "process/x.md", "digest": "b" * 64},
    )
    assert finding["decision"] == "BLOCKED"
    assert finding["code"] == "CONTRACT_FIELD_DRIFT"
    assert sorted(finding["drifted_fields"]) == ["digest", "revision"]


def test_r2_2_handoff_outside_scope_and_incomplete_blocker_block() -> None:
    finding = preflight_checks.check_fail_handoff_scope(
        ("meta_flow/**",),
        ("external/quant-lab/x.py",),
        ({"code": "E1", "route": "rework"}, {"code": "", "route": ""}),
    )
    assert finding["decision"] == "BLOCKED"


def test_r2_2_plannable_failover_passes() -> None:
    finding = preflight_checks.check_fail_handoff_scope(
        ("meta_flow/**",),
        ("meta_flow/work/x.py",),
        ({"code": "E1", "route": "rework_same_story"},),
    )
    assert finding["decision"] == "PASS"


# ---- CLI 退出码 ----


def test_cli_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from meta_flow.work.preflight import lifecycle_preflight_main

    process = _process_fixture(tmp_path)
    # 健康 route fixture 不存在：CLI 需要 sibling-binding；直接调用 main 会
    # 走 route 解析失败 → exit 2。此处验证 typed 输出与退出码契约。
    code = lifecycle_preflight_main(
        ["--project-root", str(tmp_path), "--work-id", "WORK-S01-001", "--journey", "init"]
    )
    captured = capsys.readouterr().out
    payload = json.loads(captured)
    assert code == 2
    assert payload["decision"] == "BLOCKED"
    assert payload["code"] == "PROCESS_ROUTE_UNHEALTHY"


def test_cli_happy_path_exit_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from types import SimpleNamespace

    from meta_flow.work import preflight as preflight_module

    process = _process_fixture(tmp_path)
    # 用 monkeypatch 形态注入 route 解析（保持 run_journey_preflight 真实执行）。
    original = preflight_module.lifecycle_preflight_main

    import meta_flow.project.process_route as process_route

    class _Route:
        process_root = process

    def fake_require(root):
        return _Route()

    real_require = process_route.require_process_route
    process_route.require_process_route = fake_require
    try:
        code = original(
            ["--project-root", str(tmp_path), "--work-id", "WORK-S01-001", "--journey", "init"]
        )
    finally:
        process_route.require_process_route = real_require
    captured = capsys.readouterr().out
    payload = json.loads(captured)
    assert code == 0
    assert payload["decision"] == "PASS"
    assert payload["kind"] == "LifecyclePreflightReportV1"
