"""Local workflow evaluation runner.

The runner intentionally uses only the Python standard library. Meta Flow eval
contracts are YAML documents for humans and tools, but this module validates the
stable contract surface with conservative text parsing instead of requiring a
runtime YAML dependency.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import fnmatch
import hashlib
import json
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


REQUIRED_WORKFLOW_EVAL_KEYS = {
    "schema_version",
    "suite_id",
    "sut",
    "prompt_bundle",
    "case_registry",
    "trace_policy",
    "graders",
}
REQUIRED_PROMPT_BUNDLE_KEYS = {
    "schema_version",
    "bundle_id",
    "version",
    "components",
    "compatibility",
    "rollback",
}
REQUIRED_CASE_REGISTRY_KEYS = {
    "schema_version",
    "registry_id",
    "cases",
}
SUPPORTED_GRADER_TYPES = {
    "required_fields",
    "forbidden_patterns",
    "path_exists",
    "prompt_bundle_hashes",
    "case_registry_links",
    "eval_config_non_empty",
    "manifest_bundle_consistency",
    "content_schema",
    "state_machine",
    "gate_contract",
    "phase_skill_chain",
    "hard_stop_confirmation",
    "artifact_trace_schema",
    "candidate_decision_integrity",
    "deliverable_exact_schema",
    "table_structure",
    "table_schema",
    "runtime_artifact",
    "install_mapping",
}
SUPPORTED_GRADER_MODES = {"static", "runtime", "human-review", "external"}
SUPPORTED_AUTHORIZATIONS = {"none", "local-fs", "git-read", "git-write", "llm", "network"}
SUPPORTED_BLOCKING_POLICIES = {"always", "on-release", "advisory"}
PASSING_STATUSES = {"PASS"}
NON_FAIL_INCOMPLETE_STATUSES = {"SKIP", "NEEDS_REVIEW"}
SUPPORTED_RESULT_STATUSES = {"PASS", "FAIL", "BLOCKED", "SKIP", "NEEDS_REVIEW"}
DEFAULT_ALLOWED_AUTHORIZATIONS = {"none", "local-fs"}
SEVERITY_RANK = {"BLOCKER": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
DEFAULT_PLACEHOLDER_PATTERNS = [
    r"\bTODO\b",
    r"\bTBD\b",
    r"\bFIXME\b",
    r"\bPLACEHOLDER\b",
    r"\{\{[^}]+\}\}",
    r"<[^>]*TODO[^>]*>",
]
SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_-]?key|password|passwd|token|secret|cookie)\b\s*[:=]\s*([\"']?)[^\s\"']+",
)
TRIAGE_TYPES = {"ISSUE_DRAFT", "GAP", "BACKLOG", "ENVIRONMENT", "USAGE", "DUPLICATE", "NO_ACTION"}
GAP_TYPES = {"missing_case", "missing_grader", "missing_fixture", "missing_runtime_sample", "weak_assertion"}
RECOMMENDED_ASSETS = {"case", "grader", "fixture", "runtime_sample", "doc_update"}
FEEDBACK_TOOL_OUTPUT_NAMES = {
    "feedback-pull-summary.json",
    "feedback-analyze-summary.json",
    "feedback-metrics.json",
    "triage-metrics.json",
    "TRIAGE-RESULTS.json",
    "ISSUE-DRAFTS.json",
    "ISSUE-DRAFTS.md",
    "GAPS.json",
    "EVAL-BACKLOG.json",
    "RUN-EXEC-INDEX.json",
}


@dataclass
class EvalIssue:
    severity: str
    code: str
    message: str
    path: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "path": self.path,
        }


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def mask_sensitive(text: str) -> str:
    return SENSITIVE_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=<redacted>", text)


def safe_id_component(value: str) -> str:
    component = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip()).strip("-")
    return component[:64] or "item"


def strip_value(value: str) -> str:
    value = value.strip()
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    if " #" in value:
        value = value.split(" #", 1)[0].strip()
    return value.strip().strip('"').strip("'")


def parse_inline_list(value: str) -> list[str]:
    value = strip_value(value)
    if not (value.startswith("[") and value.endswith("]")):
        return [value] if value else []
    body = value[1:-1].strip()
    if not body:
        return []
    return [strip_value(item) for item in body.split(",")]


def as_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str):
        return [value] if value else []
    return [str(value)]


def parse_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def parse_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def parse_timestamp(value: object) -> dt.datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def infer_grader_mode(grader_type: str, configured: object) -> str:
    mode = str(configured or "").strip()
    if mode:
        return mode
    if grader_type in {"runtime_artifact", "install_mapping"}:
        return "runtime"
    return "static"


def infer_grader_authorization(grader_type: str, configured: object) -> str:
    authorization = str(configured or "").strip()
    if authorization:
        return authorization
    if grader_type in {"runtime_artifact", "install_mapping"}:
        return "local-fs"
    return "none"


def grader_metadata(grader: dict[str, object]) -> dict[str, str]:
    grader_type = str(grader.get("type", ""))
    return {
        "mode": infer_grader_mode(grader_type, grader.get("mode")),
        "authorization": infer_grader_authorization(grader_type, grader.get("authorization")),
        "blocking_policy": str(grader.get("blocking_policy") or "always"),
    }


def failure_from_message(message: str) -> dict[str, object]:
    return {"message": message}


def build_structured_evidence(
    grader_id: str,
    status: str,
    messages: list[str],
    *,
    checked_files: int = 0,
    failures: list[dict[str, object]] | None = None,
    metrics: dict[str, object] | None = None,
    checked_paths: list[str] | None = None,
) -> dict[str, object]:
    actual_failures = failures if failures is not None else []
    if status == "FAIL" and not actual_failures:
        actual_failures = [failure_from_message(message) for message in messages]
    return {
        "grader_id": grader_id,
        "status": status,
        "checked_files": checked_files,
        "checked_paths": checked_paths or [],
        "failures": actual_failures,
        "metrics": metrics or {},
        "messages": messages,
    }


def result_from_messages(
    grader: dict[str, object],
    status: str,
    messages: list[str],
    *,
    checked_files: int = 0,
    failures: list[dict[str, object]] | None = None,
    metrics: dict[str, object] | None = None,
    checked_paths: list[str] | None = None,
) -> dict[str, object]:
    grader_id = str(grader.get("id", ""))
    grader_type = str(grader.get("type", ""))
    metadata = grader_metadata(grader)
    return {
        "id": grader_id,
        "type": grader_type,
        "mode": metadata["mode"],
        "authorization": metadata["authorization"],
        "blocking_policy": metadata["blocking_policy"],
        "profile_requirement": str(grader.get("profile_requirement") or grader.get("requirement") or ("optional" if metadata["blocking_policy"] == "advisory" else "required")),
        "profiles": as_list(grader.get("profiles")),
        "status": status,
        "evidence": build_structured_evidence(
            grader_id,
            status,
            messages,
            checked_files=checked_files,
            failures=failures,
            metrics=metrics,
            checked_paths=checked_paths,
        ),
        "evidence_text": messages,
    }


def render_evidence_cell(evidence: object) -> str:
    if isinstance(evidence, dict):
        messages = [str(item) for item in evidence.get("messages", [])]
        metrics = evidence.get("metrics", {})
        parts = messages[:3]
        if isinstance(metrics, dict) and metrics:
            metric_text = ", ".join(f"{key}={value}" for key, value in sorted(metrics.items()))
            parts.append(f"metrics: {metric_text}")
        failures = evidence.get("failures", [])
        if isinstance(failures, list) and failures and not messages:
            parts.extend(str(item.get("message", item)) if isinstance(item, dict) else str(item) for item in failures[:3])
        return "; ".join(parts) if parts else "structured evidence recorded"
    if isinstance(evidence, list):
        return "; ".join(str(item) for item in evidence)
    return str(evidence)


def top_level_keys(text: str) -> set[str]:
    keys: set[str] = set()
    for line in text.splitlines():
        if not line or line[0].isspace() or line.startswith("#"):
            continue
        match = re.match(r"^([A-Za-z0-9_-]+):", line)
        if match:
            keys.add(match.group(1))
    return keys


def scalar_value(text: str, key: str) -> str:
    for line in text.splitlines():
        if line.startswith(f"{key}:"):
            return strip_value(line.split(":", 1)[1])
    return ""


def nested_scalar_value(text: str, parent: str, key: str) -> str:
    lines = text.splitlines()
    in_parent = False
    for line in lines:
        if line.startswith(f"{parent}:"):
            in_parent = True
            continue
        if in_parent and line and not line[0].isspace():
            break
        if not in_parent:
            continue
        match = re.match(rf"^\s+{re.escape(key)}:\s*(.*)$", line)
        if match:
            return strip_value(match.group(1))
    return ""


def relative(base: Path, path: Path) -> str:
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return path.as_posix()


def section_blocks(text: str, section: str) -> list[dict[str, object]]:
    """Parse simple YAML list blocks under a top-level section.

    Supported shape:

    section:
      - id: item
        key: value
        values: [a, b]
        multiline_values:
          - a
          - b
    """

    lines = text.splitlines()
    in_section = False
    current: dict[str, object] | None = None
    blocks: list[dict[str, object]] = []
    pending_list_key: str | None = None

    for line in lines:
        if line.startswith(f"{section}:"):
            in_section = True
            continue
        if in_section and line and not line[0].isspace():
            break
        if not in_section:
            continue
        if not line.strip() or line.lstrip().startswith("#"):
            continue

        list_item_match = re.match(r"^(\s*)-\s+(.*)$", line)
        item_match = re.match(r"^(\s*)-\s+([A-Za-z0-9_-]+):\s*(.*)$", line)
        field_match = re.match(r"^\s+([A-Za-z0-9_-]+):\s*(.*)$", line)

        if list_item_match and current is not None and pending_list_key and len(list_item_match.group(1)) > 2:
            item = strip_value(list_item_match.group(2))
            current.setdefault(pending_list_key, [])
            if isinstance(current[pending_list_key], list) and item:
                current[pending_list_key].append(item)
            continue

        if item_match:
            if current:
                blocks.append(current)
            current = {item_match.group(2): parse_scalar_or_list(item_match.group(3))}
            pending_list_key = None
            continue
        if field_match and current is not None:
            key = field_match.group(1)
            raw_value = field_match.group(2)
            if not raw_value.strip():
                current[key] = []
                pending_list_key = key
            else:
                current[key] = parse_scalar_or_list(raw_value)
                pending_list_key = None

    if current:
        blocks.append(current)
    return blocks


def parse_scalar_or_list(raw: str) -> object:
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        return parse_inline_list(raw)
    return strip_value(raw)


def parse_yaml_scalar(raw: str) -> object:
    value = strip_value(raw)
    if value.startswith("[") and value.endswith("]"):
        return parse_inline_list(value)
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none", "~"}:
        return ""
    if re.fullmatch(r"-?\d+", value):
        try:
            return int(value)
        except ValueError:
            return value
    return value


def parse_yaml_subset(text: str) -> dict[str, object]:
    """Parse the small YAML subset used by eval registries.

    This intentionally avoids adding a runtime dependency. It supports nested
    dictionaries, lists of dictionaries, inline lists, quoted scalars, booleans,
    and integers. It is not a general YAML parser.
    """

    prepared: list[tuple[int, str]] = []
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        content = raw.split(" #", 1)[0].rstrip()
        prepared.append((len(content) - len(content.lstrip(" ")), content.lstrip(" ")))

    def parse_block(index: int, indent: int) -> tuple[object, int]:
        if index >= len(prepared):
            return {}, index
        if prepared[index][0] < indent:
            return {}, index
        is_list = prepared[index][0] == indent and prepared[index][1].startswith("- ")
        if is_list:
            items: list[object] = []
            while index < len(prepared):
                current_indent, content = prepared[index]
                if current_indent != indent or not content.startswith("- "):
                    break
                item_text = content[2:].strip()
                index += 1
                if not item_text:
                    nested, index = parse_block(index, indent + 2)
                    items.append(nested)
                    continue
                item: object
                key_match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", item_text)
                if key_match:
                    item = {key_match.group(1): parse_yaml_scalar(key_match.group(2))}
                    while index < len(prepared) and prepared[index][0] > indent:
                        child_indent, child_content = prepared[index]
                        field_match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", child_content)
                        if not field_match:
                            break
                        key = field_match.group(1)
                        rest = field_match.group(2)
                        index += 1
                        if rest.strip():
                            item[key] = parse_yaml_scalar(rest)
                        else:
                            nested, index = parse_block(index, child_indent + 2)
                            item[key] = nested
                else:
                    item = parse_yaml_scalar(item_text)
                items.append(item)
            return items, index

        payload: dict[str, object] = {}
        while index < len(prepared):
            current_indent, content = prepared[index]
            if current_indent < indent:
                break
            if current_indent > indent:
                break
            field_match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", content)
            if not field_match:
                break
            key = field_match.group(1)
            rest = field_match.group(2)
            index += 1
            if rest.strip():
                payload[key] = parse_yaml_scalar(rest)
            else:
                nested, index = parse_block(index, indent + 2)
                payload[key] = nested
        return payload, index

    parsed, _ = parse_block(0, 0)
    return parsed if isinstance(parsed, dict) else {}


def validate_required_keys(path: Path, required: set[str], label: str) -> list[EvalIssue]:
    if not path.is_file():
        return [EvalIssue("BLOCKER", "missing-file", f"Missing {label}: {path}", path.as_posix())]
    keys = top_level_keys(read_text(path))
    missing = sorted(required - keys)
    if not missing:
        return []
    return [
        EvalIssue(
            "BLOCKER",
            "missing-required-key",
            f"{label} missing required top-level keys: {', '.join(missing)}",
            path.as_posix(),
        )
    ]


def required_grader_fields(grader_type: str) -> dict[str, str]:
    return {
        "required_fields": "required_fields",
        "forbidden_patterns": "target_globs",
        "path_exists": "paths",
        "content_schema": "target or target_globs",
        "state_machine": "target",
        "gate_contract": "target",
        "phase_skill_chain": "target",
        "hard_stop_confirmation": "target",
        "artifact_trace_schema": "target or target_globs",
        "candidate_decision_integrity": "target",
        "deliverable_exact_schema": "target",
        "table_structure": "target_globs",
        "table_schema": "target",
        "runtime_artifact": "workspace",
        "install_mapping": "platform and agent or expected_skills",
    }.get(grader_type, {})


def validate_grader_config(grader: dict[str, object], eval_path: Path) -> list[EvalIssue]:
    grader_id = str(grader.get("id", "<unknown>"))
    grader_type = str(grader.get("type", ""))
    issues: list[EvalIssue] = []

    def empty(field: str) -> bool:
        return len(as_list(grader.get(field))) == 0

    if grader_type == "required_fields" and empty("required_fields"):
        issues.append(EvalIssue("BLOCKER", "empty-grader-config", f"Grader {grader_id} has empty required_fields", eval_path.as_posix()))
    if grader_type == "forbidden_patterns":
        if empty("target_globs"):
            issues.append(EvalIssue("BLOCKER", "empty-grader-config", f"Grader {grader_id} has empty target_globs", eval_path.as_posix()))
        if empty("patterns") and str(grader.get("allow_empty_patterns", "")).lower() != "true":
            issues.append(EvalIssue("BLOCKER", "empty-grader-config", f"Grader {grader_id} has empty patterns", eval_path.as_posix()))
    if grader_type == "path_exists" and empty("paths"):
        issues.append(EvalIssue("BLOCKER", "empty-grader-config", f"Grader {grader_id} has empty paths", eval_path.as_posix()))
    if grader_type in {"content_schema", "artifact_trace_schema"} and empty("target") and empty("target_globs"):
        issues.append(EvalIssue("BLOCKER", "empty-grader-config", f"Grader {grader_id} requires target or target_globs", eval_path.as_posix()))
    if grader_type in {
        "state_machine",
        "gate_contract",
        "phase_skill_chain",
        "hard_stop_confirmation",
        "candidate_decision_integrity",
        "deliverable_exact_schema",
        "table_schema",
    } and empty("target"):
        issues.append(EvalIssue("BLOCKER", "empty-grader-config", f"Grader {grader_id} requires target", eval_path.as_posix()))
    if grader_type == "table_structure" and empty("target_globs"):
        issues.append(EvalIssue("BLOCKER", "empty-grader-config", f"Grader {grader_id} has empty target_globs", eval_path.as_posix()))
    if grader_type == "runtime_artifact" and empty("workspace") and empty("sample_registry"):
        issues.append(EvalIssue("BLOCKER", "empty-grader-config", f"Grader {grader_id} requires workspace or sample_registry", eval_path.as_posix()))
    if grader_type == "install_mapping":
        if empty("platform"):
            issues.append(EvalIssue("BLOCKER", "empty-grader-config", f"Grader {grader_id} requires platform", eval_path.as_posix()))
        if empty("agent") and empty("expected_skills") and empty("expected_rules"):
            issues.append(EvalIssue("BLOCKER", "empty-grader-config", f"Grader {grader_id} requires agent, expected_skills, or expected_rules", eval_path.as_posix()))

    metadata = grader_metadata(grader)
    if metadata["mode"] not in SUPPORTED_GRADER_MODES:
        issues.append(EvalIssue("BLOCKER", "unsupported-grader-mode", f"Grader {grader_id} has unsupported mode: {metadata['mode']}", eval_path.as_posix()))
    if metadata["authorization"] not in SUPPORTED_AUTHORIZATIONS:
        issues.append(
            EvalIssue(
                "BLOCKER",
                "unsupported-grader-authorization",
                f"Grader {grader_id} has unsupported authorization: {metadata['authorization']}",
                eval_path.as_posix(),
            )
        )
    if metadata["blocking_policy"] not in SUPPORTED_BLOCKING_POLICIES:
        issues.append(
            EvalIssue(
                "BLOCKER",
                "unsupported-blocking-policy",
                f"Grader {grader_id} has unsupported blocking_policy: {metadata['blocking_policy']}",
                eval_path.as_posix(),
            )
        )
    return issues


def validate_eval_package(eval_path: Path) -> tuple[Path, list[EvalIssue]]:
    eval_path = eval_path.resolve()
    root = eval_path.parent
    issues: list[EvalIssue] = []

    issues.extend(validate_required_keys(eval_path, REQUIRED_WORKFLOW_EVAL_KEYS, "WORKFLOW-EVAL"))
    if issues:
        return root, issues

    eval_text = read_text(eval_path)
    prompt_bundle_path = root / scalar_value(eval_text, "prompt_bundle")
    case_registry_path = root / scalar_value(eval_text, "case_registry")
    issues.extend(validate_required_keys(prompt_bundle_path, REQUIRED_PROMPT_BUNDLE_KEYS, "PROMPT-BUNDLE"))
    issues.extend(validate_required_keys(case_registry_path, REQUIRED_CASE_REGISTRY_KEYS, "CASE-REGISTRY"))

    graders = section_blocks(eval_text, "graders")
    if not graders:
        issues.append(EvalIssue("BLOCKER", "missing-graders", "WORKFLOW-EVAL must define at least one grader", eval_path.as_posix()))
    for grader in graders:
        grader_id = str(grader.get("id", ""))
        grader_type = str(grader.get("type", ""))
        if not grader_id:
            issues.append(EvalIssue("BLOCKER", "grader-missing-id", "A grader is missing id", eval_path.as_posix()))
        if grader_type not in SUPPORTED_GRADER_TYPES:
            issues.append(
                EvalIssue(
                    "BLOCKER",
                    "unsupported-grader",
                    f"Grader {grader_id or '<unknown>'} has unsupported type: {grader_type}",
                    eval_path.as_posix(),
                )
            )
        else:
            issues.extend(validate_grader_config(grader, eval_path))

    return root, issues


def glob_paths(root: Path, patterns: Iterable[str]) -> list[Path]:
    matched: list[Path] = []
    for pattern in patterns:
        if pattern.startswith("../") or pattern.startswith("./") or "/" in pattern:
            matched.extend(path for path in root.glob(pattern) if path.exists())
            continue
        for path in root.rglob("*"):
            rel = relative(root, path)
            if fnmatch.fnmatch(rel, pattern):
                matched.append(path)
    return sorted(set(matched))


def grader_target_paths(root: Path, grader: dict[str, object]) -> list[Path]:
    target_globs = as_list(grader.get("target_globs"))
    if target_globs:
        return glob_paths(root, target_globs)
    target = str(grader.get("target", ""))
    return [root / target] if target else []


def check_required_patterns(text: str, patterns: Iterable[str], label: str = "pattern") -> list[str]:
    findings: list[str] = []
    for pattern in patterns:
        regex = pattern.replace("\\\\", "\\")
        if not re.search(regex, text, re.MULTILINE | re.IGNORECASE | re.DOTALL):
            findings.append(f"missing {label}: {pattern}")
    return findings


def markdown_table_header_cells(row: str) -> list[str]:
    return [cell.strip().replace("\\|", "|") for cell in row.strip().strip("|").split("|")]


def find_table_by_header_cells(text: str, expected_columns: list[str]) -> list[str] | None:
    expected = [col.strip() for col in expected_columns]
    for table in extract_all_tables(text):
        if markdown_table_header_cells(table[0]) == expected:
            return table
    return None


# ---------------------------------------------------------------------------
# Shared helpers for content_schema / table_structure graders
# ---------------------------------------------------------------------------


def _inside_fence(lines: list[str], idx: int) -> bool:
    """Return True if line *idx* is inside a fenced code block (``` or ~~~)."""
    fence_count = 0
    for i in range(idx):
        stripped = lines[i].strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            fence_count += 1
    return fence_count % 2 == 1


def extract_table_block(text: str, header_needle: str) -> list[str] | None:
    """Find a markdown table whose header row contains *header_needle*.

    Returns the list of table row lines (header + separator + data), or
    ``None`` when no matching table is found.
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            if header_needle in stripped and not re.match(r"^\|[-\s:|]+\|$", stripped):
                if _inside_fence(lines, i):
                    continue
                rows = [stripped]
                j = i + 1
                while j < len(lines):
                    nl = lines[j].strip()
                    if nl.startswith("|") and nl.endswith("|"):
                        rows.append(nl)
                        j += 1
                    else:
                        break
                return rows
    return None


def extract_all_tables(text: str) -> list[list[str]]:
    """Extract every markdown table from *text*, skipping those inside fenced code blocks.

    Returns a list of tables; each table is a list of stripped row strings
    (header, separator, and data rows).
    """
    lines = text.splitlines()
    tables: list[list[str]] = []
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if (
            stripped.startswith("|")
            and stripped.endswith("|")
            and not re.match(r"^\|[-\s:|]+\|$", stripped)
            and not _inside_fence(lines, i)
        ):
            if i + 1 < len(lines):
                sep = lines[i + 1].strip()
                if re.match(r"^\|[-\s:|]+\|$", sep):
                    table_rows = [stripped, sep]
                    j = i + 2
                    while j < len(lines):
                        dl = lines[j].strip()
                        if dl.startswith("|") and dl.endswith("|") and not re.match(r"^\|[-\s:|]+\|$", dl):
                            table_rows.append(dl)
                            j += 1
                        else:
                            break
                    tables.append(table_rows)
                    i = j
                    continue
        i += 1
    return tables


def count_table_columns(row: str) -> int:
    """Count pipe-delimited columns in a single markdown table row."""
    cells = row.split("|")
    # cells[0] and cells[-1] are the empty strings surrounding the leading/trailing |
    return len([c for c in cells[1:-1]])


def has_unescaped_pipe_in_cell(row: str) -> bool:
    """Return True if any table cell in *row* contains an unescaped ``|``."""
    cells = row.split("|")
    for cell in cells[1:-1]:
        # Remove code spans (backtick-enclosed) – a | inside them is valid
        content_no_code = re.sub(r"`[^`]*`", "", cell)
        cleaned = content_no_code.replace("\\|", "")
        if "|" in cleaned:
            return True
    return False


def run_required_fields(root: Path, grader: dict[str, object]) -> tuple[str, list[str]]:
    required = set(grader.get("required_fields", []))
    target_globs = [str(item) for item in grader.get("target_globs", [])]

    if target_globs:
        paths = glob_paths(root, target_globs)
    else:
        target_path = root / str(grader.get("target", ""))
        if not target_path.is_file():
            return "FAIL", [f"target missing: {relative(root, target_path)}"]
        paths = [target_path]

    if not paths:
        return "FAIL", ["target missing: no files matched target_globs"]

    findings: list[str] = []
    evidence: list[str] = []
    for path in paths:
        if not path.is_file():
            findings.append(f"target missing: {relative(root, path)}")
            continue
        missing = sorted(required - top_level_keys(read_text(path)))
        if missing:
            findings.append(f"{relative(root, path)} missing fields: {', '.join(missing)}")
        else:
            evidence.append(f"{relative(root, path)} contains required fields: {', '.join(sorted(required))}")

    if findings:
        return "FAIL", findings
    if not evidence:
        return "PASS", ["no files checked"]
    # Truncate evidence to first 5 and a count summary when there are many files
    if len(evidence) > 5:
        evidence = evidence[:5] + [f"... and {len(evidence) - 5} more files OK"]
    return "PASS", evidence


def run_forbidden_patterns(root: Path, grader: dict[str, object]) -> tuple[str, list[str]]:
    patterns = [str(item) for item in grader.get("patterns", [])]
    target_globs = [str(item) for item in grader.get("target_globs", [])]
    findings: list[str] = []
    for path in glob_paths(root, target_globs):
        if not path.is_file():
            continue
        text = read_text(path)
        for pattern in patterns:
            regex = pattern.replace("\\\\", "\\")
            if re.search(regex, text, re.IGNORECASE):
                findings.append(f"{relative(root, path)} matched forbidden pattern: {pattern}")
    if findings:
        return "FAIL", findings
    return "PASS", [f"no forbidden patterns matched in {', '.join(target_globs)}"]


def run_path_exists(root: Path, grader: dict[str, object]) -> tuple[str, list[str]]:
    missing: list[str] = []
    for rel_path in [str(item) for item in grader.get("paths", [])]:
        if not (root / rel_path).exists():
            missing.append(rel_path)
    if missing:
        return "FAIL", [f"missing paths: {', '.join(missing)}"]
    return "PASS", [f"all paths exist: {', '.join(str(item) for item in grader.get('paths', []))}"]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_prompt_bundle_hashes(root: Path, grader: dict[str, object], eval_text: str) -> tuple[str, list[str]]:
    bundle_path = root / scalar_value(eval_text, "prompt_bundle")
    if not bundle_path.is_file():
        return "FAIL", [f"prompt bundle missing: {relative(root, bundle_path)}"]
    findings: list[str] = []
    evidence: list[str] = []
    for component in section_blocks(read_text(bundle_path), "components"):
        rel_path = str(component.get("path", ""))
        expected = str(component.get("sha256", ""))
        if not rel_path or not expected:
            findings.append(f"component {component.get('id', '<unknown>')} missing path or sha256")
            continue
        component_path = root / rel_path
        if not component_path.is_file():
            findings.append(f"component path missing: {rel_path}")
            continue
        actual = sha256(component_path)
        if actual != expected:
            findings.append(f"{rel_path} sha256 mismatch: expected {expected}, actual {actual}")
        else:
            evidence.append(f"{rel_path} sha256 OK")
    if findings:
        return "FAIL", findings
    return "PASS", evidence or ["prompt bundle has no hash-checked components"]


def run_case_registry_links(root: Path, grader: dict[str, object], eval_text: str, grader_ids: set[str]) -> tuple[str, list[str]]:
    registry_path = root / scalar_value(eval_text, "case_registry")
    if not registry_path.is_file():
        return "FAIL", [f"case registry missing: {relative(root, registry_path)}"]
    missing: list[str] = []
    cases = section_blocks(read_text(registry_path), "cases")
    if not cases:
        return "FAIL", ["case registry defines no cases"]
    for case in cases:
        case_id = str(case.get("id", "<unknown>"))
        for grader_id in [str(item) for item in case.get("graders", [])]:
            if grader_id not in grader_ids:
                missing.append(f"{case_id} references missing grader {grader_id}")
    if missing:
        return "FAIL", missing
    return "PASS", [f"{len(cases)} case(s) reference existing graders"]


def run_eval_config_non_empty(root: Path, grader: dict[str, object], eval_text: str) -> tuple[str, list[str]]:
    eval_path = root / "__WORKFLOW_EVAL__"
    findings: list[str] = []
    checked = 0
    for configured in section_blocks(eval_text, "graders"):
        checked += 1
        for issue in validate_grader_config(configured, eval_path):
            findings.append(issue.message)
    if findings:
        return "FAIL", findings
    return "PASS", [f"{checked} grader configuration block(s) have required non-empty parameters"]


def quoted_paths(text: str) -> list[str]:
    paths: list[str] = []
    for value in re.findall(r'"([^"]+)"', text):
        if "/" in value or value.endswith((".md", ".yaml", ".yml", ".json", ".sh", ".ps1", ".py")):
            paths.append(value)
    return paths


def run_manifest_bundle_consistency(root: Path, grader: dict[str, object], eval_text: str) -> tuple[str, list[str]]:
    manifest_rel = nested_scalar_value(eval_text, "sut", "manifest")
    bundle_rel = scalar_value(eval_text, "prompt_bundle")
    if not manifest_rel:
        return "FAIL", ["sut.manifest is missing"]
    manifest_path = root / manifest_rel
    bundle_path = root / bundle_rel
    if not manifest_path.is_file():
        return "FAIL", [f"manifest missing: {relative(root, manifest_path)}"]
    if not bundle_path.is_file():
        return "FAIL", [f"prompt bundle missing: {relative(root, bundle_path)}"]

    manifest_paths = {(root / rel).resolve() for rel in quoted_paths(read_text(manifest_path))}
    bundle_components = section_blocks(read_text(bundle_path), "components")
    bundle_paths = {
        (root / str(component.get("path", ""))).resolve()
        for component in bundle_components
        if str(component.get("path", ""))
    }
    missing_from_manifest = sorted(relative(root, path) for path in bundle_paths - manifest_paths)
    if missing_from_manifest:
        return "FAIL", [f"bundle component path(s) missing from manifest artifacts: {', '.join(missing_from_manifest)}"]
    return "PASS", [f"{len(bundle_paths)} bundle component path(s) are declared in workflow manifest"]


def run_gate_contract(root: Path, grader: dict[str, object]) -> tuple[str, list[str]]:
    paths = grader_target_paths(root, grader)
    if not paths:
        return "FAIL", ["target missing"]
    gate_ids = as_list(grader.get("gate_ids"))
    required_terms = as_list(grader.get("required_terms"))
    manual_gates = as_list(grader.get("manual_gate_ids"))
    findings: list[str] = []
    evidence: list[str] = []
    for path in paths:
        if not path.is_file():
            findings.append(f"target missing: {relative(root, path)}")
            continue
        text = read_text(path)
        for gate_id in gate_ids:
            gate_pos = text.find(gate_id)
            if gate_pos < 0:
                findings.append(f"{relative(root, path)} missing {gate_id}")
                continue
            next_gate = re.search(r"\n##+\s+GATE-\d", text[gate_pos + len(gate_id) :])
            end = gate_pos + len(gate_id) + next_gate.start() if next_gate else min(len(text), gate_pos + 6000)
            block = text[gate_pos:end]
            for term in required_terms:
                if not re.search(re.escape(term), block, re.IGNORECASE):
                    findings.append(f"{relative(root, path)} {gate_id} missing contract term: {term}")
            if gate_id in manual_gates and not re.search(r"人工确认|approve|reject|HARD[-_]?STOP|⛔", block, re.IGNORECASE):
                findings.append(f"{relative(root, path)} {gate_id} missing manual hard-stop confirmation")
        if not findings:
            evidence.append(f"{relative(root, path)} declares {len(gate_ids)} gate contract(s)")
    if findings:
        return "FAIL", findings
    return "PASS", evidence or ["gate contract OK"]


def run_pattern_contract(root: Path, grader: dict[str, object], label: str) -> tuple[str, list[str]]:
    paths = grader_target_paths(root, grader)
    if not paths:
        return "FAIL", ["target missing: no files matched"]
    required_patterns = as_list(grader.get("required_patterns"))
    findings: list[str] = []
    evidence: list[str] = []
    for path in paths:
        if not path.is_file():
            findings.append(f"target missing: {relative(root, path)}")
            continue
        text = read_text(path)
        file_findings = check_required_patterns(text, required_patterns, label)
        if file_findings:
            findings.append(f"{relative(root, path)}: {'; '.join(file_findings)}")
        else:
            evidence.append(f"{relative(root, path)}: {len(required_patterns)} {label}(s) matched")
    if findings:
        return "FAIL", findings
    if len(evidence) > 5:
        evidence = evidence[:5] + [f"... and {len(evidence) - 5} more files OK"]
    return "PASS", evidence or ["pattern contract OK"]


def run_phase_skill_chain(root: Path, grader: dict[str, object]) -> tuple[str, list[str]]:
    return run_pattern_contract(root, grader, "phase skill chain pattern")


def run_hard_stop_confirmation(root: Path, grader: dict[str, object]) -> tuple[str, list[str]]:
    return run_pattern_contract(root, grader, "hard-stop confirmation pattern")


def run_artifact_trace_schema(root: Path, grader: dict[str, object]) -> tuple[str, list[str]]:
    if str(grader.get("match_scope", "")) == "combined":
        paths = grader_target_paths(root, grader)
        if not paths:
            return "FAIL", ["target missing: no files matched"]
        combined_parts: list[str] = []
        labels: list[str] = []
        for path in paths:
            if path.is_file():
                combined_parts.append(read_text(path))
                labels.append(relative(root, path))
        findings = check_required_patterns("\n".join(combined_parts), as_list(grader.get("required_patterns")), "artifact trace schema pattern")
        if findings:
            return "FAIL", findings
        return "PASS", [f"{len(labels)} file(s) collectively preserve artifact trace schema: {', '.join(labels[:5])}"]
    return run_pattern_contract(root, grader, "artifact trace schema pattern")


def run_candidate_decision_integrity(root: Path, grader: dict[str, object]) -> tuple[str, list[str]]:
    return run_pattern_contract(root, grader, "candidate decision pattern")


def run_deliverable_exact_schema(root: Path, grader: dict[str, object]) -> tuple[str, list[str]]:
    target_path = root / str(grader.get("target", ""))
    if not target_path.is_file():
        return "FAIL", [f"target missing: {relative(root, target_path)}"]
    text = read_text(target_path)
    findings = check_required_patterns(text, as_list(grader.get("required_patterns")), "deliverable schema pattern")
    expected_columns = as_list(grader.get("expected_columns"))
    if expected_columns:
        expected_row = "| " + " | ".join(expected_columns) + " |"
        if expected_row not in text:
            findings.append(f"standard table header not found exactly: {expected_row}")
    if findings:
        return "FAIL", findings
    return "PASS", [f"{relative(root, target_path)}: exact deliverable schema contract OK"]


# ---------------------------------------------------------------------------
# content_schema grader
# ---------------------------------------------------------------------------


def run_content_schema(root: Path, grader: dict[str, object]) -> tuple[str, list[str]]:
    """Validate that matched files contain required sections, patterns, and table columns.

    Grader configuration fields:
    - ``target`` / ``target_globs`` : which files to check.
    - ``required_sections`` : inline list of section headings that must appear
      as ``## <name>`` or ``### <name>`` lines.
    - ``required_patterns`` : inline list of regex patterns that must each match
      at least once somewhere in the file body.
    - ``table_header_text`` : (optional) string used to locate a table for column check.
    - ``table_min_columns`` : (optional) minimum column count for the located table.
    """
    required_sections_raw = [str(item) for item in grader.get("required_sections", [])]
    required_patterns = [str(item) for item in grader.get("required_patterns", [])]
    table_header_text = str(grader.get("table_header_text", ""))
    table_min_cols = int(grader.get("table_min_columns", 0))

    target_globs = [str(item) for item in grader.get("target_globs", [])]
    if target_globs:
        paths = glob_paths(root, target_globs)
    else:
        target_path = root / str(grader.get("target", ""))
        if not target_path.is_file():
            return "FAIL", [f"target missing: {relative(root, target_path)}"]
        paths = [target_path]

    if not paths:
        return "FAIL", ["target missing: no files matched target_globs"]

    findings: list[str] = []
    evidence: list[str] = []

    for path in paths:
        if not path.is_file():
            findings.append(f"target missing: {relative(root, path)}")
            continue
        try:
            text = read_text(path)
        except Exception:
            findings.append(f"cannot read: {relative(root, path)}")
            continue

        file_issues: list[str] = []

        # 1. Required sections (## or ### headings)
        for section in required_sections_raw:
            if not re.search(rf"^#{{2,3}}\s+{re.escape(section)}", text, re.MULTILINE):
                file_issues.append(f"missing section: '## {section}'")

        # 2. Required patterns
        for pattern in required_patterns:
            if not re.search(pattern, text):
                file_issues.append(f"missing pattern: {pattern}")

        # 3. Table column rule (optional flat field)
        if table_header_text and table_min_cols > 0:
            table = extract_table_block(text, table_header_text)
            if table is None:
                file_issues.append(f"table '{table_header_text}' not found")
            else:
                header_cols = count_table_columns(table[0])
                if header_cols < table_min_cols:
                    file_issues.append(f"table '{table_header_text}': {header_cols} cols (min {table_min_cols})")

        if file_issues:
            findings.append(f"{relative(root, path)}: {'; '.join(file_issues)}")
        else:
            evidence.append(f"{relative(root, path)}: all sections, patterns, and table rules OK")

    if findings:
        return "FAIL", findings
    if not evidence:
        return "PASS", ["no files checked"]
    if len(evidence) > 5:
        evidence = evidence[:5] + [f"... and {len(evidence) - 5} more files OK"]
    return "PASS", evidence


# ---------------------------------------------------------------------------
# state_machine grader
# ---------------------------------------------------------------------------


def run_state_machine(root: Path, grader: dict[str, object]) -> tuple[str, list[str]]:
    """Check that an agent definition declares formal states, transitions, and Gate keywords.

    Grader configuration fields:
    - ``target`` : single file path (required).
    - ``expected_states`` : list of state names that must appear as headings.
    - ``expected_transitions`` : list of regex patterns for phase→phase ordering.
    - ``required_gate_patterns`` : list of regex patterns for Gate declarations.
    - ``min_hard_stop_gates`` : minimum number of HARD-STOP / ⛔ STOP declarations.
    """
    target_path = root / str(grader.get("target", ""))
    if not target_path.is_file():
        return "FAIL", [f"target missing: {relative(root, target_path)}"]

    try:
        text = read_text(target_path)
    except Exception:
        return "FAIL", [f"cannot read: {relative(root, target_path)}"]

    findings: list[str] = []
    evidence: list[str] = []

    # 1. Expected states as headings
    expected_states: list[str] = [str(s) for s in grader.get("expected_states", [])]
    for state in expected_states:
        if re.search(rf"^#+\s+.*{re.escape(state)}", text, re.MULTILINE):
            evidence.append(f"state '{state}' found")
        else:
            findings.append(f"state not declared as heading: '{state}'")

    # 2. Expected transitions
    expected_transitions: list[str] = [str(t) for t in grader.get("expected_transitions", [])]
    for transition in expected_transitions:
        if re.search(transition, text, re.MULTILINE):
            evidence.append(f"transition pattern '{transition}' matched")
        else:
            findings.append(f"transition not found matching: '{transition}'")

    # 3. Required gate patterns
    required_gate_patterns: list[str] = [str(p) for p in grader.get("required_gate_patterns", [])]
    gates_found: set[str] = set()
    for pattern in required_gate_patterns:
        matches = re.findall(pattern, text, re.MULTILINE)
        gates_found.update(matches)
        if not matches:
            findings.append(f"no Gate matching pattern: '{pattern}'")
    if gates_found:
        evidence.append(f"{len(gates_found)} distinct gate identifiers: {', '.join(sorted(gates_found))}")

    # 4. Minimum HARD-STOP gate count
    min_hard_stop = int(grader.get("min_hard_stop_gates", 0))
    hard_stop_count = len(re.findall(r"HARD[-_]?STOP|⛔.*STOP|硬门控", text, re.IGNORECASE))
    if hard_stop_count < min_hard_stop:
        findings.append(f"only {hard_stop_count} HARD-STOP gates found (min {min_hard_stop})")
    else:
        evidence.append(f"{hard_stop_count} HARD-STOP gate declarations (min {min_hard_stop})")

    if findings:
        return "FAIL", findings
    return "PASS", evidence


# ---------------------------------------------------------------------------
# table_structure grader
# ---------------------------------------------------------------------------


def run_table_structure(root: Path, grader: dict[str, object]) -> tuple[str, list[str]]:
    """Auto-detect every markdown table in matched files and validate column alignment.

    Grader configuration fields:
    - ``target_globs`` : list of glob patterns selecting files to scan.
    """
    target_globs = [str(item) for item in grader.get("target_globs", [])]
    paths = glob_paths(root, target_globs)
    if not paths:
        return "FAIL", ["no files matched target_globs"]

    findings: list[str] = []
    evidence: list[str] = []
    total_tables = 0

    for path in paths:
        if not path.is_file():
            continue
        try:
            text = read_text(path)
        except Exception:
            findings.append(f"cannot read: {relative(root, path)}")
            continue

        tables = extract_all_tables(text)
        if not tables:
            continue
        total_tables += len(tables)
        file_ok = True

        for table_idx, table in enumerate(tables, 1):
            if len(table) < 2:
                findings.append(f"{relative(root, path)} table #{table_idx}: incomplete (only {len(table)} rows)")
                file_ok = False
                continue

            header = table[0]
            sep = table[1]
            data_rows = table[2:]

            expected_cols = count_table_columns(sep)
            if expected_cols == 0:
                findings.append(f"{relative(root, path)} table #{table_idx}: separator line is invalid")
                file_ok = False
                continue

            # Check every data row has the same column count
            for row_idx, row in enumerate(data_rows, 1):
                actual_cols = count_table_columns(row)
                if actual_cols != expected_cols:
                    findings.append(
                        f"{relative(root, path)} table #{table_idx} row {row_idx + 2}: "
                        f"{actual_cols} columns (expected {expected_cols})"
                    )
                    file_ok = False

            # Check for unescaped pipe inside cells
            for row_idx, row in enumerate(table, 1):
                if has_unescaped_pipe_in_cell(row):
                    findings.append(
                        f"{relative(root, path)} table #{table_idx} row {row_idx}: "
                        f"cell contains unescaped '|' (use '\\|')"
                    )
                    file_ok = False

        if file_ok:
            evidence.append(
                f"{relative(root, path)}: {len(tables)} table(s) OK "
                f"({sum(len(t) - 2 for t in tables)} data rows)"
            )

    if findings:
        if len(findings) > 10:
            findings = findings[:10] + [f"... and {len(findings) - 10} more issues"]
        return "FAIL", findings
    if not evidence:
        return "PASS", ["no markdown tables found in matched files"]
    if len(evidence) > 5:
        evidence = evidence[:5] + [f"... and {len(evidence) - 5} more files OK"]
    return "PASS", evidence


def run_table_schema(root: Path, grader: dict[str, object]) -> tuple[str, list[str]]:
    target_path = root / str(grader.get("target", ""))
    if not target_path.is_file():
        return "FAIL", [f"target missing: {relative(root, target_path)}"]
    expected_columns = as_list(grader.get("expected_columns"))
    if not expected_columns:
        return "FAIL", ["expected_columns is empty"]
    text = read_text(target_path)
    table = find_table_by_header_cells(text, expected_columns)
    if table is None:
        return "FAIL", [f"{relative(root, target_path)} missing table header: {' | '.join(expected_columns)}"]
    expected_cols = len(expected_columns)
    findings: list[str] = []
    for row_idx, row in enumerate(table[1:], 2):
        actual_cols = count_table_columns(row)
        if actual_cols != expected_cols:
            findings.append(
                f"{relative(root, target_path)} table row {row_idx}: {actual_cols} columns (expected {expected_cols})"
            )
    if findings:
        return "FAIL", findings
    return "PASS", [f"{relative(root, target_path)} table schema OK: {' | '.join(expected_columns)}"]


def resolved_local_path(root: Path, configured: str) -> Path:
    path = Path(configured).expanduser()
    if path.is_absolute():
        return path
    return (root / path).resolve()


def read_optional_text(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        return read_text(path)
    except UnicodeDecodeError:
        return ""


def state_phase_from_text(text: str) -> str:
    for key in ("current_phase", "phase", "status"):
        value = scalar_value(text, key)
        if value:
            return value
        nested = nested_scalar_value(text, "workflow", key)
        if nested:
            return nested
    for pattern in (
        r"^\s*(?:current_phase|phase|status):\s*['\"]?([^'\"\n#]+)",
        r"^\s*current_phase\s*=\s*['\"]([^'\"]+)",
    ):
        match = re.search(pattern, text, re.MULTILINE)
        if match:
            return strip_value(match.group(1))
    return ""


def collect_text_paths(workspace: Path, patterns: list[str]) -> list[Path]:
    if patterns:
        return [path for path in glob_paths(workspace, patterns) if path.is_file()]
    return [path for path in workspace.rglob("*") if path.is_file() and path.suffix.lower() in {".md", ".yaml", ".yml", ".json", ".txt"}]


def merge_list_field(sample: dict[str, object], grader: dict[str, object], field: str) -> list[str]:
    return as_list(sample.get(field)) or as_list(grader.get(field))


def scalar_field(sample: dict[str, object], grader: dict[str, object], field: str, default: str = "") -> str:
    value = sample.get(field)
    if value in (None, "", []):
        value = grader.get(field)
    if value in (None, []):
        return default
    return str(value)


def load_runtime_samples(root: Path, grader: dict[str, object]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    registry_rel = str(grader.get("sample_registry", "")).strip()
    if not registry_rel:
        sample = dict(grader)
        sample["id"] = str(grader.get("sample_id") or grader.get("id") or "inline-runtime-sample")
        return [sample], []

    registry_path = resolved_local_path(root, registry_rel)
    if not registry_path.is_file():
        return [], [{"path": registry_rel, "message": f"runtime sample registry missing: {registry_rel}"}]
    payload = parse_yaml_subset(read_text(registry_path))
    raw_samples = payload.get("samples") or payload.get("runtime_samples") or []
    if not isinstance(raw_samples, list):
        return [], [{"path": registry_rel, "message": "runtime sample registry must define samples list"}]

    requested_ids = set(as_list(grader.get("sample_ids")))
    requested_profile = str(grader.get("profile", "")).strip()
    samples: list[dict[str, object]] = []
    for item in raw_samples:
        if not isinstance(item, dict):
            continue
        sample_id = str(item.get("id", ""))
        sample_profile = str(item.get("profile", "full"))
        if requested_ids and sample_id not in requested_ids:
            continue
        if requested_profile and not requested_ids and sample_profile != requested_profile:
            continue
        merged = dict(grader)
        merged.update(item)
        if "id" not in merged:
            merged["id"] = sample_id or str(grader.get("id", "runtime-sample"))
        samples.append(merged)

    if requested_ids:
        found = {str(sample.get("id", "")) for sample in samples}
        missing = sorted(requested_ids - found)
        if missing:
            return samples, [{"path": registry_rel, "message": f"runtime sample id(s) not found: {', '.join(missing)}"}]
    return samples, []


def path_text_length(path: Path) -> int:
    if path.is_dir():
        return sum(path_text_length(child) for child in path.rglob("*") if child.is_file())
    return len(read_optional_text(path))


def phase_items(sample: dict[str, object]) -> list[dict[str, object]]:
    raw = sample.get("phases")
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    phase_order = as_list(sample.get("phase_order"))
    phase_paths = as_list(sample.get("phase_paths"))
    path_by_phase: dict[str, str] = {}
    for item in phase_paths:
        if "=" in item:
            key, value = item.split("=", 1)
            path_by_phase[key.strip()] = value.strip()
    return [{"id": phase, "path": path_by_phase.get(phase, "")} for phase in phase_order]


def ordered_terms_present(text: str, terms: list[str]) -> bool:
    cursor = 0
    for term in terms:
        match = re.search(re.escape(term), text[cursor:], re.IGNORECASE | re.DOTALL)
        if not match:
            return False
        cursor += match.end()
    return True


def trace_chains(sample: dict[str, object]) -> list[list[str]]:
    raw = sample.get("trace_chains") or sample.get("trace_chain") or sample.get("required_trace_terms")
    chains: list[list[str]] = []
    for item in as_list(raw):
        terms = [term.strip() for term in re.split(r"\s*(?:->|,|\|)\s*", item) if term.strip()]
        if terms:
            chains.append(terms)
    return chains


def runtime_sample_expected_status(sample: dict[str, object]) -> str:
    if parse_bool(sample.get("expected_blocked"), False):
        return "BLOCKED"
    expected = str(sample.get("expected_status") or sample.get("expected_result") or "PASS").upper()
    return expected if expected in SUPPORTED_RESULT_STATUSES else "PASS"


def sample_workspace(root: Path, sample: dict[str, object]) -> Path:
    workspace = str(sample.get("workspace", "")).strip()
    if not workspace:
        return root / "__MISSING_RUNTIME_WORKSPACE__"
    return resolved_local_path(root, workspace)


def run_one_runtime_sample(root: Path, grader: dict[str, object], sample: dict[str, object]) -> dict[str, object]:
    sample_id = str(sample.get("id") or grader.get("id") or "runtime-sample")
    workspace = sample_workspace(root, sample)
    profile = str(sample.get("profile") or grader.get("profile") or "full")
    required_paths = merge_list_field(sample, grader, "required_paths")
    required_skill_calls = merge_list_field(sample, grader, "required_skill_calls")
    required_gates = merge_list_field(sample, grader, "required_gates")
    required_patterns = merge_list_field(sample, grader, "required_patterns")
    target_globs = merge_list_field(sample, grader, "target_globs")
    placeholder_patterns = merge_list_field(sample, grader, "placeholder_patterns") or DEFAULT_PLACEHOLDER_PATTERNS
    forbidden_patterns = merge_list_field(sample, grader, "forbidden_patterns")
    expected_phase = scalar_field(sample, grader, "expected_phase")
    state_path = scalar_field(sample, grader, "state_path", "process/STATE.yaml")
    skill_calls_path = scalar_field(sample, grader, "skill_calls_path", "process/execution/SKILL-CALLS.yaml")
    gate_globs = merge_list_field(sample, grader, "gate_globs") or ["process/checks/*.md", "process/checkpoints/*.md", "process/**/*.md", "process/**/*.yaml"]
    min_tables = parse_int(sample.get("min_tables", grader.get("min_tables")), 0)
    min_phase_chars = parse_int(sample.get("min_phase_chars", grader.get("min_phase_chars")), 0)
    expected_status = runtime_sample_expected_status(sample)

    findings: list[str] = []
    failures: list[dict[str, object]] = []
    checked_paths: list[str] = []

    if not workspace.exists() or not workspace.is_dir():
        message = f"{sample_id}: runtime workspace missing: {workspace}"
        return {
            "sample_id": sample_id,
            "profile": profile,
            "status": "FAIL",
            "expected_status": expected_status,
            "messages": [message],
            "failures": [{"sample_id": sample_id, "path": str(workspace), "message": message}],
            "checked_paths": [],
            "checked_files": 0,
            "metrics": {"runtime_sample_count": 1, "runtime_fail_count": 1},
        }

    text_paths = collect_text_paths(workspace, target_globs)
    combined_text = "\n".join(read_optional_text(path) for path in text_paths)

    for rel_path in required_paths:
        candidate = workspace / rel_path
        if not candidate.exists():
            message = f"{sample_id}: missing runtime path: {rel_path}"
            findings.append(message)
            failures.append({"sample_id": sample_id, "path": rel_path, "message": message})
        else:
            checked_paths.append(rel_path)
            if candidate.is_file() and candidate.stat().st_size == 0:
                message = f"{sample_id}: runtime path is empty: {rel_path}"
                findings.append(message)
                failures.append({"sample_id": sample_id, "path": rel_path, "message": message})

    state_candidate = workspace / state_path
    if not state_candidate.exists():
        fallback_candidates = []
        if state_path.endswith(".yaml"):
            fallback_candidates.extend([workspace / state_path.removesuffix(".yaml"), workspace / f"{state_path.removesuffix('.yaml')}.md"])
        if state_path.endswith(".yml"):
            fallback_candidates.extend([workspace / state_path.removesuffix(".yml"), workspace / f"{state_path.removesuffix('.yml')}.md"])
        for fallback in fallback_candidates:
            if fallback.exists():
                state_candidate = fallback
                break
    state_text = read_optional_text(state_candidate)
    actual_phase = state_phase_from_text(state_text)
    if expected_phase:
        if not state_text:
            message = f"{sample_id}: state file missing or unreadable: {relative(workspace, state_candidate)}"
            findings.append(message)
            failures.append({"sample_id": sample_id, "path": relative(workspace, state_candidate), "message": message})
        elif actual_phase != expected_phase:
            message = f"{sample_id}: STATE phase mismatch: expected {expected_phase}, actual {actual_phase or '<missing>'}"
            findings.append(message)
            failures.append(
                {
                    "sample_id": sample_id,
                    "path": relative(workspace, state_candidate),
                    "expected_phase": expected_phase,
                    "actual_phase": actual_phase,
                    "message": message,
                }
            )

    skill_text = read_optional_text(workspace / skill_calls_path)
    for skill_name in required_skill_calls:
        if not re.search(rf"(^|[^A-Za-z0-9_-]){re.escape(skill_name)}([^A-Za-z0-9_-]|$)", skill_text):
            message = f"{sample_id}: missing required skill call: {skill_name}"
            findings.append(message)
            failures.append({"sample_id": sample_id, "path": skill_calls_path, "skill": skill_name, "message": message})

    gate_text_parts = [read_optional_text(path) for path in glob_paths(workspace, gate_globs)]
    gate_text = "\n".join(part for part in gate_text_parts if part)
    for gate_id in required_gates:
        if not re.search(re.escape(gate_id), gate_text, re.IGNORECASE):
            message = f"{sample_id}: missing required gate: {gate_id}"
            findings.append(message)
            failures.append({"sample_id": sample_id, "gate": gate_id, "message": message})

    observed_phase_positions: dict[str, int] = {}
    for phase in phase_items(sample):
        phase_id = str(phase.get("id") or phase.get("name") or "")
        phase_path = str(phase.get("path", "")).strip()
        phase_min_chars = parse_int(phase.get("min_chars", min_phase_chars), min_phase_chars)
        if not phase_id:
            continue
        if phase_path:
            candidate = workspace / phase_path
            if not candidate.exists():
                message = f"{sample_id}: phase {phase_id} artifact missing: {phase_path}"
                findings.append(message)
                failures.append({"sample_id": sample_id, "phase": phase_id, "path": phase_path, "message": message})
                continue
            checked_paths.append(phase_path)
            observed_phase_positions[phase_id] = len(observed_phase_positions)
            content_chars = path_text_length(candidate)
            if content_chars < phase_min_chars:
                message = f"{sample_id}: phase {phase_id} content density {content_chars} chars below minimum {phase_min_chars}"
                findings.append(message)
                failures.append(
                    {
                        "sample_id": sample_id,
                        "phase": phase_id,
                        "path": phase_path,
                        "actual_chars": content_chars,
                        "min_chars": phase_min_chars,
                        "message": message,
                    }
                )
        phase_patterns = as_list(phase.get("required_patterns"))
        phase_text = read_optional_text(workspace / phase_path) if phase_path else combined_text
        for pattern in phase_patterns:
            if not re.search(pattern, phase_text, re.IGNORECASE | re.DOTALL):
                message = f"{sample_id}: phase {phase_id} missing pattern: {pattern}"
                findings.append(message)
                failures.append({"sample_id": sample_id, "phase": phase_id, "pattern": pattern, "message": message})

    phase_order = as_list(sample.get("phase_order"))
    if phase_order:
        missing_in_order = [phase for phase in phase_order if phase not in observed_phase_positions and phase_items(sample)]
        if missing_in_order:
            message = f"{sample_id}: phase order incomplete, missing: {', '.join(missing_in_order)}"
            findings.append(message)
            failures.append({"sample_id": sample_id, "phase_order": phase_order, "missing": missing_in_order, "message": message})
        previous_pos = -1
        for phase in phase_order:
            if phase not in observed_phase_positions:
                continue
            pos = observed_phase_positions[phase]
            if pos < previous_pos:
                message = f"{sample_id}: phase order violation around {phase}"
                findings.append(message)
                failures.append({"sample_id": sample_id, "phase_order": phase_order, "message": message})
                break
            previous_pos = pos

    for pattern in required_patterns:
        if not re.search(pattern, combined_text, re.MULTILINE | re.IGNORECASE | re.DOTALL):
            message = f"{sample_id}: missing runtime output pattern: {pattern}"
            findings.append(message)
            failures.append({"sample_id": sample_id, "pattern": pattern, "message": message})

    for pattern in forbidden_patterns:
        if re.search(pattern, combined_text, re.MULTILINE | re.IGNORECASE | re.DOTALL):
            message = f"{sample_id}: forbidden runtime output pattern matched: {pattern}"
            findings.append(message)
            failures.append({"sample_id": sample_id, "pattern": pattern, "message": message})

    for path in text_paths:
        text = read_optional_text(path)
        if not text.strip():
            message = f"{sample_id}: text artifact is empty: {relative(workspace, path)}"
            findings.append(message)
            failures.append({"sample_id": sample_id, "path": relative(workspace, path), "message": message})
            continue
        for pattern in placeholder_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                message = f"{sample_id}: placeholder/template residue matched in {relative(workspace, path)}: {pattern}"
                findings.append(message)
                failures.append({"sample_id": sample_id, "path": relative(workspace, path), "pattern": pattern, "message": message})

    for terms in trace_chains(sample):
        if not ordered_terms_present(combined_text, terms):
            message = f"{sample_id}: trace chain not connected in order: {' -> '.join(terms)}"
            findings.append(message)
            failures.append({"sample_id": sample_id, "trace_chain": terms, "message": message})

    table_count = 0
    row_count = 0
    for path in text_paths:
        tables = extract_all_tables(read_optional_text(path))
        table_count += len(tables)
        row_count += sum(max(0, len(table) - 2) for table in tables)
    if table_count < min_tables:
        message = f"{sample_id}: runtime output table count {table_count} below minimum {min_tables}"
        findings.append(message)
        failures.append({"sample_id": sample_id, "expected_tables_min": min_tables, "actual_tables": table_count, "message": message})

    actual_status = "FAIL" if findings else "PASS"
    if expected_status == "BLOCKED":
        blocked_patterns = merge_list_field(sample, grader, "blocked_patterns") or ["blocked", "BLOCKED", "无法继续", "阻断"]
        blocked_found = any(re.search(pattern, combined_text + "\n" + state_text, re.IGNORECASE) for pattern in blocked_patterns)
        if blocked_found:
            actual_status = "BLOCKED"
            findings = []
            failures = []
        elif not findings:
            actual_status = "FAIL"
            message = f"{sample_id}: expected BLOCKED sample did not contain blocked evidence"
            findings.append(message)
            failures.append({"sample_id": sample_id, "message": message})

    metrics = {
        "runtime_sample_count": 1,
        "runtime_pass_count": 1 if actual_status == "PASS" else 0,
        "runtime_fail_count": 1 if actual_status == "FAIL" else 0,
        "runtime_blocked_count": 1 if actual_status == "BLOCKED" else 0,
        "required_path_count": len(required_paths),
        "required_skill_call_count": len(required_skill_calls),
        "required_gate_count": len(required_gates),
        "checked_text_files": len(text_paths),
        "table_count": table_count,
        "row_count": row_count,
    }
    if actual_phase:
        metrics["state_phase"] = actual_phase

    messages = findings if findings else [f"{sample_id}: runtime sample {actual_status} ({profile}) at {workspace}"]
    return {
        "sample_id": sample_id,
        "profile": profile,
        "status": actual_status,
        "expected_status": expected_status,
        "messages": messages,
        "failures": failures,
        "checked_paths": checked_paths,
        "checked_files": len(text_paths),
        "metrics": metrics,
    }


def run_runtime_artifact(root: Path, grader: dict[str, object]) -> dict[str, object]:
    samples, registry_failures = load_runtime_samples(root, grader)
    if registry_failures:
        return result_from_messages(
            grader,
            "FAIL",
            [str(item["message"]) for item in registry_failures],
            failures=registry_failures,
        )
    if not samples:
        return result_from_messages(grader, "SKIP", ["no runtime samples selected"], metrics={"runtime_sample_count": 0})

    sample_results = [run_one_runtime_sample(root, grader, sample) for sample in samples]
    failures: list[dict[str, object]] = []
    messages: list[str] = []
    checked_paths: list[str] = []
    checked_files = 0
    metrics: dict[str, object] = {
        "runtime_sample_count": len(sample_results),
        "runtime_pass_count": 0,
        "runtime_fail_count": 0,
        "runtime_blocked_count": 0,
        "profiles": sorted(set(str(result["profile"]) for result in sample_results)),
        "sample_statuses": {str(result["sample_id"]): str(result["status"]) for result in sample_results},
    }

    unexpected_failures = 0
    for result in sample_results:
        status = str(result["status"])
        expected_status = str(result["expected_status"])
        if status == "PASS":
            metrics["runtime_pass_count"] = int(metrics["runtime_pass_count"]) + 1
        if status == "FAIL":
            metrics["runtime_fail_count"] = int(metrics["runtime_fail_count"]) + 1
        if status == "BLOCKED":
            metrics["runtime_blocked_count"] = int(metrics["runtime_blocked_count"]) + 1
        checked_files += int(result["checked_files"])
        checked_paths.extend(str(path) for path in result["checked_paths"])
        messages.extend(str(message) for message in result["messages"])
        if status != expected_status:
            unexpected_failures += 1
            failures.extend(result["failures"] or [{"sample_id": result["sample_id"], "message": f"expected {expected_status}, got {status}"}])

    if unexpected_failures:
        overall_status = "FAIL"
    elif any(str(result["status"]) == "BLOCKED" for result in sample_results):
        overall_status = "BLOCKED"
    else:
        overall_status = "PASS"

    return result_from_messages(
        grader,
        overall_status,
        messages,
        checked_files=checked_files,
        checked_paths=sorted(set(checked_paths)),
        failures=failures,
        metrics=metrics,
    )


def manifest_or_tree_text(root: Path, grader: dict[str, object]) -> tuple[str, list[str], int]:
    scan_paths: list[Path] = []
    manifest_path = str(grader.get("manifest_path", "")).strip()
    installed_root = str(grader.get("installed_root", "")).strip()
    target_root = str(grader.get("target_root", "") or grader.get("target", "")).strip()
    if manifest_path:
        path = resolved_local_path(root, manifest_path)
        if path.is_file():
            scan_paths.append(path)
    for configured_root in [installed_root, target_root]:
        if not configured_root:
            continue
        base = resolved_local_path(root, configured_root)
        if base.is_dir():
            scan_paths.extend(path for path in base.rglob("*") if path.is_file() and path.suffix.lower() in {".md", ".toml", ".json", ".yaml", ".yml"})
    text_parts = [read_optional_text(path) for path in scan_paths]
    labels = [relative(root, path) for path in scan_paths]
    return "\n".join(text_parts), labels, len(scan_paths)


def resolve_platform_target(root: Path, target_root: str, contract_path: str) -> Path:
    if target_root:
        return resolved_local_path(root, target_root)
    if contract_path.startswith("~"):
        return Path.home()
    return root


def load_platform_contract(root: Path, contract_path: str) -> dict[str, object]:
    configured = contract_path or "delivery/doc/PLATFORM-CONTRACTS.yaml"
    path = resolved_local_path(root, configured)
    if not path.is_file():
        return {}
    text = read_text(path)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = parse_yaml_subset(text)
    return payload if isinstance(payload, dict) else {}


def contract_scope_paths(contract: dict[str, object], platform: str, scope: str) -> dict[str, object]:
    contracts = contract.get("contracts", {})
    if not isinstance(contracts, dict):
        return {}
    platform_contract = contracts.get(platform, {})
    if not isinstance(platform_contract, dict):
        return {}
    scopes = platform_contract.get("scopes", {})
    if not isinstance(scopes, dict):
        return {}
    selected = scopes.get(scope, {})
    return selected if isinstance(selected, dict) else {}


def contract_forbidden_paths(contract: dict[str, object], platform: str, scope: str) -> list[str]:
    contracts = contract.get("contracts", {})
    if not isinstance(contracts, dict):
        return []
    platform_contract = contracts.get(platform, {})
    if not isinstance(platform_contract, dict):
        return []
    forbidden = platform_contract.get("forbidden", {})
    if not isinstance(forbidden, dict):
        return []
    return as_list(forbidden.get(scope))


def resolve_contract_path(base: Path, configured: str) -> Path:
    if not configured:
        return base
    if configured.startswith("~/"):
        return Path.home() / configured[2:]
    candidate = Path(configured)
    if candidate.is_absolute():
        return candidate
    return base / configured


def directory_item_names(path: Path) -> set[str]:
    if not path.is_dir():
        return set()
    names: set[str] = set()
    for item in path.iterdir():
        names.add(item.stem if item.is_file() else item.name)
    return names


def run_platform_contract_install_checks(root: Path, grader: dict[str, object]) -> tuple[list[str], list[dict[str, object]], list[str], dict[str, object]]:
    platform = str(grader.get("platform", "")).strip()
    scope = str(grader.get("scope", "project")).strip() or "project"
    if not platform:
        return [], [], [], {}
    target_root = str(grader.get("target_root", "") or grader.get("target", "") or grader.get("installed_root", "")).strip()
    contract_path = str(grader.get("platform_contracts", "delivery/doc/PLATFORM-CONTRACTS.yaml")).strip()
    if not target_root and not str(grader.get("platform_contracts", "")).strip():
        return [], [], [], {}
    contract = load_platform_contract(root, contract_path)
    if not contract:
        return [], [], [], {}
    scope_paths = contract_scope_paths(contract, platform, scope)
    if not scope_paths:
        return [], [{"kind": "platform_contract", "message": f"platform contract missing scope {platform}/{scope}"}], [], {"platform_contract_checked": 0}

    base = resolve_platform_target(root, target_root, contract_path)
    failures: list[dict[str, object]] = []
    messages: list[str] = []
    checked_paths: list[str] = []
    expected_skills = set(as_list(grader.get("expected_skills")))
    expected_rules = set(as_list(grader.get("expected_rules")))
    agent = str(grader.get("agent", "")).strip()

    agents_dir = resolve_contract_path(base, str(scope_paths.get("agents", "")))
    skills_dir = resolve_contract_path(base, str(scope_paths.get("skills", "")))
    rules_path = resolve_contract_path(base, str(scope_paths.get("rules", "")))
    for path in (agents_dir, skills_dir, rules_path):
        checked_paths.append(path.as_posix())

    if agent:
        installed_agents = directory_item_names(agents_dir)
        if agent not in installed_agents:
            failures.append({"kind": "agent", "expected": agent, "path": agents_dir.as_posix(), "message": f"agent not installed at platform contract path: {agent}"})
        else:
            messages.append(f"agent installed at {agents_dir.as_posix()}: {agent}")
    if expected_skills:
        installed_skills = directory_item_names(skills_dir)
        for skill in sorted(expected_skills):
            skill_dir = skills_dir / skill
            if skill not in installed_skills and not (skill_dir / "SKILL.md").is_file():
                failures.append({"kind": "skill", "expected": skill, "path": skills_dir.as_posix(), "message": f"skill not installed at platform contract path: {skill}"})
            else:
                messages.append(f"skill installed at {skills_dir.as_posix()}: {skill}")
    if expected_rules:
        for rule in sorted(expected_rules):
            candidate = resolve_contract_path(base, rule)
            contract_rule = rules_path if rules_path.name == rule else rules_path.parent / rule
            if not candidate.exists() and not contract_rule.exists():
                failures.append({"kind": "rule", "expected": rule, "path": rules_path.as_posix(), "message": f"rule not installed at platform contract path: {rule}"})
            else:
                messages.append(f"rule installed for platform contract: {rule}")

    for forbidden in contract_forbidden_paths(contract, platform, scope):
        forbidden_path = resolve_contract_path(base, forbidden)
        checked_paths.append(forbidden_path.as_posix())
        if forbidden_path.exists():
            failures.append({"kind": "forbidden_path", "path": forbidden_path.as_posix(), "message": f"forbidden platform path exists: {forbidden}"})

    allowed_agents = set(as_list(grader.get("allowed_agents"))) | ({agent} if agent else set())
    allowed_skills = set(as_list(grader.get("allowed_skills"))) | expected_skills
    if allowed_agents and agents_dir.is_dir():
        stale_agents = sorted(directory_item_names(agents_dir) - allowed_agents)
        for stale in stale_agents:
            failures.append({"kind": "stale_agent", "actual": stale, "path": agents_dir.as_posix(), "message": f"stale agent installed: {stale}"})
    if allowed_skills and skills_dir.is_dir():
        stale_skills = sorted(directory_item_names(skills_dir) - allowed_skills)
        for stale in stale_skills:
            failures.append({"kind": "stale_skill", "actual": stale, "path": skills_dir.as_posix(), "message": f"stale skill installed: {stale}"})

    metrics = {
        "platform_contract_checked": 1,
        "expected_platform_skill_count": len(expected_skills),
        "expected_platform_rule_count": len(expected_rules),
        "checked_platform_paths": len(set(checked_paths)),
    }
    return messages, failures, sorted(set(checked_paths)), metrics


def run_install_mapping(root: Path, grader: dict[str, object]) -> dict[str, object]:
    platform = str(grader.get("platform", "")).strip()
    agent = str(grader.get("agent", "")).strip()
    expected_skills = as_list(grader.get("expected_skills"))
    expected_rules = as_list(grader.get("expected_rules"))
    text, labels, checked_files = manifest_or_tree_text(root, grader)
    target_root = str(grader.get("target_root", "") or grader.get("target", "") or grader.get("installed_root", "")).strip()
    uses_platform_contract = bool(target_root or str(grader.get("platform_contracts", "")).strip())
    findings: list[str] = []
    failures: list[dict[str, object]] = []

    if not text and not uses_platform_contract:
        message = "install mapping source missing: provide manifest_path or installed_root"
        findings.append(message)
        failures.append({"message": message})
    if text and not uses_platform_contract:
        for value, label in ((platform, "platform"), (agent, "agent")):
            if value and not re.search(re.escape(value), text, re.IGNORECASE):
                message = f"install mapping missing {label}: {value}"
                findings.append(message)
                failures.append({"field": label, "expected": value, "message": message})
        for skill in expected_skills:
            if not re.search(re.escape(skill), text, re.IGNORECASE):
                message = f"install mapping missing skill: {skill}"
                findings.append(message)
                failures.append({"kind": "skill", "expected": skill, "message": message})
        for rule in expected_rules:
            if not re.search(re.escape(rule), text, re.IGNORECASE):
                message = f"install mapping missing rule/resource: {rule}"
                findings.append(message)
                failures.append({"kind": "rule", "expected": rule, "message": message})

    platform_messages, platform_failures, platform_paths, platform_metrics = run_platform_contract_install_checks(root, grader)
    findings.extend(str(item.get("message", item)) for item in platform_failures)
    failures.extend(platform_failures)
    labels.extend(platform_paths)

    metrics = {
        "expected_skill_count": len(expected_skills),
        "expected_rule_count": len(expected_rules),
        "checked_install_files": checked_files,
        **platform_metrics,
    }
    messages = findings if findings else (platform_messages or [f"install mapping OK for platform={platform or 'n/a'} agent={agent or 'n/a'}"])
    return result_from_messages(
        grader,
        "FAIL" if findings else "PASS",
        messages,
        checked_files=checked_files,
        checked_paths=labels,
        failures=failures,
        metrics=metrics,
    )


def run_eval(
    eval_path: Path,
    out_dir: Path,
    *,
    allowed_authorizations: set[str] | None = None,
    only_types: set[str] | None = None,
) -> tuple[int, dict[str, object]]:
    root, issues = validate_eval_package(eval_path)
    eval_text = read_text(eval_path) if eval_path.is_file() else ""
    graders = section_blocks(eval_text, "graders") if eval_text else []
    grader_ids = {str(grader.get("id", "")) for grader in graders}
    allowed = allowed_authorizations or set(DEFAULT_ALLOWED_AUTHORIZATIONS)

    results: list[dict[str, object]] = []
    if not issues:
        for grader in graders:
            grader_id = str(grader.get("id", ""))
            grader_type = str(grader.get("type", ""))
            metadata = grader_metadata(grader)
            if only_types and grader_type not in only_types:
                continue
            if metadata["mode"] == "human-review":
                results.append(
                    result_from_messages(
                        grader,
                        "NEEDS_REVIEW",
                        [f"human-review grader {grader_id} requires manual review; no automatic PASS assigned"],
                    )
                )
                continue
            if metadata["authorization"] not in allowed:
                results.append(
                    result_from_messages(
                        grader,
                        "SKIP",
                        [f"grader authorization not allowed: {metadata['authorization']}"],
                        metrics={"authorization_required": metadata["authorization"]},
                    )
                )
                continue

            if grader_type == "runtime_artifact":
                results.append(run_runtime_artifact(root, grader))
                continue
            if grader_type == "install_mapping":
                results.append(run_install_mapping(root, grader))
                continue
            if grader_type == "required_fields":
                status, evidence = run_required_fields(root, grader)
            elif grader_type == "forbidden_patterns":
                status, evidence = run_forbidden_patterns(root, grader)
            elif grader_type == "path_exists":
                status, evidence = run_path_exists(root, grader)
            elif grader_type == "prompt_bundle_hashes":
                status, evidence = run_prompt_bundle_hashes(root, grader, eval_text)
            elif grader_type == "case_registry_links":
                status, evidence = run_case_registry_links(root, grader, eval_text, grader_ids)
            elif grader_type == "eval_config_non_empty":
                status, evidence = run_eval_config_non_empty(root, grader, eval_text)
            elif grader_type == "manifest_bundle_consistency":
                status, evidence = run_manifest_bundle_consistency(root, grader, eval_text)
            elif grader_type == "content_schema":
                status, evidence = run_content_schema(root, grader)
            elif grader_type == "state_machine":
                status, evidence = run_state_machine(root, grader)
            elif grader_type == "gate_contract":
                status, evidence = run_gate_contract(root, grader)
            elif grader_type == "phase_skill_chain":
                status, evidence = run_phase_skill_chain(root, grader)
            elif grader_type == "hard_stop_confirmation":
                status, evidence = run_hard_stop_confirmation(root, grader)
            elif grader_type == "artifact_trace_schema":
                status, evidence = run_artifact_trace_schema(root, grader)
            elif grader_type == "candidate_decision_integrity":
                status, evidence = run_candidate_decision_integrity(root, grader)
            elif grader_type == "deliverable_exact_schema":
                status, evidence = run_deliverable_exact_schema(root, grader)
            elif grader_type == "table_structure":
                status, evidence = run_table_structure(root, grader)
            elif grader_type == "table_schema":
                status, evidence = run_table_schema(root, grader)
            else:
                status, evidence = "FAIL", [f"unsupported grader type: {grader_type}"]
            results.append(result_from_messages(grader, status, evidence))

    result_by_id = {str(result.get("id")): str(result.get("status")) for result in results}
    registry_path = root / scalar_value(eval_text, "case_registry") if eval_text else Path()
    case_results: list[dict[str, object]] = []
    if registry_path.is_file():
        for case in section_blocks(read_text(registry_path), "cases"):
            case_id = str(case.get("id", ""))
            case_graders = as_list(case.get("graders"))
            if only_types:
                case_graders = [grader_id for grader_id in case_graders if grader_id in result_by_id]
                if not case_graders:
                    continue
            grader_statuses = [result_by_id.get(grader_id, "MISSING") for grader_id in case_graders]
            if grader_statuses and all(status == "PASS" for status in grader_statuses):
                case_status = "PASS"
            elif any(status == "FAIL" for status in grader_statuses):
                case_status = "FAIL"
            elif any(status == "BLOCKED" for status in grader_statuses):
                case_status = "BLOCKED"
            elif any(status == "NEEDS_REVIEW" for status in grader_statuses):
                case_status = "NEEDS_REVIEW"
            elif any(status == "SKIP" for status in grader_statuses):
                case_status = "SKIP"
            else:
                case_status = "FAIL"
            expected = str(case.get("expected_result", "PASS")) or "PASS"
            case_results.append(
                {
                    "id": case_id,
                    "category": str(case.get("category", "")),
                    "severity": str(case.get("severity", "")),
                    "blocking": parse_bool(case.get("blocking"), False),
                    "runtime_required": parse_bool(case.get("runtime_required"), False),
                    "requires_authorization": parse_bool(case.get("requires_authorization"), False),
                    "regression_asset": str(case.get("regression_asset", "")),
                    "source_issue": str(case.get("source_issue", "")),
                    "coverage_status": str(case.get("coverage_status", "")),
                    "last_verified_at": str(case.get("last_verified_at", "")),
                    "status": case_status,
                    "expected_result": expected,
                    "expected_match": case_status == expected,
                    "graders": case_graders,
                }
            )

    expected_nonpass_graders = {
        grader_id
        for case in case_results
        if str(case.get("expected_result")) in {"FAIL", "BLOCKED", "SKIP", "NEEDS_REVIEW"}
        for grader_id in case.get("graders", [])
    }
    expected_fail_graders = {
        grader_id
        for case in case_results
        if str(case.get("expected_result")) == "FAIL"
        for grader_id in case.get("graders", [])
    }
    unexpected_failed_graders = [
        str(result.get("id"))
        for result in results
        if result.get("status") != "PASS" and str(result.get("id")) not in expected_nonpass_graders
    ]
    incomplete_graders = [
        str(result.get("id"))
        for result in results
        if result.get("status") in NON_FAIL_INCOMPLETE_STATUSES
    ]
    status = (
        "PASS"
        if not issues
        and not unexpected_failed_graders
        and all(case.get("expected_match", True) for case in case_results)
        else "FAIL"
    )
    run_id = f"eval-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    summary: dict[str, object] = {
        "run_id": run_id,
        "created_at": now_iso(),
        "eval_path": eval_path.as_posix(),
        "suite_id": scalar_value(eval_text, "suite_id") if eval_text else "",
        "status": status,
        "issues": [issue.to_dict() for issue in issues],
        "grader_results": results,
        "case_results": case_results,
        "expected_fail_graders": sorted(expected_fail_graders),
        "expected_nonpass_graders": sorted(expected_nonpass_graders),
        "unexpected_failed_graders": unexpected_failed_graders,
        "incomplete_graders": incomplete_graders,
        "allowed_authorizations": sorted(allowed),
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "run-summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "run-summary.md").write_text(render_run_markdown(summary), encoding="utf-8")
    return (0 if status == "PASS" else 1), summary


def render_run_markdown(summary: dict[str, object]) -> str:
    lines = [
        f"# Eval Run {summary['run_id']}",
        "",
        f"- suite_id: `{summary.get('suite_id')}`",
        f"- status: `{summary.get('status')}`",
        f"- created_at: `{summary.get('created_at')}`",
        f"- eval_path: `{summary.get('eval_path')}`",
        "",
        "## Grader Results",
        "",
        "| Grader | Type | Status | Evidence |",
        "|---|---|---|---|",
    ]
    for result in summary.get("grader_results", []):
        evidence = render_evidence_cell(result.get("evidence", []))
        mode = result.get("mode", "static")
        auth = result.get("authorization", "none")
        lines.append(
            f"| `{result.get('id')}` | `{result.get('type')}` / `{mode}` / `{auth}` | "
            f"`{result.get('status')}` | {evidence} |"
        )
    lines.extend(["", "## Case Results", "", "| Case | Category | Severity | Status | Expected | Graders |", "|---|---|---|---|---|---|"])
    case_results = summary.get("case_results", [])
    if not case_results:
        lines.append("| N/A |  |  | `FAIL` |  | No case results generated |")
    else:
        for case in case_results:
            graders = ", ".join(str(item) for item in case.get("graders", []))
            lines.append(
                f"| `{case.get('id')}` | `{case.get('category')}` | `{case.get('severity', '')}` | "
                f"`{case.get('status')}` | `{case.get('expected_result')}` | {graders} |"
            )
    lines.extend(["", "## Issues", "", "| Severity | Code | Path | Message |", "|---|---|---|---|"])
    issues = summary.get("issues", [])
    if not issues:
        lines.append("| INFO | none |  | No package-level issues |")
    else:
        for issue in issues:
            lines.append(f"| {issue.get('severity')} | `{issue.get('code')}` | `{issue.get('path')}` | {issue.get('message')} |")
    lines.extend(
        [
            "",
            "## Expected Failures",
            "",
            f"- expected_fail_graders: `{', '.join(str(item) for item in summary.get('expected_fail_graders', [])) or 'none'}`",
            f"- expected_nonpass_graders: `{', '.join(str(item) for item in summary.get('expected_nonpass_graders', [])) or 'none'}`",
            f"- unexpected_failed_graders: `{', '.join(str(item) for item in summary.get('unexpected_failed_graders', [])) or 'none'}`",
            f"- incomplete_graders: `{', '.join(str(item) for item in summary.get('incomplete_graders', [])) or 'none'}`",
        ]
    )
    return "\n".join(lines) + "\n"


def load_run_summaries(runs_dir: Path) -> list[tuple[Path, dict[str, object]]]:
    summaries: list[tuple[Path, dict[str, object]]] = []
    for path in sorted(runs_dir.glob("**/run-summary.json")):
        try:
            summaries.append((path, json.loads(read_text(path))))
        except json.JSONDecodeError:
            summaries.append((path, {"run_id": path.parent.name, "status": "FAIL", "issues": [{"message": "invalid run-summary.json"}]}))
    return summaries


def load_eval_cases(eval_path: Path | None) -> list[dict[str, object]]:
    if not eval_path or not eval_path.is_file():
        return []
    root = eval_path.resolve().parent
    eval_text = read_text(eval_path)
    registry_path = root / scalar_value(eval_text, "case_registry")
    if not registry_path.is_file():
        return []
    return section_blocks(read_text(registry_path), "cases")


def case_metadata_rows(cases: list[dict[str, object]]) -> tuple[collections.Counter[str], int, int, int, int]:
    category_counter: collections.Counter[str] = collections.Counter()
    uncovered = 0
    runtime_required = 0
    source_issue_count = 0
    issue_with_regression = 0
    for case in cases:
        category_counter[str(case.get("category", "uncategorized"))] += 1
        coverage_status = str(case.get("coverage_status", "")).strip()
        if coverage_status in {"uncovered", "partial", "needs-triage"}:
            uncovered += 1
        if parse_bool(case.get("runtime_required"), False):
            runtime_required += 1
        if str(case.get("source_issue", "")).strip():
            source_issue_count += 1
            if str(case.get("regression_asset", "")).strip():
                issue_with_regression += 1
    return category_counter, uncovered, runtime_required, source_issue_count, issue_with_regression


def expand_metric_files(paths: Iterable[Path] | None, filenames: set[str]) -> list[Path]:
    expanded: list[Path] = []
    for path in paths or []:
        if path.is_dir():
            expanded.extend(item for item in path.rglob("*") if item.is_file() and item.name in filenames)
        elif path.is_file():
            expanded.append(path)
    return sorted(set(expanded))


def load_json_object(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(read_text(path))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def feedback_health_metrics(
    feedback_metrics_paths: Iterable[Path] | None = None,
    triage_paths: Iterable[Path] | None = None,
    backlog_paths: Iterable[Path] | None = None,
) -> dict[str, object]:
    metric_files = expand_metric_files(feedback_metrics_paths, {"feedback-metrics.json", "triage-metrics.json"})
    triage_files = expand_metric_files(triage_paths, {"triage-metrics.json", "TRIAGE-RESULTS.json", "ISSUE-DRAFTS.json", "GAPS.json", "EVAL-BACKLOG.json"})
    backlog_files = expand_metric_files(backlog_paths, {"EVAL-BACKLOG.json", "EVAL-BACKLOG.yaml", "EVAL-BACKLOG.yml"})

    metrics: dict[str, object] = {
        "field_feedback_count": 0,
        "normalized_run_exec_count": 0,
        "issue_draft_count": 0,
        "gap_count": 0,
        "backlog_count": 0,
        "backlog_open_count": 0,
        "environment_count": 0,
        "usage_count": 0,
        "duplicate_count": 0,
        "no_action_count": 0,
        "blocking_open_issue_count": 0,
        "open_p0_gap_count": 0,
        "regression_asset_coverage": 1.0,
        "feedback_evidence_files": [],
    }
    regression_weighted_numerator = 0.0
    regression_weighted_denominator = 0

    for path in sorted(set(metric_files + triage_files)):
        payload = load_json_object(path)
        if not payload:
            continue
        metrics["feedback_evidence_files"] = list(metrics["feedback_evidence_files"]) + [path.as_posix()]
        if "feedback_sample_count" in payload:
            metrics["field_feedback_count"] = int(metrics["field_feedback_count"]) + parse_int(payload.get("feedback_sample_count"), 0)
        metrics["normalized_run_exec_count"] = max(
            parse_int(metrics.get("normalized_run_exec_count"), 0),
            parse_int(payload.get("normalized_run_exec_count"), 0),
        )
        for key in (
            "issue_draft_count",
            "gap_count",
            "backlog_count",
            "environment_count",
            "usage_count",
            "duplicate_count",
            "no_action_count",
            "blocking_open_issue_count",
            "open_p0_gap_count",
        ):
            metrics[key] = int(metrics[key]) + parse_int(payload.get(key), 0)
        if "regression_asset_coverage" in payload and parse_int(payload.get("issue_draft_count"), 0):
            denominator = parse_int(payload.get("issue_draft_count"), 0)
            regression_weighted_numerator += float(payload.get("regression_asset_coverage", 0.0)) * denominator
            regression_weighted_denominator += denominator

    all_backlog_paths = set(backlog_files)
    for path in triage_files:
        if path.name == "EVAL-BACKLOG.json":
            all_backlog_paths.add(path)
    backlog_item_count = 0
    backlog_open_item_count = 0
    backlog_p0_item_count = 0
    backlog_blocking_issue_count = 0
    for path in sorted(all_backlog_paths):
        items = load_backlog_items(path)
        if not items:
            continue
        metrics["feedback_evidence_files"] = list(metrics["feedback_evidence_files"]) + [path.as_posix()]
        backlog_item_count += len(items)
        for item in items:
            if str(item.get("status", "pending")) != "closed":
                backlog_open_item_count += 1
                if str(item.get("priority", "")).upper() in {"P0", "BLOCKER"}:
                    backlog_p0_item_count += 1
            if str(item.get("source_issue", "")).startswith("ISSUE-DRAFT") and not str(item.get("regression_asset", "")).strip():
                backlog_blocking_issue_count += 1
    metrics["backlog_count"] = max(parse_int(metrics.get("backlog_count"), 0), backlog_item_count)
    metrics["backlog_open_count"] = max(parse_int(metrics.get("backlog_open_count"), 0), backlog_open_item_count)
    metrics["open_p0_gap_count"] = max(parse_int(metrics.get("open_p0_gap_count"), 0), backlog_p0_item_count)
    metrics["blocking_open_issue_count"] = max(parse_int(metrics.get("blocking_open_issue_count"), 0), backlog_blocking_issue_count)

    if regression_weighted_denominator:
        metrics["regression_asset_coverage"] = regression_weighted_numerator / regression_weighted_denominator
    metrics["feedback_evidence_files"] = sorted(set(str(path) for path in metrics["feedback_evidence_files"]))
    return metrics


def suite_health(
    runs_dir: Path,
    out_path: Path | None,
    eval_path: Path | None = None,
    stale_days: int = 30,
    *,
    feedback_metrics_paths: Iterable[Path] | None = None,
    triage_paths: Iterable[Path] | None = None,
    backlog_paths: Iterable[Path] | None = None,
) -> tuple[int, str]:
    summaries = load_run_summaries(runs_dir)
    total = 0
    passed = 0
    failed = 0
    run_rows: list[str] = []
    runs_by_week: collections.Counter[str] = collections.Counter()
    grader_type_distribution: collections.Counter[str] = collections.Counter()
    case_category_distribution: collections.Counter[str] = collections.Counter()
    grader_status_by_id: dict[str, list[str]] = collections.defaultdict(list)
    unexpected_failures: list[str] = []
    expected_failures: list[str] = []
    disabled_graders: list[str] = []
    runtime_sample_count = 0
    runtime_pass_count = 0
    runtime_fail_count = 0
    runtime_blocked_count = 0
    feedback_sample_count = 0
    normalized_run_exec_count = 0
    issue_draft_count = 0
    gap_count = 0
    backlog_open_count = 0
    blocking_open_issue_count = 0
    open_p0_gap_count = 0

    for path, data in summaries:
        total += 1
        status = str(data.get("status", "UNKNOWN"))
        if status == "PASS":
            passed += 1
        else:
            failed += 1
        created_at = parse_timestamp(data.get("created_at"))
        week = created_at.strftime("%G-W%V") if created_at else "unknown"
        runs_by_week[week] += 1
        run_rows.append(f"| `{data.get('run_id')}` | `{status}` | `{week}` | `{relative(runs_dir, path.parent)}` |")
        unexpected_failures.extend(str(item) for item in data.get("unexpected_failed_graders", []))
        expected_failures.extend(str(item) for item in data.get("expected_fail_graders", []))
        for result in data.get("grader_results", []):
            grader_id = str(result.get("id", ""))
            grader_type = str(result.get("type", "unknown"))
            result_status = str(result.get("status", "UNKNOWN"))
            grader_type_distribution[grader_type] += 1
            grader_status_by_id[grader_id].append(result_status)
            if result_status in {"SKIP", "NEEDS_REVIEW"}:
                disabled_graders.append(grader_id)
            evidence = result.get("evidence", {})
            if isinstance(evidence, dict):
                metrics = evidence.get("metrics", {})
                if isinstance(metrics, dict):
                    runtime_sample_count += parse_int(metrics.get("runtime_sample_count"), 0)
                    runtime_pass_count += parse_int(metrics.get("runtime_pass_count"), 0)
                    runtime_fail_count += parse_int(metrics.get("runtime_fail_count"), 0)
                    runtime_blocked_count += parse_int(metrics.get("runtime_blocked_count"), 0)
                    feedback_sample_count += parse_int(metrics.get("feedback_sample_count"), 0)
                    normalized_run_exec_count += parse_int(metrics.get("normalized_run_exec_count"), 0)
        for case in data.get("case_results", []):
            case_category_distribution[str(case.get("category", "uncategorized"))] += 1

    feedback_metrics = feedback_health_metrics(feedback_metrics_paths, triage_paths, backlog_paths)
    feedback_sample_count += parse_int(feedback_metrics.get("field_feedback_count"), 0)
    normalized_run_exec_count += parse_int(feedback_metrics.get("normalized_run_exec_count"), 0)
    issue_draft_count = parse_int(feedback_metrics.get("issue_draft_count"), 0)
    gap_count = parse_int(feedback_metrics.get("gap_count"), 0)
    backlog_open_count = parse_int(feedback_metrics.get("backlog_open_count"), 0)
    blocking_open_issue_count = parse_int(feedback_metrics.get("blocking_open_issue_count"), 0)
    open_p0_gap_count = parse_int(feedback_metrics.get("open_p0_gap_count"), 0)

    cases = load_eval_cases(eval_path)
    registry_category_distribution, uncovered_cases, runtime_required_cases, source_issue_count, issue_with_regression = case_metadata_rows(cases)
    if registry_category_distribution:
        case_category_distribution.update(registry_category_distribution)
    issue_to_regression_ratio = (issue_with_regression / source_issue_count) if source_issue_count else 1.0
    pass_rate = (passed / total) if total else 0.0
    flaky_graders = sorted(
        grader_id
        for grader_id, statuses in grader_status_by_id.items()
        if len(set(statuses)) > 1 and "PASS" in statuses and any(status != "PASS" for status in statuses)
    )

    now = dt.datetime.now(dt.timezone.utc)
    stale_cases: list[str] = []
    for case in cases:
        verified_at = parse_timestamp(case.get("last_verified_at"))
        if not verified_at or (now - verified_at).days > stale_days:
            stale_cases.append(str(case.get("id", "<unknown>")))

    uncovered_categories = sorted(
        category
        for category, count in case_category_distribution.items()
        if count == 0 or category in {"uncovered", "needs-triage"}
    )
    if uncovered_cases:
        uncovered_categories.append(f"coverage_status_gap:{uncovered_cases}")

    health = "PASS" if total > 0 and failed == 0 and not uncovered_cases and not flaky_graders else "FAIL"

    def counter_rows(counter: collections.Counter[str]) -> list[str]:
        return [f"| `{key}` | {value} |" for key, value in sorted(counter.items())] or ["| N/A | 0 |"]

    text = "\n".join(
        [
            "# Eval Suite Health",
            "",
            f"- status: `{health}`",
            f"- total_runs: `{total}`",
            f"- passed: `{passed}`",
            f"- failed: `{failed}`",
            f"- pass_rate: `{pass_rate:.2%}`",
            f"- unexpected_failures: `{len(unexpected_failures)}`",
            f"- expected_failures: `{len(expected_failures)}`",
            f"- stale_cases: `{len(stale_cases)}`",
            f"- uncovered_categories: `{len(uncovered_categories)}`",
            f"- runtime_sample_count: `{runtime_sample_count}`",
            f"- runtime_pass_count: `{runtime_pass_count}`",
            f"- runtime_fail_count: `{runtime_fail_count}`",
            f"- runtime_blocked_count: `{runtime_blocked_count}`",
            f"- feedback_sample_count: `{feedback_sample_count}`",
            f"- normalized_run_exec_count: `{normalized_run_exec_count}`",
            f"- issue_draft_count: `{issue_draft_count}`",
            f"- gap_count: `{gap_count}`",
            f"- backlog_open_count: `{backlog_open_count}`",
            f"- blocking_open_issue_count: `{blocking_open_issue_count}`",
            f"- open_p0_gap_count: `{open_p0_gap_count}`",
            f"- feedback_regression_asset_coverage: `{float(feedback_metrics.get('regression_asset_coverage', 1.0)):.2%}`",
            f"- issue_to_regression_ratio: `{issue_to_regression_ratio:.2%}`",
            f"- flaky_graders: `{len(flaky_graders)}`",
            f"- disabled_graders: `{len(disabled_graders)}`",
            "",
            "## Runs By Week",
            "",
            "| Week | Runs |",
            "|---|---|",
            *counter_rows(runs_by_week),
            "",
            "## Grader Type Distribution",
            "",
            "| Grader Type | Count |",
            "|---|---|",
            *counter_rows(grader_type_distribution),
            "",
            "## Case Category Distribution",
            "",
            "| Category | Count |",
            "|---|---|",
            *counter_rows(case_category_distribution),
            "",
            "## Run Evidence",
            "",
            "| Run | Status | Week | Path |",
            "|---|---|---|---|",
            *(run_rows or ["| N/A | `FAIL` | unknown | no run-summary.json files found |"]),
            "",
            "## Risk Notes",
            "",
            f"- unexpected_failed_graders: `{', '.join(sorted(set(unexpected_failures))) or 'none'}`",
            f"- expected_fail_graders: `{', '.join(sorted(set(expected_failures))) or 'none'}`",
            f"- stale_cases: `{', '.join(stale_cases[:20]) or 'none'}`",
            f"- uncovered_categories: `{', '.join(uncovered_categories) or 'none'}`",
            f"- flaky_graders: `{', '.join(flaky_graders) or 'none'}`",
            f"- disabled_graders: `{', '.join(sorted(set(disabled_graders))) or 'none'}`",
            f"- feedback_evidence_files: `{', '.join(feedback_metrics.get('feedback_evidence_files', [])) or 'none'}`",
            "",
        ]
    )
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
    return (0 if health == "PASS" else 1), text


def latest_summary(summaries: list[tuple[Path, dict[str, object]]]) -> tuple[Path, dict[str, object]] | None:
    if not summaries:
        return None
    return sorted(summaries, key=lambda item: str(item[1].get("created_at", "")))[-1]


def release_check(
    eval_path: Path,
    runs_dir: Path,
    out_path: Path | None = None,
    *,
    profile: str = "release",
    json_out: Path | None = None,
    feedback_metrics_paths: Iterable[Path] | None = None,
    triage_paths: Iterable[Path] | None = None,
    backlog_paths: Iterable[Path] | None = None,
) -> tuple[int, str, dict[str, object]]:
    cases = load_eval_cases(eval_path)
    eval_root, eval_issues = validate_eval_package(eval_path)
    eval_text = read_text(eval_path) if eval_path.is_file() else ""
    configured_graders = section_blocks(eval_text, "graders") if eval_text else []
    configured_by_id = {str(grader.get("id", "")): grader for grader in configured_graders}
    summaries = load_run_summaries(runs_dir)
    latest = latest_summary(summaries)
    blocking_failures: list[dict[str, str]] = []
    risk_items: list[dict[str, str]] = []
    required_evidence = ["eval_run", "suite_health"]

    for issue in eval_issues:
        blocking_failures.append({"severity": issue.severity, "code": issue.code, "message": issue.message})
    if latest is None:
        blocking_failures.append({"severity": "BLOCKER", "code": "missing-run-evidence", "message": "No run-summary.json files found"})
        latest_data: dict[str, object] = {}
    else:
        latest_data = latest[1]
        if not latest_data.get("run_id"):
            blocking_failures.append({"severity": "BLOCKER", "code": "run-id-missing", "message": "Latest eval run evidence has no run_id"})
        if latest_data.get("status") != "PASS":
            blocking_failures.append({"severity": "BLOCKER", "code": "latest-run-failed", "message": f"Latest eval run status is {latest_data.get('status')}"})

    case_result_by_id = {str(case.get("id")): case for case in latest_data.get("case_results", [])} if latest_data else {}
    result_by_id = {str(result.get("id")): result for result in latest_data.get("grader_results", [])} if latest_data else {}
    runtime_results = [
        result
        for result in latest_data.get("grader_results", [])
        if str(result.get("type")) == "runtime_artifact" and str(result.get("status")) == "PASS"
    ] if latest_data else []
    if runtime_results:
        required_evidence.append("runtime_artifact")

    prompt_hash_graders = [grader for grader in configured_graders if str(grader.get("type")) == "prompt_bundle_hashes"]
    if prompt_hash_graders:
        for grader in prompt_hash_graders:
            grader_id = str(grader.get("id", ""))
            result = result_by_id.get(grader_id, {})
            if result.get("status") != "PASS":
                blocking_failures.append(
                    {
                        "severity": "BLOCKER",
                        "code": "prompt-bundle-hash-not-pass",
                        "message": f"prompt_bundle_hashes grader {grader_id} status is {result.get('status', 'MISSING')}",
                    }
                )
    else:
        target = blocking_failures if profile == "release" else risk_items
        target.append({"severity": "BLOCKER" if profile == "release" else "MEDIUM", "code": "prompt-bundle-hash-grader-missing", "message": "No prompt_bundle_hashes grader configured"})

    for grader_id, grader in configured_by_id.items():
        grader_profiles = set(as_list(grader.get("profiles")))
        if grader_profiles and profile not in grader_profiles:
            continue
        requirement = str(grader.get("profile_requirement") or grader.get("requirement") or ("optional" if str(grader.get("blocking_policy")) == "advisory" else "required"))
        result = result_by_id.get(grader_id)
        status = str(result.get("status", "MISSING")) if result else "MISSING"
        if requirement == "required" and status != "PASS":
            blocking_failures.append(
                {
                    "severity": "BLOCKER",
                    "code": "required-grader-not-pass",
                    "message": f"{profile} required grader {grader_id} status is {status}",
                }
            )
        elif requirement == "recommended" and status != "PASS":
            risk_items.append(
                {
                    "severity": "MEDIUM",
                    "code": "recommended-grader-not-pass",
                    "message": f"{profile} recommended grader {grader_id} status is {status}",
                }
            )

    for case in cases:
        case_id = str(case.get("id", ""))
        severity = str(case.get("severity", "") or "MEDIUM").upper()
        blocking = parse_bool(case.get("blocking"), False)
        coverage_status = str(case.get("coverage_status", "")).strip()
        source_issue = str(case.get("source_issue", "")).strip()
        regression_asset = str(case.get("regression_asset", "")).strip()
        runtime_required = parse_bool(case.get("runtime_required"), False)
        case_result = case_result_by_id.get(case_id, {})
        case_status = str(case_result.get("status", "MISSING"))
        expected_match = bool(case_result.get("expected_match", False))
        expected_result = str(case_result.get("expected_result") or case.get("expected_result") or "PASS")

        if blocking and not expected_match:
            blocking_failures.append(
                {
                    "severity": "BLOCKER",
                    "code": "blocking-case-not-pass",
                    "message": f"{case_id} is blocking and expected {expected_result} but got {case_status}",
                }
            )
        if not expected_match and case_result:
            blocking_failures.append(
                {
                    "severity": "BLOCKER",
                    "code": "expected-result-mismatch",
                    "message": f"{case_id} expected {case_result.get('expected_result')} but got {case_status}",
                }
            )
        if severity in {"BLOCKER", "HIGH"} and coverage_status in {"uncovered", "needs-triage"}:
            blocking_failures.append(
                {
                    "severity": severity,
                    "code": "high-risk-uncovered",
                    "message": f"{case_id} severity={severity} coverage_status={coverage_status}",
                }
            )
        if runtime_required and not runtime_results:
            blocking_failures.append(
                {
                    "severity": "HIGH",
                    "code": "runtime-sample-missing",
                    "message": f"{case_id} requires runtime evidence but no passing runtime_artifact grader result exists",
                }
            )
        if source_issue and not regression_asset:
            blocking_failures.append(
                {
                    "severity": "HIGH",
                    "code": "issue-without-regression-asset",
                    "message": f"{case_id} links source_issue={source_issue} but has no regression_asset",
                }
            )

    recent = sorted(summaries, key=lambda item: str(item[1].get("created_at", "")))[-5:]
    recent_failed = sum(1 for _, data in recent if data.get("status") != "PASS")
    if len(recent) >= 3 and recent_failed >= 2:
        risk_items.append({"severity": "MEDIUM", "code": "suite-health-recent-degradation", "message": f"{recent_failed} of last {len(recent)} eval runs are non-PASS"})

    if any(str(result.get("status")) in NON_FAIL_INCOMPLETE_STATUSES for result in latest_data.get("grader_results", [])):
        risk_items.append({"severity": "MEDIUM", "code": "incomplete-advisory-graders", "message": "Some graders were skipped or need human review"})

    feedback_metrics = feedback_health_metrics(feedback_metrics_paths=feedback_metrics_paths, triage_paths=triage_paths, backlog_paths=backlog_paths)
    if feedback_metrics.get("feedback_evidence_files"):
        required_evidence.append("feedback_triage")
    open_p0_gap_count = parse_int(feedback_metrics.get("open_p0_gap_count"), 0)
    blocking_open_issue_count = parse_int(feedback_metrics.get("blocking_open_issue_count"), 0)
    regression_asset_coverage = float(feedback_metrics.get("regression_asset_coverage", 1.0))
    if open_p0_gap_count:
        blocking_failures.append(
            {
                "severity": "BLOCKER",
                "code": "open-p0-eval-gap",
                "message": f"{open_p0_gap_count} open P0 eval GAP/backlog item(s) remain unresolved",
            }
        )
    if blocking_open_issue_count:
        blocking_failures.append(
            {
                "severity": "HIGH",
                "code": "blocking-feedback-issue-without-regression",
                "message": f"{blocking_open_issue_count} blocking/high feedback issue(s) have no regression asset",
            }
        )
    if regression_asset_coverage < 1.0:
        risk_items.append(
            {
                "severity": "MEDIUM",
                "code": "feedback-regression-coverage-incomplete",
                "message": f"feedback issue regression asset coverage is {regression_asset_coverage:.2%}",
            }
        )

    release_decision = "BLOCKED" if blocking_failures else ("PASS_WITH_RISK" if risk_items else "PASS")
    payload: dict[str, object] = {
        "release_decision": release_decision,
        "profile": profile,
        "eval_path": eval_path.as_posix(),
        "runs_dir": runs_dir.as_posix(),
        "latest_run_id": str(latest_data.get("run_id", "")),
        "blocking_failures": blocking_failures,
        "risk_items": risk_items,
        "required_evidence": required_evidence,
        "runtime_artifact_pass_count": len(runtime_results),
        "feedback_metrics": feedback_metrics,
    }

    lines = [
        "# Eval Release Check",
        "",
        f"- release_decision: `{release_decision}`",
        f"- profile: `{profile}`",
        f"- eval: `{eval_path}`",
        f"- runs: `{runs_dir}`",
        f"- latest_run: `{latest_data.get('run_id', 'none')}`",
        f"- runtime_artifact_pass_count: `{len(runtime_results)}`",
        f"- open_p0_gap_count: `{open_p0_gap_count}`",
        f"- blocking_open_issue_count: `{blocking_open_issue_count}`",
        f"- required_evidence: `{', '.join(required_evidence)}`",
        "",
        "## Blocking Failures",
        "",
        "| Severity | Code | Message |",
        "|---|---|---|",
    ]
    if blocking_failures:
        for finding in blocking_failures:
            lines.append(f"| {finding['severity']} | `{finding['code']}` | {finding['message']} |")
    else:
        lines.append("| INFO | `none` | No release-blocking eval findings |")
    lines.extend(["", "## Risk Items", "", "| Severity | Code | Message |", "|---|---|---|"])
    if risk_items:
        for finding in risk_items:
            lines.append(f"| {finding['severity']} | `{finding['code']}` | {finding['message']} |")
    else:
        lines.append("| INFO | `none` | No release risk items |")
    text = "\n".join(lines) + "\n"
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
    if json_out:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return (0 if release_decision in {"PASS", "PASS_WITH_RISK"} else 1), text, payload


def feedback_sources(eval_path: Path) -> list[dict[str, object]]:
    if not eval_path.is_file():
        return []
    return section_blocks(read_text(eval_path), "feedback_sources")


def copy_local_feedback_source(source_path: Path, target_dir: Path) -> None:
    if target_dir.exists():
        shutil.rmtree(target_dir)
    if source_path.is_dir():
        shutil.copytree(source_path, target_dir)
        return
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target_dir / source_path.name)


def safe_extract_zip(archive: zipfile.ZipFile, target_dir: Path) -> None:
    target_root = target_dir.resolve()
    for member in archive.infolist():
        destination = (target_dir / member.filename).resolve()
        if not str(destination).startswith(str(target_root) + "/") and destination != target_root:
            raise ValueError(f"archive member escapes target directory: {member.filename}")
    archive.extractall(target_dir)


def feedback_pull(eval_path: Path, out_dir: Path, allow_git_read: bool = False) -> tuple[int, dict[str, object]]:
    root = eval_path.resolve().parent
    sources = feedback_sources(eval_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []
    for source in sources:
        source_id = str(source.get("id", ""))
        source_type = str(source.get("type", "local"))
        target_dir = out_dir / source_id
        if source_type in {"local", "ci-artifact", "run-exec"}:
            source_path = resolved_local_path(root, str(source.get("path", "")))
            if not source_path.exists():
                results.append({"id": source_id, "type": source_type, "status": "FAIL", "message": f"source path missing: {source_path}"})
                continue
            copy_local_feedback_source(source_path, target_dir)
            results.append({"id": source_id, "type": source_type, "status": "PASS", "path": str(target_dir)})
            continue
        if source_type == "archive":
            archive_path = resolved_local_path(root, str(source.get("path") or source.get("archive") or ""))
            if not archive_path.is_file():
                results.append({"id": source_id, "type": source_type, "status": "FAIL", "message": f"archive missing: {archive_path}"})
                continue
            if target_dir.exists():
                shutil.rmtree(target_dir)
            target_dir.mkdir(parents=True, exist_ok=True)
            if zipfile.is_zipfile(archive_path):
                try:
                    with zipfile.ZipFile(archive_path) as archive:
                        safe_extract_zip(archive, target_dir)
                except ValueError as error:
                    results.append({"id": source_id, "type": source_type, "status": "FAIL", "message": str(error)})
                    continue
            else:
                shutil.copy2(archive_path, target_dir / archive_path.name)
            results.append({"id": source_id, "type": source_type, "status": "PASS", "path": str(target_dir)})
            continue
        if source_type in {"git", "gitlab"}:
            repo = str(source.get("repo", ""))
            branch = str(source.get("branch", "main"))
            subpath = str(source.get("path", ""))
            if not allow_git_read:
                results.append(
                    {
                        "id": source_id,
                        "type": source_type,
                        "status": "SKIP",
                        "authorization_required": "git-read",
                        "message": "git feedback source requires --allow-git-read",
                    }
                )
                continue
            if target_dir.exists():
                shutil.rmtree(target_dir)
            clone_dir = out_dir / f".{source_id}-repo"
            if clone_dir.exists():
                shutil.rmtree(clone_dir)
            completed = subprocess.run(
                ["git", "clone", "--depth", "1", "--branch", branch, repo, str(clone_dir)],
                check=False,
                capture_output=True,
                text=True,
            )
            if completed.returncode != 0:
                results.append({"id": source_id, "type": source_type, "status": "FAIL", "message": completed.stderr.strip()})
                continue
            source_subpath = clone_dir / subpath if subpath else clone_dir
            if source_subpath.is_dir():
                shutil.copytree(source_subpath, target_dir)
            else:
                target_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_subpath, target_dir / source_subpath.name)
            results.append({"id": source_id, "type": source_type, "status": "PASS", "path": str(target_dir)})
            continue
        results.append({"id": source_id, "type": source_type, "status": "FAIL", "message": f"unsupported feedback source type: {source_type}"})

    summary = {"created_at": now_iso(), "eval_path": eval_path.as_posix(), "results": results}
    (out_dir / "feedback-pull-summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return (0 if all(item.get("status") in {"PASS", "SKIP"} for item in results) else 1), summary


def detect_feedback_status(text: str) -> str:
    lowered = text.lower()
    negated_block = any(term in lowered for term in ("no blocked", "not blocked", "without blocked", "no blocker"))
    negated_fail = any(term in lowered for term in ("no fail", "no failure", "not failed", "without failure", "no error"))
    if not text.strip():
        return "SKIPPED"
    if not negated_block and any(term in lowered for term in ("blocked", "blocker", "cannot proceed", "stuck", "无法继续")):
        return "BLOCKED"
    if not negated_fail and any(term in lowered for term in ("fail", "failed", "failure", "error", "exception", "traceback", "失败", "报错")):
        return "FAIL"
    return "PASS"


def infer_feedback_stage(text: str) -> str:
    lowered = text.lower()
    stage_terms = [
        ("runtime_artifact", ("runtime", "workspace", "artifact", "state.yaml", "run-exec", "运行产物")),
        ("install", ("install", "mapping", "agent missing", "skill missing", "安装")),
        ("feedback", ("feedback", "collect", "field", "现场")),
        ("release", ("release", "gate", "发布")),
        ("static_eval", ("prompt", "bundle", "case registry", "schema")),
    ]
    for stage, terms in stage_terms:
        if any(term in lowered for term in terms):
            return stage
    return "unknown"


def infer_feedback_category(text: str, status: str) -> str:
    lowered = text.lower()
    if any(term in lowered for term in ("duplicate", "duplicated", "重复")):
        return "duplicate"
    if any(term in lowered for term in ("environment", "env ", "permission", "network", "timeout", "dependency", "环境", "权限")):
        return "environment"
    if any(term in lowered for term in ("usage", "how to", "invalid input", "user mistake", "误用", "使用方式")):
        return "usage"
    if any(term in lowered for term in ("coverage gap", "not covered", "uncovered", "missing grader", "missing case", "缺少 grader", "覆盖不到")):
        return "coverage_gap"
    if any(term in lowered for term in ("improve", "enhancement", "nice to have", "建议", "优化")):
        return "backlog"
    if status in {"FAIL", "BLOCKED"}:
        return "defect"
    return "no_action"


def infer_feedback_severity(text: str, status: str) -> str:
    lowered = text.lower()
    if status == "BLOCKED" or any(term in lowered for term in ("blocker", "p0", "critical", "阻塞")):
        return "BLOCKER"
    if status == "FAIL" or any(term in lowered for term in ("high", "p1", "严重")):
        return "HIGH"
    if any(term in lowered for term in ("low", "p2", "minor", "低")):
        return "LOW"
    return "MEDIUM"


def infer_coverage_status(text: str, category: str) -> str:
    lowered = text.lower()
    if any(term in lowered for term in ("covered", "has regression", "regression asset")) and "not covered" not in lowered:
        return "covered"
    if any(term in lowered for term in ("partial", "partially covered", "部分覆盖")):
        return "partially_covered"
    if category == "coverage_gap" or any(term in lowered for term in ("not covered", "uncovered", "missing grader", "missing case", "覆盖不到")):
        return "not_covered"
    return "unknown"


def infer_gap_type(text: str) -> str:
    lowered = text.lower()
    if "runtime sample" in lowered or "真实运行样本" in lowered:
        return "missing_runtime_sample"
    if "fixture" in lowered:
        return "missing_fixture"
    if "grader" in lowered:
        return "missing_grader"
    if "assert" in lowered or "weak" in lowered or "断言" in lowered:
        return "weak_assertion"
    return "missing_case"


def infer_recommended_asset(gap_type: str) -> str:
    return {
        "missing_case": "case",
        "missing_grader": "grader",
        "missing_fixture": "fixture",
        "missing_runtime_sample": "runtime_sample",
        "weak_assertion": "grader",
    }.get(gap_type, "case")


def load_run_exec_payload(path: Path, source_dir: Path) -> dict[str, object] | None:
    text = read_optional_text(path)
    if not text:
        return None
    if path.suffix.lower() == ".json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict) and str(payload.get("run_exec_id", "")).strip():
            payload.setdefault("source_path", relative(source_dir, path))
            payload.setdefault("raw_text", text)
            return payload
    run_exec_id = scalar_value(text, "run_exec_id")
    if run_exec_id:
        return {"run_exec_id": run_exec_id, "source_path": relative(source_dir, path), "raw_text": text}
    return None


def normalize_one_feedback(path: Path, source_dir: Path, index: int) -> dict[str, object]:
    text = read_optional_text(path)
    existing = load_run_exec_payload(path, source_dir)
    raw_text = str(existing.get("raw_text", text)) if existing else text
    status = str((existing or {}).get("status") or detect_feedback_status(raw_text)).upper()
    if status == "PASS_WITH_RISK":
        status = "PASS"
    category = str((existing or {}).get("category") or infer_feedback_category(raw_text, status))
    severity = str((existing or {}).get("severity") or infer_feedback_severity(raw_text, status)).upper()
    stage = str((existing or {}).get("stage") or infer_feedback_stage(raw_text))
    coverage_status = str((existing or {}).get("coverage_status") or infer_coverage_status(raw_text, category))
    source_path = str((existing or {}).get("source_path") or relative(source_dir, path))
    run_exec_id = str((existing or {}).get("run_exec_id") or f"RUN-EXEC-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d')}-{index:03d}")
    excerpt = mask_sensitive(" ".join(raw_text.strip().split()))[:500]
    payload: dict[str, object] = {
        "run_exec_id": run_exec_id,
        "normalized_at": now_iso(),
        "source_path": source_path,
        "status": status if status in {"PASS", "FAIL", "BLOCKED", "SKIPPED"} else "FAIL",
        "category": category,
        "severity": severity if severity in SEVERITY_RANK else "MEDIUM",
        "stage": stage,
        "coverage_status": coverage_status,
        "evidence": {
            "path": source_path,
            "excerpt": excerpt,
        },
    }
    regression_asset = str((existing or {}).get("regression_asset", "")).strip()
    if regression_asset:
        payload["regression_asset"] = regression_asset
    return payload


def write_run_exec_markdown(payload: dict[str, object], out_path: Path) -> None:
    evidence = payload.get("evidence", {})
    source_path = str(evidence.get("path", "")) if isinstance(evidence, dict) else ""
    lines = [
        "---",
        f'run_exec_id: "{payload.get("run_exec_id", "")}"',
        f'status: "{payload.get("status", "")}"',
        f'source_path: "{source_path}"',
        f'normalized_at: "{payload.get("normalized_at", "")}"',
        "---",
        "",
        "# Normalized RUN-EXEC",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| status | `{payload.get('status', '')}` |",
        f"| category | `{payload.get('category', '')}` |",
        f"| severity | `{payload.get('severity', '')}` |",
        f"| stage | `{payload.get('stage', '')}` |",
        f"| coverage_status | `{payload.get('coverage_status', '')}` |",
        f"| evidence | `{source_path}` |",
        "",
    ]
    out_path.write_text("\n".join(lines), encoding="utf-8")


def feedback_normalize(source_dir: Path, out_dir: Path) -> tuple[int, dict[str, object]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    feedback_files = sorted(path for path in source_dir.rglob("*") if path.is_file() and path.name not in FEEDBACK_TOOL_OUTPUT_NAMES)
    run_execs: list[dict[str, object]] = []
    for idx, path in enumerate(feedback_files, 1):
        payload = normalize_one_feedback(path, source_dir, idx)
        stem = safe_id_component(str(payload["run_exec_id"]))
        (out_dir / f"{stem}.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        write_run_exec_markdown(payload, out_dir / f"{stem}.md")
        run_execs.append(payload)

    status_counter = collections.Counter(str(item.get("status", "UNKNOWN")) for item in run_execs)
    metrics = {
        "created_at": now_iso(),
        "source_dir": source_dir.as_posix(),
        "out_dir": out_dir.as_posix(),
        "feedback_sample_count": len(feedback_files),
        "normalized_run_exec_count": len(run_execs),
        "passed": status_counter["PASS"],
        "failed": status_counter["FAIL"],
        "blocked": status_counter["BLOCKED"],
        "skipped": status_counter["SKIPPED"],
    }
    (out_dir / "feedback-metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "RUN-EXEC-INDEX.json").write_text(json.dumps({"run_exec": run_execs}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0, metrics


def load_normalized_run_execs(runs_dir: Path) -> list[dict[str, object]]:
    run_execs: list[dict[str, object]] = []
    if not runs_dir.exists():
        return run_execs
    for path in sorted(runs_dir.rglob("*.json")):
        if path.name in {"feedback-metrics.json", "triage-metrics.json", "TRIAGE-RESULTS.json", "EVAL-BACKLOG.json", "GAPS.json"}:
            continue
        try:
            payload = json.loads(read_text(path))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and str(payload.get("run_exec_id", "")).strip():
            payload.setdefault("source_path", relative(runs_dir, path))
            run_execs.append(payload)
    return run_execs


def triage_type_for_run_exec(payload: dict[str, object]) -> str:
    status = str(payload.get("status", "")).upper()
    category = str(payload.get("category", "")).lower()
    coverage_status = str(payload.get("coverage_status", "")).lower()
    if category == "duplicate":
        return "DUPLICATE"
    if category == "environment":
        return "ENVIRONMENT"
    if category == "usage":
        return "USAGE"
    if category == "coverage_gap" or coverage_status in {"not_covered", "partially_covered"}:
        return "GAP"
    if category == "backlog":
        return "BACKLOG"
    if status in {"FAIL", "BLOCKED"}:
        return "ISSUE_DRAFT"
    return "NO_ACTION"


def feedback_triage(runs_dir: Path, out_dir: Path) -> tuple[int, dict[str, object]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    run_execs = load_normalized_run_execs(runs_dir)
    triage_results: list[dict[str, object]] = []
    issue_drafts: list[dict[str, object]] = []
    gaps: list[dict[str, object]] = []
    backlog_items: list[dict[str, object]] = []
    today = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d")

    for idx, payload in enumerate(run_execs, 1):
        triage_type = triage_type_for_run_exec(payload)
        status = str(payload.get("status", "UNKNOWN")).upper()
        severity = str(payload.get("severity", "MEDIUM")).upper()
        evidence_obj = payload.get("evidence")
        evidence_path = str(evidence_obj.get("path", "")) if isinstance(evidence_obj, dict) else ""
        source_path = str(payload.get("source_path") or evidence_path)
        run_exec_id = str(payload.get("run_exec_id", f"RUN-EXEC-{idx:03d}"))
        result = {
            "run_exec_id": run_exec_id,
            "source_path": source_path,
            "triage_type": triage_type,
            "status": status,
            "severity": severity,
            "category": str(payload.get("category", "unknown")),
            "stage": str(payload.get("stage", "unknown")),
            "coverage_status": str(payload.get("coverage_status", "unknown")),
        }
        triage_results.append(result)

        if triage_type == "ISSUE_DRAFT":
            issue = {
                "id": f"ISSUE-DRAFT-{idx:03d}",
                "run_exec_id": run_exec_id,
                "source_path": source_path,
                "category": str(payload.get("category", "defect")),
                "severity": severity,
                "stage": str(payload.get("stage", "unknown")),
                "coverage_status": str(payload.get("coverage_status", "unknown")),
                "status": "draft",
                "regression_asset": str(payload.get("regression_asset", "")),
            }
            issue_drafts.append(issue)
            if severity in {"BLOCKER", "HIGH"} and not issue["regression_asset"]:
                backlog_items.append(
                    {
                        "id": f"EVAL-BL-{today}-{idx:03d}",
                        "source_issue": issue["id"],
                        "source_run_exec": run_exec_id,
                        "gap_type": "missing_fixture",
                        "missing_stage": str(payload.get("stage", "field_feedback")),
                        "recommended_asset": "fixture",
                        "proposed_grader": "runtime_artifact",
                        "priority": "P0" if severity == "BLOCKER" else "P1",
                        "owner_hint": "domain-user",
                        "coverage_status": str(payload.get("coverage_status", "unknown")),
                        "status": "pending",
                    }
                )

        if triage_type == "GAP":
            evidence = payload.get("evidence", {})
            raw_hint = str(evidence.get("excerpt", "")) if isinstance(evidence, dict) else ""
            gap_type = infer_gap_type(raw_hint)
            recommended_asset = infer_recommended_asset(gap_type)
            priority = "P0" if severity in {"BLOCKER", "HIGH"} and status == "BLOCKED" else ("P1" if severity in {"BLOCKER", "HIGH"} else "P2")
            gap = {
                "id": f"GAP-{today}-{idx:03d}",
                "run_exec_id": run_exec_id,
                "source_path": source_path,
                "coverage_status": str(payload.get("coverage_status", "not_covered")),
                "gap_type": gap_type,
                "recommended_asset": recommended_asset,
                "priority": priority,
                "owner_hint": "meta-flow" if recommended_asset in {"grader", "fixture"} else "domain-user",
                "status": "open",
            }
            gaps.append(gap)
            backlog_items.append(
                {
                    "id": f"EVAL-BL-{today}-{idx:03d}",
                    "source_issue": gap["id"],
                    "source_run_exec": run_exec_id,
                    "gap_type": gap_type,
                    "missing_stage": str(payload.get("stage", "field_feedback")),
                    "recommended_asset": recommended_asset,
                    "proposed_grader": "runtime_artifact" if recommended_asset in {"runtime_sample", "fixture"} else "static",
                    "priority": priority,
                    "owner_hint": gap["owner_hint"],
                    "coverage_status": gap["coverage_status"],
                    "status": "pending",
                }
            )

        if triage_type == "BACKLOG":
            backlog_items.append(
                {
                    "id": f"EVAL-BL-{today}-{idx:03d}",
                    "source_issue": run_exec_id,
                    "source_run_exec": run_exec_id,
                    "gap_type": "weak_assertion",
                    "missing_stage": str(payload.get("stage", "field_feedback")),
                    "recommended_asset": "doc_update",
                    "proposed_grader": "advisory",
                    "priority": "P2",
                    "owner_hint": "domain-user",
                    "coverage_status": str(payload.get("coverage_status", "unknown")),
                    "status": "pending",
                }
            )

    triage_counter = collections.Counter(str(item["triage_type"]) for item in triage_results)
    issue_with_regression = sum(1 for item in issue_drafts if str(item.get("regression_asset", "")).strip())
    blocking_open_issue_count = sum(1 for item in issue_drafts if str(item.get("severity")) in {"BLOCKER", "HIGH"} and not str(item.get("regression_asset", "")).strip())
    open_p0_gap_count = sum(1 for item in gaps if str(item.get("priority")) == "P0" and str(item.get("status")) != "closed")
    metrics = {
        "created_at": now_iso(),
        "runs_dir": runs_dir.as_posix(),
        "out_dir": out_dir.as_posix(),
        "normalized_run_exec_count": len(run_execs),
        "issue_draft_count": len(issue_drafts),
        "gap_count": len(gaps),
        "backlog_count": len(backlog_items),
        "environment_count": triage_counter["ENVIRONMENT"],
        "usage_count": triage_counter["USAGE"],
        "duplicate_count": triage_counter["DUPLICATE"],
        "no_action_count": triage_counter["NO_ACTION"],
        "regression_asset_coverage": (issue_with_regression / len(issue_drafts)) if issue_drafts else 1.0,
        "blocking_open_issue_count": blocking_open_issue_count,
        "open_p0_gap_count": open_p0_gap_count,
    }

    issue_lines = [
        "# Feedback ISSUE Drafts",
        "",
        "| Issue | Severity | Stage | Coverage | Source RUN-EXEC | Regression Asset |",
        "|---|---|---|---|---|---|",
    ]
    if issue_drafts:
        for issue in issue_drafts:
            issue_lines.append(
                f"| `{issue['id']}` | `{issue['severity']}` | `{issue['stage']}` | `{issue['coverage_status']}` | "
                f"`{issue['run_exec_id']}` | `{issue.get('regression_asset') or ''}` |"
            )
    else:
        issue_lines.append("| N/A |  |  |  | no issue drafts |  |")

    (out_dir / "TRIAGE-RESULTS.json").write_text(json.dumps({"triage_results": triage_results}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "ISSUE-DRAFTS.json").write_text(json.dumps({"issue_drafts": issue_drafts}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "ISSUE-DRAFTS.md").write_text("\n".join(issue_lines) + "\n", encoding="utf-8")
    (out_dir / "GAPS.json").write_text(json.dumps({"gaps": gaps}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "EVAL-BACKLOG.json").write_text(json.dumps({"eval_backlog": backlog_items}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "triage-metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0, metrics


def feedback_analyze(eval_path: Path, source_dir: Path, out_dir: Path) -> tuple[int, dict[str, object]]:
    normalize_dir = out_dir / "run-exec"
    triage_dir = out_dir / "triage"
    normalize_code, normalize_metrics = feedback_normalize(source_dir, normalize_dir)
    triage_code, triage_metrics = feedback_triage(normalize_dir, triage_dir)
    summary = {
        "created_at": now_iso(),
        "eval_path": eval_path.as_posix(),
        "source_dir": source_dir.as_posix(),
        "run_exec_dir": normalize_dir.as_posix(),
        "triage_dir": triage_dir.as_posix(),
        "normalize": normalize_metrics,
        "triage": triage_metrics,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "feedback-analyze-summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return (0 if normalize_code == 0 and triage_code == 0 else 1), summary


def remove_first_matching_line(path: Path, pattern: str) -> bool:
    text = read_optional_text(path)
    if not text:
        return False
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if re.match(pattern, line):
            del lines[idx]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return True
    return False


def mutate_markdown_table(path: Path) -> bool:
    text = read_optional_text(path)
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|") and not re.match(r"^\|[-\s:|]+\|$", stripped):
            cells = line.split("|")
            if len(cells) > 4:
                del cells[-2]
                lines[idx] = "|".join(cells)
                path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                return True
    return False


def copied_eval_path(eval_path: Path, source: Path, target_root: Path) -> Path:
    try:
        return target_root / eval_path.resolve().relative_to(source.resolve())
    except ValueError:
        return target_root / eval_path.name


def corrupt_first_sha256(path: Path) -> bool:
    text = read_optional_text(path)
    if not text:
        return False
    new_text, count = re.subn(r"(sha256:\s*[\"']?)[0-9a-fA-F]{64}([\"']?)", rf"\g<1>{'0' * 64}\2", text, count=1)
    if count:
        path.write_text(new_text, encoding="utf-8")
        return True
    return False


def remove_required_path(root: Path, rel_path: str) -> bool:
    candidate = root / rel_path
    if candidate.exists() and candidate.is_file():
        candidate.unlink()
        return True
    if candidate.exists() and candidate.is_dir():
        shutil.rmtree(candidate)
        return True
    return False


def inject_forbidden_pattern(root: Path, grader: dict[str, object]) -> bool:
    paths = glob_paths(root, as_list(grader.get("target_globs")))
    target = next((path for path in paths if path.is_file()), None)
    if target is None and str(grader.get("target", "")).strip():
        candidate = root / str(grader.get("target"))
        target = candidate if candidate.is_file() else None
    if target is None:
        return False
    with target.open("a", encoding="utf-8") as handle:
        handle.write('\napi_key = "UNMASKED_MUTATION_SECRET"\n')
    return True


def remove_markdown_section(path: Path, section: str) -> bool:
    text = read_optional_text(path)
    if not text:
        return False
    lines = text.splitlines()
    start = None
    heading_level = 0
    for idx, line in enumerate(lines):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match and match.group(2).strip() == section:
            start = idx
            heading_level = len(match.group(1))
            break
    if start is None:
        return False
    end = len(lines)
    for idx in range(start + 1, len(lines)):
        match = re.match(r"^(#{1,6})\s+", lines[idx])
        if match and len(match.group(1)) <= heading_level:
            end = idx
            break
    del lines[start:end]
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return True


def mutate_content_schema_section(root: Path, grader: dict[str, object]) -> bool:
    sections = as_list(grader.get("required_sections"))
    if not sections:
        return False
    paths = grader_target_paths(root, grader)
    for path in paths:
        if path.is_file() and remove_markdown_section(path, sections[0]):
            return True
    return False


def mutation_allowed(mutation_type: str, requested: set[str] | None) -> bool:
    if not requested:
        return True
    aliases = {
        "delete_required_field": {"delete_required_field", "missing-required-field", "required-field"},
        "delete_table_column": {"delete_table_column", "table-column", "broken-table"},
        "delete_runtime_required_path": {"delete_runtime_required_path", "missing-runtime-path", "missing-runtime-artifact", "missing-mfq"},
        "corrupt_prompt_bundle_hash": {"corrupt_prompt_bundle_hash", "prompt-hash", "wrong-prompt-hash"},
        "delete_path_exists_artifact": {"delete_path_exists_artifact", "missing-artifact-path", "artifact-path"},
        "inject_forbidden_pattern": {"inject_forbidden_pattern", "forbidden-pattern", "secret-pattern"},
        "delete_required_section": {"delete_required_section", "missing-section", "missing-critical-section"},
    }
    return bool(aliases.get(mutation_type, {mutation_type}) & requested)


def mutate_eval(eval_path: Path, source: Path, out_dir: Path, requested_mutations: set[str] | None = None) -> tuple[int, dict[str, object]]:
    eval_text = read_text(eval_path)
    graders = section_blocks(eval_text, "graders")
    out_dir.mkdir(parents=True, exist_ok=True)
    mutations: list[dict[str, str]] = []

    def copy_source(mutation_id: str) -> Path:
        target = out_dir / mutation_id
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)
        return target

    for grader in graders:
        grader_type = str(grader.get("type", ""))
        grader_id = str(grader.get("id", ""))
        if grader_type == "prompt_bundle_hashes" and mutation_allowed("corrupt_prompt_bundle_hash", requested_mutations):
            mutation_id = f"corrupt-prompt-hash-{grader_id}"
            target_root = copy_source(mutation_id)
            target_eval = copied_eval_path(eval_path, source, target_root)
            prompt_bundle = scalar_value(read_optional_text(target_eval), "prompt_bundle")
            changed = corrupt_first_sha256(target_root / prompt_bundle) if prompt_bundle else False
            mutations.append(
                {
                    "id": mutation_id,
                    "source_grader": grader_id,
                    "expected_failing_grader": grader_id,
                    "type": "corrupt_prompt_bundle_hash",
                    "status": "created" if changed else "not-applicable",
                }
            )
        if grader_type == "required_fields" and mutation_allowed("delete_required_field", requested_mutations):
            fields = as_list(grader.get("required_fields"))
            target = str(grader.get("target", ""))
            if fields and target:
                mutation_id = f"remove-field-{grader_id}"
                target_root = copy_source(mutation_id)
                changed = remove_first_matching_line(target_root / target, rf"^\s*{re.escape(fields[0])}:")
                mutations.append(
                    {
                        "id": mutation_id,
                        "source_grader": grader_id,
                        "expected_failing_grader": grader_id,
                        "type": "delete_required_field",
                        "status": "created" if changed else "not-applicable",
                    }
                )
        if grader_type == "path_exists" and mutation_allowed("delete_path_exists_artifact", requested_mutations):
            paths = as_list(grader.get("paths"))
            if paths:
                mutation_id = f"delete-path-{grader_id}"
                target_root = copy_source(mutation_id)
                changed = remove_required_path(target_root, paths[0])
                mutations.append(
                    {
                        "id": mutation_id,
                        "source_grader": grader_id,
                        "expected_failing_grader": grader_id,
                        "type": "delete_path_exists_artifact",
                        "status": "created" if changed else "not-applicable",
                    }
                )
        if grader_type == "forbidden_patterns" and mutation_allowed("inject_forbidden_pattern", requested_mutations):
            mutation_id = f"inject-forbidden-{grader_id}"
            target_root = copy_source(mutation_id)
            changed = inject_forbidden_pattern(target_root, grader)
            mutations.append(
                {
                    "id": mutation_id,
                    "source_grader": grader_id,
                    "expected_failing_grader": grader_id,
                    "type": "inject_forbidden_pattern",
                    "status": "created" if changed else "not-applicable",
                }
            )
        if grader_type == "content_schema" and mutation_allowed("delete_required_section", requested_mutations):
            mutation_id = f"delete-section-{grader_id}"
            target_root = copy_source(mutation_id)
            changed = mutate_content_schema_section(target_root, grader)
            mutations.append(
                {
                    "id": mutation_id,
                    "source_grader": grader_id,
                    "expected_failing_grader": grader_id,
                    "type": "delete_required_section",
                    "status": "created" if changed else "not-applicable",
                }
            )
        if grader_type == "table_structure" and mutation_allowed("delete_table_column", requested_mutations):
            globs = as_list(grader.get("target_globs"))
            if globs:
                mutation_id = f"break-table-{grader_id}"
                target_root = copy_source(mutation_id)
                changed = False
                for path in glob_paths(target_root, globs):
                    if mutate_markdown_table(path):
                        changed = True
                        break
                mutations.append(
                    {
                        "id": mutation_id,
                        "source_grader": grader_id,
                        "expected_failing_grader": grader_id,
                        "type": "delete_table_column",
                        "status": "created" if changed else "not-applicable",
                    }
                )
        if grader_type == "runtime_artifact" and mutation_allowed("delete_runtime_required_path", requested_mutations):
            required_paths = as_list(grader.get("required_paths"))
            workspace = str(grader.get("workspace", ""))
            if required_paths:
                mutation_id = f"delete-runtime-path-{grader_id}"
                target_root = copy_source(mutation_id)
                changed = remove_required_path(resolved_local_path(target_root, workspace), required_paths[0])
                mutations.append(
                    {
                        "id": mutation_id,
                        "source_grader": grader_id,
                        "expected_failing_grader": grader_id,
                        "type": "delete_runtime_required_path",
                        "status": "created" if changed else "not-applicable",
                    }
                )
            elif str(grader.get("sample_registry", "")).strip():
                samples, sample_failures = load_runtime_samples(source, grader)
                pass_samples = [sample for sample in samples if runtime_sample_expected_status(sample) == "PASS"]
                if pass_samples:
                    sample = pass_samples[0]
                    sample_required_paths = as_list(sample.get("required_paths"))
                    sample_workspace_path = str(sample.get("workspace", ""))
                    if sample_required_paths and sample_workspace_path:
                        mutation_id = f"delete-runtime-path-{grader_id}"
                        target_root = copy_source(mutation_id)
                        changed = remove_required_path(resolved_local_path(target_root, sample_workspace_path), sample_required_paths[0])
                        mutations.append(
                            {
                                "id": mutation_id,
                                "source_grader": grader_id,
                                "expected_failing_grader": grader_id,
                                "sample_id": str(sample.get("id", "")),
                                "type": "delete_runtime_required_path",
                                "status": "created" if changed else "not-applicable",
                            }
                        )
                elif sample_failures:
                    mutations.append(
                        {
                            "id": f"delete-runtime-path-{grader_id}",
                            "source_grader": grader_id,
                            "expected_failing_grader": grader_id,
                            "type": "delete_runtime_required_path",
                            "status": "not-applicable",
                        }
                    )

    summary = {"created_at": now_iso(), "eval_path": eval_path.as_posix(), "source": source.as_posix(), "out": out_dir.as_posix(), "mutations": mutations}
    (out_dir / "MUTATION-REGISTRY.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return (0 if mutations else 1), summary


def load_backlog_items(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        return []
    if path.suffix == ".json":
        payload = json.loads(read_text(path))
        return list(payload.get("eval_backlog", []))
    return section_blocks(read_text(path), "eval_backlog")


def backlog_check(path: Path) -> tuple[int, str]:
    items = load_backlog_items(path)
    findings: list[str] = []
    for item in items:
        item_id = str(item.get("id", "<unknown>"))
        status = str(item.get("status", "pending"))
        if status == "closed":
            missing = [field for field in ("source_issue", "regression_asset") if not str(item.get(field, "")).strip()]
            if missing:
                findings.append(f"{item_id} closed without required field(s): {', '.join(missing)}")
        if status != "closed" and not str(item.get("source_issue", "")).strip():
            findings.append(f"{item_id} open backlog item missing source_issue")
    open_count = sum(1 for item in items if str(item.get("status", "pending")) != "closed")
    lines = [
        "# Eval Backlog Check",
        "",
        f"- backlog: `{path}`",
        f"- total: `{len(items)}`",
        f"- open: `{open_count}`",
        f"- status: `{'FAIL' if findings else 'PASS'}`",
        "",
        "| Finding |",
        "|---|",
        *(f"| {finding} |" for finding in findings),
    ]
    if not findings:
        lines.append("| none |")
    text = "\n".join(lines) + "\n"
    return (0 if not findings else 1), text


def backlog_list(path: Path) -> tuple[int, str]:
    items = load_backlog_items(path)
    lines = ["# Eval Backlog", "", "| ID | Priority | Status | Source Issue | Proposed Grader |", "|---|---|---|---|---|"]
    for item in items:
        lines.append(
            f"| `{item.get('id', '')}` | `{item.get('priority', '')}` | `{item.get('status', '')}` | "
            f"`{item.get('source_issue', '')}` | `{item.get('proposed_grader', '')}` |"
        )
    if not items:
        lines.append("| N/A |  |  |  | no backlog items |")
    return 0, "\n".join(lines) + "\n"


def write_backlog_items(path: Path, items: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".json":
        path.write_text(json.dumps({"eval_backlog": items}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return
    lines = ["eval_backlog:"]
    for item in items:
        lines.append(f'  - id: "{item.get("id", "")}"')
        for key in ("source_issue", "missing_stage", "proposed_grader", "priority", "status", "regression_asset", "case", "fixture", "closed_at"):
            if key in item and str(item.get(key, "")).strip():
                lines.append(f'    {key}: "{item.get(key)}"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def backlog_close(path: Path, item_id: str, regression_asset: str, case: str = "", fixture: str = "") -> tuple[int, str]:
    if not regression_asset:
        return 1, "regression_asset is required to close an eval backlog item\n"
    items = load_backlog_items(path)
    found = False
    for item in items:
        if str(item.get("id")) != item_id:
            continue
        item["status"] = "closed"
        item["regression_asset"] = regression_asset
        if case:
            item["case"] = case
        if fixture:
            item["fixture"] = fixture
        item["closed_at"] = now_iso()
        found = True
        break
    if not found:
        return 1, f"eval backlog item not found: {item_id}\n"
    write_backlog_items(path, items)
    return 0, f"closed {item_id} with regression_asset={regression_asset}\n"


def print_validation(root: Path, issues: list[EvalIssue]) -> None:
    print(f"eval_root: {root}")
    if not issues:
        print("validation: PASS")
        return
    print("validation: FAIL")
    for issue in issues:
        print(f"- {issue.severity} {issue.code}: {issue.message}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate and run Meta Flow workflow eval packages.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="Validate a WORKFLOW-EVAL.yaml package.")
    validate_parser.add_argument("--eval", required=True, type=Path, help="Path to WORKFLOW-EVAL.yaml")

    run_parser = subparsers.add_parser("run", help="Run deterministic graders and write run evidence.")
    run_parser.add_argument("--eval", required=True, type=Path, help="Path to WORKFLOW-EVAL.yaml")
    run_parser.add_argument("--out", required=True, type=Path, help="Directory for run-summary.json and run-summary.md")
    run_parser.add_argument(
        "--allow-authorization",
        action="append",
        default=[],
        choices=sorted(SUPPORTED_AUTHORIZATIONS),
        help="Additional grader authorization to allow for this run. Default allows none and local-fs.",
    )

    health_parser = subparsers.add_parser("suite-health", help="Summarize run evidence under a directory.")
    health_parser.add_argument("--runs", required=True, type=Path, help="Directory containing run-summary.json files")
    health_parser.add_argument("--out", type=Path, help="Optional markdown output path")
    health_parser.add_argument("--eval", type=Path, help="Optional WORKFLOW-EVAL.yaml for case registry quality semantics")
    health_parser.add_argument("--stale-days", type=int, default=30, help="Case last_verified_at staleness threshold")
    health_parser.add_argument("--feedback-metrics", action="append", type=Path, default=[], help="feedback-metrics.json or directory containing feedback/triage metrics")
    health_parser.add_argument("--triage", action="append", type=Path, default=[], help="Triage output directory or triage metrics path")
    health_parser.add_argument("--backlog", action="append", type=Path, default=[], help="Eval backlog JSON/YAML path or directory")

    release_parser = subparsers.add_parser("release-check", help="Evaluate whether an eval suite is release-ready.")
    release_parser.add_argument("--eval", required=True, type=Path, help="Path to WORKFLOW-EVAL.yaml")
    release_parser.add_argument("--runs", required=True, type=Path, help="Directory containing run-summary.json files")
    release_parser.add_argument("--out", type=Path, help="Optional markdown output path")
    release_parser.add_argument("--json-out", type=Path, help="Optional machine-readable JSON output path")
    release_parser.add_argument("--profile", default="release", choices=["release", "nightly", "field-regression"], help="Release-check profile")
    release_parser.add_argument("--format", default="markdown", choices=["markdown", "json"], help="stdout format")
    release_parser.add_argument("--feedback-metrics", action="append", type=Path, default=[], help="feedback-metrics.json or directory containing feedback metrics")
    release_parser.add_argument("--triage", action="append", type=Path, default=[], help="Triage output directory or triage metrics path")
    release_parser.add_argument("--backlog", action="append", type=Path, default=[], help="Eval backlog JSON/YAML path or directory")

    mutate_parser = subparsers.add_parser("mutate", help="Generate deterministic negative fixtures from a valid source fixture.")
    mutate_parser.add_argument("--eval", required=True, type=Path, help="Path to WORKFLOW-EVAL.yaml")
    mutate_parser.add_argument("--source", type=Path, help="Valid source fixture directory")
    mutate_parser.add_argument("--fixture", type=Path, help="Alias for --source")
    mutate_parser.add_argument("--out", required=True, type=Path, help="Output directory for generated mutations")
    mutate_parser.add_argument("--mutation", action="append", default=[], help="Mutation type/name to generate; repeatable. Default generates all applicable mutations.")

    install_parser = subparsers.add_parser("install-check", help="Run generic install mapping grader checks.")
    install_parser.add_argument("--eval", type=Path, help="Optional WORKFLOW-EVAL.yaml; runs install_mapping graders only")
    install_parser.add_argument("--out", type=Path, default=Path("process/evals/install-check"), help="Output directory when --eval is used")
    install_parser.add_argument("--platform", help="Platform name for direct check")
    install_parser.add_argument("--agent", help="Agent name for direct check")
    install_parser.add_argument("--expected-skill", action="append", default=[], help="Expected installed skill name; repeatable")
    install_parser.add_argument("--expected-rule", action="append", default=[], help="Expected installed rule/resource name; repeatable")
    install_parser.add_argument("--manifest", type=Path, help="Install manifest path for direct check")
    install_parser.add_argument("--installed-root", type=Path, help="Installed root directory for direct check")
    install_parser.add_argument("--target", type=Path, help="Platform install root for platform-contract checks")
    install_parser.add_argument("--scope", default="project", choices=["project", "user"], help="Platform contract scope")
    install_parser.add_argument("--platform-contracts", type=Path, help="Path to PLATFORM-CONTRACTS.yaml")
    install_parser.add_argument("--allowed-skill", action="append", default=[], help="Allowed installed skill when detecting stale skills; repeatable")
    install_parser.add_argument("--allowed-agent", action="append", default=[], help="Allowed installed agent when detecting stale agents; repeatable")

    feedback_parser = subparsers.add_parser("feedback", help="Pull or analyze generic eval feedback sources.")
    feedback_subparsers = feedback_parser.add_subparsers(dest="feedback_command", required=True)
    feedback_pull_parser = feedback_subparsers.add_parser("pull", help="Pull configured feedback sources.")
    feedback_pull_parser.add_argument("--eval", required=True, type=Path)
    feedback_pull_parser.add_argument("--out", required=True, type=Path)
    feedback_pull_parser.add_argument("--allow-git-read", action="store_true", help="Allow git clone for git feedback sources")
    feedback_sync_parser = feedback_subparsers.add_parser("sync", help="Alias for pull; sync configured feedback sources.")
    feedback_sync_parser.add_argument("--eval", required=True, type=Path)
    feedback_sync_parser.add_argument("--out", required=True, type=Path)
    feedback_sync_parser.add_argument("--allow-git-read", action="store_true", help="Allow git clone for git feedback sources")
    feedback_normalize_parser = feedback_subparsers.add_parser("normalize", help="Normalize raw feedback into structured RUN-EXEC records.")
    feedback_normalize_parser.add_argument("--in", dest="in_dir", required=True, type=Path)
    feedback_normalize_parser.add_argument("--out", required=True, type=Path)
    feedback_triage_parser = feedback_subparsers.add_parser("triage", help="Triage normalized RUN-EXEC records into ISSUE/GAP/backlog drafts.")
    feedback_triage_parser.add_argument("--runs", required=True, type=Path)
    feedback_triage_parser.add_argument("--out", required=True, type=Path)
    feedback_analyze_parser = feedback_subparsers.add_parser("analyze", help="Analyze pulled feedback into RUN-EXEC/ISSUE/backlog drafts.")
    feedback_analyze_parser.add_argument("--eval", required=True, type=Path)
    feedback_analyze_parser.add_argument("--source-dir", required=True, type=Path)
    feedback_analyze_parser.add_argument("--out", required=True, type=Path)

    backlog_parser = subparsers.add_parser("backlog", help="List, close, or check eval backlog objects.")
    backlog_subparsers = backlog_parser.add_subparsers(dest="backlog_command", required=True)
    backlog_list_parser = backlog_subparsers.add_parser("list", help="List eval backlog items.")
    backlog_list_parser.add_argument("--backlog", required=True, type=Path)
    backlog_check_parser = backlog_subparsers.add_parser("check", help="Validate eval backlog closure rules.")
    backlog_check_parser.add_argument("--backlog", required=True, type=Path)
    backlog_close_parser = backlog_subparsers.add_parser("close", help="Close an eval backlog item with regression evidence.")
    backlog_close_parser.add_argument("--backlog", required=True, type=Path)
    backlog_close_parser.add_argument("--id", required=True)
    backlog_close_parser.add_argument("--regression-asset", required=True)
    backlog_close_parser.add_argument("--case", default="")
    backlog_close_parser.add_argument("--fixture", default="")

    args = parser.parse_args(argv)
    if args.command == "validate":
        root, issues = validate_eval_package(args.eval)
        print_validation(root, issues)
        return 0 if not issues else 1
    if args.command == "run":
        allowed = set(DEFAULT_ALLOWED_AUTHORIZATIONS)
        allowed.update(args.allow_authorization)
        exit_code, summary = run_eval(args.eval, args.out, allowed_authorizations=allowed)
        print(f"run_id: {summary['run_id']}")
        print(f"status: {summary['status']}")
        print(f"out: {args.out}")
        return exit_code
    if args.command == "suite-health":
        exit_code, text = suite_health(
            args.runs,
            args.out,
            args.eval,
            args.stale_days,
            feedback_metrics_paths=args.feedback_metrics,
            triage_paths=args.triage,
            backlog_paths=args.backlog,
        )
        print(text, end="")
        return exit_code
    if args.command == "release-check":
        exit_code, text, payload = release_check(
            args.eval,
            args.runs,
            args.out,
            profile=args.profile,
            json_out=args.json_out,
            feedback_metrics_paths=args.feedback_metrics,
            triage_paths=args.triage,
            backlog_paths=args.backlog,
        )
        if args.format == "json":
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(text, end="")
        return exit_code
    if args.command == "mutate":
        source = args.source or args.fixture
        if source is None:
            print("mutate requires --source or --fixture", file=sys.stderr)
            return 2
        exit_code, summary = mutate_eval(args.eval, source, args.out, set(args.mutation) if args.mutation else None)
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return exit_code
    if args.command == "install-check":
        if args.eval:
            exit_code, summary = run_eval(args.eval, args.out, only_types={"install_mapping"})
            print(f"run_id: {summary['run_id']}")
            print(f"status: {summary['status']}")
            print(f"out: {args.out}")
            return exit_code
        direct_grader = {
            "id": "install-check-direct",
            "type": "install_mapping",
            "platform": args.platform or "",
            "agent": args.agent or "",
            "expected_skills": args.expected_skill,
            "expected_rules": args.expected_rule,
            "manifest_path": args.manifest.as_posix() if args.manifest else "",
            "installed_root": args.installed_root.as_posix() if args.installed_root else "",
            "target_root": args.target.as_posix() if args.target else "",
            "scope": args.scope,
            "platform_contracts": args.platform_contracts.as_posix() if args.platform_contracts else "",
            "allowed_skills": args.allowed_skill,
            "allowed_agents": args.allowed_agent,
        }
        result = run_install_mapping(Path.cwd(), direct_grader)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["status"] == "PASS" else 1
    if args.command == "feedback":
        if args.feedback_command in {"pull", "sync"}:
            exit_code, summary = feedback_pull(args.eval, args.out, args.allow_git_read)
            print(json.dumps(summary, indent=2, ensure_ascii=False))
            return exit_code
        if args.feedback_command == "normalize":
            exit_code, summary = feedback_normalize(args.in_dir, args.out)
            print(json.dumps(summary, indent=2, ensure_ascii=False))
            return exit_code
        if args.feedback_command == "triage":
            exit_code, summary = feedback_triage(args.runs, args.out)
            print(json.dumps(summary, indent=2, ensure_ascii=False))
            return exit_code
        if args.feedback_command == "analyze":
            exit_code, summary = feedback_analyze(args.eval, args.source_dir, args.out)
            print(json.dumps(summary, indent=2, ensure_ascii=False))
            return exit_code
    if args.command == "backlog":
        if args.backlog_command == "list":
            exit_code, text = backlog_list(args.backlog)
            print(text, end="")
            return exit_code
        if args.backlog_command == "check":
            exit_code, text = backlog_check(args.backlog)
            print(text, end="")
            return exit_code
        if args.backlog_command == "close":
            exit_code, text = backlog_close(args.backlog, args.id, args.regression_asset, args.case, args.fixture)
            print(text, end="")
            return exit_code
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
