"""设计包（DP）：designer 产出、manager 验收（REQ-0017/REQ-0019/SPEC-FRAMEWORK R1）。

设计包是 P2 过程文档，位于 `roadmap/R{n}/phases/P2/design/DP-*.md`；
正文是 Markdown，front matter 记录结构化字段和验收结论。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .state import ledger_append, read_current
from .workspace import resolve_contract

DESIGN_VERDICTS = ("PASS", "PASS_WITH_RISK", "NEEDS_REWORK", "BLOCKED")
DESIGN_STATUSES = ("draft", "accepted", "rejected")


class DesignError(Exception):
    """设计包操作失败。"""

    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _design_root(contract: Path, roadmap: str) -> Path:
    return contract / "roadmap" / roadmap / "phases" / "P2" / "design"


def _design_paths(contract: Path) -> list[Path]:
    return sorted((contract / "roadmap").glob("*/phases/P2/design/DP-*.md"))


def _next_id(root: Path, roadmap: str) -> str:
    numbers = []
    pattern = re.compile(rf"^DP-{re.escape(roadmap)}-(\d{{2}})$")
    if root.is_dir():
        for path in root.glob("DP-*.md"):
            match = pattern.fullmatch(path.stem)
            if match:
                numbers.append(int(match.group(1)))
    return f"DP-{roadmap}-{max(numbers, default=0) + 1:02d}"


def _split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        raise DesignError("设计包缺少 YAML front matter")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise DesignError("设计包 front matter 未闭合")
    try:
        meta = yaml.safe_load(text[4:end]) or {}
    except yaml.YAMLError as exc:
        raise DesignError(f"设计包 front matter 不是合法 YAML: {exc}") from exc
    if not isinstance(meta, dict):
        raise DesignError("设计包 front matter 顶层必须是映射")
    return meta, text[end + 5 :]


def read_design(path: Path) -> dict[str, Any]:
    meta, body = _split_front_matter(path.read_text(encoding="utf-8"))
    meta["_path"] = str(path)
    meta["_body"] = body
    return meta


def _actor_guard(
    contract: Path,
    meta: dict[str, Any],
    *,
    actor_role: str | None,
    actor_delivery: str | None,
) -> None:
    """worker 只能查看当前 R 且包含本子项目的设计包（REQ-0020 版本/子项目隔离）。"""
    if actor_role != "worker":
        return
    current = str(read_current(contract).get("roadmap") or "")
    if current and str(meta.get("roadmap") or "") != current:
        raise DesignError(f"版本隔离：worker 只能查看当前路标 {current} 的设计包", 3)
    subprojects = [str(item) for item in meta.get("subprojects") or []]
    if actor_delivery and subprojects and str(actor_delivery) not in subprojects:
        raise DesignError(f"worker 只能查看包含本子项目 {actor_delivery} 的设计包", 3)


def find_design(
    project: str | Path,
    dp_id: str,
    *,
    actor_role: str | None = None,
    actor_delivery: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    contract = resolve_contract(project)
    for path in _design_paths(contract):
        meta = read_design(path)
        if str(meta.get("id") or path.stem) == dp_id:
            _actor_guard(
                contract, meta, actor_role=actor_role, actor_delivery=actor_delivery
            )
            return path, meta
    raise DesignError(f"设计包不存在: {dp_id}")


def list_designs(
    project: str | Path,
    *,
    status: str | None = None,
    actor_role: str | None = None,
    actor_delivery: str | None = None,
) -> list[dict[str, Any]]:
    contract = resolve_contract(project)
    current = str(read_current(contract).get("roadmap") or "")
    items = []
    for path in _design_paths(contract):
        try:
            meta = read_design(path)
        except DesignError:
            continue
        if actor_role == "worker":
            if current and str(meta.get("roadmap") or "") != current:
                continue
            subprojects = [str(item) for item in meta.get("subprojects") or []]
            if actor_delivery and subprojects and str(actor_delivery) not in subprojects:
                continue
        if status and meta.get("status") != status:
            continue
        meta.pop("_body", None)
        items.append(meta)
    return items


def validate_design(meta: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if meta.get("status") not in DESIGN_STATUSES:
        errors.append(f"status 必须是 {'|'.join(DESIGN_STATUSES)}")
    if not meta.get("title"):
        errors.append("缺少 title")
    if not meta.get("owner"):
        errors.append("缺少 owner")
    requirements = meta.get("requirements") or []
    if not requirements:
        errors.append("设计包必须关联至少一个 REQ（每条 REQ 至少一个 SPEC）")
    specs = meta.get("specs") or []
    if not specs:
        errors.append("设计包必须列出 SPEC 映射")
    if not meta.get("subprojects"):
        errors.append("设计包必须描述子项目/职责")
    return errors


def _render(
    meta: dict[str, Any],
    *,
    scope: str,
    non_goals: list[str],
    interfaces: list[str],
    mapping: list[str],
    pre_research: list[str],
) -> str:
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).rstrip()
    lines = [
        "---",
        front,
        "---",
        "",
        f"# {meta['id']} {meta['title']}",
        "",
        "> 设计包（P2 过程文档）：信息流/子项目/模块/接口/规格映射由 designer 产出，manager 验收。",
        "",
        "## 1. 范围",
        "",
        scope or "待补充。",
        "",
        "## 2. 非目标",
        "",
    ]
    lines.extend(f"- {item}" for item in (non_goals or ["待补充"]))
    lines.extend(["", "## 3. 子项目与职责", ""])
    for item in meta.get("subprojects") or []:
        lines.append(f"- {item}")
    lines.extend(["", "## 4. 接口/数据", ""])
    lines.extend(f"- {item}" for item in (interfaces or ["待补充"]))
    lines.extend(["", "## 5. REQ/MFP → SPEC → 子项目/模块映射", ""])
    for req in meta.get("requirements") or []:
        spec = ", ".join(s for s in (meta.get("specs") or []) if s) or "待补充"
        lines.append(f"- {req} → {spec}")
    for item in meta.get("mfps") or []:
        lines.append(f"- {item} → {', '.join(meta.get('specs') or []) or '待补充'}")
    lines.extend(f"- {item}" for item in (mapping or []))
    lines.extend(["", "## 6. 预研计划", ""])
    lines.extend(f"- {item}" for item in (pre_research or ["无"]))
    lines.extend(["", "## 7. 验收记录", "", "见 front matter `acceptance`。", ""])
    return "\n".join(lines)


def create_design(
    project: str | Path,
    title: str,
    *,
    requirements: list[str] | None = None,
    mfps: list[str] | None = None,
    specs: list[str] | None = None,
    subprojects: list[str] | None = None,
    scope: str = "",
    non_goals: list[str] | None = None,
    interfaces: list[str] | None = None,
    mapping: list[str] | None = None,
    pre_research: list[str] | None = None,
    actor_role: str = "designer",
) -> dict[str, Any]:
    """designer 创建设计包；worker 不得冒充 designer 写设计正文。"""
    if actor_role not in {"designer", "manager"}:
        raise DesignError("只有 designer（或 manager 代记录）可以创建设计包", 3)
    contract = resolve_contract(project)
    state = read_current(contract)
    roadmap = str(state.get("roadmap") or "R1")
    root = _design_root(contract, roadmap)
    dp_id = _next_id(root, roadmap)
    meta = {
        "id": dp_id,
        "title": title.strip(),
        "type": "design-package",
        "status": "draft",
        "owner": "designer",
        "roadmap": roadmap,
        "phase": "P2",
        "requirements": list(requirements or []),
        "mfps": list(mfps or []),
        "specs": list(specs or []),
        "subprojects": list(subprojects or []),
        "created_by": actor_role,
        "created_at": _now(),
        "acceptance": None,
    }
    errors = validate_design(meta)
    if errors:
        raise DesignError("设计包不完整: " + "；".join(errors))
    path = root / f"{dp_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _render(
            meta,
            scope=scope,
            non_goals=list(non_goals or []),
            interfaces=list(interfaces or []),
            mapping=list(mapping or []),
            pre_research=list(pre_research or []),
        ),
        encoding="utf-8",
    )
    ledger_append(
        contract,
        {"event": "design.package_created", "design": dp_id, "roadmap": roadmap},
    )
    meta["_path"] = str(path)
    return meta


def update_design_meta(path: Path, meta: dict[str, Any], body: str) -> Path:
    payload = {key: value for key, value in meta.items() if not key.startswith("_")}
    path.write_text(
        "---\n" + yaml.safe_dump(payload, sort_keys=False, allow_unicode=True).rstrip() + "\n---\n" + body,
        encoding="utf-8",
    )
    return path


def accept_design(
    project: str | Path,
    dp_id: str,
    *,
    verdict: str,
    note: str | None = None,
    accepted_by: str = "manager",
    actor_role: str = "manager",
) -> dict[str, Any]:
    if actor_role != "manager":
        raise DesignError("只有 manager 可以验收设计包", 3)
    if verdict not in DESIGN_VERDICTS:
        raise DesignError(f"verdict 必须是 {'|'.join(DESIGN_VERDICTS)}")
    contract = resolve_contract(project)
    path, meta = find_design(contract, dp_id)
    body = str(meta.pop("_body", ""))
    meta["status"] = "accepted" if verdict in {"PASS", "PASS_WITH_RISK"} else "rejected"
    meta["acceptance"] = {
        "verdict": verdict,
        "note": note,
        "accepted_by": accepted_by,
        "accepted_at": _now(),
    }
    meta["updated_at"] = _now()
    update_design_meta(path, meta, body)
    ledger_append(
        contract,
        {"event": "design.accepted", "design": dp_id, "verdict": verdict, "accepted_by": accepted_by},
    )
    meta["_path"] = str(path)
    return meta
