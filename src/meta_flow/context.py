"""热区上下文、读扩展审计与归档查询。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .state import read_current
from .workspace import resolve_contract

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
    actor: str = "manager",
) -> dict[str, Any]:
    contract = resolve_contract(project)
    if reason not in REASONS:
        raise ContextError(f"reason 只能是 {'|'.join(REASONS)}")
    target = (contract / relative_path).resolve()
    if not target.is_relative_to(contract):
        raise ContextError("只能读取 contract 内文件")
    if not target.is_file():
        raise ContextError(f"文件不存在: {target}")
    size = target.stat().st_size
    if size > MAX_READ_BYTES:
        raise ContextError(f"文件超过 {MAX_READ_BYTES} 字节，禁止整体读取: {size}")
    text = target.read_text(encoding="utf-8")
    _log(
        contract,
        {
            "event": "context.expand",
            "actor": actor,
            "path": str(target.relative_to(contract)),
            "reason": reason,
            "bytes": size,
            "allowed": True,
        },
    )
    return {
        "path": str(target.relative_to(contract)),
        "reason": reason,
        "bytes": size,
        "text": text,
    }


def hot_files(project: str | Path) -> dict[str, Any]:
    contract = resolve_contract(project)
    state = read_current(contract)
    roadmap_id = str(state.get("roadmap") or "R1")
    phase = str(state.get("phase") or "P1")
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
    files = []
    for relative in candidates:
        path = contract / relative
        files.append({"path": relative, "exists": path.is_file()})
    return {"roadmap": roadmap_id, "phase": phase, "phase_status": state.get("phase_status"), "files": files}


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
    actor: str = "manager",
) -> dict[str, Any]:
    contract = resolve_contract(project)
    if reason not in REASONS:
        raise ContextError(f"reason 只能是 {'|'.join(REASONS)}")
    directory = (contract / "archive" / roadmap_id).resolve()
    if not directory.is_dir() or not directory.is_relative_to(contract / "archive"):
        raise ContextError(f"归档不存在: {roadmap_id}")
    index = directory / "INDEX.md"
    files = [
        str(path.relative_to(directory))
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path.name != "INDEX.md"
    ]
    text = index.read_text(encoding="utf-8") if index.is_file() else ""
    _log(
        contract,
        {
            "event": "archive.show",
            "actor": actor,
            "path": str(directory.relative_to(contract)),
            "reason": reason,
            "files": len(files),
            "allowed": True,
        },
    )
    return {
        "roadmap": roadmap_id,
        "path": str(directory.relative_to(contract)),
        "reason": reason,
        "files": files,
        "index": text,
    }


def read_log(project: str | Path, *, limit: int = 50) -> list[dict[str, Any]]:
    contract = resolve_contract(project)
    path = contract / "state" / "READ-LOG.ndjson"
    if not path.is_file():
        return []
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    items = []
    for line in lines[-limit:]:
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
