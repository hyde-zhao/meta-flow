"""Work 全周期读取、写入、检查组与 token 硬预算。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

TOKEN_MEASUREMENT_STATUSES = {"measured", "proxy", "unavailable"}


@dataclass(frozen=True)
class BudgetLimit:
    reads: int
    writes: int
    check_groups: int
    tokens: int

    def __post_init__(self) -> None:
        values = (self.reads, self.writes, self.check_groups, self.tokens)
        if not all(type(value) is int for value in values) or min(values) < 0:
            raise ValueError("budget limits must be non-negative")

    def as_dict(self) -> dict[str, int]:
        return {
            "reads": self.reads,
            "writes": self.writes,
            "check_groups": self.check_groups,
            "tokens": self.tokens,
        }


G0_BUDGET = BudgetLimit(reads=8, writes=8, check_groups=3, tokens=32_000)
G1_BUDGET = BudgetLimit(reads=20, writes=24, check_groups=8, tokens=96_000)


@dataclass(frozen=True)
class WorkUsage:
    reads: int = 0
    writes: int = 0
    check_groups: int = 0
    tokens: int | None = 0
    token_measurement_status: str = "measured"
    proxy_method: str = ""
    unavailable_reason: str = ""

    def __post_init__(self) -> None:
        if min(self.reads, self.writes, self.check_groups) < 0:
            raise ValueError("usage counters must be non-negative")
        if self.token_measurement_status not in TOKEN_MEASUREMENT_STATUSES:
            raise ValueError("token measurement status must be measured, proxy, or unavailable")
        if self.token_measurement_status == "unavailable":
            if self.tokens is not None:
                raise ValueError("unavailable token usage must use tokens=None")
            if not self.unavailable_reason:
                raise ValueError("unavailable token usage requires unavailable_reason")
        else:
            if self.tokens is None or self.tokens < 0:
                raise ValueError("measured/proxy token usage requires non-negative tokens")
        if self.token_measurement_status == "proxy" and not self.proxy_method:
            raise ValueError("proxy token usage requires proxy_method")
        if self.token_measurement_status != "proxy" and self.proxy_method:
            raise ValueError("proxy_method is only valid for proxy token usage")

    def as_dict(self) -> dict[str, Any]:
        return {
            "reads": self.reads,
            "writes": self.writes,
            "check_groups": self.check_groups,
            "tokens": self.tokens,
            "token_measurement_status": self.token_measurement_status,
            "proxy_method": self.proxy_method,
            "unavailable_reason": self.unavailable_reason,
        }


@dataclass(frozen=True)
class BudgetDecision:
    decision: str
    projected: WorkUsage
    exceeded_dimensions: tuple[str, ...]
    remaining: dict[str, int | None]
    reason: str

    @property
    def allowed(self) -> bool:
        return self.decision in {"OK", "WARNING"}


def _project_usage(current: WorkUsage, delta: WorkUsage) -> WorkUsage:
    if current.token_measurement_status == "unavailable" or delta.token_measurement_status == "unavailable":
        return WorkUsage(
            reads=current.reads + delta.reads,
            writes=current.writes + delta.writes,
            check_groups=current.check_groups + delta.check_groups,
            tokens=None,
            token_measurement_status="unavailable",
            unavailable_reason=current.unavailable_reason or delta.unavailable_reason,
        )
    status = "proxy" if "proxy" in {current.token_measurement_status, delta.token_measurement_status} else "measured"
    proxy_methods = [
        method
        for method in (current.proxy_method, delta.proxy_method)
        if method
    ]
    return WorkUsage(
        reads=current.reads + delta.reads,
        writes=current.writes + delta.writes,
        check_groups=current.check_groups + delta.check_groups,
        tokens=int(current.tokens or 0) + int(delta.tokens or 0),
        token_measurement_status=status,
        proxy_method=" + ".join(dict.fromkeys(proxy_methods)) if status == "proxy" else "",
    )


def evaluate_budget(
    limit: BudgetLimit,
    current: WorkUsage,
    *,
    delta: WorkUsage | None = None,
) -> BudgetDecision:
    projected = _project_usage(current, delta or WorkUsage())
    if projected.token_measurement_status == "unavailable":
        return BudgetDecision(
            decision="TELEMETRY_UNAVAILABLE",
            projected=projected,
            exceeded_dimensions=("tokens",),
            remaining={
                "reads": limit.reads - projected.reads,
                "writes": limit.writes - projected.writes,
                "check_groups": limit.check_groups - projected.check_groups,
                "tokens": None,
            },
            reason="token usage is unavailable; provide an approved proxy or pause/reclassify",
        )
    actual = {
        "reads": projected.reads,
        "writes": projected.writes,
        "check_groups": projected.check_groups,
        "tokens": int(projected.tokens or 0),
    }
    maximum = limit.as_dict()
    # 硬预算是可消费的包含上界：最后一个合法单位可以把 remaining 降到 0；
    # 只有 projected usage 真正超过上界时才 fail closed。
    exceeded = tuple(key for key, value in actual.items() if value > maximum[key])
    remaining: dict[str, int | None] = {
        key: maximum[key] - value for key, value in actual.items()
    }
    if exceeded:
        return BudgetDecision(
            decision="EXCEEDED",
            projected=projected,
            exceeded_dimensions=exceeded,
            remaining=remaining,
            reason="projected usage exceeds one or more hard limits before the operation",
        )
    warning = tuple(
        key for key, value in actual.items()
        if maximum[key] and value / maximum[key] >= 0.80
    )
    if warning:
        return BudgetDecision(
            decision="WARNING",
            projected=projected,
            exceeded_dimensions=(),
            remaining=remaining,
            reason="projected usage reaches the 80 percent warning threshold",
        )
    return BudgetDecision(
        decision="OK",
        projected=projected,
        exceeded_dimensions=(),
        remaining=remaining,
        reason="projected usage is within budget",
    )
