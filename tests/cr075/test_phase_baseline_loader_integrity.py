"""CR-075 phase baseline loader 完整性（V4 整改项 2 + V5 整改阻断三）。

CP7 门禁反馈 fail-open 修复后的完整性回归：
- 损坏 JSON 不得被静默当作「无基线」rebaseline（plan 不得产出新建 READY）
- entries 元素被篡改为非 dict 不得暴露 AttributeError traceback
- history 合法 dict 形态被改字段值/删字段后不得被 carry/append 静默接受

V5 整改阻断三新增（CP7 门禁 DQ-075-C7-V4-01 退回）：
- 反例 A：错误 kind/phase_id 绑定/scope_digest/缺维 fingerprint 的基线
  不得被 loader 接受，更不得产出 NEW_REGRESSION 归属
- 反例 B：baseline 位置的 symlink / 目录占用必须是第四态 occupied
  （typed BLOCKED BASELINE_TARGET_OCCUPIED），不是 missing、不产 READY
- 反例 C：plan 输入收紧（entry digest hex / fingerprint 六维）+ writer
  自洽终检——READY 冻结 bytes 落盘后必须通过同一 typed loader

全部负向路径必须返回 typed BLOCKED dict，不抛异常——用 pytest.raises
反而失败。
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import pytest

from meta_flow.execution_control.contract import canonical_digest
from meta_flow.execution_control.exact_file_transaction import (
    ExactFileAuthorizationV1,
)
from meta_flow.validation.baseline import (
    SCHEMA_VERSION,
    _scope_digest_for,
    apply_baseline,
    apply_invalidation,
    baseline_ref,
    check_baseline,
    inspect_baseline,
    load_baseline_state,
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
    """构造 process_root + phase 目录（plan 入口要求 PHASE.yaml 存在）。"""

    phase_dir = process / "phases" / "P7-BASELINE"
    phase_dir.mkdir(parents=True, exist_ok=True)
    (phase_dir / "PHASE.yaml").write_text(
        "schema_version: 1\nphase_id: P7-BASELINE\n", encoding="utf-8"
    )
    return "phases/P7-BASELINE/PHASE.yaml"


def _baseline_path(process: Path, phase_ref: str) -> Path:
    return process / baseline_ref(phase_ref)


def _history_item(**overrides: object) -> dict[str, object]:
    """构造带 entry_digest 的合法 history item（与 append 快照同构）。

    overrides 先应用再计算 entry_digest，因此构造出的项 digest 自洽，
    失败原因可精确隔离为字段形态本身。
    """

    item: dict[str, object] = {
        "version": 1,
        "scope_digest": "a" * 64,
        "created_at": "2026-08-24T00:00:00Z",
        "invalidated_at": "2026-08-24T01:00:00Z",
        "invalidation_reasons": ["SOURCE_FINGERPRINT_DRIFT"],
    }
    item.update(overrides)
    item.pop("entry_digest", None)
    item["entry_digest"] = canonical_digest(item)
    return item


def _valid_payload(**overrides: object) -> dict[str, object]:
    """手工构造可通过 typed loader 的合法基线（含合规 entries）。

    V5 整改后 phase_id 必须与 phase_ref 严格相等（_phase() 返回的全路径）；
    V6 整改后 scope_digest 按 phase_id+entries 重算严格绑定——构造时统一
    经 _scope_digest_for 重算（除非 override 显式提供错误的 scope_digest
    以测绑定检测本身）。
    """

    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "kind": "PhaseGreenBaselineV1",
        "phase_id": "phases/P7-BASELINE/PHASE.yaml",
        "version": 1,
        "scope_digest": "a" * 64,
        "fingerprint": dict(_FINGERPRINT),
        "entries": [dict(entry) for entry in _ENTRIES],
        "created_at": "",
        "invalidated_at": "",
        "invalidation_reasons": [],
        "history": [],
    }
    payload.update(overrides)
    # 仅当 entries 全为 dict 时重算（非 dict 元素的负向用例重算会抛异常，
    # 且其断言本就在 entries 形态处失败，静态值即可）。
    if "scope_digest" not in overrides and all(
        isinstance(entry, dict) for entry in payload["entries"]
    ):
        payload["scope_digest"] = _scope_digest_for(
            str(payload["phase_id"]), list(payload["entries"])
        )
    return payload


def _write(process: Path, phase_ref: str, content: object) -> None:
    path = _baseline_path(process, phase_ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(
            json.dumps(content, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _assert_malformed(result: dict) -> None:
    """负向统一断言：typed BLOCKED（调用成功返回即证明未抛异常）。"""

    assert result["decision"] == "BLOCKED"
    assert result["reason_codes"] == ["BASELINE_FILE_MALFORMED"]
    assert result["mutation_count"] == 0


def _assert_three_entrypoints_blocked(process: Path, phase_ref: str) -> None:
    """plan / check / invalidate 三入口全部 typed BLOCKED，plan 不产出 READY。"""

    plan = plan_baseline(
        process, phase_ref=phase_ref, entries=_ENTRIES, fingerprint=dict(_FINGERPRINT)
    )
    _assert_malformed(plan)
    assert plan.get("decision") != "READY"
    _assert_malformed(
        check_baseline(
            process,
            phase_ref=phase_ref,
            current_fingerprint=dict(_FINGERPRINT),
            failing_checks=[],
        )
    )
    _assert_malformed(
        plan_invalidation(
            process,
            phase_ref=phase_ref,
            reasons=["SOURCE_FINGERPRINT_DRIFT"],
            at="2026-08-25T00:00:00Z",
        )
    )


# ---- 负向：损坏 JSON / 顶层形态（规格 1、2）----


def test_truncated_json_blocks_all_entrypoints(tmp_path: Path) -> None:
    """截断 JSON：损坏基线不得被静默当作无基线 rebaseline。"""

    process = tmp_path
    phase_ref = _phase(process)
    _write(process, phase_ref, b'{"schema_version": 1, "entries": [')
    assert load_baseline_state(process, phase_ref) == ("malformed", None)
    _assert_three_entrypoints_blocked(process, phase_ref)


def test_invalid_bytes_blocks_all_entrypoints(tmp_path: Path) -> None:
    """非法字节（utf-8 解码失败）：三入口 typed BLOCKED。"""

    process = tmp_path
    phase_ref = _phase(process)
    _write(process, phase_ref, b"\xff\xfe\x00not-json")
    assert load_baseline_state(process, phase_ref) == ("malformed", None)
    _assert_three_entrypoints_blocked(process, phase_ref)


def test_top_level_list_blocks_all_entrypoints(tmp_path: Path) -> None:
    """顶层是 list：三入口 typed BLOCKED。"""

    process = tmp_path
    phase_ref = _phase(process)
    _write(process, phase_ref, [1, 2, 3])
    assert load_baseline_state(process, phase_ref) == ("malformed", None)
    _assert_three_entrypoints_blocked(process, phase_ref)


# ---- 负向：entries / version schema 违规（规格 3、4、5）----


@pytest.mark.parametrize(
    "bad_entries",
    [[["nested-list"]], ["plain-str"], [3], [None]],
)
def test_entries_non_dict_element_is_typed_blocked(
    tmp_path: Path, bad_entries: list
) -> None:
    """entries 元素为 list/str/int/None：返回 BLOCKED dict，重点不抛 AttributeError。"""

    process = tmp_path
    phase_ref = _phase(process)
    _write(process, phase_ref, _valid_payload(entries=bad_entries))
    _assert_malformed(
        check_baseline(
            process,
            phase_ref=phase_ref,
            current_fingerprint=dict(_FINGERPRINT),
            failing_checks=["CHECK-A"],
        )
    )
    _assert_three_entrypoints_blocked(process, phase_ref)


@pytest.mark.parametrize(
    "bad_entries",
    [
        [{"check_id": "", "result_digest": "1" * 64}],
        [{"check_id": "CHECK-A"}],
        [{"check_id": "CHECK-A", "result_digest": ""}],
        [{"result_digest": "1" * 64}],
    ],
)
def test_entries_missing_or_empty_fields_blocked(
    tmp_path: Path, bad_entries: list
) -> None:
    """entries 元素缺 check_id / 缺 result_digest / 空串：BLOCKED。"""

    process = tmp_path
    phase_ref = _phase(process)
    _write(process, phase_ref, _valid_payload(entries=bad_entries))
    _assert_three_entrypoints_blocked(process, phase_ref)


@pytest.mark.parametrize("bad_version", ["1", 0, -1, 1.5, True])
def test_invalid_version_is_typed_blocked(tmp_path: Path, bad_version: object) -> None:
    """version 为 str / 0 / 负数 / float / bool：BLOCKED（bool 防御 True==1）。"""

    process = tmp_path
    phase_ref = _phase(process)
    _write(process, phase_ref, _valid_payload(version=bad_version))
    _assert_three_entrypoints_blocked(process, phase_ref)


def test_other_schema_violations_are_typed_blocked(tmp_path: Path) -> None:
    """schema_version 不匹配 / fingerprint 形态违规：BLOCKED（typed loader 校验面）。"""

    process = tmp_path
    phase_ref = _phase(process)
    _write(process, phase_ref, _valid_payload(schema_version=SCHEMA_VERSION + 1))
    _assert_malformed(
        check_baseline(
            process,
            phase_ref=phase_ref,
            current_fingerprint=dict(_FINGERPRINT),
            failing_checks=[],
        )
    )
    _write(process, phase_ref, _valid_payload(fingerprint=["not-a-dict"]))
    _assert_malformed(
        check_baseline(
            process,
            phase_ref=phase_ref,
            current_fingerprint=dict(_FINGERPRINT),
            failing_checks=[],
        )
    )
    _write(process, phase_ref, _valid_payload(fingerprint={"environment": 3}))
    _assert_malformed(
        check_baseline(
            process,
            phase_ref=phase_ref,
            current_fingerprint=dict(_FINGERPRINT),
            failing_checks=[],
        )
    )


# ---- 负向：history item schema 与篡改检测（规格 6、7、8）----


def test_history_item_schema_violations_blocked(tmp_path: Path) -> None:
    """history item 缺 invalidated_at / version 为 str / scope_digest 非 64-hex。

    每个变体先让 entry_digest 自洽（重算），失败原因隔离为字段形态本身。
    """

    process = tmp_path
    phase_ref = _phase(process)
    missing_invalidated_at = _history_item()
    del missing_invalidated_at["invalidated_at"]
    missing_invalidated_at["entry_digest"] = canonical_digest(missing_invalidated_at)
    for bad_item in (
        missing_invalidated_at,
        _history_item(version="1"),
        _history_item(scope_digest="not-hex"),
    ):
        _write(process, phase_ref, _valid_payload(history=[bad_item]))
        _assert_three_entrypoints_blocked(process, phase_ref)


def test_tampered_history_item_digest_mismatch_blocked(tmp_path: Path) -> None:
    """改 version 值后 entry_digest 未重算：篡改检测拦截，BLOCKED。"""

    process = tmp_path
    phase_ref = _phase(process)
    tampered = dict(_history_item())
    tampered["version"] = 99
    _write(process, phase_ref, _valid_payload(history=[tampered]))
    assert load_baseline_state(process, phase_ref) == ("malformed", None)
    _assert_three_entrypoints_blocked(process, phase_ref)


def test_history_item_without_entry_digest_blocked(tmp_path: Path) -> None:
    """不含 entry_digest 的历史项一律不接受（fail-closed）：BLOCKED。"""

    process = tmp_path
    phase_ref = _phase(process)
    legacy_item = {
        key: value for key, value in _history_item().items() if key != "entry_digest"
    }
    _write(process, phase_ref, _valid_payload(history=[legacy_item]))
    assert load_baseline_state(process, phase_ref) == ("malformed", None)
    _assert_three_entrypoints_blocked(process, phase_ref)


# ---- 正路径回归：missing 与合法基线行为不变（规格 9）----


def test_missing_baseline_still_plans_v1_ready(tmp_path: Path) -> None:
    """missing：plan 决策 READY、冻结 version=1；check 保持 BASELINE_MISSING。"""

    process = tmp_path
    phase_ref = _phase(process)
    assert load_baseline_state(process, phase_ref) == ("missing", None)
    plan = plan_baseline(
        process, phase_ref=phase_ref, entries=_ENTRIES, fingerprint=dict(_FINGERPRINT)
    )
    assert plan["decision"] == "READY"
    frozen = json.loads(
        base64.b64decode(plan["exact_plan"]["targets"][0]["after_bytes_b64"])
    )
    assert frozen["version"] == 1
    assert frozen["history"] == []
    missing_check = check_baseline(
        process, phase_ref=phase_ref, current_fingerprint={}, failing_checks=[]
    )
    assert missing_check["reason_codes"] == ["BASELINE_MISSING"]


def test_valid_active_baseline_behaves_as_before(tmp_path: Path) -> None:
    """合法 created 基线：ALREADY_ACTIVE 拦截 / PASS / 归属矩阵不变。"""

    process = tmp_path
    phase_ref = _phase(process)
    _write(process, phase_ref, _valid_payload())
    assert load_baseline_state(process, phase_ref)[0] == "ok"

    again = plan_baseline(
        process, phase_ref=phase_ref, entries=_ENTRIES, fingerprint=dict(_FINGERPRINT)
    )
    assert again["decision"] == "BLOCKED"
    assert again["reason_codes"] == ["BASELINE_ALREADY_ACTIVE"]

    clean = check_baseline(
        process,
        phase_ref=phase_ref,
        current_fingerprint=dict(_FINGERPRINT),
        failing_checks=[],
    )
    assert clean["decision"] == "PASS"
    assert clean["attribution"] == {}

    regression = check_baseline(
        process,
        phase_ref=phase_ref,
        current_fingerprint=dict(_FINGERPRINT),
        failing_checks=["CHECK-A"],
    )
    assert regression["attribution"]["NEW_REGRESSION"] == ["CHECK-A"]

    drifted = check_baseline(
        process,
        phase_ref=phase_ref,
        current_fingerprint=dict(_FINGERPRINT, source_fingerprint="a" * 64),
        failing_checks=["CHECK-A"],
    )
    assert drifted["attribution"]["EXISTING_SOURCE_DRIFT"] == ["CHECK-A"]


def test_valid_invalidated_baseline_behaves_as_before(tmp_path: Path) -> None:
    """合法 invalidated 基线：check 转 NEEDS_REVIEW，rebaseline 放行 version+1。"""

    process = tmp_path
    phase_ref = _phase(process)
    payload = _valid_payload(
        version=2,
        invalidated_at="2026-08-24T01:00:00Z",
        invalidation_reasons=["SOURCE_FINGERPRINT_DRIFT"],
        history=[_history_item()],
    )
    _write(process, phase_ref, payload)
    assert load_baseline_state(process, phase_ref)[0] == "ok"

    check = check_baseline(
        process,
        phase_ref=phase_ref,
        current_fingerprint=dict(_FINGERPRINT),
        failing_checks=[],
    )
    assert check["decision"] == "NEEDS_REVIEW"
    assert check["reason_codes"] == ["BASELINE_INVALIDATED"]

    rebaseline = plan_baseline(
        process, phase_ref=phase_ref, entries=_ENTRIES, fingerprint=dict(_FINGERPRINT)
    )
    assert rebaseline["decision"] == "READY"
    frozen = json.loads(
        base64.b64decode(rebaseline["exact_plan"]["targets"][0]["after_bytes_b64"])
    )
    assert frozen["version"] == 3
    # carried history 前缀原样保留（含 entry_digest，未被改写）。
    assert frozen["history"] == payload["history"]


def test_invalidation_snapshot_carries_entry_digest_and_reloads_ok(
    tmp_path: Path,
) -> None:
    """端到端：invalidation append 的快照含 entry_digest，落盘后可再过 loader。"""

    process = tmp_path
    phase_ref = _phase(process)
    # exact-file shared writer lock 的锚文件（fixture-only）。
    if not (process / ".meta-flow-process.yaml").is_file():
        (process / ".meta-flow-process.yaml").write_text(
            "schema_version: 1\nproject_id: fixture\n", encoding="utf-8"
        )
    _write(process, phase_ref, _valid_payload())

    plan = plan_invalidation(
        process,
        phase_ref=phase_ref,
        reasons=["SOURCE_FINGERPRINT_DRIFT"],
        at="2026-08-25T00:00:00Z",
    )
    assert plan["decision"] == "READY"
    authorization = ExactFileAuthorizationV1(
        "AUTH-CR075-V4-LOADER-20260825-001",
        "phase-baseline.invalidate",
        plan["exact_plan_digest"],
        tuple(item["ref"] for item in plan["exact_plan"]["targets"]),
        "2999-01-01T00:00:00Z",
    )
    assert apply_invalidation(process, plan_payload=plan, authorization=authorization)[
        "decision"
    ] == "PASS"

    on_disk = json.loads(_baseline_path(process, phase_ref).read_text(encoding="utf-8"))
    snapshot = on_disk["history"][-1]
    assert snapshot["entry_digest"] == canonical_digest(
        {key: value for key, value in snapshot.items() if key != "entry_digest"}
    )
    # 落盘文件可再次通过 typed loader（新写入自带篡改检测且自洽）。
    assert load_baseline_state(process, phase_ref) == ("ok", on_disk)
    # 幂等回归：已失效基线再次 plan 失效 -> NO_CHANGE。
    second = plan_invalidation(
        process,
        phase_ref=phase_ref,
        reasons=["SOURCE_FINGERPRINT_DRIFT"],
        at="2026-08-25T01:00:00Z",
    )
    assert second["decision"] == "NO_CHANGE"
    assert second["idempotent"] is True


# ---- V5 整改阻断三：身份绑定与完备性（反例 A）----


@pytest.mark.parametrize(
    "overrides",
    [
        {"kind": "WorkBootstrapBaselineV1"},
        {"phase_id": "P7-BASELINE"},
        {"phase_id": "phases/OTHER-PHASE/PHASE.yaml"},
        {"phase_id": ""},
        {"scope_digest": "not-hex"},
        {"scope_digest": ""},
        {"fingerprint": {k: v for k, v in _FINGERPRINT.items() if k != "profile_digest"}},
        {"fingerprint": dict(_FINGERPRINT, environment="")},
        {"entries": [{"check_id": "CHECK-A", "result_digest": "not-hex"}]},
        {"entries": [{"check_id": "CHECK-A", "result_digest": ""}]},
        {"invalidated_at": "2026-08-24T01:00:00Z"},
        {"invalidation_reasons": ["SOURCE_FINGERPRINT_DRIFT"]},
    ],
)
def test_identity_or_completeness_violation_is_malformed(
    tmp_path: Path, overrides: dict
) -> None:
    """反例 A：错误 kind / phase_id 绑定 / scope_digest、缺维或空值
    fingerprint、非 hex entry digest、失效状态不一致——全部判 malformed，
    不得被当合法基线接受，更不得产出 NEW_REGRESSION 归属。"""

    process = tmp_path
    phase_ref = _phase(process)
    _write(process, phase_ref, _valid_payload(**overrides))
    assert load_baseline_state(process, phase_ref) == ("malformed", None)
    blocked = check_baseline(
        process,
        phase_ref=phase_ref,
        current_fingerprint=dict(_FINGERPRINT),
        failing_checks=["CHECK-A"],
    )
    _assert_malformed(blocked)
    # fail-open 核心症状断言：不得出现任何归属结论。
    assert "attribution" not in blocked or "NEW_REGRESSION" not in blocked["attribution"]


# ---- V5 整改阻断三：occupied 第四态（反例 B）----


def _assert_four_entrypoints_occupied(process: Path, phase_ref: str) -> None:
    """plan / check / invalidate / inspect 四入口全部 occupied typed BLOCKED。"""

    plan = plan_baseline(
        process, phase_ref=phase_ref, entries=_ENTRIES, fingerprint=dict(_FINGERPRINT)
    )
    assert plan["decision"] == "BLOCKED"
    assert plan["reason_codes"] == ["BASELINE_TARGET_OCCUPIED"]
    assert "exact_plan" not in plan
    for result in (
        check_baseline(
            process,
            phase_ref=phase_ref,
            current_fingerprint=dict(_FINGERPRINT),
            failing_checks=[],
        ),
        plan_invalidation(
            process,
            phase_ref=phase_ref,
            reasons=["SOURCE_FINGERPRINT_DRIFT"],
            at="2026-08-25T00:00:00Z",
        ),
        inspect_baseline(process, phase_ref=phase_ref),
    ):
        assert result["decision"] == "BLOCKED"
        assert result["reason_codes"] == ["BASELINE_TARGET_OCCUPIED"]
        assert result["mutation_count"] == 0


def test_baseline_symlink_is_occupied_not_missing(tmp_path: Path) -> None:
    """反例 B：baseline 位置是 symlink 时必须是 occupied——不是 missing，
    plan 不得产出新建 READY（原实现随后 read_bytes 会跟随 symlink）。"""

    process = tmp_path
    phase_ref = _phase(process)
    real = tmp_path / "real-baseline.json"
    real.write_text(
        json.dumps(_valid_payload(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    baseline = _baseline_path(process, phase_ref)
    baseline.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(real, baseline)
    assert load_baseline_state(process, phase_ref) == ("occupied", None)
    _assert_four_entrypoints_occupied(process, phase_ref)
    # symlink 本体未被写入或替换（fail-closed 不触碰占用目标）。
    assert baseline.is_symlink()


def test_baseline_directory_occupancy_is_occupied(tmp_path: Path) -> None:
    """目录占用 baseline 位置：occupied typed BLOCKED（非 regular file）。"""

    process = tmp_path
    phase_ref = _phase(process)
    _baseline_path(process, phase_ref).mkdir(parents=True)
    assert load_baseline_state(process, phase_ref) == ("occupied", None)
    _assert_four_entrypoints_occupied(process, phase_ref)


# ---- V5 整改阻断三：writer 输入收紧与自洽终检（反例 C）----


@pytest.mark.parametrize(
    "bad_entries",
    [
        [{"check_id": "CHECK-A", "result_digest": ""}],
        [{"check_id": "CHECK-A", "result_digest": "not-hex"}],
        [{"check_id": "CHECK-A"}],
        [{"check_id": "CHECK-A", "result_digest": None}],
    ],
)
def test_plan_rejects_non_hex_entry_digest(tmp_path: Path, bad_entries: list) -> None:
    """plan 输入收紧：非 64hex result_digest 不得产出 READY（旧实现会写出
    result_digest:"" 的 payload，落盘即被自家 loader 判 malformed）。"""

    process = tmp_path
    phase_ref = _phase(process)
    plan = plan_baseline(
        process, phase_ref=phase_ref, entries=bad_entries, fingerprint=dict(_FINGERPRINT)
    )
    assert plan["decision"] == "BLOCKED"
    assert plan["reason_codes"] == ["BASELINE_ENTRY_DIGEST_INVALID"]
    assert "exact_plan" not in plan


@pytest.mark.parametrize(
    "bad_fingerprint",
    [
        {k: v for k, v in _FINGERPRINT.items() if k != "profile_digest"},
        dict(_FINGERPRINT, environment=""),
        dict(_FINGERPRINT, provider_identity_digest=None),
        {},
    ],
)
def test_plan_rejects_incomplete_fingerprint(tmp_path: Path, bad_fingerprint: dict) -> None:
    """plan 输入收紧：六维 fingerprint 缺键/空值/None 不得产出 READY——
    缺维基线会让 check_baseline 归属矩阵静默降级为 NEW_REGRESSION。"""

    process = tmp_path
    phase_ref = _phase(process)
    plan = plan_baseline(
        process, phase_ref=phase_ref, entries=_ENTRIES, fingerprint=bad_fingerprint
    )
    assert plan["decision"] == "BLOCKED"
    assert plan["reason_codes"] == ["BASELINE_FINGERPRINT_INCOMPLETE"]
    assert "exact_plan" not in plan


def test_plan_ready_payload_passes_same_typed_loader(tmp_path: Path) -> None:
    """反例 C 自洽（正路径）：READY 冻结 bytes 落盘后必须立即通过同一
    typed loader——writer 永不产出 reader 自拒的 payload。"""

    process = tmp_path
    phase_ref = _phase(process)
    plan = plan_baseline(
        process, phase_ref=phase_ref, entries=_ENTRIES, fingerprint=dict(_FINGERPRINT)
    )
    assert plan["decision"] == "READY"
    after_bytes = base64.b64decode(plan["exact_plan"]["targets"][0]["after_bytes_b64"])
    baseline = _baseline_path(process, phase_ref)
    baseline.parent.mkdir(parents=True, exist_ok=True)
    baseline.write_bytes(after_bytes)
    state, payload = load_baseline_state(process, phase_ref)
    assert state == "ok"
    assert payload == json.loads(after_bytes)
    # 冻结 payload 的身份与完备性由 loader 语义保证（而非仅 JSON 合法）。
    assert payload["phase_id"] == phase_ref
    assert payload["kind"] == "PhaseGreenBaselineV1"
    assert set(_FINGERPRINT) <= set(payload["fingerprint"])


def test_invalidation_state_inconsistency_is_blocked(tmp_path: Path) -> None:
    """失效修订自洽终检：at 非空而 reasons 为空（invalidated_at 非空 ⇔
    reasons 非空被破坏）不得写出 reader 自拒 payload。"""

    process = tmp_path
    phase_ref = _phase(process)
    _write(process, phase_ref, _valid_payload())
    result = plan_invalidation(process, phase_ref=phase_ref, reasons=[], at="2026-08-25T00:00:00Z")
    assert result["decision"] == "BLOCKED"
    assert result["reason_codes"] == ["BASELINE_PLAN_PAYLOAD_INVALID"]
    assert result["mutation_count"] == 0


# ---- V5 整改阻断三：inspect 入口负向 ----


def test_inspect_entrypoints_typed_blocked(tmp_path: Path) -> None:
    """inspect 审计视图：malformed / occupied / missing 三态各自 typed
    BLOCKED，不得误导为可消费基线。"""

    process = tmp_path
    phase_ref = _phase(process)
    _write(process, phase_ref, b'{"schema_version": 1, "entries": [')
    malformed = inspect_baseline(process, phase_ref=phase_ref)
    assert malformed["decision"] == "BLOCKED"
    assert malformed["reason_codes"] == ["BASELINE_FILE_MALFORMED"]

    _baseline_path(process, phase_ref).unlink()
    missing = inspect_baseline(process, phase_ref=phase_ref)
    assert missing["decision"] == "BLOCKED"
    assert missing["reason_codes"] == ["BASELINE_MISSING"]

    _baseline_path(process, phase_ref).mkdir()
    occupied = inspect_baseline(process, phase_ref=phase_ref)
    assert occupied["decision"] == "BLOCKED"
    assert occupied["reason_codes"] == ["BASELINE_TARGET_OCCUPIED"]


# ---------------------------------------------------------------------------
# V6 整改负向（DQ-075-C7-V5-01 第 1/2 项）：路径组件 / scope 绑定 /
# entries 完备性 / current_fingerprint 六维 / plan target / 读取 OSError。
# ---------------------------------------------------------------------------


def _assert_four_entrypoints_occupied_ancestor(process: Path, phase_ref: str) -> None:
    """祖先 symlink 场景四入口统一断言（与最终组件 occupied 同 reason）。"""

    assert plan_baseline(
        process, phase_ref=phase_ref, entries=_ENTRIES, fingerprint=dict(_FINGERPRINT)
    )["reason_codes"] == ["BASELINE_TARGET_OCCUPIED"]
    assert check_baseline(
        process,
        phase_ref=phase_ref,
        current_fingerprint=dict(_FINGERPRINT),
        failing_checks=["CHECK-A"],
    )["reason_codes"] == ["BASELINE_TARGET_OCCUPIED"]
    assert plan_invalidation(
        process, phase_ref=phase_ref, reasons=["SOURCE_FINGERPRINT_DRIFT"], at="2026-08-25T00:00:00Z"
    )["reason_codes"] == ["BASELINE_TARGET_OCCUPIED"]
    assert inspect_baseline(process, phase_ref=phase_ref)["reason_codes"] == [
        "BASELINE_TARGET_OCCUPIED"
    ]


def test_ancestor_dir_symlink_is_occupied_not_missing(tmp_path: Path) -> None:
    """反例 D（V6 第 1 项）：phases 目录为 symlink 指向 process_root 外的
    目录（其中甚至放好合法 payload）——四入口必须 occupied，绝不跟随
    symlink 越界读取外部内容当作自家基线。"""

    process = tmp_path
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    phase_dir = outside / "phases" / "P7-BASELINE"
    phase_dir.mkdir(parents=True)
    (phase_dir / "PHASE.yaml").write_text(
        "schema_version: 1\nphase_id: P7-BASELINE\n", encoding="utf-8"
    )
    _write(outside, "phases/P7-BASELINE/PHASE.yaml", _valid_payload())
    (process / "phases").symlink_to(outside / "phases", target_is_directory=True)
    phase_ref = "phases/P7-BASELINE/PHASE.yaml"
    assert load_baseline_state(process, phase_ref) == ("occupied", None)
    _assert_four_entrypoints_occupied_ancestor(process, phase_ref)


def test_ancestor_midlevel_symlink_is_occupied(tmp_path: Path) -> None:
    """反例 D 变体：中间层（phases/P7-BASELINE）为 symlink——loader 三入口
    （check/invalidate/inspect）occupied；plan 的 phase 文件检查更早一层
    拦截（phase 路径被 symlink 占用报 PHASE_FILE_MISSING，同为 typed
    BLOCKED 且未发生任何越界读取）。"""

    process = tmp_path
    outside = tmp_path.parent / f"{tmp_path.name}-mid"
    (outside / "P7-BASELINE").mkdir(parents=True)
    (process / "phases").mkdir()
    (process / "phases" / "P7-BASELINE").symlink_to(
        outside / "P7-BASELINE", target_is_directory=True
    )
    phase_ref = "phases/P7-BASELINE/PHASE.yaml"
    assert load_baseline_state(process, phase_ref) == ("occupied", None)
    assert check_baseline(
        process,
        phase_ref=phase_ref,
        current_fingerprint=dict(_FINGERPRINT),
        failing_checks=["CHECK-A"],
    )["reason_codes"] == ["BASELINE_TARGET_OCCUPIED"]
    assert plan_invalidation(
        process, phase_ref=phase_ref, reasons=["SOURCE_FINGERPRINT_DRIFT"], at="2026-08-25T00:00:00Z"
    )["reason_codes"] == ["BASELINE_TARGET_OCCUPIED"]
    assert inspect_baseline(process, phase_ref=phase_ref)["reason_codes"] == [
        "BASELINE_TARGET_OCCUPIED"
    ]
    plan = plan_baseline(
        process, phase_ref=phase_ref, entries=_ENTRIES, fingerprint=dict(_FINGERPRINT)
    )
    assert plan["decision"] == "BLOCKED"
    assert plan["reason_codes"] == ["PHASE_FILE_MISSING"]


def test_escape_ref_component_is_occupied(tmp_path: Path) -> None:
    """反例 D 变体：phase_ref 含 ``..`` 越界段——loader 层即 occupied，
    不触碰 process_root 外任何路径。"""

    process = tmp_path
    evil_ref = "phases/../../etc/BASELINE.json"
    assert load_baseline_state(process, evil_ref) == ("occupied", None)


def test_scope_digest_tampered_entry_is_malformed(tmp_path: Path) -> None:
    """scope 绑定（V6 第 2 项）：改 entry result_digest 而不重算
    scope_digest ——malformed。"""

    process = tmp_path
    phase_ref = _phase(process)
    payload = _valid_payload()
    payload["entries"][0]["result_digest"] = "9" * 64
    _write(process, phase_ref, payload)
    assert load_baseline_state(process, phase_ref) == ("malformed", None)


def test_scope_digest_reordered_entries_is_malformed(tmp_path: Path) -> None:
    """scope 绑定：重排 entries 顺序（digest 绑定内容与顺序）——malformed。"""

    process = tmp_path
    phase_ref = _phase(process)
    payload = _valid_payload()
    payload["entries"] = list(reversed(payload["entries"]))
    _write(process, phase_ref, payload)
    assert load_baseline_state(process, phase_ref) == ("malformed", None)


def test_scope_digest_changed_check_id_is_malformed(tmp_path: Path) -> None:
    """scope 绑定：改 check_id（保持 digest 形态合法）——malformed。"""

    process = tmp_path
    phase_ref = _phase(process)
    payload = _valid_payload()
    payload["entries"][0]["check_id"] = "CHECK-A2"
    _write(process, phase_ref, payload)
    assert load_baseline_state(process, phase_ref) == ("malformed", None)


def test_empty_entries_payload_is_malformed(tmp_path: Path) -> None:
    """entries 完备性（V6 第 2 项）：空绿集没有基线语义——malformed。"""

    process = tmp_path
    phase_ref = _phase(process)
    _write(process, phase_ref, _valid_payload(entries=[]))
    assert load_baseline_state(process, phase_ref) == ("malformed", None)


def test_duplicate_check_id_entries_is_malformed(tmp_path: Path) -> None:
    """entries 完备性：重复 check_id ——malformed（scope 绑定无法区分
    重复项，绿集语义破损）。"""

    process = tmp_path
    phase_ref = _phase(process)
    duplicated = [
        {"check_id": "CHECK-A", "result_digest": "1" * 64},
        {"check_id": "CHECK-A", "result_digest": "2" * 64},
    ]
    payload = _valid_payload(entries=duplicated)
    payload["scope_digest"] = _scope_digest_for(payload["phase_id"], duplicated)
    _write(process, phase_ref, payload)
    assert load_baseline_state(process, phase_ref) == ("malformed", None)


def test_current_fingerprint_missing_dimension_is_blocked(tmp_path: Path) -> None:
    """current_fingerprint 六维（V6 第 2 项）：调用侧缺维不得进入归属
    矩阵——CURRENT_FINGERPRINT_INCOMPLETE 且无 attribution 输出。"""

    process = tmp_path
    phase_ref = _phase(process)
    _write(process, phase_ref, _valid_payload())
    partial = {k: v for k, v in _FINGERPRINT.items() if k != "profile_digest"}
    result = check_baseline(
        process, phase_ref=phase_ref, current_fingerprint=partial, failing_checks=["CHECK-A"]
    )
    assert result["decision"] == "BLOCKED"
    assert result["reason_codes"] == ["CURRENT_FINGERPRINT_INCOMPLETE"]
    assert "attribution" not in result


def test_apply_plan_target_not_mapping_is_blocked(tmp_path: Path) -> None:
    """plan target 完备性（V6 第 2 项）：targets 含非 mapping 元素——
    PLAN_TARGET_INVALID，不抛 TypeError/AttributeError。"""

    process = tmp_path
    plan_payload = {"exact_plan": {"targets": [["not-a-mapping"]]}, "exact_plan_digest": "x"}
    result = apply_baseline(
        process, plan_payload=plan_payload, authorization=None
    )
    assert result["decision"] == "BLOCKED"
    assert result["reason_codes"] == ["PLAN_TARGET_INVALID"]


def test_apply_plan_target_missing_key_is_blocked(tmp_path: Path) -> None:
    """plan target 完备性：target 缺必备键（ref）——PLAN_TARGET_INVALID。"""

    process = tmp_path
    plan_payload = {
        "exact_plan": {"targets": [{"before_exists": False}]},
        "exact_plan_digest": "x",
    }
    result = apply_baseline(
        process, plan_payload=plan_payload, authorization=None
    )
    assert result["decision"] == "BLOCKED"
    assert result["reason_codes"] == ["PLAN_TARGET_INVALID"]


def test_load_oserror_is_malformed_not_traceback(tmp_path: Path) -> None:
    """读取 OSError（V6 第 2 项）：权限拒绝的基线文件 fail-closed 为
    malformed——不可读的基线不得被当作 missing 或产出结论。"""

    process = tmp_path
    phase_ref = _phase(process)
    _write(process, phase_ref, _valid_payload())
    target = _baseline_path(process, phase_ref)
    os.chmod(target, 0)
    try:
        assert load_baseline_state(process, phase_ref) == ("malformed", None)
    finally:
        os.chmod(target, 0o644)


def test_plan_invalidation_read_oserror_typed_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """plan_invalidation 的 read_bytes OSError（loader 通过后的 IO 竞态）
    ——BASELINE_READ_ERROR，不上抛 traceback。"""

    process = tmp_path
    phase_ref = _phase(process)
    _write(process, phase_ref, _valid_payload())
    real_read_bytes = Path.read_bytes

    def _boom(self: Path) -> bytes:
        if self.name == "BASELINE.json":
            raise OSError("simulated io error")
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", _boom)
    result = plan_invalidation(
        process, phase_ref=phase_ref, reasons=["SOURCE_FINGERPRINT_DRIFT"], at="2026-08-25T00:00:00Z"
    )
    assert result["decision"] == "BLOCKED"
    assert result["reason_codes"] == ["BASELINE_READ_ERROR"]


def test_plan_baseline_read_oserror_typed_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """plan_baseline 的 before read_bytes OSError（rebaseline 路径）——
    BASELINE_READ_ERROR，不上抛 traceback。"""

    process = tmp_path
    phase_ref = _phase(process)
    invalidated = _valid_payload(
        invalidated_at="2026-08-24T01:00:00Z",
        invalidation_reasons=["SOURCE_FINGERPRINT_DRIFT"],
        history=[_history_item()],
    )
    _write(process, phase_ref, invalidated)
    real_read_bytes = Path.read_bytes

    def _boom(self: Path) -> bytes:
        if self.name == "BASELINE.json":
            raise OSError("simulated io error")
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", _boom)
    result = plan_baseline(
        process, phase_ref=phase_ref, entries=_ENTRIES, fingerprint=dict(_FINGERPRINT)
    )
    assert result["decision"] == "BLOCKED"
    assert result["reason_codes"] == ["BASELINE_READ_ERROR"]
