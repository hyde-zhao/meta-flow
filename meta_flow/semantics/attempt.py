"""dispatch/handoff attempt 状态和返工规划的唯一 owner。"""

from dataclasses import dataclass

TERMINAL_SUCCESS_STATUSES = frozenset(
    {"completed", "success", "succeeded", "passed"}
)
TERMINAL_SUCCESS_RESULTS = frozenset(
    {"pass", "success", "succeeded", "completed"}
)
TERMINAL_ATTEMPT_STATUSES = frozenset(
    {
        "completed",
        "success",
        "succeeded",
        "passed",
        "failed",
        "interrupted",
        "cancelled",
        "superseded",
    }
)
NONTERMINAL_ATTEMPT_STATUSES = frozenset(
    {"submitted", "running", "retrying"}
)
ALL_ATTEMPT_STATUSES = TERMINAL_ATTEMPT_STATUSES | NONTERMINAL_ATTEMPT_STATUSES

ACTIVE_HANDOFF_STATUSES = frozenset({"dispatched", "running", "in-progress"})
TERMINAL_HANDOFF_STATUSES = frozenset(
    {
        "completed",
        "success",
        "succeeded",
        "passed",
        "failed",
        "interrupted",
        "cancelled",
        "canceled",
        "superseded",
        "closed",
        "agent-completed",
        "agent-completed-pass",
        "rework-round-2-completed",
    }
)
ALL_HANDOFF_STATUSES = ACTIVE_HANDOFF_STATUSES | TERMINAL_HANDOFF_STATUSES

VALIDATION_LAYERS = ("static", "targeted", "compatibility", "full")


@dataclass(frozen=True)
class ReworkPlan:
    decision: str
    reuse_work: bool
    reuse_thread: bool
    new_attempt: bool
    new_dispatch: bool
    create_worktree: bool
    restart_layer: str
    layers: tuple[str, ...]
    reason_codes: tuple[str, ...]


def plan_rework(
    *,
    previous_work_id: str,
    next_work_id: str,
    previous_thread_id: str,
    next_thread_id: str,
    previous_attempt_id: str,
    next_attempt_id: str,
    previous_dispatch_id: str,
    next_dispatch_id: str,
    failed_layer: str,
    source_changed: bool,
    command_changed: bool,
    worktree_policy: str,
) -> ReworkPlan:
    """生成 ordinary current-slice rework 的封闭计划。"""

    reasons: list[str] = []
    if not previous_work_id or previous_work_id != next_work_id:
        reasons.append("REWORK_MUST_REUSE_WORK")
    if not previous_thread_id or previous_thread_id != next_thread_id:
        reasons.append("REWORK_MUST_REUSE_VERIFIED_THREAD")
    if not previous_attempt_id or previous_attempt_id == next_attempt_id:
        reasons.append("REWORK_REQUIRES_NEW_ATTEMPT_ID")
    if not previous_dispatch_id or previous_dispatch_id == next_dispatch_id:
        reasons.append("REWORK_REQUIRES_NEW_DISPATCH_ID")
    if failed_layer not in VALIDATION_LAYERS:
        reasons.append("REWORK_FAILED_LAYER_INVALID")
    if worktree_policy != "root-branch-only":
        reasons.append("REWORK_MUST_NOT_CREATE_WORKTREE")
    restart_layer = (
        "static"
        if source_changed or command_changed
        else failed_layer
        if failed_layer in VALIDATION_LAYERS
        else ""
    )
    layers = (
        VALIDATION_LAYERS[VALIDATION_LAYERS.index(restart_layer) :]
        if restart_layer in VALIDATION_LAYERS
        else ()
    )
    return ReworkPlan(
        decision="BLOCKED" if reasons else "READY",
        reuse_work=previous_work_id == next_work_id and bool(previous_work_id),
        reuse_thread=previous_thread_id == next_thread_id and bool(previous_thread_id),
        new_attempt=previous_attempt_id != next_attempt_id and bool(next_attempt_id),
        new_dispatch=previous_dispatch_id != next_dispatch_id and bool(next_dispatch_id),
        create_worktree=False,
        restart_layer=restart_layer,
        layers=layers,
        reason_codes=tuple(reasons),
    )


__all__ = [
    "ACTIVE_HANDOFF_STATUSES",
    "ALL_ATTEMPT_STATUSES",
    "ALL_HANDOFF_STATUSES",
    "NONTERMINAL_ATTEMPT_STATUSES",
    "ReworkPlan",
    "TERMINAL_ATTEMPT_STATUSES",
    "TERMINAL_HANDOFF_STATUSES",
    "TERMINAL_SUCCESS_RESULTS",
    "TERMINAL_SUCCESS_STATUSES",
    "VALIDATION_LAYERS",
    "plan_rework",
]
