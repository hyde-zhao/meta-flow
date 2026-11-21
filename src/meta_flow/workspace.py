"""工作区初始化、角色路由、状态汇总与 doctor 校验。"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

from . import templates

_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_ROADMAP_RE = re.compile(r"^R(\d+)$")


class WorkspaceError(Exception):
    """工作区操作失败。"""

    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


def _as_dir(path: Path) -> Path:
    """文件路径取其父目录；目录路径原样返回。"""
    path = path.expanduser()
    if path.is_file():
        return path.parent
    return path


def _version_core(version: str) -> str:
    """去掉 SemVer 的预发布/构建元数据，只保留 X.Y.Z。"""
    return version.split("+", 1)[0].split("-", 1)[0]


def slugify(name: str) -> str:
    """把项目名转换为稳定的 project_id。"""
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "project"


def find_workspace_root(start: Path) -> Path | None:
    """从 start 向上查找包含 contracts/project.yaml 与 deliveries/ 的工作区。"""
    current = _as_dir(start).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "contracts" / "project.yaml").is_file() and (
            candidate / "deliveries"
        ).is_dir():
            return candidate
    return None


def detect_role(start: Path) -> tuple[str, Path | None]:
    """根据目录推导当前角色。

    返回 (role, workspace_root)。未绑定工作区时 role 为 unbound。
    """
    root = find_workspace_root(start)
    if root is None:
        return "unbound", None

    current = _as_dir(start).resolve()
    try:
        relative = current.relative_to(root)
    except ValueError:
        return "unbound", root

    parts = relative.parts
    if parts and parts[0] == "contracts":
        return "manager", root
    if parts and parts[0] == "deliveries":
        return "worker", root
    return "maintainer", root


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _dump_yaml(path: Path, data: dict[str, Any]) -> None:
    _write(
        path,
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False),
    )


def _git_init(path: Path) -> None:
    try:
        completed = subprocess.run(
            ["git", "init", "-b", "main", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise WorkspaceError("未找到 git 命令；可改用 --no-git") from exc
    if completed.returncode != 0:
        raise WorkspaceError(f"git init 失败: {completed.stderr.strip()}")


def _validate_delivery_ids(deliveries: list[str]) -> None:
    if not deliveries:
        raise WorkspaceError("至少需要一个交付库；使用 --delivery 指定")
    if len(set(deliveries)) != len(deliveries):
        raise WorkspaceError("交付库 id 不能重复")
    for delivery in deliveries:
        if not _ID_RE.fullmatch(delivery):
            raise WorkspaceError(f"交付库 id 必须是小写 kebab-case: {delivery}")


def init_workspace(
    target: Path,
    name: str,
    deliveries: list[str],
    *,
    git: bool = True,
) -> Path:
    """在 target 下创建 contracts/ 与 deliveries/ 两个仓库骨架。"""
    root = target.expanduser().resolve()
    if root.exists() and not root.is_dir():
        raise WorkspaceError(f"目标不是目录: {root}")
    if (root / "contracts").exists() or (root / "deliveries").exists():
        raise WorkspaceError(
            f"目标已包含 contracts/ 或 deliveries/，拒绝覆盖: {root}"
        )

    _validate_delivery_ids(deliveries)
    project_id = slugify(name)

    contracts = root / "contracts"
    deliveries_root = root / "deliveries"

    for directory in (
        contracts / "project",
        contracts / "roadmap",
        contracts / "requirements" / "changes",
        contracts / "standards",
        contracts / "bugs",
        contracts / "knowledge",
        contracts / "architecture" / "drafts",
        contracts / "specs",
        contracts / "tasks",
        contracts / "verification",
        contracts / "handoffs",
        contracts / "state",
        contracts / "archive",
        contracts / ".metaflow",
        deliveries_root / ".metaflow",
    ):
        directory.mkdir(parents=True, exist_ok=True)

    # 根目录：工作区清单与 maintainer 角色文件
    _dump_yaml(
        root / "mf.workspace.yaml",
        {
            "schema": 1,
            "workspace": name,
            "contracts_repo": "contracts",
            "deliveries_repo": "deliveries",
            "roles": {
                "root": "maintainer",
                "contracts": "manager",
                "deliveries": "worker",
            },
        },
    )
    _write(root / "CLAUDE.md", templates.ROOT_CLAUDE)
    _write(root / "AGENTS.md", templates.ROOT_AGENTS)

    # 契约库
    _write(contracts / "CLAUDE.md", templates.CONTRACTS_CLAUDE)
    _write(contracts / "AGENTS.md", templates.CONTRACTS_AGENTS)
    _write(
        contracts / ".metaflow" / "role.yaml",
        "role: manager\nworkspace_root: ..\n",
    )
    _write(contracts / ".gitignore", "state/current.json\n.metaflow/*.lock\n")
    _dump_yaml(
        contracts / "project.yaml",
        {
            "schema": 1,
            "project_id": project_id,
            "name": name,
            "roadmap": "R1",
            "phase": "P1",
            "version": "1.0.0-alpha.1",
            "version_policy": "same-major",
            "plan_ref": "project/PROJECT-PLAN.md",
            "deliveries": [
                {
                    "id": delivery,
                    "path": f"deliveries/{delivery}",
                    "responsibility": f"{delivery} 交付库",
                }
                for delivery in deliveries
            ],
        },
    )
    _dump_yaml(
        contracts / "roadmap" / "ROADMAP.yaml",
        {
            "schema": 1,
            "roadmaps": [
                {
                    "id": "R1",
                    "title": "v1 MVP",
                    "status": "active",
                    "version_range": "1.x",
                    "version_target": "1.0.0",
                    "goal": "完成第一个可交付版本",
                    "entry_criteria": ["需求基线确认"],
                    "exit_criteria": ["P5 发布通过"],
                    "non_goals": ["多交付库并行"],
                }
            ],
        },
    )
    _dump_yaml(
        contracts / "requirements" / "REQUIREMENTS.yaml",
        {"schema": 1, "requirements": []},
    )
    _write(contracts / "project" / "PROJECT-PLAN.md", templates.PROJECT_PLAN)
    _write(contracts / "state" / "ledger.ndjson", "")

    for standard_name, content in templates.STANDARDS.items():
        _write(contracts / "standards" / standard_name, content)

    _write(contracts / "bugs" / "README.md", templates.BUGS_README)
    _write(contracts / "bugs" / "_TEMPLATE.yaml", templates.BUG_TEMPLATE)
    _write(contracts / "knowledge" / "KNOWLEDGE.yaml", templates.KNOWLEDGE_YAML)
    _write(contracts / "knowledge" / "KNOWLEDGE.md", templates.KNOWLEDGE_MD)

    # 交付库集合
    _write(deliveries_root / "CLAUDE.md", templates.DELIVERIES_CLAUDE)
    _write(deliveries_root / "AGENTS.md", templates.DELIVERIES_AGENTS)
    _write(
        deliveries_root / ".metaflow" / "role.yaml",
        "role: worker\nworkspace_root: ..\n",
    )
    _write(
        deliveries_root / ".gitignore",
        ".metaflow/session-role.json\n.metaflow/*.lock\n",
    )

    for delivery in deliveries:
        delivery_root = deliveries_root / delivery
        for directory in (
            delivery_root / "src",
            delivery_root / "tests",
            delivery_root / "release",
            delivery_root / ".metaflow",
        ):
            directory.mkdir(parents=True, exist_ok=True)
        _write(
            delivery_root / "CLAUDE.md",
            f"""# 交付库 {delivery}（执行者）

