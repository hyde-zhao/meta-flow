"""Story return packets, evidence indexes, and design deltas."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from meta_flow.checks import cp_result, state_transition
from meta_flow.context_pack import story_contract
from meta_flow.project.onboarding_contract import canonical_digest
from meta_flow.project.process_route import _resolve_runtime_path, _resolve_runtime_ref
from meta_flow.project.scale import load_yaml_object
from meta_flow.state import event_ledger

EVIDENCE_ROOT_REL = Path("process/evidence")
DESIGN_DELTA_ROOT_REL = Path("process/design-deltas")
DEVELOPMENT_PLAN_REL = Path("process/DEVELOPMENT-PLAN.yaml")
LEGACY_STORY_BACKLOG_REL = Path("process/STORY-BACKLOG.md")
LEGACY_STORY_STATUS_REL = Path("process/STORY-STATUS.md")
FEATURE_TASKS_GLOB = "docs/features/*/TASKS.md"

ALLOWED_RETURN_PACKET_TYPES = {"story_return_packet"}
ALLOWED_RETURN_STAGES = {"CP6", "CP7"}
ALLOWED_CP6_STATUSES = {
    "implemented",
    "implemented_with_risk",
    "partial",
    "blocked",
    "needs_design_clarification",
    "needs_user_decision",
    "needs_rework",
    "no_op",
    "superseded",
    "waived",
}
ALLOWED_CP7_STATUSES = {
    "verified",
    "verified_with_risk",
    "partial",
    "blocked",
    "needs_rework",
    "needs_design_clarification",
    "needs_user_decision",
    "no_op",
    "superseded",
    "waived",
}
NON_TERMINAL_STATUSES = {
    "blocked",
    "needs_design_clarification",
    "needs_user_decision",
    "needs_rework",
    "partial",
    "no_op",
    "superseded",
    "waived",
}
ALLOWED_DELTA_TYPES = {"none", "patch", "new_contract", "migration", "open_question"}
ALLOWED_DELTA_STATUSES = {"pending", "merged", "deferred", "waived"}
ALLOWED_STORY_PLAN_STATUSES = {
    "draft",
    "lld-ready",
    "lld-in-progress",
    "lld-ready-for-review",
    "lld-batch-ready-for-review",
    "lld-approved",
    "dev-ready",
    "in-development",
    "ready-for-verification",
    "verified",
    "verified-with-risk",
    "done",
    "blocked",
    "needs-rework",
    "needs-design-clarification",
    "waived",
}
STORY_ID_RE = re.compile(r"\bSTORY-[A-Za-z0-9][A-Za-z0-9._-]*\b")
FULL_LLD_REQUIRED_SECTION_PREFIXES = tuple(f"## {index}." for index in range(15))
BATCH_LLD_REQUIRED_SECTION_PREFIXES = tuple(f"## {index}." for index in range(10))
FULL_LLD_REQUIRED_SEMANTIC_TOKENS = (
    "工程依据",
    "目标",
    "需求",
    "模块拆分",
    "代码结构",
    "数据模型",
    "API",
    "流程",
    "技术细节",
    "安全",
    "测试",
    "实施",
    "风险",
    "DoD",
)
BATCH_LLD_REQUIRED_TOKENS = (
    "design_evidence_type",
    "lld_policy_required_level",
    "batch_scope",
    "homogeneous_story_pattern",
    "risk_level",
    "shared_contract",
)
BATCH_LLD_FORBIDDEN_HIGH_RISK_TOKENS = (
    "runtime-high-risk",
    "security-high",
    "external-write",
    "credential",
    "production-write",
)
CP5_DENY_DEFAULT_REFS = (
    "docs/design/HLD.md",
    "docs/design/ARCHITECTURE-DECISION.md",
    "docs/product/TEST-MATRIX.md",
    "docs/quality/TEST-REPORT.md",
    "docs/quality/REVIEW.md",
)
TECHNICAL_NOTE_REQUIRED_TOKENS = (
    "设计依据",
    "文件影响",
    "接口",
    "数据",
    "权限",
    "失败",
    "测试",
    "风险",
)
WAIVED_REQUIRED_TOKENS = ("豁免", "理由", "风险", "重访")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(
                json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            )
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _infer_project_root(path: Path) -> Path:
    for parent in path.resolve().parents:
        if parent.name == "process":
            return parent.parent
    return Path.cwd().resolve()


def _rel(project_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _canonical_runtime_ref(project_root: Path, path: Path) -> str:
    """把 release/process 物理路径还原为可持久化的 canonical logical ref。"""

    root = project_root.resolve()
    resolved = path.resolve(strict=False)
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        process_marker = _resolve_runtime_ref(root, "process/.meta-flow-process.yaml")
        process_root = process_marker.parent.resolve(strict=False)
        try:
            process_relative = resolved.relative_to(process_root)
        except ValueError as exc:
            raise ValueError("runtime path is outside the release and bound process repositories") from exc
        return f"process/{process_relative.as_posix()}"


def _runtime_root(project_root: Path | None, path: Path) -> Path:
    if project_root is not None:
        return project_root.resolve()
    if path.is_absolute():
        return _infer_project_root(path)
    return Path.cwd().resolve()


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in _as_list(value) if str(item)]


def _slug_status(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def _markdown_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    values: dict[str, str] = {}
    for line in text[4:end].splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _entry_path(entry: Any) -> str:
    if isinstance(entry, dict):
        return str(entry.get("path") or "")
    return str(entry or "")


def _changed_file_path(entry: Any) -> str:
    return _entry_path(entry)


def _matches_any(rel_path: str, patterns: list[str]) -> bool:
    return any(rel_path == pattern or fnmatch(rel_path, pattern) for pattern in patterns)


def _infer_lld_evidence_type(path: Path, text: str, explicit: str = "") -> str:
    value = explicit.strip().lower()
    if value:
        return value
    lowered = text.lower()
    if "design_evidence_type: \"batch-lld\"" in lowered or "design_evidence_type: batch-lld" in lowered:
        return "batch-lld"
    if path.name.startswith("BATCH-"):
        return "batch-lld"
    if "design_evidence_type: \"waived\"" in lowered or "required_level: \"waived\"" in lowered:
        return "waived"
    if "## 技术说明" in text or "technical-note" in lowered:
        return "technical-note"
    if path.name.endswith("-LLD.md"):
        return "full-lld"
    return "unknown"


def _missing_section_prefixes(text: str, prefixes: tuple[str, ...]) -> list[str]:
    lines = [line.strip() for line in text.splitlines()]
    return [prefix for prefix in prefixes if not any(line.startswith(prefix) for line in lines)]


def validate_lld_structure(
    lld_path: Path,
    *,
    evidence_type: str = "",
    project_root: Path | None = None,
) -> tuple[list[str], list[str]]:
    root = project_root.resolve() if project_root else _infer_project_root(lld_path)
    path = _resolve_runtime_path(root, lld_path)
    if not path.is_file():
        return [f"LLD evidence missing: {_rel(root, path)}"], []
    text = path.read_text(encoding="utf-8", errors="ignore")
    frontmatter = _markdown_frontmatter(text)
    inferred = _infer_lld_evidence_type(path, text, evidence_type)
    errors: list[str] = []
    warnings: list[str] = []

    story_id = frontmatter.get("story_id") or ""
    filename_story_ids = STORY_ID_RE.findall(path.name)
    if story_id and story_id not in path.stem:
        errors.append(f"story_id does not match filename: story_id={story_id} file={path.name}")

    if inferred == "full-lld":
        missing = _missing_section_prefixes(text, FULL_LLD_REQUIRED_SECTION_PREFIXES)
        errors.extend(f"full-lld missing required section prefix: {prefix}" for prefix in missing)
        missing_tokens = [token for token in FULL_LLD_REQUIRED_SEMANTIC_TOKENS if token not in text]
        errors.extend(f"full-lld missing required semantic token: {token}" for token in missing_tokens)
        if not story_id and not filename_story_ids:
            warnings.append("full-lld has no detectable STORY-* id in frontmatter or filename")
    elif inferred == "batch-lld":
        missing = _missing_section_prefixes(text, BATCH_LLD_REQUIRED_SECTION_PREFIXES)
        errors.extend(f"batch-lld missing required section prefix: {prefix}" for prefix in missing)
        if "### Story:" not in text and not STORY_ID_RE.search(text):
            errors.append("batch-lld must include at least one Story marker or STORY-* id")
        for token in BATCH_LLD_REQUIRED_TOKENS:
            if token not in text:
                errors.append(f"batch-lld missing required batching token: {token}")
        for token in BATCH_LLD_FORBIDDEN_HIGH_RISK_TOKENS:
            if token in text.lower():
                errors.append(f"batch-lld contains high-risk marker requiring full-lld review: {token}")
    elif inferred == "technical-note":
        if "## 技术说明" not in text and "technical-note" not in text.lower():
            errors.append("technical-note evidence must include ## 技术说明 or technical-note marker")
        missing_tokens = [token for token in TECHNICAL_NOTE_REQUIRED_TOKENS if token not in text]
        errors.extend(f"technical-note missing required evidence token: {token}" for token in missing_tokens)
    elif inferred == "waived":
        missing_tokens = [token for token in WAIVED_REQUIRED_TOKENS if token not in text]
        errors.extend(f"waived evidence missing required token: {token}" for token in missing_tokens)
    else:
        errors.append("unable to infer LLD evidence type; pass --evidence-type full-lld|batch-lld|technical-note|waived")

    return errors, warnings


def _load_context_payload(path: Path) -> dict[str, Any]:
    if path.suffix.lower() == ".json":
        return _read_json(path)
    payload = load_yaml_object(path)
    return payload if isinstance(payload, dict) else {}


def _context_values(payload: dict[str, Any], key: str) -> list[str]:
    values = payload.get(key)
    if isinstance(values, list):
        result: list[str] = []
        for item in values:
            if isinstance(item, dict):
                result.append(str(item.get("path") or item.get("ref") or item.get("id") or ""))
            else:
                result.append(str(item or ""))
        return [item for item in result if item]
    if isinstance(values, dict):
        return [str(item) for item in values.values() if str(item)]
    if values:
        return [str(values)]
    return []


def _has_read_expansion_reason(payload: dict[str, Any]) -> bool:
    if payload.get("full_doc_read_reason"):
        return True
    log = payload.get("read_expansion_log") or payload.get("read_expansion_refs")
    return bool(log)


def validate_cp5_context_capsule(context_path: Path, *, project_root: Path | None = None) -> tuple[list[str], list[str]]:
    path = context_path.resolve()
    root = project_root.resolve() if project_root else _infer_project_root(path)
    if not path.is_file():
        return [f"CP5 context missing: {_rel(root, path)}"], []
    try:
        payload = _load_context_payload(path)
    except (OSError, ValueError) as exc:
        return [str(exc)], []
    errors: list[str] = []
    warnings: list[str] = []
    checkpoint = str(payload.get("checkpoint") or payload.get("stage") or "")
    if checkpoint and "CP5" not in checkpoint:
        errors.append(f"context checkpoint/stage must be CP5, got {checkpoint}")
    read_profile = str(payload.get("read_profile") or "").strip()
    if not read_profile:
        errors.append("CP5 context missing read_profile")
    elif read_profile == "full" and not _has_read_expansion_reason(payload):
        errors.append("CP5 context read_profile=full requires full_doc_read_reason or read_expansion_log")
    if not any(payload.get(key) for key in ("allowed_reads", "must_read", "read_if_needed", "context_refs", "evidence_refs")):
        errors.append("CP5 context must declare allowed/must/read-if-needed refs or evidence refs")
    expanded_without_reason = not _has_read_expansion_reason(payload)
    for key in ("allowed_reads", "must_read"):
        refs = _context_values(payload, key)
        for ref in refs:
            for denied in CP5_DENY_DEFAULT_REFS:
                if ref.split("#", 1)[0] == denied and expanded_without_reason:
                    errors.append(f"CP5 capsule-first violation: {key} includes deny-default full doc without expansion reason: {denied}")
            if ref.endswith("-LLD.md") and expanded_without_reason:
                warnings.append(f"CP5 context {key} includes full LLD by default; prefer evidence index or read_if_needed: {ref}")
    do_not_read = set(_context_values(payload, "do_not_read_by_default"))
    if not do_not_read.intersection(CP5_DENY_DEFAULT_REFS):
        warnings.append("CP5 context should list full design/test docs in do_not_read_by_default")
    return errors, warnings


def default_return_path(project_root: Path, story_id: str, stage: str) -> Path:
    return _resolve_runtime_ref(project_root, f"process/returns/{story_id}.{stage}.return.json")


def default_evidence_path(project_root: Path, story_id: str, stage: str) -> Path:
    return _resolve_runtime_ref(project_root, EVIDENCE_ROOT_REL.as_posix()) / f"{story_id}.{stage}.index.json"


def default_design_delta_path(project_root: Path, story_id: str) -> Path:
    return _resolve_runtime_ref(project_root, DESIGN_DELTA_ROOT_REL.as_posix()) / f"{story_id}.delta.json"


def _iter_plan_story_entries(plan: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for story in _as_list(plan.get("stories")):
        if isinstance(story, dict):
            item = dict(story)
            if item.get("wave") is None:
                item["wave"] = item.get("wave_id") or ""
            entries.append(item)
    for wave in _as_list(plan.get("waves")):
        if not isinstance(wave, dict):
            continue
        wave_id = str(wave.get("wave") or wave.get("id") or wave.get("wave_id") or "")
        for story in _as_list(wave.get("stories")):
            if isinstance(story, dict):
                item = dict(story)
                if item.get("wave") is None:
                    item["wave"] = wave_id
                entries.append(item)
    return entries


def _task_ids_from_plan_story(story: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for key in ("tasks", "task_refs", "task_ids"):
        for entry in _as_list(story.get(key)):
            if isinstance(entry, dict):
                task_id = str(entry.get("task_id") or entry.get("id") or "")
            else:
                task_id = str(entry or "")
            if task_id:
                ids.add(task_id)
    return ids


def _legacy_story_ids(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    return set(STORY_ID_RE.findall(path.read_text(encoding="utf-8")))


def _markdown_table_statuses(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    statuses: dict[str, str] = {}
    header: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line.startswith("|") or "STORY-" not in line:
            if line.startswith("|") and ("Story ID" in line or "故事" in line):
                header = [cell.strip().lower() for cell in line.strip("|").split("|")]
            continue
        cells = [cell.strip().strip("`") for cell in line.strip("|").split("|")]
        story_id = next((cell for cell in cells if STORY_ID_RE.fullmatch(cell)), "")
        if not story_id:
            continue
        status_index = -1
        for candidate in ("状态", "status"):
            if candidate in header:
                status_index = header.index(candidate)
                break
        if status_index < 0 or status_index >= len(cells):
            continue
        status = _slug_status(cells[status_index])
        if status:
            statuses[story_id] = status
    return statuses


def _task_ids_from_markdown(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    text = path.read_text(encoding="utf-8")
    return set(re.findall(r"\b(?:TASK|T)-[A-Za-z0-9][A-Za-z0-9._-]*\b", text))


def validate_story_plan(project_root: Path, *, plan_path: Path | None = None, strict_legacy: bool = False) -> tuple[list[str], list[str]]:
    root = project_root.resolve()
    path = _resolve_runtime_path(root, plan_path or DEVELOPMENT_PLAN_REL)
    errors: list[str] = []
    warnings: list[str] = []
    if not path.is_file():
        return [f"missing story management truth source: {_rel(root, path)}"], warnings
    try:
        plan = load_yaml_object(path)
    except (OSError, ValueError) as exc:
        return [f"invalid development plan: {exc}"], warnings
    truth_source = str(plan.get("story_management_truth_source") or "").strip()
    if truth_source and truth_source != DEVELOPMENT_PLAN_REL.as_posix():
        errors.append(
            f"story_management_truth_source must be {DEVELOPMENT_PLAN_REL.as_posix()}: {truth_source}"
        )
    if not truth_source:
        warnings.append("story_management_truth_source is missing; defaulting to process/DEVELOPMENT-PLAN.yaml")

    story_entries = _iter_plan_story_entries(plan)
    if not story_entries:
        errors.append("DEVELOPMENT-PLAN must contain stories under top-level stories or waves[*].stories")
        return errors, warnings

    plan_statuses: dict[str, str] = {}
    plan_tasks: set[str] = set()
    seen: set[str] = set()
    for index, story in enumerate(story_entries, start=1):
        story_id = str(story.get("story_id") or story.get("id") or "").strip()
        if not story_id:
            errors.append(f"story[{index}] missing story_id")
            continue
        if story_id in seen:
            errors.append(f"duplicate story_id in DEVELOPMENT-PLAN: {story_id}")
        seen.add(story_id)
        title = str(story.get("title") or "").strip()
        if not title:
            errors.append(f"{story_id} missing title")
        wave = str(story.get("wave") or story.get("wave_id") or "").strip()
        if not wave:
            errors.append(f"{story_id} missing wave")
        status = _slug_status(story.get("status") or "draft")
        if status not in ALLOWED_STORY_PLAN_STATUSES:
            errors.append(f"{story_id} invalid status: {status}")
        plan_statuses[story_id] = status
        plan_tasks.update(_task_ids_from_plan_story(story))

    legacy_paths = [
        _resolve_runtime_ref(root, LEGACY_STORY_BACKLOG_REL.as_posix()),
        _resolve_runtime_ref(root, LEGACY_STORY_STATUS_REL.as_posix()),
        *sorted((root / "docs" / "features").glob("*/TASKS.md")),
    ]
    legacy_story_ids: dict[str, set[str]] = {
        _rel(root, legacy): _legacy_story_ids(legacy) for legacy in legacy_paths if legacy.is_file()
    }
    unknown_refs: list[str] = []
    for rel_path, story_ids in legacy_story_ids.items():
        for story_id in sorted(story_ids - set(plan_statuses)):
            unknown_refs.append(f"{rel_path}:{story_id}")
    if unknown_refs:
        message = "legacy story refs missing from DEVELOPMENT-PLAN: " + ", ".join(unknown_refs)
        if strict_legacy:
            errors.append(message)
        else:
            warnings.append(message)

    legacy_statuses = _markdown_table_statuses(
        _resolve_runtime_ref(root, LEGACY_STORY_STATUS_REL.as_posix())
    )
    for story_id, legacy_status in sorted(legacy_statuses.items()):
        plan_status = plan_statuses.get(story_id)
        if plan_status and legacy_status != plan_status:
            errors.append(
                f"legacy STORY-STATUS status conflict for {story_id}: plan={plan_status} legacy={legacy_status}"
            )

    legacy_task_ids: dict[str, set[str]] = {
        _rel(root, path): _task_ids_from_markdown(path)
        for path in sorted((root / "docs" / "features").glob("*/TASKS.md"))
    }
    unknown_tasks: list[str] = []
    for rel_path, task_ids in legacy_task_ids.items():
        for task_id in sorted(task_ids - plan_tasks):
            unknown_tasks.append(f"{rel_path}:{task_id}")
    if unknown_tasks:
        message = "legacy Feature TASKS refs missing from DEVELOPMENT-PLAN tasks: " + ", ".join(unknown_tasks)
        if strict_legacy:
            errors.append(message)
        else:
            warnings.append(message)
    return errors, warnings


def load_return_packet(path: Path) -> dict[str, Any]:
    return _read_json(path.resolve())


def _allowed_statuses(stage: str) -> set[str]:
    if stage == "CP6":
        return ALLOWED_CP6_STATUSES
    if stage == "CP7":
        return ALLOWED_CP7_STATUSES
    return set()


def validate_return_packet(
    return_path: Path,
    *,
    packet_path: Path | None = None,
    project_root: Path | None = None,
) -> tuple[list[str], list[str]]:
    root = _runtime_root(project_root, return_path)
    return_path = _resolve_runtime_path(root, return_path)
    if not return_path.is_file():
        return [f"Story return packet missing: {_canonical_runtime_ref(root, return_path)}"], []
    errors: list[str] = []
    warnings: list[str] = []
    try:
        packet = load_return_packet(return_path)
    except ValueError as exc:
        return [str(exc)], []

    context: dict[str, Any] = {}
    if packet_path:
        packet_path = _resolve_runtime_path(root, packet_path)
        if not packet_path.is_file():
            errors.append(f"Story context packet missing: {_canonical_runtime_ref(root, packet_path)}")
        else:
            try:
                context = _read_json(packet_path.resolve())
            except ValueError as exc:
                errors.append(str(exc))

    if packet.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if packet.get("packet_type") not in ALLOWED_RETURN_PACKET_TYPES:
        errors.append(f"invalid packet_type: {packet.get('packet_type')}")
    stage = str(packet.get("stage") or "")
    if stage not in ALLOWED_RETURN_STAGES:
        errors.append(f"invalid stage: {stage or '-'}")
    status = str(packet.get("status") or "")
    if stage in ALLOWED_RETURN_STAGES and status not in _allowed_statuses(stage):
        errors.append(f"invalid status for {stage}: {status or '-'}")
    for key in ("story_id", "cr_id", "status", "touched_files", "boundary_check", "verification"):
        if key not in packet:
            errors.append(f"missing required field: {key}")

    if context:
        if packet.get("story_id") != context.get("story_id"):
            errors.append(f"story_id mismatch: return={packet.get('story_id')} context={context.get('story_id')}")
        if packet.get("stage") != context.get("stage"):
            errors.append(f"stage mismatch: return={packet.get('stage')} context={context.get('stage')}")
        expected = str(context.get("expected_return_packet") or "")
        if expected and _canonical_runtime_ref(root, return_path) != expected:
            warnings.append(f"return path differs from expected_return_packet: expected {expected}")

    touched_files = [_changed_file_path(entry) for entry in _as_list(packet.get("touched_files")) if _changed_file_path(entry)]
    if status not in NON_TERMINAL_STATUSES and stage == "CP6" and not touched_files:
        errors.append("CP6 implemented return must include touched_files")

    allowed_patterns = _string_list(context.get("allowed_write_paths")) if context else []
    forbidden_patterns = _string_list(context.get("forbidden_write_paths")) if context else []
    for rel_path in touched_files:
        if allowed_patterns and not _matches_any(rel_path, allowed_patterns):
            errors.append(f"touched file outside allowed_write_paths: {rel_path}")
        if forbidden_patterns and _matches_any(rel_path, forbidden_patterns):
            errors.append(f"touched file matches forbidden_write_paths: {rel_path}")

    boundary = packet.get("boundary_check") or {}
    if not isinstance(boundary, dict):
        errors.append("boundary_check must be an object")
        boundary = {}
    if boundary.get("allowed_paths_only") is False:
        errors.append("boundary_check.allowed_paths_only must not be false")
    for rel_path in _string_list(boundary.get("forbidden_paths_touched")):
        errors.append(f"boundary_check reports forbidden path touched: {rel_path}")
    for item in _string_list(boundary.get("unexpected_imports")):
        errors.append(f"boundary_check reports unexpected import: {item}")

    contract_changes = packet.get("contract_changes") or {}
    if contract_changes and not isinstance(contract_changes, dict):
        errors.append("contract_changes must be an object")
        contract_changes = {}
    if contract_changes.get("design_delta_required") is True:
        delta_ref = str(contract_changes.get("design_delta_ref") or "")
        if not delta_ref:
            errors.append("contract_changes.design_delta_ref is required when design_delta_required=true")
        elif not (root / delta_ref).is_file():
            warnings.append(f"design_delta_ref not found on disk: {delta_ref}")

    verification = packet.get("verification") or {}
    if not isinstance(verification, dict):
        errors.append("verification must be an object")
        verification = {}
    commands = _as_list(verification.get("commands_run"))
    evidence_refs = _string_list(packet.get("evidence_refs"))
    if status not in NON_TERMINAL_STATUSES and not commands and not evidence_refs:
        errors.append("successful return must include verification.commands_run or evidence_refs")
    for command in commands:
        if not isinstance(command, dict):
            errors.append("verification.commands_run entries must be objects")
            continue
        if not command.get("command") or not command.get("result"):
            errors.append("verification.commands_run entries require command and result")

    return errors, warnings


def build_evidence_index(
    project_root: Path,
    *,
    return_path: Path,
    output: Path | None = None,
) -> tuple[dict[str, Any], Path]:
    root = project_root.resolve()
    return_path = _resolve_runtime_path(root, return_path)
    packet = load_return_packet(return_path)
    story_id = str(packet.get("story_id") or "")
    stage = str(packet.get("stage") or "")
    if not story_id or not stage:
        raise ValueError("return packet must include story_id and stage")
    verification = packet.get("verification") or {}
    evidence = {
        "schema_version": 1,
        "story_id": story_id,
        "cr_id": packet.get("cr_id"),
        "stage": stage,
        "return_ref": _canonical_runtime_ref(root, return_path),
        "changed_files": _as_list(packet.get("touched_files")),
        "commands": _as_list(verification.get("commands_run")),
        "tests": _as_list(verification.get("tests")),
        "artifacts": _as_list(packet.get("artifacts")),
        "risks": _as_list(packet.get("risks")),
        "waivers": _as_list(packet.get("waivers")),
        "design_delta_ref": (packet.get("contract_changes") or {}).get("design_delta_ref"),
    }
    output_path = _resolve_runtime_path(root, output) if output else default_evidence_path(root, story_id, stage)
    _write_json(output_path, evidence)
    return evidence, output_path


def validate_evidence_index(index_path: Path, *, project_root: Path | None = None) -> tuple[list[str], list[str]]:
    root = _runtime_root(project_root, index_path)
    index_path = _resolve_runtime_path(root, index_path)
    if not index_path.is_file():
        return [f"Evidence index missing: {_canonical_runtime_ref(root, index_path)}"], []
    errors: list[str] = []
    warnings: list[str] = []
    try:
        evidence = _read_json(index_path)
    except ValueError as exc:
        return [str(exc)], []
    if evidence.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    for key in ("story_id", "stage", "return_ref", "changed_files", "commands", "risks", "waivers"):
        if key not in evidence:
            errors.append(f"missing required field: {key}")
    return_ref = str(evidence.get("return_ref") or "")
    if return_ref:
        if not return_ref.startswith("process/"):
            errors.append("return_ref must be one canonical process/... logical ref")
        else:
            resolved_return = _resolve_runtime_path(root, return_ref)
            if not resolved_return.is_file():
                errors.append(f"return_ref missing on disk: {return_ref}")
    stage = str(evidence.get("stage") or "")
    if stage not in ALLOWED_RETURN_STAGES:
        errors.append(f"invalid stage: {stage or '-'}")
    changed_files = evidence.get("changed_files")
    if changed_files is not None and not isinstance(changed_files, list):
        errors.append("changed_files must be a list")
    commands = evidence.get("commands")
    if commands is not None and not isinstance(commands, list):
        errors.append("commands must be a list")
    if not evidence.get("changed_files") and not evidence.get("commands"):
        warnings.append("evidence index has no changed_files and no commands")
    return errors, warnings


def validate_design_delta(
    delta_path: Path,
    *,
    project_root: Path | None = None,
    require_merged: bool = False,
) -> tuple[list[str], list[str]]:
    delta_path = delta_path.resolve()
    if not delta_path.is_file():
        return [f"Design delta missing: {delta_path}"], []
    root = project_root.resolve() if project_root else _infer_project_root(delta_path)
    errors: list[str] = []
    warnings: list[str] = []
    try:
        delta = _read_json(delta_path)
    except ValueError as exc:
        return [str(exc)], []
    if delta.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    for key in ("story_id", "feature_id", "delta_type", "status"):
        if key not in delta:
            errors.append(f"missing required field: {key}")
    delta_type = str(delta.get("delta_type") or "")
    if delta_type not in ALLOWED_DELTA_TYPES:
        errors.append(f"invalid delta_type: {delta_type or '-'}")
    status = str(delta.get("status") or "")
    if status not in ALLOWED_DELTA_STATUSES:
        errors.append(f"invalid status: {status or '-'}")
    target_doc = str(delta.get("target_doc") or "")
    if delta_type != "none":
        if not target_doc:
            errors.append("target_doc is required when delta_type is not none")
        elif not (root / target_doc).is_file():
            errors.append(f"target_doc missing on disk: {target_doc}")
        changes = delta.get("changes")
        if not isinstance(changes, list) or not changes:
            errors.append("changes must be a non-empty list when delta_type is not none")
        else:
            for item in changes:
                if not isinstance(item, dict):
                    errors.append("changes entries must be objects")
                    continue
                if not item.get("section") or not item.get("operation") or not item.get("summary"):
                    errors.append("changes entries require section, operation, and summary")
    if delta.get("requires_feature_doc_update") is True and status != "merged":
        message = "design delta requires feature doc update but is not merged"
        if require_merged:
            errors.append(message)
        else:
            warnings.append(message)
    if require_merged and status != "merged":
        errors.append("design delta status must be merged")
    if status == "merged" and not delta.get("merged_ref"):
        warnings.append("merged design delta should include merged_ref")
    return errors, warnings


def build_verify_packet_from_return(
    project_root: Path,
    *,
    return_path: Path,
    story_path: Path,
    output: Path | None = None,
    budget: int | None = None,
) -> tuple[dict[str, Any], Path]:
    root = project_root.resolve()
    return_path = _resolve_runtime_path(root, return_path)
    if not return_path.is_file():
        raise ValueError(
            "CP6 Return Packet missing: "
            + _canonical_runtime_ref(root, return_path)
        )
    packet = load_return_packet(return_path)
    story_id = str(packet.get("story_id") or "")
    stage = str(packet.get("stage") or "")
    if stage != "CP6":
        raise ValueError("verify packet can only be built from a CP6 return packet")
    if not story_id:
        raise ValueError("return packet must include story_id")
    return story_contract.build_story_packet(
        root,
        story_path=story_path,
        stage="CP7",
        cr_id=str(packet.get("cr_id") or ""),
        budget=budget,
        output=output,
        cp6_return_ref=_canonical_runtime_ref(root, return_path),
    )


def build_cp6_story_projection_plan(
    project_root: Path,
    *,
    result_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    """验证 CP6 ledger 事实并生成唯一的 Story 状态投影计划。"""

    root = project_root.resolve()
    result_path = _resolve_runtime_path(root, result_path)
    result_ref = _canonical_runtime_ref(root, result_path)
    errors, _warnings = cp_result.validate_cp_result(
        result_path,
        project_root=root,
        check_consistency=False,
        correlation_profile="compat",
    )
    if errors:
        raise ValueError("CP6 result is invalid: " + "; ".join(errors))
    result = cp_result.load_cp_result(result_path)
    if result.get("checkpoint") != "CP6" or result.get("decision") != "PASS":
        raise ValueError("Story projection requires a recorded CP6 PASS result")

    checkpoint_path = event_ledger.ledger_path(root, "checkpoint")
    if not checkpoint_path.is_file():
        raise ValueError("checkpoint ledger is missing; mutation=0")
    checkpoint_events, ledger_errors = event_ledger.load_events(checkpoint_path)
    if ledger_errors:
        raise ValueError(
            "checkpoint ledger is invalid; mutation=0: " + "; ".join(ledger_errors)
        )
    matches = [
        event
        for event in checkpoint_events
        if event.get("event_type") == "checkpoint_result"
        and event.get("result_ref") == result_ref
    ]
    if len(matches) != 1:
        raise ValueError(
            f"CP6 result requires exactly one checkpoint ledger event; found={len(matches)}; mutation=0"
        )
    event = matches[0]
    for key in ("event_id", "story_id", "cr_id", "decision"):
        if event.get(key) != result.get(key):
            raise ValueError(
                f"checkpoint ledger {key} does not match CP6 result; mutation=0"
            )

    plan_path = _resolve_runtime_ref(root, DEVELOPMENT_PLAN_REL.as_posix())
    if not plan_path.is_file():
        raise ValueError("DEVELOPMENT-PLAN is missing; mutation=0")
    before = load_yaml_object(plan_path)
    projected, transitions = state_transition.project_cp6_development_plan(
        before,
        result=result,
    )
    changed = projected != before
    digest_payload = {
        "schema_version": 1,
        "kind": "cp6_story_projection_plan",
        "operation": "story.project-cp6",
        "result_ref": result_ref,
        "checkpoint_event_id": str(event["event_id"]),
        "plan_ref": DEVELOPMENT_PLAN_REL.as_posix(),
        "story_id": str(result["story_id"]),
        "before_digest": canonical_digest(before),
        "result_digest": canonical_digest(result),
        "after_digest": canonical_digest(projected),
        "transitions": [dict(item) for item in transitions],
        "decision": "READY" if changed else "NO_CHANGE",
        "mutation_count": 1 if changed else 0,
        "mutation_allowlist": (
            [DEVELOPMENT_PLAN_REL.as_posix()] if changed else []
        ),
    }
    plan = dict(digest_payload)
    plan["plan_digest"] = canonical_digest(digest_payload)
    return plan, projected, plan_path


def apply_cp6_story_projection(
    project_root: Path,
    *,
    result_path: Path,
    expected_plan_digest: str,
) -> dict[str, Any]:
    """在重算计划完全一致后原子写入派生 DEVELOPMENT-PLAN。"""

    plan, projected, plan_path = build_cp6_story_projection_plan(
        project_root,
        result_path=result_path,
    )
    if plan["decision"] == "NO_CHANGE":
        return {
            "status": "NO_CHANGE",
            "decision": "NO_CHANGE",
            "mutation_count": 0,
            "plan_digest": plan["plan_digest"],
            "transitions": [],
        }
    if not expected_plan_digest:
        raise ValueError("apply requires --expected-plan-digest; mutation=0")
    if expected_plan_digest != plan["plan_digest"]:
        raise ValueError("CP6 projection plan digest drift; mutation=0")
    _atomic_write_json(plan_path, projected)
    after = load_yaml_object(plan_path)
    if canonical_digest(after) != plan["after_digest"]:
        raise ValueError("CP6 projection post-write digest mismatch")
    return {
        "status": "PASS",
        "decision": "PASS",
        "mutation_count": 1,
        "plan_digest": plan["plan_digest"],
        "mutation_allowlist": plan["mutation_allowlist"],
        "transitions": plan["transitions"],
    }


def _print_story_help() -> None:
    print(
        "usage: meta-flow story <command> [options]\n\n"
        "Commands:\n"
        "  return-check    Validate a Story Return Packet against its Story Work/Verify Packet.\n"
        "  evidence-index  Build an Evidence Index from a Story Return Packet.\n"
        "  evidence-check  Validate an Evidence Index.\n"
        "  verify-packet   Build a CP7 Story Verify Packet from a CP6 Return Packet.\n\n"
        "  plan-check      Validate DEVELOPMENT-PLAN as the Story management truth source.\n\n"
        "  project-cp6     Project a recorded CP6 PASS into DEVELOPMENT-PLAN.\n"
        "  lld-check       Validate full-lld, batch-lld, technical-note, or waived evidence structure.\n"
        "  cp5-context-check Validate CP5 capsule-first context policy.\n\n"
        "Examples:\n"
        "  meta-flow story return-check --packet process/context/stories/STORY-CR123-S01.CP6.work-packet.json --return process/returns/STORY-CR123-S01.CP6.return.json --project-root .\n"
        "  meta-flow story evidence-index --return process/returns/STORY-CR123-S01.CP6.return.json --project-root .\n"
        "  meta-flow story verify-packet --from-return process/returns/STORY-CR123-S01.CP6.return.json --story process/stories/STORY-CR123-S01.md --project-root .\n"
        "  meta-flow story plan-check --project-root .\n"
        "  meta-flow story project-cp6 --result process/checks/CP6-STORY-CR123-S01.result.json --project-root .\n"
        "  meta-flow story lld-check --lld process/stories/STORY-CR123-S01-LLD.md --project-root .\n"
        "  meta-flow story cp5-context-check --context process/context/CP5-LLD-CONTEXT.yaml --project-root .\n"
    )


def main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if not args or args[0] in {"-h", "--help"}:
        _print_story_help()
        return 0
    command = args[0]
    if command == "return-check":
        parser = argparse.ArgumentParser(prog="meta-flow story return-check")
        parser.add_argument("--project-root", type=Path, default=None)
        parser.add_argument("--packet", dest="packet_path", type=Path, required=True)
        parser.add_argument("--return", dest="return_path", type=Path, required=True)
        parsed = parser.parse_args(args[1:])
        try:
            errors, warnings = validate_return_packet(
                parsed.return_path,
                packet_path=parsed.packet_path,
                project_root=parsed.project_root,
            )
        except (OSError, ValueError) as exc:
            errors, warnings = [str(exc)], []
        print("Story Return Packet Check: " + ("FAIL" if errors else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    if command == "evidence-index":
        parser = argparse.ArgumentParser(prog="meta-flow story evidence-index")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--return", dest="return_path", type=Path, required=True)
        parser.add_argument("--output", type=Path, default=None)
        parsed = parser.parse_args(args[1:])
        try:
            _evidence, path = build_evidence_index(
                parsed.project_root,
                return_path=parsed.return_path,
                output=parsed.output,
            )
            print(f"wrote: {_canonical_runtime_ref(parsed.project_root, path)}")
            return 0
        except (OSError, ValueError) as exc:
            print("Evidence Index Build: FAIL")
            print(f"- ERROR: {exc}")
            return 1
    if command == "evidence-check":
        parser = argparse.ArgumentParser(prog="meta-flow story evidence-check")
        parser.add_argument("--project-root", type=Path, default=None)
        parser.add_argument("--index", dest="index_path", type=Path, required=True)
        parsed = parser.parse_args(args[1:])
        try:
            errors, warnings = validate_evidence_index(
                parsed.index_path,
                project_root=parsed.project_root,
            )
        except (OSError, ValueError) as exc:
            errors, warnings = [str(exc)], []
        print("Evidence Index Check: " + ("FAIL" if errors else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    if command == "verify-packet":
        parser = argparse.ArgumentParser(prog="meta-flow story verify-packet")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--from-return", dest="return_path", type=Path, required=True)
        parser.add_argument("--story", dest="story_path", type=Path, required=True)
        parser.add_argument("--output", type=Path, default=None)
        parser.add_argument("--budget", type=int, default=None)
        parsed = parser.parse_args(args[1:])
        try:
            _packet, path = build_verify_packet_from_return(
                parsed.project_root,
                return_path=parsed.return_path,
                story_path=parsed.story_path,
                output=parsed.output,
                budget=parsed.budget,
            )
        except (OSError, ValueError) as exc:
            print("Story Verify Packet: BLOCKED")
            print(f"- {exc}")
            return 2
        print(f"wrote: {_canonical_runtime_ref(parsed.project_root, path)}")
        return 0
    if command == "plan-check":
        parser = argparse.ArgumentParser(prog="meta-flow story plan-check")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--plan", dest="plan_path", type=Path, default=None)
        parser.add_argument("--strict-legacy", action="store_true")
        parsed = parser.parse_args(args[1:])
        errors, warnings = validate_story_plan(
            parsed.project_root,
            plan_path=parsed.plan_path,
            strict_legacy=parsed.strict_legacy,
        )
        print("Story Plan Check: " + ("FAIL" if errors else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    if command == "project-cp6":
        parser = argparse.ArgumentParser(prog="meta-flow story project-cp6")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--result", dest="result_path", type=Path, required=True)
        parser.add_argument("--expected-plan-digest", default="")
        parser.add_argument("--apply", action="store_true")
        parsed = parser.parse_args(args[1:])
        try:
            if parsed.apply:
                output = apply_cp6_story_projection(
                    parsed.project_root,
                    result_path=parsed.result_path,
                    expected_plan_digest=parsed.expected_plan_digest,
                )
            else:
                output, _projected, _path = build_cp6_story_projection_plan(
                    parsed.project_root,
                    result_path=parsed.result_path,
                )
            print(json.dumps(output, ensure_ascii=False, sort_keys=True))
            return 0
        except (OSError, ValueError) as exc:
            print(
                json.dumps(
                    {
                        "status": "BLOCKED",
                        "decision": "BLOCKED",
                        "mutation_count": 0,
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 2
    if command == "lld-check":
        parser = argparse.ArgumentParser(prog="meta-flow story lld-check")
        parser.add_argument("--project-root", type=Path, default=None)
        parser.add_argument("--lld", dest="lld_path", type=Path, required=True)
        parser.add_argument("--evidence-type", default="")
        parsed = parser.parse_args(args[1:])
        errors, warnings = validate_lld_structure(
            parsed.lld_path,
            evidence_type=parsed.evidence_type,
            project_root=parsed.project_root,
        )
        print("LLD Structure Check: " + ("FAIL" if errors else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    if command == "cp5-context-check":
        parser = argparse.ArgumentParser(prog="meta-flow story cp5-context-check")
        parser.add_argument("--project-root", type=Path, default=None)
        parser.add_argument("--context", dest="context_path", type=Path, required=True)
        parsed = parser.parse_args(args[1:])
        errors, warnings = validate_cp5_context_capsule(parsed.context_path, project_root=parsed.project_root)
        print("CP5 Context Check: " + ("FAIL" if errors else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    raise SystemExit(f"未知 story 命令: {command}")


def _print_design_help() -> None:
    print(
        "usage: meta-flow design <command> [options]\n\n"
        "Commands:\n"
        "  delta-check  Validate a Story design delta and optional CP8 merged status.\n\n"
        "Examples:\n"
        "  meta-flow design delta-check --delta process/design-deltas/STORY-CR123-S01.delta.json --project-root .\n"
        "  meta-flow design delta-check --delta process/design-deltas/STORY-CR123-S01.delta.json --require-merged --project-root .\n"
    )


def design_main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if not args or args[0] in {"-h", "--help"}:
        _print_design_help()
        return 0
    command = args[0]
    if command == "delta-check":
        parser = argparse.ArgumentParser(prog="meta-flow design delta-check")
        parser.add_argument("--project-root", type=Path, default=None)
        parser.add_argument("--delta", dest="delta_path", type=Path, required=True)
        parser.add_argument("--require-merged", action="store_true")
        parsed = parser.parse_args(args[1:])
        errors, warnings = validate_design_delta(
            parsed.delta_path,
            project_root=parsed.project_root,
            require_merged=parsed.require_merged,
        )
        print("Design Delta Check: " + ("FAIL" if errors else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    raise SystemExit(f"未知 design 命令: {command}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
