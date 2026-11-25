"""项目知识、纠正记录与任务包注入。"""

from __future__ import annotations

import re
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
HOT_SECTIONS = ("terms", "behaviors", "conventions", "preferences")
MAX_HOT_BYTES = 8192


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
    delivery: str | None = None,
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
        "project": _project_id(contract),
        "delivery": delivery,
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
        "# 项目知识（热区摘要）",
        "",
        "> 由 `mf knowledge render` 生成；完整条目见 `KNOWLEDGE.yaml`，复盘见 `LESSONS.md`。",
        "",
    ]
    for key in HOT_SECTIONS:
        lines.extend([f"## {SECTION_TITLES[key]}", ""])
        items = [
            item
            for item in data.get(key) or []
            if item.get("status", "active") == "active"
        ]
        if not items:
            lines.append("(none)")
        for item in items:
            context = f"（{item.get('context')}）" if item.get("context") else ""
            lines.append(f"- **{item.get('id')}**: {item.get('text')}{context}")
        lines.append("")
    text = "\n".join(lines)
    if len(text.encode("utf-8")) > MAX_HOT_BYTES:
        suffix = "\n\n> 热区摘要超过 8KB，已截断；完整内容见 KNOWLEDGE.yaml。\n"
        limit = MAX_HOT_BYTES - len(suffix.encode("utf-8"))
        text = text.encode("utf-8")[:limit].decode("utf-8", errors="ignore") + suffix
    path = contract / "knowledge" / "KNOWLEDGE.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")

    lessons = data.get("lessons") or []
    lesson_lines = ["# 复盘与经验（冷区）", ""]
    if lessons:
        for item in lessons:
            lesson_lines.append(f"- **{item.get('id')}**: {item.get('text')}")
    else:
        lesson_lines.append("(none)")
    (contract / "knowledge" / "LESSONS.md").write_text("\n".join(lesson_lines) + "\n", encoding="utf-8")
    return path


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


_TASK_REF_RE = re.compile(r"(?<![A-Za-z0-9-])((?:R\d+-P\d+-)?T\d{3})(?![0-9])")
_NAME_LIKE_RE = re.compile(r"\b([a-z][a-z0-9]*(?:-[a-z0-9]+)+)\b")


def _task_refs(text: str) -> tuple[list[str], list[str]]:
    refs = _TASK_REF_RE.findall(text)
    full = [ref for ref in refs if ref.startswith("R")]
    bare = [ref for ref in refs if not ref.startswith("R")]
    return full, bare


def _foreign_names(text: str, project_id: str | None, delivery: str | None) -> list[str]:
    names = set(_NAME_LIKE_RE.findall(text.lower()))
    names.discard(project_id or "")
    names.discard(delivery or "")
    # 常见工具/平台名不算“外部项目”
    ignore = {"meta-flow", "meta-flow-contract", "dev-records", "meta-flow-dev"}
    return sorted(name for name in names if name not in ignore)


def packet_lines(
    contract: Path,
    *,
    limit: int = 12,
    delivery: str | None = None,
    task: dict[str, Any] | None = None,
    project_id: str | None = None,
) -> list[str]:
    """给任务包注入少量热区知识，按项目/交付库/任务相关性过滤。

    MFP-0007 A1：同名任务 ID（如别的项目的 T013 与本任务 R0-P4-T013）
    不得跨项目匹配；显式 project/delivery/roadmap 不匹配时跳过。
    """
    try:
        data = _load(contract)
    except KnowledgeError:
        return []
    project_id = project_id or _project_id(contract)
    task_id = str((task or {}).get("id") or "")
    task_roadmap = str((task or {}).get("roadmap") or "") or None
    task_number = task_id.rsplit("-", 1)[-1] if task_id else ""
    lines = []
    for key in HOT_SECTIONS:
        for item in data.get(key) or []:
            if item.get("status", "active") != "active":
                continue
            scoped_delivery = item.get("delivery")
            if scoped_delivery and delivery and str(scoped_delivery) != delivery:
                continue
            scoped_project = item.get("project")
            if scoped_project and project_id and str(scoped_project) != project_id:
                continue
            scoped_roadmap = item.get("roadmap")
            if scoped_roadmap and task_roadmap and str(scoped_roadmap) != task_roadmap:
                continue
            text = "\n".join(
                str(item.get(field) or "")
                for field in ("text", "context", "source")
            )
            full_refs, bare_refs = _task_refs(text)
            if task_id:
                # 显式完整任务 ID 指向别处：不注入
                if full_refs and task_id not in full_refs:
                    continue
                if bare_refs and task_number and task_number in bare_refs:
                    scoped = (
                        (scoped_project and scoped_project == project_id)
                        or (scoped_delivery and scoped_delivery == delivery)
                        or task_id in full_refs
                    )
                    if not scoped:
                        foreign = _foreign_names(text, project_id, delivery)
                        if foreign:
                            # 裸 Txxx + 外部项目名：判定为其他项目同名任务
                            continue
            elif bare_refs:
                continue
            lines.append(f"- [{item.get('id')}] {item.get('text')}")
            if len(lines) >= limit:
                return lines
    return lines
