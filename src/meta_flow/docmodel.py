"""文档模型：继承文档 / 过程文档 / 登记册与版本隔离（REQ-0020 / DOCUMENT-MODEL）。

- 继承文档：architecture/、standards/、knowledge/、project/、workspace/、policies/、templates/
- 过程文档：roadmap/R{n}/phases/**（PLAN/DP/SPEC/WP/TASK/证据）、reviews/、verification/、bugs/、release/
- 登记册：requirements/、improvements/、roadmap/ROADMAP.yaml、state/ledger.ndjson

SPEC 是 P2 过程文档，目标 `roadmap/R{n}/phases/P2/specs/`；legacy `specs/`
保留兼容读取（trace/doctor 不破坏）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

INHERIT_PREFIXES = (
    "architecture/",
    "standards/",
    "knowledge/",
    "project/",
    "workspace/",
    "policies/",
    "templates/",
    "agents/",
)
PROCESS_PREFIXES = (
    "roadmap/",
    "reviews/",
    "verification/",
    "bugs/",
    "release/",
    "improvements/records/",
    "archive/",
)
REGISTER_PREFIXES = (
    "requirements/",
    "improvements/",
)
PROCESS_FILENAMES = {
    "DP-",
    "WP-",
    "TASK.yaml",
    "WORK-PACKAGE.yaml",
    "VR-",
    "BUG-",
    "RELEASE-",
}
SPEC_PREFIX = "SPEC-"


class DocModelError(Exception):
    """文档模型检查失败。"""


def classify(relative: str) -> str:
    rel = relative.replace("\\", "/").lstrip("./").lstrip("/")
    if rel.startswith(INHERIT_PREFIXES):
        return "inherit"
    if rel.startswith(PROCESS_PREFIXES):
        return "process"
    if rel.startswith(REGISTER_PREFIXES):
        return "register"
    if rel in {"roadmap/ROADMAP.yaml", "state/ledger.ndjson"}:
        return "register"
    return "unknown"


def current_roadmap(contract: Path) -> str:
    path = contract / "state" / "current.json"
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
        if isinstance(data, dict) and data.get("roadmap"):
            return str(data["roadmap"])
    return "R1"


def spec_files(contract: Path, roadmap: str | None = None) -> list[Path]:
    """SPEC 兼容读取：legacy specs/ + P2 过程目录（当前/指定 R）。"""
    files: list[Path] = []
    legacy = contract / "specs"
    if legacy.is_dir():
        files.extend(sorted(legacy.glob(f"{SPEC_PREFIX}*.md")))
    base = contract / "roadmap"
    if base.is_dir():
        if roadmap:
            patterns = [f"{roadmap}/phases/P2/specs/{SPEC_PREFIX}*.md"]
        else:
            patterns = [f"*/phases/P2/specs/{SPEC_PREFIX}*.md"]
        for pattern in patterns:
            files.extend(sorted(base.glob(pattern)))
    return files


def spec_refs(contract: Path, req_id: str, roadmap: str | None = None) -> list[str]:
    """返回包含 REQ 引用的 SPEC 相对路径（legacy 与 P2 合并）。"""
    hits: list[str] = []
    for path in spec_files(contract, roadmap):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if req_id in text:
            hits.append(path.relative_to(contract).as_posix())
    return hits


def check(contract: Path, *, roadmap: str | None = None) -> list[str]:
    """返回非阻断文档模型问题（doctor warning / mf docs check）。"""
    issues: list[str] = []
    current = roadmap or current_roadmap(contract)

    architecture = contract / "architecture"
    if architecture.is_dir():
        for path in sorted(architecture.rglob("*")):
            if not path.is_file() or path.suffix != ".md":
                continue
            name = path.name
            if name.startswith(SPEC_PREFIX):
                issues.append(
                    f"SPEC 不应位于继承文档目录: {path.relative_to(contract)}"
                    "（目标 roadmap/R{n}/phases/P2/specs/）"
                )
            elif any(
                name.startswith(prefix) or name == prefix for prefix in PROCESS_FILENAMES
            ):
                issues.append(
                    f"过程文档不应位于继承文档目录: {path.relative_to(contract)}"
                )

    for path in sorted((contract / "roadmap").glob("*/phases/P2/specs/*.md")):
        if not path.name.startswith(SPEC_PREFIX):
            issues.append(
                f"P2 specs 目录含非 SPEC 文件: {path.relative_to(contract)}"
            )

    # 版本隔离：worker 只能读当前 R；当前 R 之外不应有 in_progress/ready 任务。
    for path in sorted((contract / "roadmap").glob("*/phases/*/tasks/T*/TASK.yaml")):
        try:
            import yaml

            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        version = str(data.get("roadmap") or "")
        status = str(data.get("status") or "")
        if version and version != current and status in {"in_progress", "ready", "rework"}:
            issues.append(
                f"版本隔离: {data.get('id')} 属于 {version}（当前 {current}）但状态为 {status}"
            )

    # flow_profile/phase_plan（SPEC-R1-VERSION V3/V8）：非法 profile/mode 报 issue；
    # merged/skipped 阶段不要求报告/任务。
    version_path = contract / "roadmap" / current / "VERSION.yaml"
    if version_path.is_file():
        try:
            import yaml

            meta = yaml.safe_load(version_path.read_text(encoding="utf-8")) or {}
        except Exception:
            meta = {}
        if isinstance(meta, dict):
            profile = meta.get("flow_profile")
            if profile is not None and profile not in {
                "large",
                "small",
                "bugfix",
                "patch",
                "program",
            }:
                issues.append(f"VERSION.yaml flow_profile 非法: {profile}")
            plan = meta.get("phase_plan")
            if plan is not None and not isinstance(plan, dict):
                issues.append("VERSION.yaml phase_plan 必须是 P1–P5 映射")
            elif isinstance(plan, dict):
                for phase, entry in plan.items():
                    if phase not in {"P1", "P2", "P3", "P4", "P5"}:
                        issues.append(f"phase_plan 含未知阶段: {phase}")
                        continue
                    mode = (entry or {}).get("mode") if isinstance(entry, dict) else None
                    if mode not in {"required", "merged_into", "skipped"}:
                        issues.append(f"phase_plan.{phase}.mode 非法: {mode}")
    return issues


def summary(contract: Path) -> dict[str, Any]:
    inherit = sum(
        1
        for prefix in INHERIT_PREFIXES
        for path in (contract / prefix).rglob("*")
        if path.is_file()
    )
    process = sum(
        1
        for prefix in PROCESS_PREFIXES
        for path in (contract / prefix).rglob("*")
        if path.is_file()
    )
    registers = sum(
        1
        for prefix in REGISTER_PREFIXES
        for path in (contract / prefix).rglob("*")
        if path.is_file()
    )
    specs = spec_files(contract)
    return {
        "current_roadmap": current_roadmap(contract),
        "inherit_files": inherit,
        "process_files": process,
        "register_files": registers,
        "specs": [path.relative_to(contract).as_posix() for path in specs],
    }


ENTRY_FILES = ("CLAUDE.md", "AGENTS.md", "workspace/CLAUDE.md")
ENTRY_MAX_LINES = 100
FRONT_MATTER_REQUIRED = ("id", "type", "status", "owner", "updated_at")
# 过程记录篇幅预算（行；DP-PROC-01 §6）
PROCESS_BUDGETS = {
    "handoff.md": 60,
    "dev-record.md": 200,
    "review.md": 120,
    "review-handoff.md": 20,
}


def _front_matter(path: Path) -> dict[str, Any] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    parts = text.split("\n---", 1)
    if len(parts) != 2:
        return None
    try:
        import yaml

        data = yaml.safe_load(parts[0].removeprefix("---")) or {}
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def docs_check(contract: Path, *, roadmap: str | None = None) -> list[str]:
    """双标准文档检查：front matter/入口行数/重复 ID/过程位置（REQ-0027）。"""
    issues = check(contract, roadmap=roadmap)
    for relative in ENTRY_FILES:
        path = contract / relative
        if not path.is_file():
            continue
        try:
            lines = len(path.read_text(encoding="utf-8").splitlines())
        except OSError:
            continue
        if lines > ENTRY_MAX_LINES:
            issues.append(
                f"入口文件 {relative} 超过 {ENTRY_MAX_LINES} 行（当前 {lines}）："
                "只做导航/规则，细节放分层文档"
            )
    targets: list[Path] = []
    targets.extend(sorted((contract / "roadmap").glob("*/phases/P2/specs/SPEC-*.md")))
    targets.extend(sorted((contract / "specs").glob("SPEC-*.md")))
    architecture = contract / "architecture"
    if architecture.is_dir():
        targets.extend(sorted(architecture.rglob("*.md")))
    seen: dict[str, str] = {}
    for path in targets:
        relative = path.relative_to(contract).as_posix()
        # 过程模板/索引/研究记录不强制 front matter（非长期真相或生成物）
        if path.name in {"INDEX.md"} or "adr/drafts" in relative:
            continue
        front = _front_matter(path)
        if front is None:
            issues.append(f"缺少 YAML front matter（legacy warning）: {relative}")
            continue
        missing = [
            key for key in FRONT_MATTER_REQUIRED if not str(front.get(key) or "").strip()
        ]
        if missing:
            issues.append(f"front matter 缺字段 {', '.join(missing)}: {relative}")
        doc_id = str(front.get("id") or "")
        if doc_id:
            if doc_id in seen:
                issues.append(f"重复文档 ID {doc_id}: {seen[doc_id]} 与 {relative}")
            else:
                seen[doc_id] = relative
    return issues


def process_check(contract: Path, *, roadmap: str | None = None) -> list[str]:
    """过程记录检查：篇幅/字段/孤儿/rounds/open findings（DP-PROC-01 §6）。

    两遍扫描：先收集全部任务，再检查引用，避免 T006→T007 这类 forward
    review 被误判孤儿；draft/ready 评审（目标未提交）属正常前置状态，不报错。
    """
    issues: list[str] = []
    current = roadmap or current_roadmap(contract)
    tasks: dict[str, dict[str, Any]] = {}
    bundles: dict[str, Path] = {}
    for path in sorted((contract / "roadmap").glob("*/phases/*/tasks/T*/TASK.yaml")):
        try:
            import yaml

            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if not isinstance(data, dict) or not data.get("id"):
            continue
        if roadmap and str(data.get("roadmap") or "") not in {"", current}:
            continue
        task_id = str(data["id"])
        tasks[task_id] = data
        bundles[task_id] = path.parent
    for task_id, data in tasks.items():
        if str(data.get("status") or "") in {"accepted", "cancelled"}:
            continue
        bundle = bundles[task_id]
        for name, limit in PROCESS_BUDGETS.items():
            item = bundle / name
            if not item.is_file():
                continue
            try:
                lines = len(
                    [
                        line
                        for line in item.read_text(encoding="utf-8").splitlines()
                        if line.strip()
                    ]
                )
            except OSError:
                continue
            if lines > limit:
                issues.append(
                    f"{task_id}/{name} 超过篇幅预算 {limit} 行（当前 {lines}）；"
                    "引用证据/VR，不复制长日志（DP-PROC-01）"
                )
        if data.get("kind") == "review":
            target = str(data.get("reviews") or "")
            status = str(data.get("status") or "")
            if not target or target not in tasks:
                issues.append(f"{task_id} 评审任务缺少有效的 reviews 目标")
            elif status == "in_progress" and str(
                tasks[target].get("status") or ""
            ) not in {"submitted", "accepted"}:
                issues.append(
                    f"{task_id} 评审已开始，但目标 {target} 状态为 "
                    f"{tasks[target].get('status')}（应为 submitted/accepted）"
                )
            rounds = data.get("rounds")
            if rounds is not None and not isinstance(rounds, list):
                issues.append(f"{task_id} review.rounds 必须是列表")
            elif isinstance(rounds, list) and not rounds and status in {
                "submitted",
                "accepted",
            }:
                issues.append(f"{task_id} review.rounds 为空（提交/接受时应记录轮次）")
            if (
                status == "accepted"
                and data.get("review_verdict") == "NEEDS_REWORK"
                and int(data.get("rework_count") or 0) >= 2
                and not isinstance(rounds, list)
            ):
                issues.append(
                    f"{task_id} 多轮 NEEDS_REWORK 缺 rounds[]（DP-PROC-01 同一记录累积）"
                )
            review_md = bundle / "review.md"
            if (
                status == "accepted"
                and review_md.is_file()
                and any(
                    marker in review_md.read_text(encoding="utf-8")
                    for marker in ("| open |", "status: open", "未关闭")
                )
            ):
                issues.append(f"{task_id} 已接受但仍有 open findings（关闭或标注回归）")
        else:
            review_id = str(data.get("reviewed_by_task") or "")
            if review_id and review_id not in tasks:
                issues.append(f"{task_id} 关联 review {review_id} 不存在（孤儿引用）")
    return issues
