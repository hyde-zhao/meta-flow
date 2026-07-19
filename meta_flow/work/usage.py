"""Work usage 事件、预算前置检查与可恢复原子追加。"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meta_flow.work.budget import BudgetDecision, WorkUsage, evaluate_budget
from meta_flow.work.model import Work, load_work

USAGE_SCHEMA_VERSION = 1
_EVENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_STAGE_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")


@dataclass(frozen=True)
class UsageEvent:
    event_id: str
    stage: str
    reads: int = 0
    writes: int = 0
    check_groups: int = 0
    tokens: int | None = 0
    token_measurement_status: str = "measured"
    proxy_method: str = ""
    unavailable_reason: str = ""

    def __post_init__(self) -> None:
        if not _EVENT_ID_RE.fullmatch(self.event_id):
            raise ValueError("usage event_id is invalid")
        if not _STAGE_RE.fullmatch(self.stage):
            raise ValueError("usage stage is invalid")
        self.as_usage()

    def as_usage(self) -> WorkUsage:
        return WorkUsage(
            reads=self.reads,
            writes=self.writes,
            check_groups=self.check_groups,
            tokens=self.tokens,
            token_measurement_status=self.token_measurement_status,
            proxy_method=self.proxy_method,
            unavailable_reason=self.unavailable_reason,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "stage": self.stage,
            **self.as_usage().as_dict(),
        }


@dataclass(frozen=True)
class UsageLedger:
    work_id: str
    events: tuple[UsageEvent, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": USAGE_SCHEMA_VERSION,
            "work_id": self.work_id,
            "events": [event.as_dict() for event in self.events],
        }


@dataclass(frozen=True)
class UsageAppendResult:
    decision: str
    event_id: str
    appended: bool
    budget: BudgetDecision
    ledger_ref: str


def _combine(events: tuple[UsageEvent, ...]) -> WorkUsage:
    reads = sum(event.reads for event in events)
    writes = sum(event.writes for event in events)
    checks = sum(event.check_groups for event in events)
    unavailable = [event for event in events if event.token_measurement_status == "unavailable"]
    if unavailable:
        return WorkUsage(
            reads=reads,
            writes=writes,
            check_groups=checks,
            tokens=None,
            token_measurement_status="unavailable",
            unavailable_reason="; ".join(
                dict.fromkeys(event.unavailable_reason for event in unavailable)
            ),
        )
    proxy_methods = [
        event.proxy_method
        for event in events
        if event.token_measurement_status == "proxy"
    ]
    return WorkUsage(
        reads=reads,
        writes=writes,
        check_groups=checks,
        tokens=sum(int(event.tokens or 0) for event in events),
        token_measurement_status="proxy" if proxy_methods else "measured",
        proxy_method=" + ".join(dict.fromkeys(proxy_methods)),
    )


def summarize_usage(ledger: UsageLedger) -> WorkUsage:
    return _combine(ledger.events)


def usage_path(process_root: Path, work: Work) -> Path:
    return process_root.resolve() / work.usage_ref


def load_usage(process_root: Path, work: Work) -> UsageLedger:
    path = usage_path(process_root, work)
    if not path.is_file():
        return UsageLedger(work_id=work.work_id, events=())
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid usage JSON: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != USAGE_SCHEMA_VERSION:
        raise ValueError("usage ledger schema_version is invalid")
    if payload.get("work_id") != work.work_id:
        raise ValueError("usage ledger work_id mismatch")
    raw_events = payload.get("events")
    if not isinstance(raw_events, list):
        raise ValueError("usage ledger events must be a list")
    events: list[UsageEvent] = []
    seen: set[str] = set()
    allowed = {
        "event_id",
        "stage",
        "reads",
        "writes",
        "check_groups",
        "tokens",
        "token_measurement_status",
        "proxy_method",
        "unavailable_reason",
    }
    for raw in raw_events:
        if not isinstance(raw, dict) or set(raw) != allowed:
            raise ValueError("usage event contains missing or unknown fields")
        event = UsageEvent(**raw)
        if event.event_id in seen:
            raise ValueError(f"duplicate usage event_id: {event.event_id}")
        seen.add(event.event_id)
        events.append(event)
    return UsageLedger(work_id=work.work_id, events=tuple(events))


def _write_ledger_atomic(path: Path, ledger: UsageLedger) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    if temporary.exists() or temporary.is_symlink():
        raise FileExistsError(f"temporary usage path already exists: {temporary}")
    try:
        temporary.write_text(
            json.dumps(ledger.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()


def append_usage_event(
    process_root: Path,
    work_id: str,
    event: UsageEvent,
) -> UsageAppendResult:
    work = load_work(process_root, work_id)
    ledger = load_usage(process_root, work)
    existing = next((item for item in ledger.events if item.event_id == event.event_id), None)
    if existing is not None:
        if existing != event:
            raise ValueError(f"usage event_id conflict: {event.event_id}")
        decision = evaluate_budget(work.budget, summarize_usage(ledger))
        return UsageAppendResult("NO_CHANGE", event.event_id, False, decision, work.usage_ref)

    current = summarize_usage(ledger)
    decision = evaluate_budget(work.budget, current, delta=event.as_usage())
    if decision.decision == "EXCEEDED":
        return UsageAppendResult("BLOCKED", event.event_id, False, decision, work.usage_ref)
    updated = UsageLedger(work_id=work.work_id, events=(*ledger.events, event))
    _write_ledger_atomic(usage_path(process_root, work), updated)
    terminal = "RECORDED_AND_BLOCKED" if decision.decision == "TELEMETRY_UNAVAILABLE" else "RECORDED"
    return UsageAppendResult(terminal, event.event_id, True, decision, work.usage_ref)


def stage_usage(ledger: UsageLedger) -> dict[str, dict[str, Any]]:
    stages: dict[str, list[UsageEvent]] = {}
    for event in ledger.events:
        stages.setdefault(event.stage, []).append(event)
    return {
        stage: _combine(tuple(events)).as_dict()
        for stage, events in sorted(stages.items())
    }
