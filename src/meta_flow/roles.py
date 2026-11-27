"""角色短名、会话锚点与用户终端角色切换（T033 A1 / WP-F1）。

worker/designer/manager 的 effective role 不能只依赖 shell cwd（cwd 漂移）
或任意 ``MF_ROLE`` 环境变量（可伪造）。本模块提供：

- 角色短名/别名规范化（manager/designer/worker/maintainer、
  mgr/dsg/wkr/mnt、meta-* 命名空间）；
- **按会话隔离**的锚点 ``<workspace>/.meta-flow/session-roles/<session_id>.yaml``：
  由宿主 SessionStart hook 写入；用户终端 ``mf role --as`` 写
  ``session-roles/user-tty.yaml``（显式人工切换，按 updated_at 决定优先级）；
- 运行时来源绑定：SessionStart 锚点必须携带 ``session_id``（payload 或
  ``CLAUDE_CODE_SESSION_ID``），无 session_id 的写入被拒绝；读取时只读当前
  会话锚点，避免多会话互相覆盖；
- TTY 校验：只有用户终端可以切换角色，AI Bash 工具（非 TTY）拒绝。

锚点只由受控入口写入；guard 不允许工具层直接写 ``.meta-flow/session-roles/**``
（本地 MFP 白名单除外），因此 worker 不能自行伪造锚点提权。
"""

from __future__ import annotations

import hashlib
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROLE_NAMES = ("manager", "designer", "worker", "maintainer")
ROLE_ALIASES = {
    "manager": "manager",
    "mgr": "manager",
    "meta-manager": "manager",
    "designer": "designer",
    "dsg": "designer",
    "meta-designer": "designer",
    "worker": "worker",
    "wkr": "worker",
    "meta-worker": "worker",
    "maintainer": "maintainer",
    "mnt": "maintainer",
    "meta-maintainer": "maintainer",
}
ANCHOR_DIR = Path(".meta-flow") / "session-roles"
USER_ANCHOR_NAME = "user-tty.yaml"
LEGACY_ANCHOR_REL = Path(".meta-flow") / "session-role.yaml"
ANCHOR_SOURCES = ("session-start", "user-tty")
SESSION_ENV = "CLAUDE_CODE_SESSION_ID"


class RoleError(Exception):
    """角色名/锚点/切换失败。"""

    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


def normalize_role(value: str | None) -> str | None:
    """把角色短名/别名规范为 manager/designer/worker/maintainer。"""
    if value is None:
        return None
    return ROLE_ALIASES.get(str(value).strip().lower())


def role_choices() -> list[str]:
    return list(ROLE_NAMES)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def workspace_root_for(start: Path) -> Path | None:
    """向上查找 workspace 根或 contract 根（供锚点定位）。"""
    from .workspace import find_contract_root, find_workspace_root

    path = Path(start).expanduser().resolve()
    if path.is_file():
        path = path.parent
    return find_workspace_root(path) or find_contract_root(path)


def current_session_id(explicit: str | None = None) -> str | None:
    """当前宿主会话 ID：显式参数优先，其次 CLAUDE_CODE_SESSION_ID。"""
    value = str(explicit or os.environ.get(SESSION_ENV) or "").strip()
    return value or None


def _session_file(root: Path, session_id: str) -> Path:
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:32]
    return root / ANCHOR_DIR / f"{digest}.yaml"


def anchor_path(start: Path, session_id: str | None = None) -> Path | None:
    """测试/诊断：返回当前会话锚点路径（user-tty 切换另见 user_anchor_path）。"""
    root = workspace_root_for(start)
    sid = current_session_id(session_id)
    if root is None or sid is None:
        return None
    return _session_file(root, sid)


def user_anchor_path(start: Path) -> Path | None:
    root = workspace_root_for(start)
    return root / ANCHOR_DIR / USER_ANCHOR_NAME if root is not None else None


