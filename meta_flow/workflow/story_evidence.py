"""Story return packets, evidence indexes, and design deltas."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from meta_flow.checks import cp_result, state_transition
from meta_flow.checks.frozen_cp6_evidence import (
    Cp6RevalidationReceiptV1,
    FrozenCp6EvidenceError,
    FrozenCp6EvidenceV2,
    build_cp6_evidence_v2,
    build_cp6_revalidation_receipt,
    freeze_cp6_revalidation_authorization,
    freeze_cp6_revalidation_receipt,
)
from meta_flow.context_pack import read_expansion, story_contract
from meta_flow.project.onboarding_contract import canonical_digest
from meta_flow.project.process_route import (
    _resolve_runtime_path,
    _resolve_runtime_ref,
    format_runtime_ref,
)
from meta_flow.project.scale import load_yaml_object
from meta_flow.semantics import preregistration
from meta_flow.semantics.authority import (
    render_authority_apply_result,
    render_authority_input_blocked,
    render_human_wire,
    validate_authority_binding,
)
from meta_flow.state import event_ledger

PUBLIC_OPERATION_DECLARATIONS = (
    ("story.project-cp6", ("meta-flow", "story", "project-cp6")),
    (
        "story.issue-revalidation-authority",
        ("meta-flow", "story", "issue-revalidation-authority"),
    ),
)
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


def _create_once_json(path: Path, data: dict[str, Any]) -> dict[str, Any]:
    """以 create-once 语义写入 canonical JSON，不覆盖任何既有 bytes。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, sort_keys=True)
        stream.write("\n")
    return {"status": "APPLIED", "mutation_count": 1}


def _target_bytes_observation(path: Path) -> tuple[str, bytes]:
    """读取 writer 前后目标状态；不可观察按 unknown 处理，不能宣称零 mutation。"""

    try:
        if not path.exists():
            return ("missing", b"")
        if not path.is_file():
            return ("non-file", b"")
        return ("file", path.read_bytes())
    except OSError:
        return ("unknown", b"")


def _writer_exception_result(
    path: Path,
    before: tuple[str, bytes],
    *,
    blocked_code: str,
    partial_code: str,
) -> dict[str, Any]:
    """依据实际 preimage/postimage 分类 writer exception。"""

    after = _target_bytes_observation(path)
    if before[0] == "unknown" or after[0] == "unknown" or after != before:
        return {
            "status": "PARTIAL",
            "decision": "PARTIAL",
            "mutation_count": 1,
            "reason_codes": [partial_code],
        }
    return _blocked_revalidation(blocked_code)


def _infer_project_root(path: Path) -> Path:
    for parent in path.resolve().parents:
        if parent.name == "process":
            return parent.parent
    return Path.cwd().resolve()


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
    normalized = str(value or "").strip().lower().replace("_", "-")
    return {
        "completed": "done",
        "completed-direct": "done",
    }.get(normalized, normalized)


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
        return [f"LLD evidence missing: {format_runtime_ref(root, path)}"], []
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
        return [f"CP5 context missing: {format_runtime_ref(root, path)}"], []
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


def validate_per_cr_story_plan_truth_source(
    plan: Mapping[str, Any],
    *,
    expected_cr_id: str = "",
    project_root: Path | None = None,
) -> list[str]:
    """Validate an explicit per-CR source; generic and per-CR declarations collide."""
    source = plan.get("story_management_truth_source")
    declared = plan.get("per_cr_story_plan_truth_source")
    if declared is None:
        return []
    if source:
        return ["GENERIC_PER_CR_COLLISION"]
    if not isinstance(declared, Mapping) or set(declared) != {"schema_version", "project_id", "cr_id", "plan_ref", "plan_sha256"}:
        return ["SCHEMA_MISMATCH"]
    if declared.get("schema_version") != 1:
        return ["SCHEMA_MISMATCH"]
    ref = declared.get("plan_ref")
    if not isinstance(ref, str) or not re.fullmatch(r"process/(?!.*(?:^|/)\.\.?(?:/|$))[A-Za-z0-9][A-Za-z0-9._/-]*", ref):
        return ["OUTSIDE_PROCESS_REF"]
    if not isinstance(declared.get("project_id"), str) or not declared["project_id"]:
        return ["PROJECT_MISMATCH"]
    if expected_cr_id and declared.get("cr_id") != expected_cr_id:
        return ["CR_MISMATCH"]
    if not isinstance(declared.get("plan_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", declared["plan_sha256"]):
        return ["STALE_PLAN_DIGEST"]
    if project_root is not None:
        try:
            declared_path = _resolve_runtime_ref(project_root.resolve(), ref)
            raw = declared_path.read_bytes()
        except (OSError, ValueError):
            return ["MISSING_TRUTH_SOURCE"]
        if hashlib.sha256(raw).hexdigest() != declared["plan_sha256"]:
            return ["STALE_PLAN_DIGEST"]
    return []


def validate_story_plan(
    project_root: Path,
    *,
    plan_path: Path | None = None,
    strict_legacy: bool = False,
    expected_plan_sha256: str = "",
) -> tuple[list[str], list[str]]:
    root = project_root.resolve()
    path = _resolve_runtime_path(root, plan_path or DEVELOPMENT_PLAN_REL)
    errors: list[str] = []
    warnings: list[str] = []
    if not path.is_file():
        return [f"missing story management truth source: {format_runtime_ref(root, path)}"], warnings
    try:
        plan = load_yaml_object(path)
    except (OSError, ValueError) as exc:
        return [f"invalid development plan: {exc}"], warnings
    expected_cr_id = str(plan.get("change_id") or "")
    errors.extend(
        validate_per_cr_story_plan_truth_source(
            plan,
            expected_cr_id=expected_cr_id,
            project_root=root,
        )
    )
    truth_source = str(plan.get("story_management_truth_source") or "").strip()
    if truth_source and (not truth_source.startswith("process/") or truth_source.startswith("/")):
        errors.append("story_management_truth_source must be a process logical ref")
    if not truth_source:
        warnings.append("story_management_truth_source is missing; defaulting to process/DEVELOPMENT-PLAN.yaml")
    elif not errors:
        try:
            declared_path = _resolve_runtime_ref(root, truth_source)
        except (OSError, ValueError):
            errors.append("MISSING_TRUTH_SOURCE")
        else:
            if declared_path.resolve(strict=False) != path.resolve(strict=False):
                errors.append("GENERIC_PER_CR_COLLISION")
            elif truth_source != DEVELOPMENT_PLAN_REL.as_posix():
                if not re.fullmatch(r"[0-9a-f]{64}", expected_plan_sha256):
                    errors.append(
                        "per-CR story plan check requires --expected-plan-sha256"
                    )
                else:
                    try:
                        actual_digest = hashlib.sha256(declared_path.read_bytes()).hexdigest()
                    except OSError:
                        errors.append("MISSING_TRUTH_SOURCE")
                    else:
                        if actual_digest != expected_plan_sha256:
                            errors.append("STALE_PLAN_DIGEST")

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
        format_runtime_ref(root, legacy): _legacy_story_ids(legacy)
        for legacy in legacy_paths
        if legacy.is_file()
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
        format_runtime_ref(root, path): _task_ids_from_markdown(path)
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
        return [f"Story return packet missing: {format_runtime_ref(root, return_path)}"], []
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
            errors.append(f"Story context packet missing: {format_runtime_ref(root, packet_path)}")
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
        aggregate_context = (
            stage == "CP7"
            and context.get("stage") == "CP7"
            and context.get("story_id") is None
            and packet.get("cr_id") == context.get("cr_id")
            and packet.get("aggregate_context") is True
            and isinstance(packet.get("aggregate_story_ids"), list)
            and bool(packet.get("aggregate_story_ids"))
            and packet.get("story_id") in packet.get("aggregate_story_ids", [])
        )
        if packet.get("story_id") != context.get("story_id") and not aggregate_context:
            errors.append(f"story_id mismatch: return={packet.get('story_id')} context={context.get('story_id')}")
        if packet.get("stage") != context.get("stage"):
            errors.append(f"stage mismatch: return={packet.get('stage')} context={context.get('stage')}")
        expected = str(context.get("expected_return_packet") or "")
        if expected and format_runtime_ref(root, return_path) != expected:
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
        "return_ref": format_runtime_ref(root, return_path),
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
        return [f"Evidence index missing: {format_runtime_ref(root, index_path)}"], []
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
            + format_runtime_ref(root, return_path)
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
        cp6_return_ref=format_runtime_ref(root, return_path),
    )


