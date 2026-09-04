"""按 route stage 顺序推导唯一 checkpoint 执行前沿。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

PASS_DECISIONS = frozenset({"PASS", "PASS_WITH_RISK", "WAIVED"})


@dataclass(frozen=True, slots=True)
class GateFrontierV1:
    status: str
    checkpoint: str
    result_ref: str
    pending_gate: str
    pending_checklist_path: str
    reason_code: str

    def as_dict(self) -> dict[str, str]:
        return {
            "schema_version": "1",
            "status": self.status,
            "checkpoint": self.checkpoint,
            "result_ref": self.result_ref,
            "pending_gate": self.pending_gate,
            "pending_checklist_path": self.pending_checklist_path,
            "reason_code": self.reason_code,
        }


def derive_gate_frontier(
    stages: Sequence[Mapping[str, Any]],
    checkpoint_heads: Mapping[str, Mapping[str, Any]],
    approved_results: Mapping[str, str],
    launched_results: Mapping[str, Mapping[str, str]],
) -> GateFrontierV1:
    """从有序 stage、current heads、批准和 launch 精确推导前沿。

    规则故意不扫描“第一个未批准的人工作业”。每一个前序自动 checkpoint 也
    必须先有可接受 current head，因此缺 CP6/CP7 时绝不可能跳到 CP8。
    """

    seen: set[str] = set()
    for raw_stage in stages:
        checkpoint = str(raw_stage.get("checkpoint") or "").upper()
        if not checkpoint or checkpoint in seen:
            return GateFrontierV1(
                "BLOCKED", checkpoint, "", "", "", "ROUTE_STAGE_INVALID"
            )
        seen.add(checkpoint)
        head = checkpoint_heads.get(checkpoint)
        if not isinstance(head, Mapping):
            return GateFrontierV1(
                "WAITING_CHECKPOINT",
                checkpoint,
                "",
                "",
                "",
                "CURRENT_CHECKPOINT_HEAD_MISSING",
            )
        result_ref = str(head.get("result_ref") or "")
        decision = str(head.get("decision") or "").upper()
        if not result_ref or decision not in PASS_DECISIONS:
            return GateFrontierV1(
                "BLOCKED",
                checkpoint,
                result_ref,
                "",
                "",
                "CURRENT_CHECKPOINT_HEAD_NOT_PASSABLE",
            )
        if str(raw_stage.get("human_gate") or "none") != "required":
            continue
        if approved_results.get(checkpoint) == result_ref:
            continue
        launch = launched_results.get(checkpoint)
        if not isinstance(launch, Mapping) or str(launch.get("result_ref") or "") != result_ref:
            return GateFrontierV1(
                "WAITING_GATE_LAUNCH",
                checkpoint,
                result_ref,
                "",
                "",
                "CURRENT_HEAD_GATE_LAUNCH_MISSING",
            )
        checklist = str(launch.get("checkpoint_ref") or "")
        if not checklist:
            return GateFrontierV1(
                "BLOCKED",
                checkpoint,
                result_ref,
                "",
                "",
                "GATE_LAUNCH_CHECKPOINT_REF_MISSING",
            )
        return GateFrontierV1(
            "AWAITING_HUMAN_GATE",
            checkpoint,
            result_ref,
            checkpoint,
            checklist,
            "CURRENT_HEAD_AWAITS_APPROVAL",
        )
    return GateFrontierV1("COMPLETE", "", "", "", "", "ROUTE_COMPLETE")


__all__ = ["GateFrontierV1", "PASS_DECISIONS", "derive_gate_frontier"]