def _load_anchor_file(path: Path, workspace: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    role = normalize_role(data.get("role"))
    if role not in ROLE_NAMES:
        return None
    raw_root = data.get("root")
    if not raw_root:
        return None
    role_root = Path(str(raw_root)).expanduser().resolve()
    if not role_root.exists():
        return None
    source = str(data.get("source") or "")
    if source not in ANCHOR_SOURCES:
        return None
    return {
        "role": role,
        "root": role_root,
        "cwd": str(data.get("cwd") or ""),
        "workspace_root": str(workspace),
        "contract_dir": str(data.get("contract_dir") or "") or None,
        "source": source,
        "session_id": str(data.get("session_id") or "") or None,
        "updated_at": str(data.get("updated_at") or ""),
    }


def read_anchor(start: Path, session_id: str | None = None) -> dict[str, Any] | None:
    """读取当前会话锚点；无 session_id 时只认用户 TTY 显式切换，fail-closed。

    多会话：不同 session_id 的 SessionStart 文件互不覆盖；同一 session 的
    SessionStart/clear 重写自己的文件。user-tty 切换按 updated_at 优先，
    直到本会话下一次 SessionStart 覆盖。
    """
    root = workspace_root_for(start)
    if root is None:
        return None
    sid = current_session_id(session_id)
    candidates: list[dict[str, Any]] = []
    if sid is not None:
        item = _load_anchor_file(_session_file(root, sid), root)
        if item is not None:
            candidates.append(item)
    user_item = _load_anchor_file(root / ANCHOR_DIR / USER_ANCHOR_NAME, root)
    if user_item is not None:
        candidates.append(user_item)
    if sid is None:
        # 没有会话标识时不回退到任何会话共享锚点（M2 fail-closed）；
        # 仅允许用户终端显式切换（user-tty）作为人工覆盖。
        return user_item
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.get("updated_at") or "")


def _validate_root(role: str, start: Path, cwd: Path, root: Path | None) -> Path:
    from .workspace import detect_role

    if root is not None:
        target = Path(root).expanduser().resolve()
    else:
        detected, detected_root = detect_role(cwd)
        if detected != role or detected_root is None:
            raise RoleError(
                f"目录角色 {detected} 与目标角色 {role} 不一致；"
                "请在对应工作区目录或使用用户终端切换"
            )
        target = detected_root
    if not target.exists():
        raise RoleError(f"角色根不存在: {target}")
    return target


def write_anchor(
    role: str,
    *,
    start: Path,
    source: str,
    cwd: Path | None = None,
    session_id: str | None = None,
    contract_dir: str | None = None,
    root: Path | None = None,
    stream: Any | None = None,
    out: Any | None = None,
) -> dict[str, Any]:
    """写入锚点：session-start 必须绑定 session_id；user-tty 必须用户 TTY。

    R1：user-tty 锚点会按 updated_at 影响其他会话，不能由 AI/解释器直接写入；
    ``write_anchor(source="user-tty")`` 在非 TTY（默认 stdin/stdout）一律拒绝。
    """
    role = normalize_role(role) or ""
    if role not in ROLE_NAMES:
        raise RoleError(f"角色只能是 {'|'.join(ROLE_NAMES)}: {role!r}")
    if source not in ANCHOR_SOURCES:
        raise RoleError(f"锚点来源只能是 {ANCHOR_SOURCES}: {source!r}")
    if source == "user-tty" and not is_tty(stream, out):
        raise RoleError(
            "user-tty 锚点只能由用户终端写入；非 TTY（AI/解释器）拒绝。"
            "请在用户终端运行 mf role --as <role> --reason <原因>",
            3,
        )
    workspace = workspace_root_for(start)
    if workspace is None:
        raise RoleError("未找到工作区/契约根，无法写角色锚点")
    # SessionStart 必须显式来自宿主 payload；不能用进程环境自动补全，
    # 避免任意解释器在 AI 会话内静默写有效锚点。
    sid = str(session_id or "").strip() or None
    if source == "session-start" and sid is None:
        raise RoleError(
            "SessionStart 锚点缺少 session_id（宿主 payload）；"
            "拒绝写入共享锚点（fail-closed）"
        )
    role_root = _validate_root(role, start, Path(cwd or start), root)
    if contract_dir is None:
        from .workspace import resolve_contract

        try:
            contract_dir = str(resolve_contract(workspace))
        except Exception:
            contract_dir = None
    path = (
        workspace / ANCHOR_DIR / USER_ANCHOR_NAME
        if source == "user-tty"
        else _session_file(workspace, str(sid))
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "schema": 2,
        "role": role,
        "root": str(role_root),
        "cwd": str(Path(cwd or start).expanduser().resolve()),
        "workspace_root": str(workspace),
        "contract_dir": contract_dir,
        "source": source,
        "session_id": sid if source == "session-start" else (sid or None),
        "updated_at": _now(),
    }
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return data


def session_start(
    cwd: Path, *, session_id: str | None = None, source: str = "startup"
) -> dict[str, Any] | None:
    """SessionStart hook：按宿主会话目录重写本会话锚点，/clear 不残留旧角色。"""
    from .workspace import detect_role

    detected, detected_root = detect_role(Path(cwd))
    if detected == "unbound" or detected_root is None:
        return None
    sid = str(session_id or "").strip() or None
    if sid is None:
        # 宿主未提供会话标识：不写共享锚点，回退目录推导（fail-closed）
        return None
    return write_anchor(
        detected,
        start=Path(cwd),
        source="session-start",
        cwd=Path(cwd),
        session_id=sid,
        root=detected_root,
    )


