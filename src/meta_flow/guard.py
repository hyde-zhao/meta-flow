"""PreToolUse 守卫：在 Claude Code 工具层拦截越界 Read/Write/Edit/Bash。"""

from __future__ import annotations

import json
import os
import re
import shlex
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from . import roles
from .workspace import detect_role, find_workspace_root, resolve_contract

HOOK_COMMAND = "mf hook pretool"
HOOK_MATCHER = "Read|Write|Edit|MultiEdit|NotebookEdit|Grep|Glob|Bash"
PATH_KEYS = ("file_path", "path", "notebook_path")
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
READ_TOOLS = {"Read", "Grep", "Glob"}

# Bash 路径策略（BUG-0014）：识别常见读写命令、重定向与运行时目录
BASH_READ_COMMANDS = {
    "cat",
    "head",
    "tail",
    "less",
    "more",
    "grep",
    "egrep",
    "fgrep",
    "rg",
    "awk",
    "sed",
    "cut",
    "sort",
    "uniq",
    "wc",
    "strings",
    "xxd",
    "od",
    "md5sum",
    "sha1sum",
    "sha256sum",
    "stat",
    "file",
}
BASH_WRITE_COMMANDS = {
    "tee",
    "cp",
    "mv",
    "rm",
    "ln",
    "touch",
    "mkdir",
    "rmdir",
    "truncate",
    "chmod",
    "chown",
    "dd",
    "install",
    "rsync",
}
BASH_WRITE_OPS = {">", ">>", ">|", "&>", "&>>"}
BASH_RUNTIME_PARTS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "dist",
    "build",
}


def _runtime_part(part: str) -> bool:
    """运行时/构建目录：清理或写入不视为源码越界（MFP-0030）。"""
    return part in BASH_RUNTIME_PARTS or part.endswith(".egg-info")
BASH_SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
MAX_SHELL_DEPTH = 4
PROCESS_SUBST_RE = re.compile(r"[<>]\(([^()]*)\)")
SECOND_EVAL_RE = re.compile(r"(^|[\s;&|])(?:eval|source)\b|(^|[\s;&|])\.\s")
PROCESS_WRITE_NAMES = {"dev-record.md", "handoff.md", "review.md", "review-handoff.md"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _deny(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"Meta Flow 边界: {reason}",
        }
    }


def _glob_regex(pattern: str) -> re.Pattern[str]:
    raw = pattern.replace("\\", "/").strip()
    while raw.startswith("./"):
        raw = raw[2:]
    parts = ["^"]
    index = 0
    while index < len(raw):
        char = raw[index]
        if char == "*":
            if index + 1 < len(raw) and raw[index + 1] == "*":
                parts.append(".*")
                index += 2
            else:
                parts.append("[^/]*")
                index += 1
        elif char == "?":
            parts.append("[^/]")
            index += 1
        else:
            parts.append(re.escape(char))
            index += 1
    parts.append("$")
    return re.compile("".join(parts))


def _matches(path: str, patterns: list[str]) -> bool:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return any(_glob_regex(str(pattern)).match(normalized) for pattern in patterns)


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _resolve_role(cwd: Path, session_id: str | None = None) -> tuple[str, Path | None]:
    """解析 effective role：会话锚点 > 显式 MF_ROLE（受控）> 目录推导。

    T033 A1：锚点由 SessionStart/TTY 用户切换写入，用来抵御 cwd 漂移；
    ``MF_ROLE=designer`` 不得由 worker/manager 会话通过环境变量伪造，
    只有目录/锚点本身是 designer 时才生效（fail-closed）。
    """
    detected_role, detected_root = detect_role(cwd)
    anchor = roles.read_anchor(cwd, session_id)
    if anchor is not None:
        return anchor["role"], anchor["root"]
    env_role = roles.normalize_role(os.environ.get("MF_ROLE"))
    if env_role:
        if env_role == detected_role:
            return env_role, detected_root
        if env_role == "designer":
            # designer 必须来自目录安装或锚点，环境变量不能提权
            pass
        elif env_role in {"worker", "maintainer"}:
            # 显式降权/维护角色：保持原有语义，但 root 只在与目录一致时绑定
            return env_role, None
        elif env_role == "manager":
            # manager 只允许与目录推导一致，避免 worker 会话借 MF_ROLE 提权
            pass
    if detected_role != "unbound":
        return detected_role, detected_root
    return "unbound", None


def _bash_tokens(command: str) -> list[str]:
    try:
        return shlex.split(command, posix=True)
    except ValueError:
        return command.split()


def _resolve_token_path(token: str, base: Path) -> Path:
    cleaned = os.path.expandvars(token.strip("'\""))
    candidate = Path(cleaned).expanduser()
    return candidate.resolve() if candidate.is_absolute() else (base / candidate).resolve()


def _unresolved_path(raw: str) -> bool:
    return "$" in raw or "`" in raw or "$(" in raw


def _nested_shell_parts(tokens: list[str], index: int) -> tuple[str, int] | None:
    name = Path(tokens[index].strip("'\"")).name
    if name not in BASH_SHELLS:
        return None
    cursor = index + 1
    while cursor < len(tokens) - 1:
        option = tokens[cursor]
        if option == "--":
            cursor += 1
            continue
        if option in {"-c"} or re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", option):
            return tokens[cursor + 1], cursor + 2
        if not option.startswith("-"):
            return None
        cursor += 1
    return None


