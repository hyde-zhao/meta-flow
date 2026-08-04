"""单 operation、显式注入、deny-default 的不可变读取上下文。"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from meta_flow.project.read_contract import (
    ReadContractError,
    RouteSnapshotProtocol,
    normalize_read_ref,
)
from meta_flow.work.io_metrics import IOMetrics

OPERATION_KINDS = frozenset({"query", "plan", "check", "apply"})
QUERY_PROFILES = frozenset({"default", "long-term-route"})
LOGICAL_ROOTS = frozenset({"process-repository", "release-repository"})


@dataclass(frozen=True)
class _BufferedTextSource:
    logical_ref: str
    content: str

    def read_text(self, *, encoding: str = "utf-8") -> str:
        if encoding.lower().replace("-", "") != "utf8":
            raise ValueError("buffered governance objects require UTF-8")
        return self.content

    def __str__(self) -> str:
        return self.logical_ref


def _digest(payload: object) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def route_fingerprint(route: RouteSnapshotProtocol) -> str:
    """冻结路由身份，不持久化绝对路径。"""

    return _digest(
        {
            "project_id": route.project_id,
            "layout_version": route.layout_version,
            "route_mode": route.route_mode,
            "source": route.source,
        }
    )


def _validate_pattern(pattern: str) -> str:
    prefix = pattern[:-3] if pattern.endswith("/**") else pattern
    return normalize_read_ref(prefix) + ("/**" if pattern.endswith("/**") else "")


def _matches(pattern: str, ref: str) -> bool:
    if pattern.endswith("/**"):
        prefix = pattern[:-3].rstrip("/")
        return ref == prefix or ref.startswith(prefix + "/")
    return ref == pattern


class OperationReadContext:
    """一次 query/plan/check/apply 内唯一的读取与缓存 owner。"""

    def __init__(
        self,
        process_root: Path,
        *,
        operation_id: str,
        operation_kind: str,
        allowed_reads: tuple[str, ...],
        query_profile: str = "default",
        max_objects: int = 5,
        declared_phase_refs: tuple[str, ...] = (),
        route_snapshot: str = "",
        scope_digest: str = "",
        profile_digest: str = "",
        authorization_digest: str = "",
        metrics: IOMetrics | None = None,
        logical_root: str = "process-repository",
    ) -> None:
        if not operation_id.strip():
            raise ValueError("operation_id must be non-empty")
        if operation_kind not in OPERATION_KINDS:
            raise ValueError("operation_kind must be query, plan, check, or apply")
        if query_profile not in QUERY_PROFILES:
            raise ValueError("query_profile is unsupported")
        if query_profile == "long-term-route" and operation_kind != "query":
            raise ValueError("long-term-route is only valid for query operations")
        if logical_root not in LOGICAL_ROOTS:
            raise ValueError("logical_root is unsupported")
        phases = tuple(normalize_read_ref(ref) for ref in declared_phase_refs)
        if len(phases) != len(set(phases)) or any(
            not ref.startswith("phases/") or not ref.endswith("/PHASE.yaml") for ref in phases
        ):
            raise ValueError("declared_phase_refs must be unique Phase refs")
        if query_profile == "long-term-route":
            if allowed_reads:
                raise ValueError(
                    "long-term-route derives its allowed refs from the route declaration"
                )
            patterns = ("PROJECT.yaml", "ROADMAP.yaml", *phases)
            limit = 2 + len(phases)
        else:
            if type(max_objects) is not int or max_objects < 1:
                raise ValueError("max_objects must be a positive integer")
            if operation_kind == "query" and max_objects > 5:
                raise ValueError("default query max_objects must be between 1 and 5")
            if not allowed_reads:
                raise ValueError("default read context requires an explicit read scope")
            patterns = tuple(_validate_pattern(pattern) for pattern in allowed_reads)
            limit = max_objects
        self.operation_id = operation_id.strip()
        self.operation_kind = operation_kind
        self.query_profile = query_profile
        self.logical_root = logical_root
        self.max_objects = limit
        self._root = process_root.resolve(strict=False)
        self._allowed_reads = patterns
        self._route_fingerprint = route_snapshot
        self._scope_digest = scope_digest
        self._profile_digest = profile_digest
        self._authorization_digest = authorization_digest
        self._metrics = metrics or IOMetrics(self.operation_id)
        self._bytes: dict[str, bytes] = {}
        self._parsed: dict[tuple[str, str], Any] = {}
        self._refs: list[str] = []
        self._state = "OPEN"
        self._stale_reason = ""
        self._blocked_ref = ""

    @classmethod
    def from_route(
        cls,
        route: RouteSnapshotProtocol,
        **kwargs: Any,
    ) -> OperationReadContext:
        return cls(
            route.process_root,
            route_snapshot=route_fingerprint(route),
            **kwargs,
        )

    @property
    def objects_read(self) -> int:
        return len(self._refs)

    @property
    def refs(self) -> tuple[str, ...]:
        return tuple(self._refs)

    @property
    def repository_root(self) -> Path:
        """返回本 operation 已冻结的仓库根，仅用于显式依赖注入。"""

        return self._root

    @property
    def blocked_ref(self) -> str:
        return self._blocked_ref

    @property
    def state(self) -> str:
        return self._state

    def _error(self, code: str, message: str, ref: str = "") -> ReadContractError:
        self._blocked_ref = ref
        return ReadContractError(
            code,
            message,
            logical_ref=ref,
            objects_read=self.objects_read,
            refs=self.refs,
        )

    def _require_open(self, ref: str = "") -> None:
        if self._state != "OPEN":
            code = "READ_CONTEXT_STALE" if self._state == "STALE" else "READ_CONTEXT_CLOSED"
            detail = self._stale_reason or self._state.lower()
            raise self._error(code, f"read context is not open: {detail}", ref)

    def _scoped_ref(self, logical_ref: str) -> str:
        ref = normalize_read_ref(logical_ref)
        self._require_open(ref)
        if not any(_matches(pattern, ref) for pattern in self._allowed_reads):
            raise self._error(
                "READ_SCOPE_DENIED",
                "logical ref is outside the operation read scope; target bytes=0",
                ref,
            )
        return ref

    def resolve_path(self, logical_ref: str, *, require_file: bool = False) -> Path:
        """在冻结路由内解析逻辑引用；路径映射本身不计为对象读取。"""

        ref = self._scoped_ref(logical_ref)
        path_parts = ref.split("/")
        if self.logical_root == "process-repository" and path_parts[0] == "process":
            path_parts = path_parts[1:]
        candidate = self._root.joinpath(*path_parts).resolve(strict=False)
        if not candidate.is_relative_to(self._root):
            raise self._error(
                "READ_REF_OUTSIDE_PROCESS_ROOT",
                "logical ref escapes the process repository; target bytes=0",
                ref,
            )
        if require_file and not candidate.is_file():
            raise self._error(
                "READ_OBJECT_MISSING",
                "logical ref does not identify a regular file; target bytes=0",
                ref,
            )
        return candidate

    def logical_ref_for(self, path: Path, *, qualified: bool = False) -> str:
        """把冻结仓库内路径转换为受当前 scope 约束的逻辑引用。"""

        self._require_open()
        candidate = path.resolve(strict=False)
        try:
            relative = candidate.relative_to(self._root)
        except ValueError as exc:
            raise self._error(
                "READ_REF_OUTSIDE_PROCESS_ROOT",
                "read path is outside the frozen repository root; target bytes=0",
            ) from exc
        ref = normalize_read_ref(relative.as_posix())
        if qualified and self.logical_root == "process-repository":
            ref = f"process/{ref}"
        return self._scoped_ref(ref)

    def _resolve(self, logical_ref: str) -> tuple[str, Path]:
        ref = self._scoped_ref(logical_ref)
        return ref, self.resolve_path(ref, require_file=True)

    def read_bytes(self, logical_ref: str, *, category: str | None = None) -> bytes:
        ref, path = self._resolve(logical_ref)
        cached = self._bytes.get(ref)
        if cached is not None:
            self._metrics.record_read(
                ref, byte_count=len(cached), category=category, cache_hit=True
            )
            return cached
        if self.objects_read >= self.max_objects:
            raise self._error(
                "QUERY_OBJECT_BUDGET_EXCEEDED",
                f"operation read budget is {self.max_objects} objects; target bytes=0",
                ref,
            )
        content = path.read_bytes()
        self._bytes[ref] = content
        self._refs.append(ref)
        self._metrics.record_read(ref, byte_count=len(content), category=category)
        return content

    def read_text(self, logical_ref: str, *, category: str | None = None) -> str:
        try:
            return self.read_bytes(logical_ref, category=category).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise self._error(
                "READ_ENCODING_INVALID",
                "governance object must be UTF-8",
                normalize_read_ref(logical_ref),
            ) from exc

    def read_json(self, logical_ref: str, *, category: str | None = None) -> Any:
        ref = normalize_read_ref(logical_ref)
        self._require_open(ref)
        key = (ref, "json")
        if key in self._parsed:
            cached = self._bytes[ref]
            self._metrics.record_read(
                ref,
                byte_count=len(cached),
                category=category,
                cache_hit=True,
            )
        else:
            try:
                self._parsed[key] = json.loads(self.read_text(ref, category=category))
            except json.JSONDecodeError as exc:
                raise self._error(
                    "READ_JSON_INVALID", "governance object is invalid JSON", ref
                ) from exc
        return deepcopy(self._parsed[key])

    def read_yaml_object(
        self,
        logical_ref: str,
        *,
        category: str | None = None,
        loader: Callable[[Path], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        ref = normalize_read_ref(logical_ref)
        self._require_open(ref)
        key = (ref, "yaml-object")
        if key in self._parsed:
            cached = self._bytes[ref]
            self._metrics.record_read(
                ref,
                byte_count=len(cached),
                category=category,
                cache_hit=True,
            )
        else:
            if loader is None:
                raise self._error(
                    "READ_YAML_LOADER_REQUIRED",
                    "YAML reads require one explicitly injected parser",
                    ref,
                )
            text = self.read_text(ref, category=category)
            source = _BufferedTextSource(ref, text)
            self._parsed[key] = loader(source)  # type: ignore[arg-type]
        return deepcopy(self._parsed[key])

    def byte_size(self, logical_ref: str) -> int:
        ref = normalize_read_ref(logical_ref)
        self._require_open(ref)
        if ref not in self._bytes:
            raise self._error("READ_OBJECT_NOT_RESERVED", "logical ref has not been read", ref)
        return len(self._bytes[ref])

    def assert_operation(self, expected_kind: str) -> None:
        self._require_open()
        if expected_kind != self.operation_kind:
            raise self._error(
                "OPERATION_CONTEXT_KIND_MISMATCH",
                f"{self.operation_kind} context cannot be reused for {expected_kind}",
            )

    def assert_snapshot(
        self,
        *,
        route_fingerprint: str | None = None,
        scope_digest: str | None = None,
        profile_digest: str | None = None,
        authorization_digest: str | None = None,
    ) -> None:
        self._require_open()
        expected = {
            "route": (self._route_fingerprint, route_fingerprint),
            "scope": (self._scope_digest, scope_digest),
            "profile": (self._profile_digest, profile_digest),
            "authorization": (self._authorization_digest, authorization_digest),
        }
        drift = [
            name
            for name, (frozen, current) in expected.items()
            if current is not None and frozen != current
        ]
        if drift:
            self.mark_stale("snapshot drift: " + ",".join(drift))
            raise self._error(
                "READ_CONTEXT_SNAPSHOT_DRIFT",
                "read context snapshot changed: " + ", ".join(drift),
            )

    def mark_stale(self, reason: str) -> None:
        if self._state == "OPEN":
            self._state = "STALE"
            self._stale_reason = reason or "mutation boundary crossed"

    def close_after_mutation(self, receipt: Mapping[str, Any]) -> None:
        if not isinstance(receipt, Mapping) or not receipt:
            raise ValueError("mutation close requires a non-empty receipt")
        self.mark_stale("mutation boundary crossed")

    def close(self) -> None:
        if self._state == "OPEN":
            self._state = "CLOSED"

    def metrics_summary(self) -> dict[str, Any]:
        return self._metrics.summary()

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "OperationReadContextV1",
            "operation_id": self.operation_id,
            "operation_kind": self.operation_kind,
            "query_profile": self.query_profile,
            "logical_root": self.logical_root,
            "state": self._state,
            "max_objects": self.max_objects,
            "objects_read": self.objects_read,
            "refs": list(self.refs),
            "blocked_ref": self._blocked_ref or None,
            "route_fingerprint": self._route_fingerprint or None,
            "scope_digest": self._scope_digest or None,
            "profile_digest": self._profile_digest or None,
            "authorization_digest": self._authorization_digest or None,
        }

    def __enter__(self) -> OperationReadContext:
        self._require_open()
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()


__all__ = ["OperationReadContext", "route_fingerprint"]
