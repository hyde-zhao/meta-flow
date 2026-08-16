"""DispatchCorrectionV1 的零写计划与单 ledger 原子 apply。"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol

from meta_flow.project.onboarding_contract import canonical_digest
from meta_flow.project.process_route import _resolve_runtime_ref
from meta_flow.state import event_ledger
from meta_flow.state.projection_transaction import (
    acquire_transaction_lock,
    atomic_replace_bytes,
    ensure_transaction_directory,
    release_transaction_lock,
    validate_transaction_lock,
)

LEDGER_REF = "process/state/AGENT-DISPATCH-LEDGER.ndjson"
CORRECTION_TRANSACTION_LEDGER_REF = (
    "process/state/CORRECTION-TRANSACTION-LEDGER.ndjson"
)
CORRECTION_TRANSACTION_LEDGER_NAME = "CORRECTION-TRANSACTION-LEDGER.ndjson"
CORRECTION_TRANSACTION_LOCK_REL = Path(
    ".meta-flow-runtime/correction-transaction.lock"
)


def _clean(event: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in event.items() if key != "_line_no"}


def _process_oid(project_root: Path) -> str:
    process = _resolve_runtime_ref(project_root.resolve(), "process/PROJECT.yaml").parent
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=process, check=False, capture_output=True, text=True
    )
    value = result.stdout.strip().lower()
    if (
        result.returncode != 0
        or len(value) != 40
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ValueError("process HEAD must be one lowercase 40-hex OID")
    return value


def build_dispatch_correction(
    source: Mapping[str, Any],
    *,
    terminal_result: str,
    reason: str,
    evidence_refs: tuple[str, ...],
    created_at: str,
) -> dict[str, Any]:
    source_payload = _clean(source)
    source_digest = canonical_digest(source_payload)
    identity = {
        "corrects_event_id": str(source_payload.get("event_id") or ""),
        "original_event_digest": source_digest,
        "dispatch_id": str(source_payload.get("dispatch_id") or ""),
        "attempt_id": str(source_payload.get("attempt_id") or ""),
        "terminal_result": terminal_result,
    }
    return {
        "schema_version": 1,
        "event_id": f"DISPATCH-CORRECTION-{canonical_digest(identity)[:32]}",
        "event_type": "dispatch_correction",
        "dispatch_id": identity["dispatch_id"],
        "attempt_id": identity["attempt_id"],
        "corrects_event_id": identity["corrects_event_id"],
        "original_event_digest": source_digest,
        "correction_fields": {"terminal_result": terminal_result},
        "reason": reason,
        "evidence_refs": list(evidence_refs),
        "created_at": created_at,
    }


@dataclass(frozen=True)
class DispatchCorrectionPlanV1:
    source_event_ids: tuple[str, ...]
    process_oid: str
    ledger_preimage: str
    corrections: tuple[dict[str, Any], ...]
    decision: str
    blockers: tuple[str, ...]
    mutation_count: int
    schema_version: int = 1
    kind: str = "DispatchCorrectionPlanV1"

    @property
    def plan_digest(self) -> str:
        return canonical_digest(
            {
                "schema_version": self.schema_version,
                "kind": self.kind,
                "source_event_ids": list(self.source_event_ids),
                "process_oid": self.process_oid,
                "ledger_preimage": self.ledger_preimage,
                "corrections": list(self.corrections),
                "decision": self.decision,
                "blockers": list(self.blockers),
                "mutation_count": self.mutation_count,
            }
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "source_event_ids": list(self.source_event_ids),
            "process_oid": self.process_oid,
            "ledger_preimage": self.ledger_preimage,
            "corrections": list(self.corrections),
            "decision": self.decision,
            "blockers": list(self.blockers),
            "mutation_count": self.mutation_count,
            "plan_digest": self.plan_digest,
        }


def plan_dispatch_corrections(
    project_root: Path,
    *,
    source_event_ids: tuple[str, ...],
    terminal_result: str,
    reason: str,
    evidence_refs: tuple[str, ...],
    process_oid: str | None = None,
    created_at: str | None = None,
) -> DispatchCorrectionPlanV1:
    root = project_root.resolve()
    blockers: list[str] = []
    if not source_event_ids or len(set(source_event_ids)) != len(source_event_ids):
        blockers.append("SOURCE_EVENT_IDS_MUST_BE_NONEMPTY_UNIQUE")
    if not terminal_result.strip():
        blockers.append("TERMINAL_RESULT_REQUIRED")
    if not reason.strip():
        blockers.append("REASON_REQUIRED")
    if not evidence_refs or any(not ref.startswith("process/") for ref in evidence_refs):
        blockers.append("EVIDENCE_REFS_MUST_BE_NONEMPTY_PROCESS_REFS")
    ledger = _resolve_runtime_ref(root, LEDGER_REF)
    before = ledger.read_bytes() if ledger.is_file() and not ledger.is_symlink() else b""
    events, load_errors = event_ledger.load_events(ledger)
    blockers.extend(f"LEDGER_INVALID:{error}" for error in load_errors)
    by_id = {
        str(event.get("event_id") or ""): event
        for event in events
        if str(event.get("event_id") or "")
    }
    existing, correction_errors = event_ledger.dispatch_correction_index(events)
    blockers.extend(f"EXISTING_CORRECTION_INVALID:{error}" for error in correction_errors)
    corrections: list[dict[str, Any]] = []
    timestamp = created_at or datetime.now(UTC).isoformat(timespec="seconds")
    for source_id in source_event_ids:
        source = by_id.get(source_id)
        if source is None:
            blockers.append(f"SOURCE_EVENT_NOT_FOUND:{source_id}")
            continue
        correction = build_dispatch_correction(
            source,
            terminal_result=terminal_result,
            reason=reason,
            evidence_refs=evidence_refs,
            created_at=timestamp,
        )
        current = existing.get(source_id)
        if current is not None:
            if current.get("correction_fields") != correction.get("correction_fields"):
                blockers.append(f"CORRECTION_CONFLICT:{source_id}")
            continue
        simulated = [*events, correction]
        _index, errors = event_ledger.dispatch_correction_index(simulated)
        blockers.extend(f"CORRECTION_INVALID:{error}" for error in errors)
        corrections.append(correction)
    if blockers:
        decision, corrections = "BLOCKED", []
    elif corrections:
        decision = "READY"
    else:
        decision = "NO_CHANGE"
    return DispatchCorrectionPlanV1(
        source_event_ids=source_event_ids,
        process_oid=process_oid or _process_oid(root),
        ledger_preimage=sha256(before).hexdigest(),
        corrections=tuple(corrections),
        decision=decision,
        blockers=tuple(sorted(set(blockers))),
        mutation_count=len(corrections),
    )


def _replace(path: Path, content: bytes) -> None:
    atomic_replace_bytes(path, content)


def apply_dispatch_corrections(
    project_root: Path,
    *,
    plan: DispatchCorrectionPlanV1,
    expected_plan_digest: str,
    expected_process_oid: str | None = None,
    current_process_oid: str | None = None,
) -> dict[str, Any]:
    root = project_root.resolve()
    if expected_plan_digest != plan.plan_digest:
        return {"decision": "BLOCKED", "blockers": ["PLAN_DIGEST_MISMATCH"], "mutation_count": 0}
    if plan.decision == "NO_CHANGE":
        return {"decision": "NO_CHANGE", "blockers": [], "mutation_count": 0}
    if plan.decision != "READY":
        return {"decision": "BLOCKED", "blockers": list(plan.blockers), "mutation_count": 0}
    actual_oid = current_process_oid or _process_oid(root)
    if expected_process_oid is not None and expected_process_oid != plan.process_oid:
        return {
            "decision": "BLOCKED",
            "blockers": ["PROCESS_OID_EXPECTATION_MISMATCH"],
            "mutation_count": 0,
        }
    if actual_oid != plan.process_oid:
        return {"decision": "BLOCKED", "blockers": ["PROCESS_OID_DRIFT"], "mutation_count": 0}
    ledger = _resolve_runtime_ref(root, LEDGER_REF)
    before = ledger.read_bytes()
    if sha256(before).hexdigest() != plan.ledger_preimage:
        return {"decision": "BLOCKED", "blockers": ["LEDGER_PREIMAGE_DRIFT"], "mutation_count": 0}
    text = before.decode("utf-8")
    if text and not text.endswith("\n"):
        text += "\n"
    text += "".join(
        json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n" for event in plan.corrections
    )
    _replace(ledger, text.encode("utf-8"))
    return {
        "schema_version": 1,
        "kind": "DispatchCorrectionReceiptV1",
        "decision": "APPLIED",
        "appended_event_ids": [event["event_id"] for event in plan.corrections],
        "plan_digest": plan.plan_digest,
        "mutation_count": len(plan.corrections),
    }


# The following CR-071 S00 adapter is intentionally in-memory only.  It makes
# future atomicity requirements executable in fixtures without giving this
# implementation lane a path to append a real process ledger event.
@dataclass(frozen=True)
class CorrectionSnapshotV1:
    release_oid: str
    process_oid: str
    source_preimages: tuple[tuple[str, str], ...]
    authority_preimage: str


@dataclass(frozen=True)
class CorrectionPlanV1:
    decision: str
    blockers: tuple[str, ...]
    mutation_count: int
    snapshot: CorrectionSnapshotV1
    completion_digest: str
    candidate_event_digests: tuple[tuple[str, str], ...]
    accepted_event_digest_set: str
    previous_head_digests: tuple[tuple[str, str], ...]
    lineage_digest: str
    head_set_digest: str
    authorization_ref: str = ""

    @property
    def plan_digest(self) -> str:
        return canonical_digest(
            {
                "decision": self.decision,
                "blockers": list(self.blockers),
                "mutation_count": self.mutation_count,
                "snapshot": {
                    "release_oid": self.snapshot.release_oid,
                    "process_oid": self.snapshot.process_oid,
                    "source_preimages": list(self.snapshot.source_preimages),
                    "authority_preimage": self.snapshot.authority_preimage,
                },
                "completion_digest": self.completion_digest,
                "candidate_event_digests": list(self.candidate_event_digests),
                "accepted_event_digest_set": self.accepted_event_digest_set,
                "previous_head_digests": list(self.previous_head_digests),
                "lineage_digest": self.lineage_digest,
                "head_set_digest": self.head_set_digest,
                "authorization_ref": self.authorization_ref,
            }
        )


class AtomicCutoverAdapterV1(Protocol):
    """An isolated adapter must commit both values or raise before either persists."""

    def commit(self, events: tuple[Mapping[str, Any], ...], authority: Mapping[str, Any]) -> None: ...


def plan_typed_corrections(
    snapshot: CorrectionSnapshotV1,
    *,
    completion_digest: str,
    authorization_ref: str = "",
    candidate_events: tuple[Mapping[str, Any], ...] = (),
    previous_head_digests: tuple[tuple[str, str], ...] = (),
    lineage_digest: str = "",
    head_set_digest: str = "",
) -> CorrectionPlanV1:
    """Pure planner: absent independent authorization yields no plan payload."""
    blockers: list[str] = []
    if not authorization_ref.startswith("process/"):
        blockers.append("TYPED_AUTHORIZATION_REQUIRED")
    if len(completion_digest) != 64 or any(ch not in "0123456789abcdef" for ch in completion_digest):
        blockers.append("COMPLETION_EVIDENCE_DRIFT")
    if not snapshot.source_preimages or any(len(item) != 2 or not item[0].startswith("process/") for item in snapshot.source_preimages):
        blockers.append("SOURCE_PREIMAGE_REQUIRED")
    candidate_event_digests = tuple(sorted((str(event.get("event_id") or ""), canonical_digest(event)) for event in candidate_events))
    if not candidate_event_digests or any(not event_id for event_id, _digest in candidate_event_digests):
        blockers.append("CANDIDATE_EVENTS_REQUIRED")
    candidate_event_ids = tuple(event_id for event_id, _digest in candidate_event_digests)
    if len(candidate_event_ids) != len(set(candidate_event_ids)):
        blockers.append("DUPLICATE_CANDIDATE_EVENT")
    accepted_event_digest_set = canonical_digest(list(candidate_event_digests))
    if any(
        not source_id
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
        for source_id, digest in previous_head_digests
    ):
        blockers.append("PREVIOUS_HEAD_BINDING_REQUIRED")
    if any(len(value) != 64 or any(char not in "0123456789abcdef" for char in value) for value in (lineage_digest, head_set_digest)):
        blockers.append("LINEAGE_BINDING_REQUIRED")
    return CorrectionPlanV1(
        decision="BLOCKED" if blockers else "READY",
        blockers=tuple(sorted(blockers)),
        mutation_count=0,
        snapshot=snapshot,
        completion_digest=completion_digest,
        candidate_event_digests=candidate_event_digests if not blockers else (),
        accepted_event_digest_set=accepted_event_digest_set if not blockers else "",
        previous_head_digests=previous_head_digests if not blockers else (),
        lineage_digest=lineage_digest if not blockers else "",
        head_set_digest=head_set_digest if not blockers else "",
        authorization_ref=authorization_ref if not blockers else "",
    )


def apply_typed_corrections(
    plan: CorrectionPlanV1,
    *,
    fresh_snapshot: CorrectionSnapshotV1,
    adapter: AtomicCutoverAdapterV1,
    events: tuple[Mapping[str, Any], ...],
    authority: Mapping[str, Any],
    lineage_digest: str,
    head_set_digest: str,
) -> dict[str, Any]:
    """Fresh-fact guard plus fixture-only atomic adapter; stale/blocked plans write zero."""
    if plan.decision != "READY":
        return {"decision": "BLOCKED", "blockers": list(plan.blockers), "mutation_count": 0}
    if fresh_snapshot != plan.snapshot:
        return {"decision": "BLOCKED", "blockers": ["FRESH_FACT_DRIFT"], "mutation_count": 0}
    if not all(
        len(value) == 64 and all(char in "0123456789abcdef" for char in value)
        for value in (lineage_digest, head_set_digest)
    ):
        return {"decision": "BLOCKED", "blockers": ["LINEAGE_BINDING_INVALID"], "mutation_count": 0}
    candidate_event_digests = tuple(sorted((str(event.get("event_id") or ""), canonical_digest(event)) for event in events))
    if candidate_event_digests != plan.candidate_event_digests:
        return {"decision": "BLOCKED", "blockers": ["CANDIDATE_EVENT_DRIFT"], "mutation_count": 0}
    if lineage_digest != plan.lineage_digest or head_set_digest != plan.head_set_digest:
        return {"decision": "BLOCKED", "blockers": ["LINEAGE_BINDING_DRIFT"], "mutation_count": 0}
    try:
        adapter.commit(events, authority)
    except Exception:
        return {"decision": "BLOCKED", "blockers": ["ATOMIC_CUTOVER_FAILED"], "mutation_count": 0}
    return {
        "decision": "APPLIED",
        "atomic": True,
        "lineage_digest": lineage_digest,
        "head_set_digest": head_set_digest,
        "plan_digest": plan.plan_digest,
        "completion_digest": plan.completion_digest,
        "candidate_event_digests": list(plan.candidate_event_digests),
        "accepted_event_digest_set": plan.accepted_event_digest_set,
        "previous_head_digests": list(plan.previous_head_digests),
        "mutation_count": 0,
    }


@dataclass(frozen=True)
class CorrectionTransactionSnapshotV1:
    release_oid: str
    process_oid: str
    release_dirty_inventory_digest: str
    process_dirty_inventory_digest: str
    source_preimages: tuple[tuple[str, str], ...]
    transaction_ledger_preimage: str


@dataclass(frozen=True)
class CorrectionTransactionPlanV1:
    decision: str
    blockers: tuple[str, ...]
    mutation_count: int
    snapshot: CorrectionTransactionSnapshotV1
    record: Mapping[str, Any] | None
    record_digest: str

    @property
    def plan_digest(self) -> str:
        if self.record is None:
            return ""
        return str(self.record.get("plan_digest") or "")


def _is_sha256(value: object) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _is_oid(value: object) -> bool:
    text = str(value or "")
    return len(text) == 40 and all(character in "0123456789abcdef" for character in text)


def _digest_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def plan_correction_transaction(
    snapshot: CorrectionTransactionSnapshotV1,
    *,
    baseline: tuple[Mapping[str, Any], ...],
    candidate_events: tuple[Mapping[str, Any], ...],
    completion_evidence: tuple[tuple[str, str, str], ...],
    authorization_ref: str,
    authorization_digest: str,
    previous_transaction_id: str = "",
    previous_transaction_digest: str = "",
    created_by: str,
    created_at: str,
) -> CorrectionTransactionPlanV1:
    """Build one deterministic zero-write transaction plan."""

    blockers: list[str] = []
    if not _is_oid(snapshot.release_oid) or not _is_oid(snapshot.process_oid):
        blockers.append("REPOSITORY_PREIMAGE_INVALID")
    if not _is_sha256(snapshot.release_dirty_inventory_digest) or not _is_sha256(
        snapshot.process_dirty_inventory_digest
    ):
        blockers.append("DIRTY_INVENTORY_DIGEST_INVALID")
    source_preimages = tuple(sorted(snapshot.source_preimages))
    if (
        {item[0] for item in source_preimages}
        != {
            "process/state/GATE-LEDGER.ndjson",
            "process/state/AGENT-DISPATCH-LEDGER.ndjson",
        }
        or any(not _is_sha256(item[1]) for item in source_preimages)
    ):
        blockers.append("SOURCE_PREIMAGE_REQUIRED")
    if not _is_sha256(snapshot.transaction_ledger_preimage):
        blockers.append("TRANSACTION_LEDGER_PREIMAGE_REQUIRED")
    if (
        len(completion_evidence) != 2
        or {item[0] for item in completion_evidence}
        != {"STORY-CR071-S00", "STORY-CR071-S08"}
        or any(
            len(item) != 3
            or not item[1].startswith("process/")
            or not _is_sha256(item[2])
            for item in completion_evidence
        )
    ):
        blockers.append("COMPLETION_EVIDENCE_REQUIRED")
    if not authorization_ref.startswith("process/") or not _is_sha256(
        authorization_digest
    ):
        blockers.append("TYPED_AUTHORIZATION_REQUIRED")
    if bool(previous_transaction_id) != bool(previous_transaction_digest) or (
        previous_transaction_digest and not _is_sha256(previous_transaction_digest)
    ):
        blockers.append("PREVIOUS_TRANSACTION_BINDING_INVALID")
    if len(candidate_events) != 3:
        blockers.append("EXACT_THREE_CORRECTIONS_REQUIRED")
    if blockers:
        return CorrectionTransactionPlanV1(
            "BLOCKED", tuple(sorted(set(blockers))), 0, snapshot, None, ""
        )

    completion_by_story = {
        story_id: (evidence_ref, evidence_digest)
        for story_id, evidence_ref, evidence_digest in completion_evidence
    }
    s00_completion_digest = completion_by_story["STORY-CR071-S00"][1]
    lineage = event_ledger.build_correction_lineage(
        candidate_events, baseline, {"digest": s00_completion_digest}
    )
    if lineage.decision != "PASS":
        return CorrectionTransactionPlanV1(
            "BLOCKED", tuple(lineage.errors), 0, snapshot, None, ""
        )

    transaction_identity = canonical_digest(
        {
            "candidate_event_digests": sorted(
                (
                    str(event.get("event_id") or ""),
                    canonical_digest(event),
                )
                for event in candidate_events
            ),
            "release_oid": snapshot.release_oid,
            "process_oid": snapshot.process_oid,
            "source_preimages": source_preimages,
            "transaction_ledger_preimage": snapshot.transaction_ledger_preimage,
            "completion_evidence": sorted(completion_evidence),
            "authorization_ref": authorization_ref,
            "authorization_digest": authorization_digest,
            "previous_transaction_id": previous_transaction_id,
            "previous_transaction_digest": previous_transaction_digest,
        }
    )
    record: dict[str, Any] = {
        "schema_version": 1,
        "transaction_id": f"CORRECTION-TX-{transaction_identity[:32]}",
        "event_type": "correction_transaction",
        "status": "committed",
        "corrections": [dict(event) for event in candidate_events],
        "preimage_release_oid": snapshot.release_oid,
        "preimage_process_oid": snapshot.process_oid,
        "release_dirty_inventory_digest": snapshot.release_dirty_inventory_digest,
        "process_dirty_inventory_digest": snapshot.process_dirty_inventory_digest,
        "source_preimages": [
            {"logical_ref": logical_ref, "digest": digest}
            for logical_ref, digest in source_preimages
        ],
        "transaction_ledger_preimage": snapshot.transaction_ledger_preimage,
        "completion_evidence": [
            {
                "story_id": story_id,
                "evidence_ref": evidence_ref,
                "evidence_digest": evidence_digest,
            }
            for story_id, evidence_ref, evidence_digest in sorted(completion_evidence)
        ],
        "typed_authorization_ref": authorization_ref,
        "typed_authorization_digest": authorization_digest,
        "plan_digest": "",
        "previous_transaction_id": previous_transaction_id,
        "previous_transaction_digest": previous_transaction_digest,
        "lineage_digest": event_ledger.correction_lineage_digest(lineage),
        "head_set_digest": canonical_digest(list(lineage.heads)),
        "accepted_event_digest_set": canonical_digest(
            list(lineage.accepted_event_digests)
        ),
        "created_by": created_by,
        "created_at": created_at,
    }
    record["plan_digest"] = event_ledger.correction_transaction_plan_digest(record)
    completion_digests = {
        evidence_ref: evidence_digest
        for _story_id, evidence_ref, evidence_digest in completion_evidence
    }
    validation = event_ledger.validate_correction_transaction(
        record,
        baseline,
        completion_digests,
        {authorization_ref: authorization_digest},
    )
    if validation.decision != "PASS":
        return CorrectionTransactionPlanV1(
            "BLOCKED", (validation.code,), 0, snapshot, None, ""
        )
    return CorrectionTransactionPlanV1(
        "READY",
        (),
        0,
        snapshot,
        record,
        event_ledger.correction_transaction_record_digest(record),
    )


def _read_regular_or_empty(path: Path) -> bytes:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError("correction transaction ledger target is not a regular file")
    return path.read_bytes() if path.is_file() else b""


def _blocked_transaction_receipt(
    code: str, *, mutation_count: int = 0
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "CorrectionTransactionReceiptV1",
        "decision": "BLOCKED_RECOVERY_REQUIRED" if mutation_count else "BLOCKED",
        "blockers": [code],
        "mutation_count": mutation_count,
    }


def _authority_payload(
    authority: event_ledger.EffectiveCorrectionAuthorityV1,
) -> dict[str, str]:
    return {
        "transaction_id": authority.transaction_id,
        "transaction_record_digest": authority.transaction_record_digest,
        "lineage_digest": authority.lineage_digest,
        "head_set_digest": authority.head_set_digest,
        "accepted_event_digest_set": authority.accepted_event_digest_set,
    }


def apply_correction_transaction(
    plan: CorrectionTransactionPlanV1,
    *,
    transaction_ledger: Path,
    lock_path: Path,
    allowed_state_dir: Path,
    target_logical_ref: str,
    fresh_snapshot: Callable[[], CorrectionTransactionSnapshotV1],
    baseline: tuple[Mapping[str, Any], ...],
    completion_evidence_digests: Mapping[str, str],
    authorization_evidence_digests: Mapping[str, str],
    fault_injector: Callable[[str], None] | None = None,
    replace_bytes: Callable[[Path, bytes], Path] = atomic_replace_bytes,
) -> dict[str, Any]:
    """Commit one validated record with an exact target, lock and fresh recapture."""

    if plan.decision != "READY" or plan.record is None:
        return _blocked_transaction_receipt(
            plan.blockers[0] if plan.blockers else "PLAN_NOT_READY"
        )
    record_validation = event_ledger.validate_correction_transaction(
        plan.record,
        baseline,
        completion_evidence_digests,
        authorization_evidence_digests,
    )
    if (
        record_validation.decision != "PASS"
        or plan.record_digest
        != event_ledger.correction_transaction_record_digest(plan.record)
        or plan.plan_digest
        != event_ledger.correction_transaction_plan_digest(plan.record)
    ):
        return _blocked_transaction_receipt(
            record_validation.code
            if record_validation.decision != "PASS"
            else "PLAN_BINDING_DRIFT"
        )
    if allowed_state_dir.is_symlink():
        return _blocked_transaction_receipt("TRANSACTION_STATE_DIRECTORY_UNSAFE")
    state_dir = allowed_state_dir.resolve()
    expected_target = state_dir / CORRECTION_TRANSACTION_LEDGER_NAME
    expected_lock = state_dir.parent.parent / CORRECTION_TRANSACTION_LOCK_REL
    if (
        target_logical_ref != CORRECTION_TRANSACTION_LEDGER_REF
        or transaction_ledger.absolute() != expected_target.absolute()
        or transaction_ledger.parent.absolute() != allowed_state_dir.absolute()
        or lock_path.absolute() != expected_lock.absolute()
    ):
        return _blocked_transaction_receipt("TRANSACTION_TARGET_NOT_ALLOWED")
    if state_dir.is_symlink() or (state_dir.exists() and not state_dir.is_dir()):
        return _blocked_transaction_receipt("TRANSACTION_STATE_DIRECTORY_UNSAFE")

    def fault(stage: str) -> None:
        if fault_injector is not None:
            fault_injector(stage)

    handle = None
    write_completed = False
    result: dict[str, Any]
    release_error = False
    try:
        fault("before_lock")
        ensure_transaction_directory(lock_path.parent)
        handle = acquire_transaction_lock(lock_path, plan.record_digest[:32])
        validate_transaction_lock(handle, expected_path=lock_path)
        fault("after_lock")
        before = _read_regular_or_empty(transaction_ledger)
        before_digest = _digest_bytes(before)
        before_scan = event_ledger.scan_correction_transactions(
            before,
            baseline,
            completion_evidence_digests,
            authorization_evidence_digests,
        )
        if before_scan.decision != "PASS":
            result = _blocked_transaction_receipt(before_scan.errors[0])
        elif (
            before_scan.authority is not None
            and before_scan.authority.transaction_id
            == str(plan.record.get("transaction_id") or "")
            and before_scan.authority.transaction_record_digest == plan.record_digest
        ):
            result = {
                "schema_version": 1,
                "kind": "CorrectionTransactionReceiptV1",
                "decision": "NO_CHANGE",
                "atomic": True,
                "plan_digest": plan.plan_digest,
                "transaction_id": before_scan.authority.transaction_id,
                "transaction_record_digest": plan.record_digest,
                "authority": _authority_payload(before_scan.authority),
                "pre_ledger_digest": before_digest,
                "post_ledger_digest": before_digest,
                "mutation_count": 0,
            }
        else:
            expected_previous_id = (
                "" if before_scan.authority is None else before_scan.authority.transaction_id
            )
            expected_previous_digest = (
                ""
                if before_scan.authority is None
                else before_scan.authority.transaction_record_digest
            )
            current_snapshot = fresh_snapshot()
            fault("after_fresh_recapture")
            if (
                current_snapshot != plan.snapshot
                or before_digest != plan.snapshot.transaction_ledger_preimage
                or plan.record.get("previous_transaction_id") != expected_previous_id
                or plan.record.get("previous_transaction_digest")
                != expected_previous_digest
            ):
                result = _blocked_transaction_receipt("FRESH_FACT_DRIFT")
            else:
                fault("before_atomic_replace")
                proposed = before + event_ledger.canonical_correction_transaction_line(
                    plan.record
                )
                replace_bytes(transaction_ledger, proposed)
                write_completed = True
                fault("after_atomic_replace")
                after = _read_regular_or_empty(transaction_ledger)
                after_scan = event_ledger.scan_correction_transactions(
                    after,
                    baseline,
                    completion_evidence_digests,
                    authorization_evidence_digests,
                )
                fault("after_reread")
                if (
                    after_scan.decision != "PASS"
                    or after_scan.authority is None
                    or after_scan.authority.transaction_id
                    != str(plan.record.get("transaction_id") or "")
                    or after_scan.authority.transaction_record_digest
                    != plan.record_digest
                ):
                    result = _blocked_transaction_receipt(
                        "POST_WRITE_AUTHORITY_MISMATCH", mutation_count=1
                    )
                else:
                    result = {
                        "schema_version": 1,
                        "kind": "CorrectionTransactionReceiptV1",
                        "decision": "APPLIED",
                        "atomic": True,
                        "plan_digest": plan.plan_digest,
                        "transaction_id": after_scan.authority.transaction_id,
                        "transaction_record_digest": plan.record_digest,
                        "authority": _authority_payload(after_scan.authority),
                        "source_preimages": list(plan.snapshot.source_preimages),
                        "completion_evidence_digests": dict(
                            completion_evidence_digests
                        ),
                        "authorization_evidence_digests": dict(
                            authorization_evidence_digests
                        ),
                        "pre_ledger_digest": before_digest,
                        "post_ledger_digest": _digest_bytes(after),
                        "mutation_count": 1,
                    }
    except Exception:
        result = _blocked_transaction_receipt(
            "ATOMIC_TRANSACTION_FAILED", mutation_count=1 if write_completed else 0
        )
    finally:
        if handle is not None:
            try:
                release_transaction_lock(handle)
            except Exception:
                release_error = True
    if release_error:
        return _blocked_transaction_receipt(
            "LOCK_RELEASE_FAILED", mutation_count=1 if write_completed else 0
        )
    return result


__all__ = [
    "AtomicCutoverAdapterV1",
    "CorrectionPlanV1",
    "CorrectionSnapshotV1",
    "CorrectionTransactionPlanV1",
    "CorrectionTransactionSnapshotV1",
    "CORRECTION_TRANSACTION_LEDGER_REF",
    "DispatchCorrectionPlanV1",
    "apply_correction_transaction",
    "apply_typed_corrections",
    "apply_dispatch_corrections",
    "build_dispatch_correction",
    "plan_dispatch_corrections",
    "plan_correction_transaction",
    "plan_typed_corrections",
]
