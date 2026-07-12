"""Truthful per-dispatch token telemetry; estimates never become measurements."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


MEASUREMENT_STATUSES = {"measured", "unavailable", "estimated"}


@dataclass(frozen=True)
class TokenUsage:
    measurement_status: str
    source: str
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    total_tokens: int | None = None
    model: str | None = None
    usage_record_id: str | None = None


def validate_usage(usage: TokenUsage) -> list[str]:
    errors: list[str] = []
    if usage.measurement_status not in MEASUREMENT_STATUSES:
        errors.append("invalid measurement_status")
        return errors
    values = (usage.input_tokens, usage.cached_input_tokens, usage.output_tokens, usage.reasoning_tokens, usage.total_tokens)
    if any(value is not None and value < 0 for value in values):
        errors.append("token usage values must be non-negative")
    if usage.measurement_status == "measured":
        if usage.source != "platform-reported":
            errors.append("measured usage requires source=platform-reported")
        if usage.total_tokens is None:
            errors.append("measured usage requires total_tokens")
    elif any(value is not None for value in values):
        errors.append("unavailable/estimated usage must not populate measured token fields")
    return errors


def aggregate_usage(usages: Iterable[TokenUsage]) -> dict[str, object]:
    rows = list(usages)
    errors = [error for usage in rows for error in validate_usage(usage)]
    measured = [usage for usage in rows if usage.measurement_status == "measured" and usage.total_tokens is not None]
    return {
        "measurement_status_counts": {status: sum(usage.measurement_status == status for usage in rows) for status in sorted(MEASUREMENT_STATUSES)},
        "measured_total_tokens": sum(int(usage.total_tokens or 0) for usage in measured),
        "measured_dispatches": len(measured),
        "errors": errors,
    }


def usage_from_event(event: dict[str, Any]) -> TokenUsage | None:
    """Read an optional platform usage receipt without inventing a value."""

    raw = event.get("usage")
    if not isinstance(raw, dict):
        return None
    return TokenUsage(
        measurement_status=str(raw.get("measurement_status") or "unavailable"),
        source=str(raw.get("source") or "platform-unavailable"),
        input_tokens=raw.get("input_tokens"),
        cached_input_tokens=raw.get("cached_input_tokens"),
        output_tokens=raw.get("output_tokens"),
        reasoning_tokens=raw.get("reasoning_tokens"),
        total_tokens=raw.get("total_tokens"),
        model=raw.get("model"),
        usage_record_id=raw.get("usage_record_id"),
    )
