"""热区上下文、读扩展审计与归档查询。"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from .state import read_current, tail_lines
from .workspace import detect_role, resolve_contract

REASONS = (
    "packet_missing",
    "field_conflict",
    "schema_validation_failed",
    "human_audit",
    "summary_insufficient",
)
MAX_READ_BYTES = 256 * 1024


class ContextError(Exception):
    """上下文/归档操作失败。"""

    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _actor(actor: str | None) -> tuple[str, str]:
    if actor:
        return actor, actor
    env_role = os.environ.get("MF_ROLE")
    if env_role in {"manager", "designer", "worker", "maintainer"}:
        return env_role, env_role
    role, _ = detect_role(Path.cwd())
    if role == "unbound":
        role = "manager"
    return role, role


def _log(contract: Path, event: dict[str, Any]) -> None:
    path = contract / "state" / "READ-LOG.ndjson"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"ts": _now(), **event}, ensure_ascii=False) + "\n")


def _worker_delivery(root: Path | None) -> str | None:
    if root is None:
        return None
    path = root / "delivery.yaml"
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return None
    return str(data.get("id")) if isinstance(data, dict) and data.get("id") else None


def _current_roadmap(contract: Path) -> str:
    path = contract / "state" / "current.json"
    if not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ""
    return str(data.get("roadmap") or "") if isinstance(data, dict) else ""


def _in_progress_tasks(contract: Path, delivery: str | None) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    current = _current_roadmap(contract)
    for path in sorted((contract / "roadmap").glob("*/phases/*/tasks/T*/TASK.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (yaml.YAMLError, OSError):
            continue
        if not isinstance(data, dict) or data.get("status") != "in_progress":
            continue
        # 版本隔离：worker 只读当前 R；旧 R 在途任务不再进入 expand 白名单。
        if current and str(data.get("roadmap") or "") and str(data.get("roadmap")) != current:
            continue
        if delivery and data.get("delivery") != delivery:
            continue
        data["_bundle"] = path.parent
        tasks.append(data)
    return tasks


def _task_bundle_prefix(task: dict[str, Any]) -> str:
    task_id = str(task.get("id") or "")
    parts = task_id.split("-")
    if len(parts) == 3 and parts[0] and parts[1] and parts[2]:
        return f"roadmap/{parts[0]}/phases/{parts[1]}/tasks/{parts[2]}/"
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


def _bundle_allowed(relative: str, tasks: list[dict[str, Any]]) -> bool:
    for task in tasks:
        if _path_in_prefix(relative, _task_bundle_prefix(task)):
            return True
    return False


def _review_target_allowed(relative: str, tasks: list[dict[str, Any]]) -> bool:
    for task in tasks:
        if task.get("kind") != "review":
            continue
        target = str(task.get("reviews") or "")
        if _path_in_prefix(relative, _id_bundle_prefix(target)):
            return True
    return False


def _review_output_allowed(relative: str, tasks: list[dict[str, Any]]) -> bool:
    if Path(relative).name not in {"review.md", "review-handoff.md"}:
        return False
    for task in tasks:
        if task.get("kind") == "review":
            continue
        review_task = str(task.get("reviewed_by_task") or "")
        if _path_in_prefix(relative, _id_bundle_prefix(review_task)):
            return True
    return False


def _task_scope_paths(task: dict[str, Any]) -> list[str]:
    paths = [str(item) for item in task.get("allowed_paths") or []]
    if task.get("kind") == "review":
        paths.extend(str(item) for item in (task.get("review") or {}).get("scope") or [])
    return paths


def _scope_allowed(relative: str, tasks: list[dict[str, Any]]) -> bool:
    from .task import _matches  # 延迟导入，避免模块级循环

    for task in tasks:
        if _matches(relative, _task_scope_paths(task)):
            return True
    return False


def _must_read_allowed(
    relative: str, tasks: list[dict[str, Any]], contract: Path
) -> bool:
    """worker 可展开活动任务 packet 声明的 must_read 契约基线（MFP-0025）。

    packet 的 must_read = TASK.yaml + inputs 引用；inputs 引用用与 packet
    相同的 `_find_input` 解析，保证 expand 白名单与任务包一致。
    """
    from .task import _find_input  # 延迟导入，避免模块级循环

    for task in tasks:
        prefix = _task_bundle_prefix(task)
        if prefix and _path_in_prefix(relative, prefix):
            return True
        inputs = task.get("inputs") or {}
        if not isinstance(inputs, dict):
            continue
        refs: list[str] = []
        for value in inputs.values():
            if isinstance(value, list):
                refs.extend(str(item) for item in value if item)
            elif value:
                refs.append(str(value))
        for ref in refs:
            found = _find_input(contract, ref)
            if found is None:
                continue
            try:
                if found[0].resolve() == (contract / relative).resolve():
                    return True
            except OSError:
                continue
    return False


def _resolve_expand_target(
    project_path: Path, contract: Path, relative_path: str
) -> tuple[Path, str]:
    raw = Path(str(relative_path)).expanduser()
    if raw.is_absolute():
        target = raw.resolve()
    else:
        contract_candidate = (contract / raw).resolve()
        project_candidate = (project_path / raw).resolve()
        if contract_candidate.exists() and contract_candidate.is_relative_to(contract):
            target = contract_candidate
        elif project_candidate.exists() and project_candidate.is_relative_to(project_path):
            target = project_candidate
        else:
            target = contract_candidate
    if target.is_relative_to(contract):
        return target, target.relative_to(contract).as_posix()
    if target.is_relative_to(project_path):
        return target, "delivery:" + target.relative_to(project_path).as_posix()
    raise ContextError(f"只能读取 contract 或当前交付库内文件: {target}")


def expand(
    project: str | Path,
    relative_path: str,
    *,
    reason: str,
    actor: str | None = None,
    start: int | None = None,
    end: int | None = None,
    max_bytes: int | None = None,
) -> dict[str, Any]:
    project_path = Path(project).expanduser().resolve()
    contract = resolve_contract(project_path)
    if reason not in REASONS:
        raise ContextError(f"reason 只能是 {'|'.join(REASONS)}")
    for name, value in (("start", start), ("end", end), ("max_bytes", max_bytes)):
        if value is not None and (not isinstance(value, int) or value < 0):
            raise ContextError(f"--{name.replace('_', '-')} 必须是非负整数")
    role, actor_id = _actor(actor)
    worker_root: Path | None = None
    tasks: list[dict[str, Any]] = []
    if role == "worker":
        detected, detected_root = detect_role(project_path)
        if detected != "worker" or detected_root is None:
            raise ContextError(
                "worker 无交付根绑定；请用 --project-dir 指定交付库，或从交付库运行"
            )
        worker_root = detected_root
        delivery = _worker_delivery(worker_root)
        if not delivery:
            raise ContextError(f"交付库缺少 delivery.yaml，无法确定作用域: {worker_root}")
        tasks = _in_progress_tasks(contract, delivery)
    target, display = _resolve_expand_target(project_path, contract, relative_path)
    if target.is_relative_to(contract):
        relative = target.relative_to(contract).as_posix()
        if relative.startswith("archive/") and role != "maintainer":
            raise ContextError(
                "archive 默认 deny：仅 maintainer root 可直接读取；"
                "manager/designer 需用户 grant 后用 mf archive show/export"
            )
        if role == "worker":
            if not (
                _bundle_allowed(relative, tasks)
                or _review_target_allowed(relative, tasks)
                or _review_output_allowed(relative, tasks)
                or _must_read_allowed(relative, tasks, contract)
            ):
                raise ContextError(
                    "worker 只能展开自己的任务 bundle、评审任务的目标 bundle、"
                    "返工任务的评审输出或任务包 must_read 契约基线；不能直接 expand 契约基线"
                )
        elif role == "maintainer":
            # DP-ROLE-01：maintainer root 不受 context 读边界限制（非阻断审计）。
            pass
    else:
        if role != "worker":
            raise ContextError("只有 worker 可以展开交付库文件")
        if worker_root is None or not target.is_relative_to(worker_root):
            raise ContextError("worker 只能展开自己交付库内文件")
        relative = target.relative_to(worker_root).as_posix()
        if not _scope_allowed(relative, tasks):
            raise ContextError(
                f"交付库文件不在活动任务 allowed_paths/review_scope 内: {relative}"
            )
    if not target.is_file():
        raise ContextError(f"文件不存在: {target}")
    size = target.stat().st_size
    if end is not None and end > size:
        raise ContextError(
            f"--end {end} 超出文件大小 {size}；请先用 --start/--end 分段读取"
        )
    if start is not None and end is not None and end < start:
        raise ContextError(f"--end {end} 不能小于 --start {start}")
    if max_bytes is not None and max_bytes <= 0:
        raise ContextError("--max-bytes 必须大于 0")
    segmented = start is not None or end is not None or max_bytes is not None
    if not segmented and size > MAX_READ_BYTES:
        raise ContextError(
            f"文件 {size} 字节超过 expand 上限 {MAX_READ_BYTES}；"
            "请用 --start/--end 或 --max-bytes 分段读取"
        )
    begin = start or 0
    if end is not None:
        finish = end
    elif max_bytes is not None:
        finish = min(size, begin + max_bytes)
    else:
        finish = size
    if max_bytes is not None and finish - begin > max_bytes:
        raise ContextError(
            f"请求区间 {begin}..{finish} 共 {finish - begin} 字节，超过 --max-bytes {max_bytes}；"
            "请缩小区间"
        )
    if begin > size:
        raise ContextError(f"--start {begin} 超出文件大小 {size}")
    data = target.read_bytes()
    raw = data[begin:finish]
    # 避免在 UTF-8 多字节字符中间切断：截掉尾部无法解码的字节。
    while raw:
        try:
            text = raw.decode("utf-8")
            break
        except UnicodeDecodeError as exc:
            if exc.reason != "unexpected end of data" or not raw:
                raise ContextError(
                    f"分段边界落在非 UTF-8 字节处（start={begin}, end={finish}）；"
                    "请调整 --start/--end"
                ) from exc
            raw = raw[:-1]
            finish -= 1
    if not raw:
        text = ""
    _log(
        contract,
        {
            "event": "context.expand",
            "actor": actor_id,
            "role": role,
            "path": display,
            "reason": reason,
            "bytes": size,
            "start": begin,
            "end": finish,
            "max_bytes": max_bytes,
            "segmented": segmented,
            "allowed": True,
        },
    )
    return {
        "path": display,
        "reason": reason,
        "bytes": size,
        "total_bytes": size,
        "start": begin,
        "end": finish,
        "segmented": segmented,
        "duration": None,
        "text": text,
    }


def hot_files(project: str | Path) -> dict[str, Any]:
    project_path = Path(project).expanduser().resolve()
    contract = resolve_contract(project_path)
    state = read_current(contract)
    role, detected_root = detect_role(project_path)
    if role == "unbound":
        role, _ = _actor(None)
    if role == "worker":
        # worker 的“热区”是活动任务 bundle，不暴露契约基线
        delivery = _worker_delivery(detected_root)
        if detected_root is None or not delivery:
            raise ContextError("worker 无交付根绑定；请用 --project-dir 指定交付库")
        tasks = _in_progress_tasks(contract, delivery)
        files = []
        total_bytes = 0
        for task in tasks:
            bundle = Path(str(task.get("_bundle") or ""))
            for path in sorted(bundle.rglob("*")):
                if not path.is_file():
                    continue
                relative = path.relative_to(contract).as_posix()
                size = path.stat().st_size
                total_bytes += size
                files.append({"path": relative, "exists": True, "bytes": size})
        policy_data = policy(contract)
        budget = ((policy_data.get("roles") or {}).get("worker") or {}).get("budget") or {
            "files": 10,
            "bytes": 65536,
        }
        return {
            "roadmap": str(state.get("roadmap") or "R1"),
            "phase": str(state.get("phase") or "P1"),
            "phase_status": state.get("phase_status"),
            "scope": "task-bundle",
            "files": files,
            "total_bytes": total_bytes,
            "budget": budget,
            "within_budget": total_bytes <= int(budget.get("bytes") or 65536),
        }
    roadmap_id = str(state.get("roadmap") or "R1")
    phase = str(state.get("phase") or "P1")
    previous = None
    if phase in {"P2", "P3", "P4", "P5"}:
        previous = f"P{int(phase[1:]) - 1}"
    candidates = [
        "state/current.json",
        "project/PROJECT-PLAN.md",
        "roadmap/ROADMAP.yaml",
        f"roadmap/{roadmap_id}/PLAN.md",
        "requirements/INDEX.md",
        "architecture/INDEX.md",
        "knowledge/KNOWLEDGE.md",
        "policies/CONTEXT-POLICY.yaml",
        f"roadmap/{roadmap_id}/phases/{phase}/PLAN.md",
        f"roadmap/{roadmap_id}/phases/{phase}/REPORT.md",
    ]
    if previous:
        candidates.append(f"roadmap/{roadmap_id}/phases/{previous}/HANDOFF-TO-{phase}.md")
    files = []
    total_bytes = 0
    for relative in candidates:
        path = contract / relative
        size = path.stat().st_size if path.is_file() else 0
        total_bytes += size
        files.append({"path": relative, "exists": path.is_file(), "bytes": size})
    policy_data = policy(contract)
    budget = ((policy_data.get("roles") or {}).get("manager") or {}).get("budget") or {
        "files": 12,
        "bytes": 131072,
    }
    return {
        "roadmap": roadmap_id,
        "phase": phase,
        "phase_status": state.get("phase_status"),
        "files": files,
        "total_bytes": total_bytes,
        "budget": budget,
        "within_budget": total_bytes <= int(budget.get("bytes") or 131072),
    }


def _archive_dirs(contract: Path) -> list[Path]:
    root = contract / "archive"
    if not root.is_dir():
        return []
    return sorted(path for path in root.iterdir() if path.is_dir())


ARCHIVE_PURPOSES = (
    "design_input",
    "human_audit",
    "field_conflict",
    "schema_validation_failed",
    "summary_insufficient",
)
ARCHIVE_GRANT_ROLES = ("manager", "designer")


def _parse_iso(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _ledger_events(contract: Path) -> list[dict[str, Any]]:
    path = contract / "state" / "ledger.ndjson"
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    events: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            events.append(data)
    return events


def _archive_grants(contract: Path) -> dict[str, dict[str, Any]]:
    """从 ledger 派生 grant 真相（state/archive-grants.json 只是缓存）。"""
    grants: dict[str, dict[str, Any]] = {}
    for event in _ledger_events(contract):
        name = str(event.get("event") or "")
        grant_id = str(event.get("grant_id") or "")
        if not grant_id:
            continue
        if name == "archive.authorize":
            grants[grant_id] = dict(event)
        elif name == "archive.revoke" and grant_id in grants:
            grants[grant_id]["revoked_at"] = str(event.get("ts") or _now())
            grants[grant_id]["revoked_by"] = str(event.get("actor") or "user")
        elif name in {"archive.read", "archive.export"} and grant_id in grants:
            grant = grants[grant_id]
            grant["used_bytes"] = int(grant.get("used_bytes") or 0) + int(
                event.get("bytes") or 0
            )
            grant["used_files"] = int(grant.get("used_files") or 0) + int(
                event.get("files") or 0
            )
            if name in {"archive.read", "archive.export"} and grant.get("one_shot"):
                grant["consumed"] = True
    return grants


def _scope_matches(relative: str, scope: list[str]) -> bool:
    rel = relative.replace("\\", "/").lstrip("/")
    for pattern in scope:
        pat = str(pattern).replace("\\", "/").lstrip("/")
        if not pat:
            continue
        if fnmatch.fnmatch(rel, pat) or rel == pat.rstrip("/") or rel.startswith(
            pat.rstrip("/") + "/"
        ):
            return True
    return False


def _valid_grant(
    contract: Path,
    *,
    role: str,
    roadmap: str,
    grant_id: str | None = None,
    purpose: str | None = None,
) -> dict[str, Any] | None:
    grants = _archive_grants(contract)
    now = datetime.now(UTC)
    candidates = (
        [grants[grant_id]] if grant_id and grant_id in grants else list(grants.values())
    )
    for grant in candidates:
        if str(grant.get("approved_by")) != "user":
            continue
        if str(grant.get("role")) != role:
            continue
        if str(grant.get("roadmap")) != roadmap:
            continue
        if purpose and str(grant.get("purpose")) != purpose:
            continue
        if grant.get("revoked_at"):
            continue
        expires = _parse_iso(grant.get("expires_at"))
        if expires is None or expires <= now:
            continue
        if grant.get("one_shot") and grant.get("consumed"):
            continue
        if int(grant.get("used_bytes") or 0) >= int(grant.get("max_bytes") or 0):
            continue
        if int(grant.get("used_files") or 0) >= int(grant.get("max_files") or 0):
            continue
        return grant
    return None


def authorize_archive(
    project: str | Path,
    *,
    role: str,
    roadmap: str,
    scope: list[str],
    purpose: str,
    ttl_minutes: int = 30,
    max_bytes: int = 262144,
    max_files: int = 50,
    one_shot: bool = True,
    tty: bool | None = None,
    stream: Any | None = None,
    out: Any | None = None,
) -> dict[str, Any]:
    """用户 TTY 显式授权 manager/designer 读取 archive（DP-SEC-ARCH-01）。"""
    from . import roles

    contract = resolve_contract(project)
    if role not in ARCHIVE_GRANT_ROLES:
        raise ContextError("archive grant 只允许 manager/designer（worker 不得申请）")
    if purpose not in ARCHIVE_PURPOSES:
        raise ContextError(f"purpose 只能是 {'|'.join(ARCHIVE_PURPOSES)}")
    if not re.fullmatch(r"R\d+", str(roadmap or "")):
        raise ContextError("roadmap 必须形如 R0/R1")
    if not scope or not all(str(item).strip() for item in scope):
        raise ContextError("scope 至少一个路径/glob")
    for item in scope:
        raw = str(item)
        if raw.startswith(("/", "~")) or ".." in Path(raw).parts:
            raise ContextError(f"scope 不能是绝对路径或包含 ..: {raw}")
    if ttl_minutes <= 0 or ttl_minutes > 120:
        raise ContextError("ttl_minutes 必须在 1..120 之间")
    if max_bytes <= 0 or max_files <= 0:
        raise ContextError("max_bytes/max_files 必须大于 0")
    if tty is None:
        tty = roles.is_tty(stream, out)
    if not tty:
        raise ContextError(
            "archive 授权只能由用户在终端执行（非 TTY 拒绝）："
            "mf archive authorize --role <manager|designer> --roadmap <R> ...",
            3,
        )
    now = datetime.now(UTC)
    grant_id = f"ARC-{uuid.uuid4().hex[:12]}"
    grant = {
        "grant_id": grant_id,
        "approved_by": "user",
        "approved_at": now.isoformat(),
        "role": role,
        "roadmap": roadmap,
        "scope": [str(item) for item in scope],
        "purpose": purpose,
        "expires_at": (now + timedelta(minutes=ttl_minutes)).isoformat(),
        "max_bytes": int(max_bytes),
        "max_files": int(max_files),
        "one_shot": bool(one_shot),
        "created_by_session": roles.current_session_id(),
    }
    _ledger_append(contract, {"event": "archive.authorize", **grant})
    _write_grant_cache(contract)
    return grant


def revoke_archive(
    project: str | Path,
    grant_id: str,
    *,
    tty: bool | None = None,
    stream: Any | None = None,
    out: Any | None = None,
) -> dict[str, Any]:
    from . import roles

    contract = resolve_contract(project)
    if grant_id not in _archive_grants(contract):
        raise ContextError(f"grant 不存在: {grant_id}")
    if tty is None:
        tty = roles.is_tty(stream, out)
    if not tty:
        raise ContextError("archive 授权撤销只能由用户在终端执行（非 TTY 拒绝）", 3)
    _ledger_append(
        contract,
        {"event": "archive.revoke", "grant_id": grant_id, "approved_by": "user"},
    )
    _write_grant_cache(contract)
    return {"grant_id": grant_id, "revoked": True}


def _ledger_append(contract: Path, event: dict[str, Any]) -> None:
    from .state import ledger_append

    ledger_append(contract, event)


def _write_grant_cache(contract: Path) -> None:
    """派生缓存；真相在 ledger（DP-SEC-ARCH-01 §5.1）。"""
    path = contract / "state" / "archive-grants.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    grants = _archive_grants(contract)
    path.write_text(
        json.dumps({"schema": 1, "grants": grants}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _archive_scope_files(
    directory: Path, scope: list[str]
) -> list[Path]:
    files: list[Path] = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(directory).as_posix()
        if _scope_matches(relative, scope):
            files.append(path)
    return files


def archive_list(
    project: str | Path,
    *,
    actor: str | None = None,
) -> list[dict[str, Any]]:
    contract = resolve_contract(project)
    role, _ = _actor(actor)
    if role == "worker":
        raise ContextError("worker 不得读取 archive")
    grants = _archive_grants(contract) if role in ARCHIVE_GRANT_ROLES else {}
    now = datetime.now(UTC)
    items = []
    for directory in _archive_dirs(contract):
        roadmap = directory.name
        scope_grant = next(
            (
                grant
                for grant in grants.values()
                if str(grant.get("role")) == role
                and str(grant.get("roadmap")) == roadmap
                and not grant.get("revoked_at")
                and not (grant.get("one_shot") and grant.get("consumed"))
                and (_parse_iso(grant.get("expires_at")) or now) > now
            ),
            None,
        )
        if role in ARCHIVE_GRANT_ROLES and scope_grant is None:
            continue
        files = (
            _archive_scope_files(directory, [str(item) for item in scope_grant["scope"]])
            if scope_grant is not None
            else [path for path in directory.rglob("*") if path.is_file()]
        )
        index = directory / "INDEX.md"
        items.append(
            {
                "roadmap": roadmap,
                "path": str(directory.relative_to(contract)),
                "index": str(index.relative_to(contract)) if index.is_file() else None,
                "files": len(files),
                "grant_id": scope_grant.get("grant_id") if scope_grant else None,
            }
        )
    return items


def archive_show(
    project: str | Path,
    roadmap_id: str,
    *,
    reason: str,
    actor: str | None = None,
    grant_id: str | None = None,
    path: str | None = None,
) -> dict[str, Any]:
    contract = resolve_contract(project)
    if reason not in REASONS:
        raise ContextError(f"reason 只能是 {'|'.join(REASONS)}")
    role, actor_id = _actor(actor)
    if role == "worker":
        raise ContextError("worker 不得读取 archive")
    directory = (contract / "archive" / roadmap_id).resolve()
    if not directory.is_dir() or not directory.is_relative_to(contract / "archive"):
        raise ContextError(f"归档不存在: {roadmap_id}")
    grant: dict[str, Any] | None = None
    scope: list[str] | None = None
    if role in ARCHIVE_GRANT_ROLES:
        grant = _valid_grant(
            contract, role=role, roadmap=roadmap_id, grant_id=grant_id, purpose=reason
        )
        if grant is None:
            raise ContextError(
                "archive 默认 deny：需要用户在终端授权后读取 "
                "（mf archive authorize --role <role> --roadmap <R> --scope <path> "
                f"--purpose {reason}）；grant 不存在/过期/越 scope/已撤销",
                2,
            )
        scope = [str(item) for item in grant.get("scope") or []]
    elif role != "maintainer":
        raise ContextError("archive 只允许 manager/designer（有 grant）或 maintainer")
    if path:
        target = (directory / path).resolve()
        if not target.is_relative_to(directory) or not target.is_file():
            raise ContextError(f"归档路径不存在或越界: {path}")
        if scope is not None and not _scope_matches(
            target.relative_to(directory).as_posix(), scope
        ):
            raise ContextError(f"路径不在 grant scope 内: {path}")
        files = [target]
    else:
        files = (
            _archive_scope_files(directory, scope)
            if scope is not None
            else [item for item in sorted(directory.rglob("*")) if item.is_file()]
        )
        if not files and scope is not None:
            raise ContextError("grant scope 内没有可读文件")
    total_bytes = sum(item.stat().st_size for item in files)
    if grant is not None:
        max_bytes = int(grant.get("max_bytes") or 0)
        max_files = int(grant.get("max_files") or 0)
        if total_bytes > max_bytes or len(files) > max_files:
            raise ContextError(
                f"grant 超限：请求 {len(files)} 文件/{total_bytes}B，"
                f"上限 {max_files} 文件/{max_bytes}B"
            )
    index = directory / "INDEX.md"
    text = index.read_text(encoding="utf-8") if index.is_file() else ""
    files_view = [
        str(item.relative_to(directory)) for item in files if item.name != "INDEX.md"
    ]
    _ledger_append(
        contract,
        {
            "event": "archive.read",
            "actor": actor_id,
            "role": role,
            "grant_id": grant.get("grant_id") if grant else None,
            "path": str(directory.relative_to(contract)),
            "reason": reason,
            "files": len(files_view),
            "bytes": total_bytes,
        },
    )
    _log(
        contract,
        {
            "event": "archive.read",
            "actor": actor_id,
            "role": role,
            "grant_id": grant.get("grant_id") if grant else None,
            "path": str(directory.relative_to(contract)),
            "reason": reason,
            "bytes": total_bytes,
            "allowed": True,
        },
    )
    if grant is not None:
        _write_grant_cache(contract)
    return {
        "roadmap": roadmap_id,
        "path": str(directory.relative_to(contract)),
        "reason": reason,
        "files": files_view,
        "bytes": total_bytes,
        "index": text,
        "grant_id": grant.get("grant_id") if grant else None,
    }


def archive_export(
    project: str | Path,
    *,
    grant_id: str | None = None,
    roadmap: str | None = None,
    to: str,
    actor: str | None = None,
) -> dict[str, Any]:
    """按 grant 导出归档副本到 contract 内 inputs/ 白名单目录（带 digest）。

    maintainer root 可不带 grant（用 --roadmap 指明来源，仍写 ledger/digest）；
    manager/designer 必须持有效 grant。
    """
    contract = resolve_contract(project)
    role, actor_id = _actor(actor)
    if role not in ARCHIVE_GRANT_ROLES and role != "maintainer":
        raise ContextError("archive export 只允许 manager/designer（有 grant）或 maintainer")
    target_dir = (contract / to).resolve()
    rel_target = (
        target_dir.relative_to(contract).as_posix()
        if target_dir.is_relative_to(contract)
        else ""
    )
    if not rel_target or ".." in Path(to).parts or Path(to).is_absolute():
        raise ContextError("导出目标必须是 contract 内相对目录")
    parts = rel_target.split("/")
    if "inputs" not in parts:
        raise ContextError("导出目标必须在 inputs/ 目录内（如 roadmap/R1/inputs/）")
    if rel_target.startswith(("archive/", "state/")):
        raise ContextError("不能导出到 archive/state")
    now = datetime.now(UTC)
    grant: dict[str, Any] | None = None
    if grant_id:
        grants = {
            str(item.get("grant_id")): item
            for item in _archive_grants(contract).values()
        }
        grant = grants.get(grant_id)
        if grant is None:
            raise ContextError(f"grant 不存在: {grant_id}")
        expires = _parse_iso(grant.get("expires_at"))
        if (
            grant.get("revoked_at")
            or expires is None
            or expires <= now
            or (grant.get("one_shot") and grant.get("consumed"))
        ):
            raise ContextError("grant 已过期/撤销/已消费")
        if role != "maintainer" and str(grant.get("role")) != role:
            raise ContextError("grant role 与当前角色不一致")
        roadmap = str(grant.get("roadmap") or "")
    else:
        if role != "maintainer":
            raise ContextError("archive export 需要 --grant（maintainer root 可用 --roadmap）")
        if not roadmap:
            raise ContextError("maintainer 无 grant 导出必须用 --roadmap 指明来源")
        grant = {
            "grant_id": None,
            "role": "maintainer",
            "roadmap": roadmap,
            "scope": ["**"],
            "one_shot": False,
        }
    directory = (contract / "archive" / str(roadmap)).resolve()
    if not directory.is_dir():
        raise ContextError(f"归档不存在: {roadmap}")
    files = _archive_scope_files(directory, [str(item) for item in grant.get("scope") or []])
    if not files:
        raise ContextError("grant scope 内没有可导出文件")
    total_bytes = sum(item.stat().st_size for item in files)
    if grant_id and (
        total_bytes > int(grant.get("max_bytes") or 0)
        or len(files) > int(grant.get("max_files") or 0)
    ):
        raise ContextError(
            f"grant 超限：导出 {len(files)} 文件/{total_bytes}B 超过上限"
            f" {grant.get('max_files')}/{grant.get('max_bytes')}"
        )
    target_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for item in files:
        relative = item.relative_to(directory).as_posix()
        destination = target_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = item.read_bytes()
        destination.write_bytes(payload)
        entries.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
                "reference_only": True,
            }
        )
    manifest = {
        "schema": 1,
        "grant_id": grant.get("grant_id"),
        "source_archive": f"archive/{roadmap}",
        "exported_at": now.isoformat(),
        "exported_by": actor_id,
        "role": role,
        "files": entries,
    }
    manifest_path = target_dir / "SOURCES.yaml"
    import yaml

    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    digest = hashlib.sha256(
        "\n".join(f"{item['path']}:{item['sha256']}" for item in entries).encode("utf-8")
    ).hexdigest()
    _ledger_append(
        contract,
        {
            "event": "archive.export",
            "actor": actor_id,
            "role": role,
            "grant_id": grant.get("grant_id"),
            "source": f"archive/{roadmap}",
            "to": rel_target,
            "files": len(entries),
            "bytes": total_bytes,
            "digest": f"sha256:{digest}",
        },
    )
    if grant_id:
        _write_grant_cache(contract)
    return {
        "grant_id": grant.get("grant_id"),
        "source": f"archive/{roadmap}",
        "to": rel_target,
        "files": entries,
        "bytes": total_bytes,
        "digest": f"sha256:{digest}",
        "manifest": f"{rel_target}/SOURCES.yaml",
    }


def read_log(project: str | Path, *, limit: int = 50) -> list[dict[str, Any]]:
    contract = resolve_contract(project)
    path = contract / "state" / "READ-LOG.ndjson"
    items = []
    for line in tail_lines(path, limit):
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            items.append(data)
    return items


def policy(project: str | Path) -> dict[str, Any]:
    contract = resolve_contract(project)
    path = contract / "policies" / "CONTEXT-POLICY.yaml"
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ContextError(f"{path} 不是合法 YAML: {exc}") from exc
    return data if isinstance(data, dict) else {}
