"""Story-level context contracts and work/verify packets."""

from __future__ import annotations

import argparse
import json
import sys
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from meta_flow.checks.token_budget import DEFAULT_READ_DENY_PATTERNS, estimate_tokens, load_budgets
from meta_flow.context_pack.builder import (
    DEFAULT_FULL_DOC_READ_REASONS,
    READ_POLICY_REL,
    READ_EXPANSION_LEDGER_REL,
    default_read_policy,
    load_read_policy,
    write_default_read_policy,
)
from meta_flow.context_pack import read_expansion
from meta_flow.design.feature_registry import FEATURE_REGISTRY_REL
from meta_flow.design.module_boundaries import MODULE_BOUNDARIES_REL
from meta_flow.design.product_governance import CAPABILITY_STATUS_REL, CONCEPT_OWNERS_REL, PACKAGE_IDENTITY_REL
from meta_flow.policies.authz import AUTHZ_POLICY_REL
from meta_flow.policies.gate_profiles import GATE_PROFILES_REL
from meta_flow.state.current import STATE_CURRENT_REL, load_current_state
from meta_flow.workflow.cr_lifecycle import CR_SUMMARY_ROOT_REL


STORY_CONTEXT_ROOT_REL = Path("process/context/stories")
STORY_RETURN_ROOT_REL = Path("process/returns")
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


def _path_tokens(project_root: Path, rel_path: str) -> int:
    path = project_root / rel_path
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


def _story_id_from_path(path: Path, data: dict[str, Any]) -> str:
    return str(data.get("story_id") or data.get("id") or path.stem)


def story_data_from_file(path: Path) -> dict[str, Any]:
    data = _read_json_or_yaml(path)
    data["story_id"] = _story_id_from_path(path, data)
    return data


def _story_output_path(project_root: Path, story_id: str, stage: str) -> Path:
    if stage == "BASE":
        return project_root / STORY_CONTEXT_ROOT_REL / f"{story_id}.base.context.json"
    if stage == "CP6":
        return project_root / STORY_CONTEXT_ROOT_REL / f"{story_id}.CP6.work-packet.json"
    if stage == "CP7":
        return project_root / STORY_CONTEXT_ROOT_REL / f"{story_id}.CP7.verify-packet.json"
    return project_root / STORY_CONTEXT_ROOT_REL / f"{story_id}.{stage}.context.json"


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
    write_policy: bool = True,
) -> tuple[dict[str, Any], Path]:
    project_root = project_root.resolve()
    stage = stage.upper()
    if stage not in ALLOWED_STAGES:
        raise ValueError(f"unsupported Story context stage: {stage}")
    story_path = (project_root / story_path).resolve() if not story_path.is_absolute() else story_path.resolve()
    if not story_path.is_file():
        raise FileNotFoundError(f"Story file missing: {story_path}")
    if write_policy:
        write_default_read_policy(project_root)
    read_policy = load_read_policy(project_root)
    state = load_current_state(project_root)
    story = story_data_from_file(story_path)
    story_id = str(story["story_id"])
    effective_cr_id = cr_id or str(story.get("cr_id") or "")
    story_rel = _rel(project_root, story_path)
    allowed_reads: list[dict[str, Any]] = []
    read_if_needed: list[dict[str, Any]] = []

    _append_unique(allowed_reads, _read_entry(project_root, STATE_CURRENT_REL.as_posix(), required=True, reason="runtime_state"))
    _append_unique(allowed_reads, _read_entry(project_root, story_rel, required=True, reason="story_card"))
    _append_unique(allowed_reads, _read_entry(project_root, READ_POLICY_REL.as_posix(), required=True, reason="read_policy"))
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
        if (project_root / rel_path).is_file():
            _append_unique(allowed_reads, _read_entry(project_root, rel_path, required=False, reason=reason))

    lld_policy = str(story.get("lld_policy") or story.get("required_level") or "")
    if lld_policy == "full-lld":
        lld_ref = story_rel.replace(".md", "-LLD.md")
        read_if_needed.append(
            {
                "path": lld_ref,
                "mode": "full",
                "estimated_tokens": _path_tokens(project_root, lld_ref),
                "trigger": "full_lld_required_by_policy",
                "reason": "story_lld",
            }
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
        "schema_version": 1,
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
        "allowed_reads": allowed_reads,
        "read_if_needed": read_if_needed,
        "denied_default_reads": list(read_policy.get("deny_default_reads") or DEFAULT_READ_DENY_PATTERNS),
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
    if stage == "CP7":
        packet["implementation_return_ref"] = cp6_return_ref or _return_ref(story_id, "CP6")
        packet["expected_return_packet"] = _return_ref(story_id, "CP7")
    output_path = output.resolve() if output else _story_output_path(project_root, story_id, stage)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return packet, output_path


def _matches_any(rel_path: str, patterns: list[str]) -> bool:
    return any(fnmatch(rel_path, pattern) for pattern in patterns)


def _load_packet(packet_path: Path) -> dict[str, Any]:
    return json.loads(packet_path.read_text(encoding="utf-8"))


def validate_story_packet(packet_path: Path, *, project_root: Path | None = None) -> tuple[list[str], list[str]]:
    packet_path = packet_path.resolve()
    if not packet_path.is_file():
        return [f"Story packet missing: {packet_path}"], []
    packet = _load_packet(packet_path)
    root = project_root.resolve() if project_root else _infer_project_root(packet_path)
    errors: list[str] = []
    warnings: list[str] = []
    if packet.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if packet.get("packet_type") not in ALLOWED_PACKET_TYPES:
        errors.append(f"invalid packet_type: {packet.get('packet_type')}")
    if packet.get("stage") not in ALLOWED_STAGES:
        errors.append(f"invalid stage: {packet.get('stage')}")
    for key in ("story_id", "story_ref", "feature_refs", "feature_design_refs", "allowed_reads", "denied_default_reads"):
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
    allowed_reads = packet.get("allowed_reads") or []
    if not isinstance(allowed_reads, list) or not allowed_reads:
        errors.append("allowed_reads must be a non-empty list")
        allowed_reads = []
    for entry in allowed_reads:
        if not isinstance(entry, dict):
            errors.append("allowed_reads entries must be objects")
            continue
        rel_path = str(entry.get("path") or "")
        if not rel_path:
            errors.append("allowed_reads entry missing path")
            continue
        if _matches_any(rel_path, denied):
            errors.append(f"allowed_reads contains deny-default path: {rel_path}")
        if entry.get("required") is True and not (root / rel_path).is_file():
            errors.append(f"required allowed_read missing on disk: {rel_path}")
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


def explain_story_packet(packet_path: Path) -> int:
    packet = _load_packet(packet_path.resolve())
    budget = packet.get("budget") or {}
    print("Story Context Packet:")
    print(f"- path: {packet_path.resolve()}")
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


def check_sufficiency(packet_path: Path) -> int:
    packet = _load_packet(packet_path.resolve())
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
        print(f"wrote: {path}")
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
        parser.add_argument("--packet", dest="packet_path", type=Path, required=True)
        parsed = parser.parse_args(args[1:])
        return check_sufficiency(parsed.packet_path)
    if command == "explain-story-packet":
        parser = argparse.ArgumentParser(prog="meta-flow context explain-story-packet")
        parser.add_argument("--packet", dest="packet_path", type=Path, required=True)
        parsed = parser.parse_args(args[1:])
        return explain_story_packet(parsed.packet_path)
    if command in {"read-log", "read-log-check"}:
        return read_expansion.main(args)
    raise SystemExit(f"未知 story context 命令: {command}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
