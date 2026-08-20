"""revision 9 的 package-owned、只读 consumer scanner。

scanner 自己发现完整 tracked Python universe；调用方不能注入文件列表、subject、
classification、exclusion、期望摘要或 PASS 结论。最终 authority 仍由独立 CP7
签发，本模块只产生可复算的候选结果。
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import inspect
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from meta_flow.execution_control.contract import canonical_digest

SCANNER_REF = "meta_flow/execution_control/consumer_scan.py"
SCANNER_CALLABLE_REF = (
    "meta_flow.execution_control.consumer_scan.scan_execution_control_consumers"
)
TRACKED_DISCOVERY_COMMAND = ("git", "ls-files", "-z", "--", "meta_flow", "tests")
PARSER_IDENTITY = "cpython-ast-python-3.11"
PROFILE_IDENTITY = "cr069-s5-consumer-scan-v1"

# revision 8 的 26 + 4 只作不可删除的 historical floor；final subject 还要并入
# revision 9 allowed-path 的全部当前 public exports，宁可保守扩大，也不能漏掉新 API。
HISTORICAL_SUBJECT_FLOOR = (
    "meta_flow.evolution.build_evolution_start_plan",
    "meta_flow.evolution.materialize_evolution_work",
    "meta_flow.evolution_cli.start_main",
    "meta_flow.execution_control.migration.ProviderActivationReceiptV1",
    "meta_flow.execution_control.migration.ProviderQualificationEvidenceV1",
    "meta_flow.execution_control.migration.build_provider_qualification_evidence",
    "meta_flow.execution_control.migration.current_execution_control_policy",
    "meta_flow.execution_control.migration.load_provider_activation_receipt",
    "meta_flow.execution_control.migration.materialize_provider_activation_receipt",
    "meta_flow.execution_control.runtime_context.ActiveExecutionInventoryV1",
    "meta_flow.execution_control.runtime_context.ExecutionControlContextV1",
    "meta_flow.execution_control.runtime_context.RequestMaterializationCandidateV1",
    "meta_flow.execution_control.runtime_context.build_execution_control_context",
    "meta_flow.execution_control.runtime_context.project_active_execution_inventory",
    "meta_flow.execution_control.runtime_context.target_preimage_digest",
    "meta_flow.work.assurance.ReviewPlan",
    "meta_flow.work.assurance.ValidationPlan",
    "meta_flow.work.assurance.build_review_plan",
    "meta_flow.work.assurance.build_validation_plan",
    "meta_flow.work.cli.init_main",
    "meta_flow.work.store.WorkInitAction",
    "meta_flow.work.store.WorkInitPlan",
    "meta_flow.work.store.WorkInitReceipt",
    "meta_flow.work.store.apply_work_init",
    "meta_flow.work.store.plan_work_init",
    "meta_flow.work.store.plan_work_init_from_release_root",
    "meta_flow.execution_control.migration.ExecutionControlPolicyV1",
    "meta_flow.execution_control.migration.ProviderReceiptLoadV1",
    "meta_flow.execution_control.migration.ProviderReceiptMaterializationV1",
    "meta_flow.execution_control.migration.UnknownProviderContractError",
    "meta_flow.execution_control.migration._mint_materialization_capability",
    "meta_flow.execution_control.migration._perform_receipt_create_only",
)

ALLOWED_DELTA_PATHS = (
    "meta_flow/execution_control/migration.py",
    "meta_flow/execution_control/runtime_context.py",
    SCANNER_REF,
    "meta_flow/work/store.py",
    "meta_flow/work/assurance.py",
    "meta_flow/work/cli.py",
    "meta_flow/evolution.py",
    "meta_flow/evolution_cli.py",
)

_FIXED_CLASSIFICATIONS = {
    "meta_flow/cli.py": ("validation-only-indirect-dispatch", "S5-validation"),
    "meta_flow/evolution.py": ("write-owned-producer", "STORY-CR069-F1-S5"),
    "meta_flow/evolution_cli.py": ("write-owned-adapter", "STORY-CR069-F1-S5"),
    "meta_flow/execution_control/consumer_scan.py": (
        "canonical-scanner-owner",
        "STORY-CR069-F1-S5",
    ),
    "meta_flow/execution_control/migration.py": (
        "canonical-policy-owner",
        "STORY-CR069-F1-S5",
    ),
    "meta_flow/execution_control/runtime_context.py": (
        "canonical-context-owner",
        "STORY-CR069-F1-S5",
    ),
    "meta_flow/work/assurance.py": ("write-owned-assurance", "STORY-CR069-F1-S5"),
    "meta_flow/work/cli.py": ("write-owned-adapter", "STORY-CR069-F1-S5"),
    # production_validation 只读取 canonical preimage 摘要并构造 admission graph；
    # 模块自身不拥有 writer，不能与事务 writer 混为一类。
    "meta_flow/work/production_validation.py": (
        "canonical-context-read-only-validator",
        "STORY-CR074-S05",
    ),
    # scope_amend 读取 canonical execution context，同时拥有 add-only、可恢复的
    # scope amendment transaction writer；该分类不授予 materialization security 边。
    "meta_flow/work/scope_amend.py": (
        "canonical-context-reader-transaction-writer",
        "STORY-CR074-S05",
    ),
    "meta_flow/work/store.py": ("canonical-writer-owner", "STORY-CR069-F1-S5"),
    "tests/test_cr066_read_behavior.py": ("write-owned-fixture", "STORY-CR069-F1-S5"),
    "tests/test_execution_control_consumer_scan.py": (
        "write-owned-targeted",
        "STORY-CR069-F1-S5",
    ),
    "tests/test_execution_control_migration.py": (
        "write-owned-targeted",
        "STORY-CR069-F1-S5",
    ),
    "tests/test_vnext_learning_cli.py": ("write-owned-fixture", "STORY-CR069-F1-S5"),
    "tests/test_vnext_retrospective_evolution.py": (
        "write-owned-compatibility",
        "STORY-CR069-F1-S5",
    ),
    "tests/test_vnext_work_assurance_handoff_query.py": (
        "validation-only",
        "S5-validation",
    ),
    "tests/test_vnext_work_store_cli.py": (
        "write-owned-compatibility",
        "STORY-CR069-F1-S5",
    ),
}

_EXPLICIT_DISPATCH_EDGES = (
    "meta_flow/cli.py:meta_flow.work.cli.main",
    "meta_flow/cli.py:meta_flow.evolution_cli.main",
)

# 私有 materialization 边不是普通 public consumer；它们是冻结的 security
# subjects，必须由 scanner 本身看到并且各自只有一个 writer/mint owner edge。
_SECURITY_SUBJECTS = frozenset(
    {
        "meta_flow.execution_control.migration._mint_materialization_capability",
        "meta_flow.execution_control.migration._perform_receipt_create_only",
    }
)


@dataclass(frozen=True, slots=True)
class ConsumerSourceV1:
    ref: str
    sha256: str
    bytes: int

    def as_dict(self) -> dict[str, object]:
        return {"ref": self.ref, "sha256": self.sha256, "bytes": self.bytes}


@dataclass(frozen=True, slots=True)
class ConsumerEdgeV1:
    symbol: str
    consumer_ref: str
    lines: tuple[int, ...]
    kind: str

    def as_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "consumer_ref": self.consumer_ref,
            "lines": list(self.lines),
            "kind": self.kind,
        }


@dataclass(frozen=True, slots=True)
class ConsumerClassificationV1:
    ref: str
    classification: str
    owner: str

    def as_dict(self) -> dict[str, str]:
        return {
            "ref": self.ref,
            "classification": self.classification,
            "owner": self.owner,
        }


@dataclass(frozen=True, slots=True)
class ConsumerScanResultV1:
    decision: str
    reason_codes: tuple[str, ...]
    sources: tuple[ConsumerSourceV1, ...]
    parsed_refs: tuple[str, ...]
    excluded_refs: tuple[str, ...]
    subject_symbols: tuple[str, ...]
    edges: tuple[ConsumerEdgeV1, ...]
    explicit_dispatch_edges: tuple[str, ...]
    classifications: tuple[ConsumerClassificationV1, ...]
    scanner_callable_ref: str
    scanner_source_digest: str
    scanner_contract_digest: str
    parser_identity: str
    profile_digest: str
    command_identity_digest: str
    source_set_digest: str
    subject_set_digest: str
    edge_set_digest: str
    classification_digest: str
    exit_counters: tuple[tuple[str, int], ...]
    result_digest: str
    mutation_count: int = 0

    def as_dict(self, *, include_result_digest: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": 1,
            "decision": self.decision,
            "reason_codes": list(self.reason_codes),
            "sources": [item.as_dict() for item in self.sources],
            "parsed_refs": list(self.parsed_refs),
            "excluded_refs": list(self.excluded_refs),
            "subject_symbols": list(self.subject_symbols),
            "edges": [item.as_dict() for item in self.edges],
            "explicit_dispatch_edges": list(self.explicit_dispatch_edges),
            "classifications": [item.as_dict() for item in self.classifications],
            "scanner_callable_ref": self.scanner_callable_ref,
            "scanner_source_digest": self.scanner_source_digest,
            "scanner_contract_digest": self.scanner_contract_digest,
            "parser_identity": self.parser_identity,
            "profile_digest": self.profile_digest,
            "command_identity_digest": self.command_identity_digest,
            "source_set_digest": self.source_set_digest,
            "subject_set_digest": self.subject_set_digest,
            "edge_set_digest": self.edge_set_digest,
            "classification_digest": self.classification_digest,
            "exit_counters": dict(self.exit_counters),
            "mutation_count": self.mutation_count,
        }
        if include_result_digest:
            payload["result_digest"] = self.result_digest
        return payload


def _module_name(ref: str) -> str:
    return ref[:-3].replace("/", ".") if ref.endswith(".py") else ref.replace("/", ".")


def _safe_tracked_ref(raw: bytes) -> str:
    try:
        value = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("SCANNER_TRACKED_REF_NOT_UTF8") from error
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.suffix != ".py"
        or not path.parts
        or path.parts[0] not in {"meta_flow", "tests"}
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("SCANNER_UNSAFE_REF")
    return path.as_posix()


def _public_exports(ref: str, tree: ast.AST) -> tuple[str, ...]:
    if ref not in ALLOWED_DELTA_PATHS:
        return ()
    module = _module_name(ref)
    return tuple(
        sorted(
            f"{module}.{node.name}"
            for node in getattr(tree, "body", ())
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and not node.name.startswith("_")
        )
    )


def _attribute_parts(node: ast.Attribute) -> tuple[str, ...] | None:
    parts = [node.attr]
    current: ast.expr = node.value
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return tuple(reversed(parts))


def _edges_for_tree(
    ref: str,
    tree: ast.AST,
    subjects: frozenset[str],
) -> tuple[ConsumerEdgeV1, ...]:
    module = _module_name(ref)
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                if alias.name != "*":
                    aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                aliases[alias.asname or alias.name.split(".")[0]] = alias.name
    hits: dict[tuple[str, str], set[int]] = {}
    for node in ast.walk(tree):
        target = ""
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            target = aliases.get(node.id, f"{module}.{node.id}")
        elif isinstance(node, ast.Attribute):
            parts = _attribute_parts(node)
            if parts:
                root = aliases.get(parts[0], parts[0])
                target = ".".join((root, *parts[1:]))
        if target in subjects:
            hits.setdefault((target, "ast-reference"), set()).add(node.lineno)
    return tuple(
        ConsumerEdgeV1(symbol, ref, tuple(sorted(lines)), kind)
        for (symbol, kind), lines in sorted(hits.items())
    )


def _classification_for(ref: str) -> ConsumerClassificationV1 | None:
    fixed = _FIXED_CLASSIFICATIONS.get(ref)
    if fixed:
        return ConsumerClassificationV1(ref, fixed[0], fixed[1])
    if ref.startswith("tests/"):
        return ConsumerClassificationV1(ref, "existing-test-consumer", "existing-test-owner")
    return None


def _blocked(reason: str, *, command_digest: str) -> ConsumerScanResultV1:
    counters = (
        ("syntax_error_count", 1 if reason == "SCANNER_SYNTAX_ERROR" else 0),
        ("unclassified_consumer_count", 0),
        ("unclassified_legacy_writer_call_count", 0),
        ("unfingerprinted_scanned_or_excluded_path_count", 0),
        ("unresolved_exclusion_count", 0),
        ("unresolved_path_count", 1),
        ("security_call_edge_count", 0),
        ("explicit_dispatch_error_count", 0),
    )
    empty_digest = canonical_digest([])
    payload = {
        "decision": "BLOCKED",
        "reason_codes": [reason],
        "command_identity_digest": command_digest,
        "exit_counters": dict(counters),
        "mutation_count": 0,
    }
    return ConsumerScanResultV1(
        "BLOCKED",
        (reason,),
        (),
        (),
        (),
        tuple(HISTORICAL_SUBJECT_FLOOR),
        (),
        (),
        (),
        SCANNER_CALLABLE_REF,
        "",
        "",
        PARSER_IDENTITY,
        canonical_digest(PROFILE_IDENTITY),
        command_digest,
        empty_digest,
        canonical_digest(HISTORICAL_SUBJECT_FLOOR),
        empty_digest,
        empty_digest,
        counters,
        canonical_digest(payload),
        0,
    )


def scan_execution_control_consumers(release_root: Path) -> ConsumerScanResultV1:
    """执行完整 tracked Python census；唯一 public 输入是 canonical release root。"""

    root = release_root.resolve()
    command_digest = canonical_digest(list(TRACKED_DISCOVERY_COMMAND))
    completed = subprocess.run(
        (TRACKED_DISCOVERY_COMMAND[0], "-C", str(root), *TRACKED_DISCOVERY_COMMAND[1:]),
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0 or completed.stderr:
        return _blocked("SCANNER_GIT_DISCOVERY_FAILED", command_digest=command_digest)
    try:
        refs = tuple(
            sorted(
                _safe_tracked_ref(item)
                for item in completed.stdout.split(b"\0")
                if item and item.endswith(b".py")
            )
        )
    except ValueError as error:
        return _blocked(str(error), command_digest=command_digest)
    if len(refs) != len(set(refs)):
        return _blocked("SCANNER_DUPLICATE_TRACKED_REF", command_digest=command_digest)
    if SCANNER_REF not in refs:
        return _blocked("SCANNER_SOURCE_NOT_TRACKED", command_digest=command_digest)

    sources: list[ConsumerSourceV1] = []
    trees: dict[str, ast.AST] = {}
    subjects = set(HISTORICAL_SUBJECT_FLOOR) | set(_SECURITY_SUBJECTS)
    for ref in refs:
        try:
            raw = (root / PurePosixPath(ref)).read_bytes()
        except OSError:
            return _blocked("SCANNER_SOURCE_MISSING", command_digest=command_digest)
        try:
            tree = ast.parse(raw, filename=ref)
        except (SyntaxError, UnicodeDecodeError):
            return _blocked("SCANNER_SYNTAX_ERROR", command_digest=command_digest)
        sources.append(ConsumerSourceV1(ref, hashlib.sha256(raw).hexdigest(), len(raw)))
        trees[ref] = tree
        subjects.update(_public_exports(ref, tree))

    subject_set = frozenset(subjects)
    edges = tuple(
        sorted(
            (
                edge
                for ref, tree in trees.items()
                for edge in _edges_for_tree(ref, tree, subject_set)
            ),
            key=lambda item: (item.symbol, item.consumer_ref, item.kind, item.lines),
        )
    )
    consumer_refs = set(edge.consumer_ref for edge in edges)
    consumer_refs.update(item.split(":", 1)[0] for item in _EXPLICIT_DISPATCH_EDGES)
    classifications = tuple(
        item
        for ref in sorted(consumer_refs)
        if (item := _classification_for(ref)) is not None
    )
    classified_refs = {item.ref for item in classifications}
    unclassified = sorted(consumer_refs - classified_refs)

    # legacy process-root create 只允许 store 自身的 compatibility replay；测试中除
    # closed matrix owner 外出现该调用，必须在 final candidate 前迁移或显式分类。
    legacy_calls = {
        edge.consumer_ref
        for edge in edges
        if edge.symbol == "meta_flow.work.store.plan_work_init"
        and edge.consumer_ref not in {"meta_flow/work/store.py", "tests/test_vnext_work_store_cli.py"}
    }
    security_edges = {
        subject: tuple(
            edge
            for edge in edges
            if edge.symbol == subject and not edge.consumer_ref.startswith("tests/")
        )
        for subject in _SECURITY_SUBJECTS
    }
    invalid_security_edges = {
        subject: values
        for subject, values in security_edges.items()
        if (
            len(values) != 1
            or values[0].consumer_ref != "meta_flow/execution_control/migration.py"
            or len(values[0].lines) != 1
        )
    }
    explicit_subjects = frozenset(item.split(":", 1)[1] for item in _EXPLICIT_DISPATCH_EDGES)
    explicit_ast_edges = {
        f"{edge.consumer_ref}:{edge.symbol}"
        for ref, tree in trees.items()
        for edge in _edges_for_tree(ref, tree, explicit_subjects)
    }
    explicit_dispatch_errors = set(_EXPLICIT_DISPATCH_EDGES) ^ explicit_ast_edges
    counters = (
        ("syntax_error_count", 0),
        ("unclassified_consumer_count", len(unclassified)),
        ("unclassified_legacy_writer_call_count", len(legacy_calls)),
        ("unfingerprinted_scanned_or_excluded_path_count", len(refs) - len(sources)),
        ("unresolved_exclusion_count", 0),
        ("unresolved_path_count", 0),
        ("security_call_edge_count", len(invalid_security_edges)),
        ("explicit_dispatch_error_count", len(explicit_dispatch_errors)),
    )
    reason_codes = tuple(
        reason
        for condition, reason in (
            (bool(unclassified), "SCANNER_UNCLASSIFIED_CONSUMER"),
            (bool(legacy_calls), "SCANNER_UNCLASSIFIED_LEGACY_WRITER_CALL"),
            (bool(invalid_security_edges), "SCANNER_SECURITY_CALL_EDGE_INVALID"),
            (bool(explicit_dispatch_errors), "SCANNER_EXPLICIT_DISPATCH_EDGE_INVALID"),
        )
        if condition
    )
    decision = "READY" if not reason_codes and all(value == 0 for _, value in counters) else "BLOCKED"

    source_set_digest = canonical_digest([item.as_dict() for item in sources])
    subject_set_digest = canonical_digest(sorted(subject_set))
    edge_set_digest = canonical_digest([item.as_dict() for item in edges])
    classification_digest = canonical_digest([item.as_dict() for item in classifications])
    scanner_source = next(item for item in sources if item.ref == SCANNER_REF)
    scanner_contract_digest = canonical_digest(
        {
            "callable_ref": SCANNER_CALLABLE_REF,
            "signature": str(inspect.signature(scan_execution_control_consumers)),
            "parser": PARSER_IDENTITY,
            "profile": PROFILE_IDENTITY,
            "command": list(TRACKED_DISCOVERY_COMMAND),
        }
    )
    payload = {
        "decision": decision,
        "reason_codes": list(reason_codes),
        "source_set_digest": source_set_digest,
        "subject_set_digest": subject_set_digest,
        "edge_set_digest": edge_set_digest,
        "classification_digest": classification_digest,
        "scanner_source_digest": scanner_source.sha256,
        "scanner_contract_digest": scanner_contract_digest,
        "parser_identity": PARSER_IDENTITY,
        "profile_digest": canonical_digest(PROFILE_IDENTITY),
        "command_identity_digest": command_digest,
        "exit_counters": dict(counters),
        "mutation_count": 0,
    }
    return ConsumerScanResultV1(
        decision,
        reason_codes,
        tuple(sources),
        refs,
        (),
        tuple(sorted(subject_set)),
        edges,
        tuple(sorted(explicit_ast_edges)),
        classifications,
        SCANNER_CALLABLE_REF,
        scanner_source.sha256,
        scanner_contract_digest,
        PARSER_IDENTITY,
        canonical_digest(PROFILE_IDENTITY),
        command_digest,
        source_set_digest,
        subject_set_digest,
        edge_set_digest,
        classification_digest,
        counters,
        canonical_digest(payload),
        0,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m meta_flow.execution_control.consumer_scan")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--format", choices=("json",), default="json")
    parsed = parser.parse_args(argv)
    result = scan_execution_control_consumers(Path(parsed.project_root))
    print(json.dumps(result.as_dict(), ensure_ascii=False, sort_keys=True))
    return 0 if result.decision == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ConsumerClassificationV1",
    "ConsumerEdgeV1",
    "ConsumerScanResultV1",
    "ConsumerSourceV1",
    "scan_execution_control_consumers",
]
