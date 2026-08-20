"""短 Work 交接与 OID/scope 恢复预检。"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meta_flow.project.model import is_safe_ref
from meta_flow.project.scale import dump_yaml, load_yaml_object
from meta_flow.work.model import WORK_STATUSES, Work, load_work

HANDOFF_SCHEMA_VERSION = 1
HANDOFF_POLICY_SCHEMA_VERSION = 1
HANDOFF_POLICY_KIND = "HandoffPolicyDecisionV1"
# HANDOFF policy 消费的是合法 lifecycle 的目标状态，不是只消费会创建
# HANDOFF 的三个状态。只有 paused/blocked 可能要求交接；其余合法后像必须
# 明确收敛为 NOT_REQUIRED，不能阻断 completed -> archived 等生命周期。
HANDOFF_POLICY_TRANSITIONS = frozenset(WORK_STATUSES - {"planned"})
_STEP_RE = re.compile(r"^[^\x00\r\n]{1,500}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


@dataclass(frozen=True)
class HandoffPolicyDecisionV1:
    """由 canonical Work route/risk 推导出的只读 handoff 决策。"""

    work_id: str
    transition: str
    required: bool
    decision: str
    reason_codes: tuple[str, ...]
    schema_version: int = HANDOFF_POLICY_SCHEMA_VERSION
    kind: str = HANDOFF_POLICY_KIND

    def __post_init__(self) -> None:
        if self.schema_version != HANDOFF_POLICY_SCHEMA_VERSION:
            raise ValueError("HANDOFF_POLICY_SCHEMA_VERSION_INVALID")
        if self.kind != HANDOFF_POLICY_KIND:
            raise ValueError("HANDOFF_POLICY_KIND_INVALID")
        if not _ID_RE.fullmatch(self.work_id):
            raise ValueError("HANDOFF_POLICY_WORK_ID_INVALID")
        if self.transition not in HANDOFF_POLICY_TRANSITIONS:
            raise ValueError("HANDOFF_POLICY_TRANSITION_INVALID")
        expected_decision = "REQUIRED" if self.required else "NOT_REQUIRED"
        if self.decision != expected_decision:
            raise ValueError("HANDOFF_POLICY_DECISION_INVALID")
        if not self.reason_codes or len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("HANDOFF_POLICY_REASON_CODES_INVALID")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "work_id": self.work_id,
            "transition": self.transition,
            "required": self.required,
            "decision": self.decision,
            "reason_codes": list(self.reason_codes),
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            json.dumps(
                self.as_dict(),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()


def decide_handoff_policy(work: Work, transition: str) -> HandoffPolicyDecisionV1:
    """纯函数判定目标状态是否需要 Agent HANDOFF。"""

    if transition not in HANDOFF_POLICY_TRANSITIONS:
        raise ValueError("HANDOFF_POLICY_TRANSITION_INVALID")

    reasons: list[str] = []
    if transition == "active":
        reasons.append("ACTIVE_TRANSITION_HANDOFF_NOT_REQUIRED")
    elif transition not in {"paused", "blocked"}:
        reasons.append("LIFECYCLE_TRANSITION_HANDOFF_NOT_REQUIRED")
    elif work.risk_profile == "G2":
        if work.route_profile.dispatch_mode == "functional-agent":
            reasons.append("G2_FUNCTIONAL_AGENT_HANDOFF_REQUIRED")
        if work.route_profile.legacy_cp_compatibility:
            reasons.append("G2_LEGACY_CP_HANDOFF_REQUIRED")

    required = transition in {"paused", "blocked"} and bool(reasons)
    if not required:
        if transition in {"paused", "blocked"}:
            reasons.append(
                "ROUTINE_DIRECT_G0_G1_HANDOFF_NOT_REQUIRED"
                if work.risk_profile in {"G0", "G1"}
                else "ROUTINE_DIRECT_HANDOFF_NOT_REQUIRED"
            )
        decision = "NOT_REQUIRED"
    else:
        decision = "REQUIRED"

    return HandoffPolicyDecisionV1(
        work_id=work.work_id,
        transition=transition,
        required=required,
        decision=decision,
        reason_codes=tuple(reasons),
    )


@dataclass(frozen=True)
class WorkHandoff:
    work_id: str
    project_id: str
    work_status: str
    scope_digest: str
    release_oid: str
    process_oid: str
    completed: tuple[str, ...]
    remaining: tuple[str, ...]
    blockers: tuple[str, ...]
    next_step: str
    evidence_refs: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": HANDOFF_SCHEMA_VERSION,
            **self.__dict__,
            "completed": list(self.completed),
            "remaining": list(self.remaining),
            "blockers": list(self.blockers),
            "evidence_refs": list(self.evidence_refs),
        }

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> WorkHandoff:
        expected = {
            "schema_version",
            "work_id",
            "project_id",
            "work_status",
            "scope_digest",
            "release_oid",
            "process_oid",
            "completed",
            "remaining",
            "blockers",
            "next_step",
            "evidence_refs",
        }
        if set(payload) != expected or payload.get("schema_version") != HANDOFF_SCHEMA_VERSION:
            raise ValueError("handoff fields mismatch")
        sequence_fields = ("completed", "remaining", "blockers", "evidence_refs")
        if any(
            not isinstance(payload[field], list)
            or any(not isinstance(item, str) for item in payload[field])
            for field in sequence_fields
        ):
            raise ValueError("handoff collection fields are invalid")
        handoff = cls(
            work_id=str(payload["work_id"]),
            project_id=str(payload["project_id"]),
            work_status=str(payload["work_status"]),
            scope_digest=str(payload["scope_digest"]),
            release_oid=str(payload["release_oid"]),
            process_oid=str(payload["process_oid"]),
            completed=tuple(payload["completed"]),
            remaining=tuple(payload["remaining"]),
            blockers=tuple(payload["blockers"]),
            next_step=str(payload["next_step"]),
            evidence_refs=tuple(payload["evidence_refs"]),
        )
        _validate_handoff_content(
            release_oid=handoff.release_oid,
            process_oid=handoff.process_oid,
            completed=handoff.completed,
            remaining=handoff.remaining,
            blockers=handoff.blockers,
            next_step=handoff.next_step,
            evidence_refs=handoff.evidence_refs,
        )
        return handoff


@dataclass(frozen=True)
class HandoffTransitionPlanV1:
    """route policy 派生的零写/单目标 HANDOFF child plan。"""

    decision: str
    work_id: str
    target_ref: str
    before_exists: bool
    before_digest: str
    desired_bytes: bytes
    desired_digest: str
    route_policy_digest: str
    blockers: tuple[str, ...]
    plan_digest: str

    @property
    def ready(self) -> bool:
        return self.decision == "READY" and not self.blockers

    @property
    def target_refs(self) -> tuple[str, ...]:
        return (self.target_ref,) if self.target_ref else ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "HandoffTransitionPlanV1",
            "decision": self.decision,
            "work_id": self.work_id,
            "target_ref": self.target_ref,
            "before_exists": self.before_exists,
            "before_digest": self.before_digest,
            "desired_bytes_b64": base64.b64encode(self.desired_bytes).decode("ascii"),
            "desired_digest": self.desired_digest,
            "route_policy_digest": self.route_policy_digest,
            "blockers": list(self.blockers),
            "plan_digest": self.plan_digest,
            "mutation_count": 0,
        }

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> HandoffTransitionPlanV1:
        expected = {
            "schema_version",
            "kind",
            "decision",
            "work_id",
            "target_ref",
            "before_exists",
            "before_digest",
            "desired_bytes_b64",
            "desired_digest",
            "route_policy_digest",
            "blockers",
            "plan_digest",
            "mutation_count",
        }
        if (
            set(payload) != expected
            or payload.get("schema_version") != 1
            or payload.get("kind") != "HandoffTransitionPlanV1"
        ):
            raise ValueError("HANDOFF_PLAN_FIELDS_MISMATCH")
        blockers = payload.get("blockers")
        if not isinstance(blockers, list) or any(not isinstance(item, str) for item in blockers):
            raise ValueError("HANDOFF_PLAN_BLOCKERS_INVALID")
        try:
            desired = base64.b64decode(str(payload["desired_bytes_b64"]), validate=True)
        except (TypeError, ValueError) as exc:
            raise ValueError("HANDOFF_PLAN_DESIRED_BYTES_INVALID") from exc
        plan = cls(
            decision=str(payload["decision"]),
            work_id=str(payload["work_id"]),
            target_ref=str(payload["target_ref"]),
            before_exists=bool(payload["before_exists"]),
            before_digest=str(payload["before_digest"]),
            desired_bytes=desired,
            desired_digest=str(payload["desired_digest"]),
            route_policy_digest=str(payload["route_policy_digest"]),
            blockers=tuple(blockers),
            plan_digest=str(payload["plan_digest"]),
        )
        fields = {key: payload[key] for key in expected - {"plan_digest", "mutation_count"}}
        if (
            payload.get("mutation_count") != 0
            or hashlib.sha256(desired).hexdigest() != plan.desired_digest
            or _handoff_plan_digest(fields) != plan.plan_digest
        ):
            raise ValueError("HANDOFF_PLAN_INTEGRITY_INVALID")
        return plan


@dataclass(frozen=True)
class ResumeDecision:
    decision: str
    reasons: tuple[str, ...]
    work_id: str
    expected_release_oid: str
    actual_release_oid: str
    expected_process_oid: str
    actual_process_oid: str


def _valid_oid(value: str) -> bool:
    return value == "" or (
        len(value) in {40, 64} and all(char in "0123456789abcdefABCDEF" for char in value)
    )


def _validate_handoff_content(
    *,
    release_oid: str,
    process_oid: str,
    completed: tuple[str, ...],
    remaining: tuple[str, ...],
    blockers: tuple[str, ...],
    next_step: str,
    evidence_refs: tuple[str, ...],
) -> None:
    if not _valid_oid(release_oid) or not _valid_oid(process_oid):
        raise ValueError("handoff OIDs must be empty or full hexadecimal OIDs")
    if not _STEP_RE.fullmatch(next_step):
        raise ValueError("next_step must be one bounded line")
    for values in (completed, remaining, blockers):
        if len(values) > 20 or not all(_STEP_RE.fullmatch(item) for item in values):
            raise ValueError("handoff task lists must contain at most 20 bounded lines")
    if len(evidence_refs) > 20 or not all(is_safe_ref(item) for item in evidence_refs):
        raise ValueError("handoff evidence_refs must be safe and bounded")


def build_handoff(
    work: Work,
    *,
    release_oid: str,
    process_oid: str,
    completed: tuple[str, ...],
    remaining: tuple[str, ...],
    blockers: tuple[str, ...],
    next_step: str,
    evidence_refs: tuple[str, ...] = (),
) -> WorkHandoff:
    if work.status not in {"paused", "blocked"}:
        raise ValueError("handoff can only be built for a paused or blocked Work")
    _validate_handoff_content(
        release_oid=release_oid,
        process_oid=process_oid,
        completed=completed,
        remaining=remaining,
        blockers=blockers,
        next_step=next_step,
        evidence_refs=evidence_refs,
    )
    return WorkHandoff(
        work_id=work.work_id,
        project_id=work.project_id,
        work_status=work.status,
        scope_digest=work.scope.digest,
        release_oid=release_oid,
        process_oid=process_oid,
        completed=completed,
        remaining=remaining,
        blockers=blockers,
        next_step=next_step,
        evidence_refs=evidence_refs,
    )


def handoff_path(process_root: Path, work_id: str) -> Path:
    return process_root.resolve() / "works" / work_id / "HANDOFF.yaml"


def _handoff_plan_digest(fields: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(fields, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def unavailable_handoff_transition_plan(
    work_id: str,
    reason: str,
) -> HandoffTransitionPlanV1:
    """供 aggregate planner 在 Work/postimage 不可解析时保持 typed BLOCKED。"""

    empty_digest = hashlib.sha256(b"").hexdigest()
    fields = {
        "schema_version": 1,
        "kind": "HandoffTransitionPlanV1",
        "decision": "BLOCKED",
        "work_id": work_id,
        "target_ref": "",
        "before_exists": False,
        "before_digest": empty_digest,
        "desired_bytes_b64": "",
        "desired_digest": empty_digest,
        "route_policy_digest": empty_digest,
        "blockers": [reason],
    }
    return HandoffTransitionPlanV1(
        "BLOCKED",
        work_id,
        "",
        False,
        empty_digest,
        b"",
        empty_digest,
        empty_digest,
        (reason,),
        _handoff_plan_digest(fields),
    )


def plan_handoff_transition(
    process_root: Path,
    work: Work,
    *,
    transition: str,
    handoff: WorkHandoff | None,
) -> HandoffTransitionPlanV1:
    """按 postimage Work/route policy 生成 HANDOFF child；全程零写。"""

    policy = decide_handoff_policy(work, transition)
    blockers: list[str] = []
    target_ref = ""
    before_exists = False
    before_digest = hashlib.sha256(b"").hexdigest()
    desired = b""
    if policy.required:
        target_ref = f"works/{work.work_id}/HANDOFF.yaml"
        if handoff is None:
            blockers.append("HANDOFF_REQUIRED_BY_ROUTE_POLICY")
        elif (
            handoff.work_id != work.work_id
            or handoff.project_id != work.project_id
            or handoff.work_status != transition
            or handoff.scope_digest != work.scope.digest
        ):
            blockers.append("HANDOFF_POSTIMAGE_BINDING_MISMATCH")
        else:
            _validate_handoff_content(
                release_oid=handoff.release_oid,
                process_oid=handoff.process_oid,
                completed=handoff.completed,
                remaining=handoff.remaining,
                blockers=handoff.blockers,
                next_step=handoff.next_step,
                evidence_refs=handoff.evidence_refs,
            )
            desired = (
                json.dumps(handoff.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            ).encode("utf-8")
        path = handoff_path(process_root, work.work_id)
        if path.is_symlink() or (path.exists() and not path.is_file()):
            blockers.append("HANDOFF_TARGET_UNSAFE")
        elif path.is_file():
            before_exists = True
            before_digest = hashlib.sha256(path.read_bytes()).hexdigest()
    elif handoff is not None:
        blockers.append("HANDOFF_FORBIDDEN_BY_ROUTE_POLICY")
    desired_digest = hashlib.sha256(desired).hexdigest()
    fields = {
        "schema_version": 1,
        "kind": "HandoffTransitionPlanV1",
        "decision": "BLOCKED" if blockers else "READY",
        "work_id": work.work_id,
        "target_ref": target_ref,
        "before_exists": before_exists,
        "before_digest": before_digest,
        "desired_bytes_b64": base64.b64encode(desired).decode("ascii"),
        "desired_digest": desired_digest,
        "route_policy_digest": policy.digest,
        "blockers": blockers,
    }
    return HandoffTransitionPlanV1(
        decision=str(fields["decision"]),
        work_id=work.work_id,
        target_ref=target_ref,
        before_exists=before_exists,
        before_digest=before_digest,
        desired_bytes=desired,
        desired_digest=desired_digest,
        route_policy_digest=policy.digest,
        blockers=tuple(blockers),
        plan_digest=_handoff_plan_digest(fields),
    )


def validate_handoff_transition_plan(
    process_root: Path,
    plan: HandoffTransitionPlanV1,
    *,
    verify_preimage: bool,
) -> None:
    """重算 HANDOFF child 完整性；apply admission 可同时校验 preimage。"""

    if plan.target_ref and plan.target_ref != f"works/{plan.work_id}/HANDOFF.yaml":
        raise ValueError("HANDOFF_PLAN_TARGET_INVALID")
    if hashlib.sha256(plan.desired_bytes).hexdigest() != plan.desired_digest:
        raise ValueError("HANDOFF_PLAN_DESIRED_DIGEST_MISMATCH")
    fields = {
        "schema_version": 1,
        "kind": "HandoffTransitionPlanV1",
        "decision": plan.decision,
        "work_id": plan.work_id,
        "target_ref": plan.target_ref,
        "before_exists": plan.before_exists,
        "before_digest": plan.before_digest,
        "desired_bytes_b64": base64.b64encode(plan.desired_bytes).decode("ascii"),
        "desired_digest": plan.desired_digest,
        "route_policy_digest": plan.route_policy_digest,
        "blockers": list(plan.blockers),
    }
    if _handoff_plan_digest(fields) != plan.plan_digest:
        raise ValueError("HANDOFF_PLAN_DIGEST_MISMATCH")
    if plan.decision not in {"READY", "BLOCKED"} or (
        plan.ready and bool(plan.target_ref) != bool(plan.desired_bytes)
    ):
        raise ValueError("HANDOFF_PLAN_SHAPE_INVALID")
    if verify_preimage and plan.target_ref:
        path = handoff_path(process_root, plan.work_id)
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError("HANDOFF_TARGET_UNSAFE")
        exists = path.is_file()
        current = path.read_bytes() if exists else b""
        if (
            exists != plan.before_exists
            or hashlib.sha256(current).hexdigest() != plan.before_digest
        ):
            raise ValueError("HANDOFF_PREIMAGE_DRIFT")


def handoff_from_transition_plan(plan: HandoffTransitionPlanV1) -> WorkHandoff | None:
    """从已绑定 desired bytes 恢复 fresh replan 所需的 typed HANDOFF。"""

    if not plan.target_ref:
        return None
    try:
        payload = json.loads(plan.desired_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("HANDOFF_PLAN_DESIRED_PAYLOAD_INVALID") from exc
    if not isinstance(payload, dict):
        raise ValueError("HANDOFF_PLAN_DESIRED_PAYLOAD_INVALID")
    return WorkHandoff.from_mapping(payload)


def write_handoff(process_root: Path, handoff: WorkHandoff) -> Path:
    if not _ID_RE.fullmatch(handoff.work_id) or not _ID_RE.fullmatch(handoff.project_id):
        raise ValueError("handoff work/project identity is invalid")
    if handoff.work_status not in {"paused", "blocked"}:
        raise ValueError("handoff work_status must be paused or blocked")
    if len(handoff.scope_digest) != 64 or not all(
        char in "0123456789abcdefABCDEF" for char in handoff.scope_digest
    ):
        raise ValueError("handoff scope_digest must be one SHA-256 hexadecimal digest")
    _validate_handoff_content(
        release_oid=handoff.release_oid,
        process_oid=handoff.process_oid,
        completed=handoff.completed,
        remaining=handoff.remaining,
        blockers=handoff.blockers,
        next_step=handoff.next_step,
        evidence_refs=handoff.evidence_refs,
    )
    from meta_flow.work.scope import authorize_system_write, classify_system_artifact

    logical_ref = f"works/{handoff.work_id}/HANDOFF.yaml"
    classified = classify_system_artifact(
        handoff.work_id,
        "work.handoff.write",
        logical_ref,
    )
    if classified.namespace is None:
        raise ValueError(classified.reason_code)
    path = handoff_path(process_root, handoff.work_id)
    admitted = authorize_system_write(
        classified.namespace,
        logical_ref,
        target_is_symlink=path.is_symlink(),
    )
    if not admitted.allowed:
        raise ValueError(admitted.reason_code)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    if temporary.exists() or temporary.is_symlink():
        raise FileExistsError(f"temporary handoff path already exists: {temporary}")
    temporary.write_text(dump_yaml(handoff.as_dict()) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def load_handoff(process_root: Path, work_id: str) -> WorkHandoff:
    payload = load_yaml_object(handoff_path(process_root, work_id))
    if payload.get("schema_version") != HANDOFF_SCHEMA_VERSION or payload.get("work_id") != work_id:
        raise ValueError("handoff schema/work_id mismatch")
    allowed = {
        "schema_version",
        "work_id",
        "project_id",
        "work_status",
        "scope_digest",
        "release_oid",
        "process_oid",
        "completed",
        "remaining",
        "blockers",
        "next_step",
        "evidence_refs",
    }
    if set(payload) != allowed:
        raise ValueError("handoff contains missing or unknown fields")
    stored_status = str(payload["work_status"])
    stored_project_id = str(payload["project_id"])
    stored_scope_digest = str(payload["scope_digest"])
    if stored_status not in {"paused", "blocked"}:
        raise ValueError("handoff work_status must be paused or blocked")
    if not _ID_RE.fullmatch(stored_project_id):
        raise ValueError("handoff project_id is invalid")
    if len(stored_scope_digest) != 64 or not all(
        char in "0123456789abcdefABCDEF" for char in stored_scope_digest
    ):
        raise ValueError("handoff scope_digest must be one SHA-256 hexadecimal digest")
    completed = tuple(str(item) for item in payload["completed"])
    remaining = tuple(str(item) for item in payload["remaining"])
    blockers = tuple(str(item) for item in payload["blockers"])
    next_step = str(payload["next_step"])
    evidence_refs = tuple(str(item) for item in payload["evidence_refs"])
    # 不用当前 Work 覆盖暂停时的状态和摘要，否则 scope 漂移无法被恢复预检发现。
    load_work(process_root, work_id)
    archived = WorkHandoff(
        work_id=work_id,
        project_id=stored_project_id,
        work_status=stored_status,
        scope_digest=stored_scope_digest,
        release_oid=str(payload["release_oid"]),
        process_oid=str(payload["process_oid"]),
        completed=completed,
        remaining=remaining,
        blockers=blockers,
        next_step=next_step,
        evidence_refs=evidence_refs,
    )
    _validate_handoff_content(
        release_oid=archived.release_oid,
        process_oid=archived.process_oid,
        completed=archived.completed,
        remaining=archived.remaining,
        blockers=archived.blockers,
        next_step=archived.next_step,
        evidence_refs=archived.evidence_refs,
    )
    return archived


def resume_precheck(
    work: Work,
    handoff: WorkHandoff,
    *,
    actual_release_oid: str,
    actual_process_oid: str,
) -> ResumeDecision:
    reasons: list[str] = []
    if work.work_id != handoff.work_id or work.project_id != handoff.project_id:
        reasons.append("work_identity_mismatch")
    if work.scope.digest != handoff.scope_digest:
        reasons.append("scope_digest_mismatch")
    if actual_release_oid != handoff.release_oid:
        reasons.append("release_oid_mismatch")
    if actual_process_oid != handoff.process_oid:
        reasons.append("process_oid_mismatch")
    if work.status not in {"paused", "blocked"}:
        reasons.append("work_not_paused_or_blocked")
    return ResumeDecision(
        decision="BLOCKED" if reasons else "READY",
        reasons=tuple(reasons),
        work_id=work.work_id,
        expected_release_oid=handoff.release_oid,
        actual_release_oid=actual_release_oid,
        expected_process_oid=handoff.process_oid,
        actual_process_oid=actual_process_oid,
    )
