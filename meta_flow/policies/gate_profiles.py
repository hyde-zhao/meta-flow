"""Gate profile registry and risk classifier for Meta Flow."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

GATE_PROFILES_REL = Path("process/policies/GATE-PROFILES.json")
RUNTIME_HIGH_RISK_TERMS = (
    "credential",
    "secret",
    ".env",
    "nas",
    "qmt",
    "miniqmt",
    "xtquant",
    "gateway",
    "live",
    "trading",
    "submit_order",
    "cancel_order",
    "provider_publish",
    "lake_write",
    "catalog_publish",
)
ARCHITECTURE_MAJOR_TERMS = (
    "public_contract",
    "package_contract",
    "manifest_schema",
    "adapter_boundary",
    "runner_boundary",
    "cross_platform_target",
)
DOC_PATH_PREFIXES = ("docs/", "README", "CHANGELOG", "LICENSE")
PROCESS_LITE_PREFIXES = ("process/", "scripts/check_", "meta_flow/checks/", "meta_flow/context_pack/", "meta_flow/state/")
STANDARD_LITE_BLOCKING_TERMS = (
    "requires_story_decomposition",
    "story_decomposition",
    "requires_architecture_review",
    "product_baseline_refresh_required",
    "authz_policy_refs",
    "runtime_authorization",
    "migration",
    "cross_module",
    "cross-module",
)


def default_gate_profiles() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "profiles": {
            "micro": {
                "description": "小型机械修改，不影响接口、运行时、凭据、外部系统",
                "stages": ["CP0", "CP6-lite", "CP7-lite", "CP8-lite"],
                "human_gates": [],
                "max_context_tokens": 8000,
            },
            "docs-lite": {
                "description": "README、用户文档、说明性文档",
                "stages": ["CP0", "CP2-lite", "CP8-lite"],
                "human_gates": ["CP8-lite"],
                "max_context_tokens": 10000,
            },
            "process-lite": {
                "description": "process ledger、checker、索引、归档、非业务逻辑流程修复",
                "stages": ["CP0", "CP2-lite", "CP6-lite", "CP7-lite", "CP8-lite"],
                "human_gates": ["CP8-lite"],
                "max_context_tokens": 12000,
            },
            "standard-code": {
                "description": "普通代码功能、测试、内部模块调整",
                "stages": ["CP0", "CP2", "CP3-lite", "CP5", "CP6", "CP7", "CP8"],
                "human_gates": ["CP2", "CP5", "CP8"],
                "max_context_tokens": 20000,
            },
            "standard-lite": {
                "description": "单模块 / 小范围 artifact CR，保留 CP2/CP7/CP8 硬门禁但压缩设计和发布文档形态",
                "stages": ["CP0", "CP2", "CP3-lite", "CP5-lite", "CP6", "CP7", "CP8"],
                "human_gates": ["CP2", "CP8"],
                "max_context_tokens": 16000,
                "allows_batch_lld": True,
                "requires_hard_gates": ["scope_authz_consistency", "promise_evidence_alignment"],
            },
            "architecture-major": {
                "description": "项目重构、边界重划、核心设计变更",
                "stages": ["CP0", "CP1", "CP2", "CP3", "CP4", "CP5", "CP6", "CP7", "CP8"],
                "human_gates": ["CP2", "CP3", "CP5", "CP8"],
                "max_context_tokens": 30000,
            },
            "runtime-high-risk": {
                "description": "凭据、NAS、外部系统、真实运行、交易、发布等高风险变更",
                "stages": ["CP0", "CP1", "CP2", "CP3", "CP4", "CP5", "CP6", "CP7", "CP8"],
                "human_gates": ["CP2", "CP3", "CP5", "CP8"],
                "max_context_tokens": 40000,
                "requires_explicit_authorization": True,
            },
        },
        "risk_rules": {
            "force_runtime_high_risk_if_any": list(RUNTIME_HIGH_RISK_TERMS),
            "force_architecture_major_if_any": list(ARCHITECTURE_MAJOR_TERMS),
        },
    }


def profiles_path(project_root: Path) -> Path:
    return project_root / GATE_PROFILES_REL


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def load_gate_profiles(project_root: Path) -> dict[str, Any]:
    configured = _read_json(profiles_path(project_root.resolve()))
    if configured:
        return configured
    return default_gate_profiles()


def write_default_gate_profiles(project_root: Path, *, force: bool = False) -> Path:
    path = profiles_path(project_root.resolve())
    if path.exists() and not force:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(default_gate_profiles(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def validate_gate_profiles(project_root: Path) -> list[str]:
    errors: list[str] = []
    data = load_gate_profiles(project_root)
    if data.get("schema_version") != 1:
        errors.append("GATE-PROFILES schema_version must be 1")
    profiles = data.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        return ["GATE-PROFILES profiles must be a non-empty object"]
    for required in ("docs-lite", "process-lite", "standard-lite", "standard-code", "architecture-major", "runtime-high-risk"):
        if required not in profiles:
            errors.append(f"missing required profile: {required}")
    for profile, item in profiles.items():
        if not isinstance(item, dict):
            errors.append(f"{profile} must be an object")
            continue
        if not item.get("stages"):
            errors.append(f"{profile} missing stages")
        if "human_gates" not in item:
            errors.append(f"{profile} missing human_gates")
        if int(item.get("max_context_tokens") or 0) <= 0:
            errors.append(f"{profile} max_context_tokens must be positive")
    return errors


def _normalize_values(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        for piece in value.replace(",", " ").split():
            if piece:
                normalized.append(piece)
    return normalized


def _any_term(text: str, terms: tuple[str, ...] | list[str]) -> list[str]:
    lowered = text.lower()
    return [term for term in terms if term.lower() in lowered]


def _is_docs_path(path: str) -> bool:
    return path.startswith(DOC_PATH_PREFIXES) or Path(path).name.startswith(("README", "CHANGELOG", "LICENSE"))


def classify_gate_profile(changed_files: list[str] | None = None, impacts: list[str] | None = None) -> dict[str, Any]:
    files = _normalize_values(changed_files or [])
    impact_terms = _normalize_values(impacts or [])
    joined = " ".join([*files, *impact_terms])
    runtime_hits = _any_term(joined, RUNTIME_HIGH_RISK_TERMS)
    if runtime_hits:
        return {
            "profile": "runtime-high-risk",
            "reason": "runtime_high_risk_keyword",
            "matched_terms": runtime_hits,
        }
    architecture_hits = _any_term(joined, ARCHITECTURE_MAJOR_TERMS)
    if architecture_hits:
        return {
            "profile": "architecture-major",
            "reason": "architecture_major_keyword",
            "matched_terms": architecture_hits,
        }
    if files and all(_is_docs_path(path) for path in files):
        return {"profile": "docs-lite", "reason": "docs_only_change", "matched_terms": []}
    if files and all(path.startswith(PROCESS_LITE_PREFIXES) for path in files):
        return {"profile": "process-lite", "reason": "process_hygiene_change", "matched_terms": []}
    if files and all(path.startswith("tests/") for path in files):
        return {"profile": "micro", "reason": "tests_only_change", "matched_terms": []}
    standard_lite_hits = _any_term(joined, ("standard-lite", "standard_lite", "compact_artifact", "single_artifact"))
    if standard_lite_hits:
        return {
            "profile": "standard-lite",
            "reason": "explicit_compact_artifact_keyword",
            "matched_terms": standard_lite_hits,
        }
    standard_lite_blockers = _any_term(joined, STANDARD_LITE_BLOCKING_TERMS)
    if files and len(files) <= 5 and not standard_lite_blockers:
        return {
            "profile": "standard-lite",
            "reason": "small_scope_standard_lite",
            "matched_terms": [],
        }
    return {"profile": "standard-code", "reason": "default_standard_code", "matched_terms": []}


def _print_gate_help() -> None:
    print(
        "usage: meta-flow gate <command> [options]\n\n"
        "Commands:\n"
        "  classify  Classify changed files or impact terms into a gate profile.\n"
        "  plan      Print stages and human gates for a profile.\n"
        "  check     Validate GATE-PROFILES.json.\n\n"
        "Examples:\n"
        "  meta-flow gate classify --changed-files README.md\n"
        "  meta-flow gate classify --impact QMT credential runtime\n"
        "  meta-flow gate plan --profile process-lite --project-root .\n"
    )


def main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if not args or args[0] in {"-h", "--help"}:
        _print_gate_help()
        return 0
    command = args[0]
    if command == "classify":
        parser = argparse.ArgumentParser(prog="meta-flow gate classify")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--changed-files", nargs="*", default=[])
        parser.add_argument("--impact", nargs="*", default=[])
        parsed = parser.parse_args(args[1:])
        result = classify_gate_profile(parsed.changed_files, parsed.impact)
        profiles = load_gate_profiles(parsed.project_root).get("profiles") or {}
        profile = profiles.get(result["profile"], {})
        print("Gate Classification:")
        print(f"- profile: {result['profile']}")
        print(f"- reason: {result['reason']}")
        print(f"- matched_terms: {', '.join(result['matched_terms']) or '-'}")
        print(f"- max_context_tokens: {profile.get('max_context_tokens', '-')}")
        print(f"- human_gates: {', '.join(profile.get('human_gates') or []) or '-'}")
        return 0
    if command == "plan":
        parser = argparse.ArgumentParser(prog="meta-flow gate plan")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--profile", required=True)
        parser.add_argument("--write-default", action="store_true")
        parsed = parser.parse_args(args[1:])
        if parsed.write_default:
            path = write_default_gate_profiles(parsed.project_root)
            print(f"wrote: {path}")
        profiles = load_gate_profiles(parsed.project_root).get("profiles") or {}
        if parsed.profile not in profiles:
            raise SystemExit(f"未知 gate profile: {parsed.profile}")
        print(json.dumps({"profile": parsed.profile, **profiles[parsed.profile]}, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if command == "check":
        parser = argparse.ArgumentParser(prog="meta-flow gate check")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--write-default", action="store_true")
        parsed = parser.parse_args(args[1:])
        if parsed.write_default:
            path = write_default_gate_profiles(parsed.project_root)
            print(f"wrote: {path}")
        errors = validate_gate_profiles(parsed.project_root)
        print("Gate Profile Check: " + ("FAIL" if errors else "OK"))
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    raise SystemExit(f"未知 gate 命令: {command}. 目前支持: classify, plan, check")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