def is_tty(stream: Any | None = None, out: Any | None = None) -> bool:
    stream = stream if stream is not None else sys.stdin
    out = out if out is not None else sys.stdout
    try:
        return bool(stream.isatty() and out.isatty())
    except (AttributeError, ValueError):
        return False


def switch_role(
    target: str,
    reason: str,
    *,
    cwd: Path | None = None,
    stream: Any | None = None,
    out: Any | None = None,
) -> dict[str, Any]:
    """用户在终端切换角色：非 TTY 拒绝；写 user-tty 锚点 + ledger role.switch。"""
    role = normalize_role(target)
    if role not in ROLE_NAMES:
        raise RoleError(f"角色只能是 {'|'.join(ROLE_NAMES)}: {target!r}")
    if not str(reason or "").strip():
        raise RoleError("切换角色必须提供 --reason，并写入 ledger")
    if not is_tty(stream, out):
        raise RoleError(
            "非 TTY 环境不能切换角色；请在用户终端运行 "
            f"mf role --as {role} --reason \"<原因>\"（AI 会话不得自升级）",
            3,
        )
    path = Path(cwd or Path.cwd())
    previous = read_anchor(path)
    from_anchor = previous["role"] if previous else None
    workspace = workspace_root_for(path)
    if workspace is None:
        raise RoleError("未找到工作区/契约根；请在工作区内切换角色")
    from .workspace import detect_role, resolve_contract

    detected, detected_root = detect_role(path)
    if role == "designer":
        try:
            target_root = resolve_contract(workspace)
        except Exception as exc:  # noqa: BLE001 - 统一转为角色切换错误
            raise RoleError(f"designer 工作区需要 contract：{exc}") from exc
    elif role == "worker":
        if detected != "worker" or detected_root is None:
            raise RoleError("worker 角色必须从已注册的子项目目录切换")
        target_root = detected_root
    elif role == "maintainer":
        target_root = detected_root if detected == "maintainer" else workspace
    else:
        target_root = detected_root if detected == "manager" else workspace
    data = write_anchor(
        role,
        start=path,
        source="user-tty",
        cwd=path,
        root=target_root,
        stream=stream,
        out=out,
    )
    from . import state
    from .workspace import resolve_contract

    try:
        contract = resolve_contract(workspace)
    except Exception:
        contract = None
    if contract is not None:
        state.ledger_append(
            contract,
            {
                "event": "role.switch",
                "from": from_anchor,
                "to": role,
                "cwd": str(path.expanduser().resolve()),
                "reason": str(reason).strip(),
                "source": "user-tty",
            },
        )
    data["from"] = from_anchor
    return data


def reset_anchor(
    start: Path,
    *,
    session_id: str | None = None,
) -> dict[str, Any]:
    """清理 user-tty/当前会话/遗留锚点，不写新锚点（MFP-0039）。

    仅供 maintainer 运维复位使用；worker/manager 由 CLI 角色门拒绝。
    """
    root = workspace_root_for(start)
    if root is None:
        raise RoleError("未找到工作区/契约根；无法清理角色锚点")
    sid = current_session_id(session_id)
    candidates = [
        root / ANCHOR_DIR / USER_ANCHOR_NAME,
        root / LEGACY_ANCHOR_REL,
    ]
    if sid is not None:
        candidates.append(_session_file(root, sid))
    removed: list[str] = []
    for path in candidates:
        if path.is_file():
            path.unlink()
            removed.append(str(path))
    from . import state
    from .workspace import resolve_contract

    try:
        contract = resolve_contract(root)
    except Exception:
        contract = None
    if contract is not None:
        state.ledger_append(
            contract,
            {
                "event": "role.reset",
                "root": str(root),
                "session_id": sid,
                "removed": removed,
                "by": "maintainer",
            },
        )
    return {"root": str(root), "session_id": sid, "removed": removed}


def describe(start: Path) -> dict[str, Any]:
    """返回锚点/目录/环境推导结论，供 mf role 展示与复位建议。

    A4：``mf role --json`` 必须可序列化；锚点中的 Path 统一转 str。
    """
    from .workspace import detect_role

    path = Path(start).expanduser().resolve()
    detected, detected_root = detect_role(path)
    anchor = read_anchor(path)
    anchor_view = (
        {
            key: (str(value) if isinstance(value, Path) else value)
            for key, value in anchor.items()
        }
        if anchor is not None
        else None
    )
    return {
        "detected": detected,
        "detected_root": str(detected_root) if detected_root else None,
        "anchor": anchor_view,
        "effective": anchor["role"] if anchor else detected,
        "source": "anchor" if anchor else "directory",
        "session_id": current_session_id(),
    }