def build_cp6_story_projection_plan(
    project_root: Path,
    *,
    result_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    """验证 CP6 ledger 事实并生成唯一的 Story 状态投影计划。"""

    root = project_root.resolve()
    result_path = _resolve_runtime_path(root, result_path)
    result_ref = format_runtime_ref(root, result_path)
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


def build_cp6_semantic_evidence_v2(
    project_root: Path,
    *,
    result_path: Path,
    release_oid: str,
    process_oid: str,
    scope_digest: str,
    implementation_digest: str,
    dependency_digests: Mapping[str, str],
) -> FrozenCp6EvidenceV2:
    """从 checkpoint ledger 已记录的真实 CP6 PASS 构造 contract-bound V2。"""

    root = project_root.resolve()
    projection, _projected, _plan_path = build_cp6_story_projection_plan(
        root,
        result_path=result_path,
    )
    return build_cp6_evidence_v2(
        root,
        story_id=str(projection["story_id"]),
        release_oid=release_oid,
        process_oid=process_oid,
        scope_digest=scope_digest,
        implementation_digest=implementation_digest,
        dependency_digests=dependency_digests,
        cp6_result_ref=str(projection["result_ref"]),
    )


def _parse_dependency_digest_arguments(values: list[str]) -> dict[str, str]:
    dependencies: dict[str, str] = {}
    for value in values:
        key, separator, digest = value.partition("=")
        if not separator or not key or key in dependencies:
            raise ValueError(
                "--dependency-digest must be unique KEY=SHA256 values"
            )
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("--dependency-digest value must be a lowercase sha256")
        dependencies[key] = digest
    return dict(sorted(dependencies.items()))


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


_REVALIDATION_AUTHORIZATION_FIELDS = frozenset(
    {
        "previous_cp6_ref", "superseding_cp5_ref", "approval_ref",
        "work_authorization_ref", "plan_preimage_digest", "downstream_set_digest", "downstream_set",
    }
)
_REVALIDATION_PREFLIGHT_FIELDS = frozenset(
    {"packet_digest", "read_log_digest", "return_digest", "evidence_digest",
     "result_digest", "checkpoint_digest", "plan_digest", "downstream_set_digest", "p01_event_ref"}
)
_REVALIDATION_DOWNSTREAM_POLICY_FIELDS = frozenset(
    {
        "schema_version",
        "logical_ref",
        "bytes_digest",
        "consumers",
        "policy_digest",
        "current_receipts",
    }
)


def _blocked_revalidation(code: str) -> dict[str, Any]:
    return {"status": "BLOCKED", "decision": "BLOCKED", "mutation_count": 0, "reason_codes": [code]}


def plan_cp6_revalidation(
    authorization: Cp6RevalidationReceiptV1 | Mapping[str, Any],
    *,
    source_observation: Mapping[str, Any],
    target_observation: Mapping[str, Any],
    downstream_policy: Mapping[str, Any],
) -> dict[str, Any]:
    """把授权、源、目标与下游策略冻结为可重放的 immutable plan。"""

    try:
        receipt = authorization if isinstance(authorization, Cp6RevalidationReceiptV1) else freeze_cp6_revalidation_receipt(**authorization)
    except (FrozenCp6EvidenceError, TypeError):
        return _blocked_revalidation("AUTHORIZATION_INVALID")
    if receipt.kind != "authorization" or set(receipt.payload) != _REVALIDATION_AUTHORIZATION_FIELDS:
        return _blocked_revalidation("AUTHORIZATION_FIELDS_INVALID")
    source = dict(source_observation)
    if set(source) != {"release_oid", "process_oid", "scope_digest"} or source != {
        "release_oid": receipt.release_oid,
        "process_oid": receipt.process_oid,
        "scope_digest": receipt.scope_digest,
    }:
        return _blocked_revalidation("AUTHORIZATION_SNAPSHOT_DRIFT")
    target = dict(target_observation)
    if (
        set(target) != {"logical_ref", "exists", "preimage_digest"}
        or not _is_process_logical_ref(target.get("logical_ref"))
        or not isinstance(target.get("exists"), bool)
        or (target["exists"] and not _is_sha256(target.get("preimage_digest")))
        or (not target["exists"] and target.get("preimage_digest") != "")
    ):
        return _blocked_revalidation("TARGET_OBSERVATION_INVALID")
    policy = dict(downstream_policy)
    consumers = policy.get("consumers")
    if (
        set(policy) != _REVALIDATION_DOWNSTREAM_POLICY_FIELDS
        or policy.get("schema_version") != 1
        or not _is_process_logical_ref(policy.get("logical_ref"))
        or not _is_sha256(policy.get("bytes_digest"))
        or not isinstance(consumers, Mapping)
        or policy.get("policy_digest") != canonical_digest(consumers)
        or policy.get("current_receipts") != receipt.payload["downstream_set"]
    ):
        return _blocked_revalidation("DOWNSTREAM_POLICY_INVALID")
    plan_payload = {
        "operation": "story.revalidate-cp6",
        "authorization_digest": receipt.as_dict()["payload_digest"],
        "attempt_id": receipt.attempt_id,
        "target_kind": "authorization",
        "source_observation": source,
        "target_observation": target,
        "downstream_policy": policy,
    }
    return {
        "status": "READY", "decision": "READY", "mutation_count": 1,
        "plan": plan_payload, "plan_digest": canonical_digest(plan_payload),
    }


def apply_cp6_revalidation_receipt(
    target: Path,
    receipt: Cp6RevalidationReceiptV1 | Mapping[str, Any],
    *,
    expected_plan_digest: str,
    plan: Mapping[str, Any],
    observe_current: Any,
    create_once_writer: Any,
    postcheck_reader: Any,
) -> dict[str, Any]:
    """在 apply 时重新观察全部冻结轴，并以 create-once 语义写入 receipt。"""

    try:
        frozen = receipt if isinstance(receipt, Cp6RevalidationReceiptV1) else freeze_cp6_revalidation_receipt(**receipt)
    except (FrozenCp6EvidenceError, TypeError):
        return _blocked_revalidation("RECEIPT_INVALID")
    current_plan_digest = canonical_digest(dict(plan))
    expected_authorization_digest = frozen.as_dict()["payload_digest"]
    if (
        not expected_plan_digest
        or current_plan_digest != expected_plan_digest
        or str(plan.get("authorization_digest") or "") != expected_authorization_digest
        or str(plan.get("attempt_id") or "") != frozen.attempt_id
        or str(plan.get("target_kind") or "") != frozen.kind
    ):
        return _blocked_revalidation("EXPECTED_PLAN_DIGEST_DRIFT")
    if set(plan) != {
        "operation", "authorization_digest", "attempt_id", "target_kind",
        "source_observation", "target_observation", "downstream_policy",
    }:
        return _blocked_revalidation("EXPECTED_PLAN_SHAPE_INVALID")
    try:
        current = observe_current()
    except Exception:
        return _blocked_revalidation("APPLY_CURRENT_OBSERVATION_UNAVAILABLE")
    if not isinstance(current, Mapping) or set(current) != {
        "source_observation", "target_observation", "downstream_policy",
    }:
        return _blocked_revalidation("APPLY_CURRENT_OBSERVATION_INVALID")
    if dict(current["source_observation"]) != dict(plan["source_observation"]):
        return _blocked_revalidation("APPLY_SOURCE_OBSERVATION_DRIFT")
    if dict(current["downstream_policy"]) != dict(plan["downstream_policy"]):
        return _blocked_revalidation("APPLY_DOWNSTREAM_POLICY_DRIFT")
    planned_target = dict(plan["target_observation"])
    current_target = dict(current["target_observation"])
    if (
        set(current_target) != {"logical_ref", "exists", "preimage_digest"}
        or current_target.get("logical_ref") != planned_target.get("logical_ref")
        or not _is_process_logical_ref(current_target.get("logical_ref"))
    ):
        return _blocked_revalidation("APPLY_TARGET_OBSERVATION_DRIFT")
    payload = frozen.as_dict()
    if target.exists():
        try:
            raw = target.read_bytes()
            existing = json.loads(raw)
        except (OSError, ValueError):
            return _blocked_revalidation("CREATE_ONCE_TARGET_CONFLICT")
        if (
            current_target.get("exists") is not True
            or current_target.get("preimage_digest") != hashlib.sha256(raw).hexdigest()
        ):
            return _blocked_revalidation("APPLY_TARGET_OBSERVATION_DRIFT")
        if existing != payload:
            return _blocked_revalidation("CREATE_ONCE_TARGET_CONFLICT")
        return {
            "status": "NO_CHANGE", "decision": "NO_CHANGE", "mutation_count": 0,
            "plan_digest": current_plan_digest,
        }
    if current_target != planned_target or current_target.get("exists") is not False:
        return _blocked_revalidation("APPLY_TARGET_OBSERVATION_DRIFT")
    before_write = _target_bytes_observation(target)
    if before_write[0] != "missing":
        return _blocked_revalidation("APPLY_TARGET_OBSERVATION_DRIFT")
    try:
        create_once_writer(target, payload)
    except FileExistsError:
        return _blocked_revalidation("CREATE_ONCE_TARGET_CONFLICT")
    except OSError:
        return _writer_exception_result(
            target,
            before_write,
            blocked_code="WRITE_FAILED_BEFORE_MUTATION",
            partial_code="WRITE_INTERRUPTED_AFTER_MUTATION",
        )
    try:
        if postcheck_reader(target) != payload:
            return {
                "status": "PARTIAL", "decision": "PARTIAL", "mutation_count": 1,
                "reason_codes": ["POSTCHECK_MISMATCH"],
            }
    except (OSError, ValueError):
        return {
            "status": "PARTIAL", "decision": "PARTIAL", "mutation_count": 1,
            "reason_codes": ["POSTCHECK_UNAVAILABLE"],
        }
    return {"status": "APPLIED", "decision": "PASS", "mutation_count": 1, "plan_digest": current_plan_digest}


def recover_cp6_revalidation_receipt(
    target: Path,
    receipt: Cp6RevalidationReceiptV1 | Mapping[str, Any],
    *, attempt_id: str,
) -> dict[str, Any]:
    """仅确认同 attempt 的已存在 receipt；不删除或重写 immutable 历史。"""

    try:
        frozen = receipt if isinstance(receipt, Cp6RevalidationReceiptV1) else freeze_cp6_revalidation_receipt(**receipt)
    except (FrozenCp6EvidenceError, TypeError):
        return _blocked_revalidation("RECOVERY_RECEIPT_INVALID")
    if frozen.attempt_id != attempt_id:
        return _blocked_revalidation("RECOVERY_CROSS_ATTEMPT")
    try:
        existing = _read_json(target)
    except (OSError, ValueError):
        return _blocked_revalidation("RECOVERY_TARGET_MISSING")
    if existing != frozen.as_dict():
        return _blocked_revalidation("RECOVERY_POSTCONDITION_MISMATCH")
    return {"status": "NO_CHANGE", "decision": "NO_CHANGE", "mutation_count": 0, "attempt_id": attempt_id}


def validate_cp6_revalidation_preflight(
    authorization: Cp6RevalidationReceiptV1 | Mapping[str, Any],
    *,
    required_digests: Mapping[str, str],
    p01_event: Mapping[str, Any],
) -> dict[str, Any]:
    """验证 mandatory evidence spine 与 P01 exact-one preregistration 关联。"""

    try:
        auth = authorization if isinstance(authorization, Cp6RevalidationReceiptV1) else freeze_cp6_revalidation_receipt(**authorization)
    except (FrozenCp6EvidenceError, TypeError):
        return _blocked_revalidation("AUTHORIZATION_INVALID")
    if auth.kind != "authorization" or set(required_digests) != (_REVALIDATION_PREFLIGHT_FIELDS - {"p01_event_ref"}):
        return _blocked_revalidation("PREFLIGHT_REQUIRED_SET_INVALID")
    if any(
        not isinstance(value, str) or len(value) != 64 or value.lower() != value
        or any(character not in "0123456789abcdef" for character in value)
        for value in required_digests.values()
    ):
        return _blocked_revalidation("PREFLIGHT_DIGEST_INVALID")
    if set(p01_event) != {
        "logical_ref", "event_bytes", "event_bytes_digest", "current_event_bytes_digest",
    }:
        return _blocked_revalidation("P01_PREREGISTRATION_OBSERVATION_INVALID")
    raw_event = p01_event.get("event_bytes")
    if not isinstance(raw_event, bytes):
        return _blocked_revalidation("P01_PREREGISTRATION_EVENT_BYTES_INVALID")
    try:
        parsed_event = json.loads(raw_event)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _blocked_revalidation("P01_PREREGISTRATION_EVENT_BYTES_INVALID")
    if not isinstance(parsed_event, Mapping):
        return _blocked_revalidation("P01_PREREGISTRATION_EVENT_BYTES_INVALID")
    p01_result = validate_p01_preregistration_exact_one(
        ledger_events=[p01_event],
        expected_identity={
            "story_id": auth.story_id,
            "work_id": auth.work_id,
            "attempt_id": auth.attempt_id,
            "scope_digest": auth.scope_digest,
        },
        current_selection_digest=str(parsed_event.get("selection_digest") or ""),
    )
    if p01_result["decision"] != "READY":
        return _blocked_revalidation("P01_PREREGISTRATION_CORRELATION_INVALID")
    receipt = build_cp6_revalidation_receipt(
        kind="preflight", cr_id=auth.cr_id, story_id=auth.story_id, work_id=auth.work_id,
        attempt_id=auth.attempt_id, release_oid=auth.release_oid, process_oid=auth.process_oid,
        scope_digest=auth.scope_digest,
        payload={
            "authorization_digest": auth.as_dict()["payload_digest"],
            **dict(sorted(required_digests.items())),
            "p01_event_ref": str(p01_event["logical_ref"]),
        },
    )
    return {"status": "READY", "decision": "READY", "mutation_count": 1, "receipt": receipt.as_dict()}


def admit_revalidation_downstream(
    *, consumer: str, expected_digests: Mapping[str, str], current_digests: Mapping[str, str],
) -> dict[str, Any]:
    """下游只接受 exact current digest 集合；不从状态或文件名推断 currentness。"""

    del consumer, expected_digests, current_digests
    return _blocked_revalidation("DOWNSTREAM_UNVALIDATED_CALLER_MAPPING")


def validate_p01_preregistration_exact_one(
    *,
    packet: Mapping[str, Any] | None = None,
    ledger_events: list[Mapping[str, Any]] | None = None,
    expected_identity: Mapping[str, Any] | None = None,
    current_selection_digest: str = "",
    events: list[Mapping[str, Any]] | None = None,
    current_digest: str = "",
) -> dict[str, Any]:
    """从 immutable event observation 验证 P01 exact-one current preregistration。"""

    observed = list(ledger_events if ledger_events is not None else (events or []))
    selection_digest = current_selection_digest or current_digest
    if len(observed) != 1 or not _is_sha256(selection_digest):
        return _blocked_revalidation("P01_PREREGISTRATION_CARDINALITY_INVALID")
    candidate = observed[0]
    if "event_bytes" in candidate:
        if set(candidate) != {
            "logical_ref", "event_bytes", "event_bytes_digest", "current_event_bytes_digest",
        } or not _is_process_logical_ref(candidate.get("logical_ref")):
            return _blocked_revalidation("P01_PREREGISTRATION_OBSERVATION_INVALID")
        raw = candidate.get("event_bytes")
        if not isinstance(raw, bytes):
            return _blocked_revalidation("P01_PREREGISTRATION_EVENT_BYTES_INVALID")
        digest = hashlib.sha256(raw).hexdigest()
        if (
            candidate.get("event_bytes_digest") != digest
            or candidate.get("current_event_bytes_digest") != digest
        ):
            return _blocked_revalidation("P01_PREREGISTRATION_CURRENTNESS_INVALID")
        try:
            event = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _blocked_revalidation("P01_PREREGISTRATION_EVENT_BYTES_INVALID")
    else:
        event = candidate
    if not isinstance(event, Mapping):
        return _blocked_revalidation("P01_PREREGISTRATION_EVIDENCE_INVALID")
    event_packet = event.get("packet")
    selected = event.get("selected_refs")
    if not isinstance(event_packet, Mapping) or not isinstance(selected, list):
        return _blocked_revalidation("P01_PREREGISTRATION_EVIDENCE_INVALID")
    if packet is not None and dict(event_packet) != dict(packet):
        return _blocked_revalidation("P01_PREREGISTRATION_PACKET_MISMATCH")
    try:
        required = read_expansion.select_required_preregistration_refs(event_packet)
    except ValueError:
        return _blocked_revalidation("P01_PREREGISTRATION_SELECTOR_INVALID")
    if (
        tuple(selected) != required
        or str(event.get("selection_digest") or "") != canonical_digest(selected)
        or str(event.get("selection_digest") or "") != selection_digest
    ):
        return _blocked_revalidation("P01_PREREGISTRATION_CURRENTNESS_INVALID")
    identity = dict(expected_identity or {})
    if any(event.get(field) != value for field, value in identity.items()):
        return _blocked_revalidation("P01_PREREGISTRATION_IDENTITY_MISMATCH")
    if (
        event.get("stage") != "CP6"
        or event.get("requested_ref") != required[0]
        or event.get("preregistered_by") != "host"
        or event.get("reason") != "summary_insufficient"
        or event.get("reason_evidence") != {"missing_slots": ["full_lld_body"]}
        or not _is_sha256(event.get("bytes_digest"))
    ):
        return _blocked_revalidation("P01_PREREGISTRATION_EVIDENCE_INVALID")
    return {
        "status": "READY",
        "decision": "READY",
        "mutation_count": 0,
        "logical_ref": str(candidate.get("logical_ref") or ""),
        "selection_digest": selection_digest,
    }


def validate_cp6_revalidation_spine(
    *, authorization: Mapping[str, Any], observations: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """从八个 immutable bytes observations 验证 mandatory evidence spine。"""

    roles = (
        ("packet", "context-packet"), ("read_log", "read-expansion-log"),
        ("return", "story-return"), ("evidence", "evidence-index"),
        ("result", "cp6-result"), ("checkpoint", "checkpoint-result"),
        ("plan", "development-plan"), ("downstream", "downstream-receipt-set"),
    )
    if len(observations) != len(roles):
        return _blocked_revalidation("REVALIDATION_SPINE_CARDINALITY_INVALID")
    identity = {
        "story_id": authorization.get("story_id"),
        "work_id": authorization.get("work_id"),
        "attempt_id": authorization.get("attempt_id"),
        "authorization_digest": authorization.get("payload_digest"),
    }
    if not all(isinstance(value, str) and value for value in identity.values()):
        return _blocked_revalidation("REVALIDATION_SPINE_AUTHORIZATION_INVALID")
    previous = ""
    seen_refs: set[str] = set()
    outer_fields = {
        "role", "kind", "logical_ref", "bytes", "bytes_digest", "story_id",
        "work_id", "attempt_id", "authorization_digest", "previous_digest",
    }
    inner_fields = {
        "schema_version", "role", "kind", "story_id", "work_id", "attempt_id",
        "authorization_digest", "previous_digest",
    }
    for observation, (role, kind) in zip(observations, roles, strict=True):
        if set(observation) != outer_fields:
            return _blocked_revalidation("REVALIDATION_SPINE_OBSERVATION_SHAPE_INVALID")
        ref = observation.get("logical_ref")
        raw = observation.get("bytes")
        if not _is_process_logical_ref(ref) or ref in seen_refs or not isinstance(raw, bytes):
            return _blocked_revalidation("REVALIDATION_SPINE_OBSERVATION_INVALID")
        seen_refs.add(str(ref))
        digest = hashlib.sha256(raw).hexdigest()
        if observation.get("bytes_digest") != digest:
            return _blocked_revalidation("REVALIDATION_SPINE_BYTES_DIGEST_MISMATCH")
        try:
            inner = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _blocked_revalidation("REVALIDATION_SPINE_BYTES_INVALID")
        expected = {
            "schema_version": 1, "role": role, "kind": kind,
            **identity, "previous_digest": previous,
        }
        if not isinstance(inner, Mapping) or set(inner) != inner_fields or dict(inner) != expected:
            return _blocked_revalidation("REVALIDATION_SPINE_INNER_BINDING_MISMATCH")
        expected_outer = {key: value for key, value in expected.items() if key != "schema_version"}
        if any(observation.get(key) != value for key, value in expected_outer.items()):
            return _blocked_revalidation("REVALIDATION_SPINE_OUTER_BINDING_MISMATCH")
        previous = digest
    return {"status": "READY", "decision": "READY", "mutation_count": 0}


def validate_cp6_revalidation_input_contract(
    *, input_spec: Mapping[str, Any], resolve: Any, exists: Any, read: Any,
) -> dict[str, Any]:
    """按 consumer requirement 执行 resolve→exists→read 的精确 I/O 契约。"""

    try:
        requirement = preregistration.parse_consumer_requirement(
            input_spec.get("consumer_requirement")
        )
    except preregistration.PreregistrationSemanticsError:
        return _blocked_revalidation(
            "REVALIDATION_CONSUMER_REQUIREMENT_INVALID"
        ) | {"read_count": 0}
    if not preregistration.requirement_evaluates_target_io(requirement):
        return {"status": "NOT_REQUIRED", "decision": "NOT_REQUIRED", "mutation_count": 0, "read_count": 0}
    ref = input_spec.get("logical_ref")
    expected_digest = input_spec.get("expected_bytes_digest")
    if not _is_process_logical_ref(ref) or not _is_sha256(expected_digest):
        return _blocked_revalidation("REVALIDATION_INPUT_SPEC_INVALID") | {"read_count": 0}
    try:
        route = resolve(ref)
    except Exception:
        return _blocked_revalidation("REVALIDATION_INPUT_ROUTE_UNAVAILABLE") | {"read_count": 0}
    if not isinstance(route, Mapping) or route.get("status") != "ready":
        return _blocked_revalidation("REVALIDATION_INPUT_ROUTE_INVALID") | {"read_count": 0}
    expected_lineage = input_spec.get("expected_lineage")
    if isinstance(expected_lineage, Mapping) and any(
        route.get(field) != value for field, value in expected_lineage.items()
    ):
        return _blocked_revalidation("REVALIDATION_INPUT_LINEAGE_MISMATCH") | {"read_count": 0}
    try:
        if not exists(ref):
            return _blocked_revalidation("REVALIDATION_INPUT_TARGET_MISSING") | {"read_count": 0}
        raw = read(ref)
    except Exception:
        return _blocked_revalidation("REVALIDATION_INPUT_READ_UNAVAILABLE") | {"read_count": 0}
    if not isinstance(raw, bytes) or hashlib.sha256(raw).hexdigest() != expected_digest:
        return _blocked_revalidation("REVALIDATION_INPUT_DIGEST_MISMATCH") | {"read_count": 1}
    return {"status": "READY", "decision": "READY", "mutation_count": 0, "read_count": 1}


def recover_missing_cp6_revalidation_completion(
    *,
    authorization: Cp6RevalidationReceiptV1 | Mapping[str, Any],
    preflight: Cp6RevalidationReceiptV1 | Mapping[str, Any],
    projection: Mapping[str, Any],
    target_observation: Mapping[str, Any],
    create_once_writer: Any,
    postcheck_reader: Any,
) -> dict[str, Any]:
    """仅为同一已关联 attempt create-once 恢复缺失 completion。"""

    try:
        auth = authorization if isinstance(authorization, Cp6RevalidationReceiptV1) else freeze_cp6_revalidation_receipt(**authorization)
        pre = preflight if isinstance(preflight, Cp6RevalidationReceiptV1) else freeze_cp6_revalidation_receipt(**preflight)
    except (FrozenCp6EvidenceError, TypeError):
        return _blocked_revalidation("COMPLETION_RECOVERY_RECEIPT_INVALID")
    auth_digest = auth.as_dict()["payload_digest"]
    pre_digest = pre.as_dict()["payload_digest"]
    if (
        auth.kind != "authorization"
        or pre.kind != "preflight"
        or (auth.cr_id, auth.story_id, auth.work_id, auth.attempt_id)
        != (pre.cr_id, pre.story_id, pre.work_id, pre.attempt_id)
        or pre.payload.get("authorization_digest") != auth_digest
    ):
        return _blocked_revalidation("COMPLETION_RECOVERY_CROSS_ATTEMPT")
    raw = projection.get("bytes")
    ref = projection.get("logical_ref")
    if not isinstance(raw, bytes) or not _is_process_logical_ref(ref):
        return _blocked_revalidation("COMPLETION_RECOVERY_PROJECTION_INVALID")
    projection_digest = hashlib.sha256(raw).hexdigest()
    if projection.get("bytes_digest") != projection_digest:
        return _blocked_revalidation("COMPLETION_RECOVERY_PROJECTION_DIGEST_MISMATCH")
    try:
        inner = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _blocked_revalidation("COMPLETION_RECOVERY_PROJECTION_INVALID")
    inner_fields = {
        "schema_version", "kind", "cr_id", "story_id", "work_id", "attempt_id",
        "preflight_digest", "phase",
    }
    expected_inner = {
        "schema_version": 1, "kind": "projection", "cr_id": auth.cr_id,
        "story_id": auth.story_id, "work_id": auth.work_id, "attempt_id": auth.attempt_id,
        "preflight_digest": pre_digest, "phase": "COMPLETE",
    }
    if not isinstance(inner, Mapping) or set(inner) != inner_fields or dict(inner) != expected_inner:
        return _blocked_revalidation("COMPLETION_RECOVERY_PROJECTION_LINEAGE_MISMATCH")
    if any(projection.get(field) != value for field, value in expected_inner.items()):
        return _blocked_revalidation("COMPLETION_RECOVERY_PROJECTION_OUTER_MISMATCH")
    if set(target_observation) != {"logical_ref", "path", "exists", "preimage_digest"}:
        return _blocked_revalidation("COMPLETION_RECOVERY_TARGET_INVALID")
    target = target_observation.get("path")
    if not isinstance(target, Path) or not _is_process_logical_ref(target_observation.get("logical_ref")):
        return _blocked_revalidation("COMPLETION_RECOVERY_TARGET_INVALID")
    completion = build_cp6_revalidation_receipt(
        kind="completion", cr_id=auth.cr_id, story_id=auth.story_id, work_id=auth.work_id,
        attempt_id=auth.attempt_id, release_oid=auth.release_oid, process_oid=auth.process_oid,
        scope_digest=auth.scope_digest,
        payload={
            "authorization_digest": auth_digest,
            "preflight_digest": pre_digest,
            "projection_digest": projection_digest,
            "downstream_set_digest": auth.payload["downstream_set_digest"],
        },
    )
    payload = completion.as_dict()
    if target.exists():
        try:
            raw_target = target.read_bytes()
            existing = json.loads(raw_target)
        except (OSError, ValueError):
            return _blocked_revalidation("COMPLETION_RECOVERY_TARGET_CONFLICT")
        if (
            target_observation.get("exists") is not True
            or target_observation.get("preimage_digest") != hashlib.sha256(raw_target).hexdigest()
            or existing != payload
        ):
            return _blocked_revalidation("COMPLETION_RECOVERY_TARGET_CONFLICT")
        return {"status": "NO_CHANGE", "decision": "NO_CHANGE", "mutation_count": 0}
    if target_observation.get("exists") is not False or target_observation.get("preimage_digest") != "":
        return _blocked_revalidation("COMPLETION_RECOVERY_TARGET_DRIFT")
    before_write = _target_bytes_observation(target)
    if before_write[0] != "missing":
        return _blocked_revalidation("COMPLETION_RECOVERY_TARGET_DRIFT")
    try:
        create_once_writer(target, payload)
    except FileExistsError:
        return _blocked_revalidation("COMPLETION_RECOVERY_TARGET_CONFLICT")
    except OSError:
        return _writer_exception_result(
            target,
            before_write,
            blocked_code="COMPLETION_RECOVERY_WRITE_FAILED",
            partial_code="COMPLETION_RECOVERY_WRITE_INTERRUPTED_AFTER_MUTATION",
        )
    try:
        if postcheck_reader(target) != payload:
            return {"status": "PARTIAL", "decision": "PARTIAL", "mutation_count": 1}
    except (OSError, ValueError):
        return {"status": "PARTIAL", "decision": "PARTIAL", "mutation_count": 1}
    return {"status": "RECOVERED", "decision": "PASS", "mutation_count": 1, "receipt": payload}


def admit_revalidation_downstream_receipts(
    *,
    consumer: str,
    receipt_refs: list[str],
    plan_observation: Mapping[str, Any],
    current_attempt: Mapping[str, Any],
    expected_authorization_digest: str,
    authorized_downstream_set: list[Mapping[str, Any]],
    resolve_receipt: Any,
    select_current: Any,
) -> dict[str, Any]:
    """从 plan-bound policy、receipt bytes 与 current selector 做下游准入。"""

    if set(plan_observation) != {"authorization_digest", "bound_policy", "plan_digest"}:
        return _blocked_revalidation("DOWNSTREAM_PLAN_INVALID")
    plan_payload = {key: value for key, value in plan_observation.items() if key != "plan_digest"}
    policy = plan_observation.get("bound_policy")
    if not isinstance(policy, Mapping) or set(policy) != {"schema_version", "consumers", "policy_digest"}:
        return _blocked_revalidation("DOWNSTREAM_POLICY_INVALID")
    if policy.get("schema_version") != 1:
        return _blocked_revalidation("DOWNSTREAM_POLICY_VERSION_INVALID")
    if not _is_sha256(plan_observation.get("authorization_digest")):
        return _blocked_revalidation("DOWNSTREAM_AUTHORIZATION_DIGEST_INVALID")
    if (
        not _is_sha256(expected_authorization_digest)
        or plan_observation.get("authorization_digest")
        != expected_authorization_digest
    ):
        return _blocked_revalidation("DOWNSTREAM_AUTHORIZATION_DIGEST_MISMATCH")
    policy_payload = {"schema_version": policy["schema_version"], "consumers": policy["consumers"]}
    if policy.get("policy_digest") != canonical_digest(policy_payload):
        return _blocked_revalidation("DOWNSTREAM_POLICY_DIGEST_MISMATCH")
    if plan_observation.get("plan_digest") != canonical_digest(plan_payload):
        return _blocked_revalidation("DOWNSTREAM_PLAN_DIGEST_MISMATCH")
    consumers = policy.get("consumers")
    if not isinstance(consumers, Mapping) or not consumers:
        return _blocked_revalidation("DOWNSTREAM_POLICY_CONSUMERS_INVALID")
    for declared_consumer, declared_producers in consumers.items():
        if (
            not isinstance(declared_consumer, str)
            or not declared_consumer
            or not isinstance(declared_producers, list)
            or not declared_producers
            or any(not isinstance(producer, str) or not producer for producer in declared_producers)
            or len(set(declared_producers)) != len(declared_producers)
        ):
            return _blocked_revalidation("DOWNSTREAM_POLICY_CONSUMERS_INVALID")
    if consumer not in consumers:
        return _blocked_revalidation("DOWNSTREAM_CONSUMER_UNKNOWN")
    expected_producers = list(consumers[consumer])
    if not isinstance(authorized_downstream_set, list) or any(
        not isinstance(item, Mapping)
        or set(item) != {"producer", "receipt_digest", "attempt_id"}
        or not isinstance(item.get("producer"), str)
        or not item.get("producer")
        or not _is_sha256(item.get("receipt_digest"))
        or item.get("attempt_id") != current_attempt.get("attempt_id")
        for item in authorized_downstream_set
    ):
        return _blocked_revalidation("DOWNSTREAM_AUTHORIZED_SET_INVALID")
    if expected_producers != [item["producer"] for item in authorized_downstream_set]:
        return _blocked_revalidation("DOWNSTREAM_AUTHORIZED_SET_MISMATCH")
    if len(receipt_refs) < len(expected_producers):
        return _blocked_revalidation("DOWNSTREAM_RECEIPT_SET_MISSING")
    if len(receipt_refs) > len(expected_producers):
        return _blocked_revalidation("DOWNSTREAM_RECEIPT_SET_EXTRA")
    if (
        set(current_attempt) != {"story_id", "attempt_id", "plan_digest"}
        or not isinstance(current_attempt.get("story_id"), str)
        or not current_attempt.get("story_id")
        or not isinstance(current_attempt.get("attempt_id"), str)
        or not current_attempt.get("attempt_id")
        or not _is_sha256(current_attempt.get("plan_digest"))
        or current_attempt.get("plan_digest") != plan_observation.get("plan_digest")
    ):
        return _blocked_revalidation("DOWNSTREAM_ATTEMPT_INVALID")
    parsed: list[dict[str, Any]] = []
    raw_receipts: list[bytes] = []
    for ref in receipt_refs:
        if not _is_process_logical_ref(ref):
            return _blocked_revalidation("DOWNSTREAM_RECEIPT_REF_INVALID")
        try:
            raw_receipt = resolve_receipt(ref)
            payload = json.loads(raw_receipt)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError):
            return _blocked_revalidation("DOWNSTREAM_RECEIPT_BYTES_INVALID")
        if not isinstance(payload, dict) or set(payload) != {
            "schema_version", "producer", "consumer", "story_id", "attempt_id",
        } or payload.get("schema_version") != 1:
            return _blocked_revalidation("DOWNSTREAM_RECEIPT_SHAPE_INVALID")
        parsed.append(payload)
        raw_receipts.append(raw_receipt)
    actual_producers = [payload["producer"] for payload in parsed]
    if actual_producers != expected_producers:
        if sorted(actual_producers) == sorted(expected_producers):
            return _blocked_revalidation("DOWNSTREAM_RECEIPT_ORDER_MISMATCH")
        return _blocked_revalidation("DOWNSTREAM_RECEIPT_PRODUCER_MISMATCH")
    if any(
        hashlib.sha256(raw).hexdigest() != authorized["receipt_digest"]
        for raw, authorized in zip(
            raw_receipts,
            authorized_downstream_set,
            strict=True,
        )
    ):
        return _blocked_revalidation("DOWNSTREAM_RECEIPT_DIGEST_MISMATCH")
    for ref, producer, payload in zip(receipt_refs, expected_producers, parsed, strict=True):
        if payload.get("story_id") != current_attempt.get("story_id"):
            return _blocked_revalidation("DOWNSTREAM_RECEIPT_STORY_MISMATCH")
        if payload.get("consumer") != consumer:
            return _blocked_revalidation("DOWNSTREAM_RECEIPT_CONSUMER_MISMATCH")
        if payload.get("attempt_id") != current_attempt.get("attempt_id"):
            return _blocked_revalidation("DOWNSTREAM_RECEIPT_ATTEMPT_MISMATCH")
        try:
            selection = select_current(producer, consumer)
        except Exception:
            return _blocked_revalidation("DOWNSTREAM_CURRENT_SELECTOR_UNAVAILABLE")
        if (
            not isinstance(selection, Mapping)
            or set(selection) != {"current_ref", "superseded_by"}
            or not _is_process_logical_ref(selection.get("current_ref"))
            or (
                selection.get("superseded_by") != ""
                and not _is_process_logical_ref(selection.get("superseded_by"))
            )
        ):
            return _blocked_revalidation("DOWNSTREAM_CURRENT_SELECTOR_INVALID")
        if selection.get("superseded_by"):
            return _blocked_revalidation("DOWNSTREAM_RECEIPT_SUPERSEDED")
        if selection.get("current_ref") != ref:
            return _blocked_revalidation("DOWNSTREAM_RECEIPT_NOT_CURRENT")
    return {"status": "READY", "decision": "READY", "mutation_count": 0, "consumer": consumer}


def _is_sha256(value: object) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{64}", str(value or "")))


def _is_process_logical_ref(value: object) -> bool:
    result = str(value or "")
    return (
        result.startswith("process/")
        and "\\" not in result
        and all(segment not in {"", ".", ".."} for segment in result.split("/"))
    )


def _operation_blocked(action: str, code: str) -> dict[str, Any]:
    return _blocked_revalidation(code) | {
        "action": action,
        "exit_code": 2,
        "postcondition": "UNVERIFIED",
    }


def _valid_mutation_count(value: Any) -> bool:
    return type(value) is int and value >= 0


def _service_state(result: Mapping[str, Any]) -> tuple[str, bool]:
    decision = result.get("decision")
    status = result.get("status")
    if decision is not None and not isinstance(decision, str):
        return "", False
    if status is not None and not isinstance(status, str):
        return "", False
    normalized_decision = str(decision or "").upper()
    normalized_status = str(status or "").upper()
    if normalized_decision and normalized_status and normalized_decision != normalized_status:
        return "", False
    return normalized_decision or normalized_status, True


def _parse_typed_service_result(
    action: str,
    name: str,
    result: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Total closed-world parser；返回 parsed data 或 typed operation failure。"""

    if not isinstance(result, Mapping) or not result:
        return None, _operation_blocked(
            action, f"REVALIDATION_{name.upper()}_RESULT_INVALID"
        )
    payload = dict(result)
    state, state_valid = _service_state(payload)
    if not state_valid:
        return None, _operation_blocked(
            action, f"REVALIDATION_{name.upper()}_RESULT_CONFLICT"
        )
    if state in {"BLOCKED", "PARTIAL"}:
        allowed_fields = {
            "decision", "status", "mutation_count", "reason_codes", "exit_code",
        }
        count = payload.get("mutation_count")
        reason_codes = payload.get("reason_codes")
        expected_count = 1 if state == "PARTIAL" and action in {
            "apply", "recover", "completion",
        } else 0
        if (
            not set(payload).issubset(allowed_fields)
            or "mutation_count" not in payload
            or not _valid_mutation_count(count)
            or count != expected_count
            or not isinstance(reason_codes, list)
            or not reason_codes
            or any(not isinstance(code, str) or not code for code in reason_codes)
            or ("exit_code" in payload and payload["exit_code"] != 2)
        ):
            return None, _operation_blocked(
                action, f"REVALIDATION_{name.upper()}_RESULT_INVALID"
            )
        return None, {
            "action": action,
            "status": state,
            "decision": state,
            "mutation_count": count,
            "postcondition": "UNVERIFIED",
            "reason_codes": list(reason_codes),
            "exit_code": 2,
        }
    if name == "resolve":
        if not state:
            try:
                receipt = freeze_cp6_revalidation_receipt(**payload).as_dict()
            except (FrozenCp6EvidenceError, TypeError):
                return None, _operation_blocked(
                    action, "REVALIDATION_RESOLVE_RESULT_INVALID"
                )
            return {"payload": receipt}, None
        if (
            set(payload) != {"status", "mutation_count", "payload"}
            or state != "READY"
            or not _valid_mutation_count(payload.get("mutation_count"))
            or payload["mutation_count"] != 0
            or not isinstance(payload.get("payload"), Mapping)
        ):
            return None, _operation_blocked(
                action, "REVALIDATION_RESOLVE_RESULT_INVALID"
            )
        try:
            receipt = freeze_cp6_revalidation_receipt(
                **dict(payload["payload"])
            ).as_dict()
        except (FrozenCp6EvidenceError, TypeError):
            return None, _operation_blocked(
                action, "REVALIDATION_RESOLVE_RESULT_INVALID"
            )
        return {"payload": receipt}, None
    if name == "observe_current":
        if (
            set(payload) != {"status", "mutation_count", "observation"}
            or state != "CURRENT"
            or not _valid_mutation_count(payload.get("mutation_count"))
            or payload["mutation_count"] != 0
            or not isinstance(payload.get("observation"), Mapping)
            or not payload["observation"]
        ):
            return None, _operation_blocked(
                action, "REVALIDATION_OBSERVE_CURRENT_RESULT_INVALID"
            )
        return {"observation": dict(payload["observation"])}, None
    if name == "create_once_writer":
        if (
            set(payload) != {"status", "mutation_count"}
            or state != "APPLIED"
            or not _valid_mutation_count(payload.get("mutation_count"))
            or payload["mutation_count"] != 1
        ):
            return None, _operation_blocked(
                action, "REVALIDATION_CREATE_ONCE_WRITER_RESULT_INVALID"
            )
        return {}, None
    if name == "postcheck_reader":
        if not state:
            try:
                receipt = freeze_cp6_revalidation_receipt(**payload).as_dict()
            except (FrozenCp6EvidenceError, TypeError):
                return None, _operation_blocked(
                    action, "REVALIDATION_POSTCHECK_READER_RESULT_INVALID"
                )
            return {"payload": receipt}, None
        if (
            set(payload) != {"status", "mutation_count", "payload"}
            or state != "VERIFIED"
            or not _valid_mutation_count(payload.get("mutation_count"))
            or payload["mutation_count"] != 0
            or not isinstance(payload.get("payload"), Mapping)
        ):
            return None, _operation_blocked(
                action, "REVALIDATION_POSTCHECK_READER_RESULT_INVALID"
            )
        try:
            receipt = freeze_cp6_revalidation_receipt(
                **dict(payload["payload"])
            ).as_dict()
        except (FrozenCp6EvidenceError, TypeError):
            return None, _operation_blocked(
                action, "REVALIDATION_POSTCHECK_READER_RESULT_INVALID"
            )
        return {"payload": receipt}, None
    if name == "projector":
        required = {"decision", "phase", "complete"}
        allowed = required | {"next_phase", "formal_story_status", "reason_codes"}
        if (
            not required.issubset(payload)
            or not set(payload).issubset(allowed)
            or state != "READY"
            or payload.get("phase") != "COMPLETE"
            or payload.get("complete") is not True
        ):
            return None, _operation_blocked(
                action, "REVALIDATION_PROJECTOR_INCOMPLETE"
            )
        return {"projection": payload}, None
    return None, _operation_blocked(
        action, f"REVALIDATION_{name.upper()}_RESULT_INVALID"
    )


def run_cp6_revalidation_operation(
    request: Mapping[str, Any], services: Mapping[str, Any],
) -> dict[str, Any]:
    """按 action-specific service graph 执行 generic child operation。"""

    action = str(request.get("action") or "")
    traces = {
        "plan": ("resolve", "observe_current"),
        "apply": ("resolve", "observe_current", "create_once_writer", "postcheck_reader"),
        "replay": ("resolve", "observe_current", "postcheck_reader"),
        "inspect": ("resolve", "postcheck_reader"),
        "recover": ("resolve", "observe_current", "create_once_writer", "postcheck_reader"),
        "completion": (
            "resolve", "observe_current", "projector", "create_once_writer", "postcheck_reader",
        ),
    }
    if action not in traces:
        return _blocked_revalidation("REVALIDATION_ACTION_INVALID") | {
            "action": action, "exit_code": 2, "postcondition": "UNVERIFIED",
        }
    required = set(traces[action])
    if any(name not in services or not callable(services[name]) for name in required):
        return _blocked_revalidation("REVALIDATION_SERVICE_MISSING") | {
            "action": action, "exit_code": 2, "postcondition": "UNVERIFIED",
        }
    target = request.get("target")
    authorization = request.get("authorization")
    last_result: Any = None
    resolved_payload: Mapping[str, Any] | None = None
    writer_preimage: tuple[str, bytes] | None = None
    for name in traces[action]:
        service = services[name]
        try:
            if name == "resolve":
                last_result = service(authorization)
            elif name == "observe_current":
                last_result = service(request)
            elif name == "projector":
                last_result = service(
                    request.get("event_observations") or [],
                    expected_identity=request.get("expected_identity") or {},
                    formal_story_status=str(request.get("formal_story_status") or "ready-for-verification"),
                )
            elif name == "create_once_writer":
                if not isinstance(target, Path) or resolved_payload is None:
                    return _operation_blocked(action, "REVALIDATION_WRITE_INPUT_INVALID")
                writer_preimage = _target_bytes_observation(target)
                if writer_preimage[0] == "unknown":
                    return _operation_blocked(action, "REVALIDATION_TARGET_PREIMAGE_UNAVAILABLE")
                last_result = service(target, dict(resolved_payload))
            else:
                last_result = service(target)
        except FileExistsError:
            if name == "create_once_writer":
                return _operation_blocked(
                    action, "REVALIDATION_CREATE_ONCE_TARGET_CONFLICT"
                )
            return _operation_blocked(action, f"REVALIDATION_{name.upper()}_FAILED")
        except Exception:
            if name == "create_once_writer" and isinstance(target, Path) and writer_preimage is not None:
                classified = _writer_exception_result(
                    target,
                    writer_preimage,
                    blocked_code="REVALIDATION_CREATE_ONCE_WRITER_FAILED",
                    partial_code="REVALIDATION_CREATE_ONCE_WRITER_PARTIAL",
                )
                classified.update(
                    {"action": action, "exit_code": 2, "postcondition": "UNVERIFIED"}
                )
                return classified
            return _operation_blocked(action, f"REVALIDATION_{name.upper()}_FAILED")
        parsed_result, failure = _parse_typed_service_result(action, name, last_result)
        if failure is not None:
            if (
                name == "create_once_writer"
                and failure["decision"] == "BLOCKED"
                and isinstance(target, Path)
                and writer_preimage is not None
                and _target_bytes_observation(target) != writer_preimage
            ):
                return {
                    "action": action,
                    "status": "PARTIAL",
                    "decision": "PARTIAL",
                    "mutation_count": 1,
                    "postcondition": "UNVERIFIED",
                    "reason_codes": ["REVALIDATION_CREATE_ONCE_WRITER_PARTIAL"],
                    "exit_code": 2,
                }
            if name == "postcheck_reader" and writer_preimage is not None:
                return {
                    "action": action,
                    "status": "PARTIAL",
                    "decision": "PARTIAL",
                    "mutation_count": 1,
                    "postcondition": "UNVERIFIED",
                    "reason_codes": ["REVALIDATION_POSTCHECK_INVALID_AFTER_MUTATION"],
                    "exit_code": 2,
                }
            return failure
        if parsed_result is None:
            return _operation_blocked(
                action, f"REVALIDATION_{name.upper()}_RESULT_INVALID"
            )
        if name == "resolve":
            resolved_payload = dict(parsed_result["payload"])
        if name == "postcheck_reader":
            if (
                resolved_payload is None
                or dict(parsed_result["payload"]) != dict(resolved_payload)
            ):
                if writer_preimage is not None:
                    return {
                        "action": action,
                        "status": "PARTIAL",
                        "decision": "PARTIAL",
                        "mutation_count": 1,
                        "postcondition": "UNVERIFIED",
                        "reason_codes": ["REVALIDATION_POSTCHECK_MISMATCH"],
                        "exit_code": 2,
                    }
                return _operation_blocked(action, "REVALIDATION_POSTCHECK_MISMATCH")
    statuses = {
        "plan": "READY", "apply": "APPLIED", "replay": "NO_CHANGE",
        "inspect": "READY", "recover": "RECOVERED", "completion": "COMPLETE",
    }
    result = {
        "action": action,
        "status": statuses[action],
        "decision": "PASS",
        "mutation_count": 1 if action in {"apply", "recover", "completion"} else 0,
        "postcondition": "VERIFIED",
        "exit_code": 0,
    }
    if action == "completion" and isinstance(last_result, Mapping):
        result["phase"] = "COMPLETE"
    return result


def _read_process_json(project_root: Path, logical_ref: object) -> dict[str, Any]:
    if not _is_process_logical_ref(logical_ref):
        raise ValueError("revalidation input must be a canonical process logical ref")
    payload = _read_json(
        _resolve_runtime_path(project_root, Path(str(logical_ref)))
    )
    if not isinstance(payload, dict):
        raise ValueError("revalidation JSON input must be an object")
    return payload


def _read_process_bytes(project_root: Path, logical_ref: object) -> bytes:
    if not _is_process_logical_ref(logical_ref):
        raise ValueError("revalidation input must be a canonical process logical ref")
    return _resolve_runtime_path(project_root, Path(str(logical_ref))).read_bytes()


def _current_target_observation(
    project_root: Path,
    logical_ref: str,
) -> tuple[Path, dict[str, Any]]:
    if not _is_process_logical_ref(logical_ref):
        raise ValueError("target must be a canonical process logical ref")
    target = _resolve_runtime_path(project_root, Path(logical_ref))
    state = _target_bytes_observation(target)
    if state[0] == "unknown" or state[0] == "non-file":
        raise ValueError("target preimage is unavailable or is not a regular file")
    return target, {
        "logical_ref": logical_ref,
        "exists": state[0] == "file",
        "preimage_digest": hashlib.sha256(state[1]).hexdigest()
        if state[0] == "file"
        else "",
    }


_REVALIDATION_ID_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def _revalidation_namespace(receipt: Cp6RevalidationReceiptV1) -> str:
    """返回由 Work/attempt identity 唯一决定的 Work-owned namespace。"""

    for value in (receipt.work_id, receipt.attempt_id):
        if _REVALIDATION_ID_SEGMENT.fullmatch(value) is None:
            raise ValueError("revalidation identity is not safe for a logical ref")
    return f"process/works/{receipt.work_id}/revalidation/{receipt.attempt_id}"


def _expected_revalidation_target_ref(
    receipt: Cp6RevalidationReceiptV1,
    *,
    action: str,
) -> str:
    kind_by_action = {
        "plan": "authorization",
        "apply": "authorization",
        "replay": "authorization",
        "inspect": "authorization",
        "recover": "completion",
        "completion": "completion",
    }
    if action not in kind_by_action:
        raise ValueError("revalidation action has no target capability")
    return (
        f"{_revalidation_namespace(receipt)}/receipts/"
        f"{kind_by_action[action]}.json"
    )


def _expected_revalidation_input_ref(
    receipt: Cp6RevalidationReceiptV1,
    *,
    name: str,
) -> str:
    filenames = {
        "downstream_policy": "CURRENT-DOWNSTREAM-POLICY.json",
        "admission_plan": "DOWNSTREAM-ADMISSION-PLAN.json",
        "current_selections": "CURRENT-DOWNSTREAM-SELECTIONS.json",
    }
    if name not in filenames:
        raise ValueError("unknown revalidation canonical input")
    return f"{_revalidation_namespace(receipt)}/{filenames[name]}"


def _git_head(repository: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "--verify", "HEAD"],
        text=True,
        capture_output=True,
        check=False,
    )
    oid = completed.stdout.strip()
    if completed.returncode != 0 or re.fullmatch(r"[0-9a-f]{40}", oid) is None:
        raise ValueError("current Git HEAD is unavailable")
    return oid


def _current_revalidation_source(
    project_root: Path,
    receipt: Cp6RevalidationReceiptV1,
) -> dict[str, Any]:
    """从 live Git HEAD 与 receipt 指向的 canonical Work 观察 source/scope。"""

    expected_work_ref = f"process/works/{receipt.work_id}/WORK.yaml"
    if receipt.payload.get("work_authorization_ref") != expected_work_ref:
        raise ValueError("authorization Work ref does not match its identity")
    work_path = _resolve_runtime_path(project_root, Path(expected_work_ref))
    work = load_yaml_object(work_path)
    base_oids = work.get("base_oids")
    release_oid = _git_head(project_root)
    process_oid = _git_head(work_path.parent)
    observed = {
        "release_oid": release_oid,
        "process_oid": process_oid,
        "scope_digest": work.get("scope_digest"),
    }
    expected = {
        "release_oid": receipt.release_oid,
        "process_oid": receipt.process_oid,
        "scope_digest": receipt.scope_digest,
    }
    if (
        work.get("work_id") != receipt.work_id
        or not isinstance(base_oids, dict)
        or set(base_oids) != {"release", "process"}
        or base_oids != {"release": release_oid, "process": process_oid}
        or observed != expected
    ):
        raise ValueError("authorization is not bound to current source/Work truth")
    return observed


_REVALIDATION_AUTHORITY_FIELDS = frozenset(
    {
        "schema_version",
        "story_id",
        "attempt_id",
        "authorization_ref",
        "authorization_bytes_digest",
        "authorization_payload_digest",
        "allowed_target_kinds",
        "lineage",
        "inputs",
    }
)
_REVALIDATION_AUTHORITY_LINEAGE_FIELDS = frozenset(
    {
        "previous_cp6_ref",
        "previous_cp6_bytes_digest",
        "superseding_cp5_ref",
        "superseding_cp5_bytes_digest",
        "approval_ref",
        "approval_bytes_digest",
    }
)
_REVALIDATION_AUTHORITY_INPUT_FIELDS = frozenset(
    {
        "downstream_policy_ref",
        "downstream_policy_bytes_digest",
        "admission_plan_ref",
        "admission_plan_bytes_digest",
        "current_selections_ref",
        "current_selections_bytes_digest",
    }
)


def _authorized_revalidation_input_bytes(
    project_root: Path,
    receipt: Cp6RevalidationReceiptV1,
    authority: Mapping[str, Any],
    *,
    name: str,
    logical_ref: object | None = None,
) -> bytes:
    inputs = authority.get("inputs")
    if not isinstance(inputs, Mapping):
        raise ValueError("revalidation authority inputs are unavailable")
    expected_ref = _expected_revalidation_input_ref(receipt, name=name)
    authority_ref = inputs.get(f"{name}_ref")
    selected_ref = expected_ref if logical_ref is None else str(logical_ref or "")
    if authority_ref != expected_ref or selected_ref != expected_ref:
        raise ValueError("revalidation input ref is not owner-authorized")
    raw = _read_process_bytes(project_root, expected_ref)
    if hashlib.sha256(raw).hexdigest() != inputs.get(f"{name}_bytes_digest"):
        raise ValueError("revalidation input bytes are not owner-authorized")
    return raw


def _current_revalidation_authority(
    project_root: Path,
    receipt: Cp6RevalidationReceiptV1,
    *,
    authorization_ref: str,
    authorization_bytes: bytes,
    action: str,
) -> dict[str, Any]:
    """从 canonical Work 读取 owner-issued attempt/capability authority。"""

    work_ref = f"process/works/{receipt.work_id}/WORK.yaml"
    work = load_yaml_object(_resolve_runtime_path(project_root, Path(work_ref)))
    authority = work.get("revalidation_authority")
    if not isinstance(authority, dict) or set(authority) != _REVALIDATION_AUTHORITY_FIELDS:
        raise ValueError("Work revalidation authority schema is not closed")
    allowed = authority.get("allowed_target_kinds")
    target_kind = {
        "plan": "authorization",
        "apply": "authorization",
        "replay": "authorization",
        "inspect": "authorization",
        "recover": "completion",
        "completion": "completion",
    }.get(action)
    if (
        authority.get("schema_version") != 1
        or authority.get("story_id") != receipt.story_id
        or authority.get("attempt_id") != receipt.attempt_id
        or authority.get("authorization_ref") != authorization_ref
        or authority.get("authorization_bytes_digest")
        != hashlib.sha256(authorization_bytes).hexdigest()
        or authority.get("authorization_payload_digest")
        != receipt.as_dict()["payload_digest"]
        or not isinstance(allowed, list)
        or allowed != ["authorization", "completion"]
        or target_kind not in allowed
    ):
        raise ValueError("authorization is not issued by the Work owner")
    lineage = authority.get("lineage")
    if not isinstance(lineage, dict) or set(lineage) != _REVALIDATION_AUTHORITY_LINEAGE_FIELDS:
        raise ValueError("revalidation authority lineage schema is not closed")
    lineage_contract = (
        ("previous_cp6", "previous_cp6_ref"),
        ("superseding_cp5", "superseding_cp5_ref"),
        ("approval", "approval_ref"),
    )
    for authority_name, receipt_name in lineage_contract:
        logical_ref = receipt.payload.get(receipt_name)
        if (
            lineage.get(f"{authority_name}_ref") != logical_ref
            or not _is_process_logical_ref(logical_ref)
        ):
            raise ValueError("authorization lineage ref is not owner-authorized")
        raw = _read_process_bytes(project_root, logical_ref)
        if hashlib.sha256(raw).hexdigest() != lineage.get(
            f"{authority_name}_bytes_digest"
        ):
            raise ValueError("authorization lineage bytes are not owner-authorized")
    inputs = authority.get("inputs")
    if not isinstance(inputs, dict) or set(inputs) != _REVALIDATION_AUTHORITY_INPUT_FIELDS:
        raise ValueError("revalidation authority input schema is not closed")
    for name in ("downstream_policy", "admission_plan", "current_selections"):
        _authorized_revalidation_input_bytes(
            project_root,
            receipt,
            authority,
            name=name,
        )
    return authority


def _current_revalidation_policy(
    project_root: Path,
    receipt: Cp6RevalidationReceiptV1,
    authority: Mapping[str, Any],
    logical_ref: object,
) -> dict[str, Any]:
    expected_ref = _expected_revalidation_input_ref(receipt, name="downstream_policy")
    raw = _authorized_revalidation_input_bytes(
        project_root,
        receipt,
        authority,
        name="downstream_policy",
        logical_ref=logical_ref,
    )
    try:
        policy = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("downstream policy bytes are invalid") from exc
    if not isinstance(policy, dict) or set(policy) != {
        "schema_version",
        "consumers",
        "policy_digest",
        "current_receipts",
    }:
        raise ValueError("downstream policy schema is not closed")
    return {
        **policy,
        "logical_ref": expected_ref,
        "bytes_digest": hashlib.sha256(raw).hexdigest(),
    }


def _current_revalidation_admission_plan(
    project_root: Path,
    receipt: Cp6RevalidationReceiptV1,
    authority: Mapping[str, Any],
    logical_ref: object,
) -> dict[str, Any]:
    raw = _authorized_revalidation_input_bytes(
        project_root,
        receipt,
        authority,
        name="admission_plan",
        logical_ref=logical_ref,
    )
    try:
        plan = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("admission plan bytes are invalid") from exc
    if not isinstance(plan, dict):
        raise ValueError("admission plan must be an object")
    if set(plan) != {"authorization_digest", "bound_policy", "plan_digest"}:
        raise ValueError("admission plan schema is not closed")
    if plan.get("authorization_digest") != receipt.as_dict()["payload_digest"]:
        raise ValueError("admission plan is not bound to the current authorization")
    return plan


def _current_revalidation_selections(
    project_root: Path,
    receipt: Cp6RevalidationReceiptV1,
    authority: Mapping[str, Any],
    logical_ref: object,
) -> dict[tuple[str, str], dict[str, Any]]:
    raw = _authorized_revalidation_input_bytes(
        project_root,
        receipt,
        authority,
        name="current_selections",
        logical_ref=logical_ref,
    )
    try:
        selector = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("current selector bytes are invalid") from exc
    if not isinstance(selector, dict):
        raise ValueError("current selector must be an object")
    if set(selector) != {"schema_version", "selections", "selection_digest"}:
        raise ValueError("current selector schema is not closed")
    selections = selector.get("selections")
    if (
        selector.get("schema_version") != 1
        or not isinstance(selections, list)
        or selector.get("selection_digest") != canonical_digest(selections)
    ):
        raise ValueError("current selector digest/schema is invalid")
    selection_index: dict[tuple[str, str], dict[str, Any]] = {}
    for selection in selections:
        if (
            not isinstance(selection, dict)
            or set(selection)
            != {"producer", "consumer", "current_ref", "superseded_by"}
            or not isinstance(selection.get("producer"), str)
            or not selection["producer"]
            or not isinstance(selection.get("consumer"), str)
            or not selection["consumer"]
        ):
            raise ValueError("current selector entry is invalid")
        key = (selection["producer"], selection["consumer"])
        if key in selection_index:
            raise ValueError("current selector contains a duplicate identity")
        selection_index[key] = selection
    return selection_index


def _load_revalidation_action_context(
    project_root: Path,
    context_ref: object,
    *,
    action: str,
) -> dict[str, Any]:
    context = _read_process_json(project_root, context_ref)
    if (
        set(context) != {"schema_version", "action", "payload"}
        or context.get("schema_version") != 1
        or context.get("action") != action
        or not isinstance(context.get("payload"), dict)
    ):
        raise ValueError("revalidation action context schema/action mismatch")
    fields = {
        "plan": {"downstream_policy_ref"},
        "apply": {
            "plan_ref",
            "expected_plan_digest",
            "downstream_policy_ref",
        },
        "recover": {"preflight_ref", "projection_ref"},
        "completion": {
            "required_digests", "p01_event_ref", "projection_ref", "consumer",
            "receipt_refs", "admission_plan_ref", "current_selections_ref",
        },
    }
    payload = dict(context["payload"])
    if action not in fields or set(payload) != fields[action]:
        raise ValueError("revalidation action context payload fields mismatch")
    return payload


def _public_domain_failure(action: str, result: Mapping[str, Any]) -> dict[str, Any] | None:
    decision = result.get("decision")
    count = result.get("mutation_count")
    if decision not in {"BLOCKED", "PARTIAL"}:
        return None
    if not _valid_mutation_count(count):
        return _operation_blocked(action, "REVALIDATION_DOMAIN_RESULT_INVALID")
    return {
        "action": action,
        "status": decision,
        "decision": decision,
        "mutation_count": count,
        "postcondition": "UNVERIFIED",
        "reason_codes": list(result.get("reason_codes") or []),
        "exit_code": 2,
    }


def _public_domain_success(
    action: str,
    result: Mapping[str, Any],
    *,
    status: str,
    mutation_count: int,
) -> dict[str, Any]:
    output = dict(result)
    output.update(
        {
            "action": action,
            "status": status,
            "decision": "PASS",
            "mutation_count": mutation_count,
            "postcondition": "VERIFIED",
            "exit_code": 0,
        }
    )
    return output


def _current_revalidation_generation_base(
    project_root: Path,
    receipt: Cp6RevalidationReceiptV1,
    *,
    authorization_ref: str,
    authorization_bytes: bytes,
    action: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """重新取得同一代 owner authority 与 live source。"""

    current_authorization_bytes = _read_process_bytes(
        project_root,
        authorization_ref,
    )
    if current_authorization_bytes != authorization_bytes:
        raise ValueError("authorization bytes changed during mutation")
    authority = _current_revalidation_authority(
        project_root,
        receipt,
        authorization_ref=authorization_ref,
        authorization_bytes=current_authorization_bytes,
        action=action,
    )
    source = _current_revalidation_source(project_root, receipt)
    return authority, source


def _generation_bound_create_once_services(
    *,
    create_once_writer: Any,
    postcheck_reader: Any,
    precommit: Any,
    postcommit: Any,
) -> tuple[Any, Any]:
    """把 create-once 与 target postcheck 绑定到同一代输入。"""

    def write(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            precommit()
        except Exception as exc:
            raise OSError("revalidation generation changed before mutation") from exc
        result = create_once_writer(path, payload)
        try:
            postcommit()
        except Exception as exc:
            raise OSError("revalidation generation changed after mutation") from exc
        return result

    def read(path: Path) -> dict[str, Any]:
        result = postcheck_reader(path)
        try:
            postcommit()
        except Exception as exc:
            raise OSError(
                "revalidation generation changed during target postcheck"
            ) from exc
        return result

    return write, read


def _projection_observation(
    project_root: Path,
    logical_ref: object,
) -> dict[str, Any]:
    raw = _read_process_bytes(project_root, logical_ref)
    try:
        inner = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("projection observation bytes are invalid") from exc
    if not isinstance(inner, dict):
        raise ValueError("projection observation must contain an object")
    return {
        **inner,
        "logical_ref": str(logical_ref),
        "bytes": raw,
        "bytes_digest": hashlib.sha256(raw).hexdigest(),
    }


def _run_default_cp6_revalidation_operation(
    request: Mapping[str, Any],
) -> dict[str, Any]:
    """从 canonical action context 调用真实 domain functions。"""

    action = str(request.get("action") or "")
    project_root = Path(request.get("project_root") or Path.cwd()).resolve()
    authorization_ref = request.get("authorization")
    target_ref = str(request.get("target") or "")
    try:
        authorization_bytes = _read_process_bytes(project_root, authorization_ref)
        authorization_raw = json.loads(authorization_bytes)
        if not isinstance(authorization_raw, dict):
            raise ValueError("authorization must contain one JSON object")
        authorization = freeze_cp6_revalidation_receipt(**authorization_raw)
        if authorization.kind != "authorization":
            raise ValueError("authorization ref must contain an authorization receipt")
        authority, source_observation = _current_revalidation_generation_base(
            project_root,
            authorization,
            authorization_ref=str(authorization_ref or ""),
            authorization_bytes=authorization_bytes,
            action=action,
        )
        expected_target_ref = _expected_revalidation_target_ref(
            authorization,
            action=action,
        )
        if target_ref != expected_target_ref:
            raise ValueError("target is outside the authorization capability")
        target, target_observation = _current_target_observation(
            project_root, target_ref
        )
        if action in {"replay", "inspect"}:
            replay = recover_cp6_revalidation_receipt(
                target, authorization, attempt_id=authorization.attempt_id
            )
            failure = _public_domain_failure(action, replay)
            if failure is not None:
                return failure
            return _public_domain_success(
                action,
                replay,
                status="NO_CHANGE" if action == "replay" else "READY",
                mutation_count=0,
            )
        context = _load_revalidation_action_context(
            project_root, request.get("context"), action=action
        )
        if action == "plan":
            downstream_policy = _current_revalidation_policy(
                project_root,
                authorization,
                authority,
                context["downstream_policy_ref"],
            )
            result = plan_cp6_revalidation(
                authorization,
                source_observation=source_observation,
                target_observation=target_observation,
                downstream_policy=downstream_policy,
            )
            failure = _public_domain_failure(action, result)
            if failure is not None:
                return failure
            return _public_domain_success(
                action, result, status="READY", mutation_count=0
            )
        if action == "apply":
            plan_document = _read_process_json(project_root, context["plan_ref"])
            if (
                set(plan_document)
                != {
                    "action",
                    "status",
                    "decision",
                    "mutation_count",
                    "postcondition",
                    "exit_code",
                    "plan",
                    "plan_digest",
                }
                or plan_document.get("action") != "plan"
                or plan_document.get("status") != "READY"
                or plan_document.get("decision") != "PASS"
                or plan_document.get("mutation_count") != 0
                or plan_document.get("postcondition") != "VERIFIED"
                or plan_document.get("exit_code") != 0
                or not isinstance(plan_document.get("plan"), Mapping)
                or plan_document.get("plan_digest")
                != canonical_digest(dict(plan_document["plan"]))
            ):
                return _operation_blocked(action, "REVALIDATION_PLAN_REF_INVALID")
            def current_apply_inputs() -> tuple[dict[str, Any], dict[str, Any]]:
                current_authority, current_source = (
                    _current_revalidation_generation_base(
                        project_root,
                        authorization,
                        authorization_ref=str(authorization_ref or ""),
                        authorization_bytes=authorization_bytes,
                        action=action,
                    )
                )
                current_policy = _current_revalidation_policy(
                    project_root,
                    authorization,
                    current_authority,
                    context["downstream_policy_ref"],
                )
                return current_source, current_policy

            def observe_apply_current() -> dict[str, Any]:
                current_source, current_policy = current_apply_inputs()
                _current_target, current_target = _current_target_observation(
                    project_root,
                    target_ref,
                )
                return {
                    "source_observation": current_source,
                    "target_observation": current_target,
                    "downstream_policy": current_policy,
                }

            def validate_apply_precommit() -> None:
                current = observe_apply_current()
                expected = {
                    "source_observation": plan_document["plan"][
                        "source_observation"
                    ],
                    "target_observation": plan_document["plan"][
                        "target_observation"
                    ],
                    "downstream_policy": plan_document["plan"][
                        "downstream_policy"
                    ],
                }
                if current != expected:
                    raise ValueError("apply generation changed before mutation")

            def validate_apply_postcommit() -> None:
                current_source, current_policy = current_apply_inputs()
                if (
                    current_source != plan_document["plan"]["source_observation"]
                    or current_policy != plan_document["plan"]["downstream_policy"]
                ):
                    raise ValueError("apply generation changed after mutation")

            apply_writer, apply_reader = _generation_bound_create_once_services(
                create_once_writer=_create_once_json,
                postcheck_reader=_read_json,
                precommit=validate_apply_precommit,
                postcommit=validate_apply_postcommit,
            )
            result = apply_cp6_revalidation_receipt(
                target,
                authorization,
                expected_plan_digest=str(context["expected_plan_digest"] or ""),
                plan=plan_document["plan"],
                observe_current=observe_apply_current,
                create_once_writer=apply_writer,
                postcheck_reader=apply_reader,
            )
            failure = _public_domain_failure(action, result)
            if failure is not None:
                return failure
            return _public_domain_success(
                action,
                result,
                status=str(result.get("status") or "APPLIED"),
                mutation_count=int(result.get("mutation_count") or 0),
            )
        if action == "recover":
            def current_recover_generation() -> dict[str, Any]:
                current_authority, current_source = (
                    _current_revalidation_generation_base(
                        project_root,
                        authorization,
                        authorization_ref=str(authorization_ref or ""),
                        authorization_bytes=authorization_bytes,
                        action=action,
                    )
                )
                current_preflight_bytes = _read_process_bytes(
                    project_root,
                    context["preflight_ref"],
                )
                current_preflight = json.loads(current_preflight_bytes)
                if not isinstance(current_preflight, dict):
                    raise ValueError("recover preflight must remain an object")
                current_projection = _projection_observation(
                    project_root,
                    context["projection_ref"],
                )
                fingerprint = canonical_digest({
                    "authority_digest": canonical_digest(current_authority),
                    "source": current_source,
                    "preflight_bytes_digest": hashlib.sha256(
                        current_preflight_bytes
                    ).hexdigest(),
                    "projection_bytes_digest": current_projection["bytes_digest"],
                })
                return {
                    "fingerprint": fingerprint,
                    "preflight": current_preflight,
                    "projection": current_projection,
                }

            recover_generation = current_recover_generation()
            expected_recover_generation = recover_generation["fingerprint"]

            def validate_recover_generation() -> None:
                current = current_recover_generation()
                if current["fingerprint"] != expected_recover_generation:
                    raise ValueError("recover generation changed during mutation")

            recover_writer, recover_reader = (
                _generation_bound_create_once_services(
                    create_once_writer=_create_once_json,
                    postcheck_reader=_read_json,
                    precommit=validate_recover_generation,
                    postcommit=validate_recover_generation,
                )
            )
            result = recover_missing_cp6_revalidation_completion(
                authorization=authorization,
                preflight=recover_generation["preflight"],
                projection=recover_generation["projection"],
                target_observation={
                    **target_observation,
                    "path": target,
                },
                create_once_writer=recover_writer,
                postcheck_reader=recover_reader,
            )
            failure = _public_domain_failure(action, result)
            if failure is not None:
                return failure
            return _public_domain_success(
                action,
                result,
                status=str(result.get("status") or "RECOVERED"),
                mutation_count=int(result.get("mutation_count") or 0),
            )
        if action == "completion":
            def current_completion_generation() -> dict[str, Any]:
                current_authority, current_source = (
                    _current_revalidation_generation_base(
                        project_root,
                        authorization,
                        authorization_ref=str(authorization_ref or ""),
                        authorization_bytes=authorization_bytes,
                        action=action,
                    )
                )
                event_ref = context["p01_event_ref"]
                event_bytes = _read_process_bytes(project_root, event_ref)
                event_digest = hashlib.sha256(event_bytes).hexdigest()
                current_preflight = validate_cp6_revalidation_preflight(
                    authorization,
                    required_digests=context["required_digests"],
                    p01_event={
                        "logical_ref": str(event_ref),
                        "event_bytes": event_bytes,
                        "event_bytes_digest": event_digest,
                        "current_event_bytes_digest": event_digest,
                    },
                )
                if _public_domain_failure(action, current_preflight) is not None:
                    raise ValueError("completion preflight is not current")
                current_projection = _projection_observation(
                    project_root,
                    context["projection_ref"],
                )
                current_plan = _current_revalidation_admission_plan(
                    project_root,
                    authorization,
                    current_authority,
                    context["admission_plan_ref"],
                )
                current_selections = _current_revalidation_selections(
                    project_root,
                    authorization,
                    current_authority,
                    context["current_selections_ref"],
                )
                current_downstream = admit_revalidation_downstream_receipts(
                    consumer=str(context["consumer"]),
                    receipt_refs=list(context["receipt_refs"]),
                    plan_observation=current_plan,
                    current_attempt={
                        "story_id": authorization.story_id,
                        "attempt_id": authorization.attempt_id,
                        "plan_digest": current_plan.get("plan_digest"),
                    },
                    expected_authorization_digest=authorization.as_dict()[
                        "payload_digest"
                    ],
                    authorized_downstream_set=list(
                        authorization.payload["downstream_set"]
                    ),
                    resolve_receipt=lambda ref: _read_process_bytes(
                        project_root,
                        ref,
                    ),
                    select_current=lambda producer, consumer: {
                        "current_ref": current_selections[(producer, consumer)][
                            "current_ref"
                        ],
                        "superseded_by": current_selections[(producer, consumer)][
                            "superseded_by"
                        ],
                    },
                )
                if _public_domain_failure(action, current_downstream) is not None:
                    raise ValueError("completion downstream set is not current")
                selection_snapshot = [
                    {
                        "producer": producer,
                        "consumer": consumer,
                        **selection,
                    }
                    for (producer, consumer), selection in sorted(
                        current_selections.items()
                    )
                ]
                receipt_snapshot = [
                    {
                        "logical_ref": ref,
                        "bytes_digest": hashlib.sha256(
                            _read_process_bytes(project_root, ref)
                        ).hexdigest(),
                    }
                    for ref in context["receipt_refs"]
                ]
                fingerprint = canonical_digest({
                    "authority_digest": canonical_digest(current_authority),
                    "source": current_source,
                    "event_bytes_digest": event_digest,
                    "preflight_digest": current_preflight["receipt"][
                        "payload_digest"
                    ],
                    "projection_bytes_digest": current_projection["bytes_digest"],
                    "admission_plan_digest": canonical_digest(current_plan),
                    "selection_digest": canonical_digest(selection_snapshot),
                    "receipt_snapshot": receipt_snapshot,
                    "downstream_digest": canonical_digest(current_downstream),
                })
                return {
                    "fingerprint": fingerprint,
                    "preflight": current_preflight["receipt"],
                    "projection": current_projection,
                }

            completion_generation = current_completion_generation()
            expected_completion_generation = completion_generation["fingerprint"]

            def validate_completion_generation() -> None:
                current = current_completion_generation()
                if current["fingerprint"] != expected_completion_generation:
                    raise ValueError("completion generation changed during mutation")

            completion_writer, completion_reader = (
                _generation_bound_create_once_services(
                    create_once_writer=_create_once_json,
                    postcheck_reader=_read_json,
                    precommit=validate_completion_generation,
                    postcommit=validate_completion_generation,
                )
            )
            result = recover_missing_cp6_revalidation_completion(
                authorization=authorization,
                preflight=completion_generation["preflight"],
                projection=completion_generation["projection"],
                target_observation={**target_observation, "path": target},
                create_once_writer=completion_writer,
                postcheck_reader=completion_reader,
            )
            failure = _public_domain_failure(action, result)
            if failure is not None:
                return failure
            return _public_domain_success(
                action,
                result,
                status="COMPLETE",
                mutation_count=int(result.get("mutation_count") or 0),
            )
    except (FrozenCp6EvidenceError, KeyError, OSError, TypeError, ValueError):
        return _operation_blocked(action, "REVALIDATION_DEFAULT_INPUT_INVALID")
    return _operation_blocked(action, "REVALIDATION_ACTION_INVALID")


# P02 bootstrap deliberately does not reuse ``revalidate-cp6``.  The latter is
# a legacy multi-action operation whose authority is Work-bound; this issuer is
# a narrow, receipt-bound, two-target operation and must never open WORK.yaml.
_AUTHORITY_ISSUE_REQUIRED_FLAGS = (
    "--project-root", "--work-ref", "--story-id", "--attempt-id", "--approval-ref",
    "--previous-cp6-result-ref", "--superseding-cp5-result-ref", "--scope-digest",
)
_AUTHORITY_ISSUE_REF_RE = re.compile(r"^process/(?!.*(?:^|/)\.\.?/)[A-Za-z0-9][A-Za-z0-9._/-]*$")
_AUTHORITY_ISSUE_WORK_RE = re.compile(r"^process/works/([A-Za-z0-9][A-Za-z0-9._-]*)/WORK\.yaml$")
_AUTHORITY_ISSUE_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_AUTHORITY_ISSUE_OID_RE = re.compile(r"^[0-9a-f]{40}$")


def _authority_issue_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(dict(payload), ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def _authority_issue_digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_authority_issue_json_bytes(payload)).hexdigest()


def _authority_issue_ref(value: object, field: str) -> str:
    result = str(value or "")
    if not _AUTHORITY_ISSUE_REF_RE.fullmatch(result) or "//" in result:
        raise ValueError(f"{field} must be a canonical process ref")
    return result


def _authority_issue_read_json(project_root: Path, logical_ref: object, field: str) -> tuple[str, bytes, dict[str, Any]]:
    ref = _authority_issue_ref(logical_ref, field)
    raw = _read_process_bytes(project_root, ref)
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{field} bytes are not one JSON object") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{field} must contain one JSON object")
    return ref, raw, payload


def _authority_issue_oid(payload: Mapping[str, Any], name: str) -> str:
    candidates = (
        payload.get(name),
        (payload.get("repository_oids") or {}).get(
            "release_head" if name == "release_oid" else "process_head"
        ) if isinstance(payload.get("repository_oids"), Mapping) else None,
    )
    for candidate in candidates:
        if isinstance(candidate, str) and _AUTHORITY_ISSUE_OID_RE.fullmatch(candidate):
            return candidate
    raise ValueError(f"{name} is absent from immutable input")


def _authority_issue_repository_oids(
    project_root: Path,
    process_anchor: Path,
    previous: Mapping[str, Any],
    superseding: Mapping[str, Any],
) -> tuple[str, str, str]:
    """Resolve immutable OIDs, with a fail-closed legacy bootstrap.

    Only when both immutable inputs entirely lack both OIDs do we bind the
    receipt to the live release/process HEADs.  Caller-supplied OIDs are not
    accepted, and a partial or mixed legacy input remains invalid.
    """

    def optional(payload: Mapping[str, Any], name: str) -> str | None:
        try:
            return _authority_issue_oid(payload, name)
        except ValueError:
            return None

    previous_pair = (
        optional(previous, "release_oid"),
        optional(previous, "process_oid"),
    )
    superseding_pair = (
        optional(superseding, "release_oid"),
        optional(superseding, "process_oid"),
    )
    if all(previous_pair) and all(superseding_pair):
        if previous_pair != superseding_pair:
            raise ValueError("immutable input OIDs disagree")
        return str(previous_pair[0]), str(previous_pair[1]), "immutable-inputs"
    if any(previous_pair) or any(superseding_pair):
        raise ValueError("immutable input OIDs are incomplete")
    return (
        _git_head(project_root),
        _git_head(process_anchor.parent),
        "live-head-legacy-bootstrap",
    )


def _authority_issue_target_bytes(project_root: Path, logical_ref: str) -> tuple[Path, bytes | None]:
    path = _resolve_runtime_ref(project_root, logical_ref)
    try:
        if not path.exists():
            return path, None
        if not path.is_file():
            raise ValueError("authority target is not a regular file")
        return path, path.read_bytes()
    except OSError as exc:
        raise ValueError("authority target observation is unavailable") from exc


def _authority_issue_sidecar_ref(receipt_ref: str) -> str:
    suffix = "/receipts/authorization.json"
    if not receipt_ref.endswith(suffix):
        raise ValueError("receipt ref does not have the canonical authorization suffix")
    return receipt_ref[: -len(suffix)] + "/receipts/authorization-binding.v2.json"


def _authority_issue_plan(
    project_root: Path,
    *,
    work_ref: object,
    story_id: object,
    attempt_id: object,
    approval_ref: object,
    previous_ref: object,
    superseding_ref: object,
    scope_digest: object,
) -> dict[str, Any]:
    """Build the closed P02 bootstrap plan without reading the Work object."""

    work_match = _AUTHORITY_ISSUE_WORK_RE.fullmatch(str(work_ref or ""))
    if work_match is None:
        raise ValueError("work_ref must be exactly process/works/<work-id>/WORK.yaml")
    work_id = work_match.group(1)
    story = str(story_id or "")
    attempt = str(attempt_id or "")
    if not STORY_ID_RE.fullmatch(story) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", attempt):
        raise ValueError("story_id or attempt_id is invalid")
    if not isinstance(scope_digest, str) or not _AUTHORITY_ISSUE_DIGEST_RE.fullmatch(scope_digest):
        raise ValueError("scope_digest must be a lowercase sha256 digest")
    approval_logical_ref, approval_bytes, approval_payload = _authority_issue_read_json(
        project_root, approval_ref, "approval_ref"
    )
    previous, previous_bytes, previous_payload = _authority_issue_read_json(project_root, previous_ref, "previous_cp6_result_ref")
    superseding, superseding_bytes, superseding_payload = _authority_issue_read_json(project_root, superseding_ref, "superseding_cp5_result_ref")
    cr_id = str(approval_payload.get("cr_id") or "")
    if not re.fullmatch(r"CR-[0-9]+(?:-[A-Za-z0-9._-]+)*", cr_id):
        raise ValueError("approval_ref must provide an exact cr_id")
    superseding_path = _resolve_runtime_ref(project_root, superseding)
    release_oid, process_oid, repository_oid_source = _authority_issue_repository_oids(
        project_root,
        superseding_path,
        previous_payload,
        superseding_payload,
    )
    receipt_ref = f"process/works/{work_id}/revalidation/{attempt}/receipts/authorization.json"
    sidecar_ref = _authority_issue_sidecar_ref(receipt_ref)
    receipt_path, receipt_before = _authority_issue_target_bytes(project_root, receipt_ref)
    sidecar_path, sidecar_before = _authority_issue_target_bytes(project_root, sidecar_ref)
    del receipt_path, sidecar_path  # target paths are never persisted or emitted.
    previous_digest = hashlib.sha256(previous_bytes).hexdigest()
    superseding_digest = hashlib.sha256(superseding_bytes).hexdigest()
    approval_digest = hashlib.sha256(approval_bytes).hexdigest()
    plan_preimage_digest = canonical_digest({
        "approval_digest": approval_digest,
        "previous_cp6_digest": previous_digest,
        "superseding_cp5_digest": superseding_digest,
        "release_oid": release_oid,
        "process_oid": process_oid,
        "scope_digest": scope_digest,
        "work_id": work_id,
        "story_id": story,
        "attempt_id": attempt,
    })
    receipt = {
        "schema_version": 1, "cr_id": cr_id, "story_id": story, "work_id": work_id,
        "attempt_id": attempt, "release_oid": release_oid, "process_oid": process_oid,
        "scope_digest": scope_digest, "previous_cp6_ref": previous,
        "previous_cp6_digest": previous_digest, "superseding_cp5_ref": superseding,
        "superseding_cp5_digest": superseding_digest, "plan_preimage_digest": plan_preimage_digest,
        "allowed_write_paths": [
            f"process/works/{work_id}/revalidation/{attempt}/artifacts/return.json"
        ],
    }
    # Reuse the frozen P01 parser as the compatibility oracle before any write.
    freeze_cp6_revalidation_authorization(**receipt)
    receipt_bytes = _authority_issue_json_bytes(receipt)
    receipt_digest = hashlib.sha256(receipt_bytes).hexdigest()
    binding_payload = {
        "schema_version": "Cp6RevalidationAuthorizationBindingV2", "receipt_ref": receipt_ref,
        "receipt_digest": receipt_digest, "cr_id": cr_id, "story_id": story,
        "work_id": work_id, "attempt_id": attempt,
        "approval_ref": approval_logical_ref,
        "approval_digest": approval_digest,
        "owner_authority": "oa-v2-" + canonical_digest({
            "receipt_digest": receipt_digest, "approval_digest": approval_digest,
            "scope_digest": scope_digest,
        }),
        "binding_payload_digest": canonical_digest({
            "receipt_digest": receipt_digest, "approval_digest": approval_digest,
            "previous_cp6_digest": previous_digest, "superseding_cp5_digest": superseding_digest,
        }),
        "plan_preimage_digest": plan_preimage_digest, "release_oid": release_oid,
        "process_oid": process_oid, "scope_digest": scope_digest,
    }
    validate_authority_binding(
        binding_payload,
        receipt=receipt,
        approval_ref=approval_logical_ref,
        approval_digest=approval_digest,
    )
    sidecar_bytes = _authority_issue_json_bytes(binding_payload)
    sidecar_digest = hashlib.sha256(sidecar_bytes).hexdigest()
    plan_core = {
        "operation": "issue-revalidation-authority", "cr_id": cr_id, "story_id": story,
        "work_id": work_id, "attempt_id": attempt, "receipt_digest": receipt_digest,
        "sidecar_digest": sidecar_digest, "approval_digest": approval_digest,
        "plan_preimage_digest": plan_preimage_digest,
        "repository_oid_source": repository_oid_source,
        "target_order": ["authorization-receipt", "authority-binding"],
    }
    return {
        "schema_version": 1, "action": "plan", "status": "READY", "decision": "PASS",
        "mutation_count": 0, "receipt": receipt, "sidecar": binding_payload,
        "repository_oid_source": repository_oid_source,
        "plan_digest": canonical_digest(plan_core),
        "targets": [
            {"target_kind": "authorization-receipt", "logical_ref": receipt_ref,
             "preimage_digest": hashlib.sha256(receipt_before).hexdigest() if receipt_before is not None else None,
             "candidate_digest": receipt_digest},
            {"target_kind": "authority-binding", "logical_ref": sidecar_ref,
             "preimage_digest": hashlib.sha256(sidecar_before).hexdigest() if sidecar_before is not None else None,
             "candidate_digest": sidecar_digest},
        ],
    }


def _authority_issue_result(plan: Mapping[str, Any], *, status: str, receipt_count: int, sidecar_count: int, pair_state: str, recovery_origin: str | None, error: str | None = None) -> dict[str, Any]:
    """兼容 facade；closed tuple 的唯一 owner 位于 semantics.authority。"""

    return render_authority_apply_result(
        plan_digest=str(plan["plan_digest"]),
        targets=plan["targets"],
        status=status,
        receipt_count=receipt_count,
        sidecar_count=sidecar_count,
        pair_state=pair_state,
        recovery_origin=recovery_origin,
        error=error,
    )


def _authority_issue_create_once(path: Path, data: bytes) -> None:
    """Internal injection seam for targeted writer-fault tests; not public CLI."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)


def _authority_issue_postcheck_bytes(path: Path) -> bytes:
    """Internal postcondition seam; faults remain unrepresentable in the CLI."""

    return path.read_bytes()


def _authority_issue_observe_created_target(path: Path) -> tuple[int, str]:
    """writer 抛错后按文件系统事实观测本次 create-once mutation。

    返回 ``(count, state)``；原 preimage 必为 absent，因此 target 一旦存在就表示
    本次调用已经发生不可覆盖 mutation。观测自身不可用时采用保守 count=1，
    并把 pair durability 降为 unknown，绝不把潜在 mutation 报成零。
    """

    try:
        path.lstat()
    except FileNotFoundError:
        return 0, "absent"
    except OSError:
        return 1, "unknown"
    return 1, "present"


def _apply_authority_issue(project_root: Path, plan: Mapping[str, Any], expected_plan_digest: object) -> dict[str, Any]:
    if expected_plan_digest != plan["plan_digest"]:
        raise ValueError("expected_plan_digest does not match the current plan")
    receipt_ref = str(plan["targets"][0]["logical_ref"])
    sidecar_ref = str(plan["targets"][1]["logical_ref"])
    receipt_path, receipt_before = _authority_issue_target_bytes(project_root, receipt_ref)
    sidecar_path, sidecar_before = _authority_issue_target_bytes(project_root, sidecar_ref)
    receipt_bytes = _authority_issue_json_bytes(plan["receipt"])
    sidecar_bytes = _authority_issue_json_bytes(plan["sidecar"])
    if sidecar_before is not None and receipt_before != receipt_bytes:
        raise ValueError("sidecar without the exact receipt is noncanonical")
    if receipt_before not in {None, receipt_bytes} or sidecar_before not in {None, sidecar_bytes}:
        raise ValueError("immutable authority target bytes differ")
    if receipt_before == receipt_bytes and sidecar_before == sidecar_bytes:
        return _authority_issue_result(plan, status="NO_CHANGE", receipt_count=0, sidecar_count=0, pair_state="active", recovery_origin=None)
    receipt_count = 0
    sidecar_count = 0
    try:
        if receipt_before is None:
            _authority_issue_create_once(receipt_path, receipt_bytes)
            receipt_count = 1
    except OSError:
        receipt_count, observed = _authority_issue_observe_created_target(receipt_path)
        if receipt_count == 0:
            return _authority_issue_result(plan, status="BLOCKED", receipt_count=0, sidecar_count=0, pair_state="nonactive", recovery_origin=None, error="E_FAULT_BEFORE_RECEIPT")
        return _authority_issue_result(
            plan,
            status="PARTIAL",
            receipt_count=receipt_count,
            sidecar_count=0,
            pair_state="unknown" if observed == "unknown" else "nonactive",
            recovery_origin=None,
            error="E_FAULT_AFTER_RECEIPT",
        )
    try:
        if sidecar_before is None:
            _authority_issue_create_once(sidecar_path, sidecar_bytes)
            sidecar_count = 1
    except OSError:
        observed_count, observed = _authority_issue_observe_created_target(sidecar_path)
        sidecar_count = max(sidecar_count, observed_count)
        return _authority_issue_result(
            plan,
            status="PARTIAL",
            receipt_count=receipt_count,
            sidecar_count=sidecar_count,
            pair_state="unknown" if observed == "unknown" else "nonactive",
            recovery_origin=None,
            error=(
                "E_FAULT_AFTER_SIDECAR"
                if sidecar_count == 1
                else "E_FAULT_AFTER_RECEIPT"
            ),
        )
    try:
        receipt_after = _authority_issue_postcheck_bytes(receipt_path)
        sidecar_after = _authority_issue_postcheck_bytes(sidecar_path)
    except OSError:
        return _authority_issue_result(plan, status="PARTIAL", receipt_count=receipt_count, sidecar_count=sidecar_count, pair_state="unknown", recovery_origin=None, error="E_POSTCHECK_UNKNOWN")
    if receipt_after != receipt_bytes or sidecar_after != sidecar_bytes:
        return _authority_issue_result(plan, status="PARTIAL", receipt_count=receipt_count, sidecar_count=sidecar_count, pair_state="nonactive", recovery_origin=None, error="E_FAULT_AFTER_SIDECAR")
    if receipt_count == 1 and sidecar_count == 1:
        return _authority_issue_result(plan, status="APPLIED", receipt_count=1, sidecar_count=1, pair_state="active", recovery_origin=None)
    if receipt_count == 0 and sidecar_count == 1:
        return _authority_issue_result(plan, status="RECOVERED", receipt_count=0, sidecar_count=1, pair_state="active", recovery_origin="receipt-only")
    return _authority_issue_result(plan, status="PARTIAL", receipt_count=receipt_count, sidecar_count=sidecar_count, pair_state="nonactive", recovery_origin=None, error="E_FAULT_AFTER_RECEIPT")


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
        "  revalidate-cp6 Plan a strict immutable CP6 revalidation attempt.\n"
        "  issue-revalidation-authority Issue a frozen receipt plus private binding sidecar.\n"
        "  lld-check       Validate full-lld, batch-lld, technical-note, or waived evidence structure.\n"
        "  cp5-context-check Validate CP5 capsule-first context policy.\n\n"
        "Examples:\n"
        "  meta-flow story return-check --packet process/context/stories/STORY-CR123-S01.CP6.work-packet.json --return process/returns/STORY-CR123-S01.CP6.return.json --project-root .\n"
        "  meta-flow story evidence-index --return process/returns/STORY-CR123-S01.CP6.return.json --project-root .\n"
        "  meta-flow story verify-packet --from-return process/returns/STORY-CR123-S01.CP6.return.json --story process/stories/STORY-CR123-S01.md --project-root .\n"
        "  meta-flow story plan-check --project-root .\n"
        "  meta-flow story project-cp6 --result process/checks/CP6-STORY-CR123-S01.result.json --project-root .\n"
        "  meta-flow story revalidate-cp6 --authorization process/works/W/revalidation/A/AUTHORIZATION.json --release-oid <oid> --process-oid <oid> --scope-digest <sha256> --plan-preimage-digest <sha256> --downstream-set-digest <sha256> --project-root .\n"
        "  meta-flow story lld-check --lld process/stories/STORY-CR123-S01-LLD.md --project-root .\n"
        "  meta-flow story cp5-context-check --context process/context/CP5-LLD-CONTEXT.yaml --project-root .\n"
    )


def _authority_issue_main(args: list[str]) -> int:
    """Parse the deliberately small public grammar for the bootstrap issuer."""

    if not args or args[0] in {"-h", "--help"}:
        print(
            "usage: meta-flow story issue-revalidation-authority {plan,apply} "
            "--project-root <release-root> --work-ref <process-ref> --story-id <exact-id> "
            "--attempt-id <token> --approval-ref <process-ref> "
            "--previous-cp6-result-ref <process-ref> --superseding-cp5-result-ref <process-ref> "
            "--scope-digest <sha256> [--expected-plan-digest <sha256>] [--format {json,human}]"
        )
        return 0
    action = args[0]
    if action not in {"plan", "apply"}:
        return 3
    tokens = args[1:]
    if any(token.startswith("-") and token not in {*_AUTHORITY_ISSUE_REQUIRED_FLAGS, "--expected-plan-digest", "--format"} for token in tokens):
        return 3
    if len(tokens) % 2:
        return 3
    pairs = list(zip(tokens[::2], tokens[1::2], strict=True))
    names = [name for name, _value in pairs]
    if len(names) != len(set(names)) or any(name not in {*_AUTHORITY_ISSUE_REQUIRED_FLAGS, "--expected-plan-digest", "--format"} for name in names):
        return 3
    values = dict(pairs)
    if any(flag not in values for flag in _AUTHORITY_ISSUE_REQUIRED_FLAGS):
        return 3
    if names.index("--project-root") > names.index("--work-ref"):
        return 3
    if action == "plan" and "--expected-plan-digest" in values:
        return 3
    if action == "apply" and "--expected-plan-digest" not in values:
        return 3
    output_format = values.get("--format", "json")
    if output_format not in {"json", "human"}:
        return 3
    try:
        plan = _authority_issue_plan(
            Path(values["--project-root"]).resolve(),
            work_ref=values["--work-ref"], story_id=values["--story-id"],
            attempt_id=values["--attempt-id"], approval_ref=values["--approval-ref"],
            previous_ref=values["--previous-cp6-result-ref"],
            superseding_ref=values["--superseding-cp5-result-ref"],
            scope_digest=values["--scope-digest"],
        )
        result = plan if action == "plan" else _apply_authority_issue(
            Path(values["--project-root"]).resolve(), plan, values["--expected-plan-digest"]
        )
    except (FrozenCp6EvidenceError, OSError, TypeError, ValueError) as exc:
        result = render_authority_input_blocked(
            action=action,
            message=str(exc),
            expected_plan_digest=values.get("--expected-plan-digest", ""),
        )
    if output_format == "json":
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        print(render_human_wire(result))
    return int(result["exit_code"] if "exit_code" in result else 0)


def _print_revalidation_help() -> None:
    print(
        "usage: meta-flow story revalidate-cp6 --action "
        "{plan,apply,replay,inspect,recover,completion} "
        "--authorization <process-ref> --target <process-ref> "
        "[--context <process-ref>] [--output {json,human}]"
    )


def main(
    argv: list[str] | None = None,
    *,
    services: Mapping[str, Any] | None = None,
) -> int:
    args = list(argv or [])
    if not args or args[0] in {"-h", "--help"}:
        _print_story_help()
        return 0
    command = args[0]
    if command == "issue-revalidation-authority":
        return _authority_issue_main(args[1:])
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
            print(f"wrote: {format_runtime_ref(parsed.project_root, path)}")
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
        print(f"wrote: {format_runtime_ref(parsed.project_root, path)}")
        return 0
    if command == "plan-check":
        parser = argparse.ArgumentParser(prog="meta-flow story plan-check")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--plan", dest="plan_path", type=Path, default=None)
        parser.add_argument("--strict-legacy", action="store_true")
        parser.add_argument("--expected-plan-sha256", default="")
        parsed = parser.parse_args(args[1:])
        errors, warnings = validate_story_plan(
            parsed.project_root,
            plan_path=parsed.plan_path,
            strict_legacy=parsed.strict_legacy,
            expected_plan_sha256=parsed.expected_plan_sha256,
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
        parser.add_argument("--freeze-semantic-evidence", action="store_true")
        parser.add_argument("--release-oid", default="")
        parser.add_argument("--process-oid", default="")
        parser.add_argument("--scope-digest", default="")
        parser.add_argument("--implementation-digest", default="")
        parser.add_argument("--dependency-digest", action="append", default=[])
        parsed = parser.parse_args(args[1:])
        try:
            if parsed.freeze_semantic_evidence and parsed.apply:
                raise ValueError(
                    "--freeze-semantic-evidence is a read-only plan operation; mutation=0"
                )
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
                if parsed.freeze_semantic_evidence:
                    frozen = build_cp6_semantic_evidence_v2(
                        parsed.project_root,
                        result_path=parsed.result_path,
                        release_oid=parsed.release_oid,
                        process_oid=parsed.process_oid,
                        scope_digest=parsed.scope_digest,
                        implementation_digest=parsed.implementation_digest,
                        dependency_digests=_parse_dependency_digest_arguments(
                            parsed.dependency_digest
                        ),
                    )
                    output = {
                        "projection_plan": output,
                        "frozen_evidence": frozen.as_dict(),
                    }
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
    if command == "revalidate-cp6":
        if any(value in {"-h", "--help"} for value in args[1:]):
            _print_revalidation_help()
            return 0
        parser = argparse.ArgumentParser(prog="meta-flow story revalidate-cp6")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--authorization", type=Path, required=True)
        parser.add_argument("--target", type=Path, required=True)
        parser.add_argument("--context", type=Path, default=None)
        parser.add_argument("--action", required=True)
        parser.add_argument("--output", choices=("json", "human"), default="json")
        try:
            parsed = parser.parse_args(args[1:])
        except SystemExit:
            return 2
        if parsed.action not in {"plan", "apply", "replay", "inspect", "recover", "completion"}:
            return 2
        request = {
            "action": parsed.action,
            "output": parsed.output,
            "authorization": parsed.authorization,
            "target": parsed.target,
            "context": parsed.context,
            "project_root": parsed.project_root,
        }
        if services is None:
            output = _run_default_cp6_revalidation_operation(request)
        else:
            output = run_cp6_revalidation_operation(
                request=request,
                services=dict(services),
            )
        if parsed.output == "json":
            print(json.dumps(output, ensure_ascii=False, sort_keys=True))
        else:
            print(
                " ".join(
                    f"{key}={output.get(key)}"
                    for key in ("action", "status", "decision", "mutation_count", "postcondition")
                )
            )
        return int(output.get("exit_code") or 0)
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
