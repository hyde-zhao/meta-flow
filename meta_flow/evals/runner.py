"""Local workflow evaluation runner.

The runner intentionally uses only the Python standard library. Meta Flow eval
contracts are YAML documents for humans and tools, but this module validates the
stable contract surface with conservative text parsing instead of requiring a
runtime YAML dependency.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
import json
import re
import sys
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
            if not strip_value(raw_value):
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


def run_eval(eval_path: Path, out_dir: Path) -> tuple[int, dict[str, object]]:
    root, issues = validate_eval_package(eval_path)
    eval_text = read_text(eval_path) if eval_path.is_file() else ""
    graders = section_blocks(eval_text, "graders") if eval_text else []
    grader_ids = {str(grader.get("id", "")) for grader in graders}

    results: list[dict[str, object]] = []
    if not issues:
        for grader in graders:
            grader_id = str(grader.get("id", ""))
            grader_type = str(grader.get("type", ""))
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
            results.append({"id": grader_id, "type": grader_type, "status": status, "evidence": evidence})

    result_by_id = {str(result.get("id")): str(result.get("status")) for result in results}
    registry_path = root / scalar_value(eval_text, "case_registry") if eval_text else Path()
    case_results: list[dict[str, object]] = []
    if registry_path.is_file():
        for case in section_blocks(read_text(registry_path), "cases"):
            case_id = str(case.get("id", ""))
            case_graders = as_list(case.get("graders"))
            grader_statuses = [result_by_id.get(grader_id, "MISSING") for grader_id in case_graders]
            case_status = "PASS" if grader_statuses and all(status == "PASS" for status in grader_statuses) else "FAIL"
            expected = str(case.get("expected_result", "PASS")) or "PASS"
            case_results.append(
                {
                    "id": case_id,
                    "category": str(case.get("category", "")),
                    "status": case_status,
                    "expected_result": expected,
                    "expected_match": case_status == expected,
                    "graders": case_graders,
                }
            )

    expected_fail_graders = {
        grader_id
        for case in case_results
        if str(case.get("expected_result")) == "FAIL"
        for grader_id in case.get("graders", [])
    }
    unexpected_failed_graders = [
        str(result.get("id"))
        for result in results
        if result.get("status") != "PASS" and str(result.get("id")) not in expected_fail_graders
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
        "unexpected_failed_graders": unexpected_failed_graders,
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
        evidence = "; ".join(str(item) for item in result.get("evidence", []))
        lines.append(f"| `{result.get('id')}` | `{result.get('type')}` | `{result.get('status')}` | {evidence} |")
    lines.extend(["", "## Case Results", "", "| Case | Category | Status | Expected | Graders |", "|---|---|---|---|---|"])
    case_results = summary.get("case_results", [])
    if not case_results:
        lines.append("| N/A |  | `FAIL` |  | No case results generated |")
    else:
        for case in case_results:
            graders = ", ".join(str(item) for item in case.get("graders", []))
            lines.append(
                f"| `{case.get('id')}` | `{case.get('category')}` | `{case.get('status')}` | "
                f"`{case.get('expected_result')}` | {graders} |"
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
            f"- unexpected_failed_graders: `{', '.join(str(item) for item in summary.get('unexpected_failed_graders', [])) or 'none'}`",
        ]
    )
    return "\n".join(lines) + "\n"


def suite_health(runs_dir: Path, out_path: Path | None) -> tuple[int, str]:
    summaries = sorted(runs_dir.glob("**/run-summary.json"))
    total = 0
    passed = 0
    failed = 0
    rows: list[str] = []
    for path in summaries:
        data = json.loads(read_text(path))
        total += 1
        status = data.get("status", "UNKNOWN")
        if status == "PASS":
            passed += 1
        else:
            failed += 1
        rows.append(f"| `{data.get('run_id')}` | `{status}` | `{relative(runs_dir, path.parent)}` |")
    health = "PASS" if total > 0 and failed == 0 else "FAIL"
    text = "\n".join(
        [
            "# Eval Suite Health",
            "",
            f"- status: `{health}`",
            f"- total_runs: `{total}`",
            f"- passed: `{passed}`",
            f"- failed: `{failed}`",
            "",
            "| Run | Status | Path |",
            "|---|---|---|",
            *(rows or ["| N/A | `FAIL` | no run-summary.json files found |"]),
            "",
        ]
    )
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
    return (0 if health == "PASS" else 1), text


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

    health_parser = subparsers.add_parser("suite-health", help="Summarize run evidence under a directory.")
    health_parser.add_argument("--runs", required=True, type=Path, help="Directory containing run-summary.json files")
    health_parser.add_argument("--out", type=Path, help="Optional markdown output path")

    args = parser.parse_args(argv)
    if args.command == "validate":
        root, issues = validate_eval_package(args.eval)
        print_validation(root, issues)
        return 0 if not issues else 1
    if args.command == "run":
        exit_code, summary = run_eval(args.eval, args.out)
        print(f"run_id: {summary['run_id']}")
        print(f"status: {summary['status']}")
        print(f"out: {args.out}")
        return exit_code
    if args.command == "suite-health":
        exit_code, text = suite_health(args.runs, args.out)
        print(text, end="")
        return exit_code
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
