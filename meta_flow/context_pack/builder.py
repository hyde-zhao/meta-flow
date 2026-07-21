"""Build and validate context-budgeted Meta Flow context packs."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from meta_flow.checks.token_budget import (
    DEFAULT_BUDGETS,
    DEFAULT_READ_DENY_PATTERNS,
    estimate_tokens,
    load_budgets,
)
from meta_flow.design.feature_registry import FEATURE_DESIGN_MATRIX_REL, FEATURE_REGISTRY_REL
from meta_flow.design.module_boundaries import MODULE_BOUNDARIES_REL
from meta_flow.design.product_governance import (
    CAPABILITY_STATUS_REL,
    CONCEPT_OWNERS_REL,
    PACKAGE_IDENTITY_REL,
)
from meta_flow.policies.authz import AUTHZ_POLICY_REL
from meta_flow.policies.gate_profiles import GATE_PROFILES_REL
from meta_flow.project.process_route import _resolve_runtime_path, _resolve_runtime_ref
from meta_flow.state.current import (
    STATE_CURRENT_ENTRY_REL,
    STATE_CURRENT_REL,
    load_current_state,
    refresh_current_entry,
)
from meta_flow.workflow.cr_lifecycle import (
    CR_INDEX_REL,
    CR_SUMMARY_ROOT_REL,
    validate_index_payload,
)

READ_POLICY_REL = Path("process/policies/READ-POLICY.json")
ARTIFACT_BUDGETS_REL = Path("process/policies/ARTIFACT-BUDGETS.json")
READ_EXPANSION_LEDGER_REL = Path("process/state/READ-EXPANSION-LEDGER.ndjson")
DEFAULT_OUTPUT_ROOT_REL = Path("process/context")
DEFAULT_FULL_DOC_READ_REASONS = (
    "capsule_missing",
    "field_conflict",
    "human_audit",
    "deep_review",
    "schema_validation_failed",
)
DEFAULT_STAGE_READS: dict[str, tuple[str, ...]] = {
    "CP2": (
        "docs/product/SCENARIOS.yaml",
        "docs/product/REQUIREMENTS.md",
        "docs/product/MVP-SCOPE.md",
    ),
    "CP3": (
        "docs/design/BLUEPRINT.md",
        "docs/design/HLD.md",
        "docs/design/FEATURE-DESIGN-MATRIX.md",
    ),
    "CP5": (
        "docs/design/FEATURE-DESIGN-MATRIX.md",
    ),
    "CP6": (),
    "CP7": (),
    "CP8": (
        "process/release/RELEASE-CONTEXT.yaml",
    ),
}
CHECKPOINT_REF_KEYS = ("checkpoint_ref", "checkpoint_refs", "source_checkpoint_refs")
CAPSULE_INLINE_DUPLICATE_MIN_CHARS = 160


@dataclass(frozen=True)
class ReadEntry:
    path: str
    mode: str
    estimated_tokens: int
    required: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "mode": self.mode,
            "estimated_tokens": self.estimated_tokens,
            "required": self.required,
            "reason": self.reason,
        }


def _as_posix(path: Path | str) -> str:
    return Path(path).as_posix()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _iter_cp2_results(project_root: Path, cr_id: str) -> list[Path]:
    checks_root = _resolve_runtime_ref(project_root, "process/checks")
    if not checks_root.is_dir() or not cr_id:
        return []
    compact_cr = cr_id.replace("-", "")
    candidates = [
        *checks_root.glob(f"CP2*{cr_id}*.result.json"),
        *checks_root.glob(f"CP2*{compact_cr}*.result.json"),
        *checks_root.glob("CP2*.result.json"),
    ]
    seen: set[Path] = set()
    paths: list[Path] = []
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        data = _read_json(path)
        if str(data.get("cr_id") or "") == cr_id or cr_id in path.name or compact_cr in path.name:
            paths.append(path)
    return sorted(paths)


def _required_evidence_from_cp2(project_root: Path, cr_id: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in _iter_cp2_results(project_root, cr_id):
        data = _read_json(path)
        commitments = data.get("commitments") or {}
        if not isinstance(commitments, dict):
            continue
        for entry in commitments.get("required_evidence") or []:
            if not isinstance(entry, dict):
                continue
            entry_id = str(entry.get("id") or "")
            if not entry_id or entry_id in seen:
                continue
            seen.add(entry_id)
            copied = dict(entry)
            copied["source_result_ref"] = path.relative_to(project_root).as_posix()
            entries.append(copied)
    return entries


def default_read_policy() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "default_entrypoint": "context_pack",
        "deny_default_reads": list(DEFAULT_READ_DENY_PATTERNS),
        "allow_summary_reads": [
            "process/context/*.context.json",
            "process/changes/summaries/*.summary.json",
            "process/stories/summaries/*.summary.json",
            "process/state/STATE.current.json",
            "process/current/CURRENT.json",
            "process/changes/CR-INDEX.json",
            "process/policies/AUTHZ-POLICY.json",
            "process/policies/GATE-PROFILES.json",
            "docs/design/FEATURE-REGISTRY.yaml",
            "docs/design/FEATURE-DESIGN-MATRIX.yaml",
            "docs/design/MODULE-BOUNDARIES.yaml",
            "docs/design/CAPABILITY-STATUS.yaml",
            "docs/design/CONCEPT-OWNERS.yaml",
            "docs/design/PACKAGE-IDENTITY.yaml",
        ],
        "full_doc_read_allowed_when": list(DEFAULT_FULL_DOC_READ_REASONS),
        "required_full_doc_read_log": READ_EXPANSION_LEDGER_REL.as_posix(),
        "rules": [
            "agent 必须先读取本阶段 context pack",
            "agent 默认只读取 allowed_reads",
            "全文读取必须记录 full_doc_read_reason，且原因必须属于允许枚举",
            "普通 artifact 只能引用 authz policy ID，不复制 policy 全文",
            "process/current/CURRENT.json 是文件系统发现层；状态真相仍以 STATE.current.json 为准",
        ],
    }


def read_policy_path(project_root: Path) -> Path:
    return _resolve_runtime_ref(project_root, READ_POLICY_REL.as_posix())


def load_read_policy(project_root: Path) -> dict[str, Any]:
    configured = _read_json(read_policy_path(project_root))
    if not configured:
        return default_read_policy()
    policy = default_read_policy()
    for key, value in configured.items():
        if isinstance(value, list) and isinstance(policy.get(key), list):
            policy[key] = value
        else:
            policy[key] = value
    return policy


def write_default_read_policy(project_root: Path, *, force: bool = False) -> Path:
    path = read_policy_path(project_root)
    if path.exists() and not force:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(default_read_policy(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _path_tokens(project_root: Path, rel_path: str) -> int:
    path = project_root / rel_path
    if not path.is_file():
        return 0
    try:
        return estimate_tokens(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        return 0


def _read_entry(project_root: Path, rel_path: str, *, required: bool, reason: str) -> ReadEntry:
    return ReadEntry(
        path=rel_path,
        mode="full",
        estimated_tokens=_path_tokens(project_root, rel_path),
        required=required,
        reason=reason,
    )


def _append_unique(entries: list[ReadEntry], entry: ReadEntry) -> None:
    if any(existing.path == entry.path for existing in entries):
        return
    entries.append(entry)


def _deny_default_entries(patterns: list[str]) -> list[dict[str, str]]:
    reasons = {
        "process/STATE.md": "human summary / legacy fallback，不作为 agent 默认机器入口",
        "process/DEVELOPMENT-PLAN.yaml": "计划长文由 Story packet / context 摘要承载",
        "process/STORY-STATUS.md": "legacy status 汇总，不作为当前 Story 真相源",
        "process/changes/*.md": "默认读取 CR summary / CR ledger，完整 CR 只用于审计或冲突恢复",
        "process/stories/*-LLD.md": "默认读取 Story packet / design summary，完整 LLD 按需展开",
        "process/stories/*-IMPLEMENTATION.md": "实现长证据默认通过 return/evidence index 消费",
        "process/archive/**": "历史归档属于冷区，默认禁止读取",
        "process/discussions/**": "讨论日志只用于审计 / 恢复，不替代正式产物",
    }
    return [{"path_or_pattern": pattern, "reason": reasons.get(pattern, "deny-default full document read")} for pattern in patterns]


def _string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        strings: list[str] = []
        for key, item in value.items():
            if str(key).endswith("_ref") or str(key).endswith("_refs") or str(key) in {"path", "ref"}:
                continue
            strings.extend(_string_values(item))
        return strings
    if isinstance(value, list):
        strings = []
        for item in value:
            strings.extend(_string_values(item))
        return strings
    return []


def _checkpoint_refs(context: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for key in CHECKPOINT_REF_KEYS:
        raw = context.get(key)
        if isinstance(raw, str) and raw:
            refs.append(raw)
        elif isinstance(raw, list):
            refs.extend(str(item) for item in raw if str(item))
    return sorted(set(refs))


def _capsule_redundancy_warnings(root: Path, context: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    inline_strings = [
        value.strip()
        for value in _string_values(context)
        if len(value.strip()) >= CAPSULE_INLINE_DUPLICATE_MIN_CHARS
    ]
    if not inline_strings:
        return warnings
    for ref in _checkpoint_refs(context):
        path = root / ref
        if not path.is_file():
            continue
        checkpoint_text = path.read_text(encoding="utf-8", errors="ignore")
        repeated = [value for value in inline_strings if value in checkpoint_text]
        if repeated:
            warnings.append(
                f"capsule_content_redundant: inline content duplicates checkpoint Markdown {ref}"
            )
    return warnings


def _stage_budget(project_root: Path, stage: str, explicit_budget: int | None) -> int:
    if explicit_budget is not None:
        return explicit_budget
    budgets = load_budgets(project_root)
    context_budgets = budgets.get("context_pack", DEFAULT_BUDGETS["context_pack"])
    return int(context_budgets.get(stage, 16000))


def default_output_path(project_root: Path, *, stage: str, cr_id: str, story_id: str) -> Path:
    parts = [stage]
    if cr_id:
        parts.append(cr_id.replace("-", ""))
    if story_id:
        parts.append(story_id.replace("-", ""))
    slug = "-".join(parts)
    return _resolve_runtime_ref(project_root, DEFAULT_OUTPUT_ROOT_REL.as_posix()) / f"{slug}.context.json"


def build_context_pack(
    project_root: Path,
    *,
    stage: str,
    profile: str,
    cr_id: str = "",
    story_id: str = "",
    budget: int | None = None,
    output: Path | None = None,
    write_policy: bool = True,
) -> tuple[dict[str, Any], Path]:
    project_root = project_root.resolve()
    stage = stage.upper()
    if write_policy:
        write_default_read_policy(project_root)
    read_policy = load_read_policy(project_root)
    state = load_current_state(project_root)
    if state:
        refresh_current_entry(project_root)
    project_id = str(state.get("project_id") or project_root.name)
    cr_index_semantic_digest: str | None = None
    cr_index_path = _resolve_runtime_ref(project_root, CR_INDEX_REL.as_posix())
    if cr_index_path.is_file():
        index_payload = _read_json(cr_index_path)
        if not validate_index_payload(index_payload):
            cr_index_semantic_digest = str(index_payload.get("semantic_digest") or "") or None
    allowed_reads: list[ReadEntry] = []
    must_read: list[ReadEntry] = []
    read_if_needed: list[ReadEntry] = []

    _append_unique(
        allowed_reads,
        _read_entry(project_root, STATE_CURRENT_REL.as_posix(), required=True, reason="lightweight_runtime_state"),
    )
    _append_unique(
        allowed_reads,
        _read_entry(project_root, STATE_CURRENT_ENTRY_REL.as_posix(), required=True, reason="current_discovery_entry"),
    )
    _append_unique(must_read, _read_entry(project_root, STATE_CURRENT_REL.as_posix(), required=True, reason="machine_state"))
    _append_unique(
        must_read,
        _read_entry(project_root, STATE_CURRENT_ENTRY_REL.as_posix(), required=True, reason="current_entrypoint"),
    )
    _append_unique(allowed_reads, _read_entry(project_root, CR_INDEX_REL.as_posix(), required=False, reason="cr_index"))
    if cr_id:
        summary_rel = (CR_SUMMARY_ROOT_REL / f"{cr_id}.summary.json").as_posix()
        _append_unique(allowed_reads, _read_entry(project_root, summary_rel, required=True, reason="current_cr_summary"))
    if story_id:
        story_summary_rel = f"process/stories/summaries/{story_id}.summary.json"
        _append_unique(allowed_reads, _read_entry(project_root, story_summary_rel, required=False, reason="story_summary"))
    for rel_path in DEFAULT_STAGE_READS.get(stage, ()):
        if (project_root / rel_path).is_file():
            _append_unique(read_if_needed, _read_entry(project_root, rel_path, required=False, reason=f"{stage.lower()}_stage_source"))
    _append_unique(allowed_reads, _read_entry(project_root, READ_POLICY_REL.as_posix(), required=True, reason="read_policy"))
    _append_unique(must_read, _read_entry(project_root, READ_POLICY_REL.as_posix(), required=True, reason="read_policy"))
    if _resolve_runtime_path(project_root, ARTIFACT_BUDGETS_REL).is_file():
        _append_unique(
            allowed_reads,
            _read_entry(project_root, ARTIFACT_BUDGETS_REL.as_posix(), required=False, reason="artifact_budgets"),
        )
    if _resolve_runtime_path(project_root, GATE_PROFILES_REL).is_file():
        _append_unique(
            allowed_reads,
            _read_entry(project_root, GATE_PROFILES_REL.as_posix(), required=False, reason="gate_profiles"),
        )
    if _resolve_runtime_path(project_root, AUTHZ_POLICY_REL).is_file():
        _append_unique(
            allowed_reads,
            _read_entry(project_root, AUTHZ_POLICY_REL.as_posix(), required=False, reason="authz_policy_registry"),
        )
    if _resolve_runtime_path(project_root, FEATURE_REGISTRY_REL).is_file():
        _append_unique(
            allowed_reads,
            _read_entry(project_root, FEATURE_REGISTRY_REL.as_posix(), required=False, reason="feature_registry"),
        )
    if _resolve_runtime_path(project_root, FEATURE_DESIGN_MATRIX_REL).is_file():
        _append_unique(
            allowed_reads,
            _read_entry(project_root, FEATURE_DESIGN_MATRIX_REL.as_posix(), required=False, reason="feature_design_matrix"),
        )
    if _resolve_runtime_path(project_root, MODULE_BOUNDARIES_REL).is_file():
        _append_unique(
            allowed_reads,
            _read_entry(project_root, MODULE_BOUNDARIES_REL.as_posix(), required=False, reason="module_boundaries"),
        )
    for rel_path, reason in (
        (CAPABILITY_STATUS_REL, "capability_status"),
        (CONCEPT_OWNERS_REL, "concept_owners"),
        (PACKAGE_IDENTITY_REL, "package_identity"),
    ):
        if (project_root / rel_path).is_file():
            _append_unique(allowed_reads, _read_entry(project_root, rel_path.as_posix(), required=False, reason=reason))

    must_verify = _required_evidence_from_cp2(project_root, cr_id) if stage == "CP7" and cr_id else []
    estimated_tokens = sum(entry.estimated_tokens for entry in allowed_reads)
    max_tokens = _stage_budget(project_root, stage, budget)
    denied_default_reads = list(read_policy.get("deny_default_reads") or DEFAULT_READ_DENY_PATTERNS)
    context = {
        "schema_version": 1,
        "project_id": project_id,
        "cr_id": cr_id or None,
        "story_id": story_id or None,
        "stage": stage,
        "profile": profile,
        "budget": {
            "max_tokens": max_tokens,
            "estimated_tokens": estimated_tokens,
            "estimator": "chars_div_4",
        },
        "state_ref": STATE_CURRENT_REL.as_posix(),
        "cr_index_ref": CR_INDEX_REL.as_posix(),
        "cr_index_semantic_digest": cr_index_semantic_digest,
        "cr_summary_ref": (CR_SUMMARY_ROOT_REL / f"{cr_id}.summary.json").as_posix() if cr_id else None,
        "story_summary_ref": f"process/stories/summaries/{story_id}.summary.json" if story_id else None,
        "policy_refs": {
            "read_policy": READ_POLICY_REL.as_posix(),
            "artifact_budgets": ARTIFACT_BUDGETS_REL.as_posix(),
            "gate_profiles": GATE_PROFILES_REL.as_posix(),
            "authz_policy": AUTHZ_POLICY_REL.as_posix(),
        },
        "design_refs": {
            "feature_registry": FEATURE_REGISTRY_REL.as_posix(),
            "feature_design_matrix": FEATURE_DESIGN_MATRIX_REL.as_posix(),
            "module_boundaries": MODULE_BOUNDARIES_REL.as_posix(),
            "capability_status": CAPABILITY_STATUS_REL.as_posix(),
            "concept_owners": CONCEPT_OWNERS_REL.as_posix(),
            "package_identity": PACKAGE_IDENTITY_REL.as_posix(),
        },
        "read_policy_ref": READ_POLICY_REL.as_posix(),
        "must_read": [entry.as_dict() for entry in must_read],
        "allowed_reads": [entry.as_dict() for entry in allowed_reads],
        "read_if_needed": [entry.as_dict() for entry in read_if_needed],
        "must_verify": must_verify,
        "do_not_read_by_default": _deny_default_entries(denied_default_reads),
        "denied_default_reads": denied_default_reads,
        "full_doc_read_allowed_when": list(read_policy.get("full_doc_read_allowed_when") or DEFAULT_FULL_DOC_READ_REASONS),
        "required_full_doc_read_log": str(read_policy.get("required_full_doc_read_log") or READ_EXPANSION_LEDGER_REL.as_posix()),
    }
    output_path = output.resolve() if output else default_output_path(project_root, stage=stage, cr_id=cr_id, story_id=story_id)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(context, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return context, output_path


def _matches_any(rel_path: str, patterns: list[str]) -> bool:
    return any(fnmatch(rel_path, pattern) for pattern in patterns)


def _load_context(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} invalid JSON: {exc}") from exc


def _infer_project_root(context_path: Path) -> Path:
    for parent in context_path.parents:
        if parent.name == "process":
            return parent.parent
    if len(context_path.parents) >= 3:
        return context_path.parents[2]
    return Path.cwd()


def validate_context_pack(context_path: Path, *, project_root: Path | None = None) -> tuple[list[str], list[str]]:
    context_path = context_path.resolve()
    if not context_path.is_file():
        return [f"context pack missing: {context_path}"], []
    root = project_root.resolve() if project_root else _infer_project_root(context_path)
    errors: list[str] = []
    warnings: list[str] = []
    try:
        context = _load_context(context_path)
    except ValueError as exc:
        return [str(exc)], []

    if context.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    for key in (
        "project_id",
        "stage",
        "profile",
        "budget",
        "read_policy_ref",
        "must_read",
        "allowed_reads",
        "read_if_needed",
        "do_not_read_by_default",
        "denied_default_reads",
    ):
        if key not in context:
            errors.append(f"missing required field: {key}")

    budget = context.get("budget") or {}
    max_tokens = int(budget.get("max_tokens") or 0)
    estimated_tokens = int(budget.get("estimated_tokens") or 0)
    if max_tokens <= 0:
        errors.append("budget.max_tokens must be positive")
    if estimated_tokens > max_tokens:
        errors.append(f"estimated_tokens exceeds budget: {estimated_tokens} > {max_tokens}")

    denied_patterns = list(context.get("denied_default_reads") or DEFAULT_READ_DENY_PATTERNS)
    allowed_reads = context.get("allowed_reads") or []
    must_read = context.get("must_read") or []
    read_if_needed = context.get("read_if_needed") or []
    must_verify = context.get("must_verify") or []
    do_not_read_by_default = context.get("do_not_read_by_default") or []
    if not isinstance(must_read, list) or not must_read:
        errors.append("must_read must be a non-empty list")
        must_read = []
    if not isinstance(read_if_needed, list):
        errors.append("read_if_needed must be a list")
        read_if_needed = []
    if "must_verify" in context and not isinstance(context.get("must_verify"), list):
        errors.append("must_verify must be a list")
        must_verify = []
    for index, entry in enumerate(must_verify, 1):
        if not isinstance(entry, dict):
            errors.append(f"must_verify[{index}] must be an object")
            continue
        for key in ("id", "kind", "required_stage"):
            if not entry.get(key):
                errors.append(f"must_verify[{index}] missing {key}")
        if entry.get("required_stage") and str(entry["required_stage"]) != "CP7":
            errors.append(f"must_verify[{index}] required_stage must be CP7")
    if not isinstance(do_not_read_by_default, list) or not do_not_read_by_default:
        errors.append("do_not_read_by_default must be a non-empty list")
        do_not_read_by_default = []
    do_not_patterns = [
        str(entry.get("path_or_pattern") or entry.get("path") or "")
        for entry in do_not_read_by_default
        if isinstance(entry, dict)
    ]
    if not isinstance(allowed_reads, list) or not allowed_reads:
        errors.append("allowed_reads must be a non-empty list")
        allowed_reads = []
    for entry in [*must_read, *allowed_reads, *read_if_needed]:
        if not isinstance(entry, dict):
            errors.append("read entries must be objects")
            continue
        rel_path = str(entry.get("path") or "")
        if not rel_path:
            errors.append("read entry missing path")
            continue
        if _matches_any(rel_path, denied_patterns):
            errors.append(f"allowed_reads contains deny-default path: {rel_path}")
        if entry in read_if_needed and _matches_any(rel_path, denied_patterns):
            errors.append(f"read_if_needed contains deny-default path without read expansion log policy: {rel_path}")
        if entry.get("required") is True and not (root / rel_path).is_file():
            errors.append(f"required allowed_read missing on disk: {rel_path}")
    if "process/archive/**" not in denied_patterns and "process/archive/**" not in do_not_patterns:
        errors.append("do_not_read_by_default must include process/archive/**")

    if not context.get("state_ref"):
        errors.append("state_ref missing")
    if not context.get("cr_index_ref"):
        errors.append("cr_index_ref missing")
    index_path = _resolve_runtime_ref(root, str(context.get("cr_index_ref") or CR_INDEX_REL.as_posix()))
    if index_path.is_file():
        index_payload = _read_json(index_path)
        index_errors = validate_index_payload(index_payload)
        errors.extend(f"cr_index projection invalid: {error}" for error in index_errors)
        if not index_errors and context.get("cr_index_semantic_digest") != index_payload.get("semantic_digest"):
            errors.append("cr_index_semantic_digest does not match CR-INDEX.json")
    if context.get("cr_id") and not context.get("cr_summary_ref"):
        errors.append("cr_summary_ref missing for CR context")
    if not context.get("policy_refs"):
        errors.append("policy_refs missing")
    if not context.get("read_policy_ref"):
        errors.append("read_policy_ref missing")

    reasons = context.get("full_doc_read_allowed_when") or []
    if not isinstance(reasons, list) or not reasons:
        errors.append("full_doc_read_allowed_when must be a non-empty list")
    else:
        unknown = sorted(set(str(reason) for reason in reasons) - set(DEFAULT_FULL_DOC_READ_REASONS))
        if unknown:
            errors.append(f"unknown full_doc_read_allowed_when values: {', '.join(unknown)}")
    if not context.get("required_full_doc_read_log"):
        errors.append("required_full_doc_read_log missing")

    read_policy_ref = context.get("read_policy_ref")
    if read_policy_ref and not (root / str(read_policy_ref)).is_file():
        errors.append(f"read_policy_ref missing on disk: {read_policy_ref}")
    if context.get("cr_id") and context.get("cr_summary_ref"):
        summary_path = root / str(context["cr_summary_ref"])
        if not summary_path.is_file():
            errors.append(f"cr_summary_ref missing on disk: {context['cr_summary_ref']}")
    if str(context.get("stage") or "").upper() == "CP7" and context.get("cr_id"):
        cp2_required = _required_evidence_from_cp2(root, str(context["cr_id"]))
        if cp2_required and not must_verify:
            errors.append("CP7 context must include must_verify entries from CP2 required_evidence")

    if "process/STATE.md" not in denied_patterns:
        warnings.append("denied_default_reads does not include process/STATE.md")
    if "process/DEVELOPMENT-PLAN.yaml" not in denied_patterns:
        warnings.append("denied_default_reads does not include process/DEVELOPMENT-PLAN.yaml")
    if "process/current/CURRENT.json" not in [str(entry.get("path") or "") for entry in must_read if isinstance(entry, dict)]:
        warnings.append("must_read does not include process/current/CURRENT.json")
    warnings.extend(_capsule_redundancy_warnings(root, context))
    return errors, warnings


def explain_context_pack(context_path: Path) -> int:
    context = _load_context(context_path.resolve())
    budget = context.get("budget") or {}
    print("Context Pack:")
    print(f"- path: {context_path.resolve()}")
    print(f"- project_id: {context.get('project_id')}")
    print(f"- stage: {context.get('stage')}")
    print(f"- profile: {context.get('profile')}")
    print(f"- cr_id: {context.get('cr_id') or '-'}")
    print(f"- story_id: {context.get('story_id') or '-'}")
    print(f"- estimated_tokens: {budget.get('estimated_tokens')} / {budget.get('max_tokens')}")
    print("- allowed_reads:")
    for entry in context.get("allowed_reads") or []:
        print(f"  - {entry.get('path')} ({entry.get('estimated_tokens', 0)} tokens)")
    print("- denied_default_reads:")
    for pattern in context.get("denied_default_reads") or []:
        print(f"  - {pattern}")
    return 0


def _print_context_help() -> None:
    print(
        "usage: meta-flow context <command> [options]\n\n"
        "Commands:\n"
        "  build    Build a context-budgeted context pack.\n"
        "  check    Validate a context pack budget, read policy, and required refs.\n"
        "  explain  Print a compact explanation of a context pack.\n\n"
        "  build-story-packet    Build a Story Context Contract / Work Packet / Verify Packet.\n"
        "  check-story-packet    Validate a Story context packet.\n"
        "  sufficiency-check     Validate Story packet minimum sufficient context slots.\n"
        "  explain-story-packet  Print a compact explanation of a Story context packet.\n"
        "  read-log              Append a read expansion event to READ-EXPANSION-LEDGER.ndjson.\n"
        "  read-log-check        Validate read expansion ledger events.\n\n"
        "Examples:\n"
        "  meta-flow context build --stage CP6 --profile standard-code --cr CR-101 --project-root .\n"
        "  meta-flow context check --context process/context/CP6-CR101.context.json --project-root .\n"
        "  meta-flow context explain --context process/context/CP6-CR101.context.json\n"
        "  meta-flow context build-story-packet --story process/stories/STORY-CR123-S01.md --stage CP6 --project-root .\n"
    )


def main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if not args or args[0] in {"-h", "--help"}:
        _print_context_help()
        return 0
    command = args[0]
    if command in {
        "build-story-packet",
        "check-story-packet",
        "sufficiency-check",
        "explain-story-packet",
        "read-log",
        "read-log-check",
    }:
        from meta_flow.context_pack import story_contract

        return story_contract.main(args)
    if command == "build":
        parser = argparse.ArgumentParser(prog="meta-flow context build")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--stage", required=True)
        parser.add_argument("--profile", default="standard-code")
        parser.add_argument("--cr", dest="cr_id", default="")
        parser.add_argument("--story", dest="story_id", default="")
        parser.add_argument("--budget", type=int, default=None)
        parser.add_argument("--output", type=Path, default=None)
        parser.add_argument("--no-write-policy", action="store_true")
        parsed = parser.parse_args(args[1:])
        _context, path = build_context_pack(
            parsed.project_root,
            stage=parsed.stage,
            profile=parsed.profile,
            cr_id=parsed.cr_id,
            story_id=parsed.story_id,
            budget=parsed.budget,
            output=parsed.output,
            write_policy=not parsed.no_write_policy,
        )
        print(f"wrote: {path}")
        return 0
    if command == "check":
        parser = argparse.ArgumentParser(prog="meta-flow context check")
        parser.add_argument("--project-root", type=Path, default=None)
        parser.add_argument("--context", dest="context_path", type=Path, required=True)
        parsed = parser.parse_args(args[1:])
        errors, warnings = validate_context_pack(parsed.context_path, project_root=parsed.project_root)
        print("Context Pack Check: " + ("FAIL" if errors else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    if command == "explain":
        parser = argparse.ArgumentParser(prog="meta-flow context explain")
        parser.add_argument("--context", dest="context_path", type=Path, required=True)
        parsed = parser.parse_args(args[1:])
        return explain_context_pack(parsed.context_path)
    raise SystemExit(f"未知 context 命令: {command}. 目前支持: build, check, explain")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
