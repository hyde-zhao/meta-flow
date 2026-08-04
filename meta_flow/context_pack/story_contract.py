"""Story-level context contracts and work/verify packets."""

from __future__ import annotations

import argparse
import json
import sys
from fnmatch import fnmatch
from pathlib import Path, PureWindowsPath
from typing import Any

from meta_flow.checks.frozen_cp6_evidence import project_story_admission
from meta_flow.checks.token_budget import DEFAULT_READ_DENY_PATTERNS, estimate_tokens, load_budgets
from meta_flow.context_pack import read_expansion
from meta_flow.context_pack.builder import (
    DEFAULT_FULL_DOC_READ_REASONS,
    READ_EXPANSION_LEDGER_REL,
    READ_POLICY_REL,
    load_read_policy,
    write_default_read_policy,
)
from meta_flow.design.feature_registry import FEATURE_REGISTRY_REL
from meta_flow.design.module_boundaries import MODULE_BOUNDARIES_REL
from meta_flow.design.product_governance import (
    CAPABILITY_STATUS_REL,
    CONCEPT_OWNERS_REL,
    PACKAGE_IDENTITY_REL,
)
from meta_flow.policies.authz import AUTHZ_POLICY_REL
from meta_flow.policies.gate_profiles import GATE_PROFILES_REL
from meta_flow.project.process_route import _resolve_runtime_path, _resolve_runtime_ref
from meta_flow.project.scale import load_yaml_object
from meta_flow.state.current import (
    STATE_CURRENT_ENTRY_REL,
    STATE_CURRENT_REL,
    load_current_state,
    refresh_current_entry,
    validate_current_projection,
    validate_current_state_for_write,
)
from meta_flow.workflow.cr_lifecycle import CR_SUMMARY_ROOT_REL

STORY_CONTEXT_ROOT_REL = Path("process/context/stories")
STORY_RETURN_ROOT_REL = Path("process/returns")
DEVELOPMENT_PLAN_REL = Path("process/DEVELOPMENT-PLAN.yaml")
DEFAULT_STORY_BUDGET = 8000
STRICT_SUFFICIENCY_PROFILES = {"architecture-major", "product-redesign", "runtime-high-risk"}
SUFFICIENCY_REQUIRED_SLOTS = (
    "objective.summary",
    "feature_refs",
    "feature_context",
    "cr_delta.summary",
    "acceptance",
    "dependency_inputs",
    "allowed_write_paths",
    "forbidden_write_paths",
    "verification_plan",
    "authz_policy_refs",
    "expected_return_packet",
)
ALLOWED_PACKET_TYPES = {
    "story_context_contract",
    "story_work_packet",
    "story_verify_packet",
}
ALLOWED_STAGES = {"BASE", "CP5", "CP6", "CP7"}


def _frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return ""
    end = text.find("\n---", 4)
    if end == -1:
        return ""
    return text[4:end]


def _parse_scalar_or_list(value: str) -> str | list[str]:
    raw = value.strip().strip('"').strip("'")
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [item.strip().strip('"').strip("'") for item in inner.split(",") if item.strip()]
    return raw


