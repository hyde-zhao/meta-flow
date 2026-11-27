"""任务卡、评审任务、提示词与验收状态机。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from . import bug, knowledge, roles
from .state import ledger_append, refresh_current, review_needs_rework, task_summary
from .workspace import (
    delivery_project_dir,
    load_current_state,
    registered_subprojects,
    resolve_contract,
)

TASK_ID_RE = re.compile(r"^(R\d+)-(P\d+)-T(\d{3})$")
RISKS = ("low", "medium", "high", "critical")
KINDS = ("implement", "design", "verify", "document", "review", "fix")
ACTIVE_STATUSES = {
    "draft",
    "ready",
    "in_progress",
    "submitted",
    "blocked",
    "rework",
    "rejected",
}
DEFAULT_REVIEW = {
    "low": "manager",
    "medium": "independent",
    "high": "independent",
    "critical": "user",
}
CHECKLIST = ["requirements", "design", "contracts", "tests", "security", "scope", "maintainability"]
SCOPE_MODES = ("single_subproject", "cross_subproject", "workspace")
SCOPE_OPERATIONS = {"read", "test", "release", "sync", "doctor"}
# TASK-CARD/MFP-0033：安全类任务负向矩阵必须覆盖的攻击面分组。
SECURITY_MATRIX_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("命令首词", ("命令首词", "首词", "首个可执行", "first token")),
    ("前缀命令", ("前缀命令", "前缀", "前置命令", "prefix")),
    ("参数伪装", ("参数伪装", "参数", "argument")),
    ("操作符/替换", ("操作符", "替换", "substitution", "&&", "$(")),
    ("跨项目", ("跨项目", "跨子项目", "其他子项目", "cross")),
    ("越界", ("越界", "越出", "outside")),
    ("module/subprocess/list", ("module", "subprocess", "list", "列表", "python -m")),
    ("alias/importlib/getattr/拼接", ("alias", "importlib", "getattr", "拼接")),
    ("cd/嵌套 shell/env/session_id", ("cd", "嵌套", "nested", "env", "环境变量", "session_id")),
)
SECURITY_NEGATIVE_WORDS = ("不", "禁", "拒绝", "不得", "不能", "only", "仅")
# 任务包预算档位（MFP-0007 A4）：按 effort 提供匹配档位，TASK.yaml 的
# packet_budget 显式值优先。
PACKET_BUDGET_TIERS: dict[str, dict[str, int]] = {
    "XS": {"files": 8, "bytes": 32768},
    "S": {"files": 10, "bytes": 65536},
    "M": {"files": 30, "bytes": 262144},
    "L": {"files": 50, "bytes": 524288},
    "XL": {"files": 60, "bytes": 1048576},
}


class TaskError(Exception):
    """任务操作失败。"""

    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _lease_expired(data: dict[str, Any]) -> bool:
    lease = data.get("lease") or {}
    raw = lease.get("expires_at")
    if not raw:
        return True
    try:
        return datetime.fromisoformat(str(raw)) <= datetime.now(UTC)
    except ValueError:
        return True


def _packet_budget(contract: Path, effort: str) -> dict[str, int]:
    """按任务 effort 选择任务包预算；CONTEXT-POLICY 可覆盖档位。"""
    key = str(effort or "M").upper()
    tiers = dict(PACKET_BUDGET_TIERS)
    policy_path = contract / "policies" / "CONTEXT-POLICY.yaml"
    if policy_path.is_file():
        try:
            policy_data = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            policy_data = {}
        if isinstance(policy_data, dict):
            for name, value in (policy_data.get("packet_budget_tiers") or {}).items():
                if isinstance(value, dict):
                    tiers[str(name).upper()] = {
                        "files": int(value.get("files", 10)),
                        "bytes": int(value.get("bytes", 65536)),
                    }
    return tiers.get(key, tiers["M"])


def _new_lease(owner: str = "worker", task_id: str | None = None, wave: str = "W1") -> dict[str, Any]:
    return {
        "owner": owner,
        "actor_id": os.environ.get("MF_WORKER_ID") or owner,
        "task": task_id,
        "wave": wave,
        "started_at": _now(),
        "expires_at": (datetime.now(UTC).replace(microsecond=0) + timedelta(hours=2)).isoformat(),
    }


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise TaskError(f"缺少文件: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise TaskError(f"{path} 不是合法 YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise TaskError(f"{path} 顶层必须是映射")
    return data


def _save(path: Path, data: dict[str, Any]) -> None:
    data["updated_at"] = _now()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _bundle(contract: Path, task_id: str) -> Path:
    match = TASK_ID_RE.fullmatch(task_id)
    if not match:
        raise TaskError(f"任务 ID 非法: {task_id}；应为 R1-P3-T001")
    roadmap, phase, num = match.groups()
    return contract / "roadmap" / roadmap / "phases" / phase / "tasks" / f"T{num}"


def _task_path(contract: Path, task_id: str) -> Path:
    return _bundle(contract, task_id) / "TASK.yaml"


def _next_num(tasks_dir: Path) -> int:
    numbers = [
        int(match.group(1))
        for path in tasks_dir.glob("T[0-9][0-9][0-9]")
        if (match := re.fullmatch(r"T(\d{3})", path.name))
    ]
    return max(numbers, default=0) + 1


def _task_scope(data: dict[str, Any]) -> dict[str, Any]:
    scope = data.get("scope")
    scope = scope if isinstance(scope, dict) else {}
    return {
        "mode": str(scope.get("mode") or "single_subproject"),
        "projects": [str(item) for item in scope.get("projects") or []],
        "operations": [str(item) for item in scope.get("operations") or []],
        "justification": scope.get("justification"),
    }


def _security_applies(data: dict[str, Any]) -> bool:
    security = data.get("security")
    return isinstance(security, dict) and bool(security.get("applies"))


def task_scope_errors(contract: str | Path, data: dict[str, Any]) -> list[str]:
    """校验任务子项目作用域（T033 A2）；兼容旧任务默认 single_subproject。"""
    scope = _task_scope(data)
    mode = scope["mode"]
    errors: list[str] = []
    if mode not in SCOPE_MODES:
        return [f"scope.mode 非法: {mode}"]
    registered = registered_subprojects(contract)
    known = {
        item["id"] for item in registered
    } | {
        str(item.get("delivery") or item["id"]) for item in registered
    }
    delivery = str(data.get("delivery") or "").strip()
    if mode == "single_subproject":
        if not delivery:
            # 兼容未注册子项目的单项目/历史工作区、design/review 合同层任务；
            # 注册了子项目的实现类任务必须绑定。
            if registered and data.get("kind") not in {"design", "review"}:
                errors.append("single_subproject 任务必须绑定 delivery")
        elif known and delivery not in known:
            errors.append(
                f"delivery={delivery} 未注册；已注册子项目: {', '.join(sorted(known))}"
            )
    elif mode == "cross_subproject":
        if not scope["projects"]:
            errors.append("cross_subproject 任务必须声明 scope.projects")
        unknown = [item for item in scope["projects"] if known and item not in known]
        if unknown:
            errors.append(f"scope.projects 含未注册子项目: {', '.join(unknown)}")
        if not scope["operations"]:
            errors.append("cross_subproject 任务必须声明 scope.operations")
        invalid = [item for item in scope["operations"] if item not in SCOPE_OPERATIONS]
        if invalid:
            errors.append(f"scope.operations 非法: {', '.join(invalid)}")
        if not str(scope["justification"] or "").strip():
            errors.append("cross_subproject 任务必须写 scope.justification")
    elif mode == "workspace":
        if not str(scope["justification"] or "").strip():
            errors.append("workspace 任务必须写 scope.justification")
    for field in ("project_dir", "allowed_paths_base"):
        raw = data.get(field)
        if raw and not Path(str(raw)).expanduser().is_dir():
            errors.append(f"{field} 不是有效目录: {raw}")
    return errors


def task_security_warnings(data: dict[str, Any]) -> list[str]:
    """安全类任务的非阻断项：负向矩阵攻击面覆盖不足/含正向期望。

    历史任务与新框架任务（如 WP-F2F3 流程安全）可能不覆盖全部 shell 攻击面；
    按 TASK-CARD“缺项时 validate/doctor 警告或拒绝”，作为 warning 输出。
    """
    if not _security_applies(data):
        return []
    security = data.get("security") or {}
    matrix = security.get("negative_matrix")
    if not isinstance(matrix, list) or not matrix:
        return []
    warnings: list[str] = []
    text = " ".join(
        " ".join(
            str(item.get(key) or "")
            for key in ("id", "category", "command", "expected", "evidence")
        )
        if isinstance(item, dict)
        else str(item)
        for item in matrix
    ).lower()
    missing = [
        label
        for label, keywords in SECURITY_MATRIX_GROUPS
        if not any(keyword.lower() in text for keyword in keywords)
    ]
    if missing:
        warnings.append("security.negative_matrix 覆盖不足: " + "、".join(missing))
    for item in matrix:
        if not isinstance(item, dict):
            continue
        expected = str(item.get("expected") or "").strip().lower()
        if expected in {"allow", "permit", "放行"}:
            warnings.append(
                f"security.negative_matrix.{item.get('id') or '?'} 期望为 allow（负向矩阵应为拒绝）"
            )
    return warnings


def task_security_errors(data: dict[str, Any]) -> list[str]:
    """校验安全类任务卡字段（TASK-CARD/MFP-0033/T033 A3）。

    仅对 `security.applies: true` 生效；历史 accepted 任务由 doctor 跳过，
    `mf task validate` 可显示警告。返回缺失/不满足项的人读说明。
    """
    if not _security_applies(data):
        return []
    security = data.get("security") or {}
    errors: list[str] = []
    threat = security.get("threat_model")
    if not isinstance(threat, dict):
        errors.append("security.threat_model 缺失")
        threat = {}
    for key, label in (
        ("assets", "资产"),
        ("attackers", "攻击者"),
        ("entry_points", "入口"),
        ("trust_boundary", "信任边界"),
        ("attacker_capabilities", "攻击者能力"),
    ):
        value = threat.get(key)
        if not isinstance(value, list) or not [item for item in value if str(item).strip()]:
            errors.append(f"security.threat_model.{key}（{label}）为空")
    uncovered = security.get("uncovered")
    if not isinstance(uncovered, list) or not [
        item for item in uncovered if str(item).strip()
    ]:
        errors.append("security.uncovered 必须明确不可防范围")
    if not str(security.get("risk_acceptor") or "").strip():
        errors.append("security.risk_acceptor 缺失")
    invariants = security.get("invariants")
    if not isinstance(invariants, list) or not invariants:
        errors.append("security.invariants 至少一条负面不变量")
    else:
        texts = " ".join(
            str(item.get("text") if isinstance(item, dict) else item)
            for item in invariants
        )
        if not any(word in texts for word in SECURITY_NEGATIVE_WORDS):
            errors.append("security.invariants 缺少负面不变量（不得/拒绝/不能等）")
        for item in invariants:
            if isinstance(item, dict) and not str(item.get("id") or "").strip():
                errors.append("security.invariants 条目缺少 id")
    matrix = security.get("negative_matrix")
    if not isinstance(matrix, list) or not matrix:
        errors.append("security.negative_matrix 为空")
    else:
        for item in matrix:
            if not isinstance(item, dict):
                errors.append("security.negative_matrix 条目必须是映射")
                continue
            for key in ("id", "category", "command", "expected"):
                if not str(item.get(key) or "").strip():
                    errors.append(f"security.negative_matrix 条目缺少 {key}")
    if security.get("fail_closed") is not True:
        errors.append("security.fail_closed 必须为 true（仅限可证明范围）")
    if not str(security.get("fail_closed_scope") or "").strip():
        errors.append("security.fail_closed_scope 缺失（写明可证明范围）")
    return errors


def _bind_task_delivery(
    contract: str | Path,
    delivery: str | None,
    mode: str,
    cwd: Path,
    *,
    kind: str = "implement",
) -> tuple[str | None, Path | None]:
    """解析/自动绑定任务 delivery 与工作目录（T033 A2）。"""
    registered = registered_subprojects(contract)
    known = {
        item["id"] for item in registered
    } | {
        str(item.get("delivery") or item["id"]) for item in registered
    }
    if delivery:
        if known and delivery not in known:
            raise TaskError(
                f"未知子项目 delivery={delivery}；已注册: {', '.join(sorted(known))}"
            )
        return delivery, delivery_project_dir(contract, delivery)
    if kind in {"design", "review"}:
        # design 在设计区/合同层执行，review 继承目标；不强制子项目工作目录。
        return None, None
    if mode != "single_subproject":
        return None, None
    if not registered:
        # 兼容单项目/历史工作区：未注册子项目时保留旧行为。
        return None, None
    cwd_path = cwd.expanduser().resolve()
    matches = [
        item
        for item in registered
        if cwd_path == item["path"] or item["path"] in cwd_path.parents
    ]
    if matches:
        selected = max(matches, key=lambda item: len(Path(item["path"]).parts))
        return selected["id"], Path(selected["path"])
    raise TaskError(
        "未指定 --delivery，且当前目录不在已注册子项目内；"
        f"已注册子项目: {', '.join(sorted(known))}"
    )


def _task_data(
    task_id: str,
    title: str,
    kind: str,
    roadmap: str,
    phase: str,
    *,
    delivery: str | None,
    risk: str,
    effort: str,
    review_mode: str,
    reviews: str | None,
    review_scope: list[str],
    allowed_paths: list[str],
    acceptance: list[Any],
    inputs: dict[str, Any],
    status: str,
    next_owner: str,
    owner_role: str | None = None,
    executor_role: str | None = None,
) -> dict[str, Any]:
    return {
        "id": task_id,
        "title": title,
        "kind": kind,
        "status": status,
        "owner_role": owner_role or ("designer" if kind == "design" else "worker"),
        "executor_role": executor_role
        or owner_role
        or ("designer" if kind == "design" else "worker"),
        "next_owner": next_owner,
        "roadmap": roadmap,
        "phase": phase,
        "delivery": delivery,
        "scope": {
            "mode": "single_subproject",
            "projects": [],
            "operations": [],
            "justification": None,
        },
        "project_dir": None,
        "allowed_paths_base": None,
        "security": {},
        "wave": "W1",
        "depends_on": [],
        "fixes": [],
        "lease": None,
        "effort": effort,
        "risk": {
            "level": risk,
            "score": None,
            "factors": {},
            "rationale": "",
        },
        "review": {
            "mode": review_mode,
            "scope": review_scope,
            "checklist": CHECKLIST,
        },
        "reviews": reviews,
        "reviewed_by_task": None,
        "review_verdict": None,
        # MFP-0020：任务卡最小机器字段（module/spec_ids/verification/evidence）
        "module": None,
        "spec_ids": [],
        "verification": {},
        "evidence": [],
        "inputs": inputs,
        "allowed_paths": allowed_paths,
        # 流程写入路径独立于 allowed_paths/forbidden；bundle 内文件由 guard 白名单授权
        "process_paths": ["handoff.md", "dev-record.md", "evidence/"],
        # 只约束交付工作区路径；contract bundle 流程文件由 process_paths 白名单授权
        "forbidden": ["contracts/**", "deliveries/**"],
        "deliverables": [],
        "acceptance": acceptance,
        "handoff": "required",
        "dev_record": "required" if kind != "review" else "optional",
        "created_at": _now(),
        "updated_at": _now(),
        "started_at": None,
        "submitted_at": None,
        "accepted_at": None,
        "rejection_reason": None,
    }


def create_task(
    project: str | Path,
    title: str,
    *,
    kind: str = "implement",
    delivery: str | None = None,
    risk: str = "medium",
    effort: str = "M",
    review_mode: str | None = None,
    reviews: str | None = None,
    review_scope: list[str] | None = None,
    allowed_paths: list[str] | None = None,
    acceptance: list[Any] | None = None,
    inputs: dict[str, Any] | None = None,
    wave: str = "W1",
    depends_on: list[str] | None = None,
    fixes: list[str] | None = None,
    module: str | None = None,
    spec_ids: list[str] | None = None,
    verification: dict[str, Any] | None = None,
    evidence: list[str] | None = None,
    owner_role: str | None = None,
    executor_role: str | None = None,
    owner_confirmed_by: str | None = None,
    scope_mode: str | None = None,
    scope_projects: list[str] | None = None,
    scope_operations: list[str] | None = None,
    scope_justification: str | None = None,
    security: dict[str, Any] | None = None,
    actor_role: str | None = None,
    cwd: str | Path | None = None,
    with_review: bool = True,
    from_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """创建任务卡；中高风险自动创建独立 review 任务。"""
    contract = resolve_contract(project)
    state = load_current_state(contract)
    roadmap = str(state.get("roadmap") or "R1")
    phase = str(state.get("phase") or "P1")

    data = dict(from_data or {})
    title = str(data.get("title") or title)
    kind = str(data.get("kind") or kind)
    risk = str(data.get("risk", {}).get("level") if isinstance(data.get("risk"), dict) else data.get("risk") or risk)
    if kind not in KINDS:
        raise TaskError(f"kind 只能是 {'|'.join(KINDS)}")
    if risk not in RISKS:
        raise TaskError(f"risk 只能是 {'|'.join(RISKS)}")

    mode = review_mode or (data.get("review") or {}).get("mode") or DEFAULT_REVIEW[risk]
    if mode not in {"manager", "independent", "user"}:
        raise TaskError("review.mode 只能是 manager|independent|user")
    if kind != "review" and risk in {"high", "critical"}:
        if not with_review:
            raise TaskError(f"{risk} 风险任务必须保留独立评审，不能 --no-review")
        if mode == "manager":
            raise TaskError(f"{risk} 风险任务不能降级为 manager 自审；使用 independent 或 user")
    scope = review_scope or (data.get("review") or {}).get("scope") or []
    acceptance = acceptance if acceptance is not None else data.get("acceptance") or []
    inputs = inputs if inputs is not None else data.get("inputs") or {}
    allowed = allowed_paths if allowed_paths is not None else data.get("allowed_paths") or []
    effort = str(data.get("effort") or effort)
    wave = str(data.get("wave") or wave or "W1")
    depends_on = [str(item) for item in (data.get("depends_on") or depends_on or [])]
    fixes = [str(item) for item in (data.get("fixes") or fixes or [])]
    module = str(data.get("module") or module or "") or None
    spec_ids = [str(item) for item in (data.get("spec_ids") or spec_ids or [])]
    if verification is None and isinstance(data.get("verification"), dict):
        verification = data["verification"]
    verification = verification or {}
    evidence = [str(item) for item in (data.get("evidence") or evidence or [])]

    # T033 A2：任务必须绑定子项目作用域；旧任务缺 scope 时按 single_subproject 兼容。
    raw_scope = data.get("scope")
    raw_scope = raw_scope if isinstance(raw_scope, dict) else {}
    scope_mode_value = str(
        scope_mode or raw_scope.get("mode") or "single_subproject"
    )
    projects = [
        str(item)
        for item in (scope_projects or raw_scope.get("projects") or [])
    ]
    operations = [
        str(item)
        for item in (scope_operations or raw_scope.get("operations") or [])
    ]
    justification = scope_justification or raw_scope.get("justification")
    if scope_mode_value not in SCOPE_MODES:
        raise TaskError(f"scope.mode 只能是 {'|'.join(SCOPE_MODES)}")
    if scope_mode_value != "single_subproject" and actor_role not in {None, "manager"}:
        raise TaskError("cross_subproject/workspace 作用域只能由 manager 创建")
    delivery, project_dir = _bind_task_delivery(
        contract,
        delivery,
        scope_mode_value,
        Path(cwd) if cwd is not None else Path.cwd(),
        kind=kind,
    )
    scope_data = {
        "mode": scope_mode_value,
        "projects": projects,
        "operations": operations,
        "justification": justification,
    }
    scope_probe = {
        "delivery": delivery,
        "kind": kind,
        "scope": scope_data,
        "project_dir": str(project_dir) if project_dir else None,
        "allowed_paths_base": str(project_dir) if project_dir else None,
    }
    scope_errors = task_scope_errors(contract, scope_probe)
    if scope_errors:
        raise TaskError("任务子项目作用域不完整: " + "；".join(scope_errors))

    # T033 A3：安全类任务在创建时即拒绝缺威胁模型/负向矩阵的卡。
    security_data = security if security is not None else data.get("security") or {}
    if security_data and not isinstance(security_data, dict):
        raise TaskError("security 必须是映射")
    if security_data.get("applies"):
        security_errors = task_security_errors({"security": security_data})
        if security_errors:
            raise TaskError(
                "安全类任务缺少必要字段: " + "；".join(security_errors)
            )

    # WP-F1/T033：责任主体与执行者分离（MFP-0035/ADR-007）。
    # design 默认 designer；implement/fix/document/verify 默认 worker；
    # review 由独立评审者（worker 身份）执行。非默认主责需 manager 显式确认。
    default_owner = "designer" if kind == "design" else "worker"
    requested_owner = str(data.get("owner_role") or owner_role or default_owner)
    requested_executor = str(
        data.get("executor_role") or executor_role or requested_owner
    )
    if requested_owner not in roles.ROLE_NAMES:
        raise TaskError(
            f"owner_role 只能是 {'|'.join(roles.ROLE_NAMES)}: {requested_owner}"
        )
    if requested_executor not in roles.ROLE_NAMES:
        raise TaskError(
            f"executor_role 只能是 {'|'.join(roles.ROLE_NAMES)}: {requested_executor}"
        )
    confirmed_by = str(
        data.get("owner_confirmed_by") or owner_confirmed_by or ""
    ).strip()
    owner_confirmation = None
    if requested_owner != default_owner:
        if not confirmed_by:
            raise TaskError(
                f"{kind} 任务责任主体默认为 {default_owner}；"
                f"改为 {requested_owner} 需 manager 显式确认（--owner-confirmed-by <manager/记录>）"
            )
        owner_confirmation = {
            "kind": kind,
            "owner_role": requested_owner,
            "executor_role": requested_executor,
            "confirmed_by": confirmed_by,
        }
    if requested_executor == "designer" and requested_owner != "designer":
        raise TaskError("designer 执行者只能对应 designer 责任主体")

    tasks_dir = contract / "roadmap" / roadmap / "phases" / phase / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    num = _next_num(tasks_dir)
    task_id = f"{roadmap}-{phase}-T{num:03d}"
    bundle = _bundle(contract, task_id)
    (bundle / "evidence").mkdir(parents=True, exist_ok=True)

    status = "ready" if acceptance else "draft"
    next_owner = requested_owner if status == "ready" else "manager"
    task = _task_data(
        task_id,
        title,
        kind,
        roadmap,
        phase,
        delivery=delivery,
        risk=risk,
        effort=effort,
        review_mode=mode,
        reviews=reviews,
        review_scope=scope,
        allowed_paths=allowed,
        acceptance=acceptance,
        inputs=inputs,
        status=status,
        next_owner=next_owner,
        owner_role=requested_owner,
        executor_role=requested_executor,
    )
    if isinstance(data.get("risk"), dict):
        task["risk"].update(data["risk"])
    task["wave"] = wave
    task["depends_on"] = depends_on
    task["fixes"] = fixes
    task["module"] = module
    task["spec_ids"] = spec_ids
    task["verification"] = verification
    task["evidence"] = evidence
    task["scope"] = scope_data
    task["project_dir"] = str(project_dir) if project_dir else None
    task["allowed_paths_base"] = str(project_dir) if project_dir else None
    task["security"] = security_data
    task["owner_role"] = requested_owner
    task["executor_role"] = requested_executor
    if owner_confirmation is not None:
        task["owner_confirmation"] = owner_confirmation
    if not task.get("packet_budget"):
        # 按 effort 档位分配；显式 packet_budget 优先（MFP-0007 A4）
        task["packet_budget"] = _packet_budget(contract, effort)

    review_id = None
    if kind != "review" and with_review and mode in {"independent", "user"}:
        review_num = num + 1
        review_id = f"{roadmap}-{phase}-T{review_num:03d}"
        review_bundle = _bundle(contract, review_id)
        (review_bundle / "evidence").mkdir(parents=True, exist_ok=True)
        review_task = _task_data(
            review_id,
            f"Review {task_id}: {title}",
            "review",
            roadmap,
            phase,
            delivery=delivery,
            risk=risk,
            effort="S",
            review_mode="manager",
            reviews=task_id,
            review_scope=scope,
            allowed_paths=[],
            acceptance=[
                {
                    "id": "R1",
                    "method": "artifact",
                    "target": "review-handoff.md",
                    "expect": "结论与必须整改项完整",
                }
            ],
            inputs={"tasks": [task_id]},
            status="draft",
            next_owner="manager",
        )
        review_task["depends_on"] = [task_id]
        review_task["wave"] = wave
        review_task["scope"] = scope_data
        review_task["project_dir"] = task["project_dir"]
        review_task["allowed_paths_base"] = task["allowed_paths_base"]
        _save(_task_path(contract, review_id), review_task)
        task["reviewed_by_task"] = review_id

    _save(_task_path(contract, task_id), task)
    ledger_append(
        contract,
        {
            "event": "task.create",
            "task": task_id,
            "review_task": review_id,
            "status": status,
            "from": None,
            "to": status,
            "wave": wave,
            "risk": risk,
            "owner_role": requested_owner,
            "executor_role": requested_executor,
        },
    )
    if owner_confirmation is not None:
        ledger_append(
            contract,
            {
                "event": "task.owner.confirm",
                "task": task_id,
                "kind": kind,
                "owner_role": requested_owner,
                "executor_role": requested_executor,
                "confirmed_by": confirmed_by,
            },
        )
    refresh_current(contract)
    return {
        "task": task_id,
        "review_task": review_id,
        "bundle": str(bundle),
        "status": status,
        "risk": risk,
        "review_mode": mode,
    }


def validate_task(project: str | Path, task_id: str) -> dict[str, Any]:
    """校验任务卡作用域、责任映射与安全字段（T033 A2/A3）。

    活跃任务缺项为 error；已 accepted/cancelled 的历史任务为 warning，
    与 TASK-CARD“历史任务警告并登记”一致。
    """
    contract = resolve_contract(project)
    _path, data = load_task(project, task_id)
    active = data.get("status") in ACTIVE_STATUSES
    errors: list[str] = []
    warnings: list[str] = []
    scope_messages = task_scope_errors(contract, data)
    security_messages = (
        task_security_errors(data) if data.get("kind") != "review" else []
    )
    security_warnings = (
        task_security_warnings(data) if data.get("kind") != "review" else []
    )
    owner = data.get("owner_role")
    executor = data.get("executor_role")
    mapping: list[str] = []
    if owner is not None and owner not in roles.ROLE_NAMES:
        mapping.append(f"owner_role 非法: {owner}")
    if executor is not None and executor not in roles.ROLE_NAMES:
        mapping.append(f"executor_role 非法: {executor}")
    if (
        data.get("kind") == "design"
        and executor is not None
        and owner
        and owner != "designer"
        and not data.get("owner_confirmation")
    ):
        mapping.append("design 责任主体非 designer 但缺少 manager 确认审计")
    for message in scope_messages + security_messages + mapping:
        (errors if active else warnings).append(message)
    warnings.extend(security_warnings)
    return {
        "task": task_id,
        "status": data.get("status"),
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
    }


def list_tasks(
    project: str | Path,
    *,
    status: str | None = None,
    delivery: str | None = None,
    active_only: bool = False,
) -> list[dict[str, Any]]:
    contract = resolve_contract(project)
    items = []
    for path in sorted((contract / "roadmap").glob("*/phases/*/tasks/T*/TASK.yaml")):
        try:
            data = _load(path)
        except TaskError:
            continue
        if status and data.get("status") != status:
            continue
        if active_only and data.get("status") not in ACTIVE_STATUSES:
            continue
        if delivery and data.get("delivery") and data.get("delivery") != delivery:
            continue
        data["_path"] = str(path)
        items.append(data)
    return items


def load_task(project: str | Path, task_id: str) -> tuple[Path, dict[str, Any]]:
    contract = resolve_contract(project)
    path = _task_path(contract, task_id)
    return path, _load(path)


def _task_display_dirs(
    contract: str | Path | None, data: dict[str, Any]
) -> tuple[str | None, str | None]:
    """返回任务显示用的工作目录与 allowed_paths 基准（旧任务动态回退）。"""
    base = data.get("allowed_paths_base") or data.get("project_dir")
    project_dir = data.get("project_dir") or base
    if not base and contract is not None:
        path = delivery_project_dir(contract, str(data.get("delivery") or "") or None)
        if path is not None:
            base = str(path)
            project_dir = project_dir or base
    return (str(project_dir) if project_dir else None, str(base) if base else None)


def summary_text(data: dict[str, Any], contract: str | Path | None = None) -> str:
    """生成任务人读摘要（MFP-0020）；不要求手工维护第二份状态。"""
    risk = (data.get("risk") or {}).get("level") or "-"
    acceptance = data.get("acceptance") or []
    modules = data.get("module") or "-"
    specs = ", ".join(str(item) for item in data.get("spec_ids") or []) or "-"
    lease = data.get("lease") or {}
    project_dir, base = _task_display_dirs(contract, data)
    scope = _task_scope(data)
    scope_text = scope["mode"]
    if scope["projects"]:
        scope_text += " [" + ", ".join(scope["projects"]) + "]"
    return "\n".join(
        [
            f"任务: {data.get('id')} [{data.get('status')}] kind={data.get('kind')} risk={risk}",
            f"标题: {data.get('title')}",
            f"模块/规格: {modules} / {specs}",
            f"交付库: {data.get('delivery') or '-'} wave={data.get('wave') or '-'}",
            f"子项目: delivery={data.get('delivery') or '-'} scope={scope_text}",
            f"工作目录: {project_dir or '-'}",
            f"allowed_paths 基准: {base or '-'}",
            f"责任: next_owner={data.get('next_owner')} "
            f"owner_role={data.get('owner_role') or '-'} "
            f"executor_role={data.get('executor_role') or '-'} "
            f"lease={lease.get('expires_at') or '-'}",
            f"验收: {len(acceptance)} 项"
            + (
                "（" + ", ".join(str(item.get('id')) for item in acceptance) + "）"
                if acceptance
                else ""
            ),
            f"关联: review={data.get('reviewed_by_task') or '-'} "
            f"fixes={', '.join(str(item) for item in data.get('fixes') or []) or '-'}",
        ]
    )


def _check_dependencies(contract: Path, task: dict[str, Any]) -> None:
    for dep in task.get("depends_on") or []:
        other = _find_task_data(contract, str(dep))
        if other is None:
            raise TaskError(f"依赖任务不存在: {dep}")
        if task.get("kind") == "review" and str(dep) == str(task.get("reviews")):
            if other.get("status") not in {"submitted", "accepted"}:
                raise TaskError(f"被评审任务 {dep} 尚未 submitted")
        elif other.get("status") != "accepted":
            raise TaskError(f"依赖任务 {dep} 尚未 accepted")


def _check_wave_conflicts(contract: Path, task: dict[str, Any]) -> None:
    wave = str(task.get("wave") or "W1")
    delivery = task.get("delivery")
    for path in sorted((contract / "roadmap").glob("*/phases/*/tasks/T*/TASK.yaml")):
        other = _load(path)
        if other.get("id") == task.get("id") or other.get("status") != "in_progress":
            continue
        if str(other.get("wave") or "W1") != wave:
            continue
        if delivery and other.get("delivery") and other.get("delivery") != delivery:
            continue
        if _paths_conflict(task, other):
            raise TaskError(
                f"同 wave {wave} 有写路径冲突：{task.get('id')} <-> {other.get('id')}；先串行化"
            )


def _actor_role() -> str:
    """当前执行者角色（CLI main 会注入 MF_ROLE；直接 API 默认 worker）。"""
    return roles.normalize_role(os.environ.get("MF_ROLE")) or "worker"


def _ensure_task_actor(task_id: str, data: dict[str, Any]) -> None:
    """design 任务只能由 designer 执行；designer 只能执行 design 任务。"""
    role = _actor_role()
    executor = str(data.get("executor_role") or data.get("owner_role") or "worker")
    if executor == "designer":
        if role != "designer":
            raise TaskError(
                f"design 任务 {task_id} 的执行者是 designer；{role} 不得冒充 designer"
                "（请在用户终端 mf role --as designer --reason <原因>）"
            )
    elif role == "designer":
        raise TaskError(
            f"任务 {task_id} 的执行者是 {executor}；designer 只能执行 design 任务"
        )


def start_task(
    project: str | Path,
    task_id: str,
    *,
    owner: str | None = None,
) -> dict[str, Any]:
    path, data = load_task(project, task_id)
    _ensure_task_actor(task_id, data)
    if data.get("kind") != "review":
        # T033 A3：安全类任务缺威胁模型/负向矩阵不得进入实施。
        security_errors = task_security_errors(data)
        if security_errors:
            raise TaskError(
                "安全类任务缺少必要字段，拒绝 start（先 mf task validate）: "
                + "；".join(security_errors)
            )
    status = data.get("status")
    stale_event: dict[str, Any] | None = None
    if status in {"rework", "rejected"}:
        needs_rework, _, _ = _needs_rework_link(project, data)
        if needs_rework:
            raise TaskError(
                f"任务 {task_id} 的关联 review 结论为 NEEDS_REWORK；"
                f"请用 mf task rework {task_id} 开始返工"
            )
        if status == "rework" or data.get("review_verdict") or isinstance(
            data.get("rework"), dict
        ):
            # R2：旧卡或中途 reject 可能残留 NEEDS_REWORK；以关联 review 当前状态为准，
            # 清理陈旧 verdict，避免 start/rework 双拒绝。
            previous = status
            if status == "rework":
                data["status"] = "rejected"
            data["next_owner"] = str(
                data.get("executor_role") or data.get("owner_role") or "worker"
            )
            data["lease"] = None
            reason = "关联 review 已不在 NEEDS_REWORK；start 清理陈旧 verdict"
            _clear_stale_rework(data, reason)
            status = str(data["status"])
            stale_event = {
                "event": "task.rework.stale",
                "task": task_id,
                "review_task": data.get("reviewed_by_task"),
                "reason": reason,
                "from": previous,
                "to": status,
            }
    if status == "in_progress" and not _lease_expired(data):
        lease = data.get("lease") or {}
        raise TaskError(f"任务 {task_id} 已被占用（lease 到 {lease.get('expires_at')}）")
    if status not in {"ready", "rejected", "in_progress"}:
        raise TaskError(f"任务 {task_id} 当前状态 {status} 不能 start")
    if data.get("kind") == "review" and data.get("reviews"):
        _, target = load_task(project, str(data["reviews"]))
        if target.get("status") != "submitted":
            raise TaskError(f"被评审任务 {data['reviews']} 尚未 submitted")
        actor = owner or os.environ.get("MF_WORKER_ID")
        if actor and actor not in {"worker"} and target.get("implemented_by") == actor:
            raise TaskError(f"评审者 {actor} 不能评审自己实现的任务 {data['reviews']}")
    contract = resolve_contract(project)
    _check_dependencies(contract, data)
    _check_wave_conflicts(contract, data)
    if stale_event is not None:
        ledger_append(contract, stale_event)
    if data.get("kind") != "review":
        project_path = Path(project).expanduser().resolve()
        exclude = contract if contract.is_relative_to(project_path) else None
        _save_worktree_snapshot(
            project_path,
            path.parent / "evidence" / "worktree-start.json",
            exclude,
        )
    executor = str(data.get("executor_role") or data.get("owner_role") or "worker")
    data["status"] = "in_progress"
    data["next_owner"] = executor
    data["started_at"] = _now()
    lease = _new_lease(owner or executor, task_id, str(data.get("wave") or "W1"))
    data["lease"] = lease
    _save(path, data)
    ledger_append(
        contract,
        {"event": "task.start", "task": task_id, "lease": lease["expires_at"], "owner": lease["owner"], "from": status, "to": "in_progress"},
    )
    refresh_current(contract)
    return data


def rework_task(
    project: str | Path,
    task_id: str,
    *,
    owner: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """开始 review NEEDS_REWORK 的返工（MFP-0015 E3）。

    仅允许从 review NEEDS_REWORK 触发；记录 review id、整改项、allowed_paths 与
    lease。worker 不得直接从 submitted 编辑/开始。
    """
    path, data = load_task(project, task_id)
    _ensure_task_actor(task_id, data)
    status = str(data.get("status"))
    if status == "submitted":
        raise TaskError(
            f"任务 {task_id} 处于 submitted；worker 不得直接开始；"
            "review 接受后 NEEDS_REWORK 会自动回流（所有风险级别）；"
            "若未自动回流，等 reviewer 补齐 rework_summary/范围声明，"
            "或由 manager 处理范围外事项"
        )
    if status not in {"rework", "rejected"}:
        raise TaskError(f"任务 {task_id} 当前状态 {status} 不能 rework")
    review_id = data.get("reviewed_by_task")
    if not review_id:
        raise TaskError(f"任务 {task_id} 没有关联 review 任务，不能走 rework；请用 mf task start")
    review_path, review_task = load_task(project, str(review_id))
    if not _review_task_needs_rework(review_task, review_path):
        raise TaskError(
            f"评审任务 {review_id} 当前状态 {review_task.get('status')}/"
            f"{review_task.get('review_verdict')}，不是 NEEDS_REWORK；"
            "请用 mf task start（会清理陈旧 verdict）或等待 review 裁决"
        )
    contract = resolve_contract(project)
    _check_dependencies(contract, data)
    _check_wave_conflicts(contract, data)
    project_path = Path(project).expanduser().resolve()
    exclude = contract if contract.is_relative_to(project_path) else None
    _save_worktree_snapshot(
        project_path,
        path.parent / "evidence" / "worktree-start.json",
        exclude,
    )
    scope = _read_rework_scope(review_path.parent)
    summary, summary_missing = _read_rework_summary(review_path.parent)
    existing = data.get("rework") if isinstance(data.get("rework"), dict) else {}
    lease = _new_lease(
        owner or str(data.get("executor_role") or data.get("owner_role") or "worker"),
        task_id,
        str(data.get("wave") or "W1"),
    )
    items = existing.get("items") or scope.get("items") or []
    data["rework"] = {
        "review_task": str(review_id),
        "review_verdict": "NEEDS_REWORK",
        "review_status": review_task.get("status"),
        "scope": existing.get("scope") or scope.get("scope"),
        "requires": existing.get("requires") or scope.get("requires") or [],
        "items": items,
        "allowed_paths": list(data.get("allowed_paths") or []),
        "rework_summary": existing.get("rework_summary") or summary,
        "summary_missing": existing.get("summary_missing") or summary_missing,
        "decision": existing.get("decision") or "manager",
        "auto": bool(existing.get("auto")),
        "reason": existing.get("reason"),
        "opened_at": existing.get("opened_at") or _now(),
        "started_at": _now(),
        "lease": lease["expires_at"],
        "lease_owner": lease["owner"],
        "notify": ["manager"],
        "note": note or existing.get("note"),
    }
    data["status"] = "in_progress"
    data["next_owner"] = str(
        data.get("executor_role") or data.get("owner_role") or "worker"
    )
    data["started_at"] = _now()
    data["lease"] = lease
    _save(path, data)
    ledger_append(
        contract,
        {
            "event": "task.rework",
            "task": task_id,
            "review_task": str(review_id),
            "review_status": review_task.get("status"),
            "decision": data["rework"]["decision"],
            "items": items,
            "allowed_paths": data["rework"]["allowed_paths"],
            "lease": lease["expires_at"],
            "lease_owner": lease["owner"],
            "notify": ["manager"],
            "from": status,
            "to": "in_progress",
        },
    )
    refresh_current(contract)
    return data


def _capture_diff(project: Path, target: Path, *, paths: list[str] | None = None) -> None:
    inside = subprocess.run(
        ["git", "-C", str(project), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
        check=False,
    )
    if inside.returncode != 0:
        return
    chunks = []
    for args in (["diff", "--binary"], ["diff", "--cached", "--binary"]):
        command = ["git", "-C", str(project), *args]
        if paths is not None:
            command.extend(["--", *paths])
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.stdout.strip():
            chunks.append(result.stdout)
    # 未跟踪新增文件不会出现在 git diff 中；按 owned 路径逐个生成 no-index diff，
    # 保证 evidence/diff.patch 覆盖任务实际新增文件（R4）。
    ls_args = ["ls-files", "--others", "--exclude-standard", "-z"]
    if paths is not None:
        ls_args.extend(["--", *paths])
    for name in _git_names(project, ls_args):
        result = subprocess.run(
            [
                "git",
                "-C",
                str(project),
                "diff",
                "--no-index",
                "--binary",
                "--",
                "/dev/null",
                name,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.stdout.strip():
            chunks.append(result.stdout)
    target.parent.mkdir(parents=True, exist_ok=True)
    # 即使无变更也固化空 diff，评审包可据此判断证据存在（R2）
    target.write_text("\n".join(chunks), encoding="utf-8")


def _git_names(project: Path, args: list[str]) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(project), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [item for item in result.stdout.split("\0") if item]


def _changed_files(
    project: Path,
    bundle: Path | None = None,
    exclude: Path | None = None,
) -> list[str] | None:
    snapshot_path = bundle / "evidence" / "worktree-start.json" if bundle else None
    if bundle is not None and snapshot_path is not None and snapshot_path.is_file():
        return _snapshot_changes(project, bundle, exclude)
    inside = subprocess.run(
        ["git", "-C", str(project), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
        check=False,
    )
    if inside.returncode != 0:
        return None
    names = set()
    for args in (
        ["diff", "--name-only", "-z"],
        ["diff", "--cached", "--name-only", "-z"],
        ["ls-files", "--others", "--exclude-standard", "-z"],
    ):
        names.update(_git_names(project, args))
    return sorted(names)


_SNAPSHOT_SKIP = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".meta-flow",
}


def _git_paths(project: Path, args: list[str]) -> set[str]:
    return set(_git_names(project, args))


def _ignored_paths(project: Path) -> set[str]:
    """gitignored 未跟踪路径（构建产物等），不进入任务快照（MFP-0030）。"""
    return _git_paths(project, ["ls-files", "--others", "--ignored", "--exclude-standard", "-z"])


def _untracked_paths(project: Path) -> set[str]:
    """task start 前已存在的未跟踪文件（不含 ignored）。"""
    return _git_paths(project, ["ls-files", "--others", "--exclude-standard", "-z"])


def _worktree_snapshot(project: Path, exclude: Path | None = None) -> dict[str, list[int]]:
    snapshot: dict[str, list[int]] = {}
    if not project.is_dir():
        return snapshot
    ignored = _ignored_paths(project)
    resolved_exclude = exclude.resolve() if exclude else None
    for path in project.rglob("*"):
        if not path.is_file() or any(part in _SNAPSHOT_SKIP for part in path.parts):
            continue
        if resolved_exclude is not None and path.resolve().is_relative_to(resolved_exclude):
            continue
        relative = str(path.relative_to(project))
        if relative in ignored:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        snapshot[relative] = [stat.st_mtime_ns, stat.st_size]
        if len(snapshot) >= 5000:
            break
    return snapshot


def _save_worktree_snapshot(project: Path, target: Path, exclude: Path | None = None) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(_worktree_snapshot(project, exclude), ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    # 记录 start 前已存在的未跟踪文件；提交时排除，避免既有构建产物阻塞（MFP-0030）
    meta = {
        "untracked": sorted(_untracked_paths(project)),
        "ignored": sorted(_ignored_paths(project)),
    }
    target.with_name("worktree-start-meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def _snapshot_changes(project: Path, bundle: Path, exclude: Path | None = None) -> list[str] | None:
    snapshot_path = bundle / "evidence" / "worktree-start.json"
    if not snapshot_path.is_file():
        return None
    try:
        before = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    before = {
        str(path): meta
        for path, meta in before.items()
        if not any(part in _SNAPSHOT_SKIP for part in Path(str(path)).parts)
    }
    # task start 前已存在的未跟踪文件与 gitignored 构建产物不阻塞提交（MFP-0030）
    pre_untracked: set[str] = set()
    meta_path = snapshot_path.with_name("worktree-start-meta.json")
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8")) or {}
        except json.JSONDecodeError:
            meta = {}
        if isinstance(meta, dict):
            pre_untracked = {str(item) for item in meta.get("untracked") or []}
    after = _worktree_snapshot(project, exclude)
    ignored_now = _ignored_paths(project)
    changed = set()
    for path, meta in after.items():
        if path not in before or list(meta) != list(before[path]):
            changed.add(path)
    for path in before:
        if path not in after:
            if path in ignored_now:
                # 旧快照可能包含 gitignored 安装镜像/构建产物；当前已忽略，不算变更
                continue
            changed.add(path)
    changed -= pre_untracked
    return sorted(changed)


def _parse_time(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw))
    except ValueError:
        return None


def _overlapping_tasks(contract: Path, current: dict[str, Any]) -> list[dict[str, Any]]:
    """返回与本任务活动窗口重叠的其他任务（MFP-0011）。

    并行任务在同一工作区各自 submit 时，按任务开始/提交时间判断重叠窗口，
    只隔离重叠窗口内、属于其他任务 allowed_paths 的变更；历史任务与单任务
    场景不做豁免，越界仍会被拒绝。
    """
    current_start = _parse_time(current.get("started_at"))
    if current_start is None:
        return []
    current_end = _parse_time(current.get("submitted_at")) or datetime.now(UTC)
    current_id = str(current.get("id") or "")
    others: list[dict[str, Any]] = []
    for path in sorted((contract / "roadmap").glob("*/phases/*/tasks/T*/TASK.yaml")):
        try:
            data = _load(path)
        except TaskError:
            continue
        if str(data.get("id") or "") == current_id:
            continue
        if data.get("status") not in {"in_progress", "submitted"}:
            continue
        other_start = _parse_time(data.get("started_at"))
        if other_start is None:
            continue
        other_end = _parse_time(data.get("submitted_at")) or datetime.now(UTC)
        if other_start < current_end and current_start < other_end:
            others.append(data)
    return others


def _task_diff_paths(project: Path, data: dict[str, Any]) -> list[str] | None:
    """任务证据 diff 的路径集合：所有 allowed 变更（不随返工快照重置）。

    越界/并行归属仍由快照 + ownership 校验；证据 diff 必须覆盖任务全生命周期，
    否则返工重提会漏掉返工前的已跟踪修改与未跟踪新增文件（R4）。
    """
    changed = _changed_files(project)
    if changed is None:
        return None
    forbidden = [str(item) for item in data.get("forbidden") or []]
    allowed = [str(item) for item in data.get("allowed_paths") or []]
    paths = []
    for path in changed:
        if _matches(path, forbidden):
            continue
        if not _matches(path, allowed):
            continue
        paths.append(path)
    return sorted(paths)


def _partition_changes(
    contract: Path,
    project: Path,
    data: dict[str, Any],
    bundle: Path,
    exclude: Path | None = None,
) -> tuple[list[str] | None, dict[str, str], list[str]]:
    """把本任务变更分为 owned / 其他并行任务归属 / 越界。

    返回 (owned, attributed, violations)；非 git 工作区返回 (None, {}, [])。
    """
    changed = _changed_files(project, bundle, exclude)
    if changed is None:
        return None, {}, []
    forbidden = [str(item) for item in data.get("forbidden") or []]
    allowed = [str(item) for item in data.get("allowed_paths") or []]
    others = _overlapping_tasks(contract, data)
    owned: list[str] = []
    attributed: dict[str, str] = {}
    violations: list[str] = []
    for path in changed:
        if _matches(path, forbidden):
            violations.append(f"{path} (forbidden)")
            continue
        if _matches(path, allowed):
            owned.append(path)
            continue
        owner = None
        for other in others:
            other_allowed = [str(item) for item in other.get("allowed_paths") or []]
            if other_allowed and _matches(path, other_allowed):
                owner = str(other.get("id") or "")
                break
        if owner:
            attributed[path] = owner
        else:
            violations.append(f"{path} (outside allowed_paths)")
    return owned, attributed, violations


def _validate_changed_paths(
    contract: Path,
    project: Path,
    data: dict[str, Any],
    bundle: Path,
    exclude: Path | None = None,
) -> list[str]:
    _, _, violations = _partition_changes(contract, project, data, bundle, exclude)
    return violations


def _glob_regex(pattern: str) -> re.Pattern[str]:
    raw = pattern.replace("\\", "/").strip()
    while raw.startswith("./"):
        raw = raw[2:]
    parts = ["^"]
    index = 0
    while index < len(raw):
        char = raw[index]
        if char == "*":
            if index + 1 < len(raw) and raw[index + 1] == "*":
                parts.append(".*")
                index += 2
            else:
                parts.append("[^/]*")
                index += 1
        elif char == "?":
            parts.append("[^/]")
            index += 1
        else:
            parts.append(re.escape(char))
            index += 1
    parts.append("$")
    return re.compile("".join(parts))


def _matches(path: str, patterns: list[str]) -> bool:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return any(_glob_regex(str(pattern)).match(normalized) for pattern in patterns)


BLOCKED_RE = re.compile(
    r"(?im)^\s*(?:结论|verdict|status|状态)\s*[:：=]\s*BLOCKED\b|^\s*BLOCKED\b"
)


def _handoff_blocked(path: Path) -> bool:
    """识别 handoff 结论为 BLOCKED（MFP-0026）。"""
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return bool(BLOCKED_RE.search(text))


def _process_file(
    project: Path,
    bundle: Path,
    task_id: str,
    explicit: str | Path | None,
    name: str,
    subdir: str,
) -> Path:
    """解析流程文件：显式参数 > 任务 bundle > 交付库 .meta-flow 本地副本。"""
    if explicit:
        return Path(explicit)
    bundle_path = bundle / name
    local_path = project / ".meta-flow" / subdir / f"{task_id}.md"
    if bundle_path.is_file() or not local_path.is_file():
        return bundle_path
    return local_path


def submit_task(
    project: str | Path,
    task_id: str,
    *,
    handoff: str | Path | None = None,
    dev_record: str | Path | None = None,
    owner: str | None = None,
    blocked: bool | None = None,
) -> dict[str, Any]:
    path, data = load_task(project, task_id)
    _ensure_task_actor(task_id, data)
    if data.get("status") != "in_progress":
        raise TaskError(f"任务 {task_id} 当前状态 {data.get('status')} 不能 submit")
    lease = data.get("lease") or {}
    if owner and lease.get("owner") and lease.get("owner") != owner:
        raise TaskError(f"任务 {task_id} lease owner={lease.get('owner')}，与提交者 {owner} 不一致")
    actor = owner or os.environ.get("MF_WORKER_ID") or lease.get("actor_id") or lease.get("owner")
    contract = resolve_contract(project)
    project_path = Path(project).expanduser().resolve()
    exclude = contract if contract.is_relative_to(project_path) else None
    bundle = path.parent
    owned: list[str] | None = None
    attributed: dict[str, str] = {}
    if data.get("kind") != "review":
        owned, attributed, violations = _partition_changes(
            contract, project_path, data, bundle, exclude
        )
        if violations:
            raise TaskError(
                "变更超出 allowed_paths/forbidden，拒绝提交：\n  - " + "\n  - ".join(violations)
            )
        if attributed:
            # 任务级 diff 隔离：记录被隔离到其他并行任务的路径，便于评审复核
            ownership = bundle / "evidence" / "ownership.json"
            ownership.parent.mkdir(parents=True, exist_ok=True)
            ownership.write_text(
                json.dumps(
                    {
                        "task": task_id,
                        "isolated_from": attributed,
                        "owned": owned or [],
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
    if data.get("kind") == "review":
        # MFP-0013：review 任务按 packet 指引只校验 review.md + review-handoff.md，
        # 不要求 handoff.md；implement/fix 仍校验 handoff/dev-record。
        for name in ("review.md", "review-handoff.md"):
            item = bundle / name
            if not item.is_file() or not item.read_text(encoding="utf-8").strip():
                raise TaskError(f"评审任务缺少 {name}")
        # MFP-0037：NEEDS_REWORK 必须写人话返工说明，缺失拒绝提交。
        if _read_review_verdict(bundle) == "NEEDS_REWORK":
            _, summary_missing = _read_rework_summary(bundle)
            if summary_missing:
                raise TaskError(
                    "review-handoff.md 结论 NEEDS_REWORK 时必须包含 rework_summary "
                    "人话说明：reason（返工原因）、risk（风险）、impact（问题影响）、"
                    "expectation（期望结果）；当前缺少 "
                    + ", ".join(summary_missing)
                    + "。补齐后再 mf task submit。"
                )
    else:
        handoff_path = _process_file(
            project_path, bundle, task_id, handoff, "handoff.md", "handoffs"
        )
        if not handoff_path.is_file() or not handoff_path.read_text(encoding="utf-8").strip():
            raise TaskError(f"缺少有效交接文件: {handoff_path}")
        if data.get("dev_record") == "required":
            dev_path = _process_file(
                project_path, bundle, task_id, dev_record, "dev-record.md", "dev-records"
            )
            if not dev_path.is_file() or not dev_path.read_text(encoding="utf-8").strip():
                raise TaskError(f"缺少开发记录: {dev_path}")

    # MFP-0026：BLOCKED 提交转 manager 裁决，不推进独立评审。
    # 显式 --blocked 优先；否则从 handoff 结论识别。
    is_blocked = False
    if data.get("kind") != "review":
        is_blocked = (
            bool(blocked) if blocked is not None else _handoff_blocked(handoff_path)
        )

    if data.get("kind") == "fix" and not is_blocked:
        fix_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (bundle / "dev-record.md", handoff_path)
            if path.is_file()
        )
        missing = [keyword for keyword in ("根因", "修复", "回归") if keyword not in fix_text]
        if missing:
            raise TaskError("fix 任务缺少交接章节关键字: " + "、".join(missing))

    if data.get("kind") != "review":
        # 证据 diff 覆盖任务全生命周期；越界/并行隔离仍由 owned + 快照校验
        evidence_paths = _task_diff_paths(Path(project).expanduser().resolve(), data)
        _capture_diff(
            Path(project).expanduser().resolve(),
            bundle / "evidence" / "diff.patch",
            paths=evidence_paths,
        )

    if is_blocked:
        contract = resolve_contract(project)
        data["status"] = "blocked"
        data["submitted_at"] = _now()
        if actor:
            data["implemented_by"] = actor
        data["next_owner"] = "manager"
        data["lease"] = None
        _save(path, data)
        ledger_append(
            contract,
            {
                "event": "task.blocked",
                "task": task_id,
                "next_owner": "manager",
                "from": "in_progress",
                "to": "blocked",
                "evidence_digest": _evidence_digest(bundle),
                "text": "worker BLOCKED 提交；请 manager 裁决改卡/扩 allowed_paths/CHG/新卡，"
                "评审任务不自动推进",
            },
        )
        refresh_current(contract)
        return data

    data["status"] = "submitted"
    data["submitted_at"] = _now()
    if actor:
        if data.get("kind") == "review":
            data["reviewed_by"] = actor
        else:
            data["implemented_by"] = actor
    if data.get("kind") == "review":
        data["next_owner"] = "manager"
    elif data.get("reviewed_by_task"):
        data["next_owner"] = "worker"
        review_path, review_task = load_task(project, str(data["reviewed_by_task"]))
        review_task["status"] = "ready"
        review_task["next_owner"] = "worker"
        # R1：新一轮复审开始前清理上一轮 verdict，避免 prompt/state 读陈旧值
        review_task["review_verdict"] = None
        review_task["accepted_at"] = None
        review_task["acceptance_note"] = None
        data["review_verdict"] = None
        _save(review_path, review_task)
    else:
        data["next_owner"] = "manager"
    data["lease"] = None
    _save(path, data)
    ledger_append(
        resolve_contract(project),
        {
            "event": "task.submit",
            "task": task_id,
            "next_owner": data["next_owner"],
            "from": "in_progress",
            "to": "submitted",
            "evidence_digest": _evidence_digest(bundle),
        },
    )
    if data.get("kind") == "review":
        review_verdict = _read_review_verdict(bundle)
        # MFP-0038：review 提交即触发目标回流，不等 manager accept。
        # MF_LEGACY_REWORK=1 保留旧 manager 裁决门一版（回滚通道）。
        if (
            review_verdict == "NEEDS_REWORK"
            and os.environ.get("MF_LEGACY_REWORK") != "1"
        ):
            rework_decision = _route_rework_from_review(
                project,
                task_id,
                path,
                data,
                review_verdict,
                trigger="submit",
            )
            if rework_decision is not None:
                data["rework_decision"] = rework_decision
                _save(path, data)
    refresh_current(resolve_contract(project))
    return data


REVIEW_VERDICT_RE = re.compile(
    r"verdict\s*[:=]\s*(PASS_WITH_RISK|PASS|NEEDS_REWORK|BLOCKED)", re.IGNORECASE
)


def _read_review_verdict(bundle: Path) -> str | None:
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


_WRAP_RE = r"(?:\*\*|__|`)?"


REWORK_SCOPE_RE = re.compile(
    rf"^\s*(?:>\s*|[-*]\s*)?{_WRAP_RE}rework_scope{_WRAP_RE}\s*[:=]\s*"
    rf"{_WRAP_RE}(in-scope|out-of-scope|disputed){_WRAP_RE}\s*$",
    re.IGNORECASE | re.MULTILINE,
)
REWORK_REQUIRES_RE = re.compile(
    rf"^\s*(?:>\s*|[-*]\s*)?{_WRAP_RE}rework_requires{_WRAP_RE}\s*[:=]\s*(.*?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
REWORK_ITEMS_RE = re.compile(
    rf"^\s*(?:>\s*|[-*]\s*)?{_WRAP_RE}rework_items{_WRAP_RE}\s*[:=]\s*(.*?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_REWORK_SECTION_RE = re.compile(
    r"^##\s*必须整改项\s*$(.*?)(?=^##\s|\Z)", re.MULTILINE | re.DOTALL
)
_REWORK_ITEM_ID_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[-_.][A-Za-z0-9]+)*")
# 支持 R1、R1a、M1a、BUG-0018、CHG-0004、T035 等整改项 ID（MFP-0037/0038）
_REWORK_ITEM_TOKEN_RE = re.compile(
    r"^([A-Za-z]{1,6}[A-Za-z0-9]*(?:-\d{1,4})?(?:\d{1,4}[A-Za-z]?)?)"
    r"(?=[\s:：、,，.。)）（(]|$)"
)
_REWORK_HEADING_RE = re.compile(r"^#{3,6}\s+(\S+)")
REWORK_SUMMARY_RE = re.compile(
    rf"^\s*(?:>\s*|[-*]\s*)?{_WRAP_RE}rework_summary{_WRAP_RE}\s*[:=]\s*(.*?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_REWORK_SUMMARY_DOTTED_RE = re.compile(
    r"^\s*(?:>\s*|[-*]\s*)?rework_summary[._]"
    r"(reason|risk|impact|expectation|原因|问题影响|影响|期望结果|期望)"
    r"\s*[:：=]\s*(.*?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
REWORK_SUMMARY_FIELD_RE = re.compile(
    r"^\s*(?:>\s*|[-*]\s*)?(?:rework_summary[._])?"
    r"(reason|risk|impact|expectation|原因|问题影响|影响|期望结果|期望)"
    r"\s*[:：=]\s*(.*?)\s*$",
    re.IGNORECASE,
)
_REWORK_SUMMARY_KEYS = ("reason", "risk", "impact", "expectation")
_REWORK_SUMMARY_ALIASES = {
    "reason": "reason",
    "原因": "reason",
    "risk": "risk",
    "风险": "risk",
    "impact": "impact",
    "影响": "impact",
    "问题影响": "impact",
    "expectation": "expectation",
    "期望": "expectation",
    "期望结果": "expectation",
}


def _split_rework_list(raw: str) -> list[str]:
    raw = raw.strip().strip("[]")
    if not raw or raw.lower() in {"none", "无", "-", "n/a"}:
        return []
    return [
        item.strip().strip("`*_")
        for item in re.split(r"[,，;\s]+", raw)
        if item.strip()
    ]


def _read_rework_scope(bundle: Path) -> dict[str, Any]:
    """解析 review-handoff 的整改范围声明（MFP-0015/MFP-0037）。

    缺少 rework_scope 或非 in-scope 时不自动回流；rework_requires 仅标注
    范围外事项，由 manager 另开单，不阻塞范围内返工。
    """
    path = bundle / "review-handoff.md"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    scope_match = REWORK_SCOPE_RE.search(text)
    requires_match = REWORK_REQUIRES_RE.search(text)
    items_match = REWORK_ITEMS_RE.search(text)
    requires = _split_rework_list(requires_match.group(1)) if requires_match else []
    items: list[str] = []
    if items_match:
        items.extend(_split_rework_list(items_match.group(1)))
    section = _REWORK_SECTION_RE.search(text)
    if section:
        for line in section.group(1).splitlines():
            raw = line.strip()
            if raw.startswith("|"):
                cells = [cell.strip() for cell in raw.strip("|").split("|")]
                cell = cells[0].strip("`*_ ") if cells else ""
                if not cell or cell.upper() == "ID" or set(cell) <= set("-: "):
                    continue
                if _REWORK_ITEM_ID_RE.fullmatch(cell):
                    items.append(cell)
                else:
                    # MFP-0038：表格首列允许 `R4（in-scope）` 等括号说明
                    token = _REWORK_ITEM_TOKEN_RE.match(cell)
                    if token:
                        items.append(token.group(1))
            elif raw.startswith(("-", "*")):
                body = raw.lstrip("-* ").strip().strip("`*_ ")
                if body.startswith("[") and "]" in body:
                    body = body.split("]", 1)[1].strip().strip("`*_ ")
                token = _REWORK_ITEM_TOKEN_RE.match(body)
                if token:
                    items.append(token.group(1))
    # MFP-0038：支持 `### R4（in-scope）` / `### R4(in-scope)` 小节（全角括号/无空格）
    for line in text.splitlines():
        raw = line.strip()
        if not raw.startswith("#"):
            continue
        heading = _REWORK_HEADING_RE.match(raw)
        if heading is None:
            continue
        token = _REWORK_ITEM_TOKEN_RE.match(heading.group(1))
        if token:
            items.append(token.group(1))
    deduped = list(dict.fromkeys(item for item in items if item))
    return {
        "scope": scope_match.group(1).lower() if scope_match else None,
        "requires": requires,
        "requires_declared": requires_match is not None,
        "items": deduped,
    }


def _clean_summary_value(raw: str) -> str:
    value = str(raw or "").strip().strip("`*_").strip()
    if not value or value.lower() in {"-", "none", "n/a", "todo", "待补", "待定"}:
        return ""
    if value.startswith("{") and value.endswith("}"):
        return ""
    if value.startswith("<") and value.endswith(">"):
        return ""
    return value


def _read_rework_summary(bundle: Path) -> tuple[dict[str, str], list[str]]:
    """解析 review-handoff/review 的人话返工说明（MFP-0037）。

    支持 inline 映射（``rework_summary: {reason: ..., risk: ...}``）、
    ``rework_summary:`` 后的缩进键值块，以及 ``rework_summary.reason: ...``
    独立行；中英文键名均可。返回 (字段值, 缺失字段列表)。
    """
    values: dict[str, str] = {}

    def record(name: str, raw: str) -> None:
        key = _REWORK_SUMMARY_ALIASES.get(str(name or "").strip().lower())
        value = _clean_summary_value(raw)
        if key and value:
            values.setdefault(key, value)

    for name in ("review-handoff.md", "review.md"):
        path = bundle / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for match in _REWORK_SUMMARY_DOTTED_RE.finditer(text):
            record(match.group(1), match.group(2))
        lines = text.splitlines()
        for index, line in enumerate(lines):
            match = REWORK_SUMMARY_RE.match(line)
            if not match:
                continue
            tail = match.group(1).strip()
            if tail.startswith("{"):
                for part in re.split(r"[,，;；]\s*", tail.strip("{}")):
                    field = REWORK_SUMMARY_FIELD_RE.match(part)
                    if field:
                        record(field.group(1), field.group(2))
                continue
            for follow in lines[index + 1 :]:
                if not follow.strip():
                    break
                stripped = follow.lstrip()
                if not (
                    follow.startswith((" ", "\t"))
                    or stripped.startswith((">", "-", "*"))
                ):
                    break
                field = REWORK_SUMMARY_FIELD_RE.match(follow)
                if field:
                    record(field.group(1), field.group(2))
    missing = [key for key in _REWORK_SUMMARY_KEYS if not values.get(key)]
    return values, missing


def _rework_plan(
    data: dict[str, Any],
    scope: dict[str, Any],
    *,
    summary_missing: list[str] | None = None,
    legacy: bool = False,
) -> dict[str, Any]:
    """判断 review NEEDS_REWORK 是否满足自动回流条件（MFP-0037）。

    新流程：所有风险级别直接回流实现 worker；``rework_requires``（needs）
    只做范围外标注，由 manager 另开单，不阻塞范围内返工。
    ``legacy=True`` 保留旧 manager 裁决门一版（高风险/新验收需 manager）。
    """
    reasons: list[str] = []
    risk = str((data.get("risk") or {}).get("level") or "")
    if legacy:
        if risk in {"high", "critical"}:
            reasons.append("高风险/关键任务保留 manager 裁决（--legacy-rework）")
        if not scope.get("requires_declared"):
            reasons.append("review-handoff 未声明 rework_requires（--legacy-rework）")
        elif scope.get("requires"):
            reasons.append(
                "需要新验收/BUG/MFP/CHG（--legacy-rework）: "
                + ", ".join(scope["requires"])
            )
    if str(data.get("status")) not in {"submitted", "rejected"}:
        reasons.append(f"任务状态 {data.get('status')} 不自动回流")
    if scope.get("scope") != "in-scope":
        reasons.append("整改项未声明全部在原 acceptance/scope 内（rework_scope: in-scope）")
    if summary_missing:
        reasons.append(
            "review-handoff 缺少 rework_summary 人话说明: "
            + ", ".join(summary_missing)
        )
    if not scope.get("items"):
        reasons.append("review-handoff 未列出必须整改项")
    return {"auto": not reasons, "reason": "；".join(reasons) or None}


def _review_task_needs_rework(
    review_task: dict[str, Any] | None,
    review_path: Path | None,
) -> bool:
    """判断关联 review 当前是否仍处于 NEEDS_REWORK（state 统一口径）。"""
    return review_needs_rework(
        review_task, review_path.parent if review_path is not None else None
    )


def _needs_rework_link(
    project: str | Path, data: dict[str, Any]
) -> tuple[bool, dict[str, Any] | None, Path | None]:
    review_id = data.get("reviewed_by_task")
    if not review_id:
        return False, None, None
    try:
        review_path, review_task = load_task(project, str(review_id))
    except TaskError:
        return False, None, None
    return _review_task_needs_rework(review_task, review_path), review_task, review_path


def _clear_stale_rework(data: dict[str, Any], reason: str) -> bool:
    """清理目标卡上的陈旧 review_verdict，并标记 rework 链接已失效。"""
    cleared = bool(data.get("review_verdict")) or isinstance(data.get("rework"), dict)
    data["review_verdict"] = None
    rework = data.get("rework")
    if isinstance(rework, dict):
        rework["stale"] = True
        rework["stale_reason"] = reason
    return cleared


def _active_rework_review(
    target: dict[str, Any], review_id: str
) -> dict[str, Any] | None:
    """目标已在返工（in_progress 且 rework 关联同一 review）时返回 rework 元数据。"""
    if target.get("status") != "in_progress":
        return None
    rework = target.get("rework")
    if not isinstance(rework, dict):
        return None
    if str(rework.get("review_task") or "") != str(review_id):
        return None
    return rework


def _evidence_digest(bundle: Path) -> str:
    digest = hashlib.sha256()
    for name in (
        "dev-record.md",
        "handoff.md",
        "review.md",
        "review-handoff.md",
        "evidence/diff.patch",
        "evidence/ownership.json",
    ):
        path = bundle / name
        if path.is_file():
            digest.update(name.encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def _route_rework_from_review(
    project: str | Path,
    review_id: str,
    review_bundle: Path,
    review_data: dict[str, Any],
    verdict: str,
    *,
    legacy_rework: bool = False,
    trigger: str = "submit",
) -> dict[str, Any] | None:
    """按评审结论处理目标实现任务；review submit/accept 共用（MFP-0038）。

    NEEDS_REWORK 范围门通过时，目标直接 rejected/rework、next_owner=实现
    worker，不依赖 manager accept；已开始的返工只确认，不回退状态。
    """
    target_id = review_data.get("reviews")
    if not target_id:
        return None
    target_path, target = load_task(project, str(target_id))
    target["review_verdict"] = verdict
    matched_rework = _active_rework_review(target, review_id)
    if matched_rework is not None:
        lease_valid = not _lease_expired(target)
        matched_rework["review_status"] = "accepted"
        matched_rework["review_verdict"] = verdict
        matched_rework["review_accepted_at"] = _now()
        target["next_owner"] = "worker" if lease_valid else "manager"
        lease = target.get("lease") if isinstance(target.get("lease"), dict) else {}
        decision = {
            "task": str(target_id),
            "auto": False,
            "already_in_progress": True,
            "lease_valid": lease_valid,
            "verdict": verdict,
            "reason": None,
            "items": matched_rework.get("items") or [],
            "allowed_paths": matched_rework.get("allowed_paths") or [],
            "status": target.get("status"),
            "next_owner": target.get("next_owner"),
            "lease": lease.get("expires_at"),
            "decision": matched_rework.get("decision"),
        }
        _save(target_path, target)
        ledger_append(
            resolve_contract(project),
            {
                "event": "task.rework.confirm",
                "task": str(target_id),
                "review_task": review_id,
                "verdict": verdict,
                "status": decision["status"],
                "next_owner": decision["next_owner"],
                "lease": decision["lease"],
                "lease_valid": lease_valid,
                "decision": decision["decision"],
                "notify": ["manager"],
                "trigger": trigger,
                "from": "in_progress",
                "to": "in_progress",
            },
        )
        return decision

    existing = target.get("rework")
    if (
        isinstance(existing, dict)
        and str(existing.get("review_task") or "") == str(review_id)
        and target.get("status") == "rework"
    ):
        # submit 已自动回流；accept 仅确认 verdict，不重复开单/计数
        _save(target_path, target)
        return {
            "task": str(target_id),
            "auto": bool(existing.get("auto")),
            "already_routed": True,
            "verdict": verdict,
            "reason": existing.get("reason"),
            "items": existing.get("items") or [],
            "allowed_paths": existing.get("allowed_paths") or [],
            "status": target.get("status"),
            "next_owner": target.get("next_owner"),
            "risk_level": str((target.get("risk") or {}).get("level") or ""),
            "requires": existing.get("requires") or [],
            "rework_summary": existing.get("rework_summary") or {},
            "summary_missing": existing.get("summary_missing") or [],
        }

    if verdict != "NEEDS_REWORK":
        target["next_owner"] = "manager"
        _save(target_path, target)
        return None

    target["next_owner"] = "manager"
    scope = _read_rework_scope(review_bundle.parent)
    summary, summary_missing = _read_rework_summary(review_bundle.parent)
    plan = _rework_plan(
        target,
        scope,
        summary_missing=summary_missing,
        legacy=legacy_rework,
    )
    target["rework"] = {
        "review_task": review_id,
        "review_verdict": verdict,
        "scope": scope.get("scope"),
        "requires": scope.get("requires") or [],
        "items": scope.get("items") or [],
        "allowed_paths": list(target.get("allowed_paths") or []),
        "rework_summary": summary,
        "summary_missing": summary_missing,
        "decision": "auto" if plan["auto"] else "manager",
        "auto": plan["auto"],
        "reason": plan["reason"],
        "opened_at": _now() if plan["auto"] else None,
        "notify": ["manager"],
        "lease": None,
    }
    if plan["auto"]:
        target["status"] = "rework"
        target["next_owner"] = "worker"
    _save(target_path, target)

    decision = {
        "task": str(target_id),
        "auto": plan["auto"],
        "reason": plan["reason"],
        "items": target["rework"]["items"],
        "allowed_paths": target["rework"]["allowed_paths"],
        "status": target.get("status"),
        "next_owner": target.get("next_owner"),
        "risk_level": str((target.get("risk") or {}).get("level") or ""),
        "requires": target["rework"]["requires"],
        "rework_summary": summary,
        "summary_missing": summary_missing,
    }
    contract = resolve_contract(project)
    if decision["auto"]:
        # 自动回流链路：submitted → rejected（范围门通过）→ rework
        ledger_append(
            contract,
            {
                "event": "task.reject",
                "task": str(target_id),
                "reason": "review NEEDS_REWORK：整改项在范围内，自动回流",
                "review_task": review_id,
                "auto": True,
                "trigger": trigger,
                "from": "submitted",
                "to": "rejected",
            },
        )
        ledger_append(
            contract,
            {
                "event": "task.rework.auto",
                "task": str(target_id),
                "review_task": review_id,
                "verdict": verdict,
                "risk_level": decision.get("risk_level"),
                "items": decision["items"],
                "allowed_paths": decision["allowed_paths"],
                "requires": decision.get("requires") or [],
                "next_owner": decision.get("next_owner"),
                "decision": "auto",
                "notify": ["manager"],
                "trigger": trigger,
                "from": "rejected",
                "to": "rework",
            },
        )
    ledger_append(
        contract,
        {
            "event": "task.rework.open"
            if decision["auto"]
            else "task.rework.decision_required",
            "task": str(target_id),
            "review_task": review_id,
            "decision": "auto" if decision["auto"] else "manager",
            "reason": decision["reason"],
            "items": decision["items"],
            "allowed_paths": decision["allowed_paths"],
            "notify": ["manager"],
            "trigger": trigger,
            "from": "rejected" if decision["auto"] else "submitted",
            "to": "rework" if decision["auto"] else "submitted",
        },
    )
    return decision


def accept_task(
    project: str | Path,
    task_id: str,
    *,
    verdict: str = "PASS",
    note: str | None = None,
    user_approved_by: str | None = None,
    legacy_rework: bool = False,
) -> dict[str, Any]:
    path, data = load_task(project, task_id)
    if data.get("status") != "submitted":
        raise TaskError(f"任务 {task_id} 当前状态 {data.get('status')} 不能 accept")
    if verdict not in {"PASS", "PASS_WITH_RISK", "NEEDS_REWORK", "BLOCKED"}:
        raise TaskError("verdict 非法")

    if data.get("kind") == "review":
        recorded = _read_review_verdict(path.parent)
        if recorded is None:
            raise TaskError("评审任务缺少 verdict：在 review-handoff.md 写明结论")
        if recorded != verdict:
            raise TaskError(f"评审文件结论为 {recorded}，与 accept verdict {verdict} 不一致")
        data["review_verdict"] = verdict
        data["status"] = "accepted"
        data["next_owner"] = "manager"
        data["accepted_at"] = _now()
        data["acceptance_note"] = note
        rework_decision = _route_rework_from_review(
            project,
            task_id,
            path,
            data,
            verdict,
            legacy_rework=legacy_rework,
            trigger="accept",
        )
        if rework_decision is not None and data.get("reviews"):
            data["rework_target"] = str(data["reviews"])
        _save(path, data)
        # 回流/确认 ledger 由 _route_rework_from_review 记录（MFP-0038）
        ledger_append(
            resolve_contract(project),
            {
                "event": "review.verdict",
                "review_task": task_id,
                "task": str(data.get("reviews") or "") or None,
                "verdict": verdict,
                "risk_level": (rework_decision or {}).get("risk_level"),
                "auto": bool(rework_decision.get("auto"))
                if isinstance(rework_decision, dict)
                else False,
                "next_owner": (rework_decision or {}).get("next_owner"),
                "from": "submitted",
                "to": "accepted",
            },
        )
        ledger_append(
            resolve_contract(project),
            {"event": "task.accept", "task": task_id, "kind": "review", "verdict": verdict, "from": "submitted", "to": "accepted"},
        )
        refresh_current(resolve_contract(project))
        if rework_decision is not None:
            data["rework_decision"] = rework_decision
        return data

    if str((data.get("risk") or {}).get("level")) == "critical" and not user_approved_by:
        raise TaskError("critical 任务需要用户验收：--user-approved-by <用户/记录>")
    if user_approved_by:
        data["user_approved_by"] = user_approved_by
        data["user_approved_at"] = _now()

    review_id = data.get("reviewed_by_task")
    if review_id:
        _, review_task = load_task(project, str(review_id))
        if review_task.get("status") != "accepted":
            raise TaskError(f"必须先接受 review 任务 {review_id}")
        if review_task.get("review_verdict") not in {"PASS", "PASS_WITH_RISK"}:
            raise TaskError(f"review 任务 {review_id} 结论不是 PASS")

    data["status"] = "accepted"
    data["next_owner"] = "manager"
    data["accepted_at"] = _now()
    data["acceptance_note"] = note
    data["acceptance_verdict"] = verdict
    _save(path, data)
    contract = resolve_contract(project)
    for bug_id in data.get("fixes") or []:
        bug.mark_fixed(contract, str(bug_id), task_id)
    ledger_append(
        contract,
        {"event": "task.accept", "task": task_id, "verdict": verdict, "fixes": data.get("fixes") or [], "from": "submitted", "to": "accepted"},
    )
    refresh_current(contract)
    return data


def reject_task(project: str | Path, task_id: str, reason: str) -> dict[str, Any]:
    if not reason.strip():
        raise TaskError("reject 必须给出原因")
    path, data = load_task(project, task_id)
    if data.get("status") not in {"submitted", "in_progress", "rework", "blocked"}:
        raise TaskError(f"任务 {task_id} 当前状态 {data.get('status')} 不能 reject")
    previous = str(data.get("status"))
    review_id = data.get("reviewed_by_task")
    review_path: Path | None = None
    review_task: dict[str, Any] | None = None
    needs_rework = False
    if review_id:
        review_path, review_task = load_task(project, str(review_id))
        needs_rework = _review_task_needs_rework(review_task, review_path)
    data["status"] = "rejected"
    data["next_owner"] = "worker"
    data["rejection_reason"] = reason
    data["lease"] = None
    cleared_stale = False
    if needs_rework and review_path is not None:
        # review 已裁决/提交 NEEDS_REWORK：保留评审结论作为 review→rework 链路，
        # 由 worker 用 mf task rework 开始；不再重置 review 任务。
        scope = _read_rework_scope(review_path.parent)
        existing = data.get("rework") if isinstance(data.get("rework"), dict) else {}
        data["rework"] = {
            "review_task": str(review_id),
            "review_verdict": "NEEDS_REWORK",
            "review_status": review_task.get("status") if review_task else None,
            "scope": existing.get("scope") or scope.get("scope"),
            "requires": existing.get("requires") or scope.get("requires") or [],
            "items": existing.get("items") or scope.get("items") or [],
            "allowed_paths": list(data.get("allowed_paths") or []),
            "decision": "manager",
            "auto": False,
            "reason": existing.get("reason"),
            "opened_at": existing.get("opened_at") or _now(),
            "decided_at": _now(),
            "notify": ["manager"],
            "note": reason,
            "lease": None,
        }
    elif review_id and review_path is not None and review_task is not None:
        review_task["status"] = "ready"
        review_task["next_owner"] = "worker"
        review_task["review_verdict"] = None
        review_task["accepted_at"] = None
        review_task["acceptance_note"] = None
        _save(review_path, review_task)
        # R2：review 重置时同步清理目标卡陈旧 verdict / rework 链接
        cleared_stale = _clear_stale_rework(
            data, "reject 重置 review 为 ready 时清理陈旧 verdict"
        )
    else:
        cleared_stale = _clear_stale_rework(
            data, "reject 时清理无 review 关联的陈旧 verdict"
        )
    _save(path, data)
    ledger_append(
        resolve_contract(project),
        {
            "event": "task.reject",
            "task": task_id,
            "reason": reason,
            "review_task": str(review_id) if needs_rework else None,
            "rework": "manager" if needs_rework else None,
            "cleared_stale_verdict": cleared_stale,
            "from": previous,
            "to": "rejected",
        },
    )
    refresh_current(resolve_contract(project))
    return data


def _find_task_data(contract: Path, task_id: str) -> dict[str, Any] | None:
    path = _task_path(contract, task_id)
    if not path.is_file():
        return None
    try:
        return _load(path)
    except TaskError:
        return None


def _deps_satisfied(contract: Path, task: dict[str, Any]) -> bool:
    for dep in task.get("depends_on") or []:
        other = _find_task_data(contract, str(dep))
        if other is None:
            return False
        if task.get("kind") == "review" and str(dep) == str(task.get("reviews")):
            if other.get("status") not in {"submitted", "accepted"}:
                return False
        elif other.get("status") != "accepted":
            return False
    return True


def _dependency_cycles(tasks: list[dict[str, Any]]) -> list[str]:
    """用 Kahn 拓扑排序找出依赖环或依赖环上的任务。"""
    ids = {str(task.get("id")) for task in tasks}
    deps = {
        str(task.get("id")): [str(dep) for dep in task.get("depends_on") or [] if str(dep) in ids]
        for task in tasks
    }
    reverse: dict[str, list[str]] = {task_id: [] for task_id in ids}
    indegree = {task_id: len(values) for task_id, values in deps.items()}
    for task_id, values in deps.items():
        for dep in values:
            reverse[dep].append(task_id)
    queue = [task_id for task_id, count in indegree.items() if count == 0]
    visited = []
    while queue:
        current = queue.pop()
        visited.append(current)
        for follower in reverse[current]:
            indegree[follower] -= 1
            if indegree[follower] == 0:
                queue.append(follower)
    return sorted(ids - set(visited))


def graph(project: str | Path) -> dict[str, Any]:
    tasks = list_tasks(project)
    nodes = []
    edges = []
    known = {str(task.get("id")) for task in tasks}
    for task in tasks:
        task_id = str(task.get("id"))
        nodes.append(
            {
                "id": task_id,
                "status": task.get("status"),
                "wave": task.get("wave") or "W1",
                "kind": task.get("kind"),
                "risk": (task.get("risk") or {}).get("level"),
            }
        )
        for dep in task.get("depends_on") or []:
            if str(dep) in known:
                edges.append({"from": str(dep), "to": task_id, "type": "depends_on"})
        if task.get("kind") == "review" and task.get("reviews"):
            edges.append({"from": str(task["reviews"]), "to": task_id, "type": "review"})
        rework = task.get("rework")
        if isinstance(rework, dict) and rework.get("review_task"):
            edges.append(
                {"from": str(rework["review_task"]), "to": task_id, "type": "rework"}
            )
    return {"nodes": nodes, "edges": edges, "cycles": _dependency_cycles(tasks)}


def _normalize_path(pattern: str) -> str:
    return pattern.rstrip("*").rstrip("/")


def _paths_conflict(left: dict[str, Any], right: dict[str, Any]) -> bool:
    for a in left.get("allowed_paths") or []:
        for b in right.get("allowed_paths") or []:
            na, nb = _normalize_path(str(a)), _normalize_path(str(b))
            if na and nb and (na == nb or na.startswith(nb + "/") or nb.startswith(na + "/")):
                return True
    return False


def plan_tasks(project: str | Path) -> dict[str, Any]:
    contract = resolve_contract(project)
    tasks = list_tasks(project)
    cycles = _dependency_cycles(tasks)
    if cycles:
        raise TaskError("任务依赖存在环: " + ", ".join(cycles))
    ready = []
    blocked = []
    for task in tasks:
        if task.get("status") not in {"ready", "rejected", "rework"}:
            continue
        item = {
            "id": task.get("id"),
            "title": task.get("title"),
            "wave": task.get("wave") or "W1",
            "kind": task.get("kind"),
            "risk": (task.get("risk") or {}).get("level"),
            "depends_on": task.get("depends_on") or [],
            "allowed_paths": task.get("allowed_paths") or [],
        }
        if _deps_satisfied(contract, task):
            ready.append(item)
        else:
            blocked.append(item)
    waves: dict[str, list[dict[str, Any]]] = {}
    for item in ready:
        waves.setdefault(str(item["wave"]), []).append(item)
    conflicts = []
    for wave, items in waves.items():
        for index, left in enumerate(items):
            for right in items[index + 1 :]:
                if _paths_conflict(left, right):
                    conflicts.append({"wave": wave, "a": left["id"], "b": right["id"]})
    return {"ready": ready, "blocked": blocked, "waves": waves, "conflicts": conflicts}


def next_tasks(project: str | Path, *, limit: int = 10) -> list[dict[str, Any]]:
    contract = resolve_contract(project)
    items = []
    for task in list_tasks(project):
        if task.get("status") not in {"ready", "rejected", "rework"}:
            continue
        if not _deps_satisfied(contract, task):
            continue
        items.append(
            {
                "id": task.get("id"),
                "title": task.get("title"),
                "wave": task.get("wave") or "W1",
                "kind": task.get("kind"),
                "risk": (task.get("risk") or {}).get("level"),
                "next_owner": task.get("next_owner"),
            }
        )
    items.sort(key=lambda item: (str(item["wave"]), str(item["id"])))
    return items[:limit]


def release_task(
    project: str | Path,
    task_id: str,
    *,
    reason: str = "lease 释放",
    force: bool = False,
) -> dict[str, Any]:
    path, data = load_task(project, task_id)
    if data.get("status") not in {"ready", "rejected", "in_progress"}:
        raise TaskError(f"任务 {task_id} 当前状态 {data.get('status')} 不能 release")
    previous = str(data.get("status"))
    if data.get("status") == "in_progress" and not _lease_expired(data) and not force:
        raise TaskError(f"任务 {task_id} lease 未过期；manager 回收需 --force")
    data["status"] = "ready"
    data["next_owner"] = "worker"
    data["lease"] = None
    data["release_reason"] = reason
    _save(path, data)
    ledger_append(
        resolve_contract(project),
        {"event": "task.release", "task": task_id, "reason": reason, "from": previous, "to": "ready"},
    )
    refresh_current(resolve_contract(project))
    return data


def summary(project: str | Path) -> dict[str, Any]:
    contract = resolve_contract(project)
    data = task_summary(contract)
    data["next"] = next_tasks(project, limit=5)
    data["open_bugs"] = len(bug.open_blockers(project))
    return data


def _bug_summary(contract: Path, bug_id: str) -> str | None:
    """关联 BUG 只读摘要（MFP-0024）：不要求 worker 用 Bash/expand 绕行。"""
    path = contract / "bugs" / f"{bug_id}.yaml"
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    evidence = data.get("evidence") or []
    related = data.get("related_reqs") or []
    lines = [
        f"### {bug_id} {data.get('title') or ''}".rstrip(),
        f"- severity/status: {data.get('severity')}/{data.get('status')}",
        f"- related_reqs: {', '.join(str(item) for item in related) or '-'}",
        f"- expected: {data.get('expected') or '-'}",
        f"- actual: {data.get('actual') or '-'}",
        f"- evidence: {', '.join(str(item) for item in evidence) or '-'}",
        f"- fix_task: {data.get('fix_task') or '-'}",
    ]
    return "\n".join(lines)


def _find_input(contract: Path, ref: str) -> tuple[Path, str] | None:
    # 先按 contract 相对路径精确解析（standards/templates/ADR 等任意目录），
    # 避免模糊匹配把 `standards/TASK-CARD.md` 解析成引用它的 CHG 文档。
    raw = Path(ref)
    if not raw.is_absolute():
        direct = (contract / raw).resolve()
        contract_root = contract.resolve()
        if (
            (direct == contract_root or contract_root in direct.parents)
            and direct.is_file()
        ):
            return direct, direct.read_text(encoding="utf-8")
    standards = contract / "standards" / f"{ref}.md"
    if standards.is_file():
        return standards, standards.read_text(encoding="utf-8")
    candidates: list[Path] = []
    for directory in ("requirements", "architecture", "specs", "improvements", "bugs"):
        base = contract / directory
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in {".md", ".yaml", ".yml", ".json"}:
                continue
            if "drafts" in path.parts or path.name.endswith(".bak"):
                continue
            if path.stat().st_size > 1024 * 1024:
                continue
            candidates.append(path)
            if ref in path.name:
                return path, path.read_text(encoding="utf-8")
    pattern = re.compile(rf"(?<![A-Za-z0-9_-]){re.escape(ref)}(?![A-Za-z0-9_-])")
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if pattern.search(text):
            return path, text
    return None


_ENTRY_SKIP = {
    ".git",
    ".claude",
    ".meta-flow",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
}


def _project_id(contract: Path) -> str | None:
    path = contract / "workspace" / "mf.workspace.yaml"
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    project = data.get("project") or {}
    return str(project.get("id") or "") or None


def _entry_index(
    project: Path,
    contract: Path,
    allowed_paths: list[str],
    *,
    limit: int = 20,
) -> tuple[list[str], int, int]:
    """按 allowed_paths 前缀生成代码入口清单（MFP-0007 A4）。"""
    roots: list[str] = []
    for pattern in allowed_paths:
        raw = str(pattern).replace("\\", "/").strip()
        if not raw:
            continue
        prefix = raw.split("*", 1)[0].rstrip("/")
        if not prefix or prefix in {".", "./"}:
            continue
        if prefix not in roots:
            roots.append(prefix)
    candidates: list[Path] = []
    resolved_contract = contract.resolve()
    for root in roots:
        target = (project / root).resolve()
        if not target.is_relative_to(project):
            continue
        if target == resolved_contract or resolved_contract in target.parents:
            continue
        if target.is_file():
            candidates.append(target)
        elif target.is_dir():
            for path in sorted(target.rglob("*")):
                if not path.is_file():
                    continue
                if any(part in _ENTRY_SKIP for part in path.relative_to(project).parts):
                    continue
                if path.resolve().is_relative_to(resolved_contract):
                    continue
                candidates.append(path)
                if len(candidates) >= 500:
                    break
    unique = sorted({path.resolve() for path in candidates})
    total_files = len(unique)
    total_bytes = sum(path.stat().st_size for path in unique)
    lines = []
    for path in unique[:limit]:
        relative = path.relative_to(project).as_posix()
        lines.append(f"  - {relative} ({path.stat().st_size}B)")
    if total_files > limit:
        lines.append(f"  - ... 其余 {total_files - limit} 个文件见 mf context expand / 源码树")
    return lines, total_files, total_bytes


def packet_text(project: str | Path, task_id: str, *, review: bool = False) -> str:
    contract = resolve_contract(project)
    project_path = Path(project).expanduser().resolve()
    path, data = load_task(project, task_id)
    bundle = path.parent
    review_target_id: str | None = None
    review_bundle = bundle
    if review:
        review_target_id = str(data.get("reviews") or "")
        if not review_target_id:
            raise TaskError(f"评审任务 {task_id} 缺少 reviews 目标，无法生成评审包")
        target_path, _target_data = load_task(project, review_target_id)
        review_bundle = target_path.parent
    budget = data.get("packet_budget") or _packet_budget(
        contract, str(data.get("effort") or "M")
    )
    if review and not data.get("packet_budget"):
        # 评审包额外嵌入被评审证据，默认至少 M 档预算
        review_budget = _packet_budget(contract, "M")
        if int(review_budget.get("bytes", 0)) > int(budget.get("bytes", 0)):
            budget = review_budget
    max_files = int(budget.get("files", 10))
    max_bytes = int(budget.get("bytes", 65536))
    input_refs = [
        str(ref)
        for refs in (data.get("inputs") or {}).values()
        for ref in (refs if isinstance(refs, list) else [refs])
    ]
    if len(input_refs) > max_files:
        raise TaskError(
            f"任务包输入文件数 {len(input_refs)} 超过预算 {max_files}；"
            "缩小 inputs、拆分任务或显式上调 TASK.yaml 的 packet_budget"
        )
    lines = [f"# {'REVIEW PACKET' if review else 'TASK PACKET'} {task_id}", ""]
    lines.append("## Read policy")
    lines.append(f"- must_read: TASK.yaml, {', '.join(input_refs) or '(none)'}")
    lines.append("- may_read: 自己的任务 bundle、allowed_paths；评审任务另加 review_scope")
    if review:
        lines.append(
            "- review_scope 内任意大小文件可 Read 或 `mf context expand --reason packet_missing` "
            "只读补读（写 READ-LOG）；review_scope 外仍拒绝"
        )
    lines.append(
        "- process_files: handoff.md / dev-record.md / evidence/ 由任务 bundle 白名单授权，"
        "独立于 allowed_paths/forbidden"
    )
    lines.append("- do_not_read: 其他任务、其他版本、archive、完整契约库")
    lines.append(f"- budget: files={max_files}, bytes={max_bytes}（effort={data.get('effort')}）")
    entry_lines, entry_files, entry_bytes = _entry_index(
        project_path, contract, [str(item) for item in data.get("allowed_paths") or []]
    )
    if entry_lines:
        lines.append("")
        lines.append("## Code entry index")
        lines.append("- 按 allowed_paths 前缀统计的相关源码/文档：")
        lines.extend(entry_lines)
        lines.append(f"- 合计: {entry_files} files / {entry_bytes}B")
        lines.append(
            "- 超预算提示: 使用 `mf context expand <path> --reason packet_missing` 分段读取"
            "（worker 限任务 bundle/被评审 bundle/allowed_paths，写入 READ-LOG），"
            "或拆分任务/在 TASK.yaml 上调 packet_budget"
        )
    lines.append("")
    lines.append("## Task")
    lines.append("```yaml")
    lines.append(yaml.safe_dump(data, sort_keys=False, allow_unicode=True).strip())
    lines.append("```")
    lines.append("")

    lines.append("## Inputs")
    inputs = data.get("inputs") or {}
    found_any = False
    for category, refs in inputs.items():
        if not isinstance(refs, list):
            refs = [refs]
        for ref in refs:
            found = _find_input(contract, str(ref))
            found_any = True
            if found is None:
                lines.append(f"- {category}/{ref}: 未找到")
                continue
            input_path, text = found
            snippet = text[:4000]
            lines.append(f"### {ref} ({input_path.relative_to(contract)})")
            lines.append("```text")
            lines.append(snippet)
            if len(text) > 4000:
                lines.append("... (truncated; expand with mf context)")
            lines.append("```")
    if not found_any:
        lines.append("(none)")
    # MFP-0024：fix 任务 fixes / inputs.bugs 关联 BUG 只读摘要纳入任务包
    bug_refs: list[str] = []
    for ref in data.get("fixes") or []:
        if str(ref) not in bug_refs:
            bug_refs.append(str(ref))
    for ref in (data.get("inputs") or {}).get("bugs") or []:
        if str(ref) not in bug_refs:
            bug_refs.append(str(ref))
    if bug_refs:
        lines.append("")
        lines.append("## Linked BUGs")
        for bug_id in bug_refs:
            summary = _bug_summary(contract, bug_id)
            if summary is None:
                lines.append(f"- {bug_id}: 未找到")
            else:
                lines.append(summary)

    lines.append("")
    lines.append("## Project knowledge")
    knowledge_lines = knowledge.packet_lines(
        contract,
        delivery=data.get("delivery"),
        task=data,
        project_id=_project_id(contract),
    )
    if knowledge_lines:
        lines.extend(knowledge_lines)
    else:
        lines.append("(none)")
    lines.append("")

    lines.append("## Process paths (explicit)")
    local_handoff = project_path / ".meta-flow" / "handoffs" / f"{task_id}.md"
    local_dev = project_path / ".meta-flow" / "dev-records" / f"{task_id}.md"
    if review:
        lines.append(f"- review: {bundle / 'review.md'}")
        lines.append(f"- review-handoff: {bundle / 'review-handoff.md'}")
    else:
        lines.append(f"- handoff: {bundle / 'handoff.md'}")
        lines.append(f"- dev-record: {bundle / 'dev-record.md'}")
    lines.append(f"- evidence: {bundle / 'evidence'}/")
    if not review:
        lines.append(f"- 本地副本（可选）: {local_handoff}")
        lines.append(f"- 本地副本（可选）: {local_dev}")
    lines.append(
        "- 以上流程路径由任务 bundle 白名单显式授权，与 allowed_paths/forbidden 独立；"
        "forbidden 仅约束交付工作区路径"
    )
    lines.append("")

    lines.append("## Allowed paths")
    for item in data.get("allowed_paths") or []:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Acceptance")
    for item in data.get("acceptance") or []:
        lines.append("```yaml")
        lines.append(yaml.safe_dump(item, sort_keys=False, allow_unicode=True).strip())
        lines.append("```")
    lines.append("")
    lines.append("## Handoff")
    if review:
        lines.append(f"- 写入: {bundle / 'review-handoff.md'}（另写 {bundle / 'review.md'}）")
        lines.append(f"- 提交: mf task submit {task_id}")
    else:
        lines.append(f"- 写入: {bundle / 'handoff.md'}（开发记录 {bundle / 'dev-record.md'}）")
        lines.append(
            f"- 提交: mf task submit {task_id} --handoff {bundle / 'handoff.md'}"
        )
        lines.append(
            f"- 本地副本可用: --handoff {local_handoff} --dev-record {local_dev}"
        )
    lines.append("")
    lines.append("## Responsibility")
    lines.append(f"- next_owner: {data.get('next_owner')}")
    lines.append(f"- owner_role: {data.get('owner_role') or '-'}")
    lines.append(f"- executor_role: {data.get('executor_role') or '-'}")
    lines.append(f"- delivery: {data.get('delivery') or '-'}")
    scope = _task_scope(data)
    scope_text = scope["mode"]
    if scope["projects"]:
        scope_text += " [" + ", ".join(scope["projects"]) + "]"
    lines.append(f"- scope: {scope_text}")
    project_dir, base = _task_display_dirs(contract, data)
    lines.append(f"- project_dir: {project_dir or '-'}")
    lines.append(f"- allowed_paths_base: {base or '-'}")
    lines.append(f"- risk: {(data.get('risk') or {}).get('level')}")
    lines.append(f"- review_mode: {(data.get('review') or {}).get('mode')}")
    if data.get("reviewed_by_task"):
        lines.append(f"- review_task: {data['reviewed_by_task']}")
    rework = data.get("rework")
    if isinstance(rework, dict):
        lines.append(
            f"- rework_decision: {rework.get('decision')} (auto={rework.get('auto')})"
        )
        lines.append(f"- rework_review: {rework.get('review_task')}")
        lines.append(
            "- rework_items: " + (", ".join(rework.get("items") or []) or "-")
        )
        lines.append(
            "- rework_allowed_paths: "
            + (", ".join(rework.get("allowed_paths") or []) or "-")
        )
    if data.get("reviews"):
        lines.append(f"- reviews: {data['reviews']}")
    lines.append(
        "- review_gate: 高风险任务由未参与实现的独立 reviewer 评审；实现者不自验收；"
        "结论仅 PASS|PASS_WITH_RISK|NEEDS_REWORK|BLOCKED；PASS_WITH_RISK 记录风险与接受人"
    )
    lines.append(
        f"- next_step: 每任务结束运行 mf task prompt {task_id} 明确下一责任 agent"
    )

    if review:
        lines.append("")
        lines.append(f"## Implementation Dev Record ({review_target_id})")
        dev = review_bundle / "dev-record.md"
        if not dev.is_file() or not dev.read_text(encoding="utf-8").strip():
            raise TaskError(f"评审包缺少被评审任务开发记录: {dev}")
        lines.append(dev.read_text(encoding="utf-8"))
        lines.append("")
        lines.append(f"## Implementation Handoff ({review_target_id})")
        handoff = review_bundle / "handoff.md"
        if not handoff.is_file() or not handoff.read_text(encoding="utf-8").strip():
            raise TaskError(f"评审包缺少被评审任务交接: {handoff}")
        lines.append(handoff.read_text(encoding="utf-8"))
        lines.append("")
        lines.append(f"## Diff ({review_target_id})")
        diff = review_bundle / "evidence" / "diff.patch"
        if not diff.is_file():
            raise TaskError(f"评审包缺少被评审任务 diff: {diff}")
        lines.append("```diff")
        lines.append(diff.read_text(encoding="utf-8")[:12000])
        lines.append("```")
        lines.append("")
        lines.append("## Review Output")
        lines.append(f"- 评审意见: {bundle / 'review.md'}")
        lines.append(f"- 评审交接: {bundle / 'review-handoff.md'}")

    text = "\n".join(lines).rstrip() + "\n"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    text += f"\npacket_digest: {digest}\n"
    if len(text.encode("utf-8")) > max_bytes:
        raise TaskError(
            f"任务包 {len(text.encode('utf-8'))} 字节超过预算 {max_bytes}；"
            "缩小 inputs、拆分任务，或使用 mf context expand <path> --reason packet_missing "
            "分段读取后再生成任务包"
        )
    target = bundle / ("review-packet.md" if review else "packet.md")
    target.write_text(text, encoding="utf-8")
    digest_name = "review-packet.sha256" if review else "packet.sha256"
    (bundle / digest_name).write_text(digest + "\n", encoding="utf-8")
    return text


def prompt_text(project: str | Path, task_id: str) -> str:
    _, data = load_task(project, task_id)
    status = str(data.get("status"))
    kind = str(data.get("kind"))
    risk = str((data.get("risk") or {}).get("level"))
    review_id = data.get("reviewed_by_task")
    review_task = None
    review_task_path: Path | None = None
    if review_id:
        review_task_path, review_task = load_task(project, str(review_id))
    bundle = _bundle(resolve_contract(project), task_id)

    if (
        status == "submitted"
        and kind != "review"
        and review_id
        and review_task
        and review_task.get("status") in {"ready", "in_progress", "rejected"}
    ):
        text = prompt_text(project, str(review_id))
        return f"parent_task: {task_id}\nreview_task: {review_id}\n\n{text}"

    if status == "draft":
        owner = "manager"
    elif status in {"ready", "in_progress", "rejected", "rework"}:
        owner = str(data.get("executor_role") or data.get("owner_role") or "worker")
    elif status == "submitted":
        if kind != "review" and review_task and review_task.get("status") in {"ready", "in_progress"}:
            owner = "worker"
        else:
            owner = "manager"
    else:
        owner = "manager"

    lines = [
        f"responsible_agent: {owner}",
        f"task: {task_id}",
        f"kind: {kind}",
        f"status: {status}",
        f"risk: {risk}",
        f"next_owner: {data.get('next_owner')}",
        f"owner_role: {data.get('owner_role') or '-'}",
        f"executor_role: {data.get('executor_role') or '-'}",
        f"delivery: {data.get('delivery') or '-'}",
        f"project_dir: {_task_display_dirs(resolve_contract(project), data)[0] or '-'}",
        f"allowed_paths_base: {_task_display_dirs(resolve_contract(project), data)[1] or '-'}",
        "",
    ]
    if owner == "worker":
        if kind == "review":
            lines.extend(
                [
                    f"你是独立评审者，不得是实现者。先运行：mf task show {task_id} --review-packet",
                    "只读任务包、diff、开发记录、交接和 review_scope 内源码；不要修改实现代码或验收标准。",
                    "review_scope 内任意大小文件可 Read 或 mf context expand --reason packet_missing 只读补读"
                    "（写 READ-LOG）；review_scope 外仍拒绝。",
                    f"在 {bundle / 'review.md'} 写评审意见，在 {bundle / 'review-handoff.md'} 写评审交接。",
                    "结论只能是 PASS / PASS_WITH_RISK / NEEDS_REWORK / BLOCKED；"
                    "PASS_WITH_RISK 必须写风险与接受人。",
                    "通过：结论 PASS，然后 mf task submit；由 manager 验收。",
                    "不通过：结论 NEEDS_REWORK，列出必须整改项（ID/文件/行/要求/验收方法），submit；"
                    "manager 接受 review 后，实现任务自动回流 worker 返工（所有风险级别），无需 manager 退回。",
                    "NEEDS_REWORK 时必须写 rework_summary 人话说明：reason（返工原因）、risk（风险）、"
                    "impact（问题影响）、expectation（期望结果）；缺失会被拒绝提交。",
                    "必须整改项可用表格或 `### R1/M1a/BUG-0018 ...` 小节；"
                    "review-handoff.md 声明 rework_scope: in-scope|out-of-scope|disputed；"
                    "范围外事项用 rework_requires: acceptance,bug,mfp,chg 标注，"
                    "manager 另开单，不阻塞范围内返工。",
                    "下一环节写 worker 直接重做（mf task rework）；不得留空。",
                ]
            )
        elif status == "rework":
            if not _review_task_needs_rework(review_task, review_task_path):
                lines.extend(
                    [
                        "关联 review 已不在 NEEDS_REWORK（可能已重置 ready）；",
                        f"请运行 mf task start {task_id} 清理陈旧 verdict 并恢复，不要用 mf task rework。",
                    ]
                )
            else:
                lines.extend(
                    [
                        "review 结论 NEEDS_REWORK，整改项在原验收/范围内，已自动回流（所有风险级别）。",
                        "先读取 review.md 和 review-handoff.md，只整改必须整改项。",
                        f"运行 mf task rework {task_id} 开始（记录 review id、整改项、allowed_paths 与 lease；不要用 mf task start）。",
                        "worker 不得从 submitted 直接开始；提交后不可继续编辑。",
                        f"完成后更新 {bundle / 'dev-record.md'} 和 {bundle / 'handoff.md'}，再 mf task submit。",
                        "提交后等待复审和 manager 验收；manager 会收到 task.rework 审计通知。",
                    ]
                )
        elif status == "rejected":
            needs_rework = _review_task_needs_rework(review_task, review_task_path)
            lines.extend(
                [
                    "先读取 review.md 和 review-handoff.md，只整改必须整改项。",
                    (
                        f"review 结论 NEEDS_REWORK 已回流返工；运行 mf task rework {task_id} 开始"
                        "（记录 review id、整改项、allowed_paths 与 lease；不要用 mf task start）。"
                        if needs_rework
                        else f"编辑前先运行：mf task start {task_id}（取得 lease；无交付根绑定时加 --project-dir <交付库>）。"
                    ),
                    "提交后不可继续编辑；再次返工需评审/验收结论明确后重新开始。",
                    f"完成后更新 {bundle / 'dev-record.md'} 和 {bundle / 'handoff.md'}，再 mf task submit。",
                    "等待复审和 manager 验收。",
                ]
            )
        else:
            lines.extend(
                [
                    f"先运行：mf task show {task_id} --packet",
                    f"只写 allowed_paths；完成后写 {bundle / 'dev-record.md'} 和 {bundle / 'handoff.md'}，再 mf task submit。",
                    "决策分级：D0/D1 不自行决定（写 BLOCKED/交接升级）；D2 技术决策记录结论；D3 留审计。",
                    "任务粒度：只做可独立验证增量；跨模块规格由独立 verify 任务覆盖，不在单模块任务内假装覆盖。",
                ]
            )
            if review_id:
                lines.append(f"提交后 manager 会推进 review 任务 {review_id}；不要自行验收。")
            else:
                lines.append("提交后由 manager 评审并验收；不要自行验收。")
    elif owner == "designer":
        lines.extend(
            [
                f"你是 designer（设计责任主体）。先运行：mf task show {task_id} --packet",
                "只写 contract 设计区（architecture/、specs/、P2 设计包）与任务 bundle；不写子项目源码。",
                "输出设计包 DP/SPEC/映射/跨子项目验证与预研计划；design 任务不写生产源码。",
                "决策分级：D0/D1 不自行决定（写 BLOCKED/交接升级）；D2 技术决策记录结论。",
                f"完成后更新 {bundle / 'dev-record.md'} 和 {bundle / 'handoff.md'}，再 mf task submit。",
                "提交后由 manager 验收设计；不要自行验收；角色切换请在用户终端执行 mf role --as。",
            ]
        )
    else:
        if status == "draft":
            lines.append("任务卡缺验收标准；先补全 acceptance，再置为 ready。")
        elif status == "submitted":
            if kind == "review":
                rework_scope = _read_rework_scope(bundle)
                recorded_verdict = _read_review_verdict(bundle) or data.get("review_verdict")
                lines.append(f"先读取 review.md / review-handoff.md，再 mf task accept {task_id}。")
                lines.append(
                    "评审门：确认评审者未参与实现；结论仅为 PASS/PASS_WITH_RISK/"
                    "NEEDS_REWORK/BLOCKED；PASS_WITH_RISK 需风险与接受人。"
                )
                if recorded_verdict == "NEEDS_REWORK" or rework_scope.get("scope"):
                    _, summary_missing = _read_rework_summary(bundle)
                    if (
                        rework_scope.get("scope") == "in-scope"
                        and not summary_missing
                    ):
                        lines.append(
                            "NEEDS_REWORK：范围内整改项会自动回流实现 worker（所有风险级别）；"
                            "rework_requires 标注的范围外事项由你另开单，不阻塞返工。"
                        )
                    else:
                        lines.append(
                            "NEEDS_REWORK：缺少 rework_summary 或 rework_scope 非 in-scope，不会自动回流；"
                            "让 reviewer 补齐说明后重开，或按范围外流程处理（开 CHG/BUG/MFP/新卡）。"
                        )
            elif review_id and review_task:
                if review_task.get("status") == "submitted":
                    lines.append(f"先 accept review 任务 {review_id}，再验收 {task_id}。")
                elif review_task.get("status") == "accepted":
                    if review_task.get("review_verdict") in {"PASS", "PASS_WITH_RISK"}:
                        lines.append(f"review 已通过；mf task accept {task_id} --verdict PASS。")
                    elif review_task.get("review_verdict") == "NEEDS_REWORK":
                        lines.append(
                            "review 结论 NEEDS_REWORK；未自动回流（范围外/缺说明），manager 需处理："
                        )
                        lines.append(
                            f"让 reviewer 补齐 rework_summary/范围声明后重开，或 "
                            f"mf task reject {task_id} --reason ... 让 worker 用 "
                            f"mf task rework {task_id} 开始；范围外事项开 CHG/BUG/MFP/新卡。"
                        )
                    else:
                        lines.append(
                            f"review 结论 {review_task.get('review_verdict')}；"
                            f"记录 BUG/新卡或 mf task reject {task_id} --reason ... 并说明裁决。"
                        )
                else:
                    lines.append(
                        f"等待 review 任务 {review_id} 完成；通过后再 mf task accept {task_id}。"
                    )
            else:
                lines.append(f"先完成 review，再 mf task accept {task_id} 或 mf task reject {task_id}。")
            if risk == "critical":
                lines.append("critical 任务验收必须带 --user-approved-by <用户/记录>。")
        elif status == "blocked":
            lines.append("任务以 BLOCKED 提交；先读 handoff 的阻塞证据，再裁决：")
            lines.append(
                "1) 改卡/扩大 allowed_paths 后 worker 用 mf task start/rework 重新开始；"
                "2) 开 CHG/BUG/MFP/新卡重排；3) mf task reject 并记录原因。"
            )
            lines.append("关联评审任务保持 draft/ready，不派给评审者；不得留空下一责任。")
        elif status == "accepted":
            lines.append("任务已验收；规划并创建下一个任务卡。")
        else:
            lines.append(f"检查任务状态并决定 accept/reject：mf task show {task_id}。")
    lines.append("")
    lines.append(f"责任链：每任务后运行 mf task prompt {task_id}，明确 next_owner；实现者不得自验收。")
    return "\n".join(lines).rstrip() + "\n"
