"""短 Work 交接与 OID/scope 恢复预检。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meta_flow.project.model import is_safe_ref
from meta_flow.project.scale import dump_yaml, load_yaml_object
from meta_flow.work.model import Work, load_work

HANDOFF_SCHEMA_VERSION = 1
_STEP_RE = re.compile(r"^[^\x00\r\n]{1,500}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


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
        len(value) in {40, 64}
        and all(char in "0123456789abcdefABCDEF" for char in value)
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
    path = handoff_path(process_root, handoff.work_id)
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
