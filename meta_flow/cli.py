"""Command line entry point for Meta Flow."""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


def _candidate_roots() -> list[Path]:
    roots: list[Path] = []
    if os.environ.get("META_FLOW_SOURCE"):
        roots.append(Path(os.environ["META_FLOW_SOURCE"]).expanduser())

    cwd = Path.cwd()
    roots.extend([cwd, *cwd.parents])

    package_root = Path(__file__).resolve().parent
    roots.extend([package_root.parent, *package_root.parents])
    return roots


def _find_installer() -> Path:
    for root in _candidate_roots():
        candidate = root / "delivery" / "scripts" / "install.py"
        if candidate.is_file():
            return candidate
    raise SystemExit(
        "无法定位 Meta Flow 安装器。请在 meta-flow 仓库内运行，"
        "或设置 META_FLOW_SOURCE 指向包含 delivery/scripts/install.py 的目录。"
    )


def _find_workspace_root() -> Path:
    for root in _candidate_roots():
        if (root / "process" / "STATE.md").is_file():
            return root
    return Path.cwd()


def _read_state() -> tuple[Path, str]:
    root = _find_workspace_root()
    state_path = root / "process" / "STATE.md"
    if not state_path.is_file():
        raise SystemExit(f"未找到运行态文件: {state_path}")
    return state_path, state_path.read_text(encoding="utf-8")


def _frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---", 4)
    if end == -1:
        return text
    return text[4:end]


def _scalar_value(frontmatter: str, key: str, *, nested: bool = False) -> str:
    prefix = "  " if nested else ""
    for line in frontmatter.splitlines():
        if not line.startswith(f"{prefix}{key}:"):
            continue
        raw = line.split(":", 1)[1].strip()
        return raw.strip('"')
    return ""


def _state_summary() -> dict[str, str]:
    state_path, text = _read_state()
    fm = _frontmatter(text)
    return {
        "state_path": str(state_path),
        "workflow_mode": _scalar_value(fm, "workflow_mode") or "standard",
        "current_phase": _scalar_value(fm, "current_phase") or "unknown",
        "blocked": _scalar_value(fm, "blocked") or "false",
        "active_change": _scalar_value(fm, "active_change"),
        "last_action": _scalar_value(fm, "last_action"),
        "next_action": _scalar_value(fm, "next_action"),
        "pending_gate": _scalar_value(fm, "pending_gate", nested=True),
        "pending_checklist_path": _scalar_value(fm, "pending_checklist_path", nested=True),
        "subagent_auto_dispatch": _scalar_value(fm, "subagent_auto_dispatch", nested=True) or "enabled",
    }


def _print_status() -> None:
    summary = _state_summary()
    print(f"STATE: {summary['state_path']}")
    print(f"workflow_mode: {summary['workflow_mode']}")
    print(f"current_phase: {summary['current_phase']}")
    print(f"blocked: {summary['blocked']}")
    print(f"active_change: {summary['active_change'] or '-'}")
    print(f"pending_gate: {summary['pending_gate'] or '-'}")
    print(f"pending_checklist_path: {summary['pending_checklist_path'] or '-'}")
    print(f"subagent_auto_dispatch: {summary['subagent_auto_dispatch']}")
    print(f"last_action: {summary['last_action'] or '-'}")
    print(f"next_action: {summary['next_action'] or '-'}")


def _print_next() -> None:
    summary = _state_summary()
    if summary["blocked"].lower() == "true":
        print("当前工作流处于 blocked 状态，请先查看 STATE.md 中的阻塞原因。")
        return
    if summary["pending_gate"]:
        path = summary["pending_checklist_path"] or "checkpoints/CP*.md"
        print(f"等待用户确认 {summary['pending_gate']}。请审查 {path} 后回复 approve / 修改: <具体修改点> / reject。")
        return
    print(summary["next_action"] or f"当前阶段为 {summary['current_phase']}，请使用 @meta-po 继续推进。")


def _run_doctor() -> None:
    root = _find_workspace_root()
    problems: list[str] = []
    warnings: list[str] = []

    state_path = root / "process" / "STATE.md"
    if not state_path.is_file():
        problems.append(f"缺少 {state_path}")
    for rel in ("process/checks", "checkpoints"):
        if not (root / rel).is_dir():
            warnings.append(f"缺少目录 {rel}")
    legacy_cp4 = root / "checkpoints" / "CP4-STORY-PLAN-REVIEW.md"
    if legacy_cp4.exists():
        warnings.append("发现旧 CP4 人工审查稿；当前规则下 CP4 只做自动预检并汇入 CP5。")

    if state_path.is_file():
        summary = _state_summary()
        if summary["subagent_auto_dispatch"] not in {"enabled", "disabled"}:
            warnings.append("orchestrator_session.subagent_auto_dispatch 建议为 enabled 或 disabled")
        if summary["workflow_mode"] not in {"standard", "fast-lane"}:
            warnings.append("workflow_mode 建议为 standard 或 fast-lane")

    if problems:
        print("Doctor: FAIL")
        for item in problems:
            print(f"- ERROR: {item}")
        for item in warnings:
            print(f"- WARN: {item}")
        raise SystemExit(1)

    print("Doctor: OK")
    for item in warnings:
        print(f"- WARN: {item}")


def _print_help() -> None:
    print(
        "usage: meta-flow <command> [options]\n\n"
        "Commands:\n"
        "  install    Install Meta Flow assets into Claude Code, Codex, or OpenClaw.\n"
        "  uninstall  Uninstall Meta Flow assets recorded in INSTALL-MANIFEST.\n"
        "  status     Show current process/STATE.md summary.\n"
        "  next       Show the next workflow action or pending gate.\n"
        "  doctor     Check local Meta Flow runtime structure.\n\n"
        "Examples:\n"
        "  meta-flow install codex --scope user --component rules\n"
        "  meta-flow install claude --scope project --project-dir /path/to/repo\n"
        "  meta-flow uninstall codex --scope user\n"
        "  meta-flow status\n"
    )


def _run_installer(command: str, args: list[str]) -> None:
    installer = _find_installer()
    forwarded = [*args]
    if command == "uninstall":
        forwarded = ["uninstall", *forwarded]
    original_argv = sys.argv[:]
    try:
        sys.argv = [f"meta-flow {command}", *forwarded]
        namespace = runpy.run_path(str(installer), run_name="__meta_flow_installer__")
        namespace["main"]()
    finally:
        sys.argv = original_argv


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in {"-h", "--help"}:
        _print_help()
        return

    command = args[0]
    if command == "status":
        _print_status()
        return
    if command == "next":
        _print_next()
        return
    if command == "doctor":
        _run_doctor()
        return
    if command in {"install", "uninstall"}:
        _run_installer(command, args[1:])
        return
    raise SystemExit(f"未知命令: {command}. 目前支持: install, uninstall, status, next, doctor")


if __name__ == "__main__":
    main()
