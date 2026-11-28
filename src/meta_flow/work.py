"""工作包、任务区间、决策点与验证流（REQ-0019 / SPEC-FRAMEWORK R3/R8 / CHG-0005）。

工作包是每子项目每个设计周期的上下文容器：设计引用、SPEC、接口、
allowed_paths、预算与验收都在包内。任务只在“需要人工决策”或
“需要独立验证”时拆分；默认不按任务生成 review 任务，工作包完成做
子项目最终验证后由 manager 验收（CHG-0005）。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .state import ledger_append, read_current
from .workspace import resolve_contract

WORK_STATUSES = (
    "planned",
    "in_progress",
    "waiting_decision",
    "verifying",
    "done",
    "accepted",
    "blocked",
)
TASK_TYPES = ("implement", "verify", "decision", "spike", "bugfix", "document")
VERIFICATION_MODES = ("none", "peer", "independent", "designer", "manager")
DECISION_LEVELS = ("D0", "D1", "D2", "D3")
DECISION_OWNERS = ("user", "manager")
DECISION_ROLE_WORDS = {
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
DEFAULT_BUDGET = {"files": 60, "bytes": 1048576}


class WorkError(Exception):
    """工作包操作失败。"""

    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise WorkError(f"缺少文件: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise WorkError(f"{path} 不是合法 YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise WorkError(f"{path} 顶层必须是映射")
    return data


def _dump(path: Path, data: dict[str, Any]) -> None:
    data["updated_at"] = _now()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-")
    return cleaned or "sub"


def _work_root(contract: Path, roadmap: str, phase: str) -> Path:
    return contract / "roadmap" / roadmap / "phases" / phase / "work-packages"


def _work_paths(contract: Path) -> list[Path]:
    return sorted(
        (contract / "roadmap").glob("*/phases/*/work-packages/*/WORK-PACKAGE.yaml")
    )


def _next_seq(root: Path, subproject: str) -> int:
    numbers = []
    pattern = re.compile(rf"^.+WP-{re.escape(_slug(subproject))}-(\d{{2}})$")
    if root.is_dir():
        for item in root.iterdir():
            match = pattern.fullmatch(item.name)
            if match:
                numbers.append(int(match.group(1)))
    return max(numbers, default=0) + 1


def _actor_guard(
    contract: Path,
    data: dict[str, Any],
    *,
    actor_role: str | None,
    actor_delivery: str | None,
) -> None:
    """worker 只能访问本子项目 + 当前 R 的工作包（REQ-0020 版本隔离）。"""
    if actor_role != "worker":
        return
    if not actor_delivery:
        raise WorkError("worker 无交付绑定；请从子项目运行", 3)
    if str(data.get("subproject") or "") != str(actor_delivery):
        raise WorkError(
            f"worker 只能访问本子项目工作包: {actor_delivery}", 3
        )
    current = str(read_current(contract).get("roadmap") or "")
    if current and str(data.get("roadmap") or "") != current:
        raise WorkError(f"版本隔离：worker 只能访问当前路标 {current} 的工作包", 3)


def find_work_package(
    project: str | Path,
    wp_id: str,
    *,
    actor_role: str | None = None,
    actor_delivery: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    contract = resolve_contract(project)
    for path in _work_paths(contract):
        data = _load(path)
        if str(data.get("id") or path.parent.name) == wp_id:
            _actor_guard(
                contract, data, actor_role=actor_role, actor_delivery=actor_delivery
            )
            return path, data
    raise WorkError(f"工作包不存在: {wp_id}")


def list_work_packages(
    project: str | Path,
    *,
    subproject: str | None = None,
    status: str | None = None,
    actor_role: str | None = None,
    actor_delivery: str | None = None,
) -> list[dict[str, Any]]:
    contract = resolve_contract(project)
    current = str(read_current(contract).get("roadmap") or "")
    items = []
    for path in _work_paths(contract):
        try:
            data = _load(path)
        except WorkError:
            continue
        if actor_role == "worker":
            if not actor_delivery or str(data.get("subproject")) != str(actor_delivery):
                continue
            if current and str(data.get("roadmap")) != current:
                continue
        if subproject and data.get("subproject") != subproject:
            continue
        if status and data.get("status") != status:
            continue
        data["_path"] = str(path)
        items.append(data)
    return items


def validate_work_package(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if data.get("status") not in WORK_STATUSES:
        errors.append(f"status 必须是 {'|'.join(WORK_STATUSES)}")
    if not str(data.get("subproject") or "").strip():
        errors.append("缺少 subproject")
    scope = data.get("scope")
    if not isinstance(scope, dict) or not (
        scope.get("requirements") or scope.get("mfps") or scope.get("specs")
    ):
        errors.append("scope 至少需要 requirements/mfps/specs 之一")
    context = data.get("context")
    if not isinstance(context, dict):
        errors.append("缺少 context")
    else:
        if not context.get("allowed_paths"):
            errors.append("context.allowed_paths 不能为空")
        budget = context.get("budget")
        if not isinstance(budget, dict) or not budget.get("files") or not budget.get("bytes"):
            errors.append("context.budget 必须包含 files/bytes")
    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        errors.append("tasks 必须是列表")
    else:
        seen: set[str] = set()
        for task in tasks:
            if not isinstance(task, dict):
                errors.append("tasks 条目必须是映射")
                continue
            task_id = str(task.get("id") or "")
            if not task_id:
                errors.append("任务缺少 id")
            elif task_id in seen:
                errors.append(f"任务 id 重复: {task_id}")
            seen.add(task_id)
            if task.get("type") not in TASK_TYPES:
                errors.append(f"任务 {task_id} type 必须是 {'|'.join(TASK_TYPES)}")
            if task.get("verification") not in VERIFICATION_MODES:
                errors.append(
                    f"任务 {task_id} verification 必须是 {'|'.join(VERIFICATION_MODES)}"
                )
            if task.get("type") in {"implement", "document", "bugfix"} and not task.get(
                "acceptance"
            ):
                errors.append(f"任务 {task_id} 必须至少一条验收")
            if task.get("type") == "decision":
                decision = task.get("decision")
                if not isinstance(decision, dict):
                    errors.append(f"任务 {task_id} 是 decision 但缺少 decision 块")
                else:
                    for key in ("problem", "impact", "options", "recommendation", "level", "owner"):
                        if decision.get(key) in (None, "", []):
                            errors.append(f"决策 {task_id} 缺少 {key}")
                    if decision.get("level") not in DECISION_LEVELS:
                        errors.append(f"决策 {task_id} level 非法")
                    if decision.get("owner") not in DECISION_OWNERS:
                        errors.append(f"决策 {task_id} owner 非法")
            if task.get("type") == "verify" and not task.get("verifies"):
                errors.append(f"验证任务 {task_id} 缺少 verifies")
    verification = data.get("verification")
    if not isinstance(verification, dict):
        errors.append("缺少 verification")
    else:
        if verification.get("final") not in {"subproject-worker", "designer", "manager"}:
            errors.append("verification.final 必须是 subproject-worker|designer|manager")
        if verification.get("acceptance") != "manager":
            errors.append("verification.acceptance 必须是 manager（CHG-0005）")
    return errors


def create_work_package(
    project: str | Path,
    subproject: str,
    *,
    title: str | None = None,
    design_package: str | None = None,
    requirements: list[str] | None = None,
    mfps: list[str] | None = None,
    specs: list[str] | None = None,
    design_refs: list[str] | None = None,
    interface_refs: list[str] | None = None,
    must_read: list[str] | None = None,
    allowed_paths: list[str] | None = None,
    budget: dict[str, Any] | None = None,
    acceptance: list[Any] | None = None,
    phase: str = "P3",
    actor_role: str = "manager",
) -> dict[str, Any]:
    """manager 每子项目每设计周期创建一个工作包（CHG-0005）。"""
    if actor_role != "manager":
        raise WorkError("只有 manager 可以创建/验收工作包", 3)
    contract = resolve_contract(project)
    state = read_current(contract)
    roadmap = str(state.get("roadmap") or "R1")
    if design_package:
        # R7：实施工作包引用的设计包必须存在、已验收且同路标（INFO-FLOWS §7.4）。
        from . import design as design_module

        try:
            _, dp = design_module.find_design(contract, design_package)
        except design_module.DesignError as exc:
            raise WorkError(f"工作包引用的设计包不可用: {exc}") from exc
        if dp.get("status") != "accepted":
            raise WorkError(
                f"设计包 {design_package} 未验收（status={dp.get('status')}），不能创建实施工作包"
            )
        if str(dp.get("roadmap")) != roadmap:
            raise WorkError(
                f"设计包 {design_package} 路标 {dp.get('roadmap')} 与工作包 {roadmap} 不一致"
            )
    root = _work_root(contract, roadmap, phase)
    work_dir = root / f"{roadmap}-{phase}-WP-{_slug(subproject)}-{_next_seq(root, subproject):02d}"
    data = {
        "id": work_dir.name,
        "title": (title or f"{subproject} 工作包").strip(),
        "roadmap": roadmap,
        "phase": phase,
        "subproject": subproject,
        "design_package": design_package,
        "status": "planned",
        "scope": {
            "requirements": list(requirements or []),
            "mfps": list(mfps or []),
            "specs": list(specs or []),
        },
        "context": {
            "design_refs": list(design_refs or []),
            "interface_refs": list(interface_refs or []),
            "allowed_paths": list(allowed_paths or []),
            "must_read": list(must_read or []),
            "budget": dict(budget or DEFAULT_BUDGET),
        },
        "tasks": [],
        "acceptance": list(acceptance or []),
        "verification": {
            "final": "subproject-worker",
            "cross_project": None,
            "acceptance": "manager",
        },
        "audit": {
            "created_by": actor_role,
            "created_at": _now(),
        },
        "created_at": _now(),
        "updated_at": _now(),
    }
    errors = validate_work_package(data)
    if errors:
        raise WorkError("工作包不完整: " + "；".join(errors))
    path = work_dir / "WORK-PACKAGE.yaml"
    _dump(path, data)
    ledger_append(
        contract,
        {
            "event": "work_package.created",
            "work_package": data["id"],
            "subproject": subproject,
            "roadmap": roadmap,
        },
    )
    data["_path"] = str(path)
    return data


def _save(contract: Path, path: Path, data: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    _dump(path, data)
    ledger_append(contract, {"work_package": data.get("id"), **event})
    return data


def add_task(
    project: str | Path,
    wp_id: str,
    *,
    task_type: str,
    goal: str,
    acceptance: list[Any] | None = None,
    verification: str = "none",
    context: list[str] | None = None,
    decision: dict[str, Any] | None = None,
    verifies: list[str] | None = None,
    actor_role: str = "manager",
    actor_delivery: str | None = None,
) -> dict[str, Any]:
    if actor_role not in {"manager", "worker", "designer"}:
        raise WorkError("只有 manager/worker/designer 可以添加工作包任务", 3)
    contract = resolve_contract(project)
    path, data = find_work_package(
        contract, wp_id, actor_role=actor_role, actor_delivery=actor_delivery
    )
    if data.get("status") in {"accepted"}:
        raise WorkError(f"工作包 {wp_id} 已验收，不能追加任务")
    if task_type not in TASK_TYPES:
        raise WorkError(f"task_type 必须是 {'|'.join(TASK_TYPES)}")
    if verification not in VERIFICATION_MODES:
        raise WorkError(f"verification 必须是 {'|'.join(VERIFICATION_MODES)}")
    tasks = data.setdefault("tasks", [])
    task = {
        "id": f"T{len(tasks) + 1}",
        "type": task_type,
        "goal": goal.strip(),
        "context": list(context or []),
        "acceptance": list(acceptance or []),
        "verification": verification,
        "decision": decision,
        "verifies": list(verifies or []),
        "status": "planned",
    }
    if task_type == "decision":
        decision = decision or {}
        task["decision"] = {
            "problem": decision.get("problem"),
            "impact": decision.get("impact"),
            "options": decision.get("options") or [],
            "recommendation": decision.get("recommendation"),
            "level": decision.get("level"),
            "owner": decision.get("owner"),
            "decision": decision.get("decision"),
            "decided_by": decision.get("decided_by"),
            "decided_at": decision.get("decided_at"),
        }
    tasks.append(task)
    errors = validate_work_package(data)
    if errors:
        tasks.pop()
        raise WorkError("工作包任务不完整: " + "；".join(errors))
    _save(
        contract,
        path,
        data,
        {"event": "work_package.task_added", "task": task["id"], "type": task_type},
    )
    return task


def start_work_package(
    project: str | Path,
    wp_id: str,
    *,
    actor_role: str = "worker",
    actor_delivery: str | None = None,
) -> dict[str, Any]:
    contract = resolve_contract(project)
    path, data = find_work_package(
        contract, wp_id, actor_role=actor_role, actor_delivery=actor_delivery
    )
    if data.get("status") not in {"planned", "blocked"}:
        raise WorkError(f"工作包 {wp_id} 当前状态 {data.get('status')} 不能开始")
    if not data.get("tasks"):
        raise WorkError(f"工作包 {wp_id} 还没有任务；先 mf work task")
    data["status"] = "in_progress"
    return _save(contract, path, data, {"event": "work_package.started"})


def _validate_user_confirmation(confirmed_by: str | None, note: str | None) -> tuple[str, str]:
    confirmer = str(confirmed_by or "").strip()
    text = str(note or "").strip()
    if not confirmer:
        raise WorkError("D0/D1 决策必须记录用户确认人 --confirmed-by", 3)
    if confirmer.lower() in DECISION_ROLE_WORDS:
        raise WorkError(f"决策确认人不能是角色/系统身份: {confirmer}", 3)
    if not text:
        raise WorkError("D0/D1 决策必须记录确认意见 --note", 3)
    return confirmer, text


def request_decision(
    project: str | Path,
    wp_id: str,
    *,
    problem: str,
    impact: str,
    options: list[Any],
    recommendation: str,
    level: str,
    owner: str = "manager",
    actor_role: str = "worker",
    actor_delivery: str | None = None,
) -> dict[str, Any]:
    """插入决策点并暂停工作包（WORK-PACKAGES §5）。"""
    if not str(problem or "").strip() or not str(impact or "").strip():
        raise WorkError("决策点必须写 problem 与 impact")
    if not isinstance(options, list) or not options:
        raise WorkError("决策点必须至少一个选项 options")
    if not str(recommendation or "").strip():
        raise WorkError("决策点必须写 recommendation")
    if level not in DECISION_LEVELS:
        raise WorkError(f"level 必须是 {'|'.join(DECISION_LEVELS)}")
    if owner not in DECISION_OWNERS:
        raise WorkError(f"owner 必须是 {'|'.join(DECISION_OWNERS)}")
    if level in {"D0", "D1"} and owner != "user":
        raise WorkError("D0/D1 决策 owner 必须是 user（升级用户确认）")
    if level == "D2" and owner != "manager":
        raise WorkError("D2 决策 owner 必须是 manager")
    contract = resolve_contract(project)
    path, data = find_work_package(
        contract, wp_id, actor_role=actor_role, actor_delivery=actor_delivery
    )
    if data.get("status") not in {"planned", "in_progress", "waiting_decision"}:
        raise WorkError(f"工作包 {wp_id} 当前状态 {data.get('status')} 不能提交决策点")
    tasks = data.setdefault("tasks", [])
    task = {
        "id": f"T{len(tasks) + 1}",
        "type": "decision",
        "goal": problem.strip(),
        "context": [],
        "acceptance": [],
        "verification": "none",
        "decision": {
            "problem": problem,
            "impact": impact,
            "options": list(options),
            "recommendation": recommendation,
            "level": level,
            "owner": owner,
            "decision": None,
            "decided_by": None,
            "decided_at": None,
        },
        "verifies": [],
        "status": "open",
    }
    tasks.append(task)
    data["status"] = "waiting_decision"
    _save(
        contract,
        path,
        data,
        {
            "event": "work_package.decision_requested",
            "task": task["id"],
            "level": level,
            "owner": owner,
        },
    )
    return task


def record_decision(
    project: str | Path,
    wp_id: str,
    decision_id: str,
    *,
    decision: str,
    decided_by: str,
    actor_role: str = "manager",
    confirmed_by: str | None = None,
    note: str | None = None,
    actor_delivery: str | None = None,
) -> dict[str, Any]:
    """记录决策结果（D0/D1 用户确认；D2 manager；worker 不得代记）。"""
    if actor_role not in {"manager", "worker", "designer"}:
        raise WorkError("无法确定决策记录角色", 3)
    contract = resolve_contract(project)
    path, data = find_work_package(
        contract, wp_id, actor_role=actor_role, actor_delivery=actor_delivery
    )
    task = next(
        (item for item in data.get("tasks") or [] if str(item.get("id")) == decision_id),
        None,
    )
    if task is None or task.get("type") != "decision":
        raise WorkError(f"工作包 {wp_id} 没有决策任务 {decision_id}")
    block = task.setdefault("decision", {})
    if block.get("decision"):
        raise WorkError(f"决策 {decision_id} 已记录，不能重复")
    level = str(block.get("level") or "")
    owner = str(block.get("owner") or "")
    if not str(decision or "").strip():
        raise WorkError("决策结果不能为空")
    if level in {"D0", "D1"}:
        if actor_role != "manager":
            raise WorkError("D0/D1 决策只能由 manager 记录用户确认，worker/designer 不得代记", 3)
        confirmer, note_text = _validate_user_confirmation(confirmed_by, note)
        block["confirmed_by"] = confirmer
        block["confirmation_note"] = note_text
        decided_by = confirmer
    elif level == "D2":
        if actor_role != "manager":
            raise WorkError("D2 决策只允许 manager 记录", 3)
    # D3：自动决策，允许执行角色记录并审计
    block["decision"] = decision
    block["decided_by"] = decided_by
    block["decided_at"] = _now()
    task["status"] = "done"
    if data.get("status") == "waiting_decision":
        data["status"] = "in_progress"
    _save(
        contract,
        path,
        data,
        {
            "event": "work_package.decision_recorded",
            "task": decision_id,
            "decided_by": decided_by,
            "level": level,
            "owner": owner,
        },
    )
    return data


def start_verification(
    project: str | Path,
    wp_id: str,
    *,
    verifier: str = "another-worker",
    actor_role: str = "worker",
    actor_delivery: str | None = None,
) -> dict[str, Any]:
    contract = resolve_contract(project)
    path, data = find_work_package(
        contract, wp_id, actor_role=actor_role, actor_delivery=actor_delivery
    )
    if data.get("status") not in {"in_progress", "verifying"}:
        raise WorkError(f"工作包 {wp_id} 当前状态 {data.get('status')} 不能进入验证")
    data["status"] = "verifying"
    data.setdefault("verification", {})["verifier"] = verifier
    data["verification"]["started_at"] = _now()
    return _save(contract, path, data, {"event": "work_package.verification_started"})


def record_verification(
    project: str | Path,
    wp_id: str,
    *,
    result: str,
    evidence: list[str] | None = None,
    notes: str | None = None,
    actor_role: str = "worker",
    actor_delivery: str | None = None,
) -> dict[str, Any]:
    contract = resolve_contract(project)
    path, data = find_work_package(
        contract, wp_id, actor_role=actor_role, actor_delivery=actor_delivery
    )
    if data.get("status") != "verifying":
        raise WorkError(f"工作包 {wp_id} 当前状态 {data.get('status')} 不在验证中")
    normalized = result.upper()
    if normalized not in {"PASS", "PASS_WITH_RISK", "NEEDS_REWORK", "BLOCKED"}:
        raise WorkError("result 必须是 PASS|PASS_WITH_RISK|NEEDS_REWORK|BLOCKED")
    verification = data.setdefault("verification", {})
    verification["result"] = normalized
    verification["evidence"] = list(evidence or [])
    verification["notes"] = notes
    verification["verified_at"] = _now()
    if normalized in {"PASS", "PASS_WITH_RISK"}:
        data["status"] = "done"
    else:
        data["status"] = "in_progress"
    ledger_append(
        contract,
        {
            "event": "work_package.verified",
            "work_package": data.get("id"),
            "result": normalized,
        },
    )
    _dump(path, data)
    return data


def accept_work_package(
    project: str | Path,
    wp_id: str,
    *,
    verdict: str = "PASS",
    note: str | None = None,
    accepted_by: str = "manager",
    actor_role: str = "manager",
    actor_delivery: str | None = None,
) -> dict[str, Any]:
    """工作包完成：子项目最终验证后 manager 验收（CHG-0005）。"""
    if actor_role != "manager":
        raise WorkError("只有 manager 可以验收工作包", 3)
    contract = resolve_contract(project)
    path, data = find_work_package(
        contract, wp_id, actor_role=actor_role, actor_delivery=actor_delivery
    )
    if data.get("status") != "done":
        raise WorkError(
            f"工作包 {wp_id} 当前状态 {data.get('status')} 不能验收；先完成子项目最终验证"
        )
    if verdict not in {"PASS", "PASS_WITH_RISK", "NEEDS_REWORK", "BLOCKED"}:
        raise WorkError("verdict 必须是 PASS|PASS_WITH_RISK|NEEDS_REWORK|BLOCKED")
    data["status"] = "accepted" if verdict in {"PASS", "PASS_WITH_RISK"} else "in_progress"
    data["acceptance_result"] = {
        "verdict": verdict,
        "note": note,
        "accepted_by": accepted_by,
        "accepted_at": _now(),
    }
    return _save(
        contract,
        path,
        data,
        {"event": "work_package.accepted", "verdict": verdict, "accepted_by": accepted_by},
    )


def summary(project: str | Path) -> dict[str, Any]:
    items = list_work_packages(project)
    counts: dict[str, int] = {}
    for item in items:
        status = str(item.get("status") or "planned")
        counts[status] = counts.get(status, 0) + 1
    return {
        "total": len(items),
        "counts": counts,
        "items": [
            {"id": item.get("id"), "subproject": item.get("subproject"), "status": item.get("status")}
            for item in items
        ],
    }
