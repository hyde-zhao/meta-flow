"""Validate dispatch evidence in process/handoffs/*.md frontmatter.

防止调度证据断链：handoff 文件的 dispatch 块声明 mode=subagent 时，
必须回填真实子 agent 调度证据（canonical_role / dispatch_trigger /
agent_id 或 thread_id / tool_name / spawned_at 或 resumed_at /
completed_at）。只有 handoff 没有调度证据时，不得判定目标 agent 已完成。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

# 已知 dispatch.mode 取值
SUBAGENT_MODE = "subagent"
INLINE_FALLBACK_MODE = "inline-fallback"
HANDOFF_ONLY_MODE = "handoff-only"
KNOWN_MODES = (SUBAGENT_MODE, INLINE_FALLBACK_MODE, HANDOFF_ONLY_MODE)

# 视为空的占位值（与 human_gate.EMPTY_VALUES 思路一致）
EMPTY_VALUES = {"", "-", "—", "n/a", "N/A", "无", "不适用"}


def _is_empty(value: Any) -> bool:
    return value is None or str(value).strip().strip('"').strip("'") in EMPTY_VALUES


def _parse_frontmatter(text: str) -> str | None:
    """提取 Markdown frontmatter 文本（--- 之间）。无 frontmatter 返回 None。"""
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    return text[4:end]


def _parse_dispatch_block(frontmatter: str) -> dict[str, str] | None:
    """解析 frontmatter 中 dispatch: 嵌套块的标量字段。

    不依赖 yaml；按行解析 `  key: value` 形式的嵌套字段，与 cli.py 的
    _scalar_value(nested=True) 同一约定。dispatch 块结束于第一个非缩进行。
    """
    dispatch: dict[str, str] = {}
    in_dispatch = False
    for line in frontmatter.splitlines():
        if line.startswith("dispatch:"):
            in_dispatch = True
            continue
        if not in_dispatch:
            continue
        # 遇到非缩进行（顶层 key 或空行外的内容）则 dispatch 块结束
        if line and not line.startswith(" "):
            break
        stripped = line.strip()
        if not stripped:
            continue
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        dispatch[key.strip()] = value.strip().strip('"').strip("'")
    return dispatch if dispatch else None


def validate_handoff_dispatch(path: Path) -> list[str]:
    """校验单个 handoff 文件的 dispatch 块。返回错误信息列表（空表示通过）。"""
    errors: list[str] = []
    if not path.is_file():
        return [f"handoff file not found: {path}"]
    text = path.read_text(encoding="utf-8")
    frontmatter = _parse_frontmatter(text)
    if frontmatter is None:
        return [f"{path.name}: missing or invalid YAML frontmatter"]

    dispatch = _parse_dispatch_block(frontmatter)
    if dispatch is None:
        return [f"{path.name}: missing dispatch block in frontmatter"]

    mode = dispatch.get("mode", "").strip()
    if not mode:
        errors.append(f"{path.name}: dispatch.mode is empty")
        return errors
    if mode not in KNOWN_MODES:
        errors.append(
            f"{path.name}: dispatch.mode={mode!r} is not a known mode "
            f"(expected one of {list(KNOWN_MODES)})"
        )
        return errors

    # canonical_role 对所有执行模式都是必填（状态机角色）
    if _is_empty(dispatch.get("canonical_role")):
        errors.append(f"{path.name}: dispatch.mode={mode} requires canonical_role")

    if mode == SUBAGENT_MODE:
        for field in ("dispatch_trigger", "tool_name", "completed_at"):
            if _is_empty(dispatch.get(field)):
                errors.append(f"{path.name}: dispatch.mode=subagent requires {field}")
        if _is_empty(dispatch.get("agent_id")) and _is_empty(dispatch.get("thread_id")):
            errors.append(f"{path.name}: dispatch.mode=subagent requires agent_id or thread_id")
        if _is_empty(dispatch.get("spawned_at")) and _is_empty(dispatch.get("resumed_at")):
            errors.append(f"{path.name}: dispatch.mode=subagent requires spawned_at or resumed_at")
    elif mode == INLINE_FALLBACK_MODE:
        for field in ("fallback_reason", "approved_by", "approved_at"):
            if _is_empty(dispatch.get(field)):
                errors.append(f"{path.name}: dispatch.mode=inline-fallback requires {field}")
    elif mode == HANDOFF_ONLY_MODE:
        # handoff-only 只创建交接文件，不代表目标 agent 已执行；
        # 不得携带 completed_at 等调度完成证据，否则等于假装已完成。
        if not _is_empty(dispatch.get("completed_at")):
            errors.append(
                f"{path.name}: dispatch.mode=handoff-only must not carry completed_at; "
                "handoff-only does not represent target agent execution"
            )

    return errors


def validate_handoff_dispatch_dir(project_root: Path) -> tuple[list[str], list[str]]:
    """校验 process/handoffs/ 下所有 handoff 文件。返回 (errors, checked_files)。"""
    errors: list[str] = []
    checked: list[str] = []
    handoff_dir = project_root / "process" / "handoffs"
    if not handoff_dir.is_dir():
        return errors, checked  # 无 handoff 目录不算错误
    for path in sorted(handoff_dir.glob("*.md")):
        checked.append(path.name)
        errors.extend(validate_handoff_dispatch(path))
    return errors, checked


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="meta-flow check handoff-dispatch",
        description="Validate dispatch evidence in process/handoffs/*.md frontmatter.",
    )
    parser.add_argument("--handoff", type=Path, default=None, help="Single handoff file to validate")
    parser.add_argument("--project-root", type=Path, default=Path.cwd(), help="Project root (scans process/handoffs/)")
    args = parser.parse_args(argv)

    if args.handoff:
        errors = validate_handoff_dispatch(args.handoff)
        checked = [args.handoff.name] if args.handoff.is_file() else []
    else:
        errors, checked = validate_handoff_dispatch_dir(args.project_root.resolve())

    print("Handoff Dispatch Check: " + ("FAIL" if errors else "OK"))
    if checked:
        print(f"- checked: {len(checked)} handoff file(s)")
    for error in errors:
        print(f"- ERROR: {error}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
