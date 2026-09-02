"""ConsumerAcceptanceResultV1 冻结 schema 加载与本地校验（七步合同第 1 步，IF-1..5）。

加载经 process route 解析逻辑引用；256 KiB 前置；draft-07 全量校验；
journey 复合唯一键 (journey,round,case) 与双层覆盖矩阵由导入器强制
（schema contains 已约束，此处复核——DQ-FD-076-04 / DAI-04）。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:  # O-01：jsonschema=正式 runtime dependency；缺损环境 typed 失败（CAC-N18）
    from jsonschema import Draft7Validator
except ImportError as _exc:  # pragma: no cover - 安装缺损防御负路径
    Draft7Validator = None
    _IMPORT_ERROR = str(_exc)

from meta_flow.project.model import is_safe_ref
from meta_flow.project.process_route import require_process_route, resolve_process_ref

RESULT_MAX_BYTES = 256 * 1024
SCHEMA_DIR_REF = "process/docs/design/CR-076/schemas"
CONSUMER_RESULT_SCHEMA_NAME = "consumer-acceptance-result-v1"
BUNDLE_IDENTITY_SCHEMA_NAME = "release-bundle-identity-v1"
_DESIGN_SCHEMA_NAMES = frozenset({CONSUMER_RESULT_SCHEMA_NAME, BUNDLE_IDENTITY_SCHEMA_NAME})

# 覆盖矩阵权威口径 = schema journeys.$comment（W3-W10 × 六轮 × J1/J2/J3）
JOURNEY_ENUM = ("W3", "W4", "W5", "W6", "W7", "W8", "W9", "W10")
CASE_ENUM = ("J1", "J2", "J3")
ROUND_RANGE = range(1, 7)

SCHEMA_LOAD_FAILED = "SCHEMA-LOAD-FAILED"
SCHEMA_VALIDATOR_UNAVAILABLE = "SCHEMA-VALIDATOR-UNAVAILABLE"
SCHEMA_INVALID = "SCHEMA-INVALID"
RESULT_OVERSIZE = "RESULT-OVERSIZE"
RESULT_UNREADABLE = "RESULT-UNREADABLE"
NATURAL_LANGUAGE_UNSUPPORTED = "NATURAL-LANGUAGE-UNSUPPORTED"
JOURNEY_DUPLICATE_KEY = "JOURNEY-DUPLICATE-KEY"
COVERAGE_INSUFFICIENT = "COVERAGE-INSUFFICIENT"
VARIANT_CROSS_MISMATCH = "VARIANT-CROSS-MISMATCH"


class ConsumerAcceptanceBlocked(Exception):
    """typed reason code 阻断（DESIGN 闭合词表；零 traceback）。"""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class LoadedDesignSchema:
    """route 解析后的冻结 schema（guard / close_plan 复用 bundle 入口）。"""

    name: str
    path: Path
    document: Mapping[str, Any]
    digest: str
    validator: Any


@dataclass(frozen=True, slots=True)
class SchemaFindings:
    """IF-3 输出：ok=False 时 code 为唯一 typed reason。"""

    ok: bool
    code: str
    errors: tuple[str, ...]


# (path, mtime) 单例缓存（DESIGN 性能：guard 复用时不重复加载）
_SCHEMA_CACHE: dict[tuple[str, float], LoadedDesignSchema] = {}


def load_design_schema(project_root: Path, name: str) -> LoadedDesignSchema:
    """IF-1：加载 CP3 冻结 schema（route 解析 + check_schema + digest 固定）。"""
    if Draft7Validator is None:
        raise ConsumerAcceptanceBlocked(SCHEMA_VALIDATOR_UNAVAILABLE, _IMPORT_ERROR)
    if name not in _DESIGN_SCHEMA_NAMES:
        raise ConsumerAcceptanceBlocked(SCHEMA_LOAD_FAILED, f"unknown design schema name: {name!r}")
    logical_ref = f"{SCHEMA_DIR_REF}/{name}.schema.json"
    if not is_safe_ref(logical_ref):
        raise ConsumerAcceptanceBlocked(SCHEMA_LOAD_FAILED, "schema ref is not safe")
    root = Path(project_root).resolve()
    try:
        route = require_process_route(root)
        path = resolve_process_ref(root, logical_ref)
        path.relative_to(route.process_root)
    except Exception as exc:  # route BLOCKED / 解析失败统一 typed
        raise ConsumerAcceptanceBlocked(SCHEMA_LOAD_FAILED, f"route resolve failed: {exc}") from exc
    if not path.is_file():
        raise ConsumerAcceptanceBlocked(SCHEMA_LOAD_FAILED, f"schema file missing: {logical_ref}")
    key = (str(path), path.stat().st_mtime)
    cached = _SCHEMA_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        document = json.loads(path.read_bytes().decode("utf-8"))
        Draft7Validator.check_schema(document)
    except Exception as exc:
        raise ConsumerAcceptanceBlocked(SCHEMA_LOAD_FAILED, f"schema unparsable/invalid: {exc}") from exc
    loaded = LoadedDesignSchema(
        name=name,
        path=path,
        document=document,
        digest=hashlib.sha256(path.read_bytes()).hexdigest(),
        validator=Draft7Validator(document),
    )
    _SCHEMA_CACHE[key] = loaded
    return loaded


def load_bundle_identity_schema(project_root: Path) -> LoadedDesignSchema:
    """bundle identity schema 通用加载入口（close guard / close_plan 复用，IF-1）。"""
    return load_design_schema(project_root, BUNDLE_IDENTITY_SCHEMA_NAME)


def ensure_result_within_size(raw: bytes) -> None:
    """IF-2：256 KiB 前置（超限整单拒绝，mutation=0）。"""
    if len(raw) > RESULT_MAX_BYTES:
        raise ConsumerAcceptanceBlocked(RESULT_OVERSIZE, f"{len(raw)} bytes > {RESULT_MAX_BYTES}")


def parse_result_document(raw: bytes) -> dict[str, Any]:
    """第 1 步 JSON 解析：非 canonical 渠道（自由文本/命令输出）无导入入口。"""
    text = raw.decode("utf-8", errors="replace")
    stripped = text.lstrip()
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        if stripped[:1] in ("{", "["):
            raise ConsumerAcceptanceBlocked(RESULT_UNREADABLE, f"json structure damaged: {exc}") from exc
        raise ConsumerAcceptanceBlocked(
            NATURAL_LANGUAGE_UNSUPPORTED, "document is not JSON (free text / yaml / pasted output)"
        ) from exc
    if not isinstance(document, dict):
        raise ConsumerAcceptanceBlocked(RESULT_UNREADABLE, "top level is not a JSON object")
    return document


def validate_consumer_result(payload: Mapping[str, Any], schema: LoadedDesignSchema) -> SchemaFindings:
    """IF-3：draft-07 全量校验 + 顶层 variant×artifact.variant 交叉复核（导入器侧）。"""
    errors = sorted(
        f"$.{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in schema.validator.iter_errors(payload)
    )
    if errors:
        return SchemaFindings(False, SCHEMA_INVALID, tuple(errors[:12]))
    artifact = payload.get("artifact")
    top_variant = payload.get("variant")
    artifact_variant = artifact.get("variant") if isinstance(artifact, Mapping) else None
    if top_variant != artifact_variant:
        return SchemaFindings(
            False,
            VARIANT_CROSS_MISMATCH,
            (f"variant={top_variant!r} != artifact.variant={artifact_variant!r}",),
        )
    return SchemaFindings(True, "", ())


def _journeys(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    execution = payload.get("execution")
    journeys = execution.get("journeys") if isinstance(execution, Mapping) else None
    return [row for row in journeys] if isinstance(journeys, list) else []


def check_journey_unique_keys(payload: Mapping[str, Any]) -> None:
    """IF-4：journey 复合唯一键 (journey,round,case) 导入器强制（DQ-FD-076-04）。"""
    keys = [(row.get("journey"), row.get("round"), row.get("case")) for row in _journeys(payload)]
    duplicated = sorted({key for key in keys if keys.count(key) > 1})
    if duplicated:
        raise ConsumerAcceptanceBlocked(JOURNEY_DUPLICATE_KEY, f"duplicated keys: {duplicated[:4]}")


def check_journey_coverage(payload: Mapping[str, Any]) -> None:
    """IF-5：双层覆盖矩阵复核（18 格 round×case + 24 格 journey×case，导入器侧）。"""
    rows = {(row.get("journey"), row.get("round"), row.get("case")) for row in _journeys(payload)}
    missing_round_case = sorted(
        f"round{round_}:{case}" for round_ in ROUND_RANGE for case in CASE_ENUM
        if not any(key[0] and key[1] == round_ and key[2] == case for key in rows)
    )
    missing_journey_case = sorted(
        f"{journey}:{case}" for journey in JOURNEY_ENUM for case in CASE_ENUM
        if not any(key[0] == journey and key[2] == case for key in rows)
    )
    missing = missing_round_case + missing_journey_case
    if missing:
        raise ConsumerAcceptanceBlocked(
            COVERAGE_INSUFFICIENT, f"missing {len(missing)} coverage cells: {missing[:6]}"
        )


__all__ = [
    "BUNDLE_IDENTITY_SCHEMA_NAME",
    "CASE_ENUM",
    "CONSUMER_RESULT_SCHEMA_NAME",
    "ConsumerAcceptanceBlocked",
    "JOURNEY_ENUM",
    "LoadedDesignSchema",
    "RESULT_MAX_BYTES",
    "ROUND_RANGE",
    "SchemaFindings",
    "check_journey_coverage",
    "check_journey_unique_keys",
    "ensure_result_within_size",
    "load_bundle_identity_schema",
    "load_design_schema",
    "parse_result_document",
    "validate_consumer_result",
]
