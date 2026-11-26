"""派生状态、ledger 与任务汇总。"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

MAX_STATE_BYTES = 8192
VALID_PHASES = ("P1", "P2", "P3", "P4", "P5")


class StateError(Exception):
    """派生状态无法安全重建或写入。"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _derive_current(contract: Path) -> dict[str, Any]:
    """从 ROADMAP 与任务卡重建最小当前状态，避免静默回退到 R1/P1。"""
    roadmap_data = _load_yaml(contract / "roadmap" / "ROADMAP.yaml")
    roadmaps = [item for item in roadmap_data.get("roadmaps") or [] if isinstance(item, dict)]
    active = next((item for item in roadmaps if item.get("status") == "active"), None)
    selected = active or (roadmaps[-1] if roadmaps else None)
    roadmap_id = str((selected or {}).get("id") or "R1")
    tasks = []
    for path in sorted((contract / "roadmap" / roadmap_id).glob("phases/*/tasks/T*/TASK.yaml")):
        data = _load_yaml(path)
        if data:
            tasks.append(data)
    phases = [str(task.get("phase")) for task in tasks if task.get("phase") in VALID_PHASES]
    for path in sorted((contract / "roadmap" / roadmap_id).glob("phases/*/REPORT.md")):
        if path.parent.name in VALID_PHASES:
            phases.append(path.parent.name)
    for path in sorted((contract / "roadmap" / roadmap_id).glob("phases/*/HANDOFF-TO-P*.md")):
        match = path.name.rsplit("-", 1)[-1].removesuffix(".md")
        if match in VALID_PHASES:
            phases.append(match)
    phase = max(phases, key=VALID_PHASES.index) if phases else "P1"
    phase_status = "active"
    if phase == "P5" and list((contract / "release").glob("RELEASE-*.yaml")):
        phase_status = "exited"
    return {
        "schema": 1,
        "roadmap": roadmap_id,
        "phase": phase,
        "phase_status": phase_status,
    }


def read_current(contract: Path) -> dict[str, Any]:
    path = contract / "state" / "current.json"
    if not path.is_file():
        return _derive_current(contract)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return _derive_current(contract)
    if not isinstance(data, dict):
        return _derive_current(contract)
    derived = _derive_current(contract)
    roadmap_data = _load_yaml(contract / "roadmap" / "ROADMAP.yaml")
    roadmap_ids = {str(item.get("id")) for item in roadmap_data.get("roadmaps") or []}
    if not data.get("roadmap") or (roadmap_ids and data.get("roadmap") not in roadmap_ids):
        data["roadmap"] = derived["roadmap"]
    if data.get("phase") not in (*VALID_PHASES, "done", "closed"):
        data["phase"] = derived["phase"]
    if not data.get("phase_status"):
        data["phase_status"] = "active"
    return data