def _bash_extract(
    command: str,
    cwd: Path,
    *,
    depth: int = 0,
    seen: set[str] | None = None,
) -> tuple[list[Path], set[Path], bool]:
    """从 Bash 命令提取路径/写目标；展开变量并递归解析 sh -c/bash -c。

    返回 (paths, writes, unsafe)。无法安全解析的变量/命令替换/嵌套过深置
    unsafe，由 _bash_decision 对涉及路径的 worker 读写保守拒绝。
    """
    if seen is None:
        seen = set()
    if depth > MAX_SHELL_DEPTH or command in seen:
        return [], set(), True
    seen.add(command)
    tokens = _bash_tokens(command)
    paths: list[Path] = []
    writes: set[Path] = set()
    unsafe = False
    base = cwd

    # R13：进程替换 <(...) / >(...) 内部命令会实际执行，递归解析；
    # 与 eval/source/. 组合属于二次求值，无法静态确认时保守标记 unsafe。
    if "<(" in command or ">(" in command:
        if SECOND_EVAL_RE.search(command):
            unsafe = True
        for match in PROCESS_SUBST_RE.finditer(command):
            inner = match.group(1).strip()
            if not inner:
                unsafe = True
                continue
            inner_paths, inner_writes, inner_unsafe = _bash_extract(
                inner, base, depth=depth + 1, seen=seen
            )
            paths.extend(inner_paths)
            writes.update(inner_writes)
            unsafe = unsafe or inner_unsafe

    index = 0
    expect_command = True
    assigned_vars: set[str] = set()
    while index < len(tokens):
        token = tokens[index]
        if token in {"&&", ";", "||", "|", "&"}:
            expect_command = True
            index += 1
            continue
        if expect_command and Path(token.strip("'\"")).name in {
            "sudo",
            "env",
            "command",
            "builtin",
            "nohup",
            "time",
        }:
            index += 1
            continue
        if expect_command and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", token):
            assigned_vars.add(token.split("=", 1)[0])
            index += 1
            continue
        if expect_command and (token == "eval" or Path(token.strip("'\"")).name == "eval"):
            # eval 对剩余参数二次求值；递归解析其命令文本
            nested_command = " ".join(tokens[index + 1 :]).strip()
            if not nested_command:
                unsafe = True
            else:
                nested_paths, nested_writes, nested_unsafe = _bash_extract(
                    nested_command, base, depth=depth + 1, seen=seen
                )
                paths.extend(nested_paths)
                writes.update(nested_writes)
                unsafe = unsafe or nested_unsafe
            index = len(tokens)
            continue
        if expect_command and token in {"source", "."}:
            # source/. 执行目标脚本；进程替换组合已在上方标记 unsafe；
            # 普通文件路径沿用后续路径策略校验。
            if "<(" in command or ">(" in command:
                unsafe = True
            expect_command = False
            index += 1
            continue
        nested = _nested_shell_parts(tokens, index) if expect_command else None
        if nested is not None:
            nested_command, next_index = nested
            nested_paths, nested_writes, nested_unsafe = _bash_extract(
                nested_command, base, depth=depth + 1, seen=seen
            )
            paths.extend(nested_paths)
            writes.update(nested_writes)
            unsafe = unsafe or nested_unsafe
            expect_command = False
            index = next_index
            continue
        if expect_command and token == "cd" and index + 1 < len(tokens):
            raw = os.path.expandvars(tokens[index + 1].strip("'\""))
            if _unresolved_path(raw):
                unsafe = True
            else:
                base = _resolve_token_path(raw, base)
                # M1a：cd 目标也纳入作用域校验，防止借 cd 逃逸路径检查
                paths.append(base)
            expect_command = False
            index += 2
            continue
        if token in BASH_WRITE_OPS or re.fullmatch(r"\d?>>?", token):
            if index + 1 < len(tokens):
                raw = os.path.expandvars(tokens[index + 1].strip("'\""))
                if _unresolved_path(raw):
                    unsafe = True
                else:
                    target = _resolve_token_path(raw, base)
                    paths.append(target)
                    writes.add(target)
                index += 2
                continue
        name = Path(token.strip("'\"")).name
        if name in BASH_WRITE_COMMANDS:
            cursor = index + 1
            while cursor < len(tokens) and tokens[cursor] not in {"&&", ";", "||", "|"}:
                candidate = tokens[cursor]
                if not candidate.startswith("-") and candidate not in BASH_WRITE_OPS:
                    raw = os.path.expandvars(candidate.strip("'\""))
                    if _unresolved_path(raw):
                        unsafe = True
                    else:
                        target = _resolve_token_path(raw, base)
                        paths.append(target)
                        writes.add(target)
                cursor += 1
        cleaned = token.strip("'\"")
        if "=" in cleaned and cleaned.startswith("--"):
            cleaned = cleaned.split("=", 1)[1]
        if cleaned and not cleaned.startswith("-") and cleaned not in {
            "&&",
            ";",
            "||",
            "|",
            "&",
        }:
            if not cleaned.startswith(("http://", "https://", "git@")):
                expanded = os.path.expandvars(cleaned)
                if _unresolved_path(expanded):
                    unsafe = True
                candidate = Path(expanded).expanduser()
                if "/" in expanded or candidate.is_absolute():
                    paths.append(_resolve_token_path(expanded, base))
        if expect_command:
            expect_command = False
        index += 1
    # 嵌入命令字符串的绝对路径（如 python -c / heredoc 中的 open('/path')）
    for match in re.finditer(r"(?<![\w.-])(/[^\s'\"`;|&<>]+)", command):
        raw = os.path.expandvars(match.group(1))
        if _unresolved_path(raw):
            unsafe = True
            continue
        paths.append(Path(raw).expanduser().resolve())
    # 引号内的相对路径（heredoc/python 写入等），保守纳入写路径策略
    for match in re.finditer(r"""['"]([^'"\n]+)['"]""", command):
        raw = match.group(1).strip()
        if not raw or raw.startswith(("http://", "https://", "git@")):
            continue
        if (
            "/" in raw
            or raw.startswith(".")
            or re.fullmatch(r"[A-Za-z0-9_.-]+\.[A-Za-z0-9]{1,5}", raw)
        ):
            expanded = os.path.expandvars(raw)
            if _unresolved_path(expanded):
                unsafe = True
                continue
            paths.append(_resolve_token_path(expanded, cwd))
    if _unresolved_path(command) and ("/" in command or "$(" in command or "`" in command):
        # 命令替换/反引号可能构造受保护路径；无法静态解析时保守标记
        if "$(" in command or "`" in command:
            unsafe = True
    for var in assigned_vars:
        if re.search(rf"\$\{{{re.escape(var)}\}}|\${re.escape(var)}\b", command):
            # 环境变量赋值后的引用可能改变路径语义，静态无法确认时保守标记
            unsafe = True
    deduped: list[Path] = []
    seen_paths: set[str] = set()
    for path in paths:
        key = str(path)
        if key in seen_paths:
            continue
        seen_paths.add(key)
        deduped.append(path)
    return deduped, writes, unsafe


def _bash_read_like(command: str) -> bool:
    names = {Path(token.strip("'\"")).name for token in _bash_tokens(command)}
    return bool(names & BASH_READ_COMMANDS)


def _has_redirect_write(command: str) -> bool:
    """检测写文件重定向；``2>&1``/``>&2`` 等 fd 复制不算写。"""
    for match in re.finditer(r"\d?>>?", command):
        tail = command[match.end() : match.end() + 1]
        if tail == "&":
            continue
        if tail.isdigit() and command[match.start() : match.end()].startswith(">"):
            continue
        return True
    return False


def _bash_write_heuristic(command: str) -> bool:
    if _has_redirect_write(command):
        return True
    if re.search(r"(open\(|write_text|\.write\(|--output|--out\b|tee\b)", command):
        return True
    names = {Path(token.strip("'\"")).name for token in _bash_tokens(command)}
    if names & BASH_WRITE_COMMANDS:
        return True
    if "sed" in names and any(token in {"-i", "--in-place"} for token in _bash_tokens(command)):
        return True
    return False


