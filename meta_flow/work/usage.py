"""Work usage 事件、预算前置检查与可恢复原子追加。"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from meta_flow.work.budget import BudgetDecision, WorkUsage, evaluate_budget
from meta_flow.work.model import Work, load_work

USAGE_SCHEMA_VERSION = 1
_EVENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_STAGE_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
STAGE_ALIASES = {
    "clarification": "requirements",
    "requirement": "requirements",
    "requirement-confirmation": "requirements",
    "requirements-confirmation": "requirements",
    "solution-design": "design",
    "validation": "verification",
    "verify": "verification",
}


def normalize_stage(value: str) -> str:
    """把 route/历史阶段名映射到稳定的 usage budget bucket。"""

    normalized = value.strip().lower()
    return STAGE_ALIASES.get(normalized, normalized)


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
    human_interactions: int = 0
    design_revisions: int = 0
    qa_attempts: int = 0
    final_full_suites: int = 0

    def __post_init__(self) -> None:
        if not _EVENT_ID_RE.fullmatch(self.event_id):
            raise ValueError("usage event_id is invalid")
        if not _STAGE_RE.fullmatch(self.stage):
            raise ValueError("usage stage is invalid")
        self.as_usage()

    def as_usage(self) -> WorkUsage:
        governance_values = (
            self.human_interactions,
            self.design_revisions,
            self.qa_attempts,
            self.final_full_suites,
        )
        if any(type(value) is not int or value < 0 for value in governance_values):
            raise ValueError("usage governance counters must be non-negative integers")
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
            "human_interactions": self.human_interactions,
            "design_revisions": self.design_revisions,
            "qa_attempts": self.qa_attempts,
            "final_full_suites": self.final_full_suites,
        }


def canonicalize_usage_event(event: UsageEvent) -> UsageEvent:
    """返回适合 admission、比较和新写入的 canonical usage event。"""

    stage = normalize_stage(event.stage)
    return event if stage == event.stage else replace(event, stage=stage)


@dataclass(frozen=True)
class UsageLedger:
    work_id: str
    events: tuple[UsageEvent, ...]
    changed_path_inventory: dict[str, Any] | None = None
    cost_closure: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": USAGE_SCHEMA_VERSION,
            "work_id": self.work_id,
            "events": [event.as_dict() for event in self.events],
        }
        if self.changed_path_inventory is not None:
            payload["changed_path_inventory"] = self.changed_path_inventory
        if self.cost_closure is not None:
            payload["cost_closure"] = self.cost_closure
        return payload


@dataclass(frozen=True)
class UsageAppendResult:
    decision: str
    event_id: str
    appended: bool
    budget: BudgetDecision
    ledger_ref: str


@dataclass(frozen=True)
class ChangedPathInventory:
    collapsed_status_entry_count: int
    changed_leaf_paths: tuple[str, ...]
    tracked_modified_leaf_paths: tuple[str, ...]
    untracked_leaf_paths: tuple[str, ...]
    staged_leaf_paths: tuple[str, ...]
    unknown_leaf_paths: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": "git-status-porcelain-v1-z-uall",
            "collapsed_status_entry_count": self.collapsed_status_entry_count,
            "changed_leaf_path_count": len(self.changed_leaf_paths),
            "changed_leaf_paths": list(self.changed_leaf_paths),
            "tracked_modified_leaf_path_count": len(
                self.tracked_modified_leaf_paths
            ),
            "tracked_modified_leaf_paths": list(
                self.tracked_modified_leaf_paths
            ),
            "untracked_leaf_path_count": len(self.untracked_leaf_paths),
            "untracked_leaf_paths": list(self.untracked_leaf_paths),
            "staged_leaf_path_count": len(self.staged_leaf_paths),
            "staged_leaf_paths": list(self.staged_leaf_paths),
            "unknown_leaf_path_count": len(self.unknown_leaf_paths),
            "unknown_leaf_paths": list(self.unknown_leaf_paths),
            "machine_decision_path_field": "changed_leaf_paths",
            "collapsed_status_entries_ui_only": True,
        }


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
    required = {
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
    optional = {
        "human_interactions",
        "design_revisions",
        "qa_attempts",
        "final_full_suites",
    }
    for raw in raw_events:
        if (
            not isinstance(raw, dict)
            or not required <= set(raw)
            or set(raw) - required - optional
        ):
            raise ValueError("usage event contains missing or unknown fields")
        event = UsageEvent(**raw)
        if event.event_id in seen:
            raise ValueError(f"duplicate usage event_id: {event.event_id}")
        seen.add(event.event_id)
        events.append(event)
    changed_path_inventory = payload.get("changed_path_inventory")
    if changed_path_inventory is not None and not isinstance(
        changed_path_inventory, dict
    ):
        raise ValueError("changed_path_inventory must be an object")
    cost_closure = payload.get("cost_closure")
    if cost_closure is not None and not isinstance(cost_closure, dict):
        raise ValueError("cost_closure must be an object")
    return UsageLedger(
        work_id=work.work_id,
        events=tuple(events),
        changed_path_inventory=changed_path_inventory,
        cost_closure=cost_closure,
    )


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


def _append_usage_event_unlocked(
    process_root: Path,
    work_id: str,
    event: UsageEvent,
    *,
    expected_admission_digest: str,
) -> UsageAppendResult:
    event = canonicalize_usage_event(event)
    work = load_work(process_root, work_id)
    ledger = load_usage(process_root, work)
    from meta_flow.work.usage_admission import plan_usage_admission

    existing = next((item for item in ledger.events if item.event_id == event.event_id), None)
    if existing is not None and canonicalize_usage_event(existing) != event:
        raise ValueError(f"usage event_id conflict: {event.event_id}")
    if not expected_admission_digest:
        raise ValueError("usage append requires expected_admission_digest")
    if existing is not None:
        decision = evaluate_budget(work.budget, summarize_usage(ledger))
        duplicate_decision = (
            "NO_CHANGE"
            if decision.allowed
            else "NO_CHANGE_AND_BLOCKED"
        )
        return UsageAppendResult(
            duplicate_decision,
            event.event_id,
            False,
            decision,
            work.usage_ref,
        )
    admission = plan_usage_admission(process_root, work_id, event)
    if admission.plan_digest != expected_admission_digest:
        raise ValueError("usage admission plan drifted before append")
    append_first_block = any(
        reason == "USAGE_HARD_STOP_100_PERCENT"
        or reason.startswith("USAGE_GOVERNANCE_LIMIT_EXCEEDED:")
        for reason in admission.reason_codes
    )
    if not admission.allowed and not append_first_block:
        raise ValueError(
            "usage admission blocks append: "
            f"{admission.decision}:{','.join(admission.reason_codes)}"
        )

    current = summarize_usage(ledger)
    decision = evaluate_budget(work.budget, current, delta=event.as_usage())
    updated = UsageLedger(
        work_id=work.work_id,
        events=(*ledger.events, event),
        changed_path_inventory=ledger.changed_path_inventory,
        cost_closure=ledger.cost_closure,
    )
    path = usage_path(process_root, work)
    _authorize_usage_system_write(work.work_id, work.usage_ref, path)
    _write_ledger_atomic(path, updated)
    terminal = (
        "RECORDED"
        if admission.allowed and decision.allowed
        else "RECORDED_AND_BLOCKED"
    )
    return UsageAppendResult(terminal, event.event_id, True, decision, work.usage_ref)


def append_usage_event(
    process_root: Path,
    work_id: str,
    event: UsageEvent,
    *,
    expected_admission_digest: str,
) -> UsageAppendResult:
    """在 per-Work single-writer lock 内重算 admission 并原子追加。"""

    event = canonicalize_usage_event(event)
    work = load_work(process_root, work_id)
    path = usage_path(process_root, work)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(f".{path.name}.writer.lock")
    if lock.is_symlink():
        raise ValueError("usage writer lock must not be a symlink")
    try:
        with lock.open("x", encoding="utf-8") as stream:
            stream.write(event.event_id + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise ValueError("usage writer lock is already held") from exc
    try:
        return _append_usage_event_unlocked(
            process_root,
            work_id,
            event,
            expected_admission_digest=expected_admission_digest,
        )
    finally:
        if (
            lock.is_symlink()
            or not lock.is_file()
            or lock.read_text(encoding="utf-8").strip() != event.event_id
        ):
            raise ValueError("usage writer lock ownership changed")
        lock.unlink()


def stage_usage(ledger: UsageLedger) -> dict[str, dict[str, Any]]:
    stages: dict[str, list[UsageEvent]] = {}
    for event in ledger.events:
        stages.setdefault(normalize_stage(event.stage), []).append(event)
    return {
        stage: _combine(tuple(events)).as_dict()
        for stage, events in sorted(stages.items())
    }


def _run_git_z(repo_root: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        error = result.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"git {' '.join(args)} failed: {error}")
    return result.stdout


def _z_paths(payload: bytes) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                item.decode("utf-8", errors="surrogateescape")
                for item in payload.split(b"\0")
                if item
            }
        )
    )


def _porcelain_paths(payload: bytes) -> tuple[tuple[str, str], ...]:
    parts = [item for item in payload.split(b"\0") if item]
    entries: list[tuple[str, str]] = []
    offset = 0
    while offset < len(parts):
        raw = parts[offset]
        if len(raw) < 4:
            raise ValueError("git status porcelain entry is malformed")
        status = raw[:2].decode("ascii", errors="strict")
        path = raw[3:].decode("utf-8", errors="surrogateescape")
        entries.append((status, path))
        offset += 1
        if "R" in status or "C" in status:
            if offset >= len(parts):
                raise ValueError("git rename/copy status is missing its source path")
            source = parts[offset].decode("utf-8", errors="surrogateescape")
            entries.append((status, source))
            offset += 1
    return tuple(entries)


def collect_changed_path_inventory(
    repo_root: Path,
    *,
    allowed_leaf_paths: Iterable[str] | None = None,
) -> ChangedPathInventory:
    """采集两种 Git 状态计数；机器判定只使用 ``-uall`` 叶子集合。"""

    root = repo_root.resolve()
    collapsed = _porcelain_paths(
        _run_git_z(root, "status", "--porcelain=v1", "-z")
    )
    leaf_entries = _porcelain_paths(
        _run_git_z(root, "status", "--porcelain=v1", "-z", "-uall")
    )
    leaf_paths = tuple(sorted({path for _status, path in leaf_entries}))
    leaf_set = set(leaf_paths)
    tracked_modified = tuple(
        path
        for path in _z_paths(_run_git_z(root, "diff", "--name-only", "-z"))
        if path in leaf_set
    )
    untracked = tuple(
        path
        for path in _z_paths(
            _run_git_z(root, "ls-files", "--others", "--exclude-standard", "-z")
        )
        if path in leaf_set
    )
    staged = tuple(
        path
        for path in _z_paths(
            _run_git_z(root, "diff", "--cached", "--name-only", "-z")
        )
        if path in leaf_set
    )
    allowed = None if allowed_leaf_paths is None else set(allowed_leaf_paths)
    unknown = (
        ()
        if allowed is None
        else tuple(sorted(path for path in leaf_paths if path not in allowed))
    )
    return ChangedPathInventory(
        collapsed_status_entry_count=len(collapsed),
        changed_leaf_paths=leaf_paths,
        tracked_modified_leaf_paths=tracked_modified,
        untracked_leaf_paths=untracked,
        staged_leaf_paths=staged,
        unknown_leaf_paths=unknown,
    )


def _deduplicated_human_interactions(
    gate_events: Sequence[dict[str, Any]],
) -> int:
    identities: set[str] = set()
    for offset, event in enumerate(gate_events):
        if event.get("event_type") != "human_gate_approval":
            continue
        if str(event.get("decision") or "").lower() not in {"approve", "approved"}:
            continue
        interaction_id = str(event.get("interaction_id") or "")
        identities.add(
            f"interaction:{interaction_id}"
            if interaction_id
            else f"approval:{event.get('event_id') or offset}"
        )
    return len(identities)


def build_cost_closure(
    *,
    ledger: UsageLedger,
    required_stages: Sequence[str],
    gate_events: Sequence[dict[str, Any]],
    changed_path_inventory: ChangedPathInventory,
    current_token_proxy_limit: int = 960_000,
    current_interaction_limit: int = 6,
    baseline_interactions: int = 34,
    baseline_authorized_proxy_ceiling: int = 1_752_000,
) -> dict[str, Any]:
    usage = summarize_usage(ledger)
    expected_stages = tuple(dict.fromkeys(required_stages))
    observed_stages = {normalize_stage(event.stage) for event in ledger.events}
    missing_stages = [
        stage
        for stage in expected_stages
        if normalize_stage(stage) not in observed_stages
    ]
    stage_coverage = (
        1.0
        if not expected_stages
        else (len(expected_stages) - len(missing_stages)) / len(expected_stages)
    )
    interactions = _deduplicated_human_interactions(gate_events)
    interaction_reduction = (
        0.0
        if baseline_interactions <= 0
        else (baseline_interactions - interactions) / baseline_interactions
    )
    token_ok = (
        usage.tokens is not None
        and usage.token_measurement_status in {"measured", "proxy"}
        and usage.tokens <= current_token_proxy_limit
    )
    hard_checks = {
        "stage_usage_coverage_100_percent": stage_coverage == 1.0,
        "current_token_proxy_within_limit": token_ok,
        "deduplicated_user_interactions_within_limit": (
            interactions <= current_interaction_limit
        ),
        "unknown_leaf_paths_zero": not changed_path_inventory.unknown_leaf_paths,
    }
    decision = (
        "PASS_WITH_BASELINE_LIMITATION"
        if all(hard_checks.values())
        else "FAIL"
    )
    return {
        "schema_version": 1,
        "decision": decision,
        "blocks_cp6_cp8": decision == "FAIL",
        "hard_checks": hard_checks,
        "current_usage": usage.as_dict(),
        "stage_coverage": {
            "required_stages": list(expected_stages),
            "observed_stages": sorted(observed_stages),
            "missing_stages": missing_stages,
            "coverage_ratio": stage_coverage,
        },
        "human_interactions": {
            "counting_rule": "GATE-LEDGER human_gate_approval deduplicated by interaction_id; missing IDs count individually",
            "deduplicated_user_decisions": interactions,
            "limit": current_interaction_limit,
            "baseline_observed_user_confirmations": baseline_interactions,
            "reduction_ratio": interaction_reduction,
        },
        "changed_path_inventory": changed_path_inventory.as_dict(),
        "baseline": {
            "cr_id": "CR-057",
            "observed_user_confirmations": baseline_interactions,
            "token_actual": None,
            "token_actual_status": "unavailable",
            "token_actual_unavailable_reason": "historical USAGE.json is missing",
            "authorized_proxy_ceiling": baseline_authorized_proxy_ceiling,
            "actual_to_actual_token_reduction_claim": "not_available",
        },
        "limitation": (
            "CR-057 token actual is unavailable; the authorized proxy ceiling "
            "is not an actual usage baseline"
        ),
    }


def write_usage_evidence(
    process_root: Path,
    work_id: str,
    *,
    changed_path_inventory: ChangedPathInventory,
    cost_closure: dict[str, Any],
) -> Path:
    work = load_work(process_root, work_id)
    ledger = load_usage(process_root, work)
    updated = UsageLedger(
        work_id=ledger.work_id,
        events=ledger.events,
        changed_path_inventory=changed_path_inventory.as_dict(),
        cost_closure=cost_closure,
    )
    path = usage_path(process_root, work)
    _authorize_usage_system_write(work.work_id, work.usage_ref, path)
    _write_ledger_atomic(path, updated)
    return path


def _authorize_usage_system_write(work_id: str, logical_ref: str, path: Path) -> None:
    from meta_flow.work.scope import authorize_system_write, classify_system_artifact

    classified = classify_system_artifact(work_id, "work.usage.write", logical_ref)
    if classified.namespace is None:
        raise ValueError(classified.reason_code)
    admitted = authorize_system_write(
        classified.namespace,
        logical_ref,
        target_is_symlink=path.is_symlink(),
    )
    if not admitted.allowed:
        raise ValueError(admitted.reason_code)
