"""需求基线、DoR 与追踪矩阵。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .state import ledger_append
from .workspace import resolve_contract

REQ_PATH = "requirements/REQUIREMENTS.yaml"
REQ_STATUSES = (
    "proposed",
    "accepted",
    "in_roadmap",
    "in_progress",
    "designed",
    "implemented",
    "verified",
    "released",
    "deferred",
    "rejected",
)
PRIORITIES = ("must", "should", "could", "wont")


class ReqError(Exception):
    """需求操作失败。"""

    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _path(contract: Path) -> Path:
    return contract / REQ_PATH


def _load(contract: Path) -> dict[str, Any]:
    path = _path(contract)
    if not path.is_file():
        return {"schema": 1, "requirements": []}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ReqError(f"{path} 不是合法 YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ReqError(f"{path} 顶层必须是映射")
    data.setdefault("requirements", [])
    return data


def _save(contract: Path, data: dict[str, Any]) -> None:
    path = _path(contract)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _next_id(items: list[dict[str, Any]]) -> str:
    numbers = []
    for item in items:
        raw = str(item.get("id") or "")
        if raw.startswith("REQ-") and raw[4:].isdigit():
            numbers.append(int(raw[4:]))
    return f"REQ-{max(numbers, default=0) + 1:04d}"


def _find(contract: Path, req_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    data = _load(contract)
    for item in data["requirements"]:
        if item.get("id") == req_id:
            return data, item
    raise ReqError(f"需求不存在: {req_id}")


def validate_dor(item: dict[str, Any]) -> list[str]:
    errors = []
    if not str(item.get("title") or "").strip():
        errors.append("缺少 title")
    if not str(item.get("source") or "").strip():
        errors.append("缺少来源 source")
    if not str(item.get("roadmap") or "").strip():
        errors.append("缺少所属路标 roadmap")
    if item.get("priority") not in PRIORITIES:
        errors.append(f"priority 必须是 {'|'.join(PRIORITIES)}")
    acceptance = item.get("acceptance") or []
    if not isinstance(acceptance, list) or not acceptance:
        errors.append("DoR 要求至少一条可验证验收标准")
    for index, criterion in enumerate(acceptance, start=1):
        if not isinstance(criterion, dict) or not str(criterion.get("expect") or "").strip():
            errors.append(f"验收标准 A{index} 缺少 expect")
        elif criterion.get("method") not in {"automated", "artifact", "demonstration", "metric"}:
            errors.append(f"验收标准 A{index} method 非法")
    if item.get("status") not in REQ_STATUSES:
        errors.append(f"status 必须是 {'|'.join(REQ_STATUSES)}")
    return errors


def add_requirement(
    project: str | Path,
    title: str,
    *,
    priority: str = "must",
    acceptance: list[str] | None = None,
    roadmap: str | None = None,
    source: str = "user",
    description: str = "",
    non_goals: list[str] | None = None,
    dependencies: list[str] | None = None,
) -> dict[str, Any]:
    contract = resolve_contract(project)
    data = _load(contract)
    req_id = _next_id(data["requirements"])
    state_path = contract / "state" / "current.json"
    try:
        state = yaml.safe_load(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
    except yaml.YAMLError:
        state = {}
    roadmap = roadmap or str((state or {}).get("roadmap") or "R1")
    item = {
        "id": req_id,
        "title": title.strip(),
        "source": source,
        "priority": priority,
        "status": "proposed",
        "roadmap": roadmap,
        "description": description,
        "acceptance": [
            {"id": f"A{index}", "method": "artifact", "expect": text}
            for index, text in enumerate(acceptance or [], start=1)
        ],
        "non_goals": non_goals or [],
        "dependencies": dependencies or [],
        "created_at": _now(),
        "updated_at": _now(),
    }
    errors = validate_dor(item)
    if errors:
        raise ReqError("；".join(errors))
    data["requirements"].append(item)
    _save(contract, data)
    _write_requirement_doc(contract, item)
    refresh_index(contract)
    ledger_append(contract, {"event": "req.add", "req": req_id, "title": title})
    return item


def _write_requirement_doc(contract: Path, item: dict[str, Any]) -> None:
    path = contract / "requirements" / f"{item['id']}.md"
    lines = [
        f"# {item['id']} {item.get('title')}",
        "",
        f"> source: {item.get('source')}",
        f"> priority: {item.get('priority')}",
        f"> status: {item.get('status')}",
        f"> roadmap: {item.get('roadmap')}",
        "",
        "## 背景与用户需求",
        "",
        str(item.get("description") or ""),
        "",
        "## 范围与非目标",
        "",
        "非目标：" + ("；".join(item.get("non_goals") or []) or "待补充"),
        "",
        "## 验收标准",
        "",
    ]
    for criterion in item.get("acceptance") or []:
        lines.append(f"- {criterion.get('id')}: {criterion.get('expect')}")
    lines.extend(["", "## 追踪", "", "见 `requirements/TRACE.md`。", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def list_requirements(
    project: str | Path,
    *,
    status: str | None = None,
    roadmap: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    contract = resolve_contract(project)
    items = _load(contract)["requirements"]
    filtered = [
        item
        for item in items
        if (status is None or item.get("status") == status)
        and (roadmap is None or item.get("roadmap") == roadmap)
    ]
    return filtered[:limit] if limit is not None else filtered


def show_requirement(project: str | Path, req_id: str) -> dict[str, Any]:
    contract = resolve_contract(project)
    _, item = _find(contract, req_id)
    result = dict(item)
    result["trace"] = trace_requirement(contract, req_id)
    return result


def update_requirement(
    project: str | Path,
    req_id: str,
    *,
    status: str | None = None,
    priority: str | None = None,
    roadmap: str | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    contract = resolve_contract(project)
    data, item = _find(contract, req_id)
    if status is not None:
        if status not in REQ_STATUSES:
            raise ReqError(f"status 必须是 {'|'.join(REQ_STATUSES)}")
        item["status"] = status
    if priority is not None:
        if priority not in PRIORITIES:
            raise ReqError(f"priority 必须是 {'|'.join(PRIORITIES)}")
        item["priority"] = priority
    if roadmap is not None:
        item["roadmap"] = roadmap
    if title is not None:
        item["title"] = title
    item["updated_at"] = _now()
    errors = validate_dor(item)
    if errors:
        raise ReqError("；".join(errors))
    _save(contract, data)
    _write_requirement_doc(contract, item)
    refresh_index(contract)
    ledger_append(contract, {"event": "req.update", "req": req_id, "status": item.get("status")})
    return item


def _scan_yaml_refs(directory: Path, key: str, req_id: str) -> list[dict[str, Any]]:
    items = []
    if not directory.is_dir():
        return items
    for path in sorted(directory.rglob("*.yaml")) + sorted(directory.rglob("*.yml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        refs = data.get(key) or []
        if isinstance(refs, list) and req_id in refs:
            items.append({"file": str(path.relative_to(directory.parent)), **data})
    return items


def _scan_docs(directory: Path, req_id: str, pattern: str = "*.md") -> list[str]:
    hits = []
    if not directory.is_dir():
        return hits
    paths = directory.rglob(pattern) if pattern == "*.md" else directory.glob(pattern)
    for path in sorted(paths):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if req_id in text:
            hits.append(str(path.relative_to(directory.parent)))
    return hits


def _dedupe_by_id(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result = []
    for item in items:
        item_id = str(item.get("id") or "")
        if item_id and item_id in seen:
            continue
        if item_id:
            seen.add(item_id)
        result.append(item)
    return result


def trace_requirement(
    contract: Path,
    req_id: str,
    *,
    roadmap: str | None = None,
    include_archive: bool = False,
) -> dict[str, Any]:
    """追踪单个需求；默认只扫当前/活跃路标，不读 archive（BUG-0012）。"""
    task_paths: list[Path] = []
    if roadmap:
        task_paths.extend(
            (contract / "roadmap" / roadmap).glob("phases/*/tasks/T*/TASK.yaml")
        )
    else:
        task_paths.extend((contract / "roadmap").glob("*/phases/*/tasks/T*/TASK.yaml"))
    if include_archive:
        task_paths.extend((contract / "archive").glob("*/phases/*/tasks/T*/TASK.yaml"))
    tasks = []
    evidence: list[str] = []
    for path in sorted(task_paths):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        refs = ((data.get("inputs") or {}).get("requirements")) or []
        if req_id in refs:
            task_id = str(data.get("id") or "")
            tasks.append(
                {
                    "id": data.get("id"),
                    "status": data.get("status"),
                    "risk": (data.get("risk") or {}).get("level"),
                }
            )
            # 证据：任务 evidence 目录下的文件（MFP-0020 追踪链路）
            evidence_dir = path.parent / "evidence"
            if evidence_dir.is_dir():
                for item in sorted(evidence_dir.rglob("*")):
                    if item.is_file():
                        evidence.append(
                            f"{task_id}/evidence/{item.relative_to(evidence_dir).as_posix()}"
                        )
    verification = _scan_yaml_refs(contract / "verification", "requirement_refs", req_id)
    bugs = _scan_yaml_refs(contract / "bugs", "related_reqs", req_id)
    improvements = _scan_yaml_refs(contract / "improvements", "related_reqs", req_id)
    improvements += _scan_yaml_refs(
        contract / "improvements", "requirement_refs", req_id
    )
    if include_archive:
        for archive in sorted((contract / "archive").glob("*/verification")):
            verification.extend(_scan_yaml_refs(archive, "requirement_refs", req_id))
        for archive in sorted((contract / "archive").glob("*/bugs")):
            bugs.extend(_scan_yaml_refs(archive, "related_reqs", req_id))
    return {
        # SPEC 只匹配 SPEC-*.md，避免把 INDEX.md/README.md 计为 SPEC
        "specs": _scan_docs(contract / "specs", req_id, pattern="SPEC-*.md"),
        "designs": _scan_docs(contract / "architecture", req_id),
        "tasks": tasks,
        "evidence": evidence,
        "verification": [
            {"id": item.get("id"), "result": item.get("result"), "layer": item.get("layer")}
            for item in _dedupe_by_id(verification)
        ],
        # BUG 按 id 去重（历史 archive 与 active 可能同名）
        "bugs": [
            {"id": item.get("id"), "status": item.get("status"), "severity": item.get("severity")}
            for item in _dedupe_by_id(bugs)
        ],
        "improvements": [
            {
                "id": item.get("id"),
                "kind": item.get("kind") or item.get("source_record"),
                "status": item.get("status"),
            }
            for item in _dedupe_by_id(improvements)
        ],
        "releases": _release_refs(contract, req_id),
    }


def _release_refs(contract: Path, req_id: str) -> list[dict[str, Any]]:
    items = []
    for path in sorted((contract / "release").glob("RELEASE-*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (yaml.YAMLError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        ids = [
            str(item.get("id"))
            for item in data.get("requirements") or []
            if isinstance(item, dict)
        ]
        if req_id in ids:
            items.append(
                {
                    "version": data.get("project_version"),
                    "status": data.get("status"),
                }
            )
    return items


def trace(
    project: str | Path,
    req_id: str | None = None,
    *,
    roadmap: str | None = None,
    include_archive: bool = False,
) -> dict[str, Any]:
    contract = resolve_contract(project)
    if req_id:
        _, item = _find(contract, req_id)
        return {
            req_id: {
                "title": item.get("title"),
                **trace_requirement(
                    contract, req_id, roadmap=roadmap, include_archive=include_archive
                ),
            }
        }
    result = {}
    for item in _load(contract)["requirements"]:
        if roadmap and item.get("roadmap") != roadmap:
            continue
        rid = str(item.get("id"))
        result[rid] = {
            "title": item.get("title"),
            **trace_requirement(
                contract, rid, roadmap=roadmap, include_archive=include_archive
            ),
        }
    write_trace_file(contract, result)
    return result


def write_trace_file(contract: Path, result: dict[str, Any]) -> Path:
    lines = [
        "# 追踪矩阵",
        "",
        "> 由 `mf req trace` 生成；只保留活跃/索引，不复制全量。",
        "",
        "| REQ | 标题 | SPEC | TASK | 证据 | VR | BUG | MFP/CHG | RELEASE |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for req_id, entry in result.items():
        lines.append(
            "| {req} | {title} | {specs} | {tasks} | {evidence} | {vr} | {bugs} | {improvements} | {releases} |".format(
                req=req_id,
                title=str(entry.get("title") or "").replace("|", "\\|"),
                specs=", ".join(entry.get("specs") or []) or "-",
                tasks=", ".join(f"{t['id']}({t.get('status')})" for t in entry.get("tasks") or []) or "-",
                evidence=", ".join(entry.get("evidence") or []) or "-",
                vr=", ".join(f"{v['id']}({v.get('result')})" for v in entry.get("verification") or []) or "-",
                bugs=", ".join(f"{b['id']}({b.get('status')})" for b in entry.get("bugs") or []) or "-",
                improvements=", ".join(
                    f"{item['id']}({item.get('status')})"
                    for item in entry.get("improvements") or []
                )
                or "-",
                releases=", ".join(
                    f"{item.get('version')}({item.get('status')})"
                    for item in entry.get("releases") or []
                )
                or "-",
            )
        )
    path = contract / "requirements" / "TRACE.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def refresh_index(contract: Path) -> Path:
    data = _load(contract)
    lines = [
        "# 需求索引",
        "",
        "> 由 `mf req add/update` 生成；结构化真相见 `REQUIREMENTS.yaml`。",
        "",
        "| ID | 标题 | 优先级 | 状态 | 路标 |",
        "|---|---|---|---|---|",
    ]
    for item in data["requirements"]:
        lines.append(
            f"| {item.get('id')} | {item.get('title')} | {item.get('priority')} | "
            f"{item.get('status')} | {item.get('roadmap')} |"
        )
    path = contract / "requirements" / "INDEX.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def orphans(contract: Path, *, roadmap: str | None = None) -> list[str]:
    """追踪闭环孤儿检查（MFP-0020 E1）。

    检查 REQ→SPEC→TASK→证据→VR→RELEASE 与 BUG/MFP/CHG 关联：
    - REQ 无 SPEC/TASK/证据/VR；
    - TASK 无 REQ/SPEC；
    - 任务 accepted 但关联 BUG 未关闭；未关闭 BUG 无修复任务；
    - MFP 无验收/实施证据；CHG 未闭环。
    """
    issues: list[str] = []
    tasks: dict[str, dict[str, Any]] = {}
    for path in sorted((contract / "roadmap").glob("*/phases/*/tasks/T*/TASK.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (yaml.YAMLError, OSError):
            continue
        if isinstance(data, dict) and data.get("id"):
            tasks[str(data["id"])] = data

    bugs: dict[str, dict[str, Any]] = {}
    for path in sorted((contract / "bugs").glob("BUG-*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (yaml.YAMLError, OSError):
            continue
        if isinstance(data, dict) and data.get("id"):
            bugs[str(data["id"])] = data

    for item in _load(contract)["requirements"]:
        req_id = str(item.get("id") or "")
        status = str(item.get("status") or "")
        if roadmap and item.get("roadmap") != roadmap:
            continue
        if status in {"deferred", "rejected", "proposed", "accepted"}:
            continue
        entry = trace_requirement(contract, req_id, roadmap=roadmap)
        if not entry["specs"]:
            issues.append(f"{req_id} 无 SPEC 关联")
        if not entry["tasks"]:
            issues.append(f"{req_id} 无 TASK 关联")
        if entry["tasks"] and not entry["evidence"]:
            issues.append(f"{req_id} 关联任务无证据")
        if status in {"verified", "released"} and not entry["verification"]:
            issues.append(f"{req_id} 状态 {status} 但无 VR")

    for task_id, data in tasks.items():
        if data.get("status") == "cancelled":
            continue
        inputs = data.get("inputs") or {}
        refs = inputs.get("requirements") or []
        specs = inputs.get("specs") or data.get("spec_ids") or []
        if not refs and not specs:
            issues.append(f"任务 {task_id} 无 REQ/SPEC 关联")

    for task_id, data in tasks.items():
        if data.get("status") != "accepted":
            continue
        for bug_id in data.get("fixes") or []:
            bug = bugs.get(str(bug_id))
            if bug is None:
                issues.append(f"任务 {task_id} fixes 不存在的 BUG {bug_id}")
            elif bug.get("status") != "closed":
                issues.append(f"任务 {task_id} 已 accepted 但 BUG {bug_id} 未关闭")

    fix_refs = {
        str(bug_id)
        for data in tasks.values()
        for bug_id in (data.get("fixes") or [])
    }
    for bug_id, bug in bugs.items():
        status = str(bug.get("status") or "")
        if status in {"closed", "deferred", "wontfix"}:
            continue
        if not bug.get("fix_task") and bug_id not in fix_refs:
            issues.append(f"BUG {bug_id} 未关闭且无修复任务")

    improvements_dir = contract / "improvements"
    if improvements_dir.is_dir():
        for path in sorted(improvements_dir.glob("MFP-*.yaml")):
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except (yaml.YAMLError, OSError):
                continue
            if not isinstance(data, dict):
                continue
            status = str(data.get("status") or "draft")
            if status in {"draft", "rejected", "deferred", "duplicate"}:
                continue
            if not data.get("acceptance"):
                issues.append(f"{data.get('id') or path.stem} 无验收标准")
            if status in {"implemented", "verified", "closed"}:
                resolution = data.get("resolution") or {}
                if not (resolution.get("version") or resolution.get("tests")):
                    issues.append(f"{data.get('id') or path.stem} 无实施证据（version/tests）")

    records_dir = improvements_dir / "records" if improvements_dir.is_dir() else None
    if records_dir is not None and records_dir.is_dir():
        for path in sorted(records_dir.glob("CHG-*.yaml")):
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except (yaml.YAMLError, OSError):
                continue
            if isinstance(data, dict) and data.get("status") not in {"done", "closed"}:
                issues.append(f"{data.get('id') or path.stem} CHG 未闭环")
    return issues


def validate_all(project: str | Path) -> list[str]:
    contract = resolve_contract(project)
    errors = []
    for item in _load(contract)["requirements"]:
        for error in validate_dor(item):
            errors.append(f"{item.get('id')}: {error}")
    return errors
