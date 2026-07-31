"""S04 的授权 checkpoint 事实构造与精确比较。

本模块只处理已经由 S02/S03 固化的 canonical facts；不读取文件、不消费
authorization，也不触发 executor。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from meta_flow.installation.contracts import ContractErrorCode, InstallationContractError

CHECKPOINTS = ("C1", "C2", "C3", "C4")
CHECKPOINT_SCALARS = (
    "version",
    "git_oid",
    "delivery_tree_digest",
    "plan_digest",
    "manifest_digest",
    "facts_digest",
)


@dataclass(frozen=True)
class CheckpointComparison:
    """一个 scalar 的 exact 比较结果，供审计和 fail-closed 分支消费。"""

    checkpoint: str
    scalar: str
    expected: object
    actual: object

    @property
    def matched(self) -> bool:
        return self.expected == self.actual


def validate_checkpoint_facts(payload: object, *, field: str = "checkpoint_facts") -> Mapping[str, Any]:
    """要求每个 checkpoint 恰有六个不可缺失的 canonical scalar。"""

    if not isinstance(payload, Mapping):
        raise InstallationContractError(ContractErrorCode.NONCANONICAL_VALUE, f"{field} must be a mapping")
    actual = set(payload)
    expected = set(CHECKPOINT_SCALARS)
    if unknown := sorted(str(key) for key in actual - expected):
        raise InstallationContractError(ContractErrorCode.UNKNOWN_KEY, f"{field} has unknown keys: {unknown}")
    if missing := sorted(expected - actual):
        raise InstallationContractError(ContractErrorCode.MISSING_KEY, f"{field} is missing keys: {missing}")
    return payload


def checkpoint_vector(
    expected: Mapping[str, object],
    observed: Mapping[str, object],
    *,
    checkpoints: tuple[str, ...] = CHECKPOINTS,
) -> tuple[CheckpointComparison, ...]:
    """按 C1-C4 和固定 scalar 顺序生成精确 24 项比较向量。"""

    expected_stages = _validate_stages(expected, field="expected_checkpoints", checkpoints=checkpoints)
    observed_stages = _validate_stages(observed, field="observed_checkpoints", checkpoints=checkpoints)
    return tuple(
        CheckpointComparison(checkpoint, scalar, expected_stages[checkpoint][scalar], observed_stages[checkpoint][scalar])
        for checkpoint in checkpoints
        for scalar in CHECKPOINT_SCALARS
    )


def compare_checkpoints(
    expected: Mapping[str, object],
    observed: Mapping[str, object],
    *,
    checkpoints: tuple[str, ...] = CHECKPOINTS,
) -> tuple[CheckpointComparison, ...]:
    """公开的 C1-C4 exact 比较 API。"""

    return checkpoint_vector(expected, observed, checkpoints=checkpoints)


def _validate_stages(
    payload: Mapping[str, object],
    *,
    field: str,
    checkpoints: tuple[str, ...],
) -> dict[str, Mapping[str, Any]]:
    if tuple(payload) != CHECKPOINTS:
        raise InstallationContractError(
            ContractErrorCode.NONCANONICAL_VALUE,
            f"{field} must contain checkpoints in exact order {list(CHECKPOINTS)}",
        )
    return {
        checkpoint: validate_checkpoint_facts(payload[checkpoint], field=f"{field}.{checkpoint}")
        for checkpoint in CHECKPOINTS
    }


__all__ = [
    "CHECKPOINTS",
    "CHECKPOINT_SCALARS",
    "CheckpointComparison",
    "checkpoint_vector",
    "compare_checkpoints",
    "validate_checkpoint_facts",
]
