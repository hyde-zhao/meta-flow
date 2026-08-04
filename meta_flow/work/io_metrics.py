"""轻量、默认关闭的 Work I/O 计量器。

计量器只接受逻辑引用，不接触文件系统，也不持久化事件。调用方可以在一次
operation 内显式开启它，并在命令结束时读取一个聚合 summary。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

GOVERNANCE_CATEGORIES = frozenset(
    {
        "binding_policy",
        "project_work",
        "cr_design",
        "state_projection",
        "ledger",
        "context_evidence",
    }
)
EXCLUDED_CATEGORIES = frozenset({"product_source", "test_source", "git", "external"})
IO_CATEGORIES = GOVERNANCE_CATEGORIES | EXCLUDED_CATEGORIES


def _safe_logical_ref(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("logical_ref must be a non-empty string")
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("logical_ref must be one safe relative reference")
    return path.as_posix()


def classify_logical_ref(logical_ref: str) -> str:
    """按 CR-065 冻结口径对一个逻辑引用分类。"""

    ref = _safe_logical_ref(logical_ref)
    name = Path(ref).name
    if ref == ".git" or ref.startswith(".git/"):
        return "git"
    if ref.startswith("tests/"):
        return "test_source"
    if ref.startswith("meta_flow/") or ref in {"pyproject.toml", "uv.lock"}:
        return "product_source"
    if ref == ".meta-flow/workspace.yaml" or ref.startswith("policies/"):
        return "binding_policy"
    if name.endswith("LEDGER.ndjson"):
        return "ledger"
    if (
        ref.startswith("context/")
        or ref.startswith("evidence/")
        or "/context/" in ref
        or "/evidence/" in ref
        or "CAPSULE" in name.upper()
        or "RECEIPT" in name.upper()
    ):
        return "context_evidence"
    if (
        name in {"STATE.current.json", "CURRENT.json", "WORKFLOW-HEALTH.json"}
        or ref.startswith("current/")
        or ref.startswith("state/")
        or ref.startswith("changes/summaries/")
    ):
        return "state_projection"
    if (
        ref.startswith("changes/")
        or ref.startswith("docs/design/")
        or ref.startswith("stories/")
        or name in {"HLD.md", "DEVELOPMENT-PLAN.yaml", "route-plan.json"}
        or name.endswith("-LLD.md")
    ):
        return "cr_design"
    if (
        name in {"PROJECT.yaml", "ROADMAP.yaml", "PHASE.yaml", "WORK.yaml", "REQUEST.md", "HANDOFF.yaml"}
        or ref.startswith("works/")
        or ref.startswith("phases/")
    ):
        return "project_work"
    return "external"


@dataclass
class _MutableMetric:
    action: str
    category: str
    logical_ref: str
    read_count: int = 0
    physical_reads: int = 0
    bytes: int = 0
    cache_hits: int = 0
    write_attempts: int = 0
    actual_mutations: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "category": self.category,
            "logical_ref": self.logical_ref,
            "read_count": self.read_count,
            "physical_reads": self.physical_reads,
            "bytes": self.bytes,
            "cache_hits": self.cache_hits,
            "write_attempts": self.write_attempts,
            "actual_mutations": self.actual_mutations,
        }


class IOMetrics:
    """在内存中聚合一次 operation 的逻辑/物理 I/O。

    ``enabled=False`` 是正常运行默认值。关闭时所有 record 方法在读取参数前直接
    返回，因此不会引入治理读取、路径解析或事件写入。
    """

    def __init__(self, operation_id: str, *, enabled: bool = False) -> None:
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise ValueError("operation_id must be a non-empty string")
        self.operation_id = operation_id.strip()
        self.enabled = enabled
        self._metrics: dict[tuple[str, str, str], _MutableMetric] = {}
        self._check_groups = 0

    def _metric(self, action: str, category: str, logical_ref: str) -> _MutableMetric:
        if category not in IO_CATEGORIES:
            raise ValueError(f"unsupported I/O category: {category}")
        ref = _safe_logical_ref(logical_ref)
        key = (action, category, ref)
        metric = self._metrics.get(key)
        if metric is None:
            metric = _MutableMetric(action, category, ref)
            self._metrics[key] = metric
        return metric

    def record_read(
        self,
        logical_ref: str,
        *,
        byte_count: int,
        category: str | None = None,
        cache_hit: bool = False,
    ) -> None:
        if not self.enabled:
            return
        if type(byte_count) is not int or byte_count < 0:
            raise ValueError("byte_count must be a non-negative integer")
        selected = category or classify_logical_ref(logical_ref)
        metric = self._metric("read", selected, logical_ref)
        metric.read_count += 1
        if cache_hit:
            metric.cache_hits += 1
        else:
            metric.physical_reads += 1
            metric.bytes += byte_count

    def record_write_attempt(
        self,
        logical_ref: str,
        *,
        byte_count: int = 0,
        category: str | None = None,
        actual_mutation: bool = False,
    ) -> None:
        if not self.enabled:
            return
        if type(byte_count) is not int or byte_count < 0:
            raise ValueError("byte_count must be a non-negative integer")
        selected = category or classify_logical_ref(logical_ref)
        metric = self._metric("write", selected, logical_ref)
        metric.write_attempts += 1
        if actual_mutation:
            metric.actual_mutations += 1
            metric.bytes += byte_count

    def record_check_group(self, count: int = 1) -> None:
        if not self.enabled:
            return
        if type(count) is not int or count < 0:
            raise ValueError("check group count must be a non-negative integer")
        self._check_groups += count

    def summary(self) -> dict[str, Any]:
        entries = [
            metric.as_dict()
            for _, metric in sorted(self._metrics.items(), key=lambda item: item[0])
        ]
        totals = self._totals(entries)
        governance_entries = [
            entry for entry in entries if entry["category"] in GOVERNANCE_CATEGORIES
        ]
        return {
            "schema_version": 1,
            "operation_id": self.operation_id,
            "measurement": "enabled" if self.enabled else "disabled",
            "persistence_writes": 0,
            "totals": {**totals, "check_groups": self._check_groups},
            "governance_totals": self._totals(governance_entries),
            "entries": entries,
        }

    @staticmethod
    def _totals(entries: list[dict[str, Any]]) -> dict[str, int]:
        keys = (
            "read_count",
            "physical_reads",
            "bytes",
            "cache_hits",
            "write_attempts",
            "actual_mutations",
        )
        return {key: sum(int(entry[key]) for entry in entries) for key in keys}
