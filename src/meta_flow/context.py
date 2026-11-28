"""热区上下文、读扩展审计与归档查询。"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .state import read_current, tail_lines
from .workspace import detect_role, resolve_contract

REASONS = (
    "packet_missing",
    "field_conflict",
    "schema_validation_failed",
    "human_audit",
    "summary_insufficient",
)
MAX_READ_BYTES = 256 * 1024


class ContextError(Exception):
    """上下文/归档操作失败。"""

    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _actor(actor: str | None) -> tuple[str, str]:
    if actor:
        return actor, actor
    env_role = os.environ.get("MF_ROLE")
    if env_role in {"manager", "designer", "worker", "maintainer"}:
        return env_role, env_role
    role, _ = detect_role(Path.cwd())
    if role == "unbound":
        role = "manager"
    return role, role


def _log(contract: Path, event: dict[str, Any]) -> None:
    path = contract / "state" / "READ-LOG.ndjson"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"ts": _now(), **event}, ensure_ascii=False) + "\n")


def _worker_delivery(root: Path | None) -> str | None:
    if root is None:
        return None
    path = root / "delivery.yaml"
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return None
    return str(data.get("id")) if isinstance(data, dict) and data.get("id") else None


def _current_roadmap(contract: Path) -> str:
    path = contract / "state" / "current.json"
    if not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ""
    return str(data.get("roadmap") or "") if isinstance(data, dict) else ""


def _in_progress_tasks(contract: Path, delivery: str | None) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    current = _current_roadmap(contract)
    for path in sorted((contract / "roadmap").glob("*/phases/*/tasks/T*/TASK.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (yaml.YAMLError, OSError):
            continue
        if not isinstance(data, dict) or data.get("status") != "in_progress":
            continue
        # 版本隔离：worker 只读当前 R；旧 R 在途任务不再进入 expand 白名单。
        if current and str(data.get("roadmap") or "") and str(data.get("roadmap")) != current:
            continue
        if delivery and data.get("delivery") != delivery:
            continue
        data["_bundle"] = path.parent
        tasks.append(data)
    return tasks


def _task_bundle_prefix(task: dict[str, Any]) -> str:
    task_id = str(task.get("id") or "")
    parts = task_id.split("-")
    if len(parts) == 3 and parts[0] and parts[1] and parts[2]:
        return f"roadmap/{parts[0]}/phases/{parts[1]}/tasks/{parts[2]}/"
    return ""


def _id_bundle_prefix(task_id: str) -> str:
    parts = str(task_id or "").split("-")
    if len(parts) != 3:
        return ""
    return f"roadmap/{parts[0]}/phases/{parts[1]}/tasks/{parts[2]}/"


def _path_in_prefix(relative: str, prefix: str) -> bool:
    if not prefix:
        return False
    rel = relative.replace("\\", "/").lstrip("/")
    return rel == prefix.rstrip("/") or rel.startswith(prefix)


def _bundle_allowed(relative: str, tasks: list[dict[str, Any]]) -> bool:
    for task in tasks:
        if _path_in_prefix(relative, _task_bundle_prefix(task)):
            return True
    return False


def _review_target_allowed(relative: str, tasks: list[dict[str, Any]]) -> bool:
    for task in tasks:
        if task.get("kind") != "review":
            continue
        target = str(task.get("reviews") or "")
        if _path_in_prefix(relative, _id_bundle_prefix(target)):
            return True
    return False


def _review_output_allowed(relative: str, tasks: list[dict[str, Any]]) -> bool:
    if Path(relative).name not in {"review.md", "review-handoff.md"}:
        return False
    for task in tasks:
        if task.get("kind") == "review":
            continue
        review_task = str(task.get("reviewed_by_task") or "")
        if _path_in_prefix(relative, _id_bundle_prefix(review_task)):
            return True
    return False


def _task_scope_paths(task: dict[str, Any]) -> list[str]:
    paths = [str(item) for item in task.get("allowed_paths") or []]
    if task.get("kind") == "review":
        paths.extend(str(item) for item in (task.get("review") or {}).get("scope") or [])
    return paths


def _scope_allowed(relative: str, tasks: list[dict[str, Any]]) -> bool:
    from .task import _matches  # 延迟导入，避免模块级循环

    for task in tasks:
        if _matches(relative, _task_scope_paths(task)):
            return True
    return False


def _must_read_allowed(
    relative: str, tasks: list[dict[str, Any]], contract: Path
) -> bool:
    """worker 可展开活动任务 packet 声明的 must_read 契约基线（MFP-0025）。

    packet 的 must_read = TASK.yaml + inputs 引用；inputs 引用用与 packet
    相同的 `_find_input` 解析，保证 expand 白名单与任务包一致。
    """
    from .task import _find_input  # 延迟导入，避免模块级循环

    for task in tasks:
        prefix = _task_bundle_prefix(task)
        if prefix and _path_in_prefix(relative, prefix):
            return True
        inputs = task.get("inputs") or {}
        if not isinstance(inputs, dict):
            continue
        refs: list[str] = []
        for value in inputs.values():
            if isinstance(value, list):
                refs.extend(str(item) for item in value if item)
            elif value:
                refs.append(str(value))
        for ref in refs:
            found = _find_input(contract, ref)
            if found is None:
                continue
            try:
                if found[0].resolve() == (contract / relative).resolve():
                    return True
            except OSError:
                continue
    return False


def _resolve_expand_target(
    project_path: Path, contract: Path, relative_path: str
) -> tuple[Path, str]:
    raw = Path(str(relative_path)).expanduser()
    if raw.is_absolute():
        target = raw.resolve()
    else:
        contract_candidate = (contract / raw).resolve()
        project_candidate = (project_path / raw).resolve()
        if contract_candidate.exists() and contract_candidate.is_relative_to(contract):
            target = contract_candidate
        elif project_candidate.exists() and project_candidate.is_relative_to(project_path):
            target = project_candidate
        else:
            target = contract_candidate
    if target.is_relative_to(contract):
        return target, target.relative_to(contract).as_posix()
    if target.is_relative_to(project_path):
        return target, "delivery:" + target.relative_to(project_path).as_posix()
    raise ContextError(f"只能读取 contract 或当前交付库内文件: {target}")


def expand(
    project: str | Path,
    relative_path: str,
    *,
    reason: str,
    actor: str | None = None,
) -> dict[str, Any]:
    project_path = Path(project).expanduser().resolve()
    contract = resolve_contract(project_path)
    if reason not in REASONS:
        raise ContextError(f"reason 只能是 {'|'.join(REASONS)}")
    role, actor_id = _actor(actor)
    worker_root: Path | None = None
    tasks: list[dict[str, Any]] = []
    if role == "worker":
        detected, detected_root = detect_role(project_path)
        if detected != "worker" or detected_root is None:
            raise ContextError(
                "worker 无交付根绑定；请用 --project-dir 指定交付库，或从交付库运行"
            )
        worker_root = detected_root
        delivery = _worker_delivery(worker_root)
        if not delivery:
            raise ContextError(f"交付库缺少 delivery.yaml，无法确定作用域: {worker_root}")
        tasks = _in_progress_tasks(contract, delivery)
    target, display = _resolve_expand_target(project_path, contract, relative_path)
    if target.is_relative_to(contract):
        relative = target.relative_to(contract).as_posix()
        if relative.startswith("archive/") and role != "manager":
            raise ContextError("只有 manager 可以读取 archive；worker 请使用任务包")
        if role == "worker":
            if not (
                _bundle_allowed(relative, tasks)
                or _review_target_allowed(relative, tasks)
                or _review_output_allowed(relative, tasks)
                or _must_read_allowed(relative, tasks, contract)
            ):
                raise ContextError(
                    "worker 只能展开自己的任务 bundle、评审任务的目标 bundle、"
                    "返工任务的评审输出或任务包 must_read 契约基线；不能直接 expand 契约基线"
                )
        elif role == "maintainer":
            if not relative.startswith(("workspace/", ".meta-flow/")):
                raise ContextError("maintainer 不读项目需求/设计/任务内容")
    else:
        if role != "worker":
            raise ContextError("只有 worker 可以展开交付库文件")
        if worker_root is None or not target.is_relative_to(worker_root):
            raise ContextError("worker 只能展开自己交付库内文件")
        relative = target.relative_to(worker_root).as_posix()
        if not _scope_allowed(relative, tasks):
            raise ContextError(
                f"交付库文件不在活动任务 allowed_paths/review_scope 内: {relative}"
            )
    if not target.is_file():
        raise ContextError(f"文件不存在: {target}")
    size = target.stat().st_size
    if size > MAX_READ_BYTES:
        raise ContextError(
            f"文件 {size} 字节超过 expand 上限 {MAX_READ_BYTES}；拆分文档或按段读取"
        )
    text = target.read_text(encoding="utf-8")
    _log(
        contract,
        {
            "event": "context.expand",
            "actor": actor_id,
            "role": role,
            "path": display,
            "reason": reason,
            "bytes": size,
            "allowed": True,
        },
    )
    return {
        "path": display,
        "reason": reason,
        "bytes": size,
        "text": text,
    }


def hot_files(project: str | Path) -> dict[str, Any]:
    project_path = Path(project).expanduser().resolve()
    contract = resolve_contract(project_path)
    state = read_current(contract)
    role, detected_root = detect_role(project_path)
    if role == "unbound":
        role, _ = _actor(None)
    if role == "worker":
        # worker 的“热区”是活动任务 bundle，不暴露契约基线
        delivery = _worker_delivery(detected_root)
        if detected_root is None or not delivery:
            raise ContextError("worker 无交付根绑定；请用 --project-dir 指定交付库")
        tasks = _in_progress_tasks(contract, delivery)
        files = []
        total_bytes = 0
        for task in tasks:
            bundle = Path(str(task.get("_bundle") or ""))
            for path in sorted(bundle.rglob("*")):
                if not path.is_file():
                    continue
                relative = path.relative_to(contract).as_posix()
                size = path.stat().st_size
                total_bytes += size
                files.append({"path": relative, "exists": True, "bytes": size})
        policy_data = policy(contract)
        budget = ((policy_data.get("roles") or {}).get("worker") or {}).get("budget") or {
            "files": 10,
            "bytes": 65536,
        }
        return {
            "roadmap": str(state.get("roadmap") or "R1"),
            "phase": str(state.get("phase") or "P1"),
            "phase_status": state.get("phase_status"),
            "scope": "task-bundle",
            "files": files,
            "total_bytes": total_bytes,
            "budget": budget,
            "within_budget": total_bytes <= int(budget.get("bytes") or 65536),
        }
    roadmap_id = str(state.get("roadmap") or "R1")
    phase = str(state.get("phase") or "P1")
    previous = None
    if phase in {"P2", "P3", "P4", "P5"}:
        previous = f"P{int(phase[1:]) - 1}"
    candidates = [
        "state/current.json",
        "project/PROJECT-PLAN.md",
        "roadmap/ROADMAP.yaml",
        f"roadmap/{roadmap_id}/PLAN.md",
        "requirements/INDEX.md",
        "architecture/INDEX.md",
        "knowledge/KNOWLEDGE.md",
        "policies/CONTEXT-POLICY.yaml",
        f"roadmap/{roadmap_id}/phases/{phase}/PLAN.md",
        f"roadmap/{roadmap_id}/phases/{phase}/REPORT.md",
    ]
    if previous:
        candidates.append(f"roadmap/{roadmap_id}/phases/{previous}/HANDOFF-TO-{phase}.md")
    files = []
    total_bytes = 0
    for relative in candidates:
        path = contract / relative
        size = path.stat().st_size if path.is_file() else 0
        total_bytes += size
        files.append({"path": relative, "exists": path.is_file(), "bytes": size})
    policy_data = policy(contract)
    budget = ((policy_data.get("roles") or {}).get("manager") or {}).get("budget") or {
        "files": 12,
        "bytes": 131072,
    }
    return {
        "roadmap": roadmap_id,
        "phase": phase,
        "phase_status": state.get("phase_status"),
        "files": files,
        "total_bytes": total_bytes,
        "budget": budget,
        "within_budget": total_bytes <= int(budget.get("bytes") or 131072),
    }


def _archive_dirs(contract: Path) -> list[Path]:
    root = contract / "archive"
    if not root.is_dir():
        return []
    return sorted(path for path in root.iterdir() if path.is_dir())


def archive_list(project: str | Path) -> list[dict[str, Any]]:
    contract = resolve_contract(project)
    items = []
    for directory in _archive_dirs(contract):
        index = directory / "INDEX.md"
        items.append(
            {
                "roadmap": directory.name,
                "path": str(directory.relative_to(contract)),
                "index": str(index.relative_to(contract)) if index.is_file() else None,
                "files": len([path for path in directory.rglob("*") if path.is_file()]),
            }
        )
    return items


def archive_show(
    project: str | Path,
    roadmap_id: str,
    *,
    reason: str,
    actor: str | None = None,
) -> dict[str, Any]:
    contract = resolve_contract(project)
    if reason not in REASONS:
        raise ContextError(f"reason 只能是 {'|'.join(REASONS)}")
    role, actor_id = _actor(actor)
    if role != "manager":
        raise ContextError("archive 只允许 manager 查询")
    directory = (contract / "archive" / roadmap_id).resolve()
    if not directory.is_dir() or not directory.is_relative_to(contract / "archive"):
        raise ContextError(f"归档不存在: {roadmap_id}")
    index = directory / "INDEX.md"
    files = [
        str(path.relative_to(directory))
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path.name != "INDEX.md"
    ]
    total_bytes = sum(path.stat().st_size for path in directory.rglob("*") if path.is_file())
    text = index.read_text(encoding="utf-8") if index.is_file() else ""
    _log(
        contract,
        {
            "event": "archive.show",
            "actor": actor_id,
            "role": role,
            "path": str(directory.relative_to(contract)),
            "reason": reason,
            "files": len(files),
            "bytes": total_bytes,
            "allowed": True,
        },
    )
    return {
        "roadmap": roadmap_id,
        "path": str(directory.relative_to(contract)),
        "reason": reason,
        "files": files,
        "bytes": total_bytes,
        "index": text,
    }


def read_log(project: str | Path, *, limit: int = 50) -> list[dict[str, Any]]:
    contract = resolve_contract(project)
    path = contract / "state" / "READ-LOG.ndjson"
    items = []
    for line in tail_lines(path, limit):
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            items.append(data)
    return items


def policy(project: str | Path) -> dict[str, Any]:
    contract = resolve_contract(project)
    path = contract / "policies" / "CONTEXT-POLICY.yaml"
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ContextError(f"{path} 不是合法 YAML: {exc}") from exc
    return data if isinstance(data, dict) else {}
