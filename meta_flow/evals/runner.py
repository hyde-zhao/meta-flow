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
    if "#" in value:
        value = value.split("#", 1)[0].strip()
    return value.strip().strip('"').strip("'")


def parse_inline_list(value: str) -> list[str]:
    value = strip_value(value)
    if not (value.startswith("[") and value.endswith("]")):
        return [value] if value else []
    body = value[1:-1].strip()
    if not body:
        return []
    return [strip_value(item) for item in body.split(",")]


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
    """

    lines = text.splitlines()
    in_section = False
    current: dict[str, object] | None = None
    blocks: list[dict[str, object]] = []

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

        item_match = re.match(r"^\s*-\s+([A-Za-z0-9_-]+):\s*(.*)$", line)
        field_match = re.match(r"^\s+([A-Za-z0-9_-]+):\s*(.*)$", line)
        if item_match:
            if current:
                blocks.append(current)
            current = {item_match.group(1): parse_scalar_or_list(item_match.group(2))}
            continue
        if field_match and current is not None:
            current[field_match.group(1)] = parse_scalar_or_list(field_match.group(2))

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

    return root, issues


def glob_paths(root: Path, patterns: Iterable[str]) -> list[Path]:
    matched: list[Path] = []
    for pattern in patterns:
        for path in root.rglob("*"):
            rel = relative(root, path)
            if fnmatch.fnmatch(rel, pattern):
                matched.append(path)
    return sorted(set(matched))


def run_required_fields(root: Path, grader: dict[str, object]) -> tuple[str, list[str]]:
    target = root / str(grader.get("target", ""))
    required = set(grader.get("required_fields", []))
    if not target.is_file():
        return "FAIL", [f"target missing: {relative(root, target)}"]
    missing = sorted(required - top_level_keys(read_text(target)))
    if missing:
        return "FAIL", [f"{relative(root, target)} missing fields: {', '.join(missing)}"]
    return "PASS", [f"{relative(root, target)} contains required fields: {', '.join(sorted(required))}"]


def run_forbidden_patterns(root: Path, grader: dict[str, object]) -> tuple[str, list[str]]:
    patterns = [str(item) for item in grader.get("patterns", [])]
    target_globs = [str(item) for item in grader.get("target_globs", [])]
    findings: list[str] = []
    for path in glob_paths(root, target_globs):
        if not path.is_file():
            continue
        text = read_text(path)
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
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
            else:
                status, evidence = "FAIL", [f"unsupported grader type: {grader_type}"]
            results.append({"id": grader_id, "type": grader_type, "status": status, "evidence": evidence})

    status = "PASS" if not issues and all(result["status"] == "PASS" for result in results) else "FAIL"
    run_id = f"eval-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    summary: dict[str, object] = {
        "run_id": run_id,
        "created_at": now_iso(),
        "eval_path": eval_path.as_posix(),
        "suite_id": scalar_value(eval_text, "suite_id") if eval_text else "",
        "status": status,
        "issues": [issue.to_dict() for issue in issues],
        "grader_results": results,
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
    lines.extend(["", "## Issues", "", "| Severity | Code | Path | Message |", "|---|---|---|---|"])
    issues = summary.get("issues", [])
    if not issues:
        lines.append("| INFO | none |  | No package-level issues |")
    else:
        for issue in issues:
            lines.append(f"| {issue.get('severity')} | `{issue.get('code')}` | `{issue.get('path')}` | {issue.get('message')} |")
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