def _contract_process_write(relative: str) -> bool:
    posix = "/" + relative.replace("\\", "/")
    if "/tasks/" not in posix:
        return False
    if "/evidence/" in posix:
        return True
    return Path(relative).name in PROCESS_WRITE_NAMES


def _local_mfp_write(relative: str) -> bool:
    parts = relative.replace("\\", "/").split("/")
    return (
        len(parts) == 3
        and parts[0] == ".meta-flow"
        and parts[1] == "improvements"
        and parts[2].startswith("MFP-")
        and parts[2].endswith(".yaml")
    )


def _delivery_write_allowed(relative: str, tasks: list[dict[str, Any]]) -> bool:
    parts = relative.replace("\\", "/").split("/")
    if any(_runtime_part(part) for part in parts):
        return True
    if _local_mfp_write(relative):
        return True
    if relative.startswith(".meta-flow/"):
        for task in tasks:
            task_id = str(task.get("id") or "")
            if relative in {
                f".meta-flow/dev-records/{task_id}.md",
                f".meta-flow/handoffs/{task_id}.md",
            }:
                return True
        return False
    for task in tasks:
        if _matches(relative, [str(item) for item in task.get("allowed_paths") or []]):
            return True
    return False


def _path_under_known_delivery(path: Path, workspace_root: Path | None) -> bool:
    if workspace_root is None:
        return False
    local = _load_yaml(workspace_root / ".meta-flow" / "workspace.yaml")
    for item in local.get("subprojects") or []:
        sub = (workspace_root / str(item.get("path") or "")).resolve()
        if path == sub or sub in path.parents:
            return True
    return False


def _read_budget(contract: Path, role: str) -> int:
    policy_data = _load_yaml(contract / "policies" / "CONTEXT-POLICY.yaml")
    budget = ((policy_data.get("roles") or {}).get(role) or {}).get("budget") or {}
    default = 131072 if role in {"manager", "designer"} else 65536
    return int(budget.get("bytes") or default)


def _sanitize_command(command: str) -> str:
    """审计命令前脱敏常见凭据；只记录截断后的命令文本（R11）。"""
    redacted = re.sub(r"(?i)(bearer\s+)(\S+)", r"\1***", command)
    redacted = re.sub(
        r"(?i)((?:token|secret|password|passwd|api[_-]?key|authorization)[=:\s]+)(\S+)",
        r"\1***",
        redacted,
    )
    return redacted[:500]


def _task_summary_for_hint(contract: Path, role_root: Path | None) -> tuple[str, str, str]:
    delivery = _worker_delivery(role_root)
    tasks = _active_tasks(contract, delivery) if delivery else []
    if not tasks:
        return "无", "-", "-"
    task = tasks[0]
    lease = str((task.get("lease") or {}).get("expires_at") or "-")
    allowed = ",".join(str(item) for item in task.get("allowed_paths") or []) or "-"
    return str(task.get("id") or "-"), lease, allowed


def _worker_hint(contract: Path, role_root: Path | None) -> str:
    task_id, lease, allowed = _task_summary_for_hint(contract, role_root)
    return (
        f"[role=worker task={task_id} lease={lease} allowed={allowed}; "
        "合法通道: mf task show --packet / mf context show|expand；"
        "提交后不可编辑；review NEEDS_REWORK 会自动回流，用 mf task rework <id> 开始；"
        "范围外事项用 needs: acceptance|bug|mfp|chg 标注，manager 另开单，不阻塞返工；"
        "角色切换请在用户终端 mf role --as <role> --reason <原因>；"
        "本地 MFP 用 mf improve new --local 或写 .meta-flow/improvements/MFP-*.yaml]"
    )


def _deny_with_hint(
    reason: str,
    *,
    contract: Path | None,
    role: str,
    role_root: Path | None,
) -> dict[str, Any]:
    if role == "worker" and contract is not None:
        reason = f"{reason}；{_worker_hint(contract, role_root)}"
    elif role == "designer":
        reason = (
            f"{reason}；[role=designer；设计区写 architecture/specs/P2；"
            "角色切换请在用户终端运行 mf role --as <role> --reason <原因>]"
        )
    elif role:
        reason = f"{reason}；[role={role}]"
    return _deny(reason)


def _audit_guard(
    contract: Path | None,
    *,
    role: str,
    task: str | None,
    tool: str,
    decision: str,
    path: str | None = None,
    paths: list[str] | None = None,
    reason: str | None = None,
    command: str | None = None,
    parsed: list[str] | None = None,
    unsafe: bool = False,
) -> None:
    """持久化 guard allow/deny（role/task/path/reason/tool），供查询与审计。"""
    if contract is None:
        return
    try:
        log_path = contract / "state" / "READ-LOG.ndjson"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        record: dict[str, Any] = {
            "ts": _now(),
            "event": "guard",
            "actor": role,
            "role": role,
            "task": task or "无",
            "tool": tool,
            "decision": decision,
        }
        if path:
            record["path"] = path
        if paths:
            record["paths"] = paths[:8]
        if reason:
            record["reason"] = reason
        if command is not None:
            record["command"] = _sanitize_command(command)
        if parsed is not None:
            record["parsed_paths"] = parsed[:8]
        if unsafe:
            record["unsafe"] = True
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        return


def _hook_path(payload: dict[str, Any], cwd: Path) -> Path | None:
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return None
    raw = next((tool_input.get(key) for key in PATH_KEYS if tool_input.get(key)), None)
    if raw is None:
        return None
    path = Path(str(raw)).expanduser()
    return path if path.is_absolute() else (cwd / path).resolve()


def _worker_delivery(root: Path | None) -> str | None:
    if root is None:
        return None
    data = _load_yaml(root / "delivery.yaml")
    return str(data.get("id")) if data.get("id") else None


def _task_scope_mode(task: dict[str, Any]) -> str:
    scope = task.get("scope")
    scope = scope if isinstance(scope, dict) else {}
    return str(scope.get("mode") or "single_subproject")


def _task_scope_projects(task: dict[str, Any]) -> list[str]:
    scope = task.get("scope")
    scope = scope if isinstance(scope, dict) else {}
    return [str(item) for item in scope.get("projects") or []]


def _task_scope_operations(task: dict[str, Any]) -> list[str]:
    scope = task.get("scope")
    scope = scope if isinstance(scope, dict) else {}
    return [str(item) for item in scope.get("operations") or []]


