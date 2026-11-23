"""mf 命令行入口。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml

from . import __version__, bug, context, guard, knowledge, req, roadmap, state, verify
from .global_store import (
    GlobalStoreError,
    bootstrap,
    dev_clone,
    dev_install,
    dev_status,
    dev_update,
)
from .improve import (
    ImproveError,
    find_improvement,
    import_improvement,
    list_improvements,
    new_improvement,
    source_import,
    source_list,
    source_update,
    submit_improvement,
    validate_improvement,
)
from .install import (
    InstallError,
    install_root,
    install_worker,
    load_install_manifest,
    uninstall_claude,
    upgrade_project,
)
from .task import (
    TaskError,
    accept_task,
    create_task,
    graph,
    list_tasks,
    load_task,
    next_tasks,
    packet_text,
    plan_tasks,
    prompt_text,
    reject_task,
    release_task,
    start_task,
    submit_task,
)
from .task import (
    summary as task_summary,
)
from .workspace import (
    INSTALL_REL,
    WorkspaceError,
    detect_role,
    doctor,
    doctor_global,
    find_workspace_root,
    resolve_contract,
    workspace_add_project,
    workspace_init,
    workspace_link,
    workspace_status,
    workspace_sync,
)


def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


GLOBAL_COMMANDS = {"bootstrap", "install", "uninstall", "dev", "upgrade", "role", "status", "doctor"}
MANAGER_PROJECT_COMMANDS = {
    "workspace",
    "req",
    "roadmap",
    "phase",
    "bug",
    "knowledge",
    "verify",
    "release",
    "context",
    "archive",
    "log",
}
ROLE_VALUES = {"manager", "worker", "maintainer"}


def _effective_role(args: argparse.Namespace) -> tuple[str, Path | None]:
    role, root = detect_role(Path.cwd())
    if role != "unbound":
        return role, root
    env_role = os.environ.get("MF_ROLE")
    if env_role in ROLE_VALUES:
        return env_role, None
    for attr in ("project_dir", "path"):
        raw = getattr(args, attr, None)
        if raw:
            candidate_role, candidate_root = detect_role(Path(raw))
            if candidate_role != "unbound":
                return candidate_role, candidate_root
    return "unbound", None


def _enforce_role(args: argparse.Namespace) -> None:
    command = str(getattr(args, "command", ""))
    action = str(getattr(args, "action", "") or "")
    role, _ = _effective_role(args)
    if command == "hook":
        return
    if command in {"role", "status", "doctor", "bootstrap"}:
        return
    if command in {"install", "uninstall", "upgrade"}:
        actor_role, _ = detect_role(Path.cwd())
        if actor_role == "unbound":
            actor_role = os.environ.get("MF_ROLE", "unbound")
        if actor_role not in {"manager", "maintainer", "unbound"}:
            raise WorkspaceError("worker 不能安装/卸载/升级项目", 3)
        return
    if command == "dev":
        if role not in {"maintainer", "unbound"}:
            raise WorkspaceError("dev 命令只允许 maintainer", 3)
        return
    if command == "workspace":
        if role != "manager":
            raise WorkspaceError("workspace 命令只允许 manager", 3)
        return
    if command == "task":
        worker_actions = {"list", "show", "prompt"}
        manager_actions = {"create", "accept", "reject", "release", "graph", "plan", "next", "summary"}
        if action in {"start", "submit"}:
            if role != "worker":
                raise WorkspaceError(f"task {action} 只允许 worker", 3)
            return
        if action in worker_actions and role not in {"worker", "manager"}:
            raise WorkspaceError(f"task {action} 只允许 worker/manager", 3)
        if action in manager_actions and role != "manager":
            raise WorkspaceError(f"task {action} 只允许 manager", 3)
        if action not in worker_actions | manager_actions | {"start", "submit"}:
            raise WorkspaceError(f"未知 task 动作: {action}", 3)
        return
    if command == "improve":
        if role == "manager":
            return
        if role == "maintainer":
            if action in {"list", "show"} and (args.inbox if hasattr(args, "inbox") else False):
                return
            raise WorkspaceError("maintainer 只能通过 dev improve 维护源码", 3)
        if role == "worker":
            if action in {"new", "list", "show", "validate"} and getattr(args, "local", False):
                return
            raise WorkspaceError("worker 只能使用 improve --local 创建/查看本地 MFP", 3)
        raise WorkspaceError("无法确定角色；请在工作区根/子项目运行或设置 MF_ROLE", 3)
    if command in MANAGER_PROJECT_COMMANDS:
        if role != "manager":
            raise WorkspaceError(f"{command} 命令只允许 manager", 3)
        return
    if role == "unbound":
        raise WorkspaceError("无法确定角色；请在项目根/子项目运行或设置 MF_ROLE", 3)


def _worker_delivery(role_root: Path | None) -> str | None:
    if role_root is None:
        return None
    path = role_root / "delivery.yaml"
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return None
    return str(data.get("id")) if isinstance(data, dict) and data.get("id") else None


def _ensure_worker_scope(args: argparse.Namespace, task: dict[str, Any]) -> None:
    role, root = _effective_role(args)
    if role != "worker":
        return
    delivery = _worker_delivery(root)
    if delivery and task.get("delivery") and task.get("delivery") != delivery:
        raise WorkspaceError(f"worker 只能访问交付库 {delivery} 的任务", 3)


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
    hot = data.get("hot_state") or {}
    if hot:
        print(f"当前: {hot.get('roadmap')} / {hot.get('phase')} ({hot.get('phase_status') or '-'})")
        tasks = data.get("tasks") or {}
        print(f"任务: {tasks.get('counts') or {}}")
        if hot.get("truncated"):
            print(
                f"state: 已截断（active_tasks_total={hot.get('active_tasks_total')}）；"
                "完整列表用 mf task summary"
            )
        for lease in hot.get("active_leases") or []:
            print(
                f"  lease: {lease.get('task')} owner={lease.get('owner')} "
                f"wave={lease.get('wave')} expires={lease.get('expires_at')}"
            )
        print(f"下一动作: {hot.get('next_action') or '-'}")
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


def _workspace_view(root: Path) -> dict[str, Any]:
    data = workspace_status(root)
    try:
        contract = resolve_contract(root)
        data["hot_state"] = state.refresh_current(contract)
        data["tasks"] = task_summary(root)
    except WorkspaceError:
        pass
    return data


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
    data = _workspace_view(root)
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
        data = _workspace_view(root)
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


def _load_mfp(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ImproveError(f"{path} 顶层必须是映射")
    return data


def _cmd_improve_new(args: argparse.Namespace) -> int:
    path = new_improvement(args.project_dir, args.title, local=args.local)
    print(f"改进包: {path}")
    return 0


def _cmd_improve_list(args: argparse.Namespace) -> int:
    scope = "inbox" if args.inbox else "local" if args.local else "contract"
    items = list_improvements(args.project_dir, scope=scope, status=args.status)
    if args.json:
        _print_json(items)
        return 0
    if not items:
        print("没有改进包")
        return 0
    for item in items:
        print(
            "{id} {status} {priority} {classification} {title}".format(
                id=item.get("id"),
                status=item.get("status"),
                priority=item.get("priority"),
                classification=item.get("classification"),
                title=item.get("title"),
            )
        )
    return 0


def _cmd_improve_show(args: argparse.Namespace) -> int:
    scope = "inbox" if args.inbox else "local" if args.local else "contract"
    path = find_improvement(args.project_dir, args.mfp_id, scope=scope)
    data = _load_mfp(path)
    if args.json:
        _print_json(data)
    else:
        print(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    return 0


def _cmd_improve_validate(args: argparse.Namespace) -> int:
    scope = "local" if args.local else "contract"
    path = find_improvement(args.project_dir, args.mfp_id, scope=scope)
    errors = validate_improvement(_load_mfp(path))
    if args.json:
        _print_json({"ok": not errors, "errors": errors})
    elif errors:
        print("MFP validate: FAIL")
        for error in errors:
            print(f"  - {error}")
    else:
        print("MFP validate: OK")
    return 0 if not errors else 1


def _cmd_improve_submit(args: argparse.Namespace) -> int:
    path = submit_improvement(args.project_dir, args.mfp_id)
    print(f"已提交到 inbox: {path}")
    return 0


def _cmd_improve_import(args: argparse.Namespace) -> int:
    path = import_improvement(args.project_dir, args.source)
    print(f"已导入 contract: {path}")
    return 0


def _cmd_dev_improve_import(args: argparse.Namespace) -> int:
    result = source_import(
        args.ref,
        source=args.source,
        kind=args.kind,
        already_implemented=args.already_implemented,
        version=args.version,
        commit=args.commit,
        note=args.note,
    )
    print(f"源码: {result['source']}")
    print(f"MFP: {result['mfp']} → {result['destination']}")
    print(f"classification: {result['classification']}")
    if result.get("record"):
        print(f"record: {result['record']}")
    return 0


def _cmd_dev_improve_list(args: argparse.Namespace) -> int:
    data = source_list(source=args.source, scope=args.scope)
    if args.json:
        _print_json(data)
        return 0
    for section, items in data.items():
        print(f"[{section}]")
        if not items:
            print("  (empty)")
            continue
        for item in items:
            print(
                "  {id} {status} {title}".format(
                    id=item.get("id"),
                    status=item.get("status"),
                    title=item.get("title"),
                )
            )
    return 0


def _cmd_dev_improve_update(args: argparse.Namespace) -> int:
    path = source_update(
        args.mfp_id,
        args.status,
        source=args.source,
        version=args.version,
        commit=args.commit,
        note=args.note,
    )
    print(f"已更新: {path}")
    return 0


def _cmd_task_create(args: argparse.Namespace) -> int:
    from_data = None
    if args.from_file:
        raw = yaml.safe_load(Path(args.from_file).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise TaskError("--from 文件顶层必须是映射")
        from_data = raw
    acceptance = [
        {"id": f"A{index}", "method": "artifact", "expect": text}
        for index, text in enumerate(args.acceptance or [], start=1)
    ]
    result = create_task(
        args.project_dir,
        args.title or "",
        kind=args.kind,
        delivery=args.delivery,
        risk=args.risk,
        effort=args.effort,
        review_mode=args.review_mode,
        reviews=args.reviews,
        review_scope=args.review_scope or [],
        allowed_paths=args.allowed_path or [],
        acceptance=acceptance or None,
        wave=args.wave,
        depends_on=args.depends_on or [],
        fixes=args.fixes or [],
        with_review=not args.no_review,
        from_data=from_data,
    )
    print(f"任务: {result['task']} ({result['status']}, risk={result['risk']})")
    if result.get("review_task"):
        print(f"评审任务: {result['review_task']}")
    print(f"bundle: {result['bundle']}")
    print(f"下一步: mf task prompt {result['task']}")
    return 0


def _cmd_task_list(args: argparse.Namespace) -> int:
    role, root = _effective_role(args)
    delivery = _worker_delivery(root) if role == "worker" else None
    items = list_tasks(args.project_dir, status=args.status, delivery=delivery)
    if args.json:
        _print_json(items)
        return 0
    if not items:
        print("没有任务")
        return 0
    for item in items:
        print(
            "{id} {status} {kind} risk={risk} next={next_owner} {title}".format(
                id=item.get("id"),
                status=item.get("status"),
                kind=item.get("kind"),
                risk=(item.get("risk") or {}).get("level"),
                next_owner=item.get("next_owner"),
                title=item.get("title"),
            )
        )
    return 0


def _cmd_task_show(args: argparse.Namespace) -> int:
    path, data = load_task(args.project_dir, args.task_id)
    _ensure_worker_scope(args, data)
    if args.packet:
        print(packet_text(args.project_dir, args.task_id))
        return 0
    if args.review_packet:
        print(packet_text(args.project_dir, args.task_id, review=True))
        return 0
    if args.json:
        _print_json(data)
    else:
        print(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    return 0


def _cmd_task_start(args: argparse.Namespace) -> int:
    _, current = load_task(args.project_dir, args.task_id)
    _ensure_worker_scope(args, current)
    data = start_task(args.project_dir, args.task_id, owner=args.owner)
    print(f"{data['id']} -> {data['status']} (next={data['next_owner']})")
    return 0


def _cmd_task_submit(args: argparse.Namespace) -> int:
    _, current = load_task(args.project_dir, args.task_id)
    _ensure_worker_scope(args, current)
    data = submit_task(
        args.project_dir,
        args.task_id,
        handoff=args.handoff,
        dev_record=args.dev_record,
        owner=args.owner,
    )
    print(f"{data['id']} -> {data['status']} (next={data['next_owner']})")
    return 0


def _cmd_task_accept(args: argparse.Namespace) -> int:
    data = accept_task(
        args.project_dir,
        args.task_id,
        verdict=args.verdict,
        note=args.note,
        user_approved_by=args.user_approved_by,
    )
    print(f"{data['id']} -> {data['status']} (verdict={args.verdict})")
    return 0


def _cmd_task_reject(args: argparse.Namespace) -> int:
    data = reject_task(args.project_dir, args.task_id, args.reason)
    print(f"{data['id']} -> {data['status']} (next={data['next_owner']})")
    return 0


def _cmd_task_prompt(args: argparse.Namespace) -> int:
    _, data = load_task(args.project_dir, args.task_id)
    _ensure_worker_scope(args, data)
    print(prompt_text(args.project_dir, args.task_id), end="")
    return 0


def _cmd_task_graph(args: argparse.Namespace) -> int:
    data = graph(args.project_dir)
    if args.json:
        _print_json(data)
        return 0
    for node in data["nodes"]:
        print(
            "{id} {status} wave={wave} kind={kind} risk={risk}".format(
                id=node.get("id"),
                status=node.get("status"),
                wave=node.get("wave"),
                kind=node.get("kind"),
                risk=node.get("risk"),
            )
        )
    for edge in data["edges"]:
        print(f"  {edge['from']} -> {edge['to']} ({edge['type']})")
    if data.get("cycles"):
        print("依赖环: " + ", ".join(data["cycles"]))
    return 0


def _cmd_task_plan(args: argparse.Namespace) -> int:
    data = plan_tasks(args.project_dir)
    if args.json:
        _print_json(data)
        return 0
    if not data["ready"]:
        print("没有就绪任务")
    for wave, items in data["waves"].items():
        print(f"[{wave}]")
        for item in items:
            print(f"  {item['id']} {item['title']} (risk={item['risk']})")
    if data["blocked"]:
        print("阻塞:")
        for item in data["blocked"]:
            print(f"  {item['id']} depends_on={item['depends_on']}")
    if data["conflicts"]:
        print("写冲突:")
        for conflict in data["conflicts"]:
            print(f"  {conflict['wave']}: {conflict['a']} <-> {conflict['b']}")
    return 0


def _cmd_task_next(args: argparse.Namespace) -> int:
    items = next_tasks(args.project_dir, limit=args.limit)
    if args.json:
        _print_json(items)
        return 0
    if not items:
        print("没有可执行任务")
        return 0
    for item in items:
        print(
            "{id} {wave} {kind} risk={risk} next={next_owner} {title}".format(
                id=item.get("id"),
                wave=item.get("wave"),
                kind=item.get("kind"),
                risk=item.get("risk"),
                next_owner=item.get("next_owner"),
                title=item.get("title"),
            )
        )
    return 0


def _cmd_task_release(args: argparse.Namespace) -> int:
    data = release_task(args.project_dir, args.task_id, reason=args.reason, force=args.force)
    print(f"{data['id']} -> {data['status']} (next={data['next_owner']})")
    return 0


def _cmd_task_summary(args: argparse.Namespace) -> int:
    data = task_summary(args.project_dir)
    if args.json:
        _print_json(data)
        return 0
    print(f"任务: {data['counts']}")
    print(f"活跃: {', '.join(data['active_tasks']) or '-'}")
    for lease in data.get("active_leases") or []:
        print(
            f"  lease: {lease.get('task')} owner={lease.get('owner')} "
            f"wave={lease.get('wave')} expires={lease.get('expires_at')}"
        )
    print(f"待验收: {', '.join(data['submitted_tasks']) or '-'}")
    print(f"就绪: {', '.join(data['ready_tasks']) or '-'}")
    print(f"blocker/critical BUG: {data['open_bugs']}")
    if data["next"]:
        print("下一批:")
        for item in data["next"]:
            print(f"  {item['id']} wave={item['wave']} {item['title']}")
    return 0


def _cmd_log(args: argparse.Namespace) -> int:
    contract = resolve_contract(args.project_dir)
    path = contract / "state" / "ledger.ndjson"
    if not path.is_file():
        print("没有 ledger")
        return 0
    lines = state.tail_lines(path, args.limit)
    if args.json:
        _print_json([json.loads(line) for line in lines if line.strip()])
        return 0
    print("\n".join(lines))
    return 0


def _cmd_req_add(args: argparse.Namespace) -> int:
    item = req.add_requirement(
        args.project_dir,
        args.title,
        priority=args.priority,
        acceptance=args.acceptance or [],
        roadmap=args.roadmap,
        source=args.source,
        description=args.description or "",
        non_goals=args.non_goal or [],
        dependencies=args.dependency or [],
    )
    print(f"需求: {item['id']} ({item['status']}, {item['priority']})")
    print(f"文档: requirements/{item['id']}.md")
    return 0


def _cmd_req_list(args: argparse.Namespace) -> int:
    roadmap = args.roadmap
    if roadmap is None and not args.all:
        roadmap = str(state.read_current(resolve_contract(args.project_dir)).get("roadmap") or "R1")
    items = req.list_requirements(
        args.project_dir,
        status=args.status,
        roadmap=roadmap,
        limit=args.limit,
    )
    if args.json:
        _print_json(items)
        return 0
    if not items:
        print("没有需求")
        return 0
    for item in items:
        print(
            "{id} {priority} {status} {roadmap} {title}".format(
                id=item.get("id"),
                priority=item.get("priority"),
                status=item.get("status"),
                roadmap=item.get("roadmap"),
                title=item.get("title"),
            )
        )
    if args.limit and len(items) >= args.limit:
        print(f"已显示前 {args.limit} 条；用 --limit/--all 查看更多")
    return 0


def _cmd_req_show(args: argparse.Namespace) -> int:
    data = req.show_requirement(args.project_dir, args.req_id)
    if args.json:
        _print_json(data)
    else:
        print(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    return 0


def _cmd_req_update(args: argparse.Namespace) -> int:
    item = req.update_requirement(
        args.project_dir,
        args.req_id,
        status=args.status,
        priority=args.priority,
        roadmap=args.roadmap,
        title=args.title,
    )
    print(f"{item['id']} -> {item['status']} ({item['priority']}, {item['roadmap']})")
    return 0


def _cmd_req_trace(args: argparse.Namespace) -> int:
    roadmap = args.roadmap
    if roadmap is None and not args.all and args.req_id is None:
        roadmap = str(state.read_current(resolve_contract(args.project_dir)).get("roadmap") or "R1")
    data = req.trace(args.project_dir, args.req_id, roadmap=roadmap)
    if args.json:
        _print_json(data)
        return 0
    if args.req_id:
        print(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    else:
        print("已写入: requirements/TRACE.md")
        for req_id, entry in data.items():
            print(
                "{req} specs={specs} tasks={tasks} vr={vr} bugs={bugs}".format(
                    req=req_id,
                    specs=len(entry.get("specs") or []),
                    tasks=len(entry.get("tasks") or []),
                    vr=len(entry.get("verification") or []),
                    bugs=len(entry.get("bugs") or []),
                )
            )
    return 0


def _cmd_req_validate(args: argparse.Namespace) -> int:
    errors = req.validate_all(args.project_dir)
    if args.json:
        _print_json({"ok": not errors, "errors": errors})
    elif errors:
        print("REQ validate: FAIL")
        for error in errors:
            print(f"  - {error}")
    else:
        print("REQ validate: OK")
    return 0 if not errors else 1


def _print_roadmap(data: dict[str, Any]) -> None:
    current = data.get("current") or {}
    print(f"当前: {current.get('roadmap')} / {current.get('phase')}")
    for item in data.get("roadmaps") or []:
        print(
            "{id} [{status}] {title} version={version} goal={goal}".format(
                id=item.get("id"),
                status=item.get("status"),
                title=item.get("title"),
                version=item.get("version_target"),
                goal=item.get("goal"),
            )
        )


def _cmd_roadmap_show(args: argparse.Namespace) -> int:
    data = roadmap.show(args.project_dir)
    if args.json:
        _print_json(data)
    else:
        _print_roadmap(data)
    return 0


def _cmd_roadmap_plan(args: argparse.Namespace) -> int:
    result = roadmap.plan(
        args.project_dir,
        args.roadmap_id,
        title=args.title,
        version_target=args.version_target,
        goal=args.goal,
        entry_criteria=args.entry or [],
        exit_criteria=args.exit or [],
        non_goals=args.non_goal or [],
        activate=args.activate,
    )
    print(f"路标: {result['roadmap']} ({result['version_target']})")
    print(f"计划: {result['plan']}")
    if result["activated"]:
        print("已激活为当前路标")
    return 0


def _cmd_roadmap_close(args: argparse.Namespace) -> int:
    result = roadmap.close(args.project_dir, args.roadmap_id, note=args.note, force=args.force)
    print(f"已关闭: {result['roadmap']}")
    print(f"归档: {result['archive']}")
    if result.get("next"):
        print(f"下一路标: {result['next']}")
    print(f"未完成任务: {result['unfinished_tasks']}；未关闭 blocker/critical BUG: {result['open_blocking_bugs']}")
    return 0


def _cmd_phase_enter(args: argparse.Namespace) -> int:
    result = roadmap.phase_enter(args.project_dir, args.phase)
    print(f"{result['roadmap']}-{result['phase']} -> active")
    print(f"计划: {result['plan']}")
    return 0


def _cmd_phase_review(args: argparse.Namespace) -> int:
    result = roadmap.phase_review(args.project_dir)
    print(f"{result['roadmap']}-{result['phase']} 报告: {result['report']}")
    print(result["text"], end="")
    return 0


def _cmd_phase_exit(args: argparse.Namespace) -> int:
    result = roadmap.phase_exit(
        args.project_dir,
        approved_by=args.approved_by,
        note=args.note,
        force=args.force,
    )
    print(f"{result['roadmap']}-{result['phase']} -> {result.get('next') or 'done'}")
    print(f"报告: {result['report']}")
    if result.get("handoff"):
        print(f"交接: {result['handoff']}")
    return 0


def _cmd_bug_add(args: argparse.Namespace) -> int:
    item = bug.add_bug(
        args.project_dir,
        args.title,
        severity=args.severity,
        phase=args.phase,
        task=args.task,
        verification=args.verification,
        delivery=args.delivery,
        related_reqs=args.requirement or [],
        environment=args.environment or "",
        steps=args.steps or "",
        expected=args.expected or "",
        actual=args.actual or "",
        evidence=args.evidence or [],
    )
    print(f"缺陷: {item['id']} ({item['severity']}, {item['status']})")
    return 0


def _cmd_bug_list(args: argparse.Namespace) -> int:
    roadmap = args.roadmap
    if roadmap is None and not args.all:
        roadmap = str(state.read_current(resolve_contract(args.project_dir)).get("roadmap") or "R1")
    items = bug.list_bugs(args.project_dir, status=args.status, severity=args.severity, roadmap=roadmap)
    if args.json:
        _print_json(items)
        return 0
    if not items:
        print("没有缺陷")
        return 0
    for item in items:
        print(
            "{id} {severity} {status} {title}".format(
                id=item.get("id"),
                severity=item.get("severity"),
                status=item.get("status"),
                title=item.get("title"),
            )
        )
    return 0


def _cmd_bug_show(args: argparse.Namespace) -> int:
    data = bug.show_bug(args.project_dir, args.bug_id)
    if args.json:
        _print_json(data)
    else:
        print(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    return 0


def _cmd_bug_update(args: argparse.Namespace) -> int:
    data = bug.update_bug(
        args.project_dir,
        args.bug_id,
        status=args.status,
        severity=args.severity,
        fix_task=args.fix_task,
        root_cause=args.root_cause,
        resolution=args.resolution,
    )
    print(f"{data['id']} -> {data['status']} ({data['severity']})")
    return 0


def _cmd_bug_close(args: argparse.Namespace) -> int:
    data = bug.close_bug(
        args.project_dir,
        args.bug_id,
        verification=args.verification,
        resolution=args.resolution,
    )
    print(f"{data['id']} -> {data['status']}")
    return 0


def _cmd_knowledge_add(args: argparse.Namespace) -> int:
    item = knowledge.add_knowledge(
        args.project_dir,
        args.kind,
        args.text,
        context=args.context or "",
        source=args.source,
        delivery=args.delivery,
    )
    print(f"知识: {item['id']} ({args.kind})")
    print("已刷新: knowledge/KNOWLEDGE.md")
    return 0


def _cmd_knowledge_list(args: argparse.Namespace) -> int:
    items = knowledge.list_knowledge(args.project_dir, kind=args.kind)
    if args.json:
        _print_json(items)
        return 0
    if not items:
        print("没有知识条目")
        return 0
    for item in items:
        print(f"{item['id']} [{item['kind']}] {item['text']}")
    return 0


def _cmd_knowledge_show(args: argparse.Namespace) -> int:
    data = knowledge.show_knowledge(args.project_dir, args.item_id)
    if args.json:
        _print_json(data)
    else:
        print(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    return 0


def _cmd_knowledge_render(args: argparse.Namespace) -> int:
    path = knowledge.render(resolve_contract(args.project_dir))
    print(f"已渲染: {path}")
    return 0


def _cmd_verify_record(args: argparse.Namespace) -> int:
    item = verify.record_verification(
        args.project_dir,
        layer=args.layer,
        scope=args.scope,
        result=args.result,
        requirement_refs=args.requirement or [],
        design_refs=args.design or [],
        task_refs=args.task or [],
        method=args.method,
        evidence=args.evidence or [],
        bugs=args.bug or [],
        verifier=args.verifier,
        notes=args.notes or "",
    )
    print(f"验证记录: {item['id']} ({item['layer']}, {item['result']})")
    return 0


def _cmd_verify_list(args: argparse.Namespace) -> int:
    roadmap = args.roadmap
    if roadmap is None and not args.all:
        roadmap = str(state.read_current(resolve_contract(args.project_dir)).get("roadmap") or "R1")
    items = verify.list_verifications(
        args.project_dir,
        layer=args.layer,
        result=args.result,
        roadmap=roadmap,
    )
    if args.json:
        _print_json(items)
        return 0
    if not items:
        print("没有验证记录")
        return 0
    for item in items:
        print(
            "{id} {layer} {result} {scope}".format(
                id=item.get("id"),
                layer=item.get("layer"),
                result=item.get("result"),
                scope=item.get("scope"),
            )
        )
    return 0


def _cmd_verify_show(args: argparse.Namespace) -> int:
    data = verify.show_verification(args.project_dir, args.vr_id)
    if args.json:
        _print_json(data)
    else:
        print(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    return 0


def _cmd_release_freeze(args: argparse.Namespace) -> int:
    result = verify.release_freeze(
        args.project_dir,
        version=args.version,
        note=args.note,
        force=args.force,
    )
    print(f"已冻结: {result['version']} ({result['roadmap']})")
    print(f"清单: {result['manifest']}")
    print(f"published: {result['published']}；冻结不等于发布")
    print(f"已知问题: {result['known_issues']}")
    return 0


def _cmd_release_show(args: argparse.Namespace) -> int:
    data = verify.show_release(args.project_dir, args.version)
    if args.json:
        _print_json(data)
    else:
        print(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    return 0


def _cmd_context_show(args: argparse.Namespace) -> int:
    data = context.hot_files(args.project_dir)
    if args.json:
        _print_json(data)
        return 0
    print(f"当前: {data['roadmap']} / {data['phase']} ({data.get('phase_status')})")
    print("热文件:")
    for item in data["files"]:
        size = f"{item['bytes']}B" if item.get("exists") else "missing"
        print(f"  {'OK' if item['exists'] else 'MISS'} {item['path']} ({size})")
    print(
        f"热区总量: {data['total_bytes']}B / {data['budget'].get('bytes')}B "
        f"({'OK' if data['within_budget'] else 'OVER'})"
    )
    return 0


def _cmd_context_expand(args: argparse.Namespace) -> int:
    data = context.expand(
        args.project_dir,
        args.path,
        reason=args.reason,
        actor=args.actor,
    )
    print(f"# {data['path']} ({data['bytes']} bytes, reason={data['reason']})")
    print(data["text"], end="" if data["text"].endswith("\n") else "\n")
    return 0


def _cmd_context_log(args: argparse.Namespace) -> int:
    items = context.read_log(args.project_dir, limit=args.limit)
    if args.json:
        _print_json(items)
        return 0
    for item in items:
        print(
            "{ts} {actor} {event} {path} reason={reason}".format(
                ts=item.get("ts"),
                actor=item.get("actor"),
                event=item.get("event"),
                path=item.get("path"),
                reason=item.get("reason"),
            )
        )
    return 0


def _cmd_context_policy(args: argparse.Namespace) -> int:
    data = context.policy(args.project_dir)
    if args.json:
        _print_json(data)
    else:
        print(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    return 0


def _cmd_archive_list(args: argparse.Namespace) -> int:
    items = context.archive_list(args.project_dir)
    if args.json:
        _print_json(items)
        return 0
    if not items:
        print("没有归档")
        return 0
    for item in items:
        print(f"{item['roadmap']} files={item['files']} index={item['index']}")
    return 0


def _cmd_archive_show(args: argparse.Namespace) -> int:
    data = context.archive_show(
        args.project_dir,
        args.roadmap_id,
        reason=args.reason,
        actor=args.actor,
    )
    if args.json:
        _print_json(data)
        return 0
    print(f"归档: {data['path']} (reason={data['reason']})")
    if data.get("index"):
        print(data["index"], end="")
    if data.get("files"):
        print("\n文件:")
        for name in data["files"]:
            print(f"  {name}")
    return 0



def _cmd_hook_pretool(args: argparse.Namespace) -> int:
    return guard.run_hook()


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

    task_p = sub.add_parser("task", help="任务卡与评审任务")
    task_sub = task_p.add_subparsers(dest="action", required=True)

    task_create = task_sub.add_parser("create")
    task_create.add_argument("--project-dir", default=".")
    task_create.add_argument("--title")
    task_create.add_argument("--from", dest="from_file")
    task_create.add_argument(
        "--kind", choices=["implement", "design", "verify", "document", "review", "fix"], default="implement"
    )
    task_create.add_argument("--delivery")
    task_create.add_argument("--risk", choices=["low", "medium", "high", "critical"], default="medium")
    task_create.add_argument("--effort", default="M")
    task_create.add_argument("--review-mode", choices=["manager", "independent", "user"])
    task_create.add_argument("--reviews", help="review 任务对应的实现/设计任务 ID")
    task_create.add_argument("--review-scope", action="append")
    task_create.add_argument("--allowed-path", action="append")
    task_create.add_argument("--acceptance", action="append")
    task_create.add_argument("--wave", default="W1")
    task_create.add_argument("--depends-on", action="append")
    task_create.add_argument("--fixes", action="append", help="关联 BUG id")
    task_create.add_argument("--no-review", action="store_true", help="不自动创建 review 任务")
    task_create.set_defaults(func=_cmd_task_create)

    task_list = task_sub.add_parser("list")
    task_list.add_argument("--project-dir", default=".")
    task_list.add_argument("--status")
    task_list.add_argument("--json", action="store_true")
    task_list.set_defaults(func=_cmd_task_list)

    task_show = task_sub.add_parser("show")
    task_show.add_argument("task_id")
    task_show.add_argument("--project-dir", default=".")
    task_packet = task_show.add_mutually_exclusive_group()
    task_packet.add_argument("--packet", action="store_true")
    task_packet.add_argument("--review-packet", action="store_true")
    task_show.add_argument("--json", action="store_true")
    task_show.set_defaults(func=_cmd_task_show)

    task_start = task_sub.add_parser("start")
    task_start.add_argument("task_id")
    task_start.add_argument("--project-dir", default=".")
    task_start.add_argument("--owner", help="worker 身份；也可设置 MF_WORKER_ID")
    task_start.set_defaults(func=_cmd_task_start)

    task_submit = task_sub.add_parser("submit")
    task_submit.add_argument("task_id")
    task_submit.add_argument("--project-dir", default=".")
    task_submit.add_argument("--handoff")
    task_submit.add_argument("--dev-record")
    task_submit.add_argument("--owner", help="worker 身份；也可设置 MF_WORKER_ID")
    task_submit.set_defaults(func=_cmd_task_submit)

    task_accept = task_sub.add_parser("accept")
    task_accept.add_argument("task_id")
    task_accept.add_argument("--project-dir", default=".")
    task_accept.add_argument(
        "--verdict",
        choices=["PASS", "PASS_WITH_RISK", "NEEDS_REWORK", "BLOCKED"],
        default="PASS",
    )
    task_accept.add_argument("--note")
    task_accept.add_argument("--user-approved-by", help="critical 任务的用户验收记录")
    task_accept.set_defaults(func=_cmd_task_accept)

    task_reject = task_sub.add_parser("reject")
    task_reject.add_argument("task_id")
    task_reject.add_argument("--project-dir", default=".")
    task_reject.add_argument("--reason", required=True)
    task_reject.set_defaults(func=_cmd_task_reject)

    task_prompt = task_sub.add_parser("prompt")
    task_prompt.add_argument("task_id")
    task_prompt.add_argument("--project-dir", default=".")
    task_prompt.set_defaults(func=_cmd_task_prompt)

    task_graph = task_sub.add_parser("graph", help="显示任务依赖/评审关系")
    task_graph.add_argument("--project-dir", default=".")
    task_graph.add_argument("--json", action="store_true")
    task_graph.set_defaults(func=_cmd_task_graph)

    task_plan = task_sub.add_parser("plan", help="按 wave 规划就绪任务并检查写冲突")
    task_plan.add_argument("--project-dir", default=".")
    task_plan.add_argument("--json", action="store_true")
    task_plan.set_defaults(func=_cmd_task_plan)

    task_next = task_sub.add_parser("next", help="列出可执行任务")
    task_next.add_argument("--project-dir", default=".")
    task_next.add_argument("--limit", type=int, default=10)
    task_next.add_argument("--json", action="store_true")
    task_next.set_defaults(func=_cmd_task_next)

    task_release = task_sub.add_parser("release", help="释放任务 lease 并回到 ready")
    task_release.add_argument("task_id")
    task_release.add_argument("--project-dir", default=".")
    task_release.add_argument("--reason", default="lease 释放")
    task_release.add_argument("--force", action="store_true")
    task_release.set_defaults(func=_cmd_task_release)

    task_summary_p = task_sub.add_parser("summary", help="任务/缺陷/下一批汇总")
    task_summary_p.add_argument("--project-dir", default=".")
    task_summary_p.add_argument("--json", action="store_true")
    task_summary_p.set_defaults(func=_cmd_task_summary)

    req_p = sub.add_parser("req", help="需求基线、DoR 与追踪")
    req_sub = req_p.add_subparsers(dest="action", required=True)
    req_add = req_sub.add_parser("add")
    req_add.add_argument("--project-dir", default=".")
    req_add.add_argument("--title", required=True)
    req_add.add_argument("--priority", choices=list(req.PRIORITIES), default="must")
    req_add.add_argument("--acceptance", action="append")
    req_add.add_argument("--roadmap")
    req_add.add_argument("--source", default="user")
    req_add.add_argument("--description")
    req_add.add_argument("--non-goal", action="append")
    req_add.add_argument("--dependency", action="append")
    req_add.set_defaults(func=_cmd_req_add)
    req_list = req_sub.add_parser("list")
    req_list.add_argument("--project-dir", default=".")
    req_list.add_argument("--status")
    req_list.add_argument("--roadmap")
    req_list.add_argument("--limit", type=int, default=50)
    req_list.add_argument("--all", action="store_true", help="不按当前路标过滤")
    req_list.add_argument("--json", action="store_true")
    req_list.set_defaults(func=_cmd_req_list)
    req_show = req_sub.add_parser("show")
    req_show.add_argument("req_id")
    req_show.add_argument("--project-dir", default=".")
    req_show.add_argument("--json", action="store_true")
    req_show.set_defaults(func=_cmd_req_show)
    req_update = req_sub.add_parser("update")
    req_update.add_argument("req_id")
    req_update.add_argument("--project-dir", default=".")
    req_update.add_argument("--status", choices=list(req.REQ_STATUSES))
    req_update.add_argument("--priority", choices=list(req.PRIORITIES))
    req_update.add_argument("--roadmap")
    req_update.add_argument("--title")
    req_update.set_defaults(func=_cmd_req_update)
    req_trace = req_sub.add_parser("trace")
    req_trace.add_argument("req_id", nargs="?")
    req_trace.add_argument("--project-dir", default=".")
    req_trace.add_argument("--roadmap")
    req_trace.add_argument("--all", action="store_true", help="追踪所有路标；默认当前路标")
    req_trace.add_argument("--json", action="store_true")
    req_trace.set_defaults(func=_cmd_req_trace)
    req_validate = req_sub.add_parser("validate")
    req_validate.add_argument("--project-dir", default=".")
    req_validate.add_argument("--json", action="store_true")
    req_validate.set_defaults(func=_cmd_req_validate)

    roadmap_p = sub.add_parser("roadmap", help="路标与版本计划")
    roadmap_sub = roadmap_p.add_subparsers(dest="action", required=True)
    roadmap_show = roadmap_sub.add_parser("show")
    roadmap_show.add_argument("--project-dir", default=".")
    roadmap_show.add_argument("--json", action="store_true")
    roadmap_show.set_defaults(func=_cmd_roadmap_show)
    roadmap_plan = roadmap_sub.add_parser("plan")
    roadmap_plan.add_argument("roadmap_id")
    roadmap_plan.add_argument("--project-dir", default=".")
    roadmap_plan.add_argument("--title", required=True)
    roadmap_plan.add_argument("--version-target", required=True)
    roadmap_plan.add_argument("--goal", required=True)
    roadmap_plan.add_argument("--entry", action="append")
    roadmap_plan.add_argument("--exit", action="append")
    roadmap_plan.add_argument("--non-goal", action="append")
    roadmap_plan.add_argument("--activate", action="store_true")
    roadmap_plan.set_defaults(func=_cmd_roadmap_plan)
    roadmap_close = roadmap_sub.add_parser("close")
    roadmap_close.add_argument("roadmap_id")
    roadmap_close.add_argument("--project-dir", default=".")
    roadmap_close.add_argument("--note")
    roadmap_close.add_argument("--force", action="store_true")
    roadmap_close.set_defaults(func=_cmd_roadmap_close)

    phase_p = sub.add_parser("phase", help="五阶段进入/评审/退出")
    phase_sub = phase_p.add_subparsers(dest="action", required=True)
    phase_enter = phase_sub.add_parser("enter")
    phase_enter.add_argument("phase", choices=list(roadmap.PHASES))
    phase_enter.add_argument("--project-dir", default=".")
    phase_enter.set_defaults(func=_cmd_phase_enter)
    phase_review = phase_sub.add_parser("review")
    phase_review.add_argument("--project-dir", default=".")
    phase_review.set_defaults(func=_cmd_phase_review)
    phase_exit = phase_sub.add_parser("exit")
    phase_exit.add_argument("--project-dir", default=".")
    phase_exit.add_argument("--approved-by")
    phase_exit.add_argument("--note")
    phase_exit.add_argument("--force", action="store_true")
    phase_exit.set_defaults(func=_cmd_phase_exit)

    bug_p = sub.add_parser("bug", help="缺陷生命周期")
    bug_sub = bug_p.add_subparsers(dest="action", required=True)
    bug_add = bug_sub.add_parser("add")
    bug_add.add_argument("--project-dir", default=".")
    bug_add.add_argument("--title", required=True)
    bug_add.add_argument("--severity", choices=list(bug.SEVERITIES), default="major")
    bug_add.add_argument("--phase")
    bug_add.add_argument("--task")
    bug_add.add_argument("--verification")
    bug_add.add_argument("--delivery")
    bug_add.add_argument("--requirement", action="append")
    bug_add.add_argument("--environment")
    bug_add.add_argument("--steps")
    bug_add.add_argument("--expected")
    bug_add.add_argument("--actual")
    bug_add.add_argument("--evidence", action="append")
    bug_add.set_defaults(func=_cmd_bug_add)
    bug_list = bug_sub.add_parser("list")
    bug_list.add_argument("--project-dir", default=".")
    bug_list.add_argument("--status")
    bug_list.add_argument("--severity")
    bug_list.add_argument("--roadmap")
    bug_list.add_argument("--all", action="store_true", help="不按当前路标过滤")
    bug_list.add_argument("--json", action="store_true")
    bug_list.set_defaults(func=_cmd_bug_list)
    bug_show = bug_sub.add_parser("show")
    bug_show.add_argument("bug_id")
    bug_show.add_argument("--project-dir", default=".")
    bug_show.add_argument("--json", action="store_true")
    bug_show.set_defaults(func=_cmd_bug_show)
    bug_update = bug_sub.add_parser("update")
    bug_update.add_argument("bug_id")
    bug_update.add_argument("--project-dir", default=".")
    bug_update.add_argument("--status", choices=list(bug.STATUSES))
    bug_update.add_argument("--severity", choices=list(bug.SEVERITIES))
    bug_update.add_argument("--fix-task")
    bug_update.add_argument("--root-cause")
    bug_update.add_argument("--resolution")
    bug_update.set_defaults(func=_cmd_bug_update)
    bug_close = bug_sub.add_parser("close")
    bug_close.add_argument("bug_id")
    bug_close.add_argument("--project-dir", default=".")
    bug_close.add_argument("--verification", required=True)
    bug_close.add_argument("--resolution")
    bug_close.set_defaults(func=_cmd_bug_close)

    knowledge_p = sub.add_parser("knowledge", help="项目知识/纠正记录")
    knowledge_sub = knowledge_p.add_subparsers(dest="action", required=True)
    knowledge_add = knowledge_sub.add_parser("add")
    knowledge_add.add_argument("--project-dir", default=".")
    knowledge_add.add_argument("--kind", choices=list(knowledge.KINDS), required=True)
    knowledge_add.add_argument("--text", required=True)
    knowledge_add.add_argument("--context")
    knowledge_add.add_argument("--source", default="user")
    knowledge_add.add_argument("--delivery", help="只注入指定交付库的任务包")
    knowledge_add.set_defaults(func=_cmd_knowledge_add)
    knowledge_list = knowledge_sub.add_parser("list")
    knowledge_list.add_argument("--project-dir", default=".")
    knowledge_list.add_argument("--kind", choices=list(knowledge.KINDS))
    knowledge_list.add_argument("--json", action="store_true")
    knowledge_list.set_defaults(func=_cmd_knowledge_list)
    knowledge_show = knowledge_sub.add_parser("show")
    knowledge_show.add_argument("item_id")
    knowledge_show.add_argument("--project-dir", default=".")
    knowledge_show.add_argument("--json", action="store_true")
    knowledge_show.set_defaults(func=_cmd_knowledge_show)
    knowledge_render = knowledge_sub.add_parser("render")
    knowledge_render.add_argument("--project-dir", default=".")
    knowledge_render.set_defaults(func=_cmd_knowledge_render)

    verify_p = sub.add_parser("verify", help="L1/L2/L3 验证记录")
    verify_sub = verify_p.add_subparsers(dest="action", required=True)
    verify_record = verify_sub.add_parser("record")
    verify_record.add_argument("--project-dir", default=".")
    verify_record.add_argument("--layer", choices=list(verify.LAYERS), required=True)
    verify_record.add_argument("--scope", required=True)
    verify_record.add_argument("--result", choices=list(verify.RESULTS), required=True)
    verify_record.add_argument("--requirement", action="append")
    verify_record.add_argument("--design", action="append")
    verify_record.add_argument("--task", action="append")
    verify_record.add_argument("--method", default="artifact")
    verify_record.add_argument("--evidence", action="append")
    verify_record.add_argument("--bug", action="append")
    verify_record.add_argument("--verifier", default="meta-manager")
    verify_record.add_argument("--notes")
    verify_record.set_defaults(func=_cmd_verify_record)
    verify_list = verify_sub.add_parser("list")
    verify_list.add_argument("--project-dir", default=".")
    verify_list.add_argument("--layer", choices=list(verify.LAYERS))
    verify_list.add_argument("--result", choices=list(verify.RESULTS))
    verify_list.add_argument("--roadmap")
    verify_list.add_argument("--all", action="store_true", help="不按当前路标过滤")
    verify_list.add_argument("--json", action="store_true")
    verify_list.set_defaults(func=_cmd_verify_list)
    verify_show = verify_sub.add_parser("show")
    verify_show.add_argument("vr_id")
    verify_show.add_argument("--project-dir", default=".")
    verify_show.add_argument("--json", action="store_true")
    verify_show.set_defaults(func=_cmd_verify_show)

    release_p = sub.add_parser("release", help="版本冻结（不等于发布）")
    release_sub = release_p.add_subparsers(dest="action", required=True)
    release_freeze = release_sub.add_parser("freeze")
    release_freeze.add_argument("--project-dir", default=".")
    release_freeze.add_argument("--version")
    release_freeze.add_argument("--note")
    release_freeze.add_argument("--force", action="store_true")
    release_freeze.set_defaults(func=_cmd_release_freeze)
    release_show = release_sub.add_parser("show")
    release_show.add_argument("--project-dir", default=".")
    release_show.add_argument("--version")
    release_show.add_argument("--json", action="store_true")
    release_show.set_defaults(func=_cmd_release_show)

    context_p = sub.add_parser("context", help="热区上下文与读扩展")
    context_sub = context_p.add_subparsers(dest="action", required=True)
    context_show = context_sub.add_parser("show")
    context_show.add_argument("--project-dir", default=".")
    context_show.add_argument("--json", action="store_true")
    context_show.set_defaults(func=_cmd_context_show)
    context_expand = context_sub.add_parser("expand")
    context_expand.add_argument("path")
    context_expand.add_argument("--project-dir", default=".")
    context_expand.add_argument("--reason", choices=list(context.REASONS), required=True)
    context_expand.add_argument("--actor", help="默认从当前目录/MF_ROLE 推导")
    context_expand.set_defaults(func=_cmd_context_expand)
    context_log = context_sub.add_parser("log")
    context_log.add_argument("--project-dir", default=".")
    context_log.add_argument("--limit", type=int, default=50)
    context_log.add_argument("--json", action="store_true")
    context_log.set_defaults(func=_cmd_context_log)
    context_policy = context_sub.add_parser("policy")
    context_policy.add_argument("--project-dir", default=".")
    context_policy.add_argument("--json", action="store_true")
    context_policy.set_defaults(func=_cmd_context_policy)

    archive_p = sub.add_parser("archive", help="归档查询（必须 reason）")
    archive_sub = archive_p.add_subparsers(dest="action", required=True)
    archive_list = archive_sub.add_parser("list")
    archive_list.add_argument("--project-dir", default=".")
    archive_list.add_argument("--json", action="store_true")
    archive_list.set_defaults(func=_cmd_archive_list)
    archive_show = archive_sub.add_parser("show")
    archive_show.add_argument("roadmap_id")
    archive_show.add_argument("--project-dir", default=".")
    archive_show.add_argument("--reason", choices=list(context.REASONS), required=True)
    archive_show.add_argument("--actor", help="默认从当前目录/MF_ROLE 推导")
    archive_show.add_argument("--json", action="store_true")
    archive_show.set_defaults(func=_cmd_archive_show)

    log_p = sub.add_parser("log", help="查看 ledger 审计日志")
    log_p.add_argument("--project-dir", default=".")
    log_p.add_argument("--limit", type=int, default=50)
    log_p.add_argument("--json", action="store_true")
    log_p.set_defaults(func=_cmd_log)

    improve_p = sub.add_parser("improve", help="MFP 改进包")
    improve_sub = improve_p.add_subparsers(dest="action", required=True)

    improve_new = improve_sub.add_parser("new")
    improve_new.add_argument("--title", required=True)
    improve_new.add_argument("--local", action="store_true", help="worker 本地草稿")
    improve_new.add_argument("--project-dir", default=".")
    improve_new.set_defaults(func=_cmd_improve_new)

    improve_list = improve_sub.add_parser("list")
    improve_scope = improve_list.add_mutually_exclusive_group()
    improve_scope.add_argument("--local", action="store_true")
    improve_scope.add_argument("--inbox", action="store_true")
    improve_list.add_argument("--status")
    improve_list.add_argument("--project-dir", default=".")
    improve_list.add_argument("--json", action="store_true")
    improve_list.set_defaults(func=_cmd_improve_list)

    improve_show = improve_sub.add_parser("show")
    improve_show.add_argument("mfp_id")
    improve_show_scope = improve_show.add_mutually_exclusive_group()
    improve_show_scope.add_argument("--local", action="store_true")
    improve_show_scope.add_argument("--inbox", action="store_true")
    improve_show.add_argument("--project-dir", default=".")
    improve_show.add_argument("--json", action="store_true")
    improve_show.set_defaults(func=_cmd_improve_show)

    improve_validate = improve_sub.add_parser("validate")
    improve_validate.add_argument("mfp_id")
    improve_validate.add_argument("--local", action="store_true")
    improve_validate.add_argument("--project-dir", default=".")
    improve_validate.add_argument("--json", action="store_true")
    improve_validate.set_defaults(func=_cmd_improve_validate)

    improve_submit = improve_sub.add_parser("submit")
    improve_submit.add_argument("mfp_id")
    improve_submit.add_argument("--project-dir", default=".")
    improve_submit.set_defaults(func=_cmd_improve_submit)

    improve_import = improve_sub.add_parser("import")
    improve_import.add_argument("--from", dest="source", required=True)
    improve_import.add_argument("--project-dir", default=".")
    improve_import.set_defaults(func=_cmd_improve_import)

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

    dev_improve_p = dev_sub.add_parser("improve", help="把 MFP 导入 meta-flow 源码")
    dev_improve_sub = dev_improve_p.add_subparsers(dest="improve_action", required=True)

    di_import = dev_improve_sub.add_parser("import")
    di_import.add_argument("ref", help="<project>/<MFP> 或唯一的 MFP id")
    di_import.add_argument("--kind", choices=["bug", "requirement", "change", "undecided"])
    di_import.add_argument("--already-implemented", action="store_true")
    di_import.add_argument("--version")
    di_import.add_argument("--commit")
    di_import.add_argument("--note")
    di_import.add_argument("--source")
    di_import.set_defaults(func=_cmd_dev_improve_import)

    di_list = dev_improve_sub.add_parser("list")
    di_list.add_argument("--source")
    di_list.add_argument("--scope", choices=["open", "closed", "records"], default="open")
    di_list.add_argument("--json", action="store_true")
    di_list.set_defaults(func=_cmd_dev_improve_list)

    di_update = dev_improve_sub.add_parser("update")
    di_update.add_argument("mfp_id")
    di_update.add_argument("--status", required=True)
    di_update.add_argument("--version")
    di_update.add_argument("--commit")
    di_update.add_argument("--note")
    di_update.add_argument("--source")
    di_update.set_defaults(func=_cmd_dev_improve_update)

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

    hook_p = sub.add_parser("hook", help="Claude Code hook 入口")
    hook_sub = hook_p.add_subparsers(dest="action", required=True)
    hook_pretool = hook_sub.add_parser("pretool", help="PreToolUse 角色/路径守卫")
    hook_pretool.set_defaults(func=_cmd_hook_pretool)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        _enforce_role(args)
        role, _ = _effective_role(args)
        old_role = os.environ.get("MF_ROLE")
        old_actor = os.environ.get("MF_ACTOR")
        if role in ROLE_VALUES:
            os.environ["MF_ROLE"] = role
            os.environ.setdefault("MF_ACTOR", role)
        try:
            return int(args.func(args))
        finally:
            if old_role is None:
                os.environ.pop("MF_ROLE", None)
            else:
                os.environ["MF_ROLE"] = old_role
            if old_actor is None:
                os.environ.pop("MF_ACTOR", None)
            else:
                os.environ["MF_ACTOR"] = old_actor
    except (
        WorkspaceError,
        InstallError,
        GlobalStoreError,
        ImproveError,
        TaskError,
        req.ReqError,
        roadmap.RoadmapError,
        bug.BugError,
        knowledge.KnowledgeError,
        verify.VerifyError,
        context.ContextError,
        state.StateError,
    ) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return getattr(exc, "code", 1)


if __name__ == "__main__":
    raise SystemExit(main())
