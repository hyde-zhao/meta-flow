"""STORY-CR076-S02 Feature B targeted 测试：StateProjectionLineageRebindV1。

SPR-04（计划零写）、SPR-05（执行一次性：TOCTOU/失败 mutation=0/投影 bytes
不变）、SPR-06（fb0bbaec 形态回归：rebind 后 inspect 无 LINEAGE_UNBOUND）与
失败矩阵 SPR-N01..N05。全部在 fixture 沙箱内；真实仓执行另取授权。
权威 = cr076-state-projection-recovery TEST-PLAN + DESIGN R-01..R-08。
"""

from __future__ import annotations

import base64
import hashlib
import json
import tempfile
from pathlib import Path

from test_cr_status_sync import write_termination_fixture

from meta_flow.state import current
from meta_flow.state.lineage_rebind import (
    LineageRebindPlanV1,
    StateProjectionLineageRebindAuthorizationV1,
    execute_lineage_rebind,
    plan_lineage_rebind,
)
from meta_flow.state.projection_transaction import (
    MANIFEST_REL,
    inspect_state_projection_transaction,
)

CLOSE_REF = "state/STATE.current.json"  # close head targets 用去前缀 ref
STATE_LOGICAL_REF = "process/state/STATE.current.json"
D64 = "0" * 64
RECEIPT_REF = "process/state/CR-076-activation-receipt-4e4882cd.json"


