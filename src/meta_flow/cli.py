"""mf 命令行入口。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .global_store import (
    GlobalStoreError,
    bootstrap,
    dev_clone,
    dev_install,
    dev_status,
    dev_update,
)
from .install import (
    InstallError,
    install_root,
    install_worker,
    load_install_manifest,
    uninstall_claude,
    upgrade_project,
)
from .workspace import (
    INSTALL_REL,
    WorkspaceError,
    detect_role,
    doctor,
    doctor_global,
    find_workspace_root,
    workspace_add_project,
    workspace_init,
    workspace_link,
    workspace_status,
    workspace_sync,
)


def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _print_doctor(errors: list[str], as_json: bool) -> int:
    if as_json:
        _print_json({"ok": not errors, "errors": errors})
    elif errors:
        print("mf doctor: FAIL")
        for error in errors:
            print(f"  - {error}")
    else:
        print("mf doctor: OK")
    return 0 if not errors else 1


def _print_workspace_status(data: dict[str, Any]) -> None:
    project = data.get("project") or {}
    print(f"工作区: {data.get('root')}")
    print(f"项目: {project.get('name')} ({project.get('id')})")
    contract = data.get("contract") or {}
    print(f"契约库: {contract.get('dir')}")
    print(
        "  git: {branch} {commit} {dirty}".format(
            branch=contract.get("branch") or "-",
            commit=contract.get("commit") or "-",
            dirty="dirty" if contract.get("dirty") else "clean",
        )
    )
    subprojects = data.get("subprojects") or []
    if not subprojects:
        print("子项目: 无")
        return
    print("子项目:")
    for item in subprojects:
        print(
            "  - {id} {path} version={version} git={branch} {dirty}".format(
                id=item.get("id"),
                path=item.get("path"),
                version=item.get("version") or "-",
                branch=item.get("branch") or "-",
                dirty="dirty" if item.get("dirty") else "clean",
            )
        )


def _cmd_bootstrap(args: argparse.Namespace) -> int:
    home = bootstrap(repo_url=args.repo_url, force=args.force)
    print(f"全局模板库: {home}")
    print(f"manifest: {home / 'manifest.yaml'}")
    return 0


def _cmd_install_claude(args: argparse.Namespace) -> int:
    result = install_root(
        args.project_dir,
        agent=args.agent,
        init_contract=args.init_contract,
        link_mode=args.link_mode,
        force=args.force,
    )
    print(f"已安装 manager 到: {result['project_dir']}")
    print(f"agents: {', '.join(result['agents'])}")
    print(f"安装记录: {result['install_manifest']}")
    if result.get("contract"):
        contract = result["contract"]
        print(f"契约库: {contract['contract_dir']}")
        print(f"CLAUDE.md 导入: {contract['claude_import']}")
    return 0


def _cmd_install_worker(args: argparse.Namespace) -> int:
    delivery = args.delivery or Path(args.project_dir).expanduser().resolve().name
    result = install_worker(
        args.project_dir,
        delivery,
        workspace_root=args.workspace_root,
        contract_dir=args.contract_dir,
        remote=args.remote,
        force=args.force,
    )
    print(f"已安装 worker 到: {result['project_dir']}")
    print(f"delivery: {result['delivery']}")
    print(f"安装记录: {result['install_manifest']}")
    return 0


def _cmd_uninstall_claude(args: argparse.Namespace) -> int:
    result = uninstall_claude(args.project_dir, force=args.force, purge=args.purge)
    print(f"已卸载: {result['project_dir']}")
    if result["removed"]:
        print("removed: " + ", ".join(result["removed"]))
    if result["skipped"]:
        print("skipped (modified): " + ", ".join(result["skipped"]))
    return 0


def _cmd_upgrade(args: argparse.Namespace) -> int:
    result = upgrade_project(args.project_dir, force=args.force)
    print(f"已更新: {result['project_dir']} ({result['role']})")
    print("updated: " + ", ".join(result["updated"]))
    return 0


def _cmd_workspace_init(args: argparse.Namespace) -> int:
    result = workspace_init(
        args.project_dir,
        args.name,
        contract_dir=args.contract_dir,
        contract_remote=args.contract_remote,
        link_mode=args.link_mode,
        force=args.force,
    )
    print(f"契约库: {result['contract_dir']}")
    print(f"CLAUDE.md 导入: {result['claude_import']}")
    print(f"README 链接: {result['readme_link_mode']}")
    return 0


def _cmd_workspace_add_project(args: argparse.Namespace) -> int:
    result = workspace_add_project(
        args.project_dir,
        args.name,
        args.path,
        remote=args.remote,
        delivery=args.delivery,
    )
    print(f"子项目: {result['subproject']}")
    print(f"delivery: {result['delivery']}")
    return 0


def _cmd_workspace_link(args: argparse.Namespace) -> int:
    result = workspace_link(args.project_dir)
    print(f"已重建链接: {result['root']}")
    print(f"CLAUDE.md 导入: {result['claude_import']}")
    print(f"README 链接: {result['readme_link_mode']}")
    return 0


def _cmd_workspace_sync(args: argparse.Namespace) -> int:
    result = workspace_sync(args.project_dir, check=args.check, force=args.force)
    if result["errors"]:
        print("mf workspace sync: FAIL")
        for error in result["errors"]:
            print(f"  - {error}")
        return 1
    print("mf workspace sync: OK")
    return 0


def _cmd_workspace_status(args: argparse.Namespace) -> int:
    root = find_workspace_root(Path(args.project_dir))
    if root is None:
        raise WorkspaceError("未找到工作区；先运行 mf workspace init", 2)
    data = workspace_status(root)
    if args.json:
        _print_json(data)
    else:
        _print_workspace_status(data)
    return 0


def _cmd_role(args: argparse.Namespace) -> int:
    role, path = detect_role(Path(args.path))
    if args.json:
        _print_json({"role": role, "path": str(path) if path else None})
    else:
        print(f"角色: {role}")
        if path:
            print(f"路径: {path}")
    return 0 if role != "unbound" else 2


def _cmd_status(args: argparse.Namespace) -> int:
    path = Path(args.path).expanduser().resolve()
    root = find_workspace_root(path)
    if root is not None:
        data = workspace_status(root)
        if args.json:
            _print_json(data)
        else:
            _print_workspace_status(data)
        return 0
    if (path / INSTALL_REL).is_file():
        data = load_install_manifest(path)
        if args.json:
            _print_json(data)
        else:
            print(f"安装目录: {path}")
            print(f"角色: {data.get('role')}")
            print(f"agents: {', '.join(data.get('agents', []))}")
            print(f"contract: {data.get('contract_dir') or '-'}")
        return 0
    raise WorkspaceError("未找到工作区或项目安装", 2)


def _cmd_doctor(args: argparse.Namespace) -> int:
    if args.global_scope:
        return _print_doctor(doctor_global(), args.json)
    path = Path(args.path).expanduser().resolve()
    root = find_workspace_root(path)
    if root is None:
        if (path / INSTALL_REL).is_file():
            root = path
        else:
            raise WorkspaceError("未找到工作区或项目安装", 2)
    return _print_doctor(doctor(root), args.json)


def _cmd_dev_clone(args: argparse.Namespace) -> int:
    source = dev_clone(dest=args.dest, repo=args.repo)
    print(f"源码: {source}")
    return 0


def _cmd_dev_update(args: argparse.Namespace) -> int:
    source = dev_update(source=args.source)
    print(f"已更新: {source}")
    return 0


def _cmd_dev_install(args: argparse.Namespace) -> int:
    source = dev_install(source=args.source, yes=args.yes)
    print(f"已从源码安装全局 mf: {source}")
    return 0


def _cmd_dev_status(args: argparse.Namespace) -> int:
    data = dev_status(source=args.source)
    if args.json:
        _print_json(data)
    else:
        print(f"repo: {data.get('repo_url')}")
        print(f"source: {data.get('source_dir')}")
        print(f"branch: {data.get('branch') or '-'}")
        print(f"commit: {data.get('commit') or '-'}")
        print(f"dirty: {data.get('dirty')}")
        print(f"tool: {data.get('tool_version')}")
        print(f"templates: {data.get('template_version')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mf", description="Meta Flow — AI 项目操作系统")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    bootstrap_p = sub.add_parser("bootstrap", help="创建/刷新 ~/.meta-flow 全局模板库")
    bootstrap_p.add_argument("--repo-url", help="meta-flow 源码仓库地址")
    bootstrap_p.add_argument("--force", action="store_true", help="覆盖已有全局模板")
    bootstrap_p.set_defaults(func=_cmd_bootstrap)

    install_p = sub.add_parser("install", help="安装项目 agent")
    install_sub = install_p.add_subparsers(dest="target", required=True)
    install_claude = install_sub.add_parser("claude", help="安装根目录 manager（可选 maintainer）")
    install_claude.add_argument("--project-dir", default=".")
    install_claude.add_argument("--agent", choices=["manager", "maintainer"], default="manager")
    install_claude.add_argument("--init-contract", action="store_true", help="立即创建 <项目>-contract")
    install_claude.add_argument("--link-mode", choices=["auto", "symlink", "copy"], default="auto")
    install_claude.add_argument("--force", action="store_true")
    install_claude.set_defaults(func=_cmd_install_claude)
    install_worker_p = install_sub.add_parser("worker", help="安装子项目 worker")
    install_worker_p.add_argument("--project-dir", default=".")
    install_worker_p.add_argument("--delivery")
    install_worker_p.add_argument("--workspace-root")
    install_worker_p.add_argument("--contract-dir")
    install_worker_p.add_argument("--remote")
    install_worker_p.add_argument("--force", action="store_true")
    install_worker_p.set_defaults(func=_cmd_install_worker)

    uninstall_p = sub.add_parser("uninstall", help="按 .meta-flow/install.yaml 卸载")
    uninstall_sub = uninstall_p.add_subparsers(dest="target", required=True)
    uninstall_claude_p = uninstall_sub.add_parser("claude")
    uninstall_claude_p.add_argument("--project-dir", default=".")
    uninstall_claude_p.add_argument("--force", action="store_true")
    uninstall_claude_p.add_argument("--purge", action="store_true", help="同时移除 workspace 元数据")
    uninstall_claude_p.set_defaults(func=_cmd_uninstall_claude)

    workspace_p = sub.add_parser("workspace", help="初始化和维护多仓工作区")
    workspace_sub = workspace_p.add_subparsers(dest="action", required=True)
    ws_init = workspace_sub.add_parser("init")
    ws_init.add_argument("--project-dir", default=".")
    ws_init.add_argument("--name", required=True)
    ws_init.add_argument("--contract-dir")
    ws_init.add_argument("--contract-remote")
    ws_init.add_argument("--link-mode", choices=["auto", "symlink", "copy"], default="auto")
    ws_init.add_argument("--force", action="store_true")
    ws_init.set_defaults(func=_cmd_workspace_init)
    ws_add = workspace_sub.add_parser("add-project")
    ws_add.add_argument("--project-dir", default=".")
    ws_add.add_argument("--name", required=True)
    ws_add.add_argument("--path", required=True)
    ws_add.add_argument("--remote")
    ws_add.add_argument("--delivery")
    ws_add.set_defaults(func=_cmd_workspace_add_project)
    ws_link = workspace_sub.add_parser("link")
    ws_link.add_argument("--project-dir", default=".")
    ws_link.set_defaults(func=_cmd_workspace_link)
    ws_sync = workspace_sub.add_parser("sync")
    ws_sync.add_argument("--project-dir", default=".")
    ws_sync.add_argument("--check", action="store_true")
    ws_sync.add_argument("--force", action="store_true")
    ws_sync.set_defaults(func=_cmd_workspace_sync)
    ws_status = workspace_sub.add_parser("status")
    ws_status.add_argument("--project-dir", default=".")
    ws_status.add_argument("--json", action="store_true")
    ws_status.set_defaults(func=_cmd_workspace_status)

    dev_p = sub.add_parser("dev", help="meta-flow 源码维护（maintainer）")
    dev_sub = dev_p.add_subparsers(dest="action", required=True)
    dev_clone_p = dev_sub.add_parser("clone")
    dev_clone_p.add_argument("--dest")
    dev_clone_p.add_argument("--repo")
    dev_clone_p.set_defaults(func=_cmd_dev_clone)
    dev_update_p = dev_sub.add_parser("update")
    dev_update_p.add_argument("--source")
    dev_update_p.set_defaults(func=_cmd_dev_update)
    dev_install_p = dev_sub.add_parser("install")
    dev_install_p.add_argument("--source")
    dev_install_p.add_argument("--yes", action="store_true")
    dev_install_p.set_defaults(func=_cmd_dev_install)
    dev_status_p = dev_sub.add_parser("status")
    dev_status_p.add_argument("--source")
    dev_status_p.add_argument("--json", action="store_true")
    dev_status_p.set_defaults(func=_cmd_dev_status)

    upgrade_p = sub.add_parser("upgrade", help="按全局模板更新项目安装")
    upgrade_p.add_argument("--project-dir", default=".")
    upgrade_p.add_argument("--force", action="store_true")
    upgrade_p.set_defaults(func=_cmd_upgrade)

    role_p = sub.add_parser("role", help="显示当前目录角色")
    role_p.add_argument("--path", default=".")
    role_p.add_argument("--json", action="store_true")
    role_p.set_defaults(func=_cmd_role)

    status_p = sub.add_parser("status", help="显示工作区或安装状态")
    status_p.add_argument("--path", default=".")
    status_p.add_argument("--json", action="store_true")
    status_p.set_defaults(func=_cmd_status)

    doctor_p = sub.add_parser("doctor", help="校验全局/项目/工作区")
    doctor_p.add_argument("--path", default=".")
    doctor_p.add_argument("--global", dest="global_scope", action="store_true")
    doctor_p.add_argument("--json", action="store_true")
    doctor_p.set_defaults(func=_cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (WorkspaceError, InstallError, GlobalStoreError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return getattr(exc, "code", 1)


if __name__ == "__main__":
    raise SystemExit(main())
