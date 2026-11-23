"""派生状态、ledger 与任务汇总。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

MAX_STATE_BYTES = 8192


def _now() -> str:
    return datetime.now(UTC).isoformat()


def read_current(contract: Path) -> dict[str, Any]:
    path = contract / "state" / "current.json"
    if not path.is_file():
        return {"schema": 1, "roadmap": "R1", "phase": "P1"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"schema": 1, "roadmap": "R1", "phase": "P1"}
    return data if isinstance(data, dict) else {"schema": 1, "roadmap": "R1", "phase": "P1"}


def write_current(contract: Path, data: dict[str, Any]) -> dict[str, Any]:
    path = contract / "state" / "current.json"
    data["updated_at"] = _now()
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if len(text.encode("utf-8")) > MAX_STATE_BYTES:
        data["active_tasks"] = data.get("active_tasks", [])[:10]
        data["counts"] = data.get("counts", {})
        text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return data


def ledger_append(contract: Path, event: dict[str, Any]) -> None:
    path = contract / "state" / "ledger.ndjson"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ts": _now(), **event}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def task_summary(contract: Path) -> dict[str, Any]:
    counts: dict[str, int] = {}
    active: list[str] = []
    leases: list[dict[str, Any]] = []
    submitted: list[str] = []
    ready: list[str] = []
    for path in sorted((contract / "roadmap").glob("*/phases/*/tasks/T*/TASK.yaml")):
        data = _load_yaml(path)
        status = str(data.get("status") or "draft")
        counts[status] = counts.get(status, 0) + 1
        task_id = str(data.get("id") or path.parent.name)
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
        if status == "ready":
            ready.append(task_id)
    return {
        "counts": counts,
        "active_tasks": active[:20],
        "active_leases": leases[:20],
        "submitted_tasks": submitted[:20],
        "ready_tasks": ready[:50],
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
    if phase_status == "done":
        data["next_action"] = {"type": "release", "text": "冻结发布并关闭路标"}
    elif phase_status == "closed":
        data["next_action"] = {"type": "plan", "text": "规划下一路标"}
    elif summary["submitted_tasks"]:
        data["next_action"] = {"type": "accept", "task": summary["submitted_tasks"][0]}
    elif bugs:
        data["next_action"] = {"type": "fix_bug", "bug": bugs[0].get("id")}
    elif summary["ready_tasks"]:
        data["next_action"] = {"type": "execute", "task": summary["ready_tasks"][0]}
    else:
        data["next_action"] = {"type": "plan", "text": "规划下一任务或阶段"}
    return write_current(contract, data)
