"""CR-075 P0：primitive facade 静态不变量（A-P0-01 / A-P0-02-rev1）。

A-P0-01：import SCC=0；P0 owner 集跨 owner `_` 符号导入=0；重复原语实现收敛为 1。
A-P0-02（HLD §2.1-rev1，DQ-075-P0-01 决策 A）：五模块行数不高于 facade 收敛后基线。
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

PACKAGE_ROOT = Path(__file__).parents[2] / "meta_flow"

FACADE = "meta_flow.execution_control.primitives"
P0_OWNER_MODULES = [
    "meta_flow.work.lifecycle_transaction",
    "meta_flow.work.status_transition",
    "meta_flow.work.transaction_child",
    "meta_flow.work.handoff",
    "meta_flow.state.current",
    "meta_flow.state.projection_transaction",
    "meta_flow.execution_control.exact_file_transaction",
]
# P0 纯结构搬迁后的自然行数上限（HLD §2.1-rev1）。
LINE_BUDGETS_REV1 = {
    "meta_flow/work/lifecycle_transaction.py": 2539,
    "meta_flow/work/status_transition.py": 1393,
    "meta_flow/work/transaction_child.py": 437,
    "meta_flow/state/current.py": 4000,
    "meta_flow/work/handoff.py": 667,
}
# facade 唯一实现的原语集合（current.py 的 now_utc 为 seconds 语义的领域
# 时间戳，非重复实现，不计入）。
FACADE_PRIMITIVES = {
    "digest_bytes",
    "safe_authorization_id",
    "fsync_directory",
    "write_atomic",
    "write_json_atomic",
    "replace_bytes",
    "render_yaml_bytes",
    "plan_digest",
    "manifest_path",
    "acquire_writer_lock",
    "release_writer_lock",
}


def _module_source_path(module_name: str) -> Path:
    relative = module_name.removeprefix("meta_flow.").replace(".", "/")
    return PACKAGE_ROOT / f"{relative}.py"


def _module_imports(module_name: str) -> set[str]:
    tree = ast.parse(
        _module_source_path(module_name).read_text(
            encoding="utf-8"
        )
    )
    dependencies: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("meta_flow."):
            dependencies.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("meta_flow."):
                    dependencies.add(alias.name)
    return dependencies


def test_a_p0_01_import_scc_is_zero() -> None:
    modules = [*P0_OWNER_MODULES, FACADE]
    graph = {module: _module_imports(module) & set(modules) for module in modules}
    state: dict[str, int] = {module: 0 for module in modules}

    def visit(node: str, stack: list[str]) -> None:
        state[node] = 1
        stack.append(node)
        for dependency in sorted(graph[node]):
            if state[dependency] == 1:
                raise AssertionError(f"import cycle: {stack[stack.index(dependency):] + [dependency]}")
            if state[dependency] == 0:
                visit(dependency, stack)
        stack.pop()
        state[node] = 2

    for module in modules:
        if state[module] == 0:
            visit(module, [])


def test_a_p0_01_no_cross_owner_private_imports_in_p0_set() -> None:
    offenders: list[tuple[str, str, str]] = []
    for module in P0_OWNER_MODULES:
        tree = ast.parse(_module_source_path(module).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.ImportFrom) and node.module):
                continue
            if not node.module.startswith("meta_flow."):
                continue
            if node.module == FACADE:
                continue
            for alias in node.names:
                if alias.name.startswith("_"):
                    offenders.append((module, node.module, alias.name))
    assert offenders == [], f"cross-owner private imports: {offenders}"


def test_a_p0_01_facade_is_sole_primitive_implementation_owner() -> None:
    duplicate_owners: dict[str, list[str]] = {}
    for module in [*P0_OWNER_MODULES, FACADE]:
        tree = ast.parse(_module_source_path(module).read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in FACADE_PRIMITIVES and module != FACADE:
                    duplicate_owners.setdefault(node.name, []).append(module)
    assert duplicate_owners == {}, f"duplicate primitive defs outside facade: {duplicate_owners}"


def test_a_p0_01_facade_exports_lld_contract_api() -> None:
    primitives = importlib.import_module(FACADE)
    expected = {
        "DIGEST_RE",
        "digest_bytes",
        "now_utc",
        "safe_authorization_id",
        "fsync_directory",
        "write_atomic",
        "safe_path",
        "write_json_atomic",
        "replace_bytes",
        "render_yaml_bytes",
        "plan_digest",
        "manifest_path",
        "ensure_runtime_chain",
        "acquire_writer_lock",
        "release_writer_lock",
        "SharedProjectionWriterLock",
        "acquire_shared_projection_writer_lock",
        "validate_shared_projection_writer_lock",
        "release_shared_projection_writer_lock",
    }
    missing = expected - set(vars(primitives))
    assert missing == set(), f"facade API missing: {sorted(missing)}"


def test_a_p0_02_rev1_line_budgets_hold() -> None:
    overruns: list[str] = []
    for relative, budget in LINE_BUDGETS_REV1.items():
        lines = len((PACKAGE_ROOT / relative.removeprefix("meta_flow/")).read_text(encoding="utf-8").splitlines())
        if lines > budget:
            overruns.append(f"{relative}: {lines} > {budget}")
    assert overruns == [], f"line budgets exceeded: {overruns}"


def test_facade_now_utc_is_microsecond_precision() -> None:
    from meta_flow.execution_control.primitives import now_utc

    stamp = now_utc()
    fraction = stamp.split("+")[0].split("Z")[0].split(".")[1]
    assert len(fraction) == 6, f"facade now_utc must keep microsecond precision: {stamp}"
