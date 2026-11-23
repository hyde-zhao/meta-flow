"""分层验证记录与版本冻结。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from . import bug
from .state import ledger_append, read_current, refresh_current, write_current
from .workspace import resolve_contract

LAYERS = ("implementation", "design", "requirement")
RESULTS = ("PASS", "PASS_WITH_RISK", "FAIL", "BLOCKED")
RELEASE_STATUSES = {"verified", "released", "deferred", "rejected"}


class VerifyError(Exception):
    """验证/发布操作失败。"""

    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise VerifyError(f"{path} 不是合法 YAML: {exc}") from exc
    return data if isinstance(data, dict) else {}


def _vr_paths(contract: Path) -> list[Path]:
    return sorted((contract / "verification").glob("VR-*.yaml"))


def _next_vr(contract: Path) -> str:
    numbers = [int(path.stem[3:]) for path in _vr_paths(contract) if path.stem[3:].isdigit()]
    return f"VR-{max(numbers, default=0) + 1:04d}"


def record_verification(
    project: str | Path,
    *,
    layer: str,
    scope: str,
    result: str,
    requirement_refs: list[str] | None = None,
    design_refs: list[str] | None = None,
    task_refs: list[str] | None = None,
    method: str = "artifact",
    evidence: list[str] | None = None,
    bugs: list[str] | None = None,
    verifier: str = "meta-manager",
    notes: str = "",
) -> dict[str, Any]:
    contract = resolve_contract(project)
    if layer not in LAYERS:
        raise VerifyError(f"layer 只能是 {'|'.join(LAYERS)}")
    if result not in RESULTS:
        raise VerifyError(f"result 只能是 {'|'.join(RESULTS)}")
    if not scope.strip():
        raise VerifyError("验证记录必须有 scope")
    if result == "FAIL" and not bugs:
        raise VerifyError("FAIL 验证记录必须关联至少一个 BUG")
    state = read_current(contract)
    vr_id = _next_vr(contract)
    item = {
        "id": vr_id,
        "layer": layer,
        "scope": scope,
        "roadmap": str(state.get("roadmap") or "R1"),
        "phase": str(state.get("phase") or "P1"),
        "requirement_refs": requirement_refs or [],
        "design_refs": design_refs or [],
        "task_refs": task_refs or [],
        "method": method,
        "result": result,
        "evidence": evidence or [],
        "bugs": bugs or [],
        "verifier": verifier,
        "date": _now(),
        "notes": notes,
    }
    path = contract / "verification" / f"{vr_id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(item, sort_keys=False, allow_unicode=True), encoding="utf-8")
    for bug_id in bugs or []:
        try:
            current = bug.show_bug(project, bug_id)
            if result in {"PASS", "PASS_WITH_RISK"} and current.get("status") in {
                "open",
                "triaged",
                "in_progress",
                "reopened",
            }:
                bug.update_bug(project, bug_id, status="verifying")
            elif result == "FAIL":
                bug.update_bug(project, bug_id, status="reopened")
        except bug.BugError:
            continue
    ledger_append(contract, {"event": "verify.record", "vr": vr_id, "layer": layer, "result": result})
    return item


def list_verifications(
    project: str | Path,
    *,
    layer: str | None = None,
    result: str | None = None,
    roadmap: str | None = None,
) -> list[dict[str, Any]]:
    contract = resolve_contract(project)
    items = []
    for path in _vr_paths(contract):
        data = _load_yaml(path)
        if layer and data.get("layer") != layer:
            continue
        if result and data.get("result") != result:
            continue
        if roadmap and data.get("roadmap") not in {None, roadmap}:
            continue
        items.append(data)
    return items


def show_verification(project: str | Path, vr_id: str) -> dict[str, Any]:
    for item in list_verifications(project):
        if item.get("id") == vr_id:
            return item
    raise VerifyError(f"验证记录不存在: {vr_id}")


def _requirements(contract: Path) -> list[dict[str, Any]]:
    data = _load_yaml(contract / "requirements" / "REQUIREMENTS.yaml")
    return list(data.get("requirements") or [])


def _tasks(contract: Path, roadmap_id: str) -> list[dict[str, Any]]:
    items = []
    for path in sorted((contract / "roadmap" / roadmap_id).glob("phases/*/tasks/T*/TASK.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError):
            continue
        if isinstance(data, dict):
            items.append(data)
    return items


def _bugs(contract: Path) -> list[dict[str, Any]]:
    items = []
    for path in sorted((contract / "bugs").glob("BUG-*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError):
            continue
        if isinstance(data, dict):
            items.append(data)
    return items


def open_blocking_bugs(contract: Path) -> list[dict[str, Any]]:
    return [
        bug
        for bug in _bugs(contract)
        if bug.get("status") in {"open", "triaged", "in_progress", "reopened", "verifying"}
        and bug.get("severity") in {"blocker", "critical"}
    ]


def release_freeze(
    project: str | Path,
    *,
    version: str | None = None,
    note: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    contract = resolve_contract(project)
    state = read_current(contract)
    roadmap_id = str(state.get("roadmap") or "R1")
    roadmap_data = _load_yaml(contract / "roadmap" / "ROADMAP.yaml")
    roadmap = next(
        (item for item in roadmap_data.get("roadmaps") or [] if item.get("id") == roadmap_id),
        {},
    )
    version = version or str(roadmap.get("version_target") or "0.0.0")
    try:
        roadmap_major = int(roadmap_id.lstrip("R"))
        version_major = int(version.split(".", 1)[0])
    except ValueError:
        roadmap_major = version_major = 0
    if not force and roadmap_major != version_major:
        raise VerifyError(f"路标 {roadmap_id} 与版本 {version} 的 MAJOR 不一致；用 --force 才能冻结")
    phase = str(state.get("phase") or "P1")
    phase_status = str(state.get("phase_status") or "")
    gate = state.get("last_phase_gate") or {}
    if phase != "P5" or phase_status not in {"exited", "done"}:
        raise VerifyError(f"当前阶段 {phase}/{phase_status} 未完成 P5 退出，不能冻结发布")
    if gate.get("phase") != "P5" or gate.get("roadmap") != roadmap_id:
        raise VerifyError("缺少 P5 阶段退出记录，不能冻结发布")
    if not gate.get("approved_by"):
        raise VerifyError("P5 退出缺少用户批准记录，不能冻结发布")

    requirements = _requirements(contract)
    scoped_reqs = [req for req in requirements if req.get("roadmap") == roadmap_id]
    bad_reqs = [req for req in scoped_reqs if req.get("status") not in RELEASE_STATUSES]
    bugs = _bugs(contract)
    blockers = [
        bug
        for bug in bugs
        if bug.get("status") in {"open", "triaged", "in_progress", "reopened", "verifying"}
        and bug.get("severity") in {"blocker", "critical"}
        and bug.get("roadmap") in {None, roadmap_id}
    ]
    tasks = _tasks(contract, roadmap_id)
    unfinished = [task for task in tasks if task.get("status") not in {"accepted", "cancelled"}]
    errors = []
    if bad_reqs:
        errors.append(f"{len(bad_reqs)} 个需求未达到 verified/released/deferred/rejected")
    if blockers:
        errors.append(f"{len(blockers)} 个 blocker/critical BUG 未关闭")
    if unfinished:
        errors.append(f"{len(unfinished)} 个任务未验收")
    if errors and not force:
        raise VerifyError("；".join(errors) + "；确认后用 --force")

    vr = [
        item
        for item in list_verifications(project)
        if item.get("roadmap") in {None, roadmap_id}
    ]
    scoped_bugs = [
        bug_item
        for bug_item in bugs
        if bug_item.get("roadmap") in {None, roadmap_id}
    ]
    manifest = {
        "schema": 1,
        "project_version": version,
        "roadmap": roadmap_id,
        "roadmap_version_target": roadmap.get("version_target"),
        "frozen_at": _now(),
        "status": "frozen",
        "published": False,
        "note": note or "冻结不等于发布；发布需另行授权",
        "requirements": [
            {
                "id": req.get("id"),
                "title": req.get("title"),
                "status": req.get("status"),
                "priority": req.get("priority"),
            }
            for req in scoped_reqs
        ],
        "tasks": {
            "total": len(tasks),
            "accepted": len([task for task in tasks if task.get("status") == "accepted"]),
            "unfinished": [task.get("id") for task in unfinished],
        },
        "verification": {
            "total": len(vr),
            "results": {
                result: len([item for item in vr if item.get("result") == result]) for result in RESULTS
            },
            "records": [item.get("id") for item in vr],
        },
        "known_issues": [
            {
                "id": bug.get("id"),
                "severity": bug.get("severity"),
                "status": bug.get("status"),
                "title": bug.get("title"),
            }
            for bug in scoped_bugs
            if bug.get("status") not in {"closed", "wontfix", "deferred"}
        ],
    }
    path = contract / "release" / f"RELEASE-{version}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8")
    state["release"] = {"version": version, "manifest": str(path.relative_to(contract)), "frozen_at": manifest["frozen_at"]}
    state["release_status"] = "frozen"
    write_current(contract, state)
    refresh_current(contract)
    ledger_append(contract, {"event": "release.freeze", "version": version, "roadmap": roadmap_id})
    return {
        "version": version,
        "roadmap": roadmap_id,
        "manifest": str(path),
        "manifest_relative": str(path.relative_to(contract)),
        "published": False,
        "known_issues": len(manifest["known_issues"]),
    }


def show_release(project: str | Path, version: str | None = None) -> dict[str, Any]:
    contract = resolve_contract(project)
    state = read_current(contract)
    if version is None:
        release = state.get("release") or {}
        version = release.get("version")
    if not version:
        raise VerifyError("没有已冻结的发布版本；先运行 mf release freeze")
    release = state.get("release") or {}
    manifest_relative = release.get("manifest")
    path = contract / str(manifest_relative) if manifest_relative else contract / "release" / f"RELEASE-{version}.yaml"
    if not path.is_file():
        path = contract / "release" / f"RELEASE-{version}.yaml"
    if not path.is_file():
        raise VerifyError(f"发布清单不存在: {path}")
    data = _load_yaml(path)
    return data
