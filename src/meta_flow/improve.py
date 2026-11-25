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
SENSITIVE_RE = re.compile(
    r"(?i)(password|passwd|api[_-]?key|secret|token|BEGIN [A-Z ]*PRIVATE KEY)"
)


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
    mfp_id = _next_id(target)
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
        data["_path"] = str(path)
        items.append(data)
    return items


def find_improvement(
    project: str | Path,
    mfp_id: str,
    *,
    scope: str = "contract",
) -> Path:
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
    path = find_improvement(project_path, mfp_id)
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
    if not re.fullmatch(r"MFP-\d{4}", mfp_id) or (target_dir / f"{mfp_id}.yaml").exists():
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
    if "/" in ref:
        project, mfp_id = ref.split("/", 1)
        path = inbox / project / f"{mfp_id}.yaml"
        if not path.is_file():
            raise ImproveError(f"找不到 inbox 改进包: {path}")
        return path
    matches = list(inbox.glob(f"*/{ref}.yaml"))
    if len(matches) != 1:
        raise ImproveError(f"改进包引用不唯一或不存在: {ref}；请使用 <project>/<MFP>")
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
