"""全文扩读预登记的 canonical 三值语义。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

FULL_LLD_REQUIRED_TRIGGER = "full_lld_required_by_policy"
LEGACY_PACKET_SCHEMA_VERSIONS = frozenset({1, 2})
STRICT_PACKET_SCHEMA_VERSIONS = frozenset({3, 4})


class ConsumerRequirement(StrEnum):
    """consumer 对候选输入的封闭需求枚举。"""

    REQUIRED = "required"
    OPTIONAL = "optional"
    FORBIDDEN = "forbidden"


CONSUMER_REQUIREMENTS = frozenset(item.value for item in ConsumerRequirement)


class PreregistrationSemanticsError(ValueError):
    """语义输入不属于 canonical 合同。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PreregistrationEntrySemantics:
    """单个 read_if_needed entry 的无 I/O 判定。"""

    requirement: ConsumerRequirement | None
    trigger: str
    select_required_ref: bool
    evaluate_target_io: bool
    legacy_compatibility: bool


def packet_uses_strict_semantics(schema_version: object) -> bool:
    """返回 packet 是否必须执行 canonical 三值语义。

    未标版本的历史 packet 与 v1/v2 只保留只读兼容；v3/v4 使用三值
    合同。任何其他显式版本都必须阻断，不能被未来 schema 静默降级为
    legacy 语义。
    """

    if schema_version is None:
        return False
    if type(schema_version) is not int:
        raise PreregistrationSemanticsError(
            "PACKET_SCHEMA_VERSION_INVALID",
            "packet schema_version must be an integer",
        )
    if schema_version in LEGACY_PACKET_SCHEMA_VERSIONS:
        return False
    if schema_version in STRICT_PACKET_SCHEMA_VERSIONS:
        return True
    raise PreregistrationSemanticsError(
        "PACKET_SCHEMA_VERSION_UNSUPPORTED",
        "packet schema_version is not supported by preregistration semantics",
    )


def parse_consumer_requirement(value: object) -> ConsumerRequirement:
    """解析封闭枚举；未知值不得降级为 NOT_REQUIRED。"""

    try:
        return ConsumerRequirement(value)
    except (TypeError, ValueError) as exc:
        raise PreregistrationSemanticsError(
            "CONSUMER_REQUIREMENT_INVALID",
            "read_if_needed consumer_requirement must be required, optional or forbidden",
        ) from exc


def requirement_evaluates_target_io(
    requirement: ConsumerRequirement,
) -> bool:
    """只有 required 可以进入 resolve→exists→read。"""

    return requirement is ConsumerRequirement.REQUIRED


def interpret_preregistration_entry(
    entry: Mapping[str, Any],
    *,
    strict: bool,
) -> PreregistrationEntrySemantics:
    """解释 entry，但不解析路径、不探测目标且不执行 I/O。"""

    trigger_value = entry.get("trigger")
    trigger = trigger_value if isinstance(trigger_value, str) else ""
    if not strict:
        return PreregistrationEntrySemantics(
            requirement=None,
            trigger=trigger,
            select_required_ref=trigger == FULL_LLD_REQUIRED_TRIGGER,
            evaluate_target_io=trigger == FULL_LLD_REQUIRED_TRIGGER,
            legacy_compatibility=True,
        )

    requirement = parse_consumer_requirement(entry.get("consumer_requirement"))
    if (
        requirement is ConsumerRequirement.REQUIRED
        and trigger != FULL_LLD_REQUIRED_TRIGGER
    ):
        raise PreregistrationSemanticsError(
            "REQUIRED_PREREGISTRATION_TRIGGER_INVALID",
            "required read_if_needed entry must use full_lld_required_by_policy",
        )
    evaluates_io = requirement_evaluates_target_io(requirement)
    return PreregistrationEntrySemantics(
        requirement=requirement,
        trigger=trigger,
        select_required_ref=(
            evaluates_io and trigger == FULL_LLD_REQUIRED_TRIGGER
        ),
        evaluate_target_io=evaluates_io,
        legacy_compatibility=False,
    )


def semantic_contract_payload() -> dict[str, Any]:
    """供 semantic receipt 编译器消费的稳定合同。"""

    return {
        "schema_version": 1,
        "kind": "PreregistrationSemanticsContractV1",
        "consumer_requirements": sorted(CONSUMER_REQUIREMENTS),
        "full_lld_required_trigger": FULL_LLD_REQUIRED_TRIGGER,
        "legacy_packet_schema_versions": sorted(LEGACY_PACKET_SCHEMA_VERSIONS),
        "strict_packet_schema_versions": sorted(STRICT_PACKET_SCHEMA_VERSIONS),
        "rules": {
            "required_selects_ref": True,
            "required_evaluates_target_io": True,
            "optional_evaluates_target_io": False,
            "forbidden_evaluates_target_io": False,
            "unknown_requirement": "fail-closed-before-target-io",
            "legacy_v1_v2": "trigger-compatible-without-tristate-claim",
        },
    }


__all__ = [
    "CONSUMER_REQUIREMENTS",
    "ConsumerRequirement",
    "FULL_LLD_REQUIRED_TRIGGER",
    "LEGACY_PACKET_SCHEMA_VERSIONS",
    "PreregistrationEntrySemantics",
    "PreregistrationSemanticsError",
    "STRICT_PACKET_SCHEMA_VERSIONS",
    "interpret_preregistration_entry",
    "packet_uses_strict_semantics",
    "parse_consumer_requirement",
    "requirement_evaluates_target_io",
    "semantic_contract_payload",
]
