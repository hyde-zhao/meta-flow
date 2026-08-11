"""R13 文件写入 detector hard gate。

增量检查冻结 Git OID 之后新增/修改的 writer-like call；全量基线检查则对当前
``meta_flow/`` 与 ``scripts/`` 重新做 receiver/stream 分类。D0 的 1053 仍作为
不可改写的历史校准保留，但不再充当当前产品 writer universe。
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


@dataclass(frozen=True, slots=True)
class FullWriterCallV1:
    call_id: str
    ref: str
    function: str
    line: int
    operation: str
    owner: str
    target_expression: str
    target_kind: str
    classification: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "ref": self.ref,
            "function": self.function,
            "line": self.line,
            "operation": self.operation,
            "owner": self.owner,
            "target_expression": self.target_expression,
            "target_kind": self.target_kind,
            "classification": self.classification,
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


def _import_aliases(
    tree: ast.AST,
    *,
    before_line: int | None = None,
    include_defaults: bool = True,
) -> dict[str, str]:
    aliases = (
        {"os": "os", "shutil": "shutil", "io": "io", "Path": "pathlib.Path"}
        if include_defaults
        else {}
    )
    for node in _scope_walk(tree):
        if before_line is not None and int(getattr(node, "lineno", 0)) >= before_line:
            continue
        if isinstance(node, ast.Import):
            for alias in node.names:
                aliases[alias.asname or alias.name.split(".")[0]] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return aliases


def _writer_import_alias_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        for alias in node.names:
            if alias.name in WRITER_OPERATIONS:
                names.add(alias.asname or alias.name)
    return names


def _qualified_name(node: ast.AST, aliases: Mapping[str, str]) -> str:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        prefix = _qualified_name(node.value, aliases)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _scope_walk(root: ast.AST) -> tuple[ast.AST, ...]:
    result: list[ast.AST] = []
    stack = [root]
    while stack:
        node = stack.pop()
        result.append(node)
        children = list(ast.iter_child_nodes(node))
        for child in reversed(children):
            if child is not root and isinstance(
                child,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda),
            ):
                continue
            stack.append(child)
    return tuple(result)


def _expression_assignments(
    tree: ast.AST,
    *,
    before_line: int | None = None,
) -> dict[str, ast.AST]:
    assignments: dict[str, ast.AST] = {}
    nodes = sorted(
        _scope_walk(tree),
        key=lambda node: (int(getattr(node, "lineno", 0)), int(getattr(node, "col_offset", 0))),
    )
    for node in nodes:
        if before_line is not None and int(getattr(node, "lineno", 0)) >= before_line:
            continue
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments[target.id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value:
            assignments[node.target.id] = node.value
    return assignments


def _annotated_path_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in _scope_walk(tree):
        if isinstance(node, ast.arg) and node.annotation:
            annotation = ast.unparse(node.annotation)
            if annotation.endswith("Path") or "Path |" in annotation or "Path]" in annotation:
                names.add(node.arg)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            annotation = ast.unparse(node.annotation)
            if annotation.endswith("Path") or "Path |" in annotation or "Path]" in annotation:
                names.add(node.target.id)
    return names


def _annotated_container_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in _scope_walk(tree):
        name = ""
        annotation: ast.AST | None = None
        if isinstance(node, ast.arg):
            name = node.arg
            annotation = node.annotation
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
            annotation = node.annotation
        if not name or annotation is None:
            continue
        tokens = set(re.findall(r"[a-z_][a-z0-9_]*", ast.unparse(annotation).lower()))
        if tokens & {
            "dict",
            "list",
            "mapping",
            "mutablemapping",
            "mutablesequence",
            "sequence",
            "set",
        }:
            names.add(name)
    return names


def _expression_text(node: ast.AST | None) -> str:
    if node is None:
        return "<missing>"
    try:
        value = ast.unparse(node)
    except (TypeError, ValueError):
        value = ast.dump(node, include_attributes=False)
    return value if len(value) <= 240 else value[:237] + "..."


def _name_looks_path(name: str) -> bool:
    tokens = {token for token in re.split(r"[^a-z0-9]+", name.lower()) if token}
    return bool(
        tokens
        & {
            "archive",
            "destination",
            "dir",
            "directory",
            "file",
            "manifest",
            "output",
            "path",
            "ref",
            "root",
            "source",
            "target",
            "temp",
            "temporary",
        }
    )


def _looks_path_expression(
    node: ast.AST | None,
    aliases: Mapping[str, str],
    assignments: Mapping[str, ast.AST],
    annotated_paths: set[str],
    *,
    seen: frozenset[str] = frozenset(),
) -> bool:
    if node is None:
        return False
    if isinstance(node, ast.Constant):
        return isinstance(node.value, (str, bytes))
    if isinstance(node, ast.Name):
        if node.id in annotated_paths or _name_looks_path(node.id):
            return True
        if node.id in assignments and node.id not in seen:
            return _looks_path_expression(
                assignments[node.id],
                aliases,
                assignments,
                annotated_paths,
                seen=seen | {node.id},
            )
        return False
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return True
    if isinstance(node, ast.Attribute):
        return node.attr in {"parent", "parents", "path", "root"} or _looks_path_expression(
            node.value,
            aliases,
            assignments,
            annotated_paths,
            seen=seen,
        )
    if isinstance(node, ast.Call):
        qualified = _qualified_name(node.func, aliases).lower()
        leaf = qualified.rsplit(".", 1)[-1]
        return (
            qualified in {"pathlib.path", "pathlib.purepath", "pathlib.pureposixpath"}
            or _name_looks_path(leaf)
            or leaf.startswith(("resolve_", "current_", "canonical_"))
            or (
                isinstance(node.func, ast.Attribute)
                and _looks_path_expression(
                    node.func.value,
                    aliases,
                    assignments,
                    annotated_paths,
                    seen=seen,
                )
            )
        )
    if isinstance(node, ast.Subscript):
        return _looks_path_expression(
            node.value,
            aliases,
            assignments,
            annotated_paths,
            seen=seen,
        )
    return False


def _write_mode(call: ast.Call, *, attribute_open: bool) -> str | None:
    index = 0 if attribute_open else 1
    mode_node: ast.AST | None = call.args[index] if len(call.args) > index else None
    specified = mode_node is not None
    for keyword in call.keywords:
        if keyword.arg == "mode":
            mode_node = keyword.value
            specified = True
    if not specified:
        return "r"
    if isinstance(mode_node, ast.Constant) and isinstance(mode_node.value, str):
        return mode_node.value
    return None


def _open_target(
    call: ast.Call,
    aliases: Mapping[str, str],
    assignments: Mapping[str, ast.AST],
    annotated_paths: set[str],
) -> ast.AST | None:
    qualified = _qualified_name(call.func, aliases)
    if qualified in {"open", "io.open"}:
        mode = _write_mode(call, attribute_open=False)
        return call.args[0] if call.args and mode and any(flag in mode for flag in "wax+") else None
    if qualified == "os.fdopen" and call.args:
        mode = _write_mode(call, attribute_open=False)
        if not mode or not any(flag in mode for flag in "wax+"):
            return None
        descriptor = call.args[0]
        if isinstance(descriptor, ast.Name):
            assigned = assignments.get(descriptor.id)
            if (
                isinstance(assigned, ast.Call)
                and _qualified_name(assigned.func, aliases) == "os.open"
                and assigned.args
            ):
                return assigned.args[0]
        return descriptor
    if qualified.endswith(".open_exclusive") and call.args:
        return call.args[0]
    if isinstance(call.func, ast.Attribute) and call.func.attr == "open":
        receiver = call.func.value
        if not _looks_path_expression(receiver, aliases, assignments, annotated_paths):
            return None
        mode = _write_mode(call, attribute_open=True)
        return receiver if mode and any(flag in mode for flag in "wax+") else None
    return None


def _stream_targets(
    tree: ast.AST,
    aliases: Mapping[str, str],
    assignments: Mapping[str, ast.AST],
    annotated_paths: set[str],
    *,
    before_line: int | None = None,
) -> dict[str, ast.AST]:
    streams: dict[str, ast.AST] = {}
    for node in _scope_walk(tree):
        if before_line is not None and int(getattr(node, "lineno", 0)) >= before_line:
            continue
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            target = _open_target(node.value, aliases, assignments, annotated_paths)
            if target is not None:
                for assigned in node.targets:
                    if isinstance(assigned, ast.Name):
                        streams[assigned.id] = target
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if not isinstance(item.context_expr, ast.Call):
                    continue
                target = _open_target(item.context_expr, aliases, assignments, annotated_paths)
                if target is not None and isinstance(item.optional_vars, ast.Name):
                    streams[item.optional_vars.id] = target
    return streams


def _scopes_for_line(tree: ast.AST, line: int) -> tuple[ast.AST, ...]:
    """返回 module→外层函数→内层函数的词法作用域链。"""

    matches: list[tuple[int, int, ast.AST]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        end = int(getattr(node, "end_lineno", node.lineno))
        if node.lineno <= line <= end:
            matches.append((end - node.lineno, node.lineno, node))
    ordered = tuple(item[2] for item in sorted(matches, key=lambda item: (-item[0], item[1])))
    return (tree, *ordered)


def _target_contract(
    node: ast.AST | None,
    aliases: Mapping[str, str],
    assignments: Mapping[str, ast.AST],
    annotated_paths: set[str],
) -> tuple[str, str]:
    resolved_node = node
    if isinstance(node, ast.Name) and node.id in assignments:
        assigned = assignments[node.id]
        if (
            isinstance(assigned, ast.Call)
            and _qualified_name(assigned.func, aliases) == "os.open"
            and assigned.args
        ):
            resolved_node = assigned.args[0]
        else:
            resolved_node = assigned
    text = _expression_text(resolved_node)
    literal_assignments = {
        name: value
        for name, expression in assignments.items()
        if (value := _literal_path(expression, {}))
    }
    literal = _literal_path(resolved_node, literal_assignments)
    if literal:
        return literal, "literal-or-alias"
    if _looks_path_expression(resolved_node, aliases, assignments, annotated_paths):
        return text, "symbolic-path"
    return text, "dynamic"


def _owner_for_ref(ref: str) -> str:
    return ref.removesuffix(".py").replace("/", ".")


def _is_proven_container_value(
    node: ast.AST,
    aliases: Mapping[str, str],
    assignments: Mapping[str, ast.AST],
    annotated_containers: set[str],
    *,
    seen: frozenset[str] = frozenset(),
) -> bool:
    if isinstance(node, (ast.Dict, ast.List, ast.Set, ast.Tuple)):
        return True
    if isinstance(node, ast.Attribute):
        return node.attr == "__dict__" or node.attr in annotated_containers
    if isinstance(node, ast.Name):
        if node.id in annotated_containers:
            return True
        if node.id in seen:
            return False
        assigned = assignments.get(node.id)
        return assigned is not None and _is_proven_container_value(
            assigned,
            aliases,
            assignments,
            annotated_containers,
            seen=seen | {node.id},
        )
    if isinstance(node, ast.Call):
        return _qualified_name(node.func, aliases) in {"dict", "list", "set", "tuple"}
    return False


def _full_call(
    *,
    ref: str,
    tree: ast.AST,
    call: ast.Call,
    operation: str,
    target: ast.AST | None,
    classification: str,
    aliases: Mapping[str, str],
    assignments: Mapping[str, ast.AST],
    annotated_paths: set[str],
) -> FullWriterCallV1:
    target_expression, target_kind = _target_contract(
        target,
        aliases,
        assignments,
        annotated_paths,
    )
    function = _function_for(tree, call.lineno)
    owner = _owner_for_ref(ref)
    call_id = canonical_digest(
        {
            "ref": ref,
            "function": function,
            "line": call.lineno,
            "operation": operation,
            "owner": owner,
            "target_expression": target_expression,
            "classification": classification,
        }
    )
    return FullWriterCallV1(
        call_id=call_id,
        ref=ref,
        function=function,
        line=call.lineno,
        operation=operation,
        owner=owner,
        target_expression=target_expression,
        target_kind=target_kind,
        classification=classification,
    )


def _classify_full_writer_call(
    *,
    ref: str,
    tree: ast.AST,
    call: ast.Call,
    aliases: Mapping[str, str],
    assignments: Mapping[str, ast.AST],
    annotated_paths: set[str],
    annotated_containers: set[str],
    streams: Mapping[str, ast.AST],
) -> tuple[FullWriterCallV1 | None, str | None]:
    qualified = _qualified_name(call.func, aliases)
    operation = qualified.rsplit(".", 1)[-1]
    if operation not in WRITER_OPERATIONS:
        return None, None

    module_targets: dict[str, int] = {
        "os.makedirs": 0,
        "os.remove": 0,
        "os.removedirs": 0,
        "os.rmdir": 0,
        "os.unlink": 0,
        "os.rename": 1,
        "os.replace": 1,
        "os.write": 0,
        "shutil.copy": 1,
        "shutil.copy2": 1,
        "shutil.copyfile": 1,
        "shutil.move": 1,
    }
    if qualified in module_targets:
        index = module_targets[qualified]
        target = call.args[index] if len(call.args) > index else None
        return (
            _full_call(
                ref=ref,
                tree=tree,
                call=call,
                operation=operation,
                target=target,
                classification="module-filesystem-writer",
                aliases=aliases,
                assignments=assignments,
                annotated_paths=annotated_paths,
            ),
            None,
        )

    if qualified == "dataclasses.replace":
        return None, "dataclass-value-replace"

    if qualified == "os.open":
        flags = _expression_text(call.args[1] if len(call.args) > 1 else None)
        if not any(
            token in flags
            for token in ("O_WRONLY", "O_RDWR", "O_CREAT", "O_TRUNC", "O_APPEND")
        ):
            return None, "read-only-os-open"
        target = call.args[0] if call.args else None
        return (
            _full_call(
                ref=ref,
                tree=tree,
                call=call,
                operation="open",
                target=target,
                classification="descriptor-open",
                aliases=aliases,
                assignments=assignments,
                annotated_paths=annotated_paths,
            ),
            None,
        )

    open_target = _open_target(call, aliases, assignments, annotated_paths)
    if open_target is not None:
        return (
            _full_call(
                ref=ref,
                tree=tree,
                call=call,
                operation="open",
                target=open_target,
                classification="write-mode-open",
                aliases=aliases,
                assignments=assignments,
                annotated_paths=annotated_paths,
            ),
            None,
        )
    if operation == "open":
        attribute_signature = isinstance(call.func, ast.Attribute) and qualified not in {
            "io.open",
            "os.fdopen",
        }
        mode = _write_mode(call, attribute_open=attribute_signature)
        target = (
            call.func.value
            if attribute_signature
            else call.args[0]
            if call.args
            else call.func
        )
        if mode is None:
            return (
                _full_call(
                    ref=ref,
                    tree=tree,
                    call=call,
                    operation=operation,
                    target=target,
                    classification="ambiguous-dynamic-open-mode",
                    aliases=aliases,
                    assignments=assignments,
                    annotated_paths=annotated_paths,
                ),
                None,
            )
        if any(flag in mode for flag in "wax+"):
            return (
                _full_call(
                    ref=ref,
                    tree=tree,
                    call=call,
                    operation=operation,
                    target=target,
                    classification="ambiguous-write-open-target",
                    aliases=aliases,
                    assignments=assignments,
                    annotated_paths=annotated_paths,
                ),
                None,
            )
        return None, "read-only-or-non-path-open"

    if not isinstance(call.func, ast.Attribute):
        return (
            _full_call(
                ref=ref,
                tree=tree,
                call=call,
                operation=operation,
                target=call.args[0] if call.args else call.func,
                classification="ambiguous-unbound-writer-name",
                aliases=aliases,
                assignments=assignments,
                annotated_paths=annotated_paths,
            ),
            None,
        )
    receiver = call.func.value
    if operation == "write" and isinstance(receiver, ast.Name):
        stream_target = streams.get(receiver.id)
        if stream_target is not None:
            return (
                _full_call(
                    ref=ref,
                    tree=tree,
                    call=call,
                    operation=operation,
                    target=stream_target,
                    classification="write-mode-open-stream",
                    aliases=aliases,
                    assignments=assignments,
                    annotated_paths=annotated_paths,
                ),
                None,
            )
        if receiver.id in {"stdout", "stderr"}:
            return None, "console-stream-write"
        return (
            _full_call(
                ref=ref,
                tree=tree,
                call=call,
                operation=operation,
                target=receiver,
                classification="ambiguous-stream-write",
                aliases=aliases,
                assignments=assignments,
                annotated_paths=annotated_paths,
            ),
            None,
        )
    if operation == "write":
        receiver_text = _expression_text(receiver).lower()
        if receiver_text.endswith((".stdout", ".stderr")):
            return None, "console-stream-write"
        return (
            _full_call(
                ref=ref,
                tree=tree,
                call=call,
                operation=operation,
                target=receiver,
                classification="ambiguous-stream-write",
                aliases=aliases,
                assignments=assignments,
                annotated_paths=annotated_paths,
            ),
            None,
        )

    path_methods = {
        "mkdir",
        "rmdir",
        "symlink_to",
        "touch",
        "unlink",
        "write_bytes",
        "write_text",
    }
    if operation in path_methods:
        return (
            _full_call(
                ref=ref,
                tree=tree,
                call=call,
                operation=operation,
                target=receiver,
                classification="path-method-writer",
                aliases=aliases,
                assignments=assignments,
                annotated_paths=annotated_paths,
            ),
            None,
        )
    if operation in {"rename", "replace"} and len(call.args) == 1:
        if not _looks_path_expression(receiver, aliases, assignments, annotated_paths):
            return (
                _full_call(
                    ref=ref,
                    tree=tree,
                    call=call,
                    operation=operation,
                    target=call.args[0],
                    classification="ambiguous-single-argument-replace",
                    aliases=aliases,
                    assignments=assignments,
                    annotated_paths=annotated_paths,
                ),
                None,
            )
        return (
            _full_call(
                ref=ref,
                tree=tree,
                call=call,
                operation=operation,
                target=call.args[0],
                classification="path-method-writer",
                aliases=aliases,
                assignments=assignments,
                annotated_paths=annotated_paths,
            ),
            None,
        )
    if operation == "replace" and not call.args and {
        keyword.arg for keyword in call.keywords
    } <= {"microsecond", "parameters", "tzinfo"}:
        return None, "typed-value-replace"
    if operation == "replace" and len(call.args) >= 2:
        return None, "string-or-object-replace"
    if operation == "copy" and not call.args and not call.keywords:
        if _is_proven_container_value(
            receiver,
            aliases,
            assignments,
            annotated_containers,
        ):
            return None, "typed-container-copy"
        return (
            _full_call(
                ref=ref,
                tree=tree,
                call=call,
                operation=operation,
                target=receiver,
                classification="ambiguous-zero-argument-copy",
                aliases=aliases,
                assignments=assignments,
                annotated_paths=annotated_paths,
            ),
            None,
        )
    if operation == "remove" and isinstance(receiver, ast.Name):
        if _is_proven_container_value(
            receiver,
            aliases,
            assignments,
            annotated_containers,
        ):
            return None, "typed-container-remove"
    if operation in {"copy", "copy2", "copyfile", "move", "remove", "removedirs", "makedirs"}:
        target = call.args[-1] if operation in DESTINATION_OPERATIONS and call.args else receiver
        return (
            _full_call(
                ref=ref,
                tree=tree,
                call=call,
                operation=operation,
                target=target,
                classification="ambiguous-non-module-writer-method",
                aliases=aliases,
                assignments=assignments,
                annotated_paths=annotated_paths,
            ),
            None,
        )
    return (
        _full_call(
            ref=ref,
            tree=tree,
            call=call,
            operation=operation,
            target=receiver,
            classification="ambiguous-writer-shape",
            aliases=aliases,
            assignments=assignments,
            annotated_paths=annotated_paths,
        ),
        None,
    )


def scan_full_writer_baseline(
    release_root: Path,
    *,
    source_roots: tuple[str, ...],
    include_calls: bool = True,
) -> dict[str, Any]:
    root = release_root.resolve()
    refs: list[tuple[str, Path]] = []
    findings: list[str] = []
    for source_ref in source_roots:
        source = root / source_ref
        if source.is_symlink() or not source.is_dir() or source.resolve().parent != root:
            findings.append(f"DETECTOR_FULL_SOURCE_ROOT_INVALID:{source_ref}")
            continue
        refs.extend(
            (path.relative_to(root).as_posix(), path)
            for path in source.rglob("*.py")
            if not path.is_symlink() and path.is_file()
        )
    refs = sorted(set(refs), key=lambda item: item[0])
    observed_source_file_count = len(refs)
    if len(refs) > MAX_FILES:
        findings.append("DETECTOR_FULL_FILE_BUDGET_EXCEEDED")
        refs = refs[:MAX_FILES]

    calls: list[FullWriterCallV1] = []
    exclusions: dict[str, int] = {}
    source_manifest: list[dict[str, Any]] = []
    scanned_bytes = 0
    for ref, path in refs:
        size = path.stat().st_size
        if scanned_bytes + size > MAX_BYTES:
            findings.append("DETECTOR_FULL_BYTE_BUDGET_EXCEEDED")
            break
        raw = path.read_bytes()
        scanned_bytes += len(raw)
        source_manifest.append(
            {"ref": ref, "bytes": len(raw), "sha256": sha256(raw).hexdigest()}
        )
        if len(raw) != size or scanned_bytes > MAX_BYTES:
            findings.append("DETECTOR_FULL_BYTE_BUDGET_EXCEEDED")
            break
        try:
            tree = ast.parse(raw.decode("utf-8"), filename=ref)
        except (SyntaxError, UnicodeDecodeError):
            findings.append(f"DETECTOR_FULL_PARSE_FAILED:{ref}")
            continue
        module_aliases = _import_aliases(tree)
        writer_alias_names = _writer_import_alias_names(tree)
        module_assignments = _expression_assignments(tree)
        module_annotated_paths = _annotated_path_names(tree)
        module_annotated_containers = _annotated_container_names(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            raw_operation = (
                node.func.attr
                if isinstance(node.func, ast.Attribute)
                else node.func.id
                if isinstance(node.func, ast.Name)
                else ""
            )
            if raw_operation not in WRITER_OPERATIONS and raw_operation not in writer_alias_names:
                continue
            scopes = _scopes_for_line(tree, node.lineno)
            aliases = dict(module_aliases)
            assignments = dict(module_assignments)
            annotated_paths = set(module_annotated_paths)
            annotated_containers = set(module_annotated_containers)
            streams: dict[str, ast.AST] = {}
            for lexical_scope in scopes[1:]:
                aliases.update(
                    _import_aliases(
                        lexical_scope,
                        before_line=node.lineno,
                        include_defaults=False,
                    )
                )
                assignments.update(
                    _expression_assignments(lexical_scope, before_line=node.lineno)
                )
                annotated_paths.update(_annotated_path_names(lexical_scope))
                annotated_containers.update(
                    _annotated_container_names(lexical_scope)
                )
                streams.update(
                    _stream_targets(
                        lexical_scope,
                        aliases,
                        assignments,
                        annotated_paths,
                        before_line=node.lineno,
                    )
                )
            writer, exclusion = _classify_full_writer_call(
                ref=ref,
                tree=tree,
                call=node,
                aliases=aliases,
                assignments=assignments,
                annotated_paths=annotated_paths,
                annotated_containers=annotated_containers,
                streams=streams,
            )
            if writer is not None:
                calls.append(writer)
            elif exclusion:
                exclusions[exclusion] = exclusions.get(exclusion, 0) + 1

    ordered = tuple(sorted(calls, key=lambda item: (item.ref, item.line, item.call_id)))
    ambiguous = tuple(
        item for item in ordered if item.classification.startswith("ambiguous-")
    )
    manifest_digest = canonical_digest([item.as_dict() for item in ordered])
    payload: dict[str, Any] = {
        "schema_version": 1,
        "kind": "FullWriterBaselineReportV1",
        "decision": "BLOCKED" if findings or ambiguous else "PASS",
        "qualification": "current-product-writer-inventory-v1",
        "source_roots": list(source_roots),
        "source_file_count": observed_source_file_count,
        "scanned_byte_count": scanned_bytes,
        "source_manifest_digest": canonical_digest(source_manifest),
        "writer_call_count": len(ordered),
        "classified_writer_call_count": len(ordered) - len(ambiguous),
        "ambiguous_writer_call_count": len(ambiguous),
        "writer_manifest_digest": manifest_digest,
        "classification_counts": {
            key: len([item for item in ordered if item.classification == key])
            for key in sorted({item.classification for item in ordered})
        },
        "target_kind_counts": {
            key: len([item for item in ordered if item.target_kind == key])
            for key in sorted({item.target_kind for item in ordered})
        },
        "excluded_non_file_call_count": sum(exclusions.values()),
        "exclusion_counts": dict(sorted(exclusions.items())),
        "findings": sorted(set(findings)),
        "known_limits": [
            "database/network mutation and source_roots external code are outside this file-writer inventory",
            "reflection, runtime-generated code and native-extension writes require separate runtime controls",
            "symbolic-path classification identifies a bounded expression and owner, not every runtime path value",
        ],
        "mutation_count": 0,
    }
    payload["report_digest"] = canonical_digest(payload)
    if include_calls:
        payload["writer_calls"] = [item.as_dict() for item in ordered]
        payload["ambiguous_calls"] = [item.as_dict() for item in ambiguous]
    return payload


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
        "legacy_d0_calibration",
        "full_source_baseline",
        "dynamic_allowlist",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ValueError("detector incremental baseline fields mismatch")
    if payload.get("schema_version") != 2 or payload.get("kind") != "DetectorQualifiedBaselineV2":
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
    source_roots = tuple(roots)
    full_report = scan_full_writer_baseline(
        release_root,
        source_roots=source_roots,
        include_calls=False,
    )
    full_baseline = baseline.get("full_source_baseline")
    expected_full_keys = {
        "qualification",
        "source_file_count",
        "scanned_byte_count",
        "source_manifest_digest",
        "writer_call_count",
        "classified_writer_call_count",
        "ambiguous_writer_call_count",
        "excluded_non_file_call_count",
        "writer_manifest_digest",
        "report_digest",
    }
    if not isinstance(full_baseline, dict) or set(full_baseline) != expected_full_keys:
        findings.append("DETECTOR_FULL_BASELINE_FIELDS_INVALID")
    else:
        observed_full = {key: full_report.get(key) for key in sorted(expected_full_keys)}
        if observed_full != {key: full_baseline.get(key) for key in sorted(expected_full_keys)}:
            findings.append("DETECTOR_FULL_BASELINE_DRIFT")
    if full_report.get("decision") != "PASS":
        findings.append("DETECTOR_FULL_BASELINE_UNQUALIFIED")
    calls, scan_findings, stats = scan_incremental_writers(
        release_root,
        baseline_oid=baseline_oid,
        source_roots=source_roots,
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
    calibration = baseline.get("legacy_d0_calibration")
    if calibration != {
        "total_file_writer_calls": 1063,
        "resolved_file_writer_calls": 10,
        "unresolved_file_writer_calls": 1053,
        "claim": "historical-limitation-not-product-cleanliness",
    }:
        findings.append("DETECTOR_HISTORICAL_CALIBRATION_DRIFT")
    payload = {
        "schema_version": 2,
        "kind": "DetectorQualificationReportV2",
        "decision": "BLOCKED" if findings else "PASS",
        "qualification": "product-full-baseline-plus-incremental-hard-gate-v2",
        "baseline_release_oid": baseline_oid,
        "legacy_d0_calibration": calibration,
        "full_source_baseline": full_report,
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
            "D0 的 1053 个 unresolved writer-like call 是不可改写的旧扫描校准，不再作为当前产品分母",
            "全量门覆盖 source_roots 当前 Python file writer；增量门继续覆盖 baseline 后新增/修改调用行及变更函数体",
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
    parser.add_argument("--full-baseline", action="store_true")
    parsed = parser.parse_args(argv or [])
    try:
        if parsed.full_baseline:
            report = scan_full_writer_baseline(
                parsed.project_root,
                source_roots=("meta_flow", "scripts"),
                include_calls=parsed.include_calls,
            )
        else:
            report = check_detector_qualification(parsed.project_root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"decision": "BLOCKED", "errors": [str(exc)]}, ensure_ascii=False))
        return 1
    if not parsed.include_calls and not parsed.full_baseline:
        report = {key: value for key, value in report.items() if key != "writer_calls"}
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["decision"] == "PASS" else 1


__all__ = [
    "FullWriterCallV1",
    "WriterCallV1",
    "check_baseline_ancestor",
    "check_detector_qualification",
    "qualify_dynamic_allowlist",
    "scan_full_writer_baseline",
    "scan_incremental_writers",
]
