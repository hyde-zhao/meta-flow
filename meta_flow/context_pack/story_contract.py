"""Story-level context contracts and work/verify packets."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Mapping
from fnmatch import fnmatch
from pathlib import Path, PureWindowsPath
from typing import Any

from meta_flow.checks.frozen_cp6_evidence import (
    Cp6RevalidationAuthorizationV1,
    FrozenCp6EvidenceError,
    project_story_admission,
)
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
from meta_flow.design.lightweight_design import (
    ScopeGoalNoteV1,
    extract_scope_goal_note_from_story,
)
from meta_flow.design.module_boundaries import MODULE_BOUNDARIES_REL
from meta_flow.design.product_governance import (
    CAPABILITY_STATUS_REL,
    CONCEPT_OWNERS_REL,
    PACKAGE_IDENTITY_REL,
)
from meta_flow.policies.authz import AUTHZ_POLICY_REL
from meta_flow.policies.gate_profiles import GATE_PROFILES_REL
from meta_flow.project.onboarding_contract import canonical_digest
from meta_flow.project.process_route import (
    _resolve_runtime_path,
    _resolve_runtime_ref,
    format_runtime_ref,
)
from meta_flow.project.scale import _parse_yaml_lines, _strip_comment, load_yaml_object
from meta_flow.semantics import preregistration
from meta_flow.state.current import (
    STATE_CURRENT_ENTRY_REL,
    STATE_CURRENT_REL,
    load_current_state,
    refresh_current_entry,
    validate_current_projection,
    validate_current_state_for_write,
)
from meta_flow.work.governance_profile import (
    GovernanceProfileBindingV2,
    effective_governance_profile,
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
_CANONICAL_DEV_GATE_FIELDS = (
    "cp5_confirmed",
    "dependencies_satisfied",
    "file_conflict_free",
    "implementation_authorized",
    "lld_confirmed",
)
_PRODUCTION_PATH_CONTRACT_FIELDS = {
    "schema_version",
    "story_id",
    "work_id",
    "feature_design_refs",
    "lld_ref",
    "production_entrypoints",
    "reachable_core_paths",
    "public_operation_ids",
    "mutation_mode",
    "authorization_refs",
    "receipt_refs",
    "zero_write_proof_refs",
    "targeted_test_refs",
    "negative_test_refs",
    "compatibility_test_refs",
    "output_evidence_contract",
    "file_ownership_digest",
    "contract_digest",
}
_PRODUCTION_PATH_DECLARATION_FIELDS = {
    "schema_version",
    "production_entrypoints",
    "reachable_core_paths",
    "public_operation_ids",
    "mutation_mode",
    "authorization_refs",
    "receipt_refs",
    "zero_write_proof_refs",
    "targeted_test_refs",
    "negative_test_refs",
    "compatibility_test_refs",
    "output_evidence_contract",
}
_NON_PRODUCTION_PATH_PARTS = {
    "__pycache__",
    "doc",
    "docs",
    "fixture",
    "fixtures",
    "helper",
    "helpers",
    "template",
    "templates",
    "test",
    "tests",
}


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


def _parse_story_frontmatter(text: str) -> dict[str, Any]:
    """只解析 StoryCard frontmatter；通用 YAML loader 的契约不在此处扩展。"""

    frontmatter = _frontmatter(text)
    if not frontmatter:
        return {}
    prepared: list[tuple[int, str]] = []
    for raw_line in frontmatter.splitlines():
        line = _strip_comment(raw_line).rstrip()
        if line.strip():
            prepared.append((len(line) - len(line.lstrip(" ")), line.strip()))
    if not prepared:
        return {}
    try:
        data, index = _parse_yaml_lines(prepared, 0, prepared[0][0])
    except (ValueError, IndexError) as exc:
        raise ValueError("Story frontmatter is not a supported mapping") from exc
    if index != len(prepared) or not isinstance(data, dict):
        raise ValueError("Story frontmatter is not a supported mapping")
    return data


def _as_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return [str(value)]


def _strict_string_list(value: Any, *, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"canonical Story {field} must be a list of non-empty strings")
    return value


def _stable_unique(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _canonical_string_list(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, str) or not item.strip() or item != item.strip()
        for item in value
    ):
        raise ValueError(f"ProductionPathContractV1 {field} must be a string list")
    return sorted(set(value))


def _is_production_python_path(value: str) -> bool:
    if (
        not value.endswith(".py")
        or value.startswith("/")
        or "\\" in value
        or "://" in value
    ):
        return False
    parts = value.split("/")
    return bool(parts) and all(
        part not in {"", ".", ".."} and part.lower() not in _NON_PRODUCTION_PATH_PARTS
        for part in parts
    )


def validate_production_path_contract(
    contract: Mapping[str, Any],
    *,
    ownership_primary: tuple[str, ...] | list[str] = (),
    registry_operations: tuple[str, ...] | list[str] | set[str] | None = None,
) -> tuple[str, ...]:
    """校验 closed production-path 合同；错误码供 CP6 直接 fail-closed。"""

    errors: list[str] = []
    if set(contract) != _PRODUCTION_PATH_CONTRACT_FIELDS:
        return ("PRODUCTION_CONTRACT_FIELDS_MISMATCH",)
    if contract.get("schema_version") != 1:
        errors.append("PRODUCTION_CONTRACT_SCHEMA_INVALID")
    for field in ("story_id", "work_id", "lld_ref", "output_evidence_contract"):
        value = contract.get(field)
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            errors.append(f"PRODUCTION_CONTRACT_{field.upper()}_INVALID")
    list_fields = (
        "feature_design_refs",
        "production_entrypoints",
        "reachable_core_paths",
        "public_operation_ids",
        "authorization_refs",
        "receipt_refs",
        "zero_write_proof_refs",
        "targeted_test_refs",
        "negative_test_refs",
        "compatibility_test_refs",
    )
    normalized_lists: dict[str, list[str]] = {}
    for field in list_fields:
        value = contract.get(field)
        if (
            not isinstance(value, list)
            or any(not isinstance(item, str) or not item for item in value)
            or value != sorted(set(value))
        ):
            errors.append(f"PRODUCTION_CONTRACT_{field.upper()}_INVALID")
            normalized_lists[field] = []
        else:
            normalized_lists[field] = value

    entrypoints = normalized_lists["production_entrypoints"]
    core_paths = normalized_lists["reachable_core_paths"]
    if not entrypoints or not core_paths or any(
        not _is_production_python_path(path) for path in (*entrypoints, *core_paths)
    ):
        errors.append("PRODUCTION_PATH_UNREACHABLE")
    primary = set(ownership_primary)
    if primary and not primary.intersection(core_paths):
        errors.append("PRODUCTION_CORE_OUTSIDE_PRIMARY_OWNERSHIP")

    if not all(
        normalized_lists[field]
        for field in ("targeted_test_refs", "negative_test_refs", "compatibility_test_refs")
    ):
        errors.append("PRODUCTION_TEST_EVIDENCE_MISSING")
    mutation_mode = contract.get("mutation_mode")
    if mutation_mode == "mutating":
        if not normalized_lists["authorization_refs"]:
            errors.append("MUTATION_AUTHORIZATION_MISSING")
        if not normalized_lists["receipt_refs"]:
            errors.append("MUTATION_RECEIPT_MISSING")
    elif mutation_mode == "zero-write":
        if not normalized_lists["zero_write_proof_refs"]:
            errors.append("ZERO_WRITE_PROOF_MISSING")
    else:
        errors.append("PRODUCTION_MUTATION_MODE_INVALID")

    operation_ids = normalized_lists["public_operation_ids"]
    if registry_operations is not None:
        registered = set(registry_operations)
        if any(operation_id not in registered for operation_id in operation_ids):
            errors.append("PUBLIC_OPERATION_UNREGISTERED")
    if any(not re.fullmatch(r"[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)+", item) for item in operation_ids):
        errors.append("PUBLIC_OPERATION_ID_INVALID")

    ownership_digest = contract.get("file_ownership_digest")
    if not isinstance(ownership_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", ownership_digest):
        errors.append("OWNERSHIP_DIGEST_INVALID")
    contract_digest = contract.get("contract_digest")
    if not isinstance(contract_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", contract_digest):
        errors.append("CONTRACT_DIGEST_INVALID")
    else:
        expected = canonical_digest(
            {key: value for key, value in contract.items() if key != "contract_digest"}
        )
        if contract_digest != expected:
            errors.append("CONTRACT_DIGEST_MISMATCH")
    return tuple(sorted(set(errors)))


def build_production_path_contract(
    story: Mapping[str, Any],
    *,
    ownership_digest: str,
    registry_operations: tuple[str, ...] | list[str] | set[str] | None = None,
) -> dict[str, Any]:
    """从 Story 声明与 native ownership 构造稳定的 ProductionPathContractV1。"""

    declaration = story.get("production_contract")
    if not isinstance(declaration, Mapping):
        raise ValueError("PRODUCTION_CONTRACT_MISSING")
    if set(declaration) != _PRODUCTION_PATH_DECLARATION_FIELDS:
        raise ValueError("PRODUCTION_CONTRACT_DECLARATION_FIELDS_MISMATCH")
    ownership = story.get("file_ownership")
    ownership = ownership if isinstance(ownership, Mapping) else {}
    lld_gate = story.get("lld_gate")
    lld_gate = lld_gate if isinstance(lld_gate, Mapping) else {}
    contract: dict[str, Any] = {
        "schema_version": declaration.get("schema_version"),
        "story_id": str(story.get("story_id") or ""),
        "work_id": str(story.get("work_id") or ""),
        "feature_design_refs": _canonical_string_list(
            story.get("feature_design_refs"), field="feature_design_refs"
        ),
        "lld_ref": str(lld_gate.get("evidence_ref") or ""),
        "production_entrypoints": _canonical_string_list(
            declaration.get("production_entrypoints"), field="production_entrypoints"
        ),
        "reachable_core_paths": _canonical_string_list(
            declaration.get("reachable_core_paths"), field="reachable_core_paths"
        ),
        "public_operation_ids": _canonical_string_list(
            declaration.get("public_operation_ids"), field="public_operation_ids"
        ),
        "mutation_mode": str(declaration.get("mutation_mode") or ""),
        "authorization_refs": _canonical_string_list(
            declaration.get("authorization_refs"), field="authorization_refs"
        ),
        "receipt_refs": _canonical_string_list(
            declaration.get("receipt_refs"), field="receipt_refs"
        ),
        "zero_write_proof_refs": _canonical_string_list(
            declaration.get("zero_write_proof_refs"), field="zero_write_proof_refs"
        ),
        "targeted_test_refs": _canonical_string_list(
            declaration.get("targeted_test_refs"), field="targeted_test_refs"
        ),
        "negative_test_refs": _canonical_string_list(
            declaration.get("negative_test_refs"), field="negative_test_refs"
        ),
        "compatibility_test_refs": _canonical_string_list(
            declaration.get("compatibility_test_refs"), field="compatibility_test_refs"
        ),
        "output_evidence_contract": str(declaration.get("output_evidence_contract") or ""),
        "file_ownership_digest": ownership_digest,
    }
    contract["contract_digest"] = canonical_digest(contract)
    errors = validate_production_path_contract(
        contract,
        ownership_primary=_as_list(ownership.get("primary")),
        registry_operations=registry_operations,
    )
    if errors:
        raise ValueError(",".join(errors))
    return contract


def _as_mapping_summary(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("summary") or "")
    return str(value or "")


def _runtime_output_path(project_root: Path, output: Path | None, default: Path) -> Path:
    """输出若是 process 逻辑引用，必须经 binding resolver，而非落入 release。"""

    return _resolve_runtime_path(project_root, output) if output is not None else default


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
    text = path.read_text(encoding="utf-8")
    data = _parse_story_frontmatter(text) if _frontmatter(text) else _read_json_or_yaml(path)
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


_ACCEPTANCE_HEADING_ALIASES: tuple[str, ...] = (
    "## 5. acceptance_criteria",
    "## 量化验收",
    "## 验收标准",
    "## acceptance",
)


def _acceptance_section_items(text: str) -> list[str]:
    """CHE-074-CP7：acceptance 标题多形态兼容抽取（编号项或项目符号）。"""

    for heading in _ACCEPTANCE_HEADING_ALIASES:
        items = _section_list_items(text=text, heading=heading)
        if items:
            return items
    return []


def _legacy_acceptance_heading_items(text: str) -> dict[str, list[str]]:
    """CR-075 V5：canonical 存在时逐个 legacy synonym 提取，供冲突检查消费。

    不得复用 _acceptance_section_items 的"首个非空即返回"语义：canonical 排在
    alias 首位，复用会让 legacy heading 永远读不到，冲突检查形同虚设（S01 回归）。
    """

    return {
        heading: _section_list_items(text=text, heading=heading)
        for heading in _ACCEPTANCE_HEADING_ALIASES[1:]
    }


def _section_bullets(text: str, heading: str) -> list[str]:
    return [
        line.strip()[2:].strip()
        for line in _markdown_section(text, heading)
        if line.strip().startswith("- ") and line.strip()[2:].strip()
    ]


def _section_list_items(text: str, heading: str) -> list[str]:
    """读取 canonical acceptance 的编号项或项目符号，保留其书写顺序。"""

    items: list[str] = []
    for line in _markdown_section(text, heading):
        stripped = line.strip()
        match = re.match(r"(?:[-*]|\d+[.)])\s+(.+)$", stripped)
        if match and match.group(1).strip():
            items.append(match.group(1).strip())
    return items


def _canonical_story_present(story: dict[str, Any]) -> bool:
    return "feature_id" in story or isinstance(story.get("lld_policy"), dict)


def _optional_formal_identity(value: Any, *, field: str) -> str:
    if value is None or value == "":
        return ""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Story {field} must be a non-empty string")
    return value


def _resolve_formal_cr_identity(story: dict[str, Any], *, explicit_cr_id: str) -> str:
    """解析 packet 的 formal CR identity，并拒绝 caller/card 双写漂移。"""

    explicit = _optional_formal_identity(explicit_cr_id, field="explicit --cr")
    legacy = _optional_formal_identity(story.get("cr_id"), field="cr_id")
    if not _canonical_story_present(story):
        if explicit and legacy and explicit != legacy:
            raise ValueError("explicit --cr and legacy cr_id conflict")
        return explicit or legacy
    raw_canonical = story.get("change_id")
    if not isinstance(raw_canonical, str) or not raw_canonical.strip():
        raise ValueError("canonical Story change_id must be a non-empty string")
    canonical = raw_canonical
    for name, value in (("explicit --cr", explicit), ("legacy cr_id", legacy)):
        if value and value != canonical:
            raise ValueError(f"canonical change_id and {name} conflict")
    return canonical


def _normalize_story_card_v1(story: dict[str, Any], story_text: str) -> dict[str, Any]:
    """将已知 StoryCard V1 字段映射为 packet producer 的受限输入。"""

    if not _canonical_story_present(story):
        return dict(story)
    normalized = dict(story)
    lld_policy = story.get("lld_policy")
    if not isinstance(lld_policy, dict):  # 防御性分支，保持此函数的 fail-closed 契约。
        raise ValueError("canonical Story lld_policy must be a mapping")
    required_level = lld_policy.get("required_level")
    if not isinstance(required_level, str) or not required_level:
        raise ValueError("canonical Story lld_policy.required_level must be a non-empty string")
    feature_id = story.get("feature_id")
    if not isinstance(feature_id, str) or not feature_id:
        raise ValueError("canonical Story feature_id must be a non-empty string")
    explicit_feature_refs = _strict_string_list(story.get("feature_refs"), field="feature_refs")
    design_refs = _strict_string_list(story.get("feature_design_refs"), field="feature_design_refs")
    canonical_acceptance = _section_list_items(text=story_text, heading="## 5. acceptance_criteria")
    if not canonical_acceptance:
        raise ValueError("canonical Story acceptance_criteria must contain at least one list item")
    legacy_acceptance_sources: dict[str, list[str]] = {
        "acceptance": _strict_string_list(story.get("acceptance"), field="acceptance"),
        "acceptance_criteria": _strict_string_list(
            story.get("acceptance_criteria"), field="acceptance_criteria"
        ),
    }
    # CR-075 V5：legacy heading 逐 alias 检查，canonical 与任一 legacy synonym 并存且不等即冲突。
    for heading, items in _legacy_acceptance_heading_items(story_text).items():
        source = f"legacy_heading[{heading}]"
        legacy_acceptance_sources[source] = items
    for source, values in legacy_acceptance_sources.items():
        if values and values != canonical_acceptance:
            raise ValueError(f"canonical and legacy Story acceptance conflict: {source}")
    explicit_delta = story.get("cr_delta_summary")
    if explicit_delta is not None and (not isinstance(explicit_delta, str) or not explicit_delta):
        raise ValueError("canonical Story cr_delta_summary must be a non-empty string")
    change_id = story.get("change_id")
    title = story.get("title")
    if not explicit_delta and (not isinstance(change_id, str) or not change_id or not isinstance(title, str) or not title):
        raise ValueError("canonical Story requires change_id and title for deterministic CR delta")
    normalized["lld_policy"] = required_level
    normalized["feature_refs"] = _stable_unique([feature_id, *explicit_feature_refs])
    normalized["feature_design_refs"] = design_refs
    normalized["acceptance"] = canonical_acceptance
    normalized["cr_delta_summary"] = explicit_delta or f"{change_id}: {title}"
    normalized["cr_id"] = _resolve_formal_cr_identity(story, explicit_cr_id="")
    return normalized


def _project_admission_gate(dev_gate: Any) -> dict[str, bool]:
    """白名单投影 native plan 的准入字段，保留原 plan provenance 不变。"""

    if not isinstance(dev_gate, dict):
        raise ValueError("native plan dev_gate must be a mapping")
    projected: dict[str, bool] = {}
    for field in _CANONICAL_DEV_GATE_FIELDS:
        value = dev_gate.get(field)
        if type(value) is not bool:
            raise ValueError(f"native plan dev_gate.{field} must be bool")
        projected[field] = value
    return projected


def _safe_lld_logical_ref(value: Any) -> str:
    """验证 LLD 的 logical ref；错误不包含物理 process 路径。"""

    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError("LLD_REF_UNSAFE")
    if (
        not value.startswith("process/")
        or value.startswith("/")
        or "\\" in value
        or "://" in value
        or "//" in value
        or not value.endswith(".md")
    ):
        raise ValueError("LLD_REF_UNSAFE")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("LLD_REF_UNSAFE")
    return value


def _selected_full_lld_ref(
    project_root: Path,
    *,
    raw_story: dict[str, Any],
    story_ref: str,
) -> str | None:
    """选择并预检 full LLD；canonical 分支绝不回退到 legacy 派生路径。"""

    canonical = _canonical_story_present(raw_story)
    raw_policy = raw_story.get("lld_policy")
    if canonical:
        if not isinstance(raw_policy, dict):
            raise ValueError("LLD_GATE_MALFORMED")
        required_level = raw_policy.get("required_level")
        if not isinstance(required_level, str) or not required_level:
            raise ValueError("LLD_GATE_MALFORMED")
        if required_level != "full-lld":
            return None
        gate = raw_story.get("lld_gate")
        if gate is None:
            raise ValueError("LLD_GATE_MISSING")
        if not isinstance(gate, dict) or gate.get("required") is not True:
            raise ValueError("LLD_GATE_MALFORMED")
        if "design_evidence_type" in gate and gate["design_evidence_type"] != "full-lld":
            raise ValueError("LLD_GATE_POLICY_CONFLICT")
        if "evidence_ref" not in gate:
            raise ValueError("LLD_GATE_MISSING")
        ref = _safe_lld_logical_ref(gate["evidence_ref"])
    else:
        if raw_policy != "full-lld":
            return None
        if not story_ref.startswith("process/") or not story_ref.endswith(".md"):
            raise ValueError("LLD_REF_UNSAFE")
        ref = _safe_lld_logical_ref(story_ref[:-3] + "-LLD.md")
    try:
        target = _resolve_runtime_ref(project_root, ref)
    except (FileNotFoundError, ValueError):
        raise ValueError("LLD_REF_TARGET_MISSING") from None
    if not target.is_file():
        raise ValueError("LLD_REF_TARGET_MISSING")
    return ref


def _selected_scope_goal_note_ref(
    project_root: Path,
    *,
    raw_story: dict[str, Any],
    story_id: str,
    story_ref: str,
) -> str | None:
    """选择并校验唯一 scope-goal-note；优先 Story 内联，兼容独立对象。"""

    raw_policy = raw_story.get("lld_policy")
    required_level = (
        raw_policy.get("required_level") if isinstance(raw_policy, dict) else raw_policy
    )
    if required_level != "scope-goal-note":
        return None
    gate = raw_story.get("lld_gate")
    if not isinstance(gate, dict) or gate.get("required") is not True:
        raise ValueError("SCOPE_GOAL_NOTE_GATE_MISSING")
    if gate.get("design_evidence_type") not in {None, "scope-goal-note"}:
        raise ValueError("LLD_GATE_POLICY_CONFLICT")
    ref = gate.get("evidence_ref")
    inline_payload = raw_story.get("scope_goal_note")
    if isinstance(inline_payload, Mapping) and ref:
        raise ValueError("SCOPE_GOAL_NOTE_MULTIPLE_TRUTHS")
    if isinstance(inline_payload, Mapping):
        payload = dict(inline_payload)
        raw_text = json.dumps(payload, ensure_ascii=False, indent=2)
        selected_ref = f"{story_ref}#范围与目标"
    elif ref:
        if (
            not isinstance(ref, str)
            or not ref.startswith("process/")
            or ref.startswith("/")
            or ".." in Path(ref).parts
            or Path(ref).suffix.lower() not in {".json", ".yaml", ".yml"}
        ):
            raise ValueError("SCOPE_GOAL_NOTE_REF_UNSAFE")
        target = _resolve_runtime_ref(project_root, ref)
        if not target.is_file():
            raise ValueError("SCOPE_GOAL_NOTE_TARGET_MISSING")
        payload = load_yaml_object(target)
        if not isinstance(payload, dict):
            raise ValueError("SCOPE_GOAL_NOTE_OBJECT_REQUIRED")
        raw_text = target.read_text(encoding="utf-8")
        selected_ref = ref
    else:
        story_path = _resolve_runtime_ref(project_root, story_ref)
        try:
            payload, raw_text = extract_scope_goal_note_from_story(
                story_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise ValueError(str(exc)) from exc
        selected_ref = f"{story_ref}#范围与目标"
    note = ScopeGoalNoteV1.from_mapping(
        payload,
        raw_text=raw_text,
        effective_profile="G2",
    )
    if note.story_id != story_id:
        raise ValueError("SCOPE_GOAL_NOTE_STORY_ID_MISMATCH")
    return selected_ref


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
        return _normalize_story_card_v1(story, story_text), None
    projected = _normalize_story_card_v1(story, story_text)
    ownership = plan_story.get("file_ownership")
    ownership = ownership if isinstance(ownership, dict) else {}
    projected["file_ownership"] = ownership
    plan_lld_gate = plan_story.get("lld_gate")
    if isinstance(plan_lld_gate, dict):
        projected["lld_gate"] = plan_lld_gate
    if plan_story.get("work_id"):
        projected["work_id"] = str(plan_story["work_id"])
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
        projected["acceptance"] = _acceptance_section_items(story_text)
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
    projected_gate = {
        "story_id": story_id,
        "status": str(plan_story.get("status") or ""),
        "dev_gate": _project_admission_gate(dev_gate),
    }
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


def _load_revalidation_authorization(
    project_root: Path, authorization_ref: str,
) -> tuple[Cp6RevalidationAuthorizationV1, str]:
    """只从持久化 logical ref 读取 A2 authorization，绝不信任 caller digest map。"""

    if (
        not authorization_ref.startswith("process/")
        or authorization_ref.startswith("/")
        or "\\" in authorization_ref
        or any(part in {"", ".", ".."} for part in authorization_ref.split("/"))
    ):
        raise ValueError("revalidation authorization ref must be a safe process logical ref")
    path = _resolve_runtime_path(project_root, authorization_ref)
    if not path.is_file():
        raise ValueError("revalidation authorization is missing")
    try:
        raw_bytes = path.read_bytes()
        raw = json.loads(raw_bytes)
        return Cp6RevalidationAuthorizationV1.from_dict(raw), hashlib.sha256(raw_bytes).hexdigest()
    except (json.JSONDecodeError, FrozenCp6EvidenceError, TypeError) as exc:
        raise ValueError("revalidation authorization is invalid") from exc


def _revalidation_artifact_refs(authorization: Cp6RevalidationAuthorizationV1) -> tuple[str, str]:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", authorization.work_id) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", authorization.attempt_id):
        raise ValueError("revalidation work or attempt identity is unsafe")
    root = f"process/works/{authorization.work_id}/revalidation/{authorization.attempt_id}/artifacts"
    return (
        f"{root}/{authorization.story_id}.CP6.work-packet.json",
        f"{root}/{authorization.story_id}.CP6.return.json",
    )


def _git_head(path: Path) -> str:
    result = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    value = result.stdout.strip()
    if result.returncode or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("revalidation current git fact is unavailable")
    return value


def _current_revalidation_facts(project_root: Path, authorization: Cp6RevalidationAuthorizationV1) -> dict[str, str]:
    """从 current release/process/Work 独立取事实，禁止由 authorization 回填。"""

    process_root = _resolve_runtime_ref(project_root, "process/.meta-flow-process.yaml").parent
    work_path = _resolve_runtime_path(project_root, f"process/works/{authorization.work_id}/WORK.yaml")
    if not work_path.is_file():
        raise ValueError("revalidation current Work is unavailable")
    work = _read_json_or_yaml(work_path)
    if work.get("work_id") != authorization.work_id or work.get("status") != "active":
        raise ValueError("revalidation current Work identity or status is invalid")
    scope_digest = str(work.get("scope_digest") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", scope_digest):
        raise ValueError("revalidation current Work scope_digest is unavailable")
    return {"release_oid": _git_head(project_root), "process_oid": _git_head(process_root), "scope_digest": scope_digest}


def _revalidation_allowed_targets(authorization: Cp6RevalidationAuthorizationV1, packet_ref: str, return_ref: str) -> bool:
    return all(any(fnmatch(target, pattern) for pattern in authorization.allowed_write_paths) for target in (packet_ref, return_ref))


def _native_work_allowed_targets(project_root: Path, authorization: Cp6RevalidationAuthorizationV1, packet_ref: str, return_ref: str) -> bool:
    work_path = _resolve_runtime_path(project_root, f"process/works/{authorization.work_id}/WORK.yaml")
    work = _read_json_or_yaml(work_path)
    scope = work.get("scope")
    patterns = scope.get("allowed_writes") if isinstance(scope, dict) else None
    if not isinstance(patterns, list) or not all(isinstance(pattern, str) for pattern in patterns):
        return False
    # Work scope is relative to process root; only a validated process logical ref
    # may undergo this one-way normalization.
    relative_targets = []
    for target in (packet_ref, return_ref):
        if not target.startswith("process/") or any(item in {"", ".", ".."} for item in target.split("/")):
            return False
        relative_targets.append(target.removeprefix("process/"))
    return all(any(fnmatch(target, pattern) for pattern in patterns) for target in relative_targets)


def _validate_authorization_refs(project_root: Path, authorization: Cp6RevalidationAuthorizationV1) -> None:
    for ref, digest in ((authorization.previous_cp6_ref, authorization.previous_cp6_digest), (authorization.superseding_cp5_ref, authorization.superseding_cp5_digest)):
        path = _resolve_runtime_path(project_root, ref)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("revalidation authorization reference or digest mismatch")


def _validate_revalidation_packet_preimage(path: Path, packet_ref: str, authorization: Cp6RevalidationAuthorizationV1) -> None:
    """首次 apply 只接受 authorization 冻结的 absent target preimage；replay 留给 bytes 比较。"""

    expected = canonical_digest({"target_ref": packet_ref, "exists": False})
    if authorization.plan_preimage_digest != expected:
        raise ValueError("revalidation authorization packet preimage mismatch")


def _write_revalidation_packet_create_once(path: Path, payload: bytes) -> dict[str, Any]:
    """仅为同一 attempt 创建 packet；未知写后状态保守标记为 PARTIAL。"""

    if path.exists():
        try:
            current = path.read_bytes()
        except OSError:
            return {"decision": "PARTIAL", "mutation_count": 0}
        return {
            "decision": "NO_CHANGE" if current == payload else "BLOCKED",
            "mutation_count": 0,
        }
    parents = [item for item in (path.parent, *path.parent.parents) if item != item.parent]
    before = {item: item.exists() for item in parents}

    def observed_mutations() -> int:
        parent_mutations = sum(
            not existed and item.exists() for item, existed in before.items()
        )
        target_mutations = int(path.exists())
        return parent_mutations + target_mutations

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return {"decision": "PARTIAL", "mutation_count": observed_mutations()}
    try:
        with path.open("xb") as target:
            target.write(payload)
    except FileExistsError:
        try:
            return {"decision": "NO_CHANGE" if path.read_bytes() == payload else "BLOCKED", "mutation_count": 0}
        except OSError:
            return {"decision": "PARTIAL", "mutation_count": 0}
    except OSError:
        return {"decision": "PARTIAL", "mutation_count": observed_mutations()}
    try:
        if path.read_bytes() != payload:
            return {"decision": "PARTIAL", "mutation_count": observed_mutations()}
    except OSError:
        return {"decision": "PARTIAL", "mutation_count": observed_mutations()}
    return {"decision": "APPLIED", "mutation_count": 1}


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
    revalidation_authorization_ref: str = "",
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
    story = story_data_from_file(story_path)
    raw_story = dict(story)
    story_id = str(story["story_id"])
    effective_cr_id = _resolve_formal_cr_identity(story, explicit_cr_id=cr_id)
    story_rel = (
        story_input_ref
        if not Path(story_input_ref).is_absolute() and story_input_ref.startswith("process/")
        else format_runtime_ref(project_root, story_path)
    )
    story, projected_gate = _projected_story_contract(
        project_root,
        story=story,
        story_text=story_path.read_text(encoding="utf-8"),
        story_id=story_id,
    )
    if (
        stage == "CP6"
        and not revalidation_authorization_ref
        and isinstance(projected_gate, dict)
        and projected_gate.get("status") == "ready-for-verification"
    ):
        raise ValueError("ready-for-verification requires explicit revalidation authorization")
    selected_lld_ref = _selected_full_lld_ref(
        project_root,
        raw_story=raw_story,
        story_ref=story_rel,
    )
    selected_scope_goal_note_ref = _selected_scope_goal_note_ref(
        project_root,
        raw_story=raw_story,
        story_id=story_id,
        story_ref=story_rel,
    )
    if write_policy:
        write_default_read_policy(project_root)
    read_policy = load_read_policy(project_root)
    state, state_required = _load_runtime_state_contract(project_root)
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
    if selected_scope_goal_note_ref and "#" not in selected_scope_goal_note_ref:
        _append_unique(
            must_read,
            _read_entry(
                project_root,
                selected_scope_goal_note_ref,
                required=True,
                reason="scope_goal_note",
            ),
        )
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
    risk_profile = str(story.get("risk_profile") or "")
    risk_profile_schema_version = int(story.get("risk_profile_schema_version") or 1)
    governance_binding = None
    if risk_profile_schema_version == 2 and risk_profile in {"G0", "G1", "G2", "G3"}:
        route_binding: Mapping[str, Any] = {}
        route_ref = f"process/checks/CP0-{effective_cr_id}.route-plan.json"
        if effective_cr_id:
            route_path = _resolve_runtime_ref(project_root, route_ref)
            if route_path.is_file() and not route_path.is_symlink():
                route_payload = load_yaml_object(route_path)
                candidate = route_payload.get("governance_profile")
                if isinstance(candidate, Mapping):
                    route_binding = candidate
                _append_unique(
                    must_read,
                    _read_entry(
                        project_root,
                        route_ref,
                        required=True,
                        reason="governance_profile_binding",
                    ),
                )
        route_risk_profile = str(route_binding.get("risk_profile") or "")
        if route_risk_profile and route_risk_profile != risk_profile:
            raise ValueError("STORY_ROUTE_GOVERNANCE_PROFILE_MISMATCH")
        governance_binding = GovernanceProfileBindingV2(
            schema_version=2,
            risk_profile=risk_profile,
            effective_profile=effective_governance_profile(risk_profile, 2),
            selection_source=str(
                story.get("governance_selection_source")
                or route_binding.get("selection_source")
                or ("user-explicit" if risk_profile == "G3" else "system-default")
            ),
            selection_record_digest=str(
                story.get("governance_selection_record_digest")
                or route_binding.get("selection_record_digest")
                or ""
            ),
            selection_authorization_digest=str(
                story.get("governance_selection_authorization_digest")
                or route_binding.get("selection_authorization_digest")
                or ""
            ),
            selection_source_oid=str(
                story.get("governance_selection_source_oid")
                or route_binding.get("selection_source_oid")
                or ""
            ),
            route_revision=int(
                story.get("governance_route_revision")
                or route_binding.get("route_revision")
                or 1
            ),
        )
    if selected_lld_ref:
        read_if_needed.append(
            {
                "path": selected_lld_ref,
                "mode": "full",
                # deny-default 目标在扩读授权前不得读取正文；授权后由 reader 计量。
                "estimated_tokens": 0,
                "trigger": preregistration.FULL_LLD_REQUIRED_TRIGGER,
                "reason": "story_lld",
                "consumer_requirement": preregistration.ConsumerRequirement.REQUIRED.value,
            }
        )
    denied_patterns = list(
        read_policy.get("deny_default_reads") or DEFAULT_READ_DENY_PATTERNS
    )
    preregistration_refs = list(
        read_expansion.select_required_preregistration_refs(
            {"lld_policy": lld_policy, "read_if_needed": read_if_needed}
        )
    )
    pre_dispatch_actions = (
        [
            {
                "operation": "context.read-log",
                "input_contract": "ReadExpansionPlanV2",
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
        "schema_version": 3,
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
        "design_evidence_ref": selected_scope_goal_note_ref or selected_lld_ref or None,
        "risk_profile": risk_profile,
        "risk_profile_schema_version": risk_profile_schema_version,
        "governance_profile_binding": (
            governance_binding.as_dict() if governance_binding else None
        ),
        "governance_profile_digest": governance_binding.digest if governance_binding else None,
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
    production_declaration = story.get("production_contract")
    if (
        stage == "CP6"
        and isinstance(production_declaration, Mapping)
        and production_declaration.get("schema_version") == 1
    ):
        from meta_flow.policies.public_operations import load_public_operation_registry

        registry_operations = {
            contract.operation for contract in load_public_operation_registry(project_root)
        }
        ownership = story.get("file_ownership")
        ownership = ownership if isinstance(ownership, Mapping) else {}
        packet["production_path_contract"] = build_production_path_contract(
            story,
            ownership_digest=canonical_digest(dict(ownership)),
            registry_operations=registry_operations,
        )
    revalidation_authorization: Cp6RevalidationAuthorizationV1 | None = None
    if revalidation_authorization_ref:
        if stage != "CP6":
            raise ValueError("revalidation authorization is only valid for CP6")
        revalidation_authorization, authorization_bytes_digest = _load_revalidation_authorization(project_root, revalidation_authorization_ref)
        if (revalidation_authorization.cr_id, revalidation_authorization.story_id) != (effective_cr_id, story_id):
            raise ValueError("revalidation authorization Story identity mismatch")
        if output is not None:
            raise ValueError("revalidation packet output is derived from authorization")
    if stage == "CP6":
        packet["expected_return_packet"] = _return_ref(story_id, "CP6")
        packet["admission"] = project_story_admission(
            frozen_cp6_evidence,
            expected_dependency_digests=expected_dependency_digests or {},
            projected_gate=projected_gate,
            revalidation_authorization=revalidation_authorization,
            revalidation_identity=(
                {
                    "cr_id": effective_cr_id,
                    "story_id": story_id,
                    "work_id": revalidation_authorization.work_id,
                    "attempt_id": revalidation_authorization.attempt_id,
                    "release_oid": revalidation_authorization.release_oid,
                    "process_oid": revalidation_authorization.process_oid,
                    "scope_digest": revalidation_authorization.scope_digest,
                }
                if revalidation_authorization else None
            ),
            project_root=project_root,
        )
        if revalidation_authorization:
            packet_ref, return_ref = _revalidation_artifact_refs(revalidation_authorization)
            canonical_authorization_ref = f"process/works/{revalidation_authorization.work_id}/revalidation/{revalidation_authorization.attempt_id}/receipts/authorization.json"
            if revalidation_authorization_ref != canonical_authorization_ref:
                raise ValueError("revalidation authorization ref is not canonical")
            current_facts = _current_revalidation_facts(project_root, revalidation_authorization)
            if any(current_facts[field] != getattr(revalidation_authorization, field) for field in current_facts):
                raise ValueError("revalidation authorization current facts mismatch")
            if not _revalidation_allowed_targets(revalidation_authorization, packet_ref, return_ref):
                raise ValueError("revalidation authorization target is outside allowlist")
            if not _native_work_allowed_targets(project_root, revalidation_authorization, packet_ref, return_ref):
                raise ValueError("revalidation target is outside native Work allowlist")
            _validate_authorization_refs(project_root, revalidation_authorization)
            packet["schema_version"] = 4
            packet["expected_return_packet"] = return_ref
            packet["revalidation_binding"] = {
                "version": 1,
                "authorization_ref": revalidation_authorization_ref,
                "authorization_bytes_digest": authorization_bytes_digest,
                "authorization_digest": revalidation_authorization.authorization_digest,
                "cr_id": revalidation_authorization.cr_id,
                "story_id": revalidation_authorization.story_id,
                "work_id": revalidation_authorization.work_id,
                "attempt_id": revalidation_authorization.attempt_id,
                "release_oid": revalidation_authorization.release_oid,
                "process_oid": revalidation_authorization.process_oid,
                "scope_digest": revalidation_authorization.scope_digest,
                "previous_cp6_ref": revalidation_authorization.previous_cp6_ref,
                "previous_cp6_digest": revalidation_authorization.previous_cp6_digest,
                "superseding_cp5_ref": revalidation_authorization.superseding_cp5_ref,
                "superseding_cp5_digest": revalidation_authorization.superseding_cp5_digest,
            }
            if packet["admission"]["decision"] != "READY":
                raise ValueError("revalidation authorization admission is blocked")
    if stage == "CP7":
        packet["implementation_return_ref"] = cp6_return_ref or _return_ref(story_id, "CP6")
        packet["expected_return_packet"] = _return_ref(story_id, "CP7")
    output_path = _runtime_output_path(project_root, output, _story_output_path(project_root, story_id, stage))
    if revalidation_authorization:
        output_path = _resolve_runtime_path(project_root, packet_ref)
        _validate_revalidation_packet_preimage(output_path, packet_ref, revalidation_authorization)
    serialized = (json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if revalidation_authorization:
        packet["packet_write"] = _write_revalidation_packet_create_once(output_path, serialized)
        if packet["packet_write"]["decision"] == "APPLIED":
            # The persisted bytes intentionally exclude this runtime receipt.
            pass
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(serialized)
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
    if packet_schema_version not in {1, 2, 3, 4}:
        errors.append("schema_version must be 1, 2, 3 or 4")
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
        is_full_lld = (
            str(entry.get("trigger") or "")
            == preregistration.FULL_LLD_REQUIRED_TRIGGER
        )
        if _matches_any(rel_path, denied) and not str(entry.get("trigger") or ""):
            errors.append(f"read_if_needed deny-default path lacks explicit trigger: {rel_path}")
        elif _matches_any(rel_path, denied) or is_full_lld:
            pass
        if packet_schema_version in {3, 4}:
            try:
                preregistration.interpret_preregistration_entry(
                    entry,
                    strict=True,
                )
            except preregistration.PreregistrationSemanticsError as exc:
                errors.append(str(exc))
    try:
        selected_preregistration_refs = list(
            read_expansion.select_required_preregistration_refs(packet)
        )
    except ValueError as exc:
        errors.append(str(exc))
        selected_preregistration_refs = []
    preregistration_refs = selected_preregistration_refs
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
            expected_contract = "ReadExpansionPlanV2" if packet_schema_version in {3, 4} else "ReadExpansionPlanV1"
            if set(action) != expected_fields:
                errors.append(f"Host pre_dispatch_action fields must match {expected_contract}")
            if action.get("operation") != "context.read-log":
                errors.append("Host pre_dispatch_action operation must be context.read-log")
            if action.get("input_contract") != expected_contract:
                errors.append(f"Host pre_dispatch_action input_contract must be {expected_contract}")
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
    production_contract = packet.get("production_path_contract")
    if production_contract is not None:
        if not isinstance(production_contract, dict):
            errors.append("production_path_contract must be an object")
        else:
            errors.extend(validate_production_path_contract(production_contract))
    if packet_schema_version == 4:
        binding = packet.get("revalidation_binding")
        required_binding = {
            "version", "authorization_ref", "authorization_bytes_digest", "authorization_digest",
            "cr_id", "story_id", "work_id", "attempt_id", "release_oid", "process_oid",
            "scope_digest", "previous_cp6_ref", "previous_cp6_digest", "superseding_cp5_ref",
            "superseding_cp5_digest",
        }
        if (
            not isinstance(binding, dict)
            or set(binding) != required_binding
            or type(binding.get("version")) is not int
            or binding.get("version") != 1
        ):
            errors.append("schema_version=4 revalidation_binding is invalid")
        else:
            try:
                string_fields = required_binding - {"version"}
                if any(not isinstance(binding[field], str) or not binding[field] for field in string_fields):
                    raise ValueError
                auth_ref = binding["authorization_ref"]
                logical_ref_fields = (
                    "authorization_ref",
                    "previous_cp6_ref",
                    "superseding_cp5_ref",
                )
                if any(
                    not binding[field].startswith("process/")
                    or "\\" in binding[field]
                    or "://" in binding[field]
                    or any(item in {"", ".", ".."} for item in binding[field].split("/"))
                    for field in logical_ref_fields
                ):
                    raise ValueError
                for field in ("authorization_bytes_digest", "authorization_digest", "scope_digest", "previous_cp6_digest", "superseding_cp5_digest"):
                    if not re.fullmatch(r"[0-9a-f]{64}", binding[field]):
                        raise ValueError
                for field in ("cr_id", "story_id", "work_id", "attempt_id"):
                    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", binding[field]):
                        raise ValueError
                for field in ("release_oid", "process_oid"):
                    if not re.fullmatch(r"[0-9a-f]{40}", binding[field]):
                        raise ValueError
                return_ref = (
                    f"process/works/{binding['work_id']}/revalidation/{binding['attempt_id']}"
                    f"/artifacts/{binding['story_id']}.CP6.return.json"
                )
                canonical_auth_ref = f"process/works/{binding['work_id']}/revalidation/{binding['attempt_id']}/receipts/authorization.json"
                if packet.get("cr_id") != binding["cr_id"] or packet.get("story_id") != binding["story_id"] or packet.get("expected_return_packet") != return_ref or auth_ref != canonical_auth_ref:
                    raise ValueError
                authorization, bytes_digest = _load_revalidation_authorization(root, auth_ref)
                expected_binding = {
                    "cr_id": authorization.cr_id, "story_id": authorization.story_id,
                    "work_id": authorization.work_id, "attempt_id": authorization.attempt_id,
                    "release_oid": authorization.release_oid, "process_oid": authorization.process_oid,
                    "scope_digest": authorization.scope_digest, "previous_cp6_ref": authorization.previous_cp6_ref,
                    "previous_cp6_digest": authorization.previous_cp6_digest,
                    "superseding_cp5_ref": authorization.superseding_cp5_ref,
                    "superseding_cp5_digest": authorization.superseding_cp5_digest,
                    "authorization_digest": authorization.authorization_digest,
                    "authorization_bytes_digest": bytes_digest,
                }
                if any(binding.get(key) != value for key, value in expected_binding.items()):
                    raise ValueError
            except (ValueError, FrozenCp6EvidenceError):
                errors.append("schema_version=4 revalidation_binding is invalid")
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
    profile_version = packet.get("risk_profile_schema_version", 1)
    if profile_version == 2:
        try:
            binding = packet.get("governance_profile_binding")
            if not isinstance(binding, dict):
                raise ValueError("governance_profile_binding missing")
            observed = GovernanceProfileBindingV2(**binding)
            if observed.risk_profile != str(packet.get("risk_profile") or ""):
                raise ValueError("governance_profile_binding risk_profile mismatch")
            if packet.get("governance_profile_digest") != observed.digest:
                raise ValueError("governance_profile_digest mismatch")
        except (TypeError, ValueError) as exc:
            errors.append(f"governance profile binding invalid: {exc}")
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
    print(f"- path: {format_runtime_ref(root, resolved_packet)}")
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
        parser.add_argument("--revalidation-authorization", default="")
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
            revalidation_authorization_ref=parsed.revalidation_authorization,
            write_policy=not parsed.no_write_policy,
        )
        decision = str(_packet.get("packet_write", {}).get("decision") or "APPLIED")
        if decision in {"BLOCKED", "PARTIAL"}:
            print(f"Story packet: {decision}")
            return 1
        print(f"wrote: {format_runtime_ref(parsed.project_root, path)}")
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
