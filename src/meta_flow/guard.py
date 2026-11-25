"""PreToolUse 守卫：在 Claude Code 工具层拦截越界 Read/Write/Edit。"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import yaml

from .workspace import detect_role, find_workspace_root, resolve_contract

HOOK_COMMAND = "mf hook pretool"
HOOK_MATCHER = "Read|Write|Edit|MultiEdit|NotebookEdit|Grep|Glob"
PATH_KEYS = ("file_path", "path", "notebook_path")
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
READ_TOOLS = {"Read", "Grep", "Glob"}


def _deny(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"Meta Flow 边界: {reason}",
        }
    }


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
    normalized = path.replace("\\", "/").lstrip("./")
    return any(_glob_regex(str(pattern)).match(normalized) for pattern in patterns)


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _hook_path(payload: dict[str, Any], cwd: Path) -> Path | None:
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return None
    raw = next((tool_input.get(key) for key in PATH_KEYS if tool_input.get(key)), None)
    if raw is None:
        return None
    path = Path(str(raw)).expanduser()
    return path if path.is_absolute() else (cwd / path).resolve()


def _worker_delivery(root: Path | None) -> str | None:
    if root is None:
        return None
    data = _load_yaml(root / "delivery.yaml")
    return str(data.get("id")) if data.get("id") else None


def _active_tasks(contract: Path, delivery: str | None) -> list[dict[str, Any]]:
    items = []
    for path in sorted((contract / "roadmap").glob("*/phases/*/tasks/T*/TASK.yaml")):
        task = _load_yaml(path)
        if task.get("status") != "in_progress":
            continue
        if delivery and task.get("delivery") and task.get("delivery") != delivery:
            continue
        task["_bundle"] = path.parent
        items.append(task)
    return items


def _bundle_match(relative: str, tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
    for task in tasks:
        bundle = Path(str(task.get("_bundle"))).name
        if f"/tasks/{bundle}/" in f"/{relative}":
            return task
    return None


def _manager_source_denied(path: Path, workspace_root: Path | None) -> bool:
    if workspace_root is None:
        return False
    local = _load_yaml(workspace_root / ".meta-flow" / "workspace.yaml")
    for item in local.get("subprojects") or []:
        sub = (workspace_root / str(item.get("path") or "")).resolve()
        if path == sub or sub in path.parents:
            relative = path.relative_to(sub).as_posix()
            if relative.startswith(("src/", "tests/", "lib/", "app/", "packages/")):
                return True
    return False


def pretool_decision(payload: dict[str, Any]) -> dict[str, Any] | None:
    tool = str(payload.get("tool_name") or "")
    if tool not in READ_TOOLS | WRITE_TOOLS:
        return None
    cwd = Path(str(payload.get("cwd") or os.getcwd())).expanduser().resolve()
    path = _hook_path(payload, cwd)
    if path is None:
        return None
    detected_role, detected_root = detect_role(cwd)
    env_role = os.environ.get("MF_ROLE")
    if env_role in {"manager", "worker", "maintainer"}:
        # 与 CLI 一致：显式 MF_ROLE 优先于目录推导
        role = env_role
        role_root = detected_root if detected_role == env_role else None
    else:
        role, role_root = detected_role, detected_root
    if role == "unbound":
        return None
    try:
        contract = resolve_contract(role_root or cwd)
    except Exception:
        contract = None
    workspace_root = find_workspace_root(role_root or cwd)
    if contract is None:
        return None
    if tool in READ_TOOLS and path.is_file():
        policy_data = _load_yaml(contract / "policies" / "CONTEXT-POLICY.yaml")
        budget = ((policy_data.get("roles") or {}).get(role) or {}).get("budget") or {}
        max_bytes = int(budget.get("bytes") or (131072 if role == "manager" else 65536))
        if path.stat().st_size > max_bytes:
            return _deny(
                f"{path.name} 超过 {role} 读预算 {max_bytes}B；请用 mf context show/分段读取"
            )

    if tool in WRITE_TOOLS:
        if path.is_relative_to(contract):
            relative = path.relative_to(contract).as_posix()
            if relative.startswith("archive/"):
                return _deny("archive 只读；写入请通过版本关闭流程")
            if relative.startswith("state/"):
                return _deny("state 由 mf 派生写入，禁止直接改")
            if role == "maintainer":
                return _deny("maintainer 不改项目契约")
            if role == "worker":
                tasks = _active_tasks(contract, _worker_delivery(role_root))
                task = _bundle_match(relative, tasks)
                if task is None:
                    return _deny("worker 只能写自己 in_progress 任务的 bundle")
                allowed = ["dev-record.md", "handoff.md", "review.md", "review-handoff.md", "evidence/"]
                if not any(f"/{value}" in f"/{relative}" for value in allowed):
                    return _deny("worker 不能写契约基线或其他任务")
                return None
            if role == "manager":
                if _manager_source_denied(path, workspace_root):
                    return _deny("manager 不直接改交付库源码")
                return None
            return _deny("当前角色不能写契约库")
        if role == "worker":
            root = role_root
            if root is not None and path.is_relative_to(root):
                tasks = _active_tasks(contract, _worker_delivery(root))
                for task in tasks:
                    relative = path.relative_to(root).as_posix()
                    if _matches(relative, [str(item) for item in task.get("forbidden") or []]):
                        return _deny(f"路径在任务 forbidden 内: {relative}")
                    if _matches(relative, [str(item) for item in task.get("allowed_paths") or []]):
                        return None
                return _deny("worker 写入不在当前任务 allowed_paths 内")
            return _deny("worker 只能写自己的交付库")
        if role == "manager":
            if _manager_source_denied(path, workspace_root):
                return _deny("manager 不直接改交付库源码")
            return None
        if role == "maintainer":
            global_root = Path(os.environ.get("META_FLOW_HOME", Path.home() / ".meta-flow")).resolve()
            if path.is_relative_to(global_root):
                return None
            return _deny("maintainer 只维护 meta-flow 源码/全局模板")
        return None

    # Read / Grep / Glob
    if path.is_relative_to(contract):
        relative = path.relative_to(contract).as_posix()
        if role == "manager":
            if relative.startswith("archive/"):
                return _deny("archive 只允许通过 mf archive show --reason 读取")
            return None
        if role == "worker":
            if relative == "state/current.json":
                return None
            tasks = _active_tasks(contract, _worker_delivery(role_root))
            if _bundle_match(relative, tasks) is not None:
                return None
            return _deny("worker 只能读任务包/自己的 bundle，不能读完整契约")
        if role == "maintainer":
            if relative.startswith(("workspace/", ".meta-flow/")):
                return None
            return _deny("maintainer 不读项目需求/设计/任务内容")
        return None
    if role == "worker":
        root = role_root
        if root is not None and path.is_relative_to(root):
            return None
        return _deny("worker 不读其他交付库")
    if role == "manager":
        if _manager_source_denied(path, workspace_root):
            return _deny("manager 不直接读交付库源码")
        return None
    return None


def run_hook() -> int:
    import sys

    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    if not isinstance(payload, dict):
        return 0
    decision = pretool_decision(payload)
    if decision:
        print(json.dumps(decision, ensure_ascii=False))
    return 0