def _parse_flat_yaml(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    current_key = ""
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("  - ") and current_key:
            data.setdefault(current_key, []).append(line.strip()[2:].strip().strip('"').strip("'"))
            continue
        if line.startswith("  ") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        current_key = key
        if value:
            data[key] = _parse_scalar_or_list(value)
        else:
            data[key] = []
    return data


def _read_json_or_yaml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.loads(text)
    frontmatter = _frontmatter(text)
    if frontmatter:
        return _parse_flat_yaml(frontmatter)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return _parse_flat_yaml(text)


def _as_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return [str(value)]


def _as_mapping_summary(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("summary") or "")
    return str(value or "")


def _rel(project_root: Path, path: Path) -> str:
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return path.as_posix()


def _runtime_output_path(project_root: Path, output: Path | None, default: Path) -> Path:
    """输出若是 process 逻辑引用，必须经 binding resolver，而非落入 release。"""

    return _resolve_runtime_path(project_root, output) if output is not None else default


def _canonical_runtime_ref(project_root: Path, path: Path) -> str:
    """将绑定过程仓的物理路径还原为可安全显示的 logical ref。"""

    root = project_root.resolve()
    resolved = path.resolve(strict=False)
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        process_root = _resolve_runtime_ref(root, "process/.meta-flow-process.yaml").parent
        return f"process/{resolved.relative_to(process_root.resolve()).as_posix()}"


def _path_tokens(project_root: Path, rel_path: str) -> int:
    path = _resolve_runtime_path(project_root, rel_path)
    if not path.is_file():
        return 0
    try:
        return estimate_tokens(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        return 0


def _read_entry(project_root: Path, rel_path: str, *, required: bool, reason: str) -> dict[str, Any]:
    return {
        "path": rel_path,
        "mode": "full",
        "estimated_tokens": _path_tokens(project_root, rel_path),
        "required": required,
        "reason": reason,
    }


def _append_unique(entries: list[dict[str, Any]], entry: dict[str, Any]) -> None:
    if any(existing.get("path") == entry.get("path") for existing in entries):
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


def _story_id_from_path(path: Path, data: dict[str, Any]) -> str:
    return str(data.get("story_id") or data.get("id") or path.stem)


def story_data_from_file(path: Path) -> dict[str, Any]:
    data = _read_json_or_yaml(path)
    data["story_id"] = _story_id_from_path(path, data)
    return data


def _markdown_section(text: str, heading: str) -> list[str]:
    """读取一个二级 Markdown 章节，避免调用方手工复制 Story 正文。"""

    lines = text.splitlines()
    start = next((index + 1 for index, line in enumerate(lines) if line.strip() == heading), None)
    if start is None:
        return []
    result: list[str] = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        result.append(line)
    return result


def _section_summary(text: str, heading: str) -> str:
    for line in _markdown_section(text, heading):
        stripped = line.strip()
        if stripped and not stripped.startswith(("#", "|", "-", "```")):
            return stripped
    return ""


def _section_bullets(text: str, heading: str) -> list[str]:
    return [
        line.strip()[2:].strip()
        for line in _markdown_section(text, heading)
        if line.strip().startswith("- ") and line.strip()[2:].strip()
    ]


def _development_plan_story(project_root: Path, story_id: str) -> dict[str, Any]:
    path = _resolve_runtime_ref(project_root, DEVELOPMENT_PLAN_REL.as_posix())
    if not path.is_file():
        return {}
    payload = load_yaml_object(path)
    matches = [
        story
        for wave in payload.get("waves", [])
        if isinstance(wave, dict)
        for story in wave.get("stories", [])
        if isinstance(story, dict) and str(story.get("story_id") or "") == story_id
    ]
    if len(matches) > 1:
        raise ValueError(f"duplicate Story in DEVELOPMENT-PLAN: {story_id}")
    return dict(matches[0]) if matches else {}


def _projected_story_contract(
    project_root: Path,
    *,
    story: dict[str, Any],
    story_text: str,
    story_id: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """从原生 DEVELOPMENT-PLAN 投影 packet 输入，不手工改 Story 派生状态。"""

    plan_story = _development_plan_story(project_root, story_id)
    if not plan_story:
        return story, None
    projected = dict(story)
    ownership = plan_story.get("file_ownership")
    ownership = ownership if isinstance(ownership, dict) else {}
    dependencies = plan_story.get("dependency_type")
    dependencies = dependencies if isinstance(dependencies, list) else []
    if not projected.get("feature_contract_summary"):
        projected["feature_contract_summary"] = _section_summary(story_text, "## 目标")
    if not projected.get("cr_delta_summary"):
        projected["cr_delta_summary"] = _section_summary(story_text, "## 目标")
    if not projected.get("dependency_inputs"):
        projected["dependency_inputs"] = [
            ":".join(
                part
                for part in (
                    str(item.get("upstream") or ""),
                    str(item.get("type") or ""),
                    str(item.get("gate") or ""),
                )
                if part
            )
            for item in dependencies
            if isinstance(item, dict)
        ] or ["ROOT: DEVELOPMENT-PLAN native gate"]
    if not projected.get("allowed_write_paths"):
        projected["allowed_write_paths"] = _as_list(ownership.get("primary")) + _as_list(
            ownership.get("shared")
        )
    if not projected.get("forbidden_write_paths"):
        projected["forbidden_write_paths"] = _as_list(ownership.get("forbidden"))
    if not projected.get("acceptance"):
        projected["acceptance"] = _section_bullets(story_text, "## 量化验收")
    if not projected.get("verification_plan"):
        output_files = _as_list(plan_story.get("output_files"))
        tests = [path for path in output_files if path.startswith("tests/")]
        python_files = [path for path in output_files if path.endswith(".py")]
        projected["verification_plan"] = [
            *(
                [
                    "uv run --frozen --no-sync --python 3.11 pytest -q "
                    + " ".join(tests)
                ]
                if tests
                else []
            ),
            *(
                [
                    "uv run --frozen --no-sync --python 3.11 ruff check --fix "
                    + " ".join(python_files),
                    "uv run --frozen --no-sync --python 3.11 python -m py_compile "
                    + " ".join(python_files),
                ]
                if python_files
                else []
            ),
            "git diff --check",
        ]
    if not projected.get("authz_policy_refs"):
        projected["authz_policy_refs"] = [AUTHZ_POLICY_REL.as_posix()]
    dev_gate = plan_story.get("dev_gate")
    projected_gate = (
        {
            "story_id": story_id,
            "status": str(plan_story.get("status") or ""),
            "dev_gate": dict(dev_gate),
        }
        if isinstance(dev_gate, dict)
        else None
    )
    return projected, projected_gate


def _story_output_path(project_root: Path, story_id: str, stage: str) -> Path:
    if stage == "BASE":
        return _resolve_runtime_ref(project_root, STORY_CONTEXT_ROOT_REL.as_posix()) / f"{story_id}.base.context.json"
    if stage == "CP6":
        return _resolve_runtime_ref(project_root, STORY_CONTEXT_ROOT_REL.as_posix()) / f"{story_id}.CP6.work-packet.json"
    if stage == "CP7":
        return _resolve_runtime_ref(project_root, STORY_CONTEXT_ROOT_REL.as_posix()) / f"{story_id}.CP7.verify-packet.json"
    return _resolve_runtime_ref(project_root, STORY_CONTEXT_ROOT_REL.as_posix()) / f"{story_id}.{stage}.context.json"


def _return_ref(story_id: str, stage: str) -> str:
    return (STORY_RETURN_ROOT_REL / f"{story_id}.{stage}.return.json").as_posix()


def _stage_budget(project_root: Path, stage: str, explicit_budget: int | None) -> int:
    if explicit_budget is not None:
        return explicit_budget
    budgets = load_budgets(project_root)
    context_budgets = budgets.get("context_pack", {})
    return int(context_budgets.get(stage, DEFAULT_STORY_BUDGET) or DEFAULT_STORY_BUDGET)


def _policy_refs() -> dict[str, str]:
    return {
        "read_policy": READ_POLICY_REL.as_posix(),
        "gate_profiles": GATE_PROFILES_REL.as_posix(),
        "authz_policy": AUTHZ_POLICY_REL.as_posix(),
    }


def _design_refs() -> dict[str, str]:
    return {
        "feature_registry": FEATURE_REGISTRY_REL.as_posix(),
        "module_boundaries": MODULE_BOUNDARIES_REL.as_posix(),
        "capability_status": CAPABILITY_STATUS_REL.as_posix(),
        "concept_owners": CONCEPT_OWNERS_REL.as_posix(),
        "package_identity": PACKAGE_IDENTITY_REL.as_posix(),
    }


def _load_runtime_state_contract(project_root: Path) -> tuple[dict[str, Any], bool]:
    """读取 Story packet 的状态契约，并区分合法缺失与非法漂移。"""

    state_path = _resolve_runtime_ref(project_root, STATE_CURRENT_REL.as_posix())
    entry_path = _resolve_runtime_ref(project_root, STATE_CURRENT_ENTRY_REL.as_posix())
    state_exists = state_path.is_file()
    entry_exists = entry_path.is_file()
    if not state_exists and not entry_exists:
        return {}, False
    if not state_exists:
        raise ValueError("runtime state contract is partial")

    state = load_current_state(project_root)
    if not state:
        raise ValueError("runtime state payload is empty or invalid")
    try:
        validate_current_state_for_write(state)
    except ValueError as exc:
        raise ValueError("runtime state payload is invalid") from exc

    refresh_current_entry(project_root)
    return state, True


def build_story_packet(
    project_root: Path,
    *,
    story_path: Path,
    stage: str,
    cr_id: str = "",
    budget: int | None = None,
    output: Path | None = None,
    parent_context_ref: str = "",
    cp6_return_ref: str = "",
    frozen_cp6_evidence: dict[str, Any] | None = None,
    expected_dependency_digests: dict[str, str] | None = None,
    write_policy: bool = True,
) -> tuple[dict[str, Any], Path]:
    project_root = project_root.resolve()
    stage = stage.upper()
    if stage not in ALLOWED_STAGES:
        raise ValueError(f"unsupported Story context stage: {stage}")
    story_input_ref = story_path.as_posix()
    story_path = _resolve_runtime_path(project_root, story_path)
    if not story_path.is_file():
        raise FileNotFoundError(f"Story file missing: {story_path}")
    if write_policy:
        write_default_read_policy(project_root)
    read_policy = load_read_policy(project_root)
    state, state_required = _load_runtime_state_contract(project_root)
    story = story_data_from_file(story_path)
    story_id = str(story["story_id"])
    effective_cr_id = cr_id or str(story.get("cr_id") or "")
    story_rel = (
        story_input_ref
        if not Path(story_input_ref).is_absolute() and story_input_ref.startswith("process/")
        else _rel(project_root, story_path)
    )
    lld_ref = story_rel.replace(".md", "-LLD.md")
    story, projected_gate = _projected_story_contract(
        project_root,
        story=story,
        story_text=story_path.read_text(encoding="utf-8"),
        story_id=story_id,
    )
    allowed_reads: list[dict[str, Any]] = []
    must_read: list[dict[str, Any]] = []
    read_if_needed: list[dict[str, Any]] = []

    state_reason = "runtime_state" if state_required else "runtime_state_legal_missing"
    current_reason = "current_discovery_entry" if state_required else "current_discovery_entry_legal_missing"
    _append_unique(
        allowed_reads,
        _read_entry(project_root, STATE_CURRENT_REL.as_posix(), required=state_required, reason=state_reason),
    )
    _append_unique(
        allowed_reads,
        _read_entry(
            project_root,
            STATE_CURRENT_ENTRY_REL.as_posix(),
            required=state_required,
            reason=current_reason,
        ),
    )
    _append_unique(allowed_reads, _read_entry(project_root, story_rel, required=True, reason="story_card"))
    _append_unique(allowed_reads, _read_entry(project_root, READ_POLICY_REL.as_posix(), required=True, reason="read_policy"))
    if state_required:
        _append_unique(
            must_read,
            _read_entry(project_root, STATE_CURRENT_REL.as_posix(), required=True, reason="machine_state"),
        )
        _append_unique(
            must_read,
            _read_entry(project_root, STATE_CURRENT_ENTRY_REL.as_posix(), required=True, reason="current_entrypoint"),
        )
    _append_unique(must_read, _read_entry(project_root, story_rel, required=True, reason="story_card"))
    _append_unique(must_read, _read_entry(project_root, READ_POLICY_REL.as_posix(), required=True, reason="read_policy"))
    if effective_cr_id:
        cr_summary = (CR_SUMMARY_ROOT_REL / f"{effective_cr_id}.summary.json").as_posix()
        _append_unique(allowed_reads, _read_entry(project_root, cr_summary, required=True, reason="cr_summary"))
    for rel_path, reason in (
        (FEATURE_REGISTRY_REL.as_posix(), "feature_registry"),
        (MODULE_BOUNDARIES_REL.as_posix(), "module_boundaries"),
        (GATE_PROFILES_REL.as_posix(), "gate_profiles"),
        (AUTHZ_POLICY_REL.as_posix(), "authz_policy"),
        (CAPABILITY_STATUS_REL.as_posix(), "capability_status"),
        (CONCEPT_OWNERS_REL.as_posix(), "concept_owners"),
        (PACKAGE_IDENTITY_REL.as_posix(), "package_identity"),
    ):
        if _resolve_runtime_path(project_root, rel_path).is_file():
            _append_unique(allowed_reads, _read_entry(project_root, rel_path, required=False, reason=reason))

    lld_policy = str(story.get("lld_policy") or story.get("required_level") or "")
    if lld_policy == "full-lld":
        read_if_needed.append(
            {
                "path": lld_ref,
                "mode": "full",
                # deny-default 目标在扩读授权前不得读取正文；授权后由 reader 计量。
                "estimated_tokens": 0,
                "trigger": "full_lld_required_by_policy",
                "reason": "story_lld",
            }
        )
    denied_patterns = list(
        read_policy.get("deny_default_reads") or DEFAULT_READ_DENY_PATTERNS
    )
    preregistration_refs = sorted(
        {
            str(entry.get("path") or "")
            for entry in read_if_needed
            if str(entry.get("trigger") or "")
            and _matches_any(str(entry.get("path") or ""), denied_patterns)
        }
    )
    pre_dispatch_actions = (
        [
            {
                "operation": "context.read-log",
                "input_contract": "ReadExpansionPlanV1",
                "actor": "host-orchestrator",
                "required_before": "story-dispatch",
                "requested_refs": preregistration_refs,
                "reason": "summary_insufficient",
                "reason_evidence": {"missing_slots": ["full_lld_body"]},
            }
        ]
        if preregistration_refs
        else []
    )

    estimated_tokens = sum(int(entry.get("estimated_tokens") or 0) for entry in allowed_reads)
    max_tokens = _stage_budget(project_root, stage if stage != "BASE" else "CP5", budget)
    packet_type = {
        "BASE": "story_context_contract",
        "CP5": "story_context_contract",
        "CP6": "story_work_packet",
        "CP7": "story_verify_packet",
    }[stage]
    parent_ref = parent_context_ref
    if stage in {"CP6", "CP7"} and not parent_ref:
        parent_ref = (STORY_CONTEXT_ROOT_REL / f"{story_id}.base.context.json").as_posix()
    packet: dict[str, Any] = {
        "schema_version": 2,
        "packet_type": packet_type,
        "stage": stage,
        "project_id": str(state.get("project_id") or project_root.name),
        "cr_id": effective_cr_id or None,
        "story_id": story_id,
        "story_ref": story_rel,
        "parent_context_ref": parent_ref or None,
        "objective": {
            "summary": str(story.get("objective") or story.get("title") or story_id),
            "non_goals": _as_list(story.get("non_goals")),
        },
        "feature_refs": _as_list(story.get("feature_refs") or story.get("affected_features")),
        "feature_design_refs": _as_list(story.get("feature_design_refs") or story.get("design_doc_refs")),
        "feature_contract_summary": str(
            story.get("feature_contract_summary")
            or story.get("feature_design_summary")
            or story.get("contract_summary")
            or ""
        ),
        "feature_design_summary_ref": str(story.get("feature_design_summary_ref") or story.get("design_summary_ref") or ""),
        "cr_delta": {
            "summary": str(story.get("cr_delta_summary") or story.get("design_delta_summary") or story.get("scope_delta") or ""),
            "affected_contracts": _as_list(story.get("affected_contracts") or story.get("contract_changes")),
        },
        "dependency_inputs": _as_list(story.get("dependency_inputs") or story.get("blocking_dependencies")),
        "lld_policy": lld_policy or None,
        "risk_profile": str(story.get("risk_profile") or ""),
        "must_read": must_read,
        "allowed_reads": allowed_reads,
        "read_if_needed": read_if_needed,
        "pre_dispatch_actions": pre_dispatch_actions,
        "do_not_read_by_default": _deny_default_entries(
            list(read_policy.get("deny_default_reads") or DEFAULT_READ_DENY_PATTERNS)
        ),
        "denied_default_reads": denied_patterns,
        "allowed_write_paths": _as_list(story.get("allowed_write_paths") or story.get("allowed_paths")),
        "forbidden_write_paths": _as_list(story.get("forbidden_write_paths") or story.get("forbidden_paths")),
        "acceptance": _as_list(story.get("acceptance") or story.get("acceptance_criteria")),
        "verification_plan": _as_list(story.get("verification_plan") or story.get("verification")),
        "authz_policy_refs": _as_list(story.get("authz_policy_refs")),
        "policy_refs": _policy_refs(),
        "design_refs": _design_refs(),
        "full_doc_read_allowed_when": list(read_policy.get("full_doc_read_allowed_when") or DEFAULT_FULL_DOC_READ_REASONS),
        "required_full_doc_read_log": str(read_policy.get("required_full_doc_read_log") or READ_EXPANSION_LEDGER_REL.as_posix()),
        "context_sufficiency": {
            "required_slots": list(SUFFICIENCY_REQUIRED_SLOTS),
            "strict_profiles": sorted(STRICT_SUFFICIENCY_PROFILES),
        },
        "budget": {
            "max_tokens": max_tokens,
            "estimated_tokens": estimated_tokens,
            "estimator": "chars_div_4",
        },
    }
    if stage == "CP6":
        packet["expected_return_packet"] = _return_ref(story_id, "CP6")
        packet["admission"] = project_story_admission(
            frozen_cp6_evidence,
            expected_dependency_digests=expected_dependency_digests or {},
            projected_gate=projected_gate,
        )
    if stage == "CP7":
        packet["implementation_return_ref"] = cp6_return_ref or _return_ref(story_id, "CP6")
        packet["expected_return_packet"] = _return_ref(story_id, "CP7")
    output_path = _runtime_output_path(project_root, output, _story_output_path(project_root, story_id, stage))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if state_required:
        refresh_current_entry(project_root)
        projection_findings = validate_current_projection(project_root)
        if projection_findings:
            codes = ",".join(sorted({finding.code for finding in projection_findings}))
            raise ValueError(f"runtime state projection is invalid: {codes}")
    return packet, output_path


def _matches_any(rel_path: str, patterns: list[str]) -> bool:
    return any(fnmatch(rel_path, pattern) for pattern in patterns)


def _load_packet(packet_path: Path) -> dict[str, Any]:
    return json.loads(packet_path.read_text(encoding="utf-8"))


def _absolute_path_locations(value: Any, *, location: str = "$") -> list[str]:
    if isinstance(value, dict):
        found: list[str] = []
        for key, item in value.items():
            found.extend(_absolute_path_locations(item, location=f"{location}.{key}"))
        return found
    if isinstance(value, list):
        found = []
        for index, item in enumerate(value):
            found.extend(_absolute_path_locations(item, location=f"{location}[{index}]"))
        return found
    if isinstance(value, str) and (Path(value).is_absolute() or PureWindowsPath(value).is_absolute()):
        return [location]
    return []


def validate_story_packet(packet_path: Path, *, project_root: Path | None = None) -> tuple[list[str], list[str]]:
    root = project_root.resolve() if project_root else _infer_project_root(packet_path)
    packet_path = _resolve_runtime_path(root, packet_path)
    if not packet_path.is_file():
        return ["Story packet missing"], []
    packet = _load_packet(packet_path)
    errors: list[str] = []
    warnings: list[str] = []
    absolute_locations = _absolute_path_locations(packet)
    if absolute_locations:
        errors.append("Story packet contains absolute path values at: " + ", ".join(absolute_locations))
    packet_schema_version = packet.get("schema_version")
    if packet_schema_version not in {1, 2}:
        errors.append("schema_version must be 1 or 2")
    if packet.get("packet_type") not in ALLOWED_PACKET_TYPES:
        errors.append(f"invalid packet_type: {packet.get('packet_type')}")
    if packet.get("stage") not in ALLOWED_STAGES:
        errors.append(f"invalid stage: {packet.get('stage')}")
    for key in (
        "story_id",
        "story_ref",
        "feature_refs",
        "feature_design_refs",
        "must_read",
        "allowed_reads",
        "do_not_read_by_default",
        "denied_default_reads",
    ):
        if key not in packet:
            errors.append(f"missing required field: {key}")
    budget = packet.get("budget") or {}
    max_tokens = int(budget.get("max_tokens") or 0)
    estimated_tokens = int(budget.get("estimated_tokens") or 0)
    if max_tokens <= 0:
        errors.append("budget.max_tokens must be positive")
    if estimated_tokens > max_tokens:
        errors.append(f"estimated_tokens exceeds budget: {estimated_tokens} > {max_tokens}")
    denied = list(packet.get("denied_default_reads") or DEFAULT_READ_DENY_PATTERNS)
    must_read = packet.get("must_read") or []
    if not isinstance(must_read, list) or not must_read:
        errors.append("must_read must be a non-empty list")
        must_read = []
    do_not_read_by_default = packet.get("do_not_read_by_default") or []
    if not isinstance(do_not_read_by_default, list) or not do_not_read_by_default:
        errors.append("do_not_read_by_default must be a non-empty list")
    do_not_patterns = [
        str(entry.get("path_or_pattern") or entry.get("path") or "")
        for entry in do_not_read_by_default
        if isinstance(entry, dict)
    ]
    allowed_reads = packet.get("allowed_reads") or []
    if not isinstance(allowed_reads, list) or not allowed_reads:
        errors.append("allowed_reads must be a non-empty list")
        allowed_reads = []
    for entry in [*must_read, *allowed_reads]:
        if not isinstance(entry, dict):
            errors.append("allowed_reads entries must be objects")
            continue
        rel_path = str(entry.get("path") or "")
        if not rel_path:
            errors.append("allowed_reads entry missing path")
            continue
        if _matches_any(rel_path, denied):
            errors.append(f"allowed_reads contains deny-default path: {rel_path}")
        if entry.get("required") is True and not _resolve_runtime_path(root, rel_path).is_file():
            errors.append(f"required allowed_read missing on disk: {rel_path}")
    preregistration_refs: list[str] = []
    for entry in packet.get("read_if_needed") or []:
        if not isinstance(entry, dict):
            errors.append("read_if_needed entries must be objects")
            continue
        rel_path = str(entry.get("path") or "")
        if not rel_path:
            errors.append("read_if_needed entry missing path")
            continue
        # A full LLD remains deny-default; it may appear only as an explicit
        # on-demand read, never as a default allowed read.  The caller must
        # still write a read-expansion event when it is actually expanded.
        if _matches_any(rel_path, denied) and not str(entry.get("trigger") or ""):
            errors.append(f"read_if_needed deny-default path lacks explicit trigger: {rel_path}")
        elif _matches_any(rel_path, denied):
            preregistration_refs.append(rel_path)
    actions = packet.get("pre_dispatch_actions") or []
    if preregistration_refs and packet_schema_version == 1:
        warnings.append(
            "schema_version=1 packet has no machine-enforced Host pre_dispatch_action; "
            "regenerate before the next Story dispatch"
        )
    elif preregistration_refs:
        if not isinstance(actions, list) or len(actions) != 1:
            errors.append(
                "deny-default read_if_needed requires exactly one Host pre_dispatch_action"
            )
        elif not isinstance(actions[0], dict):
            errors.append("pre_dispatch_actions entries must be objects")
        else:
            action = actions[0]
            expected_fields = read_expansion.PREREGISTRATION_ACTION_FIELDS
            if set(action) != expected_fields:
                errors.append("Host pre_dispatch_action fields must match ReadExpansionPlanV1")
            if action.get("operation") != "context.read-log":
                errors.append("Host pre_dispatch_action operation must be context.read-log")
            if action.get("input_contract") != "ReadExpansionPlanV1":
                errors.append("Host pre_dispatch_action input_contract must be ReadExpansionPlanV1")
            if action.get("actor") != "host-orchestrator":
                errors.append("Host pre_dispatch_action actor must be host-orchestrator")
            if action.get("required_before") != "story-dispatch":
                errors.append("Host pre_dispatch_action must run before story-dispatch")
            action_refs = sorted(str(item) for item in action.get("requested_refs") or [])
            if action_refs != sorted(set(preregistration_refs)):
                errors.append("Host pre_dispatch_action requested_refs mismatch read_if_needed")
            if action.get("reason") not in (
                packet.get("full_doc_read_allowed_when") or []
            ):
                errors.append("Host pre_dispatch_action reason is not allowed by read policy")
            reason_errors = read_expansion.validate_reason_evidence(
                str(action.get("reason") or ""),
                action.get("reason_evidence"),
            )
            errors.extend(
                f"Host pre_dispatch_action {error}" for error in reason_errors
            )
    elif actions:
        errors.append("pre_dispatch_actions must be empty without deny-default read_if_needed")
    if "process/archive/**" not in denied and "process/archive/**" not in do_not_patterns:
        errors.append("do_not_read_by_default must include process/archive/**")
    if packet.get("stage") in {"CP6", "CP7"} and not packet.get("parent_context_ref"):
        errors.append("parent_context_ref is required for CP6/CP7 story packets")
    if packet.get("stage") == "CP6" and not packet.get("expected_return_packet"):
        errors.append("expected_return_packet is required for CP6 story packets")
    if packet.get("stage") == "CP7":
        if not packet.get("implementation_return_ref"):
            errors.append("implementation_return_ref is required for CP7 story packets")
        if not packet.get("expected_return_packet"):
            errors.append("expected_return_packet is required for CP7 story packets")
    if not packet.get("allowed_write_paths"):
        errors.append("allowed_write_paths must be non-empty")
    if not packet.get("forbidden_write_paths"):
        warnings.append("forbidden_write_paths is empty")
    if not packet.get("acceptance"):
        errors.append("acceptance must be non-empty")
    if not packet.get("verification_plan"):
        errors.append("verification_plan must be non-empty")
    if not packet.get("lld_policy"):
        errors.append("lld_policy missing")
    if not packet.get("feature_refs"):
        errors.append("feature_refs must be non-empty")
    if not packet.get("feature_design_refs"):
        errors.append("feature_design_refs must be non-empty")
    sufficiency_errors, sufficiency_warnings = validate_context_sufficiency(packet)
    errors.extend(sufficiency_errors)
    warnings.extend(sufficiency_warnings)
    reasons = packet.get("full_doc_read_allowed_when") or []
    unknown_reasons = sorted(set(str(reason) for reason in reasons) - set(DEFAULT_FULL_DOC_READ_REASONS))
    if not reasons:
        errors.append("full_doc_read_allowed_when must be non-empty")
    elif unknown_reasons:
        errors.append(f"unknown full_doc_read_allowed_when values: {', '.join(unknown_reasons)}")
    return errors, warnings


def validate_context_sufficiency(packet: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Check whether a Story packet is small but still sufficient to execute."""

    errors: list[str] = []
    warnings: list[str] = []
    missing: list[str] = []
    risk_profile = str(packet.get("risk_profile") or "")
    stage = str(packet.get("stage") or "")
    strict = risk_profile in STRICT_SUFFICIENCY_PROFILES

    objective = packet.get("objective") or {}
    if not isinstance(objective, dict) or not str(objective.get("summary") or "").strip():
        missing.append("objective.summary")
    if not packet.get("feature_refs"):
        missing.append("feature_refs")
    if not (
        str(packet.get("feature_contract_summary") or "").strip()
        or str(packet.get("feature_design_summary_ref") or "").strip()
        or packet.get("feature_design_refs")
    ):
        missing.append("feature_context")
    elif not (str(packet.get("feature_contract_summary") or "").strip() or str(packet.get("feature_design_summary_ref") or "").strip()):
        warnings.append("context_sufficiency: feature_context uses full design refs only; add feature_contract_summary or feature_design_summary_ref")

    cr_delta = packet.get("cr_delta") or {}
    if not isinstance(cr_delta, dict) or not _as_mapping_summary(cr_delta).strip():
        missing.append("cr_delta.summary")
    if not packet.get("acceptance"):
        missing.append("acceptance")
    if not packet.get("dependency_inputs"):
        missing.append("dependency_inputs")
    if not packet.get("allowed_write_paths"):
        missing.append("allowed_write_paths")
    if not packet.get("forbidden_write_paths"):
        missing.append("forbidden_write_paths")
    if not packet.get("verification_plan"):
        missing.append("verification_plan")
    if not packet.get("authz_policy_refs"):
        missing.append("authz_policy_refs")
    if stage in {"CP6", "CP7"} and not packet.get("expected_return_packet"):
        missing.append("expected_return_packet")

    if missing:
        message = "context_sufficiency missing required slots: " + ", ".join(sorted(set(missing)))
        if strict:
            errors.append(message)
        else:
            warnings.append(message)
    return errors, warnings


def _infer_project_root(packet_path: Path) -> Path:
    for parent in packet_path.parents:
        if parent.name == "process":
            return parent.parent
    if len(packet_path.parents) >= 3:
        return packet_path.parents[2]
    return Path.cwd()


def explain_story_packet(packet_path: Path, *, project_root: Path | None = None) -> int:
    root = project_root.resolve() if project_root else _infer_project_root(packet_path)
    resolved_packet = _resolve_runtime_path(root, packet_path)
    if not resolved_packet.is_file():
        print("Story Context Packet: BLOCKED")
        print("- reason: packet missing")
        return 2
    packet = _load_packet(resolved_packet)
    budget = packet.get("budget") or {}
    print("Story Context Packet:")
    print(f"- path: {_canonical_runtime_ref(root, resolved_packet)}")
    print(f"- packet_type: {packet.get('packet_type')}")
    print(f"- stage: {packet.get('stage')}")
    print(f"- story_id: {packet.get('story_id')}")
    print(f"- cr_id: {packet.get('cr_id') or '-'}")
    print(f"- feature_refs: {', '.join(packet.get('feature_refs') or []) or '-'}")
    print(f"- estimated_tokens: {budget.get('estimated_tokens')} / {budget.get('max_tokens')}")
    print("- allowed_reads:")
    for entry in packet.get("allowed_reads") or []:
        print(f"  - {entry.get('path')} ({entry.get('estimated_tokens', 0)} tokens)")
    return 0


def check_sufficiency(packet_path: Path, *, project_root: Path | None = None) -> int:
    root = project_root.resolve() if project_root else _infer_project_root(packet_path)
    packet = _load_packet(_resolve_runtime_path(root, packet_path))
    errors, warnings = validate_context_sufficiency(packet)
    print("Context Sufficiency Check: " + ("FAIL" if errors else "OK"))
    for warning in warnings:
        print(f"- WARN: {warning}")
    for error in errors:
        print(f"- ERROR: {error}")
    return 1 if errors else 0


def main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if not args or args[0] in {"-h", "--help"}:
        print(
            "usage: meta-flow context <build-story-packet|check-story-packet|sufficiency-check|explain-story-packet|read-log|read-log-check> [options]\n\n"
            "Examples:\n"
            "  meta-flow context build-story-packet --story process/stories/STORY-CR123-S01.md --stage CP6 --project-root .\n"
            "  meta-flow context check-story-packet --packet process/context/stories/STORY-CR123-S01.CP6.work-packet.json --project-root .\n"
        )
        return 0
    command = args[0]
    if command == "build-story-packet":
        parser = argparse.ArgumentParser(prog="meta-flow context build-story-packet")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--story", dest="story_path", type=Path, required=True)
        parser.add_argument("--stage", required=True, choices=sorted(ALLOWED_STAGES))
        parser.add_argument("--cr", dest="cr_id", default="")
        parser.add_argument("--budget", type=int, default=None)
        parser.add_argument("--output", type=Path, default=None)
        parser.add_argument("--parent-context-ref", default="")
        parser.add_argument("--cp6-return-ref", default="")
        parser.add_argument("--no-write-policy", action="store_true")
        parsed = parser.parse_args(args[1:])
        _packet, path = build_story_packet(
            parsed.project_root,
            story_path=parsed.story_path,
            stage=parsed.stage,
            cr_id=parsed.cr_id,
            budget=parsed.budget,
            output=parsed.output,
            parent_context_ref=parsed.parent_context_ref,
            cp6_return_ref=parsed.cp6_return_ref,
            write_policy=not parsed.no_write_policy,
        )
        print(f"wrote: {_canonical_runtime_ref(parsed.project_root, path)}")
        return 0
    if command == "check-story-packet":
        parser = argparse.ArgumentParser(prog="meta-flow context check-story-packet")
        parser.add_argument("--project-root", type=Path, default=None)
        parser.add_argument("--packet", dest="packet_path", type=Path, required=True)
        parsed = parser.parse_args(args[1:])
        errors, warnings = validate_story_packet(parsed.packet_path, project_root=parsed.project_root)
        print("Story Context Packet Check: " + ("FAIL" if errors else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    if command == "sufficiency-check":
        parser = argparse.ArgumentParser(prog="meta-flow context sufficiency-check")
        parser.add_argument("--project-root", type=Path, default=None)
        parser.add_argument("--packet", dest="packet_path", type=Path, required=True)
        parsed = parser.parse_args(args[1:])
        return check_sufficiency(parsed.packet_path, project_root=parsed.project_root)
    if command == "explain-story-packet":
        parser = argparse.ArgumentParser(prog="meta-flow context explain-story-packet")
        parser.add_argument("--project-root", type=Path, default=None)
        parser.add_argument("--packet", dest="packet_path", type=Path, required=True)
        parsed = parser.parse_args(args[1:])
        return explain_story_packet(parsed.packet_path, project_root=parsed.project_root)
    if command in {"read-log", "read-log-check"}:
        return read_expansion.main(args)
    raise SystemExit(f"未知 story context 命令: {command}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
