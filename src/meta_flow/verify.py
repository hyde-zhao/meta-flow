"""分层验证记录与版本冻结。"""

from __future__ import annotations

import re
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


def _declared_major(roadmap: dict[str, Any], roadmap_id: str) -> tuple[int, str]:
    """返回路标声明的项目版本 MAJOR 与声明来源。

    优先 ROADMAP.yaml 的 version_major（项目版本策略），其次 version_range
    （如 1.0.x / 1.x）；都没有时回退旧规则 R{n}=MAJOR。显式声明用于
    R0/V1 1.0.x 这类项目映射（D2/MFP-0006）。
    """
    declared = roadmap.get("version_major")
    if declared is not None:
        try:
            return int(declared), "version_major"
        except (TypeError, ValueError):
            pass
    raw_range = str(roadmap.get("version_range") or "").strip()
    match = re.match(r"^(\d+)(?:\.|\b)", raw_range)
    if match:
        return int(match.group(1)), "version_range"
    try:
        return int(str(roadmap_id).lstrip("R")), "roadmap_id"
    except ValueError:
        return 0, "default"


PRE_RELEASE_RE = re.compile(r"^\d+\.\d+\.\d+-[0-9A-Za-z][0-9A-Za-z.+-]*$")


def _is_prerelease(version: str) -> bool:
    """x.y.z-alpha.1 / -rc2 等预发布；+build 元数据不算预发布。"""
    core = str(version).split("+", 1)[0]
    return PRE_RELEASE_RE.fullmatch(core) is not None


def release_stage_policy(phase: str, phase_status: str, version: str) -> str | None:
    """返回阶段门拒绝原因；None 表示允许冻结（standards/VERSION.md §6）。

    - P1/P2：禁止冻结/发布；
    - P3 active：仅允许 alpha/预发布；P3 exited/done：允许正式发布；
    - P4/P5（active/exited/done）：修复/补丁可随时冻结，不要求阶段结束或
      P5 退出（BUG-0016）；
    - done/closed：路标已结束，沿用允许语义。
    阶段门属用户门禁，--force 不可绕过。
    """
    current = str(phase or "P1")
    status = str(phase_status or "")
    if current in {"P1", "P2"}:
        return (
            f"阶段 {current}/{status or 'unknown'} 不允许冻结发布："
            "P1/P2 为规划/设计阶段，发布需等 P3 阶段结束"
        )
    if current == "P3":
        if status in {"exited", "done"}:
            return None
        if _is_prerelease(str(version)):
            return None
        return (
            f"阶段 P3/{status or 'unknown'} 仅允许 alpha/预发布版本冻结："
            f"{version} 不是预发布版本（如 x.y.z-alpha.1）；"
            "正式版本需等 P3 阶段结束（mf phase exit）后再冻结"
        )
    if current in {"P4", "P5", "done", "closed"}:
        return None
    return f"阶段 {current}/{status or 'unknown'} 不允许冻结发布"


def release_freeze(
    project: str | Path,
    *,
    version: str | None = None,
    note: str | None = None,
    force: bool = False,
    reason: str | None = None,
    approved_by: str | None = None,
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
    version_match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.-]+)?", str(version))
    if version_match is None:
        raise VerifyError(f"版本必须形如 x.y.z[-pre]: {version}")
    version_major = int(version_match.group(1))
    expected_major, declared_by = _declared_major(roadmap, roadmap_id)
    override: dict[str, Any] | None = None
    if version_major != expected_major:
        if not force:
            raise VerifyError(
                f"路标 {roadmap_id} 声明版本 MAJOR={expected_major}（{declared_by}），"
                f"与版本 {version} 不一致；用 --force --reason ... --approved-by ... 才能冻结"
            )
        if not reason or not approved_by:
            raise VerifyError(
                "MAJOR 不一致的 --force 冻结必须记录 --reason 与 --approved-by（可审计例外）"
            )
        override = {
            "reason": reason,
            "approved_by": approved_by,
            "version": version,
            "roadmap": roadmap_id,
            "expected_major": expected_major,
            "declared_by": declared_by,
            "at": _now(),
        }
    phase = str(state.get("phase") or "P1")
    phase_status = str(state.get("phase_status") or "")
    stage_error = release_stage_policy(phase, phase_status, version)
    if stage_error:
        # 阶段门属用户门禁：--force 只能绕过技术校验，不能绕过阶段策略
        raise VerifyError(stage_error)

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
        "stage": {"phase": phase, "phase_status": phase_status},
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
    if override is not None:
        manifest["override"] = override
    path = contract / "release" / f"RELEASE-{version}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8")
    state["release"] = {"version": version, "manifest": str(path.relative_to(contract)), "frozen_at": manifest["frozen_at"]}
    state["release_status"] = "frozen"
    write_current(contract, state)
    refresh_current(contract)
    ledger_append(
        contract,
        {
            "event": "release.freeze",
            "version": version,
            "roadmap": roadmap_id,
            "force": bool(override),
            "override_reason": reason if override else None,
            "approved_by": approved_by if override else None,
        },
    )
    return {
        "version": version,
        "roadmap": roadmap_id,
        "stage": {"phase": phase, "phase_status": phase_status},
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
