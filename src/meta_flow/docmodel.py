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
