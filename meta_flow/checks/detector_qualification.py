"""R13 source-bounded incremental detector hard gate。

历史 D0 的 1053 个动态 writer target 保持 limitation；本检查只要求冻结 Git OID
之后新增/修改行里的 writer-like call 全部可解析或有 exact allowlist disposition。
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from meta_flow.execution_control.contract import canonical_digest
from meta_flow.project.process_route import require_process_route

PUBLIC_OPERATION_DECLARATIONS = (
    ("detector-qualification.check", ("meta-flow", "check", "detector-qualification")),
)
BASELINE_REL = Path("governance/DETECTOR-INCREMENTAL-BASELINE.json")
WRITER_OPERATIONS = {
    "copy",
    "copy2",
    "copyfile",
    "makedirs",
    "move",
    "write",
    "write_text",
    "write_bytes",
    "remove",
    "removedirs",
    "rename",
    "replace",
    "rmdir",
    "touch",
    "unlink",
    "mkdir",
    "open",
}
MAX_FILES = 512
MAX_BYTES = 32 * 1024 * 1024
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MODULE_FIRST_ARG_OPERATIONS = {"makedirs", "remove", "removedirs", "rmdir", "unlink"}
DESTINATION_OPERATIONS = {"copy", "copy2", "copyfile", "move", "rename", "replace"}


@dataclass(frozen=True, slots=True)
class WriterCallV1:
    call_id: str
    ref: str
    function: str
    line: int
    operation: str
    target: str
    target_kind: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "ref": self.ref,
            "function": self.function,
            "line": self.line,
            "operation": self.operation,
            "target": self.target,
            "target_kind": self.target_kind,
        }


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )


def _added_lines(root: Path, baseline_oid: str, ref: str, *, untracked: bool) -> set[int]:
    if untracked:
        path = root / ref
        return set(range(1, len(path.read_text(encoding="utf-8").splitlines()) + 1))
    result = _git(root, "diff", "--unified=0", baseline_oid, "--", ref)
    if result.returncode != 0:
        raise ValueError(f"git diff failed for detector source {ref}: {result.stderr.strip()}")
    lines: set[int] = set()
    for line in result.stdout.splitlines():
        match = _HUNK_RE.match(line)
        if not match:
            continue
        start = int(match.group(1))
        count = int(match.group(2) or "1")
        lines.update(range(start, start + count))
    return lines


def _changed_python_refs(root: Path, baseline_oid: str, source_roots: tuple[str, ...]) -> tuple[tuple[str, bool], ...]:
    changed = _git(root, "diff", "--name-only", baseline_oid, "--", *source_roots)
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "--", *source_roots)
    if changed.returncode != 0 or untracked.returncode != 0:
        raise ValueError("detector Git source discovery failed")
    tracked_refs = {
        ref
        for ref in changed.stdout.splitlines()
        if ref.endswith(".py") and (root / ref).is_file()
    }
    untracked_refs = {
        ref
        for ref in untracked.stdout.splitlines()
        if ref.endswith(".py") and (root / ref).is_file()
    }
    return tuple(
        sorted(
            [(ref, False) for ref in tracked_refs - untracked_refs]
            + [(ref, True) for ref in untracked_refs]
        )
    )


def _literal_path(node: ast.AST | None, assignments: Mapping[str, str]) -> str:
    if node is None:
        return ""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return assignments.get(node.id, "")
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Path":
        return _literal_path(node.args[0] if node.args else None, assignments)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = _literal_path(node.left, assignments)
        right = _literal_path(node.right, assignments)
        if left and right:
            return f"{left.rstrip('/')}/{right.lstrip('/')}"
    return ""


def _function_for(tree: ast.AST, line: int) -> str:
    matches: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", node.lineno)
            if node.lineno <= line <= end:
                matches.append((node.lineno, node.name))
    return max(matches, default=(0, "<module>"))[1]


def _assignments(tree: ast.AST) -> dict[str, str]:
    result: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            literal = _literal_path(value, result)
            if literal:
                for target in targets:
                    if isinstance(target, ast.Name):
                        result[target.id] = literal
    return result


def _writer_target(call: ast.Call, assignments: Mapping[str, str]) -> tuple[str, str, str] | None:
    operation = ""
    target_node: ast.AST | None = None
    if isinstance(call.func, ast.Attribute):
        operation = call.func.attr
        if operation not in WRITER_OPERATIONS:
            return None
        if operation in DESTINATION_OPERATIONS:
            receiver = call.func.value
            module_call = isinstance(receiver, ast.Name) and receiver.id in {"os", "shutil"}
            receiver_name = (
                receiver.id
                if isinstance(receiver, ast.Name)
                else receiver.attr
                if isinstance(receiver, ast.Attribute)
                else ""
            ).lower()
            path_like = any(
                token in receiver_name
                for token in ("path", "target", "temporary", "temp", "file")
            )
            # ``str.replace(old, new)`` 至少有两个位置参数；``Path.replace``
            # 只有一个 destination。仅凭变量名含 ``path`` 会把路径字符串
            # 归一化误报为文件写入，因此先按调用形态排除确定的字符串替换。
            if operation == "replace" and not module_call and len(call.args) >= 2:
                return None
            if operation == "replace" and not module_call and not path_like:
                return None
        if operation in DESTINATION_OPERATIONS and call.args:
            target_node = (
                call.args[1]
                if isinstance(call.func.value, ast.Name)
                and call.func.value.id in {"os", "shutil"}
                and len(call.args) > 1
                else call.args[0]
            )
        elif (
            operation in MODULE_FIRST_ARG_OPERATIONS
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "os"
            and call.args
        ):
            target_node = call.args[0]
        else:
            target_node = call.func.value
        if operation == "open":
            mode = _literal_path(call.args[0] if call.args else None, assignments)
            if not mode or not any(flag in mode for flag in "wax+"):
                return None
            target_node = call.func.value
    elif isinstance(call.func, ast.Name) and call.func.id == "open":
        operation = "open"
        mode = _literal_path(call.args[1] if len(call.args) > 1 else None, assignments)
        if not mode or not any(flag in mode for flag in "wax+"):
            return None
        target_node = call.args[0] if call.args else None
    else:
        return None
    target = _literal_path(target_node, assignments)
    return operation, target or "<dynamic>", "literal-or-alias" if target else "dynamic"


def _changed_function_ranges(tree: ast.AST, lines: set[int]) -> tuple[tuple[int, int], ...]:
    ranges: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        end = int(getattr(node, "end_lineno", node.lineno))
        if any(node.lineno <= line <= end for line in lines):
            ranges.append((node.lineno, end))
    return tuple(ranges)


def _call_is_incrementally_affected(
    call: ast.Call,
    lines: set[int],
    changed_functions: tuple[tuple[int, int], ...],
) -> bool:
    return call.lineno in lines or any(
        start <= call.lineno <= end for start, end in changed_functions
    )


def scan_incremental_writers(
    release_root: Path,
    *,
    baseline_oid: str,
    source_roots: tuple[str, ...],
) -> tuple[tuple[WriterCallV1, ...], tuple[str, ...], dict[str, Any]]:
    root = release_root.resolve()
    refs = _changed_python_refs(root, baseline_oid, source_roots)
    if len(refs) > MAX_FILES:
        return (), ("DETECTOR_FILE_BUDGET_EXCEEDED",), {"changed_file_count": len(refs)}
    calls: list[WriterCallV1] = []
    findings: list[str] = []
    total_bytes = 0
    source_manifest: list[dict[str, Any]] = []
    for ref, untracked in refs:
        path = root / ref
        raw = path.read_bytes()
        total_bytes += len(raw)
        source_manifest.append({"ref": ref, "bytes": len(raw), "digest": canonical_digest(raw.hex())})
        if total_bytes > MAX_BYTES:
            findings.append("DETECTOR_BYTE_BUDGET_EXCEEDED")
            break
        try:
            tree = ast.parse(raw.decode("utf-8"), filename=ref)
        except (SyntaxError, UnicodeDecodeError):
            findings.append(f"DETECTOR_PARSE_FAILED:{ref}")
            continue
        lines = _added_lines(root, baseline_oid, ref, untracked=untracked)
        changed_functions = _changed_function_ranges(tree, lines)
        assignments = _assignments(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _call_is_incrementally_affected(
                node,
                lines,
                changed_functions,
            ):
                continue
            target = _writer_target(node, assignments)
            if target is None:
                continue
            operation, resolved, target_kind = target
            function = _function_for(tree, node.lineno)
            call_id = canonical_digest(
                {
                    "ref": ref,
                    "function": function,
                    "line": node.lineno,
                    "operation": operation,
                    "target_expression": ast.dump(
                        node.func.value if isinstance(node.func, ast.Attribute) else node,
                        include_attributes=False,
                    ),
                }
            )
            calls.append(
                WriterCallV1(
                    call_id,
                    ref,
                    function,
                    node.lineno,
                    operation,
                    resolved,
                    target_kind,
                )
            )
    stats = {
        "changed_file_count": len(refs),
        "scanned_byte_count": total_bytes,
        "source_manifest_digest": canonical_digest(source_manifest),
    }
    return tuple(sorted(calls, key=lambda call: (call.ref, call.line, call.call_id))), tuple(findings), stats


def _load_baseline(process_root: Path) -> dict[str, Any]:
    path = process_root / BASELINE_REL
    if path.is_symlink() or not path.is_file():
        raise ValueError("detector incremental baseline is missing or not regular")
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "schema_version",
        "kind",
        "baseline_release_oid",
        "source_roots",
        "historical_calibration",
        "dynamic_allowlist",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ValueError("detector incremental baseline fields mismatch")
    if payload.get("schema_version") != 1 or payload.get("kind") != "DetectorIncrementalBaselineV1":
        raise ValueError("detector incremental baseline kind/version mismatch")
    return payload


def qualify_dynamic_allowlist(
    calls: tuple[WriterCallV1, ...],
    allowlist_raw: object,
    process_root: Path,
) -> tuple[dict[str, Mapping[str, Any]], tuple[str, ...]]:
    if not isinstance(allowlist_raw, list):
        raise ValueError("detector dynamic_allowlist must be a list")
    findings: list[str] = []
    allowlist: dict[str, Mapping[str, Any]] = {}
    for item in allowlist_raw:
        if not isinstance(item, dict) or set(item) != {
            "call_id",
            "owner",
            "reason",
            "evidence_ref",
            "evidence_sha256",
        }:
            findings.append("DETECTOR_ALLOWLIST_FIELDS_INVALID")
            continue
        call_id = str(item["call_id"])
        if not call_id or not str(item["owner"]).strip() or not str(item["reason"]).strip():
            findings.append(f"DETECTOR_ALLOWLIST_VALUE_INVALID:{call_id or '-'}")
            continue
        if call_id in allowlist:
            findings.append("DETECTOR_ALLOWLIST_DUPLICATE")
        evidence = process_root / str(item["evidence_ref"]).removeprefix("process/")
        evidence_digest = str(item["evidence_sha256"])
        if evidence.is_symlink() or not evidence.is_file():
            findings.append(f"DETECTOR_ALLOWLIST_EVIDENCE_MISSING:{call_id}")
        elif not _SHA256_RE.fullmatch(evidence_digest):
            findings.append(f"DETECTOR_ALLOWLIST_EVIDENCE_DIGEST_INVALID:{call_id}")
        elif sha256(evidence.read_bytes()).hexdigest() != evidence_digest:
            findings.append(f"DETECTOR_ALLOWLIST_EVIDENCE_DRIFT:{call_id}")
        allowlist[call_id] = item
    unresolved = [call for call in calls if call.target_kind == "dynamic"]
    unresolved_ids = {call.call_id for call in unresolved}
    findings.extend(
        f"DETECTOR_NEW_UNRESOLVED_WRITER:{call.call_id}:{call.ref}:{call.line}"
        for call in unresolved
        if call.call_id not in allowlist
    )
    findings.extend(
        f"DETECTOR_ALLOWLIST_STALE:{call_id}"
        for call_id in sorted(set(allowlist) - unresolved_ids)
    )
    return allowlist, tuple(findings)


def check_baseline_ancestor(release_root: Path, baseline_oid: str) -> tuple[str, ...]:
    ancestor = _git(release_root, "merge-base", "--is-ancestor", baseline_oid, "HEAD")
    return () if ancestor.returncode == 0 else ("DETECTOR_BASELINE_NOT_ANCESTOR",)


def check_detector_qualification(project_root: Path) -> dict[str, Any]:
    release_root = project_root.resolve()
    route = require_process_route(release_root)
    baseline = _load_baseline(route.process_root)
    baseline_oid = str(baseline["baseline_release_oid"])
    findings = list(check_baseline_ancestor(release_root, baseline_oid))
    roots = baseline.get("source_roots")
    if not isinstance(roots, list) or not roots or not all(isinstance(ref, str) for ref in roots):
        raise ValueError("detector source_roots must be non-empty strings")
    calls, scan_findings, stats = scan_incremental_writers(
        release_root,
        baseline_oid=baseline_oid,
        source_roots=tuple(roots),
    )
    findings.extend(scan_findings)
    allowlist, allowlist_findings = qualify_dynamic_allowlist(
        calls,
        baseline.get("dynamic_allowlist"),
        route.process_root,
    )
    findings.extend(allowlist_findings)
    unresolved = [call for call in calls if call.target_kind == "dynamic"]
    unresolved_ids = {call.call_id for call in unresolved}
    calibration = baseline.get("historical_calibration")
    if calibration != {
        "total_file_writer_calls": 1063,
        "resolved_file_writer_calls": 10,
        "unresolved_file_writer_calls": 1053,
        "claim": "historical-limitation-not-product-cleanliness",
    }:
        findings.append("DETECTOR_HISTORICAL_CALIBRATION_DRIFT")
    payload = {
        "schema_version": 1,
        "kind": "DetectorQualificationReportV1",
        "decision": "BLOCKED" if findings else "PASS",
        "qualification": "source-bounded-incremental-hard-gate-v1",
        "baseline_release_oid": baseline_oid,
        "historical_calibration": calibration,
        "changed_source": stats,
        "incremental_writer_call_count": len(calls),
        "resolved_writer_call_count": len(calls) - len(unresolved),
        "allowlisted_dynamic_writer_call_count": len(unresolved_ids & set(allowlist)),
        "unresolved_unallowlisted_count": len(
            [call for call in unresolved if call.call_id not in allowlist]
        ),
        "writer_calls": [call.as_dict() for call in calls],
        "findings": sorted(set(findings)),
        "known_limits": [
            "baseline 之前的 1053 个 unresolved writer target 不在本增量 PASS 声明内",
            "本检查覆盖 source_roots 内相对 baseline 新增/修改调用行及发生变更的函数体",
            "动态/反射/运行时生成调用仍需 exact allowlist 与证据",
            "数据库、网络和 source_roots 外 writer 不属于本文件写入 detector",
        ],
        "mutation_count": 0,
    }
    payload["report_digest"] = canonical_digest(payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow check detector-qualification")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--include-calls", action="store_true")
    parsed = parser.parse_args(argv or [])
    try:
        report = check_detector_qualification(parsed.project_root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"decision": "BLOCKED", "errors": [str(exc)]}, ensure_ascii=False))
        return 1
    if not parsed.include_calls:
        report = {key: value for key, value in report.items() if key != "writer_calls"}
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["decision"] == "PASS" else 1


__all__ = [
    "WriterCallV1",
    "check_baseline_ancestor",
    "check_detector_qualification",
    "qualify_dynamic_allowlist",
    "scan_incremental_writers",
]
