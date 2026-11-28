"""Meta Flow 改进包（MFP）：创建、校验、提交与源码导入。"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from . import __version__, global_store
from .workspace import resolve_contract

MFP_DIR = "improvements"
LOCAL_DIR = Path(".meta-flow/improvements")
RECORD_KINDS = {"bug": "BUG", "requirement": "REQ", "change": "CHG"}
SAFE_MFP_ID_RE = re.compile(r"^MFP-(?:[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*-)?\d{4}$")
SAFE_PROJECT_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?$")
SENSITIVE_RE = re.compile(
    r"(?i)(password|passwd|api[_-]?key|secret|token|BEGIN [A-Z ]*PRIVATE KEY)"
)


def _safe_mfp_id(value: str) -> str:
    """MFP ID 白名单：拒绝路径分隔/穿越（N3 归档安全面，R8）。"""
    mfp_id = str(value or "").strip()
    if not SAFE_MFP_ID_RE.fullmatch(mfp_id):
        raise ImproveError(f"MFP ID 非法: {value!r}；必须形如 MFP-<project>-<seq>|MFP-<seq>", 3)
    return mfp_id


def _safe_project(value: str) -> str:
    project = str(value or "").strip()
    if not SAFE_PROJECT_RE.fullmatch(project) or project in {".", ".."}:
        raise ImproveError(f"MFP 来源项目名非法: {value!r}", 3)
    return project


class ImproveError(Exception):
    """改进包操作失败。"""

    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ImproveError(f"缺少文件: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ImproveError(f"{path} 不是合法 YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ImproveError(f"{path} 顶层必须是映射")
    return data


def _dump(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _next_id(directory: Path, prefix: str = "MFP") -> str:
    pattern = re.compile(rf"^{prefix}-(\d{{4}})\.yaml$")
    numbers = [
        int(match.group(1))
        for path in directory.glob(f"{prefix}-*.yaml")
        if (match := pattern.fullmatch(path.name))
    ]
    return f"{prefix}-{max(numbers, default=0) + 1:04d}"


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", value.strip()).strip("-").lower()
    return cleaned or "project"


def _next_local_id(directory: Path, project_id: str) -> str:
    """生产项目本地 MFP ID：``MFP-<project>-<seq>``（INFO-FLOWS §3.2）。"""
    slug = _slug(project_id)
    pattern = re.compile(rf"^MFP-{re.escape(slug)}-(\d{{4}})\.yaml$")
    numbers = [
        int(match.group(1))
        for path in directory.glob(f"MFP-{slug}-*.yaml")
        if (match := pattern.fullmatch(path.name))
    ]
    return f"MFP-{slug}-{max(numbers, default=0) + 1:04d}"


def _project_meta(project: Path) -> tuple[str, Path | None]:
    project = project.expanduser().resolve()
    local = project / ".meta-flow" / "workspace.yaml"
    if local.is_file():
        data = _load(local)
        return str(data.get("project_id") or project.name), project
    install_path = project / ".meta-flow" / "install.yaml"
    if install_path.is_file():
        install = _load(install_path)
        parent = install.get("workspace_root")
        if parent:
            parent_path = Path(str(parent)).expanduser().resolve()
            parent_local = parent_path / ".meta-flow" / "workspace.yaml"
            if parent_local.is_file():
                data = _load(parent_local)
                return str(data.get("project_id") or parent_path.name), parent_path
        return str(project.name), None
    return project.name, None


def _contract_root(project: Path) -> Path:
    project = project.expanduser().resolve()
    local = project / ".meta-flow" / "workspace.yaml"
    if local.is_file():
        data = _load(local)
        raw = data.get("contract_dir")
        if not raw:
            raise ImproveError("workspace.yaml 缺少 contract_dir")
        path = Path(str(raw)).expanduser()
        return (project / path).resolve() if not path.is_absolute() else path.resolve()
    role = project / ".meta-flow" / "role.yaml"
    if role.is_file() and (project / "workspace").is_dir():
        return project
    raise ImproveError("当前目录不是 workspace 或 contract")


def contract_dir(project: Path) -> Path:
    return _contract_root(project) / MFP_DIR


def local_dir(project: Path) -> Path:
    return project.expanduser().resolve() / LOCAL_DIR


def inbox_dir(project_id: str) -> Path:
    return global_store.global_home() / MFP_DIR / "inbox" / project_id


def _base_package(mfp_id: str, title: str, project_id: str, role: str) -> dict[str, Any]:
    return {
        "id": mfp_id,
        "title": title,
        "status": "draft",
        "priority": "should",
        "category": "feature",
        "classification": "undecided",
        "source": {
            "project": project_id,
            "role": role,
            "created_by": role,
            "created_at": _now(),
            "mf_version": __version__,
            "platform": sys.platform,
            "agent": role,
        },
        "problem": "",
        "context": {
            "scenario": "",
            "reproduction": [],
            "expected": "",
            "actual": "",
            "evidence": [],
            "affected": [],
        },
        "acceptance": [],
        "testing_plan": "",
        "rollback": "",
        "privacy": {"sanitized": False, "removed": []},
        "source_record": None,
        "resolution": {
            "version": None,
            "commit": None,
            "tests": [],
            "verified_by": None,
            "verified_at": None,
            "note": None,
        },
    }


def new_improvement(
    project: str | Path,
    title: str,
    *,
    local: bool = False,
) -> Path:
    project_path = Path(project).expanduser().resolve()
    role = "worker" if local else "manager"
    project_id, _ = _project_meta(project_path)
    target = local_dir(project_path) if local else contract_dir(project_path)
    target.mkdir(parents=True, exist_ok=True)
    mfp_id = _next_local_id(target, project_id) if local else _next_id(target)
    data = _base_package(mfp_id, title, project_id, role)
    path = target / f"{mfp_id}.yaml"
    _dump(path, data)
    if local:
        # R10/R11：本地 MFP 受控通道写审计（不记录内容）
        try:
            contract = resolve_contract(project_path)
            log_path = contract / "state" / "READ-LOG.ndjson"
            record = {
                "ts": _now(),
                "event": "guard",
                "actor": "worker",
                "role": "worker",
                "task": "无",
                "tool": "mf improve new --local",
                "decision": "allow",
                "path": str(path),
                "reason": "local-mfp",
            }
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass
    return path


def list_improvements(
    project: str | Path,
    *,
    scope: str = "contract",
    status: str | None = None,
    active_only: bool = False,
) -> list[dict[str, Any]]:
    project_path = Path(project).expanduser().resolve()
    project_id, _ = _project_meta(project_path)
    if scope == "inbox":
        directory = inbox_dir(project_id)
    elif scope == "local":
        directory = local_dir(project_path)
    else:
        directory = contract_dir(project_path)
    if not directory.is_dir():
        return []
    items = []
    for path in sorted(directory.glob("MFP-*.yaml")):
        try:
            data = _load(path)
        except ImproveError:
            continue
        if status and data.get("status") != status:
            continue
        if active_only and data.get("status") in {
            "closed",
            "verified",
            "rejected",
            "deferred",
            "duplicate",
        }:
            continue
        data["_path"] = str(path)
        items.append(data)
    return items


def find_improvement(
    project: str | Path,
    mfp_id: str,
    *,
    scope: str = "contract",
) -> Path:
    mfp_id = _safe_mfp_id(mfp_id)
    project_path = Path(project).expanduser().resolve()
    project_id, _ = _project_meta(project_path)
    directory = (
        inbox_dir(project_id)
        if scope == "inbox"
        else local_dir(project_path)
        if scope == "local"
        else contract_dir(project_path)
    )
    path = directory / f"{mfp_id}.yaml"
    if not path.is_file():
        raise ImproveError(f"找不到改进包: {path}")
    return path


def validate_improvement(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    context = data.get("context")
    source = data.get("source")
    privacy = data.get("privacy")
    if not str(data.get("title") or "").strip():
        errors.append("缺少 title")
    if not str(data.get("problem") or "").strip():
        errors.append("缺少 problem")
    if not isinstance(context, dict):
        errors.append("缺少 context")
    else:
        if not context.get("reproduction"):
            errors.append("缺少 context.reproduction")
        if not str(context.get("expected") or "").strip():
            errors.append("缺少 context.expected")
        if not str(context.get("actual") or "").strip():
            errors.append("缺少 context.actual")
        if not context.get("affected"):
            errors.append("缺少 context.affected")
        if not context.get("evidence"):
            errors.append("缺少 context.evidence")
    if not isinstance(data.get("acceptance"), list) or not data["acceptance"]:
        errors.append("缺少 acceptance")
    if not str(data.get("testing_plan") or "").strip():
        errors.append("缺少 testing_plan")
    if not isinstance(source, dict):
        errors.append("缺少 source")
    else:
        for key in ("project", "role", "mf_version"):
            if not source.get(key):
                errors.append(f"缺少 source.{key}")
    if not isinstance(privacy, dict) or privacy.get("sanitized") is not True:
        errors.append("privacy.sanitized 必须为 true")
    else:
        text = yaml.safe_dump(data, allow_unicode=True)
        if SENSITIVE_RE.search(text):
            errors.append("疑似包含敏感信息（token/password/secret/private key）")
    return errors


def submit_improvement(project: str | Path, mfp_id: str) -> Path:
    project_path = Path(project).expanduser().resolve()
    try:
        path = find_improvement(project_path, mfp_id)
    except ImproveError:
        # 生产项目本地 MFP（.meta-flow/improvements）也可直接提交到全局 inbox
        path = find_improvement(project_path, mfp_id, scope="local")
    data = _load(path)
    errors = validate_improvement(data)
    if errors:
        raise ImproveError("改进包不完整: " + "; ".join(errors))
    project_id, _ = _project_meta(project_path)
    target = inbox_dir(project_id) / f"{mfp_id}.yaml"
    data["status"] = "submitted"
    data["submitted_at"] = _now()
    data["inbox_ref"] = str(target)
    data["digest"] = _digest(path)
    _dump(path, data)
    _dump(target, data)
    return target


def import_improvement(project: str | Path, source: str | Path) -> Path:
    project_path = Path(project).expanduser().resolve()
    source_path = Path(source).expanduser().resolve()
    data = _load(source_path)
    errors = validate_improvement(data)
    if errors:
        raise ImproveError("改进包不完整: " + "; ".join(errors))
    target_dir = contract_dir(project_path)
    target_dir.mkdir(parents=True, exist_ok=True)
    mfp_id = str(data.get("id") or _next_id(target_dir))
    # 兼容本地项目 ID ``MFP-<project>-<seq>`` 与 meta-flow 内部 ``MFP-<seq>``
    if not re.fullmatch(r"MFP-(?:[A-Za-z0-9]+-)?\d{4}", mfp_id) or (
        target_dir / f"{mfp_id}.yaml"
    ).exists():
        mfp_id = _next_id(target_dir)
        data["id"] = mfp_id
    data["imported_from"] = str(source_path)
    data["status"] = "draft"
    target = target_dir / f"{mfp_id}.yaml"
    _dump(target, data)
    return target


def _source_root(source: str | Path | None) -> Path:
    if source is not None:
        path = Path(source).expanduser().resolve()
    else:
        path = Path(
            global_store.load_manifest().get("source_dir", global_store.global_home() / "source")
        ).expanduser()
    if not (path / "pyproject.toml").is_file():
        raise ImproveError(f"不是 meta-flow 源码目录: {path}")
    return path


def _find_inbox(ref: str) -> Path:
    inbox = global_store.global_home() / MFP_DIR / "inbox"
    raw = str(ref or "").strip()
    if "/" in raw:
        project, mfp_part = raw.split("/", 1)
        project = _safe_project(project)
        mfp_id = _safe_mfp_id(mfp_part)
        path = inbox / project / f"{mfp_id}.yaml"
        if not path.is_file():
            raise ImproveError(f"找不到 inbox 改进包: {path}")
        return path
    mfp_id = _safe_mfp_id(raw)
    matches = list(inbox.glob(f"*/{mfp_id}.yaml"))
    if len(matches) != 1:
        raise ImproveError(f"改进包引用不唯一或不存在: {raw}；请使用 <project>/<MFP>")
    return matches[0]


def source_import(
    ref: str,
    *,
    source: str | Path | None = None,
    kind: str | None = None,
    already_implemented: bool = False,
    version: str | None = None,
    commit: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """把全局 inbox 的 MFP 导入 meta-flow 源码仓并分类。"""
    data = _load(_find_inbox(ref))
    classification = kind or data.get("classification") or "undecided"
    if classification not in {"bug", "requirement", "change", "undecided"}:
        raise ImproveError("classification 只能是 bug|requirement|change|undecided")
    if already_implemented and classification == "undecided":
        raise ImproveError("已实现的 MFP 必须指定 --kind bug|requirement|change")

    source_root = _source_root(source)
    for sub in ("inbox", "open", "closed", "records"):
        (source_root / MFP_DIR / sub).mkdir(parents=True, exist_ok=True)
    mfp_id = str(data.get("id") or "MFP-0001")
    (source_root / MFP_DIR / "inbox" / f"{mfp_id}.yaml").write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )

    record_id = None
    if classification != "undecided":
        prefix = RECORD_KINDS[classification]
        record_id = _next_id(source_root / MFP_DIR / "records", prefix)
        data["source_record"] = record_id
        data["classification"] = classification
        record = {
            "id": record_id,
            "kind": classification,
            "title": data.get("title"),
            "status": "done" if already_implemented else "open",
            "source_mfp": mfp_id,
            "source_project": (data.get("source") or {}).get("project"),
            "acceptance": data.get("acceptance"),
            "created_at": _now(),
            "resolution": {
                "version": version,
                "commit": commit,
                "note": note,
            },
        }
        _dump(source_root / MFP_DIR / "records" / f"{record_id}.yaml", record)

    if already_implemented:
        data["status"] = "closed"
        data["resolution"].update(
            {
                "version": version,
                "commit": commit,
                "note": note or "already implemented",
                "verified_by": "maintainer-record",
                "verified_at": _now(),
            }
        )
        destination = source_root / MFP_DIR / "closed" / f"{mfp_id}.yaml"
    else:
        data["status"] = "accepted"
        destination = source_root / MFP_DIR / "open" / f"{mfp_id}.yaml"
    _dump(destination, data)
    return {
        "source": str(source_root),
        "mfp": mfp_id,
        "classification": classification,
        "record": record_id,
        "destination": str(destination),
    }


def source_list(
    *,
    source: str | Path | None = None,
    scope: str = "open",
) -> dict[str, list[dict[str, Any]]]:
    source_root = _source_root(source)
    result: dict[str, list[dict[str, Any]]] = {}
    for name in ("open", "closed", "records"):
        directory = source_root / MFP_DIR / name
        items = []
        if directory.is_dir():
            for path in sorted(directory.glob("*.yaml")):
                try:
                    data = _load(path)
                except ImproveError:
                    continue
                data["_path"] = str(path)
                items.append(data)
        result[name] = items
    if scope in result:
        return {scope: result[scope]}
    return result


def source_update(
    mfp_id: str,
    status: str,
    *,
    source: str | Path | None = None,
    version: str | None = None,
    commit: str | None = None,
    note: str | None = None,
) -> Path:
    source_root = _source_root(source)
    candidates = [
        source_root / MFP_DIR / "open" / f"{mfp_id}.yaml",
        source_root / MFP_DIR / "closed" / f"{mfp_id}.yaml",
    ]
    path = next((item for item in candidates if item.is_file()), None)
    if path is None:
        raise ImproveError(f"源码仓找不到 MFP: {mfp_id}")
    data = _load(path)
    data["status"] = status
    resolution = data.setdefault("resolution", {})
    if version is not None:
        resolution["version"] = version
    if commit is not None:
        resolution["commit"] = commit
    if note is not None:
        resolution["note"] = note
    if status in {"verified", "closed"}:
        resolution["verified_at"] = _now()
        target = source_root / MFP_DIR / "closed" / path.name
    else:
        target = source_root / MFP_DIR / "open" / path.name
    _dump(target, data)
    if target != path:
        path.unlink()
    if data.get("source_record"):
        record_path = source_root / MFP_DIR / "records" / f"{data['source_record']}.yaml"
        if record_path.is_file():
            record = _load(record_path)
            record["status"] = "done" if status in {"verified", "closed"} else status
            record.setdefault("resolution", {}).update(
                {"version": version, "commit": commit, "note": note}
            )
            _dump(record_path, record)
    return target


def _archive_dir(source_root: Path) -> Path:
    return source_root / MFP_DIR / "archive"


def _index_path(source_root: Path) -> Path:
    return _archive_dir(source_root) / "index.json"


def _write_index(source_root: Path, entries: dict[str, dict[str, Any]]) -> Path:
    path = _index_path(source_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": 1,
        "updated_at": _now(),
        "mfps": [entries[key] for key in sorted(entries)],
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path


def archive_index(source: str | Path | None = None) -> dict[str, Any]:
    """读取 meta-flow 归档索引 ``improvements/archive/index.json``。"""
    source_root = _source_root(source)
    path = _index_path(source_root)
    if not path.is_file():
        return {"schema": 1, "updated_at": None, "mfps": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ImproveError(f"{path} 不是合法 JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ImproveError(f"{path} 顶层必须是映射")
    data.setdefault("mfps", [])
    return data


def archive_improvement(
    ref: str,
    *,
    source: str | Path | None = None,
    actor_role: str = "maintainer",
) -> dict[str, Any]:
    """meta-flow maintainer 唯一归档者：inbox → 源码仓 ``improvements/archive/``。

    生产项目中的 manager/designer/worker/生产 maintainer 调用一律拒绝（N3）。
    """
    if actor_role != "maintainer":
        raise ImproveError(
            "MFP 归档只允许 meta-flow maintainer；生产项目角色与生产 maintainer 不得归档/同步",
            3,
        )
    source_root = _source_root(source)
    data = _load(_find_inbox(ref))
    errors = validate_improvement(data)
    if errors:
        raise ImproveError("改进包不完整: " + "; ".join(errors))
    mfp_id = _safe_mfp_id(str(data.get("id") or ""))
    target = _archive_dir(source_root) / f"{mfp_id}.yaml"
    data["status"] = "archived"
    data["archived_at"] = _now()
    data["archive_ref"] = f"{MFP_DIR}/archive/{mfp_id}.yaml"
    _dump(target, data)
    index = archive_index(source_root)
    entries = {
        str(item.get("id")): item
        for item in index.get("mfps") or []
        if isinstance(item, dict) and item.get("id")
    }
    entries[mfp_id] = {
        "id": mfp_id,
        "source_project": (data.get("source") or {}).get("project"),
        "title": data.get("title"),
        "status": data.get("status"),
        "decision": data.get("decision") or data.get("classification"),
        "reason": data.get("decision_note") or data.get("reason"),
        "target": data.get("target"),
        "resolution": data.get("resolution"),
        "archive_ref": data["archive_ref"],
        "updated_at": _now(),
    }
    index_path = _write_index(source_root, entries)
    return {
        "mfp": mfp_id,
        "archive": str(target),
        "index": str(index_path),
        "status": data["status"],
    }


TRIAGE_DECISIONS = ("accepted", "rejected", "deferred")


def triage_improvement(
    project: str | Path,
    mfp_id: str,
    *,
    decision: str,
    reason: str | None = None,
    next_step: str | None = None,
    target: str | None = None,
    actor_role: str = "manager",
    scope: str = "contract",
) -> dict[str, Any]:
    """meta-flow manager 评估 MFP：接收/拒绝/延期，写理由与下一步。"""
    if actor_role != "manager":
        raise ImproveError("MFP 评估只允许 meta-flow manager", 3)
    if decision not in TRIAGE_DECISIONS:
        raise ImproveError(f"decision 只能是 {'|'.join(TRIAGE_DECISIONS)}")
    if decision == "accepted" and next_step not in {"design", "direct"}:
        raise ImproveError("accepted 必须给下一步 --next-step design|direct（INFO-FLOWS §3.5）")
    if decision in {"rejected", "deferred"} and not str(reason or "").strip():
        raise ImproveError(f"{decision} 必须写理由 reason")
    path = find_improvement(project, mfp_id, scope=scope)
    data = _load(path)
    data["status"] = decision
    data["target"] = target or data.get("target")
    data["triage"] = {
        "decision": decision,
        "reason": reason,
        "next_step": next_step,
        "target": data.get("target"),
        "decided_by": "manager",
        "decided_at": _now(),
    }
    _dump(path, data)
    from .state import ledger_append

    ledger_append(
        resolve_contract(Path(project).expanduser().resolve()),
        {
            "event": "mfp.triaged",
            "mfp": mfp_id,
            "decision": decision,
            "next_step": next_step,
            "reason": reason,
            "target": data.get("target"),
        },
    )
    return data


SYNC_STATUS_MAP = {
    "resolved": "resolved",
    "closed": "resolved",
    "verified": "resolved",
    "rejected": "rejected",
    "deferred": "deferred",
    "accepted": "accepted-not-resolved",
    "in_design": "in_design",
    "in_implementation": "in_implementation",
    "triaged": "triaged",
    "archived": "archived",
}


def production_root(project: str | Path) -> Path:
    project_path = Path(project).expanduser().resolve()
    _project_id, root = _project_meta(project_path)
    return root or project_path


def sync_state_path(project: str | Path) -> Path:
    return production_root(project) / LOCAL_DIR / "state.json"


def load_sync_state(project: str | Path) -> dict[str, Any]:
    path = sync_state_path(project)
    if not path.is_file():
        return {"schema": 1, "last_sync": None, "mfps": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ImproveError(f"{path} 不是合法 JSON: {exc}") from exc
    return data if isinstance(data, dict) else {"schema": 1, "mfps": {}}


def sync_improvements(
    project: str | Path,
    *,
    from_path: str | Path | None = None,
    source: str | Path | None = None,
    actor_role: str = "maintainer",
) -> dict[str, Any]:
    """meta-flow maintainer 把归档索引同步到生产项目 ``state.json``。

    显示 resolved/rejected/accepted-not-resolved/deferred/in_design/
    in_implementation；生产项目只读自己的 MFP 状态。
    """
    if actor_role != "maintainer":
        raise ImproveError("MFP 同步只允许 meta-flow maintainer", 3)
    if from_path is not None:
        path = Path(from_path).expanduser().resolve()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ImproveError(f"{path} 不是合法 JSON: {exc}") from exc
        if isinstance(payload, dict):
            entries = payload.get("mfps") or []
        elif isinstance(payload, list):
            entries = payload
        else:
            raise ImproveError(f"{path} 顶层必须是映射或列表")
    else:
        entries = archive_index(source).get("mfps") or []
    state = {
        "schema": 1,
        "last_sync": _now(),
        "mf_version": __version__,
        "mfps": {},
    }
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        raw = str(entry.get("status") or "")
        display = SYNC_STATUS_MAP.get(raw, raw)
        resolution = entry.get("resolution") or {}
        if display == "accepted-not-resolved" and resolution:
            display = "resolved"
        state["mfps"][str(entry["id"])] = {
            "status": display,
            "raw_status": raw,
            "title": entry.get("title"),
            "decision": entry.get("decision"),
            "reason": entry.get("reason"),
            "target": entry.get("target"),
            "resolution": resolution,
            "synced_at": _now(),
        }
    path = sync_state_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    try:
        contract = resolve_contract(Path(project).expanduser().resolve())
        from .state import ledger_append

        ledger_append(
            contract,
            {
                "event": "mfp.synced",
                "project": production_root(project).name,
                "count": len(state["mfps"]),
            },
        )
    except Exception:
        pass
    return state