def _source_digest(contract: Path, data: dict[str, Any]) -> str:
    parts = [str(data.get("roadmap")), str(data.get("phase")), str(data.get("phase_status"))]
    for path in sorted((contract / "roadmap").glob("*/phases/*/tasks/T*/TASK.yaml")):
        item = _load_yaml(path)
        parts.append(f"{item.get('id')}:{item.get('status')}:{item.get('updated_at')}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]


def write_current(contract: Path, data: dict[str, Any]) -> dict[str, Any]:
    path = contract / "state" / "current.json"
    data["updated_at"] = _now()
    data["source_digest"] = _source_digest(contract, data)
    original = {
        "active_tasks": list(data.get("active_tasks") or []),
        "active_leases": list(data.get("active_leases") or []),
        "submitted_tasks": list(data.get("submitted_tasks") or []),
        "ready_tasks": list(data.get("ready_tasks") or []),
    }
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if len(text.encode("utf-8")) > MAX_STATE_BYTES:
        data["active_tasks"] = original["active_tasks"][:10]
        data["active_leases"] = original["active_leases"][:10]
        data["submitted_tasks"] = original["submitted_tasks"][:10]
        data["ready_tasks"] = original["ready_tasks"][:20]
        data["active_tasks_total"] = len(original["active_tasks"])
        data["truncated"] = True
        text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if len(text.encode("utf-8")) > MAX_STATE_BYTES:
        data.pop("active_tasks", None)
        data.pop("active_leases", None)
        data.pop("submitted_tasks", None)
        data.pop("ready_tasks", None)
        data["truncated"] = True
        data["references"] = "mf task summary"
        text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if len(text.encode("utf-8")) > MAX_STATE_BYTES:
        raise StateError(
            f"state/current.json 超过 {MAX_STATE_BYTES} 字节；请把明细移入任务卡/ledger"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    omitted = {
        key: len(values) - len(data.get(key) or [])
        for key, values in original.items()
        if len(data.get(key) or []) < len(values)
    }
    if omitted:
        ledger_append(
            contract,
            {
                "event": "state.truncate",
                "reason": f"current.json > {MAX_STATE_BYTES}B",
                "omitted": omitted,
                "active_tasks": original["active_tasks"],
            },
        )
    return data


def ledger_append(contract: Path, event: dict[str, Any]) -> None:
    path = contract / "state" / "ledger.ndjson"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(event)
    actor = payload.pop("actor", None) or os.environ.get("MF_ACTOR") or "cli"
    role = payload.pop("role", None) or os.environ.get("MF_ROLE") or "unknown"
    record = {"ts": _now(), "actor": actor, "role": role, **payload}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def tail_lines(path: Path, limit: int = 50) -> list[str]:
    """从文件尾部读取最近 N 行，避免 log/READ-LOG 全量载入。"""
    if limit <= 0 or not path.is_file():
        return []
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        position = handle.tell()
        data = b""
        newlines = 0
        while position > 0 and newlines <= limit:
            step = min(8192, position)
            position -= step
            handle.seek(position)
            chunk = handle.read(step)
            data = chunk + data
            newlines = data.count(b"\n")
    text = data.decode("utf-8", errors="ignore")
    return [line for line in text.splitlines() if line.strip()][-limit:]


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


REVIEW_VERDICT_RE = re.compile(
    r"verdict\s*[:=]\s*(PASS_WITH_RISK|PASS|NEEDS_REWORK|BLOCKED)", re.IGNORECASE
)


def _bundle_review_verdict(bundle: Path) -> str | None:
    """读取 review-handoff/review 的最新结论，避免 state 使用卡片陈旧值。"""
    for name in ("review-handoff.md", "review.md"):
        path = bundle / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        match = REVIEW_VERDICT_RE.search(text)
        if match:
            return match.group(1).upper()
        for verdict in ("PASS_WITH_RISK", "NEEDS_REWORK", "BLOCKED", "PASS"):
            if verdict in text:
                return verdict
    return None


def review_needs_rework(
    review_task: dict[str, Any] | None,
    review_bundle: Path | None,
) -> bool:
    """判断 review 当前是否处于 NEEDS_REWORK（task/state 统一口径）。

    - review accepted 且 verdict=NEEDS_REWORK；
    - 或 review submitted 且最新 review-handoff/review.md 为 NEEDS_REWORK。
    review 已重置 ready 时旧 verdict 不算有效，避免误导 start/rework。
    """
    if review_task is None or review_bundle is None:
        return False
    if (
        review_task.get("status") == "accepted"
        and review_task.get("review_verdict") == "NEEDS_REWORK"
    ):
        return True
    return (
        review_task.get("status") == "submitted"
        and _bundle_review_verdict(review_bundle) == "NEEDS_REWORK"
    )


def task_summary(contract: Path) -> dict[str, Any]:
    counts: dict[str, int] = {}
    active: list[str] = []
    leases: list[dict[str, Any]] = []
    submitted: list[str] = []
    submitted_details: list[dict[str, Any]] = []
    ready: list[str] = []
    rework: list[str] = []
    stale_rework: list[str] = []
    all_tasks: dict[str, dict[str, Any]] = {}
    task_paths: dict[str, Path] = {}
    for path in sorted((contract / "roadmap").glob("*/phases/*/tasks/T*/TASK.yaml")):
        data = _load_yaml(path)
        status = str(data.get("status") or "draft")
        counts[status] = counts.get(status, 0) + 1
        task_id = str(data.get("id") or path.parent.name)
        all_tasks[task_id] = data
        task_paths[task_id] = path.parent
        if status in {"in_progress"}:
            active.append(task_id)
            lease = data.get("lease") or {}
            leases.append(
                {
                    "task": task_id,
                    "owner": lease.get("owner"),
                    "wave": data.get("wave") or "W1",
                    "expires_at": lease.get("expires_at"),
                }
            )
        if status == "submitted":
            submitted.append(task_id)
            submitted_details.append(
                {
                    "id": task_id,
                    "kind": data.get("kind"),
                    "reviewed_by_task": data.get("reviewed_by_task"),
                    "review_status": None,
                    "review_verdict": None,
                }
            )
        if status == "ready":
            ready.append(task_id)
    for detail in submitted_details:
        review_id = detail.get("reviewed_by_task")
        if review_id and str(review_id) in all_tasks:
            review_data = all_tasks[str(review_id)]
            review_status = str(review_data.get("status") or "")
            detail["review_status"] = review_status
            if review_status == "submitted":
                # 评审已提交但未验收：以最新 handoff 为准，不读上一轮卡片 verdict
                detail["review_verdict"] = _bundle_review_verdict(
                    task_paths[str(review_id)]
                ) or (str(review_data.get("review_verdict") or "") or None)
            else:
                detail["review_verdict"] = (
                    str(review_data.get("review_verdict") or "") or None
                )
    # R3：与 task._review_task_needs_rework 统一口径，不信任目标卡历史 verdict
    for task_id, data in all_tasks.items():
        status = str(data.get("status") or "")
        if status not in {"rework", "rejected"}:
            continue
        review_id = data.get("reviewed_by_task")
        review_data = all_tasks.get(str(review_id)) if review_id else None
        review_bundle = task_paths.get(str(review_id)) if review_id else None
        if review_needs_rework(review_data, review_bundle):
            rework.append(task_id)
        elif (
            status == "rework"
            or data.get("review_verdict")
            or isinstance(data.get("rework"), dict)
        ):
            stale_rework.append(task_id)
    return {
        "counts": counts,
        "active_tasks": active[:20],
        "active_leases": leases[:20],
        "submitted_tasks": submitted[:20],
        "submitted_details": submitted_details[:20],
        "ready_tasks": ready[:50],
        "rework_tasks": rework[:20],
        "stale_rework_tasks": stale_rework[:20],
    }


def open_bugs(contract: Path) -> list[dict[str, Any]]:
    items = []
    for path in sorted((contract / "bugs").glob("BUG-*.yaml")):
        data = _load_yaml(path)
        if str(data.get("status")) in {"open", "triaged", "in_progress", "reopened", "verifying"}:
            items.append(data)
    return items


def refresh_current(contract: Path) -> dict[str, Any]:
    data = read_current(contract)
    summary = task_summary(contract)
    bugs = open_bugs(contract)
    data.update(summary)
    data["open_bugs"] = len(bugs)
    phase_status = str(data.get("phase_status") or "")
    phase = str(data.get("phase") or "")
    if phase_status == "done":
        data["next_action"] = {"type": "release", "text": "冻结发布并关闭路标"}
    elif phase_status == "exited":
        if phase == "P5":
            if data.get("release_status") == "frozen":
                data["next_action"] = {"type": "close_roadmap", "roadmap": data.get("roadmap")}
            else:
                data["next_action"] = {"type": "release", "text": "冻结发布并关闭路标"}
        else:
            next_phase = {"P1": "P2", "P2": "P3", "P3": "P4", "P4": "P5"}.get(phase)
            data["next_action"] = {"type": "enter_phase", "phase": next_phase}
    elif phase_status == "closed":
        data["next_action"] = {"type": "plan", "text": "规划下一路标"}
    elif summary.get("rework_tasks"):
        rework_task_id = summary["rework_tasks"][0]
        data["next_action"] = {
            "type": "execute_rework",
            "task": rework_task_id,
            "text": f"review NEEDS_REWORK 已重开；worker 用 mf task rework {rework_task_id} 开始，"
            "整改项与 allowed_paths 见任务卡 rework",
        }
    elif summary["submitted_tasks"]:
        detail = (summary.get("submitted_details") or [{}])[0]
        task_id = detail.get("id") or summary["submitted_tasks"][0]
        review_id = detail.get("reviewed_by_task")
        review_status = detail.get("review_status")
        if (
            detail.get("kind") != "review"
            and review_status == "accepted"
            and detail.get("review_verdict") == "NEEDS_REWORK"
        ):
            # 范围外/高风险/争议不自动重开，等 manager 裁决（MFP-0015 E2/E5）
            data["next_action"] = {
                "type": "rework_decision",
                "task": task_id,
                "review_task": review_id,
                "text": "review NEEDS_REWORK 未自动重开；manager 裁决：reject 退回 worker 用 "
                f"mf task rework {task_id}，或开 CHG/BUG/MFP/新卡",
            }
        elif detail.get("kind") == "review" or not review_id or review_status in {"accepted"}:
            data["next_action"] = {"type": "accept", "task": task_id}
        else:
            # 评审门优先：实现任务已提交但独立评审尚未完成
            data["next_action"] = {
                "type": "review",
                "task": review_id,
                "parent_task": task_id,
                "text": f"等待评审任务 {review_id}；通过后再验收 {task_id}",
            }
    elif summary.get("stale_rework_tasks"):
        stale_task_id = summary["stale_rework_tasks"][0]
        data["next_action"] = {
            "type": "recover_rework",
            "task": stale_task_id,
            "text": "旧卡 review 已不在 NEEDS_REWORK；"
            f"worker 用 mf task start {stale_task_id} 恢复（start 会清理陈旧 verdict）",
        }
    elif summary["active_tasks"]:
        # 存在在途任务与有效租约时，先跟进任务，不直接把 next_action 指向 fix_bug
        data["next_action"] = {
            "type": "follow_up_task",
            "task": summary["active_tasks"][0],
            "text": f"跟进 {summary['active_tasks'][0]}；等待 worker 提交，租约到期可回收",
        }
    elif bugs:
        data["next_action"] = {"type": "fix_bug", "bug": bugs[0].get("id")}
    elif summary["ready_tasks"]:
        data["next_action"] = {"type": "execute", "task": summary["ready_tasks"][0]}
    else:
        data["next_action"] = {"type": "plan", "text": "规划下一任务或阶段"}
    return write_current(contract, data)
