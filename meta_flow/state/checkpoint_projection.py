"""Checkpoint ledger 的唯一 current-head 投影所有者。

该模块只解释 checkpoint result、successor 与 alias correction。业务 consumer 只能消费 :class:`CheckpointProjectionV1`，不得在
模块外重新实现 current-head 归并。
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meta_flow.project.onboarding_contract import canonical_digest
from meta_flow.project.process_route import ProcessRouteError, _resolve_runtime_ref
from meta_flow.project.read_contract import ReadContextProtocol, ReadContractError
from meta_flow.state.event_ledger import load_events
from meta_flow.state.failure_observation import GateHeadFactV1

PUBLIC_OPERATION_DECLARATIONS = (
    ("cp.projection", ("meta-flow", "cp", "projection")),
)
CHECKPOINT_LEDGER_REF = "process/state/CHECKPOINT-LEDGER.ndjson"
PROJECTION_OWNER = "meta_flow.state.checkpoint_projection:CanonicalCheckpointProjectionV1"
PROJECTION_VERSION = "CanonicalCheckpointProjectionV1"
CHECKPOINT_PATTERN = re.compile(r"^(?:C0|CP[0-8])$")
RESULT_EVENT_TYPES = frozenset({"checkpoint_result", "checkpoint_precheck_result"})
GRAPH_EVENT_TYPES = RESULT_EVENT_TYPES | frozenset(
    {
        "checkpoint_result_superseded",
        "checkpoint_result_alias_correction",
    }
)
REGISTERED_CONSUMERS = (
    "cp_result",
    "cr_tracking",
    "cr_lifecycle/status-sync",
    "state_transition",
    "publisher",
)
REGISTERED_WRITE_PRODUCERS = (
    "cp_result",
)
REGISTERED_THIN_ADAPTERS = ("route_plan",)


def load_checkpoint_identity(
    project_root: Path,
    result_ref: str,
    *,
    resolver: Callable[[Path, str], Path] = _resolve_runtime_ref,
) -> tuple[str, str, str]:
    """由 canonical owner 读取一个 producer ref 的 CR/checkpoint/subject 身份。"""

    result_path = resolver(project_root.resolve(), result_ref)
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"checkpoint result identity is unavailable: {result_ref}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"checkpoint result identity is invalid: {result_ref}")
    cr_id = _text(payload.get("cr_id"))
    checkpoint = _checkpoint(payload.get("checkpoint") or payload.get("checkpoint_id"))
    subject_id = _text(payload.get("story_id")) or cr_id
    if not cr_id or not CHECKPOINT_PATTERN.fullmatch(checkpoint):
        raise ValueError(f"checkpoint result identity is incomplete: {result_ref}")
    return cr_id, checkpoint, subject_id


def _text(value: object) -> str:
    return str(value or "").strip()


def _checkpoint(value: object) -> str:
    return _text(value).upper()


def _subject(event: Mapping[str, Any], *, fallback_cr_id: str) -> str:
    return _text(event.get("story_id")) or fallback_cr_id


def _clean_event(event: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in event.items() if key != "_line_no"}


@dataclass(frozen=True)
class CheckpointFindingV1:
    """稳定、可机读的投影 finding。"""

    code: str
    message: str
    cr_id: str = ""
    checkpoint: str = ""
    event_id: str = ""
    result_ref: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
            "cr_id": self.cr_id,
            "checkpoint": self.checkpoint,
            "event_id": self.event_id,
            "result_ref": self.result_ref,
        }


@dataclass(frozen=True)
class CheckpointHeadV1:
    """一个 CR/checkpoint/subject 的唯一 current head。"""

    cr_id: str
    checkpoint: str
    subject_id: str
    event_id: str
    result_ref: str
    decision: str
    result: Mapping[str, Any]
    revision: int
    selection_mode: str
    provenance_event_ids: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "cr_id": self.cr_id,
            "checkpoint": self.checkpoint,
            "subject_id": self.subject_id,
            "event_id": self.event_id,
            "result_ref": self.result_ref,
            "decision": self.decision,
            "revision": self.revision,
            "selection_mode": self.selection_mode,
            "provenance_event_ids": list(self.provenance_event_ids),
            "result_digest": canonical_digest(dict(self.result)),
        }


@dataclass(frozen=True)
class CheckpointProjectionV1:
    """Canonical checkpoint projection 的完整、不可变输出。"""

    target_cr_id: str
    target_checkpoint: str
    heads: tuple[CheckpointHeadV1, ...]
    findings: tuple[CheckpointFindingV1, ...]
    selected_event_count: int
    loaded_result_refs: tuple[str, ...]
    source_event_digest: str
    owner: str = PROJECTION_OWNER
    contract_version: str = PROJECTION_VERSION

    @property
    def decision(self) -> str:
        return "PASS" if not self.findings else "BLOCKED"

    def head(
        self,
        checkpoint: str,
        *,
        subject_id: str = "",
    ) -> CheckpointHeadV1 | None:
        """返回唯一 head；未传 subject 时默认使用 target CR 自身。"""

        normalized = _checkpoint(checkpoint)
        expected_subject = subject_id or self.target_cr_id
        matches = [
            head
            for head in self.heads
            if head.checkpoint == normalized and head.subject_id == expected_subject
        ]
        return matches[0] if len(matches) == 1 else None

    def as_dict(self, *, include_results: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": 1,
            "kind": "CheckpointProjectionV1",
            "contract_version": self.contract_version,
            "owner": self.owner,
            "decision": self.decision,
            "target_cr_id": self.target_cr_id,
            "target_checkpoint": self.target_checkpoint,
            "selected_event_count": self.selected_event_count,
            "loaded_result_refs": list(self.loaded_result_refs),
            "source_event_digest": self.source_event_digest,
            "heads": [head.as_dict() for head in self.heads],
            "findings": [finding.as_dict() for finding in self.findings],
        }
        if include_results:
            payload["results"] = [
                {
                    "result_ref": head.result_ref,
                    "payload": dict(head.result),
                }
                for head in self.heads
            ]
        payload["projection_digest"] = canonical_digest(payload)
        return payload


def project_gate_head_fact(
    projection: CheckpointProjectionV1,
    *,
    expected_gate: str,
    projected_gate: str,
    subject_id: str = "",
) -> GateHeadFactV1:
    """由唯一 checkpoint current-head 构造 gate 关联事实。"""

    normalized = _checkpoint(expected_gate)
    head = projection.head(normalized, subject_id=subject_id)
    return GateHeadFactV1(
        expected_gate=normalized,
        projected_gate=_checkpoint(projected_gate),
        result_ref=head.result_ref if head is not None else "",
        decision=head.decision if head is not None else "",
        current=not projection.findings and head is not None,
    )


def _finding(
    code: str,
    message: str,
    *,
    event: Mapping[str, Any] | None = None,
    cr_id: str = "",
    checkpoint: str = "",
    result_ref: str = "",
) -> CheckpointFindingV1:
    source = event or {}
    return CheckpointFindingV1(
        code=code,
        message=message,
        cr_id=cr_id or _text(source.get("cr_id")),
        checkpoint=checkpoint or _checkpoint(source.get("checkpoint")),
        event_id=_text(source.get("event_id")),
        result_ref=result_ref or _text(source.get("result_ref")),
    )


def _select_target_events(
    events: Sequence[Mapping[str, Any]],
    *,
    cr_id: str,
    checkpoint: str,
) -> tuple[list[dict[str, Any]], list[CheckpointFindingV1]]:
    """先按 CR/checkpoint 隔离，再吸收与目标事件直接相连的 legacy marker。"""

    findings: list[CheckpointFindingV1] = []
    selected = [
        _clean_event(event)
        for event in events
        if _text(event.get("cr_id")) == cr_id
        and (not checkpoint or _checkpoint(event.get("checkpoint")) == checkpoint)
        and _text(event.get("event_type")) in GRAPH_EVENT_TYPES
    ]
    target_event_ids = {_text(event.get("event_id")) for event in selected if event.get("event_id")}
    target_result_refs = {
        _text(event.get("result_ref")) for event in selected if event.get("result_ref")
    }

    # 历史 superseded marker 可能没有 cr_id。只能通过已经隔离出的 event/ref
    # 建立关系，禁止凭 checkpoint 名称把其他 CR 的 marker 拉入目标闭包。
    changed = True
    while changed:
        changed = False
        for raw in events:
            event = _clean_event(raw)
            if event in selected:
                continue
            if _text(event.get("event_type")) != "checkpoint_result_superseded":
                continue
            marker_checkpoint = _checkpoint(event.get("checkpoint"))
            if checkpoint and marker_checkpoint != checkpoint:
                continue
            if (
                _text(event.get("result_ref")) not in target_result_refs
                and _text(event.get("superseded_by")) not in target_event_ids
            ):
                continue
            selected.append(event)
            target_event_ids.add(_text(event.get("event_id")))
            target_result_refs.add(_text(event.get("result_ref")))
            changed = True

    for event in selected:
        event_checkpoint = _checkpoint(event.get("checkpoint"))
        if not CHECKPOINT_PATTERN.fullmatch(event_checkpoint):
            findings.append(
                _finding(
                    "CHECKPOINT_ID_INVALID",
                    "checkpoint 必须是 C0 或 CP0..CP8",
                    event=event,
                    cr_id=cr_id,
                )
            )
    return selected, findings


def _event_identity(
    event: Mapping[str, Any],
    *,
    fallback_cr_id: str,
) -> tuple[str, str, str]:
    cr_id = _text(event.get("cr_id")) or fallback_cr_id
    return (
        cr_id,
        _checkpoint(event.get("checkpoint")),
        _subject(
            event,
            fallback_cr_id=cr_id,
        ),
    )


def _detect_edge_findings(
    edges: Mapping[str, str],
    *,
    code_prefix: str,
    events_by_id: Mapping[str, Mapping[str, Any]],
) -> list[CheckpointFindingV1]:
    findings: list[CheckpointFindingV1] = []
    for start in sorted(edges):
        seen: set[str] = set()
        cursor = start
        while cursor in edges:
            if cursor in seen:
                findings.append(
                    _finding(
                        f"{code_prefix}_CYCLE",
                        f"successor graph 存在 cycle: {cursor}",
                        event=events_by_id.get(cursor),
                    )
                )
                break
            seen.add(cursor)
            cursor = edges[cursor]
    return findings


def _event_graph(
    events: Sequence[dict[str, Any]],
    *,
    cr_id: str,
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, str],
    dict[str, str],
    set[str],
    list[CheckpointFindingV1],
]:
    """归并 event supersession 与 alias correction，不读取 result 文件。"""

    findings: list[CheckpointFindingV1] = []
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        event_id = _text(event.get("event_id"))
        if event_id:
            grouped[event_id].append(event)
    duplicate_ids = {event_id for event_id, rows in grouped.items() if len(rows) > 1}
    for event_id in sorted(duplicate_ids):
        findings.append(
            _finding(
                "DUPLICATE_EVENT_ID",
                f"event_id 在目标投影中不唯一: {event_id}",
                event=grouped[event_id][0],
            )
        )
    events_by_id = {event_id: rows[0] for event_id, rows in grouped.items() if len(rows) == 1}
    result_events = {
        event_id: event
        for event_id, event in events_by_id.items()
        if _text(event.get("event_type")) in RESULT_EVENT_TYPES
    }

    event_edges: dict[str, str] = {}

    def add_event_edge(
        source_id: str,
        target_id: str,
        *,
        event: Mapping[str, Any],
    ) -> None:
        if not source_id or source_id not in result_events or target_id not in result_events:
            findings.append(
                _finding(
                    "EVENT_SUPERSESSION_TARGET_MISSING",
                    "event supersession 的 source/target 必须唯一存在于目标 CR",
                    event=event,
                )
            )
            return
        if _event_identity(
            result_events[source_id],
            fallback_cr_id=cr_id,
        ) != _event_identity(result_events[target_id], fallback_cr_id=cr_id):
            findings.append(
                _finding(
                    "EVENT_SUPERSESSION_IDENTITY_MISMATCH",
                    "event supersession 不得跨 CR/checkpoint/subject",
                    event=event,
                )
            )
            return
        existing = event_edges.get(source_id)
        if existing is not None and existing != target_id:
            findings.append(
                _finding(
                    "EVENT_SUPERSESSION_FORK",
                    f"event successor fork: {source_id}",
                    event=event,
                )
            )
            return
        event_edges[source_id] = target_id

    for event_id, event in sorted(result_events.items()):
        source_id = _text(event.get("supersedes_event_id"))
        if source_id:
            add_event_edge(source_id, event_id, event=event)

    for marker in events:
        if _text(marker.get("event_type")) != "checkpoint_result_superseded":
            continue
        candidates = [
            event_id
            for event_id, event in result_events.items()
            if _text(event.get("result_ref")) == _text(marker.get("result_ref"))
            and _checkpoint(event.get("checkpoint")) == _checkpoint(marker.get("checkpoint"))
            and _text(event.get("decision")).upper() == _text(marker.get("decision")).upper()
            and event_id != _text(marker.get("superseded_by"))
        ]
        if len(candidates) != 1:
            findings.append(
                _finding(
                    "EVENT_SUPERSESSION_SOURCE_NOT_UNIQUE",
                    "legacy superseded marker 未匹配唯一 source event",
                    event=marker,
                )
            )
            continue
        add_event_edge(
            candidates[0],
            _text(marker.get("superseded_by")),
            event=marker,
        )

    findings.extend(
        _detect_edge_findings(
            event_edges,
            code_prefix="EVENT_SUPERSESSION",
            events_by_id=events_by_id,
        )
    )

    alias_edges: dict[str, str] = {}
    corrected_event_ids: set[str] = set()
    for correction in events:
        if _text(correction.get("event_type")) != ("checkpoint_result_alias_correction"):
            continue
        alias_ref = _text(correction.get("result_ref"))
        canonical_ref = _text(correction.get("canonical_result_ref"))
        corrects_event_id = _text(correction.get("corrects_event_id"))
        corrected = result_events.get(corrects_event_id)
        correction_identity = _event_identity(correction, fallback_cr_id=cr_id)
        if not alias_ref or not canonical_ref or alias_ref == canonical_ref or corrected is None:
            findings.append(
                _finding(
                    "ALIAS_CORRECTION_FIELDS_INVALID",
                    "alias correction 缺少有效 alias/canonical/corrected-event 绑定",
                    event=correction,
                )
            )
            continue
        compatibility_alias = _text(correction.get("alias_result_ref"))
        if compatibility_alias and compatibility_alias != alias_ref:
            findings.append(
                _finding(
                    "ALIAS_CORRECTION_COMPATIBILITY_MISMATCH",
                    "alias_result_ref 与 result_ref 不一致",
                    event=correction,
                )
            )
            continue
        if (
            _text(corrected.get("result_ref")) != alias_ref
            or _event_identity(corrected, fallback_cr_id=cr_id) != correction_identity
        ):
            findings.append(
                _finding(
                    "ALIAS_CORRECTION_IDENTITY_MISMATCH",
                    "alias correction 与被纠正 event 的身份不一致",
                    event=correction,
                )
            )
            continue
        if alias_ref in alias_edges:
            findings.append(
                _finding(
                    "ALIAS_CORRECTION_FORK",
                    f"alias ref 存在多个 canonical target: {alias_ref}",
                    event=correction,
                )
            )
            continue
        if corrects_event_id in corrected_event_ids:
            findings.append(
                _finding(
                    "ALIAS_CORRECTION_EVENT_DUPLICATE",
                    f"同一 checkpoint event 被重复纠正: {corrects_event_id}",
                    event=correction,
                )
            )
            continue
        alias_edges[alias_ref] = canonical_ref
        corrected_event_ids.add(corrects_event_id)

    for start in sorted(alias_edges):
        seen: set[str] = set()
        cursor = start
        while cursor in alias_edges:
            if cursor in seen:
                findings.append(
                    _finding(
                        "ALIAS_CORRECTION_CYCLE",
                        f"alias correction graph 存在 cycle: {cursor}",
                        result_ref=start,
                        cr_id=cr_id,
                    )
                )
                break
            seen.add(cursor)
            cursor = alias_edges[cursor]

    return (
        result_events,
        event_edges,
        alias_edges,
        corrected_event_ids,
        findings,
    )


def _resolve_alias(ref: str, alias_edges: Mapping[str, str]) -> str:
    cursor = ref
    seen: set[str] = set()
    while cursor in alias_edges and cursor not in seen:
        seen.add(cursor)
        cursor = alias_edges[cursor]
    return cursor


def required_result_refs(
    events: Sequence[Mapping[str, Any]],
    *,
    cr_id: str,
    checkpoint: str = "",
) -> tuple[tuple[str, ...], tuple[CheckpointFindingV1, ...]]:
    """返回 target isolation 与 event graph reduction 后才允许读取的 refs。"""

    normalized_checkpoint = _checkpoint(checkpoint)
    selected, findings = _select_target_events(
        events,
        cr_id=cr_id,
        checkpoint=normalized_checkpoint,
    )
    (
        result_events,
        event_edges,
        alias_edges,
        corrected_event_ids,
        graph_findings,
    ) = _event_graph(selected, cr_id=cr_id)
    findings.extend(graph_findings)
    superseded_ids = set(event_edges)
    refs = {
        _resolve_alias(_text(event.get("result_ref")), alias_edges)
        for event_id, event in result_events.items()
        if event_id not in corrected_event_ids
        and event_id not in superseded_ids
        and _text(event.get("result_ref"))
    }
    # 没有 event-level edge 的 legacy result successor 仍需在目标闭包内读取，
    # 但 alias source 与已明确 superseded 的历史 ref 永远不会被重新读取。
    for event_id, event in result_events.items():
        if event_id in corrected_event_ids or event_id in superseded_ids:
            continue
        ref = _resolve_alias(_text(event.get("result_ref")), alias_edges)
        if ref:
            refs.add(ref)
    return tuple(sorted(refs)), tuple(findings)


def project_checkpoint_events(
    events: Sequence[Mapping[str, Any]],
    results: Mapping[str, Mapping[str, Any]],
    *,
    cr_id: str,
    checkpoint: str = "",
    load_findings: Sequence[CheckpointFindingV1] = (),
) -> CheckpointProjectionV1:
    """对已经加载的目标结果执行唯一 canonical graph reduction。"""

    normalized_checkpoint = _checkpoint(checkpoint)
    selected, findings = _select_target_events(
        events,
        cr_id=cr_id,
        checkpoint=normalized_checkpoint,
    )
    findings.extend(load_findings)
    (
        result_events,
        event_edges,
        alias_edges,
        corrected_event_ids,
        graph_findings,
    ) = _event_graph(selected, cr_id=cr_id)
    findings.extend(graph_findings)

    result_event_by_ref: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for event_id, event in result_events.items():
        result_event_by_ref[_text(event.get("result_ref"))].append((event_id, event))
    selected_result_refs = {
        _resolve_alias(result_ref, alias_edges) for result_ref in result_event_by_ref if result_ref
    }

    result_edges: dict[str, str] = {}
    result_revisions: dict[str, int] = {}
    valid_results: dict[str, dict[str, Any]] = {}
    for raw_ref, raw_result in sorted(results.items()):
        result_ref = _resolve_alias(_text(raw_ref), alias_edges)
        if result_ref not in selected_result_refs:
            continue
        result = dict(raw_result)
        if raw_ref in alias_edges:
            continue
        event_rows = result_event_by_ref.get(result_ref, [])
        event = event_rows[-1][1] if event_rows else {}
        result_cr_id = _text(result.get("cr_id")) or _text(event.get("cr_id"))
        result_checkpoint = _checkpoint(
            result.get("checkpoint") or result.get("checkpoint_id")
        ) or _checkpoint(event.get("checkpoint"))
        subject_id = _text(result.get("story_id")) or _subject(
            event,
            fallback_cr_id=result_cr_id or cr_id,
        )
        expected_identity = (
            _text(event.get("cr_id")) or cr_id,
            _checkpoint(event.get("checkpoint")),
            _subject(event, fallback_cr_id=_text(event.get("cr_id")) or cr_id),
        )
        actual_identity = (result_cr_id, result_checkpoint, subject_id)
        if event and actual_identity != expected_identity:
            findings.append(
                _finding(
                    "RESULT_EVENT_IDENTITY_MISMATCH",
                    "result 与 ledger event 的 CR/checkpoint/subject 身份不一致",
                    event=event,
                    result_ref=result_ref,
                )
            )
            continue
        if result_cr_id != cr_id or (
            normalized_checkpoint and result_checkpoint != normalized_checkpoint
        ):
            findings.append(
                _finding(
                    "RESULT_TARGET_IDENTITY_MISMATCH",
                    "加载的 result 不属于目标 CR/checkpoint",
                    event=event,
                    cr_id=result_cr_id,
                    checkpoint=result_checkpoint,
                    result_ref=result_ref,
                )
            )
            continue
        revision_value = result.get("revision")
        revision = revision_value if isinstance(revision_value, int) else 1
        if revision < 1:
            findings.append(
                _finding(
                    "RESULT_REVISION_INVALID",
                    "result revision 必须为正整数",
                    event=event,
                    result_ref=result_ref,
                )
            )
            continue
        valid_results[result_ref] = result
        result_revisions[result_ref] = revision
        parent_ref = _resolve_alias(_text(result.get("supersedes_ref")), alias_edges)
        if parent_ref:
            existing = result_edges.get(parent_ref)
            if existing is not None and existing != result_ref:
                findings.append(
                    _finding(
                        "RESULT_SUCCESSOR_FORK",
                        f"result successor fork: {parent_ref}",
                        event=event,
                        result_ref=result_ref,
                    )
                )
                continue
            result_edges[parent_ref] = result_ref

    for parent_ref, child_ref in sorted(result_edges.items()):
        parent_revision = result_revisions.get(parent_ref, 1)
        child_revision = result_revisions.get(child_ref, 0)
        if child_revision <= parent_revision:
            findings.append(
                _finding(
                    "RESULT_REVISION_NOT_INCREASING",
                    f"successor revision 未递增: {parent_ref} -> {child_ref}",
                    cr_id=cr_id,
                    result_ref=child_ref,
                )
            )
    findings.extend(
        _detect_edge_findings(
            result_edges,
            code_prefix="RESULT_SUCCESSOR",
            events_by_id={},
        )
    )

    active_event_ids = set(result_events) - set(event_edges) - corrected_event_ids
    active_refs = {
        _resolve_alias(_text(result_events[event_id].get("result_ref")), alias_edges)
        for event_id in active_event_ids
        if _text(result_events[event_id].get("result_ref"))
    }
    active_refs -= set(result_edges)
    event_position = {
        _text(event.get("event_id")): position
        for position, event in enumerate(selected)
        if _text(event.get("event_id"))
    }
    active_positions_by_ref: dict[str, list[int]] = defaultdict(list)
    for event_id in active_event_ids:
        event = result_events[event_id]
        result_ref = _resolve_alias(_text(event.get("result_ref")), alias_edges)
        if result_ref and event_id in event_position:
            active_positions_by_ref[result_ref].append(event_position[event_id])

    groups: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for result_ref in sorted(active_refs):
        result = valid_results.get(result_ref)
        if result is None:
            # File loader 会为缺失 ref 提供 finding；pure API 也保持 fail closed。
            if not any(
                finding.code == "RESULT_FILE_MISSING" and finding.result_ref == result_ref
                for finding in findings
            ):
                findings.append(
                    _finding(
                        "RESULT_FILE_MISSING",
                        f"current candidate result 不存在: {result_ref}",
                        cr_id=cr_id,
                        checkpoint=normalized_checkpoint,
                        result_ref=result_ref,
                    )
                )
            continue
        result_cr_id = _text(result.get("cr_id")) or cr_id
        result_checkpoint = _checkpoint(result.get("checkpoint") or result.get("checkpoint_id"))
        subject_id = _text(result.get("story_id")) or result_cr_id
        groups[(result_cr_id, result_checkpoint, subject_id)].append(result_ref)

    heads: list[CheckpointHeadV1] = []
    for identity, refs in sorted(groups.items()):
        cr_identity, checkpoint_identity, subject_id = identity
        selection_mode = "explicit_graph"
        compatibility_provenance: set[str] = set()
        if len(refs) != 1:
            explicit_result_semantics = any(
                "revision" in valid_results[result_ref]
                or bool(_text(valid_results[result_ref].get("supersedes_ref")))
                for result_ref in refs
            )
            explicit_event_semantics = any(
                bool(_text(event.get("supersedes_event_id")))
                for result_ref in refs
                for _event_id, event in result_event_by_ref.get(result_ref, [])
            )
            positions = {
                result_ref: max(active_positions_by_ref.get(result_ref, [-1]))
                for result_ref in refs
            }
            if (
                not explicit_result_semantics
                and not explicit_event_semantics
                and all(position >= 0 for position in positions.values())
                and len(set(positions.values())) == len(positions)
            ):
                # 旧 schema 没有 revision/supersedes。对这种历史数据，append-only
                # ledger 的行序就是唯一冻结的替代顺序；兼容规则只存在于 owner 内，
                # 一旦 producer 声明任一显式图字段便立即失效，避免吞掉真实 fork。
                selected_ref = max(refs, key=positions.__getitem__)
                compatibility_provenance.update(
                    event_id
                    for result_ref in refs
                    for event_id, _event in result_event_by_ref.get(result_ref, [])
                    if event_id in active_event_ids
                )
                refs = [selected_ref]
                selection_mode = "legacy_ledger_order"
            else:
                findings.append(
                    _finding(
                        "CURRENT_HEAD_NOT_UNIQUE",
                        f"current head 不唯一: {', '.join(refs)}",
                        cr_id=cr_identity,
                        checkpoint=checkpoint_identity,
                    )
                )
                continue
        result_ref = refs[0]
        result = valid_results[result_ref]
        matching_events = [
            (event_id, event)
            for event_id, event in result_event_by_ref.get(result_ref, [])
            if event_id in active_event_ids
        ]
        event_id = matching_events[-1][0] if matching_events else _text(result.get("event_id"))
        decision = _text(result.get("decision")).upper()
        if not decision:
            findings.append(
                _finding(
                    "RESULT_DECISION_MISSING",
                    "current result 缺少 decision",
                    event=matching_events[-1][1] if matching_events else None,
                    cr_id=cr_identity,
                    checkpoint=checkpoint_identity,
                    result_ref=result_ref,
                )
            )
            continue
        provenance: set[str] = set(compatibility_provenance)
        if event_id:
            provenance.add(event_id)
        cursor = result_ref
        reverse_result_edges = {child: parent for parent, child in result_edges.items()}
        while cursor in reverse_result_edges:
            cursor = reverse_result_edges[cursor]
            provenance.update(
                event_key for event_key, _event in result_event_by_ref.get(cursor, [])
            )
        heads.append(
            CheckpointHeadV1(
                cr_id=cr_identity,
                checkpoint=checkpoint_identity,
                subject_id=subject_id,
                event_id=event_id,
                result_ref=result_ref,
                decision=decision,
                result=result,
                revision=result_revisions.get(result_ref, 1),
                selection_mode=selection_mode,
                provenance_event_ids=tuple(sorted(item for item in provenance if item)),
            )
        )

    unique_findings = {
        (
            finding.code,
            finding.message,
            finding.cr_id,
            finding.checkpoint,
            finding.event_id,
            finding.result_ref,
        ): finding
        for finding in findings
    }
    return CheckpointProjectionV1(
        target_cr_id=cr_id,
        target_checkpoint=normalized_checkpoint,
        heads=tuple(sorted(heads, key=lambda item: (item.checkpoint, item.subject_id))),
        findings=tuple(unique_findings[key] for key in sorted(unique_findings)),
        selected_event_count=len(selected),
        loaded_result_refs=tuple(sorted(results)),
        source_event_digest=canonical_digest(selected),
    )


def load_checkpoint_projection(
    project_root: Path,
    *,
    cr_id: str,
    checkpoint: str = "",
    candidate_refs: Sequence[str] = (),
    resolver: Callable[[Path, str], Path] = _resolve_runtime_ref,
    read_context: ReadContextProtocol | None = None,
) -> CheckpointProjectionV1:
    """通过 binding 读取 ledger，并只加载目标归并所需的 result refs。"""

    root = project_root.resolve()
    normalized_checkpoint = _checkpoint(checkpoint)
    ledger_path = resolver(root, CHECKPOINT_LEDGER_REF)
    if not ledger_path.is_file():
        # snapshot-only 与历史 fixture 可能尚无 checkpoint ledger。兼容读取也必须
        # 留在 canonical owner 内：只扫描绑定后的 checks 根，并按 payload 的
        # exact CR/checkpoint 隔离，不允许 consumer 自行 glob。
        checks_root = resolver(root, "process/checks")
        legacy_events: list[dict[str, Any]] = []
        legacy_results: dict[str, dict[str, Any]] = {}
        candidates: dict[str, Path] = {}
        for candidate_ref in candidate_refs:
            candidates[str(candidate_ref)] = resolver(
                root,
                str(candidate_ref),
            )
        if checks_root.is_dir():
            for result_path in sorted(checks_root.glob("*.json")):
                result_ref = "process/checks/" + result_path.relative_to(checks_root).as_posix()
                candidates.setdefault(result_ref, result_path)
        for result_ref, result_path in sorted(candidates.items()):
            if result_path.is_file():
                try:
                    payload = (
                        json.loads(result_path.read_text(encoding="utf-8"))
                        if read_context is None
                        else read_context.read_json(result_ref)
                    )
                except (OSError, json.JSONDecodeError, ReadContractError):
                    continue
                if not isinstance(payload, dict):
                    continue
                inferred_cr_id = cr_id if cr_id in result_path.name else ""
                payload_cr_id = _text(payload.get("cr_id")) or inferred_cr_id
                payload_checkpoint = _checkpoint(
                    payload.get("checkpoint") or payload.get("checkpoint_id")
                )
                if not payload_checkpoint:
                    checkpoint_match = re.search(
                        r"(?:^|[-.])(C0|CP[0-8])(?:[-.]|$)", result_path.name
                    )
                    payload_checkpoint = checkpoint_match.group(1) if checkpoint_match else ""
                if payload_cr_id != cr_id or (
                    normalized_checkpoint and payload_checkpoint != normalized_checkpoint
                ):
                    continue
                payload = dict(payload)
                payload.setdefault("cr_id", cr_id)
                payload.setdefault("checkpoint", payload_checkpoint)
                event_id = _text(payload.get("event_id")) or (
                    "LEGACY-CHECKPOINT-"
                    + canonical_digest(
                        {
                            "cr_id": cr_id,
                            "checkpoint": payload_checkpoint,
                            "result_ref": result_ref,
                        }
                    )[:24]
                )
                event: dict[str, Any] = {
                    "event_id": event_id,
                    "event_type": "checkpoint_result",
                    "cr_id": cr_id,
                    "checkpoint": payload_checkpoint,
                    "decision": _text(payload.get("decision")).upper(),
                    "result_ref": result_ref,
                }
                for field in (
                    "story_id",
                    "summary_ref",
                    "revision",
                    "supersedes_ref",
                    "supersedes_event_id",
                ):
                    value = payload.get(field)
                    if value not in (None, ""):
                        event[field] = value
                legacy_events.append(event)
                legacy_results[result_ref] = payload
        return project_checkpoint_events(
            legacy_events,
            legacy_results,
            cr_id=cr_id,
            checkpoint=normalized_checkpoint,
        )
    events, load_errors = load_events(
        ledger_path,
        read_context=read_context,
        logical_ref=CHECKPOINT_LEDGER_REF,
    )
    findings = [
        _finding(
            "CHECKPOINT_LEDGER_INVALID",
            error.replace(str(ledger_path), CHECKPOINT_LEDGER_REF),
            cr_id=cr_id,
            checkpoint=normalized_checkpoint,
        )
        for error in load_errors
    ]
    refs, graph_findings = required_result_refs(
        events,
        cr_id=cr_id,
        checkpoint=normalized_checkpoint,
    )
    findings.extend(graph_findings)
    results: dict[str, dict[str, Any]] = {}
    for result_ref in refs:
        try:
            result_path = resolver(root, result_ref)
        except ProcessRouteError as exc:
            findings.append(
                _finding(
                    "RESULT_REF_BLOCKED",
                    str(exc).replace(str(root), "<release-root>"),
                    cr_id=cr_id,
                    checkpoint=normalized_checkpoint,
                    result_ref=result_ref,
                )
            )
            continue
        if not result_path.is_file():
            findings.append(
                _finding(
                    "RESULT_FILE_MISSING",
                    f"current candidate result 不存在: {result_ref}",
                    cr_id=cr_id,
                    checkpoint=normalized_checkpoint,
                    result_ref=result_ref,
                )
            )
            continue
        try:
            payload = (
                json.loads(result_path.read_text(encoding="utf-8"))
                if read_context is None
                else read_context.read_json(result_ref)
            )
        except (OSError, json.JSONDecodeError, ReadContractError) as exc:
            findings.append(
                _finding(
                    "RESULT_FILE_INVALID",
                    f"result 无法读取或不是合法 JSON: {result_ref}: {exc}",
                    cr_id=cr_id,
                    checkpoint=normalized_checkpoint,
                    result_ref=result_ref,
                )
            )
            continue
        if not isinstance(payload, dict):
            findings.append(
                _finding(
                    "RESULT_FILE_INVALID",
                    f"result 必须是 JSON object: {result_ref}",
                    cr_id=cr_id,
                    checkpoint=normalized_checkpoint,
                    result_ref=result_ref,
                )
            )
            continue
        results[result_ref] = payload
    return project_checkpoint_events(
        events,
        results,
        cr_id=cr_id,
        checkpoint=normalized_checkpoint,
        load_findings=findings,
    )
