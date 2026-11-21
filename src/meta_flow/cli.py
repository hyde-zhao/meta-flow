"""mf 命令行入口。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .workspace import (
    WorkspaceError,
    build_status,
    detect_role,
    doctor,
    find_workspace_root,
    init_workspace,
)


def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _require_root(path: Path) -> Path:
    root = find_workspace_root(path)
    if root is None:
        raise WorkspaceError(
            f"未找到工作区：从 {path} 向上没有 contracts/project.yaml 与 deliveries/",
            code=2,
        )
    return root


def _cmd_init(args: argparse.Namespace) -> int:
    target = Path(args.path)
    name = args.name or target.expanduser().resolve().name
    deliveries = args.delivery or ["app"]
    root = init_workspace(target, name, deliveries, git=not args.no_git)
    print(f"已初始化工作区: {root}")
    print("下一步:")
    print("  1. 进入 contracts/，让 meta-manager 填写 project/INIT-CHECKLIST.md、PROJECT-PLAN 与 R1 路标")
    print("  2. 运行 mf doctor 校验")
    print("  3. 在 deliveries/<id>/ 安装 meta-worker")
    return 0


def _cmd_role(args: argparse.Namespace) -> int:
    role, root = detect_role(Path(args.path))
    if args.json:
        _print_json({"role": role, "workspace": str(root) if root else None})
    else:
        print(f"角色: {role}")
        if root:
            print(f"工作区: {root}")
    return 0 if role != "unbound" else 2


def _print_status(data: dict[str, Any]) -> None:
    project = data.get("project") or {}
    print(f"工作区: {data.get('workspace')}")
    print(f"项目: {project.get('name')} ({project.get('id')})")
    print(f"角色: {data.get('role')}")
    roadmap = data.get("roadmap")
    if isinstance(roadmap, dict):
        print(
            "路标: {id} — {title} ({range} → {target})".format(
                id=roadmap.get("id"),
                title=roadmap.get("title"),
                range=roadmap.get("version_range"),
                target=roadmap.get("version_target"),
            )
        )
    else:
        print("路标: 未找到")
    print(f"阶段: {data.get('phase')}")
    print(f"版本: {data.get('version')}")
    delivery_ids = [
        item.get("id")
        for item in (data.get("deliveries") or [])
        if isinstance(item, dict)
    ]
    print(f"交付库: {', '.join(str(item) for item in delivery_ids) or '无'}")
    tasks = data.get("tasks") or {}
    if tasks:
        rendered = " ".join(f"{key}={value}" for key, value in sorted(tasks.items()))
        print(f"任务: {rendered}")
    else:
        print("任务: 无")


def _cmd_status(args: argparse.Namespace) -> int:
    path = Path(args.path)
    root = _require_root(path)
    role, _ = detect_role(path)
    data = build_status(root, role)
    if args.json:
        _print_json(data)
    else:
        _print_status(data)
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    root = _require_root(Path(args.path))
    errors = doctor(root)
    if args.json:
        _print_json({"ok": not errors, "errors": errors})
    elif errors:
        print("mf doctor: FAIL")
        for error in errors:
            print(f"  - {error}")
    else:
        print("mf doctor: OK")
    return 0 if not errors else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mf",
        description="Meta Flow — AI 项目操作系统",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="初始化工作区（contracts + deliveries）")
    init_parser.add_argument("--path", default=".", help="工作区目录，默认当前目录")
    init_parser.add_argument("--name", help="项目名，默认使用目录名")
    init_parser.add_argument(
        "--delivery",
        action="append",
        help="交付库 id，可重复；默认 app",
    )
    init_parser.add_argument("--no-git", action="store_true", help="不为两个仓库执行 git init")
    init_parser.set_defaults(func=_cmd_init)

    role_parser = subparsers.add_parser("role", help="显示当前目录推导出的角色")
    role_parser.add_argument("--path", default=".", help="目录，默认当前目录")
    role_parser.add_argument("--json", action="store_true", help="输出 JSON")
    role_parser.set_defaults(func=_cmd_role)

    status_parser = subparsers.add_parser("status", help="显示工作区状态")
    status_parser.add_argument("--path", default=".", help="工作区内目录，默认当前目录")
    status_parser.add_argument("--json", action="store_true", help="输出 JSON")
    status_parser.set_defaults(func=_cmd_status)

    doctor_parser = subparsers.add_parser("doctor", help="校验工作区结构")
    doctor_parser.add_argument("--path", default=".", help="工作区内目录，默认当前目录")
    doctor_parser.add_argument("--json", action="store_true", help="输出 JSON")
    doctor_parser.set_defaults(func=_cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except WorkspaceError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return exc.code


if __name__ == "__main__":
    raise SystemExit(main())