def _write_close_head(process: Path, *, after: bytes) -> None:
    """写最小 COMMITTED work-close manifest（generation_lineage 校验闭合）。"""
    transaction_dir = (
        process / ".meta-flow-runtime/work-close/transactions/AUTH-WC-CR076-TEST-V1"
    )
    transaction_dir.mkdir(parents=True)
    before = b"previous"
    manifest = {
        "schema_version": 1,
        "kind": "work-close-transaction-v1",
        "authorization_id": "AUTH-WC-CR076-TEST-V1",
        "work_id": "WORK-CR076-TEST-V1",
        "plan_digest": D64,
        "state": "COMMITTED",
        "created_at": "2026-08-31T00:00:00+00:00",
        "updated_at": "2026-08-31T00:00:00+00:00",
        "attempted_refs": [CLOSE_REF],
        "applied_refs": [CLOSE_REF],
        "targets": [
            {
                "ref": CLOSE_REF,
                "before_digest": hashlib.sha256(before).hexdigest(),
                "after_digest": hashlib.sha256(after).hexdigest(),
                "before_bytes_b64": base64.b64encode(before).decode("ascii"),
                "after_bytes_b64": base64.b64encode(after).decode("ascii"),
            }
        ],
        "lineage": {},
    }
    (transaction_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _unbound_fixture(directory: str) -> tuple[Path, Path]:
    """复刻 fb0bbaec 形态：close head 之后出现未带 lineage 锚的投影写入。"""
    release, process, _cr, _scope = write_termination_fixture(Path(directory))
    current.write_current_state(release, current.default_current_state(release))
    current.update_current_state(
        release,
        {
            "active_change": "CR-101",
            "current_phase": "documentation",
            "next_action": {"type": "await_user", "text": "review CP8"},
        },
    )
    state_path = process / "state/STATE.current.json"
    # close head 锚定当时的投影 bytes（direct close generation，无 finding）
    _write_close_head(process, after=state_path.read_bytes())
    # MF-BUG-19 形态：writer 落了新投影 bytes，但没有携带 close head lineage 锚
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    payload["next_action"] = {"type": "drifted", "text": "rogue writer"}
    drifted = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    state_path.write_bytes(drifted)
    manifest_path = release / MANIFEST_REL
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for target in manifest["targets"]:
        if target["ref"] == STATE_LOGICAL_REF:
            target["after_digest"] = hashlib.sha256(drifted).hexdigest()
            target["after_bytes_b64"] = base64.b64encode(drifted).decode("ascii")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    inspection = inspect_state_projection_transaction(release)
    # 前置自检：唯一 finding 就是 LINEAGE_UNBOUND（R-01 的可 rebind 形态）
    assert inspection["findings"] == [
        f"STATE_PROJECTION_LINEAGE_UNBOUND:{STATE_LOGICAL_REF}"
    ], inspection
    return release, state_path


def _authorization_for(
    plan: LineageRebindPlanV1,
) -> StateProjectionLineageRebindAuthorizationV1:
    return StateProjectionLineageRebindAuthorizationV1(
        1,
        "StateProjectionLineageRebindAuthorizationV1",
        "AUTH-REBIND-CR076-TEST-V1",
        plan.plan_digest,
        plan.manifest_digest,
        plan.transaction_id,
        "2026-09-01T00:00:00Z",
        "2099-01-01T00:00:00Z",
        True,
    )


def test_spr_04_plan_is_zero_write_and_digest_bound() -> None:
    with tempfile.TemporaryDirectory() as directory:
        release, _state = _unbound_fixture(directory)
        manifest_bytes = (release / MANIFEST_REL).read_bytes()
        plan = plan_lineage_rebind(release, writer_receipt_ref=RECEIPT_REF)
        assert plan.decision == "READY", plan.reason
        assert plan.transaction_id and plan.manifest_digest
        assert len(plan.projection_digests) == 3  # R-02：三投影文件 digest
        assert plan.writer_receipt_ref == RECEIPT_REF  # R-03
        # 零写：计划不落任何文件
        assert (release / MANIFEST_REL).read_bytes() == manifest_bytes


def test_spr_n01_coexisting_drift_rejected() -> None:
    with tempfile.TemporaryDirectory() as directory:
        release, state_path = _unbound_fixture(directory)
        # 追加共现 finding：文件再漂移一次且不经投影 manifest（TERMINAL_GENERATION_DRIFT）
        state_path.write_bytes(state_path.read_bytes() + b"\n")
        plan = plan_lineage_rebind(release, writer_receipt_ref=RECEIPT_REF)
        assert plan.decision == "BLOCKED"
        assert "R-01" in plan.reason


def test_spr_n02_non_committed_manifest_rejected() -> None:
    with tempfile.TemporaryDirectory() as directory:
        release, _state = _unbound_fixture(directory)
        manifest_path = release / MANIFEST_REL
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["state"] = "PARTIAL"
        manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
        plan = plan_lineage_rebind(release, writer_receipt_ref=RECEIPT_REF)
        assert plan.decision == "BLOCKED"  # load_committed_projection_snapshot 拒绝非 terminal


def test_spr_05_execute_is_one_shot_and_bytes_preserved() -> None:
    with tempfile.TemporaryDirectory() as directory:
        release, state_path = _unbound_fixture(directory)
        plan = plan_lineage_rebind(release, writer_receipt_ref=RECEIPT_REF)
        assert plan.decision == "READY"
        projection_bytes = state_path.read_bytes()
        result = execute_lineage_rebind(
            release, plan, _authorization_for(plan), now="2026-09-01T06:00:00Z"
        )
        assert result["status"] == "PASS", result
        assert result["mutation_count"] == 1  # 唯一 mutation = successor manifest
        assert result["projection_files_mutated"] == 0  # R-04
        assert result["dq09_ruling"] == "not_adjudicated"  # R-08
        assert state_path.read_bytes() == projection_bytes  # R-04：逐字节不变
        # SPR-06：rebind 后 inspect 无 LINEAGE_UNBOUND（fb0bbaec 形态闭环）
        inspection = inspect_state_projection_transaction(release)
        assert inspection["decision"] == "PASS", inspection
        assert not [
            finding for finding in inspection.get("findings", []) if "LINEAGE_UNBOUND" in finding
        ]
        successor = json.loads((release / MANIFEST_REL).read_text(encoding="utf-8"))
        assert successor["lineage_rebind"]["supersedes_manifest_digest"] == plan.manifest_digest
        # R-06：旧 manifest digest 在 successor 中保留可追溯
        # R-03：writer receipt 落入 successor 记录
        assert successor["lineage_rebind"]["writer_receipt_ref"] == RECEIPT_REF
        # lineage 锚按 close head 重写（authorized_state_successor 三字段）
        anchor = successor["lineage"][STATE_LOGICAL_REF]
        assert anchor["anchor_close_authorization_id"] == "AUTH-WC-CR076-TEST-V1"
        assert anchor["current_digest"] == hashlib.sha256(projection_bytes).hexdigest()


def test_spr_n03_toctou_drift_rejected_authorization_not_consumed() -> None:
    with tempfile.TemporaryDirectory() as directory:
        release, state_path = _unbound_fixture(directory)
        plan = plan_lineage_rebind(release, writer_receipt_ref=RECEIPT_REF)
        manifest_before = (release / MANIFEST_REL).read_bytes()
        # 计划后、执行前：另一 writer 再改投影文件（TOCTOU）
        state_path.write_bytes(state_path.read_bytes() + b"\n")
        result = execute_lineage_rebind(
            release, plan, _authorization_for(plan), now="2026-09-01T06:00:00Z"
        )
        assert result["status"] == "BLOCKED"
        assert result["mutation_count"] == 0
        assert "TOCTOU" in result["reason"]
        assert (release / MANIFEST_REL).read_bytes() == manifest_before  # 无半态


def test_spr_n04_double_execution_blocked() -> None:
    with tempfile.TemporaryDirectory() as directory:
        release, _state = _unbound_fixture(directory)
        plan = plan_lineage_rebind(release, writer_receipt_ref=RECEIPT_REF)
        first = execute_lineage_rebind(
            release, plan, _authorization_for(plan), now="2026-09-01T06:00:00Z"
        )
        assert first["status"] == "PASS"
        # 同一授权二次执行：manifest 已带 successor → plan 阻断 → execute 阻断
        replan = plan_lineage_rebind(release, writer_receipt_ref=RECEIPT_REF)
        assert replan.decision == "BLOCKED"
        assert "already carries" in replan.reason
        second = execute_lineage_rebind(
            release, replan, _authorization_for(plan), now="2026-09-01T07:00:00Z"
        )
        assert second["status"] == "BLOCKED" and second["mutation_count"] == 0


def test_spr_n05_write_failure_keeps_blocked_and_no_half_state() -> None:
    with tempfile.TemporaryDirectory() as directory:
        release, _state = _unbound_fixture(directory)
        plan = plan_lineage_rebind(release, writer_receipt_ref=RECEIPT_REF)
        manifest_before = (release / MANIFEST_REL).read_bytes()
        # 注入写失败：manifest 目录变只读（successor 落盘失败）
        manifest_dir = (release / MANIFEST_REL).parent
        original_mode = manifest_dir.stat().st_mode
        manifest_dir.chmod(0o500)
        try:
            result = execute_lineage_rebind(
                release, plan, _authorization_for(plan), now="2026-09-01T06:00:00Z"
            )
            assert result["status"] == "BLOCKED"
            assert result["mutation_count"] == 0
        finally:
            manifest_dir.chmod(original_mode)
        assert (release / MANIFEST_REL).read_bytes() == manifest_before  # 旧 manifest 完整
        assert not list(manifest_dir.glob("*.rebind-tmp"))  # 无半态残留