def _active_tasks(contract: Path, delivery: str | None) -> list[dict[str, Any]]:
    items = []
    for path in sorted((contract / "roadmap").glob("*/phases/*/tasks/T*/TASK.yaml")):
        task = _load_yaml(path)
        if task.get("status") != "in_progress":
            continue
        mode = _task_scope_mode(task)
        # workspace 作用域由 manager 执行，不进入 worker guard 任务集。
        if mode == "workspace":
            continue
        if delivery:
            if mode == "cross_subproject":
                if delivery not in _task_scope_projects(task):
                    continue
            elif task.get("delivery") and task.get("delivery") != delivery:
                continue
        task["_bundle"] = path.parent
        items.append(task)
    return items


def _cross_project_read_allowed(
    path: Path,
    tasks: list[dict[str, Any]],
    workspace_root: Path | None,
) -> bool:
    """cross_subproject 任务只读/测试例外：声明项目内读取放行，写仍拒绝。"""
    if workspace_root is None:
        return False
    local_path = workspace_root / ".meta-flow" / "workspace.yaml"
    if not local_path.is_file():
        return False
    local = _load_yaml(local_path)
    allowed_projects: set[str] = set()
    for task in tasks:
        if _task_scope_mode(task) != "cross_subproject":
            continue
        operations = set(_task_scope_operations(task))
        if not operations & {"read", "test"}:
            continue
        allowed_projects.update(_task_scope_projects(task))
    if not allowed_projects:
        return False
    for item in local.get("subprojects") or []:
        sub_id = str(item.get("id") or "")
        if sub_id not in allowed_projects:
            continue
        sub = (workspace_root / str(item.get("path") or "")).resolve()
        if path == sub or sub in path.parents:
            return True
    return False


def _cross_project_write_denied(
    path: Path,
    tasks: list[dict[str, Any]],
    workspace_root: Path | None,
) -> bool:
    """cross_subproject 例外任务对声明项目的写入一律拒绝。"""
    if workspace_root is None:
        return False
    local_path = workspace_root / ".meta-flow" / "workspace.yaml"
    if not local_path.is_file():
        return False
    local = _load_yaml(local_path)
    projects: set[str] = set()
    for task in tasks:
        if _task_scope_mode(task) == "cross_subproject":
            projects.update(_task_scope_projects(task))
    if not projects:
        return False
    for item in local.get("subprojects") or []:
        if str(item.get("id") or "") not in projects:
            continue
        sub = (workspace_root / str(item.get("path") or "")).resolve()
        if path == sub or sub in path.parents:
            return True
    return False


def _designer_tasks(contract: Path) -> list[dict[str, Any]]:
    """designer 活动 design 任务（用于放行任务 bundle 的流程文件写入）。"""
    items = []
    for path in sorted((contract / "roadmap").glob("*/phases/*/tasks/T*/TASK.yaml")):
        task = _load_yaml(path)
        if task.get("status") != "in_progress":
            continue
        if task.get("kind") != "design" and task.get("owner_role") != "designer":
            continue
        if str(task.get("owner_role") or "designer") != "designer":
            continue
        task["_bundle"] = path.parent
        items.append(task)
    return items


def _task_bundle_prefix(task: dict[str, Any]) -> str:
    task_id = str(task.get("id") or "")
    parts = task_id.split("-")
    if len(parts) == 3 and parts[0] and parts[1] and parts[2]:
        return f"roadmap/{parts[0]}/phases/{parts[1]}/tasks/{parts[2]}/"
    roadmap = str(task.get("roadmap") or "")
    phase = str(task.get("phase") or "")
    bundle = Path(str(task.get("_bundle") or "")).name
    if roadmap and phase and bundle:
        return f"roadmap/{roadmap}/phases/{phase}/tasks/{bundle}/"
    return ""


def _id_bundle_prefix(task_id: str) -> str:
    parts = str(task_id or "").split("-")
    if len(parts) != 3:
        return ""
    return f"roadmap/{parts[0]}/phases/{parts[1]}/tasks/{parts[2]}/"


def _path_in_prefix(relative: str, prefix: str) -> bool:
    if not prefix:
        return False
    rel = relative.replace("\\", "/").lstrip("/")
    return rel == prefix.rstrip("/") or rel.startswith(prefix)


