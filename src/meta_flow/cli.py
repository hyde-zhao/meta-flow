"""mf 命令行入口。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from . import (
    __version__,
    bug,
    context,
    design,
    docmodel,
    guard,
    improve,
    knowledge,
    req,
    roadmap,
    roles,
    skills,
    state,
    verify,
    work,
)
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
    install_designer,
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
    dispatch_review,
    graph,
    list_tasks,
    load_task,
    next_tasks,
    packet_text,
    plan_tasks,
    prompt_text,
    reject_task,
    release_task,
    rework_task,
    start_task,
    submit_task,
    summary_text,
    validate_task,
    withdraw_task,
)
from .task import (
    summary as task_summary,
)
from .workspace import (
    INSTALL_REL,
    WorkspaceError,
    bootstrap_install_role,
    detect_role,
    doctor,
    doctor_global,
    doctor_warnings,
    find_workspace_root,
    resolve_contract,
    workspace_add_project,
    workspace_attach,
    workspace_init,
    workspace_link,
    workspace_status,
    workspace_sync,
)


def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


# T038: WP-F2F3 新命令（work/design/skill/docs）在下方按模块接入


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
ROLE_VALUES = {"manager", "designer", "worker", "maintainer"}


def _effective_role(args: argparse.Namespace) -> tuple[str, Path | None]:
    # 会话锚点优先：SessionStart/用户终端切换写入，抵御 cwd 漂移（T033 A1）
    anchor = roles.read_anchor(Path.cwd())
    if anchor is not None:
        return anchor["role"], anchor["root"]
    # 显式 MF_ROLE 优先于目录推导：maintainer 可在 workspace 根维护工具源码，
    # 不被目录识别出的 manager 角色压制；角色与目录一致时保留目录 root，
    # 保证 main() 注入 MF_ROLE 后 worker 的交付库作用域校验仍然生效。
    # designer/manager 不能由环境变量提权：必须与目录或锚点一致（fail-closed）。
    detected_role, detected_root = detect_role(Path.cwd())
    env_role = roles.normalize_role(os.environ.get("MF_ROLE"))
    if env_role in ROLE_VALUES:
        if detected_role == env_role:
            return env_role, detected_root
        if env_role in {"designer", "manager"}:
            env_role = None
    if env_role in {"worker", "maintainer"}:
        # 无交付根绑定时允许 --project-dir/--path 显式绑定（MFP-0012）
        for attr in ("project_dir", "path"):
            raw = getattr(args, attr, None)
            if raw:
                candidate_role, candidate_root = detect_role(Path(raw))
                if candidate_role == env_role:
                    return env_role, candidate_root
        return env_role, None
    if detected_role != "unbound":
        return detected_role, detected_root
    for attr in ("project_dir", "path"):
        raw = getattr(args, attr, None)
        if raw:
            candidate_role, candidate_root = detect_role(Path(raw))
            if candidate_role != "unbound":
                return candidate_role, candidate_root
    return "unbound", None


def _worker_task_scope(args: argparse.Namespace) -> tuple[str, Path | None, str | None]:
    """解析任务命令的 worker 交付作用域（MFP-0012）。

    worker 无交付根绑定时要求 --project-dir 指向交付库；否则拒绝跨交付操作。
    """
    role, root = _effective_role(args)
    if role not in {"worker", "designer"}:
        return role, root, None
    # R2：worker/designer 的任务命令只能操作本 workspace 的 contract，
    # 防止 --project-dir 指向另一个合法 workspace 读取/操作同 delivery 任务卡。
    if root is not None:
        target = getattr(args, "project_dir", ".")
        try:
            own_contract = resolve_contract(root)
            target_contract = resolve_contract(Path(str(target or ".")))
        except WorkspaceError as exc:
            raise WorkspaceError(f"任务命令契约解析失败: {exc}", 3) from exc
        if target_contract != own_contract:
            raise WorkspaceError(
                f"{role} 的任务命令 --project-dir 必须指向本工作区 contract: "
                f"{own_contract}（不接受 {target_contract}）",
                3,
            )
    if role == "designer":
        return role, root, None
    if root is None:
        raise WorkspaceError(
            "worker 无交付根绑定；请用 --project-dir 指定交付库，或从交付库运行", 3
        )
    delivery = _worker_delivery(root)
    if not delivery:
        raise WorkspaceError(
            f"交付库缺少 delivery.yaml，无法确定任务作用域: {root}", 3
        )
    return role, root, delivery


def _enforce_role(args: argparse.Namespace) -> None:
    command = str(getattr(args, "command", ""))
    action = str(getattr(args, "action", "") or "")
    role, _ = _effective_role(args)
    if command == "hook":
        return
    if role == "maintainer":
        # DP-ROLE-01 / D0-M1=A：maintainer 在 meta-flow 内是 root，不受任务/
        # lease/allowed_paths/角色门限制；外部动作由 guard 授权门单独约束。
        return
    if command in {"role", "status", "doctor", "bootstrap", "maintainer"}:
        return
    if command in {"install", "uninstall", "upgrade"}:
        actor_role, _ = _effective_role(args)
        if actor_role not in {"manager", "maintainer", "unbound"}:
            raise WorkspaceError("worker 不能安装/卸载/升级项目", 3)
        return
    if command == "dev":
        if role not in {"maintainer", "unbound"}:
            raise WorkspaceError("dev 命令只允许 maintainer", 3)
        return
    if command == "workspace":
        if role == "manager":
            return
        if action in {"init", "attach"} and role == "unbound":
            # 首次初始化/接入时 workspace.yaml 尚不存在：已安装 manager/maintainer 的项目可直接 bootstrap
            project_dir = getattr(args, "project_dir", ".")
            if bootstrap_install_role(Path(str(project_dir or "."))) in {"manager", "maintainer"}:
                return
        raise WorkspaceError("workspace 命令只允许 manager", 3)
    if command == "task":
        worker_actions = {"list", "show", "prompt", "validate"}
        manager_actions = {"create", "accept", "reject", "release", "graph", "plan", "next", "summary"}
        if action in {"start", "submit", "rework"}:
            if role not in {"worker", "designer"}:
                raise WorkspaceError(f"task {action} 只允许 worker/designer", 3)
            return
        if action == "withdraw":
            if role in {"worker", "designer", "manager"}:
                return
            raise WorkspaceError("task withdraw 只允许作者/执行角色 worker/designer/manager", 3)
        if action == "dispatch":
            if role in {"worker", "designer", "manager"}:
                return
            raise WorkspaceError("task review dispatch 只允许 worker/designer/manager", 3)
        if action in worker_actions and role not in {"worker", "designer", "manager"}:
            raise WorkspaceError(f"task {action} 只允许 worker/designer/manager", 3)
        if action in manager_actions and role != "manager":
            raise WorkspaceError(f"task {action} 只允许 manager", 3)
        if action not in worker_actions | manager_actions | {"start", "submit", "rework"}:
            raise WorkspaceError(f"未知 task 动作: {action}", 3)
        return
    if command == "improve":
        if role == "manager":
            if action == "sync":
                raise WorkspaceError("MFP 同步只允许 meta-flow maintainer", 3)
            return
        if role == "maintainer":
            # meta-flow maintainer：归档只走 dev improve archive；同步/状态只读
            if action in {"sync", "state", "list", "show", "validate"}:
                return
            raise WorkspaceError("maintainer 只能同步 MFP 或用 dev improve 归档源码", 3)
        if role == "designer":
            if action in {"new", "list", "show", "validate", "state"}:
                return
            raise WorkspaceError("designer 只能创建/查看/校验设计改进包", 3)
        if role == "worker":
            if action == "state":
                return
            if action in {"new", "list", "show", "validate"} and getattr(args, "local", False):
                return
            raise WorkspaceError("worker 只能使用 improve --local 创建/查看本地 MFP", 3)
        raise WorkspaceError("无法确定角色；请在工作区根/子项目运行或设置 MF_ROLE", 3)
    if command == "work":
        if role == "manager":
            return
        if role in {"worker", "designer"}:
            if action in {"list", "show", "start", "task", "decision", "verify"}:
                return
            raise WorkspaceError(f"{role} 不能创建工作包/验收（仅 manager）", 3)
        raise WorkspaceError("work 命令只允许 manager/worker/designer", 3)
    if command == "design":
        if role == "designer" and action in {"create", "list", "show"}:
            return
        if role == "manager" and action in {"accept", "list", "show"}:
            return
        if role == "worker" and action in {"list", "show"}:
            return
        raise WorkspaceError("design 命令：designer create/list/show；manager accept/list/show", 3)
    if command == "skill":
        if role in {"manager", "designer", "worker", "maintainer"} and action in {
            "list",
            "show",
            "validate",
        }:
            return
        raise WorkspaceError("skill 命令只读（list/show/validate）", 3)
    if command == "docs":
        if role in {"manager", "designer"}:
            return
        raise WorkspaceError("docs 命令只允许 manager/designer", 3)
    if command == "context":
        if role in {"manager", "designer"}:
            return
        if role == "worker" and action in {"show", "expand"}:
            # R1：worker 受控查看/展开自己的任务 bundle 或 allowed_paths；
            # 具体范围由 context.expand/hot_files 再校验，deny 区不放宽
            return
        raise WorkspaceError(
            "context 命令只允许 manager；worker 仅可 show/expand 自己的任务范围", 3
        )
    if command == "bug":
        # REQ-0018：manager 管理 external；worker 只走 verification 同子项目闭环。
        if role == "manager":
            return
        if role == "worker":
            if action in {"show", "list", "fix", "verify", "close", "escalate"}:
                return
            if action == "add":
                # worker 只能开 verification BUG；具体 flow 在命令内校验
                return
            raise WorkspaceError(
                "worker 只能 list/show/fix/verify/close/escalate 本子项目 verification BUG", 3
            )
        raise WorkspaceError("bug 命令只允许 manager；worker 仅限 verification flow", 3)
    if command == "state":
        if role == "manager":
            return
        raise WorkspaceError("state 命令只允许 manager", 3)
    if command == "verify" and action == "security-card":
        if role in {"manager", "designer", "maintainer", "unbound"}:
            return
        raise WorkspaceError("security-card 校验只允许 manager/designer/maintainer", 3)
    if command == "archive":
        if role in {"manager", "designer"}:
            # 默认 deny；authorize/revoke 由 TTY 校验，show/export 由 grant 校验
            return
        raise WorkspaceError(
            "archive 只允许 manager/designer（默认 deny，需用户 grant）；worker 不得读取",
            3,
        )
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
    role, _root, delivery = _worker_task_scope(args)
    if role == "designer":
        executor = str(task.get("executor_role") or task.get("owner_role") or "worker")
        if executor != "designer":
            raise WorkspaceError("designer 只能访问 design 任务（owner_role=designer）", 3)
        return
    if role != "worker":
        return
    scope = task.get("scope")
    scope = scope if isinstance(scope, dict) else {}
    mode = str(scope.get("mode") or "single_subproject")
    if mode == "workspace":
        raise WorkspaceError("workspace 作用域任务仅 manager 可执行/访问", 3)
    if mode == "cross_subproject":
        projects = [str(item) for item in scope.get("projects") or []]
        if delivery not in projects:
            raise WorkspaceError(
                f"cross_subproject 任务只允许声明子项目执行: {', '.join(projects)}", 3
            )
        return
    if task.get("delivery") and task.get("delivery") != delivery:
        raise WorkspaceError(
            f"worker 只能访问交付库 {delivery} 的任务", 3
        )
    # 版本隔离（REQ-0020/DOCUMENT-MODEL）：worker 只访问当前 R 过程文档。
    try:
        current_roadmap = str(
            state.read_current(resolve_contract(args.project_dir)).get("roadmap") or ""
        )
    except WorkspaceError:
        current_roadmap = ""
    if (
        current_roadmap
        and task.get("roadmap")
        and str(task.get("roadmap")) != current_roadmap
    ):
        raise WorkspaceError(
            f"版本隔离：worker 只能访问当前路标 {current_roadmap} 的任务", 3
        )


def _worker_task_visible(task: dict[str, Any], delivery: str | None) -> bool:
    """worker list 可见性：workspace 任务仅 manager；cross 仅声明 projects。"""
    scope = task.get("scope")
    scope = scope if isinstance(scope, dict) else {}
    mode = str(scope.get("mode") or "single_subproject")
    if mode == "workspace":
        return False
    if mode == "cross_subproject":
        projects = [str(item) for item in scope.get("projects") or []]
        return delivery in projects
    return not task.get("delivery") or task.get("delivery") == delivery


def _print_doctor(
    errors: list[str], as_json: bool, warnings: list[str] | None = None
) -> int:
    warnings = warnings or []
    if as_json:
        _print_json({"ok": not errors, "errors": errors, "warnings": warnings})
    elif errors:
        print("mf doctor: FAIL")
        for error in errors:
            print(f"  - {error}")
        for warning in warnings:
            print(f"  warning: {warning}")
    else:
        print("mf doctor: OK")
        for warning in warnings:
            print(f"  warning: {warning}")
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
    active = data.get("active_view") or {}
    if active:
        requirements = active.get("requirements") or {}
        print(f"活跃需求: {requirements.get('counts') or {}}")
        print(f"  活跃 REQ: {', '.join(requirements.get('active') or []) or '-'}")
        print(f"  活跃 BUG: {', '.join(active.get('bugs') or []) or '-'}")
        print(f"  活跃 MFP: {', '.join(active.get('mfps') or []) or '-'}")
    boundary = data.get("context_boundary") or {}
    if boundary:
        budget = boundary.get("budget") or {}
        tiers = "/".join(boundary.get("tiers") or []) or "hot/warm/cold"
        print(
            f"上下文: {boundary.get('role')} 预算 {budget.get('files')} 文件/"
            f"{budget.get('bytes')}B；分层 {tiers}；expand 需 --reason（mf context expand）"
        )
        areas = boundary.get("read_areas") or []
        print("可读区: " + (", ".join(areas) if areas else "-"))
        if boundary.get("review_gate"):
            print(f"评审门: {boundary['review_gate']}")
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


def _active_view(contract: Path) -> dict[str, Any]:
    """活跃需求/规格/BUG/MFP 状态与证据摘要（MFP-0020 E3）；默认只看活跃。"""
    roadmap = str(state.read_current(contract).get("roadmap") or "")
    try:
        requirements = req.list_requirements(contract)
    except req.ReqError:
        requirements = []
    req_counts: dict[str, int] = {}
    active_reqs = []
    for item in requirements:
        if item.get("roadmap") not in {None, roadmap}:
            continue
        status = str(item.get("status") or "")
        req_counts[status] = req_counts.get(status, 0) + 1
        if status not in {"released", "deferred", "rejected", "proposed"}:
            active_reqs.append(f"{item.get('id')}({status})")
    bugs = bug.list_bugs(contract, active_only=True, roadmap=roadmap or None)
    try:
        mfps = list_improvements(contract, scope="contract", active_only=True)
    except ImproveError:
        mfps = []
    return {
        "requirements": {
            "counts": req_counts,
            "active": active_reqs[:20],
        },
        "bugs": [
            f"{item.get('id')}({item.get('severity')}/{item.get('status')})"
            for item in bugs[:20]
        ],
        "mfps": [
            f"{item.get('id')}({item.get('status')})" for item in mfps[:20]
        ],
    }


def _workspace_view(root: Path) -> dict[str, Any]:
    data = workspace_status(root)
    try:
        contract = resolve_contract(root)
        data["hot_state"] = state.refresh_current(contract)
        data["tasks"] = task_summary(root)
        data["active_view"] = _active_view(contract)
        policy_data = context.policy(contract)
        roles = policy_data.get("roles") or {}
        manager_budget = (roles.get("manager") or {}).get("budget") or {
            "files": 12,
            "bytes": 131072,
        }
        tiers = list((policy_data.get("tiers") or {}).keys())
        roadmap_id = str((data.get("hot_state") or {}).get("roadmap") or "")
        read_areas = []
        for relative in (
            f"roadmap/{roadmap_id}" if roadmap_id else None,
            "requirements",
            "architecture",
            "specs",
            "knowledge",
            "verification",
            "bugs",
        ):
            if relative and (contract / relative).is_dir():
                read_areas.append(relative)
        data["context_boundary"] = {
            "role": "manager",
            "budget": {
                "files": int(manager_budget.get("files", 12)),
                "bytes": int(manager_budget.get("bytes", 131072)),
            },
            "tiers": tiers,
            "read_areas": read_areas,
            "expand_reason_required": True,
            "review_gate": "高风险任务由未参与实现的独立 reviewer 评审；实现者不自验收；"
            "结论 PASS|PASS_WITH_RISK|NEEDS_REWORK|BLOCKED；"
            "PASS_WITH_RISK 记录风险与接受人；每任务后 mf task prompt 明确 next_owner",
        }
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
        roadmap=args.roadmap,
        phase=args.phase,
        version=args.version,
        roadmap_title=args.roadmap_title,
    )
    print(f"契约库: {result['contract_dir']}")
    print(f"基线: {result['roadmap']}/{result['phase']} @ {result['version']}")
    print(f"CLAUDE.md 导入: {result['claude_import']}")
    print(f"README 链接: {result['readme_link_mode']}")
    return 0


def _cmd_workspace_attach(args: argparse.Namespace) -> int:
    result = workspace_attach(
        args.project_dir,
        args.name,
        contract_dir=args.contract_dir,
        contract_remote=args.contract_remote,
        link_mode=args.link_mode,
    )
    print(f"已接入契约库: {result['contract_dir']}")
    print(f"项目: {result['project_name']} ({result['project_id']})")
    print(f"基线: {result['roadmap']}/{result['phase']} @ {result['version']}")
    print(f"子项目登记: {len(result['subprojects'])}")
    if result["created"]:
        print("补齐注册文件: " + ", ".join(result["created"]))
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
    reset = bool(getattr(args, "reset", False))
    as_role = getattr(args, "as_role", None)
    if reset and as_role:
        raise WorkspaceError("--reset 与 --as 不能同时使用", 3)
    if reset:
        effective, _ = _effective_role(args)
        if effective != "maintainer":
            raise WorkspaceError("mf role --reset 只允许 maintainer 会话执行", 3)
        data = roles.reset_anchor(Path(args.path))
        if args.json:
            _print_json(data)
        else:
            print(f"角色锚点已清理: {data['root']}")
            print(f"移除: {', '.join(data['removed']) if data['removed'] else '无'}")
        return 0
    if as_role:
        data = roles.switch_role(
            as_role,
            getattr(args, "reason", "") or "",
            cwd=Path(args.path),
        )
        if args.json:
            _print_json(data)
        else:
            print(f"角色: {data['role']}（锚点已更新，source=user-tty；ledger role.switch）")
            print(f"路径: {data['root']}")
        return 0
    info = roles.describe(Path(args.path))
    anchor = info["anchor"]
    effective = info["effective"]
    if args.json:
        _print_json(
            {
                "role": effective,
                "source": info["source"],
                "detected": info["detected"],
                "detected_root": info["detected_root"],
                "session_id": info.get("session_id"),
                "anchor": anchor,
            }
        )
    else:
        print(f"角色: {effective}（来源: {info['source']}）")
        root = anchor["root"] if anchor else info["detected_root"]
        if root:
            print(f"路径: {root}")
        if (
            anchor is not None
            and info["detected"] not in {"unbound", effective}
        ):
            print(
                f"提示: 当前目录推导为 {info['detected']}，会话锚点为 {effective}；"
                f"如需复位请在用户终端运行 mf role --as {info['detected']} --reason \"<原因>\""
            )
    return 0 if effective != "unbound" else 2


def _cmd_maintainer_authorize_external(args: argparse.Namespace) -> int:
    data = roles.authorize_external(
        args.action_name,
        getattr(args, "reason", "") or "",
        cwd=Path(getattr(args, "path", ".") or "."),
        ttl_minutes=int(getattr(args, "ttl_minutes", 10) or 10),
    )
    if getattr(args, "json", False):
        _print_json(data)
    else:
        print(
            f"外部动作已授权: {data['action']}（approved_by=user，"
            f"有效期至 {data['expires_at']}；ledger maintainer.external_authorize）"
        )
    return 0


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
    scope = getattr(args, "scope", None)
    if scope in {"docs", "process"}:
        contract = resolve_contract(Path(args.path))
        issues = (
            docmodel.docs_check(contract)
            if scope == "docs"
            else docmodel.process_check(contract)
        )
        if args.json:
            _print_json({"scope": scope, "ok": not issues, "issues": issues})
        elif issues:
            print(f"doctor {scope}: FAIL（{len(issues)} 项 warning/error）")
            for issue in issues:
                print(f"  - {issue}")
        else:
            print(f"doctor {scope}: OK")
        return 0 if not issues else 1
    if args.global_scope:
        return _print_doctor(doctor_global(), args.json)
    path = Path(args.path).expanduser().resolve()
    root = find_workspace_root(path)
    if root is None:
        if (path / INSTALL_REL).is_file():
            root = path
        else:
            raise WorkspaceError("未找到工作区或项目安装", 2)
    return _print_doctor(doctor(root), args.json, doctor_warnings(root))


def _cmd_dev_clone(args: argparse.Namespace) -> int:
    source = dev_clone(dest=args.dest, repo=args.repo)
    print(f"源码: {source}")
    return 0


def _cmd_dev_update(args: argparse.Namespace) -> int:
    source = dev_update(source=args.source)
    print(f"已更新: {source}")
    return 0


def _cmd_dev_install(args: argparse.Namespace) -> int:
    # MFP-0029：uv 在 pyproject 版本号不变时会复用缓存构建，静默安装旧代码。
    # 同版本源码迭代必须强制重建；完整修复（--reinstall 与安装后自检）见 MFP-0029。
    os.environ.setdefault("UV_NO_CACHE", "1")
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
    items = list_improvements(
        args.project_dir,
        scope=scope,
        status=args.status,
        active_only=not getattr(args, "all", False),
    )
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


def _load_security_arg(raw: str | None) -> dict[str, Any] | None:
    """加载 `--security`：YAML/JSON 文件路径或内联 YAML/JSON（T033 R3）。"""
    if not raw:
        return None
    candidate = Path(raw).expanduser()
    text = candidate.read_text(encoding="utf-8") if candidate.is_file() else raw
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise TaskError(f"--security 不是合法 YAML/JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise TaskError("--security 顶层必须是映射")
    return data


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
    estimate_data = None
    if getattr(args, "estimate", None):
        parsed = yaml.safe_load(args.estimate)
        if not isinstance(parsed, dict):
            raise TaskError("--estimate 必须是映射，如 '{vu: 2, effort_hours: 3, confidence: medium}'")
        estimate_data = parsed
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
        module=getattr(args, "module", None),
        spec_ids=getattr(args, "spec_id", None) or [],
        evidence=getattr(args, "evidence", None) or [],
        owner_role=getattr(args, "owner_role", None),
        executor_role=getattr(args, "executor_role", None),
        owner_confirmed_by=getattr(args, "owner_confirmed_by", None),
        scope_mode=getattr(args, "scope_mode", None),
        scope_projects=getattr(args, "scope_project", None),
        scope_operations=getattr(args, "scope_operation", None),
        scope_justification=getattr(args, "scope_justification", None),
        security=_load_security_arg(getattr(args, "security", None)),
        actor_role=_effective_role(args)[0],
        with_review=not args.no_review,
        from_data=from_data,
        estimate=estimate_data,
        slice=getattr(args, "slice", None),
        verify=getattr(args, "verify", None),
    )
    print(f"任务: {result['task']} ({result['status']}, risk={result['risk']})")
    if result.get("review_task"):
        print(f"评审任务: {result['review_task']}")
    print(f"bundle: {result['bundle']}")
    print(f"下一步: mf task prompt {result['task']}")
    return 0


def _cmd_task_list(args: argparse.Namespace) -> int:
    role, _root, delivery = _worker_task_scope(args)
    items = list_tasks(
        args.project_dir,
        status=args.status,
        delivery=delivery if role == "worker" else None,
        active_only=not getattr(args, "all", False),
    )
    if role == "worker":
        items = [item for item in items if _worker_task_visible(item, delivery)]
        # 版本隔离：worker 只列当前 R 的任务
        current = str(
            state.read_current(resolve_contract(args.project_dir)).get("roadmap") or ""
        )
        if current:
            items = [
                item
                for item in items
                if not item.get("roadmap") or str(item.get("roadmap")) == current
            ]
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
    _worker_task_scope(args)
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
        print(summary_text(data, resolve_contract(args.project_dir)))
        print("")
        print(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    return 0


def _cmd_task_validate(args: argparse.Namespace) -> int:
    _worker_task_scope(args)
    _, current = load_task(args.project_dir, args.task_id)
    _ensure_worker_scope(args, current)
    result = validate_task(args.project_dir, args.task_id)
    if args.json:
        _print_json(result)
        return 0 if result.get("ok") else 1
    print(f"任务: {result['task']} status={result.get('status')}")
    for message in result.get("warnings") or []:
        print(f"  warning: {message}")
    for message in result.get("errors") or []:
        print(f"  error: {message}")
    print("mf task validate: OK" if result.get("ok") else "mf task validate: FAIL")
    return 0 if result.get("ok") else 1


def _cmd_task_start(args: argparse.Namespace) -> int:
    _worker_task_scope(args)
    _, current = load_task(args.project_dir, args.task_id)
    _ensure_worker_scope(args, current)
    data = start_task(args.project_dir, args.task_id, owner=args.owner)
    print(f"{data['id']} -> {data['status']} (next={data['next_owner']})")
    return 0


def _cmd_task_submit(args: argparse.Namespace) -> int:
    _worker_task_scope(args)
    _, current = load_task(args.project_dir, args.task_id)
    _ensure_worker_scope(args, current)
    data = submit_task(
        args.project_dir,
        args.task_id,
        handoff=args.handoff,
        dev_record=args.dev_record,
        owner=args.owner,
        blocked=args.blocked,
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
        legacy_rework=args.legacy_rework,
    )
    print(f"{data['id']} -> {data['status']} (verdict={args.verdict})")
    decision = data.get("rework_decision")
    if isinstance(decision, dict):
        if decision.get("already_in_progress"):
            if decision.get("lease_valid"):
                print(
                    f"manager 审计通知: {decision['task']} 已在返工中（in_progress）；"
                    "保留 next_owner=worker、lease 与 rework 元数据，worker 可继续 submit"
                )
            else:
                print(
                    f"manager 审计通知: {decision['task']} 处于 in_progress 但 lease 已失效；"
                    "已保留 rework 元数据，请回收 lease 或让 worker 重新开始"
                )
        elif decision.get("auto"):
            print(
                f"manager 审计通知: 已自动回流 {decision['task']}"
                f"（review={data['id']}，risk={decision.get('risk_level') or '-'}，"
                f"整改项={', '.join(decision.get('items') or []) or '-'}）；"
                f"worker 用 mf task rework {decision['task']} 开始"
            )
        else:
            print(
                f"manager 审计通知: {decision['task']} 未自动回流"
                f"（{decision.get('reason') or '-'}）；"
                "请补齐 rework_summary/范围声明后重开，或按范围外开 CHG/BUG/MFP/新卡"
            )
        print(f"下一步: mf task prompt {decision['task']}")
    return 0


def _cmd_task_rework(args: argparse.Namespace) -> int:
    _worker_task_scope(args)
    _, current = load_task(args.project_dir, args.task_id)
    _ensure_worker_scope(args, current)
    data = rework_task(
        args.project_dir,
        args.task_id,
        owner=args.owner,
        note=args.note,
    )
    rework = data.get("rework") or {}
    print(
        f"{data['id']} -> {data['status']} "
        f"(review={rework.get('review_task')}, next={data['next_owner']})"
    )
    print("整改项: " + (", ".join(rework.get("items") or []) or "-"))
    print("ledger task.rework 已记录（含 review / 整改项 / lease）；manager 仅审计")
    print(f"下一步: mf task prompt {data['id']}")
    return 0


def _cmd_task_withdraw(args: argparse.Namespace) -> int:
    _worker_task_scope(args)
    _, current = load_task(args.project_dir, args.task_id)
    _ensure_worker_scope(args, current)
    data = withdraw_task(
        args.project_dir,
        args.task_id,
        reason=args.reason,
        owner=args.owner,
    )
    print(
        f"{data['id']} -> {data['status']} "
        f"(withdraw_count={data.get('withdraw_count')}, next={data['next_owner']})"
    )
    print("ledger task.withdraw 已记录；review（draft/ready）已取消/挂起；证据保留")
    print(f"补充后重新运行: mf task submit {data['id']}")
    return 0


def _cmd_task_review_dispatch(args: argparse.Namespace) -> int:
    data = dispatch_review(
        args.project_dir,
        args.task_id,
        host=args.host,
        owner=args.owner,
        session_id=args.session_id,
        reason=args.reason,
        fallback=args.fallback,
    )
    dispatch = data.get("dispatch") or {}
    print(
        f"{data['id']} dispatch={dispatch.get('spawn_state')} "
        f"host={dispatch.get('host')} owner={dispatch.get('owner') or '-'} "
        f"role={dispatch.get('reviewer_role')}"
    )
    print("ledger 已记录（review.spawn / orchestration.fallback）；实际执行走 mf task start/submit")
    return 0


def _cmd_task_reject(args: argparse.Namespace) -> int:
    data = reject_task(args.project_dir, args.task_id, args.reason)
    print(f"{data['id']} -> {data['status']} (next={data['next_owner']})")
    return 0


def _cmd_task_prompt(args: argparse.Namespace) -> int:
    _worker_task_scope(args)
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
    print(f"BLOCKED: {', '.join(data.get('blocked_tasks') or []) or '-'}")
    print(f"就绪: {', '.join(data['ready_tasks']) or '-'}")
    print(f"blocker/critical BUG: {data['open_bugs']}")
    if data["next"]:
        print("下一批:")
        for item in data["next"]:
            print(f"  {item['id']} wave={item['wave']} {item['title']}")
    return 0


def _cmd_state_show(args: argparse.Namespace) -> int:
    contract = resolve_contract(args.project_dir)
    data = state.read_current(contract)
    issues = state.reconcile(contract)
    if args.json:
        _print_json({"ok": not issues, "issues": issues, "state": data})
        return 0 if not issues else 1
    print(f"当前: {data.get('roadmap')} / {data.get('phase')} ({data.get('phase_status')})")
    print(f"counts: {data.get('counts') or {}}")
    print(f"next_action: {data.get('next_action') or '-'}")
    if issues:
        print("状态对账: FAIL")
        for issue in issues:
            print(f"  - {issue}")
        print("修复: mf state rebuild")
        return 1
    print("状态对账: OK")
    return 0


def _cmd_state_rebuild(args: argparse.Namespace) -> int:
    contract = resolve_contract(args.project_dir)
    data = state.rebuild(contract)
    print(
        f"state 已重建: counts={data.get('counts') or {}} "
        f"active={len(data.get('active_tasks') or [])} "
        f"leases={len(data.get('active_leases') or [])}"
    )
    issues = state.reconcile(contract)
    if issues:
        print("重建后仍有差异:")
        for issue in issues:
            print(f"  - {issue}")
        return 1
    print("状态对账: OK（ledger 已记录 state.rebuild）")
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
    data = req.trace(
        args.project_dir,
        args.req_id,
        roadmap=roadmap,
        include_archive=args.archive,
    )
    check = getattr(args, "check", False)
    issues = req.orphans(resolve_contract(args.project_dir), roadmap=roadmap) if check else []
    if args.json:
        if check:
            _print_json({"ok": not issues, "orphans": issues, "trace": data})
        else:
            _print_json(data)
        return 0 if not issues else 1
    if args.req_id:
        print(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    else:
        print("已写入: requirements/TRACE.md")
        for req_id, entry in data.items():
            print(
                "{req} specs={specs} tasks={tasks} evidence={evidence} vr={vr} bugs={bugs} "
                "improvements={improvements} releases={releases}".format(
                    req=req_id,
                    specs=len(entry.get("specs") or []),
                    tasks=len(entry.get("tasks") or []),
                    evidence=len(entry.get("evidence") or []),
                    vr=len(entry.get("verification") or []),
                    bugs=len(entry.get("bugs") or []),
                    improvements=len(entry.get("improvements") or []),
                    releases=len(entry.get("releases") or []),
                )
            )
    if check:
        if issues:
            print("孤儿/未闭环检查: FAIL")
            for issue in issues:
                print(f"  - {issue}")
            return 1
        print("孤儿/未闭环检查: OK")
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


def _cmd_roadmap_sizing(args: argparse.Namespace) -> int:
    data = roadmap.sizing(args.project_dir, args.roadmap_id)
    if args.json:
        _print_json(data)
        return 0
    estimate = data["estimate"]
    print(
        f"{data['roadmap']} profile={data['flow_profile']} "
        f"tasks={data['task_count']} VU={estimate['vu_count']} "
        f"effort={estimate['effort_hours']}h confidence={estimate['confidence']} "
        f"suggestion={data['suggestion']}"
    )
    print(data["note"])
    return 0


def _cmd_roadmap_classify(args: argparse.Namespace) -> int:
    data = roadmap.classify(
        args.project_dir,
        args.roadmap_id,
        flow=args.flow,
        decided_by=args.decided_by,
        reason=args.reason,
    )
    if args.json:
        _print_json(data)
        return 0
    print(
        f"{data['roadmap']} flow_profile={data['flow_profile']} "
        f"(decided_by=user, {data['decision']['decided_at']})"
    )
    for phase, entry in data["phase_plan"].items():
        hint = f" -> {entry.get('target')}" if entry.get("target") else ""
        print(f"  {phase}: {entry['mode']}{hint}")
    print(f"VERSION: {data['version']}；SIZING: {data['sizing']}")
    return 0


def _cmd_phase_show(args: argparse.Namespace) -> int:
    data = roadmap.phase_view(args.project_dir)
    if args.json:
        _print_json(data)
        return 0
    print(
        f"{data['roadmap']} current={data['current']}/{data['current_status']} "
        f"flow_profile={data['flow_profile']}（{data['source']}）"
    )
    for item in data["phases"]:
        target = f" -> {item['target']}" if item.get("target") else ""
        print(
            f"  {item['phase']} {item['name']}: {item['mode']}{target} "
            f"[{item['status']}]"
        )
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
    role, root, delivery = _worker_task_scope(args)
    flow = getattr(args, "flow", "external")
    subproject = getattr(args, "subproject", None)
    if role == "worker":
        if flow != "verification":
            raise bug.BugError("worker 只能记录 verification BUG（同子项目）；external BUG 由 manager 登记", 3)
        if subproject and str(subproject) != str(delivery):
            raise bug.BugError(
                f"worker 只能登记本子项目 verification BUG: {delivery}", 3
            )
        subproject = delivery
    item = bug.add_bug(
        args.project_dir,
        args.title,
        severity=args.severity,
        phase=args.phase,
        task=args.task,
        verification=args.verification,
        delivery=args.delivery or (delivery if role == "worker" else None),
        related_reqs=args.requirement or [],
        environment=args.environment or "",
        steps=args.steps or "",
        expected=args.expected or "",
        actual=args.actual or "",
        evidence=args.evidence or [],
        flow=flow,
        scope=getattr(args, "scope", "same_subproject"),
        subproject=subproject,
        found_by=getattr(args, "found_by", None) or role,
    )
    print(f"缺陷: {item['id']} ({item['flow']}, {item['severity']}, {item['status']})")
    return 0


def _read_log_append(contract: Path, record: dict[str, Any]) -> None:
    log_path = contract / "state" / "READ-LOG.ndjson"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ts": datetime.now(UTC).isoformat(), **record}
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _cmd_bug_list(args: argparse.Namespace) -> int:
    role, _root, delivery = _worker_task_scope(args)
    contract = resolve_contract(args.project_dir)
    current = str(state.read_current(contract).get("roadmap") or "")
    roadmap = args.roadmap
    if roadmap is None and not args.all:
        roadmap = current or "R1"
    include_closed = bool(getattr(args, "include_closed", False))
    subproject = getattr(args, "subproject", None)
    if role == "worker":
        subproject = None  # 在下方按严格 own-subproject 过滤，避免宽松匹配
    if include_closed:
        reason = str(getattr(args, "reason", None) or "").strip()
        authorized_by = str(getattr(args, "authorized_by", None) or "").strip()
        if not reason or not authorized_by:
            raise bug.BugError("查询 closed BUG 必须提供用户授权 --authorized-by 与 --reason", 3)
        if authorized_by.lower() in bug.CONFIRMER_ROLE_WORDS:
            raise bug.BugError("closed BUG 查询授权人不能是角色/系统身份", 3)
        _read_log_append(
            contract,
            {
                "event": "bug.list.closed",
                "actor": role,
                "role": role,
                "tool": "mf bug list",
                "decision": "allow",
                "path": "bugs/*",
                "reason": reason,
                "authorized_by": authorized_by,
            },
        )
    elif role == "manager" and getattr(args, "history", False):
        # manager 历史查询留审计（不需要用户授权，但保留口径）
        _read_log_append(
            contract,
            {
                "event": "bug.list.closed",
                "actor": role,
                "role": role,
                "tool": "mf bug list",
                "decision": "allow",
                "path": "bugs/*",
                "reason": "manager-history",
            },
        )
    items = bug.list_bugs(
        args.project_dir,
        status=args.status,
        severity=args.severity,
        roadmap=roadmap,
        active_only=False
        if role == "worker"
        else (not getattr(args, "history", False)) and not include_closed,
        flow=getattr(args, "flow", None),
        subproject=subproject,
        include_closed=include_closed,
    )
    if role == "worker":
        visible = []
        for item in items:
            own = item.get("subproject") == delivery or item.get("delivery") == delivery
            if not own:
                continue
            if current and item.get("roadmap") not in {None, current}:
                continue
            if item.get("status") in bug.OPEN_STATUSES:
                visible.append(item)
            elif (
                item.get("flow") == "verification"
                and item.get("status") == "closed"
                and item.get("roadmap") == current
            ):
                # REQ-0018 AC4 / INFO-FLOWS §4.6：同子项目当前 R closed verification 只读可见
                visible.append(item)
            elif include_closed and item.get("status") in bug.CLOSED_STATUSES:
                visible.append(item)
        items = visible
    if args.json:
        _print_json(items)
        return 0
    if not items:
        print("没有缺陷")
        return 0
    for item in items:
        print(
            "{id} {severity} {status} {flow} {title}".format(
                id=item.get("id"),
                severity=item.get("severity"),
                status=item.get("status"),
                flow=item.get("flow", "external"),
                title=item.get("title"),
            )
        )
    return 0


def _cmd_bug_show(args: argparse.Namespace) -> int:
    role, _root, delivery = _worker_task_scope(args)
    if role == "worker":
        contract = resolve_contract(args.project_dir)
        current = str(state.read_current(contract).get("roadmap") or "")
        data = bug.show_bug(args.project_dir, args.bug_id)
        linked = bug.linked_bug_ids(contract, delivery)
        same_subproject = (
            (data.get("subproject") == delivery or data.get("delivery") == delivery)
            and (not current or data.get("roadmap") in {None, current})
        )
        open_own = same_subproject and data.get("status") in bug.OPEN_STATUSES
        closed_verification = (
            same_subproject
            and data.get("flow") == "verification"
            and data.get("status") == "closed"
            and data.get("roadmap") == current
        )
        if args.bug_id not in linked and not open_own and not closed_verification:
            raise bug.BugError(
                f"worker 只能读取活动任务关联、本子项目 open 或同子项目 closed verification BUG: {args.bug_id}",
                3,
            )
        _read_log_append(
            contract,
            {
                "event": "bug.show",
                "actor": "worker",
                "role": "worker",
                "task": "active",
                "tool": "mf bug show",
                "decision": "allow",
                "path": f"bugs/{args.bug_id}.yaml",
                "reason": "task-linked-bug"
                if args.bug_id in linked
                else "same-subproject-verification"
                if closed_verification
                else "same-subproject-open",
            },
        )
    if getattr(args, "packet", False):
        data = bug.bug_packet(args.project_dir, args.bug_id)
    else:
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
        fix_owner=getattr(args, "fix_owner", None),
    )
    print(f"{data['id']} -> {data['status']} ({data['severity']})")
    return 0


def _cmd_bug_fix(args: argparse.Namespace) -> int:
    role, _root, delivery = _worker_task_scope(args)
    data = bug.show_bug(args.project_dir, args.bug_id)
    session = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if role == "worker":
        if data.get("flow") != "verification":
            raise bug.BugError("worker 只能修复 verification BUG；external BUG 由 manager 分派", 3)
        if data.get("subproject") and data.get("subproject") != delivery:
            raise bug.BugError("verification BUG 只允许同子项目 worker 修复", 3)
    fix_owner = args.by or (session if role == "worker" else None)
    if role == "worker" and not fix_owner:
        raise bug.BugError(
            "worker 修复 verification BUG 必须提供 --by 或宿主会话标识（不得用子项目名代替身份）", 3
        )
    data = bug.update_bug(
        args.project_dir,
        args.bug_id,
        status="fixed" if args.fixed else "in_fix",
        fix_task=args.task,
        fix_owner=str(fix_owner) if fix_owner else None,
        fix_session=session if role == "worker" else None,
    )
    print(f"{data['id']} -> {data['status']} (fix_owner={data.get('fix_owner') or '-'})")
    return 0


def _cmd_bug_verify(args: argparse.Namespace) -> int:
    role, _root, delivery = _worker_task_scope(args)
    session = os.environ.get("CLAUDE_CODE_SESSION_ID")
    by = args.by or (session if role == "worker" else None)
    if role == "worker" and not by:
        raise bug.BugError(
            "worker 验证必须提供 --by 或宿主会话标识（不得用子项目名代替身份）", 3
        )
    data = bug.verify_bug(
        args.project_dir,
        args.bug_id,
        by=str(by or ""),
        evidence=args.evidence or [],
        subproject=delivery if role == "worker" else getattr(args, "subproject", None),
        viewer_session=session if role == "worker" else None,
    )
    print(
        f"{data['id']} -> {data['status']} (verified_by={data.get('verified_by')})"
    )
    return 0


def _cmd_bug_escalate(args: argparse.Namespace) -> int:
    role, _root, _delivery = _worker_task_scope(args)
    data = bug.escalate_bug(
        args.project_dir,
        args.bug_id,
        reason=args.reason,
        escalated_by=args.by or role,
    )
    print(f"{data['id']} -> {data['status']} (flow={data.get('flow')}, scope={data.get('scope')})")
    return 0


def _cmd_bug_close(args: argparse.Namespace) -> int:
    role, _root, delivery = _worker_task_scope(args)
    session = os.environ.get("CLAUDE_CODE_SESSION_ID")
    data = bug.show_bug(args.project_dir, args.bug_id)
    by = args.by
    if role == "worker":
        if data.get("flow") != "verification":
            raise bug.BugError("worker 不得关闭 external BUG；需用户确认后由 manager 关闭", 3)
        by = by or session
        if not by:
            raise bug.BugError(
                "worker 关闭 verification BUG 必须提供 --by 或宿主会话标识", 3
            )
    if data.get("flow") == "verification":
        closed = bug.close_bug(
            args.project_dir,
            args.bug_id,
            verification=args.verification,
            resolution=args.resolution,
            by=by,
            evidence=args.evidence or [],
            subproject=delivery if role == "worker" else args.subproject,
            viewer_session=session if role == "worker" else None,
        )
    else:
        if role == "worker":
            raise bug.BugError("external BUG 关闭只允许 manager 执行", 3)
        closed = bug.close_bug(
            args.project_dir,
            args.bug_id,
            verification=args.verification,
            resolution=args.resolution,
            confirmed_by=args.confirmed_by,
            note=args.note,
        )
    print(
        f"{closed['id']} -> {closed['status']} "
        f"(closure_type={closed.get('closure_type')}, "
        f"confirmed_by={(closed.get('confirmation') or {}).get('confirmed_by') or '-'})"
    )
    return 0


def _cmd_bug_audit(args: argparse.Namespace) -> int:
    contract = resolve_contract(args.project_dir)
    issues = bug.audit_bugs(contract)
    if args.json:
        _print_json({"ok": not issues, "issues": issues})
    else:
        if issues:
            print("BUG 状态审计: FAIL")
            for issue in issues:
                print(f"  - {issue}")
        else:
            print("BUG 状态审计: OK")
    return 0 if not issues else 1


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
        command=getattr(args, "command", None),
        environment=(
            yaml.safe_load(args.environment) if getattr(args, "environment", None) else None
        ),
        result_digest=getattr(args, "result_digest", None),
        artifacts=getattr(args, "artifact", None) or None,
        reuse_of=getattr(args, "reuse_of", None),
        risk=getattr(args, "risk", None),
        retention_class=getattr(args, "retention", None),
    )
    print(f"验证记录: {item['id']} ({item['layer']}, {item['result']})")
    return 0


def _cmd_verify_index(args: argparse.Namespace) -> int:
    data = verify.evidence_index(args.project_dir)
    if args.json:
        _print_json(data)
        return 0
    summary = data["summary"]
    print(
        f"证据索引: total={summary.get('total', 0)} PASS={summary.get('PASS', 0)} "
        f"PASS_WITH_RISK={summary.get('PASS_WITH_RISK', 0)} "
        f"FAIL={summary.get('FAIL', 0)} BLOCKED={summary.get('BLOCKED', 0)}"
    )
    if data["evidence_debt"]:
        print("evidence debt:")
        for issue in data["evidence_debt"]:
            print(f"  - {issue}")
    else:
        print("evidence debt: 无")
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


def _cmd_verify_security_card(args: argparse.Namespace) -> int:
    result = verify.security_card_check(args.path)
    if args.json:
        _print_json(result)
    elif result["ok"]:
        print(f"安全卡 OK: {result['path']}")
    else:
        print("安全卡校验失败:")
        for error in result["errors"]:
            print(f"  - {error}")
    return 0 if result["ok"] else 1


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
        reason=args.reason,
        approved_by=args.approved_by,
        source_dir=args.source_dir,
    )
    print(f"已冻结: {result['version']} ({result['roadmap']})")
    stage = result.get("stage") or {}
    if stage:
        print(f"阶段: {stage.get('phase')}/{stage.get('phase_status')}")
    print(f"清单: {result['manifest']}")
    print(f"published: {result['published']}；冻结不等于发布")
    print(f"已知问题: {result['known_issues']}")
    if args.force:
        print(f"override: reason={args.reason or '-'} approved_by={args.approved_by or '-'}")
    return 0


def _cmd_release_check(args: argparse.Namespace) -> int:
    result = verify.release_check(
        args.project_dir,
        version=args.version,
        source_dir=args.source_dir,
        require_tag=args.require_tag,
    )
    if args.json:
        _print_json(result)
    else:
        status = "OK" if result["ok"] else "FAIL"
        print(f"版本一致性: {status} ({result['version']})")
        for item in result["checks"]:
            if item.get("skipped"):
                mark = "SKIP"
            else:
                mark = "OK" if item["ok"] else "FAIL"
            actual = item.get("actual") if item.get("actual") is not None else "-"
            print(f"  {mark} {item['name']}: {actual} (期望 {item['expected']})")
            if item.get("detail"):
                print(f"       {item['detail']}")
        for error in result["errors"]:
            print(f"错误: {error}", file=sys.stderr)
    return 0 if result["ok"] else 1


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
    label = "任务 bundle 文件" if data.get("scope") == "task-bundle" else "热文件"
    print(f"{label}:")
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
        start=args.start,
        end=args.end,
        max_bytes=args.max_bytes,
    )
    header = f"# {data['path']} ({data['bytes']} bytes, reason={data['reason']}"
    if data.get("segmented"):
        header += (
            f", segment={data['start']}..{data['end']}"
            f"/{data['total_bytes']}"
        )
    header += ")"
    print(header)
    print(data["text"], end="" if data["text"].endswith("\n") else "\n")
    return 0


def _cmd_context_log(args: argparse.Namespace) -> int:
    items = context.read_log(args.project_dir, limit=args.limit)
    if args.json:
        _print_json(items)
        return 0
    for item in items:
        print(
            "{ts} {actor} {event} {path} reason={reason} tool={tool} "
            "decision={decision} task={task}".format(
                ts=item.get("ts"),
                actor=item.get("actor"),
                event=item.get("event"),
                path=item.get("path"),
                reason=item.get("reason"),
                tool=item.get("tool") or "-",
                decision=item.get("decision") or "-",
                task=item.get("task") or "-",
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
    items = context.archive_list(args.project_dir, actor=args.actor)
    if args.json:
        _print_json(items)
        return 0
    if not items:
        print("没有归档（或没有有效 grant）")
        return 0
    for item in items:
        print(
            f"{item['roadmap']} files={item['files']} index={item['index']} "
            f"grant={item.get('grant_id') or '-'}"
        )
    return 0


def _cmd_archive_show(args: argparse.Namespace) -> int:
    data = context.archive_show(
        args.project_dir,
        args.roadmap_id,
        reason=args.reason,
        actor=args.actor,
        grant_id=getattr(args, "grant", None),
        path=getattr(args, "path", None),
    )
    if args.json:
        _print_json(data)
        return 0
    print(
        f"归档: {data['path']} (reason={data['reason']}, "
        f"grant={data.get('grant_id') or 'maintainer'})"
    )
    if data.get("index"):
        print(data["index"], end="")
    if data.get("files"):
        print("\n文件:")
        for name in data["files"]:
            print(f"  {name}")
    return 0


def _cmd_archive_authorize(args: argparse.Namespace) -> int:
    data = context.authorize_archive(
        args.project_dir,
        role=args.role,
        roadmap=args.roadmap,
        scope=args.scope,
        purpose=args.purpose,
        ttl_minutes=args.ttl_minutes,
        max_bytes=args.max_bytes,
        max_files=args.max_files,
        one_shot=not args.multi_use,
    )
    if args.json:
        _print_json(data)
    else:
        print(
            f"grant: {data['grant_id']} role={data['role']} roadmap={data['roadmap']} "
            f"scope={', '.join(data['scope'])} purpose={data['purpose']} "
            f"expires={data['expires_at']}"
        )
    return 0


def _cmd_archive_revoke(args: argparse.Namespace) -> int:
    data = context.revoke_archive(args.project_dir, args.grant_id)
    if args.json:
        _print_json(data)
    else:
        print(f"grant 已撤销: {data['grant_id']}")
    return 0


def _cmd_archive_export(args: argparse.Namespace) -> int:
    data = context.archive_export(
        args.project_dir,
        grant_id=args.grant,
        roadmap=getattr(args, "roadmap", None),
        to=args.to,
        actor=args.actor,
    )
    if args.json:
        _print_json(data)
    else:
        print(
            f"已导出 {len(data['files'])} 文件到 {data['to']} "
            f"(digest={data['digest']}, manifest={data['manifest']})"
        )
    return 0



def _cmd_hook_pretool(args: argparse.Namespace) -> int:
    return guard.run_hook()


def _cmd_hook_session_start(args: argparse.Namespace) -> int:
    import json as _json

    try:
        payload = _json.load(sys.stdin)
    except _json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    # M1b：SessionStart 必须携带宿主会话标识；缺失时不写共享锚点（fail-closed）
    if payload.get("hook_event_name") not in (None, "SessionStart"):
        return 0
    session_id = str(payload.get("session_id") or "").strip() or None
    if session_id is None:
        return 0
    cwd = Path(str(payload.get("cwd") or Path.cwd()))
    roles.session_start(
        cwd,
        session_id=session_id,
        source=str(payload.get("source") or "startup"),
    )
    return 0


def _cmd_install_designer(args: argparse.Namespace) -> int:
    result = install_designer(
        args.project_dir,
        workspace_root=args.workspace_root,
        force=args.force,
    )
    print(f"已安装 designer 到: {result['project_dir']}")
    print(f"agents: {', '.join(result['agents'])}")
    print(f"安装记录: {result['install_manifest']}")
    return 0




def _cmd_improve_triage(args: argparse.Namespace) -> int:
    data = improve.triage_improvement(
        args.project_dir,
        args.mfp_id,
        decision=args.decision,
        reason=args.reason,
        next_step=args.next_step,
        target=args.target,
        actor_role=_effective_role(args)[0],
    )
    print(f"{data['id']} -> {data['status']} (next_step={data.get('triage', {}).get('next_step') or '-'})")
    return 0


def _cmd_improve_sync(args: argparse.Namespace) -> int:
    data = improve.sync_improvements(
        args.project_dir,
        from_path=args.from_path,
        source=args.source,
        actor_role=_effective_role(args)[0],
    )
    if args.json:
        _print_json(data)
        return 0
    print(f"MFP 同步: {improve.sync_state_path(args.project_dir)}")
    for mfp_id, entry in sorted((data.get("mfps") or {}).items()):
        print(
            "{id} {status} target={target} version={version}".format(
                id=mfp_id,
                status=entry.get("status"),
                target=entry.get("target") or "-",
                version=(entry.get("resolution") or {}).get("version") or "-",
            )
        )
    return 0


def _cmd_improve_state(args: argparse.Namespace) -> int:
    data = improve.load_sync_state(args.project_dir)
    if args.json:
        _print_json(data)
        return 0
    print(f"last_sync: {data.get('last_sync') or '-'}")
    for mfp_id, entry in sorted((data.get("mfps") or {}).items()):
        print(f"{mfp_id} {entry.get('status')} {entry.get('title') or ''}".rstrip())
    return 0


def _cmd_dev_improve_archive(args: argparse.Namespace) -> int:
    result = improve.archive_improvement(
        args.ref, source=args.source, actor_role=_effective_role(args)[0]
    )
    print(f"MFP: {result['mfp']}")
    print(f"archive: {result['archive']}")
    print(f"index: {result['index']}")
    return 0


def _cmd_dev_improve_index(args: argparse.Namespace) -> int:
    data = improve.archive_index(args.source)
    if args.json:
        _print_json(data)
        return 0
    print(f"updated_at: {data.get('updated_at') or '-'}")
    for item in data.get("mfps") or []:
        print(
            "{id} {status} {source_project} {title}".format(
                id=item.get("id"),
                status=item.get("status"),
                source_project=item.get("source_project") or "-",
                title=item.get("title") or "",
            )
        )
    return 0


def _work_actor(args: argparse.Namespace) -> tuple[str, str | None]:
    """work/design 命令的 actor 角色与子项目（worker 隔离用）。"""
    role, _root, delivery = _worker_task_scope(args)
    return role, delivery


def _cmd_work_create(args: argparse.Namespace) -> int:
    data = work.create_work_package(
        args.project_dir,
        args.subproject,
        title=args.title,
        design_package=args.design_package,
        requirements=args.requirement or [],
        mfps=args.mfp or [],
        specs=args.spec or [],
        design_refs=args.design_ref or [],
        interface_refs=args.interface_ref or [],
        must_read=args.must_read or [],
        allowed_paths=args.allowed_path or [],
        budget=_load_budget(args.budget),
        acceptance=[
            {"id": f"A{index}", "method": "artifact", "expect": text}
            for index, text in enumerate(args.acceptance or [], start=1)
        ],
        phase=args.phase,
        actor_role=_effective_role(args)[0],
    )
    print(f"工作包: {data['id']} ({data['status']})")
    print(f"path: {data['_path']}")
    return 0


def _load_budget(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        raise work.WorkError("--budget 必须是 YAML/JSON 映射")
    return data


def _cmd_work_add_task(args: argparse.Namespace) -> int:
    decision = None
    if args.type == "decision":
        decision = {
            "problem": args.problem,
            "impact": args.impact,
            "options": args.option or [],
            "recommendation": args.recommendation,
            "level": args.level,
            "owner": args.decision_owner,
        }
    role, delivery = _work_actor(args)
    task = work.add_task(
        args.project_dir,
        args.wp_id,
        task_type=args.type,
        goal=args.goal,
        acceptance=args.acceptance or [],
        verification=args.verification,
        context=args.context or [],
        decision=decision,
        verifies=args.verifies or [],
        actor_role=role,
        actor_delivery=delivery,
    )
    print(f"任务: {task['id']} ({task['type']})")
    return 0


def _cmd_work_start(args: argparse.Namespace) -> int:
    role, delivery = _work_actor(args)
    data = work.start_work_package(
        args.project_dir, args.wp_id, actor_role=role, actor_delivery=delivery
    )
    print(f"{data['id']} -> {data['status']}")
    return 0


def _cmd_work_decision(args: argparse.Namespace) -> int:
    role, delivery = _work_actor(args)
    if args.decision_id:
        data = work.record_decision(
            args.project_dir,
            args.wp_id,
            args.decision_id,
            decision=args.decision,
            decided_by=args.decided_by or role,
            actor_role=role,
            confirmed_by=getattr(args, "confirmed_by", None),
            note=getattr(args, "note", None),
            actor_delivery=delivery,
        )
        print(f"{data['id']} 决策已记录 ({args.decision_id})")
        return 0
    task = work.request_decision(
        args.project_dir,
        args.wp_id,
        problem=args.problem,
        impact=args.impact,
        options=args.option or [],
        recommendation=args.recommendation,
        level=args.level,
        owner=args.decision_owner,
        actor_role=role,
        actor_delivery=delivery,
    )
    print(f"决策点: {task['id']} (owner={args.decision_owner}, level={args.level})")
    return 0


def _cmd_work_verify(args: argparse.Namespace) -> int:
    role, delivery = _work_actor(args)
    if args.result:
        _, current = work.find_work_package(
            args.project_dir, args.wp_id, actor_role=role, actor_delivery=delivery
        )
        if current.get("status") == "in_progress":
            work.start_verification(
                args.project_dir,
                args.wp_id,
                verifier=args.verifier or role,
                actor_role=role,
                actor_delivery=delivery,
            )
        data = work.record_verification(
            args.project_dir,
            args.wp_id,
            result=args.result,
            evidence=args.evidence or [],
            notes=args.notes,
            actor_role=role,
            actor_delivery=delivery,
        )
    else:
        data = work.start_verification(
            args.project_dir,
            args.wp_id,
            verifier=args.verifier or role,
            actor_role=role,
            actor_delivery=delivery,
        )
    print(f"{data['id']} -> {data['status']}")
    return 0


def _cmd_work_accept(args: argparse.Namespace) -> int:
    data = work.accept_work_package(
        args.project_dir,
        args.wp_id,
        verdict=args.verdict,
        note=args.note,
        actor_role=_effective_role(args)[0],
    )
    print(f"{data['id']} -> {data['status']} (verdict={args.verdict})")
    return 0


def _cmd_work_list(args: argparse.Namespace) -> int:
    role, delivery = _work_actor(args)
    items = work.list_work_packages(
        args.project_dir,
        subproject=args.subproject,
        status=args.status,
        actor_role=role,
        actor_delivery=delivery,
    )
    if args.json:
        _print_json(items)
        return 0
    if not items:
        print("没有工作包")
        return 0
    for item in items:
        print(
            "{id} {status} {subproject} {title}".format(
                id=item.get("id"),
                status=item.get("status"),
                subproject=item.get("subproject"),
                title=item.get("title"),
            )
        )
    return 0


def _cmd_work_show(args: argparse.Namespace) -> int:
    role, delivery = _work_actor(args)
    _, data = work.find_work_package(
        args.project_dir, args.wp_id, actor_role=role, actor_delivery=delivery
    )
    if args.json:
        _print_json(data)
    else:
        print(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    return 0


def _cmd_design_create(args: argparse.Namespace) -> int:
    data = design.create_design(
        args.project_dir,
        args.title,
        requirements=args.requirement or [],
        mfps=args.mfp or [],
        specs=args.spec or [],
        subprojects=args.subproject or [],
        scope=args.scope or "",
        non_goals=args.non_goal or [],
        interfaces=args.interface or [],
        mapping=args.mapping or [],
        pre_research=args.pre_research or [],
        actor_role=_effective_role(args)[0],
    )
    print(f"设计包: {data['id']} ({data['status']})")
    print(f"path: {data['_path']}")
    return 0


def _cmd_design_accept(args: argparse.Namespace) -> int:
    data = design.accept_design(
        args.project_dir,
        args.dp_id,
        verdict=args.verdict,
        note=args.note,
        actor_role=_effective_role(args)[0],
    )
    print(f"{data['id']} -> {data['status']} (verdict={args.verdict})")
    return 0


def _cmd_design_list(args: argparse.Namespace) -> int:
    role, delivery = _work_actor(args)
    items = design.list_designs(
        args.project_dir, status=args.status, actor_role=role, actor_delivery=delivery
    )
    if args.json:
        _print_json(items)
        return 0
    if not items:
        print("没有设计包")
        return 0
    for item in items:
        print(f"{item.get('id')} {item.get('status')} {item.get('title')}")
    return 0


def _cmd_design_show(args: argparse.Namespace) -> int:
    role, delivery = _work_actor(args)
    path, meta = design.find_design(
        args.project_dir, args.dp_id, actor_role=role, actor_delivery=delivery
    )
    if args.json:
        meta.pop("_body", None)
        _print_json(meta)
    else:
        print(path.read_text(encoding="utf-8"))
    return 0


def _cmd_skill_list(args: argparse.Namespace) -> int:
    items = skills.discover_skills(args.project_dir)
    if args.role:
        items = [item for item in items if args.role in item["roles"]]
    if args.json:
        _print_json(
            [
                {
                    "name": item["name"],
                    "roles": item["roles"],
                    "trigger": item["trigger"],
                    "path": str(item["path"]),
                }
                for item in items
            ]
        )
        return 0
    if not items:
        print("没有技能")
        return 0
    for item in items:
        print(
            "{name} [{roles}] {trigger}".format(
                name=item["name"],
                roles=", ".join(item["roles"]),
                trigger=item["trigger"] or "-",
            )
        )
    return 0


def _cmd_skill_show(args: argparse.Namespace) -> int:
    data = skills.show_skill(args.project_dir, args.name)
    if args.json:
        _print_json(data)
    else:
        print(data["body"])
    return 0


def _cmd_skill_validate(args: argparse.Namespace) -> int:
    results = skills.validate_skills(args.project_dir)
    errors = [item for item in results if item["errors"]]
    if args.json:
        _print_json({"ok": not errors, "results": results})
    else:
        for item in results:
            if item["errors"]:
                print(f"FAIL {item['name']}: " + "；".join(item["errors"]))
            else:
                print(f"OK {item['name']}")
    return 0 if not errors else 1


def _cmd_docs_check(args: argparse.Namespace) -> int:
    contract = resolve_contract(args.project_dir)
    issues = docmodel.check(contract, roadmap=args.roadmap)
    if args.json:
        _print_json({"ok": not issues, "issues": issues})
    else:
        if issues:
            print("文档模型检查: FAIL")
            for issue in issues:
                print(f"  - {issue}")
        else:
            print("文档模型检查: OK")
    return 0 if not issues else 1


def _cmd_docs_summary(args: argparse.Namespace) -> int:
    contract = resolve_contract(args.project_dir)
    data = docmodel.summary(contract)
    if args.json:
        _print_json(data)
    else:
        print(f"当前路标: {data['current_roadmap']}")
        print(f"继承文档文件: {data['inherit_files']}")
        print(f"过程文档文件: {data['process_files']}")
        print(f"SPEC: {len(data['specs'])}")
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
    install_designer_p = install_sub.add_parser("designer", help="安装 contract designer")
    install_designer_p.add_argument("--project-dir", default=".")
    install_designer_p.add_argument("--workspace-root")
    install_designer_p.add_argument("--force", action="store_true")
    install_designer_p.set_defaults(func=_cmd_install_designer)

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
    ws_init.add_argument("--roadmap", default="R1", help="初始路标 ID（如 R0/R1）")
    ws_init.add_argument("--phase", choices=["P1", "P2", "P3", "P4", "P5"], default="P1")
    ws_init.add_argument("--version", default="1.0.0-alpha.1", help="当前版本（x.y.z[-pre]）")
    ws_init.add_argument("--roadmap-title", help="路标标题（默认按 roadmap 推导）")
    ws_init.add_argument("--force", action="store_true")
    ws_init.set_defaults(func=_cmd_workspace_init)
    ws_attach = workspace_sub.add_parser("attach", help="接入已有 contract 仓，不覆盖既有内容")
    ws_attach.add_argument("--project-dir", default=".")
    ws_attach.add_argument("--name", required=True)
    ws_attach.add_argument("--contract-dir", required=True)
    ws_attach.add_argument("--contract-remote")
    ws_attach.add_argument("--link-mode", choices=["auto", "symlink", "copy"], default="auto")
    ws_attach.set_defaults(func=_cmd_workspace_attach)
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
    task_create.add_argument(
        "--owner-role",
        choices=["manager", "designer", "worker", "maintainer"],
        help="责任主体；design 默认 designer，其他默认 worker",
    )
    task_create.add_argument(
        "--executor-role",
        choices=["manager", "designer", "worker", "maintainer"],
        help="执行者；默认同 owner_role",
    )
    task_create.add_argument(
        "--owner-confirmed-by",
        help="非默认责任主体的 manager 显式确认人/记录（写 ledger）",
    )
    task_create.add_argument("--delivery")
    task_create.add_argument(
        "--scope-mode",
        choices=["single_subproject", "cross_subproject", "workspace"],
        help="子项目作用域；cross/workspace 仅 manager",
    )
    task_create.add_argument(
        "--scope-project", action="append", help="cross/workspace 涉及子项目 id（可重复）"
    )
    task_create.add_argument(
        "--scope-operation",
        action="append",
        help="cross/workspace 操作：read|test|release|sync|doctor（可重复）",
    )
    task_create.add_argument(
        "--scope-justification", help="cross/workspace 作用域理由（必填）"
    )
    task_create.add_argument(
        "--security",
        help="安全字段 YAML/JSON 文件路径或内联内容；命中 guard/权限/白名单/"
        "路径策略/hook/发布门禁的任务必须声明 security.applies: true 并填写完整",
    )
    task_create.add_argument("--risk", choices=["low", "medium", "high", "critical"], default="medium")
    task_create.add_argument("--effort", default="M")
    task_create.add_argument(
        "--estimate",
        help="VU/工作量估计 YAML/JSON，如 '{vu: 2, effort_hours: 3, confidence: medium}'",
    )
    task_create.add_argument("--slice", help="纵向切片/Story（SPEC-R1-VERSION V7）")
    task_create.add_argument(
        "--verify", help="可复核验收命令（如 pytest tests/x.py::test_y）"
    )
    task_create.add_argument("--review-mode", choices=["manager", "independent", "user"])
    task_create.add_argument("--reviews", help="review 任务对应的实现/设计任务 ID")
    task_create.add_argument("--review-scope", action="append")
    task_create.add_argument("--allowed-path", action="append")
    task_create.add_argument("--acceptance", action="append")
    task_create.add_argument("--wave", default="W1")
    task_create.add_argument("--depends-on", action="append")
    task_create.add_argument("--fixes", action="append", help="关联 BUG id")
    task_create.add_argument("--module", help="主责模块（与规格-模块矩阵一致）")
    task_create.add_argument("--spec-id", action="append", help="关联 SPEC id")
    task_create.add_argument("--evidence", action="append", help="证据路径（机器字段）")
    task_create.add_argument("--no-review", action="store_true", help="不自动创建 review 任务")
    task_create.set_defaults(func=_cmd_task_create)

    task_list = task_sub.add_parser("list")
    task_list.add_argument("--project-dir", default=".")
    task_list.add_argument("--status")
    task_list.add_argument(
        "--all", action="store_true", help="包含 accepted/cancelled 等非活跃任务（默认只列活跃）"
    )
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

    task_validate = task_sub.add_parser(
        "validate", help="校验任务卡作用域/责任映射/安全字段（T033 A2/A3）"
    )
    task_validate.add_argument("task_id")
    task_validate.add_argument("--project-dir", default=".")
    task_validate.add_argument("--json", action="store_true")
    task_validate.set_defaults(func=_cmd_task_validate)

    task_start = task_sub.add_parser("start")
    task_start.add_argument("task_id")
    task_start.add_argument("--project-dir", default=".")
    task_start.add_argument("--owner", help="worker 身份；也可设置 MF_WORKER_ID")
    task_start.set_defaults(func=_cmd_task_start)

    task_rework = task_sub.add_parser(
        "rework", help="开始 review NEEDS_REWORK 的返工（记录 review/整改项/lease）"
    )
    task_rework.add_argument("task_id")
    task_rework.add_argument("--project-dir", default=".")
    task_rework.add_argument("--owner", help="worker 身份；也可设置 MF_WORKER_ID")
    task_rework.add_argument("--note", help="返工说明")
    task_rework.set_defaults(func=_cmd_task_rework)

    task_withdraw = task_sub.add_parser(
        "withdraw",
        help="提交后自撤回（下游未处理；submitted→in_progress，review 取消/挂起）",
    )
    task_withdraw.add_argument("task_id")
    task_withdraw.add_argument("--project-dir", default=".")
    task_withdraw.add_argument("--reason", required=True)
    task_withdraw.add_argument("--owner", help="提交者身份；也可设置 MF_WORKER_ID")
    task_withdraw.set_defaults(func=_cmd_task_withdraw)

    task_review = task_sub.add_parser("review", help="评审编排（自动 review dispatch）")
    task_review_sub = task_review.add_subparsers(dest="action", required=True)
    task_review_dispatch = task_review_sub.add_parser(
        "dispatch", help="派发独立 reviewer（spawn-requested/fallback，不伪装已执行）"
    )
    task_review_dispatch.add_argument("task_id")
    task_review_dispatch.add_argument("--project-dir", default=".")
    task_review_dispatch.add_argument(
        "--host", choices=["claude-code", "manual"], default="claude-code"
    )
    task_review_dispatch.add_argument("--owner", help="reviewer 身份（新 session/不同 owner）")
    task_review_dispatch.add_argument("--session-id", help="reviewer 新会话 id")
    task_review_dispatch.add_argument("--reason", help="派发/回退原因")
    task_review_dispatch.add_argument(
        "--fallback", action="store_true", help="宿主不可用：回退手动评审"
    )
    task_review_dispatch.set_defaults(func=_cmd_task_review_dispatch)

    task_submit = task_sub.add_parser("submit")
    task_submit.add_argument("task_id")
    task_submit.add_argument("--project-dir", default=".")
    task_submit.add_argument("--handoff")
    task_submit.add_argument("--dev-record")
    task_submit.add_argument("--owner", help="worker 身份；也可设置 MF_WORKER_ID")
    task_submit.add_argument(
        "--blocked", action="store_true", help="BLOCKED 提交：转 manager 裁决，不推进评审"
    )
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
    task_accept.add_argument(
        "--legacy-rework",
        action="store_true",
        help="旧行为：高风险/新验收保留 manager 裁决（一版回滚开关）",
    )
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
    req_trace.add_argument(
        "--check",
        action="store_true",
        help="孤儿/未闭环检查（REQ/SPEC/TASK/证据/VR/BUG/MFP/CHG）；有孤儿返回非零",
    )
    req_trace.add_argument(
        "--archive",
        action="store_true",
        help="同时扫描 archive（默认只追踪当前路标，避免旧任务/重复 BUG）",
    )
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
    roadmap_sizing = roadmap_sub.add_parser(
        "sizing", help="汇总 VU/effort/风险并给出 large/small/split 建议（不自动分类）"
    )
    roadmap_sizing.add_argument("roadmap_id")
    roadmap_sizing.add_argument("--project-dir", default=".")
    roadmap_sizing.add_argument("--json", action="store_true")
    roadmap_sizing.set_defaults(func=_cmd_roadmap_sizing)
    roadmap_classify = roadmap_sub.add_parser(
        "classify", help="用户 TTY 显式决定版本 flow_profile（写 VERSION/SIZING/ledger）"
    )
    roadmap_classify.add_argument("roadmap_id")
    roadmap_classify.add_argument("--project-dir", default=".")
    roadmap_classify.add_argument("--flow", choices=list(roadmap.FLOW_PROFILES), required=True)
    roadmap_classify.add_argument("--decided-by", default="user")
    roadmap_classify.add_argument("--reason", required=True)
    roadmap_classify.add_argument("--json", action="store_true")
    roadmap_classify.set_defaults(func=_cmd_roadmap_classify)

    phase_p = sub.add_parser("phase", help="五阶段进入/评审/退出（按 flow_profile 显示）")
    phase_sub = phase_p.add_subparsers(dest="action", required=True)
    phase_show = phase_sub.add_parser("show", help="显示 required/merged_into/skipped 与状态")
    phase_show.add_argument("--project-dir", default=".")
    phase_show.add_argument("--json", action="store_true")
    phase_show.set_defaults(func=_cmd_phase_show)
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
    bug_add.add_argument(
        "--flow", choices=list(bug.FLOWS), default="external",
        help="external（试运行/用户可见）/ verification（同子项目实施期）",
    )
    bug_add.add_argument("--scope", choices=list(bug.SCOPES), default="same_subproject")
    bug_add.add_argument("--subproject", help="verification flow 的同子项目")
    bug_add.add_argument("--found-by")
    bug_add.set_defaults(func=_cmd_bug_add)
    bug_list = bug_sub.add_parser("list")
    bug_list.add_argument("--project-dir", default=".")
    bug_list.add_argument("--status")
    bug_list.add_argument("--severity")
    bug_list.add_argument("--roadmap")
    bug_list.add_argument("--flow", choices=list(bug.FLOWS))
    bug_list.add_argument("--subproject")
    bug_list.add_argument("--all", action="store_true", help="不按当前路标过滤")
    bug_list.add_argument(
        "--history", action="store_true", help="包含 closed/deferred/wontfix 等历史缺陷"
    )
    bug_list.add_argument(
        "--include-closed", action="store_true", help="查询 closed BUG（需用户授权 + reason）"
    )
    bug_list.add_argument("--authorized-by", help="closed 查询的用户授权人")
    bug_list.add_argument("--reason", help="closed 查询理由（写 READ-LOG）")
    bug_list.add_argument("--json", action="store_true")
    bug_list.set_defaults(func=_cmd_bug_list)
    bug_show = bug_sub.add_parser("show")
    bug_show.add_argument("bug_id")
    bug_show.add_argument("--project-dir", default=".")
    bug_show.add_argument("--json", action="store_true")
    bug_show.add_argument(
        "--packet", action="store_true", help="最小修复上下文包（复现/期望/关联/范围/回归）"
    )
    bug_show.set_defaults(func=_cmd_bug_show)
    bug_update = bug_sub.add_parser("update")
    bug_update.add_argument("bug_id")
    bug_update.add_argument("--project-dir", default=".")
    bug_update.add_argument("--status", choices=list(bug.STATUSES))
    bug_update.add_argument("--severity", choices=list(bug.SEVERITIES))
    bug_update.add_argument("--fix-task")
    bug_update.add_argument("--fix-owner")
    bug_update.add_argument("--root-cause")
    bug_update.add_argument("--resolution")
    bug_update.set_defaults(func=_cmd_bug_update)
    bug_fix = bug_sub.add_parser("fix", help="进入修复/标记 fixed（verification flow 供 worker）")
    bug_fix.add_argument("bug_id")
    bug_fix.add_argument("--project-dir", default=".")
    bug_fix.add_argument("--task")
    bug_fix.add_argument("--by", help="修复者身份（默认 worker 子项目）")
    bug_fix.add_argument("--fixed", action="store_true", help="直接标记 fixed")
    bug_fix.set_defaults(func=_cmd_bug_fix)
    bug_verify = bug_sub.add_parser("verify", help="独立验证（external→pending_user_close；verification→verified）")
    bug_verify.add_argument("bug_id")
    bug_verify.add_argument("--project-dir", default=".")
    bug_verify.add_argument("--by", help="验证者/viewer（verification flow 必填且非修复者）")
    bug_verify.add_argument("--subproject")
    bug_verify.add_argument("--evidence", action="append")
    bug_verify.set_defaults(func=_cmd_bug_verify)
    bug_escalate = bug_sub.add_parser("escalate", help="verification → external（跨项目/接口/外部可见/安全/需求级）")
    bug_escalate.add_argument("bug_id")
    bug_escalate.add_argument("--project-dir", default=".")
    bug_escalate.add_argument("--reason", required=True)
    bug_escalate.add_argument("--by")
    bug_escalate.set_defaults(func=_cmd_bug_escalate)
    bug_close = bug_sub.add_parser("close")
    bug_close.add_argument("bug_id")
    bug_close.add_argument("--project-dir", default=".")
    bug_close.add_argument("--verification", required=True)
    bug_close.add_argument("--resolution")
    bug_close.add_argument("--confirmed-by", help="external：用户确认人（必填）")
    bug_close.add_argument("--note", help="external：用户确认意见（必填）")
    bug_close.add_argument("--by", help="verification：同子项目非修复者 viewer")
    bug_close.add_argument("--subproject")
    bug_close.add_argument("--evidence", action="append")
    bug_close.set_defaults(func=_cmd_bug_close)
    bug_audit = bug_sub.add_parser("audit", help="状态一致性审计（直接改状态/绕过 CLI 的痕迹）")
    bug_audit.add_argument("--project-dir", default=".")
    bug_audit.add_argument("--json", action="store_true")
    bug_audit.set_defaults(func=_cmd_bug_audit)

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
    verify_record.add_argument("--command", help="可复现验证命令（E1）")
    verify_record.add_argument("--environment", help="环境摘要 YAML/JSON，如 '{python: 3.12}'")
    verify_record.add_argument("--result-digest", help="结果摘要 digest（sha256:...）")
    verify_record.add_argument("--artifact", action="append", help="证据工件路径（可重复）")
    verify_record.add_argument("--reuse-of", help="复用既有 VR（fingerprint/命令一致）")
    verify_record.add_argument("--risk", choices=["low", "medium", "high", "critical"])
    verify_record.add_argument("--retention", choices=["permanent", "12m", "3y"])
    verify_record.set_defaults(func=_cmd_verify_record)
    verify_index = verify_sub.add_parser(
        "index", help="生成证据索引 E1/E2 与 evidence debt"
    )
    verify_index.add_argument("--project-dir", default=".")
    verify_index.add_argument("--json", action="store_true")
    verify_index.set_defaults(func=_cmd_verify_index)
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
    verify_card = verify_sub.add_parser("security-card", help="校验安全卡（MFP-0041 A1）")
    verify_card.add_argument("--path", required=True)
    verify_card.add_argument("--json", action="store_true")
    verify_card.set_defaults(func=_cmd_verify_security_card)

    release_p = sub.add_parser("release", help="版本冻结（不等于发布）")
    release_sub = release_p.add_subparsers(dest="action", required=True)
    release_freeze = release_sub.add_parser(
        "freeze",
        help=(
            "按阶段策略冻结：P1/P2 禁止；P3 active 仅预发布；P3 结束后允许；"
            "P4/P5 修复/补丁随时允许"
        ),
    )
    release_freeze.add_argument("--project-dir", default=".")
    release_freeze.add_argument("--version")
    release_freeze.add_argument("--note")
    release_freeze.add_argument(
        "--source-dir",
        help="交付源码目录（版本一致性校验；默认探测当前目录与契约同级交付库）",
    )
    release_freeze.add_argument("--force", action="store_true")
    release_freeze.add_argument("--reason", help="--force 的可审计原因")
    release_freeze.add_argument("--approved-by", dest="approved_by", help="--force 的批准人/记录")
    release_freeze.set_defaults(func=_cmd_release_freeze)
    release_check_p = release_sub.add_parser(
        "check", help="发布一致性校验（pyproject/源码版本/RELEASE-NOTES/清单/tag）"
    )
    release_check_p.add_argument("--project-dir", default=".")
    release_check_p.add_argument("--version")
    release_check_p.add_argument(
        "--source-dir",
        help="交付源码目录（默认探测当前目录与契约同级交付库）",
    )
    release_check_p.add_argument(
        "--require-tag", action="store_true", help="要求 git tag v<version> 存在"
    )
    release_check_p.add_argument("--json", action="store_true")
    release_check_p.set_defaults(func=_cmd_release_check)
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
    context_expand.add_argument(
        "--start", type=int, default=None, help="分段读取起始字节偏移（0 基）"
    )
    context_expand.add_argument(
        "--end", type=int, default=None, help="分段读取结束字节偏移（不含）"
    )
    context_expand.add_argument(
        "--max-bytes", type=int, default=None, help="单段最大字节数；超过拒绝"
    )
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

    archive_p = sub.add_parser("archive", help="归档查询（默认 deny，需用户 grant）")
    archive_sub = archive_p.add_subparsers(dest="action", required=True)
    archive_list = archive_sub.add_parser("list")
    archive_list.add_argument("--project-dir", default=".")
    archive_list.add_argument("--actor", help="默认从当前目录/MF_ROLE 推导")
    archive_list.add_argument("--json", action="store_true")
    archive_list.set_defaults(func=_cmd_archive_list)
    archive_show = archive_sub.add_parser("show")
    archive_show.add_argument("roadmap_id")
    archive_show.add_argument("--project-dir", default=".")
    archive_show.add_argument("--reason", choices=list(context.REASONS), required=True)
    archive_show.add_argument("--actor", help="默认从当前目录/MF_ROLE 推导")
    archive_show.add_argument("--grant", help="用户授权 grant id（默认 deny）")
    archive_show.add_argument("--path", help="仅读取 scope 内指定文件")
    archive_show.add_argument("--json", action="store_true")
    archive_show.set_defaults(func=_cmd_archive_show)
    archive_authorize = archive_sub.add_parser(
        "authorize", help="用户 TTY 显式授权 manager/designer 读取归档"
    )
    archive_authorize.add_argument("--project-dir", default=".")
    archive_authorize.add_argument("--role", choices=list(context.ARCHIVE_GRANT_ROLES), required=True)
    archive_authorize.add_argument("--roadmap", required=True)
    archive_authorize.add_argument(
        "--scope", action="append", required=True, help="相对 archive/R{n}/ 的路径或 glob；可重复"
    )
    archive_authorize.add_argument("--purpose", choices=list(context.ARCHIVE_PURPOSES), required=True)
    archive_authorize.add_argument("--ttl-minutes", type=int, default=30)
    archive_authorize.add_argument("--max-bytes", type=int, default=262144)
    archive_authorize.add_argument("--max-files", type=int, default=50)
    archive_authorize.add_argument(
        "--multi-use", action="store_true", help="默认 one-shot；--multi-use 允许多次读取"
    )
    archive_authorize.add_argument("--json", action="store_true")
    archive_authorize.set_defaults(func=_cmd_archive_authorize)
    archive_revoke = archive_sub.add_parser("revoke", help="用户 TTY 撤销 grant")
    archive_revoke.add_argument("grant_id")
    archive_revoke.add_argument("--project-dir", default=".")
    archive_revoke.add_argument("--json", action="store_true")
    archive_revoke.set_defaults(func=_cmd_archive_revoke)
    archive_export = archive_sub.add_parser("export", help="按 grant 导出归档副本到 inputs/")
    archive_export.add_argument("--project-dir", default=".")
    archive_export.add_argument("--grant", help="用户授权 grant id（manager/designer 必填）")
    archive_export.add_argument(
        "--roadmap", help="maintainer root 无 grant 导出时指明来源（如 R0）"
    )
    archive_export.add_argument("--to", required=True, help="contract 内 inputs/ 目录")
    archive_export.add_argument("--actor", help="默认从当前目录/MF_ROLE 推导")
    archive_export.add_argument("--json", action="store_true")
    archive_export.set_defaults(func=_cmd_archive_export)

    log_p = sub.add_parser("log", help="查看 ledger 审计日志")
    log_p.add_argument("--project-dir", default=".")
    log_p.add_argument("--limit", type=int, default=50)
    log_p.add_argument("--json", action="store_true")
    log_p.set_defaults(func=_cmd_log)

    state_p = sub.add_parser("state", help="派生状态对账与重建（TASK.yaml+ledger 为真相）")
    state_sub = state_p.add_subparsers(dest="action", required=True)
    state_show = state_sub.add_parser("show", help="列出 state 与任务卡/ledger 的差异")
    state_show.add_argument("--project-dir", default=".")
    state_show.add_argument("--json", action="store_true")
    state_show.set_defaults(func=_cmd_state_show)
    state_rebuild = state_sub.add_parser("rebuild", help="从 TASK.yaml/ledger 重建 state 快照")
    state_rebuild.add_argument("--project-dir", default=".")
    state_rebuild.set_defaults(func=_cmd_state_rebuild)

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
    improve_list.add_argument(
        "--all", action="store_true", help="包含 closed/verified 等非活跃 MFP（默认只列活跃）"
    )
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

    improve_triage = improve_sub.add_parser("triage", help="manager 评估 MFP（接收/拒绝/延期）")
    improve_triage.add_argument("mfp_id")
    improve_triage.add_argument("--project-dir", default=".")
    improve_triage.add_argument(
        "--decision", choices=list(improve.TRIAGE_DECISIONS), required=True
    )
    improve_triage.add_argument("--reason")
    improve_triage.add_argument("--next-step", choices=["design", "direct"])
    improve_triage.add_argument("--target")
    improve_triage.set_defaults(func=_cmd_improve_triage)

    improve_sync = improve_sub.add_parser("sync", help="把归档 resolution 同步到生产项目 state.json")
    improve_sync.add_argument("--project-dir", default=".")
    improve_sync.add_argument("--from", dest="from_path", help="归档 index.json 路径")
    improve_sync.add_argument("--source", help="meta-flow 源码目录（默认全局 manifest.source_dir）")
    improve_sync.add_argument("--json", action="store_true")
    improve_sync.set_defaults(func=_cmd_improve_sync)

    improve_state = improve_sub.add_parser("state", help="查看生产项目 MFP 同步状态")
    improve_state.add_argument("--project-dir", default=".")
    improve_state.add_argument("--json", action="store_true")
    improve_state.set_defaults(func=_cmd_improve_state)

    work_p = sub.add_parser("work", help="工作包/任务区间/决策点/验证流（REQ-0019）")
    work_sub = work_p.add_subparsers(dest="action", required=True)
    work_create = work_sub.add_parser("create", help="manager 每子项目每设计周期创建工作包")
    work_create.add_argument("--project-dir", default=".")
    work_create.add_argument("--subproject", required=True)
    work_create.add_argument("--title")
    work_create.add_argument("--design-package")
    work_create.add_argument("--requirement", action="append")
    work_create.add_argument("--mfp", action="append")
    work_create.add_argument("--spec", action="append")
    work_create.add_argument("--design-ref", action="append")
    work_create.add_argument("--interface-ref", action="append")
    work_create.add_argument("--must-read", action="append")
    work_create.add_argument("--allowed-path", action="append")
    work_create.add_argument("--budget", help='YAML/JSON: {"files": 60, "bytes": 1048576}')
    work_create.add_argument("--acceptance", action="append")
    work_create.add_argument("--phase", default="P3")
    work_create.set_defaults(func=_cmd_work_create)

    work_task = work_sub.add_parser("task", help="添加工作包任务（仅在需要决策/独立验证时拆分）")
    work_task.add_argument("wp_id")
    work_task.add_argument("--project-dir", default=".")
    work_task.add_argument("--type", choices=list(work.TASK_TYPES), required=True)
    work_task.add_argument("--goal", required=True)
    work_task.add_argument("--acceptance", action="append")
    work_task.add_argument("--verification", choices=list(work.VERIFICATION_MODES), default="none")
    work_task.add_argument("--context", action="append")
    work_task.add_argument("--verifies", action="append")
    work_task.add_argument("--problem")
    work_task.add_argument("--impact")
    work_task.add_argument("--option", action="append")
    work_task.add_argument("--recommendation")
    work_task.add_argument("--level", choices=list(work.DECISION_LEVELS))
    work_task.add_argument("--decision-owner", choices=list(work.DECISION_OWNERS), default="manager")
    work_task.set_defaults(func=_cmd_work_add_task)

    work_start = work_sub.add_parser("start")
    work_start.add_argument("wp_id")
    work_start.add_argument("--project-dir", default=".")
    work_start.set_defaults(func=_cmd_work_start)

    work_decision = work_sub.add_parser("decision", help="提交/记录决策点（阻塞工作包）")
    work_decision.add_argument("wp_id")
    work_decision.add_argument("--project-dir", default=".")
    work_decision.add_argument("--decision-id", help="记录已有决策点结果")
    work_decision.add_argument("--decision")
    work_decision.add_argument("--decided-by")
    work_decision.add_argument("--confirmed-by", help="D0/D1 用户确认人（manager 记录）")
    work_decision.add_argument("--note", help="D0/D1 用户确认意见")
    work_decision.add_argument("--problem")
    work_decision.add_argument("--impact")
    work_decision.add_argument("--option", action="append")
    work_decision.add_argument("--recommendation")
    work_decision.add_argument("--level", choices=list(work.DECISION_LEVELS), default="D2")
    work_decision.add_argument("--decision-owner", choices=list(work.DECISION_OWNERS), default="manager")
    work_decision.set_defaults(func=_cmd_work_decision)

    work_verify = work_sub.add_parser("verify", help="子项目最终验证（start/record）")
    work_verify.add_argument("wp_id")
    work_verify.add_argument("--project-dir", default=".")
    work_verify.add_argument("--result", choices=["PASS", "PASS_WITH_RISK", "NEEDS_REWORK", "BLOCKED"])
    work_verify.add_argument("--evidence", action="append")
    work_verify.add_argument("--notes")
    work_verify.add_argument("--verifier")
    work_verify.set_defaults(func=_cmd_work_verify)

    work_accept = work_sub.add_parser("accept", help="manager 验收工作包")
    work_accept.add_argument("wp_id")
    work_accept.add_argument("--project-dir", default=".")
    work_accept.add_argument(
        "--verdict", choices=["PASS", "PASS_WITH_RISK", "NEEDS_REWORK", "BLOCKED"], default="PASS"
    )
    work_accept.add_argument("--note")
    work_accept.set_defaults(func=_cmd_work_accept)

    work_list = work_sub.add_parser("list")
    work_list.add_argument("--project-dir", default=".")
    work_list.add_argument("--subproject")
    work_list.add_argument("--status", choices=list(work.WORK_STATUSES))
    work_list.add_argument("--json", action="store_true")
    work_list.set_defaults(func=_cmd_work_list)

    work_show = work_sub.add_parser("show")
    work_show.add_argument("wp_id")
    work_show.add_argument("--project-dir", default=".")
    work_show.add_argument("--json", action="store_true")
    work_show.set_defaults(func=_cmd_work_show)

    design_p = sub.add_parser("design", help="设计包 DP（designer 产出/manager 验收）")
    design_sub = design_p.add_subparsers(dest="action", required=True)
    design_create = design_sub.add_parser("create")
    design_create.add_argument("--project-dir", default=".")
    design_create.add_argument("--title", required=True)
    design_create.add_argument("--requirement", action="append")
    design_create.add_argument("--mfp", action="append")
    design_create.add_argument("--spec", action="append")
    design_create.add_argument("--subproject", action="append")
    design_create.add_argument("--scope")
    design_create.add_argument("--non-goal", action="append")
    design_create.add_argument("--interface", action="append")
    design_create.add_argument("--mapping", action="append")
    design_create.add_argument("--pre-research", action="append")
    design_create.set_defaults(func=_cmd_design_create)
    design_accept = design_sub.add_parser("accept")
    design_accept.add_argument("dp_id")
    design_accept.add_argument("--project-dir", default=".")
    design_accept.add_argument(
        "--verdict", choices=list(design.DESIGN_VERDICTS), required=True
    )
    design_accept.add_argument("--note")
    design_accept.set_defaults(func=_cmd_design_accept)
    design_list = design_sub.add_parser("list")
    design_list.add_argument("--project-dir", default=".")
    design_list.add_argument("--status", choices=list(design.DESIGN_STATUSES))
    design_list.add_argument("--json", action="store_true")
    design_list.set_defaults(func=_cmd_design_list)
    design_show = design_sub.add_parser("show")
    design_show.add_argument("dp_id")
    design_show.add_argument("--project-dir", default=".")
    design_show.add_argument("--json", action="store_true")
    design_show.set_defaults(func=_cmd_design_show)

    skill_p = sub.add_parser("skill", help="角色技能索引（提示词只定义身份/权限）")
    skill_sub = skill_p.add_subparsers(dest="action", required=True)
    skill_list = skill_sub.add_parser("list")
    skill_list.add_argument("--project-dir", default=".")
    skill_list.add_argument("--role")
    skill_list.add_argument("--json", action="store_true")
    skill_list.set_defaults(func=_cmd_skill_list)
    skill_show = skill_sub.add_parser("show")
    skill_show.add_argument("name")
    skill_show.add_argument("--project-dir", default=".")
    skill_show.add_argument("--json", action="store_true")
    skill_show.set_defaults(func=_cmd_skill_show)
    skill_validate = skill_sub.add_parser("validate")
    skill_validate.add_argument("--project-dir", default=".")
    skill_validate.add_argument("--json", action="store_true")
    skill_validate.set_defaults(func=_cmd_skill_validate)

    docs_p = sub.add_parser("docs", help="文档模型与版本隔离检查（REQ-0020）")
    docs_sub = docs_p.add_subparsers(dest="action", required=True)
    docs_check = docs_sub.add_parser("check")
    docs_check.add_argument("--project-dir", default=".")
    docs_check.add_argument("--roadmap")
    docs_check.add_argument("--json", action="store_true")
    docs_check.set_defaults(func=_cmd_docs_check)
    docs_summary = docs_sub.add_parser("summary")
    docs_summary.add_argument("--project-dir", default=".")
    docs_summary.add_argument("--json", action="store_true")
    docs_summary.set_defaults(func=_cmd_docs_summary)

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

    di_archive = dev_improve_sub.add_parser(
        "archive", help="meta-flow maintainer 唯一归档者（inbox → improvements/archive/）"
    )
    di_archive.add_argument("ref", help="<project>/<MFP> 或唯一的 MFP id")
    di_archive.add_argument("--source")
    di_archive.set_defaults(func=_cmd_dev_improve_archive)

    di_index = dev_improve_sub.add_parser("index", help="查看归档索引 improvements/archive/index.json")
    di_index.add_argument("--source")
    di_index.add_argument("--json", action="store_true")
    di_index.set_defaults(func=_cmd_dev_improve_index)

    upgrade_p = sub.add_parser("upgrade", help="按全局模板更新项目安装")
    upgrade_p.add_argument("--project-dir", default=".")
    upgrade_p.add_argument("--force", action="store_true")
    upgrade_p.set_defaults(func=_cmd_upgrade)

    role_p = sub.add_parser("role", help="显示/切换角色（切换仅限用户终端）")
    role_p.add_argument("--path", default=".")
    role_p.add_argument("--json", action="store_true")
    role_p.add_argument(
        "--as",
        dest="as_role",
        help="切换角色：manager|designer|worker|maintainer 或短名 mgr/dsg/wkr/mnt",
    )
    role_p.add_argument(
        "--reset",
        action="store_true",
        help="清理 user-tty/当前会话/遗留锚点（不写新锚点，仅 maintainer）",
    )
    role_p.add_argument("--reason", help="切换原因（写入 ledger role.switch）")
    role_p.set_defaults(func=_cmd_role)

    maintainer_p = sub.add_parser(
        "maintainer", help="maintainer root 运维（外部动作授权等）"
    )
    maintainer_sub = maintainer_p.add_subparsers(dest="action", required=True)
    maintainer_auth = maintainer_sub.add_parser(
        "authorize-external",
        help="用户 TTY 短时授权 maintainer 执行外部/不可逆动作",
    )
    maintainer_auth.add_argument(
        "--action",
        dest="action_name",
        required=True,
        help="动作，如 'git push' / network / install / deploy",
    )
    maintainer_auth.add_argument("--reason", required=True)
    maintainer_auth.add_argument("--ttl-minutes", type=int, default=10)
    maintainer_auth.add_argument("--path", default=".")
    maintainer_auth.add_argument("--json", action="store_true")
    maintainer_auth.set_defaults(func=_cmd_maintainer_authorize_external)

    status_p = sub.add_parser("status", help="显示工作区或安装状态")
    status_p.add_argument("--path", default=".")
    status_p.add_argument("--json", action="store_true")
    status_p.set_defaults(func=_cmd_status)

    doctor_p = sub.add_parser("doctor", help="校验全局/项目/工作区/文档/过程记录")
    doctor_p.add_argument("--path", default=".")
    doctor_p.add_argument("--global", dest="global_scope", action="store_true")
    doctor_p.add_argument(
        "scope",
        nargs="?",
        choices=["docs", "process"],
        help="docs: 双标准/front matter/入口行数；process: handoff/review rounds/篇幅",
    )
    doctor_p.add_argument("--json", action="store_true")
    doctor_p.set_defaults(func=_cmd_doctor)

    hook_p = sub.add_parser("hook", help="Claude Code hook 入口")
    hook_sub = hook_p.add_subparsers(dest="action", required=True)
    hook_pretool = hook_sub.add_parser("pretool", help="PreToolUse 角色/路径守卫")
    hook_pretool.set_defaults(func=_cmd_hook_pretool)
    hook_session = hook_sub.add_parser(
        "session-start", help="SessionStart 写角色锚点（/clear 后重写）"
    )
    hook_session.set_defaults(func=_cmd_hook_session_start)

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
        design.DesignError,
        docmodel.DocModelError,
        knowledge.KnowledgeError,
        skills.SkillError,
        verify.VerifyError,
        context.ContextError,
        state.StateError,
        roles.RoleError,
        work.WorkError,
    ) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return getattr(exc, "code", 1)


if __name__ == "__main__":
    raise SystemExit(main())
