"""缺陷生命周期、修复关联与门禁查询。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .state import ledger_append, read_current, refresh_current
from .workspace import resolve_contract

SEVERITIES = ("blocker", "critical", "major", "minor", "trivial")
STATUSES = (
    "open",
    "triaged",
    "in_progress",
    "fixed",
    "verifying",
    "closed",
    "reopened",
    "deferred",
    "wontfix",
)
OPEN_STATUSES = {"open", "triaged", "in_progress", "reopened", "verifying"}


class BugError(Exception):
    """缺陷操作失败。"""

    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _load(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise BugError(f"{path} 不是合法 YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise BugError(f"{path} 顶层必须是映射")
    return data


def _save(path: Path, data: dict[str, Any]) -> None:
    data["updated_at"] = _now()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _paths(contract: Path) -> list[Path]:
    return sorted((contract / "bugs").glob("BUG-*.yaml"))


def _find(contract: Path, bug_id: str) -> tuple[Path, dict[str, Any]]:
    for path in _paths(contract):
        if path.stem == bug_id:
            return path, _load(path)
    raise BugError(f"缺陷不存在: {bug_id}")


def _next_id(contract: Path) -> str:
    numbers = [int(path.stem[4:]) for path in _paths(contract) if path.stem[4:].isdigit()]
    return f"BUG-{max(numbers, default=0) + 1:04d}"


def add_bug(
    project: str | Path,
    title: str,
    *,
    severity: str = "major",
    phase: str | None = None,
    task: str | None = None,
    verification: str | None = None,
    delivery: str | None = None,
    related_reqs: list[str] | None = None,
    environment: str = "",
    steps: str = "",
    expected: str = "",
    actual: str = "",
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    contract = resolve_contract(project)
    if severity not in SEVERITIES:
        raise BugError(f"severity 只能是 {'|'.join(SEVERITIES)}")
    if not title.strip():
        raise BugError("BUG 必须有标题")
    state = read_current(contract)
    phase = phase or str(state.get("phase") or "P1")
    bug_id = _next_id(contract)
    item = {
        "id": bug_id,
        "title": title.strip(),
        "severity": severity,
        "status": "open",
        "roadmap": str(state.get("roadmap") or "R1"),
        "found_in": {
            "phase": phase,
            "task": task,
            "verification": verification,
        },
        "delivery": delivery,
        "related_reqs": related_reqs or [],
        "environment": environment,
        "steps": steps,
        "expected": expected,
        "actual": actual,
        "evidence": evidence or [],
        "fix_task": None,
        "root_cause": None,
        "changed_files": [],
        "regression": [],
        "resolution": None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    _save(contract / "bugs" / f"{bug_id}.yaml", item)
    refresh_current(contract)
    ledger_append(contract, {"event": "bug.add", "bug": bug_id, "severity": severity, "title": title})
    return item


def list_bugs(
    project: str | Path,
    *,
    status: str | None = None,
    severity: str | None = None,
    roadmap: str | None = None,
    active_only: bool = False,
) -> list[dict[str, Any]]:
    contract = resolve_contract(project)
    items = []
    for path in _paths(contract):
        try:
            data = _load(path)
        except BugError:
            continue
        if status and data.get("status") != status:
            continue
        if active_only and data.get("status") in {"closed", "deferred", "wontfix"}:
            continue
        if severity and data.get("severity") != severity:
            continue
        if roadmap and data.get("roadmap") not in {None, roadmap}:
            continue
        items.append(data)
    return items


def show_bug(project: str | Path, bug_id: str) -> dict[str, Any]:
    contract = resolve_contract(project)
    _, data = _find(contract, bug_id)
    return data


def linked_bug_ids(contract: Path, delivery: str | None = None) -> set[str]:
    """活动任务（in_progress）关联的 BUG：fixes + inputs.bugs（MFP-0024）。"""
    ids: set[str] = set()
    for path in sorted((contract / "roadmap").glob("*/phases/*/tasks/T*/TASK.yaml")):
        try:
            data = _load(path)
        except BugError:
            continue
        if data.get("status") != "in_progress":
            continue
        if delivery and data.get("delivery") and data.get("delivery") != delivery:
            continue
        ids.update(str(item) for item in data.get("fixes") or [] if item)
        inputs = data.get("inputs") or {}
        for item in inputs.get("bugs") or []:
            ids.add(str(item))
    return ids


def update_bug(
    project: str | Path,
    bug_id: str,
    *,
    status: str | None = None,
    severity: str | None = None,
    fix_task: str | None = None,
    root_cause: str | None = None,
    resolution: str | None = None,
) -> dict[str, Any]:
    contract = resolve_contract(project)
    path, data = _find(contract, bug_id)
    if status is not None:
        if status not in STATUSES:
            raise BugError(f"status 只能是 {'|'.join(STATUSES)}")
        data["status"] = status
    if severity is not None:
        if severity not in SEVERITIES:
            raise BugError(f"severity 只能是 {'|'.join(SEVERITIES)}")
        data["severity"] = severity
    if fix_task is not None:
        data["fix_task"] = fix_task
    if root_cause is not None:
        data["root_cause"] = root_cause
    if resolution is not None:
        data["resolution"] = resolution
    _save(path, data)
    refresh_current(contract)
    ledger_append(contract, {"event": "bug.update", "bug": bug_id, "status": data.get("status")})
    return data


def mark_fixed(contract: Path, bug_id: str, task_id: str) -> dict[str, Any] | None:
    """fix 任务验收后把关联 BUG 推进到 fixed。"""
    try:
        path, data = _find(contract, bug_id)
    except BugError:
        return None
    if data.get("status") in OPEN_STATUSES:
        data["status"] = "fixed"
        data["fix_task"] = task_id
        _save(path, data)
        refresh_current(contract)
        ledger_append(contract, {"event": "bug.fixed", "bug": bug_id, "task": task_id})
    return data


def close_bug(
    project: str | Path,
    bug_id: str,
    *,
    verification: str,
    resolution: str | None = None,
) -> dict[str, Any]:
    contract = resolve_contract(project)
    path, data = _find(contract, bug_id)
    if data.get("status") not in {"fixed", "verifying"}:
        raise BugError(f"BUG {bug_id} 当前状态 {data.get('status')} 不能 close；先 fixed/verifying")
    if not verification.strip():
        raise BugError("关闭 BUG 必须提供验证证据/说明")
    data["status"] = "closed"
    data["resolution"] = resolution or data.get("resolution") or "修复并通过验证"
    data["closed_at"] = _now()
    data["close_verification"] = verification
    _save(path, data)
    refresh_current(contract)
    ledger_append(contract, {"event": "bug.close", "bug": bug_id})
    return data


def open_blockers(project: str | Path) -> list[dict[str, Any]]:
    return [
        bug
        for bug in list_bugs(project)
        if bug.get("status") in OPEN_STATUSES and bug.get("severity") in {"blocker", "critical"}
    ]


def summary(project: str | Path) -> dict[str, Any]:
    items = list_bugs(project)
    counts: dict[str, int] = {}
    for item in items:
        key = str(item.get("severity"))
        counts[key] = counts.get(key, 0) + 1
    return {
        "open": [bug.get("id") for bug in items if bug.get("status") in OPEN_STATUSES],
        "by_severity": counts,
        "total": len(items),
    }
