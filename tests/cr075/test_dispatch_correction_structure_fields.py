"""CR-075 V4 门禁整改项 3：dispatch correction 结构字段补齐。

覆盖 build/plan 的结构字段路径（dispatch_id/canonical_role 追认）、
``dispatch_correction_index`` 的白名单扩展、行级校验豁免降级，
以及 terminal_result 路径既有 event_id 计算的硬性回归约束。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from meta_flow.state import dispatch_correction, event_ledger
from meta_flow.state.dispatch_correction import (
    build_dispatch_correction,
    plan_dispatch_corrections,
)

EVIDENCE_REF = "process/state/AGENT-DISPATCH-LEDGER.ndjson"
REASON = "CR-071 legacy agent_dispatch schema rows lack structure fields"
CREATED_AT = "2026-08-24T00:00:00Z"
PROCESS_OID = "1" * 40

# 复刻 process 仓 539/540 行的 legacy schema：event_type=agent_dispatch，
# 有 event_id/tool_name/status，缺 dispatch_id 与 canonical_role。
LEGACY_SOURCE: dict[str, object] = {
    "schema_version": 1,
    "event_id": "DISPATCH-CR071-CP2-META-PM-REV2-RESUMED-20260815-V1",
    "event_type": "agent_dispatch",
    "role": "meta-pm",
    "codex_agent_name": "meta-pm",
    "status": "running",
    "evidence": "send_input",
    "tool_name": "collaboration.followup_task",
    "resumed_at": "2026-08-15T14:55:00Z",
}

# terminal_result 路径的固定样例（与 tests/test_dispatch_correction.py 同构），
# 其 event_id 是改动前公式的逐字节输出，作为回归锚点不得漂移。
TERMINAL_SOURCE: dict[str, object] = {
    "event_id": "D-1-INTERRUPTED",
    "event_type": "dispatch",
    "dispatch_id": "D-1",
    "attempt_id": "A-1",
    "story_id": "STORY-1",
    "canonical_role": "meta-qa",
    "checkpoint": "CP7",
    "dispatch_mode": "subagent",
    "tool_name": "spawn_agent",
    "status": "interrupted",
    "completed_at": "2026-08-01T00:00:00Z",
}
TERMINAL_PATH_EVENT_ID = "DISPATCH-CORRECTION-5a5714bfd10f5e6edcd07f439d6736f6"
STRUCTURE_PATH_EVENT_ID = "DISPATCH-CORRECTION-a48b1c91a9921eec54deaebe2f0c3251"

STRUCTURE_FIELDS: dict[str, str] = {
    "dispatch_id": "DISPATCH-CR071-CP2-META-PM-REV2",
    "canonical_role": "meta-pm",
}


def _write_ledger(tmp_path: Path, events: list[dict[str, object]]) -> Path:
    path = tmp_path / "process/state/AGENT-DISPATCH-LEDGER.ndjson"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def _legacy_source(event_id: str) -> dict[str, object]:
    return {**LEGACY_SOURCE, "event_id": event_id}


def _structure_correction(
    source: dict[str, object] | None = None,
    fields: dict[str, str] | None = None,
) -> dict[str, object]:
    return build_dispatch_correction(
        LEGACY_SOURCE if source is None else source,
        structure_fields=dict(STRUCTURE_FIELDS) if fields is None else fields,
        reason=REASON,
        evidence_refs=(EVIDENCE_REF,),
        created_at=CREATED_AT,
    )


def test_line_errors_become_covered_warnings_after_structure_correction(
    tmp_path: Path,
) -> None:
    ledger = _write_ledger(tmp_path, [LEGACY_SOURCE])
    errors_before, _warnings = event_ledger.validate_event_ledger(ledger, ledger_type="dispatch")
    # 改动前基线：legacy 行的两个缺失字段均为行级 ERROR。
    assert errors_before == [
        "line 1: missing required field: dispatch_id",
        "line 1: missing required field: canonical_role",
    ]

    correction = _structure_correction()
    ledger = _write_ledger(tmp_path, [correction])

    errors, warnings = event_ledger.validate_event_ledger(ledger, ledger_type="dispatch")
    assert errors == []
    correction_id = str(correction["event_id"])
    # source 行的缺失字段被结构补齐覆盖，从 ERROR 降级为 WARN。
    assert (
        f"line 1: missing dispatch_id is covered by dispatch correction {correction_id}"
        in warnings
    )
    assert (
        f"line 1: missing canonical_role is covered by dispatch correction {correction_id}"
        in warnings
    )
    # correction 行自身镜像 legacy source 的空 dispatch_id/attempt_id，同样降级披露。
    assert (
        f"line 2: missing dispatch_id is covered by dispatch correction {correction_id}"
        in warnings
    )
    assert (
        f"line 2: missing attempt_id is covered by dispatch correction {correction_id}"
        in warnings
    )


def test_deterministic_event_id_and_terminal_path_regression(tmp_path: Path) -> None:
    first = _structure_correction()
    second = build_dispatch_correction(
        LEGACY_SOURCE,
        structure_fields=STRUCTURE_FIELDS,
        reason="different reason must not change identity",
        evidence_refs=(EVIDENCE_REF,),
        created_at="2026-08-25T09:00:00Z",
    )
    assert first["event_id"] == second["event_id"] == STRUCTURE_PATH_EVENT_ID
    assert first["correction_fields"] == {
        "dispatch_id": "DISPATCH-CR071-CP2-META-PM-REV2",
        "canonical_role": "meta-pm",
    }
    # 不同补齐字段集合必须产生不同 event_id。
    subset = _structure_correction(fields={"dispatch_id": "DISPATCH-CR071-CP2-META-PM-REV2"})
    only_role = _structure_correction(fields={"canonical_role": "meta-pm"})
    assert len({first["event_id"], subset["event_id"], only_role["event_id"]}) == 3

    # terminal_result 路径的既有 event_id 计算不得回归（固定样例断言）。
    terminal = build_dispatch_correction(
        TERMINAL_SOURCE,
        terminal_result="INTERRUPTED",
        reason="source status is explicitly interrupted",
        evidence_refs=(EVIDENCE_REF,),
        created_at="2026-08-02T00:00:00Z",
    )
    assert terminal["event_id"] == TERMINAL_PATH_EVENT_ID
    assert terminal["correction_fields"] == {"terminal_result": "INTERRUPTED"}

    # terminal 修正端到端仍被 index 与既有 terminal_result 豁免接受。
    ledger = _write_ledger(tmp_path, [TERMINAL_SOURCE, terminal])
    errors, warnings = event_ledger.validate_event_ledger(ledger, ledger_type="dispatch")
    assert errors == []
    assert any(
        "missing terminal_result is covered by dispatch correction" in item for item in warnings
    )


def test_plan_is_zero_write_ready_and_replay_no_change(tmp_path: Path) -> None:
    _write_ledger(tmp_path, [LEGACY_SOURCE])
    before = (tmp_path / "process/state/AGENT-DISPATCH-LEDGER.ndjson").read_bytes()
    plan = plan_dispatch_corrections(
        tmp_path,
        source_event_ids=(str(LEGACY_SOURCE["event_id"]),),
        structure_fields=STRUCTURE_FIELDS,
        reason=REASON,
        evidence_refs=(EVIDENCE_REF,),
        process_oid=PROCESS_OID,
        created_at=CREATED_AT,
    )
    assert plan.decision == "READY"
    assert plan.mutation_count == 1
    assert plan.corrections[0]["event_id"] == STRUCTURE_PATH_EVENT_ID
    assert (tmp_path / "process/state/AGENT-DISPATCH-LEDGER.ndjson").read_bytes() == before

    # 模拟追加后重放同 plan：既有 correction 幂等归 NO_CHANGE。
    _write_ledger(tmp_path, [plan.corrections[0]])
    replay = plan_dispatch_corrections(
        tmp_path,
        source_event_ids=(str(LEGACY_SOURCE["event_id"]),),
        structure_fields=STRUCTURE_FIELDS,
        reason=REASON,
        evidence_refs=(EVIDENCE_REF,),
        process_oid=PROCESS_OID,
        created_at=CREATED_AT,
    )
    assert replay.decision == "NO_CHANGE"
    # 字段集合漂移（少补 canonical_role）必须 fail closed。
    drifted = plan_dispatch_corrections(
        tmp_path,
        source_event_ids=(str(LEGACY_SOURCE["event_id"]),),
        structure_fields={"dispatch_id": "DISPATCH-CR071-CP2-META-PM-REV2"},
        reason=REASON,
        evidence_refs=(EVIDENCE_REF,),
        process_oid=PROCESS_OID,
        created_at=CREATED_AT,
    )
    assert drifted.decision == "BLOCKED"
    assert any("CORRECTION_CONFLICT" in blocker for blocker in drifted.blockers)


def test_negative_source_already_has_field_fails_closed(tmp_path: Path) -> None:
    source = {
        **_legacy_source("LEGACY-ROW-ALREADY-HAS-CANONICAL-ROLE"),
        "canonical_role": "meta-pm",
    }
    correction = _structure_correction(source=source)
    ledger = _write_ledger(tmp_path, [source, correction])

    errors, _warnings = event_ledger.validate_event_ledger(ledger, ledger_type="dispatch")

    assert (
        "dispatch correction source already has canonical_role: "
        "LEGACY-ROW-ALREADY-HAS-CANONICAL-ROLE" in errors
    )
    # plan 层模拟校验同样给出 blocker，而不是产出 READY plan。
    plan = plan_dispatch_corrections(
        tmp_path,
        source_event_ids=("LEGACY-ROW-ALREADY-HAS-CANONICAL-ROLE",),
        structure_fields=STRUCTURE_FIELDS,
        reason=REASON,
        evidence_refs=(EVIDENCE_REF,),
        process_oid=PROCESS_OID,
        created_at=CREATED_AT,
    )
    assert plan.decision == "BLOCKED"
    assert plan.mutation_count == 0
    assert any(
        "dispatch correction source already has canonical_role" in blocker
        for blocker in plan.blockers
    )


def test_negative_mixed_terminal_and_structure_fields_fail_closed(tmp_path: Path) -> None:
    # 库层：terminal_result 与结构字段互斥。
    with pytest.raises(ValueError, match="DISPATCH_CORRECTION_FIELDS_EXCLUSIVE"):
        build_dispatch_correction(
            LEGACY_SOURCE,
            terminal_result="PASS",
            structure_fields=STRUCTURE_FIELDS,
            reason=REASON,
            evidence_refs=(EVIDENCE_REF,),
            created_at=CREATED_AT,
        )
    # 库层：两条路径都缺时拒绝。
    with pytest.raises(ValueError, match="TERMINAL_RESULT_OR_STRUCTURE_FIELDS_REQUIRED"):
        build_dispatch_correction(
            LEGACY_SOURCE,
            reason=REASON,
            evidence_refs=(EVIDENCE_REF,),
            created_at=CREATED_AT,
        )
    # 行层：correction_fields 混入 terminal_result + 结构键被 terminal 分支拒绝。
    mixed = _structure_correction()
    mixed["event_id"] = "DISPATCH-CORRECTION-MIXED-FIELDS"
    mixed["correction_fields"] = {"terminal_result": "PASS", "dispatch_id": "D-9"}
    ledger = _write_ledger(tmp_path, [LEGACY_SOURCE, mixed])
    errors, _warnings = event_ledger.validate_event_ledger(ledger, ledger_type="dispatch")
    assert f"dispatch correction fields invalid: {LEGACY_SOURCE['event_id']}" in errors


def test_negative_empty_values_and_key_sets_fail_closed(tmp_path: Path) -> None:
    for invalid_fields in ({}, {"dispatch_id": ""}, {"dispatch_id": "   "}, {"bogus": "x"}):
        with pytest.raises(ValueError):
            build_dispatch_correction(
                LEGACY_SOURCE,
                structure_fields=invalid_fields,
                reason=REASON,
                evidence_refs=(EVIDENCE_REF,),
                created_at=CREATED_AT,
            )
    # 行层：空键集走 terminal 分支的 fields invalid；空值走结构分支的值校验。
    # 两个场景使用独立 target，避免 fork 校验先行掩盖具体错误。
    empty_keys_source = _legacy_source("LEGACY-EMPTY-KEYS-TARGET")
    empty_keys = _structure_correction(source=empty_keys_source)
    empty_keys["event_id"] = "DISPATCH-CORRECTION-EMPTY-KEYS"
    empty_keys["correction_fields"] = {}
    empty_value_source = _legacy_source("LEGACY-EMPTY-VALUE-TARGET")
    empty_value = _structure_correction(source=empty_value_source)
    empty_value["correction_fields"] = {"dispatch_id": ""}
    ledger = _write_ledger(
        tmp_path,
        [empty_keys_source, empty_keys, empty_value_source, empty_value],
    )
    errors, _warnings = event_ledger.validate_event_ledger(ledger, ledger_type="dispatch")
    assert "dispatch correction fields invalid: LEGACY-EMPTY-KEYS-TARGET" in errors
    assert "dispatch correction structure field invalid: LEGACY-EMPTY-VALUE-TARGET" in errors


def test_negative_digest_identity_and_evidence_fail_closed(tmp_path: Path) -> None:
    # 每类篡改使用独立 target source，避免 fork 校验先行掩盖具体错误。
    digest_source = _legacy_source("LEGACY-DIGEST-TARGET")
    digest_drift = _structure_correction(source=digest_source)
    digest_drift["original_event_digest"] = "0" * 64
    identity_source = _legacy_source("LEGACY-IDENTITY-TARGET")
    identity_drift = _structure_correction(source=identity_source)
    identity_drift["dispatch_id"] = "WRONG-DISPATCH-ID"
    evidence_source = _legacy_source("LEGACY-EVIDENCE-TARGET")
    evidence_drift = _structure_correction(source=evidence_source)
    evidence_drift["evidence_refs"] = ["docs/NOT-A-PROCESS-REF.md"]
    ledger = _write_ledger(
        tmp_path,
        [digest_source, digest_drift, identity_source, identity_drift, evidence_source, evidence_drift],
    )

    errors, _warnings = event_ledger.validate_event_ledger(ledger, ledger_type="dispatch")

    assert "dispatch correction original_event_digest mismatch: LEGACY-DIGEST-TARGET" in errors
    assert "dispatch correction identity mismatch: LEGACY-IDENTITY-TARGET" in errors
    assert "dispatch correction evidence_refs invalid: LEGACY-EVIDENCE-TARGET" in errors


def test_negative_fork_two_corrections_same_target(tmp_path: Path) -> None:
    first = _structure_correction()
    second = {**first, "event_id": str(first["event_id"]) + "-FORK"}
    ledger = _write_ledger(tmp_path, [LEGACY_SOURCE, first, second])

    errors, _warnings = event_ledger.validate_event_ledger(ledger, ledger_type="dispatch")

    # fork：同一 corrects_event_id 只允许一个 correction，对两分支统一生效。
    assert f"dispatch correction fork: {LEGACY_SOURCE['event_id']}" in errors


def test_cli_correction_plan_ready_and_ledgers_report_zero_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_ledger(tmp_path, [LEGACY_SOURCE])
    monkeypatch.setattr(dispatch_correction, "_process_oid", lambda root: PROCESS_OID)

    rc = event_ledger.main(
        [
            "correction-plan",
            "--project-root", str(tmp_path),
            "--source-event-id", str(LEGACY_SOURCE["event_id"]),
            "--dispatch-id-to-set", "DISPATCH-CR071-CP2-META-PM-REV2",
            "--canonical-role-to-set", "meta-pm",
            "--reason", REASON,
            "--evidence-ref", EVIDENCE_REF,
            "--created-at", CREATED_AT,
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["decision"] == "READY"
    assert payload["mutation_count"] == 1
    assert payload["corrections"][0]["event_id"] == STRUCTURE_PATH_EVENT_ID

    # 模拟追加 correction（apply 是受授权动作，测试只做同构 append）。
    _write_ledger(tmp_path, [payload["corrections"][0]])

    rc = event_ledger.main(["dispatch-check", "--project-root", str(tmp_path)])
    output = capsys.readouterr().out
    assert rc == 0
    assert "Dispatch Evidence Check: OK" in output
    assert "- ERROR" not in output
    assert "missing canonical_role is covered by dispatch correction" in output

    rc = event_ledger.main(
        [
            "check",
            "--project-root", str(tmp_path),
            "--ledger", "process/state/AGENT-DISPATCH-LEDGER.ndjson",
            "--type", "dispatch",
        ]
    )
    output = capsys.readouterr().out
    assert rc == 0
    assert "Event Ledger Check: OK" in output
    assert "- ERROR" not in output

    # CLI 互斥：结构字段与 terminal_result 同时给出必须 BLOCKED。
    rc = event_ledger.main(
        [
            "correction-plan",
            "--project-root", str(tmp_path),
            "--source-event-id", str(LEGACY_SOURCE["event_id"]),
            "--terminal-result", "PASS",
            "--dispatch-id-to-set", "DISPATCH-CR071-CP2-META-PM-REV2",
            "--reason", REASON,
            "--evidence-ref", EVIDENCE_REF,
            "--created-at", CREATED_AT,
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["decision"] == "BLOCKED"
    assert "DISPATCH_CORRECTION_FIELDS_EXCLUSIVE" in payload["blockers"]
