"""缺陷生命周期、修复关联与门禁查询（REQ-0018 / INFO-FLOWS §4 / SPEC-FRAMEWORK R6）。

两类 flow：

- ``external``：试运行/用户可见 BUG。状态
  open → triaged → in_fix → fixed → verified → pending_user_close → closed；
  关闭必须有用户显式确认（`--confirmed-by` + `--note`），closed 默认不可见。
- ``verification``：同一子项目实施期验证 BUG。状态
  open → in_fix → fixed → verified → closed；同子项目非修复者 viewer 复验关闭，
  不经过 manager/用户；跨子项目/接口/外部可见/安全/需求级升级 external。

兼容：历史 ``in_progress``/``verifying``/``reopened``/``wontfix`` 状态仍可读，
旧 API（fixed/verifying 直接 close）保留兼容，但新流程优先。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .state import ledger_append, read_current, refresh_current
from .workspace import resolve_contract

SEVERITIES = ("blocker", "critical", "major", "minor", "trivial")
FLOWS = ("external", "verification")
SCOPES = ("same_subproject", "cross_subproject")
EXTERNAL_STATUSES = (
    "open",
    "triaged",
    "in_fix",
    "fixed",
    "verified",
    "pending_user_close",
    "closed",
    "rejected",
    "duplicate",
    "deferred",
)
VERIFICATION_STATUSES = ("open", "in_fix", "fixed", "verified", "closed")
LEGACY_STATUSES = ("in_progress", "verifying", "reopened", "wontfix")
STATUSES = tuple(dict.fromkeys(EXTERNAL_STATUSES + VERIFICATION_STATUSES + LEGACY_STATUSES))
OPEN_STATUSES = {
    "open",
    "triaged",
    "in_fix",
    "fixed",
    "verified",
    "pending_user_close",
    "in_progress",
    "verifying",
    "reopened",
}
CLOSED_STATUSES = {"closed", "rejected", "duplicate", "deferred", "wontfix"}
CONFIRMER_ROLE_WORDS = {
    "manager",
    "designer",
    "worker",
    "maintainer",
    "ai",
    "system",
    "claude",
    "bot",
    "assistant",
}


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


def _hot_paths(contract: Path) -> list[Path]:
    """热区：legacy `bugs/`（当前过渡位置）+ 目标 `roadmap/R{n}/bugs/`。"""
    paths = sorted((contract / "bugs").glob("BUG-*.yaml"))
    paths.extend(sorted((contract / "roadmap").glob("*/bugs/BUG-*.yaml")))
    return paths


def _cold_paths(contract: Path) -> list[Path]:
    return sorted((contract / "archive").glob("*/bugs/BUG-*.yaml"))


def _paths(contract: Path, *, include_cold: bool = True) -> list[Path]:
    paths = _hot_paths(contract)
    if include_cold:
        paths.extend(_cold_paths(contract))
    return paths


def _find(contract: Path, bug_id: str) -> tuple[Path, dict[str, Any]]:
    for path in _hot_paths(contract):
        if path.stem == bug_id:
            return path, _load(path)
    for path in _cold_paths(contract):
        if path.stem == bug_id:
            return path, _load(path)
    raise BugError(f"缺陷不存在: {bug_id}")


def _next_id(contract: Path) -> str:
    numbers = [
        int(path.stem[4:]) for path in _paths(contract) if path.stem[4:].isdigit()
    ]
    return f"BUG-{max(numbers, default=0) + 1:04d}"


def _status_allowed(flow: str, status: str) -> bool:
    if flow == "verification":
        return status in VERIFICATION_STATUSES or status in LEGACY_STATUSES
    return status in EXTERNAL_STATUSES or status in LEGACY_STATUSES


def _validate_confirmation(confirmed_by: str | None, note: str | None) -> tuple[str, str]:
    confirmer = str(confirmed_by or "").strip()
    text = str(note or "").strip()
    if not confirmer:
        raise BugError("external BUG 关闭必须提供用户确认人 --confirmed-by", 3)
    if confirmer.lower() in CONFIRMER_ROLE_WORDS:
        raise BugError(
            f"确认人不能是角色/系统身份: {confirmer}；必须是真实用户确认记录", 3
        )
    if not text:
        raise BugError("external BUG 关闭必须提供 --note 用户确认意见", 3)
    return confirmer, text


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
    flow: str = "external",
    scope: str = "same_subproject",
    subproject: str | None = None,
    found_by: str | None = None,
) -> dict[str, Any]:
    contract = resolve_contract(project)
    if severity not in SEVERITIES:
        raise BugError(f"severity 只能是 {'|'.join(SEVERITIES)}")
    if not title.strip():
        raise BugError("BUG 必须有标题")
    if flow not in FLOWS:
        raise BugError(f"flow 只能是 {'|'.join(FLOWS)}")
    if scope not in SCOPES:
        raise BugError(f"scope 只能是 {'|'.join(SCOPES)}")
    if flow == "verification":
        if not subproject:
            raise BugError("verification BUG 必须指定同一子项目 --subproject")
        if scope != "same_subproject":
            raise BugError("verification BUG 的 scope 必须是 same_subproject（跨项目请升级 external）")
    state = read_current(contract)
    phase = phase or str(state.get("phase") or "P1")
    bug_id = _next_id(contract)
    item = {
        "id": bug_id,
        "title": title.strip(),
        "severity": severity,
        "status": "open",
        "flow": flow,
        "scope": scope,
        "subproject": subproject or delivery,
        "found_by": found_by or ("verification" if flow == "verification" else "manager"),
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
        "fix_owner": None,
        "verified_by": None,
        "closure_type": None,
        "confirmation": None,
        "escalated_from": None,
        "root_cause": None,
        "changed_files": [],
        "regression": [],
        "resolution": None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    _save(contract / "bugs" / f"{bug_id}.yaml", item)
    refresh_current(contract)
    ledger_append(
        contract,
        {
            "event": "bug.recorded",
            "bug": bug_id,
            "flow": flow,
            "severity": severity,
            "subproject": item.get("subproject"),
        },
    )
    return item


def list_bugs(
    project: str | Path,
    *,
    status: str | None = None,
    severity: str | None = None,
    roadmap: str | None = None,
    active_only: bool = False,
    flow: str | None = None,
    subproject: str | None = None,
    include_closed: bool = False,
) -> list[dict[str, Any]]:
    contract = resolve_contract(project)
    items: dict[str, dict[str, Any]] = {}
    for path in _paths(contract, include_cold=include_closed):
        try:
            data = _load(path)
        except BugError:
            continue
        bug_id = str(data.get("id") or path.stem)
        items.setdefault(bug_id, data)
    result = []
    for data in items.values():
        if status and data.get("status") != status:
            continue
        if active_only and data.get("status") not in OPEN_STATUSES:
            continue
        if severity and data.get("severity") != severity:
            continue
        if flow and data.get("flow", "external") != flow:
            continue
        if subproject and data.get("subproject") not in {subproject, None}:
            continue
        if roadmap and data.get("roadmap") not in {None, roadmap}:
            continue
        result.append(data)
    return result


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
    fix_owner: str | None = None,
    fix_session: str | None = None,
) -> dict[str, Any]:
    contract = resolve_contract(project)
    path, data = _find(contract, bug_id)
    flow = str(data.get("flow") or "external")
    if status is not None:
        if status not in STATUSES:
            raise BugError(f"status 只能是 {'|'.join(STATUSES)}")
        if not _status_allowed(flow, status):
            raise BugError(f"{flow} flow 不允许状态 {status}")
        data["status"] = status
    if severity is not None:
        if severity not in SEVERITIES:
            raise BugError(f"severity 只能是 {'|'.join(SEVERITIES)}")
        data["severity"] = severity
    if fix_task is not None:
        data["fix_task"] = fix_task
    if fix_owner is not None:
        data["fix_owner"] = fix_owner
    if fix_session is not None:
        data["fix_session"] = fix_session
    if root_cause is not None:
        data["root_cause"] = root_cause
    if resolution is not None:
        data["resolution"] = resolution
    _save(path, data)
    refresh_current(contract)
    ledger_append(contract, {"event": "bug.update", "bug": bug_id, "status": data.get("status")})
    return data


def mark_fixed(
    contract: Path, bug_id: str, task_id: str, *, fix_owner: str | None = None
) -> dict[str, Any] | None:
    """fix 任务验收后把关联 BUG 推进到 fixed。"""
    try:
        path, data = _find(contract, bug_id)
    except BugError:
        return None
    if data.get("status") in OPEN_STATUSES:
        data["status"] = "fixed"
        data["fix_task"] = task_id
        if fix_owner:
            data["fix_owner"] = fix_owner
        _save(path, data)
        refresh_current(contract)
        ledger_append(contract, {"event": "bug.fixed", "bug": bug_id, "task": task_id})
    return data


def verify_bug(
    project: str | Path,
    bug_id: str,
    *,
    by: str,
    evidence: list[str] | None = None,
    subproject: str | None = None,
    viewer_session: str | None = None,
) -> dict[str, Any]:
    """独立验证：external → pending_user_close；verification → verified。

    verification flow 必须有 fix_owner；viewer 不得等于修复者，且同一宿主会话
    （fix_session == viewer_session）不能自验（R0 会话绑定，残余风险见 dev-record）。
    """
    contract = resolve_contract(project)
    path, data = _find(contract, bug_id)
    flow = str(data.get("flow") or "external")
    if data.get("status") not in {"fixed", "verifying", "in_progress"}:
        raise BugError(f"BUG {bug_id} 当前状态 {data.get('status')} 不能验证；先 fixed")
    viewer = str(by or "").strip()
    if not viewer:
        raise BugError("验证必须提供验证者 --by", 3)
    if flow == "verification":
        fix_owner = str(data.get("fix_owner") or "").strip()
        if not fix_owner:
            raise BugError(
                f"verification BUG {bug_id} 缺少 fix_owner，不能验证；先 mf bug fix --by", 3
            )
        if viewer == fix_owner:
            raise BugError("verification BUG 不得由修复者本人复验（自验自关）", 3)
        fix_session = str(data.get("fix_session") or "").strip()
        if fix_session and viewer_session and str(viewer_session) == fix_session:
            raise BugError(
                "同一会话不能自验 verification BUG；请由另一会话/worker 复验", 3
            )
        if subproject and data.get("subproject") and str(data["subproject"]) != subproject:
            raise BugError(
                f"verification BUG 只能由同子项目 viewer 验证: {data.get('subproject')}", 3
            )
        data["status"] = "verified"
        data["verify_session"] = viewer_session
    else:
        data["status"] = "pending_user_close"
    data["verified_by"] = viewer
    if evidence:
        data.setdefault("verification_evidence", []).extend(evidence)
    _save(path, data)
    refresh_current(contract)
    ledger_append(contract, {"event": "bug.verified", "bug": bug_id, "by": viewer, "flow": flow})
    return data


def escalate_bug(
    project: str | Path, bug_id: str, *, reason: str, escalated_by: str = "worker"
) -> dict[str, Any]:
    """verification BUG 跨子项目/接口/外部可见/安全/需求级 → 升级 external。"""
    contract = resolve_contract(project)
    path, data = _find(contract, bug_id)
    if data.get("flow") != "verification":
        raise BugError(f"BUG {bug_id} 不是 verification flow，无需升级")
    if not str(reason or "").strip():
        raise BugError("升级 external 必须提供 --reason")
    data["escalated_from"] = "verification"
    data["flow"] = "external"
    data["scope"] = "cross_subproject"
    data["status"] = "triaged"
    data["escalation"] = {
        "reason": reason,
        "by": escalated_by,
        "at": _now(),
    }
    _save(path, data)
    refresh_current(contract)
    ledger_append(
        contract,
        {"event": "bug.escalated", "bug": bug_id, "reason": reason, "by": escalated_by},
    )
    return data


def close_bug(
    project: str | Path,
    bug_id: str,
    *,
    verification: str,
    resolution: str | None = None,
    confirmed_by: str | None = None,
    note: str | None = None,
    by: str | None = None,
    evidence: list[str] | None = None,
    subproject: str | None = None,
    viewer_session: str | None = None,
) -> dict[str, Any]:
    """关闭 BUG（两层门禁）。

    - external（新 schema，含 flow 字段）：仅 ``pending_user_close`` 可关，必须有
      用户确认人/意见；T038 前的历史 BUG（无 flow 字段）保留 fixed/verifying 兼容。
    - verification：必须由同子项目非修复者 viewer 关闭（closure_type=viewer），
      fix_owner 必须存在，同一会话不能自验自关。
    """
    contract = resolve_contract(project)
    path, data = _find(contract, bug_id)
    flow = str(data.get("flow") or "external")
    legacy_schema = "flow" not in data
    if data.get("status") == "closed":
        raise BugError(f"BUG {bug_id} 已关闭")
    if not str(verification or "").strip():
        raise BugError("关闭 BUG 必须提供验证证据/说明")
    status = str(data.get("status") or "")
    if flow == "verification":
        viewer = str(by or "").strip()
        if status != "verified":
            raise BugError(f"verification BUG {bug_id} 当前状态 {status} 不能关闭；先 verified", 3)
        if not viewer:
            raise BugError("verification BUG 关闭必须提供 viewer --by", 3)
        fix_owner = str(data.get("fix_owner") or "").strip()
        if not fix_owner:
            raise BugError(
                f"verification BUG {bug_id} 缺少 fix_owner，不能关闭；先 mf bug fix --by", 3
            )
        if viewer == fix_owner:
            raise BugError("verification BUG 不得由修复者本人关闭（自验自关）", 3)
        fix_session = str(data.get("fix_session") or "").strip()
        if fix_session and viewer_session and str(viewer_session) == fix_session:
            raise BugError(
                "同一会话不能关闭 verification BUG（自验自关）；请由另一会话/worker 复验", 3
            )
        if subproject and data.get("subproject") and str(data["subproject"]) != subproject:
            raise BugError(
                f"verification BUG 只能由同子项目 viewer 关闭: {data.get('subproject')}", 3
            )
        data["closure_type"] = "viewer"
        data["closed_by"] = viewer
        data["verified_by"] = data.get("verified_by") or viewer
        data["close_session"] = viewer_session
        if evidence:
            data.setdefault("verification_evidence", []).extend(evidence)
        confirmation = None
    else:
        if status == "pending_user_close":
            confirmer, confirmation_note = _validate_confirmation(confirmed_by, note)
            confirmation = {
                "confirmed_by": confirmer,
                "confirmed_at": _now(),
                "note": confirmation_note,
            }
            data["closure_type"] = "manager_user"
        elif legacy_schema and status in {"fixed", "verifying"}:
            # 仅 T038 前的历史 BUG（无 flow 字段）保留旧关闭路径。
            confirmation = None
            data["closure_type"] = "manager_user"
            data["legacy_close"] = True
        else:
            raise BugError(
                f"external BUG {bug_id} 当前状态 {status} 不能关闭；"
                "新 schema 必须 verified → pending_user_close 后由用户确认",
                3,
            )
        data["closed_by"] = "manager"
    data["status"] = "closed"
    data["resolution"] = resolution or data.get("resolution") or "修复并通过验证"
    data["closed_at"] = _now()
    data["close_verification"] = verification
    data["confirmation"] = confirmation
    _save(path, data)
    refresh_current(contract)
    ledger_append(
        contract,
        {
            "event": "bug.closed",
            "bug": bug_id,
            "flow": flow,
            "closure_type": data.get("closure_type"),
            "confirmed_by": (confirmation or {}).get("confirmed_by"),
        },
    )
    return data


def audit_bugs(contract: Path) -> list[str]:
    """状态一致性审计：直接改状态/绕过 CLI 的痕迹（N5）。"""
    issues: list[str] = []
    for path in _paths(contract, include_cold=True):
        try:
            data = _load(path)
        except BugError as exc:
            issues.append(f"{path.name}: {exc}")
            continue
        bug_id = str(data.get("id") or path.stem)
        flow = str(data.get("flow") or "external")
        status = str(data.get("status") or "")
        if status not in STATUSES:
            issues.append(f"{bug_id} 非法状态: {status}")
        if not _status_allowed(flow, status):
            issues.append(f"{bug_id} 状态 {status} 与 flow={flow} 不匹配")
        if status == "closed":
            legacy_schema = "flow" not in data
            if flow == "external" and not legacy_schema:
                if data.get("legacy_close"):
                    issues.append(
                        f"{bug_id} 新 schema external closed 不得走 legacy 兼容路径"
                    )
                if not data.get("confirmation"):
                    issues.append(f"{bug_id} external closed 缺少用户确认记录")
            if flow == "verification" and (
                data.get("closure_type") != "viewer" or not data.get("verified_by")
            ):
                issues.append(f"{bug_id} verification closed 缺少 viewer 复验记录")
    return issues


def open_blockers(project: str | Path) -> list[dict[str, Any]]:
    return [
        bug
        for bug in list_bugs(project, include_closed=False)
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
