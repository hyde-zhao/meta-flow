"""STORY-CR076-S02 Feature B targeted 测试：status-sync 投影事务接入（MF-BUG-19）。

SPR-N07：status-sync apply 且存在携带 lineage 的 manifest → STATE 写入经
投影事务、lineage 绑定、无新 LINEAGE_UNBOUND。SPR-02（targeted 部分）：
apply 后 inspect 无 LINEAGE_UNBOUND。
CT-FI1..07：FB4 四态断点注入矩阵（LLD §10/§11 归 T11）。
权威 = cr076-state-projection-recovery TEST-PLAN + LLD FB1/FB4。
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from test_cr_status_sync import _apply_ready, _authorization, write_termination_fixture

from meta_flow.state import current
from meta_flow.state.projection_transaction import (
    MANIFEST_REL,
    inspect_state_projection_transaction,
)
from meta_flow.workflow import cr_status_sync
from meta_flow.workflow.cr_index import _canonical_digest, _dirty_path_digest
from meta_flow.workflow.cr_status_transaction import (
    inspect_status_sync_transactions,
    recover_status_sync_transaction,
)

_CLOSED_INPUTS = {
    "status": "closed",
    "readiness": "READY_WITH_RISK",
    "gate_status": "cp8_closed",
    "work_id": "WORK-101",
    "effective_at": "2026-09-01T02:00:00+00:00",
}


def _ready_with_projection(directory: str) -> tuple[Path, Path]:
    """建带投影 targets 的 ready fixture（active CR-101 待关账）。"""

    release, process, _cr_path, _scope = write_termination_fixture(Path(directory))
    current.write_current_state(release, current.default_current_state(release))
    current.update_current_state(
        release,
        {
            "active_change": "CR-101",
            "current_phase": "documentation",
            "next_action": {"type": "await_user", "text": "review CP8"},
        },
    )
    return release, process


def _apply_closed(root: Path, **kwargs: object) -> dict:
    plan = cr_status_sync.plan_status_sync(root, "CR-101", **_CLOSED_INPUTS)
    result = _apply_ready(root, plan, **kwargs)
    return result


def test_spr_n07_state_write_goes_through_projection_transaction() -> None:
    with tempfile.TemporaryDirectory() as directory:
        release, process = _ready_with_projection(directory)
        result = _apply_closed(release)

        # FB4：双通道提交，投影先、exact 后
        assert result.get("status") == "PASS", result
        assert result.get("composite_state") == "COMMITTED"
        assert result.get("projection_decision") == "PASS"  # manifest state=COMMITTED

        # 投影事务 manifest：COMMITTED 且 applied refs 覆盖投影文件
        manifest_path = release / MANIFEST_REL
        assert manifest_path.is_file(), "projection transaction manifest missing"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["kind"] == "StateProjectionTransactionV1"
        assert manifest["state"] == "COMMITTED"
        applied_refs = set(manifest["applied_refs"])
        assert "process/state/STATE.current.json" in applied_refs

        # SPR-02（targeted 部分）：inspect 无 LINEAGE_UNBOUND / 未决事务
        inspection = inspect_state_projection_transaction(release)
        assert inspection["decision"] == "PASS", inspection
        assert not [
            finding
            for finding in inspection.get("findings", [])
            if "LINEAGE_UNBOUND" in finding or "UNRESOLVED" in finding
        ]

        # exact 通道同轮落地：formal CR 状态推进
        formal = (process / "changes" / "CR-101.md").read_text(encoding="utf-8")
        assert 'lifecycle_status: "closed"' in formal
        state = current.load_current_state(release)
        assert state["active_change"] is None


def test_spr_n07_unresolved_projection_transaction_blocks_before_write() -> None:
    """fail-closed：存在未决投影事务时 status-sync 写前 BLOCKED（mutation=0）。"""
    with tempfile.TemporaryDirectory() as directory:
        release, _process = _ready_with_projection(directory)
        # 注入未决投影事务：manifest 停在 APPLYING → inspect 非 PASS
        manifest_path = release / MANIFEST_REL
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["state"] = "APPLYING"
        manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")

        result = _apply_closed(release)
        assert result.get("status") == "BLOCKED"
        assert result.get("mutation_count") == 0
        assert "unresolved" in str(result.get("reason", "")).lower()


def test_ct_fi1_projection_preimage_drift_blocks_before_any_write() -> None:
    """CT-FI1 两通道均未写：prepare 阶段阻断（BLOCKED，mutation=0）。"""
    with tempfile.TemporaryDirectory() as directory:
        release, process = _ready_with_projection(directory)
        state_path = process / "state/STATE.current.json"
        formal_pre = (process / "changes/CR-101.md").read_bytes()
        plan = cr_status_sync.plan_status_sync(release, "CR-101", **_CLOSED_INPUTS)
        # 注入：计划后其他 writer 改投影文件 → prepare 阻断，两通道均未写
        state_path.write_bytes(state_path.read_bytes() + b"\n")
        result = _apply_ready(release, plan)
        assert result["status"] == "BLOCKED"
        assert result["mutation_count"] == 0
        assert "preimage drifted" in result["reason"]
        assert state_path.read_bytes().endswith(b"\n")  # composite 未再触碰该文件
        assert (process / "changes/CR-101.md").read_bytes() == formal_pre


def test_ct_fi2_projection_channel_failure_blocks_with_zero_mutation() -> None:
    """CT-FI2 第一通道提交前失败：BLOCKED（mutation=0），exact 通道不启动。"""
    with tempfile.TemporaryDirectory() as directory:
        release, process = _ready_with_projection(directory)
        projection_files = {
            ref: (process / ref.removeprefix("process/")).read_bytes()
            for ref in (
                "process/state/STATE.current.json",
                "process/STATE.md",
                "process/current/CURRENT.json",
            )
        }
        plan = cr_status_sync.plan_status_sync(release, "CR-101", **_CLOSED_INPUTS)
        with patch(
            "meta_flow.state.projection_transaction.apply_state_projection_transaction",
            side_effect=ValueError("injected pre-commit failure"),
        ):
            result = _apply_ready(release, plan)
        assert result["status"] == "BLOCKED"
        assert result["mutation_count"] == 0
        assert "projection channel failed" in result["reason"]
        # 投影 bytes 全部未动 + exact truth 未推进（第二通道未启动）
        for ref, payload_bytes in projection_files.items():
            assert (process / ref.removeprefix("process/")).read_bytes() == payload_bytes
        formal = (process / "changes/CR-101.md").read_text(encoding="utf-8")
        assert 'lifecycle_status: "closed"' not in formal


def test_ct_fi3_ct_fi5_exact_prewrite_failure_compensates_to_recovered() -> None:
    """CT-FI3 一提交后二提交前 + CT-FI5 补偿成功：投影通道已提交、exact 写前
    崩溃 → 补偿完整 → RECOVERED（如实记录已发生副作用，不宣称零 mutation）。"""
    with tempfile.TemporaryDirectory() as directory:
        release, process = _ready_with_projection(directory)
        state_path = process / "state/STATE.current.json"
        preimage = state_path.read_bytes()
        formal_pre = (process / "changes/CR-101.md").read_bytes()
        result = _apply_closed(release, _fault="before-first-replace")
        assert result["status"] == "RECOVERED"
        assert result["composite_state"] == "RECOVERED"
        assert result["compensation_complete"] is True
        # exact 通道自身写前失败（其 mutation=0）；投影补偿把文件写回 preimage
        assert result["mutation_count"] == 0
        assert state_path.read_bytes() == preimage
        assert (process / "changes/CR-101.md").read_bytes() == formal_pre
        # 补偿事务 COMMITTED：投影环境无未决，续跑可重新 plan
        inspection = inspect_state_projection_transaction(release)
        assert inspection["decision"] == "PASS", inspection


def test_ct_fi4_exact_midway_internal_recovery_is_partial_no_auto_continue() -> None:
    """CT-FI4 二提交后 receipt 前：exact 内部回滚成 RECOVERED（已发生写入），
    composite 不自动续推 → PARTIAL（compensation_complete=False）。"""
    with tempfile.TemporaryDirectory() as directory:
        release, process = _ready_with_projection(directory)
        formal_pre = (process / "changes/CR-101.md").read_bytes()
        result = _apply_closed(release, _fault="after-replace-before-receipt")
        assert result["composite_state"] == "PARTIAL"
        assert result["compensation_complete"] is False
        assert result["mutation_count"] == 1  # exact 已发生一次替换（后被内部回滚）
        # exact 内部回滚完成：formal truth 恢复，且未决事务目录被清理
        assert (process / "changes/CR-101.md").read_bytes() == formal_pre
        assert inspect_status_sync_transactions(release)["transaction_count"] == 0


def test_ct_fi6_compensation_failure_is_partial() -> None:
    """CT-FI6 补偿失败：exact 写前崩溃 + 投影补偿 apply 失败 → PARTIAL。"""
    with tempfile.TemporaryDirectory() as directory:
        release, _process = _ready_with_projection(directory)
        with patch(
            "meta_flow.state.projection_transaction.apply_state_projection_transaction",
            side_effect=[{"decision": "PASS"}, ValueError("injected compensation failure")],
        ):
            result = _apply_closed(release, _fault="before-first-replace")
        assert result["composite_state"] == "PARTIAL"
        assert result["compensation_complete"] is False


def test_ct_fi7_crash_inspect_recover_then_idempotent_reapply() -> None:
    """CT-FI7 crash 后 inspect/recover 幂等续跑：exact 回滚失败留未决 →
    inspect 观测 → recover(rollback) 清障 → 重新 plan/apply → COMMITTED。"""
    with tempfile.TemporaryDirectory() as directory:
        release, process = _ready_with_projection(directory)
        formal_pre = (process / "changes/CR-101.md").read_bytes()
        result = _apply_closed(release, _fault="after-replace-before-receipt", _fail_recovery=True)
        assert result["composite_state"] == "PARTIAL"
        # 投影通道已提交（closed 形态 bytes 落盘），exact truth 仍为 pre 状态
        assert current.load_current_state(release)["active_change"] is None
        # 未决 exact 事务可被 inspect 观测
        unresolved = inspect_status_sync_transactions(release)
        assert unresolved["transaction_count"] == 1
        transaction_id = unresolved["transactions"][0]["transaction_id"]
        # recover rollback（typed authorization 注入）清障
        recovered = recover_status_sync_transaction(
            release,
            transaction_id,
            action="rollback",
            typed_authorized=True,
            canonical_digest=_canonical_digest,
            dirty_path_digest=_dirty_path_digest,
        )
        assert recovered["status"] == "RECOVERED", recovered
        assert (process / "changes/CR-101.md").read_bytes() == formal_pre
        assert inspect_status_sync_transactions(release)["transaction_count"] == 0
        # 幂等续跑：新授权（旧授权已消费）→ 投影通道 NO_CHANGE，exact 重跑 → COMMITTED
        second_plan = cr_status_sync.plan_status_sync(release, "CR-101", **_CLOSED_INPUTS)
        second = cr_status_sync.apply_status_sync(
            release,
            second_plan,
            authorization=_authorization(second_plan, authorization_id="AUTH-STATUS-SYNC-CTFI7"),
            expected_plan_digest=second_plan.plan_digest,
        )
        assert second["status"] == "PASS", second
        # 投影文件已在第一轮经投影通道落位：续跑计划无投影 diff，composite
        # 退回单通道 exact 路径（无 composite_state 键），最终 formal 推进到位。
        assert "composite_state" not in second
        formal = (process / "changes/CR-101.md").read_text(encoding="utf-8")
        assert 'lifecycle_status: "closed"' in formal
        inspection = inspect_state_projection_transaction(release)
        assert inspection["decision"] == "PASS", inspection
