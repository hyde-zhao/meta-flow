"""路标、版本、五阶段与阶段交接。"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from . import templates
from .state import ledger_append, read_current, refresh_current, write_current
from .workspace import resolve_contract

PHASES = ("P1", "P2", "P3", "P4", "P5")
PHASE_NAMES = {
    "P1": "计划",
    "P2": "设计",
    "P3": "实施",
    "P4": "验证/验收",
    "P5": "发布",
}
GATED_PHASES = {"P1", "P2", "P4", "P5"}
FLOW_PROFILES = ("large", "small", "bugfix", "patch", "program")
PHASE_MODES = ("required", "merged_into", "skipped")

# SPEC-R1-VERSION V3：profile → phase_plan 默认（可被 VERSION.yaml 覆盖）。
DEFAULT_PHASE_PLANS: dict[str, dict[str, dict[str, Any]]] = {
    "large": {
        "P1": {"mode": "required"},
        "P2": {"mode": "required"},
        "P3": {"mode": "required"},
        "P4": {"mode": "required"},
        "P5": {"mode": "required"},
    },
    "small": {
        "P1": {"mode": "required"},
        "P2": {"mode": "merged_into", "target": "P1"},
        "P3": {"mode": "required"},
        "P4": {"mode": "merged_into", "target": "P3"},
        "P5": {"mode": "required"},
    },
    "bugfix": {
        "P1": {"mode": "skipped"},
        "P2": {"mode": "skipped"},
        "P3": {"mode": "required"},
        "P4": {"mode": "required"},
        "P5": {"mode": "required"},
    },
    "patch": {
        "P1": {"mode": "skipped"},
        "P2": {"mode": "skipped"},
        "P3": {"mode": "skipped"},
        "P4": {"mode": "required"},
        "P5": {"mode": "required"},
    },
    "program": {
        "P1": {"mode": "required"},
        "P2": {"mode": "merged_into", "target": "P1"},
        "P3": {"mode": "merged_into", "target": "P1"},
        "P4": {"mode": "merged_into", "target": "P1"},
        "P5": {"mode": "required"},
    },
}
# SPEC-R1-VERSION V2：effort band（仅建议，不做机器分类）。
EFFORT_BANDS = {"S": 0.5, "M": 1.5, "L": 3.0, "XL": 6.0}
SIZING_SMALL = {"vu_count": 10, "effort_hours": 40, "cross_module": False}
SIZING_LARGE = {"vu_count": 30, "effort_hours": 120}


class RoadmapError(Exception):
    """路标/阶段操作失败。"""

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
        raise RoadmapError(f"{path} 不是合法 YAML: {exc}") from exc
    return data if isinstance(data, dict) else {}


def _save_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _roadmap_file(contract: Path) -> Path:
    return contract / "roadmap" / "ROADMAP.yaml"


def _load_roadmap(contract: Path) -> dict[str, Any]:
    data = _load_yaml(_roadmap_file(contract))
    data.setdefault("schema", 1)
    data.setdefault("roadmaps", [])
    return data


def _save_roadmap(contract: Path, data: dict[str, Any]) -> None:
    _save_yaml(_roadmap_file(contract), data)


def _find_roadmap(contract: Path, roadmap_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    data = _load_roadmap(contract)
    for item in data["roadmaps"]:
        if item.get("id") == roadmap_id:
            return data, item
    raise RoadmapError(f"路标不存在: {roadmap_id}")


def _next_roadmap(contract: Path, roadmap_id: str) -> str | None:
    data = _load_roadmap(contract)
    ids = [str(item.get("id")) for item in data["roadmaps"]]
    try:
        index = ids.index(roadmap_id)
    except ValueError:
        return None
    for candidate in ids[index + 1 :]:
        item = next(x for x in data["roadmaps"] if x.get("id") == candidate)
        if item.get("status") in {"planned", "active"}:
            return candidate
    return None


def show(project: str | Path) -> dict[str, Any]:
    contract = resolve_contract(project)
    data = _load_roadmap(contract)
    state = read_current(contract)
    return {"current": {"roadmap": state.get("roadmap"), "phase": state.get("phase")}, **data}


def plan(
    project: str | Path,
    roadmap_id: str,
    *,
    title: str,
    version_target: str,
    goal: str,
    entry_criteria: list[str] | None = None,
    exit_criteria: list[str] | None = None,
    non_goals: list[str] | None = None,
    activate: bool = False,
) -> dict[str, Any]:
    contract = resolve_contract(project)
    if not roadmap_id.startswith("R") or not roadmap_id[1:].isdigit():
        raise RoadmapError("路标 ID 必须形如 R1/R2")
    data = _load_roadmap(contract)
    item = next((x for x in data["roadmaps"] if x.get("id") == roadmap_id), None)
    created = item is None
    if item is None:
        item = {"id": roadmap_id, "status": "planned"}
        data["roadmaps"].append(item)
    major = version_target.split(".", 1)[0]
    existing_status = str(item.get("status") or "")
    if existing_status not in {"active", "closed"}:
        existing_status = "planned"
    item.update(
        {
            "title": title,
            "status": existing_status,
            "version_range": f"{major}.x",
            "version_target": version_target,
            "goal": goal,
            "entry_criteria": entry_criteria or item.get("entry_criteria") or [],
            "exit_criteria": exit_criteria or item.get("exit_criteria") or [],
            "non_goals": non_goals or item.get("non_goals") or [],
        }
    )
    _save_roadmap(contract, data)

    roadmap_dir = contract / "roadmap" / roadmap_id
    plan_path = roadmap_dir / "PLAN.md"
    if not plan_path.is_file():
        text = templates.ARTIFACT_TEMPLATES["ROADMAP-PLAN.md"].replace("R{n}", roadmap_id)
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(text, encoding="utf-8")
    for phase in PHASES:
        (roadmap_dir / "phases" / phase).mkdir(parents=True, exist_ok=True)

    if activate:
        state = read_current(contract)
        state.update({"roadmap": roadmap_id, "phase": "P1", "phase_status": "active"})
        write_current(contract, state)
        item["status"] = "active"
        _save_roadmap(contract, data)
        refresh_current(contract)
    ledger_append(contract, {"event": "roadmap.plan", "roadmap": roadmap_id, "version": version_target})
    return {
        "roadmap": roadmap_id,
        "title": title,
        "version_target": version_target,
        "created": created,
        "plan": str(plan_path),
        "activated": activate,
    }


def _version_tasks(contract: Path, roadmap_id: str) -> list[dict[str, Any]]:
    items = []
    for path in sorted((contract / "roadmap" / roadmap_id).glob("phases/*/tasks/T*/TASK.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError):
            continue
        if isinstance(data, dict):
            items.append(data)
    return items


def _open_blocking_bugs(contract: Path) -> list[dict[str, Any]]:
    items = []
    for path in sorted((contract / "bugs").glob("BUG-*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        if str(data.get("status")) in {"open", "triaged", "in_progress", "reopened", "verifying"} and str(
            data.get("severity")
        ) in {"blocker", "critical"}:
            items.append(data)
    return items


def _version_meta_path(contract: Path, roadmap_id: str) -> Path:
    return contract / "roadmap" / roadmap_id / "VERSION.yaml"


def _sizing_path(contract: Path, roadmap_id: str) -> Path:
    return contract / "roadmap" / roadmap_id / "SIZING.yaml"


def version_meta(contract: Path, roadmap_id: str) -> dict[str, Any]:
    return _load_yaml(_version_meta_path(contract, roadmap_id))


def phase_plan(contract: Path, roadmap_id: str) -> dict[str, Any]:
    """返回 profile 与阶段计划：VERSION.yaml 显式值与默认计划合并。

    缺省/旧版本按 large 处理（MIGRATION-R1 §3）；空阶段不建任务/报告。
    """
    meta = version_meta(contract, roadmap_id)
    profile = str(meta.get("flow_profile") or "large")
    if profile not in FLOW_PROFILES:
        profile = "large"
    plan = DEFAULT_PHASE_PLANS[profile]
    explicit = meta.get("phase_plan")
    if isinstance(explicit, dict):
        plan = {**plan, **{str(k): v for k, v in explicit.items() if isinstance(v, dict)}}
    normalized: dict[str, dict[str, Any]] = {}
    for phase in PHASES:
        entry = plan.get(phase) if isinstance(plan.get(phase), dict) else {"mode": "required"}
        mode = str(entry.get("mode") or "required")
        if mode not in PHASE_MODES:
            mode = "required"
        item = {"mode": mode}
        if mode == "merged_into":
            item["target"] = str(entry.get("target") or "P1")
        if entry.get("note"):
            item["note"] = entry["note"]
        normalized[phase] = item
    return {
        "roadmap": roadmap_id,
        "flow_profile": profile,
        "phase_plan": normalized,
        "decision": meta.get("decision") or {},
        "source": "VERSION.yaml" if meta else "default(large)",
    }


def _next_required_phase(meta: dict[str, Any], current: str) -> str | None:
    """按 phase_plan 找下一个 required 阶段（program/small 跳过 merged/skipped）。"""
    plan = meta.get("phase_plan") or {}
    start = PHASES.index(current) + 1 if current in PHASES else 0
    for phase in PHASES[start:]:
        if str((plan.get(phase) or {}).get("mode") or "required") == "required":
            return phase
    return None


def sizing(project: str | Path, roadmap_id: str) -> dict[str, Any]:
    """汇总 VU/effort/风险并给出 large/small/split 建议；不自动分类。"""
    contract = resolve_contract(project)
    tasks = [
        task
        for task in _version_tasks(contract, roadmap_id)
        if str(task.get("status") or "") != "cancelled"
    ]
    vu_count = 0
    effort_hours = 0.0
    confidence_levels: list[str] = []
    cross_module = False
    high_risk = False
    for task in tasks:
        estimate = task.get("estimate") if isinstance(task.get("estimate"), dict) else {}
        try:
            vu_count += int(estimate.get("vu") or 1)
        except (TypeError, ValueError):
            vu_count += 1
        try:
            effort_hours += float(
                estimate.get("effort_hours")
                or EFFORT_BANDS.get(str(task.get("effort") or "M"), 1.5)
            )
        except (TypeError, ValueError):
            effort_hours += EFFORT_BANDS.get(str(task.get("effort") or "M"), 1.5)
        confidence = str(estimate.get("confidence") or "low")
        if confidence in {"low", "medium", "high"}:
            confidence_levels.append(confidence)
        if str((task.get("risk") or {}).get("level") or "") in {"high", "critical"}:
            high_risk = True
        if task.get("module") and "/" in str(task.get("module")):
            cross_module = True
    confidence = (
        min(confidence_levels, key=["low", "medium", "high"].index)
        if confidence_levels
        else "low"
    )
    if (
        vu_count > SIZING_LARGE["vu_count"]
        or effort_hours > SIZING_LARGE["effort_hours"]
        or cross_module
        or high_risk
    ):
        suggestion = "large"
    elif (
        vu_count <= SIZING_SMALL["vu_count"]
        and effort_hours <= SIZING_SMALL["effort_hours"]
        and not cross_module
    ):
        suggestion = "small"
    else:
        suggestion = "split"
    meta = phase_plan(contract, roadmap_id)
    data = {
        "roadmap": roadmap_id,
        "task_count": len(tasks),
        "estimate": {
            "vu_count": vu_count,
            "effort_hours": round(effort_hours, 1),
            "confidence": confidence,
            "cross_module": cross_module,
            "high_risk": high_risk,
        },
        "suggestion": suggestion,
        "flow_profile": meta["flow_profile"],
        "phase_plan": meta["phase_plan"],
        "decision": meta.get("decision") or {},
        "note": "阈值仅建议；版本流程必须由用户在版本门显式决定（mf roadmap classify）",
    }
    return data


def classify(
    project: str | Path,
    roadmap_id: str,
    *,
    flow: str,
    decided_by: str,
    reason: str,
    tty: bool | None = None,
    stream: Any | None = None,
    out: Any | None = None,
) -> dict[str, Any]:
    """用户显式决定版本流程 profile（TTY/结构化确认）；不自动分类。"""
    contract = resolve_contract(project)
    if flow not in FLOW_PROFILES:
        raise RoadmapError(f"flow 只能是 {'|'.join(FLOW_PROFILES)}")
    if decided_by != "user":
        raise RoadmapError("版本流程必须由用户显式决定：--decided-by user（不得 manager/AI 自决）")
    if not str(reason or "").strip():
        raise RoadmapError("classify 必须提供 --reason")
    from . import roles

    if tty is None:
        tty = roles.is_tty(stream, out)
    if not tty:
        raise RoadmapError(
            "版本流程决策只能在用户终端执行（非 TTY 拒绝）；"
            "请在用户终端运行 mf roadmap classify ... --decided-by user",
            3,
        )
    data, item = _find_roadmap(contract, roadmap_id)
    meta = version_meta(contract, roadmap_id)
    plan = DEFAULT_PHASE_PLANS[flow]
    now = _now()
    decision = {
        "flow": flow,
        "flow_profile": flow,
        "decided_by": "user",
        "decided_at": now,
        "rationale": str(reason).strip(),
    }
    meta.update(
        {
            "schema": meta.get("schema") or 1,
            "version": meta.get("version") or roadmap_id,
            "flow_profile": flow,
            "phase_plan": plan,
            "decision": decision,
        }
    )
    meta.setdefault("version_target", item.get("version_target"))
    _save_yaml(_version_meta_path(contract, roadmap_id), meta)
    sizing_data = _load_yaml(_sizing_path(contract, roadmap_id))
    sizing_data.update(
        {
            "schema": sizing_data.get("schema") or 1,
            "version": sizing_data.get("version") or roadmap_id,
            "flow_profile": flow,
            "phase_plan_ref": str(_version_meta_path(contract, roadmap_id).relative_to(contract)),
            "decision": {
                "decided_by": "user",
                "decided_at": now,
                "note": str(reason).strip(),
            },
        }
    )
    _save_yaml(_sizing_path(contract, roadmap_id), sizing_data)
    ledger_append(
        contract,
        {
            "event": "roadmap.classify",
            "roadmap": roadmap_id,
            "flow": flow,
            "flow_profile": flow,
            "decided_by": "user",
            "reason": str(reason).strip(),
        },
    )
    return {
        "roadmap": roadmap_id,
        "flow_profile": flow,
        "phase_plan": plan,
        "decision": decision,
        "version": str(_version_meta_path(contract, roadmap_id)),
        "sizing": str(_sizing_path(contract, roadmap_id)),
    }


def phase_view(project: str | Path) -> dict[str, Any]:
    """显示 P1–P5 的 required/merged_into/skipped 与当前状态（mf phase show）。"""
    contract = resolve_contract(project)
    state = read_current(contract)
    roadmap_id = str(state.get("roadmap") or "R1")
    current = str(state.get("phase") or "P1")
    meta = phase_plan(contract, roadmap_id)
    rows = []
    current_index = PHASES.index(current) if current in PHASES else -1
    for index, phase in enumerate(PHASES):
        entry = meta["phase_plan"][phase]
        if phase == current:
            status = str(state.get("phase_status") or "active")
        elif entry["mode"] == "merged_into":
            status = f"merged_into {entry.get('target')}"
        elif entry["mode"] == "skipped":
            status = "skipped"
        elif current_index >= 0 and index < current_index:
            status = "passed"
        else:
            status = "pending"
        rows.append(
            {
                "phase": phase,
                "name": PHASE_NAMES[phase],
                "mode": entry["mode"],
                "target": entry.get("target"),
                "status": status,
                "required": entry["mode"] == "required",
            }
        )
    return {
        "roadmap": roadmap_id,
        "current": current,
        "current_status": state.get("phase_status"),
        "flow_profile": meta["flow_profile"],
        "source": meta["source"],
        "phases": rows,
    }


def _bad_requirements(contract: Path, roadmap_id: str) -> list[dict[str, Any]]:
    path = contract / "requirements" / "REQUIREMENTS.yaml"
    data = _load_yaml(path)
    bad = []
    for item in data.get("requirements") or []:
        if item.get("roadmap") != roadmap_id:
            continue
        if item.get("status") not in {"verified", "released", "deferred", "rejected"}:
            bad.append(item)
    return bad


def close(
    project: str | Path,
    roadmap_id: str,
    *,
    note: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    contract = resolve_contract(project)
    data, item = _find_roadmap(contract, roadmap_id)
    tasks = _version_tasks(contract, roadmap_id)
    unfinished = [t for t in tasks if t.get("status") not in {"accepted", "cancelled"}]
    bad_reqs = _bad_requirements(contract, roadmap_id)
    bugs = [
        bug for bug in _open_blocking_bugs(contract) if bug.get("roadmap") in {None, roadmap_id}
    ]
    blockers = []
    state = read_current(contract)
    if state.get("roadmap") == roadmap_id:
        phase = str(state.get("phase") or "")
        phase_status = str(state.get("phase_status") or "")
        gate = state.get("last_phase_gate") or {}
        if phase != "P5" or phase_status not in {"exited", "done"}:
            blockers.append(f"当前阶段 {phase}/{phase_status} 未完成 P5 退出")
        if gate.get("phase") != "P5" or gate.get("roadmap") != roadmap_id:
            blockers.append("缺少 P5 阶段退出记录")
        elif not gate.get("approved_by"):
            blockers.append("P5 退出缺少用户批准记录")
        release = state.get("release") or {}
        if release.get("version") != item.get("version_target") and not force:
            blockers.append("还未冻结发布清单；先运行 mf release freeze")
    if unfinished and not force:
        blockers.append(f"{len(unfinished)} 个任务未验收")
    if bad_reqs and not force:
        blockers.append(f"{len(bad_reqs)} 个需求未 verified/released/deferred/rejected")
    if bugs and not force:
        blockers.append(f"{len(bugs)} 个 blocker/critical BUG 未关闭")
    if blockers:
        raise RoadmapError("；".join(blockers) + "；确认后用 --force")

    roadmap_dir = contract / "roadmap" / roadmap_id
    roadmap_dir.mkdir(parents=True, exist_ok=True)
    next_id = _next_roadmap(contract, roadmap_id)
    target_version = item.get("version_target") or "0.0.0"
    close_text = [
        f"# {roadmap_id} 版本关闭报告",
        "",
        f"> version_target: {target_version}",
        f"> closed_at: {_now()}",
        f"> note: {note or '-'}",
        "",
        "## 结果",
        "",
        f"- 任务: {len(tasks)}，未完成: {len(unfinished)}",
        f"- 需求: {len([r for r in _all_requirements(contract) if r.get('roadmap') == roadmap_id])}",
        f"- blocker/critical 未关闭 BUG: {len(bugs)}",
        "",
        "## 已知问题",
        "",
    ]
    for bug in bugs:
        close_text.append(f"- {bug.get('id')} [{bug.get('severity')}] {bug.get('title')} ({bug.get('status')})")
    if not bugs:
        close_text.append("(none)")
    if next_id:
        close_text.extend(
            [
                "",
                "## 下一版本",
                "",
                f"交接见 `HANDOFF-TO-{next_id}.md`。",
            ]
        )
    (roadmap_dir / "CLOSE.md").write_text("\n".join(close_text) + "\n", encoding="utf-8")
    if next_id:
        handoff = [
            f"# HANDOFF {roadmap_id} → {next_id}",
            "",
            f"- 来源版本: {roadmap_id} / {target_version}",
            f"- 关闭时间: {_now()}",
            f"- 任务总数: {len(tasks)}",
            f"- 未完成任务: {len(unfinished)}",
            "",
            "## 必须带入下一版本",
            "",
        ]
        for task in unfinished:
            handoff.append(f"- {task.get('id')} {task.get('title')} ({task.get('status')})")
        for bug in bugs:
            handoff.append(f"- {bug.get('id')} [{bug.get('severity')}] {bug.get('title')}")
        if not unfinished and not bugs:
            handoff.append("(none)")
        handoff.extend(["", "## 下一版本入口", "", f"`roadmap/{next_id}/PLAN.md`", ""])
        (roadmap_dir / f"HANDOFF-TO-{next_id}.md").write_text("\n".join(handoff), encoding="utf-8")

    lessons = _load_yaml(contract / "knowledge" / "KNOWLEDGE.yaml").get("lessons") or []
    lesson_lines = [
        f"# {roadmap_id} 版本复盘",
        "",
        f"> 关闭时间: {_now()}",
        "",
        "## 复盘",
        "",
    ]
    if lessons:
        for lesson in lessons:
            lesson_lines.append(f"- {lesson.get('id')}: {lesson.get('text')}")
    else:
        lesson_lines.append("(none)")
    lesson_lines.extend(["", "## 未完成项", ""])
    if unfinished:
        for task in unfinished:
            lesson_lines.append(f"- {task.get('id')} {task.get('title')}")
    else:
        lesson_lines.append("(none)")
    (roadmap_dir / f"LESSONS-{roadmap_id}.md").write_text("\n".join(lesson_lines) + "\n", encoding="utf-8")

    archive_dir = contract / "archive" / roadmap_id
    if archive_dir.exists() and not force:
        raise RoadmapError(f"归档已存在: {archive_dir}；确认覆盖用 --force")
    if archive_dir.exists():
        shutil.rmtree(archive_dir)
    archive_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(roadmap_dir), str(archive_dir))
    for path in sorted((contract / "verification").glob("VR-*.yaml")):
        try:
            record = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError):
            continue
        if isinstance(record, dict) and record.get("roadmap") == roadmap_id:
            snapshot = archive_dir / "verification" / path.name
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(snapshot))
    for path in sorted((contract / "bugs").glob("BUG-*.yaml")):
        try:
            record = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError):
            continue
        if isinstance(record, dict) and record.get("roadmap") == roadmap_id:
            snapshot = archive_dir / "bugs" / path.name
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(snapshot))
    for path in sorted((contract / "release").glob("RELEASE-*.yaml")):
        try:
            record = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError):
            continue
        if isinstance(record, dict) and (
            record.get("roadmap") == roadmap_id
            or str(record.get("project_version")) == str(target_version)
        ):
            snapshot = archive_dir / "release" / path.name
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(snapshot))
    if state.get("release", {}).get("version") == target_version:
        state["release"]["manifest"] = f"archive/{roadmap_id}/release/RELEASE-{target_version}.yaml"
    archive_requirements = [
        req for req in _all_requirements(contract) if req.get("roadmap") == roadmap_id
    ]
    if archive_requirements:
        req_dir = archive_dir / "requirements"
        req_dir.mkdir(parents=True, exist_ok=True)
        (req_dir / "REQUIREMENTS.yaml").write_text(
            yaml.safe_dump(
                {"schema": 1, "requirements": archive_requirements},
                sort_keys=False,
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        for req in archive_requirements:
            name = f"{req.get('id')}.md"
            source = contract / "requirements" / name
            if source.is_file():
                shutil.copy2(source, req_dir / name)
        trace = contract / "requirements" / "TRACE.md"
        if trace.is_file():
            shutil.copy2(trace, req_dir / "TRACE.md")
    index_text = [
        f"# 归档索引 {roadmap_id}",
        "",
        f"> 归档时间: {_now()}",
        "",
        "## 文件",
        "",
    ]
    for path in sorted(archive_dir.rglob("*")):
        if path.is_file():
            index_text.append(f"- {path.relative_to(archive_dir)}")
    (archive_dir / "INDEX.md").write_text("\n".join(index_text) + "\n", encoding="utf-8")

    item["status"] = "closed"
    item["closed_at"] = _now()
    if note:
        item["close_note"] = note
    _save_roadmap(contract, data)

    if state.get("roadmap") == roadmap_id:
        if next_id:
            state.update({"roadmap": next_id, "phase": "P1", "phase_status": "active"})
            next_data, next_item = _find_roadmap(contract, next_id)
            next_item["status"] = "active"
            _save_roadmap(contract, next_data)
        else:
            state["phase_status"] = "closed"
    write_current(contract, state)
    refresh_current(contract)
    ledger_append(contract, {"event": "roadmap.close", "roadmap": roadmap_id, "next": next_id})
    return {
        "roadmap": roadmap_id,
        "closed": True,
        "next": next_id,
        "archive": str(archive_dir),
        "unfinished_tasks": len(unfinished),
        "open_blocking_bugs": len(bugs),
    }


def _all_requirements(contract: Path) -> list[dict[str, Any]]:
    return list(_load_yaml(contract / "requirements" / "REQUIREMENTS.yaml").get("requirements") or [])


def _phase_tasks(contract: Path, roadmap_id: str, phase: str) -> list[dict[str, Any]]:
    items = []
    for path in sorted((contract / "roadmap" / roadmap_id / "phases" / phase / "tasks").glob("T*/TASK.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError):
            continue
        if isinstance(data, dict):
            items.append(data)
    return items


def _phase_dir(contract: Path, roadmap_id: str, phase: str) -> Path:
    return contract / "roadmap" / roadmap_id / "phases" / phase


def _phase_plan_path(contract: Path, roadmap_id: str, phase: str) -> Path:
    return _phase_dir(contract, roadmap_id, phase) / "PLAN.md"


def _write_phase_plan(contract: Path, roadmap_id: str, phase: str) -> Path:
    path = _phase_plan_path(contract, roadmap_id, phase)
    if path.is_file():
        return path
    text = templates.ARTIFACT_TEMPLATES["PHASE-PLAN.md"].replace("R{n}", roadmap_id).replace("P{n}", phase)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def phase_enter(project: str | Path, phase: str) -> dict[str, Any]:
    contract = resolve_contract(project)
    if phase not in PHASES:
        raise RoadmapError(f"阶段只能是 {'|'.join(PHASES)}")
    state = read_current(contract)
    roadmap_id = str(state.get("roadmap") or "R1")
    current = str(state.get("phase") or "P1")
    status = str(state.get("phase_status") or "")
    if phase == current:
        if status != "active":
            raise RoadmapError(f"当前阶段 {current} 状态为 {status}，不能重复进入")
        plan_path = _write_phase_plan(contract, roadmap_id, phase)
        return {"roadmap": roadmap_id, "phase": phase, "plan": str(plan_path), "status": "active"}
    if current not in PHASES:
        raise RoadmapError(f"当前阶段非法: {current}")
    meta = phase_plan(contract, roadmap_id)
    expected = _next_required_phase(meta, current)
    entry = meta["phase_plan"].get(phase) or {}
    if entry.get("mode") != "required":
        raise RoadmapError(
            f"{phase} 在 {meta['flow_profile']} profile 下为 {entry.get('mode')}"
            f"（merged_into {entry.get('target') or '-'}/skipped），不单独进入/建任务/报告；"
            "设计产物按文档类型存 P2 目录，见 VERSION.yaml phase_plan"
        )
    if phase != expected:
        raise RoadmapError(
            f"只能进入下一 required 阶段：当前 {current}（{meta['flow_profile']}），"
            f"下一阶段是 {expected or '无（当前为最后 required 阶段）'}，不能进入 {phase}"
        )
    if status != "exited":
        raise RoadmapError(f"必须先执行 mf phase exit 完成 {current} 并记录门禁，才能进入 {phase}")
    gate = state.get("last_phase_gate") or {}
    if gate.get("phase") != current or gate.get("next_phase") != phase:
        raise RoadmapError(f"缺少 {current} → {phase} 的阶段退出记录")
    plan_path = _write_phase_plan(contract, roadmap_id, phase)
    state.update({"roadmap": roadmap_id, "phase": phase, "phase_status": "active"})
    write_current(contract, state)
    refresh_current(contract)
    ledger_append(
        contract,
        {"event": "phase.enter", "roadmap": roadmap_id, "phase": phase, "from": current},
    )
    return {"roadmap": roadmap_id, "phase": phase, "plan": str(plan_path), "status": "active"}


def _phase_report_text(contract: Path, roadmap_id: str, phase: str) -> str:
    tasks = _phase_tasks(contract, roadmap_id, phase)
    status_counts: dict[str, int] = {}
    for task in tasks:
        status = str(task.get("status") or "draft")
        status_counts[status] = status_counts.get(status, 0) + 1
    bugs = []
    for path in sorted((contract / "bugs").glob("BUG-*.yaml")):
        try:
            bug = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError):
            continue
        if isinstance(bug, dict) and (bug.get("found_in") or {}).get("phase") == phase:
            if bug.get("roadmap") in {None, roadmap_id}:
                bugs.append(bug)
    vr = []
    for path in sorted((contract / "verification").glob("VR-*.yaml")):
        try:
            record = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError):
            continue
        if isinstance(record, dict):
            vr.append(record)
    lines = [
        f"# {roadmap_id}-{phase} 阶段报告",
        "",
        f"> 生成时间: {_now()}",
        "",
        "## 阶段目标核对",
        "",
        f"阶段: {phase} {PHASE_NAMES[phase]}",
        "",
        "## 需求覆盖",
        "",
    ]
    for req in _all_requirements(contract):
        if req.get("roadmap") == roadmap_id:
            lines.append(f"- {req.get('id')} [{req.get('status')}] {req.get('title')}")
    if not any(req.get("roadmap") == roadmap_id for req in _all_requirements(contract)):
        lines.append("(none)")
    lines.extend(["", "## L1/L2/L3 验证结果", ""])
    if vr:
        for record in vr:
            refs = record.get("task_refs") or []
            same_record = record.get("roadmap") == roadmap_id and record.get("phase") == phase
            same_tasks = any(str(ref).startswith(f"{roadmap_id}-{phase}-") for ref in refs)
            if same_record or same_tasks:
                lines.append(
                    f"- {record.get('id')} layer={record.get('layer')} result={record.get('result')} "
                    f"scope={record.get('scope')}"
                )
    else:
        lines.append("(none)")
    lines.extend(["", "## 任务", ""])
    for status, count in sorted(status_counts.items()):
        lines.append(f"- {status}: {count}")
    if not status_counts:
        lines.append("(none)")
    lines.extend(["", "## 缺陷与未决问题", ""])
    if bugs:
        for bug in bugs:
            lines.append(f"- {bug.get('id')} [{bug.get('severity')}/{bug.get('status')}] {bug.get('title')}")
    else:
        lines.append("(none)")
    lines.extend(["", "## 用户纠正与知识沉淀", ""])
    kdata = _load_yaml(contract / "knowledge" / "KNOWLEDGE.yaml")
    lessons = kdata.get("lessons") or []
    if lessons:
        for lesson in lessons:
            lines.append(f"- {lesson.get('id')}: {lesson.get('text')}")
    else:
        lines.append("(none)")
    lines.extend(["", "## 用户确认", "", "待确认。" if phase in GATED_PHASES else "本阶段不要求用户门禁。", ""])
    return "\n".join(lines)


def phase_review(project: str | Path) -> dict[str, Any]:
    contract = resolve_contract(project)
    state = read_current(contract)
    roadmap_id = str(state.get("roadmap") or "R1")
    phase = str(state.get("phase") or "P1")
    if phase not in PHASES:
        raise RoadmapError(f"当前阶段非法: {phase}")
    text = _phase_report_text(contract, roadmap_id, phase)
    path = _phase_dir(contract, roadmap_id, phase) / "REPORT.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    ledger_append(contract, {"event": "phase.review", "roadmap": roadmap_id, "phase": phase})
    return {"roadmap": roadmap_id, "phase": phase, "report": str(path), "text": text}


def phase_exit(
    project: str | Path,
    *,
    approved_by: str | None = None,
    note: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    contract = resolve_contract(project)
    state = read_current(contract)
    roadmap_id = str(state.get("roadmap") or "R1")
    phase = str(state.get("phase") or "P1")
    if phase not in PHASES:
        raise RoadmapError(f"当前阶段非法: {phase}")
    if str(state.get("phase_status") or "") != "active":
        raise RoadmapError(f"当前阶段 {phase} 不是 active，不能重复 exit")
    tasks = _phase_tasks(contract, roadmap_id, phase)
    unfinished = [task for task in tasks if task.get("status") not in {"accepted", "cancelled"}]
    if unfinished and not force:
        raise RoadmapError(f"{phase} 仍有 {len(unfinished)} 个任务未验收；先完成或 --force")
    if phase == "P1" and not force:
        reqs = [req for req in _all_requirements(contract) if req.get("roadmap") == roadmap_id]
        if not reqs:
            raise RoadmapError("P1 退出需要至少一条需求基线；先 mf req add")
    if phase == "P2" and not force:
        design_docs = [
            path
            for directory in (contract / "specs", contract / "architecture")
            for path in directory.rglob("*.md")
            if path.name != "INDEX.md" and "drafts" not in path.parts
        ]
        if not design_docs:
            raise RoadmapError("P2 退出需要至少一份 SPEC/DESIGN/ADR；先完成设计文档")
    if phase == "P4" and not force:
        layered = []
        for path in sorted((contract / "verification").glob("VR-*.yaml")):
            record = _load_yaml(path)
            if (
                record.get("layer") in {"design", "requirement"}
                and record.get("roadmap") in {None, roadmap_id}
            ):
                layered.append(record)
        if not layered:
            raise RoadmapError("P4 退出需要至少一条 L2/L3 验证记录；先 mf verify record")
    bugs = [
        bug
        for bug in _open_blocking_bugs(contract)
        if ((bug.get("found_in") or {}).get("phase") == phase)
        and bug.get("roadmap") in {None, roadmap_id}
    ]
    if bugs and not force:
        raise RoadmapError(f"{phase} 仍有 {len(bugs)} 个 blocker/critical BUG；先关闭或 --force")
    if phase in GATED_PHASES and not approved_by:
        raise RoadmapError(f"{phase} 退出需要用户门禁：--approved-by <用户/记录>")

    report = phase_review(project)
    meta = phase_plan(contract, roadmap_id)
    next_phase = _next_required_phase(meta, phase)
    handoff_path = None
    if next_phase:
        handoff = [
            f"# HANDOFF {roadmap_id}-{phase} → {roadmap_id}-{next_phase}",
            "",
            f"> 时间: {_now()}",
            f"> 用户门禁: {approved_by or '-'}",
            f"> 说明: {note or '-'}",
            "",
            "## 已完成",
            "",
        ]
        for task in tasks:
            if task.get("status") == "accepted":
                handoff.append(f"- {task.get('id')} {task.get('title')}")
        handoff.extend(["", "## 必须带入下一阶段", ""])
        for task in unfinished:
            handoff.append(f"- 未完成任务: {task.get('id')} {task.get('title')}")
        for bug in bugs:
            handoff.append(f"- 未关闭 BUG: {bug.get('id')} {bug.get('title')}")
        if not unfinished and not bugs:
            handoff.append("(none)")
        handoff.extend(["", "## 下一阶段", "", f"`roadmap/{roadmap_id}/phases/{next_phase}/PLAN.md`", ""])
        handoff_path = _phase_dir(contract, roadmap_id, phase) / f"HANDOFF-TO-{next_phase}.md"
        handoff_path.write_text("\n".join(handoff), encoding="utf-8")

    if next_phase:
        handoff = [
            f"# HANDOFF {roadmap_id}-{phase} → {roadmap_id}-{next_phase}",
            "",
            f"> 时间: {_now()}",
            f"> 用户门禁: {approved_by or '-'}",
            f"> 说明: {note or '-'}",
            "",
            "## 已完成",
            "",
        ]
        for task in tasks:
            if task.get("status") == "accepted":
                handoff.append(f"- {task.get('id')} {task.get('title')}")
        handoff.extend(["", "## 必须带入下一阶段", ""])
        for task in unfinished:
            handoff.append(f"- 未完成任务: {task.get('id')} {task.get('title')}")
        for bug in bugs:
            handoff.append(f"- 未关闭 BUG: {bug.get('id')} {bug.get('title')}")
        if not unfinished and not bugs:
            handoff.append("(none)")
        handoff.extend(["", "## 下一阶段", "", f"`roadmap/{roadmap_id}/phases/{next_phase}/PLAN.md`", ""])
        handoff_path = _phase_dir(contract, roadmap_id, phase) / f"HANDOFF-TO-{next_phase}.md"
        handoff_path.write_text("\n".join(handoff), encoding="utf-8")

    state["phase_status"] = "exited"
    state["last_phase_gate"] = {
        "roadmap": roadmap_id,
        "phase": phase,
        "next_phase": next_phase,
        "approved_by": approved_by,
        "note": note,
        "at": _now(),
    }
    write_current(contract, state)
    refresh_current(contract)
    ledger_append(
        contract,
        {
            "event": "phase.exit",
            "roadmap": roadmap_id,
            "phase": phase,
            "next": next_phase,
            "approved_by": approved_by,
        },
    )
    return {
        "roadmap": roadmap_id,
        "phase": phase,
        "next": next_phase,
        "report": report["report"],
        "handoff": str(handoff_path) if handoff_path else None,
        "approved_by": approved_by,
    }
