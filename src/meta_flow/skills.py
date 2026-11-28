"""角色技能（Skills）：发现、解析与结构校验（REQ-0020 / SPEC-FRAMEWORK R4）。

角色提示词只定义身份/权限/工作区；具体活动流程由 skill 承载。
skill 不改权限：越权仍由 role/guard/CLI 拒绝。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .workspace import resolve_contract

REQUIRED_KEYS = ("name", "roles", "trigger", "inputs", "outputs", "read", "write")
REQUIRED_SECTIONS = ("步骤", "门禁", "失败/升级", "证据", "反模式")
VALID_ROLES = {"manager", "designer", "worker", "maintainer", "user"}


class SkillError(Exception):
    """技能操作失败。"""

    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


def _split(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    try:
        meta = yaml.safe_load(text[4:end]) or {}
    except yaml.YAMLError:
        return {}, text
    if not isinstance(meta, dict):
        return {}, text
    return meta, text[end + 5 :]


def skill_dirs(project: str | Path) -> list[Path]:
    contract = resolve_contract(project)
    project_path = Path(project).expanduser().resolve()
    candidates = [
        contract / "skills",
        project_path / "skills",
        project_path / "templates" / "skills",
    ]
    seen: set[Path] = set()
    result = []
    for item in candidates:
        resolved = item.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if item.is_dir():
            result.append(item)
    return result


def discover_skills(project: str | Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for directory in skill_dirs(project):
        for path in sorted(directory.glob("*.md")):
            if path.name.upper().startswith("INDEX"):
                continue
            meta, _body = _split(path.read_text(encoding="utf-8"))
            name = str(meta.get("name") or path.stem)
            items.append(
                {
                    "name": name,
                    "path": path,
                    "source": str(directory),
                    "roles": [str(role) for role in meta.get("roles") or []],
                    "trigger": meta.get("trigger"),
                    "meta": meta,
                }
            )
    return items


def show_skill(project: str | Path, name: str) -> dict[str, Any]:
    matches = [item for item in discover_skills(project) if item["name"] == name]
    if not matches:
        raise SkillError(f"技能不存在: {name}")
    item = matches[0]
    text = Path(item["path"]).read_text(encoding="utf-8")
    meta, body = _split(text)
    return {
        "name": item["name"],
        "path": str(item["path"]),
        "meta": meta,
        "body": body,
    }


def validate_skill(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"无法读取: {exc}"]
    meta, body = _split(text)
    if not meta:
        return ["缺少 YAML front matter"]
    for key in REQUIRED_KEYS:
        if meta.get(key) in (None, "", []):
            errors.append(f"缺少 front matter: {key}")
    roles = meta.get("roles") or []
    if not isinstance(roles, list) or not roles:
        errors.append("roles 必须是非空列表")
    else:
        unknown = [role for role in roles if str(role) not in VALID_ROLES]
        if unknown:
            errors.append(f"未知角色: {', '.join(str(item) for item in unknown)}")
    for section in REQUIRED_SECTIONS:
        if f"## {section}" not in body:
            errors.append(f"缺少章节: ## {section}")
    if len(body) > 6000:
        errors.append("skill 超过 1 页（>6000 字符）")
    return errors


def validate_skills(project: str | Path) -> list[dict[str, Any]]:
    results = []
    for item in discover_skills(project):
        path = Path(item["path"])
        errors = validate_skill(path)
        results.append({"name": item["name"], "path": str(path), "errors": errors})
    return results
