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
    if env_role in {"manager", "worker", "maintainer"}:
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


def expand(
    project: str | Path,
    relative_path: str,
    *,
    reason: str,
    actor: str | None = None,
) -> dict[str, Any]:
    contract = resolve_contract(project)
    if reason not in REASONS:
        raise ContextError(f"reason 只能是 {'|'.join(REASONS)}")
    role, actor_id = _actor(actor)
    target = (contract / relative_path).resolve()
    if not target.is_relative_to(contract):
        raise ContextError("只能读取 contract 内文件")
    relative = str(target.relative_to(contract))
    if relative.startswith("archive/") and role != "manager":
        raise ContextError("只有 manager 可以读取 archive；worker 请使用任务包")
    if role == "worker" and "/tasks/" not in f"/{relative}":
        raise ContextError("worker 通过 mf task show --packet 读取，不能直接 expand 契约")
    if not target.is_file():
        raise ContextError(f"文件不存在: {target}")
    size = target.stat().st_size
    policy_data = policy(contract)
    role_budget = ((policy_data.get("roles") or {}).get(role) or {}).get("budget") or {}
    max_read = min(MAX_READ_BYTES, int(role_budget.get("bytes") or MAX_READ_BYTES))
    if size > max_read:
        raise ContextError(f"文件 {size} 字节超过 {role} 读预算 {max_read}；拆分文档或按段读取")
    text = target.read_text(encoding="utf-8")
    _log(
        contract,
        {
            "event": "context.expand",
            "actor": actor_id,
            "role": role,
            "path": relative,
            "reason": reason,
            "bytes": size,
            "allowed": True,
        },
    )
    return {
        "path": relative,
        "reason": reason,
        "bytes": size,
        "text": text,
    }


def hot_files(project: str | Path) -> dict[str, Any]:
    contract = resolve_contract(project)
    state = read_current(contract)
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