你是 `meta-worker`，当前交付库是 `{delivery}`。

- 只处理 `delivery: {delivery}` 的任务卡。
- 只写任务卡 `allowed_paths`。
- 不读契约库全文，只读 `mf task show --packet` 返回的任务包。
- 完成后写 `.metaflow/handoffs/<task-id>.md` 并 `mf task submit`。
- 不修改契约库、路标、需求、验收标准；不跨交付库。
""",
        )
        _dump_yaml(
            delivery_root / ".metaflow" / "worker.yaml",
            {
                "role": "worker",
                "delivery": delivery,
                "workspace_root": "../..",
                "allowed_paths": ["src/**", "tests/**", "release/**"],
            },
        )
        _dump_yaml(
            delivery_root / "delivery.yaml",
            {
                "id": delivery,
                "version": "1.0.0",
                "roadmap": "R1",
                "responsibility": f"{delivery} 交付库",
                "contracts": [],
                "artifacts": [],
                "docs": {
                    "release_notes": "RELEASE-NOTES.md",
                    "user_manual": "USER-MANUAL.md",
                },
                "repo": ".",
            },
        )
        _write(delivery_root / "RELEASE-NOTES.md", templates.RELEASE_NOTES)
        _write(delivery_root / "USER-MANUAL.md", templates.USER_MANUAL)
        _write(delivery_root / "src" / ".gitkeep", "")
        _write(delivery_root / "tests" / ".gitkeep", "")
        _write(delivery_root / "release" / ".gitkeep", "")

    if git:
        _git_init(contracts)
        _git_init(deliveries_root)

    return root


def load_project(root: Path) -> dict[str, Any]:
    """读取 contracts/project.yaml。"""
    path = root / "contracts" / "project.yaml"
    if not path.is_file():
        raise WorkspaceError(f"缺少 {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise WorkspaceError(f"{path} 不是合法 YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise WorkspaceError(f"{path} 顶层必须是映射")
    return data


def load_roadmap(root: Path) -> dict[str, Any]:
    """读取 contracts/roadmap/ROADMAP.yaml。"""
    path = root / "contracts" / "roadmap" / "ROADMAP.yaml"
    if not path.is_file():
        raise WorkspaceError(f"缺少 {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise WorkspaceError(f"{path} 不是合法 YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise WorkspaceError(f"{path} 顶层必须是映射")
    return data


def count_tasks(root: Path) -> dict[str, int]:
    """统计任务卡状态；无法解析的任务计入 invalid。"""
    counts: dict[str, int] = {}
    for path in sorted((root / "contracts" / "tasks").rglob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            counts["invalid"] = counts.get("invalid", 0) + 1
            continue
        status = data.get("status", "draft") if isinstance(data, dict) else "invalid"
        counts[str(status)] = counts.get(str(status), 0) + 1
    return counts


def build_status(root: Path, role: str | None = None) -> dict[str, Any]:
    """汇总当前工作区状态。"""
    project = load_project(root)
    roadmap_data = load_roadmap(root)
    roadmaps = roadmap_data.get("roadmaps") or []
    active_id = project.get("roadmap")
    active = next(
        (item for item in roadmaps if isinstance(item, dict) and item.get("id") == active_id),
        None,
    )
    return {
        "workspace": str(root),
        "project": {
            "id": project.get("project_id"),
            "name": project.get("name"),
        },
        "role": role or detect_role(root)[0],
        "roadmap": active,
        "phase": project.get("phase"),
        "version": project.get("version"),
        "version_policy": project.get("version_policy"),
        "plan_ref": project.get("plan_ref"),
        "deliveries": project.get("deliveries") or [],
        "tasks": count_tasks(root),
    }


def _contract_exists(contracts_root: Path, contract_id: str) -> bool:
    """在 specs/ 与 architecture/ 中按文件名或内容查找契约 ID。"""
    candidates = [
        *(contracts_root / "specs").rglob("*"),
        *(contracts_root / "architecture").rglob("*"),
    ]
    for path in candidates:
        if not path.is_file() or path.suffix.lower() not in {".md", ".yaml", ".yml", ".json"}:
            continue
        if contract_id in path.name:
            return True
        try:
            if contract_id in path.read_text(encoding="utf-8"):
                return True
        except OSError:
            continue
    return False


def doctor(root: Path) -> list[str]:
    """校验工作区结构与版本一致性，返回错误列表。"""
    errors: list[str] = []
    contracts = root / "contracts"
    deliveries_root = root / "deliveries"

    if not (contracts / "project.yaml").is_file():
        errors.append("缺少 contracts/project.yaml")
    if not deliveries_root.is_dir():
        errors.append("缺少 deliveries/ 目录")
    if errors:
        return errors

    try:
        project = load_project(root)
        roadmap_data = load_roadmap(root)
    except WorkspaceError as exc:
        return [str(exc)]

    project_id = project.get("project_id")
    project_name = project.get("name")
    roadmap_id = project.get("roadmap")
    if not project_id:
        errors.append("project.yaml 缺少 project_id")
    if not project_name:
        errors.append("project.yaml 缺少 name")
    if not roadmap_id:
        errors.append("project.yaml 缺少 roadmap")

    version_policy = project.get("version_policy", "same-major")
    if version_policy not in {"same-major", "exact", "independent"}:
        errors.append(f"project.yaml version_policy 非法: {version_policy}")

    plan_ref = project.get("plan_ref", "project/PROJECT-PLAN.md")
    if not (contracts / str(plan_ref)).is_file():
        errors.append(f"缺少项目计划: contracts/{plan_ref}")

    roadmaps = roadmap_data.get("roadmaps")
    if not isinstance(roadmaps, list) or not roadmaps:
        errors.append("ROADMAP.yaml 缺少非空 roadmaps 列表")
        active = None
    else:
        active = next(
            (item for item in roadmaps if isinstance(item, dict) and item.get("id") == roadmap_id),
            None,
        )
        if active is None:
            errors.append(f"ROADMAP.yaml 中找不到当前路标: {roadmap_id}")

    roadmap_match = _ROADMAP_RE.fullmatch(str(roadmap_id or ""))
    if active and roadmap_match:
        roadmap_major = roadmap_match.group(1)
        version_target = str(active.get("version_target", ""))
        major = version_target.split(".", 1)[0] if version_target else ""
        if major != roadmap_major:
            errors.append(
                f"路标 {roadmap_id} 与版本 {version_target} 的 MAJOR 不一致"
            )

    if not (contracts / "requirements" / "REQUIREMENTS.yaml").is_file():
        errors.append("缺少 contracts/requirements/REQUIREMENTS.yaml")
    else:
        try:
            yaml.safe_load(
                (contracts / "requirements" / "REQUIREMENTS.yaml").read_text(encoding="utf-8")
            )
        except yaml.YAMLError as exc:
            errors.append(f"REQUIREMENTS.yaml 不是合法 YAML: {exc}")

    for standard_name in templates.STANDARDS:
        if not (contracts / "standards" / standard_name).is_file():
            errors.append(f"缺少规范: contracts/standards/{standard_name}")

    if not (contracts / "state" / "ledger.ndjson").is_file():
        errors.append("缺少 contracts/state/ledger.ndjson")

    knowledge_path = contracts / "knowledge" / "KNOWLEDGE.yaml"
    if knowledge_path.is_file():
        try:
            yaml.safe_load(knowledge_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            errors.append(f"KNOWLEDGE.yaml 不是合法 YAML: {exc}")

    for relative in (
        "CLAUDE.md",
        "AGENTS.md",
        "mf.workspace.yaml",
        "contracts/CLAUDE.md",
        "contracts/AGENTS.md",
        "contracts/.metaflow/role.yaml",
        "deliveries/CLAUDE.md",
        "deliveries/AGENTS.md",
        "deliveries/.metaflow/role.yaml",
    ):
        if not (root / relative).is_file():
            errors.append(f"缺少角色/清单文件: {relative}")

    for relative in (
        "contracts/bugs/README.md",
        "contracts/bugs/_TEMPLATE.yaml",
        "contracts/knowledge/KNOWLEDGE.yaml",
        "contracts/knowledge/KNOWLEDGE.md",
    ):
        if not (root / relative).is_file():
            errors.append(f"缺少缺陷/知识文件: {relative}")

    deliveries = project.get("deliveries")
    if not isinstance(deliveries, list) or not deliveries:
        errors.append("project.yaml 至少需要一个交付库")
        return errors

    seen: set[str] = set()
    for entry in deliveries:
        if not isinstance(entry, dict):
            errors.append("project.yaml 的 deliveries 条目必须是映射")
            continue
        delivery_id = entry.get("id")
        raw_path = entry.get("path")
        if not delivery_id or not raw_path:
            errors.append("交付库条目缺少 id 或 path")
            continue
        if delivery_id in seen:
            errors.append(f"交付库 id 重复: {delivery_id}")
            continue
        seen.add(delivery_id)

        delivery_path = (root / str(raw_path)).resolve()
        if not delivery_path.is_relative_to(deliveries_root.resolve()):
            errors.append(f"交付库路径必须位于 deliveries/: {raw_path}")
            continue
        if not delivery_path.is_dir():
            errors.append(f"交付库目录不存在: {raw_path}")
            continue

        for required in ("delivery.yaml", "RELEASE-NOTES.md", "USER-MANUAL.md"):
            if not (delivery_path / required).is_file():
                errors.append(f"交付库 {delivery_id} 缺少 {required}")

        delivery_yaml = delivery_path / "delivery.yaml"
        if delivery_yaml.is_file():
            try:
                delivery_data = yaml.safe_load(delivery_yaml.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as exc:
                errors.append(f"{delivery_yaml} 不是合法 YAML: {exc}")
                delivery_data = {}
            if isinstance(delivery_data, dict):
                if delivery_data.get("id") != delivery_id:
                    errors.append(f"delivery.yaml 的 id 与注册表不一致: {delivery_id}")
                if delivery_data.get("roadmap") != roadmap_id:
                    errors.append(f"交付库 {delivery_id} 的 roadmap 与项目不一致")
                delivery_version = str(delivery_data.get("version", ""))
                project_version = str(project.get("version", ""))
                if version_policy == "exact":
                    if _version_core(delivery_version) != _version_core(project_version):
                        errors.append(
                            f"交付库 {delivery_id} 的版本 {delivery_version} "
                            f"必须等于项目版本 {project_version}"
                        )
                elif version_policy == "same-major":
                    delivery_major = (
                        delivery_version.split(".", 1)[0] if delivery_version else ""
                    )
                    if roadmap_match and delivery_major != roadmap_match.group(1):
                        errors.append(
                            f"交付库 {delivery_id} 的版本 {delivery_version} "
                            f"与路标 {roadmap_id} 不一致"
                        )
                # independent：兼容范围由 R2 契约库检查；R0/R1 不做额外校验
                contracts_refs = delivery_data.get("contracts") or []
                if isinstance(contracts_refs, list):
                    for contract_id in contracts_refs:
                        if isinstance(contract_id, str) and not _contract_exists(
                            contracts, contract_id
                        ):
                            errors.append(
                                f"交付库 {delivery_id} 引用了不存在的契约: {contract_id}"
                            )

    return errors
