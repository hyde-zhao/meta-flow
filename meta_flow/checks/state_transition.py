"""Validate post-approval and automatic-CP workflow transitions."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from meta_flow.checks.frozen_cp6_evidence import (
    FrozenCp6EvidenceError,
    FrozenCp6EvidenceV1,
    project_story_admission,
)
from meta_flow.project.onboarding_contract import canonical_digest
from meta_flow.project.process_route import _resolve_runtime_ref
from meta_flow.state import event_ledger
from meta_flow.state.checkpoint_projection import CheckpointProjectionV1

PASS_LIKE_DECISIONS = {"PASS", "WAIVED", "PASS_WITH_RISK"}
FAILURE_DECISIONS = {"FAIL", "BLOCKED", "NEEDS_REWORK", "NEEDS_DESIGN_CLARIFICATION"}
ALLOWED_STOP_REASONS = {
    "required_human_gate",
    "blocked",
    "needs_rework",
    "needs_design_clarification",
    "authorization_required",
    "workflow_health_threshold",
    "delivered",
    "no_remaining_route",
}
AWAIT_USER_ACTION_TYPES = {"await_user", "human_gate", "required_human_gate"}
FAILURE_STOP_REASONS = {
    "FAIL": {"blocked"},
    "BLOCKED": {"blocked", "authorization_required", "workflow_health_threshold"},
    "NEEDS_REWORK": {"needs_rework"},
    "NEEDS_DESIGN_CLARIFICATION": {"needs_design_clarification"},
}
PASS_COMPATIBLE_INTERRUPT_REASONS = {"authorization_required", "workflow_health_threshold"}
STALE_FAILURE_STOP_REASONS = {"blocked", "needs_rework", "needs_design_clarification"}
C0_SCHEMA_VERSION = 1
C0_CONSUMER_PROJECTOR_REF = "meta_flow.checks.state_transition.project_c0_consumer"
C0_RESULT_FIELDS = frozenset(
    {
        "schema_version",
        "kind",
        "cr_id",
        "checkpoint",
        "dry_run",
        "release_oid",
        "process_oid",
        "scope_digest",
        "input_evidence_refs",
        "frozen_evidence",
        "replay_results",
        "consumer_inventory",
        "bootstrap_consumer_count",
        "legacy_projector_consumer_count",
        "planned_transitions",
        "mutation_allowlist",
        "blockers",
        "decision",
        "mutation_count",
        "plan_digest",
        "checker_provenance",
    }
)


@dataclass(frozen=True)
class ChronologyNode:
    """A typed, timezone-aware timestamp from canonical workflow evidence."""

    kind: str
    occurred_at: str | datetime | None
    source_ref: str


@dataclass(frozen=True)
class ChronologyFinding:
    """Stable, machine-consumable chronology validation output."""

    code: str
    object_ref: str
    field: str
    message: str
    source_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class C0ResultV1:
    """C0 bootstrap cutover 的严格、可摘要、零副作用结果。"""

    cr_id: str
    release_oid: str
    process_oid: str
    scope_digest: str
    input_evidence_refs: tuple[str, ...]
    frozen_evidence: tuple[Mapping[str, Any], ...]
    replay_results: tuple[Mapping[str, Any], ...]
    consumer_inventory: tuple[Mapping[str, Any], ...]
    bootstrap_consumer_count: int
    legacy_projector_consumer_count: int
    planned_transitions: tuple[Mapping[str, Any], ...]
    mutation_allowlist: tuple[str, ...]
    blockers: tuple[str, ...]
    decision: str
    checker_provenance: Mapping[str, Any]
    schema_version: int = C0_SCHEMA_VERSION
    kind: str = "C0ResultV1"
    checkpoint: str = "C0"
    dry_run: bool = True
    mutation_count: int = 0
    plan_digest: str = ""

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "cr_id": self.cr_id,
            "checkpoint": self.checkpoint,
            "dry_run": self.dry_run,
            "release_oid": self.release_oid,
            "process_oid": self.process_oid,
            "scope_digest": self.scope_digest,
            "input_evidence_refs": list(self.input_evidence_refs),
            "frozen_evidence": [dict(item) for item in self.frozen_evidence],
            "replay_results": [dict(item) for item in self.replay_results],
            "consumer_inventory": [dict(item) for item in self.consumer_inventory],
            "bootstrap_consumer_count": self.bootstrap_consumer_count,
            "legacy_projector_consumer_count": self.legacy_projector_consumer_count,
            "planned_transitions": [dict(item) for item in self.planned_transitions],
            "mutation_allowlist": list(self.mutation_allowlist),
            "blockers": list(self.blockers),
            "decision": self.decision,
            "mutation_count": self.mutation_count,
            "plan_digest": self.plan_digest,
            "checker_provenance": dict(self.checker_provenance),
        }

    def as_dict(self) -> dict[str, Any]:
        payload = self._payload()
        digest_payload = {key: value for key, value in payload.items() if key != "plan_digest"}
        expected_digest = canonical_digest(digest_payload)
        if self.plan_digest and self.plan_digest != expected_digest:
            raise ValueError("C0ResultV1 plan_digest does not match canonical payload")
        payload["plan_digest"] = expected_digest
        if set(payload) != C0_RESULT_FIELDS:
            raise ValueError("C0ResultV1 field set is not the frozen 21-key contract")
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> C0ResultV1:
        if set(payload) != C0_RESULT_FIELDS:
            raise ValueError("C0ResultV1 fields mismatch")
        if payload.get("schema_version") != C0_SCHEMA_VERSION:
            raise ValueError("C0ResultV1 schema_version mismatch")
        if payload.get("kind") != "C0ResultV1" or payload.get("checkpoint") != "C0":
            raise ValueError("C0ResultV1 identity mismatch")
        if payload.get("dry_run") is not True or payload.get("mutation_count") != 0:
            raise ValueError("C0ResultV1 must remain a zero-mutation dry-run")
        instance = cls(
            cr_id=str(payload["cr_id"]),
            release_oid=str(payload["release_oid"]),
            process_oid=str(payload["process_oid"]),
            scope_digest=str(payload["scope_digest"]),
            input_evidence_refs=tuple(str(item) for item in payload["input_evidence_refs"]),
            frozen_evidence=tuple(dict(item) for item in payload["frozen_evidence"]),
            replay_results=tuple(dict(item) for item in payload["replay_results"]),
            consumer_inventory=tuple(dict(item) for item in payload["consumer_inventory"]),
            bootstrap_consumer_count=int(payload["bootstrap_consumer_count"]),
            legacy_projector_consumer_count=int(payload["legacy_projector_consumer_count"]),
            planned_transitions=tuple(dict(item) for item in payload["planned_transitions"]),
            mutation_allowlist=tuple(str(item) for item in payload["mutation_allowlist"]),
            blockers=tuple(str(item) for item in payload["blockers"]),
            decision=str(payload["decision"]),
            checker_provenance=dict(payload["checker_provenance"]),
            plan_digest=str(payload["plan_digest"]),
        )
        instance.as_dict()
        return instance


def project_c0_consumer(
    *,
    consumer_id: str,
    operation: str,
    attempts: Sequence[Mapping[str, Any]],
    absolute_process_path: str,
) -> dict[str, Any]:
    """用一个 projector 归一化所有公共 consumer 的重放结论。"""

    finding_codes: set[str] = set()
    if not attempts:
        finding_codes.add("C0_CONSUMER_NOT_EXECUTED")
    absolute_path_count = 0
    for attempt in attempts:
        if int(attempt.get("returncode", 1)) != 0:
            finding_codes.add("C0_CONSUMER_COMMAND_FAILED")
        output = f"{attempt.get('stdout', '')}\n{attempt.get('stderr', '')}"
        if absolute_process_path:
            absolute_path_count += output.count(absolute_process_path)
    if absolute_path_count:
        finding_codes.add("ABSOLUTE_PROCESS_PATH_EXPOSED")
    return {
        "consumer_id": consumer_id,
        "operation": operation,
        "projector_ref": C0_CONSUMER_PROJECTOR_REF,
        "command_count": len(attempts),
        "status": "PASS" if not finding_codes else "BLOCKED",
        "finding_codes": sorted(finding_codes),
        "absolute_process_path_count": absolute_path_count,
    }


def build_c0_result(
    *,
    cr_id: str,
    release_oid: str,
    process_oid: str,
    scope_digest: str,
    input_evidence_refs: Sequence[str],
    frozen_evidence: Sequence[Mapping[str, Any]],
    consumer_inventory: Sequence[Mapping[str, Any]],
    planned_transitions: Sequence[Mapping[str, Any]],
    mutation_allowlist: Sequence[str],
    initial_blockers: Sequence[str] = (),
) -> C0ResultV1:
    """从冻结证据和公共 consumer 重放结果生成唯一 C0 结论。"""

    blockers = list(initial_blockers)
    if len(input_evidence_refs) != 9 or len(set(input_evidence_refs)) != 9:
        blockers.append("C0_INPUT_EVIDENCE_REFS_MUST_BE_EXACTLY_9")
    if len(frozen_evidence) != 3:
        blockers.append("C0_FROZEN_EVIDENCE_MUST_BE_EXACTLY_3")
    if len(consumer_inventory) != 11:
        blockers.append("C0_CONSUMER_INVENTORY_MUST_BE_EXACTLY_11")

    replay_results: list[dict[str, Any]] = []
    for raw in frozen_evidence:
        try:
            frozen = FrozenCp6EvidenceV1.from_dict(raw)
        except FrozenCp6EvidenceError as exc:
            blockers.append(f"C0_FROZEN_EVIDENCE_INVALID:{exc}")
            continue
        admission = project_story_admission(
            frozen,
            expected_dependency_digests=frozen.dependency_digests,
        )
        replay_decision = "PASS" if admission.get("decision") == "READY" else "BLOCKED"
        replay_results.append(
            {
                "story_id": frozen.story_id,
                "decision": replay_decision,
                "admission_decision": admission.get("decision"),
                "evidence_digest": frozen.evidence_digest,
                "finding_codes": []
                if replay_decision == "PASS"
                else list(admission.get("reason_codes") or []),
            }
        )
        if replay_decision != "PASS":
            blockers.append(f"C0_REPLAY_BLOCKED:{frozen.story_id}")
    if len(replay_results) != 3 or any(item["decision"] != "PASS" for item in replay_results):
        blockers.append("C0_REPLAY_MUST_PASS_3_OF_3")

    normalized_consumers = [dict(item) for item in consumer_inventory]
    projector_refs = {str(item.get("projector_ref") or "") for item in normalized_consumers}
    if projector_refs != {C0_CONSUMER_PROJECTOR_REF}:
        blockers.append("C0_CONSUMERS_MUST_SHARE_ONE_PROJECTOR")
    if any(str(item.get("status") or "") != "PASS" for item in normalized_consumers):
        blockers.append("C0_CONSUMER_REPLAY_BLOCKED")
    if sum(int(item.get("absolute_process_path_count") or 0) for item in normalized_consumers):
        blockers.append("C0_ABSOLUTE_PROCESS_PATH_COUNT_NONZERO")

    bootstrap_consumer_count = sum(
        1 for item in normalized_consumers if str(item.get("projection_mode") or "") == "bootstrap"
    )
    legacy_projector_consumer_count = sum(
        1
        for item in normalized_consumers
        if str(item.get("projector_ref") or "") not in {"", C0_CONSUMER_PROJECTOR_REF}
    )
    if bootstrap_consumer_count:
        blockers.append("C0_BOOTSTRAP_CONSUMER_COUNT_NONZERO")
    if legacy_projector_consumer_count:
        blockers.append("C0_LEGACY_PROJECTOR_CONSUMER_COUNT_NONZERO")

    deduplicated_blockers = tuple(sorted(set(blockers)))
    return C0ResultV1(
        cr_id=cr_id,
        release_oid=release_oid,
        process_oid=process_oid,
        scope_digest=scope_digest,
        input_evidence_refs=tuple(input_evidence_refs),
        frozen_evidence=tuple(dict(item) for item in frozen_evidence),
        replay_results=tuple(replay_results),
        consumer_inventory=tuple(normalized_consumers),
        bootstrap_consumer_count=bootstrap_consumer_count,
        legacy_projector_consumer_count=legacy_projector_consumer_count,
        planned_transitions=tuple(dict(item) for item in planned_transitions),
        mutation_allowlist=tuple(mutation_allowlist),
        blockers=deduplicated_blockers,
        decision="READY" if not deduplicated_blockers else "BLOCKED",
        checker_provenance={
            "checker_name": "meta-flow route c0-dry-run",
            "checker_version": "C0ResultV1",
            "consumer_projector_ref": C0_CONSUMER_PROJECTOR_REF,
            "consumer_count": len(normalized_consumers),
        },
    )


C0_STORY_PROGRESS_ORDER = (
    "draft",
    "lld-ready",
    "lld-in-progress",
    "lld-ready-for-review",
    "lld-batch-ready-for-review",
    "lld-approved",
    "dev-ready",
    "in-development",
    "ready-for-verification",
    "verified",
    "verified-with-risk",
    "done",
)
C0_STORY_PROGRESS_RANK = {status: index for index, status in enumerate(C0_STORY_PROGRESS_ORDER)}


def _c0_story_rank(story_id: str, status: str) -> int:
    try:
        return C0_STORY_PROGRESS_RANK[status]
    except KeyError as exc:
        raise ValueError(
            f"{story_id} C0 projection cannot consume non-progress status={status or '-'}"
        ) from exc


def _c0_recovery_floors(
    prior_transitions: Iterable[Mapping[str, Any]],
    *,
    expected: set[str],
) -> dict[str, str]:
    floors: dict[str, str] = {}
    for transition in prior_transitions:
        if not isinstance(transition, Mapping):
            raise ValueError("C0 prior story transition must be an object")
        story_id = str(transition.get("subject") or "")
        if story_id not in expected:
            continue
        before_status = str(transition.get("from") or "")
        after_status = str(transition.get("to") or "")
        before_rank = _c0_story_rank(story_id, before_status)
        after_rank = _c0_story_rank(story_id, after_status)
        if before_rank <= after_rank:
            continue
        current_floor = floors.get(story_id)
        if current_floor is None or before_rank > _c0_story_rank(
            story_id,
            current_floor,
        ):
            floors[story_id] = before_status
    return floors


def has_c0_regressive_story_transition(
    transitions: Iterable[Mapping[str, Any]],
    *,
    cr_id: str,
) -> bool:
    prefix = f"STORY-{cr_id.replace('-', '')}-S"
    expected = {f"{prefix}{index:02d}" for index in range(1, 6)}
    return bool(_c0_recovery_floors(transitions, expected=expected))


def project_c0_development_plan(
    payload: Mapping[str, Any],
    *,
    cr_id: str,
    prior_transitions: Iterable[Mapping[str, Any]] = (),
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    """把 C0 PASS 单调投影为可重复的 CR Story 状态。"""

    projected = copy.deepcopy(dict(payload))
    waves = projected.get("waves")
    if not isinstance(waves, list):
        raise ValueError("DEVELOPMENT-PLAN must contain waves[]")
    prefix = f"STORY-{cr_id.replace('-', '')}-S"
    expected = {f"{prefix}{index:02d}" for index in range(1, 6)}
    stories: dict[str, dict[str, Any]] = {}
    for wave in waves:
        if not isinstance(wave, dict):
            continue
        wave_stories = wave.get("stories")
        if not isinstance(wave_stories, list):
            continue
        for story in wave_stories:
            if not isinstance(story, dict):
                continue
            story_id = str(story.get("story_id") or "")
            if story_id not in expected:
                continue
            if story_id in stories:
                raise ValueError(f"duplicate C0 story in DEVELOPMENT-PLAN: {story_id}")
            stories[story_id] = story
    missing = sorted(expected - set(stories))
    if missing:
        raise ValueError("C0 stories missing from DEVELOPMENT-PLAN: " + ", ".join(missing))
    recovery_floors = _c0_recovery_floors(
        prior_transitions,
        expected=expected,
    )

    target_states = {
        f"{prefix}01": ("ready-for-verification", True, True),
        f"{prefix}02": ("ready-for-verification", True, True),
        f"{prefix}03": ("ready-for-verification", True, True),
        f"{prefix}04": ("dev-ready", True, True),
        f"{prefix}05": ("lld-approved", False, False),
    }
    transitions: list[dict[str, Any]] = []
    for story_id in sorted(expected):
        story = stories[story_id]
        before_status = str(story.get("status") or "")
        minimum_status, minimum_dependencies, minimum_authorized = target_states[story_id]
        before_rank = _c0_story_rank(story_id, before_status)
        minimum_rank = _c0_story_rank(story_id, minimum_status)
        recovery_status = recovery_floors.get(story_id)
        recovery_rank = (
            _c0_story_rank(story_id, recovery_status)
            if recovery_status is not None
            else minimum_rank
        )
        target_rank = max(before_rank, minimum_rank, recovery_rank)
        target_status = C0_STORY_PROGRESS_ORDER[target_rank]
        lld_gate = story.get("lld_gate")
        if not isinstance(lld_gate, dict):
            raise ValueError(f"{story_id} lld_gate must be an object")
        dev_gate = story.get("dev_gate")
        if not isinstance(dev_gate, dict):
            raise ValueError(f"{story_id} dev_gate must be an object")
        dependencies_satisfied = (
            bool(dev_gate.get("dependencies_satisfied"))
            or minimum_dependencies
            or target_rank >= C0_STORY_PROGRESS_RANK["dev-ready"]
        )
        implementation_authorized = (
            bool(dev_gate.get("implementation_authorized"))
            or minimum_authorized
            or target_rank >= C0_STORY_PROGRESS_RANK["dev-ready"]
        )
        before_projection = (
            before_status,
            str(lld_gate.get("status") or ""),
            bool(dev_gate.get("lld_confirmed")),
            bool(dev_gate.get("cp5_confirmed")),
            bool(dev_gate.get("dependencies_satisfied")),
            bool(dev_gate.get("file_conflict_free")),
            bool(dev_gate.get("implementation_authorized")),
        )
        story["status"] = target_status
        lld_gate["status"] = "approved"
        dev_gate.update(
            {
                "lld_confirmed": True,
                "cp5_confirmed": True,
                "dependencies_satisfied": dependencies_satisfied,
                "file_conflict_free": True,
                "implementation_authorized": implementation_authorized,
            }
        )
        after_projection = (
            target_status,
            "approved",
            True,
            True,
            dependencies_satisfied,
            True,
            implementation_authorized,
        )
        if before_projection == after_projection:
            continue
        transitions.append(
            {
                "subject": story_id,
                "from": before_status,
                "to": target_status,
                "dependencies_satisfied": dependencies_satisfied,
                "implementation_authorized": implementation_authorized,
                "reason": (
                    "C0_REPAIR_REGRESSIVE_PRIOR_PROJECTION"
                    if recovery_status is not None
                    else "C0_PASS"
                ),
            }
        )
    return projected, tuple(transitions)


def project_cp5_development_plan(
    payload: Mapping[str, Any],
    *,
    cr_id: str,
    projection: CheckpointProjectionV1,
    gate_events: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    """把 canonical CP5 head 与一次人工批准投影为 Story 开发准入。"""

    if projection.target_cr_id != cr_id or projection.findings:
        raise ValueError("CP5 Story admission requires one valid CR projection; mutation=0")
    head = projection.head("CP5")
    if head is None:
        raise ValueError("CP5 canonical current head is unavailable; mutation=0")
    if head.decision != "PASS":
        raise ValueError("CP5 Story admission requires canonical decision=PASS; mutation=0")
    approvals = [
        approval
        for approval in event_ledger.project_gate_approvals(list(gate_events))
        if approval.passage
        and approval.cr_id == cr_id
        and approval.checkpoint == "CP5"
        and approval.result_ref == head.result_ref
    ]
    if len(approvals) != 1:
        raise ValueError(
            "CP5 Story admission requires exactly one approval bound to canonical "
            f"head; found={len(approvals)}; mutation=0"
        )

    projected = copy.deepcopy(dict(payload))
    waves = projected.get("waves")
    if not isinstance(waves, list):
        raise ValueError("DEVELOPMENT-PLAN must contain waves[]; mutation=0")
    stories: dict[str, dict[str, Any]] = {}
    for wave in waves:
        if not isinstance(wave, dict):
            continue
        wave_stories = wave.get("stories")
        if not isinstance(wave_stories, list):
            continue
        for story in wave_stories:
            if not isinstance(story, dict) or str(story.get("cr_id") or "") != cr_id:
                continue
            story_id = str(story.get("story_id") or "")
            if not story_id:
                raise ValueError("CP5 Story admission found Story without story_id; mutation=0")
            if story_id in stories:
                raise ValueError(f"duplicate Story in DEVELOPMENT-PLAN: {story_id}; mutation=0")
            stories[story_id] = story
    if not stories:
        raise ValueError(f"no {cr_id} Stories in DEVELOPMENT-PLAN; mutation=0")

    terminal_or_started = {
        "dev-ready",
        "in-development",
        "ready-for-verification",
        "verified",
        "verified-with-risk",
        "done",
    }
    completed = {
        story_id
        for story_id, story in stories.items()
        if str(story.get("status") or "")
        in {"ready-for-verification", "verified", "verified-with-risk", "done"}
    }
    transitions: list[dict[str, Any]] = []
    for story_id, story in sorted(stories.items()):
        lld_gate = story.get("lld_gate")
        dev_gate = story.get("dev_gate")
        if not isinstance(lld_gate, dict):
            raise ValueError(f"{story_id} lld_gate must be an object; mutation=0")
        if not isinstance(dev_gate, dict):
            raise ValueError(f"{story_id} dev_gate must be an object; mutation=0")
        dependencies = [str(item) for item in story.get("depends_on", []) if str(item)]
        unknown = sorted(set(dependencies) - set(stories))
        if unknown:
            raise ValueError(
                f"{story_id} has unknown dependencies: {', '.join(unknown)}; mutation=0"
            )
        dependencies_satisfied = not dependencies or all(
            dependency in completed for dependency in dependencies
        )
        current_status = str(story.get("status") or "")
        allowed = {
            "lld-ready",
            "lld-approved",
            *terminal_or_started,
        }
        if current_status not in allowed:
            raise ValueError(
                f"{story_id} cannot consume CP5 PASS from "
                f"status={current_status or '-'}; mutation=0"
            )
        already_started = current_status in terminal_or_started
        implementation_authorized = dependencies_satisfied or already_started
        target_status = current_status
        if current_status in {"lld-ready", "lld-approved"}:
            target_status = "dev-ready" if implementation_authorized else "lld-approved"
        before = (
            current_status,
            str(lld_gate.get("status") or ""),
            bool(dev_gate.get("implementation_authorized")),
        )
        story["status"] = target_status
        lld_gate["status"] = "approved"
        dev_gate.update(
            {
                "cp5_confirmed": True,
                "lld_confirmed": True,
                "dependencies_satisfied": dependencies_satisfied,
                "file_conflict_free": True,
                "implementation_authorized": implementation_authorized,
                "checkpoint_projection_digest": projection.as_dict()["projection_digest"],
                "checkpoint_result_ref": head.result_ref,
            }
        )
        after = (
            target_status,
            "approved",
            implementation_authorized,
        )
        if before != after:
            transitions.append(
                {
                    "subject": story_id,
                    "from": current_status,
                    "to": target_status,
                    "reason": "CANONICAL_CP5_PASS",
                    "result_ref": head.result_ref,
                }
            )
    return projected, tuple(transitions)


def project_cp6_development_plan(
    payload: Mapping[str, Any],
    *,
    result: Mapping[str, Any],
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    """将已记录的 CP6 PASS 原生投影到 Story 管理真相源及其直接下游。"""

    if str(result.get("checkpoint") or "") != "CP6":
        raise ValueError("Story projection requires one CP6 result")
    if str(result.get("decision") or "") != "PASS":
        raise ValueError("Story projection requires CP6 decision=PASS")
    story_id = str(result.get("story_id") or "")
    if not story_id:
        raise ValueError("CP6 result story_id is required")
    projected = copy.deepcopy(dict(payload))
    waves = projected.get("waves")
    if not isinstance(waves, list):
        raise ValueError("DEVELOPMENT-PLAN must contain waves[]")
    stories: dict[str, dict[str, Any]] = {}
    for wave in waves:
        if not isinstance(wave, dict):
            continue
        for story in wave.get("stories", []):
            if not isinstance(story, dict):
                continue
            candidate_id = str(story.get("story_id") or "")
            if not candidate_id:
                continue
            if candidate_id in stories:
                raise ValueError(f"duplicate Story in DEVELOPMENT-PLAN: {candidate_id}")
            stories[candidate_id] = story
    current = stories.get(story_id)
    if current is None:
        raise ValueError(f"CP6 Story missing from DEVELOPMENT-PLAN: {story_id}")
    current_status = str(current.get("status") or "")
    if current_status not in {
        "dev-ready",
        "in-development",
        "ready-for-verification",
    }:
        raise ValueError(f"{story_id} cannot consume CP6 PASS from status={current_status or '-'}")
    dev_gate = current.get("dev_gate")
    if not isinstance(dev_gate, dict) or not all(
        dev_gate.get(field) is True
        for field in (
            "cp5_confirmed",
            "dependencies_satisfied",
            "file_conflict_free",
            "implementation_authorized",
            "lld_confirmed",
        )
    ):
        raise ValueError(f"{story_id} CP6 projection requires a fully open dev_gate")
    transitions: list[dict[str, Any]] = []
    if current_status != "ready-for-verification":
        current["status"] = "ready-for-verification"
        transitions.append(
            {
                "subject": story_id,
                "from": current_status,
                "to": "ready-for-verification",
                "reason": "CP6_PASS",
            }
        )
    completed = {
        candidate_id
        for candidate_id, story in stories.items()
        if str(story.get("status") or "")
        in {"ready-for-verification", "verified", "verified-with-risk", "done"}
    }
    for candidate_id, downstream in sorted(stories.items()):
        dependencies = [str(item) for item in downstream.get("depends_on", []) if str(item)]
        if story_id not in dependencies or not dependencies:
            continue
        downstream_gate = downstream.get("dev_gate")
        if not isinstance(downstream_gate, dict):
            raise ValueError(f"{candidate_id} dev_gate must be an object")
        satisfied = all(dependency in completed for dependency in dependencies)
        downstream_gate["dependencies_satisfied"] = satisfied
        can_authorize = satisfied and all(
            downstream_gate.get(field) is True
            for field in (
                "cp5_confirmed",
                "file_conflict_free",
                "lld_confirmed",
            )
        )
        downstream_gate["implementation_authorized"] = can_authorize
        downstream_status = str(downstream.get("status") or "")
        if can_authorize and downstream_status == "lld-approved":
            downstream["status"] = "dev-ready"
            transitions.append(
                {
                    "subject": candidate_id,
                    "from": downstream_status,
                    "to": "dev-ready",
                    "reason": f"{story_id}_CP6_PASS",
                }
            )
    return projected, tuple(transitions)


CHRONOLOGY_KINDS = {
    "producer-complete",
    "checkpoint-created",
    "gate-opened",
    "conditional-received",
    "conditions-satisfied",
    "reviewed",
    "approved",
    "downstream-dispatch",
}
PRECEDENCE_EDGES = (
    ("producer-complete", "checkpoint-created"),
    ("checkpoint-created", "gate-opened"),
    ("gate-opened", "reviewed"),
    # Review is optional for compatibility, but a final approval must still
    # occur after the gate was formally opened when no review node is present.
    ("gate-opened", "approved"),
    ("reviewed", "approved"),
    ("approved", "downstream-dispatch"),
    ("conditional-received", "conditions-satisfied"),
    ("conditions-satisfied", "approved"),
)


def _parse_chronology_time(value: str | datetime | None) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        token = value.strip()
        if token.endswith("Z"):
            token = f"{token[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(token)
        except ValueError:
            return None
    else:
        return None
    return parsed if parsed.tzinfo is not None else None


def _chronology_finding(
    code: str,
    node: ChronologyNode,
    field: str,
    message: str,
    *refs: str,
) -> ChronologyFinding:
    return ChronologyFinding(
        code=code,
        object_ref=node.source_ref,
        field=field,
        message=message,
        source_refs=tuple(ref for ref in refs if ref),
    )


def validate_chronology(nodes: list[ChronologyNode]) -> list[ChronologyFinding]:
    """Validate the partial order of one canonical workflow attempt.

    Optional nodes are not fabricated.  Multiple nodes of the same kind are
    accepted only when they agree; a conflicting duplicate is surfaced as a
    deterministic temporal finding instead of being silently selected.
    """

    findings: list[ChronologyFinding] = []
    indexed: dict[str, tuple[ChronologyNode, datetime]] = {}
    conditional_present = False
    for node in nodes:
        if node.kind not in CHRONOLOGY_KINDS:
            findings.append(
                _chronology_finding(
                    "UNKNOWN_CHRONOLOGY_KIND", node, "kind", "unknown chronology kind"
                )
            )
            continue
        if not node.source_ref.strip():
            findings.append(
                _chronology_finding(
                    "INVALID_SOURCE_REF",
                    node,
                    "source_ref",
                    "chronology nodes require a non-empty canonical source_ref",
                )
            )
            continue
        if node.kind == "conditional-received":
            conditional_present = True
        parsed = _parse_chronology_time(node.occurred_at)
        if parsed is None:
            findings.append(
                _chronology_finding(
                    "UNPARSEABLE_TIMESTAMP",
                    node,
                    "occurred_at",
                    "chronology timestamps must be RFC3339 values with an explicit timezone",
                )
            )
            continue
        existing = indexed.get(node.kind)
        if existing is not None and existing[1] != parsed:
            findings.append(
                _chronology_finding(
                    "TEMPORAL_ORDER_VIOLATION",
                    node,
                    "occurred_at",
                    f"conflicting duplicate timestamp for {node.kind}",
                    existing[0].source_ref,
                )
            )
            continue
        indexed[node.kind] = (node, parsed)

    for earlier_kind, later_kind in PRECEDENCE_EDGES:
        earlier = indexed.get(earlier_kind)
        later = indexed.get(later_kind)
        if earlier is None or later is None:
            continue
        if earlier[1] > later[1]:
            findings.append(
                _chronology_finding(
                    "TEMPORAL_ORDER_VIOLATION",
                    later[0],
                    "occurred_at",
                    f"{earlier_kind} must not occur after {later_kind}",
                    earlier[0].source_ref,
                )
            )

    approved = indexed.get("approved")
    gate_opened = indexed.get("gate-opened")
    if approved is not None and gate_opened is None:
        findings.append(
            _chronology_finding(
                "APPROVAL_BEFORE_GATE",
                approved[0],
                "occurred_at",
                "final approval requires a prior gate-opened event",
            )
        )
    if conditional_present and approved is not None and "conditions-satisfied" not in indexed:
        findings.append(
            _chronology_finding(
                "CONDITIONS_UNSATISFIED",
                approved[0],
                "occurred_at",
                "conditional approval requires a conditions-satisfied event before final approval",
            )
        )
    return sorted(findings, key=lambda item: (item.code, item.object_ref, item.field, item.message))


def derive_gate_decision(events: list[ChronologyNode]) -> tuple[str, list[ChronologyFinding]]:
    """Return the gate state without promoting a conditional instruction to approval."""

    findings = validate_chronology(events)
    kinds = {event.kind for event in events}
    if findings:
        return "pending", findings
    if "approved" in kinds:
        return "approved", findings
    if "conditions-satisfied" in kinds:
        return "conditions-satisfied", findings
    if "conditional-received" in kinds:
        return "conditional", findings
    return "pending", findings


def validate_phase_gate_state(
    state: dict[str, Any], gate_events: list[ChronologyNode]
) -> list[ChronologyFinding]:
    """Keep phase work in progress separate from an opened human gate."""

    findings: list[ChronologyFinding] = []
    decision, chronology_findings = derive_gate_decision(gate_events)
    findings.extend(chronology_findings)
    pending_gate = str(state.get("pending_gate") or "")
    kinds = {event.kind for event in gate_events}
    approved_nodes = [event for event in gate_events if event.kind == "approved"]
    reference = (
        approved_nodes[0]
        if approved_nodes
        else ChronologyNode("gate-opened", None, "STATE.current.json")
    )

    if "gate-opened" not in kinds and {"reviewed", "approved"} & kinds:
        observed = next(event for event in gate_events if event.kind in {"reviewed", "approved"})
        findings.append(
            _chronology_finding(
                "PHASE_GATE_CONFLATION",
                observed,
                "kind",
                "formal review or approval cannot be recorded while gate-open is false",
            )
        )

    if decision in {"conditional", "conditions-satisfied"} and not pending_gate:
        findings.append(
            _chronology_finding(
                "PHASE_GATE_CONFLATION",
                reference,
                "pending_gate",
                "an unresolved conditional gate must remain represented by pending_gate",
            )
        )
    if decision == "approved":
        has_downstream_dispatch = "downstream-dispatch" in kinds
        if pending_gate:
            findings.append(
                _chronology_finding(
                    "PHASE_GATE_CONFLATION",
                    reference,
                    "pending_gate",
                    "a final approved gate cannot remain pending",
                )
            )
        elif not has_downstream_dispatch:
            findings.append(
                _chronology_finding(
                    "PHASE_GATE_CONFLATION",
                    reference,
                    "pending_gate",
                    "an approved gate without pending_gate requires a downstream transition record",
                )
            )
    return sorted(findings, key=lambda item: (item.code, item.object_ref, item.field, item.message))


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _state_path(project_root: Path, explicit: Path | None = None) -> Path:
    if explicit:
        return explicit
    return _resolve_runtime_ref(project_root, "process/state/STATE.current.json")


def _stage_index(stages: list[dict[str, Any]], checkpoint: str) -> int:
    for index, stage in enumerate(stages):
        if str(stage.get("checkpoint") or "") == checkpoint:
            return index
    return -1


def _next_required_gate(stages: list[dict[str, Any]], checkpoint: str) -> str:
    start = _stage_index(stages, checkpoint)
    if start < 0:
        return ""
    for stage in stages[start + 1 :]:
        if str(stage.get("human_gate") or "none") == "required":
            return str(stage.get("checkpoint") or "")
    return ""


def _has_automatic_stage_before_gate(
    stages: list[dict[str, Any]], checkpoint: str, gate: str
) -> bool:
    """Return whether a route has real automatic work before its next human gate."""

    start = _stage_index(stages, checkpoint)
    end = _stage_index(stages, gate)
    if start < 0 or end <= start:
        return False
    return any(
        str(stage.get("human_gate") or "none") == "none" for stage in stages[start + 1 : end]
    )


def expected_post_transition(route: dict[str, Any], checkpoint: str) -> dict[str, str]:
    """Return the required stop target after a checkpoint or approved gate."""

    stages = [stage for stage in route.get("stages") or [] if isinstance(stage, dict)]
    expected_gate = _next_required_gate(stages, checkpoint)
    if expected_gate:
        return {"kind": "required_human_gate", "checkpoint": expected_gate}
    if checkpoint == "CP8":
        return {"kind": "delivered", "checkpoint": ""}
    return {"kind": "no_remaining_required_gate", "checkpoint": ""}


def _next_action(state: dict[str, Any]) -> dict[str, Any]:
    value = state.get("next_action") or {}
    if isinstance(value, dict):
        return value
    if value:
        return {"type": "continue", "text": str(value)}
    return {}


def _stop_reason(state: dict[str, Any]) -> str:
    action = _next_action(state)
    reason = str(action.get("stop_reason") or action.get("reason") or "")
    return reason.strip()


def _is_true_delivered_terminal(state: dict[str, Any]) -> bool:
    return (
        str(state.get("current_phase") or "") == "delivered"
        and not state.get("active_change")
        and not state.get("pending_gate")
        and _stop_reason(state) == "delivered"
    )


def _decision_compatible_stop_reasons(decision: str, expected: dict[str, str]) -> set[str]:
    if decision in FAILURE_STOP_REASONS:
        return set(FAILURE_STOP_REASONS[decision])
    if decision in PASS_LIKE_DECISIONS:
        reasons = set(PASS_COMPATIBLE_INTERRUPT_REASONS)
        expected_kind = expected.get("kind") or ""
        if expected_kind == "required_human_gate":
            reasons.add("required_human_gate")
        elif expected_kind == "delivered":
            reasons.add("delivered")
        elif expected_kind == "no_remaining_required_gate":
            reasons.add("no_remaining_route")
        return reasons
    return set(ALLOWED_STOP_REASONS)


def _has_valid_stop_reason(
    state: dict[str, Any], expected: dict[str, str], *, decision: str = ""
) -> bool:
    reason = _stop_reason(state)
    if reason not in _decision_compatible_stop_reasons(decision, expected):
        return False
    if reason == "required_human_gate":
        return bool(state.get("pending_gate")) and str(state.get("pending_gate")) == expected.get(
            "checkpoint"
        )
    if reason == "delivered":
        return str(state.get("current_phase") or "") == "delivered"
    return True


def _state_matches_expected_stop(
    state: dict[str, Any], expected: dict[str, str], *, decision: str = ""
) -> list[str]:
    errors: list[str] = []
    kind = expected.get("kind") or ""
    expected_gate = expected.get("checkpoint") or ""
    pending_gate = str(state.get("pending_gate") or "")
    action = _next_action(state)
    action_type = str(action.get("type") or "")

    if kind == "required_human_gate":
        if pending_gate == expected_gate:
            if not state.get("pending_checklist_path"):
                errors.append(f"{expected_gate} is pending but pending_checklist_path is missing")
            if action_type and action_type not in AWAIT_USER_ACTION_TYPES:
                errors.append(
                    f"{expected_gate} pending gate should use await_user next_action.type, got {action_type}"
                )
            return errors
        if _has_valid_stop_reason(state, expected, decision=decision):
            return errors
        errors.append(
            f"post-transition must advance to pending_gate={expected_gate} or record a valid stop_reason; "
            f"got pending_gate={pending_gate or '-'} next_action.type={action_type or '-'}"
        )
        return errors

    if kind == "delivered":
        if _is_true_delivered_terminal(state):
            return errors
        if not pending_gate and _stop_reason(state) in PASS_COMPATIBLE_INTERRUPT_REASONS:
            return errors
        errors.append(
            "CP8 approval must reach a true delivered terminal state with no active_change/pending_gate "
            "and stop_reason=delivered, or record authorization_required/workflow_health_threshold"
        )
        return errors

    if _has_valid_stop_reason(state, expected, decision=decision):
        return errors
    if action_type in {"await_user", "continue", "wait_user"} and not pending_gate:
        errors.append(
            "route has no remaining required gate; state must continue automatically, deliver, or record a valid stop_reason"
        )
    return errors


def _is_automatic_phase_in_progress(
    *,
    route: dict[str, Any],
    state: dict[str, Any],
    checkpoint: str,
    expected: dict[str, str],
) -> bool:
    """Accept actual automatic work instead of forcing a future gate into STATE.

    A gate approval may legitimately be followed by CP6/CP7 work.  The state
    is not allowed to claim the later gate before its checklist exists, but it
    also must not fail merely because the automatic work has not finished.
    """

    if expected.get("kind") != "required_human_gate" or checkpoint not in {"CP5", "CP6", "CP7"}:
        return False
    stages = [stage for stage in route.get("stages") or [] if isinstance(stage, dict)]
    if checkpoint != "CP7" and not _has_automatic_stage_before_gate(
        stages, checkpoint, expected.get("checkpoint") or ""
    ):
        return False
    if state.get("pending_gate") or str(state.get("current_phase") or "") != "story-execution":
        return False
    if checkpoint == "CP7" and not state.get("active_story"):
        # CP7 is rolling.  The final Story must clear active_story and open
        # CP8; an earlier Story may advance the dependency graph instead.
        return False
    action_type = str(_next_action(state).get("type") or "")
    if action_type in AWAIT_USER_ACTION_TYPES or action_type in {"blocked", "done"}:
        return False
    return bool(state.get("active_change")) and bool(str(state.get("current_phase") or "").strip())


def validate_auto_cp_transition(
    *,
    route: dict[str, Any],
    state: dict[str, Any],
    checkpoint: str,
    decision: str,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    stages = [stage for stage in route.get("stages") or [] if isinstance(stage, dict)]
    index = _stage_index(stages, checkpoint)
    if index < 0:
        return [f"{checkpoint} is not present in route_plan.stages"], warnings
    human_gate = str(stages[index].get("human_gate") or "none")
    if decision in FAILURE_DECISIONS:
        expected_failure = {"kind": "failure", "checkpoint": ""}
        if not _has_valid_stop_reason(state, expected_failure, decision=decision):
            errors.append(
                f"{checkpoint} decision={decision} must leave matching "
                "stop_reason in {" + ", ".join(sorted(FAILURE_STOP_REASONS[decision])) + "}"
            )
        return errors, warnings
    if decision not in PASS_LIKE_DECISIONS:
        warnings.append(
            f"{checkpoint} decision={decision} is not pass-like; transition guard did not enforce auto-advance"
        )
        return errors, warnings
    if human_gate != "none":
        warnings.append(
            f"{checkpoint} human_gate={human_gate}; use --approved-gate after human approval is recorded"
        )
        return errors, warnings
    if _is_true_delivered_terminal(state):
        return errors, warnings
    expected = expected_post_transition(route, checkpoint)
    stale_failure_reason = _stop_reason(state)
    if stale_failure_reason in STALE_FAILURE_STOP_REASONS:
        errors.append(
            f"{checkpoint} decision={decision} cannot retain failure stop_reason={stale_failure_reason}"
        )
    if not _is_automatic_phase_in_progress(
        route=route, state=state, checkpoint=checkpoint, expected=expected
    ):
        errors.extend(_state_matches_expected_stop(state, expected, decision=decision))
    return errors, warnings


def validate_approved_gate_transition(
    *,
    route: dict[str, Any],
    state: dict[str, Any],
    checkpoint: str,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    stages = [stage for stage in route.get("stages") or [] if isinstance(stage, dict)]
    index = _stage_index(stages, checkpoint)
    if index < 0:
        return [f"{checkpoint} is not present in route_plan.stages"], warnings
    human_gate = str(stages[index].get("human_gate") or "none")
    if human_gate != "required":
        warnings.append(
            f"{checkpoint} human_gate={human_gate}; approved-gate transition is normally checked for required gates"
        )
    pending_gate = str(state.get("pending_gate") or "")
    if pending_gate == checkpoint:
        errors.append(
            f"{checkpoint} approval was recorded but STATE.current.json still waits on the same pending_gate"
        )
        return errors, warnings
    expected = expected_post_transition(route, checkpoint)
    if not _is_automatic_phase_in_progress(
        route=route, state=state, checkpoint=checkpoint, expected=expected
    ):
        errors.extend(_state_matches_expected_stop(state, expected))
    return errors, warnings


def validate_transition(
    *,
    route_plan_path: Path,
    state_path: Path,
    result_path: Path | None = None,
    checkpoint: str = "",
    decision: str = "",
    approved_gate: str = "",
) -> tuple[list[str], list[str]]:
    route = _read_json(route_plan_path)
    state = _read_json(state_path)
    if approved_gate:
        return validate_approved_gate_transition(route=route, state=state, checkpoint=approved_gate)
    if result_path:
        result = _read_json(result_path)
        checkpoint = str(result.get("checkpoint") or result.get("checkpoint_id") or checkpoint)
        decision = str(result.get("decision") or decision)
    if not checkpoint or not decision:
        return ["provide --result or both --checkpoint and --decision"], []
    return validate_auto_cp_transition(
        route=route, state=state, checkpoint=checkpoint, decision=decision
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="meta-flow check state-transition",
        description="Validate that approve/auto-CP transitions run until the next required gate, delivery, or an explicit stop_reason.",
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--route-plan", type=Path, default=None)
    parser.add_argument("--state", type=Path, default=None)
    parser.add_argument(
        "--result",
        type=Path,
        default=None,
        help="CP result JSON for automatic CP PASS/WAIVED transitions",
    )
    parser.add_argument(
        "--checkpoint", default="", help="Checkpoint id when --result is not supplied"
    )
    parser.add_argument("--decision", default="", help="Decision when --result is not supplied")
    parser.add_argument(
        "--approved-gate",
        default="",
        help="Required human gate that was just approved, for example CP3",
    )
    parser.add_argument(
        "--chronology-events",
        type=Path,
        default=None,
        help="JSON object containing events[] and optional state for chronology-only validation",
    )
    parser.add_argument("--output", choices=("text", "json"), default="text")
    parsed = parser.parse_args(argv)

    project_root = parsed.project_root.resolve()
    if parsed.chronology_events:
        try:
            payload = _read_json(parsed.chronology_events)
            raw_events = payload.get("events")
            if not isinstance(raw_events, list):
                raise ValueError("chronology events payload requires events[]")
            nodes = [
                ChronologyNode(
                    kind=str(item.get("kind") or ""),
                    occurred_at=item.get("occurred_at"),
                    source_ref=str(item.get("source_ref") or ""),
                )
                for item in raw_events
                if isinstance(item, dict)
            ]
            if len(nodes) != len(raw_events):
                raise ValueError("chronology events[] entries must be JSON objects")
            findings = validate_phase_gate_state(payload.get("state") or {}, nodes)
            decision, _ = derive_gate_decision(nodes)
            errors = [finding.message for finding in findings]
            warnings: list[str] = []
        except ValueError as exc:
            findings = []
            decision = "pending"
            errors, warnings = [str(exc)], []
        if parsed.output == "json":
            print(
                json.dumps(
                    {
                        "decision": decision,
                        "findings": [asdict(finding) for finding in findings],
                        "status": "FAIL" if errors else "OK",
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        else:
            print("State Transition Check: " + ("FAIL" if errors else "OK"))
            print(f"- gate_decision: {decision}")
            for finding in findings:
                print(
                    f"- ERROR: {finding.code} {finding.object_ref}.{finding.field}: {finding.message}"
                )
            for error in errors if not findings else []:
                print(f"- ERROR: {error}")
        return 1 if errors else 0

    if parsed.route_plan is None:
        parser.error("--route-plan is required unless --chronology-events is supplied")
    state_path = _state_path(project_root, parsed.state)
    try:
        errors, warnings = validate_transition(
            route_plan_path=parsed.route_plan,
            state_path=state_path,
            result_path=parsed.result,
            checkpoint=parsed.checkpoint,
            decision=parsed.decision,
            approved_gate=parsed.approved_gate,
        )
    except FileNotFoundError as exc:
        # STATE.current.json 是派生投影；CP5 批准后的 CP6 工作可在其尚未
        # 建立时继续，不能为了通过检查而创建该状态文件。
        missing_path = Path(exc.filename).resolve() if exc.filename else None
        if (
            parsed.approved_gate == "CP5"
            and state_path.name == "STATE.current.json"
            and missing_path == state_path.resolve()
        ):
            errors, warnings = (
                [],
                [
                    f"state projection absent: {exc.filename}; CP5 transition accepted without mutation"
                ],
            )
        else:
            errors, warnings = [str(exc)], []
    except ValueError as exc:
        errors, warnings = [str(exc)], []
    if parsed.output == "json":
        print(
            json.dumps(
                {"errors": errors, "status": "FAIL" if errors else "OK", "warnings": warnings},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    else:
        print("State Transition Check: " + ("FAIL" if errors else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
