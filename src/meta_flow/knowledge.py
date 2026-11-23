"""项目知识、纠正记录与任务包注入。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .state import ledger_append
from .workspace import resolve_contract

KINDS = {
    "term": ("terms", "TERM"),
    "behavior": ("behaviors", "BEH"),
    "convention": ("conventions", "CONV"),
    "preference": ("preferences", "PREF"),
    "lesson": ("lessons", "LESSON"),
}
SECTION_TITLES = {
    "terms": "术语",
    "behaviors": "行为约定",
    "conventions": "项目约定",
    "preferences": "沟通偏好",
    "lessons": "复盘",
}


class KnowledgeError(Exception):
    """知识操作失败。"""

    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _path(contract: Path) -> Path:
    return contract / "knowledge" / "KNOWLEDGE.yaml"


def _load(contract: Path) -> dict[str, Any]:
    path = _path(contract)
    if not path.is_file():
        return {"schema": 1, **{key: [] for key in SECTION_TITLES}}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise KnowledgeError(f"{path} 不是合法 YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise KnowledgeError(f"{path} 顶层必须是映射")
    for key in SECTION_TITLES:
        data.setdefault(key, [])
    return data


def _save(contract: Path, data: dict[str, Any]) -> None:
    path = _path(contract)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _next_id(items: list[dict[str, Any]], prefix: str) -> str:
    numbers = []
    for item in items:
        raw = str(item.get("id") or "")
        if raw.startswith(prefix + "-") and raw[len(prefix) + 1 :].isdigit():
            numbers.append(int(raw[len(prefix) + 1 :]))
    return f"{prefix}-{max(numbers, default=0) + 1:03d}"


def add_knowledge(
    project: str | Path,
    kind: str,
    text: str,
    *,
    context: str = "",
    source: str = "user",
) -> dict[str, Any]:
    if kind not in KINDS:
        raise KnowledgeError(f"kind 只能是 {'|'.join(KINDS)}")
    if not text.strip():
        raise KnowledgeError("知识内容不能为空")
    contract = resolve_contract(project)
    data = _load(contract)
    section, prefix = KINDS[kind]
    item = {
        "id": _next_id(data[section], prefix),
        "text": text.strip(),
        "context": context,
        "source": source,
        "status": "active",
        "created_at": _now(),
        "updated_at": _now(),
    }
    data[section].append(item)
    _save(contract, data)
    render(contract)
    ledger_append(contract, {"event": "knowledge.add", "kind": kind, "id": item["id"]})
    return item


def list_knowledge(project: str | Path, *, kind: str | None = None) -> list[dict[str, Any]]:
    if kind is not None and kind not in KINDS:
        raise KnowledgeError(f"kind 只能是 {'|'.join(KINDS)}")
    contract = resolve_contract(project)
    data = _load(contract)
    result = []
    for key in SECTION_TITLES:
        if kind is not None and KINDS[kind][0] != key:
            continue
        for item in data.get(key) or []:
            result.append({"kind": key, **item})
    return result


def show_knowledge(project: str | Path, item_id: str) -> dict[str, Any]:
    for item in list_knowledge(project):
        if item.get("id") == item_id:
            return item
    raise KnowledgeError(f"知识条目不存在: {item_id}")


def render(contract: Path) -> Path:
    data = _load(contract)
    lines = [
        "# 项目知识",
        "",
        "> 由 `mf knowledge render` 生成；结构化真相见 `KNOWLEDGE.yaml`。",
        "",
    ]
    for key, title in SECTION_TITLES.items():
        lines.extend([f"## {title}", ""])
        items = data.get(key) or []
        if not items:
            lines.append("(none)")
        for item in items:
            context = f"（{item.get('context')}）" if item.get("context") else ""
            lines.append(f"- **{item.get('id')}**: {item.get('text')}{context}")
        lines.append("")
    path = contract / "knowledge" / "KNOWLEDGE.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def packet_lines(contract: Path, *, limit: int = 12) -> list[str]:
    """给任务包注入少量项目知识，避免重复注入和超长上下文。"""
    try:
        data = _load(contract)
    except KnowledgeError:
        return []
    lines = []
    for key in ("terms", "behaviors", "conventions", "preferences", "lessons"):
        for item in data.get(key) or []:
            if item.get("status", "active") != "active":
                continue
            lines.append(f"- [{item.get('id')}] {item.get('text')}")
            if len(lines) >= limit:
                return lines
    return lines
