"""Validate dispatch evidence in process/handoffs/*.md frontmatter.

防止调度证据断链：handoff 文件的 dispatch 块声明 mode=subagent 时，
必须回填真实子 agent 调度证据（canonical_role / dispatch_trigger /
agent_id 或 thread_id / tool_name / spawned_at 或 resumed_at）。只有
handoff 进入终态时才要求 completed_at；进行中的真实调度不得伪造完成时间。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from meta_flow.project.process_route import _resolve_runtime_ref
from meta_flow.state.event_ledger import parse_handoff_dispatch_record

# 已知 dispatch.mode 取值
SUBAGENT_MODE = "subagent"
INLINE_FALLBACK_MODE = "inline-fallback"
HANDOFF_ONLY_MODE = "handoff-only"
KNOWN_MODES = (SUBAGENT_MODE, INLINE_FALLBACK_MODE, HANDOFF_ONLY_MODE)

# handoff 顶层 status 的当前生命周期枚举。进行中状态不代表执行完成；
# 终态统一使用现有 completed_at 字段记录终止时间。
ACTIVE_SUBAGENT_STATUSES = frozenset({"dispatched", "running", "in-progress"})
TERMINAL_SUBAGENT_STATUSES = frozenset(
    {
        "completed",
        "success",
        "succeeded",
        "passed",
        "failed",
        "interrupted",
        "cancelled",
        "canceled",
        "superseded",
        "closed",
        # 当前过程仓中仍在使用的 v1 终态别名；它们同样必须有 completed_at。
        "agent-completed",
        "agent-completed-pass",
        "rework-round-2-completed",
    }
)
KNOWN_HANDOFF_STATUSES = ACTIVE_SUBAGENT_STATUSES | TERMINAL_SUBAGENT_STATUSES

# 视为空的占位值（与 human_gate.EMPTY_VALUES 思路一致）
EMPTY_VALUES = {"", "-", "—", "n/a", "N/A", "无", "不适用"}


def _is_empty(value: Any) -> bool:
    return value is None or str(value).strip().strip('"').strip("'") in EMPTY_VALUES


def _parse_handoff_status(text: str) -> str:
    """读取 Markdown frontmatter 的顶层 ``status``，不接受正文或嵌套字段。"""
    if not text.startswith("---\n"):
        raise ValueError("missing or invalid YAML frontmatter")
    end = text.find("\n---", 4)
    if end == -1:
        raise ValueError("missing or invalid YAML frontmatter")
    for line in text[4:end].splitlines():
        if not line or line.startswith((" ", "\t")) or ":" not in line:
            continue
        key, _, value = line.partition(":")
        if key.strip() == "status":
            return value.strip().strip('"').strip("'")
    raise ValueError("missing top-level status in frontmatter")


def validate_handoff_dispatch(path: Path) -> list[str]:
    """校验单个 handoff 文件的 dispatch 块。返回错误信息列表（空表示通过）。"""
    errors: list[str] = []
    if not path.is_file():
        return [f"handoff file not found: {path}"]
    text = path.read_text(encoding="utf-8")
    try:
        record = parse_handoff_dispatch_record(text)
        status = _parse_handoff_status(text)
    except ValueError as exc:
        return [f"{path.name}: {exc}"]

    if _is_empty(status):
        return [f"{path.name}: top-level status is empty"]
    if status not in KNOWN_HANDOFF_STATUSES:
        return [
            f"{path.name}: top-level status={status!r} is not a known status "
            f"(expected one of {sorted(KNOWN_HANDOFF_STATUSES)})"
        ]

    mode = record.get("mode").strip()
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
    if _is_empty(record.get("canonical_role")):
        errors.append(f"{path.name}: dispatch.mode={mode} requires canonical_role")

    if mode == SUBAGENT_MODE:
        for field in ("dispatch_trigger", "tool_name"):
            if _is_empty(record.get(field)):
                errors.append(f"{path.name}: dispatch.mode=subagent requires {field}")
        if _is_empty(record.get("agent_id")) and _is_empty(record.get("thread_id")):
            errors.append(f"{path.name}: dispatch.mode=subagent requires agent_id or thread_id")
        if _is_empty(record.get("spawned_at")) and _is_empty(record.get("resumed_at")):
            errors.append(f"{path.name}: dispatch.mode=subagent requires spawned_at or resumed_at")
        if status in ACTIVE_SUBAGENT_STATUSES:
            if not _is_empty(record.get("completed_at")):
                errors.append(
                    f"{path.name}: active subagent status={status} must not carry completed_at"
                )
        elif _is_empty(record.get("completed_at")):
            errors.append(f"{path.name}: terminal subagent status={status} requires completed_at")
    elif mode == INLINE_FALLBACK_MODE:
        for field in ("fallback_reason", "approved_by", "approved_at"):
            if _is_empty(record.get(field)):
                errors.append(f"{path.name}: dispatch.mode=inline-fallback requires {field}")
    elif mode == HANDOFF_ONLY_MODE:
        # handoff-only 只创建交接文件，不代表目标 agent 已执行；
        # 不得携带 completed_at 等调度完成证据，否则等于假装已完成。
        if not _is_empty(record.get("completed_at")):
            errors.append(
                f"{path.name}: dispatch.mode=handoff-only must not carry completed_at; "
                "handoff-only does not represent target agent execution"
            )

    return errors


def validate_handoff_dispatch_dir(
    project_root: Path, *, strict_all: bool = False
) -> tuple[list[str], list[str]]:
    """校验 handoff 目录。

    默认只检查已经声明 frontmatter ``dispatch`` 契约的 current-format
    文件；历史 handoff 不会被倒推为具备当时不存在的调度证据。显式
    ``strict_all`` 用于迁移审计，要求目录内每个文件都满足当前契约。
    """
    errors: list[str] = []
    checked: list[str] = []
    handoff_dir = _resolve_runtime_ref(project_root, "process/handoffs")
    if not handoff_dir.is_dir():
        return errors, checked  # 无 handoff 目录不算错误
    for path in sorted(handoff_dir.glob("*.md")):
        if not strict_all:
            try:
                parse_handoff_dispatch_record(path.read_text(encoding="utf-8"))
            except ValueError:
                continue
        checked.append(path.name)
        errors.extend(validate_handoff_dispatch(path))
    return errors, checked


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="meta-flow check handoff-dispatch",
        description="Validate dispatch evidence in process/handoffs/*.md frontmatter.",
    )
    parser.add_argument(
        "--handoff", type=Path, default=None, help="Single handoff file to validate"
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Project root (scans process/handoffs/)",
    )
    parser.add_argument(
        "--strict-all",
        action="store_true",
        help="Require every handoff in the directory to use the current dispatch frontmatter contract",
    )
    args = parser.parse_args(argv)

    if args.handoff:
        errors = validate_handoff_dispatch(args.handoff)
        checked = [args.handoff.name] if args.handoff.is_file() else []
    else:
        errors, checked = validate_handoff_dispatch_dir(
            args.project_root.resolve(), strict_all=args.strict_all
        )

    print("Handoff Dispatch Check: " + ("FAIL" if errors else "OK"))
    if checked:
        print(f"- checked: {len(checked)} handoff file(s)")
    for error in errors:
        print(f"- ERROR: {error}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
