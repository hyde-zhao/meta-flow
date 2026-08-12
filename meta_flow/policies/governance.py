"""Governance truth-map and lifecycle policy checks."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from meta_flow.project.process_route import _resolve_runtime_ref

SOURCE_OF_TRUTH_REL = Path("process/policies/SOURCE-OF-TRUTH-MAP.yaml")
SOURCE_OF_TRUTH_DOC_REL = Path("docs/design/SOURCE-OF-TRUTH-MAP.md")
RETENTION_POLICY_REL = Path("process/policies/RETENTION-POLICY.json")

ALLOWED_TRUTH_ROLES = {
    "machine_truth",
    "human_authored_truth",
    "generated_summary",
    "append_only_event_log",
    "generated_packet",
    "agent_return",
    "evidence_index",
    "audit_appendix",
    "legacy_fallback",
}
ALLOWED_EDIT_POLICIES = {
    "manual-edit",
    "tool-generated",
    "append-only",
    "tool-generated-versioned",
    "human-reviewed-generated",
    "legacy-readonly",
}
GENERATED_OR_NON_TRUTH_ROLES = {
    "generated_summary",
    "generated_packet",
    "audit_appendix",
    "legacy_fallback",
}
REQUIRED_TRUTH_OBJECTS = {
    "current_runtime_state",
    "human_state_summary",
    "cr_lifecycle",
    "story_lifecycle",
    "feature_registry",
    "feature_design",
    "context_pack",
    "story_packet",
    "story_return",
    "evidence_index",
    "cp_result",
    "cp_summary",
}
LEDGER_COMPACTION_POLICY_KEYS = {
    "window_days",
    "keep_latest_n_events",
    "keep_latest_n_cr",
    "archive_rule",
}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return [str(value)] if str(value) else []


def truth_map_path(project_root: Path) -> Path:
    return _resolve_runtime_ref(project_root, SOURCE_OF_TRUTH_REL.as_posix())


def truth_map_doc_path(project_root: Path) -> Path:
    return project_root.resolve() / SOURCE_OF_TRUTH_DOC_REL


def retention_policy_path(project_root: Path) -> Path:
    return _resolve_runtime_ref(project_root, RETENTION_POLICY_REL.as_posix())


def default_source_of_truth_map() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "machine_policy_ref": SOURCE_OF_TRUTH_REL.as_posix(),
        "human_summary_ref": SOURCE_OF_TRUTH_DOC_REL.as_posix(),
        "objects": {
            "current_runtime_state": {
                "path": "process/state/STATE.current.json",
                "truth_role": "machine_truth",
                "edit_policy": "tool-generated",
                "machine_truth": True,
                "default_context": "allowed",
            },
            "human_state_summary": {
                "path": "process/STATE.md",
                "truth_role": "generated_summary",
                "edit_policy": "tool-generated",
                "machine_truth": False,
                "generated_from": ["process/state/STATE.current.json"],
                "default_context": "deny-default",
            },
            "cr_lifecycle": {
                "path": "process/state/CR-LEDGER.ndjson",
                "truth_role": "append_only_event_log",
                "edit_policy": "append-only",
                "append_only": True,
                "machine_truth": True,
                "derived_outputs": ["process/changes/CR-INDEX.json", "process/changes/summaries/*.summary.json"],
                "default_context": "summary-or-index",
            },
            "story_lifecycle": {
                "path": "process/state/STORY-LEDGER.ndjson",
                "truth_role": "append_only_event_log",
                "edit_policy": "append-only",
                "append_only": True,
                "machine_truth": True,
                "default_context": "summary-or-index",
            },
            "feature_registry": {
                "path": "docs/design/FEATURE-REGISTRY.yaml",
                "truth_role": "machine_truth",
                "edit_policy": "manual-edit",
                "machine_truth": True,
                "paired_truth": ["docs/features/<feature>/DESIGN.md"],
                "default_context": "summary-or-index",
            },
            "feature_design": {
                "path": "docs/features/<feature>/DESIGN.md",
                "truth_role": "human_authored_truth",
                "edit_policy": "manual-edit",
                "machine_truth": True,
                "paired_truth": ["docs/design/FEATURE-REGISTRY.yaml"],
                "default_context": "summary-first",
            },
            "capability_status": {
                "path": "docs/design/CAPABILITY-STATUS.yaml",
                "truth_role": "machine_truth",
                "edit_policy": "manual-edit",
                "machine_truth": True,
                "default_context": "summary-or-index",
            },
            "module_boundaries": {
                "path": "docs/design/MODULE-BOUNDARIES.yaml",
                "truth_role": "machine_truth",
                "edit_policy": "manual-edit",
                "machine_truth": True,
                "default_context": "summary-or-index",
            },
            "concept_owners": {
                "path": "docs/design/CONCEPT-OWNERS.yaml",
                "truth_role": "machine_truth",
                "edit_policy": "manual-edit",
                "machine_truth": True,
                "default_context": "summary-or-index",
            },
            "context_pack": {
                "path": "process/context/*.context.json",
                "truth_role": "generated_packet",
                "edit_policy": "tool-generated-versioned",
                "machine_truth": False,
                "generated_from": [
                    "process/state/STATE.current.json",
                    "process/policies/READ-POLICY.json",
                    "process/changes/summaries/*.summary.json",
                ],
                "default_context": "entrypoint",
            },
            "story_packet": {
                "path": "process/context/stories/*.json",
                "truth_role": "generated_packet",
                "edit_policy": "tool-generated-versioned",
                "machine_truth": False,
                "generated_from": ["process/stories/STORY-*.md", "docs/design/FEATURE-REGISTRY.yaml"],
                "default_context": "entrypoint",
            },
            "story_return": {
                "path": "process/returns/*.return.json",
                "truth_role": "agent_return",
                "edit_policy": "tool-generated",
                "machine_truth": True,
                "default_context": "summary-or-index",
            },
            "evidence_index": {
                "path": "process/evidence/*.index.json",
                "truth_role": "evidence_index",
                "edit_policy": "tool-generated",
                "machine_truth": True,
                "generated_from": ["process/returns/*.return.json"],
                "default_context": "summary-or-index",
            },
            "cp_result": {
                "path": "process/checks/*.result.json",
                "truth_role": "machine_truth",
                "edit_policy": "tool-generated",
                "machine_truth": True,
                "default_context": "summary-or-index",
            },
            "cp_summary": {
                "path": "process/checks/*.summary.md",
                "truth_role": "generated_summary",
                "edit_policy": "tool-generated",
                "machine_truth": False,
                "generated_from": ["process/checks/*.result.json"],
                "default_context": "human-only",
            },
        },
    }


def default_retention_policy() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "active_cr": {
            "default_context": "summary_plus_active_packets",
            "keep": "full_until_closed",
        },
        "closed_cr": {
            "default_context": "summary_only",
            "full_doc_read_allowed_when": [
                "human_audit",
                "field_conflict",
                "summary_insufficient",
            ],
        },
        "story_packets": {
            "keep_latest_in_default_context": True,
            "older_versions": "deny_default",
        },
        "cp_results": {
            "json_truth": "keep",
            "summary": "generated",
            "audit_appendix": "high-risk-only",
        },
        "ledgers": {
            "append_only": True,
            "default_context": "latest-window-or-index",
            "compaction": default_ledger_compaction_policy(),
        },
        "audit_appendix": {
            "default_context": "high-risk-only",
            "allowed_when": ["runtime-high-risk", "human_audit"],
        },
    }


def default_ledger_compaction_policy() -> dict[str, Any]:
    return {
        "window_days": 90,
        "keep_latest_n_events": 500,
        "keep_latest_n_cr": 20,
        "archive_rule": "summary-index-backup",
    }


def normalize_ledger_compaction_policy(value: Any) -> dict[str, Any]:
    """校验并返回 canonical ledger compaction policy。"""

    if not isinstance(value, dict):
        raise ValueError("must be an object")
    unknown = sorted(str(key) for key in set(value) - LEDGER_COMPACTION_POLICY_KEYS)
    if unknown:
        raise ValueError("has unknown fields: " + ", ".join(unknown))
    missing = sorted(LEDGER_COMPACTION_POLICY_KEYS - set(value))
    normalized: dict[str, Any] = {}
    for key in ("window_days", "keep_latest_n_events", "keep_latest_n_cr"):
        if key not in value:
            continue
        item = value.get(key)
        if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
            raise ValueError(f"{key} must be a positive integer")
        normalized[key] = item
    if missing:
        raise ValueError("missing fields: " + ", ".join(missing))
    archive_rule = value.get("archive_rule")
    if archive_rule != "summary-index-backup":
        raise ValueError("archive_rule must be summary-index-backup")
    normalized["archive_rule"] = archive_rule
    return normalized


def write_default_truth_map(project_root: Path, *, force: bool = False) -> Path:
    path = truth_map_path(project_root.resolve())
    if path.exists() and not force:
        return path
    _write_json(path, default_source_of_truth_map())
    return path


def write_default_retention_policy(project_root: Path, *, force: bool = False) -> Path:
    path = retention_policy_path(project_root.resolve())
    if path.exists() and not force:
        return path
    _write_json(path, default_retention_policy())
    return path


def load_truth_map(project_root: Path) -> dict[str, Any]:
    return _read_json(truth_map_path(project_root.resolve()))


def load_retention_policy(project_root: Path) -> dict[str, Any]:
    return _read_json(retention_policy_path(project_root.resolve()))


def validate_truth_map(project_root: Path) -> tuple[list[str], list[str]]:
    path = truth_map_path(project_root.resolve())
    if not path.is_file():
        return [f"SOURCE-OF-TRUTH-MAP missing: {path}"], []
    data = load_truth_map(project_root)
    errors: list[str] = []
    warnings: list[str] = []
    if data.get("schema_version") not in {1, 2}:
        errors.append("SOURCE-OF-TRUTH-MAP schema_version must be 1 or 2")
    if data.get("machine_policy_ref") != SOURCE_OF_TRUTH_REL.as_posix():
        errors.append(f"machine_policy_ref must be {SOURCE_OF_TRUTH_REL.as_posix()}")
    objects = data.get("objects")
    if not isinstance(objects, dict) or not objects:
        return ["SOURCE-OF-TRUTH-MAP objects must be a non-empty object"], warnings
    missing_required = sorted(REQUIRED_TRUTH_OBJECTS.difference(objects))
    for object_id in missing_required:
        errors.append(f"missing required truth object: {object_id}")
    for object_id, item in objects.items():
        if not isinstance(item, dict):
            errors.append(f"{object_id} must be an object")
            continue
        path_value = str(item.get("path") or "")
        truth_role = str(item.get("truth_role") or "")
        edit_policy = str(item.get("edit_policy") or "")
        machine_truth = bool(item.get("machine_truth", False))
        if not path_value:
            errors.append(f"{object_id} missing path")
        if truth_role not in ALLOWED_TRUTH_ROLES:
            errors.append(f"{object_id} invalid truth_role: {truth_role or '-'}")
        if edit_policy not in ALLOWED_EDIT_POLICIES:
            errors.append(f"{object_id} invalid edit_policy: {edit_policy or '-'}")
        if truth_role == "append_only_event_log" and edit_policy != "append-only":
            errors.append(f"{object_id} append_only_event_log must use edit_policy=append-only")
        if item.get("append_only") is True and edit_policy != "append-only":
            errors.append(f"{object_id} append_only=true must use edit_policy=append-only")
        if truth_role in GENERATED_OR_NON_TRUTH_ROLES and machine_truth:
            errors.append(f"{object_id} truth_role={truth_role} must not set machine_truth=true")
        generated_from = _as_list(item.get("generated_from"))
        if truth_role in {"generated_summary", "generated_packet", "evidence_index"} and not generated_from:
            errors.append(f"{object_id} truth_role={truth_role} requires generated_from")
        if path_value == "process/STATE.md" and machine_truth:
            errors.append("process/STATE.md must not be machine_truth")
        if path_value.endswith(".summary.md") and machine_truth:
            errors.append(f"{object_id} summary markdown must not be machine_truth")
        canonical_concept_id = item.get("canonical_concept_id")
        owner = item.get("owner")
        if data.get("schema_version") == 2 and (canonical_concept_id is not None or owner is not None):
            if not isinstance(canonical_concept_id, str) or not canonical_concept_id:
                errors.append(f"{object_id} canonical_concept_id must be non-empty")
            if not isinstance(owner, str) or not owner:
                errors.append(f"{object_id} owner must be non-empty")
    return errors, warnings


def validate_retention_policy(project_root: Path) -> tuple[list[str], list[str]]:
    path = retention_policy_path(project_root.resolve())
    if not path.is_file():
        return [f"RETENTION-POLICY missing: {path}"], []
    data = load_retention_policy(project_root)
    errors: list[str] = []
    warnings: list[str] = []
    if data.get("schema_version") != 1:
        errors.append("RETENTION-POLICY schema_version must be 1")
    closed_cr = data.get("closed_cr") or {}
    if not isinstance(closed_cr, dict):
        errors.append("closed_cr must be an object")
        closed_cr = {}
    if closed_cr.get("default_context") != "summary_only":
        errors.append("closed_cr.default_context must be summary_only")
    story_packets = data.get("story_packets") or {}
    if not isinstance(story_packets, dict):
        errors.append("story_packets must be an object")
        story_packets = {}
    if story_packets.get("keep_latest_in_default_context") is not True:
        errors.append("story_packets.keep_latest_in_default_context must be true")
    if story_packets.get("older_versions") not in {"deny_default", "archive"}:
        errors.append("story_packets.older_versions must be deny_default or archive")
    cp_results = data.get("cp_results") or {}
    if not isinstance(cp_results, dict):
        errors.append("cp_results must be an object")
        cp_results = {}
    if cp_results.get("json_truth") != "keep":
        errors.append("cp_results.json_truth must be keep")
    if cp_results.get("summary") != "generated":
        errors.append("cp_results.summary must be generated")
    if cp_results.get("audit_appendix") not in {"high-risk-only", "human-audit-only", "deny-default"}:
        errors.append("cp_results.audit_appendix must be high-risk-only, human-audit-only, or deny-default")
    ledgers = data.get("ledgers") or {}
    if not isinstance(ledgers, dict):
        errors.append("ledgers must be an object")
        ledgers = {}
    if ledgers.get("append_only") is not True:
        errors.append("ledgers.append_only must be true")
    if ledgers.get("default_context") not in {"latest-window-or-index", "latest-window", "index", "summary-only"}:
        errors.append("ledgers.default_context must be latest-window-or-index, latest-window, index, or summary-only")
    try:
        normalize_ledger_compaction_policy(ledgers.get("compaction"))
    except ValueError as exc:
        errors.append(f"ledgers.compaction {exc}")
    audit = data.get("audit_appendix") or {}
    if not isinstance(audit, dict):
        errors.append("audit_appendix must be an object")
        audit = {}
    if audit.get("default_context") not in {"high-risk-only", "human-audit-only", "deny-default"}:
        errors.append("audit_appendix.default_context must be high-risk-only, human-audit-only, or deny-default")
    return errors, warnings


def render_truth_map_doc(project_root: Path, *, force: bool = False) -> Path:
    root = project_root.resolve()
    data = load_truth_map(root)
    if not data:
        raise FileNotFoundError(f"SOURCE-OF-TRUTH-MAP missing: {truth_map_path(root)}")
    path = truth_map_doc_path(root)
    if path.exists() and not force:
        return path
    rows = []
    for object_id, item in sorted((data.get("objects") or {}).items()):
        if not isinstance(item, dict):
            continue
        rows.append(
            "| {object_id} | `{path}` | {truth_role} | {edit_policy} | {machine_truth} |".format(
                object_id=object_id,
                path=item.get("path", ""),
                truth_role=item.get("truth_role", ""),
                edit_policy=item.get("edit_policy", ""),
                machine_truth=str(bool(item.get("machine_truth", False))).lower(),
            )
        )
    text = (
        "# Source of Truth Map\n\n"
        "> This file is the human-readable summary. The machine policy source is "
        f"`{SOURCE_OF_TRUTH_REL.as_posix()}`.\n\n"
        "| Object | Path | Truth Role | Edit Policy | Machine Truth |\n"
        "|---|---|---|---|---|\n"
        + "\n".join(rows)
        + "\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _print_governance_help() -> None:
    print(
        "usage: meta-flow governance <command> [options]\n\n"
        "Commands:\n"
        "  init              Write default source-of-truth and retention policies.\n"
        "  truth-map-check   Validate process/policies/SOURCE-OF-TRUTH-MAP.yaml.\n"
        "  truth-map-render  Render docs/design/SOURCE-OF-TRUTH-MAP.md from the machine policy.\n"
        "  retention-check   Validate process/policies/RETENTION-POLICY.json.\n"
        "  baseline-refresh  Plan or atomically refresh the declared long-term governance projection.\n"
        "  check             Run truth-map and retention checks.\n\n"
        "Examples:\n"
        "  meta-flow governance init --project-root .\n"
        "  meta-flow governance truth-map-check --project-root .\n"
        "  meta-flow governance retention-check --project-root .\n"
        "  meta-flow governance baseline-refresh --project-root . --project-id <project-id> --immutable-commit-role release_input=release:<oid> --immutable-commit-role process_input=process:<oid>\n"
    )


def main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if not args or args[0] in {"-h", "--help"}:
        _print_governance_help()
        return 0
    command = args[0]
    if command == "baseline-refresh":
        from meta_flow.project import governance_projection

        return governance_projection.baseline_refresh_main(args[1:])
    parser = argparse.ArgumentParser(prog=f"meta-flow governance {command}")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--force", action="store_true")
    parsed = parser.parse_args(args[1:])
    root = parsed.project_root.resolve()
    if command == "init":
        truth_path = write_default_truth_map(root, force=parsed.force)
        retention_path = write_default_retention_policy(root, force=parsed.force)
        print(f"truth_map: {truth_path}")
        print(f"retention_policy: {retention_path}")
        return 0
    if command == "truth-map-check":
        errors, warnings = validate_truth_map(root)
        print("Source of Truth Map Check: " + ("FAIL" if errors else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    if command == "truth-map-render":
        path = render_truth_map_doc(root, force=parsed.force)
        print(f"wrote: {path}")
        return 0
    if command == "retention-check":
        errors, warnings = validate_retention_policy(root)
        print("Retention Policy Check: " + ("FAIL" if errors else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    if command == "check":
        truth_errors, truth_warnings = validate_truth_map(root)
        retention_errors, retention_warnings = validate_retention_policy(root)
        errors = [*truth_errors, *retention_errors]
        warnings = [*truth_warnings, *retention_warnings]
        print("Governance Policy Check: " + ("FAIL" if errors else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    raise SystemExit(
        f"未知 governance 命令: {command}. 目前支持: init, truth-map-check, truth-map-render, retention-check, baseline-refresh, check"
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