def _bundle_match(relative: str, tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
    for task in tasks:
        if _path_in_prefix(relative, _task_bundle_prefix(task)):
            return task
    return None


def _review_target_match(relative: str, tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
    """评审任务可读其 reviews 目标 bundle（含 evidence），按完整任务 ID 匹配。"""
    for task in tasks:
        if task.get("kind") != "review":
            continue
        target = str(task.get("reviews") or "")
        if _path_in_prefix(relative, _id_bundle_prefix(target)):
            return task
    return None


def _review_output_match(relative: str, tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
    """返工任务可读自己被评审任务（reviewed_by_task）的评审输出，按完整 ID。"""
    for task in tasks:
        if task.get("kind") == "review":
            continue
        review_task = str(task.get("reviewed_by_task") or "")
        if _path_in_prefix(relative, _id_bundle_prefix(review_task)):
            return task
    return None


def _review_scope_match(relative: str, tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
    """review 任务可只读 review.scope 内文件（MFP-0027，不误判写入/预算）。"""
    for task in tasks:
        if task.get("kind") != "review":
            continue
        scope = [str(item) for item in (task.get("review") or {}).get("scope") or []]
        if scope and _matches(relative, scope):
            return task
    return None


CONTROLLED_PREFIXES = {"sudo", "env", "command", "builtin", "nohup", "time"}


ANCHOR_API_RE = re.compile(
    r"\b(?:session_start|write_anchor|switch_role)\b",
    re.IGNORECASE,
)
INTERPRETER_RE = re.compile(r"\b(?:python[0-9.]*|uv|bash|sh|zsh|dash)\b", re.IGNORECASE)
_COMPACT_RE = re.compile(r"[\s'\"+_\[\](),;:`]+")


_SHELL_SPLIT_RE = re.compile(r"(?:&&|\|\||;|\n|\r|\|)")
_LAUNCHER_PREFIXES = {"command", "exec", "env", "sudo", "nohup", "time"}


def _command_segments(command: str) -> list[str]:
    """按 shell 操作符粗分命令段（引号内的 ; | && 不分割）。"""
    segments: list[str] = []
    buffer: list[str] = []
    quote: str | None = None
    escaped = False
    index = 0
    while index < len(command):
        char = command[index]
        if escaped:
            buffer.append(char)
            escaped = False
            index += 1
            continue
        if char == "\\" and quote != "'":
            buffer.append(char)
            escaped = True
            index += 1
            continue
        if quote is not None:
            buffer.append(char)
            if char == quote:
                quote = None
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            buffer.append(char)
            index += 1
            continue
        if command.startswith("&&", index) or command.startswith("||", index):
            segment = "".join(buffer).strip()
            if segment:
                segments.append(segment)
            buffer = []
            index += 2
            continue
        if char in {";", "\n", "\r", "|"}:
            segment = "".join(buffer).strip()
            if segment:
                segments.append(segment)
            buffer = []
            index += 1
            continue
        buffer.append(char)
        index += 1
    tail = "".join(buffer).strip()
    if tail:
        segments.append(tail)
    return segments


def _segment_program(segment: str) -> tuple[str, list[str]] | None:
    tokens = _bash_tokens(segment)
    index = 0
    while index < len(tokens):
        raw = tokens[index]
        name = Path(raw.strip("'\"")).name
        if name in _LAUNCHER_PREFIXES or re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*=.*", raw
        ):
            index += 1
            continue
        return name, tokens[index + 1 :]
    return None


def _segment_runs_interpreter(name: str, rest: list[str]) -> bool:
    """段首命令是否在执行解释器代码（而非把代码/词元当参数传给 git/grep）。"""
    if re.fullmatch(r"python[0-9.]*", name):
        return True
    if name in BASH_SHELLS:
        return True
    if name == "uv":
        if rest and rest[0] == "run" and len(rest) > 1:
            return _segment_runs_interpreter(Path(rest[1]).name, rest[2:])
        return False
    if name in {"mf", "mf.exe", "meta_flow", "meta_flow.cli"}:
        return True
    return False


def _session_hook_command(command: str) -> bool:
    """识别实际执行段中的 SessionStart hook 调用（M1a/R4/R8）。

    只检查解释器/uv/mf 执行段；``git commit -m`` 消息与只读 grep/cat
    中的同名词元不算调用，避免误伤（MFP-0039/REQ-0023）。
    """
    lowered = command.lower()
    if not any(word in lowered for word in ("hook", "session-start", "sessionstart")):
        return False
    for segment in _command_segments(command):
        low = segment.lower()
        if "hook" not in low and "session-start" not in low and "sessionstart" not in low:
            continue
        program = _segment_program(segment)
        if program is None:
            continue
        name, rest = program
        if name in BASH_READ_COMMANDS or name in {"git", "gh"}:
            continue
        if not _segment_runs_interpreter(name, rest):
            continue
        compact = re.sub(r"[\s'\"+_\[\](),;:`-]+", "", low)
        if "hook" in compact and "session" in compact and "start" in compact:
            return True
    return False


def _anchor_api_command(command: str) -> bool:
    """识别解释器/uv/mf 段调用锚点 API（含别名/importlib/拼接拆分）。

    只看实际执行段（MFP-0039/REQ-0023）；提交消息或只读检索里的
    ``anchor``/``session`` 词元不再触发 fail-closed。
    """
    for segment in _command_segments(command):
        program = _segment_program(segment)
        if program is None:
            continue
        name, rest = program
        if name in BASH_READ_COMMANDS or name in {"git", "gh"}:
            continue
        if not _segment_runs_interpreter(name, rest):
            continue
        if ANCHOR_API_RE.search(segment):
            return True
        lowered = segment.lower()
        compacted = _COMPACT_RE.sub("", lowered)
        if any(
            fragment in compacted
            for fragment in ("sessionstart", "writeanchor", "switchrole")
        ) and re.search(r"\b(?:meta_flow|getattr|importlib|roles)\b", lowered):
            return True
        if re.search(r"\b(?:meta_flow|getattr|importlib)\b", lowered) and re.search(
            r"anchor|session|switch", lowered
        ):
            return True
    return False


def _is_anchor_path(path: Path) -> bool:
    """会话锚点文件（legacy 单文件与 per-session 目录）。"""
    if path.name == "session-role.yaml" and path.parent.name == ".meta-flow":
        return True
    return (
        path.parent.name == "session-roles"
        and path.suffix.lower() == ".yaml"
        and ".meta-flow" in path.parts
    )


def _anchor_delete_command(command: str, write_paths: list[Path]) -> bool:
    """maintainer 清理锚点：仅允许单一 rm/unlink 删除锚点文件（MFP-0037）。

    删除锚点只会降权/清理，不构成伪造角色；创建/改写仍由 SessionStart 或
    用户终端 ``mf role --as`` 独占。
    """
    if not write_paths or any(not _is_anchor_path(item) for item in write_paths):
        return False
    if any(
        marker in command
        for marker in ("&&", "||", ";", "|", ">", "<", "`", "$(", "\n", "\r", "&")
    ):
        return False
    tokens = _bash_tokens(command)
    index = 0
    while index < len(tokens):
        raw = tokens[index]
        name = Path(raw.strip("'\"")).name
        if name in CONTROLLED_PREFIXES:
            index += 1
            continue
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", raw):
            index += 1
            continue
        break
    if index >= len(tokens):
        return False
    return Path(tokens[index].strip("'\"")).name in {"rm", "unlink"}


def _readonly_expand(command: str) -> bool:
    """识别纯只读的 `mf context expand ...` 命令（MFP-0025/0027）。

    只读命令由 context.expand 自身做路径授权并写 READ-LOG；guard 不再把
    路径参数误判为 Bash 写入。仅当首个可执行 token（允许 env/sudo 等受控
    前缀与 VAR=value 赋值后）为 `mf`（或以 `/mf` 结尾的可执行路径）且紧接
    `context expand` 时豁免；带 shell 操作符/重定向/替换/前置命令不豁免。
    """
    if any(
        marker in command
        for marker in ("&&", "||", ";", "|", ">", "<", "`", "$(", "\n", "\r", "&")
    ):
        return False
    tokens = _bash_tokens(command)
    index = 0
    while index < len(tokens):
        raw = tokens[index]
        name = Path(raw.strip("'\"")).name
        if name in CONTROLLED_PREFIXES:
            index += 1
            continue
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", raw):
            index += 1
            continue
        break
    if index >= len(tokens):
        return False
    if Path(tokens[index].strip("'\"")).name != "mf":
        return False
    rest = [
        Path(token.strip("'\"")).name for token in tokens[index + 1 : index + 3]
    ]
    return rest == ["context", "expand"]


def _maintainer_source_roots() -> list[Path]:
    """maintainer 可维护的 meta-flow 源码仓库（全局 manifest.source_dir）。"""
    home = Path(os.environ.get("META_FLOW_HOME", Path.home() / ".meta-flow"))
    roots: list[Path] = []
    manifest = home / "manifest.yaml"
    if manifest.is_file():
        try:
            data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
        except (yaml.YAMLError, OSError):
            data = {}
        raw = data.get("source_dir") if isinstance(data, dict) else None
        if raw:
            roots.append(Path(str(raw)).expanduser().resolve())
    roots.append((home / "source").resolve())
    return roots


def _manager_source_denied(path: Path, workspace_root: Path | None) -> bool:
    if workspace_root is None:
        return False
    local = _load_yaml(workspace_root / ".meta-flow" / "workspace.yaml")
    for item in local.get("subprojects") or []:
        sub = (workspace_root / str(item.get("path") or "")).resolve()
        if path == sub or sub in path.parents:
            relative = path.relative_to(sub).as_posix()
            if relative.startswith(("src/", "tests/", "lib/", "app/", "packages/")):
                return True
    return False


DESIGNER_CONTRACT_FILES = {"templates/DESIGN-PACKAGE.md"}


def _designer_contract_write(relative: str) -> bool:
    """designer 可写 contract 设计区：architecture/、specs/、P2 设计包、DP 模板。"""
    rel = relative.replace("\\", "/").lstrip("/")
    if rel.startswith(("architecture/", "specs/")):
        return True
    if rel in DESIGNER_CONTRACT_FILES:
        return True
    parts = rel.split("/")
    return (
        len(parts) >= 4
        and parts[0] == "roadmap"
        and re.fullmatch(r"R\d+", parts[1]) is not None
        and parts[2] == "phases"
        and parts[3] == "P2"
    )


def _bash_decision(payload: dict[str, Any], cwd: Path) -> dict[str, Any] | None:
    """Bash 路径策略与审计（BUG-0014/R7/R8/R10/R11）。

    覆盖常见读写命令、重定向、引号/绝对路径，展开 `$HOME` 等变量并递归解析
    `sh -c`/`bash -c`；无法安全解析的变量/命令替换/嵌套过深且涉及路径时保守
    deny。契约/交付/读预算 deny 区不放宽；本地 `.meta-flow/improvements/MFP-*.yaml`
    作为受控 write 白名单（带审计）。允许/拒绝持久化到 READ-LOG。
    """
    role, role_root = _resolve_role(cwd, payload.get("session_id"))
    if role == "unbound":
        return None
    tool_input = payload.get("tool_input") or {}
    command = str(tool_input.get("command") or "") if isinstance(tool_input, dict) else ""
    if not command.strip():
        return None
    paths, write_paths, unsafe = _bash_extract(command, cwd)
    try:
        contract = resolve_contract(role_root or cwd)
    except Exception:
        contract = None
    workspace_root = find_workspace_root(role_root or cwd)
    if contract is None:
        if role in {"worker", "designer", "manager"}:
            return _deny_with_hint(
                "无法解析 contract/工作区绑定（install.yaml 的 workspace_root 缺失、"
                "目录不在工作区或绑定不一致）；guard 对 Bash fail-closed。"
                "请从工作区根/子项目目录运行；子项目绑定漂移由 manager 运行 "
                "mf install worker --workspace-root <根> --contract-dir <contract> 修复",
                contract=None,
                role=role,
                role_root=role_root,
            )
        return None
    delivery = _worker_delivery(role_root) if role == "worker" else None
    tasks: list[dict[str, Any]] = []
    if role == "worker" and delivery:
        tasks = _active_tasks(contract, delivery)
    elif role == "designer":
        tasks = _designer_tasks(contract)
    audit_task = str(tasks[0].get("id")) if tasks else "无"
    write_all = bool(write_paths) or _bash_write_heuristic(command)
    read_like = _bash_read_like(command)
    max_bytes = _read_budget(contract, role)
    if _session_hook_command(command) or _anchor_api_command(command):
        # 防止 AI 通过 Bash 手动触发 SessionStart 锚点写入或直接调用锚点 API
        return _deny_with_hint(
            "SessionStart hook / 锚点写入 API 只能由宿主 SessionStart 或用户终端 "
            "mf role --as 调用，不能通过 Bash/解释器手动执行",
            contract=contract,
            role=role,
            role_root=role_root,
        )
    if write_all and any(_is_anchor_path(item) for item in write_paths):
        # 锚点只由 SessionStart hook / 用户终端 mf role --as 通过 CLI 写入；
        # 任何工具层直接写（含 manager 委托）都拒绝，防止伪造角色。
        # MFP-0037：maintainer 是最高维护权限，允许删除遗留锚点（降权清理），
        # 但仍禁止创建/改写锚点内容。
        if not (role == "maintainer" and _anchor_delete_command(command, write_paths)):
            return _deny_with_hint(
                "会话角色锚点只能由 SessionStart 或用户终端 mf role --as 写入；"
                "maintainer 仅可删除遗留锚点文件",
                contract=contract,
                role=role,
                role_root=role_root,
            )
    if role == "worker" and not write_all and _readonly_expand(command):
        # 纯只读 expand：路径授权与 READ-LOG 由 context.expand 负责，
        # 不把路径参数误判为 Bash 写入（MFP-0027）。
        _audit_guard(
            contract,
            role=role,
            task=audit_task,
            tool="Bash",
            decision="allow",
            paths=[str(path) for path in paths],
            command=command,
            parsed=[str(path) for path in paths],
        )
        return None
    deny_reason: str | None = None
    audit_paths = [str(path) for path in paths]
    parsed_paths = audit_paths

    if role == "worker" and unsafe:
        deny_reason = (
            "无法安全解析 shell 路径（变量/命令替换/嵌套 shell），保守拒绝"
        )

    if deny_reason is None and not paths:
        return None

    for path in paths:
        if deny_reason is not None:
            break
        if path.is_relative_to(contract):
            relative = path.relative_to(contract).as_posix()
            if role == "manager":
                if relative.startswith("archive/") or (
                    write_all and relative.startswith("state/")
                ):
                    deny_reason = f"manager Bash 不能直接访问 {relative}"
                continue
            if role == "maintainer":
                if relative.startswith(("workspace/", ".meta-flow/")) and not write_all:
                    continue
                deny_reason = "maintainer 不改/读契约项目内容"
                continue
            if role == "designer":
                if relative.startswith("archive/") and not write_all:
                    deny_reason = "designer 不直接访问 archive/**；历史只读用 mf archive show --reason"
                    continue
                own_design_task = _bundle_match(relative, tasks)
                if (
                    write_all
                    and not _designer_contract_write(relative)
                    and not (
                        own_design_task is not None
                        and _contract_process_write(relative)
                    )
                ):
                    deny_reason = f"designer 只能写 contract 设计区/本任务流程文件: {relative}"
                    continue
                if read_like and path.is_file() and path.stat().st_size > max_bytes:
                    deny_reason = (
                        f"{path.name} 超过 designer 读预算 {max_bytes}B；"
                        "请用 mf context expand <path> --reason packet_missing"
                    )
                continue
            if role == "worker":
                if role_root is None:
                    deny_reason = (
                        "worker 无交付根绑定；请从交付库目录运行，"
                        "或在 CLI 任务命令中使用 --project-dir 指定交付库"
                    )
                    continue
                if not delivery:
                    deny_reason = f"交付库缺少 delivery.yaml，无法确定任务作用域: {role_root}"
                    continue
                own = _bundle_match(relative, tasks)
                review_target = _review_target_match(relative, tasks)
                review_output = _review_output_match(relative, tasks)
                if not (own or review_target or review_output):
                    deny_reason = (
                        "worker Bash 只能访问任务包/自己的 bundle、"
                        "评审任务的目标 bundle 或返工任务的评审输出"
                    )
                    continue
                if review_output is not None and not (own or review_target):
                    if write_all or Path(relative).name not in {
                        "review.md",
                        "review-handoff.md",
                    }:
                        deny_reason = f"返工任务只能读评审输出: {relative}"
                        continue
                if write_all and not _contract_process_write(relative):
                    deny_reason = f"worker Bash 只能写任务 bundle 流程文件: {relative}"
                    continue
                if (
                    read_like
                    and path.is_file()
                    and path.stat().st_size > max_bytes
                ):
                    deny_reason = (
                        f"{path.name} 超过 worker 读预算 {max_bytes}B；"
                        "请用 mf context expand <path> --reason packet_missing"
                    )
                continue
        if role == "designer":
            if write_all:
                deny_reason = (
                    "designer 只能写 contract 设计区；不能写子项目源码/交付库"
                )
                continue
            if read_like and path.is_file() and path.stat().st_size > max_bytes:
                deny_reason = (
                    f"{path.name} 超过 designer 读预算 {max_bytes}B；"
                    "请用 mf context expand <path> --reason packet_missing"
                )
            continue
        if role == "worker":
            if role_root is None:
                if workspace_root is not None and path.is_relative_to(workspace_root):
                    deny_reason = "worker 无交付根绑定；请从交付库目录运行"
                continue
            if path.is_relative_to(role_root):
                relative = path.relative_to(role_root).as_posix()
                if write_all and not _delivery_write_allowed(relative, tasks):
                    deny_reason = f"worker Bash 写入不在任务 allowed_paths 内: {relative}"
                    continue
                reviewed = _review_scope_match(relative, tasks)
                if (
                    read_like
                    and reviewed is None
                    and path.is_file()
                    and path.stat().st_size > max_bytes
                ):
                    deny_reason = (
                        f"{path.name} 超过 worker 读预算 {max_bytes}B；"
                        "请用 mf context expand <path> --reason packet_missing"
                    )
                continue
            if workspace_root is not None and path.is_relative_to(workspace_root):
                if _cross_project_write_denied(path, tasks, workspace_root):
                    deny_reason = (
                        "cross_subproject 任务对声明子项目只读/测试，写拒绝: "
                        f"{path}"
                    )
                elif not write_all and _cross_project_read_allowed(
                    path, tasks, workspace_root
                ):
                    continue
                else:
                    deny_reason = "worker 不读/写其他交付库或工作区"
            continue
        if role == "manager":
            if _manager_source_denied(path, workspace_root):
                deny_reason = "manager 不直接读交付库源码"
            continue
        if role == "maintainer":
            continue

    _audit_guard(
        contract,
        role=role,
        task=audit_task,
        tool="Bash",
        decision="deny" if deny_reason else "allow",
        paths=audit_paths,
        reason=deny_reason,
        command=command,
        parsed=parsed_paths,
        unsafe=unsafe,
    )
    if deny_reason is not None:
        return _deny_with_hint(
            deny_reason, contract=contract, role=role, role_root=role_root
        )
    return None


def pretool_decision(payload: dict[str, Any]) -> dict[str, Any] | None:
    tool = str(payload.get("tool_name") or "")
    cwd = Path(str(payload.get("cwd") or os.getcwd())).expanduser().resolve()
    if tool == "Bash":
        return _bash_decision(payload, cwd)
    if tool not in READ_TOOLS | WRITE_TOOLS:
        return None
    path = _hook_path(payload, cwd)
    if path is None:
        return None
    role, role_root = _resolve_role(cwd, payload.get("session_id"))
    if role == "unbound":
        return None
    try:
        contract = resolve_contract(role_root or cwd)
    except Exception:
        contract = None
    workspace_root = find_workspace_root(role_root or cwd)
    if contract is None:
        if role in {"worker", "designer", "manager"}:
            return _deny_with_hint(
                "无法解析 contract/工作区绑定（install.yaml 的 workspace_root 缺失、"
                "目录不在工作区或绑定不一致）；guard fail-closed，拒绝工具调用。"
                "请从工作区根/子项目目录运行；子项目绑定漂移由 manager 运行 "
                "mf install worker --workspace-root <根> --contract-dir <contract> 修复",
                contract=None,
                role=role,
                role_root=role_root,
            )
        return None
    delivery = _worker_delivery(role_root) if role == "worker" else None
    tasks: list[dict[str, Any]] = []
    if role == "worker" and delivery:
        tasks = _active_tasks(contract, delivery)
    elif role == "designer":
        tasks = _designer_tasks(contract)
    audit_task = str(tasks[0].get("id")) if tasks else "无"

    def display(item: Path) -> str:
        try:
            return item.relative_to(contract).as_posix()
        except ValueError:
            return str(item)

    def audit(decision: str, reason: str | None = None) -> None:
        _audit_guard(
            contract,
            role=role,
            task=audit_task,
            tool=tool,
            decision=decision,
            path=display(path),
            reason=reason,
        )

    def allow() -> None:
        audit("allow")
        return None

    def deny(reason: str) -> dict[str, Any]:
        audit("deny", reason)
        return _deny_with_hint(
            reason, contract=contract, role=role, role_root=role_root
        )

    if tool in READ_TOOLS and path.is_file():
        max_bytes = _read_budget(contract, role)
        exempt = False
        if role == "worker":
            if path.is_relative_to(contract):
                relative = path.relative_to(contract).as_posix()
                if (
                    _bundle_match(relative, tasks) is not None
                    or _review_target_match(relative, tasks) is not None
                    or _review_output_match(relative, tasks) is not None
                ):
                    exempt = True
            elif role_root is not None and path.is_relative_to(role_root):
                exempt = (
                    _review_scope_match(path.relative_to(role_root).as_posix(), tasks)
                    is not None
                )
        if not exempt and path.stat().st_size > max_bytes:
            return deny(
                f"{path.name} 超过 {role} 读预算 {max_bytes}B；"
                "请用 mf context expand <path> --reason packet_missing 分段读取"
            )

    if tool in WRITE_TOOLS:
        if _is_anchor_path(path):
            return deny(
                "会话角色锚点只能由 SessionStart 或用户终端 mf role --as 写入"
            )
        if path.is_relative_to(contract):
            relative = path.relative_to(contract).as_posix()
            if relative.startswith("archive/"):
                return deny("archive 只读；写入请通过版本关闭流程")
            if relative.startswith("state/"):
                return deny("state 由 mf 派生写入，禁止直接改")
            if role == "maintainer":
                return deny("maintainer 不改项目契约")
            if role == "designer":
                if relative.startswith("archive/"):
                    return deny("archive 只读；designer 不直接写归档")
                if _designer_contract_write(relative):
                    return allow()
                if (
                    _bundle_match(relative, tasks) is not None
                    and _contract_process_write(relative)
                ):
                    return allow()
                return deny(
                    "designer 只能写 contract 设计区/本任务流程文件；"
                    "角色切换请在用户终端运行 mf role --as <role> --reason <原因>"
                )
            if role == "worker":
                if role_root is None:
                    return deny(
                        "worker 无交付根绑定；请从交付库目录运行，"
                        "或在 CLI 任务命令中使用 --project-dir 指定交付库"
                    )
                if not delivery:
                    return deny(
                        f"交付库缺少 delivery.yaml，无法确定任务作用域: {role_root}"
                    )
                task = _bundle_match(relative, tasks)
                if task is None:
                    return deny(
                        "worker 只能写自己 in_progress 任务的 bundle；"
                        "提交后不可编辑；review NEEDS_REWORK 后用 mf task rework <id> 开始，"
                        "不要用 mf task start"
                    )
                allowed = [
                    "dev-record.md",
                    "handoff.md",
                    "review.md",
                    "review-handoff.md",
                    "evidence/",
                ]
                if not any(f"/{value}" in f"/{relative}" for value in allowed):
                    return deny("worker 不能写契约基线或其他任务")
                return allow()
            if role == "manager":
                if _manager_source_denied(path, workspace_root):
                    return deny("manager 不直接改交付库源码")
                return allow()
            return deny("当前角色不能写契约库")
        if role == "designer":
            return deny(
                "designer 只能写 contract 设计区（architecture/specs/P2）；"
                "不能写子项目源码或交付库"
            )
        if role == "worker":
            root = role_root
            if root is None:
                return deny(
                    "worker 无交付根绑定；请从交付库目录运行，"
                    "或在 CLI 任务命令中使用 --project-dir 指定交付库"
                )
            if not delivery:
                return deny(f"交付库缺少 delivery.yaml，无法确定任务作用域: {root}")
            if path.is_relative_to(root):
                relative = path.relative_to(root).as_posix()
                for task in tasks:
                    if _matches(
                        relative, [str(item) for item in task.get("forbidden") or []]
                    ):
                        return deny(f"路径在任务 forbidden 内: {relative}")
                # R10/MFP-0025/MFP-0030：本地 MFP、当前任务本地副本与
                # 构建产物（gitignored 运行时目录）是受控 write 白名单，
                # 带审计；其余仍只允许 allowed_paths。
                if _delivery_write_allowed(relative, tasks):
                    return allow()
                return deny(
                    "worker 写入不在当前任务 allowed_paths 内；提交后不可编辑；"
                    "review NEEDS_REWORK 自动回流后用 mf task rework <id> 开始；"
                    "本地 MFP 可写 .meta-flow/improvements/MFP-*.yaml"
                )
            if _cross_project_write_denied(path, tasks, workspace_root):
                return deny(
                    "cross_subproject 任务对声明子项目只读/测试；写入一律拒绝"
                )
            return deny("worker 只能写自己的交付库")
        if role == "manager":
            if _manager_source_denied(path, workspace_root):
                return deny("manager 不直接改交付库源码")
            return allow()
        if role == "maintainer":
            global_root = Path(
                os.environ.get("META_FLOW_HOME", Path.home() / ".meta-flow")
            ).resolve()
            if path.is_relative_to(global_root):
                return allow()
            # MFP-0037：maintainer 需要维护 manifest.source_dir 指向的工具源码仓库
            if any(path.is_relative_to(root) for root in _maintainer_source_roots()):
                return allow()
            return deny("maintainer 只维护 meta-flow 源码/全局模板")
        return allow()

    # Read / Grep / Glob
    if path.is_relative_to(contract):
        relative = path.relative_to(contract).as_posix()
        if role == "manager":
            if relative.startswith("archive/"):
                return deny("archive 只允许通过 mf archive show --reason 读取")
            return allow()
        if role == "worker":
            if relative == "state/current.json":
                return allow()
            if role_root is None:
                return deny(
                    "worker 无交付根绑定；请从交付库目录运行，"
                    "或在 CLI 任务命令中使用 --project-dir 指定交付库"
                )
            if not delivery:
                return deny(
                    f"交付库缺少 delivery.yaml，无法确定任务作用域: {role_root}"
                )
            if _bundle_match(relative, tasks) is not None:
                return allow()
            if _review_target_match(relative, tasks) is not None:
                return allow()
            review_output = _review_output_match(relative, tasks)
            if review_output is not None and Path(relative).name in {
                "review.md",
                "review-handoff.md",
            }:
                return allow()
            return deny(
                "worker 只能读任务包/自己的 bundle、评审目标或返工评审输出"
            )
        if role == "designer":
            if relative.startswith("archive/"):
                return deny("archive 只允许通过 mf archive show --reason 读取")
            return allow()
        if role == "maintainer":
            if relative.startswith(("workspace/", ".meta-flow/")):
                return allow()
            return deny("maintainer 不读项目需求/设计/任务内容")
        return allow()
    if role == "worker":
        root = role_root
        if root is None:
            return deny(
                "worker 无交付根绑定；请从交付库目录运行，"
                "或在 CLI 任务命令中使用 --project-dir 指定交付库"
            )
        if not delivery:
            return deny(f"交付库缺少 delivery.yaml，无法确定任务作用域: {root}")
        if path.is_relative_to(root):
            return allow()
        if _cross_project_read_allowed(path, tasks, workspace_root):
            return allow()
        return deny("worker 不读其他交付库")
    if role == "manager":
        if _manager_source_denied(path, workspace_root):
            return deny("manager 不直接读交付库源码")
        return allow()
    if role == "maintainer":
        return allow()
    return allow()


def run_hook() -> int:
    import sys

    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    if not isinstance(payload, dict):
        return 0
    decision = pretool_decision(payload)
    if decision:
        print(json.dumps(decision, ensure_ascii=False))
    return 0
