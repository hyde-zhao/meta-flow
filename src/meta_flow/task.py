"""任务卡、评审任务、提示词与验收状态机。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from . import bug, knowledge
from .state import ledger_append, refresh_current, task_summary
from .workspace import load_current_state, resolve_contract

TASK_ID_RE = re.compile(r"^(R\d+)-(P\d+)-T(\d{3})$")
RISKS = ("low", "medium", "high", "critical")
KINDS = ("implement", "design", "verify", "document", "review", "fix")
DEFAULT_REVIEW = {
    "low": "manager",
    "medium": "independent",
    "high": "independent",
    "critical": "user",
}
CHECKLIST = ["requirements", "design", "contracts", "tests", "security", "scope", "maintainability"]


class TaskError(Exception):
    """任务操作失败。"""

    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _lease_expired(data: dict[str, Any]) -> bool:
    lease = data.get("lease") or {}
    raw = lease.get("expires_at")
    if not raw:
        return True
    try:
        return datetime.fromisoformat(str(raw)) <= datetime.now(UTC)
    except ValueError:
        return True


def _new_lease(owner: str = "worker", task_id: str | None = None, wave: str = "W1") -> dict[str, Any]:
    return {
        "owner": owner,
        "actor_id": os.environ.get("MF_WORKER_ID") or owner,
        "task": task_id,
        "wave": wave,
        "started_at": _now(),
        "expires_at": (datetime.now(UTC).replace(microsecond=0) + timedelta(hours=2)).isoformat(),
    }


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise TaskError(f"缺少文件: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise TaskError(f"{path} 不是合法 YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise TaskError(f"{path} 顶层必须是映射")
    return data


def _save(path: Path, data: dict[str, Any]) -> None:
    data["updated_at"] = _now()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _bundle(contract: Path, task_id: str) -> Path:
    match = TASK_ID_RE.fullmatch(task_id)
    if not match:
        raise TaskError(f"任务 ID 非法: {task_id}；应为 R1-P3-T001")
    roadmap, phase, num = match.groups()
    return contract / "roadmap" / roadmap / "phases" / phase / "tasks" / f"T{num}"


def _task_path(contract: Path, task_id: str) -> Path:
    return _bundle(contract, task_id) / "TASK.yaml"


def _next_num(tasks_dir: Path) -> int:
    numbers = [
        int(match.group(1))
        for path in tasks_dir.glob("T[0-9][0-9][0-9]")
        if (match := re.fullmatch(r"T(\d{3})", path.name))
    ]
    return max(numbers, default=0) + 1


def _task_data(
    task_id: str,
    title: str,
    kind: str,
    roadmap: str,
    phase: str,
    *,
    delivery: str | None,
    risk: str,
    effort: str,
    review_mode: str,
    reviews: str | None,
    review_scope: list[str],
    allowed_paths: list[str],
    acceptance: list[Any],
    inputs: dict[str, Any],
    status: str,
    next_owner: str,
) -> dict[str, Any]:
    return {
        "id": task_id,
        "title": title,
        "kind": kind,
        "status": status,
        "owner_role": "worker",
        "next_owner": next_owner,
        "roadmap": roadmap,
        "phase": phase,
        "delivery": delivery,
        "wave": "W1",
        "depends_on": [],
        "fixes": [],
        "lease": None,
        "effort": effort,
        "risk": {
            "level": risk,
            "score": None,
            "factors": {},
            "rationale": "",
        },
        "review": {
            "mode": review_mode,
            "scope": review_scope,
            "checklist": CHECKLIST,
        },
        "reviews": reviews,
        "reviewed_by_task": None,
        "review_verdict": None,
        "inputs": inputs,
        "allowed_paths": allowed_paths,
        "forbidden": ["contracts/**", "../**"],
        "deliverables": [],
        "acceptance": acceptance,
        "handoff": "required",
        "dev_record": "required" if kind != "review" else "optional",
        "created_at": _now(),
        "updated_at": _now(),
        "started_at": None,
        "submitted_at": None,
        "accepted_at": None,
        "rejection_reason": None,
    }


def create_task(
    project: str | Path,
    title: str,
    *,
    kind: str = "implement",
    delivery: str | None = None,
    risk: str = "medium",
    effort: str = "M",
    review_mode: str | None = None,
    reviews: str | None = None,
    review_scope: list[str] | None = None,
    allowed_paths: list[str] | None = None,
    acceptance: list[Any] | None = None,
    inputs: dict[str, Any] | None = None,
    wave: str = "W1",
    depends_on: list[str] | None = None,
    fixes: list[str] | None = None,
    with_review: bool = True,
    from_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """创建任务卡；中高风险自动创建独立 review 任务。"""
    contract = resolve_contract(project)
    state = load_current_state(contract)
    roadmap = str(state.get("roadmap") or "R1")
    phase = str(state.get("phase") or "P1")

    data = dict(from_data or {})
    title = str(data.get("title") or title)
    kind = str(data.get("kind") or kind)
    risk = str(data.get("risk", {}).get("level") if isinstance(data.get("risk"), dict) else data.get("risk") or risk)
    if kind not in KINDS:
        raise TaskError(f"kind 只能是 {'|'.join(KINDS)}")
    if risk not in RISKS:
        raise TaskError(f"risk 只能是 {'|'.join(RISKS)}")

    mode = review_mode or (data.get("review") or {}).get("mode") or DEFAULT_REVIEW[risk]
    if mode not in {"manager", "independent", "user"}:
        raise TaskError("review.mode 只能是 manager|independent|user")
    if kind != "review" and risk in {"high", "critical"}:
        if not with_review:
            raise TaskError(f"{risk} 风险任务必须保留独立评审，不能 --no-review")
        if mode == "manager":
            raise TaskError(f"{risk} 风险任务不能降级为 manager 自审；使用 independent 或 user")
    scope = review_scope or (data.get("review") or {}).get("scope") or []
    acceptance = acceptance if acceptance is not None else data.get("acceptance") or []
    inputs = inputs if inputs is not None else data.get("inputs") or {}
    allowed = allowed_paths if allowed_paths is not None else data.get("allowed_paths") or []
    effort = str(data.get("effort") or effort)
    wave = str(data.get("wave") or wave or "W1")
    depends_on = [str(item) for item in (data.get("depends_on") or depends_on or [])]
    fixes = [str(item) for item in (data.get("fixes") or fixes or [])]

    tasks_dir = contract / "roadmap" / roadmap / "phases" / phase / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    num = _next_num(tasks_dir)
    task_id = f"{roadmap}-{phase}-T{num:03d}"
    bundle = _bundle(contract, task_id)
    (bundle / "evidence").mkdir(parents=True, exist_ok=True)

    status = "ready" if acceptance else "draft"
    next_owner = "worker" if status == "ready" else "manager"
    task = _task_data(
        task_id,
        title,
        kind,
        roadmap,
        phase,
        delivery=delivery,
        risk=risk,
        effort=effort,
        review_mode=mode,
        reviews=reviews,
        review_scope=scope,
        allowed_paths=allowed,
        acceptance=acceptance,
        inputs=inputs,
        status=status,
        next_owner=next_owner,
    )
    if isinstance(data.get("risk"), dict):
        task["risk"].update(data["risk"])
    task["wave"] = wave
    task["depends_on"] = depends_on
    task["fixes"] = fixes
    if not task.get("packet_budget"):
        try:
            policy_data = yaml.safe_load(
                (contract / "policies" / "CONTEXT-POLICY.yaml").read_text(encoding="utf-8")
            )
        except (OSError, yaml.YAMLError):
            policy_data = {}
        worker_budget = (
            ((policy_data or {}).get("roles") or {}).get("worker") or {}
        ).get("budget")
        task["packet_budget"] = worker_budget or {"files": 10, "bytes": 65536}

    review_id = None
    if kind != "review" and with_review and mode in {"independent", "user"}:
        review_num = num + 1
        review_id = f"{roadmap}-{phase}-T{review_num:03d}"
        review_bundle = _bundle(contract, review_id)
        (review_bundle / "evidence").mkdir(parents=True, exist_ok=True)
        review_task = _task_data(
            review_id,
            f"Review {task_id}: {title}",
            "review",
            roadmap,
            phase,
            delivery=delivery,
            risk=risk,
            effort="S",
            review_mode="manager",
            reviews=task_id,
            review_scope=scope,
            allowed_paths=[],
            acceptance=[
                {
                    "id": "R1",
                    "method": "artifact",
                    "target": "review-handoff.md",
                    "expect": "结论与必须整改项完整",
                }
            ],
            inputs={"tasks": [task_id]},
            status="draft",
            next_owner="manager",
        )
        review_task["depends_on"] = [task_id]
        review_task["wave"] = wave
        _save(_task_path(contract, review_id), review_task)
        task["reviewed_by_task"] = review_id

    _save(_task_path(contract, task_id), task)
    ledger_append(
        contract,
        {
            "event": "task.create",
            "task": task_id,
            "review_task": review_id,
            "status": status,
            "from": None,
            "to": status,
            "wave": wave,
            "risk": risk,
        },
    )
    refresh_current(contract)
    return {
        "task": task_id,
        "review_task": review_id,
        "bundle": str(bundle),
        "status": status,
        "risk": risk,
        "review_mode": mode,
    }


def list_tasks(
    project: str | Path,
    *,
    status: str | None = None,
    delivery: str | None = None,
) -> list[dict[str, Any]]:
    contract = resolve_contract(project)
    items = []
    for path in sorted((contract / "roadmap").glob("*/phases/*/tasks/T*/TASK.yaml")):
        try:
            data = _load(path)
        except TaskError:
            continue
        if status and data.get("status") != status:
            continue
        if delivery and data.get("delivery") and data.get("delivery") != delivery:
            continue
        data["_path"] = str(path)
        items.append(data)
    return items


def load_task(project: str | Path, task_id: str) -> tuple[Path, dict[str, Any]]:
    contract = resolve_contract(project)
    path = _task_path(contract, task_id)
    return path, _load(path)


def _check_dependencies(contract: Path, task: dict[str, Any]) -> None:
    for dep in task.get("depends_on") or []:
        other = _find_task_data(contract, str(dep))
        if other is None:
            raise TaskError(f"依赖任务不存在: {dep}")
        if task.get("kind") == "review" and str(dep) == str(task.get("reviews")):
            if other.get("status") not in {"submitted", "accepted"}:
                raise TaskError(f"被评审任务 {dep} 尚未 submitted")
        elif other.get("status") != "accepted":
            raise TaskError(f"依赖任务 {dep} 尚未 accepted")


def _check_wave_conflicts(contract: Path, task: dict[str, Any]) -> None:
    wave = str(task.get("wave") or "W1")
    delivery = task.get("delivery")
    for path in sorted((contract / "roadmap").glob("*/phases/*/tasks/T*/TASK.yaml")):
        other = _load(path)
        if other.get("id") == task.get("id") or other.get("status") != "in_progress":
            continue
        if str(other.get("wave") or "W1") != wave:
            continue
        if delivery and other.get("delivery") and other.get("delivery") != delivery:
            continue
        if _paths_conflict(task, other):
            raise TaskError(
                f"同 wave {wave} 有写路径冲突：{task.get('id')} <-> {other.get('id')}；先串行化"
            )


def start_task(
    project: str | Path,
    task_id: str,
    *,
    owner: str | None = None,
) -> dict[str, Any]:
    path, data = load_task(project, task_id)
    status = data.get("status")
    if status == "in_progress" and not _lease_expired(data):
        lease = data.get("lease") or {}
        raise TaskError(f"任务 {task_id} 已被占用（lease 到 {lease.get('expires_at')}）")
    if status not in {"ready", "rejected", "in_progress"}:
        raise TaskError(f"任务 {task_id} 当前状态 {status} 不能 start")
    if data.get("kind") == "review" and data.get("reviews"):
        _, target = load_task(project, str(data["reviews"]))
        if target.get("status") != "submitted":
            raise TaskError(f"被评审任务 {data['reviews']} 尚未 submitted")
        actor = owner or os.environ.get("MF_WORKER_ID")
        if actor and actor not in {"worker"} and target.get("implemented_by") == actor:
            raise TaskError(f"评审者 {actor} 不能评审自己实现的任务 {data['reviews']}")
    contract = resolve_contract(project)
    _check_dependencies(contract, data)
    _check_wave_conflicts(contract, data)
    if data.get("kind") != "review":
        project_path = Path(project).expanduser().resolve()
        exclude = contract if contract.is_relative_to(project_path) else None
        _save_worktree_snapshot(
            project_path,
            path.parent / "evidence" / "worktree-start.json",
            exclude,
        )
    data["status"] = "in_progress"
    data["next_owner"] = "worker"
    data["started_at"] = _now()
    lease = _new_lease(owner or "worker", task_id, str(data.get("wave") or "W1"))
    data["lease"] = lease
    _save(path, data)
    ledger_append(
        contract,
        {"event": "task.start", "task": task_id, "lease": lease["expires_at"], "owner": lease["owner"], "from": status, "to": "in_progress"},
    )
    refresh_current(contract)
    return data


def _capture_diff(project: Path, target: Path) -> None:
    inside = subprocess.run(
        ["git", "-C", str(project), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
        check=False,
    )
    if inside.returncode != 0:
        return
    chunks = []
    for args in (["diff", "--binary"], ["diff", "--cached", "--binary"]):
        result = subprocess.run(
            ["git", "-C", str(project), *args],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.stdout.strip():
            chunks.append(result.stdout)
    if chunks:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(chunks), encoding="utf-8")


def _git_names(project: Path, args: list[str]) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(project), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [item for item in result.stdout.split("\0") if item]


def _changed_files(
    project: Path,
    bundle: Path | None = None,
    exclude: Path | None = None,
) -> list[str] | None:
    snapshot_path = bundle / "evidence" / "worktree-start.json" if bundle else None
    if bundle is not None and snapshot_path is not None and snapshot_path.is_file():
        return _snapshot_changes(project, bundle, exclude)
    inside = subprocess.run(
        ["git", "-C", str(project), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
        check=False,
    )
    if inside.returncode != 0:
        return None
    names = set()
    for args in (
        ["diff", "--name-only", "-z"],
        ["diff", "--cached", "--name-only", "-z"],
        ["ls-files", "--others", "--exclude-standard", "-z"],
    ):
        names.update(_git_names(project, args))
    return sorted(names)


_SNAPSHOT_SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".mypy_cache"}


def _worktree_snapshot(project: Path, exclude: Path | None = None) -> dict[str, list[int]]:
    snapshot: dict[str, list[int]] = {}
    if not project.is_dir():
        return snapshot
    resolved_exclude = exclude.resolve() if exclude else None
    for path in project.rglob("*"):
        if not path.is_file() or any(part in _SNAPSHOT_SKIP for part in path.parts):
            continue
        if resolved_exclude is not None and path.resolve().is_relative_to(resolved_exclude):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        snapshot[str(path.relative_to(project))] = [stat.st_mtime_ns, stat.st_size]
        if len(snapshot) >= 5000:
            break
    return snapshot


def _save_worktree_snapshot(project: Path, target: Path, exclude: Path | None = None) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(_worktree_snapshot(project, exclude), ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def _snapshot_changes(project: Path, bundle: Path, exclude: Path | None = None) -> list[str] | None:
    snapshot_path = bundle / "evidence" / "worktree-start.json"
    if not snapshot_path.is_file():
        return None
    try:
        before = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    after = _worktree_snapshot(project, exclude)
    changed = set()
    for path, meta in after.items():
        if path not in before or list(meta) != list(before[path]):
            changed.add(path)
    for path in before:
        if path not in after:
            changed.add(path)
    return sorted(changed)


def _validate_changed_paths(
    project: Path,
    data: dict[str, Any],
    bundle: Path,
    exclude: Path | None = None,
) -> list[str]:
    changed = _changed_files(project, bundle, exclude)
    if changed is None:
        return []
    forbidden = [str(item) for item in data.get("forbidden") or []]
    allowed = [str(item) for item in data.get("allowed_paths") or []]
    violations = []
    for path in changed:
        if _matches(path, forbidden):
            violations.append(f"{path} (forbidden)")
        elif not _matches(path, allowed):
            violations.append(f"{path} (outside allowed_paths)")
    return violations


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
    normalized = path.replace("\\", "/").lstrip("./")
    return any(_glob_regex(str(pattern)).match(normalized) for pattern in patterns)


def submit_task(
    project: str | Path,
    task_id: str,
    *,
    handoff: str | Path | None = None,
    dev_record: str | Path | None = None,
    owner: str | None = None,
) -> dict[str, Any]:
    path, data = load_task(project, task_id)
    if data.get("status") != "in_progress":
        raise TaskError(f"任务 {task_id} 当前状态 {data.get('status')} 不能 submit")
    lease = data.get("lease") or {}
    if owner and lease.get("owner") and lease.get("owner") != owner:
        raise TaskError(f"任务 {task_id} lease owner={lease.get('owner')}，与提交者 {owner} 不一致")
    actor = owner or os.environ.get("MF_WORKER_ID") or lease.get("actor_id") or lease.get("owner")
    contract = resolve_contract(project)
    project_path = Path(project).expanduser().resolve()
    exclude = contract if contract.is_relative_to(project_path) else None
    bundle = path.parent
    if data.get("kind") != "review":
        violations = _validate_changed_paths(project_path, data, bundle, exclude)
        if violations:
            raise TaskError(
                "变更超出 allowed_paths/forbidden，拒绝提交：\n  - " + "\n  - ".join(violations)
            )
    handoff_path = Path(handoff) if handoff else bundle / "handoff.md"
    if not handoff_path.is_file() or not handoff_path.read_text(encoding="utf-8").strip():
        raise TaskError(f"缺少有效交接文件: {handoff_path}")

    if data.get("kind") == "review":
        for name in ("review.md", "review-handoff.md"):
            item = bundle / name
            if not item.is_file() or not item.read_text(encoding="utf-8").strip():
                raise TaskError(f"评审任务缺少 {name}")
    elif data.get("dev_record") == "required":
        dev_path = Path(dev_record) if dev_record else bundle / "dev-record.md"
        if not dev_path.is_file() or not dev_path.read_text(encoding="utf-8").strip():
            raise TaskError(f"缺少开发记录: {dev_path}")

    if data.get("kind") == "fix":
        fix_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (bundle / "dev-record.md", handoff_path)
            if path.is_file()
        )
        missing = [keyword for keyword in ("根因", "修复", "回归") if keyword not in fix_text]
        if missing:
            raise TaskError("fix 任务缺少交接章节关键字: " + "、".join(missing))

    if data.get("kind") != "review":
        _capture_diff(Path(project).expanduser().resolve(), bundle / "evidence" / "diff.patch")

    data["status"] = "submitted"
    data["submitted_at"] = _now()
    if actor:
        if data.get("kind") == "review":
            data["reviewed_by"] = actor
        else:
            data["implemented_by"] = actor
    if data.get("kind") == "review":
        data["next_owner"] = "manager"
    elif data.get("reviewed_by_task"):
        data["next_owner"] = "worker"
        review_path, review_task = load_task(project, str(data["reviewed_by_task"]))
        review_task["status"] = "ready"
        review_task["next_owner"] = "worker"
        _save(review_path, review_task)
    else:
        data["next_owner"] = "manager"
    data["lease"] = None
    _save(path, data)
    ledger_append(
        resolve_contract(project),
        {
            "event": "task.submit",
            "task": task_id,
            "next_owner": data["next_owner"],
            "from": "in_progress",
            "to": "submitted",
            "evidence_digest": _evidence_digest(bundle),
        },
    )
    refresh_current(resolve_contract(project))
    return data


REVIEW_VERDICT_RE = re.compile(
    r"verdict\s*[:=]\s*(PASS_WITH_RISK|PASS|NEEDS_REWORK|BLOCKED)", re.IGNORECASE
)


def _read_review_verdict(bundle: Path) -> str | None:
    for name in ("review-handoff.md", "review.md"):
        path = bundle / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        match = REVIEW_VERDICT_RE.search(text)
        if match:
            return match.group(1).upper()
        for verdict in ("PASS_WITH_RISK", "NEEDS_REWORK", "BLOCKED", "PASS"):
            if verdict in text:
                return verdict
    return None


def _evidence_digest(bundle: Path) -> str:
    digest = hashlib.sha256()
    for name in ("dev-record.md", "handoff.md", "review.md", "review-handoff.md", "evidence/diff.patch"):
        path = bundle / name
        if path.is_file():
            digest.update(name.encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def accept_task(
    project: str | Path,
    task_id: str,
    *,
    verdict: str = "PASS",
    note: str | None = None,
    user_approved_by: str | None = None,
) -> dict[str, Any]:
    path, data = load_task(project, task_id)
    if data.get("status") != "submitted":
        raise TaskError(f"任务 {task_id} 当前状态 {data.get('status')} 不能 accept")
    if verdict not in {"PASS", "PASS_WITH_RISK", "NEEDS_REWORK", "BLOCKED"}:
        raise TaskError("verdict 非法")

    if data.get("kind") == "review":
        recorded = _read_review_verdict(path.parent)
        if recorded is None:
            raise TaskError("评审任务缺少 verdict：在 review-handoff.md 写明结论")
        if recorded != verdict:
            raise TaskError(f"评审文件结论为 {recorded}，与 accept verdict {verdict} 不一致")
        data["review_verdict"] = verdict
        data["status"] = "accepted"
        data["next_owner"] = "manager"
        data["accepted_at"] = _now()
        data["acceptance_note"] = note
        _save(path, data)
        if data.get("reviews"):
            target_path, target = load_task(project, str(data["reviews"]))
            target["review_verdict"] = verdict
            target["next_owner"] = "manager"
            _save(target_path, target)
        ledger_append(
            resolve_contract(project),
            {"event": "task.accept", "task": task_id, "kind": "review", "verdict": verdict, "from": "submitted", "to": "accepted"},
        )
        refresh_current(resolve_contract(project))
        return data

    if str((data.get("risk") or {}).get("level")) == "critical" and not user_approved_by:
        raise TaskError("critical 任务需要用户验收：--user-approved-by <用户/记录>")
    if user_approved_by:
        data["user_approved_by"] = user_approved_by
        data["user_approved_at"] = _now()

    review_id = data.get("reviewed_by_task")
    if review_id:
        _, review_task = load_task(project, str(review_id))
        if review_task.get("status") != "accepted":
            raise TaskError(f"必须先接受 review 任务 {review_id}")
        if review_task.get("review_verdict") not in {"PASS", "PASS_WITH_RISK"}:
            raise TaskError(f"review 任务 {review_id} 结论不是 PASS")

    data["status"] = "accepted"
    data["next_owner"] = "manager"
    data["accepted_at"] = _now()
    data["acceptance_note"] = note
    data["acceptance_verdict"] = verdict
    _save(path, data)
    contract = resolve_contract(project)
    for bug_id in data.get("fixes") or []:
        bug.mark_fixed(contract, str(bug_id), task_id)
    ledger_append(
        contract,
        {"event": "task.accept", "task": task_id, "verdict": verdict, "fixes": data.get("fixes") or [], "from": "submitted", "to": "accepted"},
    )
    refresh_current(contract)
    return data


def reject_task(project: str | Path, task_id: str, reason: str) -> dict[str, Any]:
    if not reason.strip():
        raise TaskError("reject 必须给出原因")
    path, data = load_task(project, task_id)
    if data.get("status") not in {"submitted", "in_progress"}:
        raise TaskError(f"任务 {task_id} 当前状态 {data.get('status')} 不能 reject")
    previous = str(data.get("status"))
    data["status"] = "rejected"
    data["next_owner"] = "worker"
    data["rejection_reason"] = reason
    data["lease"] = None
    _save(path, data)
    review_id = data.get("reviewed_by_task")
    if review_id:
        review_path, review_task = load_task(project, str(review_id))
        review_task["status"] = "ready"
        review_task["next_owner"] = "worker"
        review_task["review_verdict"] = None
        _save(review_path, review_task)
    ledger_append(
        resolve_contract(project),
        {"event": "task.reject", "task": task_id, "reason": reason, "from": previous, "to": "rejected"},
    )
    refresh_current(resolve_contract(project))
    return data


def _find_task_data(contract: Path, task_id: str) -> dict[str, Any] | None:
    path = _task_path(contract, task_id)
    if not path.is_file():
        return None
    try:
        return _load(path)
    except TaskError:
        return None


def _deps_satisfied(contract: Path, task: dict[str, Any]) -> bool:
    for dep in task.get("depends_on") or []:
        other = _find_task_data(contract, str(dep))
        if other is None:
            return False
        if task.get("kind") == "review" and str(dep) == str(task.get("reviews")):
            if other.get("status") not in {"submitted", "accepted"}:
                return False
        elif other.get("status") != "accepted":
            return False
    return True


def _dependency_cycles(tasks: list[dict[str, Any]]) -> list[str]:
    """用 Kahn 拓扑排序找出依赖环或依赖环上的任务。"""
    ids = {str(task.get("id")) for task in tasks}
    deps = {
        str(task.get("id")): [str(dep) for dep in task.get("depends_on") or [] if str(dep) in ids]
        for task in tasks
    }
    reverse: dict[str, list[str]] = {task_id: [] for task_id in ids}
    indegree = {task_id: len(values) for task_id, values in deps.items()}
    for task_id, values in deps.items():
        for dep in values:
            reverse[dep].append(task_id)
    queue = [task_id for task_id, count in indegree.items() if count == 0]
    visited = []
    while queue:
        current = queue.pop()
        visited.append(current)
        for follower in reverse[current]:
            indegree[follower] -= 1
            if indegree[follower] == 0:
                queue.append(follower)
    return sorted(ids - set(visited))


def graph(project: str | Path) -> dict[str, Any]:
    tasks = list_tasks(project)
    nodes = []
    edges = []
    known = {str(task.get("id")) for task in tasks}
    for task in tasks:
        task_id = str(task.get("id"))
        nodes.append(
            {
                "id": task_id,
                "status": task.get("status"),
                "wave": task.get("wave") or "W1",
                "kind": task.get("kind"),
                "risk": (task.get("risk") or {}).get("level"),
            }
        )
        for dep in task.get("depends_on") or []:
            if str(dep) in known:
                edges.append({"from": str(dep), "to": task_id, "type": "depends_on"})
        if task.get("kind") == "review" and task.get("reviews"):
            edges.append({"from": str(task["reviews"]), "to": task_id, "type": "review"})
    return {"nodes": nodes, "edges": edges, "cycles": _dependency_cycles(tasks)}


def _normalize_path(pattern: str) -> str:
    return pattern.rstrip("*").rstrip("/")


def _paths_conflict(left: dict[str, Any], right: dict[str, Any]) -> bool:
    for a in left.get("allowed_paths") or []:
        for b in right.get("allowed_paths") or []:
            na, nb = _normalize_path(str(a)), _normalize_path(str(b))
            if na and nb and (na == nb or na.startswith(nb + "/") or nb.startswith(na + "/")):
                return True
    return False


def plan_tasks(project: str | Path) -> dict[str, Any]:
    contract = resolve_contract(project)
    tasks = list_tasks(project)
    cycles = _dependency_cycles(tasks)
    if cycles:
        raise TaskError("任务依赖存在环: " + ", ".join(cycles))
    ready = []
    blocked = []
    for task in tasks:
        if task.get("status") not in {"ready", "rejected"}:
            continue
        item = {
            "id": task.get("id"),
            "title": task.get("title"),
            "wave": task.get("wave") or "W1",
            "kind": task.get("kind"),
            "risk": (task.get("risk") or {}).get("level"),
            "depends_on": task.get("depends_on") or [],
            "allowed_paths": task.get("allowed_paths") or [],
        }
        if _deps_satisfied(contract, task):
            ready.append(item)
        else:
            blocked.append(item)
    waves: dict[str, list[dict[str, Any]]] = {}
    for item in ready:
        waves.setdefault(str(item["wave"]), []).append(item)
    conflicts = []
    for wave, items in waves.items():
        for index, left in enumerate(items):
            for right in items[index + 1 :]:
                if _paths_conflict(left, right):
                    conflicts.append({"wave": wave, "a": left["id"], "b": right["id"]})
    return {"ready": ready, "blocked": blocked, "waves": waves, "conflicts": conflicts}


def next_tasks(project: str | Path, *, limit: int = 10) -> list[dict[str, Any]]:
    contract = resolve_contract(project)
    items = []
    for task in list_tasks(project):
        if task.get("status") not in {"ready", "rejected"}:
            continue
        if not _deps_satisfied(contract, task):
            continue
        items.append(
            {
                "id": task.get("id"),
                "title": task.get("title"),
                "wave": task.get("wave") or "W1",
                "kind": task.get("kind"),
                "risk": (task.get("risk") or {}).get("level"),
                "next_owner": task.get("next_owner"),
            }
        )
    items.sort(key=lambda item: (str(item["wave"]), str(item["id"])))
    return items[:limit]


def release_task(
    project: str | Path,
    task_id: str,
    *,
    reason: str = "lease 释放",
    force: bool = False,
) -> dict[str, Any]:
    path, data = load_task(project, task_id)
    if data.get("status") not in {"ready", "rejected", "in_progress"}:
        raise TaskError(f"任务 {task_id} 当前状态 {data.get('status')} 不能 release")
    previous = str(data.get("status"))
    if data.get("status") == "in_progress" and not _lease_expired(data) and not force:
        raise TaskError(f"任务 {task_id} lease 未过期；manager 回收需 --force")
    data["status"] = "ready"
    data["next_owner"] = "worker"
    data["lease"] = None
    data["release_reason"] = reason
    _save(path, data)
    ledger_append(
        resolve_contract(project),
        {"event": "task.release", "task": task_id, "reason": reason, "from": previous, "to": "ready"},
    )
    refresh_current(resolve_contract(project))
    return data


def summary(project: str | Path) -> dict[str, Any]:
    contract = resolve_contract(project)
    data = task_summary(contract)
    data["next"] = next_tasks(project, limit=5)
    data["open_bugs"] = len(bug.open_blockers(project))
    return data


def _find_input(contract: Path, ref: str) -> tuple[Path, str] | None:
    standards = contract / "standards" / f"{ref}.md"
    if standards.is_file():
        return standards, standards.read_text(encoding="utf-8")
    candidates: list[Path] = []
    for directory in ("requirements", "architecture", "specs"):
        base = contract / directory
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in {".md", ".yaml", ".yml", ".json"}:
                continue
            if "drafts" in path.parts or path.name.endswith(".bak"):
                continue
            if path.stat().st_size > 1024 * 1024:
                continue
            candidates.append(path)
            if ref in path.name:
                return path, path.read_text(encoding="utf-8")
    pattern = re.compile(rf"(?<![A-Za-z0-9_-]){re.escape(ref)}(?![A-Za-z0-9_-])")
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if pattern.search(text):
            return path, text
    return None


def packet_text(project: str | Path, task_id: str, *, review: bool = False) -> str:
    contract = resolve_contract(project)
    path, data = load_task(project, task_id)
    bundle = path.parent
    budget = data.get("packet_budget") or {}
    max_files = int(budget.get("files", 10))
    max_bytes = int(budget.get("bytes", 65536))
    input_refs = [
        str(ref)
        for refs in (data.get("inputs") or {}).values()
        for ref in (refs if isinstance(refs, list) else [refs])
    ]
    if len(input_refs) > max_files:
        raise TaskError(f"任务包输入文件数 {len(input_refs)} 超过预算 {max_files}")
    lines = [f"# {'REVIEW PACKET' if review else 'TASK PACKET'} {task_id}", ""]
    lines.append("## Read policy")
    lines.append(f"- must_read: TASK.yaml, {', '.join(input_refs) or '(none)'}")
    lines.append("- may_read: 自己的任务 bundle、allowed_paths；评审任务另加 review_scope")
    lines.append("- do_not_read: 其他任务、其他版本、archive、完整契约库")
    lines.append(f"- budget: files={max_files}, bytes={max_bytes}")
    lines.append("")
    lines.append("## Task")
    lines.append("```yaml")
    lines.append(yaml.safe_dump(data, sort_keys=False, allow_unicode=True).strip())
    lines.append("```")
    lines.append("")

    lines.append("## Inputs")
    inputs = data.get("inputs") or {}
    found_any = False
    for category, refs in inputs.items():
        if not isinstance(refs, list):
            refs = [refs]
        for ref in refs:
            found = _find_input(contract, str(ref))
            found_any = True
            if found is None:
                lines.append(f"- {category}/{ref}: 未找到")
                continue
            input_path, text = found
            snippet = text[:4000]
            lines.append(f"### {ref} ({input_path.relative_to(contract)})")
            lines.append("```text")
            lines.append(snippet)
            if len(text) > 4000:
                lines.append("... (truncated; expand with mf context)")
            lines.append("```")
    if not found_any:
        lines.append("(none)")

    lines.append("")
    lines.append("## Project knowledge")
    knowledge_lines = knowledge.packet_lines(contract, delivery=data.get("delivery"))
    if knowledge_lines:
        lines.extend(knowledge_lines)
    else:
        lines.append("(none)")
    lines.append("")

    lines.append("## Allowed paths")
    for item in data.get("allowed_paths") or []:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Acceptance")
    for item in data.get("acceptance") or []:
        lines.append("```yaml")
        lines.append(yaml.safe_dump(item, sort_keys=False, allow_unicode=True).strip())
        lines.append("```")
    lines.append("")
    lines.append("## Handoff")
    lines.append(f"- 写入: {bundle / 'handoff.md'}")
    lines.append(f"- 提交: mf task submit {task_id} --handoff {bundle / 'handoff.md'}")
    lines.append("")
    lines.append("## Responsibility")
    lines.append(f"- next_owner: {data.get('next_owner')}")
    lines.append(f"- risk: {(data.get('risk') or {}).get('level')}")
    lines.append(f"- review_mode: {(data.get('review') or {}).get('mode')}")
    if data.get("reviewed_by_task"):
        lines.append(f"- review_task: {data['reviewed_by_task']}")
    if data.get("reviews"):
        lines.append(f"- reviews: {data['reviews']}")

    if review:
        lines.append("")
        lines.append("## Implementation Dev Record")
        dev = bundle / "dev-record.md"
        lines.append(dev.read_text(encoding="utf-8") if dev.is_file() else "(missing)")
        lines.append("")
        lines.append("## Implementation Handoff")
        handoff = bundle / "handoff.md"
        lines.append(handoff.read_text(encoding="utf-8") if handoff.is_file() else "(missing)")
        lines.append("")
        lines.append("## Diff")
        diff = bundle / "evidence" / "diff.patch"
        if diff.is_file():
            lines.append("```diff")
            lines.append(diff.read_text(encoding="utf-8")[:12000])
            lines.append("```")
        else:
            lines.append("(no diff captured)")
        lines.append("")
        lines.append("## Review Output")
        lines.append(f"- 评审意见: {bundle / 'review.md'}")
        lines.append(f"- 评审交接: {bundle / 'review-handoff.md'}")

    text = "\n".join(lines).rstrip() + "\n"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    text += f"\npacket_digest: {digest}\n"
    if len(text.encode("utf-8")) > max_bytes:
        raise TaskError(
            f"任务包 {len(text.encode('utf-8'))} 字节超过预算 {max_bytes}；缩小 inputs 或分批任务"
        )
    target = bundle / ("review-packet.md" if review else "packet.md")
    target.write_text(text, encoding="utf-8")
    digest_name = "review-packet.sha256" if review else "packet.sha256"
    (bundle / digest_name).write_text(digest + "\n", encoding="utf-8")
    return text


def prompt_text(project: str | Path, task_id: str) -> str:
    _, data = load_task(project, task_id)
    status = str(data.get("status"))
    kind = str(data.get("kind"))
    risk = str((data.get("risk") or {}).get("level"))
    review_id = data.get("reviewed_by_task")
    review_task = None
    if review_id:
        _, review_task = load_task(project, str(review_id))
    bundle = _bundle(resolve_contract(project), task_id)

    if (
        status == "submitted"
        and kind != "review"
        and review_id
        and review_task
        and review_task.get("status") in {"ready", "in_progress", "rejected"}
    ):
        text = prompt_text(project, str(review_id))
        return f"parent_task: {task_id}\nreview_task: {review_id}\n\n{text}"

    if status == "draft":
        owner = "manager"
    elif status in {"ready", "in_progress", "rejected"}:
        owner = "worker"
    elif status == "submitted":
        if kind != "review" and review_task and review_task.get("status") in {"ready", "in_progress"}:
            owner = "worker"
        else:
            owner = "manager"
    else:
        owner = "manager"

    lines = [
        f"responsible_agent: {owner}",
        f"task: {task_id}",
        f"kind: {kind}",
        f"status: {status}",
        f"risk: {risk}",
        f"next_owner: {data.get('next_owner')}",
        "",
    ]
    if owner == "worker":
        if kind == "review":
            lines.extend(
                [
                    f"你是独立评审者，不得是实现者。先运行：mf task show {task_id} --review-packet",
                    "只读任务包、diff、开发记录、交接和 review_scope 内源码；不要修改实现代码。",
                    f"在 {bundle / 'review.md'} 写评审意见，在 {bundle / 'review-handoff.md'} 写评审交接。",
                    "通过：结论 PASS，然后 mf task submit；由 manager 验收。",
                    "不通过：结论 NEEDS_REWORK，列出必须整改项（ID/文件/行/要求/验收方法），submit；manager 会退回 worker1。",
                ]
            )
        elif status == "rejected":
            lines.extend(
                [
                    "先读取 review.md 和 review-handoff.md，只整改必须整改项。",
                    f"完成后更新 {bundle / 'dev-record.md'} 和 {bundle / 'handoff.md'}，再 mf task submit。",
                    "等待复审和 manager 验收。",
                ]
            )
        else:
            lines.extend(
                [
                    f"先运行：mf task show {task_id} --packet",
                    f"只写 allowed_paths；完成后写 {bundle / 'dev-record.md'} 和 {bundle / 'handoff.md'}，再 mf task submit。",
                ]
            )
            if review_id:
                lines.append(f"提交后 manager 会推进 review 任务 {review_id}；不要自行验收。")
            else:
                lines.append("提交后由 manager 评审并验收；不要自行验收。")
    else:
        if status == "draft":
            lines.append("任务卡缺验收标准；先补全 acceptance，再置为 ready。")
        elif status == "submitted":
            if kind == "review":
                lines.append(f"先读取 review.md / review-handoff.md，再 mf task accept {task_id}。")
            elif review_id and review_task:
                if review_task.get("status") == "submitted":
                    lines.append(f"先 accept review 任务 {review_id}，再验收 {task_id}。")
                elif review_task.get("status") == "accepted":
                    if review_task.get("review_verdict") in {"PASS", "PASS_WITH_RISK"}:
                        lines.append(f"review 已通过；mf task accept {task_id} --verdict PASS。")
                    else:
                        lines.append(
                            f"review 未通过；mf task reject {task_id} --reason ...，退回 worker1 整改。"
                        )
                else:
                    lines.append(
                        f"等待 review 任务 {review_id} 完成；通过后再 mf task accept {task_id}。"
                    )
            else:
                lines.append(f"先完成 review，再 mf task accept {task_id} 或 mf task reject {task_id}。")
            if risk == "critical":
                lines.append("critical 任务验收必须带 --user-approved-by <用户/记录>。")
        elif status == "accepted":
            lines.append("任务已验收；规划并创建下一个任务卡。")
        else:
            lines.append(f"检查任务状态并决定 accept/reject：mf task show {task_id}。")
    return "\n".join(lines).rstrip() + "\n"
